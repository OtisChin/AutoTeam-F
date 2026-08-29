### Task 4: Go Email-First Registration State Machine

**Files:**
- Create: `go/protocol-register/internal/register/progress.go`
- Create: `go/protocol-register/internal/register/state_machine.go`
- Create: `go/protocol-register/internal/register/state_machine_test.go`
- Create: `go/protocol-register/internal/openai/headers.go`
- Create: `go/protocol-register/internal/openai/auth_api.go`
- Modify: `go/protocol-register/cmd/protocol-registerd/main.go`

**Interfaces:**
- Produces: `register.NewHTTPRegisterEngine(register.HTTPRegisterEngineConfig) *register.HTTPRegisterEngine`.
- Produces: `openai.Client` methods for phase-1 endpoints.
- Consumes: `httpclient.New`, `mailbridge.NewClient`.

- [ ] **Step 1: Write failing mocked success test**

Create `go/protocol-register/internal/register/state_machine_test.go`:

```go
package register_test

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"autoteam-f/protocol-register/internal/model"
	"autoteam-f/protocol-register/internal/register"
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
		Mail: model.MailConfig{Provider: "generic-api", ReceiveCodeURL: mailSrv.URL},
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
```

- [ ] **Step 2: Run test to verify failure**

Run:

```powershell
cd go/protocol-register
go test ./internal/register -run TestHTTPRegisterEngineSuccessWithMockOpenAIAndMail -v
```

Expected: FAIL because `NewHTTPRegisterEngine` and OpenAI client methods do not exist.

- [ ] **Step 3: Implement OpenAI client and state machine**

Create `go/protocol-register/internal/openai/headers.go`:

```go
package openai

import "net/http"

const UserAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"

func CommonHeaders(referer string) http.Header {
	h := http.Header{}
	h.Set("User-Agent", UserAgent)
	h.Set("Accept", "application/json,text/html,*/*")
	h.Set("Referer", referer)
	h.Set("Origin", "https://auth.openai.com")
	return h
}
```

Create `go/protocol-register/internal/openai/auth_api.go`:

```go
package openai

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
)

type Client struct {
	HTTP           *http.Client
	BaseURL        string
	ChatGPTBaseURL string
}

func NewClient(httpClient *http.Client, baseURL, chatGPTBaseURL string) *Client {
	if baseURL == "" {
		baseURL = "https://auth.openai.com"
	}
	if chatGPTBaseURL == "" {
		chatGPTBaseURL = "https://chatgpt.com"
	}
	return &Client{HTTP: httpClient, BaseURL: baseURL, ChatGPTBaseURL: chatGPTBaseURL}
}

func (c *Client) GetCSRF(ctx context.Context) (string, error) {
	var out struct{ CSRFToken string `json:"csrfToken"` }
	if err := c.doJSON(ctx, http.MethodGet, c.ChatGPTBaseURL+"/api/auth/csrf", nil, &out); err != nil {
		return "", err
	}
	if out.CSRFToken == "" {
		return "", fmt.Errorf("csrf token missing")
	}
	return out.CSRFToken, nil
}

func (c *Client) SigninOpenAI(ctx context.Context, csrf string) error {
	var out struct{ URL string `json:"url"` }
	err := c.doJSON(ctx, http.MethodPost, c.ChatGPTBaseURL+"/api/auth/signin/openai", map[string]any{"csrfToken": csrf, "callbackUrl": c.ChatGPTBaseURL + "/", "json": "true"}, &out)
	if err != nil {
		return err
	}
	if out.URL == "" {
		return fmt.Errorf("auth url missing")
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, out.URL, nil)
	if err != nil {
		return err
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return err
	}
	resp.Body.Close()
	return nil
}

func (c *Client) AuthorizeContinue(ctx context.Context, email string) (string, error) {
	var out struct{ Page struct{ Type string `json:"type"` } `json:"page"` }
	err := c.doJSON(ctx, http.MethodPost, c.BaseURL+"/api/accounts/authorize/continue", map[string]any{"username": map[string]any{"value": email, "kind": "email"}, "screen_hint": "signup"}, &out)
	return out.Page.Type, err
}

func (c *Client) RegisterPassword(ctx context.Context, email, password string) error {
	return c.doJSON(ctx, http.MethodPost, c.BaseURL+"/api/accounts/user/register", map[string]any{"password": password, "username": email}, nil)
}

func (c *Client) SendEmailOTP(ctx context.Context) error {
	return c.doJSON(ctx, http.MethodGet, c.BaseURL+"/api/accounts/email-otp/send", nil, nil)
}

func (c *Client) VerifyEmailOTP(ctx context.Context, code string) (string, error) {
	var out struct{ ContinueURL string `json:"continue_url"` }
	err := c.doJSON(ctx, http.MethodPost, c.BaseURL+"/api/accounts/email-otp/verify", map[string]any{"code": code}, &out)
	return out.ContinueURL, err
}

func (c *Client) CreateAccount(ctx context.Context) error {
	return c.doJSON(ctx, http.MethodPost, c.BaseURL+"/api/accounts/profile", map[string]any{"name": "Alex Chen", "age": 33}, nil)
}

func (c *Client) GetAuthSession(ctx context.Context) (map[string]any, error) {
	var out map[string]any
	err := c.doJSON(ctx, http.MethodGet, c.ChatGPTBaseURL+"/api/auth/session", nil, &out)
	return out, err
}

func (c *Client) doJSON(ctx context.Context, method, url string, payload any, out any) error {
	var body io.Reader
	if payload != nil {
		raw, _ := json.Marshal(payload)
		body = bytes.NewReader(raw)
	}
	req, err := http.NewRequestWithContext(ctx, method, url, body)
	if err != nil {
		return err
	}
	for key, values := range CommonHeaders(c.ChatGPTBaseURL + "/") {
		for _, value := range values {
			req.Header.Add(key, value)
		}
	}
	if payload != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		raw, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return fmt.Errorf("%s %s: HTTP %d %s", method, url, resp.StatusCode, string(raw))
	}
	if out == nil {
		return nil
	}
	return json.NewDecoder(resp.Body).Decode(out)
}
```

