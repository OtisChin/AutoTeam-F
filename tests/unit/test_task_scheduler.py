import time

import pytest
from fastapi import HTTPException

from autoteam import api


def _reset_task_scheduler(monkeypatch):
    monkeypatch.setattr(api, "_tasks", {})
    monkeypatch.setattr(api, "_task_group_locks", {})
    monkeypatch.setattr(api, "_current_task_ids", {})
    monkeypatch.setattr(api, "_task_cancel_signals", {})
    monkeypatch.setattr(api, "_task_skip_signals", {})
    monkeypatch.setattr(api, "_current_task_id", None)


def _wait_for(predicate, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_start_task_allows_different_task_groups_to_run_concurrently(monkeypatch):
    _reset_task_scheduler(monkeypatch)
    release = api.threading.Event()
    started = []

    def run_task(name):
        started.append(name)
        release.wait(2)
        return {"name": name}

    register = api._start_task("register", run_task, {}, "register", task_group=api.TASK_GROUP_REGISTER)
    gopay = api._start_task("gopay-bind", run_task, {}, "gopay", task_group=api.TASK_GROUP_GOPAY)

    try:
        assert _wait_for(lambda: register["status"] == "running" and gopay["status"] == "running")
        assert sorted(started) == ["gopay", "register"]
    finally:
        release.set()

    assert _wait_for(lambda: register["status"] == "completed" and gopay["status"] == "completed")


def test_start_task_rejects_second_task_in_same_group(monkeypatch):
    _reset_task_scheduler(monkeypatch)
    release = api.threading.Event()

    def run_task():
        release.wait(2)
        return {"ok": True}

    first = api._start_task("register", run_task, {}, task_group=api.TASK_GROUP_REGISTER)
    try:
        with pytest.raises(HTTPException) as exc:
            api._start_task("register", lambda: {}, {}, task_group=api.TASK_GROUP_REGISTER)
        assert exc.value.status_code == 409
        assert _wait_for(lambda: first["status"] == "running")
    finally:
        release.set()

    assert _wait_for(lambda: first["status"] == "completed")


def test_cancel_targets_only_the_requested_task(monkeypatch):
    _reset_task_scheduler(monkeypatch)

    def run_until_cancelled():
        from autoteam import cancel_signal

        while not cancel_signal.is_cancelled():
            time.sleep(0.01)
        return {"status": "stopped"}

    def run_until_released(release):
        release.wait(2)
        return {"status": "done"}

    release_other = api.threading.Event()
    target = api._start_task("register", run_until_cancelled, {}, task_group=api.TASK_GROUP_REGISTER)
    other = api._start_task("gopay-bind", run_until_released, {}, release_other, task_group=api.TASK_GROUP_GOPAY)

    try:
        assert _wait_for(lambda: target["status"] == "running" and other["status"] == "running")
        result = api.post_task_cancel(api.TaskControlParams(task_id=target["task_id"]))
        assert result["task_id"] == target["task_id"]
        assert _wait_for(lambda: target["status"] == "cancelled")
        assert other["status"] == "running"
    finally:
        release_other.set()

    assert _wait_for(lambda: other["status"] == "completed")
