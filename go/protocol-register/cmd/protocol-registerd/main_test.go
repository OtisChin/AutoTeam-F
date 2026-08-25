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
