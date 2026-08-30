package sentinel

import (
	"fmt"
	"math"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

const (
	defaultFrameURL   = "https://sentinel.openai.com/backend-api/sentinel/frame.html"
	defaultRequestURL = "https://sentinel.openai.com/backend-api/sentinel/req"
	builtinVersion    = "20260219f9f6"

	defaultSDKTTL      = 6 * time.Hour
	defaultHTTPTimeout = 10 * time.Second
	defaultVMTimeout   = 45 * time.Second
)

type Config struct {
	SDKURL         string
	SDKVersion     string
	CacheDir       string
	SDKTTL         time.Duration
	HTTPTimeout    time.Duration
	VMTimeout      time.Duration
	FrameURL       string
	RequestURL     string
	BuiltinVersion string
}

func LoadConfigFromEnv() (Config, error) {
	cfg := Config{
		CacheDir:       defaultCacheDir(),
		SDKTTL:         defaultSDKTTL,
		HTTPTimeout:    defaultHTTPTimeout,
		VMTimeout:      defaultVMTimeout,
		FrameURL:       defaultFrameURL,
		RequestURL:     defaultRequestURL,
		BuiltinVersion: builtinVersion,
	}

	if raw := os.Getenv("GO_PROTOCOL_SENTINEL_SDK_URL"); raw != "" {
		sdk, err := parseSDKURL(raw)
		if err != nil {
			return Config{}, fmt.Errorf("GO_PROTOCOL_SENTINEL_SDK_URL: %w", err)
		}
		cfg.SDKURL = sdk.URL
	}
	if raw := os.Getenv("GO_PROTOCOL_SENTINEL_SDK_VERSION"); raw != "" {
		if err := validateSDKVersion(raw); err != nil {
			return Config{}, fmt.Errorf("GO_PROTOCOL_SENTINEL_SDK_VERSION: %w", err)
		}
		cfg.SDKVersion = raw
	}
	if raw := os.Getenv("GO_PROTOCOL_SENTINEL_CACHE_DIR"); strings.TrimSpace(raw) != "" {
		cfg.CacheDir = raw
	}

	var err error
	if cfg.SDKTTL, err = durationFromEnv("GO_PROTOCOL_SENTINEL_SDK_TTL_SECONDS", cfg.SDKTTL, true); err != nil {
		return Config{}, err
	}
	if cfg.HTTPTimeout, err = durationFromEnv("GO_PROTOCOL_SENTINEL_HTTP_TIMEOUT_SECONDS", cfg.HTTPTimeout, false); err != nil {
		return Config{}, err
	}
	if cfg.VMTimeout, err = durationFromEnv("GO_PROTOCOL_SENTINEL_VM_TIMEOUT_SECONDS", cfg.VMTimeout, false); err != nil {
		return Config{}, err
	}
	return cfg, nil
}

func defaultCacheDir() string {
	root, err := os.UserCacheDir()
	if err != nil || strings.TrimSpace(root) == "" {
		root = os.TempDir()
	}
	return filepath.Join(root, "autoteam-f", "go-protocol", "sentinel")
}

func durationFromEnv(name string, fallback time.Duration, allowZero bool) (time.Duration, error) {
	raw := strings.TrimSpace(os.Getenv(name))
	if raw == "" {
		return fallback, nil
	}
	seconds, err := strconv.ParseInt(raw, 10, 64)
	if err != nil {
		return 0, fmt.Errorf("%s must be an integer number of seconds", name)
	}
	if seconds < 0 || (!allowZero && seconds == 0) {
		return 0, fmt.Errorf("%s must be %s", name, positiveDescription(allowZero))
	}
	if seconds > math.MaxInt64/int64(time.Second) {
		return 0, fmt.Errorf("%s is too large", name)
	}
	return time.Duration(seconds) * time.Second, nil
}

func positiveDescription(allowZero bool) string {
	if allowZero {
		return "zero or greater"
	}
	return "greater than zero"
}
