"""US PayPal link extraction routes."""

from __future__ import annotations

import json
import http.cookiejar
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationInfo, field_validator

from autotoken.api_routes import brazil_pix as pix_routes
from autotoken.core.paths import PROJECT_ROOT
from autotoken.payments.us_paypal import (
    PaypalOnlyOaicsSkipped,
    PaypalJobConfig,
    build_paypal_dynamic_proxy,
    generate_paypal_trial,
    normalize_paypal_proxy_url,
    paypal_proxy_with_fresh_sid,
)
from autotoken.services import paypal_protocol_local as paypal_protocol_service
from autotoken.services import proxy_runtime
from autotoken.storage import accounts as account_store
from autotoken.storage.auth_session_store import delete_auth_session

PaypalProtocolRunConfig = paypal_protocol_service.PaypalProtocolRunConfig
extract_protocol_ba_token = paypal_protocol_service.extract_ba_token
first_protocol_proxy = paypal_protocol_service.first_proxy
run_paypal_protocol_payment = paypal_protocol_service.run_paypal_protocol_payment
sanitize_protocol_log_text = paypal_protocol_service.sanitize_log_text

LINKS_FILE = PROJECT_ROOT / "data" / "us_paypal_links.json"
ACCOUNT_STATUS_FILE = PROJECT_ROOT / "data" / "us_paypal_account_status.json"
PAY153_REMOTE_TASKS_FILE = PROJECT_ROOT / "data" / "us_paypal_pay153_remote_tasks.json"
MAX_BATCH_CONCURRENCY = 30
MAX_PROTOCOL_BATCH_CONCURRENCY = 10
MAX_ACCOUNT_ATTEMPTS = 5
MAX_CONFIGURABLE_ACCOUNT_ATTEMPTS = 20
PROXY_PREFLIGHT_MAX_ATTEMPTS = 10
MAX_CONFIGURABLE_PROXY_PREFLIGHT_ATTEMPTS = 100
PAY153_API_BASE = "https://pay.153.ink/paypal-pay/api"
PAY153_ACCOUNT_MAX_RETRIES = 3
PAYPAL_LINK_TTL_SECONDS = 3 * 3600
PAYPAL_STATUS_PENDING = "pending"
PAYPAL_STATUS_RUNNING = "running"
PAYPAL_STATUS_SUCCESS = "success"
PAYPAL_STATUS_FAILED = "failed"
PAYPAL_STATUS_NO_PROMO = "no_promo"
PAYPAL_STATUS_NON_OAICS = "non_oaics"
PAYPAL_STATUS_PAID = "paid"
PAYPAL_STATUS_TEXT = {
    "pending": "未提链",
    "running": "提链中",
    "success": "已提链",
    "failed": "提链失败",
    "no_promo": "无优惠",
    "non_oaics": "非Oaics",
    "paid": "已支付",
}
ACCOUNT_UI_FIELDS = (
    "email", "status", "account_type", "seat_type", "ttl_seconds", "expires_at", "last_active_at", "updated_at", "note",
)
JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.RLock()
LINKS_LOCK = threading.RLock()
ACCOUNT_STATUS_LOCK = threading.RLock()
PAY153_REMOTE_TASKS_LOCK = threading.RLock()
TERMINAL_STATUSES = {"success", "error", "failed", "cancelled"}
PAY153_REMOTE_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


class UsPaypalStartRequest(BaseModel):
    account_email: str = Field("", alias="accountEmail")
    proxies: str = ""
    concurrency: int = 1
    local_proxy: str = Field("", alias="localProxy")
    kookeey_endpoint: str = Field("gate.kookeey.info:1000", alias="kookeeyEndpoint")
    kookeey_user: str = Field("", alias="kookeeyUser")
    kookeey_pass: str = Field("", alias="kookeeyPass")
    region: str = "US"
    promo_region: str = Field("JP", alias="promoRegion")
    promo_mode: str = Field("promo", alias="promoMode")
    only_oaics: bool = Field(False, alias="onlyOaics")
    max_attempts: int = Field(MAX_ACCOUNT_ATTEMPTS, alias="maxAttempts")
    proxy_preflight_attempts: int = Field(PROXY_PREFLIGHT_MAX_ATTEMPTS, alias="proxyPreflightAttempts")
    model_config = {"populate_by_name": True}

    @field_validator("region", "promo_region", mode="before")
    @classmethod
    def _clean_region(cls, value: Any, info: ValidationInfo) -> str:
        fallback = "JP" if info.field_name == "promo_region" else "US"
        text = str(value or fallback).strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", text):
            return fallback
        return text

    @field_validator("max_attempts", mode="before")
    @classmethod
    def _clean_max_attempts(cls, value: Any) -> int:
        try:
            attempts = int(value or MAX_ACCOUNT_ATTEMPTS)
        except Exception:
            attempts = MAX_ACCOUNT_ATTEMPTS
        return max(1, min(MAX_CONFIGURABLE_ACCOUNT_ATTEMPTS, attempts))

    @field_validator("proxy_preflight_attempts", mode="before")
    @classmethod
    def _clean_proxy_preflight_attempts(cls, value: Any) -> int:
        try:
            attempts = int(value or PROXY_PREFLIGHT_MAX_ATTEMPTS)
        except Exception:
            attempts = PROXY_PREFLIGHT_MAX_ATTEMPTS
        return max(1, min(MAX_CONFIGURABLE_PROXY_PREFLIGHT_ATTEMPTS, attempts))

    @field_validator("promo_mode", mode="before")
    @classmethod
    def _clean_promo_mode(cls, value: Any) -> str:
        text = str(value or "skip").strip().lower().replace("-", "_")
        if text in {"promo", "apply", "apply_promo", "with_promo"}:
            return "promo"
        return "skip"


