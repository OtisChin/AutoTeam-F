"""Korea Kakao Pay checkout link extraction core."""

from __future__ import annotations

import random
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
    to_openai_pay_url,
)
from autotoken.payments.us_paypal import (
    PAYPAL_STRIPE_RUNTIME_VERSION,
    PAYPAL_STRIPE_VERSION,
    build_chatgpt_session,
    build_stripe_session,
    normalize_paypal_proxy_url,
    page_get,
    paypal_proxy_with_fresh_sid,
    stripe_init,
    warm_chatgpt_checkout_context,
)

LogFn = Callable[[str], None]

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
    local_proxy: str = ""
    kookeey_user: str = ""
    kookeey_pass: str = ""
    kookeey_endpoint: str = "gate.kookeey.info:1000"
    region: str = "KR"
    direct_proxies: list[str] = field(default_factory=list)
    preflighted_checkout_proxy_url: str = ""


def normalize_kakao_proxy_url(value: str) -> str:
    return normalize_paypal_proxy_url(value)


def kakao_proxy_with_fresh_sid(proxy_url: str, region: str = "KR") -> tuple[str, str]:
    return paypal_proxy_with_fresh_sid(proxy_url, region)


def build_kakao_dynamic_proxy(cfg: KakaoPayJobConfig, stage_index: int) -> tuple[str, str]:
    region = str(cfg.region or "KR").strip().upper() or "KR"
    preflighted = normalize_kakao_proxy_url(getattr(cfg, "preflighted_checkout_proxy_url", ""))
    if stage_index == 0 and preflighted:
        return preflighted, f"preflighted region={region}"
    direct = [normalize_kakao_proxy_url(item) for item in (cfg.direct_proxies or []) if str(item or "").strip()]
    if direct:
        idx = stage_index % len(direct)
        proxy, sid = kakao_proxy_with_fresh_sid(direct[idx], region)
        suffix = f" sid={sid}" if sid and sid != "static" else " static"
        return proxy, f"direct-{idx + 1} region={region}{suffix}"
    return build_kookeey_proxy(cfg.kookeey_user, cfg.kookeey_pass, cfg.kookeey_endpoint, region)


def kakao_billing(account_email: str = "") -> dict[str, str]:
    name, line1, city, postal = random.choice(KR_BILLING_PRESETS)
    return {
        "name": name,
        "email": account_email or f"kakao.kr.{random.randint(1000, 9999)}@example.com",
        "country": "KR",
        "line1": line1,
        "city": city,
        "postal_code": postal,
    }


def pmt_info(payload: dict[str, Any]) -> tuple[list[Any], list[Any], bool]:
    pmt = payload.get("payment_method_types") or []
    ordered = payload.get("ordered_payment_method_types") or []
    methods = [str(item).lower() for item in list(pmt) + list(ordered)]
    return pmt, ordered, "kakao_pay" in methods


def amount_info(payload: dict[str, Any]) -> str:
    total_summary = payload.get("total_summary") if isinstance(payload.get("total_summary"), dict) else {}
    invoice = payload.get("invoice") if isinstance(payload.get("invoice"), dict) else {}
    if total_summary.get("due") is not None:
        return str(total_summary.get("due"))
    if invoice.get("amount_due") is not None:
        return str(invoice.get("amount_due"))
    return "0"


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


def extract_kakao_result(payload: Any, cs_id: str = "") -> dict[str, str]:
    redirect_url, action_type = _redirect_url(payload)
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
        fields["kakao_link"] = redirect_url
        host = (urlsplit(redirect_url).netloc or "").lower()
        if host == "pm-redirects.stripe.com" or host.endswith(".pm-redirects.stripe.com"):
            fields["stripe_redirect_url"] = redirect_url
        else:
            fields["provider_redirect_url"] = redirect_url
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


def resolve_kakao_redirect(stripe: requests.Session, redirect_url: str, max_hops: int = 3) -> str:
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
    candidate = str(fields.get("kakao_link") or fields.get("provider_redirect_url") or fields.get("stripe_redirect_url") or "").strip()
    if not candidate:
        return False
    provider = resolve_kakao_redirect(stripe, candidate)
    if provider and _is_kakao_provider_url(provider):
        fields["provider_redirect_url"] = provider
    fields["kakao_link"] = candidate
    fields["link_source"] = link_source
    fields["link_binding"] = "chatgpt_checkout_session"
    return True


def kakao_return_url(cs_id: str, hosted_url: str) -> str:
    base = to_openai_pay_url(hosted_url) or hosted_url or f"https://pay.openai.com/c/pay/{cs_id}"
    parsed = urlsplit(base)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["redirect_pm_type"] = "kakao_pay"
    query["lid"] = str(uuid.uuid4())
    query["ui_mode"] = "custom"
    return urlunsplit((parsed.scheme or "https", parsed.netloc or "pay.openai.com", parsed.path, urlencode(query), parsed.fragment))


