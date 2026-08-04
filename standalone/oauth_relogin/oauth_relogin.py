"""脱敏独立版 OAuth 补登录核心模块。

这个文件从当前项目的 OAuth 补登录链路复制/抽取出可复用的通用部分：

- PKCE 生成
- OAuth authorize URL 构造
- 回调 URL 解析
- authorization_code -> token 交换
- auth_session/cookie 复用的纯协议 OAuth 跳转
- token bundle 归一化与保存

所有端点、client_id、cookie 名称均可配置；默认值使用 example 域名和占位
client_id，便于复制到其他项目后再按目标环境填写。
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
import os
import re
import secrets
import tempfile
import threading
import time
import urllib.parse
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

DEFAULT_CALLBACK_PORT = 1455
DEFAULT_AUTH_URL = "https://auth.example.com/oauth/authorize"
DEFAULT_TOKEN_URL = "https://auth.example.com/oauth/token"
DEFAULT_CLIENT_ID = "REPLACE_WITH_OAUTH_CLIENT_ID"
DEFAULT_SCOPE = "openid email profile offline_access"
DEFAULT_SESSION_COOKIE_NAME = "__Secure-next-auth.session-token"
HELPER_LANDING_URL = "https://auth.example.com/"


class OAuthError(RuntimeError):
    """Base class for standalone OAuth relogin errors."""


class OAuthLoginRequired(OAuthError):
    """The protocol flow reached a login page instead of a callback URL."""

    def __init__(self, url: str = ""):
        self.url = url or ""
        message = "OAuth 停在登录页，未获取 authorization code"
        if self.url:
            message = f"{message}: {self.url}"
        super().__init__(message)


class OAuthPhoneRequired(OAuthError):
    """The provider requested phone verification."""

    def __init__(self, url: str = ""):
        self.url = url or ""
        message = "OAuth 需要手机号验证"
        if self.url:
            message = f"{message}: {self.url}"
        super().__init__(message)


class OAuthTokenBundleError(OAuthError):
    """Token response is missing the data needed by the caller."""


class PhoneSmsError(RuntimeError):
    """Phone/SMS provider error."""


@dataclasses.dataclass(frozen=True)
class OAuthConfig:
    """Config required for a reusable OAuth relogin flow."""

    client_id: str = DEFAULT_CLIENT_ID
    auth_url: str = DEFAULT_AUTH_URL
    token_url: str = DEFAULT_TOKEN_URL
    redirect_uri: str = f"http://127.0.0.1:{DEFAULT_CALLBACK_PORT}/auth/callback"
    scope: str = DEFAULT_SCOPE
    session_cookie_name: str = DEFAULT_SESSION_COOKIE_NAME
    account_cookie_name: str = "_account"
    device_cookie_name: str = "oai-did"
    auth_domains: tuple[str, ...] = ("auth.example.com", ".auth.example.com")
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
    )

    @classmethod
    def from_env(cls, prefix: str = "OAUTH_RELOGIN_") -> OAuthConfig:
        """Create config from environment variables.

        Supported variables:
        OAUTH_RELOGIN_CLIENT_ID, OAUTH_RELOGIN_AUTH_URL,
        OAUTH_RELOGIN_TOKEN_URL, OAUTH_RELOGIN_REDIRECT_URI,
        OAUTH_RELOGIN_SCOPE, OAUTH_RELOGIN_SESSION_COOKIE_NAME,
        OAUTH_RELOGIN_AUTH_DOMAINS.
        """

        domains = os.getenv(f"{prefix}AUTH_DOMAINS", "")
        auth_domains = tuple(item.strip() for item in domains.split(",") if item.strip()) or cls().auth_domains
        return cls(
            client_id=os.getenv(f"{prefix}CLIENT_ID", DEFAULT_CLIENT_ID).strip() or DEFAULT_CLIENT_ID,
            auth_url=os.getenv(f"{prefix}AUTH_URL", DEFAULT_AUTH_URL).strip() or DEFAULT_AUTH_URL,
            token_url=os.getenv(f"{prefix}TOKEN_URL", DEFAULT_TOKEN_URL).strip() or DEFAULT_TOKEN_URL,
            redirect_uri=os.getenv(f"{prefix}REDIRECT_URI", cls().redirect_uri).strip() or cls().redirect_uri,
            scope=os.getenv(f"{prefix}SCOPE", DEFAULT_SCOPE).strip() or DEFAULT_SCOPE,
            session_cookie_name=(
                os.getenv(f"{prefix}SESSION_COOKIE_NAME", DEFAULT_SESSION_COOKIE_NAME).strip()
                or DEFAULT_SESSION_COOKIE_NAME
            ),
            auth_domains=auth_domains,
        )


def normalize_phone_sms_provider(raw: str | None = None) -> str:
    """Normalize phone/SMS provider names used by this standalone module."""

    value = str(raw or "").strip().lower().replace("-", "_")
    if value in {"hero_sms", "herosms", "hero"}:
        return "hero_sms"
    if value in {"smsbower", "sms_bower"}:
        return "smsbower"
    if value in {"smscloud", "sms_cloud", "sms_cloud_sbs"}:
        return "smscloud"
    if value in {"oasis", "oasis_sms", "oasissms", "oapi"}:
        return "oasis"
    if value in {"tujie", "tujie_sms", "tujie_cdk", "tujiecdk", "tj"}:
        return "tujie"
    return "phone_pool"


def normalize_sms_country(raw: str | None = None) -> str:
    """Normalize common country aliases to provider country IDs."""

    value = str(raw or "").strip().lower()
    if value in {"all", "any", "*", "全部", "所有", "不限", "global"}:
        return "all"
    if value and re.fullmatch(r"\d+", value):
        return value
    if value in {"", "us", "usa", "united_states", "united states", "+1"}:
        return "187"
    if value in {"gb", "uk", "united_kingdom", "united kingdom", "britain", "英国", "+44"}:
        return "44"
    if value in {"br", "bra", "brazil", "brasil", "巴西", "+55"}:
        return "73"
    if value in {"id", "idn", "indonesia", "indonesian", "印度尼西亚", "印尼", "+62"}:
        return "6"
    if value in {"co", "colombia", "colombian", "哥伦比亚", "哥伦比亚共和国", "+57"}:
        return "33"
    return value


@dataclasses.dataclass(frozen=True)
class PhoneSmsConfig:
    """接码配置。默认只内置 JSON 手机号池；HTTP 接码商通过 adapter 接入。"""

    provider: str = "phone_pool"
    country: str = "187"
    service: str = "dr"
    api_key: str = ""
    base_url: str = ""
    max_price: str = ""
    poll_attempts: int = 24
    poll_interval_seconds: float = 5.0

    @classmethod
    def from_env(cls, prefix: str = "OAUTH_RELOGIN_PHONE_SMS_") -> PhoneSmsConfig:
        attempts_raw = os.getenv(f"{prefix}POLL_ATTEMPTS", "24")
        interval_raw = os.getenv(f"{prefix}POLL_INTERVAL_SECONDS", "5")
        try:
            attempts = max(1, int(attempts_raw or "24"))
        except (TypeError, ValueError):
            attempts = 24
        try:
            interval = max(0.1, float(interval_raw or "5"))
        except (TypeError, ValueError):
            interval = 5.0
        return cls(
            provider=normalize_phone_sms_provider(os.getenv(f"{prefix}PROVIDER", "phone_pool")),
            country=normalize_sms_country(os.getenv(f"{prefix}COUNTRY", "187")),
            service=str(os.getenv(f"{prefix}SERVICE", "dr") or "dr").strip(),
            api_key=str(os.getenv(f"{prefix}API_KEY", "") or "").strip(),
            base_url=str(os.getenv(f"{prefix}BASE_URL", "") or "").strip(),
            max_price=str(os.getenv(f"{prefix}MAX_PRICE", "") or "").strip(),
            poll_attempts=attempts,
            poll_interval_seconds=interval,
        )

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "country": self.country,
            "service": self.service,
            "api_key_present": bool(self.api_key),
            "api_key": redact_secret(self.api_key),
            "base_url": self.base_url,
            "max_price": self.max_price,
            "poll_attempts": self.poll_attempts,
            "poll_interval_seconds": self.poll_interval_seconds,
        }


def _env(prefix: str, key: str, default: str = "") -> str:
    return str(os.getenv(f"{prefix}{key}", default) or default).strip()


def _count_tokens(raw: str) -> int:
    tokens = [item.strip() for item in re.split(r"[\s,;]+", str(raw or "")) if item.strip()]
    return len(tokens)


@dataclasses.dataclass(frozen=True)
class SmsProviderConfig:
    """Provider-specific SMS configuration, safe to copy between projects."""

    provider: str
    label: str
    configured: bool = False
    api_key: str = ""
    base_url: str = ""
    country: str = "187"
    service: str = "dr"
    min_price: str = ""
    max_price: str = ""
    price_mode: str = "ceiling"
    cdk_count: int = 0
    cdk_values: tuple[str, ...] = ()
    cdk_file: str = ""
    account_map_file: str = ""
    poll_attempts: int = 24
    poll_interval_seconds: float = 5.0

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "value": self.provider,
            "label": self.label,
            "configured": self.configured,
            "api_key_present": bool(self.api_key),
            "api_key_masked": redact_secret(self.api_key),
            "base_url": self.base_url,
            "country": self.country,
            "service": self.service,
            "min_price": self.min_price,
            "max_price": self.max_price,
            "price_mode": self.price_mode,
            "cdk_count": self.cdk_count,
            "cdk_file": self.cdk_file,
            "account_map_file": self.account_map_file,
            "poll_attempts": self.poll_attempts,
            "poll_interval_seconds": self.poll_interval_seconds,
        }


def _poll_attempts(prefix: str, default: int = 24) -> int:
    try:
        return max(1, int(_env(prefix, "POLL_ATTEMPTS", str(default))))
    except (TypeError, ValueError):
        return default


def _poll_interval(prefix: str, default: float = 5.0) -> float:
    raw = _env(prefix, "POLL_INTERVAL_SECONDS", str(default))
    try:
        return max(0.1, float(raw))
    except (TypeError, ValueError):
        return default


def _read_text_file(path: str) -> str:
    file_path = str(path or "").strip()
    if not file_path:
        return ""
    try:
        return Path(file_path).expanduser().read_text(encoding="utf-8")
    except Exception:
        return ""


def normalize_cdks(raw: str | list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if isinstance(raw, (list, tuple)):
        text = "\n".join(str(item or "") for item in raw)
    else:
        text = str(raw or "")
    tokens = [item.strip().upper() for item in re.split(r"[\s,;|]+", text) if item.strip()]
    seen: set[str] = set()
    result: list[str] = []
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        result.append(token)
    return tuple(result)


def normalize_sms_price_mode(raw: str | None = None) -> str:
    value = str(raw or "").strip().lower().replace("-", "_")
    if value in {"lowest", "min", "minimum", "lowest_price", "min_price", "cheap", "cheapest", "低价", "最低价"}:
        return "lowest"
    return "ceiling"


def load_phone_sms_provider_configs(prefix: str = "OAUTH_RELOGIN_") -> dict[str, SmsProviderConfig]:
    """Load all supported phone/SMS provider configs from environment variables.

    Supported providers mirror the original project's OAuth add-phone options:
    ``phone_pool``, ``hero_sms``, ``smsbower``, ``smscloud``, ``oasis``, ``tujie``.
    """

    hero_prefix = f"{prefix}HERO_SMS_"
    smsbower_prefix = f"{prefix}SMSBOWER_"
    smscloud_prefix = f"{prefix}SMSCLOUD_"
    oasis_prefix = f"{prefix}OASIS_SMS_"
    tujie_prefix = f"{prefix}TUJIE_SMS_"

    hero_key = _env(hero_prefix, "API_KEY")
    smsbower_key = _env(smsbower_prefix, "API_KEY")
    smscloud_key = _env(smscloud_prefix, "API_KEY")
    oasis_file = _env(oasis_prefix, "CDK_FILE")
    oasis_cdks = "\n".join([_env(oasis_prefix, "CDKS"), _read_text_file(oasis_file)])
    tujie_file = _env(tujie_prefix, "CDK_FILE")
    tujie_cdks = "\n".join([_env(tujie_prefix, "CDKS"), _read_text_file(tujie_file)])
    oasis_values = normalize_cdks(oasis_cdks)
    tujie_values = normalize_cdks(tujie_cdks)

    return {
        "phone_pool": SmsProviderConfig(
            provider="phone_pool",
            label="JSON 手机号池",
            configured=True,
        ),
        "hero_sms": SmsProviderConfig(
            provider="hero_sms",
            label="hero-sms",
            configured=bool(hero_key),
            api_key=hero_key,
            base_url=_env(hero_prefix, "BASE_URL", "https://hero-sms.example/stubs/handler_api.php"),
            country=normalize_sms_country(_env(hero_prefix, "COUNTRY", "187")),
            service=_env(hero_prefix, "SERVICE", "dr"),
            min_price=_env(hero_prefix, "MIN_PRICE"),
            max_price=_env(hero_prefix, "MAX_PRICE"),
            price_mode=normalize_sms_price_mode(_env(hero_prefix, "PRICE_MODE", "ceiling")),
            poll_attempts=_poll_attempts(hero_prefix),
            poll_interval_seconds=_poll_interval(hero_prefix),
        ),
        "smsbower": SmsProviderConfig(
            provider="smsbower",
            label="smsbower",
            configured=bool(smsbower_key),
            api_key=smsbower_key,
            base_url=_env(smsbower_prefix, "BASE_URL", "https://smsbower.example/stubs/handler_api.php"),
            country=normalize_sms_country(_env(smsbower_prefix, "COUNTRY", "187")),
            service=_env(smsbower_prefix, "SERVICE", "dr"),
            min_price=_env(smsbower_prefix, "MIN_PRICE"),
            max_price=_env(smsbower_prefix, "MAX_PRICE"),
            price_mode=normalize_sms_price_mode(_env(smsbower_prefix, "PRICE_MODE", "ceiling")),
            poll_attempts=_poll_attempts(smsbower_prefix),
            poll_interval_seconds=_poll_interval(smsbower_prefix),
        ),
        "smscloud": SmsProviderConfig(
            provider="smscloud",
            label="SMSCloud",
            configured=bool(smscloud_key),
            api_key=smscloud_key,
            base_url=_env(smscloud_prefix, "BASE_URL", "https://smscloud.example/api/system"),
            country=normalize_sms_country(_env(smscloud_prefix, "COUNTRY", "187")),
            service=_env(smscloud_prefix, "SERVICE", "dr"),
            min_price=_env(smscloud_prefix, "MIN_PRICE"),
            max_price=_env(smscloud_prefix, "MAX_PRICE"),
            price_mode=normalize_sms_price_mode(_env(smscloud_prefix, "PRICE_MODE", "ceiling")),
            poll_attempts=_poll_attempts(smscloud_prefix),
            poll_interval_seconds=_poll_interval(smscloud_prefix),
        ),
        "oasis": SmsProviderConfig(
            provider="oasis",
            label="Oasis CDK",
            configured=bool(oasis_values),
            base_url=_env(oasis_prefix, "BASE_URL", "https://oasis.example"),
            cdk_count=len(oasis_values),
            cdk_values=oasis_values,
            cdk_file=oasis_file,
            account_map_file=_env(oasis_prefix, "ACCOUNT_MAP_FILE", "data/oauth-oasis-account-map.json"),
            poll_attempts=_poll_attempts(oasis_prefix),
            poll_interval_seconds=_poll_interval(oasis_prefix),
        ),
        "tujie": SmsProviderConfig(
            provider="tujie",
            label="TuJie CDK",
            configured=bool(tujie_values),
            base_url=_env(tujie_prefix, "BASE_URL", "https://tujie.example"),
            cdk_count=len(tujie_values),
            cdk_values=tujie_values,
            cdk_file=tujie_file,
            account_map_file=_env(tujie_prefix, "ACCOUNT_MAP_FILE", "data/oauth-tujie-account-map.json"),
            poll_attempts=_poll_attempts(tujie_prefix),
            poll_interval_seconds=_poll_interval(tujie_prefix),
        ),
    }


def build_phone_sms_config_report(
    configs: dict[str, SmsProviderConfig] | None = None,
    *,
    selected_provider: str | None = None,
) -> dict[str, Any]:
    """Return a UI/API-safe SMS configuration report with secrets masked."""

    configs = configs or load_phone_sms_provider_configs()
    provider = normalize_phone_sms_provider(
        selected_provider or os.getenv("OAUTH_RELOGIN_PHONE_SMS_PROVIDER", "phone_pool")
    )
    selected = configs.get(provider) or configs["phone_pool"]
    return {
        "provider": selected.provider,
        "configured": selected.configured,
        "providers": [configs[key].to_safe_dict() for key in ("phone_pool", "hero_sms", "smsbower", "smscloud", "oasis", "tujie")],
    }


@dataclasses.dataclass
class PhoneItem:
    """A phone number reserved for OAuth add-phone."""

    id: str
    phone_number: str
    sms_url: str = ""
    activation_id: str = ""
    otp: str = ""
    provider: str = "phone_pool"
    raw: dict[str, Any] = dataclasses.field(default_factory=dict)


def normalize_phone_key(phone: str) -> str:
    digits = re.sub(r"\D+", "", str(phone or ""))
    return digits or str(phone or "").strip().lower()


def _normalize_import_phone(phone: str) -> str:
    value = str(phone or "").strip()
    if not value:
        return ""
    if value.startswith("+"):
        return value
    digits = re.sub(r"\D+", "", value)
    if digits and digits == value:
        return f"+{digits}"
    return value


def parse_phone_import_lines(text: str) -> list[dict[str, str]]:
    """Parse phone-pool import text.

    Supported formats:
    ``+12025550111----https://sms.example/inbox`` or
    ``12025550111|https://sms.example/inbox``.
    """

    entries: list[dict[str, str]] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if "|" in line:
            parts = re.split(r"\s*\|\s*", line, maxsplit=1)
        else:
            parts = re.split(r"\s*-{4,}\s*", line, maxsplit=1)
            if len(parts) != 2:
                match = re.match(r"^(.+?)\s+-\s+(https?://.+)$", line, re.I)
                if match:
                    parts = [match.group(1), match.group(2)]
        if len(parts) != 2:
            raise ValueError(f"导入格式无效: {line[:80]}")
        phone, sms_url = _normalize_import_phone(parts[0].strip()), parts[1].strip()
        if not phone or not sms_url:
            raise ValueError(f"导入格式无效: {line[:80]}")
        entries.append({"phone_number": phone, "sms_url": sms_url})
    return entries


class JsonPhonePoolProvider:
    """Standalone JSON-backed phone pool provider.

    The provider can manage reusable phone numbers and persist binding counts.
    OTP retrieval can be supplied by setting ``PhoneItem.otp`` in tests/tools or
    by passing ``phone_code_provider`` to ``run_oauth_relogin_flow``.
    """

    max_bindings_per_phone = 3

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"items": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PhoneSmsError(f"手机号池 JSON 无效: {self.path}") from exc
        if isinstance(data, list):
            data = {"items": data}
        if not isinstance(data, dict):
            data = {"items": []}
        items = data.get("items")
        if not isinstance(items, list):
            data["items"] = []
        return data

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def import_phones(self, text: str) -> dict[str, Any]:
        parsed = parse_phone_import_lines(text)
        data = self._load()
        items = data["items"]
        known = {normalize_phone_key(item.get("phone_number") or item.get("phone") or "") for item in items}
        added = []
        for entry in parsed:
            key = normalize_phone_key(entry["phone_number"])
            if not key or key in known:
                continue
            item = {
                "id": secrets.token_hex(8),
                "phone_number": entry["phone_number"],
                "phone_key": key,
                "sms_url": entry["sms_url"],
                "status": "available",
                "bound_count": 0,
                "bound_emails": [],
                "created_at": time.time(),
                "updated_at": time.time(),
            }
            known.add(key)
            items.insert(0, item)
            added.append(item)
        self._save(data)
        return {"added_count": len(added), "total": len(items), "added": added}

    def acquire_phone(self, email: str = "") -> PhoneItem:
        data = self._load()
        now = time.time()
        for item in data["items"]:
            status = str(item.get("status") or "available").lower()
            count = int(item.get("bound_count") or len(item.get("bound_emails") or []))
            if status == "available" and count < self.max_bindings_per_phone:
                item["reserved_by"] = str(email or "").strip().lower()
                item["reserved_at"] = now
                item["updated_at"] = now
                self._save(data)
                return PhoneItem(
                    id=str(item.get("id") or ""),
                    phone_number=str(item.get("phone_number") or ""),
                    sms_url=str(item.get("sms_url") or ""),
                    provider="phone_pool",
                    raw=dict(item),
                )
        raise PhoneSmsError("手机号池没有可用号码")

    def wait_for_code(self, phone_item: PhoneItem) -> str:
        code = str(getattr(phone_item, "otp", "") or "").strip()
        if not code:
            raise PhoneSmsError("未提供手机号验证码；请传入 phone_code_provider 或接入接码商 adapter")
        return code

    def mark_bound(self, phone_item: PhoneItem, email: str) -> None:
        normalized_email = str(email or "").strip().lower()
        data = self._load()
        now = time.time()
        for item in data["items"]:
            if str(item.get("id") or "") != str(phone_item.id):
                continue
            bound = [str(value).strip().lower() for value in item.get("bound_emails") or [] if str(value).strip()]
            if normalized_email and normalized_email not in bound:
                bound.append(normalized_email)
            item["bound_emails"] = bound[: self.max_bindings_per_phone]
            item["bound_count"] = len(item["bound_emails"])
            item["status"] = "full" if item["bound_count"] >= self.max_bindings_per_phone else "available"
            item["last_used_at"] = now
            item["updated_at"] = now
            item["reserved_by"] = ""
            item["reserved_at"] = None
            self._save(data)
            return
        raise PhoneSmsError("手机号不存在，无法标记绑定")

    def release(self, phone_item: PhoneItem, *, reason: str = "") -> None:
        data = self._load()
        now = time.time()
        for item in data["items"]:
            if str(item.get("id") or "") != str(phone_item.id):
                continue
            item["reserved_by"] = ""
            item["reserved_at"] = None
            item["last_release_reason"] = str(reason or "")
            item["updated_at"] = now
            self._save(data)
            return


def _response_payload(response: Any) -> Any:
    try:
        return response.json()
    except Exception:
        return str(getattr(response, "text", "") or "")


def _extract_code_from_text(text: str) -> str:
    match = re.search(r"(?<!\d)(\d{4,8})(?!\d)", str(text or ""))
    return match.group(1) if match else ""


def _find_nested_value(data: Any, names: set[str]) -> str:
    if isinstance(data, dict):
        for key, value in data.items():
            if str(key).lower() in names and value is not None:
                text = str(value).strip()
                if text:
                    return text
        for value in data.values():
            found = _find_nested_value(value, names)
            if found:
                return found
    if isinstance(data, list):
        for item in data:
            found = _find_nested_value(item, names)
            if found:
                return found
    return ""


def _response_error_text(data: Any) -> str:
    if isinstance(data, dict):
        return _find_nested_value(data, {"error", "message", "msg", "detail", "error_description"})
    return str(data or "").strip()


class HandlerApiSmsProvider:
    """hero-sms / smsbower style ``handler_api.php`` adapter."""

    def __init__(self, config: SmsProviderConfig, *, http_get: Callable[..., Any] | None = None):
        self.config = config
        self.http_get = http_get

    def _get(self, params: dict[str, Any]) -> Any:
        if self.http_get is None:
            import requests

            self.http_get = requests.get
        response = self.http_get(self.config.base_url, params=params, headers={}, timeout=30)
        status = int(getattr(response, "status_code", 200) or 200)
        if status >= 400:
            raise PhoneSmsError(f"{self.config.provider} HTTP {status}: {str(getattr(response, 'text', '') or '')[:200]}")
        return _response_payload(response)

    def _params(self, action: str, **extra: Any) -> dict[str, Any]:
        params = {
            "api_key": self.config.api_key,
            "action": action,
            **extra,
        }
        return {key: value for key, value in params.items() if value not in (None, "")}

    def acquire_phone(self, email: str = "") -> PhoneItem:
        if not self.config.api_key:
            raise PhoneSmsError(f"{self.config.provider} 缺少 API key")
        payload = self._get(
            self._params(
                "getNumber",
                service=self.config.service or "dr",
                country=self.config.country,
                maxPrice=self.config.max_price,
            )
        )
        activation_id = ""
        phone = ""
        if isinstance(payload, str):
            # Common format: ACCESS_NUMBER:<activation_id>:<phone>
            parts = payload.strip().split(":")
            if len(parts) >= 3 and parts[0] in {"ACCESS_NUMBER", "ACCESS_NUMBER_V2"}:
                activation_id, phone = parts[1], parts[2]
            elif payload.startswith("NO_NUMBERS"):
                raise PhoneSmsError(f"{self.config.provider} 没有可用号码")
            elif payload.startswith("BAD_") or payload.startswith("ERROR"):
                raise PhoneSmsError(payload)
        elif isinstance(payload, dict):
            data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
            activation_id = _find_nested_value(data, {"activation_id", "activationid", "id"})
            phone = _find_nested_value(data, {"phone", "phone_number", "number", "mobile"})
        if not activation_id or not phone:
            raise PhoneSmsError(f"{self.config.provider} 返回无效取号数据: {payload!r}")
        return PhoneItem(
            id=f"{self.config.provider}:{activation_id}",
            provider=self.config.provider,
            activation_id=str(activation_id),
            phone_number=str(phone),
            raw={"email": email, "response": payload},
        )

    def wait_for_code(self, phone_item: PhoneItem) -> str:
        used = set(phone_item.raw.get("used_codes") or [])
        for _attempt in range(max(1, self.config.poll_attempts)):
            payload = self._get(self._params("getStatus", id=phone_item.activation_id))
            code = ""
            if isinstance(payload, str):
                if payload.startswith("STATUS_OK:"):
                    code = payload.split(":", 1)[1].strip()
                elif payload in {"STATUS_WAIT_CODE", "STATUS_WAIT_RETRY", "STATUS_WAIT_RESEND"}:
                    code = ""
                elif payload.startswith("STATUS_CANCEL") or payload.startswith("NO_ACTIVATION"):
                    raise PhoneSmsError(payload)
            elif isinstance(payload, dict):
                code = _find_nested_value(payload, {"code", "sms_code", "verification_code", "otp"})
                if not code:
                    code = _extract_code_from_text(_find_nested_value(payload, {"sms", "text", "message", "msg"}))
            if code and code not in used:
                used.add(code)
                phone_item.otp = code
                phone_item.raw["used_codes"] = list(used)
                return code
            time.sleep(max(0.0, self.config.poll_interval_seconds))
        raise TimeoutError(f"{self.config.provider} 等待验证码超时")

    def mark_bound(self, phone_item: PhoneItem, email: str) -> None:
        del email
        self._get(self._params("setStatus", id=phone_item.activation_id, status="6"))

    def release(self, phone_item: PhoneItem, *, reason: str = "") -> None:
        del reason
        if phone_item.activation_id:
            self._get(self._params("setStatus", id=phone_item.activation_id, status="8"))


class SMSCloudSmsProvider:
    """SMSCloud HTTP adapter."""

    def __init__(self, config: SmsProviderConfig, *, http_get: Callable[..., Any] | None = None):
        self.config = config
        self.http_get = http_get

    def _url(self, path: str) -> str:
        return urljoin(str(self.config.base_url or "https://smscloud.example/api/system").rstrip("/") + "/", path.lstrip("/"))

    def _get_json(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.http_get is None:
            import requests

            self.http_get = requests.get
        response = self.http_get(
            self._url(path),
            params=params or {},
            headers={"apiKey": self.config.api_key, "Content-Type": "application/json"},
            timeout=30,
        )
        if hasattr(response, "raise_for_status"):
            response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise PhoneSmsError(f"SMSCloud 返回无效 JSON: {payload!r}")
        if int(payload.get("code") or 0) != 0:
            raise PhoneSmsError(_response_error_text(payload) or str(payload))
        return payload

    def acquire_phone(self, email: str = "") -> PhoneItem:
        del email
        if not self.config.api_key:
            raise PhoneSmsError("SMSCloud 缺少 API key")
        if not self.config.country or self.config.country == "all":
            raise PhoneSmsError("SMSCloud 取号必须指定国家 ID")
        params = {
            "countryCode": self.config.country,
            "serviceCode": self.config.service or "dr",
            **({"maxPrice": self.config.max_price} if self.config.max_price else {}),
        }
        payload = self._get_json("/public/sms/flexible", params=params)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        order_id = str(data.get("id") or "").strip()
        phone = str(data.get("phoneNumber") or data.get("phone") or "").strip()
        if not order_id or not phone:
            raise PhoneSmsError(f"SMSCloud 返回无效取号数据: {payload!r}")
        return PhoneItem(
            id=f"smscloud:{order_id}",
            provider="smscloud",
            activation_id=order_id,
            phone_number=phone,
            raw=data,
        )

    def wait_for_code(self, phone_item: PhoneItem) -> str:
        used = set(phone_item.raw.get("used_codes") or [])
        for _attempt in range(max(1, self.config.poll_attempts)):
            payload = self._get_json(f"/public/sms/orders/sync/{phone_item.activation_id}")
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            code = str(data.get("code") or "").strip() or _extract_code_from_text(str(data.get("text") or ""))
            if code and code not in used:
                used.add(code)
                phone_item.otp = code
                phone_item.raw["used_codes"] = list(used)
                return code
            time.sleep(max(0.0, self.config.poll_interval_seconds))
        raise TimeoutError("SMSCloud 等待验证码超时")

    def mark_bound(self, phone_item: PhoneItem, email: str) -> None:
        del email
        self._get_json(f"/public/sms/orders/finish/{phone_item.activation_id}")

    def release(self, phone_item: PhoneItem, *, reason: str = "") -> None:
        del reason
        if phone_item.activation_id:
            self._get_json(f"/public/sms/orders/cancel/{phone_item.activation_id}")


class CdkSmsProvider:
    """Oasis / TuJie style CDK-backed adapter."""

    def __init__(self, config: SmsProviderConfig, *, http_post: Callable[..., Any] | None = None):
        self.config = config
        self.http_post = http_post
        self._reserved: set[str] = set()

    def _endpoint(self, action: str) -> str:
        base = str(self.config.base_url or "https://cdk-sms.example").rstrip("/")
        if self.config.provider == "tujie":
            mapping = {
                "check_cdk": "/user/cdk/phone",
                "get_sms": "/user/cdk/code",
                "cancel": "/user/cdk/cancel",
            }
            return f"{base}{mapping.get(action, f'/user/cdk/{action}')}"
        return f"{base}/api.php?action={urllib.parse.quote(action)}"

    def _post_json(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.http_post is None:
            import requests

            self.http_post = requests.post
        body = {"code": str(payload.get("code") or payload.get("cdk") or "").strip()}
        if self.config.provider == "tujie":
            body = {"code": body["code"], "session_id": str(payload.get("session_id") or "")}
        response = self.http_post(self._endpoint(action), json=body, headers={"Content-Type": "application/json"}, timeout=30)
        if hasattr(response, "raise_for_status"):
            response.raise_for_status()
        parsed = response.json()
        if not isinstance(parsed, dict):
            raise PhoneSmsError(f"{self.config.provider} 返回无效 JSON: {parsed!r}")
        return parsed

    def acquire_phone(self, email: str = "") -> PhoneItem:
        del email
        if not self.config.cdk_values:
            raise PhoneSmsError(f"{self.config.provider} 缺少 CDK 配置")
        errors: list[str] = []
        for cdk in self.config.cdk_values:
            if cdk in self._reserved:
                continue
            try:
                payload = self._post_json("check_cdk", {"code": cdk})
            except Exception as exc:
                errors.append(f"{cdk}: {exc}")
                continue
            if payload.get("ok") is False or payload.get("success") is False or payload.get("available") is False:
                errors.append(f"{cdk}: {_response_error_text(payload) or '不可用'}")
                continue
            phone = _find_nested_value(payload, {"phone", "phone_number", "number", "mobile", "msisdn", "resource_value"})
            if not phone:
                errors.append(f"{cdk}: 未返回手机号")
                continue
            self._reserved.add(cdk)
            return PhoneItem(
                id=f"{self.config.provider}:{cdk}",
                provider=self.config.provider,
                activation_id=cdk,
                phone_number=phone,
                raw={"cdk": cdk, "response": payload},
            )
        raise PhoneSmsError("; ".join(errors) or f"{self.config.provider} 没有可用 CDK")

    def wait_for_code(self, phone_item: PhoneItem) -> str:
        used = set(phone_item.raw.get("used_codes") or [])
        for _attempt in range(max(1, self.config.poll_attempts)):
            payload = self._post_json("get_sms", {"code": phone_item.activation_id})
            code = _find_nested_value(payload, {"code", "sms_code", "verification_code", "otp"})
            if not re.fullmatch(r"\d{4,8}", code or ""):
                code = _extract_code_from_text(_find_nested_value(payload, {"sms", "sms_text", "text", "content", "message", "msg"}))
            if code and code not in used:
                used.add(code)
                phone_item.otp = code
                phone_item.raw["used_codes"] = list(used)
                return code
            time.sleep(max(0.0, self.config.poll_interval_seconds))
        raise TimeoutError(f"{self.config.provider} 等待验证码超时")

    def mark_bound(self, phone_item: PhoneItem, email: str) -> None:
        self._record_mapping(phone_item, email=email, status="success")

    def release(self, phone_item: PhoneItem, *, reason: str = "") -> None:
        self._reserved.discard(phone_item.activation_id)
        if self.config.provider == "tujie":
            try:
                self._post_json("cancel", {"code": phone_item.activation_id})
            except Exception:
                pass
        self._record_mapping(phone_item, email=str(phone_item.raw.get("email") or ""), status="cancelled", reason=reason)

    def _record_mapping(self, phone_item: PhoneItem, *, email: str = "", status: str, reason: str = "") -> None:
        self._reserved.discard(phone_item.activation_id)
        path_text = str(self.config.account_map_file or "").strip()
        if not path_text:
            return
        record = {
            "recorded_at": time.time(),
            "provider": self.config.provider,
            "status": status,
            "reason": reason,
            "cdk": phone_item.activation_id,
            "phone": phone_item.phone_number,
            "email": str(email or "").strip().lower(),
        }
        path = Path(path_text)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def create_sms_provider(
    provider: str | None = None,
    *,
    configs: dict[str, SmsProviderConfig] | None = None,
    phone_pool_path: str | Path = "data/oauth-phone-pool.json",
) -> Any:
    """Create the configured SMS provider adapter."""

    configs = configs or load_phone_sms_provider_configs()
    selected = normalize_phone_sms_provider(provider or os.getenv("OAUTH_RELOGIN_PHONE_SMS_PROVIDER", "phone_pool"))
    cfg = configs.get(selected)
    if not cfg:
        raise PhoneSmsError(f"不支持的接码供应商: {provider}")
    if selected == "phone_pool":
        return JsonPhonePoolProvider(phone_pool_path)
    if selected in {"hero_sms", "smsbower"}:
        return HandlerApiSmsProvider(cfg)
    if selected == "smscloud":
        return SMSCloudSmsProvider(cfg)
    if selected in {"oasis", "tujie"}:
        return CdkSmsProvider(cfg)
    raise PhoneSmsError(f"不支持的接码供应商: {provider}")


def redact_secret(value: object, *, prefix: int = 4, suffix: int = 4) -> str:
    """Return a log-safe representation of a token/secret."""

    text = str(value or "")
    if not text:
        return ""
    if len(text) <= prefix + suffix + 3:
        return "***"
    return f"{text[:prefix]}...{text[-suffix:]}"


def generate_pkce() -> tuple[str, str]:
    """Generate a PKCE code_verifier/code_challenge pair."""

    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_authorization_url(
    config: OAuthConfig,
    *,
    code_challenge: str,
    state: str,
    native_oauth: bool = True,
    extra_params: dict[str, str] | None = None,
) -> str:
    """Build the OAuth authorize URL for a PKCE authorization-code flow."""

    params = {
        "client_id": config.client_id,
        "response_type": "code",
        "redirect_uri": config.redirect_uri,
        "scope": config.scope,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": "login" if native_oauth else "consent",
    }
    if native_oauth:
        params["id_token_add_organizations"] = "true"
        params["codex_cli_simplified_flow"] = "true"
    if extra_params:
        params.update({str(key): str(value) for key, value in extra_params.items() if value is not None})
    return f"{config.auth_url}?{urllib.parse.urlencode(params)}"


def build_helper_fragment(token: str, port: str | int, auth_url: str) -> str:
    """Build a fragment consumed by ``oauth_helper_extension/content.js``."""

    return urllib.parse.urlencode(
        {
            "oauth_relogin_token": str(token or ""),
            "oauth_relogin_port": str(port or ""),
            "oauth_relogin_auth": str(auth_url or ""),
        }
    )


def build_helper_url(token: str, port: str | int, auth_url: str, *, landing_url: str = HELPER_LANDING_URL) -> str:
    """Build a helper landing URL that stores local helper config then redirects."""

    return f"{landing_url}#{build_helper_fragment(token, port, auth_url)}"


def parse_callback_url(input_text: str) -> dict[str, str]:
    """Parse code/state/error from a pasted or captured OAuth callback URL."""

    trimmed = str(input_text or "").strip()
    if not trimmed:
        raise ValueError("回调 URL 不能为空")

    candidate = trimmed
    if "://" not in candidate:
        if candidate.startswith("?"):
            candidate = "http://localhost" + candidate
        elif "=" in candidate:
            candidate = "http://localhost/?" + candidate
        elif any(ch in candidate for ch in "/?#:"):
            candidate = "http://" + candidate
        else:
            raise ValueError("无效的回调 URL")

    parsed_url = urllib.parse.urlparse(candidate)
    query = urllib.parse.parse_qs(parsed_url.query)
    fragment = urllib.parse.parse_qs(parsed_url.fragment)

    def first(name: str) -> str:
        return str((query.get(name) or fragment.get(name) or [""])[0]).strip()

    code = first("code")
    error = first("error") or first("error_description")
    if not code and not error:
        raise ValueError("回调 URL 中缺少 code")
    return {
        "code": code,
        "state": first("state"),
        "error": error,
        "raw_url": candidate,
    }


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    token = str(token or "").strip()
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload.encode("ascii")).decode("utf-8"))
    except Exception:
        return {}


def _plan_from_claims(claims: dict[str, Any]) -> str:
    auth_claims = claims.get("https://api.openai.com/auth", {}) if isinstance(claims, dict) else {}
    if not isinstance(auth_claims, dict):
        return "unknown"
    return str(auth_claims.get("chatgpt_plan_type") or "unknown").strip().lower() or "unknown"


def _account_id_from_claims(*claim_groups: dict[str, Any]) -> str:
    for claims in claim_groups:
        auth_claims = claims.get("https://api.openai.com/auth", {}) if isinstance(claims, dict) else {}
        if isinstance(auth_claims, dict):
            account_id = str(auth_claims.get("chatgpt_account_id") or "").strip()
            if account_id:
                return account_id
    return ""


def build_token_bundle(token_data: dict[str, Any], *, fallback_email: str | None = None, now: float | None = None) -> dict[str, Any]:
    """Normalize an OAuth token endpoint response into a portable auth bundle."""

    if not isinstance(token_data, dict):
        raise OAuthTokenBundleError("token 响应必须是 JSON object")
    id_token = str(token_data.get("id_token") or "")
    access_token = str(token_data.get("access_token") or "")
    refresh_token = str(token_data.get("refresh_token") or "")
    id_claims = _decode_jwt_payload(id_token)
    access_claims = _decode_jwt_payload(access_token)

    try:
        expires_in = int(token_data.get("expires_in", 3600) or 3600)
    except (TypeError, ValueError):
        expires_in = 3600
    timestamp = time.time() if now is None else float(now)
    email = str(id_claims.get("email") or access_claims.get("email") or fallback_email or "").strip().lower()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "id_token": id_token,
        "account_id": _account_id_from_claims(id_claims, access_claims),
        "email": email,
        "plan_type": _plan_from_claims(id_claims) if id_token else _plan_from_claims(access_claims),
        "expired": timestamp + expires_in,
    }


def exchange_auth_code(
    auth_code: str,
    code_verifier: str,
    *,
    config: OAuthConfig | None = None,
    fallback_email: str | None = None,
    http_post: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Exchange an authorization code for tokens.

    ``http_post`` is injectable for tests or for projects that use a custom HTTP
    client. It must return an object with ``status_code`` and ``json()``.
    """

    config = config or OAuthConfig.from_env()
    if not str(auth_code or "").strip():
        raise OAuthError("auth_code 不能为空")
    if not str(code_verifier or "").strip():
        raise OAuthError("code_verifier 不能为空")

    if http_post is None:
        import requests

        http_post = requests.post

    response = http_post(
        config.token_url,
        data={
            "grant_type": "authorization_code",
            "client_id": config.client_id,
            "code": auth_code,
            "redirect_uri": config.redirect_uri,
            "code_verifier": code_verifier,
        },
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": config.user_agent,
        },
        timeout=30,
    )
    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code != 200:
        body = str(getattr(response, "text", "") or "")[:240]
        raise OAuthError(f"OAuth token 交换失败 HTTP {status_code}: {body}")
    bundle = build_token_bundle(response.json(), fallback_email=fallback_email)
    if not bundle.get("access_token") or not bundle.get("refresh_token"):
        raise OAuthTokenBundleError("OAuth token 响应缺少 access_token 或 refresh_token")
    return bundle


