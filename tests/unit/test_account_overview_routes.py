import base64
import json

from fastapi import FastAPI, HTTPException

from autotoken import accounts, auth_session_store, auth_storage, codex_auth
from autotoken.api_routes import account_overview
from autotoken.api_routes.account_overview import create_account_overview_router
from autotoken.storage.auth_files import AUTH_JSON_FILE_MAX_BYTES


def _b64url(payload):
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


def _jwt(payload):
    return f"{_b64url({'alg': 'none', 'typ': 'JWT'})}.{_b64url(payload)}.sig"


def _app(*, loaded_accounts=None, sanitized_accounts=None, sanitize_account=None, is_main_account_email=None):
    loaded_accounts = loaded_accounts if loaded_accounts is not None else []
    captured = {}
    app = FastAPI()

    def fake_load_accounts_with_session_stubs(**kwargs):
        captured["include_session_stubs"] = kwargs.get("include_session_stubs")
        return loaded_accounts

    def fake_sanitize_accounts_batch(_accounts, _quota_cache):
        captured["sanitized_count"] = len(_accounts)
        if sanitized_accounts is not None:
            return sanitized_accounts
        return list(_accounts)

    app.include_router(
        create_account_overview_router(
            load_accounts_with_session_stubs=fake_load_accounts_with_session_stubs,
            sanitize_accounts_batch=fake_sanitize_accounts_batch,
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


def test_account_overview_list_returns_full_pool_for_frontend_pagination():
    loaded_accounts = [{"email": f"user-{index:03d}@example.com"} for index in range(250)]
    app, _captured = _app(loaded_accounts=loaded_accounts)

    result = _endpoint(app, "/api/accounts", "GET")()

    assert [account["email"] for account in result] == [
        f"user-{index:03d}@example.com" for index in range(250)
    ]
    assert _captured["sanitized_count"] == 250


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


def test_account_overview_access_token_copies_from_auth_session(monkeypatch, tmp_path):
    auth_dir = tmp_path / "auths"
    session_dir = tmp_path / "auth_session"
    auth_dir.mkdir()
    session_dir.mkdir()
    auth_file = auth_dir / "codex-user.json"
    auth_file.write_text(json.dumps({"access_token": "account-auth-token"}), encoding="utf-8")
    session_file = session_dir / "user@example.com.json"
    session_file.write_text(json.dumps({"accessToken": "session-access-token"}), encoding="utf-8")
    app, _captured = _app()

    monkeypatch.setattr(auth_storage, "AUTH_DIR", auth_dir)
    monkeypatch.setattr(auth_session_store, "AUTH_SESSION_DIR", session_dir)
    def fail_load_accounts():
        raise AssertionError("access-token route should not scan account pool when auth_session has accessToken")

    monkeypatch.setattr(accounts, "load_accounts", fail_load_accounts)
    monkeypatch.setattr(auth_session_store, "get_auth_session_file", lambda _email: str(session_file))

    result = _endpoint(app, "/api/accounts/{email}/access-token", "GET")(" User@example.com ")

    assert result == {"email": "user@example.com", "access_token": "session-access-token"}


def test_account_overview_access_token_reads_nested_auth_session_data(monkeypatch, tmp_path):
    auth_dir = tmp_path / "auths"
    session_dir = tmp_path / "auth_session"
    auth_dir.mkdir()
    session_dir.mkdir()
    session_file = session_dir / "user@example.com.json"
    session_file.write_text(
        json.dumps(
            {
                "status": 200,
                "email": "user@example.com",
                "data": {
                    "access_token": "nested-session-token",
                    "account": {"id": "account-1"},
                },
            }
        ),
        encoding="utf-8",
    )
    app, _captured = _app()

    monkeypatch.setattr(auth_storage, "AUTH_DIR", auth_dir)
    monkeypatch.setattr(auth_session_store, "AUTH_SESSION_DIR", session_dir)
    monkeypatch.setattr(accounts, "load_accounts", lambda: [{"email": "user@example.com", "auth_file": ""}])
    monkeypatch.setattr(accounts, "find_account", lambda loaded, email: loaded[0] if email == "user@example.com" else None)
    monkeypatch.setattr(auth_session_store, "get_auth_session_file", lambda _email: str(session_file))

    result = _endpoint(app, "/api/accounts/{email}/access-token", "GET")("User@example.com")

    assert result == {"email": "user@example.com", "access_token": "nested-session-token"}


def test_account_overview_export_access_tokens_for_selected_accounts(monkeypatch, tmp_path):
    auth_dir = tmp_path / "auths"
    session_dir = tmp_path / "auth_session"
    auth_dir.mkdir()
    session_dir.mkdir()
    first_session = session_dir / "first@example.com.json"
    first_session.write_text(json.dumps({"accessToken": "first-session-token"}), encoding="utf-8")
    second_auth = auth_dir / "codex-second.json"
    second_auth.write_text(json.dumps({"access_token": "second-auth-token"}), encoding="utf-8")
    app, _captured = _app()

    monkeypatch.setattr(auth_storage, "AUTH_DIR", auth_dir)
    monkeypatch.setattr(auth_session_store, "AUTH_SESSION_DIR", session_dir)
    monkeypatch.setattr(
        accounts,
        "load_accounts",
        lambda: [
            {"email": "second@example.com", "auth_file": str(second_auth)},
        ],
    )
    monkeypatch.setattr(
        accounts,
        "find_account",
        lambda loaded, email: next((row for row in loaded if row["email"] == email), None),
    )
    monkeypatch.setattr(
        auth_session_store,
        "get_auth_session_file",
        lambda email: str(first_session) if email == "first@example.com" else "",
    )

    result = _endpoint(app, "/api/accounts/export-access-tokens", "POST")(
        account_overview.ExportAccessTokensParams(
            emails=[" First@example.com ", "second@example.com", "missing@example.com", "first@example.com"]
        )
    )

    assert result["count"] == 2
    assert result["missing"] == [
        {"email": "missing@example.com", "error": "该账号没有认证文件"},
    ]
    assert result["items"] == [
        {"email": "first@example.com", "access_token": "first-session-token"},
        {"email": "second@example.com", "access_token": "second-auth-token"},
    ]
    assert result["content"] == "first-session-token\nsecond-auth-token"
    assert result["filename"].startswith("access-tokens-")


def test_account_overview_latest_mail_fetches_only_newest_message(monkeypatch):
    app, _captured = _app()
    account = {
        "email": "user@mail.com",
        "original_email": "user@mail.com",
        "mail_provider": "mail.com",
    }
    captured = {}

    monkeypatch.setattr("autotoken.storage.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.storage.mail_accounts.get_mail_account",
        lambda email: {"email": email, "mail_password": "mail-password", "refresh_token": ""},
    )

    def fake_fetch_mailcom_messages(mail_account, size=10):
        captured["email"] = mail_account["email"]
        captured["size"] = size
        return [
            {
                "id": "mail-1",
                "subject": "Newest mail",
                "sendEmail": "sender@example.com",
                "toEmail": "user@mail.com",
                "text": "latest body",
                "createTime": 1700000000,
            }
        ]

    monkeypatch.setattr("autotoken.services.mailcom_webmail.fetch_mailcom_messages", fake_fetch_mailcom_messages)

    result = _endpoint(app, "/api/accounts/{email}/latest-mail", "GET")("User@mail.com")

    assert captured == {"email": "user@mail.com", "size": 1}
    assert result["email"] == "user@mail.com"
    assert result["mail_email"] == "user@mail.com"
    assert result["provider"] == "mail.com"
    assert result["message"]["subject"] == "Newest mail"
    assert result["message"]["text"] == "latest body"


def test_account_overview_latest_mail_fetches_icloud_provider(monkeypatch):
    app, _captured = _app()
    account = {
        "email": "user@icloud.com",
        "original_email": "user@icloud.com",
        "mail_provider": "icloud",
    }
    captured = {}

    monkeypatch.setattr("autotoken.storage.accounts.load_accounts", lambda: [account])

    def fake_search(self, recipient, size=10, account_id=None):
        captured["recipient"] = recipient
        captured["size"] = size
        captured["account_id"] = account_id
        return [
            {
                "id": "icloud-1",
                "subject": "iCloud latest",
                "sendEmail": "sender@example.com",
                "toEmail": "user@icloud.com",
                "html": "<p>icloud body</p>",
                "createTime": 1700000000,
            }
        ]

    monkeypatch.setattr("autotoken.mail.icloud.ICloudMailProvider.search_emails_by_recipient", fake_search)

    result = _endpoint(app, "/api/accounts/{email}/latest-mail", "GET")("User@icloud.com")

    assert captured == {"recipient": "user@icloud.com", "size": 1, "account_id": "user@icloud.com"}
    assert result["email"] == "user@icloud.com"
    assert result["mail_email"] == "user@icloud.com"
    assert result["provider"] == "icloud"
    assert result["message"]["subject"] == "iCloud latest"
    assert result["message"]["html"] == "<p>icloud body</p>"


def test_account_overview_latest_mail_fetches_generic_api_provider(monkeypatch):
    app, _captured = _app()
    account = {
        "email": "user@dutchmail.com",
        "original_email": "user@dutchmail.com",
        "mail_provider": "generic-api",
    }
    captured = {}

    monkeypatch.setattr("autotoken.storage.accounts.load_accounts", lambda: [account])

    def fake_search(self, recipient, size=10, account_id=None):
        captured["recipient"] = recipient
        captured["size"] = size
        captured["account_id"] = account_id
        return [
            {
                "id": "generic-1",
                "subject": "Generic latest",
                "sendEmail": "sender@example.com",
                "toEmail": "user@dutchmail.com",
                "html": "<p>generic body</p>",
                "createTime": 1700000000,
            }
        ]

    monkeypatch.setattr("autotoken.mail.generic_api.GenericApiMailProvider.search_emails_by_recipient", fake_search)

    result = _endpoint(app, "/api/accounts/{email}/latest-mail", "GET")("User@dutchmail.com")

    assert captured == {"recipient": "user@dutchmail.com", "size": 1, "account_id": "user@dutchmail.com"}
    assert result["email"] == "user@dutchmail.com"
    assert result["mail_email"] == "user@dutchmail.com"
    assert result["provider"] == "generic-api"
    assert result["message"]["subject"] == "Generic latest"
    assert result["message"]["html"] == "<p>generic body</p>"


def test_account_overview_latest_mail_falls_back_to_generic_api_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "cache.sqlite3"))
    app, _captured = _app()
    account = {
        "email": "user@dutchmail.com",
        "original_email": "user@dutchmail.com",
        "mail_provider": "generic-api",
    }

    monkeypatch.setattr("autotoken.storage.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.mail.generic_api.GenericApiMailProvider.search_emails_by_recipient", lambda *args, **kwargs: [])

    from autotoken.storage.generic_api_pool import cache_mail_message

    cache_mail_message(
        "user@dutchmail.com",
        {
            "id": "cached-generic-1",
            "subject": "Cached Generic latest",
            "sendEmail": "sender@example.com",
            "toEmail": "user@dutchmail.com",
            "html": "<p>cached body</p>",
            "createTime": 1700000000,
        },
        source="unit-test",
    )

    result = _endpoint(app, "/api/accounts/{email}/latest-mail", "GET")("User@dutchmail.com")

    assert result["provider"] == "generic-api"
    assert result["message"]["subject"] == "Cached Generic latest"
    assert result["message"]["html"] == "<p>cached body</p>"


