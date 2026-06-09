"""PayPal task preflight normalization helpers."""

import re
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PROTOCOL_NO_CARD_BROWSERS = {"protocol", "http", "no_card", "no-card", "pure_protocol"}
ROXYBROWSER_BROWSERS = {"roxybrowser", "roxy-browser", "roxy"}
DISABLED_BROWSER_FALLBACKS = {"disabled", "disable", "off", "false", "no", "none", "protocol_only", "protocol-only"}


def normalize_paypal_country(value: Any = "", *, fallback: Any = "US") -> str:
    normalized = re.sub(r"[^A-Za-z]", "", str(value or fallback or "US")).upper()[:2]
    return normalized or "US"


def normalize_paypal_lang(value: Any = "", *, country: str = "US") -> str:
    normalized = re.sub(r"[^A-Za-z-]", "", str(value or "")).lower().split("-", 1)[0]
    if normalized:
        return normalized
    return "ja" if normalize_paypal_country(country) == "JP" else "en"


def normalize_paypal_runner_mode(value: Any) -> str:
    runner_mode = str(value or "").strip().lower()
    if runner_mode and runner_mode != "manual_checkout":
        raise ValueError("不支持的 PayPal 运行模式")
    return runner_mode or "manual_checkout"


def normalize_paypal_mode(value: Any) -> str:
    paypal_mode = str(value or "existing_account").strip().lower()
    if paypal_mode in {"login", "existing", "existing-account"}:
        return "existing_account"
    if paypal_mode in {"signup", "register", "create-account"}:
        return "create_account"
    if paypal_mode in {"existing_account", "create_account"}:
        return paypal_mode
    raise ValueError("paypal_mode 只支持 existing_account 或 create_account")


def normalize_paypal_mode_legacy(value: Any = "") -> str:
    paypal_mode = str(value or "").strip().lower()
    if paypal_mode in {"", "login", "existing", "existing-account"}:
        return "existing_account"
    if paypal_mode in {"signup", "register", "create-account"}:
        return "create_account"
    return paypal_mode


