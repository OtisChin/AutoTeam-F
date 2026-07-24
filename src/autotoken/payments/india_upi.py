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
from curl_cffi.requests import Session as CurlCffiSession

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
    promo_region: str = "VN"
    direct_proxies: list[str] = field(default_factory=list)
    apply_promo: bool = False
    preflighted_checkout_proxy_url: str = ""


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
    target_region = str(region or "IN").strip().upper() or "IN"
    fresh = uuid.uuid4().hex[:8]
    refreshed, region_count = re.subn(
        r"([_-]region[-_])[A-Z]{2}([:@/?#&-])",
        lambda m: f"{m.group(1)}{target_region}{m.group(2)}",
        proxy_url,
        count=1,
        flags=re.I,
    )
    refreshed, sid_count = re.subn(r"(sid-)[^-:@/?#]+(-t-)", rf"\g<1>{fresh}\g<2>", refreshed, count=1)
    refreshed, session_count = re.subn(
        r"(-session-)[^-:@/?#]+",
        rf"\g<1>{fresh}",
        refreshed,
        count=1,
        flags=re.I,
    )
    if sid_count or session_count:
        return refreshed, fresh

    # 711proxy also accepts a shorter, region-only username:
    #   USER...-zone-custom-region-IN:password@global.rotgb.711proxy.com:10000
    # In that shape the region rewrite above can change IN/VN, but there is no
    # session key to rotate.  Returning a fresh sid label would be misleading:
    # retries would keep using the exact same proxy credentials.  Inject the
    # provider's session suffix so every attempt/stage can get a distinct
    # provider session even when the shorter 711 format is pasted.
    if "711proxy" in refreshed.lower() and "-session-" not in refreshed.lower():
        refreshed_with_session, injected_count = re.subn(
            r"([_-]region[-_][A-Z]{2})(?=[:@/?#&-])",
            rf"\g<1>-session-{fresh}-sessTime-180-sessAuto-1",
            refreshed,
            count=1,
            flags=re.I,
        )
        if injected_count:
            return refreshed_with_session, fresh

    if region_count:
        return refreshed, "static"

    proxy, sid = pix_proxy_with_fresh_sid(proxy_url, target_region)
    if sid != "static":
        return proxy, sid
    refreshed, count = re.subn(r"(-session-)[A-Za-z0-9]+", rf"\g<1>{fresh}", proxy, count=1, flags=re.I)
    if count:
        return refreshed, fresh
    refreshed, count = re.subn(
        r"([_-]region[-_])[A-Z]{2}([:@/?#&-])",
        lambda m: f"{m.group(1)}{target_region}{m.group(2)}",
        proxy,
        count=1,
        flags=re.I,
    )
    if count:
        return refreshed, fresh
    refreshed, count = re.subn(
        r"(:[^:@/?#]*-)[A-Z]{2}-[A-Za-z0-9]{4,32}(@)",
        lambda m: f"{m.group(1)}{target_region}-{fresh}{m.group(2)}",
        proxy,
        count=1,
        flags=re.I,
    )
    if count:
        return refreshed, fresh
    return proxy, sid


def build_upi_dynamic_proxy(cfg: UpiJobConfig, stage_index: int, region: str | None = None) -> tuple[str, str]:
    effective_region = str(region or cfg.region or "IN").strip().upper() or "IN"
    preflighted = normalize_upi_proxy_url(getattr(cfg, "preflighted_checkout_proxy_url", ""))
    if stage_index == 0 and preflighted and effective_region == (str(cfg.region or "IN").strip().upper() or "IN"):
        return preflighted, "preflighted"
    direct = [normalize_upi_proxy_url(item) for item in (cfg.direct_proxies or []) if str(item or "").strip()]
    if direct:
        idx = stage_index % len(direct)
        proxy, sid = upi_proxy_with_fresh_sid(direct[idx], effective_region)
        return proxy, f"direct-{idx + 1} sid={sid}" if sid and sid != "static" else f"direct-{idx + 1} static"
    return build_kookeey_proxy(cfg.kookeey_user, cfg.kookeey_pass, cfg.kookeey_endpoint, effective_region)


