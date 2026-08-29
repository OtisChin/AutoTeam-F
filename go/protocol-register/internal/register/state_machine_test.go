package register_test

import (
	"autoteam-f/protocol-register/internal/model"
	"autoteam-f/protocol-register/internal/openai"
	"autoteam-f/protocol-register/internal/register"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
)

func TestHTTPRegisterEngineSuccessWithMockOpenAIAndMail(t *testing.T) {
	hits := map[string]int{}
	userAgents := map[string]int{}
	expectedSentinel := map[string]string{
		"/api/accounts/authorize/continue": "mock-authorize_continue",
		"/api/accounts/user/register":      "mock-username_password_create",
		"/api/accounts/profile":            "mock-create_account",
	}
	var mu sync.Mutex
	openaiSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits[r.URL.Path]++
		if strings.HasPrefix(r.URL.Path, "/api/") {
			w.Header().Set("Content-Type", "application/json")
			ua := r.Header.Get("User-Agent")
			mu.Lock()
			userAgents[ua]++
			mu.Unlock()
		}
		if want, ok := expectedSentinel[r.URL.Path]; ok {
			if got := r.Header.Get("openai-sentinel-token"); got != want {
				t.Errorf("%s sentinel token=%q, want %q", r.URL.Path, got, want)
			}
		} else if got := r.Header.Get("openai-sentinel-token"); got != "" {
			t.Errorf("%s unexpectedly received sentinel token %q", r.URL.Path, got)
		}
		switch r.URL.Path {
		case "/api/auth/csrf":
			_ = json.NewEncoder(w).Encode(map[string]any{"csrfToken": "csrf-1"})
		case "/api/auth/signin/openai":
			_ = json.NewEncoder(w).Encode(map[string]any{"url": "http://" + r.Host + "/oauth/start"})
		case "/oauth/start":
			http.SetCookie(w, &http.Cookie{Name: "oai-did", Value: "device-1", Path: "/"})
			_, _ = w.Write([]byte("ok"))
		case "/api/accounts/authorize/continue":
			_ = json.NewEncoder(w).Encode(map[string]any{"page": map[string]any{"type": "create_account_password"}, "continue_url": "/create-account/password"})
		case "/api/accounts/user/register":
			_ = json.NewEncoder(w).Encode(map[string]any{"ok": true})
		case "/api/accounts/email-otp/send":
			_ = json.NewEncoder(w).Encode(map[string]any{"ok": true})
		case "/api/accounts/email-otp/verify":
			_ = json.NewEncoder(w).Encode(map[string]any{"continue_url": "http://" + r.Host + "/about-you"})
		case "/api/accounts/profile":
			_ = json.NewEncoder(w).Encode(map[string]any{"continue_url": "http://" + r.Host + "/callback?code=abc"})
		case "/api/auth/session":
			_ = json.NewEncoder(w).Encode(map[string]any{"accessToken": "access-1", "sessionToken": "session-1"})
		default:
			http.NotFound(w, r)
		}
	}))
	defer openaiSrv.Close()
	mailSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{"code": "123456"})
	}))
	defer mailSrv.Close()

	provider := &staticSentinelProvider{}
	engine := register.NewHTTPRegisterEngine(register.HTTPRegisterEngineConfig{
		BaseURL: openaiSrv.URL, ChatGPTBaseURL: openaiSrv.URL, SentinelProvider: provider,
	})
	resp := engine.Register(httptest.NewRequest(http.MethodPost, "/v1/register", nil), model.RegisterRequest{
		Email: "user@example.com", Password: "Password123$",
		Mail:    model.MailConfig{Provider: "generic-api", ReceiveCodeURL: mailSrv.URL},
		Options: model.RegisterOptions{TimeoutSeconds: 2},
	})
	if !resp.Success || resp.Status != "success" || resp.SessionData["accessToken"] != "access-1" {
		t.Fatalf("unexpected response: %#v", resp)
	}
	mu.Lock()
	var userAgent string
	for ua := range userAgents {
		userAgent = ua
	}
	count := len(userAgents)
	mu.Unlock()
	if count != 1 {
		t.Fatalf("expected one user agent across the flow, got %#v", userAgents)
	}
	if userAgent != "AutoToken-F protocol-registerd/go-http" {
		t.Fatalf("user agent=%q, want deterministic go-http identity", userAgent)
	}
	wantFlows := []string{"authorize_continue", "username_password_create", "create_account"}
	if len(provider.calls) != len(wantFlows) {
		t.Fatalf("sentinel calls=%#v", provider.calls)
	}
	for i, wantFlow := range wantFlows {
		if provider.calls[i].flow != wantFlow || provider.calls[i].deviceID != "device-1" {
			t.Fatalf("sentinel call[%d]=%#v", i, provider.calls[i])
		}
	}
	for _, path := range []string{"/api/auth/csrf", "/api/auth/signin/openai", "/api/accounts/authorize/continue", "/api/accounts/user/register", "/api/accounts/email-otp/send", "/api/accounts/email-otp/verify", "/api/accounts/profile", "/api/auth/session"} {
		if hits[path] == 0 {
			t.Fatalf("expected hit for %s, hits=%#v", path, hits)
		}
	}
}

