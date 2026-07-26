"""iDEAL link extraction HTTP routes."""

from __future__ import annotations

import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from autotoken.api_routes import brazil_pix as pix_routes
from autotoken.core.paths import PROJECT_ROOT
from autotoken.integrations.gpthel_ideal import app as legacy
from autotoken.storage import accounts as account_store
from autotoken.storage.auth_session_store import delete_auth_session


IdealLongLinkRequest = legacy.LongLinkRequest
IdealQrRequest = legacy.QRCodeRequest
IdealProxyChainTestRequest = legacy.ProxyChainTestRequest

LINKS_FILE = PROJECT_ROOT / "data" / "ideal_links.json"
ACCOUNT_STATUS_FILE = PROJECT_ROOT / "data" / "ideal_account_status.json"
MAX_BATCH_CONCURRENCY = 20
MAX_ACCOUNT_ATTEMPTS = 5
MAX_CONFIGURABLE_ACCOUNT_ATTEMPTS = 20

IDEAL_STATUS_PENDING = "pending"
IDEAL_STATUS_RUNNING = "running"
IDEAL_STATUS_SUCCESS = "success"
IDEAL_STATUS_FAILED = "failed"
IDEAL_STATUS_PAID = "paid"
IDEAL_STATUS_TEXT = {
    IDEAL_STATUS_PENDING: "未提链",
    IDEAL_STATUS_RUNNING: "提链中",
    IDEAL_STATUS_SUCCESS: "已提链",
    IDEAL_STATUS_FAILED: "提链失败",
    IDEAL_STATUS_PAID: "已支付",
}
ACCOUNT_UI_FIELDS = (
    "email",
    "status",
    "account_type",
    "seat_type",
    "ttl_seconds",
    "expires_at",
    "last_active_at",
    "updated_at",
    "note",
)
JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.RLock()
LINKS_LOCK = threading.RLock()
ACCOUNT_STATUS_LOCK = threading.RLock()


class IdealBatchStartRequest(BaseModel):
    account_email: str = Field("", alias="accountEmail")
    account_emails: list[str] = Field(default_factory=list, alias="accountEmails")
    max_accounts: int | None = Field(None, alias="maxAccounts")
    proxies: str = ""
    proxy: str = ""
    concurrency: int = 1
    max_attempts: int = Field(MAX_ACCOUNT_ATTEMPTS, alias="maxAttempts")
    checkout_ui_mode: str = Field("hosted", alias="checkoutUiMode")
    payment_locale: str = Field("auto", alias="paymentLocale")
    stripe_publishable_key: str = Field("", alias="stripePublishableKey")
    device_id: str = Field("", alias="deviceId")
    client_fingerprint: str = Field("chrome", alias="clientFingerprint")
    user_agent: str = Field("", alias="userAgent")
    diagnostic_enabled: bool = Field(False, alias="diagnosticEnabled")
    proxy_chain_strategy: str = Field("", alias="proxyChainStrategy")
    checkout_proxy_region: str = Field("JP", alias="checkoutProxyRegion")
    provider_proxy_region: str = Field("NL", alias="providerProxyRegion")
    approve_proxy_region: str = Field("", alias="approveProxyRegion")
    proxy_preflight_attempts: int = Field(5, alias="proxyPreflightAttempts")
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
            attempts = int(value or 5)
        except Exception:
            attempts = 5
        return max(1, min(100, attempts))


class IdealDeleteLinksRequest(BaseModel):
    ids: list[str] = Field(default_factory=list)


class IdealDeleteAccountsRequest(BaseModel):
    emails: list[str] = Field(default_factory=list)


def _ideal_request(params: IdealLongLinkRequest) -> IdealLongLinkRequest:
    return params.model_copy(
        update={
            "link_type": "ideal",
            "billing_country": "NL",
            "payment_locale": params.payment_locale or "nl-NL",
            "checkout_ui_mode": params.checkout_ui_mode or "hosted",
        },
        deep=True,
    )


def _ideal_proxy_request(params: IdealProxyChainTestRequest) -> IdealProxyChainTestRequest:
    return params.model_copy(update={"link_type": "ideal"}, deep=True)


def _namespaced_diagnostic_url(snapshot: dict[str, Any]) -> dict[str, Any]:
    data = dict(snapshot or {})
    diagnostic_url = str(data.get("diagnostic_url") or "").strip()
    if diagnostic_url.startswith("/api/long-link/jobs/"):
        data["diagnostic_url"] = diagnostic_url.replace("/api/long-link/jobs/", "/api/ideal/long-link/jobs/", 1)
    return data


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_link(value: Any) -> str:
    return str(value or "").strip().rstrip("/")


