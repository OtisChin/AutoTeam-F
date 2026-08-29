# Go Protocol Readiness and State-Machine Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the Go protocol daemon unable to contact upstream services by default while replacing its optimistic MVP flow with deterministic transport identity, fail-closed Sentinel injection, typed auth states, correct endpoint contracts, and local session-validation parity tests.

**Architecture:** Add a readiness gate at the HTTP boundary and make the Python bridge require `protocol_ready=true`. Refactor the Go OpenAI client into endpoint-specific request builders driven by typed state responses and an injected Sentinel provider; production uses an unavailable provider, while local tests inject a static mock token. Validate the final ChatGPT session and cookie continuity before a Go registration can report success.

**Tech Stack:** Go 1.22 standard library, `httptest`, Python 3.12/pytest, Ruff

## Global Constraints

- The production daemon advertises `protocol_ready=false` and rejects `/v1/register` before invoking the engine.
- No implementation of custom challenge solving is added; Sentinel is an injected interface whose production default fails closed.
- The Go standard transport identifies itself as `go-http` and never claims a Chrome TLS profile.
- One registration owns one cookie jar from OAuth initialization through session validation.
- Unknown auth pages, HTML challenge responses, missing continuation URLs, and missing session credentials are terminal typed failures.
- All tests use local `httptest` servers; no real account registration or upstream OpenAI request is executed.

---

### Task 1: Add a production readiness gate and require it in Python

**Files:**
- Modify: `go/protocol-register/internal/model/response.go`
- Modify: `go/protocol-register/internal/register/errors.go`
- Modify: `go/protocol-register/internal/server/routes.go`
- Modify: `go/protocol-register/internal/server/server.go`
- Modify: `go/protocol-register/internal/server/routes_test.go`
- Modify: `go/protocol-register/cmd/protocol-registerd/main.go`
- Modify: `go/protocol-register/cmd/protocol-registerd/main_test.go`
- Modify: `src/autotoken/integrations/go_protocol_register_client.py`
- Modify: `tests/unit/test_go_protocol_register_client.py`

**Interfaces:**
- Produces: `server.Config{MaxConcurrency, AuthConcurrency int; ProtocolReady bool}`
- Produces: `model.ErrorInfo.RequestSent bool`
- Produces: `register.ServiceNotReadyResponse(email string)`
- Produces: `GoProtocolRegisterServiceNotReady(GoProtocolRegisterStartupUnavailable)`
- Changes: `GoProtocolRegisterClient.health()` requires both `ok=true` and `protocol_ready=true`

- [ ] **Step 1: Write failing Go readiness tests**

Add tests proving `/healthz` reports `protocol_ready=false`, `auth_concurrency`, and that `/v1/register` returns HTTP 503 with `service_not_ready`, `request_sent=false`, without invoking the engine.

```go
func TestRegisterRouteRejectsBeforeEngineWhenProtocolIsNotReady(t *testing.T) {
    engine := &countingEngine{}
    h := server.NewHandler(server.Config{
        MaxConcurrency: 7, AuthConcurrency: 3, ProtocolReady: false,
    }, engine)
    req := httptest.NewRequest(http.MethodPost, "/v1/register", strings.NewReader(`{"email":"user@example.com"}`))
    rec := httptest.NewRecorder()
    h.ServeHTTP(rec, req)

    if rec.Code != http.StatusServiceUnavailable || engine.calls != 0 {
        t.Fatalf("status=%d calls=%d body=%s", rec.Code, engine.calls, rec.Body.String())
    }
    var body model.RegisterResponse
    if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil { t.Fatal(err) }
    if body.Status != "service_not_ready" || body.Error == nil || body.Error.RequestSent {
        t.Fatalf("body=%#v", body)
    }
}
```

- [ ] **Step 2: Write the failing Python health test**

```python
def test_client_health_requires_protocol_readiness(monkeypatch):
    monkeypatch.setattr(
        go_client,
        "_json_request",
        lambda *_args, **_kwargs: {"ok": True, "protocol_ready": False},
    )
    started = []
    monkeypatch.setenv("GO_PROTOCOL_REGISTER_AUTO_START", "1")
    monkeypatch.setattr(go_client.subprocess, "Popen", lambda *a, **k: started.append((a, k)))
    with pytest.raises(go_client.GoProtocolRegisterServiceNotReady):
        GoProtocolRegisterClient(timeout=1).health()
    assert started == []
```

- [ ] **Step 3: Run readiness tests and verify RED**

