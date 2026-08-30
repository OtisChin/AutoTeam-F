package sentinel

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"

	"golang.org/x/net/html"
)

var (
	ErrInvalidConfig        = errors.New("invalid Sentinel configuration")
	ErrInvalidSDKURL        = errors.New("invalid official Sentinel SDK URL")
	ErrInvalidSDKVersion    = errors.New("invalid Sentinel SDK version")
	ErrNoSDKInFrame         = errors.New("official Sentinel frame contains no valid SDK")
	ErrNilHTTPClient        = errors.New("Sentinel HTTP client is nil")
	ErrHTTPTransport        = errors.New("Sentinel HTTP transport failed")
	ErrUnexpectedHTTPStatus = errors.New("unexpected Sentinel HTTP status")
	ErrResponseTooLarge     = errors.New("Sentinel response exceeds size limit")
	ErrEmptySDKSource       = errors.New("Sentinel SDK source is empty")
)

const (
	SDKSourceEnvURL     = "env_url"
	SDKSourceEnvVersion = "env_version"
	SDKSourceCache      = "cache"
	SDKSourceDiscovery  = "discovery"
	SDKSourceStaleCache = "stale_cache"
	SDKSourceLastGood   = "last_good"
	SDKSourceBuiltin    = "builtin"
)

var sdkVersionPattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$`)

type SDK struct {
	Version string
	URL     string
	Source  string
}

type Resolver struct {
	cfg   Config
	cache *sdkCache
	now   func() time.Time
}

type ResolverOption func(*Resolver) error

func WithClock(clock func() time.Time) ResolverOption {
	return func(resolver *Resolver) error {
		if clock == nil {
			return fmt.Errorf("%w: clock is nil", ErrInvalidConfig)
		}
		resolver.now = clock
		return nil
	}
}

func NewResolver(cfg Config, options ...ResolverOption) (*Resolver, error) {
	normalized, err := normalizeConfig(cfg)
	if err != nil {
		return nil, err
	}
	resolver := &Resolver{
		cfg: normalized,
		now: time.Now,
	}
	resolver.cache = newSDKCache(normalized.CacheDir)
	for _, option := range options {
		if option == nil {
			return nil, fmt.Errorf("%w: resolver option is nil", ErrInvalidConfig)
		}
		if err := option(resolver); err != nil {
			return nil, err
		}
	}
	return resolver, nil
}

func (r *Resolver) Candidates(ctx context.Context, client *http.Client) ([]SDK, error) {
	if ctx == nil {
		return nil, fmt.Errorf("%w: context is nil", ErrInvalidConfig)
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}

	candidates := make([]SDK, 0, 3)
	switch {
	case r.cfg.SDKURL != "":
		sdk, _ := parseSDKURL(r.cfg.SDKURL)
		sdk.Source = SDKSourceEnvURL
		candidates = append(candidates, sdk)
	case r.cfg.SDKVersion != "":
		sdk, _ := sdkFromVersion(r.cfg.SDKVersion, SDKSourceEnvVersion)
		candidates = append(candidates, sdk)
	default:
		cached, hasCached := r.cache.readRecord(latestCacheFile)
		if hasCached && r.cacheIsFresh(cached.ResolvedAt) {
			cached.SDK.Source = SDKSourceCache
			candidates = append(candidates, cached.SDK)
		} else {
			discovered, discoverErr := r.discoverSDK(ctx, client)
			if discoverErr == nil {
				candidates = append(candidates, discovered)
				_ = r.cache.writeRecord(latestCacheFile, discovered, r.now())
			} else if err := ctx.Err(); err != nil {
				return nil, err
			} else if hasCached {
				cached.SDK.Source = SDKSourceStaleCache
				candidates = append(candidates, cached.SDK)
			}
		}
	}

	if lastGood, ok := r.cache.readRecord(lastGoodCacheFile); ok {
		lastGood.SDK.Source = SDKSourceLastGood
		candidates = append(candidates, lastGood.SDK)
	}
	builtin, _ := sdkFromVersion(r.cfg.BuiltinVersion, SDKSourceBuiltin)
	candidates = append(candidates, builtin)
	return deduplicateSDKs(candidates), nil
}

func (r *Resolver) Source(ctx context.Context, client *http.Client, sdk SDK) ([]byte, error) {
	if ctx == nil {
		return nil, fmt.Errorf("%w: context is nil", ErrInvalidConfig)
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	normalized, err := normalizeSDK(sdk)
	if err != nil {
		return nil, err
	}
	if source, ok := r.cache.readSource(normalized.Version); ok {
		return source, nil
	}

	source, err := r.fetch(ctx, client, normalized.URL, maxSDKBytes, func(headers http.Header) {
		headers.Set("Accept", "application/javascript,*/*;q=0.8")
		headers.Set("Referer", r.cfg.FrameURL)
	})
	if err != nil {
		return nil, err
	}
	if len(bytes.TrimSpace(source)) == 0 {
		return nil, ErrEmptySDKSource
	}
	_ = r.cache.writeSource(normalized.Version, source)
	return append([]byte(nil), source...), nil
}

func (r *Resolver) MarkGood(sdk SDK) error {
	return r.cache.writeRecordIfChanged(lastGoodCacheFile, sdk, r.now())
}

func (r *Resolver) discoverSDK(ctx context.Context, client *http.Client) (SDK, error) {
	frame, err := r.fetch(ctx, client, r.cfg.FrameURL, maxFrameBytes, func(headers http.Header) {
		headers.Set("Accept", "text/html,application/xhtml+xml")
		headers.Set("Cache-Control", "no-cache")
		headers.Set("Pragma", "no-cache")
		headers.Set("Referer", "https://auth.openai.com/")
	})
	if err != nil {
		return SDK{}, err
	}
	base, _ := url.Parse(r.cfg.FrameURL)
	tokenizer := html.NewTokenizer(bytes.NewReader(frame))
	for {
		switch tokenizer.Next() {
		case html.ErrorToken:
			if errors.Is(tokenizer.Err(), io.EOF) {
				return SDK{}, ErrNoSDKInFrame
			}
			return SDK{}, fmt.Errorf("parse official Sentinel frame: %w", tokenizer.Err())
		case html.StartTagToken, html.SelfClosingTagToken:
			token := tokenizer.Token()
			if !strings.EqualFold(token.Data, "script") {
				continue
			}
			for _, attribute := range token.Attr {
				if !strings.EqualFold(attribute.Key, "src") || strings.TrimSpace(attribute.Val) == "" {
					continue
				}
				reference, parseErr := url.Parse(strings.TrimSpace(attribute.Val))
				if parseErr != nil {
					continue
				}
				resolved := base.ResolveReference(reference)
				sdk, validateErr := parseSDKURL(resolved.String())
				if validateErr != nil {
					continue
				}
				sdk.Source = SDKSourceDiscovery
				return sdk, nil
			}
		}
	}
}

func (r *Resolver) fetch(ctx context.Context, client *http.Client, rawURL string, limit int64, applyHeaders func(http.Header)) ([]byte, error) {
	if client == nil {
		return nil, ErrNilHTTPClient
	}
	requestContext, cancel := context.WithTimeout(ctx, r.cfg.HTTPTimeout)
	defer cancel()
	request, err := http.NewRequestWithContext(requestContext, http.MethodGet, rawURL, nil)
	if err != nil {
		return nil, fmt.Errorf("build Sentinel request: %w", err)
	}
	if applyHeaders != nil {
		applyHeaders(request.Header)
	}
	boundedClient := *client
	boundedClient.CheckRedirect = func(*http.Request, []*http.Request) error {
		return http.ErrUseLastResponse
	}
	response, err := boundedClient.Do(request)
	if err != nil {
		switch {
		case errors.Is(err, context.Canceled):
			return nil, context.Canceled
		case errors.Is(err, context.DeadlineExceeded):
			return nil, context.DeadlineExceeded
		default:
			return nil, ErrHTTPTransport
		}
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("%w: %d", ErrUnexpectedHTTPStatus, response.StatusCode)
	}
	if response.ContentLength > limit {
		return nil, ErrResponseTooLarge
	}
	payload, err := io.ReadAll(io.LimitReader(response.Body, limit+1))
	if err != nil {
		return nil, fmt.Errorf("read official Sentinel resource: %w", err)
	}
	if int64(len(payload)) > limit {
		return nil, ErrResponseTooLarge
	}
	return payload, nil
}

func (r *Resolver) cacheIsFresh(resolvedAt time.Time) bool {
	if r.cfg.SDKTTL <= 0 {
		return false
	}
	age := r.now().Sub(resolvedAt)
	return age >= 0 && age <= r.cfg.SDKTTL
}

func normalizeConfig(cfg Config) (Config, error) {
	if strings.TrimSpace(cfg.CacheDir) == "" {
		cfg.CacheDir = defaultCacheDir()
	}
	if cfg.FrameURL == "" {
		cfg.FrameURL = defaultFrameURL
	}
	if cfg.RequestURL == "" {
		cfg.RequestURL = defaultRequestURL
	}
	if cfg.BuiltinVersion == "" {
		cfg.BuiltinVersion = builtinVersion
	}
	if cfg.FrameURL != defaultFrameURL {
		return Config{}, fmt.Errorf("%w: unsupported frame URL", ErrInvalidConfig)
	}
	if cfg.RequestURL != defaultRequestURL {
		return Config{}, fmt.Errorf("%w: unsupported request URL", ErrInvalidConfig)
	}
	if cfg.SDKTTL < 0 {
		return Config{}, fmt.Errorf("%w: SDK TTL must be zero or greater", ErrInvalidConfig)
	}
	if cfg.HTTPTimeout <= 0 {
		return Config{}, fmt.Errorf("%w: HTTP timeout must be greater than zero", ErrInvalidConfig)
	}
	if cfg.VMTimeout <= 0 {
		return Config{}, fmt.Errorf("%w: VM timeout must be greater than zero", ErrInvalidConfig)
	}
	if cfg.SDKURL != "" {
		if _, err := parseSDKURL(cfg.SDKURL); err != nil {
			return Config{}, err
		}
	}
	if cfg.SDKVersion != "" {
		if err := validateSDKVersion(cfg.SDKVersion); err != nil {
			return Config{}, err
		}
	}
	if err := validateSDKVersion(cfg.BuiltinVersion); err != nil {
		return Config{}, err
	}
	return cfg, nil
}

func parseSDKURL(raw string) (SDK, error) {
	if raw == "" || strings.TrimSpace(raw) != raw {
		return SDK{}, ErrInvalidSDKURL
	}
	parsed, err := url.Parse(raw)
	if err != nil || parsed.Opaque != "" || parsed.User != nil {
		return SDK{}, ErrInvalidSDKURL
	}
	if !strings.EqualFold(parsed.Scheme, "https") {
		return SDK{}, ErrInvalidSDKURL
	}
	host := parsed.Host
	if !strings.EqualFold(host, "sentinel.openai.com") && !strings.EqualFold(host, "sentinel.openai.com:443") {
		return SDK{}, ErrInvalidSDKURL
	}
	if parsed.RawQuery != "" || parsed.ForceQuery || parsed.Fragment != "" || parsed.RawFragment != "" || parsed.RawPath != "" {
		return SDK{}, ErrInvalidSDKURL
	}
	const prefix = "/sentinel/"
	const suffix = "/sdk.js"
	if !strings.HasPrefix(parsed.Path, prefix) || !strings.HasSuffix(parsed.Path, suffix) {
		return SDK{}, ErrInvalidSDKURL
	}
	version := strings.TrimSuffix(strings.TrimPrefix(parsed.Path, prefix), suffix)
	if strings.Contains(version, "/") || validateSDKVersion(version) != nil {
		return SDK{}, ErrInvalidSDKURL
	}
	if parsed.Path != prefix+version+suffix {
		return SDK{}, ErrInvalidSDKURL
	}
	return SDK{Version: version, URL: raw}, nil
}

func validateSDKVersion(version string) error {
	if !sdkVersionPattern.MatchString(version) {
		return ErrInvalidSDKVersion
	}
	return nil
}

func sdkFromVersion(version, source string) (SDK, error) {
	if err := validateSDKVersion(version); err != nil {
		return SDK{}, err
	}
	return SDK{
		Version: version,
		URL:     "https://sentinel.openai.com/sentinel/" + version + "/sdk.js",
		Source:  source,
	}, nil
}

func normalizeSDK(sdk SDK) (SDK, error) {
	if err := validateSDKVersion(sdk.Version); err != nil {
		return SDK{}, err
	}
	parsed, err := parseSDKURL(sdk.URL)
	if err != nil || parsed.Version != sdk.Version {
		return SDK{}, ErrInvalidSDKURL
	}
	parsed.Source = sdk.Source
	return parsed, nil
}

func deduplicateSDKs(candidates []SDK) []SDK {
	unique := make([]SDK, 0, len(candidates))
	seen := make(map[string]struct{}, len(candidates))
	for _, sdk := range candidates {
		key := sdk.Version + "\x00" + sdk.URL
		if _, exists := seen[key]; exists {
			continue
		}
		seen[key] = struct{}{}
		unique = append(unique, sdk)
	}
	return unique
}
