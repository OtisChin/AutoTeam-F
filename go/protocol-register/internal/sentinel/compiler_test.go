package sentinel

import (
	"context"
	"errors"
	"net/http"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/dop251/goja"
)

func TestCompilerCoalescesConcurrentCompileByVersionAndSourceHash(t *testing.T) {
	loader := &staticSDKSourceLoader{source: readSDKFixture(t, "old")}
	compiler, err := NewCompiler(loader)
	if err != nil {
		t.Fatalf("NewCompiler() error=%v", err)
	}
	originalBuild := compiler.build
	var buildCalls atomic.Int32
	compiler.build = func(sdk SDK, source []byte) (*goja.Program, error) {
		buildCalls.Add(1)
		time.Sleep(25 * time.Millisecond)
		return originalBuild(sdk, source)
	}

	const workers = 32
	start := make(chan struct{})
	results := make(chan *CompiledSDK, workers)
	errorsSeen := make(chan error, workers)
	var wait sync.WaitGroup
	sdk := sdkForVersion("compile123", SDKSourceDiscovery)
	for range workers {
		wait.Add(1)
		go func() {
			defer wait.Done()
			<-start
			compiled, compileErr := compiler.Compile(context.Background(), nil, sdk)
			results <- compiled
			errorsSeen <- compileErr
		}()
	}
	close(start)
	wait.Wait()
	close(results)
	close(errorsSeen)

	if buildCalls.Load() != 1 {
		t.Fatalf("build calls=%d", buildCalls.Load())
	}
	if loader.calls.Load() != 1 {
		t.Fatalf("source calls=%d", loader.calls.Load())
	}
	var program *goja.Program
	for err := range errorsSeen {
		if err != nil {
			t.Fatalf("Compile() error=%v", err)
		}
	}
	for compiled := range results {
		if compiled == nil || compiled.Program == nil || compiled.SDK.Version != sdk.Version {
			t.Fatalf("compiled SDK=%#v", compiled)
		}
		if program == nil {
			program = compiled.Program
		} else if compiled.Program != program {
			t.Fatal("concurrent callers received different immutable programs")
		}
	}
}

func TestCompilerDeliversSharedFailureAndAllowsRetry(t *testing.T) {
	loader := &staticSDKSourceLoader{source: readSDKFixture(t, "old")}
	compiler, err := NewCompiler(loader)
	if err != nil {
		t.Fatal(err)
	}
	originalBuild := compiler.build
	want := errors.New("fixture compile failure")
	var buildCalls atomic.Int32
	var fail atomic.Bool
	fail.Store(true)
	const workers = 32
	compiler.build = func(sdk SDK, source []byte) (*goja.Program, error) {
		buildCalls.Add(1)
		if fail.Load() {
			time.Sleep(50 * time.Millisecond)
			return nil, want
		}
		return originalBuild(sdk, source)
	}

	start := make(chan struct{})
	errorsSeen := make(chan error, workers)
	var wait sync.WaitGroup
	sdk := sdkForVersion("retry123", SDKSourceDiscovery)
	for range workers {
		wait.Add(1)
		go func() {
			defer wait.Done()
			<-start
			compiled, compileErr := compiler.Compile(context.Background(), nil, sdk)
			if compiled != nil {
				errorsSeen <- errors.New("failed compile returned a program")
				return
			}
			errorsSeen <- compileErr
		}()
	}
	close(start)
	wait.Wait()
	close(errorsSeen)
	for err := range errorsSeen {
		if !errors.Is(err, want) {
			t.Fatalf("shared compile error=%v", err)
		}
	}
	if buildCalls.Load() != 1 {
		t.Fatalf("failed build calls=%d", buildCalls.Load())
	}

	fail.Store(false)
	compiled, err := compiler.Compile(context.Background(), nil, sdk)
	if err != nil || compiled == nil || compiled.Program == nil {
		t.Fatalf("retry Compile()=%#v error=%v", compiled, err)
	}
	if buildCalls.Load() != 2 {
		t.Fatalf("build calls after retry=%d", buildCalls.Load())
	}
}

func TestCompilerCoalescesSourceFailureAndAllowsRetry(t *testing.T) {
	want := errors.New("fixture source failure")
	loader := &failOnceSDKSourceLoader{
		source: readSDKFixture(t, "old"),
		err:    want,
		delay:  50 * time.Millisecond,
	}
	loader.fail.Store(true)
	compiler, err := NewCompiler(loader)
	if err != nil {
		t.Fatal(err)
	}

	const workers = 32
	start := make(chan struct{})
	errorsSeen := make(chan error, workers)
	var wait sync.WaitGroup
	sdk := sdkForVersion("sourceretry123", SDKSourceDiscovery)
	for range workers {
		wait.Add(1)
		go func() {
			defer wait.Done()
			<-start
			compiled, compileErr := compiler.Compile(context.Background(), nil, sdk)
			if compiled != nil {
				errorsSeen <- errors.New("failed source load returned a program")
				return
			}
			errorsSeen <- compileErr
		}()
	}
	close(start)
	wait.Wait()
	close(errorsSeen)
	for err := range errorsSeen {
		if !errors.Is(err, want) {
			t.Fatalf("shared source error=%v", err)
		}
	}
	if loader.calls.Load() != 1 {
		t.Fatalf("failed source calls=%d", loader.calls.Load())
	}

	loader.fail.Store(false)
	compiled, err := compiler.Compile(context.Background(), nil, sdk)
	if err != nil || compiled == nil || compiled.Program == nil {
		t.Fatalf("retry Compile()=%#v error=%v", compiled, err)
	}
	if loader.calls.Load() != 2 {
		t.Fatalf("source calls after retry=%d", loader.calls.Load())
	}
}

