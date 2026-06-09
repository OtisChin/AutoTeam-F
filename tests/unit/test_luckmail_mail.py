import pytest

from autotoken.core.files import READ_LINES_FILE_MAX_BYTES
from autotoken.mail.luckmail import LuckMailProvider


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


def test_luckmail_does_not_reuse_persisted_cache_by_default(monkeypatch, tmp_path):
    from autotoken import sqlite_store

    monkeypatch.setattr("autotoken.mail.luckmail.PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.delenv("LUCKMAIL_ACCOUNTS", raising=False)
    monkeypatch.delenv("LUCKMAIL_ACCOUNTS_FILE", raising=False)
    monkeypatch.delenv("LUCKMAIL_REUSE_PURCHASED_CACHE", raising=False)
    monkeypatch.setenv("LUCKMAIL_API_KEY", "luck-key")
    sqlite_store.set_json(
        "luckmail",
        "accounts",
        [{"email": "cached@example.com", "token": "tok_cached_1234567890abcdef", "purchase_id": "old"}],
    )

    client = LuckMailProvider()

    assert client.accounts == []


def test_luckmail_reuses_persisted_api_purchased_account_when_enabled(monkeypatch, tmp_path):
    from autotoken import sqlite_store

    monkeypatch.setattr("autotoken.mail.luckmail.PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.delenv("LUCKMAIL_ACCOUNTS", raising=False)
    monkeypatch.delenv("LUCKMAIL_ACCOUNTS_FILE", raising=False)
    monkeypatch.setenv("LUCKMAIL_REUSE_PURCHASED_CACHE", "1")
    monkeypatch.setenv("LUCKMAIL_API_KEY", "luck-key")
    sqlite_store.set_json("luckmail", "accounts", [])

    client = LuckMailProvider()
    monkeypatch.setattr(
        client,
        "_purchase_account",
        lambda domain=None: LuckMailProvider._parse_account_line(
            "kept@example.com----tok_kept_1234567890abcdef----purchase-1"
        ),
    )

    account_id, email = client.create_temp_email()
    restarted = LuckMailProvider()

    assert account_id == "tok_kept_1234567890abcdef"
    assert email == "kept@example.com"
    assert any(
        account.email == "kept@example.com" and account.token == "tok_kept_1234567890abcdef"
        for account in restarted.accounts
    )


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


def test_search_extracts_code_from_luckmail_mail_text_alias(monkeypatch):
    client = LuckMailProvider()
    client.accounts = [LuckMailProvider._parse_account_line("user@outlook.my----tok_abc")]
    client._tokens_by_email = {"user@outlook.my": "tok_abc"}
    client._emails_by_token = {"tok_abc": "user@outlook.my"}

    def fake_request(self, method, path, **kwargs):
        if path.endswith("/code"):
            return FakeResponse({"code": 0, "data": {"alive": True, "email_address": "user@outlook.my"}})
        return FakeResponse(
            {
                "code": 0,
                "data": {
                    "alive": True,
                    "email_address": "user@outlook.my",
                    "mails": [
                        {
                            "message_id": "m3",
                            "mail_from": "noreply@tm.openai.com",
                            "mail_subject": "Your ChatGPT code",
                            "mail_text": "Your ChatGPT code is 789012.",
                            "receive_time": "2026-06-02 12:38:05",
                        }
                    ],
                },
            }
        )

    monkeypatch.setattr(LuckMailProvider, "_request", fake_request)

    messages = client.search_emails_by_recipient("user@outlook.my", account_id="tok_abc")

    assert len(messages) == 1
    assert messages[0]["createTime"] == "2026-06-02 12:38:05"
    assert client.extract_verification_code(messages[0]) == "789012"


def test_search_normalizes_luckmail_naive_received_at_as_utc(monkeypatch):
    client = LuckMailProvider()
    client.accounts = [LuckMailProvider._parse_account_line("user@outlook.my----tok_abc")]
    client._tokens_by_email = {"user@outlook.my": "tok_abc"}
    client._emails_by_token = {"tok_abc": "user@outlook.my"}

    def fake_request(self, method, path, **kwargs):
        if path.endswith("/code"):
            return FakeResponse(
                {
                    "code": 0,
                    "data": {
                        "email_address": "user@outlook.my",
                        "verification_code": "456789",
                        "mail": {
                            "message_id": "m-utc",
                            "subject": "Your temporary OpenAI verification code",
                            "received_at": "2026-06-09 09:11:46",
                        },
                    },
                }
            )
        return FakeResponse({"code": 0, "data": {"mails": [], "email_address": "user@outlook.my"}})

    monkeypatch.setattr(LuckMailProvider, "_request", fake_request)

    messages = client.search_emails_by_recipient("user@outlook.my", account_id="tok_abc")

    assert messages[0]["received_at"] == 1780996306.0
    assert messages[0]["verification_code"] == "456789"
    assert client.extract_verification_code(messages[0]) == "456789"


def test_search_extracts_code_from_luckmail_body_text_alias(monkeypatch):
    client = LuckMailProvider()
    client.accounts = [LuckMailProvider._parse_account_line("user@outlook.my----tok_abc")]
    client._tokens_by_email = {"user@outlook.my": "tok_abc"}
    client._emails_by_token = {"tok_abc": "user@outlook.my"}

    def fake_request(self, method, path, **kwargs):
        if path.endswith("/code"):
            return FakeResponse({"code": 0, "data": {"alive": True, "email_address": "user@outlook.my"}})
        return FakeResponse(
            {
                "code": 0,
                "data": {
                    "alive": True,
                    "email_address": "user@outlook.my",
                    "mails": [
                        {
                            "message_id": "m-body-text",
                            "subject": "Your temporary OpenAI verification code",
                            "body_text": "Your temporary OpenAI verification code is 234567.",
                            "received_at": "2026-06-09 09:11:46",
                        }
                    ],
                },
            }
        )

    monkeypatch.setattr(LuckMailProvider, "_request", fake_request)

    messages = client.search_emails_by_recipient("user@outlook.my", account_id="tok_abc")

    assert client.extract_verification_code(messages[0]) == "234567"


def test_search_extracts_code_from_nested_luckmail_mail_payload(monkeypatch):
    client = LuckMailProvider()
    client.accounts = [LuckMailProvider._parse_account_line("user@outlook.my----tok_abc")]
    client._tokens_by_email = {"user@outlook.my": "tok_abc"}
    client._emails_by_token = {"tok_abc": "user@outlook.my"}

    def fake_request(self, method, path, **kwargs):
        if path.endswith("/code"):
            return FakeResponse({"code": 0, "data": {"email_address": "user@outlook.my"}})
        return FakeResponse(
            {
                "code": 0,
                "data": {
                    "email_address": "user@outlook.my",
                    "mails": [
                        {
                            "id": "m4",
                            "mail": {
                                "subject": "OpenAI email verification",
                                "html_body": "<p>Your verification code is <b>345678</b></p>",
                                "createdAt": "2026-06-02T12:38:08Z",
                            },
                        }
                    ],
                },
            }
        )

    monkeypatch.setattr(LuckMailProvider, "_request", fake_request)

    messages = client.search_emails_by_recipient("user@outlook.my", account_id="tok_abc")

    assert messages[0]["id"] == "m4"
    assert client.extract_verification_code(messages[0]) == "345678"


def test_factory_returns_luckmail_provider(monkeypatch):
    monkeypatch.setenv("MAIL_PROVIDER", "luckmail")
    from autotoken.mail import get_mail_client

    assert isinstance(get_mail_client(), LuckMailProvider)


def test_load_accounts_ignores_relative_file_path_outside_project(tmp_path, monkeypatch):
    outside = tmp_path.parent / f"outside-luckmail-{tmp_path.name}.txt"
    outside.write_text("user@outlook.my----tok_1234567890abcdef\n", encoding="utf-8")
    monkeypatch.setattr("autotoken.mail.luckmail.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("autotoken.mail.luckmail.sqlite_store.get_json", lambda *_args, **_kwargs: [])
    monkeypatch.delenv("LUCKMAIL_ACCOUNTS", raising=False)
    monkeypatch.setenv("LUCKMAIL_ACCOUNTS_FILE", f"../{outside.name}")

    client = LuckMailProvider()

    assert client.accounts == []


def test_load_accounts_rejects_oversized_account_file(tmp_path, monkeypatch):
    account_file = tmp_path / "luckmail_accounts.txt"
    account_file.write_text("x" * (READ_LINES_FILE_MAX_BYTES + 1), encoding="utf-8")
    monkeypatch.setattr("autotoken.mail.luckmail.sqlite_store.get_json", lambda *_args, **_kwargs: [])
    monkeypatch.delenv("LUCKMAIL_ACCOUNTS", raising=False)
    monkeypatch.setenv("LUCKMAIL_ACCOUNTS_FILE", str(account_file))

    with pytest.raises(ValueError, match="文件过大"):
        LuckMailProvider()
