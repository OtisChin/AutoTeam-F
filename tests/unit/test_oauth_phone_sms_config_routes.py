import anyio
import pytest
from fastapi import HTTPException

from autotoken.api_routes.oauth_phone_sms_config import (
    create_oauth_phone_sms_config_router,
    normalize_oauth_hero_sms_country,
    normalize_oauth_smsbower_country,
)


class FakeRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


def _routes():
    return {
        route.endpoint.__name__: route.endpoint
        for route in create_oauth_phone_sms_config_router(mask_secret=lambda value: f"masked:{value}").routes
    }


def test_oauth_phone_sms_config_response_masks_provider_secrets(monkeypatch):
    monkeypatch.setattr(
        "autotoken.setup_wizard._read_env",
        lambda: {
            "OAUTH_PHONE_SMS_PROVIDER": "hero",
            "OAUTH_HERO_SMS_API_KEY": "hero-key",
            "OAUTH_HERO_SMS_MAX_PRICE": "0.045",
            "OAUTH_HERO_SMS_COUNTRY": "+1",
            "OAUTH_HERO_SMS_SERVICE": "openai",
        },
    )

    result = _routes()["get_oauth_phone_sms_config"]()

    assert result["provider"] == "hero_sms"
    assert result["configured"] is True
    assert result["hero_sms_api_key_present"] is True
    assert result["hero_sms_api_key_masked"] == "masked:hero-key"
    assert result["hero_sms_country"] == "187"
    assert result["hero_sms_service"] == "dr"


def test_oauth_phone_sms_countries_uses_fallback_without_api_key(monkeypatch):
    monkeypatch.delenv("OAUTH_SMSBOWER_API_KEY", raising=False)
    monkeypatch.setattr("autotoken.setup_wizard._read_env", lambda: {})

    result = _routes()["get_oauth_phone_sms_countries"](provider="smsbower")

    assert result["provider"] == "smsbower"
    assert result["fallback"] is True
    assert result["count"] == 4
    assert result["options"][0] == {"value": "all", "label": "全部国家 / 不限制"}
    assert result["error"] == "缺少 API Key，使用兜底国家列表"


def test_oauth_phone_sms_countries_prepends_all_to_dynamic_options(monkeypatch):
    monkeypatch.setattr(
        "autotoken.setup_wizard._read_env",
        lambda: {
            "OAUTH_PHONE_SMS_PROVIDER": "hero_sms",
            "OAUTH_HERO_SMS_API_KEY": "hero-key",
        },
    )
    monkeypatch.setattr(
        "autotoken.gopay_auto_register.query_dynamic_sms_countries",
        lambda **_kwargs: {"options": [{"value": "187", "label": "美国 / 187"}]},
    )

    result = _routes()["get_oauth_phone_sms_countries"]()

    assert result["provider"] == "hero_sms"
    assert result["fallback"] is False
    assert result["options"] == [
        {"value": "all", "label": "全部国家 / 不限制"},
        {"value": "187", "label": "美国 / 187"},
    ]


def test_save_oauth_phone_sms_config_requires_provider_secret(monkeypatch):
    monkeypatch.delenv("OAUTH_HERO_SMS_API_KEY", raising=False)
    monkeypatch.setattr("autotoken.setup_wizard._read_env", lambda: {})

    with pytest.raises(HTTPException) as exc_info:
        anyio.run(_routes()["save_oauth_phone_sms_config"], FakeRequest({"provider": "hero_sms"}))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "启用 hero-sms 前需要配置 OAuth hero-sms API Key"


def test_save_oauth_phone_sms_config_writes_normalized_env(monkeypatch):
    written = {}
    monkeypatch.setattr("autotoken.setup_wizard._read_env", lambda: {})
    monkeypatch.setattr("autotoken.setup_wizard._write_env", lambda key, value: written.update({key: value}))

    result = anyio.run(
        _routes()["save_oauth_phone_sms_config"],
        FakeRequest(
            {
                "provider": "sms_bower",
                "smsbower_api_key": "sms-key",
                "smsbower_max_price": "0.05",
                "smsbower_country": "+62",
                "hero_sms_max_price": "0.04",
            }
        ),
    )

    assert written == {
        "OAUTH_PHONE_SMS_PROVIDER": "smsbower",
        "OAUTH_HERO_SMS_MAX_PRICE": "0.04",
        "OAUTH_HERO_SMS_BASE_URL": "https://hero-sms.com/stubs/handler_api.php",
        "OAUTH_HERO_SMS_COUNTRY": "187",
        "OAUTH_HERO_SMS_SERVICE": "dr",
        "OAUTH_SMSBOWER_MAX_PRICE": "0.05",
        "OAUTH_SMSBOWER_BASE_URL": "https://smsbower.page/stubs/handler_api.php",
        "OAUTH_SMSBOWER_COUNTRY": "6",
        "OAUTH_SMSBOWER_SERVICE": "dr",
        "OAUTH_SMSBOWER_API_KEY": "sms-key",
    }
    assert result["message"] == "OAuth 手机号接码配置已保存"
    assert result["provider"] == "smsbower"
    assert result["configured"] is True


def test_oauth_sms_country_normalizers_keep_numeric_and_aliases():
    assert normalize_oauth_hero_sms_country("1") == "1"
    assert normalize_oauth_smsbower_country("1") == "1"
    assert normalize_oauth_hero_sms_country("+1") == "187"
    assert normalize_oauth_smsbower_country("+62") == "6"