def _load_links() -> list[dict[str, Any]]:
    with LINKS_LOCK:
        data = _read_json(LINKS_FILE, [])
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _dedupe_link_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_accounts: set[str] = set()
    seen_links: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        email = str(item.get("account_email") or "").strip().lower()
        link = _normalize_link(item.get("ideal_link") or item.get("long_url") or item.get("hosted_instructions_url"))
        if email:
            if email in seen_accounts:
                continue
            seen_accounts.add(email)
        elif link:
            if link in seen_links:
                continue
            seen_links.add(link)
        if link:
            seen_links.add(link)
        deduped.append(item)
    return deduped


def _save_links(items: list[dict[str, Any]]) -> None:
    with LINKS_LOCK:
        _write_json(LINKS_FILE, _dedupe_link_items(items)[:1000])


def _load_account_statuses() -> dict[str, dict[str, Any]]:
    with ACCOUNT_STATUS_LOCK:
        data = _read_json(ACCOUNT_STATUS_FILE, {})
        if not isinstance(data, dict):
            return {}
        return {str(key).lower(): value for key, value in data.items() if isinstance(value, dict)}


def _save_account_statuses(statuses: dict[str, dict[str, Any]]) -> None:
    with ACCOUNT_STATUS_LOCK:
        _write_json(ACCOUNT_STATUS_FILE, statuses)


