package sentinel

import (
	"context"
	"crypto/rand"
	"encoding/json"
	"errors"
	"strconv"
	"strings"
	"time"

	"autoteam-f/protocol-register/internal/fingerprint"

	"github.com/dop251/goja"
)

var (
	ErrInvalidRuntime        = errors.New("invalid Sentinel runtime")
	ErrInvalidRuntimeInput   = errors.New("invalid Sentinel runtime input")
	ErrInvalidRuntimeOutput  = errors.New("invalid Sentinel runtime output")
	ErrRuntimeExecution      = errors.New("Sentinel runtime execution failed")
	ErrRuntimeTimeout        = errors.New("Sentinel runtime timed out")
	ErrRuntimePendingPromise = errors.New(
		"Sentinel runtime returned a pending promise",
	)
	ErrRuntimeOutputTooLarge = errors.New("Sentinel runtime output exceeds size limit")
)

const (
	maxRuntimeOutputBytes = 64 * 1024
	maxRuntimeInputBytes  = 2 * 1024 * 1024
	maxRandomBytes        = 64 * 1024
)

type SolveInput struct {
	DeviceID  string
	RequestP  string
	Challenge map[string]any
}

type SolveOutput struct {
	FinalP string `json:"final_p"`
	T      string `json:"t"`
}

type Runtime struct {
	timeout time.Duration
}

type runtimePayload struct {
	DeviceID            string         `json:"device_id"`
	SDKURL              string         `json:"sdk_url"`
	UserAgent           string         `json:"user_agent"`
	BrowserMajor        int            `json:"browser_major"`
	Language            string         `json:"language"`
	Languages           []string       `json:"languages"`
	HardwareConcurrency int            `json:"hardware_concurrency"`
	DeviceMemory        int            `json:"device_memory"`
	ScreenWidth         int            `json:"screen_width"`
	ScreenHeight        int            `json:"screen_height"`
	RequestP            string         `json:"request_p,omitempty"`
	Challenge           map[string]any `json:"challenge,omitempty"`
}

func NewRuntime(timeout time.Duration) (*Runtime, error) {
	if timeout <= 0 {
		return nil, ErrInvalidRuntime
	}
	return &Runtime{timeout: timeout}, nil
}

func (r *Runtime) Requirements(ctx context.Context, compiled *CompiledSDK, profile fingerprint.Profile, deviceID string) (string, error) {
	deviceID = strings.TrimSpace(deviceID)
	if deviceID == "" {
		return "", ErrInvalidRuntimeInput
	}
	payload, err := makeRuntimePayload(compiled, profile, deviceID)
	if err != nil {
		return "", err
	}
	vm, result, err := r.runAction(ctx, compiled, "__sentinelRequirements", payload)
	if err != nil {
		return "", err
	}
	requestP, err := requiredStringField(vm, result, "request_p")
	if err != nil {
		return "", err
	}
	if err := enforceRuntimeOutputLimit(struct {
		RequestP string `json:"request_p"`
	}{RequestP: requestP}); err != nil {
		return "", err
	}
	return requestP, nil
}

func (r *Runtime) Solve(ctx context.Context, compiled *CompiledSDK, profile fingerprint.Profile, input SolveInput) (SolveOutput, error) {
	input.DeviceID = strings.TrimSpace(input.DeviceID)
	input.RequestP = strings.TrimSpace(input.RequestP)
	if input.DeviceID == "" || input.RequestP == "" || len(input.Challenge) == 0 {
		return SolveOutput{}, ErrInvalidRuntimeInput
	}
	payload, err := makeRuntimePayload(compiled, profile, input.DeviceID)
	if err != nil {
		return SolveOutput{}, err
	}
	payload.RequestP = input.RequestP
	payload.Challenge = input.Challenge
	vm, result, err := r.runAction(ctx, compiled, "__sentinelSolve", payload)
	if err != nil {
		return SolveOutput{}, err
	}
	finalP, err := requiredStringField(vm, result, "final_p")
	if err != nil {
		return SolveOutput{}, err
	}
	token, err := requiredStringField(vm, result, "t")
	if err != nil {
		return SolveOutput{}, err
	}
	output := SolveOutput{FinalP: finalP, T: token}
	if err := enforceRuntimeOutputLimit(output); err != nil {
		return SolveOutput{}, err
	}
	return output, nil
}

