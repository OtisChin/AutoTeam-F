"""Team member HTTP routes."""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class TeamMemberRemoveParams(BaseModel):
    email: str
    user_id: str
    type: str


def create_team_members_router(
    *,
    playwright_lock: Any,
    playwright_executor: Any,
    current_busy_detail: Callable[[str], Any],
    is_main_account_email: Callable[[str], bool],
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/team/members")
    def get_team_members():
        """获取 Team 全部成员（包括手动添加的外部成员）"""
        from autotoken.settings.admin_state import get_admin_session_token, get_chatgpt_account_id

        if not get_admin_session_token() or not get_chatgpt_account_id():
            raise HTTPException(status_code=400, detail="请先完成管理员登录")

        if not playwright_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail=current_busy_detail("有任务正在执行，请等待完成后再查询"))

        try:

            def _fetch_team_members():
                from autotoken.integrations.chatgpt_api import ChatGPTTeamAPI
                from autotoken.storage.account_ops import fetch_team_state
                from autotoken.storage.accounts import load_accounts

                chatgpt = ChatGPTTeamAPI()
                chatgpt.start()
                try:
                    members, invites = fetch_team_state(chatgpt)
                    local_emails = {account["email"].lower() for account in load_accounts()}

                    result = []
                    for member in members:
                        email = (member.get("email") or "").lower()
                        result.append(
                            {
                                "email": member.get("email", ""),
                                "role": member.get("role", ""),
                                "user_id": member.get("user_id") or member.get("id", ""),
                                "is_local": email in local_emails,
                                "type": "member",
                            }
                        )
                    for invite in invites:
                        email = (invite.get("email_address") or invite.get("email") or "").lower()
                        result.append(
                            {
                                "email": email,
                                "role": invite.get("role", ""),
                                "user_id": invite.get("id", ""),
                                "is_local": email in local_emails,
                                "type": "invite",
                            }
                        )
                    return {"members": result, "total": len(members), "invites": len(invites)}
                finally:
                    chatgpt.stop()

            return playwright_executor.run(_fetch_team_members)
        finally:
            playwright_lock.release()

    @router.post("/api/team/members/remove")
    def post_team_members_remove(params: TeamMemberRemoveParams):
        """移出 Team 成员或取消邀请。"""
        from autotoken.settings.admin_state import get_admin_session_token, get_chatgpt_account_id

        if not get_admin_session_token() or not get_chatgpt_account_id():
            raise HTTPException(status_code=400, detail="请先完成管理员登录")

        if not playwright_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail=current_busy_detail("有任务正在执行，请等待完成后再操作"))

        try:
            from autotoken.storage.accounts import find_account, load_accounts, update_account

            email = params.email.strip().lower()
            user_id = params.user_id.strip()
            member_type = params.type.strip().lower()

            if not email or not user_id:
                raise HTTPException(status_code=400, detail="缺少必要参数")
            if is_main_account_email(email):
                raise HTTPException(status_code=400, detail="主号不允许从 Team 成员页移出")
            if member_type not in ("member", "invite"):
                raise HTTPException(status_code=400, detail="无效的成员类型")

            account_id = get_chatgpt_account_id()

            def _do_remove_team_member():
                from autotoken.integrations.chatgpt_api import ChatGPTTeamAPI

                chatgpt = ChatGPTTeamAPI()
                chatgpt.start()
                try:
                    if member_type == "invite":
                        path = f"/backend-api/accounts/{account_id}/invites/{user_id}"
                        action_text = "取消邀请"
                    else:
                        path = f"/backend-api/accounts/{account_id}/users/{user_id}"
                        action_text = "移出 Team"

                    result = chatgpt._api_fetch("DELETE", path)
                    return result, action_text
                finally:
                    chatgpt.stop()

            result, action_text = playwright_executor.run(_do_remove_team_member)
            if result["status"] not in (200, 204):
                raise HTTPException(status_code=500, detail=f"{action_text}失败: HTTP {result['status']}")

            accounts = load_accounts()
            account = find_account(accounts, email)
            if account:
                update_account(email, status="standby")

            return {
                "message": f"已{action_text}: {email}",
                "email": email,
                "type": member_type,
            }
        finally:
            playwright_lock.release()

    return router
