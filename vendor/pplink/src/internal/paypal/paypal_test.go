package paypal

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"reflect"
	"strings"
	"testing"
	"time"
)

func TestCheckoutSettingsForSupportedModes(t *testing.T) {
	tests := []struct {
		mode string
		want CheckoutSettings
	}{
		{mode: "us", want: CheckoutSettings{Mode: "us", Country: "US", Currency: "USD", UIMode: "hosted", ProcessorEntity: "openai_llc", UseUSProxy: true}},
		{mode: "EU", want: CheckoutSettings{Mode: "eu", Country: "FR", Currency: "EUR", UIMode: "custom", ProcessorEntity: "openai_ie"}},
		{mode: "br", want: CheckoutSettings{Mode: "br", Country: "BR", Currency: "BRL", UIMode: "custom", ProcessorEntity: "openai_ie"}},
		{mode: "unknown", want: CheckoutSettings{Mode: "us", Country: "US", Currency: "USD", UIMode: "hosted", ProcessorEntity: "openai_llc", UseUSProxy: true}},
	}

	for _, tt := range tests {
		t.Run(tt.mode, func(t *testing.T) {
			if got := CheckoutSettingsForMode(tt.mode); got != tt.want {
				t.Fatalf("CheckoutSettingsForMode(%q) = %#v, want %#v", tt.mode, got, tt.want)
			}
		})
	}
}

func TestProxyPlanKeepsChatGPTOnJPAndUsesUSOnlyForStripe(t *testing.T) {
	jp := "socks5://jp.example:1080"
	us := "socks5://us.example:1080"

	usPlan := ProxyPlanForMode("us", jp, us)
	if usPlan.ChatGPT != jp || usPlan.Geo != jp || usPlan.Stripe != us {
		t.Fatalf("US proxy plan = %#v", usPlan)
	}
	for _, rawURL := range []string{
		"https://chatgpt.com/backend-api/sentinel/ping",
		"https://chatgpt.com/backend-api/payments/checkout",
		"https://chatgpt.com/backend-api/payments/checkout/approve",
		"https://ipinfo.io/json",
	} {
		if got := usPlan.ProxyForURL(rawURL); got != jp {
			t.Fatalf("ProxyForURL(%q) = %q, want JP", rawURL, got)
		}
	}
	for _, rawURL := range []string{
		"https://api.stripe.com/v1/payment_methods",
		"https://api.stripe.com/v1/setup_intents/seti_demo/confirm",
		"https://api.stripe.com/v1/payment_pages/cs_demo",
		"https://pm-redirects.stripe.com/authorize/demo",
	} {
		if got := usPlan.ProxyForURL(rawURL); got != us {
			t.Fatalf("ProxyForURL(%q) = %q, want US", rawURL, got)
		}
	}

	for _, mode := range []string{"eu", "br"} {
		plan := ProxyPlanForMode(mode, jp, us)
		if plan.ChatGPT != jp || plan.Geo != jp || plan.Stripe != jp {
			t.Fatalf("%s proxy plan = %#v, want JP-only", mode, plan)
		}
	}
}

func TestNewStripeSessionUsesProxyPlanForConcreteClients(t *testing.T) {
	jp := "http://127.0.0.1:18081"
	us := "http://127.0.0.1:18082"
	session, err := NewStripeSession(GPTToken{AccessToken: "opaque"}, "us", jp, us, nil)
	if err != nil {
		t.Fatal(err)
	}
	if session.chatProxyURL != jp || session.geoProxyURL != jp || session.stripeProxyURL != us {
		t.Fatalf("session proxies = chat:%q geo:%q stripe:%q", session.chatProxyURL, session.geoProxyURL, session.stripeProxyURL)
	}
	if session.clientForURL("https://chatgpt.com/backend-api/payments/checkout") != session.chatClient {
		t.Fatal("checkout did not select the JP ChatGPT client")
	}
	if session.clientForURL("https://ipinfo.io/json") != session.geoClient {
		t.Fatal("geo probe did not select the JP geo client")
	}
	if session.clientForURL("https://api.stripe.com/v1/payment_methods") != session.stripeClient {
		t.Fatal("Stripe PM did not select the US Stripe client")
	}
}