def paypal_stop_before_signup_otp_enabled(value: Any) -> bool:
    raw = str(value or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def normalize_pending_retry_attempts(value: Any, *, default: int = 1, maximum: int = 3) -> int:
    try:
        return max(0, min(maximum, int(value if value is not None else default)))
    except Exception:
        return default


def normalize_paypal_concurrency(value: Any, *, default: int = 1, maximum: int = 3) -> int:
    try:
        return max(1, min(maximum, int(value or default)))
    except Exception:
        return default


def validate_paypal_timeout_seconds(value: Any) -> None:
    if value < 0:
        raise ValueError("超时时间不能为负数")


def normalize_paypal_task_inputs(
    *,
    params: Any,
    normalize_email: Callable[[Any], str],
) -> dict[str, Any]:
    email = normalize_email(getattr(params, "email", ""))
    account_emails = []
    seen_account_emails = set()
    for raw_email in getattr(params, "account_emails", None) or []:
        normalized = normalize_email(raw_email)
        if normalized and normalized not in seen_account_emails:
            seen_account_emails.add(normalized)
            account_emails.append(normalized)

    return {
        "email": email,
        "account_emails": account_emails,
        "checkout_url": str(getattr(params, "checkout_url", "") or "").strip(),
        "sms_url": str(getattr(params, "sms_url", "") or "").strip(),
        "otp_channel": str(getattr(params, "otp_channel", "sms") or "sms").strip().lower() or "sms",
    }


def include_primary_paypal_account_email(account_emails: list[str], email: str) -> list[str]:
    if account_emails and email not in account_emails:
        return [email, *account_emails]
    return list(account_emails)


def resolve_paypal_task_sms_url(
    *,
    sms_url: str,
    manual_confirm: Any,
    paypal_mode: str,
    otp_channel: str,
    default_whatsapp_sms_url: Callable[[], str],
) -> str:
    if not bool(manual_confirm) and paypal_mode == "create_account" and otp_channel == "whatsapp":
        return default_whatsapp_sms_url()
    return sms_url


def resolve_effective_paypal_concurrency(
    *,
    paypal_mode: str,
    phone_account_count: int,
    paypal_concurrency: int,
    paypal_browser: str,
    roxybrowser_profile_id: str,
    roxybrowser_auto_create_profile: bool,
) -> dict[str, Any]:
    effective_paypal_concurrency = paypal_concurrency
    progress_events: list[dict[str, Any]] = []
    if paypal_mode == "create_account":
        safe_phone_concurrency = phone_account_count if phone_account_count else 1
        if effective_paypal_concurrency > safe_phone_concurrency:
            effective_paypal_concurrency = max(1, safe_phone_concurrency)
            progress_events.append(
                {
                    "stage": "paypal_concurrency_limited",
                    "requested_concurrency": paypal_concurrency,
                    "concurrency": effective_paypal_concurrency,
                    "message": "PayPal 自动注册并发已按可独占的手机号数量限制",
                    "level": "warn",
                }
            )
    if (
        paypal_browser == "roxybrowser"
        and roxybrowser_profile_id
        and not roxybrowser_auto_create_profile
        and paypal_concurrency > 1
    ):
        effective_paypal_concurrency = 1
        progress_events.append(
            {
                "stage": "paypal_concurrency_limited",
                "requested_concurrency": paypal_concurrency,
                "concurrency": effective_paypal_concurrency,
                "message": "RoxyBrowser 单 Profile 不能并发复用，PayPal 并发已降为 1",
                "level": "warn",
            }
        )
    return {"concurrency": effective_paypal_concurrency, "progress_events": progress_events}


def paypal_locale_redirect_url(url: str, *, country: Any = "US", lang: Any = "en") -> str:
    try:
        parsed = urlsplit(str(url or ""))
    except Exception:
        return ""
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    normalized_country = normalize_paypal_country(country)
    normalized_lang = normalize_paypal_lang(lang, country=normalized_country)
    locale = f"{normalized_lang}_{normalized_country}"
    changed = False
    if query.get("country.x") != normalized_country:
        query["country.x"] = normalized_country
        changed = True
    if query.get("locale.x") != locale:
        query["locale.x"] = locale
        changed = True
    if not changed:
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def normalize_paypal_runtime_options(
    *,
    paypal_mode: str,
    paypal_browser: Any,
    paypal_fallback_browser: Any,
    paypal_region: Any,
    paypal_country: Any,
    billing_country: Any,
    paypal_lang: Any,
    bind_link_payload: Any,
    roxybrowser_workspace_id: Any,
    roxybrowser_profile_id: Any,
    roxybrowser_auto_create_profile: Any,
    paypal_card_number: Any,
    paypal_card_expiry: Any,
    paypal_card_cvv: Any,
) -> dict[str, Any]:
    payload = bind_link_payload if isinstance(bind_link_payload, dict) else {}
    normalized_browser = str(paypal_browser or "chromium").strip().lower()
    normalized_fallback = str(paypal_fallback_browser or "").strip().lower()
    normalized_region = str(paypal_region or "").strip().upper()
    normalized_country = normalize_paypal_country(paypal_country, fallback=billing_country or "US")

    if normalized_region in {"JP", "JP_NOCARD", "JAPAN_NOCARD"}:
        normalized_country = "JP"
        if normalized_browser in PROTOCOL_NO_CARD_BROWSERS and not normalized_fallback:
            normalized_fallback = "roxybrowser"
        card_values = (paypal_card_number, paypal_card_expiry, paypal_card_cvv)
        if (
            paypal_mode == "create_account"
            and normalized_fallback not in DISABLED_BROWSER_FALLBACKS
            and not any(str(value or "").strip() for value in card_values)
        ):
            normalized_fallback = "roxybrowser"
            normalized_browser = "protocol"
        if payload:
            checkout_billing = dict(payload.get("billing_details") or {})
            checkout_billing["country"] = "US"
            checkout_billing["currency"] = "USD"
            payload = {
                **payload,
                "billing_details": checkout_billing,
                "checkout_ui_mode": "hosted",
            }

    normalized_lang = normalize_paypal_lang(paypal_lang, country=normalized_country)

    protocol_no_card = normalized_browser in PROTOCOL_NO_CARD_BROWSERS
    workspace_id = str(roxybrowser_workspace_id or "").strip()
    profile_id = str(roxybrowser_profile_id or "").strip()
    auto_create_profile = bool(roxybrowser_auto_create_profile)
    if auto_create_profile and (
        normalized_browser in ROXYBROWSER_BROWSERS or normalized_fallback in ROXYBROWSER_BROWSERS
    ):
        profile_id = ""

    return {
        "paypal_browser": normalized_browser,
        "paypal_fallback_browser": normalized_fallback,
        "paypal_region": normalized_region,
        "paypal_country": normalized_country,
        "paypal_lang": normalized_lang,
        "protocol_no_card": protocol_no_card,
        "bind_link_payload": payload,
        "roxybrowser_workspace_id": workspace_id,
        "roxybrowser_profile_id": profile_id,
        "roxybrowser_auto_create_profile": auto_create_profile,
    }


def validate_paypal_task_request(
    *,
    params: Any,
    email: str,
    checkout_url: str,
    bind_link_payload: Any,
    paypal_mode: str,
    otp_channel: str,
    sms_url: str,
    protocol_no_card: bool,
    direct_ba_pre_extracted: Any | None = None,
) -> None:
    if not email:
        raise ValueError("email 不能为空")
    if otp_channel not in {"sms", "whatsapp"}:
        raise ValueError("otp_channel 只支持 sms 或 whatsapp")
    if not checkout_url and not bind_link_payload and not direct_ba_pre_extracted:
        raise ValueError("checkout_url 不能为空，或提供 bind_link_payload 用于自动生成链接")
    if bool(getattr(params, "manual_confirm", False)) and bool(getattr(params, "autofill_enabled", False)):
        raise ValueError("手动确认模式与自动生成账单信息不能同时开启")
    if bool(getattr(params, "manual_confirm", False)):
        return

    if paypal_mode == "existing_account":
        if not str(getattr(params, "paypal_email", "") or "").strip():
            raise ValueError("已有账号模式需要 paypal_email")
        if not str(getattr(params, "paypal_password", "") or "").strip():
            raise ValueError("已有账号模式需要 paypal_password")
        return

    if paypal_mode != "create_account":
        return

    if not str(getattr(params, "billing_phone", "") or "").strip():
        raise ValueError("自动注册模式需要 billing_phone")
    if not sms_url:
        raise ValueError("自动注册模式需要 sms_url")
    if bool(getattr(params, "autofill_enabled", False)):
        return

    required_billing_fields = (
        ("billing_name", "手动账单信息模式需要 billing_name"),
        ("billing_country", "手动账单信息模式需要 billing_country"),
        ("billing_state", "手动账单信息模式需要 billing_state"),
        ("billing_city", "手动账单信息模式需要 billing_city"),
        ("billing_zip", "手动账单信息模式需要 billing_zip"),
        ("billing_address1", "手动账单信息模式需要 billing_address1"),
    )
    for field_name, message in required_billing_fields:
        if not str(getattr(params, field_name, "") or "").strip():
            raise ValueError(message)
    if not protocol_no_card:
        required_card_fields = (
            ("paypal_card_number", "自动注册模式需要 paypal_card_number"),
            ("paypal_card_expiry", "自动注册模式需要 paypal_card_expiry"),
            ("paypal_card_cvv", "自动注册模式需要 paypal_card_cvv"),
        )
        for field_name, message in required_card_fields:
            if not str(getattr(params, field_name, "") or "").strip():
                raise ValueError(message)


def normalize_paypal_bind_task_runtime_options(
    *,
    manual_confirm: Any,
    paypal_mode: Any,
    paypal_browser: Any,
    paypal_fallback_browser: Any,
    paypal_country: Any,
    paypal_lang: Any,
    proxy_url: Any,
    proxy_bypass: Any,
    roxybrowser_workspace_id: Any,
    roxybrowser_profile_id: Any,
    paypal_card_number: Any,
    paypal_card_expiry: Any,
    paypal_card_cvv: Any,
) -> dict[str, Any]:
    normalized_mode = normalize_paypal_mode_legacy(paypal_mode)
    runtime = normalize_paypal_runtime_options(
        paypal_mode=normalized_mode,
        paypal_browser=paypal_browser,
        paypal_fallback_browser=paypal_fallback_browser,
        paypal_region="",
        paypal_country=paypal_country,
        billing_country="",
        paypal_lang=paypal_lang,
        bind_link_payload=None,
        roxybrowser_workspace_id=roxybrowser_workspace_id,
        roxybrowser_profile_id=roxybrowser_profile_id,
        roxybrowser_auto_create_profile=False,
        paypal_card_number=paypal_card_number,
        paypal_card_expiry=paypal_card_expiry,
        paypal_card_cvv=paypal_card_cvv,
    )
    normalized_browser = str(runtime["paypal_browser"] or "chromium").strip().lower()
    normalized_fallback = str(runtime["paypal_fallback_browser"] or "").strip().lower()
    browser_fallback_enabled = normalized_fallback not in DISABLED_BROWSER_FALLBACKS
    return {
        "auto_mode": not bool(manual_confirm),
        "paypal_mode": normalized_mode,
        "paypal_browser": normalized_browser,
        "paypal_fallback_browser": normalized_fallback,
        "paypal_country": runtime["paypal_country"],
        "paypal_lang": runtime["paypal_lang"],
        "protocol_mode": normalized_browser in PROTOCOL_NO_CARD_BROWSERS,
        "use_camoufox": normalized_browser in {"camoufox", "firefox"},
        "use_roxybrowser": normalized_browser in ROXYBROWSER_BROWSERS,
        "browser_fallback_enabled": browser_fallback_enabled,
        "fallback_use_roxybrowser": browser_fallback_enabled and normalized_fallback in ROXYBROWSER_BROWSERS,
        "fallback_use_camoufox": browser_fallback_enabled
        and normalized_fallback
        in {
            "",
            "protocol",
            "http",
            "no_card",
            "no-card",
            "pure_protocol",
            "camoufox",
            "firefox",
        },
        "launch_proxy_url": str(proxy_url or "").strip() or None,
        "launch_proxy_bypass": str(proxy_bypass or "").strip() or None,
        "roxybrowser_workspace_id": runtime["roxybrowser_workspace_id"],
        "roxybrowser_profile_id": runtime["roxybrowser_profile_id"],
    }
