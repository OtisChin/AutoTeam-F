# Protocol Registration P0 Request Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent protocol registration from amplifying failed authentication attempts through unsafe retries, profile rotation, synthetic challenge fallback, cross-engine replay, or unbounded OTP delivery.

**Architecture:** Keep the current Python protocol flow as the reference engine, but introduce fail-closed boundaries and explicit mutation budgets. Classify Go daemon startup failures separately from indeterminate registration failures so only pre-request failures can fall back. Preserve backward compatibility only through explicit opt-in environment flags.

**Tech Stack:** Python 3.12, pytest, requests/urllib3, curl_cffi, Go client bridge, Ruff

## Global Constraints

- No state-changing HTTP request may be retried automatically by a transport.
- One logical attempt uses one configured client profile and one cookie jar.
- Synthetic Sentinel fallback is disabled by default.
- Go-to-Python fallback is allowed only before `/v1/register` is sent.
- One attempt may issue one initial email OTP request and one resend request.
- New behavior is test-first and all focused Python/Go tests remain green.
- No real account registration is part of automated verification.

---

### Task 1: Restrict HTTP transport retries to safe methods

**Files:**
- Modify: `src/autotoken/_protocol_register/http_client.py`
- Create: `tests/unit/test_protocol_http_client.py`

**Interfaces:**
- Produces: `build_safe_retry_policy() -> urllib3.util.retry.Retry`
- Consumes: `create_http_session(proxy: str | None, impersonate: str)`

- [ ] **Step 1: Write the failing retry-policy test**

```python
from autotoken._protocol_register import http_client


def test_protocol_retry_policy_excludes_state_changing_methods():
    policy = http_client.build_safe_retry_policy()
    assert policy.allowed_methods == frozenset({"GET", "HEAD", "OPTIONS"})
    assert "POST" not in policy.allowed_methods
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
$env:PYTHONPATH="$PWD/src"
& 'D:\code\OpenSource\AutoTeam-F\.venv\Scripts\python.exe' -m pytest -q tests/unit/test_protocol_http_client.py
```

Expected: FAIL because `build_safe_retry_policy` does not exist.

- [ ] **Step 3: Add the safe retry-policy factory and use it**

```python
def build_safe_retry_policy() -> Retry:
    return Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset({"GET", "HEAD", "OPTIONS"}),
        respect_retry_after_header=True,
    )


# requests fallback in create_http_session
adapter = HTTPAdapter(max_retries=build_safe_retry_policy())
```

- [ ] **Step 4: Run the focused test and verify GREEN**

Run the command from Step 2.

Expected: `1 passed`.

- [ ] **Step 5: Commit**

```powershell
git add src/autotoken/_protocol_register/http_client.py tests/unit/test_protocol_http_client.py
git commit -m "fix(protocol): stop retrying auth mutations"
```

---

### Task 2: Keep one client profile for an attempt

**Files:**
- Modify: `src/autotoken/_protocol_register/http_client.py`
- Modify: `src/autotoken/_protocol_register/auth_flow.py`
- Modify: `tests/unit/test_protocol_http_client.py`
- Modify: `tests/unit/test_protocol_auth_flow_errors.py`

**Interfaces:**
- Produces: `user_agent_for_impersonate(profile: str) -> str`
- Produces: `AuthFlow._impersonate_profile: str`
- Changes: `AuthFlow._rotate_impersonate_session() -> bool` always reports no in-attempt rotation

- [ ] **Step 1: Write failing tests for stable profile behavior**

```python
def test_user_agent_matches_configured_chrome_profile():
    assert "Chrome/136.0.0.0" in http_client.user_agent_for_impersonate("chrome136")


def test_auth_flow_does_not_rotate_profile_after_tls_failure(monkeypatch):
    flow = _new_flow_without_network(monkeypatch)
    original = flow.session
    assert flow._rotate_impersonate_session() is False
    assert flow.session is original
```

- [ ] **Step 2: Run both tests and verify RED**

