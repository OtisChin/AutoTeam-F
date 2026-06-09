"""SMS OTP extraction, fetching, and polling helpers shared by auth flows."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from autotoken.core.redaction import (
    compact_log_text as _compact_log_text,
)
from autotoken.core.redaction import (
    safe_error_summary as _safe_error_summary,
)
from autotoken.core.redaction import (
    safe_otp_summary as _safe_otp_summary,
)

logger = logging.getLogger(__name__)

SMS_OTP_DEFAULT_DELAY_SECONDS = 60.0
SMS_OTP_DEFAULT_RESEND_AFTER_SECONDS = 120.0

_SMS_CODE_PATTERN = re.compile(r"(?<!\d)(\d{5,8})(?!\d)")
_SMS_DIRECT_CODE_PATTERN = re.compile(r"\s*#?(\d{5,8})\s*")
_SMS_STATUS_CODE_PATTERN = re.compile(r"(?i)\b(?:SMS[-_\s]?OK|OK)\b\D{0,20}(\d{5,8})(?!\d)")
_SMS_OTP_CONTEXT_PATTERN = re.compile(
    r"(?i)(otp|one[-\s]?time|verification|verify|security|auth(?:entication)?|"
    r"passcode|code|kode|验证码|驗證碼|认证码|認證碼|确认码|確認碼|校验码|驗證|验证|短信|"
    r"セキュリティコード|認証コード|確認コード|コード)"
)
_SMS_NON_OTP_NOTICE_PATTERN = re.compile(
    r"(?i)(thanks for confirming|transaction alerts|log in or get the app|"
    r"confirmed your phone|phone number has been confirmed)"
)
_SMS_URL_PATTERN = re.compile(r"(?i)\b(?:https?://|www\.)\S+")


class SmsOtpCancelled(RuntimeError):
    """Raised when SMS OTP polling is cancelled or reaches a configured stop condition."""


def _env_float(name: str, default: float) -> float:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except Exception:
        return default


def _cancelled_error(message: str) -> SmsOtpCancelled:
    return SmsOtpCancelled(message)


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


def extract_sms_codes(text: str) -> list[str]:
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
            window = cleaned[max(0, start - 60) : min(len(cleaned), end + 60)]
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
                    value = normalized.get(key)
                    codes = codes_from_text(value)
                    if not codes and isinstance(value, (dict, list)):
                        codes = scan(value)
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
                extract_sms_codes(json.dumps(item, ensure_ascii=False) if isinstance(item, (dict, list)) else str(item))
            )
        return _dedupe_codes(codes)

    return codes_from_text(raw)


def extract_sms_code(text: str) -> str:
    codes = extract_sms_codes(text)
    return codes[0] if codes else ""


def normalize_local_gopay_signup_bridge_url(sms_url: str, *, local_base_url: str | None = None) -> str:
    raw = str(sms_url or "").strip()
    if "/otp/gopay-signup/" not in raw:
        return raw
    try:
        parsed = urlsplit(raw)
    except Exception:
        return raw
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return raw
    base = str(local_base_url if local_base_url is not None else os.environ.get("AUTOTOKEN_LOCAL_BASE_URL") or "")
    base = base.strip().rstrip("/")
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


def gopay_signup_bridge_resend_url(sms_url: str, *, local_base_url: str | None = None) -> str:
    raw = normalize_local_gopay_signup_bridge_url(sms_url, local_base_url=local_base_url)
    if "/otp/gopay-signup/" not in raw:
        return ""
    parsed = urlsplit(raw)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["resend"] = "1"
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def trigger_gopay_signup_bridge_resend(
    sms_url: str,
    *,
    http_get: Callable[..., Any] | None = None,
    local_base_url: str | None = None,
) -> bool:
    resend_url = gopay_signup_bridge_resend_url(sms_url, local_base_url=local_base_url)
    if not resend_url:
        return False
    get = http_get or requests.get
    resp = get(
        resend_url,
        timeout=20,
        verify=False,
        headers={
            "User-Agent": "Mozilla/5.0 AutoToken/1.0",
            "Accept": "application/json, text/plain, text/html, */*",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    text = (resp.text or "").strip()
    if not resp.ok:
        raise RuntimeError(text[:200] or f"短信平台重发接口返回异常({resp.status_code})")
    return True


def fetch_sms_code(
    sms_url: str,
    ignored_otps: set[str] | None = None,
    *,
    http_get: Callable[..., Any] | None = None,
    local_base_url: str | None = None,
    whatsapp_listener_factory: Callable[[], Any] | None = None,
) -> str:
    sms_url = normalize_local_gopay_signup_bridge_url(sms_url, local_base_url=local_base_url)
    is_whatsapp_otp_url = "/otp/whatsapp/" in str(sms_url or "").lower()
    source_label = "WhatsApp 监听" if is_whatsapp_otp_url else "接码接口"
    ignored = {str(item or "").strip() for item in (ignored_otps or set()) if str(item or "").strip()}

    if is_whatsapp_otp_url:
        try:
            if whatsapp_listener_factory is None:
                from autotoken.payments.whatsapp_otp import get_default_listener

                whatsapp_listener_factory = get_default_listener
            payload = whatsapp_listener_factory().latest_response(max_age_seconds=600)
            text = json.dumps(payload, ensure_ascii=False)
            direct_otp = str(
                ((payload.get("data") or {}) if isinstance(payload, dict) else {}).get("otp") or ""
            ).strip()
            if re.fullmatch(r"\d{6}", direct_otp):
                if direct_otp not in ignored:
                    return direct_otp
                raise RuntimeError(f"{source_label}仍返回旧验证码，等待新码: {_compact_log_text(text, limit=220)}")
            codes = extract_sms_codes(text)
            for code in codes:
                if code not in ignored:
                    return code
            if codes:
                raise RuntimeError(f"{source_label}仍返回旧验证码，等待新码: {_compact_log_text(text, limit=220)}")
        except RuntimeError:
            raise
        except Exception as exc:
            logger.debug("in-process WhatsApp OTP lookup failed, falling back to HTTP: %s", exc)

    get = http_get or requests.get
    resp = get(
        sms_url,
        timeout=20,
        verify=False,
        headers={
            "User-Agent": "Mozilla/5.0 AutoToken/1.0",
            "Accept": "application/json, text/plain, text/html, */*",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    text = (resp.text or "").strip()
    if not resp.ok:
        raise RuntimeError(text[:200] or f"{source_label}返回异常({resp.status_code})")
    codes = extract_sms_codes(text)
    for code in codes:
        if code not in ignored:
            return code
    if codes:
        raise RuntimeError(f"{source_label}仍返回旧验证码，等待新码: {_compact_log_text(text, limit=220)}")
    raise RuntimeError(f"{source_label}暂无验证码: {_compact_log_text(text, limit=220)}")


def poll_otp_from_sms_url(
    sms_url: str,
    *,
    timeout_seconds: int,
    initial_delay_seconds: float | None = None,
    resend_after_seconds: float | None = None,
    max_resend_attempts: int | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    progress: Callable[..., None] | None = None,
    cancelled_error_factory: Callable[[str], Exception] | None = None,
    fetch_sms_code_fn: Callable[..., str] | None = None,
    bridge_resend_url_fn: Callable[[str], str] | None = None,
    trigger_bridge_resend_fn: Callable[[str], bool] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
    time_fn: Callable[[], float] | None = None,
    env_float_fn: Callable[[str, float], float] | None = None,
) -> Callable[[], str]:
    make_cancelled = cancelled_error_factory or _cancelled_error
    fetch_code = fetch_sms_code_fn or fetch_sms_code
    bridge_resend_url = bridge_resend_url_fn or (lambda url: gopay_signup_bridge_resend_url(url))
    trigger_bridge_resend = trigger_bridge_resend_fn or trigger_gopay_signup_bridge_resend
    sleep = sleep_fn or time.sleep
    now = time_fn or time.time
    env_float = env_float_fn or _env_float

    def provider() -> str:
        if not sms_url:
            raise make_cancelled("缺少 OTP 接口 URL")
        delay_seconds = (
            env_float("GOPAY_SMS_OTP_DELAY_SECONDS", SMS_OTP_DEFAULT_DELAY_SECONDS)
            if initial_delay_seconds is None
            else float(initial_delay_seconds or 0)
        )
        resend_interval = (
            env_float("GOPAY_SMS_OTP_RESEND_AFTER_SECONDS", SMS_OTP_DEFAULT_RESEND_AFTER_SECONDS)
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
                    raise make_cancelled("任务已取消")
                step = min(1.0, delay_seconds - waited)
                sleep(step)
                waited += step
        deadline = now() + max(60, int(timeout_seconds or 300))
        next_resend_at = now() + max(0.0, resend_interval) if resend_interval > 0 else 0.0
        while now() < deadline:
            if callable(is_cancelled) and is_cancelled():
                raise make_cancelled("任务已取消")
            if callable(progress):
                progress("fetch_otp")
            try:
                ignored_otps = getattr(provider, "_gopay_ignored_otps", set())
                ignored = {str(item or "").strip() for item in ignored_otps if str(item or "").strip()}
                code = fetch_code(sms_url, ignored_otps=ignored)
                if code:
                    if str(code).strip() in ignored:
                        logger.info("ignored previously failed OTP: %s", _safe_otp_summary(code))
                    else:
                        return code
            except Exception as exc:
                logger.info("waiting for SMS OTP: %s", exc)
            if next_resend_at and now() >= next_resend_at:
                resend_callback = getattr(provider, "_gopay_resend_callback", None)
                resend_url = bridge_resend_url(sms_url)
                if callable(resend_callback) or resend_url:
                    if resend_limit is not None and resend_attempts >= resend_limit:
                        raise make_cancelled(f"未收到 GoPay OTP，重新发送验证码已达到上限 {resend_limit} 次")
                    if callable(progress):
                        progress("sms_otp_resend_due", wait_seconds=int(resend_interval))
                    resend_attempts += 1
                    try:
                        if resend_url:
                            trigger_bridge_resend(sms_url)
                            if callable(progress):
                                progress("sms_provider_resend_triggered")
                    except Exception as exc:
                        logger.info("SMS provider resend while polling failed: %s", _safe_error_summary(exc))
                        if callable(progress):
                            progress("sms_provider_resend_failed", reason=_safe_error_summary(exc))
                    if callable(resend_callback):
                        try:
                            delay = (
                                max(0.0, env_float("GOPAY_SMS_PROVIDER_RESEND_DELAY_SECONDS", 2.0))
                                if resend_url
                                else 0.0
                            )
                            if delay:
                                sleep(delay)
                            resend_callback()
                        except Exception as exc:
                            logger.info("OTP resend while polling failed: %s", _safe_error_summary(exc))
                            if callable(progress):
                                progress("sms_otp_resend_failed", reason=_safe_error_summary(exc))
                next_resend_at = now() + max(0.0, resend_interval)
            sleep(5)
        raise make_cancelled("等待 GoPay OTP 超时")

    try:
        provider._gopay_sms_url = sms_url
        if bridge_resend_url(sms_url):
            provider._gopay_sms_provider_resend_callback = lambda: trigger_bridge_resend(sms_url)
    except Exception:
        pass
    return provider


def poll_paypal_signup_otp(
    signup_profile: dict[str, Any],
    *,
    timeout_seconds: int,
    otp_poll_timeout_seconds: int,
    resend_after_seconds: int,
    max_resend_attempts: int,
    is_cancelled: Callable[[], bool] | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    progress_event: Callable[..., dict[str, Any]],
    url_summary: Callable[[str], str],
    progress_adapter: Callable[[Callable[[dict[str, Any]], None] | None], Callable[..., None] | None],
    poll_otp_from_sms_url_fn: Callable[..., Callable[[], str]],
    click_resend: Callable[[], bool],
) -> str:
    sms_url = str(signup_profile.get("sms_url") or "").strip()
    if on_progress:
        on_progress(
            progress_event(
                "paypal_wait_signup_otp",
                sms_url=url_summary(sms_url) if sms_url else "",
                otp_channel=str(signup_profile.get("otp_channel") or "sms"),
            )
        )
    provider = poll_otp_from_sms_url_fn(
        sms_url,
        timeout_seconds=min(
            otp_poll_timeout_seconds,
            max(60, int(timeout_seconds or otp_poll_timeout_seconds)),
        ),
        initial_delay_seconds=0,
        resend_after_seconds=resend_after_seconds,
        max_resend_attempts=max_resend_attempts,
        is_cancelled=is_cancelled,
        progress=progress_adapter(on_progress),
    )
    provider._gopay_resend_callback = click_resend
    otp = str(provider() or "").strip()
    if otp and on_progress:
        on_progress(progress_event("paypal_otp_received", otp="******"))
    return otp