def _headers(config: OAuthConfig, referer: str = "") -> dict[str, str]:
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": config.user_agent,
    }
    if referer:
        headers["Referer"] = referer
    return headers


def _callback_has_oauth_result(url: str) -> bool:
    parsed = urllib.parse.urlparse(str(url or ""))
    if "/auth/callback" not in (parsed.path or "").lower():
        return False
    query = urllib.parse.parse_qs(parsed.query)
    fragment = urllib.parse.parse_qs(parsed.fragment)
    return any((query.get(name) or fragment.get(name)) for name in ("code", "error", "error_description"))


def _extract_meta_refresh_url(html: str, base_url: str) -> str:
    import re

    match = re.search(
        r"<meta[^>]+http-equiv=[\"']?refresh[\"']?[^>]+content=[\"'][^\"']*url=([^\"'>\s]+)",
        str(html or ""),
        flags=re.I,
    )
    if not match:
        return ""
    return urllib.parse.urljoin(base_url, match.group(1).replace("&amp;", "&"))


def extract_session_token(auth_session: dict[str, Any], *, session_cookie_name: str = DEFAULT_SESSION_COOKIE_NAME) -> str:
    """Extract a reusable session token from a saved auth_session payload."""

    if not isinstance(auth_session, dict):
        return ""
    data = auth_session.get("data") if isinstance(auth_session.get("data"), dict) else auth_session
    context = auth_session.get("auth_context") if isinstance(auth_session.get("auth_context"), dict) else {}
    merged = {**data, **{key: value for key, value in context.items() if value}}
    direct = str(merged.get("sessionToken") or merged.get("session_token") or "").strip()
    if direct:
        return direct
    cookie_header = str(merged.get("cookie_header") or "")
    for part in cookie_header.split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name == session_cookie_name:
            return urllib.parse.unquote(value.strip())
    return ""


