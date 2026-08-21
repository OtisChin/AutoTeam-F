import pytest

from autotoken.mail.mailu import MailuMailProvider


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


def test_login_requires_config(monkeypatch):
    monkeypatch.delenv("MAILU_BASE_URL", raising=False)
    monkeypatch.delenv("MAILU_API_KEY", raising=False)
    monkeypatch.delenv("MAILU_API_URL", raising=False)

    client = MailuMailProvider()

    with pytest.raises(RuntimeError) as exc:
        client.login()
    assert "MAILU_BASE_URL" in str(exc.value)


def test_login_verifies_health(monkeypatch):
    monkeypatch.setenv("MAILU_BASE_URL", "https://mail.example.com/mail-api/")
    monkeypatch.setenv("MAILU_API_KEY", "secret")

    captured = {}

    def fake_get(url, *args, **kwargs):
        captured["url"] = url
        captured["params"] = kwargs.get("params") or {}
        captured["headers"] = kwargs.get("headers") or {}
        return FakeResponse({"ok": True})

    monkeypatch.setattr("autotoken.mail.mailu.curl_requests.get", fake_get)

    client = MailuMailProvider()
    token = client.login()

    assert token == "mailu:https://mail.example.com/mail-api"
    assert captured["url"] == "https://mail.example.com/mail-api/health"
    assert captured["params"]["key"] == "secret"
    assert captured["headers"]["X-API-Key"] == "secret"


def test_login_rejects_bad_health(monkeypatch):
    monkeypatch.setenv("MAILU_BASE_URL", "https://mail.example.com/mail-api/")
    monkeypatch.setenv("MAILU_API_KEY", "secret")

    def fake_get(*args, **kwargs):
        return FakeResponse({"ok": False})

    monkeypatch.setattr("autotoken.mail.mailu.curl_requests.get", fake_get)

    with pytest.raises(RuntimeError) as exc:
        MailuMailProvider().login()
    assert "健康检查未通过" in str(exc.value)


def test_create_temp_email_uses_prefix_and_domain(monkeypatch):
    monkeypatch.setenv("MAILU_BASE_URL", "https://mail.example.com/mail-api/")
    monkeypatch.setenv("MAILU_API_KEY", "secret")
    monkeypatch.setenv("MAILU_DOMAIN", "openaibus.com")

    client = MailuMailProvider()
    account_id, email = client.create_temp_email(prefix="abc", domain="openaibus.com")

    assert account_id == email
    assert email.startswith("abc@openaibus.com")
    assert email.endswith("@openaibus.com")


def test_create_temp_email_uses_default_domain(monkeypatch):
    monkeypatch.setenv("MAILU_BASE_URL", "https://mail.example.com/mail-api/")
    monkeypatch.setenv("MAILU_API_KEY", "secret")
    monkeypatch.setenv("MAILU_DOMAIN", "openaibus.com")

    client = MailuMailProvider()
    _, email = client.create_temp_email()

    assert email.endswith("@openaibus.com")


def test_create_temp_email_requires_domain(monkeypatch):
    monkeypatch.setenv("MAILU_BASE_URL", "https://mail.example.com/mail-api/")
    monkeypatch.setenv("MAILU_API_KEY", "secret")
    monkeypatch.delenv("MAILU_DOMAIN", raising=False)

    client = MailuMailProvider()

    with pytest.raises(RuntimeError) as exc:
        client.create_temp_email()
    assert "MAILU_DOMAIN" in str(exc.value)


def test_search_emails_by_recipient_reads_code(monkeypatch):
    monkeypatch.setenv("MAILU_BASE_URL", "https://mail.example.com/mail-api/")
    monkeypatch.setenv("MAILU_API_KEY", "secret")
    monkeypatch.setenv("MAILU_DOMAIN", "openaibus.com")

    captured = {}

    def fake_get(url, *args, **kwargs):
        captured["url"] = url
        captured["params"] = kwargs.get("params") or {}
        return FakeResponse(
            {
                "ok": True,
                "target": "abc@openaibus.com",
                "code": "123456",
                "codes": ["123456"],
                "uid": "123",
                "subject": "验证码",
                "from": "service@example.com",
                "to": "abc@openaibus.com",
                "date": "Thu, 21 Aug 2026 10:00:00 +0800",
                "message_id": "<xxx@example.com>",
            }
        )

    monkeypatch.setattr("autotoken.mail.mailu.curl_requests.get", fake_get)

    client = MailuMailProvider()
    messages = client.search_emails_by_recipient("abc@openaibus.com", account_id="abc@openaibus.com")

    assert captured["url"] == "https://mail.example.com/mail-api/code"
    assert captured["params"]["to"] == "abc@openaibus.com"
    assert len(messages) == 1
    assert messages[0]["provider"] == "mailu"
    assert messages[0]["subject"] == "验证码"
    assert messages[0]["sendEmail"] == "service@example.com"
    assert client.extract_verification_code(messages[0]) == "123456"


