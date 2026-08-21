import json

import pytest
from fastapi import HTTPException

from autotoken.api_routes.account_refresh_quota import AccountEmailBatchParams, create_account_refresh_quota_router
from autotoken.services.task_runtime import TASK_GROUP_QUOTA
from autotoken.storage.auth_files import AUTH_JSON_FILE_MAX_BYTES


@pytest.fixture(autouse=True)
def _auth_dirs(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    session_dir = tmp_path / "auth_session"
    auth_dir.mkdir()
    session_dir.mkdir()
    monkeypatch.setattr("autotoken.storage.auth_storage.AUTH_DIR", auth_dir)
    monkeypatch.setattr("autotoken.storage.auth_session_store.AUTH_SESSION_DIR", session_dir)
    return auth_dir


def _logger():
    return type(
        "Logger",
        (),
        {
            "debug": lambda *_args, **_kwargs: None,
            "exception": lambda *_args, **_kwargs: None,
        },
    )()


def _routes(started, *, progress=None, main_email="owner@example.com"):
    progress = progress if progress is not None else []

    def start_task(command, func, params, *args, **kwargs):
        started.append({"command": command, "func": func, "params": params, "args": args, "kwargs": kwargs})
        return {"task_id": "task-1", "command": command, "params": params}

    router = create_account_refresh_quota_router(
        start_task=start_task,
        normalize_email=lambda value: str(value or "").strip().lower(),
        is_main_account_email=lambda email: str(email or "").strip().lower() == main_email,
        resolve_status_auth_file=lambda account: account.get("auth_file"),
        account_id_from_auth_data=lambda auth_data: str(auth_data.get("account_id") or ""),
        append_task_progress=lambda task_id, item: progress.append({"task_id": task_id, **item}),
        task_group_quota=TASK_GROUP_QUOTA,
        logger=_logger(),
    )
    return {route.endpoint.__name__: route.endpoint for route in router.routes}


def _auth_file(tmp_path, token="token", account_id="acct_1"):
    path = tmp_path / "auths" / f"{token}.json"
    path.write_text(json.dumps({"access_token": token, "account_id": account_id}), encoding="utf-8")
    return str(path)


def test_refresh_quota_defaults_to_all_non_main_non_fail_accounts(tmp_path, monkeypatch):
    started = []
    accounts = [
        {"email": "owner@example.com", "auth_file": _auth_file(tmp_path, "owner")},
        {"email": "active@example.com", "auth_file": _auth_file(tmp_path, "active"), "status": "active"},
        {"email": "failed@example.com", "auth_file": _auth_file(tmp_path, "failed"), "status": "fail"},
    ]
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda rows, email: next((account for account in rows if account["email"] == email), None),
    )

    routes = _routes(started)
    result = routes["post_accounts_refresh_quota"](AccountEmailBatchParams(emails=[]))

    assert result == {
        "task_id": "task-1",
        "command": "refresh-quota",
        "params": {"emails": ["active@example.com"], "missing": []},
    }
    assert started[0]["kwargs"]["task_group"] == TASK_GROUP_QUOTA
    assert started[0]["kwargs"]["pass_task_id"] is True


def test_refresh_quota_applies_updates_in_input_order(tmp_path, monkeypatch):
    started = []
    updated = []
    accounts = [
        {"email": "first@example.com", "auth_file": _auth_file(tmp_path, "first"), "status": "pending"},
        {"email": "second@example.com", "auth_file": _auth_file(tmp_path, "second"), "status": "pending"},
    ]
    monkeypatch.setenv("REFRESH_QUOTA_CONCURRENCY", "2")
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda rows, email: next((account for account in rows if account["email"] == email), None),
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **payload: updated.append((email, payload)))
    monkeypatch.setattr("autotoken.codex_auth.check_codex_quota", lambda *_args, **_kwargs: ("ok", {"plan": "plus"}))

    routes = _routes(started)
    routes["post_accounts_refresh_quota"](AccountEmailBatchParams(emails=["SECOND@example.com", "FIRST@example.com"]))
    run_result = started[0]["func"]("task-refresh")

    assert [email for email, _payload in updated] == ["second@example.com", "first@example.com"]
    assert [item["email"] for item in run_result["ok"]] == ["second@example.com", "first@example.com"]
    assert all(payload["status"] == "active" for _email, payload in updated)


