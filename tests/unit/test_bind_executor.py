import base64
import json
import sys
import types

import pytest

from autotoken import (
    bind_executor,
    chatgpt_api,
    config,
    gopay_executor,
    proxy_bridge,
)
from autotoken.gopay_executor import (
    GoPayFlowError,
    GoPayHttpCharger,
    GoPayOTPCancelled,
    GoPayPINRejected,
    _browser_checkout_nonzero_amount_hint,
    _build_result,
    _chatgpt_checkout_payload,
    _chatgpt_reference_cookie_header,
    _extract_checkout_error,
    _extract_checkout_session_id,
    _extract_sms_code,
    _extract_sms_codes,
    _fetch_random_billing_address,
    _generate_id_checkout_http,
    _generate_id_checkout_in_page,
    _gopay_progress_message,
    _is_checkout_customer_location_error,
    _is_checkout_rate_limited_error,
    _is_playwright_navigation_race_error,
    _looks_like_phone_number,
    _poll_otp_from_sms_url,
    _resolve_page_billing_locator,
    _safe_error_summary,
    _safe_proxy_summary,
    _safe_url_summary,
    _split_address_lines,
    _split_gopay_phone,
    _stripe_js_checksum,
    _stripe_rv_timestamp,
    _submit_checkout_with_retries,
    _value_matches,
)

@pytest.fixture(autouse=True)
def _fast_gopay_sms_resend(monkeypatch):
    monkeypatch.setenv("GOPAY_SMS_OTP_DELAY_SECONDS", "0")
    monkeypatch.setenv("GOPAY_SMS_CHANNEL_SWITCH_ENABLED", "0")

class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text="", headers=None, url=""):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.text = text
        self.headers = headers or {}
        self.url = url

    @property
    def ok(self):
        return 200 <= self.status_code < 300

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

def _stripe_address_update_responses(session_id="cs_test"):
    return [("POST", f"/v1/payment_pages/{session_id}", FakeResponse(json_data={"ok": True})) for _ in range(6)]

def test_chatgpt_reference_cookie_header_preserves_split_session_and_adds_account():
    cookie = "__Secure-next-auth.session-token.0=aaa; __Secure-next-auth.session-token.1=bbb; oai-did=device-cookie"

    header = _chatgpt_reference_cookie_header(
        session_token="full-session-token",
        account_id="account-123",
        device_id="device-param",
        cookie_header=cookie,
    )

    assert "__Secure-next-auth.session-token=full-session-token" not in header
    assert "__Secure-next-auth.session-token.0=aaa" in header
    assert "__Secure-next-auth.session-token.1=bbb" in header
    assert "_account=account-123" in header
    assert "oai-did=device-cookie" in header
    assert "oai-did=device-param" not in header

