### Task 5: Python Opt-In Dispatch and Configuration

**Files:**
- Create: `tests/unit/test_go_protocol_register_dispatch.py`
- Modify: `src/autotoken/auth/protocol_register.py`
- Modify: `.env.example`
- Modify: `docs/configuration.md`
- Create: `scripts/build-go-protocol-register.ps1`

**Interfaces:**
- Consumes: `GoProtocolRegisterClient.register(payload)` from Task 1.
- Produces: `PROTOCOL_REGISTER_ENGINE=go` dispatch path in `protocol_register.register_once()`.
- Produces: fallback behavior controlled by `GO_PROTOCOL_FALLBACK_PYTHON`.

- [ ] **Step 1: Write failing Python dispatch tests**

Create `tests/unit/test_go_protocol_register_dispatch.py`:

```python
from autotoken.auth import protocol_register


class FakeMailClient:
    provider_name = "generic-api"
    accounts = []


class FakeGoClient:
    def __init__(self, *args, **kwargs):
        pass

    def health(self):
        return {"ok": True}

    def register(self, payload):
        assert payload["email"] == "user@example.com"
        assert payload["password"] == "pw"
        assert payload["mail"]["provider"] == "generic-api"
        return {
            "success": True,
            "status": "success",
            "email": "user@example.com",
            "session_data": {"email": "user@example.com", "accessToken": "access", "sessionToken": "session"},
            "events": [],
        }


def test_register_once_uses_go_engine_when_enabled(monkeypatch):
    monkeypatch.setenv("PROTOCOL_REGISTER_ENGINE", "go")
    monkeypatch.setattr("autotoken.integrations.go_protocol_register_client.GoProtocolRegisterClient", FakeGoClient)
    ok, payload = protocol_register.register_once(FakeMailClient(), email="user@example.com", password="pw", account_id="user@example.com")
    assert ok is True
    assert payload["accessToken"] == "access"
    assert payload["sessionToken"] == "session"
```

- [ ] **Step 2: Run test to verify failure**

Run:

```powershell
uv run --no-sync pytest tests/unit/test_go_protocol_register_dispatch.py -q
```

Expected: FAIL because `register_once()` does not dispatch to Go.

- [ ] **Step 3: Implement Go dispatch in Python**

Add these helpers near `register_once()` in `src/autotoken/auth/protocol_register.py`:

```python
def _env_flag(name: str, default: str = "0") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in {"1", "true", "yes", "on"}


def _go_protocol_enabled() -> bool:
    return str(os.environ.get("PROTOCOL_REGISTER_ENGINE", "python") or "python").strip().lower() == "go"


def _go_protocol_mail_payload(mail_client, *, email: str, account_id: str | int | None = None) -> dict[str, Any]:
    provider = str(getattr(mail_client, "provider_name", "") or "").strip().lower()
    payload = {"provider": provider, "account_id": str(account_id or email), "receive_code_url": "", "issued_after_unix": int(time.time())}
    for account in getattr(mail_client, "accounts", []) or []:
        if str(getattr(account, "email", "") or "").strip().lower() == str(email or "").strip().lower():
            payload["receive_code_url"] = str(getattr(account, "receive_code_url", "") or "").strip()
            break
    return payload


def _register_once_go(mail_client, *, email: str, password: str, account_id=None, proxy: str | None = None, **_kwargs):
    from autotoken.integrations.go_protocol_register_client import GoProtocolRegisterClient, go_response_to_protocol_result

    timeout_seconds = max(30, int(os.environ.get("OTP_TIMEOUT", "60") or 60))
    client = GoProtocolRegisterClient(timeout=max(90.0, float(timeout_seconds + 30)))
    client.health()
    response = client.register({
        "request_id": f"autotoken-{int(time.time() * 1000)}",
        "email": email,
        "password": password,
        "proxy_url": proxy or "",
        "mail": _go_protocol_mail_payload(mail_client, email=email, account_id=account_id),
        "options": {"timeout_seconds": timeout_seconds, "trace": _env_flag("GO_PROTOCOL_TRACE", "0"), "impersonate": os.environ.get("GO_PROTOCOL_IMPERSONATE", "chrome136")},
    })
    return go_response_to_protocol_result(response)
```