def test_search_emails_by_recipient_no_matching_code(monkeypatch):
    monkeypatch.setenv("MAILU_BASE_URL", "https://mail.example.com/mail-api/")
    monkeypatch.setenv("MAILU_API_KEY", "secret")

    def fake_get(*args, **kwargs):
        return FakeResponse(
            {
                "ok": False,
                "target": "abc@openaibus.com",
                "error": "no matching code found",
                "matched_count": 0,
                "checked": 20,
            }
        )

    monkeypatch.setattr("autotoken.mail.mailu.curl_requests.get", fake_get)

    client = MailuMailProvider()
    messages = client.search_emails_by_recipient("abc@openaibus.com", account_id="abc@openaibus.com")

    assert messages == []


def test_list_emails_reads_latest(monkeypatch):
    monkeypatch.setenv("MAILU_BASE_URL", "https://mail.example.com/mail-api/")
    monkeypatch.setenv("MAILU_API_KEY", "secret")

    captured = {}

    def fake_get(url, *args, **kwargs):
        captured["url"] = url
        return FakeResponse(
            {
                "ok": True,
                "count": 1,
                "messages": [
                    {
                        "uid": "123",
                        "subject": "验证码",
                        "from": "service@example.com",
                        "to": "abc@openaibus.com",
                        "date": "Thu, 21 Aug 2026 10:00:00 +0800",
                        "message_id": "<xxx@example.com>",
                        "codes": ["123456"],
                        "code": "123456",
                        "body": "您的验证码是 123456",
                    }
                ],
            }
        )

    monkeypatch.setattr("autotoken.mail.mailu.curl_requests.get", fake_get)

    client = MailuMailProvider()
    messages = client.list_emails("abc@openaibus.com", size=10)

    assert captured["url"] == "https://mail.example.com/mail-api/latest"
    assert len(messages) == 1
    assert messages[0]["provider"] == "mailu"
    assert client.extract_verification_code(messages[0]) == "123456"


def test_list_emails_filters_other_recipients(monkeypatch):
    monkeypatch.setenv("MAILU_BASE_URL", "https://mail.example.com/mail-api/")
    monkeypatch.setenv("MAILU_API_KEY", "secret")

    def fake_get(*args, **kwargs):
        return FakeResponse(
            {
                "ok": True,
                "count": 2,
                "messages": [
                    {
                        "uid": "1",
                        "subject": "for other",
                        "from": "service@example.com",
                        "to": "other@openaibus.com",
                        "date": "Thu, 21 Aug 2026 10:00:00 +0800",
                        "message_id": "<1@example.com>",
                        "code": "111111",
                        "body": "other",
                    },
                    {
                        "uid": "2",
                        "subject": "for me",
                        "from": "service@example.com",
                        "to": "abc@openaibus.com",
                        "date": "Thu, 21 Aug 2026 10:01:00 +0800",
                        "message_id": "<2@example.com>",
                        "code": "222222",
                        "body": "mine",
                    },
                ],
            }
        )

    monkeypatch.setattr("autotoken.mail.mailu.curl_requests.get", fake_get)

    client = MailuMailProvider()
    messages = client.list_emails("abc@openaibus.com", size=10)

    assert len(messages) == 1
    assert messages[0]["id"] == "2"
    assert client.extract_verification_code(messages[0]) == "222222"


def test_delete_account_releases_reservation(monkeypatch):
    monkeypatch.setenv("MAILU_BASE_URL", "https://mail.example.com/mail-api/")
    monkeypatch.setenv("MAILU_API_KEY", "secret")
    monkeypatch.setenv("MAILU_DOMAIN", "openaibus.com")

    client = MailuMailProvider()
    account_id, email = client.create_temp_email(prefix="abc")

    result = client.delete_account(account_id)

    assert result["code"] == 0
    assert email not in client._reserved_emails


def test_factory_and_setup_schema_accept_mailu(monkeypatch):
    monkeypatch.setenv("MAIL_PROVIDER", "mailu")

    from autotoken.mail import get_mail_client
    from autotoken.settings.setup_wizard import get_mail_provider, get_setup_schema

    assert isinstance(get_mail_client(), MailuMailProvider)
    assert get_mail_provider("self-mailu") == "mailu"

    schema = get_setup_schema({"MAIL_PROVIDER": "mailu"})
    assert any(
        option["value"] == "mailu" and option["label"] == "Mailu (自建)" for option in schema["provider_options"]
    )
    assert schema["provider_fields"]["mailu"] == [
        {
            "key": "MAILU_BASE_URL",
            "prompt": "Mailu mail-api 根地址（如 https://mail.example.com/mail-api/）",
            "default": "",
            "optional": False,
        },
        {
            "key": "MAILU_API_KEY",
            "prompt": "Mailu mail-api API Key",
            "default": "",
            "optional": False,
        },
        {
            "key": "MAILU_DOMAIN",
            "prompt": "Mailu 邮箱域名（如 example.com，注册任务指定域名时可不填）",
            "default": "",
            "optional": True,
        },
    ]