def new_http_session(proxy_url: str = "") -> requests.Session:
    try:
        session = CurlCffiSession(impersonate="chrome136")
    except Exception:
        session = requests.Session()
    if hasattr(session, "trust_env"):
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


def _browser_timezone_offset_min() -> int:
    local_utc_offset_seconds = -time.timezone
    if time.daylight and time.localtime().tm_isdst > 0:
        local_utc_offset_seconds = -time.altzone
    return int(-local_utc_offset_seconds / 60)


def warm_chatgpt_checkout_context(chatgpt: requests.Session, country: str, log: LogFn | None = None) -> None:
    log = log or (lambda _m: None)
    getter = getattr(chatgpt, "get", None)
    poster = getattr(chatgpt, "post", None)
    if not callable(getter):
        return
    target_country = str(country or "IN").strip().upper() or "IN"
    warmups = [
        (
            f"https://chatgpt.com/backend-api/accounts/check/v4-2023-04-27?timezone_offset_min={_browser_timezone_offset_min()}",
            "/backend-api/accounts/check/v4-2023-04-27",
        ),
        ("https://chatgpt.com/backend-api/accounts/domain-density-eligibility", "/backend-api/accounts/domain-density-eligibility"),
        ("https://chatgpt.com/backend-api/checkout_pricing_config/countries", "/backend-api/checkout_pricing_config/countries"),
        (
            f"https://chatgpt.com/backend-api/checkout_pricing_config/configs/{target_country}",
            f"/backend-api/checkout_pricing_config/configs/{target_country}",
        ),
    ]
    statuses: list[str] = []
    for url, target_path in warmups:
        try:
            resp = getter(
                url,
                headers={"x-openai-target-path": target_path, "x-openai-target-route": target_path},
                timeout=8,
            )
            statuses.append(f"{target_path.rsplit('/', 1)[-1]}={getattr(resp, 'status_code', 0)}")
        except Exception as exc:
            statuses.append(f"{target_path.rsplit('/', 1)[-1]}={type(exc).__name__}")
    if callable(poster):
        try:
            resp = poster(
                "https://chatgpt.com/backend-api/sentinel/ping",
                json={},
                headers={
                    "x-openai-target-path": "/backend-api/sentinel/ping",
                    "x-openai-target-route": "/backend-api/sentinel/ping",
                },
                timeout=8,
            )
            statuses.append(f"sentinel={getattr(resp, 'status_code', 0)}")
        except Exception as exc:
            statuses.append(f"sentinel={type(exc).__name__}")
    log("checkout warmup: " + " ".join(statuses))


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


