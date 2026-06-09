"""Account mutation HTTP routes."""

import logging
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from autotoken.api_routes.input_limits import validate_list_payload_limit

logger = logging.getLogger(__name__)
ACCOUNT_DELETE_BATCH_MAX_EMAILS = 1_000


class AccountTypeUpdateParams(BaseModel):
    account_type: str


class DeleteBatchParams(BaseModel):
    emails: list[str]
    continue_on_error: bool = True


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
            ACCOUNT_TYPE_FREE,
            ACCOUNT_TYPE_PLUS,
            ACCOUNT_TYPE_PRO,
            ACCOUNT_TYPE_TEAM,
            find_account,
            load_accounts,
            update_account,
        )

        normalized_email = email.strip().lower()
        next_type = (params.account_type or "").strip().lower()
        allowed_types = {
            ACCOUNT_TYPE_FREE,
            ACCOUNT_TYPE_TEAM,
            ACCOUNT_TYPE_PLUS,
            ACCOUNT_TYPE_PRO,
        }
        if next_type not in allowed_types:
            raise HTTPException(status_code=400, detail=f"不支持的账号类型: {params.account_type}")
        if is_main_account_email(normalized_email):
            raise HTTPException(status_code=400, detail="主号账号类型不允许手动修改")

        account = find_account(load_accounts(), normalized_email)
        if not account:
            raise HTTPException(status_code=404, detail="账号不存在")

        updated = update_account(normalized_email, account_type=next_type)
        return {
            "message": f"已将 {normalized_email} 账号类型更新为 {next_type}",
            "account": sanitize_account(updated),
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
                    if email.lower() not in existing and not get_auth_session_file(email):
                        results.append({"email": email, "ok": False, "error": "账号不存在"})
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
                        results.append({"email": email, "ok": True, "cleanup": cleanup})
                    except Exception as exc:
                        logger.error("[批量删除] %s 失败: %s", email, exc)
                        results.append({"email": email, "ok": False, "error": str(exc)})
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