Create `go/protocol-register/internal/register/progress.go`:

```go
package register

import "autoteam-f/protocol-register/internal/model"

type Progress struct{ events []model.Event }

func (p *Progress) Add(stage, message string, extra map[string]any) {
	p.events = append(p.events, model.Event{Stage: stage, Message: message, Extra: extra})
}

func (p *Progress) Events() []model.Event {
	out := make([]model.Event, len(p.events))
	copy(out, p.events)
	return out
}
```

Create `go/protocol-register/internal/register/state_machine.go`:

```go
package register

import (
	"context"
	"fmt"
	"net/http"
	"time"
	"autoteam-f/protocol-register/internal/httpclient"
	"autoteam-f/protocol-register/internal/mailbridge"
	"autoteam-f/protocol-register/internal/model"
	"autoteam-f/protocol-register/internal/openai"
)

type HTTPRegisterEngineConfig struct{ BaseURL, ChatGPTBaseURL string }
type HTTPRegisterEngine struct{ cfg HTTPRegisterEngineConfig }

func NewHTTPRegisterEngine(cfg HTTPRegisterEngineConfig) *HTTPRegisterEngine { return &HTTPRegisterEngine{cfg: cfg} }

func (e *HTTPRegisterEngine) Register(r *http.Request, req model.RegisterRequest) model.RegisterResponse {
	progress := &Progress{}
	timeout := time.Duration(req.Options.TimeoutSeconds) * time.Second
	if timeout <= 0 {
		timeout = 60 * time.Second
	}
	ctx, cancel := context.WithTimeout(r.Context(), timeout)
	defer cancel()
	client, err := httpclient.New(req.ProxyURL, timeout+30*time.Second)
	if err != nil {
		return fail(req.Email, "network_error", err.Error(), "http_client", true, progress.Events())
	}
	api := openai.NewClient(client, e.cfg.BaseURL, e.cfg.ChatGPTBaseURL)
	csrf, err := api.GetCSRF(ctx)
	if err != nil {
		return fail(req.Email, "network_error", err.Error(), "csrf", true, progress.Events())
	}
	progress.Add("csrf", "csrf token acquired", nil)
	if err := api.SigninOpenAI(ctx, csrf); err != nil {
		return fail(req.Email, "network_error", err.Error(), "signin_openai", true, progress.Events())
	}
	pageType, err := api.AuthorizeContinue(ctx, req.Email)
	if err != nil {
		return fail(req.Email, "register_failed", err.Error(), "authorize_continue", true, progress.Events())
	}
	progress.Add("email_submitted", "email accepted", map[string]any{"page_type": pageType})
	if pageType == "create_account_password" {
		if err := api.RegisterPassword(ctx, req.Email, req.Password); err != nil {
			return fail(req.Email, "register_failed", err.Error(), "register_password", true, progress.Events())
		}
	}
	if err := api.SendEmailOTP(ctx); err != nil {
		return fail(req.Email, "register_failed", err.Error(), "send_email_otp", true, progress.Events())
	}
	code, err := mailbridge.NewClient(client, 3*time.Second).WaitForOTP(ctx, req.Mail.ReceiveCodeURL)
	if err != nil {
		return fail(req.Email, "email_code_timeout", "email OTP not received within timeout", "email_otp", false, progress.Events())
	}
	if _, err := api.VerifyEmailOTP(ctx, code); err != nil {
		return fail(req.Email, "register_failed", err.Error(), "verify_email_otp", true, progress.Events())
	}
	progress.Add("otp_verified", "email OTP verified", nil)
	if err := api.CreateAccount(ctx); err != nil {
		return fail(req.Email, "phone_blocked", err.Error(), "create_account", false, progress.Events())
	}
	sessionData, err := api.GetAuthSession(ctx)
	if err != nil {
		return fail(req.Email, "register_failed", err.Error(), "auth_session", true, progress.Events())
	}
	sessionData["email"] = req.Email
	sessionData["raw"] = map[string]any{"source": "go_protocol_register"}
	return model.RegisterResponse{Success: true, Status: "success", Email: req.Email, SessionData: sessionData, Events: progress.Events()}
}

func fail(email, status, message, step string, retryable bool, events []model.Event) model.RegisterResponse {
	code := status
	if status == "phone_blocked" {
		code = "phone_required"
	}
	if message == "" {
		message = fmt.Sprintf("%s at %s", status, step)
	}
	return model.RegisterResponse{Success: false, Status: status, Email: email, Error: &model.ErrorInfo{Code: code, Message: message, Retryable: retryable, Step: step}, Events: events}
}
```

Modify `go/protocol-register/cmd/protocol-registerd/main.go` to use:

```go
engine := register.NewHTTPRegisterEngine(register.HTTPRegisterEngineConfig{})
srv := server.New(addr, maxConcurrency, engine)
```

and import:

```go
"autoteam-f/protocol-register/internal/register"
```

- [ ] **Step 4: Run tests and commit**

Run:

```powershell
cd go/protocol-register
go test ./...
cd ..\..
git add go/protocol-register
git commit -m "feat(protocol): add Go email registration state machine"
```

Expected: Go tests PASS and commit succeeds.

---

