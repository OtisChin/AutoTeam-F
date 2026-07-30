import base64
import io
import json
import os
import zipfile
from pathlib import Path

import anyio
import pytest
from fastapi.responses import JSONResponse
from starlette.requests import Request

from autotoken import api
from autotoken.api_routes.account_cpa_auths import (
    AccountCpaAuthImportParams,
    AccountCpaAuthImportSource,
    AccountSessionCpaConvertParams,
    create_account_cpa_auths_router,
)
from autotoken.api_routes.config_io import (
    OUTLOOK_ACCOUNTS_IMPORT_MAX_BYTES,
    ICloudAccountsDeleteParams,
    ICloudAccountsImportParams,
    OutlookAccountsDeleteParams,
    OutlookAccountsImportParams,
    create_config_io_router,
)
from autotoken.api_routes.setup import SetupConfig, create_setup_router
from autotoken.api_routes.status import build_status_response
from autotoken.storage.auth_files import AUTH_JSON_FILE_MAX_BYTES


async def _request_app(method: str, path: str) -> tuple[int, bytes]:
    messages = []
    request_sent = False

    async def receive():
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    await api.app(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "root_path": "",
        },
        receive,
        send,
    )
    status = next(message["status"] for message in messages if message["type"] == "http.response.start")
    body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    return status, body


def _build_api_status(include_session_stubs: bool = True):
    return build_status_response(
        load_accounts_with_session_stubs=api._load_accounts_with_session_stubs,
        sanitize_accounts_batch=api._sanitize_accounts_batch,
        include_session_stubs=include_session_stubs,
    )


def _import_account_cpa_auths(params: AccountCpaAuthImportParams):
    routes = {route.endpoint.__name__: route.endpoint for route in create_account_cpa_auths_router().routes}
    return routes["import_account_cpa_auths"](params)


def test_extract_account_access_token_ignores_account_auth_file_outside_auth_dir(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"access_token": "outside-token"}), encoding="utf-8")

    monkeypatch.setattr("autotoken.storage.auth_storage.AUTH_DIR", auth_dir)
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "user@example.com", "auth_file": str(outside)}])
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda loaded, email: loaded[0] if email == "user@example.com" else None,
    )
    monkeypatch.setattr("autotoken.storage.auth_session_store.get_auth_session_file", lambda _email: "")

    assert api._extract_account_access_token("user@example.com") == ""


def test_extract_account_access_token_accepts_account_auth_file_inside_auth_dir(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    auth_file = auth_dir / "codex-user@example.com-plus-deadbeef.json"
    auth_file.write_text(json.dumps({"access_token": "inside-token"}), encoding="utf-8")

    monkeypatch.setattr("autotoken.storage.auth_storage.AUTH_DIR", auth_dir)
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "user@example.com", "auth_file": str(auth_file)}])
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda loaded, email: loaded[0] if email == "user@example.com" else None,
    )

    assert api._extract_account_access_token("user@example.com") == "inside-token"


def test_extract_account_access_token_ignores_oversized_auth_file(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    auth_file = auth_dir / "codex-user@example.com-plus-deadbeef.json"
    auth_file.write_text("x" * (AUTH_JSON_FILE_MAX_BYTES + 1), encoding="utf-8")

    monkeypatch.setattr("autotoken.storage.auth_storage.AUTH_DIR", auth_dir)
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "user@example.com", "auth_file": str(auth_file)}])
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda loaded, email: loaded[0] if email == "user@example.com" else None,
    )

    assert api._extract_account_access_token("user@example.com") == ""


def test_extract_account_access_token_ignores_session_file_outside_session_dir(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    session_dir = tmp_path / "auth_session"
    auth_dir.mkdir()
    session_dir.mkdir()
    outside = tmp_path / "outside-session.json"
    outside.write_text(json.dumps({"access_token": "outside-token"}), encoding="utf-8")

    monkeypatch.setattr("autotoken.storage.auth_storage.AUTH_DIR", auth_dir)
    monkeypatch.setattr("autotoken.storage.auth_session_store.AUTH_SESSION_DIR", session_dir)
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "user@example.com", "auth_file": ""}])
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda loaded, email: loaded[0] if email == "user@example.com" else None,
    )
    monkeypatch.setattr("autotoken.storage.auth_session_store.get_auth_session_file", lambda _email: str(outside))

    assert api._extract_account_access_token("user@example.com") == ""


