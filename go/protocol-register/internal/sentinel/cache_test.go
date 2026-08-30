package sentinel

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"reflect"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestCacheWritesLatestLastGoodAndVersionedSourceAtomically(t *testing.T) {
	now := time.Unix(20_000, 0)
	cfg := testConfig(t)
	const source = "globalThis.__sentinelFixture = true;"
	var frameCalls atomic.Int32
	var sourceCalls atomic.Int32
	client := &http.Client{Transport: roundTripFunc(func(req *http.Request) (*http.Response, error) {
		switch req.URL.String() {
		case defaultFrameURL:
			frameCalls.Add(1)
			return bytesResponse(http.StatusOK, []byte(`<script src="/sentinel/current456/sdk.js"></script>`)), nil
		case "https://sentinel.openai.com/sentinel/current456/sdk.js":
			sourceCalls.Add(1)
			return bytesResponse(http.StatusOK, []byte(source)), nil
		default:
			t.Fatalf("unexpected URL=%s", req.URL)
			return nil, errors.New("unexpected URL")
		}
	})}
	resolver := mustResolver(t, cfg, WithClock(func() time.Time { return now }))

	candidates, err := resolver.Candidates(context.Background(), client)
	if err != nil {
		t.Fatalf("Candidates() error=%v", err)
	}
	gotSource, err := resolver.Source(context.Background(), client, candidates[0])
	if err != nil {
		t.Fatalf("Source() error=%v", err)
	}
	if err := resolver.MarkGood(candidates[0]); err != nil {
		t.Fatalf("MarkGood() error=%v", err)
	}
	if string(gotSource) != source || frameCalls.Load() != 1 || sourceCalls.Load() != 1 {
		t.Fatalf("source=%q frameCalls=%d sourceCalls=%d", gotSource, frameCalls.Load(), sourceCalls.Load())
	}

	wantRecord := cacheRecordFixture{
		Version:    "current456",
		SDKURL:     "https://sentinel.openai.com/sentinel/current456/sdk.js",
		ResolvedAt: float64(now.Unix()),
	}
	for _, name := range []string{latestCacheFile, lastGoodCacheFile} {
		if got := readCacheRecordFixture(t, filepath.Join(cfg.CacheDir, name)); !reflect.DeepEqual(got, wantRecord) {
			t.Fatalf("%s=%#v, want %#v", name, got, wantRecord)
		}
	}
	if payload, err := os.ReadFile(filepath.Join(cfg.CacheDir, "current456.js")); err != nil || string(payload) != source {
		t.Fatalf("versioned source=%q error=%v", payload, err)
	}
	temporary, err := filepath.Glob(filepath.Join(cfg.CacheDir, "*.tmp*"))
	if err != nil {
		t.Fatal(err)
	}
	if hiddenTemporary, globErr := filepath.Glob(filepath.Join(cfg.CacheDir, ".*.tmp*")); globErr != nil {
		t.Fatal(globErr)
	} else {
		temporary = append(temporary, hiddenTemporary...)
	}
	if len(temporary) != 0 {
		t.Fatalf("temporary cache files remain: %v", temporary)
	}
}

func TestCacheIgnoresCorruptRecords(t *testing.T) {
	now := time.Unix(20_000, 0)
	cfg := testConfig(t)
	if err := os.WriteFile(filepath.Join(cfg.CacheDir, latestCacheFile), []byte(`{"version":`), 0o600); err != nil {
		t.Fatal(err)
	}
	attackerRecord, err := json.Marshal(cacheRecordFixture{
		Version:    "evil123",
		SDKURL:     "https://attacker.example/sentinel/evil123/sdk.js",
		ResolvedAt: float64(now.Unix()),
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(cfg.CacheDir, lastGoodCacheFile), attackerRecord, 0o600); err != nil {
		t.Fatal(err)
	}
	client := &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
		return bytesResponse(http.StatusServiceUnavailable, nil), nil
	})}
	resolver := mustResolver(t, cfg, WithClock(func() time.Time { return now }))

	candidates, err := resolver.Candidates(context.Background(), client)
	if err != nil {
		t.Fatalf("Candidates() error=%v", err)
	}
	if !reflect.DeepEqual(candidates, []SDK{builtinSDK()}) {
		t.Fatalf("Candidates()=%#v", candidates)
	}
}

