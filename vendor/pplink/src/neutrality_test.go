package pplink

import (
	"crypto/sha256"
	"debug/buildinfo"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"testing"
)

func retiredMarkerPatterns() []*regexp.Regexp {
	retiredSnake := strings.Join([]string{"go", "pay", "_", "pro"}, "")
	retiredKebab := strings.Join([]string{"go", "pay", "-", "pro"}, "")
	retiredLegacy := strings.Join([]string{"cn", "go", "pay"}, "")
	retiredDisplay := strings.Join([]string{"Go", "Pay", " ", "Pro"}, "")
	retiredCamelType := strings.Join([]string{"Go", "Pay", "Pro"}, "")
	retiredCamelValue := strings.Join([]string{"go", "pay", "Pro"}, "")
	patterns := []*regexp.Regexp{
		regexp.MustCompile(
			`(?i)` + regexp.QuoteMeta(retiredSnake) + `(?:_|\b)|` +
				regexp.QuoteMeta(retiredKebab) + `(?:-|\b)|` +
				regexp.QuoteMeta(retiredLegacy) + `|` +
				regexp.QuoteMeta(retiredDisplay) + `\b`,
		),
		regexp.MustCompile(
			regexp.QuoteMeta(retiredCamelType) + `[A-Z]|\b` + regexp.QuoteMeta(retiredCamelValue) + `\b`,
		),
	}
	for _, parts := range [][]string{
		{"go", "pay", "_pin"},
		{"proxy", "_id"},
		{"rebind", "_email"},
		{"hero", "_sms"},
		{"number", "_pool_file"},
		{"email", "_pool_file"},
		{"provided", "_tokens_file"},
		{"balance", "_poll_interval_sec"},
		{"balance", "_threshold_idr"},
	} {
		patterns = append(patterns, regexp.MustCompile(`(?i)\b`+regexp.QuoteMeta(strings.Join(parts, ""))+`\b`))
	}
	return patterns
}

func containsRetiredMarker(data []byte) bool {
	for _, pattern := range retiredMarkerPatterns() {
		if pattern.Match(data) {
			return true
		}
	}
	return false
}

