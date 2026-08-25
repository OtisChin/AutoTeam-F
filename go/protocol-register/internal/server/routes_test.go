package server_test

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	"autoteam-f/protocol-register/internal/model"
	"autoteam-f/protocol-register/internal/register"
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
	entered := make(chan struct{})
	h := server.NewHandler(1, fakeEngine{entered: entered, release: release})
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
	if body.Status != "register_failed" || body.Error == nil || body.Error.Code != "busy" {
		t.Fatalf("body=%#v", body)
	}
}

func TestRegisterRouteUsesExceptionStatusForBadRequest(t *testing.T) {
	h := server.NewHandler(1, fakeEngine{})
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
			h := server.NewHandler(1, fakeEngineResponse{response: model.RegisterResponse{
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
