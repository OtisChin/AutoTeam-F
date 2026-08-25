# Go Protocol Register Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a high-concurrency Go HTTP service for phase-1 email-first protocol registration and integrate Python `register_mode=protocol` with opt-in Go execution plus Python fallback.

**Architecture:** Add `go/protocol-register` as a local Go service (`protocol-registerd`) with `/healthz` and `/v1/register`. Python keeps task orchestration, mailbox selection, account persistence, and auth-session saving; Go handles the protocol HTTP state machine, direct receive-code OTP polling, bounded concurrency, and structured result mapping.

**Tech Stack:** Go 1.22+ standard library HTTP server/client, Python 3.12+/pytest, existing AutoToken manager/protocol-register interfaces, JSON contract fixtures.

## Global Constraints

- Bind Go service to loopback by default: `127.0.0.1:18787`.
- Default engine remains Python: `PROTOCOL_REGISTER_ENGINE=python`.
- Go engine is opt-in with `PROTOCOL_REGISTER_ENGINE=go`.
- Phase 1 supports email-first protocol registration only.
- Phase 1 does not migrate Browser/RoxyBrowser/CloakBrowser registration.
- Phase 1 does not migrate Codex OAuth after registration.
- Phase 1 does not migrate phone-first, phone-only, or SMS-provider flows.
- Go must not persist accounts or write `data/auth_session`; Python remains persistence owner.
- Go responses must map to Python-compatible statuses: `success`, `email_code_timeout`, `phone_blocked`, `account_deactivated`, `register_failed`, `exception`.
- Redact passwords, cookies, session tokens, OTP links, and API keys from service logs.
- Every behavior-bearing task uses test-first implementation.

---

## File Structure

Create:

- `go/protocol-register/go.mod`
- `go/protocol-register/cmd/protocol-registerd/main.go`
- `go/protocol-register/internal/model/request.go`
- `go/protocol-register/internal/model/response.go`
- `go/protocol-register/internal/server/server.go`
- `go/protocol-register/internal/server/routes.go`
- `go/protocol-register/internal/register/engine.go`
- `go/protocol-register/internal/register/errors.go`
- `go/protocol-register/internal/register/progress.go`
- `go/protocol-register/internal/register/state_machine.go`
- `go/protocol-register/internal/openai/auth_api.go`
- `go/protocol-register/internal/openai/headers.go`
- `go/protocol-register/internal/httpclient/client.go`
- `go/protocol-register/internal/mailbridge/client.go`
- `go/protocol-register/internal/mailbridge/otp.go`
- `src/autotoken/integrations/go_protocol_register_client.py`
- `tests/unit/test_go_protocol_register_client.py`
- `tests/unit/test_go_protocol_register_dispatch.py`
- `tests/fixtures/go_protocol_register/register_request_generic_api.json`
- `tests/fixtures/go_protocol_register/register_success_response.json`
- `tests/fixtures/go_protocol_register/email_code_timeout_response.json`
- `tests/fixtures/go_protocol_register/phone_required_response.json`
- `scripts/build-go-protocol-register.ps1`
- `.tmp/run_go_protocol_register_realtest.py`
- `.tmp/bench_go_protocol_register.py`

Modify:

- `src/autotoken/auth/protocol_register.py`
- `.env.example`
- `docs/configuration.md`

---

### Task 1: Python-Go Contract and Client Wrapper

**Files:**
- Create: `tests/fixtures/go_protocol_register/register_request_generic_api.json`
- Create: `tests/fixtures/go_protocol_register/register_success_response.json`
- Create: `tests/fixtures/go_protocol_register/email_code_timeout_response.json`
- Create: `tests/fixtures/go_protocol_register/phone_required_response.json`
- Create: `tests/unit/test_go_protocol_register_client.py`
- Create: `src/autotoken/integrations/go_protocol_register_client.py`

**Interfaces:**
- Produces: `GoProtocolRegisterClient(base_url: str | None = None, timeout: float = 190.0)`.
- Produces: `GoProtocolRegisterClient.health() -> dict[str, Any]`.
- Produces: `GoProtocolRegisterClient.register(payload: dict[str, Any]) -> dict[str, Any]`.
- Produces: `go_response_to_protocol_result(response: dict[str, Any]) -> tuple[bool, dict[str, Any]]`.

- [ ] **Step 1: Write contract fixtures**

Create `tests/fixtures/go_protocol_register/register_request_generic_api.json`:

```json
{
  "request_id": "test-request-1",
  "email": "user@example.com",
  "password": "Password123$",
  "proxy_url": "",
  "mail": {
    "provider": "generic-api",
    "account_id": "user@example.com",
    "receive_code_url": "https://mail.example.test/mail-api/code?to=user%40example.com&timeout=60&key=secret-key",
    "issued_after_unix": 1787650000
  },
  "options": {
    "timeout_seconds": 180,
    "trace": false,
    "impersonate": "chrome136"
  }
}
```