class UsPaypalBatchStartRequest(UsPaypalStartRequest):
    account_emails: list[str] = Field(default_factory=list, alias="accountEmails")
    max_accounts: int | None = Field(None, alias="maxAccounts")

    @field_validator("account_emails", mode="before")
    @classmethod
    def _clean_account_emails(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("accountEmails must be a list")
        seen: set[str] = set()
        emails: list[str] = []
        for item in value:
            email = str(item or "").strip()
            key = email.lower()
            if email and key not in seen:
                seen.add(key)
                emails.append(email)
        return emails



class UsPaypalProtocolStartRequest(BaseModel):
    ba_token: str = Field("", alias="baToken")
    paypal_link: str = Field("", alias="paypalLink")
    phone: str = ""
    phone_pool: str = Field("", alias="phonePool")
    sms_record_url: str = Field("", alias="smsRecordUrl")
    sms_provider: str = Field("sms_record", alias="smsProvider")
    proxy_url: str = Field("", alias="proxyUrl")
    proxies: str = ""
    country: str = "US"
    account_email: str = Field("", alias="accountEmail")
    timeout_seconds: int = Field(900, alias="timeoutSeconds")
    sms_record_wait_seconds: int = Field(300, alias="smsRecordWaitSeconds")
    sms_record_poll_seconds: float = Field(3.0, alias="smsRecordPollSeconds")
    proxy_preflight_attempts: int = Field(PROXY_PREFLIGHT_MAX_ATTEMPTS, alias="proxyPreflightAttempts")
    phone_pool_reuse_enabled: bool = Field(False, alias="phonePoolReuseEnabled")
    debug: bool = False
    model_config = {"populate_by_name": True}

    @field_validator("country", mode="before")
    @classmethod
    def _clean_protocol_country(cls, value: Any) -> str:
        text = str(value or "US").strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", text):
            return "US"
        return text

    @field_validator("sms_provider", mode="before")
    @classmethod
    def _clean_sms_provider(cls, value: Any) -> str:
        normalized = paypal_protocol_service.normalize_sms_provider(str(value or "sms_record"))
        return normalized if normalized in {"sms_record", "hero_sms", "hero_sms_rent", "smsbower"} else "sms_record"

    @field_validator("timeout_seconds", mode="before")
    @classmethod
    def _clean_timeout_seconds(cls, value: Any) -> int:
        try:
            seconds = int(value or 900)
        except Exception:
            seconds = 900
        return max(60, min(3600, seconds))

    @field_validator("sms_record_wait_seconds", mode="before")
    @classmethod
    def _clean_sms_record_wait_seconds(cls, value: Any) -> int:
        try:
            seconds = int(value or 300)
        except Exception:
            seconds = 300
        return max(60, min(900, seconds))

    @field_validator("sms_record_poll_seconds", mode="before")
    @classmethod
    def _clean_sms_record_poll_seconds(cls, value: Any) -> float:
        try:
            seconds = float(value or 3.0)
        except Exception:
            seconds = 3.0
        return max(1.0, min(30.0, seconds))

    @field_validator("proxy_preflight_attempts", mode="before")
    @classmethod
    def _clean_proxy_preflight_attempts(cls, value: Any) -> int:
        try:
            attempts = int(value or PROXY_PREFLIGHT_MAX_ATTEMPTS)
        except Exception:
            attempts = PROXY_PREFLIGHT_MAX_ATTEMPTS
        return max(1, min(MAX_CONFIGURABLE_PROXY_PREFLIGHT_ATTEMPTS, attempts))


class UsPaypalProtocolBatchStartRequest(UsPaypalProtocolStartRequest):
    account_emails: list[str] = Field(default_factory=list, alias="accountEmails")
    concurrency: int = 1

    @field_validator("account_emails", mode="before")
    @classmethod
    def _clean_account_emails(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("accountEmails must be a list")
        seen: set[str] = set()
        emails: list[str] = []
        for item in value:
            email = str(item or "").strip()
            key = email.lower()
            if email and key not in seen:
                seen.add(key)
                emails.append(email)
        return emails

    @field_validator("concurrency", mode="before")
    @classmethod
    def _clean_concurrency(cls, value: Any) -> int:
        try:
            concurrency = int(value or 1)
        except Exception:
            concurrency = 1
        return max(1, min(MAX_PROTOCOL_BATCH_CONCURRENCY, concurrency))


class UsPaypal153BatchStartRequest(BaseModel):
    account_emails: list[str] = Field(default_factory=list, alias="accountEmails")
    phone: str = ""
    phone_pool: str = Field("", alias="phonePool")
    sms_record_url: str = Field("", alias="smsRecordUrl")
    sms_provider: str = Field("sms_record", alias="smsProvider")
    country: str = "auto"
    proxies: str | list[str] = ""
    buyer_mode: str = Field("identity_elevation", alias="buyerMode")
    concurrency: int = 1
    sms_record_wait_seconds: int = Field(300, alias="smsRecordWaitSeconds")
    sms_record_poll_seconds: float = Field(3.0, alias="smsRecordPollSeconds")
    phone_pool_reuse_enabled: bool = Field(False, alias="phonePoolReuseEnabled")
    model_config = {"populate_by_name": True}

    @field_validator("account_emails", mode="before")
    @classmethod
    def _clean_account_emails(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("accountEmails must be a list")
        seen: set[str] = set()
        emails: list[str] = []
        for item in value:
            email = str(item or "").strip()
            key = email.lower()
            if email and key not in seen:
                seen.add(key)
                emails.append(email)
        return emails

    @field_validator("buyer_mode", mode="before")
    @classmethod
    def _clean_buyer_mode(cls, value: Any) -> str:
        text = str(value or "identity_elevation").strip().lower().replace("-", "_")
        return text if text in {"identity_elevation", "original"} else "identity_elevation"

    @field_validator("sms_provider", mode="before")
    @classmethod
    def _clean_sms_provider(cls, value: Any) -> str:
        normalized = paypal_protocol_service.normalize_sms_provider(str(value or "sms_record"))
        return normalized if normalized in {"sms_record", "hero_sms", "hero_sms_rent", "smsbower"} else "sms_record"

    @field_validator("country", mode="before")
    @classmethod
    def _clean_country(cls, value: Any) -> str:
        text = str(value or "auto").strip().upper()
        return text if text == "AUTO" or re.fullmatch(r"[A-Z]{2}", text) else "AUTO"

    @field_validator("concurrency", mode="before")
    @classmethod
    def _clean_concurrency(cls, value: Any) -> int:
        try:
            concurrency = int(value or 1)
        except Exception:
            concurrency = 1
        return max(1, min(MAX_PROTOCOL_BATCH_CONCURRENCY, concurrency))

    @field_validator("sms_record_wait_seconds", mode="before")
    @classmethod
    def _clean_sms_record_wait_seconds(cls, value: Any) -> int:
        try:
            seconds = int(value or 300)
        except Exception:
            seconds = 300
        return max(30, min(900, seconds))

    @field_validator("sms_record_poll_seconds", mode="before")
    @classmethod
    def _clean_sms_record_poll_seconds(cls, value: Any) -> float:
        try:
            seconds = float(value or 3.0)
        except Exception:
            seconds = 3.0
        return max(1.0, min(30.0, seconds))


class UsPaypal153InteractiveRequest(BaseModel):
    remote_job_id: str = Field("", alias="remoteJobId")
    value: str = ""
    model_config = {"populate_by_name": True}


class UsPaypal153CancelByBaRequest(BaseModel):
    paypal_link: str = Field("", alias="paypalLink")
    ba_token: str = Field("", alias="baToken")
    model_config = {"populate_by_name": True}


class UsPaypalDeleteLinksRequest(BaseModel):
    ids: list[str] = Field(default_factory=list)


class UsPaypalDeleteAccountsRequest(BaseModel):
    emails: list[str] = Field(default_factory=list)


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_links() -> list[dict[str, Any]]:
    with LINKS_LOCK:
        data = _read_json(LINKS_FILE, [])
        return [_normalize_link_record(item) for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _save_links(items: list[dict[str, Any]]) -> None:
    with LINKS_LOCK:
        _write_json(LINKS_FILE, _dedupe_link_items(items)[:1000])


def _load_account_statuses() -> dict[str, dict[str, Any]]:
    with ACCOUNT_STATUS_LOCK:
        data = _read_json(ACCOUNT_STATUS_FILE, {})
        if not isinstance(data, dict):
            return {}
        return {str(k).lower(): v for k, v in data.items() if isinstance(v, dict)}


def _save_account_statuses(statuses: dict[str, dict[str, Any]]) -> None:
    with ACCOUNT_STATUS_LOCK:
        _write_json(ACCOUNT_STATUS_FILE, statuses)


def _set_account_status(email: str, status: str, *, error: str = "", job_id: str = "") -> dict[str, Any]:
    key = str(email or "").strip().lower()
    if not key:
        return {}
    normalized = str(status or PAYPAL_STATUS_PENDING).strip().lower()
    if normalized not in PAYPAL_STATUS_TEXT:
        normalized = PAYPAL_STATUS_PENDING
    item = {
        "status": normalized,
        "status_text": PAYPAL_STATUS_TEXT[normalized],
        "error": str(error or ""),
        "job_id": str(job_id or ""),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with ACCOUNT_STATUS_LOCK:
        statuses = _load_account_statuses()
        statuses[key] = item
        _save_account_statuses(statuses)
    return item


def _paypal_paid_emails() -> set[str]:
    paid: set[str] = set()
    try:
        accounts = account_store.load_accounts()
    except Exception:
        return paid
    for account in accounts:
        email = str(account.get("email") or "").strip().lower()
        if not email:
            continue
        account_type = str(account.get("account_type") or "").strip().lower()
        status = str(account.get("status") or "").strip().lower()
        bind_provider = str(account.get("last_bind_provider") or "").strip().lower()
        bind_status = str(account.get("last_bind_status") or "").strip().lower()
        paypal_bound = bind_provider == "paypal" and bind_status in {"success", "succeeded", "ok"}
        if account_type == account_store.ACCOUNT_TYPE_PLUS or status == account_store.STATUS_PLUS or paypal_bound:
            paid.add(email)
    return paid


def _iter_auth_accounts_with_paypal_status() -> list[dict[str, Any]]:
    statuses = _load_account_statuses()
    paid_emails = _paypal_paid_emails()
    links_by_email = {
        str(item.get("account_email") or "").strip().lower(): item
        for item in _load_links()
        if str(item.get("account_email") or "").strip()
    }
    linked_emails = {
        email
        for email, item in links_by_email.items()
        if str(item.get("paypal_link") or item.get("provider_redirect_url") or item.get("stripe_redirect_url") or "").strip()
    }
    try:
        dashboard_by_email = {
            str(account.get("email") or "").strip().lower(): account
            for account in account_store.load_accounts()
            if str(account.get("email") or "").strip()
        }
    except Exception:
        dashboard_by_email = {}
    rows: list[dict[str, Any]] = []
    for account in _iter_auth_accounts(include_paid=True):
        email = str(account.get("email") or "").strip()
        if not email:
            continue
        key = email.lower()
        dashboard_account = dashboard_by_email.get(key) or {}
        item = statuses.get(key) if isinstance(statuses.get(key), dict) else {}
        if key in paid_emails:
            item = {"status": PAYPAL_STATUS_PAID, "error": "", "updated_at": ""}
        elif not item and key in linked_emails:
            item = {"status": PAYPAL_STATUS_SUCCESS, "error": "", "updated_at": ""}
        status = str(item.get("status") or PAYPAL_STATUS_PENDING)
        if status not in PAYPAL_STATUS_TEXT:
            status = PAYPAL_STATUS_PENDING
        link_item = links_by_email.get(key) if status == PAYPAL_STATUS_SUCCESS else {}
        paypal_country = _link_country_from_item(link_item) if isinstance(link_item, dict) else ""
        rows.append({
            field: (email if field == "email" else dashboard_account.get(field, account.get(field))) for field in ACCOUNT_UI_FIELDS
        } | {
            "paypal_status": status,
            "paypal_status_text": str(item.get("status_text") or PAYPAL_STATUS_TEXT[status]),
            "paypal_error": str(item.get("error") or ""),
            "paypal_country": paypal_country,
            "paypal_status_updated_at": item.get("updated_at"),
            "paypal_selectable": status != PAYPAL_STATUS_PAID,
        })
    return rows


def _iter_auth_accounts(*, include_paid: bool = False) -> list[dict[str, Any]]:
    return pix_routes._iter_auth_accounts(include_paid=include_paid)


def _load_token_for_email(email: str) -> str:
    return pix_routes._load_token_for_email(email)


def _parse_proxies(value: str | list[str]) -> list[str]:
    return pix_routes._parse_proxies(value)


def _rotate_proxies_for_account(proxies: list[str], account_index: int) -> list[str]:
    return pix_routes._rotate_proxies_for_account(proxies, account_index)


def _batch_concurrency(req: UsPaypalBatchStartRequest, total: int) -> int:
    try:
        requested = int(req.concurrency or 1)
    except Exception:
        requested = 1
    return max(1, min(MAX_BATCH_CONCURRENCY, total, requested))


def _account_attempt_limit(req: UsPaypalBatchStartRequest) -> int:
    try:
        attempts = int(req.max_attempts or MAX_ACCOUNT_ATTEMPTS)
    except Exception:
        attempts = MAX_ACCOUNT_ATTEMPTS
    return max(1, min(MAX_CONFIGURABLE_ACCOUNT_ATTEMPTS, attempts))


def _proxy_preflight_attempt_limit(value: Any, default: int = PROXY_PREFLIGHT_MAX_ATTEMPTS) -> int:
    try:
        attempts = int(value or default)
    except Exception:
        attempts = default
    return max(1, min(MAX_CONFIGURABLE_PROXY_PREFLIGHT_ATTEMPTS, attempts))


def _preflight_paypal_link_proxies_or_raise(cfg: PaypalJobConfig, log, max_attempts: int | None = None) -> PaypalJobConfig:
    region = str(cfg.region or "US").strip().upper() or "US"
    if not cfg.direct_proxies and (not cfg.kookeey_user or not cfg.kookeey_pass):
        return cfg
    attempts = _proxy_preflight_attempt_limit(max_attempts)

    def preflight_region(current_cfg: PaypalJobConfig, target_region: str, label: str) -> str:
        region_errors: list[str] = []
        for stage_index in range(attempts):
            proxy_url, sid_label = build_paypal_dynamic_proxy(current_cfg, stage_index, target_region)
            if not proxy_url:
                continue
            log(f"{label}代理预检开始：{stage_index + 1}/{attempts} region={target_region} {sid_label}")
            ok, message = proxy_runtime.preflight_payment_proxy_url(proxy_url)
            if ok:
                auth_ok, auth_message = proxy_runtime.preflight_chatgpt_authenticated_proxy_url(proxy_url, current_cfg.access_token)
                if auth_ok:
                    log(f"{label}代理预检通过：{message}; {auth_message}")
                    return proxy_url
                log(f"{label}代理认证接口预检失败：{auth_message}")
                if "token_" in str(auth_message).lower() or "authentication token" in str(auth_message).lower():
                    raise RuntimeError(f"认证接口预检失败: {auth_message}")
                region_errors.append(str(auth_message or "unknown"))
                continue
            region_errors.append(str(message or "unknown"))
            log(f"{label}代理预检失败：{message}")
        raise RuntimeError(f"代理预检失败: {target_region} {'; '.join(region_errors[-attempts:])}")

    checkout_proxy = preflight_region(cfg, region, "目标国家")
    cfg = replace(cfg, direct_proxies=[checkout_proxy], preflighted_checkout_proxy_url=checkout_proxy)
    promo_region = str(cfg.promo_region or "JP").strip().upper() or "JP"
    if cfg.apply_promo and promo_region != region:
        promo_proxy = preflight_region(cfg, promo_region, "优惠区")
        cfg = replace(cfg, preflighted_promo_proxy_url=promo_proxy)
    return cfg


def _select_batch_accounts(req: UsPaypalBatchStartRequest) -> list[dict[str, Any]]:
    available = _iter_auth_accounts()
    by_email = {str(item.get("email") or "").strip().lower(): item for item in available}
    requested = [str(email or "").strip() for email in req.account_emails if str(email or "").strip()]
    selected = [by_email[email.lower()] for email in requested if email.lower() in by_email] if requested else available
    if req.max_accounts and req.max_accounts > 0:
        selected = selected[: int(req.max_accounts)]
    return selected


def _normalize_link(value: Any) -> str:
    return str(value or "").strip().rstrip("/")


def _link_country_from_item(item: dict[str, Any]) -> str:
    billing = item.get("billing") if isinstance(item.get("billing"), dict) else {}
    country = str(item.get("target_country") or item.get("targetCountry") or item.get("paypal_country") or item.get("paypalCountry") or item.get("country") or item.get("region") or billing.get("country") or "").strip().upper()
    return country if re.fullmatch(r"[A-Z]{2}", country) else ""


def _normalize_link_record(item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    normalized["country"] = _link_country_from_item(normalized)
    return normalized


def _dedupe_link_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_accounts: set[str] = set()
    seen_links: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        email = str(item.get("account_email") or "").strip().lower()
        link = _normalize_link(item.get("paypal_link") or item.get("provider_redirect_url") or item.get("stripe_redirect_url"))
        if email:
            if email in seen_accounts:
                continue
            seen_accounts.add(email)
        elif link:
            if link in seen_links:
                continue
        if link:
            seen_links.add(link)
        deduped.append(item)
    return deduped


def _link_record_from_result(job_id: str, account_email: str, result: dict[str, Any], *, target_country: str = "") -> dict[str, Any]:
    fields = result.get("fields") if isinstance(result.get("fields"), dict) else {}
    billing = fields.get("billing") if isinstance(fields.get("billing"), dict) else result.get("billing") or {}
    paypal_link = str(fields.get("paypal_link") or fields.get("provider_redirect_url") or fields.get("stripe_redirect_url") or "")
    created_at_ts = time.time()
    clean_target_country = str(target_country or "").strip().upper()
    display_country = _link_country_from_item({"target_country": clean_target_country, "country": fields.get("country") or result.get("country"), "billing": billing})
    record = {
        "id": uuid.uuid4().hex[:16],
        "job_id": job_id,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "created_at_ts": created_at_ts,
        "paypal_expires_at_ts": created_at_ts + PAYPAL_LINK_TTL_SECONDS,
        "account_email": account_email,
        "country": display_country,
        "target_country": display_country,
        "amount": str(fields.get("amount") or result.get("amount") or ""),
        "cs_id": str(fields.get("cs_id") or ""),
        "paypal_link": paypal_link,
        "provider_redirect_url": str(fields.get("provider_redirect_url") or ""),
        "stripe_redirect_url": str(fields.get("stripe_redirect_url") or ""),
        "ba_token": str(fields.get("ba_token") or ""),
        "link_source": str(fields.get("link_source") or ""),
        "link_binding": str(fields.get("link_binding") or ""),
        "chatgpt_checkout_url": str(fields.get("chatgpt_checkout_url") or ""),
        "billing": billing,
    }
    return _normalize_link_record(record)


def _append_link(record: dict[str, Any]) -> None:
    with LINKS_LOCK:
        items = _load_links()
        record_email = str(record.get("account_email") or "").strip().lower()
        record_link = _normalize_link(record.get("paypal_link") or record.get("provider_redirect_url") or record.get("stripe_redirect_url"))
        if record_email:
            items = [item for item in items if str(item.get("account_email") or "").strip().lower() != record_email]
        elif record_link:
            items = [
                item
                for item in items
                if _normalize_link(item.get("paypal_link") or item.get("provider_redirect_url") or item.get("stripe_redirect_url")) != record_link
            ]
        items.insert(0, record)
        _save_links(items)


def _append_log(job_id: str, message: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {message}"
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        job["logs"].append(line)
        job["logs"] = job["logs"][-500:]


def _is_job_cancel_requested(job_id: str) -> bool:
    with JOBS_LOCK:
        return bool((JOBS.get(job_id) or {}).get("cancel_requested"))


def _set_job_running_delta(job_id: str, delta: int) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        job["running_count"] = max(0, int(job.get("running_count") or 0) + delta)


def _set_job_account_status(job_id: str, email: str, status_item: dict[str, Any]) -> None:
    clean_email = str(email or "").strip()
    if not clean_email or not isinstance(status_item, dict):
        return
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        statuses = job.get("account_statuses")
        if not isinstance(statuses, dict):
            statuses = {}
            job["account_statuses"] = statuses
        target_key = clean_email
        lower_email = clean_email.lower()
        for existing_key in statuses.keys():
            if str(existing_key).strip().lower() == lower_email:
                target_key = existing_key
                break
        statuses[target_key] = dict(status_item)


def _mark_account_plus_paypal(email: str, message: str = "User is already paid") -> dict[str, Any]:
    account_store.ensure_session_only_account(email)
    now = time.time()
    return account_store.update_account(
        email,
        account_type=account_store.ACCOUNT_TYPE_PLUS,
        last_bind_provider="paypal",
        last_bind_status="success",
        last_bind_at=now,
        plus_bound_at=now,
        last_bind_message=message,
        last_bind_failure_stage="",
        last_quota={"plan_type": account_store.ACCOUNT_TYPE_PLUS, "source": "paypal_payment_success", "checked_at": now},
    ) or {}


def _delete_invalid_account(email: str) -> dict[str, Any]:
    return {
        "record_deleted": bool(account_store.delete_account(email)),
        "auth_session_deleted": bool(delete_auth_session(email)),
    }


def _is_paypal_non_zero_amount_error(error: Any) -> bool:
    return pix_routes._is_non_zero_after_promo_error(error)


def delete_account_artifacts(email: str) -> dict[str, Any]:
    target = str(email or "").strip().lower()
    if not target:
        return {"links_deleted": 0, "status_deleted": False}
    items = _load_links()
    kept = [item for item in items if str(item.get("account_email") or "").strip().lower() != target]
    if len(kept) != len(items):
        _save_links(kept)
    with ACCOUNT_STATUS_LOCK:
        statuses = _load_account_statuses()
        status_deleted = statuses.pop(target, None) is not None
        if status_deleted:
            _save_account_statuses(statuses)
    return {"links_deleted": len(items) - len(kept), "status_deleted": status_deleted}


def _delete_us_paypal_account_everywhere(email: str) -> dict[str, Any]:
    clean_email = str(email or "").strip()
    paypal_cleanup = delete_account_artifacts(clean_email)
    dashboard_account_deleted = bool(account_store.delete_account(clean_email))
    auth_session_deleted = bool(delete_auth_session(clean_email))
    return {
        "ok": True,
        "email": clean_email,
        "dashboard_account_deleted": dashboard_account_deleted,
        "auth_session_deleted": auth_session_deleted,
        "paypal": paypal_cleanup,
    }


def _run_batch_account(
    job_id: str,
    req: UsPaypalBatchStartRequest,
    account: dict[str, Any],
    index: int,
    total: int,
    proxies: list[str],
) -> dict[str, Any]:
    email = str(account.get("email") or "").strip()
    started = time.monotonic()
    if _is_job_cancel_requested(job_id):
        _append_log(job_id, f"[{index}/{total}] 跳过账号：{email}（任务已取消）")
        return {"skipped": True, "email": email, "status": _set_account_status(email, PAYPAL_STATUS_PENDING, job_id=job_id)}
    proxy_slot = f" proxy槽={(index - 1) % len(proxies) + 1}/{len(proxies)}" if proxies else ""
    _set_job_running_delta(job_id, 1)
    _append_log(job_id, f"[{index}/{total}] 开始账号：{email}{proxy_slot}")

    def account_log(message: str) -> None:
        _append_log(job_id, f"[{index}/{total}] {message}")

    attempts = 0
    try:
        _set_account_status(email, PAYPAL_STATUS_RUNNING, job_id=job_id)
        token = _load_token_for_email(email)
        if not token:
            raise RuntimeError("账号缺少有效 accessToken")
        last_error = ""
        result: dict[str, Any] | None = None
        max_attempts = _account_attempt_limit(req)
        for attempt in range(1, max_attempts + 1):
            attempts = attempt
            if _is_job_cancel_requested(job_id) and attempt > 1:
                raise RuntimeError(f"任务已取消，停止重试；最后错误: {last_error}")
            attempt_proxies = _rotate_proxies_for_account(proxies, attempt)
            _append_log(job_id, f"[{index}/{total}] 第 {attempt}/{max_attempts} 次尝试：{email}")
            cfg = PaypalJobConfig(
                access_token=token,
                local_proxy=str(req.local_proxy or "").strip(),
                kookeey_user=str(req.kookeey_user or "").strip(),
                kookeey_pass=str(req.kookeey_pass or ""),
                kookeey_endpoint=str(req.kookeey_endpoint or "gate.kookeey.info:1000").strip(),
                region=(req.region or "US").strip().upper() or "US",
                promo_region=(req.promo_region or "JP").strip().upper() or "JP",
                direct_proxies=attempt_proxies,
                apply_promo=req.promo_mode == "promo",
                only_oaics=bool(req.only_oaics),
            )
            try:
                cfg = _preflight_paypal_link_proxies_or_raise(cfg, account_log, req.proxy_preflight_attempts)
                result = generate_paypal_trial(cfg, log=account_log)
                if attempt > 1:
                    _append_log(job_id, f"[{index}/{total}] 重试成功：{email} attempt={attempt}")
                break
            except Exception as exc:
                last_error = str(exc)
                if last_error.startswith("代理预检失败"):
                    status = _set_account_status(email, PAYPAL_STATUS_FAILED, error=last_error, job_id=job_id)
                    _append_log(job_id, f"[{index}/{total}] 代理预检已达到上限，停止真实提链：{email} {last_error}")
                    return {
                        "ok": False,
                        "email": email,
                        "error": {
                            "email": email,
                            "elapsed_s": round(time.monotonic() - started, 1),
                            "attempts": attempt,
                            "error": last_error,
                        },
                        "status": status,
                    }
                if pix_routes._is_already_paid_error(last_error):
                    _mark_account_plus_paypal(email, last_error)
                    status = _set_account_status(email, PAYPAL_STATUS_SUCCESS, error=last_error, job_id=job_id)
                    _append_log(job_id, f"[{index}/{total}] 账号已是 Plus：{email}，已更新账号类型=Plus 绑定渠道=PayPal")
                    return {"skipped": True, "email": email, "reason": "账号已是 Plus，已标记绑定渠道 PayPal", "status": status}
                if pix_routes._is_token_invalidated_error(last_error) or pix_routes._is_no_organization_error(last_error):
                    cleanup = _delete_invalid_account(email)
                    status = _set_account_status(email, PAYPAL_STATUS_FAILED, error=last_error, job_id=job_id)
                    return {
                        "ok": False,
                        "email": email,
                        "error": {
                            "email": email,
                            "elapsed_s": round(time.monotonic() - started, 1),
                            "attempts": attempt,
                            "error": f"账号不可用，已从账号池删除：{last_error}",
                            "cleanup": cleanup,
                        },
                        "status": status,
                    }
                if _is_paypal_non_zero_amount_error(last_error):
                    status = _set_account_status(email, PAYPAL_STATUS_NO_PROMO, error=last_error, job_id=job_id)
                    reason = "账号无优惠，账单金额非 0"
                    _append_log(job_id, f"[{index}/{total}] {reason}：{email}")
                    return {
                        "skipped": True,
                        "email": email,
                        "reason": reason,
                        "status": status,
                        "account_deleted": False,
                    }
                if isinstance(exc, PaypalOnlyOaicsSkipped):
                    status = _set_account_status(email, PAYPAL_STATUS_NON_OAICS, error="", job_id=job_id)
                    reason = "非 OAICS checkout，已跳过"
                    _append_log(job_id, f"[{index}/{total}] {reason}：{email}")
                    return {
                        "skipped": True,
                        "email": email,
                        "reason": reason,
                        "status": status,
                    }
                _append_log(job_id, f"[{index}/{total}] 第 {attempt}/{max_attempts} 次失败：{email} {last_error}")
                if attempt >= max_attempts:
                    raise
                time.sleep(min(2.0, 0.5 * attempt))
        if result is None:
            raise RuntimeError(last_error or "提链失败")
        result["account_email"] = email
        record = _link_record_from_result(job_id, email, result, target_country=req.region)
        _append_link(record)
        status = _set_account_status(email, PAYPAL_STATUS_SUCCESS, job_id=job_id)
        compact = {"email": email, "elapsed_s": round(time.monotonic() - started, 1), "attempts": attempts, "link": record}
        _append_log(job_id, f"[{index}/{total}] 成功：{email} attempts={attempts} cs_id={record.get('cs_id')}")
        return {"ok": True, "email": email, "success": compact, "status": status}
    except Exception as exc:
        error = str(exc)
        item = {"email": email, "elapsed_s": round(time.monotonic() - started, 1), "attempts": attempts or 1, "error": error}
        status = _set_account_status(email, PAYPAL_STATUS_FAILED, error=error, job_id=job_id)
        _append_log(job_id, f"[{index}/{total}] 最终失败：{email} attempts={attempts or 1} {exc}")
        return {"ok": False, "email": email, "error": item, "status": status}
    finally:
        _set_job_running_delta(job_id, -1)


def _run_batch_job(job_id: str, req: UsPaypalBatchStartRequest) -> None:
    def log(message: str) -> None:
        _append_log(job_id, message)

    try:
        accounts = _select_batch_accounts(req)
        if not accounts:
            raise RuntimeError("没有可用账号，请先选择账号池账号或刷新账号池")
        proxies = _parse_proxies(req.proxies)
        if not proxies and (not req.kookeey_user or not req.kookeey_pass):
            raise RuntimeError("请填写代理")
        concurrency = _batch_concurrency(req, len(accounts))
        successes: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        account_statuses: dict[str, dict[str, Any]] = {}
        for account in accounts:
            email = str(account.get("email") or "").strip()
            account_statuses[email] = _set_account_status(email, PAYPAL_STATUS_PENDING, job_id=job_id)
        with JOBS_LOCK:
            if job_id not in JOBS:
                return
            cancel_requested = bool(JOBS[job_id].get("cancel_requested"))
            JOBS[job_id]["status"] = "cancelling" if cancel_requested else "running"
            JOBS[job_id]["total"] = len(accounts)
            JOBS[job_id]["completed"] = 0
            JOBS[job_id]["concurrency"] = concurrency
            JOBS[job_id]["running_count"] = 0
            JOBS[job_id]["cancel_requested"] = cancel_requested
            JOBS[job_id]["skipped"] = []
            JOBS[job_id]["account_statuses"] = account_statuses
        log(
            f"PayPal 提链任务开始：{len(accounts)} 个账号，并发 {concurrency}，"
            f"目标国家={req.region}，优惠区={req.promo_region}，重试={_account_attempt_limit(req)}，promo={req.promo_mode}"
        )
        completed = 0
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [
                executor.submit(_run_batch_account, job_id, req, account, index, len(accounts), _rotate_proxies_for_account(proxies, index))
                for index, account in enumerate(accounts, start=1)
            ]
            for future in as_completed(futures):
                item = future.result()
                email = str(item.get("email") or "")
                if item.get("skipped"):
                    skipped.append({"email": email, "reason": item.get("reason") or "任务已取消"})
                elif item.get("ok"):
                    successes.append(item["success"])
                else:
                    errors.append(item["error"])
                if email:
                    account_statuses[email] = item.get("status") or {}
                completed += 1
                with JOBS_LOCK:
                    if job_id not in JOBS:
                        return
                    JOBS[job_id]["completed"] = completed
                    JOBS[job_id]["account_statuses"] = account_statuses
                    JOBS[job_id]["skipped"] = skipped
                    JOBS[job_id]["result"] = {"batch": True, "successes": successes, "errors": errors, "skipped": skipped}
        with JOBS_LOCK:
            if job_id not in JOBS:
                return
            cancelled = bool(JOBS[job_id].get("cancel_requested"))
            has_non_error_outcome = bool(successes or skipped)
            JOBS[job_id]["status"] = "cancelled" if cancelled else ("success" if has_non_error_outcome else "error")
            JOBS[job_id]["error"] = "任务已取消" if cancelled else ("" if has_non_error_outcome else "全部账号失败")
            JOBS[job_id]["finished_at"] = time.time()
        log(f"PayPal 提链任务完成：成功 {len(successes)}，失败 {len(errors)}，跳过 {len(skipped)}")
    except Exception as exc:
        with JOBS_LOCK:
            if job_id not in JOBS:
                return
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error"] = str(exc)
            JOBS[job_id]["finished_at"] = time.time()
        _append_log(job_id, f"失败: {exc}")


def _new_job(account_emails: list[str], concurrency: int) -> str:
    job_id = uuid.uuid4().hex[:12]
    created = time.time()
    with JOBS_LOCK:
        JOBS[job_id] = {
            "id": job_id, "status": "queued", "logs": ["任务已创建"],
            "result": None,
            "error": None, "created_at": created, "finished_at": None,
            "account_email": account_emails[0] if len(account_emails) == 1 else "",
            "total": len(account_emails), "completed": 0,
            "concurrency": max(1, min(MAX_BATCH_CONCURRENCY, int(concurrency or 1))),
            "cancel_requested": False, "running_count": 0, "skipped": [], "account_statuses": {},
        }
    return job_id


def _public_pay153_children(children: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(children, dict):
        return {}
    allowed = {
        "email",
        "remote_job_id",
        "country",
        "status",
        "stage",
        "error",
        "awaiting_otp",
        "awaiting_captcha",
        "awaiting_prompt",
        "cancellable",
    }
    public: dict[str, dict[str, Any]] = {}
    for remote_job_id, child in children.items():
        if not isinstance(child, dict):
            continue
        public[str(remote_job_id)] = {key: child.get(key) for key in allowed if key in child}
    return public


def _job_snapshot(job_id: str) -> dict[str, Any]:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        children = _public_pay153_children(job.get("children")) if job.get("kind") == "paypal_153_payment" else (job.get("children") or {})
        return {"id": job["id"], "status": job["status"], "logs": list(job["logs"]), "result": job["result"], "error": job["error"], "created_at": job["created_at"], "finished_at": job["finished_at"], "account_email": job.get("account_email") or "", "total": job.get("total") or 0, "completed": job.get("completed") or 0, "concurrency": job.get("concurrency") or 1, "running_count": job.get("running_count") or 0, "cancel_requested": bool(job.get("cancel_requested")), "skipped": job.get("skipped") or [], "account_statuses": job.get("account_statuses") or {}, "children": children}


def _new_protocol_batch_job(account_emails: list[str], concurrency: int = 1) -> str:
    job_id = "ppay-" + uuid.uuid4().hex[:10]
    created = time.time()
    clean_emails = [str(email or "").strip() for email in account_emails if str(email or "").strip()]
    with JOBS_LOCK:
        JOBS[job_id] = {
            "id": job_id,
            "kind": "paypal_protocol_payment",
            "status": "queued",
            "logs": ["协议支付任务已创建"],
            "result": None,
            "error": None,
            "created_at": created,
            "finished_at": None,
            "account_email": clean_emails[0] if len(clean_emails) == 1 else "",
            "total": len(clean_emails) or 1,
            "completed": 0,
            "concurrency": max(1, min(MAX_PROTOCOL_BATCH_CONCURRENCY, int(concurrency or 1))),
            "cancel_requested": False,
            "running_count": 0,
            "skipped": [],
            "account_statuses": {},
        }
    return job_id


def _new_protocol_job(account_email: str = "") -> str:
    return _new_protocol_batch_job([str(account_email or "").strip()] if str(account_email or "").strip() else [], 1)


def _split_protocol_values(value: str | list[str]) -> list[str]:
    if isinstance(value, list):
        return [str(item or "").strip() for item in value if str(item or "").strip()]
    return [item.strip() for item in str(value or "").replace(",", "\n").splitlines() if item.strip()]


def _protocol_batch_concurrency(req: UsPaypalProtocolBatchStartRequest, total: int) -> int:
    try:
        requested = int(req.concurrency or 1)
    except Exception:
        requested = 1
    return max(1, min(MAX_PROTOCOL_BATCH_CONCURRENCY, total, requested))


def _protocol_proxy_for_country(proxy_value: str, country: str) -> str:
    raw = str(proxy_value or "").strip()
    if not raw:
        return ""
    proxy, _sid = paypal_proxy_with_fresh_sid(normalize_paypal_proxy_url(raw), str(country or "US").strip().upper() or "US")
    return proxy


def _preflight_protocol_proxy_or_raise(proxy_values: str | list[str], country: str, log, max_attempts: int | None = None) -> str:
    candidates = _parse_proxies(proxy_values)
    if not candidates:
        return ""
    target_country = str(country or "US").strip().upper() or "US"
    errors: list[str] = []
    attempts = _proxy_preflight_attempt_limit(max_attempts)
    for attempt in range(attempts):
        raw_proxy = candidates[attempt % len(candidates)]
        proxy_url = _protocol_proxy_for_country(raw_proxy, target_country)
        if not proxy_url:
            continue
        log(f"协议支付代理预检开始：{attempt + 1}/{attempts} country={target_country}")
        ok, message = proxy_runtime.preflight_payment_proxy_url(proxy_url)
        if ok:
            log(f"协议支付代理预检通过：{message}")
            return proxy_url
        errors.append(str(message or "unknown"))
        log(f"协议支付代理预检失败：{message}")
    raise RuntimeError(f"代理预检失败: {'; '.join(errors[-attempts:])}")


def _protocol_proxy_for_index(proxies: list[str], index: int, country: str) -> str:
    if not proxies:
        return ""
    return _protocol_proxy_for_country(proxies[(max(1, index) - 1) % len(proxies)], country)


def _protocol_value_for_index(values: list[str], index: int) -> str:
    if not values:
        return ""
    return values[(max(1, index) - 1) % len(values)]


def _sms_record_phone_pool(req: Any) -> list[dict[str, str]]:
    pool: list[dict[str, str]] = []
    raw_pool = str(getattr(req, "phone_pool", "") or "").strip()
    if raw_pool:
        for line in raw_pool.replace("\r\n", "\n").splitlines():
            text = line.strip()
            if not text:
                continue
            parts = re.split(r"\s*-{4,}\s*", text, maxsplit=1)
            if len(parts) != 2:
                continue
            phone = parts[0].strip()
            record_url = parts[1].strip()
            if phone and record_url:
                pool.append({"phone": phone, "sms_record_url": record_url})
        return pool
    phones = _split_protocol_values(getattr(req, "phone", ""))
    record_urls = _split_protocol_values(getattr(req, "sms_record_url", ""))
    return [
        {"phone": phone, "sms_record_url": record_urls[index]}
        for index, phone in enumerate(phones)
        if index < len(record_urls) and phone and record_urls[index]
    ]


def _claim_sms_record_phone_pool_item(pool: list[dict[str, str]], lock: threading.Lock) -> dict[str, str]:
    with lock:
        if not pool:
            raise RuntimeError("SMS record 号池已领完")
        return pool.pop(0)


def _protocol_links_by_email() -> dict[str, dict[str, Any]]:
    links: dict[str, dict[str, Any]] = {}
    for item in _load_links():
        email = str(item.get("account_email") or "").strip().lower()
        link = str(item.get("paypal_link") or item.get("provider_redirect_url") or item.get("stripe_redirect_url") or "").strip()
        token = extract_protocol_ba_token(link or str(item.get("ba_token") or ""))
        if email and token and email not in links:
            links[email] = item
    return links


def _protocol_batch_tasks(req: UsPaypalProtocolBatchStartRequest) -> list[dict[str, Any]]:
    links_by_email = _protocol_links_by_email()
    tasks: list[dict[str, Any]] = []
    for email in req.account_emails:
        key = str(email or "").strip().lower()
        link = links_by_email.get(key)
        if not link:
            continue
        paypal_link = str(link.get("paypal_link") or link.get("provider_redirect_url") or link.get("stripe_redirect_url") or link.get("ba_token") or "")
        ba_token = extract_protocol_ba_token(paypal_link)
        if not ba_token:
            continue
        country = _link_country_from_item(link) or req.country
        tasks.append({"email": str(email).strip(), "ba_token": ba_token, "paypal_link": paypal_link, "country": country})
    return tasks


def _validate_protocol_batch_start(req: UsPaypalProtocolBatchStartRequest) -> list[dict[str, Any]]:
    if not req.account_emails:
        raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "请选择要支付的已提链账号"})
    tasks = _protocol_batch_tasks(req)
    if not tasks:
        raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "请选择已成功提链且包含有效 BA 链接的账号"})
    sms_provider = paypal_protocol_service.normalize_sms_provider(req.sms_provider)
    phones = _split_protocol_values(req.phone)
    if sms_provider == "sms_record":
        if len(_sms_record_phone_pool(req)) < len(tasks):
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "协议支付号池数量不足；请按“手机号----SMS record URL”每行导入一个号码"})
    elif sms_provider == "hero_sms_rent" and len(phones) < len(tasks):
        raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "HeroSMS 长效号支付时每个账号都需要分配一个长效号码"})
    elif sms_provider not in {"hero_sms", "smsbower", "hero_sms_rent"}:
        raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "不支持的 PayPal 手机接码平台"})
    unsupported = sorted({task["country"] for task in tasks if task["country"] not in paypal_protocol_service.SUPPORTED_PAYPAL_PROTOCOL_COUNTRIES})
    if unsupported:
        countries_text = paypal_protocol_service.SUPPORTED_PAYPAL_PROTOCOL_COUNTRIES_TEXT
        raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": f"当前协议支付仅开放 {countries_text}，不支持：{', '.join(unsupported)}"})
    return tasks


