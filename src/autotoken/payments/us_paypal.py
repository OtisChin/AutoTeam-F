"""US PayPal checkout link extraction core."""

from __future__ import annotations

import random
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit

import requests

from autotoken.payments.brazil_pix import (
    DEFAULT_STRIPE_PK,
    DEFAULT_USER_AGENT,
    TIMEOUT,
    build_kookeey_proxy,
    extract_pk,
    pix_proxy_context,
    pix_proxy_with_fresh_sid,
    short,
    to_openai_pay_url,
)

LogFn = Callable[[str], None]

PAYPAL_STRIPE_VERSION = "2020-08-27;custom_checkout_beta=v1; checkout_server_update_beta=v1; checkout_manual_approval_preview=v1"
PAYPAL_STRIPE_RUNTIME_VERSION = "81274c9437"
PAYPAL_BA_APPROVE_BASE = "https://www.paypal.com/agreements/approve"
PAYPAL_BA_TOKEN_RE = re.compile(r"(?i)ba_token[=:%22'\\\s]+(?P<token>BA-[A-Za-z0-9_-]+)")
PAYPAL_BA_APPROVE_RE = re.compile(
    r"(?i)(?:(?:https?:)?//)?(?:www\.)?paypal\.com/agreements/approve\?[^\\\s\"'<>]*?ba_token=(?P<token>BA-[A-Za-z0-9_-]+)"
)

US_ADDRESSES = [
    # Prefer states without sales tax so ChatGPT approval and Stripe amount stay aligned.
    ("John", "Miller", "121 SW Morrison Street", "Portland", "OR", "97204"),
    ("Sarah", "Clark", "1000 SW Broadway", "Portland", "OR", "97205"),
    ("Emily", "Lewis", "1201 N Market Street", "Wilmington", "DE", "19801"),
    ("James", "Anderson", "100 N Main Street", "Concord", "NH", "03301"),
    ("Robert", "Thomas", "101 N Last Chance Gulch", "Helena", "MT", "59601"),
]

PAYPAL_COUNTRY_CURRENCIES = {
    "US": "USD",
    "GB": "GBP",
    "CA": "CAD",
    "AU": "AUD",
    "JP": "JPY",
    "BR": "BRL",
    "VN": "VND",
    "DE": "EUR",
    "FR": "EUR",
    "IT": "EUR",
    "ES": "EUR",
    "NL": "EUR",
    "IE": "EUR",
    "PT": "EUR",
    "AT": "EUR",
    "BE": "EUR",
    "FI": "EUR",
    "SG": "SGD",
    "HK": "HKD",
    "TW": "TWD",
    "KR": "KRW",
    "MX": "MXN",
    "NZ": "NZD",
}

PAYPAL_COUNTRY_BILLING_PRESETS = {
    "GB": ("Olivia Brown", "221B Baker Street", "London", "", "NW1 6XE"),
    "CA": ("Noah Wilson", "100 Queen Street W", "Toronto", "ON", "M5H 2N2"),
    "AU": ("Charlotte Taylor", "1 Macquarie Street", "Sydney", "NSW", "2000"),
    "JP": ("Yuki Tanaka", "1-1 Chiyoda", "Tokyo", "", "100-0001"),
    "BR": ("Lucas Silva", "Rua da Consolacao 787", "Sao Paulo", "SP", "01301-000"),
    "VN": ("Minh Nguyen", "1 Dong Khoi", "Ho Chi Minh City", "", "700000"),
    "DE": ("Lukas Weber", "Unter den Linden 1", "Berlin", "", "10117"),
    "FR": ("Emma Martin", "10 Rue de Rivoli", "Paris", "", "75004"),
    "IT": ("Marco Rossi", "Via del Corso 1", "Rome", "", "00186"),
    "ES": ("Lucia Garcia", "Calle de Alcala 1", "Madrid", "", "28014"),
    "NL": ("Daan de Vries", "Damrak 1", "Amsterdam", "", "1012 LG"),
    "SG": ("Wei Tan", "1 Raffles Place", "Singapore", "", "048616"),
    "HK": ("Ho Chan", "1 Connaught Road Central", "Hong Kong", "", "000000"),
    "TW": ("Chen Lin", "No. 1 Xinyi Road", "Taipei", "", "100"),
    "KR": ("Min Kim", "1 Sejong-daero", "Seoul", "", "04524"),
    "MX": ("Sofia Hernandez", "Avenida Reforma 1", "Ciudad de Mexico", "", "06000"),
    "NZ": ("Amelia Smith", "1 Queen Street", "Auckland", "", "1010"),
}


