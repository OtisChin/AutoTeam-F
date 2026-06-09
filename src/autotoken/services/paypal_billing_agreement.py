"""PayPal billing-agreement helper functions."""

import re
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from autotoken.services import payment_checkout_state, paypal_preflight


def paypal_ba_extract_attempts(value: Any, *, default: int = 5) -> int:
    try:
        return max(1, min(5, int(value if value is not None else default)))
    except Exception:
        return max(1, min(5, int(default or 5)))


def paypal_ba_payment_method_country(
    *,
    override: str | None,
    protocol_no_card: bool,
    paypal_country: str,
) -> str:
    normalized_override = re.sub(r"[^A-Za-z]", "", str(override or "")).upper()[:2]
    if normalized_override:
        return normalized_override
    if protocol_no_card:
        return "US"
    normalized_country = re.sub(r"[^A-Za-z]", "", str(paypal_country or "")).upper()[:2]
    return normalized_country or "US"


def paypal_ba_checkout_country(paypal_country: str) -> str:
    normalized_country = re.sub(r"[^A-Za-z]", "", str(paypal_country or "")).upper()[:2]
    if normalized_country == "JP":
        return "US"
    return normalized_country


def paypal_ba_timeout_seconds(value: Any, *, default: int = 90) -> int:
    try:
        timeout = int(value if value is not None else default)
    except Exception:
        timeout = int(default or 90)
    return max(30, min(90, timeout))


def paypal_checkout_payload(*, country: str = "US", currency: str = "USD", checkout_ui_mode: str = "hosted"):
    return {
        "entry_point": "all_plans_pricing_modal",
        "plan_name": "chatgptplusplan",
        "billing_details": {"country": country, "currency": currency},
        "promo_campaign": {
            "promo_campaign_id": "plus-1-month-free",
            "is_coupon_from_query_param": False,
        },
        "checkout_ui_mode": checkout_ui_mode,
        "cancel_url": "https://chatgpt.com/#pricing",
    }


def paypal_extract_result_from_redirect(
    http: Any,
    redirect_url: str,
    checkout_session_id: str,
    pm_id: str,
    *,
    resolve_approve_url: Callable[[Any, str], tuple[str, str]],
) -> dict[str, Any]:
    try:
        approve_url, ba_token = resolve_approve_url(http, redirect_url)
    except Exception as exc:
        return {
            "status": "failed",
            "failure_stage": "extract_ba_link_resolve",
            "message": f"Failed to resolve final PayPal URL: {exc}",
            "checkout_session_id": checkout_session_id,
            "pm_id": pm_id,
        }
    if not approve_url:
        return {
            "status": "failed",
            "failure_stage": "extract_ba_link_resolve",
            "message": "Failed to resolve final PayPal URL",
            "checkout_session_id": checkout_session_id,
            "pm_id": pm_id,
        }
    if not ba_token:
        return {
            "status": "failed",
            "failure_stage": "extract_ba_link_parse",
            "message": f"Could not extract BA token from URL: {approve_url[:200]}",
            "checkout_session_id": checkout_session_id,
            "pm_id": pm_id,
            "approve_url": approve_url,
        }
    return {
        "status": "success",
        "ba_token": ba_token,
        "approve_url": approve_url,
        "checkout_session_id": checkout_session_id,
        "pm_id": pm_id,
    }


def paypal_protocol_elements_options() -> dict[str, str]:
    return {
        "elements_options_client[stripe_js_locale]": "auto",
        "elements_options_client[saved_payment_method][enable_save]": "never",
        "elements_options_client[saved_payment_method][enable_redisplay]": "never",
    }


def paypal_protocol_checkout_amount(payload: dict) -> str:
    total_summary = payload.get("total_summary") if isinstance(payload.get("total_summary"), dict) else {}
    invoice = payload.get("invoice") if isinstance(payload.get("invoice"), dict) else {}
    if total_summary.get("due") is not None:
        return str(total_summary["due"])
    if invoice.get("amount_due") is not None:
        return str(invoice["amount_due"])
    line_items = payload.get("line_items") if isinstance(payload.get("line_items"), list) else []
    if line_items:
        try:
            return str(sum(int(item.get("amount") or 0) for item in line_items if isinstance(item, dict)))
        except Exception:
            return "0"
    return "0"