def test_account_overview_subscription_queries_chatgpt_with_access_token(monkeypatch, tmp_path):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    auth_file = auth_dir / "codex-user.json"
    auth_file.write_text(json.dumps({"access_token": "access-token"}), encoding="utf-8")
    app, _captured = _app()
    captured = {}

    def fake_query(token, account_id=""):
        captured["token"] = token
        captured["account_id"] = account_id
        return {
            "raw": {
                "accounts": {
                    "account-1": {
                        "account_plan": {
                            "subscription_plan": "chatgptplusplan",
                            "account_plan_type": "plus",
                            "billing_period": "monthly",
                            "currency": "INR",
                            "is_active_subscription": True,
                            "is_renewing": True,
                            "will_renew": True,
                            "is_delinquent": False,
                            "expires_at": "2026-08-25T00:32:07+00:00",
                            "renewal_at": "2026-08-24T18:32:07+00:00",
                            "purchase_origin": "chatgpt_web",
                            "available_plans": ["chatgptfreeplan", "chatgptplusplan"],
                            "discount": 1,
                        }
                    }
                }
            },
            "queried_url": "https://chatgpt.com/backend-api/accounts/check/v4-2023-04-27",
        }

    monkeypatch.setattr(auth_storage, "AUTH_DIR", auth_dir)
    monkeypatch.setattr(accounts, "load_accounts", lambda: [{"email": "user@example.com", "auth_file": str(auth_file)}])
    monkeypatch.setattr(accounts, "find_account", lambda loaded, email: loaded[0] if email == "user@example.com" else None)
    monkeypatch.setattr(auth_session_store, "get_auth_session_file", lambda _email: "")
    monkeypatch.setattr(account_overview, "query_chatgpt_subscription", fake_query, raising=False)

    result = _endpoint(app, "/api/accounts/{email}/subscription", "GET")("user@example.com")

    assert captured["token"] == "access-token"
    assert captured["account_id"] == ""
    assert result["email"] == "user@example.com"
    assert result["subscription"]["plan_label"] == "Plus"
    assert result["subscription"]["plan_key"] == "chatgptplusplan"
    assert result["subscription"]["billing_period"] == "monthly"
    assert result["subscription"]["currency"] == "INR"
    assert result["subscription"]["active"] is True
    assert result["subscription"]["renewing"] is True
    assert result["subscription"]["delinquent"] is False
    assert result["subscription"]["ends_at"] == "2026-08-25T00:32:07+00:00"
    assert result["subscription"]["renews_at"] == "2026-08-24T18:32:07+00:00"
    assert result["subscription"]["purchase_origin"] == "chatgpt_web"
    assert result["subscription"]["available_plans"] == ["chatgptfreeplan", "chatgptplusplan"]
    assert result["subscription"]["discount"] == 1
    assert result["queried_url"].endswith("/backend-api/accounts/check/v4-2023-04-27")
    assert result["raw"]["accounts"]["account-1"]["account_plan"]["subscription_plan"] == "chatgptplusplan"


