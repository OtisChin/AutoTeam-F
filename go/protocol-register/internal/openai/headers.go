package openai

import (
	"net"
	"net/http"
	"net/url"
	"strings"

	"autoteam-f/protocol-register/internal/fingerprint"

	"golang.org/x/net/publicsuffix"
)

func APIHeaders(origin, referer string, profile fingerprint.Profile) http.Header {
	h := profileHeaders(profile)
	h.Set("Accept", "application/json")
	h.Set("Sec-Fetch-Dest", "empty")
	h.Set("Sec-Fetch-Mode", "cors")
	h.Set("Sec-Fetch-Site", "same-origin")
	h.Set("Priority", "u=1, i")
	if origin != "" {
		h.Set("Origin", origin)
	}
	if referer != "" {
		h.Set("Referer", referer)
	}
	return h
}

func NavigationHeaders(target, referer string, profile fingerprint.Profile) http.Header {
	h := profileHeaders(profile)
	h.Set("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
	h.Set("Sec-Fetch-Dest", "document")
	h.Set("Sec-Fetch-Mode", "navigate")
	h.Set("Sec-Fetch-Site", navigationFetchSite(target, referer))
	h.Set("Sec-Fetch-User", "?1")
	h.Set("Priority", "u=0, i")
	if referer != "" {
		h.Set("Referer", referer)
	}
	return h
}

func navigationFetchSite(targetRaw, refererRaw string) string {
	if strings.TrimSpace(refererRaw) == "" {
		return "none"
	}
	target, targetErr := url.Parse(targetRaw)
	referer, refererErr := url.Parse(refererRaw)
	if targetErr != nil || refererErr != nil || target.Hostname() == "" || referer.Hostname() == "" {
		return "cross-site"
	}
	if strings.EqualFold(target.Scheme, referer.Scheme) &&
		strings.EqualFold(target.Hostname(), referer.Hostname()) &&
		effectivePort(target) == effectivePort(referer) {
		return "same-origin"
	}
	if strings.EqualFold(target.Scheme, referer.Scheme) && siteForHost(target.Hostname()) == siteForHost(referer.Hostname()) {
		return "same-site"
	}
	return "cross-site"
}

func siteForHost(host string) string {
	host = strings.TrimSuffix(strings.ToLower(host), ".")
	if net.ParseIP(host) != nil {
		return host
	}
	site, err := publicsuffix.EffectiveTLDPlusOne(host)
	if err != nil {
		return host
	}
	return site
}

func profileHeaders(profile fingerprint.Profile) http.Header {
	h := http.Header{}
	h.Set("User-Agent", profile.UserAgent)
	h.Set("Sec-CH-UA", profile.SecCHUA)
	h.Set("Sec-CH-UA-Mobile", profile.SecCHUAMobile)
	h.Set("Sec-CH-UA-Platform", profile.SecCHUAPlatform)
	h.Set("Accept-Language", profile.AcceptLanguage)
	return h
}
