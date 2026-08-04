"""OAuth phone-SMS provider configuration routes."""

import os
import re
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from autotoken.auth.oasis_sms import (
    OASIS_DEFAULT_ACCOUNT_MAP_FILE,
    OASIS_DEFAULT_BASE_URL,
    normalize_oasis_cdks,
    oasis_cdk_count,
    oasis_configured,
)
from autotoken.auth.tujie_sms import (
    TUJIE_DEFAULT_ACCOUNT_MAP_FILE,
    TUJIE_DEFAULT_BASE_URL,
    normalize_tujie_cdks,
    tujie_cdk_count,
    tujie_configured,
)


def normalize_oauth_phone_sms_provider(raw: str | None = None) -> str:
    value = str(raw or "").strip().lower().replace("-", "_")
    if value in {"hero_sms", "herosms", "hero"}:
        return "hero_sms"
    if value in {"smsbower", "sms_bower"}:
        return "smsbower"
    if value in {"smscloud", "sms_cloud", "sms_cloud_sbs"}:
        return "smscloud"
    if value in {"oasis", "oasis_sms", "oasissms", "oapi"}:
        return "oasis"
    if value in {"tujie", "tujie_sms", "tujie_cdk", "tujiecdk", "tj"}:
        return "tujie"
    return "phone_pool"


def normalize_oauth_hero_sms_service(raw: str | None = None) -> str:
    value = str(raw or "").strip().lower().replace("-", "_")
    if value in {"", "openai", "chatgpt", "chat_gpt", "gpt"}:
        return "dr"
    return value


def normalize_oauth_sms_price_mode(raw: str | None = None) -> str:
    value = str(raw or "").strip().lower().replace("-", "_")
    if value in {"lowest", "min", "minimum", "lowest_price", "min_price", "cheap", "cheapest", "低价", "最低价"}:
        return "lowest"
    return "ceiling"


def normalize_oauth_hero_sms_country(raw: str | None = None) -> str:
    value = str(raw or "").strip().lower()
    if value in {"all", "any", "*", "全部", "所有", "不限", "global"}:
        return "all"
    if value and re.fullmatch(r"\d+", value):
        return value
    if value in {"", "us", "usa", "united_states", "united states", "+1"}:
        return "187"
    if value in {"id", "idn", "indonesia", "indonesian", "印度尼西亚", "印尼", "+62"}:
        return "6"
    if value in {"co", "colombia", "colombian", "哥伦比亚", "哥伦比亚共和国", "+57"}:
        return "33"
    return value


def normalize_oauth_smsbower_country(raw: str | None = None) -> str:
    value = str(raw or "").strip().lower()
    if value in {"all", "any", "*", "全部", "所有", "不限", "global"}:
        return "all"
    if value and re.fullmatch(r"\d+", value):
        return value
    if value in {"", "us", "usa", "united_states", "united states", "+1"}:
        return "187"
    if value in {"id", "idn", "indonesia", "indonesian", "印度尼西亚", "印尼", "+62"}:
        return "6"
    if value in {"co", "colombia", "colombian", "哥伦比亚", "哥伦比亚共和国", "+57"}:
        return "33"
    return value


def normalize_oauth_smscloud_country(raw: str | None = None) -> str:
    value = str(raw or "").strip().lower()
    if value in {"all", "any", "*", "全部", "所有", "不限", "global"}:
        return "all"
    if value and re.fullmatch(r"\d+", value):
        return value
    if value in {"", "us", "usa", "united_states", "united states", "+1"}:
        return "187"
    if value in {"gb", "uk", "united_kingdom", "united kingdom", "britain", "英国", "+44"}:
        return "44"
    if value in {"br", "bra", "brazil", "brasil", "巴西", "+55"}:
        return "73"
    if value in {"id", "idn", "indonesia", "indonesian", "印度尼西亚", "印尼", "+62"}:
        return "6"
    if value in {"co", "colombia", "colombian", "哥伦比亚", "哥伦比亚共和国", "+57"}:
        return "33"
    return value


