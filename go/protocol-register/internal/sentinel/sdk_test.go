package sentinel

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestSDKURLValidation(t *testing.T) {
	valid := []struct {
		url     string
		version string
	}{
		{url: "https://sentinel.openai.com/sentinel/abc/sdk.js", version: "abc"},
		{url: "https://sentinel.openai.com:443/sentinel/version_456/sdk.js", version: "version_456"},
		{url: "https://SENTINEL.OPENAI.COM/sentinel/a.b-c_d/sdk.js", version: "a.b-c_d"},
		{url: "https://sentinel.openai.com/sentinel/" + strings.Repeat("a", 64) + "/sdk.js", version: strings.Repeat("a", 64)},
	}
	for _, tt := range valid {
		t.Run(tt.url, func(t *testing.T) {
			sdk, err := parseSDKURL(tt.url)
			if err != nil {
				t.Fatalf("parseSDKURL(%q) error=%v", tt.url, err)
			}
			if sdk.Version != tt.version || sdk.URL != tt.url {
				t.Fatalf("parseSDKURL(%q)=%#v", tt.url, sdk)
			}
		})
	}

	invalid := []string{
		"http://sentinel.openai.com/sentinel/abc/sdk.js",
		"https://sub.sentinel.openai.com/sentinel/abc/sdk.js",
		"https://sentinel.openai.com.evil.example/sentinel/abc/sdk.js",
		"https://user@sentinel.openai.com/sentinel/abc/sdk.js",
		"https://sentinel.openai.com:444/sentinel/abc/sdk.js",
		"https://sentinel.openai.com/sentinel/abc/sdk.js?cache=off",
		"https://sentinel.openai.com/sentinel/abc/sdk.js?",
		"https://sentinel.openai.com/sentinel/abc/sdk.js#fragment",
		"https://sentinel.openai.com/sentinel/abc%2Fdef/sdk.js",
		"https://sentinel.openai.com/sentinel/abc%5Cdef/sdk.js",
		"https://sentinel.openai.com/sentinel/abc/sdk.js/extra",
		"https://sentinel.openai.com/sentinel/ab/sdk.js",
		"https://sentinel.openai.com/sentinel/" + strings.Repeat("a", 65) + "/sdk.js",
		"https://sentinel.openai.com/sentinel/../sdk.js",
		"https://sentinel.openai.com//sentinel/abc/sdk.js",
		" https://sentinel.openai.com/sentinel/abc/sdk.js",
	}
	for _, raw := range invalid {
		t.Run(raw, func(t *testing.T) {
			if _, err := parseSDKURL(raw); !errors.Is(err, ErrInvalidSDKURL) {
				t.Fatalf("parseSDKURL(%q) error=%v", raw, err)
			}
		})
	}
}

func TestSDKVersionValidation(t *testing.T) {
	for _, version := range []string{"abc", "a.b-c_d", strings.Repeat("z", 64)} {
		if err := validateSDKVersion(version); err != nil {
			t.Fatalf("validateSDKVersion(%q) error=%v", version, err)
		}
	}
	for _, version := range []string{"", "ab", "../escape", "a/b", strings.Repeat("z", 65)} {
		if err := validateSDKVersion(version); !errors.Is(err, ErrInvalidSDKVersion) {
			t.Fatalf("validateSDKVersion(%q) error=%v", version, err)
		}
	}
}

