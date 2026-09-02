"""Task snapshot compaction helpers for API polling and persistence."""

from __future__ import annotations

from typing import Any

TASK_LIST_PARAM_ALLOW_KEYS = {
    "account_count",
    "account_emails_count",
    "auto_register",
    "auto_register_count",
    "checkout_ui_mode",
    "count",
    "email",
    "emails_count",
    "kind",
    "link_type",
    "max_attempts",
    "mode",
    "phone_country_code",
    "proxy_label",
    "refresh_auth_session",
    "task_id",
    "timeout",
}

TASK_LIST_PROGRESS_DROP_KEYS = {
    "account_emails",
    "auth_session",
    "billing_info",
    "checkout",
    "checkout_url",
    "cookie_header",
    "raw",
    "removed_pool_emails",
    "screenshot_paths",
    "successful_emails",
}

TASK_LIST_RESULT_ALLOW_KEYS = {
    "auth_file",
    "concurrency",
    "email",
    "failed",
    "failure_stage",
    "max_attempts",
    "message",
    "missing",
    "exhausted",
    "network_error",
    "ok",
    "pending",
    "skipped",
    "status",
    "success",
    "successful",
    "total",
}


def task_public_snapshot(task: dict[str, Any] | None) -> dict[str, Any]:
    snapshot = dict(task or {})
    snapshot.pop("_group_lock_preacquired", None)
    return snapshot


def truncate_task_list_value(value: Any, *, max_string: int = 240) -> Any:
    if isinstance(value, str):
        return value if len(value) <= max_string else f"{value[:max_string]}..."
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        if len(value) <= 6 and all(not isinstance(item, (dict, list)) for item in value):
            return value
        return {"count": len(value)}
    if isinstance(value, dict):
        return {
            str(key): truncate_task_list_value(nested, max_string=120)
            for key, nested in list(value.items())[:12]
            if str(key) not in TASK_LIST_PROGRESS_DROP_KEYS
        }
    return str(value)


def compact_task_params(params: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(params, dict):
        return {}
    compact = {
        key: truncate_task_list_value(params.get(key))
        for key in TASK_LIST_PARAM_ALLOW_KEYS
        if key in params
    }
    for key in ("account_emails", "emails"):
        value = params.get(key)
        if isinstance(value, list):
            compact[f"{key}_count"] = len(value)
    return compact


def compact_task_progress(progress: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(progress, dict):
        return {}
    return {
        str(key): truncate_task_list_value(value)
        for key, value in progress.items()
        if str(key) not in TASK_LIST_PROGRESS_DROP_KEYS
    }


def compact_task_result(result: Any) -> Any:
    if not isinstance(result, dict):
        return truncate_task_list_value(result)
    return {
        key: truncate_task_list_value(result.get(key))
        for key in TASK_LIST_RESULT_ALLOW_KEYS
        if key in result
    }


def compact_setup_2fa_progress_events(progress_events: Any) -> list[dict[str, Any]]:
    if not isinstance(progress_events, list):
        return []
    compact: list[dict[str, Any]] = []
    for event in progress_events:
        if not isinstance(event, dict):
            continue
        if event.get("stage") != "account_2fa_progress":
            continue
        email = str(event.get("email") or "").strip().lower()
        status = str(event.get("status") or "").strip().lower()
        if not email or status not in {"enabled", "failed", "skipped"}:
            continue
        compact.append(
            {
                "stage": "account_2fa_progress",
                "email": email,
                "status": status,
                "reason": str(event.get("reason") or "").strip(),
            }
        )
    return compact


def compact_oauth_progress_events(progress_events: Any) -> list[dict[str, Any]]:
    if not isinstance(progress_events, list):
        return []
    compact: list[dict[str, Any]] = []
    for event in progress_events:
        if not isinstance(event, dict):
            continue
        if event.get("stage") != "account_login_done":
            continue
        email = str(event.get("email") or "").strip().lower()
        if not email:
            continue
        compact.append({"stage": "account_login_done", "email": email})
    return compact


def compact_progress_events_for_task(command: Any, progress_events: Any) -> list[dict[str, Any]]:
    command_text = str(command or "")
    if command_text == "setup-2fa":
        return compact_setup_2fa_progress_events(progress_events)
    if command_text == "login-batch" or command_text.startswith("login:"):
        return compact_oauth_progress_events(progress_events)
    return []


def task_list_snapshot(task: dict[str, Any] | None) -> dict[str, Any]:
    """Lightweight task snapshot for frequently polled task lists."""

    snapshot = task_public_snapshot(task)
    raw_params = snapshot.get("params")
    progress_events = snapshot.pop("progress_events", None)
    if isinstance(progress_events, list):
        snapshot["progress_event_count"] = len(progress_events)
        compact_progress_events = compact_progress_events_for_task(snapshot.get("command"), progress_events)
        if compact_progress_events:
            snapshot["progress_events"] = compact_progress_events
    snapshot["params"] = compact_task_params(snapshot.get("params"))
    if (
        snapshot.get("command") == "setup-2fa"
        and isinstance(raw_params, dict)
        and isinstance(raw_params.get("emails"), list)
    ):
        snapshot["params"]["emails"] = [
            str(email)
            for email in raw_params.get("emails") or []
            if str(email or "").strip()
        ]
    snapshot["progress"] = compact_task_progress(snapshot.get("progress"))
    snapshot["result"] = compact_task_result(snapshot.get("result"))
    if snapshot.get("error"):
        snapshot["error"] = truncate_task_list_value(snapshot.get("error"))
    return snapshot