def sync_kakao_tax_region(
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
            "tax_region[country]": "KR",
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
    country: str = "KR",
) -> None:
    cg = build_chatgpt_session(access_token, proxy_url, device_id)
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
    body = {
        "guid": ctx["guid"],
        "muid": ctx["muid"],
        "sid": ctx["sid"],
        "payment_method_data[type]": "kakao_pay",
        "init_checksum": ctx["init_checksum"],
        "version": PAYPAL_STRIPE_RUNTIME_VERSION,
        "expected_amount": amount,
        "expected_payment_method_type": "kakao_pay",
        "return_url": return_url,
        "elements_session_client[session_id]": ctx["elements_session_id"],
        "elements_session_client[locale]": "ko-KR",
        "elements_session_client[referrer_host]": "chatgpt.com",
        "elements_session_client[is_aggregation_expected]": "false",
        "elements_session_client[elements_init_source]": "custom_checkout",
        "elements_session_client[stripe_js_id]": ctx["stripe_js_id"],
        "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
        "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
        "elements_options_client[saved_payment_method][enable_save]": "never",
        "elements_options_client[saved_payment_method][enable_redisplay]": "never",
        "client_attribution_metadata[client_session_id]": ctx["stripe_js_id"],
        "client_attribution_metadata[checkout_session_id]": cs_id,
        "client_attribution_metadata[checkout_config_id]": ctx["config_id"],
        "client_attribution_metadata[elements_session_id]": ctx["elements_session_id"],
        "client_attribution_metadata[elements_session_config_id]": ctx["elements_session_config_id"],
        "client_attribution_metadata[merchant_integration_source]": "checkout",
        "client_attribution_metadata[merchant_integration_subtype]": "payment-element",
        "client_attribution_metadata[merchant_integration_version]": "custom",
        "client_attribution_metadata[payment_intent_creation_flow]": "deferred",
        "client_attribution_metadata[payment_method_selection_flow]": "automatic",
        "client_attribution_metadata[merchant_integration_additional_elements][0]": "payment",
        "client_attribution_metadata[merchant_integration_additional_elements][1]": "address",
        "payment_method_data[billing_details][name]": billing["name"],
        "payment_method_data[billing_details][email]": billing["email"],
        "payment_method_data[billing_details][address][country]": "KR",
        "payment_method_data[billing_details][address][line1]": billing["line1"],
        "payment_method_data[billing_details][address][city]": billing["city"],
        "payment_method_data[billing_details][address][postal_code]": billing["postal_code"],
        "consent[terms_of_service]": "accepted",
        "key": stripe_pk,
        "_stripe_version": PAYPAL_STRIPE_VERSION,
    }
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
    if not cfg.direct_proxies and (not cfg.kookeey_user or not cfg.kookeey_pass):
        raise RuntimeError("缺少代理配置：direct_proxies 或 Kookeey 用户名/密码")

    device_id = str(uuid.uuid4())
    billing = kakao_billing()
    log(f"账单: {billing['name']} / {billing['city']} / {billing['postal_code']} / KR")

    dyn1, sid1 = build_kakao_dynamic_proxy(cfg, 0)
    log(f"[1/5] KR 创建 checkout sid={sid1}")
    with pix_proxy_context(cfg.local_proxy, dyn1, log) as chain:
        proxy_url = chain.url
        cg = build_chatgpt_session(token, proxy_url, device_id)
        warm_chatgpt_checkout_context(cg, "KR", log)
        resp = cg.post(
            "https://chatgpt.com/backend-api/payments/checkout",
            json={
                "entry_point": "all_plans_pricing_modal",
                "plan_name": "chatgptplusplan",
                "billing_details": {"country": "KR", "currency": "KRW"},
                "checkout_ui_mode": "custom",
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
        if not cs_id.startswith("cs_"):
            raise RuntimeError(f"checkout missing cs_id: {short(data)}")
        pk = extract_pk(data) or DEFAULT_STRIPE_PK
        processor = str(data.get("processor_entity") or "openai_llc")

        log("[2/5] Stripe init 验证 Kakao Pay")
        stripe = build_stripe_session(proxy_url)
        ctx = _ctx()
        init_payload = stripe_init(stripe, cs_id, pk, ctx)
        amount = amount_info(init_payload)
        pmt, ordered, has_kakao = pmt_info(init_payload)
        log(f"初始金额={amount} 支付方式={pmt} ordered={ordered} has_kakao={has_kakao}")
        if not has_kakao:
            raise RuntimeError(f"未出现 Kakao Pay，pmt={pmt}")

        log("[3/5] 同步 KR tax_region")
        sync_kakao_tax_region(
            cg,
            stripe,
            cs_id=cs_id,
            stripe_pk=pk,
            processor=processor,
            checkout_email=_checkout_email(init_payload, billing),
            billing=billing,
        )
        init_payload = stripe_init(stripe, cs_id, pk, ctx)
        amount = amount_info(init_payload)
        pmt, ordered, has_kakao = pmt_info(init_payload)
        log(f"tax_region 后金额={amount} 支付方式={pmt} ordered={ordered} has_kakao={has_kakao}")
        if not has_kakao:
            raise RuntimeError(f"tax_region 后 Kakao Pay 丢失，pmt={pmt}")
        hosted = str(init_payload.get("stripe_hosted_url") or "")

        log("[4/5] inline confirm Kakao Pay")
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
            fields["payment_method_types"] = pmt
            fields["ordered_payment_method_types"] = ordered
            fields["chatgpt_checkout_url"] = f"https://chatgpt.com/checkout/{processor}/{cs_id}"
            fields["billing"] = billing
            return {"ok": True, "amount": amount, "fields": fields, "billing": billing}

        log("[5/5] approve + poll Kakao Pay")
        chatgpt_approve(token, cs_id, processor, proxy_url, device_id, log, country="KR")
        last_err: dict[str, Any] = {}
        for i in range(1, 20):
            page_data = page_get(stripe, cs_id, pk, ctx)
            fields = extract_kakao_result(page_data, cs_id)
            sub = find_submission_attempt(page_data)
            err = sub.get("error") if isinstance(sub.get("error"), dict) else {}
            log(f"poll {i}/19 sub={sub.get('state')} err={err.get('code') if err else '-'} success={is_success(fields)}")
            if is_success(fields) and finalize_kakao_result(stripe, fields, link_source="stripe_checkout_approve_poll"):
                fields["amount"] = amount
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