def sync_upi_tax_region(
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
            "billing_country": "IN",
            "billing_name": billing["name"],
            "currency": "INR",
            "tax_id": None,
            "processor_entity": processor,
            "billing_address": {
                "line1": billing["line1"],
                "city": billing["city"],
                "state": billing["state"],
                "country": "IN",
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
            "tax_region[country]": "IN",
            "tax_region[postal_code]": billing["postal_code"],
            "tax_region[line1]": billing["line1"],
            "tax_region[city]": billing["city"],
            "tax_region[state]": billing["state"],
            "key": stripe_pk,
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"stripe tax_region failed: HTTP {resp.status_code} {short(resp.text)}")


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


ACTIONABLE_UPI_INTENT_STATES = {"requires_action", "requires_source_action"}
NON_ACTIONABLE_UPI_INTENT_STATES = {
    "canceled",
    "processing",
    "requires_capture",
    "requires_confirmation",
    "requires_payment_method",
    "succeeded",
}


def _is_actionable_upi_state(state: str) -> bool:
    normalized = str(state or "").strip().lower()
    return not normalized or normalized in ACTIONABLE_UPI_INTENT_STATES


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
        "intent_type": "",
        "intent_state": "",
        "intent_usage": "",
        "intent_error_code": "",
        "intent_decline_code": "",
        "upi_vpa_present": "",
        "client_secret": "",
    }

    if isinstance(payload, dict):
        sub = find_submission_attempt(payload)
        out["submission_state"] = str(sub.get("state") or "")
        out["intent_state"] = str(payload.get("intent_state") or "")
        out["client_secret"] = str(payload.get("client_secret") or "")

        def capture_intent_metadata(obj: dict[str, Any]) -> bool:
            obj_id = str(obj.get("id") or "")
            client_secret = str(obj.get("client_secret") or "")
            is_intent = obj_id.startswith(("pi_", "seti_")) or client_secret.startswith(("pi_", "seti_"))
            if not is_intent:
                return False
            if obj_id.startswith(("pi_", "seti_")):
                out["payment_intent"] = obj_id
            elif client_secret.startswith(("pi_", "seti_")):
                out["payment_intent"] = client_secret.split("_secret_", 1)[0]
            intent_id = out["payment_intent"]
            if intent_id.startswith("seti_"):
                out["intent_type"] = "setup_intent"
            elif intent_id.startswith("pi_"):
                out["intent_type"] = "payment_intent"
            if client_secret and not out["client_secret"]:
                out["client_secret"] = client_secret
            state = str(obj.get("status") or obj.get("intent_state") or "")
            if state:
                out["intent_state"] = state
            usage = str(obj.get("usage") or "")
            if usage:
                out["intent_usage"] = usage
            last_error = obj.get("last_setup_error") or obj.get("last_payment_error") or {}
            if isinstance(last_error, dict) and last_error:
                out["intent_error_code"] = str(last_error.get("code") or "")
                out["intent_decline_code"] = str(last_error.get("decline_code") or "")
                pm = last_error.get("payment_method") if isinstance(last_error.get("payment_method"), dict) else {}
                upi = pm.get("upi") if isinstance(pm.get("upi"), dict) else {}
                if isinstance(upi, dict):
                    out["upi_vpa_present"] = "yes" if str(upi.get("vpa") or "").strip() else "no"
            return True

        def capture_upi_next_action(obj: dict[str, Any], na: dict[str, Any]) -> None:
            action_type = str(na.get("type") or "")
            if action_type:
                out["next_action_type"] = action_type
            if action_type and action_type != "upi_handle_redirect_or_display_qr_code":
                return
            state = str(obj.get("status") or obj.get("intent_state") or out["intent_state"] or "")
            if not _is_actionable_upi_state(state):
                return
            box = na.get("upi_handle_redirect_or_display_qr_code") or {}
            if not isinstance(box, dict):
                return
            hosted = str(box.get("hosted_instructions_url") or "")
            if hosted and "intent_path" not in hosted:
                out["upi_link"] = out["hosted_instructions_url"] = hosted
            mobile = str(box.get("mobile_auth_url") or "")
            if mobile.startswith("upi://") and not out["upi_link"]:
                out["upi_link"] = mobile
            qr = box.get("qr_code") if isinstance(box.get("qr_code"), dict) else {}
            if isinstance(qr, dict):
                out["qr_image_url_png"] = str(qr.get("image_url_png") or out["qr_image_url_png"])
                out["qr_image_url_svg"] = str(qr.get("image_url_svg") or out["qr_image_url_svg"])
                out["qr_expires_at"] = str(qr.get("expires_at") or out["qr_expires_at"])

        def walk(obj: Any) -> None:
            if isinstance(obj, dict):
                is_intent = capture_intent_metadata(obj)
                na = obj.get("next_action")
                if is_intent and isinstance(na, dict):
                    capture_upi_next_action(obj, na)
                for value in obj.values():
                    walk(value)
            elif isinstance(obj, list):
                for item in obj:
                    walk(item)

        walk(payload)

        # A hosted-instructions page exposes the current intent state at the top
        # level.  Do not treat links copied from unrelated fields as success when
        # Stripe says the intent is no longer actionable.
        if not _is_actionable_upi_state(out["intent_state"]):
            out["upi_link"] = ""
            out["hosted_instructions_url"] = ""
    else:
        matched = re.search(r"https://payments\.stripe\.com/upi/instructions/[A-Za-z0-9_\-]+", text)
        if matched:
            out["upi_link"] = matched.group(0)
            out["hosted_instructions_url"] = matched.group(0)
        matched = re.search(r"upi://[^\s\"']+", text)
        if matched and not out["upi_link"]:
            out["upi_link"] = matched.group(0)

    matched = re.search(r"(?:pi|seti)_[A-Za-z0-9]+", text)
    if matched and "hcaptcha" not in matched.group(0) and not out["payment_intent"]:
        out["payment_intent"] = matched.group(0)
    return out