def seed_auth_cookies(session: Any, token: str, *, config: OAuthConfig, account_id: str = "", device_id: str = "") -> None:
    """Seed auth cookies on a requests-compatible session."""

    token = str(token or "").strip()
    if not token:
        return
    for domain in config.auth_domains:
        if len(token) > 3800:
            session.cookies.set(f"{config.session_cookie_name}.0", token[:3800], domain=domain, path="/")
            session.cookies.set(f"{config.session_cookie_name}.1", token[3800:], domain=domain, path="/")
        else:
            session.cookies.set(config.session_cookie_name, token, domain=domain, path="/")
        if account_id:
            session.cookies.set(config.account_cookie_name, account_id, domain=domain, path="/")
        if device_id:
            session.cookies.set(config.device_cookie_name, device_id, domain=domain, path="/")


def follow_authorization_redirects(
    session: Any,
    auth_url: str,
    *,
    expected_state: str,
    config: OAuthConfig | None = None,
    max_redirects: int = 18,
) -> dict[str, str]:
    """Follow an OAuth authorize URL until it reaches a callback result."""

    config = config or OAuthConfig.from_env()
    current_url = auth_url
    referer = ""
    final_body = ""
    for _index in range(max(1, int(max_redirects or 1))):
        if _callback_has_oauth_result(current_url):
            parsed = parse_callback_url(current_url)
            if parsed.get("state") and parsed["state"] != expected_state:
                raise OAuthError("OAuth state 不匹配")
            return parsed

        response = session.get(current_url, headers=_headers(config, referer), allow_redirects=False, timeout=30)
        final_body = str(getattr(response, "text", "") or "")
        status = int(getattr(response, "status_code", 0) or 0)
        location = str(getattr(response, "headers", {}).get("Location") or "")
        if status in {301, 302, 303, 307, 308} and location:
            referer = current_url
            current_url = urllib.parse.urljoin(current_url, location)
            continue

        meta_url = _extract_meta_refresh_url(final_body, current_url)
        if meta_url:
            referer = current_url
            current_url = meta_url
            continue

        lower_url = current_url.lower()
        lower_body = final_body[:3000].lower()
        if "add-phone" in lower_url or "phone verification" in lower_body or "add phone" in lower_body:
            raise OAuthPhoneRequired(current_url)
        if "log-in" in lower_url or "login" in lower_url or "sign in" in lower_body:
            raise OAuthLoginRequired(current_url)
        break
    raise OAuthError(f"OAuth 未在 {max_redirects} 次跳转内返回 callback")


