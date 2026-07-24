"""Brazil PIX link extraction routes."""

from __future__ import annotations

import base64
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

from autotoken.core.paths import PROJECT_ROOT
from autotoken.payments.brazil_pix import PixJobConfig, build_pix_dynamic_proxy, generate_pix_trial
from autotoken.services import proxy_runtime
from autotoken.storage import accounts as account_store
from autotoken.storage.auth_session_store import delete_auth_session

AUTH_SESSION_DIR = PROJECT_ROOT / "data" / "auth_session"
LINKS_FILE = PROJECT_ROOT / "data" / "brazil_pix_links.json"
ACCOUNT_STATUS_FILE = PROJECT_ROOT / "data" / "brazil_pix_account_status.json"
PIX_CDK_API_BASE = "https://pix.iceaix.com"
TEMP_PIX_CDK_API_BASE = "https://pix.olimap.top/api/v1"
MAX_BATCH_CONCURRENCY = 10
MAX_ACCOUNT_ATTEMPTS = 5
MAX_CONFIGURABLE_ACCOUNT_ATTEMPTS = 20
PROXY_PREFLIGHT_MAX_ATTEMPTS = 3
JOBS: dict[str, dict[str, Any]] = {}
PAYMENT_JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()
PAYMENT_JOBS_LOCK = threading.RLock()
LINKS_LOCK = threading.RLock()
ACCOUNT_STATUS_LOCK = threading.RLock()
TEMP_CDK_STATUS_CACHE_TTL_S = 120
TEMP_CDK_STATUS_STALE_TTL_S = 1800
TEMP_CDK_STATUS_MIN_INTERVAL_S = 0.25
TEMP_CDK_STATUS_CACHE: dict[str, dict[str, Any]] = {}
TEMP_CDK_STATUS_CACHE_LOCK = threading.RLock()
TEMP_CDK_STATUS_RATE_LOCK = threading.Lock()
TEMP_CDK_STATUS_LAST_REQUEST_AT = 0.0


class BrazilPixStartRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    access_token: str = Field("", alias="accessToken")
    account_email: str = Field("", alias="accountEmail")
    proxies: str | list[str] = ""
    local_proxy: str = Field("", alias="localProxy")
    kookeey_user: str = Field("", alias="kookeeyUser")
    kookeey_pass: str = Field("", alias="kookeeyPass")
    kookeey_endpoint: str = Field("gate.kookeey.info:1000", alias="kookeeyEndpoint")
    region: str = "BR"
    max_attempts: int = Field(MAX_ACCOUNT_ATTEMPTS, alias="maxAttempts")

    @field_validator("max_attempts", mode="before")
    @classmethod
    def _clean_max_attempts(cls, value: Any) -> int:
        try:
            attempts = int(value or MAX_ACCOUNT_ATTEMPTS)
        except Exception:
            attempts = MAX_ACCOUNT_ATTEMPTS
        return max(1, min(MAX_CONFIGURABLE_ACCOUNT_ATTEMPTS, attempts))


class BrazilPixBatchStartRequest(BrazilPixStartRequest):
    account_emails: list[str] = Field(default_factory=list, alias="accountEmails")
    max_accounts: int = Field(0, alias="maxAccounts")
    concurrency: int = 1


class BrazilPixTempBatchStartRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    account_emails: list[str] = Field(default_factory=list, alias="accountEmails")
    cdk: str = ""
    cdks: list[str] = Field(default_factory=list)
    max_accounts: int = Field(0, alias="maxAccounts")
    concurrency: int = 5


class BrazilPixTempCdkStatusRequest(BaseModel):
    cdk: str = ""
    force: bool = False


class BrazilPixDeleteLinksRequest(BaseModel):
    ids: list[str] = Field(default_factory=list)


class BrazilPixDeleteAccountsRequest(BaseModel):
    emails: list[str] = Field(default_factory=list)


class BrazilPixPaymentSubmitRequest(BaseModel):
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


ACCOUNT_STATUS_PENDING = "pending"
ACCOUNT_STATUS_RUNNING = "running"
ACCOUNT_STATUS_SUCCESS = "success"
ACCOUNT_STATUS_FAILED = "failed"
ACCOUNT_STATUS_PAID = "paid"
ACCOUNT_STATUS_LABELS = {
    ACCOUNT_STATUS_PENDING: "未提链",
    ACCOUNT_STATUS_RUNNING: "提链中",
    ACCOUNT_STATUS_SUCCESS: "已提链",
    ACCOUNT_STATUS_FAILED: "提链失败",
    ACCOUNT_STATUS_PAID: "已支付",
}


def _decode_jwt_exp(token: str) -> int:
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return 0
        payload = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
        return int(json.loads(base64.urlsafe_b64decode(payload)).get("exp") or 0)
    except Exception:
        return 0


def _auth_email_from_path(path: Path, data: dict[str, Any]) -> str:
    email = str(data.get("email") or "").strip()
    if email:
        return email
    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    email = str(user.get("email") or "").strip()
    if email:
        return email
    stem = path.stem
    return stem.replace("_", ".") if "@" in stem else stem


def _extract_token(value: Any) -> str:
    if isinstance(value, str):
        raw = value.strip()
        if raw.startswith("{") or raw.startswith("["):
            try:
                return _extract_token(json.loads(raw)) or raw
            except Exception:
                return raw
        return raw
    if isinstance(value, list):
        for item in value:
            token = _extract_token(item)
            if token:
                return token
    if isinstance(value, dict):
        for key in ("accessToken", "access_token", "chatgpt_access_token", "token"):
            if str(value.get(key) or "").strip():
                return str(value.get(key)).strip()
        for item in value.values():
            token = _extract_token(item)
            if token:
                return token
    return ""


def _pix_paid_emails() -> set[str]:
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
        pix_bound = bind_provider == "pix" and bind_status in {"success", "succeeded", "ok"}
        if account_type == account_store.ACCOUNT_TYPE_PLUS or status == account_store.STATUS_PLUS or pix_bound:
            paid.add(email)
    return paid


def _dashboard_account_email_keys() -> set[str]:
    return set(_dashboard_accounts_by_email())


def _dashboard_accounts_by_email() -> dict[str, dict[str, Any]]:
    try:
        return {
            str(account.get("email") or "").strip().lower(): account
            for account in account_store.load_accounts()
            if str(account.get("email") or "").strip()
        }
    except Exception:
        return {}


def _pix_pool_excluded_emails() -> set[str]:
    return _pix_paid_emails()


