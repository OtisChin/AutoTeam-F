"""Pure HTTP/protocol ChatGPT card checkout executor.

This module is intentionally separate from ``bind_executor`` so the existing
Playwright/RoxyBrowser payment path remains untouched.
"""

from __future__ import annotations

import logging
import os
import random
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from autotoken.payments.bind_executor import (
    _build_result,
    extract_card_payload,
    generate_tax_free_billing_address,
)
from autotoken.payments.gopay_executor import (
    DEFAULT_STRIPE_PK,
    DEFAULT_STRIPE_RUNTIME_VERSION,
    STRIPE_API,
    STRIPE_VERSION_FULL,
    _approve_checkout_http,
    _chatgpt_checkout_headers,
    _checkout_approval_sentinel_headers,
    _configure_chatgpt_http_session,
    _extract_auth_session_context,
    _extract_checkout_session_id,
    _new_http_session,
    _response_json,
    _stripe_js_checksum,
    _stripe_runtime_from_env,
    _stripe_rv_timestamp,
    _verify_checkout_http,
)
from autotoken.services import checkout_response as checkout_response_service
from autotoken.services import payment_checkout_state as payment_checkout_state_service

logger = logging.getLogger(__name__)


class ProtocolCardFlowError(RuntimeError):
    def __init__(self, message: str, *, stage: str = "protocol_card"):
        super().__init__(message)
        self.stage = stage


STRIPE_VERSION_BASE = "2025-03-31.basil"


@dataclass(frozen=True, slots=True)
class ProtocolHttpProfile:
    name: str
    tls_impersonate: str
    user_agent: str
    sec_ch_ua: str
    sec_ch_ua_platform: str
    accept_language: str
    browser_locale: str
    browser_timezone: str


SAFE_PROTOCOL_HTTP_PROFILE = ProtocolHttpProfile(
    name="chrome136-windows-safe",
    tls_impersonate="chrome136",
    user_agent=(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
    ),
    sec_ch_ua='"Google Chrome";v="136", "Chromium";v="136", "Not.A/Brand";v="24"',
    sec_ch_ua_platform='"Windows"',
    accept_language="en-US,en;q=0.9",
    browser_locale="en-US",
    browser_timezone="America/New_York",
)


PROTOCOL_HTTP_PROFILES: tuple[ProtocolHttpProfile, ...] = (
    SAFE_PROTOCOL_HTTP_PROFILE,
    ProtocolHttpProfile(
        name="chrome145-windows",
        tls_impersonate="chrome145",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
        ),
        sec_ch_ua='"Google Chrome";v="145", "Chromium";v="145", "Not.A/Brand";v="24"',
        sec_ch_ua_platform='"Windows"',
        accept_language="en-US,en;q=0.9",
        browser_locale="en-US",
        browser_timezone="America/Chicago",
    ),
    ProtocolHttpProfile(
        name="chrome146-macos",
        tls_impersonate="chrome146",
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
        ),
        sec_ch_ua='"Google Chrome";v="146", "Chromium";v="146", "Not.A/Brand";v="24"',
        sec_ch_ua_platform='"macOS"',
        accept_language="en-US,en;q=0.9",
        browser_locale="en-US",
        browser_timezone="America/Los_Angeles",
    ),
)


def _select_protocol_http_profile() -> ProtocolHttpProfile:
    """Select one coherent HTTP/TLS profile for the whole protocol payment task.

    Default stays conservative: the previously validated curl_cffi impersonation
    remains active unless AUTOTOKEN_PROTOCOL_PROFILE_MODE=random is explicitly set.
    This keeps the already verified payment path stable by default.
    """

    forced = str(os.environ.get("AUTOTOKEN_PROTOCOL_HTTP_PROFILE") or "").strip().lower()
    if forced:
        for profile in PROTOCOL_HTTP_PROFILES:
            if forced in {profile.name.lower(), profile.tls_impersonate.lower()}:
                return profile
        logger.warning("[protocol_card] unknown forced HTTP profile=%s; using safe profile", forced)
        return SAFE_PROTOCOL_HTTP_PROFILE
    mode = str(os.environ.get("AUTOTOKEN_PROTOCOL_PROFILE_MODE") or "safe").strip().lower()
    if mode in {"safe", "stable", "off", "0", "false", "no"}:
        return SAFE_PROTOCOL_HTTP_PROFILE
    return random.choice(PROTOCOL_HTTP_PROFILES)


def _apply_protocol_http_profile(http: Any, profile: ProtocolHttpProfile) -> None:
    headers = {
        "User-Agent": profile.user_agent,
        "Accept-Language": profile.accept_language,
        "sec-ch-ua": profile.sec_ch_ua,
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": profile.sec_ch_ua_platform,
    }
    try:
        http.headers.update(headers)
        http._autotoken_protocol_profile = profile.name  # type: ignore[attr-defined]
    except Exception:
        logger.debug("[protocol_card] apply HTTP profile failed", exc_info=True)


def _new_protocol_http_session(
    proxy_url: str | None,
    *,
    require_curl_cffi: bool,
    profile: ProtocolHttpProfile,
) -> Any:
    try:
        http = _new_http_session(
            proxy_url,
            require_curl_cffi=require_curl_cffi,
            tls_impersonate=profile.tls_impersonate,
        )
    except Exception:
        if profile.tls_impersonate == SAFE_PROTOCOL_HTTP_PROFILE.tls_impersonate:
            raise
        logger.warning(
            "[protocol_card] HTTP session profile=%s failed; falling back to %s",
            profile.name,
            SAFE_PROTOCOL_HTTP_PROFILE.name,
            exc_info=True,
        )
        http = _new_http_session(
            proxy_url,
            require_curl_cffi=require_curl_cffi,
            tls_impersonate=SAFE_PROTOCOL_HTTP_PROFILE.tls_impersonate,
        )
        profile = SAFE_PROTOCOL_HTTP_PROFILE
    _apply_protocol_http_profile(http, profile)
    return http


def _emit(progress_callback: Callable[[dict], Any] | None, stage: str, **payload: Any) -> None:
    if not callable(progress_callback):
        return
    try:
        progress_callback({"stage": stage, **payload})
    except Exception:
        logger.debug("[protocol_card] progress callback failed", exc_info=True)


def _ensure_ok(resp: Any, stage: str) -> dict:
    status_code = int(getattr(resp, "status_code", 0) or 0)
    if 200 <= status_code < 300:
        return _response_json(resp, stage)
    raise ProtocolCardFlowError(
        f"{stage} 失败: HTTP {status_code} {(getattr(resp, 'text', '') or '')[:500]}",
        stage=stage,
    )


def _processor_entity_from_checkout_url(checkout_url: str) -> str:
    matched = re.search(r"/checkout/([^/?#]+)/(?:cs_|oaics_)", str(checkout_url or ""))
    value = str(matched.group(1) if matched else "").strip()
    return value or "openai_llc"


def _extract_protocol_checkout_id(checkout_url: str) -> str:
    matched = re.search(r"(oaics_[A-Za-z0-9_]+)", str(checkout_url or ""))
    if matched:
        return str(matched.group(1) or "").strip()
    return _extract_checkout_session_id(checkout_url)


def _protocol_checkout_url(processor_entity: str, checkout_session_id: str) -> str:
    entity = str(processor_entity or "openai_llc").strip() or "openai_llc"
    return f"https://chatgpt.com/checkout/{entity}/{checkout_session_id}"


