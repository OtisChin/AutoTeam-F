package sentinel_test

import (
	"context"
	"os"
	"testing"
	"time"

	"autoteam-f/protocol-register/internal/fingerprint"
	"autoteam-f/protocol-register/internal/httpclient"
	"autoteam-f/protocol-register/internal/sentinel"
)

func TestOfficialSDKRequirementsOnlineSmoke(t *testing.T) {
	if os.Getenv("GO_PROTOCOL_SENTINEL_ONLINE_SMOKE") != "1" {
		t.Skip("set GO_PROTOCOL_SENTINEL_ONLINE_SMOKE=1 to run the read-only official SDK smoke")
	}

	cfg, err := sentinel.LoadConfigFromEnv()
	if err != nil {
		t.Fatal(err)
	}
	resolver, err := sentinel.NewResolver(cfg)
	if err != nil {
		t.Fatal(err)
	}
	compiler, err := sentinel.NewCompiler(resolver)
	if err != nil {
		t.Fatal(err)
	}
	runtime, err := sentinel.NewRuntime(cfg.VMTimeout)
	if err != nil {
		t.Fatal(err)
	}
	provider, err := sentinel.NewProvider(cfg, resolver, compiler, runtime)
	if err != nil {
		t.Fatal(err)
	}
	profile, ok := fingerprint.Lookup("chrome144")
	if !ok {
		t.Fatal("built-in chrome144 profile is unavailable")
	}

	const smokeTimeout = 2 * time.Minute
	client, err := httpclient.NewProfiled(profile, "", smokeTimeout)
	if err != nil {
		t.Fatal(err)
	}
	defer client.CloseIdleConnections()
	ctx, cancel := context.WithTimeout(context.Background(), smokeTimeout)
	defer cancel()

	status := provider.DryRun(ctx, client, profile)
	if !status.Ready || status.SDKVersion == "" || status.Reason != "" {
		t.Fatalf("official Sentinel requirements dry-run status=%#v", status)
	}
}