Create `tests/fixtures/go_protocol_register/register_success_response.json`:

```json
{
  "success": true,
  "status": "success",
  "email": "user@example.com",
  "session_data": {
    "email": "user@example.com",
    "accessToken": "access-token-1",
    "sessionToken": "session-token-1",
    "cookies": [],
    "raw": {"source": "go_protocol_register"}
  },
  "events": [{"stage": "otp_verified", "message": "email OTP verified"}]
}
```

Create `tests/fixtures/go_protocol_register/email_code_timeout_response.json`:

```json
{
  "success": false,
  "status": "email_code_timeout",
  "email": "user@example.com",
  "error": {
    "code": "email_code_timeout",
    "message": "email OTP not received within timeout",
    "retryable": false,
    "step": "email_otp"
  },
  "events": []
}
```

Create `tests/fixtures/go_protocol_register/phone_required_response.json`:

```json
{
  "success": false,
  "status": "phone_blocked",
  "email": "user@example.com",
  "error": {
    "code": "phone_required",
    "message": "OpenAI requested phone verification",
    "retryable": false,
    "step": "create_account"
  },
  "events": [{"stage": "phone_required", "message": "phone verification required"}]
}
```

- [ ] **Step 2: Write failing Python tests**

Create `tests/unit/test_go_protocol_register_client.py`:

```python
import json
from pathlib import Path

import pytest

from autotoken.integrations.go_protocol_register_client import (
    GoProtocolRegisterClient,
    GoProtocolRegisterUnavailable,
    go_response_to_protocol_result,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "go_protocol_register"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_success_response_maps_to_protocol_result():
    ok, session_data = go_response_to_protocol_result(_fixture("register_success_response.json"))
    assert ok is True
    assert session_data["email"] == "user@example.com"
    assert session_data["accessToken"] == "access-token-1"
    assert session_data["sessionToken"] == "session-token-1"
    assert session_data["raw"]["source"] == "go_protocol_register"


def test_timeout_response_maps_to_failure_payload():
    ok, session_data = go_response_to_protocol_result(_fixture("email_code_timeout_response.json"))
    assert ok is False
    assert session_data["status"] == "email_code_timeout"
    assert session_data["reason"] == "email OTP not received within timeout"
    assert session_data["error"]["code"] == "email_code_timeout"


def test_phone_required_response_maps_to_phone_blocked():
    ok, session_data = go_response_to_protocol_result(_fixture("phone_required_response.json"))
    assert ok is False
    assert session_data["status"] == "phone_blocked"
    assert session_data["reason"] == "OpenAI requested phone verification"


def test_client_health_raises_unavailable_for_connection_error():
    client = GoProtocolRegisterClient(base_url="http://127.0.0.1:9", timeout=0.01)
    with pytest.raises(GoProtocolRegisterUnavailable):
        client.health()
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'
uv run --no-sync pytest tests/unit/test_go_protocol_register_client.py -q
```

Expected: FAIL because `src/autotoken/integrations/go_protocol_register_client.py` does not exist.

- [ ] **Step 4: Implement minimal Python client**

Create `src/autotoken/integrations/go_protocol_register_client.py`:

