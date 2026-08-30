package fingerprint

import (
	"fmt"
	"reflect"
	"strings"
	"testing"

	"github.com/bogdanfinn/tls-client/profiles"
)

func TestLookupUsesConcreteTLSClientProfiles(t *testing.T) {
	tests := []struct {
		name  string
		major int
		want  profiles.ClientProfile
	}{
		{name: "chrome144", major: 144, want: profiles.Chrome_144},
		{name: "chrome146", major: 146, want: profiles.Chrome_146},
		{name: "chrome150", major: 150, want: profiles.Chrome_150},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, ok := Lookup(tt.name)
			if !ok {
				t.Fatalf("Lookup(%q) was not found", tt.name)
			}
			if got.Name != tt.name || got.Major != tt.major {
				t.Fatalf("profile=%#v", got)
			}
			if got.TLSProfile.GetClientHelloStr() != tt.want.GetClientHelloStr() {
				t.Fatalf("%s TLS profile=%q want=%q", tt.name, got.TLSProfile.GetClientHelloStr(), tt.want.GetClientHelloStr())
			}
			if !strings.Contains(got.UserAgent, fmt.Sprintf("Chrome/%d.0.0.0", tt.major)) {
				t.Fatalf("%s user-agent=%q", tt.name, got.UserAgent)
			}
			if !strings.Contains(got.SecCHUA, fmt.Sprintf(`v="%d"`, tt.major)) {
				t.Fatalf("%s sec-ch-ua=%q", tt.name, got.SecCHUA)
			}
			if got.SecCHUAMobile != "?0" || got.SecCHUAPlatform != `"Windows"` {
				t.Fatalf("%s client hints=%q %q", tt.name, got.SecCHUAMobile, got.SecCHUAPlatform)
			}
			if !reflect.DeepEqual(got.PseudoHeaderOrder, []string{":method", ":authority", ":scheme", ":path"}) {
				t.Fatalf("%s pseudo-header order=%v", tt.name, got.PseudoHeaderOrder)
			}
		})
	}
}

func TestLookupReturnsIndependentHeaderSlices(t *testing.T) {
	first, ok := Lookup("chrome144")
	if !ok {
		t.Fatal("chrome144 was not found")
	}
	first.HeaderOrder[0] = "mutated"
	first.PseudoHeaderOrder[0] = ":mutated"

	second, ok := Lookup("chrome144")
	if !ok {
		t.Fatal("chrome144 was not found on second lookup")
	}
	if second.HeaderOrder[0] == "mutated" || second.PseudoHeaderOrder[0] == ":mutated" {
		t.Fatalf("registry slices were mutated: %#v", second)
	}
}

func TestLookupReturnsIndependentTLSProfileState(t *testing.T) {
	first, ok := Lookup("chrome146")
	if !ok {
		t.Fatal("chrome146 was not found")
	}
	settings := first.TLSProfile.GetSettings()
	for key, value := range settings {
		settings[key] = value + 1
		break
	}
	pseudoHeaders := first.TLSProfile.GetPseudoHeaderOrder()
	pseudoHeaders[0] = ":mutated"

	second, ok := Lookup("chrome146")
	if !ok {
		t.Fatal("chrome146 was not found on second lookup")
	}
	if reflect.DeepEqual(second.TLSProfile.GetSettings(), settings) {
		t.Fatalf("TLS settings were shared: %v", settings)
	}
	if second.TLSProfile.GetPseudoHeaderOrder()[0] == ":mutated" {
		t.Fatalf("TLS pseudo-header order was shared: %v", second.TLSProfile.GetPseudoHeaderOrder())
	}
}

func TestSupportedNamesAndUnknownLookup(t *testing.T) {
	if got := SupportedNames(); !reflect.DeepEqual(got, []string{"chrome144", "chrome146", "chrome150"}) {
		t.Fatalf("SupportedNames()=%v", got)
	}
	if _, ok := Lookup("chrome147"); ok {
		t.Fatal("unsupported profile unexpectedly resolved")
	}
}
