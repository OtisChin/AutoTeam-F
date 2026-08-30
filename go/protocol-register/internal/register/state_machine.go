package register

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"

	"autoteam-f/protocol-register/internal/fingerprint"
	"autoteam-f/protocol-register/internal/httpclient"
	"autoteam-f/protocol-register/internal/mailbridge"
	"autoteam-f/protocol-register/internal/model"
	"autoteam-f/protocol-register/internal/openai"
)

type ProfiledClientFactory func(fingerprint.Profile, string, time.Duration) (*http.Client, error)
type MailboxClientFactory func(time.Duration) (*http.Client, error)

type HTTPRegisterEngineConfig struct {
	BaseURL               string
	ChatGPTBaseURL        string
	SentinelProvider      openai.SentinelProvider
	FingerprintPool       fingerprint.Pool
	Draw                  fingerprint.DrawFunc
	ProfiledClientFactory ProfiledClientFactory
	MailboxClientFactory  MailboxClientFactory
}
type HTTPRegisterEngine struct{ cfg HTTPRegisterEngineConfig }

func NewHTTPRegisterEngine(cfg HTTPRegisterEngineConfig) *HTTPRegisterEngine {
	if cfg.SentinelProvider == nil {
		cfg.SentinelProvider = openai.UnavailableSentinelProvider{}
	}
	if len(cfg.FingerprintPool.Names()) == 0 {
		pool, err := fingerprint.ParsePool(fingerprint.DefaultPool)
		if err != nil {
			panic(fmt.Sprintf("invalid built-in fingerprint pool: %v", err))
		}
		cfg.FingerprintPool = pool
	}
	if cfg.Draw == nil {
		cfg.Draw = fingerprint.CryptoDraw
	}
	if cfg.ProfiledClientFactory == nil {
		cfg.ProfiledClientFactory = httpclient.NewProfiled
	}
	if cfg.MailboxClientFactory == nil {
		cfg.MailboxClientFactory = func(timeout time.Duration) (*http.Client, error) {
			return httpclient.NewStandard(timeout), nil
		}
	}
	return &HTTPRegisterEngine{cfg: cfg}
}

