from autoteam import bind_executor, config, gopay_executor
from autoteam.gopay_executor import (
    GoPayFlowError,
    GoPayHttpCharger,
    GoPayPINRejected,
    _build_result,
    _browser_checkout_nonzero_amount_hint,
    _chatgpt_checkout_payload,
    _gopay_progress_message,
    _extract_checkout_error,
    _extract_checkout_session_id,
    _extract_sms_code,
    _fetch_random_billing_address,
    _generate_id_checkout_http,
    _poll_otp_from_sms_url,
    _looks_like_phone_number,
    _safe_error_summary,
    _safe_proxy_summary,
    _safe_url_summary,
    _resolve_page_billing_locator,
    _submit_checkout_with_retries,
    _value_matches,
    _split_address_lines,
    _split_gopay_phone,
)


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._json_data


class FakeHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.headers = {}

    def post(self, url, **kwargs):
        return self._call("POST", url, **kwargs)

    def get(self, url, **kwargs):
        return self._call("GET", url, **kwargs)

    def _call(self, method, url, **kwargs):
        self.requests.append({"method": method, "url": url, "kwargs": kwargs})
        if not self.responses:
            raise AssertionError(f"unexpected HTTP call: {method} {url}")
        expected_method, expected_url_part, response = self.responses.pop(0)
        assert method == expected_method
        assert expected_url_part in url
        if isinstance(response, BaseException):
            raise response
        return response


def test_get_playwright_launch_options_prefers_task_override(monkeypatch):
    monkeypatch.setattr(config, "PLAYWRIGHT_PROXY_URL", "socks5://global.example:1080")
    monkeypatch.setattr(config, "PLAYWRIGHT_PROXY_SERVER", "")
    monkeypatch.setattr(config, "PLAYWRIGHT_PROXY_USERNAME", "")
    monkeypatch.setattr(config, "PLAYWRIGHT_PROXY_PASSWORD", "")
    monkeypatch.setattr(config, "PLAYWRIGHT_PROXY_BYPASS", "localhost,127.0.0.1")

    options = config.get_playwright_launch_options(
        proxy_url="http://user:pass@proxy.example:9999",
        proxy_bypass="localhost",
    )

    assert options["proxy"] == {
        "server": "http://proxy.example:9999",
        "username": "user",
        "password": "pass",
        "bypass": "localhost",
    }


def test_get_playwright_launch_options_normalizes_colon_proxy_with_spaces():
    raw = "us.1024proxy.io:3000:user-region-US-st-Delaware-city-Dewey Beach-sid-abc:secret"

    options = config.get_playwright_launch_options(proxy_url=raw)

    assert options["proxy"] == {
        "server": "http://us.1024proxy.io:3000",
        "username": "user-region-US-st-Delaware-city-Dewey Beach-sid-abc",
        "password": "secret",
    }
    assert config.normalize_proxy_url(raw) == (
        "http://user-region-US-st-Delaware-city-Dewey%20Beach-sid-abc:secret@us.1024proxy.io:3000"
    )


def test_get_playwright_launch_options_normalizes_schemed_colon_proxy_with_spaces():
    raw = "socks5://us.1024proxy.io:3000:user-region-US-st-Delaware-city-Dewey Beach-sid-abc:secret"

    options = config.get_playwright_launch_options(proxy_url=raw)

    assert options["proxy"] == {
        "server": "socks5://us.1024proxy.io:3000",
        "username": "user-region-US-st-Delaware-city-Dewey Beach-sid-abc",
        "password": "secret",
    }
    assert config.normalize_proxy_url(raw) == (
        "socks5://user-region-US-st-Delaware-city-Dewey%20Beach-sid-abc:secret@us.1024proxy.io:3000"
    )


def test_get_playwright_launch_options_preserves_socks5_scheme():
    options = config.get_playwright_launch_options(
        proxy_url="socks5://user name:pass@socks.example:1080",
    )

    assert options["proxy"] == {
        "server": "socks5://socks.example:1080",
        "username": "user name",
        "password": "pass",
    }


def test_get_playwright_launch_options_background_keeps_headful_offscreen(monkeypatch):
    monkeypatch.setattr(config, "PLAYWRIGHT_BACKGROUND", True)

    options = config.get_playwright_launch_options()

    assert options["headless"] is False
    assert "--window-position=-32000,-32000" in options["args"]
    assert "--start-minimized" in options["args"]


def test_get_playwright_launch_options_background_skips_headless(monkeypatch):
    monkeypatch.setattr(config, "PLAYWRIGHT_BACKGROUND", True)

    options = config.get_playwright_launch_options(headless=True)

    assert options["headless"] is True
    assert "--window-position=-32000,-32000" not in options["args"]


def test_chatgpt_http_session_requires_curl_cffi(monkeypatch):
    monkeypatch.setattr(gopay_executor, "_CurlCffiSession", None)

    try:
        gopay_executor._build_chatgpt_http_session(access_token="access")
    except GoPayFlowError as exc:
        assert exc.stage == "chatgpt_http_session"
        assert "curl-cffi" in str(exc)
    else:
        raise AssertionError("expected missing curl_cffi to fail for ChatGPT checkout HTTP session")


def test_approve_checkout_http_uses_reference_style_session_headers():
    http = FakeHttp(
        [
            ("POST", "/backend-api/sentinel/ping", FakeResponse(json_data={})),
            ("POST", "/backend-api/payments/checkout/approve", FakeResponse(json_data={"result": "approved"})),
        ]
    )

    result = gopay_executor._approve_checkout_http(
        http,
        access_token="access",
        checkout_session_id="cs_test",
        processor_entity="openai_llc",
        cookie_header="__Secure-next-auth.session-token=session",
        account_id="account",
        device_id="device",
        openai_sentinel_token="sentinel",
    )

    assert result == {"result": "approved"}
    assert http.requests[0]["url"].endswith("/backend-api/sentinel/ping")
    approve_request = http.requests[1]
    assert "headers" not in approve_request["kwargs"]
    assert http.headers["Authorization"] == "Bearer access"
    assert http.headers["Cookie"] == "__Secure-next-auth.session-token=session; oai-did=device"
    assert http.headers["oai-device-id"] == "device"
    assert http.headers["openai-sentinel-token"] == "sentinel"


def test_gopay_log_summaries_redact_sensitive_values():
    proxy = "us.1024proxy.io:3000:user-region-US-st-Delaware-city-Dewey Beach-sid-abc:secret"
    proxy_summary = _safe_proxy_summary(proxy)

    assert "us.1024proxy.io" in proxy_summary
    assert "password_present=True" in proxy_summary
    assert "secret" not in proxy_summary
    assert "Dewey Beach" not in proxy_summary

    checkout_summary = _safe_url_summary("https://chatgpt.com/checkout/openai_llc/cs_live_abcdefghijklmnopqrstuvwxyz")
    assert "chatgpt.com" in checkout_summary
    assert "cs_live_abcdefghijklmnopqrstuvwxyz" not in checkout_summary

    sms_summary = _safe_url_summary("https://it.tgflare.com/api/record?token=demo-secret&phone=6287761973970")
    assert "demo-secret" not in sms_summary
    assert "6287761973970" not in sms_summary

    error_summary = _safe_error_summary(
        "ProxyError http://user:secret@proxy.example:3000/path?token=demo-secret Authorization Bearer abc.def"
    )
    assert "user:secret" not in error_summary
    assert "demo-secret" not in error_summary
    assert "abc.def" not in error_summary


def test_normalize_expiry_and_classify_checkout_state():
    assert bind_executor.normalize_expiry("2030/5") == "05/30"
    assert bind_executor.normalize_expiry("05/2030") == "05/30"

    success = bind_executor.classify_checkout_state(
        "https://chatgpt.com/pay/success",
        "Thanks for subscribing",
    )
    failed = bind_executor.classify_checkout_state(
        "https://chatgpt.com/pay/error",
        "Your card was declined",
    )
    review = bind_executor.classify_checkout_state(
        "https://chatgpt.com/pay/review",
        "Authentication required",
    )

    assert success == {
        "status": "success",
        "failure_stage": "",
        "message": "检测到支付成功页面",
    }
    assert failed == {
        "status": "failed",
        "failure_stage": "post_submit",
        "message": "检测到支付失败提示",
    }
    assert review == {
        "status": "needs_review",
        "failure_stage": "post_submit",
        "message": "检测到需要额外验证或人工确认",
    }