def upi_fields_summary(fields: dict[str, Any]) -> str:
    error_bits = []
    if fields.get("intent_error_code"):
        error_bits.append(str(fields.get("intent_error_code")))
    if fields.get("intent_decline_code"):
        error_bits.append(str(fields.get("intent_decline_code")))
    error_text = "/".join(error_bits) if error_bits else "-"
    return (
        f"intent={fields.get('payment_intent') or '-'} "
        f"intent_type={fields.get('intent_type') or '-'} "
        f"intent_state={fields.get('intent_state') or '-'} "
        f"intent_usage={fields.get('intent_usage') or '-'} "
        f"next_action={fields.get('next_action_type') or '-'} "
        f"intent_error={error_text} "
        f"upi_vpa={fields.get('upi_vpa_present') or '-'} "
        f"link={'yes' if fields.get('upi_link') or fields.get('hosted_instructions_url') else 'no'}"
    )


def is_success(fields: dict[str, Any]) -> bool:
    link = str(fields.get("upi_link") or fields.get("hosted_instructions_url") or "")
    if not (link.startswith("https://payments.stripe.com/upi/instructions/") or link.startswith("upi://")):
        return False
    if str(fields.get("submission_state") or "").strip().lower() == "failed":
        return False
    state = str(fields.get("intent_state") or "").strip().lower()
    if state in NON_ACTIONABLE_UPI_INTENT_STATES:
        return False
    action_type = str(fields.get("next_action_type") or "").strip()
    return not action_type or action_type == "upi_handle_redirect_or_display_qr_code"


