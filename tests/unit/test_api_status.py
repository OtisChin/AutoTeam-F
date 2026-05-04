import json

from autoteam import api


def test_get_status_normalizes_main_account_status_from_saved_auth(tmp_path, monkeypatch):
    main_email = "owner@example.com"
    auth_file = tmp_path / "codex-main.json"
    auth_file.write_text(json.dumps({"access_token": "token-main"}), encoding="utf-8")

    monkeypatch.setattr(
        "autoteam.accounts.load_accounts",
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
    monkeypatch.setattr(api, "_is_main_account_email", lambda email: email == main_email)
    monkeypatch.setattr("autoteam.codex_auth.get_saved_main_auth_file", lambda: str(auth_file))
    monkeypatch.setattr(
        "autoteam.codex_auth.check_codex_quota",
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

    result = api.get_status()

    assert result["quota_cache"][main_email]["primary_pct"] == 8
    assert result["accounts"][0]["is_main_account"] is True
    assert result["accounts"][0]["status"] == "active"
    assert result["summary"] == {
        "active": 1,
        "standby": 0,
        "exhausted": 0,
        "pending": 0,
        "personal": 0,
        "plus": 0,
        "auth_invalid": 0,
        "orphan": 0,
        "total": 1,
    }


def test_sanitize_account_keeps_exportable_main_account_active_without_live_quota(tmp_path, monkeypatch):
    main_email = "owner@example.com"
    auth_file = tmp_path / "codex-main.json"
    auth_file.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(api, "_is_main_account_email", lambda email: email == main_email)
    monkeypatch.setattr("autoteam.codex_auth.get_saved_main_auth_file", lambda: str(auth_file))

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
    monkeypatch.setattr("autoteam.auth_storage.AUTH_DIR", tmp_path / "auths")
    monkeypatch.setattr("autoteam.auth_session_store.get_auth_session_file", lambda _email: str(session_file))

    sanitized = api._sanitize_account(
        {"email": "user@example.com", "status": "active", "auth_file": str(session_file)}
    )

    assert sanitized["auth_session_file"] == str(session_file)
    assert sanitized["codex_auth_file"] == ""
    assert sanitized["has_codex_auth_file"] is False
    assert sanitized["needs_codex_login"] is True


def test_sanitize_account_marks_codex_auth_file_as_logged_in(tmp_path, monkeypatch):
    auth_dir = tmp_path / "data" / "auths"
    auth_file = auth_dir / "codex-user@example.com-free-deadbeef.json"
    auth_dir.mkdir(parents=True)
    auth_file.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)
    monkeypatch.setattr("autoteam.auth_storage.AUTH_DIR", auth_dir)
    monkeypatch.setattr("autoteam.auth_session_store.get_auth_session_file", lambda _email: "")

    sanitized = api._sanitize_account(
        {"email": "user@example.com", "status": "active", "auth_file": str(auth_file)}
    )

    assert sanitized["codex_auth_file"] == str(auth_file)
    assert sanitized["has_codex_auth_file"] is True
    assert sanitized["needs_codex_login"] is False


def test_post_setup_save_keeps_cpa_optional_and_generates_api_key(monkeypatch):
    written = {}

    def fake_write_env(key, value):
        written[key] = value

    monkeypatch.setattr("autoteam.setup_wizard._write_env", fake_write_env)
    monkeypatch.setattr("autoteam.setup_wizard._verify_temporary_email", lambda: True)
    monkeypatch.setattr("autoteam.setup_wizard._verify_cpa", lambda: True)
    monkeypatch.setattr("secrets.token_urlsafe", lambda _n: "generated-token")
    monkeypatch.setattr("importlib.reload", lambda module: module)
    monkeypatch.setattr(api, "API_KEY", "")
    monkeypatch.delenv("CPA_URL", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)

    result = api.post_setup_save(
        api.SetupConfig(
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
        "autoteam.setup_wizard._read_env",
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

    result = api.get_setup_status()

    assert result["provider"] == "cloud-mail"
    assert any(field["key"] == "CLOUD_MAIL_API_URL" for field in result["fields"])
    assert all(field["key"] != "CLOUDFLARE_TEMP_EMAIL_BASE_URL" for field in result["fields"])


def test_get_register_domain_api_returns_domains(monkeypatch):
    monkeypatch.setattr("autoteam.runtime_config.get", lambda key, default=None: "mail-a.com" if key == "register_domain" else default)
    monkeypatch.setattr("autoteam.runtime_config.get_register_domain", lambda: "mail-a.com")
    monkeypatch.setattr("autoteam.runtime_config.get_register_domains", lambda: ["mail-a.com", "mail-b.com"])
    monkeypatch.setattr("autoteam.config.CLOUD_MAIL_DOMAIN", "@env-mail.com")
    monkeypatch.setattr("autoteam.config.CLOUDFLARE_TEMP_EMAIL_DOMAIN", "")

    result = api.get_register_domain_api()

    assert result["domain"] == "mail-a.com"
    assert result["domains"] == ["mail-a.com", "mail-b.com"]
    assert result["override"] == "mail-a.com"
    assert result["env_default"] == "env-mail.com"


def test_post_add_uses_selected_domain_and_random_password(monkeypatch):
    captured = {}

    monkeypatch.setattr("autoteam.runtime_config.get_register_domains", lambda: ["openaibus.com", "altbus.com"])
    monkeypatch.setattr("autoteam.runtime_config.get_register_domain", lambda: "openaibus.com")
    monkeypatch.setattr("autoteam.identity.random_password", lambda: "RandomPass123!")

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


def test_post_add_batch_accepts_multiple_domains(monkeypatch):
    captured = {}

    monkeypatch.setattr("autoteam.runtime_config.get_register_domains", lambda: ["mail-a.com", "mail-b.com", "mail-c.com"])
    monkeypatch.setattr("autoteam.runtime_config.get_register_domain", lambda: "mail-a.com")
    monkeypatch.setattr("autoteam.identity.random_password", lambda: "RandomPass123!")

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