```python
from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


class GoProtocolRegisterUnavailable(RuntimeError):
    pass


def _base_url(value: str | None = None) -> str:
    return str(value or os.environ.get("GO_PROTOCOL_REGISTER_URL") or "http://127.0.0.1:18787").rstrip("/")


def _json_request(url: str, payload: dict[str, Any] | None = None, *, timeout: float = 190.0) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers={"Accept": "application/json"})
    if payload is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except (OSError, URLError, TimeoutError) as exc:
        raise GoProtocolRegisterUnavailable(str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise GoProtocolRegisterUnavailable(f"invalid Go protocol-register JSON response: {exc}") from exc


class GoProtocolRegisterClient:
    def __init__(self, base_url: str | None = None, timeout: float = 190.0):
        self.base_url = _base_url(base_url)
        self.timeout = float(timeout or 190.0)

    def health(self) -> dict[str, Any]:
        return _json_request(f"{self.base_url}/healthz", timeout=min(self.timeout, 5.0))

    def register(self, payload: dict[str, Any]) -> dict[str, Any]:
        return _json_request(f"{self.base_url}/v1/register", payload, timeout=self.timeout)


def go_response_to_protocol_result(response: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    if bool(response.get("success")):
        session_data = dict(response.get("session_data") or {})
        session_data.setdefault("email", response.get("email") or "")
        raw = dict(session_data.get("raw") or {})
        raw.setdefault("source", "go_protocol_register")
        session_data["raw"] = raw
        return True, session_data

    error = dict(response.get("error") or {})
    reason = str(error.get("message") or response.get("status") or "go protocol register failed")
    return False, {
        "status": str(response.get("status") or error.get("code") or "register_failed"),
        "email": str(response.get("email") or ""),
        "reason": reason,
        "error": error,
        "events": list(response.get("events") or []),
        "raw": {"source": "go_protocol_register", "response": response},
    }
```

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
uv run --no-sync pytest tests/unit/test_go_protocol_register_client.py -q
git add src/autotoken/integrations/go_protocol_register_client.py tests/unit/test_go_protocol_register_client.py tests/fixtures/go_protocol_register
git commit -m "feat(protocol): add Go register client contract"
```

Expected: tests PASS and commit succeeds.

---

### Task 2: Go HTTP Service Skeleton and Bounded Admission

**Files:**
- Create: `go/protocol-register/go.mod`
- Create: `go/protocol-register/cmd/protocol-registerd/main.go`
- Create: `go/protocol-register/internal/model/request.go`
- Create: `go/protocol-register/internal/model/response.go`
- Create: `go/protocol-register/internal/server/server.go`
- Create: `go/protocol-register/internal/server/routes.go`
- Create: `go/protocol-register/internal/register/engine.go`
- Create: `go/protocol-register/internal/register/errors.go`
- Create: `go/protocol-register/internal/server/routes_test.go`

**Interfaces:**
- Produces: Go module `autoteam-f/protocol-register`.
- Produces: `server.New(addr string, maxConcurrency int, engine register.Engine) *http.Server`.
- Produces: `/healthz` and `/v1/register`.

- [ ] **Step 1: Write failing Go route tests**

Create `go/protocol-register/internal/server/routes_test.go`:

```go
package server_test

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"autoteam-f/protocol-register/internal/model"
	"autoteam-f/protocol-register/internal/register"
	"autoteam-f/protocol-register/internal/server"
)

type fakeEngine struct{ release <-chan struct{} }

func (e fakeEngine) Register(_ *http.Request, req model.RegisterRequest) model.RegisterResponse {
	if e.release != nil {
		<-e.release
	}
	return model.RegisterResponse{Success: true, Status: "success", Email: req.Email, Events: []model.Event{}}
}

var _ register.Engine = fakeEngine{}

func TestHealthz(t *testing.T) {
	h := server.NewHandler(7, fakeEngine{})
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status=%d", rec.Code)
	}
	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	if body["ok"] != true || body["service"] != "protocol-registerd" || int(body["max_concurrency"].(float64)) != 7 {
		t.Fatalf("body=%#v", body)
	}
}

func TestRegisterRouteRejectsWhenConcurrencyLimitIsReached(t *testing.T) {
	release := make(chan struct{})
	h := server.NewHandler(1, fakeEngine{release: release})
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		req := httptest.NewRequest(http.MethodPost, "/v1/register", strings.NewReader(`{"email":"one@example.com"}`))
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, req)
	}()
	time.Sleep(50 * time.Millisecond)
	req := httptest.NewRequest(http.MethodPost, "/v1/register", strings.NewReader(`{"email":"two@example.com"}`))
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	close(release)
	wg.Wait()
	if rec.Code != http.StatusTooManyRequests {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
}
```

- [ ] **Step 2: Run Go tests to verify failure**

Run:

```powershell
cd go/protocol-register
go test ./...
```

Expected: FAIL because Go module and packages are missing.

- [ ] **Step 3: Implement module, models, engine, errors, routes, CLI**

Create `go/protocol-register/go.mod`:

```go
module autoteam-f/protocol-register

go 1.22
```

Create `go/protocol-register/internal/model/request.go`:

```go
package model

type MailConfig struct {
	Provider        string `json:"provider"`
	AccountID       string `json:"account_id"`
	ReceiveCodeURL string `json:"receive_code_url"`
	IssuedAfterUnix int64  `json:"issued_after_unix"`
}

type RegisterOptions struct {
	TimeoutSeconds int    `json:"timeout_seconds"`
	Trace          bool   `json:"trace"`
	Impersonate    string `json:"impersonate"`
}

type RegisterRequest struct {
	RequestID string          `json:"request_id"`
	Email     string          `json:"email"`
	Password  string          `json:"password"`
	ProxyURL  string          `json:"proxy_url"`
	Mail      MailConfig      `json:"mail"`
	Options   RegisterOptions `json:"options"`
}
```

Create `go/protocol-register/internal/model/response.go`:

```go
package model

type Event struct {
	Stage   string         `json:"stage"`
	Message string         `json:"message"`
	Extra   map[string]any `json:"extra,omitempty"`
}

type ErrorInfo struct {
	Code      string `json:"code"`
	Message   string `json:"message"`
	Retryable bool   `json:"retryable"`
	Step      string `json:"step"`
}