def test_valid_token_item_auth_file_ignores_outside_auth_file(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")

    monkeypatch.setattr("autotoken.storage.auth_storage.AUTH_DIR", auth_dir)
    monkeypatch.setattr("autotoken.storage.auth_session_store.get_auth_session_file", lambda _email: "")

    assert api._valid_token_item_auth_file({"email": "user@example.com", "auth_file": str(outside)}) == ""


def test_valid_token_item_auth_file_accepts_auth_dir_file(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    auth_file = auth_dir / "codex-user@example.com-plus-deadbeef.json"
    auth_file.write_text("{}", encoding="utf-8")

    monkeypatch.setattr("autotoken.storage.auth_storage.AUTH_DIR", auth_dir)

    assert api._valid_token_item_auth_file({"email": "user@example.com", "auth_file": str(auth_file)}) == str(auth_file)


def test_valid_token_item_auth_file_accepts_matching_session_file(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    session_dir = tmp_path / "auth_session"
    session_dir.mkdir()
    session_file = session_dir / "user@example_com.json"
    session_file.write_text("{}", encoding="utf-8")

    monkeypatch.setattr("autotoken.storage.auth_storage.AUTH_DIR", auth_dir)
    monkeypatch.setattr("autotoken.storage.auth_session_store.AUTH_SESSION_DIR", session_dir)

    assert api._valid_token_item_auth_file({"email": "user@example.com", "auth_file": str(session_file)}) == str(
        session_file
    )


def test_valid_token_item_auth_file_ignores_session_file_outside_session_dir(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    session_dir = tmp_path / "auth_session"
    auth_dir.mkdir()
    session_dir.mkdir()
    outside = tmp_path / "outside-session.json"
    outside.write_text("{}", encoding="utf-8")

    monkeypatch.setattr("autotoken.storage.auth_storage.AUTH_DIR", auth_dir)
    monkeypatch.setattr("autotoken.storage.auth_session_store.AUTH_SESSION_DIR", session_dir)
    monkeypatch.setattr("autotoken.storage.auth_session_store.get_auth_session_file", lambda _email: str(outside))

    assert api._valid_token_item_auth_file({"email": "user@example.com", "auth_file": str(outside)}) == ""


def test_verify_plus_plan_ignores_outside_auth_file_token(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"access_token": "outside-token"}), encoding="utf-8")

    monkeypatch.setattr("autotoken.storage.auth_storage.AUTH_DIR", auth_dir)
    monkeypatch.setattr("autotoken.storage.auth_session_store.get_auth_session_file", lambda _email: "")
    monkeypatch.setenv("OPENAI_PLAN_VERIFY_ATTEMPTS", "1")
    monkeypatch.setenv("OPENAI_PLAN_VERIFY_INTERVAL_SECONDS", "0")

    probed_tokens = []

    def fake_probe(access_token, _account_id):
        probed_tokens.append(access_token)
        return {"ok": False, "reason": "missing_token"}

    monkeypatch.setattr(api, "_probe_openai_plan", fake_probe)

    result = api._verify_plus_plan({"email": "user@example.com", "auth_file": str(outside)})

    assert result["ok"] is False
    assert probed_tokens == [""]


def test_verify_plus_plan_accepts_matching_session_file(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    session_dir = tmp_path / "auth_session"
    auth_dir.mkdir()
    session_dir.mkdir()
    session_file = session_dir / "user@example_com.json"
    session_file.write_text(json.dumps({"access_token": "session-token", "account_id": "account-id"}), encoding="utf-8")

    monkeypatch.setattr("autotoken.storage.auth_storage.AUTH_DIR", auth_dir)
    monkeypatch.setattr("autotoken.storage.auth_session_store.AUTH_SESSION_DIR", session_dir)
    monkeypatch.setattr("autotoken.storage.auth_session_store.get_auth_session_file", lambda _email: str(session_file))
    monkeypatch.setenv("OPENAI_PLAN_VERIFY_ATTEMPTS", "1")
    monkeypatch.setenv("OPENAI_PLAN_VERIFY_INTERVAL_SECONDS", "0")

    probed = {}

    def fake_probe(access_token, account_id):
        probed["access_token"] = access_token
        probed["account_id"] = account_id
        return {"ok": True, "plan_type": "plus"}

    monkeypatch.setattr(api, "_probe_openai_plan", fake_probe)

    result = api._verify_plus_plan({"email": "user@example.com", "auth_file": str(session_file)})

    assert result["ok"] is True
    assert result["plan_type"] == "plus"
    assert probed == {"access_token": "session-token", "account_id": "account-id"}


def test_save_refreshed_auth_file_ignores_outside_auth_file(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"access_token": "old-token"}), encoding="utf-8")

    monkeypatch.setattr("autotoken.storage.auth_storage.AUTH_DIR", auth_dir)

    api._save_refreshed_auth_file(
        str(outside),
        {"access_token": "old-token", "refresh_token": "refresh-old"},
        {"access_token": "new-token", "refresh_token": "refresh-new"},
    )

    assert json.loads(outside.read_text(encoding="utf-8")) == {"access_token": "old-token"}


def test_save_refreshed_auth_file_accepts_auth_dir_file(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    auth_file = auth_dir / "codex-user@example.com-plus-deadbeef.json"
    auth_file.write_text(json.dumps({"access_token": "old-token", "refresh_token": "refresh-old"}), encoding="utf-8")

    monkeypatch.setattr("autotoken.storage.auth_storage.AUTH_DIR", auth_dir)
    monkeypatch.setattr("autotoken.storage.auth_index.upsert_codex_auth_file", lambda *_args, **_kwargs: None)

    api._save_refreshed_auth_file(
        str(auth_file),
        {"access_token": "old-token", "refresh_token": "refresh-old"},
        {"access_token": "new-token", "refresh_token": "refresh-new"},
    )

    saved = json.loads(auth_file.read_text(encoding="utf-8"))
    assert saved["access_token"] == "new-token"
    assert saved["refresh_token"] == "refresh-new"


def test_auto_check_active_auth_items_ignores_outside_auth_file(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    inside = auth_dir / "codex-active@example.com-team-deadbeef.json"
    inside.write_text("{}", encoding="utf-8")
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")

    monkeypatch.setattr("autotoken.storage.auth_storage.AUTH_DIR", auth_dir)
    monkeypatch.setattr(api, "_is_main_account_email", lambda email: email == "owner@example.com")

    items = api._auto_check_active_auth_items(
        [
            {"email": "active@example.com", "status": "active", "auth_file": str(inside)},
            {"email": "outside@example.com", "status": "active", "auth_file": str(outside)},
            {"email": "owner@example.com", "status": "active", "auth_file": str(inside)},
            {"email": "standby@example.com", "status": "standby", "auth_file": str(inside)},
        ]
    )

    assert items == [({"email": "active@example.com", "status": "active", "auth_file": str(inside)}, str(inside))]


def _convert_account_session_cpa_auths(params: AccountSessionCpaConvertParams):
    routes = {
        route.endpoint.__name__: route.endpoint
        for route in create_account_cpa_auths_router(
            normalize_email=api._normalized_email,
            convert_account_auth_session_to_cpa_auth=api._convert_account_auth_session_to_cpa_auth,
            is_main_account_email=api._is_main_account_email,
        ).routes
    }
    return routes["convert_account_session_cpa_auths"](params)


def _setup_routes():
    return {
        route.endpoint.__name__: route.endpoint
        for route in create_setup_router(
            get_api_key=lambda: api.API_KEY,
            set_api_key=lambda value: setattr(api, "API_KEY", value),
        ).routes
    }


def _config_io_routes():
    return {
        route.endpoint.__name__: route.endpoint
        for route in create_config_io_router(
            auto_check_config=api._auto_check_config,
            auto_check_restart=api._auto_check_restart,
            auto_refresh_quota_config=api._auto_refresh_quota_config,
            auto_refresh_quota_restart=api._auto_refresh_quota_restart,
            save_auto_refresh_quota_config=api._save_auto_refresh_quota_config,
            get_api_key=lambda: api.API_KEY,
            set_api_key=lambda value: setattr(api, "API_KEY", value),
            current_time=lambda: 123.0,
        ).routes
    }


def _b64url(payload):
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


def _session_access_jwt(email="user@example.com", account_id="acc-1"):
    return (
        f"{_b64url({'alg': 'none', 'typ': 'JWT'})}."
        f"{_b64url({'exp': 1786026576, 'https://api.openai.com/auth': {'chatgpt_account_id': account_id, 'chatgpt_plan_type': 'plus'}, 'https://api.openai.com/profile': {'email': email}})}."
        "sig"
    )


def _cpa_import_auth(email="free@example.com", account_id="acc-free"):
    return {
        "type": "codex",
        "email": email,
        "account_id": account_id,
        "access_token": "access-token",
        "id_token": "id-token",
        "refresh_token": "refresh-token",
        "expired": "2030-01-01T00:00:00Z",
        "last_refresh": "2026-01-01T00:00:00Z",
    }


def test_get_status_normalizes_main_account_status_from_saved_auth(tmp_path, monkeypatch):
    main_email = "owner@example.com"
    auth_file = tmp_path / "codex-main.json"
    auth_file.write_text(json.dumps({"access_token": "token-main"}), encoding="utf-8")

    monkeypatch.setattr(
        "autotoken.accounts.load_accounts",
        lambda: [
            {
                "email": main_email,
                "status": "exhausted",
                "auth_file": "/app/auths/codex-main.json",
                "last_quota": {
                    "primary_pct": 8,
                    "primary_resets_at": 1710000000,
                    "weekly_pct": 1,
                    "weekly_resets_at": 1710600000,
                },
            }
        ],
    )
    monkeypatch.setattr("autotoken.auth_session_store.list_auth_session_emails", lambda: [])
    monkeypatch.setattr(api, "_is_main_account_email", lambda email: email == main_email)
    monkeypatch.setattr("autotoken.codex_auth.get_saved_main_auth_file", lambda: str(auth_file))
    monkeypatch.setattr(
        "autotoken.codex_auth.check_codex_quota",
        lambda access_token: (
            "ok",
            {
                "primary_pct": 8,
                "primary_resets_at": 1710000000,
                "weekly_pct": 1,
                "weekly_resets_at": 1710600000,
            },
        ),
    )

    result = _build_api_status()

    assert result["quota_cache"][main_email]["primary_pct"] == 8
    assert result["accounts"][0]["is_main_account"] is True
    assert result["accounts"][0]["status"] == "active"
    assert result["summary"] == {
        "active": 1,
        "standby": 0,
        "exhausted": 0,
        "pending": 0,
        "auth_invalid": 0,
        "orphan": 0,
        "fail": 0,
        "free": 0,
        "team": 1,
        "plus": 0,
        "pro": 0,
        "total": 1,
    }


def test_api_app_uses_lifespan_without_deprecated_event_handlers():
    assert callable(api.app.router.lifespan_context)
    assert api.app.router.on_startup == []
    assert api.app.router.on_shutdown == []


def test_start_server_sets_local_base_url_from_requested_port(monkeypatch):
    captured = {}

    monkeypatch.delenv("AUTOTOKEN_LOCAL_BASE_URL", raising=False)
    monkeypatch.setattr("autotoken.setup_wizard.check_and_setup", lambda interactive: None)
    monkeypatch.setattr(
        "uvicorn.run",
        lambda app, host, port, log_level: captured.update(
            {"app": app, "host": host, "port": port, "log_level": log_level}
        ),
    )

    api.start_server(host="0.0.0.0", port=8899)

    assert os.environ["AUTOTOKEN_LOCAL_BASE_URL"] == "http://127.0.0.1:8899"
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 8899


def test_start_server_keeps_explicit_local_base_url(monkeypatch):
    monkeypatch.setenv("AUTOTOKEN_LOCAL_BASE_URL", "https://public.example.com")
    monkeypatch.setattr("autotoken.setup_wizard.check_and_setup", lambda interactive: None)
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: None)

    api.start_server(host="127.0.0.1", port=8899)

    assert os.environ["AUTOTOKEN_LOCAL_BASE_URL"] == "https://public.example.com"


@pytest.mark.parametrize("method", ["GET", "POST", "PUT"])
def test_unknown_api_paths_return_standard_not_found(method, monkeypatch):
    monkeypatch.setattr(api, "API_KEY", "")
    status, body = anyio.run(_request_app, method, "/api/unknown")

    assert status == 404
    assert json.loads(body) == {"detail": "Not Found"}


@pytest.mark.parametrize("path", ["/", "/dashboard/nested"])
def test_frontend_fallback_still_serves_non_api_paths(path):
    status, body = anyio.run(_request_app, "GET", path)

    assert status == 200
    assert b'<div id="app"></div>' in body


def test_normalize_access_token_preserves_trailing_s():
    assert api._normalize_access_token("Bearer new-access,") == "new-access"


def test_auth_middleware_allows_cors_preflight_without_api_key(monkeypatch):
    monkeypatch.setattr(api, "API_KEY", "secret")
    request = Request(
        {
            "type": "http",
            "method": "OPTIONS",
            "path": "/api/public/plus-extractor/cdk-status",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "scheme": "http",
            "client": ("testclient", 123),
        }
    )
    called = False

    async def call_next(_request):
        nonlocal called
        called = True
        return JSONResponse({"ok": True})

    response = anyio.run(api.auth_middleware, request, call_next)

    assert called is True
    assert response.status_code == 200


def test_sanitize_account_keeps_exportable_main_account_active_without_live_quota(tmp_path, monkeypatch):
    main_email = "owner@example.com"
    auth_file = tmp_path / "codex-main.json"
    auth_file.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(api, "_is_main_account_email", lambda email: email == main_email)
    monkeypatch.setattr("autotoken.codex_auth.get_saved_main_auth_file", lambda: str(auth_file))

    sanitized = api._sanitize_account(
        {"email": main_email, "status": "exhausted", "auth_file": "/app/auths/missing.json"}
    )

    assert sanitized["is_main_account"] is True
    assert sanitized["status"] == "active"


def test_sanitize_account_marks_auth_session_only_account_needs_codex_login(tmp_path, monkeypatch):
    session_file = tmp_path / "auth_session" / "user@example_com.json"
    session_file.parent.mkdir(parents=True)
    session_file.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)
    monkeypatch.setattr("autotoken.auth_storage.AUTH_DIR", tmp_path / "auths")
    monkeypatch.setattr("autotoken.auth_session_store.get_auth_session_file", lambda _email: str(session_file))

    sanitized = api._sanitize_account({"email": "user@example.com", "status": "active", "auth_file": str(session_file)})

    assert sanitized["auth_session_file"] == str(session_file)
    assert sanitized["codex_auth_file"] == ""
    assert sanitized["has_codex_auth_file"] is False
    assert sanitized["needs_codex_login"] is True


def test_get_status_counts_auth_session_only_accounts(monkeypatch):
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [])
    monkeypatch.setattr(
        "autotoken.auth_session_store.list_auth_session_emails",
        lambda: ["session-one@example.com", "Session-Two@Example.com"],
    )
    monkeypatch.setattr("autotoken.auth_session_store.get_auth_session_file", lambda _email: "")
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)

    result = _build_api_status()

    assert [acc["email"] for acc in result["accounts"]] == [
        "session-one@example.com",
        "session-two@example.com",
    ]
    assert result["summary"]["active"] == 2
    assert result["summary"]["free"] == 2
    assert result["summary"]["total"] == 2


