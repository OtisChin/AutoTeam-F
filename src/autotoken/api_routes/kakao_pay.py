"""Korea Kakao Pay link extraction routes."""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from typing import Any

import requests
from fastapi import APIRouter, HTTPException, Query
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from autotoken.api_routes import brazil_pix as pix_routes
from autotoken.core.paths import PROJECT_ROOT
from autotoken.payments.kakao_pay import (
    KakaoPayJobConfig,
    build_kakao_chatgpt_session,
    build_kakao_dynamic_proxy,
    generate_kakao_trial,
)
from autotoken.services import proxy_runtime
from autotoken.storage import accounts as account_store
from autotoken.storage.auth_session_store import delete_auth_session, load_auth_session

LINKS_FILE = PROJECT_ROOT / "data" / "kakao_pay_links.json"
ACCOUNT_STATUS_FILE = PROJECT_ROOT / "data" / "kakao_pay_account_status.json"
KAKAO_TEMP_EXTRACT_API_BASE = "https://masi.cc.cd"
KAKAO_TEMP_SCAN_API_BASE = "https://masi.cc.cd/kakao/scan/api/integration"
KAKAO_KK_CUSTOMER_API_BASE = "https://customer.i7wap.xyz/api/v1/customer"
KAKAO_LINK_TTL_SECONDS = 15 * 60
MAX_BATCH_CONCURRENCY = 20
MAX_ACCOUNT_ATTEMPTS = 5
MAX_CONFIGURABLE_ACCOUNT_ATTEMPTS = 20
PROXY_PREFLIGHT_MAX_ATTEMPTS = 10
MAX_CONFIGURABLE_PROXY_PREFLIGHT_ATTEMPTS = 100
KAKAO_STATUS_PENDING = "pending"
KAKAO_STATUS_RUNNING = "running"
KAKAO_STATUS_SUCCESS = "success"
KAKAO_STATUS_FAILED = "failed"
KAKAO_STATUS_PAID = "paid"
KAKAO_STATUS_TEXT = {"pending": "未提链", "running": "提链中", "success": "已提链", "failed": "提链失败", "paid": "已支付"}
ACCOUNT_UI_FIELDS = (
    "email", "status", "account_type", "seat_type", "ttl_seconds", "expires_at", "last_active_at", "updated_at", "note",
)
JOBS: dict[str, dict[str, Any]] = {}
KK_PAYMENT_JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.RLock()
KK_PAYMENT_JOBS_LOCK = threading.RLock()
LINKS_LOCK = threading.RLock()
ACCOUNT_STATUS_LOCK = threading.RLock()
TERMINAL_STATUSES = {"success", "error", "failed", "cancelled"}


class KakaoPayStartRequest(BaseModel):
    account_email: str = Field("", alias="accountEmail")
    proxies: str = ""
    concurrency: int = 1
    local_proxy: str = Field("", alias="localProxy")
    kookeey_endpoint: str = Field("gate.kookeey.info:1000", alias="kookeeyEndpoint")
    kookeey_user: str = Field("", alias="kookeeyUser")
    kookeey_pass: str = Field("", alias="kookeeyPass")
    region: str = "KR"
    max_attempts: int = Field(MAX_ACCOUNT_ATTEMPTS, alias="maxAttempts")
    proxy_preflight_attempts: int = Field(PROXY_PREFLIGHT_MAX_ATTEMPTS, alias="proxyPreflightAttempts")
    model_config = {"populate_by_name": True}

    @field_validator("region", mode="before")
    @classmethod
    def _clean_region(cls, value: Any) -> str:
        text = str(value or "KR").strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", text):
            return "KR"
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


class KakaoPayBatchStartRequest(KakaoPayStartRequest):
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


class KakaoPayDeleteLinksRequest(BaseModel):
    ids: list[str] = Field(default_factory=list)


class KakaoPayDeleteAccountsRequest(BaseModel):
    emails: list[str] = Field(default_factory=list)


class KakaoPayTempOrderRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    cdk: str = Field("", validation_alias=AliasChoices("cdk", "CDK", "code", "xCdk"))
    access_token: str = Field("", alias="accessToken", validation_alias=AliasChoices("accessToken", "access_token", "at", "token"))

    @field_validator("cdk", "access_token", mode="before")
    @classmethod
    def _clean_text(cls, value: Any) -> str:
        return str(value or "").strip()


class KakaoPayTempTicketRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    cdk: str = Field("", validation_alias=AliasChoices("cdk", "CDK", "code", "xCdk"))

    @field_validator("cdk", mode="before")
    @classmethod
    def _clean_cdk(cls, value: Any) -> str:
        return str(value or "").strip()


class KakaoPayTempBatchStartRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    account_emails: list[str] = Field(default_factory=list, alias="accountEmails")
    cdk: str = ""
    cdks: list[str] = Field(default_factory=list)
    max_accounts: int | None = Field(None, alias="maxAccounts")
    concurrency: int = 5

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

    @field_validator("cdk", mode="before")
    @classmethod
    def _clean_cdk(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("cdks", mode="before")
    @classmethod
    def _clean_cdks(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raw_items = re.split(r"[\r\n,]+", value)
        elif isinstance(value, list):
            raw_items = value
        else:
            raise ValueError("cdks must be a list")
        items: list[str] = []
        for item in raw_items:
            cdk = str(item or "").strip()
            if cdk:
                items.append(cdk)
        return items


class KakaoPayCustomerOrderRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    cdk: str = Field("", validation_alias=AliasChoices("cdk", "CDK", "code", "xCdk", "xCdkKey"))
    access_token: str = Field("", alias="accessToken", validation_alias=AliasChoices("accessToken", "access_token", "at", "token"))
    session_cookie: str = Field("", alias="sessionCookie", validation_alias=AliasChoices("sessionCookie", "session_cookie", "credential", "cookie", "cookieHeader", "cookie_header"))
    payment_url: str = Field("", alias="paymentUrl", validation_alias=AliasChoices("paymentUrl", "payment_url", "link", "url"))
    payment_method: str = Field("kakao_pay", alias="paymentMethod", validation_alias=AliasChoices("paymentMethod", "payment_method"))
    mode: str = "READY_LINK"

    @field_validator("cdk", "access_token", "session_cookie", "payment_url", "payment_method", "mode", mode="before")
    @classmethod
    def _clean_text(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("payment_method")
    @classmethod
    def _clean_payment_method(cls, value: str) -> str:
        text = str(value or "kakao_pay").strip().lower()
        return text if text in {"kakao_pay", "naver_pay"} else "kakao_pay"

    @field_validator("mode")
    @classmethod
    def _clean_mode(cls, value: str) -> str:
        text = str(value or "READY_LINK").strip().upper()
        return text if text in {"EXTRACT", "READY_LINK"} else "READY_LINK"


class KakaoPayKkPaymentSubmitRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    cdk: str = Field("", validation_alias=AliasChoices("cdk", "CDK", "code", "xCdk", "xCdkKey"))
    account_email: str = Field("", alias="accountEmail", validation_alias=AliasChoices("accountEmail", "account_email", "email"))
    link_id: str = Field("", alias="linkId", validation_alias=AliasChoices("linkId", "link_id", "id"))
    payment_url: str = Field("", alias="paymentUrl", validation_alias=AliasChoices("paymentUrl", "payment_url", "link", "url"))
    payment_method: str = Field("kakao_pay", alias="paymentMethod", validation_alias=AliasChoices("paymentMethod", "payment_method"))

    @field_validator("cdk", "account_email", "link_id", "payment_url", "payment_method", mode="before")
    @classmethod
    def _clean_text(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("payment_method")
    @classmethod
    def _clean_payment_method(cls, value: str) -> str:
        text = str(value or "kakao_pay").strip().lower()
        return text if text in {"kakao_pay", "naver_pay"} else "kakao_pay"


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _remote_json(resp: requests.Response, fallback: str) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError:
        data = {"ok": False, "error": resp.text[:500] or fallback}
    if not isinstance(data, dict):
        data = {"ok": False, "error": str(data)[:500] or fallback}
    if not resp.ok:
        raise HTTPException(status_code=resp.status_code, detail=data)
    return data


def _remote_unreachable(exc: requests.RequestException, label: str) -> HTTPException:
    return HTTPException(status_code=502, detail={"ok": False, "code": "remote_api_unreachable", "message": f"{label} 请求失败：{exc}"})


def _customer_product_type(mode: str) -> str:
    return "KAKAO_EXTRACT" if str(mode or "").upper() == "EXTRACT" else "KAKAO_AT"


def _customer_order_payload(req: KakaoPayCustomerOrderRequest) -> dict[str, Any]:
    mode = str(req.mode or "READY_LINK").strip().upper()
    body: dict[str, Any] = {
        "channel": "KAKAO_KK",
        "mode": mode,
        "productType": _customer_product_type(mode),
        "payment_method": req.payment_method,
    }
    session_cookie = str(req.session_cookie or "").strip()
    access_token = str(req.access_token or "").strip()
    if session_cookie:
        body["session_cookie"] = session_cookie
        body["credential"] = session_cookie
    if access_token:
        body["access_token"] = access_token
    payment_url = str(req.payment_url or "").strip()
    if payment_url:
        body["payment_url"] = payment_url
    return body


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


def _kakao_failure_stage(error: str) -> str:
    text = str(error or "").lower()
    if "approve failed" in text and "blocked" in text:
        return "approve_blocked"
    if "approve 后失败" in text or "setup_attempt_failed" in text or "generic_decline" in text:
        return "provider_setup_failed"
    if text.startswith("kakao 代理预检失败") or "代理预检失败" in text or "html_challenge" in text:
        return "proxy_preflight"
    if "checkout_not_kakao_trial" in text:
        return "zero_trial_gate"
    if "access token" in text or "token_" in text or "认证接口预检失败" in text:
        return "auth"
    return ""


def _set_account_status(email: str, status: str, *, error: str = "", job_id: str = "", failure_stage: str = "") -> dict[str, Any]:
    key = str(email or "").strip().lower()
    if not key:
        return {}
    normalized = str(status or KAKAO_STATUS_PENDING).strip().lower()
    if normalized not in KAKAO_STATUS_TEXT:
        normalized = KAKAO_STATUS_PENDING
    item = {
        "status": normalized,
        "error": str(error or ""),
        "failure_stage": str(failure_stage or _kakao_failure_stage(error) or ""),
        "job_id": str(job_id or ""),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with ACCOUNT_STATUS_LOCK:
        statuses = _load_account_statuses()
        statuses[key] = item
        _save_account_statuses(statuses)
    return item


def _kakao_paid_emails() -> set[str]:
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
        kakao_bound = bind_provider == "kakao_pay" and bind_status in {"success", "succeeded", "ok"}
        if account_type == account_store.ACCOUNT_TYPE_PLUS or status == account_store.STATUS_PLUS or kakao_bound:
            paid.add(email)
    return paid


def _iter_auth_accounts(*, include_paid: bool = False) -> list[dict[str, Any]]:
    return pix_routes._iter_auth_accounts(include_paid=include_paid)


def _load_token_for_email(email: str) -> str:
    return pix_routes._load_token_for_email(email)


def _load_kakao_customer_credentials_for_email(email: str) -> tuple[str, str]:
    """Return (session_cookie, access_token) for the customer API.

    The new customer API prefers session_cookie/credential because it can refresh
    the web session. Keep access_token as a legacy fallback when the session file
    is absent or incomplete.
    """
    session_cookie = ""
    access_token = ""
    try:
        session_data = load_auth_session(email)
    except Exception:
        session_data = {}
    if isinstance(session_data, dict):
        session_cookie = str(
            session_data.get("cookie_header")
            or session_data.get("cookieHeader")
            or session_data.get("session_cookie")
            or session_data.get("sessionCookie")
            or session_data.get("sessionToken")
            or session_data.get("session_token")
            or ""
        ).strip()
        access_token = str(session_data.get("accessToken") or session_data.get("access_token") or "").strip()
    if not access_token:
        access_token = _load_token_for_email(email)
    return session_cookie, access_token


def _parse_proxies(value: str | list[str]) -> list[str]:
    return pix_routes._parse_proxies(value)


def _rotate_proxies_for_account(proxies: list[str], account_index: int) -> list[str]:
    return pix_routes._rotate_proxies_for_account(proxies, account_index)


def _batch_concurrency(req: KakaoPayBatchStartRequest, total: int) -> int:
    try:
        requested = int(req.concurrency or 1)
    except Exception:
        requested = 1
    return max(1, min(MAX_BATCH_CONCURRENCY, total, requested))


def _requested_temp_concurrency(req: KakaoPayTempBatchStartRequest, total: int) -> int:
    try:
        requested = int(req.concurrency or 5)
    except Exception:
        requested = 5
    return max(1, min(MAX_BATCH_CONCURRENCY, total, requested))


def _temp_cdks(req: KakaoPayTempBatchStartRequest) -> list[str]:
    items: list[str] = []
    raw_items = list(req.cdks or [])
    if req.cdk:
        raw_items.extend(re.split(r"[\r\n,]+", req.cdk))
    for item in raw_items:
        cdk = str(item or "").strip()
        if cdk:
            items.append(cdk)
    return items


def _temp_cdk_assignments(cdks: list[str], total_accounts: int) -> list[str]:
    cleaned = [str(item or "").strip() for item in cdks if str(item or "").strip()]
    if total_accounts <= 0:
        return []
    if len(cleaned) < total_accounts:
        raise RuntimeError(f"KSCAN CDK 不足：账号 {total_accounts} 个，可用 CDK {len(cleaned)} 枚")
    return cleaned[:total_accounts]


def _account_attempt_limit(req: KakaoPayBatchStartRequest) -> int:
    try:
        attempts = int(req.max_attempts or MAX_ACCOUNT_ATTEMPTS)
    except Exception:
        attempts = MAX_ACCOUNT_ATTEMPTS
    return max(1, min(MAX_CONFIGURABLE_ACCOUNT_ATTEMPTS, attempts))


def _link_country_from_item(item: dict[str, Any]) -> str:
    billing = item.get("billing") if isinstance(item.get("billing"), dict) else {}
    country = str(item.get("country") or item.get("region") or billing.get("country") or "").strip().upper()
    return country if re.fullmatch(r"[A-Z]{2}", country) else ""


def _normalize_link_record(item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    normalized["country"] = _link_country_from_item(normalized) or "KR"
    return normalized


def _normalize_link(value: Any) -> str:
    return str(value or "").strip().rstrip("/")


def _kakao_link_url(item: dict[str, Any]) -> str:
    return str(item.get("provider_redirect_url") or item.get("kakao_link") or item.get("stripe_redirect_url") or "").strip()


def _find_kakao_payment_link(*, link_id: str = "", account_email: str = "", payment_url: str = "") -> dict[str, Any]:
    clean_id = str(link_id or "").strip()
    clean_email = str(account_email or "").strip().lower()
    clean_url = _normalize_link(payment_url)
    for item in _load_links():
        if clean_id and str(item.get("id") or "").strip() == clean_id:
            return item
        if clean_email and str(item.get("account_email") or item.get("accountEmail") or "").strip().lower() == clean_email:
            return item
        if clean_url and _normalize_link(_kakao_link_url(item)) == clean_url:
            return item
    return {}


def _submit_kakao_customer_order(req: KakaoPayCustomerOrderRequest) -> dict[str, Any]:
    try:
        resp = requests.post(
            f"{KAKAO_KK_CUSTOMER_API_BASE}/orders",
            json=_customer_order_payload(req),
            headers={"Content-Type": "application/json", "X-CDK-Key": str(req.cdk or "").strip()},
            timeout=70,
        )
    except requests.RequestException as exc:
        raise _remote_unreachable(exc, "KK 客户支付 API") from exc
    return _remote_json(resp, "KK 客户支付 API 返回非 JSON 响应")


def _customer_api_get(path: str, *, headers: dict[str, str], timeout: int = 20) -> dict[str, Any]:
    try:
        resp = requests.get(f"{KAKAO_KK_CUSTOMER_API_BASE}{path}", headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        raise _remote_unreachable(exc, "KK 客户支付 API") from exc
    return _remote_json(resp, "KK 客户支付 API 返回非 JSON 响应")


def _customer_api_post_action(path: str, *, headers: dict[str, str], timeout: int = 20) -> dict[str, Any]:
    try:
        resp = requests.post(f"{KAKAO_KK_CUSTOMER_API_BASE}{path}", headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        raise _remote_unreachable(exc, "KK 客户支付 API") from exc
    return _remote_json(resp, "KK 客户支付 API 返回非 JSON 响应")


def _kk_payment_cdk_status(cdk: str) -> dict[str, Any]:
    clean_cdk = str(cdk or "").strip()
    if not clean_cdk:
        raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "KK 支付 CDK 不能为空"})
    try:
        resp = requests.get(
            f"{KAKAO_KK_CUSTOMER_API_BASE}/orders",
            params={"page": 1, "pageSize": 100},
            headers={"Accept": "application/json", "X-CDK-Key": clean_cdk},
            timeout=20,
        )
    except requests.RequestException as exc:
        raise _remote_unreachable(exc, "KK 支付 CDK 额度查询 API") from exc
    data = _remote_json(resp, "KK 支付 CDK 额度查询 API 返回非 JSON 响应")
    snapshot = _cdk_snapshot_from_customer_orders(data)
    if snapshot:
        return {"ok": True, "data": snapshot, "orders": _customer_orders_from_payload(data)}
    return {"ok": True, "data": {"totalCount": "-", "usedCount": "-", "frozenCount": "-", "availableCount": "-"}, "orders": _customer_orders_from_payload(data)}


def _customer_orders_from_payload(data: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(data.get("data"), list):
        return [item for item in data.get("data") or [] if isinstance(item, dict)]
    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    raw_orders = (
        payload.get("orders")
        or payload.get("items")
        or payload.get("list")
        or payload.get("records")
        or data.get("orders")
        or []
    )
    if isinstance(raw_orders, list):
        return [item for item in raw_orders if isinstance(item, dict)]
    return []


def _cdk_snapshot_from_customer_orders(data: dict[str, Any]) -> dict[str, Any]:
    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    for candidate in (payload.get("cdk"), data.get("cdk")):
        if isinstance(candidate, dict):
            return candidate
    for order in _customer_orders_from_payload(data):
        cdk = order.get("cdk")
        if isinstance(cdk, dict):
            return cdk
    return {}


def _kk_payment_order_action(order_id: str, action: str, *, token: str = "", cdk: str = "") -> dict[str, Any]:
    clean_order_id = str(order_id or "").strip()
    clean_action = str(action or "").strip().lower()
    clean_token = str(token or "").strip()
    clean_cdk = str(cdk or "").strip()
    if clean_action not in {"cancel", "resubmit"}:
        raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "不支持的 KK 订单操作"})
    if not clean_order_id or (not clean_token and not clean_cdk):
        raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "order_id 以及 customerToken 或 CDK 不能为空"})
    headers: dict[str, str] = {"Accept": "application/json"}
    if clean_token:
        headers["Authorization"] = f"Bearer {clean_token}"
    if clean_cdk:
        headers["X-CDK-Key"] = clean_cdk
    return _customer_api_post_action(f"/orders/{clean_order_id}/{clean_action}", headers=headers, timeout=20)


def _kakao_temp_ticket_status(cdk: str) -> dict[str, Any]:
    clean_cdk = str(cdk or "").strip()
    if not clean_cdk:
        raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "KSCAN CDK 不能为空"})
    try:
        resp = requests.get(
            f"{KAKAO_TEMP_EXTRACT_API_BASE}/v1/cdk/status",
            headers={"X-CDK": clean_cdk},
            timeout=20,
        )
    except requests.RequestException as exc:
        raise _remote_unreachable(exc, "Kakao 临时提链服务") from exc
    return _remote_json(resp, "Kakao 临时提链服务返回非 JSON 响应")


def _customer_order_response_payload(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    order = payload.get("order") if isinstance(payload.get("order"), dict) else payload
    return (payload if isinstance(payload, dict) else {}), (order if isinstance(order, dict) else {})


def _customer_order_id(data: dict[str, Any]) -> str:
    _payload, order = _customer_order_response_payload(data)
    return str(order.get("id") or order.get("order_id") or order.get("orderId") or "").strip()


def _customer_token(data: dict[str, Any]) -> str:
    payload, _order = _customer_order_response_payload(data)
    return str(payload.get("customerToken") or payload.get("customer_token") or payload.get("token") or "").strip()


def _customer_order_success(data: dict[str, Any]) -> bool:
    _payload, order = _customer_order_response_payload(data)
    status = str(order.get("status") or data.get("status") or "").strip().lower()
    return status in {"success", "succeeded", "paid", "completed"}


def _remember_kk_payment_order(order_id: str, *, account_email: str, link_id: str, payment_url: str, cdk: str, customer_token: str = "") -> None:
    clean_order_id = str(order_id or "").strip()
    if not clean_order_id:
        return
    with KK_PAYMENT_JOBS_LOCK:
        KK_PAYMENT_JOBS[clean_order_id] = {
            "order_id": clean_order_id,
            "account_email": str(account_email or "").strip(),
            "link_id": str(link_id or "").strip(),
            "payment_url": str(payment_url or "").strip(),
            "cdk": str(cdk or "").strip(),
            "customer_token": str(customer_token or "").strip(),
            "account_marked": False,
            "account_update": {},
            "created_at": time.time(),
        }


def _clean_kakao_account_email(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    email = value.strip()
    if not email or "@" not in email or any(ch.isspace() for ch in email):
        return ""
    return email


def _mark_kk_payment_success_account(order_id: str, email: str = "", message: str = "KK payment succeeded") -> dict[str, Any]:
    clean_order_id = str(order_id or "").strip()
    clean_email = _clean_kakao_account_email(email)
    with KK_PAYMENT_JOBS_LOCK:
        payment_job = KK_PAYMENT_JOBS.get(clean_order_id) or {}
        if payment_job.get("account_marked"):
            return dict(payment_job.get("account_update") or {})
        if not clean_email:
            clean_email = _clean_kakao_account_email(payment_job.get("account_email"))
    if not clean_email:
        return {}
    updated = _mark_account_plus_kakao(clean_email, message)
    result = {
        "email": clean_email,
        "account_type": str(updated.get("account_type") or ""),
        "last_bind_provider": str(updated.get("last_bind_provider") or ""),
    }
    _set_account_status(clean_email, KAKAO_STATUS_PAID, job_id=clean_order_id)
    with KK_PAYMENT_JOBS_LOCK:
        if clean_order_id in KK_PAYMENT_JOBS:
            KK_PAYMENT_JOBS[clean_order_id]["account_email"] = clean_email
            KK_PAYMENT_JOBS[clean_order_id]["account_marked"] = True
            KK_PAYMENT_JOBS[clean_order_id]["account_update"] = result
    return result


def _timestamp_seconds(value: Any) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    try:
        numeric = float(text)
        if numeric > 0:
            return int(numeric / 1000) if numeric > 1_000_000_000_000 else int(numeric)
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return int(time.mktime(time.strptime(text.split(".")[0], fmt)))
        except Exception:
            continue
    return 0


def _dedupe_link_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_accounts: set[str] = set()
    seen_links: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        email = str(item.get("account_email") or "").strip().lower()
        link = _normalize_link(item.get("provider_redirect_url") or item.get("kakao_link") or item.get("stripe_redirect_url"))
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


def _known_account_email_keys() -> set[str]:
    return {str(account.get("email") or "").strip().lower() for account in _iter_auth_accounts(include_paid=True) if str(account.get("email") or "").strip()}


def _load_links_pruning_deleted_accounts() -> tuple[list[dict[str, Any]], int]:
    items = _load_links()
    known_emails = _known_account_email_keys()
    paid_emails = _kakao_paid_emails()
    kept: list[dict[str, Any]] = []
    removed_emails: set[str] = set()
    for item in items:
        email = str(item.get("account_email") or "").strip().lower()
        if email and known_emails and (email not in known_emails or email in paid_emails):
            removed_emails.add(email)
            continue
        kept.append(item)
    if len(kept) != len(items):
        _save_links(kept)
        statuses = _load_account_statuses()
        for email in removed_emails:
            statuses.pop(email, None)
        _save_account_statuses(statuses)
    return kept, len(items) - len(kept)


def _iter_auth_accounts_with_kakao_status() -> list[dict[str, Any]]:
    statuses = _load_account_statuses()
    paid_emails = _kakao_paid_emails()
    links_by_email = {str(item.get("account_email") or "").strip().lower(): item for item in _load_links() if str(item.get("account_email") or "").strip()}
    try:
        dashboard_by_email = {str(account.get("email") or "").strip().lower(): account for account in account_store.load_accounts() if str(account.get("email") or "").strip()}
    except Exception:
        dashboard_by_email = {}
    rows: list[dict[str, Any]] = []
    for account in _iter_auth_accounts(include_paid=True):
        email = str(account.get("email") or "").strip()
        if not email:
            continue
        key = email.lower()
        item = statuses.get(key) if isinstance(statuses.get(key), dict) else {}
        if key in paid_emails:
            item = {"status": KAKAO_STATUS_PAID, "error": "", "updated_at": ""}
        elif not item and key in links_by_email:
            item = {"status": KAKAO_STATUS_SUCCESS, "error": "", "updated_at": ""}
        status = str(item.get("status") or KAKAO_STATUS_PENDING)
        if status not in KAKAO_STATUS_TEXT:
            status = KAKAO_STATUS_PENDING
        dashboard_account = dashboard_by_email.get(key) or {}
        rows.append({
            field: (email if field == "email" else dashboard_account.get(field, account.get(field))) for field in ACCOUNT_UI_FIELDS
        } | {
            "kakao_status": status,
            "kakao_status_text": KAKAO_STATUS_TEXT[status],
            "kakao_error": str(item.get("error") or ""),
            "kakao_country": "KR",
            "kakao_status_updated_at": item.get("updated_at"),
            "kakao_selectable": status != KAKAO_STATUS_PAID,
        })
    return rows


def _link_record_from_result(job_id: str, account_email: str, result: dict[str, Any]) -> dict[str, Any]:
    fields = result.get("fields") if isinstance(result.get("fields"), dict) else {}
    billing = fields.get("billing") if isinstance(fields.get("billing"), dict) else result.get("billing") or {}
    primary_link = str(fields.get("provider_redirect_url") or fields.get("kakao_link") or fields.get("stripe_redirect_url") or "")
    created_at_ts = int(time.time())
    explicit_expires_at_ts = _timestamp_seconds(fields.get("kakao_expires_at_ts") or fields.get("kakao_expires_at") or result.get("kakao_expires_at_ts") or result.get("kakao_expires_at"))
    expires_at_ts = explicit_expires_at_ts or (created_at_ts + KAKAO_LINK_TTL_SECONDS)
    return _normalize_link_record({
        "id": uuid.uuid4().hex[:16],
        "job_id": job_id,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(created_at_ts)),
        "created_at_ts": created_at_ts,
        "account_email": account_email,
        "country": "KR",
        "amount": str(fields.get("amount") or result.get("amount") or ""),
        "cs_id": str(fields.get("cs_id") or ""),
        "kakao_link": primary_link,
        "provider_redirect_url": str(fields.get("provider_redirect_url") or ""),
        "stripe_redirect_url": str(fields.get("stripe_redirect_url") or ""),
        "kakao_ttl_seconds": KAKAO_LINK_TTL_SECONDS,
        "kakao_expires_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(expires_at_ts)),
        "kakao_expires_at_ts": expires_at_ts,
        "link_source": str(fields.get("link_source") or ""),
        "link_binding": str(fields.get("link_binding") or ""),
        "chatgpt_checkout_url": str(fields.get("chatgpt_checkout_url") or ""),
        "billing": billing,
    })


def _append_link(record: dict[str, Any]) -> None:
    with LINKS_LOCK:
        items = _load_links()
        record_email = str(record.get("account_email") or "").strip().lower()
        record_link = _normalize_link(record.get("provider_redirect_url") or record.get("kakao_link") or record.get("stripe_redirect_url"))
        if record_email:
            items = [item for item in items if str(item.get("account_email") or "").strip().lower() != record_email]
        elif record_link:
            items = [item for item in items if _normalize_link(item.get("provider_redirect_url") or item.get("kakao_link") or item.get("stripe_redirect_url")) != record_link]
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
        if job:
            job["running_count"] = max(0, int(job.get("running_count") or 0) + delta)


def _preflight_kakao_checkout_backend_proxy_url(proxy_url: str, access_token: str, region: str) -> tuple[bool, str]:
    token = str(access_token or "").strip()
    if not token:
        return False, "checkout_backend missing_token"
    target_region = str(region or "KR").strip().upper() or "KR"
    target_path = f"/backend-api/checkout_pricing_config/configs/{target_region}"
    try:
        session = build_kakao_chatgpt_session(token, proxy_url, str(uuid.uuid4()))
        try:
            resp = session.get(
                f"https://chatgpt.com{target_path}",
                headers={"x-openai-target-path": target_path, "x-openai-target-route": target_path},
                timeout=20,
            )
        finally:
            close = getattr(session, "close", None)
            if callable(close):
                close()
        status_code = int(getattr(resp, "status_code", 0) or 0)
        text = str(getattr(resp, "text", "") or "")
        content_type = str((getattr(resp, "headers", {}) or {}).get("content-type") or "").lower()
        message = f"checkout_backend HTTP {status_code or 'unknown'}"
        lower = text.lower()
        looks_html_challenge = (
            status_code in {403, 429, 503}
            and ("html" in content_type or "<html" in lower[:500])
            and any(marker in lower for marker in ("cloudflare", "challenge", "access denied", "just a moment"))
        )
        if looks_html_challenge:
            return False, message + "; html_challenge"
        if status_code == 401:
            if "token_revoked" in lower:
                return False, message + " token_revoked"
            if "token_invalidated" in lower or "invalidated oauth token" in lower or "authentication token" in lower:
                return False, message + " token_invalidated"
            return False, message
        if 200 <= status_code < 500:
            return True, message
        return False, message
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _token_preflight_error(message: str) -> bool:
    text = str(message or "").lower()
    return "token_" in text or "authentication token" in text


def _proxy_preflight_attempt_limit(value: Any, default: int = PROXY_PREFLIGHT_MAX_ATTEMPTS) -> int:
    try:
        attempts = int(value or default)
    except Exception:
        attempts = default
    return max(1, min(MAX_CONFIGURABLE_PROXY_PREFLIGHT_ATTEMPTS, attempts))


def _preflight_kakao_proxy_role(
    cfg: KakaoPayJobConfig,
    *,
    role: str,
    stage_index: int,
    require_auth: bool,
    attempt: int,
    total_attempts: int,
    log,
) -> tuple[bool, str, str]:
    proxy_url, sid_label = build_kakao_dynamic_proxy(cfg, stage_index)
    if not proxy_url:
        return False, "", "empty proxy"
    log(f"Kakao {role} 代理预检开始：{attempt}/{total_attempts} {sid_label}")
    ok, message = proxy_runtime.preflight_payment_proxy_url(proxy_url)
    if not ok:
        log(f"Kakao {role} 代理出口预检失败：{message}")
        return False, proxy_url, str(message or "unknown")
    if not require_auth:
        log(f"Kakao {role} 代理预检通过：{message}")
        return True, proxy_url, ""

    auth_ok, auth_message = proxy_runtime.preflight_chatgpt_authenticated_proxy_url(proxy_url, cfg.access_token)
    if not auth_ok:
        log(f"Kakao {role} 代理认证接口预检失败：{auth_message}")
        if _token_preflight_error(str(auth_message)):
            raise RuntimeError(f"认证接口预检失败: {auth_message}")
        return False, proxy_url, str(auth_message or "unknown")

    backend_region = (
        cfg.promotion_region
        if role == "promotion"
        else (cfg.provider_region if role == "provider" else (cfg.checkout_region or cfg.region))
    )
    backend_region = str(backend_region or "KR").strip().upper() or "KR"
    backend_ok, backend_message = _preflight_kakao_checkout_backend_proxy_url(
        proxy_url,
        cfg.access_token,
        backend_region,
    )
    if not backend_ok:
        log(f"Kakao {role} checkout backend 预检失败：{backend_message}")
        if _token_preflight_error(str(backend_message)):
            raise RuntimeError(f"认证接口预检失败: {backend_message}")
        return False, proxy_url, str(backend_message or "unknown")

    log(f"Kakao {role} 代理预检通过：{message}; {auth_message}; {backend_message}")
    return True, proxy_url, ""


def _preflight_kakao_proxies_or_raise(cfg: KakaoPayJobConfig, log, max_attempts: int | None = None) -> KakaoPayJobConfig:
    if not cfg.direct_proxies and (not cfg.kookeey_user or not cfg.kookeey_pass):
        return cfg
    attempts = _proxy_preflight_attempt_limit(max_attempts)
    stage_specs = [
        ("checkout", 0, True),
        ("promotion", 1, False),
        ("provider", 2, True),
    ]
    errors: list[str] = []
    candidate_cfg = replace(cfg, direct_proxies=(cfg.direct_proxies[:1] if cfg.direct_proxies else []))

    for attempt in range(1, attempts + 1):
        preflighted: dict[str, str] = {}
        candidate_errors: list[str] = []
        for role, stage_index, require_auth in stage_specs:
            ok, proxy_url, message = _preflight_kakao_proxy_role(
                candidate_cfg,
                role=role,
                stage_index=stage_index,
                require_auth=require_auth,
                attempt=attempt,
                total_attempts=attempts,
                log=log,
            )
            if ok:
                preflighted[role] = proxy_url
                continue
            candidate_errors.append(f"{role}: {message}")
            break
        if len(preflighted) == len(stage_specs):
            return replace(
                cfg,
                preflighted_checkout_proxy_url=preflighted["checkout"],
                preflighted_promotion_proxy_url=preflighted["promotion"],
                preflighted_provider_proxy_url=preflighted["provider"],
            )
        errors.extend(candidate_errors)

    raise RuntimeError(f"Kakao 代理预检失败: {'; '.join(errors[-attempts:])}")


def _select_batch_accounts(req: KakaoPayBatchStartRequest) -> list[dict[str, Any]]:
    available = _iter_auth_accounts()
    by_email = {str(item.get("email") or "").strip().lower(): item for item in available}
    requested = [str(email or "").strip() for email in req.account_emails if str(email or "").strip()]
    selected = [by_email[email.lower()] for email in requested if email.lower() in by_email] if requested else available
    if req.max_accounts and req.max_accounts > 0:
        selected = selected[: int(req.max_accounts)]
    return selected


def _select_temp_batch_accounts(req: KakaoPayTempBatchStartRequest) -> list[dict[str, Any]]:
    available = _iter_auth_accounts()
    by_email = {str(item.get("email") or "").strip().lower(): item for item in available}
    requested = [str(email or "").strip() for email in req.account_emails if str(email or "").strip()]
    selected = [by_email[email.lower()] for email in requested if email.lower() in by_email] if requested else available
    if req.max_accounts and req.max_accounts > 0:
        selected = selected[: int(req.max_accounts)]
    return selected


def _create_kakao_temp_external_order(access_token: str, cdk: str) -> dict[str, Any]:
    try:
        resp = requests.post(
            f"{KAKAO_TEMP_EXTRACT_API_BASE}/v1/kakao/jobs",
            json={"access_token": access_token},
            headers={"Content-Type": "application/json", "X-CDK": cdk},
            timeout=70,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Kakao 临时提链服务请求失败：{exc}") from exc
    return _remote_json(resp, "Kakao 临时提链服务返回非 JSON 响应")


def _get_kakao_temp_external_order(order_id: str, cdk: str) -> dict[str, Any]:
    try:
        resp = requests.get(
            f"{KAKAO_TEMP_EXTRACT_API_BASE}/v1/kakao/jobs/{order_id}",
            headers={"X-CDK": cdk},
            timeout=20,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Kakao 临时提链服务轮询失败：{exc}") from exc
    return _remote_json(resp, "Kakao 临时提链服务返回非 JSON 响应")


def _temp_order_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    order = payload.get("job") if isinstance(payload.get("job"), dict) else (payload.get("order") if isinstance(payload.get("order"), dict) else payload)
    return order if isinstance(order, dict) else {}


def _temp_order_id(data: dict[str, Any]) -> str:
    order = _temp_order_payload(data)
    return str(order.get("job_id") or order.get("jobId") or order.get("order_id") or order.get("orderId") or order.get("id") or "").strip()


def _temp_order_link(order: dict[str, Any]) -> str:
    output = order.get("output") if isinstance(order.get("output"), dict) else {}
    return str(
        output.get("long_url")
        or output.get("url")
        or output.get("link")
        or order.get("link")
        or order.get("kakao_link")
        or order.get("provider_redirect_url")
        or order.get("payment_url")
        or order.get("url")
        or ""
    ).strip()


def _temp_order_step_text(order: dict[str, Any]) -> str:
    steps = order.get("steps")
    if not isinstance(steps, list):
        return ""
    for step in reversed(steps):
        if not isinstance(step, dict):
            continue
        name = str(step.get("name") or step.get("stage") or step.get("code") or "").strip()
        detail = str(step.get("detail") or step.get("message") or step.get("status") or step.get("error") or "").strip()
        text = " / ".join(item for item in (name, detail) if item)
        if text:
            return text
    return ""


def _temp_order_progress(order: dict[str, Any]) -> dict[str, str]:
    status = str(order.get("status") or "").strip()
    code = str(order.get("code") or order.get("status_code") or order.get("stage") or order.get("phase") or "").strip()
    message = str(order.get("message") or order.get("detail") or order.get("error") or order.get("reason") or "").strip()
    step = _temp_order_step_text(order)
    parts = []
    if status:
        parts.append(f"status={status}")
    if code and code.lower() != status.lower():
        parts.append(f"code={code}")
    if step:
        parts.append(f"step={step}")
    if message and message not in step:
        parts.append(f"message={message}")
    return {
        "status": status,
        "code": code,
        "message": message,
        "step": step,
        "summary": " ".join(parts) or "-",
    }


def _update_temp_external_progress(job_id: str, email: str, order_id: str, order: dict[str, Any], *, log_prefix: str = "", force_log: bool = False) -> None:
    progress = _temp_order_progress(order)
    signature = "|".join([progress["status"], progress["code"], progress["step"], progress["message"]])
    status_item = _set_account_status(email, KAKAO_STATUS_RUNNING, error=progress["summary"], job_id=job_id, failure_stage="temp_extract")
    status_item.update({
        "external_job_id": order_id,
        "external_status": progress["status"],
        "external_code": progress["code"],
        "external_message": progress["message"],
        "external_step": progress["step"],
    })
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is None:
            return
        external_jobs = dict(job.get("external_jobs") or {})
        previous = external_jobs.get(email) if isinstance(external_jobs.get(email), dict) else {}
        external_jobs[email] = {
            "job_id": order_id,
            "status": progress["status"] or "queued",
            "code": progress["code"],
            "message": progress["message"],
            "step": progress["step"],
            "summary": progress["summary"],
            "updated_at": time.time(),
        }
        job["external_jobs"] = external_jobs
        account_statuses = dict(job.get("account_statuses") or {})
        account_statuses[email] = status_item
        job["account_statuses"] = account_statuses
        if force_log or str(previous.get("_signature") or "") != signature:
            external_jobs[email]["_signature"] = signature
            prefix = log_prefix or "KSCAN 状态"
            job["logs"].append(f"[{time.strftime('%H:%M:%S')}] {prefix}：{email} job_id={order_id} {progress['summary']}")
            job["logs"] = job["logs"][-500:]


def _poll_kakao_temp_external_order(order_id: str, cdk: str, cancel_check, progress_callback=None, poll_error_callback=None) -> dict[str, Any]:
    deadline = time.monotonic() + KAKAO_LINK_TTL_SECONDS + 90
    last_order: dict[str, Any] = {"order_id": order_id, "status": "pending"}
    transient_errors = 0
    while time.monotonic() < deadline:
        if cancel_check():
            raise RuntimeError("任务已取消")
        try:
            data = _get_kakao_temp_external_order(order_id, cdk)
            transient_errors = 0
        except RuntimeError as exc:
            transient_errors += 1
            message = f"临时提链服务轮询暂时失败，第 {transient_errors} 次，继续等待：{exc}"
            if poll_error_callback:
                poll_error_callback(message, transient_errors)
            time.sleep(2.0)
            continue
        order = _temp_order_payload(data)
        last_order = order or last_order
        if progress_callback and order:
            progress_callback(order)
        status = str(order.get("status") or "").strip().lower()
        if status in {"completed", "success", "succeeded"}:
            return data
        if status in {"failed", "expired", "cancelled", "canceled", "error"}:
            message = str(order.get("error") or order.get("message") or status or "临时提链失败").strip()
            raise RuntimeError(message)
        time.sleep(2.0)
    raise RuntimeError(f"临时提链轮询超时：order_id={order_id} status={last_order.get('status') or '-'}")


def _kakao_temp_result_for_link(email: str, order_id: str, data: dict[str, Any]) -> dict[str, Any]:
    order = _temp_order_payload(data)
    link = _temp_order_link(order)
    if not link:
        raise RuntimeError("临时提链完成但未返回 Kakao 链接")
    now_ts = int(time.time())
    expires_at_ts = _timestamp_seconds(order.get("expires_at") or order.get("expired_at") or order.get("qr_expires_at")) or (now_ts + KAKAO_LINK_TTL_SECONDS)
    return {
        "ok": True,
        "amount": str(order.get("amount") or ""),
        "account_email": email,
        "fields": {
            "kakao_link": link,
            "provider_redirect_url": link,
            "stripe_redirect_url": "",
            "cs_id": str(order.get("cs_id") or order.get("checkout_session_id") or order_id),
            "amount": str(order.get("amount") or ""),
            "billing": {"country": "KR"},
            "kakao_expires_at_ts": expires_at_ts,
            "link_source": "kakao_temp_scan",
            "link_binding": "kscan",
        },
        "billing": {"country": "KR"},
    }


def _run_batch_account(job_id: str, req: KakaoPayBatchStartRequest, account: dict[str, Any], index: int, total: int, proxies: list[str]) -> dict[str, Any]:
    email = str(account.get("email") or "").strip()
    proxies = proxies[:1] if proxies else []
    started = time.monotonic()
    if _is_job_cancel_requested(job_id):
        _append_log(job_id, f"[{index}/{total}] 跳过账号：{email}（任务已取消）")
        return {"skipped": True, "email": email, "status": _set_account_status(email, KAKAO_STATUS_PENDING, job_id=job_id)}
    proxy_slot = f" proxy槽={(index - 1) % len(proxies) + 1}/{len(proxies)}" if proxies else ""
    _set_job_running_delta(job_id, 1)
    _append_log(job_id, f"[{index}/{total}] 开始账号：{email}{proxy_slot}")

    def account_log(message: str) -> None:
        _append_log(job_id, f"[{index}/{total}] {message}")

    attempts = 0
    try:
        _set_account_status(email, KAKAO_STATUS_RUNNING, job_id=job_id)
        token = _load_token_for_email(email)
        if not token:
            raise RuntimeError("账号缺少有效 accessToken")
        result: dict[str, Any] | None = None
        last_error = ""
        last_deep_error = ""
        max_attempts = _account_attempt_limit(req)
        for attempt in range(1, max_attempts + 1):
            attempts = attempt
            if _is_job_cancel_requested(job_id) and attempt > 1:
                raise RuntimeError(f"任务已取消，停止重试；最后错误: {last_error}")
            account_log(f"第 {attempt}/{max_attempts} 次尝试：{email}")
            cfg = KakaoPayJobConfig(
                access_token=token,
                local_proxy=str(req.local_proxy or "").strip(),
                kookeey_user=str(req.kookeey_user or "").strip(),
                kookeey_pass=str(req.kookeey_pass or ""),
                kookeey_endpoint=str(req.kookeey_endpoint or "gate.kookeey.info:1000").strip(),
                region=(req.region or "KR").strip().upper() or "KR",
                direct_proxies=proxies,
            )
            try:
                cfg = _preflight_kakao_proxies_or_raise(cfg, account_log, req.proxy_preflight_attempts)
                result = generate_kakao_trial(cfg, log=account_log)
                break
            except Exception as exc:
                last_error = str(exc)
                if not last_error.startswith("Kakao 代理预检失败"):
                    last_deep_error = last_error
                if last_error.startswith("Kakao 代理预检失败"):
                    display_error = last_error
                    failure_stage = _kakao_failure_stage(last_error)
                    error_item: dict[str, Any] = {
                        "email": email,
                        "elapsed_s": round(time.monotonic() - started, 1),
                        "attempts": attempt,
                        "error": display_error,
                        "failure_stage": failure_stage,
                    }
                    if last_deep_error:
                        previous_stage = _kakao_failure_stage(last_deep_error) or "extract"
                        display_error = f"{last_deep_error}; 后续代理预检失败: {last_error}"
                        failure_stage = previous_stage
                        error_item["error"] = display_error
                        error_item["failure_stage"] = failure_stage
                        error_item["previous_error"] = last_deep_error
                        error_item["preflight_error"] = last_error
                    status = _set_account_status(email, KAKAO_STATUS_FAILED, error=display_error, job_id=job_id, failure_stage=failure_stage)
                    _append_log(job_id, f"[{index}/{total}] 代理预检已达到上限，停止真实提链：{email} {display_error}")
                    return {
                        "ok": False,
                        "email": email,
                        "error": error_item,
                        "status": status,
                    }
                if pix_routes._is_already_paid_error(last_error):
                    _mark_account_plus_kakao(email, last_error)
                    status = _set_account_status(email, KAKAO_STATUS_SUCCESS, error=last_error, job_id=job_id)
                    return {"skipped": True, "email": email, "reason": "账号已是 Plus，已标记绑定渠道 Kakao Pay", "status": status}
                if pix_routes._is_token_invalidated_error(last_error) or pix_routes._is_no_organization_error(last_error):
                    cleanup = _delete_invalid_account(email)
                    failure_stage = _kakao_failure_stage(last_error)
                    status = _set_account_status(email, KAKAO_STATUS_FAILED, error=last_error, job_id=job_id, failure_stage=failure_stage)
                    return {"ok": False, "email": email, "error": {"email": email, "elapsed_s": round(time.monotonic() - started, 1), "attempts": attempt, "error": f"账号不可用，已从账号池删除：{last_error}", "cleanup": cleanup, "failure_stage": failure_stage}, "status": status}
                if pix_routes._is_non_zero_after_promo_error(last_error):
                    status = _set_account_status(email, KAKAO_STATUS_FAILED, error=last_error, job_id=job_id)
                    _append_log(job_id, f"[{index}/{total}] Kakao Pay 金额非 0，账号保留：{email}")
                    return {
                        "ok": False,
                        "email": email,
                        "error": {
                            "email": email,
                            "elapsed_s": round(time.monotonic() - started, 1),
                            "attempts": attempt,
                            "error": f"Kakao Pay 金额非 0，账号保留：{last_error}",
                            "account_deleted": False,
                        },
                        "status": status,
                        "account_deleted": False,
                    }
                account_log(f"第 {attempt}/{max_attempts} 次失败：{email} {last_error}")
                if attempt >= max_attempts:
                    raise
                time.sleep(min(2.0, 0.5 * attempt))
        if result is None:
            raise RuntimeError(last_error or "提链失败")
        result["account_email"] = email
        record = _link_record_from_result(job_id, email, result)
        _append_link(record)
        status = _set_account_status(email, KAKAO_STATUS_SUCCESS, job_id=job_id)
        compact = {"email": email, "elapsed_s": round(time.monotonic() - started, 1), "attempts": attempts, "link": record}
        _append_log(job_id, f"[{index}/{total}] 成功：{email} attempts={attempts} cs_id={record.get('cs_id')}")
        return {"ok": True, "email": email, "success": compact, "status": status}
    except Exception as exc:
        error = str(exc)
        failure_stage = _kakao_failure_stage(error)
        item = {"email": email, "elapsed_s": round(time.monotonic() - started, 1), "attempts": attempts or 1, "error": error, "failure_stage": failure_stage}
        status = _set_account_status(email, KAKAO_STATUS_FAILED, error=error, job_id=job_id, failure_stage=failure_stage)
        _append_log(job_id, f"[{index}/{total}] 最终失败：{email} attempts={attempts or 1} {exc}")
        return {"ok": False, "email": email, "error": item, "status": status}
    finally:
        _set_job_running_delta(job_id, -1)


def _run_temp_batch_account(job_id: str, account: dict[str, Any], cdk: str, index: int, total: int) -> dict[str, Any]:
    email = str(account.get("email") or "").strip()
    started = time.monotonic()
    if _is_job_cancel_requested(job_id):
        _append_log(job_id, f"[{index}/{total}] 临时提链跳过账号：{email}（任务已取消）")
        return {"skipped": True, "email": email, "reason": "任务已取消", "status": _set_account_status(email, KAKAO_STATUS_PENDING, job_id=job_id)}
    _set_job_running_delta(job_id, 1)
    _append_log(job_id, f"[{index}/{total}] 临时提链开始：{email}")
    try:
        _set_account_status(email, KAKAO_STATUS_RUNNING, job_id=job_id)
        token = _load_token_for_email(email)
        if not token:
            raise RuntimeError("账号缺少有效 accessToken")
        created = _create_kakao_temp_external_order(token, cdk)
        order_id = _temp_order_id(created)
        if not order_id:
            raise RuntimeError("临时提链服务未返回 order_id")
        created_order = _temp_order_payload(created)
        if created_order:
            _update_temp_external_progress(job_id, email, order_id, created_order, log_prefix=f"[{index}/{total}] KSCAN 初始状态", force_log=True)
        _append_log(job_id, f"[{index}/{total}] KSCAN 直提任务已创建：{email} job_id={order_id}")
        polled = _poll_kakao_temp_external_order(
            order_id,
            cdk,
            lambda: _is_job_cancel_requested(job_id),
            lambda order: _update_temp_external_progress(job_id, email, order_id, order, log_prefix=f"[{index}/{total}] KSCAN 轮询状态"),
            lambda message, count: (
                _set_account_status(email, KAKAO_STATUS_RUNNING, error=message, job_id=job_id, failure_stage="temp_extract"),
                _append_log(job_id, f"[{index}/{total}] {message}"),
            ),
        )
        result = _kakao_temp_result_for_link(email, order_id, polled)
        record = _link_record_from_result(job_id, email, result)
        _append_link(record)
        status = _set_account_status(email, KAKAO_STATUS_SUCCESS, job_id=job_id)
        compact = {
            "email": email,
            "elapsed_s": round(time.monotonic() - started, 1),
            "attempts": 1,
            "cdk": cdk,
            "job_id": order_id,
            "link": record,
        }
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if job is not None:
                external_jobs = dict(job.get("external_jobs") or {})
                completed_order = _temp_order_payload(polled)
                progress = _temp_order_progress(completed_order)
                external_jobs[email] = {"job_id": order_id, "status": "completed", "code": progress["code"], "message": progress["message"], "step": progress["step"], "summary": progress["summary"], "updated_at": time.time()}
                job["external_jobs"] = external_jobs
        _append_log(job_id, f"[{index}/{total}] 临时直提成功：{email} job_id={order_id}")
        return {"ok": True, "email": email, "success": compact, "status": status}
    except Exception as exc:
        error = str(exc) or type(exc).__name__
        failure_stage = _kakao_failure_stage(error) or "temp_extract"
        item = {
            "email": email,
            "elapsed_s": round(time.monotonic() - started, 1),
            "attempts": 1,
            "error": error,
            "failure_stage": failure_stage,
            "cdk": cdk,
        }
        status = _set_account_status(email, KAKAO_STATUS_FAILED, error=error, job_id=job_id, failure_stage=failure_stage)
        _append_log(job_id, f"[{index}/{total}] 临时提链失败：{email} {error}")
        return {"ok": False, "email": email, "error": item, "status": status}
    finally:
        _set_job_running_delta(job_id, -1)


def _run_temp_batch_job(job_id: str, req: KakaoPayTempBatchStartRequest) -> None:
    def log(message: str) -> None:
        _append_log(job_id, message)

    try:
        accounts = _select_temp_batch_accounts(req)
        if not accounts:
            raise RuntimeError("没有可用账号，请先选择账号池账号或刷新账号池")
        cdks = _temp_cdk_assignments(_temp_cdks(req), len(accounts))
        concurrency = _requested_temp_concurrency(req, len(accounts))
        successes: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        account_statuses: dict[str, dict[str, Any]] = {}
        for account in accounts:
            email = str(account.get("email") or "").strip()
            account_statuses[email] = _set_account_status(email, KAKAO_STATUS_PENDING, job_id=job_id)
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "running"
            JOBS[job_id]["temp"] = True
            JOBS[job_id]["total"] = len(accounts)
            JOBS[job_id]["completed"] = 0
            JOBS[job_id]["concurrency"] = concurrency
            JOBS[job_id]["running_count"] = 0
            JOBS[job_id]["account_statuses"] = account_statuses
            JOBS[job_id]["external_jobs"] = {}
        log(f"Kakao Pay 临时提链任务开始：{len(accounts)} 个账号，并发 {concurrency}，KSCAN CDK={len(cdks)}")
        completed = 0
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [
                executor.submit(_run_temp_batch_account, job_id, account, cdks[index - 1], index, len(accounts))
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
                    JOBS[job_id]["completed"] = completed
                    JOBS[job_id]["account_statuses"] = account_statuses
                    JOBS[job_id]["skipped"] = skipped
                    JOBS[job_id]["result"] = {"batch": True, "temp": True, "successes": successes, "errors": errors, "skipped": skipped}
        with JOBS_LOCK:
            cancelled = bool(JOBS[job_id].get("cancel_requested"))
            has_non_error_outcome = bool(successes or skipped)
            JOBS[job_id]["status"] = "cancelled" if cancelled else ("success" if has_non_error_outcome else "error")
            JOBS[job_id]["error"] = "任务已取消" if cancelled else ("" if has_non_error_outcome else "全部账号失败")
            JOBS[job_id]["finished_at"] = time.time()
        log(f"Kakao Pay 临时提链任务完成：成功 {len(successes)}，失败 {len(errors)}，跳过 {len(skipped)}")
    except Exception as exc:
        with JOBS_LOCK:
            if job_id not in JOBS:
                return
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error"] = str(exc)
            JOBS[job_id]["finished_at"] = time.time()
        _append_log(job_id, f"失败: {exc}")


def _delete_invalid_account(email: str) -> dict[str, Any]:
    return {"record_deleted": bool(account_store.delete_account(email)), "auth_session_deleted": bool(delete_auth_session(email))}


def _mark_account_plus_kakao(email: str, message: str = "User is already paid") -> dict[str, Any]:
    account_store.ensure_session_only_account(email)
    now = time.time()
    return account_store.update_account(
        email,
        account_type=account_store.ACCOUNT_TYPE_PLUS,
        last_bind_provider="kakao_pay",
        last_bind_status="success",
        last_bind_at=now,
        plus_bound_at=now,
        last_bind_message=message,
        last_bind_failure_stage="",
        last_quota={"plan_type": account_store.ACCOUNT_TYPE_PLUS, "source": "kakao_pay_payment_success", "checked_at": now},
    ) or {}


def delete_account_artifacts(email: str) -> dict[str, Any]:
    target = str(email or "").strip().lower()
    if not target:
        return {"links_deleted": 0, "status_deleted": False}
    items = _load_links()
    kept = [item for item in items if str(item.get("account_email") or "").strip().lower() != target]
    if len(kept) != len(items):
        _save_links(kept)
    statuses = _load_account_statuses()
    status_deleted = statuses.pop(target, None) is not None
    if status_deleted:
        _save_account_statuses(statuses)
    return {"links_deleted": len(items) - len(kept), "status_deleted": status_deleted}


def _delete_kakao_pay_account_everywhere(email: str) -> dict[str, Any]:
    clean_email = str(email or "").strip()
    kakao_cleanup = delete_account_artifacts(clean_email)
    dashboard_account_deleted = bool(account_store.delete_account(clean_email))
    auth_session_deleted = bool(delete_auth_session(clean_email))
    return {"ok": True, "email": clean_email, "dashboard_account_deleted": dashboard_account_deleted, "auth_session_deleted": auth_session_deleted, "kakao_pay": kakao_cleanup}


def _run_batch_job(job_id: str, req: KakaoPayBatchStartRequest) -> None:
    def log(message: str) -> None:
        _append_log(job_id, message)

    try:
        accounts = _select_batch_accounts(req)
        if not accounts:
            raise RuntimeError("没有可用账号，请先选择账号池账号或刷新账号池")
        proxies = _parse_proxies(req.proxies)
        if not proxies and (not req.kookeey_user or not req.kookeey_pass):
            raise RuntimeError("请填写代理")
        if len(proxies) > 1:
            log(f"Kakao Pay 仅使用首条代理模板，其余 {len(proxies) - 1} 条已忽略")
        concurrency = _batch_concurrency(req, len(accounts))
        successes: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        account_statuses: dict[str, dict[str, Any]] = {}
        for account in accounts:
            email = str(account.get("email") or "").strip()
            account_statuses[email] = _set_account_status(email, KAKAO_STATUS_PENDING, job_id=job_id)
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "running"
            JOBS[job_id]["total"] = len(accounts)
            JOBS[job_id]["completed"] = 0
            JOBS[job_id]["concurrency"] = concurrency
            JOBS[job_id]["running_count"] = 0
            JOBS[job_id]["account_statuses"] = account_statuses
        proxy_pool = f"，代理池={len(proxies)}" if proxies else ""
        log(f"Kakao Pay 提链任务开始：{len(accounts)} 个账号，并发 {concurrency}，目标国家={req.region}{proxy_pool}")
        completed = 0
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [
                executor.submit(_run_batch_account, job_id, req, account, index, len(accounts), proxies)
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
                    JOBS[job_id]["completed"] = completed
                    JOBS[job_id]["account_statuses"] = account_statuses
                    JOBS[job_id]["skipped"] = skipped
                    JOBS[job_id]["result"] = {"batch": True, "successes": successes, "errors": errors, "skipped": skipped}
        with JOBS_LOCK:
            cancelled = bool(JOBS[job_id].get("cancel_requested"))
            has_non_error_outcome = bool(successes or skipped)
            JOBS[job_id]["status"] = "cancelled" if cancelled else ("success" if has_non_error_outcome else "error")
            JOBS[job_id]["error"] = "任务已取消" if cancelled else ("" if has_non_error_outcome else "全部账号失败")
            JOBS[job_id]["finished_at"] = time.time()
        log(f"Kakao Pay 提链任务完成：成功 {len(successes)}，失败 {len(errors)}，跳过 {len(skipped)}")
    except Exception as exc:
        with JOBS_LOCK:
            if job_id not in JOBS:
                return
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error"] = str(exc)
            JOBS[job_id]["finished_at"] = time.time()
        _append_log(job_id, f"失败: {exc}")


def _new_job(account_emails: list[str], concurrency: int, *, temp: bool = False) -> str:
    job_id = uuid.uuid4().hex[:12]
    created = time.time()
    with JOBS_LOCK:
        JOBS[job_id] = {
            "id": job_id, "status": "queued", "logs": ["任务已创建"],
            "result": None, "error": None, "created_at": created, "finished_at": None,
            "account_email": account_emails[0] if len(account_emails) == 1 else "",
            "total": len(account_emails), "completed": 0,
            "concurrency": max(1, min(MAX_BATCH_CONCURRENCY, int(concurrency or 1))),
            "cancel_requested": False, "running_count": 0, "skipped": [], "account_statuses": {},
            "temp": bool(temp), "external_jobs": {},
        }
    return job_id


def _job_snapshot(job_id: str) -> dict[str, Any]:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return {"id": job["id"], "status": job["status"], "logs": list(job["logs"]), "result": job["result"], "error": job["error"], "created_at": job["created_at"], "finished_at": job["finished_at"], "account_email": job.get("account_email") or "", "total": job.get("total") or 0, "completed": job.get("completed") or 0, "concurrency": job.get("concurrency") or 1, "running_count": job.get("running_count") or 0, "cancel_requested": bool(job.get("cancel_requested")), "skipped": job.get("skipped") or [], "account_statuses": job.get("account_statuses") or {}, "temp": bool(job.get("temp")), "external_jobs": job.get("external_jobs") or {}}


def create_kakao_pay_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/kakao-pay/accounts")
    def get_kakao_pay_accounts() -> dict[str, Any]:
        return {"accounts": _iter_auth_accounts_with_kakao_status()}

    @router.delete("/api/kakao-pay/accounts/{email}")
    def delete_kakao_pay_account(email: str) -> dict[str, Any]:
        clean_email = str(email or "").strip()
        if not clean_email:
            raise HTTPException(status_code=400, detail="email required")
        return _delete_kakao_pay_account_everywhere(clean_email)

    @router.post("/api/kakao-pay/accounts/delete")
    def delete_kakao_pay_accounts(req: KakaoPayDeleteAccountsRequest) -> dict[str, Any]:
        emails = [str(email or "").strip() for email in req.emails if str(email or "").strip()]
        if not emails:
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "请选择要删除的账号"})
        return {"ok": True, "results": [_delete_kakao_pay_account_everywhere(email) for email in emails]}

    @router.post("/api/kakao-pay/start")
    def start_kakao_pay(req: KakaoPayStartRequest) -> dict[str, str]:
        emails = [str(req.account_email or "").strip()] if str(req.account_email or "").strip() else []
        batch_req = KakaoPayBatchStartRequest.model_validate(req.model_dump(by_alias=True) | {"accountEmails": emails})
        job_id = _new_job(emails, 1)
        threading.Thread(target=_run_batch_job, args=(job_id, batch_req), daemon=True).start()
        return {"job_id": job_id}

    @router.post("/api/kakao-pay/batch/start")
    def start_kakao_pay_batch(req: KakaoPayBatchStartRequest) -> dict[str, str]:
        job_id = _new_job(req.account_emails, req.concurrency)
        threading.Thread(target=_run_batch_job, args=(job_id, req), daemon=True).start()
        return {"job_id": job_id}

    @router.post("/api/kakao-pay/temp/batch/start")
    def start_kakao_pay_temp_batch(req: KakaoPayTempBatchStartRequest) -> dict[str, str]:
        job_id = _new_job(req.account_emails, req.concurrency, temp=True)
        threading.Thread(target=_run_temp_batch_job, args=(job_id, req), daemon=True).start()
        return {"job_id": job_id}

    @router.post("/api/kakao-pay/jobs/{job_id}/cancel")
    def cancel_kakao_pay_job(job_id: str) -> dict[str, Any]:
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="job not found")
            if job.get("status") in TERMINAL_STATUSES:
                return {"ok": True, "job_id": job_id, "status": job.get("status"), "cancel_requested": bool(job.get("cancel_requested"))}
            job["cancel_requested"] = True
            if job.get("status") in {"queued", "running"}:
                job["status"] = "cancelling"
        _append_log(job_id, "收到取消请求：正在停止未开始的账号，已运行账号会跑到当前步骤结束")
        return {"ok": True, "job_id": job_id, "status": "cancelling", "cancel_requested": True}

    @router.get("/api/kakao-pay/jobs/{job_id}")
    def get_kakao_pay_job(job_id: str) -> dict[str, Any]:
        return _job_snapshot(job_id)

    @router.get("/api/kakao-pay/links")
    def get_kakao_pay_links() -> dict[str, Any]:
        links, pruned_deleted_accounts = _load_links_pruning_deleted_accounts()
        return {"links": links, "pruned_deleted_accounts": pruned_deleted_accounts}

    @router.post("/api/kakao-pay/links/delete")
    def delete_kakao_pay_links(req: KakaoPayDeleteLinksRequest) -> dict[str, Any]:
        ids = {str(item or "").strip() for item in req.ids if str(item or "").strip()}
        if not ids:
            return {"deleted": 0, "links": _load_links()}
        items = _load_links()
        kept = [item for item in items if str(item.get("id") or "") not in ids]
        _save_links(kept)
        return {"deleted": len(items) - len(kept), "links": kept}

    @router.post("/api/kakao-pay/links/clear")
    def clear_kakao_pay_links() -> dict[str, Any]:
        count = len(_load_links())
        _save_links([])
        return {"deleted": count, "links": []}

    @router.post("/api/kakao-pay/temp/orders")
    def create_kakao_pay_temp_order(req: KakaoPayTempOrderRequest) -> dict[str, Any]:
        cdk = str(req.cdk or "").strip()
        access_token = str(req.access_token or "").strip()
        if not cdk or not access_token:
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "KSCAN CDK 和 AT 不能为空"})
        try:
            return _create_kakao_temp_external_order(access_token, cdk)
        except HTTPException:
            raise
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail={"ok": False, "code": "remote_api_unreachable", "message": str(exc)}) from exc

    @router.get("/api/kakao-pay/temp/orders/{order_id}")
    def get_kakao_pay_temp_order(order_id: str, cdk: str = Query("")) -> dict[str, Any]:
        clean_order_id = str(order_id or "").strip()
        clean_cdk = str(cdk or "").strip()
        if not clean_order_id or not clean_cdk:
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "order_id 和 KSCAN CDK 不能为空"})
        try:
            return _get_kakao_temp_external_order(clean_order_id, clean_cdk)
        except HTTPException:
            raise
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail={"ok": False, "code": "remote_api_unreachable", "message": str(exc)}) from exc

    @router.post("/api/kakao-pay/temp/tickets/status")
    def get_kakao_pay_temp_ticket_status(req: KakaoPayTempTicketRequest) -> dict[str, Any]:
        return _kakao_temp_ticket_status(req.cdk)

    @router.get("/api/kakao-pay/temp/tickets/status")
    def get_kakao_pay_temp_ticket_status_get(cdk: str = Query("")) -> dict[str, Any]:
        return _kakao_temp_ticket_status(cdk)

    @router.post("/api/kakao-pay/kk-payment/orders")
    def create_kakao_pay_customer_order(req: KakaoPayCustomerOrderRequest) -> dict[str, Any]:
        cdk = str(req.cdk or "").strip()
        access_token = str(req.access_token or "").strip()
        session_cookie = str(req.session_cookie or "").strip()
        mode = str(req.mode or "READY_LINK").strip().upper()
        payment_url = str(req.payment_url or "").strip()
        if not cdk or not (session_cookie or access_token):
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "KK 支付 CDK 和 session_cookie/AT 不能为空"})
        if mode == "READY_LINK" and not payment_url:
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "READY_LINK 模式需要 NicePay 支付链接"})
        return _submit_kakao_customer_order(req)

    @router.post("/api/kakao-pay/kk-payment/submit")
    def submit_kakao_pay_customer_payment(req: KakaoPayKkPaymentSubmitRequest) -> dict[str, Any]:
        cdk = str(req.cdk or "").strip()
        if not cdk:
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "KK 支付 CDK 不能为空"})
        link_record = _find_kakao_payment_link(link_id=req.link_id, account_email=req.account_email, payment_url=req.payment_url)
        account_email = str(req.account_email or link_record.get("account_email") or link_record.get("accountEmail") or "").strip()
        payment_url = str(req.payment_url or _kakao_link_url(link_record) or "").strip()
        link_id = str(req.link_id or link_record.get("id") or "").strip()
        if not account_email:
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "请选择已提取链接对应账号"})
        if not payment_url:
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "该账号缺少已提取 Kakao/NicePay 链接"})
        session_cookie, access_token = _load_kakao_customer_credentials_for_email(account_email)
        if not session_cookie and not access_token:
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_account", "message": "账号缺少有效 session_cookie 或 accessToken"})
        order_req = KakaoPayCustomerOrderRequest.model_validate({
            "cdk": cdk,
            "sessionCookie": session_cookie,
            "accessToken": access_token,
            "paymentUrl": payment_url,
            "paymentMethod": req.payment_method,
            "mode": "READY_LINK",
        })
        data = _submit_kakao_customer_order(order_req)
        order_id = _customer_order_id(data)
        _remember_kk_payment_order(
            order_id,
            account_email=account_email,
            link_id=link_id,
            payment_url=payment_url,
            cdk=cdk,
            customer_token=_customer_token(data),
        )
        data["account_email"] = account_email
        data["link_id"] = link_id
        data["payment_url"] = payment_url
        return data

    @router.post("/api/kakao-pay/kk-payment/cdk/status")
    def get_kakao_pay_kk_payment_cdk_status(req: KakaoPayTempTicketRequest) -> dict[str, Any]:
        return _kk_payment_cdk_status(req.cdk)

    @router.get("/api/kakao-pay/kk-payment/cdk/status")
    def get_kakao_pay_kk_payment_cdk_status_get(cdk: str = Query("")) -> dict[str, Any]:
        return _kk_payment_cdk_status(cdk)

    @router.get("/api/kakao-pay/kk-payment/orders/{order_id}")
    def get_kakao_pay_customer_order(order_id: str, token: str = Query(""), cdk: str = Query(""), accountEmail: str = Query("")) -> dict[str, Any]:
        clean_order_id = str(order_id or "").strip()
        clean_token = str(token or "").strip()
        clean_cdk = str(cdk or "").strip()
        if not clean_order_id or (not clean_token and not clean_cdk):
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "order_id 以及 customerToken 或 CDK 不能为空"})
        headers: dict[str, str] = {"Accept": "application/json"}
        if clean_token:
            headers["Authorization"] = f"Bearer {clean_token}"
        if clean_cdk:
            headers["X-CDK-Key"] = clean_cdk
        data = _customer_api_get(f"/orders/{clean_order_id}", headers=headers, timeout=20)
        if _customer_order_success(data):
            account_update = _mark_kk_payment_success_account(clean_order_id, accountEmail, "KK 客户支付 API 支付成功")
            if account_update:
                payload, order = _customer_order_response_payload(data)
                order["account_email"] = account_update.get("email") or ""
                order["account_marked_plus"] = True
                if payload is not order and isinstance(payload, dict):
                    payload["order"] = order
                data["account_email"] = account_update.get("email") or ""
                data["account_marked_plus"] = True
        return data

    @router.post("/api/kakao-pay/kk-payment/orders/{order_id}/cancel")
    def cancel_kakao_pay_customer_order(order_id: str, token: str = Query(""), cdk: str = Query("")) -> dict[str, Any]:
        return _kk_payment_order_action(order_id, "cancel", token=token, cdk=cdk)

    @router.post("/api/kakao-pay/kk-payment/orders/{order_id}/resubmit")
    def resubmit_kakao_pay_customer_order(order_id: str, token: str = Query(""), cdk: str = Query("")) -> dict[str, Any]:
        return _kk_payment_order_action(order_id, "resubmit", token=token, cdk=cdk)

    return router
