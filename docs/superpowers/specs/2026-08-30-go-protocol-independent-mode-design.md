# Independent Go Protocol Registration Design

**Date:** 2026-08-30
**Status:** Approved
**Scope:** Account registration mode selection, Go authentication transport,
Go-native Sentinel execution, readiness, tests, and operator configuration.

## 1. Objective

Make Go protocol registration a first-class registration mode rather than an
alternate implementation hidden behind the Python protocol mode. Selecting Go
must never execute the Python protocol implementation or fall back to it. The
Go service must also apply a real, internally selected browser TLS/HTTP2
profile and provide its own Sentinel SDK runtime before advertising protocol
readiness.

Python remains the application-level orchestrator for mailbox creation, task
progress, and account persistence. That orchestration boundary does not grant
the Python protocol implementation control over Go transport, retries,
fingerprints, Sentinel, or fallback behavior.

### Verified dependency correction

Implementation-time source inspection found that the released
`github.com/bogdanfinn/tls-client` v1.15.1 contains concrete Chrome 144 and
Chrome 146 profiles, but not Chrome 150. Chrome 150 was added by upstream
commit `b790a311273f26051935641120de169e497e5943` on 2026-07-02. To preserve
the approved three-profile pool without copying or inventing a profile, the Go
module pins the reproducible pseudo-version
`v1.15.2-0.20260702071810-b790a311273f`. This correction supersedes the
earlier v1.15.1 reference below; the Go 1.24.1 baseline is unchanged.

## 2. Registration Modes

The application exposes five mutually exclusive modes:

| Mode | Implementation |
| --- | --- |
| `browser` | Local browser automation |
| `protocol` | Existing Python protocol implementation |
| `go_protocol` | Local `protocol-registerd` service |
| `roxy` | RoxyBrowser-backed browser automation |
| `cloak` | CloakBrowser-backed browser automation |

The registration API accepts a dedicated `go_protocol_register` /
`goProtocolRegister` flag for backward-compatible request shaping. The Web UI
shows a separate “Go 协议注册” option and keeps all mode controls mutually
exclusive. The normalized task value is `register_mode=go_protocol`.

The manager dispatches `protocol` directly to the Python protocol module and
`go_protocol` directly to a dedicated Go bridge module. The Go bridge must not
import or call `autotoken.auth.protocol_register`, `_protocol_register`,
`AuthFlow`, or `Config`.

The legacy variables `PROTOCOL_REGISTER_ENGINE` and
`GO_PROTOCOL_FALLBACK_PYTHON` no longer influence mode selection. They are
removed from active configuration and documented as ignored legacy settings.
Any Go startup, readiness, transport, Sentinel, or registration failure is
returned as a Go-mode task failure. No error category triggers Python protocol
fallback.

Phone-first and phone-only protocol flows remain Python-only. Selecting
`go_protocol` with a phone/SMS registration flow is rejected before a task is
started.

## 3. Go Request Contract

The Python orchestration layer sends identity, mailbox polling, proxy, timeout,
and tracing data to `/v1/register`. It does not select or transmit an
impersonation profile. The legacy `options.impersonate` field may remain
accepted during a compatibility window, but the Go service ignores it and
never uses it as a profile source.

The profile source of truth is the Go daemon environment:

```env
GO_PROTOCOL_FINGERPRINT_POOL=chrome144,chrome146,chrome150
```

Only profiles backed by concrete `tls-client` definitions are accepted.
Unsupported names, an empty configured pool, or duplicate-only invalid input
make the daemon protocol-unready with a precise readiness reason. Whitespace
and duplicate valid entries are normalized.

## 4. Fingerprint Selection and Transport

The Go module baseline moves to Go 1.24.1 and uses
`github.com/bogdanfinn/tls-client`
`v1.15.2-0.20260702071810-b790a311273f`. The initial supported registry is:

| Name | TLS client profile | Browser major |
| --- | --- | --- |
| `chrome144` | `profiles.Chrome_144` | 144 |
| `chrome146` | `profiles.Chrome_146` | 146 |
| `chrome150` | `profiles.Chrome_150` | 150 |

For every accepted `/v1/register` call, Go draws one pool entry with
`crypto/rand`. The selected profile remains fixed for the complete registration
attempt, including ChatGPT, Auth, Sentinel discovery/challenge traffic,
redirects, cookies, and session extraction. A TLS failure or application error
does not rotate or rebuild the attempt with a different profile. A later,
explicit registration attempt performs a new draw.

Each profile owns a coherent set of values:

- `tls-client` ClientHello and HTTP/2 profile;
- full Chrome User-Agent using the same major version;
- `sec-ch-ua`, `sec-ch-ua-mobile`, and `sec-ch-ua-platform` values;
- browser request and pseudo-header ordering applied by the transport adapter.

The existing OpenAI client continues to consume a standard `*http.Client`.
An internal `http.RoundTripper` adapter translates standard-library requests to
`fhttp` requests and translates responses back. The outer standard client owns
the cookie jar and redirect policy, while the inner TLS client has redirects
and cookie mutation disabled. This preserves the existing auth state-machine
surface while changing the wire transport.

One authentication client and connection pool are created per registration
attempt. The separate mailbox polling client remains a standard Go HTTP client
and does not receive the OpenAI browser profile or proxy unless mailbox
configuration explicitly gains such a field in a future design.

## 5. Go-Native Sentinel Provider

