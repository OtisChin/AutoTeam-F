"""Admin maintenance and diagnostic routes."""

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request


def create_admin_maintenance_router(
    *,
    playwright_lock: Any,
    playwright_executor: Any,
    current_busy_detail: Any,
    logger: Any,
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/admin/fix-account-id")
    def post_admin_fix_account_id():
        """
        Recompute the saved admin workspace account_id from the current session token.
        """
        from autotoken.integrations.chatgpt_api import ChatGPTTeamAPI
        from autotoken.settings.admin_state import (
            get_admin_email,
            get_admin_session_token,
            get_chatgpt_account_id,
            update_admin_state,
        )

        if not get_admin_session_token():
            raise HTTPException(status_code=400, detail="尚未保存 session_token,请先导入")

        def _do():
            api = ChatGPTTeamAPI()
            try:
                api._launch_browser()
                logger.info("[修复 account_id] 打开 chatgpt.com 注入 session...")
                api.page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=60000)
                time.sleep(3)
                api._wait_for_cloudflare()
                api._inject_session(get_admin_session_token())
                api.page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=60000)
                time.sleep(2)
                api._wait_for_cloudflare()
                api._fetch_access_token()

                team, personal = api._list_real_workspaces()
                admin_roles = ("account-owner", "admin", "org-admin", "workspace-owner")
                chosen = None
                for acc in team:
                    if str(acc.get("current_user_role") or "").lower() in admin_roles:
                        chosen = acc
                        break
                if not chosen and team:
                    chosen = team[0]
                if not chosen:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"当前 session ({get_admin_email()}) 没有 Team workspace,"
                            f" 只有: {[a.get('structure') for a in personal]}。"
                            f"请确认该账号已被邀请加入 Team。"
                        ),
                    )

                new_account_id = str(chosen.get("id") or "")
                new_workspace_name = str(chosen.get("name") or "")

                api.account_id = new_account_id
                verify = api._api_fetch("GET", f"/backend-api/accounts/{new_account_id}/settings")
                if verify.get("status") != 200:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"新 account_id={new_account_id} 仍不可访问 "
                            f"status={verify.get('status')},session_token 可能已过期,请重新导入。"
                        ),
                    )

                old_account_id = get_chatgpt_account_id()
                update_admin_state(account_id=new_account_id, workspace_name=new_workspace_name)
                logger.info(
                    "[修复 account_id] 已更新: %s -> %s (workspace=%s)",
                    old_account_id,
                    new_account_id,
                    new_workspace_name,
                )
                return {
                    "message": "已修复",
                    "old_account_id": old_account_id,
                    "new_account_id": new_account_id,
                    "workspace_name": new_workspace_name,
                    "role": chosen.get("current_user_role"),
                }
            finally:
                try:
                    api.stop()
                except Exception:
                    pass

        if not playwright_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail=current_busy_detail("有任务正在执行"))
        try:
            return playwright_executor.run(_do)
        finally:
            playwright_lock.release()

    @router.get("/api/admin/diagnose")
    def get_admin_diagnose():
        """
        Probe the current admin session against key ChatGPT Team admin endpoints.
        """
        from autotoken.integrations.chatgpt_api import ChatGPTTeamAPI
        from autotoken.settings.admin_state import get_admin_email, get_chatgpt_account_id

        def _do():
            from autotoken.settings.admin_state import get_admin_session_token

            api = ChatGPTTeamAPI()
            try:
                api._launch_browser()
                api.page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=60000)
                time.sleep(3)
                api._wait_for_cloudflare()
                session_token = get_admin_session_token()
                if session_token:
                    api.account_id = get_chatgpt_account_id() or ""
                    api._inject_session(session_token)
                    api.page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=60000)
                    time.sleep(2)
                    api._wait_for_cloudflare()
                api._fetch_access_token()
                account_id = api.account_id or get_chatgpt_account_id() or ""
                probes = {}

                session_result = api.page.evaluate(
                    "async () => { const r = await fetch('/api/auth/session'); "
                    "return { status: r.status, body: (await r.text()).slice(0, 400) }; }"
                )
                probes["auth_session"] = session_result

                for name, path in [
                    ("backend_me", "/backend-api/me"),
                    ("backend_accounts", "/backend-api/accounts"),
                    ("workspace_settings", f"/backend-api/accounts/{account_id}/settings"),
                    ("workspace_users", f"/backend-api/accounts/{account_id}/users"),
                ]:
                    r = api._api_fetch("GET", path)
                    probes[name] = {"status": r.get("status"), "body": (r.get("body") or "")[:500]}

                return {
                    "admin_email": get_admin_email(),
                    "account_id": account_id,
                    "access_token_present": bool(api.access_token),
                    "access_token_prefix": (api.access_token or "")[:30],
                    "probes": probes,
                }
            finally:
                try:
                    api.stop()
                except Exception:
                    pass

        if not playwright_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail=current_busy_detail("有任务正在执行"))
        try:
            return playwright_executor.run(_do)
        finally:
            playwright_lock.release()

    @router.post("/api/admin/reconcile")
    def post_admin_reconcile(request: Request):
        """对账 Team 实际成员 vs 本地状态,修复残废 / 错位 / 耗尽未抛弃 / ghost。"""
        from autotoken.interfaces.manager import cmd_reconcile

        dry_run = str(request.query_params.get("dry_run", "")).strip().lower() in ("1", "true", "yes")

        def _do():
            return cmd_reconcile(dry_run=dry_run)

        if not playwright_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail=current_busy_detail("有任务正在执行"))
        try:
            return playwright_executor.run(_do)
        finally:
            playwright_lock.release()

    return router
