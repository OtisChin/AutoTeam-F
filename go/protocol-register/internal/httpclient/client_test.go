package httpclient

import (
	"net/http"
	"testing"
	"time"

	tls_client "github.com/bogdanfinn/tls-client"
)

func TestNewStandardCreatesIndependentClients(t *testing.T) {
	first := NewStandard(3 * time.Second)
	second := NewStandard(5 * time.Second)
	if first.Timeout != 3*time.Second || second.Timeout != 5*time.Second {
		t.Fatalf("timeouts=%s,%s", first.Timeout, second.Timeout)
	}
	if first.Jar == nil || second.Jar == nil || first.Jar == second.Jar {
		t.Fatalf("cookie jars were not independent: %p %p", first.Jar, second.Jar)
	}
	if first.Transport == nil || second.Transport == nil || first.Transport == second.Transport {
		t.Fatalf("transports were not independent: %p %p", first.Transport, second.Transport)
	}

	endpoint := mustURL(t, "https://mail.example.test/")
	first.Jar.SetCookies(endpoint, []*http.Cookie{{Name: "mail", Value: "one"}})
	if cookies := second.Jar.Cookies(endpoint); len(cookies) != 0 {
		t.Fatalf("cookie leaked to second standard client: %v", cookies)
	}
}

func TestNewProfiledBuildsOuterJarAroundOneInnerClient(t *testing.T) {
	profile := mustProfile(t, "chrome150")
	client, err := NewProfiled(profile, "", 4*time.Second)
	if err != nil {
		t.Fatalf("NewProfiled() error=%v", err)
	}
	if client.Timeout != 4*time.Second || client.Jar == nil {
		t.Fatalf("outer client=%#v", client)
	}
	transport, ok := client.Transport.(*roundTripper)
	if !ok {
		t.Fatalf("transport type=%T", client.Transport)
	}
	inner, ok := transport.doer.(tls_client.HttpClient)
	if !ok {
		t.Fatalf("inner client type=%T", transport.doer)
	}
	defer inner.CloseIdleConnections()
	if inner.GetFollowRedirect() {
		t.Fatal("inner tls-client unexpectedly follows redirects")
	}
	if inner.GetCookieJar() != nil {
		t.Fatal("inner tls-client unexpectedly owns a cookie jar")
	}
}

func TestNewProfiledRejectsMalformedProxy(t *testing.T) {
	profile := mustProfile(t, "chrome144")
	if _, err := NewProfiled(profile, "http://proxy-user:secret@[::1", time.Second); err == nil {
		t.Fatal("NewProfiled() accepted malformed proxy URL")
	}
}
