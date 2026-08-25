package mailbridge

import (
	"encoding/json"
	"regexp"
)

var otpPattern = regexp.MustCompile(`\b\d{6}\b`)

func ExtractOTP(payload []byte) string {
	var data any
	if json.Unmarshal(payload, &data) == nil {
		if code := findCode(data); code != "" {
			return code
		}
	}
	return otpPattern.FindString(string(payload))
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