def test_extract_sms_code():
    assert _extract_sms_code("验证码 123456，请勿泄露") == "123456"
    assert _extract_sms_code("SMS-OK|654321") == "654321"
    assert _extract_sms_code('{"code":0,"msg":"No verification code","data":{"code":"","expired_date":"2026-07-25 00:00:00"}}') == ""
    assert _extract_sms_code('{"code":0,"data":{"code":"345678","expired_date":"2026-07-25 00:00:00"}}') == "345678"
    assert _extract_sms_code('{"code":1,"msg":"ok","data":{"code":"(GOJEK) Ini OTP buat hubungkan OpenAI LLC ke GoPay. OTP: 511937 gojek.com/safety #511937"}}') == "511937"
    assert _extract_sms_code('{"code":0,"data":{"records":[{"sms_content":"Kode OTP GoPay kamu 456789"}]}}') == "456789"
    assert _extract_sms_code('{"status":"ok","result":{"items":[{"message":"no code"},{"message":"OpenAI OTP: 567890"}]}}') == "567890"


def test_poll_otp_waits_sms_window_before_fetch(monkeypatch):
    sleeps = []
    fetches = []
    progress_events = []
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(gopay_executor, "_fetch_sms_code", lambda url: fetches.append(url) or "123456")

    provider = _poll_otp_from_sms_url(
        "https://sms.example.test",
        timeout_seconds=60,
        initial_delay_seconds=2,
        progress=lambda stage, **extra: progress_events.append({"stage": stage, **extra}),
    )

    assert provider() == "123456"
    assert sleeps == [1.0, 1.0]
    assert fetches == ["https://sms.example.test"]
    assert progress_events[0] == {"stage": "wait_sms_otp_window", "wait_seconds": 2}
    assert progress_events[1] == {"stage": "fetch_otp"}


def test_poll_otp_resends_after_two_minutes_without_code(monkeypatch):
    now = [0.0]
    resend_calls = []
    progress_events = []

    monkeypatch.setattr(gopay_executor.time, "time", lambda: now[0])
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))

    def fake_fetch(_url):
        return "123456" if now[0] >= 125 else ""

    monkeypatch.setattr(gopay_executor, "_fetch_sms_code", fake_fetch)

    provider = _poll_otp_from_sms_url(
        "https://sms.example.test",
        timeout_seconds=180,
        initial_delay_seconds=0,
        resend_after_seconds=120,
        progress=lambda stage, **extra: progress_events.append({"stage": stage, **extra}),
    )
    setattr(provider, "_gopay_resend_callback", lambda: resend_calls.append(now[0]))

    assert provider() == "123456"
    assert resend_calls == [120.0]
    assert {"stage": "sms_otp_resend_due", "wait_seconds": 120} in progress_events


def test_extract_checkout_session_id_from_response_or_url():
    assert _extract_checkout_session_id(raw={"checkout_session_id": "cs_test_123"}) == "cs_test_123"
    assert _extract_checkout_session_id("https://chatgpt.com/checkout/openai_llc/cs_live_abc") == "cs_live_abc"
    assert _extract_checkout_session_id("https://pay.openai.com/c/pay/cs_live_a1Hosted123#fid=test") == "cs_live_a1Hosted123"


def test_chatgpt_checkout_payload_supports_hosted_long_link_mode():
    assert _chatgpt_checkout_payload()["checkout_ui_mode"] == "custom"
    assert _chatgpt_checkout_payload("hosted")["checkout_ui_mode"] == "hosted"
    assert _chatgpt_checkout_payload("bad")["checkout_ui_mode"] == "custom"


def test_gopay_progress_message_includes_checkout_terms_steps():
    assert _gopay_progress_message("accept_checkout_terms", {}) == "正在勾选支付条款"
    assert _gopay_progress_message("checkout_terms_accepted", {}) == "支付条款已勾选"


def test_browser_checkout_nonzero_hint_uses_today_total(monkeypatch):
    class FakeApi:
        pass

    monkeypatch.setattr(
        gopay_executor,
        "_body_excerpt",
        lambda api, limit: "小计 IDR 349,000.00 ChatGPT Plus -IDR 349,000.00 今日应付合计 IDR 0.00",
    )
    assert _browser_checkout_nonzero_amount_hint(FakeApi()) == ""

    monkeypatch.setattr(
        gopay_executor,
        "_body_excerpt",
        lambda api, limit: "小计 IDR 349,000.00 税 IDR 10,000.00 今日应付合计 IDR 10,000.00",
    )
    assert _browser_checkout_nonzero_amount_hint(FakeApi()) == "IDR 10,000.00"


def test_split_gopay_phone_defaults_to_indonesia():
    assert _split_gopay_phone("+6287761973970") == ("62", "87761973970")
    assert _split_gopay_phone("087761973970") == ("62", "87761973970")
    assert _split_gopay_phone("+8613812345678", country_code="86") == ("86", "13812345678")


def test_gopay_http_charger_success_flow(monkeypatch):
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda *args, **kwargs: None)

    snap_token = "11111111-1111-4111-8111-111111111111"
    reference_id = "22222222-2222-4222-8222-222222222222"
    activation_link = f"https://gopay.local/link?reference={reference_id}"
    http = FakeHttp(
        [
            ("POST", "/v1/payment_pages/cs_test/init", FakeResponse(json_data={"init_checksum": "init_123"})),
            (
                "GET",
                "/v1/elements/sessions",
                FakeResponse(
                    json_data={
                        "session_id": "elements_session_real",
                        "config_id": "checkout_config_real",
                        "elements_session_config_id": "elements_config_real",
                    }
                ),
            ),
            ("POST", "/v1/payment_methods", FakeResponse(json_data={"id": "pm_test"})),
            ("POST", "/v1/payment_pages/cs_test/confirm", FakeResponse(json_data={"payment_status": "open"})),
            (
                "GET",
                "/v1/payment_pages/cs_test",
                FakeResponse(
                    json_data={
                        "setup_intent": {
                            "status": "requires_action",
                            "next_action": {
                                "type": "redirect_to_url",
                                "redirect_to_url": {"url": "https://pm-redirects.stripe.com/authorize/test"},
                            },
                        }
                    }
                ),
            ),
            (
                "GET",
                "pm-redirects.stripe.com/authorize/test",
                FakeResponse(
                    status_code=302,
                    headers={"Location": f"https://app.midtrans.com/snap/v4/redirection/{snap_token}"},
                ),
            ),
            ("GET", f"/snap/v1/transactions/{snap_token}", FakeResponse(json_data={"enabled_payments": ["gopay"]})),
            (
                "POST",
                f"/snap/v3/accounts/{snap_token}/linking",
                FakeResponse(status_code=201, json_data={"activation_link_url": activation_link}),
            ),
            ("POST", "/v1/linking/validate-reference", FakeResponse(json_data={"success": True})),
            ("POST", "/v1/linking/user-consent", FakeResponse(json_data={"success": True})),
            (
                "POST",
                "/v1/linking/validate-otp",
                FakeResponse(
                    json_data={
                        "success": True,
                        "data": {
                            "challenge": {
                                "action": {
                                    "value": {"challenge_id": "challenge_link", "client_id": "client_link"}
                                }
                            }
                        },
                    }
                ),
            ),
            ("POST", "/api/v1/users/pin/tokens/nb", FakeResponse(json_data={"token": "pin_link"})),
            ("POST", "/v1/linking/validate-pin", FakeResponse(json_data={"success": True})),
            (
                "POST",
                f"/snap/v2/transactions/{snap_token}/charge",
                FakeResponse(json_data={"gopay_verification_link_url": "https://gopay.local/pay?reference=CHARGE123"}),
            ),
            ("GET", "/v1/payment/validate", FakeResponse(json_data={"success": True})),
            (
                "POST",
                "/v1/payment/confirm",
                FakeResponse(
                    json_data={
                        "success": True,
                        "data": {
                            "challenge": {
                                "action": {
                                    "value": {"challenge_id": "challenge_pay", "client_id": "client_pay"}
                                }
                            }
                        },
                    }
                ),
            ),
            ("POST", "/api/v1/users/pin/tokens/nb", FakeResponse(json_data={"token": "pin_pay"})),
            ("POST", "/v1/payment/process", FakeResponse(json_data={"success": True, "data": {"next_action": "payment-success"}})),
        ]
    )
    progress_events = []
    approved = []
    verified = []
    sms_triggers = []

    charger = GoPayHttpCharger(
        http=http,
        phone_number="+6287761973970",
        gopay_pin="558023",
        otp_provider=lambda: "123456",
        billing_info={"name": "John Smith", "email": "john@example.com", "country": "US"},
        approve_callback=lambda session_id: approved.append(session_id) or {"result": "approved"},
        verify_callback=lambda session_id: verified.append(session_id) or {"state": "succeeded"},
        sms_otp_trigger_callback=lambda ref, link: sms_triggers.append((ref, link)),
        progress_callback=progress_events.append,
    )

    result = charger.run(checkout_session_id="cs_test", stripe_pk="pk_test")

    assert result["state"] == "succeeded"
    assert result["snap_token"] == snap_token
    assert result["reference_id"] == reference_id
    assert result["charge_ref"] == "CHARGE123"
    assert approved == []
    assert verified == ["cs_test"]
    assert sms_triggers == [(reference_id, activation_link)]
    linking_request = next(request for request in http.requests if request["url"].endswith("/linking"))
    assert linking_request["kwargs"]["json"] == {
        "type": "gopay",
        "country_code": "62",
        "phone_number": "87761973970",
    }
    assert any(event["stage"] == "gopay_payment_process" for event in progress_events)
    payment_method_request = next(request for request in http.requests if request["url"].endswith("/v1/payment_methods"))
    assert payment_method_request["kwargs"]["data"]["client_attribution_metadata[elements_session_id]"] == "elements_session_real"
    assert payment_method_request["kwargs"]["data"]["client_attribution_metadata[checkout_config_id]"] == "checkout_config_real"
    assert http.responses == []


