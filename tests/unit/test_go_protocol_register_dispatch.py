import inspect
import uuid

import pytest

from autotoken.auth import go_protocol_register as go_bridge
from autotoken.auth import protocol_register
from autotoken.integrations.go_protocol_register_client import (
    GoProtocolRegisterServiceNotReady,
    go_response_to_protocol_result,
)


class MailAccount:
    email = "user@example.com"
    receive_code_url = "https://mail.test/code"


class FakeMailClient:
    provider_name = "generic-api"
    accounts = [MailAccount()]


class CapturingGoClient:
    def __init__(self, captured, **_kwargs):
        self.captured = captured

    def health(self):
        return {"ok": True, "protocol_ready": True}

    def register(self, payload):
        self.captured["payload"] = payload
        return {
            "success": True,
            "status": "success",
            "email": payload["email"],
            "session_data": {
                "email": payload["email"],
                "accessToken": "go-access",
                "sessionToken": "go-session",
            },
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
    monkeypatch.setattr(
        protocol_register,
        "_register_once_go",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Go bridge called")),
        raising=False,
    )
    monkeypatch.setattr(protocol_register, "_load_protocol_classes", lambda: (_FakeAuthFlow, _FakeConfig))

    ok, payload = protocol_register.register_once(
        FakeMailClient(),
        email="user@example.com",
        password="pw",
    )

    assert ok is True
    assert payload["data"]["accessToken"] == "python-access"


def test_go_bridge_builds_mail_payload_without_impersonate(monkeypatch):
    monkeypatch.setenv("OTP_TIMEOUT", "45")
    monkeypatch.setenv("GO_PROTOCOL_TRACE", "1")
    monkeypatch.setenv("GO_PROTOCOL_IMPERSONATE", "chrome999")
    captured = {}
    monkeypatch.setattr(
        go_bridge,
        "GoProtocolRegisterClient",
        lambda **kwargs: CapturingGoClient(captured, **kwargs),
    )

    ok, payload = go_bridge.register_once(
        FakeMailClient(),
        email="user@example.com",
        password="pw",
        account_id="mail-account-1",
        proxy="http://proxy.test:8080",
    )

    request = captured["payload"]
    uuid.UUID(request["request_id"])
    assert ok is True
    assert payload["data"]["accessToken"] == "go-access"
    assert request["email"] == "user@example.com"
    assert request["password"] == "pw"
    assert request["mail"]["provider"] == "generic-api"
    assert request["mail"]["account_id"] == "mail-account-1"
    assert request["mail"]["receive_code_url"] == "https://mail.test/code"
    assert request["proxy_url"] == "http://proxy.test:8080"
    assert request["options"] == {"timeout_seconds": 45, "trace": True}


def test_go_bridge_failure_never_loads_python_protocol(monkeypatch):
    monkeypatch.setattr(
        protocol_register,
        "_load_protocol_classes",
        lambda: (_ for _ in ()).throw(AssertionError("Python protocol loaded")),
    )
    monkeypatch.setattr(go_bridge, "GoProtocolRegisterClient", FailingGoClient)

    with pytest.raises(GoProtocolRegisterServiceNotReady):
        go_bridge.register_once(
            FakeMailClient(),
            email="user@example.com",
            password="pw",
        )


def test_go_bridge_source_has_no_python_protocol_dependency():
    source = inspect.getsource(go_bridge)

    for forbidden in (
        "autotoken.auth.protocol_register",
        "autotoken._protocol_register",
        "AuthFlow",
        "Config",
    ):
        assert forbidden not in source


@pytest.mark.parametrize(
    "status", ["email_code_timeout", "phone_blocked", "account_deactivated", "register_failed", "exception"]
)
def test_go_failure_status_is_preserved(status):
    ok, payload = go_response_to_protocol_result(
        {"success": False, "status": status, "error": {"code": status, "message": "failure"}}
    )

    assert ok is False
    assert payload["status"] == status


def test_go_unknown_failure_status_maps_to_register_failed():
    ok, payload = go_response_to_protocol_result(
        {"success": False, "status": "provider_secret_internal", "error": {"message": "failure"}}
    )

    assert ok is False
    assert payload["status"] == "register_failed"


class _FakeConfig:
    proxy = None


class _FakeAuthResult:
    def to_dict(self):
        return {
            "access_token": "python-access",
            "session_token": "python-session",
            "email": "user@example.com",
        }

    def is_valid(self):
        return True


class _FakeAuthFlow:
    def __init__(self, config):
        self.config = config

    def run_register(self, adapter):
        return _FakeAuthResult()
