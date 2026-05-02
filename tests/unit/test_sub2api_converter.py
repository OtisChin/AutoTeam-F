import base64
import json

import pytest

from autoteam.sub2api_converter import (
    ConversionError,
    ExportSettings,
    ProxyConfig,
    export_records,
    inspect_sources,
)


def fake_jwt(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")
    return f"header.{encoded}.signature"


def build_source(email="user@example.com", extra=None):
    payload = {
        "access_token": fake_jwt(
            {
                "client_id": "app_client",
                "https://api.openai.com/profile": {"email": email},
                "https://api.openai.com/auth": {
                    "chatgpt_account_id": "access-account",
                    "chatgpt_user_id": "access-user",
                    "chatgpt_plan_type": "free",
                },
            }
        ),
        "refresh_token": "refresh-token",
        "id_token": fake_jwt(
            {
                "email": email,
                "aud": ["app_from_id"],
                "https://api.openai.com/auth": {
                    "chatgpt_account_id": "id-account",
                    "organizations": [{"id": "org-default", "is_default": True}],
                    "chatgpt_subscription_active_until": "2026-05-01T22:09:36+08:00",
                },
            }
        ),
        "account_id": "source-account",
        "email": email,
        "expired": "2026-04-18T12:20:50+08:00",
        "type": "codex",
    }
    if extra:
        payload.update(extra)
    return payload


def test_cpa_auth_converts_to_sub2api_payload():
    records = inspect_sources([("sample.json", json.dumps(build_source(extra={"note": "个人"})))])

    payload = export_records(records, ExportSettings(output_filename="accounts.json"))
    account = payload["accounts"][0]
    credentials = account["credentials"]

    assert account["name"] == "user"
    assert account["platform"] == "openai"
    assert account["type"] == "oauth"
    assert account["notes"] == "个人"
    assert credentials["email"] == "user@example.com"
    assert credentials["refresh_token"] == "refresh-token"
    assert credentials["client_id"] == "app_client"
    assert credentials["chatgpt_account_id"] == "source-account"
    assert credentials["organization_id"] == "org-default"
    assert credentials["expires_at"] == "2026-04-18T12:20:50+08:00"


def test_invalid_sources_are_not_selected():
    records = inspect_sources([("bad.json", "{bad json")])

    assert records[0].is_valid is False
    assert records[0].selected is False
    assert records[0].status_text == "JSON 解析失败"
    with pytest.raises(ConversionError):
        export_records(records, ExportSettings(output_filename="accounts.json"))


def test_proxy_config_is_exported():
    records = inspect_sources([("sample.json", json.dumps(build_source()))])
    settings = ExportSettings(
        output_filename="accounts.json",
        proxy=ProxyConfig(enabled=True, host="127.0.0.1", port=7890),
    )

    payload = export_records(records, settings)

    assert payload["proxies"][0]["proxy_key"] == "http|127.0.0.1|7890||"
    assert payload["accounts"][0]["proxy_key"] == "http|127.0.0.1|7890||"