def _set_account_status(email: str, status: str, *, error: str = "", job_id: str = "") -> dict[str, Any]:
    key = str(email or "").strip().lower()
    if not key:
        return {}
    normalized = str(status or IDEAL_STATUS_PENDING).strip().lower()
    if normalized not in IDEAL_STATUS_TEXT:
        normalized = IDEAL_STATUS_PENDING
    item = {
        "status": normalized,
        "status_text": IDEAL_STATUS_TEXT[normalized],
        "error": str(error or ""),
        "job_id": str(job_id or ""),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with ACCOUNT_STATUS_LOCK:
        statuses = _load_account_statuses()
        statuses[key] = item
        _save_account_statuses(statuses)
    return item


def _ideal_paid_emails() -> set[str]:
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
        ideal_bound = bind_provider == "ideal" and bind_status in {"success", "succeeded", "ok"}
        if account_type == account_store.ACCOUNT_TYPE_PLUS or status == account_store.STATUS_PLUS or ideal_bound:
            paid.add(email)
    return paid


def _iter_auth_accounts(*, include_paid: bool = False) -> list[dict[str, Any]]:
    accounts = pix_routes._iter_auth_accounts(include_paid=include_paid)
    if include_paid:
        return accounts
    paid = _ideal_paid_emails()
    return [item for item in accounts if str(item.get("email") or "").strip().lower() not in paid]


def _iter_auth_accounts_with_ideal_status() -> list[dict[str, Any]]:
    statuses = _load_account_statuses()
    paid_emails = _ideal_paid_emails()
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
            item = {"status": IDEAL_STATUS_PAID, "error": "", "updated_at": ""}
        elif not item and key in linked_emails:
            item = {"status": IDEAL_STATUS_SUCCESS, "error": "", "updated_at": ""}
        status = str(item.get("status") or IDEAL_STATUS_PENDING)
        if status not in IDEAL_STATUS_TEXT:
            status = IDEAL_STATUS_PENDING
        rows.append({
            field: (email if field == "email" else dashboard_account.get(field, account.get(field)))
            for field in ACCOUNT_UI_FIELDS
        } | {
            "ideal_status": status,
            "ideal_status_text": str(item.get("status_text") or IDEAL_STATUS_TEXT[status]),
            "ideal_error": str(item.get("error") or ""),
            "ideal_status_updated_at": item.get("updated_at"),
            "ideal_selectable": status != IDEAL_STATUS_PAID,
        })
    return rows


def _select_batch_accounts(req: IdealBatchStartRequest) -> list[dict[str, Any]]:
    available = _iter_auth_accounts()
    by_email = {str(item.get("email") or "").strip().lower(): item for item in available}
    requested = [str(email or "").strip() for email in req.account_emails if str(email or "").strip()]
    if req.account_email.strip() and req.account_email.strip().lower() not in {email.lower() for email in requested}:
        requested.insert(0, req.account_email.strip())
    selected = [by_email[email.lower()] for email in requested if email.lower() in by_email] if requested else available
    if req.max_accounts and req.max_accounts > 0:
        selected = selected[: int(req.max_accounts)]
    return selected


def _batch_concurrency(req: IdealBatchStartRequest, total: int) -> int:
    try:
        requested = int(req.concurrency or 1)
    except Exception:
        requested = 1
    return max(1, min(MAX_BATCH_CONCURRENCY, total, requested))


def _append_log(job_id: str, message: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {message}"
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        job.setdefault("logs", []).append(line)
        job["logs"] = job["logs"][-500:]
        job["updated_at"] = time.time()


def _link_record_from_result(job_id: str, account_email: str, result: dict[str, Any]) -> dict[str, Any]:
    link = str(result.get("long_url") or result.get("hosted_instructions_url") or "").strip()
    return {
        "id": uuid.uuid4().hex[:16],
        "job_id": job_id,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "created_at_ts": time.time(),
        "account_email": account_email,
        "amount": str(result.get("amount") or ""),
        "amount_display": str(result.get("amount_display") or ""),
        "cs_id": str(result.get("cs_id") or ""),
        "billing_country": str(result.get("billing_country") or "NL"),
        "currency": str(result.get("currency") or "EUR"),
        "ideal_link": link,
        "long_url": link,
        "provider_redirect_url": str(result.get("provider_redirect_url") or ""),
        "stripe_redirect_url": str(result.get("stripe_redirect_url") or ""),
        "stripe_hosted_url": str(result.get("stripe_hosted_url") or ""),
        "fallback": bool(result.get("fallback")),
        "provider_error": str(result.get("provider_error") or ""),
    }


def _append_link(record: dict[str, Any]) -> None:
    with LINKS_LOCK:
        items = _load_links()
        record_email = str(record.get("account_email") or "").strip().lower()
        record_link = _normalize_link(record.get("ideal_link") or record.get("long_url"))
        if record_email:
            items = [item for item in items if str(item.get("account_email") or "").strip().lower() != record_email]
        elif record_link:
            items = [
                item
                for item in items
                if _normalize_link(item.get("ideal_link") or item.get("long_url")) != record_link
            ]
        items.insert(0, record)
        _save_links(items)


def _choose_account_proxy(req: IdealBatchStartRequest, account_index: int) -> str:
    proxies = pix_routes._parse_proxies(req.proxies)
    if not proxies and req.proxy:
        proxies = pix_routes._parse_proxies(req.proxy)
    if not proxies:
        return ""
    rotated = pix_routes._rotate_proxies_for_account(proxies, account_index)
    return rotated[0] if rotated else proxies[0]


def _request_for_account(req: IdealBatchStartRequest, account_email: str, account_index: int) -> IdealLongLinkRequest:
    token = pix_routes._load_token_for_email(account_email)
    if not token:
        raise RuntimeError("未找到账号授权 Token")
    return _ideal_request(
        IdealLongLinkRequest.model_validate({
            "accessToken": token,
            "proxy": _choose_account_proxy(req, account_index),
            "stripe_publishable_key": req.stripe_publishable_key,
            "billing_country": "NL",
            "checkout_ui_mode": req.checkout_ui_mode,
            "payment_locale": req.payment_locale,
            "link_type": "ideal",
            "checkoutProxyRegion": req.checkout_proxy_region,
            "providerProxyRegion": req.provider_proxy_region,
            "proxyChainStrategy": req.proxy_chain_strategy,
            "approveProxyRegion": req.approve_proxy_region,
            "proxyPreflightAttempts": req.proxy_preflight_attempts,
            "diagnostic_enabled": req.diagnostic_enabled,
            "client_fingerprint": req.client_fingerprint,
            "device_id": req.device_id,
            "user_agent": req.user_agent,
        })
    )


def _run_account(job_id: str, req: IdealBatchStartRequest, account: dict[str, Any], account_index: int) -> dict[str, Any]:
    email = str(account.get("email") or "").strip()
    _set_account_status(email, IDEAL_STATUS_RUNNING, job_id=job_id)
    _append_log(job_id, f"{email} 开始 iDEAL 提链")
    steps: list[dict[str, str]] = []
    try:
        long_req = _request_for_account(req, email, account_index)
        use_explicit_proxy = legacy.prepare_request_proxy(long_req)
        result_model = legacy.generate_long_link_once(long_req, use_explicit_proxy, steps=steps)
        result = result_model.model_dump()
        record = _link_record_from_result(job_id, email, result)
        _append_link(record)
        _set_account_status(email, IDEAL_STATUS_SUCCESS, job_id=job_id)
        _append_log(job_id, f"{email} iDEAL 提链成功")
        return {"email": email, "result": result, "link": record}
    except HTTPException as exc:
        detail = legacy.short_text(exc.detail)
        detail, _cleanup = legacy.apply_non_zero_amount_cleanup(_request_for_account(req, email, account_index), detail, steps)
        _set_account_status(email, IDEAL_STATUS_FAILED, error=detail, job_id=job_id)
        _append_log(job_id, f"{email} iDEAL 提链失败：{detail}")
        raise RuntimeError(detail) from exc
    except Exception as exc:
        detail = legacy.short_text(exc)
        _set_account_status(email, IDEAL_STATUS_FAILED, error=detail, job_id=job_id)
        _append_log(job_id, f"{email} iDEAL 提链异常：{detail}")
        raise RuntimeError(detail) from exc


def _run_batch_job(job_id: str, req: IdealBatchStartRequest) -> None:
    accounts = _select_batch_accounts(req)
    total = len(accounts)
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job:
            job["total"] = total
            job["concurrency"] = _batch_concurrency(req, total) if total else 1
            job["updated_at"] = time.time()
    if not accounts:
        with JOBS_LOCK:
            if job := JOBS.get(job_id):
                job.update(status="error", error="没有可提链的 iDEAL 账号", finished_at=time.time(), updated_at=time.time())
        return
    successes: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    max_workers = _batch_concurrency(req, total)
    _append_log(job_id, f"批量 iDEAL 提链启动：账号 {total} 个，并发 {max_workers}")
    if max_workers == 1:
        for index, account in enumerate(accounts):
            if JOBS.get(job_id, {}).get("cancel_requested"):
                break
            email = str(account.get("email") or "").strip()
            try:
                successes.append(_run_account(job_id, req, account, index))
            except Exception as exc:
                errors.append({"email": email, "error": str(exc)})
            with JOBS_LOCK:
                if job := JOBS.get(job_id):
                    job.update(
                        completed=len(successes) + len(errors),
                        successes=list(successes),
                        errors=list(errors),
                        current_result=successes[-1]["result"] if successes else None,
                        updated_at=time.time(),
                    )
                    if job.get("cancel_requested"):
                        break
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_run_account, job_id, req, account, index): account
                for index, account in enumerate(accounts)
                if not JOBS.get(job_id, {}).get("cancel_requested")
            }
            for future in as_completed(futures):
                account = futures[future]
                email = str(account.get("email") or "").strip()
                try:
                    successes.append(future.result())
                except Exception as exc:
                    errors.append({"email": email, "error": str(exc)})
                with JOBS_LOCK:
                    if job := JOBS.get(job_id):
                        job.update(
                            completed=len(successes) + len(errors),
                            successes=list(successes),
                            errors=list(errors),
                            current_result=successes[-1]["result"] if successes else None,
                            updated_at=time.time(),
                        )
                        if job.get("cancel_requested"):
                            break
    with JOBS_LOCK:
        if job := JOBS.get(job_id):
            cancelled = bool(job.get("cancel_requested"))
            job.update(
                status="cancelled" if cancelled else ("success" if successes else "error"),
                error="" if successes else (errors[0]["error"] if errors else "任务未生成结果"),
                successes=list(successes),
                errors=list(errors),
                completed=len(successes) + len(errors),
                finished_at=time.time(),
                updated_at=time.time(),
            )


