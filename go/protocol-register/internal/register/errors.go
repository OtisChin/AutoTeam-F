package register

import "autoteam-f/protocol-register/internal/model"

func BusyResponse(email string) model.RegisterResponse {
	return model.RegisterResponse{
		Success: false,
		Status:  "register_failed",
		Email:   email,
		Error:   &model.ErrorInfo{Code: "busy", Message: "protocol-registerd concurrency limit reached", Retryable: true, Step: "admission"},
		Events:  []model.Event{},
	}
}
