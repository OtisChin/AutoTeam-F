package openai

import "net/http"

func CommonHeaders(referer, userAgent string) http.Header {
	if userAgent == "" {
		userAgent = defaultChromeProfile().UserAgent
	}
	h := http.Header{}
	h.Set("User-Agent", userAgent)
	h.Set("Accept", "application/json,text/html,*/*")
	h.Set("Referer", referer)
	h.Set("Origin", "https://auth.openai.com")
	return h
}
