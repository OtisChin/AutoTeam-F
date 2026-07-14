package paypal

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/url"
	"regexp"
	"strings"
	"time"

	http "github.com/bogdanfinn/fhttp"
	tlsclient "github.com/bogdanfinn/tls-client"
)

type StripeSession struct {
	chatClient     tlsclient.HttpClient
	geoClient      tlsclient.HttpClient
	stripeClient   tlsclient.HttpClient
	redirectClient tlsclient.HttpClient

	chatProxyURL   string
	geoProxyURL    string
	stripeProxyURL string
	proxyPlan      ProxyPlan

	gptToken          GPTToken
	settings          CheckoutSettings
	logf              func(string, ...any)
	csID              string
	deviceID          string
	processorEntity   string
	entityExplicit    bool
	payURL            string
	fpGUID            string
	fpMUID            string
	fpSID             string
	stripeJSID        string
	clientSessionID   string
	geoCountry        string
	geoRegion         string
	geoCity           string
	geoPostal         string
	geoIP             string
	stopAtPMRedirects bool
	pkLive            string
	clientSecret      string
}

func NewStripeSession(
	gpt GPTToken,
	mode string,
	jpProxy string,
	usProxy string,
	logf func(string, ...any),
) (*StripeSession, error) {
	if logf == nil {
		logf = func(string, ...any) {}
	}
	settings := CheckoutSettingsForMode(mode)
	plan := ProxyPlanForMode(settings.Mode, jpProxy, usProxy)
	jar := tlsclient.NewCookieJar()

	chatClient, err := newTLSSession(withCookieJar(jar), withProxyURL(plan.ChatGPT), withTimeoutSeconds(60))
	if err != nil {
		return nil, fmt.Errorf("chatgpt client: %s", redactProxyText(err.Error(), jpProxy, usProxy))
	}
	stripeClient, err := newTLSSession(withCookieJar(jar), withProxyURL(plan.Stripe), withTimeoutSeconds(60))
	if err != nil {
		return nil, fmt.Errorf("stripe client: %s", redactProxyText(err.Error(), jpProxy, usProxy))
	}
	redirectClient, err := newTLSSession(
		withCookieJar(jar),
		withProxyURL(plan.Stripe),
		withTimeoutSeconds(60),
		withNotFollowRedirects(),
	)
	if err != nil {
		return nil, fmt.Errorf("redirect client: %s", redactProxyText(err.Error(), jpProxy, usProxy))
	}

	logf("[stripe] JP 代理: %s", maskProxyURL(plan.ChatGPT))
	if settings.UseUSProxy && plan.Stripe != "" && plan.Stripe != plan.ChatGPT {
		logf("[stripe] US 代理(PM/confirm/poll): %s", maskProxyURL(plan.Stripe))
	}

	return &StripeSession{
		chatClient:      chatClient,
		geoClient:       chatClient,
		stripeClient:    stripeClient,
		redirectClient:  redirectClient,
		chatProxyURL:    plan.ChatGPT,
		geoProxyURL:     plan.Geo,
		stripeProxyURL:  plan.Stripe,
		proxyPlan:       plan,
		gptToken:        gpt,
		settings:        settings,
		logf:            logf,
		deviceID:        firstNonEmpty(gpt.DeviceID, newID()),
		processorEntity: settings.ProcessorEntity,
		fpGUID:          newID(),
		fpMUID:          newID(),
		fpSID:           newID(),
		stripeJSID:      newID(),
		clientSessionID: newID(),
		geoCountry:      "JP",
	}, nil
}

func (s *StripeSession) PayURL() string {
	return s.payURL
}

func (s *StripeSession) SetProcessorEntity(entity string) {
	if strings.TrimSpace(entity) != "" {
		s.processorEntity = strings.TrimSpace(entity)
		s.entityExplicit = true
	}
}

func (s *StripeSession) SetStopAtPMRedirects(stop bool) {
	s.stopAtPMRedirects = stop
}