def oauth_phone_sms_env() -> dict[str, str]:
    from autotoken.settings.setup_wizard import _read_env

    env = _read_env()

    def pick(key: str, default: str = "") -> str:
        return str(env.get(key, "") or os.environ.get(key, "") or default).strip()

    return {
        "provider": normalize_oauth_phone_sms_provider(pick("OAUTH_PHONE_SMS_PROVIDER", "phone_pool")),
        "hero_sms_api_key": pick("OAUTH_HERO_SMS_API_KEY"),
        "hero_sms_min_price": pick("OAUTH_HERO_SMS_MIN_PRICE"),
        "hero_sms_max_price": pick("OAUTH_HERO_SMS_MAX_PRICE"),
        "hero_sms_price_mode": normalize_oauth_sms_price_mode(pick("OAUTH_HERO_SMS_PRICE_MODE", "ceiling")),
        "hero_sms_base_url": pick("OAUTH_HERO_SMS_BASE_URL", "https://hero-sms.com/stubs/handler_api.php"),
        "hero_sms_country": normalize_oauth_hero_sms_country(pick("OAUTH_HERO_SMS_COUNTRY", "187")),
        "hero_sms_service": normalize_oauth_hero_sms_service(pick("OAUTH_HERO_SMS_SERVICE", "dr")),
        "smsbower_api_key": pick("OAUTH_SMSBOWER_API_KEY"),
        "smsbower_min_price": pick("OAUTH_SMSBOWER_MIN_PRICE"),
        "smsbower_max_price": pick("OAUTH_SMSBOWER_MAX_PRICE"),
        "smsbower_price_mode": normalize_oauth_sms_price_mode(pick("OAUTH_SMSBOWER_PRICE_MODE", "ceiling")),
        "smsbower_base_url": pick("OAUTH_SMSBOWER_BASE_URL", "https://smsbower.page/stubs/handler_api.php"),
        "smsbower_country": normalize_oauth_smsbower_country(pick("OAUTH_SMSBOWER_COUNTRY", "187")),
        "smsbower_service": normalize_oauth_hero_sms_service(pick("OAUTH_SMSBOWER_SERVICE", "dr")),
        "smscloud_api_key": pick("OAUTH_SMSCLOUD_API_KEY"),
        "smscloud_min_price": pick("OAUTH_SMSCLOUD_MIN_PRICE"),
        "smscloud_max_price": pick("OAUTH_SMSCLOUD_MAX_PRICE"),
        "smscloud_price_mode": normalize_oauth_sms_price_mode(pick("OAUTH_SMSCLOUD_PRICE_MODE", "ceiling")),
        "smscloud_base_url": pick("OAUTH_SMSCLOUD_BASE_URL", "https://smscloud.sbs/api/system"),
        "smscloud_country": normalize_oauth_smscloud_country(pick("OAUTH_SMSCLOUD_COUNTRY", "187")),
        "smscloud_service": normalize_oauth_hero_sms_service(pick("OAUTH_SMSCLOUD_SERVICE", "dr")),
        "oasis_sms_base_url": pick("OAUTH_OASIS_SMS_BASE_URL", OASIS_DEFAULT_BASE_URL),
        "oasis_sms_cdks": pick("OAUTH_OASIS_SMS_CDKS"),
        "oasis_sms_cdk_file": pick("OAUTH_OASIS_SMS_CDK_FILE"),
        "oasis_sms_poll_attempts": pick("OAUTH_OASIS_SMS_POLL_ATTEMPTS", "24"),
        "oasis_sms_poll_interval_ms": pick("OAUTH_OASIS_SMS_POLL_INTERVAL_MS", "5000"),
        "oasis_sms_account_map_file": pick(
            "OAUTH_OASIS_SMS_ACCOUNT_MAP_FILE",
            OASIS_DEFAULT_ACCOUNT_MAP_FILE,
        ),
        "tujie_sms_base_url": pick("OAUTH_TUJIE_SMS_BASE_URL", TUJIE_DEFAULT_BASE_URL),
        "tujie_sms_cdks": pick("OAUTH_TUJIE_SMS_CDKS"),
        "tujie_sms_cdk_file": pick("OAUTH_TUJIE_SMS_CDK_FILE"),
        "tujie_sms_poll_attempts": pick("OAUTH_TUJIE_SMS_POLL_ATTEMPTS", "24"),
        "tujie_sms_poll_interval_ms": pick("OAUTH_TUJIE_SMS_POLL_INTERVAL_MS", "5000"),
        "tujie_sms_account_map_file": pick(
            "OAUTH_TUJIE_SMS_ACCOUNT_MAP_FILE",
            TUJIE_DEFAULT_ACCOUNT_MAP_FILE,
        ),
    }


