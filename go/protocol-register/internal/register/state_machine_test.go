package register_test

import (
	"autoteam-f/protocol-register/internal/model"
	"autoteam-f/protocol-register/internal/register"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestHTTPRegisterEngineSuccessWithMockOpenAIAndMail(t *testing.T) {
	hits := map[string]int{}
	openaiSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits[r.URL.Path]++
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

	engine := register.NewHTTPRegisterEngine(register.HTTPRegisterEngineConfig{BaseURL: openaiSrv.URL, ChatGPTBaseURL: openaiSrv.URL})
	resp := engine.Register(httptest.NewRequest(http.MethodPost, "/v1/register", nil), model.RegisterRequest{
		Email: "user@example.com", Password: "Password123$",
		Mail:    model.MailConfig{Provider: "generic-api", ReceiveCodeURL: mailSrv.URL},
		Options: model.RegisterOptions{TimeoutSeconds: 2},
	})
	if !resp.Success || resp.Status != "success" || resp.SessionData["accessToken"] != "access-1" {
		t.Fatalf("unexpected response: %#v", resp)
	}
	for _, path := range []string{"/api/auth/csrf", "/api/auth/signin/openai", "/api/accounts/authorize/continue", "/api/accounts/user/register", "/api/accounts/email-otp/send", "/api/accounts/email-otp/verify", "/api/accounts/profile", "/api/auth/session"} {
		if hits[path] == 0 {
			t.Fatalf("expected hit for %s, hits=%#v", path, hits)
		}
	}
}

func TestHTTPRegisterEngineNormalizesNetworkFailureStatus(t *testing.T) {
	openaiSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "upstream unavailable", http.StatusBadGateway)
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
}