func (r *Runtime) runAction(ctx context.Context, compiled *CompiledSDK, action string, payload runtimePayload) (resultVM *goja.Runtime, resultValue goja.Value, resultErr error) {
	defer func() {
		if recover() != nil {
			resultVM = nil
			resultValue = nil
			resultErr = ErrRuntimeExecution
		}
	}()
	if r == nil || r.timeout <= 0 {
		return nil, nil, ErrInvalidRuntime
	}
	if ctx == nil {
		return nil, nil, ErrInvalidRuntimeInput
	}
	if err := ctx.Err(); err != nil {
		return nil, nil, runtimeTimeout(err)
	}
	if compiled == nil || compiled.Program == nil {
		return nil, nil, ErrInvalidRuntimeInput
	}
	if _, err := normalizeSDK(compiled.SDK); err != nil {
		return nil, nil, ErrInvalidRuntimeInput
	}
	payloadJSON, err := json.Marshal(payload)
	if err != nil || len(payloadJSON) > maxRuntimeInputBytes {
		return nil, nil, ErrInvalidRuntimeInput
	}

	actionContext, cancel := context.WithTimeout(ctx, r.timeout)
	defer cancel()
	if err := actionContext.Err(); err != nil {
		return nil, nil, runtimeTimeout(err)
	}
	vm := goja.New()
	if err := installRuntimeHosts(vm); err != nil {
		return nil, nil, ErrRuntimeExecution
	}
	if err := vm.Set("__sentinelPayloadJSON", string(payloadJSON)); err != nil {
		return nil, nil, ErrRuntimeExecution
	}

	stopInterrupt := make(chan struct{})
	interruptStopped := make(chan struct{})
	go func() {
		defer close(interruptStopped)
		select {
		case <-actionContext.Done():
			vm.Interrupt(actionContext.Err())
		case <-stopInterrupt:
		}
	}()
	defer func() {
		close(stopInterrupt)
		<-interruptStopped
	}()

	if _, err := vm.RunProgram(compiled.Program); err != nil {
		return nil, nil, normalizeRuntimeExecutionError(err)
	}
	function, ok := goja.AssertFunction(vm.Get(action))
	if !ok {
		return nil, nil, ErrRuntimeExecution
	}
	value, err := function(goja.Undefined(), vm.Get("__sentinelPayload"))
	if err != nil {
		return nil, nil, normalizeRuntimeExecutionError(err)
	}
	promise, ok := value.Export().(*goja.Promise)
	if !ok {
		return nil, nil, ErrInvalidRuntimeOutput
	}
	switch promise.State() {
	case goja.PromiseStatePending:
		return nil, nil, ErrRuntimePendingPromise
	case goja.PromiseStateRejected:
		return nil, nil, ErrRuntimeExecution
	case goja.PromiseStateFulfilled:
		if err := actionContext.Err(); err != nil {
			return nil, nil, runtimeTimeout(err)
		}
		return vm, promise.Result(), nil
	default:
		return nil, nil, ErrInvalidRuntimeOutput
	}
}

func makeRuntimePayload(compiled *CompiledSDK, profile fingerprint.Profile, deviceID string) (runtimePayload, error) {
	if compiled == nil || compiled.Program == nil {
		return runtimePayload{}, ErrInvalidRuntimeInput
	}
	normalized, err := normalizeSDK(compiled.SDK)
	if err != nil || strings.TrimSpace(profile.UserAgent) == "" || profile.Major <= 0 {
		return runtimePayload{}, ErrInvalidRuntimeInput
	}
	languages := profileLanguages(profile.AcceptLanguage)
	return runtimePayload{
		DeviceID:            deviceID,
		SDKURL:              normalized.URL,
		UserAgent:           profile.UserAgent,
		BrowserMajor:        profile.Major,
		Language:            languages[0],
		Languages:           languages,
		HardwareConcurrency: 12,
		DeviceMemory:        8,
		ScreenWidth:         1366,
		ScreenHeight:        768,
	}, nil
}

func profileLanguages(acceptLanguage string) []string {
	languages := make([]string, 0, 2)
	seen := make(map[string]struct{}, 2)
	for _, entry := range strings.Split(acceptLanguage, ",") {
		language := strings.TrimSpace(strings.SplitN(entry, ";", 2)[0])
		if language == "" {
			continue
		}
		if _, exists := seen[language]; exists {
			continue
		}
		seen[language] = struct{}{}
		languages = append(languages, language)
	}
	if len(languages) == 0 {
		return []string{"en-US", "en"}
	}
	return languages
}

