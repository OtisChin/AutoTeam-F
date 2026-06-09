import pytest
from fastapi import HTTPException

from autotoken.api_routes.gopay_pro_tasks import (
    GOPAY_PRO_BATCH_MAX_EMAILS,
    GoPayProBatchParams,
    GoPayProTaskParams,
    create_gopay_pro_tasks_router,
)
from autotoken.services.task_runtime import TASK_GROUP_GOPAY_PRO


def _routes(started, token_items=None):
    def start_task(command, func, params, *args, **kwargs):
        started.append(
            {
                "command": command,
                "func": func,
                "params": params,
                "args": args,
                "kwargs": kwargs,
            }
        )
        return {"task_id": "task-1", "command": command, "params": params}

    router = create_gopay_pro_tasks_router(
        task_kinds={"register", "harvest"},
        start_task=start_task,
        run_script_task=lambda *_args, **_kwargs: {"ok": True},
        run_batch_task=lambda *_args, **_kwargs: {"ok": True},
        account_token_items=lambda _emails: token_items or [],
    )
    return {route.endpoint.__name__: route.endpoint for route in router.routes}


def test_start_gopay_pro_task_rejects_unknown_kind():
    with pytest.raises(HTTPException) as exc_info:
        _routes([])["start_gopay_pro_task"](GoPayProTaskParams(kind="unknown"))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "不支持的 GoPay Pro 命令: unknown"


def test_start_gopay_pro_task_delegates_to_start_task():
    started = []

    result = _routes(started)["start_gopay_pro_task"](GoPayProTaskParams(kind="register"))

    assert result["command"] == "gopay-pro"
    assert started[0]["params"] == {"kind": "register"}
    assert started[0]["args"] == ("register",)
    assert started[0]["kwargs"]["task_group"] == TASK_GROUP_GOPAY_PRO
    assert started[0]["kwargs"]["pass_task_id"] is True


def test_start_gopay_pro_batch_resolves_token_items_and_delegates():
    started = []
    token_items = [{"email": "first@example.com"}, {"email": "second@example.com"}]

    result = _routes(started, token_items)["start_gopay_pro_batch"](
        GoPayProBatchParams(account_emails=["raw@example.com"], concurrency=2, max_attempts=4)
    )

    assert result["command"] == "gopay-pro-batch"
    assert started[0]["params"] == {
        "account_emails": ["first@example.com", "second@example.com"],
        "account_emails_count": 2,
        "concurrency": 2,
        "max_attempts": 4,
    }
    assert started[0]["args"] == (["first@example.com", "second@example.com"], 2, 4)
    assert started[0]["kwargs"]["task_group"] == TASK_GROUP_GOPAY_PRO
    assert started[0]["kwargs"]["pass_task_id"] is True


def test_start_gopay_pro_batch_rejects_too_many_raw_emails():
    with pytest.raises(HTTPException) as exc_info:
        _routes([])["start_gopay_pro_batch"](
            GoPayProBatchParams(
                account_emails=[f"user{index}@example.com" for index in range(GOPAY_PRO_BATCH_MAX_EMAILS + 1)]
            )
        )

    assert exc_info.value.status_code == 400
    assert "GoPay Pro 批量账号过多" in exc_info.value.detail
