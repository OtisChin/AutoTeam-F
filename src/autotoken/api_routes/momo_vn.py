"""Vietnam MoMo link extraction routes."""

from __future__ import annotations

import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from autotoken.api_routes import brazil_pix as pix_routes
from autotoken.core.paths import PROJECT_ROOT
from autotoken.payments.momo_vn import MomoVnJobConfig, detect_momo_eligibility, generate_momo_vn_trial
from autotoken.storage import accounts as account_store
from autotoken.storage.auth_session_store import delete_auth_session

LINKS_FILE = PROJECT_ROOT / "data" / "momo_vn_links.json"
ACCOUNT_STATUS_FILE = PROJECT_ROOT / "data" / "momo_vn_account_status.json"
MOMO_LINK_TTL_SECONDS = 10 * 60
MAX_BATCH_CONCURRENCY = 20
MAX_ACCOUNT_ATTEMPTS = 5
MAX_CONFIGURABLE_ACCOUNT_ATTEMPTS = 20
MOMO_STATUS_PENDING = "pending"
MOMO_STATUS_ELIGIBLE = "eligible"
MOMO_STATUS_INELIGIBLE = "ineligible"
MOMO_STATUS_RUNNING = "running"
MOMO_STATUS_FAILED = "failed"
MOMO_STATUS_SUCCESS = "success"
MOMO_STATUS_PAID = "paid"
MOMO_STATUS_TEXT = {
    MOMO_STATUS_PENDING: "未提链",
    MOMO_STATUS_ELIGIBLE: "有资格",
    MOMO_STATUS_INELIGIBLE: "无资格",
    MOMO_STATUS_RUNNING: "提链中",
    MOMO_STATUS_FAILED: "提链失败",
    MOMO_STATUS_SUCCESS: "已提链",
    MOMO_STATUS_PAID: "已支付",
}
ACCOUNT_UI_FIELDS = (
    "email", "status", "account_type", "seat_type", "ttl_seconds", "expires_at", "last_active_at", "updated_at", "note",
)
JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.RLock()
LINKS_LOCK = threading.RLock()
ACCOUNT_STATUS_LOCK = threading.RLock()
TERMINAL_STATUSES = {"success", "error", "failed", "cancelled"}


class MomoVnStartRequest(BaseModel):
    account_email: str = Field("", alias="accountEmail")
    proxies: str = ""
    concurrency: int = 1
    local_proxy: str = Field("", alias="localProxy")
    kookeey_endpoint: str = Field("gate.kookeey.info:1000", alias="kookeeyEndpoint")
    kookeey_user: str = Field("", alias="kookeeyUser")
    kookeey_pass: str = Field("", alias="kookeeyPass")
    region: str = "VN"
    max_attempts: int = Field(MAX_ACCOUNT_ATTEMPTS, alias="maxAttempts")
    qualification_only: bool = Field(False, alias="qualificationOnly")
    model_config = {"populate_by_name": True}

    @field_validator("max_attempts", mode="before")
    @classmethod
    def _clean_max_attempts(cls, value: Any) -> int:
        try:
            attempts = int(value or MAX_ACCOUNT_ATTEMPTS)
        except Exception:
            attempts = MAX_ACCOUNT_ATTEMPTS
        return max(1, min(MAX_CONFIGURABLE_ACCOUNT_ATTEMPTS, attempts))


class MomoVnBatchStartRequest(MomoVnStartRequest):
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


class MomoVnDeleteLinksRequest(BaseModel):
    ids: list[str] = Field(default_factory=list)


class MomoVnDeleteAccountsRequest(BaseModel):
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


