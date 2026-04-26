"""测试 cloudflare_temp_email provider。

注:历史 cloud-mail API(`/account/list` `/email/list` `/email/latest`)在 cloudmail.py
切到 dreamhunter2333/cloudflare_temp_email 时已经不再适用,这些用例改为针对当前
`/admin/*` 路由的实现。OTP 提取测试与后端无关,沿用原断言。
"""

from autoteam import accounts
from autoteam.mail import cloudflare_temp_email


def test_search_emails_by_recipient_returns_normalized_records(monkeypatch):
    client = cloudflare_temp_email.CloudflareTempEmailClient()
    target = "tmp-user@example.com"

    monkeypatch.setattr(accounts, "load_accounts", lambda: [])

    class _Resp:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    raw_mime = (
        "From: noreply@tm.openai.com\r\n"
        f"To: {target}\r\n"
        "Subject: Your ChatGPT code is 189799\r\n"
        "Message-ID: <abc@x>\r\n"
        "\r\n"
        "Your ChatGPT code is 189799\r\n"
    )

    def fake_get(path, params=None):
        assert path == "/admin/mails"
        assert (params or {}).get("address") == target
        return _Resp(
            {
                "results": [
                    {
                        "id": 15,
                        "address": target,
                        "raw": raw_mime,
                        "source": "noreply@tm.openai.com",
                        "created_at": 1761331200,
                    }
                ]
            }
        )

    monkeypatch.setattr(client, "_admin_get", fake_get)

    emails = client.search_emails_by_recipient(target, size=5)

    assert len(emails) == 1
    assert emails[0]["emailId"] == 15
    assert emails[0]["subject"] == "Your ChatGPT code is 189799"
    assert emails[0]["sendEmail"] == "noreply@tm.openai.com"
    assert emails[0]["accountEmail"] == target
    assert emails[0]["createTime"] == 1761331200


def test_search_emails_by_recipient_filters_unrelated_address(monkeypatch):
    client = cloudflare_temp_email.CloudflareTempEmailClient()
    target = "tmp-user@example.com"

    monkeypatch.setattr(accounts, "load_accounts", lambda: [])

    class _Resp:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(path, params=None):
        return _Resp(
            {
                "results": [
                    {
                        "id": 410,
                        "address": "someone-else@example.com",
                        "raw": "Subject: Other\r\n\r\nbody",
                    }
                ]
            }
        )

    monkeypatch.setattr(client, "_admin_get", fake_get)

    emails = client.search_emails_by_recipient(target, size=5)

    assert emails == []


def test_resolve_address_id_accepts_int_and_email(monkeypatch):
    client = cloudflare_temp_email.CloudflareTempEmailClient()

    assert client._resolve_address_id(43) == 43
    assert client._resolve_address_id("43") == 43

    class _Resp:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(path, params=None):
        assert path == "/admin/address"
        return _Resp({"results": [{"id": 99, "name": "user@example.com"}]})

    monkeypatch.setattr(client, "_admin_get", fake_get)

    assert client._resolve_address_id("user@example.com") == 99


def test_extract_verification_code_prefers_visible_text_over_html_color_values():
    client = cloudflare_temp_email.CloudflareTempEmailClient()

    email_data = {
        "text": None,
        "content": """
        <html>
          <head>
            <title>Your ChatGPT code is 676952</title>
            <style>
              .top { color: #202123; }
              .body { color: #353740; }
            </style>
          </head>
          <body>
            <p>Your ChatGPT code is 676952</p>
          </body>
        </html>
        """,
    }

    assert client.extract_verification_code(email_data) == "676952"


def test_extract_verification_code_uses_plain_text_when_available():
    client = cloudflare_temp_email.CloudflareTempEmailClient()

    email_data = {
        "text": "Your temporary OpenAI login code is 123456",
        "content": "<html><style>.top{color:#202123}</style><body>ignored</body></html>",
    }

    assert client.extract_verification_code(email_data) == "123456"


def test_factory_returns_cloudflare_temp_email_by_default(monkeypatch):
    """兼容入口仍能返回默认 provider。"""
    monkeypatch.delenv("MAIL_PROVIDER", raising=False)
    from autoteam.cloudmail import CloudMailClient

    client = CloudMailClient()
    assert isinstance(client, cloudflare_temp_email.CloudflareTempEmailClient)


def test_factory_dispatches_to_cloud_mail_when_configured(monkeypatch):
    monkeypatch.setenv("MAIL_PROVIDER", "cloud-mail")
    monkeypatch.setenv("CLOUD_MAIL_API_URL", "http://example.com")
    from autoteam.cloudmail import CloudMailClient
    from autoteam.mail.cloud_mail import CloudMailProviderClient

    client = CloudMailClient()
    assert isinstance(client, CloudMailProviderClient)


def test_factory_rejects_unknown_provider(monkeypatch):
    import pytest

    monkeypatch.setenv("MAIL_PROVIDER", "made-up")
    from autoteam.mail import get_mail_client

    with pytest.raises(ValueError, match="未知 MAIL_PROVIDER"):
        get_mail_client()
