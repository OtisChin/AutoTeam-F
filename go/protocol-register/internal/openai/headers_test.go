package openai

import "testing"

func TestAPIHeadersUseEndpointOriginAndReferer(t *testing.T) {
	headers := APIHeaders(
		"https://chatgpt.com",
		"https://chatgpt.com/auth/login",
		"AutoToken-F protocol-registerd/go-http",
	)

	if got := headers.Get("Origin"); got != "https://chatgpt.com" {
		t.Fatalf("Origin=%q", got)
	}
	if got := headers.Get("Referer"); got != "https://chatgpt.com/auth/login" {
		t.Fatalf("Referer=%q", got)
	}
	if got := headers.Get("Accept"); got != "application/json" {
		t.Fatalf("Accept=%q", got)
	}
}

func TestNavigationHeadersOmitOrigin(t *testing.T) {
	headers := NavigationHeaders(
		"https://chatgpt.com/auth/login",
		"AutoToken-F protocol-registerd/go-http",
	)

	if got := headers.Get("Origin"); got != "" {
		t.Fatalf("Origin=%q, want empty", got)
	}
	if got := headers.Get("Accept"); got != "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8" {
		t.Fatalf("Accept=%q", got)
	}
}
