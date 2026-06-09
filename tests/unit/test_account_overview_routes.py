import json

from fastapi import FastAPI, HTTPException

from autotoken import accounts, auth_session_store, auth_storage, codex_auth
from autotoken.api_routes.account_overview import create_account_overview_router
from autotoken.storage.auth_files import AUTH_JSON_FILE_MAX_BYTES


def _app(*, loaded_accounts=None, sanitized_accounts=None, sanitize_account=None, is_main_account_email=None):
    loaded_accounts = loaded_accounts if loaded_accounts is not None else []
    sanitized_accounts = sanitized_accounts if sanitized_accounts is not None else loaded_accounts
    captured = {}
    app = FastAPI()

    def fake_load_accounts_with_session_stubs(**kwargs):
        captured["include_session_stubs"] = kwargs.get("include_session_stubs")
        return loaded_accounts

    app.include_router(
        create_account_overview_router(
            load_accounts_with_session_stubs=fake_load_accounts_with_session_stubs,
            sanitize_accounts_batch=lambda _accounts, _quota_cache: sanitized_accounts,
            sanitize_account=sanitize_account or (lambda account: {**account, "sanitized": True}),
            is_main_account_email=is_main_account_email or (lambda _email: False),
        )
    )
    return app, captured


def _endpoint(app, path, method):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"missing route {method} {path}")


def test_account_overview_list_delegates_loading_and_sanitization():
    app, captured = _app(
        loaded_accounts=[{"email": "raw@example.com"}],
        sanitized_accounts=[{"email": "safe@example.com"}],
    )

    result = _endpoint(app, "/api/accounts", "GET")(include_session_stubs=False)

    assert result == [{"email": "safe@example.com"}]
    assert captured["include_session_stubs"] is False


def test_account_overview_active_and_standby_routes_sanitize_accounts(monkeypatch):
    app, _captured = _app()

    monkeypatch.setattr(accounts, "get_active_accounts", lambda: [{"email": "active@example.com"}])
    monkeypatch.setattr(accounts, "get_standby_accounts", lambda: [{"email": "standby@example.com"}])

    assert _endpoint(app, "/api/accounts/active", "GET")() == [
        {"email": "active@example.com", "sanitized": True}
    ]
    assert _endpoint(app, "/api/accounts/standby", "GET")() == [
        {"email": "standby@example.com", "sanitized": True}
    ]


