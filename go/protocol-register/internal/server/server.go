package server

import (
	"net/http"

	"autoteam-f/protocol-register/internal/register"
)

func New(addr string, maxConcurrency int, engine register.Engine) *http.Server {
	return &http.Server{Addr: addr, Handler: NewHandler(maxConcurrency, engine)}
}
