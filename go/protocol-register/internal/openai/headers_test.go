package openai

import (
	"testing"

	"autoteam-f/protocol-register/internal/fingerprint"
)

func TestAPIHeadersUseProfileAndEndpointContext(t *testing.T) {
	profile := mustOpenAIProfile(t, "chrome144")
	headers := APIHeaders(
		"https://chatgpt.com",
		"https://chatgpt.com/auth/login",
		profile,
	)

	want := map[string]string{
		"Origin":             "https://chatgpt.com",
		"Referer":            "https://chatgpt.com/auth/login",
		"Accept":             "application/json",
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
	for name, value := range want {
		if got := headers.Get(name); got != value {
			t.Fatalf("%s=%q want=%q", name, got, value)
		}
	}
}

func TestNavigationHeadersUseProfileAndOmitOrigin(t *testing.T) {
	profile := mustOpenAIProfile(t, "chrome150")
	headers := NavigationHeaders(
		"https://chatgpt.com/oauth/start",
		"https://chatgpt.com/auth/login",
		profile,
	)

	if got := headers.Get("Origin"); got != "" {
		t.Fatalf("Origin=%q, want empty", got)
	}
	want := map[string]string{
		"Referer":            "https://chatgpt.com/auth/login",
		"Accept":             "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
		"User-Agent":         profile.UserAgent,
		"Sec-CH-UA":          profile.SecCHUA,
		"Sec-CH-UA-Mobile":   profile.SecCHUAMobile,
		"Sec-CH-UA-Platform": profile.SecCHUAPlatform,
		"Accept-Language":    profile.AcceptLanguage,
		"Sec-Fetch-Dest":     "document",
		"Sec-Fetch-Mode":     "navigate",
		"Sec-Fetch-Site":     "same-origin",
		"Sec-Fetch-User":     "?1",
		"Priority":           "u=0, i",
	}
	for name, value := range want {
		if got := headers.Get(name); got != value {
			t.Fatalf("%s=%q want=%q", name, got, value)
		}
	}
}

func TestNavigationHeadersDeriveFetchSite(t *testing.T) {
	profile := mustOpenAIProfile(t, "chrome146")
	tests := []struct {
		name    string
		target  string
		referer string
		want    string
	}{
		{name: "same origin", target: "https://auth.openai.com/oauth", referer: "https://auth.openai.com/login", want: "same-origin"},
		{name: "same site", target: "https://auth.openai.com/oauth", referer: "https://platform.openai.com/login", want: "same-site"},
		{name: "cross site", target: "https://auth.openai.com/oauth", referer: "https://chatgpt.com/login", want: "cross-site"},
		{name: "no referer", target: "https://auth.openai.com/oauth", referer: "", want: "none"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			headers := NavigationHeaders(tt.target, tt.referer, profile)
			if got := headers.Get("Sec-Fetch-Site"); got != tt.want {
				t.Fatalf("Sec-Fetch-Site=%q want=%q", got, tt.want)
			}
		})
	}
}

func mustOpenAIProfile(t *testing.T, name string) fingerprint.Profile {
	t.Helper()
	profile, ok := fingerprint.Lookup(name)
	if !ok {
		t.Fatalf("profile %q was not found", name)
	}
	return profile
}
