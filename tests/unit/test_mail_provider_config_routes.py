import anyio
import pytest
from fastapi import HTTPException

from autotoken.api_routes.mail_provider_config import create_mail_provider_config_router


class FakeRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


def _routes():
    return {route.endpoint.__name__: route.endpoint for route in create_mail_provider_config_router().routes}


def test_get_mail_provider_config_includes_provider_fields_with_values(monkeypatch):
    monkeypatch.delenv("CLOUD_MAIL_DOMAIN", raising=False)
    monkeypatch.setattr(
        "autotoken.setup_wizard._read_env",
        lambda: {
            "MAIL_PROVIDER": "cloud-mail",
            "CLOUD_MAIL_API_URL": "https://mail.example.com",
        },
    )
    monkeypatch.setattr(
        "autotoken.setup_wizard.get_setup_schema",
        lambda _env: {
            "provider_options": [{"value": "cloud-mail", "label": "Cloud Mail"}],
            "provider_fields": {
                "cloud-mail": [
                    {"key": "CLOUD_MAIL_API_URL", "prompt": "API URL", "default": "", "optional": False},
                    {"key": "CLOUD_MAIL_DOMAIN", "prompt": "Domain", "default": "@example.com", "optional": False},
                ]
            },
        },
    )

    result = _routes()["get_mail_provider_config"]()

    assert result["provider"] == "cloud-mail"
    assert result["provider_options"] == [{"value": "cloud-mail", "label": "Cloud Mail"}]
    fields = result["provider_fields"]["cloud-mail"]
    assert fields[0]["value"] == "https://mail.example.com"
    assert fields[0]["configured"] is True
    assert fields[1]["value"] == "@example.com"
    assert fields[1]["configured"] is False


def test_save_mail_provider_config_writes_only_selected_provider_fields(monkeypatch):
    written = {}
    reloads = []
    monkeypatch.setattr("autotoken.setup_wizard._write_env", lambda key, value: written.update({key: value}))
    monkeypatch.setattr("autotoken.setup_wizard._verify_temporary_email", lambda: True)
    monkeypatch.setattr("importlib.reload", lambda module: reloads.append(module.__name__) or module)

    result = anyio.run(
        _routes()["save_mail_provider_config"],
        FakeRequest(
            {
                "MAIL_PROVIDER": "outlook",
                "OUTLOOK_ACCOUNTS_FILE": "data/outlook.txt",
                "OUTLOOK_DEFAULT_CLIENT_ID": "client-1",
                "CLOUD_MAIL_API_URL": "ignored",
            }
        ),
    )

    assert written == {
        "MAIL_PROVIDER": "outlook",
        "OUTLOOK_ACCOUNTS_FILE": "data/outlook.txt",
        "OUTLOOK_DEFAULT_CLIENT_ID": "client-1",
    }
    assert reloads == ["autotoken.settings.config"]
    assert result == {"message": "邮件 Provider 配置已保存", "provider": "outlook"}


def test_save_mail_provider_config_returns_validation_error(monkeypatch):
    monkeypatch.setattr("autotoken.setup_wizard._write_env", lambda _key, _value: None)
    monkeypatch.setattr("autotoken.setup_wizard._verify_temporary_email", lambda: False)
    monkeypatch.setattr("importlib.reload", lambda module: module)

    with pytest.raises(HTTPException) as exc_info:
        anyio.run(
            _routes()["save_mail_provider_config"],
            FakeRequest({"MAIL_PROVIDER": "cloudflare_temp_email"}),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "邮件 Provider 验证失败，请检查配置"
