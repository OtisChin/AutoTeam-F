"""Background task query and control routes."""

import logging
from collections.abc import Callable
from threading import Event, RLock
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import AliasChoices, BaseModel, Field

from autotoken.api_routes.input_limits import validate_list_payload_limit
from autotoken.services.task_runtime import (
    TASK_GROUP_GOPAY,
    apply_gopay_runtime_control_public_updates,
    find_control_task,
    gopay_runtime_control_progress_event,
    gopay_skip_current_error,
    gopay_skip_current_progress_event,
    gopay_skip_current_response,
    mark_task_cancel_requested,
    mark_task_skip_current_requested,
    task_cancel_requested_progress_event,
    task_cancel_requested_response,
    task_control_status_error,
    task_detail_snapshot,
    update_gopay_runtime_control,
)

GOPAY_RUNTIME_CONTROL_MAX_EMAILS = 1_000


class TaskControlParams(BaseModel):
    task_id: str = ""
    task_group: str = ""


class GoPayRuntimeControlParams(BaseModel):
    task_id: str = Field("", validation_alias=AliasChoices("task_id", "taskId"))
    gopay_concurrency: int | None = Field(
        None,
        validation_alias=AliasChoices("gopay_concurrency", "gopayConcurrency"),
    )
    gopay_auto_signup_sms_provider: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_sms_provider", "gopayAutoSignupSmsProvider"),
    )
    account_emails: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("account_emails", "accountEmails"),
    )
    gopay_balance_poll_interval_seconds: float | None = Field(
        None,
        validation_alias=AliasChoices("gopay_balance_poll_interval_seconds", "gopayBalancePollIntervalSeconds"),
    )
    gopay_transfer_balance_wait_seconds: float | None = Field(
        None,
        validation_alias=AliasChoices("gopay_transfer_balance_wait_seconds", "gopayTransferBalanceWaitSeconds"),
    )


def _find_control_task_or_raise(
    tasks: dict[str, dict],
    current_task_ids: dict[str, str | None],
    params: TaskControlParams | None,
    *,
    default_group: str | None = None,
    command: str | None = None,
) -> dict:
    result = find_control_task(
        tasks,
        current_task_ids,
        task_id=params.task_id if params else "",
        task_group=params.task_group if params else "",
        default_group=default_group,
        command=command,
    )
    if not result.found:
        raise HTTPException(status_code=result.status_code, detail=result.detail)
    return result.task or {}


