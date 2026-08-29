import pytest

from autotoken.auth import protocol_register
from autotoken.integrations.go_protocol_register_client import (
    GoProtocolRegisterUnavailable,
    go_response_to_protocol_result,
)


class MailAccount:
    email = "user@example.com"
    receive_code_url = "https://mail.test/code"


class FakeMailClient:
    provider_name = "generic-api"
    accounts = [MailAccount()]


class FakeGoClient:
    expected_impersonate = "chrome-test"

    def __init__(self, *args, **kwargs):
        pass

    def health(self):
        return {"ok": True}

    def register(self, payload):
        assert payload["email"] == "user@example.com"
        assert payload["password"] == "pw"
        assert payload["mail"]["provider"] == "generic-api"
        assert payload["mail"]["account_id"] == "mail-account-1"
        assert payload["mail"]["receive_code_url"] == "https://mail.test/code"
        assert payload["proxy_url"] == "http://proxy.test:8080"
        assert payload["options"]["timeout_seconds"] == 45
        assert payload["options"]["trace"] is True
        assert payload["options"]["impersonate"] == self.expected_impersonate
        return {
            "success": True,
            "status": "success",
            "email": "user@example.com",
            "session_data": {
                "email": "user@example.com",
                "accessToken": "access",
                "sessionToken": "session",
            },
            "events": [],
        }


def test_register_once_uses_go_engine_when_enabled(monkeypatch):
    monkeypatch.setenv("PROTOCOL_REGISTER_ENGINE", "go")
    monkeypatch.setenv("OTP_TIMEOUT", "45")
    monkeypatch.setenv("GO_PROTOCOL_TRACE", "1")
    monkeypatch.setenv("GO_PROTOCOL_IMPERSONATE", "chrome-test")
    monkeypatch.setattr(
        "autotoken.integrations.go_protocol_register_client.GoProtocolRegisterClient",
        FakeGoClient,
    )
    ok, payload = protocol_register.register_once(
        FakeMailClient(),
        email="user@example.com",
        password="pw",
        account_id="mail-account-1",
        proxy="http://proxy.test:8080",
    )
    assert ok is True
    assert payload["status"] == 200
    assert payload["data"]["accessToken"] == "access"
    assert payload["data"]["sessionToken"] == "session"


def test_register_once_go_defaults_to_chrome_143_plus_pool(monkeypatch):
    monkeypatch.setenv("PROTOCOL_REGISTER_ENGINE", "go")
    monkeypatch.setenv("OTP_TIMEOUT", "45")
    monkeypatch.setenv("GO_PROTOCOL_FALLBACK_PYTHON", "0")
    monkeypatch.setenv("GO_PROTOCOL_TRACE", "1")
    monkeypatch.delenv("GO_PROTOCOL_IMPERSONATE", raising=False)
    monkeypatch.setattr(
        "autotoken.integrations.go_protocol_register_client.GoProtocolRegisterClient",
        FakeGoClient,
    )
    monkeypatch.setattr(FakeGoClient, "expected_impersonate", "chrome143,chrome144,chrome145,chrome146,chrome147,chrome148,chrome149,chrome150,chrome151,chrome152")

    ok, payload = protocol_register.register_once(
        FakeMailClient(),
        email="user@example.com",
        password="pw",
        account_id="mail-account-1",
        proxy="http://proxy.test:8080",
    )

    assert ok is True
    assert payload["status"] == 200


def test_register_once_keeps_python_engine_as_default(monkeypatch):
    monkeypatch.delenv("PROTOCOL_REGISTER_ENGINE", raising=False)
    monkeypatch.setattr(protocol_register, "_load_protocol_classes", lambda: (_FakeAuthFlow, _FakeConfig))
    ok, payload = protocol_register.register_once(FakeMailClient(), email="user@example.com", password="pw")
    assert ok is True
    assert payload["data"]["accessToken"] == "python-access"


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


def test_register_once_go_without_fallback_raises(monkeypatch):
    monkeypatch.setenv("PROTOCOL_REGISTER_ENGINE", "go")
    monkeypatch.setenv("GO_PROTOCOL_FALLBACK_PYTHON", "0")
    monkeypatch.setattr(protocol_register, "_register_once_go", lambda *args, **kwargs: (_ for _ in ()).throw(
        GoProtocolRegisterUnavailable("service unavailable")
    ))
    with pytest.raises(GoProtocolRegisterUnavailable):
        protocol_register.register_once(FakeMailClient(), email="user@example.com", password="pw")


def test_register_once_go_fallback_uses_python_path(monkeypatch):
    calls = []
    monkeypatch.setenv("PROTOCOL_REGISTER_ENGINE", "go")
    monkeypatch.setenv("GO_PROTOCOL_FALLBACK_PYTHON", "1")
    monkeypatch.setattr(protocol_register, "_register_once_go", lambda *args, **kwargs: (_ for _ in ()).throw(
        GoProtocolRegisterUnavailable("service unavailable")
    ))
    monkeypatch.setattr(protocol_register, "_load_protocol_classes", lambda: (_FakeAuthFlow, _FakeConfig))
    monkeypatch.setattr(protocol_register, "_attach_flow_stage_logs", lambda flow: calls.append("python"))
    ok, payload = protocol_register.register_once(FakeMailClient(), email="user@example.com", password="pw")
    assert ok is True
    assert calls == ["python"]
    assert payload["data"]["accessToken"] == "python-access"


def test_register_once_go_skips_phone_sms_flows(monkeypatch):
    calls = []
    monkeypatch.setenv("PROTOCOL_REGISTER_ENGINE", "go")
    monkeypatch.setenv("GO_PROTOCOL_FALLBACK_PYTHON", "0")
    monkeypatch.setattr(protocol_register, "_register_once_go", lambda *args, **kwargs: calls.append("go") or (_ for _ in ()).throw(
        AssertionError("Go path must not run for phone/SMS protocol flows")
    ))
    monkeypatch.setattr(protocol_register, "_load_protocol_classes", lambda: (_FakeAuthFlow, _FakeConfig))
    monkeypatch.setattr(protocol_register, "_attach_flow_stage_logs", lambda flow: calls.append("python"))
    ok, payload = protocol_register.register_once(
        FakeMailClient(),
        email="user@example.com",
        password="pw",
        oauth_phone_sms_provider="phone_pool",
        oauth_phone_sms_country="US",
        oauth_oasis_sms_cdks="cdk-1",
    )
    assert ok is True
    assert calls == ["python"]
    assert payload["data"]["accessToken"] == "python-access"


class _FakeConfig:
    proxy = None


class _FakeAuthResult:
    def to_dict(self):
        return {"access_token": "python-access", "session_token": "python-session", "email": "user@example.com"}

    def is_valid(self):
        return True


class _FakeAuthFlow:
    def __init__(self, config):
        self.config = config

    def run_register(self, adapter):
        return _FakeAuthResult()