func TestCacheIgnoresOutOfRangeTimestamp(t *testing.T) {
	cfg := testConfig(t)
	record := []byte(`{"version":"cached123","sdk_url":"https://sentinel.openai.com/sentinel/cached123/sdk.js","resolved_at":9223372036854775807}`)
	if err := os.WriteFile(filepath.Join(cfg.CacheDir, latestCacheFile), record, 0o600); err != nil {
		t.Fatal(err)
	}
	client := &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
		return bytesResponse(http.StatusServiceUnavailable, nil), nil
	})}
	resolver := mustResolver(t, cfg)

	candidates, err := resolver.Candidates(context.Background(), client)
	if err != nil {
		t.Fatalf("Candidates() error=%v", err)
	}
	if !reflect.DeepEqual(candidates, []SDK{builtinSDK()}) {
		t.Fatalf("out-of-range cache timestamp was trusted: %#v", candidates)
	}
}

func TestCacheIgnoresEmptyAndOversizedSources(t *testing.T) {
	for _, tt := range []struct {
		name   string
		cached []byte
	}{
		{name: "empty", cached: nil},
		{name: "whitespace", cached: []byte(" \r\n")},
		{name: "oversized", cached: bytes.Repeat([]byte("x"), maxSDKBytes+1)},
	} {
		t.Run(tt.name, func(t *testing.T) {
			cfg := testConfig(t)
			sdk := sdkForVersion("cached123", "")
			if err := os.WriteFile(filepath.Join(cfg.CacheDir, sdk.Version+".js"), tt.cached, 0o600); err != nil {
				t.Fatal(err)
			}
			const downloaded = "globalThis.valid = true;"
			var calls atomic.Int32
			client := &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
				calls.Add(1)
				return bytesResponse(http.StatusOK, []byte(downloaded)), nil
			})}
			resolver := mustResolver(t, cfg)

			got, err := resolver.Source(context.Background(), client, sdk)
			if err != nil {
				t.Fatalf("Source() error=%v", err)
			}
			if string(got) != downloaded || calls.Load() != 1 {
				t.Fatalf("source=%q calls=%d", got, calls.Load())
			}
			persisted, err := os.ReadFile(filepath.Join(cfg.CacheDir, sdk.Version+".js"))
			if err != nil || string(persisted) != downloaded {
				t.Fatalf("persisted source=%q error=%v", persisted, err)
			}
		})
	}
}

func TestCacheReturnsValidVersionedSourceWithoutNetwork(t *testing.T) {
	cfg := testConfig(t)
	sdk := sdkForVersion("cached123", "")
	const source = "globalThis.cached = true;"
	if err := os.WriteFile(filepath.Join(cfg.CacheDir, sdk.Version+".js"), []byte(source), 0o600); err != nil {
		t.Fatal(err)
	}
	resolver := mustResolver(t, cfg)

	got, err := resolver.Source(context.Background(), noNetworkClient(t), sdk)
	if err != nil {
		t.Fatalf("Source() error=%v", err)
	}
	if string(got) != source {
		t.Fatalf("Source()=%q", got)
	}
	got[0] = 'X'
	again, err := resolver.Source(context.Background(), noNetworkClient(t), sdk)
	if err != nil || string(again) != source {
		t.Fatalf("cached source was aliased: %q error=%v", again, err)
	}
}