@dataclass
class PaypalJobConfig:
    access_token: str
    local_proxy: str = ""
    kookeey_user: str = ""
    kookeey_pass: str = ""
    kookeey_endpoint: str = "gate.kookeey.info:1000"
    region: str = "US"
    promo_region: str = "JP"
    direct_proxies: list[str] = field(default_factory=list)
    apply_promo: bool = False


def normalize_paypal_proxy_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "://" in raw:
        return raw
    parts = raw.split(":", 3)
    if len(parts) == 4 and parts[1].isdigit():
        host, port, user, password = parts
        return f"socks5h://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}"
    return f"http://{raw}"


def paypal_proxy_with_fresh_sid(proxy_url: str, region: str = "US") -> tuple[str, str]:
    fresh = uuid.uuid4().hex[:8]
    target_region = str(region or "US").strip().upper() or "US"
    proxy = str(proxy_url or "").strip()
    if not proxy:
        return "", ""

    refreshed, region_count = re.subn(
        r"([_-]region[-_])[A-Z]{2}([:@/?#&-])",
        lambda m: f"{m.group(1)}{target_region}{m.group(2)}",
        proxy,
        count=1,
        flags=re.I,
    )
    refreshed, sid_count = re.subn(r"(sid-)[^-:@/?#]+(-t-)", rf"\g<1>{fresh}\g<2>", refreshed, count=1, flags=re.I)
    refreshed, session_count = re.subn(
        r"(-session-)[^-:@/?#]+",
        rf"\g<1>{fresh}",
        refreshed,
        count=1,
        flags=re.I,
    )
    if sid_count or session_count:
        return refreshed, fresh

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

    refreshed_kookeey, kookeey_count = re.subn(
        r"(:[^:@/?#]*-)[A-Z]{2}-[A-Za-z0-9]{4,32}(@)",
        lambda m: f"{m.group(1)}{target_region}-{fresh}{m.group(2)}",
        refreshed,
        count=1,
        flags=re.I,
    )
    if kookeey_count:
        return refreshed_kookeey, fresh

    if region_count:
        return refreshed, "static"

    proxy_fallback, sid = pix_proxy_with_fresh_sid(proxy, target_region)
    if sid != "static":
        return proxy_fallback, sid
    return proxy_fallback, sid


def align_paypal_proxy_region(proxy_url: str, region: str = "US") -> str:
    target = str(region or "US").strip().upper() or "US"
    return re.sub(
        r"([_-]region[-_])[A-Z]{2}([:@/?#&-])",
        lambda m: f"{m.group(1)}{target}{m.group(2)}",
        proxy_url,
        count=1,
        flags=re.I,
    )


def build_paypal_dynamic_proxy(cfg: PaypalJobConfig, stage_index: int, region: str | None = None) -> tuple[str, str]:
    target_region = str(region or cfg.region or "US").strip().upper() or "US"
    direct = [
        align_paypal_proxy_region(normalize_paypal_proxy_url(item), target_region)
        for item in (cfg.direct_proxies or [])
        if str(item or "").strip()
    ]
    if direct:
        idx = stage_index % len(direct)
        proxy, sid = paypal_proxy_with_fresh_sid(direct[idx], target_region)
        suffix = f" sid={sid}" if sid and sid != "static" else " static"
        return proxy, f"direct-{idx + 1} region={target_region}{suffix}"
    return build_kookeey_proxy(cfg.kookeey_user, cfg.kookeey_pass, cfg.kookeey_endpoint, target_region)


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
            "Accept-Language": "en-US,en;q=0.9",
            "Authorization": f"Bearer {access_token}",
            "Origin": "https://chatgpt.com",
            "Referer": "https://chatgpt.com/",
            "Content-Type": "application/json",
            "oai-device-id": device_id,
            "oai-language": "en-US",
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
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://pay.openai.com",
            "Referer": "https://pay.openai.com/",
            "sec-fetch-site": "cross-site",
            "sec-fetch-mode": "cors",
            "sec-fetch-dest": "empty",
        }
    )
    return session


