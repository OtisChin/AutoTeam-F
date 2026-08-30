package fingerprint

import (
	"fmt"
	"maps"
	"slices"

	"github.com/bogdanfinn/tls-client/profiles"
)

// Profile is the complete browser identity selected for one registration
// attempt. Header slices are copied whenever a profile leaves the registry.
type Profile struct {
	Name              string
	Major             int
	TLSProfile        profiles.ClientProfile
	UserAgent         string
	SecCHUA           string
	SecCHUAMobile     string
	SecCHUAPlatform   string
	AcceptLanguage    string
	HeaderOrder       []string
	PseudoHeaderOrder []string
}

var supportedProfileNames = []string{"chrome144", "chrome146", "chrome150"}

var chromeHeaderOrder = []string{
	"content-length",
	"sec-ch-ua-platform",
	"user-agent",
	"sec-ch-ua",
	"content-type",
	"sec-ch-ua-mobile",
	"accept",
	"origin",
	"sec-fetch-site",
	"sec-fetch-mode",
	"sec-fetch-dest",
	"referer",
	"accept-encoding",
	"accept-language",
	"cookie",
	"priority",
}

var chromePseudoHeaderOrder = []string{":method", ":authority", ":scheme", ":path"}

var registry = map[string]Profile{
	"chrome144": newChromeProfile("chrome144", 144, profiles.Chrome_144),
	"chrome146": newChromeProfile("chrome146", 146, profiles.Chrome_146),
	"chrome150": newChromeProfile("chrome150", 150, profiles.Chrome_150),
}

func newChromeProfile(name string, major int, tlsProfile profiles.ClientProfile) Profile {
	return Profile{
		Name:            name,
		Major:           major,
		TLSProfile:      tlsProfile,
		UserAgent:       fmt.Sprintf("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/%d.0.0.0 Safari/537.36", major),
		SecCHUA:         fmt.Sprintf(`"Not_A Brand";v="99", "Chromium";v="%d", "Google Chrome";v="%d"`, major, major),
		SecCHUAMobile:   "?0",
		SecCHUAPlatform: `"Windows"`,
		AcceptLanguage:  "en-US,en;q=0.9",
		HeaderOrder:     append([]string(nil), chromeHeaderOrder...),
		PseudoHeaderOrder: append(
			[]string(nil),
			chromePseudoHeaderOrder...,
		),
	}
}

func (p Profile) clone() Profile {
	p.TLSProfile = cloneTLSProfile(p.TLSProfile)
	p.HeaderOrder = append([]string(nil), p.HeaderOrder...)
	p.PseudoHeaderOrder = append([]string(nil), p.PseudoHeaderOrder...)
	return p
}

func cloneTLSProfile(source profiles.ClientProfile) profiles.ClientProfile {
	headerPriority := source.GetHeaderPriority()
	if headerPriority != nil {
		cloned := *headerPriority
		headerPriority = &cloned
	}

	return profiles.NewClientProfile(
		source.GetClientHelloId(),
		maps.Clone(source.GetSettings()),
		slices.Clone(source.GetSettingsOrder()),
		slices.Clone(source.GetPseudoHeaderOrder()),
		source.GetConnectionFlow(),
		slices.Clone(source.GetPriorities()),
		headerPriority,
		source.GetStreamID(),
		source.GetAllowHTTP(),
		maps.Clone(source.GetHttp3Settings()),
		slices.Clone(source.GetHttp3SettingsOrder()),
		source.GetHttp3PriorityParam(),
		slices.Clone(source.GetHttp3PseudoHeaderOrder()),
		source.GetHttp3SendGreaseFrames(),
	)
}

// Lookup resolves one exact supported profile name.
func Lookup(name string) (Profile, bool) {
	profile, ok := registry[name]
	if !ok {
		return Profile{}, false
	}
	return profile.clone(), true
}

// SupportedNames returns the immutable registry order used by the default
// pool and readiness diagnostics.
func SupportedNames() []string {
	return append([]string(nil), supportedProfileNames...)
}
