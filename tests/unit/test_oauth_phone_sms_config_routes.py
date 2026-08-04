import anyio
import pytest
from fastapi import HTTPException

from autotoken.api_routes.oauth_phone_sms_config import (
    create_oauth_phone_sms_config_router,
    normalize_oauth_hero_sms_country,
    normalize_oauth_phone_sms_provider,
    normalize_oauth_smsbower_country,
    normalize_oauth_smscloud_country,
)


class FakeRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


@pytest.fixture(autouse=True)
def clear_oauth_phone_sms_env(monkeypatch):
    for key in (
        "OAUTH_PHONE_SMS_PROVIDER",
        "OAUTH_HERO_SMS_API_KEY",
        "OAUTH_HERO_SMS_MAX_PRICE",
        "OAUTH_HERO_SMS_BASE_URL",
        "OAUTH_HERO_SMS_COUNTRY",
        "OAUTH_HERO_SMS_SERVICE",
        "OAUTH_SMSBOWER_API_KEY",
        "OAUTH_SMSBOWER_MAX_PRICE",
        "OAUTH_SMSBOWER_BASE_URL",
        "OAUTH_SMSBOWER_COUNTRY",
        "OAUTH_SMSBOWER_SERVICE",
        "OAUTH_SMSCLOUD_API_KEY",
        "OAUTH_SMSCLOUD_MIN_PRICE",
        "OAUTH_SMSCLOUD_MAX_PRICE",
        "OAUTH_SMSCLOUD_BASE_URL",
        "OAUTH_SMSCLOUD_COUNTRY",
        "OAUTH_SMSCLOUD_SERVICE",
        "OAUTH_OASIS_SMS_BASE_URL",
        "OAUTH_OASIS_SMS_CDKS",
        "OAUTH_OASIS_SMS_CDK_FILE",
        "OAUTH_OASIS_SMS_POLL_ATTEMPTS",
        "OAUTH_OASIS_SMS_POLL_INTERVAL_MS",
        "OAUTH_OASIS_SMS_ACCOUNT_MAP_FILE",
        "OAUTH_TUJIE_SMS_BASE_URL",
        "OAUTH_TUJIE_SMS_CDKS",
        "OAUTH_TUJIE_SMS_CDK_FILE",
        "OAUTH_TUJIE_SMS_POLL_ATTEMPTS",
        "OAUTH_TUJIE_SMS_POLL_INTERVAL_MS",
        "OAUTH_TUJIE_SMS_ACCOUNT_MAP_FILE",
    ):
        monkeypatch.delenv(key, raising=False)


def _routes():
    return {
        route.endpoint.__name__: route.endpoint
        for route in create_oauth_phone_sms_config_router(mask_secret=lambda value: f"masked:{value}").routes
    }


