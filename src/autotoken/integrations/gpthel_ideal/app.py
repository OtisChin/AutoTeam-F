from __future__ import annotations

import base64
import io
import json
import os
import random
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from autotoken.services import proxy_runtime
from autotoken.services.payment_error_classifier import is_non_zero_amount_error
from autotoken.settings.config import normalize_proxy_url
from autotoken.storage import accounts as account_store  # noqa: F401
from autotoken.storage.auth_session_store import delete_auth_session  # noqa: F401

try:
    import qrcode
    from qrcode.exceptions import DataOverflowError
except ImportError:  # pragma: no cover - optional runtime dependency
    qrcode = None  # type: ignore[assignment]

    class DataOverflowError(Exception):
        pass

try:
    from curl_cffi.requests import Session as CurlCffiSession  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    CurlCffiSession = None  # type: ignore

from . import stripe_fingerprint
from .account_pool import AccountPoolError, AccountPoolNotFound, AccountPoolStore
from .mail_pool import (
    MailPoolConflict,
    MailPoolError,
    MailPoolNotFound,
    MailPoolOTPTimeout,
    MailPoolStore,
)


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def env_json_dict(name: str) -> dict[str, str]:
    try:
        value = json.loads(os.getenv(name, "{}") or "{}")
    except Exception:
        return {}
    if not isinstance(value, dict):
        return {}
    return {str(k).upper(): str(v) for k, v in value.items() if str(v).strip()}


DEFAULT_STRIPE_PK = (
    "pk_live_51HOrSwC6h1nxGoI3lTAgRjYVrz4dU3fVOabyCcKR3pbEJguCVAlqCxdxCUvoRh1XWwRac"
    "ViovU3kLKvpkjh7IqkW00iXQsjo3n"
)
STRIPE_VERSION_FULL = "2025-03-31.basil; checkout_server_update_beta=v1; checkout_manual_approval_preview=v1"
PAYPAL_STRIPE_VERSION = "2020-08-27;custom_checkout_beta=v1; checkout_server_update_beta=v1; checkout_manual_approval_preview=v1"
DEFAULT_TIMEOUT = 30
PAYPAL_PROVIDER_MAX_ATTEMPTS = env_int("OPENAI_PAY_PAYPAL_PROVIDER_ATTEMPTS", 10)
PROXY_REGION_CHECK_ATTEMPTS = env_int("OPENAI_PAY_PROXY_REGION_CHECK_ATTEMPTS", 2)
CHECKOUT_CREATE_MAX_ATTEMPTS = env_int("OPENAI_PAY_CHECKOUT_ATTEMPTS", 5)
STRIPE_INIT_MAX_ATTEMPTS = env_int("OPENAI_PAY_STRIPE_INIT_ATTEMPTS", 3)
BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"
RUN_OUTPUT_DIR = BASE_DIR / "run-output"
DIAGNOSTICS_DIR = RUN_OUTPUT_DIR / "diagnostics"
MAIL_POOL_DB = Path(os.getenv("MAIL_POOL_DB", str(BASE_DIR / "data" / "mail_pool.db")))
ACCOUNT_POOL_DB = Path(os.getenv("ACCOUNT_POOL_DB", str(MAIL_POOL_DB)))
PROXY_711_REFRESH_URLS = env_json_dict("OPENAI_PAY_711_REFRESH_URLS")
DEFAULT_PROXY = os.getenv(
    "OPENAI_PAY_DEFAULT_PROXY",
    "",
).strip()
PROVIDER_STAGE_PROXY = os.getenv("OPENAI_PAY_PROVIDER_PROXY", "").strip()
GOPAY_PROVIDER_STAGE_PROXY = os.getenv(
    "OPENAI_PAY_GOPAY_PROVIDER_PROXY",
    "",
).strip()
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)
APPLE_SAFARI_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6_1) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15"
)
DEFAULT_STRIPE_RUNTIME_VERSION = "6f8494a281"
PAYPAL_STRIPE_RUNTIME_VERSION = os.getenv("OPENAI_PAY_PAYPAL_STRIPE_RUNTIME_VERSION", "81274c9437").strip() or "81274c9437"
JWT_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])([A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,})(?![A-Za-z0-9_-])")
PAYPAL_BA_APPROVE_BASE = "https://www.paypal.com/agreements/approve"
PAYPAL_BA_TOKEN_RE = re.compile(
    r"(?i)(?:ba_token|baToken|billing_agreement_token|billingAgreementToken)"
    r"[\s\"'=:]+(?P<token>BA-[A-Za-z0-9_-]+)"
)
PAYPAL_BA_APPROVE_RE = re.compile(
    r"(?i)(?:(?:https?:)?//)?(?:www\.)?paypal\.com/agreements/approve\?[^\\\s\"'<>]*?ba_token=(?P<token>BA-[A-Za-z0-9_-]+)"
)
US_BILLING_NAMES = [
    ("James", "Smith"),
    ("John", "Brown"),
    ("Michael", "Johnson"),
    ("Robert", "Miller"),
    ("David", "Davis"),
    ("William", "Wilson"),
]
US_BILLING_STREETS = [
    ("3110 Sunset Boulevard", "Los Angeles", "CA", "90026"),
    ("1200 Market Street", "San Francisco", "CA", "94102"),
    ("500 Main Street", "Austin", "TX", "78701"),
    ("88 Broadway", "New York", "NY", "10007"),
    ("1200 Peachtree St", "Atlanta", "GA", "30309"),
]
JAPAN_BILLING_NAMES = [
    ("Taro", "Yamada"),
    ("Hanako", "Sato"),
    ("Ken", "Suzuki"),
    ("Yui", "Takahashi"),
    ("Haruto", "Tanaka"),
]
JAPAN_BILLING_STREETS = [
    ("1-2-3 Shibuya", "Shibuya-ku", "Tokyo", "150-0002"),
    ("2-1-1 Namba", "Chuo-ku", "Osaka", "542-0076"),
    ("3-4-5 Sakae", "Naka-ku", "Aichi", "460-0008"),
    ("4-2-8 Hakata", "Hakata-ku", "Fukuoka", "812-0011"),
]
INDONESIA_BILLING_NAMES = [
    ("Budi", "Santoso"),
    ("Agus", "Wijaya"),
    ("Siti", "Rahma"),
    ("Dewi", "Lestari"),
    ("Rizky", "Pratama"),
]
INDONESIA_BILLING_STREETS = [
    ("Jl. Jend. Sudirman No. 1", "Jakarta", "DKI Jakarta", "10210"),
    ("Jl. MH Thamrin No. 10", "Jakarta", "DKI Jakarta", "10350"),
    ("Jl. Asia Afrika No. 8", "Bandung", "Jawa Barat", "40111"),
    ("Jl. Basuki Rahmat No. 5", "Surabaya", "Jawa Timur", "60271"),
]
NETHERLANDS_BILLING_NAMES = [
    ("Jan", "de Vries"),
    ("Sanne", "Jansen"),
    ("Daan", "Bakker"),
    ("Emma", "Visser"),
    ("Lars", "Smit"),
]
NETHERLANDS_BILLING_STREETS = [
    ("Prinsengracht 263", "Amsterdam", "", "1016 GV"),
    ("Coolsingel 40", "Rotterdam", "", "3011 AD"),
    ("Oudegracht 120", "Utrecht", "", "3511 AW"),
    ("Grote Markt 1", "Groningen", "", "9712 HN"),
]
COUNTRY_CURRENCY = {
    "AT": "EUR",
    "AU": "AUD",
    "BE": "EUR",
    "BR": "BRL",
    "CA": "CAD",
    "CH": "CHF",
    "CZ": "CZK",
    "DE": "EUR",
    "DK": "DKK",
    "ES": "EUR",
    "FI": "EUR",
    "FR": "EUR",
    "GB": "GBP",
    "HK": "HKD",
    "ID": "IDR",
    "IE": "EUR",
    "IN": "INR",
    "IT": "EUR",
    "JP": "JPY",
    "KR": "KRW",
    "MX": "MXN",
    "MY": "MYR",
    "NL": "EUR",
    "NO": "NOK",
    "NZ": "NZD",
    "PH": "PHP",
    "PL": "PLN",
    "PT": "EUR",
    "SE": "SEK",
    "SG": "SGD",
    "TH": "THB",
    "TW": "TWD",
    "US": "USD",
    "VN": "VND",
}
COUNTRY_TIMEZONE = {
    "AT": "Europe/Vienna",
    "AU": "Australia/Sydney",
    "BE": "Europe/Brussels",
    "BR": "America/Sao_Paulo",
    "CA": "America/Toronto",
    "CH": "Europe/Zurich",
    "CZ": "Europe/Prague",
    "DE": "Europe/Berlin",
    "DK": "Europe/Copenhagen",
    "ES": "Europe/Madrid",
    "FI": "Europe/Helsinki",
    "FR": "Europe/Paris",
    "GB": "Europe/London",
    "HK": "Asia/Hong_Kong",
    "ID": "Asia/Jakarta",
    "IE": "Europe/Dublin",
    "IN": "Asia/Kolkata",
    "IT": "Europe/Rome",
    "JP": "Asia/Tokyo",
    "KR": "Asia/Seoul",
    "MX": "America/Mexico_City",
    "MY": "Asia/Kuala_Lumpur",
    "NL": "Europe/Amsterdam",
    "NO": "Europe/Oslo",
    "NZ": "Pacific/Auckland",
    "PH": "Asia/Manila",
    "PL": "Europe/Warsaw",
    "PT": "Europe/Lisbon",
    "SE": "Europe/Stockholm",
    "SG": "Asia/Singapore",
    "TH": "Asia/Bangkok",
    "TW": "Asia/Taipei",
    "US": "America/New_York",
    "VN": "Asia/Ho_Chi_Minh",
}
LOCALE_MAP = {
    "de": ("de-DE", "de"),
    "en": ("en-US", "en"),
    "en-US": ("en-US", "en"),
    "es": ("es-ES", "es"),
    "fr": ("fr-FR", "fr"),
    "id": ("id-ID", "id"),
    "it": ("it-IT", "it"),
    "ja": ("ja-JP", "ja"),
    "ko": ("ko-KR", "ko"),
    "pt-BR": ("pt-BR", "pt-BR"),
    "zh-CN": ("zh-CN", "zh-CN"),
    "zh-TW": ("zh-TW", "zh-TW"),
}
REGION_LOCALE = {
    "DE": ("de-DE", "de"),
    "ES": ("es-ES", "es"),
    "FR": ("fr-FR", "fr"),
    "ID": ("id-ID", "id"),
    "IT": ("it-IT", "it"),
    "JP": ("ja-JP", "ja"),
    "KR": ("ko-KR", "ko"),
    "BR": ("pt-BR", "pt-BR"),
    "CN": ("zh-CN", "zh-CN"),
    "TW": ("zh-TW", "zh-TW"),
    "HK": ("zh-TW", "zh-TW"),
    "US": ("en-US", "en"),
    "GB": ("en-GB", "en"),
    "NL": ("nl-NL", "nl"),
}


class LongLinkRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    access_token: str = Field(..., alias="accessToken")
    proxy: str = ""
    stripe_publishable_key: str = ""
    billing_country: str = "US"
    checkout_ui_mode: str = "hosted"
    payment_locale: str = "en"
    link_type: str = "hosted"
    checkout_proxy_region: str = Field("", alias="checkoutProxyRegion")
    provider_proxy_region: str = Field("", alias="providerProxyRegion")
    proxy_chain_strategy: str = Field("", alias="proxyChainStrategy")
    approve_proxy_region: str = Field("", alias="approveProxyRegion")
    proxy_preflight_attempts: int = Field(5, alias="proxyPreflightAttempts")
    diagnostic_enabled: bool = Field(False, alias="diagnosticEnabled")
    diagnostic_job_id: str = Field("", exclude=True)
    diagnostic_strategy: str = Field("", exclude=True)
    diagnostic_records: list[dict[str, Any]] = Field(default_factory=list, exclude=True)
    client_fingerprint: str = Field("chrome", alias="clientFingerprint")
    device_id: str = ""
    user_agent: str = ""

    @field_validator("proxy_preflight_attempts", mode="before")
    @classmethod
    def _clean_proxy_preflight_attempts(cls, value: Any) -> int:
        try:
            attempts = int(value or 5)
        except Exception:
            attempts = 5
        return max(1, min(100, attempts))


class ProxyChainTestRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    proxy: str = ""
    link_type: str = "hosted"
    checkout_proxy_region: str = Field("", alias="checkoutProxyRegion")
    provider_proxy_region: str = Field("", alias="providerProxyRegion")


class QRCodeRequest(BaseModel):
    value: str = Field(..., min_length=1, max_length=12000)


class MailPoolImportRequest(BaseModel):
    text: str = Field("", max_length=4 * 1024 * 1024)


class MailPoolOTPRequest(BaseModel):
    pool_id: int = Field(0, alias="pool_id")
    email: str = ""
    timeout: int = 60
    issued_after: float = Field(0, alias="issued_after")
    service: str = "verification"
    exclude_code: str = Field("", alias="exclude_code")


class RegisterReserveRequest(BaseModel):
    owner: str = "authorized_registration"
    service: str = "verification"


class RegisterOTPRequest(BaseModel):
    timeout: int = 60
    exclude_code: str = Field("", alias="exclude_code")


class AccountPoolImportRequest(BaseModel):
    text: str = Field("", max_length=8 * 1024 * 1024)


class LongLinkResponse(BaseModel):
    ok: bool
    cs_id: str
    processor_entity: str
    billing_country: str
    currency: str
    payment_locale: str
    link_type: str
    payment_method_type: str
    payment_method_id: str
    stripe_redirect_url: str
    provider_redirect_url: str
    fallback: bool = False
    provider_error: str = ""
    stripe_hosted_url: str
    long_url: str
    amount: str = ""
    amount_display: str = ""
    cs_count: int = 1
    steps: list[dict[str, str]] = Field(default_factory=list)


class ProviderAttemptBlocked(Exception):
    pass


def short_text(value: Any, limit: int = 900) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    if "<html" in text.lower()[:500]:
        status_match = re.search(r"\b(403|404|429|500|502|503|504)\b", text)
        status_hint = f" http {status_match.group(1)}" if status_match else ""
        return f"HTML response instead of API JSON{status_hint}; see diagnostics for redacted preview."
    return text if len(text) <= limit else text[:limit] + "..."


SENSITIVE_KEY_RE = re.compile(r"(?i)(token|authorization|cookie|password|secret|access|proxy|key)")
JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
PROXY_CRED_RE = re.compile(r"([a-z][a-z0-9+.-]*://)([^/@\s:]+):([^/@\s]+)@", re.I)
DIAGNOSTIC_JSON_VALUE_LIMIT = 2000
DIAGNOSTIC_JSON_LIST_LIMIT = 120
DIAGNOSTIC_JSON_DEPTH_LIMIT = 8
DIAGNOSTIC_JSON_TEXT_LIMIT = 200_000


def redact_value(value: Any, limit: int = 160) -> Any:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    text = str(value)
    if not text:
        return ""
    if "://" in text and "@" in text:
        parsed = urlsplit(text)
        return urlunsplit((parsed.scheme, parsed.netloc.split("@")[-1], parsed.path, "", ""))
    if len(text) <= 12:
        return "***"
    return f"{text[:4]}***{text[-4:]}"[:limit]


def safe_body_summary(body: Any) -> Any:
    if isinstance(body, dict):
        result: dict[str, Any] = {}
        for key, value in body.items():
            key_text = str(key)
            if SENSITIVE_KEY_RE.search(key_text):
                result[key_text] = redact_value(value)
            elif isinstance(value, (dict, list)):
                result[key_text] = safe_body_summary(value)
            else:
                result[key_text] = short_text(value, 160)
        return result
    if isinstance(body, list):
        return [safe_body_summary(item) for item in body[:20]]
    return short_text(body, 300)


def safe_json_capture(value: Any, depth: int = 0) -> Any:
    if depth > DIAGNOSTIC_JSON_DEPTH_LIMIT:
        return "[depth_limit]"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if SENSITIVE_KEY_RE.search(key_text):
                result[key_text] = redact_value(item, DIAGNOSTIC_JSON_VALUE_LIMIT)
            else:
                result[key_text] = safe_json_capture(item, depth + 1)
        return result
    if isinstance(value, list):
        items = [safe_json_capture(item, depth + 1) for item in value[:DIAGNOSTIC_JSON_LIST_LIMIT]]
        if len(value) > DIAGNOSTIC_JSON_LIST_LIMIT:
            items.append(f"[truncated {len(value) - DIAGNOSTIC_JSON_LIST_LIMIT} items]")
        return items
    if isinstance(value, str):
        return redact_diagnostic_text(value, DIAGNOSTIC_JSON_VALUE_LIMIT)
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return short_text(value, DIAGNOSTIC_JSON_VALUE_LIMIT)


def bounded_json_capture(payload: Any) -> Any:
    captured = safe_json_capture(payload)
    try:
        encoded = json.dumps(captured, ensure_ascii=False)
    except Exception:
        return short_text(captured, 5000)
    if len(encoded) <= DIAGNOSTIC_JSON_TEXT_LIMIT:
        return captured
    return {
        "_truncated": True,
        "_reason": f"redacted JSON exceeded {DIAGNOSTIC_JSON_TEXT_LIMIT} chars",
        "_top_level_keys": sorted(payload.keys())[:120] if isinstance(payload, dict) else [],
        "_preview": encoded[:DIAGNOSTIC_JSON_TEXT_LIMIT],
    }


