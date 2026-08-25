# Go Protocol Register Service Design

Date: 2026-08-25
Status: Draft for user review

## Goal

Replace the performance-critical Python protocol registration main path with a long-running Go HTTP service. The target is high-concurrency, high-throughput account registration while keeping the existing Python application as the source of truth for UI/API orchestration, mailbox configuration, account persistence, and progress aggregation.

## Scope

### In scope for phase 1

- Add a Go HTTP service for protocol registration.
- Route `register_mode=protocol` through the Go service when enabled.
- Keep Python-compatible request and response semantics so `create_account_direct()` can continue saving accounts and auth sessions using existing code.
- Support the current email-first protocol registration path:
  - initialize OpenAI auth flow;
  - submit email;
  - set or verify password as required by the flow;
  - trigger email OTP;
  - fetch OTP through the supplied mailbox bridge data;
  - verify OTP;
  - create account/profile when required;
  - return session/auth payload to Python.
- Implement service health checks, concurrency limits, request timeout handling, structured errors, and fallback to Python when configured.

### Out of scope for phase 1

- Browser, RoxyBrowser, or CloakBrowser registration.
- Codex OAuth after registration.
- Phone-first or phone-only registration.
- SMS provider integration.
- Account persistence and `auth_session` file writes in Go.
- Frontend UI redesign.

## Recommended architecture

Use a local Go HTTP service named `protocol-registerd`.

```text
Python API / task runner
  -> autotoken.interfaces.manager.create_account_direct(register_mode="protocol")
  -> autotoken.integrations.go_protocol_register_client.GoProtocolRegisterClient
  -> HTTP POST http://127.0.0.1:18787/v1/register
  -> Go protocol-registerd
  -> Go registration state machine
  -> JSON result back to Python
  -> existing Python account/auth_session persistence
```

This keeps Python stable at the integration boundary while moving the high-I/O, state-machine-heavy protocol registration logic to Go.

## Repository layout

```text
go/protocol-register/
  go.mod
  cmd/protocol-registerd/
    main.go
  internal/server/
    server.go
    routes.go
    middleware.go
  internal/register/
    engine.go
    state_machine.go
    errors.go
    progress.go
  internal/openai/
    auth_api.go
    session_extract.go
    sentinel.go
    headers.go
  internal/httpclient/
    client.go
    proxy.go
    jar.go
  internal/mailbridge/
    client.go
    otp.go
  internal/model/
    request.go
    response.go
```

Python additions:

```text
src/autotoken/integrations/go_protocol_register_client.py
```

Optional packaging helpers:

```text
scripts/build-go-protocol-register.ps1
scripts/build-go-protocol-register.sh
```

## Go service API

### `GET /healthz`

Returns service readiness and version.

Response:

```json
{
  "ok": true,
  "service": "protocol-registerd",
  "version": "dev",
  "max_concurrency": 50,
  "inflight": 3
}
```

### `POST /v1/register`

Runs one email-first protocol registration task.

Request:

```json
{
  "request_id": "uuid-or-task-id",
  "email": "user@example.com",
  "password": "Password123$",
  "proxy_url": "",
  "mail": {
    "provider": "generic-api",
    "account_id": "user@example.com",
    "receive_code_url": "https://mail.example.com/code?to=user%40example.com",
    "issued_after_unix": 1787650000
  },
  "options": {
    "timeout_seconds": 180,
    "trace": false,
    "impersonate": "chrome136"
  }
}
```

Response on success:

```json
{
  "success": true,
  "status": "success",
  "email": "user@example.com",
  "session_data": {
    "accessToken": "...",
    "sessionToken": "...",
    "cookies": [],
    "raw": {}
  },
  "events": [
    {"stage": "email_submitted", "message": "email accepted"},
    {"stage": "otp_verified", "message": "email OTP verified"}
  ]
}
```

Response on failure:

```json
{
  "success": false,
  "status": "email_code_timeout",
  "email": "user@example.com",
  "error": {
    "code": "email_code_timeout",
    "message": "email OTP not received within timeout",
    "retryable": false,
    "step": "email_otp"
  },
  "events": []
}
```

### Future streaming endpoint

Phase 1 can return buffered events in the final response. If progress needs to appear live in the UI, add:

```text
POST /v1/register/stream
```

using Server-Sent Events or newline-delimited JSON.

## Python integration

Add a client wrapper that exposes a function compatible with `autotoken.auth.protocol_register.register_once()`.

Python decision logic:

```text
if register_mode == "protocol" and PROTOCOL_REGISTER_ENGINE == "go":
    call GoProtocolRegisterClient.register_once(...)
else:
    call current Python protocol_register.register_once(...)
```

Default rollout should be explicit:

```text
PROTOCOL_REGISTER_ENGINE=python
```

Operators opt into Go with:

```text
PROTOCOL_REGISTER_ENGINE=go
GO_PROTOCOL_REGISTER_URL=http://127.0.0.1:18787
GO_PROTOCOL_REGISTER_AUTO_START=1
GO_PROTOCOL_REGISTER_BIN=bin/protocol-registerd.exe
GO_PROTOCOL_FALLBACK_PYTHON=1
```

