"""GoPay automatic signup configuration and SMS price routes."""

import os
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import AliasChoices, BaseModel, Field


def normalize_gopay_auto_signup_sms_provider(raw: str | None = None) -> str:
    value = str(raw or "").strip().lower().replace("-", "_")
    if value in {"hero_sms", "herosms"}:
        return "hero_sms"
    if value in {"smsbower", "sms_bower"}:
        return "smsbower"
    if value in {"smscode", "sms_code", "smscode_gg"}:
        return "smscode"
    return "smscloud"


def normalize_gopay_auto_signup_mode(raw: str | None = None) -> str:
    value = str(raw or "").strip().lower()
    return "appium" if value == "appium" else "http"


def gopay_auto_signup_env() -> dict[str, str]:
    from autotoken.settings.setup_wizard import _read_env

    env = _read_env()

    def pick(key: str, default: str = "") -> str:
        return str(env.get(key, "") or os.environ.get(key, "") or default).strip()

    return {
        "provider": normalize_gopay_auto_signup_sms_provider(pick("GOPAY_AUTO_SIGNUP_SMS_PROVIDER", "smscloud")),
        "smscloud_xi_token": pick("GOPAY_AUTO_SIGNUP_SMSCLOUD_XI_TOKEN"),
        "hero_sms_api_key": pick("GOPAY_AUTO_SIGNUP_HERO_SMS_API_KEY"),
        "hero_sms_base_url": pick("GOPAY_AUTO_SIGNUP_HERO_SMS_BASE_URL", "https://hero-sms.com/stubs/handler_api.php"),
        "hero_sms_country": pick("GOPAY_AUTO_SIGNUP_HERO_SMS_COUNTRY", "6"),
        "hero_sms_service": pick("GOPAY_AUTO_SIGNUP_HERO_SMS_SERVICE", "ni"),
        "hero_sms_min_price": pick("GOPAY_AUTO_SIGNUP_HERO_SMS_MIN_PRICE"),
        "hero_sms_max_price": pick("GOPAY_AUTO_SIGNUP_HERO_SMS_MAX_PRICE"),
        "hero_sms_preferred_price": pick("GOPAY_AUTO_SIGNUP_HERO_SMS_PREFERRED_PRICE"),
        "smsbower_api_key": pick("GOPAY_AUTO_SIGNUP_SMSBOWER_API_KEY") or pick("OAUTH_SMSBOWER_API_KEY"),
        "smsbower_base_url": pick("GOPAY_AUTO_SIGNUP_SMSBOWER_BASE_URL", "https://smsbower.page/stubs/handler_api.php"),
        "smsbower_country": pick("GOPAY_AUTO_SIGNUP_SMSBOWER_COUNTRY", "6"),
        "smsbower_service": pick("GOPAY_AUTO_SIGNUP_SMSBOWER_SERVICE", "ni"),
        "smsbower_min_price": pick("GOPAY_AUTO_SIGNUP_SMSBOWER_MIN_PRICE"),
        "smsbower_max_price": pick("GOPAY_AUTO_SIGNUP_SMSBOWER_MAX_PRICE"),
        "smsbower_preferred_price": pick("GOPAY_AUTO_SIGNUP_SMSBOWER_PREFERRED_PRICE"),
        "smscode_api_token": pick("GOPAY_AUTO_SIGNUP_SMSCODE_API_TOKEN"),
        "smscode_base_url": pick("GOPAY_AUTO_SIGNUP_SMSCODE_BASE_URL", "https://api.smscode.gg/v1"),
        "smscode_country_id": pick("GOPAY_AUTO_SIGNUP_SMSCODE_COUNTRY_ID", "7"),
        "smscode_platform_id": pick("GOPAY_AUTO_SIGNUP_SMSCODE_PLATFORM_ID"),
        "smscode_platform_query": pick("GOPAY_AUTO_SIGNUP_SMSCODE_PLATFORM_QUERY", "gojek"),
        "smscode_product_id": pick("GOPAY_AUTO_SIGNUP_SMSCODE_PRODUCT_ID"),
        "smscode_min_price": pick("GOPAY_AUTO_SIGNUP_SMSCODE_MIN_PRICE"),
        "smscode_max_price": pick("GOPAY_AUTO_SIGNUP_SMSCODE_MAX_PRICE"),
        "proxy_url": pick("GOPAY_AUTO_SIGNUP_PROXY_URL"),
        "country_code": pick("GOPAY_AUTO_SIGNUP_COUNTRY_CODE", "+62"),
        "signup_mode": normalize_gopay_auto_signup_mode(pick("GOPAY_AUTO_SIGNUP_MODE", "http")),
        "appium_url": pick("GOPAY_APPIUM_URL", "http://127.0.0.1:4723"),
        "appium_adb_serial": pick("GOPAY_APPIUM_ADB_SERIAL"),
    }


