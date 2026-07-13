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
    OutlookAccountsDeleteParams,
    OutlookAccountsImportParams,
    create_config_io_router,
)
from autotoken.api_routes.setup import SetupConfig, create_setup_router
from autotoken.api_routes.status import build_status_response
from autotoken.core.files import READ_JSON_FILE_MAX_BYTES
from autotoken.storage.auth_files import AUTH_JSON_FILE_MAX_BYTES


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


def test_gopay_pro_account_token_items_ignores_session_file_outside_session_dir(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    session_dir = tmp_path / "auth_session"
    auth_dir.mkdir()
    session_dir.mkdir()
    outside = tmp_path / "outside-session.json"
    outside.write_text(json.dumps({"access_token": "outside-token"}), encoding="utf-8")

    monkeypatch.setattr("autotoken.storage.auth_storage.AUTH_DIR", auth_dir)
    monkeypatch.setattr("autotoken.storage.auth_session_store.AUTH_SESSION_DIR", session_dir)
    monkeypatch.setattr(
        api,
        "_load_accounts_with_session_stubs",
        lambda include_session_stubs=True: [{"email": "user@example.com", "status": "active", "auth_file": ""}],
    )
    monkeypatch.setattr("autotoken.storage.auth_session_store.get_auth_session_file", lambda _email: str(outside))

    with pytest.raises(Exception) as exc:
        api._gopay_pro_account_token_items(["user@example.com"])

    assert "账号缺少可用 auth_file/auth_session" in str(exc.value)


def test_gopay_pro_paths_uses_default_pool_paths_for_oversized_config(tmp_path):
    root = tmp_path / "CNgopay"
    root.mkdir()
    (root / "config.json").write_text("x" * (READ_JSON_FILE_MAX_BYTES + 1), encoding="utf-8")

    paths = api._gopay_pro_paths(root)

    assert paths["numbers"] == (root / "pool_numbers.txt").resolve()
    assert paths["tokens"] == (root / "pool_tokens.txt").resolve()


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


def _write_gopay_pro_root(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.json").write_text(
        json.dumps(
            {
                "pool": {
                    "slots": 1,
                    "concurrency": 1,
                    "number_pool_file": "pool_numbers.txt",
                    "provided_tokens_file": "pool_tokens.txt",
                }
            }
        ),
        encoding="utf-8",
    )
    (root / "pool_numbers.txt").write_text("+628100000000----https://sms.example/record\n", encoding="utf-8")
    (root / "pool_tokens.txt").write_text("", encoding="utf-8")
    state_path = root / "runs" / "pool" / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "slots": {
                    "slot-01": {
                        "id": "slot-01",
                        "state": "WALLET_READY",
                        "full_phone": "+628100000000",
                        "phone": "8100000000",
                        "access_token": "gopay-access",
                        "refresh_token": "gopay-refresh",
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def test_gopay_pro_script_runner_supports_new_maintenance_commands(tmp_path, monkeypatch):
    root = tmp_path / "CNgopay"
    _write_gopay_pro_root(root)
    script_name = "fix-failed.cmd" if os.name == "nt" else "fix-failed.sh"
    (root / script_name).write_text("", encoding="utf-8")
    monkeypatch.setenv("CNGOPAY_ROOT", str(root))
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, _progress: None)
    monkeypatch.setattr("autotoken.cancel_signal.is_cancelled", lambda: False)

    captured = {}

    class FakeProcess:
        stdout = ["diagnostic ok\n"]

        def __init__(self, command, **_kwargs):
            captured["command"] = command

        def poll(self):
            return 0

        def terminate(self):
            captured["terminated"] = True

        def wait(self):
            return 0

    monkeypatch.setattr(api.subprocess, "Popen", FakeProcess)

    result = api._run_gopay_pro_script("fix-failed", "task-1", args=["-slot", "slot-01"])

    assert result["exit_code"] == 0
    assert result["script"] == script_name
    assert result["args"] == ["-slot", "slot-01"]
    assert any(script_name in str(part) for part in captured["command"])


def test_gopay_pro_script_args_reject_command_interpreter_characters():
    assert api._safe_gopay_pro_script_args(["--slot", "slot-01", "user@example.com", "a:b/c_1%2"]) == [
        "--slot",
        "slot-01",
        "user@example.com",
        "a:b/c_1%2",
    ]

    with pytest.raises(RuntimeError, match="不安全字符"):
        api._safe_gopay_pro_script_args(["slot-01&whoami"])


def test_gopay_pro_register_detects_waf_and_sets_cooldown(tmp_path, monkeypatch):
    root = tmp_path / "CNgopay"
    _write_gopay_pro_root(root)
    script_name = "reg.cmd" if os.name == "nt" else "reg.sh"
    (root / script_name).write_text("", encoding="utf-8")
    monkeypatch.setenv("CNGOPAY_ROOT", str(root))
    monkeypatch.setenv("GOPAY_PRO_WAF_COOLDOWN_SECONDS", "120")
    monkeypatch.setattr("autotoken.cancel_signal.is_cancelled", lambda: False)

    progress = []
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, payload: progress.append(payload))

    class FakeProcess:
        stdout = [
            "[slot-01] ❌ GoPay 注册/登录失败: [failed] signup 失败 (403): "
            "<!DOCTYPE html><title>WAF Block Page</title>\n"
        ]

        def __init__(self, *_args, **_kwargs):
            pass

        def poll(self):
            return 0

        def terminate(self):
            pass

        def wait(self):
            return 0

    monkeypatch.setattr(api.subprocess, "Popen", FakeProcess)

    result = api._run_gopay_pro_script("register", "task-1")
    cooldown = json.loads((root / "runs" / "pool" / "cooldowns.json").read_text(encoding="utf-8"))

    assert result["waf_blocked"] is True
    assert result["cooldown_remaining_seconds"] > 0
    assert cooldown["register_waf_reason"]
    assert any(item["stage"] == "gopay_pro_register_waf_blocked" for item in progress)


def test_gopay_pro_register_ratelimit_moves_number_to_cooldown(tmp_path, monkeypatch):
    root = tmp_path / "CNgopay"
    _write_gopay_pro_root(root)
    monkeypatch.setenv("CNGOPAY_ROOT", str(root))
    monkeypatch.setenv("GOPAY_PRO_RATELIMIT_COOLDOWN_SECONDS", "120")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, _progress: None)
    paths = api._gopay_pro_paths(root)
    state = json.loads((root / "runs" / "pool" / "state.json").read_text(encoding="utf-8"))
    state["slots"]["slot-01"]["state"] = "FAILED"
    state["slots"]["slot-01"]["error"] = "注册/登录失败: [ratelimited] 限流，需等 60 分钟"
    (root / "runs" / "pool" / "state.json").write_text(json.dumps(state), encoding="utf-8")

    result = api._mark_gopay_pro_register_ratelimit_cooldowns("task-1", {"slot-01"}, paths=paths)

    number_lines = (root / "pool_numbers.txt").read_text(encoding="utf-8").splitlines()
    cooldown = json.loads((root / "runs" / "pool" / "cooldowns.json").read_text(encoding="utf-8"))
    assert result["count"] == 1
    assert number_lines[0].startswith("# autotoken-cooldown ")
    assert "register_ratelimited_numbers" in cooldown
    assert api._active_pool_lines(number_lines) == []


