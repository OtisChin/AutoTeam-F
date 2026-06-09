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

    assert result == {"task_id": "task-1", "command": "refresh-quota", "params": {"emails": ["active@example.com"], "missing": []}}
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


def test_refresh_quota_marks_auth_error_accounts_fail(tmp_path, monkeypatch):
    started = []
    updated = []
    account = {"email": "user@example.com", "auth_file": _auth_file(tmp_path, "bad"), "status": "active"}
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda _rows, email: account if email == "user@example.com" else None)
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **payload: updated.append((email, payload)))
    monkeypatch.setattr("autotoken.codex_auth.check_codex_quota", lambda *_args, **_kwargs: ("auth_error", {}))

    routes = _routes(started)
    routes["post_accounts_refresh_quota"](AccountEmailBatchParams(emails=["user@example.com"]))
    run_result = started[0]["func"]("task-refresh")

    assert run_result["failed"] == [{"email": "user@example.com", "reason": "auth_error"}]
    assert updated[0][0] == "user@example.com"
    assert updated[0][1]["status"] == "fail"
    assert updated[0][1]["discarded_reason"] == "quota_refresh_401"


def test_refresh_quota_skips_resolver_path_outside_auth_boundaries(tmp_path, monkeypatch):
    started = []
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"access_token": "outside-token"}), encoding="utf-8")
    account = {"email": "user@example.com", "auth_file": str(outside), "status": "active"}
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda _rows, email: account if email == "user@example.com" else None)

    quota_calls = []
    monkeypatch.setattr("autotoken.codex_auth.check_codex_quota", lambda *args, **kwargs: quota_calls.append((args, kwargs)))

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
    monkeypatch.setattr("autotoken.accounts.find_account", lambda _rows, email: account if email == "user@example.com" else None)

    quota_calls = []
    monkeypatch.setattr("autotoken.codex_auth.check_codex_quota", lambda *args, **kwargs: quota_calls.append((args, kwargs)))

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
