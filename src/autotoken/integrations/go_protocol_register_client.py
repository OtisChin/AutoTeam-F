from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
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
        self._started = False

    def _start_configured_binary(self) -> None:
        binary = Path(os.environ.get("GO_PROTOCOL_REGISTER_BIN") or "bin/protocol-registerd.exe").expanduser()
        if not binary.is_absolute():
            binary = (Path.cwd() / binary).resolve()
        if not binary.is_file():
            raise GoProtocolRegisterUnavailable("configured protocol-registerd binary is missing")
        try:
            subprocess.Popen(
                [str(binary)],
                cwd=str(binary.parent),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, ValueError) as exc:
            raise GoProtocolRegisterUnavailable("unable to start protocol-registerd") from exc
        self._started = True

    def health(self) -> dict[str, Any]:
        url = f"{self.base_url}/healthz"
        def _ensure_healthy(body: dict[str, Any]) -> dict[str, Any]:
            if not bool(body.get("ok")):
                raise GoProtocolRegisterUnavailable("protocol-registerd health check failed")
            return body
        try:
            return _ensure_healthy(_json_request(url, timeout=min(self.timeout, 5.0)))
        except GoProtocolRegisterUnavailable:
            if self._started or str(os.environ.get("GO_PROTOCOL_REGISTER_AUTO_START", "1") or "").strip().lower() not in {
                "1",
                "true",
                "yes",
                "on",
            }:
                raise
            self._start_configured_binary()
            deadline = time.monotonic() + min(10.0, max(1.0, self.timeout))
            while True:
                try:
                    return _ensure_healthy(_json_request(url, timeout=min(self.timeout, 1.0)))
                except GoProtocolRegisterUnavailable:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.1)

    def register(self, payload: dict[str, Any]) -> dict[str, Any]:
        return _json_request(f"{self.base_url}/v1/register", payload, timeout=self.timeout)


def go_response_to_protocol_result(response: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    if bool(response.get("success")):
        session_data = dict(response.get("session_data") or {})
        session_data.setdefault("email", response.get("email") or "")
        raw = dict(session_data.get("raw") or {})
        raw.setdefault("source", "go_protocol_register")
        session_data["raw"] = raw
        return True, {
            "status": 200,
            "data": session_data,
            "email": str(response.get("email") or session_data.get("email") or ""),
            "events": list(response.get("events") or []),
            "raw": raw,
        }

    error = dict(response.get("error") or {})
    reason = str(error.get("message") or response.get("status") or "go protocol register failed")
    status = str(response.get("status") or "").strip().lower()
    if status not in {"email_code_timeout", "phone_blocked", "account_deactivated", "register_failed", "exception"}:
        status = "register_failed"
    return False, {
        "status": status,
        "email": str(response.get("email") or ""),
        "reason": reason,
        "error": error,
        "events": list(response.get("events") or []),
        "raw": {"source": "go_protocol_register", "response": response},
    }
