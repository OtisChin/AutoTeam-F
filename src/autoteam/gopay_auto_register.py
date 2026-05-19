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
            if self.provider == "smscloud":
                _smscloud_finish(self.base_url, self.api_key, self.activation_id)
            else:
                _hero_set_status(self.base_url, self.api_key, self.activation_id, STATUS_FINISH)
            self.closed = True

    def cancel(self) -> None:
        if not self.closed:
            if self.provider == "smscloud":
                _smscloud_cancel(self.base_url, self.api_key, self.activation_id)
            else:
                _hero_set_status(self.base_url, self.api_key, self.activation_id, STATUS_CANCEL)
            self.closed = True

    def resend(self) -> None:
        if self.closed:
            return
        if self.provider == "smscloud":
            _smscloud_resend(self.base_url, self.api_key, self.activation_id)
        else:
            _hero_set_status(self.base_url, self.api_key, self.activation_id, STATUS_RESEND)

    def reusable_status(self) -> tuple[bool, str]:
        if self.closed:
            return False, "closed"
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
    activation: SmsActivation | SmsCloudActivation,
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


def _hero_get_number(
    *,
    service_code: str,
    country_id: int,
    base_url: str,
    api_key: str,
    max_price: str = "",
) -> tuple[str, str, str]:
    params = {"service": service_code, "country": country_id}
    if str(max_price or "").strip():
        params["maxPrice"] = str(max_price or "").strip()
    ok, text, data = _hero_request(
        base_url,
        api_key,
        "getNumber",
        params,
        timeout=30,
    )
    if not ok:
        return "", "", str(text or "getNumber failed")
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
    return "", "", line or "无法解析号码"


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
    return "hero_sms"


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


def create_sms_bridge(activation: SmsActivation | SmsCloudActivation) -> GoPaySmsBridge:
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
    make, model = random.choice(PHONE_MODELS)
    fingerprint_hash = hashlib.sha256(os.urandom(32)).digest()
    fp_b64 = base64.b64encode(fingerprint_hash).decode().rstrip("=")
    return (
        f"3:{ts}-{rand_id},4:{random.randint(100000, 999999)},5:{make}|3200|2,"
        f"6:{_random_mac()},7:{_random_wifi_ssid()},8:{random.choice(SCREEN_RESOLUTIONS)},"
        f"9:passive,network,fused,gps,10:1,11:{fp_b64},"
        f"15:{os.urandom(16).hex()},16:{uuid.uuid4()}"
    )


def _random_unique_id() -> str:
    return os.urandom(8).hex()


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
        make, model = random.choice(PHONE_MODELS)
        cfg.setdefault("_fp_device_os", random.choice(ANDROID_VERSIONS))
        cfg.setdefault("_fp_phone_make", make)
        cfg.setdefault("_fp_phone_model", f"{make}, {model}")
        cfg.setdefault("_fp_unique_id", _random_unique_id())
        cfg.setdefault("_fp_x_m1", _random_x_m1())
        cfg.setdefault("_fp_transaction_id", str(uuid.uuid4()))
        lat = round(-6.2 + random.uniform(-0.05, 0.05), 7)
        lng = round(106.8 + random.uniform(-0.05, 0.05), 7)
        cfg.setdefault("_fp_location", f"{lat},{lng}")
        cfg["_device_fingerprint_initialized"] = True
    return {
        "accept-encoding": "gzip",
        "country-code": "ID",
        "gojek-country-code": "ID",
        "gojek-service-area": "1",
        "x-appversion": app_version,
        "x-help-version": app_version,
        "x-location": str(cfg.get("x_location") or cfg["_fp_location"]),
        "x-location-accuracy": f"0.0{random.randint(10, 99)}999999552965164",
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
        gopay_cfg=cfg,
        session=session,
    )
    init_data = _safe_json(resp).get("data", {}) if resp.status_code < 500 else {}
    otp_token = str(init_data.get("otp_token") or "")
    if not otp_token:
        raise GoPayAutoSignupError(f"signup initiate 未返回 otp_token: {resp.text[:300]}")
    otp = otp_provider("gopay_signup")
    if not otp:
        raise GoPayAutoSignupError("注册 OTP 未提供")
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
    resp = signed_post(
        f"{BASE_URL}/goto-auth/token",
        {
            "grant_type": "refresh_token",
            "account_id": account_id,
            "token": signup_refresh,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": signup_refresh,
            "ext_user_token": signup_access,
        },
        authorization=f"Bearer {signup_access}",
        keep_auth=True,
        gopay_cfg=cfg,
        session=session,
    )
    token_data = _safe_json(resp).get("data") or {} if resp.status_code < 500 else {}
    access_token = str(token_data.get("access_token") or signup_access)
    refresh_token = str(token_data.get("refresh_token") or signup_refresh)
    _setup_pin(
        access_token=access_token,
        pin=pin,
        otp_provider=otp_provider,
        gopay_cfg=cfg,
        session=session,
        log=log,
        pre_otp_hook=pre_pin_otp_hook,
    )
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
    country_code: str = "",
    sms_provider: str = "",
    hero_sms_config: dict[str, Any] | None = None,
    smscloud_config: dict[str, Any] | None = None,
    public_base_url: str = "",
    log: Callable[[str], None] = logger.info,
) -> GoPayAutoRegistrationResult:
    hero_sms_config = hero_sms_config or {}
    smscloud_config = smscloud_config or {}
    provider = _normalize_sms_provider(
        sms_provider
        or str(hero_sms_config.get("provider") or "")
        or str(smscloud_config.get("provider") or "")
        or _env_str("GOPAY_AUTO_SIGNUP_SMS_PROVIDER", "smscloud")
    )
    resolved_country_code = country_code or _env_str("GOPAY_AUTO_SIGNUP_COUNTRY_CODE", "+62")
    resolved_pin = str(pin or _env_str("GOPAY_AUTO_SIGNUP_DEFAULT_PIN", "558023")).strip()
    effective_proxy = str(proxy_url or _env_str("GOPAY_AUTO_SIGNUP_PROXY_URL")).strip() or None

    if not re.fullmatch(r"\d{6}", resolved_pin):
        raise GoPayAutoSignupError("GoPay 自动注册 PIN 必须是 6 位数字")

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
        activation: SmsActivation | SmsCloudActivation = SmsCloudActivation(
            activation_id=activation_id,
            phone=phone_raw,
            country_id=sms_country_value,
            base_url=smscloud_base_url,
            token=smscloud_auth,
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
        )
        if not activation_id:
            raise GoPayAutoSignupError(f"hero-sms 取号失败: {error}")
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

    cancel_scheduled = False
    try:
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
