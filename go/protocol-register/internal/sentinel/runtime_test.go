package sentinel

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"sync"
	"testing"
	"time"

	"autoteam-f/protocol-register/internal/fingerprint"

	"github.com/dop251/goja"
)

func TestRuntimeRequirementsAndSolveOldAndCurrentSDKs(t *testing.T) {
	profile := runtimeTestProfile(t)
	runtime := mustRuntime(t, time.Second)
	for _, name := range []string{"old", "current"} {
		t.Run(name, func(t *testing.T) {
			compiled := compileFixtureSDK(t, name)
			requestP, err := runtime.Requirements(context.Background(), compiled, profile, "did-123")
			if err != nil {
				t.Fatalf("Requirements() error=%v", err)
			}
			if requestP != "requirements-"+name {
				t.Fatalf("request_p=%q", requestP)
			}
			solved, err := runtime.Solve(context.Background(), compiled, profile, SolveInput{
				DeviceID: "did-123",
				RequestP: requestP,
				Challenge: map[string]any{
					"turnstile": map[string]any{"dx": "dx"},
				},
			})
			if err != nil {
				t.Fatalf("Solve() error=%v", err)
			}
			want := SolveOutput{FinalP: "final-" + name, T: requestP + ":dx"}
			if solved != want {
				t.Fatalf("Solve()=%#v, want %#v", solved, want)
			}
		})
	}
}

func TestRuntimeInstallsSelectedProfileAndSDKContext(t *testing.T) {
	source := string(readSDKFixture(t, "old"))
	source = strings.Replace(source, `return "requirements-old"`, `return [navigator.userAgent,document.currentScript.src,document.cookie,navigator.userAgentData.brands[0].version,crypto.getRandomValues(new Uint8Array(8)).length].join("|")`, 1)
	compiled := compileSDKSource(t, "profile123", []byte(source))
	profile := runtimeTestProfile(t)

	requestP, err := mustRuntime(t, time.Second).Requirements(context.Background(), compiled, profile, "did-profile")
	if err != nil {
		t.Fatalf("Requirements() error=%v", err)
	}
	for _, want := range []string{profile.UserAgent, compiled.SDK.URL, "oai-did=did-profile", fmt.Sprint(profile.Major), "|8"} {
		if !strings.Contains(requestP, want) {
			t.Fatalf("request_p=%q does not contain %q", requestP, want)
		}
	}
}

func TestRuntimeCryptoFillsEntireTypedArrayByteView(t *testing.T) {
	source := string(readSDKFixture(t, "old"))
	source = strings.Replace(source, `return "requirements-old"`, `
		globalThis.__sentinelFillRandom=function(view){
			globalThis.__fillLength=view.length;
			for(let index=0;index<view.length;index+=1){view[index]=index+1}
			return view
		};
		const words=new Uint32Array(2);
		const returned=crypto.getRandomValues(words);
		return [globalThis.__fillLength,returned===words,Array.from(new Uint8Array(words.buffer)).join(",")].join("|")
	`, 1)
	compiled := compileSDKSource(t, "randomview123", []byte(source))

	requestP, err := mustRuntime(t, time.Second).Requirements(
		context.Background(), compiled, runtimeTestProfile(t), "did-random",
	)
	if err != nil {
		t.Fatalf("Requirements() error=%v", err)
	}
	if requestP != "8|true|1,2,3,4,5,6,7,8" {
		t.Fatalf("request_p=%q", requestP)
	}
}

func TestRuntimeRejectsRandomTypedArrayOverByteLimit(t *testing.T) {
	source := string(readSDKFixture(t, "old"))
	source = strings.Replace(source, `return "requirements-old"`, `
		crypto.getRandomValues(new Uint32Array(16385));
		return "accepted"
	`, 1)
	compiled := compileSDKSource(t, "randomlimit123", []byte(source))

	_, err := mustRuntime(t, time.Second).Requirements(
		context.Background(), compiled, runtimeTestProfile(t), "did-random-limit",
	)
	if !errors.Is(err, ErrRuntimeExecution) {
		t.Fatalf("Requirements() error=%v", err)
	}
}

func TestRuntimeTextEncoderDecoderRoundTripAndViews(t *testing.T) {
	source := string(readSDKFixture(t, "old"))
	source = strings.Replace(source, `return "requirements-old"`, `
		const roundTrip=new TextDecoder().decode(new TextEncoder().encode("Sentinel 中文 🚀"));
		const bytes=new Uint8Array([120,65,66,121]);
		const view=new DataView(bytes.buffer,1,2);
		return roundTrip+"|"+new TextDecoder().decode(view)
	`, 1)
	compiled := compileSDKSource(t, "textview123", []byte(source))

	requestP, err := mustRuntime(t, time.Second).Requirements(
		context.Background(), compiled, runtimeTestProfile(t), "did-text",
	)
	if err != nil {
		t.Fatalf("Requirements() error=%v", err)
	}
	if requestP != "Sentinel 中文 🚀|AB" {
		t.Fatalf("request_p=%q", requestP)
	}
}

