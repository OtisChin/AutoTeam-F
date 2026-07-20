"""India UPI placeholder extraction routes."""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from autotoken.core.paths import PROJECT_ROOT
from autotoken.storage import accounts as account_store

LINKS_FILE = PROJECT_ROOT / "data" / "india_upi_links.json"
ACCOUNT_STATUS_FILE = PROJECT_ROOT / "data" / "india_upi_account_status.json"
MAX_BATCH_CONCURRENCY = 10
UPI_STATUS_PENDING = "pending"
UPI_STATUS_PAID = "paid"
UPI_STATUS_TEXT = {"pending": "未提链", "running": "提链中", "success": "已提链", "failed": "提链失败", "paid": "已支付"}
JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.RLock()
TERMINAL_STATUSES = {"success", "error", "failed", "cancelled", "not_implemented"}


class IndiaUpiStartRequest(BaseModel):
    account_email: str = Field("", alias="accountEmail")
    proxies: str = ""
    concurrency: int = 1
    local_proxy: str = Field("", alias="localProxy")
    kookeey_endpoint: str = Field("gate.kookeey.info:1000", alias="kookeeyEndpoint")
    kookeey_user: str = Field("", alias="kookeeyUser")
    kookeey_pass: str = Field("", alias="kookeeyPass")
    model_config = {"populate_by_name": True}


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


class IndiaUpiDeleteLinksRequest(BaseModel):
    ids: list[str] = Field(default_factory=list)


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_links() -> list[dict[str, Any]]:
    data = _read_json(LINKS_FILE, [])
    return data if isinstance(data, list) else []


def _save_links(items: list[dict[str, Any]]) -> None:
    _write_json(LINKS_FILE, items)


def _load_account_statuses() -> dict[str, dict[str, Any]]:
    data = _read_json(ACCOUNT_STATUS_FILE, {})
    return data if isinstance(data, dict) else {}


def _iter_auth_accounts_with_upi_status() -> list[dict[str, Any]]:
    statuses = _load_account_statuses()
    rows: list[dict[str, Any]] = []
    for account in account_store.load_accounts():
        email = str(account.get("email") or "").strip()
        if not email:
            continue
        item = statuses.get(email.lower()) if isinstance(statuses.get(email.lower()), dict) else {}
        status = str(item.get("status") or UPI_STATUS_PENDING)
        if status not in UPI_STATUS_TEXT:
            status = UPI_STATUS_PENDING
        rows.append({**account, "upi_status": status, "upi_status_text": str(item.get("status_text") or UPI_STATUS_TEXT[status]), "upi_error": str(item.get("error") or ""), "upi_status_updated_at": item.get("updated_at"), "upi_selectable": status != UPI_STATUS_PAID})
    return rows


def _new_job(account_emails: list[str], concurrency: int) -> str:
    job_id = uuid.uuid4().hex[:12]
    created = time.time()
    message = "印度UPI 后端核心提链功能待接入"
    skipped = [{"email": email, "reason": message} for email in account_emails]
    with JOBS_LOCK:
        JOBS[job_id] = {
            "id": job_id, "status": "not_implemented", "logs": ["任务已创建", message],
            "result": {"batch": True, "implemented": False, "message": message, "successes": [], "errors": [], "skipped": skipped},
            "error": None, "created_at": created, "finished_at": created,
            "account_email": account_emails[0] if len(account_emails) == 1 else "",
            "total": len(account_emails), "completed": 0,
            "concurrency": max(1, min(MAX_BATCH_CONCURRENCY, int(concurrency or 1))),
            "cancel_requested": False, "running_count": 0, "skipped": skipped, "account_statuses": {},
        }
    return job_id


def _job_snapshot(job_id: str) -> dict[str, Any]:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return {"id": job["id"], "status": job["status"], "logs": list(job["logs"]), "result": job["result"], "error": job["error"], "created_at": job["created_at"], "finished_at": job["finished_at"], "account_email": job.get("account_email") or "", "total": job.get("total") or 0, "completed": job.get("completed") or 0, "concurrency": job.get("concurrency") or 1, "running_count": job.get("running_count") or 0, "cancel_requested": bool(job.get("cancel_requested")), "skipped": job.get("skipped") or [], "account_statuses": job.get("account_statuses") or {}}


def create_india_upi_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/india-upi/accounts")
    def get_india_upi_accounts() -> dict[str, Any]:
        return {"accounts": _iter_auth_accounts_with_upi_status()}

    @router.post("/api/india-upi/start")
    def start_india_upi(req: IndiaUpiStartRequest) -> dict[str, str]:
        email = str(req.account_email or "").strip()
        if not email:
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "请选择要提链的账号"})
        return {"job_id": _new_job([email], req.concurrency)}

    @router.post("/api/india-upi/batch/start")
    def start_india_upi_batch(req: IndiaUpiBatchStartRequest) -> dict[str, str]:
        emails = list(req.account_emails)
        if req.max_accounts and req.max_accounts > 0:
            emails = emails[: int(req.max_accounts)]
        if not emails:
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "请选择要提链的账号"})
        return {"job_id": _new_job(emails, req.concurrency)}

    @router.get("/api/india-upi/jobs/{job_id}")
    def get_india_upi_job(job_id: str) -> dict[str, Any]:
        return _job_snapshot(job_id)

    @router.post("/api/india-upi/jobs/{job_id}/cancel")
    def cancel_india_upi_job(job_id: str) -> dict[str, Any]:
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="job not found")
            if job.get("status") not in TERMINAL_STATUSES:
                job["status"] = "cancelled"
                job["cancel_requested"] = True
                job["finished_at"] = time.time()
            return {"ok": True, "job_id": job_id, "status": job.get("status"), "cancel_requested": bool(job.get("cancel_requested"))}

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

    return router
