"""India UPI trial core: IN checkout -> optional promo update -> UPI instructions link."""

from __future__ import annotations

import json
import random
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import requests

from autotoken.payments.brazil_pix import (
    DEFAULT_STRIPE_PK,
    DEFAULT_STRIPE_RUNTIME_VERSION,
    DEFAULT_USER_AGENT,
    STRIPE_VERSION_FULL,
    TIMEOUT,
    amount_info,
    build_kookeey_proxy,
    extract_pk,
    pix_proxy_context,
    pix_proxy_with_fresh_sid,
    short,
    to_openai_pay_url,
)

LogFn = Callable[[str], None]

INDIA_ADDRESSES = [
    ("MG Road 12", "Bengaluru", "KA", "560001"),
    ("Connaught Place 21", "New Delhi", "DL", "110001"),
    ("Park Street 18", "Kolkata", "WB", "700016"),
    ("Linking Road 42", "Mumbai", "MH", "400050"),
    ("Anna Salai 66", "Chennai", "TN", "600002"),
    ("Banjara Hills Road 3", "Hyderabad", "TS", "500034"),
]
FIRST_NAMES = ["Aarav", "Vihaan", "Arjun", "Aditya", "Ishaan", "Anaya", "Diya", "Kavya", "Riya", "Meera"]
LAST_NAMES = ["Sharma", "Verma", "Patel", "Gupta", "Reddy", "Nair", "Iyer", "Singh", "Mehta", "Das"]


@dataclass
class UpiJobConfig:
    access_token: str
    local_proxy: str = ""
    kookeey_user: str = ""
    kookeey_pass: str = ""
    kookeey_endpoint: str = "gate.kookeey.info:1000"
    region: str = "IN"
    direct_proxies: list[str] = field(default_factory=list)
    apply_promo: bool = False


def normalize_upi_proxy_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "://" in raw:
        return raw
    parts = raw.split(":", 3)
    if len(parts) == 4 and parts[1].isdigit():
        host, port, user, password = parts
        from urllib.parse import quote

        return f"socks5h://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}"
    return f"http://{raw}"


def upi_proxy_with_fresh_sid(proxy_url: str, region: str = "IN") -> tuple[str, str]:
    proxy, sid = pix_proxy_with_fresh_sid(proxy_url, region)
    if sid != "static":
        return proxy, sid
    fresh = uuid.uuid4().hex[:8]
    refreshed, count = re.subn(r"(-session-)[A-Za-z0-9]+", rf"\g<1>{fresh}", proxy, count=1, flags=re.I)
    if count:
        return refreshed, fresh
    return proxy, sid


def build_upi_dynamic_proxy(cfg: UpiJobConfig, stage_index: int) -> tuple[str, str]:
    direct = [normalize_upi_proxy_url(item) for item in (cfg.direct_proxies or []) if str(item or "").strip()]
    if direct:
        idx = stage_index % len(direct)
        proxy, sid = upi_proxy_with_fresh_sid(direct[idx], cfg.region)
        return proxy, f"direct-{idx + 1} sid={sid}" if sid and sid != "static" else f"direct-{idx + 1} static"
    return build_kookeey_proxy(cfg.kookeey_user, cfg.kookeey_pass, cfg.kookeey_endpoint, cfg.region)


def new_http_session(proxy_url: str = "") -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    if proxy_url:
        session.proxies.update({"http": proxy_url, "https": proxy_url})
    return session


def build_chatgpt_session(access_token: str, proxy_url: str = "", device_id: str = "") -> requests.Session:
    device_id = str(device_id or uuid.uuid4())
    session = new_http_session(proxy_url)
    session.headers.update(
        {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": "en-IN,en;q=0.9",
            "Authorization": f"Bearer {access_token}",
            "Origin": "https://chatgpt.com",
            "Referer": "https://chatgpt.com/",
            "Content-Type": "application/json",
            "oai-device-id": device_id,
            "oai-language": "en-IN",
            "sec-ch-ua": '"Google Chrome";v="146", "Chromium";v="146", "Not.A/Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "Cookie": f"oai-did={device_id}",
        }
    )
    return session