type RegisterResponse struct {
	Success     bool           `json:"success"`
	Status      string         `json:"status"`
	Email       string         `json:"email"`
	SessionData map[string]any `json:"session_data,omitempty"`
	Error       *ErrorInfo     `json:"error,omitempty"`
	Events      []Event        `json:"events"`
}
```

Create `go/protocol-register/internal/register/engine.go`:

```go
package register

import (
	"net/http"
	"autoteam-f/protocol-register/internal/model"
)

type Engine interface {
	Register(r *http.Request, req model.RegisterRequest) model.RegisterResponse
}
```

Create `go/protocol-register/internal/register/errors.go`:

```go
package register

import "autoteam-f/protocol-register/internal/model"

func BusyResponse(email string) model.RegisterResponse {
	return model.RegisterResponse{
		Success: false,
		Status:  "busy",
		Email:   email,
		Error:   &model.ErrorInfo{Code: "busy", Message: "protocol-registerd concurrency limit reached", Retryable: true, Step: "admission"},
		Events:  []model.Event{},
	}
}
```

Create `go/protocol-register/internal/server/routes.go`:

```go
package server

import (
	"encoding/json"
	"net/http"
	"autoteam-f/protocol-register/internal/model"
	"autoteam-f/protocol-register/internal/register"
)

type Handler struct {
	maxConcurrency int
	engine         register.Engine
	sem            chan struct{}
}

func NewHandler(maxConcurrency int, engine register.Engine) http.Handler {
	if maxConcurrency <= 0 {
		maxConcurrency = 50
	}
	return &Handler{maxConcurrency: maxConcurrency, engine: engine, sem: make(chan struct{}, maxConcurrency)}
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	switch {
	case r.Method == http.MethodGet && r.URL.Path == "/healthz":
		writeJSON(w, http.StatusOK, map[string]any{"ok": true, "service": "protocol-registerd", "version": "dev", "max_concurrency": h.maxConcurrency, "inflight": len(h.sem)})
	case r.Method == http.MethodPost && r.URL.Path == "/v1/register":
		var req model.RegisterRequest
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20)).Decode(&req); err != nil {
			writeJSON(w, http.StatusBadRequest, model.RegisterResponse{Success: false, Status: "bad_request", Error: &model.ErrorInfo{Code: "bad_request", Message: err.Error(), Step: "decode"}, Events: []model.Event{}})
			return
		}
		select {
		case h.sem <- struct{}{}:
			defer func() { <-h.sem }()
		default:
			writeJSON(w, http.StatusTooManyRequests, register.BusyResponse(req.Email))
			return
		}
		writeJSON(w, http.StatusOK, h.engine.Register(r, req))
	default:
		writeJSON(w, http.StatusNotFound, map[string]any{"ok": false, "error": "not found"})
	}
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}
```

Create `go/protocol-register/internal/server/server.go`:

```go
package server

import (
	"net/http"
	"autoteam-f/protocol-register/internal/register"
)

func New(addr string, maxConcurrency int, engine register.Engine) *http.Server {
	return &http.Server{Addr: addr, Handler: NewHandler(maxConcurrency, engine)}
}
```

Create `go/protocol-register/cmd/protocol-registerd/main.go`:

```go
package main

import (
	"log"
	"net/http"
	"os"
	"strconv"
	"autoteam-f/protocol-register/internal/model"
	"autoteam-f/protocol-register/internal/server"
)

type notImplementedEngine struct{}

func (notImplementedEngine) Register(_ *http.Request, req model.RegisterRequest) model.RegisterResponse {
	return model.RegisterResponse{Success: false, Status: "not_implemented", Email: req.Email, Error: &model.ErrorInfo{Code: "not_implemented", Message: "registration engine not enabled", Step: "register"}, Events: []model.Event{}}
}

