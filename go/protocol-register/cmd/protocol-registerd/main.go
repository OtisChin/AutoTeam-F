package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"autoteam-f/protocol-register/internal/fingerprint"
	"autoteam-f/protocol-register/internal/httpclient"
	"autoteam-f/protocol-register/internal/model"
	"autoteam-f/protocol-register/internal/openai"
	"autoteam-f/protocol-register/internal/readiness"
	"autoteam-f/protocol-register/internal/register"
	"autoteam-f/protocol-register/internal/sentinel"
	"autoteam-f/protocol-register/internal/server"
)

// notImplementedEngine remains for compatibility with the command package's
// historical response-contract test. Production startup replaces it with the
// HTTP registration engine even when admission is fail-closed.
type notImplementedEngine struct{}

func (notImplementedEngine) Register(_ *http.Request, req model.RegisterRequest) model.RegisterResponse {
	return model.RegisterResponse{Success: false, Status: "register_failed", Email: req.Email, Error: &model.ErrorInfo{Code: "not_implemented", Message: "registration engine not enabled", Step: "register"}, Events: []model.Event{}}
}

type startupSentinelProvider interface {
	openai.SentinelProvider
	DryRun(context.Context, *http.Client, fingerprint.Profile) sentinel.Status
	Status() sentinel.Status
}

type runtimeDependencies struct {
	loadSentinelConfig    func() (sentinel.Config, error)
	buildSentinelProvider func(sentinel.Config) (startupSentinelProvider, error)
	newProfiledClient     register.ProfiledClientFactory
	draw                  fingerprint.DrawFunc
	newRegisterEngine     func(register.HTTPRegisterEngineConfig) register.Engine
}

type daemonRuntime struct {
	ServerConfig server.Config
	Engine       register.Engine
}

func main() {
	addr := strings.TrimSpace(os.Getenv("GO_PROTOCOL_REGISTER_ADDR"))
	if addr == "" {
		addr = "127.0.0.1:18787"
	}
	runtime := loadRuntime(context.Background(), runtimeDependencies{})
	snapshot := runtime.ServerConfig.HealthSource.Snapshot()
	srv := server.New(addr, runtime.ServerConfig, runtime.Engine)
	log.Printf(
		"protocol-registerd listening on %s protocol_ready=%t fingerprint_pool=%s sentinel_ready=%t sentinel_sdk_version=%s ready_reason=%s max_concurrency=%d auth_concurrency=%d",
		addr,
		snapshot.ProtocolReady,
		strings.Join(snapshot.FingerprintPool, ","),
		snapshot.SentinelReady,
		snapshot.SentinelSDKVersion,
		readiness.SanitizeReason(snapshot.ReadyReason),
		runtime.ServerConfig.MaxConcurrency,
		runtime.ServerConfig.AuthConcurrency,
	)
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatal(err)
	}
}

func loadRuntime(ctx context.Context, deps runtimeDependencies) daemonRuntime {
	deps = deps.withDefaults()
	if ctx == nil {
		ctx = context.Background()
	}

	pool, poolErr := loadFingerprintPool()
	provider := startupSentinelProvider(newUnavailableStartupProvider(sentinel.StatusReasonNotChecked))
	if poolErr == nil {
		provider = loadSentinelProvider(ctx, deps, pool)
	}

	healthSource := readiness.NewSource(pool, provider)
	serverConfig := server.Config{
		MaxConcurrency:  positiveEnv("GO_PROTOCOL_MAX_CONCURRENCY", 20),
		AuthConcurrency: positiveEnv("GO_PROTOCOL_AUTH_CONCURRENCY", 3),
		HealthSource:    healthSource,
	}
	engine := deps.newRegisterEngine(register.HTTPRegisterEngineConfig{
		SentinelProvider: provider,
		FingerprintPool:  pool,
		AuthConcurrency:  serverConfig.AuthConcurrency,
	})
	if engine == nil {
		engine = notImplementedEngine{}
	}
	return daemonRuntime{ServerConfig: serverConfig, Engine: engine}
}