def test_refresh_quota_preserves_stashed_status_on_success(tmp_path, monkeypatch):
    started = []
    updated = []
    account = {
        "email": "user@example.com",
        "auth_file": _auth_file(tmp_path, "stashed"),
        "status": "stashed",
        "account_type": "plus",
    }
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda _rows, email: account if email == "user@example.com" else None
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **payload: updated.append((email, payload)))
    monkeypatch.setattr(
        "autotoken.codex_auth.check_codex_quota", lambda *_args, **_kwargs: ("ok", {"plan_type": "plus"})
    )

    routes = _routes(started)
    routes["post_accounts_refresh_quota"](AccountEmailBatchParams(emails=["user@example.com"]))
    started[0]["func"]("task-refresh")

    assert updated[0][0] == "user@example.com"
    assert updated[0][1]["account_type"] == "plus"
    assert "last_quota" in updated[0][1]
    assert "status" not in updated[0][1]


def test_refresh_quota_preserves_stashed_status_when_exhausted(tmp_path, monkeypatch):
    started = []
    updated = []
    account = {
        "email": "user@example.com",
        "auth_file": _auth_file(tmp_path, "stashed-exhausted"),
        "status": "stashed",
        "account_type": "plus",
    }
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda _rows, email: account if email == "user@example.com" else None
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **payload: updated.append((email, payload)))
    monkeypatch.setattr(
        "autotoken.codex_auth.check_codex_quota",
        lambda *_args, **_kwargs: (
            "exhausted",
            {"quota": {"plan_type": "plus", "primary_pct": 100}, "resets_at": 1785000000},
        ),
    )

    routes = _routes(started)
    routes["post_accounts_refresh_quota"](AccountEmailBatchParams(emails=["user@example.com"]))
    started[0]["func"]("task-refresh")

    assert updated[0][0] == "user@example.com"
    assert updated[0][1]["quota_resets_at"] == 1785000000
    assert "status" not in updated[0][1]


def test_refresh_quota_marks_auth_error_accounts_fail(tmp_path, monkeypatch):
    started = []
    updated = []
    account = {"email": "user@example.com", "auth_file": _auth_file(tmp_path, "bad"), "status": "active"}
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda _rows, email: account if email == "user@example.com" else None
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **payload: updated.append((email, payload)))
    monkeypatch.setattr(
        "autotoken.codex_auth.check_codex_quota",
        lambda *_args, **_kwargs: ("auth_error", {"message": "invalid_token: token expired"}),
    )

    routes = _routes(started)
    routes["post_accounts_refresh_quota"](AccountEmailBatchParams(emails=["user@example.com"]))
    run_result = started[0]["func"]("task-refresh")

    assert run_result["failed"] == [
        {"email": "user@example.com", "reason": "auth_error", "error_detail": "invalid_token: token expired"}
    ]
    assert updated[0][0] == "user@example.com"
    assert updated[0][1]["status"] == "fail"
    assert updated[0][1]["discarded_reason"] == "quota_refresh_401"
    assert (
        updated[0][1]["last_bind_message"] == "刷新额度返回 401: invalid_token: token expired，账号已标记为 Fail/废弃"
    )


def test_refresh_quota_does_not_discard_token_expired_accounts(tmp_path, monkeypatch):
    started = []
    updated = []
    account = {"email": "user@example.com", "auth_file": _auth_file(tmp_path, "expired"), "status": "active"}
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda _rows, email: account if email == "user@example.com" else None
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **payload: updated.append((email, payload)))
    monkeypatch.setattr(
        "autotoken.codex_auth.check_codex_quota",
        lambda *_args, **_kwargs: (
            "auth_error",
            {
                "status_code": 401,
                "code": "token_expired",
                "message": "token_expired: Provided authentication token is expired.",
            },
        ),
    )

    routes = _routes(started)
    routes["post_accounts_refresh_quota"](AccountEmailBatchParams(emails=["user@example.com"]))
    run_result = started[0]["func"]("task-refresh")

    assert run_result["failed"] == []
    assert run_result["network_error"] == [{"email": "user@example.com", "reason": "token_expired"}]
    assert updated == [
        (
            "user@example.com",
            {
                "status": "auth_invalid",
                "last_quota_check_at": updated[0][1]["last_quota_check_at"],
                "last_bind_status": "failed",
                "last_bind_failure_stage": "auth_token_expired",
                "last_bind_message": "刷新额度返回 token_expired: Provided authentication token is expired.，账号需刷新 auth_session，未标记废弃",
            },
        )
    ]


