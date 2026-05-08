from autoteam.mail.luckmail import LuckMailProvider


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


def test_parse_luckmail_account_line_supports_token_format():
    account = LuckMailProvider._parse_account_line(
        "JasmineHuynh4883@outlook.my----tok_f644e3245a2330313c334a43df1bd75d"
    )

    assert account.email == "jasminehuynh4883@outlook.my"
    assert account.token == "tok_f644e3245a2330313c334a43df1bd75d"


def test_create_temp_email_returns_token_as_account_id(monkeypatch):
    client = LuckMailProvider()
    client.accounts = [LuckMailProvider._parse_account_line("new@outlook.my----tok_1")]
    client._tokens_by_email = {"new@outlook.my": "tok_1"}
    client._emails_by_token = {"tok_1": "new@outlook.my"}
    monkeypatch.setattr(LuckMailProvider, "_registered_emails", staticmethod(lambda: set()))

    account_id, email = client.create_temp_email()

    assert account_id == "tok_1"
    assert email == "new@outlook.my"


def test_create_temp_email_purchases_when_loaded_pool_is_reserved(monkeypatch):
    client = LuckMailProvider()
    client.api_key = "key"
    client.accounts = [LuckMailProvider._parse_account_line("used@outlook.com----tok_used")]
    client._tokens_by_email = {"used@outlook.com": "tok_used"}
    client._emails_by_token = {"tok_used": "used@outlook.com"}
    client._reserved = {"used@outlook.com"}
    monkeypatch.setattr(LuckMailProvider, "_registered_emails", staticmethod(lambda: set()))
    monkeypatch.setattr(
        LuckMailProvider,
        "_purchase_account",
        lambda self, domain=None: LuckMailProvider._parse_account_line("next@outlook.com----tok_next"),
    )

    account_id, email = client.create_temp_email(domain="outlook.com")

    assert account_id == "tok_next"
    assert email == "next@outlook.com"
    assert "next@outlook.com" in client._reserved


def test_search_emails_by_recipient_reads_latest_token_code(monkeypatch):
    client = LuckMailProvider()
    client.accounts = [LuckMailProvider._parse_account_line("user@outlook.my----tok_abc")]
    client._tokens_by_email = {"user@outlook.my": "tok_abc"}
    client._emails_by_token = {"tok_abc": "user@outlook.my"}

    def fake_request(self, method, path, **kwargs):
        if path.endswith("/code"):
            return FakeResponse(
                {
                    "code": 0,
                    "message": "success",
                    "data": {
                        "alive": True,
                        "code": "123456",
                        "email_address": "user@outlook.my",
                        "mail": {
                            "message_id": "m1",
                            "from": "noreply@openai.com",
                            "subject": "Your OpenAI verification code",
                        },
                    },
                }
            )
        return FakeResponse(
            {
                "code": 0,
                "message": "success",
                "data": {"alive": True, "email_address": "user@outlook.my", "mails": []},
            }
        )

    monkeypatch.setattr(LuckMailProvider, "_request", fake_request)

    messages = client.search_emails_by_recipient("user@outlook.my", account_id="tok_abc")

    assert len(messages) == 1
    assert messages[0]["accountId"] == "tok_abc"
    assert client.extract_verification_code(messages[0]) == "123456"


def test_search_uses_account_id_token_without_static_mapping(monkeypatch):
    client = LuckMailProvider()
    client.accounts = []
    client._tokens_by_email = {}
    client._emails_by_token = {}

    def fake_request(self, method, path, **kwargs):
        if path.endswith("/code"):
            return FakeResponse(
                {
                    "code": 0,
                    "message": "success",
                    "data": {
                        "code": "654321",
                        "email_address": "dynamic@outlook.com",
                        "mail": {"message_id": "m2", "subject": "OpenAI code"},
                    },
                }
            )
        return FakeResponse({"code": 0, "data": {"mails": [], "email_address": "dynamic@outlook.com"}})

    monkeypatch.setattr(LuckMailProvider, "_request", fake_request)

    messages = client.search_emails_by_recipient("dynamic@outlook.com", account_id="tok_dynamic")

    assert messages[0]["accountId"] == "tok_dynamic"
    assert client.extract_verification_code(messages[0]) == "654321"


def test_factory_returns_luckmail_provider(monkeypatch):
    monkeypatch.setenv("MAIL_PROVIDER", "luckmail")
    from autoteam.mail import get_mail_client

    assert isinstance(get_mail_client(), LuckMailProvider)
