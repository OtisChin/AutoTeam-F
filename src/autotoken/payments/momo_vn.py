"""Vietnam MoMo checkout link extraction core."""

from __future__ import annotations

import random
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests

from autotoken.payments.brazil_pix import (
    DEFAULT_STRIPE_PK,
    TIMEOUT,
    build_kookeey_proxy,
    extract_pk,
    pix_proxy_context,
    short,
)
from autotoken.payments.kakao_pay import (
    amount_info,
    currency_info,
    find_submission_attempt,
    page_get,
    stripe_init,
)
from autotoken.payments.us_paypal import (
    build_chatgpt_session,
    build_stripe_session,
    normalize_paypal_proxy_url,
    paypal_proxy_with_fresh_sid,
    warm_chatgpt_checkout_context,
)

LogFn = Callable[[str], None]
MOMO_COUNTRY = "VN"
MOMO_CURRENCY = "VND"
MOMO_PROMO_ID = "plus-1-month-free"
MOMO_STRIPE_VERSION = "2025-03-31.basil; checkout_server_update_beta=v1; checkout_manual_approval_preview=v1"
MOMO_STRIPE_RUNTIME_VERSION = "c00af4ce81"
MOMO_STRIPE_PAYMENT_UA = f"stripe.js/{MOMO_STRIPE_RUNTIME_VERSION}; stripe-js-v3/{MOMO_STRIPE_RUNTIME_VERSION}; checkout"
MOMO_CHECKOUT_SESSION_PREFIXES = ("cs_", "oaics_")
VN_BILLING_PRESETS = [
    ("Nguyen Van A", "1 Nguyen Hue", "Ho Chi Minh City", "700000", "HCM"),
    ("Tran Thi B", "12 Le Loi", "Ho Chi Minh City", "700000", "HCM"),
    ("Le Minh C", "25 Hai Ba Trung", "Hanoi", "100000", "HN"),
    ("Pham Gia D", "88 Tran Hung Dao", "Da Nang", "550000", "DN"),
]


@dataclass
class MomoVnJobConfig:
    access_token: str
    local_proxy: str = ""
    kookeey_user: str = ""
    kookeey_pass: str = ""
    kookeey_endpoint: str = "gate.kookeey.info:1000"
    region: str = MOMO_COUNTRY
    checkout_region: str = MOMO_COUNTRY
    promotion_region: str = MOMO_COUNTRY
    provider_region: str = MOMO_COUNTRY
    direct_proxies: list[str] = field(default_factory=list)
    preflighted_checkout_proxy_url: str = ""
    preflighted_promotion_proxy_url: str = ""
    preflighted_provider_proxy_url: str = ""
    preflight_result: dict[str, Any] | None = None


def normalize_momo_proxy_url(value: str) -> str:
    proxy = normalize_paypal_proxy_url(value)
    if proxy.lower().startswith("socks5://"):
        return f"socks5h://{proxy[len('socks5://') :]}"
    return proxy


def momo_proxy_with_fresh_sid(proxy_url: str, region: str = MOMO_COUNTRY) -> tuple[str, str]:
    return paypal_proxy_with_fresh_sid(proxy_url, region)


def _normalize_country(value: str, default: str = MOMO_COUNTRY) -> str:
    country = str(value or default).strip().upper()
    return country if re.fullmatch(r"[A-Z]{2}", country) else default


def _stage_region(cfg: MomoVnJobConfig, stage_index: int) -> str:
    if stage_index == 1:
        return _normalize_country(cfg.promotion_region, MOMO_COUNTRY)
    if stage_index >= 2:
        return _normalize_country(cfg.provider_region, MOMO_COUNTRY)
    return _normalize_country(cfg.checkout_region or cfg.region, MOMO_COUNTRY)


def build_momo_dynamic_proxy(cfg: MomoVnJobConfig, stage_index: int) -> tuple[str, str]:
    region = _stage_region(cfg, stage_index)
    preflight_attr = (
        "preflighted_checkout_proxy_url"
        if stage_index == 0
        else ("preflighted_promotion_proxy_url" if stage_index == 1 else "preflighted_provider_proxy_url")
    )
    preflighted = normalize_momo_proxy_url(getattr(cfg, preflight_attr, ""))
    if preflighted:
        return preflighted, f"preflighted region={region}"
    direct = [normalize_momo_proxy_url(item) for item in (cfg.direct_proxies or []) if str(item or "").strip()]
    if direct:
        proxy, sid = momo_proxy_with_fresh_sid(direct[0], region)
        suffix = f" sid={sid}" if sid and sid != "static" else " static"
        return proxy, f"direct-1 region={region}{suffix}"
    return build_kookeey_proxy(cfg.kookeey_user, cfg.kookeey_pass, cfg.kookeey_endpoint, region)


