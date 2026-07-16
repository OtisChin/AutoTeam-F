import pytest

from autotoken.services import sms_otp

class FakeResponse:
    def __init__(self, *, ok=True, status_code=200, text=""):
        self.ok = ok
        self.status_code = status_code
        self.text = text

def test_fetch_sms_code_rewrites_local_gopay_bridge_and_skips_ignored_code(monkeypatch):
    captured = {}
    monkeypatch.setenv("AUTOTOKEN_LOCAL_BASE_URL", "http://127.0.0.1:8989")

    def fake_get(url, **_kwargs):
        captured["url"] = url
        return FakeResponse(
            text='{"code":1,"data":{"messages":[{"text":"OpenAI OTP: 111111"},{"text":"OpenAI OTP: 222222"}]}}'
        )

    assert (
        sms_otp.fetch_sms_code(
            "http://127.0.0.1:8787/otp/gopay-signup/demo",
            ignored_otps={"111111"},
            http_get=fake_get,
        )
        == "222222"
    )
    assert captured["url"] == "http://127.0.0.1:8989/otp/gopay-signup/demo"

def test_poll_otp_resends_bridge_then_external_callback(monkeypatch):
    now = [0.0]
    operations = []
    progress_events = []
    monkeypatch.delenv("AUTOTOKEN_LOCAL_BASE_URL", raising=False)
    monkeypatch.setenv("GOPAY_SMS_PROVIDER_RESEND_DELAY_SECONDS", "0")

    def fake_fetch(_url, **_kwargs):
        return "123456" if now[0] >= 65 else ""

    provider = sms_otp.poll_otp_from_sms_url(
        "http://127.0.0.1:8787/otp/gopay-signup/demo?foo=bar",
        timeout_seconds=180,
        initial_delay_seconds=0,
        resend_after_seconds=60,
        fetch_sms_code_fn=fake_fetch,
        bridge_resend_url_fn=sms_otp.gopay_signup_bridge_resend_url,
        trigger_bridge_resend_fn=lambda url: (
            operations.append(("bridge", now[0], sms_otp.gopay_signup_bridge_resend_url(url))) or True
        ),
        sleep_fn=lambda seconds: now.__setitem__(0, now[0] + seconds),
        time_fn=lambda: now[0],
        progress=lambda stage, **extra: progress_events.append({"stage": stage, **extra}),
    )
    provider._gopay_resend_callback = lambda: operations.append(("external", now[0], ""))

    assert provider() == "123456"
    assert operations == [
        ("bridge", 60.0, "http://127.0.0.1:8787/otp/gopay-signup/demo?foo=bar&resend=1"),
        ("external", 60.0, ""),
    ]
    assert {"stage": "sms_provider_resend_triggered"} in progress_events

def test_poll_otp_uses_custom_cancelled_error_factory():
    class CustomCancelled(Exception):
        pass

    now = [0.0]
    provider = sms_otp.poll_otp_from_sms_url(
        "https://sms.example.test",
        timeout_seconds=600,
        initial_delay_seconds=0,
        resend_after_seconds=60,
        max_resend_attempts=0,
        fetch_sms_code_fn=lambda *_args, **_kwargs: "",
        sleep_fn=lambda seconds: now.__setitem__(0, now[0] + seconds),
        time_fn=lambda: now[0],
        cancelled_error_factory=CustomCancelled,
    )
    provider._gopay_resend_callback = lambda: None

    with pytest.raises(CustomCancelled, match="上限 0 次"):
        provider()