func main() {
	addr := os.Getenv("GO_PROTOCOL_REGISTER_ADDR")
	if addr == "" {
		addr = "127.0.0.1:18787"
	}
	maxConcurrency := 50
	if raw := os.Getenv("GO_PROTOCOL_MAX_CONCURRENCY"); raw != "" {
		if parsed, err := strconv.Atoi(raw); err == nil && parsed > 0 {
			maxConcurrency = parsed
		}
	}
	srv := server.New(addr, maxConcurrency, notImplementedEngine{})
	log.Printf("protocol-registerd listening on %s max_concurrency=%d", addr, maxConcurrency)
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatal(err)
	}
}
```

- [ ] **Step 4: Run tests and commit**

Run:

```powershell
cd go/protocol-register
go test ./...
cd ..\..
git add go/protocol-register
git commit -m "feat(protocol): scaffold Go register service"
```

Expected: Go tests PASS and commit succeeds.

---

### Task 3: Go HTTP Client and Mail OTP Polling

**Files:**
- Create: `go/protocol-register/internal/httpclient/client.go`
- Create: `go/protocol-register/internal/mailbridge/client.go`
- Create: `go/protocol-register/internal/mailbridge/otp.go`
- Create: `go/protocol-register/internal/mailbridge/otp_test.go`

**Interfaces:**
- Produces: `httpclient.New(proxyURL string, timeout time.Duration) (*http.Client, error)`.
- Produces: `mailbridge.ExtractOTP(payload []byte) string`.
- Produces: `mailbridge.Client.WaitForOTP(ctx context.Context, receiveCodeURL string) (string, error)`.

- [ ] **Step 1: Write failing OTP tests**

Create `go/protocol-register/internal/mailbridge/otp_test.go`:

```go
package mailbridge_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
	"autoteam-f/protocol-register/internal/mailbridge"
)

func TestExtractOTPFromJSONAndHTML(t *testing.T) {
	for _, input := range [][]byte{
		[]byte(`{"ok":true,"code":"013555"}`),
		[]byte(`{"mail":{"content":"Use 246810 to continue"}}`),
		[]byte(`<html>Your OpenAI verification code is <b>135790</b></html>`),
	} {
		if got := mailbridge.ExtractOTP(input); got == "" {
			t.Fatalf("missing code from %s", input)
		}
	}
}

func TestWaitForOTPPollsUntilCode(t *testing.T) {
	calls := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		if calls < 2 {
			w.WriteHeader(http.StatusNotFound)
			_, _ = w.Write([]byte(`{"ok":false}`))
			return
		}
		_, _ = w.Write([]byte(`{"code":"112233"}`))
	}))
	defer srv.Close()
	client := mailbridge.NewClient(srv.Client(), 10*time.Millisecond)
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	code, err := client.WaitForOTP(ctx, srv.URL)
	if err != nil || code != "112233" {
		t.Fatalf("code=%q err=%v", code, err)
	}
}
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
cd go/protocol-register
go test ./internal/mailbridge -run Test -v
```

Expected: FAIL because package implementation is missing.

- [ ] **Step 3: Implement HTTP client and mailbridge**

Create `go/protocol-register/internal/httpclient/client.go`:

```go
package httpclient

import (
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"time"
)

func New(proxyURL string, timeout time.Duration) (*http.Client, error) {
	transport := http.DefaultTransport.(*http.Transport).Clone()
	if proxyURL != "" {
		parsed, err := url.Parse(proxyURL)
		if err != nil {
			return nil, err
		}
		transport.Proxy = http.ProxyURL(parsed)
	}
	jar, _ := cookiejar.New(nil)
	if timeout <= 0 {
		timeout = 190 * time.Second
	}
	return &http.Client{Transport: transport, Jar: jar, Timeout: timeout}, nil
}
```

Create `go/protocol-register/internal/mailbridge/otp.go`:

```go
package mailbridge

import (
	"encoding/json"
	"regexp"
)

var otpPattern = regexp.MustCompile(`\b\d{6}\b`)

func ExtractOTP(payload []byte) string {
	var data any
	if json.Unmarshal(payload, &data) == nil {
		if code := findCode(data); code != "" {
			return code
		}
	}
	return otpPattern.FindString(string(payload))
}

func findCode(value any) string {
	switch typed := value.(type) {
	case map[string]any:
		for _, key := range []string{"code", "otp", "verification_code", "verificationCode"} {
			if raw, ok := typed[key].(string); ok {
				if code := otpPattern.FindString(raw); code != "" {
					return code
				}
			}
		}
		for _, raw := range typed {
			if code := findCode(raw); code != "" {
				return code
			}
		}
	case []any:
		for _, raw := range typed {
			if code := findCode(raw); code != "" {
				return code
			}
		}
	case string:
		return otpPattern.FindString(typed)
	}
	return ""
}
```

Create `go/protocol-register/internal/mailbridge/client.go`:

```go
package mailbridge

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"time"
)

type Client struct {
	httpClient   *http.Client
	pollInterval time.Duration
}

func NewClient(httpClient *http.Client, pollInterval time.Duration) *Client {
	if httpClient == nil {
		httpClient = http.DefaultClient
	}
	if pollInterval <= 0 {
		pollInterval = 3 * time.Second
	}
	return &Client{httpClient: httpClient, pollInterval: pollInterval}
}

func (c *Client) WaitForOTP(ctx context.Context, receiveCodeURL string) (string, error) {
	if receiveCodeURL == "" {
		return "", fmt.Errorf("receive_code_url is empty")
	}
	ticker := time.NewTicker(c.pollInterval)
	defer ticker.Stop()
	for {
		code, err := c.fetchOnce(ctx, receiveCodeURL)
		if err == nil && code != "" {
			return code, nil
		}
		select {
		case <-ctx.Done():
			return "", ctx.Err()
		case <-ticker.C:
		}
	}
}

