import pytest
from fastapi import HTTPException

from autotoken.api_routes.interactive_login import (
    AdminCodeParams,
    ManualAccountCallbackParams,
    create_interactive_login_router,
)


class FakeLock:
    def __init__(self):
        self.acquired = False

    def acquire(self, blocking=False):
        if self.acquired:
            return False
        self.acquired = True
        return True

    def release(self):
        self.acquired = False

    def locked(self):
        return self.acquired


class FakeExecutor:
    def run(self, func, *args, **kwargs):
        return func(*args, **kwargs)


class FakeFlow:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


def _routes(state=None, lock=None):
    state = state or {}
    state.setdefault("admin_api", None)
    state.setdefault("admin_step", None)
    state.setdefault("main_flow", None)
    state.setdefault("main_step", None)
    state.setdefault("manual_flow", None)
    lock = lock or FakeLock()

    def set_admin_login_state(api, step):
        state["admin_api"] = api
        state["admin_step"] = step

    def set_main_codex_state(flow, step):
        state["main_flow"] = flow
        state["main_step"] = step

    def set_manual_account_flow(flow):
        state["manual_flow"] = flow

    router = create_interactive_login_router(
        playwright_lock=lock,
        playwright_executor=FakeExecutor(),
        current_busy_detail=lambda message: {"message": message},
        logger=type("Logger", (), {"info": lambda *_args, **_kwargs: None, "warning": lambda *_args, **_kwargs: None, "exception": lambda *_args, **_kwargs: None})(),
        admin_status=lambda: {"login_in_progress": state["admin_api"] is not None, "login_step": state["admin_step"]},
        main_codex_status=lambda: {"in_progress": state["main_flow"] is not None, "step": state["main_step"]},
        manual_account_status=lambda: {"in_progress": state["manual_flow"] is not None},
        get_admin_login_api=lambda: state["admin_api"],
        get_admin_login_step=lambda: state["admin_step"],
        set_admin_login_state=set_admin_login_state,
        finish_admin_login=lambda completed: {"status": "completed", "info": completed},
        set_pending_admin_login=lambda api, step: set_admin_login_state(api, step) or {"status": step},
        get_main_codex_flow=lambda: state["main_flow"],
        get_main_codex_step=lambda: state["main_step"],
        set_main_codex_state=set_main_codex_state,
        finish_main_codex_sync=lambda: {"status": "completed", "codex": {"in_progress": False}},
        set_pending_main_codex_sync=lambda flow, step: set_main_codex_state(flow, step) or {"status": step},
        get_manual_account_flow=lambda: state["manual_flow"],
        set_manual_account_flow=set_manual_account_flow,
        finish_manual_account_flow=lambda result: {**result, "manual_account": {"in_progress": True}},
        set_pending_manual_account_flow=lambda flow, result: set_manual_account_flow(flow) or result,
    )
    return {route.endpoint.__name__: route.endpoint for route in router.routes}, state, lock


def test_status_routes_use_injected_state():
    routes, state, _lock = _routes({"admin_api": object(), "admin_step": "code_required", "main_flow": None, "main_step": None, "manual_flow": object()})

    assert routes["get_admin_status"]() == {"login_in_progress": True, "login_step": "code_required"}
    assert routes["get_main_codex_status"]() == {"in_progress": False, "step": None}
    assert routes["get_manual_account_status"]() == {"in_progress": True}


def test_admin_login_cancel_stops_flow_and_releases_lock():
    flow = FakeFlow()
    lock = FakeLock()
    lock.acquire()
    routes, state, _lock = _routes({"admin_api": flow, "admin_step": "code_required"}, lock)

    result = routes["post_admin_login_cancel"]()

    assert result["message"] == "管理员登录已取消"
    assert flow.stopped is True
    assert state["admin_api"] is None
    assert state["admin_step"] is None
    assert lock.locked() is False


def test_admin_code_requires_pending_code_flow():
    routes, _state, _lock = _routes()

    with pytest.raises(HTTPException) as exc_info:
        routes["post_admin_login_code"](AdminCodeParams(code="123456"))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "当前没有等待验证码的管理员登录流程"


def test_main_codex_start_uses_saved_auth_without_playwright(monkeypatch):
    synced = []
    monkeypatch.setattr("autotoken.codex_auth.get_saved_main_auth_file", lambda: "D:/auth.json")
    monkeypatch.setattr("autotoken.cpa_sync.sync_main_codex_to_cpa", lambda auth_file: synced.append(auth_file))
    routes, _state, lock = _routes()

    result = routes["post_main_codex_start"]()

    assert result == {
        "status": "completed",
        "message": "主号 Codex 已同步到 CPA",
        "codex": {"in_progress": False, "step": None},
        "info": {"auth_file": "D:/auth.json"},
    }
    assert synced == ["D:/auth.json"]
    assert lock.locked() is False


def test_manual_account_callback_requires_flow():
    routes, _state, _lock = _routes()

    with pytest.raises(HTTPException) as exc_info:
        routes["post_manual_account_callback"](ManualAccountCallbackParams(redirect_url="https://callback.example"))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "当前没有等待回调的手动添加账号流程"