def test_refresh_quota_marks_token_revoked_as_auth_revoked_without_discarding(tmp_path, monkeypatch):
    started = []
    updated = []
    account = {"email": "user@example.com", "auth_file": _auth_file(tmp_path, "revoked"), "status": "active"}
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda _rows, email: account if email == "user@example.com" else None
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **payload: updated.append((email, payload)))
    monkeypatch.setattr(
        "autotoken.codex_auth.check_codex_quota",
        lambda *_args, **_kwargs: (
            "auth_error",
            {
                "status_code": 401,
                "code": "token_revoked",
                "message": "token_revoked: Encountered invalidated oauth token for user, failing request",
            },
        ),
    )

    routes = _routes(started)
    routes["post_accounts_refresh_quota"](AccountEmailBatchParams(emails=["user@example.com"]))
    run_result = started[0]["func"]("task-refresh")

    assert run_result["failed"] == []
    assert run_result["network_error"] == [{"email": "user@example.com", "reason": "token_revoked"}]
    assert updated == [
        (
            "user@example.com",
            {
                "status": "auth_revoked",
                "last_quota_check_at": updated[0][1]["last_quota_check_at"],
                "last_bind_status": "failed",
                "last_bind_failure_stage": "auth_token_revoked",
                "last_bind_message": (
                    "刷新额度返回 token_revoked: Encountered invalidated oauth token for user, failing request，"
                    "账号掉授权，未标记废弃"
                ),
            },
        )
    ]


def test_refresh_quota_marks_token_invalidated_accounts_fail(tmp_path, monkeypatch):
    started = []
    updated = []
    account = {"email": "user@example.com", "auth_file": _auth_file(tmp_path, "invalidated"), "status": "active"}
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda _rows, email: account if email == "user@example.com" else None
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **payload: updated.append((email, payload)))
    monkeypatch.setattr(
        "autotoken.codex_auth.check_codex_quota",
        lambda *_args, **_kwargs: (
            "auth_error",
            {
                "status_code": 401,
                "code": "token_invalidated",
                "message": "token_invalidated: Your authentication token has been invalidated. Please try signing in again.",
            },
        ),
    )

    routes = _routes(started)
    routes["post_accounts_refresh_quota"](AccountEmailBatchParams(emails=["user@example.com"]))
    run_result = started[0]["func"]("task-refresh")

    assert run_result["failed"] == [
        {
            "email": "user@example.com",
            "reason": "auth_error",
            "error_detail": "token_invalidated: Your authentication token has been invalidated. Please try signing in again.",
        }
    ]
    assert run_result["network_error"] == []
    assert updated == [
        (
            "user@example.com",
            {
                "status": "fail",
                "discarded_at": updated[0][1]["discarded_at"],
                "discarded_reason": "quota_refresh_401",
                "last_quota_check_at": updated[0][1]["last_quota_check_at"],
                "last_bind_status": "failed",
                "last_bind_failure_stage": "auth_token_invalidated",
                "last_bind_message": (
                    "刷新额度返回 token_invalidated: Your authentication token has been invalidated. "
                    "Please try signing in again.，账号已标记为 Fail/废弃"
                ),
            },
        )
    ]


def test_refresh_quota_rechecks_legacy_token_expired_fail_accounts(tmp_path, monkeypatch):
    started = []
    updated = []
    quota_calls = []
    account = {
        "email": "user@example.com",
        "auth_file": _auth_file(tmp_path, "expired"),
        "status": "fail",
        "discarded_reason": "quota_refresh_401",
        "last_bind_message": "刷新额度返回 401: token_expired: Provided authentication token is expired.，账号已标记为 Fail/废弃",
    }
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda _rows, email: account if email == "user@example.com" else None
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **payload: updated.append((email, payload)))

    def fake_check(*_args, **_kwargs):
        quota_calls.append(True)
        return (
            "auth_error",
            {
                "status_code": 401,
                "code": "token_expired",
                "message": "token_expired: Provided authentication token is expired.",
            },
        )

    monkeypatch.setattr("autotoken.codex_auth.check_codex_quota", fake_check)

    routes = _routes(started)
    routes["post_accounts_refresh_quota"](AccountEmailBatchParams(emails=["user@example.com"]))
    run_result = started[0]["func"]("task-refresh")

    assert quota_calls == [True]
    assert run_result["skipped"] == []
    assert run_result["failed"] == []
    assert run_result["network_error"] == [{"email": "user@example.com", "reason": "token_expired"}]
    assert updated[0][1]["status"] == "auth_invalid"
    assert updated[0][1]["last_bind_failure_stage"] == "auth_token_expired"


