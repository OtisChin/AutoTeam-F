"""Task runtime rules shared by API adapters and tests."""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from autotoken.core.normalization import normalized_email
from autotoken.core.task_snapshots import task_list_snapshot, task_public_snapshot

TASK_GROUP_DEFAULT = "default"
TASK_GROUP_REGISTER = "register"
TASK_GROUP_BIND_CARD = "bind_card"
TASK_GROUP_GOPAY = "gopay"
TASK_GROUP_PAYPAL = "paypal"
TASK_GROUP_OAUTH = "oauth"
TASK_GROUP_QUOTA = "quota"
TASK_GROUP_TEAM = "team"

COMMAND_TASK_GROUPS = {
    "register": TASK_GROUP_REGISTER,
    "add": TASK_GROUP_REGISTER,
    "bind-card": TASK_GROUP_BIND_CARD,
    "gopay-bind": TASK_GROUP_GOPAY,
    "paypal": TASK_GROUP_PAYPAL,
    "login": TASK_GROUP_OAUTH,
    "login-batch": TASK_GROUP_OAUTH,
    "refresh-quota": TASK_GROUP_QUOTA,
    "check": TASK_GROUP_QUOTA,
    "rotate": TASK_GROUP_TEAM,
    "replace": TASK_GROUP_TEAM,
    "fill": TASK_GROUP_TEAM,
    "fill-personal": TASK_GROUP_TEAM,
    "cleanup": TASK_GROUP_TEAM,
}

EXTENDED_PROGRESS_COMMANDS = {"register"}
DEFAULT_PROGRESS_EVENT_LIMIT = 300
EXTENDED_PROGRESS_EVENT_LIMIT = 2000
CancelHook = Callable[[], None]
CancelHookErrorHandler = Callable[[str, str], None]
RUNNING_TASK_STATUSES = {"running", "pending"}


@dataclass(frozen=True)
class TaskControlLookupResult:
    task: dict | None = None
    status_code: int = 200
    detail: str = ""

    @property
    def found(self) -> bool:
        return self.task is not None


@dataclass(frozen=True)
class TaskStartSlot:
    task_group: str
    lock: Any | None = None
    acquired: bool = False
    conflict: bool = False


@dataclass(frozen=True)
class TaskRunSlot:
    task_group: str
    lock: Any
    preacquired: bool = False


def normalize_task_group(task_group: str | None, command: str = "") -> str:
    explicit = str(task_group or "").strip()
    if explicit:
        return explicit
    raw_command = str(command or "").strip()
    if raw_command.startswith("login:"):
        return TASK_GROUP_OAUTH
    return COMMAND_TASK_GROUPS.get(raw_command, TASK_GROUP_DEFAULT)


def task_group_lock(
    task_group_locks: dict[str, Any],
    task_group: str | None,
    *,
    lock_factory: Callable[[], Any],
) -> Any:
    group = str(task_group or TASK_GROUP_DEFAULT)
    lock = task_group_locks.get(group)
    if lock is None:
        lock = lock_factory()
        task_group_locks[group] = lock
    return lock


def acquire_task_start_slot(
    task_group_locks: dict[str, Any],
    task_group: str | None,
    *,
    exclusive: bool = True,
    lock_factory: Callable[[], Any],
) -> TaskStartSlot:
    normalized_group = str(task_group or TASK_GROUP_DEFAULT)
    if not exclusive:
        return TaskStartSlot(task_group=normalized_group)
    lock = task_group_lock(task_group_locks, normalized_group, lock_factory=lock_factory)
    if not lock.acquire(blocking=False):
        return TaskStartSlot(task_group=normalized_group, lock=lock, conflict=True)
    return TaskStartSlot(task_group=normalized_group, lock=lock, acquired=True)


def release_task_start_slot(slot: TaskStartSlot) -> None:
    if slot.acquired and slot.lock is not None:
        slot.lock.release()


def acquire_task_run_slot(task: dict, task_group: str | None, lock: Any) -> TaskRunSlot:
    group = str(task_group or TASK_GROUP_DEFAULT)
    preacquired = bool(task.pop("_group_lock_preacquired", False))
    if not preacquired:
        lock.acquire()
    return TaskRunSlot(task_group=group, lock=lock, preacquired=preacquired)


def release_task_run_slot(slot: TaskRunSlot) -> None:
    slot.lock.release()