func TestHTTPRegisterEngineFailsClosedBeforeAuthorizeWithoutSentinel(t *testing.T) {
	authorizeCalls := 0
	var srv *httptest.Server
	srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/auth/csrf":
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]string{"csrfToken": "csrf-1"})
		case "/api/auth/signin/openai":
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]string{"url": srv.URL + "/oauth/start"})
		case "/oauth/start":
			http.SetCookie(w, &http.Cookie{Name: "oai-did", Value: "device-1", Path: "/"})
			w.WriteHeader(http.StatusOK)
		case "/api/accounts/authorize/continue":
			authorizeCalls++
			http.Error(w, "must not be called", http.StatusInternalServerError)
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()

	engine := register.NewHTTPRegisterEngine(register.HTTPRegisterEngineConfig{
		BaseURL: srv.URL, ChatGPTBaseURL: srv.URL,
	})
	resp := engine.Register(httptest.NewRequest(http.MethodPost, "/v1/register", nil), model.RegisterRequest{
		Email: "user@example.com", Options: model.RegisterOptions{TimeoutSeconds: 2},
	})

	if resp.Status != "challenge_unavailable" || resp.Error == nil || resp.Error.Code != "challenge_unavailable" {
		t.Fatalf("response=%#v", resp)
	}
	if resp.Error.Step != "authorize_continue" || resp.Error.Retryable {
		t.Fatalf("error=%#v", resp.Error)
	}
	if authorizeCalls != 0 {
		t.Fatalf("authorize calls=%d", authorizeCalls)
	}
}

func TestHTTPRegisterEngineNormalizesNetworkFailureStatus(t *testing.T) {
	openaiSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "password=Password123$ access_token=access-secret otp=https://mail.example/otp-secret", http.StatusBadGateway)
	}))
	defer openaiSrv.Close()

	engine := register.NewHTTPRegisterEngine(register.HTTPRegisterEngineConfig{BaseURL: openaiSrv.URL, ChatGPTBaseURL: openaiSrv.URL})
	resp := engine.Register(httptest.NewRequest(http.MethodPost, "/v1/register", nil), model.RegisterRequest{
		Email:   "user@example.com",
		Options: model.RegisterOptions{TimeoutSeconds: 2},
	})
	if resp.Status != "register_failed" || resp.Error == nil || resp.Error.Code != "network_error" {
		t.Fatalf("response=%#v", resp)
	}
	for _, secret := range []string{"Password123$", "access-secret", "https://mail.example/otp-secret"} {
		if strings.Contains(resp.Error.Message, secret) {
			t.Fatalf("error leaked upstream secret %q: %q", secret, resp.Error.Message)
		}
	}
}