func (c *Client) fetchOnce(ctx context.Context, url string) (string, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return "", err
	}
	req.Header.Set("Accept", "application/json,text/html,*/*")
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return "", err
	}
	if code := ExtractOTP(body); code != "" {
		return code, nil
	}
	return "", fmt.Errorf("no otp in response status=%d", resp.StatusCode)
}
```

- [ ] **Step 4: Run tests and commit**

Run:

```powershell
cd go/protocol-register
go test ./...
cd ..\..
git add go/protocol-register/internal/httpclient go/protocol-register/internal/mailbridge
git commit -m "feat(protocol): add Go mail OTP polling"
```

Expected: Go tests PASS and commit succeeds.

---

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

### Task 5: Python Opt-In Dispatch and Configuration

**Files:**
- Create: `tests/unit/test_go_protocol_register_dispatch.py`
- Modify: `src/autotoken/auth/protocol_register.py`
- Modify: `.env.example`
- Modify: `docs/configuration.md`
- Create: `scripts/build-go-protocol-register.ps1`

**Interfaces:**
- Consumes: `GoProtocolRegisterClient.register(payload)` from Task 1.
- Produces: `PROTOCOL_REGISTER_ENGINE=go` dispatch path in `protocol_register.register_once()`.
- Produces: fallback behavior controlled by `GO_PROTOCOL_FALLBACK_PYTHON`.

- [ ] **Step 1: Write failing Python dispatch tests**

Create `tests/unit/test_go_protocol_register_dispatch.py`:

```python
from autotoken.auth import protocol_register


class FakeMailClient:
    provider_name = "generic-api"
    accounts = []


class FakeGoClient:
    def __init__(self, *args, **kwargs):
        pass

    def health(self):
        return {"ok": True}

    def register(self, payload):
        assert payload["email"] == "user@example.com"
        assert payload["password"] == "pw"
        assert payload["mail"]["provider"] == "generic-api"
        return {
            "success": True,
            "status": "success",
            "email": "user@example.com",
            "session_data": {"email": "user@example.com", "accessToken": "access", "sessionToken": "session"},
            "events": [],
        }


def test_register_once_uses_go_engine_when_enabled(monkeypatch):
    monkeypatch.setenv("PROTOCOL_REGISTER_ENGINE", "go")
    monkeypatch.setattr("autotoken.integrations.go_protocol_register_client.GoProtocolRegisterClient", FakeGoClient)
    ok, payload = protocol_register.register_once(FakeMailClient(), email="user@example.com", password="pw", account_id="user@example.com")
    assert ok is True
    assert payload["accessToken"] == "access"
    assert payload["sessionToken"] == "session"
```

- [ ] **Step 2: Run test to verify failure**

Run:

```powershell
uv run --no-sync pytest tests/unit/test_go_protocol_register_dispatch.py -q
```

Expected: FAIL because `register_once()` does not dispatch to Go.

- [ ] **Step 3: Implement Go dispatch in Python**

Add these helpers near `register_once()` in `src/autotoken/auth/protocol_register.py`:

```python
def _env_flag(name: str, default: str = "0") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in {"1", "true", "yes", "on"}


def _go_protocol_enabled() -> bool:
    return str(os.environ.get("PROTOCOL_REGISTER_ENGINE", "python") or "python").strip().lower() == "go"


def _go_protocol_mail_payload(mail_client, *, email: str, account_id: str | int | None = None) -> dict[str, Any]:
    provider = str(getattr(mail_client, "provider_name", "") or "").strip().lower()
    payload = {"provider": provider, "account_id": str(account_id or email), "receive_code_url": "", "issued_after_unix": int(time.time())}
    for account in getattr(mail_client, "accounts", []) or []:
        if str(getattr(account, "email", "") or "").strip().lower() == str(email or "").strip().lower():
            payload["receive_code_url"] = str(getattr(account, "receive_code_url", "") or "").strip()
            break
    return payload


def _register_once_go(mail_client, *, email: str, password: str, account_id=None, proxy: str | None = None, **_kwargs):
    from autotoken.integrations.go_protocol_register_client import GoProtocolRegisterClient, go_response_to_protocol_result

    timeout_seconds = max(30, int(os.environ.get("OTP_TIMEOUT", "60") or 60))
    client = GoProtocolRegisterClient(timeout=max(90.0, float(timeout_seconds + 30)))
    client.health()
    response = client.register({
        "request_id": f"autotoken-{int(time.time() * 1000)}",
        "email": email,
        "password": password,
        "proxy_url": proxy or "",
        "mail": _go_protocol_mail_payload(mail_client, email=email, account_id=account_id),
        "options": {"timeout_seconds": timeout_seconds, "trace": _env_flag("GO_PROTOCOL_TRACE", "0"), "impersonate": os.environ.get("GO_PROTOCOL_IMPERSONATE", "chrome136")},
    })
    return go_response_to_protocol_result(response)