def _generate_openai_checkout_with_protocol_session(
    http: Any,
    *,
    payload: dict[str, Any],
    profile: ProtocolHttpProfile,
) -> dict[str, Any]:
    normalized_payload = checkout_response_service.normalize_checkout_payload_for_http(payload)
    normalized_payload.pop("access_token", None)
    normalized_payload.pop("accessToken", None)
    if not normalized_payload:
        raise ProtocolCardFlowError("协议支付自动生成 checkout 缺少 payload", stage="protocol_openai_checkout_create")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://chatgpt.com",
        "Referer": "https://chatgpt.com/",
        "User-Agent": profile.user_agent,
        "Accept-Language": profile.accept_language,
        "sec-ch-ua": profile.sec_ch_ua,
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": profile.sec_ch_ua_platform,
    }
    resp = http.post(
        "https://chatgpt.com/backend-api/payments/checkout",
        json=normalized_payload,
        headers=headers,
        timeout=max(10.0, float(os.environ.get("CHECKOUT_HTTP_TIMEOUT_SECONDS", "30") or 30)),
    )
    raw_text = str(getattr(resp, "text", "") or "")
    if checkout_response_service.looks_like_cloudflare_challenge(raw_text):
        raise ProtocolCardFlowError("协议支付自动生成 checkout 被 Cloudflare challenge 拦截", stage="protocol_openai_checkout_create")
    data = _response_json(resp, "protocol_openai_checkout_create")
    status_code = int(getattr(resp, "status_code", 0) or 0)
    checkout_session_id = str(data.get("checkout_session_id") or "").strip()
    if status_code >= 400 or not checkout_session_id:
        detail = data.get("detail") or data.get("message") or data.get("error") or f"HTTP {status_code or 502}"
        raise ProtocolCardFlowError(f"协议支付自动生成 checkout 失败: {detail}", stage="protocol_openai_checkout_create")
    processor_entity = str(data.get("processor_entity") or "openai_llc").strip() or "openai_llc"
    chatgpt_checkout_url = _protocol_checkout_url(processor_entity, checkout_session_id)
    hosted_checkout_url = checkout_response_service.find_hosted_checkout_url(data)
    return {
        "checkout_session_id": checkout_session_id,
        "processor_entity": processor_entity,
        "chatgpt_checkout_url": chatgpt_checkout_url,
        "hosted_checkout_url": hosted_checkout_url,
        "url": hosted_checkout_url or chatgpt_checkout_url,
    }


def _is_plus_trial_checkout_payload(payload: dict[str, Any] | None) -> bool:
    return str((payload or {}).get("checkout_flow") or "").strip().lower() == "plus_trial"


def _generate_plus_trial_checkout_with_protocol_proxy(
    access_token: str,
    payload: dict[str, Any],
    *,
    proxy_url: str | None,
) -> dict[str, Any]:
    from autotoken.payments.plus_trial import generate_plus_trial_checkout_link

    plus_trial_payload = dict(payload)
    normalized_proxy_url = str(proxy_url or "").strip()
    if normalized_proxy_url:
        plus_trial_payload.setdefault("checkout_proxy", normalized_proxy_url)
        plus_trial_payload.setdefault("update_proxy", normalized_proxy_url)
    return generate_plus_trial_checkout_link(access_token, plus_trial_payload)


def _parse_card_expiry(value: str) -> tuple[str, str]:
    text = str(value or "").strip()
    digits = re.sub(r"\D+", "", text)
    if len(digits) == 6 and digits[:4].startswith("20"):
        month = digits[4:6]
        year = digits[:4]
    elif len(digits) == 6:
        month = digits[:2]
        year = digits[2:6]
    elif len(digits) == 4:
        month = digits[:2]
        year = f"20{digits[2:4]}"
    else:
        parts = re.findall(r"\d+", text)
        if len(parts) >= 2:
            month = parts[0].zfill(2)
            year = parts[1]
            if len(year) == 2:
                year = f"20{year}"
        else:
            raise ProtocolCardFlowError("虚拟卡有效期格式无效", stage="protocol_card_payload")
    month_int = int(month)
    if month_int < 1 or month_int > 12:
        raise ProtocolCardFlowError("虚拟卡有效期月份无效", stage="protocol_card_payload")
    return month.zfill(2), year


def _billing_from_generated_address(card_payload: dict[str, str]) -> dict[str, str]:
    address = generate_tax_free_billing_address()
    return {
        "name": card_payload.get("name") or address.get("name") or "John Doe",
        "email": card_payload.get("email") or "",
        "country": address.get("country") or "US",
        "address1": address.get("address1") or "",
        "city": address.get("city") or "",
        "state": address.get("state") or "",
        "zip": address.get("zip") or "",
        "phone": address.get("phone_number") or "",
    }


def _new_stripe_elements_context() -> dict[str, str]:
    runtime = _stripe_runtime_from_env()
    runtime_version = runtime.get("version") or DEFAULT_STRIPE_RUNTIME_VERSION
    return {
        "runtime_version": runtime_version,
        "client_session_id": str(uuid.uuid4()),
        "elements_session_id": f"elements_session_{uuid.uuid4().hex[:11]}",
        "elements_session_config_id": str(uuid.uuid4()),
        "guid": str(uuid.uuid4()),
        "muid": str(uuid.uuid4()),
        "sid": str(uuid.uuid4()),
        "time_on_page": str(random.randint(25000, 55000)),
    }


def _checkout_amount(payload: dict) -> str:
    total_summary = payload.get("total_summary") if isinstance(payload.get("total_summary"), dict) else {}
    invoice = payload.get("invoice") if isinstance(payload.get("invoice"), dict) else {}
    if total_summary.get("due") is not None:
        return str(total_summary["due"])
    if invoice.get("amount_due") is not None:
        return str(invoice["amount_due"])
    line_items = payload.get("line_items") if isinstance(payload.get("line_items"), list) else []
    if line_items:
        return str(sum(int(item.get("amount") or 0) for item in line_items if isinstance(item, dict)))
    return "0"


def _stripe_init(http: Any, checkout_session_id: str, stripe_pk: str, profile: ProtocolHttpProfile) -> dict:
    stripe_js_id = str(uuid.uuid4())
    elements_session_id = f"elements_session_{uuid.uuid4().hex[:11]}"
    elements_options = {
        "elements_options_client[saved_payment_method][enable_save]": "auto",
        "elements_options_client[saved_payment_method][enable_redisplay]": "auto",
    }
    for version, include_betas in ((STRIPE_VERSION_FULL, True), (STRIPE_VERSION_BASE, False)):
        data = {
            "browser_locale": profile.browser_locale,
            "browser_timezone": profile.browser_timezone,
            "elements_session_client[elements_init_source]": "custom_checkout",
            "elements_session_client[referrer_host]": "chatgpt.com",
            "elements_session_client[stripe_js_id]": stripe_js_id,
            "elements_session_client[locale]": "en-US",
            "elements_session_client[is_aggregation_expected]": "false",
            "_stripe_version": version,
            "key": stripe_pk,
        }
        if include_betas:
            data["elements_session_client[client_betas][0]"] = "custom_checkout_server_updates_1"
            data["elements_session_client[client_betas][1]"] = "custom_checkout_manual_approval_1"
            data.update(elements_options)
        resp = http.post(f"{STRIPE_API}/v1/payment_pages/{checkout_session_id}/init", data=data, timeout=30)
        if int(getattr(resp, "status_code", 0) or 0) == 200:
            payload = _response_json(resp, "protocol_card_init")
            init_checksum = str(payload.get("init_checksum") or "")
            if not init_checksum:
                raise ProtocolCardFlowError(f"Stripe init 未返回 init_checksum: {payload}", stage="protocol_card_init")
            return {
                "raw": payload,
                "init_checksum": init_checksum,
                "stripe_js_id": stripe_js_id,
                "elements_session_id": elements_session_id,
                "elements_session_config_id": str(uuid.uuid4()),
                "elements_options_client": elements_options if include_betas else {},
                "config_id": str(payload.get("config_id") or ""),
                "expected_amount": _checkout_amount(payload),
                "currency": str(payload.get("currency") or "usd").lower(),
                "return_url": str(payload.get("return_url") or ""),
                "stripe_hosted_url": str(payload.get("stripe_hosted_url") or ""),
                "stripe_version": version,
            }
        text = str(getattr(resp, "text", "") or "").lower()
        if int(getattr(resp, "status_code", 0) or 0) == 400 and ("beta" in text or "parameter_unknown" in text):
            continue
        _ensure_ok(resp, "protocol_card_init")
    raise ProtocolCardFlowError("Stripe init 失败: 所有 API 版本均不可用", stage="protocol_card_init")


