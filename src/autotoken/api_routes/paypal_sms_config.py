"""PayPal no-card signup SMS provider configuration routes."""

import os
import re
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request

SUPPORTED_PAYPAL_SMS_PROVIDERS = {"hero_sms", "smsbower", "smscode", "smscloud"}


def normalize_paypal_sms_provider(raw: str | None = None) -> str:
    value = re.sub(r"[^a-z0-9_ -]+", "", str(raw or "").strip().lower())
    value = value.replace("-", "_").replace(" ", "_")
    if value in {"", "manual", "explicit", "explicit_env"}:
        return "manual"
    if value in {"hero", "herosms", "hero_sms"}:
        return "hero_sms"
    if value in {"smsbower", "sms_bower"}:
        return "smsbower"
    if value in {"smscode", "sms_code", "smscode_gg"}:
        return "smscode"
    if value in {"smscloud", "sms_cloud"}:
        return "smscloud"
    return value


def paypal_sms_env() -> dict[str, str]:
    from autotoken.settings.setup_wizard import _read_env

    env = _read_env()

    def pick(key: str, default: str = "") -> str:
        return str(env.get(key, "") or os.environ.get(key, "") or default).strip()

    return {
        "provider": normalize_paypal_sms_provider(pick("PAYPAL_SMS_PROVIDER", "manual")),
        "sms_url": pick("PAYPAL_SMS_URL"),
        "phone_number": pick("PAYPAL_PHONE_NUMBER") or pick("PAYPAL_SMS_PHONE_NUMBER") or pick("PAYPAL_BILLING_PHONE"),
        "otp_channel": pick("PAYPAL_OTP_CHANNEL", "sms").lower() or "sms",
        "phone_country_code": pick("PAYPAL_SMS_PHONE_COUNTRY_CODE", pick("PAYPAL_PHONE_COUNTRY_CODE", "81")),
        "sms_api_key": pick("PAYPAL_SMS_API_KEY"),
        "hero_sms_api_key": pick("PAYPAL_HERO_SMS_API_KEY", pick("PAYPAL_SMS_API_KEY")),
        "hero_sms_base_url": pick("PAYPAL_HERO_SMS_BASE_URL", pick("PAYPAL_SMS_BASE_URL", "https://hero-sms.com/stubs/handler_api.php")),
        "hero_sms_country": pick("PAYPAL_HERO_SMS_COUNTRY", pick("PAYPAL_SMS_COUNTRY", "4")),
        "hero_sms_service": pick("PAYPAL_HERO_SMS_SERVICE", pick("PAYPAL_SMS_SERVICE", "ts")),
        "hero_sms_min_price": pick("PAYPAL_HERO_SMS_MIN_PRICE", pick("PAYPAL_SMS_MIN_PRICE")),
        "hero_sms_max_price": pick("PAYPAL_HERO_SMS_MAX_PRICE", pick("PAYPAL_SMS_MAX_PRICE")),
        "hero_sms_preferred_price": pick("PAYPAL_HERO_SMS_PREFERRED_PRICE", pick("PAYPAL_SMS_PREFERRED_PRICE")),
        "smsbower_api_key": pick("PAYPAL_SMSBOWER_API_KEY", pick("PAYPAL_SMS_API_KEY")),
        "smsbower_base_url": pick("PAYPAL_SMSBOWER_BASE_URL", pick("PAYPAL_SMS_BASE_URL", "https://smsbower.page/stubs/handler_api.php")),
        "smsbower_country": pick("PAYPAL_SMSBOWER_COUNTRY", pick("PAYPAL_SMS_COUNTRY", "4")),
        "smsbower_service": pick("PAYPAL_SMSBOWER_SERVICE", pick("PAYPAL_SMS_SERVICE", "ts")),
        "smsbower_min_price": pick("PAYPAL_SMSBOWER_MIN_PRICE", pick("PAYPAL_SMS_MIN_PRICE")),
        "smsbower_max_price": pick("PAYPAL_SMSBOWER_MAX_PRICE", pick("PAYPAL_SMS_MAX_PRICE")),
        "smsbower_preferred_price": pick("PAYPAL_SMSBOWER_PREFERRED_PRICE", pick("PAYPAL_SMS_PREFERRED_PRICE")),
        "smscode_api_token": pick("PAYPAL_SMSCODE_API_TOKEN", pick("PAYPAL_SMS_API_KEY")),
        "smscode_base_url": pick("PAYPAL_SMSCODE_BASE_URL", pick("PAYPAL_SMS_BASE_URL", "https://api.smscode.gg/v1")),
        "smscode_country_id": pick("PAYPAL_SMSCODE_COUNTRY_ID", pick("PAYPAL_SMS_COUNTRY", "4")),
        "smscode_platform_id": pick("PAYPAL_SMSCODE_PLATFORM_ID"),
        "smscode_platform_query": pick("PAYPAL_SMSCODE_PLATFORM_QUERY", pick("PAYPAL_SMS_SERVICE", "paypal")),
        "smscode_product_id": pick("PAYPAL_SMSCODE_PRODUCT_ID"),
        "smscode_min_price": pick("PAYPAL_SMSCODE_MIN_PRICE", pick("PAYPAL_SMS_MIN_PRICE")),
        "smscode_max_price": pick("PAYPAL_SMSCODE_MAX_PRICE", pick("PAYPAL_SMS_MAX_PRICE")),
        "smscloud_xi_token": pick("PAYPAL_SMSCLOUD_XI_TOKEN", pick("PAYPAL_SMS_API_KEY")),
        "smscloud_base_url": pick("PAYPAL_SMSCLOUD_BASE_URL", pick("PAYPAL_SMS_BASE_URL", "https://smscloud.sbs/api")),
        "smscloud_country": pick("PAYPAL_SMSCLOUD_COUNTRY", pick("PAYPAL_SMS_COUNTRY", "4")),
        "smscloud_service": pick("PAYPAL_SMSCLOUD_SERVICE", pick("PAYPAL_SMS_SERVICE", "paypal")),
        "smscloud_max_price": pick("PAYPAL_SMSCLOUD_MAX_PRICE", pick("PAYPAL_SMS_MAX_PRICE")),
    }


