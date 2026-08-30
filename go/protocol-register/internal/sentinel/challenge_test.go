package sentinel

import (
	"context"
	"errors"
	"io"
	"net/http"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"autoteam-f/protocol-register/internal/fingerprint"
)

func TestChallengeTransportPostsExactBodyAndSelectedProfileHeaders(t *testing.T) {
	profile := runtimeTestProfile(t)
	sdk := sdkForVersion("challenge123", SDKSourceDiscovery)
	var calls atomic.Int32
	client := &http.Client{Transport: roundTripFunc(func(req *http.Request) (*http.Response, error) {
		calls.Add(1)
		if req.Method != http.MethodPost || req.URL.String() != defaultRequestURL {
			t.Fatalf("request=%s %s", req.Method, req.URL)
		}
		body, err := io.ReadAll(req.Body)
		if err != nil {
			t.Fatal(err)
		}
		if got, want := string(body), `{"p":"request-p","id":"did-123","flow":"authorize_continue"}`; got != want {
			t.Fatalf("body=%q, want %q", got, want)
		}
		headers := map[string]string{
			"Content-Type":       "text/plain;charset=UTF-8",
			"Accept":             "*/*",
			"Accept-Encoding":    "gzip, deflate, br, zstd",
			"Origin":             "https://sentinel.openai.com",
			"Referer":            defaultFrameURL + "?sv=" + sdk.Version,
			"User-Agent":         profile.UserAgent,
			"Sec-CH-UA":          profile.SecCHUA,
			"Sec-CH-UA-Mobile":   profile.SecCHUAMobile,
			"Sec-CH-UA-Platform": profile.SecCHUAPlatform,
			"Accept-Language":    profile.AcceptLanguage,
			"Sec-Fetch-Dest":     "empty",
			"Sec-Fetch-Mode":     "cors",
			"Sec-Fetch-Site":     "same-origin",
			"Priority":           "u=1, i",
		}
		for name, want := range headers {
			if got := req.Header.Get(name); got != want {
				t.Fatalf("header %s=%q, want %q", name, got, want)
			}
		}
		return bytesResponse(http.StatusOK, []byte(`{"token":"  challenge-token  ","turnstile":{"dx":"dx"}}`)), nil
	})}

	transport := mustChallengeTransport(t)
	result, err := transport.Fetch(
		context.Background(), client, profile, sdk, "did-123", "authorize_continue", "request-p",
	)
	if err != nil {
		t.Fatalf("Fetch() error=%v", err)
	}
	if calls.Load() != 1 || result.Token != "challenge-token" {
		t.Fatalf("calls=%d result=%#v", calls.Load(), result)
	}
	if result.Payload["token"] != result.Token {
		t.Fatalf("payload token=%#v normalized token=%q", result.Payload["token"], result.Token)
	}
	turnstile, ok := result.Payload["turnstile"].(map[string]any)
	if !ok || turnstile["dx"] != "dx" {
		t.Fatalf("challenge payload=%#v", result.Payload)
	}
}

func TestChallengeTransportHonorsCanceledContextAndTimeout(t *testing.T) {
	profile := runtimeTestProfile(t)
	sdk := sdkForVersion("challenge123", SDKSourceDiscovery)
	t.Run("already canceled", func(t *testing.T) {
		var calls atomic.Int32
		client := &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
			calls.Add(1)
			return nil, errors.New("unexpected request")
		})}
		ctx, cancel := context.WithCancel(context.Background())
		cancel()
		_, err := mustChallengeTransport(t).Fetch(ctx, client, profile, sdk, "did", "flow", "request")
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("Fetch() error=%v", err)
		}
		if calls.Load() != 0 {
			t.Fatalf("calls=%d", calls.Load())
		}
	})

	t.Run("transport timeout", func(t *testing.T) {
		var calls atomic.Int32
		client := &http.Client{Transport: roundTripFunc(func(req *http.Request) (*http.Response, error) {
			calls.Add(1)
			<-req.Context().Done()
			return nil, req.Context().Err()
		})}
		transport := mustChallengeTransport(t)
		transport.timeout = 20 * time.Millisecond
		_, err := transport.Fetch(context.Background(), client, profile, sdk, "did", "flow", "request")
		if !errors.Is(err, context.DeadlineExceeded) {
			t.Fatalf("Fetch() error=%v", err)
		}
		if calls.Load() != 1 {
			t.Fatalf("calls=%d", calls.Load())
		}
	})
}

