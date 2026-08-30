package sentinel

import (
	"bytes"
	"context"
	"errors"
	"io"
	"net/http"
	"slices"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"autoteam-f/protocol-register/internal/fingerprint"
	"autoteam-f/protocol-register/internal/openai"

	"github.com/dop251/goja"
)

func TestProviderFallsBackAfterCompileOrRequirementsIncompatibility(t *testing.T) {
	first := sdkForVersion("candidateA1", SDKSourceDiscovery)
	second := sdkForVersion("candidateB2", SDKSourceBuiltin)
	tests := []struct {
		name                string
		configure           func(*providerHarness)
		wantRequirementSDKs []string
	}{
		{
			name: "compile incompatibility",
			configure: func(h *providerHarness) {
				base := h.compiler.fn
				h.compiler.fn = func(sdk SDK) (*CompiledSDK, error) {
					if sdk.Version == first.Version {
						return nil, ErrUnsupportedSDK
					}
					return base(sdk)
				}
			},
			wantRequirementSDKs: []string{second.Version},
		},
		{
			name: "requirements incompatibility",
			configure: func(h *providerHarness) {
				base := h.runtime.requirementsFn
				h.runtime.requirementsFn = func(compiled *CompiledSDK, deviceID string) (string, error) {
					if compiled.SDK.Version == first.Version {
						return "", ErrRuntimeExecution
					}
					return base(compiled, deviceID)
				}
			},
			wantRequirementSDKs: []string{first.Version, second.Version},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			h := newProviderHarness(t, []SDK{first, first, second})
			tt.configure(h)

			result, err := h.provider.Token(
				context.Background(), http.DefaultClient, runtimeTestProfile(t), "did-123", "authorize_continue",
			)
			if err != nil {
				t.Fatalf("Token() error=%v", err)
			}
			assertProviderResult(t, result, second, "did-123", "authorize_continue")
			if got := h.compiler.versions(); !slices.Equal(got, []string{first.Version, second.Version}) {
				t.Fatalf("compile SDKs=%v", got)
			}
			if got := h.runtime.requirementVersions(); !slices.Equal(got, tt.wantRequirementSDKs) {
				t.Fatalf("requirements SDKs=%v", got)
			}
			if got := h.challenge.versions(); !slices.Equal(got, []string{second.Version}) {
				t.Fatalf("challenge SDKs=%v", got)
			}
			if got := h.resolver.markedVersions(); !slices.Equal(got, []string{second.Version}) {
				t.Fatalf("marked SDKs=%v", got)
			}
			if status := h.provider.Status(); status != (Status{Ready: true, SDKVersion: second.Version}) {
				t.Fatalf("Status()=%#v", status)
			}
		})
	}
}

func TestProviderChallengeFailureReturnsImmediatelyAndPreservesReadyStatus(t *testing.T) {
	first := sdkForVersion("challengeA1", SDKSourceDiscovery)
	second := sdkForVersion("challengeB2", SDKSourceBuiltin)
	h := newProviderHarness(t, []SDK{first, second})
	if _, err := h.provider.Token(context.Background(), http.DefaultClient, runtimeTestProfile(t), "did-ready", "flow-ready"); err != nil {
		t.Fatalf("initial Token() error=%v", err)
	}
	wantStatus := h.provider.Status()
	h.resetCalls()
	h.challenge.fn = func(SDK, string, string, string) (challengeResult, error) {
		return challengeResult{}, ErrHTTPTransport
	}

	result, err := h.provider.Token(
		context.Background(), http.DefaultClient, runtimeTestProfile(t), "did-fail", "flow-fail",
	)
	if !errors.Is(err, openai.ErrChallengeUnavailable) {
		t.Fatalf("Token() error=%v", err)
	}
	if result != (openai.SentinelResult{}) {
		t.Fatalf("Token() result=%#v", result)
	}
	if got := h.compiler.versions(); !slices.Equal(got, []string{first.Version}) {
		t.Fatalf("compile SDKs=%v", got)
	}
	if got := h.runtime.requirementVersions(); !slices.Equal(got, []string{first.Version}) {
		t.Fatalf("requirements SDKs=%v", got)
	}
	if got := h.challenge.versions(); !slices.Equal(got, []string{first.Version}) {
		t.Fatalf("challenge SDKs=%v", got)
	}
	if got := h.runtime.solveVersions(); len(got) != 0 {
		t.Fatalf("solve SDKs=%v", got)
	}
	if got := h.resolver.markedVersions(); len(got) != 0 {
		t.Fatalf("marked SDKs=%v", got)
	}
	if status := h.provider.Status(); status != wantStatus {
		t.Fatalf("Status()=%#v, want %#v", status, wantStatus)
	}
}