def make_http_session(proxy_url: str | None = None) -> Any:
    """Create a requests-compatible session, preferring curl_cffi when installed."""

    try:
        from curl_cffi.requests import Session as CurlCffiSession  # type: ignore

        session = CurlCffiSession(impersonate="chrome")
    except Exception:
        import requests

        session = requests.Session()
    proxy = str(proxy_url or "").strip()
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}
    return session


def oauth_from_auth_session(
    auth_session: dict[str, Any],
    *,
    config: OAuthConfig | None = None,
    email: str = "",
    account_id: str = "",
    device_id: str = "",
    proxy_url: str | None = None,
    session: Any | None = None,
) -> dict[str, Any]:
    """Run a protocol-only OAuth relogin from an existing auth_session/cookie."""

    config = config or OAuthConfig.from_env()
    session_token = extract_session_token(auth_session, session_cookie_name=config.session_cookie_name)
    if not session_token:
        raise OAuthError("auth_session 缺少可复用凭证")

    verifier, challenge = generate_pkce()
    state = secrets.token_urlsafe(16)
    auth_url = build_authorization_url(config, code_challenge=challenge, state=state, native_oauth=True)
    session = session or make_http_session(proxy_url)
    seed_auth_cookies(session, session_token, config=config, account_id=account_id, device_id=device_id)
    callback = follow_authorization_redirects(session, auth_url, expected_state=state, config=config)
    if callback.get("error"):
        raise OAuthError(f"OAuth 返回错误: {callback['error']}")
    return exchange_auth_code(callback["code"], verifier, config=config, fallback_email=email, http_post=session.post)


