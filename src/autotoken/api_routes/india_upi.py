"""India UPI link extraction routes."""

from __future__ import annotations

import json
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
from autotoken.payments.india_upi import UpiJobConfig, build_upi_dynamic_proxy, generate_upi_trial
from autotoken.services import proxy_runtime
from autotoken.storage import accounts as account_store
from autotoken.storage.auth_session_store import delete_auth_session

LINKS_FILE = PROJECT_ROOT / "data" / "india_upi_links.json"
ACCOUNT_STATUS_FILE = PROJECT_ROOT / "data" / "india_upi_account_status.json"
TEMP_UPI_API_BASE = "https://ahwuoc.site"
UPI_SCAN_API_BASE = "https://ahwuoc.site"
MAX_BATCH_CONCURRENCY = 10
MAX_TEMP_BATCH_CONCURRENCY = 20
TEMP_CDK_COOLDOWN_SECONDS = 3 * 60
MAX_ACCOUNT_ATTEMPTS = 5
MAX_CONFIGURABLE_ACCOUNT_ATTEMPTS = 20
PROXY_PREFLIGHT_MAX_ATTEMPTS = 3
UPI_LINK_TTL_SECONDS = 5 * 60
UPI_STATUS_PENDING = "pending"
UPI_STATUS_RUNNING = "running"
UPI_STATUS_SUCCESS = "success"
UPI_STATUS_FAILED = "failed"
UPI_STATUS_PAID = "paid"
UPI_STATUS_TEXT = {"pending": "未提链", "running": "提链中", "success": "已提链", "failed": "提链失败", "paid": "已支付"}
UPI_FAILURE_META: dict[str, dict[str, str]] = {
    "upi_already_paid": {
        "stage": "account_state",
        "label": "账号已是 Plus",
        "retry_hint": "无需继续提链，账号已标记为 Plus/UPI 已绑定。",
    },
    "upi_account_invalid": {
        "stage": "auth",
        "label": "账号凭证不可用",
        "retry_hint": "与 401 一样从账号池删除，换下一个账号。",
    },
    "upi_promo_nonzero_account_ineligible": {
        "stage": "promo_amount",
        "label": "账号无 0 元试用资格",
        "retry_hint": "金额非 0，直接删除账号，不要重试同账号。",
    },
    "upi_approve_blocked": {
        "stage": "chatgpt_approve",
        "label": "ChatGPT approve 被拦截",
        "retry_hint": "不要在同一 checkout 无限 approve；重建 checkout 并换稳定 IN 出口或 fresh sid。",
    },
    "upi_setup_generic_decline": {
        "stage": "stripe_setup_intent",
        "label": "Stripe/UPI mandate 被拒",
        "retry_hint": "approve 已过但 SetupIntent 被 provider 拒；停止当前 checkout，换代理/重建，不删除账号。",
    },
    "upi_checkout_not_active": {
        "stage": "stripe_checkout",
        "label": "Checkout session 非 active",
        "retry_hint": "当前 checkout 已不可用，重建 checkout。",
    },
    "upi_egress_changed": {
        "stage": "proxy",
        "label": "代理出口漂移",
        "retry_hint": "同一 checkout/provider/approve 出口不一致；换稳定 session 或更换代理池。",
    },
    "upi_network_error": {
        "stage": "network",
        "label": "网络/代理异常",
        "retry_hint": "可重试；优先刷新代理 sid 或换出口。",
    },
    "upi_unknown_failure": {
        "stage": "unknown",
        "label": "未分类失败",
        "retry_hint": "查看任务日志中的阶段和 Stripe intent 摘要后再判断。",
    },
}
ACCOUNT_UI_FIELDS = (
    "email", "status", "account_type", "seat_type", "ttl_seconds", "expires_at", "last_active_at", "updated_at", "note",
)
JOBS: dict[str, dict[str, Any]] = {}
PAYMENT_JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.RLock()
PAYMENT_JOBS_LOCK = threading.RLock()
LINKS_LOCK = threading.RLock()
ACCOUNT_STATUS_LOCK = threading.RLock()
TERMINAL_STATUSES = {"success", "error", "failed", "cancelled"}


class IndiaUpiStartRequest(BaseModel):
    account_email: str = Field("", alias="accountEmail")
    proxies: str = ""
    concurrency: int = 1
    local_proxy: str = Field("", alias="localProxy")
    kookeey_endpoint: str = Field("gate.kookeey.info:1000", alias="kookeeyEndpoint")
    kookeey_user: str = Field("", alias="kookeeyUser")
    kookeey_pass: str = Field("", alias="kookeeyPass")
    region: str = "IN"
    promo_mode: str = Field("promo", alias="promoMode")
    max_attempts: int = Field(MAX_ACCOUNT_ATTEMPTS, alias="maxAttempts")
    model_config = {"populate_by_name": True}

    @field_validator("promo_mode", mode="before")
    @classmethod
    def _clean_promo_mode(cls, value: Any) -> str:
        text = str(value or "promo").strip().lower().replace("-", "_")
        if text in {"promo", "apply", "apply_promo", "with_promo"}:
            return "promo"
        return "skip"

    @field_validator("max_attempts", mode="before")
    @classmethod
    def _clean_max_attempts(cls, value: Any) -> int:
        try:
            attempts = int(value or MAX_ACCOUNT_ATTEMPTS)
        except Exception:
            attempts = MAX_ACCOUNT_ATTEMPTS
        return max(1, min(MAX_CONFIGURABLE_ACCOUNT_ATTEMPTS, attempts))


class IndiaUpiBatchStartRequest(IndiaUpiStartRequest):
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


class IndiaUpiTempBatchStartRequest(BaseModel):
    account_emails: list[str] = Field(default_factory=list, alias="accountEmails")
    cdk: str = ""
    cdks: list[str] = Field(default_factory=list)
    max_accounts: int | None = Field(None, alias="maxAccounts")
    concurrency: int = 5
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


class IndiaUpiPaymentSubmitRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    cdk: str = Field("", validation_alias=AliasChoices("cdk", "CDK", "code", "value"))
    link: str = Field("", validation_alias=AliasChoices("link", "url", "paymentLink", "payment_link"))

    @field_validator("cdk", "link", mode="before")
    @classmethod
    def _coerce_payment_submit_text(cls, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, dict):
            for key in ("value", "cdk", "CDK", "code", "link", "url", "paymentLink", "payment_link"):
                nested = value.get(key)
                if nested is not None:
                    return str(nested).strip()
            return ""
        return str(value).strip()


class IndiaUpiDeleteLinksRequest(BaseModel):
    ids: list[str] = Field(default_factory=list)


class IndiaUpiDeleteAccountsRequest(BaseModel):
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
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


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


def classify_upi_failure(error: Any) -> dict[str, str]:
    text = str(error or "")
    lower = text.lower()
    category = "upi_unknown_failure"
    if pix_routes._is_already_paid_error(text):
        category = "upi_already_paid"
    elif pix_routes._is_token_invalidated_error(text) or pix_routes._is_no_organization_error(text):
        category = "upi_account_invalid"
    elif pix_routes._is_non_zero_after_promo_error(text):
        category = "upi_promo_nonzero_account_ineligible"
    elif (
        "approve failed" in lower
        and ("blocked" in lower or "request is not allowed" in lower)
    ) or '"result":"blocked"' in lower or "'result': 'blocked'" in lower:
        category = "upi_approve_blocked"
    elif (
        "setup_attempt_failed" in lower
        and "generic_decline" in lower
    ) or (
        "checkout_approval_payment_failure_with_payment_error" in lower
        and "setup_intent" in lower
    ):
        category = "upi_setup_generic_decline"
    elif "checkout_not_active" in lower or "not_active_session" in lower or "active session" in lower:
        category = "upi_checkout_not_active"
    elif (
        "egress_changed" in lower
        or "main_exit_changed" in lower
        or "exit changed" in lower
        or "出口漂移" in text
        or "出口变化" in text
    ):
        category = "upi_egress_changed"
    elif any(marker in lower for marker in ("timeout", "timed out", "unexpectedeof", "eof", "proxy", "connect", "connection", "socks")):
        category = "upi_network_error"
    meta = UPI_FAILURE_META[category]
    return {
        "failure_category": category,
        "failure_stage": meta["stage"],
        "failure_label": meta["label"],
        "retry_hint": meta["retry_hint"],
    }