def test_gopay_http_charger_skips_approve_when_confirm_returns_redirect(monkeypatch):
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda *args, **kwargs: None)

    snap_token = "11111111-1111-4111-8111-111111111111"
    reference_id = "22222222-2222-4222-8222-222222222222"
    activation_link = f"https://gopay.local/link?reference={reference_id}"
    http = FakeHttp(
        [
            ("POST", "/v1/payment_pages/cs_test/init", FakeResponse(json_data={"init_checksum": "init_123"})),
            (
                "GET",
                "/v1/elements/sessions",
                FakeResponse(json_data={"session_id": "elements_session_real", "config_id": "checkout_config_real"}),
            ),
            ("POST", "/v1/payment_methods", FakeResponse(json_data={"id": "pm_test"})),
            (
                "POST",
                "/v1/payment_pages/cs_test/confirm",
                FakeResponse(
                    json_data={
                        "setup_intent": {
                            "next_action": {
                                "type": "redirect_to_url",
                                "redirect_to_url": {"url": "https://pm-redirects.stripe.com/authorize/direct"},
                            }
                        }
                    }
                ),
            ),
            (
                "GET",
                "pm-redirects.stripe.com/authorize/direct",
                FakeResponse(
                    status_code=302,
                    headers={"Location": f"https://app.midtrans.com/snap/v4/redirection/{snap_token}"},
                ),
            ),
            ("GET", f"/snap/v1/transactions/{snap_token}", FakeResponse(json_data={"enabled_payments": ["gopay"]})),
            (
                "POST",
                f"/snap/v3/accounts/{snap_token}/linking",
                FakeResponse(status_code=201, json_data={"activation_link_url": activation_link}),
            ),
            ("POST", "/v1/linking/validate-reference", FakeResponse(json_data={"success": True})),
            ("POST", "/v1/linking/user-consent", FakeResponse(json_data={"success": True})),
            (
                "POST",
                "/v1/linking/validate-otp",
                FakeResponse(
                    json_data={
                        "success": True,
                        "data": {
                            "challenge": {
                                "action": {
                                    "value": {"challenge_id": "challenge_link", "client_id": "client_link"}
                                }
                            }
                        },
                    }
                ),
            ),
            ("POST", "/api/v1/users/pin/tokens/nb", FakeResponse(json_data={"token": "pin_link"})),
            ("POST", "/v1/linking/validate-pin", FakeResponse(json_data={"success": True})),
            (
                "POST",
                f"/snap/v2/transactions/{snap_token}/charge",
                FakeResponse(json_data={"gopay_verification_link_url": "https://gopay.local/pay?reference=CHARGE123"}),
            ),
            ("GET", "/v1/payment/validate", FakeResponse(json_data={"success": True})),
            (
                "POST",
                "/v1/payment/confirm",
                FakeResponse(
                    json_data={
                        "success": True,
                        "data": {
                            "challenge": {
                                "action": {
                                    "value": {"challenge_id": "challenge_pay", "client_id": "client_pay"}
                                }
                            }
                        },
                    }
                ),
            ),
            ("POST", "/api/v1/users/pin/tokens/nb", FakeResponse(json_data={"token": "pin_pay"})),
            ("POST", "/v1/payment/process", FakeResponse(json_data={"success": True, "data": {"next_action": "payment-success"}})),
        ]
    )
    approved = []
    progress_events = []

    charger = GoPayHttpCharger(
        http=http,
        phone_number="+6287761973970",
        gopay_pin="558023",
        otp_provider=lambda: "123456",
        approve_callback=lambda session_id: approved.append(session_id) or {"result": "approved"},
        verify_callback=lambda session_id: {"state": "succeeded"},
        progress_callback=progress_events.append,
    )

    result = charger.run(checkout_session_id="cs_test", stripe_pk="pk_test")

    assert result["state"] == "succeeded"
    assert result["snap_token"] == snap_token
    assert approved == []
    assert any(
        event["stage"] == "resolve_midtrans_redirect" and event.get("source") == "stripe_confirm"
        for event in progress_events
    )
    assert http.responses == []


def test_gopay_http_charger_triggers_sms_otp_via_protocol(monkeypatch):
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda *args, **kwargs: None)

    snap_token = "11111111-1111-4111-8111-111111111111"
    reference_id = "22222222-2222-4222-8222-222222222222"
    http = FakeHttp(
        [
            ("GET", f"/snap/v1/transactions/{snap_token}", FakeResponse(json_data={"enabled_payments": ["gopay"]})),
            (
                "POST",
                f"/snap/v3/accounts/{snap_token}/linking",
                FakeResponse(status_code=201, json_data={"activation_link_url": f"https://gopay.local/link?reference={reference_id}"}),
            ),
            ("POST", "/v1/linking/validate-reference", FakeResponse(json_data={"success": True})),
            ("POST", "/v1/linking/user-consent", FakeResponse(json_data={"success": True})),
            ("POST", "/v1/linking/resend-otp", FakeResponse(json_data={"success": True})),
            (
                "POST",
                "/v1/linking/validate-otp",
                FakeResponse(
                    json_data={
                        "success": True,
                        "data": {
                            "challenge": {
                                "action": {
                                    "value": {"challenge_id": "challenge_link", "client_id": "client_link"}
                                }
                            }
                        },
                    }
                ),
            ),
            ("POST", "/api/v1/users/pin/tokens/nb", FakeResponse(json_data={"token": "pin_link"})),
            ("POST", "/v1/linking/validate-pin", FakeResponse(json_data={"success": True})),
            (
                "POST",
                f"/snap/v2/transactions/{snap_token}/charge",
                FakeResponse(json_data={"gopay_verification_link_url": "https://gopay.local/pay?reference=CHARGE123"}),
            ),
            ("GET", "/v1/payment/validate", FakeResponse(json_data={"success": True})),
            (
                "POST",
                "/v1/payment/confirm",
                FakeResponse(
                    json_data={
                        "success": True,
                        "data": {
                            "challenge": {
                                "action": {
                                    "value": {"challenge_id": "challenge_pay", "client_id": "client_pay"}
                                }
                            }
                        },
                    }
                ),
            ),
            ("POST", "/api/v1/users/pin/tokens/nb", FakeResponse(json_data={"token": "pin_pay"})),
            ("POST", "/v1/payment/process", FakeResponse(json_data={"success": True, "data": {"next_action": "payment-success"}})),
        ]
    )
    progress_events = []
    otp_callback_present = []

    def otp_provider():
        otp_callback_present.append(callable(getattr(otp_provider, "_gopay_resend_callback", None)))
        return "123456"

    charger = GoPayHttpCharger(
        http=http,
        phone_number="+6287761973970",
        gopay_pin="558023",
        otp_provider=otp_provider,
        otp_channel="sms",
        sms_resend_wait_seconds=0,
        progress_callback=progress_events.append,
    )

    result = charger.run_from_snap_token(snap_token=snap_token, checkout_session_id="cs_test")

    assert result["state"] == "succeeded"
    resend_request = next(request for request in http.requests if request["url"].endswith("/resend-otp"))
    assert resend_request["kwargs"]["json"] == {"reference_id": reference_id}
    assert [event["stage"] for event in progress_events].count("trigger_sms_otp") == 1
    assert any(event["stage"] == "sms_otp_triggered" for event in progress_events)
    assert otp_callback_present == [True]
    assert http.responses == []


