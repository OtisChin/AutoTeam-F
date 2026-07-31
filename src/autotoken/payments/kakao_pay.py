"""Korea Kakao Pay checkout link extraction core."""

from __future__ import annotations

import random
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit

import requests

from autotoken.payments.brazil_pix import (
    DEFAULT_STRIPE_PK,
    TIMEOUT,
    build_kookeey_proxy,
    extract_pk,
    pix_proxy_context,
    short,
)
from autotoken.payments.us_paypal import (
    build_chatgpt_session,
    build_stripe_session,
    new_http_session,
    normalize_paypal_proxy_url,
    paypal_proxy_with_fresh_sid,
    warm_chatgpt_checkout_context,
)
from autotoken.services.chatgpt_session import chatgpt_checkout_headers, configure_chatgpt_http_session

try:
    from autotoken.payments.gopay_executor import _checkout_approval_sentinel_headers
except Exception:  # pragma: no cover - optional checkout hardening helper
    _checkout_approval_sentinel_headers = None

LogFn = Callable[[str], None]
KAKAO_CHECKOUT_COUNTRY = "KR"
KAKAO_PROMOTION_COUNTRY = "VN"
KAKAO_PROVIDER_COUNTRY = "KR"
KAKAO_PROMO_ID = "plus-1-month-free"
KAKAO_STRIPE_VERSION = "2025-03-31.basil; checkout_server_update_beta=v1; checkout_manual_approval_preview=v1"
KAKAO_STRIPE_RUNTIME_VERSION = "c00af4ce81"
KAKAO_STRIPE_PAYMENT_UA = f"stripe.js/{KAKAO_STRIPE_RUNTIME_VERSION}; stripe-js-v3/{KAKAO_STRIPE_RUNTIME_VERSION}; checkout"

KR_BILLING_PRESETS = [
    ("Min Kim", "1 Sejong-daero", "Seoul", "04524"),
    ("Jiwoo Lee", "12 Teheran-ro", "Seoul", "06234"),
    ("Seo Yun Park", "55 Jong-ro", "Seoul", "03161"),
    ("Hyun Woo Choi", "100 Haeundaehaebyeon-ro", "Busan", "48093"),
    ("Soo Jin Jung", "25 Dongseong-ro", "Daegu", "41942"),
]


@dataclass
class KakaoPayJobConfig:
    access_token: str
    account_email: str = ""
    local_proxy: str = ""
    kookeey_user: str = ""
    kookeey_pass: str = ""
    kookeey_endpoint: str = "gate.kookeey.info:1000"
    region: str = "KR"
    checkout_region: str = KAKAO_CHECKOUT_COUNTRY
    promotion_region: str = KAKAO_PROMOTION_COUNTRY
    provider_region: str = KAKAO_PROVIDER_COUNTRY
    direct_proxies: list[str] = field(default_factory=list)
    kr_proxies: list[str] = field(default_factory=list)
    vn_proxies: list[str] = field(default_factory=list)
    direct_proxy_label: str = ""
    kr_proxy_label: str = ""
    vn_proxy_label: str = ""
    preflighted_checkout_proxy_url: str = ""
    preflighted_promotion_proxy_url: str = ""
    preflighted_provider_proxy_url: str = ""
    session_token: str = ""
    cookie_header: str = ""
    account_id: str = ""
    device_id: str = ""
    user_agent: str = ""
    accept_language: str = ""
    openai_sentinel_token: str = ""
    oai_client_version: str = ""
    oai_client_build_number: str = ""


def normalize_kakao_proxy_url(value: str) -> str:
    proxy = normalize_paypal_proxy_url(value)
    if proxy.lower().startswith("socks5://"):
        return f"socks5h://{proxy[len('socks5://') :]}"
    return proxy


def kakao_proxy_with_fresh_sid(proxy_url: str, region: str = "KR") -> tuple[str, str]:
    return paypal_proxy_with_fresh_sid(proxy_url, region)


def _normalize_country(value: str, default: str = "KR") -> str:
    country = str(value or default or "KR").strip().upper()
    return country if re.fullmatch(r"[A-Z]{2}", country) else default


def _stage_region(cfg: KakaoPayJobConfig, stage_index: int) -> str:
    if stage_index == 1:
        return _normalize_country(cfg.promotion_region, KAKAO_PROMOTION_COUNTRY)
    if stage_index >= 2:
        return _normalize_country(cfg.provider_region or cfg.region, KAKAO_PROVIDER_COUNTRY)
    return _normalize_country(cfg.checkout_region or cfg.region, KAKAO_CHECKOUT_COUNTRY)


def _proxy_has_region_selector(proxy_url: str) -> bool:
    return bool(re.search(r"[_-]region[-_][A-Z]{2}(?=[:@/?#&-])", str(proxy_url or ""), flags=re.I))


def _align_kakao_proxy_region(proxy_url: str, region: str) -> str:
    target = _normalize_country(region)
    return re.sub(
        r"([_-]region[-_])[A-Z]{2}(?=[:@/?#&-])",
        lambda m: f"{m.group(1)}{target}",
        proxy_url,
        count=1,
        flags=re.I,
    )


def _ipweb_proxy_region(proxy_url: str) -> str:
    match = re.search(r"B_\d+_([A-Z]{2})_(?:[^:@/?#]*_)*[A-Za-z0-9]+(?=[:@/?#])", str(proxy_url or ""), flags=re.I)
    return match.group(1).upper() if match else ""


