package httpclient

import (
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"time"
)

func New(proxyURL string, timeout time.Duration) (*http.Client, error) {
	transport := http.DefaultTransport.(*http.Transport).Clone()
	if proxyURL != "" {
		parsed, err := url.Parse(proxyURL)
		if err != nil {
			return nil, err
		}
		transport.Proxy = http.ProxyURL(parsed)
	}
	jar, _ := cookiejar.New(nil)
	if timeout <= 0 {
		timeout = 190 * time.Second
	}
	return &http.Client{Transport: transport, Jar: jar, Timeout: timeout}, nil
}
