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

func normalizeTimeout(timeout time.Duration) time.Duration {
	if timeout <= 0 {
		return defaultTimeout
	}
	return timeout
}