def _iter_auth_accounts(*, include_paid: bool = False) -> list[dict[str, Any]]:
    now = time.time()
    accounts: list[dict[str, Any]] = []
    if not AUTH_SESSION_DIR.exists():
        return accounts
    dashboard_accounts = _dashboard_accounts_by_email()
    dashboard_emails = set(dashboard_accounts)
    excluded_emails = set() if include_paid else _pix_pool_excluded_emails()
    for path in sorted(AUTH_SESSION_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        email = _auth_email_from_path(path, data)
        if dashboard_emails and email.lower() not in dashboard_emails:
            continue
        if email.lower() in excluded_emails:
            continue
        token = _extract_token(data)
        if not token or len(token) < 50:
            continue
        exp = _decode_jwt_exp(token)
        if exp and exp <= now + 300:
            continue
        dashboard_account = dashboard_accounts.get(email.lower()) or {}
        accounts.append(
            {
                "email": email,
                "auth_file": str(path),
                "expires_at": exp,
                "ttl_seconds": max(0, int(exp - now)) if exp else 0,
                "updated_at": dashboard_account.get("updated_at") or path.stat().st_mtime,
            }
        )
    accounts.sort(key=lambda item: (float(item.get("updated_at") or 0), item["email"].lower()), reverse=True)
    return accounts


def _normalize_account_status(value: Any) -> str:
    status = str(value or ACCOUNT_STATUS_PENDING).strip().lower()
    if status in ACCOUNT_STATUS_LABELS:
        return status
    return ACCOUNT_STATUS_PENDING


def _load_account_statuses() -> dict[str, dict[str, Any]]:
    with ACCOUNT_STATUS_LOCK:
        try:
            data = json.loads(ACCOUNT_STATUS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        statuses: dict[str, dict[str, Any]] = {}
        for raw_email, raw_item in data.items():
            email = str(raw_email or "").strip().lower()
            if not email:
                continue
            item = raw_item if isinstance(raw_item, dict) else {}
            statuses[email] = {
                "status": _normalize_account_status(item.get("status")),
                "error": str(item.get("error") or ""),
                "job_id": str(item.get("job_id") or ""),
                "updated_at": str(item.get("updated_at") or ""),
            }
        return statuses


def _save_account_statuses(statuses: dict[str, dict[str, Any]]) -> None:
    with ACCOUNT_STATUS_LOCK:
        ACCOUNT_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        ACCOUNT_STATUS_FILE.write_text(json.dumps(statuses, ensure_ascii=False, indent=2), encoding="utf-8")


def _set_account_status(email: str, status: str, *, error: str = "", job_id: str = "") -> dict[str, Any]:
    key = str(email or "").strip().lower()
    if not key:
        return {}
    item = {
        "status": _normalize_account_status(status),
        "error": str(error or ""),
        "job_id": str(job_id or ""),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with ACCOUNT_STATUS_LOCK:
        statuses = _load_account_statuses()
        statuses[key] = item
        _save_account_statuses(statuses)
    return item


def _account_status_snapshot(
    email: str,
    statuses: dict[str, dict[str, Any]],
    linked_emails: set[str],
    paid_emails: set[str] | None = None,
) -> dict[str, Any]:
    key = str(email or "").strip().lower()
    item = dict(statuses.get(key) or {})
    if key in (paid_emails or set()):
        item = {"status": ACCOUNT_STATUS_PAID, "error": "", "job_id": "", "updated_at": ""}
    elif not item and key in linked_emails:
        item = {"status": ACCOUNT_STATUS_SUCCESS, "error": "", "job_id": "", "updated_at": ""}
    status = _normalize_account_status(item.get("status"))
    return {
        "status": status,
        "status_text": ACCOUNT_STATUS_LABELS[status],
        "error": str(item.get("error") or ""),
        "job_id": str(item.get("job_id") or ""),
        "updated_at": str(item.get("updated_at") or ""),
    }


def _iter_auth_accounts_with_pix_status() -> list[dict[str, Any]]:
    accounts = _iter_auth_accounts(include_paid=True)
    statuses = _load_account_statuses()
    paid_emails = _pix_paid_emails()
    linked_emails = {
        str(item.get("account_email") or "").strip().lower()
        for item in _load_links()
        if str(item.get("account_email") or "").strip()
    }
    for account in accounts:
        snapshot = _account_status_snapshot(account["email"], statuses, linked_emails, paid_emails)
        account.update(
            {
                "pix_status": snapshot["status"],
                "pix_status_text": snapshot["status_text"],
                "pix_error": snapshot["error"],
                "pix_status_updated_at": snapshot["updated_at"],
                "pix_selectable": snapshot["status"] != ACCOUNT_STATUS_PAID,
            }
        )
    return accounts


def _load_token_for_email(email: str) -> str:
    target = email.strip().lower()
    for item in _iter_auth_accounts():
        if item["email"].lower() != target:
            continue
        data = json.loads(Path(item["auth_file"]).read_text(encoding="utf-8"))
        token = _extract_token(data)
        if token:
            return token
    return ""


def _parse_proxies(value: str | list[str]) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "")
    lines: list[str] = []
    for raw in text.replace(",", "\n").splitlines():
        item = raw.strip()
        if item:
            lines.append(item)
    return lines


def _dedupe_link_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_accounts: set[str] = set()
    seen_urls: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        email = str(item.get("account_email") or "").strip().lower()
        url = _normalize_payment_link(item.get("hosted_instructions_url"))
        if email:
            if email in seen_accounts:
                continue
            seen_accounts.add(email)
        elif url:
            if url in seen_urls:
                continue
        if url:
            seen_urls.add(url)
        deduped.append(item)
    return deduped


def _load_links() -> list[dict[str, Any]]:
    with LINKS_LOCK:
        try:
            data = json.loads(LINKS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        items = [item for item in data if isinstance(item, dict)]
        deduped = _dedupe_link_items(items)
        if len(deduped) != len(items):
            LINKS_FILE.parent.mkdir(parents=True, exist_ok=True)
            LINKS_FILE.write_text(json.dumps(deduped[:1000], ensure_ascii=False, indent=2), encoding="utf-8")
        return deduped


def _save_links(items: list[dict[str, Any]]) -> None:
    with LINKS_LOCK:
        LINKS_FILE.parent.mkdir(parents=True, exist_ok=True)
        LINKS_FILE.write_text(json.dumps(_dedupe_link_items(items)[:1000], ensure_ascii=False, indent=2), encoding="utf-8")


def _known_account_email_keys() -> set[str]:
    keys: set[str] = _dashboard_account_email_keys()
    if keys:
        return keys
    try:
        for account in _iter_auth_accounts():
            email = str(account.get("email") or "").strip().lower()
            if email:
                keys.add(email)
    except Exception:
        pass
    return keys


def _load_links_pruning_deleted_accounts() -> tuple[list[dict[str, Any]], int]:
    items = _load_links()
    known_emails = _known_account_email_keys()
    paid_emails = _pix_paid_emails()
    kept: list[dict[str, Any]] = []
    removed_emails: set[str] = set()
    for item in items:
        email = str(item.get("account_email") or "").strip().lower()
        if email and (email not in known_emails or email in paid_emails):
            removed_emails.add(email)
            continue
        kept.append(item)
    if len(kept) != len(items):
        _save_links(kept)
        with ACCOUNT_STATUS_LOCK:
            statuses = _load_account_statuses()
            changed = False
            for email in removed_emails:
                changed = statuses.pop(email, None) is not None or changed
            if changed:
                _save_account_statuses(statuses)
    return kept, len(items) - len(kept)


def delete_account_artifacts(email: str) -> dict[str, Any]:
    """Remove Brazil PIX link/status records that belong to a deleted account."""
    target = str(email or "").strip().lower()
    if not target:
        return {"links_deleted": 0, "status_deleted": False}

    items = _load_links()
    kept = [
        item
        for item in items
        if str(item.get("account_email") or "").strip().lower() != target
    ]
    if len(kept) != len(items):
        _save_links(kept)

    with ACCOUNT_STATUS_LOCK:
        statuses = _load_account_statuses()
        status_deleted = statuses.pop(target, None) is not None
        if status_deleted:
            _save_account_statuses(statuses)

    return {
        "links_deleted": len(items) - len(kept),
        "status_deleted": status_deleted,
    }


def _delete_brazil_pix_account_everywhere(email: str) -> dict[str, Any]:
    clean_email = str(email or "").strip()
    pix_cleanup = delete_account_artifacts(clean_email)
    dashboard_account_deleted = bool(account_store.delete_account(clean_email))
    auth_session_deleted = bool(delete_auth_session(clean_email))
    return {
        "ok": True,
        "email": clean_email,
        "dashboard_account_deleted": dashboard_account_deleted,
        "auth_session_deleted": auth_session_deleted,
        "pix": pix_cleanup,
    }


def _link_record_from_result(job_id: str, account_email: str, result: dict[str, Any]) -> dict[str, Any]:
    fields = result.get("fields") if isinstance(result.get("fields"), dict) else {}
    billing = fields.get("billing") if isinstance(fields.get("billing"), dict) else result.get("billing") or {}
    return {
        "id": uuid.uuid4().hex[:16],
        "job_id": job_id,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "account_email": account_email,
        "amount": str(fields.get("amount") or result.get("amount") or ""),
        "cs_id": str(fields.get("cs_id") or ""),
        "pix_copy_paste": str(fields.get("pix_copy_paste") or ""),
        "hosted_instructions_url": str(fields.get("hosted_instructions_url") or ""),
        "image_url_png": str(fields.get("image_url_png") or ""),
        "image_url_svg": str(fields.get("image_url_svg") or ""),
        "chatgpt_checkout_url": str(fields.get("chatgpt_checkout_url") or ""),
        "billing": billing,
    }


def _append_link(record: dict[str, Any]) -> None:
    with LINKS_LOCK:
        try:
            data = json.loads(LINKS_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = []
        items = data if isinstance(data, list) else []
        items = [item for item in items if isinstance(item, dict)]
        record_email = str(record.get("account_email") or "").strip().lower()
        record_url = _normalize_payment_link(record.get("hosted_instructions_url"))
        if record_email:
            items = [item for item in items if str(item.get("account_email") or "").strip().lower() != record_email]
        elif record_url:
            items = [item for item in items if _normalize_payment_link(item.get("hosted_instructions_url")) != record_url]
        items.insert(0, record)
        LINKS_FILE.parent.mkdir(parents=True, exist_ok=True)
        LINKS_FILE.write_text(json.dumps(_dedupe_link_items(items)[:1000], ensure_ascii=False, indent=2), encoding="utf-8")


def _append_log(job_id: str, message: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {message}"
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        job["logs"].append(line)
        job["logs"] = job["logs"][-500:]


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
        result.setdefault("message", "支付服务拒绝提交")
        return result
    if data.get("code") == "bad_payment_api_response":
        raise HTTPException(status_code=502, detail={"message": "支付服务响应格式错误"})
    return data


def _payment_api_error(exc: requests.RequestException) -> HTTPException:
    return HTTPException(status_code=502, detail={"ok": False, "code": "payment_api_unreachable", "message": f"支付服务请求失败：{exc}"})


def _normalize_payment_link(value: Any) -> str:
    return str(value or "").strip().rstrip("/")


def _account_email_for_payment_link(link: str) -> str:
    target = _normalize_payment_link(link)
    if not target:
        return ""
    for item in _load_links():
        hosted_url = _normalize_payment_link(item.get("hosted_instructions_url"))
        if hosted_url == target:
            return str(item.get("account_email") or "").strip()
    return ""


def _mark_payment_success_account(job_id: str, message: str = "PIX CDK payment succeeded") -> dict[str, Any]:
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
    updated = _mark_account_plus_pix(email, message)
    result = {
        "email": email,
        "account_type": str(updated.get("account_type") or ""),
        "last_bind_provider": str(updated.get("last_bind_provider") or ""),
    }
    with PAYMENT_JOBS_LOCK:
        if job_id in PAYMENT_JOBS:
            PAYMENT_JOBS[job_id]["account_email"] = email
            PAYMENT_JOBS[job_id]["account_marked"] = True
            PAYMENT_JOBS[job_id]["account_update"] = result
    return result


def _is_job_cancel_requested(job_id: str) -> bool:
    with JOBS_LOCK:
        return bool((JOBS.get(job_id) or {}).get("cancel_requested"))


def _set_job_running_delta(job_id: str, delta: int) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        job["running_count"] = max(0, int(job.get("running_count") or 0) + delta)


def _is_already_paid_error(error: Any) -> bool:
    return "user is already paid" in str(error or "").lower()


def _is_token_invalidated_error(error: Any) -> bool:
    text = str(error or "").lower()
    return ("401" in text or "status\": 401" in text or "status 401" in text) and (
        "token_invalidated" in text
        or "token_revoked" in text
        or "authentication token has been invalidated" in text
        or "invalidated oauth token" in text
    )


def _is_no_organization_error(error: Any) -> bool:
    text = str(error or "").lower()
    return "no_organization" in text or "must be a member of an organization" in text


def _is_non_zero_after_promo_error(error: Any) -> bool:
    text = str(error or "").lower()
    return ("promo" in text or "套 promo" in text or "套promo" in text) and (
        "金额不是 0" in text or "amount is not 0" in text or "amount not 0" in text
    )


def _mark_account_plus_pix(email: str, message: str = "User is already paid") -> dict[str, Any]:
    account_store.ensure_session_only_account(email)
    updated = account_store.update_account(
        email,
        account_type=account_store.ACCOUNT_TYPE_PLUS,
        last_bind_provider="pix",
        last_bind_status="success",
        last_bind_at=time.time(),
        plus_bound_at=time.time(),
        last_bind_message=message,
        last_bind_failure_stage="",
    )
    return updated or {}


def _delete_invalid_account(email: str) -> dict[str, Any]:
    return {
        "record_deleted": bool(account_store.delete_account(email)),
        "auth_session_deleted": bool(delete_auth_session(email)),
    }


def _run_job(job_id: str, req: BrazilPixStartRequest) -> None:
    def log(message: str) -> None:
        _append_log(job_id, message)

    try:
        token = _extract_token(req.access_token)
        account_email = str(req.account_email or "").strip()
        if not token and account_email:
            token = _load_token_for_email(account_email)
        if not token:
            raise RuntimeError("缺少 Access Token 或账号池账号")
        proxies = _parse_proxies(req.proxies)
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "running"
            JOBS[job_id]["account_email"] = account_email
        cfg = PixJobConfig(
            access_token=token,
            local_proxy=str(req.local_proxy or "").strip(),
            kookeey_user=str(req.kookeey_user or "").strip(),
            kookeey_pass=str(req.kookeey_pass or ""),
            kookeey_endpoint=str(req.kookeey_endpoint or "gate.kookeey.info:1000").strip(),
            region=(req.region or "BR").strip().upper() or "BR",
            direct_proxies=proxies,
        )
        cfg = _preflight_pix_proxy_or_raise(cfg, log)
        result = generate_pix_trial(cfg, log=log)
        result["account_email"] = account_email
        link_record = _link_record_from_result(job_id, account_email, result)
        _append_link(link_record)
        result["link_record"] = link_record
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "success"
            JOBS[job_id]["result"] = result
            JOBS[job_id]["finished_at"] = time.time()
        log("任务完成")
    except Exception as exc:
        error = str(exc)
        if account_email and _is_token_invalidated_error(error):
            cleanup = _delete_invalid_account(account_email)
            error = f"账号已失效，已从账号池删除：{error}"
            _set_account_status(account_email, ACCOUNT_STATUS_FAILED, error=error, job_id=job_id)
            _append_log(job_id, f"账号 token 已失效，已从账号池删除：{account_email} cleanup={cleanup}")
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error"] = error
            JOBS[job_id]["finished_at"] = time.time()
        _append_log(job_id, f"失败: {error}")


def _select_batch_accounts(req: BrazilPixBatchStartRequest) -> list[dict[str, Any]]:
    available = _iter_auth_accounts()
    by_email = {item["email"].lower(): item for item in available}
    requested = [email.strip() for email in req.account_emails if str(email or "").strip()]
    if requested:
        selected = [by_email[email.lower()] for email in requested if email.lower() in by_email]
    else:
        selected = available
    max_accounts = int(req.max_accounts or 0)
    if max_accounts > 0:
        selected = selected[:max_accounts]
    return selected


def _batch_concurrency(req: BrazilPixBatchStartRequest, total: int) -> int:
    try:
        requested = int(req.concurrency or 1)
    except Exception:
        requested = 1
    return max(1, min(MAX_BATCH_CONCURRENCY, total, requested))


def _account_attempt_limit(req: BrazilPixBatchStartRequest) -> int:
    try:
        attempts = int(req.max_attempts or MAX_ACCOUNT_ATTEMPTS)
    except Exception:
        attempts = MAX_ACCOUNT_ATTEMPTS
    return max(1, min(MAX_CONFIGURABLE_ACCOUNT_ATTEMPTS, attempts))


def _preflight_pix_proxy_or_raise(cfg: PixJobConfig, log) -> PixJobConfig:
    if not cfg.direct_proxies and (not cfg.kookeey_user or not cfg.kookeey_pass):
        return cfg
    errors: list[str] = []
    for stage_index in range(PROXY_PREFLIGHT_MAX_ATTEMPTS):
        proxy_url, sid_label = build_pix_dynamic_proxy(cfg, stage_index)
        if not proxy_url:
            continue
        log(f"代理预检开始：{stage_index + 1}/{PROXY_PREFLIGHT_MAX_ATTEMPTS} {sid_label}")
        ok, message = proxy_runtime.preflight_payment_proxy_url(proxy_url)
        if ok:
            log(f"代理预检通过：{message}")
            return replace(cfg, direct_proxies=[proxy_url])
        errors.append(str(message or "unknown"))
        log(f"代理预检失败：{message}")
    raise RuntimeError(f"代理预检失败: {'; '.join(errors[-PROXY_PREFLIGHT_MAX_ATTEMPTS:])}")


def _temp_batch_concurrency(req: BrazilPixTempBatchStartRequest, total: int) -> int:
    try:
        requested = int(req.concurrency or 5)
    except Exception:
        requested = 5
    return max(1, min(total, requested))


def _requested_temp_concurrency(req: BrazilPixTempBatchStartRequest) -> int:
    try:
        return max(1, int(req.concurrency or 5))
    except Exception:
        return 5


def _temp_cdks(req: BrazilPixTempBatchStartRequest) -> list[str]:
    values: list[str] = []
    for value in req.cdks or []:
        text = str(value or "").strip()
        if text:
            values.append(text)
    single = str(req.cdk or "").strip()
    if single:
        values.append(single)
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _rotate_proxies_for_account(proxies: list[str], account_index: int) -> list[str]:
    if not proxies:
        return []
    offset = (max(1, account_index) - 1) % len(proxies)
    return proxies[offset:] + proxies[:offset]


def _run_batch_account(
    job_id: str,
    req: BrazilPixBatchStartRequest,
    account: dict[str, Any],
    index: int,
    total: int,
    proxies: list[str],
) -> dict[str, Any]:
    email = account["email"]
    started = time.monotonic()
    if _is_job_cancel_requested(job_id):
        _append_log(job_id, f"[{index}/{total}] 跳过账号：{email}（任务已取消）")
        return {"skipped": True, "email": email, "status": _set_account_status(email, ACCOUNT_STATUS_PENDING, job_id=job_id)}
    proxy_slot = f" proxy槽={(index - 1) % len(proxies) + 1}/{len(proxies)}" if proxies else ""
    _set_job_running_delta(job_id, 1)
    _append_log(job_id, f"[{index}/{total}] 开始账号：{email}{proxy_slot}")

    def account_log(message: str) -> None:
        _append_log(job_id, f"[{index}/{total}] {message}")

    attempts = 0
    try:
        _set_account_status(email, ACCOUNT_STATUS_RUNNING, job_id=job_id)
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
            cfg = PixJobConfig(
                access_token=token,
                local_proxy=str(req.local_proxy or "").strip(),
                kookeey_user=str(req.kookeey_user or "").strip(),
                kookeey_pass=str(req.kookeey_pass or ""),
                kookeey_endpoint=str(req.kookeey_endpoint or "gate.kookeey.info:1000").strip(),
                region=(req.region or "BR").strip().upper() or "BR",
                direct_proxies=attempt_proxies,
            )
            try:
                cfg = _preflight_pix_proxy_or_raise(cfg, account_log)
                result = generate_pix_trial(cfg, log=account_log)
                if attempt > 1:
                    _append_log(job_id, f"[{index}/{total}] 重试成功：{email} attempt={attempt}")
                break
            except Exception as exc:
                last_error = str(exc)
                if last_error.startswith("代理预检失败"):
                    status = _set_account_status(email, ACCOUNT_STATUS_FAILED, error=last_error, job_id=job_id)
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
                if _is_already_paid_error(last_error):
                    _mark_account_plus_pix(email, last_error)
                    status = _set_account_status(email, ACCOUNT_STATUS_SUCCESS, error=last_error, job_id=job_id)
                    _append_log(job_id, f"[{index}/{total}] 账号已是 Plus：{email}，已更新账号类型=Plus 绑定渠道=Pix")
                    return {
                        "skipped": True,
                        "email": email,
                        "reason": "账号已是 Plus，已标记绑定渠道 Pix",
                        "status": status,
                        "account_updated": True,
                    }
                if _is_token_invalidated_error(last_error):
                    cleanup = _delete_invalid_account(email)
                    status = _set_account_status(email, ACCOUNT_STATUS_FAILED, error=last_error, job_id=job_id)
                    _append_log(job_id, f"[{index}/{total}] 账号 token 已失效，已从账号池删除：{email} cleanup={cleanup}")
                    return {
                        "ok": False,
                        "email": email,
                        "error": {
                            "email": email,
                            "elapsed_s": round(time.monotonic() - started, 1),
                            "attempts": attempt,
                            "error": f"账号已失效，已从账号池删除：{last_error}",
                            "cleanup": cleanup,
                        },
                        "status": status,
                        "account_deleted": True,
                    }
                if _is_no_organization_error(last_error):
                    cleanup = _delete_invalid_account(email)
                    status = _set_account_status(email, ACCOUNT_STATUS_FAILED, error=last_error, job_id=job_id)
                    _append_log(
                        job_id,
                        f"[{index}/{total}] 账号缺少 Platform organization，注册未完整完成，已从账号池删除：{email} cleanup={cleanup}",
                    )
                    return {
                        "ok": False,
                        "email": email,
                        "error": {
                            "email": email,
                            "elapsed_s": round(time.monotonic() - started, 1),
                            "attempts": attempt,
                            "error": f"账号缺少 Platform organization，已从账号池删除：{last_error}",
                            "cleanup": cleanup,
                        },
                        "status": status,
                        "account_deleted": True,
                    }
                if _is_non_zero_after_promo_error(last_error):
                    cleanup = _delete_invalid_account(email)
                    status = _set_account_status(email, ACCOUNT_STATUS_FAILED, error=last_error, job_id=job_id)
                    _append_log(job_id, f"[{index}/{total}] 账号套 promo 后金额非 0，已从账号池删除：{email} cleanup={cleanup}")
                    return {
                        "ok": False,
                        "email": email,
                        "error": {
                            "email": email,
                            "elapsed_s": round(time.monotonic() - started, 1),
                            "attempts": attempt,
                            "error": f"套 promo 后金额非 0，已从账号池删除：{last_error}",
                            "cleanup": cleanup,
                        },
                        "status": status,
                        "account_deleted": True,
                    }
                _append_log(job_id, f"[{index}/{total}] 第 {attempt}/{max_attempts} 次失败：{email} {last_error}")
                if attempt >= max_attempts:
                    raise
                time.sleep(min(2.0, 0.5 * attempt))
        if result is None:
            raise RuntimeError(last_error or "提链失败")
        result["account_email"] = email
        record = _link_record_from_result(job_id, email, result)
        _append_link(record)
        compact = {
            "email": email,
            "elapsed_s": round(time.monotonic() - started, 1),
            "attempts": attempts,
            "link": record,
        }
        status = _set_account_status(email, ACCOUNT_STATUS_SUCCESS, job_id=job_id)
        _append_log(job_id, f"[{index}/{total}] 成功：{email} attempts={attempts} cs_id={record.get('cs_id')}")
        return {"ok": True, "email": email, "success": compact, "status": status}
    except Exception as exc:
        error = str(exc)
        item = {"email": email, "elapsed_s": round(time.monotonic() - started, 1), "attempts": attempts or 1, "error": error}
        status = _set_account_status(email, ACCOUNT_STATUS_FAILED, error=error, job_id=job_id)
        _append_log(job_id, f"[{index}/{total}] 最终失败：{email} attempts={attempts or 1} {exc}")
        return {"ok": False, "email": email, "error": item, "status": status}
    finally:
        _set_job_running_delta(job_id, -1)


def _temp_external_json(resp: requests.Response) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError(f"临时提链服务返回非 JSON: HTTP {resp.status_code} {resp.text[:300]}") from None
    if not isinstance(data, dict):
        raise RuntimeError(f"临时提链服务响应格式错误: {str(data)[:300]}")
    if not resp.ok:
        message = data.get("message") or data.get("error") or data.get("detail") or f"HTTP {resp.status_code}"
        raise RuntimeError(f"临时提链服务拒绝请求: {message}")
    return data


def _temp_nested_job(data: dict[str, Any]) -> dict[str, Any]:
    job = data.get("job") if isinstance(data.get("job"), dict) else {}
    return job or data


def _temp_sources(data: dict[str, Any]) -> list[dict[str, Any]]:
    job = _temp_nested_job(data)
    job_result = job.get("result") if isinstance(job.get("result"), dict) else {}
    data_result = data.get("result") if isinstance(data.get("result"), dict) else {}
    sources: list[dict[str, Any]] = []
    for source in (job_result, job, data_result, data):
        if isinstance(source, dict) and source not in sources:
            sources.append(source)
    return sources


def _temp_field(data: dict[str, Any], *names: str) -> str:
    for source in _temp_sources(data):
        for name in names:
            value = source.get(name) if isinstance(source, dict) else None
            if str(value or "").strip():
                return str(value).strip()
    return ""


def _temp_status(data: dict[str, Any]) -> str:
    return _temp_field(data, "status", "state").strip().lower()


def _temp_success_result(account_email: str, remote_job_id: str, data: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "amount": _temp_field(data, "amount", "expected_amount") or "0",
        "cs_id": _temp_field(data, "cs_id", "checkout_session_id", "checkoutSessionId"),
        "pix_copy_paste": _temp_field(data, "pix_copy_paste", "pixCopyPaste", "copy_paste", "qr_code", "qrCode"),
        "hosted_instructions_url": _temp_field(
            data,
            "hosted_instructions_url",
            "hostedInstructionsUrl",
            "pix_hosted_instructions_url",
            "pixHostedInstructionsUrl",
            "link",
            "url",
            "payment_link",
            "paymentLink",
        ),
        "image_url_png": _temp_field(data, "image_url_png", "imageUrlPng", "pix_image_url_png", "pixImageUrlPng", "qr_image", "qrImage"),
        "image_url_svg": _temp_field(data, "image_url_svg", "imageUrlSvg", "pix_image_url_svg", "pixImageUrlSvg"),
        "chatgpt_checkout_url": _temp_field(data, "chatgpt_checkout_url", "chatgptCheckoutUrl"),
    }
    if not fields["hosted_instructions_url"] and not fields["pix_copy_paste"]:
        raise RuntimeError(f"临时提链成功但未返回 PIX 链接或复制码: remote_job={remote_job_id}")
    return {
        "ok": True,
        "account_email": account_email,
        "amount": fields["amount"],
        "fields": fields,
        "remote_job_id": remote_job_id,
    }


def _temp_cdk_cache_key(cdk: str) -> str:
    return str(cdk or "").strip().lower()


def _get_temp_cdk_status_cache(cdk: str, *, allow_stale: bool = False) -> dict[str, Any] | None:
    key = _temp_cdk_cache_key(cdk)
    if not key:
        return None
    now = time.time()
    max_age = TEMP_CDK_STATUS_STALE_TTL_S if allow_stale else TEMP_CDK_STATUS_CACHE_TTL_S
    with TEMP_CDK_STATUS_CACHE_LOCK:
        item = TEMP_CDK_STATUS_CACHE.get(key)
        if not item:
            return None
        age = now - float(item.get("ts") or 0)
        if age < 0 or age > max_age:
            return None
        data = item.get("data")
        if not isinstance(data, dict):
            return None
        result = dict(data)
        result["cached"] = True
        result["stale"] = age > TEMP_CDK_STATUS_CACHE_TTL_S
        result["cache_age_s"] = round(age, 1)
        return result


def _set_temp_cdk_status_cache(cdk: str, data: dict[str, Any]) -> None:
    key = _temp_cdk_cache_key(cdk)
    if not key:
        return
    clean = dict(data)
    clean.pop("cached", None)
    clean.pop("stale", None)
    clean.pop("cache_age_s", None)
    clean.pop("upstream_error", None)
    with TEMP_CDK_STATUS_CACHE_LOCK:
        TEMP_CDK_STATUS_CACHE[key] = {"ts": time.time(), "data": clean}


def _wait_temp_cdk_status_rate_limit() -> None:
    global TEMP_CDK_STATUS_LAST_REQUEST_AT
    with TEMP_CDK_STATUS_RATE_LOCK:
        now = time.monotonic()
        wait_s = TEMP_CDK_STATUS_LAST_REQUEST_AT + TEMP_CDK_STATUS_MIN_INTERVAL_S - now
        if wait_s > 0:
            time.sleep(wait_s)
        TEMP_CDK_STATUS_LAST_REQUEST_AT = time.monotonic()


def _temp_cdk_status_data(cdk: str, *, force: bool = False) -> dict[str, Any]:
    if not force:
        cached = _get_temp_cdk_status_cache(cdk)
        if cached is not None:
            return cached
    try:
        _wait_temp_cdk_status_rate_limit()
        resp = requests.post(
            f"{TEMP_PIX_CDK_API_BASE}/cdk/status",
            json={"cdk": cdk},
            headers={"Content-Type": "application/json"},
            timeout=20,
        )
    except requests.RequestException as exc:
        cached = _get_temp_cdk_status_cache(cdk, allow_stale=True)
        if cached is not None:
            cached["stale"] = True
            cached["upstream_error"] = str(exc)
            return cached
        raise RuntimeError(f"临时 CDK 余额查询失败: {exc}") from exc
    try:
        data = resp.json()
    except ValueError:
        cached = _get_temp_cdk_status_cache(cdk, allow_stale=True)
        if cached is not None:
            cached["stale"] = True
            cached["upstream_error"] = f"HTTP {resp.status_code} non-json"
            return cached
        raise RuntimeError(f"临时 CDK 余额服务返回非 JSON: HTTP {resp.status_code} {resp.text[:300]}") from None
    if not isinstance(data, dict):
        cached = _get_temp_cdk_status_cache(cdk, allow_stale=True)
        if cached is not None:
            cached["stale"] = True
            cached["upstream_error"] = f"bad response: {str(data)[:120]}"
            return cached
        raise RuntimeError(f"临时 CDK 余额服务响应格式错误: {str(data)[:300]}")
    if not resp.ok:
        cached = _get_temp_cdk_status_cache(cdk, allow_stale=True)
        if cached is not None:
            cached["stale"] = True
            cached["upstream_error"] = data.get("message") or data.get("error") or f"HTTP {resp.status_code}"
            return cached
        message = data.get("message") or data.get("error") or data.get("detail") or f"HTTP {resp.status_code}"
        raise RuntimeError(f"临时 CDK 余额服务拒绝请求: {message}")
    _set_temp_cdk_status_cache(cdk, data)
    return data


def _temp_cdk_balance_from_status(data: dict[str, Any]) -> int | None:
    if data.get("ok") is False:
        return 0
    sources: list[dict[str, Any]] = []
    for value in (
        data.get("cdk"),
        data.get("data"),
        data.get("result"),
        data,
    ):
        if isinstance(value, dict) and value not in sources:
            sources.append(value)
    for source in sources:
        valid = source.get("valid")
        state = str(source.get("state") or source.get("status") or "").strip().lower()
        if valid is False or state in {"invalid", "disabled", "expired", "blocked"}:
            return 0
        for name in ("balance", "remaining", "quota_remaining", "quotaRemaining", "available"):
            if name not in source:
                continue
            try:
                return max(0, int(float(str(source.get(name)).strip())))
            except Exception:
                continue
    return None


def _temp_cdk_balance(cdk: str) -> int | None:
    data = _temp_cdk_status_data(cdk)
    return _temp_cdk_balance_from_status(data)


def _temp_cdk_assignments(cdks: list[str], total_accounts: int, log=None) -> list[str]:
    if total_accounts <= 0 or not cdks:
        return []
    if len(cdks) == 1:
        return [cdks[0]] * total_accounts

    expanded: list[str] = []
    known_balances: list[tuple[str, int]] = []
    unknown_cdks: list[str] = []
    for cdk in cdks:
        try:
            balance = _temp_cdk_balance(cdk)
        except Exception as exc:
            balance = None
            if callable(log):
                log(f"CDK 余额查询失败，暂按备用轮询处理：{cdk[:8]}... {exc}")
        if balance is None:
            unknown_cdks.append(cdk)
            continue
        known_balances.append((cdk, balance))
        if balance > 0:
            expanded.extend([cdk] * balance)
            if len(expanded) >= total_accounts:
                break

    if expanded:
        assignments = expanded[:total_accounts]
        if len(assignments) < total_accounts:
            fallback_cdks = [cdk for cdk, balance in known_balances if balance > 0] or unknown_cdks or cdks
            if callable(log):
                log(f"CDK 已知余额 {len(expanded)} 小于账号数 {total_accounts}，剩余账号按 CDK 池轮询补齐")
            while len(assignments) < total_accounts:
                assignments.append(fallback_cdks[(len(assignments) - len(expanded)) % len(fallback_cdks)])
        if callable(log):
            positive = sum(1 for _, balance in known_balances if balance > 0)
            log(f"CDK 余额分配完成：已查询 {len(known_balances)}/{len(cdks)} 个，余额可用 CDK {positive} 个，总额度 {len(expanded)}")
        return assignments

    if callable(log):
        log("CDK 余额未查到可用额度，回退为按 CDK 列表轮询分配")
    return [cdks[index % len(cdks)] for index in range(total_accounts)]


def _create_temp_external_job(credential: str, cdk: str) -> tuple[str, str, dict[str, Any]]:
    try:
        resp = requests.post(
            f"{TEMP_PIX_CDK_API_BASE}/jobs",
            json={"credential": credential, "cdk": cdk},
            headers={"Content-Type": "application/json"},
            timeout=70,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"临时提链服务请求失败: {exc}") from exc
    data = _temp_external_json(resp)
    remote_job_id = _temp_field(data, "job_id", "jobId", "id")
    job_token = _temp_field(data, "job_token", "jobToken", "token", "status_token", "statusToken")
    if not remote_job_id:
        raise RuntimeError(f"临时提链服务未返回 job_id: {str(data)[:300]}")
    if not job_token:
        raise RuntimeError(f"临时提链服务未返回 job_token: {str(data)[:300]}")
    return remote_job_id, job_token, data


def _poll_temp_external_job(remote_job_id: str, job_token: str, *, cancel_check=None) -> dict[str, Any]:
    terminal_success = {"succeeded", "success", "completed", "done"}
    terminal_failed = {"failed", "error", "cancelled", "canceled", "interrupted"}
    last_data: dict[str, Any] = {}
    for _ in range(90):
        if callable(cancel_check) and cancel_check():
            raise RuntimeError("任务已取消")
        try:
            resp = requests.get(
                f"{TEMP_PIX_CDK_API_BASE}/jobs/{remote_job_id}",
                headers={"Authorization": f"Bearer {job_token}"},
                timeout=20,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"临时提链服务查询失败: {exc}") from exc
        data = _temp_external_json(resp)
        last_data = data
        status = _temp_status(data)
        if status in terminal_success:
            return data
        if status in terminal_failed:
            message = _temp_field(data, "message", "error", "error_message", "errorMessage") or status
            raise RuntimeError(f"临时提链失败: {message}")
        time.sleep(2.0)
    raise RuntimeError(f"临时提链轮询超时: {str(last_data)[:300]}")


def _delete_temp_external_job(remote_job_id: str, job_token: str) -> None:
    if not remote_job_id or not job_token:
        return
    try:
        requests.delete(
            f"{TEMP_PIX_CDK_API_BASE}/jobs/{remote_job_id}",
            headers={"Authorization": f"Bearer {job_token}"},
            timeout=20,
        )
    except Exception:
        pass


def _run_temp_batch_account(
    job_id: str,
    req: BrazilPixTempBatchStartRequest,
    account: dict[str, Any],
    cdk: str,
    index: int,
    total: int,
) -> dict[str, Any]:
    email = account["email"]
    started = time.monotonic()
    if _is_job_cancel_requested(job_id):
        _append_log(job_id, f"[{index}/{total}] 跳过账号：{email}（任务已取消）")
        return {"skipped": True, "email": email, "status": _set_account_status(email, ACCOUNT_STATUS_PENDING, job_id=job_id)}
    _set_job_running_delta(job_id, 1)
    _append_log(job_id, f"[{index}/{total}] 临时提链开始账号：{email}")
    try:
        _set_account_status(email, ACCOUNT_STATUS_RUNNING, job_id=job_id)
        token = _load_token_for_email(email)
        if not token:
            raise RuntimeError("账号缺少有效 accessToken")
        cdk = str(cdk or "").strip()
        if not cdk:
            raise RuntimeError("临时提链缺少 CDK")
        remote_job_id, job_token, created = _create_temp_external_job(token, cdk)
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if job is not None:
                external_jobs = job.setdefault("external_jobs", {})
                external_jobs[email] = {"job_id": remote_job_id, "job_token": job_token}
        _append_log(job_id, f"[{index}/{total}] 已提交 olimap 临时提链任务：{remote_job_id}")
        if _temp_status(created) in {"succeeded", "success", "completed", "done"}:
            data = created
        else:
            data = _poll_temp_external_job(remote_job_id, job_token, cancel_check=lambda: _is_job_cancel_requested(job_id))
        result = _temp_success_result(email, remote_job_id, data)
        record = _link_record_from_result(job_id, email, result)
        _append_link(record)
        status = _set_account_status(email, ACCOUNT_STATUS_SUCCESS, job_id=job_id)
        compact = {
            "email": email,
            "elapsed_s": round(time.monotonic() - started, 1),
            "attempts": 1,
            "link": record,
            "remote_job_id": remote_job_id,
        }
        _append_log(job_id, f"[{index}/{total}] 临时提链成功：{email} remote_job={remote_job_id}")
        return {"ok": True, "email": email, "success": compact, "status": status}
    except Exception as exc:
        error = str(exc)
        item = {"email": email, "elapsed_s": round(time.monotonic() - started, 1), "attempts": 1, "error": error}
        status = _set_account_status(email, ACCOUNT_STATUS_FAILED, error=error, job_id=job_id)
        _append_log(job_id, f"[{index}/{total}] 临时提链失败：{email} {error}")
        return {"ok": False, "email": email, "error": item, "status": status}
    finally:
        _set_job_running_delta(job_id, -1)


def _run_temp_batch_job(job_id: str, req: BrazilPixTempBatchStartRequest) -> None:
    def log(message: str) -> None:
        _append_log(job_id, message)

    try:
        accounts = _select_batch_accounts(
            BrazilPixBatchStartRequest(accountEmails=req.account_emails, maxAccounts=req.max_accounts, concurrency=req.concurrency)
        )
        if not accounts:
            raise RuntimeError("没有可用账号，请先选择账号池账号或刷新账号池")
        cdks = _temp_cdks(req)
        if not cdks:
            raise RuntimeError("请填写临时提链 CDK")
        concurrency = _temp_batch_concurrency(req, len(accounts))
        successes: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        account_statuses: dict[str, dict[str, Any]] = {}
        for account in accounts:
            email = account["email"]
            account_statuses[email] = _set_account_status(email, ACCOUNT_STATUS_PENDING, job_id=job_id)
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "running"
            JOBS[job_id]["total"] = len(accounts)
            JOBS[job_id]["completed"] = 0
            JOBS[job_id]["concurrency"] = concurrency
            JOBS[job_id]["running_count"] = 0
            JOBS[job_id]["cancel_requested"] = False
            JOBS[job_id]["skipped"] = []
            JOBS[job_id]["account_statuses"] = account_statuses
            JOBS[job_id]["temp"] = True
            JOBS[job_id]["external_jobs"] = {}
        log(f"临时提链任务开始：{len(accounts)} 个账号，并发 {concurrency}")
        completed = 0
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            cdk_assignments = _temp_cdk_assignments(cdks, len(accounts), log)
            futures = [
                executor.submit(_run_temp_batch_account, job_id, req, account, cdk_assignments[index - 1], index, len(accounts))
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
        log(f"临时提链任务完成：成功 {len(successes)}，失败 {len(errors)}，跳过 {len(skipped)}")
    except Exception as exc:
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error"] = str(exc)
            JOBS[job_id]["finished_at"] = time.time()
        _append_log(job_id, f"失败: {exc}")


def _run_batch_job(job_id: str, req: BrazilPixBatchStartRequest) -> None:
    def log(message: str) -> None:
        _append_log(job_id, message)

    try:
        accounts = _select_batch_accounts(req)
        if not accounts:
            raise RuntimeError("没有可用账号，请先选择账号池账号或刷新账号池")
        proxies = _parse_proxies(req.proxies)
        if not proxies and (not req.kookeey_user or not req.kookeey_pass):
            raise RuntimeError("请填写 BR 代理列表，或填写 Kookeey 用户名/密码")
        concurrency = _batch_concurrency(req, len(accounts))
        successes: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        account_statuses: dict[str, dict[str, Any]] = {}
        for account in accounts:
            email = account["email"]
            account_statuses[email] = _set_account_status(email, ACCOUNT_STATUS_PENDING, job_id=job_id)
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "running"
            JOBS[job_id]["total"] = len(accounts)
            JOBS[job_id]["completed"] = 0
            JOBS[job_id]["concurrency"] = concurrency
            JOBS[job_id]["running_count"] = 0
            JOBS[job_id]["cancel_requested"] = False
            JOBS[job_id]["skipped"] = []
            JOBS[job_id]["account_statuses"] = account_statuses
        log(f"提链任务开始：{len(accounts)} 个账号，并发 {concurrency}")
        completed = 0
        skipped: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [
                executor.submit(
                    _run_batch_account,
                    job_id,
                    req,
                    account,
                    index,
                    len(accounts),
                    _rotate_proxies_for_account(proxies, index),
                )
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
        log(f"提链任务完成：成功 {len(successes)}，失败 {len(errors)}，跳过 {len(skipped)}")
    except Exception as exc:
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error"] = str(exc)
            JOBS[job_id]["finished_at"] = time.time()
        _append_log(job_id, f"失败: {exc}")


def create_brazil_pix_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/brazil-pix/accounts")
    def get_brazil_pix_accounts() -> dict[str, Any]:
        return {"accounts": _iter_auth_accounts_with_pix_status()}

    @router.delete("/api/brazil-pix/accounts/{email}")
    def delete_brazil_pix_account(email: str) -> dict[str, Any]:
        clean_email = str(email or "").strip()
        if not clean_email:
            raise HTTPException(status_code=400, detail="email required")
        return _delete_brazil_pix_account_everywhere(clean_email)

    @router.post("/api/brazil-pix/accounts/delete")
    def delete_brazil_pix_accounts(req: BrazilPixDeleteAccountsRequest) -> dict[str, Any]:
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
        results = [_delete_brazil_pix_account_everywhere(email) for email in emails]
        return {"ok": True, "deleted": len(results), "results": results}

    @router.post("/api/brazil-pix/start")
    def start_brazil_pix(req: BrazilPixStartRequest) -> dict[str, str]:
        job_id = uuid.uuid4().hex[:12]
        with JOBS_LOCK:
            JOBS[job_id] = {
                "id": job_id,
                "status": "queued",
                "logs": [],
                "result": None,
                "error": None,
                "created_at": time.time(),
                "finished_at": None,
                "account_email": str(req.account_email or "").strip(),
                "account_statuses": {},
                "cancel_requested": False,
                "running_count": 0,
            }
        thread = threading.Thread(target=_run_job, args=(job_id, req), daemon=True)
        thread.start()
        return {"job_id": job_id}

    @router.post("/api/brazil-pix/batch/start")
    def start_brazil_pix_batch(req: BrazilPixBatchStartRequest) -> dict[str, str]:
        job_id = uuid.uuid4().hex[:12]
        with JOBS_LOCK:
            JOBS[job_id] = {
                "id": job_id,
                "status": "queued",
                "logs": [],
                "result": None,
                "error": None,
                "created_at": time.time(),
                "finished_at": None,
                "account_email": "",
                "total": 0,
                "completed": 0,
                "concurrency": max(1, min(MAX_BATCH_CONCURRENCY, int(req.concurrency or 1))),
                "cancel_requested": False,
                "running_count": 0,
                "skipped": [],
                "account_statuses": {},
            }
        thread = threading.Thread(target=_run_batch_job, args=(job_id, req), daemon=True)
        thread.start()
        return {"job_id": job_id}

    @router.post("/api/brazil-pix/temp/batch/start")
    def start_brazil_pix_temp_batch(req: BrazilPixTempBatchStartRequest) -> dict[str, str]:
        if not _temp_cdks(req):
            raise HTTPException(status_code=400, detail="请填写临时提链 CDK")
        job_id = uuid.uuid4().hex[:12]
        with JOBS_LOCK:
            JOBS[job_id] = {
                "id": job_id,
                "status": "queued",
                "logs": [],
                "result": None,
                "error": None,
                "created_at": time.time(),
                "finished_at": None,
                "account_email": "",
                "total": 0,
                "completed": 0,
                "concurrency": _requested_temp_concurrency(req),
                "cancel_requested": False,
                "running_count": 0,
                "skipped": [],
                "account_statuses": {},
                "temp": True,
                "external_jobs": {},
            }
        thread = threading.Thread(target=_run_temp_batch_job, args=(job_id, req), daemon=True)
        thread.start()
        return {"job_id": job_id}

    @router.post("/api/brazil-pix/temp/cdk/status")
    def get_brazil_pix_temp_cdk_status(req: BrazilPixTempCdkStatusRequest) -> dict[str, Any]:
        cdk = str(req.cdk or "").strip()
        if not cdk:
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "CDK 不能为空"})
        try:
            return _temp_cdk_status_data(cdk, force=bool(req.force))
        except RuntimeError as exc:
            raise HTTPException(
                status_code=502,
                detail={"ok": False, "code": "temp_cdk_api_unreachable", "message": str(exc)},
            ) from exc

    @router.post("/api/brazil-pix/jobs/{job_id}/cancel")
    def cancel_brazil_pix_job(job_id: str) -> dict[str, Any]:
        should_log = False
        external_jobs: dict[str, dict[str, Any]] = {}
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="job not found")
            if job.get("status") in {"success", "error", "cancelled"}:
                return {"ok": True, "job_id": job_id, "status": job.get("status"), "cancel_requested": bool(job.get("cancel_requested"))}
            job["cancel_requested"] = True
            if job.get("status") in {"queued", "running"}:
                job["status"] = "cancelling"
            external_jobs = dict(job.get("external_jobs") or {}) if job.get("temp") else {}
            should_log = True
        for external in external_jobs.values():
            if isinstance(external, dict):
                _delete_temp_external_job(str(external.get("job_id") or ""), str(external.get("job_token") or ""))
        if should_log:
            _append_log(job_id, "收到取消请求：正在停止未开始的账号，已运行账号会跑到当前步骤结束")
        return {"ok": True, "job_id": job_id, "status": "cancelling", "cancel_requested": True}

    @router.get("/api/brazil-pix/jobs/{job_id}")
    def get_brazil_pix_job(job_id: str) -> dict[str, Any]:
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="job not found")
            return {
                "id": job["id"],
                "status": job["status"],
                "logs": list(job["logs"]),
                "result": job["result"],
                "error": job["error"],
                "created_at": job["created_at"],
                "finished_at": job["finished_at"],
                "account_email": job.get("account_email") or "",
                "total": job.get("total") or 0,
                "completed": job.get("completed") or 0,
                "concurrency": job.get("concurrency") or 1,
                "running_count": job.get("running_count") or 0,
                "cancel_requested": bool(job.get("cancel_requested")),
                "skipped": job.get("skipped") or [],
                "account_statuses": job.get("account_statuses") or {},
            }

    @router.get("/api/brazil-pix/links")
    def get_brazil_pix_links() -> dict[str, Any]:
        links, pruned_deleted_accounts = _load_links_pruning_deleted_accounts()
        return {"links": links, "pruned_deleted_accounts": pruned_deleted_accounts}

    @router.post("/api/brazil-pix/links/delete")
    def delete_brazil_pix_links(req: BrazilPixDeleteLinksRequest) -> dict[str, Any]:
        ids = {str(item) for item in req.ids if str(item)}
        if not ids:
            return {"deleted": 0, "links": _load_links()}
        items = _load_links()
        kept = [item for item in items if str(item.get("id") or "") not in ids]
        _save_links(kept)
        return {"deleted": len(items) - len(kept), "links": kept}

    @router.post("/api/brazil-pix/links/clear")
    def clear_brazil_pix_links() -> dict[str, Any]:
        count = len(_load_links())
        _save_links([])
        return {"deleted": count, "links": []}

    @router.post("/api/brazil-pix/payment/submit")
    def submit_brazil_pix_payment(req: BrazilPixPaymentSubmitRequest | None = None) -> dict[str, Any]:
        req = req or BrazilPixPaymentSubmitRequest()
        cdk = str(req.cdk or "").strip()
        link = str(req.link or "").strip()
        if not cdk or not link:
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "CDK 和链接不能为空"})
        try:
            resp = requests.post(
                f"{PIX_CDK_API_BASE}/api/submit",
                json={"cdk": cdk, "link": link},
                headers={"Content-Type": "application/json"},
                timeout=70,
            )
        except requests.RequestException as exc:
            raise _payment_api_error(exc) from exc
        data = _payment_api_submit_json(resp)
        job_id = str(data.get("job_id") or "").strip()
        if job_id:
            with PAYMENT_JOBS_LOCK:
                PAYMENT_JOBS[job_id] = {
                    "job_id": job_id,
                    "status_token": str(data.get("status_token") or ""),
                    "link": link,
                    "cdk": cdk,
                    "account_email": _account_email_for_payment_link(link),
                    "account_marked": False,
                    "account_update": {},
                    "created_at": time.time(),
                }
        return data

    @router.get("/api/brazil-pix/payment/jobs/{job_id}")
    def get_brazil_pix_payment_job(job_id: str, token: str = Query("")) -> dict[str, Any]:
        clean_job_id = str(job_id or "").strip()
        clean_token = str(token or "").strip()
        if not clean_job_id or not clean_token:
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "job_id 和 token 不能为空"})
        try:
            resp = requests.get(
                f"{PIX_CDK_API_BASE}/api/jobs/{clean_job_id}",
                params={"token": clean_token},
                timeout=20,
            )
        except requests.RequestException as exc:
            raise _payment_api_error(exc) from exc
        data = _payment_api_json(resp)
        job = data.get("job") if isinstance(data.get("job"), dict) else {}
        if str(job.get("status") or "") == "succeeded":
            account_update = _mark_payment_success_account(clean_job_id, str(job.get("message") or "PIX CDK payment succeeded"))
            if account_update:
                job["account_email"] = account_update.get("email") or ""
                job["account_type"] = account_update.get("account_type") or ""
                job["last_bind_provider"] = account_update.get("last_bind_provider") or ""
                job["account_marked_plus"] = True
        return data

    return router
