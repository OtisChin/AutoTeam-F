package model

type MailConfig struct {
	Provider        string `json:"provider"`
	AccountID       string `json:"account_id"`
	ReceiveCodeURL  string `json:"receive_code_url"`
	IssuedAfterUnix int64  `json:"issued_after_unix"`
}

type RegisterOptions struct {
	TimeoutSeconds int    `json:"timeout_seconds"`
	Trace          bool   `json:"trace"`
	Impersonate    string `json:"impersonate"`
}

type RegisterRequest struct {
	RequestID string          `json:"request_id"`
	Email     string          `json:"email"`
	Password  string          `json:"password"`
	ProxyURL  string          `json:"proxy_url"`
	Mail      MailConfig      `json:"mail"`
	Options   RegisterOptions `json:"options"`
}

type ProxyProbeRequest struct {
	ProxyURL       string `json:"proxy_url"`
	TimeoutSeconds int    `json:"timeout_seconds"`
}

type ProxyProbeResponse struct {
	OK                 bool   `json:"ok"`
	FingerprintProfile string `json:"fingerprint_profile,omitempty"`
	Error              string `json:"error,omitempty"`
}