def test_sanitize_account_marks_codex_auth_file_as_logged_in(tmp_path, monkeypatch):
    auth_dir = tmp_path / "data" / "auths"
    auth_file = auth_dir / "codex-user@example.com-free-deadbeef.json"
    auth_dir.mkdir(parents=True)
    auth_file.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)
    monkeypatch.setattr("autotoken.auth_storage.AUTH_DIR", auth_dir)
    monkeypatch.setattr("autotoken.auth_session_store.get_auth_session_file", lambda _email: "")

    sanitized = api._sanitize_account({"email": "user@example.com", "status": "active", "auth_file": str(auth_file)})

    assert sanitized["codex_auth_file"] == str(auth_file)
    assert sanitized["has_codex_auth_file"] is True
    assert sanitized["codex_auth_synthetic"] is False
    assert sanitized["needs_codex_login"] is False


def test_sanitize_account_marks_synthetic_codex_auth_file_needs_login(tmp_path, monkeypatch):
    auth_dir = tmp_path / "data" / "auths"
    auth_file = auth_dir / "codex-user@example.com-plus-deadbeef.json"
    auth_dir.mkdir(parents=True)
    auth_file.write_text(json.dumps({"id_token_synthetic": True}), encoding="utf-8")

    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)
    monkeypatch.setattr("autotoken.auth_storage.AUTH_DIR", auth_dir)
    monkeypatch.setattr("autotoken.auth_session_store.get_auth_session_file", lambda _email: "")

    sanitized = api._sanitize_account({"email": "user@example.com", "status": "active", "auth_file": str(auth_file)})

    assert sanitized["codex_auth_file"] == str(auth_file)
    assert sanitized["has_codex_auth_file"] is True
    assert sanitized["codex_auth_synthetic"] is True
    assert sanitized["needs_codex_login"] is True


