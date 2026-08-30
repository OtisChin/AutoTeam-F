package sentinel

import (
	"testing"
	"time"
)

var configEnvNames = []string{
	"GO_PROTOCOL_SENTINEL_SDK_URL",
	"GO_PROTOCOL_SENTINEL_SDK_VERSION",
	"GO_PROTOCOL_SENTINEL_CACHE_DIR",
	"GO_PROTOCOL_SENTINEL_SDK_TTL_SECONDS",
	"GO_PROTOCOL_SENTINEL_HTTP_TIMEOUT_SECONDS",
	"GO_PROTOCOL_SENTINEL_VM_TIMEOUT_SECONDS",
}

func TestDefaultConfig(t *testing.T) {
	clearConfigEnv(t)
	cfg, err := LoadConfigFromEnv()
	if err != nil {
		t.Fatalf("LoadConfigFromEnv() error=%v", err)
	}
	if cfg.SDKURL != "" || cfg.SDKVersion != "" || cfg.CacheDir == "" {
		t.Fatalf("override/default paths=%#v", cfg)
	}
	if cfg.SDKTTL != 6*time.Hour || cfg.HTTPTimeout != 10*time.Second || cfg.VMTimeout != 45*time.Second {
		t.Fatalf("durations=%#v", cfg)
	}
	if cfg.FrameURL != defaultFrameURL || cfg.RequestURL != defaultRequestURL || cfg.BuiltinVersion != builtinVersion {
		t.Fatalf("official defaults=%#v", cfg)
	}
}

func TestLoadConfigFromEnvUsesValidatedOverrides(t *testing.T) {
	clearConfigEnv(t)
	cacheDir := t.TempDir()
	t.Setenv("GO_PROTOCOL_SENTINEL_SDK_URL", "https://sentinel.openai.com/sentinel/manual123/sdk.js")
	t.Setenv("GO_PROTOCOL_SENTINEL_SDK_VERSION", "version_456")
	t.Setenv("GO_PROTOCOL_SENTINEL_CACHE_DIR", cacheDir)
	t.Setenv("GO_PROTOCOL_SENTINEL_SDK_TTL_SECONDS", "0")
	t.Setenv("GO_PROTOCOL_SENTINEL_HTTP_TIMEOUT_SECONDS", "2")
	t.Setenv("GO_PROTOCOL_SENTINEL_VM_TIMEOUT_SECONDS", "3")

	cfg, err := LoadConfigFromEnv()
	if err != nil {
		t.Fatalf("LoadConfigFromEnv() error=%v", err)
	}
	if cfg.SDKURL != "https://sentinel.openai.com/sentinel/manual123/sdk.js" || cfg.SDKVersion != "version_456" || cfg.CacheDir != cacheDir {
		t.Fatalf("overrides=%#v", cfg)
	}
	if cfg.SDKTTL != 0 || cfg.HTTPTimeout != 2*time.Second || cfg.VMTimeout != 3*time.Second {
		t.Fatalf("durations=%#v", cfg)
	}
}

func TestLoadConfigFromEnvRejectsInvalidValues(t *testing.T) {
	tests := []struct {
		name  string
		env   string
		value string
	}{
		{name: "SDK URL", env: "GO_PROTOCOL_SENTINEL_SDK_URL", value: "https://attacker.example/sentinel/abc/sdk.js"},
		{name: "SDK version", env: "GO_PROTOCOL_SENTINEL_SDK_VERSION", value: "../escape"},
		{name: "negative TTL", env: "GO_PROTOCOL_SENTINEL_SDK_TTL_SECONDS", value: "-1"},
		{name: "invalid TTL", env: "GO_PROTOCOL_SENTINEL_SDK_TTL_SECONDS", value: "invalid"},
		{name: "zero HTTP timeout", env: "GO_PROTOCOL_SENTINEL_HTTP_TIMEOUT_SECONDS", value: "0"},
		{name: "negative VM timeout", env: "GO_PROTOCOL_SENTINEL_VM_TIMEOUT_SECONDS", value: "-5"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			clearConfigEnv(t)
			t.Setenv(tt.env, tt.value)
			if _, err := LoadConfigFromEnv(); err == nil {
				t.Fatalf("%s=%q was accepted", tt.env, tt.value)
			}
		})
	}
}

func clearConfigEnv(t *testing.T) {
	t.Helper()
	for _, name := range configEnvNames {
		t.Setenv(name, "")
	}
}
