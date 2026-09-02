package mailbridge

import (
	"encoding/json"
	"regexp"
	"strings"
	"time"
)

var otpPattern = regexp.MustCompile(`\b\d{6}\b`)
var staticCardStartPattern = regexp.MustCompile(`(?is)<(?:article|div)\b[^>]*class=["'][^"']*\bcard\b[^"']*["'][^>]*>`)
var cardFieldPattern = regexp.MustCompile(`(?is)<[^>]*class=["'][^"']*\b(fr|su|dt|bd)\b[^"']*["'][^>]*>(.*?)</[^>]+>`)
var htmlTagPattern = regexp.MustCompile(`(?is)<[^>]+>`)
var htmlCommentPattern = regexp.MustCompile(`(?is)<!--.*?-->`)
var htmlScriptPattern = regexp.MustCompile(`(?is)<script\b[^>]*>.*?</script>`)
var htmlStylePattern = regexp.MustCompile(`(?is)<style\b[^>]*>.*?</style>`)

func ExtractOTP(payload []byte) string {
	return ExtractOTPWithOptions(payload, WaitOptions{})
}

func ExtractOTPWithOptions(payload []byte, opts WaitOptions) string {
	if code := extractStaticCardOTP(payload, opts); code != "" {
		return code
	}
	var data any
	if json.Unmarshal(payload, &data) == nil {
		if code := findCode(data); code != "" {
			if opts.ExcludeCodes[code] {
				return ""
			}
			return code
		}
	}
	if opts.IssuedAfterUnix > 0 && looksLikeHTML(payload) {
		return ""
	}
	code := otpPattern.FindString(string(payload))
	if opts.ExcludeCodes[code] {
		return ""
	}
	return code
}

func extractStaticCardOTP(payload []byte, opts WaitOptions) string {
	html := string(payload)
	starts := staticCardStartPattern.FindAllStringIndex(html, -1)
	if len(starts) == 0 {
		return ""
	}
	for index, start := range starts {
		end := len(html)
		if index+1 < len(starts) {
			end = starts[index+1][0]
		}
		card := html[start[0]:end]
		fields := map[string]string{}
		for _, match := range cardFieldPattern.FindAllStringSubmatch(card, -1) {
			fields[strings.ToLower(match[1])] += " " + stripHTML(match[2])
		}
		combined := strings.ToLower(fields["fr"] + " " + fields["su"] + " " + fields["bd"])
		if !strings.Contains(combined, "openai") && !strings.Contains(combined, "chatgpt") {
			continue
		}
		if opts.IssuedAfterUnix > 0 {
			timestamp := parseUnixTime(fields["dt"])
			if timestamp > 0 && timestamp+30 < opts.IssuedAfterUnix {
				continue
			}
		}
		code := otpPattern.FindString(stripHTML(card))
		if code == "" || opts.ExcludeCodes[code] {
			continue
		}
		return code
	}
	return ""
}

func looksLikeHTML(payload []byte) bool {
	text := strings.ToLower(strings.TrimSpace(string(payload)))
	return strings.Contains(text, "<html") ||
		strings.Contains(text, "<body") ||
		strings.Contains(text, "<main") ||
		strings.Contains(text, "<article")
}

func stripHTML(raw string) string {
	raw = htmlScriptPattern.ReplaceAllString(raw, " ")
	raw = htmlStylePattern.ReplaceAllString(raw, " ")
	raw = htmlCommentPattern.ReplaceAllString(raw, " ")
	text := htmlTagPattern.ReplaceAllString(raw, " ")
	text = strings.NewReplacer("&nbsp;", " ", "&amp;", "&", "&lt;", "<", "&gt;", ">").Replace(text)
	return strings.Join(strings.Fields(text), " ")
}

func parseUnixTime(raw string) int64 {
	text := strings.TrimSpace(raw)
	if text == "" {
		return 0
	}
	for _, layout := range []string{
		"2006-01-02 15:04:05",
		time.RFC3339,
		time.RFC1123Z,
		"Mon, 02 Jan 2006 15:04:05 -0700 (MST)",
		"2006-01-02T15:04:05",
		"2006/01/02 15:04:05",
	} {
		if ts, err := time.ParseInLocation(layout, text, time.Local); err == nil {
			return ts.Unix()
		}
	}
	return 0
}

func findCode(value any) string {
	switch typed := value.(type) {
	case map[string]any:
		for _, key := range []string{"code", "otp", "verification_code", "verificationCode"} {
			if raw, ok := typed[key].(string); ok {
				if code := otpPattern.FindString(raw); code != "" {
					return code
				}
			}
		}
		for _, raw := range typed {
			if code := findCode(raw); code != "" {
				return code
			}
		}
	case []any:
		for _, raw := range typed {
			if code := findCode(raw); code != "" {
				return code
			}
		}
	case string:
		return otpPattern.FindString(typed)
	}
	return ""
}