func TestNewStripeSessionRedactsAuthenticatedProxyLogs(t *testing.T) {
	jp := "socks5://jp-user:jp-password@jp.example:1080"
	us := "http://us-user:us-password@us.example:8080"
	var logs []string
	_, err := NewStripeSession(GPTToken{AccessToken: "opaque"}, "us", jp, us, func(format string, args ...any) {
		logs = append(logs, fmt.Sprintf(format, args...))
	})
	if err != nil {
		t.Fatal(err)
	}
	joined := strings.Join(logs, "\n")
	for _, secret := range []string{"jp-user", "jp-password", "us-user", "us-password"} {
		if strings.Contains(joined, secret) {
			t.Fatalf("proxy log leaked %q: %s", secret, joined)
		}
	}
	for _, maskedHost := range []string{"***@jp.example:1080", "***@us.example:8080"} {
		if !strings.Contains(joined, maskedHost) {
			t.Fatalf("proxy log missing masked host %q: %s", maskedHost, joined)
		}
	}
}

func TestNewStripeSessionRedactsMalformedAuthenticatedProxyErrors(t *testing.T) {
	tests := []struct {
		name    string
		jpProxy string
		usProxy string
		secrets []string
	}{
		{
			name:    "malformed jp",
			jpProxy: "socks5://jp-user:JP-SECRET@",
			secrets: []string{"jp-user", "JP-SECRET", "socks5://jp-user:JP-SECRET@"},
		},
		{
			name:    "malformed us",
			jpProxy: "http://127.0.0.1:1",
			usProxy: "http://us-user:US-SECRET@",
			secrets: []string{"us-user", "US-SECRET", "http://us-user:US-SECRET@"},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var logs []string
			_, err := NewStripeSession(GPTToken{AccessToken: "opaque"}, "us", tt.jpProxy, tt.usProxy, func(format string, args ...any) {
				logs = append(logs, fmt.Sprintf(format, args...))
			})
			if err == nil {
				t.Fatal("malformed authenticated proxy was accepted")
			}
			combined := err.Error() + "\n" + strings.Join(logs, "\n") + "\n" + maskProxyURL(firstNonEmpty(tt.usProxy, tt.jpProxy))
			for _, secret := range tt.secrets {
				if strings.Contains(combined, secret) {
					t.Fatalf("proxy error chain leaked %q: %s", secret, combined)
				}
			}
		})
	}
}

func TestExplicitProcessorEntitySurvivesCheckoutResponse(t *testing.T) {
	session := &StripeSession{processorEntity: "openai_llc"}
	session.SetProcessorEntity("openai_override")
	session.applyCheckoutResponse(map[string]any{
		"checkout_session_id": "cs_demo",
		"processor_entity":    "openai_ie",
	})
	if session.processorEntity != "openai_override" {
		t.Fatalf("processor entity = %q, want explicit override", session.processorEntity)
	}

	defaultSession := &StripeSession{processorEntity: "openai_llc"}
	defaultSession.applyCheckoutResponse(map[string]any{
		"checkout_session_id": "cs_demo",
		"processor_entity":    "openai_ie",
	})
	if defaultSession.processorEntity != "openai_ie" {
		t.Fatalf("default processor entity = %q, want checkout response value", defaultSession.processorEntity)
	}
}

