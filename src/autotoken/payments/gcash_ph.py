"""Philippines GCash checkout link extraction core."""

from __future__ import annotations

import json
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
)
from autotoken.payments.us_paypal import (
    build_chatgpt_session,
    build_stripe_session,
    normalize_paypal_proxy_url,
    paypal_proxy_with_fresh_sid,
    warm_chatgpt_checkout_context,
)

LogFn = Callable[[str], None]
GCASH_COUNTRY = "PH"
GCASH_PROMOTION_COUNTRY = "PH"
GCASH_CURRENCY = "PHP"
GCASH_PROMO_ID = "plus-1-month-free"
GCASH_STRIPE_VERSION = "2025-03-31.basil; checkout_server_update_beta=v1; checkout_manual_approval_preview=v1"
GCASH_STRIPE_RUNTIME_VERSION = "c00af4ce81"
GCASH_STRIPE_PAYMENT_UA = f"stripe.js/{GCASH_STRIPE_RUNTIME_VERSION}; stripe-js-v3/{GCASH_STRIPE_RUNTIME_VERSION}; checkout"
GCASH_CHECKOUT_SESSION_PREFIXES = ("cs_", "oaics_")
PH_BILLING_PRESETS = [
    ("Juan Dela Cruz", "6819 Ayala Avenue", "Makati", "1226", "Metro Manila"),
    ("Maria Santos", "Ortigas Center", "Pasig", "1605", "Metro Manila"),
    ("Jose Reyes", "Osmena Boulevard", "Cebu City", "6000", "Cebu"),
    ("Ana Garcia", "Roxas Boulevard", "Manila", "1000", "Metro Manila"),
]


@dataclass
class GCashPhJobConfig:
    access_token: str
    local_proxy: str = ""
    kookeey_user: str = ""
    kookeey_pass: str = ""
    kookeey_endpoint: str = "gate.kookeey.info:1000"
    region: str = GCASH_COUNTRY
    checkout_region: str = GCASH_COUNTRY
    promotion_region: str = GCASH_PROMOTION_COUNTRY
    provider_region: str = GCASH_COUNTRY
    direct_proxies: list[str] = field(default_factory=list)
    preflighted_checkout_proxy_url: str = ""
    preflighted_promotion_proxy_url: str = ""
    preflighted_provider_proxy_url: str = ""
    preflight_result: dict[str, Any] | None = None
    front_promo: bool = False


def normalize_gcash_proxy_url(value: str) -> str:
    proxy = normalize_paypal_proxy_url(value)
    if proxy.lower().startswith("socks5://"):
        return f"socks5h://{proxy[len('socks5://') :]}"
    return proxy


def gcash_proxy_with_fresh_sid(proxy_url: str, region: str = GCASH_COUNTRY) -> tuple[str, str]:
    return paypal_proxy_with_fresh_sid(proxy_url, region)


def _normalize_country(value: str, default: str = GCASH_COUNTRY) -> str:
    country = str(value or default).strip().upper()
    return country if re.fullmatch(r"[A-Z]{2}", country) else default


def _stage_region(cfg: GCashPhJobConfig, stage_index: int) -> str:
    if stage_index == 1:
        return _normalize_country(cfg.promotion_region, GCASH_PROMOTION_COUNTRY)
    if stage_index >= 2:
        return _normalize_country(cfg.provider_region, GCASH_COUNTRY)
    return _normalize_country(cfg.checkout_region or cfg.region, GCASH_COUNTRY)


def build_gcash_dynamic_proxy(cfg: GCashPhJobConfig, stage_index: int) -> tuple[str, str]:
    region = _stage_region(cfg, stage_index)
    preflight_attr = (
        "preflighted_checkout_proxy_url"
        if stage_index == 0
        else ("preflighted_promotion_proxy_url" if stage_index == 1 else "preflighted_provider_proxy_url")
    )
    preflighted = normalize_gcash_proxy_url(getattr(cfg, preflight_attr, ""))
    if preflighted:
        return preflighted, f"preflighted region={region}"
    direct = [normalize_gcash_proxy_url(item) for item in (cfg.direct_proxies or []) if str(item or "").strip()]
    if direct:
        proxy, sid = gcash_proxy_with_fresh_sid(direct[0], region)
        suffix = f" sid={sid}" if sid and sid != "static" else " static"
        return proxy, f"direct-1 region={region}{suffix}"
    return build_kookeey_proxy(cfg.kookeey_user, cfg.kookeey_pass, cfg.kookeey_endpoint, region)


def build_gcash_chatgpt_session(access_token: str, proxy_url: str = "", device_id: str = "") -> requests.Session:
    session = build_chatgpt_session(access_token, proxy_url, device_id)
    try:
        session.headers.update({
            "Accept-Language": "en-PH,en;q=0.9,en-US;q=0.8",
            "oai-language": "en-PH",
            "sec-ch-ua": '"Google Chrome";v="147", "Chromium";v="147", "Not.A/Brand";v="24"',
        })
    except Exception:
        pass
    return session


def gcash_billing(account_email: str = "") -> dict[str, str]:
    name, line1, city, postal, state = random.choice(PH_BILLING_PRESETS)
    return {
        "name": name,
        "email": account_email or f"gcash.ph.{random.randint(1000, 9999)}@example.com",
        "country": GCASH_COUNTRY,
        "line1": line1,
        "city": city,
        "postal_code": postal,
        "state": state,
    }


def pmt_info(payload: dict[str, Any]) -> tuple[list[Any], list[Any], bool]:
    pmt = payload.get("payment_method_types") or []
    ordered = payload.get("ordered_payment_method_types") or []
    methods = [str(item).lower() for item in list(pmt) + list(ordered)]
    return pmt, ordered, "gcash" in methods


def is_zero_amount(value: Any) -> bool:
    try:
        return float(str(value or "").strip()) == 0.0
    except Exception:
        return str(value or "").strip() in {"0", "0.0", "0.00"}


def is_gcash_checkout_session_id(value: Any) -> bool:
    return str(value or "").startswith(GCASH_CHECKOUT_SESSION_PREFIXES)


def is_openai_custom_checkout_session_id(value: Any) -> bool:
    return str(value or "").startswith("oaics_")


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


def _gcash_elements_params(ctx: dict[str, str], *, include_session: bool = False) -> dict[str, str]:
    params = {
        "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
        "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
        "elements_session_client[elements_init_source]": "custom_checkout",
        "elements_session_client[referrer_host]": "chatgpt.com",
        "elements_session_client[stripe_js_id]": ctx["stripe_js_id"],
        "elements_session_client[locale]": "vi",
        "elements_session_client[is_aggregation_expected]": "false",
        "elements_options_client[saved_payment_method][enable_save]": "never",
        "elements_options_client[saved_payment_method][enable_redisplay]": "never",
    }
    if include_session:
        params["elements_session_client[session_id]"] = ctx["elements_session_id"]
    return params


