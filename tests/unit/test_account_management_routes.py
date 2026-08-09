import pytest
from fastapi import FastAPI, HTTPException

import autotoken.api_routes.account_management as account_management
from autotoken import account_ops, accounts, admin_state, auth_session_store, chatgpt_api, manager
from autotoken.api_routes.account_management import (
    ACCOUNT_DELETE_BATCH_MAX_EMAILS,
    AccountMetadataBatchUpdateParams,
    AccountMetadataUpdateParams,
    AccountTypeUpdateParams,
    DeleteBatchParams,
    create_account_management_router,
)


@pytest.fixture(autouse=True)
def _stub_brazil_pix_cleanup(monkeypatch):
    monkeypatch.setattr(account_management, "cleanup_brazil_pix_account_artifacts", lambda _email: {"links_deleted": 0})


class FakeLock:
    def __init__(self, acquired=True):
        self.acquired = acquired
        self.acquire_calls = []
        self.release_calls = 0

    def acquire(self, **kwargs):
        self.acquire_calls.append(kwargs)
        return self.acquired

    def release(self):
        self.release_calls += 1


class FakeExecutor:
    def __init__(self):
        self.calls = []
        self.timeout_calls = []

    def run(self, fn, *args, **kwargs):
        self.calls.append((fn, args, kwargs))
        return fn(*args, **kwargs)

    def run_with_timeout(self, timeout, fn, *args, **kwargs):
        self.timeout_calls.append((timeout, fn, args, kwargs))
        return fn(*args, **kwargs)


def _app(*, lock=None, executor=None, current_busy_detail=None, is_main_account_email=None, sanitize_account=None):
    app = FastAPI()
    app.include_router(
        create_account_management_router(
            playwright_lock=lock or FakeLock(),
            playwright_executor=executor or FakeExecutor(),
            current_busy_detail=current_busy_detail or (lambda message: {"message": message}),
            is_main_account_email=is_main_account_email or (lambda _email: False),
            sanitize_account=sanitize_account or (lambda account: {**account, "sanitized": True}),
        )
    )
    return app


def _endpoint(app, path, method):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"missing route {method} {path}")


