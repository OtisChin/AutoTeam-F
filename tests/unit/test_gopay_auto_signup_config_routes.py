import anyio
import pytest
from fastapi import HTTPException

from autotoken.api_routes.gopay_auto_signup_config import (
    GoPayHeroSmsPriceQueryParams,
    GoPaySmsCodePriceQueryParams,
    create_gopay_auto_signup_config_router,
    normalize_gopay_auto_signup_mode,
    normalize_gopay_auto_signup_sms_provider,
)


class FakeRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


def _routes():
    return {
        route.endpoint.__name__: route.endpoint
        for route in create_gopay_auto_signup_config_router(mask_secret=lambda value: f"masked:{value}").routes
    }


def test_gopay_auto_signup_config_response_masks_provider_secrets(monkeypatch):
    monkeypatch.setattr(
        "autotoken.setup_wizard._read_env",
        lambda: {
            "GOPAY_AUTO_SIGNUP_SMS_PROVIDER": "hero-sms",
            "GOPAY_AUTO_SIGNUP_HERO_SMS_API_KEY": "hero-key",
            "GOPAY_AUTO_SIGNUP_HERO_SMS_MIN_PRICE": "0.02",
            "GOPAY_AUTO_SIGNUP_COUNTRY_CODE": "+62",
            "GOPAY_AUTO_SIGNUP_MODE": "appium",
            "GOPAY_APPIUM_URL": "http://127.0.0.1:4723",
            "GOPAY_APPIUM_ADB_SERIAL": "emulator-5554",
        },
    )

    result = _routes()["get_gopay_auto_signup_config"]()

    assert result["provider"] == "hero_sms"
    assert result["configured"] is True
    assert result["country_code"] == "+62"
    assert result["hero_sms_api_key_present"] is True
    assert result["hero_sms_api_key_masked"] == "masked:hero-key"
    assert result["hero_sms_min_price"] == "0.02"
    assert result["signup_mode"] == "appium"
    assert result["appium_adb_serial"] == "emulator-5554"


def test_query_gopay_hero_sms_prices_requires_api_key(monkeypatch):
    monkeypatch.delenv("GOPAY_AUTO_SIGNUP_HERO_SMS_API_KEY", raising=False)
    monkeypatch.setattr("autotoken.setup_wizard._read_env", lambda: {})

    with pytest.raises(HTTPException) as exc_info:
        _routes()["query_gopay_hero_sms_prices"](GoPayHeroSmsPriceQueryParams())

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "缺少 hero-sms API Key"


def test_query_gopay_hero_sms_prices_delegates_and_strips_raw(monkeypatch):
    captured = {}
    monkeypatch.setattr("autotoken.setup_wizard._read_env", lambda: {})

    def fake_query_hero_sms_price_tiers(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "tiers": [{"price": "0.04"}], "raw": "provider-secret"}

    monkeypatch.setattr(
        "autotoken.gopay_auto_register.query_hero_sms_price_tiers",
        fake_query_hero_sms_price_tiers,
    )

    result = _routes()["query_gopay_hero_sms_prices"](
        GoPayHeroSmsPriceQueryParams(
            hero_sms_api_key="hero-key",
            hero_sms_base_url="https://hero.example/stubs/handler_api.php",
            hero_sms_country="6.0",
            hero_sms_service="ni",
            hero_sms_min_price="0.02",
            hero_sms_max_price="0.08",
            hero_sms_preferred_price="0.04",
        )
    )

    assert result == {"ok": True, "tiers": [{"price": "0.04"}]}
    assert captured == {
        "service_code": "ni",
        "country_id": 6,
        "base_url": "https://hero.example/stubs/handler_api.php",
        "api_key": "hero-key",
        "min_price": "0.02",
        "max_price": "0.08",
        "preferred_price": "0.04",
    }


def test_query_gopay_smscode_prices_delegates(monkeypatch):
    captured = {}
    monkeypatch.setattr("autotoken.setup_wizard._read_env", lambda: {})

    def fake_query_smscode_products(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "products": [{"id": "product-1"}]}

    monkeypatch.setattr("autotoken.gopay_auto_register.query_smscode_products", fake_query_smscode_products)

    result = _routes()["query_gopay_smscode_prices"](
        GoPaySmsCodePriceQueryParams(
            smscode_api_token="sms-token",
            smscode_base_url="https://smscode.example/v1",
            smscode_country_id="7",
            smscode_platform_id="platform-1",
            smscode_platform_query="gojek",
            smscode_min_price="0.01",
            smscode_max_price="0.05",
        )
    )

    assert result == {"ok": True, "products": [{"id": "product-1"}]}
    assert captured == {
        "base_url": "https://smscode.example/v1",
        "api_token": "sms-token",
        "country_id": "7",
        "platform_id": "platform-1",
        "platform_query": "gojek",
        "min_price": "0.01",
        "max_price": "0.05",
    }


def test_save_gopay_auto_signup_config_writes_normalized_env(monkeypatch):
    written = {}
    monkeypatch.setattr("autotoken.setup_wizard._read_env", lambda: {})
    monkeypatch.setattr("autotoken.setup_wizard._write_env", lambda key, value: written.update({key: value}))

    result = anyio.run(
        _routes()["save_gopay_auto_signup_config"],
        FakeRequest(
            {
                "provider": "sms_code",
                "country_code": "+62",
                "smscode_api_token": "sms-token",
                "smscode_platform_id": "platform-1",
                "hero_sms_api_key": "hero-key",
                "smsbower_api_key": "bower-key",
                "proxy_url": "http://proxy.example:8080",
                "signup_mode": "appium",
                "appium_url": "http://127.0.0.1:4723",
                "appium_adb_serial": "emulator-5554",
            }
        ),
    )

    assert written["GOPAY_AUTO_SIGNUP_SMS_PROVIDER"] == "smscode"
    assert written["GOPAY_AUTO_SIGNUP_COUNTRY_CODE"] == "+62"
    assert written["GOPAY_AUTO_SIGNUP_PROXY_URL"] == "http://proxy.example:8080"
    assert written["GOPAY_AUTO_SIGNUP_MODE"] == "appium"
    assert written["GOPAY_AUTO_SIGNUP_HERO_SMS_API_KEY"] == "hero-key"
    assert written["GOPAY_AUTO_SIGNUP_SMSBOWER_API_KEY"] == "bower-key"
    assert written["GOPAY_AUTO_SIGNUP_SMSCODE_API_TOKEN"] == "sms-token"
    assert written["GOPAY_AUTO_SIGNUP_SMSCODE_PLATFORM_ID"] == "platform-1"
    assert written["GOPAY_APPIUM_URL"] == "http://127.0.0.1:4723"
    assert written["GOPAY_APPIUM_ADB_SERIAL"] == "emulator-5554"
    assert result["message"] == "GoPay 自动注册配置已保存"
    assert result["provider"] == "smscode"
    assert result["configured"] is True


def test_gopay_auto_signup_normalizers():
    assert normalize_gopay_auto_signup_sms_provider("hero-sms") == "hero_sms"
    assert normalize_gopay_auto_signup_sms_provider("sms_code") == "smscode"
    assert normalize_gopay_auto_signup_sms_provider("unknown") == "smscloud"
    assert normalize_gopay_auto_signup_mode("appium") == "appium"
    assert normalize_gopay_auto_signup_mode("browser") == "http"