def save_auth_bundle(bundle: dict[str, Any], path: str | Path) -> str:
    """Save an auth bundle without logging or printing secrets."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        target.chmod(0o600)
    except Exception:
        pass
    return str(target)


def _safe_email_slug(email: str) -> str:
    value = str(email or "").strip().lower()
    slug = re.sub(r"[^a-z0-9_.+-]+", "-", value)
    return slug.strip("-") or "oauth-account"


def append_phone_binding_record(path: str | Path, *, phone_item: PhoneItem, email: str, now: float | None = None) -> str:
    """Append a non-secret phone binding audit record to JSON."""

    target = Path(path)
    if target.exists():
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PhoneSmsError(f"手机号绑定记录 JSON 无效: {target}") from exc
    else:
        data = {"bindings": []}
    if not isinstance(data, dict):
        data = {"bindings": []}
    bindings = data.get("bindings")
    if not isinstance(bindings, list):
        bindings = []
        data["bindings"] = bindings
    bindings.append(
        {
            "email": str(email or "").strip().lower(),
            "phone_number": phone_item.phone_number,
            "phone_id": phone_item.id,
            "provider": phone_item.provider,
            "bound_at": time.time() if now is None else float(now),
        }
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)


@dataclasses.dataclass
class OAuthFlowState:
    """Mutable state exposed to the browser helper extension."""

    email: str
    password: str = ""
    otp: str = ""
    phone: str = ""
    phone_otp: str = ""

    def to_json(self) -> dict[str, str]:
        return {
            "email": self.email,
            "password": self.password,
            "otp": self.otp or self.phone_otp,
            "phone": self.phone,
            "phone_otp": self.phone_otp or self.otp,
        }


class _ReusableHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


class LocalOAuthHelperServer:
    """Local server consumed by ``oauth_helper_extension/content.js``."""

    def __init__(self, state: OAuthFlowState, *, port: int = 0, token: str | None = None):
        self.state = state
        self.port = int(port or 0)
        self.token = token or secrets.token_urlsafe(18)
        self.server: _ReusableHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.events: list[dict[str, Any]] = []
        self.phone_required_url = ""
        self.callback_url = ""

    def start(self) -> LocalOAuthHelperServer:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def _authorized(self) -> bool:
                parsed = urllib.parse.urlparse(self.path)
                token = urllib.parse.parse_qs(parsed.query).get("token", [""])[0]
                return token == owner.token

            def _json(self, status: int, payload: dict[str, Any]) -> None:
                raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path != "/state":
                    self.send_error(404)
                    return
                if not self._authorized():
                    self._json(403, {"error": "forbidden"})
                    return
                self._json(200, owner.state.to_json())

            def do_POST(self):
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path != "/event":
                    self.send_error(404)
                    return
                if not self._authorized():
                    self._json(403, {"error": "forbidden"})
                    return
                try:
                    length = int(self.headers.get("Content-Length") or "0")
                    payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                except Exception:
                    payload = {}
                if isinstance(payload, dict):
                    owner.events.append(payload)
                    event_type = str(payload.get("type") or "")
                    url = str(payload.get("url") or "")
                    if event_type == "phone_required":
                        owner.phone_required_url = url
                    if event_type == "callback":
                        owner.callback_url = url
                self._json(200, {"ok": True})

            def log_message(self, _format, *_args):
                return

        self.server = _ReusableHTTPServer(("127.0.0.1", self.port), Handler)
        self.port = int(self.server.server_port)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def set_phone(self, phone_item: PhoneItem) -> None:
        self.state.phone = phone_item.phone_number

    def set_otp(self, otp: str) -> None:
        self.state.otp = str(otp or "").strip()
        self.state.phone_otp = self.state.otp

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1)
        self.thread = None


class OAuthCallbackServer:
    """Local OAuth redirect_uri callback server."""

    def __init__(self, *, port: int = DEFAULT_CALLBACK_PORT):
        self.port = int(port or 0)
        self.server: _ReusableHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self._event = threading.Event()
        self.callback: dict[str, str] | None = None

    def start(self) -> OAuthCallbackServer:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if not urllib.parse.urlparse(self.path).path.startswith("/auth/callback"):
                    self.send_error(404)
                    return
                host = self.headers.get("Host", f"127.0.0.1:{owner.port}")
                raw_url = f"http://{host}{self.path}"
                try:
                    owner.callback = parse_callback_url(raw_url)
                    owner._event.set()
                    status = 200
                    body = "Authentication successful. You can close this window."
                except Exception as exc:
                    owner.callback = {"code": "", "state": "", "error": str(exc), "raw_url": raw_url}
                    owner._event.set()
                    status = 400
                    body = f"Authentication failed: {exc}"
                raw = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, _format, *_args):
                return

        self.server = _ReusableHTTPServer(("127.0.0.1", self.port), Handler)
        self.port = int(self.server.server_port)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def wait_for_callback(self, *, timeout: float = 180) -> dict[str, str]:
        if not self._event.wait(timeout=max(0.1, float(timeout or 180))):
            raise TimeoutError("等待 OAuth callback 超时")
        return dict(self.callback or {})

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1)
        self.thread = None


class BrowserOAuthRunner:
    """Browser/helper based OAuth runner that can bind phone and exchange tokens."""

    def __init__(
        self,
        *,
        email: str,
        password: str = "",
        config: OAuthConfig | None = None,
        sms_provider: Any | None = None,
        phone_code_provider: Callable[[PhoneItem], str] | None = None,
        proxy_url: str | None = None,
        open_browser: Callable[[str], Any] | None = None,
        wait_callback: Callable[[BrowserOAuthRunner], dict[str, str]] | None = None,
        exchange: Callable[..., dict[str, Any]] | None = None,
        callback_timeout_seconds: float = 300,
    ):
        self.email = str(email or "").strip().lower()
        self.password = password
        self.config = config or OAuthConfig.from_env()
        self.sms_provider = sms_provider
        self.phone_code_provider = phone_code_provider
        self.proxy_url = proxy_url
        self.open_browser = open_browser or self._open_default_browser
        self.wait_callback = wait_callback
        self.exchange = exchange or exchange_auth_code
        self.callback_timeout_seconds = callback_timeout_seconds
        self.code_verifier = ""
        self.state = ""
        self.phone_item: PhoneItem | None = None
        self.helper_server: LocalOAuthHelperServer | None = None
        self.callback_server: OAuthCallbackServer | None = None

    def _open_default_browser(self, url: str) -> None:
        extension_dir = Path(__file__).resolve().parent / "oauth_helper_extension"
        if extension_dir.exists():
            try:
                from playwright.sync_api import sync_playwright

                playwright = sync_playwright().start()
                user_data_dir = tempfile.mkdtemp(prefix="oauth-relogin-profile-")
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir,
                    headless=False,
                    args=[
                        f"--disable-extensions-except={extension_dir}",
                        f"--load-extension={extension_dir}",
                    ],
                    proxy={"server": self.proxy_url} if self.proxy_url else None,
                )
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                self._playwright_runtime = {
                    "playwright": playwright,
                    "context": context,
                    "user_data_dir": user_data_dir,
                }
                return
            except Exception:
                try:
                    runtime = getattr(self, "_playwright_runtime", {}) or {}
                    if runtime.get("context"):
                        runtime["context"].close()
                    if runtime.get("playwright"):
                        runtime["playwright"].stop()
                except Exception:
                    pass
        import webbrowser

        webbrowser.open(url)

    def _handle_phone_if_needed(self) -> None:
        if not self.helper_server or not self.helper_server.phone_required_url:
            return
        if self.phone_item:
            return
        if self.sms_provider is None:
            raise OAuthPhoneRequired(self.helper_server.phone_required_url)
        self.phone_item = self.sms_provider.acquire_phone(self.email)
        self.helper_server.set_phone(self.phone_item)
        if self.phone_code_provider is not None:
            code = str(self.phone_code_provider(self.phone_item) or "").strip()
        else:
            code = str(self.sms_provider.wait_for_code(self.phone_item) or "").strip()
        if not code:
            raise PhoneSmsError("未获取到手机号验证码")
        self.phone_item.otp = code
        self.helper_server.set_otp(code)

    def _wait_for_callback_default(self) -> dict[str, str]:
        assert self.callback_server is not None
        deadline = time.time() + max(1.0, float(self.callback_timeout_seconds))
        while time.time() < deadline:
            self._handle_phone_if_needed()
            if self.callback_server._event.wait(timeout=0.5):
                return dict(self.callback_server.callback or {})
        raise TimeoutError("等待 OAuth callback 超时")

    def run(self) -> dict[str, Any]:
        self.code_verifier, challenge = generate_pkce()
        self.state = secrets.token_urlsafe(16)
        redirect_port = urllib.parse.urlparse(self.config.redirect_uri).port or DEFAULT_CALLBACK_PORT
        self.callback_server = OAuthCallbackServer(port=redirect_port).start()
        self.helper_server = LocalOAuthHelperServer(OAuthFlowState(email=self.email, password=self.password), port=0).start()
        auth_url = build_authorization_url(self.config, code_challenge=challenge, state=self.state, native_oauth=True)
        helper_url = build_helper_url(self.helper_server.token, self.helper_server.port, auth_url)
        try:
            self.open_browser(helper_url)
            callback = self.wait_callback(self) if self.wait_callback else self._wait_for_callback_default()
            if callback.get("error"):
                raise OAuthError(f"OAuth 返回错误: {callback['error']}")
            if callback.get("state") and callback["state"] != self.state:
                raise OAuthError("OAuth state 不匹配")
            bundle = self.exchange(
                callback["code"],
                self.code_verifier,
                config=self.config,
                fallback_email=self.email,
            )
            if self.phone_item and self.sms_provider is not None:
                self.sms_provider.mark_bound(self.phone_item, self.email)
            return bundle
        except Exception:
            if self.phone_item and self.sms_provider is not None and hasattr(self.sms_provider, "release"):
                try:
                    self.sms_provider.release(self.phone_item, reason="browser_oauth_failed")
                except Exception:
                    pass
            raise
        finally:
            if self.helper_server:
                self.helper_server.stop()
            if self.callback_server:
                self.callback_server.stop()
            runtime = getattr(self, "_playwright_runtime", {}) or {}
            try:
                if runtime.get("context"):
                    runtime["context"].close()
                if runtime.get("playwright"):
                    runtime["playwright"].stop()
            except Exception:
                pass


def default_oauth_runner(**kwargs) -> dict[str, Any]:
    """Default protocol runner used by ``run_oauth_relogin_flow``.

    This runner expects an existing auth_session dict. Browser/UI automation and
    external SMS APIs are intentionally adapters so the copied module can be used
    in different projects without dragging the original app's task system.
    """

    auth_session = kwargs.get("auth_session")
    if not isinstance(auth_session, dict):
        raise OAuthError("默认 runner 需要 auth_session；浏览器登录请传入自定义 oauth_runner")
    return oauth_from_auth_session(
        auth_session,
        config=kwargs.get("config"),
        email=str(kwargs.get("email") or ""),
        account_id=str(kwargs.get("account_id") or ""),
        device_id=str(kwargs.get("device_id") or ""),
        proxy_url=kwargs.get("proxy_url"),
    )


def run_oauth_relogin_flow(
    *,
    email: str,
    password: str = "",
    output_dir: str | Path = "oauth-output",
    config: OAuthConfig | None = None,
    auth_session: dict[str, Any] | None = None,
    bind_phone: bool = False,
    sms_provider: Any | None = None,
    phone_code_provider: Callable[[PhoneItem], str] | None = None,
    oauth_runner: Callable[..., dict[str, Any]] | None = None,
    proxy_url: str | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Run the standalone OAuth relogin orchestration and persist JSON files.

    End-to-end responsibility:
    1. load OAuth config
    2. optionally reserve a phone number
    3. expose a ``get_phone_code`` callback to the OAuth/browser runner
    4. persist the returned token bundle as JSON
    5. mark the phone as bound and write a binding audit JSON file

    ``oauth_runner`` is the integration point for either protocol auth_session
    login or browser automation in the target project. It must return a token
    bundle compatible with ``save_auth_bundle``.
    """

    normalized_email = str(email or "").strip().lower()
    if not normalized_email:
        raise OAuthError("email 不能为空")
    config = config or OAuthConfig.from_env()
    runner = oauth_runner or default_oauth_runner
    timestamp = time.time() if now is None else float(now)
    output_root = Path(output_dir)
    phone_item: PhoneItem | None = None
    phone_records_file = ""

    if bind_phone:
        if sms_provider is None:
            raise PhoneSmsError("bind_phone=True 时必须提供 sms_provider")
        phone_item = sms_provider.acquire_phone(normalized_email)

    def get_phone_code() -> str:
        if not phone_item:
            return ""
        if phone_code_provider is not None:
            code = str(phone_code_provider(phone_item) or "").strip()
            if not code:
                raise PhoneSmsError("phone_code_provider 未返回验证码")
            phone_item.otp = code
            return code
        return str(sms_provider.wait_for_code(phone_item) or "").strip()

    try:
        bundle = runner(
            email=normalized_email,
            password=password,
            config=config,
            auth_session=auth_session,
            phone_item=phone_item,
            get_phone_code=get_phone_code,
            proxy_url=proxy_url,
        )
        if not isinstance(bundle, dict):
            raise OAuthTokenBundleError("oauth_runner 未返回 token bundle")
        if not bundle.get("access_token") or not bundle.get("refresh_token"):
            raise OAuthTokenBundleError("OAuth token bundle 缺少 access_token 或 refresh_token")

        actual_email = str(bundle.get("email") or normalized_email).strip().lower()
        slug = _safe_email_slug(actual_email)
        auth_file = save_auth_bundle(bundle, output_root / "auths" / f"oauth-{slug}.json")

        if phone_item and sms_provider is not None:
            sms_provider.mark_bound(phone_item, actual_email)
            phone_records_file = append_phone_binding_record(
                output_root / "phone-bindings.json",
                phone_item=phone_item,
                email=actual_email,
                now=timestamp,
            )

        return {
            "status": "completed",
            "email": actual_email,
            "auth_file": auth_file,
            "phone_bound": bool(phone_item),
            "phone_number": phone_item.phone_number if phone_item else "",
            "phone_records_file": phone_records_file,
            "plan_type": str(bundle.get("plan_type") or "unknown"),
            "account_id": str(bundle.get("account_id") or ""),
        }
    except Exception:
        if phone_item and sms_provider is not None and hasattr(sms_provider, "release"):
            try:
                sms_provider.release(phone_item, reason="oauth_flow_failed")
            except Exception:
                pass
        raise


