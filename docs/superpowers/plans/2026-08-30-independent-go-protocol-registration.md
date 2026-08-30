# Independent Go Protocol Registration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a first-class `go_protocol` registration mode whose Python orchestration never enters the Python protocol implementation, while the Go daemon owns a stable per-attempt Chrome TLS/HTTP2 profile and a Go-native, dynamically refreshed Sentinel SDK runtime.

**Architecture:** The API and Vue form normalize five explicit registration modes and the manager dispatches Go work through a dedicated Python bridge. In the daemon, an immutable fingerprint pool selects one `tls-client` profile per request, a `net/http` adapter preserves the existing auth state machine, and a cached Goja provider discovers, patches, compiles, and executes the official Sentinel SDK. A live readiness source combines fingerprint validity and a Sentinel requirements dry-run and drives both `/healthz` and fail-closed admission.

**Tech Stack:** Python 3.10+, FastAPI/Pydantic, Vue 3/Vite, Go 1.24.1, `github.com/bogdanfinn/tls-client`, `github.com/bogdanfinn/fhttp`, `github.com/dop251/goja`, standard Go `net/http`, `httptest`, Pytest, Ruff.

## Global Constraints

- Go protocol registration is normalized as `register_mode=go_protocol`; `protocol` remains the Python implementation.
- Python may create mailboxes, orchestrate tasks, and persist results, but the Go bridge must not import or call `autotoken.auth.protocol_register`, `autotoken._protocol_register`, `AuthFlow`, or `Config`.
- `PROTOCOL_REGISTER_ENGINE` and `GO_PROTOCOL_FALLBACK_PYTHON` are ignored legacy settings and never alter dispatch or fallback.
- Phone-first and phone-only flows remain Python-only; API validation rejects them with Go mode before task creation.
- The only supported Go profiles are `chrome144`, `chrome146`, and `chrome150`; the default pool is exactly `chrome144,chrome146,chrome150`.
- One profile is selected with `crypto/rand` at the start of each explicit Go attempt and remains fixed throughout that attempt.
- Go baseline is exactly 1.24.1.
- Pin `github.com/bogdanfinn/tls-client` to `v1.15.2-0.20260702071810-b790a311273f`, the first reproducible upstream revision containing concrete Chrome 144, 146, and 150 profiles.
- Pin `github.com/dop251/goja` to `v0.0.0-20260603125802-cfe4039cb6d7`, whose module baseline remains compatible with Go 1.24.1.
- Sentinel executes inside the Go binary with `go:embed`; Python, Node, and an external JavaScript process are prohibited.
- Official SDK URLs must use HTTPS, host `sentinel.openai.com`, and path `/sentinel/<version>/sdk.js` with no credentials, non-default port, query, or fragment.
- Sentinel has no synthetic token fallback; empty, oversized, timed-out, or malformed output fails closed as `challenge_unavailable`.
- Tests must not register an account, submit an email to OpenAI, request an OTP, or mutate a real upstream account.
- Do not merge to `main` or push a remote in this implementation run.

## File Structure

### Python and Web

- `src/autotoken/api_routes/account_register_task.py`: request aliases, mode normalization, and pre-task phone-flow rejection.
- `src/autotoken/auth/go_protocol_register.py`: dedicated Go request bridge and mailbox payload construction.
- `src/autotoken/auth/protocol_register.py`: Python-only protocol registration after legacy Go dispatch is removed.
- `src/autotoken/interfaces/manager.py`: normalized-mode dispatch and shared result persistence.
- `web/src/components/RegisterAccountPage.vue`: single-valued registration engine selector, storage migration, and API payload.
- `web/scripts/test-go-protocol-register-ui.mjs`: source contract for label, persistence, exclusivity, and payload aliases.
- `tests/unit/test_account_register_task_routes.py`: API alias, normalization, and validation coverage.
- `tests/unit/test_go_protocol_register_dispatch.py`: dedicated bridge and no-fallback coverage.
- `tests/unit/test_registration_service.py`: manager dispatch coverage through the normalized mode.

### Go Fingerprint and Transport

- `go/protocol-register/internal/fingerprint/profile.go`: immutable supported-profile registry and coherent browser headers.
- `go/protocol-register/internal/fingerprint/pool.go`: strict pool parser and injectable random selection.
- `go/protocol-register/internal/httpclient/adapter.go`: `net/http` request/response conversion to `fhttp`.
- `go/protocol-register/internal/httpclient/client.go`: outer cookie/redirect client and inner `tls-client` construction.
- `go/protocol-register/internal/openai/headers.go`: profile-derived API/navigation/Sentinel headers.
- `go/protocol-register/internal/register/state_machine.go`: one selection/client per attempt and diagnostic metadata.
- `go/protocol-register/internal/register/auth_gate.go`: bounded auth phases that release capacity while mail polling waits.

### Go Sentinel and Readiness

- `go/protocol-register/internal/sentinel/config.go`: limits, URLs, timeouts, cache path, and environment parsing.
- `go/protocol-register/internal/sentinel/sdk.go`: official URL validation, frame discovery, candidate ordering, and metadata.
- `go/protocol-register/internal/sentinel/cache.go`: versioned source cache and atomic latest/last-good records.
- `go/protocol-register/internal/sentinel/patch.go`: validated semantic SDK patching.
- `go/protocol-register/internal/sentinel/compiler.go`: source loading, patching, Goja compilation, and per-version coalescing.
- `go/protocol-register/internal/sentinel/runtime.go`: isolated, interruptible Goja VMs and output validation.
- `go/protocol-register/internal/sentinel/runtime.js`: embedded browser compatibility adapter.
- `go/protocol-register/internal/sentinel/challenge.go`: bounded `/backend-api/sentinel/req` transport and JSON validation.
- `go/protocol-register/internal/sentinel/provider.go`: requirements/challenge/solve lifecycle and readiness status.
- `go/protocol-register/internal/readiness/state.go`: combined immutable pool plus live Sentinel health snapshot.
- `go/protocol-register/internal/server/routes.go`: dynamic health output and fail-closed admission.
- `go/protocol-register/cmd/protocol-registerd/main.go`: daemon bootstrap and dependency wiring.

## Dependency Order

1. Tasks 1-2 establish independent application dispatch.
2. Tasks 3-5 establish a real, stable Go transport.
3. Task 6 adds bounded auth-phase concurrency after the state machine owns a profiled client.
4. Tasks 7-9 establish Sentinel resolution, execution, and provider behavior.
5. Task 10 wires dynamic readiness and daemon startup.
6. Task 11 updates operator documentation and performs full verification.

---

### Task 1: Expose and normalize the `go_protocol` mode

**Files:**
- Modify: `src/autotoken/api_routes/account_register_task.py`
- Modify: `tests/unit/test_account_register_task_routes.py`
- Modify: `web/src/components/RegisterAccountPage.vue`
- Create: `web/scripts/test-go-protocol-register-ui.mjs`
- Modify: `web/package.json`

**Interfaces:**
- Consumes: Existing `ManualRegisterParams`, `cmd_register_accounts(...)`, and `api.startAdd(payload)`.
- Produces: `ManualRegisterParams.go_protocol_register: bool`, API alias `goProtocolRegister`, and normalized `register_mode="go_protocol"`.
- Produces: Vue `registerForm.registerEngine` with values `browser|protocol|go_protocol|roxy|cloak`.

- [x] **Step 1: Add failing API tests for aliases, precedence, and phone rejection**

