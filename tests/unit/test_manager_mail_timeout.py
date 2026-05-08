from autoteam.manager import MAIL_TIMEOUT, _direct_register_code_timeout


class FakeMailClient:
    def __init__(self, provider_name, email_type=""):
        self.provider_name = provider_name
        self.email_type = email_type


def test_outlook_register_code_timeout_defaults_to_90_seconds():
    assert _direct_register_code_timeout(FakeMailClient("outlook"), "user@outlook.com") == 90


def test_luckmail_microsoft_register_code_timeout_defaults_to_90_seconds():
    assert _direct_register_code_timeout(FakeMailClient("luckmail", "ms_graph"), "user@outlook.my") == 90


def test_non_microsoft_mail_uses_regular_mail_timeout():
    assert _direct_register_code_timeout(FakeMailClient("cloudflare_temp_email"), "user@example.com") == MAIL_TIMEOUT
