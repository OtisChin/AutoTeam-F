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
            "session_data": {
                "email": "user@example.com",
                "accessToken": "access",
                "sessionToken": "session",
            },
            "events": [],
        }


def test_register_once_uses_go_engine_when_enabled(monkeypatch):
    monkeypatch.setenv("PROTOCOL_REGISTER_ENGINE", "go")
    monkeypatch.setattr(
        "autotoken.integrations.go_protocol_register_client.GoProtocolRegisterClient",
        FakeGoClient,
    )
    ok, payload = protocol_register.register_once(
        FakeMailClient(),
        email="user@example.com",
        password="pw",
        account_id="user@example.com",
    )
    assert ok is True
    assert payload["accessToken"] == "access"
    assert payload["sessionToken"] == "session"
