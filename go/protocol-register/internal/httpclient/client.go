package httpclient

import (
	"net/http"
	"net/http/cookiejar"
	"time"

	"autoteam-f/protocol-register/internal/fingerprint"

	tls_client "github.com/bogdanfinn/tls-client"
)

const defaultTimeout = 190 * time.Second

func NewProfiled(profile fingerprint.Profile, proxyURL string, timeout time.Duration) (*http.Client, error) {
	timeout = normalizeTimeout(timeout)
	options := []tls_client.HttpClientOption{
		tls_client.WithClientProfile(profile.TLSProfile),
		tls_client.WithNotFollowRedirects(),
		tls_client.WithTimeoutMilliseconds(int(timeout.Milliseconds())),
	}
	if proxyURL != "" {
		options = append(options, tls_client.WithProxyUrl(proxyURL))
	}
	inner, err := tls_client.NewHttpClient(nil, options...)
	if err != nil {
		return nil, err
	}
	jar, _ := cookiejar.New(nil)
	return &http.Client{
		Transport: newRoundTripper(inner, profile),
		Jar:       jar,
		Timeout:   timeout,
	}, nil
}

func NewStandard(timeout time.Duration) *http.Client {
	timeout = normalizeTimeout(timeout)
	transport := http.DefaultTransport.(*http.Transport).Clone()
	jar, _ := cookiejar.New(nil)
	return &http.Client{Transport: transport, Jar: jar, Timeout: timeout}
}

// NewMailbox returns a client that impersonates a browser TLS/HTTP2
// fingerprint and follows redirects.  Mail receive-code endpoints (e.g. the
// iCloud listing pages) sit behind bot protection that rejects Go's default
// TLS fingerprint, so a plain net/http client can never retrieve the OTP.
func NewMailbox(profile fingerprint.Profile, timeout time.Duration) (*http.Client, error) {
	timeout = normalizeTimeout(timeout)
	inner, err := tls_client.NewHttpClient(nil,
		tls_client.WithClientProfile(profile.TLSProfile),
		tls_client.WithTimeoutMilliseconds(int(timeout.Milliseconds())),
	)
	if err != nil {
		return nil, err
	}
	jar, _ := cookiejar.New(nil)
	return &http.Client{
		Transport: newRoundTripper(inner, profile),
		Jar:       jar,
		Timeout:   timeout,
	}, nil
}

func normalizeTimeout(timeout time.Duration) time.Duration {
	if timeout <= 0 {
		return defaultTimeout
	}
	return timeout
}