def paypal_protocol_amount_due(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        digits = re.sub(r"\D+", "", str(value or ""))
        return int(digits or "0")


def paypal_protocol_payment_method_types(payload: Any) -> set[str]:
    found: set[str] = set()

    def visit(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                visit(child_value, str(child_key or ""))
            return
        if isinstance(value, (list, tuple)):
            if key in {"payment_method_types", "ordered_payment_method_types", "automatic_payment_method_types"}:
                for item in value:
                    if isinstance(item, str):
                        found.add(item.strip().lower())
            for item in value:
                visit(item)

    visit(payload)
    return found


def paypal_protocol_unescape_url(value: str) -> str:
    return (
        str(value or "")
        .replace("&amp;", "&")
        .replace("&#38;", "&")
        .replace("&#x26;", "&")
        .replace("\\u0026", "&")
        .replace("\\/", "/")
    )


def paypal_protocol_extract_url_from_text(value: str) -> str:
    text = paypal_protocol_unescape_url(value).strip()
    if not text:
        return ""
    if text.startswith("http") and ("paypal.com" in text.lower() or "pm-redirects.stripe.com" in text.lower()):
        return text.strip("\"'<> ")
    for match in re.finditer(r"https?://[^\s\"'<>\\]+", text, re.I):
        url = match.group(0).rstrip("),.;")
        lowered = url.lower()
        if "paypal.com" in lowered or "pm-redirects.stripe.com" in lowered:
            return url
    return ""


def paypal_protocol_extract_ba_token(url: str, fallback: str = "") -> str:
    try:
        params = dict(parse_qsl(urlsplit(str(url or "")).query, keep_blank_values=True))
    except Exception:
        params = {}
    for name in ("ba_token", "baToken", "billingAgreementId", "billing_agreement_id", "token"):
        value = str(params.get(name) or "").strip()
        if value.upper().startswith("BA-"):
            return value
    match = re.search(r"\bBA-[A-Z0-9-]{6,}\b", str(url or ""), re.I)
    if match:
        return match.group(0)
    return fallback


def paypal_direct_ba_pre_extracted(
    params: Any,
    *,
    fallback_checkout_url: str = "",
) -> dict[str, Any] | None:
    approve_url = str(getattr(params, "paypal_approve_url", "") or "").strip()
    ba_token = str(getattr(params, "paypal_ba_token", "") or "").strip()
    if approve_url and not ba_token:
        ba_token = paypal_protocol_extract_ba_token(approve_url)
    if not approve_url and not ba_token:
        return None
    if not ba_token:
        raise ValueError("paypal_ba_token 不能为空，或 paypal_approve_url 必须包含 BA token")

    checkout_session_id = str(getattr(params, "paypal_checkout_session_id", "") or "").strip()
    checkout_url = (
        str(getattr(params, "paypal_checkout_url", "") or "").strip()
        or str(fallback_checkout_url or "").strip()
    )
    hosted_checkout_url = str(getattr(params, "paypal_hosted_checkout_url", "") or "").strip()
    if not (checkout_session_id or checkout_url or hosted_checkout_url):
        raise ValueError(
            "直连 PayPal BA/link 模式需要 paypal_checkout_session_id、paypal_checkout_url、"
            "paypal_hosted_checkout_url 或 checkout_url"
        )

    return {
        "status": "success",
        "ba_token": ba_token,
        "approve_url": approve_url,
        "checkout_session_id": checkout_session_id,
        "checkout_url": checkout_url,
        "hosted_checkout_url": hosted_checkout_url,
        "pm_id": str(getattr(params, "paypal_payment_method_id", "") or "").strip(),
    }


def find_paypal_redirect_url(payload: Any) -> str:
    seen: set[int] = set()

    def walk(value: Any) -> str:
        marker = id(value)
        if marker in seen:
            return ""
        seen.add(marker)
        if isinstance(value, str):
            found = paypal_protocol_extract_url_from_text(value)
            if found:
                return found
            return ""
        if isinstance(value, dict):
            if value.get("type") == "redirect_to_url" and isinstance(value.get("redirect_to_url"), dict):
                url = paypal_protocol_extract_url_from_text(str((value.get("redirect_to_url") or {}).get("url") or ""))
                if url:
                    return url
            for key in ("url", "href", "return_url", "redirect_url"):
                url = paypal_protocol_extract_url_from_text(str(value.get(key) or ""))
                if url:
                    return url
            for nested in value.values():
                found = walk(nested)
                if found:
                    return found
        if isinstance(value, list):
            for item in value:
                found = walk(item)
                if found:
                    return found
        return ""

    return walk(payload)


def paypal_create_account_entry_url(
    url: str,
    *,
    ba_token: str = "",
    country: str = "US",
    lang: str = "en",
) -> str:
    raw_url = str(url or "").strip()
    if not raw_url or not payment_checkout_state.is_paypal_host(raw_url):
        return ""
    try:
        parsed = urlsplit(raw_url)
    except Exception:
        return ""
    normalized_country = paypal_preflight.normalize_paypal_country(country)
    normalized_lang = paypal_preflight.normalize_paypal_lang(lang, country=normalized_country)
    locale = f"{normalized_lang}_{normalized_country}"
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    token = paypal_protocol_extract_ba_token(raw_url, ba_token)
    if not token:
        return ""
    query["ul"] = "1"
    query["country.x"] = normalized_country
    query["locale.x"] = locale
    query["modxo_redirect_reason"] = "guest_user"
    query["ulOnboardRedirect"] = "true"
    query["ba_token"] = token
    return urlunsplit(("https", "www.paypal.com", "/agreements/approve", urlencode(query), ""))


def paypal_ba_extract_kwargs(
    *,
    auth_session_context: Mapping[str, Any] | dict[str, Any],
    access_token: str,
    proxy_url: str,
    provider_proxy_url: str,
    paypal_country: str,
    payment_method_country: str,
    timeout_seconds: Any,
    is_cancelled: Callable[[], bool],
) -> dict[str, Any]:
    context = dict(auth_session_context or {})
    return {
        "access_token": str(access_token or ""),
        "session_token": str(context.get("session_token") or ""),
        "cookie_header": str(context.get("cookie_header") or ""),
        "account_id": str(context.get("account_id") or ""),
        "device_id": str(context.get("device_id") or ""),
        "user_agent": str(context.get("user_agent") or ""),
        "openai_sentinel_token": str(context.get("openai_sentinel_token") or ""),
        "oai_client_version": str(context.get("oai_client_version") or ""),
        "oai_client_build_number": str(context.get("oai_client_build_number") or ""),
        "proxy_url": str(proxy_url or ""),
        "provider_proxy_url": str(provider_proxy_url or ""),
        "approve_proxy_url": str(provider_proxy_url or ""),
        "country": paypal_ba_checkout_country(paypal_country),
        "currency": "USD",
        "payment_method_country": str(payment_method_country or ""),
        "timeout_seconds": paypal_ba_timeout_seconds(timeout_seconds),
        "is_cancelled": is_cancelled,
    }


def paypal_ba_auth_context(
    email: str,
    fallback_access_token: str,
    *,
    session_context_loader: Callable[[str], Mapping[str, Any] | dict[str, Any]],
    use_full_context: bool,
    log_failure: Callable[[Exception], None] | None = None,
) -> dict[str, str]:
    try:
        raw_context = session_context_loader(email)
        session_context = dict(raw_context or {})
    except Exception as exc:
        if log_failure:
            log_failure(exc)
        session_context = {}

    access_token_value = (
        str(session_context.get("access_token") or "").strip() or str(fallback_access_token or "").strip()
    )
    if use_full_context:
        merged = dict(session_context)
        merged["access_token"] = access_token_value
        return {str(key): str(value or "") for key, value in merged.items()}

    return {
        "access_token": access_token_value,
        "session_token": "",
        "cookie_header": "",
        "account_id": "",
        "device_id": "",
        "user_agent": str(session_context.get("user_agent") or ""),
        "openai_sentinel_token": "",
        "oai_client_version": "",
        "oai_client_build_number": "",
    }


def paypal_already_paid_text(value: Any) -> bool:
    normalized = re.sub(r"\s+", " ", str(value or "")).strip().lower()
    return bool(normalized) and any(
        marker in normalized
        for marker in (
            "user is paid",
            "user already paid",
            "user is already paid",
            "already a paid user",
            "already paid user",
            "already subscribed",
            "already has an active subscription",
            "用户已付费",
            "已是付费用户",
            "已有有效订阅",
        )
    )


def paypal_user_paid_success(candidate_email: str, message: str = "") -> dict[str, Any]:
    return {
        "status": "success",
        "failure_stage": "",
        "message": message or "ChatGPT 返回 User is already paid，账号已是付费用户，标记为 PayPal 绑定成功",
        "screenshot_paths": [],
        "email": candidate_email,
        "user_paid_skip": True,
    }


def paypal_ba_progress_base(
    *,
    stage: str,
    email: str,
    current: int,
    total: int,
    retry_round: int | None = None,
    ba_attempt: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "stage": stage,
        "email": email,
        "current": current,
        "total": total,
    }
    if retry_round is not None:
        payload["retry_round"] = retry_round
    if ba_attempt is not None:
        payload["ba_attempt"] = ba_attempt
    return payload


def paypal_provider_proxy_selected_progress(
    *,
    email: str,
    current: int,
    total: int,
    proxy_label: str,
    proxy_api_provider: str,
    proxy_summary: str,
    retry_round: int | None = None,
    ba_attempt: int | None = None,
) -> dict[str, Any]:
    payload = paypal_ba_progress_base(
        stage="paypal_provider_proxy_selected",
        email=email,
        current=current,
        total=total,
        retry_round=retry_round,
        ba_attempt=ba_attempt,
    )
    payload.update(
        {
            "proxy_label": proxy_label,
            "proxy_api_provider": proxy_api_provider,
            "message": f"PayPal provider 阶段已切换代理: {proxy_summary}",
        }
    )
    return payload


def paypal_provider_proxy_failed_progress(
    *,
    email: str,
    current: int,
    total: int,
    proxy_label: str,
    proxy_api_provider: str,
    error: Any,
    retry_round: int | None = None,
) -> dict[str, Any]:
    payload = paypal_ba_progress_base(
        stage="paypal_provider_proxy_failed",
        email=email,
        current=current,
        total=total,
        retry_round=retry_round,
    )
    payload.update(
        {
            "proxy_label": proxy_label,
            "proxy_api_provider": proxy_api_provider,
            "message": f"PayPal provider 阶段代理获取失败，回退当前代理: {error}",
            "level": "warn",
        }
    )
    return payload


def paypal_ba_extract_attempt_failed_progress(
    *,
    email: str,
    current: int,
    total: int,
    ba_attempt: int,
    max_ba_attempts: int,
    result_payload: Mapping[str, Any] | dict[str, Any] | None,
    retry_round: int | None = None,
) -> dict[str, Any]:
    result = dict(result_payload or {})
    payload = paypal_ba_progress_base(
        stage="paypal_ba_extract_attempt_failed",
        email=email,
        current=current,
        total=total,
        retry_round=retry_round,
        ba_attempt=ba_attempt,
    )
    payload.update(
        {
            "max_ba_attempts": max_ba_attempts,
            "failure_stage": result.get("failure_stage") or "",
            "message": (
                f"PayPal BA 第 {ba_attempt}/{max_ba_attempts} 次失败: " + str(result.get("message") or "unknown")
            ),
            "level": "warn",
        }
    )
    return payload


def paypal_ba_extract_retry_progress(
    *,
    email: str,
    current: int,
    total: int,
    ba_attempt: int,
    max_ba_attempts: int,
    retry_round: int | None = None,
) -> dict[str, Any]:
    payload = paypal_ba_progress_base(
        stage="paypal_ba_extract_retry",
        email=email,
        current=current,
        total=total,
        retry_round=retry_round,
        ba_attempt=ba_attempt,
    )
    payload.update(
        {
            "max_ba_attempts": max_ba_attempts,
            "message": f"PayPal BA 第 {ba_attempt}/{max_ba_attempts} 次重试，重新获取代理和 checkout",
            "level": "warn",
        }
    )
    return payload


def paypal_ba_extracted_progress(
    *,
    email: str,
    current: int,
    total: int,
    ba_token: Any,
) -> dict[str, Any]:
    token = str(ba_token or "")
    return {
        "stage": "paypal_ba_extracted",
        "email": email,
        "current": current,
        "total": total,
        "ba_token": ba_token,
        "message": "已通过 HTTP 协议提取 PayPal BA 链接: " + token[:12] + "...",
    }


def paypal_ba_extract_failed_progress(
    *,
    email: str,
    current: int,
    total: int,
    result_payload: Mapping[str, Any] | dict[str, Any] | None,
) -> dict[str, Any]:
    result = dict(result_payload or {})
    return {
        "stage": "paypal_ba_extract_failed",
        "email": email,
        "current": current,
        "total": total,
        "message": "HTTP 提取 BA 链接失败: " + str(result.get("message") or "unknown"),
        "level": "warn",
    }


def paypal_approve_proxy_selected_progress(
    *,
    email: str,
    current: int,
    total: int,
    proxy_label: str,
    proxy_api_provider: str,
    proxy_summary: str,
    ba_attempt: int,
) -> dict[str, Any]:
    return {
        "stage": "paypal_approve_proxy_selected",
        "email": email,
        "current": current,
        "total": total,
        "proxy_label": proxy_label,
        "proxy_api_provider": proxy_api_provider,
        "ba_attempt": ba_attempt,
        "message": f"PayPal BA 重试将使用 provider 代理执行 ChatGPT approve: {proxy_summary}",
    }


def paypal_checkout_long_link_extracted_progress(
    *,
    email: str,
    current: int,
    total: int,
    checkout_url: str,
) -> dict[str, Any]:
    return {
        "stage": "paypal_checkout_long_link_extracted",
        "email": email,
        "current": current,
        "total": total,
        "checkout_url": checkout_url,
        "message": "已通过 HTTP 协议获取 PayPal 可用长 checkout 链接，继续后续流程",
    }