def test_refresh_quota_rechecks_legacy_token_revoked_fail_accounts(tmp_path, monkeypatch):
    started = []
    updated = []
    quota_calls = []
    account = {
        "email": "user@example.com",
        "auth_file": _auth_file(tmp_path, "revoked"),
        "status": "fail",
        "discarded_reason": "quota_refresh_401",
        "last_bind_message": (
            "刷新额度返回 401: token_revoked: Encountered invalidated oauth token for user, failing request，"
            "账号已标记为 Fail/废弃"
        ),
    }
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda _rows, email: account if email == "user@example.com" else None
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **payload: updated.append((email, payload)))

    def fake_check(*_args, **_kwargs):
        quota_calls.append(True)
        return (
            "auth_error",
            {
                "status_code": 401,
                "code": "token_revoked",
                "message": "token_revoked: Encountered invalidated oauth token for user, failing request",
            },
        )

    monkeypatch.setattr("autotoken.codex_auth.check_codex_quota", fake_check)

    routes = _routes(started)
    routes["post_accounts_refresh_quota"](AccountEmailBatchParams(emails=["user@example.com"]))
    run_result = started[0]["func"]("task-refresh")

    assert quota_calls == [True]
    assert run_result["skipped"] == []
    assert run_result["failed"] == []
    assert run_result["network_error"] == [{"email": "user@example.com", "reason": "token_revoked"}]
    assert updated[0][1]["status"] == "auth_revoked"
    assert updated[0][1]["last_bind_failure_stage"] == "auth_token_revoked"
    assert "discarded_reason" not in updated[0][1]


def test_refresh_quota_skips_legacy_token_invalidated_fail_accounts(tmp_path, monkeypatch):
    started = []
    updated = []
    quota_calls = []
    account = {
        "email": "user@example.com",
        "auth_file": _auth_file(tmp_path, "invalidated"),
        "status": "fail",
        "discarded_reason": "quota_refresh_401",
        "last_bind_message": (
            "刷新额度返回 401: token_invalidated: Your authentication token has been invalidated. "
            "Please try signing in again.，账号已标记为 Fail/废弃"
        ),
    }
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda _rows, email: account if email == "user@example.com" else None
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **payload: updated.append((email, payload)))

    def fake_check(*_args, **_kwargs):
        quota_calls.append(True)
        return (
            "auth_error",
            {
                "status_code": 401,
                "code": "token_invalidated",
                "message": "token_invalidated: Your authentication token has been invalidated. Please try signing in again.",
            },
        )

    monkeypatch.setattr("autotoken.codex_auth.check_codex_quota", fake_check)

    routes = _routes(started)
    routes["post_accounts_refresh_quota"](AccountEmailBatchParams(emails=["user@example.com"]))
    run_result = started[0]["func"]("task-refresh")

    assert quota_calls == []
    assert run_result["skipped"] == [{"email": "user@example.com", "reason": "fail_account"}]
    assert run_result["failed"] == []
    assert run_result["network_error"] == []
    assert updated == []


def test_refresh_quota_success_clears_legacy_quota_401_discard_marker(tmp_path, monkeypatch):
    started = []
    updated = []
    account = {
        "email": "user@example.com",
        "auth_file": _auth_file(tmp_path, "recovered"),
        "status": "fail",
        "account_type": "plus",
        "discarded_reason": "quota_refresh_401",
        "last_bind_status": "failed",
        "last_bind_failure_stage": "auth_401",
        "last_bind_message": (
            "刷新额度返回 401: token_expired: Provided authentication token is expired.，账号已标记为 Fail/废弃"
        ),
    }
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda _rows, email: account if email == "user@example.com" else None
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **payload: updated.append((email, payload)))
    monkeypatch.setattr(
        "autotoken.codex_auth.check_codex_quota",
        lambda *_args, **_kwargs: ("ok", {"plan_type": "plus", "weekly_pct": 1}),
    )

    routes = _routes(started)
    routes["post_accounts_refresh_quota"](AccountEmailBatchParams(emails=["user@example.com"]))
    run_result = started[0]["func"]("task-refresh")

    assert run_result["ok"][0]["email"] == "user@example.com"
    assert updated[0][1]["status"] == "active"
    assert updated[0][1]["discarded_reason"] == ""
    assert updated[0][1]["discarded_at"] is None
    assert updated[0][1]["last_bind_failure_stage"] == ""
    assert updated[0][1]["last_bind_message"] == ""


def test_refresh_quota_does_not_discard_network_error_accounts(tmp_path, monkeypatch):
    started = []
    updated = []
    account = {
        "email": "user@example.com",
        "auth_file": _auth_file(tmp_path, "temporary-forbidden"),
        "status": "active",
    }
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda _rows, email: account if email == "user@example.com" else None
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **payload: updated.append((email, payload)))
    monkeypatch.setattr("autotoken.codex_auth.check_codex_quota", lambda *_args, **_kwargs: ("network_error", None))

    routes = _routes(started)
    routes["post_accounts_refresh_quota"](AccountEmailBatchParams(emails=["user@example.com"]))
    run_result = started[0]["func"]("task-refresh")

    assert run_result["network_error"] == [{"email": "user@example.com", "reason": "network_error"}]
    assert run_result["failed"] == []
    assert updated == []