func (s *StripeSession) ExtractPayPalLink() (*PayPalLink, error) {
	s.seedCookies()
	s.probeGeo()
	s.logf("[stripe] Step 1: warmup")
	_ = s.warmup()
	s.logf("[stripe] Step 2: 创建 checkout")
	if err := s.createCheckout(); err != nil {
		return nil, fmt.Errorf("创建 checkout 失败: %w", err)
	}
	s.logf("[stripe] checkout cs=%s", s.csID)
	s.logf("[stripe] Step 3: stripe init")
	if err := s.stripeInit(); err != nil {
		return nil, fmt.Errorf("stripe init 失败: %w", err)
	}
	s.logf("[stripe] Step 4: PayPal PM")
	link, err := requirePayPalPMResult(s.createPayPalPM())
	if err != nil {
		return nil, err
	}
	if link != nil {
		if s.stopAtPMRedirects || strings.Contains(link.FullURL, "paypal.com") {
			return link, nil
		}
	}
	s.logf("[stripe] Step 5: stripe confirm")
	if link, err := s.pollForPayPalRedirect(); err == nil && link != nil {
		return link, nil
	}
	s.logf("[stripe] Step 6: chatgpt approve")
	if err := s.chatgptApprove(); err != nil {
		s.logf("[stripe] approve err=%v", err)
	}
	s.logf("[stripe] Step 7: poll redirect")
	return s.pollForPayPalRedirect()
}

func requirePayPalPMResult(link *PayPalLink, err error) (*PayPalLink, error) {
	if err != nil {
		return nil, fmt.Errorf("PayPal PM failed: %w", err)
	}
	return link, nil
}

func (s *StripeSession) clientForURL(rawURL string) tlsclient.HttpClient {
	u, err := url.Parse(rawURL)
	if err != nil {
		return s.chatClient
	}
	host := strings.ToLower(u.Hostname())
	if host == "ipinfo.io" {
		return s.geoClient
	}
	if host == "pm-redirects.stripe.com" {
		return s.redirectClient
	}
	if host == "api.stripe.com" || host == "checkout.stripe.com" || strings.HasSuffix(host, ".stripe.com") {
		return s.stripeClient
	}
	return s.chatClient
}

func (s *StripeSession) redactError(err error) error {
	if err == nil {
		return nil
	}
	return errors.New(redactProxyText(err.Error(), s.chatProxyURL, s.geoProxyURL, s.stripeProxyURL))
}

func (s *StripeSession) warmup() error {
	req, err := http.NewRequest("GET", "https://chatgpt.com/backend-api/sentinel/ping", nil)
	if err != nil {
		return err
	}
	req.Header = s.chatgptHeaders("/backend-api/sentinel/ping")
	resp, err := s.chatClient.Do(req)
	if err != nil {
		return s.redactError(err)
	}
	defer resp.Body.Close()
	s.logf("[stripe] warmup status=%d (token)", resp.StatusCode)
	return nil
}