def build_gopay_auto_signup_config_response(
    message: str = "",
    *,
    mask_secret: Callable[[str], str],
    provider: str | None = None,
    country_code: str | None = None,
) -> dict[str, Any]:
    cfg = gopay_auto_signup_env()
    selected_provider = provider or cfg["provider"]
    configured = {
        "smscloud": bool(cfg["smscloud_xi_token"]),
        "hero_sms": bool(cfg["hero_sms_api_key"]),
        "smsbower": bool(cfg["smsbower_api_key"]),
        "smscode": bool(cfg["smscode_api_token"]),
    }
    response = {
        "provider": selected_provider,
        "country_code": country_code or cfg["country_code"] or "+62",
        "providers": [
            {
                "value": "smscloud",
                "label": "smscloud",
                "configured": bool(cfg["smscloud_xi_token"]),
                "secret_key": "GOPAY_AUTO_SIGNUP_SMSCLOUD_XI_TOKEN",
            },
            {
                "value": "hero_sms",
                "label": "hero-sms",
                "configured": bool(cfg["hero_sms_api_key"]),
                "secret_key": "GOPAY_AUTO_SIGNUP_HERO_SMS_API_KEY",
            },
            {
                "value": "smsbower",
                "label": "smsbower",
                "configured": bool(cfg["smsbower_api_key"]),
                "secret_key": "GOPAY_AUTO_SIGNUP_SMSBOWER_API_KEY",
            },
            {
                "value": "smscode",
                "label": "smscode.gg",
                "configured": bool(cfg["smscode_api_token"]),
                "secret_key": "GOPAY_AUTO_SIGNUP_SMSCODE_API_TOKEN",
            },
        ],
        "configured": bool(configured.get(selected_provider)),
        "smscloud_xi_token_present": bool(cfg["smscloud_xi_token"]),
        "hero_sms_api_key_present": bool(cfg["hero_sms_api_key"]),
        "smsbower_api_key_present": bool(cfg["smsbower_api_key"]),
        "smscode_api_token_present": bool(cfg["smscode_api_token"]),
        "smscloud_xi_token_masked": mask_secret(cfg["smscloud_xi_token"]),
        "hero_sms_api_key_masked": mask_secret(cfg["hero_sms_api_key"]),
        "smsbower_api_key_masked": mask_secret(cfg["smsbower_api_key"]),
        "smscode_api_token_masked": mask_secret(cfg["smscode_api_token"]),
        "hero_sms_base_url": cfg.get("hero_sms_base_url", "https://hero-sms.com/stubs/handler_api.php"),
        "hero_sms_country": cfg.get("hero_sms_country", "6"),
        "hero_sms_service": cfg.get("hero_sms_service", "ni"),
        "hero_sms_min_price": cfg.get("hero_sms_min_price", ""),
        "hero_sms_max_price": cfg.get("hero_sms_max_price", ""),
        "hero_sms_preferred_price": cfg.get("hero_sms_preferred_price", ""),
        "smsbower_base_url": cfg.get("smsbower_base_url", "https://smsbower.page/stubs/handler_api.php"),
        "smsbower_country": cfg.get("smsbower_country", "6"),
        "smsbower_service": cfg.get("smsbower_service", "ni"),
        "smsbower_min_price": cfg.get("smsbower_min_price", ""),
        "smsbower_max_price": cfg.get("smsbower_max_price", ""),
        "smsbower_preferred_price": cfg.get("smsbower_preferred_price", ""),
        "smscode_base_url": cfg.get("smscode_base_url", "https://api.smscode.gg/v1"),
        "smscode_country_id": cfg.get("smscode_country_id", "7"),
        "smscode_platform_id": cfg.get("smscode_platform_id", ""),
        "smscode_platform_query": cfg.get("smscode_platform_query", "gojek"),
        "smscode_product_id": cfg.get("smscode_product_id", ""),
        "smscode_min_price": cfg.get("smscode_min_price", ""),
        "smscode_max_price": cfg.get("smscode_max_price", ""),
        "proxy_url": cfg["proxy_url"],
        "proxy_url_present": bool(cfg["proxy_url"]),
        "signup_mode": cfg.get("signup_mode") or "http",
        "appium_url": cfg.get("appium_url") or "http://127.0.0.1:4723",
        "appium_adb_serial": cfg.get("appium_adb_serial") or "",
    }
    if message:
        response["message"] = message
    return response


