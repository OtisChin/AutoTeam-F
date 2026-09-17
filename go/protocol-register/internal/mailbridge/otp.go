package mailbridge

import (
	"encoding/base64"
	"encoding/json"
	"net/url"
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
var detailBasePattern = regexp.MustCompile(`(?is)\bvar\s+detailBase\s*=\s*["']([^"']*)["']`)
var detailSuffixPattern = regexp.MustCompile(`(?is)\bvar\s+detailSuffix\s*=\s*["']([^"']*)["']`)
var detailMessageIDPattern = regexp.MustCompile(`(?is)\bdata-id\s*=\s*["']?(\d+)["']?`)
var detailHashIDPattern = regexp.MustCompile(`(?is)href\s*=\s*["']#mail-(\d+)["']`)
var otpContextPattern = regexp.MustCompile(`(?i)(?:temporary\s+(?:openai|chatgpt)\s+(?:login|verification)\s+code|verification\s+code|login\s+code|验证码|认证码)\D{0,80}(\d{6})`)
var mailCardStartPattern = regexp.MustCompile(`(?is)<(?:article|div|li|section)\b[^>]*class=["'][^"']*\bmail-card\b[^"']*["'][^>]*>`)
var mailCardSubjectPattern = regexp.MustCompile(`(?is)<[^>]*class=["'][^"']*\bsubject\b[^"']*["'][^>]*>(.*?)</[^>]+>`)
var mailCardDatePattern = regexp.MustCompile(`(?is)<[^>]*class=["'][^"']*\bdate\b[^"']*["'][^>]*>(.*?)</[^>]+>`)

func ExtractOTP(payload []byte) string {
	return ExtractOTPWithOptions(payload, WaitOptions{})
}

func ExtractOTPWithOptions(payload []byte, opts WaitOptions) string {
	if code := extractStaticCardOTP(payload, opts); code != "" {
		return code
	}
	if code := extractMailCardOTP(payload, opts); code != "" {
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

// extractMailCardOTP parses listing pages such as mail.ai1998.xyz whose
// messages are rendered as <article class="mail-card"> blocks carrying a
// <span class="subject">, <span class="date"> and a rich <div class="body">.
// The generic digit fallback is disabled whenever a freshness filter is set, so
// these cards must be recognised explicitly or every code is treated as stale.
func extractMailCardOTP(payload []byte, opts WaitOptions) string {
	html := string(payload)
	starts := mailCardStartPattern.FindAllStringIndex(html, -1)
	if len(starts) == 0 {
		return ""
	}
	for index, start := range starts {
		end := len(html)
		if index+1 < len(starts) {
			end = starts[index+1][0]
		}
		card := html[start[0]:end]
		subject := stripHTML(firstMatchString(mailCardSubjectPattern, card))
		combined := strings.ToLower(subject + " " + stripHTML(card))
		if !strings.Contains(combined, "openai") && !strings.Contains(combined, "chatgpt") {
			continue
		}
		if opts.IssuedAfterUnix > 0 {
			timestamp := parseUnixTime(stripHTML(firstMatchString(mailCardDatePattern, card)))
			if timestamp > 0 && timestamp+30 < opts.IssuedAfterUnix {
				continue
			}
		}
		if code := extractOTPFromVisibleHTML(card, opts); code != "" {
			return code
		}
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

// DetailURLs derives mail-detail URLs from a receive-code listing page.
//
// Vendors such as icloudyang.com render the list as metadata only and load the
// message body (which carries the OTP) from a JS-derived detail endpoint:
//
//	var detailBase='/message/'; var detailSuffix='/token/email'
//	<a class="item" href="#mail-1771556" data-id="1771556">
//
// Following these links is required because the listing itself contains no code.
func DetailURLs(listURL string, payload []byte) []string {
	html := string(payload)
	base := firstMatchString(detailBasePattern, html)
	suffix := firstMatchString(detailSuffixPattern, html)
	if base == "" || suffix == "" {
		return nil
	}
	ids := []string{}
	seenID := map[string]bool{}
	for _, pattern := range []*regexp.Regexp{detailMessageIDPattern, detailHashIDPattern} {
		for _, match := range pattern.FindAllStringSubmatch(html, -1) {
			id := match[1]
			if id != "" && !seenID[id] {
				seenID[id] = true
				ids = append(ids, id)
			}
		}
	}
	if len(ids) == 0 {
		return nil
	}
	baseURL, err := url.Parse(listURL)
	if err != nil {
		return nil
	}
	urls := make([]string, 0, len(ids))
	seenURL := map[string]bool{}
	for _, id := range ids {
		ref, err := url.Parse(base + id + suffix)
		if err != nil {
			continue
		}
		full := baseURL.ResolveReference(ref).String()
		if full != "" && !seenURL[full] {
			seenURL[full] = true
			urls = append(urls, full)
		}
	}
	return urls
}

// ExtractOTPFromDetail parses a mail-detail response. Vendors return JSON with
// the body embedded as a data URI (base64 HTML); some return plain HTML instead.
func ExtractOTPFromDetail(payload []byte, opts WaitOptions) string {
	var data map[string]any
	if json.Unmarshal(payload, &data) == nil {
		if code := explicitCode(data); code != "" {
			if !opts.ExcludeCodes[code] {
				return code
			}
			return ""
		}
		if opts.IssuedAfterUnix > 0 {
			if received, ok := data["receivedAt"].(string); ok {
				if timestamp := parseUnixTime(received); timestamp > 0 && timestamp+30 < opts.IssuedAfterUnix {
					return ""
				}
			}
		}
		if body, ok := data["body"].(string); ok && body != "" {
			if decoded := decodeDataURI(body); decoded != "" {
				if code := extractOTPFromVisibleHTML(decoded, opts); code != "" {
					return code
				}
			}
		}
	}
	if looksLikeHTML(payload) {
		if code := extractOTPFromVisibleHTML(string(payload), opts); code != "" {
			return code
		}
	}
	return ""
}

func explicitCode(data map[string]any) string {
	for _, key := range []string{"code", "otp", "verification_code", "verificationCode"} {
		raw, ok := data[key].(string)
		if !ok {
			continue
		}
		if code := otpPattern.FindString(raw); code != "" {
			return code
		}
	}
	return ""
}

func extractOTPFromVisibleHTML(html string, opts WaitOptions) string {
	text := stripHTML(html)
	if text == "" {
		return ""
	}
	if match := otpContextPattern.FindStringSubmatch(text); match != nil {
		if !opts.ExcludeCodes[match[1]] {
			return match[1]
		}
	}
	for _, code := range otpPattern.FindAllString(text, -1) {
		if !opts.ExcludeCodes[code] {
			return code
		}
	}
	return ""
}

func decodeDataURI(value string) string {
	text := strings.TrimSpace(value)
	if !strings.HasPrefix(strings.ToLower(text), "data:") {
		return ""
	}
	index := strings.Index(text, ",")
	if index < 0 {
		return ""
	}
	header := strings.ToLower(text[:index])
	payload := text[index+1:]
	if strings.Contains(header, ";base64") {
		if decoded, err := base64.StdEncoding.DecodeString(payload); err == nil {
			return string(decoded)
		}
		if decoded, err := base64.RawStdEncoding.DecodeString(payload); err == nil {
			return string(decoded)
		}
		return ""
	}
	if decoded, err := url.QueryUnescape(payload); err == nil {
		return decoded
	}
	return payload
}

func firstMatchString(pattern *regexp.Regexp, value string) string {
	match := pattern.FindStringSubmatch(value)
	if match == nil {
		return ""
	}
	return match[1]
}