def _run_protocol_payment_job(job_id: str, req: UsPaypalProtocolStartRequest) -> None:
    def log(message: str) -> None:
        _append_log(job_id, sanitize_protocol_log_text(message))

    try:
        ba_token = extract_protocol_ba_token(req.ba_token or req.paypal_link)
        if not ba_token:
            raise RuntimeError("缺少有效 PayPal BA token/link")
        proxy_candidates = _parse_proxies(req.proxy_url) or _parse_proxies(req.proxies)
        sms_provider = paypal_protocol_service.normalize_sms_provider(req.sms_provider)
        phone = str(req.phone or "").strip()
        sms_record_url = str(req.sms_record_url or "").strip()
        if sms_provider == "sms_record":
            if not phone or not sms_record_url:
                pool = _sms_record_phone_pool(req)
                if pool:
                    phone = pool[0]["phone"]
                    sms_record_url = pool[0]["sms_record_url"]
            if not phone:
                raise RuntimeError("请填写 PayPal 注册手机号")
            if not sms_record_url:
                raise RuntimeError("请填写 SMS record URL")
        elif sms_provider == "hero_sms_rent" and not phone:
            raise RuntimeError("请填写 HeroSMS 长效号码")
        account_email = str(req.account_email or "").strip()
        with JOBS_LOCK:
            if job_id not in JOBS:
                return
            JOBS[job_id]["status"] = "running"
            JOBS[job_id]["running_count"] = 1
        log(f"PayPal 协议支付开始：country={req.country} ba_token={ba_token}")
        proxy_url = _preflight_protocol_proxy_or_raise(proxy_candidates, req.country, log, req.proxy_preflight_attempts)
        cfg = PaypalProtocolRunConfig(
            ba_token=ba_token,
            phone=phone,
            sms_record_url=sms_record_url,
            sms_provider=sms_provider,
            # Provider API key/base/service/country/price are fixed backend
            # configuration.  Keep request fields only for backward-compatible
            # parsing; do not trust or forward web payload overrides.
            sms_api_key="",
            sms_base_url="",
            sms_service="",
            sms_country="",
            sms_min_price="",
            sms_max_price="",
            sms_preferred_price="",
            proxy_url=proxy_url,
            country=req.country,
            timeout_seconds=req.timeout_seconds,
            sms_record_wait_seconds=req.sms_record_wait_seconds,
            sms_record_poll_seconds=req.sms_record_poll_seconds,
            phone_pool_reuse_enabled=bool(req.phone_pool_reuse_enabled),
            debug=req.debug,
        )
        result = run_paypal_protocol_payment(
            cfg,
            log=log,
            cancel_check=lambda: _is_job_cancel_requested(job_id),
        )
        terminal = str(result.get("status") or "").lower()
        ok = terminal == "success"
        if ok and account_email:
            _mark_account_plus_paypal(account_email, "PayPal protocol approval success")
            _set_account_status(account_email, PAYPAL_STATUS_PAID, job_id=job_id)
        with JOBS_LOCK:
            if job_id not in JOBS:
                return
            JOBS[job_id]["status"] = "success" if ok else ("cancelled" if terminal == "cancelled" else "error")
            JOBS[job_id]["result"] = result
            JOBS[job_id]["error"] = "" if ok else str(result.get("message") or "协议支付失败")
            JOBS[job_id]["completed"] = 1
            JOBS[job_id]["running_count"] = 0
            JOBS[job_id]["finished_at"] = time.time()
        log("PayPal 协议支付完成" if ok else f"PayPal 协议支付未成功：{result.get('message') or terminal}")
    except Exception as exc:
        error = sanitize_protocol_log_text(str(exc))
        with JOBS_LOCK:
            if job_id not in JOBS:
                return
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error"] = error
            JOBS[job_id]["completed"] = 1
            JOBS[job_id]["running_count"] = 0
            JOBS[job_id]["finished_at"] = time.time()
        _append_log(job_id, f"协议支付失败: {error}")


