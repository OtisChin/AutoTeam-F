"""WhatsApp OTP and local OTP bridge HTTP routes."""

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import AliasChoices, BaseModel, Field


class WhatsAppOtpStartParams(BaseModel):
    profile_dir: str = Field("", validation_alias=AliasChoices("profile_dir", "profileDir"))
    headless: bool = False
    adb_path: str = Field("", validation_alias=AliasChoices("adb_path", "adbPath"))
    adb_serial: str = Field("", validation_alias=AliasChoices("adb_serial", "adbSerial"))
    adb_port: str = Field("", validation_alias=AliasChoices("adb_port", "adbPort"))
    poll_interval_seconds: float = Field(
        2.0, validation_alias=AliasChoices("poll_interval_seconds", "pollIntervalSeconds")
    )


def create_whatsapp_otp_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/whatsapp-otp/status")
    def get_whatsapp_otp_status():
        from autotoken.payments.whatsapp_otp import get_default_listener

        return get_default_listener().status()

    @router.post("/api/whatsapp-otp/start")
    def post_whatsapp_otp_start(params: WhatsAppOtpStartParams | None = None):
        import autotoken.payments.whatsapp_otp as whatsapp_otp_module
        from autotoken.payments.whatsapp_otp import (
            DEFAULT_ADB_PATH,
            DEFAULT_PROFILE_DIR,
            WhatsAppOtpListener,
            get_default_listener,
        )

        params = params or WhatsAppOtpStartParams()
        profile_dir = (
            Path(params.profile_dir).expanduser() if str(params.profile_dir or "").strip() else DEFAULT_PROFILE_DIR
        )
        adb_path = str(params.adb_path or "").strip()
        adb_serial = str(params.adb_serial or "").strip()
        adb_port = re.sub(r"\D+", "", str(params.adb_port or ""))
        if not adb_serial and adb_port:
            adb_serial = f"emulator-{adb_port}"
        requested_adb_path = adb_path or DEFAULT_ADB_PATH
        poll_interval_seconds = float(params.poll_interval_seconds or 2.0)
        listener = get_default_listener()
        if (
            str(listener.profile_dir) != str(profile_dir)
            or listener.headless != bool(params.headless)
            or getattr(listener, "adb_path", "") != requested_adb_path
            or getattr(listener, "adb_serial", "") != adb_serial
            or float(getattr(listener, "poll_interval_seconds", 2.0)) != poll_interval_seconds
        ):
            listener.stop()
            listener = WhatsAppOtpListener(
                profile_dir=profile_dir,
                headless=bool(params.headless),
                adb_path=requested_adb_path,
                adb_serial=adb_serial,
                poll_interval_seconds=poll_interval_seconds,
            )
            whatsapp_otp_module._DEFAULT_LISTENER = listener
        return listener.start()

    @router.post("/api/whatsapp-otp/stop")
    def post_whatsapp_otp_stop():
        from autotoken.payments.whatsapp_otp import get_default_listener

        return get_default_listener().stop()

    @router.post("/api/whatsapp-otp/clear")
    def post_whatsapp_otp_clear():
        from autotoken.payments.whatsapp_otp import get_default_listener

        return get_default_listener().clear()

    @router.get("/api/whatsapp-otp/latest")
    def get_whatsapp_otp_latest(max_age_seconds: int = 600):
        from autotoken.payments.whatsapp_otp import get_default_listener

        return get_default_listener().latest_response(max_age_seconds=max_age_seconds)

    @router.get("/otp/whatsapp/latest")
    def get_whatsapp_otp_latest_public(max_age_seconds: int = 600):
        """Local, auth-free OTP endpoint compatible with existing GoPay sms_url polling."""
        from autotoken.payments.whatsapp_otp import get_default_listener

        return get_default_listener().latest_response(max_age_seconds=max_age_seconds)

    @router.get("/otp/gopay-signup/{bridge_token}")
    def get_gopay_signup_otp_public(bridge_token: str, resend: bool = False):
        """Local, auth-free OTP endpoint for auto-registered GoPay wallets."""
        from autotoken.payments.gopay_auto_register import get_sms_bridge_payload

        try:
            return get_sms_bridge_payload(bridge_token, resend=resend)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="GoPay OTP bridge 不存在或已关闭") from exc

    return router