func TestProviderChallengeTimeoutPreservesDeadlineClassification(t *testing.T) {
	h := newProviderHarness(t, []SDK{sdkForVersion("challengeTimeout1", SDKSourceDiscovery)})
	h.challenge.fn = func(SDK, string, string, string) (challengeResult, error) {
		return challengeResult{}, context.DeadlineExceeded
	}

	_, err := h.provider.Token(
		context.Background(), http.DefaultClient, runtimeTestProfile(t), "did-timeout", "flow-timeout",
	)
	if !errors.Is(err, openai.ErrChallengeUnavailable) || !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("Token() error=%v", err)
	}
}

func TestProviderSolveIncompatibilityStartsFreshCycleOnNextCandidate(t *testing.T) {
	first := sdkForVersion("solveA1", SDKSourceDiscovery)
	second := sdkForVersion("solveB2", SDKSourceBuiltin)
	h := newProviderHarness(t, []SDK{first, second})
	base := h.runtime.solveFn
	h.runtime.solveFn = func(compiled *CompiledSDK, input SolveInput) (SolveOutput, error) {
		if compiled.SDK.Version == first.Version {
			return SolveOutput{}, ErrRuntimeExecution
		}
		return base(compiled, input)
	}

	result, err := h.provider.Token(
		context.Background(), http.DefaultClient, runtimeTestProfile(t), "did-solve", "flow-solve",
	)
	if err != nil {
		t.Fatalf("Token() error=%v", err)
	}
	assertProviderResult(t, result, second, "did-solve", "flow-solve")
	for name, got := range map[string][]string{
		"compile":      h.compiler.versions(),
		"requirements": h.runtime.requirementVersions(),
		"challenge":    h.challenge.versions(),
		"solve":        h.runtime.solveVersions(),
	} {
		if !slices.Equal(got, []string{first.Version, second.Version}) {
			t.Fatalf("%s SDKs=%v", name, got)
		}
	}
	if got := h.resolver.markedVersions(); !slices.Equal(got, []string{second.Version}) {
		t.Fatalf("marked SDKs=%v", got)
	}
	challengeCalls := h.challenge.snapshot()
	if challengeCalls[0].requestP != "request-"+first.Version || challengeCalls[1].requestP != "request-"+second.Version {
		t.Fatalf("challenge calls=%#v", challengeCalls)
	}
}

func TestProviderRejectsInvalidFinalTokenWithoutSyntheticFallbackOrMarkGood(t *testing.T) {
	sdk := sdkForVersion("invalidFinal1", SDKSourceDiscovery)
	tests := []struct {
		name      string
		configure func(*providerHarness)
	}{
		{
			name: "empty final p",
			configure: func(h *providerHarness) {
				h.runtime.solveFn = func(*CompiledSDK, SolveInput) (SolveOutput, error) {
					return SolveOutput{FinalP: " ", T: "turn"}, nil
				}
			},
		},
		{
			name: "empty turnstile token",
			configure: func(h *providerHarness) {
				h.runtime.solveFn = func(*CompiledSDK, SolveInput) (SolveOutput, error) {
					return SolveOutput{FinalP: "final", T: " "}, nil
				}
			},
		},
		{
			name: "oversized final token",
			configure: func(h *providerHarness) {
				h.challenge.fn = func(sdk SDK, _, _, _ string) (challengeResult, error) {
					token := strings.Repeat("c", maxRuntimeOutputBytes)
					return challengeResult{Payload: map[string]any{"token": token}, Token: token}, nil
				}
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			h := newProviderHarness(t, []SDK{sdk})
			tt.configure(h)
			result, err := h.provider.Token(
				context.Background(), http.DefaultClient, runtimeTestProfile(t), "did-invalid", "flow-invalid",
			)
			if !errors.Is(err, openai.ErrChallengeUnavailable) {
				t.Fatalf("Token() error=%v", err)
			}
			if result != (openai.SentinelResult{}) || strings.TrimSpace(result.Token) != "" {
				t.Fatalf("Token() returned synthetic result=%#v", result)
			}
			if got := h.resolver.markedVersions(); len(got) != 0 {
				t.Fatalf("marked SDKs=%v", got)
			}
		})
	}
}

