package openai

import (
	"context"
	"errors"
	"net/http"
	"testing"
)

func TestUnavailableSentinelProviderFailsClosed(t *testing.T) {
	result, err := (UnavailableSentinelProvider{}).Token(
		context.Background(), http.DefaultClient, mustOpenAIProfile(t, "chrome146"), "device-1", "authorize_continue",
	)
	if !errors.Is(err, ErrSentinelUnavailable) {
		t.Fatalf("err=%v", err)
	}
	if result != (SentinelResult{}) {
		t.Fatalf("result=%#v", result)
	}
}

func TestUnavailableSentinelProviderPreservesCanceledContext(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	result, err := (UnavailableSentinelProvider{}).Token(
		ctx, http.DefaultClient, mustOpenAIProfile(t, "chrome146"), "device-1", "authorize_continue",
	)
	if !errors.Is(err, ErrChallengeUnavailable) || !errors.Is(err, context.Canceled) {
		t.Fatalf("err=%v", err)
	}
	if result != (SentinelResult{}) {
		t.Fatalf("result=%#v", result)
	}
}