def _stripe_elements_session(
    http: Any,
    checkout_session_id: str,
    stripe_pk: str,
    init_ctx: dict,
    profile: ProtocolHttpProfile,
) -> None:
    effective_version = init_ctx.get("stripe_version") or STRIPE_VERSION_FULL
    params = {
        "deferred_intent[mode]": "subscription",
        "deferred_intent[amount]": str(int(re.sub(r"\D+", "", str(init_ctx.get("expected_amount") or "0")) or "0")),
        "deferred_intent[currency]": str(init_ctx.get("currency") or "usd").lower(),
        "deferred_intent[setup_future_usage]": "off_session",
        "deferred_intent[payment_method_types][0]": "card",
        "currency": str(init_ctx.get("currency") or "usd").lower(),
        "key": stripe_pk,
        "_stripe_version": effective_version,
        "elements_init_source": "custom_checkout",
        "referrer_host": "chatgpt.com",
        "stripe_js_id": init_ctx["stripe_js_id"],
        "locale": profile.browser_locale,
        "type": "deferred_intent",
        "checkout_session_id": checkout_session_id,
    }
    if "checkout_server_update_beta" in effective_version:
        params["client_betas[0]"] = "custom_checkout_server_updates_1"
        params["client_betas[1]"] = "custom_checkout_manual_approval_1"
    resp = http.get(f"{STRIPE_API}/v1/elements/sessions", params=params, timeout=30)
    if int(getattr(resp, "status_code", 0) or 0) != 200:
        logger.info("[protocol_card] elements/sessions soft-failed: HTTP %s", getattr(resp, "status_code", "?"))
        return
    payload = _response_json(resp, "protocol_card_elements_session")
    if payload.get("session_id") or payload.get("id"):
        init_ctx["elements_session_id"] = str(payload.get("session_id") or payload.get("id") or "")
    if payload.get("config_id"):
        init_ctx["config_id"] = str(payload.get("config_id") or "")
    if payload.get("payment_method_checkout_config_id"):
        init_ctx["payment_method_checkout_config_id"] = str(payload.get("payment_method_checkout_config_id") or "")
    if payload.get("elements_session_config_id"):
        init_ctx["elements_session_config_id"] = str(payload.get("elements_session_config_id") or "")


def _stripe_update_address(
    http: Any,
    checkout_session_id: str,
    stripe_pk: str,
    init_ctx: dict,
    billing: dict[str, str],
    profile: ProtocolHttpProfile,
) -> None:
    effective_version = init_ctx.get("stripe_version") or STRIPE_VERSION_FULL
    base = {
        "elements_session_client[elements_init_source]": "custom_checkout",
        "elements_session_client[referrer_host]": "chatgpt.com",
        "elements_session_client[session_id]": init_ctx.get("elements_session_id") or f"elements_session_{uuid.uuid4().hex[:11]}",
        "elements_session_client[stripe_js_id]": init_ctx.get("stripe_js_id") or str(uuid.uuid4()),
        "elements_session_client[locale]": profile.browser_locale,
        "elements_session_client[is_aggregation_expected]": "false",
        "client_attribution_metadata[merchant_integration_additional_elements][0]": "payment",
        "client_attribution_metadata[merchant_integration_additional_elements][1]": "address",
        "key": stripe_pk,
        "_stripe_version": effective_version,
    }
    if "checkout_server_update_beta" in effective_version:
        base["elements_session_client[client_betas][0]"] = "custom_checkout_server_updates_1"
        base["elements_session_client[client_betas][1]"] = "custom_checkout_manual_approval_1"
    base.update(init_ctx.get("elements_options_client") or {})
    steps = [
        ("country", {"tax_region[country]": billing.get("country") or "US"}),
        ("line1", {"tax_region[line1]": billing.get("address1") or ""}),
        ("city", {"tax_region[city]": billing.get("city") or ""}),
        ("state", {"tax_region[state]": billing.get("state") or ""}),
        ("postal_code", {"tax_region[postal_code]": billing.get("zip") or ""}),
    ]
    accumulated: dict[str, str] = {}
    for _field, fields in steps:
        accumulated.update({key: str(value) for key, value in fields.items() if value})
        data = dict(base)
        data.update(accumulated)
        resp = http.post(f"{STRIPE_API}/v1/payment_pages/{checkout_session_id}", data=data, timeout=30)
        _ensure_ok(resp, "protocol_card_address_update")
        time.sleep(0.1)


def _stripe_create_card_payment_method(
    http: Any,
    checkout_session_id: str,
    stripe_pk: str,
    init_ctx: dict,
    card_payload: dict[str, str],
    billing: dict[str, str],
    email: str,
    profile: ProtocolHttpProfile,
) -> str:
    runtime = _stripe_runtime_from_env()
    runtime_version = runtime.get("version") or DEFAULT_STRIPE_RUNTIME_VERSION
    exp_month, exp_year = _parse_card_expiry(card_payload.get("expiry_date") or "")
    data = {
        "type": "card",
        "card[number]": re.sub(r"\D+", "", str(card_payload.get("card_number") or "")),
        "card[cvc]": re.sub(r"\D+", "", str(card_payload.get("cvv") or "")),
        "card[exp_month]": exp_month,
        "card[exp_year]": exp_year,
        "billing_details[name]": billing.get("name") or "John Doe",
        "billing_details[email]": email or billing.get("email") or "buyer@example.com",
        "billing_details[phone]": billing.get("phone") or "",
        "billing_details[address][country]": billing.get("country") or "US",
        "billing_details[address][line1]": billing.get("address1") or "",
        "billing_details[address][city]": billing.get("city") or "",
        "billing_details[address][postal_code]": billing.get("zip") or "",
        "billing_details[address][state]": billing.get("state") or "",
        "payment_user_agent": f"stripe.js/{runtime_version}; stripe-js-v3/{runtime_version}; payment-element; deferred-intent",
        "referrer": "https://chatgpt.com",
        "time_on_page": str(random.randint(25000, 55000)),
        "client_attribution_metadata[client_session_id]": init_ctx["stripe_js_id"],
        "client_attribution_metadata[checkout_session_id]": checkout_session_id,
        "client_attribution_metadata[checkout_config_id]": init_ctx.get("payment_method_checkout_config_id")
        or init_ctx.get("config_id")
        or "",
        "client_attribution_metadata[elements_session_id]": init_ctx["elements_session_id"],
        "client_attribution_metadata[elements_session_config_id]": init_ctx["elements_session_config_id"],
        "client_attribution_metadata[merchant_integration_source]": "elements",
        "client_attribution_metadata[merchant_integration_subtype]": "payment-element",
        "client_attribution_metadata[merchant_integration_version]": "2021",
        "client_attribution_metadata[payment_intent_creation_flow]": "deferred",
        "client_attribution_metadata[payment_method_selection_flow]": "automatic",
        "client_attribution_metadata[merchant_integration_additional_elements][0]": "payment",
        "client_attribution_metadata[merchant_integration_additional_elements][1]": "address",
        "guid": init_ctx.get("guid") or uuid.uuid4().hex,
        "muid": init_ctx.get("muid") or uuid.uuid4().hex,
        "sid": init_ctx.get("sid") or uuid.uuid4().hex,
        "_stripe_version": init_ctx.get("stripe_version") or STRIPE_VERSION_FULL,
        "key": stripe_pk,
    }
    resp = http.post(f"{STRIPE_API}/v1/payment_methods", data=data, timeout=30)
    payload = _ensure_ok(resp, "protocol_card_payment_method")
    payment_method_id = str(payload.get("id") or "")
    if not payment_method_id.startswith("pm_"):
        raise ProtocolCardFlowError(f"Stripe payment_method 返回异常: {payload}", stage="protocol_card_payment_method")
    return payment_method_id