def test_gopay_http_charger_retries_when_linking_otp_is_invalid(monkeypatch):
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda *args, **kwargs: None)

    snap_token = "11111111-1111-4111-8111-111111111111"
    reference_id = "22222222-2222-4222-8222-222222222222"
    http = FakeHttp(
        [
            ("GET", f"/snap/v1/transactions/{snap_token}", FakeResponse(json_data={"enabled_payments": ["gopay"]})),
            (
                "POST",
                f"/snap/v3/accounts/{snap_token}/linking",
                FakeResponse(status_code=201, json_data={"activation_link_url": f"https://gopay.local/link?reference={reference_id}"}),
            ),
            ("POST", "/v1/linking/validate-reference", FakeResponse(json_data={"success": True})),
            ("POST", "/v1/linking/user-consent", FakeResponse(json_data={"success": True})),
            ("POST", "/v1/linking/resend-otp", FakeResponse(json_data={"success": True})),
            (
                "POST",
                "/v1/linking/validate-otp",
                FakeResponse(
                    status_code=400,
                    json_data={
                        "success": False,
                        "errors": [
                            {
                                "code": "GoPay-1604",
                                "message_title": "Kode OTP-nya salah. Mohon cek ulang dan coba lagi.",
                                "is_retryable": True,
                            }
                        ],
                    },
                    text='{"success":false,"errors":[{"code":"GoPay-1604"}]}',
                ),
            ),
            (
                "POST",
                "/v1/linking/validate-otp",
                FakeResponse(
                    json_data={
                        "success": True,
                        "data": {
                            "challenge": {
                                "action": {
                                    "value": {"challenge_id": "challenge_link", "client_id": "client_link"}
                                }
                            }
                        },
                    }
                ),
            ),
            ("POST", "/api/v1/users/pin/tokens/nb", FakeResponse(json_data={"token": "pin_link"})),
            ("POST", "/v1/linking/validate-pin", FakeResponse(json_data={"success": True})),
            (
                "POST",
                f"/snap/v2/transactions/{snap_token}/charge",
                FakeResponse(json_data={"gopay_verification_link_url": "https://gopay.local/pay?reference=CHARGE123"}),
            ),
            ("GET", "/v1/payment/validate", FakeResponse(json_data={"success": True})),
            (
                "POST",
                "/v1/payment/confirm",
                FakeResponse(
                    json_data={
                        "success": True,
                        "data": {
                            "challenge": {
                                "action": {
                                    "value": {"challenge_id": "challenge_pay", "client_id": "client_pay"}
                                }
                            }
                        },
                    }
                ),
            ),
            ("POST", "/api/v1/users/pin/tokens/nb", FakeResponse(json_data={"token": "pin_pay"})),
            ("POST", "/v1/payment/process", FakeResponse(json_data={"success": True, "data": {"next_action": "payment-success"}})),
        ]
    )
    otp_calls = []
    progress_events = []

    def otp_provider():
        ignored = set(getattr(otp_provider, "_gopay_ignored_otps", set()))
        otp_calls.append(ignored)
        return "222222" if "111111" in ignored else "111111"

    charger = GoPayHttpCharger(
        http=http,
        phone_number="+6287761973970",
        gopay_pin="558023",
        otp_provider=otp_provider,
        otp_channel="sms",
        sms_resend_wait_seconds=0,
        progress_callback=progress_events.append,
    )

    result = charger.run_from_snap_token(snap_token=snap_token, checkout_session_id="cs_test")

    assert result["state"] == "succeeded"
    validate_requests = [request for request in http.requests if request["url"].endswith("/validate-otp")]
    assert [request["kwargs"]["json"]["otp"] for request in validate_requests] == ["111111", "222222"]
    assert otp_calls == [set(), {"111111"}]
    assert any(event["stage"] == "otp_invalid" for event in progress_events)
    assert http.responses == []


def test_gopay_http_charger_retries_transient_stripe_payment_method(monkeypatch):
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda *args, **kwargs: None)
    http = FakeHttp(
        [
            ("POST", "/v1/payment_methods", gopay_executor.requests.exceptions.ReadTimeout("timeout")),
            ("POST", "/v1/payment_methods", FakeResponse(json_data={"id": "pm_retry"})),
        ]
    )
    charger = GoPayHttpCharger(
        http=http,
        phone_number="+6287761973970",
        gopay_pin="558023",
        otp_provider=lambda: "123456",
    )

    assert charger._stripe_create_payment_method("cs_test", "pk_test") == "pm_retry"
    assert len(http.requests) == 2


def test_gopay_http_charger_retries_transient_gopay_validate_reference(monkeypatch):
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda *args, **kwargs: None)
    http = FakeHttp(
        [
            ("POST", "/v1/linking/validate-reference", gopay_executor.requests.exceptions.SSLError("eof")),
            ("POST", "/v1/linking/validate-reference", FakeResponse(json_data={"success": True})),
        ]
    )
    charger = GoPayHttpCharger(
        http=http,
        phone_number="+6287761973970",
        gopay_pin="558023",
        otp_provider=lambda: "123456",
    )

    charger._gopay_validate_reference("reference")

    assert len(http.requests) == 2


def test_gopay_http_charger_marks_rate_limited_user_consent():
    progress_events = []
    http = FakeHttp(
        [
            (
                "POST",
                "/v1/linking/user-consent",
                FakeResponse(json_data={"success": False, "message": "too many attempts, please try again later"}),
            ),
        ]
    )
    charger = GoPayHttpCharger(
        http=http,
        phone_number="+6287761973970",
        gopay_pin="558023",
        otp_provider=lambda: "123456",
        progress_callback=progress_events.append,
    )

    try:
        charger._gopay_user_consent("reference")
    except gopay_executor.GoPayRateLimited as exc:
        assert exc.stage == "gopay_rate_limited"
    else:
        raise AssertionError("expected GoPayRateLimited")

    assert any(event["stage"] == "gopay_rate_limited" for event in progress_events)


def test_generate_id_checkout_http_builds_canonical_url():
    http = FakeHttp(
        [
            (
                "POST",
                "/backend-api/payments/checkout",
                FakeResponse(
                    json_data={
                        "checkout_session_id": "cs_test_123",
                        "processor_entity": "openai_llc",
                        "publishable_key": "pk_test",
                    }
                ),
            ),
        ]
    )

    result = _generate_id_checkout_http(
        http,
        access_token="access",
        session_token="session",
        account_id="account",
        device_id="device",
        openai_sentinel_token="sentinel",
        oai_client_version="web-1",
        oai_client_build_number="123",
    )

    assert result["url"] == "https://chatgpt.com/checkout/openai_llc/cs_test_123"
    checkout_request = http.requests[-1]
    assert checkout_request["kwargs"]["json"]["billing_details"] == {"country": "ID", "currency": "IDR"}
    assert checkout_request["kwargs"]["json"]["checkout_ui_mode"] == "custom"
    assert http.headers["Authorization"] == "Bearer access"
    assert "__Secure-next-auth.session-token=session" in http.headers["Cookie"]
    assert "_account=" not in http.headers["Cookie"]
    assert "chatgpt-account-id" not in http.headers
    assert http.headers["openai-sentinel-token"] == "sentinel"
    assert http.headers["oai-client-version"] == "web-1"
    assert http.headers["oai-client-build-number"] == "123"