func TestRuntimeRejectsOversizedTextCodecBuffers(t *testing.T) {
	tests := []struct {
		name       string
		javascript string
	}{
		{
			name:       "encoder",
			javascript: `new TextEncoder().encode("x".repeat(2097153));`,
		},
		{
			name:       "decoder typed array",
			javascript: `new TextDecoder().decode(new Uint8Array(2097153));`,
		},
		{
			name:       "decoder array buffer",
			javascript: `new TextDecoder().decode(new ArrayBuffer(2097153));`,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			source := string(readSDKFixture(t, "old"))
			source = strings.Replace(
				source,
				`return "requirements-old"`,
				tt.javascript+`return "accepted"`,
				1,
			)
			compiled := compileSDKSource(t, "textlimit123", []byte(source))

			_, err := mustRuntime(t, time.Second).Requirements(
				context.Background(), compiled, runtimeTestProfile(t), "did-text-limit",
			)
			if !errors.Is(err, ErrRuntimeExecution) {
				t.Fatalf("Requirements() error=%v", err)
			}
		})
	}
}

func TestRuntimeFetchAlwaysFailsClosed(t *testing.T) {
	source := string(readSDKFixture(t, "old"))
	source = strings.Replace(source, `return "requirements-old"`, `return await fetch("https://attacker.example/")`, 1)
	compiled := compileSDKSource(t, "fetch123", []byte(source))
	_, err := mustRuntime(t, time.Second).Requirements(context.Background(), compiled, runtimeTestProfile(t), "did-123")
	if !errors.Is(err, ErrRuntimeExecution) {
		t.Fatalf("Requirements() error=%v", err)
	}
}

func TestRuntimeConvertsHostPanicsToExecutionError(t *testing.T) {
	compiled := mustDirectCompiledSDK(t, `
async function __sentinelRequirements(){
  globalThis.__sentinelFillRandom({});
  return {request_p:"unreachable"};
}
`)
	var recovered any
	var runtimeErr error
	func() {
		defer func() { recovered = recover() }()
		_, runtimeErr = mustRuntime(t, time.Second).Requirements(
			context.Background(), compiled, runtimeTestProfile(t), "did-host-panic",
		)
	}()
	if recovered != nil {
		t.Fatalf("Requirements() leaked host panic: %v", recovered)
	}
	if !errors.Is(runtimeErr, ErrRuntimeExecution) {
		t.Fatalf("Requirements() error=%v", runtimeErr)
	}
}

func TestRuntimeUsesIsolatedVMPerAction(t *testing.T) {
	compiled := mustDirectCompiledSDK(t, `
var actionCounter=(globalThis.actionCounter||0)+1;
async function __sentinelRequirements(){return {request_p:String(actionCounter)}}
`)
	runtime := mustRuntime(t, time.Second)
	profile := runtimeTestProfile(t)
	const workers = 32
	results := make(chan string, workers)
	errorsSeen := make(chan error, workers)
	var wait sync.WaitGroup
	for range workers {
		wait.Add(1)
		go func() {
			defer wait.Done()
			result, err := runtime.Requirements(context.Background(), compiled, profile, "did-isolated")
			results <- result
			errorsSeen <- err
		}()
	}
	wait.Wait()
	close(results)
	close(errorsSeen)
	for err := range errorsSeen {
		if err != nil {
			t.Fatalf("Requirements() error=%v", err)
		}
	}
	for result := range results {
		if result != "1" {
			t.Fatalf("runtime state leaked between actions: %q", result)
		}
	}
}

func TestRuntimeInterruptsInfiniteLoopOnContextCancellation(t *testing.T) {
	compiled := mustDirectCompiledSDK(t, `
async function __sentinelRequirements(){for(;;){}}
`)
	ctx, cancel := context.WithCancel(context.Background())
	time.AfterFunc(20*time.Millisecond, cancel)
	started := time.Now()
	_, err := mustRuntime(t, time.Second).Requirements(ctx, compiled, runtimeTestProfile(t), "did-timeout")
	if !errors.Is(err, ErrRuntimeTimeout) {
		t.Fatalf("Requirements() error=%v", err)
	}
	if time.Since(started) > 500*time.Millisecond {
		t.Fatalf("runtime interruption took %s", time.Since(started))
	}
}

func TestRuntimeRejectsPendingAndRejectedPromises(t *testing.T) {
	profile := runtimeTestProfile(t)
	runtime := mustRuntime(t, time.Second)
	tests := []struct {
		name   string
		source string
		want   error
	}{
		{name: "pending", source: `async function __sentinelRequirements(){return await new Promise(()=>{})}`, want: ErrRuntimePendingPromise},
		{name: "rejected", source: `async function __sentinelRequirements(){throw new Error("private challenge body")}`, want: ErrRuntimeExecution},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, err := runtime.Requirements(context.Background(), mustDirectCompiledSDK(t, tt.source), profile, "did-123")
			if !errors.Is(err, tt.want) {
				t.Fatalf("Requirements() error=%v", err)
			}
			if strings.Contains(fmt.Sprint(err), "private challenge body") {
				t.Fatalf("runtime error leaked JS details: %v", err)
			}
		})
	}
}