func TestProviderDryRunFallsBackWithoutChallengeAndUpdatesStatus(t *testing.T) {
	first := sdkForVersion("dryRunA1", SDKSourceDiscovery)
	second := sdkForVersion("dryRunB2", SDKSourceLastGood)
	h := newProviderHarness(t, []SDK{first, first, second})
	base := h.compiler.fn
	h.compiler.fn = func(sdk SDK) (*CompiledSDK, error) {
		if sdk.Version == first.Version {
			return nil, ErrUnsupportedSDK
		}
		return base(sdk)
	}

	status := h.provider.DryRun(context.Background(), http.DefaultClient, runtimeTestProfile(t))
	want := Status{Ready: true, SDKVersion: second.Version}
	if status != want || h.provider.Status() != want {
		t.Fatalf("DryRun()=%#v Status()=%#v", status, h.provider.Status())
	}
	if got := h.challenge.versions(); len(got) != 0 {
		t.Fatalf("DryRun made challenge calls=%v", got)
	}
	if got := h.runtime.solveVersions(); len(got) != 0 {
		t.Fatalf("DryRun made solve calls=%v", got)
	}
	if got := h.resolver.markedVersions(); len(got) != 0 {
		t.Fatalf("DryRun marked SDKs=%v", got)
	}
}

func TestProviderDryRunReportsDeepestSanitizedFailureReason(t *testing.T) {
	sdk := sdkForVersion("dryFailA1", SDKSourceDiscovery)
	tests := []struct {
		name      string
		configure func(*providerHarness)
		want      string
	}{
		{
			name: "resolution",
			configure: func(h *providerHarness) {
				h.resolver.err = errors.New("private resolution response")
			},
			want: StatusReasonSDKResolutionFailed,
		},
		{
			name: "compile",
			configure: func(h *providerHarness) {
				h.compiler.fn = func(SDK) (*CompiledSDK, error) {
					return nil, errors.New("private compile source")
				}
			},
			want: StatusReasonSDKCompileFailed,
		},
		{
			name: "requirements",
			configure: func(h *providerHarness) {
				h.runtime.requirementsFn = func(*CompiledSDK, string) (string, error) {
					return "", errors.New("private requirements output")
				}
			},
			want: StatusReasonRequirementsFailed,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			h := newProviderHarness(t, []SDK{sdk})
			if status := h.provider.Status(); status.Reason != StatusReasonNotChecked || status.Ready {
				t.Fatalf("initial Status()=%#v", status)
			}
			tt.configure(h)
			status := h.provider.DryRun(context.Background(), http.DefaultClient, runtimeTestProfile(t))
			if status.Ready || status.SDKVersion != "" || status.Reason != tt.want {
				t.Fatalf("DryRun()=%#v", status)
			}
			if strings.Contains(status.Reason, "private") {
				t.Fatalf("DryRun leaked private reason=%q", status.Reason)
			}
		})
	}
}

