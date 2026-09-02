package openai

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime"
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"strings"

	"autoteam-f/protocol-register/internal/fingerprint"
)

var ErrInvalidAuthState = errors.New("invalid auth state")

const maxJSONResponseBytes = 1 << 20

type AuthStep struct {
	PageType              string
	ContinueURL           string
	EmailVerificationMode string
}

type authStepResponse struct {
	Page struct {
		Type    string `json:"type"`
		Payload struct {
			EmailVerificationMode string `json:"email_verification_mode"`
		} `json:"payload"`
	} `json:"page"`
	ContinueURL string `json:"continue_url"`
}

func (r authStepResponse) authStep() (AuthStep, error) {
	step := AuthStep{
		PageType:              strings.TrimSpace(r.Page.Type),
		ContinueURL:           strings.TrimSpace(r.ContinueURL),
		EmailVerificationMode: strings.TrimSpace(r.Page.Payload.EmailVerificationMode),
	}
	if err := validateAuthStep(step); err != nil {
		return AuthStep{}, err
	}
	return step, nil
}

func (r authStepResponse) createAccountStep() (AuthStep, error) {
	step := AuthStep{
		PageType:              strings.TrimSpace(r.Page.Type),
		ContinueURL:           strings.TrimSpace(r.ContinueURL),
		EmailVerificationMode: strings.TrimSpace(r.Page.Payload.EmailVerificationMode),
	}
	if step.PageType != "" && step.PageType != "external_url" {
		return AuthStep{}, fmt.Errorf("%w: unsupported create-account page", ErrInvalidAuthState)
	}
	if !validContinueURL(step.ContinueURL) {
		return AuthStep{}, fmt.Errorf("%w: continuation missing or invalid", ErrInvalidAuthState)
	}
	return step, nil
}

type Client struct {
	HTTP           *http.Client
	BaseURL        string
	ChatGPTBaseURL string
	Profile        fingerprint.Profile
}

func NewClient(httpClient *http.Client, baseURL, chatGPTBaseURL string, profile fingerprint.Profile) *Client {
	if httpClient == nil {
		httpClient = &http.Client{}
	}
	if httpClient.Jar == nil {
		clone := *httpClient
		clone.Jar, _ = cookiejar.New(nil)
		httpClient = &clone
	}
	if baseURL == "" {
		baseURL = "https://auth.openai.com"
	}
	if chatGPTBaseURL == "" {
		chatGPTBaseURL = "https://chatgpt.com"
	}
	return &Client{
		HTTP:           httpClient,
		BaseURL:        strings.TrimRight(baseURL, "/"),
		ChatGPTBaseURL: strings.TrimRight(chatGPTBaseURL, "/"),
		Profile:        profile,
	}
}

func (c *Client) GetCSRF(ctx context.Context) (string, error) {
	var out struct {
		CSRFToken string `json:"csrfToken"`
	}
	if err := c.doJSON(ctx, http.MethodGet, c.ChatGPTBaseURL+"/api/auth/csrf", nil, &out, c.chatGPTAPIHeaders(c.ChatGPTBaseURL+"/auth/login")); err != nil {
		return "", err
	}
	if out.CSRFToken == "" {
		return "", fmt.Errorf("csrf token missing")
	}
	return out.CSRFToken, nil
}

func (c *Client) InitializeOAuth(ctx context.Context, csrf string) (string, error) {
	var out struct {
		URL string `json:"url"`
	}
	form := url.Values{}
	form.Set("csrfToken", csrf)
	form.Set("callbackUrl", c.ChatGPTBaseURL+"/")
	form.Set("json", "true")
	err := c.doForm(ctx, http.MethodPost, c.ChatGPTBaseURL+"/api/auth/signin/openai", form, &out, c.chatGPTAPIHeaders(c.ChatGPTBaseURL+"/auth/login"))
	if err != nil {
		return "", err
	}
	target, err := c.resolveURL(out.URL, c.BaseURL)
	if err != nil {
		return "", err
	}
	if !sameOriginRaw(target, c.BaseURL) {
		return "", fmt.Errorf("%w: oauth host is not allowed", ErrInvalidAuthState)
	}
	if err := c.navigate(ctx, target, c.ChatGPTBaseURL+"/auth/login"); err != nil {
		return "", err
	}
	deviceID := strings.TrimSpace(c.DeviceID())
	if deviceID == "" {
		return "", fmt.Errorf("%w: device cookie missing", ErrInvalidAuthState)
	}
	return deviceID, nil
}

