package main

import (
	"log"
	"net/http"
	"os"
	"strconv"

	"autoteam-f/protocol-register/internal/model"
	"autoteam-f/protocol-register/internal/register"
	"autoteam-f/protocol-register/internal/server"
)

// notImplementedEngine remains for compatibility with the command package's
// historical response-contract test. The daemon uses HTTPRegisterEngine.
type notImplementedEngine struct{}

func (notImplementedEngine) Register(_ *http.Request, req model.RegisterRequest) model.RegisterResponse {
	return model.RegisterResponse{Success: false, Status: "register_failed", Email: req.Email, Error: &model.ErrorInfo{Code: "not_implemented", Message: "registration engine not enabled", Step: "register"}, Events: []model.Event{}}
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
	engine := register.NewHTTPRegisterEngine(register.HTTPRegisterEngineConfig{})
	srv := server.New(addr, maxConcurrency, engine)
	log.Printf("protocol-registerd listening on %s max_concurrency=%d", addr, maxConcurrency)
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatal(err)
	}
}