def _run_protocol_batch_account(
    job_id: str,
    req: UsPaypalProtocolBatchStartRequest,
    task: dict[str, Any],
    index: int,
    total: int,
    proxies: list[str],
    phones: list[str],
    record_urls: list[str],
    sms_record_pool: list[dict[str, str]] | None = None,
    sms_record_pool_lock: threading.Lock | None = None,
) -> dict[str, Any]:
    email = str(task.get("email") or "").strip()
    started = time.monotonic()
    if _is_job_cancel_requested(job_id):
        _append_log(job_id, f"[{index}/{total}] 跳过协议支付：{email}（任务已取消）")
        return {"skipped": True, "email": email, "reason": "任务已取消", "status": _set_account_status(email, PAYPAL_STATUS_SUCCESS, job_id=job_id)}

    sms_provider = paypal_protocol_service.normalize_sms_provider(req.sms_provider)
    phone = _protocol_value_for_index(phones, index) if sms_provider in {"sms_record", "hero_sms_rent"} else ""
    sms_record_url = _protocol_value_for_index(record_urls, index) if sms_provider == "sms_record" else ""
    proxy_candidates = _rotate_proxies_for_account(proxies, index)
    proxy_slot = f" proxy槽={(index - 1) % len(proxies) + 1}/{len(proxies)}" if proxies else " no-proxy"
    _set_job_running_delta(job_id, 1)
    running_status = _set_account_status(email, PAYPAL_STATUS_RUNNING, job_id=job_id)
    _set_job_account_status(job_id, email, running_status)
    _append_log(job_id, f"[{index}/{total}] PayPal 协议支付开始：{email} country={task.get('country')}{proxy_slot}")

    def account_log(message: str) -> None:
        _append_log(job_id, f"[{index}/{total}] {message}")

    try:
        if sms_provider == "sms_record" and sms_record_pool is not None and sms_record_pool_lock is not None:
            pool_item = _claim_sms_record_phone_pool_item(sms_record_pool, sms_record_pool_lock)
            phone = pool_item["phone"]
            sms_record_url = pool_item["sms_record_url"]
        proxy_url = _preflight_protocol_proxy_or_raise(
            proxy_candidates,
            str(task.get("country") or req.country),
            account_log,
            req.proxy_preflight_attempts,
        )
        cfg = PaypalProtocolRunConfig(
            ba_token=str(task.get("ba_token") or ""),
            paypal_link=str(task.get("paypal_link") or ""),
            phone=phone,
            sms_record_url=sms_record_url,
            sms_provider=sms_provider,
            sms_api_key="",
            sms_base_url="",
            sms_service="",
            sms_country="",
            sms_min_price="",
            sms_max_price="",
            sms_preferred_price="",
            proxy_url=proxy_url,
            country=str(task.get("country") or req.country),
            timeout_seconds=req.timeout_seconds,
            sms_record_wait_seconds=req.sms_record_wait_seconds,
            sms_record_poll_seconds=req.sms_record_poll_seconds,
            phone_pool_reuse_enabled=bool(req.phone_pool_reuse_enabled),
            debug=req.debug,
        )
        result = run_paypal_protocol_payment(
            cfg,
            log=account_log,
            cancel_check=lambda: _is_job_cancel_requested(job_id),
        )
        terminal = str(result.get("status") or "").lower()
        if terminal == "success":
            _mark_account_plus_paypal(email, "PayPal protocol approval success")
            status = _set_account_status(email, PAYPAL_STATUS_PAID, job_id=job_id)
            compact = {"email": email, "elapsed_s": round(time.monotonic() - started, 1), "country": cfg.country, "phone": phone, "sms_record_url": sms_record_url, "result": result}
            _append_log(job_id, f"[{index}/{total}] 协议支付成功：{email}")
            return {"ok": True, "email": email, "success": compact, "status": status}
        if terminal == "cancelled":
            status = _set_account_status(email, PAYPAL_STATUS_SUCCESS, error="协议支付已取消", job_id=job_id)
            return {"skipped": True, "email": email, "phone": phone, "sms_record_url": sms_record_url, "reason": "协议支付已取消", "status": status}
        message = str(result.get("message") or terminal or "协议支付失败")
        status = _set_account_status(email, PAYPAL_STATUS_FAILED, error=message, job_id=job_id)
        _append_log(job_id, f"[{index}/{total}] 协议支付失败：{email} {message}")
        return {
            "ok": False,
            "email": email,
            "error": {"email": email, "elapsed_s": round(time.monotonic() - started, 1), "country": cfg.country, "phone": phone, "sms_record_url": sms_record_url, "error": message, "result": result},
            "status": status,
        }
    except Exception as exc:
        error = sanitize_protocol_log_text(str(exc))
        status = _set_account_status(email, PAYPAL_STATUS_FAILED, error=error, job_id=job_id)
        _append_log(job_id, f"[{index}/{total}] 协议支付异常：{email} {error}")
        return {
            "ok": False,
            "email": email,
            "error": {"email": email, "elapsed_s": round(time.monotonic() - started, 1), "country": task.get("country"), "phone": phone, "sms_record_url": sms_record_url, "error": error},
            "status": status,
        }
    finally:
        _set_job_running_delta(job_id, -1)


