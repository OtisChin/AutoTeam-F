package server_test

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"slices"
	"strings"
	"sync"
	"testing"

	"autoteam-f/protocol-register/internal/model"
	"autoteam-f/protocol-register/internal/readiness"
	"autoteam-f/protocol-register/internal/register"
	"autoteam-f/protocol-register/internal/sentinel"
	"autoteam-f/protocol-register/internal/server"
)

type fakeEngine struct {
	entered chan<- struct{}
	release <-chan struct{}
}

func (e fakeEngine) Register(_ *http.Request, req model.RegisterRequest) model.RegisterResponse {
	if e.entered != nil {
		e.entered <- struct{}{}
	}
	if e.release != nil {
		<-e.release
	}
	return model.RegisterResponse{Success: true, Status: "success", Email: req.Email, Events: []model.Event{}}
}

var _ register.Engine = fakeEngine{}

type countingEngine struct{ calls int }

func (e *countingEngine) Register(_ *http.Request, req model.RegisterRequest) model.RegisterResponse {
	e.calls++
	return model.RegisterResponse{Success: true, Status: "success", Email: req.Email, Events: []model.Event{}}
}

func TestRegisterRouteRejectsBeforeEngineWhenProtocolIsNotReady(t *testing.T) {
	engine := &countingEngine{}
	health := newMutableHealthSource(readiness.Snapshot{
		FingerprintPool: []string{"chrome144", "chrome146", "chrome150"},
		ReadyReason:     sentinel.StatusReasonRequirementsFailed,
	})
	h := server.NewHandler(server.Config{
		MaxConcurrency: 7, AuthConcurrency: 3, HealthSource: health,
	}, engine)
	req := httptest.NewRequest(http.MethodPost, "/v1/register", strings.NewReader(`{"email":"user@example.com"}`))
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusServiceUnavailable || engine.calls != 0 {
		t.Fatalf("status=%d calls=%d body=%s", rec.Code, engine.calls, rec.Body.String())
	}
	var body model.RegisterResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	if body.Status != "service_not_ready" || body.Error == nil || body.Error.RequestSent ||
		body.Metadata["ready_reason"] != sentinel.StatusReasonRequirementsFailed ||
		!strings.Contains(body.Error.Message, sentinel.StatusReasonRequirementsFailed) {
		t.Fatalf("body=%#v", body)
	}
	if health.callsCount() != 1 {
		t.Fatalf("health snapshot calls=%d", health.callsCount())
	}
}

func TestHealthzReadsLiveSnapshotAndExposesComponentMetadata(t *testing.T) {
	health := newMutableHealthSource(readiness.Snapshot{
		FingerprintPool: []string{"chrome144", "chrome150"},
		ReadyReason:     sentinel.StatusReasonSDKCompileFailed,
	})
	h := server.NewHandler(server.Config{MaxConcurrency: 7, AuthConcurrency: 3, HealthSource: health}, fakeEngine{})

	first := getHealth(t, h)
	if first["ok"] != true || first["protocol_ready"] != false || first["sentinel_ready"] != false ||
		first["ready_reason"] != sentinel.StatusReasonSDKCompileFailed || first["service"] != "protocol-registerd" ||
		int(first["max_concurrency"].(float64)) != 7 || int(first["auth_concurrency"].(float64)) != 3 {
		t.Fatalf("first health=%#v", first)
	}
	if got := stringSlice(first["fingerprint_pool"]); !slices.Equal(got, []string{"chrome144", "chrome150"}) {
		t.Fatalf("fingerprint_pool=%v", got)
	}

	health.set(readiness.Snapshot{
		ProtocolReady:      true,
		FingerprintPool:    []string{"chrome144", "chrome150"},
		SentinelReady:      true,
		SentinelSDKVersion: "currentA1",
	})
	second := getHealth(t, h)
	if second["protocol_ready"] != true || second["sentinel_ready"] != true ||
		second["sentinel_sdk_version"] != "currentA1" || second["ready_reason"] != "" {
		t.Fatalf("second health=%#v", second)
	}
	if health.callsCount() != 2 {
		t.Fatalf("health snapshot calls=%d", health.callsCount())
	}
}

func TestRoutesSanitizeUnknownReadinessReason(t *testing.T) {
	health := newMutableHealthSource(readiness.Snapshot{
		FingerprintPool: []string{"chrome144"},
		ReadyReason:     "private SDK response https://secret.example/token",
	})
	engine := &countingEngine{}
	h := server.NewHandler(server.Config{HealthSource: health}, engine)
	healthBody := getHealth(t, h)
	if healthBody["ready_reason"] != readiness.ReasonSentinelUnavailable {
		t.Fatalf("health=%#v", healthBody)
	}

	req := httptest.NewRequest(http.MethodPost, "/v1/register", strings.NewReader(`{"email":"user@example.com"}`))
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusServiceUnavailable || engine.calls != 0 || strings.Contains(rec.Body.String(), "secret.example") {
		t.Fatalf("status=%d calls=%d body=%s", rec.Code, engine.calls, rec.Body.String())
	}
	var body model.RegisterResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	if body.Metadata["ready_reason"] != readiness.ReasonSentinelUnavailable {
		t.Fatalf("body=%#v", body)
	}
}