def stripe_init(stripe: requests.Session, cs_id: str, stripe_pk: str, ctx: dict[str, str]) -> dict[str, Any]:
    resp = stripe.post(
        f"https://api.stripe.com/v1/payment_pages/{cs_id}/init",
        data={
            "key": stripe_pk,
            "eid": "NA",
            "browser_locale": "en-PH",
            "browser_timezone": "Asia/Manila",
            "redirect_type": "url",
            "_stripe_version": GCASH_STRIPE_VERSION,
            **_gcash_elements_params(ctx),
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
            "_stripe_version": GCASH_STRIPE_VERSION,
            **_gcash_elements_params(ctx, include_session=True),
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"payment_pages get failed: HTTP {resp.status_code} {short(resp.text)}")
    return resp.json() or {}


def _redirect_url(payload: Any) -> tuple[str, str]:
    if isinstance(payload, dict):
        action = payload.get("next_action")
        if isinstance(action, dict):
            redirect = action.get("redirect_to_url")
            if isinstance(redirect, dict) and str(redirect.get("url") or "").strip():
                return str(redirect.get("url") or "").strip(), str(action.get("type") or "")
        for key in ("setup_intent", "payment_intent", "submission_attempt", "latest_attempt", "submission", "session"):
            found, action_type = _redirect_url(payload.get(key))
            if found:
                return found, action_type
    if isinstance(payload, list):
        for item in payload:
            found, action_type = _redirect_url(item)
            if found:
                return found, action_type
    return "", ""


def _is_stripe_pm_redirect_url(value: str) -> bool:
    host = (urlsplit(str(value or "")).netloc or "").lower()
    return host.endswith("pm-redirects.stripe.com")


def _is_gcash_provider_url(value: str) -> bool:
    host = (urlsplit(str(value or "")).netloc or "").lower()
    return (
        _is_stripe_pm_redirect_url(value)
        or "gcash" in host
        or host.endswith("alipayplus.com")
        or host.endswith(".alipayplus.com")
        or host.endswith("mynt.xyz")
        or host.endswith(".mynt.xyz")
    )


def _is_final_gcash_provider_url(value: str) -> bool:
    host = (urlsplit(str(value or "")).netloc or "").lower()
    return (
        "gcash" in host
        or host.endswith("alipayplus.com")
        or host.endswith(".alipayplus.com")
        or host.endswith("mynt.xyz")
        or host.endswith(".mynt.xyz")
    )


def _extract_gcash_qr_fields(value: Any) -> dict[str, str]:
    out = {"gcash_qr_url": "", "gcash_qr_data": "", "gcash_qr_image": ""}

    def capture(text: str) -> None:
        if not text:
            return
        if re.match(r"https?://", text, re.I) and ("qr" in text.lower() or "gcash" in text.lower()):
            if not out["gcash_qr_url"]:
                out["gcash_qr_url"] = text
            return
        if not out["gcash_qr_data"] and (
            text.lower().startswith(("gcash://", "data:image/"))
            or ("gcash" in text.lower() and len(text) >= 12 and len(text) <= 512 and "<" not in text)
        ):
            out["gcash_qr_data"] = text
        if not out["gcash_qr_image"] and text.lower().startswith("data:image/"):
            out["gcash_qr_image"] = text

    def walk(node: Any) -> None:
        if isinstance(node, str):
            capture(node.strip())
        elif isinstance(node, dict):
            for key, nested in node.items():
                key_l = str(key or "").lower()
                if any(marker in key_l for marker in ("qr", "code", "image", "deeplink", "deep_link")):
                    walk(nested)
                elif isinstance(nested, (dict, list)):
                    walk(nested)
        elif isinstance(node, list):
            for nested in node:
                walk(nested)

    walk(value)
    if isinstance(value, str):
        text = value
        for pattern in (
            r"data:image/(?:png|svg\+xml|jpeg);base64,[A-Za-z0-9+/=]+",
            r"gcash://[^\s\"'<>]+",
            r"https?://[^\s\"'<>]+(?:qr|QRCode|qrcode|gcash)[^\s\"'<>]*",
        ):
            match = re.search(pattern, text, re.I)
            if match:
                capture(match.group(0))
    return out


def extract_gcash_result(payload: Any, cs_id: str = "") -> dict[str, str]:
    redirect_url, action_type = _redirect_url(payload)
    fields = {
        "gcash_link": "",
        "provider_redirect_url": "",
        "stripe_redirect_url": "",
        "cs_id": cs_id,
        "submission_state": "",
        "next_action_type": action_type,
        "setup_intent": "",
        "payment_intent": "",
        "intent_state": "",
        "gcash_qr_url": "",
        "gcash_qr_data": "",
        "gcash_qr_image": "",
    }
    fields.update({k: v for k, v in _extract_gcash_qr_fields(payload).items() if v})
    if redirect_url and _is_gcash_provider_url(redirect_url):
        if _is_stripe_pm_redirect_url(redirect_url):
            fields["stripe_redirect_url"] = redirect_url
        else:
            fields["provider_redirect_url"] = redirect_url
            fields["gcash_link"] = redirect_url
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
    return _is_gcash_provider_url(str(fields.get("gcash_link") or fields.get("provider_redirect_url") or fields.get("stripe_redirect_url") or ""))


def resolve_gcash_redirect(stripe: requests.Session, redirect_url: str, max_hops: int = 3) -> str:
    current = str(redirect_url or "").strip()
    for _ in range(max(1, int(max_hops or 1))):
        if not current:
            return ""
        if _is_final_gcash_provider_url(current):
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


def finalize_gcash_result(stripe: requests.Session, fields: dict[str, Any], *, link_source: str) -> bool:
    candidate = str(fields.get("provider_redirect_url") or fields.get("gcash_link") or fields.get("stripe_redirect_url") or "").strip()
    if not candidate:
        return False
    provider = resolve_gcash_redirect(stripe, candidate)
    if provider and _is_final_gcash_provider_url(provider):
        fields["provider_redirect_url"] = provider
        fields["gcash_link"] = provider
    elif _is_final_gcash_provider_url(candidate):
        fields["provider_redirect_url"] = candidate
        fields["gcash_link"] = candidate
    elif _is_stripe_pm_redirect_url(candidate):
        fields["provider_redirect_url"] = candidate
        fields["gcash_link"] = candidate
    else:
        return False
    if _is_stripe_pm_redirect_url(candidate):
        fields["stripe_redirect_url"] = candidate
    try:
        response = stripe.get(fields["gcash_link"], allow_redirects=True, timeout=TIMEOUT)
        if response.text:
            qr_fields = _extract_gcash_qr_fields(response.text)
            for key, value in qr_fields.items():
                if value and not fields.get(key):
                    fields[key] = value
    except Exception:
        pass
    fields["link_source"] = link_source
    fields["link_binding"] = "chatgpt_checkout_session"
    return True


def gcash_return_url(cs_id: str, hosted_url: str) -> str:
    success_url = f"https://chatgpt.com/backend-api/payments/checkout/openai_llc/{cs_id}/success?billing_country=PH"
    base = hosted_url or f"https://checkout.stripe.com/c/pay/{cs_id}"
    parsed = urlsplit(base)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["returned_from_redirect"] = "true"
    query["ui_mode"] = "custom"
    query["return_url"] = success_url
    return urlunsplit((parsed.scheme or "https", parsed.netloc or "checkout.stripe.com", parsed.path, urlencode(query), parsed.fragment))


def update_gcash_checkout_promotion(chatgpt: requests.Session, *, cs_id: str, processor: str, promo_id: str = GCASH_PROMO_ID) -> None:
    body: dict[str, Any] = {
        "checkout_session_id": cs_id,
        "processor_entity": processor,
        "plan_name": "chatgptplusplan",
        "price_interval": "month",
        "seat_quantity": 1,
        "billing_details": {"country": GCASH_COUNTRY, "currency": GCASH_CURRENCY},
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


def sync_gcash_tax_region(
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
            "billing_country": GCASH_COUNTRY,
            "billing_name": billing["name"],
            "currency": GCASH_CURRENCY,
            "tax_id": None,
            "processor_entity": processor,
            "billing_address": {
                "line1": billing["line1"],
                "city": billing["city"],
                "country": GCASH_COUNTRY,
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
            "tax_region[country]": GCASH_COUNTRY,
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
    country: str = GCASH_COUNTRY,
) -> None:
    cg = build_gcash_chatgpt_session(access_token, proxy_url, device_id)
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


def _confirm_gcash_inline(
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
            "payment_method_type": "gcash",
            "key": stripe_pk,
            "_stripe_version": GCASH_STRIPE_VERSION,
        },
        timeout=TIMEOUT,
    )
    if pre_confirm_resp.status_code >= 400:
        raise RuntimeError(f"pre_confirm failed: HTTP {pre_confirm_resp.status_code} {short(pre_confirm_resp.text)}")
    payment_method_resp = stripe.post(
        "https://api.stripe.com/v1/payment_methods",
        data={
            "type": "gcash",
            "billing_details[name]": billing["name"],
            "billing_details[email]": billing["email"],
            "billing_details[address][country]": GCASH_COUNTRY,
            "billing_details[address][line1]": billing["line1"],
            "billing_details[address][city]": billing["city"],
            "billing_details[address][postal_code]": billing["postal_code"],
            "billing_details[address][state]": billing.get("state") or "",
            "guid": ctx["guid"],
            "muid": ctx["muid"],
            "sid": ctx["sid"],
            "_stripe_version": GCASH_STRIPE_VERSION,
            "key": stripe_pk,
            "payment_user_agent": GCASH_STRIPE_PAYMENT_UA,
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
            "version": GCASH_STRIPE_RUNTIME_VERSION,
            "expected_amount": amount,
            "expected_payment_method_type": "gcash",
            "return_url": return_url,
            "client_attribution_metadata[client_session_id]": ctx["client_session_id"],
            "client_attribution_metadata[checkout_session_id]": cs_id,
            "client_attribution_metadata[checkout_config_id]": ctx.get("config_id") or "",
            "client_attribution_metadata[merchant_integration_source]": "checkout",
            "client_attribution_metadata[merchant_integration_version]": "custom_checkout",
            "client_attribution_metadata[payment_method_selection_flow]": "merchant_specified",
            "key": stripe_pk,
            "_stripe_version": GCASH_STRIPE_VERSION,
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"confirm failed: HTTP {resp.status_code} {short(resp.text)}")
    return resp.json() or {}


def _checkout_email(init_payload: dict[str, Any], billing: dict[str, str]) -> str:
    customer = init_payload.get("customer") if isinstance(init_payload.get("customer"), dict) else {}
    return str(customer.get("email") or billing.get("email") or "")


def _walk_payload_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _walk_payload_dicts(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_payload_dicts(nested)


def _nested_string(payload: Any, names: tuple[str, ...], *, prefixes: tuple[str, ...] = ()) -> str:
    for item in _walk_payload_dicts(payload):
        for name in names:
            value = item.get(name)
            if isinstance(value, str):
                text = value.strip()
                if text and (not prefixes or text.startswith(prefixes)):
                    return text
    return ""


def _minor_amount(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, dict):
        for key in ("minorUnitsAmount", "minor_units_amount", "amount", "value"):
            parsed = _minor_amount(value.get(key))
            if parsed is not None:
                return parsed
    text = str(value).strip()
    if re.fullmatch(r"[+-]?\d+(?:\.0+)?", text):
        return int(text.split(".", 1)[0])
    return None


def oaics_amount_observations(payload: Any) -> list[tuple[str, int]]:
    paths = (
        ("checkout_amount_minor",),
        ("total_summary", "due"),
        ("totalSummary", "due"),
        ("invoice", "amount_due"),
        ("invoice", "amountDue"),
        ("amount_due",),
        ("amountDue",),
        ("amount_total",),
        ("amountTotal",),
        ("total", "total"),
        ("total", "due"),
        ("total", "taxInclusive"),
        ("total", "taxInclusiveAmount"),
    )
    found: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for item in _walk_payload_dicts(payload):
        for path in paths:
            current: Any = item
            for key in path:
                if not isinstance(current, dict) or key not in current:
                    current = None
                    break
                current = current.get(key)
            amount = _minor_amount(current)
            if amount is None:
                continue
            marker = (".".join(path), amount)
            if marker not in seen:
                seen.add(marker)
                found.append(marker)
    return found


def verify_oaics_zero_snapshot(payload: Any, *, cs_id: str, currency: str) -> int:
    observations = oaics_amount_observations(payload)
    if not observations:
        raise RuntimeError(f"OAICS 未返回可核验的应付金额: {cs_id}")
    nonzero = [(label, amount) for label, amount in observations if amount != 0]
    if nonzero:
        detail = ", ".join(f"{label}={amount}" for label, amount in nonzero)
        raise RuntimeError(f"GCash 金额必须为 0: {detail} {str(currency or '').upper()}")
    return 0


def _oaics_observed_amount_text(payload: Any, default: str = "") -> str:
    observations = oaics_amount_observations(payload)
    if not observations:
        return default
    first_nonzero = next((amount for _label, amount in observations if amount != 0), None)
    return str(first_nonzero if first_nonzero is not None else observations[0][1])


def oaics_payment_method_types(payload: Any) -> list[str]:
    methods: list[str] = []
    seen: set[str] = set()
    for item in _walk_payload_dicts(payload):
        candidates = item.get("payment_method_types")
        if candidates is None:
            candidates = item.get("paymentMethodTypes")
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if isinstance(candidate, dict):
                candidate = candidate.get("type")
            method = str(candidate or "").strip().lower()
            if method and method not in seen:
                seen.add(method)
                methods.append(method)
    return methods


def oaics_custom_payment_methods(payload: Any) -> list[dict[str, Any]]:
    methods: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in _walk_payload_dicts(payload):
        candidates = item.get("custom_payment_methods")
        if candidates is None:
            candidates = item.get("customPaymentMethods")
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            method_id = str(candidate.get("id") or "").strip()
            if not method_id.startswith("cpmt_") or method_id in seen:
                continue
            seen.add(method_id)
            methods.append(candidate)
    methods.sort(key=lambda item: 0 if "gcash" in json.dumps(item, ensure_ascii=True).lower() else 1)
    return methods


def oaics_gcash_custom_payment_methods(payload: Any) -> list[dict[str, Any]]:
    return [item for item in oaics_custom_payment_methods(payload) if "gcash" in json.dumps(item, ensure_ascii=True).lower()]


def extract_oaics_redirect_to_url(payload: Any) -> str:
    redirect_url, _action_type = _redirect_url(payload)
    if redirect_url:
        return redirect_url
    if isinstance(payload, dict):
        nested_url = _find_url_string(payload, ("pm-redirects.stripe.com", "gcash.ph"))
        if nested_url:
            return nested_url
    return ""


def _find_url_string(value: Any, preferred_hosts: tuple[str, ...]) -> str:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        if any(host in text.lower() for host in preferred_hosts):
            match = re.search(r"https?://[^\\\s\"'<>]+", text)
            return match.group(0) if match else text
        return ""
    if isinstance(value, dict):
        for key in ("url", "redirect_url", "redirectUrl", "hosted_url", "hostedUrl"):
            found = _find_url_string(value.get(key), preferred_hosts)
            if found:
                return found
        for nested in value.values():
            found = _find_url_string(nested, preferred_hosts)
            if found:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _find_url_string(nested, preferred_hosts)
            if found:
                return found
    return ""


def fetch_oaics_checkout_session(
    chatgpt: requests.Session,
    access_token: str,
    cs_id: str,
    processor: str,
    *,
    country: str,
    device_id: str,
) -> dict[str, Any]:
    if not is_openai_custom_checkout_session_id(cs_id):
        raise RuntimeError(f"不是 oaics checkout: {cs_id}")
    checkout_url = f"https://chatgpt.com/checkout/{processor}/{cs_id}"
    resp = chatgpt.get(
        f"https://chatgpt.com/backend-api/payments/checkout/{processor}/{cs_id}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Referer": checkout_url,
            "x-openai-target-path": "/backend-api/payments/checkout/{processor_entity}/{checkout_session_id}",
            "x-openai-target-route": "/backend-api/payments/checkout/{processor_entity}/{checkout_session_id}",
            "oai-device-id": device_id,
            "oai-language": f"{str(country or GCASH_COUNTRY).lower()}",
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"读取 OAICS Checkout 失败 HTTP {resp.status_code}: {short(resp.text)}")
    return resp.json() or {}


def submit_oaics_checkout_taxes(
    chatgpt: requests.Session,
    access_token: str,
    cs_id: str,
    processor: str,
    *,
    billing: dict[str, str],
    country: str,
    currency: str,
    device_id: str,
) -> dict[str, Any]:
    checkout_url = f"https://chatgpt.com/checkout/{processor}/{cs_id}"
    body = {
        "checkout_session_id": cs_id,
        "checkout_email": str(billing.get("email") or ""),
        "billing_country": str(country or billing.get("country") or GCASH_COUNTRY).upper(),
        "billing_name": str(billing.get("name") or ""),
        "currency": str(currency or GCASH_CURRENCY).upper(),
        "tax_id": str(billing.get("tax_id") or "") or None,
        "processor_entity": processor,
        "billing_address": {
            "country": str(country or billing.get("country") or GCASH_COUNTRY).upper(),
            "line1": str(billing.get("line1") or ""),
            "line2": str(billing.get("line2") or ""),
            "city": str(billing.get("city") or ""),
            "state": str(billing.get("state") or ""),
            "postal_code": str(billing.get("postal_code") or ""),
        },
    }
    resp = chatgpt.post(
        "https://chatgpt.com/backend-api/payments/checkout/taxes",
        json=body,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Referer": checkout_url,
            "x-openai-target-path": "/backend-api/payments/checkout/taxes",
            "x-openai-target-route": "/backend-api/payments/checkout/taxes",
            "oai-device-id": device_id,
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"OAICS taxes failed: HTTP {resp.status_code} {short(resp.text)}")
    return resp.json() or {}


def create_oaics_elements_session(
    stripe: requests.Session,
    state: dict[str, Any],
    *,
    country: str,
    currency: str,
) -> dict[str, Any]:
    publishable_key = str(state.get("publishable_key") or state.get("stripe_publishable_key") or state.get("public_key") or "").strip()
    customer_secret = str(state.get("customer_session_client_secret") or "").strip()
    if not publishable_key.startswith(("pk_live_", "pk_test_")):
        raise RuntimeError("OAICS GCash 缺少 Stripe publishable_key")
    if not customer_secret:
        raise RuntimeError("OAICS GCash 缺少 customer_session_client_secret")
    stripe_js_id = str(uuid.uuid4())
    params: dict[str, Any] = {
        "customer_session_client_secret": customer_secret,
        "client_betas[0]": "custom_checkout_server_updates_1",
        "client_betas[1]": "custom_checkout_manual_approval_1",
        "deferred_intent[mode]": "subscription",
        "deferred_intent[amount]": "0",
        "deferred_intent[currency]": str(currency or GCASH_CURRENCY).lower(),
        "deferred_intent[setup_future_usage]": "off_session",
        "currency": str(currency or GCASH_CURRENCY).lower(),
        "key": publishable_key,
        "_stripe_version": GCASH_STRIPE_VERSION,
        "elements_init_source": "stripe.elements",
        "referrer_host": "chatgpt.com",
        "stripe_js_id": stripe_js_id,
        "locale": "en-PH",
        "type": "deferred_intent",
    }
    for index, method in enumerate(oaics_payment_method_types(state)):
        params[f"deferred_intent[payment_method_types][{index}]"] = method
    resp = stripe.get("https://api.stripe.com/v1/elements/sessions", params=params, timeout=TIMEOUT)
    if resp.status_code >= 400:
        raise RuntimeError(f"OAICS GCash Elements Session 失败 HTTP {resp.status_code}: {short(resp.text)}")
    payload = resp.json() or {}
    payload["_oaics_publishable_key"] = publishable_key
    payload["_oaics_stripe_js_id"] = stripe_js_id
    payload["_oaics_payment_method_types"] = oaics_payment_method_types(state)
    return payload


def create_oaics_gcash_confirmation_token(
    stripe: requests.Session,
    elements: dict[str, Any],
    *,
    billing: dict[str, str],
    currency: str,
) -> str:
    pk = str(elements.get("_oaics_publishable_key") or "").strip()
    if not pk:
        raise RuntimeError("OAICS GCash ConfirmationToken 缺少 publishable_key")
    body: dict[str, Any] = {
        "payment_method_data[type]": "gcash",
        "payment_method_data[billing_details][name]": str(billing.get("name") or ""),
        "payment_method_data[billing_details][email]": str(billing.get("email") or ""),
        "payment_method_data[billing_details][address][country]": str(billing.get("country") or GCASH_COUNTRY).upper(),
        "payment_method_data[billing_details][address][line1]": str(billing.get("line1") or ""),
        "payment_method_data[billing_details][address][city]": str(billing.get("city") or ""),
        "payment_method_data[billing_details][address][postal_code]": str(billing.get("postal_code") or ""),
        "payment_method_data[referrer]": "https://chatgpt.com",
        "payment_method_data[time_on_page]": str(random.randint(25000, 55000)),
        "setup_future_usage": "off_session",
        "set_as_default_payment_method": "false",
        "mandate_data[customer_acceptance][type]": "online",
        "mandate_data[customer_acceptance][online][infer_from_client]": "true",
        "client_context[currency]": str(currency or GCASH_CURRENCY).lower(),
        "client_context[mode]": "subscription",
        "client_attribution_metadata[merchant_integration_source]": "elements",
        "client_attribution_metadata[merchant_integration_subtype]": "payment-element",
        "client_attribution_metadata[merchant_integration_version]": "2021",
        "client_attribution_metadata[payment_intent_creation_flow]": "deferred",
        "client_attribution_metadata[payment_method_selection_flow]": "automatic",
        "key": pk,
    }
    if billing.get("state"):
        body["payment_method_data[billing_details][address][state]"] = str(billing.get("state") or "")
    for index, method in enumerate(elements.get("_oaics_payment_method_types") or []):
        body[f"client_context[payment_method_types][{index}]"] = method
    for name, value in (
        ("elements_session_id", _nested_string(elements, ("session_id", "sessionId", "id"), prefixes=("elements_session_",))),
        ("elements_session_config_id", _nested_string(elements, ("config_id", "elements_session_config_id", "elementsSessionConfigId"))),
    ):
        if value:
            body[f"client_attribution_metadata[{name}]"] = value
            body[f"payment_method_data[client_attribution_metadata][{name}]"] = value
    customer = _nested_string(elements, ("customer", "customer_id", "customerId"), prefixes=("cus_",))
    if customer:
        body["client_context[customer]"] = customer
    resp = stripe.post(
        "https://api.stripe.com/v1/confirmation_tokens",
        data=body,
        headers={
            "Authorization": f"Bearer {pk}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Stripe-Version": GCASH_STRIPE_VERSION,
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"OAICS GCash ConfirmationToken 失败 HTTP {resp.status_code}: {short(resp.text)}")
    payload = resp.json() or {}
    token = str(payload.get("id") or payload.get("confirmation_token") or payload.get("confirmationToken") or "").strip()
    if not token.startswith(("ctoken_", "ct_")):
        raise RuntimeError("OAICS GCash ConfirmationToken 响应缺少 token")
    return token


def confirm_oaics_standard_gcash(
    chatgpt: requests.Session,
    access_token: str,
    cs_id: str,
    processor: str,
    confirmation_token: str,
    *,
    country: str,
    device_id: str,
) -> dict[str, Any]:
    resp = chatgpt.post(
        "https://chatgpt.com/backend-api/payments/checkout/confirm",
        json={
            "checkout_session_id": cs_id,
            "confirm_token": confirmation_token,
            "selected_payment_method_type": "gcash",
        },
        headers={
            "Authorization": f"Bearer {access_token}",
            "Referer": f"https://chatgpt.com/checkout/{processor}/{cs_id}",
            "x-openai-target-path": "/backend-api/payments/checkout/confirm",
            "x-openai-target-route": "/backend-api/payments/checkout/confirm",
            "oai-device-id": device_id,
            "oai-language": f"{str(country or GCASH_COUNTRY).lower()}",
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"OAICS GCash confirm 失败 HTTP {resp.status_code}: {short(resp.text)}")
    payload = resp.json() or {}
    status = str(payload.get("status") or "").strip().lower()
    if status == "blocked":
        raise RuntimeError("OAICS GCash confirm blocked")
    return payload


def confirm_oaics_gcash_intent(
    stripe: requests.Session,
    confirmation_token: str,
    app_confirm: dict[str, Any],
    elements: dict[str, Any],
) -> dict[str, Any]:
    pk = str(elements.get("_oaics_publishable_key") or "").strip()
    client_secret = str(app_confirm.get("client_secret") or "").strip()
    if "_secret_" not in client_secret:
        raise RuntimeError("OAICS GCash confirm 未返回 Intent client_secret")
    intent_id = client_secret.split("_secret_", 1)[0]
    if intent_id.startswith("pi_"):
        collection = "payment_intents"
    elif intent_id.startswith("seti_"):
        collection = "setup_intents"
    else:
        raise RuntimeError("OAICS GCash confirm 返回了未知 Intent")
    body = {
        "confirmation_token": confirmation_token,
        "client_secret": client_secret,
        "use_stripe_sdk": "true",
        "key": pk,
    }
    return_url = str(app_confirm.get("confirm_return_url") or "").strip()
    if return_url:
        body["return_url"] = return_url
    resp = stripe.post(
        f"https://api.stripe.com/v1/{collection}/{intent_id}/confirm",
        data=body,
        headers={
            "Authorization": f"Bearer {pk}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Stripe-Version": GCASH_STRIPE_VERSION,
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"OAICS GCash Intent confirm 失败 HTTP {resp.status_code}: {short(resp.text)}")
    return resp.json() or {}


def confirm_oaics_custom_payment_method(
    chatgpt: requests.Session,
    access_token: str,
    cs_id: str,
    processor: str,
    custom_payment_method_id: str,
    *,
    country: str,
    device_id: str,
) -> dict[str, Any]:
    resp = chatgpt.post(
        "https://chatgpt.com/backend-api/payments/checkout/confirm",
        json={
            "checkout_session_id": cs_id,
            "processor_entity": processor,
            "selected_payment_method_type": custom_payment_method_id,
        },
        headers={
            "Authorization": f"Bearer {access_token}",
            "Referer": f"https://chatgpt.com/checkout/{processor}/{cs_id}",
            "x-openai-target-path": "/backend-api/payments/checkout/confirm",
            "x-openai-target-route": "/backend-api/payments/checkout/confirm",
            "oai-device-id": device_id,
            "oai-language": f"{str(country or GCASH_COUNTRY).lower()}",
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"确认 OAICS GCash 支付方式失败 HTTP {resp.status_code}: {short(resp.text)}")
    payload = resp.json() or {}
    status = str(payload.get("status") or "").strip().lower()
    if status == "blocked":
        raise RuntimeError("OAICS GCash confirm blocked")
    if status and status != "success":
        raise RuntimeError(f"确认 OAICS GCash 支付方式失败 status={status}")
    return payload


def start_oaics_custom_payment_method(
    chatgpt: requests.Session,
    access_token: str,
    cs_id: str,
    processor: str,
    custom_payment_method_id: str,
    *,
    country: str,
    device_id: str,
) -> dict[str, Any]:
    resp = chatgpt.post(
        "https://chatgpt.com/backend-api/payments/checkout/custom_payment_method/start",
        json={
            "checkout_session_id": cs_id,
            "processor_entity": processor,
            "custom_payment_method_type_id": custom_payment_method_id,
        },
        headers={
            "Authorization": f"Bearer {access_token}",
            "Referer": f"https://chatgpt.com/checkout/{processor}/{cs_id}",
            "x-openai-target-path": "/backend-api/payments/checkout/custom_payment_method/start",
            "x-openai-target-route": "/backend-api/payments/checkout/custom_payment_method/start",
            "oai-device-id": device_id,
            "oai-language": f"{str(country or GCASH_COUNTRY).lower()}",
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"启动 OAICS GCash 支付失败 HTTP {resp.status_code}: {short(resp.text)}")
    payload = resp.json() or {}
    action = payload.get("next_action") if isinstance(payload.get("next_action"), dict) else {}
    if str(payload.get("status") or "").strip().lower() != "requires_action" or not str(action.get("url") or "").strip():
        raise RuntimeError("OAICS GCash start 未返回跳转地址")
    return payload


def _finish_oaics_gcash_redirect(
    stripe: requests.Session,
    redirect: str,
    *,
    cs_id: str,
    billing: dict[str, str],
    methods: list[str],
    link_source: str,
    processor: str,
) -> dict[str, Any]:
    fields = extract_gcash_result({"next_action": {"redirect_to_url": {"url": redirect}}}, cs_id)
    if not is_success(fields) or not finalize_gcash_result(stripe, fields, link_source=link_source):
        raise RuntimeError("OAICS GCash 未返回 GCash 链接")
    fields["amount"] = "0"
    fields["currency"] = GCASH_CURRENCY
    fields["payment_method_types"] = methods
    fields["ordered_payment_method_types"] = methods
    fields["chatgpt_checkout_url"] = f"https://chatgpt.com/checkout/{processor}/{cs_id}"
    fields["billing"] = billing
    fields["link_binding"] = "chatgpt_oaics_checkout_session"
    return {"ok": True, "amount": "0", "currency": GCASH_CURRENCY, "fields": fields, "billing": billing}


def generate_gcash_oaics_trial_experimental(
    *,
    access_token: str,
    cs_id: str,
    processor: str,
    proxy_url: str,
    device_id: str,
    billing: dict[str, str],
    country: str,
    currency: str,
    promo_already_applied: bool = False,
    log: LogFn | None = None,
) -> dict[str, Any]:
    log = log or (lambda _m: None)
    chatgpt = build_gcash_chatgpt_session(access_token, proxy_url, device_id)
    stripe = build_stripe_session(proxy_url)
    warm_chatgpt_checkout_context(chatgpt, country, log)
    if not promo_already_applied:
        update_gcash_checkout_promotion(chatgpt, cs_id=cs_id, processor=processor)
    state = fetch_oaics_checkout_session(chatgpt, access_token, cs_id, processor, country=country, device_id=device_id)
    taxes = submit_oaics_checkout_taxes(
        chatgpt,
        access_token,
        cs_id,
        processor,
        billing=billing,
        country=country,
        currency=currency,
        device_id=device_id,
    )
    merged_state = dict(state)
    merged_state.update(taxes)
    verify_oaics_zero_snapshot(merged_state, cs_id=cs_id, currency=currency)
    methods = oaics_payment_method_types(merged_state)
    log(f"[oaics] amount=0 payment_method_types={methods}")
    if "gcash" not in methods:
        cpmt = oaics_gcash_custom_payment_methods(merged_state)
        if not cpmt:
            raise RuntimeError(f"OAICS payment_method_types 未包含 gcash: methods={methods}")
        method_id = str(cpmt[0].get("id") or "")
        confirm_oaics_custom_payment_method(
            chatgpt,
            access_token,
            cs_id,
            processor,
            method_id,
            country=country,
            device_id=device_id,
        )
        started = start_oaics_custom_payment_method(
            chatgpt,
            access_token,
            cs_id,
            processor,
            method_id,
            country=country,
            device_id=device_id,
        )
        action = started.get("next_action") if isinstance(started.get("next_action"), dict) else {}
        redirect = str(action.get("url") or "").strip()
        return _finish_oaics_gcash_redirect(
            stripe,
            redirect,
            cs_id=cs_id,
            billing=billing,
            methods=[method_id],
            link_source="oaics_custom_payment_method_start",
            processor=processor,
        )
    elements = create_oaics_elements_session(stripe, merged_state, country=country, currency=currency)
    confirmation_token = create_oaics_gcash_confirmation_token(stripe, elements, billing=billing, currency=currency)
    app_confirm = confirm_oaics_standard_gcash(
        chatgpt,
        access_token,
        cs_id,
        processor,
        confirmation_token,
        country=country,
        device_id=device_id,
    )
    redirect = extract_oaics_redirect_to_url(app_confirm)
    if not redirect:
        intent_confirm = confirm_oaics_gcash_intent(stripe, confirmation_token, app_confirm, elements)
        redirect = extract_oaics_redirect_to_url(intent_confirm)
    return _finish_oaics_gcash_redirect(
        stripe,
        redirect,
        cs_id=cs_id,
        billing=billing,
        methods=methods,
        link_source="oaics_standard_gcash_intent_confirm",
        processor=processor,
    )


def detect_gcash_eligibility(cfg: GCashPhJobConfig, log: LogFn | None = None) -> dict[str, Any]:
    log = log or (lambda _m: None)
    token = str(cfg.access_token or "").strip()
    if not token:
        raise RuntimeError("缺少 Access Token")
    if not cfg.direct_proxies and (not cfg.kookeey_user or not cfg.kookeey_pass):
        raise RuntimeError("缺少代理配置：direct_proxies 或 Kookeey 用户名/密码")

    device_id = str(uuid.uuid4())
    billing = gcash_billing()
    dyn1, sid1 = build_gcash_dynamic_proxy(cfg, 0)
    log(f"[1/2] PH 创建 PHP checkout 检测 GCash sid={sid1}")
    with pix_proxy_context(cfg.local_proxy, dyn1, log) as chain1:
        checkout_proxy_url = chain1.url
        cg = build_gcash_chatgpt_session(token, checkout_proxy_url, device_id)
        warm_chatgpt_checkout_context(cg, GCASH_COUNTRY, log)
        checkout_body: dict[str, Any] = {
            "entry_point": "all_plans_pricing_modal",
            "plan_name": "chatgptplusplan",
            "billing_details": {"country": GCASH_COUNTRY, "currency": GCASH_CURRENCY},
            "cancel_url": "https://chatgpt.com/#pricing",
            "checkout_ui_mode": "custom",
        }
        if cfg.front_promo:
            checkout_body["promo_campaign"] = {"promo_campaign_id": GCASH_PROMO_ID, "is_coupon_from_query_param": False}
        resp = cg.post(
            "https://chatgpt.com/backend-api/payments/checkout",
            json=checkout_body,
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
        if not is_gcash_checkout_session_id(cs_id):
            raise RuntimeError(f"checkout missing cs_id: {short(data)}")
        pk = str(data.get("publishable_key") or data.get("public_key") or extract_pk(data) or DEFAULT_STRIPE_PK)
        processor = str(data.get("processor_entity") or "openai_llc")
        if is_openai_custom_checkout_session_id(cs_id):
            if not cfg.front_promo:
                update_gcash_checkout_promotion(cg, cs_id=cs_id, processor=processor)
            state = fetch_oaics_checkout_session(cg, token, cs_id, processor, country=GCASH_COUNTRY, device_id=device_id)
            taxes = submit_oaics_checkout_taxes(
                cg,
                token,
                cs_id,
                processor,
                billing=billing,
                country=GCASH_COUNTRY,
                currency=GCASH_CURRENCY,
                device_id=device_id,
            )
            merged_state = dict(state)
            merged_state.update(taxes)
            zero_error = ""
            try:
                amount = verify_oaics_zero_snapshot(merged_state, cs_id=cs_id, currency=GCASH_CURRENCY)
            except RuntimeError as exc:
                amount = _oaics_observed_amount_text(merged_state, "")
                zero_error = str(exc)
            pmt = oaics_payment_method_types(merged_state)
            cpmt = oaics_gcash_custom_payment_methods(merged_state)
            has_gcash = "gcash" in pmt or bool(cpmt)
            status = "eligible" if has_gcash and not zero_error else "ineligible"
            log(f"[2/2] oaics eligibility amount={amount} pmt={pmt} custom={len(cpmt)} has_gcash={has_gcash}")
            return {
                "ok": True,
                "status": status,
                "has_gcash": has_gcash,
                "amount": str(amount),
                "currency": GCASH_CURRENCY.lower(),
                "cs_id": cs_id,
                "processor": processor,
                "stripe_pk": pk,
                "device_id": device_id,
                "checkout_proxy_url": checkout_proxy_url,
                "promotion_proxy_url": checkout_proxy_url,
                "provider_proxy_url": checkout_proxy_url,
                "payment_method_types": pmt,
                "ordered_payment_method_types": pmt,
                "custom_payment_methods": cpmt,
                "billing": billing,
                "ctx": _ctx(),
                "checkout_flow": "oaics",
                "front_promo": bool(cfg.front_promo),
                "error": zero_error,
            }
        ctx = _ctx()
        stripe = build_stripe_session(checkout_proxy_url)
        init_payload = stripe_init(stripe, cs_id, pk, ctx)
        _sync_ctx_from_init(ctx, init_payload)
        amount = amount_info(init_payload)
        currency = currency_info(init_payload)
        pmt, ordered, has_gcash = pmt_info(init_payload)
        promo_applied = bool(cfg.front_promo)
        if has_gcash and not promo_applied:
            update_gcash_checkout_promotion(cg, cs_id=cs_id, processor=processor)
            promo_applied = True
            init_payload = stripe_init(stripe, cs_id, pk, ctx)
            _sync_ctx_from_init(ctx, init_payload)
            amount = amount_info(init_payload)
            currency = currency_info(init_payload)
            pmt, ordered, has_gcash = pmt_info(init_payload)
        status = "eligible" if has_gcash and is_zero_amount(amount) else "ineligible"
        log(f"[2/2] eligibility 金额={amount} currency={currency} pmt={pmt} ordered={ordered} has_gcash={has_gcash} promo_applied={promo_applied}")
        return {
            "ok": True,
            "status": status,
            "has_gcash": has_gcash,
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
            "front_promo": promo_applied,
        }


def generate_gcash_ph_trial(cfg: GCashPhJobConfig, log: LogFn | None = None) -> dict[str, Any]:
    log = log or (lambda _m: None)
    token = str(cfg.access_token or "").strip()
    if not token:
        raise RuntimeError("缺少 Access Token")
    eligibility = cfg.preflight_result or detect_gcash_eligibility(cfg, log)
    if str(eligibility.get("status") or "").lower() != "eligible" or not eligibility.get("has_gcash"):
        raise RuntimeError("无 GCash 资格")

    cs_id = str(eligibility.get("cs_id") or "")
    if not is_gcash_checkout_session_id(cs_id):
        raise RuntimeError("资格检测缺少 checkout session")
    if is_openai_custom_checkout_session_id(cs_id):
        processor = str(eligibility.get("processor") or "openai_llc")
        device_id = str(eligibility.get("device_id") or uuid.uuid4())
        billing = dict(eligibility.get("billing") or gcash_billing())
        proxy_url = str(eligibility.get("provider_proxy_url") or eligibility.get("checkout_proxy_url") or "")
        if not proxy_url:
            dyn, sid = build_gcash_dynamic_proxy(cfg, 2)
            log(f"[oaics] 使用 provider 代理 sid={sid}")
            proxy_url = dyn
        return generate_gcash_oaics_trial_experimental(
            access_token=token,
            cs_id=cs_id,
            processor=processor,
            proxy_url=proxy_url,
            device_id=device_id,
            billing=billing,
            country=GCASH_COUNTRY,
            currency=GCASH_CURRENCY,
            promo_already_applied=bool(eligibility.get("front_promo")),
            log=log,
        )
    processor = str(eligibility.get("processor") or "openai_llc")
    stripe_pk = str(eligibility.get("stripe_pk") or DEFAULT_STRIPE_PK)
    device_id = str(eligibility.get("device_id") or uuid.uuid4())
    billing = dict(eligibility.get("billing") or gcash_billing())
    ctx = dict(eligibility.get("ctx") or _ctx())
    promotion_region = _stage_region(cfg, 1)
    provider_region = _stage_region(cfg, 2)

    dyn2, sid2 = build_gcash_dynamic_proxy(cfg, 1)
    if bool(eligibility.get("front_promo")):
        log(f"[1/4] {promotion_region} checkout/update 已在资格检测阶段注入 promo，跳过重复注入")
    else:
        log(f"[1/4] {promotion_region} checkout/update 注入 promo sid={sid2}")
        with pix_proxy_context(cfg.local_proxy, dyn2, log) as chain2:
            promotion_proxy_url = chain2.url
            promotion_cg = build_gcash_chatgpt_session(token, promotion_proxy_url, device_id)
            warm_chatgpt_checkout_context(promotion_cg, promotion_region, log)
            update_gcash_checkout_promotion(promotion_cg, cs_id=cs_id, processor=processor)

    dyn3, sid3 = build_gcash_dynamic_proxy(cfg, 2)
    log(f"[2/4] {provider_region} Stripe refresh 验证 0 PHP + GCash sid={sid3}")
    with pix_proxy_context(cfg.local_proxy, dyn3, log) as chain3:
        provider_proxy_url = chain3.url
        provider_cg = build_gcash_chatgpt_session(token, provider_proxy_url, device_id)
        warm_chatgpt_checkout_context(provider_cg, GCASH_COUNTRY, log)
        stripe = build_stripe_session(provider_proxy_url)
        init_payload = stripe_init(stripe, cs_id, stripe_pk, ctx)
        _sync_ctx_from_init(ctx, init_payload)
        amount = amount_info(init_payload)
        currency = currency_info(init_payload)
        pmt, ordered, has_gcash = pmt_info(init_payload)
        log(f"promo 后金额={amount} currency={currency} 支付方式={pmt} ordered={ordered} has_gcash={has_gcash}")
        if not has_gcash:
            raise RuntimeError(f"promo 后未出现 GCash，pmt={pmt}")
        if not is_zero_amount(amount):
            raise RuntimeError(f"套 promo 后金额不是 0: {amount}")
        if currency and currency != "vnd":
            raise RuntimeError(f"套 promo 后币种不是 PHP: {currency}")

        log("[3/4] 同步 PH taxes / Stripe tax_region")
        sync_gcash_tax_region(
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
        pmt, ordered, has_gcash = pmt_info(init_payload)
        log(f"tax_region 后金额={amount} currency={currency} 支付方式={pmt} ordered={ordered} has_gcash={has_gcash}")
        if not has_gcash:
            raise RuntimeError(f"tax sync 后未出现 GCash，pmt={pmt}")
        if not is_zero_amount(amount):
            raise RuntimeError(f"tax sync 后金额不是 0: {amount}")
        if currency and currency != "vnd":
            raise RuntimeError(f"tax sync 后币种不是 PHP: {currency}")

        hosted = str(init_payload.get("stripe_hosted_url") or "")
        log("[4/4] pre_confirm + payment_method + confirm GCash")
        confirm_payload = _confirm_gcash_inline(
            stripe,
            cs_id=cs_id,
            stripe_pk=stripe_pk,
            ctx=ctx,
            billing=billing,
            amount=amount,
            return_url=gcash_return_url(cs_id, hosted),
        )
        fields = extract_gcash_result(confirm_payload, cs_id)
        sub = find_submission_attempt(confirm_payload)
        log(f"confirm submission={sub.get('state')} redirect={bool(fields.get('gcash_link') or fields.get('stripe_redirect_url'))}")
        if (
            str(sub.get("state") or "").strip().lower() not in {"requires_approval", "processing"}
            and is_success(fields)
            and finalize_gcash_result(stripe, fields, link_source="stripe_payment_pages_confirm")
        ):
            fields["amount"] = amount
            fields["currency"] = (currency or GCASH_CURRENCY).upper()
            fields["payment_method_types"] = pmt
            fields["ordered_payment_method_types"] = ordered
            fields["chatgpt_checkout_url"] = f"https://chatgpt.com/checkout/{processor}/{cs_id}"
            fields["billing"] = billing
            return {"ok": True, "amount": amount, "currency": fields["currency"], "fields": fields, "billing": billing}

        log("PH approve + poll GCash")
        chatgpt_approve(token, cs_id, processor, provider_proxy_url, device_id, log, country=GCASH_COUNTRY)
        for i in range(1, 11):
            page_data = page_get(stripe, cs_id, stripe_pk, ctx)
            fields = extract_gcash_result(page_data, cs_id)
            sub = find_submission_attempt(page_data)
            err = sub.get("error") if isinstance(sub.get("error"), dict) else {}
            log(f"poll {i}/10 sub={sub.get('state')} err={err.get('code') if err else '-'} success={is_success(fields)}")
            if is_success(fields) and finalize_gcash_result(stripe, fields, link_source="stripe_checkout_approve_poll"):
                fields["amount"] = amount
                fields["currency"] = (currency or GCASH_CURRENCY).upper()
                fields["payment_method_types"] = pmt
                fields["ordered_payment_method_types"] = ordered
                fields["chatgpt_checkout_url"] = f"https://chatgpt.com/checkout/{processor}/{cs_id}"
                fields["billing"] = billing
                return {"ok": True, "amount": amount, "currency": fields["currency"], "fields": fields, "billing": billing}
            if sub.get("state") == "failed":
                raise RuntimeError(f"approve 后失败: {err.get('code')}")
            time.sleep(1.0)
        raise RuntimeError("轮询超时，未拿到 GCash 链接")
