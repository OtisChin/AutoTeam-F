package main

import (
	"context"
	"net/http"
	"slices"
	"sync"
	"testing"
	"time"

	"autoteam-f/protocol-register/internal/fingerprint"
	"autoteam-f/protocol-register/internal/model"
	"autoteam-f/protocol-register/internal/openai"
	"autoteam-f/protocol-register/internal/readiness"
	"autoteam-f/protocol-register/internal/register"
	"autoteam-f/protocol-register/internal/sentinel"
)

func TestNotImplementedEngineUsesCompatibleStatus(t *testing.T) {
	response := (notImplementedEngine{}).Register(nil, model.RegisterRequest{Email: "user@example.com"})
	if response.Status != "register_failed" || response.Error == nil || response.Error.Code != "not_implemented" {
		t.Fatalf("response=%#v", response)
	}
}

func TestLoadRuntimeUsesExactDefaultPoolAndBoundedSentinelDryRun(t *testing.T) {
	t.Setenv("GO_PROTOCOL_FINGERPRINT_POOL", "")
	t.Setenv("GO_PROTOCOL_MAX_CONCURRENCY", "17")
	t.Setenv("GO_PROTOCOL_AUTH_CONCURRENCY", "5")

	provider := newFakeStartupProvider(sentinel.Status{Ready: true, SDKVersion: "fixtureA1"})
	capture := &runtimeCapture{}
	runtime := loadRuntime(context.Background(), testRuntimeDependencies(t, provider, capture, 1))
	snapshot := runtime.ServerConfig.HealthSource.Snapshot()

	wantPool := []string{"chrome144", "chrome146", "chrome150"}
	if !snapshot.ProtocolReady || !snapshot.SentinelReady || snapshot.SentinelSDKVersion != "fixtureA1" ||
		!slices.Equal(snapshot.FingerprintPool, wantPool) {
		t.Fatalf("snapshot=%#v", snapshot)
	}
	if runtime.Engine == nil || runtime.ServerConfig.MaxConcurrency != 17 || runtime.ServerConfig.AuthConcurrency != 5 {
		t.Fatalf("runtime=%#v", runtime)
	}
	if capture.clientCalls != 1 || capture.clientProfile != "chrome146" || capture.clientProxy != "" || capture.clientTimeout <= 0 {
		t.Fatalf("capture=%#v", capture)
	}
	dryRuns, tokenCalls, profile, bounded := provider.calls()
	if dryRuns != 1 || tokenCalls != 0 || profile != "chrome146" || !bounded {
		t.Fatalf("dry_runs=%d token_calls=%d profile=%q bounded=%v", dryRuns, tokenCalls, profile, bounded)
	}
	if !slices.Equal(capture.engineConfig.FingerprintPool.Names(), wantPool) ||
		capture.engineConfig.SentinelProvider != provider || capture.engineConfig.AuthConcurrency != 5 {
		t.Fatalf("engine config=%#v", capture.engineConfig)
	}
}

func TestLoadRuntimeDeduplicatesConfiguredPoolWithoutReordering(t *testing.T) {
	t.Setenv("GO_PROTOCOL_FINGERPRINT_POOL", " chrome150,chrome144,chrome150,chrome144 ")
	provider := newFakeStartupProvider(sentinel.Status{Ready: true, SDKVersion: "fixtureB2"})
	capture := &runtimeCapture{}
	runtime := loadRuntime(context.Background(), testRuntimeDependencies(t, provider, capture, 0))

	want := []string{"chrome150", "chrome144"}
	if got := runtime.ServerConfig.HealthSource.Snapshot().FingerprintPool; !slices.Equal(got, want) {
		t.Fatalf("fingerprint pool=%v, want %v", got, want)
	}
	if got := capture.engineConfig.FingerprintPool.Names(); !slices.Equal(got, want) {
		t.Fatalf("engine fingerprint pool=%v, want %v", got, want)
	}
}

func TestLoadRuntimeStartsFailClosedWithUnsupportedPool(t *testing.T) {
	t.Setenv("GO_PROTOCOL_FINGERPRINT_POOL", "chrome144,chrome999")
	provider := newFakeStartupProvider(sentinel.Status{Ready: true, SDKVersion: "must-not-run"})
	capture := &runtimeCapture{}
	runtime := loadRuntime(context.Background(), testRuntimeDependencies(t, provider, capture, 0))
	snapshot := runtime.ServerConfig.HealthSource.Snapshot()

	if runtime.Engine == nil || runtime.ServerConfig.HealthSource == nil {
		t.Fatalf("daemon runtime was not constructed: %#v", runtime)
	}
	if snapshot.ProtocolReady || snapshot.ReadyReason != readiness.ReasonFingerprintPoolInvalid || len(snapshot.FingerprintPool) != 0 {
		t.Fatalf("snapshot=%#v", snapshot)
	}
	dryRuns, tokenCalls, _, _ := provider.calls()
	if dryRuns != 0 || tokenCalls != 0 || capture.clientCalls != 0 {
		t.Fatalf("dry_runs=%d token_calls=%d client_calls=%d", dryRuns, tokenCalls, capture.clientCalls)
	}
	if len(capture.engineConfig.FingerprintPool.Names()) != 0 {
		t.Fatalf("invalid pool unexpectedly replaced: %v", capture.engineConfig.FingerprintPool.Names())
	}
}