func TestCheckoutPayloadMatchesBindingContract(t *testing.T) {
	for _, mode := range []string{"us", "eu", "br"} {
		settings := CheckoutSettingsForMode(mode)
		payload := CheckoutPayload(settings)
		encoded, err := json.Marshal(payload)
		if err != nil {
			t.Fatal(err)
		}

		var got map[string]any
		if err := json.Unmarshal(encoded, &got); err != nil {
			t.Fatal(err)
		}
		if got["entry_point"] != "all_plans_pricing_modal" || got["plan_name"] != "chatgptplusplan" {
			t.Fatalf("%s checkout identity = %s", mode, encoded)
		}
		billing := got["billing_details"].(map[string]any)
		if billing["country"] != settings.Country || billing["currency"] != settings.Currency {
			t.Fatalf("%s billing_details = %#v", mode, billing)
		}
		promo := got["promo_campaign"].(map[string]any)
		if promo["promo_campaign_id"] != "plus-1-month-free" || promo["is_coupon_from_query_param"] != false {
			t.Fatalf("%s promo_campaign = %#v", mode, promo)
		}
		if got["checkout_ui_mode"] != settings.UIMode || got["cancel_url"] != "https://chatgpt.com/#pricing" {
			t.Fatalf("%s checkout options = %s", mode, encoded)
		}
	}
}

func TestApplyStripeInitAllowsZeroAndRejectsNonzeroAmount(t *testing.T) {
	newSession := func() *StripeSession {
		return &StripeSession{
			settings: CheckoutSettingsForMode("us"),
			logf:     func(string, ...any) {},
		}
	}

	zero := newSession()
	if err := zero.applyStripeInit(`{"amount_total":0,"client_secret":"seti_demo_secret_value"} pk_live_TEST`); err != nil {
		t.Fatalf("zero amount rejected: %v", err)
	}
	if zero.pkLive != "pk_live_TEST" || zero.clientSecret != "seti_demo_secret_value" {
		t.Fatalf("zero init state = pk:%q secret:%q", zero.pkLive, zero.clientSecret)
	}

	nonzero := newSession()
	err := nonzero.applyStripeInit(`{"amount_total":1250} pk_live_TEST seti_demo_secret_value`)
	if err == nil {
		t.Fatal("nonzero amount accepted")
	}
	for _, want := range []string{"non-zero checkout amount", "1250", "USD"} {
		if !strings.Contains(err.Error(), want) {
			t.Fatalf("nonzero error missing %q: %v", want, err)
		}
	}

	for _, tt := range []struct {
		name string
		text string
	}{
		{name: "missing", text: `{"currency":"usd"}`},
		{name: "string zero", text: `{"amount_total":"0"}`},
		{name: "string nonzero", text: `{"amount_total":"1250"}`},
		{name: "escaped field", text: `{\"amount_total\":0}`},
		{name: "malformed field", text: `{"amount_total" 0}`},
		{name: "truncated json", text: `{"amount_total":0`},
		{name: "trailing comma", text: `{"amount_total":0,`},
		{name: "leading zero", text: `{"amount_total":00}`},
		{name: "multiple amount fields", text: `{"amount_total":0,"amount_due":0}`},
		{name: "duplicate amount key", text: `{"amount_total":0,"amount_total":0}`},
		{name: "nonnumeric", text: `{"amount_total":null}`},
	} {
		t.Run(tt.name, func(t *testing.T) {
			err := newSession().applyStripeInit(tt.text)
			if err == nil {
				t.Fatalf("unknown amount format accepted: %s", tt.text)
			}
			if !strings.Contains(err.Error(), "checkout amount") {
				t.Fatalf("amount error lacks context: %v", err)
			}
		})
	}
}