def test_gopay_http_charger_retries_linking_when_account_already_linked(monkeypatch):
    sleeps = []
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda seconds: sleeps.append(seconds))

    snap_token = "11111111-1111-4111-8111-111111111111"
    reference_id = "22222222-2222-4222-8222-222222222222"
    http = FakeHttp(
        [
            ("GET", f"/snap/v1/transactions/{snap_token}", FakeResponse(json_data={"enabled_payments": ["gopay"]})),
            (
                "POST",
                f"/snap/v3/accounts/{snap_token}/linking",
                FakeResponse(status_code=406, json_data={"error_messages": ["account already linked"]}),
            ),
            (
                "POST",
                f"/snap/v3/accounts/{snap_token}/linking",
                FakeResponse(status_code=201, json_data={"activation_link_url": f"https://gopay.local/link?reference={reference_id}"}),
            ),
            ("POST", "/v1/linking/validate-reference", FakeResponse(json_data={"success": True})),
            ("POST", "/v1/linking/user-consent", FakeResponse(json_data={"success": True})),
            (
                "POST",
                "/v1/linking/validate-otp",
                FakeResponse(
                    json_data={
                        "success": True,
                        "data": {
                            "challenge": {
                                "action": {
                                    "value": {"challenge_id": "challenge_link", "client_id": "client_link"}
                                }
                            }
                        },
                    }
                ),
            ),
            ("POST", "/api/v1/users/pin/tokens/nb", FakeResponse(json_data={"token": "pin_link"})),
            ("POST", "/v1/linking/validate-pin", FakeResponse(json_data={"success": True})),
            (
                "POST",
                f"/snap/v2/transactions/{snap_token}/charge",
                FakeResponse(json_data={"gopay_verification_link_url": "https://gopay.local/pay?reference=CHARGE123"}),
            ),
            ("GET", "/v1/payment/validate", FakeResponse(json_data={"success": True})),
            (
                "POST",
                "/v1/payment/confirm",
                FakeResponse(
                    json_data={
                        "success": True,
                        "data": {
                            "challenge": {
                                "action": {
                                    "value": {"challenge_id": "challenge_pay", "client_id": "client_pay"}
                                }
                            }
                        },
                    }
                ),
            ),
            ("POST", "/api/v1/users/pin/tokens/nb", FakeResponse(json_data={"token": "pin_pay"})),
            ("POST", "/v1/payment/process", FakeResponse(json_data={"success": True, "data": {"next_action": "payment-success"}})),
        ]
    )
    progress_events = []
    otp_calls = []

    charger = GoPayHttpCharger(
        http=http,
        phone_number="+6287761973970",
        gopay_pin="558023",
        otp_provider=lambda: otp_calls.append(True) or "123456",
        progress_callback=progress_events.append,
    )

    result = charger.run_from_snap_token(snap_token=snap_token, checkout_session_id="cs_test")

    assert result["state"] == "succeeded"
    assert result["reference_id"] == reference_id
    assert result["charge_ref"] == "CHARGE123"
    assert otp_calls == [True]
    assert any(event["stage"] == "midtrans_already_linked" for event in progress_events)
    linked_event = next(event for event in progress_events if event["stage"] == "midtrans_already_linked")
    assert linked_event["wait_seconds"] == 30
    assert "解绑" in linked_event["message"]
    assert sleeps == [30.0]
    assert http.responses == []


def test_gopay_http_charger_exits_after_repeated_already_linked(monkeypatch):
    sleeps = []
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda seconds: sleeps.append(seconds))

    snap_token = "11111111-1111-4111-8111-111111111111"
    http = FakeHttp(
        [
            ("GET", f"/snap/v1/transactions/{snap_token}", FakeResponse(json_data={"enabled_payments": ["gopay"]})),
            (
                "POST",
                f"/snap/v3/accounts/{snap_token}/linking",
                FakeResponse(status_code=406, json_data={"error_messages": ["account already linked"]}),
            ),
            (
                "POST",
                f"/snap/v3/accounts/{snap_token}/linking",
                FakeResponse(status_code=406, json_data={"error_messages": ["account already linked"]}),
            ),
            (
                "POST",
                f"/snap/v3/accounts/{snap_token}/linking",
                FakeResponse(status_code=406, json_data={"error_messages": ["account already linked"]}),
            ),
            (
                "POST",
                f"/snap/v3/accounts/{snap_token}/linking",
                FakeResponse(status_code=406, json_data={"error_messages": ["account already linked"]}),
            ),
        ]
    )
    progress_events = []
    otp_calls = []
    charger = GoPayHttpCharger(
        http=http,
        phone_number="+6287761973970",
        gopay_pin="558023",
        otp_provider=lambda: otp_calls.append(True) or "123456",
        progress_callback=progress_events.append,
    )

    try:
        charger.run_from_snap_token(snap_token=snap_token, checkout_session_id="cs_test")
    except gopay_executor.GoPayAlreadyLinked as exc:
        assert exc.stage == "midtrans_linking"
        assert "解绑" in str(exc)
    else:
        raise AssertionError("expected GoPayAlreadyLinked")

    assert [event["stage"] for event in progress_events].count("midtrans_already_linked") == 3
    assert any(event["stage"] == "midtrans_already_linked_failed" for event in progress_events)
    assert sleeps == [30.0, 30.0, 30.0]
    assert otp_calls == []
    assert http.responses == []


def test_gopay_http_charger_allows_midtrans_one_idr_authorization_before_linking(monkeypatch):
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda *args, **kwargs: None)
    monkeypatch.delenv("GOPAY_ALLOW_NONZERO_CHARGE", raising=False)

    snap_token = "11111111-1111-4111-8111-111111111111"
    http = FakeHttp(
        [
            (
                "GET",
                f"/snap/v1/transactions/{snap_token}",
                FakeResponse(
                    json_data={
                        "transaction_details": {"gross_amount": "1", "currency": "IDR"},
                        "enabled_payments": ["gopay"],
                    }
                ),
            ),
            (
                "POST",
                f"/snap/v3/accounts/{snap_token}/linking",
                FakeResponse(status_code=406, json_data={"error_messages": ["account already linked"]}),
            ),
            (
                "POST",
                f"/snap/v3/accounts/{snap_token}/linking",
                FakeResponse(status_code=406, json_data={"error_messages": ["account already linked"]}),
            ),
            (
                "POST",
                f"/snap/v3/accounts/{snap_token}/linking",
                FakeResponse(status_code=406, json_data={"error_messages": ["account already linked"]}),
            ),
            (
                "POST",
                f"/snap/v3/accounts/{snap_token}/linking",
                FakeResponse(status_code=406, json_data={"error_messages": ["account already linked"]}),
            ),
        ]
    )
    progress_events = []
    charger = GoPayHttpCharger(
        http=http,
        phone_number="+6287761973970",
        gopay_pin="558023",
        otp_provider=lambda: "123456",
        progress_callback=progress_events.append,
    )

    try:
        charger.run_from_snap_token(snap_token=snap_token, checkout_session_id="cs_test")
    except gopay_executor.GoPayAlreadyLinked:
        pass
    else:
        raise AssertionError("expected GoPayAlreadyLinked")

    assert not any(event["stage"] == "midtrans_nonzero_amount_blocked" for event in progress_events)
    assert any(request["url"].endswith("/linking") for request in http.requests)
    assert http.responses == []