def test_gopay_auth_context_extracts_account_id_from_access_token(monkeypatch):
    def b64url(payload):
        raw = json.dumps(payload, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    access_token = ".".join(
        [
            b64url({"alg": "none"}),
            b64url(
                {
                    "https://api.openai.com/auth": {
                        "chatgpt_account_id": "account-from-jwt",
                    },
                    "https://api.openai.com/profile": {
                        "email": "user@example.com",
                    },
                }
            ),
            "sig",
        ]
    )
    monkeypatch.setattr(
        gopay_executor,
        "load_auth_session",
        lambda email: {
            "accessToken": access_token,
            "sessionToken": "session-token",
            "cookie_header": "__Secure-next-auth.session-token=session-token",
            "device_id": "device-id",
        },
    )
    monkeypatch.setattr(gopay_executor, "_load_chatgpt_auth_file_context", lambda email: {})

    context = gopay_executor._extract_auth_session_context("user@example.com")

    assert context["account_id"] == "account-from-jwt"
    assert context["access_token"] == access_token
    assert context["session_token"] == "session-token"

def test_run_bind_task_injects_selected_account_auth_session_before_checkout(monkeypatch):
    events = []
    apis = []

    class FakePage:
        url = "about:blank"

        def goto(self, url, **_kwargs):
            events.append(("goto", url))
            self.url = url

    class FakeApi:
        def __init__(self):
            self.page = FakePage()
            self.context = None
            self.oai_device_id = ""
            apis.append(self)

        def _launch_browser(self, **_kwargs):
            events.append(("launch", self.oai_device_id))
            self.context = object()

        def _wait_for_cloudflare(self):
            events.append(("cloudflare", None))

        def stop(self):
            events.append(("stop", None))

    def inject(api, **kwargs):
        events.append(("inject", kwargs))
        assert api.context is not None

    monkeypatch.setattr(bind_executor, "ChatGPTTeamAPI", FakeApi)
    monkeypatch.setattr(
        bind_executor,
        "load_auth_session",
        lambda email: {
            "sessionToken": "session-token",
            "cookie_header": "__Secure-next-auth.session-token=session-token",
            "account_id": "account-id",
            "device_id": "device-id",
        }
        if email == "user@example.com"
        else {},
        raising=False,
    )
    monkeypatch.setattr(bind_executor.chatgpt_session_service, "inject_chatgpt_browser_cookies", inject, raising=False)
    monkeypatch.setattr(bind_executor, "_capture_screenshot", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(bind_executor, "_fill_field", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        bind_executor,
        "generate_tax_free_billing_address",
        lambda: {
            "name": "Generated User",
            "country": "US",
            "state": "OR",
            "city": "Portland",
            "zip": "97201",
            "address1": "800 SW 5th Ave",
        },
    )
    monkeypatch.setattr(
        bind_executor,
        "_wait_for_checkout_result",
        lambda *_args, **_kwargs: {"status": "success", "message": "ok", "screenshot_paths": []},
    )

    result = bind_executor.run_bind_task(
        email="user@example.com",
        checkout_url="https://chatgpt.com/checkout/openai_llc/cs_test",
        card_item={
            "value": "4242424242424242",
            "meta": {"content": {"expiry_date": "12/30", "cvv": "123"}},
        },
    )

    assert result["status"] == "success"
    assert apis[0].oai_device_id == "device-id"
    assert events[:5] == [
        ("launch", "device-id"),
        (
            "inject",
            {
                "session_token": "session-token",
                "cookie_header": "__Secure-next-auth.session-token=session-token",
                "account_id": "account-id",
                "device_id": "device-id",
            },
        ),
        ("goto", "https://chatgpt.com/"),
        ("cloudflare", None),
        ("goto", "https://chatgpt.com/checkout/openai_llc/cs_test"),
    ]

def test_bind_checkout_response_capture_extracts_stripe_decline_reason():
    capture = bind_executor._new_checkout_network_capture()

    class FakePlaywrightResponse:
        url = "https://api.stripe.com/v1/payment_intents/pi_test_123/confirm"
        status = 402

        def json(self):
            return {
                "error": {
                    "code": "card_declined",
                    "decline_code": "generic_decline",
                    "message": "Your card was declined.",
                    "type": "card_error",
                }
            }

    bind_executor._capture_checkout_network_response(capture, FakePlaywrightResponse())
    result = bind_executor._enrich_checkout_result_with_network_failure(
        bind_executor._build_result("failed", failure_stage="post_submit", message="检测到支付失败提示"),
        capture,
    )

    assert result["payment_intent"]["failure_reason"] == {
        "code": "card_declined",
        "decline_code": "generic_decline",
        "message": "Your card was declined.",
        "type": "card_error",
    }
    assert "card_declined" in result["message"]
    assert "generic_decline" in result["message"]

def test_wait_for_checkout_result_includes_captured_network_decline(monkeypatch):
    capture = bind_executor._new_checkout_network_capture()
    bind_executor._capture_checkout_network_payload(
        capture,
        url="https://api.stripe.com/v1/payment_intents/pi_test_123/confirm",
        status=402,
        payload={
            "error": {
                "code": "card_declined",
                "decline_code": "do_not_honor",
                "message": "The bank did not approve this payment.",
                "type": "card_error",
            }
        },
    )

    class FakeLocator:
        def inner_text(self, timeout=1500):
            return "Your card was declined."

    class FakePage:
        url = "https://chatgpt.com/checkout/openai_llc/oaics_demo"

        def locator(self, _selector):
            return FakeLocator()

    class FakeApi:
        page = FakePage()

    monkeypatch.setattr(bind_executor, "_capture_screenshot", lambda *_args, **_kwargs: "")

    result = bind_executor._wait_for_checkout_result(
        FakeApi(),
        session_id="session",
        screenshot_paths=[],
        timeout_seconds=10,
        network_capture=capture,
    )

    assert result["status"] == "failed"
    assert result["payment_intent"]["failure_reason"]["code"] == "card_declined"
    assert result["payment_intent"]["failure_reason"]["decline_code"] == "do_not_honor"
    assert "do_not_honor" in result["message"]

def test_run_bind_task_fails_when_selected_account_has_no_auth_session(monkeypatch):
    events = []

    class FakeApi:
        def __init__(self):
            self.context = None
            self.page = type("Page", (), {"url": "about:blank"})()

        def _launch_browser(self, **_kwargs):
            events.append("launch")
            self.context = object()

        def stop(self):
            events.append("stop")

    monkeypatch.setattr(bind_executor, "ChatGPTTeamAPI", FakeApi)
    monkeypatch.setattr(bind_executor, "load_auth_session", lambda _email: {}, raising=False)
    monkeypatch.setattr(bind_executor, "_capture_screenshot", lambda *_args, **_kwargs: "")

    result = bind_executor.run_bind_task(
        email="user@example.com",
        checkout_url="https://chatgpt.com/checkout/openai_llc/cs_test",
        card_item={
            "value": "4242424242424242",
            "meta": {"content": {"expiry_date": "12/30", "cvv": "123"}},
        },
    )

    assert result["status"] == "failed"
    assert result["failure_stage"] == "open_checkout"
    assert "session token" in result["message"]
    assert events == ["stop"]

def test_run_bind_task_waits_for_slow_checkout_card_field(monkeypatch):
    timeouts = []

    class FakeLocator:
        def click(self, **_kwargs):
            pass

        def fill(self, *_args, **_kwargs):
            pass

    class FakePage:
        url = "https://chatgpt.com/checkout/openai_llc/cs_test"

        def goto(self, *_args, **_kwargs):
            pass

    class FakeApi:
        def __init__(self):
            self.page = FakePage()
            self.context = object()
            self.oai_device_id = ""

        def _launch_browser(self, **_kwargs):
            pass

        def _wait_for_cloudflare(self):
            pass

        def stop(self):
            pass

    def locator_from_selectors(_api, selectors, timeout_ms=4000):
        if selectors == bind_executor.CARD_NUMBER_SELECTORS:
            timeouts.append(timeout_ms)
            if timeout_ms < 60_000:
                return None
        return FakeLocator()

    monkeypatch.setattr(bind_executor, "ChatGPTTeamAPI", FakeApi)
    monkeypatch.setattr(
        bind_executor,
        "load_auth_session",
        lambda _email: {
            "sessionToken": "session-token",
            "cookie_header": "__Secure-next-auth.session-token=session-token",
        },
        raising=False,
    )
    monkeypatch.setattr(
        bind_executor.chatgpt_session_service,
        "inject_chatgpt_browser_cookies",
        lambda *_args, **_kwargs: None,
        raising=False,
    )
    monkeypatch.setattr(bind_executor, "_capture_screenshot", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(bind_executor, "_locator_from_selectors", locator_from_selectors)
    monkeypatch.setattr(bind_executor, "_fill_billing_name_before_address", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        bind_executor,
        "generate_tax_free_billing_address",
        lambda: {
            "name": "Generated User",
            "country": "US",
            "state": "OR",
            "city": "Portland",
            "zip": "97201",
            "address1": "800 SW 5th Ave",
        },
    )
    monkeypatch.setattr(
        bind_executor,
        "_wait_for_checkout_result",
        lambda *_args, **_kwargs: {"status": "success", "message": "ok", "screenshot_paths": []},
    )

    result = bind_executor.run_bind_task(
        email="user@example.com",
        checkout_url="https://chatgpt.com/checkout/openai_llc/cs_test",
        card_item={
            "value": "4242424242424242",
            "meta": {"content": {"expiry_date": "12/30", "cvv": "123"}},
        },
    )

    assert result["status"] == "success"
    assert timeouts
    assert timeouts[0] >= 60_000

def test_extract_card_payload_does_not_use_card_billing_address():
    payload = bind_executor.extract_card_payload(
        {
            "value": "4242424242424242",
            "meta": {
                "content": {
                    "expiry_date": "12/30",
                    "cvv": "123",
                    "name": "Jane Doe",
                    "address": "123 Main St, New York NY 10001, US",
                }
            },
        }
    )

    assert payload["address"] == ""
    assert payload["city"] == ""
    assert payload["state"] == ""
    assert payload["postal_code"] == ""
    assert payload["country"] == ""

def test_generate_tax_free_billing_address_rejects_non_tax_free_generated_address():
    billing = bind_executor.generate_tax_free_billing_address(
        fetch_billing_address=lambda: {
            "name": "Generated User",
            "country": "US",
            "state": "CA",
            "city": "Los Angeles",
            "zip": "90026",
            "address1": "3110 Sunset Boulevard",
        }
    )

    assert billing["country"] == "US"
    assert billing["state"] in bind_executor.TAX_FREE_US_STATES
    assert billing["state"] != "CA"
    assert billing["address1"]
    assert billing["city"]
    assert billing["zip"]

def test_run_bind_task_fills_generated_tax_free_billing_address(monkeypatch):
    filled = []

    class FakeLocator:
        def __init__(self, label):
            self.label = label

        def click(self, **_kwargs):
            pass

        def fill(self, value, **_kwargs):
            filled.append((self.label, value))

    class FakePage:
        url = "https://chatgpt.com/checkout/openai_llc/cs_test"

        def goto(self, *_args, **_kwargs):
            pass

    class FakeApi:
        def __init__(self):
            self.page = FakePage()
            self.context = object()
            self.oai_device_id = ""

        def _launch_browser(self, **_kwargs):
            pass

        def _wait_for_cloudflare(self):
            pass

        def stop(self):
            pass

    def locator_from_selectors(_api, selectors, timeout_ms=4000):
        if selectors == bind_executor.SUBMIT_SELECTORS:
            return FakeLocator("subscribe")
        if selectors == bind_executor.CARD_NUMBER_SELECTORS:
            return FakeLocator("card")
        if selectors == bind_executor.EXPIRY_SELECTORS:
            return FakeLocator("expiry")
        if selectors == bind_executor.CVC_SELECTORS:
            return FakeLocator("cvc")
        if selectors == bind_executor.NAME_SELECTORS:
            return FakeLocator("name")
        if selectors == bind_executor.ADDRESS_SELECTORS:
            return FakeLocator("address")
        if selectors == bind_executor.CITY_SELECTORS:
            return FakeLocator("city")
        if selectors == bind_executor.STATE_SELECTORS:
            return FakeLocator("state")
        if selectors == bind_executor.POSTAL_CODE_SELECTORS:
            return FakeLocator("postal")
        if selectors == bind_executor.COUNTRY_SELECTORS:
            return FakeLocator("country")
        return None

    monkeypatch.setattr(bind_executor, "ChatGPTTeamAPI", FakeApi)
    monkeypatch.setattr(
        bind_executor,
        "load_auth_session",
        lambda _email: {
            "sessionToken": "session-token",
            "cookie_header": "__Secure-next-auth.session-token=session-token",
        },
        raising=False,
    )
    monkeypatch.setattr(
        bind_executor.chatgpt_session_service,
        "inject_chatgpt_browser_cookies",
        lambda *_args, **_kwargs: None,
        raising=False,
    )
    monkeypatch.setattr(bind_executor, "_capture_screenshot", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(bind_executor, "_locator_from_selectors", locator_from_selectors)
    monkeypatch.setattr(
        bind_executor,
        "generate_tax_free_billing_address",
        lambda: {
            "name": "Generated User",
            "country": "US",
            "state": "OR",
            "city": "Portland",
            "zip": "97201",
            "address1": "800 SW 5th Ave",
            "address2": "",
            "phone_number": "503-555-0182",
        },
    )
    monkeypatch.setattr(
        bind_executor,
        "_wait_for_checkout_result",
        lambda *_args, **_kwargs: {"status": "success", "message": "ok", "screenshot_paths": []},
    )

    result = bind_executor.run_bind_task(
        email="user@example.com",
        checkout_url="https://chatgpt.com/checkout/openai_llc/cs_test",
        card_item={
            "value": "4242424242424242",
            "meta": {
                "content": {
                    "expiry_date": "12/30",
                    "cvv": "123",
                    "name": "Jane Doe",
                    "address": "123 Main St, New York NY 10001, US",
                }
            },
        },
    )

    assert result["status"] == "success"
    assert ("address", "800 SW 5th Ave") in filled
    assert ("city", "Portland") in filled
    assert ("state", "OR") in filled
    assert ("postal", "97201") in filled
    assert ("country", "US") in filled
    assert ("address", "123 Main St") not in filled

def test_run_bind_task_fills_billing_address_once_after_card_fields(monkeypatch):
    filled = []
    launch_kwargs = {}

    class FakeLocator:
        def __init__(self, label):
            self.label = label

        def click(self, **_kwargs):
            pass

        def fill(self, value, **_kwargs):
            filled.append((self.label, value))

    class FakePage:
        url = "https://chatgpt.com/checkout/openai_llc/cs_test"

        def goto(self, *_args, **_kwargs):
            pass

    class FakeApi:
        def __init__(self):
            self.page = FakePage()
            self.context = object()
            self.oai_device_id = ""

        def _launch_browser(self, **_kwargs):
            launch_kwargs.update(_kwargs)

        def _wait_for_cloudflare(self):
            pass

        def stop(self):
            pass

    def locator_from_selectors(_api, selectors, timeout_ms=4000):
        labels = {
            id(bind_executor.SUBMIT_SELECTORS): "subscribe",
            id(bind_executor.CARD_NUMBER_SELECTORS): "card",
            id(bind_executor.EXPIRY_SELECTORS): "expiry",
            id(bind_executor.CVC_SELECTORS): "cvc",
            id(bind_executor.BILLING_NAME_SELECTORS): "billing-name",
            id(bind_executor.COUNTRY_SELECTORS): "country",
            id(bind_executor.ADDRESS_SELECTORS): "address",
            id(bind_executor.CITY_SELECTORS): "city",
            id(bind_executor.STATE_SELECTORS): "state",
            id(bind_executor.POSTAL_CODE_SELECTORS): "postal",
        }
        label = labels.get(id(selectors))
        return FakeLocator(label) if label else None

    monkeypatch.setattr(bind_executor, "ChatGPTTeamAPI", FakeApi)
    monkeypatch.setattr(
        bind_executor,
        "load_auth_session",
        lambda _email: {
            "sessionToken": "session-token",
            "cookie_header": "__Secure-next-auth.session-token=session-token",
        },
        raising=False,
    )
    monkeypatch.setattr(
        bind_executor.chatgpt_session_service,
        "inject_chatgpt_browser_cookies",
        lambda *_args, **_kwargs: None,
        raising=False,
    )
    monkeypatch.setattr(bind_executor, "_capture_screenshot", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(bind_executor, "_locator_from_selectors", locator_from_selectors)
    monkeypatch.setattr(
        bind_executor,
        "generate_tax_free_billing_address",
        lambda: {
            "name": "Generated User",
            "country": "US",
            "state": "OR",
            "city": "Portland",
            "zip": "97201",
            "address1": "800 SW 5th Ave",
        },
    )
    monkeypatch.setattr(bind_executor, "_nudge_billing_address_recalculation", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        bind_executor,
        "_wait_for_checkout_result",
        lambda *_args, **_kwargs: {"status": "success", "message": "ok", "screenshot_paths": []},
    )

    result = bind_executor.run_bind_task(
        email="user@example.com",
        checkout_url="https://chatgpt.com/checkout/openai_llc/cs_test",
        card_item={
            "value": "4242424242424242",
            "meta": {"content": {"expiry_date": "12/30", "cvv": "123"}},
        },
        roxybrowser_profile_id="existing-profile",
    )

    assert result["status"] == "success"
    assert [label for label, _value in filled] == [
        "card",
        "expiry",
        "cvc",
        "billing-name",
        "country",
        "address",
        "city",
        "state",
        "postal",
    ]
    assert launch_kwargs["use_roxybrowser"] is True
    assert launch_kwargs["randomize_fingerprint"] is False
    assert launch_kwargs["roxybrowser_force_new_profile"] is True
    assert launch_kwargs["roxybrowser_profile_id"] is None

def test_run_bind_task_fills_billing_name_without_touching_link_name(monkeypatch):
    filled = []

    class FakeLocator:
        def __init__(self, label):
            self.label = label

        def click(self, **_kwargs):
            pass

        def fill(self, value, **_kwargs):
            filled.append((self.label, value))

    class FakePage:
        url = "https://chatgpt.com/checkout/openai_llc/cs_test"

        def goto(self, *_args, **_kwargs):
            pass

    class FakeApi:
        def __init__(self):
            self.page = FakePage()
            self.context = object()
            self.oai_device_id = ""

        def _launch_browser(self, **_kwargs):
            pass

        def _wait_for_cloudflare(self):
            pass

        def stop(self):
            pass

    def locator_from_selectors(_api, selectors, timeout_ms=4000):
        if selectors == bind_executor.SUBMIT_SELECTORS:
            return FakeLocator("subscribe")
        if selectors == bind_executor.CARD_NUMBER_SELECTORS:
            return FakeLocator("card")
        if selectors == bind_executor.EXPIRY_SELECTORS:
            return FakeLocator("expiry")
        if selectors == bind_executor.CVC_SELECTORS:
            return FakeLocator("cvc")
        if selectors == bind_executor.NAME_SELECTORS:
            return FakeLocator("link-name")
        if selectors == bind_executor.BILLING_NAME_SELECTORS:
            return FakeLocator("billing-name")
        if selectors == bind_executor.COUNTRY_SELECTORS:
            return FakeLocator("country")
        if selectors == bind_executor.ADDRESS_SELECTORS:
            return FakeLocator("address")
        if selectors == bind_executor.CITY_SELECTORS:
            return FakeLocator("city")
        if selectors == bind_executor.STATE_SELECTORS:
            return FakeLocator("state")
        if selectors == bind_executor.POSTAL_CODE_SELECTORS:
            return FakeLocator("postal")
        return None

    monkeypatch.setattr(bind_executor, "ChatGPTTeamAPI", FakeApi)
    monkeypatch.setattr(
        bind_executor,
        "load_auth_session",
        lambda _email: {
            "sessionToken": "session-token",
            "cookie_header": "__Secure-next-auth.session-token=session-token",
        },
        raising=False,
    )
    monkeypatch.setattr(
        bind_executor.chatgpt_session_service,
        "inject_chatgpt_browser_cookies",
        lambda *_args, **_kwargs: None,
        raising=False,
    )
    monkeypatch.setattr(bind_executor, "_capture_screenshot", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(bind_executor, "_locator_from_selectors", locator_from_selectors)
    monkeypatch.setattr(
        bind_executor,
        "generate_tax_free_billing_address",
        lambda: {
            "name": "FREDDIE PACHECO",
            "country": "US",
            "state": "AK",
            "city": "Anchorage",
            "zip": "99503",
            "address1": "1040 West 27th Avenue",
        },
    )
    monkeypatch.setattr(
        bind_executor,
        "_wait_for_checkout_result",
        lambda *_args, **_kwargs: {"status": "success", "message": "ok", "screenshot_paths": []},
    )

    result = bind_executor.run_bind_task(
        email="user@example.com",
        checkout_url="https://chatgpt.com/checkout/openai_llc/cs_test",
        card_item={
            "value": "4242424242424242",
            "meta": {"content": {"expiry_date": "12/30", "cvv": "123"}},
        },
        manual_confirm=False,
    )

    assert result["status"] == "success"
    assert ("link-name", "FREDDIE PACHECO") not in filled
    assert ("billing-name", "FREDDIE PACHECO") in filled

def test_address_line1_selectors_do_not_match_billing_group_name_field():
    joined = "\n".join(bind_executor.ADDRESS_SELECTORS)

    assert 'name*="address"' not in joined
    assert 'id*="address"' not in joined
    assert any("address-line1" in selector for selector in bind_executor.ADDRESS_SELECTORS)

def test_chatgpt_checkout_selectors_include_real_stripe_billing_fields():
    assert "#billingAddress-nameInput" in bind_executor.BILLING_NAME_SELECTORS
    assert bind_executor.BILLING_NAME_SELECTORS.index("#billingAddress-nameInput") < bind_executor.BILLING_NAME_SELECTORS.index('input[name="name"]')
    assert bind_executor.BILLING_NAME_SELECTORS.index("#billingAddress-nameInput") < bind_executor.BILLING_NAME_SELECTORS.index('input[autocomplete="name"]')
    assert "#billingAddress-countryInput" in bind_executor.COUNTRY_SELECTORS
    assert "#billingAddress-addressLine1Input" in bind_executor.ADDRESS_SELECTORS
    assert "#billingAddress-localityInput" in bind_executor.CITY_SELECTORS
    assert "#billingAddress-administrativeAreaInput" in bind_executor.STATE_SELECTORS
    assert 'select[name="administrativeArea"]' in bind_executor.STATE_SELECTORS
    assert "#billingAddress-postalCodeInput" in bind_executor.POSTAL_CODE_SELECTORS

def test_chatgpt_checkout_form_selectors_do_not_depend_on_visible_language():
    selector_groups = (
        bind_executor.CARD_NUMBER_SELECTORS,
        bind_executor.EXPIRY_SELECTORS,
        bind_executor.CVC_SELECTORS,
        bind_executor.NAME_SELECTORS,
        bind_executor.BILLING_NAME_SELECTORS,
        bind_executor.COUNTRY_SELECTORS,
        bind_executor.ADDRESS_SELECTORS,
        bind_executor.CITY_SELECTORS,
        bind_executor.STATE_SELECTORS,
        bind_executor.POSTAL_CODE_SELECTORS,
        bind_executor.SUBMIT_SELECTORS,
    )
    joined = "\n".join(selector for selectors in selector_groups for selector in selectors).lower()

    assert "placeholder" not in joined
    assert "aria-label" not in joined
    assert "has-text" not in joined

def test_locator_from_selectors_respects_selector_priority():
    calls = []

    class FakeApi:
        def _visible_locator_in_frames(self, selectors, timeout_ms=5000):
            calls.append(tuple(selectors))
            if selectors == ["#billingAddress-nameInput"]:
                return "billing-name"
            if selectors == ['input[name="name"]']:
                return "link-name"
            return None

    locator = bind_executor._locator_from_selectors(
        FakeApi(),
        ["#billingAddress-nameInput", 'input[name="name"]'],
        timeout_ms=1000,
    )

    assert locator == "billing-name"
    assert calls[0] == ("#billingAddress-nameInput",)

def test_run_bind_task_auto_mode_clicks_subscribe_after_fill(monkeypatch):
    events = []

    class FakeLocator:
        def __init__(self, label):
            self.label = label

        def click(self, **_kwargs):
            events.append(("click", self.label))

        def fill(self, value, **_kwargs):
            events.append(("fill", self.label, value))

    class FakePage:
        url = "https://chatgpt.com/checkout/openai_llc/cs_test"

        def goto(self, *_args, **_kwargs):
            events.append(("goto", "checkout"))

    class FakeApi:
        def __init__(self):
            self.page = FakePage()
            self.context = object()
            self.oai_device_id = ""

        def _launch_browser(self, **_kwargs):
            pass

        def _wait_for_cloudflare(self):
            pass

        def stop(self):
            pass

    def locator_from_selectors(_api, selectors, timeout_ms=4000):
        if selectors == bind_executor.SUBMIT_SELECTORS:
            return FakeLocator("subscribe")
        if selectors == bind_executor.CARD_NUMBER_SELECTORS:
            return FakeLocator("card")
        if selectors == bind_executor.EXPIRY_SELECTORS:
            return FakeLocator("expiry")
        if selectors == bind_executor.CVC_SELECTORS:
            return FakeLocator("cvc")
        if selectors == bind_executor.NAME_SELECTORS:
            return FakeLocator("name")
        if selectors == bind_executor.COUNTRY_SELECTORS:
            return FakeLocator("country")
        if selectors == bind_executor.ADDRESS_SELECTORS:
            return FakeLocator("address")
        if selectors == bind_executor.CITY_SELECTORS:
            return FakeLocator("city")
        if selectors == bind_executor.STATE_SELECTORS:
            return FakeLocator("state")
        if selectors == bind_executor.POSTAL_CODE_SELECTORS:
            return FakeLocator("postal")
        return None

    monkeypatch.setattr(bind_executor, "ChatGPTTeamAPI", FakeApi)
    monkeypatch.setattr(
        bind_executor,
        "load_auth_session",
        lambda _email: {
            "sessionToken": "session-token",
            "cookie_header": "__Secure-next-auth.session-token=session-token",
        },
        raising=False,
    )
    monkeypatch.setattr(
        bind_executor.chatgpt_session_service,
        "inject_chatgpt_browser_cookies",
        lambda *_args, **_kwargs: None,
        raising=False,
    )
    monkeypatch.setattr(bind_executor, "_capture_screenshot", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(bind_executor, "_locator_from_selectors", locator_from_selectors)
    monkeypatch.setattr(
        bind_executor,
        "generate_tax_free_billing_address",
        lambda: {
            "name": "Generated User",
            "country": "US",
            "state": "OR",
            "city": "Portland",
            "zip": "97201",
            "address1": "800 SW 5th Ave",
        },
    )
    monkeypatch.setattr(
        bind_executor,
        "_wait_for_checkout_result",
        lambda *_args, **_kwargs: {"status": "success", "message": "ok", "screenshot_paths": []},
    )

    result = bind_executor.run_bind_task(
        email="user@example.com",
        checkout_url="https://chatgpt.com/checkout/openai_llc/cs_test",
        card_item={
            "value": "4242424242424242",
            "meta": {"content": {"expiry_date": "12/30", "cvv": "123"}},
        },
        manual_confirm=False,
    )

    assert result["status"] == "success"
    assert ("click", "subscribe") in events
    assert events.index(("fill", "postal", "97201")) < events.index(("click", "subscribe"))

def test_submit_selectors_use_technical_attributes_only():
    assert "button[type=\"submit\"]" in bind_executor.SUBMIT_SELECTORS
    assert "input[type=\"submit\"]" in bind_executor.SUBMIT_SELECTORS
    assert not any("has-text" in selector for selector in bind_executor.SUBMIT_SELECTORS)

def test_stripe_runtime_checksums_match_checkout_encoding():
    assert _stripe_js_checksum("pm_1TcY9qC6h1nxGoI3nnzNhtsS") == "qto~d^n0=QU>azbu]]ew#CoPd&m_]}q`U|_Oe}l>DWmcQ=ato?"
    assert _stripe_rv_timestamp().startswith("qto>n<Q=U&CyY&`>X^r<YNr<YN`")

def _stripe_confirm_init_ctx(raw=None):
    return {
        "raw": raw or {},
        "init_checksum": "init_123",
        "stripe_js_id": "stripe_js_123",
        "elements_session_id": "elements_session_123",
        "elements_session_config_id": "elements_config_123",
        "expected_amount": "299000",
        "currency": "idr",
        "return_url": "https://chatgpt.com/checkout/verify",
        "locale": "en",
    }

def test_stripe_confirm_accepts_terms_when_required_by_init():
    http = FakeHttp(
        [
            ("POST", "/v1/payment_pages/cs_test/confirm", FakeResponse(json_data={"payment_status": "open"})),
        ]
    )
    charger = GoPayHttpCharger(
        http=http,
        phone_number="+6287761973970",
        gopay_pin="558023",
        otp_provider=lambda: "123456",
    )

    payload = charger._stripe_confirm(
        "cs_test",
        "pm_test",
        "pk_test",
        init_ctx=_stripe_confirm_init_ctx({"consent_collection": {"terms_of_service": "required"}}),
    )

    assert payload["payment_status"] == "open"
    assert http.requests[0]["kwargs"]["data"]["consent[terms_of_service]"] == "accepted"

def test_stripe_confirm_retries_with_terms_consent_when_stripe_requires_it():
    http = FakeHttp(
        [
            (
                "POST",
                "/v1/payment_pages/cs_test/confirm",
                FakeResponse(
                    status_code=400,
                    text='{"error":{"message":"Please accept the merchant\'s terms of service before checking out."}}',
                ),
            ),
            ("POST", "/v1/payment_pages/cs_test/confirm", FakeResponse(json_data={"payment_status": "open"})),
        ]
    )
    progress_events = []
    init_ctx = _stripe_confirm_init_ctx()
    charger = GoPayHttpCharger(
        http=http,
        phone_number="+6287761973970",
        gopay_pin="558023",
        otp_provider=lambda: "123456",
        progress_callback=progress_events.append,
    )

    payload = charger._stripe_confirm("cs_test", "pm_test", "pk_test", init_ctx=init_ctx)

    assert payload["payment_status"] == "open"
    assert len(http.requests) == 2
    assert http.requests[1]["kwargs"]["data"]["consent[terms_of_service]"] == "accepted"
    assert init_ctx["include_terms_of_service_consent"] is True
    assert any(event["stage"] == "stripe_confirm_retry_terms" for event in progress_events)

def test_gopay_http_charger_approve_callback_uses_blocked_guidance():
    payload = {"result": "blocked"}
    progress_events = []
    charger = GoPayHttpCharger(
        http=FakeHttp([]),
        phone_number="+6287761973970",
        gopay_pin="558023",
        otp_provider=lambda: "123456",
        approve_callback=lambda _session_id: payload,
        progress_callback=progress_events.append,
    )

    with pytest.raises(GoPayFlowError) as exc:
        charger._approve_checkout("cs_test")

    assert exc.value.stage == "chatgpt_approve"
    assert str(exc.value) == gopay_executor._chatgpt_approve_blocked_message(payload)
    assert any(event["stage"] == "chatgpt_approve" for event in progress_events)

def test_gopay_http_request_wraps_dns_failure_with_stage():
    http = FakeHttp(
        [
            (
                "GET",
                "app.midtrans.com",
                RuntimeError(
                    "Failed to perform, curl: (6) Could not resolve host: app.midtrans.com. "
                    "See https://curl.se/libcurl/c/libcurl-errors.html first for more details."
                ),
            ),
            (
                "GET",
                "app.midtrans.com",
                RuntimeError(
                    "Failed to perform, curl: (6) Could not resolve host: app.midtrans.com. "
                    "See https://curl.se/libcurl/c/libcurl-errors.html first for more details."
                ),
            ),
        ]
    )
    charger = GoPayHttpCharger(
        http=http,
        phone_number="+6287761973970",
        gopay_pin="558023",
        otp_provider=lambda: "123456",
    )

    try:
        charger._request(
            "GET", "https://app.midtrans.com/snap/v1/transactions/token", stage="midtrans_load_transaction"
        )
    except GoPayFlowError as exc:
        assert exc.stage == "midtrans_load_transaction"
        assert "Could not resolve host: app.midtrans.com" in str(exc)
    else:
        raise AssertionError("expected DNS failure to be wrapped as GoPayFlowError")

    assert len(http.requests) == 2

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
    assert config.normalize_proxy_url(raw, default_auth_scheme="socks5h") == (
        "socks5h://user-region-US-st-Delaware-city-Dewey%20Beach-sid-abc:secret@us.1024proxy.io:3000"
    )

def test_get_playwright_launch_options_normalizes_schemed_colon_proxy_with_spaces():
    raw = "socks5://us.1024proxy.io:3000:user-region-US-st-Delaware-city-Dewey Beach-sid-abc:secret"

    options = config.get_playwright_launch_options(proxy_url=raw)

    assert options["proxy"] == {
        "server": "http://us.1024proxy.io:3000",
        "username": "user-region-US-st-Delaware-city-Dewey Beach-sid-abc",
        "password": "secret",
    }
    assert config.normalize_proxy_url(raw) == (
        "socks5://user-region-US-st-Delaware-city-Dewey%20Beach-sid-abc:secret@us.1024proxy.io:3000"
    )

def test_normalize_proxy_url_supports_common_import_formats():
    assert config.normalize_proxy_url("proxy.example:9999:user:pass") == ("http://user:pass@proxy.example:9999")
    assert config.normalize_proxy_url("socks5://user:pass@proxy.example:9999") == (
        "socks5://user:pass@proxy.example:9999"
    )
    assert config.normalize_proxy_url("user:pass@proxy.example:9999") == ("http://user:pass@proxy.example:9999")
    assert config.normalize_proxy_url("proxy.example:9999@user:pass") == ("http://user:pass@proxy.example:9999")

def test_normalize_proxy_url_can_treat_unschemed_auth_formats_as_socks5h():
    assert config.normalize_proxy_url("us.1024proxy.io:3000:user:pass", default_auth_scheme="socks5h") == (
        "socks5h://user:pass@us.1024proxy.io:3000"
    )
    assert config.normalize_proxy_url("user:pass@us.1024proxy.io:3000", default_auth_scheme="socks5h") == (
        "socks5h://user:pass@us.1024proxy.io:3000"
    )
    assert config.normalize_proxy_url("us.1024proxy.io:3000@user:pass", default_auth_scheme="socks5h") == (
        "socks5h://user:pass@us.1024proxy.io:3000"
    )

def test_normalize_proxy_url_socks5h_default_is_provider_agnostic():
    raw = "us2.cliproxy.io:3010:user-region-US-st-California-city-Los Angeles-sid-abc-t-120:secret"

    assert config.normalize_proxy_url(raw, default_auth_scheme="socks5h") == (
        "socks5h://user-region-US-st-California-city-Los%20Angeles-sid-abc-t-120:secret@us2.cliproxy.io:3010"
    )

def test_playwright_socks_bridge_wraps_unauthenticated_socks_proxy():
    bridge = proxy_bridge.start_playwright_socks_bridge("socks5h://127.0.0.1:1080")
    try:
        assert bridge is not None
        assert bridge.upstream_url == "socks5h://127.0.0.1:1080"
        assert bridge.proxy_url.startswith("http://127.0.0.1:")
    finally:
        if bridge:
            bridge.stop()

def test_camoufox_uses_unauthenticated_socks_proxy_without_bridge():
    effective_proxy, bridge = chatgpt_api._camoufox_effective_proxy_url("socks5h://127.0.0.1:1080")

    assert effective_proxy == "socks5h://127.0.0.1:1080"
    assert bridge is None

def test_camoufox_uses_imported_http_proxy_without_bridge():
    effective_proxy, bridge = chatgpt_api._camoufox_effective_proxy_url("proxy.example:9999:user:pass")

    assert effective_proxy == "proxy.example:9999:user:pass"
    assert bridge is None

def test_camoufox_bridges_explicit_authenticated_socks_proxy():
    effective_proxy, bridge = chatgpt_api._camoufox_effective_proxy_url("socks5h://user:pass@127.0.0.1:1080")
    try:
        assert bridge is not None
        assert effective_proxy == bridge.proxy_url
    finally:
        if bridge:
            bridge.stop()

def test_camoufox_launch_disables_geoip_proxy_preflight(monkeypatch):
    captured = {}

    class FakeContext:
        pages = []

        def new_page(self):
            return object()

    class FakeCamoufox:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def __enter__(self):
            return FakeContext()

    monkeypatch.setitem(sys.modules, "camoufox", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "camoufox.sync_api", types.SimpleNamespace(Camoufox=FakeCamoufox))

    api = chatgpt_api.ChatGPTTeamAPI()
    api._temp_user_data_dir = "tmp-camoufox-profile"
    api._launch_browser_camoufox(effective_proxy_url="socks5://127.0.0.1:1080")

    assert captured["proxy"] == {"server": "socks5://127.0.0.1:1080"}
    assert captured["geoip"] is False

def test_roxybrowser_relaunch_cleans_active_runtime_before_start(monkeypatch):
    calls = []

    class OldContext:
        def close(self):
            calls.append("old_context_close")

    class OldBrowser:
        def close(self):
            calls.append("old_browser_close")

    class OldPlaywright:
        def stop(self):
            calls.append("old_playwright_stop")

    class OldClient:
        def browser_close(self, dir_id):
            calls.append(("old_roxy_close", dir_id))

        def browser_delete(self, workspace_id, dir_ids):
            calls.append(("old_roxy_delete", workspace_id, dir_ids))

    class FakeLaunch:
        dir_id = "new-dir"
        workspace_id = "new-workspace"
        created_profile = True
        reused_existing_profile = False
        requested_os = "IOS"
        requested_os_version = "18.2"
        connection = {"http": "127.0.0.1:54510"}

    class FakeClient:
        def __init__(self, api_host, api_token):
            pass

        def launch(self, **kwargs):
            calls.append("new_roxy_launch")
            return FakeLaunch()

    class FakePage:
        def evaluate(self, _script):
            return {"platform": "iPhone", "user_agent": "iPhone", "max_touch_points": 5}

    class FakeContext:
        pages = [FakePage()]

    class FakeBrowser:
        contexts = [FakeContext()]

    class FakeChromium:
        def connect_over_cdp(self, **kwargs):
            calls.append("new_roxy_connect")
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    def start_playwright():
        calls.append("new_playwright_start")
        assert "old_playwright_stop" in calls
        return FakePlaywright()

    monkeypatch.setattr(
        chatgpt_api, "get_roxybrowser_config", lambda: {"api_host": "http://roxy", "api_token": "token"}
    )
    monkeypatch.setattr(chatgpt_api, "RoxyBrowserClient", FakeClient)
    monkeypatch.setattr(chatgpt_api, "sync_playwright", lambda: types.SimpleNamespace(start=start_playwright))

    api = chatgpt_api.ChatGPTTeamAPI()
    api.context = OldContext()
    api.browser = OldBrowser()
    api.page = object()
    api.playwright = OldPlaywright()
    api._roxybrowser_client = OldClient()
    api._roxybrowser_dir_id = "old-dir"
    api._roxybrowser_workspace_id = "old-workspace"
    api._roxybrowser_created_dir = True

    api._launch_browser_roxybrowser(force_new_profile=True)

    assert calls[:6] == [
        "old_context_close",
        "old_browser_close",
        ("old_roxy_close", "old-dir"),
        ("old_roxy_delete", "old-workspace", ["old-dir"]),
        "old_playwright_stop",
        "new_roxy_launch",
    ]
    assert calls.index("old_playwright_stop") < calls.index("new_playwright_start")
    assert api._roxybrowser_dir_id == "new-dir"
    assert api.page is not None

def test_get_playwright_launch_options_rewrites_authenticated_socks5_for_chromium():
    options = config.get_playwright_launch_options(
        proxy_url="socks5://user name:pass@socks.example:1080",
    )

    assert options["proxy"] == {
        "server": "http://socks.example:1080",
        "username": "user name",
        "password": "pass",
    }

def test_get_playwright_launch_options_preserves_unauthenticated_socks5_scheme():
    options = config.get_playwright_launch_options(
        proxy_url="socks5://socks.example:1080",
    )

    assert options["proxy"] == {
        "server": "socks5://socks.example:1080",
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

def test_approve_checkout_http_uses_reference_style_session_headers(monkeypatch):
    http = FakeHttp(
        [
            ("POST", "/backend-api/sentinel/ping", FakeResponse(json_data={})),
            ("POST", "/backend-api/payments/checkout/approve", FakeResponse(json_data={"result": "approved"})),
        ]
    )
    monkeypatch.setattr(
        gopay_executor,
        "_checkout_approval_sentinel_headers",
        lambda **kwargs: {"OpenAI-Sentinel-Token": "checkout-sentinel", "OAI-Telemetry": "[1,null]"},
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
    approve_headers = approve_request["kwargs"]["headers"]
    assert approve_headers["authorization"] == "Bearer access"
    assert approve_headers["cookie"] == "__Secure-next-auth.session-token=session"
    assert approve_headers["oai-device-id"] == "device"
    assert approve_headers["chatgpt-account-id"] == "account"
    assert approve_headers["x-openai-target-path"] == "/backend-api/payments/checkout/approve"
    assert approve_headers["OpenAI-Sentinel-Token"] == "checkout-sentinel"
    assert http.headers["Authorization"] == "Bearer access"
    assert http.headers["Cookie"] == "__Secure-next-auth.session-token=session; _account=account; oai-did=device"
    assert http.headers["oai-device-id"] == "device"
    assert http.headers["openai-sentinel-token"] == "sentinel"

def test_inject_chatgpt_browser_cookies_splits_large_session_cookie_from_header():
    class FakeContext:
        def __init__(self):
            self.cookies = []

        def add_cookies(self, cookies):
            self.cookies.extend(cookies)

    class FakeApi:
        def __init__(self):
            self.context = FakeContext()

    api = FakeApi()
    session_value = "x" * 4200

    gopay_executor._inject_chatgpt_browser_cookies(
        api,
        cookie_header=(
            f"__Secure-next-auth.session-token={session_value}; "
            "Path=/; SameSite=Lax; HttpOnly; malformed name=value; small=ok"
        ),
        account_id="account",
        device_id="device",
    )

    cookie_by_name = {cookie["name"]: cookie for cookie in api.context.cookies}
    assert "__Secure-next-auth.session-token" not in cookie_by_name
    assert cookie_by_name["__Secure-next-auth.session-token.0"]["value"] == "x" * 3800
    assert cookie_by_name["__Secure-next-auth.session-token.1"]["value"] == "x" * 400
    assert "Path" not in cookie_by_name
    assert "SameSite" not in cookie_by_name
    assert "malformed name" not in cookie_by_name
    assert cookie_by_name["small"]["value"] == "ok"
    assert cookie_by_name["_account"]["value"] == "account"
    assert cookie_by_name["oai-did"]["value"] == "device"

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

def test_fetch_sms_code_skips_ignored_old_otp(monkeypatch):
    class SmsResponse:
        ok = True
        status_code = 200
        text = '{"code":1,"data":{"messages":[{"text":"OpenAI OTP: 111111"},{"text":"OpenAI OTP: 222222"}]}}'

    monkeypatch.setattr(gopay_executor.requests, "get", lambda *_args, **_kwargs: SmsResponse())

    assert gopay_executor._fetch_sms_code("https://sms.example.test", ignored_otps={"111111"}) == "222222"

def test_fetch_sms_code_waits_when_only_ignored_otp_is_available(monkeypatch):
    class SmsResponse:
        ok = True
        status_code = 200
        text = '{"code":1,"data":{"code":"OpenAI OTP: 111111"}}'

    monkeypatch.setattr(gopay_executor.requests, "get", lambda *_args, **_kwargs: SmsResponse())

    try:
        gopay_executor._fetch_sms_code("https://sms.example.test", ignored_otps={"111111"})
    except RuntimeError as exc:
        assert "旧验证码" in str(exc)
    else:
        raise AssertionError("expected ignored-only OTP response to wait for a new code")

def test_fetch_whatsapp_sms_code_prefers_latest_otp_field(monkeypatch):
    class Listener:
        def latest_response(self, *, max_age_seconds=600):
            return {
                "code": 1,
                "data": {
                    "otp": "493828",
                    "code": "GoPay 493828 is your verification code.",
                    "messages": [
                        {"code": "751104", "raw": "GoPay 751104 is your verification code."},
                        {"code": "493828", "raw": "GoPay 493828 is your verification code."},
                    ],
                },
            }

    monkeypatch.setattr("autotoken.whatsapp_otp.get_default_listener", lambda: Listener())

    assert gopay_executor._fetch_sms_code("http://127.0.0.1:8787/otp/whatsapp/latest") == "493828"

def test_poll_otp_waits_sms_window_before_fetch(monkeypatch):
    sleeps = []
    fetches = []
    progress_events = []
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(gopay_executor, "_fetch_sms_code", lambda url, **_kwargs: fetches.append(url) or "123456")

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

    def fake_fetch(_url, **_kwargs):
        return "123456" if now[0] >= 125 else ""

    monkeypatch.setattr(gopay_executor, "_fetch_sms_code", fake_fetch)

    provider = _poll_otp_from_sms_url(
        "https://sms.example.test",
        timeout_seconds=180,
        initial_delay_seconds=0,
        resend_after_seconds=120,
        progress=lambda stage, **extra: progress_events.append({"stage": stage, **extra}),
    )
    provider._gopay_resend_callback = lambda: resend_calls.append(now[0])

    assert provider() == "123456"
    assert resend_calls == [120.0]
    assert {"stage": "sms_otp_resend_due", "wait_seconds": 120} in progress_events

def test_poll_otp_triggers_sms_bridge_resend_after_gopay_resend(monkeypatch):
    now = [0.0]
    operations = []
    progress_events = []

    monkeypatch.setattr(gopay_executor.time, "time", lambda: now[0])
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    monkeypatch.delenv("AUTOTOKEN_LOCAL_BASE_URL", raising=False)
    monkeypatch.setenv("GOPAY_SMS_PROVIDER_RESEND_DELAY_SECONDS", "0")

    def fake_fetch(_url, **_kwargs):
        return "123456" if now[0] >= 65 else ""

    def fake_get(url, **_kwargs):
        operations.append(("bridge", now[0], url))
        return FakeResponse(text='{"ok": false, "data": {"status": "pending"}}')

    monkeypatch.setattr(gopay_executor, "_fetch_sms_code", fake_fetch)
    monkeypatch.setattr(gopay_executor.requests, "get", fake_get)

    provider = _poll_otp_from_sms_url(
        "http://127.0.0.1:8787/otp/gopay-signup/demo?foo=bar",
        timeout_seconds=180,
        initial_delay_seconds=0,
        resend_after_seconds=60,
        progress=lambda stage, **extra: progress_events.append({"stage": stage, **extra}),
    )
    provider._gopay_resend_callback = lambda: operations.append(("gopay", now[0], ""))

    assert provider() == "123456"
    assert operations[:2] == [
        ("bridge", 60.0, "http://127.0.0.1:8787/otp/gopay-signup/demo?foo=bar&resend=1"),
        ("gopay", 60.0, ""),
    ]
    assert {"stage": "sms_provider_resend_triggered"} in progress_events

def test_local_gopay_signup_bridge_url_uses_configured_base(monkeypatch):
    monkeypatch.setenv("AUTOTOKEN_LOCAL_BASE_URL", "http://127.0.0.1:8989")

    assert (
        gopay_executor._gopay_signup_bridge_resend_url("http://127.0.0.1:8787/otp/gopay-signup/demo?foo=bar")
        == "http://127.0.0.1:8989/otp/gopay-signup/demo?foo=bar&resend=1"
    )

def test_fetch_sms_code_rewrites_stale_local_gopay_signup_port(monkeypatch):
    captured = {}
    monkeypatch.setenv("AUTOTOKEN_LOCAL_BASE_URL", "http://127.0.0.1:8989")

    def fake_get(url, **_kwargs):
        captured["url"] = url
        return FakeResponse(text='{"ok": true, "data": {"otp": "654321"}}')

    monkeypatch.setattr(gopay_executor.requests, "get", fake_get)

    assert gopay_executor._fetch_sms_code("http://127.0.0.1:8787/otp/gopay-signup/demo") == "654321"
    assert captured["url"] == "http://127.0.0.1:8989/otp/gopay-signup/demo"

def test_poll_otp_stops_after_max_resend_attempts(monkeypatch):
    now = [0.0]
    resend_calls = []

    monkeypatch.setattr(gopay_executor.time, "time", lambda: now[0])
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    monkeypatch.setattr(gopay_executor, "_fetch_sms_code", lambda *_args, **_kwargs: "")

    provider = _poll_otp_from_sms_url(
        "http://127.0.0.1:8787/otp/whatsapp/latest",
        timeout_seconds=600,
        initial_delay_seconds=0,
        resend_after_seconds=60,
        max_resend_attempts=3,
    )
    provider._gopay_resend_callback = lambda: resend_calls.append(now[0])

    try:
        provider()
    except GoPayOTPCancelled as exc:
        assert "上限 3 次" in str(exc)
    else:
        raise AssertionError("expected OTP polling to stop after max resend attempts")

    assert resend_calls == [60.0, 120.0, 180.0]

def test_extract_checkout_session_id_from_response_or_url():
    assert _extract_checkout_session_id(raw={"checkout_session_id": "cs_test_123"}) == "cs_test_123"
    assert _extract_checkout_session_id("https://chatgpt.com/checkout/openai_llc/cs_live_abc") == "cs_live_abc"
    assert (
        _extract_checkout_session_id("https://pay.openai.com/c/pay/cs_live_a1Hosted123#fid=test")
        == "cs_live_a1Hosted123"
    )

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

    monkeypatch.setattr(
        gopay_executor,
        "_body_excerpt",
        lambda api, limit: "Subtotal Rp349.000 Discount -Rp349.000 Total payment Rp1",
    )
    assert _browser_checkout_nonzero_amount_hint(FakeApi()) == "Rp1"

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
            *_stripe_address_update_responses(),
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
            ("POST", "/v1/linking/resend-otp", FakeResponse(json_data={"success": True})),
            (
                "POST",
                "/v1/linking/validate-otp",
                FakeResponse(
                    json_data={
                        "success": True,
                        "data": {
                            "challenge": {
                                "action": {"value": {"challenge_id": "challenge_link", "client_id": "client_link"}}
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
                                "action": {"value": {"challenge_id": "challenge_pay", "client_id": "client_pay"}}
                            }
                        },
                    }
                ),
            ),
            ("POST", "/api/v1/users/pin/tokens/nb", FakeResponse(json_data={"token": "pin_pay"})),
            (
                "POST",
                "/v1/payment/process",
                FakeResponse(json_data={"success": True, "data": {"next_action": "payment-success"}}),
            ),
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
    assert sms_triggers == []
    linking_request = next(request for request in http.requests if request["url"].endswith("/linking"))
    assert json.loads(linking_request["kwargs"]["data"].decode("utf-8")) == {
        "type": "gopay",
        "country_code": "62",
        "phone_number": "87761973970",
    }
    linking_headers = linking_request["kwargs"]["headers"]
    assert linking_headers["X-Source"] == "snap"
    assert linking_headers["X-Source-App-Type"] == "redirection"
    assert linking_headers["X-Source-Version"] == "2.3.0"
    assert linking_headers["X-Snap-Signature"]
    assert linking_headers["X-Timestamp"]
    assert any(event["stage"] == "gopay_payment_process" for event in progress_events)
    payment_method_request = next(
        request for request in http.requests if request["url"].endswith("/v1/payment_methods")
    )
    assert (
        payment_method_request["kwargs"]["data"]["client_attribution_metadata[elements_session_id]"]
        == "elements_session_real"
    )
    assert (
        payment_method_request["kwargs"]["data"]["client_attribution_metadata[checkout_config_id]"]
        == "checkout_config_real"
    )
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
            *_stripe_address_update_responses(),
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
            ("POST", "/v1/linking/resend-otp", FakeResponse(json_data={"success": True})),
            (
                "POST",
                "/v1/linking/validate-otp",
                FakeResponse(
                    json_data={
                        "success": True,
                        "data": {
                            "challenge": {
                                "action": {"value": {"challenge_id": "challenge_link", "client_id": "client_link"}}
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
                                "action": {"value": {"challenge_id": "challenge_pay", "client_id": "client_pay"}}
                            }
                        },
                    }
                ),
            ),
            ("POST", "/api/v1/users/pin/tokens/nb", FakeResponse(json_data={"token": "pin_pay"})),
            (
                "POST",
                "/v1/payment/process",
                FakeResponse(json_data={"success": True, "data": {"next_action": "payment-success"}}),
            ),
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

def test_gopay_resolve_snap_token_polls_open_checkout_without_approve(monkeypatch):
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda *args, **kwargs: None)

    snap_token = "11111111-1111-4111-8111-111111111111"
    open_page = FakeResponse(json_data={"payment_status": "unpaid", "status": "open"})
    redirect_page = FakeResponse(
        json_data={
            "setup_intent": {
                "status": "requires_action",
                "next_action": {
                    "type": "redirect_to_url",
                    "redirect_to_url": {"url": "https://pm-redirects.stripe.com/authorize/after-approve"},
                },
            }
        }
    )
    http = FakeHttp(
        [
            ("GET", "/v1/payment_pages/cs_test", open_page),
            ("GET", "/v1/payment_pages/cs_test", open_page),
            ("GET", "/v1/payment_pages/cs_test", open_page),
            ("GET", "/v1/payment_pages/cs_test", redirect_page),
            (
                "GET",
                "pm-redirects.stripe.com/authorize/after-approve",
                FakeResponse(
                    status_code=302,
                    headers={"Location": f"https://app.midtrans.com/snap/v4/redirection/{snap_token}"},
                ),
            ),
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
        progress_callback=progress_events.append,
    )

    assert charger._resolve_snap_token("cs_test", "pk_test") == snap_token
    assert approved == []
    assert not any(event["stage"] == "chatgpt_approve" for event in progress_events)
    assert http.responses == []

def test_gopay_extract_redirect_url_finds_nested_midtrans_redirect():
    payload = {
        "payment_status": "unpaid",
        "status": "open",
        "session": {
            "checkout": {
                "external_redirect": {
                    "url": "https://pm-redirects.stripe.com/authorize/nested",
                }
            }
        },
    }

    assert GoPayHttpCharger._extract_redirect_url(payload) == "https://pm-redirects.stripe.com/authorize/nested"

def test_gopay_http_charger_uses_transaction_midtrans_client_key(monkeypatch):
    snap_token = "11111111-1111-4111-8111-111111111111"
    reference_id = "22222222-2222-4222-8222-222222222222"
    client_key = "Mid-client-from-transaction"
    http = FakeHttp(
        [
            (
                "GET",
                f"/snap/v1/transactions/{snap_token}",
                FakeResponse(json_data={"merchant": {"client_key": client_key}}),
            ),
            (
                "POST",
                f"/snap/v3/accounts/{snap_token}/linking",
                FakeResponse(
                    status_code=201,
                    json_data={"activation_link_url": f"https://gopay.local/link?reference={reference_id}"},
                ),
            ),
        ]
    )
    charger = GoPayHttpCharger(
        http=http,
        phone_number="+6287761973970",
        gopay_pin="558023",
        otp_provider=lambda: "123456",
        midtrans_client_id="old-client-key",
    )
    monkeypatch.setattr(charger, "_gopay_validate_reference", lambda reference: None)
    monkeypatch.setattr(charger, "_gopay_user_consent", lambda reference: None)
    monkeypatch.setattr(charger, "_trigger_linking_otp_channel", lambda reference: None)
    monkeypatch.setattr(charger, "_gopay_validate_otp", lambda reference, otp: ("challenge_link", "client_link"))
    monkeypatch.setattr(charger, "_tokenize_pin", lambda challenge_id, client_id: "pin_token")
    monkeypatch.setattr(charger, "_gopay_validate_pin", lambda reference, pin_token: None)
    monkeypatch.setattr(charger, "_midtrans_create_charge", lambda token: "charge_ref")
    monkeypatch.setattr(charger, "_gopay_payment_validate", lambda charge_ref: None)
    monkeypatch.setattr(charger, "_gopay_payment_confirm", lambda charge_ref: ("challenge_pay", "client_pay"))
    monkeypatch.setattr(charger, "_gopay_payment_process", lambda charge_ref, pin_token: None)

    result = charger.run_from_snap_token(snap_token=snap_token, checkout_session_id="cs_test")

    link_request = next(request for request in http.requests if request["url"].endswith("/linking"))
    expected_auth = "Basic " + gopay_executor.base64.b64encode(f"{client_key}:".encode("ascii")).decode("ascii")
    assert result["state"] == "succeeded"
    assert link_request["kwargs"]["headers"]["Authorization"] == expected_auth

def test_midtrans_charge_denied_is_payment_process_failure():
    payload = {
        "status_code": "202",
        "status_message": "Your transaction is denied. Please try again or try another payment method.",
        "transaction_status": "deny",
        "fraud_status": "deny",
        "payment_type": "gopay",
    }
    http = FakeHttp(
        [
            (
                "POST",
                "/snap/v2/transactions/snap-token/charge",
                FakeResponse(status_code=202, json_data=payload),
            ),
        ]
    )
    charger = GoPayHttpCharger(
        http=http,
        phone_number="+6287761973970",
        gopay_pin="558023",
        otp_provider=lambda: "123456",
    )

    with pytest.raises(GoPayFlowError) as exc:
        charger._midtrans_create_charge("snap-token")

    assert exc.value.stage == "gopay_payment_process"
    assert "transaction is denied" in str(exc.value)

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
                FakeResponse(
                    status_code=201,
                    json_data={"activation_link_url": f"https://gopay.local/link?reference={reference_id}"},
                ),
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
                                "action": {"value": {"challenge_id": "challenge_link", "client_id": "client_link"}}
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
                                "action": {"value": {"challenge_id": "challenge_pay", "client_id": "client_pay"}}
                            }
                        },
                    }
                ),
            ),
            ("POST", "/api/v1/users/pin/tokens/nb", FakeResponse(json_data={"token": "pin_pay"})),
            (
                "POST",
                "/v1/payment/process",
                FakeResponse(json_data={"success": True, "data": {"next_action": "payment-success"}}),
            ),
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

def test_gopay_http_charger_switches_to_sms_without_resend(monkeypatch):
    monkeypatch.setenv("GOPAY_SMS_CHANNEL_SWITCH_ENABLED", "1")
    monkeypatch.setenv("GOPAY_SMS_CHANNEL_SWITCH_DELAY_SECONDS", "0")

    http = FakeHttp(
        [
            ("POST", "/v1/linking/user-consent", FakeResponse(json_data={"success": True})),
        ]
    )
    progress_events = []
    charger = GoPayHttpCharger(
        http=http,
        phone_number="+6287761973970",
        gopay_pin="558023",
        otp_provider=lambda: "123456",
        otp_channel="sms",
        sms_resend_wait_seconds=10,
        progress_callback=progress_events.append,
    )

    charger._trigger_linking_otp_channel("ref_sms_switch")

    assert len(http.requests) == 1
    assert http.requests[0]["url"].endswith("/user-consent")
    assert http.requests[0]["kwargs"]["json"] == {"reference_id": "ref_sms_switch", "otp_channel": "sms"}
    assert not any(request["url"].endswith("/resend-otp") for request in http.requests)
    assert any(event["stage"] == "gopay_sms_channel_switched" for event in progress_events)
    assert any(event["stage"] == "sms_otp_triggered" for event in progress_events)

def test_gopay_http_charger_falls_back_to_resend_when_sms_switch_fails(monkeypatch):
    monkeypatch.setenv("GOPAY_SMS_CHANNEL_SWITCH_ENABLED", "1")
    monkeypatch.setenv("GOPAY_SMS_CHANNEL_SWITCH_DELAY_SECONDS", "0")
    sleeps = []
    monkeypatch.setattr(GoPayHttpCharger, "_sleep_with_cancel", lambda self, seconds: sleeps.append(seconds))

    http = FakeHttp(
        [
            ("POST", "/v1/linking/user-consent", FakeResponse(status_code=400, text="too early")),
            ("POST", "/v1/linking/resend-otp", FakeResponse(json_data={"success": True})),
        ]
    )
    progress_events = []
    charger = GoPayHttpCharger(
        http=http,
        phone_number="+6287761973970",
        gopay_pin="558023",
        otp_provider=lambda: "123456",
        otp_channel="sms",
        sms_resend_wait_seconds=10,
        progress_callback=progress_events.append,
    )

    charger._trigger_linking_otp_channel("ref_sms_fallback")

    assert [request["url"].rsplit("/", 1)[-1] for request in http.requests] == ["user-consent", "resend-otp"]
    assert http.requests[1]["kwargs"]["json"] == {"reference_id": "ref_sms_fallback"}
    assert sleeps == [10.0]
    assert any(event["stage"] == "gopay_sms_channel_switch_failed" for event in progress_events)
    assert any(event["stage"] == "sms_otp_triggered" for event in progress_events)

def test_gopay_http_charger_triggers_sms_provider_before_protocol_otp(monkeypatch):
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda *args, **kwargs: None)
    monkeypatch.setenv("GOPAY_SMS_PROVIDER_RESEND_DELAY_SECONDS", "0")

    snap_token = "11111111-1111-4111-8111-111111111111"
    reference_id = "22222222-2222-4222-8222-222222222222"
    http = FakeHttp(
        [
            ("GET", f"/snap/v1/transactions/{snap_token}", FakeResponse(json_data={"enabled_payments": ["gopay"]})),
            (
                "POST",
                f"/snap/v3/accounts/{snap_token}/linking",
                FakeResponse(
                    status_code=201,
                    json_data={"activation_link_url": f"https://gopay.local/link?reference={reference_id}"},
                ),
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
                                "action": {"value": {"challenge_id": "challenge_link", "client_id": "client_link"}}
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
                                "action": {"value": {"challenge_id": "challenge_pay", "client_id": "client_pay"}}
                            }
                        },
                    }
                ),
            ),
            ("POST", "/api/v1/users/pin/tokens/nb", FakeResponse(json_data={"token": "pin_pay"})),
            (
                "POST",
                "/v1/payment/process",
                FakeResponse(json_data={"success": True, "data": {"next_action": "payment-success"}}),
            ),
        ]
    )
    provider_events = []
    progress_events = []

    def otp_provider():
        return "123456"

    otp_provider._gopay_sms_provider_resend_callback = lambda: provider_events.append(len(http.requests))

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
    resend_index = next(index for index, request in enumerate(http.requests) if request["url"].endswith("/resend-otp"))
    assert provider_events == [resend_index]
    assert any(
        event["stage"] == "sms_provider_resend_triggered" and event.get("reason") == "before_gopay_otp"
        for event in progress_events
    )

