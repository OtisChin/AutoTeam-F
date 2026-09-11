from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any

import requests

try:
    from curl_cffi.requests import Session as CurlSession
except ImportError:  # pragma: no cover - optional runtime dependency
    CurlSession = None  # type: ignore[assignment]

from autotoken.api_routes.account_overview import PLUS_TRIAL_PROMO_CAMPAIGN_ID
from autotoken.payments.plus_trial import (
    CHECKOUT_URL,
    DEFAULT_CLIENT_BUILD,
    DEFAULT_CLIENT_VERSION,
    DEFAULT_USER_AGENT,
    TRACE_URL,
    checkout_amount_minor,
    checkout_currency,
    extract_processor_entity,
    initial_cookie_header,
    processor_entity_for_country,
    refresh_cookie_header,
    set_proxy,
)
from autotoken.services.payment_stripe import DEFAULT_STRIPE_PK

PROMO_CHECKOUT_STATE_BASE = "https://chatgpt.com/backend-api/payments/checkout"
STRIPE_PAYMENT_PAGES_BASE = "https://api.stripe.com/v1/payment_pages"
STRIPE_PREFLIGHT_URL = "https://api.stripe.com/"
STRIPE_VERSION = "2025-03-31.basil; checkout_server_update_beta=v1; checkout_manual_approval_preview=v1"


@dataclass(frozen=True)
class PromoPaymentRoute:
    method: str
    country: str
    currency: str
    locale: str
    label: str


PROMO_PAYMENT_ROUTES: dict[str, PromoPaymentRoute] = {
    "paypal": PromoPaymentRoute("paypal", "US", "USD", "en-US", "PayPal / US"),
    "momo": PromoPaymentRoute("momo", "VN", "VND", "vi-VN", "MoMo / VN"),
    "gcash": PromoPaymentRoute("gcash", "PH", "PHP", "en-PH", "GCash / PH"),
    "grabpay": PromoPaymentRoute("grabpay", "SG", "SGD", "en-SG", "GrabPay / SG"),
    "kakao_pay": PromoPaymentRoute("kakao_pay", "KR", "KRW", "ko-KR", "Kakao Pay / KR"),
    "gopay": PromoPaymentRoute("gopay", "ID", "IDR", "id-ID", "GoPay / ID"),
}

_METHOD_ALIASES = {
    "card_payment": "card",
    "direct_card": "card",
    "kakao": "kakao_pay",
    "go_pay": "gopay",
    "grab_pay": "grabpay",
}
_METHOD_FIELD_KEYS = {
    "payment_method_types",
    "paymentMethodTypes",
    "ordered_payment_method_types",
    "orderedPaymentMethodTypes",
    "payment_method_specs",
    "paymentMethodSpecs",
    "custom_payment_methods",
    "customPaymentMethods",
}
_OBJECT_METHOD_KEYS = ("type", "payment_method_type", "paymentMethodType", "name", "label", "display_name", "displayName", "id")
_CHECKOUT_SESSION_KEYS = (
    "checkout_session_id",
    "checkoutSessionId",
    "session_id",
    "sessionId",
    "id",
)


def normalize_promo_payment_method(value: Any) -> str:
    method = re.sub(r"[-\s]+", "_", str(value or "").strip().lower())
    method = _METHOD_ALIASES.get(method, method)
    compact = method.replace("_", "")
    for known in PROMO_PAYMENT_ROUTES:
        if compact == known.replace("_", "") or compact.startswith(f"{known.replace('_', '')}wallet"):
            method = known
            break
    if not method or method.startswith("cpmt_"):
        return ""
    return method


