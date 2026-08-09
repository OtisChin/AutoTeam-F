"""Account mutation HTTP routes."""

import logging
import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from autotoken.core.normalization import normalized_email
from autotoken.core.paths import PROJECT_ROOT
from autotoken.api_routes.input_limits import validate_list_payload_limit

logger = logging.getLogger(__name__)
ACCOUNT_DELETE_BATCH_MAX_EMAILS = 1_000
_delete_batch_audit_lock = threading.Lock()


class AccountTypeUpdateParams(BaseModel):
    account_type: str


class AccountMetadataUpdateParams(BaseModel):
    account_type: str
    status: str
    last_bind_provider: str = ""


class AccountMetadataBatchUpdateParams(BaseModel):
    emails: list[str]
    account_type: str | None = None
    status: str | None = None
    last_bind_provider: str | None = None


class DeleteBatchParams(BaseModel):
    emails: list[str]
    continue_on_error: bool = True


def _clean_account_type_or_raise(value: str) -> str:
    from autotoken.storage.accounts import (
        ACCOUNT_TYPE_FREE,
        ACCOUNT_TYPE_PLUS,
        ACCOUNT_TYPE_PRO,
        ACCOUNT_TYPE_TEAM,
    )

    next_type = (value or "").strip().lower()
    allowed_types = {
        ACCOUNT_TYPE_FREE,
        ACCOUNT_TYPE_TEAM,
        ACCOUNT_TYPE_PLUS,
        ACCOUNT_TYPE_PRO,
    }
    if next_type not in allowed_types:
        raise HTTPException(status_code=400, detail=f"不支持的账号类型: {value}")
    return next_type


def _clean_account_status_or_raise(value: str) -> str:
    from autotoken.storage.accounts import (
        STATUS_ACTIVE,
        STATUS_AUTH_INVALID,
        STATUS_EXHAUSTED,
        STATUS_FAIL,
        STATUS_ORPHAN,
        STATUS_PENDING,
        STATUS_PERSONAL,
        STATUS_PLUS,
        STATUS_STASHED,
        STATUS_SESSION_ONLY,
        STATUS_STANDBY,
    )

    next_status = (value or "").strip().lower()
    allowed_statuses = {
        STATUS_ACTIVE,
        STATUS_EXHAUSTED,
        STATUS_STANDBY,
        STATUS_PENDING,
        STATUS_PERSONAL,
        STATUS_PLUS,
        STATUS_STASHED,
        STATUS_AUTH_INVALID,
        STATUS_ORPHAN,
        STATUS_FAIL,
        STATUS_SESSION_ONLY,
    }
    if next_status not in allowed_statuses:
        raise HTTPException(status_code=400, detail=f"不支持的账号状态: {value}")
    return next_status


def _clean_bind_provider_or_raise(value: str) -> str:
    next_provider = (value or "").strip().lower()
    allowed_providers = {
        "",
        "pix",
        "paypal",
        "upi",
        "ideal",
        "kakao_pay",
        "momo_vn",
        "gopay",
        "card",
        "external_import",
    }
    if next_provider not in allowed_providers:
        raise HTTPException(status_code=400, detail=f"不支持的绑定渠道: {value}")
    return next_provider


def _account_type_update_fields(account: dict, next_type: str, **changes: Any) -> dict[str, Any]:
    update_fields: dict[str, Any] = {"account_type": next_type, **changes}
    last_quota = account.get("last_quota")
    if isinstance(last_quota, dict) and "plan_type" in last_quota:
        update_fields["last_quota"] = {**last_quota, "plan_type": next_type}
    return update_fields


def _account_metadata_update_fields(
    account: dict,
    *,
    account_type: str | None = None,
    status: str | None = None,
    last_bind_provider: str | None = None,
) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    if account_type is not None:
        changes["account_type"] = _clean_account_type_or_raise(account_type)
    if status is not None:
        changes["status"] = _clean_account_status_or_raise(status)
    if last_bind_provider is not None:
        changes["last_bind_provider"] = _clean_bind_provider_or_raise(last_bind_provider)
    if not changes:
        raise HTTPException(status_code=400, detail="至少需要提供一个可更新字段")
    if "account_type" in changes:
        return _account_type_update_fields(account, str(changes.pop("account_type")), **changes)
    return changes