def build_stripe_session(proxy_url: str = "") -> requests.Session:
    session = new_http_session(proxy_url)
    session.headers.update(
        {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept-Language": "en-IN,en;q=0.9",
            "Origin": "https://pay.openai.com",
            "Referer": "https://pay.openai.com/",
            "sec-fetch-site": "cross-site",
            "sec-fetch-mode": "cors",
            "sec-fetch-dest": "empty",
        }
    )
    return session


def india_billing() -> dict[str, str]:
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    line1, city, state, postal = random.choice(INDIA_ADDRESSES)
    slug = re.sub(r"[^a-z]", "", f"{first}{last}".lower())
    return {
        "name": f"{first} {last}",
        "email": f"{slug}{random.randint(10, 99)}@gmail.com",
        "phone": f"+91{random.randint(7000000000, 9999999999)}",
        "country": "IN",
        "line1": line1,
        "city": city,
        "state": state,
        "postal_code": postal,
    }


def pmt_info(payload: dict[str, Any]) -> tuple[list[Any], list[Any], bool]:
    pmt = payload.get("payment_method_types") or []
    ordered = payload.get("ordered_payment_method_types") or []
    methods = [str(item).lower() for item in list(pmt) + list(ordered)]
    return pmt, ordered, "upi" in methods


def _ctx() -> dict[str, str]:
    return {
        "stripe_js_id": str(uuid.uuid4()),
        "elements_session_id": f"elements_session_{uuid.uuid4().hex[:11]}",
        "elements_session_config_id": str(uuid.uuid4()),
        "config_id": "",
        "init_checksum": "",
    }