def test_refresh_quota_skips_resolver_path_outside_auth_boundaries(tmp_path, monkeypatch):
    started = []
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"access_token": "outside-token"}), encoding="utf-8")
    account = {"email": "user@example.com", "auth_file": str(outside), "status": "active"}
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda _rows, email: account if email == "user@example.com" else None
    )

    quota_calls = []
    monkeypatch.setattr(
        "autotoken.codex_auth.check_codex_quota", lambda *args, **kwargs: quota_calls.append((args, kwargs))
    )

    routes = _routes(started)
    routes["post_accounts_refresh_quota"](AccountEmailBatchParams(emails=["user@example.com"]))
    run_result = started[0]["func"]("task-refresh")

    assert run_result["skipped"] == [{"email": "user@example.com", "reason": "missing_auth_file"}]
    assert quota_calls == []


def test_refresh_quota_skips_oversized_auth_file(tmp_path, monkeypatch):
    started = []
    auth_file = tmp_path / "auths" / "huge.json"
    auth_file.write_text("x" * (AUTH_JSON_FILE_MAX_BYTES + 1), encoding="utf-8")
    account = {"email": "user@example.com", "auth_file": str(auth_file), "status": "active"}
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda _rows, email: account if email == "user@example.com" else None
    )

    quota_calls = []
    monkeypatch.setattr(
        "autotoken.codex_auth.check_codex_quota", lambda *args, **kwargs: quota_calls.append((args, kwargs))
    )

    routes = _routes(started)
    routes["post_accounts_refresh_quota"](AccountEmailBatchParams(emails=["user@example.com"]))
    run_result = started[0]["func"]("task-refresh")

    assert run_result["skipped"][0]["email"] == "user@example.com"
    assert run_result["skipped"][0]["reason"] == "invalid_auth_file"
    assert "认证文件过大" in run_result["skipped"][0]["error"]
    assert quota_calls == []


def test_refresh_quota_raises_404_when_no_accounts(monkeypatch):
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda _rows, _email: None)

    routes = _routes([])
    with pytest.raises(HTTPException) as exc_info:
        routes["post_accounts_refresh_quota"](AccountEmailBatchParams(emails=["missing@example.com"]))

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "账号不存在"


def test_refresh_quota_aligns_account_type_from_wham_plan_type(tmp_path, monkeypatch):
    started = []
    updated = []
    account = {
        "email": "user@example.com",
        "auth_file": _auth_file(tmp_path, "tok"),
        "status": "active",
        "account_type": "free",
    }
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda _rows, email: account if email == "user@example.com" else None
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **payload: updated.append((email, payload)))
    monkeypatch.setattr(
        "autotoken.codex_auth.check_codex_quota",
        lambda *_args, **_kwargs: (
            "ok",
            {
                "plan_type": "plus",
                "primary_pct": 12,
                "primary_resets_at": 1785000000,
                "primary_window_seconds": 18000,
                "weekly_pct": 98,
                "weekly_resets_at": 1785551222,
                "weekly_window_seconds": 604800,
            },
        ),
    )

    routes = _routes(started)
    routes["post_accounts_refresh_quota"](AccountEmailBatchParams(emails=["user@example.com"]))
    run_result = started[0]["func"]("task-refresh")

    assert run_result["ok"][0]["quota"]["plan_type"] == "plus"
    assert updated[0][0] == "user@example.com"
    assert updated[0][1]["account_type"] == "plus"
    assert updated[0][1]["last_quota"]["weekly_window_seconds"] == 604800


