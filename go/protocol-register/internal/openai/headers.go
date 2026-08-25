package openai

import "net/http"

const UserAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"

func CommonHeaders(referer string) http.Header {
	h := http.Header{}
	h.Set("User-Agent", UserAgent)
	h.Set("Accept", "application/json,text/html,*/*")
	h.Set("Referer", referer)
	h.Set("Origin", "https://auth.openai.com")
	return h
}