func (c *Client) SigninOpenAI(ctx context.Context, csrf string) error {
	_, err := c.InitializeOAuth(ctx, csrf)
	return err
}

func (c *Client) AuthorizeContinue(ctx context.Context, email, sentinelToken string) (AuthStep, error) {
	if strings.TrimSpace(sentinelToken) == "" {
		return AuthStep{}, ErrSentinelUnavailable
	}
	var out authStepResponse
	headers := c.authAPIHeaders(c.BaseURL + "/create-account")
	headers.Set("openai-sentinel-token", sentinelToken)
	err := c.doJSON(ctx, http.MethodPost, c.BaseURL+"/api/accounts/authorize/continue", map[string]any{"username": map[string]any{"value": email, "kind": "email"}, "screen_hint": "signup"}, &out, headers)
	if err != nil {
		return AuthStep{}, err
	}
	return out.authStep()
}

func (c *Client) RegisterPassword(ctx context.Context, email, password, sentinelToken string) error {
	if strings.TrimSpace(sentinelToken) == "" {
		return ErrSentinelUnavailable
	}
	headers := c.authAPIHeaders(c.BaseURL + "/create-account/password")
	headers.Set("openai-sentinel-token", sentinelToken)
	return c.doJSON(ctx, http.MethodPost, c.BaseURL+"/api/accounts/user/register", map[string]any{"password": password, "username": email}, nil, headers)
}

func (c *Client) BeginPasswordSignup(ctx context.Context) error {
	target, err := c.resolveURL(c.BaseURL+"/create-account/password", c.BaseURL)
	if err != nil {
		return err
	}
	return c.navigate(ctx, target, c.BaseURL+"/email-verification")
}

func (c *Client) SendEmailOTP(ctx context.Context) error {
	return c.doJSON(ctx, http.MethodGet, c.BaseURL+"/api/accounts/email-otp/send", nil, nil, c.authAPIHeaders(c.BaseURL+"/create-account/password"))
}

func (c *Client) ResendEmailOTP(ctx context.Context) error {
	headers := c.authAPIHeaders(c.BaseURL + "/email-verification")
	headers.Set("Content-Type", "application/json")
	return c.doJSON(ctx, http.MethodPost, c.BaseURL+"/api/accounts/email-otp/resend", map[string]any{}, nil, headers)
}

func (c *Client) VerifyEmailOTP(ctx context.Context, code string) (AuthStep, error) {
	var out authStepResponse
	err := c.doJSON(ctx, http.MethodPost, c.BaseURL+"/api/accounts/email-otp/validate", map[string]any{"code": code}, &out, c.authAPIHeaders(c.BaseURL+"/email-verification"))
	if err != nil {
		return AuthStep{}, err
	}
	return out.authStep()
}

func (c *Client) CreateAccount(ctx context.Context, sentinelToken, name, birthdate string) (AuthStep, error) {
	if strings.TrimSpace(sentinelToken) == "" {
		return AuthStep{}, ErrSentinelUnavailable
	}
	if strings.TrimSpace(name) == "" || strings.TrimSpace(birthdate) == "" {
		return AuthStep{}, fmt.Errorf("%w: account profile missing", ErrInvalidAuthState)
	}
	headers := c.authAPIHeaders(c.BaseURL + "/about-you")
	headers.Set("openai-sentinel-token", sentinelToken)
	var out authStepResponse
	err := c.doJSON(ctx, http.MethodPost, c.BaseURL+"/api/accounts/create_account", map[string]any{"name": name, "birthdate": birthdate}, &out, headers)
	if err != nil {
		return AuthStep{}, err
	}
	return out.createAccountStep()
}

func (c *Client) GetAuthSession(ctx context.Context) (map[string]any, error) {
	var out map[string]any
	err := c.doJSON(ctx, http.MethodGet, c.ChatGPTBaseURL+"/api/auth/session", nil, &out, c.chatGPTAPIHeaders(c.ChatGPTBaseURL+"/"))
	return out, err
}

