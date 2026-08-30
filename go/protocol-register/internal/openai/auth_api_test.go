package openai

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync/atomic"
	"testing"
)

func TestSigninOpenAIUsesFormContractAndChatGPTOrigin(t *testing.T) {
	type capturedRequest struct {
		method           string
		contentType      string
		origin           string
		referer          string
		userAgent        string
		secCHUA          string
		secCHUAMobile    string
		secCHUAPlatform  string
		body             string
		navigationOrigin string
		navigationAccept string
		navigationUA     string
		navigationCHUA   string
	}
	var captured capturedRequest
	var srv *httptest.Server
	srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/auth/signin/openai":
			raw, _ := io.ReadAll(r.Body)
			captured = capturedRequest{
				method:          r.Method,
				contentType:     r.Header.Get("Content-Type"),
				origin:          r.Header.Get("Origin"),
				referer:         r.Header.Get("Referer"),
				userAgent:       r.Header.Get("User-Agent"),
				secCHUA:         r.Header.Get("Sec-CH-UA"),
				secCHUAMobile:   r.Header.Get("Sec-CH-UA-Mobile"),
				secCHUAPlatform: r.Header.Get("Sec-CH-UA-Platform"),
				body:            string(raw),
			}
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]string{"url": srv.URL + "/oauth/start"})
		case "/oauth/start":
			captured.navigationOrigin = r.Header.Get("Origin")
			captured.navigationAccept = r.Header.Get("Accept")
			captured.navigationUA = r.Header.Get("User-Agent")
			captured.navigationCHUA = r.Header.Get("Sec-CH-UA")
			http.SetCookie(w, &http.Cookie{Name: "oai-did", Value: "device-1", Path: "/"})
			w.WriteHeader(http.StatusOK)
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()

	profile := mustOpenAIProfile(t, "chrome144")
	client := NewClient(srv.Client(), srv.URL, srv.URL, profile)
	deviceID, err := client.InitializeOAuth(context.Background(), "csrf-1")
	if err != nil {
		t.Fatal(err)
	}
	if deviceID != "device-1" {
		t.Fatalf("deviceID=%q", deviceID)
	}

	values, err := url.ParseQuery(captured.body)
	if err != nil {
		t.Fatal(err)
	}
	if captured.method != http.MethodPost {
		t.Fatalf("method=%q", captured.method)
	}
	if captured.contentType != "application/x-www-form-urlencoded" {
		t.Fatalf("Content-Type=%q", captured.contentType)
	}
	if captured.origin != srv.URL || captured.referer != srv.URL+"/auth/login" {
		t.Fatalf("origin=%q referer=%q", captured.origin, captured.referer)
	}
	if captured.userAgent != profile.UserAgent || captured.navigationUA != profile.UserAgent {
		t.Fatalf("User-Agent API=%q navigation=%q", captured.userAgent, captured.navigationUA)
	}
	if captured.secCHUA != profile.SecCHUA || captured.navigationCHUA != profile.SecCHUA ||
		captured.secCHUAMobile != profile.SecCHUAMobile || captured.secCHUAPlatform != profile.SecCHUAPlatform {
		t.Fatalf("client hints=%#v", captured)
	}
	if captured.navigationOrigin != "" {
		t.Fatalf("navigation Origin=%q, want empty", captured.navigationOrigin)
	}
	if captured.navigationAccept != "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8" {
		t.Fatalf("navigation Accept=%q", captured.navigationAccept)
	}
	if values.Get("csrfToken") != "csrf-1" || values.Get("callbackUrl") != srv.URL+"/" || values.Get("json") != "true" {
		t.Fatalf("form=%#v", values)
	}
}

func TestInitializeOAuthRequiresDeviceCookie(t *testing.T) {
	var srv *httptest.Server
	srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/auth/signin/openai":
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]string{"url": srv.URL + "/oauth/start"})
		case "/oauth/start":
			w.WriteHeader(http.StatusOK)
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()

	client := NewClient(srv.Client(), srv.URL, srv.URL, mustOpenAIProfile(t, "chrome146"))
	if _, err := client.InitializeOAuth(context.Background(), "csrf-1"); !errors.Is(err, ErrInvalidAuthState) {
		t.Fatalf("err=%v", err)
	}
}

