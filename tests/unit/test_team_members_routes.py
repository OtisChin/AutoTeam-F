from fastapi import FastAPI, HTTPException

from autotoken import account_ops, accounts, admin_state, chatgpt_api
from autotoken.api_routes.team_members import TeamMemberRemoveParams, create_team_members_router


class _FakeLock:
    def __init__(self, acquire_result=True):
        self.acquire_result = acquire_result
        self.acquire_calls = 0
        self.release_calls = 0

    def acquire(self, blocking=False):
        self.acquire_calls += 1
        self.blocking = blocking
        return self.acquire_result

    def release(self):
        self.release_calls += 1


class _ImmediateExecutor:
    def run(self, func):
        return func()


def _app(*, lock=None, is_main_account_email=None):
    app = FastAPI()
    app.include_router(
        create_team_members_router(
            playwright_lock=lock or _FakeLock(),
            playwright_executor=_ImmediateExecutor(),
            current_busy_detail=lambda message: {"message": message, "busy": True},
            is_main_account_email=is_main_account_email or (lambda _email: False),
        )
    )
    return app


def _endpoint(app, path, method):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"missing route {method} {path}")


def _admin_ready(monkeypatch):
    monkeypatch.setattr(admin_state, "get_admin_session_token", lambda: "session")
    monkeypatch.setattr(admin_state, "get_chatgpt_account_id", lambda: "account-1")


def test_team_members_routes_require_admin_login(monkeypatch):
    monkeypatch.setattr(admin_state, "get_admin_session_token", lambda: "")
    monkeypatch.setattr(admin_state, "get_chatgpt_account_id", lambda: "")
    app = _app()

    try:
        _endpoint(app, "/api/team/members", "GET")()
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail == "请先完成管理员登录"
    else:
        raise AssertionError("team member query without admin login must fail")


def test_team_members_routes_report_busy_without_releasing_unacquired_lock(monkeypatch):
    _admin_ready(monkeypatch)
    lock = _FakeLock(acquire_result=False)
    app = _app(lock=lock)

    try:
        _endpoint(app, "/api/team/members", "GET")()
    except HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail == {"message": "有任务正在执行，请等待完成后再查询", "busy": True}
    else:
        raise AssertionError("busy team member query must fail")

    assert lock.acquire_calls == 1
    assert lock.release_calls == 0


def test_team_members_list_combines_members_invites_and_local_flags(monkeypatch):
    _admin_ready(monkeypatch)
    lock = _FakeLock()
    app = _app(lock=lock)

    started = []
    stopped = []

    class FakeChatGPT:
        def start(self):
            started.append(True)

        def stop(self):
            stopped.append(True)

    monkeypatch.setattr(chatgpt_api, "ChatGPTTeamAPI", FakeChatGPT)
    monkeypatch.setattr(
        account_ops,
        "fetch_team_state",
        lambda _chatgpt: (
            [{"email": "Local@example.com", "role": "member", "user_id": "user-1"}],
            [{"email_address": "Invite@example.com", "role": "member", "id": "invite-1"}],
        ),
    )
    monkeypatch.setattr(accounts, "load_accounts", lambda: [{"email": "local@example.com"}])

    result = _endpoint(app, "/api/team/members", "GET")()

    assert result == {
        "members": [
            {
                "email": "Local@example.com",
                "role": "member",
                "user_id": "user-1",
                "is_local": True,
                "type": "member",
            },
            {
                "email": "invite@example.com",
                "role": "member",
                "user_id": "invite-1",
                "is_local": False,
                "type": "invite",
            },
        ],
        "total": 1,
        "invites": 1,
    }
    assert started == [True]
    assert stopped == [True]
    assert lock.release_calls == 1


def test_team_member_remove_deletes_member_and_updates_local_account(monkeypatch):
    _admin_ready(monkeypatch)
    lock = _FakeLock()
    app = _app(lock=lock)
    paths = []
    updates = []

    class FakeChatGPT:
        def start(self):
            pass

        def stop(self):
            pass

        def _api_fetch(self, method, path):
            paths.append((method, path))
            return {"status": 204}

    monkeypatch.setattr(chatgpt_api, "ChatGPTTeamAPI", FakeChatGPT)
    monkeypatch.setattr(accounts, "load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(accounts, "find_account", lambda loaded, email: {"email": email} if loaded and email == "user@example.com" else None)
    monkeypatch.setattr(accounts, "update_account", lambda email, **kwargs: updates.append((email, kwargs)))

    result = _endpoint(app, "/api/team/members/remove", "POST")(
        TeamMemberRemoveParams(email=" User@example.com ", user_id="user-1", type="member")
    )

    assert result == {"message": "已移出 Team: user@example.com", "email": "user@example.com", "type": "member"}
    assert paths == [("DELETE", "/backend-api/accounts/account-1/users/user-1")]
    assert updates == [("user@example.com", {"status": "standby"})]
    assert lock.release_calls == 1


def test_team_member_remove_validates_main_account_and_upstream_status(monkeypatch):
    _admin_ready(monkeypatch)
    app = _app(is_main_account_email=lambda email: email == "owner@example.com")

    try:
        _endpoint(app, "/api/team/members/remove", "POST")(
            TeamMemberRemoveParams(email="owner@example.com", user_id="user-main", type="member")
        )
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail == "主号不允许从 Team 成员页移出"
    else:
        raise AssertionError("main account removal must fail")

    app = _app()

    class FakeChatGPT:
        def start(self):
            pass

        def stop(self):
            pass

        def _api_fetch(self, _method, _path):
            return {"status": 500}

    monkeypatch.setattr(chatgpt_api, "ChatGPTTeamAPI", FakeChatGPT)

    try:
        _endpoint(app, "/api/team/members/remove", "POST")(
            TeamMemberRemoveParams(email="invite@example.com", user_id="invite-1", type="invite")
        )
    except HTTPException as exc:
        assert exc.status_code == 500
        assert exc.detail == "取消邀请失败: HTTP 500"
    else:
        raise AssertionError("upstream remove failure must fail")
