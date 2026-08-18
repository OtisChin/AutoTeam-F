from autotoken.mail.generic_api import GenericApiMailProvider


class FakeResponse:
    def __init__(self, payload=None, *, text="", status_code=200):
        self._payload = payload
        self.text = text if text else (str(payload) if payload is not None else "")
        self.status_code = status_code

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def test_parse_generic_api_account_line_accepts_any_domain_receive_code_link():
    account = GenericApiMailProvider._parse_account_line(
        "nanette_hayspjq@birdlover.com----https://example.trycloudflare.com/code/token"
    )

    assert account.email == "nanette_hayspjq@birdlover.com"
    assert account.receive_code_url == "https://example.trycloudflare.com/code/token"
    assert account.validate()


def test_parse_generic_api_account_line_accepts_five_hyphen_separator():
    account = GenericApiMailProvider._parse_account_line(
        "2om2y576g4@mgbubu.com-----https://icloud.api.mgbubu.com/api/v1/otp?token=icm_ZGx0AwAAAAAAAAkMDr7OG0JmD9HL48ZFysbk8tsBFy0"
    )

    assert account.email == "2om2y576g4@mgbubu.com"
    assert account.receive_code_url == "https://icloud.api.mgbubu.com/api/v1/otp?token=icm_ZGx0AwAAAAAAAAkMDr7OG0JmD9HL48ZFysbk8tsBFy0"
    assert account.validate()


def test_create_temp_email_skips_registered_and_filters_domain(monkeypatch):
    client = GenericApiMailProvider()
    client.accounts = [
        GenericApiMailProvider._parse_account_line("used@birdlover.com----https://example.com/code/used"),
        GenericApiMailProvider._parse_account_line("fresh@other.com----https://example.com/code/other"),
        GenericApiMailProvider._parse_account_line("fresh@birdlover.com----https://example.com/code/fresh"),
    ]
    monkeypatch.setattr(GenericApiMailProvider, "_registered_emails", staticmethod(lambda: {"used@birdlover.com"}))

    assert client.create_temp_email(domain="birdlover.com") == ("fresh@birdlover.com", "fresh@birdlover.com")


def test_search_emails_by_recipient_reads_json_code_link(monkeypatch):
    client = GenericApiMailProvider()
    client.accounts = [
        GenericApiMailProvider._parse_account_line("user@birdlover.com----https://example.com/code/user")
    ]

    def fake_get(*args, **kwargs):
        return FakeResponse(
            {
                "data": {
                    "subject": "Your temporary ChatGPT login code",
                    "content": "Use code 654321 to continue",
                    "from": "noreply@tm.openai.com",
                }
            }
        )

    monkeypatch.setattr("autotoken.mail.icloud.curl_requests.get", fake_get)

    messages = client.search_emails_by_recipient("user@birdlover.com", account_id="user@birdlover.com")

    assert len(messages) == 1
    assert messages[0]["provider"] == "generic-api"
    assert client.extract_verification_code(messages[0]) == "654321"


def test_search_emails_by_recipient_reads_plain_or_html_link(monkeypatch):
    client = GenericApiMailProvider()
    client.accounts = [
        GenericApiMailProvider._parse_account_line("user@birdlover.com----https://example.com/code/user")
    ]

    def fake_get(*args, **kwargs):
        return FakeResponse(None, text="<html><body>Your OpenAI verification code is <b>123456</b></body></html>")

    monkeypatch.setattr("autotoken.mail.icloud.curl_requests.get", fake_get)

    messages = client.search_emails_by_recipient("user@birdlover.com", account_id="user@birdlover.com")

    assert len(messages) == 1
    assert messages[0]["provider"] == "generic-api"
    assert client.extract_verification_code(messages[0]) == "123456"


def test_search_emails_by_recipient_parses_code_inside_mail_field(monkeypatch):
    client = GenericApiMailProvider()
    client.accounts = [
        GenericApiMailProvider._parse_account_line("user@birdlover.com----https://example.com/code/user")
    ]

    def fake_get(*args, **kwargs):
        return FakeResponse(
            {
                "email": "user@birdlover.com",
                "code": None,
                "mail": {
                    "subject": "Your verification code",
                    "content": "Use code 246810 to continue",
                    "from": "noreply@tm.openai.com",
                },
            }
        )

    monkeypatch.setattr("autotoken.mail.icloud.curl_requests.get", fake_get)

    messages = client.search_emails_by_recipient("user@birdlover.com", account_id="user@birdlover.com")

    assert len(messages) == 1
    assert messages[0]["provider"] == "generic-api"
    assert client.extract_verification_code(messages[0]) == "246810"


def test_search_emails_by_recipient_ignores_empty_code_and_empty_mail(monkeypatch):
    client = GenericApiMailProvider()
    client.accounts = [
        GenericApiMailProvider._parse_account_line("user@birdlover.com----https://example.com/code/user")
    ]

    def fake_get(*args, **kwargs):
        return FakeResponse({"email": "user@birdlover.com", "code": None, "mail": None})

    monkeypatch.setattr("autotoken.mail.icloud.curl_requests.get", fake_get)

    messages = client.search_emails_by_recipient("user@birdlover.com", account_id="user@birdlover.com")

    assert messages == []


def test_search_emails_by_recipient_caches_live_generic_api_message(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "cache.sqlite3"))
    from autotoken.storage.generic_api_pool import get_cached_mail_message

    client = GenericApiMailProvider()
    client.accounts = [
        GenericApiMailProvider._parse_account_line("user@birdlover.com----https://example.com/code/user")
    ]

    def fake_get(*args, **kwargs):
        return FakeResponse(
            {
                "email": "user@birdlover.com",
                "code": "135790",
                "mail": {"subject": "Your verification code", "content": "Use 135790"},
            }
        )

    monkeypatch.setattr("autotoken.mail.icloud.curl_requests.get", fake_get)

    messages = client.search_emails_by_recipient("user@birdlover.com", account_id="user@birdlover.com")
    cached = get_cached_mail_message("user@birdlover.com")

    assert len(messages) == 1
    assert cached["subject"] == "Your verification code"
    assert cached["content"] == messages[0]["content"]


def test_factory_and_setup_schema_accept_generic_api(monkeypatch):
    monkeypatch.setenv("MAIL_PROVIDER", "通用API")

    from autotoken.mail import get_mail_client
    from autotoken.settings.setup_wizard import get_mail_provider, get_setup_schema

    assert isinstance(get_mail_client(), GenericApiMailProvider)
    assert get_mail_provider("generic_api") == "generic-api"

    schema = get_setup_schema({"MAIL_PROVIDER": "generic-api"})
    assert any(option["value"] == "generic-api" and option["label"] == "通用API" for option in schema["provider_options"])
    assert schema["provider_fields"]["generic-api"] == [
        {
            "key": "GENERIC_API_ACCOUNTS_FILE",
            "prompt": "通用API账号池文件路径（默认 data/generic_api_accounts.txt）",
            "default": "data/generic_api_accounts.txt",
            "optional": True,
        },
        {
            "key": "GENERIC_API_ACCOUNTS",
            "prompt": "通用API账号池内联（email--收码链接，2个及以上-都可，每行/分号分隔）",
            "default": "",
            "optional": True,
        },
    ]