def chatgpt_approve(access_token: str, cs_id: str, processor: str, proxy_url: str, device_id: str, log: LogFn) -> None:
    last_err = ""
    for attempt in range(1, 4):
        approve_proxy = proxy_url
        if attempt > 1 and proxy_url:
            approve_proxy, sid = upi_proxy_with_fresh_sid(proxy_url, "IN")
            if sid and sid != "static":
                log(f"approve attempt {attempt}: refresh proxy sid={sid}")
        cg = build_chatgpt_session(access_token, approve_proxy, device_id)
        try:
            try:
                cg.post(
                    "https://chatgpt.com/backend-api/sentinel/ping",
                    json={},
                    headers={
                        "Referer": "https://chatgpt.com/",
                        "x-openai-target-path": "/backend-api/sentinel/ping",
                        "x-openai-target-route": "/backend-api/sentinel/ping",
                    },
                    timeout=TIMEOUT,
                )
            except Exception:
                pass
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
    log(f"[1/6] IN 创建 checkout（先不带 promo） sid={sid1}")
    with pix_proxy_context(cfg.local_proxy, dyn1, log) as chain1:
        p1 = chain1.url
        cg = build_chatgpt_session(token, p1, device_id)
        warm_chatgpt_checkout_context(cg, "IN", log)
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

        if cfg.apply_promo:
            time.sleep(0.8)
            stripe0 = build_stripe_session(p1)
            ctx0 = _ctx()
            init0 = stripe_init(stripe0, cs_id, pk, ctx0)
            amt0 = amount_info(init0)
            pmt0, ordered0, has_upi0 = pmt_info(init0)
            log(f"创建后金额={amt0} 支付方式={pmt0} ordered={ordered0} has_upi={has_upi0}")
            if not has_upi0:
                raise RuntimeError(f"创建后未出现 UPI，pmt={pmt0}")

    promo_region = str(cfg.promo_region or "VN").strip().upper() or "VN"
    dyn2, sid2 = build_upi_dynamic_proxy(cfg, 1, promo_region)
    if cfg.apply_promo:
        log(f"[2/6] {promo_region} update 套试用 promo sid={sid2}")
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
                    "billing_details": {"country": promo_region, "currency": "VND" if promo_region == "VN" else "INR"},
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
        init_payload: dict[str, Any] = {}
        amount = ""
        pmt: list[Any] = []
        ordered: list[Any] = []
        has_upi = False
        max_init_attempts = 4 if cfg.apply_promo else 1
        for init_attempt in range(1, max_init_attempts + 1):
            if cfg.apply_promo:
                time.sleep(0.8 if init_attempt == 1 else 1.0)
            init_payload = stripe_init(stripe, cs_id, pk, ctx)
            amount = amount_info(init_payload)
            pmt, ordered, has_upi = pmt_info(init_payload)
            prefix = "套 promo 后" if cfg.apply_promo else ""
            log(f"{prefix}金额={amount} 支付方式={pmt} ordered={ordered} has_upi={has_upi} init_attempt={init_attempt}")
            if not has_upi:
                raise RuntimeError(f"{'套 promo 后' if cfg.apply_promo else ''}未出现 UPI，pmt={pmt}")
            if not cfg.apply_promo or amount in ("0", "0.0"):
                break
            if init_attempt < max_init_attempts:
                log(f"套 promo 后金额仍非 0，等待后重试 Stripe init: {amount}")
        if cfg.apply_promo and amount not in ("0", "0.0"):
            raise RuntimeError(f"套 promo 后金额不是 0: {amount}")

        log("[4/7] 同步 IN taxes / Stripe tax_region")
        cg3 = build_chatgpt_session(token, p3, device_id)
        checkout_email = str(billing.get("email") or "")
        sync_upi_tax_region(cg3, stripe, cs_id=cs_id, stripe_pk=pk, processor=processor, checkout_email=checkout_email, billing=billing)
        time.sleep(0.5)
        init_payload = stripe_init(stripe, cs_id, pk, ctx)
        amount = amount_info(init_payload)
        pmt, ordered, has_upi = pmt_info(init_payload)
        prefix = "tax sync 后" if cfg.apply_promo else "tax sync 后"
        log(f"{prefix}金额={amount} 支付方式={pmt} ordered={ordered} has_upi={has_upi}")
        if not has_upi:
            raise RuntimeError(f"tax sync 后未出现 UPI，pmt={pmt}")
        if cfg.apply_promo and amount not in ("0", "0.0"):
            raise RuntimeError(f"tax sync 后金额不是 0: {amount}")

        hosted = str(init_payload.get("stripe_hosted_url") or "")
        log("[5/7] 创建 UPI payment_method")
        time.sleep(0.6)
        pm_id = _create_upi_payment_method(stripe, cs_id=cs_id, stripe_pk=pk, ctx=ctx, billing=billing)
        log(f"pm_id={pm_id}")

        log("[6/7] confirm UPI")
        time.sleep(0.7)
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
        log(f"confirm submission={sub.get('state')} {upi_fields_summary(fields)}")
        if is_success(fields):
            fields["amount"] = amount
            fields["chatgpt_checkout_url"] = f"https://chatgpt.com/checkout/{processor}/{cs_id}"
            fields["billing"] = billing
            return {"ok": True, "amount": amount, "fields": fields, "billing": billing}

        log("[7/7] approve + poll UPI")
        chatgpt_approve(token, cs_id, processor, p3, device_id, log)
        last_err: dict[str, Any] = {}
        for i in range(1, 16):
            page_data = page_get(stripe, cs_id, pk, ctx)
            fields = extract_upi_result(page_data, cs_id)
            sub = find_submission_attempt(page_data)
            err = sub.get("error") if isinstance(sub.get("error"), dict) else {}
            log(
                f"poll {i}/15 sub={sub.get('state')} err={err.get('code') if err else '-'} "
                f"success={is_success(fields)} {upi_fields_summary(fields)}"
            )
            if is_success(fields):
                fields["amount"] = amount
                fields["chatgpt_checkout_url"] = f"https://chatgpt.com/checkout/{processor}/{cs_id}"
                fields["billing"] = billing
                return {"ok": True, "amount": amount, "fields": fields, "billing": billing}
            if sub.get("state") == "failed":
                last_err = err or {}
                pe = last_err.get("payment_error") if isinstance(last_err.get("payment_error"), dict) else {}
                raise RuntimeError(
                    f"approve 后失败: {last_err.get('code')} "
                    f"payment_error={pe.get('code')}/{pe.get('decline_code')} "
                    f"{upi_fields_summary(fields)}"
                )
            time.sleep(1.0)
        raise RuntimeError("轮询超时，未拿到 UPI 链接")