func TestExtractAmountFromInitRequiresBareNumericField(t *testing.T) {
	for _, tt := range []struct {
		name       string
		text       string
		wantAmount int
		wantErr    bool
	}{
		{name: "numeric zero", text: `{"amount_total":0}`, wantAmount: 0},
		{name: "nested html numeric zero", text: `<script>{"state":{"amount_due":0}}</script>`, wantAmount: 0},
		{name: "numeric nonzero", text: `{"total_amount_due":1250}`, wantAmount: 1250},
		{name: "missing", text: `{"currency":"usd"}`, wantErr: true},
		{name: "string zero", text: `{"amount_total":"0"}`, wantErr: true},
		{name: "string nonzero", text: `{"amount_total":"1250"}`, wantErr: true},
		{name: "escaped field", text: `{\"amount_total\":0}`, wantErr: true},
		{name: "malformed", text: `{"amount_total" 0}`, wantErr: true},
		{name: "truncated json", text: `{"amount_total":0`, wantErr: true},
		{name: "trailing comma", text: `{"amount_total":0,`, wantErr: true},
		{name: "leading zero", text: `{"amount_total":00}`, wantErr: true},
		{name: "multiple amount fields", text: `{"amount_total":0,"amount_due":0}`, wantErr: true},
		{name: "duplicate amount key", text: `{"amount_total":0,"amount_total":0}`, wantErr: true},
		{name: "nonnumeric", text: `{"amount_total":null}`, wantErr: true},
	} {
		t.Run(tt.name, func(t *testing.T) {
			amount, err := extractAmountFromInit(tt.text)
			if tt.wantErr {
				if err == nil {
					t.Fatalf("extractAmountFromInit(%q) = %d, nil", tt.text, amount)
				}
				return
			}
			if err != nil || amount != tt.wantAmount {
				t.Fatalf("extractAmountFromInit(%q) = %d, %v; want %d, nil", tt.text, amount, err, tt.wantAmount)
			}
		})
	}
}

type failingReader struct {
	err error
}

func (reader failingReader) Read([]byte) (int, error) {
	return 0, reader.err
}

func TestApplyStripeInitReaderPropagatesReadError(t *testing.T) {
	sentinel := errors.New("body read failed")
	session := &StripeSession{
		settings: CheckoutSettingsForMode("us"),
		logf:     func(string, ...any) {},
	}
	err := session.applyStripeInitReader(failingReader{err: sentinel})
	if !errors.Is(err, sentinel) {
		t.Fatalf("applyStripeInitReader() error = %v, want wrapped sentinel", err)
	}
	if !strings.Contains(err.Error(), "read stripe init response") {
		t.Fatalf("read error lacks context: %v", err)
	}
}

func TestRandomIdentityUsesGeoOnlyWhenCountriesMatch(t *testing.T) {
	tests := []struct {
		name           string
		billingCountry string
		geoCountry     string
		geoRegion      string
		geoCity        string
		geoPostal      string
		wantState      string
		wantCity       string
		wantPostal     string
	}{
		{name: "us ignores jp geo", billingCountry: "US", geoCountry: "JP", geoRegion: "Tokyo", geoCity: "Shibuya", geoPostal: "150-0001", wantState: "CA", wantCity: "San Francisco", wantPostal: "94105"},
		{name: "fr ignores jp geo", billingCountry: "FR", geoCountry: "JP", geoRegion: "Tokyo", geoCity: "Shibuya", geoPostal: "150-0001", wantState: "Ile-de-France", wantCity: "Paris", wantPostal: "75001"},
		{name: "br ignores jp geo", billingCountry: "BR", geoCountry: "JP", geoRegion: "Tokyo", geoCity: "Shibuya", geoPostal: "150-0001", wantState: "SP", wantCity: "Sao Paulo", wantPostal: "01001-000"},
		{name: "us accepts us geo", billingCountry: "US", geoCountry: "us", geoRegion: "WA", geoCity: "Seattle", geoPostal: "98101", wantState: "WA", wantCity: "Seattle", wantPostal: "98101"},
		{name: "fr accepts fr geo", billingCountry: "FR", geoCountry: "FR", geoRegion: "Provence", geoCity: "Marseille", geoPostal: "13001", wantState: "Provence", wantCity: "Marseille", wantPostal: "13001"},
		{name: "br accepts br geo", billingCountry: "BR", geoCountry: "BR", geoRegion: "RJ", geoCity: "Rio de Janeiro", geoPostal: "20000-000", wantState: "RJ", wantCity: "Rio de Janeiro", wantPostal: "20000-000"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := randomIdentity(
				tt.billingCountry,
				tt.geoCountry,
				tt.geoRegion,
				tt.geoCity,
				tt.geoPostal,
				"person@example.test",
			)
			if got.Country != tt.billingCountry || got.State != tt.wantState || got.City != tt.wantCity || got.PostalCode != tt.wantPostal {
				t.Fatalf("identity = country:%q state:%q city:%q postal:%q", got.Country, got.State, got.City, got.PostalCode)
			}
		})
	}
}