def _stage_direct_proxy_items(cfg: KakaoPayJobConfig, stage_index: int, region: str) -> tuple[list[str], str]:
    if stage_index == 1:
        raw = cfg.vn_proxies or cfg.direct_proxies
        label = str(cfg.vn_proxy_label or cfg.direct_proxy_label or "").strip()
    else:
        raw = cfg.kr_proxies or cfg.direct_proxies
        label = str(cfg.kr_proxy_label or cfg.direct_proxy_label or "").strip()
    direct = [normalize_kakao_proxy_url(item) for item in (raw or []) if str(item or "").strip()]
    return direct, label or "direct-1"


def _has_direct_proxy_config(cfg: KakaoPayJobConfig) -> bool:
    return bool(cfg.direct_proxies or cfg.kr_proxies or cfg.vn_proxies)


def build_kakao_dynamic_proxy(cfg: KakaoPayJobConfig, stage_index: int) -> tuple[str, str]:
    region = _stage_region(cfg, stage_index)
    preflight_attr = (
        "preflighted_checkout_proxy_url"
        if stage_index == 0
        else ("preflighted_promotion_proxy_url" if stage_index == 1 else "preflighted_provider_proxy_url")
    )
    preflighted = normalize_kakao_proxy_url(getattr(cfg, preflight_attr, ""))
    if preflighted:
        return preflighted, f"preflighted region={region}"
    direct, direct_label = _stage_direct_proxy_items(cfg, stage_index, region)
    if direct:
        ipweb_direct = [item for item in direct if _ipweb_proxy_region(item)]
        if ipweb_direct:
            region_matched = [item for item in ipweb_direct if _ipweb_proxy_region(item) == region]
            candidate = random.choice(region_matched or ipweb_direct)
        else:
            candidate = direct[0]
        proxy, sid = kakao_proxy_with_fresh_sid(candidate, region)
        suffix = f" sid={sid}" if sid and sid != "static" else " static"
        return proxy, f"{direct_label} region={region}{suffix}"
    return build_kookeey_proxy(cfg.kookeey_user, cfg.kookeey_pass, cfg.kookeey_endpoint, region)


def build_kakao_chatgpt_session(
    access_token: str,
    proxy_url: str = "",
    device_id: str = "",
    *,
    session_token: str = "",
    cookie_header: str = "",
    account_id: str = "",
    user_agent: str = "",
    accept_language: str = "",
    openai_sentinel_token: str = "",
    oai_client_version: str = "",
    oai_client_build_number: str = "",
) -> requests.Session:
    session = build_chatgpt_session(access_token, proxy_url, device_id)
    if any(
        str(value or "").strip()
        for value in (
            session_token,
            cookie_header,
            account_id,
            user_agent,
            accept_language,
            openai_sentinel_token,
            oai_client_version,
            oai_client_build_number,
        )
    ):
        configure_chatgpt_http_session(
            session,
            access_token=access_token,
            session_token=session_token,
            cookie_header=cookie_header,
            account_id=account_id,
            device_id=device_id,
            user_agent=user_agent,
            openai_sentinel_token=openai_sentinel_token,
            oai_client_version=oai_client_version,
            oai_client_build_number=oai_client_build_number,
            accept_language=accept_language or "ko-KR,ko;q=0.9,en-US;q=0.8",
        )
    try:
        session.headers.update(
            {
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
                "oai-language": "ko-KR",
                "sec-ch-ua": '"Google Chrome";v="147", "Chromium";v="147", "Not.A/Brand";v="24"',
            }
        )
    except Exception:
        pass
    return session


def _build_kakao_cfg_chatgpt_session(cfg: KakaoPayJobConfig, proxy_url: str, device_id: str) -> requests.Session:
    return build_kakao_chatgpt_session(
        cfg.access_token,
        proxy_url,
        device_id,
        session_token=cfg.session_token,
        cookie_header=cfg.cookie_header,
        account_id=cfg.account_id,
        user_agent=cfg.user_agent,
        accept_language=cfg.accept_language or "ko-KR,ko;q=0.9,en-US;q=0.8",
        openai_sentinel_token=cfg.openai_sentinel_token,
        oai_client_version=cfg.oai_client_version,
        oai_client_build_number=cfg.oai_client_build_number,
    )


def _build_kakao_reference_chatgpt_session(cfg: KakaoPayJobConfig, proxy_url: str, device_id: str) -> requests.Session:
    session = new_http_session(proxy_url)
    configure_chatgpt_http_session(
        session,
        access_token=cfg.access_token,
        session_token=cfg.session_token,
        cookie_header=cfg.cookie_header,
        account_id=cfg.account_id,
        device_id=device_id or cfg.device_id,
        user_agent=cfg.user_agent,
        openai_sentinel_token=cfg.openai_sentinel_token,
        oai_client_version=cfg.oai_client_version,
        oai_client_build_number=cfg.oai_client_build_number,
        accept_language=cfg.accept_language or "ko-KR,ko;q=0.9,en-US;q=0.8",
    )
    try:
        session.headers.update({"oai-language": "ko-KR", "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8"})
    except Exception:
        pass
    return session


def kakao_billing(account_email: str = "") -> dict[str, str]:
    name, line1, city, postal = random.choice(KR_BILLING_PRESETS)
    return {
        "name": name,
        "email": account_email or f"kakao.kr.{random.randint(1000, 9999)}@example.com",
        "country": "KR",
        "line1": line1,
        "city": city,
        "state": "Seoul",
        "postal_code": postal,
    }


