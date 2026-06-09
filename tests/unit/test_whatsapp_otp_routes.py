from pathlib import Path

from fastapi import FastAPI, HTTPException

import autotoken.whatsapp_otp as whatsapp_otp_module
from autotoken.api_routes.whatsapp_otp import WhatsAppOtpStartParams, create_whatsapp_otp_router


class FakeListener:
    def __init__(
        self,
        *,
        profile_dir=Path("profile"),
        headless=False,
        adb_path="adb",
        adb_serial="",
        poll_interval_seconds=2.0,
    ):
        self.profile_dir = profile_dir
        self.headless = headless
        self.adb_path = adb_path
        self.adb_serial = adb_serial
        self.poll_interval_seconds = poll_interval_seconds
        self.stopped = False

    def status(self):
        return {"running": False, "adb_serial": self.adb_serial}

    def start(self):
        return {
            "running": True,
            "profile_dir": str(self.profile_dir),
            "headless": self.headless,
            "adb_path": self.adb_path,
            "adb_serial": self.adb_serial,
            "poll_interval_seconds": self.poll_interval_seconds,
        }

    def stop(self):
        self.stopped = True
        return {"running": False}

    def clear(self):
        return {"cleared": True}

    def latest_response(self, max_age_seconds=600):
        return {"code": 1, "data": {"otp": "123456", "max_age_seconds": max_age_seconds}}


def _app():
    app = FastAPI()
    app.include_router(create_whatsapp_otp_router())
    return app


def _endpoint(app, path, method):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"missing route {method} {path}")


def test_whatsapp_otp_routes_delegate_to_current_listener(monkeypatch):
    app = _app()
    listener = FakeListener(adb_serial="emulator-5554")
    monkeypatch.setattr(whatsapp_otp_module, "get_default_listener", lambda: listener)

    assert _endpoint(app, "/api/whatsapp-otp/status", "GET")() == {"running": False, "adb_serial": "emulator-5554"}
    assert _endpoint(app, "/api/whatsapp-otp/stop", "POST")() == {"running": False}
    assert listener.stopped is True
    assert _endpoint(app, "/api/whatsapp-otp/clear", "POST")() == {"cleared": True}
    assert _endpoint(app, "/api/whatsapp-otp/latest", "GET")(max_age_seconds=10) == {
        "code": 1,
        "data": {"otp": "123456", "max_age_seconds": 10},
    }
    assert _endpoint(app, "/otp/whatsapp/latest", "GET")(max_age_seconds=20) == {
        "code": 1,
        "data": {"otp": "123456", "max_age_seconds": 20},
    }


def test_whatsapp_otp_start_reuses_matching_listener(monkeypatch, tmp_path):
    app = _app()
    listener = FakeListener(profile_dir=tmp_path, headless=True, adb_path="adbx", adb_serial="emulator-5556")
    monkeypatch.setattr(whatsapp_otp_module, "DEFAULT_PROFILE_DIR", tmp_path)
    monkeypatch.setattr(whatsapp_otp_module, "DEFAULT_ADB_PATH", "adbx")
    monkeypatch.setattr(whatsapp_otp_module, "get_default_listener", lambda: listener)

    result = _endpoint(app, "/api/whatsapp-otp/start", "POST")(
        WhatsAppOtpStartParams(profile_dir=str(tmp_path), headless=True, adb_path="", adb_serial="emulator-5556")
    )

    assert result["adb_serial"] == "emulator-5556"
    assert listener.stopped is False


def test_whatsapp_otp_start_replaces_changed_listener_and_normalizes_adb_port(monkeypatch, tmp_path):
    app = _app()
    old_listener = FakeListener(profile_dir=tmp_path / "old")
    created = []
    monkeypatch.setattr(whatsapp_otp_module, "DEFAULT_PROFILE_DIR", tmp_path / "default")
    monkeypatch.setattr(whatsapp_otp_module, "DEFAULT_ADB_PATH", "adb")
    monkeypatch.setattr(whatsapp_otp_module, "get_default_listener", lambda: old_listener)

    class NewListener(FakeListener):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            created.append(self)

    monkeypatch.setattr(whatsapp_otp_module, "WhatsAppOtpListener", NewListener)

    result = _endpoint(app, "/api/whatsapp-otp/start", "POST")(
        WhatsAppOtpStartParams(profile_dir=str(tmp_path / "new"), adb_port="tcp:5558", pollIntervalSeconds=3)
    )

    assert old_listener.stopped is True
    assert len(created) == 1
    assert whatsapp_otp_module._DEFAULT_LISTENER is created[0]
    assert result["profile_dir"] == str(tmp_path / "new")
    assert result["adb_serial"] == "emulator-5558"
    assert result["poll_interval_seconds"] == 3.0


def test_gopay_signup_otp_public_delegates_and_translates_missing_bridge(monkeypatch):
    app = _app()

    monkeypatch.setattr(
        "autotoken.gopay_auto_register.get_sms_bridge_payload",
        lambda token, resend=False: {"token": token, "resend": resend},
    )
    assert _endpoint(app, "/otp/gopay-signup/{bridge_token}", "GET")("bridge-1", resend=True) == {
        "token": "bridge-1",
        "resend": True,
    }

    def missing_bridge(token, resend=False):
        raise KeyError(token)

    monkeypatch.setattr("autotoken.gopay_auto_register.get_sms_bridge_payload", missing_bridge)
    try:
        _endpoint(app, "/otp/gopay-signup/{bridge_token}", "GET")("missing")
    except HTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "GoPay OTP bridge 不存在或已关闭"
    else:
        raise AssertionError("missing GoPay OTP bridge must return 404")
