package sentinel

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/dop251/goja"
)

func TestPatchSDKSourceExposesRequiredOldAndCurrentExportsExactlyOnce(t *testing.T) {
	for _, name := range []string{"old", "current"} {
		t.Run(name, func(t *testing.T) {
			source := readSDKFixture(t, name)
			patched, err := PatchSDKSource(source)
			if err != nil {
				t.Fatalf("PatchSDKSource() error=%v", err)
			}
			for _, export := range []string{
				"globalThis.SentinelSDK=",
				"globalThis.__debugP=",
				".__debug_n=",
				".__debug_bindProof=",
			} {
				if count := strings.Count(string(patched), export); count != 1 {
					t.Fatalf("export %q count=%d\n%s", export, count, patched)
				}
			}
			if strings.Contains(string(patched), "var SentinelSDK=") {
				t.Fatalf("local SentinelSDK export remains:\n%s", patched)
			}

			vm := goja.New()
			if _, err := vm.RunString(string(patched)); err != nil {
				t.Fatalf("patched SDK execution error=%v", err)
			}
			proof := vm.Get("__debugP")
			if proof == nil || goja.IsUndefined(proof) || goja.IsNull(proof) {
				t.Fatal("globalThis.__debugP is unavailable")
			}
			if _, ok := goja.AssertFunction(proof.ToObject(vm).Get("getRequirementsToken")); !ok {
				t.Fatal("proof requirements function is unavailable")
			}
			sdk := vm.Get("SentinelSDK").ToObject(vm)
			for _, field := range []string{"__debug_n", "__debug_bindProof"} {
				if _, ok := goja.AssertFunction(sdk.Get(field)); !ok {
					t.Fatalf("SentinelSDK.%s is unavailable", field)
				}
			}
		})
	}
}

func TestPatchSDKSourceRejectsMissingOrAmbiguousSemanticAnchors(t *testing.T) {
	old := string(readSDKFixture(t, "old"))
	tests := []struct {
		name   string
		source string
	}{
		{name: "empty", source: ""},
		{name: "no semantic layout", source: "var SentinelSDK={};"},
		{name: "duplicate complete SDK", source: old + "\n" + old},
		{name: "duplicate proof instance", source: strings.Replace(old, "var P=new _;", "var P=new _;var Q=new _;", 1)},
		{name: "duplicate proof WeakMap", source: strings.Replace(old, "const I=new WeakMap;", "const I=new WeakMap;const J=new WeakMap;", 1)},
		{name: "duplicate proof binding", source: strings.Replace(old, "function $(t)", "function X(t,n){I.set(t,n)}function $(t)", 1)},
		{name: "missing turnstile solver", source: strings.Replace(old, ".dx?await _n(", ".dx?null&&_n(", 1)},
		{name: "missing public export", source: strings.TrimSuffix(old, "t.token=ye,t}({});\n") + "t}({});"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if _, err := PatchSDKSource([]byte(tt.source)); !errors.Is(err, ErrUnsupportedSDK) {
				t.Fatalf("PatchSDKSource() error=%v", err)
			}
		})
	}
}

func TestPatchSDKSourceDoesNotMutateInput(t *testing.T) {
	source := readSDKFixture(t, "old")
	want := append([]byte(nil), source...)
	if _, err := PatchSDKSource(source); err != nil {
		t.Fatal(err)
	}
	if string(source) != string(want) {
		t.Fatal("PatchSDKSource mutated its input")
	}
}

func readSDKFixture(t *testing.T, name string) []byte {
	t.Helper()
	source, err := os.ReadFile(filepath.Join("testdata", "sdk-"+name+".js"))
	if err != nil {
		t.Fatal(err)
	}
	return source
}
