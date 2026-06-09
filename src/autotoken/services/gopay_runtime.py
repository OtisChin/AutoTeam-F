"""GoPay task runtime helpers shared by API orchestration code."""

import os
import random
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit


def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)) or default)
    except Exception:
        return default


def auto_register_bind_delay_seconds() -> float:
    min_seconds = max(0.0, env_float("GOPAY_AUTO_REGISTER_BIND_DELAY_MIN", 10.0))
    max_seconds = max(0.0, env_float("GOPAY_AUTO_REGISTER_BIND_DELAY_MAX", 20.0))
    if max_seconds < min_seconds:
        min_seconds, max_seconds = max_seconds, min_seconds
    if max_seconds <= 0:
        return 0.0
    if max_seconds == min_seconds:
        return min_seconds
    return random.uniform(min_seconds, max_seconds)


def auto_signup_no_transfer_bind_wait_seconds() -> float:
    return max(0.0, env_float("GOPAY_AUTO_SIGNUP_NO_TRANSFER_BIND_WAIT_SECONDS", 60.0))


def auto_signup_no_transfer_retry_waits_seconds() -> list[float]:
    raw = str(os.environ.get("GOPAY_AUTO_SIGNUP_NO_TRANSFER_RETRY_WAITS", "60,120") or "").strip()
    waits: list[float] = []
    for part in re.split(r"[\s,;|]+", raw):
        if not part:
            continue
        try:
            seconds = float(part)
        except Exception:
            continue
        if seconds > 0:
            waits.append(seconds)
    return waits


def wallet_balance_poll_intervals_from_env() -> list[float]:
    raw = str(os.environ.get("GOPAY_WALLET_BALANCE_POLL_INTERVALS", "") or "").strip()
    waits: list[float] = []
    if raw:
        for part in re.split(r"[\s,;|]+", raw):
            if not part:
                continue
            try:
                seconds = float(part)
            except Exception:
                continue
            if seconds > 0:
                waits.append(seconds)
    if waits:
        return waits
    interval = max(1.0, env_float("GOPAY_WALLET_BALANCE_POLL_INTERVAL_SECONDS", 20.0))
    try:
        attempts = max(1, min(30, int(os.environ.get("GOPAY_WALLET_BALANCE_POLL_ATTEMPTS", "6") or "6")))
    except Exception:
        attempts = 6
    return [interval] * attempts


def default_wallet_balance_poll_interval_seconds() -> float:
    intervals = wallet_balance_poll_intervals_from_env()
    for value in intervals:
        try:
            seconds = float(value)
        except Exception:
            continue
        if seconds > 0:
            return seconds
    return 0.0


def default_wallet_balance_wait_seconds() -> float:
    return sum(max(0.0, float(value or 0.0)) for value in wallet_balance_poll_intervals_from_env())


def normalize_runtime_seconds(
    value: int | float | str | None,
    default: int | float,
    *,
    minimum: float = 0.0,
    maximum: float = 1800.0,
) -> float:
    try:
        raw = default if value is None else value
        seconds = float(raw)
    except Exception:
        seconds = float(default or 0.0)
    if seconds < minimum:
        seconds = minimum
    if seconds > maximum:
        seconds = maximum
    return round(seconds, 3)


def build_balance_poll_intervals(total_wait_seconds: float, interval_seconds: float) -> list[float]:
    total_wait = max(0.0, float(total_wait_seconds or 0.0))
    interval = max(0.0, float(interval_seconds or 0.0))
    if total_wait <= 0 or interval <= 0:
        return [0.0]
    intervals: list[float] = []
    remaining = total_wait
    while remaining > 0:
        wait_seconds = min(interval, remaining)
        intervals.append(wait_seconds)
        remaining = max(0.0, remaining - wait_seconds)
        if len(intervals) >= 120:
            break
    return intervals or [0.0]


def normalize_runtime_concurrency(value: int | str | None, default: int = 1) -> int:
    try:
        raw = default if value is None else value
        return max(1, min(10, int(raw or default)))
    except Exception:
        return max(1, min(10, int(default or 1)))


def auto_signup_prefetch_wallets() -> int:
    try:
        return max(0, min(2, int(os.environ.get("GOPAY_AUTO_SIGNUP_PREFETCH_WALLETS", "1") or "1")))
    except Exception:
        return 1


def default_whatsapp_otp_url() -> str:
    base_url = str(os.environ.get("AUTOTOKEN_LOCAL_BASE_URL") or "http://127.0.0.1:8787").strip().rstrip("/")
    return f"{base_url}/otp/whatsapp/latest"


def rewrite_local_signup_url_for_base(sms_url: str, base_url: str) -> str:
    raw = str(sms_url or "").strip()
    base = str(base_url or "").strip().rstrip("/")
    if not raw or not base or "/otp/gopay-signup/" not in raw:
        return raw
    try:
        parsed = urlsplit(raw)
        base_parsed = urlsplit(base)
    except Exception:
        return raw
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return raw
    if not base_parsed.scheme or not base_parsed.netloc:
        return raw
    return urlunsplit((base_parsed.scheme, base_parsed.netloc, parsed.path, parsed.query, parsed.fragment))


def rewrite_phone_account_sms_url_for_base(account: dict[str, Any], base_url: str) -> dict[str, Any]:
    rewritten = dict(account or {})
    sms_url = str(rewritten.get("sms_url") or rewritten.get("smsUrl") or "").strip()
    if sms_url:
        rewritten["sms_url"] = rewrite_local_signup_url_for_base(sms_url, base_url)
    return rewritten


def mask_phone_for_log(phone: str) -> str:
    digits = re.sub(r"\D+", "", str(phone or ""))
    if not digits:
        return ""
    if len(digits) <= 4:
        return "***"
    return f"***{digits[-4:]}(len={len(digits)})"


def normalized_pool_country(value: Any) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    return digits or "62"