def create_task_control_router(
    *,
    tasks: Callable[[], dict[str, dict]],
    current_task_ids: Callable[[], dict[str, str | None]],
    task_cancel_signals: Callable[[], dict[str, Event]],
    task_skip_signals: Callable[[], dict[str, Event]],
    task_runtime_controls: Callable[[], dict[str, dict[str, Any]]],
    task_runtime_controls_lock: Callable[[], RLock],
    load_task_snapshots: Callable[[], list[dict]],
    merged_task_snapshots: Callable[..., list[dict]],
    run_task_cancel_hooks: Callable[[str], None],
    append_task_progress: Callable[[str | None, dict], Any],
    persist_task_snapshot: Callable[[dict | None], None],
    normalize_gopay_runtime_concurrency: Callable[[int | str | None, int], int],
    normalize_gopay_runtime_seconds: Callable[..., float],
    normalize_gopay_auto_signup_sms_provider: Callable[[str | None], str],
    default_gopay_wallet_balance_poll_interval_seconds: Callable[[], float],
    default_gopay_wallet_balance_wait_seconds: Callable[[], float],
    logger: logging.Logger,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/tasks")
    def get_tasks(detail: bool = False):
        """查看所有任务。"""
        return merged_task_snapshots(compact=not detail)

    @router.get("/api/tasks/{task_id}")
    def get_task(task_id: str):
        """查看任务状态"""
        task = task_detail_snapshot(tasks(), task_id, load_task_snapshots())
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        return task

    @router.post("/api/tasks/cancel", status_code=202)
    def post_task_cancel(params: TaskControlParams | None = None):
        from autotoken.core import cancel_signal

        params = params or TaskControlParams()
        task = _find_control_task_or_raise(tasks(), current_task_ids(), params)
        task_id = str(task.get("task_id") or "")
        status_error = task_control_status_error(task, "取消")
        if status_error:
            raise HTTPException(status_code=400, detail=status_error)
        cancel_event = task_cancel_signals().get(task_id)
        if cancel_event is not None:
            cancel_signal.request_cancel_event(cancel_event, f"手动停止 task={task_id[:8]}")
        else:
            cancel_signal.request_cancel(f"手动停止 task={task_id[:8]}")
        run_task_cancel_hooks(task_id)
        mark_task_cancel_requested(task)
        append_task_progress(task_id, task_cancel_requested_progress_event())
        return task_cancel_requested_response(task)

    @router.post("/api/tasks/skip-current", status_code=202)
    def post_task_skip_current(params: TaskControlParams | None = None):
        """请求 GoPay 批量任务跳过当前账号，并在安全点切换到下一个账号。"""
        params = params or TaskControlParams()
        task = _find_control_task_or_raise(
            tasks(),
            current_task_ids(),
            params,
            default_group=TASK_GROUP_GOPAY,
            command="gopay-bind",
        )
        task_id = str(task.get("task_id") or "")
        skip_signal = task_skip_signals().get(task_id)
        skip_error = gopay_skip_current_error(task, skip_signal)
        if skip_error:
            raise HTTPException(status_code=400, detail=skip_error)
        mark_task_skip_current_requested(task, skip_signal)
        append_task_progress(task_id, gopay_skip_current_progress_event())
        logger.info("[API] requested GoPay current-account skip: task=%s", task_id[:8])
        return gopay_skip_current_response(task)

    @router.post("/api/tasks/gopay/runtime-control", status_code=202)
    def post_gopay_runtime_control(params: GoPayRuntimeControlParams):
        """Hot-update GoPay controls for not-yet-started accounts in the current task."""
        task_params = TaskControlParams(task_id=params.task_id) if params.task_id else TaskControlParams()
        task = _find_control_task_or_raise(
            tasks(),
            current_task_ids(),
            task_params,
            default_group=TASK_GROUP_GOPAY,
            command="gopay-bind",
        )
        task_id = str(task.get("task_id") or "")
        status_error = task_control_status_error(task, "热切换")
        if status_error:
            raise HTTPException(status_code=400, detail=status_error)
        if task.get("command") != "gopay-bind":
            raise HTTPException(status_code=400, detail="当前任务不支持 GoPay 热切换")
        validate_list_payload_limit(
            params.account_emails,
            max_items=GOPAY_RUNTIME_CONTROL_MAX_EMAILS,
            label="GoPay 热切换账号",
        )

        provider_input = str(params.gopay_auto_signup_sms_provider or "").strip()
        control_update = update_gopay_runtime_control(
            task_runtime_controls(),
            task_runtime_controls_lock(),
            task_id,
            gopay_concurrency=(
                normalize_gopay_runtime_concurrency(params.gopay_concurrency, 1)
                if params.gopay_concurrency is not None
                else None
            ),
            sms_provider=normalize_gopay_auto_signup_sms_provider(provider_input) if provider_input else None,
            balance_poll_interval_seconds=(
                normalize_gopay_runtime_seconds(
                    params.gopay_balance_poll_interval_seconds,
                    default_gopay_wallet_balance_poll_interval_seconds(),
                    maximum=300.0,
                )
                if params.gopay_balance_poll_interval_seconds is not None
                else None
            ),
            transfer_balance_wait_seconds=(
                normalize_gopay_runtime_seconds(
                    params.gopay_transfer_balance_wait_seconds,
                    default_gopay_wallet_balance_wait_seconds(),
                    maximum=1800.0,
                )
                if params.gopay_transfer_balance_wait_seconds is not None
                else None
            ),
            account_emails=params.account_emails or [],
        )
        updates = control_update["updates"]
        added_emails = control_update["added_emails"]
        apply_gopay_runtime_control_public_updates(task, updates, added_emails)

        if not updates or set(updates) == {"version"}:
            raise HTTPException(status_code=400, detail="没有可应用的热切换内容")

        append_task_progress(task_id, gopay_runtime_control_progress_event(updates, added_emails))
        persist_task_snapshot(task)
        return {
            "message": "GoPay 热切换已应用",
            "task_id": task_id,
            "updates": updates,
        }

    return router
