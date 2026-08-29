import json
import subprocess
import threading
from pathlib import Path

import pytest

from autotoken.integrations import go_protocol_register_client as go_client
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


def test_register_transport_failure_is_indeterminate(monkeypatch):
    monkeypatch.setattr(
        go_client,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("reset")),
    )
    client = GoProtocolRegisterClient(base_url="http://127.0.0.1:1")

    with pytest.raises(go_client.GoProtocolRegisterIndeterminate):
        client.register({"email": "user@example.com"})


def test_client_auto_starts_configured_binary_and_retries_health(monkeypatch, tmp_path):
    binary = tmp_path / "protocol-registerd.exe"
    binary.write_bytes(b"fixture")
    monkeypatch.setenv("GO_PROTOCOL_REGISTER_AUTO_START", "1")
    monkeypatch.setenv("GO_PROTOCOL_REGISTER_BIN", str(binary))
    monkeypatch.setattr("autotoken.integrations.go_protocol_register_client._AUTO_START_TRIGGERED", False)
    calls = []

    def fake_request(url, payload=None, *, timeout, failure_type):
        calls.append(url)
        if len(calls) <= 2:
            raise failure_type("connection refused")
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


def test_client_auto_start_is_process_wide(monkeypatch, tmp_path):
    binary = tmp_path / "protocol-registerd.exe"
    binary.write_bytes(b"fixture")
    monkeypatch.setenv("GO_PROTOCOL_REGISTER_AUTO_START", "1")
    monkeypatch.setenv("GO_PROTOCOL_REGISTER_BIN", str(binary))
    monkeypatch.setattr("autotoken.integrations.go_protocol_register_client._AUTO_START_TRIGGERED", False)

    state = {"calls": 0}
    calls_lock = threading.Lock()
    started = []

    def fake_request(url, payload=None, *, timeout, failure_type):
        assert payload is None
        with calls_lock:
            state["calls"] += 1
            call_number = state["calls"]
        if call_number <= 3:
            raise failure_type("connection refused")
        return {"ok": True}

    monkeypatch.setattr(
        "autotoken.integrations.go_protocol_register_client._json_request", fake_request
    )
    monkeypatch.setattr(
        "autotoken.integrations.go_protocol_register_client.subprocess.Popen",
        lambda args, **kwargs: started.append((args, kwargs)),
    )

    results = []
    errors = []

    def run_health():
        try:
            results.append(GoProtocolRegisterClient(timeout=1).health())
        except Exception as exc:  # pragma: no cover - defensive
            errors.append(exc)

    threads = [threading.Thread(target=run_health) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert results == [{"ok": True}, {"ok": True}]
    assert len(started) == 1