def test_oauth_phone_sms_config_response_masks_provider_secrets(monkeypatch):
    monkeypatch.setattr(
        "autotoken.settings.setup_wizard._read_env",
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
    monkeypatch.setattr(
        "autotoken.api_routes.oauth_phone_sms_config.oauth_phone_sms_env",
        lambda: {
            "provider": "smsbower",
            "smsbower_api_key": "",
            "smsbower_base_url": "https://smsbower.page/stubs/handler_api.php",
            "smsbower_service": "dr",
            "hero_sms_api_key": "",
            "hero_sms_base_url": "https://hero-sms.com/stubs/handler_api.php",
            "hero_sms_service": "dr",
        },
    )

    result = _routes()["get_oauth_phone_sms_countries"](provider="smsbower")

    assert result["provider"] == "smsbower"
    assert result["fallback"] is True
    assert result["count"] == 8
    assert result["options"][0] == {"value": "all", "label": "全部国家 / 不限制"}
    assert {"value": "31", "label": "南非 / 31"} in result["options"]
    assert result["error"] == "缺少 API Key，使用兜底国家列表"


def test_oauth_phone_sms_config_response_includes_smscloud(monkeypatch):
    monkeypatch.setattr(
        "autotoken.settings.setup_wizard._read_env",
        lambda: {
            "OAUTH_PHONE_SMS_PROVIDER": "smscloud",
            "OAUTH_SMSCLOUD_API_KEY": "cloud-key",
            "OAUTH_SMSCLOUD_COUNTRY": "44",
            "OAUTH_SMSCLOUD_SERVICE": "openai",
            "OAUTH_SMSCLOUD_MIN_PRICE": "0.05",
            "OAUTH_SMSCLOUD_MAX_PRICE": "0.08",
        },
    )

    result = _routes()["get_oauth_phone_sms_config"]()

    assert result["provider"] == "smscloud"
    assert result["configured"] is True
    assert result["smscloud_api_key_present"] is True
    assert result["smscloud_api_key_masked"] == "masked:cloud-key"
    assert result["smscloud_country"] == "44"
    assert result["smscloud_service"] == "dr"
    assert any(option["value"] == "smscloud" and option["configured"] for option in result["providers"])


def test_oauth_phone_sms_countries_returns_smscloud_options(monkeypatch):
    monkeypatch.setattr(
        "autotoken.api_routes.oauth_phone_sms_config.oauth_phone_sms_env",
        lambda: {
            "provider": "smscloud",
            "smscloud_api_key": "cloud-key",
            "smscloud_base_url": "https://smscloud.sbs/api/system",
            "smscloud_service": "dr",
        },
    )
    monkeypatch.setattr(
        "autotoken.auth.smscloud_sms.query_smscloud_countries",
        lambda **_kwargs: {"options": [{"value": "44", "label": "英国 / United Kingdom / +44 / 44"}]},
    )

    result = _routes()["get_oauth_phone_sms_countries"](provider="smscloud")

    assert result["provider"] == "smscloud"
    assert result["fallback"] is False
    assert result["options"] == [
        {"value": "all", "label": "全部国家 / 不限制"},
        {"value": "44", "label": "英国 / United Kingdom / +44 / 44"},
    ]


def test_save_oauth_phone_sms_config_writes_smscloud_env(monkeypatch):
    written = {}
    monkeypatch.setattr("autotoken.settings.setup_wizard._read_env", lambda: {})
    monkeypatch.setattr("autotoken.settings.setup_wizard._write_env", lambda key, value: written.update({key: value}))

    result = anyio.run(
        _routes()["save_oauth_phone_sms_config"],
        FakeRequest(
            {
                "provider": "sms_cloud",
                "smscloud_api_key": "cloud-key",
                "smscloud_min_price": "0.05",
                "smscloud_max_price": "0.08",
                "smscloud_country": "uk",
            }
        ),
    )

    assert written["OAUTH_PHONE_SMS_PROVIDER"] == "smscloud"
    assert written["OAUTH_SMSCLOUD_API_KEY"] == "cloud-key"
    assert written["OAUTH_SMSCLOUD_MIN_PRICE"] == "0.05"
    assert written["OAUTH_SMSCLOUD_MAX_PRICE"] == "0.08"
    assert written["OAUTH_SMSCLOUD_BASE_URL"] == "https://smscloud.sbs/api/system"
    assert written["OAUTH_SMSCLOUD_COUNTRY"] == "44"
    assert written["OAUTH_SMSCLOUD_SERVICE"] == "dr"
    assert result["provider"] == "smscloud"
    assert result["configured"] is True


def test_oauth_phone_sms_config_response_includes_oasis_status(monkeypatch):
    monkeypatch.setattr(
        "autotoken.settings.setup_wizard._read_env",
        lambda: {
            "OAUTH_PHONE_SMS_PROVIDER": "oasis",
            "OAUTH_OASIS_SMS_CDKS": "SMS-6L2A-6TAH-Q7BA SMS-8EQ6-8E5G-KN2C",
            "OAUTH_OASIS_SMS_BASE_URL": "https://sms.oapi.vip",
            "OAUTH_OASIS_SMS_ACCOUNT_MAP_FILE": "data/oasis-map.jsonl",
        },
    )

    result = _routes()["get_oauth_phone_sms_config"]()

    assert result["provider"] == "oasis"
    assert result["configured"] is True
    assert result["oasis_sms_cdk_count"] == 2
    assert result["oasis_sms_account_map_file"] == "data/oasis-map.jsonl"
    assert any(option["value"] == "oasis" and option["configured"] for option in result["providers"])


def test_oauth_phone_sms_config_response_includes_tujie_status(monkeypatch):
    monkeypatch.setattr(
        "autotoken.settings.setup_wizard._read_env",
        lambda: {
            "OAUTH_PHONE_SMS_PROVIDER": "tujie",
            "OAUTH_TUJIE_SMS_CDKS": "SMS-AE4H6TLEZV5H69SJGQ SMS-3VBXJBRT5UWHB2RW7E",
            "OAUTH_TUJIE_SMS_BASE_URL": "https://tujie.example",
            "OAUTH_TUJIE_SMS_ACCOUNT_MAP_FILE": "data/tujie-map.jsonl",
        },
    )

    result = _routes()["get_oauth_phone_sms_config"]()

    assert result["provider"] == "tujie"
    assert result["configured"] is True
    assert result["tujie_sms_cdk_count"] == 2
    assert result["tujie_sms_base_url"] == "https://tujie.example"
    assert result["tujie_sms_account_map_file"] == "data/tujie-map.jsonl"
    assert any(option["value"] == "tujie" and option["configured"] for option in result["providers"])


def test_oauth_phone_sms_countries_returns_empty_for_oasis(monkeypatch):
    monkeypatch.setattr("autotoken.settings.setup_wizard._read_env", lambda: {"OAUTH_PHONE_SMS_PROVIDER": "oasis"})

    result = _routes()["get_oauth_phone_sms_countries"](provider="oasis")

    assert result == {"provider": "oasis", "options": [], "count": 0, "error": ""}


def test_oauth_phone_sms_countries_returns_empty_for_tujie(monkeypatch):
    monkeypatch.setattr("autotoken.settings.setup_wizard._read_env", lambda: {"OAUTH_PHONE_SMS_PROVIDER": "tujie"})

    result = _routes()["get_oauth_phone_sms_countries"](provider="tujie")

    assert result == {"provider": "tujie", "options": [], "count": 0, "error": ""}


def test_oauth_phone_sms_countries_prepends_all_to_dynamic_options(monkeypatch):
    monkeypatch.setattr(
        "autotoken.settings.setup_wizard._read_env",
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
    monkeypatch.setattr("autotoken.settings.setup_wizard._read_env", lambda: {})

    with pytest.raises(HTTPException) as exc_info:
        anyio.run(_routes()["save_oauth_phone_sms_config"], FakeRequest({"provider": "hero_sms"}))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "启用 hero-sms 前需要配置 OAuth hero-sms API Key"


def test_save_oauth_phone_sms_config_requires_oasis_cdk_pool(monkeypatch):
    monkeypatch.setattr("autotoken.settings.setup_wizard._read_env", lambda: {})

    with pytest.raises(HTTPException) as exc_info:
        anyio.run(_routes()["save_oauth_phone_sms_config"], FakeRequest({"provider": "oasis"}))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "启用 Oasis 前需要配置 CDK 池或 CDK 文件"


def test_save_oauth_phone_sms_config_writes_tujie_env(monkeypatch):
    written = {}
    monkeypatch.setattr("autotoken.settings.setup_wizard._read_env", lambda: {})
    monkeypatch.setattr("autotoken.settings.setup_wizard._write_env", lambda key, value: written.update({key: value}))

    result = anyio.run(
        _routes()["save_oauth_phone_sms_config"],
        FakeRequest(
            {
                "provider": "tujie",
                "tujie_sms_base_url": "https://tujie.example",
                "tujie_sms_cdks": "SMS-AE4H6TLEZV5H69SJGQ\nSMS-3VBXJBRT5UWHB2RW7E",
                "tujie_sms_account_map_file": "data/tujie-map.jsonl",
            }
        ),
    )

    assert written["OAUTH_PHONE_SMS_PROVIDER"] == "tujie"
    assert written["OAUTH_TUJIE_SMS_BASE_URL"] == "https://tujie.example"
    assert written["OAUTH_TUJIE_SMS_CDKS"] == "SMS-AE4H6TLEZV5H69SJGQ,SMS-3VBXJBRT5UWHB2RW7E"
    assert written["OAUTH_TUJIE_SMS_ACCOUNT_MAP_FILE"] == "data/tujie-map.jsonl"
    assert result["provider"] == "tujie"
    assert result["configured"] is True


def test_save_oauth_phone_sms_config_requires_tujie_cdk_pool(monkeypatch):
    monkeypatch.setattr("autotoken.settings.setup_wizard._read_env", lambda: {})

    with pytest.raises(HTTPException) as exc_info:
        anyio.run(_routes()["save_oauth_phone_sms_config"], FakeRequest({"provider": "tujie"}))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "启用 TuJie 前需要配置 CDK 池或 CDK 文件"


def test_save_oauth_phone_sms_config_writes_normalized_env(monkeypatch):
    written = {}
    monkeypatch.setattr("autotoken.settings.setup_wizard._read_env", lambda: {})
    monkeypatch.setattr("autotoken.settings.setup_wizard._write_env", lambda key, value: written.update({key: value}))

    result = anyio.run(
        _routes()["save_oauth_phone_sms_config"],
        FakeRequest(
            {
                "provider": "sms_bower",
                "smsbower_api_key": "sms-key",
                "smsbower_min_price": "0.1",
                "smsbower_max_price": "0.05",
                "smsbower_price_mode": "lowest",
                "smsbower_country": "+62",
                "hero_sms_min_price": "0.02",
                "hero_sms_max_price": "0.04",
                "hero_sms_price_mode": "ceiling",
            }
        ),
    )

    assert written == {
        "OAUTH_PHONE_SMS_PROVIDER": "smsbower",
        "OAUTH_HERO_SMS_MIN_PRICE": "0.02",
        "OAUTH_HERO_SMS_MAX_PRICE": "0.04",
        "OAUTH_HERO_SMS_PRICE_MODE": "ceiling",
        "OAUTH_HERO_SMS_BASE_URL": "https://hero-sms.com/stubs/handler_api.php",
        "OAUTH_HERO_SMS_COUNTRY": "187",
        "OAUTH_HERO_SMS_SERVICE": "dr",
        "OAUTH_SMSBOWER_MIN_PRICE": "0.1",
        "OAUTH_SMSBOWER_MAX_PRICE": "0.05",
        "OAUTH_SMSBOWER_PRICE_MODE": "lowest",
        "OAUTH_SMSBOWER_BASE_URL": "https://smsbower.page/stubs/handler_api.php",
        "OAUTH_SMSBOWER_COUNTRY": "6",
        "OAUTH_SMSBOWER_SERVICE": "dr",
        "OAUTH_SMSCLOUD_MIN_PRICE": "",
        "OAUTH_SMSCLOUD_MAX_PRICE": "",
        "OAUTH_SMSCLOUD_PRICE_MODE": "ceiling",
        "OAUTH_SMSCLOUD_BASE_URL": "https://smscloud.sbs/api/system",
        "OAUTH_SMSCLOUD_COUNTRY": "187",
        "OAUTH_SMSCLOUD_SERVICE": "dr",
        "OAUTH_OASIS_SMS_BASE_URL": "https://sms.oapi.vip",
        "OAUTH_OASIS_SMS_CDKS": "",
        "OAUTH_OASIS_SMS_CDK_FILE": "",
        "OAUTH_OASIS_SMS_POLL_ATTEMPTS": "24",
        "OAUTH_OASIS_SMS_POLL_INTERVAL_MS": "5000",
        "OAUTH_OASIS_SMS_ACCOUNT_MAP_FILE": "oasis-cdk-accounts.jsonl",
        "OAUTH_TUJIE_SMS_BASE_URL": "https://tujie.xyz/api",
        "OAUTH_TUJIE_SMS_CDKS": "",
        "OAUTH_TUJIE_SMS_CDK_FILE": "",
        "OAUTH_TUJIE_SMS_POLL_ATTEMPTS": "24",
        "OAUTH_TUJIE_SMS_POLL_INTERVAL_MS": "5000",
        "OAUTH_TUJIE_SMS_ACCOUNT_MAP_FILE": "tujie-cdk-accounts.jsonl",
        "OAUTH_SMSBOWER_API_KEY": "sms-key",
    }
    assert result["message"] == "OAuth 手机号接码配置已保存"
    assert result["provider"] == "smsbower"
    assert result["configured"] is True


def test_save_oauth_phone_sms_config_writes_oasis_env(monkeypatch):
    written = {}
    monkeypatch.setattr("autotoken.settings.setup_wizard._read_env", lambda: {})
    monkeypatch.setattr("autotoken.settings.setup_wizard._write_env", lambda key, value: written.update({key: value}))

    result = anyio.run(
        _routes()["save_oauth_phone_sms_config"],
        FakeRequest(
            {
                "provider": "oapi",
                "oasis_sms_base_url": "https://sms.oapi.vip/",
                "oasis_sms_cdks": "SMS-6L2A-6TAH-Q7BA\nSMS-8EQ6-8E5G-KN2C",
                "oasis_sms_cdk_file": "data/oasis.txt",
                "oasis_sms_poll_attempts": "30",
                "oasis_sms_poll_interval_ms": "4000",
                "oasis_sms_account_map_file": "data/oasis-map.jsonl",
            }
        ),
    )

    assert written["OAUTH_PHONE_SMS_PROVIDER"] == "oasis"
    assert written["OAUTH_OASIS_SMS_BASE_URL"] == "https://sms.oapi.vip/"
    assert written["OAUTH_OASIS_SMS_CDKS"] == "SMS-6L2A-6TAH-Q7BA,SMS-8EQ6-8E5G-KN2C"
    assert written["OAUTH_OASIS_SMS_CDK_FILE"] == "data/oasis.txt"
    assert written["OAUTH_OASIS_SMS_POLL_ATTEMPTS"] == "30"
    assert written["OAUTH_OASIS_SMS_POLL_INTERVAL_MS"] == "4000"
    assert written["OAUTH_OASIS_SMS_ACCOUNT_MAP_FILE"] == "data/oasis-map.jsonl"
    assert result["provider"] == "oasis"
    assert result["configured"] is True


def test_oauth_sms_country_normalizers_keep_numeric_and_aliases():
    assert normalize_oauth_hero_sms_country("1") == "1"
    assert normalize_oauth_smsbower_country("1") == "1"
    assert normalize_oauth_hero_sms_country("+1") == "187"
    assert normalize_oauth_smsbower_country("+62") == "6"
    assert normalize_oauth_smscloud_country("巴西") == "73"
    assert normalize_oauth_smscloud_country("+55") == "73"
    assert normalize_oauth_phone_sms_provider("oapi") == "oasis"
    assert normalize_oauth_phone_sms_provider("tujie_cdk") == "tujie"
    assert normalize_oauth_phone_sms_provider("sms_cloud") == "smscloud"
