package openai

import (
	"context"
	"errors"
	"fmt"
	"net/http"
)

var (
	ErrChallengeUnavailable = errors.New("challenge unavailable")
	ErrSentinelUnavailable  = fmt.Errorf("%w: sentinel provider unavailable", ErrChallengeUnavailable)
)

type SentinelProvider interface {
	Token(ctx context.Context, httpClient *http.Client, deviceID, flow string) (string, error)
}

type UnavailableSentinelProvider struct{}

func (UnavailableSentinelProvider) Token(context.Context, *http.Client, string, string) (string, error) {
	return "", ErrSentinelUnavailable
}