def _append_link(item: dict[str, Any]) -> None:
    with LINKS_LOCK:
        items = _load_links()
        items.insert(0, item)
        _save_links(items)


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
    normalized = str(status or MOMO_STATUS_PENDING).strip().lower()
    if normalized not in MOMO_STATUS_TEXT:
        normalized = MOMO_STATUS_PENDING
    item = {"status": normalized, "error": str(error or ""), "job_id": str(job_id or ""), "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    with ACCOUNT_STATUS_LOCK:
        statuses = _load_account_statuses()
        statuses[key] = item
        _save_account_statuses(statuses)
    return item


def _momo_paid_emails() -> set[str]:
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
        momo_bound = bind_provider == "momo_vn" and bind_status in {"success", "succeeded", "ok"}
        if account_type == account_store.ACCOUNT_TYPE_PLUS or status == account_store.STATUS_PLUS or momo_bound:
            paid.add(email)
    return paid


def _iter_auth_accounts(*, include_paid: bool = False) -> list[dict[str, Any]]:
    return pix_routes._iter_auth_accounts(include_paid=include_paid)


def _load_token_for_email(email: str) -> str:
    return pix_routes._load_token_for_email(email)


def _parse_proxies(value: str | list[str]) -> list[str]:
    return pix_routes._parse_proxies(value)


def _rotate_proxies_for_account(proxies: list[str], account_index: int) -> list[str]:
    return pix_routes._rotate_proxies_for_account(proxies, account_index)


def _batch_concurrency(req: MomoVnBatchStartRequest, total: int) -> int:
    try:
        requested = int(req.concurrency or 1)
    except Exception:
        requested = 1
    return max(1, min(MAX_BATCH_CONCURRENCY, total, requested))


def _account_attempt_limit(req: MomoVnBatchStartRequest) -> int:
    try:
        attempts = int(req.max_attempts or MAX_ACCOUNT_ATTEMPTS)
    except Exception:
        attempts = MAX_ACCOUNT_ATTEMPTS
    return max(1, min(MAX_CONFIGURABLE_ACCOUNT_ATTEMPTS, attempts))


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
        link = _normalize_link(item.get("momo_link") or item.get("provider_redirect_url") or item.get("stripe_redirect_url"))
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
    paid_emails = _momo_paid_emails()
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


def _iter_auth_accounts_with_momo_status() -> list[dict[str, Any]]:
    statuses = _load_account_statuses()
    paid_emails = _momo_paid_emails()
    linked_emails = {str(item.get("account_email") or "").strip().lower() for item in _load_links() if str(item.get("account_email") or "").strip()}
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
        dashboard_account = dashboard_by_email.get(key) or {}
        item = statuses.get(key) if isinstance(statuses.get(key), dict) else {}
        if key in paid_emails:
            item = {"status": MOMO_STATUS_PAID, "error": "", "updated_at": ""}
        elif not item and key in linked_emails:
            item = {"status": MOMO_STATUS_SUCCESS, "error": "", "updated_at": ""}
        status = str(item.get("status") or MOMO_STATUS_PENDING)
        if status not in MOMO_STATUS_TEXT:
            status = MOMO_STATUS_PENDING
        rows.append({
            field: (email if field == "email" else dashboard_account.get(field, account.get(field))) for field in ACCOUNT_UI_FIELDS
        } | {
            "momo_status": status,
            "momo_status_text": MOMO_STATUS_TEXT[status],
            "momo_error": str(item.get("error") or ""),
            "momo_country": "VN",
            "momo_status_updated_at": item.get("updated_at"),
            "momo_selectable": status != MOMO_STATUS_PAID,
        })
    return rows


def _select_batch_accounts(req: MomoVnBatchStartRequest) -> list[dict[str, Any]]:
    available = _iter_auth_accounts()
    by_email = {str(item.get("email") or "").strip().lower(): item for item in available}
    requested = [str(email or "").strip() for email in req.account_emails if str(email or "").strip()]
    selected = [by_email[email.lower()] for email in requested if email.lower() in by_email] if requested else available
    if req.max_accounts and req.max_accounts > 0:
        selected = selected[: int(req.max_accounts)]
    return selected


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
    return 0


def _link_record_from_result(job_id: str, account_email: str, result: dict[str, Any]) -> dict[str, Any]:
    fields = result.get("fields") if isinstance(result.get("fields"), dict) else {}
    billing = fields.get("billing") if isinstance(fields.get("billing"), dict) else result.get("billing") or {}
    primary_link = str(fields.get("provider_redirect_url") or fields.get("momo_link") or fields.get("stripe_redirect_url") or "")
    currency = str(fields.get("currency") or result.get("currency") or "VND").strip().upper() or "VND"
    created_at_ts = int(time.time())
    explicit_expires_at_ts = _timestamp_seconds(fields.get("momo_expires_at_ts") or fields.get("momo_expires_at") or result.get("momo_expires_at_ts") or result.get("momo_expires_at"))
    expires_at_ts = explicit_expires_at_ts or (created_at_ts + MOMO_LINK_TTL_SECONDS)
    return {
        "id": uuid.uuid4().hex[:16],
        "job_id": job_id,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(created_at_ts)),
        "created_at_ts": created_at_ts,
        "account_email": account_email,
        "country": "VN",
        "amount": str(fields.get("amount") or result.get("amount") or ""),
        "currency": currency,
        "cs_id": str(fields.get("cs_id") or ""),
        "momo_link": primary_link,
        "provider_redirect_url": str(fields.get("provider_redirect_url") or primary_link),
        "stripe_redirect_url": str(fields.get("stripe_redirect_url") or ""),
        "momo_ttl_seconds": max(0, expires_at_ts - created_at_ts),
        "momo_expires_at_ts": expires_at_ts,
        "billing": billing,
    }


