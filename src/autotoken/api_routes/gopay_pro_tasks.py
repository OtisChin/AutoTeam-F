"""GoPay Pro task launch routes."""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import AliasChoices, BaseModel, Field

from autotoken.services.task_runtime import TASK_GROUP_GOPAY_PRO

GOPAY_PRO_BATCH_MAX_EMAILS = 1_000


class GoPayProTaskParams(BaseModel):
    kind: str = ""


class GoPayProBatchParams(BaseModel):
    account_emails: list[str] = Field(default_factory=list, validation_alias=AliasChoices("account_emails", "accountEmails"))
    concurrency: int | None = None
    max_attempts: int = Field(3, validation_alias=AliasChoices("max_attempts", "maxAttempts"))


def create_gopay_pro_tasks_router(
    *,
    task_kinds: set[str],
    start_task: Callable[..., dict[str, Any]],
    run_script_task: Callable[..., dict[str, Any]],
    run_batch_task: Callable[..., dict[str, Any]],
    account_token_items: Callable[[list[str]], list[dict[str, str]]],
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/gopay-pro/task", status_code=202)
    def start_gopay_pro_task(params: GoPayProTaskParams):
        kind = str(params.kind or "").strip()
        if kind not in task_kinds:
            raise HTTPException(status_code=400, detail=f"不支持的 GoPay Pro 命令: {kind}")
        return start_task(
            "gopay-pro",
            run_script_task,
            {"kind": kind},
            kind,
            task_group=TASK_GROUP_GOPAY_PRO,
            pass_task_id=True,
        )

    @router.post("/api/gopay-pro/batch", status_code=202)
    def start_gopay_pro_batch(params: GoPayProBatchParams):
        if len(params.account_emails or []) > GOPAY_PRO_BATCH_MAX_EMAILS:
            raise HTTPException(status_code=400, detail=f"GoPay Pro 批量账号过多，最多支持 {GOPAY_PRO_BATCH_MAX_EMAILS} 个")
        token_items = account_token_items(params.account_emails)
        emails = [item["email"] for item in token_items]
        return start_task(
            "gopay-pro-batch",
            run_batch_task,
            {
                "account_emails": emails,
                "account_emails_count": len(emails),
                "concurrency": params.concurrency,
                "max_attempts": params.max_attempts,
            },
            emails,
            params.concurrency,
            params.max_attempts,
            task_group=TASK_GROUP_GOPAY_PRO,
            pass_task_id=True,
        )

    return router
