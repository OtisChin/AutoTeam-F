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
			writeJSON(w, http.StatusBadRequest, model.RegisterResponse{Success: false, Status: "exception", Error: &model.ErrorInfo{Code: "bad_request", Message: err.Error(), Step: "decode"}, Events: []model.Event{}})
			return
		}
		select {
		case h.sem <- struct{}{}:
			defer func() { <-h.sem }()
		default:
			writeJSON(w, http.StatusTooManyRequests, register.BusyResponse(req.Email))
			return
		}
		writeJSON(w, http.StatusOK, normalizeRegisterResponse(h.engine.Register(r, req)))
	default:
		writeJSON(w, http.StatusNotFound, map[string]any{"ok": false, "error": "not found"})
	}
}

var allowedFailureStatuses = map[string]struct{}{
	"email_code_timeout":  {},
	"phone_blocked":       {},
	"account_deactivated": {},
	"register_failed":     {},
	"exception":           {},
}

func normalizeRegisterResponse(response model.RegisterResponse) model.RegisterResponse {
	if response.Success {
		response.Status = "success"
		return response
	}
	if _, ok := allowedFailureStatuses[response.Status]; ok {
		return response
	}

	originalStatus := response.Status
	response.Status = "register_failed"
	if response.Error == nil {
		response.Error = &model.ErrorInfo{}
	}
	if response.Error.Code == "" {
		response.Error.Code = originalStatus
	}
	return response
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}
