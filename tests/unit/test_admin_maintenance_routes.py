import pytest
from fastapi import HTTPException

from autotoken.api_routes.admin_maintenance import create_admin_maintenance_router


class FakeLock:
    def __init__(self, locked=False):
        self.acquired = locked

    def acquire(self, blocking=False):
        if self.acquired:
            return False
        self.acquired = True
        return True

    def release(self):
        self.acquired = False


class FakeExecutor:
    def run(self, func, *args, **kwargs):
        return func(*args, **kwargs)


class FakeRequest:
    def __init__(self, query_params):
        self.query_params = query_params


def _routes(lock=None):
    router = create_admin_maintenance_router(
        playwright_lock=lock or FakeLock(),
        playwright_executor=FakeExecutor(),
        current_busy_detail=lambda message: {"message": message},
        logger=type("Logger", (), {"info": lambda *_args, **_kwargs: None})(),
    )
    return {route.endpoint.__name__: route.endpoint for route in router.routes}


def test_admin_reconcile_parses_dry_run_and_releases_lock(monkeypatch):
    calls = []
    lock = FakeLock()
    monkeypatch.setattr("autotoken.manager.cmd_reconcile", lambda dry_run=False: calls.append(dry_run) or {"dry_run": dry_run})

    result = _routes(lock)["post_admin_reconcile"](FakeRequest({"dry_run": "true"}))

    assert result == {"dry_run": True}
    assert calls == [True]
    assert lock.acquired is False


def test_admin_reconcile_reports_busy_task_when_lock_is_held():
    with pytest.raises(HTTPException) as exc_info:
        _routes(FakeLock(locked=True))["post_admin_reconcile"](FakeRequest({}))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == {"message": "有任务正在执行"}


def test_admin_fix_account_id_requires_saved_session(monkeypatch):
    monkeypatch.setattr("autotoken.admin_state.get_admin_session_token", lambda: "")

    with pytest.raises(HTTPException) as exc_info:
        _routes()["post_admin_fix_account_id"]()

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "尚未保存 session_token,请先导入"
