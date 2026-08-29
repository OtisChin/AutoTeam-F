import json
import subprocess
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


def test_success_response_maps_to_python_persistence_shape():
    ok, session_data = go_response_to_protocol_result(_fixture("register_success_response.json"))
    assert ok is True
    assert session_data["status"] == 200
    assert session_data["data"]["email"] == "user@example.com"
    assert session_data["data"]["accessToken"] == "access-token-1"
    assert session_data["data"]["sessionToken"] == "session-token-1"
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


def test_client_health_raises_unavailable_when_body_is_not_ok(monkeypatch):
    monkeypatch.setattr(
        "autotoken.integrations.go_protocol_register_client._json_request",
        lambda *args, **kwargs: {"ok": False},
    )
    client = GoProtocolRegisterClient(timeout=1)
    with pytest.raises(GoProtocolRegisterUnavailable):
        client.health()


def test_client_auto_starts_configured_binary_and_retries_health(monkeypatch, tmp_path):
    binary = tmp_path / "protocol-registerd.exe"
    binary.write_bytes(b"fixture")
    monkeypatch.setenv("GO_PROTOCOL_REGISTER_AUTO_START", "1")
    monkeypatch.setenv("GO_PROTOCOL_REGISTER_BIN", str(binary))
    calls = []

    def fake_request(url, payload=None, *, timeout):
        calls.append(url)
        if len(calls) == 1:
            raise GoProtocolRegisterUnavailable("connection refused")
        return {"ok": True}

    started = []
    monkeypatch.setattr(
        "autotoken.integrations.go_protocol_register_client._json_request", fake_request
    )
    monkeypatch.setattr(
        "autotoken.integrations.go_protocol_register_client.subprocess.Popen",
        lambda args, **kwargs: started.append((args, kwargs)),
    )

    result = GoProtocolRegisterClient(timeout=1).health()

    assert result == {"ok": True}
    assert started == [
        ([str(binary)], {
            "cwd": str(tmp_path),
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "stdin": subprocess.DEVNULL,
        })
    ]