def test_account_overview_access_token_falls_back_to_auth_file_when_session_has_no_token(monkeypatch, tmp_path):
    auth_dir = tmp_path / "auths"
    session_dir = tmp_path / "auth_session"
    auth_dir.mkdir()
    session_dir.mkdir()
    auth_file = auth_dir / "codex-user.json"
    auth_file.write_text(json.dumps({"access_token": "account-auth-token"}), encoding="utf-8")
    session_file = session_dir / "user@example.com.json"
    session_file.write_text(json.dumps({"email": "user@example.com"}), encoding="utf-8")
    app, _captured = _app()

    monkeypatch.setattr(auth_storage, "AUTH_DIR", auth_dir)
    monkeypatch.setattr(auth_session_store, "AUTH_SESSION_DIR", session_dir)
    monkeypatch.setattr(accounts, "load_accounts", lambda: [{"email": "user@example.com", "auth_file": str(auth_file)}])
    monkeypatch.setattr(accounts, "find_account", lambda loaded, email: loaded[0] if email == "user@example.com" else None)
    monkeypatch.setattr(auth_session_store, "get_auth_session_file", lambda _email: str(session_file))

    result = _endpoint(app, "/api/accounts/{email}/access-token", "GET")("user@example.com")

    assert result["access_token"] == "account-auth-token"