def _run_protocol_batch_payment_job(job_id: str, req: UsPaypalProtocolBatchStartRequest) -> None:
    def log(message: str) -> None:
        _append_log(job_id, sanitize_protocol_log_text(message))

    try:
        tasks = _validate_protocol_batch_start(req)
        sms_provider = paypal_protocol_service.normalize_sms_provider(req.sms_provider)
        proxies = _parse_proxies(req.proxies or req.proxy_url)
        phones = _split_protocol_values(req.phone)
        record_urls = _split_protocol_values(req.sms_record_url)
        sms_record_pool = _sms_record_phone_pool(req)
        sms_record_pool_lock = threading.Lock()
        concurrency = _protocol_batch_concurrency(req, len(tasks))
        successes: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        account_statuses: dict[str, dict[str, Any]] = {}
        for task in tasks:
            email = str(task.get("email") or "")
            if email:
                account_statuses[email] = _set_account_status(email, PAYPAL_STATUS_PENDING, job_id=job_id)
        with JOBS_LOCK:
            if job_id not in JOBS:
                return
            cancel_requested = bool(JOBS[job_id].get("cancel_requested"))
            JOBS[job_id]["status"] = "cancelling" if cancel_requested else "running"
            JOBS[job_id]["total"] = len(tasks)
            JOBS[job_id]["completed"] = 0
            JOBS[job_id]["concurrency"] = concurrency
            JOBS[job_id]["running_count"] = 0
            JOBS[job_id]["cancel_requested"] = cancel_requested
            JOBS[job_id]["skipped"] = []
            JOBS[job_id]["account_statuses"] = account_statuses
        log(f"PayPal 协议批量支付开始：{len(tasks)} 个账号，并发 {concurrency}，接码={sms_provider}，代理={len(proxies)} 条")

        completed = 0
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [
                executor.submit(_run_protocol_batch_account, job_id, req, task, index, len(tasks), proxies, phones, record_urls, sms_record_pool, sms_record_pool_lock)
                for index, task in enumerate(tasks, start=1)
            ]
            for future in as_completed(futures):
                item = future.result()
                email = str(item.get("email") or "")
                if item.get("skipped"):
                    skipped.append({"email": email, "reason": item.get("reason") or "任务已取消"})
                elif item.get("ok"):
                    successes.append(item["success"])
                else:
                    errors.append(item["error"])
                if email:
                    account_statuses[email] = item.get("status") or {}
                completed += 1
                with JOBS_LOCK:
                    if job_id not in JOBS:
                        return
                    JOBS[job_id]["completed"] = completed
                    JOBS[job_id]["account_statuses"] = account_statuses
                    JOBS[job_id]["skipped"] = skipped
                    JOBS[job_id]["result"] = {"batch": True, "successes": successes, "errors": errors, "skipped": skipped}
        with JOBS_LOCK:
            if job_id not in JOBS:
                return
            cancelled = bool(JOBS[job_id].get("cancel_requested"))
            has_non_error_outcome = bool(successes or skipped)
            JOBS[job_id]["status"] = "cancelled" if cancelled else ("success" if has_non_error_outcome else "error")
            JOBS[job_id]["error"] = "任务已取消" if cancelled else ("" if has_non_error_outcome else "全部账号支付失败")
            JOBS[job_id]["finished_at"] = time.time()
        log(f"PayPal 协议批量支付完成：成功 {len(successes)}，失败 {len(errors)}，跳过 {len(skipped)}")
    except HTTPException as exc:
        message = exc.detail.get("message") if isinstance(exc.detail, dict) else str(exc.detail)
        with JOBS_LOCK:
            if job_id not in JOBS:
                return
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error"] = str(message or "协议批量支付失败")
            JOBS[job_id]["finished_at"] = time.time()
        log(f"协议批量支付失败: {message}")
    except Exception as exc:
        error = sanitize_protocol_log_text(str(exc))
        with JOBS_LOCK:
            if job_id not in JOBS:
                return
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error"] = error
            JOBS[job_id]["finished_at"] = time.time()
        log(f"协议批量支付失败: {error}")


class Pay153Client:
    def __init__(self, base_url: str = PAY153_API_BASE):
        self.base_url = str(base_url or PAY153_API_BASE).rstrip("/")
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookie_jar))
        self._lock = threading.RLock()

    def cookie_snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "version": cookie.version,
                    "name": cookie.name,
                    "value": cookie.value,
                    "port": cookie.port,
                    "port_specified": cookie.port_specified,
                    "domain": cookie.domain,
                    "domain_specified": cookie.domain_specified,
                    "domain_initial_dot": cookie.domain_initial_dot,
                    "path": cookie.path,
                    "path_specified": cookie.path_specified,
                    "secure": cookie.secure,
                    "expires": cookie.expires,
                    "discard": cookie.discard,
                    "comment": cookie.comment,
                    "comment_url": cookie.comment_url,
                    "rest": dict(getattr(cookie, "_rest", {}) or {}),
                    "rfc2109": cookie.rfc2109,
                }
                for cookie in self.cookie_jar
            ]

    @classmethod
    def from_cookie_snapshot(cls, cookies: list[dict[str, Any]] | None, base_url: str = PAY153_API_BASE) -> "Pay153Client":
        client = cls(base_url=base_url)
        for item in cookies or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            if not name:
                continue
            cookie = http.cookiejar.Cookie(
                version=int(item.get("version") or 0),
                name=name,
                value=str(item.get("value") or ""),
                port=item.get("port"),
                port_specified=bool(item.get("port_specified")),
                domain=str(item.get("domain") or ""),
                domain_specified=bool(item.get("domain_specified")),
                domain_initial_dot=bool(item.get("domain_initial_dot")),
                path=str(item.get("path") or "/"),
                path_specified=bool(item.get("path_specified", True)),
                secure=bool(item.get("secure")),
                expires=item.get("expires"),
                discard=bool(item.get("discard", True)),
                comment=item.get("comment"),
                comment_url=item.get("comment_url"),
                rest=dict(item.get("rest") or {}),
                rfc2109=bool(item.get("rfc2109")),
            )
            client.cookie_jar.set_cookie(cookie)
        return client

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None, timeout: float = 30.0) -> dict[str, Any]:
        clean_path = "/" + str(path or "").lstrip("/")
        body = None
        headers = {"Accept": "application/json", "User-Agent": "AutoToken/Pay153Proxy"}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(f"{self.base_url}{clean_path}", data=body, headers=headers, method=str(method or "GET").upper())
        try:
            with self._lock:
                with self.opener.open(request, timeout=timeout) as response:
                    raw = response.read().decode("utf-8", errors="replace")
                    return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                data = {}
            message = data.get("error") or data.get("message") or raw or f"HTTP {exc.code}"
            raise RuntimeError(str(message)) from exc
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"153 API 请求失败: {exc}") from exc


def _new_pay153_client() -> Pay153Client:
    return Pay153Client()


def _pay153_request(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 30.0,
    client: Pay153Client | None = None,
) -> dict[str, Any]:
    if client is not None:
        return client.request(method, path, payload, timeout)
    clean_path = "/" + str(path or "").lstrip("/")
    body = None
    headers = {"Accept": "application/json", "User-Agent": "AutoToken/Pay153Proxy"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(f"{PAY153_API_BASE}{clean_path}", data=body, headers=headers, method=str(method or "GET").upper())
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            data = {}
        message = data.get("error") or data.get("message") or raw or f"HTTP {exc.code}"
        raise RuntimeError(str(message)) from exc
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"153 API 请求失败: {exc}") from exc


def _pay153_create_job(paypal_url: str, phone: str, country: str, proxies: list[str], buyer_mode: str, client: Pay153Client | None = None) -> dict[str, Any]:
    return _pay153_request(
        "POST",
        "/jobs",
        {
            "paypal_url": paypal_url,
            "phone": phone,
            "country": country,
            "proxies": proxies,
            "agreement_only": False,
            "buyer_mode": buyer_mode,
        },
        timeout=45.0,
        client=client,
    )


def _pay153_get_job(remote_job_id: str, client: Pay153Client | None = None) -> dict[str, Any]:
    return _pay153_request("GET", f"/jobs/{urllib.parse.quote(str(remote_job_id), safe='')}?log_offset=0", timeout=30.0, client=client)


def _pay153_list_jobs(client: Pay153Client | None = None) -> dict[str, Any]:
    return _pay153_request("GET", "/jobs?limit=200", timeout=30.0, client=client)


def _pay153_submit_otp(remote_job_id: str, value: str, client: Pay153Client | None = None) -> dict[str, Any]:
    return _pay153_request("POST", f"/jobs/{urllib.parse.quote(str(remote_job_id), safe='')}/otp", {"value": value}, timeout=30.0, client=client)


def _pay153_submit_captcha(remote_job_id: str, value: str, client: Pay153Client | None = None) -> dict[str, Any]:
    return _pay153_request("POST", f"/jobs/{urllib.parse.quote(str(remote_job_id), safe='')}/captcha", {"value": value}, timeout=30.0, client=client)


def _pay153_cancel_job(remote_job_id: str, client: Pay153Client | None = None) -> dict[str, Any]:
    return _pay153_request("POST", f"/jobs/{urllib.parse.quote(str(remote_job_id), safe='')}/cancel", {}, timeout=30.0, client=client)


def _pay153_normalize_ba_token(value: str) -> str:
    text = str(value or "").strip()
    return extract_protocol_ba_token(text) or (text if text.upper().startswith("BA-") else "")


def _pay153_job_matches_ba(remote_job: dict[str, Any], ba_token: str) -> bool:
    target = _pay153_normalize_ba_token(ba_token)
    if not target:
        return False
    candidates = [
        remote_job.get("ba_token"),
        remote_job.get("paypal_url"),
        remote_job.get("paypal_link"),
        remote_job.get("url"),
    ]
    result = remote_job.get("result")
    if isinstance(result, dict):
        candidates.extend([result.get("ba_token"), result.get("paypal_url"), result.get("paypal_link")])
    return any(_pay153_normalize_ba_token(str(value or "")) == target for value in candidates)


def _load_pay153_remote_tasks() -> dict[str, dict[str, Any]]:
    with PAY153_REMOTE_TASKS_LOCK:
        data = _read_json(PAY153_REMOTE_TASKS_FILE, {})
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = list(data.values())
    else:
        items = []
    tasks: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        remote_job_id = str(item.get("remote_job_id") or item.get("id") or "").strip()
        if not remote_job_id:
            continue
        tasks[remote_job_id] = {**item, "remote_job_id": remote_job_id}
    return tasks


def _save_pay153_remote_tasks(tasks: dict[str, dict[str, Any]]) -> None:
    clean: dict[str, dict[str, Any]] = {}
    for remote_job_id, item in (tasks or {}).items():
        if not isinstance(item, dict):
            continue
        clean_remote = str(item.get("remote_job_id") or remote_job_id or "").strip()
        if not clean_remote:
            continue
        clean[clean_remote] = {**item, "remote_job_id": clean_remote}
    with PAY153_REMOTE_TASKS_LOCK:
        _write_json(PAY153_REMOTE_TASKS_FILE, clean)


def _persist_pay153_remote_task(job_id: str, child: dict[str, Any], client: Pay153Client | None = None) -> None:
    if not isinstance(child, dict):
        return
    remote_job_id = str(child.get("remote_job_id") or "").strip()
    if not remote_job_id:
        return
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with PAY153_REMOTE_TASKS_LOCK:
        tasks = _read_json(PAY153_REMOTE_TASKS_FILE, {})
        tasks = tasks if isinstance(tasks, dict) else {}
        previous = tasks.get(remote_job_id) if isinstance(tasks.get(remote_job_id), dict) else {}
        cookies = client.cookie_snapshot() if isinstance(client, Pay153Client) else previous.get("cookies", [])
        base_url = client.base_url if isinstance(client, Pay153Client) else previous.get("base_url", PAY153_API_BASE)
        tasks[remote_job_id] = {
            **previous,
            "remote_job_id": remote_job_id,
            "local_job_id": str(job_id or previous.get("local_job_id") or ""),
            "email": str(child.get("email") or previous.get("email") or ""),
            "country": str(child.get("country") or previous.get("country") or ""),
            "ba_token": _pay153_normalize_ba_token(str(child.get("ba_token") or previous.get("ba_token") or "")),
            "paypal_link": str(child.get("paypal_link") or previous.get("paypal_link") or ""),
            "status": str(child.get("status") or previous.get("status") or "").strip().lower(),
            "stage": str(child.get("stage") or previous.get("stage") or ""),
            "error": str(child.get("error") or previous.get("error") or ""),
            "base_url": str(base_url or PAY153_API_BASE),
            "cookies": cookies,
            "created_at": previous.get("created_at") or now,
            "updated_at": now,
        }
        _write_json(PAY153_REMOTE_TASKS_FILE, tasks)


