from fastapi import FastAPI

from autotoken import cpa_sync, register_failures
from autotoken.api_routes.support import create_support_router


def _app(log_buffer=None, start_main_codex_sync=None):
    app = FastAPI()
    app.include_router(
        create_support_router(
            log_buffer=log_buffer or [],
            start_main_codex_sync=start_main_codex_sync or (lambda: {"task_id": "main-codex"}),
        )
    )
    return app


def _endpoint(app, path, method):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"missing route {method} {path}")


def test_sync_routes_delegate_to_cpa_services(monkeypatch):
    app = _app()
    calls = []

    monkeypatch.setattr(cpa_sync, "sync_to_cpa", lambda: calls.append("to-cpa"))
    monkeypatch.setattr(cpa_sync, "sync_from_cpa", lambda: {"imported": 2})

    assert _endpoint(app, "/api/sync", "POST")() == {"message": "同步完成"}
    assert calls == ["to-cpa"]
    assert _endpoint(app, "/api/sync/from-cpa", "POST")() == {
        "message": "已从 CPA 同步到本地",
        "result": {"imported": 2},
    }


def test_register_failures_route_clamps_limit_and_returns_counts(monkeypatch):
    app = _app()
    captured = {}

    def fake_list_failures(limit):
        captured["limit"] = limit
        return [{"category": "oauth_failed"}]

    monkeypatch.setattr(register_failures, "list_failures", fake_list_failures)
    monkeypatch.setattr(register_failures, "count_by_category", lambda: {"oauth_failed": 1})

    assert _endpoint(app, "/api/register-failures", "GET")(limit=9999) == {
        "items": [{"category": "oauth_failed"}],
        "counts": {"oauth_failed": 1},
    }
    assert captured["limit"] == 500

    _endpoint(app, "/api/register-failures", "GET")(limit=0)
    assert captured["limit"] == 1


def test_logs_route_supports_limit_and_since_filters():
    log_buffer = [
        {"time": 1.0, "level": "INFO", "message": "one"},
        {"time": 2.0, "level": "INFO", "message": "two"},
        {"time": 3.0, "level": "ERROR", "message": "three"},
    ]
    app = _app(log_buffer=log_buffer)
    endpoint = _endpoint(app, "/api/logs", "GET")
    initial = endpoint(limit=2)

    assert isinstance(initial["boot_id"], str) and initial["boot_id"]
    assert initial == {"logs": log_buffer[-2:], "total": 3, "boot_id": initial["boot_id"]}
    assert endpoint(since=1.5) == {
        "logs": log_buffer[1:],
        "total": 3,
        "boot_id": initial["boot_id"],
    }


def test_logs_route_uses_stable_id_cursor_for_identical_entries():
    log_buffer = [
        {"id": 41, "time": 2.0, "level": "INFO", "message": "same"},
        {"id": 42, "time": 2.0, "level": "INFO", "message": "same"},
    ]
    app = _app(log_buffer=log_buffer)
    endpoint = _endpoint(app, "/api/logs", "GET")
    boot_id = endpoint()["boot_id"]

    assert endpoint(since=2.0, since_id=41, since_boot_id=boot_id) == {
        "logs": [log_buffer[1]],
        "total": 2,
        "boot_id": boot_id,
    }


def test_logs_route_returns_new_boot_history_when_process_id_resets():
    old_buffer = [
        {"id": log_id, "time": 100.0 + log_id, "level": "INFO", "message": f"old {log_id}"}
        for log_id in range(1, 43)
    ]
    old_app = _app(log_buffer=old_buffer)
    old_endpoint = _endpoint(old_app, "/api/logs", "GET")
    old_boot_id = old_endpoint()["boot_id"]

    new_buffer = [
        {"id": 1, "time": 1.0, "level": "INFO", "message": "after restart one"},
        {"id": 2, "time": 2.0, "level": "INFO", "message": "after restart two"},
    ]
    new_app = _app(log_buffer=new_buffer)
    new_endpoint = _endpoint(new_app, "/api/logs", "GET")

    result = new_endpoint(
        limit=1000,
        since=142.0,
        since_id=42,
        since_boot_id=old_boot_id,
    )

    assert result == {
        "logs": new_buffer,
        "total": 2,
        "boot_id": result["boot_id"],
    }
    assert result["boot_id"] != old_boot_id


def test_logs_route_does_not_guess_restart_from_current_max_id():
    log_buffer = [
        {"id": 1, "time": 101.0, "level": "INFO", "message": "one"},
        {"id": 2, "time": 102.0, "level": "INFO", "message": "two"},
    ]
    app = _app(log_buffer=log_buffer)
    endpoint = _endpoint(app, "/api/logs", "GET")
    boot_id = endpoint()["boot_id"]

    assert endpoint(since=100.0, since_id=42, since_boot_id=boot_id) == {
        "logs": [],
        "total": 2,
        "boot_id": boot_id,
    }


def test_logs_route_defaults_to_deeper_history_and_clamps_limit():
    log_buffer = [{"time": float(i), "level": "INFO", "message": str(i)} for i in range(6000)]
    app = _app(log_buffer=log_buffer)

    default_result = _endpoint(app, "/api/logs", "GET")()
    clamped_result = _endpoint(app, "/api/logs", "GET")(limit=999999)

    assert isinstance(default_result["boot_id"], str) and default_result["boot_id"]
    assert clamped_result["boot_id"] == default_result["boot_id"]
    assert len(default_result["logs"]) == 1000
    assert default_result["logs"] == log_buffer[-1000:]
    assert len(clamped_result["logs"]) == 5000
    assert clamped_result["logs"] == log_buffer[-5000:]


def test_main_codex_compat_route_uses_injected_callback():
    app = _app(start_main_codex_sync=lambda: {"task_id": "task-main", "command": "main-codex-sync"})

    assert _endpoint(app, "/api/sync/main-codex", "POST")() == {
        "task_id": "task-main",
        "command": "main-codex-sync",
    }


def test_cpa_files_route_delegates_to_cpa_service(monkeypatch):
    app = _app()

    monkeypatch.setattr(cpa_sync, "list_cpa_files", lambda: {"files": ["codex-user.json"]})

    assert _endpoint(app, "/api/cpa/files", "GET")() == {"files": ["codex-user.json"]}