func TestDiscoverSDKUsesFirstValidScriptFromBoundedFrame(t *testing.T) {
	frame, err := os.ReadFile(filepath.Join("testdata", "frame-current.html"))
	if err != nil {
		t.Fatal(err)
	}
	cfg := testConfig(t)
	var calls atomic.Int32
	client := &http.Client{Transport: roundTripFunc(func(req *http.Request) (*http.Response, error) {
		calls.Add(1)
		if req.Method != http.MethodGet || req.URL.String() != defaultFrameURL {
			t.Fatalf("discovery request=%s %s", req.Method, req.URL)
		}
		if req.Header.Get("Accept") != "text/html,application/xhtml+xml" || req.Header.Get("Referer") != "https://auth.openai.com/" {
			t.Fatalf("discovery headers=%v", req.Header)
		}
		return bytesResponse(http.StatusOK, frame), nil
	})}
	resolver := mustResolver(t, cfg)

	sdk, err := resolver.discoverSDK(context.Background(), client)
	if err != nil {
		t.Fatalf("discoverSDK() error=%v", err)
	}
	if sdk.Version != "20260830abcd" || sdk.URL != "https://sentinel.openai.com/sentinel/20260830abcd/sdk.js" || sdk.Source != SDKSourceDiscovery {
		t.Fatalf("discovered SDK=%#v", sdk)
	}
	if calls.Load() != 1 {
		t.Fatalf("discovery calls=%d", calls.Load())
	}
}

func TestDiscoverSDKRejectsOversizedFrame(t *testing.T) {
	cfg := testConfig(t)
	client := &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
		return bytesResponse(http.StatusOK, bytes.Repeat([]byte("x"), maxFrameBytes+1)), nil
	})}
	resolver := mustResolver(t, cfg)

	if _, err := resolver.discoverSDK(context.Background(), client); !errors.Is(err, ErrResponseTooLarge) {
		t.Fatalf("discoverSDK() error=%v", err)
	}
}

func TestDiscoverSDKDoesNotFollowRedirects(t *testing.T) {
	cfg := testConfig(t)
	var calls atomic.Int32
	client := &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
		calls.Add(1)
		response := bytesResponse(http.StatusFound, nil)
		response.Header.Set("Location", "https://attacker.example/frame.html")
		return response, nil
	})}
	resolver := mustResolver(t, cfg)

	if _, err := resolver.discoverSDK(context.Background(), client); !errors.Is(err, ErrUnexpectedHTTPStatus) {
		t.Fatalf("discoverSDK() error=%v", err)
	}
	if calls.Load() != 1 {
		t.Fatalf("redirect requests=%d", calls.Load())
	}
}

func TestCandidatesUseValidatedURLOverrideWithoutNetwork(t *testing.T) {
	cfg := testConfig(t)
	cfg.SDKURL = "https://sentinel.openai.com/sentinel/manual123/sdk.js"
	cfg.SDKVersion = "ignored456"
	client := noNetworkClient(t)
	resolver := mustResolver(t, cfg)

	candidates, err := resolver.Candidates(context.Background(), client)
	if err != nil {
		t.Fatalf("Candidates() error=%v", err)
	}
	want := []SDK{
		{Version: "manual123", URL: cfg.SDKURL, Source: SDKSourceEnvURL},
		builtinSDK(),
	}
	if !reflect.DeepEqual(candidates, want) {
		t.Fatalf("Candidates()=%#v, want %#v", candidates, want)
	}
}

func TestCandidatesUseValidatedVersionOverrideWithoutNetwork(t *testing.T) {
	cfg := testConfig(t)
	cfg.SDKVersion = "version_456"
	resolver := mustResolver(t, cfg)

	candidates, err := resolver.Candidates(context.Background(), noNetworkClient(t))
	if err != nil {
		t.Fatalf("Candidates() error=%v", err)
	}
	if got := candidateVersionSources(candidates); !reflect.DeepEqual(got, []string{"version_456/env_version", builtinVersion + "/builtin"}) {
		t.Fatalf("candidate order=%v", got)
	}
}

func TestCandidatesReuseFreshCacheWithoutDiscovery(t *testing.T) {
	now := time.Unix(20_000, 0)
	cfg := testConfig(t)
	cfg.SDKTTL = 2 * time.Hour
	cached := sdkForVersion("cached123", SDKSourceCache)
	writeCacheRecordFixture(t, cfg.CacheDir, latestCacheFile, cached, now.Add(-time.Hour))
	resolver := mustResolver(t, cfg, WithClock(func() time.Time { return now }))

	candidates, err := resolver.Candidates(context.Background(), noNetworkClient(t))
	if err != nil {
		t.Fatalf("Candidates() error=%v", err)
	}
	if got := candidateVersionSources(candidates); !reflect.DeepEqual(got, []string{"cached123/cache", builtinVersion + "/builtin"}) {
		t.Fatalf("candidate order=%v", got)
	}
}

