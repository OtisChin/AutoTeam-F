from autotoken.services.mailcom_auth_session import login_mailcom_auth_session_once
from autotoken.storage import accounts, auth_session_store, mail_accounts


def test_mailcom_auth_session_login_promotes_pending_pool_account(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setattr(auth_session_store, "AUTH_SESSION_DIR", tmp_path / "auth_session")
    monkeypatch.setattr(accounts, "get_admin_email", lambda: "")

    mail_accounts.import_mail_accounts("finished@mail.com----mail-pass----gpt-pass")
    mail_accounts.sync_mail_accounts_to_account_pool(["finished@mail.com"])
    assert accounts.load_accounts()[0]["status"] == accounts.STATUS_PENDING

    class FakeMailComProvider:
        def login(self):
            return None

    monkeypatch.setattr("autotoken.mail.mailcom.MailComMailProvider", FakeMailComProvider)
    monkeypatch.setattr(
        "autotoken.auth.protocol_register.login_once",
        lambda *_args, **_kwargs: {"user": {"email": "finished@mail.com"}, "access_token": "at"},
    )

    result = login_mailcom_auth_session_once("Finished@mail.com")

    account = accounts.load_accounts()[0]
    assert result["status"] == "success"
    assert result["auth_session_file"]
    assert account["email"] == "finished@mail.com"
    assert account["status"] == accounts.STATUS_ACTIVE
    assert account["password"] == "gpt-pass"
    assert account["mail_provider"] == "mail.com"
    assert account["seat_type"] == accounts.SEAT_CODEX


def test_mailcom_auth_session_login_passes_stored_totp_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setattr(auth_session_store, "AUTH_SESSION_DIR", tmp_path / "auth_session")
    monkeypatch.setattr(accounts, "get_admin_email", lambda: "")

    mail_accounts.import_mail_accounts("totp@mail.com----mail-pass----gpt-pass")
    mail_accounts.sync_mail_accounts_to_account_pool(["totp@mail.com"])
    accounts.save_totp_metadata("totp@mail.com", secret=("GEZDGNBVGY3TQOJQ" + "GEZDGNBVGY3TQOJQ"))
    captured = {}

    class FakeMailComProvider:
        def login(self):
            return None

    def fake_login_once(*_args, **kwargs):
        captured.update(kwargs)
        return {"user": {"email": "totp@mail.com"}, "access_token": "at"}

    monkeypatch.setattr("autotoken.mail.mailcom.MailComMailProvider", FakeMailComProvider)
    monkeypatch.setattr("autotoken.auth.protocol_register.login_once", fake_login_once)

    login_mailcom_auth_session_once("totp@mail.com")

    assert captured["totp_secret"] == ("GEZDGNBVGY3TQOJQ" + "GEZDGNBVGY3TQOJQ")
