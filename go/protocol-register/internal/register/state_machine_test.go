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

func TestHTTPRegisterEngineEnforcesLocalAuthStateParity(t *testing.T) {
	type requestExpectation struct {
		method        string
		path          string
		contentType   string
		origin        string
		referer       string
		sentinelToken string
		authCookies   bool
		sessionCookie bool
	}

	var (
		openaiSrv   *httptest.Server
		expected    []requestExpectation
		requestMu   sync.Mutex
		requestStep int
	)
	openaiSrv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requestMu.Lock()
		if requestStep >= len(expected) {
			requestMu.Unlock()
			t.Errorf("unexpected extra request: %s %s", r.Method, r.URL.RequestURI())
			http.NotFound(w, r)
			return
		}
		want := expected[requestStep]
		requestStep++
		requestMu.Unlock()

		if r.Method != want.method || r.URL.Path != want.path {
			t.Errorf("request=%s %s, want %s %s", r.Method, r.URL.Path, want.method, want.path)
		}
		if got := r.Header.Get("User-Agent"); got != "AutoToken-F protocol-registerd/go-http" {
			t.Errorf("%s User-Agent=%q", r.URL.Path, got)
		}
		if got := r.Header.Get("Content-Type"); got != want.contentType {
			t.Errorf("%s Content-Type=%q, want %q", r.URL.Path, got, want.contentType)
		}
		if got := r.Header.Get("Origin"); got != want.origin {
			t.Errorf("%s Origin=%q, want %q", r.URL.Path, got, want.origin)
		}
		if got := r.Header.Get("Referer"); got != want.referer {
			t.Errorf("%s Referer=%q, want %q", r.URL.Path, got, want.referer)
		}
		if got := r.Header.Get("openai-sentinel-token"); got != want.sentinelToken {
			t.Errorf("%s sentinel=%q, want %q", r.URL.Path, got, want.sentinelToken)
		}
		if want.authCookies {
			for name, value := range map[string]string{"oai-did": "device-1", "auth-state": "state-1"} {
				cookie, err := r.Cookie(name)
				if err != nil || cookie.Value != value {
					t.Errorf("%s cookie %s=%v err=%v", r.URL.Path, name, cookie, err)
				}
			}
		}
		if want.sessionCookie {
			cookie, err := r.Cookie("next-auth.session-token")
			if err != nil || cookie.Value != "session-1" {
				t.Errorf("%s session cookie=%v err=%v", r.URL.Path, cookie, err)
			}
		}

		writeJSON := func(payload any) {
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(payload)
		}
		switch r.URL.Path {
		case "/api/auth/csrf":
			writeJSON(map[string]string{"csrfToken": "csrf-1"})
		case "/api/auth/signin/openai":
			if err := r.ParseForm(); err != nil || r.Form.Get("csrfToken") != "csrf-1" || r.Form.Get("json") != "true" {
				t.Errorf("signin form=%#v err=%v", r.Form, err)
			}
			writeJSON(map[string]string{"url": openaiSrv.URL + "/oauth/start"})
		case "/oauth/start":
			http.SetCookie(w, &http.Cookie{Name: "oai-did", Value: "device-1", Path: "/"})
			http.SetCookie(w, &http.Cookie{Name: "auth-state", Value: "state-1", Path: "/"})
			w.Header().Set("Content-Type", "text/html")
			_, _ = w.Write([]byte("oauth initialized"))
		case "/api/accounts/authorize/continue":
			var body map[string]any
			_ = json.NewDecoder(r.Body).Decode(&body)
			username, _ := body["username"].(map[string]any)
			if username["value"] != "user@example.com" || body["screen_hint"] != "signup" {
				t.Errorf("authorize body=%#v", body)
			}
			writeJSON(map[string]any{"page": map[string]any{"type": "create_account_password"}, "continue_url": "/create-account/password"})
		case "/create-account/password":
			w.Header().Set("Content-Type", "text/html")
			_, _ = w.Write([]byte("password page"))
		case "/api/accounts/user/register":
			var body map[string]any
			_ = json.NewDecoder(r.Body).Decode(&body)
			if body["username"] != "user@example.com" || body["password"] != "Password123$" {
				t.Errorf("password body=%#v", body)
			}
			writeJSON(map[string]bool{"ok": true})
		case "/api/accounts/email-otp/send":
			writeJSON(map[string]bool{"ok": true})
		case "/api/accounts/email-otp/validate":
			var body map[string]any
			_ = json.NewDecoder(r.Body).Decode(&body)
			if body["code"] != "123456" {
				t.Errorf("OTP body=%#v", body)
			}
			writeJSON(map[string]any{"page": map[string]any{"type": "about_you"}, "continue_url": "/about-you"})
		case "/api/accounts/create_account":
			var body map[string]any
			_ = json.NewDecoder(r.Body).Decode(&body)
			if body["name"] != "Alex Chen" || body["birthdate"] != "1993-01-01" {
				t.Errorf("create-account body=%#v", body)
			}
			writeJSON(map[string]string{"continue_url": "/authorize/resume"})
		case "/authorize/resume":
			http.Redirect(w, r, openaiSrv.URL+"/api/auth/callback/openai?code=abc", http.StatusFound)
		case "/api/auth/callback/openai":
			if r.URL.Query().Get("code") != "abc" {
				t.Errorf("callback query=%q", r.URL.RawQuery)
			}
			http.SetCookie(w, &http.Cookie{Name: "next-auth.session-token", Value: "session-1", Path: "/"})
			w.Header().Set("Content-Type", "text/html")
			_, _ = w.Write([]byte("callback consumed"))
		case "/api/auth/session":
			writeJSON(map[string]any{"accessToken": "access-1", "user": map[string]any{"email": "user@example.com"}})
		default:
			http.NotFound(w, r)
		}
	}))
	defer openaiSrv.Close()

	expected = []requestExpectation{
		{method: http.MethodGet, path: "/api/auth/csrf", origin: openaiSrv.URL, referer: openaiSrv.URL + "/auth/login"},
		{method: http.MethodPost, path: "/api/auth/signin/openai", contentType: "application/x-www-form-urlencoded", origin: openaiSrv.URL, referer: openaiSrv.URL + "/auth/login"},
		{method: http.MethodGet, path: "/oauth/start", referer: openaiSrv.URL + "/auth/login"},
		{method: http.MethodPost, path: "/api/accounts/authorize/continue", contentType: "application/json", origin: openaiSrv.URL, referer: openaiSrv.URL + "/create-account", sentinelToken: "mock-authorize_continue", authCookies: true},
		{method: http.MethodGet, path: "/create-account/password", referer: openaiSrv.URL + "/", authCookies: true},
		{method: http.MethodPost, path: "/api/accounts/user/register", contentType: "application/json", origin: openaiSrv.URL, referer: openaiSrv.URL + "/create-account/password", sentinelToken: "mock-username_password_create", authCookies: true},
		{method: http.MethodGet, path: "/api/accounts/email-otp/send", origin: openaiSrv.URL, referer: openaiSrv.URL + "/create-account/password", authCookies: true},
		{method: http.MethodPost, path: "/api/accounts/email-otp/validate", contentType: "application/json", origin: openaiSrv.URL, referer: openaiSrv.URL + "/email-verification", authCookies: true},
		{method: http.MethodPost, path: "/api/accounts/create_account", contentType: "application/json", origin: openaiSrv.URL, referer: openaiSrv.URL + "/about-you", sentinelToken: "mock-create_account", authCookies: true},
		{method: http.MethodGet, path: "/authorize/resume", referer: openaiSrv.URL + "/", authCookies: true},
		{method: http.MethodGet, path: "/api/auth/callback/openai", referer: openaiSrv.URL + "/authorize/resume", authCookies: true},
		{method: http.MethodGet, path: "/api/auth/session", origin: openaiSrv.URL, referer: openaiSrv.URL + "/", authCookies: true, sessionCookie: true},
	}

	mailCalls := 0
	mailSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mailCalls++
		if len(r.Cookies()) != 0 {
			t.Errorf("mail request leaked auth cookies: %#v", r.Cookies())
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]string{"code": "123456"})
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

	if !resp.Success || resp.Status != "success" || resp.SessionData["accessToken"] != "access-1" || resp.SessionData["sessionToken"] != "session-1" {
		t.Fatalf("unexpected response: %#v", resp)
	}
	requestMu.Lock()
	gotRequestSteps := requestStep
	requestMu.Unlock()
	if gotRequestSteps != len(expected) || mailCalls != 1 {
		t.Fatalf("request steps=%d/%d mail calls=%d", gotRequestSteps, len(expected), mailCalls)
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
	assertSanitizedFailure(t, resp, "signin_openai", secret, "invalid_auth_state", "invalid_auth_state")
}

func TestHTTPRegisterEngineSanitizesProxyURLErrors(t *testing.T) {
	secret := "proxy-password"
	engine := register.NewHTTPRegisterEngine(register.HTTPRegisterEngineConfig{BaseURL: "http://127.0.0.1:1", ChatGPTBaseURL: "http://127.0.0.1:1"})
	resp := engine.Register(httptest.NewRequest(http.MethodPost, "/v1/register", nil), model.RegisterRequest{
		Email:    "user@example.com",
		ProxyURL: "http://proxy-user:" + secret + "@[::1",
		Options:  model.RegisterOptions{TimeoutSeconds: 2},
	})
	assertSanitizedFailure(t, resp, "http_client", secret, "register_failed", "network_error")
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

func assertSanitizedFailure(t *testing.T, resp model.RegisterResponse, step, secret, status, code string) {
	t.Helper()
	if resp.Status != status || resp.Error == nil || resp.Error.Code != code || resp.Error.Step != step {
		t.Fatalf("response=%#v", resp)
	}
	raw, _ := json.Marshal(resp)
	if strings.Contains(string(raw), secret) {
		t.Fatalf("response leaked secret %q: %s", secret, raw)
	}
}
