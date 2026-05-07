from autoteam.whatsapp_otp import WhatsAppOtpListener, _extract_otp_from_text


def test_extract_whatsapp_gopay_otp():
    text = "(GOJEK) Ini OTP buat hubungkan OpenAI LLC ke GoPay. OTP: 511937 gojek.com/safety"

    assert _extract_otp_from_text(text) == "511937"
    assert _extract_otp_from_text("hello 511937") == ""


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


def test_whatsapp_listener_reports_login_required(tmp_path):
    listener = WhatsAppOtpListener(profile_dir=tmp_path)
    listener._running = True
    listener._thread = type("Thread", (), {"is_alive": lambda self: True})()
    listener._login_required = True

    response = listener.latest_response()

    assert response["code"] == 0
    assert response["msg"] == "WhatsApp Web needs login"
