"""Brazil PIX link extraction routes."""

from __future__ import annotations

import base64
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import requests
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from autotoken.core.paths import PROJECT_ROOT
from autotoken.payments.brazil_pix import PixJobConfig, generate_pix_trial
from autotoken.storage import accounts as account_store
from autotoken.storage.auth_session_store import delete_auth_session

AUTH_SESSION_DIR = PROJECT_ROOT / "data" / "auth_session"
LINKS_FILE = PROJECT_ROOT / "data" / "brazil_pix_links.json"
ACCOUNT_STATUS_FILE = PROJECT_ROOT / "data" / "brazil_pix_account_status.json"
PIX_CDK_API_BASE = "https://pix.iceaix.com"
MAX_BATCH_CONCURRENCY = 10
MAX_ACCOUNT_ATTEMPTS = 3
JOBS: dict[str, dict[str, Any]] = {}
PAYMENT_JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()
PAYMENT_JOBS_LOCK = threading.RLock()
LINKS_LOCK = threading.RLock()
ACCOUNT_STATUS_LOCK = threading.RLock()


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


class BrazilPixBatchStartRequest(BrazilPixStartRequest):
    account_emails: list[str] = Field(default_factory=list, alias="accountEmails")
    max_accounts: int = Field(0, alias="maxAccounts")
    concurrency: int = 1


class BrazilPixDeleteLinksRequest(BaseModel):
    ids: list[str] = Field(default_factory=list)


class BrazilPixPaymentSubmitRequest(BaseModel):
    cdk: str
    link: str


ACCOUNT_STATUS_PENDING = "pending"
ACCOUNT_STATUS_RUNNING = "running"
ACCOUNT_STATUS_SUCCESS = "success"
ACCOUNT_STATUS_FAILED = "failed"
ACCOUNT_STATUS_LABELS = {
    ACCOUNT_STATUS_PENDING: "未提链",
    ACCOUNT_STATUS_RUNNING: "提链中",
    ACCOUNT_STATUS_SUCCESS: "已提链",
    ACCOUNT_STATUS_FAILED: "提链失败",
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


def _pix_pool_excluded_emails() -> set[str]:
    excluded: set[str] = set()
    try:
        accounts = account_store.load_accounts()
    except Exception:
        return excluded
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
            excluded.add(email)
    return excluded


def _iter_auth_accounts() -> list[dict[str, Any]]:
    now = time.time()
    accounts: list[dict[str, Any]] = []
    if not AUTH_SESSION_DIR.exists():
        return accounts
    excluded_emails = _pix_pool_excluded_emails()
    for path in sorted(AUTH_SESSION_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        email = _auth_email_from_path(path, data)
        if email.lower() in excluded_emails:
            continue
        token = _extract_token(data)
        if not token or len(token) < 50:
            continue
        exp = _decode_jwt_exp(token)
        if exp and exp <= now + 300:
            continue
        accounts.append(
            {
                "email": email,
                "auth_file": str(path),
                "expires_at": exp,
                "ttl_seconds": max(0, int(exp - now)) if exp else 0,
            }
        )
    accounts.sort(key=lambda item: ("example.com" in item["email"].lower(), item["email"].lower()))
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


def _account_status_snapshot(email: str, statuses: dict[str, dict[str, Any]], linked_emails: set[str]) -> dict[str, Any]:
    key = str(email or "").strip().lower()
    item = dict(statuses.get(key) or {})
    if not item and key in linked_emails:
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
    accounts = _iter_auth_accounts()
    statuses = _load_account_statuses()
    linked_emails = {
        str(item.get("account_email") or "").strip().lower()
        for item in _load_links()
        if str(item.get("account_email") or "").strip()
    }
    for account in accounts:
        snapshot = _account_status_snapshot(account["email"], statuses, linked_emails)
        account.update(
            {
                "pix_status": snapshot["status"],
                "pix_status_text": snapshot["status_text"],
                "pix_error": snapshot["error"],
                "pix_status_updated_at": snapshot["updated_at"],
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


def _payment_api_json(resp: requests.Response) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError:
        data = {"ok": False, "code": f"http_{resp.status_code}", "message": resp.text[:500] or "支付服务返回非 JSON 响应"}
    if not resp.ok:
        message = data.get("message") if isinstance(data, dict) else ""
        raise HTTPException(status_code=resp.status_code, detail=data if isinstance(data, dict) else {"message": message or str(data)})
    if not isinstance(data, dict):
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
        "token_invalidated" in text or "authentication token has been invalidated" in text
    )


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
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error"] = str(exc)
            JOBS[job_id]["finished_at"] = time.time()
        _append_log(job_id, f"失败: {exc}")


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
        for attempt in range(1, MAX_ACCOUNT_ATTEMPTS + 1):
            attempts = attempt
            if _is_job_cancel_requested(job_id) and attempt > 1:
                raise RuntimeError(f"任务已取消，停止重试；最后错误: {last_error}")
            attempt_proxies = _rotate_proxies_for_account(proxies, attempt)
            _append_log(job_id, f"[{index}/{total}] 第 {attempt}/{MAX_ACCOUNT_ATTEMPTS} 次尝试：{email}")
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
                result = generate_pix_trial(cfg, log=account_log)
                if attempt > 1:
                    _append_log(job_id, f"[{index}/{total}] 重试成功：{email} attempt={attempt}")
                break
            except Exception as exc:
                last_error = str(exc)
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
                _append_log(job_id, f"[{index}/{total}] 第 {attempt}/{MAX_ACCOUNT_ATTEMPTS} 次失败：{email} {last_error}")
                if attempt >= MAX_ACCOUNT_ATTEMPTS:
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

    @router.post("/api/brazil-pix/jobs/{job_id}/cancel")
    def cancel_brazil_pix_job(job_id: str) -> dict[str, Any]:
        should_log = False
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="job not found")
            if job.get("status") in {"success", "error", "cancelled"}:
                return {"ok": True, "job_id": job_id, "status": job.get("status"), "cancel_requested": bool(job.get("cancel_requested"))}
            job["cancel_requested"] = True
            if job.get("status") in {"queued", "running"}:
                job["status"] = "cancelling"
            should_log = True
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
        return {"links": _load_links()}

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
    def submit_brazil_pix_payment(req: BrazilPixPaymentSubmitRequest) -> dict[str, Any]:
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
        data = _payment_api_json(resp)
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