```python
def _stub_register_dependencies(monkeypatch):
    monkeypatch.setattr("autotoken.runtime_config.get_register_domains", lambda: ["example.com"])
    monkeypatch.setattr("autotoken.runtime_config.get_register_domain", lambda: "example.com")
    monkeypatch.setattr("autotoken.identity.random_password", lambda: "generated-pass")
    monkeypatch.setattr("autotoken.setup_wizard.get_mail_provider", lambda value=None: value or "cloudmail")


def test_manual_register_params_accepts_camel_case_go_protocol():
    params = ManualRegisterParams.model_validate({"goProtocolRegister": True})
    assert params.go_protocol_register is True


def test_post_add_normalizes_go_protocol_mode(monkeypatch):
    started = []
    _stub_register_dependencies(monkeypatch)
    routes = _routes(started)
    result = routes["post_add"](ManualRegisterParams(go_protocol_register=True))
    assert result["params"]["register_mode"] == "go_protocol"
    assert started[0]["kwargs"]["register_mode"] == "go_protocol"


@pytest.mark.parametrize("payload", [
    {"registration_flow": "phone_cpa", "go_protocol_register": True},
    {"phone_only": True, "go_protocol_register": True},
])
def test_post_add_rejects_phone_flow_for_go_protocol(monkeypatch, payload):
    _stub_register_dependencies(monkeypatch)
    routes = _routes([])
    with pytest.raises(HTTPException) as exc_info:
        routes["post_add"](ManualRegisterParams(**payload))
    assert exc_info.value.status_code == 400
    assert "Go 协议注册不支持手机号注册流程" in exc_info.value.detail
```

- [x] **Step 2: Run the focused API tests and verify RED**

Run:

```powershell
$env:PYTHONPATH="$PWD\src"
& 'D:\code\OpenSource\AutoTeam-F\.venv\Scripts\python.exe' -m pytest tests/unit/test_account_register_task_routes.py -q
```

Expected: FAIL because `go_protocol_register` does not exist and Go phone flows are not rejected.

- [x] **Step 3: Implement deterministic server-side normalization**

Add the field and normalize in this order so legacy requests containing multiple booleans remain deterministic:

```python
go_protocol_register: bool = Field(
    False,
    validation_alias=AliasChoices("go_protocol_register", "goProtocolRegister"),
)

if params.go_protocol_register and (registration_flow != "standard" or bool(params.phone_only)):
    raise HTTPException(status_code=400, detail="Go 协议注册不支持手机号注册流程")

use_cloakbrowser = registration_flow == "standard" and bool(params.use_cloakbrowser)
use_roxybrowser = registration_flow == "standard" and bool(params.use_roxybrowser) and not use_cloakbrowser
use_go_protocol = (
    registration_flow == "standard"
    and bool(params.go_protocol_register)
    and not use_cloakbrowser
    and not use_roxybrowser
)
use_python_protocol = (
    bool(params.protocol_register)
    and not use_cloakbrowser
    and not use_roxybrowser
    and not use_go_protocol
)
register_mode = (
    "protocol" if registration_flow == "phone_cpa"
    else "cloak" if use_cloakbrowser
    else "roxy" if use_roxybrowser
    else "go_protocol" if use_go_protocol
    else "protocol" if use_python_protocol
    else "browser"
)
```

- [x] **Step 4: Add a failing UI source contract**

Create `web/scripts/test-go-protocol-register-ui.mjs`:

```javascript
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const page = readFileSync(new URL('../src/components/RegisterAccountPage.vue', import.meta.url), 'utf8')
assert.match(page, /Go 协议注册/, 'page exposes a distinct Go protocol label')
assert.match(page, /registerEngine:\s*'browser'/, 'form uses one engine value')
assert.match(page, /go_protocol_register:\s*!isPhoneCpaFlow\.value\s*&&\s*registerForm\.value\.registerEngine\s*===\s*'go_protocol'/, 'payload sends dedicated Go flag')
assert.match(page, /registerEngine:\s*registerForm\.value\.registerEngine/, 'saved form persists the engine')
assert.doesNotMatch(page, /v-model="registerForm\.goProtocolRegister"/, 'mode is not represented by an independent checkbox')
console.log('go protocol register UI tests passed')
```

Add `"test:go-protocol-register": "node scripts/test-go-protocol-register-ui.mjs"` to `web/package.json`.

- [x] **Step 5: Run the UI test and verify RED**

Run: `npm --prefix web run test:go-protocol-register`

Expected: FAIL because the label, single-valued engine, and payload field are absent.

- [x] **Step 6: Replace independent mode checkboxes with one persisted engine value**

Use radio inputs bound to `registerForm.registerEngine`, migrate old saved booleans with precedence `cloak > roxy > go_protocol > protocol > browser`, and construct the payload as:

```javascript
protocol_register: isPhoneCpaFlow.value || registerForm.value.registerEngine === 'protocol',
go_protocol_register: !isPhoneCpaFlow.value && registerForm.value.registerEngine === 'go_protocol',
use_roxybrowser: !isPhoneCpaFlow.value && registerForm.value.registerEngine === 'roxy',
use_cloakbrowser: !isPhoneCpaFlow.value && registerForm.value.registerEngine === 'cloak',
```

Persist only `registerEngine`; retain load-time migration from `protocolRegister`, `useRoxyBrowser`, and `useCloakBrowser` so existing browser storage remains valid.

- [x] **Step 7: Verify API and UI GREEN**

Run the Pytest command from Step 2, `npm --prefix web run test:go-protocol-register`, and `npm --prefix web run build`.

Expected: all commands PASS.

- [x] **Step 8: Commit the normalized mode surface**

```powershell
git add src/autotoken/api_routes/account_register_task.py tests/unit/test_account_register_task_routes.py web/src/components/RegisterAccountPage.vue web/scripts/test-go-protocol-register-ui.mjs web/package.json
git commit -m "feat(register): expose independent Go protocol mode"
```

---

### Task 2: Isolate the Python Go bridge and manager dispatch

**Files:**
- Create: `src/autotoken/auth/go_protocol_register.py`
- Modify: `src/autotoken/auth/protocol_register.py`
- Modify: `src/autotoken/interfaces/manager.py`
- Modify: `tests/unit/test_go_protocol_register_dispatch.py`
- Modify: `tests/unit/test_registration_service.py`

**Interfaces:**
- Consumes: `GoProtocolRegisterClient.health()`, `GoProtocolRegisterClient.register(payload)`, and `go_response_to_protocol_result(response)`.
- Produces: `autotoken.auth.go_protocol_register.register_once(mail_client, *, email, password, account_id=None, proxy=None) -> tuple[bool, dict]`.
- Produces: `_register_by_mode(register_mode, mail_client, **kwargs) -> tuple[bool, dict]` in the manager.

- [x] **Step 1: Replace legacy environment-switch tests with failing isolation tests**