func TestChallengeTransportRejectsRedirectsOversizedAndMalformedResponsesWithoutLeaks(t *testing.T) {
	tests := []struct {
		name      string
		response  func() *http.Response
		transport error
		secret    string
	}{
		{
			name: "redirect",
			response: func() *http.Response {
				response := bytesResponse(http.StatusFound, []byte("private redirect body"))
				response.Header.Set("Location", "https://attacker.example/private")
				return response
			},
			transport: ErrUnexpectedHTTPStatus,
			secret:    "private redirect body",
		},
		{
			name: "declared oversized",
			response: func() *http.Response {
				response := bytesResponse(http.StatusOK, []byte(`{"token":"small"}`))
				response.ContentLength = maxChallengeBytes + 1
				return response
			},
			transport: ErrResponseTooLarge,
		},
		{
			name:      "streamed oversized",
			response:  func() *http.Response { return bytesResponse(http.StatusOK, make([]byte, maxChallengeBytes+1)) },
			transport: ErrResponseTooLarge,
		},
		{
			name:      "JSON array",
			response:  func() *http.Response { return bytesResponse(http.StatusOK, []byte(`["private-array"]`)) },
			transport: ErrInvalidChallengeResponse,
			secret:    "private-array",
		},
		{
			name:      "malformed JSON",
			response:  func() *http.Response { return bytesResponse(http.StatusOK, []byte(`{"token":"private-malformed"`)) },
			transport: ErrInvalidChallengeResponse,
			secret:    "private-malformed",
		},
		{
			name:      "trailing JSON",
			response:  func() *http.Response { return bytesResponse(http.StatusOK, []byte(`{"token":"one"}{"private":"two"}`)) },
			transport: ErrInvalidChallengeResponse,
			secret:    "private",
		},
		{
			name:      "missing token",
			response:  func() *http.Response { return bytesResponse(http.StatusOK, []byte(`{"private":"missing"}`)) },
			transport: ErrInvalidChallengeResponse,
			secret:    "missing",
		},
		{
			name:      "empty token",
			response:  func() *http.Response { return bytesResponse(http.StatusOK, []byte(`{"token":"  "}`)) },
			transport: ErrInvalidChallengeResponse,
		},
		{
			name:      "non-string token",
			response:  func() *http.Response { return bytesResponse(http.StatusOK, []byte(`{"token":12345}`)) },
			transport: ErrInvalidChallengeResponse,
			secret:    "12345",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var calls atomic.Int32
			client := &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
				calls.Add(1)
				return tt.response(), nil
			})}
			_, err := mustChallengeTransport(t).Fetch(
				context.Background(), client, runtimeTestProfile(t), sdkForVersion("challenge123", ""), "did", "flow", "request",
			)
			if !errors.Is(err, tt.transport) {
				t.Fatalf("Fetch() error=%v", err)
			}
			if tt.secret != "" && strings.Contains(err.Error(), tt.secret) {
				t.Fatalf("Fetch() leaked response data: %v", err)
			}
			if tt.name == "redirect" && !strings.Contains(err.Error(), "302") {
				t.Fatalf("Fetch() omitted safe HTTP status code: %v", err)
			}
			if calls.Load() != 1 {
				t.Fatalf("calls=%d", calls.Load())
			}
		})
	}
}

func TestChallengeTransportSanitizesTransportAndReadErrors(t *testing.T) {
	tests := []struct {
		name   string
		client *http.Client
		want   error
	}{
		{
			name: "transport",
			client: &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
				return nil, errors.New("private transport credential")
			})},
			want: ErrHTTPTransport,
		},
		{
			name: "body read",
			client: &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
				return &http.Response{
					StatusCode: http.StatusOK,
					Header:     make(http.Header),
					Body:       errorReadCloser{err: errors.New("private body read credential")},
				}, nil
			})},
			want: ErrInvalidChallengeResponse,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, err := mustChallengeTransport(t).Fetch(
				context.Background(), tt.client, runtimeTestProfile(t), sdkForVersion("challenge123", ""), "did", "flow", "request",
			)
			if !errors.Is(err, tt.want) {
				t.Fatalf("Fetch() error=%v", err)
			}
			if strings.Contains(err.Error(), "private") || strings.Contains(err.Error(), "credential") {
				t.Fatalf("Fetch() leaked private error: %v", err)
			}
		})
	}
}

func TestChallengeTransportRejectsInvalidInputs(t *testing.T) {
	transport := mustChallengeTransport(t)
	profile := runtimeTestProfile(t)
	sdk := sdkForVersion("challenge123", "")
	tests := []struct {
		name        string
		ctx         context.Context
		client      *http.Client
		profileName string
		sdk         SDK
		device      string
		flow        string
		request     string
		want        error
	}{
		{name: "nil context", client: noNetworkClient(t), profileName: profile.Name, sdk: sdk, device: "did", flow: "flow", request: "request", want: ErrInvalidChallengeInput},
		{name: "nil client", ctx: context.Background(), profileName: profile.Name, sdk: sdk, device: "did", flow: "flow", request: "request", want: ErrNilHTTPClient},
		{name: "invalid profile", ctx: context.Background(), client: noNetworkClient(t), sdk: sdk, device: "did", flow: "flow", request: "request", want: ErrInvalidChallengeInput},
		{name: "invalid SDK", ctx: context.Background(), client: noNetworkClient(t), profileName: profile.Name, sdk: SDK{}, device: "did", flow: "flow", request: "request", want: ErrInvalidChallengeInput},
		{name: "empty device", ctx: context.Background(), client: noNetworkClient(t), profileName: profile.Name, sdk: sdk, flow: "flow", request: "request", want: ErrInvalidChallengeInput},
		{name: "empty flow", ctx: context.Background(), client: noNetworkClient(t), profileName: profile.Name, sdk: sdk, device: "did", request: "request", want: ErrInvalidChallengeInput},
		{name: "empty request", ctx: context.Background(), client: noNetworkClient(t), profileName: profile.Name, sdk: sdk, device: "did", flow: "flow", want: ErrInvalidChallengeInput},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			selected := profile
			if tt.profileName == "" {
				selected = selectedZeroProfile()
			}
			_, err := transport.Fetch(tt.ctx, tt.client, selected, tt.sdk, tt.device, tt.flow, tt.request)
			if !errors.Is(err, tt.want) {
				t.Fatalf("Fetch() error=%v", err)
			}
		})
	}
}

func mustChallengeTransport(t *testing.T) challengeTransport {
	t.Helper()
	transport, err := newChallengeTransport(testConfig(t))
	if err != nil {
		t.Fatalf("newChallengeTransport() error=%v", err)
	}
	return transport
}

func selectedZeroProfile() fingerprint.Profile {
	return fingerprint.Profile{}
}

type errorReadCloser struct {
	err error
}

func (r errorReadCloser) Read([]byte) (int, error) { return 0, r.err }
func (errorReadCloser) Close() error               { return nil }