class GoPayHeroSmsPriceQueryParams(BaseModel):
    hero_sms_api_key: str = Field(
        "",
        validation_alias=AliasChoices("hero_sms_api_key", "heroSmsApiKey", "gopay_auto_signup_hero_sms_api_key"),
    )
    hero_sms_base_url: str = Field(
        "",
        validation_alias=AliasChoices("hero_sms_base_url", "heroSmsBaseUrl", "gopay_auto_signup_hero_sms_base_url"),
    )
    hero_sms_country: str = Field(
        "",
        validation_alias=AliasChoices("hero_sms_country", "heroSmsCountry", "gopay_auto_signup_hero_sms_country"),
    )
    hero_sms_service: str = Field(
        "",
        validation_alias=AliasChoices("hero_sms_service", "heroSmsService", "gopay_auto_signup_hero_sms_service"),
    )
    hero_sms_min_price: str = Field(
        "",
        validation_alias=AliasChoices("hero_sms_min_price", "heroSmsMinPrice", "gopay_auto_signup_hero_sms_min_price"),
    )
    hero_sms_max_price: str = Field(
        "",
        validation_alias=AliasChoices("hero_sms_max_price", "heroSmsMaxPrice", "gopay_auto_signup_hero_sms_max_price"),
    )
    hero_sms_preferred_price: str = Field(
        "",
        validation_alias=AliasChoices(
            "hero_sms_preferred_price",
            "heroSmsPreferredPrice",
            "hero_sms_price_tier",
            "heroSmsPriceTier",
            "gopay_auto_signup_hero_sms_preferred_price",
        ),
    )


class GoPaySmsCodePriceQueryParams(BaseModel):
    smscode_api_token: str = Field(
        "",
        validation_alias=AliasChoices("smscode_api_token", "smscodeApiToken", "gopay_auto_signup_smscode_api_token"),
    )
    smscode_base_url: str = Field(
        "",
        validation_alias=AliasChoices("smscode_base_url", "smscodeBaseUrl", "gopay_auto_signup_smscode_base_url"),
    )
    smscode_country_id: str = Field(
        "",
        validation_alias=AliasChoices("smscode_country_id", "smscodeCountryId", "gopay_auto_signup_smscode_country_id"),
    )
    smscode_platform_id: str = Field(
        "",
        validation_alias=AliasChoices(
            "smscode_platform_id",
            "smscodePlatformId",
            "gopay_auto_signup_smscode_platform_id",
        ),
    )
    smscode_platform_query: str = Field(
        "",
        validation_alias=AliasChoices(
            "smscode_platform_query",
            "smscodePlatformQuery",
            "gopay_auto_signup_smscode_platform_query",
        ),
    )
    smscode_min_price: str = Field(
        "",
        validation_alias=AliasChoices("smscode_min_price", "smscodeMinPrice", "gopay_auto_signup_smscode_min_price"),
    )
    smscode_max_price: str = Field(
        "",
        validation_alias=AliasChoices("smscode_max_price", "smscodeMaxPrice", "gopay_auto_signup_smscode_max_price"),
    )