def build_oauth_phone_sms_config_response(
    message: str = "",
    *,
    mask_secret: Callable[[str], str],
) -> dict[str, Any]:
    cfg = oauth_phone_sms_env()
    provider = cfg["provider"]
    oasis_env = {
        "OAUTH_OASIS_SMS_CDKS": cfg["oasis_sms_cdks"],
        "OAUTH_OASIS_SMS_CDK_FILE": cfg["oasis_sms_cdk_file"],
    }
    oasis_ready = oasis_configured(oasis_env)
    tujie_env = {
        "OAUTH_TUJIE_SMS_BASE_URL": cfg["tujie_sms_base_url"],
        "OAUTH_TUJIE_SMS_CDKS": cfg["tujie_sms_cdks"],
        "OAUTH_TUJIE_SMS_CDK_FILE": cfg["tujie_sms_cdk_file"],
    }
    tujie_ready = tujie_configured(tujie_env)
    response = {
        "provider": provider,
        "providers": [
            {
                "value": "phone_pool",
                "label": "手机号池",
                "configured": True,
            },
            {
                "value": "hero_sms",
                "label": "hero-sms",
                "configured": bool(cfg["hero_sms_api_key"]),
                "secret_key": "OAUTH_HERO_SMS_API_KEY",
            },
            {
                "value": "smsbower",
                "label": "smsbower",
                "configured": bool(cfg["smsbower_api_key"]),
                "secret_key": "OAUTH_SMSBOWER_API_KEY",
            },
            {
                "value": "smscloud",
                "label": "SMSCloud",
                "configured": bool(cfg["smscloud_api_key"]),
                "secret_key": "OAUTH_SMSCLOUD_API_KEY",
            },
            {
                "value": "oasis",
                "label": "Oasis CDK",
                "configured": oasis_ready,
            },
            {
                "value": "tujie",
                "label": "TuJie CDK",
                "configured": tujie_ready,
            },
        ],
        "configured": provider == "phone_pool"
        or (provider == "hero_sms" and bool(cfg["hero_sms_api_key"]))
        or (provider == "smsbower" and bool(cfg["smsbower_api_key"]))
        or (provider == "smscloud" and bool(cfg["smscloud_api_key"]))
        or (provider == "oasis" and oasis_ready)
        or (provider == "tujie" and tujie_ready),
        "hero_sms_api_key_present": bool(cfg["hero_sms_api_key"]),
        "hero_sms_api_key_masked": mask_secret(cfg["hero_sms_api_key"]),
        "hero_sms_min_price": cfg["hero_sms_min_price"],
        "hero_sms_max_price": cfg["hero_sms_max_price"],
        "hero_sms_price_mode": cfg["hero_sms_price_mode"],
        "hero_sms_country": cfg["hero_sms_country"] or "187",
        "hero_sms_service": cfg["hero_sms_service"] or "dr",
        "smsbower_api_key_present": bool(cfg["smsbower_api_key"]),
        "smsbower_api_key_masked": mask_secret(cfg["smsbower_api_key"]),
        "smsbower_min_price": cfg["smsbower_min_price"],
        "smsbower_max_price": cfg["smsbower_max_price"],
        "smsbower_price_mode": cfg["smsbower_price_mode"],
        "smsbower_country": cfg["smsbower_country"] or "187",
        "smsbower_service": cfg["smsbower_service"] or "dr",
        "smscloud_api_key_present": bool(cfg["smscloud_api_key"]),
        "smscloud_api_key_masked": mask_secret(cfg["smscloud_api_key"]),
        "smscloud_min_price": cfg["smscloud_min_price"],
        "smscloud_max_price": cfg["smscloud_max_price"],
        "smscloud_price_mode": cfg["smscloud_price_mode"],
        "smscloud_country": cfg["smscloud_country"] or "187",
        "smscloud_service": cfg["smscloud_service"] or "dr",
        "oasis_sms_base_url": cfg["oasis_sms_base_url"] or OASIS_DEFAULT_BASE_URL,
        "oasis_sms_cdk_count": oasis_cdk_count(oasis_env),
        "oasis_sms_cdk_file": cfg["oasis_sms_cdk_file"],
        "oasis_sms_cdk_file_present": bool(cfg["oasis_sms_cdk_file"]),
        "oasis_sms_poll_attempts": cfg["oasis_sms_poll_attempts"] or "24",
        "oasis_sms_poll_interval_ms": cfg["oasis_sms_poll_interval_ms"] or "5000",
        "oasis_sms_account_map_file": cfg["oasis_sms_account_map_file"] or OASIS_DEFAULT_ACCOUNT_MAP_FILE,
        "tujie_sms_base_url": cfg["tujie_sms_base_url"] or TUJIE_DEFAULT_BASE_URL,
        "tujie_sms_cdk_count": tujie_cdk_count(tujie_env),
        "tujie_sms_cdk_file": cfg["tujie_sms_cdk_file"],
        "tujie_sms_cdk_file_present": bool(cfg["tujie_sms_cdk_file"]),
        "tujie_sms_poll_attempts": cfg["tujie_sms_poll_attempts"] or "24",
        "tujie_sms_poll_interval_ms": cfg["tujie_sms_poll_interval_ms"] or "5000",
        "tujie_sms_account_map_file": cfg["tujie_sms_account_map_file"] or TUJIE_DEFAULT_ACCOUNT_MAP_FILE,
        "hero_sms_service_label": "OpenAI",
    }
    if message:
        response["message"] = message
    return response