```powershell
Push-Location go/protocol-register
go test -count=1 ./internal/server ./cmd/protocol-registerd
Pop-Location
$env:PYTHONPATH="$PWD/src"
& 'D:\code\OpenSource\AutoTeam-F\.venv\Scripts\python.exe' -m pytest -q tests/unit/test_go_protocol_register_client.py -k readiness
```

Expected: Go fails because `server.Config` and `RequestSent` do not exist; Python fails because health accepts `ok=true` without readiness.

- [ ] **Step 4: Implement the readiness boundary**

Use this server configuration and response contract:

```go
type Config struct {
    MaxConcurrency  int
    AuthConcurrency int
    ProtocolReady   bool
}

type ErrorInfo struct {
    Code        string `json:"code"`
    Message     string `json:"message"`
    Retryable   bool   `json:"retryable"`
    Step        string `json:"step"`
    RequestSent bool   `json:"request_sent"`
}
```

`/healthz` always reports process health plus readiness. `/v1/register` checks readiness before decoding or acquiring admission. Set `Retry-After: 30` on `service_not_ready` and `Retry-After: 1` on `busy`. The command's `loadServerConfig()` defaults to `MaxConcurrency=20`, `AuthConcurrency=3`, and `ProtocolReady=false`; do not add an environment override that can set readiness true in this phase.

In Python, `_ensure_healthy` raises `GoProtocolRegisterServiceNotReady("protocol-registerd is not protocol-ready")` when `protocol_ready` is not exactly true. `health()` propagates this subtype immediately and must not try to start another binary; connection/startup failures still use the existing auto-start path. `register_once` may treat the subtype as a startup-only fallback because no registration request was sent.

- [ ] **Step 5: Run readiness tests and verify GREEN**

Run the commands from Step 3. Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```powershell
git add go/protocol-register/internal/model/response.go go/protocol-register/internal/register/errors.go go/protocol-register/internal/server go/protocol-register/cmd/protocol-registerd src/autotoken/integrations/go_protocol_register_client.py tests/unit/test_go_protocol_register_client.py
git commit -m "fix(go-protocol): gate upstream traffic on readiness"
```

---

### Task 2: Replace randomized Chrome labels with deterministic go-http identity

**Files:**
- Modify: `go/protocol-register/internal/openai/impersonation.go`
- Create: `go/protocol-register/internal/openai/impersonation_test.go`
- Modify: `go/protocol-register/internal/openai/headers.go`
- Create: `go/protocol-register/internal/openai/headers_test.go`
- Modify: `go/protocol-register/internal/openai/auth_api.go`
- Create: `go/protocol-register/internal/openai/auth_api_test.go`
- Modify: `go/protocol-register/internal/register/state_machine_test.go`

**Interfaces:**
- Produces: `openai.TransportProfile{Name, UserAgent string}`
- Produces: `openai.ResolveTransportProfile(raw string) TransportProfile`
- Produces: `openai.APIHeaders(origin, referer, userAgent string) http.Header`
- Produces: `openai.NavigationHeaders(referer, userAgent string) http.Header`

- [ ] **Step 1: Write failing deterministic identity tests**

```go
func TestResolveTransportProfileNeverClaimsChrome(t *testing.T) {
    for _, raw := range []string{"", "chrome143,chrome152", "chrome147"} {
        got := ResolveTransportProfile(raw)
        if got.Name != "go-http" || strings.Contains(got.UserAgent, "Chrome/") {
            t.Fatalf("raw=%q profile=%#v", raw, got)
        }
    }
}
```

Add header tests asserting ChatGPT requests use ChatGPT Origin/Referer, auth requests use auth Origin/Referer, and navigation requests omit Origin.

- [ ] **Step 2: Write the failing sign-in request contract test**

Use an `httptest.Server` and assert `/api/auth/signin/openai` is POSTed as `application/x-www-form-urlencoded`, contains `csrfToken`, `callbackUrl`, and `json=true`, and uses the deterministic go-http User-Agent.

- [ ] **Step 3: Run OpenAI client tests and verify RED**

```powershell
Push-Location go/protocol-register
go test -count=1 ./internal/openai ./internal/register
Pop-Location
```

Expected: failures show randomized Chrome selection, one global Origin, and JSON instead of form encoding.

- [ ] **Step 4: Implement deterministic identity and endpoint headers**

Replace the profile pool with:

```go
type TransportProfile struct { Name, UserAgent string }

func ResolveTransportProfile(_ string) TransportProfile {
    return TransportProfile{
        Name: "go-http",
        UserAgent: "AutoToken-F protocol-registerd/go-http",
    }
}
```

Build headers per endpoint. `SigninOpenAI` must use `url.Values.Encode()` and `Content-Type: application/x-www-form-urlencoded`. Keep request bodies bounded and never include credentials in returned errors.