def test_gopay_http_charger_whatsapp_channel_does_not_set_resend_callback(monkeypatch):
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda *args, **kwargs: None)

    snap_token = "11111111-1111-4111-8111-111111111111"
    reference_id = "22222222-2222-4222-8222-222222222222"
    http = FakeHttp(
        [
            ("GET", f"/snap/v1/transactions/{snap_token}", FakeResponse(json_data={"enabled_payments": ["gopay"]})),
            (
                "POST",
                f"/snap/v3/accounts/{snap_token}/linking",
                FakeResponse(
                    status_code=201,
                    json_data={"activation_link_url": f"https://gopay.local/link?reference={reference_id}"},
                ),
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
                                "action": {"value": {"challenge_id": "challenge_link", "client_id": "client_link"}}
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
                                "action": {"value": {"challenge_id": "challenge_pay", "client_id": "client_pay"}}
                            }
                        },
                    }
                ),
            ),
            ("POST", "/api/v1/users/pin/tokens/nb", FakeResponse(json_data={"token": "pin_pay"})),
            (
                "POST",
                "/v1/payment/process",
                FakeResponse(json_data={"success": True, "data": {"next_action": "payment-success"}}),
            ),
        ]
    )
    progress_events = []
    otp_callback_present = []

    def otp_provider():
        otp_callback_present.append(callable(getattr(otp_provider, "_gopay_resend_callback", None)))
        return "123456"

    charger = GoPayHttpCharger(
        http=http,
        phone_number="+8615825989172",
        gopay_pin="558023",
        otp_provider=otp_provider,
        otp_channel="whatsapp",
        progress_callback=progress_events.append,
    )

    result = charger.run_from_snap_token(snap_token=snap_token, checkout_session_id="cs_test")

    assert result["state"] == "succeeded"
    assert not any(request["url"].endswith("/resend-otp") for request in http.requests)
    assert any(event["stage"] == "wait_whatsapp_otp" for event in progress_events)
    assert otp_callback_present == [False]
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
                FakeResponse(
                    status_code=201,
                    json_data={"activation_link_url": f"https://gopay.local/link?reference={reference_id}"},
                ),
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
                                "action": {"value": {"challenge_id": "challenge_link", "client_id": "client_link"}}
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
                                "action": {"value": {"challenge_id": "challenge_pay", "client_id": "client_pay"}}
                            }
                        },
                    }
                ),
            ),
            ("POST", "/api/v1/users/pin/tokens/nb", FakeResponse(json_data={"token": "pin_pay"})),
            (
                "POST",
                "/v1/payment/process",
                FakeResponse(json_data={"success": True, "data": {"next_action": "payment-success"}}),
            ),
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