func TestCandidatesRefreshStaleCacheFromDiscovery(t *testing.T) {
	now := time.Unix(20_000, 0)
	cfg := testConfig(t)
	cfg.SDKTTL = time.Minute
	writeCacheRecordFixture(t, cfg.CacheDir, latestCacheFile, sdkForVersion("stale123", SDKSourceCache), now.Add(-time.Hour))
	client := frameClient(t, `<script src="/sentinel/current456/sdk.js"></script>`)
	resolver := mustResolver(t, cfg, WithClock(func() time.Time { return now }))

	candidates, err := resolver.Candidates(context.Background(), client)
	if err != nil {
		t.Fatalf("Candidates() error=%v", err)
	}
	if got := candidateVersionSources(candidates); !reflect.DeepEqual(got, []string{"current456/discovery", builtinVersion + "/builtin"}) {
		t.Fatalf("candidate order=%v", got)
	}
	record := readCacheRecordFixture(t, filepath.Join(cfg.CacheDir, latestCacheFile))
	if record.Version != "current456" || record.SDKURL != sdkForVersion("current456", "").URL || record.ResolvedAt != float64(now.Unix()) {
		t.Fatalf("latest cache=%#v", record)
	}
}

func TestCandidatesFallBackToStaleCacheWhenDiscoveryFails(t *testing.T) {
	now := time.Unix(20_000, 0)
	cfg := testConfig(t)
	cfg.SDKTTL = time.Minute
	writeCacheRecordFixture(t, cfg.CacheDir, latestCacheFile, sdkForVersion("stale123", SDKSourceCache), now.Add(-time.Hour))
	client := &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
		return bytesResponse(http.StatusServiceUnavailable, []byte("private upstream body")), nil
	})}
	resolver := mustResolver(t, cfg, WithClock(func() time.Time { return now }))

	candidates, err := resolver.Candidates(context.Background(), client)
	if err != nil {
		t.Fatalf("Candidates() error=%v", err)
	}
	if got := candidateVersionSources(candidates); !reflect.DeepEqual(got, []string{"stale123/stale_cache", builtinVersion + "/builtin"}) {
		t.Fatalf("candidate order=%v", got)
	}
}

func TestCandidatesTTLZeroAlwaysDiscovers(t *testing.T) {
	now := time.Unix(20_000, 0)
	cfg := testConfig(t)
	cfg.SDKTTL = 0
	writeCacheRecordFixture(t, cfg.CacheDir, latestCacheFile, sdkForVersion("cached123", SDKSourceCache), now)
	resolver := mustResolver(t, cfg, WithClock(func() time.Time { return now }))

	candidates, err := resolver.Candidates(context.Background(), frameClient(t, `<script src="/sentinel/current456/sdk.js"></script>`))
	if err != nil {
		t.Fatalf("Candidates() error=%v", err)
	}
	if candidates[0].Version != "current456" || candidates[0].Source != SDKSourceDiscovery {
		t.Fatalf("primary candidate=%#v", candidates[0])
	}
}

func TestCandidatesOrderCurrentLastGoodBuiltin(t *testing.T) {
	now := time.Unix(20_000, 0)
	cfg := testConfig(t)
	cfg.SDKVersion = "current456"
	writeCacheRecordFixture(t, cfg.CacheDir, lastGoodCacheFile, sdkForVersion("known789", SDKSourceLastGood), now.Add(-time.Hour))
	resolver := mustResolver(t, cfg, WithClock(func() time.Time { return now }))

	candidates, err := resolver.Candidates(context.Background(), noNetworkClient(t))
	if err != nil {
		t.Fatalf("Candidates() error=%v", err)
	}
	if got := candidateVersionSources(candidates); !reflect.DeepEqual(got, []string{"current456/env_version", "known789/last_good", builtinVersion + "/builtin"}) {
		t.Fatalf("candidate order=%v", got)
	}
}