If the Go service is unavailable and fallback is enabled, Python logs the reason and uses the existing Python protocol path. If fallback is disabled, the registration attempt fails fast with `go_protocol_unavailable`.

## Mail and OTP design

Phase 1 avoids migrating all Python mail providers. Python resolves the selected mailbox and sends enough mailbox metadata to Go.

For `generic-api`, Go can fetch `receive_code_url` directly. For providers that cannot expose a simple receive-code URL, Python can provide a local mail bridge endpoint later.

Phase 1 supported mailbox payloads:

- `generic-api`: direct receive-code URL.
- `icloud`: direct receive-code URL when available.
- Other providers: fallback to Python protocol path until a bridge is added.

OTP polling rules:

- Poll until `timeout_seconds`.
- Ignore messages older than `issued_after_unix` when timestamps are available.
- Extract explicit code fields before regex parsing.
- Return `email_code_timeout` instead of generic failure when no OTP arrives.

## Concurrency model

The Go service owns a weighted semaphore:

```text
GO_PROTOCOL_MAX_CONCURRENCY=50
```

Each registration task gets:

- independent cookie jar;
- independent request context with deadline;
- optional per-request proxy;
- shared `http.Transport` pools keyed by proxy/fingerprint settings where safe;
- structured per-task event buffer.

Python still controls total task count and user-facing progress. Go controls internal HTTP concurrency and avoids Python thread/GIL overhead on protocol I/O.

## Performance goals

Initial measurable targets:

- Single successful generic-api registration should be faster than Python protocol path under the same network conditions.
- 20 concurrent protocol registrations should avoid Python CPU saturation.
- Service should sustain at least 50 inflight tasks without unbounded goroutine or memory growth.
- Failures such as OTP timeout should return structured errors without blocking worker slots past deadline.

## Error mapping

Go errors must map to Python-compatible statuses:

| Go code | Python status | Meaning |
|---|---|---|
| `email_already_in_use` | `duplicate` / duplicate swap | OpenAI says email already used |
| `email_code_timeout` | `email_code_timeout` | OTP not received |
| `phone_required` | `phone_blocked` | add-phone encountered |
| `account_deactivated` | `account_deactivated` | account disabled/deactivated response |
| `rate_limited` | `register_failed` with retryable detail | OpenAI or proxy rate limit |
| `network_error` | `exception` or retryable failure | transport/proxy failure |
| `html_challenge` | `register_failed` | Cloudflare/challenge page in protocol path |
| `internal_error` | `exception` | service bug or unexpected state |

Python remains responsible for duplicate mailbox rotation and unavailable-email marking.

## Security and operational constraints

- Bind to loopback by default: `127.0.0.1` only.
- Do not log raw passwords, session tokens, cookies, OTP links, or API keys.
- Redact secrets in request/response logs.
- Add request size limits.
- Add graceful shutdown and drain inflight requests.
- Use per-request context cancellation to prevent stuck goroutines.

## Testing strategy

### Go unit tests

- OTP extraction from JSON, HTML, and plain text.
- Request header construction.
- Error classifier mapping.
- Context timeout and semaphore release.
- Cookie jar isolation between concurrent tasks.

### Go integration tests

- Mock OpenAI auth endpoints with `httptest.Server`.
- Mock receive-code API.
- Verify full success state machine.
- Verify duplicate, OTP timeout, add-phone, and HTML challenge paths.

### Python tests

- `register_mode=protocol` calls Go client when `PROTOCOL_REGISTER_ENGINE=go`.
- Fallback to Python protocol path when Go service is unavailable and fallback is enabled.
- No fallback when `GO_PROTOCOL_FALLBACK_PYTHON=0`.
- Python converts Go response into the existing `(success, session_data)` flow.
- Account/auth_session persistence remains unchanged.

### Contract tests

Store JSON fixtures for:

```text
tests/fixtures/go_protocol_register/register_request_generic_api.json
tests/fixtures/go_protocol_register/register_success_response.json
tests/fixtures/go_protocol_register/email_code_timeout_response.json
tests/fixtures/go_protocol_register/phone_required_response.json
```

Both Go and Python tests should validate these fixtures.

## Rollout plan

1. Add Go service skeleton, `/healthz`, and config.
2. Add Python Go client and fallback behavior behind `PROTOCOL_REGISTER_ENGINE=go`.
3. Implement request/response contract tests.
4. Port minimal email-first protocol state machine to Go.
5. Support direct receive-code URL OTP polling for `generic-api` and `icloud`.
6. Run one real generic-api registration.
7. Run concurrency benchmarks at 5, 20, and 50 inflight tasks.
8. Tune transport pooling, timeouts, and concurrency defaults.
9. Document deployment and troubleshooting.

## Success criteria

- Existing Python protocol mode still works when `PROTOCOL_REGISTER_ENGINE=python`.
- Go mode works for at least one real `generic-api` mailbox registration.
- Go mode returns session data that current Python account/auth_session save path accepts.
- Go service handles 20+ concurrent registration requests without Python becoming the bottleneck.
- Failure categories are precise enough for existing mailbox rotation and task reporting.
- Unit and integration tests pass on Windows in this repository.