func TestCacheWriteFailureDoesNotHideDiscoveryOrDownload(t *testing.T) {
	root := t.TempDir()
	blocked := filepath.Join(root, "not-a-directory")
	if err := os.WriteFile(blocked, []byte("block cache directory creation"), 0o600); err != nil {
		t.Fatal(err)
	}
	cfg := testConfig(t)
	cfg.CacheDir = blocked
	const source = "globalThis.downloaded = true;"
	client := &http.Client{Transport: roundTripFunc(func(req *http.Request) (*http.Response, error) {
		if req.URL.String() == defaultFrameURL {
			return bytesResponse(http.StatusOK, []byte(`<script src="/sentinel/current456/sdk.js"></script>`)), nil
		}
		return bytesResponse(http.StatusOK, []byte(source)), nil
	})}
	resolver := mustResolver(t, cfg)

	candidates, err := resolver.Candidates(context.Background(), client)
	if err != nil || candidates[0].Version != "current456" {
		t.Fatalf("Candidates()=%#v error=%v", candidates, err)
	}
	got, err := resolver.Source(context.Background(), client, candidates[0])
	if err != nil || string(got) != source {
		t.Fatalf("Source()=%q error=%v", got, err)
	}
	if err := resolver.MarkGood(candidates[0]); err == nil {
		t.Fatal("MarkGood() accepted an unwritable cache")
	}
}

func TestCacheMarkGoodDoesNotRewriteUnchangedSDK(t *testing.T) {
	var unixTime atomic.Int64
	unixTime.Store(20_000)
	cfg := testConfig(t)
	resolver := mustResolver(t, cfg, WithClock(func() time.Time {
		return time.Unix(unixTime.Load(), 0)
	}))
	sdk := sdkForVersion("known123", SDKSourceDiscovery)
	if err := resolver.MarkGood(sdk); err != nil {
		t.Fatalf("first MarkGood() error=%v", err)
	}
	unixTime.Store(30_000)
	if err := resolver.MarkGood(sdk); err != nil {
		t.Fatalf("second MarkGood() error=%v", err)
	}

	record := readCacheRecordFixture(t, filepath.Join(cfg.CacheDir, lastGoodCacheFile))
	if record.ResolvedAt != 20_000 {
		t.Fatalf("unchanged SDK was rewritten: %#v", record)
	}
}

func TestCacheConcurrentReadersAndWritersObserveCompleteRecords(t *testing.T) {
	now := time.Unix(20_000, 0)
	cfg := testConfig(t)
	cfg.SDKVersion = "current456"
	sdks := []SDK{
		sdkForVersion("known123", SDKSourceDiscovery),
		sdkForVersion("known789", SDKSourceDiscovery),
	}
	const workers = 24
	const iterations = 40
	start := make(chan struct{})
	errorsSeen := make(chan error, workers)
	var wait sync.WaitGroup

	for worker := range workers {
		wait.Add(1)
		go func(worker int) {
			defer wait.Done()
			resolver := mustResolverConcurrent(cfg, func() time.Time { return now })
			<-start
			for iteration := range iterations {
				if (worker+iteration)%2 == 0 {
					sdkIndex := (worker + iteration/2) % len(sdks)
					if err := resolver.MarkGood(sdks[sdkIndex]); err != nil {
						errorsSeen <- err
						return
					}
					continue
				}
				candidates, err := resolver.Candidates(context.Background(), nil)
				if err != nil {
					errorsSeen <- err
					return
				}
				for _, candidate := range candidates {
					parsed, parseErr := parseSDKURL(candidate.URL)
					if parseErr != nil || parsed.Version != candidate.Version {
						errorsSeen <- errors.New("reader observed a partial cache record")
						return
					}
				}
			}
		}(worker)
	}
	close(start)
	wait.Wait()
	close(errorsSeen)
	for err := range errorsSeen {
		t.Fatal(err)
	}

	record := readCacheRecordFixture(t, filepath.Join(cfg.CacheDir, lastGoodCacheFile))
	if record != (cacheRecordFixture{Version: "known123", SDKURL: sdkForVersion("known123", "").URL, ResolvedAt: float64(now.Unix())}) &&
		record != (cacheRecordFixture{Version: "known789", SDKURL: sdkForVersion("known789", "").URL, ResolvedAt: float64(now.Unix())}) {
		t.Fatalf("final cache record is incomplete: %#v", record)
	}
}

func mustResolverConcurrent(cfg Config, clock func() time.Time) *Resolver {
	resolver, err := NewResolver(cfg, WithClock(clock))
	if err != nil {
		panic(err)
	}
	return resolver
}