def normalize_paypal_country(value: str, default: str = "US") -> str:
    country = str(value or default or "US").strip().upper()
    return country if re.fullmatch(r"[A-Z]{2}", country) else default


def paypal_currency_for_country(country: str) -> str:
    return PAYPAL_COUNTRY_CURRENCIES.get(normalize_paypal_country(country), "USD")


def paypal_billing(account_email: str = "", country: str = "US") -> dict[str, str]:
    country_code = normalize_paypal_country(country)
    if country_code != "US" and country_code in PAYPAL_COUNTRY_BILLING_PRESETS:
        name, line1, city, state, postal = PAYPAL_COUNTRY_BILLING_PRESETS[country_code]
        return {
            "name": name,
            "email": account_email or f"paypal.{country_code.lower()}.{random.randint(1000, 9999)}@example.com",
            "country": country_code,
            "line1": line1,
            "city": city,
            "state": state,
            "postal_code": postal,
        }
    first, last, line1, city, state, postal = random.choice(US_ADDRESSES)
    suffix = random.randint(1000, 9999)
    return {
        "name": f"{first} {last}",
        "email": account_email or f"{first.lower()}.{last.lower()}{suffix}@example.com",
        "country": country_code,
        "line1": line1,
        "city": city,
        "state": state,
        "postal_code": postal,
    }


def us_billing(account_email: str = "") -> dict[str, str]:
    return paypal_billing(account_email, "US")


def pmt_info(payload: dict[str, Any]) -> tuple[list[Any], list[Any], bool]:
    pmt = payload.get("payment_method_types") or []
    ordered = payload.get("ordered_payment_method_types") or []
    methods = [str(item).lower() for item in list(pmt) + list(ordered)]
    return pmt, ordered, "paypal" in methods


def amount_info(payload: dict[str, Any]) -> str:
    total_summary = payload.get("total_summary") if isinstance(payload.get("total_summary"), dict) else {}
    invoice = payload.get("invoice") if isinstance(payload.get("invoice"), dict) else {}
    if total_summary.get("due") is not None:
        return str(total_summary.get("due"))
    if invoice.get("amount_due") is not None:
        return str(invoice.get("amount_due"))
    return "0"


def is_zero_amount(value: Any) -> bool:
    text = str(value if value is not None else "").strip()
    if not text:
        return False
    try:
        return float(text) == 0.0
    except Exception:
        return text in {"0", "0.0", "0.00"}


def promo_currency_for_region(region: str) -> str:
    return {"JP": "JPY", "BR": "BRL", "VN": "VND"}.get(str(region or "").strip().upper(), "USD")


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