func (s *StripeSession) createCheckout() error {
	payload, err := json.Marshal(CheckoutPayload(s.settings))
	if err != nil {
		return err
	}
	s.logf(
		"[stripe] createCheckout body: country=%s currency=%s ui_mode=%s entity(default)=%s",
		s.settings.Country,
		s.settings.Currency,
		s.settings.UIMode,
		s.processorEntity,
	)
	req, err := http.NewRequest(
		"POST",
		"https://chatgpt.com/backend-api/payments/checkout",
		bytes.NewReader(payload),
	)
	if err != nil {
		return err
	}
	req.Header = s.chatgptHeaders("/backend-api/payments/checkout")
	req.Header.Set("content-type", "application/json")
	resp, err := s.chatClient.Do(req)
	if err != nil {
		return s.redactError(err)
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 300 {
		return fmt.Errorf("status %d: %s", resp.StatusCode, truncate(string(data), 500))
	}
	var response map[string]any
	if err := json.Unmarshal(data, &response); err != nil {
		return err
	}
	s.applyCheckoutResponse(response)
	if s.payURL == "" && s.csID != "" {
		s.payURL = "https://pay.openai.com/c/pay/" + s.csID
	}
	s.logf("[stripe] checkout session: %s, body=%s", s.csID, truncate(string(data), 300))
	if s.csID == "" {
		return fmt.Errorf("invalid checkout session: %s", truncate(string(data), 300))
	}
	return nil
}

func (s *StripeSession) applyCheckoutResponse(response map[string]any) {
	s.csID = firstNonEmpty(stringValue(response["checkout_session_id"]), stringValue(response["id"]))
	s.payURL = firstNonEmpty(
		stringValue(response["stripe_hosted_url"]),
		stringValue(response["url"]),
		stringValue(response["checkout_url"]),
		stringValue(response["paypal_redirect_url"]),
	)
	s.clientSecret = stringValue(response["client_secret"])
	s.pkLive = stringValue(response["stripe_publishable_key"])
	if !s.entityExplicit {
		if entity := stringValue(response["processor_entity"]); entity != "" {
			s.processorEntity = entity
		}
	}
}

func (s *StripeSession) stripeInit() error {
	if s.payURL == "" {
		return errors.New("no checkout URL")
	}
	resp, err := s.doReq("GET", s.payURL, nil, nil)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	return s.applyStripeInitReader(resp.Body)
}

func (s *StripeSession) applyStripeInitReader(reader io.Reader) error {
	data, err := io.ReadAll(reader)
	if err != nil {
		return fmt.Errorf("read stripe init response: %w", err)
	}
	return s.applyStripeInit(string(data))
}

func (s *StripeSession) applyStripeInit(text string) error {
	amount, err := extractAmountFromInit(text)
	if err != nil {
		return fmt.Errorf("checkout amount validation failed: %w", err)
	}
	s.pkLive = firstNonEmpty(s.pkLive, firstMatch(text, `pk_live_[A-Za-z0-9_]+`))
	s.clientSecret = firstNonEmpty(s.clientSecret, firstMatch(text, `seti_[A-Za-z0-9_]+_secret_[A-Za-z0-9_]+`))
	s.logf("[stripe] init: currency=%s amount=%d", s.settings.Currency, amount)
	s.logf("[stripe] checkout publishable_key=%s", s.pkLive)
	if amount > 0 {
		return fmt.Errorf("non-zero checkout amount: %d %s", amount, s.settings.Currency)
	}
	return nil
}

func (s *StripeSession) createPayPalPM() (*PayPalLink, error) {
	ident := randomIdentity(
		s.settings.Country,
		s.geoCountry,
		s.geoRegion,
		s.geoCity,
		s.geoPostal,
		s.gptToken.Email,
	)
	s.logf(
		"[stripe] PM billing: name=%q email=%s country=%s state=%s city=%s postal=%s line1=%s",
		ident.Name,
		ident.Email,
		ident.Country,
		ident.State,
		ident.City,
		ident.PostalCode,
		ident.Line1,
	)
	form := url.Values{}
	form.Set("type", "paypal")
	form.Set("billing_details[name]", ident.Name)
	form.Set("billing_details[email]", ident.Email)
	form.Set("billing_details[address][country]", ident.Country)
	form.Set("billing_details[address][state]", ident.State)
	form.Set("billing_details[address][city]", ident.City)
	form.Set("billing_details[address][postal_code]", ident.PostalCode)
	form.Set("billing_details[address][line1]", ident.Line1)
	if ident.Phone != "" {
		form.Set("billing_details[phone]", ident.Phone)
	}
	form.Set("guid", s.fpGUID)
	form.Set("muid", s.fpMUID)
	form.Set("sid", s.fpSID)
	form.Set("payment_user_agent", "stripe.js/30777f36-1141-46bc-a435-f4bec3472ed5; stripe-js-v3/30777f36-1141-46bc-a435-f4bec3472ed5")
	form.Set("expected_payment_method_type", "paypal")
	if s.pkLive != "" {
		form.Set("key", s.pkLive)
	}
	resp, err := s.doReq(
		"POST",
		"https://api.stripe.com/v1/payment_methods",
		strings.NewReader(form.Encode()),
		formHeaders(),
	)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(resp.Body)
	if raw := extractRedirectURL(data); raw != "" {
		s.logf("[stripe] PayPal redirect: %s", raw)
		return parsePayPalLink(raw)
	}
	if resp.StatusCode >= 300 {
		return nil, fmt.Errorf("pm: %s, body=%s", resp.Status, truncate(string(data), 500))
	}
	var response map[string]any
	if json.Unmarshal(data, &response) == nil {
		if id := stringValue(response["id"]); id != "" {
			return s.confirmSetupIntentWithPM(id)
		}
	}
	return nil, nil
}

func (s *StripeSession) confirmSetupIntentWithPM(paymentMethodID string) (*PayPalLink, error) {
	if s.clientSecret == "" || paymentMethodID == "" {
		return nil, nil
	}
	setupIntentID := strings.Split(s.clientSecret, "_secret_")[0]
	if setupIntentID == "" {
		return nil, nil
	}
	form := setupIntentConfirmValues(s.clientSecret, paymentMethodID, s.pkLive, s.clientSessionID)
	resp, err := s.doReq(
		"POST",
		"https://api.stripe.com/v1/setup_intents/"+urlEncode(setupIntentID)+"/confirm",
		strings.NewReader(form.Encode()),
		formHeaders(),
	)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(resp.Body)
	if raw := extractRedirectURL(data); raw != "" {
		s.logf("[stripe] confirm | redirect: %s", raw)
		if s.stopAtPMRedirects {
			return parsePayPalLink(raw)
		}
		if strings.Contains(raw, "pm-redirects.stripe.com") {
			followed, followErr := s.followAnyRedirect(raw)
			if followErr == nil && followed != "" {
				return parsePayPalLink(followed)
			}
		}
		return parsePayPalLink(raw)
	}
	if resp.StatusCode >= 300 {
		return nil, fmt.Errorf("confirm status %d: %s", resp.StatusCode, truncate(string(data), 500))
	}
	return nil, nil
}

func (s *StripeSession) pollForPayPalRedirect() (*PayPalLink, error) {
	if s.clientSecret == "" && !strings.Contains(s.payURL, "pm-redirects.stripe.com") {
		return nil, errors.New("no PayPal redirect source: missing pm-redirect URL and client secret")
	}
	last := ""
	for attempt := 1; attempt <= 60; attempt++ {
		time.Sleep(time.Second)
		raw, err := s.resolvePayPalLink()
		if err == nil && raw != "" {
			s.logf("[stripe] poll #%d: pm-redirects: %s", attempt, raw)
			return parsePayPalLink(raw)
		}
		if err != nil {
			last = err.Error()
		}
		s.logf("[stripe] poll #%d: setup_intent.status=%s", attempt, last)
	}
	return nil, fmt.Errorf("PayPal redirect not found (last=%s)", last)
}

func (s *StripeSession) resolvePayPalLink() (string, error) {
	if s.payURL != "" && strings.Contains(s.payURL, "pm-redirects.stripe.com") {
		if s.stopAtPMRedirects {
			return s.payURL, nil
		}
		return s.followAnyRedirect(s.payURL)
	}
	if s.clientSecret != "" {
		rawURL := "https://api.stripe.com/v1/payment_pages/" + urlEncode(s.clientSecret)
		resp, err := s.doReq("GET", rawURL, nil, nil)
		if err != nil {
			return "", err
		}
		defer resp.Body.Close()
		data, _ := io.ReadAll(resp.Body)
		return extractRedirectURL(data), nil
	}
	return "", errors.New("no payment page")
}

func (s *StripeSession) followAnyRedirect(raw string) (string, error) {
	last := raw
	for hop := 1; hop <= 10; hop++ {
		resp, err := s.doReq("GET", last, nil, nil)
		if err != nil {
			return "", err
		}
		location := resp.Header.Get("Location")
		resp.Body.Close()
		s.logf("[stripe] redirect hop %d: %d | %s", hop, resp.StatusCode, location)
		if location == "" {
			break
		}
		if strings.Contains(location, "paypal.com") {
			s.logf("[stripe] paypal.com: %s", location)
			return location, nil
		}
		if strings.HasPrefix(location, "/") {
			previous, _ := url.Parse(last)
			location = previous.Scheme + "://" + previous.Host + location
		}
		last = location
	}
	if isPayPalURL(last) {
		return last, nil
	}
	return "", fmt.Errorf("redirect: %s", last)
}

func (s *StripeSession) chatgptApprove() error {
	form := url.Values{}
	form.Set("checkout_session_id", s.csID)
	form.Set("processor_entity", s.processorEntity)
	form.Set("client_attribution_metadata[client_session_id]", s.clientSessionID)
	form.Set("client_attribution_metadata[merchant_integration_source]", "custom_checkout_manual_approval_1")
	form.Set("client_attribution_metadata[merchant_integration_version]", "2020-08-27;custom_checkout_beta=v1")
	req, err := http.NewRequest(
		"POST",
		"https://chatgpt.com/backend-api/payments/checkout/approve",
		strings.NewReader(form.Encode()),
	)
	if err != nil {
		return err
	}
	req.Header = s.chatgptHeaders("/backend-api/payments/checkout/approve")
	req.Header.Set("content-type", "application/x-www-form-urlencoded")
	resp, err := s.chatClient.Do(req)
	if err != nil {
		return s.redactError(err)
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(resp.Body)
	s.logf("[stripe] chatgpt approve status=%d body=%s", resp.StatusCode, truncate(string(data), 300))
	if resp.StatusCode >= 300 {
		return fmt.Errorf("approve http %d: %s", resp.StatusCode, truncate(string(data), 500))
	}
	return nil
}

func (s *StripeSession) chatgptHeaders(targetPath string) http.Header {
	headers := http.Header{}
	headers.Set("authorization", "Bearer "+s.gptToken.AccessToken)
	headers.Set("content-type", "application/json")
	headers.Set("accept", "application/json")
	headers.Set("user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/144 Safari/537.36")
	headers.Set("origin", "https://chatgpt.com")
	headers.Set("referer", "https://chatgpt.com/")
	headers.Set("oai-did", s.deviceID)
	headers.Set("x-openai-target-path", targetPath)
	return headers
}

func (s *StripeSession) doReq(method, rawURL string, body io.Reader, headers http.Header) (*http.Response, error) {
	var bodyData []byte
	if body != nil {
		bodyData, _ = io.ReadAll(body)
	}
	var lastErr error
	for attempt := 1; attempt <= 3; attempt++ {
		resp, err := s.doReqOnce(method, rawURL, bodyData, headers)
		if err == nil {
			return resp, nil
		}
		lastErr = s.redactError(err)
		s.logf("[net-retry %d/3] %s %s: %v", attempt, method, rawURL, lastErr)
	}
	return nil, lastErr
}

func (s *StripeSession) doReqOnce(
	method string,
	rawURL string,
	bodyData []byte,
	headers http.Header,
) (*http.Response, error) {
	var body io.Reader
	if bodyData != nil {
		body = bytes.NewReader(bodyData)
	}
	req, err := http.NewRequest(method, rawURL, body)
	if err != nil {
		return nil, err
	}
	if headers != nil {
		req.Header = headers.Clone()
	}
	if req.Header.Get("user-agent") == "" {
		req.Header.Set("user-agent", "Mozilla/5.0")
	}
	if req.Header.Get("accept-language") == "" {
		req.Header.Set("accept-language", "en-US,en;q=0.9")
	}
	return s.clientForURL(rawURL).Do(req)
}

func (s *StripeSession) seedCookies() {
	for _, raw := range []string{"https://chatgpt.com", "https://pay.openai.com"} {
		u, err := url.Parse(raw)
		if err != nil {
			continue
		}
		cookies := []*http.Cookie{
			{Name: "oai-did", Value: s.deviceID, Domain: u.Host, Path: "/"},
			{Name: "consent[terms_of_service]", Value: "accepted", Domain: u.Host, Path: "/"},
		}
		if s.gptToken.SessionToken != "" {
			cookies = append(cookies, &http.Cookie{
				Name:   "__Secure-next-auth.session-token",
				Value:  s.gptToken.SessionToken,
				Domain: u.Host,
				Path:   "/",
			})
		}
		s.chatClient.SetCookies(u, cookies)
		s.stripeClient.SetCookies(u, cookies)
		s.redirectClient.SetCookies(u, cookies)
	}
}

func (s *StripeSession) probeGeo() {
	resp, err := s.geoClient.Get("https://ipinfo.io/json")
	if err != nil {
		s.logf("[geo] 查询 IP 地理失败 (status=0, err=%v), 使用默认 JP", s.redactError(err))
		s.geoCountry = firstNonEmpty(s.geoCountry, "JP")
		return
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(resp.Body)
	var response map[string]any
	if err := json.Unmarshal(data, &response); err != nil {
		s.geoCountry = firstNonEmpty(s.geoCountry, "JP")
		return
	}
	s.geoIP = stringValue(response["ip"])
	s.geoCountry = firstNonEmpty(stringValue(response["country"]), s.geoCountry, "JP")
	s.geoRegion = firstNonEmpty(stringValue(response["region"]), s.geoRegion)
	s.geoCity = firstNonEmpty(stringValue(response["city"]), s.geoCity)
	s.geoPostal = firstNonEmpty(stringValue(response["postal"]), s.geoPostal)
	s.logf(
		"[geo] IP=%s country=%s region=%s city=%s postal=%s",
		s.geoIP,
		s.geoCountry,
		s.geoRegion,
		s.geoCity,
		s.geoPostal,
	)
}

func formHeaders() http.Header {
	headers := http.Header{}
	headers.Set("content-type", "application/x-www-form-urlencoded")
	headers.Set("accept", "application/json")
	headers.Set("origin", "https://checkout.stripe.com")
	headers.Set("referer", "https://checkout.stripe.com")
	headers.Set("user-agent", "Mozilla/5.0")
	return headers
}

func extractRedirectFromNextAction(value any) string {
	if object, ok := value.(map[string]any); ok {
		if nextAction, ok := object["next_action"].(map[string]any); ok {
			if raw := deepSearchRedirectURL(nextAction); raw != "" {
				return raw
			}
		}
	}
	return deepSearchRedirectURL(value)
}

func extractRedirectURL(data []byte) string {
	text := string(data)
	if raw := firstMatch(text, `https://pm-redirects\.stripe\.com[^"\\\s]+`); raw != "" {
		return strings.ReplaceAll(raw, `\u0026`, "&")
	}
	if raw := firstMatch(text, `https://www\.paypal\.com/agreements/approve\?ba_token=[^"\\\s]+`); raw != "" {
		return strings.ReplaceAll(raw, `\u0026`, "&")
	}
	var value any
	if json.Unmarshal(data, &value) == nil {
		return extractRedirectFromNextAction(value)
	}
	return ""
}

func deepSearchRedirectURL(value any) string {
	switch typed := value.(type) {
	case map[string]any:
		for key, child := range typed {
			if strings.Contains(strings.ToLower(key), "redirect") {
				if raw := stringValue(child); isPayPalURL(raw) {
					return raw
				}
			}
			if raw := deepSearchRedirectURL(child); raw != "" {
				return raw
			}
		}
	case []any:
		for _, child := range typed {
			if raw := deepSearchRedirectURL(child); raw != "" {
				return raw
			}
		}
	case string:
		if isPayPalURL(typed) {
			return typed
		}
	}
	return ""
}

func extractAmountFromInit(text string) (int, error) {
	ranges := balancedJSONObjects(text)
	outside := []byte(text)
	amounts := make([]int64, 0, 1)
	for _, objectRange := range ranges {
		for index := objectRange.start; index < objectRange.end; index++ {
			outside[index] = ' '
		}
		candidate := text[objectRange.start:objectRange.end]
		if !containsKnownAmountName(candidate) {
			continue
		}
		values, err := decodeAmountObject(candidate)
		if err != nil {
			return 0, fmt.Errorf("invalid checkout amount object: %w", err)
		}
		amounts = append(amounts, values...)
	}
	if containsKnownAmountName(string(outside)) {
		return 0, errors.New("checkout amount field is not inside a complete JSON object")
	}
	if len(amounts) == 0 {
		return 0, errors.New("checkout amount field missing")
	}
	if len(amounts) != 1 {
		return 0, fmt.Errorf("multiple checkout amount values found: %d", len(amounts))
	}
	if amounts[0] > int64(^uint(0)>>1) {
		return 0, fmt.Errorf("checkout amount is too large: %d", amounts[0])
	}
	return int(amounts[0]), nil
}

type jsonObjectRange struct {
	start int
	end   int
}

func balancedJSONObjects(text string) []jsonObjectRange {
	ranges := make([]jsonObjectRange, 0, 1)
	start := -1
	depth := 0
	inString := false
	escaped := false
	for index := 0; index < len(text); index++ {
		character := text[index]
		if depth == 0 {
			if character == '{' {
				start = index
				depth = 1
				inString = false
				escaped = false
			}
			continue
		}
		if inString {
			if escaped {
				escaped = false
				continue
			}
			if character == '\\' {
				escaped = true
				continue
			}
			if character == '"' {
				inString = false
			}
			continue
		}
		switch character {
		case '"':
			inString = true
		case '{':
			depth++
		case '}':
			depth--
			if depth == 0 {
				ranges = append(ranges, jsonObjectRange{start: start, end: index + 1})
				start = -1
			}
		}
	}
	return ranges
}

var knownAmountNames = []string{"amount_total", "amount_due", "total_amount_due"}

func containsKnownAmountName(text string) bool {
	for _, name := range knownAmountNames {
		if strings.Contains(text, name) {
			return true
		}
	}
	return false
}

func isKnownAmountName(name string) bool {
	for _, known := range knownAmountNames {
		if name == known {
			return true
		}
	}
	return false
}

func decodeAmountObject(raw string) ([]int64, error) {
	decoder := json.NewDecoder(strings.NewReader(raw))
	decoder.UseNumber()
	opening, err := decoder.Token()
	if err != nil {
		return nil, err
	}
	delimiter, ok := opening.(json.Delim)
	if !ok || delimiter != '{' {
		return nil, errors.New("checkout amount container is not a JSON object")
	}
	amounts := make([]int64, 0, 1)
	if err := walkJSONObject(decoder, &amounts); err != nil {
		return nil, err
	}
	if trailing, err := decoder.Token(); err != io.EOF {
		if err != nil {
			return nil, err
		}
		return nil, fmt.Errorf("unexpected trailing JSON token %v", trailing)
	}
	return amounts, nil
}

func walkJSONObject(decoder *json.Decoder, amounts *[]int64) error {
	for decoder.More() {
		keyToken, err := decoder.Token()
		if err != nil {
			return err
		}
		key, ok := keyToken.(string)
		if !ok {
			return fmt.Errorf("JSON object key has type %T", keyToken)
		}
		if err := walkJSONValue(decoder, key, amounts); err != nil {
			return err
		}
	}
	closing, err := decoder.Token()
	if err != nil {
		return err
	}
	if delimiter, ok := closing.(json.Delim); !ok || delimiter != '}' {
		return fmt.Errorf("unexpected JSON object terminator %v", closing)
	}
	return nil
}

func walkJSONArray(decoder *json.Decoder, amounts *[]int64) error {
	for decoder.More() {
		if err := walkJSONValue(decoder, "", amounts); err != nil {
			return err
		}
	}
	closing, err := decoder.Token()
	if err != nil {
		return err
	}
	if delimiter, ok := closing.(json.Delim); !ok || delimiter != ']' {
		return fmt.Errorf("unexpected JSON array terminator %v", closing)
	}
	return nil
}

func walkJSONValue(decoder *json.Decoder, key string, amounts *[]int64) error {
	value, err := decoder.Token()
	if err != nil {
		return err
	}
	if isKnownAmountName(key) {
		number, ok := value.(json.Number)
		if !ok {
			return fmt.Errorf("checkout amount %s must be a JSON number, got %T", key, value)
		}
		amount, err := number.Int64()
		if err != nil {
			return fmt.Errorf("checkout amount %s is not an integer: %w", key, err)
		}
		if amount < 0 {
			return fmt.Errorf("checkout amount %s is negative: %d", key, amount)
		}
		*amounts = append(*amounts, amount)
		return nil
	}
	delimiter, ok := value.(json.Delim)
	if !ok {
		return nil
	}
	switch delimiter {
	case '{':
		return walkJSONObject(decoder, amounts)
	case '[':
		return walkJSONArray(decoder, amounts)
	default:
		return fmt.Errorf("unexpected JSON delimiter %q", delimiter)
	}
}

func stringValue(value any) string {
	switch typed := value.(type) {
	case string:
		return typed
	case fmt.Stringer:
		return typed.String()
	case json.Number:
		return typed.String()
	default:
		return ""
	}
}

func firstMatch(value, pattern string) string {
	return regexp.MustCompile(pattern).FindString(value)
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if value != "" {
			return value
		}
	}
	return ""
}