def test_post_setup_save_keeps_cpa_optional_and_generates_api_key(monkeypatch):
    written = {}

    def fake_write_env(key, value):
        written[key] = value

    monkeypatch.setattr("autotoken.setup_wizard._write_env", fake_write_env)
    monkeypatch.setattr("autotoken.setup_wizard._verify_temporary_email", lambda: True)
    monkeypatch.setattr("autotoken.setup_wizard._verify_cpa", lambda: True)
    monkeypatch.setattr("secrets.token_urlsafe", lambda _n: "generated-token")
    monkeypatch.setattr("importlib.reload", lambda module: module)
    monkeypatch.setattr(api, "API_KEY", "")
    monkeypatch.delenv("CPA_URL", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)

    result = _setup_routes()["post_setup_save"](
        SetupConfig(
            MAIL_PROVIDER="cloudflare_temp_email",
            CLOUDFLARE_TEMP_EMAIL_BASE_URL="http://mail.example.com",
            CLOUDFLARE_TEMP_EMAIL_ADMIN_PASSWORD="secret",
            CLOUDFLARE_TEMP_EMAIL_DOMAIN="@example.com",
            CLOUD_MAIL_API_URL="",
            CLOUD_MAIL_ADMIN_EMAIL="",
            CLOUD_MAIL_ADMIN_PASSWORD="",
            CLOUD_MAIL_DOMAIN="",
            CPA_URL="",
            CPA_KEY="key-1",
            PLAYWRIGHT_PROXY_URL="",
            PLAYWRIGHT_PROXY_BYPASS="",
            API_KEY="",
        )
    )

    assert written["MAIL_PROVIDER"] == "cloudflare_temp_email"
    assert written["CLOUDFLARE_TEMP_EMAIL_BASE_URL"] == "http://mail.example.com"
    assert written["CLOUDMAIL_BASE_URL"] == "http://mail.example.com"
    assert written["CPA_URL"] == ""
    assert written["CPA_KEY"] == "key-1"
    assert written["API_KEY"] == "generated-token"
    assert result["api_key"] == "generated-token"
    assert api.API_KEY == "generated-token"


def test_get_setup_status_uses_provider_specific_required_fields(monkeypatch):
    monkeypatch.setattr(
        "autotoken.setup_wizard._read_env",
        lambda: {
            "MAIL_PROVIDER": "cloud-mail",
            "CLOUD_MAIL_API_URL": "https://mail.example.com",
            "CLOUD_MAIL_ADMIN_EMAIL": "admin@example.com",
            "CLOUD_MAIL_ADMIN_PASSWORD": "secret",
            "CLOUD_MAIL_DOMAIN": "@example.com",
            "CPA_URL": "http://127.0.0.1:8317",
            "CPA_KEY": "key-1",
            "API_KEY": "token",
        },
    )

    result = _setup_routes()["get_setup_status"]()

    assert result["provider"] == "cloud-mail"
    assert any(field["key"] == "CLOUD_MAIL_API_URL" for field in result["fields"])
    assert all(field["key"] != "CLOUDFLARE_TEMP_EMAIL_BASE_URL" for field in result["fields"])