def rollback_task_start(
    tasks: dict[str, dict],
    task_id: str,
    start_slot: TaskStartSlot,
    *,
    skip_signals: dict[str, Any],
    cancel_signals: dict[str, Any],
    cancel_hooks: dict[str, list[CancelHook]],
    cancel_hooks_lock: Any,
    controls: dict[str, dict[str, Any]],
    controls_lock: Any,
) -> dict | None:
    release_task_start_slot(start_slot)
    removed = tasks.pop(str(task_id or ""), None)
    clear_task_runtime_state(
        task_id,
        skip_signals=skip_signals,
        cancel_signals=cancel_signals,
        cancel_hooks=cancel_hooks,
        cancel_hooks_lock=cancel_hooks_lock,
        controls=controls,
        controls_lock=controls_lock,
    )
    return removed


def launch_task_thread(
    *,
    thread_factory: Callable[..., Any],
    target: Callable[..., Any],
    task_id: str,
    func: Callable[..., Any],
    pass_task_id: bool = False,
    args: tuple = (),
    kwargs: dict | None = None,
    on_start_error: Callable[[], None] | None = None,
) -> Any:
    try:
        thread = thread_factory(
            target=target,
            args=(task_id, func, pass_task_id, *tuple(args or ())),
            kwargs=kwargs or {},
            daemon=True,
        )
        thread.start()
        return thread
    except Exception:
        if on_start_error:
            on_start_error()
        raise


def bind_task_thread_context(
    context: Any,
    *,
    task_id: str,
    task_group: str,
    cancel_event: Any,
    set_cancel_event: Callable[[Any], None],
) -> None:
    context.task_id = task_id
    context.task_group = task_group
    context.cancel_event = cancel_event
    set_cancel_event(cancel_event)


def clear_task_thread_context(
    context: Any,
    *,
    clear_cancel_event: Callable[[], None],
    extra_attrs: tuple[str, ...] = (),
) -> None:
    clear_cancel_event()
    for attr in ("task_id", "task_group", "cancel_event", *extra_attrs):
        try:
            delattr(context, attr)
        except AttributeError:
            pass


def running_task_for_group(tasks: dict[str, dict], current_task_ids: dict[str, str | None], task_group: str | None) -> dict:
    group = str(task_group or TASK_GROUP_DEFAULT)
    task_id = current_task_ids.get(group)
    return tasks.get(task_id or "", {}) if task_id else {}


def find_control_task(
    tasks: dict[str, dict],
    current_task_ids: dict[str, str | None],
    *,
    task_id: str | None = "",
    task_group: str | None = "",
    default_group: str | None = None,
    command: str | None = None,
) -> TaskControlLookupResult:
    requested_id = str(task_id or "").strip()
    if requested_id:
        task = tasks.get(requested_id)
        if not task:
            return TaskControlLookupResult(status_code=404, detail="任务不存在")
        return TaskControlLookupResult(task=task)

    requested_group = str(task_group or default_group or "").strip()
    if requested_group:
        task = running_task_for_group(tasks, current_task_ids, requested_group)
        if task:
            return TaskControlLookupResult(task=task)

    running = [
        task
        for task in tasks.values()
        if task.get("status") in RUNNING_TASK_STATUSES
        and (not command or task.get("command") == command)
        and (not requested_group or task.get("task_group") == requested_group)
    ]
    if not running:
        return TaskControlLookupResult(status_code=404, detail="当前没有正在运行的任务")
    task = sorted(running, key=lambda item: item.get("started_at") or item.get("created_at") or 0, reverse=True)[0]
    return TaskControlLookupResult(task=task)


def task_control_status_error(task: dict, action: str) -> str:
    if task.get("status") in RUNNING_TASK_STATUSES:
        return ""
    return f"任务当前状态 {task.get('status')} 无法{action}"


def gopay_skip_current_error(task: dict, skip_signal: Any | None) -> str:
    status_error = task_control_status_error(task, "跳过")
    if status_error:
        return status_error
    if task.get("command") != "gopay-bind":
        return "当前任务不支持跳过账号"
    params = task.get("params") if isinstance(task.get("params"), dict) else {}
    account_emails = params.get("account_emails") if isinstance(params.get("account_emails"), list) else []
    if len(account_emails) <= 1:
        return "当前 GoPay 任务没有下一个账号可切换"
    if skip_signal is None:
        return "当前 GoPay 任务不支持跳过账号"
    return ""


def mark_task_cancel_requested(task: dict) -> None:
    task["cancel_requested"] = True


