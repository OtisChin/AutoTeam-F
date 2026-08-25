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