func (c *Client) FollowContinue(ctx context.Context, continueURL string) error {
	target, err := c.resolveURL(continueURL, c.BaseURL)
	if err != nil {
		return err
	}
	return c.navigate(ctx, target, c.BaseURL+"/")
}

func (c *Client) doJSON(ctx context.Context, method, targetURL string, payload any, out any, headers http.Header) error {
	var body io.Reader
	if payload != nil {
		raw, err := json.Marshal(payload)
		if err != nil {
			return fmt.Errorf("encode JSON request: %w", err)
		}
		body = bytes.NewReader(raw)
	}
	headers = headers.Clone()
	if payload != nil {
		headers.Set("Content-Type", "application/json")
	}
	return c.do(ctx, method, targetURL, body, out, headers)
}

func (c *Client) doForm(ctx context.Context, method, targetURL string, form url.Values, out any, headers http.Header) error {
	headers = headers.Clone()
	headers.Set("Content-Type", "application/x-www-form-urlencoded")
	return c.do(ctx, method, targetURL, strings.NewReader(form.Encode()), out, headers)
}

func (c *Client) do(ctx context.Context, method, targetURL string, body io.Reader, out any, headers http.Header) error {
	req, err := http.NewRequestWithContext(ctx, method, targetURL, body)
	if err != nil {
		return fmt.Errorf("build %s request", method)
	}
	for key, values := range headers {
		for _, value := range values {
			req.Header.Add(key, value)
		}
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return fmt.Errorf("%s request failed", method)
	}
	defer resp.Body.Close()
	mediaType, _, contentTypeErr := mime.ParseMediaType(resp.Header.Get("Content-Type"))
	if mediaType == "text/html" || mediaType == "application/xhtml+xml" {
		return ErrChallengeUnavailable
	}
	if contentTypeErr != nil || (mediaType != "application/json" && !strings.HasSuffix(mediaType, "+json")) {
		return ErrInvalidAuthState
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("%s %s: HTTP %d", method, req.URL.Path, resp.StatusCode)
	}
	raw, err := io.ReadAll(io.LimitReader(resp.Body, maxJSONResponseBytes+1))
	if err != nil {
		return fmt.Errorf("%s response read failed", method)
	}
	if len(raw) > maxJSONResponseBytes {
		return fmt.Errorf("%w: JSON response too large", ErrInvalidAuthState)
	}
	if out == nil {
		return nil
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	if err := decoder.Decode(out); err != nil {
		return fmt.Errorf("%w: JSON response invalid", ErrInvalidAuthState)
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return fmt.Errorf("%w: JSON response has trailing data", ErrInvalidAuthState)
	}
	return nil
}

func (c *Client) chatGPTAPIHeaders(referer string) http.Header {
	return APIHeaders(baseOrigin(c.ChatGPTBaseURL), referer, c.Profile)
}

func (c *Client) authAPIHeaders(referer string) http.Header {
	return APIHeaders(baseOrigin(c.BaseURL), referer, c.Profile)
}

func (c *Client) DeviceID() string {
	if c.HTTP == nil || c.HTTP.Jar == nil {
		return ""
	}
	for _, raw := range []string{c.BaseURL, c.ChatGPTBaseURL} {
		parsed, err := url.Parse(raw)
		if err != nil {
			continue
		}
		for _, cookie := range c.HTTP.Jar.Cookies(parsed) {
			if cookie.Name == "oai-did" {
				return cookie.Value
			}
		}
	}
	return ""
}

func (c *Client) resolveURL(raw, relativeBase string) (*url.URL, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return nil, fmt.Errorf("%w: continuation missing", ErrInvalidAuthState)
	}
	base, err := url.Parse(relativeBase)
	if err != nil || base.Scheme == "" || base.Host == "" {
		return nil, fmt.Errorf("%w: configured base URL invalid", ErrInvalidAuthState)
	}
	target, err := url.Parse(raw)
	if err != nil {
		return nil, fmt.Errorf("%w: continuation invalid", ErrInvalidAuthState)
	}
	if !target.IsAbs() {
		target = base.ResolveReference(target)
	}
	if target.User != nil || !c.allowedURL(target) {
		return nil, fmt.Errorf("%w: continuation host is not allowed", ErrInvalidAuthState)
	}
	return target, nil
}

