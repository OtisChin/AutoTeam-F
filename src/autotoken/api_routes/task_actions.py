"""General background task launch routes."""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from autotoken.services.task_runtime import TASK_GROUP_QUOTA, TASK_GROUP_TEAM


class TaskParams(BaseModel):
    target: int = 5
    leave_workspace: bool = False


class CleanupParams(BaseModel):
    max_seats: int | None = None


class CheckParams(BaseModel):
    include_standby: bool = False


class ReplaceParams(BaseModel):
    email: str
    reason: str = "manual"


def create_task_actions_router(*, start_task: Callable[..., dict[str, Any]]) -> APIRouter:
    router = APIRouter()

    @router.post("/api/tasks/check", status_code=202)
    def post_check(params: CheckParams | None = None):
        """检查所有 active 账号额度（后台执行）。include_standby=True 时追加探测 standby 池。"""
        from autotoken.interfaces.manager import cmd_check

        params = params or CheckParams()
        include_standby = bool(params.include_standby)

        def _run():
            exhausted = cmd_check(include_standby=include_standby)
            return {"exhausted": [a["email"] for a in exhausted]}

        return start_task("check", _run, {"include_standby": include_standby}, task_group=TASK_GROUP_QUOTA)

    @router.post("/api/tasks/rotate", status_code=202)
    def post_rotate(params: TaskParams | None = None):
        """智能轮转（后台执行）"""
        from autotoken.interfaces.manager import cmd_rotate

        params = params or TaskParams()
        return start_task("rotate", cmd_rotate, {"target": params.target}, params.target, task_group=TASK_GROUP_TEAM)

    @router.post("/api/tasks/replace", status_code=202)
    def post_replace(params: ReplaceParams):
        """定点替换一个 Team 子号。"""
        from autotoken.interfaces.manager import cmd_replace_one

        email = (params.email or "").strip()
        if not email:
            raise HTTPException(status_code=400, detail="email 不能为空")
        return start_task(
            "replace",
            cmd_replace_one,
            {"email": email, "reason": params.reason},
            email,
            params.reason,
            task_group=TASK_GROUP_TEAM,
        )

    @router.post("/api/tasks/fill", status_code=202)
    def post_fill(params: TaskParams | None = None):
        """补满 Team 成员（后台执行）。leave_workspace=True 时切换为生产免费号模式。"""
        from autotoken.interfaces.manager import TEAM_SUB_ACCOUNT_HARD_CAP, cmd_fill

        params = params or TaskParams()
        if params.leave_workspace:
            from autotoken.storage.accounts import STATUS_ACTIVE, STATUS_EXHAUSTED, load_accounts

            in_team_local = sum(
                1 for account in load_accounts() if account.get("status") in (STATUS_ACTIVE, STATUS_EXHAUSTED)
            )
            if in_team_local >= TEAM_SUB_ACCOUNT_HARD_CAP:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Team 子号已满 {in_team_local}/{TEAM_SUB_ACCOUNT_HARD_CAP},"
                        "fill-personal 拒绝执行。请先等子号自然 exhausted 或手动腾位置后再试"
                    ),
                )

        command = "fill-personal" if params.leave_workspace else "fill"
        return start_task(
            command,
            cmd_fill,
            {"target": params.target, "leave_workspace": params.leave_workspace},
            params.target,
            leave_workspace=params.leave_workspace,
            task_group=TASK_GROUP_TEAM,
        )

    @router.post("/api/tasks/cleanup", status_code=202)
    def post_cleanup(params: CleanupParams | None = None):
        """清理多余成员（后台执行）"""
        from autotoken.interfaces.manager import cmd_cleanup

        params = params or CleanupParams()
        return start_task(
            "cleanup",
            cmd_cleanup,
            {"max_seats": params.max_seats},
            params.max_seats,
            task_group=TASK_GROUP_TEAM,
        )

    return router