func (e *HTTPRegisterEngine) Register(r *http.Request, req model.RegisterRequest) model.RegisterResponse {
	progress := &Progress{}
	metadata := map[string]string{}
	profile, err := e.cfg.FingerprintPool.Select(e.cfg.Draw)
	if err != nil {
		return fail(req.Email, "network_error", err.Error(), "fingerprint", true, progress.Events(), metadata)
	}
	metadata["fingerprint_profile"] = profile.Name

	timeout := time.Duration(req.Options.TimeoutSeconds) * time.Second
	if timeout <= 0 {
		timeout = 60 * time.Second
	}
	ctx, cancel := context.WithTimeout(r.Context(), timeout)
	defer cancel()
	client, err := e.cfg.ProfiledClientFactory(profile, req.ProxyURL, timeout+30*time.Second)
	if err != nil {
		return fail(req.Email, "network_error", err.Error(), "http_client", true, progress.Events(), metadata)
	}
	if client == nil {
		return fail(req.Email, "network_error", "profiled client unavailable", "http_client", true, progress.Events(), metadata)
	}
	defer client.CloseIdleConnections()
	api := openai.NewClient(client, e.cfg.BaseURL, e.cfg.ChatGPTBaseURL, profile)
	csrf, err := api.GetCSRF(ctx)
	if err != nil {
		return fail(req.Email, "network_error", err.Error(), "csrf", true, progress.Events(), metadata)
	}
	progress.Add("csrf", "csrf token acquired", nil)
	deviceID, err := api.InitializeOAuth(ctx, csrf)
	if err != nil {
		return authFailure(req.Email, err, "signin_openai", "network_error", true, progress.Events(), metadata)
	}
	authorizeToken, err := e.sentinelToken(ctx, client, profile, deviceID, "authorize_continue", metadata)
	if err != nil {
		return authFailure(req.Email, err, "authorize_continue", "register_failed", true, progress.Events(), metadata)
	}
	authStep, err := api.AuthorizeContinue(ctx, req.Email, authorizeToken)
	if err != nil {
		return authFailure(req.Email, err, "authorize_continue", "register_failed", true, progress.Events(), metadata)
	}
	progress.Add("email_submitted", "email accepted", map[string]any{"page_type": authStep.PageType})
	if err := api.FollowContinue(ctx, authStep.ContinueURL); err != nil {
		return authFailure(req.Email, err, "authorize_continue", "register_failed", true, progress.Events(), metadata)
	}
	if authStep.PageType == "create_account_password" {
		passwordToken, err := e.sentinelToken(ctx, client, profile, deviceID, "username_password_create", metadata)
		if err != nil {
			return authFailure(req.Email, err, "register_password", "register_failed", true, progress.Events(), metadata)
		}
		if err := api.RegisterPassword(ctx, req.Email, req.Password, passwordToken); err != nil {
			return authFailure(req.Email, err, "register_password", "register_failed", true, progress.Events(), metadata)
		}
	}
	if err := api.SendEmailOTP(ctx); err != nil {
		return fail(req.Email, "register_failed", err.Error(), "send_email_otp", true, progress.Events(), metadata)
	}
	mailHTTPClient, err := e.cfg.MailboxClientFactory(timeout + 30*time.Second)
	if err != nil {
		return fail(req.Email, "network_error", err.Error(), "mail_client", true, progress.Events(), metadata)
	}
	if mailHTTPClient == nil {
		return fail(req.Email, "network_error", "mailbox client unavailable", "mail_client", true, progress.Events(), metadata)
	}
	defer mailHTTPClient.CloseIdleConnections()
	code, err := mailbridge.NewClient(mailHTTPClient, 3*time.Second).WaitForOTP(ctx, req.Mail.ReceiveCodeURL)
	if err != nil {
		return fail(req.Email, "email_code_timeout", "email OTP not received within timeout", "email_otp", false, progress.Events(), metadata)
	}
	otpStep, err := api.VerifyEmailOTP(ctx, code)
	if err != nil {
		return authFailure(req.Email, err, "verify_email_otp", "register_failed", true, progress.Events(), metadata)
	}
	if otpStep.PageType != "about_you" {
		return authFailure(req.Email, openai.ErrInvalidAuthState, "verify_email_otp", "register_failed", true, progress.Events(), metadata)
	}
	progress.Add("otp_verified", "email OTP verified", nil)
	createToken, err := e.sentinelToken(ctx, client, profile, deviceID, "create_account", metadata)
	if err != nil {
		return authFailure(req.Email, err, "create_account", "phone_blocked", false, progress.Events(), metadata)
	}
	createStep, err := api.CreateAccount(ctx, createToken, "Alex Chen", "1993-01-01")
	if err != nil {
		return authFailure(req.Email, err, "create_account", "phone_blocked", false, progress.Events(), metadata)
	}
	if err := api.FollowContinue(ctx, createStep.ContinueURL); err != nil {
		return authFailure(req.Email, err, "create_account_redirect", "register_failed", false, progress.Events(), metadata)
	}
	rawSession, err := api.GetAuthSession(ctx)
	if err != nil {
		return fail(req.Email, "register_failed", err.Error(), "auth_session", true, progress.Events(), metadata)
	}
	sessionData, err := openai.ExtractSession(rawSession, client.Jar, api.ChatGPTBaseURL)
	if err != nil {
		return fail(req.Email, "session_missing", err.Error(), "auth_session", false, progress.Events(), metadata)
	}
	sessionData["email"] = req.Email
	raw := map[string]any{
		"source":              "go_protocol_register",
		"fingerprint_profile": profile.Name,
	}
	if sdkVersion := metadata["sentinel_sdk_version"]; sdkVersion != "" {
		raw["sentinel_sdk_version"] = sdkVersion
	}
	sessionData["raw"] = raw
	return model.RegisterResponse{Success: true, Status: "success", Email: req.Email, SessionData: sessionData, Metadata: metadata, Events: progress.Events()}
}

func (e *HTTPRegisterEngine) sentinelToken(ctx context.Context, client *http.Client, profile fingerprint.Profile, deviceID, flow string, metadata map[string]string) (string, error) {
	result, err := e.cfg.SentinelProvider.Token(ctx, client, profile, deviceID, flow)
	token := strings.TrimSpace(result.Token)
	if err != nil || token == "" {
		return "", openai.ErrSentinelUnavailable
	}
	if _, recorded := metadata["sentinel_sdk_version"]; !recorded {
		if sdkVersion := strings.TrimSpace(result.SDKVersion); sdkVersion != "" {
			metadata["sentinel_sdk_version"] = sdkVersion
		}
	}
	return token, nil
}

func authFailure(email string, err error, step, fallbackStatus string, fallbackRetryable bool, events []model.Event, metadata map[string]string) model.RegisterResponse {
	switch {
	case errors.Is(err, openai.ErrChallengeUnavailable):
		return fail(email, "challenge_unavailable", err.Error(), step, false, events, metadata)
	case errors.Is(err, openai.ErrInvalidAuthState):
		return fail(email, "invalid_auth_state", err.Error(), step, false, events, metadata)
	default:
		return fail(email, fallbackStatus, err.Error(), step, fallbackRetryable, events, metadata)
	}
}

func fail(email, status, _ string, step string, retryable bool, events []model.Event, metadata map[string]string) model.RegisterResponse {
	code := status
	if status == "network_error" {
		status = "register_failed"
	}
	if status == "phone_blocked" {
		code = "phone_required"
	}
	message := fmt.Sprintf("%s at %s", status, step)
	return model.RegisterResponse{Success: false, Status: status, Email: email, Error: &model.ErrorInfo{Code: code, Message: message, Retryable: retryable, Step: step}, Events: events, Metadata: metadata}
}