func TestProviderFailedRefreshStaysReadyOnlyWhileValidatedLastGoodExecutes(t *testing.T) {
	lastGood := sdkForVersion("lastGoodA1", SDKSourceDiscovery)
	refresh := sdkForVersion("refreshB2", SDKSourceDiscovery)
	h := newProviderHarness(t, []SDK{lastGood})
	if _, err := h.provider.Token(context.Background(), http.DefaultClient, runtimeTestProfile(t), "did", "flow"); err != nil {
		t.Fatalf("Token() error=%v", err)
	}
	if got := h.resolver.markedVersions(); !slices.Equal(got, []string{lastGood.Version}) {
		t.Fatalf("marked SDKs=%v", got)
	}
	lastGood.Source = SDKSourceLastGood
	h.resolver.setCandidates([]SDK{refresh, lastGood})
	baseCompile := h.compiler.fn
	h.compiler.fn = func(sdk SDK) (*CompiledSDK, error) {
		if sdk.Version == refresh.Version {
			return nil, ErrUnsupportedSDK
		}
		return baseCompile(sdk)
	}
	challengeCalls := len(h.challenge.snapshot())

	status := h.provider.DryRun(context.Background(), http.DefaultClient, runtimeTestProfile(t))
	if status != (Status{Ready: true, SDKVersion: lastGood.Version}) {
		t.Fatalf("DryRun(last-good)=%#v", status)
	}
	if len(h.challenge.snapshot()) != challengeCalls {
		t.Fatal("DryRun unexpectedly called challenge endpoint")
	}

	h.runtime.requirementsFn = func(*CompiledSDK, string) (string, error) {
		return "", ErrRuntimeExecution
	}
	status = h.provider.DryRun(context.Background(), http.DefaultClient, runtimeTestProfile(t))
	if status.Ready || status.Reason != StatusReasonRequirementsFailed {
		t.Fatalf("DryRun(failed last-good)=%#v", status)
	}
}

func TestProviderTokenDoesNotSerializeConcurrentCalls(t *testing.T) {
	sdk := sdkForVersion("parallelA1", SDKSourceDiscovery)
	h := newProviderHarness(t, []SDK{sdk})
	const workers = 24
	var active atomic.Int32
	var peak atomic.Int32
	allEntered := make(chan struct{})
	release := make(chan struct{})
	var enteredOnce sync.Once
	h.runtime.requirementsFn = func(compiled *CompiledSDK, _ string) (string, error) {
		current := active.Add(1)
		for {
			seen := peak.Load()
			if current <= seen || peak.CompareAndSwap(seen, current) {
				break
			}
		}
		if current == workers {
			enteredOnce.Do(func() { close(allEntered) })
		}
		<-release
		active.Add(-1)
		return "request-" + compiled.SDK.Version, nil
	}

	start := make(chan struct{})
	errorsSeen := make(chan error, workers)
	var wait sync.WaitGroup
	profile := runtimeTestProfile(t)
	for index := range workers {
		wait.Add(1)
		go func() {
			defer wait.Done()
			<-start
			_, err := h.provider.Token(
				context.Background(), http.DefaultClient, profile, "did-parallel-"+string(rune('a'+index)), "flow",
			)
			errorsSeen <- err
		}()
	}
	close(start)
	select {
	case <-allEntered:
	case <-time.After(time.Second):
		close(release)
		wait.Wait()
		t.Fatalf("concurrent requirements peak=%d; Token appears serialized", peak.Load())
	}
	close(release)
	wait.Wait()
	close(errorsSeen)
	for err := range errorsSeen {
		if err != nil {
			t.Fatalf("Token() error=%v", err)
		}
	}
	if peak.Load() != workers {
		t.Fatalf("concurrent requirements peak=%d", peak.Load())
	}
	if status := h.provider.Status(); !status.Ready || status.SDKVersion != sdk.Version {
		t.Fatalf("Status()=%#v", status)
	}
}