def mark_task_skip_current_requested(task: dict, skip_signal: Any) -> None:
    skip_signal.set()
    task["skip_current_requested"] = True


TASK_CANCEL_REQUESTED_MESSAGE = "已请求立即中止，正在停止提交新步骤并打断当前可中断等待"
TASK_CANCEL_REQUESTED_PROGRESS_MESSAGE = "已请求立即中止任务，正在停止提交新步骤并打断当前可中断等待"
GOPAY_SKIP_CURRENT_RESPONSE_MESSAGE = "已请求跳过当前账号，等待切换下一个账号"
GOPAY_SKIP_CURRENT_PROGRESS_MESSAGE = "已请求跳过当前账号，等待当前步骤在安全点退出后切换下一个账号"


def task_control_response(task: dict, message: str) -> dict:
    return {
        "message": message,
        "task_id": str(task.get("task_id") or ""),
        "command": task.get("command"),
        "task_group": task.get("task_group"),
    }


def task_cancel_requested_progress_event() -> dict:
    return {
        "stage": "task_cancel_requested",
        "message": TASK_CANCEL_REQUESTED_PROGRESS_MESSAGE,
    }


def task_cancel_requested_response(task: dict) -> dict:
    return task_control_response(task, TASK_CANCEL_REQUESTED_MESSAGE)


def gopay_skip_current_progress_event() -> dict:
    return {
        "stage": "gopay_skip_current_requested",
        "message": GOPAY_SKIP_CURRENT_PROGRESS_MESSAGE,
    }


def gopay_skip_current_response(task: dict) -> dict:
    return task_control_response(task, GOPAY_SKIP_CURRENT_RESPONSE_MESSAGE)


def apply_gopay_runtime_control_public_updates(task: dict, updates: dict[str, Any], added_emails: list[str]) -> None:
    if added_emails:
        public_params = task.get("params") if isinstance(task.get("params"), dict) else {}
        existing = public_params.get("account_emails") if isinstance(public_params.get("account_emails"), list) else []
        merged: list[str] = []
        seen_public: set[str] = set()
        for raw_email in [*existing, *added_emails]:
            email = _normalized_email(raw_email)
            if email and email not in seen_public:
                seen_public.add(email)
                merged.append(email)
        public_params["account_emails"] = merged
        task["params"] = public_params
        updates["added_account_emails"] = added_emails

    runtime_keys = {
        "gopay_concurrency",
        "gopay_auto_signup_sms_provider",
        "gopay_balance_poll_interval_seconds",
        "gopay_transfer_balance_wait_seconds",
    }
    if not runtime_keys.intersection(updates):
        return
    public_params = task.get("params") if isinstance(task.get("params"), dict) else {}
    for key in runtime_keys:
        if key in updates:
            public_params[key] = updates[key]
    task["params"] = public_params


def gopay_runtime_control_update_message(updates: dict[str, Any], added_emails: list[str]) -> str:
    return (
        "GoPay 热切换已应用："
        + "，".join(
            [
                f"并发 {updates['gopay_concurrency']}" if "gopay_concurrency" in updates else "",
                f"短信服务商 {updates['gopay_auto_signup_sms_provider']}" if "gopay_auto_signup_sms_provider" in updates else "",
                f"余额查询间隔 {updates['gopay_balance_poll_interval_seconds']}s"
                if "gopay_balance_poll_interval_seconds" in updates
                else "",
                f"转账到账等待 {updates['gopay_transfer_balance_wait_seconds']}s"
                if "gopay_transfer_balance_wait_seconds" in updates
                else "",
                f"追加账号 {len(added_emails)} 个" if added_emails else "",
            ]
        ).strip("，")
    )


def gopay_runtime_control_progress_event(updates: dict[str, Any], added_emails: list[str]) -> dict:
    return {
        "stage": "gopay_runtime_control_updated",
        "updates": updates,
        "message": gopay_runtime_control_update_message(updates, added_emails),
        "level": "success",
    }


def busy_task_detail(
    default_message: str,
    tasks: dict[str, dict],
    current_task_ids: dict[str, str | None],
    *,
    current_task_id: str | None,
    task_group: str | None = None,
    special_running_task: dict | None = None,
) -> dict:
    if special_running_task:
        return {"message": default_message, "running_task": dict(special_running_task)}
    running = running_task_for_group(tasks, current_task_ids, task_group) if task_group else tasks.get(current_task_id or "", {})
    return {
        "message": default_message,
        "running_task": {
            "task_id": running.get("task_id") or current_task_id,
            "command": running.get("command", "unknown"),
            "task_group": running.get("task_group") or task_group,
            "started_at": running.get("started_at"),
        },
    }