def build_momo_chatgpt_session(access_token: str, proxy_url: str = "", device_id: str = "") -> requests.Session:
    session = build_chatgpt_session(access_token, proxy_url, device_id)
    try:
        session.headers.update({
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8",
            "oai-language": "vi-VN",
            "sec-ch-ua": '"Google Chrome";v="147", "Chromium";v="147", "Not.A/Brand";v="24"',
        })
    except Exception:
        pass
    return session


def momo_billing(account_email: str = "") -> dict[str, str]:
    name, line1, city, postal, state = random.choice(VN_BILLING_PRESETS)
    return {
        "name": name,
        "email": account_email or f"momo.vn.{random.randint(1000, 9999)}@example.com",
        "country": MOMO_COUNTRY,
        "line1": line1,
        "city": city,
        "postal_code": postal,
        "state": state,
    }


def pmt_info(payload: dict[str, Any]) -> tuple[list[Any], list[Any], bool]:
    pmt = payload.get("payment_method_types") or []
    ordered = payload.get("ordered_payment_method_types") or []
    methods = [str(item).lower() for item in list(pmt) + list(ordered)]
    return pmt, ordered, "momo" in methods


def is_zero_amount(value: Any) -> bool:
    try:
        return float(str(value or "").strip()) == 0.0
    except Exception:
        return str(value or "").strip() in {"0", "0.0", "0.00"}


def is_momo_checkout_session_id(value: Any) -> bool:
    return str(value or "").startswith(MOMO_CHECKOUT_SESSION_PREFIXES)


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