- [ ] **Step 5: Run OpenAI client tests and verify GREEN**

Run the command from Step 3. Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```powershell
git add go/protocol-register/internal/openai go/protocol-register/internal/register/state_machine_test.go
git commit -m "fix(go-protocol): report standard Go transport honestly"
```

---

### Task 3: Introduce fail-closed Sentinel injection and typed auth states

**Files:**
- Create: `go/protocol-register/internal/openai/sentinel.go`
- Create: `go/protocol-register/internal/openai/sentinel_test.go`
- Modify: `go/protocol-register/internal/openai/auth_api.go`
- Modify: `go/protocol-register/internal/openai/auth_api_test.go`
- Modify: `go/protocol-register/internal/register/state_machine.go`
- Modify: `go/protocol-register/internal/register/state_machine_test.go`

**Interfaces:**
- Produces: `openai.SentinelProvider.Token(ctx, httpClient, deviceID, flow) (string, error)`
- Produces: `openai.UnavailableSentinelProvider`
- Produces: `openai.ErrSentinelUnavailable`
- Produces: `openai.AuthStep{PageType, ContinueURL, EmailVerificationMode string}`
- Changes: `register.HTTPRegisterEngineConfig.SentinelProvider openai.SentinelProvider`

- [ ] **Step 1: Write failing fail-closed provider tests**

```go
func TestUnavailableSentinelProviderFailsClosed(t *testing.T) {
    _, err := (UnavailableSentinelProvider{}).Token(
        context.Background(), http.DefaultClient, "device-1", "authorize_continue",
    )
    if !errors.Is(err, ErrSentinelUnavailable) { t.Fatalf("err=%v", err) }
}
```

Add an engine test proving a nil/default provider returns `challenge_unavailable` before `/api/accounts/authorize/continue` is called.

- [ ] **Step 2: Write failing typed-state tests**

Test `AuthorizeContinue` for `create_account_password` and `email_otp_verification`, and reject an unknown page, missing continuation data, and `text/html` challenge responses as `invalid_auth_state` or `challenge_unavailable`.

- [ ] **Step 3: Run focused tests and verify RED**

```powershell
Push-Location go/protocol-register
go test -count=1 ./internal/openai ./internal/register
Pop-Location
```

Expected: failures because the provider interface, typed step, and fail-closed classification do not exist.

- [ ] **Step 4: Implement provider injection and typed states**

The production provider only returns `ErrSentinelUnavailable`; it does not fetch, execute, synthesize, or solve a challenge. The state machine requests tokens for `authorize_continue`, `username_password_create`, and `create_account`, and sends them only in `openai-sentinel-token` headers on their matching mutations.

Parse JSON responses through a 1 MiB `io.LimitReader`. Reject non-JSON or HTML responses before decoding. Only these page types are accepted in this phase: `create_account_password`, `email_otp_verification`, `about_you`, and an empty page when a validated `continue_url` is present.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run the command from Step 3. Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```powershell
git add go/protocol-register/internal/openai go/protocol-register/internal/register
git commit -m "fix(go-protocol): fail closed on unsupported auth states"
```

---

### Task 4: Validate cookie continuity and complete local state-machine parity

**Files:**
- Create: `go/protocol-register/internal/openai/session_extract.go`
- Create: `go/protocol-register/internal/openai/session_extract_test.go`
- Modify: `go/protocol-register/internal/openai/auth_api.go`
- Modify: `go/protocol-register/internal/openai/auth_api_test.go`
- Modify: `go/protocol-register/internal/register/state_machine.go`
- Rewrite: `go/protocol-register/internal/register/state_machine_test.go`

**Interfaces:**
- Produces: `openai.ExtractSession(raw map[string]any, jar http.CookieJar, chatGPTBaseURL string) (map[string]any, error)`
- Produces: `openai.ErrSessionMissing`
- Produces: `Client.InitializeOAuth(ctx, csrf) (deviceID string, error)`
- Produces: `Client.VerifyEmailOTP(ctx, code) (AuthStep, error)`
- Produces: `Client.CreateAccount(ctx, token, name, birthdate) (AuthStep, error)`
- Produces: `Client.FollowContinue(ctx, continueURL) error`

- [ ] **Step 1: Write failing session-extraction tests**