def test_gopay_http_charger_submits_billing_address_by_protocol(monkeypatch):
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda *args, **kwargs: None)
    http = FakeHttp(_stripe_address_update_responses())
    progress_events = []
    charger = GoPayHttpCharger(
        http=http,
        phone_number="+6287761973970",
        gopay_pin="558023",
        otp_provider=lambda: "123456",
        billing_info={
            "country": "ID",
            "address1": "Jl. Sunset Road 8",
            "city": "Denpasar",
            "state": "Bali",
            "zip": "80228",
        },
        progress_callback=progress_events.append,
    )
    init_ctx = {
        "stripe_js_id": "stripe-js",
        "elements_session_id": "elements-session",
        "elements_session_config_id": "elements-config",
        "locale": "en",
        "elements_options_client": {"elements_options_client[stripe_js_locale]": "auto"},
    }

    charger._stripe_update_payment_page_address("cs_test", "pk_test", init_ctx)

    assert len(http.requests) == 6
    step_payloads = [request["kwargs"]["data"] for request in http.requests]
    assert step_payloads[0]["tax_region[country]"] == "ID"
    assert "tax_region[line1]" not in step_payloads[1]
    assert step_payloads[2]["tax_region[line1]"] == "Jl. Sunset Road 8"
    assert step_payloads[3]["tax_region[city]"] == "Denpasar"
    assert step_payloads[4]["tax_region[state]"] == "Bali"
    assert step_payloads[5]["tax_region[postal_code]"] == "80228"
    assert step_payloads[-1]["elements_session_client[session_id]"] == "elements-session"
    assert any(event["stage"] == "stripe_address_update_done" for event in progress_events)

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