```python
class CapturingGoClient:
    def __init__(self, captured):
        self.captured = captured

    def health(self):
        return {"ok": True, "protocol_ready": True}

    def register(self, payload):
        self.captured["payload"] = payload
        return {
            "success": True,
            "status": "success",
            "email": payload["email"],
            "session_data": {"accessToken": "go-access", "sessionToken": "go-session"},
            "events": [],
        }


class FailingGoClient:
    def __init__(self, **_kwargs):
        pass

    def health(self):
        raise GoProtocolRegisterServiceNotReady("not ready")


def test_python_protocol_ignores_legacy_go_engine(monkeypatch):
    monkeypatch.setenv("PROTOCOL_REGISTER_ENGINE", "go")
    monkeypatch.setenv("GO_PROTOCOL_FALLBACK_PYTHON", "1")
    monkeypatch.setattr(protocol_register, "_load_protocol_classes", lambda: (_FakeAuthFlow, _FakeConfig))
    ok, payload = protocol_register.register_once(FakeMailClient(), email="user@example.com", password="pw")
    assert ok is True
    assert payload["data"]["accessToken"] == "python-access"


def test_go_bridge_never_sends_impersonate(monkeypatch):
    monkeypatch.setenv("GO_PROTOCOL_IMPERSONATE", "chrome999")
    captured = {}
    monkeypatch.setattr(go_bridge, "GoProtocolRegisterClient", lambda **_kwargs: CapturingGoClient(captured))
    ok, _ = go_bridge.register_once(FakeMailClient(), email="user@example.com", password="pw")
    assert ok is True
    assert "impersonate" not in captured["payload"]["options"]


def test_go_bridge_failure_never_loads_python_protocol(monkeypatch):
    monkeypatch.setattr(protocol_register, "_load_protocol_classes", lambda: (_ for _ in ()).throw(AssertionError("Python protocol loaded")))
    monkeypatch.setattr(go_bridge, "GoProtocolRegisterClient", FailingGoClient)
    with pytest.raises(GoProtocolRegisterServiceNotReady):
        go_bridge.register_once(FakeMailClient(), email="user@example.com", password="pw")
```

- [x] **Step 2: Run bridge tests and verify RED**

Run:

```powershell
$env:PYTHONPATH="$PWD\src"
& 'D:\code\OpenSource\AutoTeam-F\.venv\Scripts\python.exe' -m pytest tests/unit/test_go_protocol_register_dispatch.py -q
```

Expected: FAIL because the dedicated bridge module and mode dispatcher are absent.

- [x] **Step 3: Implement the dedicated bridge without forbidden imports**

Create `src/autotoken/auth/go_protocol_register.py` with this public shape:

```python
from autotoken.integrations.go_protocol_register_client import (
    GoProtocolRegisterClient,
    go_response_to_protocol_result,
)


def register_once(mail_client, *, email: str, password: str, account_id=None, proxy: str | None = None):
    timeout_seconds = max(30, int(os.environ.get("OTP_TIMEOUT", "60") or 60))
    client = GoProtocolRegisterClient(timeout=max(90.0, float(timeout_seconds + 30)))
    client.health()
    response = client.register({
        "request_id": str(uuid.uuid4()),
        "email": email,
        "password": password,
        "proxy_url": proxy or "",
        "mail": _mail_payload(mail_client, email=email, account_id=account_id),
        "options": {
            "timeout_seconds": timeout_seconds,
            "trace": _env_flag("GO_PROTOCOL_TRACE", "0"),
        },
    })
    return go_response_to_protocol_result(response)
```

Keep `_mail_payload` and `_env_flag` local to this file. Do not import the Python protocol package.

- [x] **Step 4: Make `auth.protocol_register.register_once` Python-only**

Delete `GO_PROTOCOL_IMPERSONATE_DEFAULT`, `_go_protocol_enabled`, `_go_protocol_mail_payload`, `_register_once_go`, `_go_protocol_supported_request`, and all fallback branches. The first executable line of `register_once` must load `AuthFlow, Config` and continue the current Python path.

- [x] **Step 5: Add failing manager dispatch tests**

```python
def test_register_by_mode_dispatches_go_only(monkeypatch):
    calls = []
    monkeypatch.setattr(go_protocol_register, "register_once", lambda *a, **k: calls.append("go") or (True, {}))
    monkeypatch.setattr(protocol_register, "register_once", lambda *a, **k: (_ for _ in ()).throw(AssertionError("python called")))
    assert manager._register_by_mode("go_protocol", FakeMailClient(), email="u@example.com", password="pw")[0]
    assert calls == ["go"]


def test_register_by_mode_dispatches_python_protocol_only(monkeypatch):
    calls = []
    monkeypatch.setattr(protocol_register, "register_once", lambda *a, **k: calls.append("python") or (True, {}))
    assert manager._register_by_mode("protocol", FakeMailClient(), email="u@example.com", password="pw")[0]
    assert calls == ["python"]
```

- [x] **Step 6: Implement normalized manager dispatch and propagate browser modes**

Accept `browser|protocol|go_protocol|roxy|cloak` in `cmd_register_accounts`. Derive Roxy/Cloak flags from the normalized mode, pass Cloak through to `_register_direct_once`, and use:

```python
def _register_by_mode(register_mode, mail_client, **kwargs):
    if register_mode == "go_protocol":
        from autotoken.auth.go_protocol_register import register_once
        return register_once(mail_client, **kwargs)
    if register_mode in {"protocol", "http", "api"}:
        from autotoken.auth.protocol_register import register_once
        return register_once(mail_client, **kwargs)
    raise ValueError(f"unsupported protocol registration mode: {register_mode}")
```

Call this helper only for `protocol` and `go_protocol`; direct browser registration remains separate. Do not pass OAuth phone supplier arguments into the Go bridge.

- [x] **Step 7: Verify bridge and manager GREEN**

Run:

```powershell
$env:PYTHONPATH="$PWD\src"
& 'D:\code\OpenSource\AutoTeam-F\.venv\Scripts\python.exe' -m pytest tests/unit/test_go_protocol_register_dispatch.py tests/unit/test_registration_service.py tests/unit/test_account_register_task_routes.py -q
```

Expected: PASS with no network access.

- [x] **Step 8: Commit the isolated dispatch boundary**

```powershell
git add src/autotoken/auth/go_protocol_register.py src/autotoken/auth/protocol_register.py src/autotoken/interfaces/manager.py tests/unit/test_go_protocol_register_dispatch.py tests/unit/test_registration_service.py
git commit -m "refactor(register): isolate Go protocol dispatch"
```

---

### Task 3: Add the real Chrome fingerprint registry and random pool

**Files:**
- Modify: `go/protocol-register/go.mod`
- Create: `go/protocol-register/go.sum`
- Create: `go/protocol-register/internal/fingerprint/profile.go`
- Create: `go/protocol-register/internal/fingerprint/profile_test.go`
- Create: `go/protocol-register/internal/fingerprint/pool.go`
- Create: `go/protocol-register/internal/fingerprint/pool_test.go`
- Delete: `go/protocol-register/internal/openai/impersonation.go`
- Delete: `go/protocol-register/internal/openai/impersonation_test.go`

**Interfaces:**
- Produces: `fingerprint.Profile` with `Name`, `Major`, `TLSProfile`, `UserAgent`, client hints, header order, and pseudo-header order.
- Produces: `ParsePool(raw string) (Pool, error)`, `Pool.Names() []string`, and `Pool.Select(draw DrawFunc) (Profile, error)`.
- Produces: `CryptoDraw(max int) (int, error)`.

- [x] **Step 1: Pin the transport dependency and write failing profile registry tests**

Set `go 1.24.1` and pin `github.com/bogdanfinn/tls-client` to the exact
transport version from Global Constraints. Do not add Goja yet: `go mod tidy`
would remove that still-unused dependency before Task 8. Add tests that compare
registry entries to concrete upstream profile IDs:

```go
func TestLookupUsesConcreteTLSClientProfiles(t *testing.T) {
    tests := []struct {
        name string
        major int
        want profiles.ClientProfile
    }{
        {"chrome144", 144, profiles.Chrome_144},
        {"chrome146", 146, profiles.Chrome_146},
        {"chrome150", 150, profiles.Chrome_150},
    }
    for _, tt := range tests {
        got, ok := Lookup(tt.name)
        if !ok || got.Major != tt.major || got.TLSProfile.GetClientHelloStr() != tt.want.GetClientHelloStr() {
            t.Fatalf("%s=%#v ok=%t", tt.name, got, ok)
        }
        if !strings.Contains(got.UserAgent, fmt.Sprintf("Chrome/%d.0.0.0", tt.major)) {
            t.Fatalf("%s user-agent=%q", tt.name, got.UserAgent)
        }
    }
}
```

- [x] **Step 2: Write failing strict pool and deterministic-selection tests**

Cover empty input, whitespace, duplicate valid names, one unsupported name among valid names, invalid-only duplicates, deterministic draw, draw errors, and out-of-range draw values.

```go
func TestParsePoolNormalizesWhitespaceAndDuplicates(t *testing.T) {
    pool, err := ParsePool(" chrome144,chrome146, chrome144 ,chrome150 ")
    if err != nil || !reflect.DeepEqual(pool.Names(), []string{"chrome144", "chrome146", "chrome150"}) {
        t.Fatalf("pool=%v err=%v", pool.Names(), err)
    }
}

func TestPoolSelectUsesInjectedDrawOnce(t *testing.T) {
    pool, _ := ParsePool(DefaultPool)
    calls := 0
    got, err := pool.Select(func(max int) (int, error) { calls++; return 2, nil })
    if err != nil || got.Name != "chrome150" || calls != 1 {
        t.Fatalf("profile=%#v calls=%d err=%v", got, calls, err)
    }
}
```

- [x] **Step 3: Run fingerprint tests and verify RED**

Run: `go test ./internal/fingerprint -v` from `go/protocol-register`.

Expected: package build failure because the registry does not exist.

- [x] **Step 4: Implement immutable profiles and coherent browser values**

Use a private map backed by `profiles.Chrome_144`, `profiles.Chrome_146`, and `profiles.Chrome_150`. Build User-Agent and `sec-ch-ua` from the same `Major`; use Windows desktop values (`?0`, `"Windows"`) and Chrome pseudo-header order `:method,:authority,:scheme,:path`. Return cloned slices from exported accessors.

- [x] **Step 5: Implement strict parsing and `crypto/rand` selection**

```go
func CryptoDraw(max int) (int, error) {
    if max <= 0 {
        return 0, ErrEmptyPool
    }
    value, err := rand.Int(rand.Reader, big.NewInt(int64(max)))
    if err != nil {
        return 0, fmt.Errorf("draw fingerprint profile: %w", err)
    }
    return int(value.Int64()), nil
}
```

Reject the whole configured pool if any non-empty item is unsupported. Deduplicate valid names while preserving configuration order.

- [x] **Step 6: Verify GREEN and tidy modules**

Run:

```powershell
go test ./internal/fingerprint -v
go mod tidy
go test ./...
```

Expected: all commands PASS and `go.sum` is generated.

- [x] **Step 7: Commit the registry**

```powershell
git add go/protocol-register/go.mod go/protocol-register/go.sum go/protocol-register/internal/fingerprint go/protocol-register/internal/openai/impersonation.go go/protocol-register/internal/openai/impersonation_test.go
git commit -m "feat(go-protocol): add real Chrome fingerprint pool"
```

---

### Task 4: Adapt `net/http` to `tls-client`/`fhttp`

**Files:**
- Create: `go/protocol-register/internal/httpclient/adapter.go`
- Create: `go/protocol-register/internal/httpclient/adapter_test.go`
- Modify: `go/protocol-register/internal/httpclient/client.go`
- Create: `go/protocol-register/internal/httpclient/client_test.go`

**Interfaces:**
- Consumes: `fingerprint.Profile` and `tls_client.HttpClient`.
- Produces: `NewProfiled(profile fingerprint.Profile, proxyURL string, timeout time.Duration) (*http.Client, error)`.
- Produces: `NewStandard(timeout time.Duration) *http.Client` for mailbox polling.
- Produces: an internal `fhttpDoer` interface for deterministic adapter tests.

- [x] **Step 1: Write failing conversion tests with a capturing `fhttpDoer`**

```go
type captureDoer struct {
    request *fhttp.Request
    response *fhttp.Response
    err error
}

func (d *captureDoer) Do(req *fhttp.Request) (*fhttp.Response, error) {
    d.request = req
    return d.response, d.err
}

func TestRoundTripConvertsRequestAndResponse(t *testing.T) {
    doer := &captureDoer{response: &fhttp.Response{
        Status: "201 Created", StatusCode: 201, Proto: "HTTP/2.0", ProtoMajor: 2,
        Header: fhttp.Header{"Set-Cookie": {"session=one; Path=/"}},
        Body: io.NopCloser(strings.NewReader("ok")), ContentLength: 2,
    }}
    profile, _ := fingerprint.Lookup("chrome146")
    transport := newRoundTripper(doer, profile)
    req, _ := http.NewRequest(http.MethodPost, "https://example.test/path", strings.NewReader("body"))
    req.Header.Set("User-Agent", profile.UserAgent)
    resp, err := transport.RoundTrip(req)
    if err != nil || resp.StatusCode != 201 || resp.Request != req {
        t.Fatalf("resp=%#v err=%v", resp, err)
    }
    if doer.request.Context() != req.Context() || doer.request.Header.Get("User-Agent") != profile.UserAgent {
        t.Fatalf("converted request=%#v", doer.request)
    }
}
```

- [x] **Step 2: Add failing cookie, redirect, cancellation, and header-order tests**

Use an `httptest.Server` behind an `fhttp.Client` to prove the outer standard client consumes `Set-Cookie`, performs the second redirect request, and sends the cookie. Use a blocking fake doer to prove cancellation reaches the inner request context. Assert `fhttp.HeaderOrderKey` and `fhttp.PHeaderOrderKey` are populated from the selected profile and are never serialized back to the outer response.

- [x] **Step 3: Run adapter tests and verify RED**

Run: `go test ./internal/httpclient -v`.

Expected: build failure because the adapter and profiled constructor are absent.

- [x] **Step 4: Implement lossless request/response conversion**

The `RoundTrip` method must create an `fhttp.Request` with the original context, method, URL, body, content length, host, transfer encoding, and cloned headers. Convert the returned status, protocol, headers, trailers, body, and content length into a standard `http.Response` whose `Request` is the original request. Return errors without reading or replaying request bodies.

- [x] **Step 5: Construct one inner client and one outer jar per attempt**

Use:

```go
options := []tls_client.HttpClientOption{
    tls_client.WithClientProfile(profile.TLSProfile),
    tls_client.WithNotFollowRedirects(),
    tls_client.WithTimeoutMilliseconds(int(timeout.Milliseconds())),
}
if proxyURL != "" {
    options = append(options, tls_client.WithProxyUrl(proxyURL))
}
inner, err := tls_client.NewHttpClient(nil, options...)
jar, _ := cookiejar.New(nil)
return &http.Client{
    Transport: newRoundTripper(inner, profile),
    Jar: jar,
    Timeout: timeout,
}, nil
```

Do not add an inner cookie jar and do not enable inner redirects. Implement `CloseIdleConnections` forwarding on the adapter.

- [x] **Step 6: Verify GREEN and race safety**

Run:

```powershell
go test ./internal/httpclient -v
go test -race ./internal/httpclient
go test ./...
```

Expected: PASS; the tests show two outer redirect calls and one shared inner connection-capable client.

- [x] **Step 7: Commit the transport adapter**