def current_task_id_for_group(
    *,
    thread_task_id: str | None = None,
    fallback_task_id: str | None = None,
    current_task_ids: dict[str, str | None],
    current_task_id: str | None,
    task_group: str | None = None,
) -> str | None:
    if thread_task_id:
        return thread_task_id
    if fallback_task_id:
        return fallback_task_id
    if task_group:
        return current_task_ids.get(str(task_group or TASK_GROUP_DEFAULT))
    return current_task_id


def activate_current_task_index(current_task_ids: dict[str, str | None], task_group: str, task_id: str) -> str:
    current_task_ids[str(task_group or TASK_GROUP_DEFAULT)] = task_id
    return task_id


def clear_current_task_index(
    current_task_ids: dict[str, str | None],
    *,
    current_task_id: str | None,
    task_group: str,
    task_id: str,
) -> str | None:
    next_current_task_id = None if current_task_id == task_id else current_task_id
    group = str(task_group or TASK_GROUP_DEFAULT)
    if current_task_ids.get(group) == task_id:
        current_task_ids[group] = None
    return next_current_task_id


def create_task_record(
    command: str,
    params: dict | None,
    *,
    task_group: str | None = None,
    exclusive: bool = True,
    task_id: str | None = None,
    now: float | None = None,
    group_lock_preacquired: bool = False,
) -> dict:
    task = {
        "task_id": str(task_id or uuid.uuid4().hex[:12]),
        "command": command,
        "task_group": normalize_task_group(task_group, command),
        "params": params or {},
        "exclusive": exclusive,
        "status": "pending",
        "created_at": time.time() if now is None else float(now),
        "started_at": None,
        "finished_at": None,
        "result": None,
        "error": None,
        "progress": None,
        "progress_events": [],
    }
    if group_lock_preacquired:
        task["_group_lock_preacquired"] = True
    return task


def prepare_task_start(
    tasks: dict[str, dict],
    cancel_signals: dict[str, Any],
    command: str,
    params: dict | None,
    *,
    task_group: str | None = None,
    exclusive: bool = True,
    group_lock_preacquired: bool = False,
    cancel_event_factory: Callable[[], Any],
    task_id: str | None = None,
    now: float | None = None,
    max_history: int,
) -> dict:
    task = create_task_record(
        command,
        params,
        task_group=task_group,
        exclusive=exclusive,
        task_id=task_id,
        now=now,
        group_lock_preacquired=group_lock_preacquired,
    )
    normalized_task_id = str(task["task_id"])
    tasks[normalized_task_id] = task
    cancel_signals[normalized_task_id] = cancel_event_factory()
    prune_task_history(tasks, max_history)
    return task


def ensure_task_cancel_event(
    cancel_signals: dict[str, Any],
    task_id: str,
    *,
    cancel_event_factory: Callable[[], Any],
) -> Any:
    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id:
        return cancel_event_factory()
    cancel_event = cancel_signals.get(normalized_task_id)
    if cancel_event is None:
        cancel_event = cancel_event_factory()
        cancel_signals[normalized_task_id] = cancel_event
    return cancel_event


def runtime_control(
    controls: dict[str, dict[str, Any]],
    lock: Any,
    task_id: str,
    *,
    create: bool = False,
) -> dict[str, Any]:
    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id:
        return {}
    with lock:
        if create:
            return controls.setdefault(normalized_task_id, {})
        control = controls.get(normalized_task_id)
        return control if isinstance(control, dict) else {}


def init_gopay_runtime_control(
    controls: dict[str, dict[str, Any]],
    lock: Any,
    task_id: str,
    *,
    gopay_concurrency: int,
    sms_provider: str,
    account_emails: list[str],
    balance_poll_interval_seconds: float,
    transfer_balance_wait_seconds: float,
) -> dict[str, Any]:
    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id:
        return {}
    normalized_accounts = _normalized_unique_emails(account_emails)
    with lock:
        control = controls.setdefault(normalized_task_id, {})
        control.setdefault("pending_account_emails", [])
        control.setdefault("all_account_emails", normalized_accounts[:])
        control.setdefault("gopay_concurrency", gopay_concurrency)
        control.setdefault("gopay_auto_signup_sms_provider", sms_provider)
        control.setdefault("gopay_balance_poll_interval_seconds", balance_poll_interval_seconds)
        control.setdefault("gopay_transfer_balance_wait_seconds", transfer_balance_wait_seconds)
        control["version"] = int(control.get("version") or 0)
        return dict(control)


