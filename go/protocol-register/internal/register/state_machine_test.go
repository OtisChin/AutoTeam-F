package register_test

import (
	"autoteam-f/protocol-register/internal/fingerprint"
	"autoteam-f/protocol-register/internal/model"
	"autoteam-f/protocol-register/internal/openai"
	"autoteam-f/protocol-register/internal/register"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/cookiejar"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestHTTPRegisterEngineEnforcesLocalAuthStateParity(t *testing.T) {
	selectedProfile := mustRegisterProfile(t, "chrome144")
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
		if got := r.Header.Get("User-Agent"); got != selectedProfile.UserAgent {
			t.Errorf("%s User-Agent=%q want=%q", r.URL.Path, got, selectedProfile.UserAgent)
		}
		browserHeaders := map[string]string{
			"Sec-CH-UA":          selectedProfile.SecCHUA,
			"Sec-CH-UA-Mobile":   selectedProfile.SecCHUAMobile,
			"Sec-CH-UA-Platform": selectedProfile.SecCHUAPlatform,
			"Accept-Language":    selectedProfile.AcceptLanguage,
		}
		for name, value := range browserHeaders {
			if got := r.Header.Get(name); got != value {
				t.Errorf("%s %s=%q want=%q", r.URL.Path, name, got, value)
			}
		}
		for _, name := range []string{"Sec-Fetch-Dest", "Sec-Fetch-Mode", "Sec-Fetch-Site", "Priority"} {
			if got := r.Header.Get(name); got == "" {
				t.Errorf("%s %s is empty", r.URL.Path, name)
			}
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
		for _, name := range []string{"Sec-CH-UA", "Sec-CH-UA-Mobile", "Sec-CH-UA-Platform", "Sec-Fetch-Site", "Priority"} {
			if got := r.Header.Get(name); got != "" {
				t.Errorf("mail request leaked browser header %s=%q", name, got)
			}
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]string{"code": "123456"})
	}))
	defer mailSrv.Close()

	provider := &staticSentinelProvider{sdkVersion: "sdk-fixture-1"}
	drawCalls := 0
	profiledClientCalls := 0
	mailboxClientCalls := 0
	var profiledClient *http.Client
	engine := register.NewHTTPRegisterEngine(register.HTTPRegisterEngineConfig{
		BaseURL: openaiSrv.URL, ChatGPTBaseURL: openaiSrv.URL, SentinelProvider: provider,
		FingerprintPool: mustRegisterPool(t, fingerprint.DefaultPool),
		Draw: func(max int) (int, error) {
			drawCalls++
			if max != 3 {
				t.Fatalf("draw max=%d", max)
			}
			return 0, nil
		},
		ProfiledClientFactory: func(profile fingerprint.Profile, proxyURL string, timeout time.Duration) (*http.Client, error) {
			profiledClientCalls++
			if profile.Name != selectedProfile.Name || proxyURL != "" || timeout <= 0 {
				t.Fatalf("profiled factory profile=%s proxy=%q timeout=%s", profile.Name, proxyURL, timeout)
			}
			jar, err := cookiejar.New(nil)
			if err != nil {
				return nil, err
			}
			profiledClient = openaiSrv.Client()
			profiledClient.Jar = jar
			profiledClient.Timeout = timeout
			return profiledClient, nil
		},
		MailboxClientFactory: func(timeout time.Duration) (*http.Client, error) {
			mailboxClientCalls++
			client := mailSrv.Client()
			client.Timeout = timeout
			return client, nil
		},
	})
	resp := engine.Register(httptest.NewRequest(http.MethodPost, "/v1/register", nil), model.RegisterRequest{
		Email: "user@example.com", Password: "Password123$",
		Mail:    model.MailConfig{Provider: "generic-api", ReceiveCodeURL: mailSrv.URL},
		Options: model.RegisterOptions{TimeoutSeconds: 2, Impersonate: "chrome999"},
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
	if drawCalls != 1 || profiledClientCalls != 1 || mailboxClientCalls != 1 {
		t.Fatalf("draw=%d profiled clients=%d mailbox clients=%d", drawCalls, profiledClientCalls, mailboxClientCalls)
	}
	if resp.Metadata["fingerprint_profile"] != selectedProfile.Name || resp.Metadata["sentinel_sdk_version"] != provider.sdkVersion || len(resp.Metadata) != 2 {
		t.Fatalf("metadata=%v", resp.Metadata)
	}
	raw, ok := resp.SessionData["raw"].(map[string]any)
	if !ok || raw["source"] != "go_protocol_register" || raw["fingerprint_profile"] != selectedProfile.Name || raw["sentinel_sdk_version"] != provider.sdkVersion {
		t.Fatalf("session raw=%#v", resp.SessionData["raw"])
	}
	wantFlows := []string{"authorize_continue", "username_password_create", "create_account"}
	if len(provider.calls) != len(wantFlows) {
		t.Fatalf("sentinel calls=%#v", provider.calls)
	}
	for i, wantFlow := range wantFlows {
		if provider.calls[i].flow != wantFlow || provider.calls[i].deviceID != "device-1" ||
			provider.calls[i].profileName != selectedProfile.Name || provider.calls[i].client != profiledClient {
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

	engine := register.NewHTTPRegisterEngine(localHTTPConfig(srv.URL))
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

	engine := register.NewHTTPRegisterEngine(localHTTPConfig(openaiSrv.URL))
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

	engine := register.NewHTTPRegisterEngine(localHTTPConfig(openaiSrv.URL))
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

	engine := register.NewHTTPRegisterEngine(localHTTPConfig(openaiSrv.URL))
	resp := engine.Register(httptest.NewRequest(http.MethodPost, "/v1/register", nil), model.RegisterRequest{
		Email:   "user@example.com",
		Options: model.RegisterOptions{TimeoutSeconds: 2},
	})
	assertSanitizedFailure(t, resp, "signin_openai", secret, "invalid_auth_state", "invalid_auth_state")
}

func TestHTTPRegisterEngineDoesNotReselectProfileAfterRetryableNetworkFailure(t *testing.T) {
	drawCalls := 0
	profiledClientCalls := 0
	mailboxClientCalls := 0
	selectedProfile := mustRegisterProfile(t, "chrome144")
	engine := register.NewHTTPRegisterEngine(register.HTTPRegisterEngineConfig{
		BaseURL: "https://auth.example.test", ChatGPTBaseURL: "https://chatgpt.example.test",
		FingerprintPool: mustRegisterPool(t, fingerprint.DefaultPool),
		Draw: func(max int) (int, error) {
			drawCalls++
			if max != 3 {
				t.Fatalf("draw max=%d", max)
			}
			return 0, nil
		},
		ProfiledClientFactory: func(profile fingerprint.Profile, _ string, timeout time.Duration) (*http.Client, error) {
			profiledClientCalls++
			if profile.Name != selectedProfile.Name {
				t.Fatalf("profile=%s", profile.Name)
			}
			jar, err := cookiejar.New(nil)
			if err != nil {
				return nil, err
			}
			return &http.Client{
				Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
					return nil, errors.New("dial failed")
				}),
				Jar:     jar,
				Timeout: timeout,
			}, nil
		},
		MailboxClientFactory: func(time.Duration) (*http.Client, error) {
			mailboxClientCalls++
			return http.DefaultClient, nil
		},
	})

	resp := engine.Register(httptest.NewRequest(http.MethodPost, "/v1/register", nil), model.RegisterRequest{
		Email: "user@example.com",
		Options: model.RegisterOptions{
			TimeoutSeconds: 2,
			Impersonate:    "chrome999",
		},
	})

	if resp.Status != "register_failed" || resp.Error == nil || resp.Error.Code != "network_error" || !resp.Error.Retryable || resp.Error.Step != "csrf" {
		t.Fatalf("response=%#v", resp)
	}
	if drawCalls != 1 || profiledClientCalls != 1 || mailboxClientCalls != 0 {
		t.Fatalf("draw=%d profiled clients=%d mailbox clients=%d", drawCalls, profiledClientCalls, mailboxClientCalls)
	}
	if resp.Metadata["fingerprint_profile"] != selectedProfile.Name || len(resp.Metadata) != 1 {
		t.Fatalf("metadata=%v", resp.Metadata)
	}
}

func TestHTTPRegisterEngineAuthConcurrencyReleasesDuringMailboxPolling(t *testing.T) {
	var authActive atomic.Int32
	var maxAuthActive atomic.Int32
	var csrfCalls atomic.Int32
	firstAuthEntered := make(chan struct{})
	secondAuthEntered := make(chan struct{})
	releaseFirstAuth := make(chan struct{})
	firstSendOTPEntered := make(chan struct{})
	releaseFirstSendOTP := make(chan struct{})
	var sendOTPCalls atomic.Int32

	var authServer *httptest.Server
	authServer = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		active := authActive.Add(1)
		updateMaxInt32(&maxAuthActive, active)
		defer authActive.Add(-1)

		writeJSON := func(payload any) {
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(payload)
		}
		switch r.URL.Path {
		case "/api/auth/csrf":
			switch csrfCalls.Add(1) {
			case 1:
				close(firstAuthEntered)
				select {
				case <-releaseFirstAuth:
				case <-r.Context().Done():
					return
				}
			case 2:
				close(secondAuthEntered)
			}
			writeJSON(map[string]string{"csrfToken": "csrf-1"})
		case "/api/auth/signin/openai":
			writeJSON(map[string]string{"url": authServer.URL + "/oauth/start"})
		case "/oauth/start":
			http.SetCookie(w, &http.Cookie{Name: "oai-did", Value: "device-1", Path: "/"})
			w.WriteHeader(http.StatusOK)
		case "/api/accounts/authorize/continue":
			writeJSON(map[string]any{
				"page": map[string]any{
					"type":    "email_otp_verification",
					"payload": map[string]string{"email_verification_mode": "passwordless_signup"},
				},
				"continue_url": "/email-verification",
			})
		case "/email-verification":
			w.WriteHeader(http.StatusOK)
		case "/api/accounts/email-otp/send":
			if sendOTPCalls.Add(1) == 1 {
				close(firstSendOTPEntered)
				select {
				case <-releaseFirstSendOTP:
				case <-r.Context().Done():
					return
				}
			}
			writeJSON(map[string]bool{"ok": true})
		case "/api/accounts/email-otp/validate":
			writeJSON(map[string]any{"page": map[string]string{"type": "about_you"}, "continue_url": "/about-you"})
		case "/api/accounts/create_account":
			writeJSON(map[string]string{"continue_url": "/authorize/resume"})
		case "/authorize/resume":
			http.SetCookie(w, &http.Cookie{Name: "next-auth.session-token", Value: "session-1", Path: "/"})
			w.WriteHeader(http.StatusOK)
		case "/api/auth/session":
			writeJSON(map[string]any{"accessToken": "access-1", "user": map[string]string{"email": "user@example.com"}})
		default:
			http.NotFound(w, r)
		}
	}))
	defer authServer.Close()

	var mailInflight atomic.Int32
	var maxMailInflight atomic.Int32
	bothMailEntered := make(chan struct{})
	releaseMail := make(chan struct{})
	mailServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		inflight := mailInflight.Add(1)
		updateMaxInt32(&maxMailInflight, inflight)
		defer mailInflight.Add(-1)
		if inflight == 2 {
			close(bothMailEntered)
		}
		select {
		case <-releaseMail:
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]string{"code": "123456"})
		case <-r.Context().Done():
			return
		}
	}))
	defer mailServer.Close()

	cfg := localHTTPConfig(authServer.URL)
	cfg.AuthConcurrency = 1
	cfg.SentinelProvider = statelessSentinelProvider{}
	profiledFactory := cfg.ProfiledClientFactory
	var profiledClientCalls atomic.Int32
	secondClientReady := make(chan struct{})
	cfg.ProfiledClientFactory = func(profile fingerprint.Profile, proxyURL string, timeout time.Duration) (*http.Client, error) {
		client, err := profiledFactory(profile, proxyURL, timeout)
		if profiledClientCalls.Add(1) == 2 {
			close(secondClientReady)
		}
		return client, err
	}
	engine := register.NewHTTPRegisterEngine(cfg)
	responses := make(chan model.RegisterResponse, 2)
	registerAttempt := func(email string) {
		responses <- engine.Register(httptest.NewRequest(http.MethodPost, "/v1/register", nil), model.RegisterRequest{
			Email: email,
			Mail:  model.MailConfig{Provider: "generic-api", ReceiveCodeURL: mailServer.URL},
			Options: model.RegisterOptions{
				TimeoutSeconds: 5,
			},
		})
	}

	go registerAttempt("first@example.com")
	select {
	case <-firstAuthEntered:
	case <-time.After(time.Second):
		t.Fatal("first attempt did not enter auth")
	}
	go registerAttempt("second@example.com")
	select {
	case <-secondClientReady:
	case <-time.After(time.Second):
		close(releaseFirstAuth)
		close(releaseFirstSendOTP)
		close(releaseMail)
		t.Fatal("second attempt did not reach the auth gate")
	}
	select {
	case <-secondAuthEntered:
		close(releaseFirstAuth)
		close(releaseFirstSendOTP)
		close(releaseMail)
		t.Fatal("second attempt entered auth while first held the only slot")
	case <-time.After(50 * time.Millisecond):
	}
	close(releaseFirstAuth)
	select {
	case <-firstSendOTPEntered:
	case <-time.After(time.Second):
		close(releaseFirstSendOTP)
		close(releaseMail)
		t.Fatal("first attempt did not reach SendEmailOTP")
	}
	select {
	case <-secondAuthEntered:
		close(releaseFirstSendOTP)
		close(releaseMail)
		t.Fatal("second attempt entered auth before the first auth phase completed")
	case <-time.After(50 * time.Millisecond):
	}
	close(releaseFirstSendOTP)

	select {
	case <-bothMailEntered:
		if authActive.Load() != 0 {
			t.Fatalf("auth active while both mail pollers waited: %d", authActive.Load())
		}
	case <-time.After(2 * time.Second):
		t.Fatal("both mailbox pollers did not become inflight")
	}
	close(releaseMail)
	for range 2 {
		select {
		case resp := <-responses:
			if !resp.Success {
				t.Fatalf("response=%#v", resp)
			}
		case <-time.After(2 * time.Second):
			t.Fatal("registration attempt did not finish")
		}
	}
	if maxAuthActive.Load() != 1 || maxMailInflight.Load() != 2 || csrfCalls.Load() != 2 {
		t.Fatalf("max auth=%d max mail=%d csrf calls=%d", maxAuthActive.Load(), maxMailInflight.Load(), csrfCalls.Load())
	}
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
	client      *http.Client
	profileName string
	deviceID    string
	flow        string
}

