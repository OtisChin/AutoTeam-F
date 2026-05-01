from autoteam import bind_executor, config, gopay_executor
from autoteam.gopay_executor import (
    GoPayHttpCharger,
    GoPayPINRejected,
    _build_result,
    _extract_checkout_error,
    _extract_checkout_session_id,
    _extract_sms_code,
    _fetch_random_billing_address,
    _generate_id_checkout_http,
    _poll_otp_from_sms_url,
    _looks_like_phone_number,
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


class FakeGoPayBody:
    def __init__(self, text):
        self.text = text

    def inner_text(self, timeout=None):
        return self.text


class FakeGoPayLocator:
    first = None

    def __init__(self, page, visible=False):
        self.first = self
        self.page = page
        self.visible = visible

    def is_visible(self, timeout=None):
        return self.visible

    def click(self, timeout=None):
        self.page.clicked = True


class FakeGoPayPage:
    def __init__(self, body_text="", sms_visible=True):
        self.body_text = body_text
        self.sms_visible = sms_visible
        self.clicked = False
        self.goto_url = ""
        self.waits = []

    def goto(self, url, wait_until=None, timeout=None):
        self.goto_url = url

    def locator(self, selector):
        return FakeGoPayBody(self.body_text)

    def get_by_role(self, role, name=None):
        return FakeGoPayLocator(self, visible=self.sms_visible and role == "button")

    def evaluate(self, script):
        return False

    def wait_for_timeout(self, timeout):
        self.waits.append(timeout)


class FakeGoPayContext:
    def __init__(self, page):
        self.page = page
        self.closed = False

    def new_page(self):
        return self.page

    def close(self):
        self.closed = True


class FakeGoPayBrowser:
    def __init__(self, context):
        self.context = context
        self.new_context_calls = 0

    def new_context(self, **kwargs):
        self.new_context_calls += 1
        self.context_options = kwargs
        return self.context


def test_trigger_sms_otp_uses_isolated_browser_context():
    page = FakeGoPayPage()
    isolated_context = FakeGoPayContext(page)
    browser = FakeGoPayBrowser(isolated_context)
    progress_events = []

    class SharedContext:
        def new_page(self):
            raise AssertionError("GoPay SMS page must not reuse ChatGPT context")

    class FakeApi:
        pass

    fake_api = FakeApi()
    fake_api.browser = browser
    fake_api.context = SharedContext()

    gopay_executor._trigger_sms_otp_in_page(
        fake_api,
        activation_link_url="https://merchants-gws-app.gopayapi.com/app/authorize?reference=ref&target=gwc",
        wait_seconds=0,
        progress=lambda stage, **extra: progress_events.append({"stage": stage, **extra}),
    )

    assert browser.new_context_calls == 1
    assert browser.context_options["locale"] == "en-US"
    assert page.clicked is True
    assert isolated_context.closed is True
    assert {"stage": "sms_otp_triggered"} in progress_events


def test_trigger_sms_otp_marks_gopay_rate_limited_and_closes_context():
    page = FakeGoPayPage(body_text="请稍后再试。 个人隐私政策 条款与条件", sms_visible=False)
    isolated_context = FakeGoPayContext(page)
    browser = FakeGoPayBrowser(isolated_context)
    progress_events = []

    class FakeApi:
        pass

    fake_api = FakeApi()
    fake_api.browser = browser

    try:
        gopay_executor._trigger_sms_otp_in_page(
            fake_api,
            activation_link_url="https://merchants-gws-app.gopayapi.com/app/authorize?reference=ref&target=gwc",
            wait_seconds=0,
            progress=lambda stage, **extra: progress_events.append({"stage": stage, **extra}),
        )
    except gopay_executor.GoPayRateLimited as exc:
        assert exc.stage == "gopay_rate_limited"
    else:
        raise AssertionError("expected GoPayRateLimited")

    assert isolated_context.closed is True
    assert {"stage": "gopay_rate_limited"} in progress_events


def test_extract_checkout_session_id_from_response_or_url():
    assert _extract_checkout_session_id(raw={"checkout_session_id": "cs_test_123"}) == "cs_test_123"
    assert _extract_checkout_session_id("https://chatgpt.com/checkout/openai_llc/cs_live_abc") == "cs_live_abc"


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
            ("POST", "/v1/payment_methods", FakeResponse(json_data={"id": "pm_test"})),
            ("POST", "/v1/payment_pages/cs_test/init", FakeResponse(json_data={"init_checksum": "init_123"})),
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
    assert approved == ["cs_test"]
    assert verified == ["cs_test"]
    assert sms_triggers == [(reference_id, activation_link)]
    linking_request = next(request for request in http.requests if request["url"].endswith("/linking"))
    assert linking_request["kwargs"]["json"] == {
        "type": "gopay",
        "country_code": "62",
        "phone_number": "87761973970",
    }
    assert any(event["stage"] == "gopay_payment_process" for event in progress_events)
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
    )

    assert result["url"] == "https://chatgpt.com/checkout/openai_llc/cs_test_123"
    checkout_request = http.requests[-1]
    assert checkout_request["kwargs"]["json"]["billing_details"] == {"country": "ID", "currency": "IDR"}
    assert http.headers["Authorization"] == "Bearer access"
    assert "__Secure-next-auth.session-token=session" in http.headers["Cookie"]
    assert "_account=" not in http.headers["Cookie"]
    assert "chatgpt-account-id" not in http.headers


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


def test_gopay_http_charger_blocks_nonzero_charge_after_linking_pin(monkeypatch):
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda *args, **kwargs: None)
    monkeypatch.delenv("GOPAY_ALLOW_NONZERO_CHARGE", raising=False)

    snap_token = "11111111-1111-4111-8111-111111111111"
    reference_id = "22222222-2222-4222-8222-222222222222"
    http = FakeHttp(
        [
            (
                "GET",
                f"/snap/v1/transactions/{snap_token}",
                FakeResponse(
                    json_data={
                        "transaction_details": {"gross_amount": "349000", "currency": "IDR"},
                        "enabled_payments": ["gopay"],
                    }
                ),
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
    except gopay_executor.GoPayChargeBlocked as exc:
        assert exc.stage == "midtrans_charge_guard"
        assert "349000" in str(exc)
    else:
        raise AssertionError("expected GoPayChargeBlocked")

    assert any(event["stage"] == "midtrans_nonzero_amount_blocked" for event in progress_events)
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

    result = gopay_executor.run_gopay_bind_task(
        email="primary@example.com",
        checkout_url="",
        phone_number="+6287761973970",
        sms_url="https://sms.example.test",
        gopay_pin="558023",
    )

    assert calls == ["primary@example.com"]
    assert result["failure_stage"] == "chatgpt_approve"
    assert result["email_used"] == "primary@example.com"
    assert gopay_executor._GOPAY_APPROVE_BLOCKED_UNTIL == {}


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


def test_submit_checkout_retries_payment_approval_errors(monkeypatch):
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
    assert len(attempts) == 3
    assert "重试 3 次" in error
    assert "付款未获批准" in error
    assert any(stage == "submit_retry" for stage, _ in progress_events)


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