def stripe_init(stripe: requests.Session, cs_id: str, stripe_pk: str, ctx: dict[str, str]) -> dict[str, Any]:
    resp = stripe.post(
        f"https://api.stripe.com/v1/payment_pages/{cs_id}/init",
        data={
            "browser_locale": "en-IN",
            "browser_timezone": "Asia/Kolkata",
            "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
            "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
            "elements_session_client[elements_init_source]": "custom_checkout",
            "elements_session_client[referrer_host]": "chatgpt.com",
            "elements_session_client[stripe_js_id]": ctx["stripe_js_id"],
            "elements_session_client[locale]": "en-IN",
            "elements_session_client[is_aggregation_expected]": "false",
            "elements_options_client[saved_payment_method][enable_save]": "never",
            "elements_options_client[saved_payment_method][enable_redisplay]": "never",
            "key": stripe_pk,
            "_stripe_version": STRIPE_VERSION_FULL,
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"stripe init failed: HTTP {resp.status_code} {short(resp.text)}")
    data = resp.json() or {}
    ctx["config_id"] = str(data.get("config_id") or ctx.get("config_id") or "")
    ctx["init_checksum"] = str(data.get("init_checksum") or "")
    ctx["elements_session_config_id"] = str(data.get("config_id") or ctx.get("elements_session_config_id") or uuid.uuid4())
    return data


def page_get(stripe: requests.Session, cs_id: str, stripe_pk: str, ctx: dict[str, str]) -> dict[str, Any]:
    resp = stripe.get(
        f"https://api.stripe.com/v1/payment_pages/{cs_id}",
        params={
            "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
            "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
            "elements_session_client[elements_init_source]": "custom_checkout",
            "elements_session_client[referrer_host]": "chatgpt.com",
            "elements_session_client[session_id]": ctx["elements_session_id"],
            "elements_session_client[stripe_js_id]": ctx["stripe_js_id"],
            "elements_session_client[locale]": "en-IN",
            "elements_session_client[is_aggregation_expected]": "false",
            "elements_options_client[saved_payment_method][enable_save]": "never",
            "elements_options_client[saved_payment_method][enable_redisplay]": "never",
            "key": stripe_pk,
            "_stripe_version": STRIPE_VERSION_FULL,
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


def extract_upi_result(payload: Any, cs_id: str = "") -> dict[str, str]:
    text = json.dumps(payload, ensure_ascii=False) if not isinstance(payload, str) else payload
    out = {
        "upi_link": "",
        "hosted_instructions_url": "",
        "qr_image_url_png": "",
        "qr_image_url_svg": "",
        "qr_expires_at": "",
        "cs_id": cs_id,
        "submission_state": "",
        "next_action_type": "",
        "payment_intent": "",
    }
    matched = re.search(r"https://payments\.stripe\.com/upi/instructions/[A-Za-z0-9_\-]+", text)
    if matched:
        out["upi_link"] = matched.group(0)
        out["hosted_instructions_url"] = matched.group(0)
    matched = re.search(r"upi://[^\s\"']+", text)
    if matched and not out["upi_link"]:
        out["upi_link"] = matched.group(0)
    matched = re.search(r"pi_[A-Za-z0-9]+", text)
    if matched and "hcaptcha" not in matched.group(0):
        out["payment_intent"] = matched.group(0)

    if isinstance(payload, dict):
        sub = find_submission_attempt(payload)
        out["submission_state"] = str(sub.get("state") or "")

        def walk(obj: Any) -> None:
            if isinstance(obj, dict):
                na = obj.get("next_action")
                if isinstance(na, dict):
                    if na.get("type"):
                        out["next_action_type"] = str(na.get("type") or "")
                    box = na.get("upi_handle_redirect_or_display_qr_code") or {}
                    if isinstance(box, dict):
                        hosted = str(box.get("hosted_instructions_url") or "")
                        if hosted and "intent_path" not in hosted:
                            out["upi_link"] = out["hosted_instructions_url"] = hosted
                        qr = box.get("qr_code") if isinstance(box.get("qr_code"), dict) else {}
                        if isinstance(qr, dict):
                            out["qr_image_url_png"] = str(qr.get("image_url_png") or out["qr_image_url_png"])
                            out["qr_image_url_svg"] = str(qr.get("image_url_svg") or out["qr_image_url_svg"])
                            out["qr_expires_at"] = str(qr.get("expires_at") or out["qr_expires_at"])
                for value in obj.values():
                    walk(value)
            elif isinstance(obj, list):
                for item in obj:
                    walk(item)

        walk(payload)
    return out


def is_success(fields: dict[str, Any]) -> bool:
    link = str(fields.get("upi_link") or fields.get("hosted_instructions_url") or "")
    return link.startswith("https://payments.stripe.com/upi/instructions/") or link.startswith("upi://")


def chatgpt_approve(access_token: str, cs_id: str, processor: str, proxy_url: str, device_id: str, log: LogFn) -> None:
    cg = build_chatgpt_session(access_token, proxy_url, device_id)
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
                return
            last_err = short(resp.text)
        except Exception as exc:
            last_err = short(exc)
            log(f"approve attempt {attempt} error: {last_err}")
        time.sleep(1.0)
    raise RuntimeError(f"approve failed: {last_err}")


def _create_upi_payment_method(
    stripe: requests.Session,
    *,
    cs_id: str,
    stripe_pk: str,
    ctx: dict[str, str],
    billing: dict[str, str],
) -> str:
    runtime = DEFAULT_STRIPE_RUNTIME_VERSION
    resp = stripe.post(
        "https://api.stripe.com/v1/payment_methods",
        data={
            "billing_details[name]": billing["name"],
            "billing_details[email]": billing["email"],
            "billing_details[phone]": billing["phone"],
            "billing_details[address][country]": "IN",
            "billing_details[address][line1]": billing["line1"],
            "billing_details[address][city]": billing["city"],
            "billing_details[address][postal_code]": billing["postal_code"],
            "billing_details[address][state]": billing["state"],
            "type": "upi",
            "guid": uuid.uuid4().hex,
            "muid": uuid.uuid4().hex,
            "sid": uuid.uuid4().hex,
            "payment_user_agent": f"stripe.js/{runtime}; stripe-js-v3/{runtime}; payment-element; deferred-intent",
            "referrer": "https://chatgpt.com",
            "time_on_page": str(random.randint(28000, 65000)),
            "client_attribution_metadata[checkout_session_id]": cs_id,
            "client_attribution_metadata[client_session_id]": ctx["stripe_js_id"],
            "client_attribution_metadata[checkout_config_id]": ctx["config_id"],
            "client_attribution_metadata[elements_session_id]": ctx["elements_session_id"],
            "client_attribution_metadata[elements_session_config_id]": ctx["elements_session_config_id"],
            "client_attribution_metadata[merchant_integration_source]": "elements",
            "client_attribution_metadata[merchant_integration_subtype]": "payment-element",
            "client_attribution_metadata[merchant_integration_version]": "2021",
            "client_attribution_metadata[payment_intent_creation_flow]": "deferred",
            "client_attribution_metadata[payment_method_selection_flow]": "automatic",
            "client_attribution_metadata[merchant_integration_additional_elements][0]": "payment",
            "client_attribution_metadata[merchant_integration_additional_elements][1]": "address",
            "key": stripe_pk,
            "_stripe_version": STRIPE_VERSION_FULL,
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"create pm failed: {short(resp.text)}")
    pm_id = str((resp.json() or {}).get("id") or "")
    if not pm_id.startswith("pm_"):
        raise RuntimeError(f"bad pm id: {short(resp.text)}")
    return pm_id


def _confirm_upi(
    stripe: requests.Session,
    *,
    cs_id: str,
    stripe_pk: str,
    ctx: dict[str, str],
    payment_method_id: str,
    amount: str,
    return_url: str,
) -> dict[str, Any]:
    runtime = DEFAULT_STRIPE_RUNTIME_VERSION
    resp = stripe.post(
        f"https://api.stripe.com/v1/payment_pages/{cs_id}/confirm",
        data={
            "guid": uuid.uuid4().hex,
            "muid": uuid.uuid4().hex,
            "sid": uuid.uuid4().hex,
            "payment_method": payment_method_id,
            "init_checksum": ctx["init_checksum"],
            "version": runtime,
            "expected_amount": amount,
            "expected_payment_method_type": "upi",
            "return_url": return_url,
            "elements_session_client[session_id]": ctx["elements_session_id"],
            "elements_session_client[locale]": "en-IN",
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
            "consent[terms_of_service]": "accepted",
            "key": stripe_pk,
            "_stripe_version": STRIPE_VERSION_FULL,
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"confirm failed: {short(resp.text)}")
    return resp.json() or {}


def generate_upi_trial(cfg: UpiJobConfig, log: LogFn | None = None) -> dict[str, Any]:
    log = log or (lambda _m: None)
    token = str(cfg.access_token or "").strip()
    if not token:
        raise RuntimeError("缺少 Access Token")
    if not cfg.direct_proxies and (not cfg.kookeey_user or not cfg.kookeey_pass):
        raise RuntimeError("缺少代理配置：direct_proxies 或 Kookeey 用户名/密码")

    device_id = str(uuid.uuid4())
    billing = india_billing()
    log(f"账单: {billing['name']} / {billing['city']}-{billing['state']} / {billing['postal_code']}")

    dyn1, sid1 = build_upi_dynamic_proxy(cfg, 0)
    log(f"[1/6] IN 创建 checkout（{'套 promo' if cfg.apply_promo else '跳过 promo'}） sid={sid1}")
    with pix_proxy_context(cfg.local_proxy, dyn1, log) as chain1:
        p1 = chain1.url
        cg = build_chatgpt_session(token, p1, device_id)
        resp = cg.post(
            "https://chatgpt.com/backend-api/payments/checkout",
            json={
                "entry_point": "all_plans_pricing_modal",
                "plan_name": "chatgptplusplan",
                "billing_details": {"country": "IN", "currency": "INR"},
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

    dyn2, sid2 = build_upi_dynamic_proxy(cfg, 1)
    if cfg.apply_promo:
        log(f"[2/6] IN update 套试用 promo sid={sid2}")
        with pix_proxy_context(cfg.local_proxy, dyn2, log) as chain2:
            p2 = chain2.url
            cg2 = build_chatgpt_session(token, p2, device_id)
            update = cg2.post(
                "https://chatgpt.com/backend-api/payments/checkout/update",
                json={
                    "checkout_session_id": cs_id,
                    "processor_entity": processor,
                    "plan_name": "chatgptplusplan",
                    "price_interval": "month",
                    "seat_quantity": 1,
                    "billing_details": {"country": "IN", "currency": "INR"},
                    "promo_campaign": {
                        "promo_campaign_id": "plus-1-month-free",
                        "is_coupon_from_query_param": False,
                    },
                },
                headers={
                    "x-openai-target-path": "/backend-api/payments/checkout/update",
                    "x-openai-target-route": "/backend-api/payments/checkout/update",
                },
                timeout=TIMEOUT,
            )
            log(f"update HTTP {update.status_code} {short(update.text, 120)}")
            if update.status_code >= 400:
                raise RuntimeError(f"update failed: {short(update.text)}")
    else:
        log(f"[2/6] 跳过 promo update sid={sid2}")

    dyn3, sid3 = build_upi_dynamic_proxy(cfg, 2)
    log(f"[3/6] Stripe init sid={sid3}")
    with pix_proxy_context(cfg.local_proxy, dyn3, log) as chain3:
        p3 = chain3.url
        stripe = build_stripe_session(p3)
        ctx = _ctx()
        init_payload = stripe_init(stripe, cs_id, pk, ctx)
        amount = amount_info(init_payload)
        pmt, ordered, has_upi = pmt_info(init_payload)
        log(f"金额={amount} 支付方式={pmt} ordered={ordered} has_upi={has_upi}")
        if not has_upi:
            raise RuntimeError(f"未出现 UPI，pmt={pmt}")
        if cfg.apply_promo and amount not in ("0", "0.0"):
            raise RuntimeError(f"套 promo 后金额不是 0: {amount}")

        hosted = str(init_payload.get("stripe_hosted_url") or "")
        log("[4/6] 创建 UPI payment_method")
        pm_id = _create_upi_payment_method(stripe, cs_id=cs_id, stripe_pk=pk, ctx=ctx, billing=billing)
        log(f"pm_id={pm_id}")

        log("[5/6] confirm UPI")
        return_url = to_openai_pay_url(hosted) or hosted or f"https://pay.openai.com/c/pay/{cs_id}"
        confirm_payload = _confirm_upi(
            stripe,
            cs_id=cs_id,
            stripe_pk=pk,
            ctx=ctx,
            payment_method_id=pm_id,
            amount=amount,
            return_url=return_url,
        )
        fields = extract_upi_result(confirm_payload, cs_id)
        sub = find_submission_attempt(confirm_payload)
        log(f"confirm submission={sub.get('state')}")
        if is_success(fields):
            fields["amount"] = amount
            fields["chatgpt_checkout_url"] = f"https://chatgpt.com/checkout/{processor}/{cs_id}"
            fields["billing"] = billing
            return {"ok": True, "amount": amount, "fields": fields, "billing": billing}

        log("[6/6] approve + poll UPI")
        chatgpt_approve(token, cs_id, processor, p3, device_id, log)
        last_err: dict[str, Any] = {}
        for i in range(1, 16):
            page_data = page_get(stripe, cs_id, pk, ctx)
            fields = extract_upi_result(page_data, cs_id)
            sub = find_submission_attempt(page_data)
            err = sub.get("error") if isinstance(sub.get("error"), dict) else {}
            log(f"poll {i}/15 sub={sub.get('state')} err={err.get('code') if err else '-'} success={is_success(fields)}")
            if is_success(fields):
                fields["amount"] = amount
                fields["chatgpt_checkout_url"] = f"https://chatgpt.com/checkout/{processor}/{cs_id}"
                fields["billing"] = billing
                return {"ok": True, "amount": amount, "fields": fields, "billing": billing}
            if sub.get("state") == "failed":
                last_err = err or {}
                raise RuntimeError(f"approve 后失败: {last_err.get('code')}")
            time.sleep(1.0)
        raise RuntimeError("轮询超时，未拿到 UPI 链接")
