package openai

import (
	"strings"
	"testing"
)

func TestResolveTransportProfileNeverClaimsChrome(t *testing.T) {
	for _, raw := range []string{"", "chrome143,chrome152", "chrome147"} {
		got := ResolveTransportProfile(raw)
		if got.Name != "go-http" || strings.Contains(got.UserAgent, "Chrome/") {
			t.Fatalf("raw=%q profile=%#v", raw, got)
		}
	}
}