def test_gopay_http_charger_blocks_stripe_nonzero_before_approve(monkeypatch):
    monkeypatch.delenv("GOPAY_ALLOW_NONZERO_CHARGE", raising=False)

    http = FakeHttp(
        [
            (
                "POST",
                "/v1/payment_pages/cs_test/init",
                FakeResponse(json_data={"init_checksum": "init_123", "total_summary": {"due": 34900000}}),
            ),
        ]
    )
    progress_events = []
    charger = GoPayHttpCharger(
        http=http,
        phone_number="+6287761973970",
        gopay_pin="558023",
        otp_provider=lambda: "123456",
        approve_callback=lambda session_id: (_ for _ in ()).throw(AssertionError("approve must not run for nonzero due")),
        progress_callback=progress_events.append,
    )

    try:
        charger.run(checkout_session_id="cs_test", stripe_pk="pk_test")
    except gopay_executor.GoPayChargeBlocked as exc:
        assert exc.stage == "stripe_charge_guard"
        assert "ChatGPT approve" in str(exc)
    else:
        raise AssertionError("expected GoPayChargeBlocked")

    assert any(event["stage"] == "stripe_nonzero_amount_blocked" for event in progress_events)
    assert not any(event["stage"] == "chatgpt_approve" for event in progress_events)
    assert not any(request["url"].endswith("/v1/payment_methods") for request in http.requests)
    assert not any(request["url"].endswith("/confirm") for request in http.requests)
    assert http.responses == []


def test_gopay_http_charger_blocks_stripe_nonzero_before_linking(monkeypatch):
    monkeypatch.delenv("GOPAY_ALLOW_NONZERO_CHARGE", raising=False)

    snap_token = "11111111-1111-4111-8111-111111111111"
    http = FakeHttp(
        [
            (
                "GET",
                f"/snap/v1/transactions/{snap_token}",
                FakeResponse(json_data={"enabled_payments": ["gopay"]}),
            ),
        ]
    )
    progress_events = []
    charger = GoPayHttpCharger(
        http=http,
        phone_number="+6287761973970",
        gopay_pin="558023",
        otp_provider=lambda: "123456",
        progress_callback=progress_events.append,
    )
    charger.expected_due_amount = 34900000

    try:
        charger.run_from_snap_token(snap_token=snap_token, checkout_session_id="cs_test")
    except gopay_executor.GoPayChargeBlocked as exc:
        assert exc.stage == "stripe_charge_guard"
        assert "GoPay 绑定前停止" in str(exc)
    else:
        raise AssertionError("expected GoPayChargeBlocked")

    assert any(event["stage"] == "stripe_nonzero_amount_blocked" for event in progress_events)
    assert not any(request["url"].endswith("/linking") for request in http.requests)
    assert http.responses == []


def test_gopay_http_charger_allows_zero_stripe_due_with_midtrans_gross(monkeypatch):
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda *args, **kwargs: None)

    snap_token = "11111111-1111-4111-8111-111111111111"
    reference_id = "22222222-2222-4222-8222-222222222222"
    http = FakeHttp(
        [
            (
                "GET",
                f"/snap/v1/transactions/{snap_token}",
                FakeResponse(json_data={"transaction_details": {"gross_amount": "349000", "currency": "IDR"}}),
            ),
            (
                "POST",
                f"/snap/v3/accounts/{snap_token}/linking",
                FakeResponse(status_code=406, json_data={"error_messages": ["account already linked"]}),
            ),
            (
                "POST",
                f"/snap/v3/accounts/{snap_token}/linking",
                FakeResponse(status_code=201, json_data={"activation_link_url": f"https://gopay.local/link?reference={reference_id}"}),
            ),
            ("POST", "/v1/linking/validate-reference", FakeResponse(json_data={"success": True})),
            ("POST", "/v1/linking/user-consent", FakeResponse(json_data={"success": True})),
            (
                "POST",
                "/v1/linking/validate-otp",
                FakeResponse(
                    json_data={
                        "success": True,
                        "data": {
                            "challenge": {
                                "action": {
                                    "value": {"challenge_id": "challenge_link", "client_id": "client_link"}
                                }
                            }
                        },
                    }
                ),
            ),
            ("POST", "/api/v1/users/pin/tokens/nb", FakeResponse(json_data={"token": "pin_link"})),
            ("POST", "/v1/linking/validate-pin", FakeResponse(json_data={"success": True})),
            (
                "POST",
                f"/snap/v2/transactions/{snap_token}/charge",
                FakeResponse(json_data={"gopay_verification_link_url": "https://gopay.local/pay?reference=CHARGE123"}),
            ),
            ("GET", "/v1/payment/validate", FakeResponse(json_data={"success": True})),
            (
                "POST",
                "/v1/payment/confirm",
                FakeResponse(
                    json_data={
                        "success": True,
                        "data": {
                            "challenge": {
                                "action": {
                                    "value": {"challenge_id": "challenge_pay", "client_id": "client_pay"}
                                }
                            }
                        },
                    }
                ),
            ),
            ("POST", "/api/v1/users/pin/tokens/nb", FakeResponse(json_data={"token": "pin_pay"})),
            ("POST", "/v1/payment/process", FakeResponse(json_data={"success": True, "data": {"next_action": "payment-success"}})),
        ]
    )
    progress_events = []
    charger = GoPayHttpCharger(
        http=http,
        phone_number="+6287761973970",
        gopay_pin="558023",
        otp_provider=lambda: "123456",
        progress_callback=progress_events.append,
    )
    charger.expected_due_amount = 0

    result = charger.run_from_snap_token(snap_token=snap_token, checkout_session_id="cs_test")

    assert result["state"] == "succeeded"
    assert result["charge_ref"] == "CHARGE123"
    assert any(event["stage"] == "stripe_zero_due_confirmed" for event in progress_events)


def test_gopay_http_charger_rejects_bad_pin():
    charger = GoPayHttpCharger(
        http=FakeHttp(
            [
                (
                    "POST",
                    "/api/v1/users/pin/tokens/nb",
                    FakeResponse(status_code=401, text='{"error":"invalid pin"}'),
                )
            ]
        ),
        phone_number="+6287761973970",
        gopay_pin="000000",
        otp_provider=lambda: "123456",
    )

    try:
        charger._tokenize_pin("challenge", "client")
    except GoPayPINRejected as exc:
        assert exc.stage == "gopay_tokenize_pin"
        assert "PIN" in str(exc)
    else:
        raise AssertionError("expected GoPayPINRejected")


def test_split_address_lines():
    assert _split_address_lines("570 MARGARET ST APT C") == ("570 MARGARET ST", "APT C")
    assert _split_address_lines("123 MAIN ST") == ("123 MAIN ST", "")


def test_fetch_random_billing_address_falls_back_on_network_error(monkeypatch):
    def fail(*args, **kwargs):
        raise gopay_executor.requests.exceptions.SSLError("ssl")

    monkeypatch.setattr(gopay_executor.requests, "post", fail)

    result = _fetch_random_billing_address()

    assert result["country"] == "US"
    assert result["state"] == "CA"
    assert result["zip"] == "90026"


def test_gopay_result_includes_billing_info():
    result = _build_result(
        "success",
        message="ok",
        billing_info={
            "name": "John Smith",
            "country": "US",
            "state": "MI",
            "city": "MUSKEGON",
            "zip": "49442",
            "address1": "570 MARGARET ST",
            "address2": "APT C",
        },
    )

    assert result["billing_info"]["name"] == "John Smith"
    assert result["billing_info"]["address1"] == "570 MARGARET ST"


def test_gopay_bind_task_rotates_on_chatgpt_approve_blocked(monkeypatch):
    monkeypatch.setenv("GOPAY_APPROVE_BLOCKED_COOLDOWN_SECONDS", "123")
    gopay_executor._GOPAY_APPROVE_BLOCKED_UNTIL.clear()
    monkeypatch.setattr(
        gopay_executor,
        "list_auth_session_emails",
        lambda: ["primary@example.com", "backup@example.com"],
    )
    calls = []

    def fake_run_once(**kwargs):
        calls.append(kwargs["email"])
        if kwargs["email"] == "primary@example.com":
            return {
                "status": "failed",
                "failure_stage": "chatgpt_approve",
                "message": "ChatGPT approve 未通过: {'result': 'blocked'}",
            }
        return {"status": "success", "message": "ok"}

    monkeypatch.setattr(gopay_executor, "_run_gopay_bind_task_once", fake_run_once)
    progress_events = []

    result = gopay_executor.run_gopay_bind_task(
        email="primary@example.com",
        account_emails=["primary@example.com", "backup@example.com"],
        checkout_url="",
        phone_number="+6287761973970",
        sms_url="https://sms.example.test",
        gopay_pin="558023",
        progress_callback=progress_events.append,
    )

    assert calls == ["primary@example.com", "backup@example.com"]
    assert result["status"] == "success"
    assert result["email_used"] == "backup@example.com"
    assert result["requested_email"] == "primary@example.com"
    assert result["blocked_emails"] == ["primary@example.com"]
    assert "primary@example.com" in gopay_executor._GOPAY_APPROVE_BLOCKED_UNTIL
    assert any(event["stage"] == "chatgpt_approve_blocked_rotate" for event in progress_events)
    assert any(event["stage"] == "gopay_rotate_account" for event in progress_events)