func TestFollowContinueRejectsUntrustedHostBeforeRequest(t *testing.T) {
	untrustedCalls := 0
	untrusted := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		untrustedCalls++
		w.WriteHeader(http.StatusOK)
	}))
	defer untrusted.Close()
	trusted := httptest.NewServer(http.NotFoundHandler())
	defer trusted.Close()

	client := NewClient(http.DefaultClient, trusted.URL, trusted.URL, mustOpenAIProfile(t, "chrome146"))
	err := client.FollowContinue(context.Background(), untrusted.URL+"/steal-session")
	if !errors.Is(err, ErrInvalidAuthState) {
		t.Fatalf("err=%v", err)
	}
	if untrustedCalls != 0 {
		t.Fatalf("untrusted calls=%d", untrustedCalls)
	}
}

func TestJSONResponsesRejectTrailingAndOversizedData(t *testing.T) {
	tests := []struct {
		name string
		body string
	}{
		{name: "trailing JSON", body: `{"csrfToken":"csrf-1"}{"extra":true}`},
		{name: "oversized", body: `{"csrfToken":"csrf-1"}` + strings.Repeat(" ", (1<<20)+1)},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.Header().Set("Content-Type", "application/json")
				_, _ = io.WriteString(w, tt.body)
			}))
			defer srv.Close()

			client := NewClient(srv.Client(), srv.URL, srv.URL, mustOpenAIProfile(t, "chrome146"))
			if _, err := client.GetCSRF(context.Background()); !errors.Is(err, ErrInvalidAuthState) {
				t.Fatalf("err=%v", err)
			}
		})
	}
}

func TestNoOutputJSONResponsesAreDrainedForConnectionReuse(t *testing.T) {
	var newConnections atomic.Int32
	srv := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]string{"padding": strings.Repeat("x", 4096)})
	}))
	srv.Config.ConnState = func(_ net.Conn, state http.ConnState) {
		if state == http.StateNew {
			newConnections.Add(1)
		}
	}
	srv.Start()
	defer srv.Close()

	client := NewClient(srv.Client(), srv.URL, srv.URL, mustOpenAIProfile(t, "chrome146"))
	for range 2 {
		if err := client.SendEmailOTP(context.Background()); err != nil {
			t.Fatal(err)
		}
	}
	if got := newConnections.Load(); got != 1 {
		t.Fatalf("connections=%d, want one reused connection", got)
	}
}

func TestClientUsesHeadersForEachEndpointBase(t *testing.T) {
	type capturedHeaders struct {
		origin  string
		referer string
	}
	var authHeaders, chatGPTHeaders capturedHeaders

	authServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		authHeaders = capturedHeaders{origin: r.Header.Get("Origin"), referer: r.Header.Get("Referer")}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{
			"page":         map[string]any{"type": "create_account_password"},
			"continue_url": "/create-account/password",
		})
	}))
	defer authServer.Close()

	chatGPTServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		chatGPTHeaders = capturedHeaders{origin: r.Header.Get("Origin"), referer: r.Header.Get("Referer")}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]string{"csrfToken": "csrf-1"})
	}))
	defer chatGPTServer.Close()

	client := NewClient(http.DefaultClient, authServer.URL, chatGPTServer.URL, mustOpenAIProfile(t, "chrome146"))
	if _, err := client.GetCSRF(context.Background()); err != nil {
		t.Fatal(err)
	}
	if _, err := client.AuthorizeContinue(context.Background(), "user@example.com", "sentinel-1"); err != nil {
		t.Fatal(err)
	}

	if chatGPTHeaders.origin != chatGPTServer.URL || chatGPTHeaders.referer != chatGPTServer.URL+"/auth/login" {
		t.Fatalf("ChatGPT headers=%#v", chatGPTHeaders)
	}
	if authHeaders.origin != authServer.URL || authHeaders.referer != authServer.URL+"/create-account" {
		t.Fatalf("auth headers=%#v", authHeaders)
	}
}

func TestAuthorizeContinueReturnsTypedKnownStates(t *testing.T) {
	tests := []struct {
		name string
		body map[string]any
		want AuthStep
	}{
		{
			name: "password registration",
			body: map[string]any{
				"page":         map[string]any{"type": "create_account_password"},
				"continue_url": "/create-account/password",
			},
			want: AuthStep{PageType: "create_account_password", ContinueURL: "/create-account/password"},
		},
		{
			name: "email OTP",
			body: map[string]any{
				"page": map[string]any{
					"type":    "email_otp_verification",
					"payload": map[string]any{"email_verification_mode": "passwordless_signup"},
				},
				"continue_url": "/email-verification",
			},
			want: AuthStep{
				PageType:              "email_otp_verification",
				ContinueURL:           "/email-verification",
				EmailVerificationMode: "passwordless_signup",
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var sentinelToken string
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				sentinelToken = r.Header.Get("openai-sentinel-token")
				w.Header().Set("Content-Type", "application/json")
				_ = json.NewEncoder(w).Encode(tt.body)
			}))
			defer srv.Close()

			client := NewClient(srv.Client(), srv.URL, srv.URL, mustOpenAIProfile(t, "chrome146"))
			got, err := client.AuthorizeContinue(context.Background(), "user@example.com", "sentinel-authorize")
			if err != nil {
				t.Fatal(err)
			}
			if got != tt.want {
				t.Fatalf("step=%#v, want %#v", got, tt.want)
			}
			if sentinelToken != "sentinel-authorize" {
				t.Fatalf("openai-sentinel-token=%q", sentinelToken)
			}
		})
	}
}