def diagnostic_request_headers(session: Any, request_headers: dict[str, Any] | None = None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    try:
        merged.update({str(k).lower(): v for k, v in dict(getattr(session, "headers", {}) or {}).items()})
    except Exception:
        pass
    if request_headers:
        merged.update({str(k).lower(): v for k, v in request_headers.items()})
    return merged


def redact_diagnostic_text(text: str, limit: int = 500) -> str:
    preview = short_text(text, limit)
    preview = JWT_RE.sub("jwt***", preview)
    preview = PROXY_CRED_RE.sub(r"\1***:***@", preview)
    preview = re.sub(r"(?i)(access[_-]?token|authorization|cookie|secret|password)[\"'=:\s]+([^\"'\s,}]+)", r"\1=***", preview)
    return preview


def response_json_payload(response: Any) -> tuple[bool, Any]:
    try:
        return True, response.json() or {}
    except Exception:
        return False, None


def classify_response(response: Any, payload: Any, text: str) -> str:
    lower = (text or "").lower()
    if "<html" in lower[:1000]:
        return "html_instead_of_json"
    if "checkout_not_active_session" in lower:
        return "checkout_not_active_session"
    if response is not None and getattr(response, "status_code", 0) >= 400:
        return "http_error"
    if isinstance(payload, dict):
        result = str(payload.get("result") or "").lower()
        error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        error_code = str(error.get("code") or "").lower()
        error_message = str(error.get("message") or "").lower()
        if result == "blocked" or error_code == "blocked" or error_message.strip() == "blocked":
            return "blocked"
        amount = expected_amount(payload)
        if not is_acceptable_low_amount(amount) and any(key in payload for key in ("total_summary", "invoice", "line_items")):
            return "amount_above_threshold"
        if payload.get("error"):
            return "api_error"
        return "ok"
    return "schema_changed"


def extract_diag_fields(payload: Any, text: str) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if isinstance(payload, dict):
        for key in ("id", "checkout_session_id", "session_id", "result", "payment_method", "payment_method_id"):
            if payload.get(key):
                fields[key] = short_text(payload.get(key), 180)
        amount = expected_amount(payload)
        if amount != "0" or any(key in payload for key in ("total_summary", "invoice", "line_items")):
            fields["amount"] = amount
        redirect_url = extract_redirect_to_url(payload)
        if redirect_url:
            fields["redirect_url"] = short_text(redirect_url, 260)
        ba_url = extract_paypal_ba_approve_url(payload)
        if ba_url:
            fields["ba_approve_url"] = short_text(ba_url, 260)
    cs_match = re.search(r"cs_(?:live|test)_[A-Za-z0-9]+", text or "")
    if cs_match and "cs_id" not in fields:
        fields["cs_id"] = cs_match.group(0)
    pm_match = re.search(r"pm_[A-Za-z0-9]+", text or "")
    if pm_match and "pm_id" not in fields:
        fields["pm_id"] = pm_match.group(0)
    ba_match = PAYPAL_BA_TOKEN_RE.search(text or "")
    if ba_match:
        fields["ba_token"] = ba_match.group("token")
    return fields


def record_diagnostic(
    req: LongLinkRequest,
    stage: str,
    response: Any,
    *,
    request_body: Any = None,
    request_headers: Any = None,
    proxy_stage: str = "",
    strategy: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    if not getattr(req, "diagnostic_enabled", False):
        return
    url = str(getattr(response, "url", "") or "")
    parsed = urlsplit(url)
    text = str(getattr(response, "text", "") or "")
    is_json, payload = response_json_payload(response)
    headers = getattr(response, "headers", {}) or {}
    record = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "stage": stage,
        "strategy": strategy or getattr(req, "diagnostic_strategy", ""),
        "proxy_stage": proxy_stage,
        "url": {"host": parsed.netloc, "path": parsed.path},
        "status_code": int(getattr(response, "status_code", 0) or 0),
        "content_type": str(headers.get("content-type") or headers.get("Content-Type") or ""),
        "is_json": is_json,
        "classification": classify_response(response, payload, text),
        "request_body": safe_body_summary(request_body),
        "request_headers": safe_body_summary(request_headers),
        "response_headers": safe_body_summary(dict(headers)),
        "response_keys": sorted(payload.keys())[:40] if isinstance(payload, dict) else [],
        "response_preview": redact_diagnostic_text(text, 500),
        "response_json": bounded_json_capture(payload) if is_json else None,
        "fields": extract_diag_fields(payload, text),
    }
    if extra:
        record["extra"] = safe_body_summary(extra)
    req.diagnostic_records.append(record)


def save_diagnostics(req: LongLinkRequest, job_id: str, final_status: str) -> str:
    if not getattr(req, "diagnostic_enabled", False):
        return ""
    DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
    path = DIAGNOSTICS_DIR / f"{job_id}.json"
    payload = {
        "job_id": job_id,
        "final_status": final_status,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "link_type": normalize_link_type(req.link_type),
        "proxy_chain": {
            "checkout": req.checkout_proxy_region,
            "provider": req.provider_proxy_region,
            "approve": req.approve_proxy_region,
            "strategy": req.proxy_chain_strategy,
        },
        "records": req.diagnostic_records,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def proxy_summary(proxy: str) -> str:
    value = str(proxy or "").strip()
    if not value:
        return "未设置"
    target = value if re.match(r"^[a-z][a-z0-9+.-]*://", value, flags=re.I) else f"http://{value}"
    parsed = urlsplit(target)
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    region = proxy_region_from_url(value) or "-"
    sid_match = re.search(r"sid-([^-:@]*)-t-", value)
    sid = sid_match.group(1) if sid_match else ""
    sid_text = f"sid-{sid}" if sid else "sid-"
    scheme = parsed.scheme or "http"
    return f"{region} / {sid_text} / {scheme}://{host}{port}"


def add_step(steps: list[dict[str, str]] | None, name: str, status: str = "info", detail: Any = "") -> None:
    if steps is None:
        return
    steps.append(
        {
            "time": time.strftime("%H:%M:%S"),
            "name": short_text(name, 120),
            "status": short_text(status, 20),
            "detail": short_text(detail),
        }
    )


JOBS_LOCK = threading.Lock()
LONG_LINK_JOBS: dict[str, dict[str, Any]] = {}


class JobStepList(list[dict[str, str]]):
    def __init__(self, job_id: str) -> None:
        super().__init__()
        self.job_id = job_id

    def append(self, item: dict[str, str]) -> None:
        super().append(item)
        with JOBS_LOCK:
            job = LONG_LINK_JOBS.get(self.job_id)
            if job is not None:
                job["steps"] = list(self)
                job["updated_at"] = time.time()


class StrategyStepList:
    def __init__(self, base: JobStepList, label: str) -> None:
        self.base = base
        self.label = label

    def append(self, item: dict[str, str]) -> None:
        copied = dict(item)
        copied["name"] = f"[{self.label}] {copied.get('name', '')}"
        self.base.append(copied)


def cleanup_old_jobs(max_age_seconds: int = 3600) -> None:
    cutoff = time.time() - max_age_seconds
    with JOBS_LOCK:
        for job_id, job in list(LONG_LINK_JOBS.items()):
            if float(job.get("updated_at") or job.get("started_at") or 0) < cutoff:
                LONG_LINK_JOBS.pop(job_id, None)


def job_snapshot(job_id: str) -> dict[str, Any]:
    with JOBS_LOCK:
        job = LONG_LINK_JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return {
            "job_id": job_id,
            "status": job.get("status", "unknown"),
            "steps": list(job.get("steps") or []),
            "result": job.get("result"),
            "error": job.get("error", ""),
            "status_code": job.get("status_code", 200),
            "diagnostic_url": job.get("diagnostic_url", ""),
        }


def mark_job(job_id: str, **updates: Any) -> None:
    with JOBS_LOCK:
        job = LONG_LINK_JOBS.get(job_id)
        if job is not None:
            job.update(updates)
            job["updated_at"] = time.time()


def new_session() -> Any:
    if CurlCffiSession is not None:
        return CurlCffiSession(impersonate="chrome136")
    return requests.Session()


def is_711_proxy(proxy: str) -> bool:
    value = str(proxy or "").strip()
    if not value:
        return False
    target = value if re.match(r"^[a-z][a-z0-9+.-]*://", value, flags=re.I) else f"socks5h://{value}"
    try:
        parsed = urlsplit(target)
    except Exception:
        return "711proxy.com" in value.lower()
    return (parsed.hostname or "").lower().endswith("711proxy.com")


def proxy_711_region(proxy: str) -> str:
    value = str(proxy or "")
    if "region-JP" in value:
        return "JP"
    if "region-US" in value:
        return "US"
    return "GLOBAL"


def refresh_711_proxy(proxy_or_region: str) -> bool:
    region = str(proxy_or_region or "").strip().upper()
    if region not in PROXY_711_REFRESH_URLS:
        region = proxy_711_region(proxy_or_region)
    url = PROXY_711_REFRESH_URLS.get(region)
    if not url:
        return False
    try:
        response = requests.get(url, timeout=12)
        return response.status_code < 400
    except Exception:
        return False


def proxy_with_fresh_sid(proxy: str) -> str:
    proxy = str(proxy or "").strip()
    if not proxy:
        return ""
    if is_711_proxy(proxy):
        refresh_711_proxy(proxy)
        return proxy
    sid = uuid.uuid4().hex[:8]
    return re.sub(r"sid-[^-:@]*-t-", f"sid-{sid}-t-", proxy, count=1)


def normalize_payment_proxy_url(proxy: str) -> str:
    proxy = str(proxy or "").strip()
    if not proxy:
        return ""
    default_scheme = "http" if is_711_proxy(proxy) else "socks5h"
    return normalize_proxy_url(proxy, default_auth_scheme=default_scheme)


def stripe_browser_id() -> str:
    return f"{uuid.uuid4()}{uuid.uuid4().hex[:8]}"


def is_loopback_proxy(proxy: str) -> bool:
    value = str(proxy or "").strip()
    if not value:
        return False
    target = value if re.match(r"^[a-z][a-z0-9+.-]*://", value, flags=re.I) else f"http://{value}"
    host = (urlsplit(target).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"} or host.startswith("127.")


def prepare_attempt_proxy(req: LongLinkRequest, original_proxy: str) -> bool:
    original_proxy = str(original_proxy or "").strip()
    if normalize_link_type(req.link_type) in {"paypal", "gopay", "ideal"} and is_loopback_proxy(original_proxy):
        original_proxy = ""
    if original_proxy:
        req.proxy = normalize_payment_proxy_url(
            proxy_with_fresh_sid(proxy_with_region_override(original_proxy, req.checkout_proxy_region))
        )
        return True
    req.proxy = normalize_payment_proxy_url(
        proxy_with_fresh_sid(proxy_with_region_override(DEFAULT_PROXY, req.checkout_proxy_region))
    )
    return False


def proxy_preflight_attempt_limit(req: Any) -> int:
    try:
        attempts = int(getattr(req, "proxy_preflight_attempts", 5) or 5)
    except Exception:
        attempts = 5
    return max(1, min(100, attempts))


def prepare_request_proxy(req: LongLinkRequest) -> bool:
    original_proxy = str(req.proxy or "").strip()
    if normalize_link_type(req.link_type) in {"paypal", "gopay", "ideal"} and is_loopback_proxy(original_proxy):
        original_proxy = ""
    if not original_proxy:
        return prepare_attempt_proxy(req, "")

    attempts = proxy_preflight_attempt_limit(req)
    errors: list[str] = []
    for _attempt in range(1, attempts + 1):
        req.proxy = normalize_payment_proxy_url(
            proxy_with_fresh_sid(proxy_with_region_override(original_proxy, req.checkout_proxy_region))
        )
        ok, message = proxy_runtime.preflight_payment_proxy_url(req.proxy)
        if ok:
            auth_ok, auth_message = proxy_runtime.preflight_chatgpt_authenticated_proxy_url(req.proxy, req.access_token)
            if auth_ok:
                return True
            auth_text = str(auth_message or "unknown")
            if "token_" in auth_text.lower() or "authentication token" in auth_text.lower():
                raise HTTPException(status_code=502, detail=f"认证接口预检失败: {auth_message}")
            errors.append(auth_text)
            continue
        errors.append(str(message or "unknown"))
    raise HTTPException(status_code=502, detail=f"代理预检失败: {'; '.join(errors[-attempts:])}")


def effective_default_proxy(proxy: str = "") -> str:
    return str(proxy or "").strip() or DEFAULT_PROXY


def set_proxy_url(session: Any, proxy: str) -> None:
    proxy = normalize_payment_proxy_url(proxy)
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}


def set_proxy(session: Any, proxy: str) -> None:
    set_proxy_url(session, effective_default_proxy(proxy))


def proxy_for_region(proxy: str, region: str) -> str:
    proxy = str(proxy or "").strip()
    region = str(region or "").strip().upper()
    if proxy and region and "region-" in proxy:
        proxy = re.sub(r"region-[A-Za-z]{2}", f"region-{region}", proxy)
        if region != "JP":
            proxy = re.sub(r"-st-[^-:@]+(?=-sid-)", "", proxy)
        return proxy
    if is_711_proxy(proxy):
        return proxy
    return proxy


def proxy_region_from_url(proxy: str) -> str:
    proxy_text = str(proxy or "")
    if is_711_proxy(proxy_text):
        if "region-JP" in proxy_text:
            return "JP"
        if "region-US" in proxy_text:
            return "US"
        return "GLOBAL"
    match = re.search(r"region-([A-Za-z]{2})", str(proxy or ""))
    return match.group(1).upper() if match else ""


def normalize_proxy_region(region: str) -> str:
    value = str(region or "").strip().upper()
    if value and re.fullmatch(r"[A-Z]{2}", value):
        return value
    return ""


def use_same_provider_proxy(value: str) -> bool:
    return str(value or "").strip().lower() in {
        "same",
        "none",
        "off",
        "no",
        "false",
        "0",
        "不切换",
        "不使用",
    }


def proxy_with_region_override(proxy: str, region: str) -> str:
    normalized = normalize_proxy_region(region)
    return proxy_for_region(proxy, normalized) if normalized else str(proxy or "").strip()


def proxy_failure_hint(proxy: str) -> str:
    try:
        session = new_session()
        session.headers.update({"User-Agent": DEFAULT_USER_AGENT, "Accept": "text/plain,*/*"})
        set_proxy_url(session, proxy)
        response = session.get("http://api.ipify.org", timeout=10)
        text = short_text(response.text, 180)
        if response.status_code >= 400 or "auth failed" in text.lower() or "forbidden" in text.lower():
            return f"proxy http probe {response.status_code}: {text}"
    except Exception as exc:
        return f"proxy http probe failed: {short_text(exc, 180)}"
    return ""


def probe_proxy(proxy: str, expected_region: str, stage: str) -> dict[str, Any]:
    proxy = str(proxy or "").strip()
    expected_region = normalize_proxy_region(expected_region) or proxy_region_from_url(proxy)
    if not proxy:
        return {
            "stage": stage,
            "ok": False,
            "match": False,
            "expected_region": expected_region,
            "actual_region": "",
            "ip": "",
            "error": "proxy is empty",
        }

    session = new_session()
    session.headers.update({"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json,text/plain,*/*"})
    set_proxy_url(session, proxy)
    endpoints = (
        "https://api.myip.com",
        "https://ipwho.is/",
        "https://ipapi.co/json/",
    )
    last_error = ""
    for url in endpoints:
        try:
            response = session.get(url, timeout=DEFAULT_TIMEOUT)
            if response.status_code >= 400:
                last_error = f"{url} http {response.status_code}: {response.text[:120]}"
                continue
            try:
                data = response.json() or {}
            except Exception:
                last_error = f"{url} bad json: {response.text[:120]}"
                continue
            actual_region = str(
                data.get("cc")
                or data.get("country_code")
                or data.get("countryCode")
                or data.get("country")
                or ""
            ).upper()
            ip = str(data.get("ip") or data.get("query") or "").strip()
            if actual_region:
                return {
                    "stage": stage,
                    "ok": True,
                    "match": bool(expected_region and actual_region == expected_region),
                    "expected_region": expected_region,
                    "actual_region": actual_region,
                    "ip": ip,
                    "error": "",
                }
            last_error = f"{url} missing country code"
        except Exception as exc:
            last_error = str(exc)

    if "CONNECT" in last_error or "403" in last_error or "407" in last_error:
        hint = proxy_failure_hint(proxy)
        if hint:
            last_error = f"{last_error} | {hint}"

    return {
        "stage": stage,
        "ok": False,
        "match": False,
        "expected_region": expected_region,
        "actual_region": "",
        "ip": "",
        "error": last_error,
    }


def ensure_proxy_region(
    proxy: str,
    expected_region: str,
    stage: str,
    steps: list[dict[str, str]] | None = None,
    max_checks: int | None = None,
) -> str:
    proxy = str(proxy or "").strip()
    expected_region = normalize_proxy_region(expected_region) or proxy_region_from_url(proxy)
    if not proxy or not expected_region:
        return proxy

    checks = max(1, int(max_checks or PROXY_REGION_CHECK_ATTEMPTS or 1))
    candidate = proxy
    last_candidate = proxy
    last_detail = ""
    for index in range(1, checks + 1):
        result = probe_proxy(candidate, expected_region, stage)
        last_candidate = candidate
        ok = bool(result.get("ok") and result.get("match"))
        actual = str(result.get("actual_region") or "-")
        ip = str(result.get("ip") or "-")
        error = str(result.get("error") or "")
        detail = f"第 {index}/{checks} 次：期望 {expected_region}，实际 {actual}，IP {ip}"
        if error:
            detail += f"，错误 {error[:160]}"
        add_step(steps, f"{stage} 代理出口检测", "ok" if ok else "warn", detail)
        if ok:
            return candidate
        last_detail = detail
        candidate = proxy_with_fresh_sid(proxy)

    add_step(steps, f"{stage} 代理出口检测", "warn", f"未拿到匹配出口，继续使用最后一次代理。{last_detail}")
    return last_candidate


def provider_stage_proxy(req: LongLinkRequest, use_explicit_proxy: bool | None = None) -> str:
    explicit = str(req.proxy or "").strip()
    if use_explicit_proxy is None:
        use_explicit_proxy = bool(explicit)
    provider_region = normalize_proxy_region(req.provider_proxy_region)
    if use_same_provider_proxy(req.provider_proxy_region):
        return explicit or DEFAULT_PROXY
    if explicit and use_explicit_proxy:
        if provider_region:
            return proxy_with_fresh_sid(proxy_for_region(explicit, provider_region))
        return explicit
    base_proxy = explicit or DEFAULT_PROXY
    if normalize_link_type(req.link_type) == "gopay":
        provider_proxy = GOPAY_PROVIDER_STAGE_PROXY or proxy_for_region(base_proxy, "ID")
        return proxy_with_fresh_sid(proxy_for_region(provider_proxy, provider_region) if provider_region else provider_proxy)
    if normalize_link_type(req.link_type) == "ideal":
        provider_proxy = proxy_for_region(base_proxy, "NL")
        return proxy_with_fresh_sid(proxy_for_region(provider_proxy, provider_region) if provider_region else provider_proxy)
    if PROVIDER_STAGE_PROXY:
        provider_proxy = PROVIDER_STAGE_PROXY
    else:
        provider_proxy = proxy_for_region(base_proxy, "US")
    return proxy_with_fresh_sid(proxy_for_region(provider_proxy, provider_region) if provider_region else provider_proxy)


def apply_provider_proxy(chatgpt: Any, proxy: str) -> None:
    set_proxy_url(chatgpt, proxy)


def currency_for_country(country: str) -> str:
    return COUNTRY_CURRENCY.get(str(country or "").upper(), "USD")


def normalize_country(country: str) -> str:
    country = str(country or "").strip().upper()
    return country if country in COUNTRY_CURRENCY else "US"


def normalize_link_type(link_type: str) -> str:
    value = str(link_type or "hosted").strip().lower()
    aliases = {
        "payment": "hosted",
        "pay": "hosted",
        "long": "hosted",
        "pp": "paypal",
        "paypal": "paypal",
        "ideal": "ideal",
        "iDEAL": "ideal",
        "gopy": "gopay",
        "gopay": "gopay",
    }
    return aliases.get(value, "hosted")


def effective_country(req: LongLinkRequest) -> str:
    link_type = normalize_link_type(req.link_type)
    if link_type == "paypal":
        return "US"
    if link_type == "gopay":
        return "ID"
    if link_type == "ideal":
        return "NL"
    return normalize_country(req.billing_country)


def browser_timezone_for_request(req: LongLinkRequest) -> str:
    link_type = normalize_link_type(req.link_type)
    candidates: list[str] = []
    if link_type == "paypal":
        candidates = [req.provider_proxy_region, req.checkout_proxy_region, req.approve_proxy_region, "US"]
    elif link_type == "gopay":
        candidates = [req.provider_proxy_region, req.checkout_proxy_region, "ID"]
    elif link_type == "ideal":
        candidates = [req.provider_proxy_region, req.checkout_proxy_region, "NL"]
    else:
        candidates = [req.checkout_proxy_region, effective_country(req)]
    for candidate in candidates:
        region = normalize_proxy_region(candidate)
        if region and region in COUNTRY_TIMEZONE:
            return COUNTRY_TIMEZONE[region]
    return COUNTRY_TIMEZONE.get(effective_country(req), "America/New_York")


def browser_region_for_request(req: LongLinkRequest) -> str:
    link_type = normalize_link_type(req.link_type)
    candidates: list[str]
    if link_type == "paypal":
        candidates = [req.provider_proxy_region, req.checkout_proxy_region, req.approve_proxy_region, "US"]
    elif link_type == "gopay":
        candidates = [req.provider_proxy_region, req.checkout_proxy_region, "ID"]
    elif link_type == "ideal":
        candidates = [req.provider_proxy_region, req.checkout_proxy_region, "NL"]
    else:
        candidates = [req.checkout_proxy_region, effective_country(req)]
    for candidate in candidates:
        region = normalize_proxy_region(candidate)
        if region:
            return region
    return effective_country(req)


def browser_profile_for_request(req: LongLinkRequest) -> dict[str, str]:
    requested_locale = str(req.payment_locale or "").strip()
    browser_locale, elements_locale = locale_parts(requested_locale)
    region = browser_region_for_request(req)
    if not requested_locale or requested_locale.lower() == "auto":
        browser_locale, elements_locale = REGION_LOCALE.get(region, LOCALE_MAP["en"])
    return {
        "region": region,
        "browser_locale": browser_locale,
        "elements_locale": elements_locale,
        "accept_language": f"{browser_locale},{browser_locale.split('-')[0]};q=0.9,en;q=0.8",
        "timezone": browser_timezone_for_request(req),
        "client_fingerprint": normalize_client_fingerprint(req.client_fingerprint),
    }


def locale_parts(locale: str) -> tuple[str, str]:
    return LOCALE_MAP.get(str(locale or "").strip(), LOCALE_MAP["en"])


def extract_jwt_token(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = JWT_PATTERN.search(text.removeprefix("Bearer ").strip())
    return match.group(1) if match else ""


def find_token(value: Any) -> str:
    if isinstance(value, str):
        return extract_jwt_token(value)
    if isinstance(value, dict):
        for key in ("accessToken", "access_token", "token"):
            token = extract_jwt_token(value.get(key)) or str(value.get(key) or "").strip()
            if token:
                return token
        for item in value.values():
            token = find_token(item)
            if token:
                return token
    if isinstance(value, list):
        for item in value:
            token = find_token(item)
            if token:
                return token
    return ""


def is_latin1_header_value(value: str) -> bool:
    try:
        str(value or "").encode("latin-1")
        return True
    except UnicodeEncodeError:
        return False


def safe_user_agent(value: str) -> str:
    user_agent = str(value or "").strip() or DEFAULT_USER_AGENT
    return user_agent if is_latin1_header_value(user_agent) else DEFAULT_USER_AGENT


def normalize_client_fingerprint(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    if normalized in {"apple", "safari", "apple-safari", "mac-safari", "ios", "iphone"}:
        return "apple-safari"
    return "chrome"


def default_user_agent_for_request(req: LongLinkRequest) -> str:
    if str(req.user_agent or "").strip():
        return safe_user_agent(req.user_agent)
    if normalize_client_fingerprint(req.client_fingerprint) == "apple-safari":
        return APPLE_SAFARI_USER_AGENT
    return DEFAULT_USER_AGENT


def client_hint_headers(req: LongLinkRequest) -> dict[str, str]:
    if normalize_client_fingerprint(req.client_fingerprint) == "apple-safari":
        return {
            "sec-ch-ua": '"Safari";v="17", "Not.A/Brand";v="8"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
        }
    return {
        "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }


def normalize_access_token(raw: str) -> str:
    token = str(raw or "").strip()
    if not token:
        return ""
    extracted = extract_jwt_token(token)
    if extracted:
        return extracted
    if token.startswith("{") or token.startswith("["):
        try:
            return find_token(json.loads(token))
        except json.JSONDecodeError:
            return ""
    return token if is_latin1_header_value(token) else ""


def decode_jwt_payload(access_token: str) -> dict[str, Any]:
    token = normalize_access_token(access_token)
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    try:
        padded = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
        return json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")) or {}
    except Exception:
        return {}


def account_email_from_token(access_token: str) -> str:
    payload = decode_jwt_payload(access_token)
    profile = payload.get("https://api.openai.com/profile")
    candidates: list[Any] = []
    if isinstance(profile, dict):
        candidates.extend([profile.get("email"), profile.get("email_address")])
    candidates.extend([payload.get("email"), payload.get("preferred_username")])
    for candidate in candidates:
        email = str(candidate or "").strip()
        if re.fullmatch(r"[^@\s]{1,128}@[^@\s]{1,190}\.[^@\s]{2,32}", email):
            return email[:254]
    return ""


def cleanup_account_for_non_zero_amount(req: LongLinkRequest, reason: Any, steps: JobStepList | None = None) -> dict[str, Any]:
    email = account_email_from_token(req.access_token)
    cleanup = {
        "email": email,
        "dashboard_account_deleted": False,
        "auth_session_deleted": False,
        "legacy_account_disabled": False,
        "account_deleted": False,
    }
    if not email:
        if steps is not None:
            add_step(steps, "账号池处理", "warn", "金额非 0，但 accessToken 中未解析到邮箱；按策略不删除账号。")
        return cleanup
    if steps is not None:
        add_step(steps, "账号池处理", "warn", f"金额非 0，账号保留：{masked_email(email)} cleanup={cleanup}")
    return cleanup


def apply_non_zero_amount_cleanup(req: LongLinkRequest, detail: str, steps: JobStepList | None = None) -> tuple[str, dict[str, Any] | None]:
    if not is_non_zero_amount_error(detail):
        return detail, None
    cleanup = cleanup_account_for_non_zero_amount(req, detail, steps)
    if cleanup.get("email"):
        return f"金额非 0，账号保留：{detail}", cleanup
    return f"金额非 0，账号保留（未解析到邮箱）：{detail}", cleanup


def masked_email(email: str) -> str:
    value = str(email or "").strip()
    if "@" not in value:
        return ""
    local, domain = value.split("@", 1)
    if len(local) <= 2:
        masked_local = local[:1] + "*"
    else:
        masked_local = local[:2] + "***" + local[-1:]
    return f"{masked_local}@{domain}"


def extract_processor_entity(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    direct = data.get("processor_entity") or data.get("processorEntity")
    if direct:
        return str(direct).strip()
    for key in ("checkout_session", "session", "checkout", "data"):
        nested = data.get(key)
        if isinstance(nested, dict):
            found = extract_processor_entity(nested)
            if found:
                return found
    return ""


def build_chatgpt_session(req: LongLinkRequest) -> Any:
    access_token = normalize_access_token(req.access_token)
    if not access_token:
        raise HTTPException(status_code=400, detail="Access Token 未识别：请粘贴纯 JWT，或粘贴包含 accessToken/access_token/token 的 session JSON。")
    if not is_latin1_header_value(access_token):
        raise HTTPException(status_code=400, detail="Access Token 包含非 Header 字符，请重新复制纯 JWT。")

    requested_device_id = req.device_id.strip()
    device_id = requested_device_id if requested_device_id and is_latin1_header_value(requested_device_id) else str(uuid.uuid4())
    if not requested_device_id:
        req.device_id = device_id
    user_agent = default_user_agent_for_request(req)
    browser_profile = browser_profile_for_request(req)
    browser_profile["client_fingerprint"] = normalize_client_fingerprint(req.client_fingerprint)
    session = new_session()
    headers = {
        "User-Agent": user_agent,
        "Accept": "*/*",
        "Accept-Language": browser_profile["accept_language"],
        "Authorization": f"Bearer {access_token}",
        "Origin": "https://chatgpt.com",
        "Referer": "https://chatgpt.com/",
        "Content-Type": "application/json",
        "oai-device-id": device_id,
        "oai-language": browser_profile["browser_locale"],
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "Cookie": f"oai-did={device_id}",
    }
    headers.update(client_hint_headers(req))
    session.headers.update(headers)
    set_proxy(session, req.proxy)
    return session


def create_checkout(req: LongLinkRequest, chatgpt_session: Any | None = None) -> dict[str, Any]:
    billing_country = effective_country(req)
    currency = currency_for_country(billing_country)
    checkout_ui_mode = (req.checkout_ui_mode or "hosted").strip() or "hosted"
    link_type = normalize_link_type(req.link_type)
    browser_profile = browser_profile_for_request(req)
    # plan_name strings reverse-engineered from chatgpt.com front-end js.
    # `chatgptgoplan` is the only plan whose cs actually produces a real
    # payment_intent+next_action.redirect_to_url for GoPay (i.e. the only
    # plan whose cs.payment_object_status advances to "requires_action"
    # after ChatGPT manual_approval).
    # CAVEAT: For this account, the GoPay-specific promo `go-1-month-free`
    # is silently dropped by ChatGPT backend so due remains IDR 75,000.
    # The Plus-side `plus-1-month-free` promo works for the Plus path but
    # creates a SetupIntent that stripe declines for GoPay PMs.
    if link_type == "gopay":
        plan_name = "chatgptgoplan"
        promo_campaign_id = "go-1-month-free"
    else:
        plan_name = "chatgptplusplan"
        promo_campaign_id = "plus-1-month-free"
    body = {
        "entry_point": "all_plans_pricing_modal",
        "plan_name": plan_name,
        "billing_details": {
            "country": billing_country,
            "currency": currency,
        },
        "checkout_ui_mode": checkout_ui_mode,
    }
    if link_type != "ideal":
        body["promo_campaign"] = {
            "promo_campaign_id": promo_campaign_id,
            "is_coupon_from_query_param": False,
        }
    headers = {
        "referer": "https://chatgpt.com/",
        "x-openai-target-path": "/backend-api/payments/checkout",
        "x-openai-target-route": "/backend-api/payments/checkout",
    }
    chatgpt = chatgpt_session or build_chatgpt_session(req)
    response = chatgpt.post(
        "https://chatgpt.com/backend-api/payments/checkout",
        json=body,
        headers=headers,
        timeout=DEFAULT_TIMEOUT,
    )
    record_diagnostic(req, "chatgpt_checkout", response, request_body=body, request_headers=diagnostic_request_headers(chatgpt, headers), proxy_stage="checkout", extra={"browser_profile": browser_profile})
    if response.status_code >= 400:
        body_text = response.text[:500] if response.text else ""
        if "cannot combine currencies" in body_text.lower():
            raise HTTPException(
                status_code=409,
                detail=(
                    "GoPay needs an IDR checkout, but this Stripe customer already has active USD "
                    "checkout/subscription state. Use a fresh account/customer or wait for the USD "
                    "checkout state to expire; this cannot be bypassed in code."
                ),
            )
        raise HTTPException(
            status_code=response.status_code,
            detail=f"checkout create failed: {body_text}",
        )

    try:
        data = response.json() or {}
    except Exception:
        raise HTTPException(status_code=502, detail=short_text(response.text)) from None
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail=f"checkout response was not a JSON object: {short_text(data)}")
    cs_id = data.get("checkout_session_id") or data.get("session_id") or data.get("id")
    if not cs_id or not str(cs_id).startswith("cs_"):
        raise HTTPException(status_code=502, detail=f"checkout response missing cs_id: {data}")
    return {
        "cs_id": str(cs_id),
        "processor_entity": extract_processor_entity(data),
        "publishable_key": str(data.get("publishable_key") or ""),
        "billing_country": billing_country,
        "currency": currency,
    }


def checkout_page_url(checkout: dict[str, Any], country: str = "NL") -> str:
    processor = processor_entity_for_country(country, str(checkout.get("processor_entity") or ""))
    return f"https://chatgpt.com/checkout/{processor}/{checkout['cs_id']}"


def update_checkout_promotion(
    chatgpt: Any,
    checkout: dict[str, Any],
    req: LongLinkRequest,
    steps: list[dict[str, str]] | None = None,
) -> None:
    _ = chatgpt
    update_req = req.model_copy()
    update_req.checkout_proxy_region = "VN"
    update_req.proxy = normalize_payment_proxy_url(proxy_with_fresh_sid(proxy_for_region(req.proxy, "VN")))
    update_req.proxy = ensure_proxy_region(update_req.proxy, "VN", "checkout/update promo", steps)
    update_chatgpt = build_chatgpt_session(update_req)
    body: dict[str, Any] = {
        "checkout_session_id": checkout["cs_id"],
        "processor_entity": processor_entity_for_country("NL", str(checkout.get("processor_entity") or "")),
        "plan_name": "chatgptplusplan",
        "price_interval": "month",
        "seat_quantity": 1,
        "promo_campaign": {
            "promo_campaign_id": "plus-1-month-free",
            "is_coupon_from_query_param": False,
        },
    }
    url = "https://chatgpt.com/backend-api/payments/checkout/update"
    headers = {
        "Referer": checkout_page_url(checkout, "NL"),
        "x-openai-target-path": "/backend-api/payments/checkout/update",
        "x-openai-target-route": "/backend-api/payments/checkout/update",
    }
    response = update_chatgpt.post(url, json=body, headers=headers, timeout=DEFAULT_TIMEOUT)
    record_diagnostic(
        req,
        "chatgpt_checkout_update",
        response,
        request_body=body,
        request_headers=diagnostic_request_headers(update_chatgpt, headers),
        proxy_stage="checkout_update",
        extra={"cs_id": checkout["cs_id"], "promotion_region": "VN"},
    )
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=f"checkout/update failed: {short_text(response.text)}")
    try:
        payload = response.json() or {}
    except Exception:
        raise HTTPException(status_code=502, detail=short_text(response.text)) from None
    if isinstance(payload, dict) and payload.get("success") is False:
        raise HTTPException(status_code=502, detail=f"checkout/update rejected: {short_text(payload)}")
    add_step(steps, "iDEAL checkout/update promo", "ok", "VN checkout/update 已注入 plus-1-month-free")


def stripe_init(cs_id: str, req: LongLinkRequest, proxy_override: str = "") -> dict[str, Any]:
    stripe_pk = req.stripe_publishable_key.strip() or DEFAULT_STRIPE_PK
    browser_profile = browser_profile_for_request(req)
    browser_locale = browser_profile["browser_locale"]
    elements_locale = browser_profile["elements_locale"]
    browser_timezone = browser_profile["timezone"]
    stripe = new_session()
    stripe.headers.update(
        {
            "User-Agent": default_user_agent_for_request(req),
            "Accept-Language": browser_profile["accept_language"],
        }
    )
    if proxy_override:
        set_proxy_url(stripe, proxy_override)
    else:
        set_proxy(stripe, req.proxy)
    if normalize_link_type(req.link_type) == "paypal":
        body = {
            "key": stripe_pk,
            "eid": "NA",
            "browser_locale": browser_locale,
            "browser_timezone": browser_timezone,
            "redirect_type": "url",
        }
    else:
        body = {
            "browser_locale": browser_locale,
            "browser_timezone": browser_timezone,
            "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
            "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
            "elements_session_client[elements_init_source]": "custom_checkout",
            "elements_session_client[referrer_host]": "chatgpt.com",
            "elements_session_client[stripe_js_id]": str(uuid.uuid4()),
            "elements_session_client[locale]": elements_locale,
            "elements_session_client[is_aggregation_expected]": "false",
            "elements_options_client[saved_payment_method][enable_save]": "never",
            "elements_options_client[saved_payment_method][enable_redisplay]": "never",
            "key": stripe_pk,
            "_stripe_version": STRIPE_VERSION_FULL,
        }
    response = stripe.post(
        f"https://api.stripe.com/v1/payment_pages/{cs_id}/init",
        data=body,
        timeout=DEFAULT_TIMEOUT,
    )
    record_diagnostic(req, "stripe_payment_pages_init", response, request_body=body, proxy_stage="provider" if proxy_override else "checkout", extra={"cs_id": cs_id, "browser_profile": browser_profile})
    if response.status_code >= 400:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"stripe init failed: {response.text[:500]}",
        )
    return response.json() or {}


def stripe_init_gopay_checksum(stripe: Any, cs_id: str, stripe_pk: str, req: LongLinkRequest) -> str:
    browser_profile = browser_profile_for_request(req)
    browser_locale = browser_profile["browser_locale"]
    elements_locale = browser_profile["elements_locale"]
    browser_timezone = browser_profile["timezone"]
    body = {
        "browser_locale": browser_locale,
        "browser_timezone": browser_timezone,
        "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
        "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
        "elements_session_client[elements_init_source]": "custom_checkout",
        "elements_session_client[referrer_host]": "chatgpt.com",
        "elements_session_client[stripe_js_id]": str(uuid.uuid4()),
        "elements_session_client[locale]": elements_locale,
        "elements_session_client[is_aggregation_expected]": "false",
        "key": stripe_pk,
    }
    response = stripe.post(
        f"https://api.stripe.com/v1/payment_pages/{cs_id}/init",
        data=body,
        timeout=DEFAULT_TIMEOUT,
    )
    record_diagnostic(req, "stripe_gopay_init_checksum", response, request_body=body, proxy_stage="provider", extra={"cs_id": cs_id, "browser_profile": browser_profile})
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=f"stripe gopay init failed: {response.text[:500]}")
    checksum = str((response.json() or {}).get("init_checksum") or "").strip()
    if not checksum:
        raise HTTPException(status_code=502, detail=f"stripe gopay init missing init_checksum: {response.text[:300]}")
    return checksum


def to_openai_pay_url(stripe_hosted_url: str) -> str:
    url = str(stripe_hosted_url or "").strip()
    if not url:
        return ""
    if url.startswith("https://checkout.stripe.com"):
        return "https://pay.openai.com" + url[len("https://checkout.stripe.com") :]

    parsed = urlsplit(url)
    if parsed.netloc.lower() == "checkout.stripe.com":
        return urlunsplit((parsed.scheme or "https", "pay.openai.com", parsed.path, parsed.query, parsed.fragment))
    return url


def processor_entity_for_country(country: str, processor_entity: str = "") -> str:
    entity = str(processor_entity or "").strip()
    if entity:
        return entity
    return "openai_llc" if str(country or "").upper() == "US" else "openai_ie"


def chatgpt_success_return_url(cs_id: str, country: str, processor_entity: str = "") -> str:
    entity = processor_entity_for_country(country, processor_entity)
    return f"https://chatgpt.com/checkout/verify?stripe_session_id={cs_id}&processor_entity={entity}&plan_type=plus"


def stripe_checkout_long_url(cs_id: str, country: str, processor_entity: str = "") -> str:
    return (
        f"https://checkout.stripe.com/c/pay/{cs_id}"
        f"?returned_from_redirect=true&ui_mode=custom&return_url="
        f"{quote(chatgpt_success_return_url(cs_id, country, processor_entity), safe='')}"
    )


def stripe_confirm_return_url(cs_id: str, checkout: dict[str, Any], stripe_hosted_url: str) -> str:
    hosted_url = to_openai_pay_url(stripe_hosted_url) or stripe_checkout_long_url(
        cs_id,
        checkout["billing_country"],
        checkout.get("processor_entity", ""),
    )
    if "pay.openai.com/" in hosted_url or "checkout.stripe.com/" in hosted_url:
        parsed = urlsplit(hosted_url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query.setdefault(
            "success_return_url",
            chatgpt_success_return_url(
                cs_id,
                checkout["billing_country"],
                checkout.get("processor_entity", ""),
            ),
        )
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))
    return hosted_url


def paypal_confirm_return_url(cs_id: str, checkout: dict[str, Any], stripe_hosted_url: str) -> str:
    hosted_url = to_openai_pay_url(stripe_hosted_url) or stripe_checkout_long_url(
        cs_id,
        checkout["billing_country"],
        checkout.get("processor_entity", ""),
    )
    parsed = urlsplit(hosted_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["redirect_pm_type"] = "paypal"
    query["lid"] = str(uuid.uuid4())
    query["ui_mode"] = "custom"
    netloc = parsed.netloc or "pay.openai.com"
    return urlunsplit((parsed.scheme or "https", netloc, parsed.path, urlencode(query), parsed.fragment))


def expected_amount(init_payload: Any) -> str:
    if not isinstance(init_payload, dict):
        return "0"
    total_summary = init_payload.get("total_summary")
    if isinstance(total_summary, dict) and total_summary.get("due") is not None:
        return str(total_summary.get("due"))
    invoice = init_payload.get("invoice")
    if isinstance(invoice, dict) and invoice.get("amount_due") is not None:
        return str(invoice.get("amount_due"))
    line_items = init_payload.get("line_items")
    if isinstance(line_items, list):
        total = 0
        found = False
        for item in line_items:
            if isinstance(item, dict) and item.get("amount") is not None:
                try:
                    total += int(item.get("amount") or 0)
                    found = True
                except Exception:
                    pass
        if found:
            return str(total)
    return "0"


MAX_ACCEPTABLE_MINOR_AMOUNT = int(os.getenv("OPENAI_PAY_MAX_ACCEPTABLE_MINOR_AMOUNT", "50") or "50")


def is_zero_amount(value: Any) -> bool:
    text = str(value if value is not None else "").strip()
    if not text:
        return False
    try:
        return float(text) == 0.0
    except Exception:
        return text in {"0", "0.0", "0.00"}


def is_acceptable_low_amount(value: Any, max_minor_amount: int = MAX_ACCEPTABLE_MINOR_AMOUNT) -> bool:
    _ = max_minor_amount
    return is_zero_amount(value)


def amount_policy_text(value: Any) -> str:
    return f"amount={value}, allowed==0"


def payment_methods_for_payload(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    methods: list[str] = []
    for key in ("payment_method_types", "ordered_payment_method_types"):
        values = payload.get(key)
        if isinstance(values, list):
            methods.extend(str(item).strip().lower() for item in values if str(item).strip())
    return methods


def payment_payload_supports_method(payload: Any, payment_method_type: str) -> bool:
    methods = payment_methods_for_payload(payload)
    if not methods:
        return True
    return normalize_link_type(payment_method_type) in methods


def payment_methods_policy_text(payload: Any, payment_method_type: str) -> str:
    methods = payment_methods_for_payload(payload)
    return f"required={normalize_link_type(payment_method_type)}, methods={methods or 'unknown'}"


def display_amount(value: Any, currency: str = "") -> str:
    text = str(value if value is not None else "").strip()
    if not text:
        return ""
    code = str(currency or "").upper()
    symbols = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}
    zero_decimal = {"JPY", "KRW", "IDR"}
    try:
        raw = int(float(text))
    except Exception:
        return f"{text} {code}".strip()
    if code in zero_decimal:
        amount_text = str(raw)
    else:
        amount_text = f"{raw / 100:.2f}"
    symbol = symbols.get(code)
    return f"{symbol}{amount_text}" if symbol else f"{amount_text} {code}".strip()


def stripe_context(cs_id: str, init_payload: dict[str, Any], req: LongLinkRequest) -> dict[str, Any]:
    browser_profile = browser_profile_for_request(req)
    elements_locale = browser_profile["elements_locale"]
    paypal_mode = normalize_link_type(req.link_type) == "paypal"
    return {
        "stripe_js_id": str(uuid.uuid4()),
        "client_session_id": str(uuid.uuid4()),
        "guid": stripe_browser_id(),
        "muid": stripe_browser_id(),
        "sid": stripe_browser_id(),
        "elements_session_id": f"elements_session_{uuid.uuid4().hex[:11]}",
        "elements_session_config_id": str(init_payload.get("config_id") or uuid.uuid4()),
        "config_id": init_payload.get("config_id") or "",
        "init_checksum": init_payload.get("init_checksum") or "",
        "currency": str(init_payload.get("currency") or currency_for_country(effective_country(req))).lower(),
        "checkout_amount": expected_amount(init_payload),
        "locale": elements_locale,
        "runtime_version": PAYPAL_STRIPE_RUNTIME_VERSION if paypal_mode else DEFAULT_STRIPE_RUNTIME_VERSION,
        "stripe_version": PAYPAL_STRIPE_VERSION if paypal_mode else STRIPE_VERSION_FULL,
    }


def billing_for_link_type(link_type: str, account_email: str = "", paypal_country: str = "JP") -> dict[str, str]:
    normalized = normalize_link_type(link_type)
    if normalized == "paypal":
        if str(paypal_country or "").upper() == "US":
            first_name, last_name = random.choice(US_BILLING_NAMES)
            line1, city, state, postal_code = random.choice(US_BILLING_STREETS)
            country = "US"
        else:
            first_name, last_name = random.choice(JAPAN_BILLING_NAMES)
            line1, city, state, postal_code = random.choice(JAPAN_BILLING_STREETS)
            country = "JP"
        suffix = random.randint(1000, 9999)
        return {
            "name": f"{first_name} {last_name}",
            "email": account_email or f"{first_name.lower()}.{last_name.lower()}{suffix}@example.com",
            "country": country,
            "line1": line1,
            "city": city,
            "state": state,
            "postal_code": postal_code,
        }
    if normalized == "gopay":
        first_name, last_name = random.choice(INDONESIA_BILLING_NAMES)
        line1, city, state, postal_code = random.choice(INDONESIA_BILLING_STREETS)
        suffix = random.randint(1000, 9999)
        return {
            "name": f"{first_name} {last_name}",
            "email": account_email or f"{first_name.lower()}.{last_name.lower()}{suffix}@example.com",
            "country": "ID",
            "line1": line1,
            "city": city,
            "state": state,
            "postal_code": postal_code,
        }
    if normalized == "ideal":
        first_name, last_name = random.choice(NETHERLANDS_BILLING_NAMES)
        line1, city, state, postal_code = random.choice(NETHERLANDS_BILLING_STREETS)
        suffix = random.randint(1000, 9999)
        return {
            "name": f"{first_name} {last_name}",
            "email": account_email or f"{first_name.lower()}.{last_name.lower()}{suffix}@example.com",
            "country": "NL",
            "line1": line1,
            "city": city,
            "state": state,
            "postal_code": postal_code,
        }
    first_name, last_name = random.choice(US_BILLING_NAMES)
    line1, city, state, postal_code = random.choice(US_BILLING_STREETS)
    suffix = random.randint(1000, 9999)
    return {
        "name": f"{first_name} {last_name}",
        "email": f"{first_name.lower()}.{last_name.lower()}{suffix}@example.com",
        "country": "US",
        "line1": line1,
        "city": city,
        "state": state,
        "postal_code": postal_code,
    }


def build_stripe_session(req: LongLinkRequest, proxy_override: str = "") -> Any:
    browser_profile = browser_profile_for_request(req)
    stripe = new_session()
    stripe.headers.update(
        {
            "User-Agent": default_user_agent_for_request(req),
            "Accept-Language": browser_profile["accept_language"],
        }
    )
    if proxy_override:
        set_proxy_url(stripe, proxy_override)
    else:
        set_proxy(stripe, req.proxy)
    return stripe


def stripe_create_payment_method(
    stripe: Any,
    req: LongLinkRequest,
    cs_id: str,
    stripe_pk: str,
    billing: dict[str, str],
    payment_method_type: str,
    ctx: dict[str, Any],
    strategy: dict[str, Any] | None = None,
) -> str:
    payment_method_type = normalize_link_type(payment_method_type)
    if payment_method_type == "gopay":
        body = {
            "billing_details[name]": billing.get("name") or "Budi Santoso",
            "billing_details[email]": billing.get("email") or "buyer@example.com",
            "billing_details[address][country]": billing.get("country") or "ID",
            "billing_details[address][line1]": billing.get("line1") or "Jl. Jend. Sudirman No. 1",
            "billing_details[address][city]": billing.get("city") or "Jakarta",
            "billing_details[address][postal_code]": billing.get("postal_code") or "10210",
            "billing_details[address][state]": billing.get("state") or "DKI Jakarta",
            "type": "gopay",
            "client_attribution_metadata[checkout_session_id]": cs_id,
            "key": stripe_pk,
        }
    elif payment_method_type == "ideal":
        body = {
            "billing_details[name]": billing.get("name") or "Jan de Vries",
            "billing_details[email]": billing.get("email") or "buyer@example.com",
            "billing_details[address][country]": billing.get("country") or "NL",
            "billing_details[address][line1]": billing.get("line1") or "Prinsengracht 263",
            "billing_details[address][city]": billing.get("city") or "Amsterdam",
            "billing_details[address][postal_code]": billing.get("postal_code") or "1016 GV",
            "type": "ideal",
            "client_attribution_metadata[checkout_session_id]": cs_id,
            "key": stripe_pk,
        }
    else:
        runtime_version = str(ctx.get("runtime_version") or DEFAULT_STRIPE_RUNTIME_VERSION)
        body = {
            "billing_details[email]": billing.get("email") or "buyer@example.com",
            "billing_details[address][country]": billing.get("country") or "US",
            "billing_details[address][line1]": billing.get("line1") or "3110 Sunset Boulevard",
            "billing_details[address][city]": billing.get("city") or "Los Angeles",
            "billing_details[address][postal_code]": billing.get("postal_code") or "90026",
            "billing_details[address][state]": billing.get("state") or "CA",
            "type": "paypal",
            "guid": str(ctx.get("guid") or stripe_browser_id()),
            "muid": str(ctx.get("muid") or stripe_browser_id()),
            "sid": str(ctx.get("sid") or stripe_browser_id()),
            "_stripe_version": str(ctx.get("stripe_version") or PAYPAL_STRIPE_VERSION),
            "key": stripe_pk,
            "payment_user_agent": f"stripe.js/{runtime_version}; stripe-js-v3/{runtime_version}; checkout",
            "client_attribution_metadata[client_session_id]": str(ctx.get("client_session_id") or ctx["stripe_js_id"]),
            "client_attribution_metadata[checkout_session_id]": cs_id,
            "client_attribution_metadata[merchant_integration_source]": "checkout",
            "client_attribution_metadata[merchant_integration_version]": "custom_checkout",
            "client_attribution_metadata[payment_method_selection_flow]": "automatic",
            "client_attribution_metadata[checkout_config_id]": ctx.get("config_id") or "",
        }
    response = stripe.post("https://api.stripe.com/v1/payment_methods", data=body, timeout=DEFAULT_TIMEOUT)
    record_diagnostic(
        req,
        "stripe_payment_methods",
        response,
        request_body=body,
        proxy_stage="provider",
        strategy=str(strategy.get("name") or "") if strategy else "",
        extra={"cs_id": cs_id, "billing_country": billing.get("country") or ""},
    )
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=f"stripe payment_methods failed: {response.text[:500]}")
    pm_id = str((response.json() or {}).get("id") or "")
    if not pm_id.startswith("pm_"):
        raise HTTPException(status_code=502, detail=f"stripe payment_methods bad response: {response.text[:300]}")
    return pm_id


def paypal_confirm_strategy(attempt: int) -> dict[str, Any]:
    # Strategy only controls submit shape. Billing country is bound to the
    # provider proxy exit later so request geography stays coherent.
    strategies = (
        {"name": "baseline", "inline": False, "email_mode": "account"},
        {"name": "inline", "inline": True, "email_mode": "account"},
    )
    return strategies[(max(1, int(attempt or 1)) - 1) % len(strategies)]


def paypal_billing_country_for_provider(req: LongLinkRequest, provider_proxy: str) -> str:
    provider_region = (
        normalize_proxy_region(req.provider_proxy_region)
        or proxy_region_from_url(provider_proxy)
        or normalize_proxy_region(req.checkout_proxy_region)
        or proxy_region_from_url(req.proxy)
        or "US"
    )
    return "US" if provider_region == "US" else "JP"


def add_paypal_billing_fields(body: dict[str, str], billing: dict[str, str], prefix: str) -> None:
    body[f"{prefix}[billing_details][name]"] = billing.get("name") or "John Doe"
    body[f"{prefix}[billing_details][email]"] = billing.get("email") or "buyer@example.com"
    body[f"{prefix}[billing_details][address][country]"] = billing.get("country") or "US"
    body[f"{prefix}[billing_details][address][line1]"] = billing.get("line1") or "3110 Sunset Boulevard"
    body[f"{prefix}[billing_details][address][city]"] = billing.get("city") or "Los Angeles"
    body[f"{prefix}[billing_details][address][postal_code]"] = billing.get("postal_code") or "90026"
    body[f"{prefix}[billing_details][address][state]"] = billing.get("state") or "CA"


def add_paypal_confirm_extras(body: dict[str, str], strategy: dict[str, Any]) -> None:
    if strategy.get("stripe_sdk"):
        body["use_stripe_sdk"] = "true"
    if strategy.get("mandate"):
        body["mandate_data[customer_acceptance][type]"] = "online"
        body["mandate_data[customer_acceptance][online][infer_from_client]"] = "true"


def stripe_update_paypal_tax_region(stripe: Any, req: LongLinkRequest, cs_id: str, stripe_pk: str, billing: dict[str, str]) -> None:
    country = billing.get("country") or "JP"
    state = billing.get("state") or ""
    updates = [
        {"eid": "NA", "tax_region[country]": country, "key": stripe_pk},
    ]
    if state:
        updates.append({"eid": "NA", "tax_region[country]": country, "tax_region[state]": state, "key": stripe_pk})
    for body in updates:
        response = stripe.post(f"https://api.stripe.com/v1/payment_pages/{cs_id}", data=body, timeout=DEFAULT_TIMEOUT)
        record_diagnostic(req, "stripe_tax_region_update", response, request_body=body, proxy_stage="provider", extra={"cs_id": cs_id, "billing_country": country})
        if response.status_code >= 400:
            raise HTTPException(status_code=response.status_code, detail=f"stripe tax region update failed: {response.text[:500]}")


def find_nested_payment_method_id(payload: Any) -> str:
    if isinstance(payload, dict):
        direct = payload.get("payment_method")
        if isinstance(direct, str) and direct.startswith("pm_"):
            return direct
        if isinstance(direct, dict):
            direct_id = str(direct.get("id") or "").strip()
            if direct_id.startswith("pm_"):
                return direct_id
        payload_id = str(payload.get("id") or "").strip()
        if payload.get("object") == "payment_method" and payload_id.startswith("pm_"):
            return payload_id
        for key in ("setup_intent", "payment_intent", "last_setup_error", "payment_method", "data"):
            found = find_nested_payment_method_id(payload.get(key))
            if found:
                return found
        for value in payload.values():
            found = find_nested_payment_method_id(value)
            if found:
                return found
    if isinstance(payload, list):
        for value in payload:
            found = find_nested_payment_method_id(value)
            if found:
                return found
    return ""


def find_payment_method_payload(payload: Any, pm_id: str = "") -> dict[str, Any]:
    if isinstance(payload, dict):
        object_type = payload.get("object")
        payload_id = str(payload.get("id") or "").strip()
        if object_type == "payment_method" and (not pm_id or payload_id == pm_id):
            return payload
        for key in ("payment_method", "setup_intent", "payment_intent", "last_setup_error", "data"):
            found = find_payment_method_payload(payload.get(key), pm_id)
            if found:
                return found
        for value in payload.values():
            found = find_payment_method_payload(value, pm_id)
            if found:
                return found
    if isinstance(payload, list):
        for value in payload:
            found = find_payment_method_payload(value, pm_id)
            if found:
                return found
    return {}


def paypal_pm_summary(payload: Any, pm_id: str = "") -> str:
    pm = find_payment_method_payload(payload, pm_id)
    if not pm:
        nested_pm_id = find_nested_payment_method_id(payload)
        return f"pm={nested_pm_id or pm_id or '-'}; paypal_fields=not_found"
    billing = pm.get("billing_details") if isinstance(pm.get("billing_details"), dict) else {}
    address = billing.get("address") if isinstance(billing.get("address"), dict) else {}
    paypal = pm.get("paypal") if isinstance(pm.get("paypal"), dict) else {}
    return (
        f"pm={pm.get('id') or pm_id or '-'}; "
        f"allow_redisplay={pm.get('allow_redisplay') or '-'}; "
        f"billing_country={address.get('country') or '-'}; "
        f"billing_email={masked_email(str(billing.get('email') or '')) or '-'}; "
        f"paypal_country={paypal.get('country') or '-'}; "
        f"payer_email={masked_email(str(paypal.get('payer_email') or '')) or '-'}; "
        f"payer_id={paypal.get('payer_id') or '-'}; "
        f"billing_agreement_id={paypal.get('billing_agreement_id') or '-'}"
    )


def find_redirect_url_string(payload: Any, preferred_hosts: tuple[str, ...] = ()) -> str:
    preferred = tuple(host.lower().lstrip(".") for host in preferred_hosts if host)

    def good_url(value: str) -> bool:
        if not value.startswith(("http://", "https://")):
            return False
        host = (urlsplit(value).netloc or "").lower()
        if not preferred:
            return True
        return any(host == item or host.endswith(f".{item}") for item in preferred)

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


def is_paypal_ba_approve_url(value: str) -> bool:
    try:
        parsed = urlsplit(str(value or "").strip())
    except Exception:
        return False
    host = (parsed.netloc or "").lower()
    if not (host == "paypal.com" or host.endswith(".paypal.com")):
        return False
    path = parsed.path.rstrip("/").lower()
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    return path == "/agreements/approve" and bool(str(query.get("ba_token") or "").strip())


def paypal_ba_approve_url_from_token(token: str) -> str:
    token = str(token or "").strip().strip(" \t\r\n\"'<>),.;]}")
    if not token:
        return ""
    return f"{PAYPAL_BA_APPROVE_BASE}?ba_token={quote(token, safe='')}"


def normalize_text_for_ba_scan(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    text = (
        text.replace("\\/", "/")
        .replace("\\u0026", "&")
        .replace("\\u003d", "=")
        .replace("\\u003D", "=")
        .replace("&amp;", "&")
    )
    try:
        return unquote(text)
    except Exception:
        return text


def iter_text_values(payload: Any) -> list[str]:
    values: list[str] = []
    if isinstance(payload, str):
        values.append(payload)
    elif isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(key, str):
                values.append(key)
                if isinstance(value, (str, int, float)):
                    values.append(f"{key}={value}")
            values.extend(iter_text_values(value))
    elif isinstance(payload, list):
        for item in payload:
            values.extend(iter_text_values(item))
    return values


def extract_paypal_ba_approve_url(payload: Any) -> str:
    for raw in iter_text_values(payload):
        text = normalize_text_for_ba_scan(raw)
        if not text:
            continue
        if is_paypal_ba_approve_url(text):
            parsed = urlsplit(text)
            token = dict(parse_qsl(parsed.query, keep_blank_values=True)).get("ba_token") or ""
            return paypal_ba_approve_url_from_token(unquote(token))
        for pattern in (PAYPAL_BA_APPROVE_RE, PAYPAL_BA_TOKEN_RE):
            match = pattern.search(text)
            if match:
                return paypal_ba_approve_url_from_token(unquote(match.group("token")))
    return ""


def stripe_confirm(
    stripe: Any,
    cs_id: str,
    pm_id: str,
    stripe_pk: str,
    payment_method_type: str,
    init_payload: dict[str, Any],
    ctx: dict[str, Any],
    checkout: dict[str, Any],
    req: LongLinkRequest,
    stripe_hosted_url: str,
    strategy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payment_method_type = normalize_link_type(payment_method_type)
    return_url = stripe_confirm_return_url(cs_id, checkout, stripe_hosted_url)
    if payment_method_type == "gopay":
        init_checksum = stripe_init_gopay_checksum(stripe, cs_id, stripe_pk, req)
        body = {
            "guid": uuid.uuid4().hex,
            "muid": uuid.uuid4().hex,
            "sid": uuid.uuid4().hex,
            "payment_method": pm_id,
            "init_checksum": init_checksum,
            "version": "fed52f3bc6",
            "expected_amount": "0",
            "expected_payment_method_type": "gopay",
            "return_url": return_url,
            "elements_session_client[session_id]": f"elements_session_{uuid.uuid4().hex[:11]}",
            "elements_session_client[locale]": browser_profile_for_request(req)["elements_locale"],
            "elements_session_client[referrer_host]": "chatgpt.com",
            "elements_session_client[is_aggregation_expected]": "false",
            "client_attribution_metadata[client_session_id]": str(uuid.uuid4()),
            "client_attribution_metadata[merchant_integration_source]": "elements",
            "client_attribution_metadata[merchant_integration_subtype]": "payment-element",
            "client_attribution_metadata[payment_intent_creation_flow]": "deferred",
            "consent[terms_of_service]": "accepted",
            "key": stripe_pk,
        }
    else:
        runtime_version = str(ctx.get("runtime_version") or DEFAULT_STRIPE_RUNTIME_VERSION)
        if payment_method_type == "paypal":
            return_url = paypal_confirm_return_url(cs_id, checkout, stripe_hosted_url)
        expected_payment_method_type = "paypal" if payment_method_type == "paypal" else payment_method_type
        body = {
            "eid": "NA",
            "payment_method": pm_id,
            "expected_amount": str(ctx.get("checkout_amount") or expected_amount(init_payload)),
            "expected_payment_method_type": expected_payment_method_type,
            "return_url": return_url,
            "_stripe_version": str(ctx.get("stripe_version") or (PAYPAL_STRIPE_VERSION if payment_method_type == "paypal" else STRIPE_VERSION_FULL)),
            "guid": str(ctx.get("guid") or stripe_browser_id()),
            "muid": str(ctx.get("muid") or stripe_browser_id()),
            "sid": str(ctx.get("sid") or stripe_browser_id()),
            "key": stripe_pk,
            "version": runtime_version,
            "init_checksum": str(init_payload.get("init_checksum") or ctx.get("init_checksum") or ""),
            "client_attribution_metadata[client_session_id]": str(ctx.get("client_session_id") or ctx["stripe_js_id"]),
            "client_attribution_metadata[checkout_session_id]": cs_id,
            "client_attribution_metadata[merchant_integration_source]": "checkout",
            "client_attribution_metadata[merchant_integration_version]": "custom_checkout",
            "client_attribution_metadata[payment_method_selection_flow]": "automatic",
            "client_attribution_metadata[checkout_config_id]": ctx.get("config_id") or "",
            "link_brand": "link",
        }
        if payment_method_type == "paypal":
            add_paypal_confirm_extras(body, strategy or {})
    try:
        stripe_fingerprint.apply_fingerprint(body, payment_method_type)
    except stripe_fingerprint.FingerprintNotFound:
        pass
    response = stripe.post(f"https://api.stripe.com/v1/payment_pages/{cs_id}/confirm", data=body, timeout=DEFAULT_TIMEOUT)
    record_diagnostic(
        req,
        "stripe_confirm",
        response,
        request_body=body,
        proxy_stage="provider",
        strategy=str((strategy or {}).get("name") or ""),
        extra={"cs_id": cs_id, "pm_id": pm_id, "billing_country": body.get("payment_method_data[billing_details][address][country]") or ""},
    )
    ba_approve_url = extract_paypal_ba_approve_url(response.text)
    if ba_approve_url:
        return {"_ba_approve_url": ba_approve_url, "_raw_status": response.status_code}
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=f"stripe confirm failed: {response.text[:500]}")
    try:
        payload = response.json() or {}
    except Exception:
        payload = {"_raw_text": response.text}
    ba_approve_url = extract_paypal_ba_approve_url(payload)
    if ba_approve_url:
        payload["_ba_approve_url"] = ba_approve_url
    return payload


def stripe_confirm_paypal_inline(
    stripe: Any,
    cs_id: str,
    stripe_pk: str,
    billing: dict[str, str],
    init_payload: dict[str, Any],
    ctx: dict[str, Any],
    checkout: dict[str, Any],
    req: LongLinkRequest,
    stripe_hosted_url: str,
    strategy: dict[str, Any],
) -> dict[str, Any]:
    runtime_version = str(ctx.get("runtime_version") or DEFAULT_STRIPE_RUNTIME_VERSION)
    return_url = stripe_confirm_return_url(cs_id, checkout, stripe_hosted_url)
    body = {
        "guid": uuid.uuid4().hex,
        "muid": uuid.uuid4().hex,
        "sid": uuid.uuid4().hex,
        "payment_method_data[type]": "paypal",
        "init_checksum": str(init_payload.get("init_checksum") or ctx.get("init_checksum") or ""),
        "version": runtime_version,
        "expected_amount": str(ctx.get("checkout_amount") or expected_amount(init_payload)),
        "expected_payment_method_type": "paypal",
        "return_url": return_url,
        "elements_session_client[session_id]": ctx["elements_session_id"],
        "elements_session_client[locale]": str(ctx.get("locale") or "en"),
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
        "client_attribution_metadata[checkout_config_id]": ctx.get("config_id") or "",
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
        "_stripe_version": STRIPE_VERSION_FULL,
    }
    add_paypal_billing_fields(body, billing, "payment_method_data")
    add_paypal_confirm_extras(body, strategy)
    response = stripe.post(f"https://api.stripe.com/v1/payment_pages/{cs_id}/confirm", data=body, timeout=DEFAULT_TIMEOUT)
    record_diagnostic(
        req,
        "stripe_confirm_inline",
        response,
        request_body=body,
        proxy_stage="provider",
        strategy=str(strategy.get("name") or ""),
        extra={"cs_id": cs_id, "billing_country": billing.get("country") or ""},
    )
    ba_approve_url = extract_paypal_ba_approve_url(response.text)
    if ba_approve_url:
        return {"_ba_approve_url": ba_approve_url, "_raw_status": response.status_code}
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=f"stripe inline confirm failed: {response.text[:500]}")
    try:
        payload = response.json() or {}
    except Exception:
        payload = {"_raw_text": response.text}
    ba_approve_url = extract_paypal_ba_approve_url(payload)
    if ba_approve_url:
        payload["_ba_approve_url"] = ba_approve_url
    return payload


def extract_redirect_to_url(payload: Any) -> str:
    ba_approve_url = extract_paypal_ba_approve_url(payload)
    if ba_approve_url:
        return ba_approve_url
    if not isinstance(payload, dict):
        return ""
    next_action = payload.get("next_action")
    if isinstance(next_action, dict) and next_action.get("type") == "redirect_to_url":
        redirect_to_url = next_action.get("redirect_to_url") or {}
        if isinstance(redirect_to_url, dict):
            url = str(redirect_to_url.get("url") or "").strip()
            if url:
                return url
    for key in ("setup_intent", "payment_intent"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            found = extract_redirect_to_url(nested)
            if found:
                return found
    nested_url = find_redirect_url_string(payload, ("pm-redirects.stripe.com", "paypal.com"))
    if nested_url and "docs/error-codes" not in nested_url:
        return nested_url
    return ""


def setup_intent_last_error(payload: Any, current_pm_id: str = "") -> str:
    if isinstance(payload, dict):
        setup_intent = payload.get("setup_intent")
        if isinstance(setup_intent, dict):
            last_error = setup_intent.get("last_setup_error")
            if last_error:
                if current_pm_id and isinstance(last_error, dict):
                    error_pm = last_error.get("payment_method")
                    error_pm_id = ""
                    if isinstance(error_pm, dict):
                        error_pm_id = str(error_pm.get("id") or "").strip()
                    elif isinstance(error_pm, str):
                        error_pm_id = error_pm.strip()
                    if error_pm_id and error_pm_id != current_pm_id:
                        last_error = None
                if not last_error:
                    return ""
                try:
                    return json.dumps(last_error, ensure_ascii=False)[:700]
                except Exception:
                    return str(last_error)[:700]
        for value in payload.values():
            found = setup_intent_last_error(value, current_pm_id=current_pm_id)
            if found:
                return found
    if isinstance(payload, list):
        for value in payload:
            found = setup_intent_last_error(value, current_pm_id=current_pm_id)
            if found:
                return found
    return ""


def raise_if_setup_intent_blocked(payload: Any, context: str, current_pm_id: str = "") -> None:
    last_error = setup_intent_last_error(payload, current_pm_id=current_pm_id)
    if last_error:
        raise ProviderAttemptBlocked(f"{context}: setup_intent.last_setup_error: {last_error}")


def retryable_paypal_provider_error(detail: Any) -> bool:
    text = str(detail or "").lower()
    return any(
        item in text
        for item in (
            "setup_intent.last_setup_error",
            "redirect url resolution timeout",
            "blocked_billing_address_countries",
            "requires_payment_method",
            "chatgpt approve unexpected result",
            "blocked",
            "stripe confirm failed",
            "stripe inline confirm failed",
            "chatgpt approve failed",
            "invalid_request_error",
            "setup_attempt_failed",
            "generic_decline",
            "checkout_upcoming_invoice_mismatch",
        )
    )


def is_checkout_invoice_mismatch(detail: Any) -> bool:
    return "checkout_upcoming_invoice_mismatch" in str(detail or "").lower()


def should_retry_second_confirm_after_approve(detail: Any) -> bool:
    text = str(detail or "").lower()
    return "checkout_upcoming_invoice_mismatch" in text or "redirect url resolution timeout" in text or "missing_redirect" in text


def is_chatgpt_approve_blocked(detail: Any) -> bool:
    text = str(detail or "").lower()
    return "chatgpt approve unexpected result" in text and "blocked" in text


def is_payment_method_types_mismatch(detail: Any) -> bool:
    text = str(detail or "").lower()
    return "payment_method_types_mismatch" in text


def retryable_transient_error(detail: Any) -> bool:
    text = str(detail or "").lower()
    return any(
        item in text
        for item in (
            "<html",
            "html response instead of api json",
            "html_instead_of_json",
            "internal server error",
            "tls connect error",
            "curl:",
            "openssl_internal",
            "timeout",
            "temporarily",
            "connection",
            "bad gateway",
            "gateway timeout",
        )
    )


def is_html_response_error(detail: Any) -> bool:
    text = str(detail or "").lower()
    return "<html" in text or "html response instead of api json" in text or "html_instead_of_json" in text


def stripe_payment_page_redirect_url(
    stripe: Any,
    cs_id: str,
    stripe_pk: str,
    req: LongLinkRequest,
    timeout_seconds: float = 30,
    retry_on_setup_error: bool = False,
    steps: list[dict[str, str]] | None = None,
    current_pm_id: str = "",
) -> str:
    deadline = time.time() + max(1.0, float(timeout_seconds or 30))
    last_err = ""
    # PayPal 和 GoPay 统一走 GET /v1/payment_pages/{cs} 带完整 beta flags。
    # 旧版 PayPal 走 /poll 简版只带 key，stripe 返回精简 cs (keys=[id,invoice_*,locale,mode,payment_object_status])
    # 看不到 setup_intent/next_action，导致 PayPal 永远拿不到 BA token。
    # GoPay 端到端验证证明：必须 elements_session_client[client_betas][]=custom_checkout_server_updates_1
    # + custom_checkout_manual_approval_1 才能 stripe materialize intent。

    params = {
        "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
        "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
        "elements_session_client[elements_init_source]": "custom_checkout",
        "elements_session_client[referrer_host]": "chatgpt.com",
        "elements_session_client[session_id]": f"elements_session_{uuid.uuid4().hex[:11]}",
        "elements_session_client[stripe_js_id]": str(uuid.uuid4()),
        "elements_session_client[locale]": browser_profile_for_request(req)["elements_locale"],
        "elements_session_client[is_aggregation_expected]": "false",
        "elements_options_client[saved_payment_method][enable_save]": "never",
        "elements_options_client[saved_payment_method][enable_redisplay]": "never",
        "key": stripe_pk,
        "_stripe_version": STRIPE_VERSION_FULL,
    }
    while time.time() < deadline:
        response = stripe.get(f"https://api.stripe.com/v1/payment_pages/{cs_id}", params=params, timeout=DEFAULT_TIMEOUT)
        record_diagnostic(req, "stripe_payment_pages_poll", response, request_body=params, proxy_stage="provider", extra={"cs_id": cs_id, "pm_id": current_pm_id})
        if response.status_code == 200:
            try:
                payload = response.json() or {}
            except Exception:
                payload = {"_raw_text": response.text}
            if retry_on_setup_error:
                raise_if_setup_intent_blocked(payload, "stripe payment_pages", current_pm_id=current_pm_id)
            redirect_url = extract_redirect_to_url(payload)
            if redirect_url:
                label = "发现 ba_token，已拼接 PayPal BA approve 链" if is_paypal_ba_approve_url(redirect_url) else f"拿到 redirect_url：{redirect_url[:180]}"
                add_step(steps, "轮询 Stripe payment_pages", "ok", label)
                return redirect_url
            last_err = f"keys=[{','.join(sorted(payload.keys())[:8])}]"
        else:
            last_err = f"http {response.status_code}: {response.text[:120]}"
        time.sleep(1)
    add_step(steps, "轮询 Stripe payment_pages", "fail", f"超时：{last_err}")
    raise HTTPException(status_code=504, detail=f"redirect url resolution timeout: {last_err}")


def chatgpt_approve(chatgpt: Any, cs_id: str, checkout: dict[str, Any], req: LongLinkRequest) -> None:
    country = checkout["billing_country"]
    processor_entity = processor_entity_for_country(country, checkout.get("processor_entity", ""))
    ping_headers = {
        "referer": "https://chatgpt.com/",
        "x-openai-target-path": "/backend-api/sentinel/ping",
        "x-openai-target-route": "/backend-api/sentinel/ping",
    }
    try:
        ping_response = chatgpt.post(
            "https://chatgpt.com/backend-api/sentinel/ping",
            json={},
            headers=ping_headers,
            timeout=DEFAULT_TIMEOUT,
        )
        record_diagnostic(req, "chatgpt_sentinel_ping", ping_response, request_body={}, request_headers=diagnostic_request_headers(chatgpt, ping_headers), proxy_stage="approve", extra={"cs_id": cs_id})
    except Exception as exc:
        if getattr(req, "diagnostic_enabled", False):
            req.diagnostic_records.append(
                {
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "stage": "chatgpt_sentinel_ping",
                    "strategy": "",
                    "proxy_stage": "approve",
                    "url": {"host": "chatgpt.com", "path": "/backend-api/sentinel/ping"},
                    "classification": "request_exception",
                    "request_body": {},
                    "request_headers": safe_body_summary(diagnostic_request_headers(chatgpt, ping_headers)),
                    "error": short_text(exc),
                    "extra": {"cs_id": cs_id},
                }
            )
    approve_headers = {
        "referer": f"https://chatgpt.com/checkout/{processor_entity}/{cs_id}",
        "x-openai-target-path": "/backend-api/payments/checkout/approve",
        "x-openai-target-route": "/backend-api/payments/checkout/approve",
    }
    approve_body = {"checkout_session_id": cs_id, "processor_entity": processor_entity}
    response = chatgpt.post(
        "https://chatgpt.com/backend-api/payments/checkout/approve",
        json=approve_body,
        headers=approve_headers,
        timeout=DEFAULT_TIMEOUT,
    )
    record_diagnostic(req, "chatgpt_approve", response, request_body=approve_body, request_headers=diagnostic_request_headers(chatgpt, approve_headers), proxy_stage="approve", extra={"cs_id": cs_id})
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=f"chatgpt approve failed: {response.text[:500]}")
    try:
        result = (response.json() or {}).get("result")
    except Exception:
        result = ""
    if result != "approved":
        raise HTTPException(status_code=502, detail=f"chatgpt approve unexpected result: {result!r}")


def chatgpt_approve_with_retries(
    chatgpt: Any,
    cs_id: str,
    checkout: dict[str, Any],
    req: LongLinkRequest,
    steps: list[dict[str, str]] | None = None,
    attempts: int = 10,
) -> None:
    last_error: HTTPException | None = None
    max_attempts = max(1, int(attempts or 1))
    for approve_attempt in range(1, max_attempts + 1):
        try:
            if approve_attempt > 1:
                approve_region = normalize_proxy_region(req.approve_proxy_region)
                if req.proxy:
                    retry_proxy = proxy_with_fresh_sid(proxy_for_region(req.proxy, approve_region) if approve_region else req.proxy)
                    apply_provider_proxy(chatgpt, retry_proxy)
                    add_step(steps, "ChatGPT approve retry", "info", f"attempt {approve_attempt}/{max_attempts}; proxy={proxy_summary(retry_proxy)}")
                else:
                    add_step(steps, "ChatGPT approve retry", "info", f"attempt {approve_attempt}/{max_attempts}; no proxy configured")
            chatgpt_approve(chatgpt, cs_id, checkout, req)
            if approve_attempt > 1:
                add_step(steps, "ChatGPT approve retry", "ok", f"attempt {approve_attempt}/{max_attempts} approved")
            return
        except HTTPException as exc:
            last_error = exc
            if not is_chatgpt_approve_blocked(exc.detail) or approve_attempt >= max_attempts:
                raise
            add_step(steps, "ChatGPT approve retry", "warn", f"attempt {approve_attempt}/{max_attempts} blocked; retrying same cs with a fresh approve session")
    if last_error:
        raise last_error


def redirect_url_after_confirm(
    chatgpt: Any,
    stripe: Any,
    confirm_payload: dict[str, Any],
    cs_id: str,
    stripe_pk: str,
    checkout: dict[str, Any],
    req: LongLinkRequest,
    approval_stripe: Any | None = None,
    retry_on_setup_error: bool = False,
    steps: list[dict[str, str]] | None = None,
    current_pm_id: str = "",
) -> str:
    if retry_on_setup_error:
        raise_if_setup_intent_blocked(confirm_payload, "stripe confirm", current_pm_id=current_pm_id)
    redirect_url = extract_redirect_to_url(confirm_payload)
    if redirect_url:
        label = "confirm payload 发现 ba_token，已拼接 PayPal BA approve 链" if is_paypal_ba_approve_url(redirect_url) else f"直接返回 redirect_url：{redirect_url[:180]}"
        add_step(steps, "Stripe confirm", "ok", label)
        return redirect_url
    submission = confirm_payload.get("submission_attempt") if isinstance(confirm_payload, dict) else None
    if isinstance(submission, dict) and submission.get("state") == "requires_approval":
        add_step(steps, "ChatGPT approve", "info", "confirm 需要 approve，回到前段代理执行 ChatGPT approve")
        chatgpt_approve_with_retries(chatgpt, cs_id, checkout, req, steps=steps)
        add_step(steps, "ChatGPT approve", "ok", "approve 返回 approved")
        return stripe_payment_page_redirect_url(
            approval_stripe or stripe,
            cs_id,
            stripe_pk,
            req,
            timeout_seconds=45,
            retry_on_setup_error=retry_on_setup_error,
            steps=steps,
            current_pm_id=current_pm_id,
        )
    add_step(steps, "Stripe confirm", "info", "未直接返回 redirect_url，开始轮询 payment_pages")
    return stripe_payment_page_redirect_url(
        stripe,
        cs_id,
        stripe_pk,
        req,
        timeout_seconds=30,
        retry_on_setup_error=retry_on_setup_error,
        steps=steps,
        current_pm_id=current_pm_id,
    )


def resolve_external_redirect(stripe: Any, redirect_url: str, preferred_hosts: tuple[str, ...] = (), max_hops: int = 5, req: LongLinkRequest | None = None) -> str:
    current = str(redirect_url or "").strip()
    preferred = tuple(host.lower().lstrip(".") for host in preferred_hosts if host)
    for _ in range(max(1, int(max_hops or 1))):
        if not current:
            return ""
        ba_approve_url = extract_paypal_ba_approve_url(current)
        if ba_approve_url:
            return ba_approve_url
        host = (urlsplit(current).netloc or "").lower()
        try:
            response = stripe.get(current, allow_redirects=False, timeout=DEFAULT_TIMEOUT)
        except Exception:
            return current
        if req is not None:
            record_diagnostic(req, "provider_redirect_follow", response, request_body={"url": current}, proxy_stage="provider", extra={"hop_url": current})
        ba_approve_url = extract_paypal_ba_approve_url(
            {
                "request_url": current,
                "response_url": getattr(response, "url", ""),
                "location": response.headers.get("Location", ""),
                "body": response.text,
            }
        )
        if ba_approve_url:
            return ba_approve_url
        if preferred and any(host == item or host.endswith(f".{item}") for item in preferred):
            return current
        if response.status_code not in (301, 302, 303, 307, 308):
            return current
        location = str(response.headers.get("Location") or "").strip()
        if not location:
            return current
        current = urljoin(current, location)
    return current


def create_provider_link(
    chatgpt: Any,
    checkout: dict[str, Any],
    init_payload: dict[str, Any],
    stripe_hosted_url: str,
    req: LongLinkRequest,
    provider_proxy: str = "",
    steps: list[dict[str, str]] | None = None,
) -> dict[str, str]:
    link_type = normalize_link_type(req.link_type)
    if link_type == "paypal":
        return create_paypal_provider_link(
            chatgpt,
            checkout,
            init_payload,
            stripe_hosted_url,
            req,
            provider_proxy=provider_proxy,
            steps=steps,
        )
    provider_amount = expected_amount(init_payload)
    if not is_acceptable_low_amount(provider_amount):
        add_step(
            steps,
            "Provider 金额校验",
            "warn",
            f"{amount_policy_text(provider_amount)}，超过低金额阈值，要求重建 checkout",
        )
        raise ProviderAttemptBlocked(f"amount policy failed: {amount_policy_text(provider_amount)}")
    add_step(steps, "Provider 金额校验", "ok", amount_policy_text(provider_amount))
    stripe_pk = req.stripe_publishable_key.strip() or DEFAULT_STRIPE_PK
    add_step(steps, "Provider 阶段代理", "info", proxy_summary(provider_proxy or req.proxy))
    stripe = build_stripe_session(req, proxy_override=provider_proxy)
    ctx = stripe_context(checkout["cs_id"], init_payload, req)
    billing = billing_for_link_type(link_type, account_email_from_token(req.access_token))
    add_step(steps, "创建 Provider payment_method", "info", f"type={link_type}, billing_country={billing.get('country')}")
    pm_id = stripe_create_payment_method(stripe, req, checkout["cs_id"], stripe_pk, billing, link_type, ctx)
    add_step(steps, "创建 Provider payment_method", "ok", pm_id)
    confirm_payload = stripe_confirm(
        stripe,
        checkout["cs_id"],
        pm_id,
        stripe_pk,
        link_type,
        init_payload,
        ctx,
        checkout,
        req,
        stripe_hosted_url,
    )
    add_step(steps, "Provider confirm", "ok", "Stripe confirm 请求完成")
    stripe_redirect_url = redirect_url_after_confirm(
        chatgpt,
        stripe,
        confirm_payload,
        checkout["cs_id"],
        stripe_pk,
        checkout,
        req,
        steps=steps,
        current_pm_id=pm_id,
    )
    preferred_hosts = ("paypal.com",) if link_type == "paypal" else ()
    provider_url = resolve_external_redirect(stripe, stripe_redirect_url, preferred_hosts=preferred_hosts, req=req)
    add_step(steps, "解析 Provider Redirect URL", "ok", provider_url or stripe_redirect_url)
    return {
        "payment_method_id": pm_id,
        "stripe_redirect_url": stripe_redirect_url,
        "provider_redirect_url": provider_url,
        "long_url": provider_url or stripe_redirect_url,
    }


def create_paypal_provider_link(
    chatgpt: Any,
    checkout: dict[str, Any],
    init_payload: dict[str, Any],
    stripe_hosted_url: str,
    req: LongLinkRequest,
    provider_proxy: str = "",
    steps: list[dict[str, str]] | None = None,
) -> dict[str, str]:
    stripe_pk = req.stripe_publishable_key.strip() or DEFAULT_STRIPE_PK
    attempts = max(1, int(PAYPAL_PROVIDER_MAX_ATTEMPTS or 1))
    last_error = ""
    last_pm_id = ""
    last_stripe_redirect_url = ""
    account_email = account_email_from_token(req.access_token)
    # email_mode=account 时 token 没邮箱用合成兜底（phone-only token 也能跑）
    effective_email = account_email or f"buyer.{uuid.uuid4().hex[:12]}@example.com"
    add_step(
        steps,
        "PayPal provider 循环",
        "info",
        (
            f"最多 {attempts} 次；每次失败 *重建新 cs_live*（不复用，避开 cs not_active）；"
            f"strategy 控制 inline/billing/sdk/mandate 变体；provider 代理：{proxy_summary(provider_proxy or req.proxy)}"
        ),
    )
    if account_email:
        add_step(steps, "账号邮箱识别", "ok", f"PayPal billing email 使用账号邮箱：{masked_email(account_email)}")
    else:
        add_step(steps, "账号邮箱识别", "info", f"token 无邮箱，使用合成兜底：{masked_email(effective_email)}")

    # 第 1 次复用外面传入的 cs/init；第 2+ 次每次重建新 cs
    current_checkout = checkout
    current_init_payload = init_payload
    current_stripe_hosted_url = stripe_hosted_url

    for attempt in range(1, attempts + 1):
        try:
            strategy = paypal_confirm_strategy(attempt)
            add_step(
                steps,
                f"PayPal 第 {attempt}/{attempts} 次",
                "info",
                f"开始：Stripe init -> {'inline confirm' if strategy.get('inline') else '创建 PM -> confirm'} -> approve/poll；策略={strategy['name']}",
            )
            attempt_provider_proxy = provider_proxy if attempt == 1 else proxy_with_fresh_sid(provider_proxy or req.proxy)
            approve_region = normalize_proxy_region(req.approve_proxy_region)
            if approve_region:
                attempt_approval_proxy = proxy_with_fresh_sid(proxy_for_region(req.proxy or provider_proxy, approve_region))
            else:
                # ChatGPT approve / Stripe polling usually belongs to the provider
                # stage, but some black-box deployments bind approve to checkout.
                attempt_approval_proxy = attempt_provider_proxy
            attempt_provider_proxy = ensure_proxy_region(
                attempt_provider_proxy,
                proxy_region_from_url(attempt_provider_proxy),
                f"PayPal 第 {attempt}/{attempts} 次 provider",
                steps,
            )
            attempt_approval_proxy = ensure_proxy_region(
                attempt_approval_proxy,
                proxy_region_from_url(attempt_approval_proxy),
                f"PayPal 第 {attempt}/{attempts} 次 approve/poll",
                steps,
            )
            add_step(
                steps,
                f"PayPal 第 {attempt}/{attempts} 次代理",
                "info",
                f"provider={proxy_summary(attempt_provider_proxy)}; approve/poll={proxy_summary(attempt_approval_proxy)}",
            )
            # ★ 修复：每次失败重建 cs（第 1 次复用入参）
            if attempt > 1:
                add_step(steps, f"PayPal 第 {attempt}/{attempts} 次 重建 cs", "info", "上次 cs 已被 stripe 标 not_active，调 chatgpt /checkout 拿新 cs_live")
                checkout_retry_proxy = ensure_proxy_region(
                    proxy_with_fresh_sid(req.proxy),
                    normalize_proxy_region(req.checkout_proxy_region) or proxy_region_from_url(req.proxy),
                    f"PayPal 第 {attempt}/{attempts} 次 checkout",
                    steps,
                )
                apply_provider_proxy(chatgpt, checkout_retry_proxy)
                current_checkout = create_checkout(req, chatgpt)
                add_step(steps, f"PayPal 第 {attempt}/{attempts} 次 重建 cs", "ok", f"new cs_id={current_checkout['cs_id']}")
                apply_provider_proxy(chatgpt, attempt_approval_proxy)
                current_init_payload = stripe_init(current_checkout["cs_id"], req, proxy_override=attempt_provider_proxy)
                current_stripe_hosted_url = str(current_init_payload.get("stripe_hosted_url") or "").strip()
            cs_id = current_checkout["cs_id"]
            attempt_init_payload = current_init_payload
            attempt_stripe_hosted_url = current_stripe_hosted_url or stripe_hosted_url
            add_step(
                steps,
                f"PayPal 第 {attempt}/{attempts} 次 Stripe init",
                "ok",
                f"cs={cs_id}; keys={','.join(sorted(attempt_init_payload.keys())[:10])}; hosted={attempt_stripe_hosted_url[:180]}",
            )
            attempt_amount = expected_amount(attempt_init_payload)
            if not is_acceptable_low_amount(attempt_amount):
                add_step(
                    steps,
                    f"PayPal 第 {attempt}/{attempts} 次金额校验",
                    "warn",
                    f"{amount_policy_text(attempt_amount)}，丢弃当前 cs 并重试",
                )
                raise ProviderAttemptBlocked(f"amount policy failed: {amount_policy_text(attempt_amount)}")
            add_step(steps, f"PayPal 第 {attempt}/{attempts} 次金额校验", "ok", amount_policy_text(attempt_amount))
            stripe = build_stripe_session(req, proxy_override=attempt_provider_proxy)
            approval_stripe = build_stripe_session(req, proxy_override=attempt_approval_proxy)
            apply_provider_proxy(chatgpt, attempt_approval_proxy)
            ctx = stripe_context(cs_id, attempt_init_payload, req)
            attempt_billing_country = paypal_billing_country_for_provider(req, attempt_provider_proxy)
            billing = billing_for_link_type("paypal", effective_email, paypal_country=attempt_billing_country)
            stripe_update_paypal_tax_region(stripe, req, cs_id, stripe_pk, billing)
            add_step(steps, f"PayPal 第 {attempt}/{attempts} 次 tax_region", "ok", f"country={billing.get('country')}; state={billing.get('state') or '-'}")
            add_step(
                steps,
                f"PayPal 第 {attempt}/{attempts} 次策略",
                "info",
                (
                    f"strategy={strategy['name']}; inline={bool(strategy.get('inline'))}; "
                    f"email_mode={strategy.get('email_mode') or 'account'}; "
                    f"stripe_sdk={bool(strategy.get('stripe_sdk'))}; mandate={bool(strategy.get('mandate'))}; "
                    f"billing_country={billing.get('country')}; billing_email={masked_email(billing.get('email') or '')}; "
                    f"provider_proxy={proxy_summary(attempt_provider_proxy)}"
                ),
            )
            pm_id = ""
            if strategy.get("inline"):
                add_step(steps, f"PayPal 第 {attempt}/{attempts} 次 inline PM", "info", "不预创建 pm_，直接在 confirm 中提交 payment_method_data。")
                confirm_payload = stripe_confirm_paypal_inline(
                    stripe,
                    cs_id,
                    stripe_pk,
                    billing,
                    attempt_init_payload,
                    ctx,
                    current_checkout,
                    req,
                    attempt_stripe_hosted_url,
                    strategy,
                )
                pm_id = find_nested_payment_method_id(confirm_payload)
                if pm_id:
                    last_pm_id = pm_id
                add_step(steps, f"PayPal 第 {attempt}/{attempts} 次 inline PM", "ok", paypal_pm_summary(confirm_payload, pm_id))
            else:
                add_step(steps, f"PayPal 第 {attempt}/{attempts} 次 创建 PM", "info", "预创建 PayPal payment_method。")
                pm_id = stripe_create_payment_method(stripe, req, cs_id, stripe_pk, billing, "paypal", ctx, strategy=strategy)
                last_pm_id = pm_id
                add_step(steps, f"PayPal 第 {attempt}/{attempts} 次 创建 PM", "ok", pm_id)
                confirm_payload = stripe_confirm(
                    stripe,
                    cs_id,
                    pm_id,
                    stripe_pk,
                    "paypal",
                    attempt_init_payload,
                    ctx,
                    current_checkout,
                    req,
                    attempt_stripe_hosted_url,
                    strategy=strategy,
                )
                add_step(steps, f"PayPal 第 {attempt}/{attempts} 次 PM字段", "info", paypal_pm_summary(confirm_payload, pm_id))
            add_step(steps, f"PayPal 第 {attempt}/{attempts} 次 confirm", "ok", "Stripe confirm 请求完成")
            try:
                stripe_redirect_url = redirect_url_after_confirm(
                    chatgpt,
                    stripe,
                    confirm_payload,
                    cs_id,
                    stripe_pk,
                    current_checkout,
                    req,
                    approval_stripe=approval_stripe,
                    retry_on_setup_error=True,
                    steps=steps,
                    current_pm_id=pm_id,
                )
            except HTTPException as exc:
                if not should_retry_second_confirm_after_approve(exc.detail):
                    raise
                add_step(
                    steps,
                    f"PayPal 第 {attempt}/{attempts} 次二次 confirm",
                    "warn",
                    f"approve/poll needs a refresh ({short_text(exc.detail, 180)}); re-running Stripe init -> confirm -> approve.",
                )
                attempt_init_payload = stripe_init(cs_id, req, proxy_override=attempt_provider_proxy)
                attempt_stripe_hosted_url = str(attempt_init_payload.get("stripe_hosted_url") or attempt_stripe_hosted_url or "").strip()
                ctx = stripe_context(cs_id, attempt_init_payload, req)
                if strategy.get("inline"):
                    confirm_payload = stripe_confirm_paypal_inline(
                        stripe,
                        cs_id,
                        stripe_pk,
                        billing,
                        attempt_init_payload,
                        ctx,
                        current_checkout,
                        req,
                        attempt_stripe_hosted_url,
                        strategy,
                    )
                    pm_id = find_nested_payment_method_id(confirm_payload) or pm_id
                else:
                    confirm_payload = stripe_confirm(
                        stripe,
                        cs_id,
                        pm_id,
                        stripe_pk,
                        "paypal",
                        attempt_init_payload,
                        ctx,
                        current_checkout,
                        req,
                        attempt_stripe_hosted_url,
                        strategy=strategy,
                    )
                add_step(steps, f"PayPal 第 {attempt}/{attempts} 次二次 confirm", "ok", "second Stripe confirm completed")
                stripe_redirect_url = redirect_url_after_confirm(
                    chatgpt,
                    stripe,
                    confirm_payload,
                    cs_id,
                    stripe_pk,
                    current_checkout,
                    req,
                    approval_stripe=approval_stripe,
                    retry_on_setup_error=True,
                    steps=steps,
                    current_pm_id=pm_id,
                )
            last_stripe_redirect_url = stripe_redirect_url
            provider_url = resolve_external_redirect(stripe, stripe_redirect_url, preferred_hosts=("paypal.com",), req=req)
            add_step(
                steps,
                f"PayPal 第 {attempt}/{attempts} 次 Provider URL",
                "ok",
                provider_url or stripe_redirect_url,
            )
            return {
                "payment_method_id": pm_id,
                "stripe_redirect_url": stripe_redirect_url,
                "provider_redirect_url": provider_url,
                "long_url": provider_url or stripe_redirect_url,
            }
        except ProviderAttemptBlocked as exc:
            last_error = f"attempt {attempt}/{attempts}: {exc}"
            add_step(steps, f"PayPal 第 {attempt}/{attempts} 次失败", "fail", exc)
        except HTTPException as exc:
            if not retryable_paypal_provider_error(exc.detail):
                add_step(steps, f"PayPal 第 {attempt}/{attempts} 次中止", "fail", exc.detail)
                raise
            last_error = f"attempt {attempt}/{attempts}: {exc.detail}"
            add_step(steps, f"PayPal 第 {attempt}/{attempts} 次失败", "fail", exc.detail)
        except Exception as exc:
            last_error = f"attempt {attempt}/{attempts}: {exc}"
            add_step(steps, f"PayPal 第 {attempt}/{attempts} 次异常", "fail", exc)

    add_step(steps, "PayPal provider 失败", "fail", f"{attempts} 次都没拿到 PayPal approve URL，准备回退 hosted。last_error={last_error}")
    raise HTTPException(
        status_code=504,
        detail=(
            f"paypal provider exhausted {attempts} attempts, last_error={last_error}, "
            f"last_pm={last_pm_id}, last_redirect={last_stripe_redirect_url}"
        ),
    )


app = FastAPI(title="OpenAI Pay Long Link")
mail_pool_store = MailPoolStore(MAIL_POOL_DB)
account_pool_store = AccountPoolStore(ACCOUNT_POOL_DB)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
if PUBLIC_DIR.exists():
    app.mount("/public", StaticFiles(directory=PUBLIC_DIR), name="public")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(PUBLIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/api/qr")
def qr_code(req: QRCodeRequest) -> StreamingResponse:
    value = req.value.strip()
    if not value:
        raise HTTPException(status_code=400, detail="二维码内容不能为空")
    if qrcode is None:
        raise HTTPException(status_code=500, detail="当前环境缺少 qrcode 依赖，请安装 qrcode[pil]")

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=4,
    )
    qr.add_data(value)
    try:
        qr.make(fit=True)
    except (DataOverflowError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="二维码内容过长") from exc
    image = qr.make_image(fill_color="#111827", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": 'inline; filename="ideal-qr.png"',
        },
    )