func TestLoadRuntimeUsesLiveSentinelStatusInsteadOfHardCodedReadiness(t *testing.T) {
	t.Setenv("GO_PROTOCOL_FINGERPRINT_POOL", "chrome144")
	provider := newFakeStartupProvider(sentinel.Status{Reason: sentinel.StatusReasonRequirementsFailed})
	runtime := loadRuntime(context.Background(), testRuntimeDependencies(t, provider, &runtimeCapture{}, 0))

	first := runtime.ServerConfig.HealthSource.Snapshot()
	if first.ProtocolReady || first.ReadyReason != sentinel.StatusReasonRequirementsFailed {
		t.Fatalf("first snapshot=%#v", first)
	}
	provider.setStatus(sentinel.Status{Ready: true, SDKVersion: "lastGoodC3"})
	second := runtime.ServerConfig.HealthSource.Snapshot()
	if !second.ProtocolReady || second.SentinelSDKVersion != "lastGoodC3" || second.ReadyReason != "" {
		t.Fatalf("second snapshot=%#v", second)
	}
}

type runtimeCapture struct {
	clientCalls   int
	clientProfile string
	clientProxy   string
	clientTimeout time.Duration
	engineConfig  register.HTTPRegisterEngineConfig
}

func testRuntimeDependencies(
	t *testing.T,
	provider startupSentinelProvider,
	capture *runtimeCapture,
	selectedIndex int,
) runtimeDependencies {
	t.Helper()
	return runtimeDependencies{
		loadSentinelConfig: func() (sentinel.Config, error) {
			return sentinel.Config{HTTPTimeout: 20 * time.Millisecond, VMTimeout: 30 * time.Millisecond}, nil
		},
		buildSentinelProvider: func(sentinel.Config) (startupSentinelProvider, error) {
			return provider, nil
		},
		newProfiledClient: func(profile fingerprint.Profile, proxyURL string, timeout time.Duration) (*http.Client, error) {
			capture.clientCalls++
			capture.clientProfile = profile.Name
			capture.clientProxy = proxyURL
			capture.clientTimeout = timeout
			return &http.Client{}, nil
		},
		draw: func(max int) (int, error) {
			if selectedIndex < 0 || selectedIndex >= max {
				t.Fatalf("selected index %d outside pool size %d", selectedIndex, max)
			}
			return selectedIndex, nil
		},
		newRegisterEngine: func(cfg register.HTTPRegisterEngineConfig) register.Engine {
			capture.engineConfig = cfg
			return notImplementedEngine{}
		},
	}
}

type fakeStartupProvider struct {
	mu              sync.RWMutex
	status          sentinel.Status
	dryRunResult    sentinel.Status
	dryRuns         int
	tokenCalls      int
	dryRunProfile   string
	dryRunIsBounded bool
}

func newFakeStartupProvider(dryRunResult sentinel.Status) *fakeStartupProvider {
	return &fakeStartupProvider{
		status:       sentinel.Status{Reason: sentinel.StatusReasonNotChecked},
		dryRunResult: dryRunResult,
	}
}

func (p *fakeStartupProvider) Token(
	context.Context,
	*http.Client,
	fingerprint.Profile,
	string,
	string,
) (openai.SentinelResult, error) {
	p.mu.Lock()
	p.tokenCalls++
	p.mu.Unlock()
	return openai.SentinelResult{}, openai.ErrSentinelUnavailable
}

func (p *fakeStartupProvider) DryRun(ctx context.Context, _ *http.Client, profile fingerprint.Profile) sentinel.Status {
	_, bounded := ctx.Deadline()
	p.mu.Lock()
	p.dryRuns++
	p.dryRunProfile = profile.Name
	p.dryRunIsBounded = bounded
	p.status = p.dryRunResult
	status := p.status
	p.mu.Unlock()
	return status
}

func (p *fakeStartupProvider) Status() sentinel.Status {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.status
}

func (p *fakeStartupProvider) setStatus(status sentinel.Status) {
	p.mu.Lock()
	p.status = status
	p.mu.Unlock()
}

func (p *fakeStartupProvider) calls() (dryRuns, tokenCalls int, profile string, bounded bool) {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.dryRuns, p.tokenCalls, p.dryRunProfile, p.dryRunIsBounded
}

var _ startupSentinelProvider = (*fakeStartupProvider)(nil)