def test_gopay_protocol_form_mode_generates_hosted_checkout(monkeypatch):
    progress_events = []
    generated_modes = []
    run_calls = []

    monkeypatch.setenv("GOPAY_CHECKOUT_FORM_MODE", "protocol")
    monkeypatch.setattr(
        gopay_executor,
        "load_auth_session",
        lambda email: {
            "accessToken": "access",
            "sessionToken": "session",
            "account": {"id": "account"},
            "device_id": "device",
        },
    )
    monkeypatch.setattr(gopay_executor, "_build_chatgpt_http_session", lambda **kwargs: object())
    monkeypatch.setattr(gopay_executor, "_new_http_session", lambda *args, **kwargs: object())

    def fake_generate(http, **kwargs):
        generated_modes.append(kwargs["checkout_ui_mode"])
        return {
            "url": "https://pay.openai.com/c/pay/cs_live_hosted#fragment",
            "raw": {
                "checkout_session_id": "cs_live_hosted",
                "processor_entity": "openai_llc",
                "publishable_key": "pk_hosted",
            },
        }

    monkeypatch.setattr(gopay_executor, "_generate_id_checkout_http", fake_generate)

    class FakeGoPayCharger:
        def __init__(self, **kwargs):
            pass

        def run(self, *, checkout_session_id, stripe_pk):
            run_calls.append((checkout_session_id, stripe_pk))
            return {
                "state": "succeeded",
                "snap_token": "11111111-1111-4111-8111-111111111111",
                "charge_ref": "CHARGE123",
                "reference_id": "REF123",
            }

    monkeypatch.setattr(gopay_executor, "GoPayHttpCharger", FakeGoPayCharger)

    result = gopay_executor._run_gopay_bind_task_once(
        email="primary@example.com",
        checkout_url="",
        checkout_ui_mode="custom",
        phone_number="+6287761973970",
        sms_url="https://sms.example.test",
        gopay_pin="558023",
        progress_callback=progress_events.append,
    )

    assert result["status"] == "success"
    assert result["checkout_url"] == "https://pay.openai.com/c/pay/cs_live_hosted#fragment"
    assert generated_modes == ["hosted"]
    assert run_calls == [("cs_live_hosted", "pk_hosted")]
    checkout_ready = next(event for event in progress_events if event["stage"] == "checkout_ready")
    assert checkout_ready["mode"] == "protocol"
    assert checkout_ready["checkout_ui_mode"] == "hosted"