def test_account_overview_codex_auth_exports_account_auth_file(monkeypatch, tmp_path):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    auth_file = auth_dir / "codex-user.json"
    auth_file.write_text(
        json.dumps(
            {
                "id_token": "id-token",
                "accessToken": "access-token",
                "refresh_token": "refresh-token",
                "account": {"id": "account-1"},
                "last_refresh": "2026-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    app, _captured = _app()

    monkeypatch.setattr(auth_storage, "AUTH_DIR", auth_dir)
    monkeypatch.setattr(accounts, "load_accounts", lambda: [{"email": "user@example.com", "auth_file": str(auth_file)}])
    monkeypatch.setattr(accounts, "find_account", lambda loaded, email: loaded[0] if email == "user@example.com" else None)

    result = _endpoint(app, "/api/accounts/{email}/codex-auth", "GET")(" User@example.com ")

    assert result["email"] == "user@example.com"
    assert result["auth_file"] == str(auth_file)
    assert result["codex_auth"]["tokens"] == {
        "id_token": "id-token",
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "account_id": "account-1",
    }


def test_account_overview_codex_auth_rejects_oversized_auth_file(monkeypatch, tmp_path):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    auth_file = auth_dir / "codex-user.json"
    auth_file.write_text("x" * (AUTH_JSON_FILE_MAX_BYTES + 1), encoding="utf-8")
    app, _captured = _app()

    monkeypatch.setattr(auth_storage, "AUTH_DIR", auth_dir)
    monkeypatch.setattr(accounts, "load_accounts", lambda: [{"email": "user@example.com", "auth_file": str(auth_file)}])
    monkeypatch.setattr(accounts, "find_account", lambda loaded, email: loaded[0] if email == "user@example.com" else None)

    try:
        _endpoint(app, "/api/accounts/{email}/codex-auth", "GET")("user@example.com")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "认证文件无法读取" in exc.detail
    else:
        raise AssertionError("oversized auth file must fail")


def test_account_overview_codex_auth_ignores_account_auth_file_outside_auth_dir(monkeypatch, tmp_path):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    outside_file = tmp_path / "outside.json"
    outside_file.write_text(json.dumps({"access_token": "outside-token"}), encoding="utf-8")
    app, _captured = _app()

    monkeypatch.setattr(auth_storage, "AUTH_DIR", auth_dir)
    monkeypatch.setattr(accounts, "load_accounts", lambda: [{"email": "user@example.com", "auth_file": str(outside_file)}])
    monkeypatch.setattr(accounts, "find_account", lambda loaded, email: loaded[0] if email == "user@example.com" else None)
    monkeypatch.setattr("autotoken.auth_session_store.get_auth_session_file", lambda _email: "")

    try:
        _endpoint(app, "/api/accounts/{email}/codex-auth", "GET")("user@example.com")
    except HTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "该账号没有认证文件"
    else:
        raise AssertionError("account auth_file outside AUTH_DIR must not be exported")


def test_account_overview_codex_auth_ignores_session_file_outside_session_dir(monkeypatch, tmp_path):
    auth_dir = tmp_path / "auths"
    session_dir = tmp_path / "sessions"
    auth_dir.mkdir()
    session_dir.mkdir()
    outside_file = tmp_path / "outside-session.json"
    outside_file.write_text(json.dumps({"access_token": "outside-token"}), encoding="utf-8")
    app, _captured = _app()

    monkeypatch.setattr(auth_storage, "AUTH_DIR", auth_dir)
    monkeypatch.setattr(auth_session_store, "AUTH_SESSION_DIR", session_dir)
    monkeypatch.setattr(accounts, "load_accounts", lambda: [{"email": "user@example.com", "auth_file": ""}])
    monkeypatch.setattr(accounts, "find_account", lambda loaded, email: loaded[0] if email == "user@example.com" else None)
    monkeypatch.setattr(auth_session_store, "get_auth_session_file", lambda _email: str(outside_file))

    try:
        _endpoint(app, "/api/accounts/{email}/codex-auth", "GET")("user@example.com")
    except HTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "该账号没有认证文件"
    else:
        raise AssertionError("auth_session path outside AUTH_SESSION_DIR must not be exported")


def test_account_overview_codex_auth_uses_main_auth_file(monkeypatch, tmp_path):
    auth_file = tmp_path / "codex-main.json"
    auth_file.write_text(json.dumps({"access_token": "main-token", "account_id": "main-account"}), encoding="utf-8")
    app, _captured = _app(is_main_account_email=lambda email: email == "owner@example.com")

    monkeypatch.setattr(codex_auth, "get_saved_main_auth_file", lambda: str(auth_file))

    result = _endpoint(app, "/api/accounts/{email}/codex-auth", "GET")("owner@example.com")

    assert result["codex_auth"]["tokens"]["access_token"] == "main-token"
    assert result["codex_auth"]["tokens"]["account_id"] == "main-account"


def test_account_overview_codex_auth_reports_missing_files(monkeypatch):
    app, _captured = _app()

    monkeypatch.setattr(accounts, "load_accounts", lambda: [])
    monkeypatch.setattr(accounts, "find_account", lambda _loaded, _email: None)

    try:
        _endpoint(app, "/api/accounts/{email}/codex-auth", "GET")("missing@example.com")
    except HTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "该账号没有认证文件"
    else:
        raise AssertionError("missing account auth file must fail")
