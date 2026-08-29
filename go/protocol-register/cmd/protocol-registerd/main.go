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
	cfg := loadServerConfig()
	engine := register.NewHTTPRegisterEngine(register.HTTPRegisterEngineConfig{})
	srv := server.New(addr, cfg, engine)
	log.Printf(
		"protocol-registerd listening on %s protocol_ready=%t max_concurrency=%d auth_concurrency=%d",
		addr,
		cfg.ProtocolReady,
		cfg.MaxConcurrency,
		cfg.AuthConcurrency,
	)
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatal(err)
	}
}

func loadServerConfig() server.Config {
	return server.Config{
		MaxConcurrency:  positiveEnv("GO_PROTOCOL_MAX_CONCURRENCY", 20),
		AuthConcurrency: positiveEnv("GO_PROTOCOL_AUTH_CONCURRENCY", 3),
		ProtocolReady:   false,
	}
}

func positiveEnv(name string, fallback int) int {
	raw := os.Getenv(name)
	if raw == "" {
		return fallback
	}
	parsed, err := strconv.Atoi(raw)
	if err != nil || parsed <= 0 {
		return fallback
	}
	return parsed
}
