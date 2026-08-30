package register

import "autoteam-f/protocol-register/internal/model"

func BusyResponse(email string) model.RegisterResponse {
	return model.RegisterResponse{
		Success: false,
		Status:  "busy",
		Email:   email,
		Error:   &model.ErrorInfo{Code: "busy", Message: "protocol-registerd concurrency limit reached", Retryable: true, Step: "admission", RequestSent: false},
		Events:  []model.Event{},
	}
}

func ServiceNotReadyResponse(email string) model.RegisterResponse {
	return model.RegisterResponse{
		Success: false,
		Status:  "service_not_ready",
		Email:   email,
		Error: &model.ErrorInfo{
			Code:        "service_not_ready",
			Message:     "protocol registration is not ready",
			Retryable:   true,
			Step:        "readiness",
			RequestSent: false,
		},
		Events: []model.Event{},
	}
}
