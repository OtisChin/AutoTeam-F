package openai

import (
	"context"
	"errors"
	"net/http"
	"testing"
)

func TestUnavailableSentinelProviderFailsClosed(t *testing.T) {
	_, err := (UnavailableSentinelProvider{}).Token(
		context.Background(), http.DefaultClient, "device-1", "authorize_continue",
	)
	if !errors.Is(err, ErrSentinelUnavailable) {
		t.Fatalf("err=%v", err)
	}
}
