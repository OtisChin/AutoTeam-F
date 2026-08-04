"""TuJie CDK-backed SMS provider for OAuth phone verification."""

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

TUJIE_DEFAULT_BASE_URL = "https://tujie.xyz/api"
TUJIE_DEFAULT_ACCOUNT_MAP_FILE = "tujie-cdk-accounts.jsonl"

_CDK_RE = re.compile(r"SMS-[A-Z0-9][A-Z0-9-]{6,40}", re.IGNORECASE)
_CODE_RE = re.compile(r"(?<!\d)(\d{6,8})(?!\d)")
_PHONE_LABEL_RE = re.compile(
    r"(?:手机号|手机号码|号码|取号|phone|number|mobile|msisdn)\s*[:：]?\s*(\+?\d[\d\s().-]{5,22}\d)",
    re.IGNORECASE,
)
_PHONE_RE = re.compile(r"(?<![A-Z0-9])(\+?\d[\d\s().-]{6,22}\d)(?![A-Z0-9])", re.IGNORECASE)
_POOL_LOCK = threading.Lock()
_REQUEST_LOCK = threading.Lock()
_USED_CDKS: set[str] = set()
_RESERVED_CDKS: set[str] = set()
_TUJIE_NEXT_REQUEST_AT = 0.0


class TuJieRateLimitError(RuntimeError):
    """Raised when TuJie keeps returning HTTP 429 after retries."""


