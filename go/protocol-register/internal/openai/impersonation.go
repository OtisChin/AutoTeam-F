package openai

import (
	"fmt"
	"math/rand"
	"regexp"
	"strconv"
	"strings"
)

type ImpersonationProfile struct {
	Name      string
	UserAgent string
}

var defaultChromeVersions = []int{143, 144, 145, 146, 147, 148, 149, 150, 151, 152}
var defaultImpersonationProfilesList = buildDefaultImpersonationProfiles()

var chromeLabelPattern = regexp.MustCompile(`(?i)^chrome(\d+)$`)
var chromeVersionPattern = regexp.MustCompile(`(?i)^(?:chrome/)?(\d+)(?:\.0\.0\.0)?$`)

func ResolveImpersonation(raw string) ImpersonationProfile {
	return resolveImpersonation(raw, rand.Intn)
}

func resolveImpersonation(raw string, pick func(int) int) ImpersonationProfile {
	profiles := collectImpersonationProfiles(raw)
	if len(profiles) == 0 {
		profiles = defaultImpersonationProfilesList
	}
	idx := 0
	if len(profiles) > 1 && pick != nil {
		if candidate := pick(len(profiles)); candidate >= 0 && candidate < len(profiles) {
			idx = candidate
		}
	}
	return profiles[idx]
}

func collectImpersonationProfiles(raw string) []ImpersonationProfile {
	tokens := parseImpersonationPool(raw)
	profiles := make([]ImpersonationProfile, 0, len(tokens))
	for _, token := range tokens {
		if profile, ok := profileFromToken(token); ok {
			profiles = append(profiles, profile)
		}
	}
	return profiles
}

func parseImpersonationPool(raw string) []string {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return nil
	}
	tokens := strings.FieldsFunc(raw, func(r rune) bool {
		return r == ',' || r == ';' || r == '\n' || r == '\r' || r == '|'
	})
	if len(tokens) == 0 {
		return []string{raw}
	}
	cleaned := make([]string, 0, len(tokens))
	for _, token := range tokens {
		if token = strings.TrimSpace(token); token != "" {
			cleaned = append(cleaned, token)
		}
	}
	if len(cleaned) == 0 {
		return nil
	}
	return cleaned
}

func profileFromToken(token string) (ImpersonationProfile, bool) {
	token = strings.TrimSpace(token)
	if token == "" {
		return ImpersonationProfile{}, false
	}
	if profile, ok := profileFromChromeLabel(token); ok {
		return profile, true
	}
	if profile, ok := profileFromChromeVersionToken(token); ok {
		return profile, true
	}
	return ImpersonationProfile{}, false
}

func profileFromChromeLabel(token string) (ImpersonationProfile, bool) {
	match := chromeLabelPattern.FindStringSubmatch(strings.ToLower(token))
	if len(match) != 2 {
		return ImpersonationProfile{}, false
	}
	version, err := strconv.Atoi(match[1])
	if err != nil || version <= 0 {
		return ImpersonationProfile{}, false
	}
	return profileFromChromeVersion(version), true
}

func profileFromChromeVersionToken(token string) (ImpersonationProfile, bool) {
	match := chromeVersionPattern.FindStringSubmatch(token)
	if len(match) != 2 {
		return ImpersonationProfile{}, false
	}
	version, err := strconv.Atoi(match[1])
	if err != nil || version <= 0 {
		return ImpersonationProfile{}, false
	}
	return profileFromChromeVersion(version), true
}

func profileFromChromeVersion(version int) ImpersonationProfile {
	return ImpersonationProfile{
		Name:      fmt.Sprintf("chrome%d", version),
		UserAgent: chromeUserAgent(version),
	}
}

func buildDefaultImpersonationProfiles() []ImpersonationProfile {
	profiles := make([]ImpersonationProfile, 0, len(defaultChromeVersions))
	for _, version := range defaultChromeVersions {
		profiles = append(profiles, profileFromChromeVersion(version))
	}
	return profiles
}

func defaultChromeProfile() ImpersonationProfile {
	return defaultImpersonationProfilesList[0]
}

func chromeUserAgent(version int) string {
	return fmt.Sprintf("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/%d.0.0.0 Safari/537.36", version)
}