def _mark_pay153_remote_task_status(remote_job_id: str, status: str, error: str = "") -> None:
    clean_remote = str(remote_job_id or "").strip()
    if not clean_remote:
        return
    with PAY153_REMOTE_TASKS_LOCK:
        tasks = _read_json(PAY153_REMOTE_TASKS_FILE, {})
        if not isinstance(tasks, dict):
            return
        item = tasks.get(clean_remote)
        if not isinstance(item, dict):
            return
        item["status"] = str(status or "").strip().lower()
        if error:
            item["error"] = str(error)
        item["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        tasks[clean_remote] = item
        _write_json(PAY153_REMOTE_TASKS_FILE, tasks)


def _mark_pay153_remote_task_error(remote_job_id: str, error: str) -> None:
    clean_remote = str(remote_job_id or "").strip()
    if not clean_remote:
        return
    with PAY153_REMOTE_TASKS_LOCK:
        tasks = _read_json(PAY153_REMOTE_TASKS_FILE, {})
        if not isinstance(tasks, dict):
            return
        item = tasks.get(clean_remote)
        if not isinstance(item, dict):
            return
        item["error"] = str(error or "")
        item["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        tasks[clean_remote] = item
        _write_json(PAY153_REMOTE_TASKS_FILE, tasks)


def _pay153_client_from_persisted_task(item: dict[str, Any]) -> Pay153Client:
    return Pay153Client.from_cookie_snapshot(
        item.get("cookies") if isinstance(item.get("cookies"), list) else [],
        base_url=str(item.get("base_url") or PAY153_API_BASE),
    )


def _pay153_cancel_persisted_jobs_for_ba(ba_token_or_url: str, *, skip: set[str] | None = None) -> list[str]:
    target = _pay153_normalize_ba_token(ba_token_or_url)
    if not target:
        return []
    cancelled: list[str] = []
    seen = set(skip or set())
    persisted_candidates = [
        item
        for item in _load_pay153_remote_tasks().values()
        if str(item.get("status") or "").strip().lower() not in PAY153_REMOTE_TERMINAL_STATUSES
        and _pay153_job_matches_ba(item, target)
    ]
    for item in persisted_candidates:
        remote_job_id = str(item.get("remote_job_id") or "").strip()
        if not remote_job_id or remote_job_id in seen:
            continue
        persisted_client = _pay153_client_from_persisted_task(item)
        try:
            _pay153_cancel_job(remote_job_id, client=persisted_client)
        except Exception as exc:
            _mark_pay153_remote_task_error(remote_job_id, sanitize_protocol_log_text(str(exc)))
            continue
        cancelled.append(remote_job_id)
        seen.add(remote_job_id)
        _mark_pay153_remote_task_status(remote_job_id, "cancelled", "已按 BA 清理重启前远端卡住任务")
    return cancelled


def _pay153_cancel_existing_jobs_for_ba(ba_token_or_url: str, client: Pay153Client | None = None) -> list[str]:
    target = _pay153_normalize_ba_token(ba_token_or_url)
    if not target:
        return []
    cancelled: list[str] = []
    local_candidates: list[tuple[str, str, Any]] = []
    with JOBS_LOCK:
        for local_job_id, local_job in JOBS.items():
            if not isinstance(local_job, dict) or local_job.get("kind") != "paypal_153_payment":
                continue
            clients = local_job.get("pay153_clients") if isinstance(local_job.get("pay153_clients"), dict) else {}
            children = local_job.get("children") if isinstance(local_job.get("children"), dict) else {}
            for remote_job_id, child in children.items():
                if not isinstance(child, dict):
                    continue
                status = str(child.get("status") or "").strip().lower()
                if status in {"completed", "failed", "cancelled"}:
                    continue
                if not _pay153_job_matches_ba(child, target):
                    continue
                clean_remote = str(child.get("remote_job_id") or remote_job_id or "").strip()
                if clean_remote:
                    local_candidates.append((str(local_job_id), clean_remote, clients.get(clean_remote)))
    for local_job_id, remote_job_id, local_client in local_candidates:
        _pay153_cancel_job(remote_job_id, client=local_client)
        cancelled.append(remote_job_id)
        _mark_pay153_remote_task_status(remote_job_id, "cancelled", "已按 BA 清理远端卡住任务")
        with JOBS_LOCK:
            local_job = JOBS.get(local_job_id)
            child = ((local_job or {}).get("children") or {}).get(remote_job_id) if isinstance(local_job, dict) else None
            if isinstance(child, dict):
                child["status"] = "cancelled"
                child["error"] = "已按 BA 清理远端卡住任务"
                child["awaiting_otp"] = False
                child["awaiting_captcha"] = False

    cancelled.extend(_pay153_cancel_persisted_jobs_for_ba(target, skip=set(cancelled)))

    try:
        data = _pay153_list_jobs(client=client)
    except Exception:
        if cancelled:
            return cancelled
        raise
    jobs = data.get("jobs") if isinstance(data, dict) else []
    for remote_job in jobs if isinstance(jobs, list) else []:
        if not isinstance(remote_job, dict):
            continue
        status = str(remote_job.get("status") or "").strip().lower()
        if status in {"completed", "failed", "cancelled"}:
            continue
        if not _pay153_job_matches_ba(remote_job, target):
            continue
        remote_job_id = str(remote_job.get("id") or remote_job.get("job_id") or "").strip()
        if not remote_job_id or remote_job_id in cancelled:
            continue
        _pay153_cancel_job(remote_job_id, client=client)
        cancelled.append(remote_job_id)
        _mark_pay153_remote_task_status(remote_job_id, "cancelled", "已按 BA 清理远端卡住任务")
    return cancelled


def _pay153_is_already_processing_error(message: str) -> bool:
    return "already being processed" in str(message or "").lower()


def _split_pay153_values(value: str | list[str]) -> list[str]:
    if isinstance(value, list):
        return [str(item or "").strip() for item in value if str(item or "").strip()]
    return [item.strip() for item in str(value or "").replace(",", "\n").splitlines() if item.strip()]


def _pay153_sms_record_pool(req: UsPaypal153BatchStartRequest) -> list[dict[str, str]]:
    pool: list[dict[str, str]] = []
    raw_pool = str(req.phone_pool or "").strip()
    if raw_pool:
        for line in raw_pool.replace("\r\n", "\n").splitlines():
            text = line.strip()
            if not text:
                continue
            parts = re.split(r"\s*-{4,}\s*", text, maxsplit=1)
            if len(parts) != 2:
                continue
            phone = parts[0].strip()
            record_url = parts[1].strip()
            if phone and record_url:
                pool.append({"phone": phone, "sms_record_url": record_url})
        return pool
    phones = _split_pay153_values(req.phone)
    record_urls = _split_pay153_values(req.sms_record_url)
    return [
        {"phone": phone, "sms_record_url": record_urls[index]}
        for index, phone in enumerate(phones)
        if index < len(record_urls) and phone and record_urls[index]
    ]


def _claim_pay153_sms_record_pool_item(pool: list[dict[str, str]], lock: threading.Lock) -> dict[str, str]:
    with lock:
        if not pool:
            raise RuntimeError("153支付号池已领完")
        return pool.pop(0)


def _pay153_batch_concurrency(req: UsPaypal153BatchStartRequest, total: int) -> int:
    try:
        requested = int(req.concurrency or 1)
    except Exception:
        requested = 1
    return max(1, min(MAX_PROTOCOL_BATCH_CONCURRENCY, total, requested))


def _pay153_remote_job_from_response(data: dict[str, Any]) -> dict[str, Any]:
    if isinstance(data.get("job"), dict):
        return data["job"]
    return data


class Pay153SmsRecordActivation:
    def __init__(self, phone_number: str):
        self.activation_id = "pay153-sms-record"
        self.phone_number = phone_number
        self.provider_id = "sms_record"
        self.reused = True


class Pay153SmsRecordOtpProvider:
    def __init__(self, phone: str, record_url: str, wait_seconds: float = 300.0, poll_interval: float = 3.0):
        self.phone = str(phone or "").strip()
        self.record_url = str(record_url or "").strip()
        self.wait_seconds = max(30.0, float(wait_seconds or 300.0))
        self.poll_interval = max(1.0, float(poll_interval or 3.0))
        self._seen_codes: set[str] = set()
        self._sent_at = 0.0

    def reserve_number(self) -> Pay153SmsRecordActivation:
        return Pay153SmsRecordActivation(self.phone)

    def mark_sms_sent(self, activation: Any) -> None:
        self._sent_at = time.time()

    def abandon(self, activation: Any, reason: str) -> None:
        return None

    def register_confirmation_result(self, activation: Any, confirmed: bool) -> None:
        return None

    def _record_payload_text_and_time(self, raw: str) -> tuple[str, float | None]:
        try:
            payload = json.loads(raw)
        except Exception:
            return raw, None
        if not isinstance(payload, dict):
            return raw, None
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        text = json.dumps(data, ensure_ascii=False) if isinstance(data, (dict, list)) else str(data or raw)
        code_time = str(data.get("code_time") or data.get("time") or "").strip() if isinstance(data, dict) else ""
        if not code_time:
            return text, None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
            try:
                return text, time.mktime(time.strptime(code_time, fmt))
            except Exception:
                pass
        return text, None

    def wait_for_code(self, activation: Any, timeout_seconds: float | None = None) -> str | None:
        deadline = time.time() + float(timeout_seconds or self.wait_seconds)
        while time.time() < deadline:
            try:
                req = urllib.request.Request(self.record_url, headers={"User-Agent": "AutoToken/Pay153SmsRecord"})
                with urllib.request.urlopen(req, timeout=10) as response:
                    raw = response.read().decode("utf-8", errors="replace")
                text, code_ts = self._record_payload_text_and_time(raw)
                if self._sent_at and code_ts is not None and code_ts + 3 < self._sent_at:
                    time.sleep(self.poll_interval)
                    continue
                lowered = text.lower()
                candidates: list[tuple[int, int, str]] = []
                for match in re.finditer(r"(?<!\d)(\d{5,6})(?!\d)", text):
                    window = lowered[max(0, match.start() - 120):match.end() + 120]
                    score = 0 if any(token in window for token in ("paypal", "pay pal", "verification", "code", "验证码", "短信")) else 1
                    candidates.append((score, -match.start(), match.group(1)))
                for _score, _position, code in sorted(candidates):
                    if code not in self._seen_codes:
                        self._seen_codes.add(code)
                        return code
            except Exception:
                pass
            time.sleep(self.poll_interval)
        return None


def _build_pay153_otp_provider(sms_provider: str, phone: str, country: str, req: UsPaypal153BatchStartRequest) -> Any:
    normalized = paypal_protocol_service.normalize_sms_provider(sms_provider)
    if normalized == "sms_record":
        return Pay153SmsRecordOtpProvider(phone, str(req.sms_record_url or ""), req.sms_record_wait_seconds, req.sms_record_poll_seconds)
    from autotoken._paypal_protocol_engine.paypal import smsbower as paypal_sms_providers

    if normalized == "hero_sms_rent":
        return paypal_sms_providers.build_hero_sms_rent_provider(
            phone_number=phone,
            paypal_country=country,
            wait_seconds=req.sms_record_wait_seconds,
            poll_interval_seconds=req.sms_record_poll_seconds,
            reuse_enabled=bool(req.phone_pool_reuse_enabled),
        )
    if normalized in {"hero_sms", "smsbower"}:
        return paypal_sms_providers.build_sms_activate_provider(
            provider=normalized,
            paypal_country=country,
            wait_seconds=req.sms_record_wait_seconds,
            poll_interval_seconds=req.sms_record_poll_seconds,
            reuse_enabled=bool(req.phone_pool_reuse_enabled),
        )
    raise RuntimeError("不支持的 PayPal 手机接码平台")


def _new_pay153_batch_job(account_emails: list[str], concurrency: int = 1) -> str:
    job_id = "p153-" + uuid.uuid4().hex[:10]
    created = time.time()
    clean_emails = [str(email or "").strip() for email in account_emails if str(email or "").strip()]
    with JOBS_LOCK:
        JOBS[job_id] = {
            "id": job_id,
            "kind": "paypal_153_payment",
            "status": "queued",
            "logs": ["153支付任务已创建"],
            "result": None,
            "error": None,
            "created_at": created,
            "finished_at": None,
            "account_email": clean_emails[0] if len(clean_emails) == 1 else "",
            "total": len(clean_emails) or 1,
            "completed": 0,
            "concurrency": max(1, min(MAX_PROTOCOL_BATCH_CONCURRENCY, int(concurrency or 1))),
            "cancel_requested": False,
            "running_count": 0,
            "skipped": [],
            "account_statuses": {},
            "children": {},
            "pay153_clients": {},
        }
    return job_id


def _pay153_batch_tasks(req: UsPaypal153BatchStartRequest) -> list[dict[str, Any]]:
    links_by_email = _protocol_links_by_email()
    selected_country = str(req.country or "AUTO").strip().upper()
    tasks: list[dict[str, Any]] = []
    for email in req.account_emails:
        clean_email = str(email or "").strip()
        link = links_by_email.get(clean_email.lower())
        if not link:
            continue
        paypal_link = str(link.get("paypal_link") or link.get("provider_redirect_url") or link.get("stripe_redirect_url") or link.get("ba_token") or "")
        ba_token = extract_protocol_ba_token(paypal_link)
        if not ba_token:
            continue
        tasks.append({
            "email": clean_email,
            "ba_token": ba_token,
            "paypal_link": paypal_link,
            "country": selected_country if selected_country != "AUTO" else (_link_country_from_item(link) or "US"),
        })
    return tasks


def _validate_pay153_batch_start(req: UsPaypal153BatchStartRequest) -> list[dict[str, Any]]:
    if not req.account_emails:
        raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "请选择要使用 153 支付的已提链账号"})
    tasks = _pay153_batch_tasks(req)
    if not tasks:
        raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "请选择已成功提链且包含有效 BA 链接的账号"})
    sms_provider = paypal_protocol_service.normalize_sms_provider(req.sms_provider)
    phones = _split_pay153_values(req.phone)
    if sms_provider == "sms_record":
        if len(_pay153_sms_record_pool(req)) < len(tasks):
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "153支付号池数量不足；请按“手机号----SMS record URL”每行导入一个号码"})
    elif sms_provider == "hero_sms_rent":
        if len(phones) < len(tasks):
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "HeroSMS 长效号 153支付批量提交时，每个账号都需要一行长效号码"})
    elif sms_provider not in {"hero_sms", "smsbower"}:
        raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "不支持的 PayPal 手机接码平台"})
    proxies = _split_pay153_values(req.proxies)
    if not proxies:
        raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "153支付需要至少一条代理"})
    if len(proxies) > 500:
        raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "153支付代理池最多支持 500 条"})
    return tasks


def _pay153_child_snapshot(remote_job: dict[str, Any], *, email: str, country: str, ba_token: str, remote_job_id: str) -> dict[str, Any]:
    status = str(remote_job.get("status") or "").strip().lower()
    return {
        "email": email,
        "remote_job_id": remote_job_id,
        "country": country,
        "ba_token": ba_token,
        "status": status,
        "stage": str(remote_job.get("stage") or ""),
        "logs": list(remote_job.get("logs") or []) if isinstance(remote_job.get("logs"), list) else [],
        "result": remote_job.get("result") if isinstance(remote_job.get("result"), dict) else None,
        "error": str(remote_job.get("error") or ""),
        "awaiting_otp": bool(remote_job.get("awaiting_otp")),
        "awaiting_captcha": bool(remote_job.get("awaiting_captcha")),
        "awaiting_prompt": str(remote_job.get("awaiting_prompt") or ""),
        "challenge_url": str(remote_job.get("challenge_url") or ""),
        "cancellable": bool(remote_job.get("cancellable")),
    }


def _set_pay153_child(job_id: str, child: dict[str, Any]) -> None:
    client = None
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        children = job.setdefault("children", {})
        children[child["remote_job_id"]] = child
        clients = job.get("pay153_clients") if isinstance(job.get("pay153_clients"), dict) else {}
        client = clients.get(str(child.get("remote_job_id") or ""))
    _persist_pay153_remote_task(job_id, child, client if isinstance(client, Pay153Client) else None)


def _set_pay153_child_client(job_id: str, remote_job_id: str, client: Pay153Client) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        clients = job.setdefault("pay153_clients", {})
        clients[str(remote_job_id)] = client


def _get_pay153_child_client(job_id: str, remote_job_id: str) -> Any:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        clients = job.get("pay153_clients") or {}
        client = clients.get(str(remote_job_id))
    return client