def update_gopay_runtime_control(
    controls: dict[str, dict[str, Any]],
    lock: Any,
    task_id: str,
    *,
    gopay_concurrency: int | None = None,
    sms_provider: str | None = None,
    balance_poll_interval_seconds: float | None = None,
    transfer_balance_wait_seconds: float | None = None,
    account_emails: list[str] | None = None,
) -> dict[str, Any]:
    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id:
        return {"control": {}, "updates": {}, "added_emails": []}
    updates: dict[str, Any] = {}
    added_emails: list[str] = []
    with lock:
        control = controls.setdefault(normalized_task_id, {})
        control.setdefault("pending_account_emails", [])
        control.setdefault("all_account_emails", [])

        if gopay_concurrency is not None:
            control["gopay_concurrency"] = gopay_concurrency
            updates["gopay_concurrency"] = control["gopay_concurrency"]
        if sms_provider:
            control["gopay_auto_signup_sms_provider"] = sms_provider
            updates["gopay_auto_signup_sms_provider"] = sms_provider
        if balance_poll_interval_seconds is not None:
            control["gopay_balance_poll_interval_seconds"] = balance_poll_interval_seconds
            updates["gopay_balance_poll_interval_seconds"] = control["gopay_balance_poll_interval_seconds"]
        if transfer_balance_wait_seconds is not None:
            control["gopay_transfer_balance_wait_seconds"] = transfer_balance_wait_seconds
            updates["gopay_transfer_balance_wait_seconds"] = control["gopay_transfer_balance_wait_seconds"]

        all_emails = control["all_account_emails"] if isinstance(control.get("all_account_emails"), list) else []
        pending = control["pending_account_emails"] if isinstance(control.get("pending_account_emails"), list) else []
        seen = {_normalized_email(email) for email in all_emails}
        for email in _normalized_unique_emails(account_emails or []):
            if email in seen:
                continue
            seen.add(email)
            all_emails.append(email)
            pending.append(email)
            added_emails.append(email)
        control["all_account_emails"] = all_emails
        control["pending_account_emails"] = pending
        control["version"] = int(control.get("version") or 0) + 1
        updates["version"] = control["version"]
        return {"control": dict(control), "updates": updates, "added_emails": added_emails}


def drain_gopay_pending_account_emails(
    controls: dict[str, dict[str, Any]],
    lock: Any,
    task_id: str,
    existing_emails: set[str],
) -> list[str]:
    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id:
        return []
    with lock:
        control = controls.get(normalized_task_id)
        if not isinstance(control, dict):
            return []
        pending = control.get("pending_account_emails")
        if not isinstance(pending, list) or not pending:
            return []
        control["pending_account_emails"] = []
    drained: list[str] = []
    for raw_email in pending:
        email = _normalized_email(raw_email)
        if email and email not in existing_emails:
            existing_emails.add(email)
            drained.append(email)
    return drained


def clear_task_runtime_state(
    task_id: str,
    *,
    skip_signals: dict[str, Any],
    cancel_signals: dict[str, Any],
    cancel_hooks: dict[str, list[CancelHook]],
    cancel_hooks_lock: Any,
    controls: dict[str, dict[str, Any]],
    controls_lock: Any,
) -> None:
    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id:
        return
    skip_signals.pop(normalized_task_id, None)
    cancel_signals.pop(normalized_task_id, None)
    clear_task_cancel_hooks(cancel_hooks, cancel_hooks_lock, normalized_task_id)
    with controls_lock:
        controls.pop(normalized_task_id, None)


def _normalized_email(value: Any) -> str:
    return normalized_email(value)