class GoPaySmsBowerPriceQueryParams(BaseModel):
    smsbower_api_key: str = Field(
        "",
        validation_alias=AliasChoices("smsbower_api_key", "smsbowerApiKey", "gopay_auto_signup_smsbower_api_key"),
    )
    smsbower_base_url: str = Field(
        "",
        validation_alias=AliasChoices("smsbower_base_url", "smsbowerBaseUrl", "gopay_auto_signup_smsbower_base_url"),
    )
    smsbower_country: str = Field(
        "",
        validation_alias=AliasChoices("smsbower_country", "smsbowerCountry", "gopay_auto_signup_smsbower_country"),
    )
    smsbower_service: str = Field(
        "",
        validation_alias=AliasChoices("smsbower_service", "smsbowerService", "gopay_auto_signup_smsbower_service"),
    )
    smsbower_min_price: str = Field(
        "",
        validation_alias=AliasChoices("smsbower_min_price", "smsbowerMinPrice", "gopay_auto_signup_smsbower_min_price"),
    )
    smsbower_max_price: str = Field(
        "",
        validation_alias=AliasChoices("smsbower_max_price", "smsbowerMaxPrice", "gopay_auto_signup_smsbower_max_price"),
    )
    smsbower_preferred_price: str = Field(
        "",
        validation_alias=AliasChoices(
            "smsbower_preferred_price",
            "smsbowerPreferredPrice",
            "smsbower_price_tier",
            "smsbowerPriceTier",
            "gopay_auto_signup_smsbower_preferred_price",
        ),
    )