def _confirm_requires_approval(payload: dict) -> bool:
    candidates = []
    for key in ("submission_attempt", "session"):
        obj = payload.get(key)
        if isinstance(obj, dict):
            candidates.append(obj)
            nested = obj.get("submission_attempt")
            if isinstance(nested, dict):
                candidates.append(nested)
    payment_page = payload.get("payment_page") if isinstance(payload.get("payment_page"), dict) else {}
    session = payment_page.get("session") if isinstance(payment_page.get("session"), dict) else {}
    if session:
        candidates.append(session)
        nested = session.get("submission_attempt")
        if isinstance(nested, dict):
            candidates.append(nested)
    return any(str(candidate.get("state") or "").strip().lower() == "requires_approval" for candidate in candidates)


def _stripe_confirm_card(
    http: Any,
    checkout_session_id: str,
    stripe_pk: str,
    init_ctx: dict,
    payment_method_id: str,
    processor_entity: str,
    profile: ProtocolHttpProfile,
) -> dict:
    runtime = _stripe_runtime_from_env()
    chatgpt_return = (
        f"https://chatgpt.com/checkout/verify?stripe_session_id={checkout_session_id}"
        f"&processor_entity={processor_entity}&plan_type=plus"
    )
    return_url = (
        f"https://checkout.stripe.com/c/pay/{checkout_session_id}"
        f"?returned_from_redirect=true&ui_mode=custom&return_url={quote(chatgpt_return, safe='')}"
    )
    if init_ctx.get("stripe_hosted_url") and init_ctx.get("return_url"):
        return_url = (
            f"{init_ctx['stripe_hosted_url']}?returned_from_redirect=true"
            f"&ui_mode=custom&return_url={quote(str(init_ctx['return_url']), safe='')}"
        )
    elif init_ctx.get("return_url"):
        return_url = str(init_ctx["return_url"])
    data = {
        "guid": uuid.uuid4().hex,
        "muid": uuid.uuid4().hex,
        "sid": uuid.uuid4().hex,
        "payment_method": payment_method_id,
        "init_checksum": init_ctx["init_checksum"],
        "version": runtime.get("version") or DEFAULT_STRIPE_RUNTIME_VERSION,
        "expected_amount": init_ctx.get("expected_amount") or "0",
        "expected_payment_method_type": "card",
        "return_url": return_url,
        "elements_session_client[elements_init_source]": "custom_checkout",
        "elements_session_client[referrer_host]": "chatgpt.com",
        "elements_session_client[stripe_js_id]": init_ctx["stripe_js_id"],
        "elements_session_client[locale]": profile.browser_locale,
        "elements_session_client[is_aggregation_expected]": "false",
        "elements_session_client[session_id]": init_ctx["elements_session_id"],
        "client_attribution_metadata[client_session_id]": init_ctx["stripe_js_id"],
        "client_attribution_metadata[checkout_session_id]": checkout_session_id,
        "client_attribution_metadata[checkout_config_id]": init_ctx.get("config_id", ""),
        "client_attribution_metadata[elements_session_id]": init_ctx["elements_session_id"],
        "client_attribution_metadata[elements_session_config_id]": init_ctx["elements_session_config_id"],
        "client_attribution_metadata[merchant_integration_source]": "checkout",
        "client_attribution_metadata[merchant_integration_subtype]": "payment-element",
        "client_attribution_metadata[merchant_integration_version]": "custom",
        "client_attribution_metadata[payment_intent_creation_flow]": "deferred",
        "client_attribution_metadata[payment_method_selection_flow]": "automatic",
        "client_attribution_metadata[merchant_integration_additional_elements][0]": "payment",
        "client_attribution_metadata[merchant_integration_additional_elements][1]": "address",
        "consent[terms_of_service]": "accepted",
        "_stripe_version": init_ctx.get("stripe_version") or STRIPE_VERSION_FULL,
        "key": stripe_pk,
        "js_checksum": runtime.get("js_checksum") or _stripe_js_checksum(payment_method_id),
        "rv_timestamp": runtime.get("rv_timestamp") or _stripe_rv_timestamp(),
    }
    if "checkout_server_update_beta" in str(data["_stripe_version"]):
        data["elements_session_client[client_betas][0]"] = "custom_checkout_server_updates_1"
        data["elements_session_client[client_betas][1]"] = "custom_checkout_manual_approval_1"
    data.update(init_ctx.get("elements_options_client") or {})
    resp = http.post(f"{STRIPE_API}/v1/payment_pages/{checkout_session_id}/confirm", data=data, timeout=30)
    return _ensure_ok(resp, "protocol_card_confirm")


def _openai_checkout_update_taxes(
    chatgpt_http: Any,
    *,
    checkout_session_id: str,
    processor_entity: str,
    email: str,
    billing: dict[str, str],
    currency: str = "php",
) -> dict:
    body = {
        "checkout_session_id": checkout_session_id,
        "checkout_email": email or billing.get("email") or "",
        "billing_country": billing.get("country") or "US",
        "billing_name": billing.get("name") or "John Doe",
        "currency": str(currency or "php").lower(),
        "tax_id": None,
        "processor_entity": processor_entity,
        "billing_address": {
            "country": billing.get("country") or "US",
            "line1": billing.get("address1") or "",
            "city": billing.get("city") or "",
            "state": billing.get("state") or "",
            "postal_code": billing.get("zip") or "",
        },
    }
    resp = chatgpt_http.post(
        "https://chatgpt.com/backend-api/payments/checkout/taxes",
        json=body,
        headers={
            "x-openai-target-path": "/backend-api/payments/checkout/taxes",
            "x-openai-target-route": "/backend-api/payments/checkout/taxes",
        },
        timeout=60,
    )
    return _ensure_ok(resp, "protocol_openai_taxes")


def _openai_checkout_currency(taxes_payload: dict, fallback: str = "php") -> str:
    candidates: list[Any] = []
    for key in ("checkout_session", "checkout_state", "session"):
        value = taxes_payload.get(key)
        if isinstance(value, dict):
            candidates.extend([value.get("currency"), value.get("presentment_currency")])
    candidates.extend([taxes_payload.get("currency"), fallback])
    for candidate in candidates:
        currency = str(candidate or "").strip().lower()
        if currency:
            return currency
    return "php"