def test_gopay_pro_checkout_401_is_terminal_event():
    log = "\n".join(
        [
            "[12:23:13] [slot-13] ❌ Plus 支付失败: chatgpt checkout 401: {",
            '"error": {"message": "Could not parse your authentication token. Please try signing in again."}',
        ]
    )

    assert api._gopay_pro_text_has_chatgpt_checkout_unauthorized(log)
    assert api._gopay_pro_harvest_checkout_unauthorized_slots(log) == ["slot-13"]
    assert api._gopay_pro_harvest_terminal_events(log) == [{"kind": "checkout_unauthorized", "slot_id": "slot-13"}]


def test_normalize_access_token_preserves_trailing_s():
    assert api._normalize_access_token("Bearer new-access,") == "new-access"


def test_gopay_pro_midtrans_charge_202_marks_slot(tmp_path, monkeypatch):
    root = tmp_path / "CNgopay"
    _write_gopay_pro_root(root)
    monkeypatch.setenv("CNGOPAY_ROOT", str(root))
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, _progress: None)
    paths = api._gopay_pro_paths(root)
    log = "[15:59:07] [slot-01] ❌ Plus 支付失败: midtrans charge denied: status=deny fraud=deny code=202 message=Your transaction is denied.\n"

    slot_ids = api._gopay_pro_midtrans_charge_202_slots(log)
    marked = api._mark_gopay_pro_midtrans_charge_202_slots("task-1", slot_ids, paths=paths)

    state = json.loads((root / "runs" / "pool" / "state.json").read_text(encoding="utf-8"))
    assert slot_ids == ["slot-01"]
    assert marked == 1
    assert state["slots"]["slot-01"]["midtrans_charge_202"] is True
    assert "midtrans_charge_202_reason" not in state["slots"]["slot-01"]