func TestCandidatesDeduplicateByVersionAndURL(t *testing.T) {
	now := time.Unix(20_000, 0)
	cfg := testConfig(t)
	cfg.SDKVersion = builtinVersion
	writeCacheRecordFixture(t, cfg.CacheDir, lastGoodCacheFile, builtinSDK(), now.Add(-time.Hour))
	resolver := mustResolver(t, cfg, WithClock(func() time.Time { return now }))

	candidates, err := resolver.Candidates(context.Background(), noNetworkClient(t))
	if err != nil {
		t.Fatalf("Candidates() error=%v", err)
	}
	if len(candidates) != 1 || candidates[0].Source != SDKSourceEnvVersion {
		t.Fatalf("deduplicated candidates=%#v", candidates)
	}
}

func TestDownloadRejectsOversizedSDKSource(t *testing.T) {
	cfg := testConfig(t)
	client := &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
		return bytesResponse(http.StatusOK, bytes.Repeat([]byte("x"), maxSDKBytes+1)), nil
	})}
	resolver := mustResolver(t, cfg)

	if _, err := resolver.Source(context.Background(), client, sdkForVersion("large123", "")); !errors.Is(err, ErrResponseTooLarge) {
		t.Fatalf("Source() error=%v", err)
	}
}

func TestDownloadRejectsEmptySDKSource(t *testing.T) {
	cfg := testConfig(t)
	client := &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
		return bytesResponse(http.StatusOK, []byte(" \r\n\t")), nil
	})}
	resolver := mustResolver(t, cfg)

	if _, err := resolver.Source(context.Background(), client, sdkForVersion("empty123", "")); !errors.Is(err, ErrEmptySDKSource) {
		t.Fatalf("Source() error=%v", err)
	}
}

func TestDownloadRejectsRedirectAndSanitizesHTTPBody(t *testing.T) {
	cfg := testConfig(t)
	secret := "DO_NOT_EXPOSE_RESPONSE_BODY"
	var calls atomic.Int32
	client := &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
		calls.Add(1)
		response := bytesResponse(http.StatusFound, []byte(secret))
		response.Header.Set("Location", "https://attacker.example/sdk.js")
		return response, nil
	})}
	resolver := mustResolver(t, cfg)

	_, err := resolver.Source(context.Background(), client, sdkForVersion("safe123", ""))
	if !errors.Is(err, ErrUnexpectedHTTPStatus) || strings.Contains(fmt.Sprint(err), secret) {
		t.Fatalf("Source() error=%v", err)
	}
	if calls.Load() != 1 {
		t.Fatalf("download requests=%d", calls.Load())
	}
}

func TestDownloadSanitizesTransportErrors(t *testing.T) {
	cfg := testConfig(t)
	const secret = "proxy-user:proxy-password@private-proxy.example"
	client := &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
		return nil, errors.New(secret)
	})}
	resolver := mustResolver(t, cfg)

	_, err := resolver.Source(context.Background(), client, sdkForVersion("safe123", ""))
	if !errors.Is(err, ErrHTTPTransport) || strings.Contains(fmt.Sprint(err), secret) {
		t.Fatalf("Source() error=%v", err)
	}
}

func TestDownloadRejectsMismatchedSDKVersionAndURLBeforeNetwork(t *testing.T) {
	cfg := testConfig(t)
	resolver := mustResolver(t, cfg)
	sdk := SDK{Version: "first123", URL: sdkForVersion("second456", "").URL}

	if _, err := resolver.Source(context.Background(), noNetworkClient(t), sdk); !errors.Is(err, ErrInvalidSDKURL) {
		t.Fatalf("Source() error=%v", err)
	}
}