func TestRegisterRouteRejectsWhenConcurrencyLimitIsReached(t *testing.T) {
	release := make(chan struct{})
	entered := make(chan struct{})
	h := server.NewHandler(server.Config{MaxConcurrency: 1, HealthSource: readyHealthSource()}, fakeEngine{entered: entered, release: release})
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		req := httptest.NewRequest(http.MethodPost, "/v1/register", strings.NewReader(`{"email":"one@example.com"}`))
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, req)
	}()
	<-entered
	req := httptest.NewRequest(http.MethodPost, "/v1/register", strings.NewReader(`{"email":"two@example.com"}`))
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	close(release)
	wg.Wait()
	if rec.Code != http.StatusTooManyRequests {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
	var body model.RegisterResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	if body.Status != "busy" || body.Error == nil || body.Error.Code != "busy" || body.Error.RequestSent {
		t.Fatalf("body=%#v", body)
	}
}

func TestRegisterRouteUsesExceptionStatusForBadRequest(t *testing.T) {
	h := server.NewHandler(server.Config{MaxConcurrency: 1, HealthSource: readyHealthSource()}, fakeEngine{})
	req := httptest.NewRequest(http.MethodPost, "/v1/register", strings.NewReader("{"))
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	var body model.RegisterResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	if body.Status != "exception" || body.Error == nil || body.Error.Code != "bad_request" {
		t.Fatalf("body=%#v", body)
	}
}

func TestRegisterRouteNormalizesInvalidEngineStatus(t *testing.T) {
	tests := []struct {
		name       string
		success    bool
		status     string
		errorCode  string
		expectStat string
		expectCode string
	}{
		{name: "failed response", status: "engine_internal", errorCode: "", expectStat: "register_failed", expectCode: "engine_internal"},
		{name: "failed response preserves error code", status: "engine_internal", errorCode: "provider_timeout", expectStat: "register_failed", expectCode: "provider_timeout"},
		{name: "successful response", success: true, status: "engine_ok", errorCode: "", expectStat: "success", expectCode: ""},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			h := server.NewHandler(server.Config{MaxConcurrency: 1, HealthSource: readyHealthSource()}, fakeEngineResponse{response: model.RegisterResponse{
				Success: tt.success,
				Status:  tt.status,
				Error:   &model.ErrorInfo{Code: tt.errorCode},
				Events:  []model.Event{},
			}})
			req := httptest.NewRequest(http.MethodPost, "/v1/register", strings.NewReader(`{"email":"user@example.com"}`))
			rec := httptest.NewRecorder()
			h.ServeHTTP(rec, req)

			var body model.RegisterResponse
			if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
				t.Fatal(err)
			}
			if body.Status != tt.expectStat {
				t.Fatalf("status=%q, want %q", body.Status, tt.expectStat)
			}
			if tt.expectCode == "" {
				if body.Error != nil && body.Error.Code != "" {
					t.Fatalf("error.code=%q, want empty", body.Error.Code)
				}
				return
			}
			if body.Error == nil || body.Error.Code != tt.expectCode {
				t.Fatalf("error=%#v, want code %q", body.Error, tt.expectCode)
			}
		})
	}
}

type fakeEngineResponse struct {
	response model.RegisterResponse
}

func (e fakeEngineResponse) Register(_ *http.Request, _ model.RegisterRequest) model.RegisterResponse {
	return e.response
}

type mutableHealthSource struct {
	mu       sync.RWMutex
	snapshot readiness.Snapshot
	calls    int
}

func newMutableHealthSource(snapshot readiness.Snapshot) *mutableHealthSource {
	return &mutableHealthSource{snapshot: snapshot}
}

func (s *mutableHealthSource) Snapshot() readiness.Snapshot {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.calls++
	snapshot := s.snapshot
	snapshot.FingerprintPool = append([]string(nil), snapshot.FingerprintPool...)
	return snapshot
}

func (s *mutableHealthSource) set(snapshot readiness.Snapshot) {
	s.mu.Lock()
	s.snapshot = snapshot
	s.mu.Unlock()
}

func (s *mutableHealthSource) callsCount() int {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.calls
}

func readyHealthSource() *mutableHealthSource {
	return newMutableHealthSource(readiness.Snapshot{
		ProtocolReady:      true,
		FingerprintPool:    []string{"chrome144", "chrome146", "chrome150"},
		SentinelReady:      true,
		SentinelSDKVersion: "readyA1",
	})
}

func getHealth(t *testing.T, handler http.Handler) map[string]any {
	t.Helper()
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	return body
}

func stringSlice(value any) []string {
	raw, _ := value.([]any)
	result := make([]string, len(raw))
	for index, item := range raw {
		result[index], _ = item.(string)
	}
	return result
}