def stripe_init(stripe: requests.Session, cs_id: str, stripe_pk: str, ctx: dict[str, str]) -> dict[str, Any]:
    resp = stripe.post(
        f"https://api.stripe.com/v1/payment_pages/{cs_id}/init",
        data={
            "browser_locale": "en-US",
            "browser_timezone": "America/Los_Angeles",
            "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
            "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
            "elements_session_client[elements_init_source]": "custom_checkout",
            "elements_session_client[referrer_host]": "chatgpt.com",
            "elements_session_client[stripe_js_id]": ctx["stripe_js_id"],
            "elements_session_client[locale]": "en-US",
            "elements_session_client[is_aggregation_expected]": "false",
            "elements_options_client[saved_payment_method][enable_save]": "never",
            "elements_options_client[saved_payment_method][enable_redisplay]": "never",
            "key": stripe_pk,
            "_stripe_version": PAYPAL_STRIPE_VERSION,
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


def stripe_update_tax_region(stripe: requests.Session, cs_id: str, stripe_pk: str, billing: dict[str, str]) -> None:
    bodies = [{"eid": "NA", "tax_region[country]": billing["country"], "key": stripe_pk}]
    if billing.get("state"):
        bodies.append({"eid": "NA", "tax_region[country]": billing["country"], "tax_region[state]": billing["state"], "key": stripe_pk})
    for body in bodies:
        resp = stripe.post(f"https://api.stripe.com/v1/payment_pages/{cs_id}", data=body, timeout=TIMEOUT)
        if resp.status_code >= 400:
            raise RuntimeError(f"stripe tax region update failed: HTTP {resp.status_code} {short(resp.text)}")


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
            "elements_session_client[locale]": "en-US",
            "elements_session_client[is_aggregation_expected]": "false",
            "elements_options_client[saved_payment_method][enable_save]": "never",
            "elements_options_client[saved_payment_method][enable_redisplay]": "never",
            "key": stripe_pk,
            "_stripe_version": PAYPAL_STRIPE_VERSION,
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


def _iter_text_values(payload: Any) -> list[str]:
    values: list[str] = []
    if isinstance(payload, str):
        values.append(payload)
    elif isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(key, str):
                values.append(key)
            if isinstance(value, (str, int, float)):
                values.append(f"{key}={value}")
            values.extend(_iter_text_values(value))
    elif isinstance(payload, list):
        for item in payload:
            values.extend(_iter_text_values(item))
    return values


def is_paypal_ba_approve_url(value: str) -> bool:
    try:
        parsed = urlsplit(str(value or "").strip())
    except Exception:
        return False
    host = (parsed.netloc or "").lower()
    if not (host == "paypal.com" or host.endswith(".paypal.com")):
        return False
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    return parsed.path.rstrip("/").lower() == "/agreements/approve" and bool(str(query.get("ba_token") or "").strip())


def paypal_ba_approve_url_from_token(token: str) -> str:
    token = str(token or "").strip().strip(" \t\r\n\"'<>),.;]}")
    return f"{PAYPAL_BA_APPROVE_BASE}?ba_token={quote(token, safe='')}" if token else ""


def extract_paypal_ba_approve_url(payload: Any) -> str:
    for raw in _iter_text_values(payload):
        text = str(raw or "").replace("\\/", "/").replace("\\u0026", "&").replace("&amp;", "&")
        try:
            text = unquote(text)
        except Exception:
            pass
        if is_paypal_ba_approve_url(text):
            token = dict(parse_qsl(urlsplit(text).query, keep_blank_values=True)).get("ba_token") or ""
            return paypal_ba_approve_url_from_token(unquote(token))
        for pattern in (PAYPAL_BA_APPROVE_RE, PAYPAL_BA_TOKEN_RE):
            match = pattern.search(text)
            if match:
                return paypal_ba_approve_url_from_token(unquote(match.group("token")))
    return ""


def find_redirect_url_string(payload: Any, preferred_hosts: tuple[str, ...] = ()) -> str:
    preferred = tuple(host.lower().lstrip(".") for host in preferred_hosts if host)

    def good_url(value: str) -> bool:
        if not value.startswith(("http://", "https://")):
            return False
        host = (urlsplit(value).netloc or "").lower()
        return not preferred or any(host == item or host.endswith(f".{item}") for item in preferred)

    if isinstance(payload, str):
        value = payload.strip()
        return value if good_url(value) else ""
    if isinstance(payload, dict):
        for key in ("url", "redirect_url", "return_url", "hosted_url"):
            found = find_redirect_url_string(payload.get(key), preferred_hosts)
            if found:
                return found
        for value in payload.values():
            found = find_redirect_url_string(value, preferred_hosts)
            if found:
                return found
    if isinstance(payload, list):
        for value in payload:
            found = find_redirect_url_string(value, preferred_hosts)
            if found:
                return found
    return ""


def extract_redirect_to_url(payload: Any) -> str:
    ba_approve_url = extract_paypal_ba_approve_url(payload)
    if ba_approve_url:
        return ba_approve_url
    if isinstance(payload, dict):
        next_action = payload.get("next_action")
        if isinstance(next_action, dict) and next_action.get("type") == "redirect_to_url":
            redirect_to_url = next_action.get("redirect_to_url") or {}
            if isinstance(redirect_to_url, dict) and str(redirect_to_url.get("url") or "").strip():
                return str(redirect_to_url.get("url") or "").strip()
        for key in ("setup_intent", "payment_intent", "submission_attempt", "latest_attempt", "session"):
            found = extract_redirect_to_url(payload.get(key))
            if found:
                return found
        nested_url = find_redirect_url_string(payload, ("pm-redirects.stripe.com", "paypal.com"))
        if nested_url and "docs/error-codes" not in nested_url:
            return nested_url
    return ""


def extract_paypal_result(payload: Any, cs_id: str = "") -> dict[str, str]:
    redirect_url = extract_redirect_to_url(payload)
    fields = {
        "paypal_link": "",
        "provider_redirect_url": "",
        "stripe_redirect_url": "",
        "ba_token": "",
        "cs_id": cs_id,
        "submission_state": "",
        "next_action_type": "",
        "setup_intent": "",
    }
    if is_paypal_ba_approve_url(redirect_url):
        fields["paypal_link"] = fields["provider_redirect_url"] = redirect_url
    elif redirect_url:
        fields["stripe_redirect_url"] = redirect_url
        if "pm-redirects.stripe.com" in redirect_url:
            fields["paypal_link"] = redirect_url
    token_match = re.search(r"BA-[A-Za-z0-9_-]+", fields["provider_redirect_url"] or fields["paypal_link"])
    if token_match:
        fields["ba_token"] = token_match.group(0)
    if isinstance(payload, dict):
        sub = find_submission_attempt(payload)
        fields["submission_state"] = str(sub.get("state") or "")
        setup_intent = payload.get("setup_intent")
        if isinstance(setup_intent, dict):
            fields["setup_intent"] = str(setup_intent.get("id") or "")
        next_action = payload.get("next_action")
        if isinstance(next_action, dict):
            fields["next_action_type"] = str(next_action.get("type") or "")
    return fields


def is_success(fields: dict[str, Any]) -> bool:
    link = str(fields.get("paypal_link") or fields.get("provider_redirect_url") or fields.get("stripe_redirect_url") or "")
    return link.startswith("https://pm-redirects.stripe.com/authorize/") or is_paypal_ba_approve_url(link)


def resolve_external_redirect(stripe: requests.Session, redirect_url: str, max_hops: int = 5) -> str:
    current = str(redirect_url or "").strip()
    for _ in range(max(1, int(max_hops or 1))):
        if not current:
            return ""
        ba_approve_url = extract_paypal_ba_approve_url(current)
        if ba_approve_url:
            return ba_approve_url
        host = (urlsplit(current).netloc or "").lower()
        if host == "paypal.com" or host.endswith(".paypal.com"):
            return current
        try:
            response = stripe.get(current, allow_redirects=False, timeout=TIMEOUT)
        except Exception:
            return current
        ba_approve_url = extract_paypal_ba_approve_url({"url": current, "location": response.headers.get("Location", ""), "body": response.text})
        if ba_approve_url:
            return ba_approve_url
        if response.status_code not in (301, 302, 303, 307, 308):
            return current
        location = str(response.headers.get("Location") or "").strip()
        if not location:
            return current
        current = urljoin(current, location)
    return current


def paypal_return_url(cs_id: str, processor: str, hosted_url: str) -> str:
    base = to_openai_pay_url(hosted_url) or hosted_url or f"https://pay.openai.com/c/pay/{cs_id}"
    parsed = urlsplit(base)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["redirect_pm_type"] = "paypal"
    query["lid"] = str(uuid.uuid4())
    query["ui_mode"] = "custom"
    return urlunsplit((parsed.scheme or "https", parsed.netloc or "pay.openai.com", parsed.path, urlencode(query), parsed.fragment))


def chatgpt_approve(access_token: str, cs_id: str, processor: str, proxy_url: str, device_id: str, log: LogFn) -> None:
    cg = build_chatgpt_session(access_token, proxy_url, device_id)
    try:
        cg.post(
            "https://chatgpt.com/backend-api/sentinel/ping",
            json={},
            headers={"x-openai-target-path": "/backend-api/sentinel/ping", "x-openai-target-route": "/backend-api/sentinel/ping"},
            timeout=TIMEOUT,
        )
    except Exception:
        pass
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


def chatgpt_update_trial_promo(
    access_token: str,
    *,
    cs_id: str,
    processor: str,
    proxy_url: str,
    device_id: str,
    country: str = "JP",
    currency: str = "JPY",
) -> dict[str, Any]:
    cg = build_chatgpt_session(access_token, proxy_url, device_id)
    resp = cg.post(
        "https://chatgpt.com/backend-api/payments/checkout/update",
        json={
            "checkout_session_id": cs_id,
            "processor_entity": processor,
            "plan_name": "chatgptplusplan",
            "price_interval": "month",
            "seat_quantity": 1,
            "billing_details": {"country": country, "currency": currency},
            "promo_campaign": {"promo_campaign_id": "plus-1-month-free", "is_coupon_from_query_param": False},
        },
        headers={
            "Referer": f"https://chatgpt.com/checkout/{processor}/{cs_id}",
            "x-openai-target-path": "/backend-api/payments/checkout/update",
            "x-openai-target-route": "/backend-api/payments/checkout/update",
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"update failed: HTTP {resp.status_code} {short(resp.text)}")
    try:
        return resp.json() or {}
    except Exception:
        return {}


def _confirm_paypal_inline(
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
        "payment_method_data[type]": "paypal",
        "init_checksum": ctx["init_checksum"],
        "version": PAYPAL_STRIPE_RUNTIME_VERSION,
        "expected_amount": amount,
        "expected_payment_method_type": "paypal",
        "return_url": return_url,
        "elements_session_client[session_id]": ctx["elements_session_id"],
        "elements_session_client[locale]": "en-US",
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
        "_stripe_version": PAYPAL_STRIPE_VERSION,
    }
    body.update(
        {
            "payment_method_data[billing_details][name]": billing["name"],
            "payment_method_data[billing_details][email]": billing["email"],
            "payment_method_data[billing_details][address][country]": billing.get("country") or "US",
            "payment_method_data[billing_details][address][line1]": billing.get("line1") or "",
            "payment_method_data[billing_details][address][city]": billing.get("city") or "",
            "payment_method_data[billing_details][address][postal_code]": billing.get("postal_code") or "",
            "payment_method_data[billing_details][address][state]": billing.get("state") or "",
        }
    )
    resp = stripe.post(f"https://api.stripe.com/v1/payment_pages/{cs_id}/confirm", data=body, timeout=TIMEOUT)
    ba_approve_url = extract_paypal_ba_approve_url(resp.text)
    if ba_approve_url:
        return {"_ba_approve_url": ba_approve_url, "_raw_status": resp.status_code}
    if resp.status_code >= 400:
        raise RuntimeError(f"confirm failed: HTTP {resp.status_code} {short(resp.text)}")
    payload = resp.json() or {}
    ba_approve_url = extract_paypal_ba_approve_url(payload)
    if ba_approve_url:
        payload["_ba_approve_url"] = ba_approve_url
    return payload


def create_express_billing_agreement(
    stripe: requests.Session,
    *,
    stripe_pk: str,
    sdk_version: str = "v5",
) -> dict[str, str]:
    """Create a PayPal Billing Agreement token through Stripe Express Checkout.

    Stripe's PayPal Payment Element path creates a Checkout-owned SetupIntent for
    zero-amount trials. In current OpenAI/Stripe sessions that SetupIntent can be
    provider-declined before a PayPal redirect is emitted. Express Checkout has a
    separate Billing Agreement creation endpoint that returns a BA token directly.
    """

    resp = stripe.post(
        "https://api.stripe.com/v1/elements/express_billing_agreement",
        data={
            "key": stripe_pk,
            "paypal_sdk_version": sdk_version,
            "_stripe_version": PAYPAL_STRIPE_VERSION,
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"express BA failed: HTTP {resp.status_code} {short(resp.text)}")
    try:
        payload = resp.json() or {}
    except Exception as exc:
        raise RuntimeError(f"express BA invalid response: {short(resp.text)}") from exc
    token = str(payload.get("paypal_billing_agreement_token") or "").strip()
    if not token.startswith("BA-"):
        raise RuntimeError(f"express BA missing token: {short(payload)}")
    return {
        "paypal_link": paypal_ba_approve_url_from_token(token),
        "provider_redirect_url": paypal_ba_approve_url_from_token(token),
        "stripe_redirect_url": "",
        "ba_token": token,
        "link_source": "stripe_express_billing_agreement",
        "paypal_sdk_version": sdk_version,
    }


def generate_paypal_trial(cfg: PaypalJobConfig, log: LogFn | None = None) -> dict[str, Any]:
    log = log or (lambda _m: None)
    token = str(cfg.access_token or "").strip()
    if not token:
        raise RuntimeError("缺少 Access Token")
    if not cfg.direct_proxies and (not cfg.kookeey_user or not cfg.kookeey_pass):
        raise RuntimeError("缺少代理配置：direct_proxies 或 Kookeey 用户名/密码")

    device_id = str(uuid.uuid4())
    checkout_region = normalize_paypal_country(cfg.region, "US")
    promo_region = normalize_paypal_country(cfg.promo_region, "JP")
    checkout_currency = paypal_currency_for_country(checkout_region)
    billing = paypal_billing(country=checkout_region)
    state_text = f"-{billing.get('state')}" if billing.get("state") else ""
    log(f"账单: {billing['name']} / {billing['city']}{state_text} / {billing['postal_code']} / {billing['country']}")

    dyn1, sid1 = build_paypal_dynamic_proxy(cfg, 0, checkout_region)
    log(f"[1/6] {checkout_region} 创建 checkout（先不带 promo） sid={sid1}")
    with pix_proxy_context(cfg.local_proxy, dyn1, log) as chain1:
        p1 = chain1.url
        cg = build_chatgpt_session(token, p1, device_id)
        resp = cg.post(
            "https://chatgpt.com/backend-api/payments/checkout",
            json={
                "entry_point": "all_plans_pricing_modal",
                "plan_name": "chatgptplusplan",
                "billing_details": {"country": checkout_region, "currency": checkout_currency},
                "checkout_ui_mode": "custom",
            },
            headers={"x-openai-target-path": "/backend-api/payments/checkout", "x-openai-target-route": "/backend-api/payments/checkout"},
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

    dyn2, sid2 = build_paypal_dynamic_proxy(cfg, 1, checkout_region)
    log(f"[2/6] {checkout_region} Stripe init 预热 PayPal 支付方式 sid={sid2}")
    with pix_proxy_context(cfg.local_proxy, dyn2, log) as chain2:
        stripe_proxy = chain2.url
        stripe = build_stripe_session(stripe_proxy)
        ctx = _ctx()
        init_payload = stripe_init(stripe, cs_id, pk, ctx)
        amount = amount_info(init_payload)
        pmt, ordered, has_paypal = pmt_info(init_payload)
        pre_promo_amount = amount
        pre_promo_pmt = pmt
        pre_promo_ordered = ordered
        log(f"预热金额={amount} 支付方式={pmt} ordered={ordered} has_paypal={has_paypal}")
        if not has_paypal and not cfg.apply_promo:
            raise RuntimeError(f"未出现 PayPal，pmt={pmt}")

        if cfg.apply_promo:
            dyn3, sid3 = build_paypal_dynamic_proxy(cfg, 2, promo_region)
            log(f"[3/6] {promo_region} 后注入试用 promo sid={sid3}")
            with pix_proxy_context(cfg.local_proxy, dyn3, log) as chain3:
                update_payload = chatgpt_update_trial_promo(
                    token,
                    cs_id=cs_id,
                    processor=processor,
                    proxy_url=chain3.url,
                    device_id=device_id,
                    country=promo_region,
                    currency=promo_currency_for_region(promo_region),
                )
                log(f"promo update success={bool(update_payload.get('success', True))} keys={sorted(update_payload.keys())[:6]}")

            log(f"[4/6] {checkout_region} Stripe re-init 验证 0 元 + PayPal")
            init_payload = stripe_init(stripe, cs_id, pk, ctx)
            amount = amount_info(init_payload)
            pmt, ordered, has_paypal = pmt_info(init_payload)
            log(f"后注入金额={amount} 支付方式={pmt} ordered={ordered} has_paypal={has_paypal}")
            if not has_paypal:
                raise RuntimeError(f"后注入 promo 后未出现 PayPal，pmt={pmt}")
        else:
            log("[3/6] 跳过 promo update")
            if not is_zero_amount(amount):
                raise RuntimeError(f"PayPal 金额必须为 0: {amount}")
            log(f"[4/6] 更新 {checkout_region} tax_region {billing.get('state') or '-'}")
            stripe_update_tax_region(stripe, cs_id, pk, billing)
            init_payload = stripe_init(stripe, cs_id, pk, ctx)
            amount = amount_info(init_payload)
            pmt, ordered, has_paypal = pmt_info(init_payload)
            log(f"tax_region 后金额={amount} 支付方式={pmt} ordered={ordered} has_paypal={has_paypal}")
            if not has_paypal:
                raise RuntimeError(f"未出现 PayPal，pmt={pmt}")

        if not is_zero_amount(amount):
            raise RuntimeError(f"PayPal 金额必须为 0: {amount}")
        hosted = str(init_payload.get("stripe_hosted_url") or "")

        log("[5/6] Express Checkout Billing Agreement 提链")
        try:
            fields = create_express_billing_agreement(stripe, stripe_pk=pk, sdk_version="v5")
            fields["amount"] = amount
            fields["pre_promo_amount"] = pre_promo_amount
            fields["pre_promo_payment_method_types"] = pre_promo_pmt
            fields["pre_promo_ordered_payment_method_types"] = pre_promo_ordered
            fields["post_promo_payment_method_types"] = pmt
            fields["post_promo_ordered_payment_method_types"] = ordered
            fields["cs_id"] = cs_id
            fields["chatgpt_checkout_url"] = f"https://chatgpt.com/checkout/{processor}/{cs_id}"
            fields["billing"] = billing
            log(f"Express BA 提链成功 source={fields.get('link_source')} ba_token={bool(fields.get('ba_token'))}")
            return {"ok": True, "amount": amount, "fields": fields, "billing": billing}
        except Exception as exc:
            log(f"Express BA 提链失败，回退 inline confirm: {short(exc)}")

        log("[5/6] inline confirm PayPal")
        confirm_payload = _confirm_paypal_inline(
            stripe,
            cs_id=cs_id,
            stripe_pk=pk,
            ctx=ctx,
            billing=billing,
            amount=amount,
            return_url=paypal_return_url(cs_id, processor, hosted),
        )
        fields = extract_paypal_result(confirm_payload, cs_id)
        sub = find_submission_attempt(confirm_payload)
        log(f"confirm submission={sub.get('state')} redirect={bool(fields.get('stripe_redirect_url') or fields.get('paypal_link'))}")
        if is_success(fields):
            provider = resolve_external_redirect(stripe, fields.get("paypal_link") or fields.get("stripe_redirect_url") or "")
            if provider and is_paypal_ba_approve_url(provider):
                fields["provider_redirect_url"] = provider
                fields["paypal_link"] = provider
                token_match = re.search(r"BA-[A-Za-z0-9_-]+", provider)
                fields["ba_token"] = token_match.group(0) if token_match else fields.get("ba_token", "")
            fields["amount"] = amount
            fields["pre_promo_amount"] = pre_promo_amount
            fields["pre_promo_payment_method_types"] = pre_promo_pmt
            fields["pre_promo_ordered_payment_method_types"] = pre_promo_ordered
            fields["post_promo_payment_method_types"] = pmt
            fields["post_promo_ordered_payment_method_types"] = ordered
            fields["chatgpt_checkout_url"] = f"https://chatgpt.com/checkout/{processor}/{cs_id}"
            fields["billing"] = billing
            return {"ok": True, "amount": amount, "fields": fields, "billing": billing}

        log("[6/6] approve + poll PayPal")
        chatgpt_approve(token, cs_id, processor, stripe_proxy, device_id, log)
        last_err: dict[str, Any] = {}
        for i in range(1, 20):
            page_data = page_get(stripe, cs_id, pk, ctx)
            fields = extract_paypal_result(page_data, cs_id)
            sub = find_submission_attempt(page_data)
            err = sub.get("error") if isinstance(sub.get("error"), dict) else {}
            log(f"poll {i}/19 sub={sub.get('state')} err={err.get('code') if err else '-'} success={is_success(fields)}")
            if is_success(fields):
                provider = resolve_external_redirect(stripe, fields.get("paypal_link") or fields.get("stripe_redirect_url") or "")
                if provider and is_paypal_ba_approve_url(provider):
                    fields["provider_redirect_url"] = provider
                    fields["paypal_link"] = provider
                    token_match = re.search(r"BA-[A-Za-z0-9_-]+", provider)
                    fields["ba_token"] = token_match.group(0) if token_match else fields.get("ba_token", "")
                fields["amount"] = amount
                fields["pre_promo_amount"] = pre_promo_amount
                fields["pre_promo_payment_method_types"] = pre_promo_pmt
                fields["pre_promo_ordered_payment_method_types"] = pre_promo_ordered
                fields["post_promo_payment_method_types"] = pmt
                fields["post_promo_ordered_payment_method_types"] = ordered
                fields["chatgpt_checkout_url"] = f"https://chatgpt.com/checkout/{processor}/{cs_id}"
                fields["billing"] = billing
                return {"ok": True, "amount": amount, "fields": fields, "billing": billing}
            if sub.get("state") == "failed":
                last_err = err or {}
                raise RuntimeError(f"approve 后失败: {last_err.get('code')}")
            time.sleep(1.0)
        raise RuntimeError("轮询超时，未拿到 PayPal 链接")
