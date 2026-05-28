"""GoPay 绑卡执行器。"""

from __future__ import annotations

import base64
import json
import logging
import os
import random
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

import requests
from urllib3.exceptions import InsecureRequestWarning

from autoteam.auth_session_store import load_auth_session
from autoteam.chatgpt_api import ChatGPTTeamAPI
from autoteam.config import normalize_proxy_url
from autoteam.paths import PROJECT_ROOT

logger = logging.getLogger(__name__)
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

SCREENSHOT_DIR = PROJECT_ROOT / "data" / "bind_screenshots"
GOPAY_NETWORK_CAPTURE_DIR = PROJECT_ROOT / "data" / "gopay_network_captures"

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
    re.compile(r"customer'?s location.*(?:not|isn'?t).*recognized", re.IGNORECASE),
    re.compile(r"valid customer address", re.IGNORECASE),
    re.compile(r"automatically calculate tax", re.IGNORECASE),
    re.compile(r"http\s*429", re.IGNORECASE),
    re.compile(r"too many requests", re.IGNORECASE),
    re.compile(r"rate limit", re.IGNORECASE),
    re.compile(r"请求.*(?:过多|频繁)"),
)

CHECKOUT_PAYMENT_NOT_APPROVED_PATTERNS = (
    re.compile(r"付款.*未获批准"),
    re.compile(r"未获批准"),
    re.compile(r"payment\s+(?:was\s+)?not\s+approved", re.IGNORECASE),
    re.compile(r"payment\s+(?:was\s+)?declined", re.IGNORECASE),
    re.compile(r"not\s+approved", re.IGNORECASE),
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
GOPAY_SMS_CHANNEL_SWITCH_DELAY_S = 30.0
GOPAY_SMS_OTP_RESEND_AFTER_S = 120.0
GOPAY_APPROVE_BLOCKED_COOLDOWN_S = 1800.0
HTTP_TIMEOUT_SECONDS = 60
TRANSIENT_HTTP_RETRY_ATTEMPTS = 2
TRANSIENT_HTTP_RETRY_SLEEP_S = 2.0
GOPAY_PIN_TOKEN_RETRY_ATTEMPTS = 5
GOPAY_PIN_TOKEN_RETRY_SLEEP_S = 5.0
TRANSIENT_RETRY_STAGES = {
    "stripe_payment_method",
    "stripe_init",
    "stripe_elements_session",
    "stripe_address_update",
    "stripe_confirm",
    "resolve_midtrans_redirect",
    "pm_redirect",
    "midtrans_load_transaction",
    "gopay_validate_reference",
    "gopay_user_consent",
    "gopay_sms_channel_switch",
    "trigger_sms_otp",
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


class GoPayOTPInvalid(GoPayFlowError):
    pass


class GoPayPINRejected(GoPayFlowError):
    pass


class GoPayChargeBlocked(GoPayFlowError):
    pass


class GoPayAlreadyLinked(GoPayFlowError):
    pass


class GoPayRateLimited(GoPayFlowError):
    pass


def _new_http_session(proxy_url: str | None = None, *, require_curl_cffi: bool = False) -> Any:
    if _CurlCffiSession is not None:
        session = _CurlCffiSession(impersonate=os.environ.get("GOPAY_TLS_IMPERSONATE", "chrome136"))
        try:
            session._autoteam_transport = "curl_cffi"  # type: ignore[attr-defined]
        except Exception:
            pass
    else:
        if require_curl_cffi:
            raise GoPayFlowError(
                "GoPay ChatGPT checkout/approve 需要 curl-cffi 的 Chrome TLS 指纹；"
                "当前环境未安装 curl_cffi，请执行 `pip install curl-cffi` 或重新安装项目依赖后重试",
                stage="chatgpt_http_session",
            )
        session = requests.Session()
        try:
            session._autoteam_transport = "requests"  # type: ignore[attr-defined]
        except Exception:
            pass
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    normalized_proxy_url = normalize_proxy_url(proxy_url)
    if normalized_proxy_url.lower().startswith("socks5://"):
        # HTTP clients should resolve target DNS through authenticated SOCKS
        # proxies. socks5:// can resolve locally and breaks some providers
        # during TLS CONNECT; socks5h:// keeps browser/protocol traffic stable.
        normalized_proxy_url = f"socks5h://{normalized_proxy_url[len('socks5://'):]}"
    if normalized_proxy_url:
        logger.info("[gopay_executor] HTTP session proxy enabled: %s", _safe_proxy_summary(normalized_proxy_url))
        try:
            session.proxies = {"http": normalized_proxy_url, "https": normalized_proxy_url}
        except Exception:
            logger.exception("[gopay_executor] HTTP session proxy assignment failed")
    return session


def _http_transport_name(http: Any) -> str:
    try:
        value = getattr(http, "_autoteam_transport", "")
        if value:
            return str(value)
    except Exception:
        pass
    module = http.__class__.__module__
    if module.startswith("curl_cffi"):
        return "curl_cffi"
    return "requests"


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
        logger.info(
            "[gopay_executor] %s returned GoPay rate-limit payload: http_status=%s body=%s",
            stage,
            getattr(resp, "status_code", "?"),
            _compact_log_text(text),
        )
        raise GoPayRateLimited(_gopay_rate_limited_message(), stage="gopay_rate_limited")
    raise GoPayFlowError(
        f"{stage} 失败: HTTP {getattr(resp, 'status_code', '?')} {(getattr(resp, 'text', '') or '')[:500]}",
        stage=stage,
    )


def _is_transient_http_error(exc: Exception) -> bool:
    if isinstance(exc, requests.RequestException):
        return True
    text = str(exc or "").lower()
    if any(
        marker in text
        for marker in (
            "curl: (6)",
            "could not resolve host",
            "couldn't resolve host",
            "name resolution",
            "temporary failure in name resolution",
            "getaddrinfo",
            "dns",
            "failed to connect",
            "connection timed out",
            "connection timeout",
            "connection reset",
            "connection refused",
        )
    ):
        return True
    module = exc.__class__.__module__
    name = exc.__class__.__name__.lower()
    return module.startswith("curl_cffi") and any(
        marker in name for marker in ("timeout", "connection", "proxy", "ssl", "requests", "dns", "resolve")
    )


def _env_truthy(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _env_enabled(name: str, default: bool = True) -> bool:
    raw = str(os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off"}


def _parse_amount(value: Any) -> int | None:
    raw = str(value if value is not None else "").strip()
    if not raw:
        return None
    try:
        return int(float(raw))
    except Exception:
        return None


def _parse_display_amount(value: Any) -> int | None:
    raw = str(value if value is not None else "").strip()
    if not raw:
        return None
    cleaned = re.sub(r"(?i)\b(?:idr|rp|usd)\b|us\$|\$", "", raw)
    cleaned = re.sub(r"[^\d,.\-+]", "", cleaned)
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        normalized = cleaned.replace(",", "")
    elif "," in cleaned:
        parts = cleaned.split(",")
        normalized = "".join(parts) if all(len(part) == 3 for part in parts[1:]) else cleaned.replace(",", ".")
    else:
        normalized = cleaned
    try:
        return int(float(normalized))
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


def _env_int(name: str, default: int) -> int:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(float(raw))
    except Exception:
        return default


def _transient_http_retry_attempts(stage: str) -> int:
    if stage not in TRANSIENT_RETRY_STAGES:
        return 1
    if stage == "gopay_tokenize_pin":
        return max(1, _env_int("GOPAY_PIN_TOKEN_RETRY_ATTEMPTS", GOPAY_PIN_TOKEN_RETRY_ATTEMPTS))
    return max(1, _env_int("GOPAY_TRANSIENT_HTTP_RETRY_ATTEMPTS", TRANSIENT_HTTP_RETRY_ATTEMPTS))


def _transient_http_retry_sleep_seconds(stage: str, attempt: int) -> float:
    if stage == "gopay_tokenize_pin":
        base = max(0.0, _env_float("GOPAY_PIN_TOKEN_RETRY_SLEEP_SECONDS", GOPAY_PIN_TOKEN_RETRY_SLEEP_S))
        return base * max(1, int(attempt or 1))
    return max(0.0, _env_float("GOPAY_TRANSIENT_HTTP_RETRY_SLEEP_SECONDS", TRANSIENT_HTTP_RETRY_SLEEP_S))


def _mask_log_value(value: Any, *, left: int = 6, right: int = 4) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if len(raw) <= left + right:
        return f"{raw[:2]}***len={len(raw)}"
    return f"{raw[:left]}...{raw[-right:]}(len={len(raw)})"


def _compact_log_text(text: Any, *, limit: int = 220) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit]}..."


def _safe_url_summary(url: Any) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
    except Exception:
        return _mask_log_value(raw)

    host = parsed.hostname or ""
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port:
        host = f"{host}:{port}"
    safe_path_segments = []
    for segment in (parsed.path or "/").split("/"):
        if re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", segment, re.IGNORECASE):
            safe_path_segments.append(_mask_log_value(segment))
        elif re.match(r"^(cs|pm|pi|seti|tok|src|snap)_[A-Za-z0-9_=-]{12,}$", segment):
            safe_path_segments.append(_mask_log_value(segment))
        elif len(segment) >= 40 and re.fullmatch(r"[A-Za-z0-9_.=-]+", segment):
            safe_path_segments.append(_mask_log_value(segment))
        else:
            safe_path_segments.append(segment)
    safe_path = "/".join(safe_path_segments) or "/"
    parts = [f"host={host}", f"path={safe_path}"]
    query_parts = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        key_lower = key.lower()
        if key_lower in {"reference", "checkout_session_id", "session_id", "snap_token", "token", "client_secret"}:
            query_parts.append(f"{key}={_mask_log_value(value)}")
        elif key_lower in {"target", "locale", "payment_type"}:
            query_parts.append(f"{key}={value}")
        else:
            query_parts.append(f"{key}=<redacted>")
    if query_parts:
        parts.append(f"query={','.join(query_parts)}")
    return " ".join(parts)


def _safe_proxy_summary(proxy_url: str | None) -> str:
    raw = str(proxy_url or "").strip()
    if not raw:
        return "disabled"
    try:
        normalized = normalize_proxy_url(raw)
        parsed = urlsplit(normalized)
        username = unquote(parsed.username or "")
        fields = [
            "enabled",
            f"scheme={parsed.scheme}",
            f"host={parsed.hostname or ''}",
            f"port={parsed.port or ''}",
            f"username={_mask_log_value(username, left=8, right=4) if username else '<none>'}",
            f"password_present={bool(parsed.password)}",
        ]
        return " ".join(fields)
    except Exception as exc:
        return f"invalid error={exc}"


def _safe_email_summary(email: Any) -> str:
    raw = str(email or "").strip()
    if "@" not in raw:
        return _mask_log_value(raw, left=3, right=2)
    local, domain = raw.split("@", 1)
    return f"{_mask_log_value(local, left=3, right=2)}@{domain}"


def _safe_phone_summary(phone_number: Any, country_code: str = "") -> str:
    digits = re.sub(r"\D+", "", str(phone_number or ""))
    prefix = re.sub(r"\D+", "", str(country_code or ""))
    if not digits:
        return f"country_code={prefix or '<auto>'} phone=<empty>"
    return f"country_code={prefix or '<auto>'} phone=***{digits[-4:]}(len={len(digits)})"


def _safe_otp_summary(otp: Any) -> str:
    digits = re.sub(r"\D+", "", str(otp or ""))
    if not digits:
        return "<empty>"
    if len(digits) <= 4:
        return f"{digits[:1]}***len={len(digits)}"
    return f"{digits[:2]}***{digits[-2:]}(len={len(digits)})"


def _redact_network_capture_text(text: Any, *, limit: int = 900) -> str:
    raw = _compact_log_text(text, limit=max(limit * 2, 1200))
    if not raw:
        return ""
    raw = re.sub(r"\b(reference_id|reference|token|client_secret|otp|pin|password)=([^&\s]+)", r"\1=<redacted>", raw, flags=re.IGNORECASE)
    raw = re.sub(r'"(reference_id|reference|token|client_secret|otp|pin|password)"\s*:\s*"[^"]*"', r'"\1":"<redacted>"', raw, flags=re.IGNORECASE)
    raw = re.sub(r"\b(cs|pm|pi|seti|tok|src|snap)_[A-Za-z0-9_=-]{12,}\b", lambda m: _mask_log_value(m.group(0)), raw)
    raw = re.sub(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
        lambda m: _mask_log_value(m.group(0)),
        raw,
        flags=re.IGNORECASE,
    )
    return raw[:limit]


def _gopay_progress_level(stage: str) -> str:
    if stage in {
        "checkout_not_approved",
        "checkout_not_approved_rotate",
        "chatgpt_approve_blocked_rotate",
        "chatgpt_approve_blocked_cooldown",
        "gopay_account_skipped_cooldown",
        "submit_retry",
        "stripe_nonzero_amount_blocked",
        "midtrans_nonzero_amount_blocked",
        "gopay_nonzero_amount_blocked_rotate",
        "midtrans_already_linked",
        "midtrans_already_linked_failed",
        "gopay_rate_limited",
        "midtrans_linking_retry",
        "sms_otp_resend_due",
        "sms_provider_resend_failed",
        "sms_otp_resend_failed",
        "otp_invalid",
        "gopay_payment_process_failed_rotate",
        "gopay_account_failed_rotate",
        "gopay_retryable_failure_rotate",
        "gopay_already_linked_retry",
        "gopay_rate_limited_retry",
        "gopay_otp_retry",
        "gopay_auth_session_refresh_failed",
    }:
        return "warn"
    if stage in {
        "completed",
        "payment_completed",
        "billing_info_filled",
        "gopay_selected",
        "otp_received",
        "gopay_auth_session_refresh_done",
        "chatgpt_user_paid_skip",
    }:
        return "success"
    if stage in {
        "failed",
        "gopay_all_accounts_blocked",
        "gopay_all_accounts_rejected",
        "gopay_all_payment_process_failed",
        "gopay_all_nonzero_amount_blocked",
        "gopay_all_accounts_failed",
    }:
        return "error"
    return "info"


def _gopay_progress_message(stage: str, payload: dict[str, Any]) -> str:
    if payload.get("message"):
        return str(payload.get("message") or "")
    email = _safe_email_summary(payload.get("email") or "")
    attempt = payload.get("attempt")
    total = payload.get("total")
    attempt_suffix = f"（第 {attempt}/{total} 个）" if attempt and total else ""
    field = str(payload.get("field") or "").strip()
    wait_seconds = payload.get("wait_seconds")
    stage_messages = {
        "billing_address_generated": "已自动生成账单地址",
        "billing_address_retry": "账单地址无法识别，已更换地址重试",
        "chatgpt_http_session_ready": "ChatGPT HTTP 会话已准备好",
        "generate_checkout": "正在生成 ChatGPT 支付链接",
        "chatgpt_checkout_browser_handoff": "进入浏览器 checkout UI，等待真实页面跳转",
        "open_checkout": "正在打开支付页",
        "checkout_opened": "支付页已打开",
        "select_gopay": "正在选择 GoPay 支付方式",
        "gopay_selected": "已选择 GoPay 支付方式",
        "fill_billing_info": "正在填写账单信息",
        "billing_info_filled": "账单信息填写完成",
        "accept_checkout_terms": "正在勾选支付条款",
        "checkout_terms_accepted": "支付条款已勾选",
        "submit_checkout": "正在提交订阅",
        "submit_clicked": "已点击订阅，等待 Stripe/Midtrans 跳转",
        "gopay_http_flow": "已进入 GoPay/Midtrans 接管流程",
        "stripe_zero_due_confirmed": "已确认 Stripe 应付金额为 0",
        "stripe_address_update": "正在通过协议提交 Stripe 账单地址",
        "stripe_address_update_done": "Stripe 账单地址协议提交完成",
        "stripe_confirm_retry_terms": "Stripe 提示需接受条款，正在补充条款确认后重试",
        "stripe_protocol_form_failed_browser_fallback": "协议填表失败，切换到浏览器 checkout UI",
        "midtrans_load_transaction": "正在读取 Midtrans 交易",
        "midtrans_linking": "正在发起 GoPay 账户绑定",
        "midtrans_linking_retry": "GoPay 账户绑定接口 429 限流，正在直接重试协议接口",
        "gopay_validate_reference": "正在校验 GoPay 绑定引用",
        "gopay_user_consent": "正在确认 GoPay 授权",
        "gopay_sms_channel_switch": "正在尝试切换 GoPay SMS OTP",
        "gopay_sms_channel_switched": "已切换 GoPay SMS OTP",
        "gopay_sms_channel_switch_failed": "GoPay SMS OTP 切换失败，回退重发流程",
        "trigger_sms_otp": "正在触发 GoPay OTP",
        "sms_otp_triggered": "已触发 GoPay OTP",
        "sms_otp_resend_due": "1 分钟未收到 GoPay OTP，正在重新发送验证码",
        "sms_provider_resend_triggered": "已通知短信平台重新接收 GoPay OTP",
        "whatsapp_otp_trigger": "正在触发 GoPay WhatsApp OTP",
        "wait_whatsapp_otp": "正在等待安卓模拟器 WhatsApp 接收 GoPay OTP",
        "wait_otp": "正在等待 GoPay SMS OTP",
        "fetch_otp": "正在从接码接口拉取 GoPay OTP",
        "otp_invalid": "GoPay OTP 错误，继续等待新验证码",
        "gopay_validate_otp": "正在校验 GoPay OTP",
        "gopay_tokenize_pin": "正在生成 GoPay PIN token",
        "gopay_validate_pin": "正在校验 GoPay 绑定 PIN",
        "midtrans_create_charge": "正在创建 Midtrans GoPay 扣款",
        "gopay_payment_validate": "正在校验 GoPay 扣款引用",
        "gopay_payment_confirm": "正在确认 GoPay 扣款",
        "gopay_payment_process": "正在提交 GoPay 扣款 PIN",
        "gopay_payment_process_failed_rotate": "GoPay 钱包扣款授权失败，切换下一个账号",
        "gopay_retryable_failure_rotate": "当前账号遇到可重试失败，切换下一个账号",
        "gopay_already_linked_retry": "GoPay 手机号仍绑定其他账号，稍后重试",
        "gopay_rate_limited_retry": "GoPay/Midtrans 限流，稍后重试",
        "gopay_otp_retry": "GoPay OTP 未完成，稍后重试",
        "gopay_auth_session_refresh_started": "auth_session 已失效，正在重新登录刷新",
        "gopay_auth_session_refresh_done": "auth_session 已刷新，稍后重试 GoPay",
        "gopay_auth_session_refresh_failed": "auth_session 刷新失败，账号标记废弃",
        "chatgpt_user_paid_skip": "账号已是付费用户，跳过 GoPay 绑卡",
        "gopay_account_failed_rotate": "当前账号 GoPay 任务失败，切换下一个账号",
        "gopay_nonzero_amount_blocked_rotate": "账单金额非 0，切换下一个账号",
        "payment_completed": "GoPay 支付已提交，正在回查 ChatGPT 状态",
        "chatgpt_verify": "正在回查 ChatGPT 支付结果",
        "completed": "GoPay 支付完成，绑定完成",
        "failed": "GoPay 流程失败",
        "chatgpt_approve": "正在确认 ChatGPT checkout",
        "chatgpt_approve_browser_fallback": "approve HTTP 被拦截，切换到浏览器上下文重试",
        "chatgpt_approve_browser_fallback_succeeded": "浏览器上下文 approve 已通过",
        "chatgpt_approve_blocked_rotate": "ChatGPT approve 被拦截，切换下一个账号",
        "gopay_all_accounts_blocked": "所有候选账号的 approve 都被拦截",
        "gopay_all_accounts_rejected": "所有候选账号的付款均未获批准",
        "gopay_all_accounts_failed": "所有候选账号的 GoPay 任务均失败",
    }
    if stage == "billing_info_ready":
        billing = payload.get("billing_info") if isinstance(payload.get("billing_info"), dict) else {}
        city = str(billing.get("city") or "").strip()
        state = str(billing.get("state") or "").strip()
        zip_code = str(billing.get("zip") or "").strip()
        location = " ".join(part for part in (city, state, zip_code) if part)
        return f"当前账单地址已准备：{location}" if location else "当前账单地址已准备"
    if stage == "checkout_ready":
        url_summary = _safe_url_summary(payload.get("checkout_url") or "")
        return f"支付链接已生成：{url_summary}" if url_summary else "支付链接已生成"
    if stage == "gopay_try_account":
        return f"正在处理账号 {email or '<empty>'}{attempt_suffix}"
    if stage == "gopay_rotate_account":
        return f"切换到下一个账号 {email or '<empty>'}{attempt_suffix}"
    if stage == "gopay_account_skipped_cooldown":
        remaining = payload.get("remaining_seconds")
        return f"跳过冷却中的账号 {email or '<empty>'}，剩余 {remaining}s"
    if stage == "billing_fill_field" and field:
        return f"正填入 {field}"
    if stage == "billing_select_field" and field:
        return f"正选择 {field}"
    if stage == "billing_field_verified" and field:
        return f"提交前校验通过：{field}"
    if stage == "wait_sms_otp_window" and wait_seconds is not None:
        return f"等待 {wait_seconds}s 后触发/拉取 GoPay SMS OTP"
    if stage == "wait_sms_channel_switch_window" and wait_seconds is not None:
        return f"等待 {wait_seconds}s 后尝试切换 GoPay SMS OTP"
    if stage == "gopay_sms_channel_switch_failed":
        reason = str(payload.get("reason") or "").strip()
        return f"GoPay SMS OTP 切换失败，回退重发流程：{_compact_log_text(reason, limit=120)}" if reason else "GoPay SMS OTP 切换失败，回退重发流程"
    if stage == "sms_otp_resend_failed":
        reason = str(payload.get("reason") or "").strip()
        return f"GoPay SMS OTP 重新发送失败，继续等待接码接口：{_compact_log_text(reason, limit=120)}" if reason else "GoPay SMS OTP 重新发送失败，继续等待接码接口"
    if stage == "sms_provider_resend_failed":
        reason = str(payload.get("reason") or "").strip()
        return f"短信平台重新接收 GoPay OTP 失败，继续等待接码接口：{_compact_log_text(reason, limit=120)}" if reason else "短信平台重新接收 GoPay OTP 失败，继续等待接码接口"
    if stage == "wait_whatsapp_otp":
        return "等待安卓模拟器 WhatsApp 接收 GoPay OTP"
    if stage == "whatsapp_otp_trigger":
        return "尝试触发 GoPay WhatsApp OTP"
    if stage == "otp_received":
        return f"收到 GoPay OTP：{payload.get('otp') or '<redacted>'}"
    if stage == "otp_invalid":
        attempt = payload.get("attempt")
        max_attempts = payload.get("max_attempts")
        suffix = f"（第 {attempt}/{max_attempts} 次）" if attempt and max_attempts else ""
        return f"GoPay OTP 错误，已忽略该验证码并继续等待新验证码{suffix}"
    if stage == "submit_retry":
        reason = str(payload.get("reason") or "").strip()
        return f"订阅提交失败，准备重试：{_compact_log_text(reason, limit=120)}" if reason else "订阅提交失败，准备重试"
    if stage.endswith("_retry"):
        next_attempt = payload.get("next_attempt")
        max_attempts = payload.get("max_attempts")
        wait = payload.get("wait_seconds")
        reason = str(payload.get("reason") or "").strip()
        suffix = f"（{next_attempt}/{max_attempts}）" if next_attempt and max_attempts else ""
        wait_text = f"，等待 {int(float(wait))}s" if wait is not None else ""
        reason_text = f"：{_compact_log_text(reason, limit=120)}" if reason else ""
        return f"网络请求失败，准备重试{suffix}{wait_text}{reason_text}"
    return stage_messages.get(stage, "")


def _build_gopay_progress_payload(stage: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {"stage": stage}
    payload.update(dict(extra or {}))
    if not payload.get("message"):
        message = _gopay_progress_message(stage, payload)
        if message:
            payload["message"] = message
    if not payload.get("level"):
        payload["level"] = _gopay_progress_level(stage)
    return payload


def _emit_gopay_progress(progress_callback: Any, stage: str, **extra):
    if callable(progress_callback):
        progress_callback(_build_gopay_progress_payload(stage, extra))


def _safe_error_summary(error: Any, *, limit: int = 240) -> str:
    text = _compact_log_text(error, limit=limit)
    text = re.sub(r"://[^@\s]+@", "://<auth>@", text)
    text = re.sub(r"([?&](?:token|access_token|session_token|client_secret|otp|pin)=)[^&\s]+", r"\1<redacted>", text, flags=re.IGNORECASE)
    text = re.sub(r"(Bearer\s+)[A-Za-z0-9._=-]+", r"\1<redacted>", text, flags=re.IGNORECASE)
    return text


def _is_playwright_navigation_race_error(error: Any) -> bool:
    text = str(error or "").lower()
    return bool(
        "execution context was destroyed" in text
        or "most likely because of a navigation" in text
        or "cannot find context with specified id" in text
    )


def _wait_for_page_navigation_quiet(page: Any, *, quiet_ms: int = 700, timeout_ms: int = 5000) -> None:
    """Wait until the current Playwright page URL stops changing briefly."""
    deadline = time.time() + max(0.1, timeout_ms / 1000)
    quiet_deadline = 0.0
    last_url = None
    while time.time() < deadline:
        try:
            current_url = str(getattr(page, "url", "") or "")
        except Exception:
            current_url = ""
        now = time.time()
        if current_url != last_url:
            last_url = current_url
            quiet_deadline = now + max(0.1, quiet_ms / 1000)
        elif quiet_deadline and now >= quiet_deadline:
            return
        try:
            page.wait_for_timeout(200)
        except Exception:
            time.sleep(0.2)


def _is_chatgpt_approve_blocked_result(result: dict | None) -> bool:
    if not isinstance(result, dict):
        return False
    if str(result.get("failure_stage") or "") != "chatgpt_approve":
        return False
    return "blocked" in str(result.get("message") or "").lower()


def _is_checkout_payment_not_approved_error(text: str) -> bool:
    clean = str(text or "").strip()
    return bool(clean and any(pattern.search(clean) for pattern in CHECKOUT_PAYMENT_NOT_APPROVED_PATTERNS))


def _is_checkout_customer_location_error(text: str) -> bool:
    clean = str(text or "").strip()
    if not clean:
        return False
    return bool(
        re.search(r"customer'?s location.*(?:not|isn'?t).*recognized", clean, re.IGNORECASE)
        or re.search(r"valid customer address", clean, re.IGNORECASE)
        or re.search(r"automatically calculate tax", clean, re.IGNORECASE)
    )


def _is_checkout_rate_limited_error(text: str) -> bool:
    clean = str(text or "").strip()
    if not clean:
        return False
    return "429" in clean or _looks_like_gopay_rate_limit_text(clean)


def _is_checkout_payment_not_approved_result(result: dict | None) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("status") == "success":
        return False
    stage = str(result.get("failure_stage") or "")
    if stage not in {"checkout_not_approved", "browser_checkout", "submit_checkout"}:
        return False
    return _is_checkout_payment_not_approved_error(str(result.get("message") or ""))


def _is_gopay_payment_process_rotatable_result(result: dict | None) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("status") == "success":
        return False
    if str(result.get("failure_stage") or "") != "gopay_payment_process":
        return False
    message = str(result.get("message") or "").lower()
    return (
        "gopay_wallet" in message
        or "payment-switch" in message
        or "createauth" in message
        or "errorcode=201" in message
        or '"code":"201"' in message
        or "'code': '201'" in message
    )


def _is_gopay_nonzero_amount_blocked_result(result: dict | None) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("status") == "success":
        return False
    return str(result.get("failure_stage") or "") in {
        "browser_charge_guard",
        "stripe_charge_guard",
        "midtrans_charge_guard",
    }


def _is_gopay_already_linked_result(result: dict | None) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("status") == "success":
        return False
    message = str(result.get("message") or "").lower()
    return (
        str(result.get("failure_stage") or "") == "midtrans_linking"
        and (
            "already linked" in message
            or "已绑定其他账号" in message
            or "绑定其他账号" in message
        )
    )


def _looks_like_chatgpt_user_paid_text(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    if not normalized:
        return False
    return any(
        marker in normalized
        for marker in (
            "user is paid",
            "user already paid",
            "already a paid user",
            "already paid user",
            "already subscribed",
            "already has an active subscription",
            "用户已付费",
            "已是付费用户",
            "已有有效订阅",
        )
    )


def _is_chatgpt_user_paid_result(result: dict | None) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("status") == "success":
        return bool(result.get("user_paid_skip"))
    return _looks_like_chatgpt_user_paid_text(json.dumps(result, ensure_ascii=False))


def _as_chatgpt_user_paid_success(result: dict | None, *, checkout_url: str = "", billing_info: dict | None = None) -> dict:
    payload = dict(result or {})
    payload.update(
        {
            "status": "success",
            "failure_stage": "",
            "message": "ChatGPT 返回 user is paid，账号已是付费用户，跳过 GoPay 绑卡",
            "user_paid_skip": True,
        }
    )
    if checkout_url and not payload.get("checkout_url"):
        payload["checkout_url"] = checkout_url
    if billing_info and not payload.get("billing_info"):
        payload["billing_info"] = billing_info
    return payload


def _is_midtrans_linking_rate_limited_result(result: dict | None) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("status") == "success":
        return False
    return str(result.get("failure_stage") or "") == "midtrans_linking" and "http 429" in str(
        result.get("message") or ""
    ).lower()


def _is_midtrans_linking_rate_limited_error(exc: BaseException) -> bool:
    stage = str(getattr(exc, "stage", "") or "")
    if stage != "midtrans_linking":
        return False
    return "http 429" in str(exc).lower() or _looks_like_gopay_rate_limit_text(str(exc))


def _is_chatgpt_token_invalidated_result(result: dict | None) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("status") == "success":
        return False
    text = json.dumps(result, ensure_ascii=False).lower()
    return (
        "token_invalidated" in text
        or "authentication token has been invalidated" in text
        or ("http 401" in text and "invalidated" in text)
    )


def _looks_like_http_forbidden_text(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    if not normalized:
        return False
    return "http 403" in normalized or "status 403" in normalized or "forbidden" in normalized


def _gopay_pending_retry_reason(result: dict | None) -> str:
    if not isinstance(result, dict) or result.get("status") == "success":
        return ""
    if _is_chatgpt_user_paid_result(result) or _is_chatgpt_token_invalidated_result(result) or _is_gopay_nonzero_amount_blocked_result(result):
        return ""
    if _is_chatgpt_approve_blocked_result(result):
        return "chatgpt_approve_blocked"
    if _is_gopay_payment_process_rotatable_result(result):
        return "gopay_payment_process"
    if _is_gopay_already_linked_result(result):
        return "gopay_already_linked"
    stage = str(result.get("failure_stage") or "")
    message = str(result.get("message") or "")
    if _is_midtrans_linking_rate_limited_result(result) or stage == "gopay_rate_limited" or _looks_like_gopay_rate_limit_text(message):
        return "rate_limited"
    if stage == "gopay_wallet_no_numbers" or "no_numbers" in message.lower() or "no numbers" in message.lower():
        return "gopay_wallet_no_numbers"
    if stage in {"fetch_otp", "gopay_validate_otp", "trigger_sms_otp"}:
        return "gopay_otp"
    if _looks_like_http_forbidden_text(message):
        return "http_403"
    if stage in {
        "resolve_midtrans_redirect",
        "pm_redirect",
        "midtrans_load_transaction",
        "midtrans_linking",
        "gopay_validate_reference",
        "gopay_user_consent",
        "gopay_payment_validate",
        "gopay_payment_confirm",
        "browser_checkout",
        "generate_checkout",
    }:
        return "transient_gopay_flow"
    return ""


def _gopay_pending_retry_source_stage(result: dict | None, reason: str) -> str:
    if reason == "checkout_not_approved":
        return "checkout_not_approved_rotate"
    if reason == "gopay_payment_process":
        return "gopay_payment_process_failed_rotate"
    if reason == "gopay_already_linked":
        return "gopay_already_linked_retry"
    if reason == "rate_limited":
        return "gopay_rate_limited_retry"
    if reason == "gopay_wallet_no_numbers":
        return "gopay_wallet_no_numbers_retry"
    if reason == "gopay_otp":
        return "gopay_otp_retry"
    return "gopay_retryable_failure_rotate"


def _gopay_rate_limited_message() -> str:
    return "GoPay 授权页提示尝试过多，请稍后重试，或更换 GoPay 手机号/钱包"


def _looks_like_gopay_rate_limit_text(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    if not normalized:
        return False
    return any(
        marker in normalized
        for marker in (
            "请求过多",
            "请求太多",
            "尝试过多",
            "请求频繁",
            "操作过于频繁",
            "访问过于频繁",
            "请稍后重试",
            "请稍后再试",
            "稍后再试",
            "稍后重试",
            "更换 gopay",
            "更换 gopay 手机号",
            "更换 gopay 手机号/钱包",
            "too many attempts",
            "too many requests",
            "rate limited",
            "rate limit",
            "try again later",
            "please try again later",
            "terlalu banyak",
            "terlalu banyak permintaan",
            "terlalu banyak percobaan",
            "permintaan terlalu banyak",
            "terlalu sering",
            "anda sudah mencoba terlalu banyak",
            "kamu sudah mencoba terlalu banyak",
            "kamu udah kebanyakan nyoba",
            "udah kebanyakan nyoba",
            "kebanyakan nyoba",
            "kebanyakan mencoba",
            "sudah terlalu banyak mencoba",
            "coba lagi setelah beberapa saat",
            "setelah beberapa saat",
            "coba lagi nanti",
            "coba beberapa saat lagi",
            "silakan coba lagi nanti",
            "silahkan coba lagi nanti",
            "mohon coba lagi nanti",
        )
    )


def _looks_like_gopay_rate_limit_payload(payload: Any) -> bool:
    try:
        text = json.dumps(payload, ensure_ascii=False)
    except Exception:
        text = str(payload or "")
    return _looks_like_gopay_rate_limit_text(text)


def _looks_like_gopay_invalid_otp_payload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    errors = payload.get("errors")
    if not isinstance(errors, list):
        errors = []
    for error in errors:
        if not isinstance(error, dict):
            continue
        code = str(error.get("code") or "").strip().lower()
        message = str(error.get("message_title") or error.get("message") or "").strip().lower()
        if code == "gopay-1604":
            return True
        if "kode otp" in message and ("salah" in message or "wrong" in message):
            return True
    return False


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


def _extract_snap_token(url: Any) -> str:
    matched = re.search(
        r"app\.midtrans\.com/snap/v[14]/redirection/([a-f0-9-]{36})",
        str(url or ""),
        re.IGNORECASE,
    )
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
    openai_sentinel_token: str = "",
    oai_client_version: str = "",
    oai_client_build_number: str = "",
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
    if openai_sentinel_token:
        headers["openai-sentinel-token"] = openai_sentinel_token
    if oai_client_version:
        headers["oai-client-version"] = oai_client_version
    if oai_client_build_number:
        headers["oai-client-build-number"] = oai_client_build_number
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
    openai_sentinel_token: str = "",
    oai_client_version: str = "",
    oai_client_build_number: str = "",
    proxy_url: str | None = None,
) -> Any:
    http = _new_http_session(proxy_url, require_curl_cffi=True)
    _configure_chatgpt_http_session(
        http,
        access_token=access_token,
        session_token=session_token,
        cookie_header=cookie_header,
        account_id=account_id,
        device_id=device_id,
        user_agent=user_agent,
        openai_sentinel_token=openai_sentinel_token,
        oai_client_version=oai_client_version,
        oai_client_build_number=oai_client_build_number,
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


def _load_chatgpt_auth_file_context(email: str) -> dict[str, str]:
    """Load the local Codex/CPA auth file as a fallback ChatGPT token source."""
    normalized = str(email or "").strip().lower()
    if not normalized:
        return {}

    auth_file = ""
    try:
        from autoteam.accounts import find_account, load_accounts

        account = find_account(load_accounts(), normalized)
        if account:
            auth_file = str(account.get("auth_file") or "").strip()
    except Exception:
        auth_file = ""

    if not auth_file:
        return {}

    try:
        path = Path(auth_file)
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    if not isinstance(data, dict):
        return {}
    account_data = data.get("account") if isinstance(data.get("account"), dict) else {}
    user_data = data.get("user") if isinstance(data.get("user"), dict) else {}
    return {
        "access_token": str(data.get("access_token") or data.get("accessToken") or "").strip(),
        "account_id": str(
            data.get("account_id")
            or data.get("accountId")
            or account_data.get("id")
            or account_data.get("account_id")
            or user_data.get("account_id")
            or user_data.get("accountId")
            or ""
        ).strip(),
        "id_token": str(data.get("id_token") or data.get("idToken") or "").strip(),
        "auth_file": auth_file,
    }


def _looks_like_pm_redirect_url(url: str) -> bool:
    raw = str(url or "").lower()
    return "pm-redirects.stripe.com/authorize/" in raw or "app.midtrans.com/snap/" in raw


def _gopay_signup_bridge_resend_url(sms_url: str) -> str:
    raw = _normalize_local_gopay_signup_bridge_url(sms_url)
    if "/otp/gopay-signup/" not in raw:
        return ""
    parsed = urlsplit(raw)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["resend"] = "1"
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def _normalize_local_gopay_signup_bridge_url(sms_url: str) -> str:
    raw = str(sms_url or "").strip()
    if "/otp/gopay-signup/" not in raw:
        return raw
    try:
        parsed = urlsplit(raw)
    except Exception:
        return raw
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return raw
    base = str(os.environ.get("AUTOTEAM_LOCAL_BASE_URL") or "").strip().rstrip("/")
    if not base:
        return raw
    try:
        base_parsed = urlsplit(base)
    except Exception:
        return raw
    if not base_parsed.scheme or not base_parsed.netloc:
        return raw
    if parsed.netloc == base_parsed.netloc and parsed.scheme == base_parsed.scheme:
        return raw
    return urlunsplit((base_parsed.scheme, base_parsed.netloc, parsed.path, parsed.query, parsed.fragment))


def _trigger_gopay_signup_bridge_resend(sms_url: str) -> bool:
    resend_url = _gopay_signup_bridge_resend_url(sms_url)
    if not resend_url:
        return False
    resp = requests.get(
        resend_url,
        timeout=20,
        verify=False,
        headers={
            "User-Agent": "Mozilla/5.0 AutoTeam/1.0",
            "Accept": "application/json, text/plain, text/html, */*",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    text = (resp.text or "").strip()
    if not resp.ok:
        raise RuntimeError(text[:200] or f"短信平台重发接口返回异常({resp.status_code})")
    return True


def _poll_otp_from_sms_url(
    sms_url: str,
    *,
    timeout_seconds: int,
    initial_delay_seconds: float | None = None,
    resend_after_seconds: float | None = None,
    max_resend_attempts: int | None = None,
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
        resend_interval = (
            _env_float("GOPAY_SMS_OTP_RESEND_AFTER_SECONDS", GOPAY_SMS_OTP_RESEND_AFTER_S)
            if resend_after_seconds is None
            else float(resend_after_seconds or 0)
        )
        resend_limit = None if max_resend_attempts is None else max(0, int(max_resend_attempts or 0))
        resend_attempts = 0
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
        next_resend_at = time.time() + max(0.0, resend_interval) if resend_interval > 0 else 0.0
        while time.time() < deadline:
            if callable(is_cancelled) and is_cancelled():
                raise GoPayOTPCancelled("任务已取消", stage="fetch_otp")
            if callable(progress):
                progress("fetch_otp")
            try:
                ignored_otps = getattr(provider, "_gopay_ignored_otps", set())
                ignored = {str(item or "").strip() for item in ignored_otps if str(item or "").strip()}
                code = _fetch_sms_code(sms_url, ignored_otps=ignored)
                if code:
                    if str(code).strip() in ignored:
                        logger.info("[gopay_executor] 忽略已验证失败的 GoPay OTP: %s", _safe_otp_summary(code))
                    else:
                        return code
            except Exception as exc:
                logger.info("[gopay_executor] 等待 GoPay OTP: %s", exc)
            if next_resend_at and time.time() >= next_resend_at:
                resend_callback = getattr(provider, "_gopay_resend_callback", None)
                bridge_resend_url = _gopay_signup_bridge_resend_url(sms_url)
                if callable(resend_callback) or bridge_resend_url:
                    if resend_limit is not None and resend_attempts >= resend_limit:
                        raise GoPayOTPCancelled(
                            f"未收到 GoPay OTP，重新发送验证码已达到上限 {resend_limit} 次",
                            stage="fetch_otp",
                        )
                    if callable(progress):
                        progress("sms_otp_resend_due", wait_seconds=int(resend_interval))
                    resend_attempts += 1
                    try:
                        if bridge_resend_url:
                            _trigger_gopay_signup_bridge_resend(sms_url)
                            if callable(progress):
                                progress("sms_provider_resend_triggered")
                    except Exception as exc:
                        logger.info(
                            "[gopay_executor] SMS provider resend while polling failed: %s",
                            _safe_error_summary(exc),
                        )
                        if callable(progress):
                            progress("sms_provider_resend_failed", reason=_safe_error_summary(exc))
                    if callable(resend_callback):
                        try:
                            delay = max(0.0, _env_float("GOPAY_SMS_PROVIDER_RESEND_DELAY_SECONDS", 2.0)) if bridge_resend_url else 0.0
                            if delay:
                                time.sleep(delay)
                            resend_callback()
                        except Exception as exc:
                            logger.info(
                                "[gopay_executor] GoPay OTP resend while polling failed: %s",
                                _safe_error_summary(exc),
                            )
                            if callable(progress):
                                progress("sms_otp_resend_failed", reason=_safe_error_summary(exc))
                next_resend_at = time.time() + max(0.0, resend_interval)
            time.sleep(5)
        raise GoPayOTPCancelled("等待 GoPay OTP 超时", stage="fetch_otp")

    try:
        setattr(provider, "_gopay_sms_url", sms_url)
        if _gopay_signup_bridge_resend_url(sms_url):
            setattr(provider, "_gopay_sms_provider_resend_callback", lambda: _trigger_gopay_signup_bridge_resend(sms_url))
    except Exception:
        pass
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


def _normalize_checkout_ui_mode(value: str = "") -> str:
    mode = str(value or "").strip().lower()
    return "hosted" if mode == "hosted" else "custom"


def _normalize_checkout_form_mode(value: str = "") -> str:
    mode = str(value or "").strip().lower().replace("_", "-")
    if mode in {"protocol", "browser", "auto"}:
        return mode
    if "GOPAY_BROWSER_CHECKOUT_UI" in os.environ:
        return "browser" if _env_enabled("GOPAY_BROWSER_CHECKOUT_UI", True) else "protocol"
    return "auto"


def _protocol_checkout_can_browser_fallback(exc: GoPayFlowError) -> bool:
    return str(getattr(exc, "stage", "") or "") in {
        "stripe_init",
        "stripe_elements_session",
        "stripe_address_update",
        "stripe_payment_method",
        "stripe_confirm",
        "chatgpt_approve",
        "resolve_midtrans_redirect",
        "pm_redirect",
    }


def _chatgpt_checkout_payload(checkout_ui_mode: str = "custom") -> dict:
    return {
        "entry_point": "all_plans_pricing_modal",
        "plan_name": "chatgptplusplan",
        "billing_details": {"country": "ID", "currency": "IDR"},
        "promo_campaign": {
            "promo_campaign_id": "plus-1-month-free",
            "is_coupon_from_query_param": False,
        },
        "checkout_ui_mode": _normalize_checkout_ui_mode(checkout_ui_mode),
    }


def _generate_id_checkout_http(
    http: Any,
    *,
    access_token: str,
    checkout_ui_mode: str = "custom",
    session_token: str = "",
    cookie_header: str = "",
    account_id: str = "",
    device_id: str = "",
    user_agent: str = "",
    openai_sentinel_token: str = "",
    oai_client_version: str = "",
    oai_client_build_number: str = "",
) -> dict:
    _configure_chatgpt_http_session(
        http,
        access_token=access_token,
        session_token=session_token,
        cookie_header=cookie_header,
        account_id=account_id,
        device_id=device_id,
        user_agent=user_agent,
        openai_sentinel_token=openai_sentinel_token,
        oai_client_version=oai_client_version,
        oai_client_build_number=oai_client_build_number,
    )

    normalized_checkout_ui_mode = _normalize_checkout_ui_mode(checkout_ui_mode)
    resp = http.post(
        "https://chatgpt.com/backend-api/payments/checkout",
        json=_chatgpt_checkout_payload(normalized_checkout_ui_mode),
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    if (
        resp.status_code == 400
        and normalized_checkout_ui_mode == "hosted"
        and "checkout ui mode is not supported" in str(resp.text or "").lower()
    ):
        logger.info("[gopay_executor] hosted checkout ui mode unsupported, retrying checkout generation with custom mode")
        resp = http.post(
            "https://chatgpt.com/backend-api/payments/checkout",
            json=_chatgpt_checkout_payload("custom"),
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


def _chatgpt_approve_blocked_message(payload: dict) -> str:
    return (
        f"ChatGPT approve 未通过: {payload}；"
        "这发生在 GoPay/Midtrans 前，表示 ChatGPT checkout approve 被风控拦截。"
        "浏览器能打开 checkout 页不等于协议 approve 会通过。"
        "可等待账号冷却、切换 auth_session，或在浏览器手动选择 GoPay 后把 "
        "pm-redirects.stripe.com / app.midtrans.com/snap 链接粘到 Checkout 链接继续接管 GoPay"
    )


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
    if access_token or cookie_header or account_id or device_id or openai_sentinel_token:
        _configure_chatgpt_http_session(
            http,
            access_token=access_token,
            cookie_header=cookie_header,
            account_id=account_id,
            device_id=device_id,
            openai_sentinel_token=openai_sentinel_token,
        )
    try:
        http.post(
            "https://chatgpt.com/backend-api/sentinel/ping",
            json={},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.info("[gopay_executor] sentinel ping before approve skipped: %s", _safe_error_summary(exc))
    logger.info(
        "[gopay_executor] ChatGPT approve request using reference-style session headers: cookie_present=%s auth_present=%s sentinel_present=%s",
        bool(cookie_header or _cookie_header_from_http_session(http)),
        bool(access_token),
        bool(openai_sentinel_token),
    )
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
        raise GoPayFlowError(_chatgpt_approve_blocked_message(payload), stage="chatgpt_approve")
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
    headers = _chatgpt_checkout_headers(
        access_token=access_token,
        checkout_session_id=checkout_session_id,
        processor_entity=processor_entity,
        cookie_header=cookie_header,
        account_id=account_id,
        device_id=device_id,
        openai_sentinel_token=openai_sentinel_token,
    )
    resp = http.get(
        "https://chatgpt.com/checkout/verify",
        params={
            "stripe_session_id": checkout_session_id,
            "processor_entity": processor_entity,
            "plan_type": "plus",
        },
        headers=headers,
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


def _inject_chatgpt_browser_cookies(
    api: ChatGPTTeamAPI,
    *,
    session_token: str = "",
    cookie_header: str = "",
    account_id: str = "",
    device_id: str = "",
):
    if not getattr(api, "context", None):
        raise GoPayFlowError("浏览器上下文未初始化，无法注入 ChatGPT 登录态", stage="chatgpt_approve")

    cookies = []
    seen = set()
    for raw in str(cookie_header or "").split(";"):
        if "=" not in raw:
            continue
        name, value = raw.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name or not value or name in seen:
            continue
        seen.add(name)
        cookies.append(
            {
                "name": name,
                "value": value,
                "url": "https://chatgpt.com",
                "secure": True,
                "sameSite": "Lax",
            }
        )

    token = str(session_token or "").strip()
    has_session_cookie = any(
        name in seen
        for name in (
            "__Secure-next-auth.session-token",
            "__Secure-next-auth.session-token.0",
            "__Secure-next-auth.session-token.1",
        )
    )
    if token and not has_session_cookie:
        if len(token) > 4000:
            token_cookies = [
                ("__Secure-next-auth.session-token.0", token[:4000]),
                ("__Secure-next-auth.session-token.1", token[4000:]),
            ]
        else:
            token_cookies = [("__Secure-next-auth.session-token", token)]
        for name, value in token_cookies:
            seen.add(name)
            cookies.append(
                {
                    "name": name,
                    "value": value,
                    "url": "https://chatgpt.com",
                    "httpOnly": True,
                    "secure": True,
                    "sameSite": "Lax",
                }
            )

    if account_id and "_account" not in seen:
        cookies.append(
            {
                "name": "_account",
                "value": account_id,
                "url": "https://chatgpt.com",
                "secure": True,
                "sameSite": "Lax",
            }
        )
    if device_id and "oai-did" not in seen:
        cookies.append(
            {
                "name": "oai-did",
                "value": device_id,
                "url": "https://chatgpt.com",
                "secure": True,
                "sameSite": "Lax",
            }
        )
    if cookies:
        api.context.add_cookies(cookies)
        logger.info(
            "[gopay_executor] injected ChatGPT browser cookies: count=%s session_split=%s full_session=%s",
            len(cookies),
            any(cookie.get("name") == "__Secure-next-auth.session-token.0" for cookie in cookies),
            any(cookie.get("name") == "__Secure-next-auth.session-token" for cookie in cookies),
        )


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
                const headers = { "Content-Type": "application/json" };
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


def _approve_checkout_with_browser_context(
    api: ChatGPTTeamAPI,
    *,
    access_token: str,
    session_token: str = "",
    cookie_header: str = "",
    checkout_session_id: str,
    processor_entity: str,
    account_id: str = "",
    device_id: str = "",
    proxy_url: str | None = None,
    proxy_bypass: str | None = None,
) -> dict:
    if not _env_enabled("GOPAY_APPROVE_BROWSER_FALLBACK", False):
        raise GoPayFlowError("ChatGPT approve 浏览器 fallback 已禁用", stage="chatgpt_approve")
    if not getattr(api, "browser", None):
        api.account_id = account_id or getattr(api, "account_id", "")
        api.oai_device_id = device_id or getattr(api, "oai_device_id", "") or str(uuid.uuid4())
        api._launch_browser(proxy_url=proxy_url, proxy_bypass=proxy_bypass)
        _inject_chatgpt_browser_cookies(
            api,
            session_token=session_token,
            cookie_header=cookie_header,
            account_id=account_id,
            device_id=device_id,
        )

    context = _load_checkout_context_in_page(
        api,
        checkout_session_id=checkout_session_id,
        processor_entity=processor_entity,
        timeout_ms=20000,
    )
    result = _approve_checkout_in_page(
        api,
        access_token=access_token,
        checkout_session_id=checkout_session_id,
        processor_entity=processor_entity,
    )
    if result.get("result") not in (None, "approved"):
        raise GoPayFlowError(_chatgpt_approve_blocked_message(result), stage="chatgpt_approve")
    if context.get("cookie_header"):
        result["_browser_cookie_header"] = context["cookie_header"]
    if context.get("openai_sentinel_token"):
        result["_browser_openai_sentinel_token"] = context["openai_sentinel_token"]
    return result


def _remember_gopay_redirect_url(url: Any, captured: dict):
    raw = str(url or "").strip()
    if not raw:
        return
    if _looks_like_pm_redirect_url(raw):
        captured["redirect_url"] = raw
    snap_token = _extract_snap_token(raw)
    if snap_token:
        captured["snap_token"] = snap_token


def _diagnose_gopay_authorize_network(
    api: ChatGPTTeamAPI,
    *,
    activation_link_url: str,
    reference_id: str,
    label: str = "whatsapp_authorize",
) -> dict:
    """Capture GoPay authorize page network when explicitly enabled.

    This is a diagnostic helper for comparing the browser "back and re-enter"
    behavior with the known protocol endpoints. It records only sanitized
    request/response metadata and small redacted payload snippets.
    """
    if not _env_truthy("GOPAY_CAPTURE_AUTH_NETWORK"):
        return {"enabled": False}
    activation_link_url = str(activation_link_url or "").strip()
    if not activation_link_url:
        return {"enabled": True, "error": "empty activation link"}

    GOPAY_NETWORK_CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    capture_id = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
    capture_path = GOPAY_NETWORK_CAPTURE_DIR / f"{label}_{capture_id}.json"
    events: list[dict[str, Any]] = []

    def interested(url: Any) -> bool:
        raw = str(url or "").lower()
        return any(
            host in raw
            for host in (
                "app.midtrans.com",
                "gwa.gopayapi.com",
                "customer.gopayapi.com",
                "merchants-gws-app.gopayapi.com",
                "pin-web-client.gopayapi.com",
            )
        )

    def record(event: dict[str, Any]):
        event["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        events.append(event)

    def click_consent_if_present() -> bool:
        selectors = [
            "button:has-text('Hubungkan')",
            "button:has-text('Connect')",
            "button:has-text('Lanjut')",
            "button:has-text('Continue')",
            "button:has-text('Oke')",
            "button",
        ]
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if not locator.is_visible(timeout=1200):
                    continue
                text = ""
                try:
                    text = locator.inner_text(timeout=800)
                except Exception:
                    text = ""
                record({"type": "marker", "action": "click_consent", "selector": selector, "text": _compact_log_text(text, limit=80)})
                locator.click(timeout=5000)
                page.wait_for_timeout(6000)
                record({"type": "marker", "action": "after_click_consent", "page_url": _safe_url_summary(getattr(page, "url", ""))})
                return True
            except Exception:
                continue
        record({"type": "marker", "action": "click_consent_not_found", "page_url": _safe_url_summary(getattr(page, "url", ""))})
        return False

    def on_request(req):
        try:
            url = str(getattr(req, "url", "") or "")
            if not interested(url):
                return
            post_data = ""
            try:
                post_data = getattr(req, "post_data", "") or ""
            except Exception:
                post_data = ""
            record(
                {
                    "type": "request",
                    "method": str(getattr(req, "method", "") or ""),
                    "url": _safe_url_summary(url),
                    "payload": _redact_network_capture_text(post_data, limit=700),
                }
            )
        except Exception:
            pass

    def on_response(resp):
        try:
            url = str(getattr(resp, "url", "") or "")
            if not interested(url):
                return
            body = ""
            try:
                content_type = ""
                try:
                    headers = getattr(resp, "headers", {}) or {}
                    content_type = str(headers.get("content-type") or headers.get("Content-Type") or "")
                except Exception:
                    content_type = ""
                if "json" in content_type or "text" in content_type or "javascript" in content_type:
                    body = resp.text() if callable(getattr(resp, "text", None)) else ""
            except Exception:
                body = ""
            record(
                {
                    "type": "response",
                    "status": int(getattr(resp, "status", 0) or 0),
                    "url": _safe_url_summary(url),
                    "body": _redact_network_capture_text(body, limit=900),
                }
            )
        except Exception:
            pass

    page = None
    try:
        page = api.context.new_page() if getattr(api, "context", None) else getattr(api, "page", None)
    except Exception:
        page = getattr(api, "page", None)
    if not page:
        return {"enabled": True, "error": "browser page unavailable"}

    try:
        page.on("request", on_request)
        page.on("response", on_response)
    except Exception:
        pass

    result = {"enabled": True, "path": str(capture_path), "events": 0}
    try:
        record(
            {
                "type": "marker",
                "action": "open_activation_link",
                "url": _safe_url_summary(activation_link_url),
                "reference": _mask_log_value(reference_id),
            }
        )
        page.goto(activation_link_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)
        record({"type": "marker", "action": "after_open", "page_url": _safe_url_summary(getattr(page, "url", ""))})
        click_consent_if_present()

        try:
            record({"type": "marker", "action": "go_back"})
            page.go_back(wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2500)
            record({"type": "marker", "action": "after_back", "page_url": _safe_url_summary(getattr(page, "url", ""))})
            click_consent_if_present()
        except Exception as exc:
            record({"type": "marker", "action": "go_back_failed", "error": _safe_error_summary(exc)})

        record({"type": "marker", "action": "reopen_activation_link", "url": _safe_url_summary(activation_link_url)})
        page.goto(activation_link_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)
        record({"type": "marker", "action": "after_reopen", "page_url": _safe_url_summary(getattr(page, "url", ""))})
        click_consent_if_present()
    except Exception as exc:
        result["error"] = _safe_error_summary(exc)
        record({"type": "marker", "action": "capture_failed", "error": _safe_error_summary(exc)})
    finally:
        result["events"] = len(events)
        payload = {
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "activation_link": _safe_url_summary(activation_link_url),
            "reference": _mask_log_value(reference_id),
            "events": events,
        }
        try:
            capture_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info(
                "[gopay_executor] GoPay auth network capture saved: path=%s events=%s",
                capture_path,
                len(events),
            )
        except Exception as exc:
            result["write_error"] = _safe_error_summary(exc)
        try:
            if page is not getattr(api, "page", None):
                page.close()
        except Exception:
            pass
    return result


def _browser_checkout_to_gopay_redirect(
    api: ChatGPTTeamAPI,
    *,
    access_token: str,
    checkout_ui_mode: str = "custom",
    session_token: str = "",
    cookie_header: str = "",
    checkout_url: str = "",
    raw_checkout: dict | None = None,
    email: str = "",
    account_id: str = "",
    device_id: str = "",
    billing: dict,
    session_id: str,
    screenshot_paths: list[str],
    proxy_url: str | None = None,
    proxy_bypass: str | None = None,
    progress: Callable[..., None] | None = None,
) -> dict:
    if callable(progress):
        progress("chatgpt_checkout_browser_handoff")
    if not getattr(api, "browser", None):
        api.account_id = account_id or getattr(api, "account_id", "")
        api.oai_device_id = device_id or getattr(api, "oai_device_id", "") or str(uuid.uuid4())
        api._launch_browser(proxy_url=proxy_url, proxy_bypass=proxy_bypass)
        _inject_chatgpt_browser_cookies(
            api,
            session_token=session_token,
            cookie_header=cookie_header,
            account_id=account_id,
            device_id=device_id,
        )

    captured: dict[str, Any] = {"redirect_url": "", "snap_token": "", "rate_limited": "", "rate_limited_count": 0}

    def remember_from_obj(obj):
        try:
            _remember_gopay_redirect_url(getattr(obj, "url", ""), captured)
        except Exception:
            pass

    def remember_response(obj):
        remember_from_obj(obj)
        try:
            status = int(getattr(obj, "status", 0) or 0)
        except Exception:
            status = 0
        if status == 429:
            url = str(getattr(obj, "url", "") or "")
            captured["rate_limited"] = f"HTTP 429 {_safe_url_summary(url)}"
            captured["rate_limited_count"] = int(captured.get("rate_limited_count") or 0) + 1
            logger.info(
                "[gopay_executor] browser checkout observed HTTP 429, will retry submit: url=%s count=%s",
                _safe_url_summary(url),
                captured["rate_limited_count"],
            )

    def on_popup(page):
        try:
            page.on("request", remember_from_obj)
            page.on("response", remember_response)
            page.on("framenavigated", remember_from_obj)
        except Exception:
            pass

    try:
        api.context.on("page", on_popup)
        api.page.on("request", remember_from_obj)
        api.page.on("response", remember_response)
        api.page.on("framenavigated", remember_from_obj)
    except Exception:
        pass

    home_ready = _goto_with_retry(api.page, "https://chatgpt.com/", wait_until="domcontentloaded", timeout=60000, attempts=3)
    if home_ready:
        try:
            api.page.wait_for_timeout(2500)
        except Exception:
            time.sleep(2.5)
        _log_browser_auth_session_diag(api, label="home")
        _select_chatgpt_account_if_needed(api, email=email)
    else:
        logger.info(
            "[gopay_executor] home warmup failed, continuing with checkout URL directly: current=%s body=%s",
            _safe_url_summary(getattr(api.page, "url", "")),
            _compact_log_text(_body_excerpt(api, 300), limit=180),
        )
    checkout_url = str(checkout_url or "").strip()
    raw_checkout = raw_checkout if isinstance(raw_checkout, dict) else {}
    if not checkout_url:
        if not home_ready:
            raise GoPayFlowError("浏览器首页预热失败，且没有可直接打开的 checkout URL", stage="browser_checkout")
        checkout_meta = _generate_id_checkout_in_page(api, access_token, checkout_ui_mode=checkout_ui_mode)
        checkout_url = str(checkout_meta.get("url") or "").strip()
        raw_checkout = checkout_meta.get("raw") if isinstance(checkout_meta.get("raw"), dict) else {}
    checkout_session_id = _extract_checkout_session_id(checkout_url, raw_checkout)
    processor_entity = _extract_processor_entity(raw_checkout)
    if not checkout_url or not checkout_session_id:
        raise GoPayFlowError(f"浏览器生成 checkout 失败: {checkout_meta}", stage="generate_checkout")
    logger.info("[gopay_executor] browser checkout fallback generated checkout: %s", _safe_url_summary(checkout_url))

    if callable(progress):
        progress("open_checkout", checkout_url=checkout_url)
    if not _open_checkout_in_page(api, checkout_url, email=email):
        _capture_screenshot(api, session_id, "gopay-browser-checkout-open-failed", screenshot_paths)
        raise GoPayFlowError("浏览器打开 checkout 页面失败", stage="browser_checkout")
    if callable(progress):
        progress("checkout_opened", checkout_url=checkout_url)

    nonzero_hint = _browser_checkout_nonzero_amount_hint(api)
    if nonzero_hint and not _env_truthy("GOPAY_ALLOW_NONZERO_CHARGE"):
        _capture_screenshot(api, session_id, "gopay-browser-nonzero-amount-blocked", screenshot_paths)
        raise GoPayChargeBlocked(
            (
                f"浏览器 checkout 页面今日应付金额非 0 ({nonzero_hint})，已在填写账单前停止；"
            ),
            stage="browser_charge_guard",
        )

    def guard_checkout_due_amount(*, where: str):
        amount_hint = _browser_checkout_nonzero_amount_hint(api)
        if amount_hint and not _env_truthy("GOPAY_ALLOW_NONZERO_CHARGE"):
            _capture_screenshot(api, session_id, f"gopay-browser-nonzero-amount-blocked-{where}", screenshot_paths)
            raise GoPayChargeBlocked(
                (
                    f"浏览器 checkout 页面今日应付金额非 0 ({amount_hint})，已在填写账单前停止；"
                ),
                stage="browser_charge_guard",
            )

    if callable(progress):
        progress("select_gopay")
    selected, select_error = _select_gopay_option(api)
    if not selected:
        logger.info("[gopay_executor] browser checkout fallback did not explicitly select GoPay: %s", select_error)
    else:
        if callable(progress):
            progress("gopay_selected")
        guard_checkout_due_amount(where="after-gopay-select")
    ok, fill_error = _fill_billing_form_on_page(api, billing, session_id, screenshot_paths, progress=progress)
    if not ok:
        raise GoPayFlowError(f"浏览器填写 checkout 账单地址失败: {fill_error}", stage="browser_checkout")
    guard_checkout_due_amount(where="after-billing-fill")
    _accept_checkout_terms_on_page(api, progress=progress)

    submit_selectors = [
        'button:has-text("Subscribe")',
        'button:has-text("Pay")',
        'button:has-text("订阅")',
        'button[type="submit"]',
    ]
    submit_attempt = 0
    next_submit_at = 0.0
    submit_retry_delay = _env_float("GOPAY_BROWSER_SUBMIT_RETRY_SECONDS", 4.0)
    max_submit_attempts = max(1, int(_env_float("GOPAY_BROWSER_SUBMIT_RETRY_ATTEMPTS", 10)))
    max_address_retry_attempts = max(0, int(_env_float("GOPAY_BROWSER_ADDRESS_RETRY_ATTEMPTS", 2)))
    address_retry_attempts = 0
    last_click_error = ""
    deadline = time.time() + 90
    last_error = ""
    handled_rate_limited_count = 0
    while time.time() < deadline:
        if submit_attempt < max_submit_attempts and time.time() >= next_submit_at:
            submit_attempt += 1
            ok, click_error = _click(
                api,
                submit_selectors,
                "提交订阅按钮",
                timeout_ms=12000 if submit_attempt == 1 else 5000,
            )
            if not ok:
                last_click_error = click_error
                logger.info(
                    "[gopay_executor] browser checkout submit click failed: attempt=%s/%s error=%s",
                    submit_attempt,
                    max_submit_attempts,
                    _safe_error_summary(click_error),
                )
                if submit_attempt >= max_submit_attempts:
                    _capture_screenshot(api, session_id, "gopay-browser-submit-click-failed", screenshot_paths)
                    raise GoPayFlowError(f"浏览器提交 checkout 失败: {click_error}", stage="browser_checkout")
            else:
                if callable(progress):
                    progress("submit_clicked", mode="browser", attempt=submit_attempt, max_attempts=max_submit_attempts)
            next_submit_at = time.time() + max(3.0, submit_retry_delay)

        try:
            for page in list(getattr(api.context, "pages", []) or []):
                _remember_gopay_redirect_url(getattr(page, "url", ""), captured)
        except Exception:
            pass
        if captured.get("redirect_url") or captured.get("snap_token"):
            logger.info(
                "[gopay_executor] browser checkout fallback captured redirect: redirect=%s snap_token=%s",
                _safe_url_summary(captured.get("redirect_url")),
                _mask_log_value(captured.get("snap_token")),
            )
            try:
                api.page.evaluate("() => window.stop()")
            except Exception:
                pass
            return {
                "checkout_url": checkout_url,
                "checkout_session_id": checkout_session_id,
                "processor_entity": processor_entity,
                "redirect_url": captured.get("redirect_url", ""),
                "snap_token": captured.get("snap_token", ""),
            }
        rate_limited_count = int(captured.get("rate_limited_count") or 0)
        if rate_limited_count > handled_rate_limited_count:
            handled_rate_limited_count = rate_limited_count
            rate_limited_error = str(captured.get("rate_limited") or "HTTP 429")
            last_error = rate_limited_error
            logger.info(
                "[gopay_executor] browser checkout submit hit rate limit, retrying current checkout account: attempt=%s/%s reason=%s",
                submit_attempt,
                max_submit_attempts,
                _compact_log_text(rate_limited_error, limit=180),
            )
            if submit_attempt < max_submit_attempts:
                if callable(progress):
                    progress(
                        "submit_retry",
                        attempt=submit_attempt + 1,
                        max_attempts=max_submit_attempts,
                        reason=rate_limited_error,
                    )
                next_submit_at = min(next_submit_at, time.time() + max(3.0, submit_retry_delay))
                try:
                    api.page.wait_for_timeout(500)
                except Exception:
                    time.sleep(0.5)
                continue
            break
        error = _extract_checkout_error(api)
        if error:
            last_error = error
            logger.info("[gopay_executor] browser checkout fallback checkout error: %s", error)
            if _is_checkout_rate_limited_error(error):
                if submit_attempt < max_submit_attempts:
                    if callable(progress):
                        progress(
                            "submit_retry",
                            attempt=submit_attempt + 1,
                            max_attempts=max_submit_attempts,
                            reason=error,
                        )
                    next_submit_at = min(next_submit_at, time.time() + max(3.0, submit_retry_delay))
                    try:
                        api.page.wait_for_timeout(500)
                    except Exception:
                        time.sleep(0.5)
                    continue
                break
            if _is_checkout_payment_not_approved_error(error):
                _capture_screenshot(api, session_id, "gopay-browser-payment-not-approved", screenshot_paths)
                raise GoPayFlowError(
                    f"付款未获批准，当前账号将从号池删除并停止本次账号尝试: {error}",
                    stage="checkout_not_approved",
                )
            if _is_checkout_customer_location_error(error):
                if address_retry_attempts >= max_address_retry_attempts:
                    _capture_screenshot(api, session_id, "gopay-browser-tax-address-retry-exhausted", screenshot_paths)
                    raise GoPayFlowError(
                        f"账单地址无法用于自动计算税费，已重试 {address_retry_attempts} 次仍失败: {error}",
                        stage="browser_checkout",
                    )
                address_retry_attempts += 1
                next_billing = _billing_address_for_tax_retry(address_retry_attempts)
                billing.clear()
                billing.update(next_billing)
                public_billing = _public_billing_info(billing)
                logger.info(
                    "[gopay_executor] checkout tax address rejected, retrying with replacement billing address: attempt=%s/%s billing=%s error=%s",
                    address_retry_attempts,
                    max_address_retry_attempts,
                    public_billing,
                    _compact_log_text(error, limit=180),
                )
                if callable(progress):
                    progress(
                        "billing_address_retry",
                        attempt=address_retry_attempts,
                        max_attempts=max_address_retry_attempts,
                        billing_info=public_billing,
                        reason=error,
                    )
                ok, fill_error = _fill_billing_form_on_page(api, billing, session_id, screenshot_paths, progress=progress)
                if not ok:
                    _capture_screenshot(api, session_id, "gopay-browser-tax-address-refill-failed", screenshot_paths)
                    raise GoPayFlowError(
                        f"税费地址重试时填写新账单地址失败: {fill_error}",
                        stage="browser_checkout",
                    )
                _accept_checkout_terms_on_page(api, progress=progress)
                submit_attempt = 0
                next_submit_at = 0.0
                last_error = ""
                continue
        try:
            api.page.wait_for_timeout(500)
        except Exception:
            time.sleep(0.5)

    _capture_screenshot(api, session_id, "gopay-browser-redirect-timeout", screenshot_paths)
    raise GoPayFlowError(
        f"浏览器 checkout 未捕获到 Stripe/Midtrans 跳转: {last_error or last_click_error or _body_excerpt(api, 500)}",
        stage="browser_checkout",
    )


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


class GoPayHttpCharger:
    """Stripe -> Midtrans -> GoPay tokenization flow.

    ChatGPT/Stripe/Midtrans/GoPay calls are plain HTTP. The production GoPay
    path does not open the GoPay authorize page; SMS OTP is first switched via
    /v1/linking/user-consent otp_channel=sms, then falls back to resend-otp.
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
        otp_channel: str = "sms",
        sms_resend_wait_seconds: float | None = None,
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
        self.otp_channel = str(otp_channel or "sms").strip().lower()
        self._auth_network_capture_done = False
        self.sms_resend_wait_seconds = (
            _env_float("GOPAY_SMS_OTP_DELAY_SECONDS", GOPAY_SMS_OTP_DELAY_S)
            if sms_resend_wait_seconds is None
            else float(sms_resend_wait_seconds or 0)
        )
        self.is_cancelled = is_cancelled
        self.progress_callback = progress_callback
        self.expected_due_amount: int | None = None
        self.expected_due_currency = ""
        self._stripe_expected_due_checked = False
        self.activation_link_url = ""

    def _progress(self, stage: str, **extra):
        _emit_gopay_progress(self.progress_callback, stage, **extra)

    def _check_cancelled(self):
        if callable(self.is_cancelled) and self.is_cancelled():
            raise GoPayFlowError("任务已取消", stage="cancelled")

    def _sleep_with_cancel(self, seconds: float):
        deadline = time.time() + max(0.0, float(seconds or 0))
        while time.time() < deadline:
            self._check_cancelled()
            time.sleep(min(1.0, max(0.0, deadline - time.time())))

    def _request(self, method: str, url: str, *, stage: str, **kwargs):
        func = getattr(self.http, method.lower())
        timeout = kwargs.pop("timeout", HTTP_TIMEOUT_SECONDS)
        attempts = _transient_http_retry_attempts(stage)
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            self._check_cancelled()
            try:
                logger.info(
                    "[gopay_executor] HTTP request: stage=%s method=%s attempt=%s/%s timeout=%s url=%s",
                    stage,
                    method.upper(),
                    attempt,
                    attempts,
                    timeout,
                    _safe_url_summary(url),
                )
                resp = func(url, timeout=timeout, **kwargs)
                logger.info(
                    "[gopay_executor] HTTP response: stage=%s status=%s url=%s",
                    stage,
                    getattr(resp, "status_code", "?"),
                    _safe_url_summary(url),
                )
                return resp
            except Exception as exc:
                last_exc = exc
                transient_error = _is_transient_http_error(exc)
                if not transient_error:
                    raise
                if attempt >= attempts:
                    raise GoPayFlowError(
                        f"{stage} 网络请求失败: {_safe_error_summary(exc)}",
                        stage=stage,
                    ) from exc
                logger.info(
                    "[gopay_executor] transient HTTP error at %s, retry %s/%s: %s",
                    stage,
                    attempt + 1,
                    attempts,
                    _safe_error_summary(exc),
                )
                wait_seconds = _transient_http_retry_sleep_seconds(stage, attempt)
                self._progress(
                    f"{stage}_retry",
                    attempt=attempt,
                    next_attempt=attempt + 1,
                    max_attempts=attempts,
                    wait_seconds=wait_seconds,
                    reason=_safe_error_summary(exc),
                )
                self._sleep_with_cancel(wait_seconds)
        raise last_exc or GoPayFlowError(f"{stage} HTTP 请求失败", stage=stage)

    def _stripe_create_payment_method(self, checkout_session_id: str, stripe_pk: str, init_ctx: dict | None = None) -> str:
        self._progress("stripe_create_payment_method")
        billing = self.billing_info
        init_ctx = init_ctx or {}
        runtime = _stripe_runtime_from_env()
        runtime.update({k: v for k, v in self.runtime.items() if v})
        runtime_version = runtime.get("version") or DEFAULT_STRIPE_RUNTIME_VERSION
        stripe_js_id = init_ctx.get("stripe_js_id") or str(uuid.uuid4())
        elements_session_id = init_ctx.get("elements_session_id") or f"elements_session_{uuid.uuid4().hex[:11]}"
        elements_session_config_id = init_ctx.get("elements_session_config_id") or str(uuid.uuid4())
        checkout_config_id = init_ctx.get("payment_method_checkout_config_id") or init_ctx.get("config_id") or ""
        data = {
            "billing_details[name]": billing.get("name") or "John Doe",
            "billing_details[email]": billing.get("email") or "buyer@example.com",
            "billing_details[address][country]": billing.get("country") or "US",
            "billing_details[address][line1]": billing.get("address1") or "3110 Sunset Boulevard",
            "billing_details[address][city]": billing.get("city") or "Los Angeles",
            "billing_details[address][postal_code]": billing.get("zip") or "90026",
            "billing_details[address][state]": billing.get("state") or "CA",
            "type": "gopay",
            "payment_user_agent": f"stripe.js/{runtime_version}; stripe-js-v3/{runtime_version}; payment-element; deferred-intent",
            "referrer": "https://chatgpt.com",
            "time_on_page": str(random.randint(25000, 55000)),
            "client_attribution_metadata[client_session_id]": stripe_js_id,
            "client_attribution_metadata[checkout_session_id]": checkout_session_id,
            "client_attribution_metadata[checkout_config_id]": checkout_config_id,
            "client_attribution_metadata[elements_session_id]": elements_session_id,
            "client_attribution_metadata[elements_session_config_id]": elements_session_config_id,
            "client_attribution_metadata[merchant_integration_source]": "elements",
            "client_attribution_metadata[merchant_integration_subtype]": "payment-element",
            "client_attribution_metadata[merchant_integration_version]": "2021",
            "client_attribution_metadata[payment_intent_creation_flow]": "deferred",
            "client_attribution_metadata[payment_method_selection_flow]": "automatic",
            "client_attribution_metadata[merchant_integration_additional_elements][0]": "payment",
            "client_attribution_metadata[merchant_integration_additional_elements][1]": "address",
            "guid": init_ctx.get("guid") or uuid.uuid4().hex,
            "muid": init_ctx.get("muid") or uuid.uuid4().hex,
            "sid": init_ctx.get("sid") or uuid.uuid4().hex,
            "_stripe_version": STRIPE_VERSION_FULL,
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
        url = f"{STRIPE_API}/v1/payment_pages/{checkout_session_id}/init"

        STRIPE_VERSION_BASE = "2025-03-31.basil"
        # 先用基础版本，失败再用完整版本
        for version, include_betas in [
            (STRIPE_VERSION_BASE, False),
            (STRIPE_VERSION_FULL, True),
        ]:
            data = {
                "browser_locale": "en-US",
                "browser_timezone": "Asia/Shanghai",
                "elements_session_client[elements_init_source]": "custom_checkout",
                "elements_session_client[referrer_host]": "chatgpt.com",
                "elements_session_client[stripe_js_id]": stripe_js_id,
                "elements_session_client[locale]": "en",
                "elements_session_client[is_aggregation_expected]": "false",
                "_stripe_version": version,
                "key": stripe_pk,
            }
            if include_betas:
                data["elements_session_client[client_betas][0]"] = "custom_checkout_server_updates_1"
                data["elements_session_client[client_betas][1]"] = "custom_checkout_manual_approval_1"
                data.update(elements_options)

            resp = self._request("post", url, data=data, stage="stripe_init")
            status_code = int(getattr(resp, "status_code", 0) or 0)
            if status_code == 200:
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
                    "elements_options_client": elements_options if include_betas else {},
                    "config_id": str(payload.get("config_id") or ""),
                    "expected_amount": self._checkout_amount(payload),
                    "currency": str(payload.get("currency") or "idr").lower(),
                    "return_url": str(payload.get("return_url") or ""),
                    "stripe_hosted_url": str(payload.get("stripe_hosted_url") or ""),
                    "stripe_version": version,
                }
            if status_code == 400:
                text = str(getattr(resp, "text", "") or "").lower()
                if "beta" in text or "parameter_unknown" in text:
                    logger.info("[gopay] stripe_init version=%s rejected, trying next...", version[:30])
                    continue
            _ensure_ok(resp, "stripe_init")

        raise GoPayFlowError("Stripe init 失败: 所有 API 版本均不可用", stage="stripe_init")

    def _stripe_elements_session(self, checkout_session_id: str, stripe_pk: str, init_ctx: dict) -> dict:
        self._progress("stripe_elements_session")
        amount = init_ctx.get("expected_amount")
        if amount is None:
            amount = "0"
        currency = str(init_ctx.get("currency") or "idr").lower()
        locale = str(init_ctx.get("locale") or "en")
        effective_version = init_ctx.get("stripe_version") or STRIPE_VERSION_FULL
        params = {
            "deferred_intent[mode]": "subscription",
            "deferred_intent[amount]": str(int(_parse_amount(amount) or 0)),
            "deferred_intent[currency]": currency,
            "deferred_intent[setup_future_usage]": "off_session",
            "deferred_intent[payment_method_types][0]": "gopay",
            "currency": currency,
            "key": stripe_pk,
            "_stripe_version": effective_version,
            "elements_init_source": "custom_checkout",
            "referrer_host": "chatgpt.com",
            "stripe_js_id": init_ctx["stripe_js_id"],
            "locale": locale,
            "type": "deferred_intent",
            "checkout_session_id": checkout_session_id,
        }
        if "checkout_server_update_beta" in effective_version:
            params["client_betas[0]"] = "custom_checkout_server_updates_1"
            params["client_betas[1]"] = "custom_checkout_manual_approval_1"
        resp = self._request("get", f"{STRIPE_API}/v1/elements/sessions", params=params, stage="stripe_elements_session")
        if resp.status_code != 200:
            logger.info(
                "[gopay_executor] Stripe elements/sessions skipped: HTTP %s %s",
                resp.status_code,
                _compact_log_text(resp.text or "", limit=160),
            )
            return {}
        payload = _response_json(resp, "stripe_elements_session")
        real_session_id = str(payload.get("session_id") or payload.get("id") or "")
        if real_session_id:
            init_ctx["elements_session_id"] = real_session_id
        if payload.get("config_id"):
            init_ctx["config_id"] = str(payload.get("config_id") or "")
        if payload.get("payment_method_checkout_config_id"):
            init_ctx["payment_method_checkout_config_id"] = str(payload.get("payment_method_checkout_config_id") or "")
        if payload.get("elements_session_config_id"):
            init_ctx["elements_session_config_id"] = str(payload.get("elements_session_config_id") or "")
        logger.info(
            "[gopay_executor] Stripe elements/sessions ready: session_id_present=%s config_id_present=%s",
            bool(real_session_id),
            bool(init_ctx.get("config_id")),
        )
        return payload

    def _stripe_update_payment_page_address(self, checkout_session_id: str, stripe_pk: str, init_ctx: dict) -> None:
        self._progress("stripe_address_update")
        billing = self.billing_info
        effective_version = init_ctx.get("stripe_version") or STRIPE_VERSION_FULL
        base = {
            "elements_session_client[elements_init_source]": "custom_checkout",
            "elements_session_client[referrer_host]": "chatgpt.com",
            "elements_session_client[session_id]": init_ctx.get("elements_session_id") or f"elements_session_{uuid.uuid4().hex[:11]}",
            "elements_session_client[stripe_js_id]": init_ctx.get("stripe_js_id") or str(uuid.uuid4()),
            "elements_session_client[locale]": init_ctx.get("locale") or "en",
            "elements_session_client[is_aggregation_expected]": "false",
            "client_attribution_metadata[merchant_integration_additional_elements][0]": "payment",
            "client_attribution_metadata[merchant_integration_additional_elements][1]": "address",
            "key": stripe_pk,
            "_stripe_version": effective_version,
        }
        if "checkout_server_update_beta" in effective_version:
            base["elements_session_client[client_betas][0]"] = "custom_checkout_server_updates_1"
            base["elements_session_client[client_betas][1]"] = "custom_checkout_manual_approval_1"
        base.update(init_ctx.get("elements_options_client") or {})
        steps = [
            ("country", {"tax_region[country]": str(billing.get("country") or "US").strip() or "US"}),
            ("focus", {}),
            ("line1", {"tax_region[line1]": str(billing.get("address1") or "3110 Sunset Boulevard").strip()}),
            ("city", {"tax_region[city]": str(billing.get("city") or "Los Angeles").strip()}),
            ("state", {"tax_region[state]": str(billing.get("state") or "CA").strip()}),
            ("postal_code", {"tax_region[postal_code]": str(billing.get("zip") or "90026").strip()}),
        ]
        accumulated: dict[str, str] = {}
        for index, (field, fields) in enumerate(steps, 1):
            self._check_cancelled()
            accumulated.update({key: value for key, value in fields.items() if value})
            data = dict(base)
            data.update(accumulated)
            self._progress("stripe_address_update", field=field, attempt=index, total=len(steps))
            resp = self._request(
                "post",
                f"{STRIPE_API}/v1/payment_pages/{checkout_session_id}",
                data=data,
                stage="stripe_address_update",
            )
            if resp.status_code != 200:
                raise GoPayFlowError(
                    f"Stripe 地址提交失败: step={field} HTTP {resp.status_code} {(resp.text or '')[:300]}",
                    stage="stripe_address_update",
                )
            self._sleep_with_cancel(random.uniform(0.2, 0.7))
        self._progress("stripe_address_update_done")

    def _stripe_confirm(self, checkout_session_id: str, payment_method_id: str, stripe_pk: str, init_ctx: dict | None = None) -> dict:
        self._progress("stripe_confirm")
        init_ctx = init_ctx or self._stripe_init(checkout_session_id, stripe_pk)
        self.expected_due_amount = _parse_amount(init_ctx.get("expected_amount"))
        self.expected_due_currency = "stripe"
        effective_version = init_ctx.get("stripe_version") or STRIPE_VERSION_FULL
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
            "_stripe_version": effective_version,
            "key": stripe_pk,
        }
        if "checkout_server_update_beta" in effective_version:
            data["elements_session_client[client_betas][0]"] = "custom_checkout_server_updates_1"
            data["elements_session_client[client_betas][1]"] = "custom_checkout_manual_approval_1"
        consent_collection = {}
        raw_init = init_ctx.get("raw")
        if isinstance(raw_init, dict):
            raw_consent_collection = raw_init.get("consent_collection")
            if isinstance(raw_consent_collection, dict):
                consent_collection = raw_consent_collection
        consent_behavior = init_ctx.get("include_terms_of_service_consent")
        if consent_behavior is None:
            consent_behavior = consent_collection.get("terms_of_service") not in (None, "", "none")
        if consent_behavior:
            data["consent[terms_of_service]"] = "accepted"
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
        if (
            resp.status_code == 400
            and "consent[terms_of_service]" not in data
            and "terms of service" in (resp.text or "").lower()
        ):
            self._progress("stripe_confirm_retry_terms")
            data["consent[terms_of_service]"] = "accepted"
            init_ctx["include_terms_of_service_consent"] = True
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

    @staticmethod
    def _confirm_requires_checkout_approval(payload: dict) -> bool:
        candidates = []
        for key in ("submission_attempt", "session"):
            obj = payload.get(key)
            if isinstance(obj, dict):
                candidates.append(obj)
                nested = obj.get("submission_attempt")
                if isinstance(nested, dict):
                    candidates.append(nested)
        payment_page = payload.get("payment_page")
        if isinstance(payment_page, dict):
            session = payment_page.get("session")
            if isinstance(session, dict):
                candidates.append(session)
                nested = session.get("submission_attempt")
                if isinstance(nested, dict):
                    candidates.append(nested)
        return any(str(candidate.get("state") or "") == "requires_approval" for candidate in candidates)

    @staticmethod
    def _confirm_state_summary(payload: dict) -> str:
        setup_intent = payload.get("setup_intent") if isinstance(payload.get("setup_intent"), dict) else {}
        payment_intent = payload.get("payment_intent") if isinstance(payload.get("payment_intent"), dict) else {}
        session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
        submission_attempt = payload.get("submission_attempt") if isinstance(payload.get("submission_attempt"), dict) else {}
        if not submission_attempt and isinstance(session.get("submission_attempt"), dict):
            submission_attempt = session["submission_attempt"]
        return (
            f"submission_attempt={submission_attempt.get('state')!r} "
            f"setup_intent={setup_intent.get('status')!r} "
            f"payment_intent={payment_intent.get('status')!r} "
            f"payment_status={payload.get('payment_status')!r} status={payload.get('status')!r}"
        )

    def _resolve_snap_token(self, checkout_session_id: str, stripe_pk: str) -> str:
        self._progress("resolve_midtrans_redirect")
        params = {
            "elements_session_client[elements_init_source]": "custom_checkout",
            "elements_session_client[referrer_host]": "chatgpt.com",
            "elements_session_client[session_id]": f"elements_session_{uuid.uuid4().hex[:11]}",
            "elements_session_client[stripe_js_id]": str(uuid.uuid4()),
            "elements_session_client[locale]": "en",
            "elements_session_client[is_aggregation_expected]": "false",
            "key": stripe_pk,
            "_stripe_version": "2025-03-31.basil",
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

    def _guard_stripe_expected_due(self):
        if self.expected_due_amount is None:
            return False
        if self.expected_due_amount <= 0:
            if not self._stripe_expected_due_checked:
                self._progress("stripe_zero_due_confirmed")
            self._stripe_expected_due_checked = True
            return True
        if _env_truthy("GOPAY_ALLOW_NONZERO_CHARGE"):
            return False
        self._stripe_expected_due_checked = True
        self._progress("stripe_nonzero_amount_blocked", expected_amount=str(self.expected_due_amount))
        raise GoPayChargeBlocked(
            (
                f"Stripe expected_amount={self.expected_due_amount} 非 0，已在 ChatGPT approve / GoPay 绑定前停止；"
            ),
            stage="stripe_charge_guard",
        )

    def _guard_before_gopay_binding(self, transaction: dict):
        if self._guard_stripe_expected_due():
            return
        amount, currency = self._midtrans_gross_amount(transaction)
        if amount > 0:
            logger.info(
                "[gopay_executor] Midtrans gross_amount=%s %s accepted; checkout 页面金额校验已在提交前完成",
                amount,
                currency or "IDR",
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
            logger.info(
                "[gopay_executor] Midtrans linking attempt: snap_token=%s attempt=%s/%s phone=%s",
                _mask_log_value(snap_token),
                attempt,
                GOPAY_LINK_RETRY_LIMIT + 1,
                _safe_phone_summary(self.phone_number, self.country_code),
            )
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
                logger.info(
                    "[gopay_executor] Midtrans linking succeeded: reference=%s activation=%s",
                    _mask_log_value(matched.group(1)),
                    _safe_url_summary(self.activation_link_url),
                )
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
                        _safe_error_summary(last_error),
                        GOPAY_LINK_RETRY_SLEEP_S,
                        attempt,
                        GOPAY_LINK_RETRY_LIMIT,
                    )
                    time.sleep(GOPAY_LINK_RETRY_SLEEP_S)
                    continue
                logger.info(
                    "[gopay_executor] Midtrans linking 406 (%s), retry %s/%s",
                    _safe_error_summary(last_error),
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
            logger.info("[gopay_executor] GoPay validate-reference returned rate-limit payload: %s", _safe_error_summary(payload))
            raise GoPayRateLimited(_gopay_rate_limited_message(), stage="gopay_rate_limited")
        if not payload.get("success"):
            raise GoPayFlowError(f"GoPay validate-reference 失败: {payload}", stage="gopay_validate_reference")
        logger.info("[gopay_executor] GoPay validate-reference succeeded: reference=%s", _mask_log_value(reference_id))

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
            logger.info("[gopay_executor] GoPay user-consent returned rate-limit payload: %s", _safe_error_summary(payload))
            raise GoPayRateLimited(_gopay_rate_limited_message(), stage="gopay_rate_limited")
        if not payload.get("success"):
            raise GoPayFlowError(f"GoPay user-consent 失败: {payload}", stage="gopay_user_consent")
        logger.info("[gopay_executor] GoPay user-consent succeeded: reference=%s", _mask_log_value(reference_id))

    def _gopay_switch_to_sms_otp(self, reference_id: str) -> bool:
        self._progress("gopay_sms_channel_switch")
        try:
            resp = self._request(
                "post",
                "https://gwa.gopayapi.com/v1/linking/user-consent",
                json={"reference_id": reference_id, "otp_channel": "sms"},
                headers={
                    "Origin": "https://merchants-gws-app.gopayapi.com",
                    "Referer": "https://merchants-gws-app.gopayapi.com/",
                    "x-user-locale": "en-US",
                },
                stage="gopay_sms_channel_switch",
            )
            _ensure_ok(resp, "gopay_sms_channel_switch")
            payload = _response_json(resp, "gopay_sms_channel_switch")
            if _looks_like_gopay_rate_limit_payload(payload):
                self._progress("gopay_rate_limited")
                logger.info("[gopay_executor] GoPay SMS channel switch returned rate-limit payload: %s", _safe_error_summary(payload))
                raise GoPayRateLimited(_gopay_rate_limited_message(), stage="gopay_rate_limited")
            if not payload.get("success"):
                raise GoPayFlowError(f"GoPay SMS channel switch 失败: {payload}", stage="gopay_sms_channel_switch")
        except GoPayRateLimited:
            raise
        except Exception as exc:
            reason = _safe_error_summary(exc)
            logger.info("[gopay_executor] GoPay SMS channel switch failed, falling back to resend-otp: %s", reason)
            self._progress("gopay_sms_channel_switch_failed", reason=reason)
            return False
        self._progress("gopay_sms_channel_switched")
        self._progress("sms_otp_triggered")
        logger.info("[gopay_executor] GoPay OTP switched to SMS via user-consent: reference=%s", _mask_log_value(reference_id))
        return True

    def _gopay_resend_otp(self, reference_id: str):
        self._progress("trigger_sms_otp")
        resp = self._request(
            "post",
            "https://gwa.gopayapi.com/v1/linking/resend-otp",
            json={"reference_id": reference_id},
            headers={
                "Origin": "https://merchants-gws-app.gopayapi.com",
                "Referer": "https://merchants-gws-app.gopayapi.com/",
                "x-user-locale": "en-US",
            },
            stage="trigger_sms_otp",
        )
        _ensure_ok(resp, "trigger_sms_otp")
        payload = _response_json(resp, "trigger_sms_otp")
        if _looks_like_gopay_rate_limit_payload(payload):
            self._progress("gopay_rate_limited")
            logger.info("[gopay_executor] GoPay resend-otp returned rate-limit payload: %s", _safe_error_summary(payload))
            raise GoPayRateLimited(_gopay_rate_limited_message(), stage="gopay_rate_limited")
        if not payload.get("success"):
            raise GoPayFlowError(f"GoPay resend-otp 失败: {payload}", stage="trigger_sms_otp")
        self._progress("sms_otp_triggered")
        logger.info("[gopay_executor] GoPay OTP triggered via protocol resend: reference=%s", _mask_log_value(reference_id))

    def _trigger_sms_provider_resend_before_gopay_otp(self) -> bool:
        callback = getattr(self.otp_provider, "_gopay_sms_provider_resend_callback", None)
        if self.otp_channel != "sms" or not callable(callback):
            return False
        try:
            callback()
            self._progress("sms_provider_resend_triggered", reason="before_gopay_otp")
            return True
        except Exception as exc:
            logger.info(
                "[gopay_executor] SMS provider resend before GoPay OTP failed: %s",
                _safe_error_summary(exc),
            )
            self._progress("sms_provider_resend_failed", reason=_safe_error_summary(exc))
            return False

    def _trigger_linking_otp_channel(self, reference_id: str):
        if self.otp_channel == "sms":
            wait_seconds = max(0.0, float(self.sms_resend_wait_seconds or 0))
            switch_enabled = _env_enabled("GOPAY_SMS_CHANNEL_SWITCH_ENABLED", True)
            switch_delay = max(
                0.0,
                _env_float(
                    "GOPAY_SMS_CHANNEL_SWITCH_DELAY_SECONDS",
                    min(GOPAY_SMS_CHANNEL_SWITCH_DELAY_S, wait_seconds),
                ),
            )
            if switch_enabled and switch_delay < wait_seconds:
                self._progress("wait_sms_channel_switch_window", wait_seconds=int(switch_delay))
                logger.info(
                    "[gopay_executor] waiting before GoPay SMS channel switch: reference=%s wait_seconds=%s",
                    _mask_log_value(reference_id),
                    int(switch_delay),
                )
                if switch_delay:
                    self._sleep_with_cancel(switch_delay)
                if self._trigger_sms_provider_resend_before_gopay_otp():
                    delay = max(0.0, _env_float("GOPAY_SMS_PROVIDER_RESEND_DELAY_SECONDS", 2.0))
                    if delay:
                        self._sleep_with_cancel(delay)
                if self._gopay_switch_to_sms_otp(reference_id):
                    return
                wait_seconds = max(0.0, wait_seconds - switch_delay)
            self._progress("wait_sms_otp_window", wait_seconds=int(wait_seconds))
            logger.info(
                "[gopay_executor] waiting before protocol SMS OTP resend: reference=%s wait_seconds=%s",
                _mask_log_value(reference_id),
                int(wait_seconds),
            )
            self._sleep_with_cancel(wait_seconds)
            if self._trigger_sms_provider_resend_before_gopay_otp():
                delay = max(0.0, _env_float("GOPAY_SMS_PROVIDER_RESEND_DELAY_SECONDS", 2.0))
                if delay:
                    self._sleep_with_cancel(delay)
            self._gopay_resend_otp(reference_id)
            return

        if callable(self.sms_otp_trigger_callback) and not self._auth_network_capture_done:
            self._progress("whatsapp_otp_trigger")
            self.sms_otp_trigger_callback(reference_id, self.activation_link_url)
            return
        self._progress("wait_whatsapp_otp")
        logger.info(
            "[gopay_executor] GoPay OTP channel is WhatsApp; waiting for WhatsApp listener without protocol resend: reference=%s",
            _mask_log_value(reference_id),
        )

    def _gopay_validate_otp(self, reference_id: str, otp: str) -> tuple[str, str]:
        self._progress("gopay_validate_otp")
        resp = self._request(
            "post",
            "https://gwa.gopayapi.com/v1/linking/validate-otp",
            json={"reference_id": reference_id, "otp": otp},
            headers={"Origin": "https://merchants-gws-app.gopayapi.com", "Referer": "https://merchants-gws-app.gopayapi.com/"},
            stage="gopay_validate_otp",
        )
        status_code = int(getattr(resp, "status_code", 0) or 0)
        if status_code >= 400:
            try:
                payload = _response_json(resp, "gopay_validate_otp")
            except GoPayFlowError:
                payload = {}
            if _looks_like_gopay_invalid_otp_payload(payload):
                logger.info(
                    "[gopay_executor] GoPay validate-otp rejected invalid OTP: reference=%s otp=%s payload=%s",
                    _mask_log_value(reference_id),
                    _safe_otp_summary(otp),
                    _safe_error_summary(payload),
                )
                raise GoPayOTPInvalid(f"GoPay OTP 错误: {payload}", stage="gopay_validate_otp")
        _ensure_ok(resp, "gopay_validate_otp")
        payload = _response_json(resp, "gopay_validate_otp")
        if _looks_like_gopay_rate_limit_payload(payload):
            self._progress("gopay_rate_limited")
            logger.info("[gopay_executor] GoPay validate-otp returned rate-limit payload: %s", _safe_error_summary(payload))
            raise GoPayRateLimited(_gopay_rate_limited_message(), stage="gopay_rate_limited")
        if _looks_like_gopay_invalid_otp_payload(payload):
            raise GoPayOTPInvalid(f"GoPay OTP 错误: {payload}", stage="gopay_validate_otp")
        if not payload.get("success"):
            raise GoPayFlowError(f"GoPay OTP 校验失败: {payload}", stage="gopay_validate_otp")
        challenge = payload.get("data", {}).get("challenge", {}).get("action", {}).get("value", {})
        challenge_id = str(challenge.get("challenge_id") or "")
        client_id = str(challenge.get("client_id") or "")
        if not challenge_id or not client_id:
            raise GoPayFlowError(f"GoPay OTP 返回缺少 PIN challenge: {payload}", stage="gopay_validate_otp")
        logger.info(
            "[gopay_executor] GoPay validate-otp succeeded: reference=%s challenge_present=%s client_id_present=%s",
            _mask_log_value(reference_id),
            bool(challenge_id),
            bool(client_id),
        )
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
        init_ctx = self._stripe_init(checkout_session_id, stripe_pk)
        self.expected_due_amount = _parse_amount(init_ctx.get("expected_amount"))
        self.expected_due_currency = "stripe"
        self._guard_stripe_expected_due()
        self._stripe_elements_session(checkout_session_id, stripe_pk, init_ctx)
        self._stripe_update_payment_page_address(checkout_session_id, stripe_pk, init_ctx)
        payment_method_id = self._stripe_create_payment_method(checkout_session_id, stripe_pk, init_ctx=init_ctx)
        confirm_payload = self._stripe_confirm(checkout_session_id, payment_method_id, stripe_pk, init_ctx=init_ctx)
        self._guard_stripe_expected_due()
        confirm_redirect_url = self._extract_redirect_url(confirm_payload)
        if confirm_redirect_url:
            self._progress("resolve_midtrans_redirect", source="stripe_confirm")
            logger.info(
                "[gopay_executor] Stripe confirm returned redirect, skip ChatGPT approve: %s",
                _safe_url_summary(confirm_redirect_url),
            )
            snap_token = self._fetch_pm_redirect_snap_token(confirm_redirect_url)
        else:
            if self._confirm_requires_checkout_approval(confirm_payload):
                logger.info(
                    "[gopay_executor] Stripe confirm requires ChatGPT approve: %s",
                    self._confirm_state_summary(confirm_payload),
                )
                self._approve_checkout(checkout_session_id)
            else:
                logger.info(
                    "[gopay_executor] Stripe confirm did not explicitly require ChatGPT approve, resolving redirect: %s",
                    self._confirm_state_summary(confirm_payload),
                )
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
        self._guard_before_gopay_binding(transaction)
        reference_id = self._midtrans_init_linking(snap_token)
        if (
            self.otp_channel == "whatsapp"
            and _env_truthy("GOPAY_CAPTURE_AUTH_NETWORK")
            and callable(self.sms_otp_trigger_callback)
        ):
            self._progress("whatsapp_otp_trigger")
            self.sms_otp_trigger_callback(reference_id, self.activation_link_url)
            self._auth_network_capture_done = True
        self._gopay_validate_reference(reference_id)
        self._gopay_user_consent(reference_id)
        self._trigger_linking_otp_channel(reference_id)
        self._progress("wait_otp")
        if self.otp_channel == "sms":
            try:
                setattr(self.otp_provider, "_gopay_resend_callback", lambda: self._gopay_resend_otp(reference_id))
            except Exception:
                pass
        max_otp_attempts = max(1, _env_int("GOPAY_OTP_VALIDATE_ATTEMPTS", 3))
        invalid_otps: set[str] = set()
        challenge_id = ""
        client_id = ""
        last_invalid_exc: GoPayOTPInvalid | None = None
        for attempt in range(1, max_otp_attempts + 1):
            try:
                setattr(self.otp_provider, "_gopay_ignored_otps", set(invalid_otps))
            except Exception:
                pass
            otp = self.otp_provider()
            if not otp:
                raise GoPayOTPCancelled("未获取到 GoPay OTP", stage="fetch_otp")
            self._progress("otp_received", otp=_safe_otp_summary(otp), attempt=attempt, max_attempts=max_otp_attempts)
            try:
                challenge_id, client_id = self._gopay_validate_otp(reference_id, otp)
                break
            except GoPayOTPInvalid as exc:
                last_invalid_exc = exc
                invalid_otps.add(str(otp).strip())
                self._progress(
                    "otp_invalid",
                    otp=_safe_otp_summary(otp),
                    attempt=attempt,
                    max_attempts=max_otp_attempts,
                )
                if attempt >= max_otp_attempts:
                    raise GoPayOTPInvalid(
                        f"GoPay OTP 连续 {max_otp_attempts} 次错误，已停止重试",
                        stage="gopay_validate_otp",
                    ) from exc
                logger.info(
                    "[gopay_executor] GoPay OTP invalid, ignoring code and waiting for next one: reference=%s otp=%s attempt=%s/%s",
                    _mask_log_value(reference_id),
                    _safe_otp_summary(otp),
                    attempt,
                    max_otp_attempts,
                )
                continue
        if not challenge_id or not client_id:
            raise last_invalid_exc or GoPayOTPCancelled("未获取到可用 GoPay OTP", stage="fetch_otp")
        pin_token = self._tokenize_pin(challenge_id, client_id)
        self._gopay_validate_pin(reference_id, pin_token)

        charge_ref = self._midtrans_create_charge(snap_token)
        self._gopay_payment_validate(charge_ref)
        charge_challenge_id, charge_client_id = self._gopay_payment_confirm(charge_ref)
        charge_pin_token = self._tokenize_pin(charge_challenge_id, charge_client_id)
        self._gopay_payment_process(charge_ref, charge_pin_token)
        self._progress("payment_completed")

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

TAX_RETRY_BILLING_ADDRESSES = (
    DEFAULT_BILLING_ADDRESS,
    {
        "name": "John Doe",
        "country": "US",
        "state": "NY",
        "city": "New York",
        "zip": "10118",
        "address1": "350 5th Avenue",
        "address2": "",
        "phone_number": "212-555-0182",
    },
)


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


def _flatten_address_fields(value, prefix: str = "") -> dict[str, str]:
    fields: dict[str, str] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            next_key = f"{prefix}_{key}" if prefix else str(key)
            fields.update(_flatten_address_fields(item, next_key))
        return fields
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            fields.update(_flatten_address_fields(item, f"{prefix}_{index}"))
        return fields
    if prefix:
        fields[prefix] = str(value or "").strip()
    return fields


def _address_field(address: dict, *names: str) -> str:
    normalized = {
        re.sub(r"[^a-z0-9]+", "", str(key or "").lower()): value
        for key, value in _flatten_address_fields(address).items()
    }
    for name in names:
        key = re.sub(r"[^a-z0-9]+", "", str(name or "").lower())
        value = str(normalized.get(key) or "").strip()
        if value:
            return value
    for name in names:
        key = re.sub(r"[^a-z0-9]+", "", str(name or "").lower())
        for candidate_key, value in normalized.items():
            if candidate_key.endswith(key):
                text = str(value or "").strip()
                if text:
                    return text
    return ""


def _fetch_random_billing_address() -> dict:
    try:
        http = _new_http_session(require_curl_cffi=False)
        resp = http.post(
            "https://www.meiguodizhi.com/api/v1/dz",
            json={"path": "/", "method": "address"},
            headers={
                "Content-Type": "application/json",
                "Origin": "http://localhost:5173",
                "Referer": "https://www.meiguodizhi.com/",
            },
            timeout=30,
            verify=False,
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
    result = {
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
    card_number = _address_field(
        address,
        "Card_Number",
        "CardNumber",
        "Credit_Card_Number",
        "CreditCardNumber",
        "Credit Card Number",
        "CC Number",
        "CCNumber",
    )
    card_expiry = _address_field(
        address,
        "Expiry",
        "Expiry_Date",
        "ExpiryDate",
        "Exp_Date",
        "ExpDate",
        "Expires",
        "Expiration",
        "Expiration_Date",
        "ExpirationDate",
        "Credit_Card_Expiry",
        "CreditCardExpiry",
        "Credit Card Expiry",
    )
    if not card_expiry:
        expiry_month = _address_field(address, "Expiry_Month", "Exp_Month", "Expiration_Month")
        expiry_year = _address_field(address, "Expiry_Year", "Exp_Year", "Expiration_Year")
        if expiry_month and expiry_year:
            card_expiry = f"{expiry_month}/{expiry_year}"
    card_cvv = _address_field(address, "CVV", "CVV2", "CVC", "Security_Code", "Credit_Card_CVV", "Credit Card CVV")
    if card_number:
        result["card_number"] = card_number
    if card_expiry:
        result["card_expiry"] = card_expiry
    if card_cvv:
        result["card_cvv"] = card_cvv
    return result


def _billing_address_for_tax_retry(attempt: int) -> dict:
    index = max(0, min(attempt - 1, len(TAX_RETRY_BILLING_ADDRESSES) - 1))
    return dict(TAX_RETRY_BILLING_ADDRESSES[index])


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
        if not getattr(api, "_address_autocomplete_dismiss_logged", False):
            logger.info("[gopay_executor] 已关闭地址自动推荐，改为手动填写城市/州/邮编")
            setattr(api, "_address_autocomplete_dismiss_logged", True)
    except Exception as exc:
        logger.debug("[gopay_executor] 关闭地址自动推荐失败: %s", exc)


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
                    _safe_url_summary(frame_url),
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
            _safe_url_summary(frame_url),
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

def _fill_billing_form_on_page(
    api: ChatGPTTeamAPI,
    billing: dict,
    session_id: str,
    screenshot_paths: list[str],
    progress: Callable[..., None] | None = None,
):
    if callable(progress):
        progress("fill_billing_info")
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
        if callable(progress):
            progress("billing_fill_field", field=label)
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
        if callable(progress):
            progress("billing_select_field", field=label)
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
            if callable(progress):
                progress("billing_field_verified", field=label)
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
    if callable(progress):
        progress("billing_info_filled")
    return True, ""


def _accept_checkout_terms_on_page(api: ChatGPTTeamAPI, progress: Callable[..., None] | None = None) -> int:
    if callable(progress):
        progress("accept_checkout_terms")
    def _is_checked(locator) -> bool:
        try:
            return bool(locator.is_checked(timeout=500))
        except Exception:
            pass
        try:
            value = str(locator.get_attribute("aria-checked", timeout=500) or "").strip().lower()
            return value == "true"
        except Exception:
            return False

    total = 0
    for frame in _iter_page_frames(api):
        try:
            locator = frame.locator('input[type="checkbox"], [role="checkbox"]')
            count = locator.count()
        except Exception:
            continue
        for index in range(count):
            checkbox = locator.nth(index)
            try:
                if not checkbox.is_visible(timeout=500) or checkbox.is_disabled(timeout=500) or _is_checked(checkbox):
                    continue
            except Exception:
                continue
            try:
                checkbox.scroll_into_view_if_needed(timeout=1500)
            except Exception:
                pass
            checked = False
            try:
                checkbox.check(timeout=2500, force=True)
                checked = _is_checked(checkbox)
            except Exception:
                checked = False
            if not checked:
                try:
                    checkbox.click(timeout=2500, force=True)
                    time.sleep(0.2)
                    checked = _is_checked(checkbox)
                except Exception:
                    checked = False
            if not checked:
                try:
                    handle = checkbox.element_handle(timeout=1000)
                    if handle:
                        frame.evaluate(
                            """(node) => {
                              node.checked = true;
                              node.setAttribute('aria-checked', 'true');
                              node.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
                              node.dispatchEvent(new Event('input', { bubbles: true }));
                              node.dispatchEvent(new Event('change', { bubbles: true }));
                            }""",
                            handle,
                        )
                        time.sleep(0.2)
                        checked = _is_checked(checkbox)
                except Exception:
                    checked = False
            if checked:
                total += 1
    if total:
        logger.info("[gopay_executor] 已勾选 checkout 条款 checkbox: count=%s", total)
        if callable(progress):
            progress("checkout_terms_accepted", count=total)
    else:
        logger.info("[gopay_executor] checkout 页面未发现需要勾选的条款 checkbox")
    return total


def _dedupe_codes(codes: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for code in codes:
        normalized = str(code or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


_SMS_CODE_PATTERN = re.compile(r"(?<!\d)(\d{5,8})(?!\d)")
_SMS_DIRECT_CODE_PATTERN = re.compile(r"\s*#?(\d{5,8})\s*")
_SMS_STATUS_CODE_PATTERN = re.compile(r"(?i)\b(?:SMS[-_\s]?OK|OK)\b\D{0,20}(\d{5,8})(?!\d)")
_SMS_OTP_CONTEXT_PATTERN = re.compile(
    r"(?i)(otp|one[-\s]?time|verification|verify|security|auth(?:entication)?|"
    r"passcode|code|kode|验证码|驗證碼|认证码|認證碼|确认码|確認碼|校验码|驗證|验证|短信)"
)
_SMS_NON_OTP_NOTICE_PATTERN = re.compile(
    r"(?i)(thanks for confirming|transaction alerts|log in or get the app|"
    r"confirmed your phone|phone number has been confirmed)"
)
_SMS_URL_PATTERN = re.compile(r"(?i)\b(?:https?://|www\.)\S+")


def _extract_sms_codes(text: str) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []

    otp_keys = {
        "code",
        "otp",
        "sms_code",
        "verification_code",
        "verify_code",
        "verifycode",
        "pin",
    }
    text_keys = {
        "content",
        "message",
        "msg",
        "text",
        "sms",
        "sms_content",
        "smscontent",
        "body",
        "raw",
        "value",
    }
    container_keys = {
        "data",
        "result",
        "results",
        "record",
        "records",
        "row",
        "rows",
        "item",
        "items",
        "list",
        "messages",
        "payload",
    }

    def codes_from_value(value: Any) -> list[str]:
        matched = re.fullmatch(_SMS_DIRECT_CODE_PATTERN, str(value or "").strip())
        return [matched.group(1)] if matched else []

    def codes_from_text(value: Any) -> list[str]:
        # 接码接口有时会把旧短信和新短信一起返回。按出现顺序反转，优先取最新的验证码。
        raw_text = str(value or "").strip()
        if not raw_text:
            return []
        status_codes = _SMS_STATUS_CODE_PATTERN.findall(raw_text)
        cleaned = _SMS_URL_PATTERN.sub(" ", raw_text)
        if _SMS_NON_OTP_NOTICE_PATTERN.search(cleaned) and not _SMS_OTP_CONTEXT_PATTERN.search(cleaned):
            return _dedupe_codes(list(reversed(status_codes)))
        matches: list[str] = []
        for match in _SMS_CODE_PATTERN.finditer(cleaned):
            start, end = match.span(1)
            window = cleaned[max(0, start - 60): min(len(cleaned), end + 60)]
            if _SMS_OTP_CONTEXT_PATTERN.search(window):
                matches.append(match.group(1))
        return _dedupe_codes(list(reversed([*status_codes, *matches])))

    try:
        payload = json.loads(raw)
    except Exception:
        payload = None

    if isinstance(payload, dict):
        def scan(obj: Any) -> list[str]:
            if isinstance(obj, list):
                codes: list[str] = []
                for item in reversed(obj):
                    codes.extend(scan(item))
                return _dedupe_codes(codes)
            if not isinstance(obj, dict):
                return _dedupe_codes(codes_from_value(obj) or codes_from_text(obj))

            normalized = {str(key or "").strip().lower(): value for key, value in obj.items()}
            for key in otp_keys:
                if key in normalized:
                    codes = codes_from_value(normalized.get(key)) or codes_from_text(normalized.get(key))
                    if codes:
                        return _dedupe_codes(codes)
            for key in text_keys:
                if key in normalized:
                    codes = codes_from_text(normalized.get(key))
                    if codes:
                        return _dedupe_codes(codes)
            codes: list[str] = []
            for key, value in normalized.items():
                if key in container_keys:
                    codes.extend(scan(value))
            return _dedupe_codes(codes)

        return scan(payload)

    if isinstance(payload, list):
        codes: list[str] = []
        for item in reversed(payload):
            codes.extend(
                _extract_sms_codes(json.dumps(item, ensure_ascii=False) if isinstance(item, (dict, list)) else str(item))
            )
        return _dedupe_codes(codes)

    return codes_from_text(raw)


def _extract_sms_code(text: str) -> str:
    codes = _extract_sms_codes(text)
    return codes[0] if codes else ""


def _fetch_sms_code(sms_url: str, ignored_otps: set[str] | None = None) -> str:
    sms_url = _normalize_local_gopay_signup_bridge_url(sms_url)
    is_whatsapp_otp_url = "/otp/whatsapp/" in str(sms_url or "").lower()
    source_label = "WhatsApp 监听" if is_whatsapp_otp_url else "接码接口"
    if is_whatsapp_otp_url:
        try:
            from autoteam.whatsapp_otp import get_default_listener

            payload = get_default_listener().latest_response(max_age_seconds=600)
            text = json.dumps(payload, ensure_ascii=False)
            ignored = {str(item or "").strip() for item in (ignored_otps or set()) if str(item or "").strip()}
            direct_otp = str(((payload.get("data") or {}) if isinstance(payload, dict) else {}).get("otp") or "").strip()
            if re.fullmatch(r"\d{6}", direct_otp):
                if direct_otp not in ignored:
                    return direct_otp
                raise RuntimeError(f"{source_label}仍返回旧验证码，等待新码: {_compact_log_text(text, limit=220)}")
            codes = _extract_sms_codes(text)
            for code in codes:
                if code not in ignored:
                    return code
            if codes:
                raise RuntimeError(f"{source_label}仍返回旧验证码，等待新码: {_compact_log_text(text, limit=220)}")
        except RuntimeError:
            raise
        except Exception as exc:
            logger.debug("[gopay_executor] in-process WhatsApp OTP lookup failed, falling back to HTTP: %s", exc)
    resp = requests.get(
        sms_url,
        timeout=20,
        verify=False,
        headers={
            "User-Agent": "Mozilla/5.0 AutoTeam/1.0",
            "Accept": "application/json, text/plain, text/html, */*",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    text = (resp.text or "").strip()
    if not resp.ok:
        raise RuntimeError(text[:200] or f"{source_label}返回异常({resp.status_code})")
    ignored = {str(item or "").strip() for item in (ignored_otps or set()) if str(item or "").strip()}
    codes = _extract_sms_codes(text)
    for code in codes:
        if code not in ignored:
            return code
    if codes:
        raise RuntimeError(f"{source_label}仍返回旧验证码，等待新码: {_compact_log_text(text, limit=220)}")
    else:
        raise RuntimeError(f"{source_label}暂无验证码: {_compact_log_text(text, limit=220)}")


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




def _open_checkout_in_page(api: ChatGPTTeamAPI, checkout_url: str, email: str = ""):
    last_error = ""
    try:
        if not _goto_with_retry(api.page, checkout_url, wait_until="domcontentloaded", timeout=60000, attempts=3):
            raise GoPayFlowError("checkout goto failed", stage="browser_checkout")
    except Exception as exc:
        last_error = str(exc)
        checkout_page = api.context.new_page()
        api.page = checkout_page
        if not _goto_with_retry(checkout_page, checkout_url, wait_until="domcontentloaded", timeout=60000, attempts=3):
            logger.info(
                "[gopay_executor] checkout page goto failed: first=%s target=%s current=%s",
                _safe_error_summary(last_error),
                _safe_url_summary(checkout_url),
                _safe_url_summary(getattr(getattr(api, "page", None), "url", "")),
            )
            return False

    if _select_chatgpt_account_if_needed(api, email=email):
        if not _goto_with_retry(api.page, checkout_url, wait_until="domcontentloaded", timeout=60000, attempts=2):
            logger.info(
                "[gopay_executor] checkout page retry after account selection failed: target=%s current=%s",
                _safe_url_summary(checkout_url),
                _safe_url_summary(getattr(api.page, "url", "")),
            )
    _log_browser_auth_session_diag(api, label="checkout")
    deadline = time.time() + 35
    checkout_id = _extract_checkout_session_id(checkout_url)
    while time.time() < deadline:
        current_url = str(getattr(api.page, "url", "") or "")
        if checkout_url in current_url or (checkout_id and checkout_id in current_url) or _is_checkout_page(api):
            logger.info("[gopay_executor] checkout page opened: %s", _safe_url_summary(current_url))
            return True
        if _select_chatgpt_account_if_needed(api, email=email):
            if not _goto_with_retry(api.page, checkout_url, wait_until="domcontentloaded", timeout=60000, attempts=2):
                logger.info(
                    "[gopay_executor] checkout page retry in wait loop failed: target=%s current=%s",
                    _safe_url_summary(checkout_url),
                    _safe_url_summary(getattr(api.page, "url", "")),
                )
        try:
            api.page.wait_for_timeout(500)
        except Exception:
            time.sleep(0.5)
    logger.info(
        "[gopay_executor] checkout page open timeout: target=%s current=%s body=%s",
        _safe_url_summary(checkout_url),
        _safe_url_summary(getattr(api.page, "url", "")),
        _compact_log_text(_body_excerpt(api, 500), limit=300),
    )
    return False


def _select_chatgpt_account_if_needed(api: ChatGPTTeamAPI, email: str = "") -> bool:
    target_email = str(email or "").strip().lower()
    try:
        body = _body_excerpt(api, 1200).lower()
    except Exception:
        body = ""
    if "选择一个帐户" not in body and "choose an account" not in body and (not target_email or target_email not in body):
        return False
    script = """(targetEmail) => {
      const lower = (value) => String(value || "").toLowerCase();
      const target = lower(targetEmail);
      const nodes = Array.from(document.querySelectorAll("button, a, [role='button'], div, span"));
      const scored = [];
      for (const node of nodes) {
        const text = lower(node.innerText || node.textContent || "");
        if (!text) continue;
        const hasTarget = target && text.includes(target);
        const hasAccountHint = /choose an account|选择一个帐户|continue|继续|登录|log in/.test(text);
        if (!hasTarget && !hasAccountHint) continue;
        let clickable = node;
        for (let i = 0; i < 5 && clickable && !/^(BUTTON|A)$/.test(clickable.tagName || "") && clickable.getAttribute("role") !== "button"; i++) {
          clickable = clickable.parentElement;
        }
        if (!clickable) clickable = node;
        scored.push({ node: clickable, score: (hasTarget ? 100 : 0) + (hasAccountHint ? 10 : 0), text });
      }
      scored.sort((a, b) => b.score - a.score);
      if (!scored.length) return { clicked: false, reason: "no-candidate" };
      scored[0].node.click();
      return { clicked: true, text: scored[0].text.slice(0, 160) };
    }"""
    try:
        result = api.page.evaluate(script, target_email)
    except Exception as exc:
        logger.info("[gopay_executor] ChatGPT account chooser click failed: %s", _safe_error_summary(exc))
        return False
    if result and result.get("clicked"):
        logger.info("[gopay_executor] selected ChatGPT account in browser: %s", _compact_log_text(result.get("text"), limit=120))
        try:
            api.page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        try:
            api.page.wait_for_timeout(2500)
        except Exception:
            time.sleep(2.5)
        return True
    logger.info("[gopay_executor] ChatGPT account chooser not clicked: %s", result)
    return False


def _log_browser_auth_session_diag(api: ChatGPTTeamAPI, *, label: str):
    try:
        result = api.page.evaluate(
            """async () => {
              try {
                const resp = await fetch("/api/auth/session", {
                  method: "GET",
                  credentials: "include",
                  headers: { Accept: "application/json" }
                });
                const text = await resp.text();
                let data = {};
                try { data = text ? JSON.parse(text) : {}; } catch (_) {}
                return {
                  ok: resp.ok,
                  status: resp.status,
                  accessTokenPresent: Boolean(data && data.accessToken),
                  userPresent: Boolean(data && data.user),
                  accountIdPresent: Boolean(data && (data.accountId || data.account_id)),
                  rawPrefix: text.slice(0, 80)
                };
              } catch (e) {
                return { ok: false, status: 0, error: String(e && e.message ? e.message : e) };
              }
            }"""
        )
    except Exception as exc:
        logger.info("[gopay_executor] browser auth session diag failed: label=%s error=%s", label, _safe_error_summary(exc))
        return
    logger.info(
        "[gopay_executor] browser auth session diag: label=%s status=%s ok=%s access_token_present=%s user_present=%s account_id_present=%s error=%s raw=%s",
        label,
        result.get("status"),
        result.get("ok"),
        result.get("accessTokenPresent"),
        result.get("userPresent"),
        result.get("accountIdPresent"),
        _safe_error_summary(result.get("error") or ""),
        _compact_log_text(result.get("rawPrefix") or "", limit=80),
    )


def _goto_with_retry(page, url: str, *, wait_until: str = "domcontentloaded", timeout: int = 60000, attempts: int = 3) -> bool:
    last_error = ""
    for attempt in range(1, max(1, attempts) + 1):
        try:
            page.goto(url, wait_until=wait_until, timeout=timeout)
            return True
        except Exception as exc:
            last_error = _safe_error_summary(exc)
            logger.info(
                "[gopay_executor] browser goto failed, retrying: attempt=%s/%s url=%s error=%s",
                attempt,
                attempts,
                _safe_url_summary(url),
                last_error,
            )
            time.sleep(min(2.0 * attempt, 5.0))
    logger.info("[gopay_executor] browser goto exhausted: url=%s error=%s", _safe_url_summary(url), last_error)
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
                logger.info("[gopay_executor] 切回 checkout 页面: %s", _safe_url_summary(url))
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
        r"the customer'?s location isn'?t recognized[^.。]*\.?",
        r"set a valid customer address[^.。]*\.?",
        r"automatically calculate tax[^.。]*\.?",
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
        if _is_checkout_payment_not_approved_error(last_error):
            return False, f"付款未获批准，当前账号将从号池删除并停止本次账号尝试: {last_error}"
        if attempt < max_attempts:
            progress("submit_retry", attempt=attempt + 1, max_attempts=max_attempts, reason=last_error)
            time.sleep(1.5)

    return False, f"点击订阅重试 {max_attempts} 次后仍失败: {last_error or '未进入手机号页面'}"


def _browser_checkout_nonzero_amount_hint(api: ChatGPTTeamAPI) -> str:
    text = _body_excerpt(api, 3500)
    compact = re.sub(r"\s+", " ", text or "").strip()
    if not compact:
        return ""
    amount_expr = r"(?:IDR|Rp|US\$|\$)\s*[-+]?\d[\d,.]*(?:\.\d{1,2})?|[-+]?\d[\d,.]*(?:\.\d{1,2})?\s*(?:IDR|Rp|USD)"
    today_patterns = (
        rf"(?:今日应付合计|今天应付合计|今日应付|今天应付|今日支付合计|今天支付合计|应付金额|支付金额|amount\s+due|total\s+due\s+today|due\s+today|today'?s\s+total|total\s+payment|payment\s+total|jumlah\s+yang\s+harus\s+dibayar|total\s+pembayaran)\s*({amount_expr})",
        rf"({amount_expr})\s*(?:total\s+due\s+today|due\s+today|today'?s\s+total|total\s+payment|payment\s+total|今日应付合计|今天应付合计|今日应付|今天应付|今日支付合计|今天支付合计|应付金额|支付金额|jumlah\s+yang\s+harus\s+dibayar|total\s+pembayaran)",
    )
    for pattern in today_patterns:
        matched = re.search(pattern, compact, flags=re.IGNORECASE)
        if not matched:
            continue
        amount_text = matched.group(1).strip()
        parsed = _parse_display_amount(amount_text)
        if parsed and parsed > 0:
            return amount_text
        return ""
    zero_markers = (
        "$0",
        "us$0",
        "idr 0",
        "rp0",
        "rp 0",
        "free trial",
        "free today",
        "gratis",
        "免费",
        "0.00",
    )
    lower = compact.lower()
    if any(marker in lower for marker in zero_markers):
        return ""
    amount_patterns = (
        r"(?:us\$|\$)\s*(?:[1-9]\d*)(?:[.,]\d{2})?",
        r"(?:idr|rp)\s*[1-9]\d*(?:[.,]\d{3})*(?:\.\d{1,2})?",
        r"[1-9]\d*(?:[.,]\d{3})*(?:\.\d{1,2})?\s*(?:idr|rp)",
    )
    for pattern in amount_patterns:
        matched = re.search(pattern, compact, flags=re.IGNORECASE)
        if matched:
            return matched.group(0)
    return ""


def _generate_id_checkout_in_page(api: ChatGPTTeamAPI, access_token: str, checkout_ui_mode: str = "custom"):
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
    result = None
    last_error: Exception | None = None
    max_attempts = max(1, _env_int("GOPAY_BROWSER_CHECKOUT_EVALUATE_ATTEMPTS", 8))
    for attempt in range(1, max_attempts + 1):
        try:
            _wait_for_page_navigation_quiet(api.page)
            result = api.page.evaluate(
                script,
                {
                    "accessToken": access_token,
                    "payload": _chatgpt_checkout_payload(checkout_ui_mode),
                },
            )
            break
        except Exception as exc:
            last_error = exc
            if not _is_playwright_navigation_race_error(exc) or attempt >= max_attempts:
                raise
            logger.info(
                "[gopay_executor] checkout generation evaluate raced with page navigation, retrying: attempt=%s/%s current=%s error=%s",
                attempt,
                max_attempts,
                _safe_url_summary(getattr(api.page, "url", "")),
                _safe_error_summary(exc),
            )
            try:
                api.page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
            try:
                api.page.wait_for_timeout(1500)
            except Exception:
                time.sleep(1.5)
            _wait_for_page_navigation_quiet(api.page)
    if result is None and last_error is not None:
        raise last_error
    if not isinstance(result, dict):
        raise RuntimeError(f"生成印尼区支付链接失败: unexpected result {type(result).__name__}")
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


def _open_id_checkout_via_page_script(api: ChatGPTTeamAPI, access_token: str, checkout_ui_mode: str = "custom"):
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
          checkout_ui_mode: args.checkoutUiMode || "custom"
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
        if (data && (data.url || data.checkout_session_id)) {
          const url = data.url || ("https://chatgpt.com/checkout/openai_llc/" + data.checkout_session_id);
          window.location.href = url;
          return { ok: true, url, raw: data };
        }
        return { ok: false, detail: data.detail || JSON.stringify(data), raw: data };
      } catch (e) {
        return { ok: false, detail: String(e && e.message ? e.message : e) };
      }
    }"""
    result = None
    last_error: Exception | None = None
    max_attempts = max(1, _env_int("GOPAY_BROWSER_CHECKOUT_EVALUATE_ATTEMPTS", 8))
    for attempt in range(1, max_attempts + 1):
        try:
            _wait_for_page_navigation_quiet(api.page)
            result = api.page.evaluate(
                script,
                {
                    "accessToken": access_token,
                    "checkoutUiMode": _normalize_checkout_ui_mode(checkout_ui_mode),
                },
            )
            break
        except Exception as exc:
            last_error = exc
            if not _is_playwright_navigation_race_error(exc) or attempt >= max_attempts:
                raise
            logger.info(
                "[gopay_executor] checkout redirect evaluate raced with page navigation, retrying: attempt=%s/%s current=%s error=%s",
                attempt,
                max_attempts,
                _safe_url_summary(getattr(api.page, "url", "")),
                _safe_error_summary(exc),
            )
            try:
                api.page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
            try:
                api.page.wait_for_timeout(1500)
            except Exception:
                time.sleep(1.5)
            _wait_for_page_navigation_quiet(api.page)
    if result is None and last_error is not None:
        raise last_error
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
    checkout_ui_mode: str = "custom",
    phone_number: str,
    sms_url: str,
    gopay_pin: str,
    otp_channel: str = "sms",
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
    A ChatGPT access token is required; auth_session cookies are used when available.
    """

    api = ChatGPTTeamAPI()
    session_id = uuid.uuid4().hex[:12]
    screenshot_paths: list[str] = []
    final_checkout_url = str(checkout_url or "").strip()
    checkout_ui_mode = _normalize_checkout_ui_mode(checkout_ui_mode)
    try:
        proxy_url = normalize_proxy_url(proxy_url)
    except ValueError as exc:
        logger.info("[gopay_executor] GoPay task proxy config invalid: %s", exc)
        return _build_result("failed", failure_stage="proxy_config", message=str(exc), checkout_url=final_checkout_url)
    logger.info(
        "[gopay_executor] GoPay task starting: email=%s checkout=%s phone=%s proxy=%s bypass=%s timeout=%s",
        _safe_email_summary(email),
        _safe_url_summary(final_checkout_url) if final_checkout_url else "<auto-generate>",
        _safe_phone_summary(phone_number, country_code),
        _safe_proxy_summary(proxy_url),
        str(proxy_bypass or "").strip() or "<none>",
        timeout_seconds,
    )
    auth_session = load_auth_session(email)
    session_token = str(auth_session.get("sessionToken") or auth_session.get("session_token") or "").strip()
    access_token = str(auth_session.get("accessToken") or auth_session.get("access_token") or "").strip()
    auth_file_context = _load_chatgpt_auth_file_context(email)
    if not access_token:
        access_token = str(auth_file_context.get("access_token") or "").strip()
    generated_checkout_meta: dict = {}

    def progress(stage: str, **extra):
        _emit_gopay_progress(progress_callback, stage, **extra)

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
        account_id = str(account_info.get("id") or auth_file_context.get("account_id") or "").strip()
        device_id = str(
            auth_session.get("device_id")
            or auth_session.get("oai_device_id")
            or auth_session.get("oaiDeviceId")
            or ""
        ).strip() or str(uuid.uuid4())
        openai_sentinel_token = str(
            auth_session.get("openai_sentinel_token")
            or auth_session.get("openaiSentinelToken")
            or auth_session.get("sentinel_token")
            or ""
        ).strip()
        oai_client_version = str(auth_session.get("oai_client_version") or auth_session.get("oaiClientVersion") or "").strip()
        oai_client_build_number = str(
            auth_session.get("oai_client_build_number") or auth_session.get("oaiClientBuildNumber") or ""
        ).strip()
        token_source = "auth_session" if str(auth_session.get("accessToken") or auth_session.get("access_token") or "").strip() else "auth_file"

        logger.info(
            "[gopay_executor] ChatGPT token context ready: email=%s source=%s access_token_present=%s session_cookie_present=%s account_id_present=%s device_id=%s sentinel_token_present=%s auth_file_present=%s",
            _safe_email_summary(email),
            token_source,
            bool(access_token),
            bool(session_token or str(auth_session.get("cookie_header") or "").strip()),
            bool(account_id),
            _mask_log_value(device_id),
            bool(openai_sentinel_token),
            bool(auth_file_context.get("auth_file")),
        )

        if cancelled():
            return _build_result("failed", failure_stage="generate_checkout", message="任务已取消", screenshot_paths=screenshot_paths, billing_info=public_billing_info)
        if not access_token:
            return _build_result(
                "failed",
                failure_stage="generate_checkout",
                message=f"账号缺少 ChatGPT access_token；已尝试 auth_session 和 auth_file/CPA 认证文件 (source={token_source})",
                screenshot_paths=screenshot_paths,
                billing_info=public_billing_info,
            )
        if not session_token and not str(auth_session.get("cookie_header") or "").strip():
            logger.info(
                "[gopay_executor] ChatGPT Web session cookie missing; continuing with bearer access_token from %s",
                token_source,
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
            openai_sentinel_token=openai_sentinel_token,
            oai_client_version=oai_client_version,
            oai_client_build_number=oai_client_build_number,
            proxy_url=proxy_url,
        )
        progress("chatgpt_http_session_ready")
        logger.info(
            "[gopay_executor] ChatGPT HTTP session ready: email=%s proxy=%s transport=%s",
            _safe_email_summary(email),
            _safe_proxy_summary(proxy_url),
            _http_transport_name(chatgpt_http),
        )

        direct_redirect_mode = _looks_like_pm_redirect_url(final_checkout_url)
        checkout_form_mode = _normalize_checkout_form_mode(os.environ.get("GOPAY_CHECKOUT_FORM_MODE", ""))
        browser_checkout_ui_mode = not direct_redirect_mode and checkout_form_mode == "browser"
        protocol_browser_fallback_enabled = not direct_redirect_mode and checkout_form_mode == "auto"
        protocol_checkout_ui_mode = (
            os.environ.get("GOPAY_PROTOCOL_CHECKOUT_UI_MODE")
            or os.environ.get("GOPAY_HOSTED_PROTOCOL_CHECKOUT_UI_MODE")
            or "hosted"
        )
        protocol_checkout_ui_mode = _normalize_checkout_ui_mode(protocol_checkout_ui_mode)
        if direct_redirect_mode:
            progress("checkout_ready", checkout_url=final_checkout_url, mode="redirect")
            logger.info("[gopay_executor] using direct redirect checkout: %s", _safe_url_summary(final_checkout_url))
            raw_checkout = {}
        elif browser_checkout_ui_mode:
            if not final_checkout_url:
                progress("generate_checkout")
                try:
                    generated_checkout_meta = _generate_id_checkout_http(
                        chatgpt_http,
                        access_token=access_token,
                        checkout_ui_mode=checkout_ui_mode,
                        session_token=session_token,
                        cookie_header=cookie_header,
                        account_id=account_id,
                        device_id=device_id,
                        user_agent=str(auth_session.get("user_agent") or auth_session.get("userAgent") or "").strip(),
                        openai_sentinel_token=openai_sentinel_token,
                        oai_client_version=oai_client_version,
                        oai_client_build_number=oai_client_build_number,
                    )
                    cookie_header = str(getattr(chatgpt_http, "_chatgpt_cookie_header", "") or cookie_header)
                except Exception as exc:
                    logger.info(
                        "[gopay_executor] HTTP checkout generation failed in browser UI mode, will generate inside browser: %s",
                        _safe_error_summary(exc),
                    )
                    final_checkout_url = ""
                    raw_checkout = {}
                else:
                    final_checkout_url = str(generated_checkout_meta.get("url") or "").strip()
                    raw_checkout = generated_checkout_meta.get("raw") if isinstance(generated_checkout_meta.get("raw"), dict) else {}
                    logger.info("[gopay_executor] generated GoPay checkout session for browser UI: %s", _safe_url_summary(final_checkout_url))
            else:
                raw_checkout = {}
            progress("checkout_ready", checkout_url=final_checkout_url, mode="browser_ui")
            logger.info(
                "[gopay_executor] using full browser checkout UI flow; ChatGPT approve API will not be called: checkout=%s",
                _safe_url_summary(final_checkout_url) if final_checkout_url else "<browser-generate>",
            )
        elif not final_checkout_url:
            progress("generate_checkout")
            try:
                generated_checkout_meta = _generate_id_checkout_http(
                    chatgpt_http,
                    access_token=access_token,
                    checkout_ui_mode=protocol_checkout_ui_mode,
                    session_token=session_token,
                    cookie_header=cookie_header,
                    account_id=account_id,
                    device_id=device_id,
                    user_agent=str(auth_session.get("user_agent") or auth_session.get("userAgent") or "").strip(),
                    openai_sentinel_token=openai_sentinel_token,
                    oai_client_version=oai_client_version,
                    oai_client_build_number=oai_client_build_number,
                )
                cookie_header = str(getattr(chatgpt_http, "_chatgpt_cookie_header", "") or cookie_header)
            except Exception as exc:
                raise GoPayFlowError(f"生成印尼区支付链接失败: {exc}", stage="generate_checkout") from exc
            final_checkout_url = str(generated_checkout_meta.get("url") or "").strip()
            progress("checkout_ready", checkout_url=final_checkout_url, mode="protocol", checkout_ui_mode=protocol_checkout_ui_mode)
            logger.info(
                "[gopay_executor] generated GoPay checkout session for protocol form mode: checkout_ui_mode=%s url=%s",
                protocol_checkout_ui_mode,
                _safe_url_summary(final_checkout_url),
            )
            raw_checkout = generated_checkout_meta.get("raw") if isinstance(generated_checkout_meta.get("raw"), dict) else {}
        else:
            progress("checkout_ready", checkout_url=final_checkout_url)
            logger.info("[gopay_executor] using provided checkout URL: %s", _safe_url_summary(final_checkout_url))
            raw_checkout = {}

        checkout_session_id = _extract_checkout_session_id(final_checkout_url, raw_checkout)
        if not checkout_session_id and not direct_redirect_mode and not browser_checkout_ui_mode:
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
        logger.info(
            "[gopay_executor] checkout identifiers ready: checkout_session_id=%s direct_redirect=%s browser_ui=%s form_mode=%s processor_entity=%s midtrans_client_id_present=%s",
            _mask_log_value(checkout_session_id),
            direct_redirect_mode,
            browser_checkout_ui_mode,
            checkout_form_mode,
            processor_entity or "<default>",
            bool(midtrans_client_id),
        )

        def approve_callback(cs_id: str) -> dict:
            nonlocal cookie_header, openai_sentinel_token
            try:
                return _approve_checkout_http(
                    chatgpt_http,
                    access_token=access_token,
                    checkout_session_id=cs_id,
                    processor_entity=processor_entity,
                    cookie_header=cookie_header,
                    account_id=account_id,
                    device_id=device_id,
                    openai_sentinel_token=openai_sentinel_token,
                )
            except GoPayFlowError as exc:
                if exc.stage != "chatgpt_approve" or not _env_enabled("GOPAY_APPROVE_BROWSER_FALLBACK", False):
                    raise
                progress("chatgpt_approve_browser_fallback", checkout_session_id=cs_id)
                logger.info(
                    "[gopay_executor] ChatGPT approve HTTP failed, trying browser fallback: checkout_session_id=%s error=%s",
                    _mask_log_value(cs_id),
                    _safe_error_summary(exc),
                )
                result = _approve_checkout_with_browser_context(
                    api,
                    access_token=access_token,
                    session_token=session_token,
                    cookie_header=cookie_header,
                    checkout_session_id=cs_id,
                    processor_entity=processor_entity,
                    account_id=account_id,
                    device_id=device_id,
                    proxy_url=proxy_url,
                    proxy_bypass=proxy_bypass,
                )
                cookie_header = _merge_cookie_headers(cookie_header, str(result.get("_browser_cookie_header") or ""))
                openai_sentinel_token = str(result.get("_browser_openai_sentinel_token") or openai_sentinel_token)
                _configure_chatgpt_http_session(
                    chatgpt_http,
                    access_token=access_token,
                    session_token=session_token,
                    cookie_header=cookie_header,
                    account_id=account_id,
                    device_id=device_id,
                    openai_sentinel_token=openai_sentinel_token,
                    user_agent=str(auth_session.get("user_agent") or auth_session.get("userAgent") or "").strip(),
                )
                logger.info("[gopay_executor] ChatGPT approve browser fallback succeeded")
                progress("chatgpt_approve_browser_fallback_succeeded", checkout_session_id=cs_id)
                return result

        def verify_callback(cs_id: str) -> dict:
            try:
                return _verify_checkout_http(
                    chatgpt_http,
                    access_token=access_token,
                    checkout_session_id=cs_id,
                    processor_entity=processor_entity,
                    cookie_header=cookie_header,
                    account_id=account_id,
                    device_id=device_id,
                    openai_sentinel_token=openai_sentinel_token,
                )
            except Exception as exc:
                logger.info(
                    "[gopay_executor] ChatGPT verify HTTP failed, trying browser context: checkout_session_id=%s error=%s",
                    _mask_log_value(cs_id),
                    _safe_error_summary(exc),
                )
                if getattr(api, "page", None):
                    try:
                        return _verify_checkout_in_page(
                            api,
                            access_token=access_token,
                            checkout_session_id=cs_id,
                            processor_entity=processor_entity,
                        )
                    except Exception as browser_exc:
                        logger.info(
                            "[gopay_executor] ChatGPT verify browser context failed: checkout_session_id=%s error=%s",
                            _mask_log_value(cs_id),
                            _safe_error_summary(browser_exc),
                        )
                return {
                    "state": "verify_timeout",
                    "verify": {"error": _safe_error_summary(exc)},
                }

        resolved_otp_channel = str(otp_channel or os.environ.get("GOPAY_OTP_CHANNEL") or "sms").strip().lower()
        sms_otp_timeout = _env_int("GOPAY_BIND_SMS_OTP_TIMEOUT_SECONDS", 180)
        sms_otp_resend_limit = _env_int("GOPAY_BIND_SMS_OTP_MAX_RESEND_ATTEMPTS", 2)
        otp_provider = _poll_otp_from_sms_url(
            sms_url,
            timeout_seconds=60 if resolved_otp_channel == "whatsapp" else max(60, sms_otp_timeout),
            initial_delay_seconds=0,
            resend_after_seconds=None,
            max_resend_attempts=None if resolved_otp_channel == "whatsapp" else max(0, sms_otp_resend_limit),
            is_cancelled=is_cancelled,
            progress=progress,
        )

        sms_otp_trigger_callback = None
        if resolved_otp_channel == "whatsapp" and _env_truthy("GOPAY_CAPTURE_AUTH_NETWORK"):
            def sms_otp_trigger_callback(reference_id: str, activation_link_url: str) -> None:
                progress("whatsapp_otp_trigger")
                result = _diagnose_gopay_authorize_network(
                    api,
                    activation_link_url=activation_link_url,
                    reference_id=reference_id,
                )
                logger.info(
                    "[gopay_executor] GoPay WhatsApp authorize network diagnostic finished: %s",
                    _safe_error_summary(result),
                )
                if _env_truthy("GOPAY_CAPTURE_AUTH_NETWORK_ONLY"):
                    raise GoPayOTPCancelled("GoPay 授权页网络诊断已完成，按配置停止在 OTP 前", stage="fetch_otp")

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
            sms_otp_trigger_callback=sms_otp_trigger_callback,
            otp_channel=resolved_otp_channel,
            is_cancelled=is_cancelled,
            progress_callback=progress_callback,
        )
        logger.info(
            "[gopay_executor] GoPay OTP channel resolved: otp_channel=%s sms_url=%s",
            getattr(charger, "otp_channel", resolved_otp_channel),
            _safe_url_summary(sms_url) if sms_url else "<empty>",
        )

        progress("gopay_http_flow", checkout_session_id=checkout_session_id)
        logger.info(
            "[gopay_executor] GoPay flow started: checkout_session_id=%s direct_redirect=%s browser_ui=%s form_mode=%s",
            _mask_log_value(checkout_session_id),
            direct_redirect_mode,
            browser_checkout_ui_mode,
            checkout_form_mode,
        )

        def run_browser_handoff_with_midtrans_retry(*, fallback_stage: str = "browser_checkout"):
            nonlocal final_checkout_url, public_billing_info, checkout_session_id, processor_entity
            max_attempts = max(1, _env_int("GOPAY_MIDTRANS_LINKING_429_RETRY_ATTEMPTS", 30))
            last_exc: GoPayFlowError | None = None
            browser_handoff = _browser_checkout_to_gopay_redirect(
                api,
                access_token=access_token,
                checkout_ui_mode=checkout_ui_mode,
                session_token=session_token,
                cookie_header=cookie_header,
                checkout_url=final_checkout_url,
                raw_checkout=raw_checkout,
                email=email,
                account_id=account_id,
                device_id=device_id,
                billing=billing,
                session_id=session_id,
                screenshot_paths=screenshot_paths,
                proxy_url=proxy_url,
                proxy_bypass=proxy_bypass,
                progress=progress,
            )
            final_checkout_url = str(browser_handoff.get("checkout_url") or final_checkout_url)
            public_billing_info = _public_billing_info(billing)
            checkout_session_id = str(browser_handoff.get("checkout_session_id") or checkout_session_id)
            processor_entity = str(browser_handoff.get("processor_entity") or processor_entity)
            redirect_url = str(browser_handoff.get("redirect_url") or "")
            snap_token = str(browser_handoff.get("snap_token") or "")
            if redirect_url and not snap_token:
                snap_token = charger._fetch_pm_redirect_snap_token(redirect_url)
            if not snap_token:
                raise GoPayFlowError("浏览器 checkout UI 未返回 Midtrans 跳转", stage=fallback_stage)

            retry_seconds = max(0.5, _env_float("GOPAY_MIDTRANS_LINKING_429_RETRY_SECONDS", 3.0))
            for protocol_attempt in range(1, max_attempts + 1):
                if protocol_attempt > 1:
                    logger.info(
                        "[gopay_executor] retry current account by protocol post after Midtrans 429: attempt=%s/%s email=%s snap_token=%s",
                        protocol_attempt,
                        max_attempts,
                        _safe_email_summary(email),
                        _mask_log_value(snap_token),
                    )
                    progress(
                        "midtrans_linking_retry",
                        attempt=protocol_attempt,
                        max_attempts=max_attempts,
                        reason="Midtrans linking 失败: HTTP 429，直接重试协议接口",
                    )
                try:
                    return charger.run_from_snap_token(
                        snap_token=snap_token,
                        checkout_session_id=checkout_session_id,
                    )
                except GoPayFlowError as exc:
                    if not _is_midtrans_linking_rate_limited_error(exc):
                        raise
                    last_exc = exc
                    logger.info(
                        "[gopay_executor] Midtrans linking 429 after browser handoff; retrying protocol post without refilling billing: attempt=%s/%s error=%s",
                        protocol_attempt,
                        max_attempts,
                        _safe_error_summary(exc),
                    )
                    if protocol_attempt >= max_attempts:
                        break
                    time.sleep(retry_seconds)
            raise last_exc or GoPayFlowError("Midtrans linking 429 重试耗尽", stage="midtrans_linking")

        if direct_redirect_mode:
            flow_result = charger.run_from_redirect(
                redirect_url=final_checkout_url,
                checkout_session_id=checkout_session_id,
            )
        elif browser_checkout_ui_mode:
            flow_result = run_browser_handoff_with_midtrans_retry(fallback_stage="browser_checkout")
        else:
            try:
                flow_result = charger.run(checkout_session_id=checkout_session_id, stripe_pk=stripe_pk)
            except GoPayFlowError as exc:
                if (
                    not protocol_browser_fallback_enabled
                    or not _env_enabled("GOPAY_BROWSER_CHECKOUT_FALLBACK", True)
                    or not _protocol_checkout_can_browser_fallback(exc)
                ):
                    raise
                logger.info(
                    "[gopay_executor] protocol checkout failed before GoPay authorization, switching to full browser checkout handoff: checkout_session_id=%s stage=%s error=%s",
                    _mask_log_value(checkout_session_id),
                    exc.stage,
                    _safe_error_summary(exc),
                )
                progress(
                    "stripe_protocol_form_failed_browser_fallback",
                    checkout_session_id=checkout_session_id,
                    reason=_safe_error_summary(exc),
                    failure_stage=exc.stage,
                )
                flow_result = run_browser_handoff_with_midtrans_retry(fallback_stage=exc.stage or "protocol_checkout")
        logger.info(
            "[gopay_executor] GoPay HTTP flow finished: state=%s reference=%s charge_ref=%s snap_token=%s",
            flow_result.get("state", ""),
            _mask_log_value(flow_result.get("reference_id", "")),
            _mask_log_value(flow_result.get("charge_ref", "")),
            _mask_log_value(flow_result.get("snap_token", "")),
        )

        flow_state = str(flow_result.get("state") or "")
        if flow_state in {"succeeded", "verify_timeout"}:
            progress("completed")
            verify_timeout = flow_state == "verify_timeout"
            result = _build_result(
                "success",
                message=(
                    "GoPay 支付已完成，ChatGPT verify 网络超时，已按成功处理"
                    if verify_timeout
                    else "GoPay 支付成功"
                ),
                screenshot_paths=screenshot_paths,
                checkout_url=final_checkout_url,
                billing_info=public_billing_info,
            )
            if verify_timeout:
                result["verify_warning"] = "chatgpt_verify_timeout"
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
                "verify": flow_result.get("verify") or {},
                "verify_state": flow_state,
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
        if _looks_like_chatgpt_user_paid_text(str(exc)):
            progress("chatgpt_user_paid_skip", email=email, message="ChatGPT 返回 user is paid，账号已是付费用户，跳过 GoPay 绑卡")
            return _as_chatgpt_user_paid_success(
                {
                    "screenshot_paths": screenshot_paths,
                    "checkout_url": final_checkout_url,
                },
                checkout_url=final_checkout_url,
                billing_info=public_billing_info,
            )
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
        if _looks_like_chatgpt_user_paid_text(str(exc)):
            progress("chatgpt_user_paid_skip", email=email, message="ChatGPT 返回 user is paid，账号已是付费用户，跳过 GoPay 绑卡")
            return _as_chatgpt_user_paid_success(
                {
                    "screenshot_paths": screenshot_paths,
                    "checkout_url": final_checkout_url,
                },
                checkout_url=final_checkout_url,
                billing_info=public_billing_info,
            )
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
    checkout_ui_mode: str = "custom",
    phone_number: str,
    sms_url: str,
    gopay_pin: str,
    otp_channel: str = "sms",
    phone_accounts: list[dict] | None = None,
    billing_info: dict | None = None,
    country_code: str = "",
    proxy_url: str | None = None,
    proxy_bypass: str | None = None,
    timeout_seconds: int = 900,
    account_emails: list[str] | None = None,
    pending_retry_attempts: int = 1,
    auth_session_refresh_callback=None,
    is_cancelled=None,
    skip_current=None,
    clear_skip_current=None,
    progress_callback=None,
):
    """Run GoPay payment.

    Account rotation is only enabled for explicit batch mode: multiple
    account_emails and an auto-generated checkout.
    """

    requested_email = str(email or "").strip().lower()
    final_checkout_url = str(checkout_url or "").strip()
    checkout_ui_mode = _normalize_checkout_ui_mode(checkout_ui_mode)
    try:
        pending_retry_attempts = max(0, min(3, int(1 if pending_retry_attempts is None else pending_retry_attempts)))
    except Exception:
        pending_retry_attempts = 1
    pending_retry_backoffs = [60.0, 180.0, 300.0]

    normalized_phone_accounts: list[dict] = []
    seen_phone_accounts: set[tuple[str, str, str]] = set()
    for raw_phone_account in phone_accounts or []:
        if not isinstance(raw_phone_account, dict):
            continue
        account_country_code = str(raw_phone_account.get("country_code") or raw_phone_account.get("countryCode") or country_code or "").strip()
        account_phone_number = str(raw_phone_account.get("phone_number") or raw_phone_account.get("phoneNumber") or "").strip()
        account_sms_url = str(raw_phone_account.get("sms_url") or raw_phone_account.get("smsUrl") or "").strip()
        account_gopay_pin = str(raw_phone_account.get("gopay_pin") or raw_phone_account.get("gopayPin") or "").strip()
        account_otp_channel = str(raw_phone_account.get("otp_channel") or raw_phone_account.get("otpChannel") or otp_channel or "sms").strip().lower()
        if account_otp_channel == "whatsapp":
            account_sms_url = str(os.environ.get("AUTOTEAM_LOCAL_BASE_URL") or "http://127.0.0.1:8787").strip().rstrip("/") + "/otp/whatsapp/latest"
        if not account_phone_number or not account_sms_url or not account_gopay_pin:
            continue
        phone_key = (account_country_code, account_phone_number, account_sms_url)
        if phone_key in seen_phone_accounts:
            continue
        seen_phone_accounts.add(phone_key)
        normalized_phone_accounts.append(
            {
                "country_code": account_country_code,
                "phone_number": account_phone_number,
                "sms_url": account_sms_url,
                "gopay_pin": account_gopay_pin,
                "otp_channel": account_otp_channel,
            }
        )
    if not normalized_phone_accounts:
        fallback_sms_url = str(sms_url or "").strip()
        if str(otp_channel or "sms").strip().lower() == "whatsapp":
            fallback_sms_url = str(os.environ.get("AUTOTEAM_LOCAL_BASE_URL") or "http://127.0.0.1:8787").strip().rstrip("/") + "/otp/whatsapp/latest"
        normalized_phone_accounts.append(
            {
                "country_code": str(country_code or "").strip(),
                "phone_number": str(phone_number or "").strip(),
                "sms_url": fallback_sms_url,
                "gopay_pin": str(gopay_pin or "").strip(),
                "otp_channel": str(otp_channel or "sms").strip().lower(),
            }
        )

    def phone_for_attempt(attempt: int) -> dict:
        return normalized_phone_accounts[(max(1, int(attempt or 1)) - 1) % len(normalized_phone_accounts)]

    def emit(stage: str, **extra):
        _emit_gopay_progress(progress_callback, stage, **extra)

    def cancel_requested() -> bool:
        return callable(is_cancelled) and is_cancelled()

    def skip_requested() -> bool:
        return callable(skip_current) and skip_current()

    def clear_skip_request():
        if callable(clear_skip_current):
            clear_skip_current()

    def current_attempt_interrupted() -> bool:
        return cancel_requested() or skip_requested()

    def run_once(candidate_email: str, attempt: int = 1) -> dict:
        active_phone = phone_for_attempt(attempt)
        return _run_gopay_bind_task_once(
            email=candidate_email,
            checkout_url=checkout_url,
            checkout_ui_mode=checkout_ui_mode,
            phone_number=str(active_phone.get("phone_number") or ""),
            sms_url=str(active_phone.get("sms_url") or ""),
            gopay_pin=str(active_phone.get("gopay_pin") or ""),
            otp_channel=str(active_phone.get("otp_channel") or otp_channel or "sms"),
            billing_info=billing_info,
            country_code=str(active_phone.get("country_code") or ""),
            proxy_url=proxy_url,
            proxy_bypass=proxy_bypass,
            timeout_seconds=timeout_seconds,
            is_cancelled=current_attempt_interrupted,
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
    logger.info(
        "[gopay_executor] account rotation mode: enabled=%s requested_email=%s checkout=%s candidates=%s",
        rotation_enabled,
        _safe_email_summary(requested_email),
        _safe_url_summary(final_checkout_url) if final_checkout_url else "<auto-generate>",
        [_safe_email_summary(candidate) for candidate in dict.fromkeys(explicit_candidates)],
    )

    if not rotation_enabled:
        emit("gopay_try_account", email=requested_email, attempt=1, total=1)
        result = run_once(requested_email, 1)
        if _is_chatgpt_user_paid_result(result):
            result = _as_chatgpt_user_paid_success(result, checkout_url=final_checkout_url)
            result["user_paid_skip_emails"] = [requested_email]
            emit("chatgpt_user_paid_skip", email=requested_email, message=result.get("message") or "")
        result["email_used"] = requested_email
        result["requested_email"] = requested_email
        logger.info(
            "[gopay_executor] single GoPay attempt finished: email=%s status=%s failure_stage=%s",
            _safe_email_summary(requested_email),
            result.get("status") or "",
            result.get("failure_stage") or "",
        )
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
    last_blocked_email = ""
    rejected: list[str] = []
    last_rejected_result: dict | None = None
    last_rejected_email = ""
    payment_failed: list[str] = []
    last_payment_failed_result: dict | None = None
    last_payment_failed_email = ""
    nonzero_blocked: list[str] = []
    last_nonzero_blocked_result: dict | None = None
    last_nonzero_blocked_email = ""
    failed: list[str] = []
    token_invalidated: list[str] = []
    last_failed_result: dict | None = None
    last_failed_email = ""
    successful: list[str] = []
    last_success_result: dict | None = None
    last_success_email = ""
    skipped_cooldown: list[str] = []
    skipped_by_user: list[str] = []
    pending_retry: list[str] = []
    retried: list[str] = []
    auth_session_refreshed: list[str] = []
    auth_session_refresh_failed: list[str] = []
    user_paid_skip: list[str] = []

    def append_unique(target: list[str], value: str):
        value = str(value or "").strip().lower()
        if value and value not in target:
            target.append(value)

    def remove_email(target: list[str], value: str):
        value = str(value or "").strip().lower()
        if not value:
            return
        target[:] = [item for item in target if item != value]

    def queue_pending_retry(candidate: str, *, reason: str, stage: str, retry_round: int = 0):
        if str(candidate or "").strip().lower() in successful:
            return
        append_unique(pending_retry, candidate)
        emit(
            "gopay_pending_retry_queued",
            email=candidate,
            pending_retry=len(pending_retry),
            reason=reason,
            source_stage=stage,
            retry_round=retry_round,
            max_retry_rounds=pending_retry_attempts,
            message=f"账号暂未明确失败，加入待重试: {candidate}",
        )

    def refresh_auth_session_for_retry(candidate: str, failure_result: dict, *, retry_round: int = 0) -> bool:
        normalized = str(candidate or "").strip().lower()
        if not normalized or normalized in auth_session_refreshed or normalized in auth_session_refresh_failed:
            return False
        append_unique(token_invalidated, normalized)
        append_unique(auth_session_refresh_failed, normalized)
        emit(
            "gopay_auth_session_refresh_failed",
            email=normalized,
            retry_round=retry_round,
            failure_stage=failure_result.get("failure_stage") or "",
            message=f"auth_session access token 已失效，账号已标记废弃，不再尝试刷新: {normalized}",
            level="warn",
        )
        return False

    def mark_candidate_successful(candidate: str):
        append_unique(successful, candidate)
        remove_email(pending_retry, candidate)
        remove_email(blocked, candidate)
        remove_email(rejected, candidate)
        remove_email(payment_failed, candidate)
        remove_email(nonzero_blocked, candidate)
        remove_email(failed, candidate)
        remove_email(token_invalidated, candidate)
        remove_email(skipped_cooldown, candidate)
        remove_email(skipped_by_user, candidate)
        remove_email(auth_session_refresh_failed, candidate)

    def attach_common_lists(result: dict):
        success_set = set(successful)
        result["blocked_emails"] = [item for item in blocked if item not in success_set]
        result["rejected_emails"] = [item for item in rejected if item not in success_set]
        result["payment_failed_emails"] = [item for item in payment_failed if item not in success_set]
        result["nonzero_blocked_emails"] = [item for item in nonzero_blocked if item not in success_set]
        result["failed_emails"] = [item for item in failed if item not in success_set]
        result["token_invalidated_emails"] = [item for item in token_invalidated if item not in success_set]
        result["successful_emails"] = successful[:]
        result["skipped_emails"] = [item for item in skipped_by_user if item not in success_set]
        result["skipped_cooldown_emails"] = [item for item in skipped_cooldown if item not in success_set]
        result["pending_retry_emails"] = [item for item in pending_retry if item not in success_set]
        result["retried_emails"] = retried[:]
        result["auth_session_refreshed_emails"] = auth_session_refreshed[:]
        result["auth_session_refresh_failed_emails"] = [item for item in auth_session_refresh_failed if item not in success_set]
        result["user_paid_skip_emails"] = user_paid_skip[:]
        result["pending_retry_attempts"] = pending_retry_attempts
        if blocked or rejected or payment_failed or nonzero_blocked or failed:
            result["rotated_from"] = requested_email
        return result

    for index, candidate in enumerate(candidates, 1):
        if cancel_requested():
            return _build_result(
                "failed",
                failure_stage="generate_checkout",
                message="任务已取消",
            )
        if skip_requested():
            skipped_by_user.append(candidate)
            clear_skip_request()
            logger.info(
                "[gopay_executor] user skipped GoPay candidate before start: email=%s",
                _safe_email_summary(candidate),
            )
            emit(
                "gopay_account_skipped_by_user",
                email=candidate,
                attempted=len(attempted),
                remaining_candidates=max(0, len(candidates) - index),
                message=f"已跳过当前账号: {candidate}",
            )
            continue

        remaining = _approve_blocked_remaining(candidate)
        if remaining > 0:
            skipped_cooldown.append(candidate)
            logger.info(
                "[gopay_executor] skip GoPay candidate because chatgpt_approve cooldown is active: email=%s remaining_seconds=%s",
                _safe_email_summary(candidate),
                remaining,
            )
            emit("gopay_account_skipped_cooldown", email=candidate, remaining_seconds=remaining)
            queue_pending_retry(candidate, reason="local_cooldown", stage="gopay_account_skipped_cooldown")
            continue

        attempted.append(candidate)
        logger.info(
            "[gopay_executor] trying GoPay candidate: email=%s attempt=%s/%s",
            _safe_email_summary(candidate),
            index,
            len(candidates),
        )
        if candidate != requested_email:
            emit("gopay_rotate_account", email=candidate, attempt=index, total=len(candidates))
        else:
            emit("gopay_try_account", email=candidate, attempt=index, total=len(candidates))

        result = run_once(candidate, index)
        if _is_chatgpt_user_paid_result(result):
            result = _as_chatgpt_user_paid_success(result, checkout_url=final_checkout_url)
            append_unique(user_paid_skip, candidate)
            emit("chatgpt_user_paid_skip", email=candidate, message=result.get("message") or "")
        result["email_used"] = candidate
        result["requested_email"] = requested_email
        result["attempted_emails"] = attempted[:]

        if skip_requested() and not cancel_requested() and result.get("status") != "success":
            skipped_by_user.append(candidate)
            clear_skip_request()
            logger.info(
                "[gopay_executor] user skipped GoPay candidate during attempt: email=%s status=%s failure_stage=%s",
                _safe_email_summary(candidate),
                result.get("status") or "",
                result.get("failure_stage") or "",
            )
            emit(
                "gopay_account_skipped_by_user",
                email=candidate,
                attempted=len(attempted),
                remaining_candidates=max(0, len(candidates) - index),
                message=f"已跳过当前账号: {candidate}",
            )
            continue

        if _is_chatgpt_approve_blocked_result(result):
            cooldown = int(_mark_approve_blocked(candidate))
            blocked.append(candidate)
            last_blocked_result = result
            last_blocked_email = candidate
            logger.info(
                "[gopay_executor] GoPay candidate blocked at chatgpt_approve, rotating: email=%s cooldown_seconds=%s message=%s",
                _safe_email_summary(candidate),
                cooldown,
                _compact_log_text(result.get("message") or "", limit=180),
            )
            emit(
                "chatgpt_approve_blocked_rotate",
                email=candidate,
                cooldown_seconds=cooldown,
                attempted=len(attempted),
                remaining_candidates=max(0, len(candidates) - index),
            )
            if pending_retry_attempts > 0:
                queue_pending_retry(candidate, reason="chatgpt_approve_blocked", stage="chatgpt_approve_blocked_rotate")
            continue

        if _is_chatgpt_token_invalidated_result(result):
            if pending_retry_attempts > 0 and refresh_auth_session_for_retry(candidate, result):
                queue_pending_retry(candidate, reason="auth_session_refreshed", stage="gopay_auth_session_refresh_done")
                continue

        retry_reason = _gopay_pending_retry_reason(result)
        if retry_reason and pending_retry_attempts > 0:
            source_stage = _gopay_pending_retry_source_stage(result, retry_reason)
            logger.info(
                "[gopay_executor] GoPay candidate returned retryable failure, queue pending retry: email=%s reason=%s stage=%s message=%s",
                _safe_email_summary(candidate),
                retry_reason,
                result.get("failure_stage") or "",
                _compact_log_text(result.get("message") or "", limit=180),
            )
            emit(
                source_stage,
                email=candidate,
                attempted=len(attempted),
                remaining_candidates=max(0, len(candidates) - index),
                failure_stage=result.get("failure_stage") or "",
                reason=retry_reason,
                message=(
                    "当前账号遇到可重试失败，先切换下一个账号，稍后重试: "
                    f"{_compact_log_text(result.get('message') or '', limit=180)}"
                ),
            )
            queue_pending_retry(candidate, reason=retry_reason, stage=source_stage)
            continue

        if _is_checkout_payment_not_approved_result(result):
            rejected.append(candidate)
            last_rejected_result = result
            last_rejected_email = candidate
            not_approved_message = (
                f"付款未获批准，当前账号将从号池删除并停止本次账号尝试: "
                f"{_compact_log_text(result.get('message') or '付款未获批准', limit=180)}"
            )
            logger.info(
                "[gopay_executor] GoPay candidate checkout payment not approved, rotating and marking for pool deletion: email=%s message=%s",
                _safe_email_summary(candidate),
                _compact_log_text(result.get("message") or "", limit=180),
            )
            emit(
                "checkout_not_approved_rotate",
                email=candidate,
                message=not_approved_message,
                attempted=len(attempted),
                remaining_candidates=max(0, len(candidates) - index),
            )
            continue

        if _is_gopay_payment_process_rotatable_result(result):
            payment_failed.append(candidate)
            last_payment_failed_result = result
            last_payment_failed_email = candidate
            logger.info(
                "[gopay_executor] GoPay candidate payment/process failed with wallet auth error, rotating: email=%s message=%s",
                _safe_email_summary(candidate),
                _compact_log_text(result.get("message") or "", limit=180),
            )
            emit(
                "gopay_payment_process_failed_rotate",
                email=candidate,
                attempted=len(attempted),
                remaining_candidates=max(0, len(candidates) - index),
                message=(
                    "GoPay 钱包扣款授权失败，切换下一个账号: "
                    f"{_compact_log_text(result.get('message') or 'gopay_payment_process failed', limit=180)}"
                ),
            )
            continue

        if _is_gopay_nonzero_amount_blocked_result(result):
            nonzero_blocked.append(candidate)
            last_nonzero_blocked_result = result
            last_nonzero_blocked_email = candidate
            logger.info(
                "[gopay_executor] GoPay candidate blocked by non-zero amount guard, rotating: email=%s stage=%s message=%s",
                _safe_email_summary(candidate),
                result.get("failure_stage") or "",
                _compact_log_text(result.get("message") or "", limit=180),
            )
            emit(
                "gopay_nonzero_amount_blocked_rotate",
                email=candidate,
                attempted=len(attempted),
                remaining_candidates=max(0, len(candidates) - index),
                message=(
                    "账单金额非 0，当前账号停止并切换下一个账号: "
                    f"{_compact_log_text(result.get('message') or '', limit=180)}"
                ),
            )
            continue

        if result.get("status") != "success" and not _is_gopay_already_linked_result(result):
            if cancel_requested() or str(result.get("failure_stage") or "") == "cancelled":
                return result
            failed.append(candidate)
            last_failed_result = result
            last_failed_email = candidate
            if _is_chatgpt_token_invalidated_result(result):
                append_unique(token_invalidated, candidate)
            logger.info(
                "[gopay_executor] GoPay candidate failed, rotating: email=%s status=%s failure_stage=%s message=%s",
                _safe_email_summary(candidate),
                result.get("status") or "",
                result.get("failure_stage") or "",
                _compact_log_text(result.get("message") or "", limit=180),
            )
            emit(
                "gopay_account_failed_rotate",
                email=candidate,
                attempted=len(attempted),
                remaining_candidates=max(0, len(candidates) - index),
                failure_stage=result.get("failure_stage") or "",
                token_invalidated=_is_chatgpt_token_invalidated_result(result),
                message=(
                    "当前账号 GoPay 任务失败，切换下一个账号: "
                    f"{_compact_log_text(result.get('message') or '', limit=180)}"
                ),
            )
            continue

        attach_common_lists(result)

        if result.get("status") == "success":
            mark_candidate_successful(candidate)
            last_success_result = dict(result)
            last_success_email = candidate
            logger.info(
                "[gopay_executor] GoPay candidate succeeded, continuing batch: email=%s remaining_candidates=%s",
                _safe_email_summary(candidate),
                max(0, len(candidates) - index),
            )
            emit(
                "gopay_account_bound",
                email=candidate,
                checkout_url=result.get("checkout_url") or "",
                attempted=len(attempted),
                successful=len(successful),
                remaining_candidates=max(0, len(candidates) - index),
                message=f"当前账号 GoPay 绑定成功: {candidate}",
            )
            continue

        logger.info(
            "[gopay_executor] GoPay candidate finished without approve-block rotation: email=%s status=%s failure_stage=%s",
            _safe_email_summary(candidate),
            result.get("status") or "",
            result.get("failure_stage") or "",
        )
        return result

    retry_attempt_index = 0
    for retry_round in range(1, pending_retry_attempts + 1):
        retry_candidates = pending_retry[:]
        if not retry_candidates:
            break
        wait_seconds = pending_retry_backoffs[min(retry_round - 1, len(pending_retry_backoffs) - 1)]
        logger.info(
            "[gopay_executor] waiting before GoPay pending retry round: round=%s/%s wait=%ss pending=%s",
            retry_round,
            pending_retry_attempts,
            wait_seconds,
            [_safe_email_summary(candidate) for candidate in retry_candidates],
        )
        emit(
            "gopay_pending_retry_wait",
            retry_round=retry_round,
            max_retry_rounds=pending_retry_attempts,
            delay_seconds=wait_seconds,
            pending_retry=len(retry_candidates),
            message=f"待重试第 {retry_round}/{pending_retry_attempts} 轮将在 {wait_seconds:.0f}s 后开始",
        )
        if cancel_requested():
            return _build_result("failed", failure_stage="generate_checkout", message="任务已取消")
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        if cancel_requested():
            return _build_result("failed", failure_stage="generate_checkout", message="任务已取消")

        logger.info(
            "[gopay_executor] retrying GoPay pending candidates: round=%s/%s pending=%s",
            retry_round,
            pending_retry_attempts,
            [_safe_email_summary(candidate) for candidate in retry_candidates],
        )
        emit(
            "gopay_pending_retry_started",
            retry_round=retry_round,
            max_retry_rounds=pending_retry_attempts,
            pending_retry=len(retry_candidates),
            message=f"开始第 {retry_round}/{pending_retry_attempts} 轮待重试，共 {len(retry_candidates)} 个账号",
        )

        for retry_offset, candidate in enumerate(retry_candidates, 1):
            if cancel_requested():
                return _build_result(
                    "failed",
                    failure_stage="generate_checkout",
                    message="任务已取消",
                )
            append_unique(retried, candidate)
            append_unique(attempted, candidate)
            remove_email(pending_retry, candidate)
            retry_attempt_index += 1
            emit(
                "gopay_pending_retry_account",
                email=candidate,
                attempt=retry_offset,
                total=len(retry_candidates),
                retry_round=retry_round,
                max_retry_rounds=pending_retry_attempts,
                pending_retry=len(pending_retry),
                message=f"正在执行第 {retry_round}/{pending_retry_attempts} 轮待重试: {candidate}",
            )
            logger.info(
                "[gopay_executor] retrying pending GoPay candidate: email=%s round=%s/%s retry=%s/%s",
                _safe_email_summary(candidate),
                retry_round,
                pending_retry_attempts,
                retry_offset,
                len(retry_candidates),
            )
            result = run_once(candidate, len(candidates) + retry_attempt_index)
            if _is_chatgpt_user_paid_result(result):
                result = _as_chatgpt_user_paid_success(result, checkout_url=final_checkout_url)
                append_unique(user_paid_skip, candidate)
                emit("chatgpt_user_paid_skip", email=candidate, retry_round=retry_round, message=result.get("message") or "")
            result["email_used"] = candidate
            result["requested_email"] = requested_email
            result["attempted_emails"] = attempted[:]
            result["retried_emails"] = retried[:]

            if result.get("status") == "success":
                mark_candidate_successful(candidate)
                last_success_result = dict(result)
                last_success_email = candidate
                logger.info(
                    "[gopay_executor] pending GoPay retry succeeded: email=%s round=%s/%s",
                    _safe_email_summary(candidate),
                    retry_round,
                    pending_retry_attempts,
                )
                emit(
                    "gopay_account_bound",
                    email=candidate,
                    checkout_url=result.get("checkout_url") or "",
                    attempted=len(attempted),
                    successful=len(successful),
                    remaining_candidates=max(0, len(pending_retry)),
                    retry_round=retry_round,
                    max_retry_rounds=pending_retry_attempts,
                    message=f"当前账号 GoPay 绑定成功: {candidate}",
                )
                continue

            failure_stage = result.get("failure_stage") or ""
            failure_message = result.get("message") or ""
            if _is_chatgpt_approve_blocked_result(result):
                append_unique(blocked, candidate)
                last_blocked_result = result
                last_blocked_email = candidate
                emit(
                    "gopay_pending_retry_failed",
                    email=candidate,
                    retry_round=retry_round,
                    max_retry_rounds=pending_retry_attempts,
                    failure_stage=failure_stage,
                    message=failure_message,
                )
                if retry_round < pending_retry_attempts:
                    queue_pending_retry(
                        candidate,
                        reason="chatgpt_approve_blocked",
                        stage="gopay_pending_retry_failed",
                        retry_round=retry_round,
                    )
                continue
            retry_reason = _gopay_pending_retry_reason(result)
            if retry_reason and retry_round < pending_retry_attempts:
                emit(
                    "gopay_pending_retry_failed",
                    email=candidate,
                    retry_round=retry_round,
                    max_retry_rounds=pending_retry_attempts,
                    failure_stage=failure_stage,
                    reason=retry_reason,
                    message=failure_message,
                )
                queue_pending_retry(
                    candidate,
                    reason=retry_reason,
                    stage="gopay_pending_retry_failed",
                    retry_round=retry_round,
                )
                continue
            if _is_chatgpt_token_invalidated_result(result):
                remove_email(blocked, candidate)
                remove_email(skipped_cooldown, candidate)
                if retry_round < pending_retry_attempts and refresh_auth_session_for_retry(candidate, result, retry_round=retry_round):
                    emit(
                        "gopay_pending_retry_failed",
                        email=candidate,
                        retry_round=retry_round,
                        max_retry_rounds=pending_retry_attempts,
                        failure_stage=failure_stage,
                        reason="auth_session_refreshed",
                        message="auth_session 已刷新，加入下一轮 GoPay 重试",
                    )
                    queue_pending_retry(
                        candidate,
                        reason="auth_session_refreshed",
                        stage="gopay_auth_session_refresh_done",
                        retry_round=retry_round,
                    )
                    continue
                append_unique(failed, candidate)
                append_unique(token_invalidated, candidate)
                last_failed_result = result
                last_failed_email = candidate
                emit(
                    "gopay_pending_retry_failed",
                    email=candidate,
                    retry_round=retry_round,
                    max_retry_rounds=pending_retry_attempts,
                    failure_stage=failure_stage,
                    reason="token_invalidated",
                    message=failure_message,
                )
                continue
            if _is_checkout_payment_not_approved_result(result):
                remove_email(blocked, candidate)
                remove_email(skipped_cooldown, candidate)
                append_unique(rejected, candidate)
                last_rejected_result = result
                last_rejected_email = candidate
                emit("gopay_pending_retry_failed", email=candidate, retry_round=retry_round, max_retry_rounds=pending_retry_attempts, failure_stage=failure_stage, message=failure_message)
                continue
            if _is_gopay_payment_process_rotatable_result(result):
                remove_email(blocked, candidate)
                remove_email(skipped_cooldown, candidate)
                append_unique(payment_failed, candidate)
                last_payment_failed_result = result
                last_payment_failed_email = candidate
                emit("gopay_pending_retry_failed", email=candidate, retry_round=retry_round, max_retry_rounds=pending_retry_attempts, failure_stage=failure_stage, message=failure_message)
                continue
            if _is_gopay_nonzero_amount_blocked_result(result):
                remove_email(blocked, candidate)
                remove_email(skipped_cooldown, candidate)
                append_unique(nonzero_blocked, candidate)
                last_nonzero_blocked_result = result
                last_nonzero_blocked_email = candidate
                emit("gopay_pending_retry_failed", email=candidate, retry_round=retry_round, max_retry_rounds=pending_retry_attempts, failure_stage=failure_stage, message=failure_message)
                continue
            if _is_gopay_already_linked_result(result):
                remove_email(blocked, candidate)
                remove_email(skipped_cooldown, candidate)
                append_unique(failed, candidate)
                last_failed_result = result
                last_failed_email = candidate
                emit("gopay_pending_retry_failed", email=candidate, retry_round=retry_round, max_retry_rounds=pending_retry_attempts, failure_stage=failure_stage, reason="gopay_already_linked", message=failure_message)
                continue
            if result.get("status") != "success" and not _is_gopay_already_linked_result(result):
                if cancel_requested() or str(result.get("failure_stage") or "") == "cancelled":
                    return result
                remove_email(blocked, candidate)
                remove_email(skipped_cooldown, candidate)
                append_unique(failed, candidate)
                last_failed_result = result
                last_failed_email = candidate
                if _is_chatgpt_token_invalidated_result(result):
                    append_unique(token_invalidated, candidate)
                emit("gopay_pending_retry_failed", email=candidate, retry_round=retry_round, max_retry_rounds=pending_retry_attempts, failure_stage=failure_stage, message=failure_message)
                continue

            logger.info(
                "[gopay_executor] pending GoPay retry finished with terminal non-success result: email=%s status=%s failure_stage=%s",
                _safe_email_summary(candidate),
                result.get("status") or "",
                result.get("failure_stage") or "",
            )
            return attach_common_lists(result)

    if last_success_result:
        last_success_result = dict(last_success_result)
        last_success_result["message"] = f"GoPay 批量绑定完成: 成功 {len(successful)}/{len(candidates)} 个账号"
        attach_common_lists(last_success_result)
        last_success_result["attempted_emails"] = attempted[:]
        last_success_result["email_used"] = last_success_email or (successful[-1] if successful else requested_email)
        last_success_result["requested_email"] = requested_email
        emit("gopay_batch_completed", attempted=len(attempted), successful=len(successful))
        logger.info(
            "[gopay_executor] GoPay batch completed: attempted=%s successful=%s blocked=%s rejected=%s payment_failed=%s nonzero_blocked=%s failed=%s skipped=%s",
            len(attempted),
            [_safe_email_summary(candidate) for candidate in successful],
            [_safe_email_summary(candidate) for candidate in blocked],
            [_safe_email_summary(candidate) for candidate in rejected],
            [_safe_email_summary(candidate) for candidate in payment_failed],
            [_safe_email_summary(candidate) for candidate in nonzero_blocked],
            [_safe_email_summary(candidate) for candidate in failed],
            [_safe_email_summary(candidate) for candidate in skipped_by_user],
        )
        return last_success_result

    if last_failed_result:
        last_failed_result = dict(last_failed_result)
        if _is_midtrans_linking_rate_limited_result(last_failed_result):
            last_failed_result["message"] = "GoPay/Midtrans 限流，请稍后重试"
        else:
            last_failed_result["message"] = f"GoPay 批量绑定失败: 尝试 {len(attempted)} 个账号均未成功"
        last_failed_result["failed_emails"] = failed[:]
        last_failed_result["token_invalidated_emails"] = token_invalidated[:]
        last_failed_result["blocked_emails"] = blocked[:]
        last_failed_result["rejected_emails"] = rejected[:]
        last_failed_result["payment_failed_emails"] = payment_failed[:]
        last_failed_result["nonzero_blocked_emails"] = nonzero_blocked[:]
        last_failed_result["skipped_cooldown_emails"] = skipped_cooldown[:]
        last_failed_result["skipped_emails"] = skipped_by_user[:]
        last_failed_result["pending_retry_emails"] = pending_retry[:]
        last_failed_result["retried_emails"] = retried[:]
        last_failed_result["auth_session_refreshed_emails"] = auth_session_refreshed[:]
        last_failed_result["auth_session_refresh_failed_emails"] = auth_session_refresh_failed[:]
        last_failed_result["attempted_emails"] = attempted[:]
        last_failed_result["email_used"] = last_failed_email or (attempted[-1] if attempted else requested_email)
        last_failed_result["requested_email"] = requested_email
        emit("gopay_all_accounts_failed", attempted=len(attempted), failed=len(failed))
        logger.info(
            "[gopay_executor] all GoPay candidates failed without terminal already-linked error: attempted=%s failed=%s token_invalidated=%s",
            len(attempted),
            [_safe_email_summary(candidate) for candidate in failed],
            [_safe_email_summary(candidate) for candidate in token_invalidated],
        )
        return last_failed_result

    if last_rejected_result and not last_blocked_result and not last_payment_failed_result and not last_nonzero_blocked_result:
        last_rejected_result = dict(last_rejected_result)
        last_rejected_result["rejected_emails"] = rejected[:]
        last_rejected_result["payment_failed_emails"] = payment_failed[:]
        last_rejected_result["nonzero_blocked_emails"] = nonzero_blocked[:]
        last_rejected_result["failed_emails"] = failed[:]
        last_rejected_result["token_invalidated_emails"] = token_invalidated[:]
        last_rejected_result["skipped_emails"] = skipped_by_user[:]
        last_rejected_result["pending_retry_emails"] = pending_retry[:]
        last_rejected_result["retried_emails"] = retried[:]
        last_rejected_result["auth_session_refreshed_emails"] = auth_session_refreshed[:]
        last_rejected_result["auth_session_refresh_failed_emails"] = auth_session_refresh_failed[:]
        last_rejected_result["attempted_emails"] = attempted[:]
        last_rejected_result["email_used"] = last_rejected_email or (attempted[-1] if attempted else requested_email)
        last_rejected_result["requested_email"] = requested_email
        emit("gopay_all_accounts_rejected", attempted=len(attempted), rejected=len(rejected))
        logger.info(
            "[gopay_executor] all GoPay candidates rejected by checkout payment approval: attempted=%s rejected=%s",
            len(attempted),
            [_safe_email_summary(candidate) for candidate in rejected],
        )
        return last_rejected_result

    if last_payment_failed_result and not last_blocked_result and not last_nonzero_blocked_result:
        last_payment_failed_result = dict(last_payment_failed_result)
        last_payment_failed_result["payment_failed_emails"] = payment_failed[:]
        last_payment_failed_result["rejected_emails"] = rejected[:]
        last_payment_failed_result["nonzero_blocked_emails"] = nonzero_blocked[:]
        last_payment_failed_result["failed_emails"] = failed[:]
        last_payment_failed_result["token_invalidated_emails"] = token_invalidated[:]
        last_payment_failed_result["skipped_emails"] = skipped_by_user[:]
        last_payment_failed_result["pending_retry_emails"] = pending_retry[:]
        last_payment_failed_result["retried_emails"] = retried[:]
        last_payment_failed_result["auth_session_refreshed_emails"] = auth_session_refreshed[:]
        last_payment_failed_result["auth_session_refresh_failed_emails"] = auth_session_refresh_failed[:]
        last_payment_failed_result["attempted_emails"] = attempted[:]
        last_payment_failed_result["email_used"] = last_payment_failed_email or (attempted[-1] if attempted else requested_email)
        last_payment_failed_result["requested_email"] = requested_email
        emit("gopay_all_payment_process_failed", attempted=len(attempted), payment_failed=len(payment_failed))
        logger.info(
            "[gopay_executor] all GoPay candidates failed at payment/process wallet auth: attempted=%s payment_failed=%s",
            len(attempted),
            [_safe_email_summary(candidate) for candidate in payment_failed],
        )
        return last_payment_failed_result

    if last_nonzero_blocked_result and not last_blocked_result:
        last_nonzero_blocked_result = dict(last_nonzero_blocked_result)
        last_nonzero_blocked_result["nonzero_blocked_emails"] = nonzero_blocked[:]
        last_nonzero_blocked_result["payment_failed_emails"] = payment_failed[:]
        last_nonzero_blocked_result["rejected_emails"] = rejected[:]
        last_nonzero_blocked_result["failed_emails"] = failed[:]
        last_nonzero_blocked_result["token_invalidated_emails"] = token_invalidated[:]
        last_nonzero_blocked_result["skipped_emails"] = skipped_by_user[:]
        last_nonzero_blocked_result["pending_retry_emails"] = pending_retry[:]
        last_nonzero_blocked_result["retried_emails"] = retried[:]
        last_nonzero_blocked_result["auth_session_refreshed_emails"] = auth_session_refreshed[:]
        last_nonzero_blocked_result["auth_session_refresh_failed_emails"] = auth_session_refresh_failed[:]
        last_nonzero_blocked_result["attempted_emails"] = attempted[:]
        last_nonzero_blocked_result["email_used"] = last_nonzero_blocked_email or (attempted[-1] if attempted else requested_email)
        last_nonzero_blocked_result["requested_email"] = requested_email
        emit("gopay_all_nonzero_amount_blocked", attempted=len(attempted), nonzero_blocked=len(nonzero_blocked))
        logger.info(
            "[gopay_executor] all GoPay candidates blocked by non-zero amount guard: attempted=%s nonzero_blocked=%s",
            len(attempted),
            [_safe_email_summary(candidate) for candidate in nonzero_blocked],
        )
        return last_nonzero_blocked_result

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
        last_blocked_result["rejected_emails"] = rejected[:]
        last_blocked_result["payment_failed_emails"] = payment_failed[:]
        last_blocked_result["nonzero_blocked_emails"] = nonzero_blocked[:]
        last_blocked_result["failed_emails"] = failed[:]
        last_blocked_result["token_invalidated_emails"] = token_invalidated[:]
        last_blocked_result["skipped_cooldown_emails"] = skipped_cooldown[:]
        last_blocked_result["skipped_emails"] = skipped_by_user[:]
        last_blocked_result["pending_retry_emails"] = pending_retry[:]
        last_blocked_result["retried_emails"] = retried[:]
        last_blocked_result["auth_session_refreshed_emails"] = auth_session_refreshed[:]
        last_blocked_result["auth_session_refresh_failed_emails"] = auth_session_refresh_failed[:]
        last_blocked_result["attempted_emails"] = attempted[:]
        last_blocked_result["email_used"] = last_blocked_email or (attempted[-1] if attempted else requested_email)
        last_blocked_result["requested_email"] = requested_email
        emit("gopay_all_accounts_blocked", attempted=len(attempted), skipped_cooldown=len(skipped_cooldown))
        logger.info(
            "[gopay_executor] all GoPay candidates blocked or cooling down: attempted=%s blocked=%s skipped_cooldown=%s",
            len(attempted),
            [_safe_email_summary(candidate) for candidate in blocked],
            [_safe_email_summary(candidate) for candidate in skipped_cooldown],
        )
        return last_blocked_result

    if skipped_by_user:
        logger.info(
            "[gopay_executor] all remaining GoPay candidates skipped by user: skipped=%s",
            [_safe_email_summary(candidate) for candidate in skipped_by_user],
        )
        emit("gopay_all_accounts_skipped", skipped=len(skipped_by_user), attempted=len(attempted))
        result = _build_result(
            "failed",
            failure_stage="skipped",
            message="已跳过所有候选账号，任务结束",
            billing_info=_public_billing_info(billing_info or {}),
        )
        result["skipped_emails"] = skipped_by_user[:]
        result["attempted_emails"] = attempted[:]
        result["pending_retry_emails"] = pending_retry[:]
        result["retried_emails"] = retried[:]
        return result

    logger.info(
        "[gopay_executor] no GoPay candidates available because all are cooling down: skipped_cooldown=%s",
        [_safe_email_summary(candidate) for candidate in skipped_cooldown],
    )
    return _build_result(
        "failed",
        failure_stage="chatgpt_approve",
        message="所有候选 auth_session 仍在 chatgpt_approve 冷却中，请稍后重试",
        billing_info=_public_billing_info(billing_info or {}),
    )
