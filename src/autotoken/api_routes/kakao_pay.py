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

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from autotoken.api_routes import brazil_pix as pix_routes
from autotoken.core.paths import PROJECT_ROOT
from autotoken.payments.kakao_pay import (
    KakaoPayJobConfig,
    build_kakao_dynamic_proxy,
    generate_kakao_trial,
)
from autotoken.services import proxy_runtime
from autotoken.storage import accounts as account_store
from autotoken.storage.auth_session_store import delete_auth_session

LINKS_FILE = PROJECT_ROOT / "data" / "kakao_pay_links.json"
ACCOUNT_STATUS_FILE = PROJECT_ROOT / "data" / "kakao_pay_account_status.json"
MAX_BATCH_CONCURRENCY = 20
MAX_ACCOUNT_ATTEMPTS = 5
MAX_CONFIGURABLE_ACCOUNT_ATTEMPTS = 20
PROXY_PREFLIGHT_MAX_ATTEMPTS = 5
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
JOBS_LOCK = threading.RLock()
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
    normalized = str(status or KAKAO_STATUS_PENDING).strip().lower()
    if normalized not in KAKAO_STATUS_TEXT:
        normalized = KAKAO_STATUS_PENDING
    item = {"status": normalized, "error": str(error or ""), "job_id": str(job_id or ""), "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
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


def _dedupe_link_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_accounts: set[str] = set()
    seen_links: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        email = str(item.get("account_email") or "").strip().lower()
        link = _normalize_link(item.get("kakao_link") or item.get("provider_redirect_url") or item.get("stripe_redirect_url"))
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
    return _normalize_link_record({
        "id": uuid.uuid4().hex[:16],
        "job_id": job_id,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "account_email": account_email,
        "country": "KR",
        "amount": str(fields.get("amount") or result.get("amount") or ""),
        "cs_id": str(fields.get("cs_id") or ""),
        "kakao_link": str(fields.get("kakao_link") or fields.get("provider_redirect_url") or fields.get("stripe_redirect_url") or ""),
        "provider_redirect_url": str(fields.get("provider_redirect_url") or ""),
        "stripe_redirect_url": str(fields.get("stripe_redirect_url") or ""),
        "link_source": str(fields.get("link_source") or ""),
        "link_binding": str(fields.get("link_binding") or ""),
        "chatgpt_checkout_url": str(fields.get("chatgpt_checkout_url") or ""),
        "billing": billing,
    })


def _append_link(record: dict[str, Any]) -> None:
    with LINKS_LOCK:
        items = _load_links()
        record_email = str(record.get("account_email") or "").strip().lower()
        record_link = _normalize_link(record.get("kakao_link") or record.get("provider_redirect_url") or record.get("stripe_redirect_url"))
        if record_email:
            items = [item for item in items if str(item.get("account_email") or "").strip().lower() != record_email]
        elif record_link:
            items = [item for item in items if _normalize_link(item.get("kakao_link") or item.get("provider_redirect_url") or item.get("stripe_redirect_url")) != record_link]
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


def _preflight_kakao_proxies_or_raise(cfg: KakaoPayJobConfig, log) -> KakaoPayJobConfig:
    if not cfg.direct_proxies and (not cfg.kookeey_user or not cfg.kookeey_pass):
        return cfg
    region = str(cfg.region or "KR").strip().upper() or "KR"
    errors: list[str] = []
    for stage_index in range(PROXY_PREFLIGHT_MAX_ATTEMPTS):
        proxy_url, sid_label = build_kakao_dynamic_proxy(cfg, stage_index)
        if not proxy_url:
            continue
        log(f"代理预检开始：{stage_index + 1}/{PROXY_PREFLIGHT_MAX_ATTEMPTS} region={region} {sid_label}")
        ok, message = proxy_runtime.preflight_payment_proxy_url(proxy_url)
        if ok:
            auth_ok, auth_message = proxy_runtime.preflight_chatgpt_authenticated_proxy_url(proxy_url, cfg.access_token)
            if auth_ok:
                log(f"代理预检通过：{message}; {auth_message}")
                return replace(cfg, direct_proxies=[proxy_url], preflighted_checkout_proxy_url=proxy_url)
            log(f"代理认证接口预检失败：{auth_message}")
            if "token_" in str(auth_message).lower() or "authentication token" in str(auth_message).lower():
                raise RuntimeError(f"认证接口预检失败: {auth_message}")
            errors.append(str(auth_message or "unknown"))
            continue
        errors.append(str(message or "unknown"))
        log(f"代理预检失败：{message}")
    raise RuntimeError(f"代理预检失败: {region} {'; '.join(errors[-PROXY_PREFLIGHT_MAX_ATTEMPTS:])}")


def _select_batch_accounts(req: KakaoPayBatchStartRequest) -> list[dict[str, Any]]:
    available = _iter_auth_accounts()
    by_email = {str(item.get("email") or "").strip().lower(): item for item in available}
    requested = [str(email or "").strip() for email in req.account_emails if str(email or "").strip()]
    selected = [by_email[email.lower()] for email in requested if email.lower() in by_email] if requested else available
    if req.max_accounts and req.max_accounts > 0:
        selected = selected[: int(req.max_accounts)]
    return selected


def _run_batch_account(job_id: str, req: KakaoPayBatchStartRequest, account: dict[str, Any], index: int, total: int, proxies: list[str]) -> dict[str, Any]:
    email = str(account.get("email") or "").strip()
    started = time.monotonic()
    if _is_job_cancel_requested(job_id):
        _append_log(job_id, f"[{index}/{total}] 跳过账号：{email}（任务已取消）")
        return {"skipped": True, "email": email, "status": _set_account_status(email, KAKAO_STATUS_PENDING, job_id=job_id)}
    _set_job_running_delta(job_id, 1)
    _append_log(job_id, f"[{index}/{total}] 开始账号：{email}")

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
                direct_proxies=_rotate_proxies_for_account(proxies, attempt),
            )
            try:
                cfg = _preflight_kakao_proxies_or_raise(cfg, account_log)
                result = generate_kakao_trial(cfg, log=account_log)
                break
            except Exception as exc:
                last_error = str(exc)
                if pix_routes._is_already_paid_error(last_error):
                    _mark_account_plus_kakao(email, last_error)
                    status = _set_account_status(email, KAKAO_STATUS_SUCCESS, error=last_error, job_id=job_id)
                    return {"skipped": True, "email": email, "reason": "账号已是 Plus，已标记绑定渠道 Kakao Pay", "status": status}
                if pix_routes._is_token_invalidated_error(last_error) or pix_routes._is_no_organization_error(last_error):
                    cleanup = _delete_invalid_account(email)
                    status = _set_account_status(email, KAKAO_STATUS_FAILED, error=last_error, job_id=job_id)
                    return {"ok": False, "email": email, "error": {"email": email, "elapsed_s": round(time.monotonic() - started, 1), "attempts": attempt, "error": f"账号不可用，已从账号池删除：{last_error}", "cleanup": cleanup}, "status": status}
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
        item = {"email": email, "elapsed_s": round(time.monotonic() - started, 1), "attempts": attempts or 1, "error": error}
        status = _set_account_status(email, KAKAO_STATUS_FAILED, error=error, job_id=job_id)
        _append_log(job_id, f"[{index}/{total}] 最终失败：{email} attempts={attempts or 1} {exc}")
        return {"ok": False, "email": email, "error": item, "status": status}
    finally:
        _set_job_running_delta(job_id, -1)


