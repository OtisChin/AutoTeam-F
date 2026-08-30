package register

import (
	"net/http"

	"autoteam-f/protocol-register/internal/model"
)

type Engine interface {
	Register(r *http.Request, req model.RegisterRequest) model.RegisterResponse
}

type ProxyProber interface {
	ProbeProxy(r *http.Request, req model.ProxyProbeRequest) model.ProxyProbeResponse
}
