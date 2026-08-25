package register

import (
	"net/http"

	"autoteam-f/protocol-register/internal/model"
)

type Engine interface {
	Register(r *http.Request, req model.RegisterRequest) model.RegisterResponse
}