```

At the top of `register_once()`, add:

```python
if _go_protocol_enabled():
    try:
        return _register_once_go(mail_client, email=email, password=password, account_id=account_id, proxy=proxy)
    except Exception as exc:
        if not _env_flag("GO_PROTOCOL_FALLBACK_PYTHON", "1"):
            raise
        logger.warning("Go 协议注册不可用，回退 Python 协议注册: %s", safe_error_summary(exc, limit=180))
```

- [ ] **Step 4: Add build script and docs**

Create `scripts/build-go-protocol-register.ps1`:

```powershell
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$OutDir = Join-Path $Root 'bin'
New-Item -ItemType Directory -Force $OutDir | Out-Null
Push-Location (Join-Path $Root 'go/protocol-register')
try {
  go test ./...
  go build -o (Join-Path $OutDir 'protocol-registerd.exe') ./cmd/protocol-registerd
} finally {
  Pop-Location
}
Write-Host "Built $OutDir\protocol-registerd.exe"
```

Append to `.env.example`:

```text
PROTOCOL_REGISTER_ENGINE=python
GO_PROTOCOL_REGISTER_URL=http://127.0.0.1:18787
GO_PROTOCOL_REGISTER_AUTO_START=1
GO_PROTOCOL_REGISTER_BIN=bin/protocol-registerd.exe
GO_PROTOCOL_MAX_CONCURRENCY=50
GO_PROTOCOL_FALLBACK_PYTHON=1
GO_PROTOCOL_TRACE=0
GO_PROTOCOL_IMPERSONATE=chrome136
```

Add to `docs/configuration.md`:

```markdown
## Go protocol registration service

`PROTOCOL_REGISTER_ENGINE=python` keeps the legacy Python protocol path. Set `PROTOCOL_REGISTER_ENGINE=go` to route `register_mode=protocol` through the local `protocol-registerd` service.

| Variable | Default | Purpose |
|---|---:|---|
| `GO_PROTOCOL_REGISTER_URL` | `http://127.0.0.1:18787` | Local service endpoint |
| `GO_PROTOCOL_REGISTER_AUTO_START` | `1` | Python may start the local binary |
| `GO_PROTOCOL_REGISTER_BIN` | `bin/protocol-registerd.exe` | Windows binary path |
| `GO_PROTOCOL_MAX_CONCURRENCY` | `50` | Maximum inflight Go registration tasks |
| `GO_PROTOCOL_FALLBACK_PYTHON` | `1` | Use Python path when Go service is unavailable |
| `GO_PROTOCOL_TRACE` | `0` | Include non-secret trace events |
| `GO_PROTOCOL_IMPERSONATE` | `chrome136` | Header/fingerprint label |
```

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'
uv run --no-sync pytest tests/unit/test_go_protocol_register_client.py tests/unit/test_go_protocol_register_dispatch.py tests/unit/test_manager_auth_session.py tests/unit/test_protocol_auth_flow_errors.py -q
uv run --no-sync ruff check src/autotoken/auth/protocol_register.py src/autotoken/integrations/go_protocol_register_client.py tests/unit/test_go_protocol_register_client.py tests/unit/test_go_protocol_register_dispatch.py
powershell -ExecutionPolicy Bypass -File scripts/build-go-protocol-register.ps1
git add src/autotoken/auth/protocol_register.py src/autotoken/integrations/go_protocol_register_client.py tests/unit/test_go_protocol_register_dispatch.py .env.example docs/configuration.md scripts/build-go-protocol-register.ps1
git commit -m "feat(protocol): route protocol register through Go service"
```

Expected: Python tests PASS, Ruff PASS, Go binary builds, and commit succeeds.

---

### Task 6: Verification Harness and Performance Check

**Files:**
- Create: `.tmp/run_go_protocol_register_realtest.py`
- Create: `.tmp/bench_go_protocol_register.py`
- Modify: `docs/configuration.md`

**Interfaces:**
- Consumes: `cmd_register_accounts()`.
- Consumes: `bin/protocol-registerd.exe`.

- [ ] **Step 1: Create real-test script**

Create `.tmp/run_go_protocol_register_realtest.py`:

```python
import json
import logging
import os
import sys
import time

os.environ.setdefault("PROTOCOL_REGISTER_ENGINE", "go")
os.environ.setdefault("GO_PROTOCOL_REGISTER_AUTO_START", "1")
os.environ.setdefault("GO_PROTOCOL_FALLBACK_PYTHON", "0")
os.environ.setdefault("MAIL_PROVIDER", "generic-api")
os.environ.setdefault("GENERIC_API_SKIP_REGISTERED", "0")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stdout)

from autotoken.interfaces.manager import cmd_register_accounts


def progress(item):
    safe = dict(item or {})
    if safe.get("email"):
        local, _, domain = str(safe["email"]).partition("@")
        safe["email"] = local[:2] + "***@" + domain
    print("PROGRESS " + json.dumps(safe, ensure_ascii=False), flush=True)


start = time.time()
result = cmd_register_accounts(
    count=1,
    concurrency=1,
    retry_attempts=1,
    interval_seconds=0,
    jitter_min_seconds=0,
    jitter_max_seconds=0,
    mail_provider="generic-api",
    register_mode="protocol",
    proxy_url="",
    proxy_pool=[],
    post_register_oauth=False,
    progress_callback=progress,
)
print("REALTEST_RESULT " + json.dumps(result, ensure_ascii=False, default=str), flush=True)
print("REALTEST_ELAPSED_SECONDS", round(time.time() - start, 1), flush=True)
```

- [ ] **Step 2: Create service benchmark script**

Create `.tmp/bench_go_protocol_register.py`:

```python
import concurrent.futures
import json
import time
from urllib.request import Request, urlopen

URL = "http://127.0.0.1:18787/healthz"


def call_health(_index):
    req = Request(URL, headers={"Accept": "application/json"})
    with urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))["ok"]


for workers in (5, 20, 50):
    start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(call_health, range(workers * 20)))
    elapsed = time.time() - start
    print(json.dumps({"workers": workers, "requests": len(results), "ok": sum(1 for item in results if item), "elapsed_seconds": round(elapsed, 3), "rps": round(len(results) / elapsed, 1)}))
```

- [ ] **Step 3: Run final verification**

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'
uv run --no-sync pytest tests/unit/test_go_protocol_register_client.py tests/unit/test_go_protocol_register_dispatch.py tests/unit/test_manager_auth_session.py tests/unit/test_protocol_auth_flow_errors.py tests/unit/test_account_register_task_routes.py -q
uv run --no-sync ruff check src/autotoken/auth/protocol_register.py src/autotoken/integrations/go_protocol_register_client.py tests/unit/test_go_protocol_register_client.py tests/unit/test_go_protocol_register_dispatch.py
cd go/protocol-register
go test ./...
cd ..\..
powershell -ExecutionPolicy Bypass -File scripts/build-go-protocol-register.ps1
```

Expected: all commands exit 0 and `bin/protocol-registerd.exe` exists.

- [ ] **Step 4: Run benchmark**

Start service:

```powershell
$env:GO_PROTOCOL_MAX_CONCURRENCY='50'
.\bin\protocol-registerd.exe
```

Run benchmark:

```powershell
uv run --no-sync python .tmp\bench_go_protocol_register.py
```

Expected: each line reports `ok` equal to `requests`.

- [ ] **Step 5: Run one real generic-api registration**

Set a fresh mailbox:

```powershell
$env:GENERIC_API_ACCOUNTS='email@example.com ---- https://mail.example.com/mail-api/code?to=email%40example.com&timeout=60&key=secret'
uv run --no-sync python .tmp\run_go_protocol_register_realtest.py
```

Expected: when the mailbox receives OpenAI OTP, result contains `ok=1`, `failed=0`, and an `auth_file` path under `data/auth_session`.

- [ ] **Step 6: Commit verification harness**

Run:

```powershell
git add .tmp/run_go_protocol_register_realtest.py .tmp/bench_go_protocol_register.py docs/configuration.md
git commit -m "test(protocol): add Go register verification harness"
```

---

## Final Verification Before Completion

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'
uv run --no-sync pytest tests/unit/test_go_protocol_register_client.py tests/unit/test_go_protocol_register_dispatch.py tests/unit/test_manager_auth_session.py tests/unit/test_protocol_auth_flow_errors.py tests/unit/test_account_register_task_routes.py -q
uv run --no-sync ruff check src/autotoken/auth/protocol_register.py src/autotoken/integrations/go_protocol_register_client.py tests/unit/test_go_protocol_register_client.py tests/unit/test_go_protocol_register_dispatch.py
cd go/protocol-register
go test ./...
cd ..\..
powershell -ExecutionPolicy Bypass -File scripts/build-go-protocol-register.ps1
```

Expected:

- Python tests pass.
- Ruff passes.
- Go tests pass.
- `bin/protocol-registerd.exe` exists.
- Existing `PROTOCOL_REGISTER_ENGINE=python` behavior remains available.
- `PROTOCOL_REGISTER_ENGINE=go` uses the Go service or fails fast when fallback is disabled.
