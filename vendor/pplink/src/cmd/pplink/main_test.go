package main

import (
	"bytes"
	"errors"
	"flag"
	"io"
	"reflect"
	"strings"
	"testing"
	"time"

	"autotoken-pplink/internal/config"
	"autotoken-pplink/internal/paypal"
)

type fakeSession struct {
	link     *paypal.PayPalLink
	err      error
	stopAtPM bool
	entity   string
}

func (s *fakeSession) SetStopAtPMRedirects(stop bool)   { s.stopAtPM = stop }
func (s *fakeSession) SetProcessorEntity(entity string) { s.entity = entity }
func (s *fakeSession) ExtractPayPalLink() (*paypal.PayPalLink, error) {
	return s.link, s.err
}

func successfulDeps(captured *[][3]string) appDeps {
	return appDeps{
		loadConfig: config.Load,
		parseToken: paypal.ParseGPTToken,
		newSession: func(_ paypal.GPTToken, mode, jpProxy, usProxy string, _ func(string, ...any)) (payPalSession, error) {
			if captured != nil {
				*captured = append(*captured, [3]string{mode, jpProxy, usProxy})
			}
			return &fakeSession{link: &paypal.PayPalLink{FullURL: "https://pm-redirects.stripe.com/authorize/demo"}}, nil
		},
		rotateSID: func(proxy string) string { return proxy + "-rotated" },
		sleep:     func(time.Duration) {},
	}
}

func TestFlagSurfaceAndDefaults(t *testing.T) {
	fs, opts := newFlagSet(io.Discard)
	var names []string
	fs.VisitAll(func(f *flag.Flag) { names = append(names, f.Name) })
	wantNames := []string{
		"config",
		"entity",
		"max-retry",
		"mode",
		"proxy",
		"retry-wait",
		"stop-at-pm-redirects",
		"token",
		"us-proxy",
	}
	if !reflect.DeepEqual(names, wantNames) {
		t.Fatalf("flags = %v, want %v", names, wantNames)
	}
	if opts.configPath != "config.json" || opts.mode != "us" || opts.entity != "" || opts.proxy != "" || opts.usProxy != "" || opts.token != "" || opts.maxRetry != 0 || opts.retryWait != 0 || opts.stopAtPMRedirects {
		t.Fatalf("defaults = %#v", opts)
	}
}

func TestHelpDocumentsBRModeEntityAndProxyRouting(t *testing.T) {
	var help bytes.Buffer
	flags, _ := newFlagSet(&help)
	flags.PrintDefaults()
	for _, want := range []string{
		"br(BR/BRL/custom,JP 单代理)",
		"eu/br→openai_ie",
		"EU/BR 模式留空只走 JP",
	} {
		if !strings.Contains(help.String(), want) {
			t.Fatalf("help missing %q:\n%s", want, help.String())
		}
	}
}

func TestFlagsOverrideConfigAndEmptyFlagsKeepConfig(t *testing.T) {
	captured := make([][3]string, 0, 1)
	deps := successfulDeps(&captured)
	deps.loadConfig = func(string) (*config.Config, error) {
		return &config.Config{ProxyJP: "socks5://config-jp", ProxyUS: "socks5://config-us"}, nil
	}

	var stderr bytes.Buffer
	exitCode := run([]string{
		"-proxy", "socks5://flag-jp",
		"-us-proxy", "socks5://flag-us",
		"-token", "opaque",
	}, strings.NewReader(""), &stderr, deps)
	if exitCode != 0 {
		t.Fatalf("run() exit = %d, stderr=%s", exitCode, stderr.String())
	}
	want := [][3]string{{"us", "socks5://flag-jp", "socks5://flag-us"}}
	if !reflect.DeepEqual(captured, want) {
		t.Fatalf("sessions = %#v, want %#v", captured, want)
	}

	captured = captured[:0]
	stderr.Reset()
	exitCode = run([]string{"-token", "opaque"}, strings.NewReader(""), &stderr, deps)
	if exitCode != 0 {
		t.Fatalf("config-only run() exit = %d, stderr=%s", exitCode, stderr.String())
	}
	want = [][3]string{{"us", "socks5://config-jp", "socks5://config-us"}}
	if !reflect.DeepEqual(captured, want) {
		t.Fatalf("config-only sessions = %#v, want %#v", captured, want)
	}
}