def _delete_account_artifacts(email: str) -> dict[str, Any]:
    clean_email = str(email or "").strip()
    key = clean_email.lower()
    if not clean_email:
        return {"email": "", "links_deleted": 0, "dashboard_account_deleted": False, "auth_session_deleted": False}
    with LINKS_LOCK:
        links = _load_links()
        kept = [item for item in links if str(item.get("account_email") or "").strip().lower() != key]
        _save_links(kept)
    with ACCOUNT_STATUS_LOCK:
        statuses = _load_account_statuses()
        statuses.pop(key, None)
        _save_account_statuses(statuses)
    legacy_disabled = False
    try:
        legacy_disabled = bool(legacy.account_pool_store.disable_account_by_email(clean_email))
    except Exception:
        legacy_disabled = False
    return {
        "email": clean_email,
        "links_deleted": len(links) - len(kept),
        "dashboard_account_deleted": bool(account_store.delete_account(clean_email)),
        "auth_session_deleted": bool(delete_auth_session(clean_email)),
        "legacy_account_disabled": legacy_disabled,
    }


def create_ideal_link_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/ideal/accounts")
    def get_ideal_accounts() -> dict[str, Any]:
        return {"accounts": _iter_auth_accounts_with_ideal_status()}

    @router.delete("/api/ideal/accounts/{email}")
    def delete_ideal_account(email: str) -> dict[str, Any]:
        clean_email = str(email or "").strip()
        if not clean_email:
            raise HTTPException(status_code=400, detail="email required")
        return _delete_account_artifacts(clean_email)

    @router.post("/api/ideal/accounts/delete")
    def delete_ideal_accounts(req: IdealDeleteAccountsRequest) -> dict[str, Any]:
        seen: set[str] = set()
        emails = []
        for value in req.emails:
            email = str(value or "").strip()
            key = email.lower()
            if email and key not in seen:
                seen.add(key)
                emails.append(email)
        results = [_delete_account_artifacts(email) for email in emails]
        return {"deleted": len(results), "results": results}

    @router.post("/api/ideal/batch/start")
    def start_ideal_batch(req: IdealBatchStartRequest) -> dict[str, str]:
        job_id = uuid.uuid4().hex
        with JOBS_LOCK:
            JOBS[job_id] = {
                "job_id": job_id,
                "status": "running",
                "total": 0,
                "completed": 0,
                "concurrency": 1,
                "successes": [],
                "errors": [],
                "logs": [],
                "current_result": None,
                "error": "",
                "cancel_requested": False,
                "started_at": time.time(),
                "updated_at": time.time(),
            }
        threading.Thread(target=lambda: _run_batch_job(job_id, req), daemon=True).start()
        return {"job_id": job_id}

    @router.post("/api/ideal/jobs/{job_id}/cancel")
    def cancel_ideal_job(job_id: str) -> dict[str, Any]:
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="job not found")
            job["cancel_requested"] = True
            if job.get("status") == "running" and int(job.get("completed") or 0) >= int(job.get("total") or 0):
                job["status"] = "cancelled"
                job["finished_at"] = time.time()
            job["updated_at"] = time.time()
            return {"ok": True, "job_id": job_id, "status": job.get("status"), "cancel_requested": True}

    @router.get("/api/ideal/jobs/{job_id}")
    def get_ideal_job(job_id: str) -> dict[str, Any]:
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="job not found")
            return dict(job)

    @router.get("/api/ideal/links")
    def get_ideal_links() -> dict[str, Any]:
        return {"links": _load_links()}

    @router.post("/api/ideal/links/delete")
    def delete_ideal_links(req: IdealDeleteLinksRequest) -> dict[str, Any]:
        ids = {str(item or "").strip() for item in req.ids if str(item or "").strip()}
        if not ids:
            return {"deleted": 0, "links": _load_links()}
        links = _load_links()
        kept = [item for item in links if str(item.get("id") or "") not in ids]
        _save_links(kept)
        return {"deleted": len(links) - len(kept), "links": kept}

    @router.post("/api/ideal/links/clear")
    def clear_ideal_links() -> dict[str, Any]:
        links = _load_links()
        _save_links([])
        return {"deleted": len(links), "links": []}

    @router.post("/api/ideal/long-link/start")
    def post_ideal_long_link_start(params: IdealLongLinkRequest) -> dict[str, str]:
        try:
            return legacy.start_long_link_job(_ideal_request(params))
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"iDEAL 提链任务启动失败: {exc}") from exc

    @router.get("/api/ideal/long-link/jobs/{job_id}")
    def get_ideal_long_link_job(job_id: str) -> dict[str, Any]:
        return _namespaced_diagnostic_url(legacy.job_snapshot(job_id))

    @router.get("/api/ideal/long-link/jobs/{job_id}/diagnostics")
    def get_ideal_long_link_job_diagnostics(job_id: str):
        return legacy.get_long_link_job_diagnostics(job_id)

    @router.post("/api/ideal/proxy-chain-test")
    def post_ideal_proxy_chain_test(params: IdealProxyChainTestRequest) -> dict[str, Any]:
        try:
            return legacy.proxy_chain_test(_ideal_proxy_request(params))
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"iDEAL 代理测试失败: {exc}") from exc

    @router.post("/api/ideal/qr")
    def post_ideal_qr(params: IdealQrRequest):
        return legacy.qr_code(params)

    return router