def _normalized_unique_emails(values: list[str] | tuple[str, ...]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        email = _normalized_email(raw)
        if email and email not in seen:
            seen.add(email)
            normalized.append(email)
    return normalized


def prune_task_history(tasks: dict[str, dict], max_history: int) -> list[str]:
    if len(tasks) <= max_history:
        return []
    deleted: list[str] = []
    sorted_ids = sorted(tasks, key=lambda task_id: tasks[task_id]["created_at"])
    for task_id in sorted_ids[: len(tasks) - max_history]:
        if tasks[task_id]["status"] in ("completed", "failed"):
            del tasks[task_id]
            deleted.append(task_id)
    return deleted


def mark_task_running(task: dict, *, now: float | None = None) -> None:
    task["status"] = "running"
    task["started_at"] = time.time() if now is None else float(now)


def mark_task_prestart_cancelled(task: dict, *, now: float | None = None) -> None:
    task["status"] = "cancelled"
    task["result"] = {"status": "cancelled", "message": "任务启动前已取消"}
    task["finished_at"] = time.time() if now is None else float(now)


def mark_task_run_prestart_cancelled(
    task: dict,
    task_id: str,
    *,
    current_task_ids: dict[str, str | None] | None = None,
    current_task_id: str | None = None,
    task_group: str | None = None,
    now: float | None = None,
) -> str | None:
    mark_task_prestart_cancelled(task, now=now)
    if current_task_ids is None or task_group is None:
        return current_task_id
    return clear_current_task_index(
        current_task_ids,
        current_task_id=current_task_id,
        task_group=task_group,
        task_id=task_id,
    )


def mark_task_completed(task: dict, result: Any, *, is_cancelled: bool = False) -> None:
    task["status"] = "cancelled" if is_cancelled else "completed"
    task["result"] = result


def mark_task_failed(task: dict, error: BaseException, *, is_cancelled: bool = False) -> None:
    task["status"] = "cancelled" if is_cancelled else "failed"
    task_result = getattr(error, "task_result", None)
    if task_result is not None:
        task["result"] = task_result
    task["error"] = str(error)


def mark_task_finished(task: dict, *, now: float | None = None) -> None:
    task["finished_at"] = time.time() if now is None else float(now)


def mark_task_run_finished(
    task: dict,
    task_id: str,
    *,
    current_task_ids: dict[str, str | None] | None = None,
    current_task_id: str | None = None,
    task_group: str | None = None,
    now: float | None = None,
) -> str | None:
    mark_task_finished(task, now=now)
    if current_task_ids is None or task_group is None:
        return current_task_id
    return clear_current_task_index(
        current_task_ids,
        current_task_id=current_task_id,
        task_group=task_group,
        task_id=task_id,
    )


def execute_task_callable(
    task: dict,
    task_id: str,
    func: Callable[..., Any],
    args: tuple = (),
    kwargs: dict | None = None,
    *,
    pass_task_id: bool = False,
    is_cancelled: Callable[[], bool],
) -> BaseException | None:
    call_kwargs = kwargs or {}
    try:
        result = func(task_id, *args, **call_kwargs) if pass_task_id else func(*args, **call_kwargs)
        mark_task_completed(task, result, is_cancelled=is_cancelled())
        return None
    except Exception as exc:
        mark_task_failed(task, exc, is_cancelled=is_cancelled())
        return exc


def process_is_running(pid: int | None, *, current_pid: int | None = None) -> bool:
    try:
        value = int(pid or 0)
    except Exception:
        return False
    if value <= 0:
        return False
    current = os.getpid() if current_pid is None else int(current_pid or 0)
    if value == current:
        return True

    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            process_query_limited_information = 0x1000
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel32.GetExitCodeProcess.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            handle = kernel32.OpenProcess(process_query_limited_information, False, value)
            if not handle:
                return False
            try:
                exit_code = wintypes.DWORD()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return False
                return exit_code.value == 259  # STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False

    try:
        os.kill(value, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


def append_task_progress_event(
    task: dict,
    progress: dict | None,
    *,
    now: float | None = None,
    event_id: str | None = None,
    worker_label: str = "",
    worker_index: int = 0,
) -> dict:
    timestamp = time.time() if now is None else float(now)
    progress_data = dict(progress or {})
    normalized_worker_label = str(worker_label or "").strip()
    if normalized_worker_label:
        progress_data.setdefault("worker", normalized_worker_label)
        progress_data.setdefault("worker_label", normalized_worker_label)
        if worker_index > 0:
            progress_data.setdefault("worker_index", worker_index)
        message = str(progress_data.get("message") or "").strip()
        if message and not re.match(r"^\[worker-\d+\]\s", message):
            progress_data["message"] = f"[{normalized_worker_label}] {message}"

    event = {
        **progress_data,
        "event_id": event_id or uuid.uuid4().hex[:12],
        "updated_at": timestamp,
    }
    task["progress"] = {
        **(task.get("progress") or {}),
        **event,
    }
    progress_events = task.setdefault("progress_events", [])
    progress_events.append(event)
    max_progress_events = (
        EXTENDED_PROGRESS_EVENT_LIMIT
        if str(task.get("command") or "") in EXTENDED_PROGRESS_COMMANDS
        else DEFAULT_PROGRESS_EVENT_LIMIT
    )
    if len(progress_events) > max_progress_events:
        del progress_events[: len(progress_events) - max_progress_events]
    return event


def append_live_task_progress(
    live_tasks: dict[str, dict],
    task_id: str | None,
    progress: dict | None,
    *,
    worker_label: str = "",
    worker_index: int = 0,
) -> dict | None:
    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id:
        return None
    task = live_tasks.get(normalized_task_id)
    if not task:
        return None
    append_task_progress_event(task, progress, worker_label=worker_label, worker_index=worker_index)
    return task


def register_task_cancel_hook(
    cancel_hooks: dict[str, list[CancelHook]],
    cancel_signals: dict[str, Any],
    lock: Any,
    task_id: str,
    hook: CancelHook,
    *,
    on_error: CancelHookErrorHandler | None = None,
) -> Callable[[], None]:
    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id or not callable(hook):
        return lambda: None
    with lock:
        cancel_hooks.setdefault(normalized_task_id, []).append(hook)
        cancel_event = cancel_signals.get(normalized_task_id)
        already_cancelled = bool(cancel_event and cancel_event.is_set())

    def unregister() -> None:
        with lock:
            hooks = cancel_hooks.get(normalized_task_id)
            if not hooks:
                return
            try:
                hooks.remove(hook)
            except ValueError:
                return
            if not hooks:
                cancel_hooks.pop(normalized_task_id, None)

    if already_cancelled:
        _run_cancel_hook(hook, normalized_task_id, "late_registration", on_error=on_error)
        unregister()
    return unregister


def run_task_cancel_hooks(
    cancel_hooks: dict[str, list[CancelHook]],
    lock: Any,
    task_id: str,
    *,
    on_error: CancelHookErrorHandler | None = None,
) -> int:
    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id:
        return 0
    with lock:
        hooks = list(cancel_hooks.pop(normalized_task_id, []))
    for hook in hooks:
        _run_cancel_hook(hook, normalized_task_id, "cancel", on_error=on_error)
    return len(hooks)


def clear_task_cancel_hooks(cancel_hooks: dict[str, list[CancelHook]], lock: Any, task_id: str) -> None:
    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id:
        return
    with lock:
        cancel_hooks.pop(normalized_task_id, None)


def _run_cancel_hook(
    hook: CancelHook,
    task_id: str,
    stage: str,
    *,
    on_error: CancelHookErrorHandler | None,
) -> None:
    try:
        hook()
    except Exception:
        if on_error:
            on_error(task_id, stage)


def interrupted_task_snapshot(data: dict, *, now: float | None = None, event_id: str | None = None) -> dict:
    timestamp = now or time.time()
    snapshot = dict(data or {})
    snapshot["status"] = "cancelled"
    snapshot["finished_at"] = timestamp
    snapshot["error"] = "后端已重启，旧任务已中断"
    event = {
        "stage": "task_interrupted_on_startup",
        "message": "后端已重启，旧任务已中断，可重新提交任务",
        "event_id": event_id or uuid.uuid4().hex[:12],
        "updated_at": timestamp,
    }
    snapshot["progress"] = {**(snapshot.get("progress") or {}), **event}
    progress_events = snapshot.get("progress_events")
    if isinstance(progress_events, list):
        progress_events = [*progress_events, event]
        if len(progress_events) > 300:
            progress_events = progress_events[-300:]
    else:
        progress_events = [event]
    snapshot["progress_events"] = progress_events
    return snapshot


def persist_task_snapshot(task: dict | None, *, owner_pid: int | None = None) -> None:
    if not task or not task.get("task_id"):
        return
    from autotoken.storage import sqlite_store

    snapshot = task_public_snapshot(task)
    sqlite_store.initialize()
    with sqlite_store.connect() as conn:
        conn.execute(
            """
            INSERT INTO task_snapshots(
                task_id, command, task_group, status, created_at, started_at,
                finished_at, owner_pid, data, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s','now'))
            ON CONFLICT(task_id) DO UPDATE SET
                command=excluded.command,
                task_group=excluded.task_group,
                status=excluded.status,
                started_at=excluded.started_at,
                finished_at=excluded.finished_at,
                owner_pid=excluded.owner_pid,
                data=excluded.data,
                updated_at=excluded.updated_at
            """,
            (
                str(snapshot.get("task_id") or ""),
                str(snapshot.get("command") or ""),
                str(snapshot.get("task_group") or TASK_GROUP_DEFAULT),
                str(snapshot.get("status") or "pending"),
                float(snapshot.get("created_at") or time.time()),
                snapshot.get("started_at"),
                snapshot.get("finished_at"),
                os.getpid() if owner_pid is None else owner_pid,
                json.dumps(snapshot, ensure_ascii=False),
            ),
        )


def cancel_orphaned_task_snapshots(
    *,
    process_checker: Callable[[int | None], bool] = process_is_running,
    now: float | None = None,
) -> int:
    from autotoken.storage import sqlite_store

    sqlite_store.initialize()
    with sqlite_store.connect() as conn:
        rows = conn.execute(
            """
            SELECT task_id, owner_pid, data
            FROM task_snapshots
            WHERE status IN ('running', 'pending')
            """
        ).fetchall()
        cancelled = 0
        timestamp = time.time() if now is None else float(now)
        for row in rows:
            owner_pid = row["owner_pid"]
            if process_checker(owner_pid):
                continue
            try:
                data = json.loads(row["data"] or "{}")
            except Exception:
                data = {}
            if not isinstance(data, dict):
                data = {}
            data.setdefault("task_id", row["task_id"])
            data = interrupted_task_snapshot(data, now=timestamp)
            conn.execute(
                """
                UPDATE task_snapshots
                SET status = 'cancelled',
                    finished_at = ?,
                    data = ?,
                    updated_at = strftime('%s','now')
                WHERE task_id = ?
                """,
                (timestamp, json.dumps(data, ensure_ascii=False), row["task_id"]),
            )
            cancelled += 1
        return cancelled


def load_task_snapshots(
    limit: int,
    *,
    process_checker: Callable[[int | None], bool] = process_is_running,
    now: float | None = None,
) -> list[dict]:
    from autotoken.storage import sqlite_store

    sqlite_store.initialize()
    with sqlite_store.connect() as conn:
        rows = conn.execute(
            """
            SELECT task_id, owner_pid, status, data
            FROM task_snapshots
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        tasks = []
        stale_updates = []
        timestamp = time.time() if now is None else float(now)
        for row in rows:
            try:
                data = json.loads(row["data"] or "{}")
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            data.setdefault("task_id", row["task_id"])
            status = str(row["status"] or data.get("status") or "")
            if status in ("running", "pending") and not process_checker(row["owner_pid"]):
                data = interrupted_task_snapshot(data, now=timestamp)
                stale_updates.append((json.dumps(data, ensure_ascii=False), row["task_id"], timestamp))
            if data.get("task_id"):
                tasks.append(data)
        for data_json, task_id, finished_at in stale_updates:
            conn.execute(
                """
                UPDATE task_snapshots
                SET status = 'cancelled',
                    finished_at = ?,
                    data = ?,
                    updated_at = strftime('%s','now')
                WHERE task_id = ?
                """,
                (finished_at, data_json, task_id),
            )
        return tasks


def task_detail_snapshot(live_tasks: dict[str, dict], task_id: str, persisted_snapshots: list[dict] | tuple[dict, ...]) -> dict | None:
    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id:
        return None
    task = live_tasks.get(normalized_task_id)
    if task:
        return task_public_snapshot(task)
    for snapshot in persisted_snapshots or []:
        if str(snapshot.get("task_id") or "") == normalized_task_id:
            return snapshot
    return None


def merged_task_snapshots(
    live_tasks: dict[str, dict],
    *,
    limit: int,
    compact: bool = False,
    process_checker: Callable[[int | None], bool] = process_is_running,
) -> list[dict]:
    snapshot_fn = task_list_snapshot if compact else task_public_snapshot
    merged = {
        str(task.get("task_id") or ""): snapshot_fn(task)
        for task in load_task_snapshots(limit, process_checker=process_checker)
    }
    for task_id, task in live_tasks.items():
        merged[str(task_id)] = snapshot_fn(task)
    return sorted(
        [task for task in merged.values() if task.get("task_id")],
        key=lambda task: float(task.get("created_at") or 0),
        reverse=True,
    )
