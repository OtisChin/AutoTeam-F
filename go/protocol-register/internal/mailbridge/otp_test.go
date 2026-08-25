package mailbridge_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"autoteam-f/protocol-register/internal/mailbridge"
)

func TestExtractOTPFromJSONAndHTML(t *testing.T) {
	for _, input := range [][]byte{
		[]byte(`{"ok":true,"code":"013555"}`),
		[]byte(`{"mail":{"content":"Use 246810 to continue"}}`),
		[]byte(`<html>Your OpenAI verification code is <b>135790</b></html>`),
	} {
		if got := mailbridge.ExtractOTP(input); got == "" {
			t.Fatalf("missing code from %s", input)
		}
	}
}

func TestWaitForOTPPollsUntilCode(t *testing.T) {
	calls := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		if calls < 2 {
			w.WriteHeader(http.StatusNotFound)
			_, _ = w.Write([]byte(`{"ok":false}`))
			return
		}
		_, _ = w.Write([]byte(`{"code":"112233"}`))
	}))
	defer srv.Close()
	client := mailbridge.NewClient(srv.Client(), 10*time.Millisecond)
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	code, err := client.WaitForOTP(ctx, srv.URL)
	if err != nil || code != "112233" {
		t.Fatalf("code=%q err=%v", code, err)
	}
}
