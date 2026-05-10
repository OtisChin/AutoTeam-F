import autoteam.whatsapp_otp as whatsapp_otp_module
from autoteam.whatsapp_otp import WhatsAppOtpListener, _extract_otp_from_text


def _clear_global_whatsapp_cache():
    with whatsapp_otp_module._GLOBAL_LOCK:
        whatsapp_otp_module._GLOBAL_LATEST = None
        whatsapp_otp_module._GLOBAL_RECENT.clear()
        whatsapp_otp_module._GLOBAL_SEEN_KEYS.clear()
        whatsapp_otp_module._GLOBAL_SEEN_CODES.clear()


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
    _clear_global_whatsapp_cache()
    listener = WhatsAppOtpListener(profile_dir=tmp_path)

    response = listener.latest_response()

    assert response["code"] == 0
    assert response["msg"] == "WhatsApp Android listener is not running"


def test_whatsapp_listener_latest_response_uses_global_otp_from_replaced_listener(tmp_path):
    _clear_global_whatsapp_cache()
    old_listener = WhatsAppOtpListener(profile_dir=tmp_path / "old")
    old_listener._running = True
    old_listener._thread = type("Thread", (), {"is_alive": lambda self: True})()
    old_listener._record_message(code="884854", raw="GoPay 884854 is your verification code.")

    new_listener = WhatsAppOtpListener(profile_dir=tmp_path / "new")
    response = new_listener.latest_response(max_age_seconds=600)

    assert response["code"] == 1
    assert response["data"]["otp"] == "884854"


def test_whatsapp_listener_latest_response_prefers_newer_global_otp(tmp_path):
    _clear_global_whatsapp_cache()
    current_listener = WhatsAppOtpListener(profile_dir=tmp_path / "current")
    current_listener._running = True
    current_listener._thread = type("Thread", (), {"is_alive": lambda self: True})()
    current_listener._record_message(code="751104", raw="GoPay 751104 is your verification code.")

    replacement_listener = WhatsAppOtpListener(profile_dir=tmp_path / "replacement")
    replacement_listener._running = True
    replacement_listener._thread = type("Thread", (), {"is_alive": lambda self: True})()
    replacement_listener._record_message(code="493828", raw="GoPay 493828 is your verification code.")

    response = current_listener.latest_response(max_age_seconds=600)

    assert response["code"] == 1
    assert response["data"]["otp"] == "493828"


def test_whatsapp_listener_does_not_let_ui_history_override_notification(monkeypatch, tmp_path):
    _clear_global_whatsapp_cache()
    listener = WhatsAppOtpListener(profile_dir=tmp_path)

    def fake_run_adb(args, **_kwargs):
        if "dumpsys" in args:
            return """
              NotificationRecord(pkg=com.whatsapp user=UserHandle{0})
                android.title=String (GoPay)
                android.text=SpannableString (720262 is your verification code. For your security, do not share this code.)
            """
        return """
          <?xml version="1.0" encoding="UTF-8"?>
          <node text="GoPay 720262 is your verification code."/>
          <node text="GoPay 738846 is your verification code."/>
        """

    monkeypatch.setattr(listener, "_run_adb", fake_run_adb)

    messages = listener._scrape_device()

    assert any("720262" in message for message in messages)
    assert not any("738846" in message for message in messages)


def test_whatsapp_listener_does_not_refresh_latest_with_same_old_code(tmp_path):
    _clear_global_whatsapp_cache()
    listener = WhatsAppOtpListener(profile_dir=tmp_path)
    listener._running = True
    listener._thread = type("Thread", (), {"is_alive": lambda self: True})()
    listener._record_message(code="738846", raw="GoPay 738846 is your verification code.")
    first = listener.latest_response(max_age_seconds=600)["data"]["received_at"]

    listener._record_message(code="738846", raw="GoPay 738846 is your verification code. Expires in 5 minutes.")

    response = listener.latest_response(max_age_seconds=600)
    assert response["data"]["otp"] == "738846"
    assert response["data"]["received_at"] == first


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


def test_whatsapp_listener_keeps_otp_candidates_when_many_noisy_notifications(monkeypatch, tmp_path):
    otp_blob = """
      NotificationRecord(pkg=com.whatsapp user=UserHandle{0})
        android.title=String (GoPay)
        android.text=SpannableString (273576 is your verification code. For your security, do not share this code.)
    """
    noisy_blob = "\n".join(
        f"NotificationRecord(pkg=com.gojek.gopay user=UserHandle{{0}}) android.text=String (Rp1.000 from user {index} has been received in your GoPay.)"
        for index in range(80)
    )
    listener = WhatsAppOtpListener(profile_dir=tmp_path)
    monkeypatch.setattr(
        listener,
        "_run_adb",
        lambda args, **_kwargs: otp_blob + "\n" + noisy_blob if "dumpsys" in args else "",
    )

    messages = listener._scrape_device()

    assert any(_extract_otp_from_text(message) == "273576" for message in messages)


def test_extract_whatsapp_otp_ignores_notification_metadata_numbers():
    text = (
        "Group summaries: 0|com.gojek.gopay|2147483647|ranker_group|10055 "
        "Usage Stats: key='com.whatsapp', numEnqueuedByApp=8"
    )

    assert _extract_otp_from_text(text) == ""


def test_extract_whatsapp_otp_requires_six_digits():
    text = "GoPay 1234 is your verification code. For your security, do not share this code."

    assert _extract_otp_from_text(text) == ""