func TestProviderRealResolverCompilerRuntimeLifecycleUsesOnlyFakeHTTP(t *testing.T) {
	sdk := sdkForVersion("integrationA1", SDKSourceEnvURL)
	cfg := testConfig(t)
	cfg.SDKURL = sdk.URL
	resolver, err := NewResolver(cfg)
	if err != nil {
		t.Fatal(err)
	}
	compiler, err := NewCompiler(resolver)
	if err != nil {
		t.Fatal(err)
	}
	runtime, err := NewRuntime(time.Second)
	if err != nil {
		t.Fatal(err)
	}
	provider, err := NewProvider(cfg, resolver, compiler, runtime)
	if err != nil {
		t.Fatal(err)
	}

	var sdkGets atomic.Int32
	var challengePosts atomic.Int32
	client := &http.Client{Transport: roundTripFunc(func(req *http.Request) (*http.Response, error) {
		switch {
		case req.Method == http.MethodGet && req.URL.String() == sdk.URL:
			sdkGets.Add(1)
			return bytesResponse(http.StatusOK, readSDKFixture(t, "old")), nil
		case req.Method == http.MethodPost && req.URL.String() == defaultRequestURL:
			challengePosts.Add(1)
			body, readErr := io.ReadAll(req.Body)
			if readErr != nil {
				t.Fatal(readErr)
			}
			if !bytes.Equal(body, []byte(`{"p":"requirements-old","id":"did-integration","flow":"authorize_continue"}`)) {
				t.Fatalf("challenge body=%s", body)
			}
			return bytesResponse(
				http.StatusOK,
				[]byte(`{"token":"challenge-token","turnstile":{"dx":"dx"}}`),
			), nil
		default:
			t.Fatalf("unexpected HTTP request: %s %s", req.Method, req.URL)
			return nil, errors.New("unexpected HTTP request")
		}
	})}

	result, err := provider.Token(
		context.Background(), client, runtimeTestProfile(t), "did-integration", "authorize_continue",
	)
	if err != nil {
		t.Fatalf("Token() error=%v", err)
	}
	wantToken := `{"p":"final-old","t":"requirements-old:dx","c":"challenge-token","id":"did-integration","flow":"authorize_continue"}`
	if result.Token != wantToken || result.SDKVersion != sdk.Version {
		t.Fatalf("Token()=%#v", result)
	}
	if sdkGets.Load() != 1 || challengePosts.Load() != 1 {
		t.Fatalf("sdk GETs=%d challenge POSTs=%d", sdkGets.Load(), challengePosts.Load())
	}
	if status := provider.Status(); status != (Status{Ready: true, SDKVersion: sdk.Version}) {
		t.Fatalf("Status()=%#v", status)
	}
	lastGood, ok := resolver.cache.readRecord(lastGoodCacheFile)
	if !ok || lastGood.SDK.Version != sdk.Version {
		t.Fatalf("last-good=%#v ok=%v", lastGood, ok)
	}
}

func TestNewProviderRejectsMissingDependenciesAndInvalidConfig(t *testing.T) {
	cfg := testConfig(t)
	resolver, err := NewResolver(cfg)
	if err != nil {
		t.Fatal(err)
	}
	compiler, err := NewCompiler(resolver)
	if err != nil {
		t.Fatal(err)
	}
	runtime, err := NewRuntime(time.Second)
	if err != nil {
		t.Fatal(err)
	}
	tests := []struct {
		name     string
		cfg      Config
		resolver *Resolver
		compiler *Compiler
		runtime  *Runtime
	}{
		{name: "nil resolver", cfg: cfg, compiler: compiler, runtime: runtime},
		{name: "nil compiler", cfg: cfg, resolver: resolver, runtime: runtime},
		{name: "nil runtime", cfg: cfg, resolver: resolver, compiler: compiler},
		{
			name:     "invalid challenge URL",
			cfg:      func() Config { invalid := cfg; invalid.RequestURL = "https://attacker.example/private"; return invalid }(),
			resolver: resolver,
			compiler: compiler,
			runtime:  runtime,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if _, err := NewProvider(tt.cfg, tt.resolver, tt.compiler, tt.runtime); err == nil {
				t.Fatal("NewProvider() unexpectedly succeeded")
			}
		})
	}
}

