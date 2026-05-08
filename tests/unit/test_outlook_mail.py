import pytest

from autoteam.mail.outlook import OutlookMailProvider


def test_parse_outlook_account_line_supports_codex_console_format():
    account = OutlookMailProvider._parse_account_line(
        "User@Outlook.com----mail-pass----client-id----refresh-token"
    )

    assert account.email == "user@outlook.com"
    assert account.password == "mail-pass"
    assert account.client_id == "client-id"
    assert account.refresh_token == "refresh-token"
    assert account.has_oauth()


def test_create_temp_email_skips_registered_accounts(monkeypatch):
    client = OutlookMailProvider()
    client.accounts = [
        OutlookMailProvider._parse_account_line("used@outlook.com----p"),
        OutlookMailProvider._parse_account_line("new@outlook.com----p"),
    ]
    monkeypatch.setattr(OutlookMailProvider, "_registered_emails", staticmethod(lambda: {"used@outlook.com"}))

    account_id, email = client.create_temp_email()

    assert account_id == "new@outlook.com"
    assert email == "new@outlook.com"


def test_create_temp_email_exhausted_when_all_registered(monkeypatch):
    client = OutlookMailProvider()
    client.accounts = [OutlookMailProvider._parse_account_line("used@outlook.com----p")]
    monkeypatch.setattr(OutlookMailProvider, "_registered_emails", staticmethod(lambda: {"used@outlook.com"}))

    with pytest.raises(RuntimeError, match="没有可用的 Outlook 账号"):
        client.create_temp_email()


def test_factory_returns_outlook_provider(monkeypatch):
    monkeypatch.setenv("MAIL_PROVIDER", "outlook")
    from autoteam.mail import get_mail_client

    assert isinstance(get_mail_client(), OutlookMailProvider)
