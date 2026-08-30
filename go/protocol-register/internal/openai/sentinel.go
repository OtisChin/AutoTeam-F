package openai

import (
	"context"
	"errors"
	"fmt"
	"net/http"

	"autoteam-f/protocol-register/internal/fingerprint"
)

var (
	ErrChallengeUnavailable = errors.New("challenge unavailable")
	ErrSentinelUnavailable  = fmt.Errorf("%w: sentinel provider unavailable", ErrChallengeUnavailable)
)

type SentinelProvider interface {
	Token(ctx context.Context, httpClient *http.Client, profile fingerprint.Profile, deviceID, flow string) (SentinelResult, error)
}

type SentinelResult struct {
	Token      string
	SDKVersion string
}

type UnavailableSentinelProvider struct{}

func (UnavailableSentinelProvider) Token(context.Context, *http.Client, fingerprint.Profile, string, string) (SentinelResult, error) {
	return SentinelResult{}, ErrSentinelUnavailable
}
