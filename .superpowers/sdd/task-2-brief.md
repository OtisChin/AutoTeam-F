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