def raise_mail_pool_http(exc: Exception) -> None:
    if isinstance(exc, MailPoolNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, MailPoolConflict):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, MailPoolOTPTimeout):
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    if isinstance(exc, MailPoolError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise HTTPException(status_code=502, detail=str(exc)) from exc


def raise_account_pool_http(exc: Exception) -> None:
    if isinstance(exc, AccountPoolNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, AccountPoolError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/mail-pool")
def list_mail_pool() -> dict[str, Any]:
    try:
        return {"success": True, "items": mail_pool_store.list_mailboxes()}
    except Exception as exc:
        raise_mail_pool_http(exc)


@app.post("/api/mail-pool/import")
def import_mail_pool(req: MailPoolImportRequest) -> dict[str, Any]:
    try:
        return mail_pool_store.import_mailboxes(req.text)
    except Exception as exc:
        raise_mail_pool_http(exc)


@app.post("/api/mail-pool/otp")
def read_mail_pool_otp(req: MailPoolOTPRequest) -> dict[str, Any]:
    try:
        return mail_pool_store.wait_for_mailbox_otp(
            mailbox_id=req.pool_id,
            email=req.email,
            timeout=req.timeout,
            issued_after=req.issued_after,
            service=req.service,
            exclude_code=req.exclude_code,
        )
    except Exception as exc:
        raise_mail_pool_http(exc)


@app.get("/api/mail-pool/{mailbox_id}/messages")
def list_mail_pool_messages(mailbox_id: int, limit: int = 20) -> dict[str, Any]:
    try:
        return {"success": True, "messages": mail_pool_store.list_messages(mailbox_id, limit)}
    except Exception as exc:
        raise_mail_pool_http(exc)


@app.post("/api/mail-pool/{mailbox_id}/reset")
def reset_mail_pool_item(mailbox_id: int) -> dict[str, bool]:
    try:
        mail_pool_store.reset_mailbox(mailbox_id)
        return {"success": True}
    except Exception as exc:
        raise_mail_pool_http(exc)


@app.delete("/api/mail-pool/{mailbox_id}")
def delete_mail_pool_item(mailbox_id: int) -> dict[str, bool]:
    try:
        mail_pool_store.delete_mailbox(mailbox_id)
        return {"success": True}
    except Exception as exc:
        raise_mail_pool_http(exc)


@app.post("/api/register/reserve")
def reserve_registration_mailbox(req: RegisterReserveRequest) -> dict[str, Any]:
    try:
        job = mail_pool_store.create_registration_job(req.owner, req.service)
        return {
            "success": True,
            "stage": "mail_pool_reserved",
            "next_action": "authorized_registration",
            "job": job,
            "flow": [
                "使用预留邮箱执行你有权限的注册或授权流程",
                "调用注册任务验证码接口读取邮箱验证码",
                "拿到合法 Access Token 后粘贴到 iDEAL 提取区",
                "完成后标记邮箱已注册，失败则释放邮箱",
            ],
        }
    except Exception as exc:
        raise_mail_pool_http(exc)


@app.get("/api/register/jobs")
def list_registration_jobs(limit: int = 50) -> dict[str, Any]:
    try:
        return {"success": True, "items": mail_pool_store.list_registration_jobs(limit)}
    except Exception as exc:
        raise_mail_pool_http(exc)


@app.get("/api/register/jobs/{job_id}")
def get_registration_job(job_id: str) -> dict[str, Any]:
    try:
        return {"success": True, "job": mail_pool_store.get_registration_job(job_id)}
    except Exception as exc:
        raise_mail_pool_http(exc)


@app.post("/api/register/jobs/{job_id}/otp")
def read_registration_job_otp(job_id: str, req: RegisterOTPRequest) -> dict[str, Any]:
    try:
        return mail_pool_store.wait_for_job_otp(
            job_id=job_id,
            timeout=req.timeout,
            exclude_code=req.exclude_code,
        )
    except Exception as exc:
        raise_mail_pool_http(exc)


@app.post("/api/register/jobs/{job_id}/complete")
def complete_registration_job(job_id: str) -> dict[str, Any]:
    try:
        return {"success": True, "job": mail_pool_store.complete_registration_job(job_id)}
    except Exception as exc:
        raise_mail_pool_http(exc)


@app.post("/api/register/jobs/{job_id}/release")
def release_registration_job(job_id: str) -> dict[str, Any]:
    try:
        return {"success": True, "job": mail_pool_store.release_registration_job(job_id)}
    except Exception as exc:
        raise_mail_pool_http(exc)


@app.get("/api/accounts")
def list_accounts(status: str = "all", q: str = "", limit: int = 300) -> dict[str, Any]:
    try:
        data = account_pool_store.list_accounts(status=status, query=q, limit=limit)
        return {"success": True, **data}
    except Exception as exc:
        raise_account_pool_http(exc)


@app.post("/api/accounts/import")
def import_accounts(req: AccountPoolImportRequest) -> dict[str, Any]:
    try:
        return account_pool_store.import_accounts(req.text)
    except Exception as exc:
        raise_account_pool_http(exc)


@app.get("/api/accounts/{account_id}/token")
def get_account_token(account_id: int) -> dict[str, Any]:
    try:
        return account_pool_store.reveal_access_token(account_id)
    except Exception as exc:
        raise_account_pool_http(exc)


@app.post("/api/accounts/{account_id}/used")
def mark_account_used(account_id: int) -> dict[str, Any]:
    try:
        return {"success": True, "account": account_pool_store.mark_used(account_id)}
    except Exception as exc:
        raise_account_pool_http(exc)


@app.post("/api/accounts/{account_id}/reset")
def reset_account(account_id: int) -> dict[str, Any]:
    try:
        return {"success": True, "account": account_pool_store.reset_account(account_id)}
    except Exception as exc:
        raise_account_pool_http(exc)


@app.delete("/api/accounts/{account_id}")
def disable_account(account_id: int) -> dict[str, bool]:
    try:
        account_pool_store.disable_account(account_id)
        return {"success": True}
    except Exception as exc:
        raise_account_pool_http(exc)


@app.post("/api/proxy-chain-test")
def proxy_chain_test(req: ProxyChainTestRequest) -> dict[str, Any]:
    link_type = normalize_link_type(req.link_type)
    probe_req = LongLinkRequest(
        accessToken="proxy-chain-test",
        proxy=req.proxy,
        link_type=link_type,
        checkout_proxy_region=req.checkout_proxy_region,
        provider_proxy_region=req.provider_proxy_region,
    )
    use_explicit_proxy = prepare_request_proxy(probe_req)
    checkout_proxy = probe_req.proxy
    checkout_expected = normalize_proxy_region(req.checkout_proxy_region) or proxy_region_from_url(checkout_proxy)
    checkout = probe_proxy(checkout_proxy, checkout_expected, "checkout")

    provider_value = str(req.provider_proxy_region or "").strip()
    provider_region = normalize_proxy_region(provider_value)
    provider_uses_checkout = use_same_provider_proxy(provider_value) or (
        link_type == "hosted" and not provider_region and not provider_value
    )
    if provider_uses_checkout:
        provider = {
            **checkout,
            "stage": "provider",
            "expected_region": checkout.get("expected_region", ""),
            "skipped": True,
            "error": checkout.get("error", ""),
        }
    else:
        provider_proxy = provider_stage_proxy(probe_req, use_explicit_proxy=use_explicit_proxy)
        provider_expected = normalize_proxy_region(provider_value) or proxy_region_from_url(provider_proxy)
        if provider_proxy == checkout_proxy:
            provider = {
                **checkout,
                "stage": "provider",
                "expected_region": provider_expected or checkout.get("expected_region", ""),
                "skipped": True,
                "error": checkout.get("error", ""),
            }
        else:
            provider = probe_proxy(provider_proxy, provider_expected, "provider")

    probes = [checkout] + ([provider] if provider else [])
    return {
        "ok": all(bool(item and item.get("ok") and item.get("match")) for item in probes),
        "link_type": link_type,
        "checkout": checkout,
        "provider": provider,
    }


@app.post("/api/long-link", response_model=LongLinkResponse)
def generate_long_link(req: LongLinkRequest) -> LongLinkResponse | JSONResponse:
    try:
        use_explicit_proxy = prepare_request_proxy(req)
        return generate_long_link_once(req, use_explicit_proxy)
    except HTTPException:
        raise
    except Exception as exc:
        return JSONResponse(status_code=502, content={"detail": str(exc)})


PARALLEL_PROXY_STRATEGIES: tuple[tuple[str, str, str, str], ...] = (
    ("US→US", "US", "US", ""),
    ("JP→US", "JP", "US", ""),
    ("JP→JP", "JP", "same", ""),
    ("US→JP", "US", "JP", ""),
    ("JP→US→JP", "JP", "US", "JP"),
)

DUAL_IDEAL_PROXY_STRATEGIES: tuple[tuple[str, str, str, str], ...] = (
    ("JP→NL", "JP", "NL", ""),
    ("NL→NL", "NL", "NL", ""),
)

MATRIX_PROXY_STRATEGIES: tuple[tuple[str, str, str, str], ...] = tuple(
    (f"{checkout}->{provider}->{approve}", checkout, provider, approve)
    for checkout in ("US", "JP")
    for provider in ("US", "JP")
    for approve in ("US", "JP")
)


@app.post("/api/long-link/start")
def start_long_link_job(req: LongLinkRequest) -> dict[str, str]:
    cleanup_old_jobs()
    job_id = uuid.uuid4().hex
    with JOBS_LOCK:
        LONG_LINK_JOBS[job_id] = {
            "status": "running",
            "steps": [],
            "result": None,
            "error": "",
            "status_code": 200,
            "started_at": time.time(),
            "updated_at": time.time(),
        }

    def run_job() -> None:
        steps = JobStepList(job_id)
        req.diagnostic_job_id = job_id
        try:
            add_step(steps, "任务已启动", "info", "开始准备代理和请求参数。")
            chain_mode = str(req.proxy_chain_strategy or "").strip().lower()
            if chain_mode == "sequential8":
                run_sequential_proxy_strategies(job_id, req, steps)
                return
            if chain_mode in {"dual_ideal", "parallel4", "matrix8"}:
                run_parallel_proxy_strategies(job_id, req, steps, mode=chain_mode)
                return
            use_explicit_proxy = prepare_request_proxy(req)
            result = generate_long_link_once(req, use_explicit_proxy, steps=steps)
            mark_job(job_id, status="done", result=result.model_dump(), error="", status_code=200)
        except HTTPException as exc:
            detail = short_text(exc.detail)
            detail, cleanup = apply_non_zero_amount_cleanup(req, detail, steps)
            add_step(steps, "任务失败", "fail", detail)
            updates: dict[str, Any] = {"status": "error", "error": detail, "status_code": exc.status_code}
            if cleanup:
                updates["account_cleanup"] = cleanup
            mark_job(job_id, **updates)
        except Exception as exc:
            detail = short_text(exc)
            detail, cleanup = apply_non_zero_amount_cleanup(req, detail, steps)
            add_step(steps, "任务异常", "fail", detail)
            updates = {"status": "error", "error": detail, "status_code": 502}
            if cleanup:
                updates["account_cleanup"] = cleanup
            mark_job(job_id, **updates)
        finally:
            try:
                diagnostic_path = save_diagnostics(req, job_id, job_snapshot(job_id).get("status", "unknown"))
                if diagnostic_path:
                    mark_job(job_id, diagnostic_path=diagnostic_path, diagnostic_url=f"/api/long-link/jobs/{job_id}/diagnostics")
            except Exception as exc:
                add_step(steps, "诊断保存失败", "warn", short_text(exc))

    threading.Thread(target=run_job, daemon=True).start()
    return {"job_id": job_id}


def run_parallel_proxy_strategies(job_id: str, req: LongLinkRequest, steps: JobStepList, mode: str = "parallel4") -> None:
    if mode == "dual_ideal":
        strategies = DUAL_IDEAL_PROXY_STRATEGIES
    elif mode == "matrix8":
        strategies = MATRIX_PROXY_STRATEGIES
    else:
        strategies = PARALLEL_PROXY_STRATEGIES
    add_step(steps, "??????", "info", f"mode={mode}; ???? {len(strategies)} ??????????")
    done = threading.Event()
    errors: dict[str, str] = {}
    errors_lock = threading.Lock()

    def worker(label: str, checkout_region: str, provider_region: str, approve_region: str = "") -> None:
        if done.is_set():
            return
        worker_req = req.model_copy(deep=True)
        worker_req.checkout_proxy_region = checkout_region
        worker_req.provider_proxy_region = provider_region
        worker_req.approve_proxy_region = approve_region
        worker_req.diagnostic_strategy = label
        worker_req.proxy_chain_strategy = ""
        worker_steps = StrategyStepList(steps, label)
        try:
            approve_detail = f" → approve {approve_region}" if approve_region else ""
            add_step(worker_steps, "策略启动", "info", f"前段 {checkout_region} → 后段 {provider_region}{approve_detail}")
            use_explicit_proxy = prepare_request_proxy(worker_req)
            result = generate_long_link_once(worker_req, use_explicit_proxy, steps=worker_steps)
            if done.is_set():
                return
            done.set()
            mark_job(job_id, status="done", result=result.model_dump(), error="", status_code=200)
            add_step(steps, "并发链路策略", "ok", f"{label} 已成功，任务结束。")
        except HTTPException as exc:
            detail = short_text(exc.detail)
            with errors_lock:
                errors[label] = detail
            add_step(worker_steps, "策略失败", "fail", detail)
        except Exception as exc:
            detail = short_text(exc)
            with errors_lock:
                errors[label] = detail
            add_step(worker_steps, "策略异常", "fail", detail)
        finally:
            if worker_req.diagnostic_records:
                with errors_lock:
                    req.diagnostic_records.extend(worker_req.diagnostic_records)

    threads = [
        threading.Thread(target=worker, args=strategy, daemon=True)
        for strategy in strategies
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    if done.is_set():
        return
    detail = "; ".join(f"{label}: {error}" for label, error in errors.items()) or "all proxy strategies failed"
    detail, cleanup = apply_non_zero_amount_cleanup(req, detail, steps)
    add_step(steps, "并发链路策略", "fail", detail)
    updates: dict[str, Any] = {"status": "error", "error": short_text(detail), "status_code": 502}
    if cleanup:
        updates["account_cleanup"] = cleanup
    mark_job(job_id, **updates)


def run_sequential_proxy_strategies(job_id: str, req: LongLinkRequest, steps: JobStepList) -> None:
    errors: dict[str, str] = {}
    add_step(steps, "Sequential 8 combos", "info", f"mode=sequential8; testing {len(MATRIX_PROXY_STRATEGIES)} combos one by one.")

    for label, checkout_region, provider_region, approve_region in MATRIX_PROXY_STRATEGIES:
        worker_req = req.model_copy(deep=True)
        worker_req.checkout_proxy_region = checkout_region
        worker_req.provider_proxy_region = provider_region
        worker_req.approve_proxy_region = approve_region
        worker_req.diagnostic_strategy = label
        worker_req.proxy_chain_strategy = ""
        worker_steps = StrategyStepList(steps, label)
        try:
            approve_detail = f" -> approve {approve_region}" if approve_region else ""
            add_step(worker_steps, "Strategy start", "info", f"checkout {checkout_region} -> provider {provider_region}{approve_detail}")
            use_explicit_proxy = prepare_request_proxy(worker_req)
            result = generate_long_link_once(worker_req, use_explicit_proxy, steps=worker_steps)
            mark_job(job_id, status="done", result=result.model_dump(), error="", status_code=200)
            add_step(steps, "Sequential 8 combos", "ok", f"{label} succeeded; stopped.")
            return
        except HTTPException as exc:
            detail = short_text(exc.detail)
            errors[label] = detail
            add_step(worker_steps, "Strategy failed", "fail", detail)
        except Exception as exc:
            detail = short_text(exc)
            errors[label] = detail
            add_step(worker_steps, "Strategy exception", "fail", detail)
        finally:
            if worker_req.diagnostic_records:
                req.diagnostic_records.extend(worker_req.diagnostic_records)

    detail = "; ".join(f"{label}: {error}" for label, error in errors.items()) or "all sequential proxy strategies failed"
    detail, cleanup = apply_non_zero_amount_cleanup(req, detail, steps)
    add_step(steps, "Sequential 8 combos", "fail", detail)
    updates: dict[str, Any] = {"status": "error", "error": short_text(detail), "status_code": 502}
    if cleanup:
        updates["account_cleanup"] = cleanup
    mark_job(job_id, **updates)


@app.get("/api/long-link/jobs/{job_id}")
def get_long_link_job(job_id: str) -> dict[str, Any]:
    return job_snapshot(job_id)


@app.get("/api/long-link/jobs/{job_id}/diagnostics")
def get_long_link_job_diagnostics(job_id: str) -> FileResponse:
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise HTTPException(status_code=404, detail="diagnostics not found")
    path = DIAGNOSTICS_DIR / f"{job_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="diagnostics not found")
    return FileResponse(path, media_type="application/json", filename=f"{job_id}-diagnostics.json")


def generate_long_link_once(
    req: LongLinkRequest,
    use_explicit_proxy: bool,
    steps: list[dict[str, str]] | None = None,
) -> LongLinkResponse:
    if steps is None:
        steps = []
    link_type = normalize_link_type(req.link_type)
    add_step(
        steps,
        "请求开始",
        "info",
        f"link_type={link_type}; checkout_proxy={proxy_summary(req.proxy)}; custom_proxy_chain={'yes' if req.checkout_proxy_region or req.provider_proxy_region else 'no'}",
    )
    cs_count = 0
    checkout_expected_region = normalize_proxy_region(req.checkout_proxy_region) or proxy_region_from_url(req.proxy)
    chatgpt = None
    checkout = None
    last_checkout_error = ""
    checkout_attempts = max(1, int(CHECKOUT_CREATE_MAX_ATTEMPTS or 1))
    for checkout_attempt in range(1, checkout_attempts + 1):
        if checkout_attempt > 1:
            req.proxy = proxy_with_fresh_sid(req.proxy)
            add_step(steps, f"创建 ChatGPT checkout 第 {checkout_attempt}/{checkout_attempts} 次", "info", f"前段换 sid 重试：{proxy_summary(req.proxy)}")
        req.proxy = ensure_proxy_region(req.proxy, checkout_expected_region, f"checkout 第 {checkout_attempt}/{checkout_attempts} 次", steps)
        chatgpt = build_chatgpt_session(req)
        add_step(steps, "ChatGPT 会话", "ok", "Access Token 已识别，已建立前段请求会话")
        try:
            checkout = create_checkout(req, chatgpt)
            cs_count += 1
            break
        except HTTPException as exc:
            last_checkout_error = str(exc.detail)
            add_step(steps, f"创建 ChatGPT checkout 第 {checkout_attempt}/{checkout_attempts} 次失败", "fail", last_checkout_error)
            if checkout_attempt >= checkout_attempts or not retryable_transient_error(last_checkout_error):
                raise
            if link_type == "ideal" and is_html_response_error(last_checkout_error) and checkout_expected_region != "NL":
                checkout_expected_region = "NL"
                req.checkout_proxy_region = "NL"
                req.proxy = proxy_with_fresh_sid(proxy_for_region(req.proxy, "NL"))
                add_step(steps, "iDEAL checkout 前段切换", "warn", "ChatGPT checkout 返回 HTML，下一次改用 NL 前段重建 checkout")
        except Exception as exc:
            last_checkout_error = str(exc)
            add_step(steps, f"创建 ChatGPT checkout 第 {checkout_attempt}/{checkout_attempts} 次异常", "fail", last_checkout_error)
            if checkout_attempt >= checkout_attempts or not retryable_transient_error(last_checkout_error):
                raise
            if link_type == "ideal" and is_html_response_error(last_checkout_error) and checkout_expected_region != "NL":
                checkout_expected_region = "NL"
                req.checkout_proxy_region = "NL"
                req.proxy = proxy_with_fresh_sid(proxy_for_region(req.proxy, "NL"))
                add_step(steps, "iDEAL checkout 前段切换", "warn", "ChatGPT checkout 返回 HTML，下一次改用 NL 前段重建 checkout")
    if not checkout:
        raise HTTPException(status_code=502, detail=f"checkout create failed after retries: {last_checkout_error}")
    add_step(
        steps,
        "创建 ChatGPT checkout",
        "ok",
        f"cs_id={checkout['cs_id']}; billing_country={checkout['billing_country']}; currency={checkout['currency']}; processor={checkout['processor_entity']}",
    )
    if checkout.get("publishable_key") and not req.stripe_publishable_key.strip():
        req.stripe_publishable_key = str(checkout["publishable_key"])
        add_step(steps, "Stripe Publishable Key", "ok", "using publishable_key returned by checkout")
    if link_type == "ideal":
        update_checkout_promotion(chatgpt, checkout, req, steps=steps)
    post_checkout_proxy = ""
    if link_type in {"paypal", "gopay", "ideal"}:
        post_checkout_proxy = provider_stage_proxy(req, use_explicit_proxy=use_explicit_proxy)
        provider_expected_region = normalize_proxy_region(req.provider_proxy_region) or proxy_region_from_url(post_checkout_proxy)
        post_checkout_proxy = ensure_proxy_region(post_checkout_proxy, provider_expected_region, "provider", steps)
        add_step(steps, "切换 Provider 代理", "info", proxy_summary(post_checkout_proxy))
        if link_type == "gopay":
            apply_provider_proxy(chatgpt, post_checkout_proxy)
            add_step(steps, "GoPay ChatGPT 会话代理", "ok", "GoPay provider 阶段已切换到后段代理")
    init_payload = None
    init_attempts = max(1, int(STRIPE_INIT_MAX_ATTEMPTS or 1))
    last_init_error = ""
    for init_attempt in range(1, init_attempts + 1):
        try:
            if init_attempt > 1:
                if post_checkout_proxy:
                    post_checkout_proxy = ensure_proxy_region(proxy_with_fresh_sid(post_checkout_proxy), proxy_region_from_url(post_checkout_proxy), f"provider init 第 {init_attempt}/{init_attempts} 次", steps)
                else:
                    req.proxy = ensure_proxy_region(proxy_with_fresh_sid(req.proxy), checkout_expected_region, f"checkout init 第 {init_attempt}/{init_attempts} 次", steps)
            init_payload = stripe_init(checkout["cs_id"], req, proxy_override=post_checkout_proxy)
            break
        except HTTPException as exc:
            last_init_error = str(exc.detail)
            add_step(steps, f"Stripe init 第 {init_attempt}/{init_attempts} 次失败", "fail", last_init_error)
            if init_attempt >= init_attempts or not retryable_transient_error(last_init_error):
                raise
        except Exception as exc:
            last_init_error = str(exc)
            add_step(steps, f"Stripe init 第 {init_attempt}/{init_attempts} 次异常", "fail", last_init_error)
            if init_attempt >= init_attempts or not retryable_transient_error(last_init_error):
                raise
    if init_payload is None:
        raise HTTPException(status_code=502, detail=f"stripe init failed after retries: {last_init_error}")
    stripe_hosted_url = str(init_payload.get("stripe_hosted_url") or "").strip()
    if not stripe_hosted_url:
        add_step(steps, "Stripe init", "fail", f"missing stripe_hosted_url, keys={sorted(init_payload.keys())}")
        raise HTTPException(
            status_code=502,
            detail=f"stripe init response missing stripe_hosted_url, keys={sorted(init_payload.keys())}",
        )
    add_step(
        steps,
        "Stripe init",
        "ok",
        f"hosted_url={stripe_hosted_url[:180]}; keys={','.join(sorted(init_payload.keys())[:10])}",
    )
    if link_type in {"gopay", "ideal"}:
        amount_attempt = 1
        while (
            (
                not is_acceptable_low_amount(expected_amount(init_payload))
                or not payment_payload_supports_method(init_payload, link_type)
            )
            and amount_attempt < checkout_attempts
        ):
            bad_amount = expected_amount(init_payload)
            bad_methods = payment_methods_policy_text(init_payload, link_type)
            reason = amount_policy_text(bad_amount)
            if is_acceptable_low_amount(bad_amount):
                reason = bad_methods
            elif not payment_payload_supports_method(init_payload, link_type):
                reason = f"{reason}; {bad_methods}"
            add_step(
                steps,
                f"{link_type} 金额校验 第 {amount_attempt}/{checkout_attempts} 次",
                "warn",
                f"{reason}，丢弃当前 cs 并重建 checkout",
            )
            amount_attempt += 1
            req.proxy = ensure_proxy_region(
                proxy_with_fresh_sid(req.proxy),
                checkout_expected_region,
                f"checkout amount retry 第 {amount_attempt}/{checkout_attempts} 次",
                steps,
            )
            chatgpt = build_chatgpt_session(req)
            add_step(steps, "ChatGPT 会话", "ok", "金额重试：已重建前段请求会话")
            checkout = create_checkout(req, chatgpt)
            cs_count += 1
            add_step(
                steps,
                f"重建 ChatGPT checkout 第 {amount_attempt}/{checkout_attempts} 次",
                "ok",
                f"cs_id={checkout['cs_id']}; billing_country={checkout['billing_country']}; currency={checkout['currency']}; processor={checkout['processor_entity']}",
            )
            if checkout.get("publishable_key") and not req.stripe_publishable_key.strip():
                req.stripe_publishable_key = str(checkout["publishable_key"])
                add_step(steps, "Stripe Publishable Key", "ok", "using publishable_key returned by checkout")
            if link_type == "ideal":
                update_checkout_promotion(chatgpt, checkout, req, steps=steps)
            if post_checkout_proxy:
                post_checkout_proxy = ensure_proxy_region(
                    proxy_with_fresh_sid(post_checkout_proxy),
                    normalize_proxy_region(req.provider_proxy_region) or proxy_region_from_url(post_checkout_proxy),
                    f"provider amount retry 第 {amount_attempt}/{checkout_attempts} 次",
                    steps,
                )
            init_payload = stripe_init(checkout["cs_id"], req, proxy_override=post_checkout_proxy)
            stripe_hosted_url = str(init_payload.get("stripe_hosted_url") or "").strip()
            add_step(
                steps,
                f"重建 Stripe init 第 {amount_attempt}/{checkout_attempts} 次",
                "ok",
                f"{amount_policy_text(expected_amount(init_payload))}; {payment_methods_policy_text(init_payload, link_type)}; hosted={stripe_hosted_url[:180]}",
            )
        final_amount = expected_amount(init_payload)
        if not is_acceptable_low_amount(final_amount):
            add_step(
                steps,
                f"{link_type} 金额校验",
                "fail",
                f"{amount_policy_text(final_amount)}，已重试 {amount_attempt}/{checkout_attempts} 次仍超过阈值",
            )
            raise HTTPException(status_code=502, detail=f"amount policy failed after retries: {amount_policy_text(final_amount)}")
        if not payment_payload_supports_method(init_payload, link_type):
            add_step(
                steps,
                f"{link_type} 支付方式校验",
                "fail",
                f"{payment_methods_policy_text(init_payload, link_type)}，已重试 {amount_attempt}/{checkout_attempts} 次仍不支持",
            )
            raise HTTPException(
                status_code=502,
                detail=f"payment method policy failed after retries: {payment_methods_policy_text(init_payload, link_type)}",
            )
        add_step(steps, f"{link_type} 金额校验", "ok", amount_policy_text(final_amount))
        add_step(steps, f"{link_type} 支付方式校验", "ok", payment_methods_policy_text(init_payload, link_type))
    hosted_long_url = to_openai_pay_url(stripe_hosted_url)
    add_step(steps, "生成 hosted 长链", "ok", hosted_long_url)
    provider = {
        "payment_method_id": "",
        "stripe_redirect_url": "",
        "provider_redirect_url": "",
        "long_url": hosted_long_url,
    }
    fallback = False
    provider_error = ""
    if link_type in {"paypal", "gopay", "ideal"}:
        provider_attempts = checkout_attempts if link_type in {"gopay", "ideal"} else 1
        for provider_attempt in range(1, provider_attempts + 1):
            try:
                provider = create_provider_link(
                    chatgpt,
                    checkout,
                    init_payload,
                    stripe_hosted_url,
                    req,
                    provider_proxy=post_checkout_proxy,
                    steps=steps,
                )
                break
            except HTTPException as exc:
                fallback = True
                provider_error = str(exc.detail)
                should_rebuild = link_type in {"gopay", "ideal"} and (
                    is_chatgpt_approve_blocked(provider_error) or is_payment_method_types_mismatch(provider_error)
                )
                if not should_rebuild or provider_attempt >= provider_attempts:
                    add_step(steps, "Provider 提取失败，回退 hosted", "fail", provider_error)
                    if link_type in {"paypal", "ideal"}:
                        raise HTTPException(status_code=502, detail=provider_error)
                    break
                add_step(
                    steps,
                    f"Provider blocked 重试 第 {provider_attempt}/{provider_attempts} 次",
                    "warn",
                    f"{provider_error}；丢弃当前 cs 并重建 checkout",
                )
            except ProviderAttemptBlocked as exc:
                fallback = True
                provider_error = str(exc)
                if link_type not in {"gopay", "ideal"} or provider_attempt >= provider_attempts:
                    add_step(steps, "Provider 提取失败，回退 hosted", "fail", provider_error)
                    if link_type in {"paypal", "ideal"}:
                        raise HTTPException(status_code=502, detail=provider_error)
                    break
                add_step(
                    steps,
                    f"Provider 重试 第 {provider_attempt}/{provider_attempts} 次",
                    "warn",
                    f"{provider_error}；丢弃当前 cs 并重建 checkout",
                )
            except Exception as exc:
                fallback = True
                provider_error = str(exc)
                add_step(steps, "Provider 提取异常，回退 hosted", "fail", provider_error)
                if link_type in {"paypal", "ideal"}:
                    raise HTTPException(status_code=502, detail=provider_error)
                break

            req.proxy = ensure_proxy_region(
                proxy_with_fresh_sid(req.proxy),
                checkout_expected_region,
                f"provider blocked checkout retry 第 {provider_attempt + 1}/{provider_attempts} 次",
                steps,
            )
            chatgpt = build_chatgpt_session(req)
            add_step(steps, "ChatGPT 会话", "ok", "blocked 重试：已重建前段请求会话")
            checkout = create_checkout(req, chatgpt)
            cs_count += 1
            add_step(
                steps,
                f"重建 ChatGPT checkout 第 {provider_attempt + 1}/{provider_attempts} 次",
                "ok",
                f"cs_id={checkout['cs_id']}; billing_country={checkout['billing_country']}; currency={checkout['currency']}; processor={checkout['processor_entity']}",
            )
            if checkout.get("publishable_key") and not req.stripe_publishable_key.strip():
                req.stripe_publishable_key = str(checkout["publishable_key"])
                add_step(steps, "Stripe Publishable Key", "ok", "using publishable_key returned by checkout")
            if link_type == "ideal":
                update_checkout_promotion(chatgpt, checkout, req, steps=steps)
            if post_checkout_proxy:
                post_checkout_proxy = ensure_proxy_region(
                    proxy_with_fresh_sid(post_checkout_proxy),
                    normalize_proxy_region(req.provider_proxy_region) or proxy_region_from_url(post_checkout_proxy),
                    f"provider blocked init retry 第 {provider_attempt + 1}/{provider_attempts} 次",
                    steps,
                )
            init_payload = stripe_init(checkout["cs_id"], req, proxy_override=post_checkout_proxy)
            stripe_hosted_url = str(init_payload.get("stripe_hosted_url") or "").strip()
            hosted_long_url = to_openai_pay_url(stripe_hosted_url)
            provider["long_url"] = hosted_long_url
            rebuilt_amount = expected_amount(init_payload)
            add_step(
                steps,
                f"重建 Stripe init 第 {provider_attempt + 1}/{provider_attempts} 次",
                "ok",
                f"{amount_policy_text(rebuilt_amount)}; hosted={stripe_hosted_url[:180]}",
            )
            if not is_acceptable_low_amount(rebuilt_amount):
                add_step(
                    steps,
                    f"{link_type} 金额校验 第 {provider_attempt + 1}/{provider_attempts} 次",
                    "warn",
                    f"{amount_policy_text(rebuilt_amount)}，继续重建 checkout",
                )

    response_amount = expected_amount(init_payload)
    return LongLinkResponse(
        ok=True,
        cs_id=checkout["cs_id"],
        processor_entity=checkout["processor_entity"],
        billing_country=checkout["billing_country"],
        currency=checkout["currency"],
        payment_locale=locale_parts(req.payment_locale)[0],
        link_type=link_type,
        payment_method_type=link_type if link_type in {"paypal", "gopay", "ideal"} else "",
        payment_method_id=provider["payment_method_id"],
        stripe_redirect_url=provider["stripe_redirect_url"],
        provider_redirect_url=provider["provider_redirect_url"],
        fallback=fallback,
        provider_error=provider_error,
        stripe_hosted_url=stripe_hosted_url,
        long_url=provider["long_url"] or hosted_long_url,
        amount=response_amount,
        amount_display=display_amount(response_amount, checkout["currency"]),
        cs_count=cs_count,
        steps=list(steps or []),
    )
