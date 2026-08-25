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
