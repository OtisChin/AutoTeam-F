from autotoken.services.chatgpt_2fa_setup import (
    ChatGPT2FASetupExecutor,
    ChatGPT2FASetupStatus,
)


class FakeLocator:
    def __init__(self, page, key, count=1, attr=None, checked=False):
        self.page = page
        self.key = key
        self._count = count
        self._attr = attr
        self._checked = checked
        self.fills = []
        self.clicks = 0

    def count(self):
        return self._count

    def first(self):
        return self

    def get_attribute(self, name):
        assert name == "href"
        return self._attr

    def click(self, **_kwargs):
        self.clicks += 1
        self.page.clicked.append(self.key)

    def fill(self, value):
        self.fills.append(value)
        self.page.filled.append((self.key, value))

    def is_checked(self):
        return self._checked


class FakePage:
    url = "https://chatgpt.com/"

    def __init__(self, *, otpauth="", authenticator_count=1, checked_after=True):
        self.goto_urls = []
        self.clicked = []
        self.filled = []
        self.waits = []
        self.otpauth = otpauth
        self.authenticator_count = authenticator_count
        self.checked_after = checked_after

    def goto(self, url, **_kwargs):
        self.goto_urls.append(url)
        self.url = url

    def wait_for_load_state(self, *args, **kwargs):
        self.waits.append((args, kwargs))

    def wait_for_timeout(self, _ms):
        pass

    def locator(self, selector):
        if selector == 'a[href^="otpauth://totp/"]':
            return FakeLocator(self, selector, count=1 if self.otpauth else 0, attr=self.otpauth)
        if "Authenticator app" in selector or "身份验证器应用" in selector:
            return FakeLocator(self, selector, count=self.authenticator_count, checked=self.checked_after)
        return FakeLocator(self, selector, count=0)

    def get_by_role(self, role, name=None):
        if name and ("Authenticator app" in str(name) or "身份验证器应用" in str(name)):
            return FakeLocator(
                self,
                f"role={role}:{name}",
                count=self.authenticator_count,
                checked=self.checked_after,
            )
        return FakeLocator(self, f"role={role}:{name}")

    def get_by_placeholder(self, placeholder):
        return FakeLocator(self, f"placeholder={placeholder}")

    def get_by_label(self, label):
        return FakeLocator(self, f"label={label}")

    def get_by_text(self, text):
        if "Authenticator app" in str(text) or "身份验证器应用" in str(text):
            return FakeLocator(self, f"text={text}", count=self.authenticator_count, checked=self.checked_after)
        return FakeLocator(self, f"text={text}")

RFC6238_BASE32 = "GEZDGNBVGY3TQOJQ" + "GEZDGNBVGY3TQOJQ"
OPENAI_URI = "otpauth://totp/OpenAI:user%40example.com?secret=" + RFC6238_BASE32 + "&issuer=OpenAI"


def test_executor_enables_totp_from_official_otpauth_link_and_persists_metadata():
    page = FakePage(otpauth=OPENAI_URI)
    saved = []
    progress = []

    result = ChatGPT2FASetupExecutor(page, save_metadata=lambda **kwargs: saved.append(kwargs)).enable(
        "user@example.com",
        progress=progress.append,
        for_time=59,
    )

    assert result.status == ChatGPT2FASetupStatus.ENABLED
    assert result.masked_secret == "GEZD…QOJQ"
    assert page.goto_urls == ["https://chatgpt.com/#settings/Security"]
    assert page.filled
    assert page.filled[0][1] == "287082"
    assert saved[0]["email"] == "user@example.com"
    assert saved[0]["secret"] == ("GEZDGNBVGY3TQOJQ" + "GEZDGNBVGY3TQOJQ")
    assert saved[0]["issuer"] == "OpenAI"
    assert not any("GEZDGNBV" in str(item) or "287082" in str(item) for item in progress)


def test_executor_reports_unsupported_when_authenticator_option_missing():
    result = ChatGPT2FASetupExecutor(FakePage(authenticator_count=0)).enable("user@example.com")

    assert result.status == ChatGPT2FASetupStatus.UNSUPPORTED
    assert "Authenticator app" in result.reason


def test_executor_reports_secret_unavailable_without_otpauth_link():
    result = ChatGPT2FASetupExecutor(FakePage(otpauth="", checked_after=False)).enable("user@example.com")

    assert result.status == ChatGPT2FASetupStatus.SECRET_UNAVAILABLE
    assert result.masked_secret == ""


def test_executor_records_recovery_required_when_enabled_but_secret_missing_after_click():
    recovery = []

    result = ChatGPT2FASetupExecutor(
        FakePage(otpauth="", checked_after=True),
        mark_recovery_required=lambda email: recovery.append(email),
    ).enable("user@example.com")

    assert result.status == ChatGPT2FASetupStatus.RECOVERY_REQUIRED
    assert recovery == ["user@example.com"]


def test_executor_records_recovery_required_when_already_enabled_without_secret():
    recovery = []

    result = ChatGPT2FASetupExecutor(
        FakePage(otpauth="", checked_after=True),
        mark_recovery_required=lambda email: recovery.append(email),
    ).enable("user@example.com", assume_already_enabled=True)

    assert result.status == ChatGPT2FASetupStatus.RECOVERY_REQUIRED
    assert recovery == ["user@example.com"]


