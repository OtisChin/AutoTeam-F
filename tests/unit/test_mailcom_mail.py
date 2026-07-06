import pytest

from autotoken.mail.mailcom import MailComMailProvider
from autotoken.storage import mail_accounts


def test_mailcom_provider_selects_available_sqlite_account(monkeypatch):
    provider = MailComMailProvider()
    monkeypatch.setattr(
        "autotoken.storage.mail_accounts.list_available_registration_accounts",
        lambda: [
            {
                "email": "fresh@mail.com",
                "gpt_password": "gpt-pass",
                "mail_password": "mail-pass",
                "refresh_token": "rt",
            }
        ],
    )

    account_id, email = provider.create_temp_email()

    assert account_id == "fresh@mail.com"
    assert email == "fresh@mail.com"
    assert provider._resolve_account_id("fresh@mail.com") == "fresh@mail.com"


def test_mailcom_provider_exhaustion_message(monkeypatch):
    provider = MailComMailProvider()
    monkeypatch.setattr("autotoken.storage.mail_accounts.list_available_registration_accounts", lambda: [])

    with pytest.raises(RuntimeError, match="没有可用的 mail.com 账号"):
        provider.create_temp_email()


def test_mailcom_provider_fetches_messages_via_official_webmail(monkeypatch):
    provider = MailComMailProvider()
    monkeypatch.setattr(
        "autotoken.storage.mail_accounts.get_mail_account",
        lambda email: {"email": email, "mail_password": "mail-pass", "refresh_token": "rt"},
    )
    monkeypatch.setattr(
        "autotoken.services.mailcom_webmail.fetch_mailcom_messages",
        lambda account, size=10: [
            {
                "id": "m1",
                "subject": "OpenAI code",
                "sendEmail": "noreply@openai.com",
                "toEmail": account["email"],
                "text": "Your code is 123456",
                "html": "",
                "content": "Your code is 123456",
                "createTime": 1710000000,
                "createdAt": 1710000000,
            }
        ],
    )

    messages = provider.search_emails_by_recipient("fresh@mail.com", size=5)

    assert messages[0]["accountId"] == "fresh@mail.com"
    assert messages[0]["toEmail"] == "fresh@mail.com"
    assert provider.extract_verification_code(messages[0]) == "123456"


def test_mailcom_provider_can_select_pending_synced_account_without_auth_session(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "mail.sqlite3"))
    mail_accounts.import_mail_accounts("fresh@mail.com----gpt-pass----mail-pass----rt")
    monkeypatch.setattr(
        "autotoken.storage.accounts.load_accounts",
        lambda: [{"email": "fresh@mail.com", "status": "pending", "mail_provider": "mail.com"}],
    )
    monkeypatch.setattr("autotoken.storage.auth_session_store.list_auth_session_emails", lambda: [])
    monkeypatch.setattr("autotoken.storage.register_failures.list_failures", lambda _limit=500: [])

    provider = MailComMailProvider()
    account_id, email = provider.create_temp_email()

    assert account_id == "fresh@mail.com"
    assert email == "fresh@mail.com"


def test_factory_returns_mailcom_provider(monkeypatch):
    monkeypatch.setenv("MAIL_PROVIDER", "mail.com")
    from autotoken.mail import get_mail_client

    assert isinstance(get_mail_client(), MailComMailProvider)