func (c *Client) navigate(ctx context.Context, target *url.URL, referer string) error {
	if target == nil || !c.allowedURL(target) {
		return fmt.Errorf("%w: navigation host is not allowed", ErrInvalidAuthState)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, target.String(), nil)
	if err != nil {
		return fmt.Errorf("%w: navigation request invalid", ErrInvalidAuthState)
	}
	for key, values := range NavigationHeaders(target.String(), referer, c.Profile) {
		for _, value := range values {
			req.Header.Add(key, value)
		}
	}
	redirectClient := *c.HTTP
	previousCheckRedirect := c.HTTP.CheckRedirect
	redirectClient.CheckRedirect = func(next *http.Request, via []*http.Request) error {
		if len(via) >= 10 || !c.allowedURL(next.URL) {
			return fmt.Errorf("%w: redirect is not allowed", ErrInvalidAuthState)
		}
		if len(via) > 0 {
			next.Header.Set("Referer", redirectReferer(via[len(via)-1].URL, next.URL))
			next.Header.Set("Sec-Fetch-Site", navigationFetchSite(next.URL.String(), via[len(via)-1].URL.String()))
		}
		if previousCheckRedirect != nil {
			return previousCheckRedirect(next, via)
		}
		return nil
	}
	resp, err := redirectClient.Do(req)
	if err != nil {
		if errors.Is(err, ErrInvalidAuthState) {
			return ErrInvalidAuthState
		}
		return fmt.Errorf("navigation request failed")
	}
	defer resp.Body.Close()
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 1<<20))
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("navigation request failed: HTTP %d", resp.StatusCode)
	}
	return nil
}

func (c *Client) allowedURL(target *url.URL) bool {
	if target == nil || target.User != nil || (target.Scheme != "http" && target.Scheme != "https") {
		return false
	}
	return sameOriginRaw(target, c.BaseURL) || sameOriginRaw(target, c.ChatGPTBaseURL)
}

func sameOriginRaw(target *url.URL, rawBase string) bool {
	base, err := url.Parse(rawBase)
	if err != nil || target == nil {
		return false
	}
	return strings.EqualFold(target.Scheme, base.Scheme) &&
		strings.EqualFold(target.Hostname(), base.Hostname()) &&
		effectivePort(target) == effectivePort(base)
}

func effectivePort(parsed *url.URL) string {
	if parsed.Port() != "" {
		return parsed.Port()
	}
	if strings.EqualFold(parsed.Scheme, "https") {
		return "443"
	}
	if strings.EqualFold(parsed.Scheme, "http") {
		return "80"
	}
	return ""
}

func redirectReferer(previous, next *url.URL) string {
	if previous == nil || next == nil || (previous.Scheme == "https" && next.Scheme == "http") {
		return ""
	}
	if !sameOriginURL(previous, next) {
		return previous.Scheme + "://" + previous.Host + "/"
	}
	copy := *previous
	copy.User = nil
	copy.RawQuery = ""
	copy.ForceQuery = false
	copy.Fragment = ""
	return copy.String()
}

func sameOriginURL(left, right *url.URL) bool {
	return left != nil && right != nil &&
		strings.EqualFold(left.Scheme, right.Scheme) &&
		strings.EqualFold(left.Hostname(), right.Hostname()) &&
		effectivePort(left) == effectivePort(right)
}

func validateAuthStep(step AuthStep) error {
	switch step.PageType {
	case "", "create_account_password", "email_otp_verification", "about_you":
	default:
		return fmt.Errorf("%w: unsupported page", ErrInvalidAuthState)
	}
	if !validContinueURL(step.ContinueURL) {
		return fmt.Errorf("%w: continuation missing or invalid", ErrInvalidAuthState)
	}
	return nil
}

func validContinueURL(raw string) bool {
	parsed, err := url.Parse(raw)
	if err != nil {
		return false
	}
	if parsed.IsAbs() {
		return (parsed.Scheme == "http" || parsed.Scheme == "https") && parsed.Host != ""
	}
	return parsed.Host == "" && strings.HasPrefix(parsed.Path, "/")
}

func baseOrigin(raw string) string {
	parsed, err := url.Parse(raw)
	if err != nil || parsed.Scheme == "" || parsed.Host == "" {
		return strings.TrimRight(raw, "/")
	}
	return parsed.Scheme + "://" + parsed.Host
}