def normalize_tujie_cdks(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if isinstance(value, (list, tuple)):
        raw = "\n".join(str(item or "") for item in value)
    else:
        raw = str(value or "")
    matches = [match.group(0).strip(" ,;|\t\r\n").upper() for match in _CDK_RE.finditer(raw)]
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
        logger.debug("[TuJie] 读取 CDK 文件失败: %s", file_path, exc_info=True)
        return ""


def tujie_cdks_from_env(env: dict[str, str] | None = None) -> list[str]:
    source = env if env is not None else os.environ
    inline = str(source.get("OAUTH_TUJIE_SMS_CDKS") or "").strip()
    cdk_file = str(source.get("OAUTH_TUJIE_SMS_CDK_FILE") or "").strip()
    return normalize_tujie_cdks(f"{inline}\n{_read_cdk_file(cdk_file)}")


def tujie_cdks_from_sources(
    cdks: str | list[str] | tuple[str, ...] | None = None,
    *,
    env: dict[str, str] | None = None,
) -> list[str]:
    source = env if env is not None else os.environ
    configured = "\n".join(tujie_cdks_from_env(source))
    inline = "\n".join(normalize_tujie_cdks(cdks))
    return normalize_tujie_cdks(f"{inline}\n{configured}")


def tujie_cdk_count(env: dict[str, str] | None = None) -> int:
    return len(tujie_cdks_from_env(env))


def tujie_configured(env: dict[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    base_url = str(source.get("OAUTH_TUJIE_SMS_BASE_URL") or TUJIE_DEFAULT_BASE_URL).strip()
    return tujie_cdk_count(source) > 0 and bool(base_url)


def _api_url(base_url: str) -> str:
    return f"{str(base_url or '').strip().rstrip('/')}/api.php"


def _tujie_mode() -> str:
    mode = str(os.environ.get("OAUTH_TUJIE_SMS_MODE") or "api").strip().lower().replace("-", "_")
    if mode in {"page", "browser", "web"}:
        return "page"
    if mode in {"legacy_api", "old_api", "api_php"}:
        return "legacy_api"
    return "api"


def _tujie_http_headers() -> dict[str, str]:
    device_id = str(os.environ.get("OAUTH_TUJIE_SMS_DEVICE_ID") or "").strip()
    if not device_id:
        device_id = "autotoken-tujie-" + re.sub(r"\D+", "", str(int(time.time())))[:10]
    return {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "https://tujie.xyz",
        "Referer": "https://tujie.xyz/my/cdk",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "X-Device-Id": device_id,
    }


def _tujie_endpoint(base_url: str, action: str) -> str:
    root = str(base_url or TUJIE_DEFAULT_BASE_URL).strip().rstrip("/")
    if _tujie_mode() == "legacy_api":
        return f"{root}/api.php?action={action}" if not root.endswith("api.php") else f"{root}?action={action}"
    if root.endswith("/api"):
        api_root = root
    else:
        api_root = f"{root}/api"
    path = {
        "check_cdk": "/user/cdk/check",
        "assign": "/user/cdk/assign",
        "get_sms": "/user/cdk/code",
        "cancel": "/user/cdk/cancel",
        "change": "/user/cdk/change",
    }.get(action, f"/user/cdk/{action}")
    return f"{api_root}{path}"


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    try:
        return max(minimum, int(str(os.environ.get(name) or default).strip()))
    except Exception:
        return max(minimum, default)


def _throttle_tujie_request() -> None:
    global _TUJIE_NEXT_REQUEST_AT
    interval = _env_int("OAUTH_TUJIE_SMS_REQUEST_INTERVAL_MS", 1500, minimum=0) / 1000
    if interval <= 0:
        return
    with _REQUEST_LOCK:
        now = time.time()
        delay = _TUJIE_NEXT_REQUEST_AT - now
        if delay > 0:
            time.sleep(delay)
            now = time.time()
        _TUJIE_NEXT_REQUEST_AT = max(now, _TUJIE_NEXT_REQUEST_AT) + interval


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


def _response_error(data: dict[str, Any]) -> str:
    for key in ("error", "message", "msg", "detail", "_message"):
        value = str(data.get(key) or "").strip()
        if value:
            return value
    return ""


def _post_tujie(action: str, payload: dict[str, Any], *, base_url: str) -> dict[str, Any]:
    configured_base_url = str(base_url or os.environ.get("OAUTH_TUJIE_SMS_BASE_URL") or TUJIE_DEFAULT_BASE_URL).strip()
    if not configured_base_url:
        raise RuntimeError("缺少 OAUTH_TUJIE_SMS_BASE_URL 配置")
    cdk = str(payload.get("cdk") or payload.get("code") or "").strip()
    if _tujie_mode() == "legacy_api":
        body = {"code": cdk}
    else:
        body = {
            "cdk_type": str(payload.get("cdk_type") or "SMS").strip().upper() or "SMS",
            "cdk": cdk,
        }
        session_id = str(payload.get("session_id") or payload.get("sessionId") or "").strip()
        if session_id:
            body["session_id"] = session_id
    attempts = _env_int("OAUTH_TUJIE_SMS_429_RETRIES", 4, minimum=1)
    backoff_ms = _env_int("OAUTH_TUJIE_SMS_429_BACKOFF_MS", 5000, minimum=500)
    last_error = ""
    for attempt in range(1, attempts + 1):
        _throttle_tujie_request()
        response = requests.post(_tujie_endpoint(configured_base_url, action), json=body, headers=_tujie_http_headers(), timeout=30)
        if response.status_code == 429:
            parsed = _response_json_or_empty(response)
            last_error = _response_error(parsed) or str(getattr(response, "text", "") or "")[:200] or "Too Many Requests"
            if attempt < attempts:
                fallback = min(30.0, (backoff_ms / 1000) * attempt)
                delay = _retry_after_seconds(response, fallback)
                logger.warning(
                    "[TuJie] 接口限流 429，%.1fs 后重试: action=%s attempt=%s/%s",
                    delay,
                    action,
                    attempt,
                    attempts,
                )
                time.sleep(delay)
                continue
            raise TuJieRateLimitError(f"TuJie HTTP 429 Too Many Requests: {last_error}")
        try:
            parsed = response.json()
        except Exception as exc:
            if response.status_code >= 400:
                raise RuntimeError(f"TuJie HTTP {response.status_code}: {response.text[:200]}") from exc
            raise RuntimeError(f"TuJie 返回非 JSON 响应: {response.text[:200]}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"TuJie 返回格式无效: {parsed!r}")
        if _tujie_mode() != "legacy_api" and "code" in parsed and "data" in parsed:
            api_code = parsed.get("code")
            data = parsed.get("data") if isinstance(parsed.get("data"), dict) else {}
            result = dict(data)
            result["_api_code"] = api_code
            result["_message"] = str(parsed.get("message") or "").strip()
            result["_raw_response"] = parsed
            result["_http_status"] = response.status_code
            if api_code not in (0, "0"):
                result.setdefault("ok", False)
                result.setdefault("success", False)
                result.setdefault("message", str(parsed.get("message") or f"TuJie API code={api_code}"))
            return result
        parsed.setdefault("_http_status", response.status_code)
        return parsed
    raise TuJieRateLimitError(f"TuJie HTTP 429 Too Many Requests: {last_error or 'Too Many Requests'}")


def _normalize_phone_text(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    has_plus = text.lstrip().startswith("+")
    digits = re.sub(r"\D+", "", text)
    if not (8 <= len(digits) <= 15):
        return ""
    return f"+{digits}" if has_plus else digits


def _extract_tujie_phone(text: str, *, cdk: str = "") -> str:
    cdk_digits = set(re.findall(r"\d{3,}", str(cdk or "")))
    for pattern in (_PHONE_LABEL_RE, _PHONE_RE):
        for match in pattern.finditer(str(text or "")):
            phone = _normalize_phone_text(match.group(1))
            if not phone:
                continue
            digits = re.sub(r"\D+", "", phone)
            if digits in cdk_digits:
                continue
            # 避免把验证码当手机号。
            if 6 <= len(digits) <= 8 and re.search(r"(验证码|code|otp)", str(text or ""), re.IGNORECASE):
                continue
            return phone
    return ""


def _resolve_tujie_page_url(cdk: str, base_url: str) -> tuple[str, bool]:
    raw = str(base_url or os.environ.get("OAUTH_TUJIE_SMS_BASE_URL") or "").strip()
    if not raw:
        raise RuntimeError("缺少 OAUTH_TUJIE_SMS_BASE_URL 配置")
    encoded = requests.utils.quote(str(cdk or "").strip(), safe="")
    for token in ("{cdk}", "{code}", "{CDK}", "{CODE}"):
        if token in raw:
            return raw.replace(token, encoded), True
    if str(cdk or "").strip() and str(cdk or "").strip() in raw:
        return raw, True
    return raw, False


def _submit_tujie_cdk_if_needed(page: Any, cdk: str, *, direct_url: bool) -> None:
    if direct_url:
        return
    cdk = str(cdk or "").strip()
    if not cdk:
        return
    try:
        handles = page.locator("input, textarea").element_handles()
    except Exception:
        handles = []
    filled = False
    for handle in handles:
        try:
            if not handle.is_visible():
                continue
            attrs = " ".join(
                str(handle.get_attribute(name) or "")
                for name in ("placeholder", "name", "id", "aria-label", "type", "value")
            ).lower()
            if filled:
                break
            if not attrs or any(key in attrs for key in ("cdk", "code", "card", "key", "卡密", "兑换", "取码")):
                handle.fill(cdk, timeout=2000)
                filled = True
        except Exception:
            continue
    if not filled and handles:
        try:
            handles[0].fill(cdk, timeout=2000)
            filled = True
        except Exception:
            filled = False
    if not filled:
        return
    button_texts = ("查询", "查看", "提交", "确定", "兑换", "取码", "开始", "获取", "search", "check", "submit", "get")
    for text in button_texts:
        try:
            locator = page.get_by_role("button", name=re.compile(text, re.IGNORECASE)).first
            if locator.count():
                locator.click(timeout=3000)
                page.wait_for_timeout(1000)
                return
        except Exception:
            continue
    try:
        buttons = page.locator("button, input[type=button], input[type=submit]").element_handles()
    except Exception:
        buttons = []
    for handle in buttons:
        try:
            label = " ".join(
                str(part or "")
                for part in (
                    handle.inner_text(),
                    handle.get_attribute("value"),
                    handle.get_attribute("aria-label"),
                    handle.get_attribute("title"),
                )
            ).lower()
            if not label or any(text in label for text in button_texts):
                handle.click(timeout=3000)
                page.wait_for_timeout(1000)
                return
        except Exception:
            continue
    try:
        page.keyboard.press("Enter")
        page.wait_for_timeout(1000)
    except Exception:
        return


def _page_body_text(page: Any) -> str:
    parts: list[str] = []
    try:
        parts.append(str(page.inner_text("body", timeout=5000) or ""))
    except Exception:
        pass
    try:
        value_text = page.evaluate(
            """() => Array.from(document.querySelectorAll('input, textarea, [contenteditable="true"]'))
                .map(el => [el.value, el.textContent, el.placeholder, el.getAttribute('aria-label')].filter(Boolean).join(' '))
                .join('\\n')"""
        )
        parts.append(str(value_text or ""))
    except Exception:
        pass
    return "\n".join(part for part in parts if part)


def _open_tujie_page_runtime(cdk: str, *, base_url: str) -> tuple[dict[str, Any], dict[str, Any]]:
    url, direct_url = _resolve_tujie_page_url(cdk, base_url)
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError("TuJie 页面取码需要安装 Playwright") from exc

    timeout_ms = _env_int("OAUTH_TUJIE_SMS_PAGE_TIMEOUT_MS", 30000, minimum=5000)
    headless_raw = str(os.environ.get("OAUTH_TUJIE_SMS_HEADLESS") or "1").strip().lower()
    headless = headless_raw not in {"0", "false", "no", "off", "headed", "有头"}
    playwright = sync_playwright().start()
    browser = None
    context = None
    try:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        try:
            page.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in {"image", "media", "font"}
                else route.continue_(),
            )
        except Exception:
            pass
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        _submit_tujie_cdk_if_needed(page, cdk, direct_url=direct_url)
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        text = _page_body_text(page)
        state = {
            "ok": True,
            "url": url,
            "phone": _extract_tujie_phone(text, cdk=cdk),
            "sms": text,
            "code": _extract_tujie_sms_code({"sms": text}),
        }
        runtime = {"playwright": playwright, "browser": browser, "context": context, "page": page, "direct_url": direct_url}
        return state, runtime
    except Exception:
        for obj in (context, browser, playwright):
            try:
                obj.close() if obj is not playwright else obj.stop()
            except Exception:
                pass
        raise


def _fetch_tujie_page_state(cdk: str, *, base_url: str, runtime: dict[str, Any] | None = None) -> dict[str, Any]:
    if runtime and runtime.get("page"):
        page = runtime["page"]
        try:
            page.reload(wait_until="domcontentloaded", timeout=_env_int("OAUTH_TUJIE_SMS_PAGE_TIMEOUT_MS", 30000, minimum=5000))
            _submit_tujie_cdk_if_needed(page, cdk, direct_url=bool(runtime.get("direct_url")))
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            text = _page_body_text(page)
            return {
                "ok": True,
                "url": page.url,
                "phone": _extract_tujie_phone(text, cdk=cdk),
                "sms": text,
                "code": _extract_tujie_sms_code({"sms": text}),
            }
        except Exception:
            logger.debug("[TuJie] 复用取码页面失败，改为重新打开: cdk=%s", cdk, exc_info=True)
    state, new_runtime = _open_tujie_page_runtime(cdk, base_url=base_url)
    if runtime is not None:
        runtime.update(new_runtime)
    else:
        _close_tujie_runtime(new_runtime)
    return state


def _close_tujie_runtime(runtime: dict[str, Any] | None) -> None:
    if not runtime:
        return
    for key in ("context", "browser"):
        try:
            obj = runtime.get(key)
            if obj:
                obj.close()
        except Exception:
            pass
    try:
        playwright = runtime.get("playwright")
        if playwright:
            playwright.stop()
    except Exception:
        pass
    runtime.clear()


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


def _successful_tujie_cdks_from_map() -> set[str]:
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
            if str(item.get("provider") or "").lower() != "tujie":
                continue
            cdk = str(item.get("cdk") or "").strip().upper()
            if cdk and str(item.get("status") or "").strip().lower() == "success":
                used.add(cdk)
    except Exception:
        logger.debug("[TuJie] 读取已成功 CDK 映射失败: %s", path, exc_info=True)
    return used


def _extract_tujie_sms_code(result: dict[str, Any]) -> str:
    explicit = str(_find_value(result, {"code", "sms_code", "verification_code", "otp"}) or "").strip()
    if re.fullmatch(r"\d{6,8}", explicit):
        return explicit
    sms_text = str(_find_value(result, {"sms", "sms_text", "text", "content", "message", "msg"}) or "")
    match = _CODE_RE.search(sms_text)
    return match.group(1) if match else ""


class TuJieActivation:
    def __init__(
        self,
        *,
        cdk: str,
        phone: str,
        base_url: str,
        mode: str = "api",
        session_id: str = "",
        page_runtime: dict[str, Any] | None = None,
    ):
        self.cdk = str(cdk or "").strip().upper()
        self.phone = str(phone or "").strip()
        self.base_url = str(base_url or "").strip()
        self.mode = str(mode or "api").strip().lower()
        self.session_id = str(session_id or "").strip()
        self.page_runtime = page_runtime or {}
        self.used_codes: set[str] = set()

    def wait_code(
        self,
        *,
        timeout_sec: int = 120,
        label: str = "",
        max_resends: int = 0,
    ) -> str:
        del max_resends
        deadline = time.time() + max(1, int(timeout_sec or 120))
        attempts_limit = _env_int("OAUTH_TUJIE_SMS_POLL_ATTEMPTS", 24, minimum=1)
        interval = max(0.5, _env_int("OAUTH_TUJIE_SMS_POLL_INTERVAL_MS", 5000, minimum=500) / 1000)
        last_error = ""
        attempts = 0
        while time.time() < deadline and attempts < attempts_limit:
            attempts += 1
            try:
                result = (
                    _post_tujie("get_sms", {"cdk": self.cdk, "session_id": self.session_id}, base_url=self.base_url)
                    if self.mode in {"api", "legacy_api"}
                    else _fetch_tujie_page_state(self.cdk, base_url=self.base_url, runtime=self.page_runtime)
                )
                code = _extract_tujie_sms_code(result)
                if code and code not in self.used_codes:
                    logger.info("[TuJie] 已收到验证码: cdk=%s phone=%s label=%s", self.cdk, self.phone, label)
                    self.used_codes.add(code)
                    return code
                last_error = _response_error(result)
            except Exception as exc:
                last_error = str(exc)
                logger.debug("[TuJie] 查询验证码失败: cdk=%s error=%s", self.cdk, exc, exc_info=True)
            time.sleep(interval)
        raise TimeoutError(f"TuJie {int(timeout_sec or 120)}s 内未收到验证码: {last_error}".strip())

    def resend(self) -> None:
        logger.info("[TuJie] 当前供应商不支持重发验证码: cdk=%s", self.cdk)

    def finish(self) -> None:
        if self.mode == "page":
            _close_tujie_runtime(self.page_runtime)

    def cancel(self) -> None:
        if self.mode == "page":
            _close_tujie_runtime(self.page_runtime)
            return
        if self.mode == "api" and self.session_id:
            try:
                _post_tujie("cancel", {"cdk": self.cdk, "session_id": self.session_id}, base_url=self.base_url)
            except Exception as exc:
                logger.debug("[TuJie] 取消接码会话失败: cdk=%s session_id=%s error=%s", self.cdk, self.session_id, exc)


def _item_from_activation(
    cdk: str,
    phone: str,
    *,
    base_url: str,
    email: str = "",
    mode: str = "api",
    session_id: str = "",
    page_runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    activation = TuJieActivation(
        cdk=cdk,
        phone=phone,
        base_url=base_url,
        mode=mode,
        session_id=session_id,
        page_runtime=page_runtime,
    )
    return {
        "id": f"tujie:{cdk}",
        "record_id": f"tujie:{cdk}",
        "source": "tujie",
        "provider": "tujie",
        "activation": activation,
        "activation_id": cdk,
        "session_id": session_id,
        "cdk": cdk,
        "phone": phone,
        "phone_number": phone,
        "email": email,
        "created_at": time.time(),
    }


def acquire_tujie_phone(
    email: str = "",
    *,
    reservation_owner: str | None = None,
    base_url: str | None = None,
    cdks: str | list[str] | tuple[str, ...] | None = None,
) -> tuple[dict[str, Any] | None, str]:
    configured_base_url = str(base_url or os.environ.get("OAUTH_TUJIE_SMS_BASE_URL") or TUJIE_DEFAULT_BASE_URL).strip()
    if not configured_base_url:
        return None, "缺少 OAUTH_TUJIE_SMS_BASE_URL 配置"
    mode = _tujie_mode()
    cdk_pool = tujie_cdks_from_sources(cdks)
    if not cdk_pool:
        return None, "缺少 OAUTH_TUJIE_SMS_CDKS 或 OAUTH_TUJIE_SMS_CDK_FILE 配置"
    persisted_success = _successful_tujie_cdks_from_map()
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
                return None, "TuJie CDK 池中的可用 CDK 正由其他 worker 使用"
            return None, "TuJie CDK 池没有未使用的 CDK（仅成功的 CDK 会被视为已使用）"
        errors: list[str] = []
        for cdk in candidates:
            page_runtime: dict[str, Any] | None = None
            try:
                if mode in {"api", "legacy_api"}:
                    result = _post_tujie("check_cdk", {"cdk": cdk}, base_url=configured_base_url)
                    if mode == "api":
                        api_status = str(result.get("status") or "").strip().upper()
                        if result.get("available") is False and not _find_value(result, {"phone", "phone_number", "resource_value"}):
                            error = _response_error(result) or str(result.get("_message") or "") or "CDK 不可用"
                            errors.append(f"{cdk}: {error}")
                            continue
                        if api_status in {"USED", "INVALID"} and not _find_value(result, {"phone", "phone_number", "resource_value"}):
                            error = _response_error(result) or str(result.get("_message") or "") or f"CDK 状态 {api_status}"
                            errors.append(f"{cdk}: {error}")
                            continue
                        if not _find_value(result, {"phone", "phone_number", "resource_value"}):
                            result = _post_tujie("assign", {"cdk": cdk}, base_url=configured_base_url)
                else:
                    result, page_runtime = _open_tujie_page_runtime(cdk, base_url=configured_base_url)
                if result.get("ok") is False or result.get("success") is False:
                    error = _response_error(result) or "兑换失败"
                    errors.append(f"{cdk}: {error}")
                    _close_tujie_runtime(page_runtime)
                    continue
                phone = _find_value(result, {"phone", "phone_number", "number", "mobile", "msisdn", "resource_value"})
                if not phone:
                    error = _response_error(result) or str(result.get("_message") or "") or "未返回手机号"
                    errors.append(f"{cdk}: {error}")
                    _close_tujie_runtime(page_runtime)
                    continue
                session_id = _find_value(result, {"session_id", "sessionid"}) or cdk
                _RESERVED_CDKS.add(cdk)
                logger.info(
                    "[TuJie] CDK 已获取手机号: email=%s owner=%s mode=%s cdk=%s phone=%s",
                    email,
                    reservation_owner or "",
                    mode,
                    cdk,
                    phone,
                )
                return _item_from_activation(
                    cdk,
                    phone,
                    base_url=configured_base_url,
                    email=email,
                    mode=mode,
                    session_id=session_id,
                    page_runtime=page_runtime,
                ), ""
            except TuJieRateLimitError as exc:
                _close_tujie_runtime(page_runtime)
                return None, str(exc)
            except Exception as exc:
                _close_tujie_runtime(page_runtime)
                errors.append(f"{cdk}: {exc}")
        return None, "; ".join(errors) or "TuJie 未返回可用号码"


def _account_map_path() -> Path:
    raw = str(os.environ.get("OAUTH_TUJIE_SMS_ACCOUNT_MAP_FILE") or TUJIE_DEFAULT_ACCOUNT_MAP_FILE).strip()
    return Path(raw).expanduser()


def record_tujie_account_mapping(
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
        "provider": "tujie",
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
        logger.info("[TuJie] 已保存 CDK 和账号映射: cdk=%s email=%s file=%s", cdk, record["email"], path)
    except Exception:
        logger.warning("[TuJie] 保存 CDK 和账号映射失败: cdk=%s file=%s", cdk, path, exc_info=True)
    finally:
        activation = phone_item.get("activation")
        try:
            if activation and is_success and hasattr(activation, "finish"):
                activation.finish()
            elif activation and not is_success and hasattr(activation, "cancel"):
                activation.cancel()
        except Exception:
            logger.debug("[TuJie] 结束取码会话失败: cdk=%s", cdk, exc_info=True)
