import pytest
from fastapi import HTTPException

from autotoken.api_routes.task_actions import (
    CheckParams,
    CleanupParams,
    ReplaceParams,
    TaskParams,
    create_task_actions_router,
)
from autotoken.services.task_runtime import TASK_GROUP_QUOTA, TASK_GROUP_TEAM


def _routes(started):
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

    return {route.endpoint.__name__: route.endpoint for route in create_task_actions_router(start_task=start_task).routes}


def test_post_check_starts_quota_task_and_preserves_result_shape(monkeypatch):
    started = []
    monkeypatch.setattr("autotoken.manager.cmd_check", lambda include_standby=False: [{"email": "a@example.com"}])

    result = _routes(started)["post_check"](CheckParams(include_standby=True))

    assert result == {"task_id": "task-1", "command": "check", "params": {"include_standby": True}}
    assert started[0]["kwargs"]["task_group"] == TASK_GROUP_QUOTA
    assert started[0]["func"]() == {"exhausted": ["a@example.com"]}


def test_post_rotate_starts_team_task(monkeypatch):
    started = []
    monkeypatch.setattr("autotoken.manager.cmd_rotate", lambda target: {"target": target})

    result = _routes(started)["post_rotate"](TaskParams(target=7))

    assert result["command"] == "rotate"
    assert started[0]["params"] == {"target": 7}
    assert started[0]["args"] == (7,)
    assert started[0]["kwargs"]["task_group"] == TASK_GROUP_TEAM


def test_post_replace_requires_email():
    with pytest.raises(HTTPException) as exc_info:
        _routes([])["post_replace"](ReplaceParams(email=" "))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "email 不能为空"


def test_post_fill_personal_rejects_when_team_is_full(monkeypatch):
    monkeypatch.setattr("autotoken.manager.TEAM_SUB_ACCOUNT_HARD_CAP", 2)
    monkeypatch.setattr("autotoken.accounts.STATUS_ACTIVE", "active")
    monkeypatch.setattr("autotoken.accounts.STATUS_EXHAUSTED", "exhausted")
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"status": "active"}, {"status": "exhausted"}])

    with pytest.raises(HTTPException) as exc_info:
        _routes([])["post_fill"](TaskParams(target=5, leave_workspace=True))

    assert exc_info.value.status_code == 409
    assert "Team 子号已满 2/2" in exc_info.value.detail


def test_post_cleanup_starts_team_task(monkeypatch):
    started = []
    monkeypatch.setattr("autotoken.manager.cmd_cleanup", lambda max_seats=None: {"max_seats": max_seats})

    result = _routes(started)["post_cleanup"](CleanupParams(max_seats=3))

    assert result["command"] == "cleanup"
    assert started[0]["params"] == {"max_seats": 3}
    assert started[0]["args"] == (3,)
    assert started[0]["kwargs"]["task_group"] == TASK_GROUP_TEAM