The daemon embeds a Sentinel adapter with `go:embed` and executes the official
SDK in Goja. It does not import Python code, invoke Python, call a Python
service, or require Node.

The Goja dependency is pinned to a revision compatible with Go 1.24. The
runtime architecture is:

1. Resolve the SDK URL from an explicit validated override, a fresh cache,
   official frame discovery, stale cache, or the built-in fallback.
2. Accept only HTTPS URLs on `sentinel.openai.com` whose path exactly matches
   `/sentinel/<version>/sdk.js`.
3. Download with bounded response size and timeout, then write the versioned
   cache atomically.
4. Run the semantic patcher once and compile the patched SDK into a cached
   immutable Goja program. Concurrent loads of one version are coalesced.
5. Create an isolated Goja runtime per action and install a bounded browser
   compatibility environment.
6. Generate a requirements token, fetch `/backend-api/sentinel/req` through the
   registration attempt’s selected TLS client, solve the returned challenge,
   and return `{p,t,c,id,flow}`.

The current SDK candidate is tried first, followed by runtime-validated
last-known-good and built-in candidates. SDK load or execution incompatibility
may advance to the next candidate. A challenge transport failure does not
replay the challenge against another SDK. A candidate is marked last-known-good
only after one complete requirements/challenge/solve cycle succeeds.

Every VM is interrupted when its context expires. SDK source, discovery HTML,
challenge body, generated output, and logged error text have explicit size
limits. Empty or malformed output is `challenge_unavailable`; there is no
synthetic token fallback.

## 6. Readiness

Readiness is computed rather than hard-coded. At startup the daemon validates
the configured fingerprint registry, resolves/downloads an SDK candidate,
compiles it, and executes a requirements dry-run. It does not send an account
registration request or OTP mutation during startup.

`protocol_ready=true` requires both a valid non-empty fingerprint pool and a
Sentinel candidate that completes the dry-run. Otherwise the HTTP server still
starts, `/v1/register` remains fail-closed, and `/healthz` reports the component
reason.

Health output includes:

```json
{
  "ok": true,
  "protocol_ready": true,
  "fingerprint_pool": ["chrome144", "chrome146", "chrome150"],
  "sentinel_ready": true,
  "sentinel_sdk_version": "<validated version>",
  "ready_reason": ""
}
```

SDK refresh follows the configured TTL. A refresh failure may continue using a
previously validated last-known-good candidate. A transient challenge HTTP
failure affects the current attempt but does not globally disable an otherwise
healthy provider.

## 7. Error and Retry Semantics

- Go daemon unavailable or unready: fail the `go_protocol` task without Python
  fallback.
- Invalid Go fingerprint configuration: daemon remains protocol-unready.
- Unsupported phone/SMS flow: API validation error before task creation.
- TLS/network failure: return a typed retryable Go failure; do not rotate the
  profile inside the attempt.
- Unknown auth state, challenge failure, or missing session credentials:
  terminal fail-closed response as defined by the existing hardening contract.
- Application-level retries create a new explicit Go attempt and therefore may
  draw a new profile. State-changing HTTP requests are not automatically
  replayed by the transport.

Response/event metadata records the selected profile name and Sentinel SDK
version for diagnostics without recording cookies, tokens, mailbox keys, or
proxy credentials.

## 8. Performance and Concurrency

The selected profile lookup and random draw occur once per attempt. TLS
connections, cookies, and the OpenAI client are reused for the entire state
machine. SDK downloads and compilation are cached and coalesced; Goja runtimes
are isolated per action and are never shared concurrently.

The existing service concurrency admission remains in force. Sentinel work is
bounded by context and the daemon’s authentication concurrency setting. No
global profile-selection mutex is placed on the hot path.

## 9. Test Strategy

Implementation follows red-green-refactor TDD. Tests do not register a real
account or request an email OTP.

Python tests cover:

- API aliases and mutually exclusive mode normalization;
- `register_mode=go_protocol` dispatch to the dedicated Go bridge;
- proof that Go failures never import or call Python protocol classes;
- unchanged Python `protocol` behavior;
- phone/SMS rejection for Go mode;
- Web UI payload, saved form state, and mode labels.

Go tests cover:

- pool parsing, deduplication, invalid configuration, and all supported profile
  mappings;
- injectable deterministic selection and profile stability for one state
  machine run;
- coherent User-Agent and Client Hints;
- the standard-library/fhttp adapter, cookies, redirects, context cancellation,
  and response conversion against local servers;
- Sentinel URL validation, discovery, atomic cache, TTL, last-good fallback,
  bounded downloads, semantic patching of old/current fixture layouts,
  concurrent compile coalescing, VM timeout, and output validation;
- readiness success/failure and health metadata;
- local mock auth state-machine parity using the selected profile.

Verification includes Python focused tests and full unit tests, Ruff,
`go test -race ./...`, `go vet ./...`, and a Windows daemon build. An optional
non-mutating online smoke fetches the official frame and SDK and generates only
a requirements token. It does not use a mailbox, create an account, submit an
email, or trigger OTP delivery.

## 10. Compatibility and Documentation

`.env.example`, configuration documentation, UI copy, and build instructions
are updated for the new mode, Go 1.24.1 baseline, fingerprint pool, Sentinel
cache/TTL settings, and readiness fields. Existing API clients that do not send
the Go flag retain their current browser/Python protocol behavior.

No merge to `main` and no remote push are part of this implementation unless
the user requests them after verification.
