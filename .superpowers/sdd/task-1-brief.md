### Task 1: Python-Go Contract and Client Wrapper

**Files:**
- Create: `tests/fixtures/go_protocol_register/register_request_generic_api.json`
- Create: `tests/fixtures/go_protocol_register/register_success_response.json`
- Create: `tests/fixtures/go_protocol_register/email_code_timeout_response.json`
- Create: `tests/fixtures/go_protocol_register/phone_required_response.json`
- Create: `tests/unit/test_go_protocol_register_client.py`
- Create: `src/autotoken/integrations/go_protocol_register_client.py`

**Interfaces:**
- Produces: `GoProtocolRegisterClient(base_url: str | None = None, timeout: float = 190.0)`.
- Produces: `GoProtocolRegisterClient.health() -> dict[str, Any]`.
- Produces: `GoProtocolRegisterClient.register(payload: dict[str, Any]) -> dict[str, Any]`.
- Produces: `go_response_to_protocol_result(response: dict[str, Any]) -> tuple[bool, dict[str, Any]]`.

- [ ] **Step 1: Write contract fixtures**

Create `tests/fixtures/go_protocol_register/register_request_generic_api.json`:

```json
{
  "request_id": "test-request-1",
  "email": "user@example.com",
  "password": "Password123$",
  "proxy_url": "",
  "mail": {
    "provider": "generic-api",
    "account_id": "user@example.com",
    "receive_code_url": "https://mail.example.test/mail-api/code?to=user%40example.com&timeout=60&key=secret-key",
    "issued_after_unix": 1787650000
  },
  "options": {
    "timeout_seconds": 180,
    "trace": false,
    "impersonate": "chrome136"
  }
}
```

Create `tests/fixtures/go_protocol_register/register_success_response.json`:

```json
{
  "success": true,
  "status": "success",
  "email": "user@example.com",
  "session_data": {
    "email": "user@example.com",
    "accessToken": "access-token-1",
    "sessionToken": "session-token-1",
    "cookies": [],
    "raw": {"source": "go_protocol_register"}
  },
  "events": [{"stage": "otp_verified", "message": "email OTP verified"}]
}
```

Create `tests/fixtures/go_protocol_register/email_code_timeout_response.json`:

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

Create `tests/fixtures/go_protocol_register/phone_required_response.json`:

```json
{
  "success": false,
  "status": "phone_blocked",
  "email": "user@example.com",
  "error": {
    "code": "phone_required",
    "message": "OpenAI requested phone verification",
    "retryable": false,
    "step": "create_account"
  },
  "events": [{"stage": "phone_required", "message": "phone verification required"}]
}
```

- [ ] **Step 2: Write failing Python tests**

Create `tests/unit/test_go_protocol_register_client.py`:

```python
import json
from pathlib import Path

import pytest

from autotoken.integrations.go_protocol_register_client import (
    GoProtocolRegisterClient,
    GoProtocolRegisterUnavailable,
    go_response_to_protocol_result,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "go_protocol_register"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_success_response_maps_to_protocol_result():
    ok, session_data = go_response_to_protocol_result(_fixture("register_success_response.json"))
    assert ok is True
    assert session_data["email"] == "user@example.com"
    assert session_data["accessToken"] == "access-token-1"
    assert session_data["sessionToken"] == "session-token-1"
    assert session_data["raw"]["source"] == "go_protocol_register"


def test_timeout_response_maps_to_failure_payload():
    ok, session_data = go_response_to_protocol_result(_fixture("email_code_timeout_response.json"))
    assert ok is False
    assert session_data["status"] == "email_code_timeout"
    assert session_data["reason"] == "email OTP not received within timeout"
    assert session_data["error"]["code"] == "email_code_timeout"


def test_phone_required_response_maps_to_phone_blocked():
    ok, session_data = go_response_to_protocol_result(_fixture("phone_required_response.json"))
    assert ok is False
    assert session_data["status"] == "phone_blocked"
    assert session_data["reason"] == "OpenAI requested phone verification"


def test_client_health_raises_unavailable_for_connection_error():
    client = GoProtocolRegisterClient(base_url="http://127.0.0.1:9", timeout=0.01)
    with pytest.raises(GoProtocolRegisterUnavailable):
        client.health()
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'
uv run --no-sync pytest tests/unit/test_go_protocol_register_client.py -q
```

Expected: FAIL because `src/autotoken/integrations/go_protocol_register_client.py` does not exist.

- [ ] **Step 4: Implement minimal Python client**

Create `src/autotoken/integrations/go_protocol_register_client.py`:

```python
from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


class GoProtocolRegisterUnavailable(RuntimeError):
    pass


def _base_url(value: str | None = None) -> str:
    return str(value or os.environ.get("GO_PROTOCOL_REGISTER_URL") or "http://127.0.0.1:18787").rstrip("/")


def _json_request(url: str, payload: dict[str, Any] | None = None, *, timeout: float = 190.0) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers={"Accept": "application/json"})
    if payload is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except (OSError, URLError, TimeoutError) as exc:
        raise GoProtocolRegisterUnavailable(str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise GoProtocolRegisterUnavailable(f"invalid Go protocol-register JSON response: {exc}") from exc


class GoProtocolRegisterClient:
    def __init__(self, base_url: str | None = None, timeout: float = 190.0):
        self.base_url = _base_url(base_url)
        self.timeout = float(timeout or 190.0)

    def health(self) -> dict[str, Any]:
        return _json_request(f"{self.base_url}/healthz", timeout=min(self.timeout, 5.0))

    def register(self, payload: dict[str, Any]) -> dict[str, Any]:
        return _json_request(f"{self.base_url}/v1/register", payload, timeout=self.timeout)


def go_response_to_protocol_result(response: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    if bool(response.get("success")):
        session_data = dict(response.get("session_data") or {})
        session_data.setdefault("email", response.get("email") or "")
        raw = dict(session_data.get("raw") or {})
        raw.setdefault("source", "go_protocol_register")
        session_data["raw"] = raw
        return True, session_data

    error = dict(response.get("error") or {})
    reason = str(error.get("message") or response.get("status") or "go protocol register failed")
    return False, {
        "status": str(response.get("status") or error.get("code") or "register_failed"),
        "email": str(response.get("email") or ""),
        "reason": reason,
        "error": error,
        "events": list(response.get("events") or []),
        "raw": {"source": "go_protocol_register", "response": response},
    }
```

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
uv run --no-sync pytest tests/unit/test_go_protocol_register_client.py -q
git add src/autotoken/integrations/go_protocol_register_client.py tests/unit/test_go_protocol_register_client.py tests/fixtures/go_protocol_register
git commit -m "feat(protocol): add Go register client contract"
```

Expected: tests PASS and commit succeeds.

---

