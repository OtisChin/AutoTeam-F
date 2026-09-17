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
	// SalvageExisting resumes the passwordless OTP login branch for an address
	// that a previous attempt already registered but never verified (for
	// example when the verification code could not be fetched).  Without it the
	// engine treats such an address as a duplicate and asks for a new mailbox.
	SalvageExisting bool `json:"salvage_existing"`
}

type Identity struct {
	Name      string `json:"name"`
	Birthdate string `json:"birthdate"`
}

type RegisterRequest struct {
	RequestID string          `json:"request_id"`
	Email     string          `json:"email"`
	Password  string          `json:"password"`
	Identity  Identity        `json:"identity"`
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