func TestStopAndEntityFlagsReachSession(t *testing.T) {
	created := &fakeSession{link: &paypal.PayPalLink{FullURL: "https://pm-redirects.stripe.com/authorize/demo"}}
	deps := successfulDeps(nil)
	deps.newSession = func(_ paypal.GPTToken, _, _, _ string, _ func(string, ...any)) (payPalSession, error) {
		return created, nil
	}

	var stderr bytes.Buffer
	exitCode := run([]string{
		"-stop-at-pm-redirects",
		"-entity", "openai_test",
		"-token", "opaque",
	}, strings.NewReader(""), &stderr, deps)
	if exitCode != 0 {
		t.Fatalf("run() exit = %d, stderr=%s", exitCode, stderr.String())
	}
	if !created.stopAtPM || created.entity != "openai_test" {
		t.Fatalf("session flags = stop:%v entity:%q", created.stopAtPM, created.entity)
	}
}

func TestMissingConfigDoesNotBlockFlagOnlyInvocation(t *testing.T) {
	captured := make([][3]string, 0, 1)
	deps := successfulDeps(&captured)
	deps.loadConfig = func(string) (*config.Config, error) { return nil, errors.New("missing") }

	var stderr bytes.Buffer
	exitCode := run([]string{
		"-config", `Z:\missing\config.json`,
		"-mode", "us",
		"-proxy", "http://127.0.0.1:1",
		"-us-proxy", "http://127.0.0.1:2",
		"-max-retry", "1",
		"-retry-wait", "0",
		"-stop-at-pm-redirects",
		"-token", "not-a-jwt",
	}, strings.NewReader(""), &stderr, deps)
	if exitCode != 0 {
		t.Fatalf("run() exit = %d, stderr=%s", exitCode, stderr.String())
	}
	if len(captured) != 1 || captured[0] != [3]string{"us", "http://127.0.0.1:1", "http://127.0.0.1:2"} {
		t.Fatalf("sessions = %#v", captured)
	}
}

func TestMaskProxyRedactsMalformedTrailingAtCredentials(t *testing.T) {
	proxy := "socks5://jp-user:JP-SECRET@"
	masked := maskProxy(proxy)
	for _, secret := range []string{proxy, "jp-user", "JP-SECRET"} {
		if strings.Contains(masked, secret) {
			t.Fatalf("maskProxy leaked %q in %q", secret, masked)
		}
	}
}

func TestRunRedactsMalformedAuthenticatedProxyErrors(t *testing.T) {
	tests := []struct {
		name    string
		jpProxy string
		usProxy string
		secrets []string
	}{
		{
			name:    "malformed jp",
			jpProxy: "socks5://jp-user:JP-SECRET@",
			secrets: []string{"jp-user", "JP-SECRET", "socks5://jp-user:JP-SECRET@"},
		},
		{
			name:    "malformed us",
			jpProxy: "http://127.0.0.1:1",
			usProxy: "socks5://us-user:US-SECRET@",
			secrets: []string{"us-user", "US-SECRET", "socks5://us-user:US-SECRET@"},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var stderr bytes.Buffer
			exitCode := run([]string{
				"-config", `Z:\missing\config.json`,
				"-mode", "us",
				"-proxy", tt.jpProxy,
				"-us-proxy", tt.usProxy,
				"-max-retry", "1",
				"-token", "opaque",
			}, strings.NewReader(""), &stderr, productionDeps())
			if exitCode != 1 {
				t.Fatalf("run() exit = %d, stderr=%s", exitCode, stderr.String())
			}
			for _, secret := range tt.secrets {
				if strings.Contains(stderr.String(), secret) {
					t.Fatalf("run stderr leaked %q: %s", secret, stderr.String())
				}
			}
		})
	}
}