def _delete_invalid_account(email: str) -> dict[str, Any]:
    return {"record_deleted": bool(account_store.delete_account(email)), "auth_session_deleted": bool(delete_auth_session(email))}


def _mark_account_plus_kakao(email: str, message: str = "User is already paid") -> dict[str, Any]:
    account_store.ensure_session_only_account(email)
    return account_store.update_account(
        email,
        account_type=account_store.ACCOUNT_TYPE_PLUS,
        last_bind_provider="kakao_pay",
        last_bind_status="success",
        last_bind_at=time.time(),
        plus_bound_at=time.time(),
        last_bind_message=message,
        last_bind_failure_stage="",
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
        log(f"Kakao Pay 提链任务开始：{len(accounts)} 个账号，并发 {concurrency}，目标国家={req.region}")
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
        return {"id": job["id"], "status": job["status"], "logs": list(job["logs"]), "result": job["result"], "error": job["error"], "created_at": job["created_at"], "finished_at": job["finished_at"], "account_email": job.get("account_email") or "", "total": job.get("total") or 0, "completed": job.get("completed") or 0, "concurrency": job.get("concurrency") or 1, "running_count": job.get("running_count") or 0, "cancel_requested": bool(job.get("cancel_requested")), "skipped": job.get("skipped") or [], "account_statuses": job.get("account_statuses") or {}}


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

    return router
