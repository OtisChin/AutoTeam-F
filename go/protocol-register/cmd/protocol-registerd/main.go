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
