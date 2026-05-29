"""GoPay 自动注册与 Hero-SMS OTP 桥接。"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import random
import re
import string
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

import requests

try:
    from curl_cffi import requests as curl_requests
except Exception:  # pragma: no cover - optional dependency
    curl_requests = None

try:
    from curl_cffi.requests import Session as CurlCffiSession
except Exception:  # pragma: no cover - optional dependency
    CurlCffiSession = None

from autoteam.config import normalize_proxy_url

logger = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 3.0
DEFAULT_AUTO_SIGNUP_OTP_TIMEOUT_SEC = 120
DEFAULT_EXISTING_NUMBER_CANCEL_DELAY_SEC = 120
STATUS_CANCEL = -1
STATUS_RESEND = 3
STATUS_FINISH = 6
DEFAULT_SMSCODE_BASE_URL = "https://api.smscode.gg/v1"

HMAC_KEY = "4&G6DbV&j8QZs~{)(Ila_w_|v@aqJq]E-;*(J9PanZ8sm01kTi{X<iG``]d7P&L"
DEFAULT_X_E2 = "ED9A2B38749FBDE9ACA61D6A685B7"
BASE_URL = "https://accounts.goto-products.com"
API_URL = "https://api.gojekapi.com"
CUSTOMER_URL = "https://customer.gopayapi.com"
CLIENT_ID = "gopay:consumer:app"
CLIENT_SECRET = "raOUumeMRBNifqvZRFjvsgTnjAlaA9"
SIGNUP_BASIC_AUTH = "Basic YmI2NDg0MTMtYjYzNy00NDNhLThlYmYtMTc2Y2Y5YjVkYzMy"
DEFAULT_APP_VERSION = "2.8.0"

PHONE_MODELS = [
    ("Xiaomi", "MI 9"),
    ("HONOR", "BVL-AN20"),
    ("Samsung", "SM-A546B"),
    ("Samsung", "SM-G991B"),
    ("Xiaomi", "M2101K6G"),
    ("Xiaomi", "2201116SG"),
    ("OPPO", "CPH2399"),
    ("vivo", "V2145"),
    ("Realme", "RMX3393"),
    ("Huawei", "NOH-AN00"),
    ("OnePlus", "LE2115"),
]
SCREEN_RESOLUTIONS = ["1080x2400", "1080x2340", "1440x2560", "1080x1920", "1080x2412"]
ANDROID_VERSIONS = ["Android, 11", "Android, 12", "Android, 13", "Android, 14"]
WIFI_PREFIXES = ["TP-Link", "Belkin", "ASUS", "Netgear", "Linksys", "Xiaomi", "Huawei"]
CHIPSET_PROFILES = ["msmnile|1785|8", "kona|1804|8", "lahaina|1804|8", "taro|1804|8"]

_BRIDGE_LOCK = threading.Lock()
_SMS_BRIDGES: dict[str, "GoPaySmsBridge"] = {}


class HeroSmsError(RuntimeError):
    pass


class GoPayAutoSignupError(RuntimeError):
    pass


class GoPayNumberAlreadyRegistered(GoPayAutoSignupError):
    """The SMS number already has a GoPay account."""


class GoPaySignupProbeError(GoPayAutoSignupError):
    """The pre-signup GoPay probe did not return a conclusive result."""


@dataclass(slots=True)
class GoPayAccountResult:
    access_token: str = ""
    refresh_token: str = ""
    account_id: str = ""
    phone: str = ""
    country_code: str = ""
    pin: str = ""
    session: Any = None
    gopay_cfg: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GoPaySmsBridge:
    token: str
    activation_id: str
    base_url: str
    api_key: str
    provider: str = "hero_sms"
    ignored_codes: set[str] = field(default_factory=set)
    closed: bool = False

    def latest_response(self) -> dict[str, Any]:
        if self.closed:
            return {"ok": False, "data": {"status": "closed"}}
        if self.provider == "smscode":
            ok, code, message = _smscode_latest_code(
                self.base_url,
                self.api_key,
                self.activation_id,
                ignored_codes=self.ignored_codes,
            )
            if ok and code:
                return {"ok": True, "data": {"otp": code, "activation_id": self.activation_id}}
            if message == "stale":
                return {"ok": False, "data": {"status": "stale"}}
            if message == "pending":
                return {"ok": False, "data": {"status": "pending"}}
            return {"ok": False, "data": {"status": "error", "message": message or "smscode error"}}
        if self.provider == "smscloud":
            ok, code, message = _smscloud_latest_code(
                self.base_url,
                self.api_key,
                self.activation_id,
                ignored_codes=self.ignored_codes,
            )
            if ok and code:
                return {"ok": True, "data": {"otp": code, "activation_id": self.activation_id}}
            if message == "stale":
                return {"ok": False, "data": {"status": "stale"}}
            if message == "pending":
                return {"ok": False, "data": {"status": "pending"}}
            return {"ok": False, "data": {"status": "error", "message": message or "smscloud error"}}

        ok, text, data = _hero_request(
            self.base_url,
            self.api_key,
            "getStatus",
            {"id": self.activation_id},
            timeout=20,
        )
        if not ok:
            return {"ok": False, "data": {"status": "error", "message": str(text or "hero-sms error")}}

        code = ""
        line = str(text or "").strip()
        if line.upper().startswith("STATUS_OK:"):
            code = line.split(":", 1)[1].strip()
        elif isinstance(data, dict):
            code = str(data.get("code") or data.get("sms") or "").strip()
        if code:
            if code in self.ignored_codes:
                return {"ok": False, "data": {"status": "stale"}}
            return {"ok": True, "data": {"otp": code, "activation_id": self.activation_id}}
        return {"ok": False, "data": {"status": "pending"}}

    def finish(self) -> None:
        if not self.closed:
            if self.provider == "smscode":
                _smscode_finish(self.base_url, self.api_key, self.activation_id)
            elif self.provider == "smscloud":
                _smscloud_finish(self.base_url, self.api_key, self.activation_id)
            else:
                _hero_set_status(self.base_url, self.api_key, self.activation_id, STATUS_FINISH)
            self.closed = True

    def cancel(self) -> None:
        if not self.closed:
            if self.provider == "smscode":
                _smscode_cancel(self.base_url, self.api_key, self.activation_id)
            elif self.provider == "smscloud":
                _smscloud_cancel(self.base_url, self.api_key, self.activation_id)
            else:
                _hero_set_status(self.base_url, self.api_key, self.activation_id, STATUS_CANCEL)
            self.closed = True

    def resend(self) -> None:
        if self.closed:
            return
        if self.provider == "smscode":
            _smscode_resend(self.base_url, self.api_key, self.activation_id)
        elif self.provider == "smscloud":
            _smscloud_resend(self.base_url, self.api_key, self.activation_id)
        else:
            _hero_set_status(self.base_url, self.api_key, self.activation_id, STATUS_RESEND)

    def reusable_status(self) -> tuple[bool, str]:
        if self.closed:
            return False, "closed"
        if self.provider == "smscode":
            ok, data, message = _smscode_get_order(self.base_url, self.api_key, self.activation_id)
            if not ok:
                return False, message or "smscode_status_error"
            order = _smscode_find_order(data, self.activation_id)
            if not order:
                return False, "smscode_order_missing"
            status_text = str(order.get("status") or "").strip().lower()
            if status_text in {"completed", "canceled", "cancelled", "expired", "failed"}:
                return False, status_text or "smscode_terminal"
            return True, status_text or "smscode_active"
        if self.provider == "smscloud":
            ok, data, message = _smscloud_request(self.base_url, self.api_key, "get", "/system/app/sms/myNumber", timeout=20)
            if not ok:
                return False, message or "smscloud_status_error"
            order = _smscloud_find_order(data, self.activation_id)
            if not order:
                return False, "smscloud_order_missing"
            status_text = " ".join(
                str(order.get(key) or "").strip().lower()
                for key in ("status", "state", "statusName", "orderStatus", "statusText")
            )
            terminal_markers = (
                "cancel",
                "canceled",
                "cancelled",
                "finish",
                "finished",
                "complete",
                "completed",
                "expired",
                "closed",
                "refund",
                "done",
                "used",
            )
            if any(marker in status_text for marker in terminal_markers):
                return False, status_text or "smscloud_terminal"
            return True, status_text or "smscloud_active"

        ok, text, _ = _hero_request(
            self.base_url,
            self.api_key,
            "getStatus",
            {"id": self.activation_id},
            timeout=20,
        )
        if not ok:
            return False, str(text or "hero_status_error")
        line = str(text or "").strip()
        upper = line.upper()
        if upper.startswith("STATUS_OK:") or upper in {"STATUS_WAIT_CODE", "STATUS_WAIT_RETRY"}:
            return True, upper
        if any(marker in upper for marker in ("STATUS_CANCEL", "STATUS_FINISH", "NO_ACTIVATION", "ACCESS_CANCEL")):
            return False, upper or "hero_terminal"
        return False, upper or "hero_unknown_status"


@dataclass(slots=True)
class GoPayAutoRegistrationResult:
    phone_number: str
    country_code: str
    gopay_pin: str
    sms_url: str
    activation_id: str
    bridge_token: str
    access_token: str = ""
    refresh_token: str = ""
    account_id: str = ""
    session: Any = None
    gopay_cfg: dict[str, Any] = field(default_factory=dict)

    def as_phone_account(self) -> dict[str, str]:
        return {
            "country_code": self.country_code,
            "phone_number": self.phone_number,
            "sms_url": self.sms_url,
            "gopay_pin": self.gopay_pin,
            "otp_channel": "sms",
        }

    def close(self, *, success: bool = True) -> None:
        close_sms_bridge(self.bridge_token, success=success)


class SmsActivation:
    provider = "hero_sms"

    def __init__(
        self,
        *,
        activation_id: str,
        phone: str,
        country_id: int,
        base_url: str,
        api_key: str,
        log: Callable[[str], None] = logger.info,
    ):
        self.activation_id = activation_id
        self.phone = phone
        self.country_id = country_id
        self.base_url = base_url
        self.api_key = api_key
        self.log = log
        self.used_codes: set[str] = set()

    def wait_code(self, *, timeout_sec: int = 300, label: str = "", max_resends: int = 3) -> str:
        start = time.time()
        last_resend = start
        resend_count = 0
        resend_intervals = [30, 60, 120]
        while time.time() - start < timeout_sec:
            ok, text, data = _hero_request(
                self.base_url,
                self.api_key,
                "getStatus",
                {"id": self.activation_id},
                timeout=20,
            )
            if not ok:
                time.sleep(POLL_INTERVAL_SEC)
                continue

            code = ""
            line = str(text or "").strip()
            if line.upper().startswith("STATUS_OK:"):
                code = line.split(":", 1)[1].strip()
            elif isinstance(data, dict):
                code = str(data.get("code") or data.get("sms") or "").strip()
            if code and code not in self.used_codes:
                self.used_codes.add(code)
                return code

            elapsed = time.time() - last_resend
            if resend_count < max_resends:
                wait_time = resend_intervals[min(resend_count, len(resend_intervals) - 1)]
                if elapsed > wait_time:
                    resend_count += 1
                    self.log(f"[{label}] 超过 {wait_time}s 未收到新码，请求第 {resend_count} 次重发")
                    _hero_set_status(self.base_url, self.api_key, self.activation_id, STATUS_RESEND)
                    last_resend = time.time()
            time.sleep(POLL_INTERVAL_SEC)
        return ""

    def cancel(self) -> None:
        _hero_set_status(self.base_url, self.api_key, self.activation_id, STATUS_CANCEL)

    def finish(self) -> None:
        _hero_set_status(self.base_url, self.api_key, self.activation_id, STATUS_FINISH)

    def resend(self) -> None:
        _hero_set_status(self.base_url, self.api_key, self.activation_id, STATUS_RESEND)


def _delayed_cancel_activation(
    activation: SmsActivation | SmsCloudActivation | SmsCodeActivation,
    *,
    delay_seconds: int = DEFAULT_EXISTING_NUMBER_CANCEL_DELAY_SEC,
    log: Callable[[str], None] = logger.info,
    reason: str = "",
) -> None:
    def worker() -> None:
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        try:
            activation.cancel()
            log(
                "[gopay-signup] 已延迟取消短信号码: "
                f"provider={getattr(activation, 'provider', 'unknown')} "
                f"activation={getattr(activation, 'activation_id', '')} "
                f"reason={reason or 'existing_or_probe_failed'}"
            )
        except Exception as exc:
            log(
                "[gopay-signup] 延迟取消短信号码失败: "
                f"provider={getattr(activation, 'provider', 'unknown')} "
                f"activation={getattr(activation, 'activation_id', '')} "
                f"error={exc}"
            )

    threading.Thread(
        target=worker,
        name=f"gopay-sms-cancel-{getattr(activation, 'activation_id', '')}",
        daemon=True,
    ).start()


def _env_str(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env_str(name)
    if not raw:
        return default
    try:
        return int(float(raw))
    except Exception:
        return default


def _looks_like_transient_gopay_network_error(exc: Exception | str) -> bool:
    normalized = re.sub(r"\s+", " ", str(exc or "")).strip().lower()
    if not normalized:
        return False
    if any(marker in normalized for marker in ("ratelimit:", "rate_limited", "rate limited", "too many requests")):
        return False
    return any(
        marker in normalized
        for marker in (
            "recv failure",
            "connection was reset",
            "connection reset",
            "could not resolve host",
            "operation timed out",
            "timed out",
            "connection timed out",
            "connection refused",
            "connection aborted",
            "network is unreachable",
            "remote disconnected",
            "waf block page",
            "domain-config-1256704386",
            "cos.accelerate.myqcloud",
            "<title>waf block page</title>",
            "blocked by waf",
            "curl: (6)",
            "curl: (7)",
            "curl: (28)",
            "curl: (35)",
            "curl: (56)",
        )
    )


def _hero_request(
    base_url: str,
    api_key: str,
    action: str,
    params: Optional[dict[str, Any]] = None,
    *,
    timeout: int = 25,
) -> tuple[bool, str, Any]:
    if not api_key:
        return False, "NO_KEY", None
    query = {"action": action, "api_key": api_key}
    for key, value in (params or {}).items():
        if value is None:
            continue
        text = str(value).strip()
        if text:
            query[key] = value
    try:
        if curl_requests is not None:
            try:
                resp = curl_requests.get(base_url, params=query, timeout=timeout, impersonate="chrome131")
            except Exception as exc:
                if "could not resolve host" not in str(exc).lower():
                    raise
                logger.info("[gopay-signup] hero-sms curl_cffi DNS failed, falling back to requests")
                resp = requests.get(base_url, params=query, timeout=timeout)
        else:
            resp = requests.get(base_url, params=query, timeout=timeout)
    except Exception as exc:
        return False, f"REQUEST_ERROR:{exc}", None
    text = str(resp.text or "").strip()
    try:
        data = resp.json()
    except Exception:
        data = None
    if not (200 <= resp.status_code < 300):
        return False, text or f"HTTP {resp.status_code}", data
    return True, text, data


def _normalize_hero_price(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = re.sub(r"^[^\d.]+", "", text.replace(",", ""))
    try:
        number = float(text)
    except Exception:
        return None
    if not (number > 0):
        return None
    return round(number, 4)


def _resolve_hero_stock_state(payload: Any) -> tuple[bool, int]:
    if not isinstance(payload, dict):
        return False, 0
    candidates: list[float] = []
    for key in (
        "count",
        "quantity",
        "qty",
        "stock",
        "total",
        "available",
        "availability",
        "free",
        "phones",
        "numbers",
    ):
        if key not in payload:
            continue
        try:
            candidates.append(float(payload.get(key)))
        except Exception:
            continue
    if not candidates:
        return False, 0
    return True, int(max(candidates))


def _collect_hero_price_candidates(payload: Any, candidates: list[float] | None = None) -> list[float]:
    candidates = candidates if candidates is not None else []
    if isinstance(payload, list):
        for item in payload:
            _collect_hero_price_candidates(item, candidates)
        return candidates
    if not isinstance(payload, dict):
        return candidates

    cost = _normalize_hero_price(payload.get("cost") or payload.get("price"))
    if cost is not None:
        has_stock, stock_count = _resolve_hero_stock_state(payload)
        if not has_stock or stock_count > 0:
            candidates.append(cost)

    for key, value in payload.items():
        keyed_price = _normalize_hero_price(key)
        if keyed_price is not None:
            if isinstance(value, dict):
                has_stock, stock_count = _resolve_hero_stock_state(value)
                if has_stock and stock_count > 0:
                    candidates.append(keyed_price)
            else:
                try:
                    if float(value) > 0:
                        candidates.append(keyed_price)
                except Exception:
                    pass
        _collect_hero_price_candidates(value, candidates)
    return candidates


def _collect_hero_price_tiers(payload: Any, tiers: dict[float, int] | None = None) -> dict[float, int]:
    tiers = tiers if tiers is not None else {}
    if isinstance(payload, list):
        for item in payload:
            _collect_hero_price_tiers(item, tiers)
        return tiers
    if not isinstance(payload, dict):
        return tiers

    cost = _normalize_hero_price(payload.get("cost") or payload.get("price") or payload.get("Price"))
    if cost is not None:
        count = payload.get("physicalCount", payload.get("count", payload.get("qty", payload.get("Qty", 0))))
        try:
            stock_count = max(0, int(float(count)))
        except Exception:
            stock_count = 0
        tiers[cost] = max(tiers.get(cost, 0), stock_count)

    def push_tier_map(tier_map: Any) -> None:
        if not isinstance(tier_map, dict):
            return
        for price_key, count_raw in tier_map.items():
            price = _normalize_hero_price(price_key)
            if price is None:
                continue
            try:
                stock_count = max(0, int(float(count_raw)))
            except Exception:
                stock_count = 0
            tiers[price] = max(tiers.get(price, 0), stock_count)

    push_tier_map(payload.get("freePriceMap"))
    push_tier_map(payload.get("priceMap"))

    for key, value in payload.items():
        keyed_price = _normalize_hero_price(key)
        if keyed_price is not None:
            if isinstance(value, dict):
                stock_candidates = []
                for stock_key in ("physicalCount", "count", "stock", "available", "quantity", "qty", "left", "free"):
                    try:
                        stock_candidates.append(float(value.get(stock_key)))
                    except Exception:
                        pass
                if stock_candidates:
                    tiers[keyed_price] = max(tiers.get(keyed_price, 0), max(0, int(max(stock_candidates))))
            else:
                try:
                    tiers[keyed_price] = max(tiers.get(keyed_price, 0), max(0, int(float(value))))
                except Exception:
                    pass
        _collect_hero_price_tiers(value, tiers)
    return tiers


def _collect_hero_top_country_price_tiers(payload: Any, country_id: int) -> dict[float, int]:
    if not isinstance(payload, dict):
        return {}
    tiers: dict[float, int] = {}
    normalized_country = int(country_id)
    for entry in payload.values():
        if not isinstance(entry, dict):
            continue
        try:
            entry_country = int(float(entry.get("country") or entry.get("countryId") or entry.get("country_id") or entry.get("id") or 0))
        except Exception:
            entry_country = 0
        if entry_country != normalized_country:
            continue
        _collect_hero_price_tiers(entry, tiers)
    return tiers


def _sorted_unique_hero_prices(values: list[float]) -> list[float]:
    return sorted({round(float(value), 4) for value in values if _normalize_hero_price(value) is not None})[:20]


def _filter_hero_prices(
    prices: list[float],
    *,
    min_price: str = "",
    max_price: str = "",
    preferred_price: str = "",
) -> tuple[list[float], str]:
    min_limit = _normalize_hero_price(min_price)
    max_limit = _normalize_hero_price(max_price)
    preferred = _normalize_hero_price(preferred_price)
    if min_limit is not None and max_limit is not None and min_limit > max_limit:
        return [], f"HeroSMS 价格区间无效：最低购买价 {min_limit} 高于价格上限 {max_limit}"

    filtered = []
    for price in _sorted_unique_hero_prices(prices):
        if min_limit is not None and price < min_limit:
            continue
        if max_limit is not None and price > max_limit:
            continue
        # HeroSMS getNumber maxPrice is a ceiling. Once a preferred ceiling is
        # used, lower buckets are already covered by that request.
        if preferred is not None and price < preferred:
            continue
        filtered.append(price)
    if preferred is not None:
        if min_limit is not None and preferred < min_limit:
            return filtered, ""
        if max_limit is not None and preferred > max_limit:
            return filtered, ""
        if preferred not in filtered:
            filtered.append(preferred)
        filtered = [preferred, *[price for price in filtered if price != preferred]]
    return filtered, ""


def _filter_hero_tiers(
    tiers: dict[float, int],
    *,
    min_price: str = "",
    max_price: str = "",
    preferred_price: str = "",
) -> tuple[list[dict[str, Any]], str]:
    min_limit = _normalize_hero_price(min_price)
    max_limit = _normalize_hero_price(max_price)
    preferred = _normalize_hero_price(preferred_price)
    if min_limit is not None and max_limit is not None and min_limit > max_limit:
        return [], f"HeroSMS 价格区间无效：最低购买价 {min_limit} 高于价格上限 {max_limit}"

    entries = []
    for price in sorted(tiers):
        if min_limit is not None and price < min_limit:
            continue
        if max_limit is not None and price > max_limit:
            continue
        # maxPrice is a ceiling, so lower tiers are included when requesting the
        # preferred tier and should not be shown/retried separately.
        if preferred is not None and price < preferred:
            continue
        entries.append({"price": round(float(price), 4), "count": max(0, int(tiers.get(price, 0)))})
    if preferred is not None:
        if min_limit is None or preferred >= min_limit:
            if max_limit is None or preferred <= max_limit:
                if not any(entry["price"] == preferred for entry in entries):
                    entries.append({"price": preferred, "count": 0})
                entries = [
                    *[entry for entry in entries if entry["price"] == preferred],
                    *[entry for entry in entries if entry["price"] != preferred],
                ]
    return entries, ""


def query_hero_sms_price_tiers(
    *,
    service_code: str,
    country_id: int,
    base_url: str,
    api_key: str,
    min_price: str = "",
    max_price: str = "",
    preferred_price: str = "",
) -> dict[str, Any]:
    payloads: list[Any] = []
    top_country_payloads: list[Any] = []
    errors: list[str] = []
    for action, extra_params in (
        ("getPricesExtended", {"freePrice": "true"}),
        ("getPrices", {}),
        ("getPricesForVerification", {}),
    ):
        try:
            ok, text, data = _hero_request(
                base_url,
                api_key,
                action,
                {"service": service_code, "country": country_id, **extra_params},
                timeout=30,
            )
        except Exception as exc:
            ok, text, data = False, str(exc), None
        payload: Any = data if data is not None else text
        if ok:
            payloads.append(payload)
        else:
            errors.append(f"{action}: {text or 'failed'}")
    try:
        ok, text, data = _hero_request(
            base_url,
            api_key,
            "getTopCountriesByService",
            {"service": service_code, "freePrice": "true"},
            timeout=30,
        )
    except Exception as exc:
        ok, text, data = False, str(exc), None
    top_payload: Any = data if data is not None else text
    if ok:
        top_country_payloads.append(top_payload)
    else:
        errors.append(f"getTopCountriesByService: {text or 'failed'}")

    try:
        ok, text, data = _hero_request(
            base_url,
            api_key,
            "getPricesVerification",
            {"service": service_code, "country": country_id},
            timeout=30,
        )
    except Exception as exc:
        ok, text, data = False, str(exc), None
    verification_payload: Any = data if data is not None else text
    if ok:
        payloads.append(verification_payload)
    else:
        errors.append(f"getPricesVerification: {text or 'failed'}")
    if not payloads and not top_country_payloads:
        return {
            "ok": False,
            "error": "；".join(errors) or "HeroSMS 价格档位查询失败",
            "raw": [],
            "prices": [],
            "filtered_prices": [],
        }
    tier_map: dict[float, int] = {}
    for payload in payloads:
        for price, count in _collect_hero_price_tiers(payload).items():
            tier_map[price] = max(tier_map.get(price, 0), count)
    for payload in top_country_payloads:
        for price, count in _collect_hero_top_country_price_tiers(payload, country_id).items():
            tier_map[price] = max(tier_map.get(price, 0), count)
    prices = _sorted_unique_hero_prices(
        list(tier_map.keys()) or [price for payload in payloads for price in _collect_hero_price_candidates(payload)]
    )
    filtered, error = _filter_hero_prices(
        prices,
        min_price=min_price,
        max_price=max_price,
        preferred_price=preferred_price,
    )
    if error:
        return {"ok": False, "error": error, "raw": payloads, "prices": prices, "filtered_prices": []}
    filtered_tiers, error = _filter_hero_tiers(
        tier_map,
        min_price=min_price,
        max_price=max_price,
        preferred_price=preferred_price,
    )
    if error:
        return {"ok": False, "error": error, "raw": payloads, "prices": prices, "filtered_prices": []}
    tiers = [{"price": price, "count": max(0, int(tier_map.get(price, 0)))} for price in prices]
    return {
        "ok": True,
        "error": "",
        "raw": [*payloads, *top_country_payloads],
        "prices": prices,
        "filtered_prices": filtered,
        "tiers": tiers,
        "filtered_tiers": filtered_tiers,
        "count": len(filtered),
    }


def _hero_get_number(
    *,
    service_code: str,
    country_id: int | str | None,
    base_url: str,
    api_key: str,
    max_price: str = "",
    min_price: str = "",
    preferred_price: str = "",
) -> tuple[str, str, str]:
    country_text = str(country_id or "").strip().lower()
    limited_country = country_text not in {"", "all", "any", "*"}
    price_plan = None
    if limited_country and (str(min_price or "").strip() or str(max_price or "").strip() or str(preferred_price or "").strip()):
        price_plan = query_hero_sms_price_tiers(
            service_code=service_code,
            country_id=int(float(country_text)),
            base_url=base_url,
            api_key=api_key,
            min_price=min_price,
            max_price=max_price,
            preferred_price=preferred_price,
        )
        if not price_plan.get("ok"):
            return "", "", str(price_plan.get("error") or "HeroSMS 价格档位查询失败")
        if not price_plan.get("filtered_prices"):
            return "", "", "HeroSMS 当前价格区间内没有可用号码"

    params = {"service": service_code}
    if limited_country:
        params["country"] = int(float(country_text))
    if str(max_price or "").strip():
        params["maxPrice"] = str(max_price or "").strip()
    candidate_params = [params]
    use_fixed_price_candidates = bool(str(min_price or "").strip() or str(preferred_price or "").strip())
    if use_fixed_price_candidates and price_plan and price_plan.get("filtered_prices"):
        candidate_params = []
        for price in price_plan["filtered_prices"]:
            candidate = {
                "service": service_code,
                "maxPrice": str(price),
                "fixedPrice": "true",
            }
            if limited_country:
                candidate["country"] = int(float(country_text))
            candidate_params.append(candidate)
    last_error = ""
    for candidate in candidate_params:
        ok, text, data = _hero_request(
            base_url,
            api_key,
            "getNumber",
            candidate,
            timeout=30,
        )
        if not ok:
            last_error = str(text or "getNumber failed")
            if re.search(r"\b(?:NO_NUMBERS|WRONG_MAX_PRICE)\b", last_error, re.I):
                continue
            return "", "", last_error
        line = str(text or "").strip()
        if line.upper().startswith("ACCESS_NUMBER:"):
            parts = line.split(":", 2)
            if len(parts) >= 3:
                return parts[1].strip(), parts[2].strip(), ""
        if isinstance(data, dict):
            activation_id = str(data.get("activationId") or data.get("id") or "")
            phone = str(data.get("phoneNumber") or data.get("phone") or "")
            if activation_id and phone:
                return activation_id, phone, ""
        last_error = line or "无法解析号码"
        if re.search(r"\b(?:NO_NUMBERS|WRONG_MAX_PRICE)\b", last_error, re.I):
            continue
        return "", "", last_error
    return "", "", last_error or "HeroSMS 无可用号码"


def _hero_set_status(base_url: str, api_key: str, activation_id: str, status: int) -> str:
    if not activation_id:
        return ""
    _, text, _ = _hero_request(
        base_url,
        api_key,
        "setStatus",
        {"id": activation_id, "status": status},
        timeout=20,
    )
    return str(text or "")


def _normalize_sms_provider(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {"smscloud", "sms_cloud", "xi_sms", "xisms"}:
        return "smscloud"
    if normalized in {"smscode", "sms_code", "smscode_gg"}:
        return "smscode"
    return "hero_sms"


def _smscode_base_url(base_url: str) -> str:
    resolved = str(base_url or DEFAULT_SMSCODE_BASE_URL).strip().rstrip("/")
    return resolved or DEFAULT_SMSCODE_BASE_URL


def _smscode_request(
    base_url: str,
    api_token: str,
    method: str,
    path: str,
    *,
    params: Optional[dict[str, Any]] = None,
    data: Optional[dict[str, Any]] = None,
    headers: Optional[dict[str, str]] = None,
    timeout: int = 25,
) -> tuple[bool, Any, str]:
    token = str(api_token or "").strip()
    if not token:
        return False, None, "NO_TOKEN"
    url = f"{_smscode_base_url(base_url)}/{str(path or '').lstrip('/')}"
    request_headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    request_headers.update(headers or {})
    try:
        if curl_requests is not None:
            resp = curl_requests.request(
                method.upper(),
                url,
                params=params,
                json=data,
                headers=request_headers,
                timeout=timeout,
                impersonate="chrome131",
            )
        else:
            resp = requests.request(method.upper(), url, params=params, json=data, headers=request_headers, timeout=timeout)
    except Exception as exc:
        return False, None, f"REQUEST_ERROR:{exc}"
    text = str(resp.text or "").strip()
    try:
        payload = resp.json()
    except Exception:
        payload = text
    if not (200 <= resp.status_code < 300):
        return False, payload, _smscode_error_message(payload) or text or f"HTTP {resp.status_code}"
    if isinstance(payload, dict) and payload.get("success") is False:
        return False, payload, _smscode_error_message(payload) or text or "SMSCode request failed"
    if isinstance(payload, dict) and "data" in payload:
        return True, payload.get("data"), ""
    return True, payload, ""


def _smscode_error_message(payload: Any) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            code = str(error.get("code") or "").strip()
            message = str(error.get("message") or "").strip()
            return f"{code}: {message}".strip(": ")
        message = str(payload.get("message") or payload.get("msg") or "").strip()
        if message:
            return message
    return ""


def _smscode_collection(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("items", "rows", "records", "orders", "products", "list", "data"):
        value = payload.get(key)
        if value is payload:
            continue
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        nested = _smscode_collection(value)
        if nested:
            return nested
    return [payload]


def _smscode_find_order(payload: Any, activation_id: str = "") -> dict[str, Any]:
    activation_id = str(activation_id or "").strip()
    for item in _smscode_collection(payload):
        item_id = str(item.get("id") or item.get("order_id") or item.get("orderId") or "").strip()
        if not activation_id or item_id == activation_id:
            return item
    return {}


def _smscode_extract_code(order: dict[str, Any], ignored_codes: set[str] | None = None) -> str:
    ignored = {str(item or "").strip() for item in (ignored_codes or set()) if str(item or "").strip()}

    def valid_code(value: Any) -> str:
        code = str(value or "").strip()
        return code if re.fullmatch(r"\d{4,8}", code) and code not in ignored else ""

    for key in ("code", "otp", "otp_code", "sms_code", "verification_code"):
        code = valid_code(order.get(key))
        if code:
            return code
    for key in ("message", "sms", "text", "otp_message", "sms_text", "content"):
        text = str(order.get(key) or "")
        for match in re.finditer(r"(?<!\d)(\d{4,8})(?!\d)", text):
            code = valid_code(match.group(1))
            if code:
                return code
    messages = order.get("messages") or order.get("sms_messages") or order.get("smsList") or []
    if isinstance(messages, dict):
        messages = [messages]
    if isinstance(messages, list):
        for message in reversed([item for item in messages if isinstance(item, dict)]):
            code = _smscode_extract_code(message, ignored_codes=ignored)
            if code:
                return code
    return ""


def _smscode_product_id(product: dict[str, Any]) -> str:
    return str(product.get("id") or product.get("product_id") or product.get("productId") or "").strip()


def _smscode_product_price(product: dict[str, Any]) -> float | None:
    for key in ("price", "cost", "amount"):
        price = _normalize_hero_price(product.get(key))
        if price is not None:
            return price
    return None


def _smscode_product_stock(product: dict[str, Any]) -> int:
    for key in ("available", "stock", "quantity", "qty", "count", "numbers_count"):
        if key not in product:
            continue
        try:
            return max(0, int(float(product.get(key))))
        except Exception:
            pass
    return 1


def _smscode_resolve_platform_id(
    *,
    base_url: str,
    api_token: str,
    country_id: str,
    platform_id: str = "",
    platform_query: str = "gopay",
) -> tuple[str, str]:
    platform_id = str(platform_id or "").strip()
    if platform_id:
        return platform_id, ""
    query = str(platform_query or "gopay").strip().lower()
    ok, data, message = _smscode_request(
        base_url,
        api_token,
        "get",
        "/catalog/services",
        params={"country_id": country_id},
        timeout=30,
    )
    if not ok:
        return "", message or "services query failed"
    services = _smscode_collection(data)
    for service in services:
        haystack = " ".join(
            str(service.get(key) or "").strip().lower()
            for key in ("name", "code", "slug", "platform", "service")
        )
        if query and query in haystack:
            resolved = str(service.get("id") or service.get("platform_id") or service.get("platformId") or "").strip()
            if resolved:
                return resolved, ""
    return "", f"SMSCode 未找到平台: {platform_query or 'gopay'}"


def _filter_smscode_products(
    products: list[dict[str, Any]],
    *,
    min_price: str = "",
    max_price: str = "",
) -> tuple[list[dict[str, Any]], str]:
    min_value = _normalize_hero_price(min_price)
    max_value = _normalize_hero_price(max_price)
    if min_value is not None and max_value is not None and min_value > max_value:
        return [], "SMSCode 价格区间无效：最低价不能大于最高价"
    filtered: list[dict[str, Any]] = []
    for product in products:
        product_id = _smscode_product_id(product)
        price = _smscode_product_price(product)
        if not product_id or price is None:
            continue
        if _smscode_product_stock(product) <= 0:
            continue
        if min_value is not None and price < min_value:
            continue
        if max_value is not None and price > max_value:
            continue
        filtered.append(product)
    filtered.sort(key=lambda item: (_smscode_product_price(item) or 999999, _smscode_product_id(item)))
    return filtered, ""


def query_smscode_products(
    *,
    base_url: str,
    api_token: str,
    country_id: str = "6",
    platform_id: str = "",
    platform_query: str = "gopay",
    min_price: str = "",
    max_price: str = "",
) -> dict[str, Any]:
    resolved_platform_id, error = _smscode_resolve_platform_id(
        base_url=base_url,
        api_token=api_token,
        country_id=country_id,
        platform_id=platform_id,
        platform_query=platform_query,
    )
    if error:
        return {"ok": False, "error": error, "products": [], "filtered_products": []}
    ok, data, message = _smscode_request(
        base_url,
        api_token,
        "get",
        "/catalog/products",
        params={"country_id": country_id, "platform_id": resolved_platform_id},
        timeout=30,
    )
    if not ok:
        return {"ok": False, "error": message or "SMSCode 产品查询失败", "products": [], "filtered_products": []}
    products = _smscode_collection(data)
    normalized_products = []
    for product in products:
        if not isinstance(product, dict):
            continue
        product_id = _smscode_product_id(product)
        price = _smscode_product_price(product)
        stock = _smscode_product_stock(product)
        if product_id and price is not None:
            normalized_products.append({**product, "id": product_id, "price": price, "count": stock})
    filtered, filter_error = _filter_smscode_products(normalized_products, min_price=min_price, max_price=max_price)
    if filter_error:
        return {"ok": False, "error": filter_error, "products": normalized_products, "filtered_products": []}
    return {
        "ok": True,
        "error": "",
        "platform_id": resolved_platform_id,
        "products": normalized_products,
        "filtered_products": filtered,
        "count": len(filtered),
    }


def _smscode_get_number(
    *,
    base_url: str,
    api_token: str,
    country_id: str = "6",
    platform_id: str = "",
    platform_query: str = "gopay",
    product_id: str = "",
    min_price: str = "",
    max_price: str = "",
) -> tuple[str, str, str]:
    selected_product_id = str(product_id or "").strip()
    if not selected_product_id:
        plan = query_smscode_products(
            base_url=base_url,
            api_token=api_token,
            country_id=country_id,
            platform_id=platform_id,
            platform_query=platform_query,
            min_price=min_price,
            max_price=max_price,
        )
        if not plan.get("ok"):
            return "", "", str(plan.get("error") or "SMSCode 产品查询失败")
        products = plan.get("filtered_products") or []
        if not products:
            return "", "", "SMSCode 当前价格区间内没有可用号码"
        selected_product_id = _smscode_product_id(products[0])
    ok, data, message = _smscode_request(
        base_url,
        api_token,
        "post",
        "/orders/create",
        data={"product_id": selected_product_id, "quantity": 1},
        headers={"Idempotency-Key": uuid.uuid4().hex},
        timeout=30,
    )
    if not ok:
        return "", "", message or "orders/create failed"
    order = _smscode_find_order(data)
    activation_id = str(order.get("id") or order.get("order_id") or order.get("orderId") or "").strip()
    phone = str(order.get("phone_number") or order.get("phone") or order.get("number") or "").strip()
    if activation_id and phone:
        return activation_id, phone, ""
    if activation_id:
        deadline = time.time() + 25
        while time.time() < deadline:
            ok, latest_data, latest_message = _smscode_get_order(base_url, api_token, activation_id)
            if not ok:
                return "", "", latest_message or "order query failed"
            latest_order = _smscode_find_order(latest_data, activation_id)
            phone = str(latest_order.get("phone_number") or latest_order.get("phone") or latest_order.get("number") or "").strip()
            if phone:
                return activation_id, phone, ""
            time.sleep(1)
    return "", "", f"无法解析 SMSCode 号码: {data!r}"


def _smscode_get_order(base_url: str, api_token: str, activation_id: str) -> tuple[bool, Any, str]:
    if not activation_id:
        return False, None, "NO_ORDER_ID"
    return _smscode_request(base_url, api_token, "get", f"/orders/{activation_id}", timeout=20)


def _smscode_latest_code(
    base_url: str,
    api_token: str,
    activation_id: str,
    *,
    ignored_codes: set[str] | None = None,
) -> tuple[bool, str, str]:
    ok, data, message = _smscode_get_order(base_url, api_token, activation_id)
    if not ok:
        return False, "", message or "order query failed"
    order = _smscode_find_order(data, activation_id)
    if not order:
        return False, "", "pending"
    code = _smscode_extract_code(order, ignored_codes=ignored_codes)
    if not code:
        return False, "", "pending"
    if code in (ignored_codes or set()):
        return False, "", "stale"
    return True, code, ""


def _smscode_order_action(base_url: str, api_token: str, activation_id: str, action: str) -> None:
    if not activation_id:
        return
    ok, _data, message = _smscode_request(
        base_url,
        api_token,
        "post",
        f"/orders/{action}",
        data={"id": activation_id},
        timeout=20,
    )
    if not ok and action != "cancel":
        raise HeroSmsError(message or f"SMSCode {action} failed")


def _smscode_resend(base_url: str, api_token: str, activation_id: str) -> None:
    _smscode_order_action(base_url, api_token, activation_id, "resend")


def _smscode_finish(base_url: str, api_token: str, activation_id: str) -> None:
    _smscode_order_action(base_url, api_token, activation_id, "finish")


def _smscode_cancel(base_url: str, api_token: str, activation_id: str) -> None:
    _smscode_order_action(base_url, api_token, activation_id, "cancel")


def _smscloud_base_url(base_url: str) -> str:
    resolved = str(base_url or "https://smscloud.sbs/api").strip().rstrip("/")
    if not resolved:
        resolved = "https://smscloud.sbs/api"
    parts = urlsplit(resolved)
    if parts.netloc.lower().endswith("smscloud.sbs") and parts.path in {"", "/"}:
        return f"{resolved}/api"
    return resolved


def _smscloud_request(
    base_url: str,
    token: str,
    method: str,
    path: str,
    *,
    params: Optional[dict[str, Any]] = None,
    data: Optional[dict[str, Any]] = None,
    timeout: int = 25,
) -> tuple[bool, Any, str]:
    token = str(token or "").strip()
    if not token:
        return False, None, "NO_TOKEN"
    url = f"{_smscloud_base_url(base_url)}/{str(path or '').lstrip('/')}"
    headers = {
        "Content-Type": "application/json;charset=utf-8",
        "X-Requested-With": "XMLHttpRequest",
        "XI-Authorization": token,
    }
    try:
        if curl_requests is not None:
            resp = curl_requests.request(
                method.upper(),
                url,
                params=params,
                json=data,
                headers=headers,
                timeout=timeout,
                impersonate="chrome131",
            )
        else:
            resp = requests.request(method.upper(), url, params=params, json=data, headers=headers, timeout=timeout)
    except Exception as exc:
        return False, None, f"REQUEST_ERROR:{exc}"
    text = str(resp.text or "").strip()
    try:
        payload = resp.json()
    except Exception:
        payload = text
    if not (200 <= resp.status_code < 300):
        return False, payload, text or f"HTTP {resp.status_code}"
    if isinstance(payload, dict):
        code = payload.get("code", payload.get("status", 200))
        try:
            numeric_code = int(code)
        except Exception:
            numeric_code = 200 if code in {None, ""} else -1
        if numeric_code in {0, 200}:
            return True, payload.get("data", payload), ""
        return False, payload, str(payload.get("message") or payload.get("msg") or text or f"SMSCloud code {code}")
    return True, payload, ""


def _smscloud_collection(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("rows", "records", "list", "items", "orders"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    data = payload.get("data")
    if data is not payload:
        nested = _smscloud_collection(data)
        if nested:
            return nested
    return [payload]


def _smscloud_find_order(payload: Any, activation_id: str = "") -> dict[str, Any]:
    activation_id = str(activation_id or "").strip()
    for item in _smscloud_collection(payload):
        item_id = str(item.get("id") or item.get("orderId") or item.get("activationId") or "").strip()
        if not activation_id or item_id == activation_id:
            return item
    return {}


def _smscloud_extract_code(order: dict[str, Any], ignored_codes: set[str] | None = None) -> str:
    ignored = {str(item or "").strip() for item in (ignored_codes or set()) if str(item or "").strip()}

    def valid_code(value: Any) -> str:
        code = str(value or "").strip()
        return code if re.fullmatch(r"\d{4,8}", code) and code not in ignored else ""

    def message_sort_key(message: dict[str, Any]) -> tuple[float, float]:
        date_value = message.get("dateTime") or message.get("createdAt") or message.get("time") or 0
        id_value = message.get("id") or 0
        try:
            date_number = float(date_value)
        except Exception:
            date_number = 0.0
        try:
            id_number = float(id_value)
        except Exception:
            id_number = 0.0
        return date_number, id_number

    messages = order.get("messages") or order.get("smsList") or order.get("sms") or []
    if isinstance(messages, dict):
        messages = [messages]
    if not isinstance(messages, list):
        messages = []
    sorted_messages = sorted(
        [item for item in messages if isinstance(item, dict)],
        key=message_sort_key,
        reverse=True,
    )
    for message in sorted_messages:
        for key in ("code", "smsCode", "verificationCode", "otp"):
            code = valid_code(message.get(key))
            if code:
                return code
        text = " ".join(str(message.get(key) or "") for key in ("text", "content", "message", "smsContent"))
        for match in re.finditer(r"(?<!\d)(\d{4,8})(?!\d)", text):
            code = valid_code(match.group(1))
            if code:
                return code
    for message in sorted_messages:
        text = " ".join(str(message.get(key) or "") for key in ("text", "content", "message", "smsContent"))
        match = re.search(r"(?<!\d)(\d{4,8})(?!\d)", text)
        if match and match.group(1) not in ignored:
            return match.group(1)
    for key in ("code", "smsCode", "verificationCode", "otp"):
        code = valid_code(order.get(key))
        if code:
            return code
    text = " ".join(str(order.get(key) or "") for key in ("text", "content", "message", "smsContent"))
    for match in re.finditer(r"(?<!\d)(\d{4,8})(?!\d)", text):
        code = valid_code(match.group(1))
        if code:
            return code
    return ""


def _smscloud_get_number(
    *,
    service_code: str,
    country_id: str,
    base_url: str,
    token: str,
    max_price: str = "",
) -> tuple[str, str, str]:
    payload: dict[str, Any] = {"service": service_code, "country": country_id}
    if str(max_price or "").strip():
        payload["maxPrice"] = str(max_price or "").strip()
    ok, data, message = _smscloud_request(
        base_url,
        token,
        "post",
        "/system/app/sms/getNumber",
        data=payload,
        timeout=30,
    )
    if not ok:
        return "", "", message or "getNumber failed"
    order = _smscloud_find_order(data)
    activation_id = str(order.get("id") or order.get("orderId") or order.get("activationId") or "").strip()
    phone = str(order.get("phoneNumber") or order.get("phone") or order.get("number") or "").strip()
    if activation_id and phone:
        return activation_id, phone, ""
    if activation_id:
        deadline = time.time() + 25
        while time.time() < deadline:
            ok, latest_data, latest_message = _smscloud_request(base_url, token, "get", "/system/app/sms/myNumber", timeout=20)
            if not ok:
                return "", "", latest_message or "myNumber failed"
            latest_order = _smscloud_find_order(latest_data, activation_id)
            phone = str(latest_order.get("phoneNumber") or latest_order.get("phone") or latest_order.get("number") or "").strip()
            if phone:
                return activation_id, phone, ""
            time.sleep(1)
    return "", "", f"无法解析 smscloud 号码: {data!r}"


def _smscloud_latest_code(
    base_url: str,
    token: str,
    activation_id: str,
    *,
    ignored_codes: set[str] | None = None,
) -> tuple[bool, str, str]:
    ok, data, message = _smscloud_request(base_url, token, "get", "/system/app/sms/myNumber", timeout=20)
    if not ok:
        return False, "", message or "myNumber failed"
    order = _smscloud_find_order(data, activation_id)
    if not order:
        return False, "", "pending"
    code = _smscloud_extract_code(order, ignored_codes=ignored_codes)
    if not code:
        return False, "", "pending"
    if code in (ignored_codes or set()):
        return False, "", "stale"
    return True, code, ""


def _smscloud_order_action(base_url: str, token: str, activation_id: str, action: str) -> None:
    if not activation_id:
        return
    _smscloud_request(base_url, token, "post", f"/system/app/sms/number/{activation_id}/{action}", timeout=20)


def _smscloud_resend(base_url: str, token: str, activation_id: str) -> None:
    _smscloud_order_action(base_url, token, activation_id, "resend")


def _smscloud_finish(base_url: str, token: str, activation_id: str) -> None:
    _smscloud_order_action(base_url, token, activation_id, "finish")


def _smscloud_cancel(base_url: str, token: str, activation_id: str) -> None:
    _smscloud_order_action(base_url, token, activation_id, "cancel")


class SmsCloudActivation:
    provider = "smscloud"

    def __init__(
        self,
        *,
        activation_id: str,
        phone: str,
        country_id: str,
        base_url: str,
        token: str,
        log: Callable[[str], None] = logger.info,
    ):
        self.activation_id = activation_id
        self.phone = phone
        self.country_id = country_id
        self.base_url = _smscloud_base_url(base_url)
        self.api_key = token
        self.log = log
        self.used_codes: set[str] = set()

    def wait_code(self, *, timeout_sec: int = 300, label: str = "", max_resends: int = 3) -> str:
        start = time.time()
        last_resend = start
        resend_count = 0
        resend_intervals = [30, 60, 120]
        while time.time() - start < timeout_sec:
            ok, code, _ = _smscloud_latest_code(
                self.base_url,
                self.api_key,
                self.activation_id,
                ignored_codes=self.used_codes,
            )
            if ok and code:
                self.used_codes.add(code)
                return code

            elapsed = time.time() - last_resend
            if resend_count < max_resends:
                wait_time = resend_intervals[min(resend_count, len(resend_intervals) - 1)]
                if elapsed > wait_time:
                    resend_count += 1
                    self.log(f"[{label}] 超过 {wait_time}s 未收到新码，请求 smscloud 第 {resend_count} 次重发")
                    self.resend()
                    last_resend = time.time()
            time.sleep(POLL_INTERVAL_SEC)
        return ""

    def cancel(self) -> None:
        _smscloud_cancel(self.base_url, self.api_key, self.activation_id)

    def finish(self) -> None:
        _smscloud_finish(self.base_url, self.api_key, self.activation_id)

    def resend(self) -> None:
        _smscloud_resend(self.base_url, self.api_key, self.activation_id)


class SmsCodeActivation:
    provider = "smscode"

    def __init__(
        self,
        *,
        activation_id: str,
        phone: str,
        country_id: str,
        base_url: str,
        api_token: str,
        log: Callable[[str], None] = logger.info,
    ):
        self.activation_id = activation_id
        self.phone = phone
        self.country_id = country_id
        self.base_url = _smscode_base_url(base_url)
        self.api_key = api_token
        self.log = log
        self.used_codes: set[str] = set()

    def wait_code(self, *, timeout_sec: int = 300, label: str = "", max_resends: int = 3) -> str:
        start = time.time()
        last_resend = start
        resend_count = 0
        resend_intervals = [30, 60, 120]
        while time.time() - start < timeout_sec:
            ok, code, _ = _smscode_latest_code(
                self.base_url,
                self.api_key,
                self.activation_id,
                ignored_codes=self.used_codes,
            )
            if ok and code:
                self.used_codes.add(code)
                return code

            elapsed = time.time() - last_resend
            if resend_count < max_resends:
                wait_time = resend_intervals[min(resend_count, len(resend_intervals) - 1)]
                if elapsed > wait_time:
                    resend_count += 1
                    self.log(f"[{label}] 超过 {wait_time}s 未收到新码，请求 SMSCode 第 {resend_count} 次重发")
                    self.resend()
                    last_resend = time.time()
            time.sleep(POLL_INTERVAL_SEC)
        return ""

    def cancel(self) -> None:
        _smscode_cancel(self.base_url, self.api_key, self.activation_id)

    def finish(self) -> None:
        _smscode_finish(self.base_url, self.api_key, self.activation_id)

    def resend(self) -> None:
        _smscode_resend(self.base_url, self.api_key, self.activation_id)


def create_sms_bridge(activation: SmsActivation | SmsCloudActivation | SmsCodeActivation) -> GoPaySmsBridge:
    bridge = GoPaySmsBridge(
        token=uuid.uuid4().hex,
        activation_id=activation.activation_id,
        base_url=activation.base_url,
        api_key=activation.api_key,
        provider=getattr(activation, "provider", "hero_sms"),
        ignored_codes=set(activation.used_codes),
    )
    with _BRIDGE_LOCK:
        _SMS_BRIDGES[bridge.token] = bridge
    return bridge


def get_sms_bridge_payload(token: str, *, resend: bool = False) -> dict[str, Any]:
    with _BRIDGE_LOCK:
        bridge = _SMS_BRIDGES.get(str(token or "").strip())
    if bridge is None:
        raise KeyError("bridge not found")
    if resend:
        bridge.resend()
    return bridge.latest_response()


def is_sms_bridge_reusable(token: str) -> tuple[bool, str]:
    with _BRIDGE_LOCK:
        bridge = _SMS_BRIDGES.get(str(token or "").strip())
    if bridge is None:
        return False, "bridge_missing"
    return bridge.reusable_status()


def close_sms_bridge(token: str, *, success: bool = True) -> None:
    bridge = None
    with _BRIDGE_LOCK:
        bridge = _SMS_BRIDGES.pop(str(token or "").strip(), None)
    if bridge is None:
        return
    if success:
        bridge.finish()
    else:
        bridge.cancel()


def _random_name() -> str:
    return "".join(random.choices(string.ascii_uppercase, k=3))


def _random_mac() -> str:
    return ":".join(f"{random.randint(0, 255):02x}" for _ in range(6))


def _random_wifi_ssid() -> str:
    prefix = random.choice(WIFI_PREFIXES)
    suffix = "".join(random.choices(string.hexdigits[:16], k=12))
    return f"{prefix}_{suffix}"


def _random_x_m1() -> str:
    import base64

    ts = int(time.time() * 1000)
    rand_id = random.randint(1000000000000000000, 9999999999999999999)
    fingerprint_hash = hashlib.sha256(os.urandom(32)).digest()
    fp_b64 = base64.b64encode(fingerprint_hash).decode().rstrip("=")
    chipset = random.choice(CHIPSET_PROFILES)
    return (
        f"3:{ts}-{rand_id},4:{random.randint(100000, 999999)},5:{chipset},"
        f"6:02:00:00:00:00:00,7:<unknown ssid>,8:{random.choice(SCREEN_RESOLUTIONS)},"
        f"10:1,11:{fp_b64},"
        f"15:{os.urandom(16).hex()},16:{uuid.uuid4()}"
    )


def _random_unique_id() -> str:
    return os.urandom(8).hex()


def _random_device_token() -> str:
    token_body = "".join(random.choices(string.ascii_letters + string.digits + "-_", k=140))
    return f"f-{uuid.uuid4().hex[:22]}:APA91b{token_body}"


def sign_x_e1(headers: dict[str, str], method: str, host: str, path: str, body_text: str = "") -> str:
    ts = int(time.time() * 1000)
    nonce = os.urandom(80).hex()
    lowered = {key.lower(): value for key, value in headers.items()}
    auth = lowered.get("authorization", "")
    bearer = auth[len("Bearer ") :] if auth.startswith("Bearer ") else auth
    body_md5 = hashlib.md5(body_text.encode()).hexdigest()
    canonical = (
        f"{lowered.get('x-apptype', '')};"
        f"{lowered.get('x-phonemodel', '')}:{bearer};"
        f"{lowered.get('x-uniqueid', '')}:;"
        f"{body_md5}:{host}{path};"
        f"{method.upper()}:{ts};"
        f"{lowered.get('x-deviceos', '')}:{lowered.get('x-appversion', '')};"
        f"{lowered.get('x-m1', '')}:{lowered.get('x-appid', '')};"
        f"{nonce}:{lowered.get('x-phonemake', '')};"
        f"{lowered.get('x-platform', '')}"
    )
    digest = hmac.new(HMAC_KEY.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return f"{digest}:{nonce}:D:{ts}"


def build_gopay_app_headers(authorization: str = "Bearer ", gopay_cfg: Optional[dict[str, Any]] = None) -> dict[str, str]:
    cfg = gopay_cfg if gopay_cfg is not None else {}
    app_version = str(cfg.get("app_version") or DEFAULT_APP_VERSION)
    if not cfg.get("_device_fingerprint_initialized"):
        make, model = PHONE_MODELS[0]
        cfg.setdefault("_fp_device_os", ANDROID_VERSIONS[0])
        cfg.setdefault("_fp_phone_make", make)
        cfg.setdefault("_fp_phone_model", f"{make}, {model}")
        cfg.setdefault("_fp_unique_id", _random_unique_id())
        cfg.setdefault("_fp_x_m1", _random_x_m1())
        cfg.setdefault("_fp_device_token", _random_device_token())
        cfg.setdefault("_fp_transaction_id", str(uuid.uuid4()))
        lat = round(-6.2 + random.uniform(-0.05, 0.05), 7)
        lng = round(106.8 + random.uniform(-0.05, 0.05), 7)
        cfg.setdefault("_fp_location", f"{lat},{lng}")
        cfg["_device_fingerprint_initialized"] = True
    cfg.setdefault("_fp_device_token", _random_device_token())
    return {
        "accept-encoding": "gzip, deflate, br",
        "country-code": "ID",
        "gojek-country-code": "ID",
        "gojek-service-area": "1",
        "x-appversion": app_version,
        "x-help-version": app_version,
        "x-uniqueid": str(cfg.get("unique_id") or cfg["_fp_unique_id"]),
        "x-phonemake": str(cfg.get("phone_make") or cfg["_fp_phone_make"]),
        "x-phonemodel": str(cfg.get("phone_model") or cfg["_fp_phone_model"]),
        "x-deviceos": str(cfg.get("device_os") or cfg["_fp_device_os"]),
        "x-user-type": "customer",
        "x-appid": "com.gojek.gopay",
        "gojek-timezone": "Asia/Jakarta",
        "x-apptype": "GOPAY",
        "x-user-locale": "en_ID",
        "accept-language": "en-ID",
        "x-platform": "Android",
        "x-devicetoken": str(cfg.get("device_token") or cfg["_fp_device_token"]),
        "user-agent": f"GoPay/{app_version} (com.gojek.gopay; build:{app_version.replace('.', '')}; {cfg.get('device_os') or cfg['_fp_device_os']})",
        "content-type": "application/json",
        "x-m1": str(cfg.get("x_m1") or cfg["_fp_x_m1"]),
        "x-e2": DEFAULT_X_E2,
        "x-authsdk-version": "1.0.0",
        "x-cvsdk-version": "1.0.0",
        "authorization": authorization,
        "x-request-id": str(uuid.uuid1()),
        "transaction-id": str(cfg.get("_fp_transaction_id") or uuid.uuid4()),
    }


def signed_post(
    url: str,
    body: Any,
    *,
    authorization: str = "Bearer ",
    gopay_cfg: Optional[dict[str, Any]] = None,
    keep_auth: bool = False,
    extra_headers: Optional[dict[str, str]] = None,
    session: Optional[Any] = None,
    timeout: int = 30,
):
    parsed = urlsplit(url)
    host = parsed.netloc
    path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    body_text = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    headers = build_gopay_app_headers(authorization, gopay_cfg)
    if extra_headers:
        headers.update(extra_headers)
    headers["host"] = host
    headers["x-e1"] = sign_x_e1(headers, "POST", host, path, body_text)
    if not keep_auth:
        headers.pop("authorization", None)
    http = session or requests
    return http.post(url, data=body_text, headers=headers, timeout=timeout)


def signed_get(
    url: str,
    *,
    authorization: str = "Bearer ",
    gopay_cfg: Optional[dict[str, Any]] = None,
    keep_auth: bool = False,
    extra_headers: Optional[dict[str, str]] = None,
    session: Optional[Any] = None,
    timeout: int = 30,
):
    parsed = urlsplit(url)
    host = parsed.netloc
    path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    headers = build_gopay_app_headers(authorization, gopay_cfg)
    if extra_headers:
        headers.update(extra_headers)
    headers["host"] = host
    headers["x-e1"] = sign_x_e1(headers, "GET", host, path, "")
    if not keep_auth:
        headers.pop("authorization", None)
    headers.pop("host", None)
    http = session or requests
    return http.get(url, headers=headers, timeout=timeout)


def create_gopay_session(proxy_url: Optional[str] = None) -> Any:
    normalized_proxy = normalize_proxy_url(proxy_url) if proxy_url else ""
    if CurlCffiSession is not None and normalized_proxy:
        session = CurlCffiSession(impersonate="chrome136")
    else:
        session = requests.Session()
    try:
        session.trust_env = False
    except Exception:
        pass
    if normalized_proxy:
        session.proxies = {"http": normalized_proxy, "https": normalized_proxy}
    else:
        session.proxies = {"http": "", "https": ""}
    return session


def _safe_json(resp: Any) -> dict[str, Any]:
    try:
        data = resp.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def query_gopay_balance(
    *,
    access_token: str,
    gopay_cfg: Optional[dict[str, Any]] = None,
    session: Optional[Any] = None,
    timeout: int = 30,
) -> dict[str, Any]:
    access_token = str(access_token or "").strip()
    if not access_token:
        raise GoPayAutoSignupError("缺少 GoPay access_token，无法查询余额")
    resp = signed_get(
        f"{CUSTOMER_URL}/v1/payment-options/balances",
        authorization=f"Bearer {access_token}",
        keep_auth=True,
        gopay_cfg=gopay_cfg,
        session=session,
        timeout=timeout,
    )
    data = _safe_json(resp)
    if resp.status_code >= 400:
        raise GoPayAutoSignupError(f"GoPay 余额查询失败 ({resp.status_code}): {str(getattr(resp, 'text', ''))[:240]}")
    entries = data.get("data") if isinstance(data.get("data"), list) else []
    selected: dict[str, Any] = {}
    for item in entries:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").lower()
        if not selected:
            selected = item
        if "gopay" in item_type or item_type in {"wallet", "go_pay"}:
            selected = item
            break
    balance = selected.get("balance") if isinstance(selected.get("balance"), dict) else {}
    raw_value = balance.get("value")
    try:
        value = float(raw_value)
    except Exception:
        value = 0.0
    return {
        "value": value,
        "currency": str(balance.get("currency") or selected.get("country_code") or "IDR"),
        "display_value": str(balance.get("display_value") or ""),
        "type": str(selected.get("type") or ""),
        "token": str(selected.get("token") or ""),
        "raw": data,
    }


def _extract_errors(resp_json: dict[str, Any]) -> list[dict[str, Any]]:
    errors = resp_json.get("errors", [])
    return errors if isinstance(errors, list) else []


def _has_error_code(resp_json: dict[str, Any], code: str) -> bool:
    return any(isinstance(item, dict) and item.get("code") == code for item in _extract_errors(resp_json))


def _probe_response_summary(resp: Any, data: dict[str, Any]) -> str:
    errors = _extract_errors(data)
    error_codes = [
        str(item.get("code") or "")
        for item in errors
        if isinstance(item, dict) and str(item.get("code") or "").strip()
    ]
    body = str(getattr(resp, "text", "") or "").replace("\n", " ").replace("\r", " ").strip()
    parts = [f"status={getattr(resp, 'status_code', '<unknown>')}"]
    if error_codes:
        parts.append(f"errors={','.join(error_codes[:4])}")
    if body:
        parts.append(f"body={body[:240]}")
    return " ".join(parts)


def _accept_signup_consents(
    *,
    access_token: str,
    gopay_cfg: dict[str, Any],
    session: Any,
) -> None:
    resp = signed_post(
        f"{CUSTOMER_URL}/api/v2/consents/accept",
        {
            "consents": [
                {"consent_name": "gopay_app_tnc", "user_type": "CUSTOMER", "flow": "signUp"},
                {"consent_name": "gopay_app_privacy_note", "user_type": "CUSTOMER", "flow": "signUp"},
                {"consent_name": "gojek_app_tnc", "user_type": "CUSTOMER", "flow": "signUp"},
                {"consent_name": "gojek_app_privacy_note", "user_type": "CUSTOMER", "flow": "signUp"},
            ]
        },
        authorization=f"Bearer {access_token}",
        keep_auth=True,
        extra_headers={"key": "value"},
        gopay_cfg=gopay_cfg,
        session=session,
    )
    data = _safe_json(resp) if resp.status_code < 500 else {}
    if resp.status_code >= 400 or data.get("success") is False:
        raise GoPayAutoSignupError(f"consent accept 失败 ({resp.status_code}): {resp.text[:300]}")


def _ensure_pin_allowed(
    *,
    access_token: str,
    pin: str,
    gopay_cfg: dict[str, Any],
    session: Any,
) -> None:
    resp = signed_post(
        f"{CUSTOMER_URL}/api/v1/users/pins/allowed",
        {"pin": pin},
        authorization=f"Bearer {access_token}",
        keep_auth=True,
        gopay_cfg=gopay_cfg,
        session=session,
    )
    data = _safe_json(resp) if resp.status_code < 500 else {}
    if resp.status_code >= 400 or data.get("success") is False:
        raise GoPayAutoSignupError(f"PIN allowed 失败 ({resp.status_code}): {resp.text[:300]}")


def _setup_pin(
    *,
    access_token: str,
    pin: str,
    otp_provider: Callable[[str], str],
    gopay_cfg: dict[str, Any],
    session: Any,
    log: Callable[[str], None],
    pre_otp_hook: Callable[[], None] | None = None,
) -> None:
    log("[gopay-signup] 校验 PIN 是否可设置...")
    _ensure_pin_allowed(
        access_token=access_token,
        pin=pin,
        gopay_cfg=gopay_cfg,
        session=session,
    )
    log("[gopay-signup] 请求 PIN 设置验证方式...")
    resp = signed_post(
        f"{BASE_URL}/cvs/v1/methods",
        {
            "country_code": None,
            "email_address": None,
            "client_id": CLIENT_ID,
            "phone_number": None,
            "client_secret": CLIENT_SECRET,
            "flow": "goto_pin_wa_sms",
            "device_verification_token_id": None,
        },
        authorization=f"Bearer {access_token}",
        keep_auth=True,
        gopay_cfg=gopay_cfg,
        session=session,
    )
    methods_data = _safe_json(resp).get("data", {}) if resp.status_code < 500 else {}
    pin_verification_id = str(methods_data.get("verification_id") or "")
    if not pin_verification_id:
        raise GoPayAutoSignupError(f"PIN methods 失败: {resp.text[:300]}")
    if pre_otp_hook:
        pre_otp_hook()
    time.sleep(random.uniform(1.0, 2.5))
    log("[gopay-signup] 触发 PIN 设置 SMS OTP...")
    resp = signed_post(
        f"{BASE_URL}/cvs/v1/initiate",
        {
            "verification_id": pin_verification_id,
            "flow": "goto_pin_wa_sms",
            "verification_method": "otp_sms",
            "country_code": None,
            "email_address": None,
            "client_id": CLIENT_ID,
            "phone_number": None,
            "client_secret": CLIENT_SECRET,
            "is_multiple_method": None,
            "device_verification_token_id": None,
        },
        authorization=f"Bearer {access_token}",
        keep_auth=True,
        gopay_cfg=gopay_cfg,
        session=session,
    )
    init_data = _safe_json(resp).get("data", {}) if resp.status_code < 500 else {}
    pin_otp_token = str(init_data.get("otp_token") or "")
    if not pin_otp_token:
        raise GoPayAutoSignupError(f"PIN initiate 失败: {resp.text[:300]}")
    log("[gopay-signup] 等待 PIN 设置 SMS OTP...")
    pin_otp = otp_provider("gopay_pin_setup")
    if not pin_otp:
        raise GoPayAutoSignupError("PIN OTP 未提供")
    log("[gopay-signup] 已收到 PIN 设置 SMS OTP，开始校验...")
    resp = signed_post(
        f"{BASE_URL}/cvs/v1/verify",
        {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "flow": "goto_pin_wa_sms",
            "verification_method": "otp_sms",
            "verification_id": pin_verification_id,
            "data": {"otp": pin_otp, "otp_token": pin_otp_token},
        },
        authorization=f"Bearer {access_token}",
        keep_auth=True,
        gopay_cfg=gopay_cfg,
        session=session,
    )
    verify_data = _safe_json(resp).get("data", {}) if resp.status_code < 500 else {}
    pin_verification_token = str(verify_data.get("verification_token") or "")
    if not pin_verification_token:
        raise GoPayAutoSignupError(f"PIN verify 失败: {resp.text[:300]}")
    log("[gopay-signup] PIN OTP 校验成功，提交 PIN 设置...")
    headers = build_gopay_app_headers(f"Bearer {access_token}", gopay_cfg)
    headers["verification-token"] = f"Bearer {pin_verification_token}"
    headers["is-token-required"] = "false"
    headers["host"] = urlsplit(CUSTOMER_URL).netloc
    pin_body = {"client_id": "", "pin": pin, "challenge_id": ""}
    body_text = json.dumps(pin_body, separators=(",", ":"))
    path = "/api/v2/users/pins/setup/tokens"
    headers["x-e1"] = sign_x_e1(headers, "POST", headers["host"], path, body_text)
    headers.pop("host", None)
    resp = session.post(f"{CUSTOMER_URL}{path}", data=body_text, headers=headers, timeout=30)
    if resp.status_code >= 400:
        raise GoPayAutoSignupError(f"PIN setup 失败 ({resp.status_code}): {resp.text[:300]}")
    log("[gopay-signup] PIN 设置完成")


def auto_login(
    *,
    phone: str,
    country_code: str,
    pin: str,
    otp_provider: Callable[[str], str],
    gopay_cfg: Optional[dict[str, Any]] = None,
    proxy_url: Optional[str] = None,
    log: Callable[[str], None] = logger.info,
) -> GoPayAccountResult:
    phone = re.sub(r"\D", "", phone)
    if not country_code.startswith("+"):
        country_code = f"+{country_code}"
    session = create_gopay_session(proxy_url)
    cfg = gopay_cfg if gopay_cfg is not None else {}
    log(f"[gopay-login] 探测 {country_code}{phone}")
    resp = signed_post(
        f"{BASE_URL}/goto-auth/login/methods",
        {
            "phone_number": phone,
            "country_code": country_code,
            "email": "",
            "device_verification_token_id": "",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        gopay_cfg=cfg,
        session=session,
    )
    data = _safe_json(resp) if resp.status_code < 400 else {}
    if _has_error_code(data, "auth:error:user:not_found"):
        raise GoPayAutoSignupError(f"账号不存在: {country_code}{phone}")
    time.sleep(random.uniform(1.5, 3.0))
    verification_id = str(uuid.uuid4())
    resp = signed_post(
        f"{BASE_URL}/cvs/v1/methods",
        {
            "country_code": country_code,
            "email_address": None,
            "client_id": CLIENT_ID,
            "phone_number": phone,
            "client_secret": CLIENT_SECRET,
            "flow": "login_1fa",
            "device_verification_token_id": None,
        },
        authorization="",
        keep_auth=True,
        gopay_cfg=cfg,
        session=session,
    )
    methods_data = _safe_json(resp).get("data", {}) if resp.status_code < 500 else {}
    verification_id = str(methods_data.get("verification_id") or verification_id)
    time.sleep(random.uniform(1.0, 2.5))
    resp = signed_post(
        f"{BASE_URL}/cvs/v1/initiate",
        {
            "verification_id": verification_id,
            "flow": "login_1fa",
            "verification_method": "otp_sms",
            "country_code": country_code,
            "email_address": None,
            "client_id": CLIENT_ID,
            "phone_number": phone,
            "client_secret": CLIENT_SECRET,
            "is_multiple_method": None,
            "device_verification_token_id": None,
        },
        authorization="",
        keep_auth=True,
        extra_headers={"key": "value"},
        gopay_cfg=cfg,
        session=session,
    )
    init_data = _safe_json(resp).get("data", {}) if resp.status_code < 500 else {}
    otp_token = str(init_data.get("otp_token") or "")
    if not otp_token:
        raise GoPayAutoSignupError(f"login initiate 未返回 otp_token: {resp.text[:300]}")
    otp = otp_provider("gopay_login")
    if not otp:
        raise GoPayAutoSignupError("OTP 未提供")
    resp = signed_post(
        f"{BASE_URL}/cvs/v1/verify",
        {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "flow": "login_1fa",
            "verification_method": "otp_sms",
            "verification_id": verification_id,
            "data": {"otp": otp, "otp_token": otp_token},
        },
        gopay_cfg=cfg,
        session=session,
    )
    verify_data = _safe_json(resp).get("data", {}) if resp.status_code < 500 else {}
    verification_token = str(verify_data.get("verification_token") or "")
    if not verification_token:
        raise GoPayAutoSignupError("login verify 失败")
    resp = signed_post(
        f"{BASE_URL}/goto-auth/accountlist",
        {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET},
        extra_headers={"verification-token": f"Bearer {verification_token}"},
        gopay_cfg=cfg,
        session=session,
    )
    acc_data = _safe_json(resp).get("data", {}) if resp.status_code < 500 else {}
    account_list = acc_data.get("account_list", []) if isinstance(acc_data, dict) else []
    one_fa_token = str(acc_data.get("1fa_token") or "")
    account_id = ""
    if isinstance(account_list, list) and account_list:
        first = account_list[0] if isinstance(account_list[0], dict) else {}
        account_id = str(first.get("account_id") or first.get("id") or "")
    if not account_id:
        account_id = str(acc_data.get("account_id") or acc_data.get("id") or "")
    if not account_id or not one_fa_token:
        raise GoPayAutoSignupError("accountlist 缺少 account_id/1fa_token")
    resp = signed_post(
        f"{BASE_URL}/goto-auth/token",
        {
            "grant_type": "cvs",
            "account_id": account_id,
            "token": one_fa_token,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "ext_user_token": None,
        },
        gopay_cfg=cfg,
        session=session,
    )
    token_data = (_safe_json(resp).get("data") or {}) if resp.status_code < 500 else {}
    if not isinstance(token_data, dict):
        token_data = {}
    access_token = str(token_data.get("access_token") or "")
    refresh_token = str(token_data.get("refresh_token") or "")
    if not access_token:
        raise GoPayAutoSignupError(f"token 换取失败: {resp.text[:300]}")
    try:
        _setup_pin(
            access_token=access_token,
            pin=pin,
            otp_provider=otp_provider,
            gopay_cfg=cfg,
            session=session,
            log=log,
            pre_otp_hook=None,
        )
    except GoPayAutoSignupError as exc:
        lowered = str(exc).lower()
        if "already" not in lowered and "exist" not in lowered:
            raise
    return GoPayAccountResult(
        access_token=access_token,
        refresh_token=refresh_token,
        account_id=account_id,
        phone=phone,
        country_code=country_code,
        pin=pin,
        session=session,
        gopay_cfg=cfg,
    )


def appium_auto_signup(
    *,
    phone: str,
    country_code: str,
    pin: str,
    otp_provider: Callable[[str], str],
    appium_config: Optional[dict[str, Any]] = None,
    proxy_url: Optional[str] = None,
    log: Callable[[str], None] = logger.info,
    pre_pin_otp_hook: Callable[[], None] | None = None,
) -> GoPayAccountResult:
    """通过 Appium 自动化 GoPay APP 完成注册，再用 HTTP login 获取 token。

    流程:
    1. Appium 驱动真实 GoPay APP 完成注册 + PIN 设置
       （APP 内部携带真实 F4 token + Play Integrity，绕过 cvs/v1/initiate 封锁）
    2. 注册完成后，尝试从设备存储提取 token
    3. 如果提取失败，通过 HTTP auto_login (login_1fa) 获取 token
    """
    try:
        from autoteam.gopay_appium import GopayAppiumDriver, GopayAppiumError
    except ImportError as exc:
        raise GoPayAutoSignupError(
            "Appium 模式需要安装依赖: pip install Appium-Python-Client"
        ) from exc

    phone = re.sub(r"\D", "", phone)
    if not country_code.startswith("+"):
        country_code = f"+{country_code}"

    acfg = appium_config or {}
    name = _random_name()

    driver = GopayAppiumDriver(
        appium_url=str(acfg.get("appium_url") or _env_str("GOPAY_APPIUM_URL", "http://127.0.0.1:4723")),
        adb_serial=str(acfg.get("adb_serial") or ""),
        apk_path=str(acfg.get("apk_path") or ""),
        log=log,
    )
    try:
        driver.start_session()
        result = driver.signup(
            phone=phone,
            country_code=country_code,
            name=name,
            pin=pin,
            otp_provider=otp_provider,
            pre_pin_otp_hook=pre_pin_otp_hook,
        )
    except GopayAppiumError as exc:
        if "手机号已注册" in str(exc):
            raise GoPayNumberAlreadyRegistered(str(exc)) from exc
        raise
    except Exception as exc:
        raise GoPayAutoSignupError(f"Appium 注册失败: {exc}") from exc
    finally:
        driver.close()

    # 如果 Appium 成功提取了 token，直接返回
    access_token = str(result.get("access_token") or "")
    refresh_token = str(result.get("refresh_token") or "")
    account_id = str(result.get("account_id") or "")

    if access_token:
        log("[gopay-appium] 从设备存储提取 token 成功，跳过 HTTP login")
        return GoPayAccountResult(
            access_token=access_token,
            refresh_token=refresh_token,
            account_id=account_id,
            phone=phone,
            country_code=country_code,
            pin=pin,
        )

    # Token 提取失败 → 通过 HTTP login_1fa 获取 token
    log("[gopay-appium] 设备 token 提取失败，通过 HTTP login_1fa 获取 token...")
    if pre_pin_otp_hook:
        pre_pin_otp_hook()
    return auto_login(
        phone=phone,
        country_code=country_code,
        pin=pin,
        otp_provider=otp_provider,
        proxy_url=proxy_url,
        log=log,
    )


def auto_signup(
    *,
    phone: str,
    country_code: str,
    pin: str,
    otp_provider: Callable[[str], str],
    gopay_cfg: Optional[dict[str, Any]] = None,
    proxy_url: Optional[str] = None,
    log: Callable[[str], None] = logger.info,
    pre_pin_otp_hook: Callable[[], None] | None = None,
) -> GoPayAccountResult:
    phone = re.sub(r"\D", "", phone)
    if not country_code.startswith("+"):
        country_code = f"+{country_code}"
    session = create_gopay_session(proxy_url)
    cfg = gopay_cfg if gopay_cfg is not None else {}
    name = _random_name()
    log(f"[gopay-signup] 探测手机号是否已注册: {country_code}{phone}")
    resp = signed_post(
        f"{BASE_URL}/goto-auth/login/methods",
        {
            "phone_number": phone,
            "country_code": country_code,
            "email": "",
            "device_verification_token_id": "",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        gopay_cfg=cfg,
        session=session,
    )
    data = _safe_json(resp) if resp.status_code < 500 else {}
    if not _has_error_code(data, "auth:error:user:not_found"):
        summary = _probe_response_summary(resp, data)
        if resp.status_code < 500 and data.get("success") is True and isinstance(data.get("data"), dict):
            methods = data.get("data", {}).get("methods")
            default_method = data.get("data", {}).get("default_method")
            raise GoPayNumberAlreadyRegistered(
                "号码已存在 GoPay 钱包: "
                f"phone={country_code}{phone} default_method={default_method or ''} "
                f"methods={methods or []} {summary}"
            )
        raise GoPaySignupProbeError(f"GoPay 注册前探测异常: phone={country_code}{phone} {summary}")
    log("[gopay-signup] 手机号未注册，准备获取注册 verification_id")
    time.sleep(random.uniform(1.5, 3.0))
    verification_id = str(uuid.uuid4())
    resp = signed_post(
        f"{BASE_URL}/cvs/v1/methods",
        {
            "country_code": country_code,
            "email_address": None,
            "client_id": CLIENT_ID,
            "phone_number": phone,
            "client_secret": CLIENT_SECRET,
            "flow": "signup",
            "device_verification_token_id": None,
        },
        authorization="",
        keep_auth=True,
        gopay_cfg=cfg,
        session=session,
    )
    methods_data = _safe_json(resp).get("data", {}) if resp.status_code < 500 else {}
    verification_id = str(methods_data.get("verification_id") or verification_id)
    log("[gopay-signup] 已获取注册 verification_id，触发注册 SMS OTP")
    time.sleep(random.uniform(1.0, 2.5))
    resp = signed_post(
        f"{BASE_URL}/cvs/v1/initiate",
        {
            "verification_id": verification_id,
            "flow": "signup",
            "verification_method": "otp_sms",
            "country_code": country_code,
            "email_address": None,
            "client_id": CLIENT_ID,
            "phone_number": phone,
            "client_secret": CLIENT_SECRET,
            "is_multiple_method": None,
            "device_verification_token_id": None,
        },
        authorization="",
        keep_auth=True,
        extra_headers={"key": "value"},
        gopay_cfg=cfg,
        session=session,
    )

    init_data = _safe_json(resp).get("data", {}) if resp.status_code < 500 else {}
    otp_token = str(init_data.get("otp_token") or "")
    if not otp_token:
        raise GoPayAutoSignupError(f"signup initiate 未返回 otp_token: {resp.text[:300]}")
    log("[gopay-signup] 等待注册 SMS OTP...")
    otp = otp_provider("gopay_signup")
    if not otp:
        raise GoPayAutoSignupError("注册 OTP 未提供")
    log("[gopay-signup] 已收到注册 SMS OTP，开始校验...")
    resp = signed_post(
        f"{BASE_URL}/cvs/v1/verify",
        {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "flow": "signup",
            "verification_method": "otp_sms",
            "verification_id": verification_id,
            "data": {"otp": otp, "otp_token": otp_token},
        },
        gopay_cfg=cfg,
        session=session,
    )
    verify_data = _safe_json(resp).get("data", {}) if resp.status_code < 500 else {}
    verification_token = str(verify_data.get("verification_token") or "")
    if not verification_token:
        raise GoPayAutoSignupError("signup verify 失败")
    log("[gopay-signup] 注册 OTP 校验成功，创建 GoPay customer...")
    resp = signed_post(
        f"{API_URL}/v7/customers/signup",
        {
            "client_name": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "data": {
                "name": name,
                "phone": f"{country_code}{phone}",
                "email": "",
                "signed_up_country": country_code,
                "onboarding_partner": "gopay_consumer_app",
            },
        },
        authorization=SIGNUP_BASIC_AUTH,
        keep_auth=True,
        extra_headers={"verification-token": f"Bearer {verification_token}"},
        gopay_cfg=cfg,
        session=session,
    )
    signup_data = _safe_json(resp).get("data") or {} if resp.status_code < 500 else {}
    signup_access = str(signup_data.get("access_token") or "") if isinstance(signup_data, dict) else ""
    signup_refresh = str(signup_data.get("refresh_token") or "") if isinstance(signup_data, dict) else ""
    account_id = str(signup_data.get("resource_owner_id") or (signup_data.get("customer") or {}).get("id") or "")
    if not signup_access:
        raise GoPayAutoSignupError("signup 失败")
    log("[gopay-signup] GoPay customer 创建成功，刷新访问 token...")
    resp = signed_post(
        f"{BASE_URL}/goto-auth/token",
        {
            "grant_type": "refresh_token",
            "token": signup_refresh,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        authorization=f"Bearer {signup_access}",
        keep_auth=True,
        gopay_cfg=cfg,
        session=session,
    )
    token_data = _safe_json(resp).get("data") or {} if resp.status_code < 500 else {}
    access_token = str(token_data.get("access_token") or signup_access)
    refresh_token = str(token_data.get("refresh_token") or signup_refresh)
    log("[gopay-signup] GoPay token 已就绪，接受必要授权...")
    _accept_signup_consents(
        access_token=access_token,
        gopay_cfg=cfg,
        session=session,
    )
    log("[gopay-signup] 授权已接受，开始设置 PIN...")
    _setup_pin(
        access_token=access_token,
        pin=pin,
        otp_provider=otp_provider,
        gopay_cfg=cfg,
        session=session,
        log=log,
        pre_otp_hook=pre_pin_otp_hook,
    )
    log("[gopay-signup] GoPay 钱包注册流程完成")
    return GoPayAccountResult(
        access_token=access_token,
        refresh_token=refresh_token,
        account_id=account_id,
        phone=phone,
        country_code=country_code,
        pin=pin,
        session=session,
        gopay_cfg=cfg,
    )


def _local_public_base_url(base_url: str = "") -> str:
    return str(base_url or _env_str("AUTOTEAM_LOCAL_BASE_URL", "http://127.0.0.1:8787")).strip().rstrip("/")


def register_gopay_wallet(
    *,
    pin: str,
    proxy_url: str | None = None,
    network_retry_proxy_provider: Callable[[], str | None] | None = None,
    country_code: str = "",
    sms_provider: str = "",
    hero_sms_config: dict[str, Any] | None = None,
    smscloud_config: dict[str, Any] | None = None,
    smsbower_config: dict[str, Any] | None = None,
    smscode_config: dict[str, Any] | None = None,
    appium_config: dict[str, Any] | None = None,
    public_base_url: str = "",
    log: Callable[[str], None] = logger.info,
) -> GoPayAutoRegistrationResult:
    hero_sms_config = hero_sms_config or {}
    smscloud_config = smscloud_config or {}
    smsbower_config = smsbower_config or {}
    smscode_config = smscode_config or {}
    provider = _normalize_sms_provider(
        sms_provider
        or str(hero_sms_config.get("provider") or "")
        or str(smscloud_config.get("provider") or "")
        or str(smsbower_config.get("provider") or "")
        or str(smscode_config.get("provider") or "")
        or _env_str("GOPAY_AUTO_SIGNUP_SMS_PROVIDER", "smscloud")
    )
    resolved_country_code = country_code or _env_str("GOPAY_AUTO_SIGNUP_COUNTRY_CODE", "+62")
    resolved_pin = str(pin or _env_str("GOPAY_AUTO_SIGNUP_DEFAULT_PIN", "558023")).strip()
    effective_proxy = str(proxy_url or _env_str("GOPAY_AUTO_SIGNUP_PROXY_URL")).strip() or None
    require_proxy = _env_str("GOPAY_AUTO_SIGNUP_REQUIRE_PROXY", "1").lower() not in {"0", "false", "no", "off"}

    if not re.fullmatch(r"\d{6}", resolved_pin):
        raise GoPayAutoSignupError("GoPay 自动注册 PIN 必须是 6 位数字")
    if require_proxy and not effective_proxy:
        raise GoPayAutoSignupError(
            "GoPay 自动注册需要配置印尼代理，已停止取号；请在 GoPay 自动注册配置中填写 GOPAY_AUTO_SIGNUP_PROXY_URL，"
            "或传入任务 proxy_url。若确认当前机器就是印尼出口，可设置 GOPAY_AUTO_SIGNUP_REQUIRE_PROXY=0"
        )
    log(
        "[gopay-signup] 准备注册 GoPay 钱包: "
        f"provider={provider} country={resolved_country_code} proxy={'enabled' if effective_proxy else 'disabled'}"
    )

    if provider == "smscloud":
        smscloud_auth = str(
            smscloud_config.get("xi_token")
            or _env_str("GOPAY_AUTO_SIGNUP_SMSCLOUD_XI_TOKEN")
        ).strip()
        smscloud_base_url = _smscloud_base_url(
            str(smscloud_config.get("base_url") or _env_str("GOPAY_AUTO_SIGNUP_SMSCLOUD_BASE_URL", "https://smscloud.sbs/api"))
        )
        sms_country_value = str(smscloud_config.get("country") or _env_str("GOPAY_AUTO_SIGNUP_SMSCLOUD_COUNTRY", "6")).strip()
        sms_service = str(smscloud_config.get("service") or _env_str("GOPAY_AUTO_SIGNUP_SMSCLOUD_SERVICE", "ni")).strip()
        sms_max_price = str(smscloud_config.get("max_price") or _env_str("GOPAY_AUTO_SIGNUP_SMSCLOUD_MAX_PRICE")).strip()
        try:
            sms_timeout = int(
                float(
                    smscloud_config.get("timeout_sec")
                    or _env_int("GOPAY_AUTO_SIGNUP_SMSCLOUD_TIMEOUT", DEFAULT_AUTO_SIGNUP_OTP_TIMEOUT_SEC)
                )
            )
        except Exception:
            sms_timeout = DEFAULT_AUTO_SIGNUP_OTP_TIMEOUT_SEC
        if not smscloud_auth:
            raise GoPayAutoSignupError("缺少 GOPAY_AUTO_SIGNUP_SMSCLOUD_XI_TOKEN 配置")
        activation_id, phone_raw, error = _smscloud_get_number(
            service_code=sms_service,
            country_id=sms_country_value,
            base_url=smscloud_base_url,
            token=smscloud_auth,
            max_price=sms_max_price,
        )
        if not activation_id:
            if "登录凭证已过期" in str(error):
                raise GoPayAutoSignupError(
                    "smscloud 登录凭证无效：取号接口需要网站 localStorage 中的 XI_TOKEN，"
                    "请配置 GOPAY_AUTO_SIGNUP_SMSCLOUD_XI_TOKEN，不是个人资料里的 API密钥"
                )
            raise GoPayAutoSignupError(f"smscloud 取号失败: {error}")
        log(f"[gopay-signup] smscloud 取号成功: +{resolved_country_code.strip('+')}***{str(phone_raw)[-4:]}")
        activation: SmsActivation | SmsCloudActivation | SmsCodeActivation = SmsCloudActivation(
            activation_id=activation_id,
            phone=phone_raw,
            country_id=sms_country_value,
            base_url=smscloud_base_url,
            token=smscloud_auth,
            log=log,
        )
    elif provider == "smscode":
        smscode_token = str(smscode_config.get("api_token") or _env_str("GOPAY_AUTO_SIGNUP_SMSCODE_API_TOKEN")).strip()
        smscode_base_url = _smscode_base_url(
            str(smscode_config.get("base_url") or _env_str("GOPAY_AUTO_SIGNUP_SMSCODE_BASE_URL", DEFAULT_SMSCODE_BASE_URL))
        )
        sms_country_value = str(smscode_config.get("country_id") or _env_str("GOPAY_AUTO_SIGNUP_SMSCODE_COUNTRY_ID", "6")).strip() or "6"
        smscode_platform_id = str(smscode_config.get("platform_id") or _env_str("GOPAY_AUTO_SIGNUP_SMSCODE_PLATFORM_ID")).strip()
        smscode_platform_query = str(
            smscode_config.get("platform_query")
            or _env_str("GOPAY_AUTO_SIGNUP_SMSCODE_PLATFORM_QUERY", "gopay")
        ).strip() or "gopay"
        smscode_product_id = str(smscode_config.get("product_id") or _env_str("GOPAY_AUTO_SIGNUP_SMSCODE_PRODUCT_ID")).strip()
        smscode_min_price = str(smscode_config.get("min_price") or _env_str("GOPAY_AUTO_SIGNUP_SMSCODE_MIN_PRICE")).strip()
        smscode_max_price = str(smscode_config.get("max_price") or _env_str("GOPAY_AUTO_SIGNUP_SMSCODE_MAX_PRICE")).strip()
        try:
            sms_timeout = int(
                float(
                    smscode_config.get("timeout_sec")
                    or _env_int("GOPAY_AUTO_SIGNUP_SMSCODE_TIMEOUT", DEFAULT_AUTO_SIGNUP_OTP_TIMEOUT_SEC)
                )
            )
        except Exception:
            sms_timeout = DEFAULT_AUTO_SIGNUP_OTP_TIMEOUT_SEC
        if not smscode_token:
            raise GoPayAutoSignupError("缺少 GOPAY_AUTO_SIGNUP_SMSCODE_API_TOKEN 配置")
        activation_id, phone_raw, error = _smscode_get_number(
            base_url=smscode_base_url,
            api_token=smscode_token,
            country_id=sms_country_value,
            platform_id=smscode_platform_id,
            platform_query=smscode_platform_query,
            product_id=smscode_product_id,
            min_price=smscode_min_price,
            max_price=smscode_max_price,
        )
        if not activation_id:
            raise GoPayAutoSignupError(f"SMSCode 取号失败: {error}")
        log(f"[gopay-signup] SMSCode 取号成功: +{resolved_country_code.strip('+')}***{str(phone_raw)[-4:]}")
        activation = SmsCodeActivation(
            activation_id=activation_id,
            phone=phone_raw,
            country_id=sms_country_value,
            base_url=smscode_base_url,
            api_token=smscode_token,
            log=log,
        )
    else:
        hero_api_key = str(hero_sms_config.get("api_key") or _env_str("GOPAY_AUTO_SIGNUP_HERO_SMS_API_KEY")).strip()
        hero_base_url = str(
            hero_sms_config.get("base_url")
            or _env_str("GOPAY_AUTO_SIGNUP_HERO_SMS_BASE_URL", "https://hero-sms.com/stubs/handler_api.php")
        ).strip()
        try:
            sms_country = int(float(hero_sms_config.get("country") or _env_int("GOPAY_AUTO_SIGNUP_HERO_SMS_COUNTRY", 6)))
        except Exception:
            sms_country = 6
        sms_service = str(hero_sms_config.get("service") or _env_str("GOPAY_AUTO_SIGNUP_HERO_SMS_SERVICE", "ni")).strip()
        hero_max_price = str(
            hero_sms_config.get("max_price") or _env_str("GOPAY_AUTO_SIGNUP_HERO_SMS_MAX_PRICE")
        ).strip()
        hero_min_price = str(
            hero_sms_config.get("min_price") or _env_str("GOPAY_AUTO_SIGNUP_HERO_SMS_MIN_PRICE")
        ).strip()
        hero_preferred_price = str(
            hero_sms_config.get("preferred_price")
            or hero_sms_config.get("price_tier")
            or _env_str("GOPAY_AUTO_SIGNUP_HERO_SMS_PREFERRED_PRICE")
        ).strip()
        try:
            sms_timeout = int(
                float(
                    hero_sms_config.get("timeout_sec")
                    or _env_int("GOPAY_AUTO_SIGNUP_HERO_SMS_TIMEOUT", DEFAULT_AUTO_SIGNUP_OTP_TIMEOUT_SEC)
                )
            )
        except Exception:
            sms_timeout = DEFAULT_AUTO_SIGNUP_OTP_TIMEOUT_SEC
        if not hero_api_key:
            raise GoPayAutoSignupError("缺少 GOPAY_AUTO_SIGNUP_HERO_SMS_API_KEY 配置")
        activation_id, phone_raw, error = _hero_get_number(
            service_code=sms_service,
            country_id=sms_country,
            base_url=hero_base_url,
            api_key=hero_api_key,
            max_price=hero_max_price,
            min_price=hero_min_price,
            preferred_price=hero_preferred_price,
        )
        if not activation_id:
            raise GoPayAutoSignupError(f"hero-sms 取号失败: {error}")
        log(f"[gopay-signup] hero-sms 取号成功: +{resolved_country_code.strip('+')}***{str(phone_raw)[-4:]}")
        activation = SmsActivation(
            activation_id=activation_id,
            phone=phone_raw,
            country_id=sms_country,
            base_url=hero_base_url,
            api_key=hero_api_key,
            log=log,
        )

    phone = str(phone_raw or "").lstrip("+")
    digits_country_code = re.sub(r"\D", "", resolved_country_code) or "62"
    if phone.startswith(digits_country_code):
        phone = phone[len(digits_country_code) :]
    shared_cfg: dict[str, Any] = {}

    def otp_provider(label: str) -> str:
        return activation.wait_code(timeout_sec=sms_timeout, label=label)

    def reactivate_before_pin() -> None:
        activation.resend()

    signup_mode = str(
        (appium_config or {}).get("signup_mode", "")
        or _env_str("GOPAY_AUTO_SIGNUP_MODE")
    ).strip().lower()
    if signup_mode != "appium":
        signup_mode = "http"
    log(f"[gopay-signup] signup_mode resolved: request={(appium_config or {}).get('signup_mode', '')!r} final={signup_mode!r}")

    cancel_scheduled = False
    try:
        try:
            if signup_mode == "appium":
                # Appium 模式：通过真实 APP 完成注册，绕过 cvs/v1/initiate 服务端封锁
                log("[gopay-signup] 使用 Appium 模式注册")
                account_result = appium_auto_signup(
                    phone=phone,
                    country_code=resolved_country_code,
                    pin=resolved_pin,
                    otp_provider=otp_provider,
                    appium_config=appium_config,
                    proxy_url=effective_proxy,
                    log=log,
                    pre_pin_otp_hook=reactivate_before_pin,
                )
            else:
                # HTTP 模式（原有流程）
                network_attempts = max(1, min(5, _env_int("GOPAY_AUTO_SIGNUP_CURRENT_NUMBER_NETWORK_ATTEMPTS", 3)))
                for network_attempt in range(1, network_attempts + 1):
                    try:
                        account_result = auto_signup(
                            phone=phone,
                            country_code=resolved_country_code,
                            pin=resolved_pin,
                            otp_provider=otp_provider,
                            gopay_cfg=shared_cfg,
                            proxy_url=effective_proxy,
                            log=log,
                            pre_pin_otp_hook=reactivate_before_pin,
                        )
                        break
                    except Exception as exc:
                        if not _looks_like_transient_gopay_network_error(exc) or network_attempt >= network_attempts:
                            raise
                        selected_retry_proxy = ""
                        if network_retry_proxy_provider is not None:
                            try:
                                selected_retry_proxy = str(network_retry_proxy_provider() or "").strip()
                            except Exception as proxy_exc:
                                log(
                                    "GoPay 注册网络中断，切换代理失败，将继续使用当前代理重试: "
                                    f"error={str(proxy_exc)[:180]}"
                                )
                        if selected_retry_proxy:
                            effective_proxy = selected_retry_proxy
                        delay = min(8.0, 1.5 * network_attempt)
                        log(
                            (
                                "GoPay 注册网络中断，已切换代理并使用当前号码重试: "
                                if selected_retry_proxy
                                else "GoPay 注册网络中断，使用当前号码重试: "
                            )
                            + f"attempt={network_attempt + 1}/{network_attempts} "
                            f"phone={resolved_country_code}{phone[:2]}***{phone[-4:] if len(phone) >= 4 else phone} "
                            f"error={str(exc)[:180]}"
                        )
                        time.sleep(delay)
        except GoPayNumberAlreadyRegistered as exc:
            _delayed_cancel_activation(activation, log=log, reason=str(exc))
            cancel_scheduled = True
            safe_detail = re.sub(
                r"phone=\+?\d+",
                f"phone={resolved_country_code}{phone[:2]}***{phone[-4:]}" if len(phone) >= 6 else "phone=<masked>",
                str(exc),
            )
            raise GoPayNumberAlreadyRegistered(
                "sms 号码已存在 GoPay 钱包，无法保证 PIN 与配置一致，已放弃该号码并准备换号: "
                f"{safe_detail}"
            ) from exc
        except GoPaySignupProbeError:
            raise
        bridge = create_sms_bridge(activation)
        return GoPayAutoRegistrationResult(
            phone_number=phone,
            country_code=re.sub(r"\D", "", resolved_country_code) or "62",
            gopay_pin=resolved_pin,
            sms_url=f"{_local_public_base_url(public_base_url)}/otp/gopay-signup/{bridge.token}",
            activation_id=activation_id,
            bridge_token=bridge.token,
            access_token=account_result.access_token,
            refresh_token=account_result.refresh_token,
            account_id=account_result.account_id,
            session=account_result.session,
            gopay_cfg=account_result.gopay_cfg,
        )
    except Exception:
        if not cancel_scheduled:
            try:
                activation.cancel()
            except Exception:
                logger.debug("[gopay-signup] cancel activation failed", exc_info=True)
        raise