def _append_log(job_id: str, message: str) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        logs = job.setdefault("logs", [])
        logs.append(message)
        if len(logs) > 500:
            del logs[:-500]


def _is_job_cancel_requested(job_id: str) -> bool:
    with JOBS_LOCK:
        return bool((JOBS.get(job_id) or {}).get("cancel_requested"))


def _set_job_running_delta(job_id: str, delta: int) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        job["running_count"] = max(0, int(job.get("running_count") or 0) + int(delta))


def _should_retry_momo_error(message: str) -> bool:
    text = str(message or "").strip().lower()
    if not text:
        return True
    non_retry_markers = (
        "缺少 access token",
        "账号缺少有效 accesstoken",
        "账号缺少邮箱",
        "缺少代理",
        "无 momo 资格",
        "无资格",
    )
    return not any(marker in text for marker in non_retry_markers)


def _run_batch_account(
    job_id: str,
    req: MomoVnBatchStartRequest,
    account: dict[str, Any],
    index: int,
    total: int,
    proxies: list[str],
) -> dict[str, Any]:
    started = time.monotonic()
    email = str(account.get("email") or "").strip()
    if not email:
        return {"ok": False, "email": "", "error": {"email": "", "elapsed_s": 0.0, "attempts": 0, "error": "账号缺少邮箱"}, "status": {}}

    def account_log(message: str) -> None:
        _append_log(job_id, f"[{index}/{total}] {email}: {message}")

    if _is_job_cancel_requested(job_id):
        account_log("跳过账号：任务已取消")
        return {"ok": False, "email": email, "skipped": True, "reason": "任务已取消", "status": _set_account_status(email, MOMO_STATUS_PENDING, job_id=job_id)}

    if str(email).lower() in _momo_paid_emails():
        status = _set_account_status(email, MOMO_STATUS_PAID, job_id=job_id)
        return {"ok": False, "email": email, "skipped": True, "reason": "账号已支付", "status": status}

    attempts = 0
    _set_job_running_delta(job_id, 1)
    try:
        _set_account_status(email, MOMO_STATUS_RUNNING, job_id=job_id)
        token = _load_token_for_email(email)
        if not token:
            raise RuntimeError("缺少 Access Token")
        rotated_proxies = _rotate_proxies_for_account(proxies, index - 1)
        result: dict[str, Any] | None = None
        last_error = ""
        max_attempts = _account_attempt_limit(req)
        for attempt in range(1, max_attempts + 1):
            attempts = attempt
            if _is_job_cancel_requested(job_id) and attempt > 1:
                raise RuntimeError(f"任务已取消，停止重试；最后错误: {last_error}")
            account_log(f"第 {attempt}/{max_attempts} 次尝试")
            cfg = MomoVnJobConfig(
                access_token=token,
                local_proxy=req.local_proxy,
                kookeey_user=req.kookeey_user,
                kookeey_pass=req.kookeey_pass,
                kookeey_endpoint=req.kookeey_endpoint,
                region=req.region,
                direct_proxies=rotated_proxies,
            )
            try:
                eligibility = detect_momo_eligibility(cfg, account_log)
                if str(eligibility.get("status") or "").lower() != MOMO_STATUS_ELIGIBLE or not eligibility.get("has_momo"):
                    status = _set_account_status(email, MOMO_STATUS_INELIGIBLE, job_id=job_id)
                    account_log("资格检测结果：无 MoMo")
                    return {"ok": False, "email": email, "skipped": True, "reason": "无资格", "status": status}
                status = _set_account_status(email, MOMO_STATUS_ELIGIBLE, job_id=job_id)
                if req.qualification_only:
                    account_log("资格检测结果：有 MoMo")
                    return {"ok": True, "email": email, "success": {"email": email, "elapsed_s": round(time.monotonic() - started, 1), "attempts": attempts, "qualified": True}, "status": status}
                result = generate_momo_vn_trial(replace(cfg, preflight_result=eligibility), account_log)
                break
            except Exception as exc:
                last_error = str(exc)
                if pix_routes._is_non_zero_after_promo_error(last_error):
                    status = _set_account_status(email, MOMO_STATUS_FAILED, error=last_error, job_id=job_id)
                    _append_log(job_id, f"[{index}/{total}] MoMo VN 金额非 0，账号保留：{email}")
                    return {
                        "ok": False,
                        "email": email,
                        "error": {
                            "email": email,
                            "elapsed_s": round(time.monotonic() - started, 1),
                            "attempts": attempt,
                            "error": f"MoMo VN 金额非 0，账号保留：{last_error}",
                            "account_deleted": False,
                        },
                        "status": status,
                        "account_deleted": False,
                    }
                account_log(f"第 {attempt}/{max_attempts} 次失败：{last_error}")
                if attempt >= max_attempts or not _should_retry_momo_error(last_error):
                    raise
                time.sleep(min(2.0, 0.5 * attempt))
        if result is None:
            raise RuntimeError(last_error or "提链失败")
        result["account_email"] = email
        record = _link_record_from_result(job_id, email, result)
        _append_link(record)
        status = _set_account_status(email, MOMO_STATUS_SUCCESS, job_id=job_id)
        compact = {"email": email, "elapsed_s": round(time.monotonic() - started, 1), "attempts": attempts, "link": record}
        _append_log(job_id, f"[{index}/{total}] 成功：{email} attempts={attempts} cs_id={record.get('cs_id')}")
        return {"ok": True, "email": email, "success": compact, "status": status}
    except Exception as exc:
        error = str(exc)
        status = _set_account_status(email, MOMO_STATUS_FAILED, error=error, job_id=job_id)
        _append_log(job_id, f"[{index}/{total}] 最终失败：{email} attempts={attempts or 1} {exc}")
        return {"ok": False, "email": email, "error": {"email": email, "elapsed_s": round(time.monotonic() - started, 1), "attempts": attempts or 1, "error": error}, "status": status}
    finally:
        _set_job_running_delta(job_id, -1)