def pmt_info(payload: dict[str, Any]) -> tuple[list[Any], list[Any], bool]:
    pmt = payload.get("payment_method_types") or []
    ordered = payload.get("ordered_payment_method_types") or []
    methods = [str(item).lower() for item in list(pmt) + list(ordered)]
    return pmt, ordered, "kakao_pay" in methods


def amount_info(payload: dict[str, Any]) -> str:
    options = payload.get("elements_options") if isinstance(payload.get("elements_options"), dict) else {}
    if options.get("amount") is not None:
        return str(int(options["amount"]))
    total_summary = payload.get("total_summary") if isinstance(payload.get("total_summary"), dict) else {}
    invoice = payload.get("invoice") if isinstance(payload.get("invoice"), dict) else {}
    if total_summary.get("due") is not None:
        return str(total_summary.get("due"))
    if invoice.get("amount_due") is not None:
        return str(invoice.get("amount_due"))
    if invoice.get("total") is not None:
        return str(invoice.get("total"))
    line_items = payload.get("line_items")
    if isinstance(line_items, list):
        amounts = [item.get("amount") for item in line_items if isinstance(item, dict) and item.get("amount") is not None]
        if amounts:
            return str(sum(int(value) for value in amounts))
    return "0"


def currency_info(payload: dict[str, Any]) -> str:
    return str(payload.get("currency") or "").strip().lower()


def is_zero_amount(value: Any) -> bool:
    try:
        return float(str(value or "").strip()) == 0.0
    except Exception:
        return str(value or "").strip() in {"0", "0.0", "0.00"}


def _ctx() -> dict[str, str]:
    return {
        "stripe_js_id": str(uuid.uuid4()),
        "client_session_id": str(uuid.uuid4()),
        "guid": uuid.uuid4().hex,
        "muid": uuid.uuid4().hex,
        "sid": uuid.uuid4().hex,
        "elements_session_id": f"elements_session_{uuid.uuid4().hex[:11]}",
        "elements_session_config_id": str(uuid.uuid4()),
        "config_id": "",
        "init_checksum": "",
    }


def _kakao_elements_params(ctx: dict[str, str], *, include_session: bool = False) -> dict[str, str]:
    params = {
        "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
        "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
        "elements_session_client[elements_init_source]": "custom_checkout",
        "elements_session_client[referrer_host]": "chatgpt.com",
        "elements_session_client[stripe_js_id]": ctx["stripe_js_id"],
        "elements_session_client[locale]": "ko",
        "elements_session_client[is_aggregation_expected]": "false",
        "elements_options_client[saved_payment_method][enable_save]": "auto",
        "elements_options_client[saved_payment_method][enable_redisplay]": "auto",
    }
    if include_session:
        params["elements_session_client[session_id]"] = ctx["elements_session_id"]
    return params


