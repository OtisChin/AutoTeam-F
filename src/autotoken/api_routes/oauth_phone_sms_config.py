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


def normalize_oauth_phone_sms_provider(raw: str | None = None) -> str:
    value = str(raw or "").strip().lower().replace("-", "_")
    if value in {"hero_sms", "herosms", "hero"}:
        return "hero_sms"
    if value in {"smsbower", "sms_bower"}:
        return "smsbower"
    if value in {"oasis", "oasis_sms", "oasissms", "oapi"}:
        return "oasis"
    return "phone_pool"


def normalize_oauth_hero_sms_service(raw: str | None = None) -> str:
    value = str(raw or "").strip().lower().replace("-", "_")
    if value in {"", "openai", "chatgpt", "chat_gpt", "gpt"}:
        return "dr"
    return value


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


def oauth_phone_sms_env() -> dict[str, str]:
    from autotoken.settings.setup_wizard import _read_env

    env = _read_env()

    def pick(key: str, default: str = "") -> str:
        return str(env.get(key, "") or os.environ.get(key, "") or default).strip()

    return {
        "provider": normalize_oauth_phone_sms_provider(pick("OAUTH_PHONE_SMS_PROVIDER", "phone_pool")),
        "hero_sms_api_key": pick("OAUTH_HERO_SMS_API_KEY"),
        "hero_sms_max_price": pick("OAUTH_HERO_SMS_MAX_PRICE"),
        "hero_sms_base_url": pick("OAUTH_HERO_SMS_BASE_URL", "https://hero-sms.com/stubs/handler_api.php"),
        "hero_sms_country": normalize_oauth_hero_sms_country(pick("OAUTH_HERO_SMS_COUNTRY", "187")),
        "hero_sms_service": normalize_oauth_hero_sms_service(pick("OAUTH_HERO_SMS_SERVICE", "dr")),
        "smsbower_api_key": pick("OAUTH_SMSBOWER_API_KEY"),
        "smsbower_max_price": pick("OAUTH_SMSBOWER_MAX_PRICE"),
        "smsbower_base_url": pick("OAUTH_SMSBOWER_BASE_URL", "https://smsbower.page/stubs/handler_api.php"),
        "smsbower_country": normalize_oauth_smsbower_country(pick("OAUTH_SMSBOWER_COUNTRY", "187")),
        "smsbower_service": normalize_oauth_hero_sms_service(pick("OAUTH_SMSBOWER_SERVICE", "dr")),
        "oasis_sms_base_url": pick("OAUTH_OASIS_SMS_BASE_URL", OASIS_DEFAULT_BASE_URL),
        "oasis_sms_cdks": pick("OAUTH_OASIS_SMS_CDKS"),
        "oasis_sms_cdk_file": pick("OAUTH_OASIS_SMS_CDK_FILE"),
        "oasis_sms_poll_attempts": pick("OAUTH_OASIS_SMS_POLL_ATTEMPTS", "24"),
        "oasis_sms_poll_interval_ms": pick("OAUTH_OASIS_SMS_POLL_INTERVAL_MS", "5000"),
        "oasis_sms_account_map_file": pick(
            "OAUTH_OASIS_SMS_ACCOUNT_MAP_FILE",
            OASIS_DEFAULT_ACCOUNT_MAP_FILE,
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
                "value": "oasis",
                "label": "Oasis CDK",
                "configured": oasis_ready,
            },
        ],
        "configured": provider == "phone_pool"
        or (provider == "hero_sms" and bool(cfg["hero_sms_api_key"]))
        or (provider == "smsbower" and bool(cfg["smsbower_api_key"]))
        or (provider == "oasis" and oasis_ready),
        "hero_sms_api_key_present": bool(cfg["hero_sms_api_key"]),
        "hero_sms_api_key_masked": mask_secret(cfg["hero_sms_api_key"]),
        "hero_sms_max_price": cfg["hero_sms_max_price"],
        "hero_sms_country": cfg["hero_sms_country"] or "187",
        "hero_sms_service": cfg["hero_sms_service"] or "dr",
        "smsbower_api_key_present": bool(cfg["smsbower_api_key"]),
        "smsbower_api_key_masked": mask_secret(cfg["smsbower_api_key"]),
        "smsbower_max_price": cfg["smsbower_max_price"],
        "smsbower_country": cfg["smsbower_country"] or "187",
        "smsbower_service": cfg["smsbower_service"] or "dr",
        "oasis_sms_base_url": cfg["oasis_sms_base_url"] or OASIS_DEFAULT_BASE_URL,
        "oasis_sms_cdk_count": oasis_cdk_count(oasis_env),
        "oasis_sms_cdk_file": cfg["oasis_sms_cdk_file"],
        "oasis_sms_cdk_file_present": bool(cfg["oasis_sms_cdk_file"]),
        "oasis_sms_poll_attempts": cfg["oasis_sms_poll_attempts"] or "24",
        "oasis_sms_poll_interval_ms": cfg["oasis_sms_poll_interval_ms"] or "5000",
        "oasis_sms_account_map_file": cfg["oasis_sms_account_map_file"] or OASIS_DEFAULT_ACCOUNT_MAP_FILE,
        "hero_sms_service_label": "OpenAI",
    }
    if message:
        response["message"] = message
    return response


