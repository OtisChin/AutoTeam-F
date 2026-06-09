from fastapi import FastAPI, HTTPException

from autotoken import accounts, manager
from autotoken.api_routes.status import create_status_router


class _FakeLock:
    def __init__(self, acquire_result=True):
        self.acquire_result = acquire_result
        self.release_calls = 0

    def acquire(self, blocking=False):
        self.blocking = blocking
        return self.acquire_result

    def release(self):
        self.release_calls += 1


class _ImmediateExecutor:
    def run(self, func):
        return func()


def _app(*, lock=None, loaded_accounts=None, sanitized_accounts=None):
    loaded_accounts = loaded_accounts if loaded_accounts is not None else []
    sanitized_accounts = sanitized_accounts if sanitized_accounts is not None else loaded_accounts
    app = FastAPI()
    app.include_router(
        create_status_router(
            load_accounts_with_session_stubs=lambda **_kwargs: loaded_accounts,
            sanitize_accounts_batch=lambda _accounts, _quota_cache: sanitized_accounts,
            playwright_lock=lock or _FakeLock(),
            playwright_executor=_ImmediateExecutor(),
            current_busy_detail=lambda message: {"message": message, "busy": True},
        )
    )
    return app


def _endpoint(app, path, method):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"missing route {method} {path}")


def test_status_route_builds_summary_and_quota_cache():
    loaded_accounts = [
        {
            "email": "active@example.com",
            "status": "active",
            "account_type": "team",
            "last_quota": {"primary_pct": 10},
        },
        {"email": "plus@example.com", "status": "active", "account_type": "plus"},
        {"email": "free@example.com", "status": "standby", "account_type": "free"},
        {"email": "pro@example.com", "status": "exhausted", "account_type": "pro"},
    ]
    app = _app(loaded_accounts=loaded_accounts)

    result = _endpoint(app, "/api/status", "GET")()

    assert result["accounts"] == loaded_accounts
    assert result["quota_cache"] == {"active@example.com": {"primary_pct": 10}}
    assert result["summary"] == {
        "active": 2,
        "standby": 1,
        "exhausted": 1,
        "pending": 0,
        "auth_invalid": 0,
        "orphan": 0,
        "fail": 0,
        "free": 1,
        "team": 1,
        "plus": 1,
        "pro": 1,
        "total": 4,
    }


def test_sync_accounts_route_runs_sync_with_lock_and_reports_total(monkeypatch):
    lock = _FakeLock()
    events = []
    app = _app(lock=lock)

    monkeypatch.setattr(manager, "sync_account_states", lambda: events.append("sync"))
    monkeypatch.setattr(accounts, "load_accounts", lambda: [{"email": "a@example.com"}, {"email": "b@example.com"}])

    result = _endpoint(app, "/api/sync/accounts", "POST")()

    assert result == {"message": "同步完成，共 2 个账号", "total": 2}
    assert events == ["sync"]
    assert lock.release_calls == 1


def test_sync_accounts_route_reports_busy_without_release(monkeypatch):
    lock = _FakeLock(acquire_result=False)
    app = _app(lock=lock)

    try:
        _endpoint(app, "/api/sync/accounts", "POST")()
    except HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail == {"message": "有任务正在执行，请等待完成后再同步", "busy": True}
    else:
        raise AssertionError("busy account sync must fail")

    assert lock.release_calls == 0