def test_account_overview_subscription_uses_auth_account_id_and_real_account_check_fields(monkeypatch, tmp_path):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    auth_file = auth_dir / "codex-user.json"
    auth_file.write_text(
        json.dumps(
            {
                "access_token": _jwt(
                    {
                        "https://api.openai.com/auth": {
                            "chatgpt_account_id": "target-account",
                            "chatgpt_plan_type": "free",
                        }
                    }
                ),
                "account": {"id": "target-account"},
            }
        ),
        encoding="utf-8",
    )
    app, _captured = _app()
    captured = {}

    def fake_query(token, account_id=""):
        captured["token"] = token
        captured["account_id"] = account_id
        return {
            "raw": {
                "id": "sub-123",
                "plan_type": "plus",
                "seats_in_use": 1,
                "seats_entitled": 1,
                "active_start": "2099-01-01T01:11:00Z",
                "active_until": "2100-01-01T00:00:00Z",
                "billing_period": "monthly",
                "billing_currency": "USD",
                "will_renew": True,
                "is_delinquent": False,
                "is_processor_stripe": True,
            },
            "queried_url": "https://chatgpt.com/backend-api/subscriptions?account_id=target-account",
        }

    monkeypatch.setattr(auth_storage, "AUTH_DIR", auth_dir)
    monkeypatch.setattr(accounts, "load_accounts", lambda: [{"email": "user@example.com", "auth_file": str(auth_file)}])
    monkeypatch.setattr(accounts, "find_account", lambda loaded, email: loaded[0] if email == "user@example.com" else None)
    monkeypatch.setattr(auth_session_store, "get_auth_session_file", lambda _email: "")
    monkeypatch.setattr(account_overview, "query_chatgpt_subscription", fake_query, raising=False)

    result = _endpoint(app, "/api/accounts/{email}/subscription", "GET")("user@example.com")

    assert captured["account_id"] == "target-account"
    assert result["subscription"]["plan_label"] == "Plus"
    assert result["subscription"]["jwt_plan_type"] == "free"
    assert result["subscription"]["plan_key"] == "chatgptplusplan"
    assert result["subscription"]["active"] is True
    assert result["subscription"]["paid"] is True
    assert result["subscription"]["channel_label"] == "网页 (Web)"
    assert result["subscription"]["payment_processor"] == "Stripe"
    assert result["subscription"]["seats"] == {"used": 1, "total": 1}
    assert result["subscription"]["starts_at"].startswith("2099-01-01T01:11:00")
    assert result["subscription"]["ends_at"].startswith("2100-01-01T00:00:00")
    assert result["subscription"]["renews_at"].startswith("2100-01-01T00:00:00")
    assert isinstance(result["subscription"]["remaining_days"], int)
    assert result["raw"]["id"] == "sub-123"


