# Protocol Registration Reliability and Compliance Hardening Design

Date: 2026-08-30
Status: Approved for implementation

## Goal

Make protocol registration predictable, observable, and resource-efficient while
reducing false positives caused by duplicated requests, inconsistent sessions,
stale OTPs, and uncontrolled concurrency. The Go service remains an opt-in path
until it demonstrates semantic parity with the supported authentication flow.

## Operating constraints

- Do not add or improve challenge-bypass behavior.
- A challenge or unsupported authentication state fails closed or transfers to
  an explicitly selected supported browser flow.
- Do not fabricate a token when Sentinel execution fails.
- One account attempt keeps one egress route, one cookie jar, one device identity,
  and one client profile from start to finish.
- State-changing requests are never retried automatically by an HTTP transport.
- A client timeout after a state-changing request is indeterminate; Python must
  not immediately replay the same registration through another engine.
- High task throughput comes from stage separation and bounded queues, not from
  sending many simultaneous authentication mutations.
- Logs, events, and errors must not expose passwords, OTP URLs, cookies, tokens,
  proxy credentials, or upstream response bodies.

## Baseline findings

The existing Python path is the functional reference, but currently compounds
transport retries, OTP fallbacks, verification retries, and account retries. It
also rotates HTTP impersonation after TLS failures, creating a new cookie jar and
changing client behavior inside one logical attempt.

The Go path is a phase-one skeleton. Its local integration tests use simplified
mock endpoints and do not establish production semantic parity. The service does
not yet implement the planned session extractor, readiness gate, staged
concurrency, mail freshness checks, or reusable transport factory. Its Chrome
pool changes only the User-Agent while the underlying Go TLS stack remains
unchanged, so random rotation is not a valid browser profile.

## Architecture

```text
Python task controller
  -> mailbox preparation
  -> engine admission/readiness check
  -> registration attempt with immutable AttemptContext
       -> auth-start permit (small bounded pool)
       -> OTP wait (separate larger wait pool)
       -> auth-finish permit (same bounded auth pool)
  -> credential validation and persistence
  -> structured outcome and rolling circuit breaker
```

The Python controller remains the source of truth for mailbox selection,
account persistence, UI progress, and rollout policy. Go owns protocol request
execution only after its readiness gate passes.

## 1. Immutable attempt context

Every attempt has a generated UUID and immutable context:

```text
AttemptContext
  request_id
  email
  proxy route
  client profile
  device id
  issued-at timestamp
  request budget
```

Retries that require a new cookie jar are a new attempt and must not silently
reuse the previous attempt's mutation budget. Identity/profile data is generated
once and reused for all requests in the same attempt.

## 2. Retry and mutation budgets

### Transport layer

- Retry only safe/idempotent methods such as GET and HEAD.
- Never transport-retry password registration, OTP send/resend, OTP validation,
  profile creation, or callback consumption.
- Respect context cancellation and server Retry-After metadata.

### Application layer

- At most one initial OTP delivery and one explicitly classified resend.
- Default OTP verification attempts: two, each with a distinct fresh code.
- A 4xx authentication state error is terminal unless an exact state transition
  explicitly declares it recoverable.
- A 403, 429, challenge page, or phone-required result opens the relevant
  circuit breaker and is not followed by fingerprint or proxy cycling.
- Go-to-Python fallback is allowed only for daemon startup/readiness failure
  before `/v1/register` is sent.

## 3. Stable client behavior

- Remove random Chrome 143-152 User-Agent selection from the Go path.
- Keep one configured profile for an attempt; profile changes require a new
  attempt and an explicit operator decision.
- Python must not rotate the impersonation profile and replace its session after
  a TLS error. A TLS error is a network failure.
- Origin, Referer, content type, and redirect handling are built per endpoint,
  not from one global header template.
- The Go standard transport is reported as `go-http`; it must not claim browser
  impersonation in health or event metadata.

## 4. Challenge handling

- The existing custom Sentinel path is not expanded or optimized.
- Synthetic/Python token fallback is disabled by default.
- SDK execution failure, unsupported SDK layout, empty challenge data, or invalid
  output returns a typed `challenge_unavailable` failure.
- The task controller may stop or use a separately selected supported browser
  mode. It does not replay the same account automatically.
- Downloaded SDK execution must receive a scrubbed environment and bounded
  timeout/output. No application secrets are inherited by the subprocess.

## 5. Go readiness and state-machine parity

`GET /healthz` reports:

```json
{
  "ok": true,
  "ready": false,
  "protocol_ready": false,
  "service": "protocol-registerd",
  "version": "dev",
  "max_concurrency": 20,
  "auth_concurrency": 3,
  "inflight": 0
}
```

The Python client routes traffic to Go only when `protocol_ready=true`.

The Go state machine must provide explicit typed states and validate every
transition:

```text
csrf -> signin -> authorize -> password? -> otp-delivery -> otp-wait
     -> otp-verify -> profile? -> redirect/callback -> session-validate
```