def create_gopay_auto_signup_config_router(*, mask_secret: Callable[[str], str]) -> APIRouter:
    router = APIRouter()

    @router.get("/api/config/gopay-auto-signup")
    def get_gopay_auto_signup_config():
        return build_gopay_auto_signup_config_response(mask_secret=mask_secret)

    @router.post("/api/config/gopay-auto-signup/hero-sms/prices")
    def query_gopay_hero_sms_prices(params: GoPayHeroSmsPriceQueryParams):
        from autotoken.payments.gopay_auto_register import query_hero_sms_price_tiers

        cfg = gopay_auto_signup_env()
        api_key = str(params.hero_sms_api_key or cfg["hero_sms_api_key"] or "").strip()
        if not api_key:
            raise HTTPException(status_code=400, detail="缺少 hero-sms API Key")
        base_url = str(
            params.hero_sms_base_url
            or cfg.get("hero_sms_base_url")
            or "https://hero-sms.com/stubs/handler_api.php"
        ).strip()
        service = str(params.hero_sms_service or cfg.get("hero_sms_service") or "ni").strip()
        try:
            country = int(float(params.hero_sms_country or cfg.get("hero_sms_country") or "6"))
        except Exception:
            country = 6
        result = query_hero_sms_price_tiers(
            service_code=service,
            country_id=country,
            base_url=base_url,
            api_key=api_key,
            min_price=params.hero_sms_min_price or cfg.get("hero_sms_min_price", ""),
            max_price=params.hero_sms_max_price or cfg.get("hero_sms_max_price", ""),
            preferred_price=params.hero_sms_preferred_price or cfg.get("hero_sms_preferred_price", ""),
        )
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error") or "hero-sms 查询失败")
        result.pop("raw", None)
        return result

    @router.post("/api/config/gopay-auto-signup/smsbower/prices")
    def query_gopay_smsbower_prices(params: GoPaySmsBowerPriceQueryParams):
        from autotoken.payments.gopay_auto_register import query_smsbower_price_tiers

        cfg = gopay_auto_signup_env()
        api_key = str(params.smsbower_api_key or cfg["smsbower_api_key"] or "").strip()
        if not api_key:
            raise HTTPException(status_code=400, detail="缺少 smsbower API Key")
        base_url = str(
            params.smsbower_base_url
            or cfg.get("smsbower_base_url")
            or "https://smsbower.page/stubs/handler_api.php"
        ).strip()
        service = str(params.smsbower_service or cfg.get("smsbower_service") or "ni").strip()
        try:
            country = int(float(params.smsbower_country or cfg.get("smsbower_country") or "6"))
        except Exception:
            country = 6
        result = query_smsbower_price_tiers(
            service_code=service,
            country_id=country,
            base_url=base_url,
            api_key=api_key,
            min_price=params.smsbower_min_price or cfg.get("smsbower_min_price", ""),
            max_price=params.smsbower_max_price or cfg.get("smsbower_max_price", ""),
            preferred_price=params.smsbower_preferred_price or cfg.get("smsbower_preferred_price", ""),
        )
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error") or "smsbower 查询失败")
        result.pop("raw", None)
        return result

    @router.post("/api/config/gopay-auto-signup/smscode/prices")
    def query_gopay_smscode_prices(params: GoPaySmsCodePriceQueryParams):
        from autotoken.payments.gopay_auto_register import query_smscode_products

        cfg = gopay_auto_signup_env()
        api_token = str(params.smscode_api_token or cfg["smscode_api_token"] or "").strip()
        if not api_token:
            raise HTTPException(status_code=400, detail="缺少 SMSCode API Token")
        result = query_smscode_products(
            base_url=str(params.smscode_base_url or cfg.get("smscode_base_url") or "https://api.smscode.gg/v1").strip(),
            api_token=api_token,
            country_id=str(params.smscode_country_id or cfg.get("smscode_country_id") or "7").strip(),
            platform_id=str(params.smscode_platform_id or cfg.get("smscode_platform_id") or "").strip(),
            platform_query=str(params.smscode_platform_query or cfg.get("smscode_platform_query") or "gojek").strip(),
            min_price=params.smscode_min_price or cfg.get("smscode_min_price", ""),
            max_price=params.smscode_max_price or cfg.get("smscode_max_price", ""),
        )
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error") or "SMSCode 查询失败")
        return result

    @router.put("/api/config/gopay-auto-signup")
    async def save_gopay_auto_signup_config(request: Request):
        from autotoken.settings.setup_wizard import _write_env

        data = await request.json()
        provider = normalize_gopay_auto_signup_sms_provider(
            data.get("provider") or data.get("GOPAY_AUTO_SIGNUP_SMS_PROVIDER")
        )
        country_code = str(data.get("country_code") or data.get("GOPAY_AUTO_SIGNUP_COUNTRY_CODE") or "+62").strip() or "+62"
        smscloud_xi_token = str(
            data.get("smscloud_xi_token") or data.get("GOPAY_AUTO_SIGNUP_SMSCLOUD_XI_TOKEN") or ""
        ).strip()
        hero_sms_api_key = str(data.get("hero_sms_api_key") or data.get("GOPAY_AUTO_SIGNUP_HERO_SMS_API_KEY") or "").strip()
        hero_sms_base_url = str(
            data.get("hero_sms_base_url")
            or data.get("GOPAY_AUTO_SIGNUP_HERO_SMS_BASE_URL")
            or "https://hero-sms.com/stubs/handler_api.php"
        ).strip()
        hero_sms_country = str(data.get("hero_sms_country") or data.get("GOPAY_AUTO_SIGNUP_HERO_SMS_COUNTRY") or "6").strip()
        hero_sms_service = str(data.get("hero_sms_service") or data.get("GOPAY_AUTO_SIGNUP_HERO_SMS_SERVICE") or "ni").strip()
        hero_sms_min_price = str(data.get("hero_sms_min_price") or data.get("GOPAY_AUTO_SIGNUP_HERO_SMS_MIN_PRICE") or "").strip()
        hero_sms_max_price = str(data.get("hero_sms_max_price") or data.get("GOPAY_AUTO_SIGNUP_HERO_SMS_MAX_PRICE") or "").strip()
        hero_sms_preferred_price = str(
            data.get("hero_sms_preferred_price") or data.get("GOPAY_AUTO_SIGNUP_HERO_SMS_PREFERRED_PRICE") or ""
        ).strip()
        smsbower_api_key = str(data.get("smsbower_api_key") or data.get("GOPAY_AUTO_SIGNUP_SMSBOWER_API_KEY") or "").strip()
        smsbower_base_url = str(
            data.get("smsbower_base_url")
            or data.get("GOPAY_AUTO_SIGNUP_SMSBOWER_BASE_URL")
            or "https://smsbower.page/stubs/handler_api.php"
        ).strip()
        smsbower_country = str(
            data.get("smsbower_country") or data.get("GOPAY_AUTO_SIGNUP_SMSBOWER_COUNTRY") or "6"
        ).strip()
        smsbower_service = str(
            data.get("smsbower_service") or data.get("GOPAY_AUTO_SIGNUP_SMSBOWER_SERVICE") or "ni"
        ).strip()
        smsbower_min_price = str(
            data.get("smsbower_min_price") or data.get("GOPAY_AUTO_SIGNUP_SMSBOWER_MIN_PRICE") or ""
        ).strip()
        smsbower_max_price = str(
            data.get("smsbower_max_price") or data.get("GOPAY_AUTO_SIGNUP_SMSBOWER_MAX_PRICE") or ""
        ).strip()
        smsbower_preferred_price = str(
            data.get("smsbower_preferred_price") or data.get("GOPAY_AUTO_SIGNUP_SMSBOWER_PREFERRED_PRICE") or ""
        ).strip()
        smscode_api_token = str(
            data.get("smscode_api_token") or data.get("GOPAY_AUTO_SIGNUP_SMSCODE_API_TOKEN") or ""
        ).strip()
        smscode_base_url = str(
            data.get("smscode_base_url")
            or data.get("GOPAY_AUTO_SIGNUP_SMSCODE_BASE_URL")
            or "https://api.smscode.gg/v1"
        ).strip()
        smscode_country_id = str(
            data.get("smscode_country_id") or data.get("GOPAY_AUTO_SIGNUP_SMSCODE_COUNTRY_ID") or "7"
        ).strip()
        smscode_platform_id = str(
            data.get("smscode_platform_id") or data.get("GOPAY_AUTO_SIGNUP_SMSCODE_PLATFORM_ID") or ""
        ).strip()
        smscode_platform_query = str(
            data.get("smscode_platform_query") or data.get("GOPAY_AUTO_SIGNUP_SMSCODE_PLATFORM_QUERY") or "gojek"
        ).strip()
        smscode_product_id = str(
            data.get("smscode_product_id") or data.get("GOPAY_AUTO_SIGNUP_SMSCODE_PRODUCT_ID") or ""
        ).strip()
        smscode_min_price = str(data.get("smscode_min_price") or data.get("GOPAY_AUTO_SIGNUP_SMSCODE_MIN_PRICE") or "").strip()
        smscode_max_price = str(data.get("smscode_max_price") or data.get("GOPAY_AUTO_SIGNUP_SMSCODE_MAX_PRICE") or "").strip()
        proxy_url = str(data.get("proxy_url") or data.get("GOPAY_AUTO_SIGNUP_PROXY_URL") or "").strip()
        signup_mode = normalize_gopay_auto_signup_mode(
            data.get("signup_mode") or data.get("GOPAY_AUTO_SIGNUP_MODE") or "http"
        )
        appium_url = str(data.get("appium_url") or data.get("GOPAY_APPIUM_URL") or "").strip()
        appium_adb_serial = str(data.get("appium_adb_serial") or data.get("GOPAY_APPIUM_ADB_SERIAL") or "").strip()

        updates = {
            "GOPAY_AUTO_SIGNUP_SMS_PROVIDER": provider,
            "GOPAY_AUTO_SIGNUP_COUNTRY_CODE": country_code,
            "GOPAY_AUTO_SIGNUP_PROXY_URL": proxy_url,
            "GOPAY_AUTO_SIGNUP_MODE": signup_mode,
        }
        if smscloud_xi_token:
            updates["GOPAY_AUTO_SIGNUP_SMSCLOUD_XI_TOKEN"] = smscloud_xi_token
        if hero_sms_api_key:
            updates["GOPAY_AUTO_SIGNUP_HERO_SMS_API_KEY"] = hero_sms_api_key
        if smsbower_api_key:
            updates["GOPAY_AUTO_SIGNUP_SMSBOWER_API_KEY"] = smsbower_api_key
        if smscode_api_token:
            updates["GOPAY_AUTO_SIGNUP_SMSCODE_API_TOKEN"] = smscode_api_token
        updates["GOPAY_AUTO_SIGNUP_HERO_SMS_BASE_URL"] = hero_sms_base_url or "https://hero-sms.com/stubs/handler_api.php"
        updates["GOPAY_AUTO_SIGNUP_HERO_SMS_COUNTRY"] = hero_sms_country or "6"
        updates["GOPAY_AUTO_SIGNUP_HERO_SMS_SERVICE"] = hero_sms_service or "ni"
        updates["GOPAY_AUTO_SIGNUP_HERO_SMS_MIN_PRICE"] = hero_sms_min_price
        updates["GOPAY_AUTO_SIGNUP_HERO_SMS_MAX_PRICE"] = hero_sms_max_price
        updates["GOPAY_AUTO_SIGNUP_HERO_SMS_PREFERRED_PRICE"] = hero_sms_preferred_price
        updates["GOPAY_AUTO_SIGNUP_SMSBOWER_BASE_URL"] = smsbower_base_url or "https://smsbower.page/stubs/handler_api.php"
        updates["GOPAY_AUTO_SIGNUP_SMSBOWER_COUNTRY"] = smsbower_country or "6"
        updates["GOPAY_AUTO_SIGNUP_SMSBOWER_SERVICE"] = smsbower_service or "ni"
        updates["GOPAY_AUTO_SIGNUP_SMSBOWER_MIN_PRICE"] = smsbower_min_price
        updates["GOPAY_AUTO_SIGNUP_SMSBOWER_MAX_PRICE"] = smsbower_max_price
        updates["GOPAY_AUTO_SIGNUP_SMSBOWER_PREFERRED_PRICE"] = smsbower_preferred_price
        updates["GOPAY_AUTO_SIGNUP_SMSCODE_BASE_URL"] = smscode_base_url or "https://api.smscode.gg/v1"
        updates["GOPAY_AUTO_SIGNUP_SMSCODE_COUNTRY_ID"] = smscode_country_id or "7"
        updates["GOPAY_AUTO_SIGNUP_SMSCODE_PLATFORM_ID"] = smscode_platform_id
        updates["GOPAY_AUTO_SIGNUP_SMSCODE_PLATFORM_QUERY"] = smscode_platform_query or "gojek"
        updates["GOPAY_AUTO_SIGNUP_SMSCODE_PRODUCT_ID"] = smscode_product_id
        updates["GOPAY_AUTO_SIGNUP_SMSCODE_MIN_PRICE"] = smscode_min_price
        updates["GOPAY_AUTO_SIGNUP_SMSCODE_MAX_PRICE"] = smscode_max_price
        if appium_url:
            updates["GOPAY_APPIUM_URL"] = appium_url
        if appium_adb_serial:
            updates["GOPAY_APPIUM_ADB_SERIAL"] = appium_adb_serial

        for key, value in updates.items():
            _write_env(key, value)
            os.environ[key] = value

        return build_gopay_auto_signup_config_response(
            "GoPay 自动注册配置已保存",
            mask_secret=mask_secret,
            provider=provider,
            country_code=country_code,
        )

    return router