func TestCompilerKeysCacheBySourceHash(t *testing.T) {
	loader := &mutableSDKSourceLoader{source: readSDKFixture(t, "old")}
	compiler, err := NewCompiler(loader)
	if err != nil {
		t.Fatal(err)
	}
	sdk := sdkForVersion("mutable123", SDKSourceDiscovery)
	first, err := compiler.Compile(context.Background(), nil, sdk)
	if err != nil {
		t.Fatal(err)
	}
	loader.set(readSDKFixture(t, "current"))
	second, err := compiler.Compile(context.Background(), nil, sdk)
	if err != nil {
		t.Fatal(err)
	}
	if first.Program == second.Program {
		t.Fatal("different source hashes reused one program")
	}
}

func TestCompilerRejectsNilLoaderAndCanceledContext(t *testing.T) {
	if _, err := NewCompiler(nil); !errors.Is(err, ErrInvalidCompiler) {
		t.Fatalf("NewCompiler(nil) error=%v", err)
	}
	loader := &staticSDKSourceLoader{source: readSDKFixture(t, "old")}
	compiler, err := NewCompiler(loader)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := compiler.Compile(ctx, nil, sdkForVersion("cancel123", "")); !errors.Is(err, context.Canceled) {
		t.Fatalf("Compile(canceled) error=%v", err)
	}
	if loader.calls.Load() != 0 {
		t.Fatalf("source calls=%d", loader.calls.Load())
	}
}

func TestCompilerRecoversSourceLoaderPanicAndAllowsRetry(t *testing.T) {
	loader := &panicOnceSDKSourceLoader{source: readSDKFixture(t, "old")}
	compiler, err := NewCompiler(loader)
	if err != nil {
		t.Fatal(err)
	}
	sdk := sdkForVersion("loaderpanic123", SDKSourceDiscovery)

	var recovered any
	var firstErr error
	func() {
		defer func() { recovered = recover() }()
		_, firstErr = compiler.Compile(context.Background(), nil, sdk)
	}()
	if recovered != nil {
		t.Fatalf("Compile() leaked source loader panic: %v", recovered)
	}
	if !errors.Is(firstErr, ErrSDKCompile) {
		t.Fatalf("Compile() error=%v", firstErr)
	}
	if strings.Contains(firstErr.Error(), "private source panic") {
		t.Fatalf("Compile() leaked panic details: %v", firstErr)
	}

	compiled, err := compiler.Compile(context.Background(), nil, sdk)
	if err != nil || compiled == nil || compiled.Program == nil {
		t.Fatalf("retry Compile()=%#v error=%v", compiled, err)
	}
	if loader.calls.Load() != 2 {
		t.Fatalf("source calls=%d", loader.calls.Load())
	}
}

type staticSDKSourceLoader struct {
	source []byte
	err    error
	calls  atomic.Int32
}

func (l *staticSDKSourceLoader) Source(ctx context.Context, _ *http.Client, _ SDK) ([]byte, error) {
	l.calls.Add(1)
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if l.err != nil {
		return nil, l.err
	}
	return append([]byte(nil), l.source...), nil
}

type mutableSDKSourceLoader struct {
	mu     sync.RWMutex
	source []byte
}

type panicOnceSDKSourceLoader struct {
	source []byte
	calls  atomic.Int32
}

type failOnceSDKSourceLoader struct {
	source []byte
	err    error
	delay  time.Duration
	fail   atomic.Bool
	calls  atomic.Int32
}

func (l *failOnceSDKSourceLoader) Source(ctx context.Context, _ *http.Client, _ SDK) ([]byte, error) {
	l.calls.Add(1)
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if l.fail.Load() {
		timer := time.NewTimer(l.delay)
		defer timer.Stop()
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-timer.C:
			return nil, l.err
		}
	}
	return append([]byte(nil), l.source...), nil
}

func (l *panicOnceSDKSourceLoader) Source(context.Context, *http.Client, SDK) ([]byte, error) {
	if l.calls.Add(1) == 1 {
		panic("private source panic")
	}
	return append([]byte(nil), l.source...), nil
}

func (l *mutableSDKSourceLoader) Source(context.Context, *http.Client, SDK) ([]byte, error) {
	l.mu.RLock()
	defer l.mu.RUnlock()
	return append([]byte(nil), l.source...), nil
}

func (l *mutableSDKSourceLoader) set(source []byte) {
	l.mu.Lock()
	l.source = append([]byte(nil), source...)
	l.mu.Unlock()
}