func assertProviderResult(t *testing.T, result openai.SentinelResult, sdk SDK, deviceID, flow string) {
	t.Helper()
	want := `{"p":"final-` + sdk.Version + `","t":"turn-` + sdk.Version + `","c":"challenge-` + sdk.Version + `","id":"` + deviceID + `","flow":"` + flow + `"}`
	if result.Token != want || result.SDKVersion != sdk.Version {
		t.Fatalf("SentinelResult=%#v, want token=%s sdk=%s", result, want, sdk.Version)
	}
}

type providerHarness struct {
	provider  *Provider
	resolver  *fakeProviderResolver
	compiler  *fakeProviderCompiler
	runtime   *fakeProviderRuntime
	challenge *fakeProviderChallenge
}

func newProviderHarness(t *testing.T, candidates []SDK) *providerHarness {
	t.Helper()
	program, err := goja.Compile("provider-fixture.js", "", true)
	if err != nil {
		t.Fatal(err)
	}
	resolver := &fakeProviderResolver{candidates: append([]SDK(nil), candidates...)}
	compiler := &fakeProviderCompiler{}
	compiler.fn = func(sdk SDK) (*CompiledSDK, error) {
		return &CompiledSDK{SDK: sdk, Program: program}, nil
	}
	runtime := &fakeProviderRuntime{}
	runtime.requirementsFn = func(compiled *CompiledSDK, _ string) (string, error) {
		return "request-" + compiled.SDK.Version, nil
	}
	runtime.solveFn = func(compiled *CompiledSDK, _ SolveInput) (SolveOutput, error) {
		return SolveOutput{FinalP: "final-" + compiled.SDK.Version, T: "turn-" + compiled.SDK.Version}, nil
	}
	challenge := &fakeProviderChallenge{}
	challenge.fn = func(sdk SDK, _, _, _ string) (challengeResult, error) {
		token := "challenge-" + sdk.Version
		return challengeResult{
			Payload: map[string]any{"token": token, "turnstile": map[string]any{"dx": "dx"}},
			Token:   token,
		}, nil
	}
	provider, err := newProvider(resolver, compiler, runtime, challenge)
	if err != nil {
		t.Fatalf("newProvider() error=%v", err)
	}
	return &providerHarness{
		provider: provider, resolver: resolver, compiler: compiler, runtime: runtime, challenge: challenge,
	}
}

func (h *providerHarness) resetCalls() {
	h.resolver.resetMarked()
	h.compiler.reset()
	h.runtime.reset()
	h.challenge.reset()
}

type fakeProviderResolver struct {
	mu         sync.RWMutex
	candidates []SDK
	err        error
	marked     []SDK
}

func (r *fakeProviderResolver) Candidates(ctx context.Context, _ *http.Client) ([]SDK, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	r.mu.RLock()
	defer r.mu.RUnlock()
	return append([]SDK(nil), r.candidates...), r.err
}

func (r *fakeProviderResolver) MarkGood(sdk SDK) error {
	r.mu.Lock()
	r.marked = append(r.marked, sdk)
	r.mu.Unlock()
	return nil
}

func (r *fakeProviderResolver) setCandidates(candidates []SDK) {
	r.mu.Lock()
	r.candidates = append([]SDK(nil), candidates...)
	r.mu.Unlock()
}

func (r *fakeProviderResolver) markedVersions() []string {
	r.mu.RLock()
	defer r.mu.RUnlock()
	versions := make([]string, len(r.marked))
	for index, sdk := range r.marked {
		versions[index] = sdk.Version
	}
	return versions
}

func (r *fakeProviderResolver) resetMarked() {
	r.mu.Lock()
	r.marked = nil
	r.mu.Unlock()
}

type fakeProviderCompiler struct {
	mu    sync.Mutex
	fn    func(SDK) (*CompiledSDK, error)
	calls []SDK
}

func (c *fakeProviderCompiler) Compile(ctx context.Context, _ *http.Client, sdk SDK) (*CompiledSDK, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	c.mu.Lock()
	c.calls = append(c.calls, sdk)
	fn := c.fn
	c.mu.Unlock()
	return fn(sdk)
}

