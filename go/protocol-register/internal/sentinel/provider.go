package sentinel

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"sync/atomic"

	"autoteam-f/protocol-register/internal/fingerprint"
	"autoteam-f/protocol-register/internal/openai"
)

var ErrInvalidProvider = errors.New("invalid Sentinel provider")

const (
	StatusReasonNotChecked          = "sentinel_not_checked"
	StatusReasonSDKResolutionFailed = "sentinel_sdk_resolution_failed"
	StatusReasonSDKCompileFailed    = "sentinel_sdk_compile_failed"
	StatusReasonRequirementsFailed  = "sentinel_requirements_failed"
)

type Status struct {
	Ready      bool
	SDKVersion string
	Reason     string
}

type providerResolver interface {
	Candidates(context.Context, *http.Client) ([]SDK, error)
	MarkGood(SDK) error
}

type providerCompiler interface {
	Compile(context.Context, *http.Client, SDK) (*CompiledSDK, error)
}

type providerRuntime interface {
	Requirements(context.Context, *CompiledSDK, fingerprint.Profile, string) (string, error)
	Solve(context.Context, *CompiledSDK, fingerprint.Profile, SolveInput) (SolveOutput, error)
}

type providerChallenge interface {
	Fetch(context.Context, *http.Client, fingerprint.Profile, SDK, string, string, string) (challengeResult, error)
}

type Provider struct {
	resolver  providerResolver
	compiler  providerCompiler
	runtime   providerRuntime
	challenge providerChallenge
	status    atomic.Pointer[Status]
}

type finalToken struct {
	P    string `json:"p"`
	T    string `json:"t"`
	C    string `json:"c"`
	ID   string `json:"id"`
	Flow string `json:"flow"`
}

func NewProvider(cfg Config, resolver *Resolver, compiler *Compiler, runtime *Runtime) (*Provider, error) {
	if resolver == nil || compiler == nil || runtime == nil {
		return nil, ErrInvalidProvider
	}
	challenge, err := newChallengeTransport(cfg)
	if err != nil {
		return nil, err
	}
	return newProvider(resolver, compiler, runtime, challenge)
}

func newProvider(
	resolver providerResolver,
	compiler providerCompiler,
	runtime providerRuntime,
	challenge providerChallenge,
) (*Provider, error) {
	if resolver == nil || compiler == nil || runtime == nil || challenge == nil {
		return nil, ErrInvalidProvider
	}
	provider := &Provider{
		resolver:  resolver,
		compiler:  compiler,
		runtime:   runtime,
		challenge: challenge,
	}
	provider.storeStatus(Status{Reason: StatusReasonNotChecked})
	return provider, nil
}

func (p *Provider) Token(
	ctx context.Context,
	client *http.Client,
	profile fingerprint.Profile,
	deviceID string,
	flow string,
) (openai.SentinelResult, error) {
	if p == nil || p.resolver == nil || p.compiler == nil || p.runtime == nil || p.challenge == nil ||
		ctx == nil || client == nil || !validChallengeProfile(profile) {
		return openai.SentinelResult{}, providerUnavailable(ctx)
	}
	if err := ctx.Err(); err != nil {
		return openai.SentinelResult{}, providerUnavailable(ctx)
	}
	deviceID = strings.TrimSpace(deviceID)
	flow = strings.TrimSpace(flow)
	if deviceID == "" || flow == "" || len(deviceID) > maxRuntimeOutputBytes || len(flow) > maxRuntimeOutputBytes {
		return openai.SentinelResult{}, openai.ErrSentinelUnavailable
	}

	candidates, err := p.resolver.Candidates(ctx, client)
	if err != nil {
		return openai.SentinelResult{}, providerUnavailable(ctx)
	}
	for _, sdk := range deduplicateSDKs(candidates) {
		if err := ctx.Err(); err != nil {
			return openai.SentinelResult{}, providerUnavailable(ctx)
		}
		compiled, err := p.compiler.Compile(ctx, client, sdk)
		if err != nil || !compiledMatchesSDK(compiled, sdk) {
			if ctx.Err() != nil {
				return openai.SentinelResult{}, providerUnavailable(ctx)
			}
			continue
		}
		requestP, err := p.runtime.Requirements(ctx, compiled, profile, deviceID)
		requestP = strings.TrimSpace(requestP)
		if err != nil || requestP == "" || len(requestP) > maxRuntimeOutputBytes {
			if ctx.Err() != nil {
				return openai.SentinelResult{}, providerUnavailable(ctx)
			}
			continue
		}

		challenge, err := p.challenge.Fetch(ctx, client, profile, sdk, deviceID, flow, requestP)
		if err != nil || len(challenge.Payload) == 0 || strings.TrimSpace(challenge.Token) == "" {
			return openai.SentinelResult{}, providerUnavailable(ctx, err)
		}
		solved, err := p.runtime.Solve(ctx, compiled, profile, SolveInput{
			DeviceID:  deviceID,
			RequestP:  requestP,
			Challenge: challenge.Payload,
		})
		if err != nil {
			if ctx.Err() != nil {
				return openai.SentinelResult{}, providerUnavailable(ctx)
			}
			continue
		}
		token, err := encodeFinalToken(solved, challenge.Token, deviceID, flow)
		if err != nil {
			continue
		}

		_ = p.resolver.MarkGood(sdk)
		p.storeStatus(Status{Ready: true, SDKVersion: sdk.Version})
		return openai.SentinelResult{Token: token, SDKVersion: sdk.Version}, nil
	}
	return openai.SentinelResult{}, providerUnavailable(ctx)
}