At the top of `register_once()`, add:

```python
if _go_protocol_enabled():
    try:
        return _register_once_go(mail_client, email=email, password=password, account_id=account_id, proxy=proxy)
    except Exception as exc:
        if not _env_flag("GO_PROTOCOL_FALLBACK_PYTHON", "1"):
            raise
        logger.warning("Go 协议注册不可用，回退 Python 协议注册: %s", safe_error_summary(exc, limit=180))
```

- [ ] **Step 4: Add build script and docs**

Create `scripts/build-go-protocol-register.ps1`:

```powershell
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$OutDir = Join-Path $Root 'bin'
New-Item -ItemType Directory -Force $OutDir | Out-Null
Push-Location (Join-Path $Root 'go/protocol-register')
try {
  go test ./...
  go build -o (Join-Path $OutDir 'protocol-registerd.exe') ./cmd/protocol-registerd
} finally {
  Pop-Location
}
Write-Host "Built $OutDir\protocol-registerd.exe"
```

Append to `.env.example`:

```text
PROTOCOL_REGISTER_ENGINE=python
GO_PROTOCOL_REGISTER_URL=http://127.0.0.1:18787
GO_PROTOCOL_REGISTER_AUTO_START=1
GO_PROTOCOL_REGISTER_BIN=bin/protocol-registerd.exe
GO_PROTOCOL_MAX_CONCURRENCY=50
GO_PROTOCOL_FALLBACK_PYTHON=1
GO_PROTOCOL_TRACE=0
GO_PROTOCOL_IMPERSONATE=chrome136
```

Add to `docs/configuration.md`:

```markdown
## Go protocol registration service

`PROTOCOL_REGISTER_ENGINE=python` keeps the legacy Python protocol path. Set `PROTOCOL_REGISTER_ENGINE=go` to route `register_mode=protocol` through the local `protocol-registerd` service.

| Variable | Default | Purpose |
|---|---:|---|
| `GO_PROTOCOL_REGISTER_URL` | `http://127.0.0.1:18787` | Local service endpoint |
| `GO_PROTOCOL_REGISTER_AUTO_START` | `1` | Python may start the local binary |
| `GO_PROTOCOL_REGISTER_BIN` | `bin/protocol-registerd.exe` | Windows binary path |
| `GO_PROTOCOL_MAX_CONCURRENCY` | `50` | Maximum inflight Go registration tasks |
| `GO_PROTOCOL_FALLBACK_PYTHON` | `1` | Use Python path when Go service is unavailable |
| `GO_PROTOCOL_TRACE` | `0` | Include non-secret trace events |
| `GO_PROTOCOL_IMPERSONATE` | `chrome136` | Header/fingerprint label |
```

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'
uv run --no-sync pytest tests/unit/test_go_protocol_register_client.py tests/unit/test_go_protocol_register_dispatch.py tests/unit/test_manager_auth_session.py tests/unit/test_protocol_auth_flow_errors.py -q
uv run --no-sync ruff check src/autotoken/auth/protocol_register.py src/autotoken/integrations/go_protocol_register_client.py tests/unit/test_go_protocol_register_client.py tests/unit/test_go_protocol_register_dispatch.py
powershell -ExecutionPolicy Bypass -File scripts/build-go-protocol-register.ps1
git add src/autotoken/auth/protocol_register.py src/autotoken/integrations/go_protocol_register_client.py tests/unit/test_go_protocol_register_dispatch.py .env.example docs/configuration.md scripts/build-go-protocol-register.ps1
git commit -m "feat(protocol): route protocol register through Go service"
```

Expected: Python tests PASS, Ruff PASS, Go binary builds, and commit succeeds.

---

