"""Oasis CDK-backed SMS provider for OAuth phone verification."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

OASIS_DEFAULT_BASE_URL = "https://sms.oapi.vip"
OASIS_DEFAULT_ACCOUNT_MAP_FILE = "oasis-cdk-accounts.jsonl"

_CDK_RE = re.compile(r"SMS-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}", re.IGNORECASE)
_CODE_RE = re.compile(r"(?<!\d)(\d{6,8})(?!\d)")
_POOL_LOCK = threading.Lock()
_REQUEST_LOCK = threading.Lock()
_USED_CDKS: set[str] = set()
_RESERVED_CDKS: set[str] = set()
_OASIS_NEXT_REQUEST_AT = 0.0


class OasisRateLimitError(RuntimeError):
    """Raised when Oasis keeps returning HTTP 429 after retries."""


def normalize_oasis_cdks(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if isinstance(value, (list, tuple)):
        raw = "\n".join(str(item or "") for item in value)
    else:
        raw = str(value or "")
    matches = [match.group(0).upper() for match in _CDK_RE.finditer(raw)]
    if not matches:
        matches = [
            token.strip().upper()
            for token in re.split(r"[\s,;|]+", raw)
            if token.strip().upper().startswith("SMS-")
        ]
    seen: set[str] = set()
    result: list[str] = []
    for cdk in matches:
        if cdk in seen:
            continue
        seen.add(cdk)
        result.append(cdk)
    return result


def _read_cdk_file(path: str | None) -> str:
    file_path = str(path or "").strip()
    if not file_path:
        return ""
    try:
        return Path(file_path).expanduser().read_text(encoding="utf-8")
    except Exception:
        logger.debug("[Oasis] 读取 CDK 文件失败: %s", file_path, exc_info=True)
        return ""


def oasis_cdks_from_env(env: dict[str, str] | None = None) -> list[str]:
    source = env if env is not None else os.environ
    inline = str(source.get("OAUTH_OASIS_SMS_CDKS") or "").strip()
    cdk_file = str(source.get("OAUTH_OASIS_SMS_CDK_FILE") or "").strip()
    return normalize_oasis_cdks(f"{inline}\n{_read_cdk_file(cdk_file)}")


def oasis_cdks_from_sources(
    cdks: str | list[str] | tuple[str, ...] | None = None,
    *,
    env: dict[str, str] | None = None,
) -> list[str]:
    source = env if env is not None else os.environ
    configured = "\n".join(oasis_cdks_from_env(source))
    inline = "\n".join(normalize_oasis_cdks(cdks))
    return normalize_oasis_cdks(f"{inline}\n{configured}")


def oasis_cdk_count(env: dict[str, str] | None = None) -> int:
    return len(oasis_cdks_from_env(env))


def oasis_configured(env: dict[str, str] | None = None) -> bool:
    return oasis_cdk_count(env) > 0


def _api_url(base_url: str) -> str:
    return f"{str(base_url or OASIS_DEFAULT_BASE_URL).rstrip('/')}/api.php"


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    try:
        return max(minimum, int(str(os.environ.get(name) or default).strip()))
    except Exception:
        return max(minimum, default)


def _throttle_oasis_request() -> None:
    global _OASIS_NEXT_REQUEST_AT
    interval = _env_int("OAUTH_OASIS_SMS_REQUEST_INTERVAL_MS", 1500, minimum=0) / 1000
    if interval <= 0:
        return
    with _REQUEST_LOCK:
        now = time.time()
        delay = _OASIS_NEXT_REQUEST_AT - now
        if delay > 0:
            time.sleep(delay)
            now = time.time()
        _OASIS_NEXT_REQUEST_AT = max(now, _OASIS_NEXT_REQUEST_AT) + interval


def _retry_after_seconds(response: Any, fallback: float) -> float:
    headers = getattr(response, "headers", {}) or {}
    raw = str(headers.get("Retry-After") or "").strip()
    if raw:
        try:
            return max(0.5, float(raw))
        except Exception:
            return fallback
    return fallback


def _response_json_or_empty(response: Any) -> dict[str, Any]:
    try:
        parsed = response.json()
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _post_oasis(action: str, payload: dict[str, Any], *, base_url: str) -> dict[str, Any]:
    body = {"code": str(payload.get("code") or payload.get("cdk") or "").strip()}
    attempts = _env_int("OAUTH_OASIS_SMS_429_RETRIES", 4, minimum=1)
    backoff_ms = _env_int("OAUTH_OASIS_SMS_429_BACKOFF_MS", 5000, minimum=500)
    last_error = ""
    for attempt in range(1, attempts + 1):
        _throttle_oasis_request()
        response = requests.post(f"{_api_url(base_url)}?action={action}", json=body, timeout=30)
        if response.status_code == 429:
            parsed = _response_json_or_empty(response)
            last_error = _response_error(parsed) or str(getattr(response, "text", "") or "")[:200] or "Too Many Requests"
            if attempt < attempts:
                fallback = min(30.0, (backoff_ms / 1000) * attempt)
                delay = _retry_after_seconds(response, fallback)
                logger.warning(
                    "[Oasis] 接口限流 429，%.1fs 后重试: action=%s attempt=%s/%s",
                    delay,
                    action,
                    attempt,
                    attempts,
                )
                time.sleep(delay)
                continue
            raise OasisRateLimitError(f"Oasis HTTP 429 Too Many Requests: {last_error}")
        try:
            parsed = response.json()
        except Exception as exc:
            if response.status_code >= 400:
                raise RuntimeError(f"Oasis HTTP {response.status_code}: {response.text[:200]}") from exc
            raise RuntimeError(f"Oasis 返回非 JSON 响应: {response.text[:200]}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"Oasis 返回格式无效: {parsed!r}")
        parsed.setdefault("_http_status", response.status_code)
        return parsed
    raise OasisRateLimitError(f"Oasis HTTP 429 Too Many Requests: {last_error or 'Too Many Requests'}")



def _find_value(data: Any, keys: set[str]) -> str:
    if isinstance(data, dict):
        for key, value in data.items():
            if str(key).lower() in keys and value is not None:
                text = str(value).strip()
                if text:
                    return text
        for value in data.values():
            found = _find_value(value, keys)
            if found:
                return found
    if isinstance(data, list):
        for item in data:
            found = _find_value(item, keys)
            if found:
                return found
    return ""


def _response_error(data: dict[str, Any]) -> str:
    for key in ("error", "message", "msg", "detail"):
        value = str(data.get(key) or "").strip()
        if value:
            return value
    return ""


def _successful_oasis_cdks_from_map() -> set[str]:
    path = _account_map_path()
    if not path.exists():
        return set()
    used: set[str] = set()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                item = json.loads(text)
            except Exception:
                continue
            if not isinstance(item, dict):
                continue
            if str(item.get("provider") or "").lower() != "oasis":
                continue
            cdk = str(item.get("cdk") or "").strip().upper()
            if cdk and str(item.get("status") or "").strip().lower() == "success":
                used.add(cdk)
    except Exception:
        logger.debug("[Oasis] 读取已成功 CDK 映射失败: %s", path, exc_info=True)
    return used


def _extract_oasis_sms_code(result: dict[str, Any]) -> str:
    explicit = str(_find_value(result, {"code", "sms_code", "verification_code", "otp"}) or "").strip()
    if re.fullmatch(r"\d{6,8}", explicit):
        return explicit
    sms_text = str(_find_value(result, {"sms", "sms_text", "text", "content", "message", "msg"}) or "")
    match = _CODE_RE.search(sms_text)
    return match.group(1) if match else ""


class OasisActivation:
    def __init__(self, *, cdk: str, phone: str, base_url: str):
        self.cdk = str(cdk or "").strip().upper()
        self.phone = str(phone or "").strip()
        self.base_url = str(base_url or OASIS_DEFAULT_BASE_URL).strip()
        self.used_codes: set[str] = set()

    def wait_code(
        self,
        *,
        timeout_sec: int = 120,
        label: str = "",
        max_resends: int = 0,
    ) -> str:
        deadline = time.time() + max(1, int(timeout_sec or 120))
        try:
            max_attempts = max(1, int(os.environ.get("OAUTH_OASIS_SMS_POLL_ATTEMPTS", "24") or "24"))
        except Exception:
            max_attempts = 24
        try:
            interval = max(0.5, float(os.environ.get("OAUTH_OASIS_SMS_POLL_INTERVAL_MS", "5000") or "5000") / 1000)
        except Exception:
            interval = 5.0
        last_error = ""
        attempts = 0
        while time.time() < deadline and attempts < max_attempts:
            attempts += 1
            try:
                result = _post_oasis("get_sms", {"code": self.cdk}, base_url=self.base_url)
                code = _extract_oasis_sms_code(result)
                if code and code not in self.used_codes:
                    logger.info("[Oasis] 已收到验证码: cdk=%s phone=%s label=%s", self.cdk, self.phone, label)
                    self.used_codes.add(code)
                    return code
                last_error = _response_error(result)
            except Exception as exc:
                last_error = str(exc)
                logger.debug("[Oasis] 查询验证码失败: cdk=%s error=%s", self.cdk, exc, exc_info=True)
            time.sleep(interval)
        raise TimeoutError(f"Oasis {int(timeout_sec or 120)}s 内未收到验证码: {last_error}".strip())

    def resend(self) -> None:
        logger.info("[Oasis] 当前供应商不支持重发验证码: cdk=%s", self.cdk)

    def finish(self) -> None:
        return None

    def cancel(self) -> None:
        return None


def _item_from_activation(cdk: str, phone: str, *, base_url: str, email: str = "") -> dict[str, Any]:
    activation = OasisActivation(cdk=cdk, phone=phone, base_url=base_url)
    return {
        "id": f"oasis:{cdk}",
        "record_id": f"oasis:{cdk}",
        "source": "oasis",
        "provider": "oasis",
        "activation": activation,
        "activation_id": cdk,
        "cdk": cdk,
        "phone": phone,
        "phone_number": phone,
        "email": email,
        "created_at": time.time(),
    }


def acquire_oasis_phone(
    email: str = "",
    *,
    reservation_owner: str | None = None,
    base_url: str | None = None,
    cdks: str | list[str] | tuple[str, ...] | None = None,
) -> tuple[dict[str, Any] | None, str]:
    configured_base_url = str(base_url or os.environ.get("OAUTH_OASIS_SMS_BASE_URL") or OASIS_DEFAULT_BASE_URL).strip()
    cdk_pool = oasis_cdks_from_sources(cdks)
    if not cdk_pool:
        return None, "缺少 OAUTH_OASIS_SMS_CDKS 或 OAUTH_OASIS_SMS_CDK_FILE 配置"
    persisted_success = _successful_oasis_cdks_from_map()
    with _POOL_LOCK:
        unconsumed = [
            cdk
            for cdk in cdk_pool
            if cdk not in _USED_CDKS and cdk not in persisted_success
        ]
        candidates = [
            cdk
            for cdk in unconsumed
            if cdk not in _RESERVED_CDKS
        ]
        if not candidates:
            if unconsumed:
                return None, "Oasis CDK 池中的可用 CDK 正由其他 worker 使用"
            return None, "Oasis CDK 池没有未使用的 CDK（仅注册成功的 CDK 会被视为已使用）"
        errors: list[str] = []
        for cdk in candidates:
            try:
                result = _post_oasis("check_cdk", {"code": cdk}, base_url=configured_base_url)
                if result.get("ok") is False or result.get("success") is False:
                    error = _response_error(result) or "兑换失败"
                    errors.append(f"{cdk}: {error}")
                    continue
                phone = _find_value(result, {"phone", "phone_number", "number", "mobile", "msisdn"})
                if not phone:
                    error = _response_error(result) or "兑换成功但未返回手机号"
                    errors.append(f"{cdk}: {error}")
                    continue
                _RESERVED_CDKS.add(cdk)
                logger.info(
                    "[Oasis] CDK 已兑换手机号: email=%s owner=%s cdk=%s phone=%s",
                    email,
                    reservation_owner or "",
                    cdk,
                    phone,
                )
                return _item_from_activation(cdk, phone, base_url=configured_base_url, email=email), ""
            except OasisRateLimitError as exc:
                return None, str(exc)
            except Exception as exc:
                errors.append(f"{cdk}: {exc}")
        return None, "; ".join(errors) or "Oasis 未返回可用号码"


def _account_map_path() -> Path:
    raw = str(os.environ.get("OAUTH_OASIS_SMS_ACCOUNT_MAP_FILE") or OASIS_DEFAULT_ACCOUNT_MAP_FILE).strip()
    return Path(raw).expanduser()


def record_oasis_account_mapping(
    phone_item: dict[str, Any],
    *,
    email: str = "",
    password: str = "",
    status: str = "success",
    reason: str = "",
) -> None:
    cdk = str(phone_item.get("cdk") or phone_item.get("activation_id") or "").strip().upper()
    if not cdk:
        return
    status_text = str(status or "").strip()
    reason_text = str(reason or "").strip()
    is_success = status_text.lower() == "success"
    with _POOL_LOCK:
        _RESERVED_CDKS.discard(cdk)
        if is_success:
            _USED_CDKS.add(cdk)
        else:
            _USED_CDKS.discard(cdk)
    record = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "provider": "oasis",
        "status": status_text,
        "reason": reason_text,
        "cdk": cdk,
        "phone": str(phone_item.get("phone_number") or phone_item.get("phone") or "").strip(),
        "email": str(email or phone_item.get("email") or "").strip(),
        "password": str(password or "").strip(),
    }
    path = _account_map_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        logger.info("[Oasis] 已保存 CDK 和账号映射: cdk=%s email=%s file=%s", cdk, record["email"], path)
    except Exception:
        logger.warning("[Oasis] 保存 CDK 和账号映射失败: cdk=%s file=%s", cdk, path, exc_info=True)