def test_refresh_quota_uses_subscription_plan_when_wham_returns_free_monthly_for_plus(tmp_path, monkeypatch):
    started = []
    updated = []
    account = {
        "email": "user@example.com",
        "auth_file": _auth_file(tmp_path, "tok", "acct_1"),
        "status": "active",
        "account_type": "free",
    }
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda _rows, email: account if email == "user@example.com" else None
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **payload: updated.append((email, payload)))

    wham_free_monthly = {
        "plan_type": "free",
        "checked_at": 1785526420,
        "windows": {
            "monthly": {
                "source": "primary_window",
                "used_percent": 0,
                "reset_at": None,
                "reset_after_seconds": None,
                "limit_window_seconds": 2592000,
            }
        },
        "monthly_pct": 0,
        "monthly_resets_at": None,
        "monthly_window_seconds": 2592000,
        "monthly_reset_after_seconds": None,
    }
    quota_calls = []

    def fake_check(token, account_id=None, **kwargs):
        quota_calls.append((token, account_id, kwargs))
        return "ok", wham_free_monthly.copy()

    monkeypatch.setattr("autotoken.codex_auth.check_codex_quota", fake_check)
    monkeypatch.setattr(
        "autotoken.api_routes.account_overview.query_chatgpt_subscription",
        lambda access_token, account_id="": {
            "raw": {
                "subscription": {"plan_type": "plus", "active": True, "paid": True},
                "account_check": {
                    "accounts": {
                        "acct_1": {
                            "account": {"plan_type": "plus"},
                            "entitlement": {"has_active_subscription": True, "subscription_plan": "chatgptplusplan"},
                        }
                    }
                },
            }
        },
    )

    routes = _routes(started)
    routes["post_accounts_refresh_quota"](AccountEmailBatchParams(emails=["user@example.com"]))
    run_result = started[0]["func"]("task-refresh")

    assert len(quota_calls) == 2
    assert run_result["ok"][0]["quota"]["plan_type"] == "plus"
    assert updated[0][1]["account_type"] == "plus"
    assert updated[0][1]["last_quota"]["plan_type"] == "plus"
    assert updated[0][1]["last_quota"]["weekly_pct"] == 0
    assert updated[0][1]["last_quota"]["weekly_window_seconds"] == 604800
    assert "monthly" in updated[0][1]["last_quota"]["windows"]


def test_refresh_quota_uses_second_wham_response_after_subscription_warmup(tmp_path, monkeypatch):
    started = []
    updated = []
    account = {
        "email": "user@example.com",
        "auth_file": _auth_file(tmp_path, "tok", "acct_1"),
        "status": "active",
        "account_type": "free",
    }
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda _rows, email: account if email == "user@example.com" else None
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **payload: updated.append((email, payload)))

    responses = [
        {
            "plan_type": "free",
            "checked_at": 1785526420,
            "windows": {"monthly": {"used_percent": 0, "limit_window_seconds": 2592000}},
            "monthly_pct": 0,
            "monthly_window_seconds": 2592000,
        },
        {
            "plan_type": "plus",
            "checked_at": 1785526422,
            "windows": {"weekly": {"used_percent": 12, "limit_window_seconds": 604800}},
            "weekly_pct": 12,
            "weekly_window_seconds": 604800,
        },
    ]

    def fake_check(*_args, **_kwargs):
        return "ok", responses.pop(0)

    monkeypatch.setattr("autotoken.codex_auth.check_codex_quota", fake_check)
    monkeypatch.setattr(
        "autotoken.api_routes.account_overview.query_chatgpt_subscription",
        lambda *_args, **_kwargs: {"raw": {"subscription": {"plan_type": "plus", "active": True, "paid": True}}},
    )

    routes = _routes(started)
    routes["post_accounts_refresh_quota"](AccountEmailBatchParams(emails=["user@example.com"]))
    run_result = started[0]["func"]("task-refresh")

    assert run_result["ok"][0]["quota"]["plan_type"] == "plus"
    assert updated[0][1]["account_type"] == "plus"
    assert updated[0][1]["last_quota"]["weekly_pct"] == 12
    assert updated[0][1]["last_quota"]["weekly_window_seconds"] == 604800


def test_refresh_quota_does_not_downgrade_existing_plus_when_subscription_check_temporarily_fails(
    tmp_path, monkeypatch
):
    started = []
    updated = []
    account = {
        "email": "user@example.com",
        "auth_file": _auth_file(tmp_path, "tok", "acct_1"),
        "status": "active",
        "account_type": "plus",
        "last_quota": {"plan_type": "plus", "weekly_pct": 0, "weekly_window_seconds": 604800},
    }
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda _rows, email: account if email == "user@example.com" else None
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **payload: updated.append((email, payload)))
    monkeypatch.setattr(
        "autotoken.codex_auth.check_codex_quota",
        lambda *_args, **_kwargs: (
            "ok",
            {
                "plan_type": "free",
                "checked_at": 1785526420,
                "windows": {"monthly": {"used_percent": 0, "limit_window_seconds": 2592000}},
                "monthly_pct": 0,
                "monthly_window_seconds": 2592000,
            },
        ),
    )

    def fail_subscription(*_args, **_kwargs):
        raise RuntimeError("temporary 403")

    monkeypatch.setattr("autotoken.api_routes.account_overview.query_chatgpt_subscription", fail_subscription)

    routes = _routes(started)
    routes["post_accounts_refresh_quota"](AccountEmailBatchParams(emails=["user@example.com"]))
    run_result = started[0]["func"]("task-refresh")

    assert run_result["ok"][0]["quota"]["plan_type"] == "plus"
    assert updated[0][1]["account_type"] == "plus"
    assert updated[0][1]["status"] == "active"
    assert updated[0][1]["last_quota"]["plan_type"] == "plus"
    assert updated[0][1]["last_quota"]["monthly_pct"] == 0