type staticSentinelProvider struct {
	calls      []sentinelCall
	sdkVersion string
}

func (p *staticSentinelProvider) Token(_ context.Context, client *http.Client, profile fingerprint.Profile, deviceID, flow string) (openai.SentinelResult, error) {
	p.calls = append(p.calls, sentinelCall{client: client, profileName: profile.Name, deviceID: deviceID, flow: flow})
	return openai.SentinelResult{Token: "mock-" + flow, SDKVersion: p.sdkVersion}, nil
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

func localHTTPConfig(baseURL string) register.HTTPRegisterEngineConfig {
	return register.HTTPRegisterEngineConfig{
		BaseURL: baseURL, ChatGPTBaseURL: baseURL,
		Draw: func(int) (int, error) { return 0, nil },
		ProfiledClientFactory: func(_ fingerprint.Profile, _ string, timeout time.Duration) (*http.Client, error) {
			jar, err := cookiejar.New(nil)
			if err != nil {
				return nil, err
			}
			return &http.Client{
				Transport: http.DefaultTransport.(*http.Transport).Clone(),
				Jar:       jar,
				Timeout:   timeout,
			}, nil
		},
		MailboxClientFactory: func(timeout time.Duration) (*http.Client, error) {
			jar, err := cookiejar.New(nil)
			if err != nil {
				return nil, err
			}
			return &http.Client{
				Transport: http.DefaultTransport.(*http.Transport).Clone(),
				Jar:       jar,
				Timeout:   timeout,
			}, nil
		},
	}
}

func mustRegisterProfile(t *testing.T, name string) fingerprint.Profile {
	t.Helper()
	profile, ok := fingerprint.Lookup(name)
	if !ok {
		t.Fatalf("profile %q was not found", name)
	}
	return profile
}

func mustRegisterPool(t *testing.T, raw string) fingerprint.Pool {
	t.Helper()
	pool, err := fingerprint.ParsePool(raw)
	if err != nil {
		t.Fatalf("ParsePool(%q) error=%v", raw, err)
	}
	return pool
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(req *http.Request) (*http.Response, error) {
	return f(req)
}

type statelessSentinelProvider struct{}

func (statelessSentinelProvider) Token(_ context.Context, _ *http.Client, _ fingerprint.Profile, _ string, flow string) (openai.SentinelResult, error) {
	return openai.SentinelResult{Token: "mock-" + flow, SDKVersion: "sdk-concurrency-1"}, nil
}

func updateMaxInt32(maximum *atomic.Int32, candidate int32) {
	for current := maximum.Load(); candidate > current; current = maximum.Load() {
		if maximum.CompareAndSwap(current, candidate) {
			return
		}
	}
}