Unknown pages, missing continuation data, HTML challenges, and missing session
credentials are failures. Mock servers must validate method, content type,
Origin/Referer, cookies, redirect continuity, and request ordering.

Until this parity suite passes, the daemon advertises `protocol_ready=false` and
returns `service_not_ready` without contacting an upstream service.

## 6. Mail bridge

The mail bridge uses a dedicated HTTP client rather than the authentication
proxy transport.

- Consume the complete `MailConfig`, including `IssuedAfterUnix`.
- Reject codes older than the attempt's issue timestamp when timestamp metadata
  is available.
- Track and reject already-consumed codes.
- Distinguish terminal 4xx configuration/authentication errors from retryable
  timeouts and 5xx errors.
- Use bounded exponential backoff with jitter rather than synchronized fixed
  three-second polling.
- Limit response bodies and validate content type/shape before extracting a code.
- Redact the receive-code URL in all errors and events.

## 7. Staged concurrency

Two independent limits are required:

- `max_concurrency`: total admitted attempts, including OTP waiters.
- `auth_concurrency`: attempts currently allowed to call authentication endpoints.

An attempt releases the auth permit while waiting for email and reacquires it
before OTP validation. Mail polling therefore does not consume scarce auth
capacity, while external authentication traffic remains conservatively bounded.

Admission returns structured 429 responses with Retry-After. The Python task
controller keeps pending work queued instead of immediately retrying.

## 8. Transport reuse and isolation

- Reuse Go `http.Transport` instances only for identical proxy/network settings.
- Keep a separate cookie jar per attempt.
- Bound idle connections and idle lifetime.
- Close idle connections when a transport pool entry expires.
- Do not use the authentication proxy for mailbox APIs unless separately and
  explicitly configured.

## 9. Error model

Errors have stable machine-readable codes:

```text
service_not_ready
busy
network_error
indeterminate_result
invalid_auth_state
challenge_unavailable
rate_limited
email_code_timeout
email_code_stale
email_code_rejected
phone_required
account_deactivated
session_missing
internal_error
```

Each error includes `retryable`, `step`, and `request_sent`. Python fallback is
permitted only when `request_sent=false` and the code is `service_not_ready` or a
daemon startup error.

## 10. Observability

Every progress event includes request ID, stage, elapsed milliseconds, and a
safe outcome code. Aggregate metrics include:

- admitted, inflight, and rejected attempts;
- auth-stage concurrency and wait duration;
- stage latency p50/p95;
- OTP delivery and resend counts;
- stale/reused OTP rejection counts;
- response categories by step;
- session-validation success rate;
- circuit-breaker state.

Raw email addresses, proxy URLs, tokens, cookies, passwords, and OTP URLs are not
metric labels.

## 11. Circuit breaker

Replace a single global consecutive-failure counter with rolling counters scoped
by failure category and egress identity. Opening a breaker prevents new auth
starts but allows in-flight OTP waiters to finish safely. A successful unrelated
mail operation does not reset an authentication-risk breaker.

## 12. Testing

### Python

- Transport does not retry POST.
- Impersonation does not rotate mid-attempt.
- Synthetic Sentinel fallback fails closed.
- Go startup failures may fall back; indeterminate register failures may not.
- OTP delivery enforces one initial send plus one resend budget.
- Task admission honors Retry-After without immediate replay.

### Go

- Direct tests for request builders and endpoint-specific headers/body encoding.
- Cookie continuity and per-attempt isolation.
- Unknown/HTML/challenge state classification.
- Mail freshness, consumed-code exclusion, terminal error handling, and backoff.
- Staged concurrency: OTP wait releases auth capacity.
- Admission semaphore release on panic, cancellation, and timeout.
- Read/header/idle timeouts and graceful shutdown.
- Transport pool reuse with independent cookie jars.

### Verification

- `pytest` for focused Python protocol tests.
- `ruff check` on modified Python files.
- `go test ./...`, `go vet ./...`, and Linux CI `go test -race ./...`.
- Mock load tests at 5, 20, and 50 admitted attempts; authentication concurrency
  must never exceed the configured small limit.
- A real canary is manual, single-account, authorized, and starts at concurrency
  one. It is not part of automated tests.

## Rollout gates

1. Ship request-safety changes while Python remains the default engine.
2. Ship Go readiness=false plus full local parity tests.
3. Enable Go for mock/shadow traffic only.
4. Run one authorized canary with fallback disabled.
5. Require session-validation success and zero duplicate OTP delivery before
   increasing auth concurrency from one.
6. Keep browser fallback explicit; never trigger it automatically after an
   indeterminate protocol mutation.

## Non-goals

- Increasing simultaneous upstream registrations to evade rate limits.
- Fingerprint, proxy, or identity rotation intended to bypass challenges.
- Improving custom anti-abuse challenge solving.
- Automated creation of real accounts as a test fixture.