func TestCreateAccountAcceptsExternalURLState(t *testing.T) {
	var srv *httptest.Server
	var callbackURL string
	srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/accounts/create_account" {
			http.NotFound(w, r)
			return
		}
		if got := r.Header.Get("openai-sentinel-token"); got != "sentinel-create" {
			t.Errorf("openai-sentinel-token=%q", got)
		}
		var body map[string]any
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Fatal(err)
		}
		if body["name"] != "Alex Chen" || body["birthdate"] != "1993-01-01" {
			t.Errorf("body=%#v", body)
		}
		callbackURL = srv.URL + "/api/auth/callback/openai?code=callback-code"
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{
			"continue_url": callbackURL,
			"method":       http.MethodGet,
			"page": map[string]any{
				"type": "external_url",
				"payload": map[string]any{
					"url": callbackURL,
				},
			},
		})
	}))
	defer srv.Close()

	client := NewClient(srv.Client(), srv.URL, srv.URL, mustOpenAIProfile(t, "chrome150"))
	got, err := client.CreateAccount(
		context.Background(),
		"sentinel-create",
		"Alex Chen",
		"1993-01-01",
	)
	if err != nil {
		t.Fatal(err)
	}
	if got.PageType != "external_url" || got.ContinueURL != callbackURL {
		t.Fatalf("step=%#v", got)
	}
}

func TestCreateAccountRejectsInvalidStates(t *testing.T) {
	tests := []struct {
		name string
		body map[string]any
	}{
		{
			name: "wrong page type",
			body: map[string]any{
				"page":         map[string]any{"type": "email_otp_verification"},
				"continue_url": "/email-verification",
			},
		},
		{
			name: "missing external continuation",
			body: map[string]any{
				"page": map[string]any{"type": "external_url"},
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				w.Header().Set("Content-Type", "application/json")
				_ = json.NewEncoder(w).Encode(tt.body)
			}))
			defer srv.Close()

			client := NewClient(srv.Client(), srv.URL, srv.URL, mustOpenAIProfile(t, "chrome146"))
			_, err := client.CreateAccount(
				context.Background(),
				"sentinel-create",
				"Alex Chen",
				"1993-01-01",
			)
			if !errors.Is(err, ErrInvalidAuthState) {
				t.Fatalf("err=%v", err)
			}
		})
	}
}

func TestAuthorizeContinueRejectsInvalidAndChallengeStates(t *testing.T) {
	tests := []struct {
		name        string
		contentType string
		status      int
		body        string
		wantErr     error
	}{
		{
			name:        "unknown page",
			contentType: "application/json",
			status:      http.StatusOK,
			body:        `{"page":{"type":"captcha"},"continue_url":"/captcha"}`,
			wantErr:     ErrInvalidAuthState,
		},
		{
			name:        "missing continuation",
			contentType: "application/json",
			status:      http.StatusOK,
			body:        `{"page":{"type":"create_account_password"}}`,
			wantErr:     ErrInvalidAuthState,
		},
		{
			name:        "HTML challenge",
			contentType: "text/html; charset=utf-8",
			status:      http.StatusForbidden,
			body:        `<html><title>challenge</title></html>`,
			wantErr:     ErrChallengeUnavailable,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.Header().Set("Content-Type", tt.contentType)
				w.WriteHeader(tt.status)
				_, _ = w.Write([]byte(tt.body))
			}))
			defer srv.Close()

			client := NewClient(srv.Client(), srv.URL, srv.URL, mustOpenAIProfile(t, "chrome146"))
			_, err := client.AuthorizeContinue(context.Background(), "user@example.com", "sentinel-authorize")
			if !errors.Is(err, tt.wantErr) {
				t.Fatalf("err=%v, want %v", err, tt.wantErr)
			}
		})
	}
}