```go
func TestExtractSessionRequiresAccessAndSessionTokens(t *testing.T) {
    jar, _ := cookiejar.New(nil)
    base, _ := url.Parse("https://chatgpt.test")
    jar.SetCookies(base, []*http.Cookie{{Name: "__Secure-next-auth.session-token", Value: "session-1"}})
    got, err := ExtractSession(map[string]any{"accessToken": "access-1"}, jar, base.String())
    if err != nil || got["sessionToken"] != "session-1" { t.Fatalf("got=%#v err=%v", got, err) }
}
```

Add missing-access and missing-session cases, including reconstruction from `.0`, `.1` cookie chunks.

- [ ] **Step 2: Rewrite the local parity test and verify RED**

The mock auth server must enforce this order and contract:

```text
GET  /api/auth/csrf
POST /api/auth/signin/openai              form encoded, ChatGPT Origin
GET  /oauth/start                         sets oai-did and auth-state cookies
POST /api/accounts/authorize/continue     Sentinel authorize token, auth Origin
GET  /create-account/password
POST /api/accounts/user/register          Sentinel password token
GET  /api/accounts/email-otp/send
POST /api/accounts/email-otp/validate
POST /api/accounts/create_account         Sentinel create token
GET  /authorize/resume
GET  /api/auth/callback/openai             sets ChatGPT session cookie
GET  /api/auth/session
```

The test fails if method, content type, Origin/Referer, cookie continuity, Sentinel flow token, redirect order, endpoint path, or session credentials differ. Inject a test-only static provider that maps each flow to `mock-<flow>`.

- [ ] **Step 3: Implement corrected endpoints and session validation**

Use `/api/accounts/email-otp/validate` and `/api/accounts/create_account`. Require a device cookie after OAuth initialization. Resolve relative continuation URLs only against the configured auth base, reject other hosts, follow redirects with the same client/jar, then call `/api/auth/session` and pass the response through `ExtractSession`. A successful result is impossible without both access and session tokens.

- [ ] **Step 4: Run parity tests and verify GREEN**

```powershell
Push-Location go/protocol-register
go test -count=1 ./internal/openai ./internal/register
go test -count=20 ./internal/openai ./internal/register
Pop-Location
```

Expected: both the single run and 20 repeated runs pass.

- [ ] **Step 5: Commit**

```powershell
git add go/protocol-register/internal/openai go/protocol-register/internal/register
git commit -m "test(go-protocol): enforce local auth state parity"
```

---

### Task 5: Document readiness and run the complete phase gate

**Files:**
- Modify: `.env.example`
- Modify: `docs/configuration.md`
- Test: Python Go bridge and all Go packages

**Interfaces:**
- Consumes all Task 1-4 behavior.
- Produces the rollout contract that Go remains blocked from upstream traffic.

- [ ] **Step 1: Update configuration defaults**

Set examples to:

```dotenv
PROTOCOL_REGISTER_ENGINE=python
GO_PROTOCOL_MAX_CONCURRENCY=20
GO_PROTOCOL_AUTH_CONCURRENCY=3
GO_PROTOCOL_IMPERSONATE=go-http
```

Document that `GO_PROTOCOL_IMPERSONATE` is retained only for request compatibility and is ignored by the standard transport. State that `protocol_ready=false` is intentionally hard-coded in this phase, so selecting the Go engine causes startup-only fallback or a clear unavailable error without contacting upstream.

- [ ] **Step 2: Run complete verification**

```powershell
$env:PYTHONPATH="$PWD/src"
& 'D:\code\OpenSource\AutoTeam-F\.venv\Scripts\python.exe' -m pytest -q tests/unit/test_go_protocol_register_client.py tests/unit/test_go_protocol_register_dispatch.py tests/unit/test_account_register_task_routes.py
& 'D:\code\OpenSource\AutoTeam-F\.venv\Scripts\ruff.exe' check src/autotoken/integrations/go_protocol_register_client.py tests/unit/test_go_protocol_register_client.py
Push-Location go/protocol-register
go test -count=1 ./...
go test -count=20 ./internal/openai ./internal/register ./internal/server
go vet ./...
go build -o ../../bin/protocol-registerd-readiness.exe ./cmd/protocol-registerd
Pop-Location
```

Expected: Python tests, Ruff, all Go tests, repeated tests, vet, and build pass.

- [ ] **Step 3: Verify the built daemon manually without registration**

Start the daemon on a temporary localhost port, GET `/healthz`, and assert `ok=true` and `protocol_ready=false`. POST a local dummy `/v1/register` request and assert HTTP 503 `service_not_ready`; do not provide a real email, proxy, or mailbox URL.

- [ ] **Step 4: Check diff hygiene and commit documentation**

```powershell
git diff --check
git status --short
git add .env.example docs/configuration.md
git commit -m "docs(go-protocol): document readiness gate"
```