func TestHTTPRegisterEngineRejectsFailedOpenAIOAuthSignin(t *testing.T) {
	openaiSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/auth/csrf":
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]any{"csrfToken": "csrf-1"})
		case "/api/auth/signin/openai":
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]any{"url": "http://" + r.Host + "/oauth/start"})
		case "/oauth/start":
			http.Error(w, "oauth provider failure", http.StatusBadGateway)
		default:
			t.Fatalf("unexpected request to %s", r.URL.Path)
		}
	}))
	defer openaiSrv.Close()

	engine := register.NewHTTPRegisterEngine(register.HTTPRegisterEngineConfig{BaseURL: openaiSrv.URL, ChatGPTBaseURL: openaiSrv.URL})
	resp := engine.Register(httptest.NewRequest(http.MethodPost, "/v1/register", nil), model.RegisterRequest{
		Email:   "user@example.com",
		Options: model.RegisterOptions{TimeoutSeconds: 2},
	})
	if resp.Status != "register_failed" || resp.Error == nil || resp.Error.Code != "network_error" {
		t.Fatalf("response=%#v", resp)
	}
	if resp.Error.Step != "signin_openai" {
		t.Fatalf("error=%#v", resp.Error)
	}
	if strings.Contains(resp.Error.Message, "oauth provider failure") {
		t.Fatalf("error leaked response body: %q", resp.Error.Message)
	}
}

func TestHTTPRegisterEngineSanitizesOAuthURLErrors(t *testing.T) {
	secret := "state=oauth-state-secret"
	openaiSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/auth/csrf":
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]any{"csrfToken": "csrf-1"})
		case "/api/auth/signin/openai":
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]any{"url": "http://[::1?" + secret})
		default:
			t.Fatalf("unexpected request to %s", r.URL.Path)
		}
	}))
	defer openaiSrv.Close()

	engine := register.NewHTTPRegisterEngine(register.HTTPRegisterEngineConfig{BaseURL: openaiSrv.URL, ChatGPTBaseURL: openaiSrv.URL})
	resp := engine.Register(httptest.NewRequest(http.MethodPost, "/v1/register", nil), model.RegisterRequest{
		Email:   "user@example.com",
		Options: model.RegisterOptions{TimeoutSeconds: 2},
	})
	assertSanitizedFailure(t, resp, "signin_openai", secret)
}

func TestHTTPRegisterEngineSanitizesProxyURLErrors(t *testing.T) {
	secret := "proxy-password"
	engine := register.NewHTTPRegisterEngine(register.HTTPRegisterEngineConfig{BaseURL: "http://127.0.0.1:1", ChatGPTBaseURL: "http://127.0.0.1:1"})
	resp := engine.Register(httptest.NewRequest(http.MethodPost, "/v1/register", nil), model.RegisterRequest{
		Email:    "user@example.com",
		ProxyURL: "http://proxy-user:" + secret + "@[::1",
		Options:  model.RegisterOptions{TimeoutSeconds: 2},
	})
	assertSanitizedFailure(t, resp, "http_client", secret)
}

type sentinelCall struct {
	deviceID string
	flow     string
}

type staticSentinelProvider struct {
	calls []sentinelCall
}

func (p *staticSentinelProvider) Token(_ context.Context, _ *http.Client, deviceID, flow string) (string, error) {
	p.calls = append(p.calls, sentinelCall{deviceID: deviceID, flow: flow})
	return "mock-" + flow, nil
}

var _ openai.SentinelProvider = (*staticSentinelProvider)(nil)

func assertSanitizedFailure(t *testing.T, resp model.RegisterResponse, step, secret string) {
	t.Helper()
	if resp.Status != "register_failed" || resp.Error == nil || resp.Error.Code != "network_error" || resp.Error.Step != step {
		t.Fatalf("response=%#v", resp)
	}
	raw, _ := json.Marshal(resp)
	if strings.Contains(string(raw), secret) {
		t.Fatalf("response leaked secret %q: %s", secret, raw)
	}
}