def _get_owned_pay153_child(job_id: str, remote_job_id: str) -> dict[str, Any]:
    clean_remote = str(remote_job_id or "").strip()
    if not clean_remote:
        raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "remoteJobId required"})
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        children = job.get("children") or {}
        child = children.get(clean_remote)
        if not isinstance(child, dict):
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "remoteJobId 不属于当前 153支付任务"})
        return dict(child)


def _run_pay153_batch_account(
    job_id: str,
    req: UsPaypal153BatchStartRequest,
    task: dict[str, Any],
    index: int,
    total: int,
    phones: list[str],
    proxies: list[str],
    record_urls: list[str] | None = None,
    sms_record_pool: list[dict[str, str]] | None = None,
    sms_record_pool_lock: threading.Lock | None = None,
) -> dict[str, Any]:
    email = str(task.get("email") or "").strip()
    if _is_job_cancel_requested(job_id):
        _append_log(job_id, f"[{index}/{total}] 跳过153支付：{email}（任务已取消）")
        return {"skipped": True, "email": email, "reason": "任务已取消", "status": _set_account_status(email, PAYPAL_STATUS_SUCCESS, job_id=job_id)}

    _set_job_running_delta(job_id, 1)
    try:
        last_item: dict[str, Any] | None = None
        for retry_index in range(PAY153_ACCOUNT_MAX_RETRIES + 1):
            if retry_index > 0:
                if _is_job_cancel_requested(job_id):
                    _append_log(job_id, f"[{index}/{total}] 跳过153支付重试：{email}（任务已取消）")
                    return {"skipped": True, "email": email, "reason": "任务已取消", "status": _set_account_status(email, PAYPAL_STATUS_SUCCESS, job_id=job_id)}
                _append_log(job_id, f"[{index}/{total}] 153支付失败，准备重试 {retry_index}/{PAY153_ACCOUNT_MAX_RETRIES}：{email}")
            item = _run_pay153_batch_account_once(
                job_id,
                req,
                task,
                index,
                total,
                phones,
                proxies,
                record_urls,
                sms_record_pool,
                sms_record_pool_lock,
            )
            if item.get("ok") or item.get("skipped"):
                return item
            last_item = item
            if retry_index >= PAY153_ACCOUNT_MAX_RETRIES or not _pay153_account_failure_retryable(item):
                return item
        return last_item or {"ok": False, "email": email, "error": {"email": email, "error": "153支付失败"}, "status": _set_account_status(email, PAYPAL_STATUS_FAILED, error="153支付失败", job_id=job_id)}
    finally:
        _set_job_running_delta(job_id, -1)


def _pay153_account_failure_retryable(item: dict[str, Any]) -> bool:
    error = item.get("error") if isinstance(item, dict) else {}
    message = str(error.get("error") if isinstance(error, dict) else error or "")
    if _pay153_is_already_processing_error(message) and isinstance(error, dict) and error.get("remote_cancelled"):
        return True
    non_retryable_markers = (
        "验证码等待 60s 超时",
        "SMS record 号池已领完",
        "任务已取消",
        "153支付已取消",
        "already being processed",
        "This PayPal link is already being processed by another task",
    )
    return not any(marker in message for marker in non_retryable_markers)


def _run_pay153_batch_account_once(
    job_id: str,
    req: UsPaypal153BatchStartRequest,
    task: dict[str, Any],
    index: int,
    total: int,
    phones: list[str],
    proxies: list[str],
    record_urls: list[str] | None = None,
    sms_record_pool: list[dict[str, str]] | None = None,
    sms_record_pool_lock: threading.Lock | None = None,
) -> dict[str, Any]:
    email = str(task.get("email") or "").strip()
    country = str(task.get("country") or "US").strip().upper() or "US"
    ba_token = str(task.get("ba_token") or "")
    paypal_link = str(task.get("paypal_link") or ba_token)
    sms_provider = paypal_protocol_service.normalize_sms_provider(req.sms_provider)
    phone = _protocol_value_for_index(phones, index) if sms_provider in {"sms_record", "hero_sms_rent"} else ""
    record_url = _protocol_value_for_index(record_urls or [], index) if sms_provider == "sms_record" else ""
    if _is_job_cancel_requested(job_id):
        _append_log(job_id, f"[{index}/{total}] 跳过153支付：{email}（任务已取消）")
        return {"skipped": True, "email": email, "reason": "任务已取消", "status": _set_account_status(email, PAYPAL_STATUS_SUCCESS, job_id=job_id)}

    started = time.monotonic()
    running_status = _set_account_status(email, PAYPAL_STATUS_RUNNING, job_id=job_id)
    _set_job_account_status(job_id, email, running_status)
    _append_log(job_id, f"[{index}/{total}] 153支付开始：{email} country={country}")
    try:
        stale_cancelled = _pay153_cancel_persisted_jobs_for_ba(paypal_link)
        if stale_cancelled:
            _append_log(job_id, f"[{index}/{total}] 已预清理153重启前卡住任务：{email} remote={','.join(stale_cancelled)}")
    except Exception as stale_cancel_exc:
        _append_log(job_id, f"[{index}/{total}] 预清理153卡住任务失败：{email} {sanitize_protocol_log_text(str(stale_cancel_exc))}")
    otp_provider = None
    activation = None
    otp_marked_sent = False
    otp_code_submitted = False
    auto_change_phone_enabled = sms_provider in {"hero_sms", "smsbower"}
    pay153_otp_wait_seconds = 60.0 if auto_change_phone_enabled else req.sms_record_wait_seconds
    pay153_phone_change_count = 0
    pay153_max_phone_changes = 3
    try:
        if sms_provider == "sms_record" and sms_record_pool is not None and sms_record_pool_lock is not None:
            pool_item = _claim_pay153_sms_record_pool_item(sms_record_pool, sms_record_pool_lock)
            phone = pool_item["phone"]
            record_url = pool_item["sms_record_url"]
        provider_req = req.model_copy(update={"sms_record_url": record_url}) if sms_provider == "sms_record" else req
        otp_provider = _build_pay153_otp_provider(sms_provider, phone, country, provider_req)
        activation = otp_provider.reserve_number()
        phone = str(getattr(activation, "phone_number", None) or phone or "").strip()
        if not phone:
            raise RuntimeError("手机号供应商未返回可用号码")
        _append_log(job_id, f"[{index}/{total}] 153支付接码准备完成：{email} provider={sms_provider} phone={sanitize_protocol_log_text(phone)}")
        client = _new_pay153_client()
        created = _pay153_create_job(paypal_link, phone, country, proxies, req.buyer_mode, client=client)
        remote_job = _pay153_remote_job_from_response(created)
        remote_job_id = str(remote_job.get("id") or "")
        if not remote_job_id:
            raise RuntimeError("153 未返回远端任务 ID")
        _set_pay153_child_client(job_id, remote_job_id, client)
        child = _pay153_child_snapshot(remote_job, email=email, country=country, ba_token=ba_token, remote_job_id=remote_job_id)
        _set_pay153_child(job_id, child)
        if child["logs"]:
            for line in child["logs"]:
                _append_log(job_id, f"[{index}/{total}] {sanitize_protocol_log_text(str(line))}")
        while child["status"] not in {"completed", "failed", "cancelled"}:
            if _is_job_cancel_requested(job_id):
                break
            time.sleep(1.0)
            if child.get("awaiting_otp") and otp_provider is not None and activation is not None and not otp_code_submitted:
                if not otp_marked_sent and hasattr(otp_provider, "mark_sms_sent"):
                    otp_provider.mark_sms_sent(activation)
                    otp_marked_sent = True
                code = otp_provider.wait_for_code(activation, timeout_seconds=pay153_otp_wait_seconds) if hasattr(otp_provider, "wait_for_code") else None
                if code:
                    _append_log(job_id, f"[{index}/{total}] 已从 {sms_provider} 获取验证码并提交到153远端任务：{email}")
                    remote_job = _pay153_submit_otp(remote_job_id, str(code), client=client)
                    child = _pay153_child_snapshot(_pay153_remote_job_from_response(remote_job), email=email, country=country, ba_token=ba_token, remote_job_id=remote_job_id)
                    _set_pay153_child(job_id, child)
                    otp_code_submitted = True
                    continue
                if auto_change_phone_enabled:
                    if hasattr(otp_provider, "abandon"):
                        otp_provider.abandon(activation, "pay153_otp_timeout_60s_change_phone")
                    if pay153_phone_change_count >= pay153_max_phone_changes:
                        activation = None
                        raise RuntimeError(f"153支付验证码等待 60s 超时，已换号 {pay153_max_phone_changes} 次仍未收到验证码")
                    pay153_phone_change_count += 1
                    activation = otp_provider.reserve_number()
                    phone = str(getattr(activation, "phone_number", None) or "").strip()
                    if not phone:
                        raise RuntimeError("手机号供应商未返回可用号码")
                    otp_marked_sent = False
                    _append_log(job_id, f"[{index}/{total}] {sms_provider} 60s 未收到验证码，自动换号 {pay153_phone_change_count}/{pay153_max_phone_changes}：{email} phone={sanitize_protocol_log_text(phone)}")
                    remote_job = _pay153_submit_otp(remote_job_id, phone, client=client)
                    child = _pay153_child_snapshot(_pay153_remote_job_from_response(remote_job), email=email, country=country, ba_token=ba_token, remote_job_id=remote_job_id)
                    _set_pay153_child(job_id, child)
                    continue
            remote_job = _pay153_get_job(remote_job_id, client=client)
            child = _pay153_child_snapshot(remote_job, email=email, country=country, ba_token=ba_token, remote_job_id=remote_job_id)
            _set_pay153_child(job_id, child)
        if _is_job_cancel_requested(job_id) and child["status"] not in {"completed", "failed", "cancelled"}:
            child = {**child, "status": "cancelled", "error": "任务已取消", "awaiting_otp": False, "awaiting_captcha": False}
            _set_pay153_child(job_id, child)
            status = _set_account_status(email, PAYPAL_STATUS_SUCCESS, error="153支付已取消", job_id=job_id)
            return {"skipped": True, "email": email, "phone": phone, "sms_record_url": record_url, "reason": "任务已取消", "status": status}
        if child["status"] == "completed":
            if otp_provider is not None and activation is not None and hasattr(otp_provider, "register_confirmation_result"):
                otp_provider.register_confirmation_result(activation, True)
            _mark_account_plus_paypal(email, "PayPal 153 approval success")
            status = _set_account_status(email, PAYPAL_STATUS_PAID, job_id=job_id)
            compact = {"email": email, "elapsed_s": round(time.monotonic() - started, 1), "country": country, "phone": phone, "sms_record_url": record_url, "remote_job_id": remote_job_id, "result": child.get("result") or {}}
            _append_log(job_id, f"[{index}/{total}] 153支付成功：{email}")
            return {"ok": True, "email": email, "success": compact, "status": status}
        if child["status"] == "cancelled":
            status = _set_account_status(email, PAYPAL_STATUS_SUCCESS, error="153支付已取消", job_id=job_id)
            return {"skipped": True, "email": email, "phone": phone, "sms_record_url": record_url, "reason": "153支付已取消", "status": status}
        message = child.get("error") or child.get("stage") or "153支付失败"
        if otp_provider is not None and activation is not None and hasattr(otp_provider, "register_confirmation_result"):
            otp_provider.register_confirmation_result(activation, False)
        status = _set_account_status(email, PAYPAL_STATUS_FAILED, error=str(message), job_id=job_id)
        _append_log(job_id, f"[{index}/{total}] 153支付失败：{email} {message}")
        return {"ok": False, "email": email, "error": {"email": email, "elapsed_s": round(time.monotonic() - started, 1), "country": country, "phone": phone, "sms_record_url": record_url, "error": str(message), "remote_job_id": remote_job_id, "result": child.get("result") or {}}, "status": status}
    except Exception as exc:
        error = sanitize_protocol_log_text(str(exc))
        if otp_provider is not None and activation is not None and hasattr(otp_provider, "abandon"):
            otp_provider.abandon(activation, error)
        remote_cancelled: list[str] = []
        if _pay153_is_already_processing_error(error):
            try:
                remote_cancelled = _pay153_cancel_existing_jobs_for_ba(paypal_link, client=client)
                if remote_cancelled:
                    _append_log(job_id, f"[{index}/{total}] 已取消153远端卡住任务：{email} remote={','.join(remote_cancelled)}")
                else:
                    _append_log(job_id, f"[{index}/{total}] 未找到可取消的153远端卡住任务：{email} ba={ba_token}")
            except Exception as cancel_exc:
                cancel_error = sanitize_protocol_log_text(str(cancel_exc))
                _append_log(job_id, f"[{index}/{total}] 清理153远端卡住任务失败：{email} {cancel_error}")
        status = _set_account_status(email, PAYPAL_STATUS_FAILED, error=error, job_id=job_id)
        _append_log(job_id, f"[{index}/{total}] 153支付异常：{email} {error}")
        return {"ok": False, "email": email, "error": {"email": email, "elapsed_s": round(time.monotonic() - started, 1), "country": country, "phone": phone, "sms_record_url": record_url, "error": error, "remote_cancelled": remote_cancelled}, "status": status}


