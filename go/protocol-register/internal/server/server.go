package server

import (
	"net/http"

	"autoteam-f/protocol-register/internal/register"
)

func New(addr string, cfg Config, engine register.Engine) *http.Server {
	return &http.Server{Addr: addr, Handler: NewHandler(cfg, engine)}
}
