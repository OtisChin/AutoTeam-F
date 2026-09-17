package openai

import (
	"crypto/rand"
	"encoding/binary"
	"encoding/hex"
	"net"
	"net/http"
	"net/url"
	"strconv"
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
	addDatadogTraceHeaders(h)
	addAccessFlowInvocationID(h)
	if origin != "" {
		h.Set("Origin", origin)
	}
	if referer != "" {
		h.Set("Referer", referer)
	}
	return h
}

func addAccessFlowInvocationID(h http.Header) {
	var raw [16]byte
	if _, err := rand.Read(raw[:]); err != nil {
		return
	}
	// Browser auth requests attach a fresh UUID to every state-machine call.
	h.Set("x-access-flow-invocation-id", hex.EncodeToString(raw[0:4])+"-"+hex.EncodeToString(raw[4:6])+"-"+hex.EncodeToString(raw[6:8])+"-"+hex.EncodeToString(raw[8:10])+"-"+hex.EncodeToString(raw[10:]))
}

func addDatadogTraceHeaders(h http.Header) {
	var traceBytes, parentBytes [8]byte
	if _, err := rand.Read(traceBytes[:]); err != nil {
		return
	}
	if _, err := rand.Read(parentBytes[:]); err != nil {
		return
	}
	traceID := binary.BigEndian.Uint64(traceBytes[:])
	parentID := binary.BigEndian.Uint64(parentBytes[:])
	traceHex := strconv.FormatUint(traceID, 16)
	parentHex := strconv.FormatUint(parentID, 16)
	h.Set("traceparent", "00-0000000000000000"+strings.Repeat("0", 16-len(traceHex))+traceHex+"-"+strings.Repeat("0", 16-len(parentHex))+parentHex+"-01")
	h.Set("tracestate", "dd=s:1;o:rum")
	h.Set("x-datadog-origin", "rum")
	h.Set("x-datadog-parent-id", strconv.FormatUint(parentID, 10))
	h.Set("x-datadog-sampling-priority", "1")
	h.Set("x-datadog-trace-id", strconv.FormatUint(traceID, 10))
}

func NavigationHeaders(target, referer string, profile fingerprint.Profile) http.Header {
	h := profileHeaders(profile)
	addDatadogTraceHeaders(h)
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