def build_paypal_sms_config_response(
    message: str = "",
    *,
    mask_secret: Callable[[str], str],
) -> dict[str, Any]:
    cfg = paypal_sms_env()
    provider = cfg["provider"]
    configured_by_provider = {
        "manual": bool(cfg["sms_url"] and cfg["phone_number"]),
        "hero_sms": bool(cfg["hero_sms_api_key"]),
        "smsbower": bool(cfg["smsbower_api_key"]),
        "smscode": bool(cfg["smscode_api_token"]),
        "smscloud": bool(cfg["smscloud_xi_token"]),
    }
    response = {
        "provider": provider,
        "configured": bool(configured_by_provider.get(provider)),
        "manual_configured": bool(cfg["sms_url"] and cfg["phone_number"]),
        "auto_provider_configured": bool(configured_by_provider.get(provider)) if provider != "manual" else False,
        "providers": [
            {"value": "manual", "label": "已有接码链接", "configured": bool(cfg["sms_url"] and cfg["phone_number"])},
            {"value": "hero_sms", "label": "hero-sms", "configured": bool(cfg["hero_sms_api_key"]), "secret_key": "PAYPAL_HERO_SMS_API_KEY"},
            {"value": "smsbower", "label": "smsbower", "configured": bool(cfg["smsbower_api_key"]), "secret_key": "PAYPAL_SMSBOWER_API_KEY"},
            {"value": "smscode", "label": "smscode.gg", "configured": bool(cfg["smscode_api_token"]), "secret_key": "PAYPAL_SMSCODE_API_TOKEN"},
            {"value": "smscloud", "label": "smscloud", "configured": bool(cfg["smscloud_xi_token"]), "secret_key": "PAYPAL_SMSCLOUD_XI_TOKEN"},
        ],
        "sms_url_present": bool(cfg["sms_url"]),
        "phone_number_present": bool(cfg["phone_number"]),
        "otp_channel": cfg["otp_channel"] if cfg["otp_channel"] in {"sms", "whatsapp"} else "sms",
        "phone_country_code": cfg["phone_country_code"] or "81",
        "sms_api_key_present": bool(cfg["sms_api_key"]),
        "sms_api_key_masked": mask_secret(cfg["sms_api_key"]),
    }
    for name in ("hero_sms", "smsbower", "smscode", "smscloud"):
        secret_key = "xi_token" if name == "smscloud" else ("api_token" if name == "smscode" else "api_key")
        secret_value = cfg[f"{name}_{secret_key}"]
        response[f"{name}_{secret_key}_present"] = bool(secret_value)
        response[f"{name}_{secret_key}_masked"] = mask_secret(secret_value)
        for suffix in (
            "base_url",
            "country",
            "service",
            "min_price",
            "max_price",
            "preferred_price",
            "country_id",
            "platform_id",
            "platform_query",
            "product_id",
        ):
            key = f"{name}_{suffix}"
            if key in cfg:
                response[key] = cfg[key]
    if message:
        response["message"] = message
    return response