```powershell
git add go/protocol-register/internal/httpclient
git commit -m "feat(go-protocol): use tls-client transport adapter"
```

---

### Task 5: Bind one profile to the complete registration state machine

**Files:**
- Modify: `go/protocol-register/internal/openai/headers.go`
- Modify: `go/protocol-register/internal/openai/headers_test.go`
- Modify: `go/protocol-register/internal/openai/auth_api.go`
- Modify: `go/protocol-register/internal/openai/auth_api_test.go`
- Modify: `go/protocol-register/internal/openai/sentinel.go`
- Modify: `go/protocol-register/internal/register/state_machine.go`
- Modify: `go/protocol-register/internal/register/state_machine_test.go`
- Modify: `go/protocol-register/internal/model/response.go`

**Interfaces:**
- Consumes: `fingerprint.Pool.Select`, `httpclient.NewProfiled`, and `httpclient.NewStandard`.
- Produces: `openai.SentinelResult{Token, SDKVersion string}` and `SentinelProvider.Token(ctx context.Context, client *http.Client, profile fingerprint.Profile, deviceID, flow string) (SentinelResult, error)`.
- Produces: response `metadata.fingerprint_profile` and `metadata.sentinel_sdk_version`.

- [x] **Step 1: Write failing profile stability and legacy-field-ignore tests**

Inject a draw function that records calls and returns Chrome 144. Execute the full local auth fixture with `Options.Impersonate="chrome999"`. Assert the draw runs once, every OpenAI and Sentinel call sees Chrome 144, every browser request carries a Chrome 144 User-Agent/client hints, and the mailbox request carries neither auth cookies nor browser client hints.

```go
if drawCalls != 1 {
    t.Fatalf("profile draw calls=%d, want 1", drawCalls)
}
if got := resp.Metadata["fingerprint_profile"]; got != "chrome144" {
    t.Fatalf("profile metadata=%q", got)
}
```

- [x] **Step 2: Run state-machine tests and verify RED**

Run: `go test ./internal/openai ./internal/register -v`.

Expected: FAIL because the current state machine resolves `go-http` from the request field and has no profile metadata.

- [x] **Step 3: Make OpenAI headers consume the immutable profile**

Change `NewClient` to store `fingerprint.Profile`, and have API/navigation header builders set User-Agent, `sec-ch-ua`, `sec-ch-ua-mobile`, `sec-ch-ua-platform`, `Sec-Fetch-*`, `Accept-Language`, and `Priority` from that profile. Endpoint-specific Origin and Referer remain unchanged.

- [x] **Step 4: Select before client construction and retain the profile value**

Add `FingerprintPool`, `Draw`, `ProfiledClientFactory`, and `MailboxClientFactory` to `HTTPRegisterEngineConfig`. Default the draw to `fingerprint.CryptoDraw`. At the beginning of `Register`, select once, create one profiled client, and pass the same profile and client through OpenAI and all Sentinel calls. Continue accepting `options.impersonate` in the JSON model but never read it.

Add a retryable TLS/network failure test whose injected profiled client fails on the first request. Assert the response has `error.retryable=true`, the draw count remains one, and no second profile/client is constructed inside that attempt.

- [x] **Step 5: Add non-secret diagnostics to success and failure responses**

Add:

```go
type RegisterResponse struct {
    // existing fields
    Metadata map[string]string `json:"metadata,omitempty"`
}
```

Always record the selected profile after selection. Record the SDK version after the first successful Sentinel result. Mirror both values in successful `session_data.raw`; do not record proxy URLs, mailbox URLs, cookies, tokens, passwords, or OTP values.

- [x] **Step 6: Verify GREEN**

Run:

```powershell
go test ./internal/openai ./internal/register -v
go test ./...
```

Expected: PASS and the local parity test proves one profile/client is reused across redirects, cookies, Sentinel calls, and session extraction.

- [x] **Step 7: Commit the attempt-scoped profile behavior**

```powershell
git add go/protocol-register/internal/openai go/protocol-register/internal/register go/protocol-register/internal/model/response.go
git commit -m "feat(go-protocol): keep fingerprint stable per attempt"
```

---

### Task 6: Enforce auth-phase concurrency without blocking on mail polling

**Files:**
- Create: `go/protocol-register/internal/register/auth_gate.go`
- Create: `go/protocol-register/internal/register/auth_gate_test.go`
- Modify: `go/protocol-register/internal/register/state_machine.go`
- Modify: `go/protocol-register/internal/register/state_machine_test.go`

**Interfaces:**
- Consumes: `HTTPRegisterEngineConfig.AuthConcurrency`.
- Produces: context-aware `authGate.acquire(ctx) (release func(), err error)`.

- [x] **Step 1: Write failing gate cancellation and parallelism tests**

Test capacity normalization, a second acquire blocking while the first is held, immediate release on context cancellation, and no leaked slot after an error.

- [x] **Step 2: Write a failing two-attempt integration test**

Use local auth and mail servers with barriers. With `AuthConcurrency=1`, prove that at most one auth handler is active, attempt two can enter its initial auth phase while attempt one waits for mailbox polling, and both mailbox pollers can be inflight independently.

- [x] **Step 3: Run register tests and verify RED**

Run: `go test ./internal/register -run 'AuthGate|AuthConcurrency' -v`.

Expected: FAIL because `AuthConcurrency` is not enforced.

- [x] **Step 4: Split the state machine into bounded auth phases**

Acquire before CSRF through `SendEmailOTP`, release before `WaitForOTP`, then reacquire for `VerifyEmailOTP` through session extraction. Use `defer release()` inside focused phase functions so every return path releases the slot. Sentinel execution therefore always occurs under the auth gate.

- [x] **Step 5: Verify GREEN under the race detector**

Run:

```powershell
go test ./internal/register -v
go test -race ./internal/register
```

Expected: PASS with maximum observed auth concurrency equal to one in the integration fixture.

- [x] **Step 6: Commit the concurrency boundary**

```powershell
git add go/protocol-register/internal/register/auth_gate.go go/protocol-register/internal/register/auth_gate_test.go go/protocol-register/internal/register/state_machine.go go/protocol-register/internal/register/state_machine_test.go
git commit -m "perf(go-protocol): bound authentication phases"
```

---

### Task 7: Resolve and cache official Sentinel SDK candidates

**Files:**
- Create: `go/protocol-register/internal/sentinel/config.go`
- Create: `go/protocol-register/internal/sentinel/config_test.go`
- Create: `go/protocol-register/internal/sentinel/sdk.go`
- Create: `go/protocol-register/internal/sentinel/sdk_test.go`
- Create: `go/protocol-register/internal/sentinel/cache.go`
- Create: `go/protocol-register/internal/sentinel/cache_test.go`
- Create: `go/protocol-register/internal/sentinel/testdata/frame-current.html`

**Interfaces:**
- Produces: `sentinel.Config`, `SDK{Version, URL, Source string}`, and `Resolver.Candidates(ctx, client) ([]SDK, error)`.
- Produces: `Resolver.Source(ctx, client, sdk) ([]byte, error)` and `Resolver.MarkGood(sdk) error`.

- [x] **Step 1: Write failing URL and frame-discovery tests**

Accept only `https://sentinel.openai.com/sentinel/<version>/sdk.js`. Explicitly reject HTTP, subdomains, userinfo, port 444, query, fragment, escaped path separators, extra path segments, and versions outside `[A-Za-z0-9][A-Za-z0-9._-]{2,63}`. Parse the first valid script source from the bounded official frame fixture.

