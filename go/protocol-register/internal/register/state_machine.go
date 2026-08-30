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
	AuthConcurrency       int
}
type HTTPRegisterEngine struct {
	cfg      HTTPRegisterEngineConfig
	authGate *authGate
}

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
	if cfg.AuthConcurrency <= 0 {
		cfg.AuthConcurrency = defaultAuthConcurrency
	}
	return &HTTPRegisterEngine{cfg: cfg, authGate: newAuthGate(cfg.AuthConcurrency)}
}

func (e *HTTPRegisterEngine) orderedProfiles() ([]fingerprint.Profile, error) {
	first, err := e.cfg.FingerprintPool.Select(e.cfg.Draw)
	if err != nil {
		return nil, err
	}
	names := e.cfg.FingerprintPool.Names()
	start := -1
	for index, name := range names {
		if name == first.Name {
			start = index
			break
		}
	}
	if start < 0 {
		return nil, fingerprint.ErrUnsupportedProfile
	}
	profiles := make([]fingerprint.Profile, 0, len(names))
	for offset := range names {
		name := names[(start+offset)%len(names)]
		profile, ok := fingerprint.Lookup(name)
		if !ok {
			return nil, fmt.Errorf("%w: %q", fingerprint.ErrUnsupportedProfile, name)
		}
		profiles = append(profiles, profile)
	}
	return profiles, nil
}

func (e *HTTPRegisterEngine) selectProfile(preferred string) (fingerprint.Profile, error) {
	preferred = strings.TrimSpace(preferred)
	if preferred != "" {
		for _, name := range e.cfg.FingerprintPool.Names() {
			if name != preferred {
				continue
			}
			if profile, ok := fingerprint.Lookup(name); ok {
				return profile, nil
			}
			break
		}
	}
	return e.cfg.FingerprintPool.Select(e.cfg.Draw)
}

func (e *HTTPRegisterEngine) ProbeProxy(r *http.Request, req model.ProxyProbeRequest) model.ProxyProbeResponse {
	timeout := time.Duration(req.TimeoutSeconds) * time.Second
	if timeout <= 0 {
		timeout = 20 * time.Second
	}
	if timeout > 30*time.Second {
		timeout = 30 * time.Second
	}
	ctx := context.Background()
	if r != nil {
		ctx = r.Context()
	}
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	profiles, err := e.orderedProfiles()
	if err != nil {
		return model.ProxyProbeResponse{Error: "fingerprint pool unavailable"}
	}
	for _, profile := range profiles {
		client, clientErr := e.cfg.ProfiledClientFactory(profile, req.ProxyURL, timeout)
		if clientErr != nil || client == nil {
			continue
		}
		token, probeErr := openai.NewClient(client, e.cfg.BaseURL, e.cfg.ChatGPTBaseURL, profile).GetCSRF(ctx)
		client.CloseIdleConnections()
		if probeErr == nil && strings.TrimSpace(token) != "" {
			return model.ProxyProbeResponse{OK: true, FingerprintProfile: profile.Name}
		}
		if ctx.Err() != nil {
			break
		}
	}
	return model.ProxyProbeResponse{Error: "csrf probe failed for configured Go profiles"}
}