def run_browser_oauth_relogin_flow(
    *,
    email: str,
    password: str = "",
    output_dir: str | Path = "oauth-output",
    config: OAuthConfig | None = None,
    sms_provider: Any | None = None,
    phone_code_provider: Callable[[PhoneItem], str] | None = None,
    proxy_url: str | None = None,
    open_browser: Callable[[str], Any] | None = None,
    wait_callback: Callable[[BrowserOAuthRunner], dict[str, str]] | None = None,
    exchange: Callable[..., dict[str, Any]] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Run the complete browser-helper OAuth relogin flow and persist JSON."""

    normalized_email = str(email or "").strip().lower()
    if not normalized_email:
        raise OAuthError("email 不能为空")
    config = config or OAuthConfig.from_env()
    runner = BrowserOAuthRunner(
        email=normalized_email,
        password=password,
        config=config,
        sms_provider=sms_provider,
        phone_code_provider=phone_code_provider,
        proxy_url=proxy_url,
        open_browser=open_browser,
        wait_callback=wait_callback,
        exchange=exchange,
    )
    bundle = runner.run()
    if not isinstance(bundle, dict) or not bundle.get("access_token") or not bundle.get("refresh_token"):
        raise OAuthTokenBundleError("浏览器 OAuth 未返回有效 token bundle")
    actual_email = str(bundle.get("email") or normalized_email).strip().lower()
    output_root = Path(output_dir)
    auth_file = save_auth_bundle(bundle, output_root / "auths" / f"oauth-{_safe_email_slug(actual_email)}.json")
    phone_records_file = ""
    if runner.phone_item:
        phone_records_file = append_phone_binding_record(
            output_root / "phone-bindings.json",
            phone_item=runner.phone_item,
            email=actual_email,
            now=time.time() if now is None else float(now),
        )
    return {
        "status": "completed",
        "email": actual_email,
        "auth_file": auth_file,
        "phone_bound": bool(runner.phone_item),
        "phone_number": runner.phone_item.phone_number if runner.phone_item else "",
        "phone_records_file": phone_records_file,
        "plan_type": str(bundle.get("plan_type") or "unknown"),
        "account_id": str(bundle.get("account_id") or ""),
    }