func TestDownloadHonorsCanceledContextBeforeReadingCache(t *testing.T) {
	cfg := testConfig(t)
	sdk := sdkForVersion("cached123", "")
	if err := os.WriteFile(filepath.Join(cfg.CacheDir, sdk.Version+".js"), []byte("globalThis.cached = true;"), 0o600); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	resolver := mustResolver(t, cfg)

	if _, err := resolver.Source(ctx, noNetworkClient(t), sdk); !errors.Is(err, context.Canceled) {
		t.Fatalf("Source() error=%v", err)
	}
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(req *http.Request) (*http.Response, error) {
	return f(req)
}

func bytesResponse(status int, body []byte) *http.Response {
	return &http.Response{
		StatusCode:    status,
		Status:        fmt.Sprintf("%d %s", status, http.StatusText(status)),
		Header:        make(http.Header),
		Body:          io.NopCloser(bytes.NewReader(body)),
		ContentLength: int64(len(body)),
	}
}

func noNetworkClient(t *testing.T) *http.Client {
	t.Helper()
	return &http.Client{Transport: roundTripFunc(func(req *http.Request) (*http.Response, error) {
		t.Fatalf("unexpected network request: %s %s", req.Method, req.URL)
		return nil, errors.New("unexpected network request")
	})}
}

func frameClient(t *testing.T, frame string) *http.Client {
	t.Helper()
	return &http.Client{Transport: roundTripFunc(func(req *http.Request) (*http.Response, error) {
		if req.URL.String() != defaultFrameURL {
			t.Fatalf("unexpected frame URL=%s", req.URL)
		}
		return bytesResponse(http.StatusOK, []byte(frame)), nil
	})}
}

func testConfig(t *testing.T) Config {
	t.Helper()
	return Config{
		CacheDir:       t.TempDir(),
		SDKTTL:         6 * time.Hour,
		HTTPTimeout:    10 * time.Second,
		VMTimeout:      45 * time.Second,
		FrameURL:       defaultFrameURL,
		RequestURL:     defaultRequestURL,
		BuiltinVersion: builtinVersion,
	}
}

func mustResolver(t *testing.T, cfg Config, options ...ResolverOption) *Resolver {
	t.Helper()
	resolver, err := NewResolver(cfg, options...)
	if err != nil {
		t.Fatalf("NewResolver() error=%v", err)
	}
	return resolver
}

func sdkForVersion(version, source string) SDK {
	return SDK{
		Version: version,
		URL:     "https://sentinel.openai.com/sentinel/" + version + "/sdk.js",
		Source:  source,
	}
}

func builtinSDK() SDK {
	return sdkForVersion(builtinVersion, SDKSourceBuiltin)
}

func candidateVersionSources(candidates []SDK) []string {
	got := make([]string, len(candidates))
	for index, sdk := range candidates {
		got[index] = sdk.Version + "/" + sdk.Source
	}
	return got
}

type cacheRecordFixture struct {
	Version    string  `json:"version"`
	SDKURL     string  `json:"sdk_url"`
	ResolvedAt float64 `json:"resolved_at"`
}

func writeCacheRecordFixture(t *testing.T, dir, name string, sdk SDK, resolvedAt time.Time) {
	t.Helper()
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	payload, err := json.Marshal(cacheRecordFixture{
		Version:    sdk.Version,
		SDKURL:     sdk.URL,
		ResolvedAt: float64(resolvedAt.Unix()),
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, name), payload, 0o600); err != nil {
		t.Fatal(err)
	}
}

func readCacheRecordFixture(t *testing.T, path string) cacheRecordFixture {
	t.Helper()
	payload, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var record cacheRecordFixture
	if err := json.Unmarshal(payload, &record); err != nil {
		t.Fatalf("decode %s: %v; payload=%q", path, err, payload)
	}
	return record
}