```powershell
$env:PYTHONPATH="$PWD/src"
& 'D:\code\OpenSource\AutoTeam-F\.venv\Scripts\python.exe' -m pytest -q tests/unit/test_protocol_http_client.py tests/unit/test_protocol_auth_flow_errors.py -k "profile or rotate"
```

Expected: FAIL because profile-derived UA and stable-session behavior are missing.

- [ ] **Step 3: Implement a configured immutable profile**

```python
_CHROME_PROFILE = re.compile(r"^chrome(\d+)$", re.IGNORECASE)


def user_agent_for_impersonate(profile: str) -> str:
    match = _CHROME_PROFILE.fullmatch(str(profile or "").strip())
    version = int(match.group(1)) if match else 136
    return (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{version}.0.0.0 Safari/537.36"
    )
```

```python
self._impersonate_profile = (
    os.getenv("OPENAI_HTTP_IMPERSONATE", "chrome136").strip() or "chrome136"
)
self.session = create_http_session(
    proxy=config.proxy,
    impersonate=self._impersonate_profile,
)
self._user_agent = user_agent_for_impersonate(self._impersonate_profile)
```

Replace `_rotate_impersonate_session` with a fail-stable implementation that logs
the TLS failure and returns `False` without replacing `self.session`. Use
`self._user_agent` in `_common_headers` and OAuth initialization.

- [ ] **Step 4: Run focused tests and the complete protocol error suite**

```powershell
$env:PYTHONPATH="$PWD/src"
& 'D:\code\OpenSource\AutoTeam-F\.venv\Scripts\python.exe' -m pytest -q tests/unit/test_protocol_http_client.py tests/unit/test_protocol_auth_flow_errors.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/autotoken/_protocol_register/http_client.py src/autotoken/_protocol_register/auth_flow.py tests/unit/test_protocol_http_client.py tests/unit/test_protocol_auth_flow_errors.py
git commit -m "fix(protocol): keep auth client profile stable"
```

---

### Task 3: Fail closed when Sentinel execution is unavailable

**Files:**
- Modify: `src/autotoken/_protocol_register/sentinel.py`
- Modify: `src/autotoken/_protocol_register/sentinel_quickjs.py`
- Modify: `tests/unit/test_sentinel_sdk_integration.py`
- Modify: `.env.example`
- Modify: `docs/configuration.md`

**Interfaces:**
- Produces: `SentinelUnavailable(RuntimeError)`
- Produces: `_subprocess_env(extra: dict[str, str]) -> dict[str, str]`
- Adds compatibility flag: `OPENAI_SENTINEL_ALLOW_SYNTHETIC_FALLBACK=0`

- [ ] **Step 1: Write failing tests for fail-closed behavior and scrubbed environment**

```python
def test_sentinel_fails_closed_when_quickjs_is_unavailable(monkeypatch):
    monkeypatch.delenv("OPENAI_SENTINEL_ALLOW_SYNTHETIC_FALLBACK", raising=False)
    monkeypatch.setattr(sentinel_quickjs, "get_sentinel_token_via_quickjs", lambda *a, **k: None)
    with pytest.raises(sentinel.SentinelUnavailable):
        sentinel.get_sentinel_token(FakeSession(), "device-1")


def test_quickjs_subprocess_environment_excludes_application_secrets(monkeypatch):
    monkeypatch.setenv("APPLICATION_SECRET_FOR_TEST", "do-not-inherit")
    env = sentinel_quickjs._subprocess_env({"OPENAI_SENTINEL_VM_TIMEOUT_MS": "1000"})
    assert "APPLICATION_SECRET_FOR_TEST" not in env
    assert env["OPENAI_SENTINEL_VM_TIMEOUT_MS"] == "1000"
```

- [ ] **Step 2: Run the tests and verify RED**

```powershell
$env:PYTHONPATH="$PWD/src"
& 'D:\code\OpenSource\AutoTeam-F\.venv\Scripts\python.exe' -m pytest -q tests/unit/test_sentinel_sdk_integration.py -k "fails_closed or excludes_application_secrets"
```

Expected: FAIL because the exception and environment scrubber do not exist.