def test_query_chatgpt_subscription_uses_subscriptions_endpoint_with_account_id(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"plan_type": "plus"}

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, **kwargs):
            calls.append({"url": url, "headers": dict(kwargs.get("headers") or {}), "session_headers": dict(self.headers)})
            return FakeResponse()

    monkeypatch.setattr(account_overview, "_new_chatgpt_subscription_session", lambda token: FakeSession(), raising=False)

    result = account_overview.query_chatgpt_subscription("valid-token", account_id="acc-1")

    assert result["raw"] == {"plan_type": "plus"}
    assert len(calls) == 2
    assert calls[0]["url"] == "https://chatgpt.com/backend-api/subscriptions?account_id=acc-1"
    assert calls[0]["headers"]["x-openai-target-path"] == "/backend-api/subscriptions"
    assert calls[1]["headers"]["x-openai-target-path"] == "/backend-api/accounts/check/v4-2023-04-27"
    assert "Chatgpt-Account-Id" not in calls[0]["headers"]
    assert "Chatgpt-Account-Id" not in calls[0]["session_headers"]


def test_query_chatgpt_subscription_merges_account_check_discounts(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, **kwargs):
            calls.append({"url": url, "headers": dict(kwargs.get("headers") or {})})
            if "/backend-api/subscriptions?" in url:
                return FakeResponse({"plan_type": "plus", "active_until": "2100-01-01T00:00:00Z"})
            return FakeResponse(
                {
                    "accounts": {
                        "acc-1": {
                            "entitlement": {
                                "subscription_plan": "chatgptplusplan",
                                "applied_discounts": [
                                    {
                                        "promo_campaign_id": "plus-1-month-free",
                                        "amount": 100.0,
                                        "duration_num_periods": 1,
                                        "discount_expires_at": "2100-01-01T00:00:00+00:00",
                                        "cancellation_policy": "term_end",
                                    }
                                ],
                            },
                            "eligible_offers": {
                                "offers": [
                                    {"id": "chatgptfreeplan"},
                                    {"id": "chatgptplusplan"},
                                ]
                            },
                        }
                    }
                }
            )

    monkeypatch.setattr(account_overview, "_new_chatgpt_subscription_session", lambda token: FakeSession(), raising=False)
    monkeypatch.setattr(account_overview, "_browser_timezone_offset_min", lambda: 480, raising=False)

    result = account_overview.query_chatgpt_subscription("valid-token", account_id="acc-1")
    normalized = account_overview.normalize_chatgpt_subscription(result["raw"], account_id="acc-1")

    assert calls[0]["url"] == "https://chatgpt.com/backend-api/subscriptions?account_id=acc-1"
    assert calls[1]["url"] == "https://chatgpt.com/backend-api/accounts/check/v4-2023-04-27?timezone_offset_min=480"
    assert normalized["plan_key"] == "chatgptplusplan"
    assert normalized["applied_discounts"] == [
        {
            "id": "plus-1-month-free",
            "percent_off": 100.0,
            "duration_in_months": 1,
            "ends_at": "2100-01-01T00:00:00+00:00",
            "end_behavior": "term_end",
        }
    ]
    assert normalized["available_plans"] == ["chatgptfreeplan", "chatgptplusplan"]