func (e *HTTPRegisterEngine) Register(r *http.Request, req model.RegisterRequest) model.RegisterResponse {
	progress := &Progress{}
	metadata := map[string]string{}
	profile, err := e.selectProfile(req.Options.Impersonate)
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
	attempt := &registrationAttempt{
		engine:   e,
		ctx:      ctx,
		request:  req,
		client:   client,
		profile:  profile,
		api:      api,
		progress: progress,
		metadata: metadata,
	}
	deviceID, failure := attempt.runInitialAuthPhase()
	if failure != nil {
		return *failure
	}
	mailHTTPClient, err := e.cfg.MailboxClientFactory(timeout + 30*time.Second)
	if err != nil {
		return *attempt.failure("network_error", err, "mail_client", true)
	}
	if mailHTTPClient == nil {
		return *attempt.failure("network_error", errors.New("mailbox client unavailable"), "mail_client", true)
	}
	defer mailHTTPClient.CloseIdleConnections()
	code, err := mailbridge.NewClient(mailHTTPClient, 3*time.Second).WaitForOTP(ctx, req.Mail.ReceiveCodeURL)
	if err != nil {
		return *attempt.failure("email_code_timeout", errors.New("email OTP not received within timeout"), "email_otp", false)
	}
	sessionData, failure := attempt.runFinalAuthPhase(deviceID, code)
	if failure != nil {
		return *failure
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

type registrationAttempt struct {
	engine   *HTTPRegisterEngine
	ctx      context.Context
	request  model.RegisterRequest
	client   *http.Client
	profile  fingerprint.Profile
	api      *openai.Client
	progress *Progress
	metadata map[string]string
}

func (a *registrationAttempt) runInitialAuthPhase() (string, *model.RegisterResponse) {
	release, err := a.engine.authGate.acquire(a.ctx)
	if err != nil {
		return "", a.failure("network_error", err, "auth_gate", true)
	}
	defer release()

	csrf, err := a.api.GetCSRF(a.ctx)
	if err != nil {
		return "", a.failure("network_error", err, "csrf", true)
	}
	a.progress.Add("csrf", "csrf token acquired", nil)
	deviceID, err := a.api.InitializeOAuth(a.ctx, csrf)
	if err != nil {
		return "", a.authFailure(err, "signin_openai", "network_error", true)
	}
	authorizeToken, err := a.engine.sentinelToken(a.ctx, a.client, a.profile, deviceID, "authorize_continue", a.metadata)
	if err != nil {
		return "", a.authFailure(err, "authorize_continue", "register_failed", true)
	}
	authStep, err := a.api.AuthorizeContinue(a.ctx, a.request.Email, authorizeToken)
	if err != nil {
		return "", a.authFailure(err, "authorize_continue", "register_failed", true)
	}
	a.progress.Add("email_submitted", "email accepted", map[string]any{"page_type": authStep.PageType})
	if err := a.api.FollowContinue(a.ctx, authStep.ContinueURL); err != nil {
		return "", a.authFailure(err, "authorize_continue", "register_failed", true)
	}
	if authStep.PageType == "create_account_password" {
		passwordToken, err := a.engine.sentinelToken(a.ctx, a.client, a.profile, deviceID, "username_password_create", a.metadata)
		if err != nil {
			return "", a.authFailure(err, "register_password", "register_failed", true)
		}
		if err := a.api.RegisterPassword(a.ctx, a.request.Email, a.request.Password, passwordToken); err != nil {
			return "", a.authFailure(err, "register_password", "register_failed", true)
		}
	}
	if err := a.api.SendEmailOTP(a.ctx); err != nil {
		return "", a.failure("register_failed", err, "send_email_otp", true)
	}
	return deviceID, nil
}

func (a *registrationAttempt) runFinalAuthPhase(deviceID, code string) (map[string]any, *model.RegisterResponse) {
	release, err := a.engine.authGate.acquire(a.ctx)
	if err != nil {
		return nil, a.failure("network_error", err, "auth_gate", true)
	}
	defer release()

	otpStep, err := a.api.VerifyEmailOTP(a.ctx, code)
	if err != nil {
		return nil, a.authFailure(err, "verify_email_otp", "register_failed", true)
	}
	if otpStep.PageType != "about_you" {
		return nil, a.authFailure(openai.ErrInvalidAuthState, "verify_email_otp", "register_failed", true)
	}
	a.progress.Add("otp_verified", "email OTP verified", nil)
	createToken, err := a.engine.sentinelToken(a.ctx, a.client, a.profile, deviceID, "create_account", a.metadata)
	if err != nil {
		return nil, a.authFailure(err, "create_account", "phone_blocked", false)
	}
	createStep, err := a.api.CreateAccount(a.ctx, createToken, "Alex Chen", "1993-01-01")
	if err != nil {
		return nil, a.authFailure(err, "create_account", "phone_blocked", false)
	}
	if err := a.api.FollowContinue(a.ctx, createStep.ContinueURL); err != nil {
		return nil, a.authFailure(err, "create_account_redirect", "register_failed", false)
	}
	rawSession, err := a.api.GetAuthSession(a.ctx)
	if err != nil {
		return nil, a.failure("register_failed", err, "auth_session", true)
	}
	sessionData, err := openai.ExtractSession(rawSession, a.client.Jar, a.api.ChatGPTBaseURL)
	if err != nil {
		return nil, a.failure("session_missing", err, "auth_session", false)
	}
	return sessionData, nil
}

func (a *registrationAttempt) failure(status string, err error, step string, retryable bool) *model.RegisterResponse {
	detail := ""
	if err != nil {
		detail = err.Error()
	}
	response := fail(a.request.Email, status, detail, step, retryable, a.progress.Events(), a.metadata)
	return &response
}

func (a *registrationAttempt) authFailure(err error, step, fallbackStatus string, fallbackRetryable bool) *model.RegisterResponse {
	response := authFailure(a.request.Email, err, step, fallbackStatus, fallbackRetryable, a.progress.Events(), a.metadata)
	return &response
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