def test_account_management_delete_uses_remote_cleanup_when_lock_and_admin_available(monkeypatch):
    lock = FakeLock(acquired=True)
    executor = FakeExecutor()
    calls = {}
    app = _app(lock=lock, executor=executor)

    monkeypatch.setattr(accounts, "load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(auth_session_store, "get_auth_session_file", lambda _email: "")
    monkeypatch.setattr(admin_state, "get_admin_session_token", lambda: "session-token")
    monkeypatch.setattr(admin_state, "get_chatgpt_account_id", lambda: "account-id")
    monkeypatch.setattr(auth_session_store, "delete_auth_session", lambda email: email == "User@example.com")
    monkeypatch.setattr(account_management, "cleanup_brazil_pix_account_artifacts", lambda email: {"links_deleted": 1})

    def fake_delete_managed_account(email, *, remove_remote, remove_cloudmail):
        calls["delete"] = {
            "email": email,
            "remove_remote": remove_remote,
            "remove_cloudmail": remove_cloudmail,
        }
        return {"removed": True}

    monkeypatch.setattr(account_ops, "delete_managed_account", fake_delete_managed_account)

    result = _endpoint(app, "/api/accounts/{email}", "DELETE")("User@example.com")

    assert result["remote_cleanup"] is True
    assert result["remote_cleanup_skipped"] is False
    assert result["cleanup"] == {"removed": True, "auth_session_deleted": True, "brazil_pix": {"links_deleted": 1}}
    assert calls["delete"] == {
        "email": "User@example.com",
        "remove_remote": True,
        "remove_cloudmail": False,
    }
    assert len(executor.calls) == 1
    assert lock.acquire_calls == [{"blocking": False}]
    assert lock.release_calls == 1


def test_account_management_delete_falls_back_to_local_cleanup_when_lock_busy(monkeypatch):
    lock = FakeLock(acquired=False)
    app = _app(lock=lock)

    monkeypatch.setattr(accounts, "load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(auth_session_store, "get_auth_session_file", lambda _email: "")
    monkeypatch.setattr(auth_session_store, "delete_auth_session", lambda _email: False)
    monkeypatch.setattr(
        account_ops,
        "delete_managed_account",
        lambda email, *, remove_remote, remove_cloudmail: {
            "email": email,
            "remove_remote": remove_remote,
            "remove_cloudmail": remove_cloudmail,
        },
    )

    result = _endpoint(app, "/api/accounts/{email}", "DELETE")("user@example.com")

    assert result["cleanup"]["remove_remote"] is False
    assert result["cleanup"]["remove_cloudmail"] is False
    assert result["remote_cleanup"] is False
    assert result["remote_cleanup_skipped"] is True
    assert lock.release_calls == 0


def test_account_management_delete_rejects_main_and_missing_accounts(monkeypatch):
    main_app = _app(is_main_account_email=lambda email: email == "owner@example.com")
    with _raises_http(400, "主号不允许删除"):
        _endpoint(main_app, "/api/accounts/{email}", "DELETE")("owner@example.com")

    missing_app = _app()
    monkeypatch.setattr(accounts, "load_accounts", lambda: [])
    monkeypatch.setattr(auth_session_store, "get_auth_session_file", lambda _email: "")

    with _raises_http(404, "账号不存在"):
        _endpoint(missing_app, "/api/accounts/{email}", "DELETE")("missing@example.com")


def test_account_management_delete_batch_cleans_auth_session_only_accounts(monkeypatch):
    lock = FakeLock(acquired=False)
    app = _app(lock=lock)
    captured = {"deleted_sessions": [], "managed": []}

    monkeypatch.setattr(accounts, "load_accounts", lambda: [])
    monkeypatch.setattr(
        auth_session_store,
        "get_auth_session_file",
        lambda email: "data/auth_session/ghost@example_com.json" if email == "ghost@example.com" else "",
    )
    monkeypatch.setattr(
        auth_session_store,
        "delete_auth_session",
        lambda email: captured["deleted_sessions"].append(email) or True,
    )
    monkeypatch.setattr(admin_state, "get_admin_session_token", lambda: "")
    monkeypatch.setattr(admin_state, "get_chatgpt_account_id", lambda: "")

    def fake_delete_managed_account(email, **kwargs):
        captured["managed"].append((email, kwargs))
        return {"local_record": False, "local_auth_files": [], "cpa_files": []}

    monkeypatch.setattr(account_ops, "delete_managed_account", fake_delete_managed_account)

    result = _endpoint(app, "/api/accounts/delete-batch", "POST")(
        DeleteBatchParams(emails=["ghost@example.com"], continue_on_error=True)
    )

    assert result["summary"]["ok"] == 1
    assert result["summary"]["remote_cleanup"] is False
    assert result["results"][0]["cleanup"]["auth_session_deleted"] is True
    assert captured["deleted_sessions"] == ["ghost@example.com"]
    assert captured["managed"][0] == (
        "ghost@example.com",
        {
            "remove_remote": False,
            "remove_cloudmail": False,
            "chatgpt_api": None,
            "remote_state": None,
            "sync_cpa_after": False,
        },
    )


def test_account_management_delete_batch_uses_timeout_runner_when_lock_acquired(monkeypatch):
    lock = FakeLock(acquired=True)
    executor = FakeExecutor()
    app = _app(lock=lock, executor=executor)

    monkeypatch.setattr(accounts, "load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(auth_session_store, "get_auth_session_file", lambda _email: "")
    monkeypatch.setattr(auth_session_store, "delete_auth_session", lambda _email: False)
    monkeypatch.setattr(admin_state, "get_admin_session_token", lambda: "")
    monkeypatch.setattr(admin_state, "get_chatgpt_account_id", lambda: "")
    monkeypatch.setattr(
        account_ops,
        "delete_managed_account",
        lambda email, **_kwargs: {"email": email},
    )

    result = _endpoint(app, "/api/accounts/delete-batch", "POST")(
        DeleteBatchParams(emails=["user@example.com", "USER@example.com"], continue_on_error=True)
    )

    assert result["summary"] == {
        "total": 1,
        "ok": 1,
        "failed": 0,
        "skipped": 0,
        "remote_cleanup": False,
    }
    assert executor.timeout_calls[0][0] == 300
    assert lock.release_calls == 1


def test_account_management_delete_batch_writes_audit_for_successful_deletions(monkeypatch):
    lock = FakeLock(acquired=False)
    app = _app(lock=lock)
    captured_audits = []
    account = {
        "email": "user@example.com",
        "status": "auth_invalid",
        "account_type": "free",
        "seat_type": "unknown",
        "credentials_exported": False,
        "mail_provider": "icloud",
        "cloudmail_account_id": "user@example.com",
        "auth_file": "data/auth_session/user@example_com.json",
        "last_bind_failure_stage": "auth_token_expired",
        "last_bind_message": "token expired",
    }

    monkeypatch.setattr(accounts, "load_accounts", lambda: [account])
    monkeypatch.setattr(auth_session_store, "get_auth_session_file", lambda _email: "")
    monkeypatch.setattr(auth_session_store, "delete_auth_session", lambda _email: True)
    monkeypatch.setattr(admin_state, "get_admin_session_token", lambda: "")
    monkeypatch.setattr(admin_state, "get_chatgpt_account_id", lambda: "")
    monkeypatch.setattr(
        account_ops,
        "delete_managed_account",
        lambda email, **_kwargs: {"local_record": True, "local_auth_files": ["codex.json"], "cpa_files": []},
    )
    monkeypatch.setattr(
        account_management,
        "append_delete_batch_account_audit",
        lambda **kwargs: captured_audits.append(kwargs),
        raising=False,
    )

    result = _endpoint(app, "/api/accounts/delete-batch", "POST")(
        DeleteBatchParams(emails=["user@example.com"], continue_on_error=True)
    )

    assert result["summary"]["ok"] == 1
    assert captured_audits == [
        {
            "email": "user@example.com",
            "account": account,
            "record_deleted": True,
            "auth_session_deleted": True,
            "remote_cleanup": False,
            "cleanup": {
                "local_record": True,
                "local_auth_files": ["codex.json"],
                "cpa_files": [],
                "auth_session_deleted": True,
                "brazil_pix": {"links_deleted": 0},
            },
            "success": True,
            "error": "",
        }
    ]


def test_account_management_delete_batch_rejects_empty_and_main_accounts():
    app = _app(is_main_account_email=lambda email: email.lower() == "owner@example.com")

    with _raises_http(400, "emails 不能为空"):
        _endpoint(app, "/api/accounts/delete-batch", "POST")(DeleteBatchParams(emails=[]))

    with _raises_http(400, "主号不允许删除: ['owner@example.com']"):
        _endpoint(app, "/api/accounts/delete-batch", "POST")(DeleteBatchParams(emails=["owner@example.com"]))


def test_account_management_delete_batch_rejects_too_many_raw_emails():
    app = _app()

    with _raises_http(400, f"批量删除账号条目过多，最多支持 {ACCOUNT_DELETE_BATCH_MAX_EMAILS} 条"):
        _endpoint(app, "/api/accounts/delete-batch", "POST")(
            DeleteBatchParams(emails=[f"user{index}@example.com" for index in range(ACCOUNT_DELETE_BATCH_MAX_EMAILS + 1)])
        )


def test_account_management_kick_account_updates_active_account(monkeypatch):
    lock = FakeLock(acquired=True)
    executor = FakeExecutor()
    app = _app(lock=lock, executor=executor)
    account = {"email": "user@example.com", "status": "active"}
    captured = {}

    monkeypatch.setattr(accounts, "load_accounts", lambda: [account])
    monkeypatch.setattr(accounts, "find_account", lambda loaded, email: loaded[0] if email == "user@example.com" else None)
    monkeypatch.setattr(accounts, "update_account", lambda email, **kwargs: captured.setdefault("updated", (email, kwargs)))
    monkeypatch.setattr(manager, "remove_from_team", lambda api, email: captured.setdefault("removed", (api, email)) or True)

    class FakeChatGPTTeamAPI:
        def start(self):
            captured["started"] = True

        def stop(self):
            captured["stopped"] = True

    monkeypatch.setattr(chatgpt_api, "ChatGPTTeamAPI", FakeChatGPTTeamAPI)

    result = _endpoint(app, "/api/accounts/{email}/kick", "POST")(" User@example.com ")

    assert result == {"message": "已将 user@example.com 移出 Team", "email": "user@example.com", "status": "standby"}
    assert captured["updated"] == ("user@example.com", {"status": "standby"})
    assert captured["removed"][1] == "user@example.com"
    assert captured["started"] is True
    assert captured["stopped"] is True
    assert len(executor.calls) == 1
    assert lock.release_calls == 1


def test_account_management_kick_account_reports_busy_main_missing_and_inactive(monkeypatch):
    busy_app = _app(lock=FakeLock(acquired=False), current_busy_detail=lambda message: {"busy": message})
    with _raises_http(409, {"busy": "有任务正在执行，请等待完成后再操作"}):
        _endpoint(busy_app, "/api/accounts/{email}/kick", "POST")("user@example.com")

    main_app = _app(is_main_account_email=lambda email: email == "owner@example.com")
    with _raises_http(400, "主号不允许移出 Team"):
        _endpoint(main_app, "/api/accounts/{email}/kick", "POST")("owner@example.com")

    app = _app()
    monkeypatch.setattr(accounts, "load_accounts", lambda: [{"email": "inactive@example.com", "status": "standby"}])
    monkeypatch.setattr(
        accounts,
        "find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    with _raises_http(404, "账号不存在"):
        _endpoint(app, "/api/accounts/{email}/kick", "POST")("missing@example.com")
    with _raises_http(400, "账号状态为 standby，不是 active"):
        _endpoint(app, "/api/accounts/{email}/kick", "POST")("inactive@example.com")


def test_account_management_update_account_type_validates_and_sanitizes(monkeypatch):
    app = _app()

    monkeypatch.setattr(accounts, "load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(accounts, "find_account", lambda loaded, email: loaded[0] if email == "user@example.com" else None)
    monkeypatch.setattr(
        accounts,
        "update_account",
        lambda email, **changes: {"email": email, **changes},
    )

    result = _endpoint(app, "/api/accounts/{email}/type", "POST")(
        " User@example.com ",
        AccountTypeUpdateParams(account_type="PLUS"),
    )

    assert result == {
        "message": "已将 user@example.com 账号类型更新为 plus",
        "account": {"email": "user@example.com", "account_type": "plus", "sanitized": True},
    }


def test_account_management_update_account_type_syncs_cached_quota_plan(monkeypatch):
    app = _app()
    captured = {}
    account = {
        "email": "user@example.com",
        "account_type": "plus",
        "last_quota": {"plan_type": "plus", "weekly_pct": 10},
    }

    monkeypatch.setattr(accounts, "load_accounts", lambda: [account])
    monkeypatch.setattr(accounts, "find_account", lambda loaded, email: loaded[0] if email == "user@example.com" else None)

    def fake_update_account(email, **changes):
        captured["updated"] = (email, changes)
        return {**account, **changes}

    monkeypatch.setattr(accounts, "update_account", fake_update_account)

    result = _endpoint(app, "/api/accounts/{email}/type", "POST")(
        "user@example.com",
        AccountTypeUpdateParams(account_type="free"),
    )

    assert captured["updated"] == (
        "user@example.com",
        {"account_type": "free", "last_quota": {"plan_type": "free", "weekly_pct": 10}},
    )
    assert result["account"]["account_type"] == "free"


def test_account_management_update_account_metadata_validates_and_sanitizes(monkeypatch):
    app = _app()
    captured = {}

    monkeypatch.setattr(accounts, "load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(accounts, "find_account", lambda loaded, email: loaded[0] if email == "user@example.com" else None)

    def fake_update_account(email, **changes):
        captured["updated"] = (email, changes)
        return {"email": email, **changes}

    monkeypatch.setattr(accounts, "update_account", fake_update_account)

    result = _endpoint(app, "/api/accounts/{email}/metadata", "PATCH")(
        " User@example.com ",
        AccountMetadataUpdateParams(
            account_type="PLUS",
            status="ACTIVE",
            last_bind_provider="PayPal",
        ),
    )

    assert captured["updated"] == (
        "user@example.com",
        {"account_type": "plus", "status": "active", "last_bind_provider": "paypal"},
    )
    assert result == {
        "message": "已更新 user@example.com 账号信息",
        "account": {
            "email": "user@example.com",
            "account_type": "plus",
            "status": "active",
            "last_bind_provider": "paypal",
            "sanitized": True,
        },
    }


def test_account_management_update_account_metadata_syncs_cached_quota_plan(monkeypatch):
    app = _app()
    captured = {}
    account = {
        "email": "user@example.com",
        "account_type": "plus",
        "status": "active",
        "last_bind_provider": "paypal",
        "last_quota": {"plan_type": "plus", "primary_pct": 0},
    }

    monkeypatch.setattr(accounts, "load_accounts", lambda: [account])
    monkeypatch.setattr(accounts, "find_account", lambda loaded, email: loaded[0] if email == "user@example.com" else None)

    def fake_update_account(email, **changes):
        captured["updated"] = (email, changes)
        return {**account, **changes}

    monkeypatch.setattr(accounts, "update_account", fake_update_account)

    result = _endpoint(app, "/api/accounts/{email}/metadata", "PATCH")(
        "user@example.com",
        AccountMetadataUpdateParams(account_type="free", status="standby", last_bind_provider=""),
    )

    assert captured["updated"] == (
        "user@example.com",
        {
            "account_type": "free",
            "status": "standby",
            "last_bind_provider": "",
            "last_quota": {"plan_type": "free", "primary_pct": 0},
        },
    )
    assert result["account"]["account_type"] == "free"


def test_account_management_update_account_metadata_can_clear_bind_provider(monkeypatch):
    app = _app()
    captured = {}

    monkeypatch.setattr(accounts, "load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(accounts, "find_account", lambda loaded, email: loaded[0] if email == "user@example.com" else None)
    def fake_update_account(email, **changes):
        captured["updated"] = (email, changes)
        return {"email": email, **changes}

    monkeypatch.setattr(accounts, "update_account", fake_update_account)

    _endpoint(app, "/api/accounts/{email}/metadata", "PATCH")(
        "user@example.com",
        AccountMetadataUpdateParams(account_type="free", status="standby", last_bind_provider=""),
    )

    assert captured["updated"] == (
        "user@example.com",
        {"account_type": "free", "status": "standby", "last_bind_provider": ""},
    )


def test_account_management_update_account_metadata_accepts_current_dashboard_options(monkeypatch):
    app = _app()
    captured = {}

    monkeypatch.setattr(accounts, "load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(accounts, "find_account", lambda loaded, email: loaded[0] if email == "user@example.com" else None)

    def fake_update_account(email, **changes):
        captured["updated"] = (email, changes)
        return {"email": email, **changes}

    monkeypatch.setattr(accounts, "update_account", fake_update_account)

    _endpoint(app, "/api/accounts/{email}/metadata", "PATCH")(
        "user@example.com",
        AccountMetadataUpdateParams(account_type="plus", status="session_only", last_bind_provider="momo_vn"),
    )

    assert captured["updated"] == (
        "user@example.com",
        {"account_type": "plus", "status": "session_only", "last_bind_provider": "momo_vn"},
    )


def test_account_management_update_account_metadata_reports_invalid_main_and_missing(monkeypatch):
    app = _app()

    with _raises_http(400, "不支持的账号状态: invalid"):
        _endpoint(app, "/api/accounts/{email}/metadata", "PATCH")(
            "user@example.com",
            AccountMetadataUpdateParams(account_type="free", status="invalid", last_bind_provider="paypal"),
        )

    with _raises_http(400, "不支持的绑定渠道: crypto"):
        _endpoint(app, "/api/accounts/{email}/metadata", "PATCH")(
            "user@example.com",
            AccountMetadataUpdateParams(account_type="free", status="active", last_bind_provider="crypto"),
        )

    main_app = _app(is_main_account_email=lambda email: email == "owner@example.com")
    with _raises_http(400, "主号账号信息不允许手动修改"):
        _endpoint(main_app, "/api/accounts/{email}/metadata", "PATCH")(
            "owner@example.com",
            AccountMetadataUpdateParams(account_type="team", status="active", last_bind_provider="card"),
        )

    monkeypatch.setattr(accounts, "load_accounts", lambda: [])
    monkeypatch.setattr(accounts, "find_account", lambda _loaded, _email: None)
    with _raises_http(404, "账号不存在"):
        _endpoint(app, "/api/accounts/{email}/metadata", "PATCH")(
            "missing@example.com",
            AccountMetadataUpdateParams(account_type="free", status="active", last_bind_provider=""),
        )


def test_account_management_update_accounts_metadata_batch_updates_partial_fields_and_skips_main(monkeypatch):
    app = _app(is_main_account_email=lambda email: email == "owner@example.com")
    captured = []
    accounts_by_email = {
        "user@example.com": {"email": "user@example.com", "account_type": "free", "status": "pending", "last_bind_provider": ""},
        "other@example.com": {"email": "other@example.com", "account_type": "team", "status": "standby", "last_bind_provider": "paypal"},
    }

    monkeypatch.setattr(accounts, "load_accounts", lambda: list(accounts_by_email.values()))
    monkeypatch.setattr(accounts, "find_account", lambda loaded, email: accounts_by_email.get(email))

    def fake_update_account(email, **changes):
        captured.append((email, changes))
        current = dict(accounts_by_email[email])
        current.update(changes)
        accounts_by_email[email] = current
        return current

    monkeypatch.setattr(accounts, "update_account", fake_update_account)

    result = _endpoint(app, "/api/accounts/metadata-batch", "PATCH")(
        AccountMetadataBatchUpdateParams(
            emails=["user@example.com", "owner@example.com", "missing@example.com", "other@example.com"],
            status="stashed",
            last_bind_provider="kakao_pay",
        )
    )

    assert result == {
        "message": "已批量更新 2 个账号信息",
        "updated": 2,
        "missing": ["missing@example.com"],
        "skipped_main": ["owner@example.com"],
        "accounts": [
            {"email": "user@example.com", "account_type": "free", "status": "stashed", "last_bind_provider": "kakao_pay", "sanitized": True},
            {"email": "other@example.com", "account_type": "team", "status": "stashed", "last_bind_provider": "kakao_pay", "sanitized": True},
        ],
    }
    assert captured == [
        ("user@example.com", {"status": "stashed", "last_bind_provider": "kakao_pay"}),
        ("other@example.com", {"status": "stashed", "last_bind_provider": "kakao_pay"}),
    ]


def test_account_management_update_accounts_metadata_batch_rejects_empty_payload_and_invalid_values():
    app = _app()

    with _raises_http(400, "emails 不能为空"):
        _endpoint(app, "/api/accounts/metadata-batch", "PATCH")(AccountMetadataBatchUpdateParams(emails=[]))

    with _raises_http(400, "至少需要提供一个可更新字段"):
        _endpoint(app, "/api/accounts/metadata-batch", "PATCH")(AccountMetadataBatchUpdateParams(emails=["user@example.com"]))

    with _raises_http(400, "不支持的账号状态: invalid"):
        _endpoint(app, "/api/accounts/metadata-batch", "PATCH")(
            AccountMetadataBatchUpdateParams(emails=["user@example.com"], status="invalid")
        )


def test_account_management_update_account_type_reports_invalid_main_and_missing(monkeypatch):
    app = _app()

    with _raises_http(400, "不支持的账号类型: enterprise"):
        _endpoint(app, "/api/accounts/{email}/type", "POST")(
            "user@example.com",
            AccountTypeUpdateParams(account_type="enterprise"),
        )

    main_app = _app(is_main_account_email=lambda email: email == "owner@example.com")
    with _raises_http(400, "主号账号类型不允许手动修改"):
        _endpoint(main_app, "/api/accounts/{email}/type", "POST")(
            "owner@example.com",
            AccountTypeUpdateParams(account_type="team"),
        )

    monkeypatch.setattr(accounts, "load_accounts", lambda: [])
    monkeypatch.setattr(accounts, "find_account", lambda _loaded, _email: None)
    with _raises_http(404, "账号不存在"):
        _endpoint(app, "/api/accounts/{email}/type", "POST")(
            "missing@example.com",
            AccountTypeUpdateParams(account_type="free"),
        )


class _raises_http:
    def __init__(self, status_code, detail):
        self.status_code = status_code
        self.detail = detail

    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, _traceback):
        assert exc_type is HTTPException
        assert exc.status_code == self.status_code
        assert exc.detail == self.detail
        return True