def test_gopay_bind_task_single_account_does_not_rotate_on_blocked(monkeypatch):
    monkeypatch.setenv("GOPAY_APPROVE_BLOCKED_COOLDOWN_SECONDS", "123")
    gopay_executor._GOPAY_APPROVE_BLOCKED_UNTIL.clear()
    monkeypatch.setattr(
        gopay_executor,
        "list_auth_session_emails",
        lambda: ["primary@example.com", "backup@example.com"],
    )
    calls = []

    def fake_run_once(**kwargs):
        calls.append(kwargs["email"])
        return {
            "status": "failed",
            "failure_stage": "chatgpt_approve",
            "message": "ChatGPT approve 未通过: {'result': 'blocked'}",
        }

    monkeypatch.setattr(gopay_executor, "_run_gopay_bind_task_once", fake_run_once)
    progress_events = []

    result = gopay_executor.run_gopay_bind_task(
        email="primary@example.com",
        checkout_url="",
        phone_number="+6287761973970",
        sms_url="https://sms.example.test",
        gopay_pin="558023",
        progress_callback=progress_events.append,
    )

    assert calls == ["primary@example.com"]
    assert result["failure_stage"] == "chatgpt_approve"
    assert result["email_used"] == "primary@example.com"
    assert "approve_blocked_cooldown_seconds" not in result
    assert gopay_executor._GOPAY_APPROVE_BLOCKED_UNTIL == {}
    assert not any(event["stage"] == "chatgpt_approve_blocked_cooldown" for event in progress_events)

    retried = gopay_executor.run_gopay_bind_task(
        email="primary@example.com",
        checkout_url="",
        phone_number="+6287761973970",
        sms_url="https://sms.example.test",
        gopay_pin="558023",
    )

    assert calls == ["primary@example.com", "primary@example.com"]
    assert retried["failure_stage"] == "chatgpt_approve"
    assert "冷却" not in retried["message"]


def test_gopay_bind_task_checkout_url_disables_rotation(monkeypatch):
    calls = []

    def fake_run_once(**kwargs):
        calls.append(kwargs["email"])
        return {
            "status": "failed",
            "failure_stage": "chatgpt_approve",
            "message": "ChatGPT approve 未通过: {'result': 'blocked'}",
        }

    monkeypatch.setattr(gopay_executor, "_run_gopay_bind_task_once", fake_run_once)

    result = gopay_executor.run_gopay_bind_task(
        email="primary@example.com",
        account_emails=["primary@example.com", "backup@example.com"],
        checkout_url="https://chatgpt.com/checkout/openai_llc/cs_test",
        phone_number="+6287761973970",
        sms_url="https://sms.example.test",
        gopay_pin="558023",
    )

    assert calls == ["primary@example.com"]
    assert result["failure_stage"] == "chatgpt_approve"
    assert result["email_used"] == "primary@example.com"


def test_gopay_bind_task_direct_midtrans_link_skips_checkout_and_approve(monkeypatch):
    progress_events = []
    created = {}
    midtrans_url = "https://app.midtrans.com/snap/v4/redirection/11111111-1111-4111-8111-111111111111"

    monkeypatch.setattr(
        gopay_executor,
        "load_auth_session",
        lambda email: {
            "accessToken": "access",
            "sessionToken": "session",
            "account": {"id": "account"},
        },
    )
    monkeypatch.setattr(gopay_executor, "_build_chatgpt_http_session", lambda **kwargs: object())
    monkeypatch.setattr(gopay_executor, "_new_http_session", lambda *args, **kwargs: object())

    class FakeGoPayCharger:
        def __init__(self, **kwargs):
            created.update(kwargs)

        def run(self, **kwargs):
            raise AssertionError("direct Midtrans link must not run Stripe/approve path")

        def run_from_redirect(self, *, redirect_url, checkout_session_id=""):
            assert redirect_url == midtrans_url
            assert checkout_session_id == ""
            return {
                "state": "succeeded",
                "snap_token": "11111111-1111-4111-8111-111111111111",
                "charge_ref": "CHARGE123",
                "reference_id": "REF123",
            }

    monkeypatch.setattr(gopay_executor, "GoPayHttpCharger", FakeGoPayCharger)

    result = gopay_executor._run_gopay_bind_task_once(
        email="primary@example.com",
        checkout_url=midtrans_url,
        phone_number="+6287761973970",
        sms_url="https://sms.example.test",
        gopay_pin="558023",
        progress_callback=progress_events.append,
    )

    assert result["status"] == "success"
    assert result["flow"] == "gopay_http"
    assert not any(event["stage"] == "generate_checkout" for event in progress_events)
    assert any(event["stage"] == "checkout_ready" and event.get("mode") == "redirect" for event in progress_events)
    assert callable(created["approve_callback"])
    assert callable(created["verify_callback"])
    assert created["otp_channel"] == "sms"
    assert "sms_otp_trigger_callback" not in created or created["sms_otp_trigger_callback"] is None


def test_gopay_bind_task_treats_verify_timeout_after_payment_as_success(monkeypatch):
    midtrans_url = "https://app.midtrans.com/snap/v4/redirection/11111111-1111-4111-8111-111111111111"
    progress_events = []

    monkeypatch.setattr(
        gopay_executor,
        "load_auth_session",
        lambda email: {
            "accessToken": "access",
            "sessionToken": "session",
            "account": {"id": "account"},
        },
    )
    monkeypatch.setattr(gopay_executor, "_build_chatgpt_http_session", lambda **kwargs: object())
    monkeypatch.setattr(gopay_executor, "_new_http_session", lambda *args, **kwargs: object())

    class FakeGoPayCharger:
        def __init__(self, **kwargs):
            pass

        def run_from_redirect(self, *, redirect_url, checkout_session_id=""):
            return {
                "state": "verify_timeout",
                "snap_token": "11111111-1111-4111-8111-111111111111",
                "charge_ref": "CHARGE123",
                "reference_id": "REF123",
                "verify": {"state": "verify_timeout", "error": "connect timeout"},
            }

    monkeypatch.setattr(gopay_executor, "GoPayHttpCharger", FakeGoPayCharger)

    result = gopay_executor._run_gopay_bind_task_once(
        email="primary@example.com",
        checkout_url=midtrans_url,
        phone_number="+6287761973970",
        sms_url="https://sms.example.test",
        gopay_pin="558023",
        progress_callback=progress_events.append,
    )

    assert result["status"] == "success"
    assert result["verify_state"] == "verify_timeout"
    assert result["verify_warning"] == "chatgpt_verify_timeout"
    assert "verify 网络超时" in result["message"]
    assert any(event["stage"] == "completed" for event in progress_events)
    assert not any(event["stage"] == "failed" for event in progress_events)