func installRuntimeHosts(vm *goja.Runtime) error {
	if err := vm.Set("__sentinelFillRandom", func(call goja.FunctionCall) goja.Value {
		value := call.Argument(0)
		object := value.ToObject(vm)
		length := object.Get("length").ToInteger()
		if length < 0 || length > maxRandomBytes {
			panic(vm.NewTypeError("random buffer length is invalid"))
		}
		buffer := make([]byte, int(length))
		if _, err := rand.Read(buffer); err != nil {
			panic(vm.NewGoError(err))
		}
		for index, item := range buffer {
			if err := object.Set(strconv.Itoa(index), int(item)); err != nil {
				panic(vm.NewGoError(err))
			}
		}
		return value
	}); err != nil {
		return err
	}
	if err := vm.Set("__sentinelEncodeUTF8", func(input string) goja.ArrayBuffer {
		if len(input) > maxRuntimeInputBytes {
			panic(vm.NewTypeError("text input length is invalid"))
		}
		return vm.NewArrayBuffer([]byte(input))
	}); err != nil {
		return err
	}
	return vm.Set("__sentinelDecodeUTF8", func(value goja.Value) string {
		if value == nil || goja.IsUndefined(value) || goja.IsNull(value) {
			return ""
		}
		var data []byte
		switch exported := value.Export().(type) {
		case []uint8:
			if len(exported) > maxRuntimeInputBytes {
				panic(vm.NewTypeError("text buffer length is invalid"))
			}
			data = exported
		case goja.ArrayBuffer:
			data = exported.Bytes()
			if len(data) > maxRuntimeInputBytes {
				panic(vm.NewTypeError("text buffer length is invalid"))
			}
		default:
			object := value.ToObject(vm)
			lengthValue := object.Get("length")
			if lengthValue == nil || goja.IsUndefined(lengthValue) || goja.IsNull(lengthValue) {
				panic(vm.NewTypeError("text buffer length is invalid"))
			}
			length := lengthValue.ToInteger()
			if length < 0 || length > maxRuntimeInputBytes {
				panic(vm.NewTypeError("text buffer length is invalid"))
			}
			data = make([]byte, int(length))
			for index := range data {
				data[index] = byte(object.Get(strconv.Itoa(index)).ToInteger())
			}
		}
		return strings.ToValidUTF8(string(data), "\uFFFD")
	})
}

func requiredStringField(vm *goja.Runtime, value goja.Value, field string) (string, error) {
	object, ok := value.(*goja.Object)
	if !ok || object == nil {
		return "", ErrInvalidRuntimeOutput
	}
	fieldValue := object.Get(field)
	if fieldValue == nil || goja.IsUndefined(fieldValue) || goja.IsNull(fieldValue) {
		return "", ErrInvalidRuntimeOutput
	}
	text, ok := fieldValue.Export().(string)
	if !ok {
		return "", ErrInvalidRuntimeOutput
	}
	text = strings.TrimSpace(text)
	if text == "" {
		return "", ErrInvalidRuntimeOutput
	}
	if len(text) > maxRuntimeOutputBytes {
		return "", ErrRuntimeOutputTooLarge
	}
	return text, nil
}

func enforceRuntimeOutputLimit(value any) error {
	payload, err := json.Marshal(value)
	if err != nil {
		return ErrInvalidRuntimeOutput
	}
	if len(payload) > maxRuntimeOutputBytes {
		return ErrRuntimeOutputTooLarge
	}
	return nil
}

func normalizeRuntimeExecutionError(err error) error {
	var interrupted *goja.InterruptedError
	if errors.As(err, &interrupted) {
		if cause, ok := interrupted.Value().(error); ok {
			return runtimeTimeout(cause)
		}
		return ErrRuntimeTimeout
	}
	if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
		return runtimeTimeout(err)
	}
	return ErrRuntimeExecution
}

func runtimeTimeout(cause error) error {
	if cause == nil {
		return ErrRuntimeTimeout
	}
	return errors.Join(ErrRuntimeTimeout, cause)
}