def _stripe_create_confirmation_token(
    http: Any,
    stripe_pk: str,
    card_payload: dict[str, str],
    billing: dict[str, str],
    email: str,
    *,
    currency: str = "php",
    customer_id: str = "",
    elements_context: dict[str, str] | None = None,
) -> str:
    elements_context = elements_context or _new_stripe_elements_context()
    runtime_version = elements_context.get("runtime_version") or DEFAULT_STRIPE_RUNTIME_VERSION
    exp_month, exp_year = _parse_card_expiry(card_payload.get("expiry_date") or "")
    exp_year_short = exp_year[-2:] if len(exp_year) == 4 and exp_year.startswith("20") else exp_year
    client_session_id = elements_context.get("client_session_id") or str(uuid.uuid4())
    elements_session_id = elements_context.get("elements_session_id") or f"elements_session_{uuid.uuid4().hex[:11]}"
    elements_session_config_id = elements_context.get("elements_session_config_id") or str(uuid.uuid4())
    data = {
        "payment_method_data[type]": "card",
        "payment_method_data[card][number]": re.sub(r"\D+", "", str(card_payload.get("card_number") or "")),
        "payment_method_data[card][cvc]": re.sub(r"\D+", "", str(card_payload.get("cvv") or "")),
        "payment_method_data[card][exp_month]": exp_month,
        "payment_method_data[card][exp_year]": exp_year_short,
        "payment_method_data[billing_details][name]": billing.get("name") or "John Doe",
        "payment_method_data[billing_details][phone]": billing.get("phone") or "",
        "payment_method_data[billing_details][address][country]": billing.get("country") or "US",
        "payment_method_data[billing_details][address][line1]": billing.get("address1") or "",
        "payment_method_data[billing_details][address][city]": billing.get("city") or "",
        "payment_method_data[billing_details][address][state]": billing.get("state") or "",
        "payment_method_data[billing_details][address][postal_code]": billing.get("zip") or "",
        "payment_method_data[allow_redisplay]": "limited",
        "payment_method_data[payment_user_agent]": f"stripe.js/{runtime_version}; stripe-js-v3/{runtime_version}; payment-element; deferred-intent",
        "payment_method_data[referrer]": "https://chatgpt.com",
        "payment_method_data[time_on_page]": elements_context.get("time_on_page") or str(random.randint(25000, 55000)),
        "payment_method_data[client_attribution_metadata][client_session_id]": client_session_id,
        "payment_method_data[client_attribution_metadata][merchant_integration_source]": "elements",
        "payment_method_data[client_attribution_metadata][merchant_integration_subtype]": "payment-element",
        "payment_method_data[client_attribution_metadata][merchant_integration_version]": "2021",
        "payment_method_data[client_attribution_metadata][payment_intent_creation_flow]": "deferred",
        "payment_method_data[client_attribution_metadata][payment_method_selection_flow]": "merchant_specified",
        "payment_method_data[client_attribution_metadata][elements_session_id]": elements_session_id,
        "payment_method_data[client_attribution_metadata][elements_session_config_id]": elements_session_config_id,
        "payment_method_data[client_attribution_metadata][merchant_integration_additional_elements][0]": "expressCheckout",
        "payment_method_data[client_attribution_metadata][merchant_integration_additional_elements][1]": "payment",
        "payment_method_data[client_attribution_metadata][merchant_integration_additional_elements][2]": "address",
        "payment_method_data[guid]": elements_context.get("guid") or str(uuid.uuid4()),
        "payment_method_data[muid]": elements_context.get("muid") or str(uuid.uuid4()),
        "payment_method_data[sid]": elements_context.get("sid") or str(uuid.uuid4()),
        "setup_future_usage": "off_session",
        "client_context[currency]": str(currency or "php").lower(),
        "client_context[mode]": "subscription",
        "client_context[payment_method_types][0]": "card",
        "client_context[payment_method_types][1]": "link",
        "client_attribution_metadata[client_session_id]": client_session_id,
        "client_attribution_metadata[merchant_integration_source]": "elements",
        "client_attribution_metadata[merchant_integration_subtype]": "payment-element",
        "client_attribution_metadata[merchant_integration_version]": "2021",
        "client_attribution_metadata[payment_intent_creation_flow]": "deferred",
        "client_attribution_metadata[payment_method_selection_flow]": "merchant_specified",
        "client_attribution_metadata[elements_session_id]": elements_session_id,
        "client_attribution_metadata[elements_session_config_id]": elements_session_config_id,
        "client_attribution_metadata[merchant_integration_additional_elements][0]": "expressCheckout",
        "client_attribution_metadata[merchant_integration_additional_elements][1]": "payment",
        "client_attribution_metadata[merchant_integration_additional_elements][2]": "address",
        "set_as_default_payment_method": "false",
        "key": stripe_pk,
        "_stripe_version": STRIPE_VERSION_FULL,
    }
    if customer_id:
        data["client_context[customer]"] = customer_id
    resp = http.post(
        f"{STRIPE_API}/v1/confirmation_tokens",
        data=data,
        headers={"Accept": "application/json", "Origin": "https://js.stripe.com", "Referer": "https://js.stripe.com/"},
        timeout=30,
    )
    payload = _ensure_ok(resp, "protocol_openai_confirmation_token")
    confirmation_token_id = str(payload.get("id") or "")
    if not confirmation_token_id.startswith("ctoken_"):
        raise ProtocolCardFlowError(
            f"Stripe confirmation_token 返回异常: {payload}",
            stage="protocol_openai_confirmation_token",
        )
    return confirmation_token_id


def _openai_checkout_confirm(
    chatgpt_http: Any,
    *,
    access_token: str,
    checkout_session_id: str,
    processor_entity: str,
    confirmation_token_id: str,
    cookie_header: str = "",
    account_id: str = "",
    device_id: str = "",
    profile: ProtocolHttpProfile,
) -> dict:
    headers = _chatgpt_checkout_headers(
        access_token=access_token,
        checkout_session_id=checkout_session_id,
        processor_entity=processor_entity,
        cookie_header=cookie_header,
        account_id=account_id,
        device_id=device_id,
        target_path="/backend-api/payments/checkout/confirm",
        openai_sentinel_token="",
        sec_ch_ua=profile.sec_ch_ua,
        sec_ch_ua_platform=profile.sec_ch_ua_platform,
    )
    sentinel_headers = _checkout_approval_sentinel_headers(
        cookie_header=headers.get("cookie", ""),
        user_agent=profile.user_agent,
        checkout_url=f"https://chatgpt.com/checkout/{processor_entity}/{checkout_session_id}",
    )
    headers.update(sentinel_headers)
    headers.pop("openai-sentinel-token", None)
    headers["user-agent"] = profile.user_agent
    resp = chatgpt_http.post(
        "https://chatgpt.com/backend-api/payments/checkout/confirm",
        json={
            "checkout_session_id": checkout_session_id,
            "confirm_token": confirmation_token_id,
            "selected_payment_method_type": "card",
        },
        headers=headers,
        timeout=90,
    )
    return _ensure_ok(resp, "protocol_openai_confirm")