def _run_batch_job(job_id: str, req: MomoVnBatchStartRequest) -> None:
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
            account_statuses[email] = _set_account_status(email, MOMO_STATUS_PENDING, job_id=job_id)
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "running"
            JOBS[job_id]["total"] = len(accounts)
            JOBS[job_id]["completed"] = 0
            JOBS[job_id]["concurrency"] = concurrency
            JOBS[job_id]["running_count"] = 0
            JOBS[job_id]["account_statuses"] = account_statuses
        mode_text = "仅检测资格" if req.qualification_only else "完整提链"
        log(f"MoMo VN 任务开始：{len(accounts)} 个账号，并发 {concurrency}，模式={mode_text}")
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
                    skipped.append({"email": email, "reason": item.get("reason") or "已跳过"})
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
        log(f"MoMo VN 任务完成：成功 {len(successes)}，失败 {len(errors)}，跳过 {len(skipped)}")
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
            "result": None, "error": None, "created_at": created, "finished_at": None,
            "account_email": account_emails[0] if len(account_emails) == 1 else "",
            "total": len(account_emails), "completed": 0,
            "concurrency": max(1, min(MAX_BATCH_CONCURRENCY, int(concurrency or 1))),
            "cancel_requested": False, "running_count": 0, "skipped": [], "account_statuses": {},
        }
    return job_id