func TestRuntimeRejectsInvalidRequirementsOutput(t *testing.T) {
	tests := []struct {
		name       string
		javascript string
		want       error
	}{
		{name: "empty", javascript: `""`, want: ErrInvalidRuntimeOutput},
		{name: "whitespace", javascript: `"   "`, want: ErrInvalidRuntimeOutput},
		{name: "number", javascript: `123`, want: ErrInvalidRuntimeOutput},
		{name: "missing", javascript: `undefined`, want: ErrInvalidRuntimeOutput},
		{name: "oversized", javascript: `"x".repeat(65537)`, want: ErrRuntimeOutputTooLarge},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			compiled := mustDirectCompiledSDK(t, `async function __sentinelRequirements(){return {request_p:`+tt.javascript+`}}`)
			_, err := mustRuntime(t, time.Second).Requirements(context.Background(), compiled, runtimeTestProfile(t), "did-123")
			if !errors.Is(err, tt.want) {
				t.Fatalf("Requirements() error=%v", err)
			}
		})
	}
}

func TestRuntimeRejectsInvalidSolveInputAndOutput(t *testing.T) {
	profile := runtimeTestProfile(t)
	runtime := mustRuntime(t, time.Second)
	validInput := SolveInput{DeviceID: "did-123", RequestP: "request-p", Challenge: map[string]any{"turnstile": map[string]any{"dx": "dx"}}}
	if _, err := runtime.Solve(context.Background(), mustDirectCompiledSDK(t, `async function __sentinelSolve(){return {final_p:"final",t:"token"}}`), profile, SolveInput{}); !errors.Is(err, ErrInvalidRuntimeInput) {
		t.Fatalf("Solve(empty input) error=%v", err)
	}

	tests := []struct {
		name   string
		result string
		want   error
	}{
		{name: "empty final", result: `{final_p:"",t:"token"}`, want: ErrInvalidRuntimeOutput},
		{name: "empty t", result: `{final_p:"final",t:""}`, want: ErrInvalidRuntimeOutput},
		{name: "number final", result: `{final_p:123,t:"token"}`, want: ErrInvalidRuntimeOutput},
		{name: "number t", result: `{final_p:"final",t:123}`, want: ErrInvalidRuntimeOutput},
		{name: "missing fields", result: `{}`, want: ErrInvalidRuntimeOutput},
		{name: "oversized final", result: `{final_p:"x".repeat(65537),t:"token"}`, want: ErrRuntimeOutputTooLarge},
		{name: "oversized t", result: `{final_p:"final",t:"x".repeat(65537)}`, want: ErrRuntimeOutputTooLarge},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			compiled := mustDirectCompiledSDK(t, `async function __sentinelSolve(){return `+tt.result+`}`)
			_, err := runtime.Solve(context.Background(), compiled, profile, validInput)
			if !errors.Is(err, tt.want) {
				t.Fatalf("Solve() error=%v", err)
			}
		})
	}
}

func compileFixtureSDK(t *testing.T, name string) *CompiledSDK {
	t.Helper()
	return compileSDKSource(t, "fixture"+name, readSDKFixture(t, name))
}

func compileSDKSource(t *testing.T, version string, source []byte) *CompiledSDK {
	t.Helper()
	compiler, err := NewCompiler(&staticSDKSourceLoader{source: source})
	if err != nil {
		t.Fatal(err)
	}
	compiled, err := compiler.Compile(context.Background(), nil, sdkForVersion(version, SDKSourceDiscovery))
	if err != nil {
		t.Fatalf("Compile() error=%v", err)
	}
	return compiled
}

func mustDirectCompiledSDK(t *testing.T, source string) *CompiledSDK {
	t.Helper()
	program, err := goja.Compile("runtime-fixture.js", source, true)
	if err != nil {
		t.Fatalf("goja.Compile() error=%v", err)
	}
	return &CompiledSDK{SDK: sdkForVersion("runtime123", SDKSourceBuiltin), Program: program}
}

func mustRuntime(t *testing.T, timeout time.Duration) *Runtime {
	t.Helper()
	runtime, err := NewRuntime(timeout)
	if err != nil {
		t.Fatalf("NewRuntime() error=%v", err)
	}
	return runtime
}

func runtimeTestProfile(t *testing.T) fingerprint.Profile {
	t.Helper()
	profile, ok := fingerprint.Lookup("chrome146")
	if !ok {
		t.Fatal("chrome146 profile is unavailable")
	}
	return profile
}
