package paypal

import (
	http "github.com/bogdanfinn/fhttp"
	tlsclient "github.com/bogdanfinn/tls-client"
	"github.com/bogdanfinn/tls-client/profiles"
)

type tlsSessionOption func(*tlsSessionConfig)

type tlsSessionConfig struct {
	proxyURL         string
	cookieJar        http.CookieJar
	timeoutSeconds   int
	noRedirect       bool
	clientProfile    profiles.ClientProfile
	hasClientProfile bool
}

func withProxyURL(proxyURL string) tlsSessionOption {
	return func(config *tlsSessionConfig) { config.proxyURL = proxyURL }
}

func withCookieJar(jar http.CookieJar) tlsSessionOption {
	return func(config *tlsSessionConfig) { config.cookieJar = jar }
}

func withTimeoutSeconds(seconds int) tlsSessionOption {
	return func(config *tlsSessionConfig) { config.timeoutSeconds = seconds }
}

func withNotFollowRedirects() tlsSessionOption {
	return func(config *tlsSessionConfig) { config.noRedirect = true }
}

func withClientProfile(profile profiles.ClientProfile) tlsSessionOption {
	return func(config *tlsSessionConfig) {
		config.clientProfile = profile
		config.hasClientProfile = true
	}
}

func newTLSSession(options ...tlsSessionOption) (tlsclient.HttpClient, error) {
	config := tlsSessionConfig{timeoutSeconds: 60}
	for _, option := range options {
		option(&config)
	}
	clientOptions := []tlsclient.HttpClientOption{
		tlsclient.WithTimeoutSeconds(config.timeoutSeconds),
		tlsclient.WithRandomTLSExtensionOrder(),
	}
	if config.cookieJar != nil {
		clientOptions = append(clientOptions, tlsclient.WithCookieJar(config.cookieJar))
	} else {
		clientOptions = append(clientOptions, tlsclient.WithCookieJar(tlsclient.NewCookieJar()))
	}
	if config.proxyURL != "" {
		clientOptions = append(clientOptions, tlsclient.WithProxyUrl(config.proxyURL))
	}
	if config.noRedirect {
		clientOptions = append(clientOptions, tlsclient.WithNotFollowRedirects())
	}
	if config.hasClientProfile {
		clientOptions = append(clientOptions, tlsclient.WithClientProfile(config.clientProfile))
	} else {
		clientOptions = append(clientOptions, tlsclient.WithClientProfile(profiles.Chrome_144))
	}
	return tlsclient.NewHttpClient(tlsclient.NewNoopLogger(), clientOptions...)
}