def test_gopay_bind_task_uses_full_browser_checkout_ui_without_protocol_approve(monkeypatch):
    progress_events = []
    checkout_url = "https://chatgpt.com/checkout/openai_llc/cs_test"
    handoff_calls = []

    monkeypatch.setattr(
        gopay_executor,
        "load_auth_session",
        lambda email: {
            "accessToken": "access",
            "sessionToken": "session",
            "account": {"id": "account"},
            "device_id": "device",
            "cookie_header": "__Secure-next-auth.session-token=session; old=1",
        },
    )
    monkeypatch.setattr(gopay_executor, "_build_chatgpt_http_session", lambda **kwargs: object())
    monkeypatch.setattr(gopay_executor, "_new_http_session", lambda *args, **kwargs: object())

    def fake_browser_handoff(api, **kwargs):
        handoff_calls.append(kwargs)
        return {
            "checkout_url": "https://chatgpt.com/checkout/openai_llc/cs_browser",
            "checkout_session_id": "cs_browser",
            "processor_entity": "openai_llc",
            "redirect_url": "https://pm-redirects.stripe.com/authorize/test",
        }

    monkeypatch.setattr(gopay_executor, "_browser_checkout_to_gopay_redirect", fake_browser_handoff)

    class FakeGoPayCharger:
        def __init__(self, **kwargs):
            pass

        def run(self, *, checkout_session_id, stripe_pk):
            raise AssertionError("browser UI mode must not run protocol Stripe/approve checkout")

        def run_from_redirect(self, *, redirect_url, checkout_session_id=""):
            assert redirect_url == "https://pm-redirects.stripe.com/authorize/test"
            assert checkout_session_id == "cs_browser"
            return {
                "state": "succeeded",
                "snap_token": "11111111-1111-4111-8111-111111111111",
                "charge_ref": "CHARGE123",
                "reference_id": "REF123",
            }

    monkeypatch.setattr(gopay_executor, "GoPayHttpCharger", FakeGoPayCharger)

    result = gopay_executor._run_gopay_bind_task_once(
        email="primary@example.com",
        checkout_url=checkout_url,
        phone_number="+6287761973970",
        sms_url="https://sms.example.test",
        gopay_pin="558023",
        progress_callback=progress_events.append,
    )

    assert result["status"] == "success"
    assert result["session_id"] == "cs_browser"
    assert result["checkout_url"] == "https://chatgpt.com/checkout/openai_llc/cs_browser"
    assert handoff_calls
    assert handoff_calls[0]["session_token"] == "session"
    assert handoff_calls[0]["checkout_url"] == checkout_url
    assert handoff_calls[0]["checkout_ui_mode"] == "custom"


def test_gopay_bind_task_missing_access_token_does_not_launch_playwright(monkeypatch):
    class FakeApi:
        def _launch_browser(self, *args, **kwargs):
            raise AssertionError("GoPay protocol mode must not launch Playwright")

        def stop(self):
            pass

    monkeypatch.setattr(gopay_executor, "ChatGPTTeamAPI", FakeApi)
    monkeypatch.setattr(
        gopay_executor,
        "load_auth_session",
        lambda email: {
            "sessionToken": "session",
            "account": {"id": "account"},
        },
    )

    result = gopay_executor._run_gopay_bind_task_once(
        email="primary@example.com",
        checkout_url="",
        phone_number="+6287761973970",
        sms_url="https://sms.example.test",
        gopay_pin="558023",
        billing_info={
            "name": "John Smith",
            "country": "US",
            "state": "CA",
            "city": "San Mateo",
            "zip": "94401",
            "address1": "1 Main St",
        },
    )

    assert result["status"] == "failed"
    assert result["failure_stage"] == "generate_checkout"
    assert "GoPay 协议模式不会启动 Playwright" in result["message"]


def test_looks_like_phone_number():
    assert _looks_like_phone_number("+6287761973970") is True
    assert _looks_like_phone_number("510-207-7094") is True
    assert _looks_like_phone_number("94612") is False


def test_value_matches_normalizes_whitespace_and_case():
    assert _value_matches("501  Holly Avenue", "501 Holly Avenue") is True
    assert _value_matches("Panama City", "panama city") is True
    assert _value_matches("FL", "CA") is False


def test_extract_checkout_error_detects_payment_not_approved():
    class FakePage:
        def evaluate(self, script):
            return ["开始免费试用 Plus 付款未获批准 付款方式 账单地址", "订阅"]

    class FakeApi:
        page = FakePage()

    assert _extract_checkout_error(FakeApi()) == "付款未获批准"


def test_submit_checkout_stops_on_payment_not_approved(monkeypatch):
    attempts = []
    progress_events = []

    def fake_click(*args, **kwargs):
        attempts.append(1)
        return True, ""

    monkeypatch.setattr(gopay_executor, "_click", fake_click)
    monkeypatch.setattr(
        gopay_executor,
        "_wait_for_phone_page_or_checkout_error",
        lambda *args, **kwargs: (False, "付款未获批准"),
    )
    monkeypatch.setattr(gopay_executor, "_capture_screenshot", lambda *args, **kwargs: None)
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda *args, **kwargs: None)

    ok, error = _submit_checkout_with_retries(
        object(),
        "session",
        [],
        lambda stage, **extra: progress_events.append((stage, extra)),
        max_attempts=3,
    )

    assert ok is False
    assert len(attempts) == 1
    assert "当前账号将从号池删除" in error
    assert "付款未获批准" in error
    assert not any(stage == "submit_retry" for stage, _ in progress_events)


def test_gopay_bind_task_rotates_on_checkout_payment_not_approved(monkeypatch):
    monkeypatch.setattr(
        gopay_executor,
        "list_auth_session_emails",
        lambda: ["primary@example.com", "backup@example.com"],
    )
    calls = []

    def fake_run_once(**kwargs):
        calls.append(kwargs["email"])
        if kwargs["email"] == "primary@example.com":
            return {
                "status": "failed",
                "failure_stage": "checkout_not_approved",
                "message": "付款未获批准，当前账号将从号池删除并停止本次账号尝试: 付款未获批准",
            }
        return {"status": "success", "message": "ok"}

    monkeypatch.setattr(gopay_executor, "_run_gopay_bind_task_once", fake_run_once)
    progress_events = []

    result = gopay_executor.run_gopay_bind_task(
        email="primary@example.com",
        account_emails=["primary@example.com", "backup@example.com"],
        checkout_url="",
        phone_number="+6287761973970",
        sms_url="https://sms.example.test",
        gopay_pin="558023",
        progress_callback=progress_events.append,
    )

    assert calls == ["primary@example.com", "backup@example.com"]
    assert result["status"] == "success"
    assert result["email_used"] == "backup@example.com"
    assert result["rejected_emails"] == ["primary@example.com"]
    assert any(event["stage"] == "checkout_not_approved_rotate" for event in progress_events)


def test_gopay_bind_task_batch_continues_after_success(monkeypatch):
    calls = []

    def fake_run_once(**kwargs):
        calls.append(kwargs["email"])
        return {"status": "success", "message": f"ok {kwargs['email']}"}

    monkeypatch.setattr(gopay_executor, "_run_gopay_bind_task_once", fake_run_once)
    progress_events = []

    result = gopay_executor.run_gopay_bind_task(
        email="first@example.com",
        account_emails=["first@example.com", "second@example.com", "third@example.com"],
        checkout_url="",
        phone_number="+6287761973970",
        sms_url="https://sms.example.test",
        gopay_pin="558023",
        progress_callback=progress_events.append,
    )

    assert calls == ["first@example.com", "second@example.com", "third@example.com"]
    assert result["status"] == "success"
    assert result["email_used"] == "third@example.com"
    assert result["successful_emails"] == ["first@example.com", "second@example.com", "third@example.com"]
    assert result["attempted_emails"] == ["first@example.com", "second@example.com", "third@example.com"]
    assert "成功 3/3 个账号" in result["message"]
    assert sum(1 for event in progress_events if event["stage"] == "gopay_account_bound") == 3
    assert any(event["stage"] == "gopay_batch_completed" for event in progress_events)


def test_resolve_page_billing_locator_searches_child_frames():
    class MissingLocator:
        first = None

        def __init__(self):
            self.first = self

        def wait_for(self, state=None, timeout=None):
            raise RuntimeError("not found")

    class FoundLocator:
        first = None

        def __init__(self):
            self.first = self
            self.waited = None

        def wait_for(self, state=None, timeout=None):
            self.waited = state

    class FakeFrame:
        def __init__(self, locator=None):
            self.locator_result = locator or MissingLocator()

        def get_by_placeholder(self, text, exact=None):
            return self.locator_result

        def get_by_label(self, text, exact=None):
            return MissingLocator()

        def locator(self, selector):
            return MissingLocator()

    class FakePage:
        def __init__(self):
            self.main_frame = FakeFrame()
            self.child_locator = FoundLocator()
            self.frames = [self.main_frame, FakeFrame(self.child_locator)]

    class FakeApi:
        def __init__(self):
            self.page = FakePage()

    api = FakeApi()
    locator = _resolve_page_billing_locator(
        api,
        ["input[placeholder='全名']"],
        placeholders=["全名"],
        labels=[],
        timeout_ms=200,
    )

    assert locator is api.page.child_locator
    assert locator.waited == "visible"
