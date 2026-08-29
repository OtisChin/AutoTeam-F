package openai

import (
	"errors"
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"testing"
)

func TestExtractSessionRequiresAccessAndSessionTokens(t *testing.T) {
	jar, err := cookiejar.New(nil)
	if err != nil {
		t.Fatal(err)
	}
	base, err := url.Parse("https://chatgpt.test")
	if err != nil {
		t.Fatal(err)
	}
	jar.SetCookies(base, []*http.Cookie{{Name: "__Secure-next-auth.session-token", Value: "session-1"}})
	raw := map[string]any{"accessToken": "access-1", "user": map[string]any{"email": "user@example.com"}}

	got, err := ExtractSession(raw, jar, base.String())
	if err != nil {
		t.Fatal(err)
	}
	if got["accessToken"] != "access-1" || got["sessionToken"] != "session-1" {
		t.Fatalf("session=%#v", got)
	}
	if _, mutated := raw["sessionToken"]; mutated {
		t.Fatalf("input map was mutated: %#v", raw)
	}
}

func TestExtractSessionReassemblesChunkedCookieInNumericOrder(t *testing.T) {
	jar, _ := cookiejar.New(nil)
	base, _ := url.Parse("https://chatgpt.test")
	jar.SetCookies(base, []*http.Cookie{
		{Name: "__Secure-next-auth.session-token.1", Value: "part-2"},
		{Name: "__Secure-next-auth.session-token.0", Value: "part-1"},
	})

	got, err := ExtractSession(map[string]any{"accessToken": "access-1"}, jar, base.String())
	if err != nil {
		t.Fatal(err)
	}
	if got["sessionToken"] != "part-1part-2" {
		t.Fatalf("sessionToken=%#v", got["sessionToken"])
	}
}

func TestExtractSessionRejectsMissingCredentials(t *testing.T) {
	base, _ := url.Parse("https://chatgpt.test")
	tests := []struct {
		name string
		raw  map[string]any
		jar  http.CookieJar
	}{
		{
			name: "missing access token",
			raw:  map[string]any{},
			jar:  jarWithCookies(base, &http.Cookie{Name: "next-auth.session-token", Value: "session-1"}),
		},
		{
			name: "missing session cookie",
			raw:  map[string]any{"accessToken": "access-1", "sessionToken": "untrusted-response-token"},
			jar:  jarWithCookies(base),
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if _, err := ExtractSession(tt.raw, tt.jar, base.String()); !errors.Is(err, ErrSessionMissing) {
				t.Fatalf("err=%v", err)
			}
		})
	}
}

func jarWithCookies(base *url.URL, cookies ...*http.Cookie) http.CookieJar {
	jar, _ := cookiejar.New(nil)
	jar.SetCookies(base, cookies)
	return jar
}