def _stripe_confirm_payment_intent(
    http: Any,
    stripe_pk: str,
    *,
    client_secret: str,
    checkout_session_id: str,
    processor_entity: str,
    card_payload: dict[str, str],
    billing: dict[str, str],
    email: str,
    currency: str,
    customer_id: str = "",
    plan_type: str = "plus",
    elements_context: dict[str, str] | None = None,
) -> dict:
    """Confirm the PaymentIntent that OpenAI creates after checkout/confirm.

    The hosted checkout performs this extra Stripe call after the OpenAI
    ``/checkout/confirm`` response returns a ``client_secret``.  Treat 402 as a
    valid card-decline response and let the caller retrieve the PI afterward so
    the final result is based on Stripe's canonical PaymentIntent state.
    """

    payment_intent_id = _payment_intent_id_from_client_secret(client_secret)
    if not payment_intent_id:
        raise ProtocolCardFlowError("OpenAI confirm 未返回有效 payment_intent client_secret", stage="protocol_card_payment_intent_confirm")
    elements_context = elements_context or _new_stripe_elements_context()
    runtime_version = elements_context.get("runtime_version") or DEFAULT_STRIPE_RUNTIME_VERSION
    exp_month, exp_year = _parse_card_expiry(card_payload.get("expiry_date") or "")
    exp_year_short = exp_year[-2:] if len(exp_year) == 4 and exp_year.startswith("20") else exp_year
    client_session_id = elements_context.get("client_session_id") or str(uuid.uuid4())
    elements_session_id = elements_context.get("elements_session_id") or f"elements_session_{uuid.uuid4().hex[:11]}"
    elements_session_config_id = elements_context.get("elements_session_config_id") or str(uuid.uuid4())
    lower_currency = str(currency or "php").lower()
    return_url = (
        "https://chatgpt.com/checkout/verify"
        f"?stripe_session_id={quote(checkout_session_id)}"
        f"&processor_entity={quote(processor_entity)}"
        f"&plan_type={quote(plan_type or 'plus')}"
    )
    data = {
        "return_url": return_url,
        "payment_method_data[type]": "card",
        "payment_method_data[card][number]": re.sub(r"\D+", "", str(card_payload.get("card_number") or "")),
        "payment_method_data[card][cvc]": re.sub(r"\D+", "", str(card_payload.get("cvv") or "")),
        "payment_method_data[card][exp_month]": exp_month,
        "payment_method_data[card][exp_year]": exp_year_short,
        "payment_method_data[billing_details][name]": billing.get("name") or "John Doe",
        "payment_method_data[billing_details][phone]": billing.get("phone") or "",
        "payment_method_data[billing_details][address][country]": billing.get("country") or "US",
        "payment_method_data[billing_details][address][line1]": billing.get("address1") or "",
        "payment_method_data[billing_details][address][city]": billing.get("city") or "",
        "payment_method_data[billing_details][address][state]": billing.get("state") or "",
        "payment_method_data[billing_details][address][postal_code]": billing.get("zip") or "",
        "payment_method_data[allow_redisplay]": "limited",
        "payment_method_data[payment_user_agent]": f"stripe.js/{runtime_version}; stripe-js-v3/{runtime_version}; payment-element; deferred-intent",
        "payment_method_data[referrer]": "https://chatgpt.com",
        "payment_method_data[time_on_page]": elements_context.get("time_on_page") or str(random.randint(25000, 55000)),
        "payment_method_data[client_attribution_metadata][client_session_id]": client_session_id,
        "payment_method_data[client_attribution_metadata][merchant_integration_source]": "elements",
        "payment_method_data[client_attribution_metadata][merchant_integration_subtype]": "payment-element",
        "payment_method_data[client_attribution_metadata][merchant_integration_version]": "2021",
        "payment_method_data[client_attribution_metadata][payment_intent_creation_flow]": "deferred",
        "payment_method_data[client_attribution_metadata][payment_method_selection_flow]": "merchant_specified",
        "payment_method_data[client_attribution_metadata][elements_session_id]": elements_session_id,
        "payment_method_data[client_attribution_metadata][elements_session_config_id]": elements_session_config_id,
        "payment_method_data[client_attribution_metadata][merchant_integration_additional_elements][0]": "expressCheckout",
        "payment_method_data[client_attribution_metadata][merchant_integration_additional_elements][1]": "payment",
        "payment_method_data[client_attribution_metadata][merchant_integration_additional_elements][2]": "address",
        "payment_method_data[guid]": elements_context.get("guid") or str(uuid.uuid4()),
        "payment_method_data[muid]": elements_context.get("muid") or str(uuid.uuid4()),
        "payment_method_data[sid]": elements_context.get("sid") or str(uuid.uuid4()),
        "expected_payment_method_type": "card",
        "client_context[currency]": lower_currency,
        "client_context[mode]": "subscription",
        "client_context[payment_method_types][0]": "link",
        "client_context[payment_method_types][1]": "card",
        "client_context[setup_future_usage]": "off_session",
        "set_as_default_payment_method": "false",
        "use_stripe_sdk": "true",
        "key": stripe_pk,
        "_stripe_version": STRIPE_VERSION_FULL,
        "client_attribution_metadata[client_session_id]": client_session_id,
        "client_attribution_metadata[merchant_integration_source]": "elements",
        "client_attribution_metadata[merchant_integration_subtype]": "payment-element",
        "client_attribution_metadata[merchant_integration_version]": "2021",
        "client_attribution_metadata[payment_intent_creation_flow]": "deferred",
        "client_attribution_metadata[payment_method_selection_flow]": "merchant_specified",
        "client_attribution_metadata[elements_session_id]": elements_session_id,
        "client_attribution_metadata[elements_session_config_id]": elements_session_config_id,
        "client_attribution_metadata[merchant_integration_additional_elements][0]": "expressCheckout",
        "client_attribution_metadata[merchant_integration_additional_elements][1]": "payment",
        "client_attribution_metadata[merchant_integration_additional_elements][2]": "address",
        "client_secret": client_secret,
    }
    if customer_id:
        data["client_context[customer]"] = customer_id
    resp = http.post(
        f"{STRIPE_API}/v1/payment_intents/{payment_intent_id}/confirm",
        data=data,
        headers={"Accept": "application/json", "Origin": "https://js.stripe.com", "Referer": "https://js.stripe.com/"},
        timeout=60,
    )
    try:
        payload = _response_json(resp, "protocol_card_payment_intent_confirm")
    except Exception:
        payload = {"raw": str(getattr(resp, "text", "") or "")[:500]}
    payload["_http_status"] = int(getattr(resp, "status_code", 0) or 0)
    payload.setdefault("id", payment_intent_id)
    return payload


def _payment_intent_confirm_summary(confirm_payload: dict) -> dict[str, Any]:
    payload = confirm_payload if isinstance(confirm_payload, dict) else {}
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    summary: dict[str, Any] = {
        "http_status": int(payload.get("_http_status") or 0),
        "status": str(payload.get("status") or "").strip(),
    }
    if error:
        summary["error"] = {
            "code": str(error.get("code") or "").strip(),
            "decline_code": str(error.get("decline_code") or "").strip(),
            "message": str(error.get("message") or "").strip(),
            "type": str(error.get("type") or "").strip(),
        }
    return summary


def _openai_confirm_summary(confirm_payload: dict) -> dict[str, Any]:
    payload = confirm_payload if isinstance(confirm_payload, dict) else {}
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    summary: dict[str, Any] = {
        "status": str(payload.get("status") or payload.get("result") or "").strip(),
        "client_secret_present": bool(str(payload.get("client_secret") or "").strip()),
    }
    if error:
        summary["error"] = {
            "code": str(error.get("code") or "").strip(),
            "message": str(error.get("message") or "").strip(),
            "type": str(error.get("type") or "").strip(),
        }
    return summary


def _find_nested_string(payload: Any, key: str) -> str:
    target = str(key or "")
    if not target:
        return ""
    stack = [payload]
    seen = 0
    while stack and seen < 500:
        seen += 1
        current = stack.pop()
        if isinstance(current, dict):
            value = current.get(target)
            if isinstance(value, str) and value.strip():
                return value.strip()
            for nested in current.values():
                if isinstance(nested, (dict, list)):
                    stack.append(nested)
        elif isinstance(current, list):
            for nested in current:
                if isinstance(nested, (dict, list)):
                    stack.append(nested)
    return ""


def _payment_intent_id_from_client_secret(client_secret: str) -> str:
    value = str(client_secret or "").strip()
    if not value:
        return ""
    if "_secret_" in value:
        value = value.split("_secret_", 1)[0]
    return value if value.startswith("pi_") else ""


def _wait_stripe_payment_intent(http: Any, stripe_pk: str, client_secret: str, *, attempts: int = 3) -> dict:
    payment_intent_id = _payment_intent_id_from_client_secret(client_secret)
    if not payment_intent_id:
        return {}
    last_payload: dict[str, Any] = {}
    for attempt in range(max(1, int(attempts or 1))):
        resp = http.get(
            f"{STRIPE_API}/v1/payment_intents/{payment_intent_id}",
            params={"client_secret": client_secret, "key": stripe_pk},
            headers={"Accept": "application/json", "Origin": "https://js.stripe.com", "Referer": "https://js.stripe.com/"},
            timeout=30,
        )
        payload = _response_json(resp, "protocol_card_payment_intent")
        if isinstance(payload, dict):
            last_payload = payload
            status = str(payload.get("status") or "").strip()
            if status and status not in {"processing", "requires_confirmation"}:
                return payload
        if attempt < max(1, int(attempts or 1)) - 1:
            time.sleep(1)
    return last_payload


def _payment_intent_next_action_summary(payment_intent: dict) -> dict[str, Any]:
    next_action = payment_intent.get("next_action") if isinstance(payment_intent, dict) else {}
    return next_action if isinstance(next_action, dict) else {}


