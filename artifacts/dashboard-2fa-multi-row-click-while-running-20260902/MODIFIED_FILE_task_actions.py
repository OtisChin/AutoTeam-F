"""General background task launch routes."""
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from autotoken.api_routes.input_limits import validate_list_payload_limit
from autotoken.services.task_runtime import TASK_GROUP_OAUTH, TASK_GROUP_QUOTA, TASK_GROUP_TEAM


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


class AccountTwoFactorSetupParams(BaseModel):
    emails: list[str]


def create_task_actions_router(
    *,
    start_task: Callable[..., dict[str, Any]],
    append_task_progress: Callable[[str | None, dict[str, Any]], Any] | None = None,
    logger: Any = None,
) -> APIRouter:
    if logger is None:
        from loguru import logger as task_logger
    else:
        task_logger = logger
    router = APIRouter()

    def log_2fa(message: str, *args: Any) -> None:
        task_logger.info(message.format(*args) if args else message)

    @router.post("/api/accounts/2fa/setup", status_code=202)
    def post_accounts_2fa_setup(params: AccountTwoFactorSetupParams):
        """Enable authenticator TOTP for existing accounts over saved protocol sessions."""
        from autotoken.core.normalization import normalized_email
        from autotoken.services.account_two_factor import setup_accounts_two_factor_protocol

        validate_list_payload_limit(params.emails, max_items=1_000, label="批量设置2FA")
        emails = []
        seen = set()
        for value in params.emails:
            email = normalized_email(value)
            if not email or email in seen:
                continue
            seen.add(email)
            emails.append(email)
        if not emails:
            raise HTTPException(status_code=400, detail="emails 不能为空")

        log_2fa("[2FA] 提交协议设置任务：{} 个账号", len(emails))

        def _run(task_id: str):
            log_2fa("[2FA] 任务 {} 开始：{} 个账号", task_id[:8], len(emails))

            def _progress(event: dict[str, Any]) -> None:
                if append_task_progress:
                    append_task_progress(task_id, event)
                message = str(event.get("message") or "").strip()
                if message:
                    log_2fa("[2FA] {}", message)

            _progress(
                {
                    "stage": "account_2fa_started",
                    "total": len(emails),
                    "emails": emails,
                    "message": f"开始设置 2FA，共 {len(emails)} 个账号",
                }
            )
            result = setup_accounts_two_factor_protocol(emails, progress=_progress)
            log_2fa(
                "[2FA] 任务 {} 完成：total={} enabled={} skipped={} failed={}",
                task_id[:8],
                result.get("total"),
                len(result.get("enabled") or []),
                len(result.get("skipped") or []),
                len(result.get("failed") or []),
            )
            return result

        return start_task(
            "setup-2fa",
            _run,
            {"emails": emails},
            exclusive=False,
            task_group=TASK_GROUP_OAUTH,
            pass_task_id=True,
        )

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
        """补满 Team 成员（后台执行）。"""
        from autotoken.interfaces.manager import TEAM_INVITE_REGISTER_DISABLED_MESSAGE, cmd_fill

        params = params or TaskParams()
        if params.leave_workspace:
            raise HTTPException(status_code=410, detail=TEAM_INVITE_REGISTER_DISABLED_MESSAGE)

        return start_task(
            "fill",
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