def _job_snapshot(job_id: str) -> dict[str, Any]:
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


def _delete_momo_vn_account_everywhere(email: str) -> dict[str, Any]:
    clean_email = str(email or "").strip()
    momo_cleanup = delete_account_artifacts(clean_email)
    dashboard_account_deleted = bool(account_store.delete_account(clean_email))
    auth_session_deleted = bool(delete_auth_session(clean_email))
    return {"ok": True, "email": clean_email, "dashboard_account_deleted": dashboard_account_deleted, "auth_session_deleted": auth_session_deleted, "momo_vn": momo_cleanup}


def create_momo_vn_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/momo-vn/accounts")
    def get_momo_vn_accounts() -> dict[str, Any]:
        return {"accounts": _iter_auth_accounts_with_momo_status()}

    @router.delete("/api/momo-vn/accounts/{email}")
    def delete_momo_vn_account(email: str) -> dict[str, Any]:
        clean_email = str(email or "").strip()
        if not clean_email:
            raise HTTPException(status_code=400, detail="email required")
        return _delete_momo_vn_account_everywhere(clean_email)

    @router.post("/api/momo-vn/accounts/delete")
    def delete_momo_vn_accounts(req: MomoVnDeleteAccountsRequest) -> dict[str, Any]:
        emails = [str(email or "").strip() for email in req.emails if str(email or "").strip()]
        if not emails:
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "请选择要删除的账号"})
        return {"ok": True, "results": [_delete_momo_vn_account_everywhere(email) for email in emails]}

    @router.post("/api/momo-vn/start")
    def start_momo_vn(req: MomoVnStartRequest) -> dict[str, str]:
        emails = [str(req.account_email or "").strip()] if str(req.account_email or "").strip() else []
        batch_req = MomoVnBatchStartRequest.model_validate(req.model_dump(by_alias=True) | {"accountEmails": emails})
        job_id = _new_job(emails, 1)
        threading.Thread(target=_run_batch_job, args=(job_id, batch_req), daemon=True).start()
        return {"job_id": job_id}

    @router.post("/api/momo-vn/batch/start")
    def start_momo_vn_batch(req: MomoVnBatchStartRequest) -> dict[str, str]:
        job_id = _new_job(req.account_emails, req.concurrency)
        threading.Thread(target=_run_batch_job, args=(job_id, req), daemon=True).start()
        return {"job_id": job_id}

    @router.post("/api/momo-vn/jobs/{job_id}/cancel")
    def cancel_momo_vn_job(job_id: str) -> dict[str, Any]:
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

    @router.get("/api/momo-vn/jobs/{job_id}")
    def get_momo_vn_job(job_id: str) -> dict[str, Any]:
        return _job_snapshot(job_id)

    @router.get("/api/momo-vn/links")
    def get_momo_vn_links() -> dict[str, Any]:
        links, pruned_deleted_accounts = _load_links_pruning_deleted_accounts()
        return {"links": links, "pruned_deleted_accounts": pruned_deleted_accounts}

    @router.post("/api/momo-vn/links/delete")
    def delete_momo_vn_links(req: MomoVnDeleteLinksRequest) -> dict[str, Any]:
        ids = {str(item or "").strip() for item in req.ids if str(item or "").strip()}
        if not ids:
            return {"deleted": 0, "links": _load_links()}
        items = _load_links()
        kept = [item for item in items if str(item.get("id") or "") not in ids]
        _save_links(kept)
        return {"deleted": len(items) - len(kept), "links": kept}

    @router.post("/api/momo-vn/links/clear")
    def clear_momo_vn_links() -> dict[str, Any]:
        count = len(_load_links())
        _save_links([])
        return {"deleted": count, "links": []}

    return router