func loadSentinelProvider(
	ctx context.Context,
	deps runtimeDependencies,
	pool fingerprint.Pool,
) startupSentinelProvider {
	cfg, err := deps.loadSentinelConfig()
	if err != nil {
		return newUnavailableStartupProvider(sentinel.StatusReasonSDKResolutionFailed)
	}
	provider, err := deps.buildSentinelProvider(cfg)
	if err != nil || provider == nil {
		return newUnavailableStartupProvider(sentinel.StatusReasonSDKResolutionFailed)
	}
	profile, err := pool.Select(deps.draw)
	if err != nil {
		return newUnavailableStartupProvider(readiness.ReasonSentinelUnavailable)
	}
	timeout := startupDryRunTimeout(cfg)
	client, err := deps.newProfiledClient(profile, "", timeout)
	if err != nil || client == nil {
		return newUnavailableStartupProvider(sentinel.StatusReasonRequirementsFailed)
	}
	defer client.CloseIdleConnections()

	dryRunContext, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	provider.DryRun(dryRunContext, client, profile)
	return provider
}

func loadFingerprintPool() (fingerprint.Pool, error) {
	raw := strings.TrimSpace(os.Getenv("GO_PROTOCOL_FINGERPRINT_POOL"))
	if raw == "" {
		raw = fingerprint.DefaultPool
	}
	return fingerprint.ParsePool(raw)
}

func startupDryRunTimeout(cfg sentinel.Config) time.Duration {
	const fallback = 65 * time.Second
	if cfg.HTTPTimeout <= 0 || cfg.VMTimeout <= 0 {
		return fallback
	}
	const maxDuration = time.Duration(1<<63 - 1)
	if cfg.HTTPTimeout > (maxDuration-cfg.VMTimeout)/2 {
		return maxDuration
	}
	return 2*cfg.HTTPTimeout + cfg.VMTimeout
}

func (deps runtimeDependencies) withDefaults() runtimeDependencies {
	if deps.loadSentinelConfig == nil {
		deps.loadSentinelConfig = sentinel.LoadConfigFromEnv
	}
	if deps.buildSentinelProvider == nil {
		deps.buildSentinelProvider = buildSentinelProvider
	}
	if deps.newProfiledClient == nil {
		deps.newProfiledClient = httpclient.NewProfiled
	}
	if deps.draw == nil {
		deps.draw = fingerprint.CryptoDraw
	}
	if deps.newRegisterEngine == nil {
		deps.newRegisterEngine = func(cfg register.HTTPRegisterEngineConfig) register.Engine {
			return register.NewHTTPRegisterEngine(cfg)
		}
	}
	return deps
}

func buildSentinelProvider(cfg sentinel.Config) (startupSentinelProvider, error) {
	resolver, err := sentinel.NewResolver(cfg)
	if err != nil {
		return nil, err
	}
	compiler, err := sentinel.NewCompiler(resolver)
	if err != nil {
		return nil, err
	}
	runtime, err := sentinel.NewRuntime(cfg.VMTimeout)
	if err != nil {
		return nil, err
	}
	return sentinel.NewProvider(cfg, resolver, compiler, runtime)
}

type unavailableStartupProvider struct {
	status sentinel.Status
}

func newUnavailableStartupProvider(reason string) *unavailableStartupProvider {
	reason = readiness.SanitizeReason(reason)
	if reason == "" {
		reason = readiness.ReasonSentinelUnavailable
	}
	return &unavailableStartupProvider{status: sentinel.Status{Reason: reason}}
}

func (p *unavailableStartupProvider) Token(
	ctx context.Context,
	_ *http.Client,
	_ fingerprint.Profile,
	_, _ string,
) (openai.SentinelResult, error) {
	return (openai.UnavailableSentinelProvider{}).Token(ctx, nil, fingerprint.Profile{}, "", "")
}

func (p *unavailableStartupProvider) DryRun(
	_ context.Context,
	_ *http.Client,
	_ fingerprint.Profile,
) sentinel.Status {
	return p.Status()
}

func (p *unavailableStartupProvider) Status() sentinel.Status {
	if p == nil {
		return sentinel.Status{Reason: readiness.ReasonSentinelUnavailable}
	}
	return p.status
}

func positiveEnv(name string, fallback int) int {
	raw := os.Getenv(name)
	if raw == "" {
		return fallback
	}
	parsed, err := strconv.Atoi(raw)
	if err != nil || parsed <= 0 {
		return fallback
	}
	return parsed
}

var _ startupSentinelProvider = (*unavailableStartupProvider)(nil)