def test_refresh_quota_downgrades_existing_plus_when_subscription_confirms_free(tmp_path, monkeypatch):
    started = []
    updated = []
    account = {
        "email": "user@example.com",
        "auth_file": _auth_file(tmp_path, "tok", "acct_1"),
        "status": "active",
        "account_type": "plus",
        "last_quota": {"plan_type": "plus", "weekly_pct": 0, "weekly_window_seconds": 604800},
    }
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda _rows, email: account if email == "user@example.com" else None
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **payload: updated.append((email, payload)))
    monkeypatch.setattr(
        "autotoken.codex_auth.check_codex_quota",
        lambda *_args, **_kwargs: (
            "ok",
            {
                "plan_type": "free",
                "checked_at": 1785526420,
                "windows": {"monthly": {"used_percent": 0, "limit_window_seconds": 2592000}},
                "monthly_pct": 0,
                "monthly_window_seconds": 2592000,
            },
        ),
    )
    monkeypatch.setattr(
        "autotoken.api_routes.account_overview.query_chatgpt_subscription",
        lambda *_args, **_kwargs: {"raw": {"subscription": {"plan_type": "free", "active": True, "paid": False}}},
    )

    routes = _routes(started)
    routes["post_accounts_refresh_quota"](AccountEmailBatchParams(emails=["user@example.com"]))
    run_result = started[0]["func"]("task-refresh")

    assert run_result["ok"][0]["quota"]["plan_type"] == "free"
    assert updated[0][1]["account_type"] == "free"
    assert updated[0][1]["status"] == "personal"
    assert updated[0][1]["last_quota"]["plan_type"] == "free"


def test_refresh_quota_downgrades_existing_plus_when_subscription_confirms_free_even_if_wham_returns_plus(
    tmp_path, monkeypatch
):
    started = []
    updated = []
    account = {
        "email": "user@example.com",
        "auth_file": _auth_file(tmp_path, "tok", "acct_1"),
        "status": "plus",
        "account_type": "plus",
        "last_quota": {"plan_type": "plus", "weekly_pct": 0, "weekly_window_seconds": 604800},
    }
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda _rows, email: account if email == "user@example.com" else None
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **payload: updated.append((email, payload)))
    monkeypatch.setattr(
        "autotoken.codex_auth.check_codex_quota",
        lambda *_args, **_kwargs: (
            "ok",
            {
                "plan_type": "plus",
                "checked_at": 1785526420,
                "windows": {"weekly": {"used_percent": 1, "limit_window_seconds": 604800}},
                "weekly_pct": 1,
                "weekly_window_seconds": 604800,
            },
        ),
    )
    monkeypatch.setattr(
        "autotoken.api_routes.account_overview.query_chatgpt_subscription",
        lambda *_args, **_kwargs: {"raw": {"subscription": {"plan_type": "free", "active": False, "paid": False}}},
    )

    routes = _routes(started)
    routes["post_accounts_refresh_quota"](AccountEmailBatchParams(emails=["user@example.com"]))
    run_result = started[0]["func"]("task-refresh")

    assert run_result["ok"][0]["quota"]["plan_type"] == "free"
    assert updated[0][1]["account_type"] == "free"
    assert updated[0][1]["status"] == "personal"
    assert updated[0][1]["last_quota"]["plan_type"] == "free"


def test_refresh_quota_accepts_auth_session_access_token_casing(tmp_path, monkeypatch):
    started = []
    quota_calls = []
    updated = []
    session_file = tmp_path / "auth_session" / "user@example.com.json"
    session_file.write_text(
        json.dumps({"accessToken": "session-token", "account": {"id": "acct-session"}}), encoding="utf-8"
    )
    account = {"email": "user@example.com", "auth_file": str(session_file), "status": "active", "account_type": "free"}
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda _rows, email: account if email == "user@example.com" else None
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **payload: updated.append((email, payload)))

    def fake_check(token, account_id=None, **_kwargs):
        quota_calls.append((token, account_id))
        return "ok", {"plan_type": "free", "primary_pct": 1}

    monkeypatch.setattr("autotoken.codex_auth.check_codex_quota", fake_check)
    monkeypatch.setattr(
        "autotoken.api_routes.account_overview.query_chatgpt_subscription",
        lambda *_args, **_kwargs: {"raw": {"subscription": {"plan_type": "free", "active": False, "paid": False}}},
    )

    routes = _routes(started, progress=[], main_email="owner@example.com")
    routes["post_accounts_refresh_quota"](AccountEmailBatchParams(emails=["user@example.com"]))
    run_result = started[0]["func"]("task-refresh")

    assert quota_calls == [("session-token", "acct-session")]
    assert run_result["skipped"] == []
    assert updated[0][1]["last_quota"] == {"plan_type": "free", "primary_pct": 1}