def _set_account_status(
    email: str,
    status: str,
    *,
    error: str = "",
    job_id: str = "",
    failure: dict[str, str] | None = None,
) -> dict[str, Any]:
    key = str(email or "").strip().lower()
    if not key:
        return {}
    normalized = str(status or UPI_STATUS_PENDING).strip().lower()
    if normalized not in UPI_STATUS_TEXT:
        normalized = UPI_STATUS_PENDING
    item = {
        "status": normalized,
        "error": str(error or ""),
        "job_id": str(job_id or ""),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if failure:
        item.update({key: value for key, value in failure.items() if value})
    with ACCOUNT_STATUS_LOCK:
        statuses = _load_account_statuses()
        statuses[key] = item
        _save_account_statuses(statuses)
    return item


def _upi_paid_emails() -> set[str]:
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
        upi_bound = bind_provider == "upi" and bind_status in {"success", "succeeded", "ok"}
        if account_type == account_store.ACCOUNT_TYPE_PLUS or status == account_store.STATUS_PLUS or upi_bound:
            paid.add(email)
    return paid


def _iter_auth_accounts_with_upi_status() -> list[dict[str, Any]]:
    statuses = _load_account_statuses()
    paid_emails = _upi_paid_emails()
    linked_emails = {
        str(item.get("account_email") or "").strip().lower()
        for item in _load_links()
        if str(item.get("account_email") or "").strip()
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
            item = {"status": UPI_STATUS_PAID, "error": "", "updated_at": ""}
        elif not item and key in linked_emails:
            item = {"status": UPI_STATUS_SUCCESS, "error": "", "updated_at": ""}
        status = str(item.get("status") or UPI_STATUS_PENDING)
        if status not in UPI_STATUS_TEXT:
            status = UPI_STATUS_PENDING
        rows.append({
            field: (email if field == "email" else dashboard_account.get(field, account.get(field))) for field in ACCOUNT_UI_FIELDS
        } | {
            "upi_status": status,
            "upi_status_text": str(item.get("status_text") or UPI_STATUS_TEXT[status]),
            "upi_error": str(item.get("error") or ""),
            "upi_failure_category": str(item.get("failure_category") or ""),
            "upi_failure_stage": str(item.get("failure_stage") or ""),
            "upi_failure_label": str(item.get("failure_label") or ""),
            "upi_retry_hint": str(item.get("retry_hint") or ""),
            "upi_status_updated_at": item.get("updated_at"),
            "upi_selectable": status != UPI_STATUS_PAID,
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


def _batch_concurrency(req: IndiaUpiBatchStartRequest, total: int) -> int:
    try:
        requested = int(req.concurrency or 1)
    except Exception:
        requested = 1
    return max(1, min(MAX_BATCH_CONCURRENCY, total, requested))


def _account_attempt_limit(req: IndiaUpiBatchStartRequest) -> int:
    try:
        attempts = int(req.max_attempts or MAX_ACCOUNT_ATTEMPTS)
    except Exception:
        attempts = MAX_ACCOUNT_ATTEMPTS
    return max(1, min(MAX_CONFIGURABLE_ACCOUNT_ATTEMPTS, attempts))


def _preflight_upi_proxy_or_raise(cfg: UpiJobConfig, log) -> UpiJobConfig:
    region = str(cfg.region or "IN").strip().upper() or "IN"
    if not cfg.direct_proxies and (not cfg.kookeey_user or not cfg.kookeey_pass):
        return cfg
    errors: list[str] = []
    for stage_index in range(PROXY_PREFLIGHT_MAX_ATTEMPTS):
        proxy_url, sid_label = build_upi_dynamic_proxy(cfg, stage_index, region)
        if not proxy_url:
            continue
        log(f"目标国家代理预检开始：{stage_index + 1}/{PROXY_PREFLIGHT_MAX_ATTEMPTS} region={region} {sid_label}")
        ok, message = proxy_runtime.preflight_payment_proxy_url(proxy_url)
        if ok:
            auth_ok, auth_message = proxy_runtime.preflight_chatgpt_authenticated_proxy_url(proxy_url, cfg.access_token)
            if auth_ok:
                log(f"目标国家代理预检通过：{message}; {auth_message}")
                return replace(cfg, direct_proxies=[proxy_url], preflighted_checkout_proxy_url=proxy_url)
            log(f"目标国家代理认证接口预检失败：{auth_message}")
            if "token_" in str(auth_message).lower() or "authentication token" in str(auth_message).lower():
                raise RuntimeError(f"认证接口预检失败: {auth_message}")
            errors.append(str(auth_message or "unknown"))
            continue
        errors.append(str(message or "unknown"))
        log(f"目标国家代理预检失败：{message}")
    raise RuntimeError(f"代理预检失败: {region} {'; '.join(errors[-PROXY_PREFLIGHT_MAX_ATTEMPTS:])}")


def _select_batch_accounts(req: IndiaUpiBatchStartRequest) -> list[dict[str, Any]]:
    available = _iter_auth_accounts()
    by_email = {str(item.get("email") or "").strip().lower(): item for item in available}
    requested = [str(email or "").strip() for email in req.account_emails if str(email or "").strip()]
    selected = [by_email[email.lower()] for email in requested if email.lower() in by_email] if requested else available
    if req.max_accounts and req.max_accounts > 0:
        selected = selected[: int(req.max_accounts)]
    return selected


def _normalize_link(value: Any) -> str:
    return str(value or "").strip().rstrip("/")


def _dedupe_link_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_accounts: set[str] = set()
    seen_links: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        email = str(item.get("account_email") or "").strip().lower()
        link = _normalize_link(item.get("upi_link") or item.get("hosted_instructions_url"))
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


def _link_record_from_result(job_id: str, account_email: str, result: dict[str, Any]) -> dict[str, Any]:
    fields = result.get("fields") if isinstance(result.get("fields"), dict) else {}
    billing = fields.get("billing") if isinstance(fields.get("billing"), dict) else result.get("billing") or {}
    hosted = str(fields.get("hosted_instructions_url") or fields.get("upi_link") or "")
    created_at_ts = time.time()
    explicit_expires_at_ts = _timestamp_seconds(fields.get("upi_expires_at_ts") or fields.get("upi_expires_at") or result.get("upi_expires_at_ts") or result.get("upi_expires_at"))
    expires_at_ts = explicit_expires_at_ts or (created_at_ts + UPI_LINK_TTL_SECONDS)
    payment_uri = str(fields.get("upi_payment_uri") or fields.get("upiPaymentUri") or "")
    qr_image_svg = str(fields.get("qr_image_url_svg") or "")
    qr_image_png = str(fields.get("qr_image_url_png") or "")
    if payment_uri.startswith("http") and not (qr_image_svg or qr_image_png):
        if ".svg" in payment_uri.lower():
            qr_image_svg = payment_uri
        else:
            qr_image_png = payment_uri
    return {
        "id": uuid.uuid4().hex[:16],
        "job_id": job_id,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "created_at_ts": created_at_ts,
        "upi_ttl_seconds": UPI_LINK_TTL_SECONDS,
        "upi_expires_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(expires_at_ts)),
        "upi_expires_at_ts": expires_at_ts,
        "account_email": account_email,
        "amount": str(fields.get("amount") or result.get("amount") or ""),
        "cs_id": str(fields.get("cs_id") or ""),
        "upi_link": str(fields.get("upi_link") or hosted),
        "hosted_instructions_url": hosted,
        "upi_payment_uri": payment_uri,
        "qr_image_url_png": qr_image_png,
        "qr_image_url_svg": qr_image_svg,
        "qr_expires_at": str(fields.get("qr_expires_at") or ""),
        "chatgpt_checkout_url": str(fields.get("chatgpt_checkout_url") or ""),
        "billing": billing,
    }


def _append_link(record: dict[str, Any]) -> None:
    with LINKS_LOCK:
        items = _load_links()
        record_email = str(record.get("account_email") or "").strip().lower()
        record_link = _normalize_link(record.get("upi_link") or record.get("hosted_instructions_url"))
        if record_email:
            items = [item for item in items if str(item.get("account_email") or "").strip().lower() != record_email]
        elif record_link:
            items = [
                item
                for item in items
                if _normalize_link(item.get("upi_link") or item.get("hosted_instructions_url")) != record_link
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


def _timestamp_seconds(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    try:
        numeric = float(value)
        if numeric <= 0:
            return 0.0
        return numeric / 1000 if numeric > 1e12 else numeric
    except Exception:
        pass
    try:
        parsed = time.mktime(time.strptime(str(value).replace("T", " ").split(".")[0].rstrip("Z"), "%Y-%m-%d %H:%M:%S"))
        return float(parsed) if parsed > 0 else 0.0
    except Exception:
        return 0.0


def _temp_external_json(resp: requests.Response) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError(f"临时 UPI 服务返回非 JSON: HTTP {resp.status_code} {resp.text[:300]}") from None
    if not isinstance(data, dict):
        raise RuntimeError(f"临时 UPI 服务响应格式错误: {str(data)[:300]}")
    if not resp.ok:
        message = data.get("detail") or data.get("message") or data.get("error") or f"HTTP {resp.status_code}"
        raise RuntimeError(f"临时 UPI 服务拒绝请求: {message}")
    return data


def _temp_field(data: dict[str, Any], *names: str) -> str:
    sources: list[dict[str, Any]] = []
    for source in (data.get("result"), data.get("job"), data):
        if isinstance(source, dict) and source not in sources:
            sources.append(source)
    for source in sources:
        for name in names:
            value = source.get(name)
            if str(value or "").strip():
                return str(value).strip()
    return ""


def _temp_status(data: dict[str, Any]) -> str:
    return _temp_field(data, "status", "state").strip().lower()


def _is_temp_cdk_used_error(message: str) -> bool:
    text = str(message or "").strip().lower()
    return (
        "cdk has already been used" in text
        or "cdk already used" in text
        or "cdk 已使用" in text
        or "cdk已使用" in text
    )


def _is_temp_cdk_cooling_error(message: str) -> bool:
    text = str(message or "").strip().lower()
    return (
        "cdk is already running in another task" in text
        or "cdk already running in another task" in text
        or "cdk is running in another task" in text
        or "already running in another task" in text
        or "cdk 正在其他任务中运行" in text
        or "cdk正在其他任务中运行" in text
    )


def _temp_cdks(req: IndiaUpiTempBatchStartRequest) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    raw_items = list(req.cdks or [])
    raw_items.extend(str(req.cdk or "").replace(",", "\n").splitlines())
    for item in raw_items:
        cdk = str(item or "").strip()
        key = cdk.lower()
        if cdk and key not in seen:
            seen.add(key)
            values.append(cdk)
    return values


def _requested_temp_concurrency(req: IndiaUpiTempBatchStartRequest) -> int:
    try:
        requested = int(req.concurrency or 5)
    except Exception:
        requested = 5
    return max(1, min(MAX_TEMP_BATCH_CONCURRENCY, requested))


def _temp_batch_concurrency(req: IndiaUpiTempBatchStartRequest, total: int) -> int:
    return max(1, min(total, _requested_temp_concurrency(req)))


def _temp_cdk_assignments(cdks: list[str], total_accounts: int) -> list[str]:
    if total_accounts <= 0 or not cdks:
        return []
    return [cdks[index % len(cdks)] for index in range(total_accounts)]


def _create_temp_external_job(access_token: str, cdk: str) -> tuple[str, str, dict[str, Any]]:
    try:
        resp = requests.post(
            f"{TEMP_UPI_API_BASE}/api/run",
            json={"accessToken": access_token, "cdk": cdk},
            headers={"Content-Type": "application/json"},
            timeout=70,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"临时 UPI 服务请求失败: {exc}") from exc
    data = _temp_external_json(resp)
    remote_job_id = _temp_field(data, "jobId", "job_id", "id")
    job_token = _temp_field(data, "jobToken", "job_token", "token")
    if not remote_job_id:
        raise RuntimeError(f"临时 UPI 服务未返回 jobId: {str(data)[:300]}")
    if not job_token:
        raise RuntimeError(f"临时 UPI 服务未返回 jobToken: {str(data)[:300]}")
    return remote_job_id, job_token, data


def _poll_temp_external_job(remote_job_id: str, job_token: str, *, cancel_check=None) -> dict[str, Any]:
    terminal_success = {"success", "succeeded", "completed", "done"}
    terminal_failed = {"failed", "error", "stopped", "cancelled", "canceled"}
    last_data: dict[str, Any] = {}
    for _ in range(90):
        if callable(cancel_check) and cancel_check():
            raise RuntimeError("任务已取消")
        try:
            resp = requests.get(
                f"{TEMP_UPI_API_BASE}/api/jobs/{remote_job_id}",
                headers={"X-Job-Token": job_token},
                timeout=20,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"临时 UPI 服务查询失败: {exc}") from exc
        data = _temp_external_json(resp)
        last_data = data
        status = _temp_status(data)
        if status in terminal_success:
            return data
        if status in terminal_failed:
            message = _temp_field(data, "detail", "message", "error") or status
            raise RuntimeError(f"临时 UPI 提链失败: {message}")
        time.sleep(2.0)
    raise RuntimeError(f"临时 UPI 提链轮询超时: {str(last_data)[:300]}")


def _stop_temp_external_job(remote_job_id: str, job_token: str) -> None:
    if not remote_job_id or not job_token:
        return
    try:
        requests.post(
            f"{TEMP_UPI_API_BASE}/api/jobs/{remote_job_id}/stop",
            headers={"X-Job-Token": job_token},
            timeout=20,
        )
    except Exception:
        pass


def _temp_success_result(account_email: str, remote_job_id: str, data: dict[str, Any]) -> dict[str, Any]:
    upi_url = _temp_field(data, "upiUrl", "upi_url", "hosted_instructions_url", "hostedInstructionsUrl", "link", "url")
    payment_uri = _temp_field(data, "upiPaymentUri", "upi_payment_uri", "paymentUri", "payment_uri", "qr", "qrUrl")
    expires_at = _timestamp_seconds(_temp_field(data, "upiExpiresAt", "upi_expires_at", "expiresAt", "expires_at"))
    fields = {
        "amount": _temp_field(data, "amount", "expected_amount") or "0",
        "cs_id": _temp_field(data, "cs_id", "checkout_session_id", "checkoutSessionId"),
        "upi_link": upi_url or payment_uri,
        "hosted_instructions_url": upi_url,
        "upi_payment_uri": payment_uri,
        "upi_expires_at_ts": expires_at,
        "qr_image_url_svg": payment_uri if payment_uri.startswith("http") and ".svg" in payment_uri.lower() else "",
        "qr_image_url_png": payment_uri if payment_uri.startswith("http") and ".svg" not in payment_uri.lower() else "",
        "chatgpt_checkout_url": _temp_field(data, "chatgpt_checkout_url", "chatgptCheckoutUrl"),
    }
    if not fields["hosted_instructions_url"] and not fields["upi_payment_uri"]:
        raise RuntimeError(f"临时 UPI 提链成功但未返回 UPI 链接或付款二维码: remote_job={remote_job_id}")
    return {"ok": True, "account_email": account_email, "amount": fields["amount"], "fields": fields, "remote_job_id": remote_job_id}


def _is_job_cancel_requested(job_id: str) -> bool:
    with JOBS_LOCK:
        return bool((JOBS.get(job_id) or {}).get("cancel_requested"))


def _set_job_running_delta(job_id: str, delta: int) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        job["running_count"] = max(0, int(job.get("running_count") or 0) + delta)


def _mark_account_plus_upi(email: str, message: str = "User is already paid") -> dict[str, Any]:
    account_store.ensure_session_only_account(email)
    return account_store.update_account(
        email,
        account_type=account_store.ACCOUNT_TYPE_PLUS,
        last_bind_provider="upi",
        last_bind_status="success",
        last_bind_at=time.time(),
        plus_bound_at=time.time(),
        last_bind_message=message,
        last_bind_failure_stage="",
    ) or {}


def _payment_api_response_body(resp: requests.Response) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError:
        data = {"ok": False, "code": f"http_{resp.status_code}", "message": resp.text[:500] or "支付服务返回非 JSON 响应"}
    if not isinstance(data, dict):
        return {"ok": False, "code": "bad_payment_api_response", "message": "支付服务响应格式错误", "raw": str(data)[:500]}
    return data


def _payment_api_json(resp: requests.Response) -> dict[str, Any]:
    data = _payment_api_response_body(resp)
    if not resp.ok:
        raise HTTPException(status_code=resp.status_code, detail=data)
    if data.get("code") == "bad_payment_api_response":
        raise HTTPException(status_code=502, detail={"message": "支付服务响应格式错误"})
    return data


def _payment_api_submit_json(resp: requests.Response) -> dict[str, Any]:
    data = _payment_api_response_body(resp)
    if not resp.ok:
        result = dict(data)
        result["ok"] = False
        result["http_status"] = resp.status_code
        result.setdefault("code", f"http_{resp.status_code}")
        result.setdefault("message", "UPI-SCAN 支付服务拒绝提交")
        return result
    if data.get("code") == "bad_payment_api_response":
        raise HTTPException(status_code=502, detail={"message": "支付服务响应格式错误"})
    return data


def _payment_api_error(exc: requests.RequestException) -> HTTPException:
    return HTTPException(status_code=502, detail={"ok": False, "code": "upi_scan_api_unreachable", "message": f"UPI-SCAN 支付服务请求失败：{exc}"})


def _normalize_payment_link(value: Any) -> str:
    return str(value or "").strip().rstrip("/")


def _account_email_for_payment_link(link: str) -> str:
    target = _normalize_payment_link(link)
    if not target:
        return ""
    for item in _load_links():
        candidates = (
            item.get("hosted_instructions_url"),
            item.get("upi_link"),
            item.get("link"),
            item.get("url"),
        )
        if any(_normalize_payment_link(candidate) == target for candidate in candidates):
            return str(item.get("account_email") or item.get("accountEmail") or "").strip()
    return ""


def _mark_payment_success_account(job_id: str, message: str = "UPI-SCAN payment succeeded") -> dict[str, Any]:
    with PAYMENT_JOBS_LOCK:
        payment_job = PAYMENT_JOBS.get(job_id) or {}
        if payment_job.get("account_marked"):
            return dict(payment_job.get("account_update") or {})
        email = str(payment_job.get("account_email") or "").strip()
        link = str(payment_job.get("link") or "")
    if not email:
        email = _account_email_for_payment_link(link)
    if not email:
        return {}
    updated = _mark_account_plus_upi(email, message)
    result = {
        "email": email,
        "account_type": str(updated.get("account_type") or ""),
        "last_bind_provider": str(updated.get("last_bind_provider") or ""),
    }
    _set_account_status(email, UPI_STATUS_PAID, job_id=job_id)
    with PAYMENT_JOBS_LOCK:
        if job_id in PAYMENT_JOBS:
            PAYMENT_JOBS[job_id]["account_email"] = email
            PAYMENT_JOBS[job_id]["account_marked"] = True
            PAYMENT_JOBS[job_id]["account_update"] = result
    return result


def _delete_invalid_account(email: str) -> dict[str, Any]:
    return {
        "record_deleted": bool(account_store.delete_account(email)),
        "auth_session_deleted": bool(delete_auth_session(email)),
    }


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


def _delete_india_upi_account_everywhere(email: str) -> dict[str, Any]:
    clean_email = str(email or "").strip()
    upi_cleanup = delete_account_artifacts(clean_email)
    dashboard_account_deleted = bool(account_store.delete_account(clean_email))
    auth_session_deleted = bool(delete_auth_session(clean_email))
    return {
        "ok": True,
        "email": clean_email,
        "dashboard_account_deleted": dashboard_account_deleted,
        "auth_session_deleted": auth_session_deleted,
        "upi": upi_cleanup,
    }


def _run_batch_account(
    job_id: str,
    req: IndiaUpiBatchStartRequest,
    account: dict[str, Any],
    index: int,
    total: int,
    proxies: list[str],
) -> dict[str, Any]:
    email = str(account.get("email") or "").strip()
    started = time.monotonic()
    if _is_job_cancel_requested(job_id):
        _append_log(job_id, f"[{index}/{total}] 跳过账号：{email}（任务已取消）")
        return {"skipped": True, "email": email, "status": _set_account_status(email, UPI_STATUS_PENDING, job_id=job_id)}
    proxy_slot = f" proxy槽={(index - 1) % len(proxies) + 1}/{len(proxies)}" if proxies else ""
    _set_job_running_delta(job_id, 1)
    _append_log(job_id, f"[{index}/{total}] 开始账号：{email}{proxy_slot}")

    def account_log(message: str) -> None:
        _append_log(job_id, f"[{index}/{total}] {message}")

    attempts = 0
    try:
        _set_account_status(email, UPI_STATUS_RUNNING, job_id=job_id)
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
            cfg = UpiJobConfig(
                access_token=token,
                local_proxy=str(req.local_proxy or "").strip(),
                kookeey_user=str(req.kookeey_user or "").strip(),
                kookeey_pass=str(req.kookeey_pass or ""),
                kookeey_endpoint=str(req.kookeey_endpoint or "gate.kookeey.info:1000").strip(),
                region=(req.region or "IN").strip().upper() or "IN",
                direct_proxies=attempt_proxies,
                apply_promo=req.promo_mode == "promo",
            )
            try:
                cfg = _preflight_upi_proxy_or_raise(cfg, account_log)
                result = generate_upi_trial(cfg, log=account_log)
                if attempt > 1:
                    _append_log(job_id, f"[{index}/{total}] 重试成功：{email} attempt={attempt}")
                break
            except Exception as exc:
                last_error = str(exc)
                failure = classify_upi_failure(last_error)
                if last_error.startswith("代理预检失败"):
                    status = _set_account_status(email, UPI_STATUS_FAILED, error=last_error, job_id=job_id, failure=failure)
                    _append_log(job_id, f"[{index}/{total}] 代理预检已达到上限，停止真实提链：{email} {last_error}")
                    return {
                        "ok": False,
                        "email": email,
                        "error": {
                            "email": email,
                            "elapsed_s": round(time.monotonic() - started, 1),
                            "attempts": attempt,
                            "error": last_error,
                            **failure,
                        },
                        "status": status,
                    }
                if pix_routes._is_already_paid_error(last_error):
                    _mark_account_plus_upi(email, last_error)
                    status = _set_account_status(email, UPI_STATUS_SUCCESS, error=last_error, job_id=job_id, failure=failure)
                    _append_log(job_id, f"[{index}/{total}] 账号已是 Plus：{email}，已更新账号类型=Plus 绑定渠道=UPI")
                    return {"skipped": True, "email": email, "reason": "账号已是 Plus，已标记绑定渠道 UPI", "status": status, **failure}
                if pix_routes._is_token_invalidated_error(last_error) or pix_routes._is_no_organization_error(last_error):
                    cleanup = _delete_invalid_account(email)
                    status = _set_account_status(email, UPI_STATUS_FAILED, error=last_error, job_id=job_id, failure=failure)
                    return {
                        "ok": False,
                        "email": email,
                        "error": {
                            "email": email,
                            "elapsed_s": round(time.monotonic() - started, 1),
                            "attempts": attempt,
                            "error": f"账号不可用，已从账号池删除：{last_error}",
                            "cleanup": cleanup,
                            **failure,
                        },
                        "status": status,
                    }
                if pix_routes._is_non_zero_after_promo_error(last_error):
                    cleanup = _delete_invalid_account(email)
                    status = _set_account_status(email, UPI_STATUS_FAILED, error=last_error, job_id=job_id, failure=failure)
                    _append_log(job_id, f"[{index}/{total}] 账号金额非 0，已从账号池删除：{email} cleanup={cleanup}")
                    return {
                        "ok": False,
                        "email": email,
                        "error": {
                            "email": email,
                            "elapsed_s": round(time.monotonic() - started, 1),
                            "attempts": attempt,
                            "error": f"金额非 0，已从账号池删除：{last_error}",
                            "cleanup": cleanup,
                            "account_deleted": True,
                            **failure,
                        },
                        "status": status,
                        "account_deleted": True,
                    }
                _append_log(job_id, f"[{index}/{total}] 第 {attempt}/{max_attempts} 次失败：{email} [{failure['failure_category']}] {last_error}")
                if attempt >= max_attempts:
                    raise
                time.sleep(min(2.0, 0.5 * attempt))
        if result is None:
            raise RuntimeError(last_error or "提链失败")
        result["account_email"] = email
        record = _link_record_from_result(job_id, email, result)
        _append_link(record)
        status = _set_account_status(email, UPI_STATUS_SUCCESS, job_id=job_id)
        compact = {"email": email, "elapsed_s": round(time.monotonic() - started, 1), "attempts": attempts, "link": record}
        _append_log(job_id, f"[{index}/{total}] 成功：{email} attempts={attempts} cs_id={record.get('cs_id')}")
        return {"ok": True, "email": email, "success": compact, "status": status}
    except Exception as exc:
        error = str(exc)
        failure = classify_upi_failure(error)
        item = {"email": email, "elapsed_s": round(time.monotonic() - started, 1), "attempts": attempts or 1, "error": error, **failure}
        status = _set_account_status(email, UPI_STATUS_FAILED, error=error, job_id=job_id, failure=failure)
        _append_log(job_id, f"[{index}/{total}] 最终失败：{email} attempts={attempts or 1} [{failure['failure_category']}] {exc}")
        return {"ok": False, "email": email, "error": item, "status": status}
    finally:
        _set_job_running_delta(job_id, -1)


def _run_temp_batch_account(
    job_id: str,
    account: dict[str, Any],
    cdk: str,
    index: int,
    total: int,
) -> dict[str, Any]:
    email = str(account.get("email") or "").strip()
    started = time.monotonic()
    clean_cdk = str(cdk or "").strip()
    if _is_job_cancel_requested(job_id):
        _append_log(job_id, f"[{index}/{total}] 跳过账号：{email}（任务已取消）")
        return {"skipped": True, "email": email, "cdk": clean_cdk, "status": _set_account_status(email, UPI_STATUS_PENDING, job_id=job_id)}
    _set_job_running_delta(job_id, 1)
    _append_log(job_id, f"[{index}/{total}] 临时 UPI 提链开始账号：{email}")
    try:
        _set_account_status(email, UPI_STATUS_RUNNING, job_id=job_id)
        token = _load_token_for_email(email)
        if not token:
            raise RuntimeError("账号缺少有效 accessToken")
        if not clean_cdk:
            raise RuntimeError("临时 UPI 提链缺少 CDK")
        remote_job_id, job_token, created = _create_temp_external_job(token, clean_cdk)
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if job is not None:
                external_jobs = job.setdefault("external_jobs", {})
                external_jobs[email] = {"job_id": remote_job_id, "job_token": job_token}
        _append_log(job_id, f"[{index}/{total}] 已提交 Public UPI Generate 任务：{remote_job_id}")
        if _temp_status(created) in {"success", "succeeded", "completed", "done"}:
            data = created
        else:
            data = _poll_temp_external_job(remote_job_id, job_token, cancel_check=lambda: _is_job_cancel_requested(job_id))
        result = _temp_success_result(email, remote_job_id, data)
        record = _link_record_from_result(job_id, email, result)
        _append_link(record)
        status = _set_account_status(email, UPI_STATUS_SUCCESS, job_id=job_id)
        compact = {
            "email": email,
            "elapsed_s": round(time.monotonic() - started, 1),
            "attempts": 1,
            "link": record,
            "remote_job_id": remote_job_id,
            "cdk": clean_cdk,
        }
        _append_log(job_id, f"[{index}/{total}] 临时 UPI 提链成功：{email} remote_job={remote_job_id}")
        return {"ok": True, "email": email, "success": compact, "status": status}
    except Exception as exc:
        error = str(exc)
        cdk_cooling = _is_temp_cdk_cooling_error(error)
        item = {
            "email": email,
            "elapsed_s": round(time.monotonic() - started, 1),
            "attempts": 1,
            "error": error,
            "cdk": clean_cdk,
            "cdk_used": _is_temp_cdk_used_error(error),
            "cdk_cooling": cdk_cooling,
            "cdk_cooldown_seconds": TEMP_CDK_COOLDOWN_SECONDS if cdk_cooling else 0,
        }
        status = _set_account_status(email, UPI_STATUS_FAILED, error=error, job_id=job_id)
        _append_log(job_id, f"[{index}/{total}] 临时 UPI 提链失败：{email} {error}")
        return {"ok": False, "email": email, "error": item, "status": status}
    finally:
        _set_job_running_delta(job_id, -1)


def _run_temp_batch_job(job_id: str, req: IndiaUpiTempBatchStartRequest) -> None:
    def log(message: str) -> None:
        _append_log(job_id, message)

    try:
        selector = IndiaUpiBatchStartRequest(accountEmails=req.account_emails, maxAccounts=req.max_accounts, concurrency=req.concurrency)
        accounts = _select_batch_accounts(selector)
        if not accounts:
            raise RuntimeError("没有可用账号，请先选择账号池账号或刷新账号池")
        cdks = _temp_cdks(req)
        if not cdks:
            raise RuntimeError("请填写临时 UPI 提链 CDK")
        concurrency = _temp_batch_concurrency(req, len(accounts))
        successes: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        account_statuses: dict[str, dict[str, Any]] = {}
        for account in accounts:
            email = str(account.get("email") or "").strip()
            account_statuses[email] = _set_account_status(email, UPI_STATUS_PENDING, job_id=job_id)
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
            JOBS[job_id]["temp"] = True
            JOBS[job_id]["external_jobs"] = {}
        log(f"临时 UPI 提链任务开始：{len(accounts)} 个账号，并发 {concurrency}")
        completed = 0
        cdk_assignments = _temp_cdk_assignments(cdks, len(accounts))
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [
                executor.submit(_run_temp_batch_account, job_id, account, cdk_assignments[index - 1], index, len(accounts))
                for index, account in enumerate(accounts, start=1)
            ]
            for future in as_completed(futures):
                item = future.result()
                email = str(item.get("email") or "")
                if item.get("skipped"):
                    skipped.append({"email": email, "cdk": item.get("cdk") or "", "reason": item.get("reason") or "任务已取消"})
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
        log(f"临时 UPI 提链任务完成：成功 {len(successes)}，失败 {len(errors)}，跳过 {len(skipped)}")
    except Exception as exc:
        with JOBS_LOCK:
            if job_id not in JOBS:
                return
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error"] = str(exc)
            JOBS[job_id]["finished_at"] = time.time()
        _append_log(job_id, f"失败: {exc}")


def _run_batch_job(job_id: str, req: IndiaUpiBatchStartRequest) -> None:
    def log(message: str) -> None:
        _append_log(job_id, message)

    try:
        accounts = _select_batch_accounts(req)
        if not accounts:
            raise RuntimeError("没有可用账号，请先选择账号池账号或刷新账号池")
        proxies = _parse_proxies(req.proxies)
        if not proxies and (not req.kookeey_user or not req.kookeey_pass):
            raise RuntimeError("请填写 IN 代理列表，或填写 Kookeey 用户名/密码")
        concurrency = _batch_concurrency(req, len(accounts))
        successes: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        account_statuses: dict[str, dict[str, Any]] = {}
        for account in accounts:
            email = str(account.get("email") or "").strip()
            account_statuses[email] = _set_account_status(email, UPI_STATUS_PENDING, job_id=job_id)
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
        log(f"UPI 提链任务开始：{len(accounts)} 个账号，并发 {concurrency}，promo={req.promo_mode}")
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
        log(f"UPI 提链任务完成：成功 {len(successes)}，失败 {len(errors)}，跳过 {len(skipped)}")
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
            "result": None,
            "error": None, "created_at": created, "finished_at": None,
            "account_email": account_emails[0] if len(account_emails) == 1 else "",
            "total": len(account_emails), "completed": 0,
            "concurrency": max(1, min(MAX_TEMP_BATCH_CONCURRENCY if temp else MAX_BATCH_CONCURRENCY, int(concurrency or 1))),
            "cancel_requested": False, "running_count": 0, "skipped": [], "account_statuses": {},
            "temp": bool(temp), "external_jobs": {},
        }
    return job_id


def _job_snapshot(job_id: str) -> dict[str, Any]:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return {"id": job["id"], "status": job["status"], "logs": list(job["logs"]), "result": job["result"], "error": job["error"], "created_at": job["created_at"], "finished_at": job["finished_at"], "account_email": job.get("account_email") or "", "total": job.get("total") or 0, "completed": job.get("completed") or 0, "concurrency": job.get("concurrency") or 1, "running_count": job.get("running_count") or 0, "cancel_requested": bool(job.get("cancel_requested")), "skipped": job.get("skipped") or [], "account_statuses": job.get("account_statuses") or {}, "temp": bool(job.get("temp"))}


def create_india_upi_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/india-upi/accounts")
    def get_india_upi_accounts() -> dict[str, Any]:
        return {"accounts": _iter_auth_accounts_with_upi_status()}

    @router.delete("/api/india-upi/accounts/{email}")
    def delete_india_upi_account(email: str) -> dict[str, Any]:
        clean_email = str(email or "").strip()
        if not clean_email:
            raise HTTPException(status_code=400, detail="email required")
        return _delete_india_upi_account_everywhere(clean_email)

    @router.post("/api/india-upi/accounts/delete")
    def delete_india_upi_accounts(req: IndiaUpiDeleteAccountsRequest) -> dict[str, Any]:
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
        results = [_delete_india_upi_account_everywhere(email) for email in emails]
        return {"ok": True, "deleted": len(results), "results": results}

    @router.post("/api/india-upi/start")
    def start_india_upi(req: IndiaUpiStartRequest) -> dict[str, str]:
        email = str(req.account_email or "").strip()
        if not email:
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "请选择要提链的账号"})
        job_id = _new_job([email], req.concurrency)
        threading.Thread(target=_run_batch_job, args=(job_id, IndiaUpiBatchStartRequest(**req.model_dump() | {"account_emails": [email]})), daemon=True).start()
        return {"job_id": job_id}

    @router.post("/api/india-upi/batch/start")
    def start_india_upi_batch(req: IndiaUpiBatchStartRequest) -> dict[str, str]:
        emails = list(req.account_emails)
        if req.max_accounts and req.max_accounts > 0:
            emails = emails[: int(req.max_accounts)]
        if not emails:
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "请选择要提链的账号"})
        job_id = _new_job(emails, req.concurrency)
        threading.Thread(target=_run_batch_job, args=(job_id, req), daemon=True).start()
        return {"job_id": job_id}

    @router.post("/api/india-upi/temp/batch/start")
    def start_india_upi_temp_batch(req: IndiaUpiTempBatchStartRequest) -> dict[str, str]:
        emails = list(req.account_emails)
        if req.max_accounts and req.max_accounts > 0:
            emails = emails[: int(req.max_accounts)]
        if not emails:
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "请选择要提链的账号"})
        if not _temp_cdks(req):
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "请填写临时 UPI 提链 CDK"})
        job_id = _new_job(emails, _requested_temp_concurrency(req), temp=True)
        threading.Thread(target=_run_temp_batch_job, args=(job_id, req), daemon=True).start()
        return {"job_id": job_id}

    @router.get("/api/india-upi/jobs/{job_id}")
    def get_india_upi_job(job_id: str) -> dict[str, Any]:
        return _job_snapshot(job_id)

    @router.post("/api/india-upi/jobs/{job_id}/cancel")
    def cancel_india_upi_job(job_id: str) -> dict[str, Any]:
        should_log = False
        external_jobs: dict[str, dict[str, Any]] = {}
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="job not found")
            if job.get("status") in TERMINAL_STATUSES:
                return {"ok": True, "job_id": job_id, "status": job.get("status"), "cancel_requested": bool(job.get("cancel_requested"))}
            job["cancel_requested"] = True
            if job.get("status") in {"queued", "running"}:
                job["status"] = "cancelling"
            external_jobs = dict(job.get("external_jobs") or {}) if job.get("temp") else {}
            should_log = True
        for external in external_jobs.values():
            if isinstance(external, dict):
                _stop_temp_external_job(str(external.get("job_id") or ""), str(external.get("job_token") or ""))
        if should_log:
            _append_log(job_id, "收到取消请求：正在停止未开始的账号，已运行账号会跑到当前步骤结束")
        return {"ok": True, "job_id": job_id, "status": "cancelling", "cancel_requested": True}

    @router.get("/api/india-upi/links")
    def get_india_upi_links() -> dict[str, Any]:
        return {"links": _load_links()}

    @router.post("/api/india-upi/links/delete")
    def delete_india_upi_links(req: IndiaUpiDeleteLinksRequest) -> dict[str, Any]:
        ids = {str(item) for item in req.ids if str(item)}
        items = _load_links()
        kept = [item for item in items if str(item.get("id") or "") not in ids] if ids else items
        if ids:
            _save_links(kept)
        return {"deleted": len(items) - len(kept), "links": kept}

    @router.post("/api/india-upi/links/clear")
    def clear_india_upi_links() -> dict[str, Any]:
        count = len(_load_links())
        _save_links([])
        return {"deleted": count, "links": []}

    @router.post("/api/india-upi/payment/submit")
    def submit_india_upi_payment(req: IndiaUpiPaymentSubmitRequest | None = None) -> dict[str, Any]:
        req = req or IndiaUpiPaymentSubmitRequest()
        cdk = str(req.cdk or "").strip()
        link = str(req.link or "").strip()
        if not cdk or not link:
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "UPI-SCAN CDK 和 UPI 链接不能为空"})
        try:
            resp = requests.post(
                f"{UPI_SCAN_API_BASE}/api/submit",
                json={"cdk": cdk, "link": link},
                headers={"Content-Type": "application/json"},
                timeout=70,
            )
        except requests.RequestException as exc:
            raise _payment_api_error(exc) from exc
        data = _payment_api_submit_json(resp)
        job_id = str(data.get("job_id") or data.get("jobId") or data.get("id") or "").strip()
        if job_id:
            with PAYMENT_JOBS_LOCK:
                PAYMENT_JOBS[job_id] = {
                    "job_id": job_id,
                    "status_token": str(data.get("status_token") or data.get("jobToken") or data.get("job_token") or data.get("token") or ""),
                    "link": link,
                    "cdk": cdk,
                    "account_email": _account_email_for_payment_link(link),
                    "account_marked": False,
                    "account_update": {},
                    "created_at": time.time(),
                }
        return data

    @router.get("/api/india-upi/payment/jobs/{job_id}")
    def get_india_upi_payment_job(job_id: str, token: str = Query("")) -> dict[str, Any]:
        clean_job_id = str(job_id or "").strip()
        clean_token = str(token or "").strip()
        if not clean_job_id or not clean_token:
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "job_id 和 token 不能为空"})
        try:
            resp = requests.get(
                f"{UPI_SCAN_API_BASE}/api/jobs/{clean_job_id}",
                params={"token": clean_token},
                headers={"X-Job-Token": clean_token},
                timeout=20,
            )
        except requests.RequestException as exc:
            raise _payment_api_error(exc) from exc
        data = _payment_api_json(resp)
        job = data.get("job") if isinstance(data.get("job"), dict) else {}
        if str(job.get("status") or "").strip().lower() == "succeeded":
            account_update = _mark_payment_success_account(clean_job_id, str(job.get("message") or "UPI-SCAN payment succeeded"))
            if account_update:
                job["account_email"] = account_update.get("email") or ""
                job["account_type"] = account_update.get("account_type") or ""
                job["last_bind_provider"] = account_update.get("last_bind_provider") or ""
                job["account_marked_plus"] = True
        return data

    return router