def oauth_phone_sms_country_fallback(provider: str) -> list[dict[str, str]]:
    common = [{"value": "all", "label": "全部国家 / 不限制"}]
    if provider in {"smsbower", "smscloud"}:
        return [
            *common,
            {"value": "187", "label": "美国 / 187"},
            {"value": "44", "label": "英国 / 44"},
            {"value": "31", "label": "南非 / 31"},
            {"value": "48", "label": "荷兰 / 48"},
            {"value": "73", "label": "巴西 / 73"},
            {"value": "6", "label": "印度尼西亚 / 6"},
            {"value": "33", "label": "哥伦比亚 / 33"},
        ]
    if provider == "hero_sms":
        return [
            *common,
            {"value": "187", "label": "美国 / 187"},
            {"value": "31", "label": "南非 / 31"},
            {"value": "48", "label": "荷兰 / 48"},
            {"value": "6", "label": "印度尼西亚 / 6"},
            {"value": "33", "label": "哥伦比亚 / 33"},
        ]
    return []


def create_oauth_phone_sms_config_router(*, mask_secret: Callable[[str], str]) -> APIRouter:
    router = APIRouter()

    @router.get("/api/config/oauth-phone-sms")
    def get_oauth_phone_sms_config():
        return build_oauth_phone_sms_config_response(mask_secret=mask_secret)

    @router.get("/api/config/oauth-phone-sms/countries")
    def get_oauth_phone_sms_countries(provider: str = ""):
        from autotoken.payments.gopay_auto_register import query_dynamic_sms_countries

        cfg = oauth_phone_sms_env()
        normalized = normalize_oauth_phone_sms_provider(provider or cfg["provider"])
        if normalized in {"phone_pool", "oasis", "tujie"}:
            return {"provider": normalized, "options": [], "count": 0, "error": ""}
        if normalized == "smsbower":
            api_key = cfg["smsbower_api_key"]
            base_url = cfg["smsbower_base_url"] or "https://smsbower.page/stubs/handler_api.php"
            service = cfg["smsbower_service"] or "dr"
        elif normalized == "smscloud":
            api_key = cfg["smscloud_api_key"]
            base_url = cfg["smscloud_base_url"] or "https://smscloud.sbs/api/system"
            service = cfg["smscloud_service"] or "dr"
        else:
            api_key = cfg["hero_sms_api_key"]
            base_url = cfg["hero_sms_base_url"] or "https://hero-sms.com/stubs/handler_api.php"
            service = cfg["hero_sms_service"] or "dr"
        fallback = oauth_phone_sms_country_fallback(normalized)
        if not api_key:
            return {
                "provider": normalized,
                "options": fallback,
                "count": len(fallback),
                "error": "缺少 API Key，使用兜底国家列表",
                "fallback": True,
            }
        if normalized == "smscloud":
            from autotoken.auth.smscloud_sms import query_smscloud_countries

            result = query_smscloud_countries(base_url=base_url, api_key=api_key, service_code=service)
        else:
            result = query_dynamic_sms_countries(
                provider=normalized,
                service_code=service,
                base_url=base_url,
                api_key=api_key,
            )
        options = result.get("options") or fallback
        if options and not any(str(option.get("value") or "") == "all" for option in options if isinstance(option, dict)):
            options = [{"value": "all", "label": "全部国家 / 不限制"}, *options]
        return {
            "provider": normalized,
            "options": options,
            "count": len(options),
            "error": result.get("error") or ("" if result.get("options") else "使用兜底国家列表"),
            "fallback": not bool(result.get("options")),
        }

    @router.put("/api/config/oauth-phone-sms")
    async def save_oauth_phone_sms_config(request: Request):
        from autotoken.settings.setup_wizard import _write_env

        data = await request.json()
        current = oauth_phone_sms_env()
        provider = normalize_oauth_phone_sms_provider(data.get("provider") or data.get("OAUTH_PHONE_SMS_PROVIDER"))
        hero_sms_api_key = str(data.get("hero_sms_api_key") or data.get("OAUTH_HERO_SMS_API_KEY") or "").strip()
        hero_sms_min_price = str(data.get("hero_sms_min_price") or data.get("OAUTH_HERO_SMS_MIN_PRICE") or "").strip()
        hero_sms_max_price = str(data.get("hero_sms_max_price") or data.get("OAUTH_HERO_SMS_MAX_PRICE") or "").strip()
        hero_sms_price_mode = normalize_oauth_sms_price_mode(
            data.get("hero_sms_price_mode")
            or data.get("OAUTH_HERO_SMS_PRICE_MODE")
            or current.get("hero_sms_price_mode")
            or "ceiling"
        )
        hero_sms_country = normalize_oauth_hero_sms_country(
            data.get("hero_sms_country") or data.get("OAUTH_HERO_SMS_COUNTRY") or current["hero_sms_country"] or "187"
        )
        smsbower_api_key = str(data.get("smsbower_api_key") or data.get("OAUTH_SMSBOWER_API_KEY") or "").strip()
        smsbower_min_price = str(data.get("smsbower_min_price") or data.get("OAUTH_SMSBOWER_MIN_PRICE") or "").strip()
        smsbower_max_price = str(data.get("smsbower_max_price") or data.get("OAUTH_SMSBOWER_MAX_PRICE") or "").strip()
        smsbower_price_mode = normalize_oauth_sms_price_mode(
            data.get("smsbower_price_mode")
            or data.get("OAUTH_SMSBOWER_PRICE_MODE")
            or current.get("smsbower_price_mode")
            or "ceiling"
        )
        smsbower_country = normalize_oauth_smsbower_country(
            data.get("smsbower_country") or data.get("OAUTH_SMSBOWER_COUNTRY") or current["smsbower_country"] or "187"
        )
        smscloud_api_key = str(data.get("smscloud_api_key") or data.get("OAUTH_SMSCLOUD_API_KEY") or "").strip()
        smscloud_min_price = str(data.get("smscloud_min_price") or data.get("OAUTH_SMSCLOUD_MIN_PRICE") or "").strip()
        smscloud_max_price = str(data.get("smscloud_max_price") or data.get("OAUTH_SMSCLOUD_MAX_PRICE") or "").strip()
        smscloud_price_mode = normalize_oauth_sms_price_mode(
            data.get("smscloud_price_mode")
            or data.get("OAUTH_SMSCLOUD_PRICE_MODE")
            or current.get("smscloud_price_mode")
            or "ceiling"
        )
        smscloud_country = normalize_oauth_smscloud_country(
            data.get("smscloud_country") or data.get("OAUTH_SMSCLOUD_COUNTRY") or current["smscloud_country"] or "187"
        )
        oasis_sms_base_url = str(
            data.get("oasis_sms_base_url")
            or data.get("OAUTH_OASIS_SMS_BASE_URL")
            or current["oasis_sms_base_url"]
            or OASIS_DEFAULT_BASE_URL
        ).strip()
        oasis_sms_cdks_raw = str(
            data.get("oasis_sms_cdks")
            or data.get("OAUTH_OASIS_SMS_CDKS")
            or current["oasis_sms_cdks"]
            or ""
        )
        oasis_sms_cdks = ",".join(normalize_oasis_cdks(oasis_sms_cdks_raw))
        oasis_sms_cdk_file = str(
            data.get("oasis_sms_cdk_file")
            or data.get("OAUTH_OASIS_SMS_CDK_FILE")
            or current["oasis_sms_cdk_file"]
            or ""
        ).strip()
        oasis_sms_poll_attempts = str(
            data.get("oasis_sms_poll_attempts")
            or data.get("OAUTH_OASIS_SMS_POLL_ATTEMPTS")
            or current["oasis_sms_poll_attempts"]
            or "24"
        ).strip()
        oasis_sms_poll_interval_ms = str(
            data.get("oasis_sms_poll_interval_ms")
            or data.get("OAUTH_OASIS_SMS_POLL_INTERVAL_MS")
            or current["oasis_sms_poll_interval_ms"]
            or "5000"
        ).strip()
        oasis_sms_account_map_file = str(
            data.get("oasis_sms_account_map_file")
            or data.get("OAUTH_OASIS_SMS_ACCOUNT_MAP_FILE")
            or current["oasis_sms_account_map_file"]
            or OASIS_DEFAULT_ACCOUNT_MAP_FILE
        ).strip()
        tujie_sms_base_url = str(
            data.get("tujie_sms_base_url")
            or data.get("OAUTH_TUJIE_SMS_BASE_URL")
            or current["tujie_sms_base_url"]
            or TUJIE_DEFAULT_BASE_URL
        ).strip()
        tujie_sms_cdks_raw = str(
            data.get("tujie_sms_cdks")
            or data.get("OAUTH_TUJIE_SMS_CDKS")
            or current["tujie_sms_cdks"]
            or ""
        )
        tujie_sms_cdks = ",".join(normalize_tujie_cdks(tujie_sms_cdks_raw))
        tujie_sms_cdk_file = str(
            data.get("tujie_sms_cdk_file")
            or data.get("OAUTH_TUJIE_SMS_CDK_FILE")
            or current["tujie_sms_cdk_file"]
            or ""
        ).strip()
        tujie_sms_poll_attempts = str(
            data.get("tujie_sms_poll_attempts")
            or data.get("OAUTH_TUJIE_SMS_POLL_ATTEMPTS")
            or current["tujie_sms_poll_attempts"]
            or "24"
        ).strip()
        tujie_sms_poll_interval_ms = str(
            data.get("tujie_sms_poll_interval_ms")
            or data.get("OAUTH_TUJIE_SMS_POLL_INTERVAL_MS")
            or current["tujie_sms_poll_interval_ms"]
            or "5000"
        ).strip()
        tujie_sms_account_map_file = str(
            data.get("tujie_sms_account_map_file")
            or data.get("OAUTH_TUJIE_SMS_ACCOUNT_MAP_FILE")
            or current["tujie_sms_account_map_file"]
            or TUJIE_DEFAULT_ACCOUNT_MAP_FILE
        ).strip()
        if provider == "hero_sms" and not (hero_sms_api_key or current["hero_sms_api_key"]):
            raise HTTPException(status_code=400, detail="启用 hero-sms 前需要配置 OAuth hero-sms API Key")
        if provider == "smsbower" and not (smsbower_api_key or current["smsbower_api_key"]):
            raise HTTPException(status_code=400, detail="启用 smsbower 前需要配置 OAuth smsbower API Key")
        if provider == "smscloud" and not (smscloud_api_key or current["smscloud_api_key"]):
            raise HTTPException(status_code=400, detail="启用 SMSCloud 前需要配置 OAuth SMSCloud API Key")
        if provider == "oasis" and not (oasis_sms_cdks or oasis_sms_cdk_file):
            raise HTTPException(status_code=400, detail="启用 Oasis 前需要配置 CDK 池或 CDK 文件")
        if provider == "tujie":
            if not (tujie_sms_cdks or tujie_sms_cdk_file):
                raise HTTPException(status_code=400, detail="启用 TuJie 前需要配置 CDK 池或 CDK 文件")

        updates = {
            "OAUTH_PHONE_SMS_PROVIDER": provider,
            "OAUTH_HERO_SMS_MIN_PRICE": hero_sms_min_price,
            "OAUTH_HERO_SMS_MAX_PRICE": hero_sms_max_price,
            "OAUTH_HERO_SMS_PRICE_MODE": hero_sms_price_mode,
            "OAUTH_HERO_SMS_BASE_URL": "https://hero-sms.com/stubs/handler_api.php",
            "OAUTH_HERO_SMS_COUNTRY": hero_sms_country,
            "OAUTH_HERO_SMS_SERVICE": "dr",
            "OAUTH_SMSBOWER_MIN_PRICE": smsbower_min_price,
            "OAUTH_SMSBOWER_MAX_PRICE": smsbower_max_price,
            "OAUTH_SMSBOWER_PRICE_MODE": smsbower_price_mode,
            "OAUTH_SMSBOWER_BASE_URL": "https://smsbower.page/stubs/handler_api.php",
            "OAUTH_SMSBOWER_COUNTRY": smsbower_country,
            "OAUTH_SMSBOWER_SERVICE": "dr",
            "OAUTH_SMSCLOUD_MIN_PRICE": smscloud_min_price,
            "OAUTH_SMSCLOUD_MAX_PRICE": smscloud_max_price,
            "OAUTH_SMSCLOUD_PRICE_MODE": smscloud_price_mode,
            "OAUTH_SMSCLOUD_BASE_URL": "https://smscloud.sbs/api/system",
            "OAUTH_SMSCLOUD_COUNTRY": smscloud_country,
            "OAUTH_SMSCLOUD_SERVICE": "dr",
            "OAUTH_OASIS_SMS_BASE_URL": oasis_sms_base_url or OASIS_DEFAULT_BASE_URL,
            "OAUTH_OASIS_SMS_CDKS": oasis_sms_cdks,
            "OAUTH_OASIS_SMS_CDK_FILE": oasis_sms_cdk_file,
            "OAUTH_OASIS_SMS_POLL_ATTEMPTS": oasis_sms_poll_attempts or "24",
            "OAUTH_OASIS_SMS_POLL_INTERVAL_MS": oasis_sms_poll_interval_ms or "5000",
            "OAUTH_OASIS_SMS_ACCOUNT_MAP_FILE": oasis_sms_account_map_file or OASIS_DEFAULT_ACCOUNT_MAP_FILE,
            "OAUTH_TUJIE_SMS_BASE_URL": tujie_sms_base_url or TUJIE_DEFAULT_BASE_URL,
            "OAUTH_TUJIE_SMS_CDKS": tujie_sms_cdks,
            "OAUTH_TUJIE_SMS_CDK_FILE": tujie_sms_cdk_file,
            "OAUTH_TUJIE_SMS_POLL_ATTEMPTS": tujie_sms_poll_attempts or "24",
            "OAUTH_TUJIE_SMS_POLL_INTERVAL_MS": tujie_sms_poll_interval_ms or "5000",
            "OAUTH_TUJIE_SMS_ACCOUNT_MAP_FILE": tujie_sms_account_map_file or TUJIE_DEFAULT_ACCOUNT_MAP_FILE,
        }
        if hero_sms_api_key:
            updates["OAUTH_HERO_SMS_API_KEY"] = hero_sms_api_key
        if smsbower_api_key:
            updates["OAUTH_SMSBOWER_API_KEY"] = smsbower_api_key
        if smscloud_api_key:
            updates["OAUTH_SMSCLOUD_API_KEY"] = smscloud_api_key

        for key, value in updates.items():
            _write_env(key, value)
            os.environ[key] = value

        return build_oauth_phone_sms_config_response("OAuth 手机号接码配置已保存", mask_secret=mask_secret)

    return router