def test_query_chatgpt_subscription_handles_no_subscription_404_with_account_check(monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload if payload is not None else {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self):
            return self._payload

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, **kwargs):
            calls.append(url)
            if "/backend-api/subscriptions?" in url:
                return FakeResponse(404, {"detail": "No subscription found for account"})
            return FakeResponse(
                200,
                {
                    "accounts": {
                        "acc-free": {
                            "account": {
                                "plan_type": "free",
                                "has_previously_paid_subscription": False,
                            },
                            "entitlement": {
                                "has_active_subscription": False,
                                "subscription_plan": "chatgptfreeplan",
                                "applied_discounts": [],
                            },
                            "eligible_offers": {
                                "offers": [
                                    {"id": "chatgptfreeplan"},
                                    {"id": "chatgptplusplan"},
                                ]
                            },
                        }
                    }
                },
            )

    monkeypatch.setattr(account_overview, "_new_chatgpt_subscription_session", lambda token: FakeSession(), raising=False)
    monkeypatch.setattr(account_overview, "_browser_timezone_offset_min", lambda: 480, raising=False)

    result = account_overview.query_chatgpt_subscription("valid-token", account_id="acc-free")
    normalized = account_overview.normalize_chatgpt_subscription(result["raw"], account_id="acc-free")

    assert calls == [
        "https://chatgpt.com/backend-api/subscriptions?account_id=acc-free",
        "https://chat.openai.com/backend-api/subscriptions?account_id=acc-free",
        "https://chatgpt.com/backend-api/accounts/check/v4-2023-04-27?timezone_offset_min=480",
    ]
    assert normalized["plan_label"] == "Free"
    assert normalized["plan_key"] == "chatgptfreeplan"
    assert normalized["active"] is False
    assert normalized["paid"] is False
    assert normalized["available_plans"] == ["chatgptfreeplan", "chatgptplusplan"]


def test_query_chatgpt_subscription_uses_account_check_when_primary_404_and_fallback_401(monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload if payload is not None else {}

        @property
        def text(self):
            return json.dumps(self._payload)

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self):
            return self._payload

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, **kwargs):
            calls.append(url)
            if url.startswith("https://chatgpt.com/backend-api/subscriptions?"):
                return FakeResponse(404, {"detail": "No subscription found for account"})
            if url.startswith("https://chat.openai.com/backend-api/subscriptions?"):
                return FakeResponse(401, {"detail": {"message": "Unauthorized - Access token is missing"}})
            if "/backend-api/accounts/check/" in url:
                return FakeResponse(
                    200,
                    {
                        "accounts": {
                            "acc-plus": {
                                "account": {"plan_type": "plus", "has_previously_paid_subscription": True},
                                "entitlement": {
                                    "has_active_subscription": True,
                                    "subscription_plan": "chatgptplusplan",
                                    "applied_discounts": [{"promo_campaign_id": "plus-1-month-free"}],
                                },
                            }
                        }
                    },
                )
            return FakeResponse(200, {})

    monkeypatch.setattr(account_overview, "_new_chatgpt_subscription_session", lambda token: FakeSession(), raising=False)
    monkeypatch.setattr(account_overview, "_browser_timezone_offset_min", lambda: 480, raising=False)

    result = account_overview.query_chatgpt_subscription("valid-token", account_id="acc-plus")
    normalized = account_overview.normalize_chatgpt_subscription(result["raw"], account_id="acc-plus")

    assert calls == [
        "https://chatgpt.com/backend-api/subscriptions?account_id=acc-plus",
        "https://chat.openai.com/backend-api/subscriptions?account_id=acc-plus",
        "https://chatgpt.com/backend-api/accounts/check/v4-2023-04-27?timezone_offset_min=480",
    ]
    assert normalized["plan_label"] == "Plus"
    assert normalized["plan_key"] == "chatgptplusplan"
    assert normalized["active"] is True
    assert normalized["paid"] is True
    assert normalized["applied_discounts"] == [
        {
            "id": "plus-1-month-free",
            "percent_off": None,
            "duration_in_months": None,
            "ends_at": "",
            "end_behavior": "",
        }
    ]


