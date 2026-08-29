package main

import (
	"testing"

	"autoteam-f/protocol-register/internal/model"
)

func TestNotImplementedEngineUsesCompatibleStatus(t *testing.T) {
	response := (notImplementedEngine{}).Register(nil, model.RegisterRequest{Email: "user@example.com"})
	if response.Status != "register_failed" || response.Error == nil || response.Error.Code != "not_implemented" {
		t.Fatalf("response=%#v", response)
	}
}

func TestLoadServerConfigDefaultsToNotReady(t *testing.T) {
	t.Setenv("GO_PROTOCOL_MAX_CONCURRENCY", "")
	t.Setenv("GO_PROTOCOL_AUTH_CONCURRENCY", "")

	cfg := loadServerConfig()

	if cfg.ProtocolReady || cfg.MaxConcurrency != 20 || cfg.AuthConcurrency != 3 {
		t.Fatalf("config=%#v", cfg)
	}
}
