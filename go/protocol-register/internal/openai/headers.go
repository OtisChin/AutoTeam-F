package openai

import "net/http"

func APIHeaders(origin, referer, userAgent string) http.Header {
	if userAgent == "" {
		userAgent = defaultTransportUserAgent
	}
	h := http.Header{}
	h.Set("User-Agent", userAgent)
	h.Set("Accept", "application/json")
	if origin != "" {
		h.Set("Origin", origin)
	}
	if referer != "" {
		h.Set("Referer", referer)
	}
	return h
}

func NavigationHeaders(referer, userAgent string) http.Header {
	if userAgent == "" {
		userAgent = defaultTransportUserAgent
	}
	h := http.Header{}
	h.Set("User-Agent", userAgent)
	h.Set("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
	if referer != "" {
		h.Set("Referer", referer)
	}
	return h
}