def test_playwright_navigation_race_error_is_retryable():
    assert _is_playwright_navigation_race_error(
        "Page.evaluate: Execution context was destroyed, most likely because of a navigation"
    )
    assert not _is_playwright_navigation_race_error("HTTP 403")

def test_generate_id_checkout_in_page_retries_navigation_race(monkeypatch):
    monkeypatch.setenv("GOPAY_BROWSER_CHECKOUT_EVALUATE_ATTEMPTS", "2")

    class FakePage:
        url = "https://chatgpt.com/"

        def __init__(self):
            self.calls = 0
            self.waits = []

        def evaluate(self, _script, _args):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError(
                    "Page.evaluate: Execution context was destroyed, most likely because of a navigation"
                )
            return {
                "ok": True,
                "status": 200,
                "url": "https://chatgpt.com/checkout/openai_llc/cs_test_123",
                "raw": {"checkout_session_id": "cs_test_123"},
            }

        def wait_for_load_state(self, state, timeout=0):
            self.waits.append((state, timeout))

        def wait_for_timeout(self, timeout):
            self.waits.append(("timeout", timeout))

    class FakeApi:
        def __init__(self):
            self.page = FakePage()

    fake_api = FakeApi()

    result = _generate_id_checkout_in_page(fake_api, access_token="access")

    assert result["url"] == "https://chatgpt.com/checkout/openai_llc/cs_test_123"
    assert fake_api.page.calls == 2
    assert ("domcontentloaded", 10000) in fake_api.page.waits

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
                FakeResponse(
                    status_code=201,
                    json_data={"activation_link_url": f"https://gopay.local/link?reference={reference_id}"},
                ),
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
                                "action": {"value": {"challenge_id": "challenge_link", "client_id": "client_link"}}
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
                                "action": {"value": {"challenge_id": "challenge_pay", "client_id": "client_pay"}}
                            }
                        },
                    }
                ),
            ),
            ("POST", "/api/v1/users/pin/tokens/nb", FakeResponse(json_data={"token": "pin_pay"})),
            (
                "POST",
                "/v1/payment/process",
                FakeResponse(json_data={"success": True, "data": {"next_action": "payment-success"}}),
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
        approve_callback=lambda session_id: (_ for _ in ()).throw(
            AssertionError("approve must not run for nonzero due")
        ),
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
                FakeResponse(
                    status_code=201,
                    json_data={"activation_link_url": f"https://gopay.local/link?reference={reference_id}"},
                ),
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
                                "action": {"value": {"challenge_id": "challenge_link", "client_id": "client_link"}}
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
                                "action": {"value": {"challenge_id": "challenge_pay", "client_id": "client_pay"}}
                            }
                        },
                    }
                ),
            ),
            ("POST", "/api/v1/users/pin/tokens/nb", FakeResponse(json_data={"token": "pin_pay"})),
            (
                "POST",
                "/v1/payment/process",
                FakeResponse(json_data={"success": True, "data": {"next_action": "payment-success"}}),
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
    class FailingHttp:
        def post(self, *args, **kwargs):
            raise gopay_executor.requests.exceptions.SSLError("ssl")

    def fail(*args, **kwargs):
        raise gopay_executor.requests.exceptions.SSLError("ssl")

    monkeypatch.setattr(gopay_executor, "_new_http_session", lambda **_kwargs: FailingHttp())
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
    calls = []
    slept = []

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
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda seconds: slept.append(seconds))
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

    assert calls == ["primary@example.com", "backup@example.com", "primary@example.com"]
    assert result["status"] == "success"
    assert result["email_used"] == "backup@example.com"
    assert result["requested_email"] == "primary@example.com"
    assert result["blocked_emails"] == ["primary@example.com"]
    assert result["retried_emails"] == ["primary@example.com"]
    assert slept == [60.0]
    assert "primary@example.com" in gopay_executor._GOPAY_APPROVE_BLOCKED_UNTIL
    assert any(event["stage"] == "chatgpt_approve_blocked_rotate" for event in progress_events)
    assert any(event["stage"] == "gopay_rotate_account" for event in progress_events)