def create_paypal_sms_config_router(*, mask_secret: Callable[[str], str]) -> APIRouter:
    router = APIRouter()

    @router.get("/api/config/paypal-sms")
    def get_paypal_sms_config():
        return build_paypal_sms_config_response(mask_secret=mask_secret)

    @router.put("/api/config/paypal-sms")
    async def save_paypal_sms_config(request: Request):
        from autotoken.settings.setup_wizard import _write_env

        data = await request.json()
        current = paypal_sms_env()
        provider = normalize_paypal_sms_provider(data.get("provider") or data.get("PAYPAL_SMS_PROVIDER"))
        if provider not in {"manual", *SUPPORTED_PAYPAL_SMS_PROVIDERS}:
            raise HTTPException(status_code=400, detail="PAYPAL_SMS_PROVIDER 只支持 manual、hero_sms、smsbower、smscode 或 smscloud")

        sms_url = str(data.get("sms_url") or data.get("PAYPAL_SMS_URL") or "").strip()
        phone_number = str(data.get("phone_number") or data.get("PAYPAL_PHONE_NUMBER") or "").strip()
        if provider == "manual" and not ((sms_url or current["sms_url"]) and (phone_number or current["phone_number"])):
            raise HTTPException(status_code=400, detail="已有接码链接模式需要 PAYPAL_SMS_URL 与 PAYPAL_PHONE_NUMBER")

        secret_inputs = {
            "hero_sms": str(data.get("hero_sms_api_key") or data.get("PAYPAL_HERO_SMS_API_KEY") or "").strip(),
            "smsbower": str(data.get("smsbower_api_key") or data.get("PAYPAL_SMSBOWER_API_KEY") or "").strip(),
            "smscode": str(data.get("smscode_api_token") or data.get("PAYPAL_SMSCODE_API_TOKEN") or "").strip(),
            "smscloud": str(data.get("smscloud_xi_token") or data.get("PAYPAL_SMSCLOUD_XI_TOKEN") or "").strip(),
        }
        current_secret = {
            "hero_sms": current["hero_sms_api_key"],
            "smsbower": current["smsbower_api_key"],
            "smscode": current["smscode_api_token"],
            "smscloud": current["smscloud_xi_token"],
        }
        if provider in SUPPORTED_PAYPAL_SMS_PROVIDERS and not (secret_inputs[provider] or current_secret[provider]):
            raise HTTPException(status_code=400, detail=f"启用 {provider} 前需要配置对应 PayPal SMS API Key/Token")

        updates = {
            "PAYPAL_SMS_PROVIDER": "" if provider == "manual" else provider,
            "PAYPAL_OTP_CHANNEL": str(data.get("otp_channel") or current["otp_channel"] or "sms").strip().lower() or "sms",
            "PAYPAL_SMS_PHONE_COUNTRY_CODE": str(data.get("phone_country_code") or current["phone_country_code"] or "81").strip(),
            "PAYPAL_HERO_SMS_BASE_URL": str(data.get("hero_sms_base_url") or current["hero_sms_base_url"] or "https://hero-sms.com/stubs/handler_api.php").strip(),
            "PAYPAL_HERO_SMS_COUNTRY": str(data.get("hero_sms_country") or current["hero_sms_country"] or "4").strip(),
            "PAYPAL_HERO_SMS_SERVICE": str(data.get("hero_sms_service") or current["hero_sms_service"] or "ts").strip(),
            "PAYPAL_HERO_SMS_MIN_PRICE": str(data.get("hero_sms_min_price") or "").strip(),
            "PAYPAL_HERO_SMS_MAX_PRICE": str(data.get("hero_sms_max_price") or "").strip(),
            "PAYPAL_HERO_SMS_PREFERRED_PRICE": str(data.get("hero_sms_preferred_price") or "").strip(),
            "PAYPAL_SMSBOWER_BASE_URL": str(data.get("smsbower_base_url") or current["smsbower_base_url"] or "https://smsbower.page/stubs/handler_api.php").strip(),
            "PAYPAL_SMSBOWER_COUNTRY": str(data.get("smsbower_country") or current["smsbower_country"] or "4").strip(),
            "PAYPAL_SMSBOWER_SERVICE": str(data.get("smsbower_service") or current["smsbower_service"] or "ts").strip(),
            "PAYPAL_SMSBOWER_MIN_PRICE": str(data.get("smsbower_min_price") or "").strip(),
            "PAYPAL_SMSBOWER_MAX_PRICE": str(data.get("smsbower_max_price") or "").strip(),
            "PAYPAL_SMSBOWER_PREFERRED_PRICE": str(data.get("smsbower_preferred_price") or "").strip(),
            "PAYPAL_SMSCODE_BASE_URL": str(data.get("smscode_base_url") or current["smscode_base_url"] or "https://api.smscode.gg/v1").strip(),
            "PAYPAL_SMSCODE_COUNTRY_ID": str(data.get("smscode_country_id") or current["smscode_country_id"] or "4").strip(),
            "PAYPAL_SMSCODE_PLATFORM_ID": str(data.get("smscode_platform_id") or "").strip(),
            "PAYPAL_SMSCODE_PLATFORM_QUERY": str(data.get("smscode_platform_query") or current["smscode_platform_query"] or "paypal").strip(),
            "PAYPAL_SMSCODE_PRODUCT_ID": str(data.get("smscode_product_id") or "").strip(),
            "PAYPAL_SMSCODE_MIN_PRICE": str(data.get("smscode_min_price") or "").strip(),
            "PAYPAL_SMSCODE_MAX_PRICE": str(data.get("smscode_max_price") or "").strip(),
            "PAYPAL_SMSCLOUD_BASE_URL": str(data.get("smscloud_base_url") or current["smscloud_base_url"] or "https://smscloud.sbs/api").strip(),
            "PAYPAL_SMSCLOUD_COUNTRY": str(data.get("smscloud_country") or current["smscloud_country"] or "4").strip(),
            "PAYPAL_SMSCLOUD_SERVICE": str(data.get("smscloud_service") or current["smscloud_service"] or "paypal").strip(),
            "PAYPAL_SMSCLOUD_MAX_PRICE": str(data.get("smscloud_max_price") or "").strip(),
        }
        if sms_url:
            updates["PAYPAL_SMS_URL"] = sms_url
        if phone_number:
            updates["PAYPAL_PHONE_NUMBER"] = phone_number
        if secret_inputs["hero_sms"]:
            updates["PAYPAL_HERO_SMS_API_KEY"] = secret_inputs["hero_sms"]
        if secret_inputs["smsbower"]:
            updates["PAYPAL_SMSBOWER_API_KEY"] = secret_inputs["smsbower"]
        if secret_inputs["smscode"]:
            updates["PAYPAL_SMSCODE_API_TOKEN"] = secret_inputs["smscode"]
        if secret_inputs["smscloud"]:
            updates["PAYPAL_SMSCLOUD_XI_TOKEN"] = secret_inputs["smscloud"]

        for key, value in updates.items():
            _write_env(key, value)
            os.environ[key] = value

        return build_paypal_sms_config_response("PayPal 接码配置已保存", mask_secret=mask_secret)

    return router
