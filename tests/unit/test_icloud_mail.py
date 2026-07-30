from autotoken.mail.icloud import ICloudMailProvider


class FakeResponse:
    def __init__(self, payload=None, *, text="", status_code=200):
        self._payload = payload
        self.text = text if text else (str(payload) if payload is not None else "")
        self.status_code = status_code

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def test_parse_icloud_account_line_supports_receive_code_link_format():
    account = ICloudMailProvider._parse_account_line(
        "46.prequel_plumb@icloud.com----https://icloud-api.top/show/token/46.prequel_plumb@icloud.com"
    )

    assert account.email == "46.prequel_plumb@icloud.com"
    assert account.receive_code_url == "https://icloud-api.top/show/token/46.prequel_plumb@icloud.com"
    assert account.validate()


def test_create_temp_email_skips_registered_accounts(monkeypatch):
    client = ICloudMailProvider()
    client.accounts = [
        ICloudMailProvider._parse_account_line("used@icloud.com----https://icloud-api.top/show/token/used@icloud.com"),
        ICloudMailProvider._parse_account_line("new@icloud.com----https://icloud-api.top/show/token/new@icloud.com"),
    ]
    monkeypatch.setattr(ICloudMailProvider, "_registered_emails", staticmethod(lambda: {"used@icloud.com"}))

    account_id, email = client.create_temp_email()

    assert account_id == "new@icloud.com"
    assert email == "new@icloud.com"


def test_search_emails_by_recipient_reads_receive_code_link_html(monkeypatch):
    client = ICloudMailProvider()
    client.accounts = [
        ICloudMailProvider._parse_account_line("user@icloud.com----https://icloud-api.top/show/token/user@icloud.com")
    ]

    def fake_get(*args, **kwargs):
        return FakeResponse(
            None,
            text="<html><body>Your OpenAI verification code is <b>123456</b></body></html>",
        )

    monkeypatch.setattr("autotoken.mail.icloud.curl_requests.get", fake_get)

    messages = client.search_emails_by_recipient("user@icloud.com", account_id="user@icloud.com")

    assert len(messages) == 1
    assert messages[0]["accountId"] == "user@icloud.com"
    assert messages[0]["provider"] == "icloud"
    assert client.extract_verification_code(messages[0]) == "123456"


def test_search_emails_by_recipient_reads_receive_code_link_json(monkeypatch):
    client = ICloudMailProvider()
    client.accounts = [
        ICloudMailProvider._parse_account_line("user@icloud.com----https://icloud-api.top/show/token/user@icloud.com")
    ]

    def fake_get(*args, **kwargs):
        return FakeResponse(
            {
                "data": {
                    "subject": "Your temporary ChatGPT verification code",
                    "content": "Use code 654321 to continue",
                    "from": "noreply@tm.openai.com",
                }
            }
        )

    monkeypatch.setattr("autotoken.mail.icloud.curl_requests.get", fake_get)

    messages = client.search_emails_by_recipient("user@icloud.com", account_id="user@icloud.com")

    assert len(messages) == 1
    assert messages[0]["subject"] == "Your temporary ChatGPT verification code"
    assert client.extract_verification_code(messages[0]) == "654321"


def test_factory_accepts_icloud_provider(monkeypatch):
    monkeypatch.setenv("MAIL_PROVIDER", "icloud")

    from autotoken.mail import get_mail_client

    client = get_mail_client()

    assert isinstance(client, ICloudMailProvider)


def test_setup_schema_exposes_icloud_provider_fields():
    from autotoken.settings.setup_wizard import get_mail_provider, get_setup_schema

    assert get_mail_provider("iCloud") == "icloud"

    schema = get_setup_schema({"MAIL_PROVIDER": "icloud"})

    assert any(option["value"] == "icloud" and option["label"] == "iCloud" for option in schema["provider_options"])
    assert schema["provider_fields"]["icloud"] == [
        {
            "key": "ICLOUD_ACCOUNTS_FILE",
            "prompt": "iCloud 账号池文件路径（默认 data/icloud_accounts.txt）",
            "default": "data/icloud_accounts.txt",
            "optional": True,
        },
        {
            "key": "ICLOUD_ACCOUNTS",
            "prompt": "iCloud 账号池内联（email----收码链接，每行/分号分隔）",
            "default": "",
            "optional": True,
        },
    ]