def _payment_intent_success_result(payment_intent: dict) -> tuple[bool, str]:
    status = str(payment_intent.get("status") or "").strip() if isinstance(payment_intent, dict) else ""
    if status == "succeeded":
        return True, "PaymentIntent succeeded"
    reason = _payment_intent_failure_reason(payment_intent if isinstance(payment_intent, dict) else {})
    parts = [f"PaymentIntent status: {status or 'unknown'}"]
    for key in ("code", "decline_code", "message", "outcome_reason", "network_status"):
        value = str(reason.get(key) or "").strip()
        if value:
            parts.append(f"{key}: {value}")
    next_action = _payment_intent_next_action_summary(payment_intent if isinstance(payment_intent, dict) else {})
    action_type = str(next_action.get("type") or "").strip()
    if action_type:
        parts.append(f"next_action: {action_type}")
    return False, "；".join(parts)


def _payment_intent_failure_reason(payment_intent: dict) -> dict[str, str]:
    data = payment_intent if isinstance(payment_intent, dict) else {}
    last_error = data.get("last_payment_error") if isinstance(data.get("last_payment_error"), dict) else {}
    latest_charge = data.get("latest_charge") if isinstance(data.get("latest_charge"), dict) else {}
    outcome = latest_charge.get("outcome") if isinstance(latest_charge.get("outcome"), dict) else {}
    failure_message = str(latest_charge.get("failure_message") or "").strip()
    failure_code = str(latest_charge.get("failure_code") or "").strip()
    reason = {
        "code": str(last_error.get("code") or failure_code or "").strip(),
        "decline_code": str(last_error.get("decline_code") or "").strip(),
        "message": str(
            last_error.get("message")
            or failure_message
            or outcome.get("seller_message")
            or outcome.get("network_status")
            or ""
        ).strip(),
        "type": str(last_error.get("type") or outcome.get("type") or "").strip(),
        "outcome_reason": str(outcome.get("reason") or "").strip(),
        "charge_status": str(latest_charge.get("status") or "").strip(),
        "network_status": str(outcome.get("network_status") or "").strip(),
        "risk_level": str(outcome.get("risk_level") or "").strip(),
        "cancellation_reason": str(data.get("cancellation_reason") or "").strip(),
    }
    return reason


