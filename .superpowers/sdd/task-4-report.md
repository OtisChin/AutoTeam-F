# Task 4 Report — Go Email-First Registration State Machine

- **status:** DONE
- **commit hash:** `0583a45e14bd54a95da26cec1102ffd470fdcda2`

## Modified files

- `go/protocol-register/cmd/protocol-registerd/main.go`
- `go/protocol-register/internal/openai/headers.go`
- `go/protocol-register/internal/openai/auth_api.go`
- `go/protocol-register/internal/register/progress.go`
- `go/protocol-register/internal/register/state_machine.go`
- `go/protocol-register/internal/register/state_machine_test.go`

## Tests

1. RED (before implementation):
   ```powershell
   cd go/protocol-register
   go test ./internal/register -run TestHTTPRegisterEngineSuccessWithMockOpenAIAndMail -v
   ```
   Result: failed as expected because `register.NewHTTPRegisterEngine` and `register.HTTPRegisterEngineConfig` were undefined.

2. Targeted state-machine tests:
   ```powershell
   cd go/protocol-register
   go test ./internal/register -run 'TestHTTPRegisterEngine(SuccessWithMockOpenAIAndMail|NormalizesNetworkFailureStatus)' -v
   ```
   Result: PASS (mocked OpenAI/mail email-first flow and direct engine status normalization).

3. Full Go suite:
   ```powershell
   cd go/protocol-register
   go test ./...
   ```
   Result: PASS — command, mailbridge, register, and server packages pass; httpclient, model, and openai report no test files.

## Self-review

- The daemon remains loopback-by-default and now wires the opt-in Go HTTP register engine.
- The state machine covers only email-first registration, obtains the session data in memory, and does not persist accounts or write `data/auth_session`.
- Requests share the proxy-aware, cookie-jar HTTP client across OpenAI and mail polling.
- Failure responses use supported statuses; network failures normalize to `register_failed` while retaining `network_error` in `error.code`.
- No Codex OAuth, phone-first/phone-only, browser/cloak, or unrelated project files were changed.

## Fix Report — Reject failed OpenAI OAuth signin responses

- **Files changed:** `go/protocol-register/internal/openai/auth_api.go`, `go/protocol-register/internal/register/state_machine_test.go`
- **Fix:** `SigninOpenAI` now rejects non-2xx OAuth signin responses with a status-only, non-secret error. Added a state-machine regression test for an OAuth endpoint returning HTTP 502.
- **Tests:** `cd go/protocol-register; go test ./...` — PASS; all command, mailbridge, register, and server tests passed.
- **Commit SHA:** `81479d602f24f352760e113c950f3577325cc7f3`
- **Concerns:** None.

## Fix Report — Sanitize register error responses

- **Files changed:** `go/protocol-register/internal/register/state_machine.go`, `go/protocol-register/internal/register/state_machine_test.go`
- **Fix:** Centralized state-machine failure messages to stable status/step text, discarding raw upstream, URL, transport, and proxy errors. Added OAuth URL and proxy credential redaction regression tests.
- **Tests:** `cd go/protocol-register; go test ./...` — PASS; all available Go packages passed.
- **Commit SHA:** `7aa4b28c505fe94415fb52742a007ad79b3ca220`
- **Concerns:** None.

## Fix Report — Redact upstream OpenAI error bodies

- **Files changed:** `go/protocol-register/internal/openai/auth_api.go`, `go/protocol-register/internal/register/state_machine_test.go`
- **Fix:** `doJSON` now returns only HTTP method, endpoint path, and status code for non-2xx responses. Added regression assertions covering password, access-token, and OTP-link response-body secrets.
- **Tests:** `cd go/protocol-register; go test ./...` — PASS; all available Go packages passed.
- **Commit SHA:** `7c1ab31d7556189c0146d3a5a38cbcb89ce5ddfb`
- **Concerns:** None.
