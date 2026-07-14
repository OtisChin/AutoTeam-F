package paypal

import (
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"strings"
	"time"

	"autotoken-pplink/internal/proxyutil"
)

type GPTToken struct {
	AccessToken  string
	SessionToken string
	DeviceID     string
	Email        string
}

type PayPalLink struct {
	FullURL string
	BAToken string
	Token   string
	SSRT    string
	Country string
	Locale  string
}

type CheckoutSettings struct {
	Mode            string
	Country         string
	Currency        string
	UIMode          string
	ProcessorEntity string
	UseUSProxy      bool
}

func CheckoutSettingsForMode(mode string) CheckoutSettings {
	switch strings.ToLower(strings.TrimSpace(mode)) {
	case "eu":
		return CheckoutSettings{
			Mode:            "eu",
			Country:         "FR",
			Currency:        "EUR",
			UIMode:          "custom",
			ProcessorEntity: "openai_ie",
		}
	case "br":
		return CheckoutSettings{
			Mode:            "br",
			Country:         "BR",
			Currency:        "BRL",
			UIMode:          "custom",
			ProcessorEntity: "openai_ie",
		}
	default:
		return CheckoutSettings{
			Mode:            "us",
			Country:         "US",
			Currency:        "USD",
			UIMode:          "hosted",
			ProcessorEntity: "openai_llc",
			UseUSProxy:      true,
		}
	}
}

type ProxyPlan struct {
	ChatGPT string
	Geo     string
	Stripe  string
}

func ProxyPlanForMode(mode, jpProxy, usProxy string) ProxyPlan {
	settings := CheckoutSettingsForMode(mode)
	stripeProxy := jpProxy
	if settings.UseUSProxy && strings.TrimSpace(usProxy) != "" {
		stripeProxy = usProxy
	}
	return ProxyPlan{
		ChatGPT: jpProxy,
		Geo:     jpProxy,
		Stripe:  stripeProxy,
	}
}

func (p ProxyPlan) ProxyForURL(rawURL string) string {
	u, err := url.Parse(rawURL)
	if err != nil {
		return p.ChatGPT
	}
	host := strings.ToLower(u.Hostname())
	if host == "ipinfo.io" {
		return p.Geo
	}
	if host == "api.stripe.com" || host == "checkout.stripe.com" || strings.HasSuffix(host, ".stripe.com") {
		return p.Stripe
	}
	return p.ChatGPT
}

func maskProxyURL(proxy string) string {
	return proxyutil.Mask(proxy)
}

func redactProxyText(text string, proxies ...string) string {
	return proxyutil.RedactText(text, proxies...)
}

type checkoutPayload struct {
	EntryPoint     string         `json:"entry_point"`
	PlanName       string         `json:"plan_name"`
	BillingDetails billingDetails `json:"billing_details"`
	PromoCampaign  promoCampaign  `json:"promo_campaign"`
	CheckoutUIMode string         `json:"checkout_ui_mode"`
	CancelURL      string         `json:"cancel_url"`
}

type billingDetails struct {
	Country  string `json:"country"`
	Currency string `json:"currency"`
}

type promoCampaign struct {
	ID                 string `json:"promo_campaign_id"`
	FromQueryParameter bool   `json:"is_coupon_from_query_param"`
}

func CheckoutPayload(settings CheckoutSettings) checkoutPayload {
	return checkoutPayload{
		EntryPoint: "all_plans_pricing_modal",
		PlanName:   "chatgptplusplan",
		BillingDetails: billingDetails{
			Country:  settings.Country,
			Currency: settings.Currency,
		},
		PromoCampaign: promoCampaign{
			ID:                 "plus-1-month-free",
			FromQueryParameter: false,
		},
		CheckoutUIMode: settings.UIMode,
		CancelURL:      "https://chatgpt.com/#pricing",
	}
}

func ParseGPTToken(raw string) (GPTToken, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return GPTToken{}, errors.New("empty token")
	}
	return GPTToken{
		AccessToken: raw,
		DeviceID:    newID(),
		Email:       extractEmailFromJWT(raw),
	}, nil
}

func extractEmailFromJWT(raw string) string {
	parts := strings.Split(raw, ".")
	if len(parts) < 2 {
		return ""
	}
	payload, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return ""
	}
	var claims map[string]any
	if err := json.Unmarshal(payload, &claims); err != nil {
		return ""
	}
	if email, _ := claims["email"].(string); email != "" {
		return email
	}
	if profile, ok := claims["https://api.openai.com/profile"].(map[string]any); ok {
		if email, _ := profile["email"].(string); email != "" {
			return email
		}
	}
	return ""
}

func parsePayPalLink(raw string) (*PayPalLink, error) {
	u, err := url.Parse(raw)
	if err != nil {
		return nil, err
	}
	q := u.Query()
	return &PayPalLink{
		FullURL: raw,
		BAToken: q.Get("ba_token"),
		Token:   q.Get("token"),
		SSRT:    q.Get("ssrt"),
		Country: q.Get("country.x"),
		Locale:  q.Get("locale.x"),
	}, nil
}

var stickySIDPattern = regexp.MustCompile(`(?i)(sid-)[A-Za-z0-9]+`)

func RotateSID(proxyURL string) string {
	return rotateSID(proxyURL, fmt.Sprintf("%d", time.Now().UnixNano()))
}

func rotateSID(proxyURL, sid string) string {
	if proxyURL == "" || sid == "" {
		return proxyURL
	}
	return stickySIDPattern.ReplaceAllString(proxyURL, "${1}"+sid)
}

func setupIntentConfirmValues(clientSecret, paymentMethodID, publishableKey, clientSessionID string) url.Values {
	values := url.Values{}
	values.Set("payment_method", paymentMethodID)
	values.Set("expected_payment_method_type", "paypal")
	values.Set("use_stripe_sdk", "true")
	values.Set("client_secret", clientSecret)
	values.Set("key", publishableKey)
	values.Set("client_attribution_metadata[client_session_id]", clientSessionID)
	values.Set("client_attribution_metadata[merchant_integration_source]", "custom_checkout_manual_approval_1")
	values.Set("client_attribution_metadata[merchant_integration_version]", "2020-08-27;custom_checkout_beta=v1")
	return values
}

func newID() string {
	var value [16]byte
	if _, err := rand.Read(value[:]); err != nil {
		return fmt.Sprintf("%d", time.Now().UnixNano())
	}
	value[6] = (value[6] & 0x0f) | 0x40
	value[8] = (value[8] & 0x3f) | 0x80
	hexValue := hex.EncodeToString(value[:])
	return strings.Join([]string{
		hexValue[0:8],
		hexValue[8:12],
		hexValue[12:16],
		hexValue[16:20],
		hexValue[20:32],
	}, "-")
}

func urlEncode(value string) string {
	return url.QueryEscape(value)
}

func truncate(value string, max int) string {
	if max <= 0 || len(value) <= max {
		return value
	}
	return value[:max] + "..."
}

func isPayPalURL(value string) bool {
	return strings.Contains(value, "paypal.com") || strings.Contains(value, "pm-redirects.stripe.com")
}
