package register

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"

	"autoteam-f/protocol-register/internal/httpclient"
	"autoteam-f/protocol-register/internal/mailbridge"
	"autoteam-f/protocol-register/internal/model"
	"autoteam-f/protocol-register/internal/openai"
)

type HTTPRegisterEngineConfig struct {
	BaseURL          string
	ChatGPTBaseURL   string
	SentinelProvider openai.SentinelProvider
}
type HTTPRegisterEngine struct{ cfg HTTPRegisterEngineConfig }

func NewHTTPRegisterEngine(cfg HTTPRegisterEngineConfig) *HTTPRegisterEngine {
	if cfg.SentinelProvider == nil {
		cfg.SentinelProvider = openai.UnavailableSentinelProvider{}
	}
	return &HTTPRegisterEngine{cfg: cfg}
}

func (e *HTTPRegisterEngine) Register(r *http.Request, req model.RegisterRequest) model.RegisterResponse {
	progress := &Progress{}
	timeout := time.Duration(req.Options.TimeoutSeconds) * time.Second
	if timeout <= 0 {
		timeout = 60 * time.Second
	}
	ctx, cancel := context.WithTimeout(r.Context(), timeout)
	defer cancel()
	client, err := httpclient.New(req.ProxyURL, timeout+30*time.Second)
	if err != nil {
		return fail(req.Email, "network_error", err.Error(), "http_client", true, progress.Events())
	}
	profile := openai.ResolveTransportProfile(req.Options.Impersonate)
	api := openai.NewClient(client, e.cfg.BaseURL, e.cfg.ChatGPTBaseURL, profile.UserAgent)
	csrf, err := api.GetCSRF(ctx)
	if err != nil {
		return fail(req.Email, "network_error", err.Error(), "csrf", true, progress.Events())
	}
	progress.Add("csrf", "csrf token acquired", nil)
	if err := api.SigninOpenAI(ctx, csrf); err != nil {
		return fail(req.Email, "network_error", err.Error(), "signin_openai", true, progress.Events())
	}
	authorizeToken, err := e.sentinelToken(ctx, client, api.DeviceID(), "authorize_continue")
	if err != nil {
		return authFailure(req.Email, err, "authorize_continue", "register_failed", true, progress.Events())
	}
	authStep, err := api.AuthorizeContinue(ctx, req.Email, authorizeToken)
	if err != nil {
		return authFailure(req.Email, err, "authorize_continue", "register_failed", true, progress.Events())
	}
	progress.Add("email_submitted", "email accepted", map[string]any{"page_type": authStep.PageType})
	if authStep.PageType == "create_account_password" {
		passwordToken, err := e.sentinelToken(ctx, client, api.DeviceID(), "username_password_create")
		if err != nil {
			return authFailure(req.Email, err, "register_password", "register_failed", true, progress.Events())
		}
		if err := api.RegisterPassword(ctx, req.Email, req.Password, passwordToken); err != nil {
			return authFailure(req.Email, err, "register_password", "register_failed", true, progress.Events())
		}
	}
	if err := api.SendEmailOTP(ctx); err != nil {
		return fail(req.Email, "register_failed", err.Error(), "send_email_otp", true, progress.Events())
	}
	code, err := mailbridge.NewClient(client, 3*time.Second).WaitForOTP(ctx, req.Mail.ReceiveCodeURL)
	if err != nil {
		return fail(req.Email, "email_code_timeout", "email OTP not received within timeout", "email_otp", false, progress.Events())
	}
	if _, err := api.VerifyEmailOTP(ctx, code); err != nil {
		return fail(req.Email, "register_failed", err.Error(), "verify_email_otp", true, progress.Events())
	}
	progress.Add("otp_verified", "email OTP verified", nil)
	createToken, err := e.sentinelToken(ctx, client, api.DeviceID(), "create_account")
	if err != nil {
		return authFailure(req.Email, err, "create_account", "phone_blocked", false, progress.Events())
	}
	if err := api.CreateAccount(ctx, createToken); err != nil {
		return authFailure(req.Email, err, "create_account", "phone_blocked", false, progress.Events())
	}
	sessionData, err := api.GetAuthSession(ctx)
	if err != nil {
		return fail(req.Email, "register_failed", err.Error(), "auth_session", true, progress.Events())
	}
	sessionData["email"] = req.Email
	sessionData["raw"] = map[string]any{"source": "go_protocol_register"}
	return model.RegisterResponse{Success: true, Status: "success", Email: req.Email, SessionData: sessionData, Events: progress.Events()}
}

func (e *HTTPRegisterEngine) sentinelToken(ctx context.Context, client *http.Client, deviceID, flow string) (string, error) {
	token, err := e.cfg.SentinelProvider.Token(ctx, client, deviceID, flow)
	if err != nil || strings.TrimSpace(token) == "" {
		return "", openai.ErrSentinelUnavailable
	}
	return token, nil
}

func authFailure(email string, err error, step, fallbackStatus string, fallbackRetryable bool, events []model.Event) model.RegisterResponse {
	switch {
	case errors.Is(err, openai.ErrChallengeUnavailable):
		return fail(email, "challenge_unavailable", err.Error(), step, false, events)
	case errors.Is(err, openai.ErrInvalidAuthState):
		return fail(email, "invalid_auth_state", err.Error(), step, false, events)
	default:
		return fail(email, fallbackStatus, err.Error(), step, fallbackRetryable, events)
	}
}

func fail(email, status, _ string, step string, retryable bool, events []model.Event) model.RegisterResponse {
	code := status
	if status == "network_error" {
		status = "register_failed"
	}
	if status == "phone_blocked" {
		code = "phone_required"
	}
	message := fmt.Sprintf("%s at %s", status, step)
	return model.RegisterResponse{Success: false, Status: status, Email: email, Error: &model.ErrorInfo{Code: code, Message: message, Retryable: retryable, Step: step}, Events: events}
}