func TestRequirePayPalPMResultPropagatesError(t *testing.T) {
	sentinel := errors.New("payment method transport failed")
	link, err := requirePayPalPMResult(nil, sentinel)
	if link != nil {
		t.Fatalf("link = %#v, want nil", link)
	}
	if !errors.Is(err, sentinel) {
		t.Fatalf("error = %v, want wrapped sentinel", err)
	}
	if !strings.Contains(err.Error(), "PayPal PM failed") {
		t.Fatalf("error lacks PM context: %v", err)
	}
}

func TestPollForPayPalRedirectFailsFastWithoutRedirectOrClientSecret(t *testing.T) {
	session := &StripeSession{
		payURL: "https://pay.openai.com/c/pay/cs_demo",
		logf:   func(string, ...any) {},
	}
	done := make(chan error, 1)
	go func() {
		_, err := session.pollForPayPalRedirect()
		done <- err
	}()

	select {
	case err := <-done:
		if err == nil || !strings.Contains(err.Error(), "no PayPal redirect source") {
			t.Fatalf("poll error = %v", err)
		}
	case <-time.After(100 * time.Millisecond):
		t.Fatal("poll did not fail fast without a redirect URL or client secret")
	}
}

func TestRotateSIDReplacesStickyValueWithoutChangingOtherCredentials(t *testing.T) {
	proxy := "socks5://user-region-JP-sid-ORIGINAL-t-5:secret@example.test:1080"
	got := rotateSID(proxy, "NEWVALUE")
	want := "socks5://user-region-JP-sid-NEWVALUE-t-5:secret@example.test:1080"
	if got != want {
		t.Fatalf("rotateSID() = %q, want %q", got, want)
	}
	if rotateSID("socks5://user:secret@example.test:1080", "NEWVALUE") != "socks5://user:secret@example.test:1080" {
		t.Fatal("rotateSID changed a proxy without a sticky SID")
	}
}

func TestParsePayPalLinkPreservesAuthorizeURL(t *testing.T) {
	raw := "https://www.paypal.com/agreements/approve?ba_token=BA-DEMO&token=EC-DEMO&ssrt=7&country.x=US&locale.x=en_US"
	link, err := parsePayPalLink(raw)
	if err != nil {
		t.Fatal(err)
	}
	if link.FullURL != raw || link.BAToken != "BA-DEMO" || link.Token != "EC-DEMO" || link.SSRT != "7" || link.Country != "US" || link.Locale != "en_US" {
		t.Fatalf("parsePayPalLink() = %#v", link)
	}
}

func TestFormEncodingKeepsCheckoutAttributionParameters(t *testing.T) {
	values := setupIntentConfirmValues("seti_demo_secret_value", "pm_demo", "pk_live_demo", "session_demo")
	want := url.Values{
		"payment_method":               {"pm_demo"},
		"expected_payment_method_type": {"paypal"},
		"use_stripe_sdk":               {"true"},
		"client_secret":                {"seti_demo_secret_value"},
		"key":                          {"pk_live_demo"},
		"client_attribution_metadata[client_session_id]":            {"session_demo"},
		"client_attribution_metadata[merchant_integration_source]":  {"custom_checkout_manual_approval_1"},
		"client_attribution_metadata[merchant_integration_version]": {"2020-08-27;custom_checkout_beta=v1"},
	}
	if !reflect.DeepEqual(values, want) {
		t.Fatalf("setupIntentConfirmValues() = %#v, want %#v", values, want)
	}
	if strings.Contains(values.Encode(), " ") {
		t.Fatalf("encoded form contains spaces: %q", values.Encode())
	}
}