- [x] **Step 2: Write failing candidate-order and TTL tests**

Use an injected clock and fake HTTP client to cover: validated URL override, validated version override, fresh cache without discovery, discovery replacing stale cache, discovery failure falling back to stale cache, last-good after the current candidate, built-in last, and deduplication by version plus URL.

- [x] **Step 3: Write failing bounded-download and atomic-cache tests**

Assert discovery HTML over 1 MiB and SDK source over 4 MiB are rejected. After writes, assert `latest.json`, `last-good.json`, and `<version>.js` contain complete valid data and no temporary file remains. Corrupt cache records must be ignored rather than trusted.

- [x] **Step 4: Run Sentinel resolver tests and verify RED**

Run: `go test ./internal/sentinel -run 'URL|Discover|Cache|Candidates|Download' -v`.

Expected: package build failure because the resolver does not exist.

- [x] **Step 5: Implement configuration and strict official URL validation**

Use Go-owned environment names:

```text
GO_PROTOCOL_SENTINEL_SDK_URL
GO_PROTOCOL_SENTINEL_SDK_VERSION
GO_PROTOCOL_SENTINEL_CACHE_DIR
GO_PROTOCOL_SENTINEL_SDK_TTL_SECONDS
GO_PROTOCOL_SENTINEL_HTTP_TIMEOUT_SECONDS
GO_PROTOCOL_SENTINEL_VM_TIMEOUT_SECONDS
```

Defaults are a six-hour TTL, 10-second discovery/download timeout, 45-second VM timeout, official frame URL, official request URL, and built-in version `20260219f9f6`.

- [x] **Step 6: Implement bounded discovery, candidate ordering, and atomic cache writes**

Use `io.LimitReader(limit+1)`, `golang.org/x/net/html` tokenization, `os.CreateTemp` in the destination directory, `File.Sync`, close, and `os.Rename`. Cache source by validated version only; never derive a filesystem name from unvalidated input.

- [x] **Step 7: Verify GREEN and race safety**

Run:

```powershell
go test ./internal/sentinel -run 'URL|Discover|Cache|Candidates|Download' -v
go test -race ./internal/sentinel -run 'Cache|Candidates'
```

Expected: PASS without contacting the network.

- [x] **Step 8: Commit the resolver**

```powershell
git add go/protocol-register/internal/sentinel/config.go go/protocol-register/internal/sentinel/config_test.go go/protocol-register/internal/sentinel/sdk.go go/protocol-register/internal/sentinel/sdk_test.go go/protocol-register/internal/sentinel/cache.go go/protocol-register/internal/sentinel/cache_test.go go/protocol-register/internal/sentinel/testdata/frame-current.html
git commit -m "feat(go-protocol): resolve official Sentinel SDK"
```

---

### Task 8: Patch, compile, and execute Sentinel in isolated Goja VMs

**Files:**
- Modify: `go/protocol-register/go.mod`
- Modify: `go/protocol-register/go.sum`
- Create: `go/protocol-register/internal/sentinel/runtime.js`
- Create: `go/protocol-register/internal/sentinel/patch.go`
- Create: `go/protocol-register/internal/sentinel/patch_test.go`
- Create: `go/protocol-register/internal/sentinel/compiler.go`
- Create: `go/protocol-register/internal/sentinel/compiler_test.go`
- Create: `go/protocol-register/internal/sentinel/runtime.go`
- Create: `go/protocol-register/internal/sentinel/runtime_test.go`
- Create: `go/protocol-register/internal/sentinel/testdata/sdk-old.js`
- Create: `go/protocol-register/internal/sentinel/testdata/sdk-current.js`

**Interfaces:**
- Consumes: validated SDK bytes from `Resolver.Source`.
- Produces: `CompiledSDK{SDK SDK, Program *goja.Program}`.
- Produces: `Compiler.Compile(ctx, client, sdk) (*CompiledSDK, error)` with one in-flight compile per version/source hash.
- Produces: `Runtime.Requirements(ctx, compiled, profile, deviceID) (string, error)` and `Runtime.Solve(ctx, compiled, profile, SolveInput) (SolveOutput, error)`.

- [x] **Step 1: Pin Goja and add old/current semantic patch fixtures and failing tests**

Pin `github.com/dop251/goja` to
`v0.0.0-20260603125802-cfe4039cb6d7`. Each fixture must contain a minimal SDK
export, proof instance, proof WeakMap binding, and turnstile solver in the two
layouts observed by existing Python integration fixtures. Assert patching
exposes exactly `globalThis.SentinelSDK`, `globalThis.__debugP`,
`SentinelSDK.__debug_n`, and `SentinelSDK.__debug_bindProof`. Zero or multiple
matches must return an unsupported-SDK error.

- [x] **Step 2: Add failing compile-coalescing tests**

Start 32 goroutines requesting the same version/source. Instrument the patch/compile function and assert exactly one call, all goroutines receive the same immutable `*goja.Program`, and a failed compile is delivered to all waiters and removed so a later call can retry.

- [x] **Step 3: Add failing runtime success, timeout, and output-limit tests**

Use fixture SDKs to return deterministic requirements and solve outputs. Add an infinite-loop fixture and cancel its context; assert `*goja.InterruptedError` is converted to `ErrRuntimeTimeout`. Reject pending promises, empty `request_p`, empty `final_p`, empty `t`, non-string values, and output over 64 KiB.

- [x] **Step 4: Run runtime tests and verify RED**

Run: `go test ./internal/sentinel -run 'Patch|Compile|Runtime|Requirements|Solve' -v`.

Expected: FAIL because patching, compilation, and Goja execution are absent.

- [x] **Step 5: Implement one-time semantic patching and immutable compilation**

Patch source in Go with anchored, uniqueness-checked regular expressions equivalent to the proven Python adapter semantics. Concatenate the embedded compatibility runtime, patched SDK, and exported action wrappers, then call `goja.Compile("sentinel-<version>.js", source, true)`. Key compile coalescing by `version + sha256(source)`.

- [x] **Step 6: Implement the embedded compatibility runtime**

`runtime.js` installs bounded synchronous implementations for `window`, `self`, `document`, `navigator`, `screen`, `performance`, storage, base64, URL, text encoding, events, timers, `crypto.getRandomValues`, and browser fields derived from `fingerprint.Profile`. It exports:

```javascript
async function __sentinelRequirements(payload) {
  __installSentinelRuntime(payload)
  return { request_p: await globalThis.__debugP.getRequirementsToken() }
}

async function __sentinelSolve(payload) {
  __installSentinelRuntime(payload)
  const finalP = await globalThis.__debugP.getEnforcementToken(payload.challenge)
  globalThis.SentinelSDK.__debug_bindProof(payload.challenge, payload.request_p)
  const dx = payload.challenge?.turnstile?.dx
  const t = dx ? await globalThis.SentinelSDK.__debug_n(payload.challenge, dx) : ""
  return { final_p: finalP, t }
}
```

Host `fetch` must throw; all network traffic remains in Go.

- [x] **Step 7: Implement per-action VM isolation and interruption**

Create a new `goja.Runtime` for each action, run the cached program, invoke one exported function, and inspect the returned `*goja.Promise`. Start one goroutine that calls `vm.Interrupt(ctx.Err())` on cancellation and always stop it via a `done` channel. Never reuse a runtime concurrently.

- [x] **Step 8: Verify GREEN and race safety**

Run:

```powershell
go test ./internal/sentinel -run 'Patch|Compile|Runtime|Requirements|Solve' -v
go test -race ./internal/sentinel -run 'Compile|Runtime'
```