def test_gopay_pro_harvest_progress_prints_email_for_success(tmp_path, monkeypatch):
    root = tmp_path / "CNgopay"
    _write_gopay_pro_root(root)
    script_name = "harvest.cmd" if os.name == "nt" else "harvest.sh"
    (root / script_name).write_text("", encoding="utf-8")
    monkeypatch.setenv("CNGOPAY_ROOT", str(root))
    monkeypatch.setattr("autotoken.cancel_signal.is_cancelled", lambda: False)
    state_path = root / "runs" / "pool" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["slots"] = {
        "slot-01": {
            "id": "slot-01",
            "state": "PLUS_PAYING",
            "full_phone": "+628100000000",
            "access_token": "access-token-1",
        }
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")
    paths = api._gopay_pro_paths(root)
    api._write_gopay_pro_token_map(
        paths,
        [
            {
                "email": "user@example.com",
                "access_token": "access-token-1",
                "account_id": "account-1",
                "auth_file": "auth.json",
            }
        ],
    )

    progress = []
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, payload: progress.append(payload))

    class FakeProcess:
        stdout = [
            "[00:44:00] [slot-01] 开 Plus（phone=+628100000000）\n",
            "[00:44:01] [slot-01] ✅ Plus 开通成功 charge_ref=A1\n",
            "[00:44:25] [slot-01] ✅ 换绑完成，稳定号 +628100000000 已释放（token 已清）\n",
        ]

        def __init__(self, *_args, **_kwargs):
            pass

        def poll(self):
            return 0

        def terminate(self):
            pass

        def wait(self):
            return 0

    monkeypatch.setattr(api.subprocess, "Popen", FakeProcess)

    result = api._run_gopay_pro_script("harvest", "task-1", account_emails=["wrong-order@example.com"])

    assert result["slot_emails"] == {"slot-01": "user@example.com"}
    messages = [str(item.get("message") or "") for item in progress]
    assert any("Plus 开通成功" in message and "email=user@example.com" in message for message in messages)
    assert any("换绑完成" in message and "email=user@example.com" in message for message in messages)