func TestSourceTreeExcludesRetiredSubsystemMarkers(t *testing.T) {
	moduleData, err := os.ReadFile("go.mod")
	if err != nil {
		t.Fatal(err)
	}
	if firstLine := strings.SplitN(string(moduleData), "\n", 2)[0]; firstLine != "module autotoken-pplink" {
		t.Fatalf("module line = %q", firstLine)
	}

	err = filepath.WalkDir("..", func(path string, entry fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if entry.IsDir() {
			return nil
		}
		data, readErr := os.ReadFile(path)
		if readErr != nil {
			return readErr
		}
		if containsRetiredMarker(data) {
			t.Errorf("%s contains a retired marker assembled by the test", path)
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
}

func TestRetiredMarkerMatcherAllowsOrdinaryProxyIdentifier(t *testing.T) {
	ordinaryIdentifier := strings.Join([]string{"go", "pay", "Proxy"}, "")
	if containsRetiredMarker([]byte(ordinaryIdentifier)) {
		t.Fatalf("ordinary identifier %q was rejected", ordinaryIdentifier)
	}
}

func TestRetiredMarkerMatcherFindsLegacyPrefixesWithSuffixes(t *testing.T) {
	for _, value := range []string{
		strings.Join([]string{"CN", "go", "pay", "Backup"}, ""),
		strings.Join([]string{"cn", "go", "pay", "2"}, ""),
	} {
		if !containsRetiredMarker([]byte(value)) {
			t.Errorf("legacy marker with suffix was missed: %q", value)
		}
	}
}

func TestBundledExecutableMatchesDeterministicBuildContract(t *testing.T) {
	bundledPath := filepath.Join("..", "pplink.exe")
	info := assertExecutableBuildContract(t, bundledPath)
	assertEmptyBuildID(t, bundledPath)

	t.Run("reproducible with embedded toolchain", func(t *testing.T) {
		if info.GoVersion != runtime.Version() {
			t.Skipf("bundled toolchain %s differs from current %s; buildinfo and raw scan still verified", info.GoVersion, runtime.Version())
		}
		tempDir := t.TempDir()
		firstPath := filepath.Join(tempDir, "pplink-first.exe")
		secondPath := filepath.Join(tempDir, "pplink-second.exe")
		buildPPlink(t, firstPath)
		buildPPlink(t, secondPath)
		assertEmptyBuildID(t, firstPath)
		assertEmptyBuildID(t, secondPath)

		bundledHash := fileSHA256(t, bundledPath)
		firstHash := fileSHA256(t, firstPath)
		secondHash := fileSHA256(t, secondPath)
		if firstHash != secondHash {
			t.Fatalf("consecutive builds differ: %s != %s", firstHash, secondHash)
		}
		if bundledHash != firstHash {
			t.Fatalf("bundled executable is stale: bundled=%s rebuilt=%s", bundledHash, firstHash)
		}
	})
}

func assertExecutableBuildContract(t *testing.T, path string) *buildinfo.BuildInfo {
	t.Helper()
	info, err := buildinfo.ReadFile(path)
	if err != nil {
		t.Fatalf("read buildinfo for %s: %v", path, err)
	}
	if info.Path != "autotoken-pplink/cmd/pplink" || info.Main.Path != "autotoken-pplink" {
		t.Fatalf("neutral module mismatch: path=%q module=%q", info.Path, info.Main.Path)
	}
	settings := make(map[string]string, len(info.Settings))
	for _, setting := range info.Settings {
		settings[setting.Key] = setting.Value
		if strings.HasPrefix(setting.Key, "vcs") {
			t.Errorf("unexpected VCS build setting %s=%s", setting.Key, setting.Value)
		}
	}
	for key, want := range map[string]string{
		"CGO_ENABLED": "0",
		"GOOS":        "windows",
		"GOARCH":      "amd64",
		"GOAMD64":     "v1",
		"-trimpath":   "true",
	} {
		if got := settings[key]; got != want {
			t.Errorf("build setting %s=%q, want %q", key, got, want)
		}
	}
	return info
}

func buildPPlink(t *testing.T, outputPath string) {
	t.Helper()
	args := []string{
		"build",
		"-mod=readonly",
		"-trimpath",
		"-buildvcs=false",
		"-tags=netgo,osusergo",
		"-ldflags=-s -w -buildid=",
		"-o",
		outputPath,
		"./cmd/pplink",
	}
	command := exec.Command("go", args...)
	command.Dir = "."
	command.Env = deterministicBuildEnvironment()
	if output, err := command.CombinedOutput(); err != nil {
		t.Fatalf("go %s failed: %v\n%s", strings.Join(args, " "), err, output)
	}
}

func deterministicBuildEnvironment() []string {
	overrides := map[string]string{
		"CGO_ENABLED":       "0",
		"GOOS":              "windows",
		"GOARCH":            "amd64",
		"GOAMD64":           "v1",
		"GOWORK":            "off",
		"GOFLAGS":           "",
		"SOURCE_DATE_EPOCH": "0",
	}
	environment := make([]string, 0, len(os.Environ())+len(overrides))
	for _, entry := range os.Environ() {
		key := strings.ToUpper(strings.SplitN(entry, "=", 2)[0])
		if _, overridden := overrides[key]; !overridden {
			environment = append(environment, entry)
		}
	}
	for _, key := range []string{"CGO_ENABLED", "GOOS", "GOARCH", "GOAMD64", "GOWORK", "GOFLAGS", "SOURCE_DATE_EPOCH"} {
		environment = append(environment, key+"="+overrides[key])
	}
	return environment
}

func assertEmptyBuildID(t *testing.T, path string) {
	t.Helper()
	output, err := exec.Command("go", "tool", "buildid", path).CombinedOutput()
	if err != nil {
		t.Fatalf("go tool buildid %s: %v\n%s", path, err, output)
	}
	if buildID := strings.TrimSpace(string(output)); buildID != "" {
		t.Fatalf("build ID for %s = %q, want empty", path, buildID)
	}
}

func fileSHA256(t *testing.T, path string) string {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return fmt.Sprintf("%x", sha256.Sum256(data))
}

func TestBuildScriptPinsDeterministicStaticWindowsTarget(t *testing.T) {
	data, err := os.ReadFile(filepath.Join("..", "build.ps1"))
	if err != nil {
		t.Fatal(err)
	}
	script := string(data)
	for _, required := range []string{
		"CGO_ENABLED",
		"GOOS",
		"GOARCH",
		"GOAMD64",
		"GOWORK",
		"-mod=readonly",
		"-trimpath",
		"-buildvcs=false",
		"-ldflags=-s -w -buildid=",
		"./cmd/pplink",
		"pplink.exe",
	} {
		if !strings.Contains(script, required) {
			t.Errorf("build.ps1 missing %q", required)
		}
	}
	for name, value := range map[string]string{
		"CGO_ENABLED": "0",
		"GOOS":        "windows",
		"GOARCH":      "amd64",
		"GOAMD64":     "v1",
		"GOWORK":      "off",
	} {
		assignment := "$env:" + name + " = '" + value + "'"
		if !strings.Contains(script, assignment) {
			t.Errorf("build.ps1 missing exact assignment %q", assignment)
		}
	}
}

func TestReadmeDocumentsTheCLIAndMinimalConfig(t *testing.T) {
	data, err := os.ReadFile(filepath.Join("..", "README.md"))
	if err != nil {
		t.Fatal(err)
	}
	readme := string(data)
	for _, flagName := range []string{
		"-config",
		"-entity",
		"-max-retry",
		"-mode",
		"-proxy",
		"-retry-wait",
		"-stop-at-pm-redirects",
		"-token",
		"-us-proxy",
	} {
		if !strings.Contains(readme, "`"+flagName+"`") {
			t.Errorf("README missing %s", flagName)
		}
	}
	for _, configKey := range []string{"proxy_jp", "proxy_us"} {
		if !strings.Contains(readme, `"`+configKey+`"`) {
			t.Errorf("README missing config key %s", configKey)
		}
	}
	for _, exitContract := range []string{
		"Business-input failures and exhausted retries exit with code `1`.",
		"Flag syntax errors exit with code `2`.",
	} {
		if !strings.Contains(readme, exitContract) {
			t.Errorf("README missing exit contract %q", exitContract)
		}
	}
}
