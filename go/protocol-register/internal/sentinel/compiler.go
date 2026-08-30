package sentinel

import (
	"bytes"
	"context"
	"crypto/sha256"
	_ "embed"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"sync"

	"github.com/dop251/goja"
)

var (
	ErrInvalidCompiler = errors.New("invalid Sentinel compiler")
	ErrSDKCompile      = errors.New("Sentinel SDK compilation failed")
)

const sdkSourceMarker = "/*__SENTINEL_SDK_SOURCE__*/"

//go:embed runtime.js
var compatibilityRuntime string

type SDKSourceLoader interface {
	Source(ctx context.Context, client *http.Client, sdk SDK) ([]byte, error)
}

type CompiledSDK struct {
	SDK     SDK
	Program *goja.Program
}

type compileCall struct {
	done    chan struct{}
	program *goja.Program
	err     error
}

type Compiler struct {
	loader SDKSourceLoader
	build  func(SDK, []byte) (*goja.Program, error)

	mu       sync.Mutex
	programs map[string]*goja.Program
	inflight map[string]*compileCall
	attempts map[string]*compileCall
}

func NewCompiler(loader SDKSourceLoader) (*Compiler, error) {
	if loader == nil {
		return nil, ErrInvalidCompiler
	}
	compiler := &Compiler{
		loader:   loader,
		programs: make(map[string]*goja.Program),
		inflight: make(map[string]*compileCall),
		attempts: make(map[string]*compileCall),
	}
	compiler.build = compiler.buildProgram
	return compiler, nil
}

func (c *Compiler) Compile(ctx context.Context, client *http.Client, sdk SDK) (*CompiledSDK, error) {
	if ctx == nil {
		return nil, fmt.Errorf("%w: context is nil", ErrInvalidCompiler)
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	normalized, err := normalizeSDK(sdk)
	if err != nil {
		return nil, err
	}
	attemptKey := normalized.Version + "\x00" + normalized.URL
	c.mu.Lock()
	if call := c.attempts[attemptKey]; call != nil {
		c.mu.Unlock()
		program, err := waitCompileCall(ctx, call)
		if err != nil {
			return nil, err
		}
		return &CompiledSDK{SDK: normalized, Program: program}, nil
	}
	attempt := &compileCall{done: make(chan struct{})}
	c.attempts[attemptKey] = attempt
	c.mu.Unlock()

	program, compileErr := c.runCompileSource(ctx, client, normalized)
	c.mu.Lock()
	attempt.program = program
	attempt.err = compileErr
	delete(c.attempts, attemptKey)
	close(attempt.done)
	c.mu.Unlock()
	if compileErr != nil {
		return nil, compileErr
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	return &CompiledSDK{SDK: normalized, Program: program}, nil
}

func (c *Compiler) runCompileSource(ctx context.Context, client *http.Client, sdk SDK) (program *goja.Program, err error) {
	defer func() {
		if recover() != nil {
			program = nil
			err = ErrSDKCompile
		}
	}()
	return c.compileSource(ctx, client, sdk)
}

func (c *Compiler) compileSource(ctx context.Context, client *http.Client, sdk SDK) (*goja.Program, error) {
	source, err := c.loader.Source(ctx, client, sdk)
	if err != nil {
		return nil, err
	}
	source = append([]byte(nil), source...)
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if len(source) > maxSDKBytes {
		return nil, ErrResponseTooLarge
	}
	if len(bytes.TrimSpace(source)) == 0 {
		return nil, ErrEmptySDKSource
	}
	hash := sha256.Sum256(source)
	key := sdk.Version + "\x00" + fmt.Sprintf("%x", hash[:])

	c.mu.Lock()
	if program := c.programs[key]; program != nil {
		c.mu.Unlock()
		return program, nil
	}
	if call := c.inflight[key]; call != nil {
		c.mu.Unlock()
		return waitCompileCall(ctx, call)
	}
	call := &compileCall{done: make(chan struct{})}
	c.inflight[key] = call
	c.mu.Unlock()

	program, buildErr := c.runBuild(sdk, source)
	if buildErr == nil && program == nil {
		buildErr = ErrSDKCompile
	}
	c.mu.Lock()
	if buildErr == nil {
		c.programs[key] = program
	}
	call.program = program
	call.err = buildErr
	delete(c.inflight, key)
	close(call.done)
	c.mu.Unlock()
	if buildErr != nil {
		return nil, buildErr
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	return program, nil
}

func waitCompileCall(ctx context.Context, call *compileCall) (*goja.Program, error) {
	select {
	case <-ctx.Done():
		return nil, ctx.Err()
	case <-call.done:
		return call.program, call.err
	}
}

func (c *Compiler) runBuild(sdk SDK, source []byte) (program *goja.Program, err error) {
	defer func() {
		if recover() != nil {
			program = nil
			err = ErrSDKCompile
		}
	}()
	return c.build(sdk, source)
}

func (c *Compiler) buildProgram(sdk SDK, source []byte) (*goja.Program, error) {
	patched, err := PatchSDKSource(source)
	if err != nil {
		return nil, err
	}
	if strings.Count(compatibilityRuntime, sdkSourceMarker) != 1 {
		return nil, ErrSDKCompile
	}
	programSource := strings.Replace(compatibilityRuntime, sdkSourceMarker, string(patched), 1)
	program, err := goja.Compile("sentinel-"+sdk.Version+".js", programSource, true)
	if err != nil {
		return nil, ErrSDKCompile
	}
	return program, nil
}