def test_gopay_bind_task_single_account_does_not_rotate_on_blocked(monkeypatch):
    monkeypatch.setenv("GOPAY_APPROVE_BLOCKED_COOLDOWN_SECONDS", "123")
    gopay_executor._GOPAY_APPROVE_BLOCKED_UNTIL.clear()
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

    monkeypatch.setenv("GOPAY_CHECKOUT_FORM_MODE", "browser")
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
            "snap_token": "11111111-1111-4111-8111-111111111111",
        }

    monkeypatch.setattr(gopay_executor, "_browser_checkout_to_gopay_redirect", fake_browser_handoff)

    class FakeGoPayCharger:
        def __init__(self, **kwargs):
            pass

        def run(self, *, checkout_session_id, stripe_pk):
            raise AssertionError("browser UI mode must not run protocol Stripe/approve checkout")

        def run_from_snap_token(self, *, snap_token, checkout_session_id=""):
            assert snap_token == "11111111-1111-4111-8111-111111111111"
            assert checkout_session_id == "cs_browser"
            return {
                "state": "succeeded",
                "snap_token": snap_token,
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

def test_gopay_bind_task_auto_mode_falls_back_to_browser_when_protocol_form_fails(monkeypatch):
    progress_events = []
    checkout_url = "https://chatgpt.com/checkout/openai_llc/cs_test"
    handoff_calls = []
    run_calls = []

    monkeypatch.setenv("GOPAY_CHECKOUT_FORM_MODE", "auto")
    monkeypatch.setenv("GOPAY_BROWSER_CHECKOUT_FALLBACK", "1")
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
            "snap_token": "11111111-1111-4111-8111-111111111111",
        }

    monkeypatch.setattr(gopay_executor, "_browser_checkout_to_gopay_redirect", fake_browser_handoff)

    class FakeGoPayCharger:
        def __init__(self, **kwargs):
            pass

        def run(self, *, checkout_session_id, stripe_pk):
            run_calls.append((checkout_session_id, stripe_pk))
            raise GoPayFlowError("Stripe 地址提交失败", stage="stripe_address_update")

        def run_from_snap_token(self, *, snap_token, checkout_session_id=""):
            return {
                "state": "succeeded",
                "snap_token": snap_token,
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
    assert run_calls == [("cs_test", gopay_executor.DEFAULT_STRIPE_PK)]
    assert handoff_calls
    assert any(event["stage"] == "stripe_protocol_form_failed_browser_fallback" for event in progress_events)

def test_gopay_bind_task_auto_mode_respects_disabled_browser_fallback_when_chatgpt_approve_blocked(monkeypatch):
    progress_events = []
    checkout_url = "https://chatgpt.com/checkout/openai_llc/cs_test"
    handoff_calls = []
    run_calls = []

    monkeypatch.setenv("GOPAY_CHECKOUT_FORM_MODE", "auto")
    monkeypatch.setenv("GOPAY_BROWSER_CHECKOUT_FALLBACK", "0")
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
            "snap_token": "11111111-1111-4111-8111-111111111111",
        }

    monkeypatch.setattr(gopay_executor, "_browser_checkout_to_gopay_redirect", fake_browser_handoff)

    class FakeGoPayCharger:
        def __init__(self, **kwargs):
            pass

        def run(self, *, checkout_session_id, stripe_pk):
            run_calls.append((checkout_session_id, stripe_pk))
            raise GoPayFlowError("ChatGPT approve 未通过: {'result': 'blocked'}", stage="chatgpt_approve")

        def run_from_snap_token(self, *, snap_token, checkout_session_id=""):
            return {
                "state": "succeeded",
                "snap_token": snap_token,
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

    assert result["status"] == "failed"
    assert result["failure_stage"] == "chatgpt_approve"
    assert "ChatGPT approve" in result["message"]
    assert run_calls == [("cs_test", gopay_executor.DEFAULT_STRIPE_PK)]
    assert handoff_calls == []
    assert not any(event["stage"] == "stripe_protocol_form_failed_browser_fallback" for event in progress_events)
    assert not any(event["stage"] == "chatgpt_checkout_browser_handoff" for event in progress_events)

def test_gopay_bind_task_retries_same_checkout_on_midtrans_linking_429(monkeypatch):
    progress_events = []
    checkout_url = "https://chatgpt.com/checkout/openai_llc/cs_test"
    handoff_calls = []
    snap_calls = []
    slept = []

    monkeypatch.setenv("GOPAY_CHECKOUT_FORM_MODE", "browser")
    monkeypatch.setenv("GOPAY_MIDTRANS_LINKING_429_RETRY_ATTEMPTS", "3")
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
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda seconds: slept.append(seconds))

    def fake_browser_handoff(api, **kwargs):
        handoff_calls.append(kwargs)
        attempt = len(handoff_calls)
        return {
            "checkout_url": f"https://chatgpt.com/checkout/openai_llc/cs_browser_{attempt}",
            "checkout_session_id": f"cs_browser_{attempt}",
            "processor_entity": "openai_llc",
            "redirect_url": f"https://pm-redirects.stripe.com/authorize/test_{attempt}",
            "snap_token": "11111111-1111-4111-8111-111111111111",
        }

    monkeypatch.setattr(gopay_executor, "_browser_checkout_to_gopay_redirect", fake_browser_handoff)

    class FakeGoPayCharger:
        def __init__(self, **kwargs):
            pass

        def run(self, *, checkout_session_id, stripe_pk):
            raise AssertionError("browser UI mode must not run protocol Stripe/approve checkout")

        def run_from_snap_token(self, *, snap_token, checkout_session_id=""):
            snap_calls.append((snap_token, checkout_session_id))
            if len(snap_calls) == 1:
                raise GoPayFlowError("Midtrans linking 失败: HTTP 429", stage="midtrans_linking")
            return {
                "state": "succeeded",
                "snap_token": snap_token,
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
    assert len(handoff_calls) == 1
    assert len(snap_calls) == 2
    assert snap_calls[0] == ("11111111-1111-4111-8111-111111111111", "cs_browser_1")
    assert snap_calls[1] == ("11111111-1111-4111-8111-111111111111", "cs_browser_1")
    assert any(event["stage"] == "midtrans_linking_retry" for event in progress_events)
    assert slept == [3.0]

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

def test_extract_checkout_error_detects_customer_location_tax_error():
    class FakePage:
        def evaluate(self, script):
            return [
                "The customer's location isn't recognized. Set a valid customer address in order to automatically calculate tax.",
                "Subscribe",
            ]

    class FakeApi:
        page = FakePage()

    error = _extract_checkout_error(FakeApi())

    assert "customer's location isn't recognized" in error.lower()
    assert _is_checkout_customer_location_error(error) is True

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

def test_checkout_rate_limit_error_is_not_payment_not_approved():
    assert _is_checkout_rate_limited_error("HTTP 429 too many requests")
    assert _is_checkout_rate_limited_error("请求过于频繁，请稍后再试")
    assert not gopay_executor._is_checkout_payment_not_approved_error("HTTP 429 too many requests")

def test_gopay_bind_task_rotates_on_checkout_payment_not_approved(monkeypatch):
    calls = []
    slept = []

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
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda seconds: slept.append(seconds))
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
    assert result["retried_emails"] == []
    assert slept == []
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

