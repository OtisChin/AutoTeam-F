from autoteam.whatsapp_otp import WhatsAppOtpListener, _extract_otp_from_text


def test_extract_whatsapp_gopay_otp():
    text = "(GOJEK) Ini OTP buat hubungkan OpenAI LLC ke GoPay. OTP: 511937 gojek.com/safety"

    assert _extract_otp_from_text(text) == "511937"
    assert _extract_otp_from_text("hello 511937") == ""


def test_extract_whatsapp_gopay_otp_when_code_precedes_label():
    text = "GoPay 001294 is your verification code. For your security, do not share this code."

    assert _extract_otp_from_text(text) == "001294"


def test_whatsapp_listener_latest_response_returns_recent_messages(tmp_path):
    listener = WhatsAppOtpListener(profile_dir=tmp_path)
    listener._running = True
    listener._thread = type("Thread", (), {"is_alive": lambda self: True})()

    listener._record_message(code="111111", raw="GOJEK OTP: 111111")
    listener._record_message(code="222222", raw="GOJEK OTP: 222222")

    response = listener.latest_response(max_age_seconds=600)

    assert response["code"] == 1
    assert response["data"]["otp"] == "222222"
    assert response["data"]["code"] == "GOJEK OTP: 222222"
    assert [item["code"] for item in response["data"]["messages"]] == ["111111", "222222"]


def test_whatsapp_listener_latest_response_when_not_running(tmp_path):
    listener = WhatsAppOtpListener(profile_dir=tmp_path)

    response = listener.latest_response()

    assert response["code"] == 0
    assert response["msg"] == "WhatsApp Android listener is not running"


def test_whatsapp_listener_start_returns_resolved_adb_status(monkeypatch, tmp_path):
    listener = WhatsAppOtpListener(profile_dir=tmp_path, poll_interval_seconds=0.5)
    monkeypatch.setattr(listener, "_resolve_device", lambda: "emulator-5554")
    monkeypatch.setattr(listener, "_scrape_device", lambda: [])

    status = listener.start()

    try:
        assert status["running"] is True
        assert status["adb_serial"] == "emulator-5554"
        assert status["adb_path"] == "adb"
    finally:
        listener.stop()


def test_whatsapp_listener_extracts_candidates_from_adb_blob():
    blob = """
      NotificationRecord(pkg=com.whatsapp user=UserHandle{0})
        android.title=GOJEK
        android.text=(GOJEK) Ini OTP buat hubungkan OpenAI LLC ke GoPay. OTP: 511937 gojek.com/safety
    """

    candidates = WhatsAppOtpListener._extract_candidates_from_blob(blob)

    assert candidates
    assert _extract_otp_from_text(candidates[-1]) == "511937"


def test_extract_whatsapp_otp_ignores_notification_metadata_numbers():
    text = (
        "Group summaries: 0|com.gojek.gopay|2147483647|ranker_group|10055 "
        "Usage Stats: key='com.whatsapp', numEnqueuedByApp=8"
    )

    assert _extract_otp_from_text(text) == ""