def run_protocol_card_bind_task(
    *,
    email: str = "",
    card_item: dict,
    checkout_url: str = "",
    checkout_payload: dict[str, Any] | None = None,
    proxy_url: str | None = None,
    proxy_bypass: str | None = None,
    timeout_seconds: int = 900,
    is_cancelled: Callable[[], bool] | None = None,
    progress_callback: Callable[[dict], Any] | None = None,
) -> dict[str, Any]:
    """Run card binding without browser automation.

    Full Stripe protocol implementation is added behind this stable entrypoint;
    the route can now safely dispatch without modifying the Playwright path.
    """

    del proxy_bypass  # HTTP protocol path uses one normalized proxy URL only.
    checkout_url = str(checkout_url or "").strip()
    try:
        if callable(is_cancelled) and is_cancelled():
            return _build_result("failed", failure_stage="protocol_card_cancelled", message="任务已取消")
        auth_context = _extract_auth_session_context(email)
        access_token = str(auth_context.get("access_token") or "").strip()
        session_token = str(auth_context.get("session_token") or "").strip()
        cookie_header = str(auth_context.get("cookie_header") or "").strip()
        account_id = str(auth_context.get("account_id") or "").strip()
        device_id = str(auth_context.get("device_id") or "").strip()
        if not (access_token or session_token or cookie_header):
            return _build_result(
                "failed",
                failure_stage="protocol_chatgpt_auth",
                message=f"所选账号缺少可用 ChatGPT access_token/session: {email}",
            )

        card_payload = extract_card_payload(card_item)
        billing = _billing_from_generated_address(card_payload)
        profile = _select_protocol_http_profile()
        _emit(
            progress_callback,
            "protocol_card_http_profile",
            profile=profile.name,
            tls_impersonate=profile.tls_impersonate,
            locale=profile.browser_locale,
        )
        chatgpt_http = _new_protocol_http_session(proxy_url, require_curl_cffi=True, profile=profile)
        _configure_chatgpt_http_session(
            chatgpt_http,
            access_token=access_token,
            session_token=session_token,
            cookie_header=cookie_header,
            account_id=account_id,
            device_id=device_id,
            user_agent=str(auth_context.get("user_agent") or auth_context.get("userAgent") or "").strip(),
            accept_language=profile.accept_language,
            sec_ch_ua=profile.sec_ch_ua,
            sec_ch_ua_platform=profile.sec_ch_ua_platform,
        )
        _apply_protocol_http_profile(chatgpt_http, profile)
        stripe_http = _new_protocol_http_session(proxy_url, require_curl_cffi=True, profile=profile)

        checkout_generated: dict[str, Any] = {}
        if not checkout_url and isinstance(checkout_payload, dict) and checkout_payload:
            if _is_plus_trial_checkout_payload(checkout_payload):
                _emit(
                    progress_callback,
                    "protocol_plus_trial_checkout_create",
                    plan_name=str(checkout_payload.get("plan_name") or ""),
                )
                checkout_generated = _generate_plus_trial_checkout_with_protocol_proxy(
                    access_token,
                    checkout_payload,
                    proxy_url=proxy_url,
                )
            else:
                _emit(progress_callback, "protocol_openai_checkout_create", plan_name=str(checkout_payload.get("plan_name") or ""))
                checkout_generated = _generate_openai_checkout_with_protocol_session(
                    chatgpt_http,
                    payload=checkout_payload,
                    profile=profile,
                )
            checkout_url = str(checkout_generated.get("chatgpt_checkout_url") or checkout_generated.get("url") or "").strip()

        checkout_session_id = _extract_protocol_checkout_id(checkout_url)
        if not checkout_session_id:
            return _build_result("failed", failure_stage="protocol_checkout_session", message="未能从 checkout 链接提取 session id")
        processor_entity = (
            str(checkout_generated.get("processor_entity") or "").strip()
            if checkout_generated
            else ""
        ) or _processor_entity_from_checkout_url(checkout_url)

        if checkout_session_id.startswith("oaics_"):
            _emit(progress_callback, "protocol_openai_taxes", checkout_session_id=checkout_session_id)
            taxes_payload = _openai_checkout_update_taxes(
                chatgpt_http,
                checkout_session_id=checkout_session_id,
                processor_entity=processor_entity,
                email=email,
                billing=billing,
                currency="php",
            )
            checkout_currency = _openai_checkout_currency(taxes_payload, "php")
            customer_id = _find_nested_string(taxes_payload, "customer")
            elements_context = _new_stripe_elements_context()
            _emit(progress_callback, "protocol_openai_confirmation_token", checkout_session_id=checkout_session_id)
            confirmation_token_id = _stripe_create_confirmation_token(
                stripe_http,
                DEFAULT_STRIPE_PK,
                card_payload,
                billing,
                email,
                currency=checkout_currency,
                customer_id=customer_id,
                elements_context=elements_context,
            )
            _emit(progress_callback, "protocol_openai_confirm", confirmation_token_id=confirmation_token_id)
            confirm_payload = _openai_checkout_confirm(
                chatgpt_http,
                access_token=access_token,
                checkout_session_id=checkout_session_id,
                processor_entity=processor_entity,
                confirmation_token_id=confirmation_token_id,
                cookie_header=cookie_header,
                account_id=account_id,
                device_id=device_id,
                profile=profile,
            )
            classified = payment_checkout_state_service.classify_stripe_payment_page(confirm_payload)
            if classified and classified.get("status") == "failed":
                classified["confirmation_token_id"] = confirmation_token_id
                classified["checkout_session_id"] = checkout_session_id
                return classified
            client_secret = _find_nested_string(confirm_payload, "client_secret")
            if not client_secret:
                return {
                    "status": "needs_review",
                    "failure_stage": "protocol_openai_confirm",
                    "message": "OpenAI confirm 未返回 payment_intent client_secret",
                    "screenshot_paths": [],
                    "checkout_session_id": checkout_session_id,
                    "checkout_url": checkout_url,
                    "confirmation_token_id": confirmation_token_id,
                    "openai_confirm": _openai_confirm_summary(confirm_payload),
                    "protocol_checkout_provider": "open_ai",
                    "protocol_checkout_currency": checkout_currency,
                    "protocol_http_profile": profile.name,
                }
            _emit(progress_callback, "protocol_card_payment_intent_confirm", checkout_session_id=checkout_session_id)
            pi_confirm_payload = _stripe_confirm_payment_intent(
                stripe_http,
                DEFAULT_STRIPE_PK,
                client_secret=client_secret,
                checkout_session_id=checkout_session_id,
                processor_entity=processor_entity,
                card_payload=card_payload,
                billing=billing,
                email=email,
                currency=checkout_currency,
                customer_id=customer_id,
                elements_context=elements_context,
            )
            _emit(progress_callback, "protocol_card_payment_intent", checkout_session_id=checkout_session_id)
            payment_intent = _wait_stripe_payment_intent(stripe_http, DEFAULT_STRIPE_PK, client_secret)
            payment_succeeded, payment_message = _payment_intent_success_result(payment_intent)
            if not payment_succeeded:
                failure_reason = _payment_intent_failure_reason(payment_intent)
                confirm_result = _payment_intent_confirm_summary(pi_confirm_payload)
                return {
                    "status": "needs_review",
                    "failure_stage": "post_submit",
                    "message": payment_message,
                    "screenshot_paths": [],
                    "checkout_session_id": checkout_session_id,
                    "checkout_url": checkout_url,
                    "confirmation_token_id": confirmation_token_id,
                    "payment_intent": {
                        "id": payment_intent.get("id") or _payment_intent_id_from_client_secret(client_secret),
                        "status": payment_intent.get("status") or "",
                        "failure_reason": failure_reason,
                        "confirm_result": confirm_result,
                        "next_action": _payment_intent_next_action_summary(payment_intent),
                    },
                    "protocol_checkout_provider": "open_ai",
                    "protocol_checkout_currency": checkout_currency,
                    "protocol_http_profile": profile.name,
                }
            _emit(progress_callback, "protocol_card_verify", checkout_session_id=checkout_session_id)
            verify = _verify_checkout_http(
                chatgpt_http,
                access_token=access_token,
                checkout_session_id=checkout_session_id,
                processor_entity=processor_entity,
                cookie_header=cookie_header,
                account_id=account_id,
                device_id=device_id,
                user_agent=profile.user_agent,
                sec_ch_ua=profile.sec_ch_ua,
                sec_ch_ua_platform=profile.sec_ch_ua_platform,
            )
            state = "success" if verify.get("state") == "succeeded" and payment_succeeded else "needs_review"
            _emit(progress_callback, "payment_completed", checkout_session_id=checkout_session_id, state=verify.get("state"))
            return {
                "status": state,
                "failure_stage": "" if state == "success" else "post_submit",
                "message": "协议支付已完成并通过 ChatGPT verify" if state == "success" else "协议支付已提交，但未确认最终状态",
                "screenshot_paths": [],
                "checkout_session_id": checkout_session_id,
                "checkout_url": checkout_url,
                "confirmation_token_id": confirmation_token_id,
                "payment_intent": {
                    "id": payment_intent.get("id") or _payment_intent_id_from_client_secret(client_secret),
                    "status": payment_intent.get("status") or "",
                    "confirm_result": _payment_intent_confirm_summary(pi_confirm_payload),
                    "next_action": _payment_intent_next_action_summary(payment_intent),
                },
                "verify": verify,
                "billing_address": {
                    "country": billing.get("country") or "",
                    "state": billing.get("state") or "",
                    "city": billing.get("city") or "",
                    "zip": billing.get("zip") or "",
                },
                "protocol_checkout_provider": "open_ai",
                "protocol_checkout_currency": checkout_currency,
                "protocol_http_profile": profile.name,
            }

        _emit(progress_callback, "protocol_card_init", checkout_session_id=checkout_session_id)
        init_ctx = _stripe_init(stripe_http, checkout_session_id, DEFAULT_STRIPE_PK, profile)
        _emit(progress_callback, "protocol_card_elements_session", checkout_session_id=checkout_session_id)
        _stripe_elements_session(stripe_http, checkout_session_id, DEFAULT_STRIPE_PK, init_ctx, profile)
        _emit(progress_callback, "protocol_card_address_update", state=billing.get("state"), zip=billing.get("zip"))
        _stripe_update_address(stripe_http, checkout_session_id, DEFAULT_STRIPE_PK, init_ctx, billing, profile)
        _emit(progress_callback, "protocol_card_payment_method", checkout_session_id=checkout_session_id)
        payment_method_id = _stripe_create_card_payment_method(
            stripe_http,
            checkout_session_id,
            DEFAULT_STRIPE_PK,
            init_ctx,
            card_payload,
            billing,
            email,
            profile,
        )
        _emit(progress_callback, "protocol_card_confirm", payment_method_id=payment_method_id)
        confirm_payload = _stripe_confirm_card(
            stripe_http,
            checkout_session_id,
            DEFAULT_STRIPE_PK,
            init_ctx,
            payment_method_id,
            processor_entity,
            profile,
        )
        classified = payment_checkout_state_service.classify_stripe_payment_page(confirm_payload)
        if classified and classified.get("status") == "failed":
            classified["payment_method_id"] = payment_method_id
            classified["checkout_session_id"] = checkout_session_id
            return classified
        if _confirm_requires_approval(confirm_payload):
            _emit(progress_callback, "protocol_card_approve", checkout_session_id=checkout_session_id)
            _approve_checkout_http(
                chatgpt_http,
                access_token=access_token,
                checkout_session_id=checkout_session_id,
                processor_entity=processor_entity,
                cookie_header=cookie_header,
                account_id=account_id,
                device_id=device_id,
                user_agent=profile.user_agent,
                accept_language=profile.accept_language,
                sec_ch_ua=profile.sec_ch_ua,
                sec_ch_ua_platform=profile.sec_ch_ua_platform,
            )
        _emit(progress_callback, "protocol_card_verify", checkout_session_id=checkout_session_id)
        verify = _verify_checkout_http(
            chatgpt_http,
            access_token=access_token,
            checkout_session_id=checkout_session_id,
            processor_entity=processor_entity,
            cookie_header=cookie_header,
            account_id=account_id,
            device_id=device_id,
            user_agent=profile.user_agent,
            sec_ch_ua=profile.sec_ch_ua,
            sec_ch_ua_platform=profile.sec_ch_ua_platform,
        )
        state = "success" if verify.get("state") == "succeeded" else "needs_review"
        _emit(progress_callback, "payment_completed", checkout_session_id=checkout_session_id, state=verify.get("state"))
        return {
            "status": state,
            "failure_stage": "" if state == "success" else "post_submit",
            "message": "协议支付已完成并通过 ChatGPT verify" if state == "success" else "协议支付已提交，但未确认最终状态",
            "screenshot_paths": [],
            "checkout_session_id": checkout_session_id,
            "checkout_url": checkout_url,
            "payment_method_id": payment_method_id,
            "verify": verify,
            "billing_address": {
                "country": billing.get("country") or "",
                "state": billing.get("state") or "",
                "city": billing.get("city") or "",
                "zip": billing.get("zip") or "",
            },
            "protocol_http_profile": profile.name,
        }
    except ProtocolCardFlowError as exc:
        logger.exception("[protocol_card] flow failed")
        return _build_result("failed", failure_stage=exc.stage, message=str(exc), screenshot_paths=[])
    except Exception as exc:
        logger.exception("[protocol_card] unexpected error")
        return _build_result(
            "failed",
            failure_stage="protocol_card_unexpected",
            message=f"协议支付异常: {exc}",
            screenshot_paths=[],
        )
