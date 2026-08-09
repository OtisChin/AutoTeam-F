"""Dashboard status and account-sync HTTP routes."""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException


def build_status_response(
    *,
    load_accounts_with_session_stubs: Callable[..., list[dict]],
    sanitize_accounts_batch: Callable[[list[dict], dict | None], list[dict]],
    include_session_stubs: bool = True,
) -> dict:
    """Build the dashboard status payload without performing live quota checks."""
    from autotoken.storage.accounts import (
        STATUS_ACTIVE,
        STATUS_AUTH_INVALID,
        STATUS_EXHAUSTED,
        STATUS_FAIL,
        STATUS_ORPHAN,
        STATUS_PENDING,
        STATUS_STASHED,
        STATUS_STANDBY,
    )

    accounts = load_accounts_with_session_stubs(include_session_stubs=include_session_stubs)
    quota_cache = {
        account["email"]: account.get("last_quota")
        for account in accounts
        if isinstance(account.get("last_quota"), dict) and account.get("email")
    }
    sanitized_accounts = sanitize_accounts_batch(accounts, quota_cache)

    return {
        "accounts": sanitized_accounts,
        "summary": {
            "active": sum(1 for account in sanitized_accounts if account["status"] == STATUS_ACTIVE),
            "standby": sum(1 for account in sanitized_accounts if account["status"] == STATUS_STANDBY),
            "stashed": sum(1 for account in sanitized_accounts if account["status"] == STATUS_STASHED),
            "exhausted": sum(1 for account in sanitized_accounts if account["status"] == STATUS_EXHAUSTED),
            "pending": sum(1 for account in sanitized_accounts if account["status"] == STATUS_PENDING),
            "auth_invalid": sum(1 for account in sanitized_accounts if account["status"] == STATUS_AUTH_INVALID),
            "orphan": sum(1 for account in sanitized_accounts if account["status"] == STATUS_ORPHAN),
            "fail": sum(1 for account in sanitized_accounts if account["status"] == STATUS_FAIL),
            "free": sum(1 for account in sanitized_accounts if account.get("account_type") == "free"),
            "team": sum(1 for account in sanitized_accounts if account.get("account_type") == "team"),
            "plus": sum(1 for account in sanitized_accounts if account.get("account_type") == "plus"),
            "pro": sum(1 for account in sanitized_accounts if account.get("account_type") == "pro"),
            "total": len(sanitized_accounts),
        },
        "quota_cache": quota_cache,
    }


def create_status_router(
    *,
    load_accounts_with_session_stubs: Callable[..., list[dict]],
    sanitize_accounts_batch: Callable[[list[dict], dict | None], list[dict]],
    playwright_lock: Any,
    playwright_executor: Any,
    current_busy_detail: Callable[[str], Any],
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/status")
    def get_status(include_session_stubs: bool = True):
        """获取所有账号状态。"""
        return build_status_response(
            load_accounts_with_session_stubs=load_accounts_with_session_stubs,
            sanitize_accounts_batch=sanitize_accounts_batch,
            include_session_stubs=include_session_stubs,
        )

    @router.post("/api/sync/accounts")
    def post_sync_accounts():
        """从 auths 目录和 Team 成员同步账号到 accounts.json"""
        from autotoken.interfaces.manager import sync_account_states

        if not playwright_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail=current_busy_detail("有任务正在执行，请等待完成后再同步"))

        try:
            playwright_executor.run(sync_account_states)
        finally:
            playwright_lock.release()

        from autotoken.storage.accounts import load_accounts

        accounts = load_accounts()
        return {"message": f"同步完成，共 {len(accounts)} 个账号", "total": len(accounts)}

    return router