func (p *Provider) DryRun(ctx context.Context, client *http.Client, profile fingerprint.Profile) Status {
	if p == nil || p.resolver == nil || p.compiler == nil || p.runtime == nil ||
		ctx == nil || client == nil || !validChallengeProfile(profile) {
		return p.updateFailureStatus(StatusReasonSDKResolutionFailed)
	}
	candidates, err := p.resolver.Candidates(ctx, client)
	if err != nil || len(candidates) == 0 {
		return p.updateFailureStatus(StatusReasonSDKResolutionFailed)
	}
	failureReason := StatusReasonSDKCompileFailed
	for _, sdk := range deduplicateSDKs(candidates) {
		compiled, err := p.compiler.Compile(ctx, client, sdk)
		if err != nil || !compiledMatchesSDK(compiled, sdk) {
			continue
		}
		failureReason = StatusReasonRequirementsFailed
		requestP, err := p.runtime.Requirements(ctx, compiled, profile, "sentinel-readiness-dry-run")
		requestP = strings.TrimSpace(requestP)
		if err != nil || requestP == "" || len(requestP) > maxRuntimeOutputBytes {
			continue
		}
		status := Status{Ready: true, SDKVersion: sdk.Version}
		p.storeStatus(status)
		return status
	}
	return p.updateFailureStatus(failureReason)
}

func (p *Provider) Status() Status {
	if p == nil {
		return Status{Reason: StatusReasonNotChecked}
	}
	status := p.status.Load()
	if status == nil {
		return Status{Reason: StatusReasonNotChecked}
	}
	return *status
}

func (p *Provider) storeStatus(status Status) {
	if p == nil {
		return
	}
	copy := status
	p.status.Store(&copy)
}

func (p *Provider) updateFailureStatus(reason string) Status {
	status := Status{Reason: reason}
	if p != nil {
		p.storeStatus(status)
	}
	return status
}

func compiledMatchesSDK(compiled *CompiledSDK, sdk SDK) bool {
	if compiled == nil || compiled.Program == nil {
		return false
	}
	want, err := normalizeSDK(sdk)
	if err != nil {
		return false
	}
	got, err := normalizeSDK(compiled.SDK)
	return err == nil && got.Version == want.Version && got.URL == want.URL
}

func encodeFinalToken(solved SolveOutput, challengeToken, deviceID, flow string) (string, error) {
	token := finalToken{
		P:    strings.TrimSpace(solved.FinalP),
		T:    strings.TrimSpace(solved.T),
		C:    strings.TrimSpace(challengeToken),
		ID:   strings.TrimSpace(deviceID),
		Flow: strings.TrimSpace(flow),
	}
	if token.P == "" || token.T == "" || token.C == "" || token.ID == "" || token.Flow == "" {
		return "", ErrInvalidRuntimeOutput
	}
	payload, err := json.Marshal(token)
	if err != nil {
		return "", ErrInvalidRuntimeOutput
	}
	if len(payload) > maxRuntimeOutputBytes {
		return "", ErrRuntimeOutputTooLarge
	}
	return string(payload), nil
}

func providerUnavailable(ctx context.Context, causes ...error) error {
	if ctx != nil {
		if err := ctx.Err(); err != nil {
			return errors.Join(openai.ErrSentinelUnavailable, err)
		}
	}
	for _, cause := range causes {
		switch {
		case errors.Is(cause, context.Canceled):
			return errors.Join(openai.ErrSentinelUnavailable, context.Canceled)
		case errors.Is(cause, context.DeadlineExceeded):
			return errors.Join(openai.ErrSentinelUnavailable, context.DeadlineExceeded)
		}
	}
	return openai.ErrSentinelUnavailable
}

var _ openai.SentinelProvider = (*Provider)(nil)
