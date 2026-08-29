package model

type Event struct {
	Stage   string         `json:"stage"`
	Message string         `json:"message"`
	Extra   map[string]any `json:"extra,omitempty"`
}

type ErrorInfo struct {
	Code        string `json:"code"`
	Message     string `json:"message"`
	Retryable   bool   `json:"retryable"`
	Step        string `json:"step"`
	RequestSent bool   `json:"request_sent"`
}

type RegisterResponse struct {
	Success     bool           `json:"success"`
	Status      string         `json:"status"`
	Email       string         `json:"email"`
	SessionData map[string]any `json:"session_data,omitempty"`
	Error       *ErrorInfo     `json:"error,omitempty"`
	Events      []Event        `json:"events"`
}