def test_chatgpt_ph_checkout_vat_summary_is_not_zero_tax():
    body = """
    按月订阅订阅
    PHP 8,919.64
    VAT (12%)
    PHP 1,070.36
    今日应付金额
    PHP 9,990.00
    """

    assert bind_executor._tax_summary_still_has_vat(body) is True
    assert bind_executor._tax_summary_has_zero_tax(body) is False

def test_chatgpt_ph_checkout_recalculated_us_address_is_zero_tax():
    body = """
    按月订阅订阅
    PHP 8,919.64
    税额 (0%)
    PHP 0.00
    今日应付金额
    PHP 8,919.64
    """

    assert bind_executor._tax_summary_still_has_vat(body) is False
    assert bind_executor._tax_summary_has_zero_tax(body) is True

def test_nudge_billing_address_recalculation_dispatches_address_fields():
    calls = []

    class FakeFrame:
        def evaluate(self, script, fields):
            calls.append(fields)
            return ["country", "address", "postal_code"]

    class FakePage(FakeFrame):
        def __init__(self):
            self.frames = [FakeFrame()]

    class FakeApi:
        def __init__(self):
            self.page = FakePage()

    bind_executor._nudge_billing_address_recalculation(
        FakeApi(),
        {
            "name": "DAWN M KUCK",
            "country": "US",
            "address": "632 W 6th Ave",
            "city": "Anchorage",
            "state": "AK",
            "postal_code": "99501",
        },
    )

    assert len(calls) == 2
    assert calls[0]["country"] == "US"
    assert calls[0]["postal_code"] == "99501"