def test_query_chatgpt_subscription_falls_back_to_chat_openai_when_chatgpt_forbidden(monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload if payload is not None else {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self):
            return self._payload

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, **kwargs):
            calls.append(url)
            if "chatgpt.com" in url:
                return FakeResponse(403, {"detail": "forbidden"})
            return FakeResponse(200, {"plan_type": "plus"})

    monkeypatch.setattr(account_overview, "_new_chatgpt_subscription_session", lambda token: FakeSession(), raising=False)

    result = account_overview.query_chatgpt_subscription("valid-token", account_id="acc-1")

    assert len(calls) == 3
    assert calls[0].startswith("https://chatgpt.com/")
    assert calls[1].startswith("https://chat.openai.com/")
    assert calls[0] == "https://chatgpt.com/backend-api/subscriptions?account_id=acc-1"
    assert calls[1] == "https://chat.openai.com/backend-api/subscriptions?account_id=acc-1"
    assert calls[2].startswith("https://chat.openai.com/backend-api/accounts/check/")
    assert result["raw"]["plan_type"] == "plus"


def test_query_chatgpt_subscription_retries_temporary_forbidden(monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload if payload is not None else {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self):
            return self._payload

    class FakeSession:
        def __init__(self):
            self.headers = {}
            self.subscription_calls = 0

        def get(self, url, **kwargs):
            calls.append(url)
            if "/backend-api/subscriptions?" in url:
                self.subscription_calls += 1
                if self.subscription_calls <= 2:
                    return FakeResponse(403, {"detail": "temporary forbidden"})
                return FakeResponse(200, {"plan_type": "plus"})
            return FakeResponse(200, {"accounts": {}})

    monkeypatch.setattr(account_overview, "_new_chatgpt_subscription_session", lambda token: FakeSession(), raising=False)
    monkeypatch.setattr(account_overview, "_browser_timezone_offset_min", lambda: 480, raising=False)

    result = account_overview.query_chatgpt_subscription("valid-token", account_id="acc-1")

    subscription_calls = [url for url in calls if "/backend-api/subscriptions?" in url]
    warmup_calls = [url for url in calls if "/api/auth/session" in url or "/backend-api/accounts/check/" in url]
    assert len(subscription_calls) == 3
    assert any("/api/auth/session" in url for url in warmup_calls)
    assert result["raw"]["subscription"]["plan_type"] == "plus"


def test_query_chatgpt_subscription_reports_persistent_forbidden_as_temporary(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 403

        def raise_for_status(self):
            raise RuntimeError("HTTP 403")

        def json(self):
            return {"detail": "forbidden"}

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, **kwargs):
            calls.append(url)
            return FakeResponse()

    monkeypatch.setattr(account_overview, "_new_chatgpt_subscription_session", lambda token: FakeSession(), raising=False)

    try:
        account_overview.query_chatgpt_subscription("valid-token", account_id="acc-1")
    except HTTPException as exc:
        assert exc.status_code == 403
        assert "临时拒绝" in exc.detail
        assert "auth_session 已失效" not in exc.detail
    else:
        raise AssertionError("persistent 403 should fail with a temporary refusal message")

    subscription_calls = [url for url in calls if "/backend-api/subscriptions?" in url]
    assert len(subscription_calls) == 6