def test_get_register_domain_api_returns_domains(monkeypatch):
    from autotoken.api_routes.register_domain import create_register_domain_router

    monkeypatch.setattr(
        "autotoken.runtime_config.get", lambda key, default=None: "mail-a.com" if key == "register_domain" else default
    )
    monkeypatch.setattr("autotoken.runtime_config.get_register_domain", lambda: "mail-a.com")
    monkeypatch.setattr("autotoken.runtime_config.get_register_domains", lambda: ["mail-a.com", "mail-b.com"])
    monkeypatch.setattr("autotoken.config.CLOUD_MAIL_DOMAIN", "@env-mail.com")
    monkeypatch.setattr("autotoken.config.CLOUDFLARE_TEMP_EMAIL_DOMAIN", "")

    routes = {route.endpoint.__name__: route.endpoint for route in create_register_domain_router().routes}
    result = routes["get_register_domain_api"]()

    assert result["domain"] == "mail-a.com"
    assert result["domains"] == ["mail-a.com", "mail-b.com"]
    assert result["override"] == "mail-a.com"
    assert result["env_default"] == "env-mail.com"


def test_post_add_uses_selected_domain_and_random_password(monkeypatch):
    captured = {}

    monkeypatch.setattr("autotoken.runtime_config.get_register_domains", lambda: ["openaibus.com", "altbus.com"])
    monkeypatch.setattr("autotoken.runtime_config.get_register_domain", lambda: "openaibus.com")
    monkeypatch.setattr("autotoken.identity.random_password", lambda: "RandomPass123!")

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["command"] = command
        captured["func"] = func
        captured["params"] = params
        captured["kwargs"] = kwargs
        return {"task_id": "task-123", "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    result = api.post_add(api.ManualRegisterParams(domain="altbus.com", prefix="demo", password=""))

    assert result["task_id"] == "task-123"
    assert captured["command"] == "register"
    assert captured["params"]["domain"] == "altbus.com"
    assert captured["params"]["domains"] == ["altbus.com"]
    assert captured["params"]["prefix"] == "demo"
    assert captured["params"]["password_mode"] == "random"
    assert captured["params"]["post_register_oauth"] is False
    assert captured["kwargs"]["email_prefix"] == "demo"
    assert captured["kwargs"]["password"] == "RandomPass123!"
    assert captured["kwargs"]["domain"] == "altbus.com"
    assert captured["kwargs"]["domains"] == ["altbus.com"]
    assert captured["kwargs"]["post_register_oauth"] is False


def test_post_add_outlook_does_not_require_register_domain(monkeypatch):
    captured = {}

    monkeypatch.setattr("autotoken.runtime_config.get_register_domains", lambda: [])
    monkeypatch.setattr("autotoken.runtime_config.get_register_domain", lambda: "")
    monkeypatch.setattr("autotoken.identity.random_password", lambda: "RandomPass123!")

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["command"] = command
        captured["params"] = params
        captured["kwargs"] = kwargs
        return {"task_id": "task-outlook", "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    result = api.post_add(api.ManualRegisterParams(mail_provider="outlook", domain="", domains=[]))

    assert result["task_id"] == "task-outlook"
    assert captured["command"] == "register"
    assert captured["params"]["mail_provider"] == "outlook"
    assert captured["params"]["domain"] == ""
    assert captured["params"]["domains"] == []
    assert captured["kwargs"]["mail_provider"] == "outlook"
    assert captured["kwargs"]["domain"] == ""
    assert captured["kwargs"]["domains"] == []


def test_post_import_outlook_accounts_appends_valid_unique_lines(tmp_path, monkeypatch):
    accounts_file = tmp_path / "outlook_accounts.txt"
    accounts_file.write_text("used@hotmail.com----https://mailapi.icu/key?type=html&orderNo=old\n", encoding="utf-8")
    written_env = {}

    monkeypatch.setattr("autotoken.paths.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("autotoken.setup_wizard._read_env", lambda: {"OUTLOOK_ACCOUNTS_FILE": str(accounts_file)})
    monkeypatch.setattr("autotoken.setup_wizard._write_env", lambda key, value: written_env.update({key: value}))

    result = _config_io_routes()["post_import_outlook_accounts"](
        OutlookAccountsImportParams(
            filename="accounts.txt",
            content=(
                "NewUser@hotmail.com----https://mailapi.icu/key?type=html&orderNo=new\n"
                "used@hotmail.com----https://mailapi.icu/key?type=html&orderNo=dup\n"
                "bad-line\n"
                "Oauth@outlook.com----pass----client-id----refresh-token\n"
            ),
        )
    )

    saved = accounts_file.read_text(encoding="utf-8")
    assert result["imported"] == 2
    assert result["duplicates"] == 1
    assert result["invalid"] == 1
    assert result["first_imported_email"] == "NewUser@hotmail.com"
    assert saved.startswith("NewUser@hotmail.com----https://mailapi.icu/key?type=html&orderNo=new\n")
    assert "NewUser@hotmail.com----https://mailapi.icu/key?type=html&orderNo=new" in saved
    assert "Oauth@outlook.com----pass----client-id----refresh-token" in saved
    assert written_env == {}


def test_post_import_outlook_accounts_creates_default_file_when_unconfigured(tmp_path, monkeypatch):
    written_env = {}

    monkeypatch.setattr("autotoken.paths.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("autotoken.setup_wizard._read_env", lambda: {})
    monkeypatch.setattr("autotoken.setup_wizard._write_env", lambda key, value: written_env.update({key: value}))
    monkeypatch.delenv("OUTLOOK_ACCOUNTS_FILE", raising=False)

    result = _config_io_routes()["post_import_outlook_accounts"](
        OutlookAccountsImportParams(
            filename="accounts.txt",
            content="user@hotmail.com----https://mailapi.icu/key?type=html&orderNo=abc",
        )
    )

    assert result["imported"] == 1
    assert written_env["OUTLOOK_ACCOUNTS_FILE"] == "data/outlook_accounts.txt"
    assert (tmp_path / "data" / "outlook_accounts.txt").exists()


def test_get_outlook_accounts_status_marks_registered_and_redacts_secrets(tmp_path, monkeypatch):
    accounts_file = tmp_path / "outlook_accounts.txt"
    accounts_file.write_text(
        "\n".join(
            [
                "registered@hotmail.com----secret-password",
                "blocked@outlook.com----https://mailapi.icu/key?type=html&orderNo=secret-order",
                "Ready@outlook.com----mail-pass----client-id----refresh-token",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("autotoken.paths.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("autotoken.setup_wizard._read_env", lambda: {"OUTLOOK_ACCOUNTS_FILE": str(accounts_file)})
    monkeypatch.setattr("autotoken.storage.accounts.load_accounts", lambda: [{"email": "registered@hotmail.com"}])
    monkeypatch.setattr(
        "autotoken.mail.outlook.OutlookMailProvider._registered_emails",
        staticmethod(lambda: {"registered@hotmail.com", "blocked@outlook.com"}),
    )

    result = _config_io_routes()["get_outlook_accounts_status"]()

    assert result["total"] == 3
    assert result["available"] == 1
    assert result["registered"] == 1
    assert result["unavailable"] == 1
    assert result["next_available_email"] == "Ready@outlook.com"
    statuses = {item["email"]: item["status"] for item in result["accounts"]}
    assert statuses == {
        "registered@hotmail.com": "registered",
        "blocked@outlook.com": "unavailable",
        "Ready@outlook.com": "available",
    }
    serialized = json.dumps(result)
    assert "secret-password" not in serialized
    assert "secret-order" not in serialized
    assert "refresh-token" not in serialized


def test_get_outlook_accounts_status_keeps_persisted_outlook_registration_after_restart(tmp_path, monkeypatch):
    from autotoken.storage import outlook_pool

    accounts_file = tmp_path / "outlook_accounts.txt"
    accounts_file.write_text(
        "\n".join(
            [
                "registered@hotmail.com----secret-password",
                "ready@outlook.com----mail-pass",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(outlook_pool, "STATE_FILE", tmp_path / "outlook_pool.json")
    outlook_pool.mark_registered_email("registered@hotmail.com", source="register_success")
    monkeypatch.setattr("autotoken.paths.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("autotoken.setup_wizard._read_env", lambda: {"OUTLOOK_ACCOUNTS_FILE": str(accounts_file)})
    monkeypatch.setattr("autotoken.storage.accounts.load_accounts", lambda: [])

    result = _config_io_routes()["get_outlook_accounts_status"]()

    assert result["registered"] == 1
    assert result["available"] == 1
    assert result["next_available_email"] == "ready@outlook.com"
    statuses = {item["email"]: item["status"] for item in result["accounts"]}
    assert statuses["registered@hotmail.com"] == "registered"
    assert statuses["ready@outlook.com"] == "available"


def test_post_delete_outlook_accounts_removes_selected_lines_and_redacts_secrets(tmp_path, monkeypatch):
    accounts_file = tmp_path / "outlook_accounts.txt"
    accounts_file.write_text(
        "\n".join(
            [
                "# keep comments",
                "delete1@hotmail.com----secret-password",
                "keep@outlook.com----keep-password",
                "delete2@outlook.com----https://mailapi.icu/key?type=html&orderNo=secret-order",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("autotoken.paths.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("autotoken.setup_wizard._read_env", lambda: {"OUTLOOK_ACCOUNTS_FILE": str(accounts_file)})

    result = _config_io_routes()["post_delete_outlook_accounts"](
        OutlookAccountsDeleteParams(emails=["delete1@hotmail.com", "DELETE2@outlook.com", "missing@outlook.com"])
    )

    saved = accounts_file.read_text(encoding="utf-8")
    assert result["requested"] == 3
    assert result["deleted"] == 2
    assert result["deleted_emails"] == ["delete1@hotmail.com", "delete2@outlook.com"]
    assert result["missing_emails"] == ["missing@outlook.com"]
    assert "# keep comments" in saved
    assert "keep@outlook.com----keep-password" in saved
    assert "delete1@hotmail.com" not in saved
    assert "delete2@outlook.com" not in saved
    serialized = json.dumps(result)
    assert "secret-password" not in serialized
    assert "secret-order" not in serialized


def test_post_import_icloud_accounts_appends_valid_unique_lines(tmp_path, monkeypatch):
    accounts_file = tmp_path / "icloud_accounts.txt"
    accounts_file.write_text(
        "used@icloud.com----https://icloud-api.top/show/token/used@icloud.com\n",
        encoding="utf-8",
    )
    written_env = {}

    monkeypatch.setattr("autotoken.paths.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("autotoken.setup_wizard._read_env", lambda: {"ICLOUD_ACCOUNTS_FILE": str(accounts_file)})
    monkeypatch.setattr("autotoken.setup_wizard._write_env", lambda key, value: written_env.update({key: value}))

    result = _config_io_routes()["post_import_icloud_accounts"](
        ICloudAccountsImportParams(
            filename="icloud.txt",
            content=(
                "NewUser@icloud.com----https://icloud-api.top/show/token/NewUser@icloud.com\n"
                "used@icloud.com----https://icloud-api.top/show/token/used@icloud.com\n"
                "bad-line\n"
            ),
        )
    )

    saved = accounts_file.read_text(encoding="utf-8")
    assert result["imported"] == 1
    assert result["duplicates"] == 1
    assert result["invalid"] == 1
    assert result["first_imported_email"] == "newuser@icloud.com"
    assert saved.startswith("NewUser@icloud.com----https://icloud-api.top/show/token/NewUser@icloud.com\n")
    assert written_env == {}


def test_get_icloud_accounts_status_marks_registered_and_redacts_links(tmp_path, monkeypatch):
    from autotoken.storage import icloud_pool

    accounts_file = tmp_path / "icloud_accounts.txt"
    accounts_file.write_text(
        "\n".join(
            [
                "registered@icloud.com----https://icloud-api.top/show/secret/registered@icloud.com",
                "dead@icloud.com----https://icloud-api.top/show/secret/dead@icloud.com",
                "Ready@icloud.com----https://icloud-api.top/show/secret/Ready@icloud.com",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("autotoken.paths.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("autotoken.setup_wizard._read_env", lambda: {"ICLOUD_ACCOUNTS_FILE": str(accounts_file)})
    monkeypatch.setattr(icloud_pool, "STATE_FILE", tmp_path / "icloud_pool.json")
    monkeypatch.setattr(
        "autotoken.storage.accounts.load_accounts",
        lambda: [
            {"email": "registered@icloud.com", "status": "active"},
            {"email": "dead@icloud.com", "status": "fail", "last_error": "account_deactivated"},
        ],
    )
    icloud_pool.mark_unavailable_email("dead@icloud.com", source="account_deactivated")

    result = _config_io_routes()["get_icloud_accounts_status"]()

    assert result["total"] == 3
    assert result["available"] == 1
    assert result["registered"] == 1
    assert result["unavailable"] == 1
    assert result["next_available_email"] == "ready@icloud.com"
    assert {item["email"]: item["status"] for item in result["accounts"]} == {
        "ready@icloud.com": "available",
    }
    assert {item["email"]: item["status"] for item in result["all_accounts"]} == {
        "registered@icloud.com": "registered",
        "dead@icloud.com": "unavailable",
        "ready@icloud.com": "available",
    }
    serialized = json.dumps(result)
    assert "https://icloud-api.top/show/secret" not in serialized


def test_post_delete_icloud_accounts_removes_selected_lines_and_redacts_links(tmp_path, monkeypatch):
    accounts_file = tmp_path / "icloud_accounts.txt"
    accounts_file.write_text(
        "\n".join(
            [
                "# keep comments",
                "delete1@icloud.com----https://icloud-api.top/show/secret/delete1@icloud.com",
                "keep@icloud.com----https://icloud-api.top/show/secret/keep@icloud.com",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("autotoken.paths.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("autotoken.setup_wizard._read_env", lambda: {"ICLOUD_ACCOUNTS_FILE": str(accounts_file)})

    result = _config_io_routes()["post_delete_icloud_accounts"](
        ICloudAccountsDeleteParams(emails=["DELETE1@icloud.com", "missing@icloud.com"])
    )

    saved = accounts_file.read_text(encoding="utf-8")
    assert result["requested"] == 2
    assert result["deleted"] == 1
    assert result["deleted_emails"] == ["delete1@icloud.com"]
    assert result["missing_emails"] == ["missing@icloud.com"]
    assert "# keep comments" in saved
    assert "keep@icloud.com----https://icloud-api.top/show/secret/keep@icloud.com" in saved
    assert "delete1@icloud.com" not in saved
    assert "secret/delete1" not in json.dumps(result)


def test_post_import_outlook_accounts_rejects_relative_path_outside_project(tmp_path, monkeypatch):
    monkeypatch.setattr("autotoken.paths.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("autotoken.setup_wizard._read_env", lambda: {"OUTLOOK_ACCOUNTS_FILE": "../outside.txt"})

    with pytest.raises(Exception) as exc:
        _config_io_routes()["post_import_outlook_accounts"](
            OutlookAccountsImportParams(
                filename="accounts.txt",
                content="user@hotmail.com----https://mailapi.icu/key?type=html&orderNo=abc",
            )
        )

    assert "OUTLOOK_ACCOUNTS_FILE 不能指向项目目录外" in str(exc.value)
    assert not (tmp_path.parent / "outside.txt").exists()


def test_post_import_outlook_accounts_rejects_oversized_existing_file(tmp_path, monkeypatch):
    accounts_file = tmp_path / "outlook_accounts.txt"
    accounts_file.write_text("x" * (OUTLOOK_ACCOUNTS_IMPORT_MAX_BYTES + 1), encoding="utf-8")

    monkeypatch.setattr("autotoken.paths.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("autotoken.setup_wizard._read_env", lambda: {"OUTLOOK_ACCOUNTS_FILE": str(accounts_file)})

    with pytest.raises(Exception) as exc:
        _config_io_routes()["post_import_outlook_accounts"](
            OutlookAccountsImportParams(
                filename="accounts.txt",
                content="user@hotmail.com----https://mailapi.icu/key?type=html&orderNo=abc",
            )
        )

    assert "现有 Outlook 账号池文件过大" in str(exc.value)
    assert accounts_file.stat().st_size == OUTLOOK_ACCOUNTS_IMPORT_MAX_BYTES + 1


def test_convert_account_session_cpa_auths_updates_auth_file(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    account = {"email": "user@example.com", "auth_file": "", "account_type": "free"}
    updated = {}

    monkeypatch.setattr("autotoken.session_cpa_converter.AUTH_DIR", auth_dir)
    monkeypatch.setattr("autotoken.auth_storage.AUTH_DIR", auth_dir)
    monkeypatch.setattr("autotoken.session_cpa_converter.upsert_codex_auth_file", lambda *args, **kwargs: None)
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda accounts, email: account if email == "user@example.com" else None,
    )
    monkeypatch.setattr(
        "autotoken.accounts.update_account",
        lambda email, **kwargs: updated.update(kwargs) or {**account, **kwargs},
    )
    monkeypatch.setattr(
        "autotoken.auth_session_store.load_auth_session",
        lambda email: {
            "user": {"email": email, "id": "user-1"},
            "account": {"id": "acc-1", "planType": "plus"},
            "accessToken": _session_access_jwt(email, "acc-1"),
            "sessionToken": "session-token",
            "expires": "2026-08-06T14:29:36.155Z",
        },
    )

    result = _convert_account_session_cpa_auths(AccountSessionCpaConvertParams(emails=["user@example.com"]))

    assert result["converted"] == 1
    assert result["files"][0]["id_token_synthetic"] is True
    assert updated["auth_file"].endswith(".json")
    assert updated["account_type"] == "plus"
    assert (auth_dir / result["files"][0]["filename"]).exists()


def test_convert_account_session_cpa_auths_does_not_downgrade_plus_to_free(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    account = {"email": "plus@example.com", "auth_file": "", "account_type": "plus"}
    updated = {}

    monkeypatch.setattr("autotoken.session_cpa_converter.AUTH_DIR", auth_dir)
    monkeypatch.setattr("autotoken.auth_storage.AUTH_DIR", auth_dir)
    monkeypatch.setattr("autotoken.session_cpa_converter.upsert_codex_auth_file", lambda *args, **kwargs: None)
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda accounts, email: account if email == "plus@example.com" else None,
    )
    monkeypatch.setattr(
        "autotoken.accounts.update_account",
        lambda email, **kwargs: updated.update(kwargs) or {**account, **kwargs},
    )
    monkeypatch.setattr(
        "autotoken.auth_session_store.load_auth_session",
        lambda email: {
            "user": {"email": email, "id": "user-1"},
            "account": {"id": "acc-1", "planType": "free"},
            "accessToken": _session_access_jwt(email, "acc-1"),
            "sessionToken": "session-token",
            "expires": "2026-08-06T14:29:36.155Z",
        },
    )

    result = _convert_account_session_cpa_auths(AccountSessionCpaConvertParams(emails=["plus@example.com"]))

    assert result["converted"] == 1
    assert result["files"][0]["filename"].startswith("codex-plus@example.com-plus-")
    assert updated["account_type"] == "plus"


def test_import_account_cpa_auths_accepts_zip_and_pasted_json(tmp_path, monkeypatch):
    from autotoken import accounts as accounts_module
    from autotoken import auth_storage, cpa_sync

    auth_dir = tmp_path / "data" / "auths"
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setattr(accounts_module, "ACCOUNTS_FILE", tmp_path / "accounts.json")
    monkeypatch.setattr(auth_storage, "AUTH_DIR", auth_dir)
    monkeypatch.setattr(cpa_sync, "AUTH_DIR", auth_dir)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("nested/zipped.json", json.dumps(_cpa_import_auth("zip@example.com", "acc-zip")))
        archive.writestr("nested/broken.json", "{")

    result = _import_account_cpa_auths(
        AccountCpaAuthImportParams(
            pasted_text=json.dumps({"codex_auth": _cpa_import_auth("paste@example.com", "acc-paste")}),
            files=[
                AccountCpaAuthImportSource(
                    filename="auths.zip",
                    content_base64=base64.b64encode(buffer.getvalue()).decode("ascii"),
                )
            ],
        )
    )

    assert result["imported"] == 2
    assert result["accounts_added"] == 2
    assert [item["email"] for item in result["files"]] == ["paste@example.com", "zip@example.com"]
    assert result["invalid"][0]["filename"] == "nested/broken.json"
    accounts = accounts_module.load_accounts()
    assert {account["email"] for account in accounts} == {"paste@example.com", "zip@example.com"}
    assert all(account["status"] == accounts_module.STATUS_STANDBY for account in accounts)


def test_import_account_cpa_auths_does_not_downgrade_existing_plus(tmp_path, monkeypatch):
    from autotoken import accounts as accounts_module
    from autotoken import auth_storage, cpa_sync

    auth_dir = tmp_path / "data" / "auths"
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setattr(accounts_module, "ACCOUNTS_FILE", tmp_path / "accounts.json")
    monkeypatch.setattr(auth_storage, "AUTH_DIR", auth_dir)
    monkeypatch.setattr(cpa_sync, "AUTH_DIR", auth_dir)

    accounts_module.save_accounts(
        [
            {
                "email": "plus@example.com",
                "status": accounts_module.STATUS_PLUS,
                "account_type": accounts_module.ACCOUNT_TYPE_PLUS,
            }
        ]
    )
    auth_payload = _cpa_import_auth("plus@example.com", "acc-plus")
    auth_payload["plan_type"] = "free"

    result = _import_account_cpa_auths(AccountCpaAuthImportParams(pasted_text=json.dumps({"codex_auth": auth_payload})))

    assert result["imported"] == 1
    account = accounts_module.find_account(accounts_module.load_accounts(), "plus@example.com")
    assert account["account_type"] == accounts_module.ACCOUNT_TYPE_PLUS


def test_update_account_cpa_auth_plan_type_adds_missing_plan_type(tmp_path, monkeypatch):
    from autotoken import auth_storage, cpa_sync

    auth_dir = tmp_path / "data" / "auths"
    auth_dir.mkdir(parents=True)
    auth_file = auth_dir / "codex-user@example.com-unknown-deadbeef.json"
    auth_file.write_text(
        json.dumps(
            {
                "type": "codex",
                "email": "user@example.com",
                "account_id": "acc-user",
                "access_token": "access-token",
                "id_token": "id-token",
                "refresh_token": "refresh-token",
                "expired": "2030-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    updates = {}

    monkeypatch.setattr(auth_storage, "AUTH_DIR", auth_dir)
    monkeypatch.setattr(cpa_sync, "AUTH_DIR", auth_dir)
    monkeypatch.setattr("autotoken.cpa_sync.upsert_codex_auth_file", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("autotoken.cpa_sync.delete_codex_auth_file", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "autotoken.accounts.update_account", lambda email, **kwargs: updates.setdefault(email, {}).update(kwargs)
    )

    result = api._update_account_cpa_auth_plan_type(
        "USER@example.com",
        account={"email": "user@example.com", "auth_file": str(auth_file)},
        plan_type="plus",
    )

    assert result["status"] == "updated"
    updated_path = Path(result["auth_file"])
    assert updated_path.name.startswith("codex-user@example.com-plus-")
    saved = json.loads(updated_path.read_text(encoding="utf-8"))
    assert saved["plan_type"] == "plus"
    assert saved["chatgpt_plan_type"] == "plus"
    assert not auth_file.exists()
    assert updates["user@example.com"]["auth_file"] == str(updated_path)


def test_post_add_batch_accepts_multiple_domains(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "autotoken.runtime_config.get_register_domains", lambda: ["mail-a.com", "mail-b.com", "mail-c.com"]
    )
    monkeypatch.setattr("autotoken.runtime_config.get_register_domain", lambda: "mail-a.com")
    monkeypatch.setattr("autotoken.identity.random_password", lambda: "RandomPass123!")

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["command"] = command
        captured["params"] = params
        captured["kwargs"] = kwargs
        return {"task_id": "task-456", "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    result = api.post_add(
        api.ManualRegisterParams(
            mode="batch",
            count=5,
            concurrency=2,
            domains=["mail-b.com", "@mail-c.com", "mail-b.com"],
            prefix="demo",
            post_register_oauth=True,
        )
    )

    assert result["task_id"] == "task-456"
    assert captured["command"] == "register"
    assert captured["params"]["domain"] == "mail-b.com"
    assert captured["params"]["domains"] == ["mail-b.com", "mail-c.com"]
    assert captured["kwargs"]["domain"] == "mail-b.com"
    assert captured["kwargs"]["domains"] == ["mail-b.com", "mail-c.com"]
    assert captured["kwargs"]["post_register_oauth"] is True
    assert captured["kwargs"]["count"] == 5
    assert captured["kwargs"]["concurrency"] == 2