- [ ] **Step 3: Implement fail-closed behavior**

```python
class SentinelUnavailable(RuntimeError):
    pass


def _allow_synthetic_fallback() -> bool:
    return str(os.getenv("OPENAI_SENTINEL_ALLOW_SYNTHETIC_FALLBACK", "0")).strip().lower() in {
        "1", "true", "yes", "on"
    }
```

After QuickJS returns no token, raise `SentinelUnavailable` unless the explicit
compatibility flag is enabled. Keep the existing synthetic implementation only
inside that explicit compatibility branch.

Build the subprocess environment from a fixed allowlist containing Windows
process-launch variables (`PATH`, `SYSTEMROOT`, `WINDIR`, `COMSPEC`, `PATHEXT`,
`TEMP`, `TMP`) plus the three Sentinel runtime variables. Replace
`{**os.environ, ...}` in `subprocess.run` with this scrubbed dictionary.

- [ ] **Step 4: Document the new default**

Add to `.env.example`:

```dotenv
# Sentinel execution fails closed by default; legacy synthetic fallback is unsupported.
OPENAI_SENTINEL_ALLOW_SYNTHETIC_FALLBACK=0
```

Document that failures stop protocol registration or require an explicitly
selected supported browser flow.

- [ ] **Step 5: Run Sentinel tests and Ruff**

```powershell
$env:PYTHONPATH="$PWD/src"
& 'D:\code\OpenSource\AutoTeam-F\.venv\Scripts\python.exe' -m pytest -q tests/unit/test_sentinel_sdk.py tests/unit/test_sentinel_sdk_integration.py
& 'D:\code\OpenSource\AutoTeam-F\.venv\Scripts\ruff.exe' check src/autotoken/_protocol_register/sentinel.py src/autotoken/_protocol_register/sentinel_quickjs.py tests/unit/test_sentinel_sdk_integration.py
```

Expected: tests and Ruff pass.

- [ ] **Step 6: Commit**

```powershell
git add src/autotoken/_protocol_register/sentinel.py src/autotoken/_protocol_register/sentinel_quickjs.py tests/unit/test_sentinel_sdk_integration.py .env.example docs/configuration.md
git commit -m "fix(protocol): fail closed on sentinel errors"
```

---

### Task 4: Permit Python fallback only for Go startup failures

**Files:**
- Modify: `src/autotoken/integrations/go_protocol_register_client.py`
- Modify: `src/autotoken/auth/protocol_register.py`
- Modify: `tests/unit/test_go_protocol_register_client.py`
- Modify: `tests/unit/test_go_protocol_register_dispatch.py`

**Interfaces:**
- Produces: `GoProtocolRegisterStartupUnavailable`
- Produces: `GoProtocolRegisterIndeterminate`
- Changes: `_json_request(..., failure_type=...)`
- Changes: `register_once` catches only startup failures for Python fallback

- [ ] **Step 1: Write failing exception-classification tests**

```python
def test_register_transport_failure_is_indeterminate(monkeypatch):
    monkeypatch.setattr(go_client, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("reset")))
    client = go_client.GoProtocolRegisterClient(base_url="http://127.0.0.1:1")
    with pytest.raises(go_client.GoProtocolRegisterIndeterminate):
        client.register({"email": "user@example.com"})


def test_indeterminate_go_failure_does_not_fallback_to_python(monkeypatch):
    monkeypatch.setenv("PROTOCOL_REGISTER_ENGINE", "go")
    monkeypatch.setenv("GO_PROTOCOL_FALLBACK_PYTHON", "1")
    monkeypatch.setattr(
        protocol_register,
        "_register_once_go",
        lambda *a, **k: (_ for _ in ()).throw(GoProtocolRegisterIndeterminate("reset")),
    )
    with pytest.raises(GoProtocolRegisterIndeterminate):
        protocol_register.register_once(FakeMailClient(), email="user@example.com", password="pw")
```

- [ ] **Step 2: Run tests and verify RED**