def _run_pay153_batch_payment_job(job_id: str, req: UsPaypal153BatchStartRequest) -> None:
    try:
        tasks = _validate_pay153_batch_start(req)
        phones = _split_pay153_values(req.phone)
        record_urls = _split_pay153_values(req.sms_record_url)
        sms_record_pool = _pay153_sms_record_pool(req)
        sms_record_pool_lock = threading.Lock()
        proxies = _split_pay153_values(req.proxies)
        concurrency = _pay153_batch_concurrency(req, len(tasks))
        successes: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        account_statuses: dict[str, dict[str, Any]] = {}
        for task in tasks:
            email = str(task.get("email") or "")
            if email:
                account_statuses[email] = _set_account_status(email, PAYPAL_STATUS_PENDING, job_id=job_id)
        with JOBS_LOCK:
            if job_id not in JOBS:
                return
            cancel_requested = bool(JOBS[job_id].get("cancel_requested"))
            JOBS[job_id]["status"] = "cancelling" if cancel_requested else "running"
            JOBS[job_id]["total"] = len(tasks)
            JOBS[job_id]["completed"] = 0
            JOBS[job_id]["concurrency"] = concurrency
            JOBS[job_id]["running_count"] = 0
            JOBS[job_id]["cancel_requested"] = cancel_requested
            JOBS[job_id]["skipped"] = []
            JOBS[job_id]["account_statuses"] = account_statuses
            JOBS[job_id]["children"] = {}
            JOBS[job_id]["pay153_clients"] = {}
        _append_log(job_id, f"153支付批量任务开始：{len(tasks)} 个账号，并发 {concurrency}，代理={len(proxies)} 条")
        completed = 0
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {
                executor.submit(_run_pay153_batch_account, job_id, req, task, index, len(tasks), phones, proxies, record_urls, sms_record_pool, sms_record_pool_lock): task
                for index, task in enumerate(tasks, start=1)
            }
            for future in as_completed(futures):
                try:
                    item = future.result()
                except Exception as exc:
                    task = futures.get(future) or {}
                    email = str(task.get("email") or "")
                    error = sanitize_protocol_log_text(str(exc))
                    _append_log(job_id, f"153支付账号任务异常：{email} {error}")
                    item = {
                        "ok": False,
                        "email": email,
                        "error": {"email": email, "error": error},
                        "status": _set_account_status(email, PAYPAL_STATUS_FAILED, error=error, job_id=job_id) if email else {},
                    }
                email = str(item.get("email") or "")
                if item.get("skipped"):
                    skipped.append({"email": email, "reason": item.get("reason") or "任务已取消"})
                elif item.get("ok"):
                    successes.append(item["success"])
                else:
                    errors.append(item["error"])
                if email:
                    account_statuses[email] = item.get("status") or {}
                completed += 1
                with JOBS_LOCK:
                    if job_id not in JOBS:
                        return
                    JOBS[job_id]["completed"] = completed
                    JOBS[job_id]["account_statuses"] = account_statuses
                    JOBS[job_id]["skipped"] = skipped
                    JOBS[job_id]["result"] = {"batch": True, "successes": successes, "errors": errors, "skipped": skipped}
        with JOBS_LOCK:
            if job_id not in JOBS:
                return
            cancelled = bool(JOBS[job_id].get("cancel_requested"))
            has_non_error_outcome = bool(successes or skipped)
            JOBS[job_id]["status"] = "cancelled" if cancelled else ("success" if has_non_error_outcome else "error")
            JOBS[job_id]["error"] = "任务已取消" if cancelled else ("" if has_non_error_outcome else "全部账号153支付失败")
            JOBS[job_id]["finished_at"] = time.time()
        _append_log(job_id, f"153支付批量任务完成：成功 {len(successes)}，失败 {len(errors)}，跳过 {len(skipped)}")
    except HTTPException as exc:
        message = exc.detail.get("message") if isinstance(exc.detail, dict) else str(exc.detail)
        with JOBS_LOCK:
            if job_id not in JOBS:
                return
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error"] = str(message or "153支付批量任务失败")
            JOBS[job_id]["finished_at"] = time.time()
        _append_log(job_id, f"153支付批量任务失败: {message}")
    except Exception as exc:
        error = sanitize_protocol_log_text(str(exc))
        with JOBS_LOCK:
            if job_id not in JOBS:
                return
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error"] = error
            JOBS[job_id]["finished_at"] = time.time()
        _append_log(job_id, f"153支付批量任务失败: {error}")


def create_us_paypal_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/us-paypal/accounts")
    def get_us_paypal_accounts() -> dict[str, Any]:
        return {"accounts": _iter_auth_accounts_with_paypal_status()}

    @router.delete("/api/us-paypal/accounts/{email}")
    def delete_us_paypal_account(email: str) -> dict[str, Any]:
        clean_email = str(email or "").strip()
        if not clean_email:
            raise HTTPException(status_code=400, detail="email required")
        return _delete_us_paypal_account_everywhere(clean_email)

    @router.post("/api/us-paypal/accounts/delete")
    def delete_us_paypal_accounts(req: UsPaypalDeleteAccountsRequest) -> dict[str, Any]:
        seen: set[str] = set()
        emails: list[str] = []
        for email in req.emails:
            clean_email = str(email or "").strip()
            key = clean_email.lower()
            if not clean_email or key in seen:
                continue
            seen.add(key)
            emails.append(clean_email)
        if not emails:
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "请选择要删除的账号"})
        results = [_delete_us_paypal_account_everywhere(email) for email in emails]
        return {"ok": True, "deleted": len(results), "results": results}

    @router.post("/api/us-paypal/start")
    def start_us_paypal(req: UsPaypalStartRequest) -> dict[str, str]:
        email = str(req.account_email or "").strip()
        if not email:
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "请选择要提链的账号"})
        job_id = _new_job([email], req.concurrency)
        threading.Thread(target=_run_batch_job, args=(job_id, UsPaypalBatchStartRequest(**req.model_dump() | {"account_emails": [email]})), daemon=True).start()
        return {"job_id": job_id}

    @router.post("/api/us-paypal/batch/start")
    def start_us_paypal_batch(req: UsPaypalBatchStartRequest) -> dict[str, str]:
        emails = list(req.account_emails)
        if req.max_accounts and req.max_accounts > 0:
            emails = emails[: int(req.max_accounts)]
        if not emails:
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "请选择要提链的账号"})
        job_id = _new_job(emails, req.concurrency)
        threading.Thread(target=_run_batch_job, args=(job_id, req), daemon=True).start()
        return {"job_id": job_id}

    @router.post("/api/us-paypal/protocol/start")
    def start_us_paypal_protocol(req: UsPaypalProtocolStartRequest) -> dict[str, str]:
        if not extract_protocol_ba_token(req.ba_token or req.paypal_link):
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "请填写有效 BA 链接或 BA token"})
        sms_provider = paypal_protocol_service.normalize_sms_provider(req.sms_provider)
        if sms_provider == "sms_record":
            if not _sms_record_phone_pool(req):
                raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "请导入协议支付号池：手机号----SMS record URL"})
        elif sms_provider == "hero_sms_rent":
            if not str(req.phone or "").strip():
                raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "请填写 HeroSMS 长效号码"})
        elif sms_provider not in {"hero_sms", "smsbower"}:
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "不支持的 PayPal 手机接码平台"})
        if req.country not in paypal_protocol_service.SUPPORTED_PAYPAL_PROTOCOL_COUNTRIES:
            countries_text = paypal_protocol_service.SUPPORTED_PAYPAL_PROTOCOL_COUNTRIES_TEXT
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": f"当前协议支付仅开放 {countries_text}"})
        job_id = _new_protocol_job(req.account_email)
        threading.Thread(target=_run_protocol_payment_job, args=(job_id, req), daemon=True).start()
        return {"job_id": job_id}

    @router.post("/api/us-paypal/protocol/batch/start")
    def start_us_paypal_protocol_batch(req: UsPaypalProtocolBatchStartRequest) -> dict[str, str]:
        tasks = _validate_protocol_batch_start(req)
        job_id = _new_protocol_batch_job([str(task.get("email") or "") for task in tasks], req.concurrency)
        threading.Thread(target=_run_protocol_batch_payment_job, args=(job_id, req), daemon=True).start()
        return {"job_id": job_id}

    @router.get("/api/us-paypal/protocol/jobs/{job_id}")
    def get_us_paypal_protocol_job(job_id: str) -> dict[str, Any]:
        return _job_snapshot(job_id)

    @router.post("/api/us-paypal/protocol/jobs/{job_id}/cancel")
    def cancel_us_paypal_protocol_job(job_id: str) -> dict[str, Any]:
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="job not found")
            if job.get("status") in TERMINAL_STATUSES:
                return {"ok": True, "job_id": job_id, "status": job.get("status"), "cancel_requested": bool(job.get("cancel_requested"))}
            job["cancel_requested"] = True
            if job.get("status") in {"queued", "running"}:
                job["status"] = "cancelling"
        _append_log(job_id, "收到取消请求：协议引擎将终止子进程")
        return {"ok": True, "job_id": job_id, "status": "cancelling", "cancel_requested": True}

    @router.post("/api/us-paypal/pay153/batch/start")
    def start_us_paypal_pay153_batch(req: UsPaypal153BatchStartRequest) -> dict[str, str]:
        tasks = _validate_pay153_batch_start(req)
        job_id = _new_pay153_batch_job([str(task.get("email") or "") for task in tasks], req.concurrency)
        threading.Thread(target=_run_pay153_batch_payment_job, args=(job_id, req), daemon=True).start()
        return {"job_id": job_id}

    @router.get("/api/us-paypal/pay153/supported-countries")
    def get_us_paypal_pay153_supported_countries() -> dict[str, Any]:
        return _pay153_request("GET", "/supported-countries")

    @router.get("/api/us-paypal/pay153/stats")
    def get_us_paypal_pay153_stats() -> dict[str, Any]:
        return _pay153_request("GET", "/stats")

    @router.post("/api/us-paypal/pay153/remote/cancel-by-ba")
    def cancel_us_paypal_pay153_remote_by_ba(req: UsPaypal153CancelByBaRequest) -> dict[str, Any]:
        target = _pay153_normalize_ba_token(req.ba_token or req.paypal_link)
        if not target:
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "请提供有效 BA 链接或 BA token"})
        cancelled = _pay153_cancel_existing_jobs_for_ba(target)
        return {"ok": True, "ba_token": target, "remote_cancelled": cancelled}

    @router.get("/api/us-paypal/pay153/jobs/{job_id}")
    def get_us_paypal_pay153_job(job_id: str) -> dict[str, Any]:
        return _job_snapshot(job_id)

    @router.post("/api/us-paypal/pay153/jobs/{job_id}/otp")
    def submit_us_paypal_pay153_otp(job_id: str, req: UsPaypal153InteractiveRequest) -> dict[str, Any]:
        child = _get_owned_pay153_child(job_id, req.remote_job_id)
        client = _get_pay153_child_client(job_id, child["remote_job_id"])
        data = _pay153_submit_otp(child["remote_job_id"], req.value, client=client)
        remote_job = _pay153_remote_job_from_response(data)
        if remote_job:
            _set_pay153_child(
                job_id,
                _pay153_child_snapshot(
                    remote_job,
                    email=str(child.get("email") or ""),
                    country=str(child.get("country") or ""),
                    ba_token=str(child.get("ba_token") or ""),
                    remote_job_id=child["remote_job_id"],
                ),
            )
        _append_log(job_id, f"153支付验证码已提交：{child.get('email') or child['remote_job_id']}")
        return {"ok": True, "job": _job_snapshot(job_id)}

    @router.post("/api/us-paypal/pay153/jobs/{job_id}/captcha")
    def submit_us_paypal_pay153_captcha(job_id: str, req: UsPaypal153InteractiveRequest) -> dict[str, Any]:
        child = _get_owned_pay153_child(job_id, req.remote_job_id)
        client = _get_pay153_child_client(job_id, child["remote_job_id"])
        data = _pay153_submit_captcha(child["remote_job_id"], req.value, client=client)
        remote_job = _pay153_remote_job_from_response(data)
        if remote_job:
            _set_pay153_child(
                job_id,
                _pay153_child_snapshot(
                    remote_job,
                    email=str(child.get("email") or ""),
                    country=str(child.get("country") or ""),
                    ba_token=str(child.get("ba_token") or ""),
                    remote_job_id=child["remote_job_id"],
                ),
            )
        _append_log(job_id, f"153支付验证结果已提交：{child.get('email') or child['remote_job_id']}")
        return {"ok": True, "job": _job_snapshot(job_id)}

    @router.post("/api/us-paypal/pay153/jobs/{job_id}/cancel")
    def cancel_us_paypal_pay153_job(job_id: str) -> dict[str, Any]:
        remote_cancelled: list[str] = []
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="job not found")
            if job.get("status") in TERMINAL_STATUSES:
                return {"ok": True, "job_id": job_id, "status": job.get("status"), "cancel_requested": bool(job.get("cancel_requested"))}
            job["cancel_requested"] = True
            if job.get("status") in {"queued", "running"}:
                job["status"] = "cancelling"
            children = [dict(child) for child in (job.get("children") or {}).values() if isinstance(child, dict)]
        for child in children:
            remote_job_id = str(child.get("remote_job_id") or "")
            if remote_job_id and str(child.get("status") or "") not in {"completed", "failed", "cancelled"}:
                try:
                    _pay153_cancel_job(remote_job_id, client=_get_pay153_child_client(job_id, remote_job_id))
                    remote_cancelled.append(remote_job_id)
                except Exception as exc:
                    _append_log(job_id, f"153远端取消失败 {remote_job_id}: {sanitize_protocol_log_text(str(exc))}")
        _append_log(job_id, "收到取消请求：正在停止 153 远端任务")
        return {"ok": True, "job_id": job_id, "status": "cancelling", "cancel_requested": True, "remote_cancelled": remote_cancelled}

    @router.get("/api/us-paypal/jobs/{job_id}")
    def get_us_paypal_job(job_id: str) -> dict[str, Any]:
        return _job_snapshot(job_id)

    @router.post("/api/us-paypal/jobs/{job_id}/cancel")
    def cancel_us_paypal_job(job_id: str) -> dict[str, Any]:
        should_log = False
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="job not found")
            if job.get("status") in TERMINAL_STATUSES:
                return {"ok": True, "job_id": job_id, "status": job.get("status"), "cancel_requested": bool(job.get("cancel_requested"))}
            job["cancel_requested"] = True
            if job.get("status") in {"queued", "running"}:
                job["status"] = "cancelling"
            should_log = True
        if should_log:
            _append_log(job_id, "收到取消请求：正在停止未开始的账号，已运行账号会跑到当前步骤结束")
        return {"ok": True, "job_id": job_id, "status": "cancelling", "cancel_requested": True}

    @router.get("/api/us-paypal/links")
    def get_us_paypal_links() -> dict[str, Any]:
        return {"links": _load_links()}

    @router.post("/api/us-paypal/links/delete")
    def delete_us_paypal_links(req: UsPaypalDeleteLinksRequest) -> dict[str, Any]:
        ids = {str(item) for item in req.ids if str(item)}
        items = _load_links()
        kept = [item for item in items if str(item.get("id") or "") not in ids] if ids else items
        if ids:
            _save_links(kept)
        return {"deleted": len(items) - len(kept), "links": kept}

    @router.post("/api/us-paypal/links/clear")
    def clear_us_paypal_links() -> dict[str, Any]:
        count = len(_load_links())
        _save_links([])
        return {"deleted": count, "links": []}

    return router
