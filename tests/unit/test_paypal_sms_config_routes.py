import anyio
import pytest
from fastapi import HTTPException

from autotoken.api_routes.paypal_sms_config import create_paypal_sms_config_router, normalize_paypal_sms_provider


class FakeRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


def _routes():
    return {
        route.endpoint.__name__: route.endpoint
        for route in create_paypal_sms_config_router(mask_secret=lambda value: f"masked:{value}").routes
    }


def test_paypal_sms_config_response_masks_provider_secrets(monkeypatch):
    monkeypatch.setattr(
        "autotoken.settings.setup_wizard._read_env",
        lambda: {
            "PAYPAL_SMS_PROVIDER": "hero-sms",
            "PAYPAL_HERO_SMS_API_KEY": "hero-key",
            "PAYPAL_HERO_SMS_COUNTRY": "4",
            "PAYPAL_HERO_SMS_SERVICE": "ts",
            "PAYPAL_SMS_PHONE_COUNTRY_CODE": "81",
        },
    )

    result = _routes()["get_paypal_sms_config"]()

    assert result["provider"] == "hero_sms"
    assert result["configured"] is True
    assert result["phone_country_code"] == "81"
    assert result["hero_sms_api_key_present"] is True
    assert result["hero_sms_api_key_masked"] == "masked:hero-key"


def test_save_paypal_sms_config_requires_manual_sms_pair(monkeypatch):
    monkeypatch.delenv("PAYPAL_SMS_URL", raising=False)
    monkeypatch.delenv("PAYPAL_PHONE_NUMBER", raising=False)
    monkeypatch.setattr("autotoken.settings.setup_wizard._read_env", lambda: {})

    with pytest.raises(HTTPException) as exc_info:
        anyio.run(_routes()["save_paypal_sms_config"], FakeRequest({"provider": "manual"}))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "已有接码链接模式需要 PAYPAL_SMS_URL 与 PAYPAL_PHONE_NUMBER"


def test_save_paypal_sms_config_writes_normalized_provider_env(monkeypatch):
    written = {}
    monkeypatch.setattr("autotoken.settings.setup_wizard._read_env", lambda: {})
    monkeypatch.setattr("autotoken.settings.setup_wizard._write_env", lambda key, value: written.update({key: value}))

    result = anyio.run(
        _routes()["save_paypal_sms_config"],
        FakeRequest(
            {
                "provider": "sms_bower",
                "smsbower_api_key": "bower-key",
                "smsbower_country": "4",
                "smsbower_service": "ts",
                "smsbower_max_price": "0.045",
                "phone_country_code": "81",
            }
        ),
    )

    assert written["PAYPAL_SMS_PROVIDER"] == "smsbower"
    assert written["PAYPAL_SMSBOWER_API_KEY"] == "bower-key"
    assert written["PAYPAL_SMSBOWER_COUNTRY"] == "4"
    assert written["PAYPAL_SMSBOWER_SERVICE"] == "ts"
    assert written["PAYPAL_SMSBOWER_MAX_PRICE"] == "0.045"
    assert written["PAYPAL_SMS_PHONE_COUNTRY_CODE"] == "81"
    assert result["message"] == "PayPal 接码配置已保存"
    assert result["provider"] == "smsbower"
    assert result["configured"] is True


def test_paypal_sms_provider_normalizer_aliases():
    assert normalize_paypal_sms_provider("hero-sms") == "hero_sms"
    assert normalize_paypal_sms_provider("sms_code") == "smscode"
    assert normalize_paypal_sms_provider("sms cloud") == "smscloud"
    assert normalize_paypal_sms_provider("") == "manual"