def normalize_promo_methods(values: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        method = normalize_promo_payment_method(value)
        if method and method not in seen:
            seen.add(method)
            out.append(method)
    return out


def extract_promo_payment_methods(payload: Any, *, country: str = "", currency: str = "") -> list[str]:
    """Recursively extract normalized payment method IDs from checkout/Stripe state."""

    found: list[Any] = []
    visited: set[int] = set()
    opaque_custom_seen = False
    text_mentions: set[str] = set()

    def add_candidate(value: Any) -> None:
        if isinstance(value, dict):
            for key in _OBJECT_METHOD_KEYS:
                if value.get(key) not in (None, ""):
                    found.append(value.get(key))
                    break
            serialized = json.dumps(value, ensure_ascii=False, default=str).lower()
            for method in PROMO_PAYMENT_ROUTES:
                if method in serialized or method.replace("_", "") in serialized.replace("_", ""):
                    text_mentions.add(method)
            return
        found.append(value)

    def walk(obj: Any) -> None:
        nonlocal opaque_custom_seen
        if isinstance(obj, dict):
            marker = id(obj)
            if marker in visited:
                return
            visited.add(marker)
            for key, value in obj.items():
                if key in _METHOD_FIELD_KEYS:
                    if isinstance(value, list):
                        for item in value:
                            if isinstance(item, dict) and str(item.get("id") or "").startswith("cpmt_"):
                                opaque_custom_seen = True
                            add_candidate(item)
                    elif isinstance(value, dict):
                        add_candidate(value)
                    else:
                        add_candidate(value)
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(payload)
    methods = normalize_promo_methods(found + sorted(text_mentions))
    if (
        str(country or "").upper() == "PH"
        and str(currency or "").upper() == "PHP"
        and opaque_custom_seen
        and "gcash" not in methods
    ):
        methods.append("gcash")
    return methods


def extract_checkout_session_id(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in _CHECKOUT_SESSION_KEYS:
            value = str(payload.get(key) or "").strip()
            if value.startswith(("oaics_", "cs_live_", "cs_test_")):
                return value
        for key in ("checkout_session", "checkoutSession", "session", "checkout", "data", "result", "payload"):
            found = extract_checkout_session_id(payload.get(key))
            if found:
                return found
        text = json.dumps(payload, ensure_ascii=False, default=str)
    elif isinstance(payload, list):
        for item in payload:
            found = extract_checkout_session_id(item)
            if found:
                return found
        text = json.dumps(payload, ensure_ascii=False, default=str)
    else:
        text = str(payload or "")
    matched = re.search(r"(oaics_[A-Za-z0-9_\-]+|cs_(?:live|test)_[A-Za-z0-9_\-]+)", text)
    return matched.group(1) if matched else ""


def checkout_session_prefix(session_id: str) -> str:
    text = str(session_id or "")
    if text.startswith("oaics_"):
        return "oaics_"
    if text.startswith("cs_live_"):
        return "cs_live_"
    if text.startswith("cs_test_"):
        return "cs_test_"
    return ""


def safe_promo_error(value: Any, *, limit: int = 280) -> str:
    text = str(value or "")
    text = re.sub(r"Bearer\s+[A-Za-z0-9._\-]+", "Bearer ***", text, flags=re.I)
    text = re.sub(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+", "***", text)
    text = re.sub(r"(session-token=)[^;\s]+", r"\1***", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def route_for_promo_method(method: str) -> PromoPaymentRoute | None:
    return PROMO_PAYMENT_ROUTES.get(normalize_promo_payment_method(method))


def promo_payment_method_options() -> list[dict[str, str]]:
    return [asdict(route) for route in PROMO_PAYMENT_ROUTES.values()]


def _session_factory() -> Any:
    if CurlSession is not None:
        return CurlSession(impersonate="chrome136")
    session = requests.Session()
    return session


def _new_session(access_token: str, *, proxy_url: str, locale: str, device_id: str, session_cookie: str = "") -> Any:
    session = _session_factory()
    if hasattr(session, "trust_env"):
        session.trust_env = False
    session.headers.update(
        {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": f"{locale},{locale.split('-', 1)[0]};q=0.9,en;q=0.8",
            "Authorization": f"Bearer {access_token}",
            "Origin": "https://chatgpt.com",
            "Referer": "https://chatgpt.com/",
            "Content-Type": "application/json",
            "oai-device-id": device_id,
            "oai-language": locale,
            "oai-session-id": str(uuid.uuid4()),
            "oai-client-version": DEFAULT_CLIENT_VERSION,
            "oai-client-build-number": DEFAULT_CLIENT_BUILD,
            "Cookie": initial_cookie_header(session_cookie, device_id),
        }
    )
    set_proxy(session, proxy_url)
    return session


def _response_detail(response: Any) -> str:
    status = int(getattr(response, "status_code", 0) or 0)
    text = str(getattr(response, "text", "") or "")
    try:
        data = response.json()
        if isinstance(data, dict):
            for key in ("detail", "message", "error", "reason", "code", "type"):
                if data.get(key):
                    text = str(data.get(key))
                    break
    except Exception:
        pass
    return safe_promo_error(f"HTTP {status}: {text}")


def _classify_http_failure(response: Any, *, state_prefix: str) -> tuple[str, str, str]:
    status = int(getattr(response, "status_code", 0) or 0)
    detail = _response_detail(response)
    lower = detail.lower()
    if status == 400 and "already paid" in lower:
        return "already_paid", "already_paid", detail
    if status == 400:
        return "checkout_rejected", "checkout_rejected", detail
    if status == 401:
        return "token_invalid", "token_invalid", detail
    if status == 403:
        return "risk_blocked", f"{state_prefix}_blocked", detail
    if status == 429:
        return "rate_limited", f"{state_prefix}_rate_limited", detail
    return "unknown", f"{state_prefix}_failed", detail


def _cloudflare_exit(session: Any, *, timeout: float) -> tuple[str, int, str]:
    url = os.environ.get("PAYMENT_CHECK_EXIT_URL", TRACE_URL).strip() or TRACE_URL
    try:
        response = session.get(url, timeout=min(timeout, 15.0))
        status = int(getattr(response, "status_code", 0) or 0)
        if status >= 400:
            return "", status, _response_detail(response)
        fields = dict(
            line.split("=", 1)
            for line in str(getattr(response, "text", "") or "").splitlines()
            if "=" in line
        )
        return str(fields.get("loc") or "").strip().upper(), status, ""
    except Exception as exc:
        return "", 0, safe_promo_error(exc)


def _preflight_stripe(session: Any, *, timeout: float) -> None:
    url = os.environ.get("PAYMENT_STRIPE_PREFLIGHT_URL", STRIPE_PREFLIGHT_URL).strip() or STRIPE_PREFLIGHT_URL
    session.get(url, timeout=min(timeout, 15.0))


def _warm_chatgpt(session: Any, *, timeout: float) -> tuple[int, str]:
    url = os.environ.get("PAYMENT_WARMUP_URL", "https://chatgpt.com/").strip() or "https://chatgpt.com/"
    try:
        response = session.get(url, timeout=min(timeout, 20.0))
        status = int(getattr(response, "status_code", 0) or 0)
        if status >= 400:
            return status, _response_detail(response)
        return status, ""
    except Exception as exc:
        return 0, safe_promo_error(exc)


def _check_me(session: Any, access_token: str, account_id: str, *, timeout: float) -> tuple[bool, dict[str, Any]]:
    url = os.environ.get("PAYMENT_ME_URL", "https://chatgpt.com/backend-api/me").strip() or "https://chatgpt.com/backend-api/me"
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    if account_id:
        headers["ChatGPT-Account-ID"] = account_id
    try:
        response = session.get(url, headers=headers, timeout=min(timeout, 30.0))
    except Exception as exc:
        return False, {"status": "unknown", "state": "me_failed", "error": safe_promo_error(exc), "http_status": 0}
    status = int(getattr(response, "status_code", 0) or 0)
    if 200 <= status < 300:
        return True, {"http_status": status}
    result_status, state, error = _classify_http_failure(response, state_prefix="me")
    if result_status == "checkout_rejected":
        result_status = "unknown"
        state = "me_failed"
    return False, {"status": result_status, "state": state, "error": error, "http_status": status}


def _checkout_body(route: PromoPaymentRoute) -> dict[str, Any]:
    return {
        "entry_point": "all_plans_pricing_modal",
        "plan_name": "chatgptplusplan",
        "billing_details": {"country": route.country, "currency": route.currency},
        "checkout_ui_mode": "custom",
        "promo_campaign": {
            "promo_campaign_id": PLUS_TRIAL_PROMO_CAMPAIGN_ID,
            "is_coupon_from_query_param": False,
        },
    }


def _create_checkout(session: Any, route: PromoPaymentRoute, *, timeout: float) -> tuple[bool, dict[str, Any]]:
    refresh_cookie_header(session)
    headers = {
        "Referer": "https://chatgpt.com/",
        "x-openai-target-path": "/backend-api/payments/checkout",
        "x-openai-target-route": "/backend-api/payments/checkout",
    }
    try:
        response = session.post(
            os.environ.get("PAYMENT_CHECKOUT_URL", CHECKOUT_URL).strip() or CHECKOUT_URL,
            json=_checkout_body(route),
            headers=headers,
            timeout=timeout,
        )
    except Exception as exc:
        return False, {"status": "unknown", "state": "checkout_failed", "error": safe_promo_error(exc), "http_status": 0}
    status = int(getattr(response, "status_code", 0) or 0)
    if status >= 400:
        result_status, state, error = _classify_http_failure(response, state_prefix="checkout")
        return False, {"status": result_status, "state": state, "error": error, "http_status": status}
    try:
        payload = response.json() or {}
    except Exception as exc:
        return False, {"status": "unknown", "state": "invalid_response", "error": safe_promo_error(exc), "http_status": status}
    if not isinstance(payload, dict):
        return False, {"status": "unknown", "state": "invalid_response", "error": "Checkout 返回格式异常", "http_status": status}
    return True, {"payload": payload, "http_status": status}


def _extract_publishable_keys(payload: Any) -> list[str]:
    keys: list[str] = []
    text = json.dumps(payload, ensure_ascii=False, default=str) if not isinstance(payload, str) else payload
    for key in re.findall(r"pk_(?:live|test)_[A-Za-z0-9]+", text):
        if key not in keys:
            keys.append(key)
    for raw in re.split(r"[\s,;]+", os.environ.get("PAYMENT_STRIPE_PUBLISHABLE_KEYS", "")):
        key = raw.strip()
        if key.startswith(("pk_live_", "pk_test_")) and key not in keys:
            keys.append(key)
    if DEFAULT_STRIPE_PK not in keys:
        keys.append(DEFAULT_STRIPE_PK)
    return keys


def _fetch_oaics_state(
    session: Any,
    access_token: str,
    session_id: str,
    route: PromoPaymentRoute,
    *,
    processor: str,
    device_id: str,
    timeout: float,
) -> dict[str, Any]:
    checkout_url = f"https://chatgpt.com/checkout/{processor}/{session_id}"
    response = session.get(
        f"{os.environ.get('PAYMENT_CHECKOUT_STATE_BASE', PROMO_CHECKOUT_STATE_BASE).rstrip('/')}/{processor}/{session_id}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Referer": checkout_url,
            "x-openai-target-path": "/backend-api/payments/checkout/{processor_entity}/{checkout_session_id}",
            "x-openai-target-route": "/backend-api/payments/checkout/{processor_entity}/{checkout_session_id}",
            "oai-device-id": device_id,
            "oai-language": route.locale,
        },
        timeout=timeout,
    )
    if int(getattr(response, "status_code", 0) or 0) >= 400:
        raise RuntimeError(_response_detail(response))
    payload = response.json() or {}
    return payload if isinstance(payload, dict) else {}


def _fetch_stripe_state(session: Any, session_id: str, route: PromoPaymentRoute, checkout_payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    errors: list[str] = []
    for key in _extract_publishable_keys(checkout_payload):
        try:
            response = session.post(
                f"{os.environ.get('PAYMENT_STRIPE_API_BASE', 'https://api.stripe.com/v1').rstrip('/')}/payment_pages/{session_id}/init",
                data={
                    "browser_locale": route.locale,
                    "key": key,
                    "_stripe_version": STRIPE_VERSION,
                },
                headers={"Origin": "https://js.stripe.com", "Referer": "https://js.stripe.com/"},
                timeout=timeout,
            )
            if int(getattr(response, "status_code", 0) or 0) >= 400:
                errors.append(_response_detail(response))
                continue
            payload = response.json() or {}
            return payload if isinstance(payload, dict) else {}
        except Exception as exc:
            errors.append(safe_promo_error(exc))
    raise RuntimeError(errors[-1] if errors else "Stripe init 失败")


def detect_promo_payment_method(
    *,
    access_token: str,
    account_id: str,
    method: str,
    proxy_url: str,
    device_id: str = "",
    session_cookie: str = "",
    verify_proxy_country: bool = True,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Create a Plus-trial checkout and inspect returned payment methods for one route."""

    route = route_for_promo_method(method)
    if route is None:
        return {"method": method, "status": "disabled", "state": "unsupported_method", "error": "不支持的支付方式"}
    access_token = str(access_token or "").strip()
    if not access_token:
        return {"method": route.method, "status": "token_invalid", "state": "missing_access_token", "error": "缺少 access_token"}
    timeout = float(timeout or float(os.environ.get("PAYMENT_CHECK_TIMEOUT_SECONDS", "45") or 45))
    device_id = str(device_id or "").strip() or str(uuid.uuid4())
    session = _new_session(access_token, proxy_url=proxy_url, locale=route.locale, device_id=device_id, session_cookie=session_cookie)
    try:
        checked_at = time.time()
        result: dict[str, Any] = {
            "method": route.method,
            "country": route.country,
            "currency": route.currency,
            "locale": route.locale,
            "label": route.label,
            "status": "unknown",
            "state": "started",
            "methods": [],
            "checked_at": checked_at,
            "exit": "",
            "http_status": 0,
            "session_type": "",
        }
        if verify_proxy_country:
            observed, exit_status, exit_error = _cloudflare_exit(session, timeout=timeout)
            result["exit"] = observed
            if exit_status:
                result["http_status"] = exit_status
            if not observed:
                result.update({"status": "proxy_unavailable", "state": "proxy_unavailable", "error": exit_error or "代理出口无法检测"})
                return result
            if observed != route.country:
                result.update(
                    {
                        "status": "proxy_country_mismatch",
                        "state": "proxy_country_mismatch",
                        "error": f"出口国家 {observed} 与 {route.country} 不一致",
                    }
                )
                return result
        try:
            _preflight_stripe(session, timeout=timeout)
        except Exception:
            pass
        warm_status, warm_error = _warm_chatgpt(session, timeout=timeout)
        if warm_status == 403:
            result.update({"status": "risk_blocked", "state": "warmup_blocked", "error": warm_error, "http_status": warm_status})
            return result
        ok, me_result = _check_me(session, access_token, account_id, timeout=timeout)
        if not ok:
            result.update(me_result)
            return result
        checkout_ok, checkout_result = _create_checkout(session, route, timeout=timeout)
        result["http_status"] = checkout_result.get("http_status") or result.get("http_status") or 0
        if not checkout_ok:
            result.update({key: value for key, value in checkout_result.items() if key != "payload"})
            return result
        checkout_payload = checkout_result.get("payload") or {}
        session_id = extract_checkout_session_id(checkout_payload)
        result["session_type"] = checkout_session_prefix(session_id)
        merged_payloads: list[Any] = [checkout_payload]
        methods = extract_promo_payment_methods(checkout_payload, country=route.country, currency=route.currency)
        if session_id.startswith("oaics_"):
            processor = extract_processor_entity(checkout_payload) or processor_entity_for_country(route.country)
            try:
                state_payload = _fetch_oaics_state(
                    session,
                    access_token,
                    session_id,
                    route,
                    processor=processor,
                    device_id=device_id,
                    timeout=timeout,
                )
                merged_payloads.append(state_payload)
                methods = normalize_promo_methods(
                    methods + extract_promo_payment_methods(state_payload, country=route.country, currency=route.currency)
                )
            except Exception as exc:
                if not methods:
                    result.update({"status": "unknown", "state": "checkout_state_failed", "error": safe_promo_error(exc)})
                    return result
        elif session_id.startswith(("cs_live_", "cs_test_")):
            try:
                stripe_payload = _fetch_stripe_state(session, session_id, route, checkout_payload, timeout=timeout)
                merged_payloads.append(stripe_payload)
                methods = normalize_promo_methods(
                    methods + extract_promo_payment_methods(stripe_payload, country=route.country, currency=route.currency)
                )
            except Exception as exc:
                if not methods:
                    result.update({"status": "unknown", "state": "stripe_init_failed", "error": safe_promo_error(exc)})
                    return result
        else:
            result.update({"status": "unknown", "state": "invalid_checkout_session", "error": "Checkout 未返回支持的会话 ID"})
            return result
        result["methods"] = methods
        result["amount_minor"] = checkout_amount_minor(merged_payloads[-1])
        result["amount_currency"] = checkout_currency(merged_payloads[-1]) or route.currency
        if methods:
            result.update({"status": "available", "state": "payment_methods_available"})
        else:
            result.update({"status": "not_returned", "state": "payment_methods_empty"})
        return result
    finally:
        try:
            session.close()
        except Exception:
            pass