def test_gopay_pro_batch_aborts_after_register_waf_without_harvest(tmp_path, monkeypatch):
    root = tmp_path / "CNgopay"
    _write_gopay_pro_root(root)
    state_path = root / "runs" / "pool" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["slots"]["slot-01"]["state"] = "EMPTY"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    token = "access-token-1"
    (root / "pool_tokens.txt").write_text(f"{token}\n", encoding="utf-8")
    monkeypatch.setenv("CNGOPAY_ROOT", str(root))
    monkeypatch.setattr("autotoken.cancel_signal.is_cancelled", lambda: False)
    monkeypatch.setattr(
        api,
        "_gopay_pro_account_token_items",
        lambda _emails: [
            {
                "email": "user@example.com",
                "access_token": token,
                "refresh_token": "refresh-token",
                "account_id": "account-1",
                "auth_file": "",
            }
        ],
    )

    calls = []

    def fake_script(kind, task_id, *, stage="", args=None, suppress_status_table=False, account_emails=None):
        calls.append(kind)
        if kind == "register":
            return {
                "kind": kind,
                "script": "reg.cmd",
                "exit_code": 75,
                "log_text": "WAF Block Page",
                "log_tail": "WAF Block Page",
                "waf_blocked": True,
                "cooldown_remaining_seconds": 3600,
            }
        if kind == "harvest":
            raise AssertionError("harvest should not run after register WAF")
        return {"kind": kind, "script": f"{kind}.cmd", "exit_code": 0, "log_text": "", "log_tail": ""}

    monkeypatch.setattr(api, "_append_task_progress", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(api, "_run_gopay_pro_script", fake_script)

    with pytest.raises(RuntimeError, match="WAF"):
        api._run_gopay_pro_batch_task("task-1", ["user@example.com"], concurrency=1, max_attempts=1)

    assert calls[:3] == ["refresh", "fix-failed", "register"]
    assert "harvest" not in calls


def test_gopay_pro_batch_runs_refresh_and_fix_failed_before_harvest(tmp_path, monkeypatch):
    root = tmp_path / "CNgopay"
    _write_gopay_pro_root(root)
    token = "access-token-1"
    (root / "pool_tokens.txt").write_text(f"{token}\n", encoding="utf-8")
    monkeypatch.setenv("CNGOPAY_ROOT", str(root))
    monkeypatch.setattr("autotoken.cancel_signal.is_cancelled", lambda: False)
    monkeypatch.setattr(
        api,
        "_gopay_pro_account_token_items",
        lambda _emails: [
            {
                "email": "user@example.com",
                "access_token": token,
                "refresh_token": "refresh-token",
                "account_id": "account-1",
                "auth_file": "",
            }
        ],
    )
    monkeypatch.setattr(api, "_verify_plus_plan", lambda _item: {"ok": True, "plan_type": "plus"})
    monkeypatch.setattr(api, "_mark_gopay_pro_success_account", lambda *args, **kwargs: {})

    progress = []
    calls = []

    def fake_progress(_task_id, payload):
        progress.append(payload)

    def fake_script(kind, task_id, *, stage="", args=None, suppress_status_table=False, account_emails=None):
        calls.append({"kind": kind, "stage": stage, "args": args or [], "suppress": suppress_status_table})
        if kind == "harvest":
            (root / "pool_tokens.txt").write_text("", encoding="utf-8")
            log = "\n".join(
                [
                    "[slot-01] 开 Plus（phone=+628100000000）",
                    "[slot-01] [gopay] chatgpt verify ok",
                    "[slot-01] ✅ Plus 开通成功 charge_ref=A1",
                    "[slot-01] ✅ 换绑完成，稳定号 +628100000000 已释放（token 已清）",
                ]
            )
            return {"kind": kind, "script": "harvest.cmd", "exit_code": 0, "log_text": log, "log_tail": log}
        return {"kind": kind, "script": f"{kind}.cmd", "exit_code": 0, "log_text": "", "log_tail": ""}

    monkeypatch.setattr(api, "_append_task_progress", fake_progress)
    monkeypatch.setattr(api, "_run_gopay_pro_script", fake_script)

    result = api._run_gopay_pro_batch_task("task-1", ["user@example.com"], concurrency=1, max_attempts=1)

    assert result["status"] == "success"
    assert result["successful_emails"] == ["user@example.com"]
    assert [call["kind"] for call in calls[:3]] == ["refresh", "fix-failed", "harvest"]
    assert calls[0]["suppress"] is True
    assert any(item["stage"] == "gopay_pro_fix_failed_before_batch" for item in progress)
    token_map = json.loads((root / "runs" / "pool" / "token_map.json").read_text(encoding="utf-8"))
    assert token not in json.dumps(token_map)
    assert token_map["tokens"][api._gopay_pro_token_fingerprint(token)]["email"] == "user@example.com"


def test_mark_gopay_pro_success_account_ignores_auth_file_outside_auth_dir(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    outside = tmp_path / "outside-auth.json"
    outside.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("autotoken.storage.auth_storage.AUTH_DIR", auth_dir)

    updates = []

    def fake_update_account(email, **fields):
        updates.append((email, fields))
        return {"email": email, **fields}

    monkeypatch.setattr("autotoken.storage.accounts.update_account", fake_update_account)
    monkeypatch.setattr(api, "_update_account_cpa_auth_plan_type", lambda *_args, **_kwargs: {})

    updated = api._mark_gopay_pro_success_account(
        "user@example.com",
        task_id="task-1",
        message="ok",
        auth_file=str(outside),
    )

    assert "auth_file" not in updates[0][1]
    assert "auth_file" not in updated


def test_mark_gopay_pro_success_account_accepts_auth_file_inside_auth_dir(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    auth_file = auth_dir / "codex-user@example.com-plus-deadbeef.json"
    auth_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("autotoken.storage.auth_storage.AUTH_DIR", auth_dir)

    updates = []

    def fake_update_account(email, **fields):
        updates.append((email, fields))
        return {"email": email, **fields}

    monkeypatch.setattr("autotoken.storage.accounts.update_account", fake_update_account)
    monkeypatch.setattr(api, "_update_account_cpa_auth_plan_type", lambda *_args, **_kwargs: {})

    updated = api._mark_gopay_pro_success_account(
        "user@example.com",
        task_id="task-1",
        message="ok",
        auth_file=str(auth_file),
    )

    expected = str(auth_file.resolve())
    assert updates[0][1]["auth_file"] == expected
    assert updated["auth_file"] == expected


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
    assert result["first_imported_email"] == "newuser@hotmail.com"
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
                "ready@outlook.com----mail-pass----client-id----refresh-token",
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
    assert result["next_available_email"] == "ready@outlook.com"
    statuses = {item["email"]: item["status"] for item in result["accounts"]}
    assert statuses == {
        "registered@hotmail.com": "registered",
        "blocked@outlook.com": "unavailable",
        "ready@outlook.com": "available",
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
