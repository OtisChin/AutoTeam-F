package proxyutil

import (
	"net/url"
	"sort"
	"strings"
)

// Mask returns a credential-free proxy label suitable for logs.
func Mask(proxy string) string {
	proxy = strings.TrimSpace(proxy)
	if proxy == "" {
		return "(空)"
	}
	parsed, err := url.Parse(proxy)
	if err == nil && parsed.Host != "" {
		if parsed.User != nil {
			return "***@" + parsed.Host
		}
		return "@" + parsed.Host
	}
	if at := strings.LastIndex(proxy, "@"); at >= 0 {
		host := strings.TrimSpace(proxy[at+1:])
		if host == "" {
			return "***@<invalid>"
		}
		return "***@" + host
	}
	if strings.Contains(proxy, "://") {
		return "<invalid proxy>"
	}
	return proxy
}

// RedactText removes raw proxy URLs and their userinfo from an error or log message.
func RedactText(text string, proxies ...string) string {
	redacted := text
	for _, proxy := range proxies {
		proxy = strings.TrimSpace(proxy)
		if proxy == "" {
			continue
		}
		masked := Mask(proxy)
		redacted = strings.ReplaceAll(redacted, proxy, masked)
		redacted = strings.ReplaceAll(redacted, url.QueryEscape(proxy), url.QueryEscape(masked))
		redacted = strings.ReplaceAll(redacted, url.PathEscape(proxy), url.PathEscape(masked))

		variants := credentialVariants(proxy)
		sort.Slice(variants, func(i, j int) bool { return len(variants[i]) > len(variants[j]) })
		for _, secret := range variants {
			if secret != "" {
				redacted = strings.ReplaceAll(redacted, secret, "***")
			}
		}
	}
	return redacted
}

func credentialVariants(proxy string) []string {
	values := make(map[string]struct{})
	add := func(value string) {
		if value == "" {
			return
		}
		values[value] = struct{}{}
		values[url.QueryEscape(value)] = struct{}{}
		values[url.PathEscape(value)] = struct{}{}
		if decoded, err := url.QueryUnescape(value); err == nil {
			values[decoded] = struct{}{}
		}
	}

	if parsed, err := url.Parse(proxy); err == nil && parsed.User != nil {
		add(parsed.User.String())
		add(parsed.User.Username())
		if password, ok := parsed.User.Password(); ok {
			add(password)
		}
	}
	if scheme := strings.Index(proxy, "://"); scheme >= 0 {
		if at := strings.LastIndex(proxy, "@"); at > scheme+3 {
			userinfo := proxy[scheme+3 : at]
			add(userinfo)
			username, password, found := strings.Cut(userinfo, ":")
			add(username)
			if found {
				add(password)
			}
		}
	}

	result := make([]string, 0, len(values))
	for value := range values {
		result = append(result, value)
	}
	return result
}