def oauth_phone_sms_country_fallback(provider: str) -> list[dict[str, str]]:
    common = [{"value": "all", "label": "全部国家 / 不限制"}]
    if provider == "smsbower":
        return [
            *common,
            {"value": "187", "label": "美国 / 187"},
            {"value": "6", "label": "印度尼西亚 / 6"},
            {"value": "33", "label": "哥伦比亚 / 33"},
        ]
    if provider == "hero_sms":
        return [
            *common,
            {"value": "187", "label": "美国 / 187"},
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
        if normalized in {"phone_pool", "oasis"}:
            return {"provider": normalized, "options": [], "count": 0, "error": ""}
        if normalized == "smsbower":
            api_key = cfg["smsbower_api_key"]
            base_url = cfg["smsbower_base_url"] or "https://smsbower.page/stubs/handler_api.php"
            service = cfg["smsbower_service"] or "dr"
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
        hero_sms_max_price = str(data.get("hero_sms_max_price") or data.get("OAUTH_HERO_SMS_MAX_PRICE") or "").strip()
        hero_sms_country = normalize_oauth_hero_sms_country(
            data.get("hero_sms_country") or data.get("OAUTH_HERO_SMS_COUNTRY") or current["hero_sms_country"] or "187"
        )
        smsbower_api_key = str(data.get("smsbower_api_key") or data.get("OAUTH_SMSBOWER_API_KEY") or "").strip()
        smsbower_max_price = str(data.get("smsbower_max_price") or data.get("OAUTH_SMSBOWER_MAX_PRICE") or "").strip()
        smsbower_country = normalize_oauth_smsbower_country(
            data.get("smsbower_country") or data.get("OAUTH_SMSBOWER_COUNTRY") or current["smsbower_country"] or "187"
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
        if provider == "hero_sms" and not (hero_sms_api_key or current["hero_sms_api_key"]):
            raise HTTPException(status_code=400, detail="启用 hero-sms 前需要配置 OAuth hero-sms API Key")
        if provider == "smsbower" and not (smsbower_api_key or current["smsbower_api_key"]):
            raise HTTPException(status_code=400, detail="启用 smsbower 前需要配置 OAuth smsbower API Key")
        if provider == "oasis" and not (oasis_sms_cdks or oasis_sms_cdk_file):
            raise HTTPException(status_code=400, detail="启用 Oasis 前需要配置 CDK 池或 CDK 文件")

        updates = {
            "OAUTH_PHONE_SMS_PROVIDER": provider,
            "OAUTH_HERO_SMS_MAX_PRICE": hero_sms_max_price,
            "OAUTH_HERO_SMS_BASE_URL": "https://hero-sms.com/stubs/handler_api.php",
            "OAUTH_HERO_SMS_COUNTRY": hero_sms_country,
            "OAUTH_HERO_SMS_SERVICE": "dr",
            "OAUTH_SMSBOWER_MAX_PRICE": smsbower_max_price,
            "OAUTH_SMSBOWER_BASE_URL": "https://smsbower.page/stubs/handler_api.php",
            "OAUTH_SMSBOWER_COUNTRY": smsbower_country,
            "OAUTH_SMSBOWER_SERVICE": "dr",
            "OAUTH_OASIS_SMS_BASE_URL": oasis_sms_base_url or OASIS_DEFAULT_BASE_URL,
            "OAUTH_OASIS_SMS_CDKS": oasis_sms_cdks,
            "OAUTH_OASIS_SMS_CDK_FILE": oasis_sms_cdk_file,
            "OAUTH_OASIS_SMS_POLL_ATTEMPTS": oasis_sms_poll_attempts or "24",
            "OAUTH_OASIS_SMS_POLL_INTERVAL_MS": oasis_sms_poll_interval_ms or "5000",
            "OAUTH_OASIS_SMS_ACCOUNT_MAP_FILE": oasis_sms_account_map_file or OASIS_DEFAULT_ACCOUNT_MAP_FILE,
        }
        if hero_sms_api_key:
            updates["OAUTH_HERO_SMS_API_KEY"] = hero_sms_api_key
        if smsbower_api_key:
            updates["OAUTH_SMSBOWER_API_KEY"] = smsbower_api_key

        for key, value in updates.items():
            _write_env(key, value)
            os.environ[key] = value

        return build_oauth_phone_sms_config_response("OAuth 手机号接码配置已保存", mask_secret=mask_secret)

    return router
