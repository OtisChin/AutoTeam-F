package httpclient

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/cookiejar"
	"net/http/httptest"
	"net/url"
	"reflect"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"autoteam-f/protocol-register/internal/fingerprint"

	fhttp "github.com/bogdanfinn/fhttp"
)

type captureDoer struct {
	request    *fhttp.Request
	response   *fhttp.Response
	err        error
	mutate     func(*fhttp.Request)
	closeCalls int
}

func (d *captureDoer) Do(req *fhttp.Request) (*fhttp.Response, error) {
	d.request = req
	if d.mutate != nil {
		d.mutate(req)
	}
	return d.response, d.err
}

func (d *captureDoer) CloseIdleConnections() {
	d.closeCalls++
}

func TestRoundTripConvertsRequestAndResponse(t *testing.T) {
	responseBody := io.NopCloser(strings.NewReader("ok"))
	doer := &captureDoer{
		response: &fhttp.Response{
			Status:           "201 Created",
			StatusCode:       http.StatusCreated,
			Proto:            "HTTP/2.0",
			ProtoMajor:       2,
			Header:           fhttp.Header{"Set-Cookie": {"session=one; Path=/"}, fhttp.HeaderOrderKey: {"not-a-response-header"}, fhttp.PHeaderOrderKey: {"not-a-response-header"}},
			Body:             responseBody,
			ContentLength:    2,
			TransferEncoding: []string{"identity"},
			Close:            true,
			Trailer:          fhttp.Header{"X-Trailer": {"done"}},
		},
		mutate: func(req *fhttp.Request) {
			req.Header.Set("X-Original", "inner-mutated")
		},
	}
	profile := mustProfile(t, "chrome146")
	transport := newRoundTripper(doer, profile)

	ctx := context.WithValue(context.Background(), struct{}{}, "request-context")
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, "https://example.test/path?one=two", strings.NewReader("body"))
	if err != nil {
		t.Fatal(err)
	}
	req.Host = "override.example.test"
	req.TransferEncoding = []string{"chunked"}
	req.Header["X-Multi"] = []string{"one", "two"}
	req.Header.Set("X-Original", "outer")
	req.Trailer = http.Header{"X-Request-Trailer": {"later"}}

	resp, err := transport.RoundTrip(req)
	if err != nil {
		t.Fatalf("RoundTrip() error=%v", err)
	}
	if resp.StatusCode != http.StatusCreated || resp.Status != "201 Created" || resp.Request != req {
		t.Fatalf("response=%#v", resp)
	}
	if resp.Proto != "HTTP/2.0" || resp.ProtoMajor != 2 || resp.ContentLength != 2 {
		t.Fatalf("response protocol/content length=%#v", resp)
	}
	if resp.Body != responseBody || !resp.Close || !reflect.DeepEqual(resp.TransferEncoding, []string{"identity"}) {
		t.Fatalf("response stream metadata=%#v", resp)
	}
	if got := resp.Header.Values("Set-Cookie"); !reflect.DeepEqual(got, []string{"session=one; Path=/"}) {
		t.Fatalf("response cookies=%v", got)
	}
	for name := range resp.Header {
		if strings.EqualFold(name, fhttp.HeaderOrderKey) || strings.EqualFold(name, fhttp.PHeaderOrderKey) {
			t.Fatalf("wire-only order header %q leaked to response: %v", name, resp.Header)
		}
	}
	if got := resp.Trailer.Values("X-Trailer"); !reflect.DeepEqual(got, []string{"done"}) {
		t.Fatalf("response trailer=%v", got)
	}

	converted := doer.request
	if converted == nil {
		t.Fatal("inner request was not captured")
	}
	if converted.Context() != req.Context() || converted.Method != req.Method || converted.URL.String() != req.URL.String() {
		t.Fatalf("converted request=%#v", converted)
	}
	if converted.Host != req.Host || converted.ContentLength != req.ContentLength || !reflect.DeepEqual(converted.TransferEncoding, req.TransferEncoding) {
		t.Fatalf("converted request metadata=%#v", converted)
	}
	if got := converted.Header.Values("X-Multi"); !reflect.DeepEqual(got, []string{"one", "two"}) {
		t.Fatalf("converted request headers=%v", converted.Header)
	}
	if req.Header.Get("X-Original") != "outer" {
		t.Fatalf("inner header mutation reached outer request: %v", req.Header)
	}
	if got := converted.Trailer.Values("X-Request-Trailer"); !reflect.DeepEqual(got, []string{"later"}) {
		t.Fatalf("converted request trailer=%v", got)
	}
	body, err := io.ReadAll(converted.Body)
	if err != nil || string(body) != "body" {
		t.Fatalf("converted body=%q error=%v", body, err)
	}
	if got := converted.Header[fhttp.HeaderOrderKey]; !reflect.DeepEqual(got, profile.HeaderOrder) {
		t.Fatalf("header order=%v want=%v", got, profile.HeaderOrder)
	}
	if got := converted.Header[fhttp.PHeaderOrderKey]; !reflect.DeepEqual(got, profile.PseudoHeaderOrder) {
		t.Fatalf("pseudo-header order=%v want=%v", got, profile.PseudoHeaderOrder)
	}
}

