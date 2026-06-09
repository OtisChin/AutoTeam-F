import time

import pytest
from fastapi import HTTPException

from autotoken import api
from autotoken.api_routes.task_control import GOPAY_RUNTIME_CONTROL_MAX_EMAILS


def _reset_task_scheduler(monkeypatch):
    monkeypatch.setattr(api, "_tasks", {})
    monkeypatch.setattr(api, "_task_group_locks", {})
    monkeypatch.setattr(api, "_current_task_ids", {})
    monkeypatch.setattr(api, "_task_cancel_signals", {})
    monkeypatch.setattr(api, "_task_skip_signals", {})
    monkeypatch.setattr(api, "_task_cancel_hooks", {})
    monkeypatch.setattr(api, "_task_runtime_controls", {})
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
        from autotoken import cancel_signal

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


def test_cancel_runs_registered_task_hook_immediately(monkeypatch):
    _reset_task_scheduler(monkeypatch)
    release = api.threading.Event()
    hook_called = []

    def run_until_released():
        release.wait(2)
        return {"status": "released"}

    task = api._start_task("gopay-bind", run_until_released, {}, task_group=api.TASK_GROUP_GOPAY)

    try:
        assert _wait_for(lambda: task["status"] == "running")

        def cancel_hook():
            hook_called.append(time.time())
            release.set()

        api._register_task_cancel_hook(task["task_id"], cancel_hook)
        started_at = time.time()
        result = api.post_task_cancel(api.TaskControlParams(task_id=task["task_id"]))

        assert result["task_id"] == task["task_id"]
        assert release.wait(0.2)
        assert hook_called
        assert time.time() - started_at < 0.5
        assert _wait_for(lambda: task["status"] == "cancelled")
    finally:
        release.set()


def test_gopay_runtime_control_updates_running_task(monkeypatch):
    _reset_task_scheduler(monkeypatch)
    release = api.threading.Event()

    def run_until_released():
        release.wait(2)
        return {"status": "done"}

    task = api._start_task("gopay-bind", run_until_released, {"account_emails": ["first@example.com"]}, task_group=api.TASK_GROUP_GOPAY)
    try:
        assert _wait_for(lambda: task["status"] == "running")
        api._init_gopay_runtime_control(
            task["task_id"],
            gopay_concurrency=1,
            sms_provider="smscloud",
            account_emails=["first@example.com"],
        )

        result = api.post_gopay_runtime_control(
            api.GoPayRuntimeControlParams(
                task_id=task["task_id"],
                gopay_concurrency=5,
                gopay_auto_signup_sms_provider="hero_sms",
                gopay_balance_poll_interval_seconds=7,
                gopay_transfer_balance_wait_seconds=45,
                account_emails=["second@example.com", "first@example.com"],
            )
        )

        control = api._gopay_runtime_control(task["task_id"])
        assert result["updates"]["gopay_concurrency"] == 5
        assert result["updates"]["gopay_auto_signup_sms_provider"] == "hero_sms"
        assert result["updates"]["gopay_balance_poll_interval_seconds"] == 7
        assert result["updates"]["gopay_transfer_balance_wait_seconds"] == 45
        assert result["updates"]["added_account_emails"] == ["second@example.com"]
        assert control["pending_account_emails"] == ["second@example.com"]
        assert control["all_account_emails"] == ["first@example.com", "second@example.com"]
        assert task["params"]["account_emails"] == ["first@example.com", "second@example.com"]
        assert task["params"]["gopay_balance_poll_interval_seconds"] == 7
        assert task["params"]["gopay_transfer_balance_wait_seconds"] == 45
    finally:
        release.set()


def test_gopay_runtime_control_rejects_too_many_raw_account_emails(monkeypatch):
    _reset_task_scheduler(monkeypatch)
    release = api.threading.Event()

    def run_until_released():
        release.wait(2)
        return {"status": "done"}

    task = api._start_task(
        "gopay-bind",
        run_until_released,
        {"account_emails": ["first@example.com"]},
        task_group=api.TASK_GROUP_GOPAY,
    )
    try:
        assert _wait_for(lambda: task["status"] == "running")
        with pytest.raises(HTTPException) as exc:
            api.post_gopay_runtime_control(
                api.GoPayRuntimeControlParams(
                    task_id=task["task_id"],
                    account_emails=[
                        f"user{index}@example.com" for index in range(GOPAY_RUNTIME_CONTROL_MAX_EMAILS + 1)
                    ],
                )
            )
        assert exc.value.status_code == 400
        assert "GoPay 热切换账号条目过多" in exc.value.detail
    finally:
        release.set()