func TestEUAndBRIgnoreUSProxy(t *testing.T) {
	for _, mode := range []string{"eu", "br"} {
		t.Run(mode, func(t *testing.T) {
			captured := make([][3]string, 0, 1)
			deps := successfulDeps(&captured)
			deps.loadConfig = func(string) (*config.Config, error) {
				return &config.Config{ProxyJP: "jp", ProxyUS: "us"}, nil
			}
			var stderr bytes.Buffer
			if exitCode := run([]string{"-mode", mode, "-token", "opaque"}, strings.NewReader(""), &stderr, deps); exitCode != 0 {
				t.Fatalf("run() exit = %d, stderr=%s", exitCode, stderr.String())
			}
			if len(captured) != 1 || captured[0] != [3]string{mode, "jp", ""} {
				t.Fatalf("sessions = %#v", captured)
			}
			if !strings.Contains(stderr.String(), strings.ToUpper(mode)+" 模式忽略 us-proxy") {
				t.Fatalf("stderr missing ignored-proxy log: %s", stderr.String())
			}
		})
	}
}

func TestRetriesRotateEachOriginalProxyIndependently(t *testing.T) {
	var sessions [][3]string
	var rotateInputs []string
	deps := successfulDeps(nil)
	deps.loadConfig = func(string) (*config.Config, error) {
		return &config.Config{ProxyJP: "jp-sid-BASE", ProxyUS: "us-sid-BASE"}, nil
	}
	deps.rotateSID = func(proxy string) string {
		rotateInputs = append(rotateInputs, proxy)
		return proxy + "-rotated-" + string(rune('0'+len(rotateInputs)))
	}
	deps.newSession = func(_ paypal.GPTToken, mode, jpProxy, usProxy string, _ func(string, ...any)) (payPalSession, error) {
		sessions = append(sessions, [3]string{mode, jpProxy, usProxy})
		return &fakeSession{err: errors.New("try again")}, nil
	}

	var stderr bytes.Buffer
	exitCode := run([]string{"-token", "opaque", "-max-retry", "3"}, strings.NewReader(""), &stderr, deps)
	if exitCode != 1 {
		t.Fatalf("run() exit = %d, want 1", exitCode)
	}
	if !reflect.DeepEqual(rotateInputs, []string{"jp-sid-BASE", "us-sid-BASE", "jp-sid-BASE", "us-sid-BASE"}) {
		t.Fatalf("rotate inputs = %#v", rotateInputs)
	}
	wantSessions := [][3]string{
		{"us", "jp-sid-BASE", "us-sid-BASE"},
		{"us", "jp-sid-BASE-rotated-1", "us-sid-BASE-rotated-2"},
		{"us", "jp-sid-BASE-rotated-3", "us-sid-BASE-rotated-4"},
	}
	if !reflect.DeepEqual(sessions, wantSessions) {
		t.Fatalf("sessions = %#v, want %#v", sessions, wantSessions)
	}
}

func TestOutputAndExitContract(t *testing.T) {
	deps := successfulDeps(nil)
	var stderr bytes.Buffer
	if exitCode := run([]string{"-token", "opaque"}, strings.NewReader(""), &stderr, deps); exitCode != 0 {
		t.Fatalf("success exit = %d", exitCode)
	}
	for _, want := range []string{"pplink #1", "JP proxy:", "US proxy:", "Authorize URL: https://pm-redirects.stripe.com/authorize/demo"} {
		if !strings.Contains(stderr.String(), want) {
			t.Fatalf("success output missing %q: %s", want, stderr.String())
		}
	}

	deps.newSession = func(_ paypal.GPTToken, _, _, _ string, _ func(string, ...any)) (payPalSession, error) {
		return &fakeSession{err: errors.New("checkout failed")}, nil
	}
	stderr.Reset()
	if exitCode := run([]string{"-token", "opaque", "-max-retry", "1"}, strings.NewReader(""), &stderr, deps); exitCode != 1 {
		t.Fatalf("failure exit = %d", exitCode)
	}
	for _, want := range []string{"#1 ❌ checkout failed", "达到最大重试次数 1,放弃"} {
		if !strings.Contains(stderr.String(), want) {
			t.Fatalf("failure output missing %q: %s", want, stderr.String())
		}
	}
}
