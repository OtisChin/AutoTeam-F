import pytest

from autotoken.core.files import READ_LINES_FILE_MAX_BYTES
from autotoken.mail.outlook import OutlookMailProvider


class FakeResponse:
    def __init__(self, payload=None, *, text="", status_code=200):
        self._payload = payload
        self.text = text if text else (str(payload) if payload is not None else "")
        self.status_code = status_code

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def test_parse_outlook_account_line_supports_codex_console_format():
    account = OutlookMailProvider._parse_account_line(
        "User@Outlook.com----mail-pass----client-id----refresh-token"
    )

    assert account.email == "user@outlook.com"
    assert account.password == "mail-pass"
    assert account.client_id == "client-id"
    assert account.refresh_token == "refresh-token"
    assert account.has_oauth()


def test_parse_outlook_account_line_supports_mailapi_url_format():
    account = OutlookMailProvider._parse_account_line(
        "LisaTaylor6398@hotmail.com----https://mailapi.icu/key?type=html&orderNo=f5706957db1af386"
    )

    assert account.email == "lisataylor6398@hotmail.com"
    assert account.password == ""
    assert account.mailapi_url == "https://mailapi.icu/key?type=html&orderNo=f5706957db1af386"
    assert account.has_mailapi()
    assert account.validate()


def test_parse_outlook_account_line_supports_pipe_refresh_token_before_client_id():
    account = OutlookMailProvider._parse_account_line(
        "User@Hotmail.com|mail-pass|M.C556_BAY.0.U.-long-refresh-token-value-"
        "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx|"
        "9e5f94bc-e8a4-4e73-b8be-63364c29d753"
    )

    assert account.email == "user@hotmail.com"
    assert account.password == "mail-pass"
    assert account.client_id == "9e5f94bc-e8a4-4e73-b8be-63364c29d753"
    assert account.refresh_token.startswith("M.C556_BAY")
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


def test_create_temp_email_skips_persisted_registered_accounts_after_restart(tmp_path, monkeypatch):
    from autotoken.storage import outlook_pool

    monkeypatch.setattr(outlook_pool, "STATE_FILE", tmp_path / "outlook_pool.json")
    outlook_pool.mark_registered_email("used@outlook.com", source="register_success")

    restarted = OutlookMailProvider()
    restarted.accounts = [
        OutlookMailProvider._parse_account_line("used@outlook.com----p"),
        OutlookMailProvider._parse_account_line("new@outlook.com----p"),
    ]

    account_id, email = restarted.create_temp_email()

    assert account_id == "new@outlook.com"
    assert email == "new@outlook.com"


def test_list_accounts_limits_and_marks_account_capabilities():
    client = OutlookMailProvider()
    client.accounts = [
        OutlookMailProvider._parse_account_line("first@outlook.com----p"),
        OutlookMailProvider._parse_account_line("second@outlook.com----https://mailapi.icu/key?type=html&orderNo=abc"),
    ]

    assert client.list_accounts(size=1) == [
        {
            "id": "first@outlook.com",
            "email": "first@outlook.com",
            "accountEmail": "first@outlook.com",
            "has_oauth": False,
            "has_mailapi": False,
            "provider": "outlook",
        }
    ]
    assert client.list_accounts(size=2)[1] == {
        "id": "second@outlook.com",
        "email": "second@outlook.com",
        "accountEmail": "second@outlook.com",
        "has_oauth": False,
        "has_mailapi": True,
        "provider": "outlook",
    }


def test_search_emails_by_recipient_reads_mailapi_html(monkeypatch):
    client = OutlookMailProvider()
    client.accounts = [
        OutlookMailProvider._parse_account_line(
            "user@hotmail.com----https://mailapi.icu/key?type=html&orderNo=abc"
        )
    ]

    def fake_get(*args, **kwargs):
        return FakeResponse(
            None,
            text="<html><body>Your OpenAI verification code is <b>123456</b></body></html>",
        )

    monkeypatch.setattr("autotoken.mail.outlook.curl_requests.get", fake_get)

    messages = client.search_emails_by_recipient("user@hotmail.com", account_id="user@hotmail.com")

    assert len(messages) == 1
    assert messages[0]["accountId"] == "user@hotmail.com"
    assert client.extract_verification_code(messages[0]) == "123456"


def test_search_emails_by_recipient_reads_mailapi_json(monkeypatch):
    client = OutlookMailProvider()
    client.accounts = [
        OutlookMailProvider._parse_account_line(
            "user@hotmail.com----https://mailapi.icu/key?type=html&orderNo=abc"
        )
    ]

    def fake_get(*args, **kwargs):
        return FakeResponse(
            {
                "code": 0,
                "data": {
                    "subject": "OpenAI code",
                    "html": "<div>Use 654321 to continue.</div>",
                    "from": "noreply@openai.com",
                },
            }
        )

    monkeypatch.setattr("autotoken.mail.outlook.curl_requests.get", fake_get)

    messages = client.search_emails_by_recipient("user@hotmail.com", account_id="user@hotmail.com")

    assert messages[0]["sendEmail"] == "noreply@openai.com"
    assert client.extract_verification_code(messages[0]) == "654321"


def test_search_emails_by_recipient_treats_mailapi_404_as_empty(monkeypatch):
    client = OutlookMailProvider()
    client.accounts = [
        OutlookMailProvider._parse_account_line(
            "user@hotmail.com----https://mailapi.icu/key?type=html&orderNo=abc"
        )
    ]

    def fake_get(*args, **kwargs):
        return FakeResponse(None, text='{"error":"未找到符合规则的邮件"}', status_code=404)

    monkeypatch.setattr("autotoken.mail.outlook.curl_requests.get", fake_get)

    assert client.search_emails_by_recipient("user@hotmail.com", account_id="user@hotmail.com") == []


def test_factory_returns_outlook_provider(monkeypatch):
    monkeypatch.setenv("MAIL_PROVIDER", "outlook")
    from autotoken.mail import get_mail_client

    assert isinstance(get_mail_client(), OutlookMailProvider)


def test_load_accounts_ignores_relative_file_path_outside_project(tmp_path, monkeypatch):
    outside = tmp_path.parent / f"outside-outlook-{tmp_path.name}.txt"
    outside.write_text("user@outlook.com----mail-pass\n", encoding="utf-8")
    monkeypatch.setattr("autotoken.mail.outlook.PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("OUTLOOK_ACCOUNTS", raising=False)
    monkeypatch.setenv("OUTLOOK_ACCOUNTS_FILE", f"../{outside.name}")

    client = OutlookMailProvider()

    assert client.accounts == []


def test_load_accounts_rejects_oversized_account_file(tmp_path, monkeypatch):
    account_file = tmp_path / "outlook_accounts.txt"
    account_file.write_text("x" * (READ_LINES_FILE_MAX_BYTES + 1), encoding="utf-8")
    monkeypatch.delenv("OUTLOOK_ACCOUNTS", raising=False)
    monkeypatch.setenv("OUTLOOK_ACCOUNTS_FILE", str(account_file))

    with pytest.raises(ValueError, match="文件过大"):
        OutlookMailProvider()