Expected: PASS; compile count is one and every execution uses a distinct VM.

- [x] **Step 9: Commit the embedded runtime**

```powershell
git add go/protocol-register/go.mod go/protocol-register/go.sum go/protocol-register/internal/sentinel/runtime.js go/protocol-register/internal/sentinel/patch.go go/protocol-register/internal/sentinel/patch_test.go go/protocol-register/internal/sentinel/compiler.go go/protocol-register/internal/sentinel/compiler_test.go go/protocol-register/internal/sentinel/runtime.go go/protocol-register/internal/sentinel/runtime_test.go go/protocol-register/internal/sentinel/testdata/sdk-old.js go/protocol-register/internal/sentinel/testdata/sdk-current.js
git commit -m "feat(go-protocol): execute Sentinel SDK with Goja"
```

---

### Task 9: Complete the Sentinel requirements/challenge/solve provider

**Files:**
- Create: `go/protocol-register/internal/sentinel/challenge.go`
- Create: `go/protocol-register/internal/sentinel/challenge_test.go`
- Create: `go/protocol-register/internal/sentinel/provider.go`
- Create: `go/protocol-register/internal/sentinel/provider_test.go`
- Modify: `go/protocol-register/internal/openai/sentinel.go`
- Modify: `go/protocol-register/internal/openai/sentinel_test.go`

**Interfaces:**
- Consumes: `Resolver`, `Compiler`, `Runtime`, selected profiled `*http.Client`, and `fingerprint.Profile`.
- Produces: an `openai.SentinelProvider` implementation and `Provider.DryRun(ctx, client, profile) Status`.
- Produces: `Provider.Status() Status`, where `type Status struct { Ready bool; SDKVersion string; Reason string }`.

- [x] **Step 1: Write failing bounded challenge transport tests**

Assert POST method, `text/plain;charset=UTF-8`, exact `{p,id,flow}` request body, official Referer/Origin, selected profile headers, context cancellation, 1 MiB response limit, JSON-object requirement, non-empty challenge token, and sanitized errors that exclude body contents.

- [x] **Step 2: Write failing provider candidate and fallback tests**

Cover these exact rules:

1. Compile or requirements incompatibility advances to the next deduplicated candidate.
2. Challenge transport failure returns immediately and performs exactly one challenge POST.
3. Solve incompatibility may advance to the next candidate with a fresh requirements/challenge cycle.
4. A candidate is marked last-known-good only after requirements, challenge, solve, and final token validation all succeed.
5. No candidate success returns `openai.ErrChallengeUnavailable`; no synthetic token is constructed.

- [x] **Step 3: Write failing dry-run and status tests**

`DryRun` must resolve/download/compile and produce a non-empty requirements token without calling the challenge endpoint. A failed refresh retains readiness only when a previously validated last-good compiled candidate remains executable.

- [x] **Step 4: Run provider tests and verify RED**

Run: `go test ./internal/sentinel ./internal/openai -run 'Challenge|Provider|DryRun|Unavailable' -v`.

Expected: FAIL because no production provider exists.

- [x] **Step 5: Implement challenge transport and final token validation**

Serialize the final token with `json.Marshal` from:

```go
type finalToken struct {
    P string `json:"p"`
    T string `json:"t"`
    C string `json:"c"`
    ID string `json:"id"`
    Flow string `json:"flow"`
}
```

Require non-empty `P`, `T`, `C`, `ID`, and `Flow`, and enforce the 64 KiB generated-output limit before returning `openai.SentinelResult`.

- [x] **Step 6: Implement candidate lifecycle and last-good updates**

Keep resolver/compiler caches behind mutexes, but place no global lock around `Token`. Per-action runtimes remain independent. Update status atomically after dry-run or successful full cycles; transient challenge failures do not globally disable an already ready provider.

- [x] **Step 7: Verify GREEN and concurrency safety**

Run:

```powershell
go test ./internal/sentinel ./internal/openai -v
go test -race ./internal/sentinel ./internal/openai
```

Expected: PASS and no challenge retry occurs for transport failures.

- [x] **Step 8: Commit the production provider**

```powershell
git add go/protocol-register/internal/sentinel/challenge.go go/protocol-register/internal/sentinel/challenge_test.go go/protocol-register/internal/sentinel/provider.go go/protocol-register/internal/sentinel/provider_test.go go/protocol-register/internal/openai/sentinel.go go/protocol-register/internal/openai/sentinel_test.go
git commit -m "feat(go-protocol): complete Sentinel challenge provider"
```

---

### Task 10: Compute readiness and expose live health metadata

**Files:**
- Create: `go/protocol-register/internal/readiness/state.go`
- Create: `go/protocol-register/internal/readiness/state_test.go`
- Modify: `go/protocol-register/internal/server/routes.go`
- Modify: `go/protocol-register/internal/server/routes_test.go`
- Modify: `go/protocol-register/cmd/protocol-registerd/main.go`
- Modify: `go/protocol-register/cmd/protocol-registerd/main_test.go`

**Interfaces:**
- Consumes: parsed `fingerprint.Pool` and `sentinel.Provider.Status()`.
- Produces: `readiness.Source.Snapshot() Snapshot`, where `Snapshot` contains `ProtocolReady bool`, `FingerprintPool []string`, `SentinelReady bool`, `SentinelSDKVersion string`, and `ReadyReason string`.
- Produces: health JSON fields `protocol_ready`, `fingerprint_pool`, `sentinel_ready`, `sentinel_sdk_version`, and `ready_reason`.

- [x] **Step 1: Write failing combined-readiness tests**

Assert readiness requires both a non-empty valid pool and ready Sentinel status. Preserve the exact component reason for invalid pool, SDK resolution failure, compile failure, and requirements dry-run failure. Assert a ready last-good provider remains protocol-ready after a failed refresh.

- [x] **Step 2: Extend failing route tests for live health and fail-closed reason**

Inject a mutable fake source, request `/healthz`, mutate it, request again, and prove the second response changes. When unready, `/v1/register` must return HTTP 503 without calling the engine and include a sanitized `service_not_ready` reason.

- [x] **Step 3: Add failing bootstrap tests**

Set `GO_PROTOCOL_FINGERPRINT_POOL` to valid, duplicate, empty, and unsupported values. Inject a fake Sentinel provider/dry-run so tests prove `loadRuntime` does not hard-code readiness and that the default names are exactly 144/146/150.

- [x] **Step 4: Run readiness/server/main tests and verify RED**

Run:

```powershell
go test ./internal/readiness ./internal/server ./cmd/protocol-registerd -v
```

Expected: FAIL because `ProtocolReady` is a static boolean and main hard-codes false.

- [x] **Step 5: Implement live snapshots and route admission**

Replace static `ProtocolReady` with a `HealthSource` interface:

```go
type HealthSource interface {
    Snapshot() readiness.Snapshot
}
```

Read one snapshot per request. Health always returns HTTP 200 and `ok=true` when the process is running. Registration returns 503 whenever the same snapshot has `ProtocolReady=false`.

- [x] **Step 6: Wire daemon bootstrap and startup dry-run**

Parse the pool first, construct the Sentinel resolver/compiler/runtime/provider, run a bounded requirements dry-run, construct the combined source, and start the HTTP server regardless of readiness. Pass the same pool/provider to `HTTPRegisterEngine`; set `AuthConcurrency` from `GO_PROTOCOL_AUTH_CONCURRENCY`.

- [x] **Step 7: Verify GREEN**

Run:

```powershell
go test ./internal/readiness ./internal/server ./cmd/protocol-registerd -v
go test ./...
```

Expected: PASS; startup tests show no account, email, OTP, or `/sentinel/req` mutation.

- [x] **Step 8: Commit dynamic readiness**

```powershell
git add go/protocol-register/internal/readiness go/protocol-register/internal/server go/protocol-register/cmd/protocol-registerd
git commit -m "feat(go-protocol): compute daemon readiness"
```

---

### Task 11: Document, benchmark, and verify the complete implementation

**Files:**
- Modify: `.env.example`
- Modify: `docs/configuration.md`
- Modify: `README.md`
- Create: `go/protocol-register/internal/fingerprint/pool_benchmark_test.go`
- Create: `go/protocol-register/internal/sentinel/online_smoke_test.go`
- Modify: `docs/superpowers/plans/2026-08-30-independent-go-protocol-registration.md`

**Interfaces:**
- Consumes: all completed behavior.
- Produces: operator configuration, benchmark evidence, optional non-mutating online smoke, and checked plan boxes.

- [x] **Step 1: Add a parallel selection benchmark and compile-cache stress test**

```go
func BenchmarkPoolSelectParallel(b *testing.B) {
    pool, _ := ParsePool(DefaultPool)
    b.ReportAllocs()
    b.RunParallel(func(pb *testing.PB) {
        for pb.Next() {
            if _, err := pool.Select(CryptoDraw); err != nil {
                b.Fatal(err)
            }
        }
    })
}
```

Retain the 32-goroutine compile coalescing test under `go test -race` as the cache stress check.

- [x] **Step 2: Add an explicitly gated online smoke**

`online_smoke_test.go` must call `t.Skip` unless `GO_PROTOCOL_SENTINEL_ONLINE_SMOKE=1`. When enabled, it may fetch only the official frame and SDK and execute `DryRun`; it must use no mailbox, email, password, `/v1/register`, or challenge request.

- [x] **Step 3: Update environment and operator docs**

Replace active legacy settings with:

```env
GO_PROTOCOL_REGISTER_URL=http://127.0.0.1:18787
GO_PROTOCOL_REGISTER_AUTO_START=1
GO_PROTOCOL_REGISTER_BIN=bin/protocol-registerd.exe
GO_PROTOCOL_MAX_CONCURRENCY=20
GO_PROTOCOL_AUTH_CONCURRENCY=3
GO_PROTOCOL_FINGERPRINT_POOL=chrome144,chrome146,chrome150
GO_PROTOCOL_TRACE=0
GO_PROTOCOL_SENTINEL_CACHE_DIR=
GO_PROTOCOL_SENTINEL_SDK_TTL_SECONDS=21600
GO_PROTOCOL_SENTINEL_HTTP_TIMEOUT_SECONDS=10
GO_PROTOCOL_SENTINEL_VM_TIMEOUT_SECONDS=45
```

Document `PROTOCOL_REGISTER_ENGINE`, `GO_PROTOCOL_FALLBACK_PYTHON`, and `GO_PROTOCOL_IMPERSONATE` as ignored legacy names. Document exact health fields, Go 1.24.1, the pinned dependency commit, cache refresh/last-good semantics, and that Go failures never enter Python protocol code.

- [x] **Step 4: Run focused Python and UI verification**

```powershell
$env:PYTHONPATH="$PWD\src"
$python='D:\code\OpenSource\AutoTeam-F\.venv\Scripts\python.exe'
& $python -m pytest tests/unit/test_account_register_task_routes.py tests/unit/test_go_protocol_register_dispatch.py tests/unit/test_go_protocol_register_client.py tests/unit/test_registration_service.py -q
npm --prefix web ci
npm --prefix web run test:go-protocol-register
npm --prefix web run build
```

Expected: all commands PASS.

- [ ] **Step 5: Run the full Python suite and Ruff**

```powershell
$env:PYTHONPATH="$PWD\src"
$python='D:\code\OpenSource\AutoTeam-F\.venv\Scripts\python.exe'
& $python -m pytest -q
& 'D:\code\OpenSource\AutoTeam-F\.venv\Scripts\ruff.exe' check src tests
```

Expected: PASS with no unexpected warnings.

Verification note (2026-08-30): the repository-wide baseline is not green. The
full suite completed with `2173 passed, 105 failed`; failures are concentrated
in unrelated PayPal, packaging, CLI, mail/provider, and test-order-sensitive
legacy suites. Full Ruff reports 162 existing findings in those same unrelated
areas. All eight Python test files changed by this branch pass (`170 passed`),
and Ruff passes all 17 changed Python files. Step 5 remains unchecked rather
than treating feature-scoped evidence as a repository-wide pass.

- [x] **Step 6: Run Go race, vet, benchmark, and Windows build verification**

From `go/protocol-register`:

```powershell
go test -race ./...
go vet ./...
go test ./internal/fingerprint -run '^$' -bench BenchmarkPoolSelectParallel -benchmem
$env:GOOS='windows'; $env:GOARCH='amd64'; go build -o '..\..\bin\protocol-registerd.verify.exe' ./cmd/protocol-registerd
Remove-Item -LiteralPath '..\..\bin\protocol-registerd.verify.exe'
Remove-Item Env:GOOS
Remove-Item Env:GOARCH
```

Expected: tests and vet PASS, benchmark reports no shared-state race, and the Windows binary builds successfully.

- [x] **Step 7: Run static isolation and secret scans**

```powershell
rg -n "PROTOCOL_REGISTER_ENGINE|GO_PROTOCOL_FALLBACK_PYTHON|GO_PROTOCOL_IMPERSONATE" src web go/protocol-register
rg -n "autotoken\.auth\.protocol_register|autotoken\._protocol_register|AuthFlow|Config" src/autotoken/auth/go_protocol_register.py
rg -n "password|accessToken|sessionToken|receive_code_url|proxy_url" go/protocol-register/internal --glob '*.go'
```

Expected: the first command finds no active dispatch reads, the second finds no matches, and every third-command match is a contract field or redaction test rather than a log statement.

- [x] **Step 8: Perform final diff review and update plan checkboxes**

Run `git diff --check`, `git status --short`, and `git log --oneline --decorate -12`. Review that only planned files changed, all generated binaries are removed, and `go.sum` is committed.

- [x] **Step 9: Commit documentation and verification assets**

```powershell
git add .env.example README.md docs/configuration.md go/protocol-register/internal/fingerprint/pool_benchmark_test.go go/protocol-register/internal/sentinel/online_smoke_test.go docs/superpowers/plans/2026-08-30-independent-go-protocol-registration.md
git commit -m "docs(go-protocol): document independent runtime"
```

## Requirements Trace

| Requirement | Implemented by |
| --- | --- |
| Dedicated API/UI mode and aliases | Task 1 |
| No Python fallback/import path | Task 2 |
| Python protocol behavior unchanged | Task 2 |
| Real 144/146/150 pool and random fixed selection | Tasks 3 and 5 |
| `net/http` compatibility over `tls-client` | Task 4 |
| Coherent UA/client hints/header order | Tasks 3-5 |
| Mailbox client isolation | Tasks 4-5 |
| Bounded high-concurrency auth phases | Task 6 |
| Official SDK discovery, TTL, cache, last-good | Task 7 |
| Embedded Goja runtime, semantic patch, VM interruption | Task 8 |
| Requirements/challenge/solve and no synthetic fallback | Task 9 |
| Computed readiness and detailed health | Task 10 |
| Operator docs, race/vet/build checks, non-mutating smoke | Task 11 |