def _sync_ctx_from_init(ctx: dict[str, str], payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        return
    config_id = str(payload.get("config_id") or ctx.get("config_id") or "")
    init_checksum = str(payload.get("init_checksum") or ctx.get("init_checksum") or "")
    ctx["config_id"] = config_id
    ctx["init_checksum"] = init_checksum
    if config_id:
        ctx["elements_session_config_id"] = config_id


def stripe_init(stripe: requests.Session, cs_id: str, stripe_pk: str, ctx: dict[str, str]) -> dict[str, Any]:
    resp = stripe.post(
        f"https://api.stripe.com/v1/payment_pages/{cs_id}/init",
        data={
            "key": stripe_pk,
            "eid": "NA",
            "browser_locale": "ko-KR",
            "browser_timezone": "Asia/Seoul",
            "redirect_type": "url",
            "_stripe_version": KAKAO_STRIPE_VERSION,
            **_kakao_elements_params(ctx),
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"stripe init failed: HTTP {resp.status_code} {short(resp.text)}")
    data = resp.json() or {}
    _sync_ctx_from_init(ctx, data)
    return data


def page_get(stripe: requests.Session, cs_id: str, stripe_pk: str, ctx: dict[str, str]) -> dict[str, Any]:
    resp = stripe.get(
        f"https://api.stripe.com/v1/payment_pages/{cs_id}",
        params={
            "key": stripe_pk,
            "_stripe_version": KAKAO_STRIPE_VERSION,
            **_kakao_elements_params(ctx, include_session=True),
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"payment_pages get failed: HTTP {resp.status_code} {short(resp.text)}")
    return resp.json() or {}


def find_submission_attempt(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    for key in ("submission_attempt", "latest_attempt", "submission"):
        val = payload.get(key)
        if isinstance(val, dict) and val:
            return val
    session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
    val = session.get("submission_attempt")
    return val if isinstance(val, dict) else {}


def _redirect_url(payload: Any) -> tuple[str, str]:
    if isinstance(payload, dict):
        next_action = payload.get("next_action")
        if isinstance(next_action, dict):
            redirect_to_url = next_action.get("redirect_to_url")
            if isinstance(redirect_to_url, dict) and str(redirect_to_url.get("url") or "").strip():
                return str(redirect_to_url.get("url") or "").strip(), str(next_action.get("type") or "")
        for key in ("setup_intent", "payment_intent", "submission_attempt", "latest_attempt", "session"):
            found, action_type = _redirect_url(payload.get(key))
            if found:
                return found, action_type
    if isinstance(payload, list):
        for item in payload:
            found, action_type = _redirect_url(item)
            if found:
                return found, action_type
    return "", ""


def _is_kakao_provider_url(url: str) -> bool:
    try:
        host = (urlsplit(str(url or "")).netloc or "").lower()
    except Exception:
        return False
    return (
        host == "pm-redirects.stripe.com"
        or host.endswith(".pm-redirects.stripe.com")
        or host == "pay.nicepay.co.kr"
        or host.endswith(".nicepay.co.kr")
        or "kakao" in host
    )


def _is_stripe_pm_redirect_url(url: str) -> bool:
    try:
        host = (urlsplit(str(url or "")).netloc or "").lower()
    except Exception:
        return False
    return host == "pm-redirects.stripe.com" or host.endswith(".pm-redirects.stripe.com")


def _is_final_kakao_provider_url(url: str) -> bool:
    try:
        host = (urlsplit(str(url or "")).netloc or "").lower()
    except Exception:
        return False
    return host == "pay.nicepay.co.kr" or host.endswith(".nicepay.co.kr") or ("kakao" in host and not _is_stripe_pm_redirect_url(url))


def find_kakao_redirect_url_string(payload: Any) -> str:
    def normalize_text(value: Any) -> str:
        text = str(value or "").strip().replace("\\/", "/").replace("\\u0026", "&").replace("&amp;", "&")
        try:
            return unquote(text)
        except Exception:
            return text

    def good_url(value: str) -> str:
        text = normalize_text(value)
        candidates = [text]
        candidates.extend(re.findall(r"https?://[^\s\"'<>\\\\]+", text))
        for candidate in candidates:
            candidate = candidate.strip().rstrip("),.;")
            if not candidate.startswith(("http://", "https://")):
                continue
            host = (urlsplit(candidate).netloc or "").lower()
            if (
                host == "pm-redirects.stripe.com"
                or host.endswith(".pm-redirects.stripe.com")
                or host == "pay.nicepay.co.kr"
                or host.endswith(".nicepay.co.kr")
                or "kakao" in host
            ):
                return candidate
        return ""

    if isinstance(payload, str):
        return good_url(payload)
    if isinstance(payload, dict):
        for key in ("url", "redirect_url", "return_url", "hosted_url"):
            found = find_kakao_redirect_url_string(payload.get(key))
            if found:
                return found
        for value in payload.values():
            found = find_kakao_redirect_url_string(value)
            if found:
                return found
    if isinstance(payload, list):
        for value in payload:
            found = find_kakao_redirect_url_string(value)
            if found:
                return found
    return ""


def extract_kakao_result(payload: Any, cs_id: str = "") -> dict[str, str]:
    redirect_url, action_type = _redirect_url(payload)
    if not redirect_url:
        redirect_url = find_kakao_redirect_url_string(payload)
    fields = {
        "kakao_link": "",
        "provider_redirect_url": "",
        "stripe_redirect_url": "",
        "cs_id": cs_id,
        "submission_state": "",
        "next_action_type": action_type,
        "setup_intent": "",
        "payment_intent": "",
        "intent_state": "",
    }
    if redirect_url and _is_kakao_provider_url(redirect_url):
        if _is_stripe_pm_redirect_url(redirect_url):
            fields["stripe_redirect_url"] = redirect_url
        else:
            fields["provider_redirect_url"] = redirect_url
            fields["kakao_link"] = redirect_url
    if isinstance(payload, dict):
        sub = find_submission_attempt(payload)
        fields["submission_state"] = str(sub.get("state") or "")
        for key, dest in (("setup_intent", "setup_intent"), ("payment_intent", "payment_intent")):
            intent = payload.get(key)
            if isinstance(intent, dict):
                fields[dest] = str(intent.get("id") or "")
                fields["intent_state"] = str(intent.get("status") or fields["intent_state"] or "")
    return fields


def is_success(fields: dict[str, Any]) -> bool:
    return _is_kakao_provider_url(str(fields.get("kakao_link") or fields.get("provider_redirect_url") or fields.get("stripe_redirect_url") or ""))


def resolve_kakao_redirect(stripe: requests.Session, redirect_url: str, max_hops: int = 5) -> str:
    current = str(redirect_url or "").strip()
    for _ in range(max(1, int(max_hops or 1))):
        if not current:
            return ""
        host = (urlsplit(current).netloc or "").lower()
        if host.endswith(".nicepay.co.kr") or "kakao" in host:
            return current
        try:
            response = stripe.get(current, allow_redirects=False, timeout=TIMEOUT)
        except Exception:
            return current
        location = str(response.headers.get("Location") or "").strip()
        if not location:
            return current
        current = urljoin(current, location)
    return current


def finalize_kakao_result(stripe: requests.Session, fields: dict[str, Any], *, link_source: str) -> bool:
    candidate = str(fields.get("provider_redirect_url") or fields.get("kakao_link") or fields.get("stripe_redirect_url") or "").strip()
    if not candidate:
        return False
    provider = resolve_kakao_redirect(stripe, candidate)
    if provider and _is_final_kakao_provider_url(provider):
        fields["provider_redirect_url"] = provider
        fields["kakao_link"] = provider
    elif _is_final_kakao_provider_url(candidate):
        fields["provider_redirect_url"] = candidate
        fields["kakao_link"] = candidate
    else:
        return False
    if _is_stripe_pm_redirect_url(candidate):
        fields["stripe_redirect_url"] = candidate
    fields["link_source"] = link_source
    fields["link_binding"] = "chatgpt_checkout_session"
    return True


def kakao_return_url(cs_id: str, hosted_url: str) -> str:
    success_url = f"https://chatgpt.com/backend-api/payments/checkout/openai_llc/{cs_id}/success?billing_country=KR"
    base = hosted_url or f"https://checkout.stripe.com/c/pay/{cs_id}"
    parsed = urlsplit(base)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["returned_from_redirect"] = "true"
    query["ui_mode"] = "custom"
    query["return_url"] = success_url
    return urlunsplit((parsed.scheme or "https", parsed.netloc or "checkout.stripe.com", parsed.path, urlencode(query), parsed.fragment))


def update_kakao_checkout_promotion(
    chatgpt: requests.Session,
    *,
    cs_id: str,
    processor: str,
    promo_id: str = KAKAO_PROMO_ID,
) -> None:
    body: dict[str, Any] = {
        "checkout_session_id": cs_id,
        "processor_entity": processor,
        "plan_name": "chatgptplusplan",
        "price_interval": "month",
        "seat_quantity": 1,
    }
    if promo_id:
        body["promo_campaign"] = {
            "promo_campaign_id": promo_id,
            "is_coupon_from_query_param": False,
        }
    resp = chatgpt.post(
        "https://chatgpt.com/backend-api/payments/checkout/update",
        json=body,
        headers={
            "Referer": f"https://chatgpt.com/checkout/{processor}/{cs_id}",
            "x-openai-target-path": "/backend-api/payments/checkout/update",
            "x-openai-target-route": "/backend-api/payments/checkout/update",
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"checkout/update failed: HTTP {resp.status_code} {short(resp.text)}")
    try:
        payload = resp.json() or {}
    except Exception:
        payload = {}
    if isinstance(payload, dict) and payload.get("success") is False:
        raise RuntimeError(f"checkout/update rejected: {short(payload)}")


def sync_kakao_tax_region(
    chatgpt: requests.Session,
    stripe: requests.Session,
    *,
    cs_id: str,
    stripe_pk: str,
    processor: str,
    checkout_email: str,
    billing: dict[str, str],
    ctx: dict[str, str] | None = None,
) -> None:
    state = str(billing.get("state") or "Seoul").strip() or "Seoul"
    chatgpt.post(
        "https://chatgpt.com/backend-api/payments/checkout/taxes",
        json={
            "checkout_session_id": cs_id,
            "checkout_email": checkout_email,
            "billing_country": "KR",
            "billing_name": billing["name"],
            "currency": "KRW",
            "tax_id": None,
            "processor_entity": processor,
            "billing_address": {
                "line1": billing["line1"],
                "city": billing["city"],
                "country": "KR",
                "postal_code": billing["postal_code"],
                "state": state,
            },
        },
        headers={
            "Referer": f"https://chatgpt.com/checkout/{processor}/{cs_id}",
            "x-openai-target-path": "/backend-api/payments/checkout/taxes",
            "x-openai-target-route": "/backend-api/payments/checkout/taxes",
        },
        timeout=TIMEOUT,
    )
    resp = stripe.post(
        f"https://api.stripe.com/v1/payment_pages/{cs_id}",
        data={
            "key": stripe_pk,
            "_stripe_version": KAKAO_STRIPE_VERSION,
            **(_kakao_elements_params(ctx, include_session=True) if ctx else {"eid": "NA"}),
            "tax_region[country]": "KR",
            "tax_region[postal_code]": billing["postal_code"],
            "tax_region[line1]": billing["line1"],
            "tax_region[city]": billing["city"],
            "tax_region[state]": state,
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"stripe tax_region failed: HTTP {resp.status_code} {short(resp.text)}")


def chatgpt_approve(
    access_token: str,
    cs_id: str,
    processor: str,
    proxy_url: str,
    device_id: str,
    log: LogFn,
    *,
    country: str = "KR",
    cfg: KakaoPayJobConfig | None = None,
) -> None:
    last_err = ""
    for attempt in range(1, 4):
        approve_proxy = proxy_url
        if attempt > 1 and proxy_url:
            approve_proxy, sid = kakao_proxy_with_fresh_sid(proxy_url, country)
            if sid and sid != "static":
                log(f"approve attempt {attempt}: refresh proxy sid={sid}")
        use_reference_context = bool(cfg and (cfg.cookie_header or cfg.session_token or cfg.account_id or cfg.user_agent))
        cg = (
            _build_kakao_reference_chatgpt_session(cfg, approve_proxy, device_id)
            if use_reference_context and cfg
            else (_build_kakao_cfg_chatgpt_session(cfg, approve_proxy, device_id) if cfg else build_kakao_chatgpt_session(access_token, approve_proxy, device_id))
        )
        if not use_reference_context:
            warm_chatgpt_checkout_context(cg, country, log)
        try:
            checkout_url = f"https://chatgpt.com/checkout/{processor}/{cs_id}"
            for url, label in (
                (checkout_url, "chatgpt_checkout"),
                (f"https://pay.openai.com/c/pay/{cs_id}", "pay_openai"),
                (f"https://checkout.stripe.com/c/pay/{cs_id}", "stripe_checkout"),
            ):
                try:
                    hosted_resp = cg.get(url, timeout=12, allow_redirects=False)
                    log(f"hosted_side_effect {label}=HTTP{getattr(hosted_resp, 'status_code', 0)}")
                except Exception as hosted_exc:
                    log(f"hosted_side_effect {label}={type(hosted_exc).__name__}")
            session_headers = getattr(cg, "headers", {}) or {}
            cookie_header = str(session_headers.get("Cookie") or session_headers.get("cookie") or "")
            headers = chatgpt_checkout_headers(
                access_token=access_token,
                checkout_session_id=cs_id,
                processor_entity=processor,
                cookie_header=cookie_header,
                account_id=str((cfg.account_id if cfg else "") or ""),
                device_id=device_id,
                target_path="/backend-api/payments/checkout/approve",
                openai_sentinel_token="",
                sec_ch_ua=str(session_headers.get("sec-ch-ua") or ""),
                sec_ch_ua_platform='"Windows"',
            )
            if cfg and cfg.user_agent:
                headers["user-agent"] = cfg.user_agent
            if callable(_checkout_approval_sentinel_headers):
                try:
                    sentinel_headers = _checkout_approval_sentinel_headers(
                        cookie_header=cookie_header,
                        user_agent=str(headers.get("user-agent") or session_headers.get("User-Agent") or session_headers.get("user-agent") or ""),
                        checkout_url=checkout_url,
                    )
                    headers.update(sentinel_headers)
                    if sentinel_headers.get("OpenAI-Sentinel-Token"):
                        log("approve sentinel_headers=present")
                except Exception as sentinel_exc:
                    log(f"approve sentinel_headers={type(sentinel_exc).__name__}")
            headers.pop("openai-sentinel-token", None)
            try:
                ping = cg.post("https://chatgpt.com/backend-api/sentinel/ping", json={}, timeout=10)
                log(f"approve sentinel_ping=HTTP{getattr(ping, 'status_code', 0)}")
            except Exception as sentinel_ping_exc:
                log(f"approve sentinel_ping={type(sentinel_ping_exc).__name__}")
            resp = cg.post(
                "https://chatgpt.com/backend-api/payments/checkout/approve",
                json={"checkout_session_id": cs_id, "processor_entity": processor},
                headers=headers,
                timeout=TIMEOUT,
            )
            log(f"approve attempt {attempt}: HTTP {resp.status_code} {short(resp.text, 120)}")
            if resp.status_code < 400:
                try:
                    result = (resp.json() or {}).get("result")
                except Exception:
                    result = ""
                if not result or result == "approved":
                    return
                last_err = f"unexpected result: {result!r}"
            else:
                last_err = short(resp.text)
        except Exception as exc:
            last_err = short(exc)
            log(f"approve attempt {attempt} error: {last_err}")
        time.sleep(1.0)
    raise RuntimeError(f"approve failed: {last_err}")


def _confirm_kakao_inline(
    stripe: requests.Session,
    *,
    cs_id: str,
    stripe_pk: str,
    ctx: dict[str, str],
    billing: dict[str, str],
    amount: str,
    return_url: str,
) -> dict[str, Any]:
    pre_confirm_resp = stripe.post(
        f"https://api.stripe.com/v1/payment_pages/{cs_id}/pre_confirm",
        data={
            "eid": str(uuid.uuid4()),
            "payment_method_type": "kakao_pay",
            "key": stripe_pk,
            "_stripe_version": KAKAO_STRIPE_VERSION,
        },
        timeout=TIMEOUT,
    )
    if pre_confirm_resp.status_code >= 400:
        raise RuntimeError(f"pre_confirm failed: HTTP {pre_confirm_resp.status_code} {short(pre_confirm_resp.text)}")

    payment_method_body = {
        "type": "kakao_pay",
        "billing_details[name]": billing["name"],
        "billing_details[email]": billing["email"],
        "billing_details[address][country]": "KR",
        "billing_details[address][line1]": billing["line1"],
        "billing_details[address][line2]": "",
        "billing_details[address][city]": billing["city"],
        "billing_details[address][postal_code]": billing["postal_code"],
        "billing_details[address][state]": billing.get("state") or "",
        "guid": ctx["guid"],
        "muid": ctx["muid"],
        "sid": ctx["sid"],
        "_stripe_version": KAKAO_STRIPE_VERSION,
        "key": stripe_pk,
        "payment_user_agent": KAKAO_STRIPE_PAYMENT_UA,
        "client_attribution_metadata[client_session_id]": ctx["client_session_id"],
        "client_attribution_metadata[checkout_session_id]": cs_id,
        "client_attribution_metadata[merchant_integration_source]": "checkout",
        "client_attribution_metadata[merchant_integration_version]": "custom_checkout",
        "client_attribution_metadata[payment_method_selection_flow]": "merchant_specified",
    }
    if ctx.get("config_id"):
        payment_method_body["client_attribution_metadata[checkout_config_id]"] = ctx["config_id"]
    payment_method_resp = stripe.post("https://api.stripe.com/v1/payment_methods", data=payment_method_body, timeout=TIMEOUT)
    if payment_method_resp.status_code >= 400:
        raise RuntimeError(f"payment method failed: HTTP {payment_method_resp.status_code} {short(payment_method_resp.text)}")
    payment_method_id = str((payment_method_resp.json() or {}).get("id") or "")
    if not payment_method_id.startswith("pm_"):
        raise RuntimeError(f"payment method missing id: {short(payment_method_resp.text)}")

    body = {
        "eid": "NA",
        "guid": ctx["guid"],
        "muid": ctx["muid"],
        "sid": ctx["sid"],
        "payment_method": payment_method_id,
        "init_checksum": ctx["init_checksum"],
        "version": KAKAO_STRIPE_RUNTIME_VERSION,
        "expected_amount": amount,
        "tax_id_collection[purchasing_as_business]": "false",
        "expected_payment_method_type": "kakao_pay",
        "return_url": return_url,
        "client_attribution_metadata[client_session_id]": ctx["client_session_id"],
        "client_attribution_metadata[checkout_session_id]": cs_id,
        "client_attribution_metadata[merchant_integration_source]": "checkout",
        "client_attribution_metadata[merchant_integration_version]": "custom_checkout",
        "client_attribution_metadata[payment_method_selection_flow]": "merchant_specified",
        "link_brand": "link",
        "key": stripe_pk,
        "_stripe_version": KAKAO_STRIPE_VERSION,
        **_kakao_elements_params(ctx, include_session=True),
    }
    if ctx.get("config_id"):
        body["client_attribution_metadata[checkout_config_id]"] = ctx["config_id"]
    resp = stripe.post(f"https://api.stripe.com/v1/payment_pages/{cs_id}/confirm", data=body, timeout=TIMEOUT)
    if resp.status_code >= 400:
        raise RuntimeError(f"confirm failed: HTTP {resp.status_code} {short(resp.text)}")
    return resp.json() or {}


def _checkout_email(init_payload: dict[str, Any], billing: dict[str, str]) -> str:
    customer = init_payload.get("customer") if isinstance(init_payload.get("customer"), dict) else {}
    return str(customer.get("email") or billing.get("email") or "")


def generate_kakao_trial(cfg: KakaoPayJobConfig, log: LogFn | None = None) -> dict[str, Any]:
    log = log or (lambda _m: None)
    token = str(cfg.access_token or "").strip()
    if not token:
        raise RuntimeError("缺少 Access Token")
    if not _has_direct_proxy_config(cfg) and (not cfg.kookeey_user or not cfg.kookeey_pass):
        raise RuntimeError("缺少代理配置：KR/VN 代理池、direct_proxies 或 Kookeey 用户名/密码")

    device_id = str(cfg.device_id or "").strip() or str(uuid.uuid4())
    checkout_region = _stage_region(cfg, 0)
    promotion_region = _stage_region(cfg, 1)
    provider_region = _stage_region(cfg, 2)
    billing = kakao_billing(cfg.account_email)
    log(f"账单: {billing['name']} / {billing['city']} / {billing['postal_code']} / KR")

    dyn1, sid1 = build_kakao_dynamic_proxy(cfg, 0)
    log(f"[1/6] {checkout_region} 创建 KRW Kakao trial checkout sid={sid1}")
    with pix_proxy_context(cfg.local_proxy, dyn1, log) as chain1:
        checkout_proxy_url = chain1.url
        cg = _build_kakao_cfg_chatgpt_session(cfg, checkout_proxy_url, device_id)
        warm_chatgpt_checkout_context(cg, checkout_region, log)
        resp = cg.post(
            "https://chatgpt.com/backend-api/payments/checkout",
            json={
                "entry_point": "all_plans_pricing_modal",
                "plan_name": "chatgptplusplan",
                "billing_details": {"country": checkout_region, "currency": "KRW"},
                "cancel_url": "https://chatgpt.com/#pricing",
                "checkout_ui_mode": "custom",
                "promo_campaign": {
                    "promo_campaign_id": KAKAO_PROMO_ID,
                    "is_coupon_from_query_param": False,
                },
            },
            headers={
                "x-openai-target-path": "/backend-api/payments/checkout",
                "x-openai-target-route": "/backend-api/payments/checkout",
            },
            timeout=TIMEOUT,
        )
        log(f"checkout HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise RuntimeError(f"checkout failed: {short(resp.text)}")
        data = resp.json() or {}
        cs_id = str(data.get("checkout_session_id") or data.get("session_id") or data.get("id") or "")
        if not cs_id.startswith(("cs_", "oaics_")):
            raise RuntimeError(f"checkout missing cs_id: {short(data)}")
        pk = str(data.get("publishable_key") or data.get("public_key") or extract_pk(data) or DEFAULT_STRIPE_PK)
        processor = str(data.get("processor_entity") or "openai_llc")

        ctx = _ctx()
        log(f"[2/6] {checkout_region} Bootstrap Stripe init 验证 Kakao Pay")
        stripe = build_stripe_session(checkout_proxy_url)
        init_payload = stripe_init(stripe, cs_id, pk, ctx)
        _sync_ctx_from_init(ctx, init_payload)
        amount = amount_info(init_payload)
        pmt, ordered, has_kakao = pmt_info(init_payload)
        log(f"Bootstrap 金额={amount} currency={currency_info(init_payload)} 支付方式={pmt} ordered={ordered} has_kakao={has_kakao}")
        if not has_kakao:
            raise RuntimeError(f"未出现 Kakao Pay，pmt={pmt}")

    dyn2, sid2 = build_kakao_dynamic_proxy(cfg, 1)
    log(f"[3/6] {promotion_region} checkout/update 注入 promo sid={sid2}")
    with pix_proxy_context(cfg.local_proxy, dyn2, log) as chain2:
        promotion_proxy_url = chain2.url
        promotion_cg = _build_kakao_cfg_chatgpt_session(cfg, promotion_proxy_url, device_id)
        warm_chatgpt_checkout_context(promotion_cg, promotion_region, log)
        update_kakao_checkout_promotion(
            promotion_cg,
            cs_id=cs_id,
            processor=processor,
            promo_id=KAKAO_PROMO_ID,
        )

    dyn3, sid3 = build_kakao_dynamic_proxy(cfg, 2)
    log(f"[4/6] {provider_region} Stripe refresh 验证 0 KRW + Kakao sid={sid3}")
    with pix_proxy_context(cfg.local_proxy, dyn3, log) as chain3:
        provider_proxy_url = chain3.url
        provider_cg = _build_kakao_cfg_chatgpt_session(cfg, provider_proxy_url, device_id)
        warm_chatgpt_checkout_context(provider_cg, provider_region, log)
        stripe = build_stripe_session(provider_proxy_url)
        init_payload = stripe_init(stripe, cs_id, pk, ctx)
        _sync_ctx_from_init(ctx, init_payload)
        amount = amount_info(init_payload)
        pmt, ordered, has_kakao = pmt_info(init_payload)
        currency = currency_info(init_payload)
        log(f"promo 后金额={amount} currency={currency} 支付方式={pmt} ordered={ordered} has_kakao={has_kakao}")
        if not has_kakao or not is_zero_amount(amount) or currency != "krw":
            raise RuntimeError(f"checkout_not_kakao_trial: stage=post_promo amount={amount} currency={currency} methods={pmt}")

        log(f"[5/6] 同步 {provider_region} checkout/taxes 与 Stripe tax_region")
        sync_kakao_tax_region(
            provider_cg,
            stripe,
            cs_id=cs_id,
            stripe_pk=pk,
            processor=processor,
            checkout_email=_checkout_email(init_payload, billing),
            billing=billing,
            ctx=ctx,
        )
        init_payload = stripe_init(stripe, cs_id, pk, ctx)
        _sync_ctx_from_init(ctx, init_payload)
        amount = amount_info(init_payload)
        pmt, ordered, has_kakao = pmt_info(init_payload)
        currency = currency_info(init_payload)
        log(f"tax_region 后金额={amount} currency={currency} 支付方式={pmt} ordered={ordered} has_kakao={has_kakao}")
        if not has_kakao or not is_zero_amount(amount) or currency != "krw":
            raise RuntimeError(f"checkout_not_kakao_trial: stage=tax_region amount={amount} currency={currency} methods={pmt}")
        hosted = str(init_payload.get("stripe_hosted_url") or "")

        log(f"[6/6] {provider_region} pre_confirm + payment_method + confirm Kakao Pay")
        confirm_payload = _confirm_kakao_inline(
            stripe,
            cs_id=cs_id,
            stripe_pk=pk,
            ctx=ctx,
            billing=billing,
            amount=amount,
            return_url=kakao_return_url(cs_id, hosted),
        )
        fields = extract_kakao_result(confirm_payload, cs_id)
        sub = find_submission_attempt(confirm_payload)
        log(f"confirm submission={sub.get('state')} redirect={bool(fields.get('kakao_link'))}")
        if is_success(fields) and finalize_kakao_result(stripe, fields, link_source="stripe_payment_pages_confirm"):
            fields["amount"] = amount
            fields["post_promo_payment_method_types"] = pmt
            fields["post_promo_ordered_payment_method_types"] = ordered
            fields["payment_method_types"] = pmt
            fields["ordered_payment_method_types"] = ordered
            fields["chatgpt_checkout_url"] = f"https://chatgpt.com/checkout/{processor}/{cs_id}"
            fields["billing"] = billing
            return {"ok": True, "amount": amount, "fields": fields, "billing": billing}

        log(f"{provider_region} approve + {provider_region} poll Kakao Pay")
        chatgpt_approve(token, cs_id, processor, provider_proxy_url, device_id, log, country=provider_region, cfg=cfg)
        last_err: dict[str, Any] = {}
        for i in range(1, 11):
            page_data = page_get(stripe, cs_id, pk, ctx)
            fields = extract_kakao_result(page_data, cs_id)
            sub = find_submission_attempt(page_data)
            err = sub.get("error") if isinstance(sub.get("error"), dict) else {}
            log(f"poll {i}/10 sub={sub.get('state')} err={err.get('code') if err else '-'} success={is_success(fields)}")
            if is_success(fields) and finalize_kakao_result(stripe, fields, link_source="stripe_checkout_approve_poll"):
                fields["amount"] = amount
                fields["post_promo_payment_method_types"] = pmt
                fields["post_promo_ordered_payment_method_types"] = ordered
                fields["payment_method_types"] = pmt
                fields["ordered_payment_method_types"] = ordered
                fields["chatgpt_checkout_url"] = f"https://chatgpt.com/checkout/{processor}/{cs_id}"
                fields["billing"] = billing
                return {"ok": True, "amount": amount, "fields": fields, "billing": billing}
            if sub.get("state") == "failed":
                last_err = err or {}
                raise RuntimeError(f"approve 后失败: {last_err.get('code')}")
            time.sleep(1.0)
        raise RuntimeError("轮询超时，未拿到 Kakao Pay 链接")