```powershell
$env:PYTHONPATH="$PWD/src"
& 'D:\code\OpenSource\AutoTeam-F\.venv\Scripts\python.exe' -m pytest -q tests/unit/test_go_protocol_register_client.py tests/unit/test_go_protocol_register_dispatch.py -k "indeterminate or fallback"
```

Expected: FAIL because startup and indeterminate failures are not distinct.

- [ ] **Step 3: Implement typed failures**

```python
class GoProtocolRegisterStartupUnavailable(GoProtocolRegisterUnavailable):
    pass


class GoProtocolRegisterIndeterminate(GoProtocolRegisterUnavailable):
    pass
```

`health()` and binary-start failures use `GoProtocolRegisterStartupUnavailable`.
`register()` uses `GoProtocolRegisterIndeterminate` for connection, timeout, and
invalid-response failures after request dispatch. In `protocol_register.py`, catch
only `GoProtocolRegisterStartupUnavailable` for configured Python fallback.

Use `uuid.uuid4()` for `request_id` instead of a millisecond timestamp.

- [ ] **Step 4: Run Go bridge tests**

```powershell
$env:PYTHONPATH="$PWD/src"
& 'D:\code\OpenSource\AutoTeam-F\.venv\Scripts\python.exe' -m pytest -q tests/unit/test_go_protocol_register_client.py tests/unit/test_go_protocol_register_dispatch.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/autotoken/integrations/go_protocol_register_client.py src/autotoken/auth/protocol_register.py tests/unit/test_go_protocol_register_client.py tests/unit/test_go_protocol_register_dispatch.py
git commit -m "fix(protocol): prevent cross-engine replay"
```

---

### Task 5: Enforce email OTP delivery and verification budgets

**Files:**
- Modify: `src/autotoken/_protocol_register/auth_flow.py`
- Modify: `tests/unit/test_protocol_auth_flow_errors.py`
- Modify: `.env.example`
- Modify: `docs/configuration.md`

**Interfaces:**
- Produces: `OtpDeliveryBudgetExceeded(RuntimeError)`
- Adds state: `_email_otp_send_attempts`, `_email_otp_resend_attempts`
- Default: `OPENAI_EMAIL_OTP_VERIFY_MAX_ATTEMPTS=2`
- Default: `OPENAI_EMAIL_OTP_MAX_RESENDS=1`

- [ ] **Step 1: Write failing budget tests**

```python
def test_email_otp_initial_delivery_is_attempted_once(monkeypatch):
    flow = _flow_with_recording_session(monkeypatch, [200, 200])
    flow.send_otp()
    with pytest.raises(OtpDeliveryBudgetExceeded):
        flow.send_otp()
    assert flow.session.request_count("/api/accounts/email-otp/send") == 1


def test_kickoff_does_not_cascade_to_other_otp_endpoints(monkeypatch):
    flow = _flow_with_recording_session(monkeypatch, [500])
    assert flow.kickoff_otp_delivery("register_password_success") is False
    assert flow.session.paths == ["/api/accounts/email-otp/send"]


def test_email_otp_resend_is_attempted_once(monkeypatch):
    flow = _flow_with_recording_session(monkeypatch, [200, 200])
    assert flow.resend_otp() is True
    assert flow.resend_otp() is False
    assert flow.session.request_count("/api/accounts/email-otp/resend") == 1
```

- [ ] **Step 2: Run tests and verify RED**

```powershell
$env:PYTHONPATH="$PWD/src"
& 'D:\code\OpenSource\AutoTeam-F\.venv\Scripts\python.exe' -m pytest -q tests/unit/test_protocol_auth_flow_errors.py -k "otp_initial_delivery or does_not_cascade or resend_is_attempted_once"
```

Expected: FAIL because delivery counters and strict endpoint selection are absent.

- [ ] **Step 3: Add mutation counters and strict delivery selection**

Initialize counters in `AuthFlow.__init__`. Increment before dispatch so a timeout
still consumes the mutation budget. `send_otp` raises when the initial budget is
already consumed. `resend_otp` returns `False` when its configured budget is
consumed.

