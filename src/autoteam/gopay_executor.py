"""GoPay 绑卡执行器。"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import requests

from autoteam.auth_session_store import list_auth_session_emails, load_auth_session
from autoteam.chatgpt_api import ChatGPTTeamAPI

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent
SCREENSHOT_DIR = PROJECT_ROOT / "data" / "bind_screenshots"

SUCCESS_HINTS = (
    "payment successful",
    "thanks for subscribing",
    "subscription active",
    "you are now subscribed",
    "支付成功",
    "付款成功",
    "订阅成功",
    "berhasil",
)

CHECKOUT_ERROR_PATTERNS = (
    re.compile(r"付款.*未获批准"),
    re.compile(r"未获批准"),
    re.compile(r"出了错"),
    re.compile(r"请重试"),
    re.compile(r"payment.*not.*approved", re.IGNORECASE),
    re.compile(r"payment.*declined", re.IGNORECASE),
    re.compile(r"not.*approved", re.IGNORECASE),
    re.compile(r"try again", re.IGNORECASE),
    re.compile(r"something went wrong", re.IGNORECASE),
    re.compile(r"unable to process", re.IGNORECASE),
)

try:
    from curl_cffi.requests import Session as _CurlCffiSession  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    _CurlCffiSession = None  # type: ignore

DEFAULT_STRIPE_PK = (
    "pk_live_51HOrSwC6h1nxGoI3lTAgRjYVrz4dU3fVOabyCcKR3pbEJguCVAlqCxdxCUvoRh1XWwRac"
    "ViovU3kLKvpkjh7IqkW00iXQsjo3n"
)
DEFAULT_MIDTRANS_CLIENT_ID = "Mid-client-3TX8nUa-f_RgNrky"
DEFAULT_STRIPE_RUNTIME_VERSION = "fed52f3bc6"
STRIPE_API = "https://api.stripe.com"
STRIPE_VERSION_FULL = "2025-03-31.basil; checkout_server_update_beta=v1; checkout_manual_approval_preview=v1"
GOPAY_LINK_RETRY_LIMIT = 3
GOPAY_LINK_RETRY_SLEEP_S = 30.0
GOPAY_SMS_OTP_DELAY_S = 60.0
GOPAY_APPROVE_BLOCKED_COOLDOWN_S = 1800.0
HTTP_TIMEOUT_SECONDS = 60
TRANSIENT_HTTP_RETRY_ATTEMPTS = 2
TRANSIENT_HTTP_RETRY_SLEEP_S = 2.0
TRANSIENT_RETRY_STAGES = {
    "stripe_payment_method",
    "stripe_init",
    "stripe_confirm",
    "resolve_midtrans_redirect",
    "pm_redirect",
    "midtrans_load_transaction",
    "gopay_validate_reference",
    "gopay_user_consent",
    "gopay_validate_otp",
    "gopay_tokenize_pin",
    "gopay_validate_pin",
    "midtrans_create_charge",
    "gopay_payment_validate",
    "gopay_payment_confirm",
    "gopay_payment_process",
}

_GOPAY_APPROVE_BLOCKED_UNTIL: dict[str, float] = {}


class GoPayFlowError(RuntimeError):
    def __init__(self, message: str, stage: str = "gopay_http"):
        super().__init__(message)
        self.stage = stage


class GoPayOTPCancelled(GoPayFlowError):
    pass


class GoPayPINRejected(GoPayFlowError):
    pass


class GoPayChargeBlocked(GoPayFlowError):
    pass


class GoPayAlreadyLinked(GoPayFlowError):
    pass


class GoPayRateLimited(GoPayFlowError):
    pass


def _new_http_session(proxy_url: str | None = None) -> Any:
    if _CurlCffiSession is not None:
        session = _CurlCffiSession(impersonate=os.environ.get("GOPAY_TLS_IMPERSONATE", "chrome136"))
    else:
        session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    if proxy_url:
        try:
            session.proxies = {"http": proxy_url, "https": proxy_url}
        except Exception:
            pass
    return session


def _response_json(resp, stage: str) -> dict:
    try:
        data = resp.json()
    except Exception as exc:
        raise GoPayFlowError(
            f"{stage} 返回非 JSON: HTTP {getattr(resp, 'status_code', '?')} {(getattr(resp, 'text', '') or '')[:300]}",
            stage=stage,
        ) from exc
    return data if isinstance(data, dict) else {"_raw": data}


def _ensure_ok(resp, stage: str):
    if 200 <= int(getattr(resp, "status_code", 0) or 0) < 300:
        return
    text = str(getattr(resp, "text", "") or "")
    if _looks_like_gopay_rate_limit_text(text):
        raise GoPayRateLimited(_gopay_rate_limited_message(), stage="gopay_rate_limited")
    raise GoPayFlowError(
        f"{stage} 失败: HTTP {getattr(resp, 'status_code', '?')} {(getattr(resp, 'text', '') or '')[:500]}",
        stage=stage,
    )


def _is_transient_http_error(exc: Exception) -> bool:
    if isinstance(exc, requests.RequestException):
        return True
    module = exc.__class__.__module__
    name = exc.__class__.__name__.lower()
    return module.startswith("curl_cffi") and any(
        marker in name for marker in ("timeout", "connection", "proxy", "ssl", "requests")
    )


def _env_truthy(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_amount(value: Any) -> int | None:
    raw = str(value if value is not None else "").strip()
    if not raw:
        return None
    try:
        return int(float(raw))
    except Exception:
        return None


def _env_float(name: str, default: float) -> float:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except Exception:
        return default


def _is_chatgpt_approve_blocked_result(result: dict | None) -> bool:
    if not isinstance(result, dict):
        return False
    if str(result.get("failure_stage") or "") != "chatgpt_approve":
        return False
    return "blocked" in str(result.get("message") or "").lower()


def _gopay_rate_limited_message() -> str:
    return "GoPay 授权页提示尝试过多，请稍后重试，或更换 GoPay 手机号/钱包"


def _looks_like_gopay_rate_limit_text(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    if not normalized:
        return False
    return any(
        marker in normalized
        for marker in (
            "请稍后再试",
            "稍后再试",
            "too many attempts",
            "try again later",
            "please try again later",
            "terlalu banyak",
            "coba lagi nanti",
        )
    )


def _looks_like_gopay_rate_limit_payload(payload: Any) -> bool:
    try:
        text = json.dumps(payload, ensure_ascii=False)
    except Exception:
        text = str(payload or "")
    return _looks_like_gopay_rate_limit_text(text)


def _approve_blocked_cooldown_seconds() -> float:
    return max(0.0, _env_float("GOPAY_APPROVE_BLOCKED_COOLDOWN_SECONDS", GOPAY_APPROVE_BLOCKED_COOLDOWN_S))


def _mark_approve_blocked(email: str) -> float:
    cooldown = _approve_blocked_cooldown_seconds()
    until = time.time() + cooldown
    if email:
        _GOPAY_APPROVE_BLOCKED_UNTIL[email.strip().lower()] = until
    return cooldown


def _approve_blocked_remaining(email: str) -> int:
    blocked_until = _GOPAY_APPROVE_BLOCKED_UNTIL.get(email.strip().lower(), 0.0)
    remaining = int(max(0.0, blocked_until - time.time()))
    if remaining <= 0 and email.strip().lower() in _GOPAY_APPROVE_BLOCKED_UNTIL:
        _GOPAY_APPROVE_BLOCKED_UNTIL.pop(email.strip().lower(), None)
    return remaining


def _gopay_auth_rotation_candidates(email: str, candidate_emails: list[str] | None = None) -> list[str]:
    primary = str(email or "").strip().lower()
    candidates: list[str] = []
    source = candidate_emails if candidate_emails is not None else [primary]
    for candidate in source:
        normalized = str(candidate or "").strip().lower()
        if normalized and normalized not in candidates:
            candidates.append(normalized)
    if primary and primary not in candidates:
        candidates.insert(0, primary)
    return candidates


def _extract_checkout_session_id(checkout_url: str = "", raw: dict | None = None) -> str:
    data = raw if isinstance(raw, dict) else {}
    for key in ("checkout_session_id", "session_id", "id"):
        value = str(data.get(key) or "").strip()
        if value.startswith("cs_"):
            return value
    matched = re.search(r"(cs_[A-Za-z0-9_]+)", str(checkout_url or ""))
    return matched.group(1) if matched else ""


def _extract_processor_entity(raw: dict | None) -> str:
    data = raw if isinstance(raw, dict) else {}
    return str(data.get("processor_entity") or "openai_llc").strip() or "openai_llc"


def _stripe_runtime_from_env() -> dict:
    return {
        "version": os.environ.get("GOPAY_STRIPE_RUNTIME_VERSION", DEFAULT_STRIPE_RUNTIME_VERSION).strip(),
        "js_checksum": os.environ.get("GOPAY_STRIPE_JS_CHECKSUM", "").strip(),
        "rv_timestamp": os.environ.get("GOPAY_STRIPE_RV_TIMESTAMP", "").strip(),
    }


def _split_gopay_phone(phone_number: str, country_code: str = "") -> tuple[str, str]:
    explicit_country = re.sub(r"\D", "", str(country_code or ""))
    digits = re.sub(r"\D", "", str(phone_number or ""))
    if not digits:
        return explicit_country or "62", ""

    if explicit_country:
        local = digits
        if local.startswith(explicit_country):
            local = local[len(explicit_country):]
        if explicit_country == "62" and local.startswith("0"):
            local = local[1:]
        return explicit_country, local

    raw = str(phone_number or "").strip()
    if raw.startswith("+"):
        if digits.startswith("62"):
            local = digits[2:]
            return "62", local[1:] if local.startswith("0") else local
        if digits.startswith("86"):
            return "86", digits[2:]

    if digits.startswith("62") and len(digits) > 10:
        local = digits[2:]
        return "62", local[1:] if local.startswith("0") else local
    if digits.startswith("86") and len(digits) > 11:
        return "86", digits[2:]
    if digits.startswith("0"):
        return "62", digits[1:]
    return "62", digits


def _chatgpt_cookie_header(session_token: str = "", account_id: str = "", device_id: str = "") -> str:
    parts: list[str] = []
    token = str(session_token or "").strip()
    if token:
        if len(token) > 3800:
            parts.append(f"__Secure-next-auth.session-token.0={token[:3800]}")
            parts.append(f"__Secure-next-auth.session-token.1={token[3800:]}")
        else:
            parts.append(f"__Secure-next-auth.session-token={token}")
    if account_id:
        parts.append(f"_account={account_id}")
    if device_id:
        parts.append(f"oai-did={device_id}")
    return "; ".join(parts)


def _chatgpt_reference_cookie_header(
    session_token: str = "",
    account_id: str = "",
    device_id: str = "",
    cookie_header: str = "",
) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for raw in str(cookie_header or "").split(";"):
        item = raw.strip()
        if not item or "=" not in item:
            continue
        name = item.split("=", 1)[0].strip()
        if name and name not in seen:
            seen.add(name)
            parts.append(item)

    token = str(session_token or "").strip()
    if token and "__Secure-next-auth.session-token" not in seen:
        parts.append(f"__Secure-next-auth.session-token={token}")
        seen.add("__Secure-next-auth.session-token")
    if device_id and "oai-did" not in seen:
        parts.append(f"oai-did={device_id}")
    return "; ".join(parts)


def _configure_chatgpt_http_session(
    http: Any,
    *,
    access_token: str,
    session_token: str = "",
    cookie_header: str = "",
    account_id: str = "",
    device_id: str = "",
    user_agent: str = "",
) -> dict:
    device_id = str(device_id or "").strip() or str(uuid.uuid4())
    user_agent = str(user_agent or "").strip() or (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
    )
    resolved_cookie = _chatgpt_reference_cookie_header(
        session_token=session_token,
        account_id=account_id,
        device_id=device_id,
        cookie_header=cookie_header,
    )
    headers = {
        "User-Agent": user_agent,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://chatgpt.com",
        "Referer": "https://chatgpt.com/",
        "Content-Type": "application/json",
        "oai-device-id": device_id,
        "oai-language": "en-US",
        "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    if resolved_cookie:
        headers["Cookie"] = resolved_cookie
    try:
        http.headers.update(headers)
        http._oai_device_id = device_id  # type: ignore[attr-defined]
        http._chatgpt_cookie_header = resolved_cookie  # type: ignore[attr-defined]
    except Exception:
        pass
    return {"device_id": device_id, "cookie_header": resolved_cookie}


def _build_chatgpt_http_session(
    *,
    access_token: str,
    session_token: str = "",
    cookie_header: str = "",
    account_id: str = "",
    device_id: str = "",
    user_agent: str = "",
    proxy_url: str | None = None,
) -> Any:
    http = _new_http_session(proxy_url)
    _configure_chatgpt_http_session(
        http,
        access_token=access_token,
        session_token=session_token,
        cookie_header=cookie_header,
        account_id=account_id,
        device_id=device_id,
        user_agent=user_agent,
    )
    return http


def _merge_cookie_headers(*headers: str) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for header in headers:
        for raw in str(header or "").split(";"):
            item = raw.strip()
            if not item or "=" not in item:
                continue
            name = item.split("=", 1)[0].strip()
            if not name or name in seen:
                continue
            seen.add(name)
            parts.append(item)
    return "; ".join(parts)


def _cookie_header_from_http_session(http: Any) -> str:
    try:
        cookies = getattr(http, "cookies", None)
        if not cookies:
            return ""
        if hasattr(cookies, "get_dict"):
            items = cookies.get_dict(domain="chatgpt.com").items()
            fallback_items = cookies.get_dict().items()
            pairs = list(items) or list(fallback_items)
        else:
            pairs = [(cookie.name, cookie.value) for cookie in cookies]
        return "; ".join(f"{name}={value}" for name, value in pairs if name and value)
    except Exception:
        return ""


def _looks_like_pm_redirect_url(url: str) -> bool:
    raw = str(url or "").lower()
    return "pm-redirects.stripe.com/authorize/" in raw or "app.midtrans.com/snap/" in raw


def _poll_otp_from_sms_url(
    sms_url: str,
    *,
    timeout_seconds: int,
    initial_delay_seconds: float | None = None,
    is_cancelled=None,
    progress: Callable[..., None] | None = None,
) -> Callable[[], str]:
    def provider() -> str:
        if not sms_url:
            raise GoPayOTPCancelled("缺少 OTP 接口 URL", stage="fetch_otp")
        delay_seconds = (
            _env_float("GOPAY_SMS_OTP_DELAY_SECONDS", GOPAY_SMS_OTP_DELAY_S)
            if initial_delay_seconds is None
            else float(initial_delay_seconds or 0)
        )
        if delay_seconds > 0:
            waited = 0.0
            if callable(progress):
                progress("wait_sms_otp_window", wait_seconds=int(delay_seconds))
            while waited < delay_seconds:
                if callable(is_cancelled) and is_cancelled():
                    raise GoPayOTPCancelled("任务已取消", stage="fetch_otp")
                step = min(1.0, delay_seconds - waited)
                time.sleep(step)
                waited += step
        deadline = time.time() + max(60, int(timeout_seconds or 300))
        while time.time() < deadline:
            if callable(is_cancelled) and is_cancelled():
                raise GoPayOTPCancelled("任务已取消", stage="fetch_otp")
            if callable(progress):
                progress("fetch_otp")
            try:
                code = _fetch_sms_code(sms_url)
                if code:
                    return code
            except Exception as exc:
                logger.info("[gopay_executor] 等待 GoPay OTP: %s", exc)
            time.sleep(5)
        raise GoPayOTPCancelled("等待 GoPay OTP 超时", stage="fetch_otp")

    return provider


def _chatgpt_checkout_headers(
    *,
    access_token: str,
    checkout_session_id: str,
    processor_entity: str,
    cookie_header: str = "",
    account_id: str = "",
    device_id: str = "",
    target_path: str = "",
    openai_sentinel_token: str = "",
) -> dict:
    headers = {
        "accept": "*/*",
        "content-type": "application/json",
        "origin": "https://chatgpt.com",
        "referer": f"https://chatgpt.com/checkout/{processor_entity}/{checkout_session_id}",
        "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
    }
    if target_path:
        headers["x-openai-target-path"] = target_path
        headers["x-openai-target-route"] = target_path
    if access_token:
        headers["authorization"] = f"Bearer {access_token}"
    if cookie_header:
        headers["cookie"] = cookie_header
    if device_id:
        headers["oai-device-id"] = device_id
    if account_id:
        headers["chatgpt-account-id"] = account_id
    if openai_sentinel_token:
        headers["openai-sentinel-token"] = openai_sentinel_token
    return headers


def _chatgpt_checkout_payload() -> dict:
    return {
        "entry_point": "all_plans_pricing_modal",
        "plan_name": "chatgptplusplan",
        "billing_details": {"country": "ID", "currency": "IDR"},
        "promo_campaign": {
            "promo_campaign_id": "plus-1-month-free",
            "is_coupon_from_query_param": False,
        },
        "checkout_ui_mode": "custom",
    }


def _generate_id_checkout_http(
    http: Any,
    *,
    access_token: str,
    session_token: str = "",
    cookie_header: str = "",
    account_id: str = "",
    device_id: str = "",
    user_agent: str = "",
) -> dict:
    _configure_chatgpt_http_session(
        http,
        access_token=access_token,
        session_token=session_token,
        cookie_header=cookie_header,
        account_id=account_id,
        device_id=device_id,
        user_agent=user_agent,
    )

    resp = http.post(
        "https://chatgpt.com/backend-api/payments/checkout",
        json=_chatgpt_checkout_payload(),
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    if resp.status_code != 200:
        raise GoPayFlowError(
            f"HTTP checkout 生成失败: HTTP {resp.status_code} {(resp.text or '')[:500]}",
            stage="generate_checkout",
        )
    data = _response_json(resp, "generate_checkout")
    checkout_session_id = _extract_checkout_session_id(raw=data)
    processor_entity = _extract_processor_entity(data)
    checkout_url = str(data.get("url") or "").strip()
    if not checkout_url and checkout_session_id:
        checkout_url = f"https://chatgpt.com/checkout/{processor_entity}/{checkout_session_id}"
    if not checkout_url:
        raise GoPayFlowError(f"HTTP checkout 返回缺少 url: {data}", stage="generate_checkout")
    return {"url": checkout_url, "raw": data}


def _approve_checkout_http(
    http: Any,
    *,
    access_token: str,
    checkout_session_id: str,
    processor_entity: str,
    cookie_header: str = "",
    account_id: str = "",
    device_id: str = "",
    openai_sentinel_token: str = "",
) -> dict:
    if access_token or cookie_header or account_id or device_id:
        _configure_chatgpt_http_session(
            http,
            access_token=access_token,
            cookie_header=cookie_header,
            account_id=account_id,
            device_id=device_id,
        )
    if openai_sentinel_token:
        try:
            http.headers.update({"openai-sentinel-token": openai_sentinel_token})
        except Exception:
            pass
    try:
        http.post(
            "https://chatgpt.com/backend-api/sentinel/ping",
            json={},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.info("[gopay_executor] sentinel ping before approve skipped: %s", exc)

    resp = http.post(
        "https://chatgpt.com/backend-api/payments/checkout/approve",
        json={
            "checkout_session_id": checkout_session_id,
            "processor_entity": processor_entity,
        },
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    if resp.status_code != 200:
        raise GoPayFlowError(
            f"ChatGPT approve 失败: HTTP {resp.status_code} {(resp.text or '')[:500]}",
            stage="chatgpt_approve",
        )
    payload = _response_json(resp, "chatgpt_approve")
    if payload.get("result") not in (None, "approved"):
        raise GoPayFlowError(f"ChatGPT approve 未通过: {payload}", stage="chatgpt_approve")
    return payload


def _verify_checkout_http(
    http: Any,
    *,
    access_token: str,
    checkout_session_id: str,
    processor_entity: str,
    cookie_header: str = "",
    account_id: str = "",
    device_id: str = "",
    openai_sentinel_token: str = "",
) -> dict:
    if access_token or cookie_header or account_id or device_id:
        _configure_chatgpt_http_session(
            http,
            access_token=access_token,
            cookie_header=cookie_header,
            account_id=account_id,
            device_id=device_id,
        )
    if openai_sentinel_token:
        try:
            http.headers.update({"openai-sentinel-token": openai_sentinel_token})
        except Exception:
            pass
    resp = http.get(
        "https://chatgpt.com/checkout/verify",
        params={
            "stripe_session_id": checkout_session_id,
            "processor_entity": processor_entity,
            "plan_type": "plus",
        },
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    if resp.status_code == 200:
        return {"state": "succeeded", "verify": {"status": resp.status_code}}
    return {"state": "verify_timeout", "verify": {"status": resp.status_code, "body": (resp.text or "")[:500]}}


def _collect_page_cookie_header(api: ChatGPTTeamAPI) -> str:
    try:
        cookies = api.context.cookies("https://chatgpt.com")
    except Exception:
        cookies = []
    parts = []
    seen = set()
    for cookie in cookies or []:
        if not isinstance(cookie, dict):
            continue
        name = str(cookie.get("name") or "").strip()
        value = str(cookie.get("value") or "").strip()
        if not name or not value or name in seen:
            continue
        seen.add(name)
        parts.append(f"{name}={value}")
    return "; ".join(parts)


def _load_checkout_context_in_page(
    api: ChatGPTTeamAPI,
    *,
    checkout_session_id: str,
    processor_entity: str,
    timeout_ms: int = 15000,
) -> dict:
    state = {"sentinel_token": ""}

    def on_response(resp):
        if "backend-api/sentinel/req" not in str(getattr(resp, "url", "")):
            return
        try:
            if int(getattr(resp, "status", 0) or 0) != 200:
                return
            data = resp.json()
            token = str(data.get("token") or "").strip() if isinstance(data, dict) else ""
            if token:
                state["sentinel_token"] = token
        except Exception:
            pass

    try:
        api.page.on("response", on_response)
    except Exception:
        pass
    try:
        api.page.goto(
            f"https://chatgpt.com/checkout/{processor_entity}/{checkout_session_id}",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        deadline = time.time() + max(1, timeout_ms / 1000)
        while time.time() < deadline and not state["sentinel_token"]:
            try:
                api.page.wait_for_timeout(500)
            except Exception:
                time.sleep(0.5)
    except Exception as exc:
        logger.info("[gopay_executor] checkout context warmup failed: %s", exc)
    return {
        "cookie_header": _collect_page_cookie_header(api),
        "openai_sentinel_token": state["sentinel_token"],
    }


def _approve_checkout_in_page(
    api: ChatGPTTeamAPI,
    *,
    access_token: str,
    checkout_session_id: str,
    processor_entity: str,
) -> dict:
    result = api.page.evaluate(
        """async (payload) => {
            try {
                try {
                    await fetch("/backend-api/sentinel/ping", {
                        method: "POST",
                        credentials: "include",
                        headers: { "Content-Type": "application/json" },
                        body: "{}"
                    });
                } catch (_) {}
                const headers = {
                    "Content-Type": "application/json",
                    "x-openai-target-path": "/backend-api/payments/checkout/approve",
                    "x-openai-target-route": "/backend-api/payments/checkout/approve"
                };
                if (payload.access_token) {
                    headers.Authorization = "Bearer " + payload.access_token;
                }
                const resp = await fetch("https://chatgpt.com/backend-api/payments/checkout/approve", {
                    method: "POST",
                    credentials: "include",
                    headers,
                    body: JSON.stringify({
                        checkout_session_id: payload.checkout_session_id,
                        processor_entity: payload.processor_entity
                    })
                });
                const text = await resp.text();
                let data = {};
                try { data = text ? JSON.parse(text) : {}; }
                catch (_) { data = { raw: text.slice(0, 500) }; }
                return { ok: resp.ok, status: resp.status, data };
            } catch (e) {
                return { ok: false, status: 0, error: String(e && e.message ? e.message : e) };
            }
        }""",
        {
            "access_token": access_token,
            "checkout_session_id": checkout_session_id,
            "processor_entity": processor_entity,
        },
    )
    if not result.get("ok"):
        detail = result.get("error") or (result.get("data") or {}).get("detail") or (result.get("data") or {}).get("error")
        raise GoPayFlowError(
            f"ChatGPT approve 失败: HTTP {result.get('status')} {detail or result.get('data')}",
            stage="chatgpt_approve",
        )
    return result.get("data") or {}


def _verify_checkout_in_page(
    api: ChatGPTTeamAPI,
    *,
    access_token: str,
    checkout_session_id: str,
    processor_entity: str,
) -> dict:
    result = api.page.evaluate(
        """async (payload) => {
            const url = new URL("https://chatgpt.com/checkout/verify");
            url.searchParams.set("stripe_session_id", payload.checkout_session_id);
            url.searchParams.set("processor_entity", payload.processor_entity);
            url.searchParams.set("plan_type", "plus");
            try {
                const headers = {};
                if (payload.access_token) {
                    headers.Authorization = "Bearer " + payload.access_token;
                }
                const resp = await fetch(url.toString(), {
                    method: "GET",
                    credentials: "include",
                    headers,
                    redirect: "follow"
                });
                const text = await resp.text();
                return { ok: resp.ok, status: resp.status, final_url: resp.url, body: text.slice(0, 500) };
            } catch (e) {
                return { ok: false, status: 0, error: String(e && e.message ? e.message : e) };
            }
        }""",
        {
            "access_token": access_token,
            "checkout_session_id": checkout_session_id,
            "processor_entity": processor_entity,
        },
    )
    if result.get("ok"):
        return {"state": "succeeded", "verify": result}
    return {"state": "verify_timeout", "verify": result}


def _new_isolated_gopay_context(api: ChatGPTTeamAPI):
    browser = getattr(api, "browser", None)
    if not browser:
        raise GoPayFlowError("浏览器尚未启动，无法打开 GoPay 授权页", stage="trigger_sms_otp")
    return browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
        ),
        locale="en-US",
        extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
        },
    )


def _page_text(page, limit: int = 2000) -> str:
    try:
        return str(page.locator("body").inner_text(timeout=1200) or "")[:limit]
    except Exception:
        return ""


def _raise_if_gopay_rate_limited_page(page, progress: Callable[..., None] | None = None):
    if _looks_like_gopay_rate_limit_text(_page_text(page)):
        if callable(progress):
            progress("gopay_rate_limited")
        raise GoPayRateLimited(_gopay_rate_limited_message(), stage="gopay_rate_limited")


def _trigger_sms_otp_in_page(
    api: ChatGPTTeamAPI,
    *,
    activation_link_url: str,
    proxy_url: str | None = None,
    proxy_bypass: str | None = None,
    wait_seconds: float | None = None,
    is_cancelled=None,
    progress: Callable[..., None] | None = None,
):
    url = str(activation_link_url or "").strip()
    if not url:
        raise GoPayFlowError("缺少 GoPay activation_link_url，无法切换 SMS OTP", stage="trigger_sms_otp")

    wait_seconds = (
        _env_float("GOPAY_SMS_OTP_DELAY_SECONDS", GOPAY_SMS_OTP_DELAY_S)
        if wait_seconds is None
        else float(wait_seconds or 0)
    )
    if callable(progress):
        progress("wait_sms_otp_window", wait_seconds=int(wait_seconds))

    isolated_context = None
    try:
        if not getattr(api, "browser", None):
            api._launch_browser(proxy_url=proxy_url, proxy_bypass=proxy_bypass)
        isolated_context = _new_isolated_gopay_context(api)
        page = isolated_context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        _raise_if_gopay_rate_limited_page(page, progress)
    except Exception as exc:
        try:
            if isolated_context:
                isolated_context.close()
        except Exception:
            pass
        if isinstance(exc, GoPayFlowError):
            raise
        raise GoPayFlowError(f"打开 GoPay SMS OTP 页面失败: {exc}", stage="trigger_sms_otp") from exc

    try:
        deadline = time.time() + max(30.0, wait_seconds + 45.0)
        last_error = ""
        patterns = (
            r"\bSMS\b",
            r"kirim.*sms",
            r"send.*sms",
            r"via.*sms",
            r"text\s*message",
            r"gunakan.*sms",
        )
        while time.time() < deadline:
            if callable(is_cancelled) and is_cancelled():
                raise GoPayOTPCancelled("任务已取消", stage="trigger_sms_otp")
            _raise_if_gopay_rate_limited_page(page, progress)
            if callable(progress):
                progress("trigger_sms_otp")

            for pattern in patterns:
                try:
                    locator = page.get_by_role("button", name=re.compile(pattern, re.IGNORECASE)).first
                    if locator.is_visible(timeout=500):
                        locator.click(timeout=5000)
                        page.wait_for_timeout(1500)
                        _raise_if_gopay_rate_limited_page(page, progress)
                        if callable(progress):
                            progress("sms_otp_triggered")
                        return
                except GoPayFlowError:
                    raise
                except Exception as exc:
                    last_error = str(exc)
                try:
                    locator = page.get_by_role("link", name=re.compile(pattern, re.IGNORECASE)).first
                    if locator.is_visible(timeout=500):
                        locator.click(timeout=5000)
                        page.wait_for_timeout(1500)
                        _raise_if_gopay_rate_limited_page(page, progress)
                        if callable(progress):
                            progress("sms_otp_triggered")
                        return
                except GoPayFlowError:
                    raise
                except Exception as exc:
                    last_error = str(exc)

            try:
                clicked = page.evaluate(
                    """() => {
                        const re = /sms/i;
                        const nodes = Array.from(document.querySelectorAll('button,a,[role="button"],[onclick]'));
                        for (const el of nodes) {
                            const text = (el.innerText || el.textContent || '').trim();
                            const rect = el.getBoundingClientRect();
                            const style = window.getComputedStyle(el);
                            if (!re.test(text) || rect.width <= 0 || rect.height <= 0 || style.visibility === 'hidden' || style.display === 'none') {
                                continue;
                            }
                            el.click();
                            return true;
                        }
                        return false;
                    }"""
                )
                if clicked:
                    page.wait_for_timeout(1500)
                    _raise_if_gopay_rate_limited_page(page, progress)
                    if callable(progress):
                        progress("sms_otp_triggered")
                    return
            except GoPayFlowError:
                raise
            except Exception as exc:
                last_error = str(exc)

            try:
                page.wait_for_timeout(1000)
            except Exception:
                time.sleep(1)

        if callable(progress):
            progress("sms_otp_trigger_failed")
        raise GoPayFlowError(f"未找到或无法点击 GoPay SMS OTP 按钮: {last_error}", stage="trigger_sms_otp")
    finally:
        try:
            if isolated_context:
                isolated_context.close()
        except Exception:
            pass


class GoPayHttpCharger:
    """Stripe -> Midtrans -> GoPay tokenization flow.

    ChatGPT endpoints still run through Playwright page callbacks so the
    project keeps using its existing logged-in browser context. External
    Stripe/Midtrans/GoPay calls are plain HTTP and no longer depend on the
    fragile checkout DOM.
    """

    def __init__(
        self,
        *,
        http: Any,
        phone_number: str,
        gopay_pin: str,
        otp_provider: Callable[[], str],
        billing_info: dict | None = None,
        country_code: str = "",
        stripe_runtime: dict | None = None,
        midtrans_client_id: str | None = None,
        approve_callback: Callable[[str], dict] | None = None,
        verify_callback: Callable[[str], dict] | None = None,
        sms_otp_trigger_callback: Callable[[str, str], None] | None = None,
        is_cancelled=None,
        progress_callback=None,
    ):
        self.http = http
        self.country_code, self.phone_number = _split_gopay_phone(phone_number, country_code)
        self.gopay_pin = str(gopay_pin or "").strip()
        self.otp_provider = otp_provider
        self.billing_info = dict(billing_info or {})
        self.runtime = dict(stripe_runtime or {})
        self.midtrans_client_id = (
            str(midtrans_client_id or os.environ.get("GOPAY_MIDTRANS_CLIENT_ID") or DEFAULT_MIDTRANS_CLIENT_ID).strip()
        )
        self.approve_callback = approve_callback
        self.verify_callback = verify_callback
        self.sms_otp_trigger_callback = sms_otp_trigger_callback
        self.is_cancelled = is_cancelled
        self.progress_callback = progress_callback
        self.expected_due_amount: int | None = None
        self.expected_due_currency = ""
        self.activation_link_url = ""

    def _progress(self, stage: str, **extra):
        if callable(self.progress_callback):
            payload = {"stage": stage}
            payload.update(extra)
            self.progress_callback(payload)

    def _check_cancelled(self):
        if callable(self.is_cancelled) and self.is_cancelled():
            raise GoPayFlowError("任务已取消", stage="cancelled")

    def _request(self, method: str, url: str, *, stage: str, **kwargs):
        func = getattr(self.http, method.lower())
        timeout = kwargs.pop("timeout", HTTP_TIMEOUT_SECONDS)
        attempts = TRANSIENT_HTTP_RETRY_ATTEMPTS if stage in TRANSIENT_RETRY_STAGES else 1
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            self._check_cancelled()
            try:
                return func(url, timeout=timeout, **kwargs)
            except Exception as exc:
                last_exc = exc
                if attempt >= attempts or not _is_transient_http_error(exc):
                    raise
                logger.info(
                    "[gopay_executor] transient HTTP error at %s, retry %s/%s: %s",
                    stage,
                    attempt + 1,
                    attempts,
                    exc,
                )
                time.sleep(TRANSIENT_HTTP_RETRY_SLEEP_S)
        raise last_exc or GoPayFlowError(f"{stage} HTTP 请求失败", stage=stage)

    def _stripe_create_payment_method(self, checkout_session_id: str, stripe_pk: str) -> str:
        self._progress("stripe_create_payment_method")
        billing = self.billing_info
        data = {
            "billing_details[name]": billing.get("name") or "John Doe",
            "billing_details[email]": billing.get("email") or "buyer@example.com",
            "billing_details[address][country]": billing.get("country") or "US",
            "billing_details[address][line1]": billing.get("address1") or "3110 Sunset Boulevard",
            "billing_details[address][city]": billing.get("city") or "Los Angeles",
            "billing_details[address][postal_code]": billing.get("zip") or "90026",
            "billing_details[address][state]": billing.get("state") or "CA",
            "type": "gopay",
            "client_attribution_metadata[checkout_session_id]": checkout_session_id,
            "key": stripe_pk,
        }
        resp = self._request("post", f"{STRIPE_API}/v1/payment_methods", data=data, stage="stripe_payment_method")
        _ensure_ok(resp, "stripe_payment_method")
        payload = _response_json(resp, "stripe_payment_method")
        payment_method_id = str(payload.get("id") or "")
        if not payment_method_id.startswith("pm_"):
            raise GoPayFlowError(f"Stripe payment_method 返回异常: {payload}", stage="stripe_payment_method")
        return payment_method_id

    @staticmethod
    def _elements_options_client_payload() -> dict:
        return {
            "elements_options_client[stripe_js_locale]": "auto",
            "elements_options_client[saved_payment_method][enable_save]": "never",
            "elements_options_client[saved_payment_method][enable_redisplay]": "never",
        }

    @staticmethod
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

    def _stripe_init(self, checkout_session_id: str, stripe_pk: str) -> dict:
        self._progress("stripe_init")
        stripe_js_id = str(uuid.uuid4())
        elements_session_id = f"elements_session_{uuid.uuid4().hex[:11]}"
        elements_options = self._elements_options_client_payload()
        data = {
            "browser_locale": "en-US",
            "browser_timezone": "Asia/Shanghai",
            "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
            "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
            "elements_session_client[elements_init_source]": "custom_checkout",
            "elements_session_client[referrer_host]": "chatgpt.com",
            "elements_session_client[stripe_js_id]": stripe_js_id,
            "elements_session_client[locale]": "en",
            "elements_session_client[is_aggregation_expected]": "false",
            "_stripe_version": STRIPE_VERSION_FULL,
            "key": stripe_pk,
        }
        data.update(elements_options)
        resp = self._request("post", f"{STRIPE_API}/v1/payment_pages/{checkout_session_id}/init", data=data, stage="stripe_init")
        _ensure_ok(resp, "stripe_init")
        payload = _response_json(resp, "stripe_init")
        init_checksum = str(payload.get("init_checksum") or "")
        if not init_checksum:
            raise GoPayFlowError(f"Stripe init 未返回 init_checksum: {payload}", stage="stripe_init")
        return {
            "raw": payload,
            "init_checksum": init_checksum,
            "stripe_js_id": stripe_js_id,
            "elements_session_id": elements_session_id,
            "elements_session_config_id": str(uuid.uuid4()),
            "elements_options_client": elements_options,
            "config_id": str(payload.get("config_id") or ""),
            "expected_amount": self._checkout_amount(payload),
            "return_url": str(payload.get("return_url") or ""),
            "stripe_hosted_url": str(payload.get("stripe_hosted_url") or ""),
            "locale": str(payload.get("locale") or "en"),
        }

    def _stripe_confirm(self, checkout_session_id: str, payment_method_id: str, stripe_pk: str) -> dict:
        self._progress("stripe_confirm")
        init_ctx = self._stripe_init(checkout_session_id, stripe_pk)
        self.expected_due_amount = _parse_amount(init_ctx.get("expected_amount"))
        self.expected_due_currency = "stripe"
        runtime = _stripe_runtime_from_env()
        runtime.update({k: v for k, v in self.runtime.items() if v})
        chatgpt_return = (
            f"https://chatgpt.com/checkout/verify?stripe_session_id={checkout_session_id}"
            "&processor_entity=openai_llc&plan_type=plus"
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
            "expected_payment_method_type": "gopay",
            "return_url": return_url,
            "elements_session_client[elements_init_source]": "custom_checkout",
            "elements_session_client[referrer_host]": "chatgpt.com",
            "elements_session_client[stripe_js_id]": init_ctx["stripe_js_id"],
            "elements_session_client[locale]": init_ctx.get("locale") or "en",
            "elements_session_client[is_aggregation_expected]": "false",
            "elements_session_client[session_id]": init_ctx["elements_session_id"],
            "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
            "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
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
            "_stripe_version": STRIPE_VERSION_FULL,
            "key": stripe_pk,
        }
        data.update(init_ctx.get("elements_options_client") or {})
        if runtime.get("js_checksum"):
            data["js_checksum"] = runtime["js_checksum"]
        if runtime.get("rv_timestamp"):
            data["rv_timestamp"] = runtime["rv_timestamp"]
        resp = self._request(
            "post",
            f"{STRIPE_API}/v1/payment_pages/{checkout_session_id}/confirm",
            data=data,
            stage="stripe_confirm",
        )
        if resp.status_code != 200:
            hint = ""
            if not runtime.get("js_checksum") or not runtime.get("rv_timestamp"):
                hint = "；可通过 GOPAY_STRIPE_JS_CHECKSUM / GOPAY_STRIPE_RV_TIMESTAMP 配置当前 Stripe runtime"
            raise GoPayFlowError(
                f"Stripe confirm 失败: HTTP {resp.status_code} {(resp.text or '')[:500]}{hint}",
                stage="stripe_confirm",
            )
        return _response_json(resp, "stripe_confirm")

    def _approve_checkout(self, checkout_session_id: str):
        self._progress("chatgpt_approve")
        if not callable(self.approve_callback):
            raise GoPayFlowError("缺少 ChatGPT approve 回调", stage="chatgpt_approve")
        result = self.approve_callback(checkout_session_id)
        if isinstance(result, dict) and result.get("result") not in (None, "approved"):
            raise GoPayFlowError(f"ChatGPT approve 未通过: {result}", stage="chatgpt_approve")

    @staticmethod
    def _extract_redirect_url(payload: dict) -> str:
        candidates = []
        for key in ("next_action", "setup_intent", "payment_intent"):
            obj = payload.get(key)
            if isinstance(obj, dict):
                candidates.append(obj.get("next_action") if key != "next_action" else obj)
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get("type") == "redirect_to_url":
                return str((candidate.get("redirect_to_url") or {}).get("url") or "")
            if isinstance(candidate, dict) and candidate.get("redirect_to_url"):
                return str((candidate.get("redirect_to_url") or {}).get("url") or "")
        return ""

    def _resolve_snap_token(self, checkout_session_id: str, stripe_pk: str) -> str:
        self._progress("resolve_midtrans_redirect")
        params = {
            "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
            "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
            "elements_session_client[elements_init_source]": "custom_checkout",
            "elements_session_client[referrer_host]": "chatgpt.com",
            "elements_session_client[session_id]": f"elements_session_{uuid.uuid4().hex[:11]}",
            "elements_session_client[stripe_js_id]": str(uuid.uuid4()),
            "elements_session_client[locale]": "en",
            "elements_session_client[is_aggregation_expected]": "false",
            "elements_options_client[stripe_js_locale]": "auto",
            "elements_options_client[saved_payment_method][enable_save]": "never",
            "elements_options_client[saved_payment_method][enable_redisplay]": "never",
            "key": stripe_pk,
            "_stripe_version": STRIPE_VERSION_FULL,
        }
        deadline = time.time() + 60
        last_error = ""
        while time.time() < deadline:
            resp = self._request(
                "get",
                f"{STRIPE_API}/v1/payment_pages/{checkout_session_id}",
                params=params,
                stage="resolve_midtrans_redirect",
            )
            if resp.status_code == 200:
                payload = _response_json(resp, "resolve_midtrans_redirect")
                redirect_url = self._extract_redirect_url(payload)
                if redirect_url:
                    return self._fetch_pm_redirect_snap_token(redirect_url)
                setup_intent = payload.get("setup_intent") if isinstance(payload.get("setup_intent"), dict) else {}
                last_error = (
                    f"setup_intent={setup_intent.get('status')!r} "
                    f"payment_status={payload.get('payment_status')!r} status={payload.get('status')!r}"
                )
            else:
                last_error = f"HTTP {resp.status_code}: {(resp.text or '')[:160]}"
            time.sleep(1)
        raise GoPayFlowError(f"未能解析 Midtrans snap_token: {last_error}", stage="resolve_midtrans_redirect")

    def _fetch_pm_redirect_snap_token(self, redirect_url: str) -> str:
        if "app.midtrans.com/snap/" in redirect_url:
            matched = re.search(r"app\.midtrans\.com/snap/v[14]/redirection/([a-f0-9-]{36})", redirect_url)
            if matched:
                return matched.group(1)
        resp = self._request("get", redirect_url, allow_redirects=False, stage="pm_redirect")
        if resp.status_code not in (301, 302, 303, 307, 308):
            raise GoPayFlowError(f"pm-redirects 未返回跳转: HTTP {resp.status_code}", stage="pm_redirect")
        location = resp.headers.get("Location", "")
        matched = re.search(r"app\.midtrans\.com/snap/v[14]/redirection/([a-f0-9-]{36})", location)
        if not matched:
            raise GoPayFlowError(f"pm-redirects Location 缺少 snap_token: {location}", stage="pm_redirect")
        return matched.group(1)

    def _midtrans_auth_header(self) -> dict:
        token = base64.b64encode(f"{self.midtrans_client_id}:".encode("ascii")).decode("ascii")
        return {"Authorization": f"Basic {token}"}

    def _midtrans_load_transaction(self, snap_token: str):
        self._progress("midtrans_load_transaction", snap_token=snap_token)
        resp = self._request(
            "get",
            f"https://app.midtrans.com/snap/v1/transactions/{snap_token}",
            headers={
                "x-source": "snap",
                "x-source-app-type": "redirection",
                "x-source-version": "2.3.0",
            },
            stage="midtrans_load_transaction",
        )
        _ensure_ok(resp, "midtrans_load_transaction")
        return _response_json(resp, "midtrans_load_transaction")

    @staticmethod
    def _midtrans_gross_amount(transaction: dict) -> tuple[int, str]:
        details = transaction.get("transaction_details") if isinstance(transaction, dict) else {}
        raw_amount = str((details or {}).get("gross_amount") or "0").strip()
        currency = str((details or {}).get("currency") or "").strip()
        try:
            amount = int(float(raw_amount or "0"))
        except Exception:
            amount = 0
        return amount, currency

    def _guard_final_charge(self, transaction: dict):
        if _env_truthy("GOPAY_ALLOW_NONZERO_CHARGE"):
            return
        if self.expected_due_amount is not None:
            if self.expected_due_amount <= 0:
                self._progress("stripe_zero_due_confirmed")
                return
            self._progress("stripe_nonzero_amount_blocked", expected_amount=str(self.expected_due_amount))
            raise GoPayChargeBlocked(
                (
                    f"Stripe expected_amount={self.expected_due_amount} 非 0，已在最终扣款前停止；"
                    "如确认要真实扣款，设置 GOPAY_ALLOW_NONZERO_CHARGE=1 后重试"
                ),
                stage="stripe_charge_guard",
            )
        amount, currency = self._midtrans_gross_amount(transaction)
        if amount <= 0:
            return
        self._progress("midtrans_nonzero_amount_blocked", gross_amount=str(amount), currency=currency)
        raise GoPayChargeBlocked(
            (
                f"Midtrans gross_amount={amount} {currency or 'IDR'} 非 0，已在最终扣款前停止；"
                "如确认要真实扣款，设置 GOPAY_ALLOW_NONZERO_CHARGE=1 后重试"
            ),
            stage="midtrans_charge_guard",
        )

    def _midtrans_init_linking(self, snap_token: str) -> str:
        self._progress("midtrans_linking")
        headers = {
            **self._midtrans_auth_header(),
            "Content-Type": "application/json",
            "Origin": "https://app.midtrans.com",
            "Referer": f"https://app.midtrans.com/snap/v4/redirection/{snap_token}",
        }
        body = {
            "type": "gopay",
            "country_code": self.country_code,
            "phone_number": self.phone_number,
        }
        last_error = ""
        for attempt in range(1, GOPAY_LINK_RETRY_LIMIT + 2):
            resp = self._request(
                "post",
                f"https://app.midtrans.com/snap/v3/accounts/{snap_token}/linking",
                json=body,
                headers=headers,
                stage="midtrans_linking",
            )
            if resp.status_code == 201:
                payload = _response_json(resp, "midtrans_linking")
                self.activation_link_url = str(payload.get("activation_link_url") or "")
                matched = re.search(r"reference=([a-f0-9-]{36})", self.activation_link_url)
                if not matched:
                    raise GoPayFlowError(f"Midtrans linking 缺少 reference: {payload}", stage="midtrans_linking")
                return matched.group(1)
            if resp.status_code == 406:
                payload = _response_json(resp, "midtrans_linking")
                messages = payload.get("error_messages") or []
                last_error = str(messages[0] if messages else payload)
                if "already linked" in last_error.lower():
                    if attempt > GOPAY_LINK_RETRY_LIMIT:
                        self._progress(
                            "midtrans_already_linked_failed",
                            attempt=attempt,
                            max_retries=GOPAY_LINK_RETRY_LIMIT,
                            message="该 GoPay 手机号已绑定其他账号，已重试 3 次仍未解除绑定",
                        )
                        raise GoPayAlreadyLinked(
                            "该 GoPay 手机号已绑定其他账号；请先在 GoPay 侧解绑其他账号后再重试",
                            stage="midtrans_linking",
                        )
                    self._progress(
                        "midtrans_already_linked",
                        attempt=attempt,
                        max_retries=GOPAY_LINK_RETRY_LIMIT,
                        wait_seconds=int(GOPAY_LINK_RETRY_SLEEP_S),
                        message="该 GoPay 手机号已绑定其他账号，请先解绑其他账号；30 秒后自动重试",
                    )
                    logger.info(
                        "[gopay_executor] Midtrans linking already linked (%s), wait %ss before retry %s/%s",
                        last_error,
                        GOPAY_LINK_RETRY_SLEEP_S,
                        attempt,
                        GOPAY_LINK_RETRY_LIMIT,
                    )
                    time.sleep(GOPAY_LINK_RETRY_SLEEP_S)
                    continue
                logger.info(
                    "[gopay_executor] Midtrans linking 406 (%s), retry %s/%s",
                    last_error,
                    attempt,
                    GOPAY_LINK_RETRY_LIMIT,
                )
                if attempt <= GOPAY_LINK_RETRY_LIMIT:
                    time.sleep(GOPAY_LINK_RETRY_SLEEP_S)
                continue
            raise GoPayFlowError(f"Midtrans linking 失败: HTTP {resp.status_code} {(resp.text or '')[:300]}", stage="midtrans_linking")
        raise GoPayFlowError(f"Midtrans linking 重试耗尽: {last_error}", stage="midtrans_linking")

    def _gopay_validate_reference(self, reference_id: str):
        self._progress("gopay_validate_reference")
        resp = self._request(
            "post",
            "https://gwa.gopayapi.com/v1/linking/validate-reference",
            json={"reference_id": reference_id},
            headers={"Origin": "https://merchants-gws-app.gopayapi.com", "Referer": "https://merchants-gws-app.gopayapi.com/"},
            stage="gopay_validate_reference",
        )
        _ensure_ok(resp, "gopay_validate_reference")
        payload = _response_json(resp, "gopay_validate_reference")
        if _looks_like_gopay_rate_limit_payload(payload):
            self._progress("gopay_rate_limited")
            raise GoPayRateLimited(_gopay_rate_limited_message(), stage="gopay_rate_limited")
        if not payload.get("success"):
            raise GoPayFlowError(f"GoPay validate-reference 失败: {payload}", stage="gopay_validate_reference")

    def _gopay_user_consent(self, reference_id: str):
        self._progress("gopay_user_consent")
        resp = self._request(
            "post",
            "https://gwa.gopayapi.com/v1/linking/user-consent",
            json={"reference_id": reference_id},
            headers={
                "Origin": "https://merchants-gws-app.gopayapi.com",
                "Referer": "https://merchants-gws-app.gopayapi.com/",
                "x-user-locale": "en-US",
            },
            stage="gopay_user_consent",
        )
        _ensure_ok(resp, "gopay_user_consent")
        payload = _response_json(resp, "gopay_user_consent")
        if _looks_like_gopay_rate_limit_payload(payload):
            self._progress("gopay_rate_limited")
            raise GoPayRateLimited(_gopay_rate_limited_message(), stage="gopay_rate_limited")
        if not payload.get("success"):
            raise GoPayFlowError(f"GoPay user-consent 失败: {payload}", stage="gopay_user_consent")

    def _gopay_validate_otp(self, reference_id: str, otp: str) -> tuple[str, str]:
        self._progress("gopay_validate_otp")
        resp = self._request(
            "post",
            "https://gwa.gopayapi.com/v1/linking/validate-otp",
            json={"reference_id": reference_id, "otp": otp},
            headers={"Origin": "https://merchants-gws-app.gopayapi.com", "Referer": "https://merchants-gws-app.gopayapi.com/"},
            stage="gopay_validate_otp",
        )
        _ensure_ok(resp, "gopay_validate_otp")
        payload = _response_json(resp, "gopay_validate_otp")
        if _looks_like_gopay_rate_limit_payload(payload):
            self._progress("gopay_rate_limited")
            raise GoPayRateLimited(_gopay_rate_limited_message(), stage="gopay_rate_limited")
        if not payload.get("success"):
            raise GoPayFlowError(f"GoPay OTP 校验失败: {payload}", stage="gopay_validate_otp")
        challenge = payload.get("data", {}).get("challenge", {}).get("action", {}).get("value", {})
        challenge_id = str(challenge.get("challenge_id") or "")
        client_id = str(challenge.get("client_id") or "")
        if not challenge_id or not client_id:
            raise GoPayFlowError(f"GoPay OTP 返回缺少 PIN challenge: {payload}", stage="gopay_validate_otp")
        return challenge_id, client_id

    def _tokenize_pin(self, challenge_id: str, client_id: str) -> str:
        self._progress("gopay_tokenize_pin")
        resp = self._request(
            "post",
            "https://customer.gopayapi.com/api/v1/users/pin/tokens/nb",
            json={"challenge_id": challenge_id, "client_id": client_id, "pin": self.gopay_pin},
            headers={
                "x-appversion": "1.0.0",
                "x-correlation-id": str(uuid.uuid4()),
                "x-is-mobile": "false",
                "x-platform": "Windows",
                "x-request-id": str(uuid.uuid4()),
                "x-user-locale": "id",
                "Origin": "https://pin-web-client.gopayapi.com",
                "Referer": "https://pin-web-client.gopayapi.com/",
            },
            stage="gopay_tokenize_pin",
        )
        if resp.status_code in (400, 401, 403):
            raise GoPayPINRejected(f"GoPay PIN 被拒绝: {(resp.text or '')[:200]}", stage="gopay_tokenize_pin")
        _ensure_ok(resp, "gopay_tokenize_pin")
        payload = _response_json(resp, "gopay_tokenize_pin")
        token = (
            payload.get("token")
            or payload.get("data", {}).get("token")
            or payload.get("data", {}).get("pin_token")
            or ""
        )
        if not token:
            raise GoPayFlowError(f"GoPay PIN token 响应缺少 token: {payload}", stage="gopay_tokenize_pin")
        return str(token)

    def _gopay_validate_pin(self, reference_id: str, pin_token: str):
        self._progress("gopay_validate_pin")
        resp = self._request(
            "post",
            "https://gwa.gopayapi.com/v1/linking/validate-pin",
            json={"reference_id": reference_id, "token": pin_token},
            headers={"Origin": "https://merchants-gws-app.gopayapi.com", "Referer": "https://merchants-gws-app.gopayapi.com/"},
            stage="gopay_validate_pin",
        )
        _ensure_ok(resp, "gopay_validate_pin")
        payload = _response_json(resp, "gopay_validate_pin")
        if not payload.get("success"):
            raise GoPayFlowError(f"GoPay validate-pin 失败: {payload}", stage="gopay_validate_pin")

    def _midtrans_create_charge(self, snap_token: str) -> str:
        self._progress("midtrans_create_charge")
        resp = self._request(
            "post",
            f"https://app.midtrans.com/snap/v2/transactions/{snap_token}/charge",
            json={"payment_type": "gopay", "tokenization": "true", "promo_details": None},
            headers={
                **self._midtrans_auth_header(),
                "Content-Type": "application/json",
                "Origin": "https://app.midtrans.com",
                "Referer": f"https://app.midtrans.com/snap/v4/redirection/{snap_token}",
            },
            stage="midtrans_create_charge",
        )
        _ensure_ok(resp, "midtrans_create_charge")
        payload = _response_json(resp, "midtrans_create_charge")
        matched = re.search(r"reference=([A-Za-z0-9]+)", str(payload.get("gopay_verification_link_url") or ""))
        if not matched:
            raise GoPayFlowError(f"Midtrans charge 缺少 GoPay reference: {payload}", stage="midtrans_create_charge")
        return matched.group(1)

    def _gopay_payment_validate(self, charge_ref: str):
        self._progress("gopay_payment_validate")
        last_text = ""
        for _ in range(8):
            resp = self._request(
                "get",
                f"https://gwa.gopayapi.com/v1/payment/validate?reference_id={charge_ref}",
                headers={"Origin": "https://merchants-gws-app.gopayapi.com", "Referer": "https://merchants-gws-app.gopayapi.com/"},
                stage="gopay_payment_validate",
            )
            last_text = resp.text or ""
            if resp.status_code == 200:
                payload = _response_json(resp, "gopay_payment_validate")
                if payload.get("success"):
                    return
            time.sleep(1.5)
        raise GoPayFlowError(f"GoPay payment/validate 未就绪: {last_text[:200]}", stage="gopay_payment_validate")

    def _gopay_payment_confirm(self, charge_ref: str) -> tuple[str, str]:
        self._progress("gopay_payment_confirm")
        resp = self._request(
            "post",
            f"https://gwa.gopayapi.com/v1/payment/confirm?reference_id={charge_ref}",
            json={"payment_instructions": []},
            headers={"Origin": "https://merchants-gws-app.gopayapi.com", "Referer": "https://merchants-gws-app.gopayapi.com/"},
            stage="gopay_payment_confirm",
        )
        _ensure_ok(resp, "gopay_payment_confirm")
        payload = _response_json(resp, "gopay_payment_confirm")
        if not payload.get("success"):
            raise GoPayFlowError(f"GoPay payment/confirm 失败: {payload}", stage="gopay_payment_confirm")
        challenge = payload.get("data", {}).get("challenge", {}).get("action", {}).get("value", {})
        challenge_id = str(challenge.get("challenge_id") or "")
        client_id = str(challenge.get("client_id") or "")
        if not challenge_id or not client_id:
            raise GoPayFlowError(f"GoPay payment/confirm 缺少 PIN challenge: {payload}", stage="gopay_payment_confirm")
        return challenge_id, client_id

    def _gopay_payment_process(self, charge_ref: str, pin_token: str):
        self._progress("gopay_payment_process")
        resp = self._request(
            "post",
            f"https://gwa.gopayapi.com/v1/payment/process?reference_id={charge_ref}",
            json={"challenge": {"type": "GOPAY_PIN_CHALLENGE", "value": {"pin_token": pin_token}}},
            headers={"Origin": "https://merchants-gws-app.gopayapi.com", "Referer": "https://merchants-gws-app.gopayapi.com/"},
            stage="gopay_payment_process",
        )
        _ensure_ok(resp, "gopay_payment_process")
        payload = _response_json(resp, "gopay_payment_process")
        if not payload.get("success") or payload.get("data", {}).get("next_action") != "payment-success":
            raise GoPayFlowError(f"GoPay payment/process 未成功: {payload}", stage="gopay_payment_process")

    def _verify_checkout(self, checkout_session_id: str) -> dict:
        self._progress("chatgpt_verify")
        if callable(self.verify_callback):
            return self.verify_callback(checkout_session_id)
        return {"state": "succeeded"}

    def run(self, *, checkout_session_id: str, stripe_pk: str) -> dict:
        payment_method_id = self._stripe_create_payment_method(checkout_session_id, stripe_pk)
        self._stripe_confirm(checkout_session_id, payment_method_id, stripe_pk)
        self._approve_checkout(checkout_session_id)
        snap_token = self._resolve_snap_token(checkout_session_id, stripe_pk)
        result = self.run_from_snap_token(snap_token=snap_token, checkout_session_id=checkout_session_id)
        result["session_id"] = checkout_session_id
        result["checkout_session_id"] = checkout_session_id
        return result

    def run_from_redirect(self, *, redirect_url: str, checkout_session_id: str = "") -> dict:
        snap_token = self._fetch_pm_redirect_snap_token(redirect_url)
        return self.run_from_snap_token(snap_token=snap_token, checkout_session_id=checkout_session_id)

    def run_from_snap_token(self, *, snap_token: str, checkout_session_id: str = "") -> dict:
        transaction = self._midtrans_load_transaction(snap_token)
        reference_id = self._midtrans_init_linking(snap_token)
        self._gopay_validate_reference(reference_id)
        self._gopay_user_consent(reference_id)
        if callable(self.sms_otp_trigger_callback):
            self.sms_otp_trigger_callback(reference_id, self.activation_link_url)
        self._progress("wait_otp")
        otp = self.otp_provider()
        if not otp:
            raise GoPayOTPCancelled("未获取到 GoPay OTP", stage="fetch_otp")
        challenge_id, client_id = self._gopay_validate_otp(reference_id, otp)
        pin_token = self._tokenize_pin(challenge_id, client_id)
        self._gopay_validate_pin(reference_id, pin_token)

        self._guard_final_charge(transaction)
        charge_ref = self._midtrans_create_charge(snap_token)
        self._gopay_payment_validate(charge_ref)
        charge_challenge_id, charge_client_id = self._gopay_payment_confirm(charge_ref)
        charge_pin_token = self._tokenize_pin(charge_challenge_id, charge_client_id)
        self._gopay_payment_process(charge_ref, charge_pin_token)

        verify = self._verify_checkout(checkout_session_id) if checkout_session_id else {"state": "succeeded"}
        state = "succeeded" if verify.get("state") == "succeeded" else "verify_timeout"
        return {
            "state": state,
            "snap_token": snap_token,
            "charge_ref": charge_ref,
            "reference_id": reference_id,
            "verify": verify,
        }

PHONE_PAGE_SELECTORS = (
    'input[type="tel"]',
    'input[name*="phone" i]',
    'input[id*="phone" i]',
    'input[autocomplete="tel"]',
    'input[placeholder*="phone" i]',
    'input[placeholder*="nomor" i]',
    'input[placeholder*="62"]',
    'input[placeholder*="08"]',
)
PHONE_PAGE_PLACEHOLDERS = ("Phone number", "Nomor handphone", "Nomor telepon", "+62", "08")
PHONE_PAGE_LABELS = ("Phone number", "Nomor handphone", "Nomor telepon")

FRAME_BILLING_NAME_SELECTORS = [
    'input[placeholder="全名"]',
    'input[placeholder="Full name"]',
    'input[placeholder="Name"]',
    'input[autocomplete="name"]',
    'input[name*="name" i]',
    'input[placeholder*="全名"]',
    'input[placeholder*="姓名"]',
    'input[placeholder*="full name" i]',
]
FRAME_BILLING_COUNTRY_SELECTORS = [
    'select[aria-label*="国家" i]',
    'select[aria-label*="country" i]',
    'select[placeholder*="Country" i]',
    'select[autocomplete="country-name"]',
    'select[name*="country" i]',
]
FRAME_BILLING_STATE_SELECTORS = [
    'select[placeholder*="州"]',
    'input[placeholder*="州"]',
    'select[aria-label*="州"]',
    'input[aria-label*="州"]',
    'select[placeholder="State"]',
    'input[placeholder="State"]',
    'select[aria-label*="state" i]',
    'input[aria-label*="state" i]',
    'select[placeholder*="Province" i]',
    'input[placeholder*="Province" i]',
    'select[autocomplete="address-level1"]',
    'input[autocomplete="address-level1"]',
    'select[name*="state" i]',
    'input[name*="state" i]',
]
FRAME_BILLING_CITY_SELECTORS = [
    'input[placeholder="城市"]',
    'input[aria-label*="城市"]',
    'input[placeholder="City"]',
    'input[aria-label*="city" i]',
    'input[placeholder*="Town" i]',
    'input[autocomplete="address-level2"]',
    'input[name*="city" i]',
]
FRAME_BILLING_ZIP_SELECTORS = [
    'input[placeholder*="邮政编码"]',
    'input[aria-label*="邮政编码"]',
    'input[placeholder="ZIP"]',
    'input[placeholder="ZIP code"]',
    'input[placeholder="Postal code"]',
    'input[aria-label*="zip" i]',
    'input[aria-label*="postal" i]',
    'input[autocomplete="postal-code"]',
    'input[name*="postal" i]',
    'input[name*="zip" i]',
]
FRAME_BILLING_ADDRESS1_SELECTORS = [
    'input[placeholder="地址"]',
    'input[placeholder*="地址第 1 行"]',
    'input[aria-label*="地址第 1 行"]',
    'input[placeholder="Address line 1"]',
    'input[placeholder="Address"]',
    'input[placeholder="Street address"]',
    'input[aria-label*="address line 1" i]',
    'input[autocomplete="address-line1"]',
    'input[name*="line1" i]',
]
FRAME_BILLING_ADDRESS2_SELECTORS = [
    'input[placeholder*="地址第 2 行"]',
    'input[aria-label*="地址第 2 行"]',
    'input[placeholder="Address line 2"]',
    'input[placeholder*="Apartment" i]',
    'input[placeholder*="Suite" i]',
    'input[aria-label*="address line 2" i]',
    'input[autocomplete="address-line2"]',
    'input[name*="line2" i]',
]
CN_BILLING_NAME_SELECTORS = ['input[placeholder="全名"]']
CN_BILLING_COUNTRY_SELECTORS = ['select[aria-label*="国家" i]', 'select[placeholder*="国家"]']
CN_BILLING_ADDRESS1_SELECTORS = ['input[placeholder="地址第 1 行"]']
CN_BILLING_ADDRESS2_SELECTORS = ['input[placeholder="地址第 2 行"]']
CN_BILLING_CITY_SELECTORS = ['input[placeholder="城市"]']
CN_BILLING_STATE_SELECTORS = ['select[placeholder="州"]', 'input[placeholder="州"]']
CN_BILLING_ZIP_SELECTORS = ['input[placeholder="邮政编码"]']

BILLING_NAME_LABELS = ["全名", "姓名", "Full name", "Name"]
BILLING_COUNTRY_LABELS = ["国家或地区", "国家", "Country or region", "Country"]
BILLING_ADDRESS1_LABELS = ["地址第 1 行", "地址", "地址1", "Address line 1", "Address"]
BILLING_ADDRESS2_LABELS = ["地址第 2 行", "地址2", "Address line 2", "Apartment, suite, etc."]
BILLING_CITY_LABELS = ["城市", "City", "Town / City"]
BILLING_STATE_LABELS = ["州", "省", "State", "Province", "State / Province"]
BILLING_ZIP_LABELS = ["邮政编码", "邮编", "ZIP", "ZIP code", "Postal code"]

BILLING_NAME_PLACEHOLDERS = ["全名", "Full name", "Name"]
BILLING_ADDRESS1_PLACEHOLDERS = ["地址第 1 行", "地址", "Address line 1", "Address", "Street address"]
BILLING_ADDRESS2_PLACEHOLDERS = ["地址第 2 行", "Address line 2", "Apartment", "Suite"]
BILLING_CITY_PLACEHOLDERS = ["城市", "City", "Town"]
BILLING_STATE_PLACEHOLDERS = ["州", "State", "Province"]
BILLING_ZIP_PLACEHOLDERS = ["邮政编码", "ZIP", "ZIP code", "Postal code"]

DEFAULT_BILLING_ADDRESS = {
    "name": "John Doe",
    "country": "US",
    "state": "CA",
    "city": "Los Angeles",
    "zip": "90026",
    "address1": "3110 Sunset Boulevard",
    "address2": "",
    "phone_number": "213-555-0182",
}


def _looks_like_phone_number(value: str) -> bool:
    raw = re.sub(r"\s+", "", str(value or "").strip())
    if not raw:
        return False
    if raw.startswith("+"):
        return True
    digits_only = re.sub(r"\D", "", raw)
    return len(digits_only) >= 8 and any(ch in raw for ch in ("+", "-", "(", ")"))


def _split_address_lines(address1: str) -> tuple[str, str]:
    raw = str(address1 or "").strip()
    if not raw:
        return "", ""
    matched = re.match(r"^(.*?)(?:\s+(APT|APARTMENT|UNIT|STE|SUITE|FL)\.?\s+.+)$", raw, flags=re.IGNORECASE)
    if not matched:
        return raw, ""
    line1 = matched.group(1).strip()
    line2 = raw[len(line1):].strip(" ,")
    return line1, line2


def _fetch_random_billing_address() -> dict:
    try:
        resp = requests.post(
            "https://www.meiguodizhi.io/api/v1/ai-random-address",
            json={"path": "/", "method": "address"},
            headers={
                "Content-Type": "application/json",
                "Origin": "http://localhost:5173",
                "Referer": "https://www.meiguodizhi.io/",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        address = data.get("address") or {}
    except Exception as exc:
        logger.info("[gopay_executor] random billing address service unavailable, using fallback: %s", exc)
        return dict(DEFAULT_BILLING_ADDRESS)
    full_name = str(address.get("Full_Name") or "").strip()
    address1 = str(address.get("Address") or "").strip()
    city = str(address.get("City") or "").strip()
    state = str(address.get("State") or "").strip()
    zip_code = str(address.get("Zip_Code") or "").strip()
    if not all([full_name, address1, city, state, zip_code]):
        logger.info("[gopay_executor] random billing address response incomplete, using fallback")
        return dict(DEFAULT_BILLING_ADDRESS)
    line1, line2 = _split_address_lines(address1)
    return {
        "name": full_name,
        "country": "US",
        "state": state,
        "city": city,
        "zip": zip_code,
        "address1": line1 or address1,
        "address2": line2,
        "phone_number": str(address.get("Telephone") or "").strip(),
        "raw": address,
    }


def _public_billing_info(billing: dict | None) -> dict:
    source = dict(billing or {})
    return {
        "name": str(source.get("name") or "").strip(),
        "country": str(source.get("country") or "").strip(),
        "state": str(source.get("state") or "").strip(),
        "city": str(source.get("city") or "").strip(),
        "zip": str(source.get("zip") or "").strip(),
        "address1": str(source.get("address1") or "").strip(),
        "address2": str(source.get("address2") or "").strip(),
        "phone_number": str(source.get("phone_number") or "").strip(),
    }


def _build_result(
    status: str,
    *,
    failure_stage: str = "",
    message: str = "",
    screenshot_paths: list[str] | None = None,
    checkout_url: str = "",
    billing_info: dict | None = None,
):
    return {
        "status": status,
        "failure_stage": failure_stage,
        "message": message,
        "screenshot_paths": screenshot_paths or [],
        "checkout_url": checkout_url,
        "billing_info": dict(billing_info or {}),
    }


def _capture_screenshot(api: ChatGPTTeamAPI, session_id: str, stage: str, screenshot_paths: list[str]):
    try:
        if not getattr(api, "page", None):
            return ""
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = SCREENSHOT_DIR / f"{session_id}-{stage}.png"
        api.page.screenshot(path=str(path), full_page=True, timeout=5000)
        screenshot_paths.append(str(path))
        return str(path)
    except Exception as exc:
        logger.warning("[gopay_executor] 截图失败(%s): %s", stage, exc)
        return ""


def _visible_locator(api: ChatGPTTeamAPI, selectors: list[str], timeout_ms: int = 4000):
    return api._visible_locator_in_frames(selectors, timeout_ms=timeout_ms)


def _click(api: ChatGPTTeamAPI, selectors: list[str], label: str, timeout_ms: int = 5000):
    locator = _visible_locator(api, selectors, timeout_ms=timeout_ms)
    if not locator:
        return False, f"未找到 {label}"
    try:
        locator.click(timeout=timeout_ms)
        return True, ""
    except Exception as exc:
        return False, f"点击 {label} 失败: {exc}"


def _fill(api: ChatGPTTeamAPI, selectors: list[str], value: str, label: str, timeout_ms: int = 5000):
    locator = _visible_locator(api, selectors, timeout_ms=timeout_ms)
    if not locator:
        return False, f"未找到 {label}"
    try:
        locator.click(timeout=min(timeout_ms, 2000))
    except Exception:
        pass
    try:
        locator.fill(str(value or ""), timeout=timeout_ms)
        return True, ""
    except Exception as exc:
        return False, f"填写 {label} 失败: {exc}"


def _scroll_locator_into_view(locator, label: str):
    try:
        locator.scroll_into_view_if_needed(timeout=2500)
        logger.info("[gopay_executor] 已滚动到字段 %s", label)
        return True
    except Exception as exc:
        logger.info("[gopay_executor] 滚动到字段 %s 失败: %s", label, exc)
        return False


def _read_locator_value(locator) -> str:
    try:
        return str(locator.input_value(timeout=800) or "").strip()
    except Exception:
        pass
    try:
        return str(locator.text_content(timeout=800) or "").strip()
    except Exception:
        return ""


def _set_locator_value(locator, value: str) -> bool:
    script = """(el, value) => {
      if (!el) return false;
      el.setAttribute('autocomplete', 'off');
      el.setAttribute('aria-autocomplete', 'none');
      const tag = (el.tagName || '').toLowerCase();
      if (tag === 'select') {
        el.value = value;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        el.dispatchEvent(new Event('blur', { bubbles: true }));
        if (typeof el.blur === 'function') el.blur();
        return true;
      }
      const proto = tag === 'textarea' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
      if (descriptor && descriptor.set) descriptor.set.call(el, value);
      else el.value = value;
      let inputEvent;
      try {
        inputEvent = new InputEvent('input', { bubbles: true, inputType: 'insertText', data: value });
      } catch (_) {
        inputEvent = new Event('input', { bubbles: true });
      }
      el.dispatchEvent(inputEvent);
      el.dispatchEvent(new Event('change', { bubbles: true }));
      el.dispatchEvent(new Event('blur', { bubbles: true }));
      if (typeof el.blur === 'function') el.blur();
      return true;
    }"""
    try:
        return bool(locator.evaluate(script, str(value or ""), timeout=2000))
    except Exception:
        return False


def _value_matches(expected: str, actual: str) -> bool:
    expected_raw = str(expected or "").strip()
    actual_raw = str(actual or "").strip()
    if expected_raw == actual_raw:
        return True
    expected_norm = re.sub(r"\s+", " ", expected_raw).lower()
    actual_norm = re.sub(r"\s+", " ", actual_raw).lower()
    return bool(expected_norm) and expected_norm == actual_norm


def _dismiss_address_autocomplete(api: ChatGPTTeamAPI, address1_locator=None):
    try:
        if address1_locator:
            address1_locator.evaluate(
                """(el) => {
                  el.setAttribute('autocomplete', 'off');
                  el.setAttribute('aria-autocomplete', 'none');
                  if (typeof el.blur === 'function') el.blur();
                }""",
                timeout=800,
            )
    except Exception:
        pass
    try:
        if address1_locator:
            try:
                address1_locator.press("Escape", timeout=800)
            except Exception:
                pass
        api.page.keyboard.press("Escape")
        time.sleep(0.2)
        logger.info("[gopay_executor] 已关闭地址自动推荐，改为手动填写城市/州/邮编")
    except Exception as exc:
        logger.info("[gopay_executor] 关闭地址自动推荐失败: %s", exc)


def _suppress_address_autocomplete_ui(api: ChatGPTTeamAPI):
    script = """() => {
      const id = 'autoteam-hide-address-autocomplete';
      if (!document.getElementById(id)) {
        const style = document.createElement('style');
        style.id = id;
        style.textContent = [
          'iframe[src*="autocomplete-suggestions"]',
          'iframe[title*="autocomplete" i]'
        ].join(',') + '{display:none!important;pointer-events:none!important;visibility:hidden!important;}';
        document.documentElement.appendChild(style);
      }
      return true;
    }"""
    try:
        api.page.evaluate(script)
    except Exception:
        pass


def _iter_page_frames(api: ChatGPTTeamAPI):
    try:
        page = getattr(api, "page", None)
        if not page:
            return []
        frames = []
        main_frame = getattr(page, "main_frame", None)
        if main_frame:
            frames.append(main_frame)
        for frame in list(getattr(page, "frames", []) or []):
            if frame not in frames:
                frames.append(frame)
        return frames
    except Exception:
        return []


def _locator_by_placeholder_or_label(api: ChatGPTTeamAPI, placeholders: list[str], labels: list[str], timeout_ms: int = 1200, frames=None):
    return _locator_by_placeholder_or_label_with_state(
        api,
        placeholders,
        labels,
        timeout_ms=timeout_ms,
        require_visible=True,
        frames=frames,
    )


def _locator_by_placeholder_or_label_with_state(
    api: ChatGPTTeamAPI,
    placeholders: list[str],
    labels: list[str],
    timeout_ms: int = 1200,
    require_visible: bool = True,
    frames=None,
):
    state = "visible" if require_visible else "attached"
    per_try_timeout = max(80, min(180, timeout_ms))
    for frame in (frames or _iter_page_frames(api)):
        for text in placeholders:
            try:
                locator = frame.get_by_placeholder(text, exact=True).first
                locator.wait_for(state=state, timeout=per_try_timeout)
                return locator
            except Exception:
                continue
        for text in placeholders:
            try:
                locator = frame.get_by_placeholder(re.compile(re.escape(text), re.IGNORECASE)).first
                locator.wait_for(state=state, timeout=per_try_timeout)
                return locator
            except Exception:
                continue
        for text in labels:
            try:
                locator = frame.get_by_label(text, exact=True).first
                locator.wait_for(state=state, timeout=per_try_timeout)
                return locator
            except Exception:
                continue
        for text in labels:
            try:
                locator = frame.get_by_label(re.compile(re.escape(text), re.IGNORECASE)).first
                locator.wait_for(state=state, timeout=per_try_timeout)
                return locator
            except Exception:
                continue
    return None


def _resolve_page_billing_locator(
    api: ChatGPTTeamAPI,
    selectors: list[str],
    placeholders: list[str] | None = None,
    labels: list[str] | None = None,
    timeout_ms: int = 1200,
    require_visible: bool = True,
    frames=None,
):
    state = "visible" if require_visible else "attached"
    for frame in (frames or _iter_page_frames(api)):
        for selector in selectors:
            try:
                candidate = frame.locator(selector).first
                candidate.wait_for(state=state, timeout=min(400, timeout_ms))
                return candidate
            except Exception:
                continue
    locator = None
    if placeholders or labels:
        locator = _locator_by_placeholder_or_label_with_state(
            api,
            placeholders or [],
            labels or [],
            timeout_ms=timeout_ms,
            require_visible=require_visible,
            frames=frames,
        )
    if locator:
        return locator
    return None


def _score_billing_frame(frame) -> int:
    script = """() => {
      const texts = [];
      for (const node of document.querySelectorAll('input,select,textarea,label,[aria-label]')) {
        texts.push(node.getAttribute('placeholder') || '');
        texts.push(node.getAttribute('aria-label') || '');
        texts.push(node.getAttribute('autocomplete') || '');
        texts.push(node.getAttribute('name') || '');
        texts.push(node.innerText || node.textContent || '');
      }
      const haystack = texts.join('\\n').toLowerCase();
      const tests = [
        /全名|full name|\\bname\\b/,
        /国家或地区|country/,
        /地址第\\s*1\\s*行|address line 1|street address|address-line1/,
        /城市|city|address-level2/,
        /州|state|province|address-level1/,
        /邮政编码|postal|zip/
      ];
      return tests.reduce((score, pattern) => score + (pattern.test(haystack) ? 1 : 0), 0);
    }"""
    try:
        return int(frame.evaluate(script) or 0)
    except Exception:
        return 0


def _find_billing_form_frames(api: ChatGPTTeamAPI, timeout_seconds: int = 5):
    deadline = time.time() + timeout_seconds
    best_frames = []
    best_score = 0
    while time.time() < deadline:
        scored = []
        for frame in _iter_page_frames(api):
            score = _score_billing_frame(frame)
            if score:
                scored.append((score, frame))
        if scored:
            scored.sort(key=lambda item: item[0], reverse=True)
            best_score, best_frame = scored[0]
            best_frames = [best_frame]
            if best_score >= 3:
                frame_url = str(getattr(best_frame, "url", "") or "")
                if len(frame_url) > 180:
                    frame_url = frame_url[:180] + "..."
                logger.info(
                    "[gopay_executor] 已锁定账单表单 frame，score=%s url=%s",
                    best_score,
                    frame_url,
                )
                return best_frames
        time.sleep(0.3)
    if best_frames:
        frame_url = str(getattr(best_frames[0], "url", "") or "")
        if len(frame_url) > 180:
            frame_url = frame_url[:180] + "..."
        logger.info(
            "[gopay_executor] 使用最高分账单 frame，score=%s url=%s",
            best_score,
            frame_url,
        )
        return best_frames
    logger.info("[gopay_executor] 未能锁定账单 frame，回退到全页面 frame 搜索")
    return None


def _scroll_to_billing_section(api: ChatGPTTeamAPI):
    selectors = [
        'text=账单地址',
        'text=Billing address',
        'text=Billing Address',
    ]
    locator = _visible_locator(api, selectors, timeout_ms=2000)
    if locator:
        try:
            locator.scroll_into_view_if_needed(timeout=2000)
            logger.info("[gopay_executor] 已滚动到账单地址区域")
            return True
        except Exception:
            pass
    try:
        api.page.evaluate(
            """() => {
              const nodes = Array.from(document.querySelectorAll('h1,h2,h3,h4,div,span,label'));
              const hit = nodes.find((node) => /账单地址|billing address/i.test((node.innerText || node.textContent || '').trim()));
              if (hit) hit.scrollIntoView({ behavior: 'instant', block: 'center' });
            }"""
        )
        logger.info("[gopay_executor] 已尝试滚动到账单地址区域")
        return True
    except Exception:
        return False

def _fill_billing_form_on_page(api: ChatGPTTeamAPI, billing: dict, session_id: str, screenshot_paths: list[str]):
    _scroll_to_billing_section(api)
    _suppress_address_autocomplete_ui(api)
    billing_frames = _find_billing_form_frames(api, timeout_seconds=4)
    field_locators: dict[str, object] = {}

    def _resolve_field_locator(
        selectors: list[str],
        placeholders: list[str] | None = None,
        labels: list[str] | None = None,
        timeout_ms: int = 3000,
        require_visible: bool = True,
    ):
        return _resolve_page_billing_locator(
            api,
            selectors,
            placeholders=placeholders,
            labels=labels,
            timeout_ms=timeout_ms,
            require_visible=require_visible,
            frames=billing_frames,
        )

    def _fill_page(
        selectors: list[str],
        value: str,
        label: str,
        optional: bool = False,
        screenshot_stage: str = "",
        placeholders: list[str] | None = None,
        labels: list[str] | None = None,
    ):
        if label == "账单邮编" and _looks_like_phone_number(str(value or "")):
            return False, f"{label} 值疑似手机号，已阻止误填: {value}", None
        locator = _resolve_field_locator(selectors, placeholders=placeholders, labels=labels, timeout_ms=3000)
        if not locator:
            if optional:
                logger.info("[gopay_executor] 页面未找到可选字段 %s", label)
                return True, "", None
            if screenshot_stage:
                _capture_screenshot(api, session_id, screenshot_stage, screenshot_paths)
            return False, f"未找到 {label}", None
        _scroll_locator_into_view(locator, label)
        try:
            current = str(locator.input_value(timeout=1000) or "").strip()
        except Exception:
            current = ""
        if current == str(value or "").strip():
            logger.info("[gopay_executor] 页面 %s 已有目标值，跳过填写", label)
            return True, "", locator
        logger.info("[gopay_executor] 页面准备填写 %s，当前值=%r，新值=%r", label, current, value)
        try:
            locator.fill(str(value or ""), timeout=4000)
            actual = _read_locator_value(locator)
            if value and not _value_matches(str(value), actual):
                logger.info("[gopay_executor] 页面 fill 写入 %s 后暂未读回目标值，实际=%r，尝试原生重写", label, actual)
                if _set_locator_value(locator, str(value or "")):
                    time.sleep(0.2)
                    actual = _read_locator_value(locator)
                if value and not _value_matches(str(value), actual):
                    if screenshot_stage:
                        _capture_screenshot(api, session_id, screenshot_stage, screenshot_paths)
                    return False, f"填写 {label} 后校验失败: 期望={value!r}, 实际={actual!r}", locator
            return True, "", locator
        except Exception as exc:
            logger.info("[gopay_executor] 页面 fill %s 失败，尝试原生写入: %s", label, exc)
            if _set_locator_value(locator, str(value or "")):
                time.sleep(0.2)
                actual = _read_locator_value(locator)
                if not value or _value_matches(str(value), actual):
                    return True, "", locator
            if screenshot_stage:
                _capture_screenshot(api, session_id, screenshot_stage, screenshot_paths)
            return False, f"填写 {label} 失败: {exc}", locator

    def _select_page(
        selectors: list[str],
        value: str,
        label: str,
        optional: bool = False,
        screenshot_stage: str = "",
        placeholders: list[str] | None = None,
        labels: list[str] | None = None,
    ):
        locator = _resolve_field_locator(selectors, placeholders=placeholders, labels=labels, timeout_ms=3000)
        if not locator:
            if optional:
                logger.info("[gopay_executor] 页面未找到可选字段 %s", label)
                return True, "", None
            if screenshot_stage:
                _capture_screenshot(api, session_id, screenshot_stage, screenshot_paths)
            return False, f"未找到 {label}", None
        _scroll_locator_into_view(locator, label)
        logger.info("[gopay_executor] 页面准备选择 %s，新值=%r", label, value)
        try:
            locator.select_option(value=str(value or ""), timeout=4000)
            actual = _read_locator_value(locator)
            logger.info("[gopay_executor] 页面已选择 %s，当前值=%r", label, actual)
            return True, "", locator
        except Exception:
            try:
                locator.select_option(label=str(value or ""), timeout=4000)
                actual = _read_locator_value(locator)
                logger.info("[gopay_executor] 页面已选择 %s，当前值=%r", label, actual)
                return True, "", locator
            except Exception:
                try:
                    locator.click(timeout=1500)
                    api.page.keyboard.type(str(value or ""), delay=30)
                    api.page.keyboard.press("Enter")
                    return True, "", locator
                except Exception as exc:
                    if optional:
                        logger.info("[gopay_executor] 页面跳过可选选择字段 %s: %s", label, exc)
                        return True, "", locator
                    if screenshot_stage:
                        _capture_screenshot(api, session_id, screenshot_stage, screenshot_paths)
                    return False, f"选择 {label} 失败: {exc}", locator

    def _final_check_field(key: str, label: str, expected: str, screenshot_stage: str):
        locator = field_locators.get(key)
        if not locator:
            _capture_screenshot(api, session_id, screenshot_stage, screenshot_paths)
            return False, f"提交前校验失败，缺少 {label} 定位器"
        actual = _read_locator_value(locator)
        if _value_matches(expected, actual):
            logger.info("[gopay_executor] 提交前校验通过 %s=%r", label, actual)
            return True, ""
        logger.info("[gopay_executor] 提交前发现 %s 被改写，实际=%r，重写为=%r", label, actual, expected)
        try:
            locator.fill(expected, timeout=2500)
        except Exception:
            _set_locator_value(locator, expected)
        _dismiss_address_autocomplete(api, field_locators.get("address1"))
        time.sleep(0.3)
        actual = _read_locator_value(locator)
        if not _value_matches(expected, actual):
            _capture_screenshot(api, session_id, screenshot_stage, screenshot_paths)
            return False, f"提交前校验失败 {label}: 期望={expected!r}, 实际={actual!r}"
        logger.info("[gopay_executor] 提交前重写成功 %s=%r", label, actual)
        return True, ""

    def _verify_billing_stable_before_submit():
        _suppress_address_autocomplete_ui(api)
        _dismiss_address_autocomplete(api, field_locators.get("address1"))
        time.sleep(1.0)
        checks = [
            ("name", "账单姓名", str(billing.get("name") or ""), "gopay-billing-name-final-failed"),
            ("address1", "账单地址1", str(billing.get("address1") or ""), "gopay-billing-address1-final-failed"),
            ("city", "账单城市", str(billing.get("city") or ""), "gopay-billing-city-final-failed"),
            ("state", "账单州/省", str(billing.get("state") or ""), "gopay-billing-state-final-failed"),
            ("zip", "账单邮编", str(billing.get("zip") or ""), "gopay-billing-zip-final-failed"),
        ]
        for key, label, expected, screenshot_stage in checks:
            if not expected:
                continue
            ok, error = _final_check_field(key, label, expected, screenshot_stage)
            if not ok:
                return False, error
        return True, ""

    ok, error, locator = _fill_page(
        CN_BILLING_NAME_SELECTORS + FRAME_BILLING_NAME_SELECTORS,
        billing.get("name") or "",
        "账单姓名",
        screenshot_stage="gopay-billing-name-failed",
        placeholders=BILLING_NAME_PLACEHOLDERS,
        labels=BILLING_NAME_LABELS,
    )
    if not ok:
        return False, error
    field_locators["name"] = locator
    ok, error, locator = _select_page(
        CN_BILLING_COUNTRY_SELECTORS + FRAME_BILLING_COUNTRY_SELECTORS,
        billing.get("country") or "US",
        "账单国家",
        optional=True,
        screenshot_stage="gopay-billing-country-failed",
        labels=BILLING_COUNTRY_LABELS,
    )
    if not ok:
        logger.info("[gopay_executor] 页面跳过国家自动填写: %s", error)
    if locator:
        field_locators["country"] = locator
    ok, error, address1_locator = _fill_page(
        CN_BILLING_ADDRESS1_SELECTORS + FRAME_BILLING_ADDRESS1_SELECTORS,
        billing.get("address1") or "",
        "账单地址1",
        screenshot_stage="gopay-billing-address1-failed",
        placeholders=BILLING_ADDRESS1_PLACEHOLDERS,
        labels=BILLING_ADDRESS1_LABELS,
    )
    if not ok:
        return False, error
    field_locators["address1"] = address1_locator
    _dismiss_address_autocomplete(api, address1_locator)
    logger.info("[gopay_executor] 开始手动填写城市/州/邮编")
    if str(billing.get("address2") or "").strip():
        ok, error, locator = _fill_page(
            CN_BILLING_ADDRESS2_SELECTORS + FRAME_BILLING_ADDRESS2_SELECTORS,
            billing.get("address2") or "",
            "账单地址2",
            optional=True,
            screenshot_stage="gopay-billing-address2-failed",
            placeholders=BILLING_ADDRESS2_PLACEHOLDERS,
            labels=BILLING_ADDRESS2_LABELS,
        )
        if not ok:
            logger.info("[gopay_executor] 页面跳过地址2自动填写: %s", error)
        elif locator:
            field_locators["address2"] = locator
    ok, error, locator = _fill_page(
        CN_BILLING_CITY_SELECTORS + FRAME_BILLING_CITY_SELECTORS,
        billing.get("city") or "",
        "账单城市",
        screenshot_stage="gopay-billing-city-failed",
        placeholders=BILLING_CITY_PLACEHOLDERS,
        labels=BILLING_CITY_LABELS,
    )
    if not ok:
        return False, error
    field_locators["city"] = locator
    ok, error, locator = _select_page(
        CN_BILLING_STATE_SELECTORS + FRAME_BILLING_STATE_SELECTORS,
        billing.get("state") or "",
        "账单州/省",
        screenshot_stage="gopay-billing-state-failed",
        placeholders=BILLING_STATE_PLACEHOLDERS,
        labels=BILLING_STATE_LABELS,
    )
    if not ok:
        ok, error, locator = _fill_page(
            CN_BILLING_STATE_SELECTORS + FRAME_BILLING_STATE_SELECTORS,
            billing.get("state") or "",
            "账单州/省",
            screenshot_stage="gopay-billing-state-failed",
            placeholders=BILLING_STATE_PLACEHOLDERS,
            labels=BILLING_STATE_LABELS,
        )
        if not ok:
            return False, error
    field_locators["state"] = locator
    ok, error, locator = _fill_page(
        CN_BILLING_ZIP_SELECTORS + FRAME_BILLING_ZIP_SELECTORS,
        billing.get("zip") or "",
        "账单邮编",
        screenshot_stage="gopay-billing-zip-failed",
        placeholders=BILLING_ZIP_PLACEHOLDERS,
        labels=BILLING_ZIP_LABELS,
    )
    if not ok:
        return False, error
    field_locators["zip"] = locator
    ok, error = _verify_billing_stable_before_submit()
    if not ok:
        return False, error
    return True, ""


def _extract_sms_code(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""

    def code_from_value(value: Any) -> str:
        matched = re.fullmatch(r"\D*(\d{4,8})\D*", str(value or "").strip())
        return matched.group(1) if matched else ""

    def code_from_text(value: Any) -> str:
        matched = re.search(r"(?<!\d)(\d{4,8})(?!\d)", str(value or ""))
        return matched.group(1) if matched else ""

    try:
        payload = json.loads(raw)
    except Exception:
        payload = None

    if isinstance(payload, dict):
        data = payload.get("data")
        candidates: list[Any] = []
        if isinstance(data, dict):
            for key in ("code", "otp", "sms_code", "verification_code", "verify_code"):
                candidates.append(data.get(key))
            for key in ("content", "message", "msg", "text", "sms"):
                candidates.append(data.get(key))
        elif isinstance(data, list):
            for item in reversed(data):
                if isinstance(item, dict):
                    for key in ("code", "otp", "sms_code", "verification_code", "verify_code"):
                        candidates.append(item.get(key))
                    for key in ("content", "message", "msg", "text", "sms"):
                        candidates.append(item.get(key))
                else:
                    candidates.append(item)
        for candidate in candidates:
            code = code_from_value(candidate) or code_from_text(candidate)
            if code:
                return code
        return ""

    if isinstance(payload, list):
        for item in reversed(payload):
            code = _extract_sms_code(json.dumps(item, ensure_ascii=False) if isinstance(item, (dict, list)) else str(item))
            if code:
                return code
        return ""

    matched = re.search(r"(?<!\d)(\d{4,8})(?!\d)", raw)
    return matched.group(1) if matched else ""


def _fetch_sms_code(sms_url: str) -> str:
    resp = requests.get(
        sms_url,
        timeout=20,
        verify=False,
        headers={
            "User-Agent": "Mozilla/5.0 AutoTeam/1.0",
            "Accept": "text/plain, text/html, */*",
        },
    )
    text = (resp.text or "").strip()
    if not resp.ok:
        raise RuntimeError(text[:200] or f"接码接口返回异常({resp.status_code})")
    code = _extract_sms_code(text)
    if not code:
        raise RuntimeError("接码接口暂无验证码")
    return code


def _wait_for_text(api: ChatGPTTeamAPI, keywords: list[str], timeout_seconds: int = 30):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            body = api.page.locator("body").inner_text(timeout=1500)
        except Exception:
            body = ""
        haystack = body.lower()
        if any(keyword.lower() in haystack for keyword in keywords):
            return True
        time.sleep(1)
    return False


def _body_excerpt(api: ChatGPTTeamAPI, limit: int = 1600):
    try:
        return api.page.locator("body").inner_text(timeout=1500)[:limit]
    except Exception:
        return ""


def _is_checkout_page(api: ChatGPTTeamAPI) -> bool:
    try:
        url = str(getattr(api.page, "url", "") or "").lower()
        if "/checkout/" in url or "payments" in url:
            return True
        body = _body_excerpt(api, 1200).lower()
        hints = (
            "gopay",
            "payment method",
            "pay now",
            "billing address",
            "subscribe",
            "bayar",
            "otp",
        )
        return any(hint in body for hint in hints)
    except Exception:
        return False




def _open_checkout_in_page(api: ChatGPTTeamAPI, checkout_url: str):
    try:
        checkout_page = api.context.new_page()
        checkout_page.goto(checkout_url, wait_until="domcontentloaded", timeout=60000)
        api.page = checkout_page
    except Exception:
        try:
            api.page.goto(checkout_url, wait_until="domcontentloaded", timeout=60000)
        except Exception:
            return False

    deadline = time.time() + 20
    while time.time() < deadline:
        current_url = str(getattr(api.page, "url", "") or "")
        if checkout_url in current_url or _is_checkout_page(api):
            return True
        time.sleep(1)
    return False


def _select_gopay_option(api: ChatGPTTeamAPI):
    selectors = [
        'text=/gopay/i',
        'button:has-text("GoPay")',
        'label:has-text("GoPay")',
        '[data-testid*="gopay" i]',
        '[value*="gopay" i]',
        'input[value*="gopay" i]',
        'input[name*="payment" i]',
        '[role="radio"]:has-text("GoPay")',
        '[role="button"]:has-text("GoPay")',
        'img[alt*="gopay" i]',
    ]
    for selector in selectors:
        locator = _visible_locator(api, [selector], timeout_ms=2500)
        if not locator:
            continue
        try:
            locator.click(timeout=4000)
            return True, ""
        except Exception:
            continue

    script = """() => {
      const nodes = Array.from(document.querySelectorAll('button,label,div,span,input,[role="button"],[role="radio"]'));
      for (const node of nodes) {
        const text = (node.innerText || node.textContent || node.value || '').trim();
        if (/gopay/i.test(text) || /gopay/i.test(node.getAttribute?.('aria-label') || '') || /gopay/i.test(node.getAttribute?.('value') || '')) {
          node.click();
          return true;
        }
      }
      return false;
    }"""
    try:
        clicked = bool(api.page.evaluate(script))
        if clicked:
            return True, ""
    except Exception:
        pass

    return False, "未找到 GoPay 选项"


def _sync_latest_page(api: ChatGPTTeamAPI):
    try:
        pages = list(getattr(api.context, "pages", []) or [])
        if not pages:
            return
        current_url = str(getattr(getattr(api, "page", None), "url", "") or "")
        if "/checkout/" in current_url:
            return
        for page in reversed(pages):
            url = str(getattr(page, "url", "") or "")
            if "/checkout/" in url and "chatgpt.com" in url:
                api.page = page
                logger.info("[gopay_executor] 切回 checkout 页面: %s", url)
                return
        api.page = pages[-1]
    except Exception:
        pass


def _phone_page_ready(api: ChatGPTTeamAPI) -> bool:
    _sync_latest_page(api)
    frames = _iter_page_frames(api)
    for frame in frames:
        for selector in PHONE_PAGE_SELECTORS:
            try:
                locator = frame.locator(selector).first
                locator.wait_for(state="visible", timeout=120)
                placeholder = str(locator.get_attribute("placeholder", timeout=120) or "").strip()
                logger.info("[gopay_executor] 已进入手机号页面，命中输入框 placeholder=%r", placeholder)
                return True
            except Exception:
                continue
    for frame in frames:
        for text in PHONE_PAGE_PLACEHOLDERS:
            try:
                locator = frame.get_by_placeholder(text, exact=True).first
                locator.wait_for(state="visible", timeout=120)
                logger.info("[gopay_executor] 已进入手机号页面，命中手机号占位符=%r", text)
                return True
            except Exception:
                continue
        for text in PHONE_PAGE_LABELS:
            try:
                locator = frame.get_by_label(text, exact=True).first
                locator.wait_for(state="visible", timeout=120)
                logger.info("[gopay_executor] 已进入手机号页面，命中手机号 label=%r", text)
                return True
            except Exception:
                continue
    body = _body_excerpt(api, 1600).lower()
    has_phone_hints = any(hint in body for hint in ("nomor handphone", "phone number", "nomor telepon", "whatsapp", "otp"))
    still_on_billing = any(hint in body for hint in ("账单地址", "billing address", "全名", "地址第 1 行", "address line 1"))
    if has_phone_hints and not still_on_billing:
        logger.info("[gopay_executor] 已进入手机号页面，依据页面文本命中")
        return True
    return False


def _compact_checkout_error(text: str) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean:
        return ""
    for phrase in ("付款未获批准", "出了错，请重试。", "出错了，请重试。", "请重试。"):
        if phrase in clean:
            return phrase
    english_patterns = (
        r"payment\s+(?:was\s+)?not\s+approved",
        r"payment\s+(?:was\s+)?declined",
        r"something went wrong",
        r"please try again",
        r"try again",
        r"unable to process[^.。]*",
    )
    for pattern in english_patterns:
        matched = re.search(pattern, clean, flags=re.IGNORECASE)
        if matched:
            return matched.group(0).strip()
    return clean[:500]


def _extract_checkout_error(api: ChatGPTTeamAPI) -> str:
    script = """() => {
      const isVisible = (node) => {
        if (!node || !node.getBoundingClientRect) return false;
        const style = window.getComputedStyle(node);
        if (!style || style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) return false;
        const rect = node.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      };
      const nodes = Array.from(document.querySelectorAll('[role="alert"],[aria-live],div,span,p'));
      return nodes
        .filter(isVisible)
        .map((node) => (node.innerText || node.textContent || '').replace(/\\s+/g, ' ').trim())
        .filter(Boolean)
        .slice(0, 300);
    }"""
    try:
        candidates = api.page.evaluate(script) or []
    except Exception:
        candidates = []
    matched_errors = []
    for text in candidates:
        clean = str(text or "").strip()
        if not clean:
            continue
        if any(pattern.search(clean) for pattern in CHECKOUT_ERROR_PATTERNS):
            matched_errors.append(_compact_checkout_error(clean))
    if matched_errors:
        return sorted(matched_errors, key=len)[0]

    body = _body_excerpt(api, 2000)
    matched_errors = []
    for line in re.split(r"[\r\n]+", body):
        clean = re.sub(r"\s+", " ", line).strip()
        if clean and any(pattern.search(clean) for pattern in CHECKOUT_ERROR_PATTERNS):
            matched_errors.append(_compact_checkout_error(clean))
    if matched_errors:
        return sorted(matched_errors, key=len)[0]
    return ""


def _wait_for_phone_page_or_checkout_error(
    api: ChatGPTTeamAPI,
    timeout_seconds: int = 20,
    previous_error: str = "",
    stale_error_grace_seconds: int = 35,
) -> tuple[bool, str]:
    started_at = time.time()
    deadline = time.time() + timeout_seconds
    last_error = ""
    while time.time() < deadline:
        if _phone_page_ready(api):
            return True, ""
        error = _extract_checkout_error(api)
        if error:
            last_error = error
            if error != previous_error or time.time() - started_at >= stale_error_grace_seconds:
                return False, error
        time.sleep(0.5)
    return False, last_error


def _submit_checkout_with_retries(
    api: ChatGPTTeamAPI,
    session_id: str,
    screenshot_paths: list[str],
    progress,
    max_attempts: int = 3,
) -> tuple[bool, str]:
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        previous_error = _extract_checkout_error(api)
        progress("submit_checkout", attempt=attempt, max_attempts=max_attempts)
        logger.info("[gopay_executor] 点击订阅，attempt=%s/%s", attempt, max_attempts)
        ok, error = _click(
            api,
            [
                'button:has-text("Subscribe")',
                'button:has-text("Pay")',
                'button:has-text("订阅")',
                'button[type="submit"]',
            ],
            "提交订阅按钮",
            timeout_ms=10000,
        )
        if not ok:
            _capture_screenshot(api, session_id, f"gopay-submit-attempt-{attempt}-click-failed", screenshot_paths)
            return False, error
        progress("submit_clicked", attempt=attempt, max_attempts=max_attempts)

        progress("wait_phone_step", attempt=attempt, max_attempts=max_attempts)
        reached_phone_page, checkout_error = _wait_for_phone_page_or_checkout_error(
            api,
            timeout_seconds=60,
            previous_error=previous_error,
        )
        if reached_phone_page:
            return True, ""

        last_error = checkout_error or "点击订阅后未跳转到手机号页面"
        logger.info("[gopay_executor] 第 %s/%s 次订阅提交失败: %s", attempt, max_attempts, last_error)
        _capture_screenshot(api, session_id, f"gopay-submit-attempt-{attempt}-failed", screenshot_paths)
        if attempt < max_attempts:
            progress("submit_retry", attempt=attempt + 1, max_attempts=max_attempts, reason=last_error)
            time.sleep(1.5)

    return False, f"点击订阅重试 {max_attempts} 次后仍失败: {last_error or '未进入手机号页面'}"


def _generate_id_checkout_in_page(api: ChatGPTTeamAPI, access_token: str):
    script = """async (args) => {
      const accessToken = (args && args.accessToken) || "";
      if (!accessToken) {
        return { ok: false, detail: "缺少 accessToken" };
      }
      const fetchWithTimeout = async (url, init = {}, timeoutMs = 12000) => {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeoutMs);
        try {
          return await fetch(url, { ...init, signal: controller.signal });
        } finally {
          clearTimeout(timer);
        }
      };
      const timezoneOffset = new Date().getTimezoneOffset();
      const warmups = [
        ["/api/auth/session", { method: "GET" }],
        [`/backend-api/accounts/check/v4-2023-04-27?timezone_offset_min=${timezoneOffset}`, { method: "GET" }],
        ["/backend-api/accounts/domain-density-eligibility", { method: "GET" }],
        ["/backend-api/checkout_pricing_config/countries", { method: "GET" }],
        ["/backend-api/checkout_pricing_config/configs/ID", { method: "GET" }]
      ];
      for (const [url, init] of warmups) {
        try {
          await fetchWithTimeout(url, {
            ...init,
            credentials: "include",
            headers: {
              Authorization: "Bearer " + accessToken,
              Accept: "application/json",
              "x-openai-target-path": url.split("?")[0],
              "x-openai-target-route": url.split("?")[0]
            }
          }, 8000);
        } catch (_) {}
      }
      try {
        await fetchWithTimeout("/backend-api/sentinel/ping", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: "{}"
        }, 8000);
      } catch (_) {}
      const payload = args.payload;
      const attempts = [
        {
          label: "basic",
          headers: {
            Authorization: "Bearer " + accessToken,
            "Content-Type": "application/json",
          }
        },
        {
          label: "target",
          headers: {
            Authorization: "Bearer " + accessToken,
            "Content-Type": "application/json",
            Accept: "*/*",
            "oai-language": navigator.language || "en-US",
            "oai-session-id": crypto.randomUUID ? crypto.randomUUID() : String(Date.now()),
            "x-openai-target-path": "/backend-api/payments/checkout",
            "x-openai-target-route": "/backend-api/payments/checkout"
          }
        }
      ];
      let last = { ok: false, status: 0, detail: "未执行 checkout 请求", raw: {} };
      for (const attempt of attempts) {
        let resp;
        try {
          resp = await fetchWithTimeout("https://chatgpt.com/backend-api/payments/checkout", {
            method: "POST",
            credentials: "include",
            headers: attempt.headers,
            body: JSON.stringify(payload),
          }, 20000);
        } catch (e) {
          last = { ok: false, status: 0, detail: String(e && e.message ? e.message : e), raw: {}, attempt: attempt.label };
          continue;
        }
        const text = await resp.text();
        let data = {};
        try {
          data = text ? JSON.parse(text) : {};
        } catch (_) {
          data = { raw: text.slice(0, 500) };
        }
        if (resp.ok) {
          const checkoutSessionId = data.checkout_session_id || "";
          const processorEntity = data.processor_entity || "openai_llc";
          const url = data.url || (checkoutSessionId ? `https://chatgpt.com/checkout/${processorEntity}/${checkoutSessionId}` : "");
          return { ok: Boolean(url), status: resp.status, url, raw: data, detail: url ? "" : "生成 checkout 返回缺少 url", attempt: attempt.label };
        }
        last = { ok: false, status: resp.status, detail: data.detail || data.error || `HTTP ${resp.status}`, raw: data, attempt: attempt.label };
        if (resp.status !== 403) {
          break;
        }
      }
      return last;
    }"""
    result = api.page.evaluate(
        script,
        {
            "accessToken": access_token,
            "payload": _chatgpt_checkout_payload(),
        },
    )
    if not result.get("ok"):
        detail = result.get("detail") or "生成印尼区支付链接失败"
        status = result.get("status")
        if status:
            raise RuntimeError(f"{detail}: HTTP {status}")
        raise RuntimeError(detail)
    return {
        "url": str(result.get("url") or "").strip(),
        "raw": result.get("raw") or {},
    }


def _open_id_checkout_via_page_script(api: ChatGPTTeamAPI, access_token: str):
    script = """async (args) => {
      try {
        const accessToken = (args && args.accessToken) || "";
        const s = await (await fetch("/api/auth/session")).json();
        const token = (s && s.accessToken) || accessToken || "";
        if (!token) {
          return { ok: false, detail: "请先登录 ChatGPT！" };
        }
        const payload = {
          entry_point: "all_plans_pricing_modal",
          plan_name: "chatgptplusplan",
          billing_details: { country: "ID", currency: "IDR" },
          promo_campaign: {
            promo_campaign_id: "plus-1-month-free",
            is_coupon_from_query_param: false
          },
          checkout_ui_mode: "custom"
        };
        const resp = await fetch("https://chatgpt.com/backend-api/payments/checkout", {
          method: "POST",
          headers: {
            Authorization: "Bearer " + token,
            "Content-Type": "application/json"
          },
          body: JSON.stringify(payload)
        });
        const data = await resp.json();
        if (data && data.checkout_session_id) {
          const url = "https://chatgpt.com/checkout/openai_llc/" + data.checkout_session_id;
          window.location.href = url;
          return { ok: true, url, raw: data };
        }
        return { ok: false, detail: data.detail || JSON.stringify(data), raw: data };
      } catch (e) {
        return { ok: false, detail: String(e && e.message ? e.message : e) };
      }
    }"""
    result = api.page.evaluate(
        script,
        {
            "accessToken": access_token,
        },
    )
    if not result.get("ok"):
        raise RuntimeError(result.get("detail") or "页面内生成并跳转 checkout 失败")
    return {
        "url": str(result.get("url") or "").strip(),
        "raw": result.get("raw") or {},
    }


def _run_gopay_bind_task_once(
    *,
    email: str,
    checkout_url: str,
    phone_number: str,
    sms_url: str,
    gopay_pin: str,
    billing_info: dict | None = None,
    country_code: str = "",
    proxy_url: str | None = None,
    proxy_bypass: str | None = None,
    timeout_seconds: int = 900,
    is_cancelled=None,
    progress_callback=None,
):
    """Run GoPay payment with HTTP tokenization instead of checkout UI automation.

    The default path mirrors the reference project: a single ChatGPT HTTP
    session creates checkout, approves it, then verifies after GoPay settles.
    Browser login is only a fallback when the saved auth session lacks tokens.
    """

    api = ChatGPTTeamAPI()
    session_id = uuid.uuid4().hex[:12]
    screenshot_paths: list[str] = []
    final_checkout_url = str(checkout_url or "").strip()
    auth_session = load_auth_session(email)
    session_token = str(auth_session.get("sessionToken") or auth_session.get("session_token") or "").strip()
    access_token = str(auth_session.get("accessToken") or auth_session.get("access_token") or "").strip()
    generated_checkout_meta: dict = {}

    def progress(stage: str, **extra):
        if callable(progress_callback):
            payload = {"stage": stage}
            payload.update(extra)
            progress_callback(payload)

    def cancelled():
        return callable(is_cancelled) and is_cancelled()

    billing = dict(billing_info or {})
    if not all(
        str(billing.get(key) or "").strip()
        for key in ("name", "country", "state", "city", "zip", "address1")
    ):
        billing = _fetch_random_billing_address()
        progress("billing_address_generated", billing_city=billing.get("city", ""), billing_state=billing.get("state", ""))
    public_billing_info = _public_billing_info(billing)
    logger.info("[gopay_executor] 本次账单地址: %s", public_billing_info)
    progress("billing_info_ready", billing_info=public_billing_info)

    try:
        account_info = auth_session.get("account") if isinstance(auth_session.get("account"), dict) else {}
        account_id = str(account_info.get("id") or "").strip()
        device_id = str(
            auth_session.get("device_id")
            or auth_session.get("oai_device_id")
            or auth_session.get("oaiDeviceId")
            or ""
        ).strip() or str(uuid.uuid4())
        token_source = "auth_session"

        if not access_token or not session_token:
            progress("open_chatgpt", email=email)
            api._launch_browser(proxy_url=proxy_url, proxy_bypass=proxy_bypass)
            api.page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=60000)
            api._wait_for_cloudflare()
            if session_token and account_id:
                api.account_id = account_id
                logger.info("[gopay_executor] 使用 session 注入模式启动浏览器，不执行 workspace 自动检测")
                api._inject_session(session_token)
            token_source = api._fetch_access_token(allow_bearer_file=False)
            if not access_token:
                access_token = str(getattr(api, "access_token", "") or "").strip()
            if not device_id:
                device_id = str(getattr(api, "oai_device_id", "") or "").strip() or str(uuid.uuid4())
            _capture_screenshot(api, session_id, "gopay-home", screenshot_paths)

        if cancelled():
            return _build_result("failed", failure_stage="generate_checkout", message="任务已取消", screenshot_paths=screenshot_paths, billing_info=public_billing_info)
        if not access_token:
            return _build_result(
                "failed",
                failure_stage="generate_checkout",
                message=f"对应 auth_session 缺少 accessToken，且浏览器会话未能刷新 accessToken (source={token_source})",
                screenshot_paths=screenshot_paths,
                billing_info=public_billing_info,
            )
        if not session_token and not str(auth_session.get("cookie_header") or "").strip():
            return _build_result(
                "failed",
                failure_stage="generate_checkout",
                message="对应 auth_session 缺少 sessionToken/cookie_header，无法构造参考项目的 ChatGPT HTTP 会话",
                screenshot_paths=screenshot_paths,
                billing_info=public_billing_info,
            )

        cookie_header = _chatgpt_reference_cookie_header(
            session_token=session_token,
            account_id=account_id,
            device_id=device_id,
            cookie_header=str(auth_session.get("cookie_header") or "").strip(),
        )
        chatgpt_http = _build_chatgpt_http_session(
            access_token=access_token,
            session_token=session_token,
            cookie_header=cookie_header,
            account_id=account_id,
            device_id=device_id,
            user_agent=str(auth_session.get("user_agent") or auth_session.get("userAgent") or "").strip(),
            proxy_url=proxy_url,
        )
        progress("chatgpt_http_session_ready")

        direct_redirect_mode = _looks_like_pm_redirect_url(final_checkout_url)
        if direct_redirect_mode:
            progress("checkout_ready", checkout_url=final_checkout_url, mode="redirect")
            raw_checkout = {}
        elif not final_checkout_url:
            progress("generate_checkout")
            try:
                generated_checkout_meta = _generate_id_checkout_http(
                    chatgpt_http,
                    access_token=access_token,
                    session_token=session_token,
                    cookie_header=cookie_header,
                    account_id=account_id,
                    device_id=device_id,
                    user_agent=str(auth_session.get("user_agent") or auth_session.get("userAgent") or "").strip(),
                )
                cookie_header = str(getattr(chatgpt_http, "_chatgpt_cookie_header", "") or cookie_header)
            except Exception as exc:
                raise GoPayFlowError(f"生成印尼区支付链接失败: {exc}", stage="generate_checkout") from exc
            final_checkout_url = str(generated_checkout_meta.get("url") or "").strip()
            progress("checkout_ready", checkout_url=final_checkout_url)
            logger.info("[gopay_executor] 已生成 GoPay checkout session: %s", final_checkout_url)
            raw_checkout = generated_checkout_meta.get("raw") if isinstance(generated_checkout_meta.get("raw"), dict) else {}
        else:
            progress("checkout_ready", checkout_url=final_checkout_url)
            raw_checkout = {}

        checkout_session_id = _extract_checkout_session_id(final_checkout_url, raw_checkout)
        if not checkout_session_id and not direct_redirect_mode:
            return _build_result(
                "failed",
                failure_stage="generate_checkout",
                message=f"无法从 checkout 响应或 URL 提取 checkout_session_id: {final_checkout_url}",
                screenshot_paths=screenshot_paths,
                checkout_url=final_checkout_url,
                billing_info=public_billing_info,
            )
        processor_entity = _extract_processor_entity(raw_checkout)
        stripe_pk = (
            os.environ.get("GOPAY_STRIPE_PUBLISHABLE_KEY")
            or str(raw_checkout.get("publishable_key") or "")
            or DEFAULT_STRIPE_PK
        )
        midtrans_client_id = os.environ.get("GOPAY_MIDTRANS_CLIENT_ID", "")

        def approve_callback(cs_id: str) -> dict:
            return _approve_checkout_http(
                chatgpt_http,
                access_token=access_token,
                checkout_session_id=cs_id,
                processor_entity=processor_entity,
                cookie_header=cookie_header,
                account_id=account_id,
                device_id=device_id,
            )

        def verify_callback(cs_id: str) -> dict:
            return _verify_checkout_http(
                chatgpt_http,
                access_token=access_token,
                checkout_session_id=cs_id,
                processor_entity=processor_entity,
                cookie_header=cookie_header,
                account_id=account_id,
                device_id=device_id,
            )

        otp_provider = _poll_otp_from_sms_url(
            sms_url,
            timeout_seconds=max(90, min(int(timeout_seconds or 900), 600)),
            initial_delay_seconds=0,
            is_cancelled=is_cancelled,
            progress=progress,
        )

        def trigger_sms_otp(reference_id: str, activation_link_url: str):
            _trigger_sms_otp_in_page(
                api,
                activation_link_url=activation_link_url,
                proxy_url=proxy_url,
                proxy_bypass=proxy_bypass,
                is_cancelled=is_cancelled,
                progress=progress,
            )

        charger = GoPayHttpCharger(
            http=_new_http_session(proxy_url),
            phone_number=phone_number,
            country_code=country_code,
            gopay_pin=gopay_pin,
            otp_provider=otp_provider,
            billing_info=billing,
            stripe_runtime=_stripe_runtime_from_env(),
            midtrans_client_id=midtrans_client_id,
            approve_callback=approve_callback,
            verify_callback=verify_callback,
            sms_otp_trigger_callback=trigger_sms_otp,
            is_cancelled=is_cancelled,
            progress_callback=progress_callback,
        )

        progress("gopay_http_flow", checkout_session_id=checkout_session_id)
        if direct_redirect_mode:
            flow_result = charger.run_from_redirect(
                redirect_url=final_checkout_url,
                checkout_session_id=checkout_session_id,
            )
        else:
            flow_result = charger.run(checkout_session_id=checkout_session_id, stripe_pk=stripe_pk)

        if flow_result.get("state") == "succeeded":
            progress("completed")
            result = _build_result(
                "success",
                message="GoPay 支付成功",
                screenshot_paths=screenshot_paths,
                checkout_url=final_checkout_url,
                billing_info=public_billing_info,
            )
        else:
            progress("failed", failure_stage="chatgpt_verify")
            result = _build_result(
                "needs_review",
                failure_stage="chatgpt_verify",
                message="GoPay 扣款已完成，但 ChatGPT verify 未确认成功",
                screenshot_paths=screenshot_paths,
                checkout_url=final_checkout_url,
                billing_info=public_billing_info,
            )
        result.update(
            {
                "session_id": checkout_session_id,
                "processor_entity": processor_entity,
                "snap_token": flow_result.get("snap_token", ""),
                "charge_ref": flow_result.get("charge_ref", ""),
                "reference_id": flow_result.get("reference_id", ""),
                "flow": "gopay_http",
            }
        )
        return result
    except GoPayPINRejected as exc:
        logger.exception("[gopay_executor] GoPay PIN rejected")
        return _build_result(
            "failed",
            failure_stage=exc.stage or "fill_pin",
            message=str(exc),
            screenshot_paths=screenshot_paths,
            checkout_url=final_checkout_url,
            billing_info=public_billing_info,
        )
    except GoPayOTPCancelled as exc:
        logger.exception("[gopay_executor] GoPay OTP cancelled")
        return _build_result(
            "failed",
            failure_stage=exc.stage or "fetch_otp",
            message=str(exc),
            screenshot_paths=screenshot_paths,
            checkout_url=final_checkout_url,
            billing_info=public_billing_info,
        )
    except GoPayFlowError as exc:
        logger.exception("[gopay_executor] GoPay HTTP flow failed")
        return _build_result(
            "failed",
            failure_stage=exc.stage or "gopay_http",
            message=str(exc),
            screenshot_paths=screenshot_paths,
            checkout_url=final_checkout_url,
            billing_info=public_billing_info,
        )
    except Exception as exc:
        logger.exception("[gopay_executor] unexpected error")
        _capture_screenshot(api, session_id, "gopay-unexpected-error", screenshot_paths)
        return _build_result("failed", failure_stage="post_submit", message=f"执行 GoPay 任务时出现异常: {exc}", screenshot_paths=screenshot_paths, checkout_url=final_checkout_url, billing_info=public_billing_info)
    finally:
        try:
            api.stop()
        except Exception:
            pass


def run_gopay_bind_task(
    *,
    email: str,
    checkout_url: str,
    phone_number: str,
    sms_url: str,
    gopay_pin: str,
    billing_info: dict | None = None,
    country_code: str = "",
    proxy_url: str | None = None,
    proxy_bypass: str | None = None,
    timeout_seconds: int = 900,
    account_emails: list[str] | None = None,
    is_cancelled=None,
    progress_callback=None,
):
    """Run GoPay payment.

    Account rotation is only enabled for explicit batch mode: multiple
    account_emails and an auto-generated checkout.
    """

    requested_email = str(email or "").strip().lower()
    final_checkout_url = str(checkout_url or "").strip()

    def emit(stage: str, **extra):
        if callable(progress_callback):
            payload = {"stage": stage}
            payload.update(extra)
            progress_callback(payload)

    def run_once(candidate_email: str) -> dict:
        return _run_gopay_bind_task_once(
            email=candidate_email,
            checkout_url=checkout_url,
            phone_number=phone_number,
            sms_url=sms_url,
            gopay_pin=gopay_pin,
            billing_info=billing_info,
            country_code=country_code,
            proxy_url=proxy_url,
            proxy_bypass=proxy_bypass,
            timeout_seconds=timeout_seconds,
            is_cancelled=is_cancelled,
            progress_callback=progress_callback,
        )

    explicit_candidates = [
        str(candidate or "").strip().lower()
        for candidate in (account_emails or [])
        if str(candidate or "").strip()
    ]
    rotation_enabled = (
        not final_checkout_url
        and not _env_truthy("GOPAY_DISABLE_APPROVE_ROTATION")
        and len(dict.fromkeys(explicit_candidates)) > 1
    )

    if not rotation_enabled:
        result = run_once(requested_email)
        result["email_used"] = requested_email
        result["requested_email"] = requested_email
        return result

    candidates = _gopay_auth_rotation_candidates(requested_email, explicit_candidates)
    if not candidates:
        return _build_result(
            "failed",
            failure_stage="generate_checkout",
            message="没有可用 auth_session 账号",
        )

    attempted: list[str] = []
    blocked: list[str] = []
    last_blocked_result: dict | None = None
    skipped_cooldown: list[str] = []

    for index, candidate in enumerate(candidates, 1):
        if callable(is_cancelled) and is_cancelled():
            return _build_result(
                "failed",
                failure_stage="generate_checkout",
                message="任务已取消",
            )

        remaining = _approve_blocked_remaining(candidate)
        if remaining > 0:
            skipped_cooldown.append(candidate)
            emit("gopay_account_skipped_cooldown", email=candidate, remaining_seconds=remaining)
            continue

        attempted.append(candidate)
        if candidate != requested_email:
            emit("gopay_rotate_account", email=candidate, attempt=index, total=len(candidates))
        else:
            emit("gopay_try_account", email=candidate, attempt=index, total=len(candidates))

        result = run_once(candidate)
        result["email_used"] = candidate
        result["requested_email"] = requested_email
        result["attempted_emails"] = attempted[:]

        if _is_chatgpt_approve_blocked_result(result):
            cooldown = int(_mark_approve_blocked(candidate))
            blocked.append(candidate)
            last_blocked_result = result
            emit(
                "chatgpt_approve_blocked_rotate",
                email=candidate,
                cooldown_seconds=cooldown,
                attempted=len(attempted),
                remaining_candidates=max(0, len(candidates) - index),
            )
            continue

        if blocked:
            result["blocked_emails"] = blocked[:]
            result["rotated_from"] = requested_email
        return result

    if last_blocked_result:
        message = (
            "所有候选 auth_session 的 ChatGPT approve 都返回 blocked，"
            "已将这些账号加入冷却；请稍后重试或补充新的 auth_session"
        )
        if skipped_cooldown and not attempted:
            message = "所有候选 auth_session 仍在 chatgpt_approve 冷却中，请稍后重试"
        last_blocked_result = dict(last_blocked_result)
        last_blocked_result["message"] = message
        last_blocked_result["blocked_emails"] = blocked[:]
        last_blocked_result["skipped_cooldown_emails"] = skipped_cooldown[:]
        last_blocked_result["attempted_emails"] = attempted[:]
        last_blocked_result["email_used"] = attempted[-1] if attempted else requested_email
        last_blocked_result["requested_email"] = requested_email
        emit("gopay_all_accounts_blocked", attempted=len(attempted), skipped_cooldown=len(skipped_cooldown))
        return last_blocked_result

    return _build_result(
        "failed",
        failure_stage="chatgpt_approve",
        message="所有候选 auth_session 仍在 chatgpt_approve 冷却中，请稍后重试",
        billing_info=_public_billing_info(billing_info or {}),
    )