func (c *fakeProviderCompiler) versions() []string {
	c.mu.Lock()
	defer c.mu.Unlock()
	versions := make([]string, len(c.calls))
	for index, sdk := range c.calls {
		versions[index] = sdk.Version
	}
	return versions
}

func (c *fakeProviderCompiler) reset() {
	c.mu.Lock()
	c.calls = nil
	c.mu.Unlock()
}

type providerRuntimeCall struct {
	compiled *CompiledSDK
	deviceID string
	input    SolveInput
}

type fakeProviderRuntime struct {
	mu             sync.Mutex
	requirementsFn func(*CompiledSDK, string) (string, error)
	solveFn        func(*CompiledSDK, SolveInput) (SolveOutput, error)
	requirements   []providerRuntimeCall
	solves         []providerRuntimeCall
}

func (r *fakeProviderRuntime) Requirements(ctx context.Context, compiled *CompiledSDK, _ fingerprint.Profile, deviceID string) (string, error) {
	if err := ctx.Err(); err != nil {
		return "", err
	}
	r.mu.Lock()
	r.requirements = append(r.requirements, providerRuntimeCall{compiled: compiled, deviceID: deviceID})
	fn := r.requirementsFn
	r.mu.Unlock()
	return fn(compiled, deviceID)
}

func (r *fakeProviderRuntime) Solve(ctx context.Context, compiled *CompiledSDK, _ fingerprint.Profile, input SolveInput) (SolveOutput, error) {
	if err := ctx.Err(); err != nil {
		return SolveOutput{}, err
	}
	r.mu.Lock()
	r.solves = append(r.solves, providerRuntimeCall{compiled: compiled, input: input})
	fn := r.solveFn
	r.mu.Unlock()
	return fn(compiled, input)
}

func (r *fakeProviderRuntime) requirementVersions() []string {
	r.mu.Lock()
	defer r.mu.Unlock()
	versions := make([]string, len(r.requirements))
	for index, call := range r.requirements {
		versions[index] = call.compiled.SDK.Version
	}
	return versions
}

func (r *fakeProviderRuntime) solveVersions() []string {
	r.mu.Lock()
	defer r.mu.Unlock()
	versions := make([]string, len(r.solves))
	for index, call := range r.solves {
		versions[index] = call.compiled.SDK.Version
	}
	return versions
}

func (r *fakeProviderRuntime) reset() {
	r.mu.Lock()
	r.requirements = nil
	r.solves = nil
	r.mu.Unlock()
}

type providerChallengeCall struct {
	sdk      SDK
	deviceID string
	flow     string
	requestP string
}

type fakeProviderChallenge struct {
	mu    sync.Mutex
	fn    func(SDK, string, string, string) (challengeResult, error)
	calls []providerChallengeCall
}

func (c *fakeProviderChallenge) Fetch(
	ctx context.Context,
	_ *http.Client,
	_ fingerprint.Profile,
	sdk SDK,
	deviceID string,
	flow string,
	requestP string,
) (challengeResult, error) {
	if err := ctx.Err(); err != nil {
		return challengeResult{}, err
	}
	c.mu.Lock()
	c.calls = append(c.calls, providerChallengeCall{sdk: sdk, deviceID: deviceID, flow: flow, requestP: requestP})
	fn := c.fn
	c.mu.Unlock()
	return fn(sdk, deviceID, flow, requestP)
}

func (c *fakeProviderChallenge) versions() []string {
	c.mu.Lock()
	defer c.mu.Unlock()
	versions := make([]string, len(c.calls))
	for index, call := range c.calls {
		versions[index] = call.sdk.Version
	}
	return versions
}

func (c *fakeProviderChallenge) snapshot() []providerChallengeCall {
	c.mu.Lock()
	defer c.mu.Unlock()
	return append([]providerChallengeCall(nil), c.calls...)
}

func (c *fakeProviderChallenge) reset() {
	c.mu.Lock()
	c.calls = nil
	c.mu.Unlock()
}