Replace the fallback cascade with:

```python
def kickoff_otp_delivery(self, mode: str = "") -> bool:
    mode_lc = str(mode or "").strip().lower()
    if mode_lc in {"register_password_success", "register_password_failed_fallback"}:
        try:
            self.send_otp()
            return True
        except Exception as exc:
            logger.warning("initial OTP delivery failed: %s", safe_error_summary(exc, limit=180))
            return False
    return self.resend_otp("https://auth.openai.com/email-verification")
```

Change `_email_otp_verify_max_attempts` default from three to two. Remove direct
`send_otp()` fallbacks after `kickoff_otp_delivery()` returns `False`; raise a
clear delivery error instead.

- [ ] **Step 4: Update existing OTP tests and documentation**

Existing tests that assert passwordless/send cascades must instead assert one
state-specific endpoint. Add to `.env.example`:

```dotenv
OPENAI_EMAIL_OTP_VERIFY_MAX_ATTEMPTS=2
OPENAI_EMAIL_OTP_MAX_RESENDS=1
```

- [ ] **Step 5: Run the complete protocol suite**

```powershell
$env:PYTHONPATH="$PWD/src"
& 'D:\code\OpenSource\AutoTeam-F\.venv\Scripts\python.exe' -m pytest -q tests/unit/test_protocol_auth_flow_errors.py tests/unit/test_go_protocol_register_client.py tests/unit/test_go_protocol_register_dispatch.py tests/unit/test_sentinel_sdk.py tests/unit/test_sentinel_sdk_integration.py tests/unit/test_protocol_http_client.py
& 'D:\code\OpenSource\AutoTeam-F\.venv\Scripts\ruff.exe' check src/autotoken/_protocol_register src/autotoken/auth/protocol_register.py src/autotoken/integrations/go_protocol_register_client.py tests/unit/test_protocol_auth_flow_errors.py tests/unit/test_protocol_http_client.py tests/unit/test_go_protocol_register_client.py tests/unit/test_go_protocol_register_dispatch.py tests/unit/test_sentinel_sdk.py tests/unit/test_sentinel_sdk_integration.py
```

Expected: all tests and Ruff pass.

- [ ] **Step 6: Commit**

```powershell
git add src/autotoken/_protocol_register/auth_flow.py tests/unit/test_protocol_auth_flow_errors.py .env.example docs/configuration.md
git commit -m "fix(protocol): bound email OTP mutations"
```

---

### Task 6: P0 verification and rollout documentation

**Files:**
- Modify: `docs/configuration.md`
- Test: all focused Python and Go protocol tests

**Interfaces:**
- Consumes all behavior from Tasks 1-5.
- Produces a documented safe-default rollout contract.

- [ ] **Step 1: Document safe defaults and migration behavior**

Document:

- Python remains the default engine.
- Go fallback is startup-only.
- Synthetic Sentinel fallback requires explicit legacy opt-in.
- Profile rotation is removed.
- OTP delivery is bounded to one initial request and one resend.

- [ ] **Step 2: Run all focused verification**

```powershell
$env:PYTHONPATH="$PWD/src"
& 'D:\code\OpenSource\AutoTeam-F\.venv\Scripts\python.exe' -m pytest -q tests/unit/test_account_register_task_routes.py tests/unit/test_go_protocol_register_client.py tests/unit/test_go_protocol_register_dispatch.py tests/unit/test_protocol_auth_flow_errors.py tests/unit/test_protocol_http_client.py tests/unit/test_sentinel_sdk.py tests/unit/test_sentinel_sdk_integration.py
Push-Location go/protocol-register
go test -count=1 ./...
go vet ./...
Pop-Location
```

Expected: Python and Go suites pass.

- [ ] **Step 3: Check diff hygiene**

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors; only intended files are modified.

- [ ] **Step 4: Commit documentation if it was not included earlier**

```powershell
git add docs/configuration.md .env.example
git diff --cached --quiet; if ($LASTEXITCODE -ne 0) { git commit -m "docs(protocol): document safe registration defaults" }
```