def _delete_batch_audit_path() -> Path:
    return PROJECT_ROOT / "data" / "account_delete_audit.jsonl"


def _account_delete_audit_snapshot(account: dict | None) -> dict[str, Any]:
    if not account:
        return {}
    keys = [
        "email",
        "status",
        "account_type",
        "seat_type",
        "mail_provider",
        "cloudmail_account_id",
        "auth_file",
        "credentials_exported",
        "credentials_exported_at",
        "last_bind_status",
        "last_bind_failure_stage",
        "last_bind_message",
        "last_bind_task_id",
        "last_bind_at",
        "discarded_reason",
        "discarded_at",
    ]
    return {key: account.get(key) for key in keys if key in account}


def append_delete_batch_account_audit(
    *,
    email: str,
    account: dict | None,
    record_deleted: bool,
    auth_session_deleted: bool,
    remote_cleanup: bool,
    cleanup: dict | None,
    success: bool,
    error: str = "",
) -> None:
    """Persist a complete local audit row for /api/accounts/delete-batch."""
    payload = {
        "ts": time.time(),
        "email": normalized_email(email),
        "source": "api-delete-batch",
        "actor": "dashboard/api",
        "reason": "manual_delete_batch",
        "success": bool(success),
        "error": str(error or ""),
        "record_deleted": bool(record_deleted),
        "auth_session_deleted": bool(auth_session_deleted),
        "remote_cleanup": bool(remote_cleanup),
        "cleanup": cleanup or {},
        "account_existed": bool(account),
        "status": (account or {}).get("status"),
        "account_type": (account or {}).get("account_type"),
        "seat_type": (account or {}).get("seat_type"),
        "mail_provider": (account or {}).get("mail_provider"),
        "cloudmail_account_id_present": bool((account or {}).get("cloudmail_account_id")),
        "auth_file": (account or {}).get("auth_file"),
        "credentials_exported": bool((account or {}).get("credentials_exported")),
        "credentials_exported_at": (account or {}).get("credentials_exported_at"),
        "last_bind_status": (account or {}).get("last_bind_status"),
        "last_bind_failure_stage": (account or {}).get("last_bind_failure_stage"),
        "last_bind_message": (account or {}).get("last_bind_message"),
        "last_bind_task_id": (account or {}).get("last_bind_task_id"),
        "last_bind_at": (account or {}).get("last_bind_at"),
        "account_snapshot": _account_delete_audit_snapshot(account),
    }
    path = _delete_batch_audit_path()
    try:
        from autotoken.storage import sqlite_store

        sqlite_store.initialize()
        with sqlite_store.connect() as conn:
            conn.execute(
                """
                INSERT INTO event_records(kind, timestamp, email, category, task_id, status, data)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "account_delete_batch_audit",
                    float(payload["ts"]),
                    payload["email"],
                    payload["reason"],
                    "delete-batch",
                    str(payload.get("status") or ""),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with _delete_batch_audit_lock:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception as exc:
        logger.warning("[delete-batch-audit] failed to persist audit: email=%s error=%s", email, exc)


def cleanup_brazil_pix_account_artifacts(email: str) -> dict[str, Any]:
    try:
        from autotoken.api_routes import brazil_pix

        return brazil_pix.delete_account_artifacts(email)
    except Exception as exc:
        logger.debug("[账号删除] 清理 Brazil PIX 记录失败 %s: %s", email, exc)
        return {"links_deleted": 0, "status_deleted": False, "error": str(exc)}


def create_account_management_router(
    *,
    playwright_lock: Any,
    playwright_executor: Any,
    current_busy_detail: Callable[[str], Any],
    is_main_account_email: Callable[[str], bool],
    sanitize_account: Callable[[dict], dict],
) -> APIRouter:
    router = APIRouter()

    @router.delete("/api/accounts/{email}")
    def delete_account(email: str):
        """删除本地管理账号及其关联资源。"""
        lock_acquired = playwright_lock.acquire(blocking=False)
        try:
            from autotoken.settings.admin_state import get_admin_session_token, get_chatgpt_account_id
            from autotoken.storage.account_ops import delete_managed_account
            from autotoken.storage.accounts import load_accounts
            from autotoken.storage.auth_session_store import delete_auth_session, get_auth_session_file

            if is_main_account_email(email):
                raise HTTPException(status_code=400, detail="主号不允许删除")

            accounts = load_accounts()
            if not any(a["email"].lower() == email.lower() for a in accounts) and not get_auth_session_file(email):
                raise HTTPException(status_code=404, detail="账号不存在")

            remote_cleanup = bool(lock_acquired and get_admin_session_token() and get_chatgpt_account_id())
            if lock_acquired:
                cleanup = playwright_executor.run(
                    delete_managed_account,
                    email,
                    remove_remote=remote_cleanup,
                    remove_cloudmail=False,
                )
            else:
                cleanup = delete_managed_account(email, remove_remote=False, remove_cloudmail=False)
            cleanup["auth_session_deleted"] = delete_auth_session(email)
            cleanup["brazil_pix"] = cleanup_brazil_pix_account_artifacts(email)
            return {
                "message": "账号删除完成",
                "deleted_email": email,
                "cleanup": cleanup,
                "remote_cleanup": remote_cleanup,
                "remote_cleanup_skipped": not lock_acquired,
            }
        finally:
            if lock_acquired:
                playwright_lock.release()

    @router.post("/api/accounts/{email}/type")
    def update_account_type(email: str, params: AccountTypeUpdateParams):
        """手动更新账号类型。只改本地 accounts.json，不做 Team/CPA 侧操作。"""
        from autotoken.storage.accounts import (
            find_account,
            load_accounts,
            update_account,
        )

        normalized_email = email.strip().lower()
        next_type = _clean_account_type_or_raise(params.account_type)
        if is_main_account_email(normalized_email):
            raise HTTPException(status_code=400, detail="主号账号类型不允许手动修改")

        account = find_account(load_accounts(), normalized_email)
        if not account:
            raise HTTPException(status_code=404, detail="账号不存在")

        updated = update_account(normalized_email, **_account_type_update_fields(account, next_type))
        return {
            "message": f"已将 {normalized_email} 账号类型更新为 {next_type}",
            "account": sanitize_account(updated),
        }

    @router.patch("/api/accounts/{email}/metadata")
    def update_account_metadata(email: str, params: AccountMetadataUpdateParams):
        """手动更新账号类型、账号状态和绑定渠道。只改本地账号池记录。"""
        from autotoken.storage.accounts import find_account, load_accounts, update_account

        normalized_email = email.strip().lower()
        next_type = _clean_account_type_or_raise(params.account_type)
        next_status = _clean_account_status_or_raise(params.status)
        next_provider = _clean_bind_provider_or_raise(params.last_bind_provider)
        if is_main_account_email(normalized_email):
            raise HTTPException(status_code=400, detail="主号账号信息不允许手动修改")

        account = find_account(load_accounts(), normalized_email)
        if not account:
            raise HTTPException(status_code=404, detail="账号不存在")

        updated = update_account(
            normalized_email,
            **_account_metadata_update_fields(
                account,
                account_type=next_type,
                status=next_status,
                last_bind_provider=next_provider,
            ),
        )
        return {
            "message": f"已更新 {normalized_email} 账号信息",
            "account": sanitize_account(updated),
        }

    @router.patch("/api/accounts/metadata-batch")
    def update_accounts_metadata_batch(params: AccountMetadataBatchUpdateParams):
        """批量更新账号类型、账号状态和绑定渠道。只改本地账号池记录。"""
        from autotoken.storage.accounts import find_account, load_accounts, update_account

        validate_list_payload_limit(params.emails, max_items=ACCOUNT_DELETE_BATCH_MAX_EMAILS, label="批量修改账号")
        raw_emails = [(email or "").strip() for email in (params.emails or [])]
        emails = [email for email in raw_emails if email]
        if not emails:
            raise HTTPException(status_code=400, detail="emails 不能为空")
        if params.account_type is None and params.status is None and params.last_bind_provider is None:
            raise HTTPException(status_code=400, detail="至少需要提供一个可更新字段")
        if params.account_type is not None:
            _clean_account_type_or_raise(params.account_type)
        if params.status is not None:
            _clean_account_status_or_raise(params.status)
        if params.last_bind_provider is not None:
            _clean_bind_provider_or_raise(params.last_bind_provider)

        seen: set[str] = set()
        unique_emails: list[str] = []
        for email in emails:
            normalized = email.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            unique_emails.append(email)

        accounts = load_accounts()
        updated_accounts: list[dict[str, Any]] = []
        missing: list[str] = []
        skipped_main: list[str] = []
        for email in unique_emails:
            normalized_email = email.strip().lower()
            if is_main_account_email(normalized_email):
                skipped_main.append(normalized_email)
                continue
            account = find_account(accounts, normalized_email)
            if not account:
                missing.append(normalized_email)
                continue
            changes = _account_metadata_update_fields(
                account,
                account_type=params.account_type,
                status=params.status,
                last_bind_provider=params.last_bind_provider,
            )
            updated = update_account(normalized_email, **changes)
            if updated:
                updated_accounts.append(sanitize_account(updated))

        return {
            "message": f"已批量更新 {len(updated_accounts)} 个账号信息",
            "updated": len(updated_accounts),
            "missing": missing,
            "skipped_main": skipped_main,
            "accounts": updated_accounts,
        }

    @router.post("/api/accounts/{email}/kick")
    def post_kick_account(email: str):
        """将账号从 Team 中移出，状态变为 standby"""
        if not playwright_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail=current_busy_detail("有任务正在执行，请等待完成后再操作"))

        try:
            from autotoken.interfaces.manager import remove_from_team
            from autotoken.storage.accounts import find_account, load_accounts, update_account

            email = email.strip().lower()
            if is_main_account_email(email):
                raise HTTPException(status_code=400, detail="主号不允许移出 Team")
            accounts = load_accounts()
            acc = find_account(accounts, email)
            if not acc:
                raise HTTPException(status_code=404, detail="账号不存在")
            if acc["status"] != "active":
                raise HTTPException(status_code=400, detail=f"账号状态为 {acc['status']}，不是 active")

            def _do_kick():
                from autotoken.integrations.chatgpt_api import ChatGPTTeamAPI

                chatgpt = ChatGPTTeamAPI()
                chatgpt.start()
                try:
                    return remove_from_team(chatgpt, email)
                finally:
                    chatgpt.stop()

            ok = playwright_executor.run(_do_kick)
            if ok:
                update_account(email, status="standby")
                return {"message": f"已将 {email} 移出 Team", "email": email, "status": "standby"}
            raise HTTPException(status_code=500, detail=f"移出 {email} 失败")
        finally:
            playwright_lock.release()

    @router.post("/api/accounts/delete-batch")
    def delete_accounts_batch(params: DeleteBatchParams):
        """
        批量删除本地管理账号。整批共享一个 chatgpt_api,
        Team 成员/邀请状态只拉一次；CPA 自动同步已禁用，需要时手动同步。
        不删除临时邮箱服务中的邮箱账号。
        """
        from autotoken.integrations.chatgpt_api import ChatGPTTeamAPI
        from autotoken.settings.admin_state import get_admin_session_token, get_chatgpt_account_id
        from autotoken.storage.account_ops import delete_managed_account, fetch_team_state
        from autotoken.storage.accounts import load_accounts
        from autotoken.storage.auth_session_store import delete_auth_session, get_auth_session_file

        validate_list_payload_limit(params.emails, max_items=ACCOUNT_DELETE_BATCH_MAX_EMAILS, label="批量删除账号")
        raw_emails = [(e or "").strip() for e in (params.emails or [])]
        emails = [e for e in raw_emails if e]
        if not emails:
            raise HTTPException(status_code=400, detail="emails 不能为空")

        seen = set()
        dedup = []
        for email in emails:
            normalized = email.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            dedup.append(email)
        emails = dedup

        main_emails = [email for email in emails if is_main_account_email(email)]
        if main_emails:
            raise HTTPException(status_code=400, detail=f"主号不允许删除: {main_emails}")

        lock_acquired = playwright_lock.acquire(blocking=False)

        def _run():
            accounts = load_accounts()
            existing = {(account.get("email") or "").lower(): account for account in accounts}
            remote_cleanup = bool(lock_acquired and get_admin_session_token() and get_chatgpt_account_id())

            chatgpt_api = None
            results = []
            try:
                if remote_cleanup:
                    chatgpt_api = ChatGPTTeamAPI()
                    chatgpt_api.start()
                remote_state = fetch_team_state(chatgpt_api) if remote_cleanup else None

                for email in emails:
                    account_before = existing.get(email.lower())
                    if email.lower() not in existing and not get_auth_session_file(email):
                        results.append({"email": email, "ok": False, "error": "账号不存在"})
                        append_delete_batch_account_audit(
                            email=email,
                            account=None,
                            record_deleted=False,
                            auth_session_deleted=False,
                            remote_cleanup=remote_cleanup,
                            cleanup={},
                            success=False,
                            error="账号不存在",
                        )
                        if not params.continue_on_error:
                            break
                        continue
                    try:
                        cleanup = delete_managed_account(
                            email,
                            remove_remote=remote_cleanup,
                            remove_cloudmail=False,
                            chatgpt_api=chatgpt_api,
                            remote_state=remote_state,
                            sync_cpa_after=False,
                        )
                        cleanup["auth_session_deleted"] = delete_auth_session(email)
                        cleanup["brazil_pix"] = cleanup_brazil_pix_account_artifacts(email)
                        results.append({"email": email, "ok": True, "cleanup": cleanup})
                        append_delete_batch_account_audit(
                            email=email,
                            account=account_before,
                            record_deleted=bool(cleanup.get("local_record")),
                            auth_session_deleted=bool(cleanup.get("auth_session_deleted")),
                            remote_cleanup=remote_cleanup,
                            cleanup=cleanup,
                            success=True,
                            error="",
                        )
                    except Exception as exc:
                        logger.error("[批量删除] %s 失败: %s", email, exc)
                        results.append({"email": email, "ok": False, "error": str(exc)})
                        append_delete_batch_account_audit(
                            email=email,
                            account=account_before,
                            record_deleted=False,
                            auth_session_deleted=False,
                            remote_cleanup=remote_cleanup,
                            cleanup={},
                            success=False,
                            error=str(exc),
                        )
                        if not params.continue_on_error:
                            break
            finally:
                if chatgpt_api:
                    try:
                        chatgpt_api.stop()
                    except Exception as exc:
                        logger.debug("[批量删除] 关闭 chatgpt_api 异常: %s", exc)
                logger.info("[批量删除] 自动 CPA 同步已禁用，需要时请手动执行“同步 CPA”")

            ok_count = sum(1 for result in results if result["ok"])
            return {
                "results": results,
                "summary": {
                    "total": len(emails),
                    "ok": ok_count,
                    "failed": len(results) - ok_count,
                    "skipped": len(emails) - len(results),
                    "remote_cleanup": remote_cleanup,
                },
            }

        try:
            if not lock_acquired:
                return _run()
            timeout = max(300, 30 * len(emails) + 120)
            return playwright_executor.run_with_timeout(timeout, _run)
        finally:
            if lock_acquired:
                playwright_lock.release()

    return router