def _sync_ctx_from_init(ctx: dict[str, str], payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        return
    config_id = str(payload.get("config_id") or ctx.get("config_id") or "")
    init_checksum = str(payload.get("init_checksum") or ctx.get("init_checksum") or "")
    ctx["config_id"] = config_id
    ctx["init_checksum"] = init_checksum
    if config_id:
        ctx["elements_session_config_id"] = config_id


def _redirect_url(payload: Any) -> tuple[str, str]:
    if not isinstance(payload, dict):
        return "", ""
    action = payload.get("next_action") if isinstance(payload.get("next_action"), dict) else {}
    action_type = str(action.get("type") or "")
    redirect = action.get("redirect_to_url") if isinstance(action.get("redirect_to_url"), dict) else {}
    return str(redirect.get("url") or ""), action_type


def _is_stripe_pm_redirect_url(value: str) -> bool:
    host = (urlsplit(str(value or "")).netloc or "").lower()
    return host.endswith("pm-redirects.stripe.com")


def _is_momo_provider_url(value: str) -> bool:
    host = (urlsplit(str(value or "")).netloc or "").lower()
    return host.endswith("payment.momo.vn") or host.endswith(".momo.vn") or _is_stripe_pm_redirect_url(value)


def _is_final_momo_provider_url(value: str) -> bool:
    host = (urlsplit(str(value or "")).netloc or "").lower()
    return host.endswith("payment.momo.vn") or host.endswith(".momo.vn")


def extract_momo_result(payload: Any, cs_id: str = "") -> dict[str, str]:
    redirect_url, action_type = _redirect_url(payload)
    fields = {
        "momo_link": "",
        "provider_redirect_url": "",
        "stripe_redirect_url": "",
        "cs_id": cs_id,
        "submission_state": "",
        "next_action_type": action_type,
        "setup_intent": "",
        "payment_intent": "",
        "intent_state": "",
    }
    if redirect_url and _is_momo_provider_url(redirect_url):
        if _is_stripe_pm_redirect_url(redirect_url):
            fields["stripe_redirect_url"] = redirect_url
        else:
            fields["provider_redirect_url"] = redirect_url
            fields["momo_link"] = redirect_url
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
    return _is_momo_provider_url(str(fields.get("momo_link") or fields.get("provider_redirect_url") or fields.get("stripe_redirect_url") or ""))


def resolve_momo_redirect(stripe: requests.Session, redirect_url: str, max_hops: int = 3) -> str:
    current = str(redirect_url or "").strip()
    for _ in range(max(1, int(max_hops or 1))):
        if not current:
            return ""
        if _is_final_momo_provider_url(current):
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


def finalize_momo_result(stripe: requests.Session, fields: dict[str, Any], *, link_source: str) -> bool:
    candidate = str(fields.get("provider_redirect_url") or fields.get("momo_link") or fields.get("stripe_redirect_url") or "").strip()
    if not candidate:
        return False
    provider = resolve_momo_redirect(stripe, candidate)
    if provider and _is_final_momo_provider_url(provider):
        fields["provider_redirect_url"] = provider
        fields["momo_link"] = provider
    elif _is_final_momo_provider_url(candidate):
        fields["provider_redirect_url"] = candidate
        fields["momo_link"] = candidate
    else:
        return False
    if _is_stripe_pm_redirect_url(candidate):
        fields["stripe_redirect_url"] = candidate
    fields["link_source"] = link_source
    fields["link_binding"] = "chatgpt_checkout_session"
    return True


def momo_return_url(cs_id: str, hosted_url: str) -> str:
    success_url = f"https://chatgpt.com/backend-api/payments/checkout/openai_llc/{cs_id}/success?billing_country=VN"
    base = hosted_url or f"https://checkout.stripe.com/c/pay/{cs_id}"
    parsed = urlsplit(base)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["returned_from_redirect"] = "true"
    query["ui_mode"] = "custom"
    query["return_url"] = success_url
    return urlunsplit((parsed.scheme or "https", parsed.netloc or "checkout.stripe.com", parsed.path, urlencode(query), parsed.fragment))


def update_momo_checkout_promotion(chatgpt: requests.Session, *, cs_id: str, processor: str, promo_id: str = MOMO_PROMO_ID) -> None:
    body: dict[str, Any] = {
        "checkout_session_id": cs_id,
        "processor_entity": processor,
        "plan_name": "chatgptplusplan",
        "price_interval": "month",
        "seat_quantity": 1,
        "billing_details": {"country": MOMO_COUNTRY, "currency": MOMO_CURRENCY},
    }
    if promo_id:
        body["promo_campaign"] = {"promo_campaign_id": promo_id, "is_coupon_from_query_param": False}
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


def sync_momo_tax_region(
    chatgpt: requests.Session,
    stripe: requests.Session,
    *,
    cs_id: str,
    stripe_pk: str,
    processor: str,
    checkout_email: str,
    billing: dict[str, str],
) -> None:
    chatgpt.post(
        "https://chatgpt.com/backend-api/payments/checkout/taxes",
        json={
            "checkout_session_id": cs_id,
            "checkout_email": checkout_email,
            "billing_country": MOMO_COUNTRY,
            "billing_name": billing["name"],
            "currency": MOMO_CURRENCY,
            "tax_id": None,
            "processor_entity": processor,
            "billing_address": {
                "line1": billing["line1"],
                "city": billing["city"],
                "country": MOMO_COUNTRY,
                "postal_code": billing["postal_code"],
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
            "eid": "NA",
            "tax_region[country]": MOMO_COUNTRY,
            "tax_region[postal_code]": billing["postal_code"],
            "tax_region[line1]": billing["line1"],
            "tax_region[city]": billing["city"],
            "key": stripe_pk,
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
    country: str = MOMO_COUNTRY,
) -> None:
    cg = build_momo_chatgpt_session(access_token, proxy_url, device_id)
    warm_chatgpt_checkout_context(cg, country, log)
    last_err = ""
    for attempt in range(1, 4):
        try:
            resp = cg.post(
                "https://chatgpt.com/backend-api/payments/checkout/approve",
                json={"checkout_session_id": cs_id, "processor_entity": processor},
                headers={
                    "Referer": f"https://chatgpt.com/checkout/{processor}/{cs_id}",
                    "x-openai-target-path": "/backend-api/payments/checkout/approve",
                    "x-openai-target-route": "/backend-api/payments/checkout/approve",
                },
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


def _confirm_momo_inline(
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
            "payment_method_type": "momo",
            "key": stripe_pk,
            "_stripe_version": MOMO_STRIPE_VERSION,
        },
        timeout=TIMEOUT,
    )
    if pre_confirm_resp.status_code >= 400:
        raise RuntimeError(f"pre_confirm failed: HTTP {pre_confirm_resp.status_code} {short(pre_confirm_resp.text)}")
    payment_method_resp = stripe.post(
        "https://api.stripe.com/v1/payment_methods",
        data={
            "type": "momo",
            "billing_details[name]": billing["name"],
            "billing_details[email]": billing["email"],
            "billing_details[address][country]": MOMO_COUNTRY,
            "billing_details[address][line1]": billing["line1"],
            "billing_details[address][city]": billing["city"],
            "billing_details[address][postal_code]": billing["postal_code"],
            "billing_details[address][state]": billing.get("state") or "",
            "guid": ctx["guid"],
            "muid": ctx["muid"],
            "sid": ctx["sid"],
            "_stripe_version": MOMO_STRIPE_VERSION,
            "key": stripe_pk,
            "payment_user_agent": MOMO_STRIPE_PAYMENT_UA,
            "client_attribution_metadata[client_session_id]": ctx["client_session_id"],
            "client_attribution_metadata[checkout_session_id]": cs_id,
            "client_attribution_metadata[merchant_integration_source]": "checkout",
            "client_attribution_metadata[merchant_integration_version]": "custom_checkout",
            "client_attribution_metadata[payment_method_selection_flow]": "merchant_specified",
            "client_attribution_metadata[checkout_config_id]": ctx.get("config_id") or "",
        },
        timeout=TIMEOUT,
    )
    if payment_method_resp.status_code >= 400:
        raise RuntimeError(f"payment method failed: HTTP {payment_method_resp.status_code} {short(payment_method_resp.text)}")
    payment_method_id = str((payment_method_resp.json() or {}).get("id") or "")
    if not payment_method_id.startswith("pm_"):
        raise RuntimeError(f"payment method missing id: {short(payment_method_resp.text)}")
    resp = stripe.post(
        f"https://api.stripe.com/v1/payment_pages/{cs_id}/confirm",
        data={
            "eid": "NA",
            "guid": ctx["guid"],
            "muid": ctx["muid"],
            "sid": ctx["sid"],
            "payment_method": payment_method_id,
            "init_checksum": ctx["init_checksum"],
            "version": MOMO_STRIPE_RUNTIME_VERSION,
            "expected_amount": amount,
            "expected_payment_method_type": "momo",
            "return_url": return_url,
            "client_attribution_metadata[client_session_id]": ctx["client_session_id"],
            "client_attribution_metadata[checkout_session_id]": cs_id,
            "client_attribution_metadata[checkout_config_id]": ctx.get("config_id") or "",
            "client_attribution_metadata[merchant_integration_source]": "checkout",
            "client_attribution_metadata[merchant_integration_version]": "custom_checkout",
            "client_attribution_metadata[payment_method_selection_flow]": "merchant_specified",
            "key": stripe_pk,
            "_stripe_version": MOMO_STRIPE_VERSION,
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"confirm failed: HTTP {resp.status_code} {short(resp.text)}")
    return resp.json() or {}


def _checkout_email(init_payload: dict[str, Any], billing: dict[str, str]) -> str:
    customer = init_payload.get("customer") if isinstance(init_payload.get("customer"), dict) else {}
    return str(customer.get("email") or billing.get("email") or "")


def detect_momo_eligibility(cfg: MomoVnJobConfig, log: LogFn | None = None) -> dict[str, Any]:
    log = log or (lambda _m: None)
    token = str(cfg.access_token or "").strip()
    if not token:
        raise RuntimeError("缺少 Access Token")
    if not cfg.direct_proxies and (not cfg.kookeey_user or not cfg.kookeey_pass):
        raise RuntimeError("缺少代理配置：direct_proxies 或 Kookeey 用户名/密码")

    device_id = str(uuid.uuid4())
    billing = momo_billing()
    dyn1, sid1 = build_momo_dynamic_proxy(cfg, 0)
    log(f"[1/2] VN 创建 VND checkout 检测 MoMo sid={sid1}")
    with pix_proxy_context(cfg.local_proxy, dyn1, log) as chain1:
        checkout_proxy_url = chain1.url
        cg = build_momo_chatgpt_session(token, checkout_proxy_url, device_id)
        warm_chatgpt_checkout_context(cg, MOMO_COUNTRY, log)
        resp = cg.post(
            "https://chatgpt.com/backend-api/payments/checkout",
            json={
                "entry_point": "all_plans_pricing_modal",
                "plan_name": "chatgptplusplan",
                "billing_details": {"country": MOMO_COUNTRY, "currency": MOMO_CURRENCY},
                "cancel_url": "https://chatgpt.com/#pricing",
                "checkout_ui_mode": "custom",
            },
            headers={
                "x-openai-target-path": "/backend-api/payments/checkout",
                "x-openai-target-route": "/backend-api/payments/checkout",
            },
            timeout=TIMEOUT,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"checkout failed: {short(resp.text)}")
        data = resp.json() or {}
        cs_id = str(data.get("checkout_session_id") or data.get("session_id") or data.get("id") or "")
        if not is_momo_checkout_session_id(cs_id):
            raise RuntimeError(f"checkout missing cs_id: {short(data)}")
        pk = str(data.get("publishable_key") or data.get("public_key") or extract_pk(data) or DEFAULT_STRIPE_PK)
        processor = str(data.get("processor_entity") or "openai_llc")
        ctx = _ctx()
        stripe = build_stripe_session(checkout_proxy_url)
        init_payload = stripe_init(stripe, cs_id, pk, ctx)
        _sync_ctx_from_init(ctx, init_payload)
        amount = amount_info(init_payload)
        currency = currency_info(init_payload)
        pmt, ordered, has_momo = pmt_info(init_payload)
        status = "eligible" if has_momo else "ineligible"
        log(f"[2/2] eligibility 金额={amount} currency={currency} pmt={pmt} ordered={ordered} has_momo={has_momo}")
        return {
            "ok": True,
            "status": status,
            "has_momo": has_momo,
            "amount": amount,
            "currency": currency,
            "cs_id": cs_id,
            "processor": processor,
            "stripe_pk": pk,
            "device_id": device_id,
            "checkout_proxy_url": checkout_proxy_url,
            "promotion_proxy_url": checkout_proxy_url,
            "provider_proxy_url": checkout_proxy_url,
            "payment_method_types": pmt,
            "ordered_payment_method_types": ordered,
            "billing": billing,
            "ctx": ctx,
        }


def generate_momo_vn_trial(cfg: MomoVnJobConfig, log: LogFn | None = None) -> dict[str, Any]:
    log = log or (lambda _m: None)
    token = str(cfg.access_token or "").strip()
    if not token:
        raise RuntimeError("缺少 Access Token")
    eligibility = cfg.preflight_result or detect_momo_eligibility(cfg, log)
    if str(eligibility.get("status") or "").lower() != "eligible" or not eligibility.get("has_momo"):
        raise RuntimeError("无 MoMo 资格")

    cs_id = str(eligibility.get("cs_id") or "")
    if not is_momo_checkout_session_id(cs_id):
        raise RuntimeError("资格检测缺少 checkout session")
    processor = str(eligibility.get("processor") or "openai_llc")
    stripe_pk = str(eligibility.get("stripe_pk") or DEFAULT_STRIPE_PK)
    device_id = str(eligibility.get("device_id") or uuid.uuid4())
    billing = dict(eligibility.get("billing") or momo_billing())
    ctx = dict(eligibility.get("ctx") or _ctx())

    dyn2, sid2 = build_momo_dynamic_proxy(cfg, 1)
    log(f"[1/4] VN checkout/update 注入 promo sid={sid2}")
    with pix_proxy_context(cfg.local_proxy, dyn2, log) as chain2:
        promotion_proxy_url = chain2.url
        promotion_cg = build_momo_chatgpt_session(token, promotion_proxy_url, device_id)
        warm_chatgpt_checkout_context(promotion_cg, MOMO_COUNTRY, log)
        update_momo_checkout_promotion(promotion_cg, cs_id=cs_id, processor=processor)

    dyn3, sid3 = build_momo_dynamic_proxy(cfg, 2)
    log(f"[2/4] VN Stripe refresh 验证 0 VND + MoMo sid={sid3}")
    with pix_proxy_context(cfg.local_proxy, dyn3, log) as chain3:
        provider_proxy_url = chain3.url
        provider_cg = build_momo_chatgpt_session(token, provider_proxy_url, device_id)
        warm_chatgpt_checkout_context(provider_cg, MOMO_COUNTRY, log)
        stripe = build_stripe_session(provider_proxy_url)
        init_payload = stripe_init(stripe, cs_id, stripe_pk, ctx)
        _sync_ctx_from_init(ctx, init_payload)
        amount = amount_info(init_payload)
        currency = currency_info(init_payload)
        pmt, ordered, has_momo = pmt_info(init_payload)
        log(f"promo 后金额={amount} currency={currency} 支付方式={pmt} ordered={ordered} has_momo={has_momo}")
        if not has_momo:
            raise RuntimeError(f"promo 后未出现 MoMo，pmt={pmt}")
        if not is_zero_amount(amount):
            raise RuntimeError(f"套 promo 后金额不是 0: {amount}")
        if currency and currency != "vnd":
            raise RuntimeError(f"套 promo 后币种不是 VND: {currency}")

        log("[3/4] 同步 VN taxes / Stripe tax_region")
        sync_momo_tax_region(
            provider_cg,
            stripe,
            cs_id=cs_id,
            stripe_pk=stripe_pk,
            processor=processor,
            checkout_email=_checkout_email(init_payload, billing),
            billing=billing,
        )
        init_payload = stripe_init(stripe, cs_id, stripe_pk, ctx)
        _sync_ctx_from_init(ctx, init_payload)
        amount = amount_info(init_payload)
        currency = currency_info(init_payload)
        pmt, ordered, has_momo = pmt_info(init_payload)
        log(f"tax_region 后金额={amount} currency={currency} 支付方式={pmt} ordered={ordered} has_momo={has_momo}")
        if not has_momo:
            raise RuntimeError(f"tax sync 后未出现 MoMo，pmt={pmt}")
        if not is_zero_amount(amount):
            raise RuntimeError(f"tax sync 后金额不是 0: {amount}")
        if currency and currency != "vnd":
            raise RuntimeError(f"tax sync 后币种不是 VND: {currency}")

        hosted = str(init_payload.get("stripe_hosted_url") or "")
        log("[4/4] pre_confirm + payment_method + confirm MoMo")
        confirm_payload = _confirm_momo_inline(
            stripe,
            cs_id=cs_id,
            stripe_pk=stripe_pk,
            ctx=ctx,
            billing=billing,
            amount=amount,
            return_url=momo_return_url(cs_id, hosted),
        )
        fields = extract_momo_result(confirm_payload, cs_id)
        sub = find_submission_attempt(confirm_payload)
        log(f"confirm submission={sub.get('state')} redirect={bool(fields.get('momo_link') or fields.get('stripe_redirect_url'))}")
        if (
            str(sub.get("state") or "").strip().lower() not in {"requires_approval", "processing"}
            and is_success(fields)
            and finalize_momo_result(stripe, fields, link_source="stripe_payment_pages_confirm")
        ):
            fields["amount"] = amount
            fields["payment_method_types"] = pmt
            fields["ordered_payment_method_types"] = ordered
            fields["chatgpt_checkout_url"] = f"https://chatgpt.com/checkout/{processor}/{cs_id}"
            fields["billing"] = billing
            return {"ok": True, "amount": amount, "fields": fields, "billing": billing}

        log("VN approve + poll MoMo")
        chatgpt_approve(token, cs_id, processor, provider_proxy_url, device_id, log, country=MOMO_COUNTRY)
        for i in range(1, 20):
            page_data = page_get(stripe, cs_id, stripe_pk, ctx)
            fields = extract_momo_result(page_data, cs_id)
            sub = find_submission_attempt(page_data)
            err = sub.get("error") if isinstance(sub.get("error"), dict) else {}
            log(f"poll {i}/19 sub={sub.get('state')} err={err.get('code') if err else '-'} success={is_success(fields)}")
            if is_success(fields) and finalize_momo_result(stripe, fields, link_source="stripe_checkout_approve_poll"):
                fields["amount"] = amount
                fields["payment_method_types"] = pmt
                fields["ordered_payment_method_types"] = ordered
                fields["chatgpt_checkout_url"] = f"https://chatgpt.com/checkout/{processor}/{cs_id}"
                fields["billing"] = billing
                return {"ok": True, "amount": amount, "fields": fields, "billing": billing}
            if sub.get("state") == "failed":
                raise RuntimeError(f"approve 后失败: {err.get('code')}")
            time.sleep(1.0)
        raise RuntimeError("轮询超时，未拿到 MoMo 链接")
