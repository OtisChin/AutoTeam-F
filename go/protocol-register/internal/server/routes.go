package server

import (
	"encoding/json"
	"net/http"

	"autoteam-f/protocol-register/internal/model"
	"autoteam-f/protocol-register/internal/readiness"
	"autoteam-f/protocol-register/internal/register"
)

type HealthSource interface {
	Snapshot() readiness.Snapshot
}

type Handler struct {
	cfg    Config
	engine register.Engine
	sem    chan struct{}
}

type Config struct {
	MaxConcurrency  int
	AuthConcurrency int
	HealthSource    HealthSource
}

func normalizeConfig(cfg Config) Config {
	if cfg.MaxConcurrency <= 0 {
		cfg.MaxConcurrency = 20
	}
	if cfg.AuthConcurrency <= 0 {
		cfg.AuthConcurrency = 3
	}
	if cfg.AuthConcurrency > cfg.MaxConcurrency {
		cfg.AuthConcurrency = cfg.MaxConcurrency
	}
	return cfg
}

func NewHandler(cfg Config, engine register.Engine) http.Handler {
	cfg = normalizeConfig(cfg)
	return &Handler{cfg: cfg, engine: engine, sem: make(chan struct{}, cfg.MaxConcurrency)}
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	switch {
	case r.Method == http.MethodGet && r.URL.Path == "/healthz":
		snapshot := h.healthSnapshot()
		writeJSON(w, http.StatusOK, map[string]any{
			"ok":                   true,
			"protocol_ready":       snapshot.ProtocolReady,
			"fingerprint_pool":     snapshot.FingerprintPool,
			"sentinel_ready":       snapshot.SentinelReady,
			"sentinel_sdk_version": snapshot.SentinelSDKVersion,
			"ready_reason":         snapshot.ReadyReason,
			"service":              "protocol-registerd",
			"version":              "dev",
			"max_concurrency":      h.cfg.MaxConcurrency,
			"auth_concurrency":     h.cfg.AuthConcurrency,
			"inflight":             len(h.sem),
		})
	case r.Method == http.MethodPost && r.URL.Path == "/v1/probe":
		snapshot := h.healthSnapshot()
		if !snapshot.ProtocolReady {
			w.Header().Set("Retry-After", "30")
			writeJSON(w, http.StatusServiceUnavailable, model.ProxyProbeResponse{Error: "service_not_ready"})
			return
		}
		var req model.ProxyProbeRequest
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20)).Decode(&req); err != nil {
			writeJSON(w, http.StatusBadRequest, model.ProxyProbeResponse{Error: "bad_request"})
			return
		}
		prober, ok := h.engine.(register.ProxyProber)
		if !ok {
			writeJSON(w, http.StatusServiceUnavailable, model.ProxyProbeResponse{Error: "proxy_probe_unavailable"})
			return
		}
		select {
		case h.sem <- struct{}{}:
			defer func() { <-h.sem }()
		default:
			w.Header().Set("Retry-After", "1")
			writeJSON(w, http.StatusTooManyRequests, model.ProxyProbeResponse{Error: "busy"})
			return
		}
		writeJSON(w, http.StatusOK, prober.ProbeProxy(r, req))
	case r.Method == http.MethodPost && r.URL.Path == "/v1/register":
		snapshot := h.healthSnapshot()
		if !snapshot.ProtocolReady {
			w.Header().Set("Retry-After", "30")
			response := register.ServiceNotReadyResponse("")
			response.Metadata = map[string]string{"ready_reason": snapshot.ReadyReason}
			response.Error.Message += ": " + snapshot.ReadyReason
			writeJSON(w, http.StatusServiceUnavailable, response)
			return
		}
		var req model.RegisterRequest
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20)).Decode(&req); err != nil {
			writeJSON(w, http.StatusBadRequest, model.RegisterResponse{Success: false, Status: "exception", Error: &model.ErrorInfo{Code: "bad_request", Message: err.Error(), Step: "decode"}, Events: []model.Event{}})
			return
		}
		select {
		case h.sem <- struct{}{}:
			defer func() { <-h.sem }()
		default:
			w.Header().Set("Retry-After", "1")
			writeJSON(w, http.StatusTooManyRequests, register.BusyResponse(req.Email))
			return
		}
		writeJSON(w, http.StatusOK, normalizeRegisterResponse(h.engine.Register(r, req)))
	default:
		writeJSON(w, http.StatusNotFound, map[string]any{"ok": false, "error": "not found"})
	}
}

func (h *Handler) healthSnapshot() readiness.Snapshot {
	if h.cfg.HealthSource == nil {
		return readiness.Snapshot{
			FingerprintPool: []string{},
			ReadyReason:     readiness.ReasonFingerprintPoolInvalid,
		}
	}
	snapshot := h.cfg.HealthSource.Snapshot()
	snapshot.FingerprintPool = append([]string(nil), snapshot.FingerprintPool...)
	snapshot.ReadyReason = readiness.SanitizeReason(snapshot.ReadyReason)
	if !snapshot.ProtocolReady && snapshot.ReadyReason == "" {
		snapshot.ReadyReason = readiness.ReasonSentinelUnavailable
	}
	if snapshot.ProtocolReady {
		snapshot.ReadyReason = ""
	}
	return snapshot
}

var allowedFailureStatuses = map[string]struct{}{
	"service_not_ready":   {},
	"busy":                {},
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
