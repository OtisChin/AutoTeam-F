package openai

import (
	"errors"
	"net/http"
	"net/url"
	"sort"
	"strconv"
	"strings"
)

var ErrSessionMissing = errors.New("session credentials missing")

var sessionCookieNames = []string{
	"__Secure-next-auth.session-token",
	"next-auth.session-token",
	"__Secure-authjs.session-token",
	"authjs.session-token",
}

func ExtractSession(raw map[string]any, jar http.CookieJar, chatGPTBaseURL string) (map[string]any, error) {
	accessToken, _ := raw["accessToken"].(string)
	accessToken = strings.TrimSpace(accessToken)
	if accessToken == "" || jar == nil {
		return nil, ErrSessionMissing
	}
	base, err := url.Parse(chatGPTBaseURL)
	if err != nil || base.Scheme == "" || base.Host == "" {
		return nil, ErrSessionMissing
	}
	sessionToken := extractSessionCookie(jar.Cookies(base))
	if strings.TrimSpace(sessionToken) == "" {
		return nil, ErrSessionMissing
	}

	out := make(map[string]any, len(raw)+1)
	for key, value := range raw {
		out[key] = value
	}
	out["accessToken"] = accessToken
	out["sessionToken"] = sessionToken
	return out, nil
}

func extractSessionCookie(cookies []*http.Cookie) string {
	values := make(map[string]string, len(cookies))
	for _, cookie := range cookies {
		if cookie != nil {
			values[cookie.Name] = cookie.Value
		}
	}
	for _, baseName := range sessionCookieNames {
		if value := values[baseName]; strings.TrimSpace(value) != "" {
			return value
		}
		chunks := make(map[int]string)
		for name, value := range values {
			if !strings.HasPrefix(name, baseName+".") {
				continue
			}
			index, err := strconv.Atoi(strings.TrimPrefix(name, baseName+"."))
			if err == nil && index >= 0 {
				chunks[index] = value
			}
		}
		if len(chunks) == 0 {
			continue
		}
		indexes := make([]int, 0, len(chunks))
		for index := range chunks {
			indexes = append(indexes, index)
		}
		sort.Ints(indexes)
		var joined strings.Builder
		for expected, index := range indexes {
			if index != expected || strings.TrimSpace(chunks[index]) == "" {
				joined.Reset()
				break
			}
			joined.WriteString(chunks[index])
		}
		if joined.Len() > 0 {
			return joined.String()
		}
	}
	return ""
}