def test_refresh_quota_accepts_nested_auth_session_access_token(tmp_path, monkeypatch):
    started = []
    quota_calls = []
    updated = []
    auth_payload = {
        "status": 200,
        "data": {
            "accessToken": "nested-session-token",
            "account": {"id": "acct-nested"},
        },
    }
    session_file = tmp_path / "auth_session" / "user@example.com.json"
    session_file.write_text(json.dumps(auth_payload), encoding="utf-8")
    account = {"email": "user@example.com", "auth_file": str(session_file), "status": "active", "account_type": "free"}
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda _rows, email: account if email == "user@example.com" else None
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **payload: updated.append((email, payload)))

    def fake_check(token, account_id=None, **_kwargs):
        quota_calls.append((token, account_id))
        return "ok", {"plan_type": "free", "primary_pct": 1}

    monkeypatch.setattr("autotoken.codex_auth.check_codex_quota", fake_check)
    monkeypatch.setattr(
        "autotoken.api_routes.account_overview.query_chatgpt_subscription",
        lambda *_args, **_kwargs: {"raw": {"subscription": {"plan_type": "free", "active": False, "paid": False}}},
    )

    routes = _routes(started, progress=[], main_email="owner@example.com")
    routes["post_accounts_refresh_quota"](AccountEmailBatchParams(emails=["user@example.com"]))
    run_result = started[0]["func"]("task-refresh")

    assert quota_calls == [("nested-session-token", "acct-nested")]
    assert run_result["skipped"] == []
    assert updated[0][1]["last_quota"] == {"plan_type": "free", "primary_pct": 1}


def test_refresh_quota_passes_auth_session_context_to_wham_usage(tmp_path, monkeypatch):
    started = []
    quota_calls = []
    updated = []
    auth_payload = {
        "accessToken": "session-token",
        "account": {"id": "acct-session"},
        "cookie_header": "oai-did=device; session=abc",
        "openai_sentinel_token": "sentinel",
        "oai_client_version": "prod-version",
        "oai_client_build_number": "1234567",
        "oai_device_id": "device-id",
    }
    session_file = tmp_path / "auth_session" / "user@example.com.json"
    session_file.write_text(json.dumps(auth_payload), encoding="utf-8")
    account = {"email": "user@example.com", "auth_file": str(session_file), "status": "active", "account_type": "free"}
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda _rows, email: account if email == "user@example.com" else None
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **payload: updated.append((email, payload)))

    def fake_check(token, account_id=None, **kwargs):
        quota_calls.append((token, account_id, kwargs))
        return "ok", {"plan_type": "free", "primary_pct": 1}

    monkeypatch.setattr("autotoken.codex_auth.check_codex_quota", fake_check)
    monkeypatch.setattr(
        "autotoken.api_routes.account_overview.query_chatgpt_subscription",
        lambda *_args, **_kwargs: {"raw": {"subscription": {"plan_type": "free", "active": False, "paid": False}}},
    )

    routes = _routes(started, progress=[], main_email="owner@example.com")
    routes["post_accounts_refresh_quota"](AccountEmailBatchParams(emails=["user@example.com"]))
    run_result = started[0]["func"]("task-refresh")

    assert quota_calls == [("session-token", "acct-session", {"timeout": 25, "auth_data": auth_payload})]
    assert run_result["ok"][0]["email"] == "user@example.com"
    assert updated[0][1]["last_quota"] == {"plan_type": "free", "primary_pct": 1}


def test_refresh_quota_defaults_to_eight_concurrency_for_large_batches(tmp_path, monkeypatch):
    started = []
    rows = [
        {"email": f"user{i}@example.com", "auth_file": _auth_file(tmp_path, f"tok{i}"), "status": "active"}
        for i in range(12)
    ]
    monkeypatch.delenv("REFRESH_QUOTA_CONCURRENCY", raising=False)
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: rows)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "autotoken.codex_auth.check_codex_quota", lambda *_args, **_kwargs: ("ok", {"plan_type": "free"})
    )

    routes = _routes(started)
    routes["post_accounts_refresh_quota"](AccountEmailBatchParams(emails=[row["email"] for row in rows]))
    run_result = started[0]["func"]("task-refresh")

    assert run_result["concurrency"] == 8
