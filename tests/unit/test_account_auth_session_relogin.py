from autotoken.storage import accounts, auth_session_store
from contextlib import contextmanager


def test_relogin_account_auth_session_without_auth_file_saves_session_only(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setattr(auth_session_store, "AUTH_SESSION_DIR", tmp_path / "auth_session")
    monkeypatch.setattr(accounts, "get_admin_email", lambda: "")

    accounts.add_account(
        "plain@example.com",
        "pw",
        cloudmail_account_id="mail-id",
        seat_type=accounts.SEAT_CODEX,
        mail_provider="icloud",
    )
    captured = {}

    class FakeMailClient:
        def login(self):
            captured["mail_login"] = True

    def fake_login_once(mail_client, **kwargs):
        captured["login_once"] = kwargs
        return {"user": {"email": "plain@example.com"}, "access_token": "chatgpt-at", "sessionToken": "session-token"}

    def fail_convert(*_args, **_kwargs):
        raise AssertionError("缺少 codex auth 文件的补登录不应转换 CPA/Codex auth")

    monkeypatch.setattr("autotoken.mail.TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr("autotoken.auth.protocol_register.login_once", fake_login_once)
    monkeypatch.setattr("autotoken.services.account_cpa_auth.convert_account_auth_session_to_cpa_auth", fail_convert)

    from autotoken.services.account_auth_session_relogin import relogin_account_auth_session_once

    account = accounts.load_accounts()[0]
    result = relogin_account_auth_session_once("plain@example.com", account)

    saved = auth_session_store.load_auth_session("plain@example.com")
    updated = accounts.load_accounts()[0]
    assert result["status"] == "success"
    assert result["auth_session_file"]
    assert result["codex_auth_updated"] is False
    assert saved["access_token"] == "chatgpt-at"
    assert updated["status"] == accounts.STATUS_ACTIVE
    assert updated["auth_file"] in ("", None)
    assert captured["login_once"]["email"] == "plain@example.com"
    assert captured["login_once"]["account_id"] == "mail-id"


def test_relogin_account_auth_session_promotes_nested_access_token(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setattr(auth_session_store, "AUTH_SESSION_DIR", tmp_path / "auth_session")
    monkeypatch.setattr(accounts, "get_admin_email", lambda: "")

    accounts.add_account(
        "nested@example.com",
        "pw",
        cloudmail_account_id="mail-id",
        seat_type=accounts.SEAT_CODEX,
        mail_provider="icloud",
    )

    class FakeMailClient:
        def login(self):
            pass

    def fake_login_once(_mail_client, **_kwargs):
        return {
            "status": 200,
            "email": "nested@example.com",
            "data": {
                "accessToken": "nested-chatgpt-at",
                "access_token": "nested-chatgpt-at",
                "chatgpt_access_token": "nested-chatgpt-at",
                "sessionToken": "nested-session-token",
                "account": {"id": "account-1"},
            },
        }

    monkeypatch.setattr("autotoken.mail.TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr("autotoken.auth.protocol_register.login_once", fake_login_once)

    from autotoken.services.account_auth_session_relogin import relogin_account_auth_session_once

    account = accounts.load_accounts()[0]
    result = relogin_account_auth_session_once("nested@example.com", account)
    saved = auth_session_store.load_auth_session("nested@example.com")

    assert result["status"] == "success"
    assert saved["access_token"] == "nested-chatgpt-at"
    assert saved["accessToken"] == "nested-chatgpt-at"
    assert saved["chatgpt_access_token"] == "nested-chatgpt-at"
    assert saved["sessionToken"] == "nested-session-token"
    assert saved["account"] == {"id": "account-1"}


def test_relogin_account_auth_session_releases_provider_env_lock_before_chatgpt_login(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setattr(auth_session_store, "AUTH_SESSION_DIR", tmp_path / "auth_session")
    monkeypatch.setattr(accounts, "get_admin_email", lambda: "")

    accounts.add_account(
        "parallel@example.com",
        "pw",
        cloudmail_account_id="mail-id",
        seat_type=accounts.SEAT_CODEX,
        mail_provider="icloud",
    )
    provider_context_active = {"value": False}

    @contextmanager
    def fake_temporary_mail_provider(_provider, _overrides=None):
        provider_context_active["value"] = True
        try:
            yield
        finally:
            provider_context_active["value"] = False

    class FakeMailClient:
        def login(self):
            assert provider_context_active["value"] is True

    def fake_login_once(_mail_client, **_kwargs):
        assert provider_context_active["value"] is False
        return {"user": {"email": "parallel@example.com"}, "access_token": "chatgpt-at", "sessionToken": "session-token"}

    monkeypatch.setattr("autotoken.interfaces.manager._temporary_mail_provider", fake_temporary_mail_provider)
    monkeypatch.setattr("autotoken.mail.TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr("autotoken.auth.protocol_register.login_once", fake_login_once)

    from autotoken.services.account_auth_session_relogin import relogin_account_auth_session_once

    account = accounts.load_accounts()[0]
    result = relogin_account_auth_session_once("parallel@example.com", account)

    assert result["status"] == "success"
