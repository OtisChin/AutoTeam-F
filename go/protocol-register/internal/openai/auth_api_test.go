package openai

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
)

func TestSigninOpenAIUsesFormContractAndChatGPTOrigin(t *testing.T) {
	type capturedRequest struct {
		method           string
		contentType      string
		origin           string
		referer          string
		userAgent        string
		body             string
		navigationOrigin string
		navigationAccept string
	}
	var captured capturedRequest
	var srv *httptest.Server
	srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/auth/signin/openai":
			raw, _ := io.ReadAll(r.Body)
			captured = capturedRequest{
				method:      r.Method,
				contentType: r.Header.Get("Content-Type"),
				origin:      r.Header.Get("Origin"),
				referer:     r.Header.Get("Referer"),
				userAgent:   r.Header.Get("User-Agent"),
				body:        string(raw),
			}
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]string{"url": srv.URL + "/oauth/start"})
		case "/oauth/start":
			captured.navigationOrigin = r.Header.Get("Origin")
			captured.navigationAccept = r.Header.Get("Accept")
			w.WriteHeader(http.StatusOK)
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()

	profile := ResolveTransportProfile("chrome143,chrome152")
	client := NewClient(srv.Client(), srv.URL, srv.URL, profile.UserAgent)
	if err := client.SigninOpenAI(context.Background(), "csrf-1"); err != nil {
		t.Fatal(err)
	}

	values, err := url.ParseQuery(captured.body)
	if err != nil {
		t.Fatal(err)
	}
	if captured.method != http.MethodPost {
		t.Fatalf("method=%q", captured.method)
	}
	if captured.contentType != "application/x-www-form-urlencoded" {
		t.Fatalf("Content-Type=%q", captured.contentType)
	}
	if captured.origin != srv.URL || captured.referer != srv.URL+"/auth/login" {
		t.Fatalf("origin=%q referer=%q", captured.origin, captured.referer)
	}
	if strings.Contains(captured.userAgent, "Chrome/") {
		t.Fatalf("User-Agent=%q", captured.userAgent)
	}
	if captured.navigationOrigin != "" {
		t.Fatalf("navigation Origin=%q, want empty", captured.navigationOrigin)
	}
	if captured.navigationAccept != "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8" {
		t.Fatalf("navigation Accept=%q", captured.navigationAccept)
	}
	if values.Get("csrfToken") != "csrf-1" || values.Get("callbackUrl") != srv.URL+"/" || values.Get("json") != "true" {
		t.Fatalf("form=%#v", values)
	}
}

func TestClientUsesHeadersForEachEndpointBase(t *testing.T) {
	type capturedHeaders struct {
		origin  string
		referer string
	}
	var authHeaders, chatGPTHeaders capturedHeaders

	authServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		authHeaders = capturedHeaders{origin: r.Header.Get("Origin"), referer: r.Header.Get("Referer")}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{"page": map[string]any{"type": "create_account_password"}})
	}))
	defer authServer.Close()

	chatGPTServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		chatGPTHeaders = capturedHeaders{origin: r.Header.Get("Origin"), referer: r.Header.Get("Referer")}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]string{"csrfToken": "csrf-1"})
	}))
	defer chatGPTServer.Close()

	client := NewClient(http.DefaultClient, authServer.URL, chatGPTServer.URL, defaultTransportUserAgent)
	if _, err := client.GetCSRF(context.Background()); err != nil {
		t.Fatal(err)
	}
	if _, err := client.AuthorizeContinue(context.Background(), "user@example.com"); err != nil {
		t.Fatal(err)
	}

	if chatGPTHeaders.origin != chatGPTServer.URL || chatGPTHeaders.referer != chatGPTServer.URL+"/auth/login" {
		t.Fatalf("ChatGPT headers=%#v", chatGPTHeaders)
	}
	if authHeaders.origin != authServer.URL || authHeaders.referer != authServer.URL+"/" {
		t.Fatalf("auth headers=%#v", authHeaders)
	}
}