func TestRoundTripReturnsDoerErrorWithoutReadingBody(t *testing.T) {
	want := errors.New("inner transport failed")
	body := &countingReadCloser{}
	doer := &captureDoer{err: want}
	transport := newRoundTripper(doer, mustProfile(t, "chrome144"))
	req, err := http.NewRequest(http.MethodPost, "https://example.test/", body)
	if err != nil {
		t.Fatal(err)
	}

	if _, err := transport.RoundTrip(req); !errors.Is(err, want) {
		t.Fatalf("RoundTrip() error=%v", err)
	}
	if body.reads.Load() != 0 {
		t.Fatalf("adapter read request body %d times", body.reads.Load())
	}
}

func TestRoundTripPreservesStreamingTrailerUpdates(t *testing.T) {
	requestTrailer := http.Header{"X-Request-Trailer": nil}
	responseTrailer := fhttp.Header{"X-Response-Trailer": nil}
	requestTrailerSeen := ""
	doer := &captureDoer{
		response: &fhttp.Response{
			Status:     "200 OK",
			StatusCode: http.StatusOK,
			Header:     make(fhttp.Header),
			Body:       http.NoBody,
			Trailer:    responseTrailer,
		},
		mutate: func(req *fhttp.Request) {
			requestTrailer.Set("X-Request-Trailer", "sent-late")
			requestTrailerSeen = req.Trailer.Get("X-Request-Trailer")
		},
	}
	transport := newRoundTripper(doer, mustProfile(t, "chrome146"))
	req, err := http.NewRequest(http.MethodPost, "https://example.test/trailers", http.NoBody)
	if err != nil {
		t.Fatal(err)
	}
	req.Trailer = requestTrailer

	resp, err := transport.RoundTrip(req)
	if err != nil {
		t.Fatalf("RoundTrip() error=%v", err)
	}
	if requestTrailerSeen != "sent-late" {
		t.Fatalf("inner request trailer update=%q", requestTrailerSeen)
	}
	responseTrailer.Set("X-Response-Trailer", "received-late")
	if got := resp.Trailer.Get("X-Response-Trailer"); got != "received-late" {
		t.Fatalf("outer response trailer update=%q", got)
	}
}

func TestRoundTripPropagatesCancellation(t *testing.T) {
	doer := &blockingDoer{started: make(chan *fhttp.Request, 1)}
	transport := newRoundTripper(doer, mustProfile(t, "chrome150"))
	ctx, cancel := context.WithCancel(context.Background())
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, "https://example.test/wait", nil)
	if err != nil {
		t.Fatal(err)
	}
	result := make(chan error, 1)
	go func() {
		_, err := transport.RoundTrip(req)
		result <- err
	}()

	select {
	case inner := <-doer.started:
		if inner.Context() != req.Context() {
			t.Fatal("inner request did not preserve the outer context")
		}
	case <-time.After(time.Second):
		t.Fatal("inner request did not start")
	}
	cancel()
	select {
	case err := <-result:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("RoundTrip() error=%v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("RoundTrip did not return after cancellation")
	}
}

func TestOuterClientOwnsCookiesAndRedirects(t *testing.T) {
	var calls atomic.Int32
	var cookieSeen atomic.Bool
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		switch r.URL.Path {
		case "/start":
			http.SetCookie(w, &http.Cookie{Name: "session", Value: "one", Path: "/"})
			http.Redirect(w, r, "/finish", http.StatusFound)
		case "/finish":
			cookie, err := r.Cookie("session")
			cookieSeen.Store(err == nil && cookie.Value == "one")
			_, _ = io.WriteString(w, "done")
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()

	inner := &fhttp.Client{CheckRedirect: func(*fhttp.Request, []*fhttp.Request) error {
		return fhttp.ErrUseLastResponse
	}}
	jar, err := cookiejar.New(nil)
	if err != nil {
		t.Fatal(err)
	}
	outer := &http.Client{
		Transport: newRoundTripper(inner, mustProfile(t, "chrome146")),
		Jar:       jar,
		Timeout:   2 * time.Second,
	}
	resp, err := outer.Get(server.URL + "/start")
	if err != nil {
		t.Fatalf("outer.Get() error=%v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK || resp.Request.URL.Path != "/finish" {
		t.Fatalf("response=%#v", resp)
	}
	if calls.Load() != 2 || !cookieSeen.Load() {
		t.Fatalf("calls=%d cookieSeen=%t", calls.Load(), cookieSeen.Load())
	}
}

func TestRoundTripperForwardsCloseIdleConnections(t *testing.T) {
	doer := &captureDoer{}
	var transport http.RoundTripper = newRoundTripper(doer, mustProfile(t, "chrome144"))
	closer, ok := transport.(interface{ CloseIdleConnections() })
	if !ok {
		t.Fatal("transport does not expose CloseIdleConnections")
	}
	closer.CloseIdleConnections()
	if doer.closeCalls != 1 {
		t.Fatalf("close calls=%d", doer.closeCalls)
	}
}

type countingReadCloser struct {
	reads atomic.Int32
}

func (b *countingReadCloser) Read([]byte) (int, error) {
	b.reads.Add(1)
	return 0, io.EOF
}

func (*countingReadCloser) Close() error { return nil }

type blockingDoer struct {
	started chan *fhttp.Request
}

func (d *blockingDoer) Do(req *fhttp.Request) (*fhttp.Response, error) {
	d.started <- req
	<-req.Context().Done()
	return nil, req.Context().Err()
}

func mustProfile(t *testing.T, name string) fingerprint.Profile {
	t.Helper()
	profile, ok := fingerprint.Lookup(name)
	if !ok {
		t.Fatalf("profile %q was not found", name)
	}
	return profile
}

func mustURL(t *testing.T, raw string) *url.URL {
	t.Helper()
	parsed, err := url.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	return parsed
}
