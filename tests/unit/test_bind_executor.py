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
    paypal_bind_executor,
    paypal_protocol_signup,
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


def test_paypal_auth_context_extracts_account_id_from_access_token(monkeypatch):
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
        paypal_bind_executor,
        "load_auth_session",
        lambda email: {
            "accessToken": access_token,
            "sessionToken": "session-token",
            "cookie_header": "__Secure-next-auth.session-token=session-token",
            "device_id": "device-id",
        },
    )
    monkeypatch.setattr(paypal_bind_executor, "_load_chatgpt_auth_file_context", lambda email: {})

    context = paypal_bind_executor._extract_auth_session_context("user@example.com")

    assert context["account_id"] == "account-from-jwt"
    assert paypal_bind_executor._email_from_access_token(access_token) == "user@example.com"


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


def test_paypal_progress_event_wrapper_uses_shared_stage_messages():
    assert paypal_bind_executor._progress_event("paypal_wait_result", url="https://paypal.example") == {
        "stage": "paypal_wait_result",
        "message": "PayPal 已授权，等待商户页面确认结果",
        "url": "https://paypal.example",
    }
    assert paypal_bind_executor._progress_event("custom_stage") == {
        "stage": "custom_stage",
        "message": "custom_stage",
    }


def test_paypal_body_excerpt_wrapper_includes_unique_frame_text():
    class FakeLocator:
        def __init__(self, text):
            self.text = text

        def inner_text(self, timeout=None):
            return self.text

    class FakeFrame:
        def __init__(self, text):
            self.text = text

        def locator(self, selector):
            assert selector == "body"
            return FakeLocator(self.text)

    class FakePage:
        def __init__(self):
            self.main_frame = FakeFrame("main frame duplicate")
            self.frames = [self.main_frame, FakeFrame("Main body"), FakeFrame("Frame body")]

        def locator(self, selector):
            assert selector == "body"
            return FakeLocator("Main body")

    class FakeApi:
        page = FakePage()

    assert paypal_bind_executor._body_excerpt(FakeApi(), limit=100) == "Main body\nFrame body"


def test_paypal_sync_relevant_payment_page_wrapper_uses_paypal_and_checkout_classifiers():
    class FakePage:
        def __init__(self, url):
            self.url = url

    class FakeContext:
        def __init__(self, pages):
            self.pages = pages

    class FakeApi:
        def __init__(self, pages):
            self.context = FakeContext(pages)
            self.page = pages[0]

    paypal_page = FakePage("https://www.paypal.com/checkoutweb/signup")
    checkout_page = FakePage("https://checkout.stripe.com/c/pay/cs_test")
    unrelated_page = FakePage("https://example.com/")
    api = FakeApi([unrelated_page, paypal_page, checkout_page])

    assert paypal_bind_executor._sync_relevant_payment_page(api, prefer_paypal=True) is paypal_page
    assert api.page is paypal_page

    assert paypal_bind_executor._sync_relevant_payment_page(api, prefer_paypal=False) is checkout_page
    assert api.page is checkout_page


def test_force_paypal_us_locale_wrapper_updates_paypal_url_only():
    class FakePage:
        def __init__(self, url):
            self.url = url
            self.goto_calls = []
            self.waits = []

        def goto(self, url, **kwargs):
            self.goto_calls.append((url, kwargs))
            self.url = url

        def wait_for_timeout(self, timeout):
            self.waits.append(timeout)

    class FakeApi:
        def __init__(self, url):
            self.page = FakePage(url)

    non_paypal = FakeApi("https://example.com/checkout?country.x=US")
    assert paypal_bind_executor._force_paypal_us_locale(non_paypal, country="JP", lang="ja") is False
    assert non_paypal.page.goto_calls == []

    paypal = FakeApi("https://www.paypal.com/checkoutweb/signup?ba_token=BA-DEMO&country.x=US")
    assert paypal_bind_executor._force_paypal_us_locale(paypal, country="JP", lang="") is True
    assert paypal.page.goto_calls[0][0] == (
        "https://www.paypal.com/checkoutweb/signup?ba_token=BA-DEMO&country.x=JP&locale.x=ja_JP"
    )
    assert paypal.page.goto_calls[0][1] == {"wait_until": "domcontentloaded", "timeout": 60000}
    assert paypal.page.waits == [1500]

    assert paypal_bind_executor._force_paypal_us_locale(paypal, country="JP", lang="ja") is False
    assert len(paypal.page.goto_calls) == 1


def test_paypal_click_first_wrapper_uses_visible_locator(monkeypatch):
    class FakeLocator:
        def __init__(self):
            self.scrolled = False
            self.clicked = False

        def is_disabled(self, timeout=None):
            return False

        def scroll_into_view_if_needed(self, timeout=None):
            self.scrolled = True

        def click(self, timeout=None):
            self.clicked = timeout

    locator = FakeLocator()
    captured = {}

    def fake_visible(_api, selectors, timeout_ms=0):
        captured["selectors"] = selectors
        captured["timeout_ms"] = timeout_ms
        return locator

    monkeypatch.setattr(paypal_bind_executor, "_visible_locator_in_frames", fake_visible)

    assert paypal_bind_executor._click_first(object(), ["button"], timeout_ms=4321) is True
    assert captured == {"selectors": ["button"], "timeout_ms": 4321}
    assert locator.scrolled is True
    assert locator.clicked == 4321


def test_paypal_option_selected_wrapper_uses_attached_state_locator(monkeypatch):
    class FakePage:
        def evaluate(self, _script):
            return False

    class FakeApi:
        page = FakePage()

    locator = object()
    captured = {}

    def fake_attached(_api, selectors, timeout_ms=0):
        captured["selectors"] = selectors
        captured["timeout_ms"] = timeout_ms
        return locator

    monkeypatch.setattr(paypal_bind_executor, "_attached_locator_in_frames", fake_attached)
    monkeypatch.setattr(paypal_bind_executor, "_locator_is_checked", lambda value: value is locator)

    assert paypal_bind_executor._is_paypal_option_selected(FakeApi()) is True
    assert captured["selectors"] == paypal_bind_executor.PAYPAL_CHECKOUT_STATE_SELECTORS
    assert captured["timeout_ms"] == 300


def test_paypal_checkout_control_wrapper_passes_checkout_dependencies(monkeypatch):
    captured = {}

    def fake_click_control(_api, **kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "click_paypal_checkout_control",
        fake_click_control,
    )

    assert paypal_bind_executor._click_paypal_checkout_control(object()) is True
    assert captured["checkout_selectors"] == paypal_bind_executor.PAYPAL_CHECKOUT_SELECTORS
    assert captured["state_selectors"] == paypal_bind_executor.PAYPAL_CHECKOUT_STATE_SELECTORS
    assert callable(captured["click_first"])
    assert callable(captured["attached_locator"])
    assert captured["frames"] is paypal_bind_executor._iter_page_frames


def test_select_paypal_option_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    progress_events = []
    on_progress = progress_events.append

    def fake_select_option(_api, **kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "select_paypal_option",
        fake_select_option,
    )

    api = object()
    assert paypal_bind_executor._select_paypal_option(api, on_progress=on_progress) is True
    assert captured["paypal_host"] is paypal_bind_executor._is_paypal_host
    assert captured["option_selected"] is paypal_bind_executor._is_paypal_option_selected
    assert captured["click_control"] is paypal_bind_executor._click_paypal_checkout_control
    assert captured["progress_event"] is paypal_bind_executor._progress_event
    assert captured["on_progress"] is on_progress


def test_wait_for_paypal_checkout_interactive_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}

    def fake_wait_interactive(_api, **kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "wait_paypal_checkout_interactive",
        fake_wait_interactive,
    )

    api = object()
    assert paypal_bind_executor._wait_for_paypal_checkout_interactive(api, timeout_seconds=27) is True
    assert captured["paypal_selectors"] == paypal_bind_executor.PAYPAL_CHECKOUT_SELECTORS
    assert captured["submit_selectors"] == paypal_bind_executor.CHECKOUT_SUBMIT_SELECTORS
    assert callable(captured["visible_locator"])
    assert captured["body_excerpt"] is paypal_bind_executor._body_excerpt
    assert captured["timeout_seconds"] == 27
    assert captured["logger"] is paypal_bind_executor.logger
    assert captured["url_summary"] is paypal_bind_executor._safe_url_summary


def test_inspect_paypal_page_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}

    def fake_inspect(_api, **kwargs):
        captured.update(kwargs)
        return {"url": "https://www.paypal.com/"}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "inspect_paypal_page",
        fake_inspect,
    )

    api = object()
    assert paypal_bind_executor._inspect_paypal_page(api) == {"url": "https://www.paypal.com/"}
    assert captured["paypal_host"] is paypal_bind_executor._is_paypal_host
    assert captured["ensure_captcha_bypass"] is paypal_bind_executor._ensure_paypal_hosted_captcha_bypass
    assert captured["body_excerpt"] is paypal_bind_executor._body_excerpt
    assert callable(captured["visible_locator"])
    assert captured["has_phone_rejected_prompt"] is paypal_bind_executor._has_paypal_phone_rejected_prompt
    assert captured["has_otp_inputs"] is paypal_bind_executor._has_paypal_otp_inputs
    assert captured["phone_rejected_text_hint"] is paypal_bind_executor._paypal_phone_rejected_text_hint
    assert captured["card_rejected_text_hint"] is paypal_bind_executor._paypal_card_rejected_text_hint
    assert captured["signup_registration_text_hint"] is paypal_bind_executor._paypal_signup_registration_text_hint
    assert captured["signup_otp_text_hint"] is paypal_bind_executor._paypal_signup_otp_text_hint
    assert captured["login_text_hint"] is paypal_bind_executor._paypal_login_text_hint
    assert captured["passkey_text_hint"] is paypal_bind_executor._paypal_passkey_text_hint
    assert captured["approve_text_hint"] is paypal_bind_executor._paypal_approve_text_hint
    assert captured["email_selectors"] == paypal_bind_executor.PAYPAL_EMAIL_SELECTORS
    assert captured["password_selectors"] == paypal_bind_executor.PAYPAL_PASSWORD_SELECTORS
    assert captured["approve_selectors"] == paypal_bind_executor.PAYPAL_APPROVE_SELECTORS
    assert captured["prompt_selectors"] == paypal_bind_executor.PAYPAL_DISMISS_PROMPT_SELECTORS
    assert captured["create_account_selectors"] == paypal_bind_executor.PAYPAL_CREATE_ACCOUNT_SELECTORS
    assert captured["phone_selectors"] == paypal_bind_executor.PAYPAL_PHONE_SELECTORS
    assert captured["card_selectors"] == paypal_bind_executor.PAYPAL_CARD_NUMBER_SELECTORS


def test_paypal_prompt_wrappers_pass_browser_dependencies(monkeypatch):
    prompt_captured = {}
    phone_dismiss_captured = {}
    has_prompt_captured = {}
    progress_events = []
    on_progress = progress_events.append

    def fake_dismiss_prompt(_api, **kwargs):
        prompt_captured.update(kwargs)
        return True

    def fake_click_frame(frame):
        return frame == "frame"

    def fake_dismiss_phone(_api, **kwargs):
        phone_dismiss_captured.update(kwargs)
        return True

    def fake_has_prompt(_api, **kwargs):
        has_prompt_captured.update(kwargs)
        return True

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "dismiss_paypal_prompts",
        fake_dismiss_prompt,
    )
    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "click_paypal_phone_rejected_ok_in_frame",
        fake_click_frame,
    )
    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "dismiss_paypal_phone_rejected_prompt",
        fake_dismiss_phone,
    )
    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "has_paypal_phone_rejected_prompt",
        fake_has_prompt,
    )

    api = object()
    assert paypal_bind_executor._dismiss_paypal_prompts(api, on_progress=on_progress) is True
    assert prompt_captured["prompt_selectors"] == paypal_bind_executor.PAYPAL_DISMISS_PROMPT_SELECTORS
    assert callable(prompt_captured["click_first"])
    assert prompt_captured["progress_event"] is paypal_bind_executor._progress_event
    assert prompt_captured["on_progress"] is on_progress

    assert paypal_bind_executor._click_paypal_phone_rejected_ok_in_frame("frame") is True

    assert paypal_bind_executor._dismiss_paypal_phone_rejected_prompt(api) is True
    assert phone_dismiss_captured["frames"] is paypal_bind_executor._iter_page_frames
    assert phone_dismiss_captured["click_ok_in_frame"] is paypal_bind_executor._click_paypal_phone_rejected_ok_in_frame
    assert callable(phone_dismiss_captured["click_first"])
    assert phone_dismiss_captured["has_prompt"] is paypal_bind_executor._has_paypal_phone_rejected_prompt
    assert phone_dismiss_captured["prompt_selectors"] == paypal_bind_executor.PAYPAL_DISMISS_PROMPT_SELECTORS

    assert paypal_bind_executor._has_paypal_phone_rejected_prompt(api) is True
    assert has_prompt_captured["rejected_selectors"] == paypal_bind_executor.PAYPAL_PHONE_REJECTED_SELECTORS
    assert callable(has_prompt_captured["visible_locator"])
    assert has_prompt_captured["body_excerpt"] is paypal_bind_executor._body_excerpt
    assert has_prompt_captured["text_hint"] is paypal_bind_executor._paypal_phone_rejected_text_hint


def test_paypal_signup_registration_form_visible_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}

    def fake_registration_visible(_api, **kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_signup_registration_form_visible",
        fake_registration_visible,
    )

    api = object()
    assert paypal_bind_executor._paypal_signup_registration_form_visible(api) is True
    assert captured["body_excerpt"] is paypal_bind_executor._body_excerpt
    assert captured["text_visible"] is paypal_bind_executor._paypal_signup_registration_form_text_visible
    assert callable(captured["visible_locator"])
    assert captured["field_selector_groups"] == (
        paypal_bind_executor.PAYPAL_PHONE_SELECTORS,
        paypal_bind_executor.PAYPAL_CARD_NUMBER_SELECTORS,
        paypal_bind_executor.PAYPAL_CARD_EXPIRY_SELECTORS,
        paypal_bind_executor.PAYPAL_PASSWORD_SELECTORS,
        paypal_bind_executor.PAYPAL_BIRTH_DATE_SELECTORS,
    )


def test_click_paypal_signup_otp_resend_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    progress_events = []
    on_progress = progress_events.append

    def fake_click_resend(_api, **kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "click_paypal_signup_otp_resend",
        fake_click_resend,
    )

    api = object()
    assert paypal_bind_executor._click_paypal_signup_otp_resend(api, on_progress=on_progress) is True
    assert captured["frames"] is paypal_bind_executor._iter_page_frames
    assert callable(captured["click_first"])
    assert captured["progress_event"] is paypal_bind_executor._progress_event
    assert captured["on_progress"] is on_progress
    assert captured["sleep"] is paypal_bind_executor.time.sleep


def test_maybe_enter_paypal_signup_from_login_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    click_calls = []
    goto_calls = []
    def on_progress(_event):
        return None

    def fake_maybe_enter(_api, **kwargs):
        captured.update(kwargs)
        kwargs["click_create_account"](_api)
        kwargs["goto_create_account_entry"](_api, ba_token="BA-ARG", country="JP", lang="ja")
        return True, "", True

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "maybe_enter_paypal_signup_from_login",
        fake_maybe_enter,
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_click_paypal_create_account",
        lambda api, **kwargs: click_calls.append((api, kwargs)) or True,
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_goto_paypal_create_account_entry",
        lambda api, **kwargs: goto_calls.append((api, kwargs)) or True,
    )

    api = object()
    state = {"needs_login": True}
    assert paypal_bind_executor._maybe_enter_paypal_signup_from_login(
        api,
        state=state,
        signup_submitted=False,
        signup_email_submitted=False,
        paypal_country="JP",
        paypal_lang="ja",
        paypal_ba_token="BA-123",
        on_progress=on_progress,
    ) == (True, "", True)
    assert captured["state"] is state
    assert captured["signup_submitted"] is False
    assert captured["signup_email_submitted"] is False
    assert captured["ba_token"] == "BA-123"
    assert captured["country"] == "JP"
    assert captured["lang"] == "ja"
    assert captured["sleep"] is paypal_bind_executor.time.sleep
    assert click_calls == [(api, {"on_progress": on_progress})]
    assert goto_calls == [(api, {"ba_token": "BA-ARG", "country": "JP", "lang": "ja", "on_progress": on_progress})]


def test_handle_paypal_signup_needs_login_redirect_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    progress_events = []
    on_progress = progress_events.append

    def fake_handle(_api, **kwargs):
        captured.update(kwargs)
        return {"action": "continue", "signup_login_redirect_count": 1}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_signup_needs_login_redirect",
        fake_handle,
    )

    api = object()
    state = {"needs_login": True}
    assert paypal_bind_executor._handle_paypal_signup_needs_login_redirect(
        api,
        state=state,
        signup_login_redirect_count=0,
        paypal_ba_token="BA-123",
        paypal_country="JP",
        paypal_lang="ja",
        on_progress=on_progress,
        sleep_after_redirect_seconds=1.5,
    ) == {"action": "continue", "signup_login_redirect_count": 1}
    assert captured["state"] is state
    assert captured["signup_login_redirect_count"] == 0
    assert captured["max_redirects"] == 3
    assert captured["ba_token"] == "BA-123"
    assert captured["country"] == "JP"
    assert captured["lang"] == "ja"
    assert captured["goto_create_account_entry"] is paypal_bind_executor._goto_paypal_create_account_entry
    assert captured["on_progress"] is on_progress
    assert captured["sleep_after_redirect_seconds"] == 1.5
    assert captured["sleep"] is paypal_bind_executor.time.sleep


def test_maybe_dismiss_paypal_passkey_prompt_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    progress_events = []
    on_progress = progress_events.append

    def fake_dismiss(_api, **kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "maybe_dismiss_paypal_passkey_prompt",
        fake_dismiss,
    )

    api = object()
    state = {"has_passkey_prompt": True}
    assert (
        paypal_bind_executor._maybe_dismiss_paypal_passkey_prompt(
            api,
            state=state,
            on_progress=on_progress,
        )
        is True
    )
    assert captured["state"] is state
    assert captured["dismiss_prompts"] is paypal_bind_executor._dismiss_paypal_prompts
    assert captured["on_progress"] is on_progress
    assert captured["sleep"] is paypal_bind_executor.time.sleep


def test_inspect_and_merge_paypal_state_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}

    def fake_merge(previous_state, inspected_state, **kwargs):
        captured["previous_state"] = previous_state
        captured["inspected_state"] = inspected_state
        captured.update(kwargs)
        return {"body_text": "merged"}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "merge_paypal_inspected_state",
        fake_merge,
    )

    api = object()
    previous_state = {"_fill_retry_count": 2}
    inspected_state = {"body_text": "fresh"}
    monkeypatch.setattr(
        paypal_bind_executor, "_inspect_paypal_page", lambda target: inspected_state if target is api else {}
    )

    assert paypal_bind_executor._inspect_and_merge_paypal_state(
        api,
        previous_state=previous_state,
        paypal_ba_token="BA-TOKEN",
    ) == {"body_text": "merged"}
    assert captured["previous_state"] is previous_state
    assert captured["inspected_state"] is inspected_state
    assert captured["ba_token"] == "BA-TOKEN"


def test_maybe_mark_paypal_signup_registration_ready_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}

    def fake_mark_ready(_api, **kwargs):
        captured.update(kwargs)
        kwargs["registration_form_visible"](_api)
        return True

    visible_calls = []
    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "maybe_mark_paypal_signup_registration_ready",
        fake_mark_ready,
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_paypal_signup_registration_form_visible",
        lambda api: visible_calls.append(api) or True,
    )

    api = object()
    state = {}
    assert (
        paypal_bind_executor._maybe_mark_paypal_signup_registration_ready(
            api,
            state=state,
            signup_submitted=False,
        )
        is True
    )
    assert captured["state"] is state
    assert captured["signup_submitted"] is False
    assert visible_calls == [api]


def test_maybe_click_paypal_signup_create_account_ready_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    click_calls = []
    def on_progress(_event):
        return None

    def fake_maybe_click(_api, **kwargs):
        captured.update(kwargs)
        kwargs["click_create_account"](_api)
        return True, "", True

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "maybe_click_paypal_signup_create_account_ready",
        fake_maybe_click,
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_click_paypal_create_account",
        lambda api, **kwargs: click_calls.append((api, kwargs)) or True,
    )

    api = object()
    state = {"create_account_ready": True}
    assert paypal_bind_executor._maybe_click_paypal_signup_create_account_ready(
        api,
        state=state,
        on_progress=on_progress,
    ) == (True, "", True)
    assert captured["state"] is state
    assert captured["sleep"] is paypal_bind_executor.time.sleep
    assert click_calls == [(api, {"on_progress": on_progress})]


def test_sync_paypal_signup_authorize_state_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}

    def fake_sync(state, **kwargs):
        captured["state"] = state
        captured.update(kwargs)
        return {
            "signup_email_submitted": True,
            "signup_email_submitted_at": 10.0,
            "signup_form_submitted": True,
            "signup_submitted_at": 20.0,
            "phone_only_retry": False,
            "card_retry_count": 1,
            "otp_phone_lock_key": "",
        }

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "sync_paypal_signup_authorize_state",
        fake_sync,
    )

    state = {"signup_email_submitted": True}
    assert paypal_bind_executor._sync_paypal_signup_authorize_state(
        state,
        signup_email_submitted=False,
        signup_email_submitted_at=0.0,
        signup_form_submitted=False,
        signup_submitted_at=0.0,
        card_retry_count=0,
    ) == {
        "signup_email_submitted": True,
        "signup_email_submitted_at": 10.0,
        "signup_form_submitted": True,
        "signup_submitted_at": 20.0,
        "phone_only_retry": False,
        "card_retry_count": 1,
        "otp_phone_lock_key": "",
    }
    assert captured["state"] is state
    assert captured["signup_email_submitted"] is False
    assert captured["signup_email_submitted_at"] == 0.0
    assert captured["signup_form_submitted"] is False
    assert captured["signup_submitted_at"] == 0.0
    assert captured["card_retry_count"] == 0
    assert captured["now"] is paypal_bind_executor.time.time


def test_seed_paypal_signup_authorize_state_wrapper_delegates(monkeypatch):
    captured = {}
    state = {}
    submitted_phone_keys = {"12025550123"}

    def fake_seed(target_state, **kwargs):
        captured["state"] = target_state
        captured.update(kwargs)
        return target_state

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "seed_paypal_signup_authorize_state",
        fake_seed,
    )

    assert (
        paypal_bind_executor._seed_paypal_signup_authorize_state(
            state,
            signup_email_submitted=True,
            signup_email_submitted_at=12.5,
            signup_form_submitted=True,
            signup_submitted_at=20.5,
            submitted_phone_keys=submitted_phone_keys,
            phone_only_retry=True,
            card_retry_count=2,
            otp_phone_lock_key="otp-lock",
        )
        is state
    )
    assert captured == {
        "state": state,
        "signup_email_submitted": True,
        "signup_email_submitted_at": 12.5,
        "signup_form_submitted": True,
        "signup_submitted_at": 20.5,
        "submitted_phone_keys": submitted_phone_keys,
        "phone_only_retry": True,
        "card_retry_count": 2,
        "otp_phone_lock_key": "otp-lock",
    }


def test_paypal_signup_authorize_state_values_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_values(signup_state):
        captured["signup_state"] = signup_state
        return (True, 12.5, False, 20.5, True, 3, "otp-lock")

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_signup_authorize_state_values",
        fake_values,
    )

    signup_state = {"signup_email_submitted": True}
    assert paypal_bind_executor._paypal_signup_authorize_state_values(signup_state) == (
        True,
        12.5,
        False,
        20.5,
        True,
        3,
        "otp-lock",
    )
    assert captured["signup_state"] is signup_state


def test_paypal_signup_email_step_state_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}

    def fake_email_state(state, **kwargs):
        captured["state"] = state
        captured.update(kwargs)
        return {"is_email_step": True, "is_blank_after_email": False, "timeout_result": None}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_signup_email_step_state",
        fake_email_state,
    )

    state = {"email_locator": object()}
    assert paypal_bind_executor._paypal_signup_email_step_state(
        state,
        signup_email_submitted=True,
    ) == {"is_email_step": True, "is_blank_after_email": False, "timeout_result": None}
    assert captured["state"] is state
    assert captured["signup_email_submitted"] is True
    assert captured["wait_timeout_seconds"] == paypal_bind_executor.PAYPAL_SIGNUP_EMAIL_STEP_WAIT_TIMEOUT_SECONDS
    assert captured["now"] is paypal_bind_executor.time.time


def test_recover_paypal_signup_email_step_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    progress_events = []
    on_progress = progress_events.append

    def fake_recover(_api, **kwargs):
        captured.update(kwargs)
        return True, "", True

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "recover_paypal_signup_email_step",
        fake_recover,
    )

    api = object()
    signup_profile = {"email": "demo@example.com"}
    state = {"signup_email_submitted": True}
    assert paypal_bind_executor._recover_paypal_signup_email_step(
        api,
        signup_profile=signup_profile,
        state=state,
        submitted_at=100.0,
        first_submitted_at=90.0,
        on_progress=on_progress,
    ) == (True, "", True)
    assert captured["signup_profile"] is signup_profile
    assert captured["state"] is state
    assert captured["submitted_at"] == 100.0
    assert captured["first_submitted_at"] == 90.0
    assert (
        captured["stuck_recover_delay_seconds"] == paypal_bind_executor.PAYPAL_SIGNUP_EMAIL_STUCK_RECOVER_DELAY_SECONDS
    )
    assert captured["recover_email_spinner"] is paypal_bind_executor._js_recover_paypal_email_spinner
    assert captured["progress_event"] is paypal_bind_executor._progress_event
    assert captured["on_progress"] is on_progress
    assert captured["logger"] is paypal_bind_executor.logger
    assert captured["max_js_before_reload"] == 1
    assert captured["max_reload_cycles"] == 3
    assert captured["now"] is paypal_bind_executor.time.time
    assert captured["sleep"] is paypal_bind_executor.time.sleep


def test_recover_paypal_signup_unhandled_email_stuck_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    progress_events = []
    on_progress = progress_events.append

    def fake_recover(_api, **kwargs):
        captured.update(kwargs)
        return {"action": "continue", "signup_email_submitted": False, "signup_email_submitted_at": 0.0}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "recover_paypal_signup_unhandled_email_stuck",
        fake_recover,
    )

    api = object()
    signup_profile = {"email": "demo@example.com"}
    state = {"signup_email_submitted": True}
    assert paypal_bind_executor._recover_paypal_signup_unhandled_email_stuck(
        api,
        signup_profile=signup_profile,
        state=state,
        signup_email_submitted=True,
        signup_email_submitted_at=100.0,
        current_url="https://www.paypal.com/pay",
        on_progress=on_progress,
    ) == {"action": "continue", "signup_email_submitted": False, "signup_email_submitted_at": 0.0}
    assert captured["signup_profile"] is signup_profile
    assert captured["state"] is state
    assert captured["signup_email_submitted"] is True
    assert captured["signup_email_submitted_at"] == 100.0
    assert captured["current_url"] == "https://www.paypal.com/pay"
    assert captured["wait_timeout_seconds"] == paypal_bind_executor.PAYPAL_SIGNUP_EMAIL_STEP_WAIT_TIMEOUT_SECONDS
    assert (
        captured["stuck_recover_delay_seconds"] == paypal_bind_executor.PAYPAL_SIGNUP_EMAIL_STUCK_RECOVER_DELAY_SECONDS
    )
    assert captured["recover_email_spinner"] is paypal_bind_executor._js_recover_paypal_email_spinner
    assert captured["progress_event"] is paypal_bind_executor._progress_event
    assert captured["on_progress"] is on_progress
    assert captured["logger"] is paypal_bind_executor.logger
    assert captured["url_summary"] is paypal_bind_executor._safe_url_summary
    assert captured["max_js_before_reload"] == 1
    assert captured["max_reload_cycles"] == 3
    assert captured["now"] is paypal_bind_executor.time.time
    assert captured["sleep"] is paypal_bind_executor.time.sleep


def test_continue_paypal_signup_email_step_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    progress_events = []
    on_progress = progress_events.append

    def fake_continue(_api, **kwargs):
        captured.update(kwargs)
        return True, "", True

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "continue_paypal_signup_email_step",
        fake_continue,
    )

    api = object()
    signup_profile = {"email": "demo@example.com"}
    state = {"email_locator": object()}
    assert paypal_bind_executor._continue_paypal_signup_email_step(
        api,
        signup_profile=signup_profile,
        state=state,
        current_url="https://www.paypal.com/pay",
        signup_email_submitted=False,
        is_blank_after_email=False,
        on_progress=on_progress,
    ) == (True, "", True)
    assert captured["signup_profile"] is signup_profile
    assert captured["state"] is state
    assert captured["current_url"] == "https://www.paypal.com/pay"
    assert captured["signup_email_submitted"] is False
    assert captured["is_blank_after_email"] is False
    assert captured["submit_email_step"] is paypal_bind_executor._submit_paypal_signup_email_step
    assert captured["progress_event"] is paypal_bind_executor._progress_event
    assert captured["on_progress"] is on_progress
    assert captured["now"] is paypal_bind_executor.time.time
    assert captured["sleep"] is paypal_bind_executor.time.sleep


def test_sync_paypal_signup_phone_submission_state_wrapper_passes_form_dependencies(monkeypatch):
    captured = {}

    def fake_sync(signup_profile, state, **kwargs):
        captured["signup_profile"] = signup_profile
        captured["state"] = state
        captured.update(kwargs)
        return True, "8352880840", {"8352880840"}, True

    monkeypatch.setattr(
        paypal_bind_executor.payment_form_fields_service,
        "sync_paypal_signup_phone_submission_state",
        fake_sync,
    )

    signup_profile = {"phone": "8352880840"}
    state = {}
    assert paypal_bind_executor._sync_paypal_signup_phone_submission_state(
        signup_profile,
        state,
        signup_submitted=False,
    ) == (True, "8352880840", {"8352880840"}, True)
    assert captured["signup_profile"] is signup_profile
    assert captured["state"] is state
    assert captured["signup_submitted"] is False
    assert captured["normalize_phone"] is paypal_bind_executor._normalize_paypal_phone


def test_stop_before_paypal_signup_otp_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    progress_events = []
    on_progress = progress_events.append

    def fake_stop(**kwargs):
        captured.update(kwargs)
        return True, "", False

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "stop_before_paypal_signup_otp",
        fake_stop,
    )

    state = {}
    signup_profile = {"phone": "+817012345678"}
    assert paypal_bind_executor._stop_before_paypal_signup_otp(
        state=state,
        signup_profile=signup_profile,
        current_url="https://www.paypal.com/checkoutweb/signup",
        on_progress=on_progress,
    ) == (True, "", False)
    assert captured["state"] is state
    assert captured["signup_profile"] is signup_profile
    assert captured["current_url"] == "https://www.paypal.com/checkoutweb/signup"
    assert captured["progress_event"] is paypal_bind_executor._progress_event
    assert captured["on_progress"] is on_progress


def test_maybe_wait_for_paypal_signup_otp_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    progress_events = []
    on_progress = progress_events.append

    def fake_wait(_api, **kwargs):
        captured.update(kwargs)
        return True, "", True

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "maybe_wait_for_paypal_signup_otp",
        fake_wait,
    )

    api = object()
    state = {"signup_submitted": True}
    signup_profile = {"phone": "8352880971"}
    assert paypal_bind_executor._maybe_wait_for_paypal_signup_otp(
        api,
        state=state,
        signup_profile=signup_profile,
        current_url="https://www.paypal.com/checkoutweb/signup",
        on_progress=on_progress,
    ) == (True, "", True)
    assert captured["state"] is state
    assert captured["signup_profile"] is signup_profile
    assert captured["current_url"] == "https://www.paypal.com/checkoutweb/signup"
    assert captured["otp_wait_timeout_seconds"] == paypal_bind_executor.PAYPAL_SIGNUP_OTP_WAIT_TIMEOUT_SECONDS
    assert captured["body_excerpt"] is paypal_bind_executor._body_excerpt
    assert captured["has_otp_inputs"] is paypal_bind_executor._has_paypal_otp_inputs
    assert captured["signup_otp_text_hint"] is paypal_bind_executor._paypal_signup_otp_text_hint
    assert callable(captured["click_create_submit"])
    assert captured["progress_event"] is paypal_bind_executor._progress_event
    assert captured["on_progress"] is on_progress
    assert captured["logger"] is paypal_bind_executor.logger
    assert captured["now"] is paypal_bind_executor.time.time
    assert captured["sleep"] is paypal_bind_executor.time.sleep


def test_submit_paypal_signup_otp_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    progress_events = []
    on_progress = progress_events.append
    def is_cancelled():
        return False

    def fake_submit_otp(_api, **kwargs):
        captured.update(kwargs)
        return True, "", True

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "submit_paypal_signup_otp",
        fake_submit_otp,
    )

    api = object()
    state = {"needs_otp": True}
    signup_profile = {"phone": "8352880971"}
    assert paypal_bind_executor._submit_paypal_signup_otp(
        api,
        signup_profile=signup_profile,
        state=state,
        current_url="https://www.paypal.com/checkoutweb/signup",
        is_cancelled=is_cancelled,
        on_progress=on_progress,
    ) == (True, "", True)
    assert captured["signup_profile"] is signup_profile
    assert captured["state"] is state
    assert captured["current_url"] == "https://www.paypal.com/checkoutweb/signup"
    assert captured["otp_poll_timeout_seconds"] == paypal_bind_executor.PAYPAL_SIGNUP_OTP_POLL_TIMEOUT_SECONDS
    assert captured["is_cancelled"] is is_cancelled
    assert captured["poll_signup_otp"] is paypal_bind_executor._poll_paypal_signup_otp
    assert captured["fill_otp_inputs"] is paypal_bind_executor._fill_paypal_otp_inputs
    assert callable(captured["click_next"])
    assert captured["release_phone_lock"] is paypal_bind_executor._release_paypal_signup_phone_lock
    assert captured["progress_event"] is paypal_bind_executor._progress_event
    assert captured["on_progress"] is on_progress
    assert captured["otp_cancelled_exception"] is GoPayOTPCancelled
    assert captured["sleep"] is paypal_bind_executor.time.sleep


def test_dismiss_paypal_cookie_banner_evaluates_frames_and_waits(monkeypatch):
    calls = []
    waits = []
    click_calls = []

    class FakeFrame:
        def __init__(self, dismissed):
            self.dismissed = dismissed

        def evaluate(self, script):
            calls.append(script)
            return {"dismissed": self.dismissed}

    class FakePage:
        def wait_for_timeout(self, timeout):
            waits.append(timeout)

    class FakeApi:
        page = FakePage()

    monkeypatch.setattr(
        paypal_bind_executor,
        "_iter_page_frames",
        lambda _api: [FakeFrame(False), FakeFrame(True)],
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_click_first",
        lambda api, selectors, timeout_ms: click_calls.append((selectors, timeout_ms)) or False,
    )

    assert paypal_bind_executor._dismiss_paypal_cookie_banner(FakeApi()) is True
    assert click_calls == [(paypal_bind_executor.PAYPAL_COOKIE_BANNER_ACCEPT_SELECTORS, 700)]
    assert calls == [paypal_bind_executor.PAYPAL_COOKIE_BANNER_DISMISS_SCRIPT] * 2
    assert waits == [300]


def test_paypal_cookie_banner_dismiss_only_uses_close_controls():
    selectors = "\n".join(paypal_bind_executor.PAYPAL_COOKIE_BANNER_ACCEPT_SELECTORS)
    assert "Close" in selectors or "閉じる" in selectors
    for forbidden in ("Accept", "Agree", "はい", "同意", "承諾", "すべて同意"):
        assert forbidden not in selectors
    script = paypal_bind_executor.PAYPAL_COOKIE_BANNER_DISMISS_SCRIPT
    assert "accept all" not in script
    assert "|agree|" not in script
    assert "|はい|" not in script
    assert "|同意|" not in script


def test_click_paypal_signup_submit_clears_overlays_before_click(monkeypatch):
    calls = []
    progress_events = []
    api = types.SimpleNamespace()

    monkeypatch.setattr(
        paypal_bind_executor,
        "_dismiss_paypal_cookie_banner",
        lambda _api: calls.append("cookie") or False,
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_dismiss_paypal_prompts",
        lambda _api, on_progress=None: calls.append(("prompts", on_progress)) or False,
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_press_escape_to_dismiss_browser_bubbles",
        lambda _api: calls.append("escape"),
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_click_first",
        lambda _api, selectors, timeout_ms: (_ for _ in ()).throw(AssertionError("selector fallback should not be needed")),
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_js_click_paypal_signup_submit",
        lambda _api: calls.append("js") or True,
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_mark_paypal_signup_submit_clicked",
        lambda _api: calls.append("mark"),
    )

    assert paypal_bind_executor._click_paypal_signup_submit(api, on_progress=progress_events.append) is True
    assert calls == [
        "cookie",
        ("prompts", progress_events.append),
        "escape",
        "cookie",
        "js",
        "mark",
    ]


def test_click_paypal_signup_submit_uses_one_selector_fallback_when_js_finds_no_button(monkeypatch):
    calls = []
    api = types.SimpleNamespace()

    monkeypatch.setattr(paypal_bind_executor, "_dismiss_paypal_cookie_banner", lambda _api: calls.append("cookie") or False)
    monkeypatch.setattr(
        paypal_bind_executor,
        "_dismiss_paypal_prompts",
        lambda _api, on_progress=None: calls.append("prompts") or False,
    )
    monkeypatch.setattr(paypal_bind_executor, "_press_escape_to_dismiss_browser_bubbles", lambda _api: calls.append("escape"))
    monkeypatch.setattr(
        paypal_bind_executor,
        "_click_first",
        lambda _api, selectors, timeout_ms: calls.append(("click", timeout_ms)) or True,
    )
    monkeypatch.setattr(paypal_bind_executor, "_js_click_paypal_signup_submit", lambda _api: calls.append("js") or False)
    monkeypatch.setattr(
        paypal_bind_executor,
        "_mark_paypal_signup_submit_clicked",
        lambda _api: calls.append("mark"),
    )

    assert paypal_bind_executor._click_paypal_signup_submit(api) is True
    assert calls == [
        "cookie",
        "prompts",
        "escape",
        "cookie",
        "js",
        ("click", 1500),
        "mark",
    ]


def test_click_paypal_signup_submit_skips_repeat_click_during_cooldown(monkeypatch):
    api = types.SimpleNamespace(_paypal_signup_submit_clicked_at=100.0)
    monkeypatch.setattr(paypal_bind_executor.time, "monotonic", lambda: 110.0)
    monkeypatch.setattr(
        paypal_bind_executor,
        "_dismiss_paypal_cookie_banner",
        lambda _api: (_ for _ in ()).throw(AssertionError("repeat submit should be skipped")),
    )

    assert paypal_bind_executor._click_paypal_signup_submit(api) is True


def test_js_click_paypal_signup_submit_treats_recent_submit_guard_as_success(monkeypatch):
    waits = []

    class FakeFrame:
        def evaluate(self, script):
            assert script == paypal_bind_executor.PAYPAL_SIGNUP_SUBMIT_CLICK_SCRIPT
            return {"clicked": False, "skipped": True, "reason": "recent_submit"}

    class FakePage:
        def wait_for_timeout(self, timeout_ms):
            waits.append(timeout_ms)

    api = types.SimpleNamespace(page=FakePage())
    monkeypatch.setattr(paypal_bind_executor, "_iter_page_frames", lambda _api: [FakeFrame()])

    assert paypal_bind_executor._js_click_paypal_signup_submit(api) is True
    assert waits == [500]


def test_handle_paypal_signup_submitted_phase_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    progress_events = []
    on_progress = progress_events.append
    def is_cancelled():
        return False

    def fake_handle(_api, **kwargs):
        captured.update(kwargs)
        return True, "", True

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_signup_submitted_phase",
        fake_handle,
    )

    api = object()
    signup_profile = {"phone": "8352880971"}
    state = {"signup_submitted": True}
    assert paypal_bind_executor._handle_paypal_signup_submitted_phase(
        api,
        signup_profile=signup_profile,
        state=state,
        card_retry_count=2,
        current_url="https://www.paypal.com/checkoutweb/signup",
        is_cancelled=is_cancelled,
        on_progress=on_progress,
    ) == (True, "", True)
    assert captured["signup_profile"] is signup_profile
    assert captured["state"] is state
    assert captured["card_retry_count"] == 2
    assert captured["current_url"] == "https://www.paypal.com/checkoutweb/signup"
    assert captured["is_cancelled"] is is_cancelled
    assert captured["visible_validation_error"] is paypal_bind_executor._paypal_signup_visible_validation_error
    assert captured["release_phone_lock"] is paypal_bind_executor._release_paypal_signup_phone_lock
    assert captured["retry_card_rejected"] is paypal_bind_executor._retry_paypal_signup_after_card_rejected
    assert captured["stop_before_signup_otp_enabled"] is paypal_bind_executor._paypal_stop_before_signup_otp_enabled
    assert captured["body_excerpt"] is paypal_bind_executor._body_excerpt
    assert captured["has_otp_inputs"] is paypal_bind_executor._has_paypal_otp_inputs
    assert captured["signup_otp_text_hint"] is paypal_bind_executor._paypal_signup_otp_text_hint
    assert captured["stop_before_otp"] is paypal_bind_executor._stop_before_paypal_signup_otp
    assert captured["maybe_wait_for_otp"] is paypal_bind_executor._maybe_wait_for_paypal_signup_otp
    assert captured["submit_otp"] is paypal_bind_executor._submit_paypal_signup_otp
    assert captured["on_progress"] is on_progress
    assert captured["sleep"] is paypal_bind_executor.time.sleep


def test_submit_paypal_login_step_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    progress_events = []
    on_progress = progress_events.append

    def fake_submit_login(_api, **kwargs):
        captured.update(kwargs)
        return True, ""

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "submit_paypal_login_step",
        fake_submit_login,
    )

    api = object()
    credentials = {"email": "existing@example.com", "password": "Secret123!"}
    state = {"login_phase": "login_combined"}
    assert paypal_bind_executor._submit_paypal_login_step(
        api,
        credentials=credentials,
        state=state,
        on_progress=on_progress,
    ) == (True, "")
    assert captured["credentials"] is credentials
    assert captured["state"] is state
    assert captured["next_selectors"] == paypal_bind_executor.PAYPAL_NEXT_SELECTORS
    assert captured["set_locator_value"] is paypal_bind_executor._set_locator_value
    assert callable(captured["click_first"])
    assert captured["progress_event"] is paypal_bind_executor._progress_event
    assert captured["on_progress"] is on_progress
    assert captured["sleep"] is paypal_bind_executor.time.sleep


def test_click_paypal_approve_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    progress_events = []
    on_progress = progress_events.append

    def fake_click_approve(_api, **kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "click_paypal_approve",
        fake_click_approve,
    )

    api = object()
    assert paypal_bind_executor._click_paypal_approve(api, on_progress=on_progress) is True
    assert captured["approve_selectors"] == paypal_bind_executor.PAYPAL_APPROVE_SELECTORS
    assert callable(captured["click_first"])
    assert captured["progress_event"] is paypal_bind_executor._progress_event
    assert captured["on_progress"] is on_progress


def test_paypal_create_account_and_email_step_wrappers_pass_browser_dependencies(monkeypatch):
    create_captured = {}
    step_captured = {}
    wait_captured = {}
    progress_events = []
    on_progress = progress_events.append

    def fake_click_create(_api, **kwargs):
        create_captured.update(kwargs)
        return True

    def fake_step_advanced(_api, before_url, **kwargs):
        step_captured.update({"before_url": before_url, **kwargs})
        return True

    def fake_wait_step(_api, before_url, **kwargs):
        wait_captured.update({"before_url": before_url, **kwargs})
        return True

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "click_paypal_create_account",
        fake_click_create,
    )
    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_signup_email_step_advanced",
        fake_step_advanced,
    )
    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "wait_paypal_signup_email_step_advanced",
        fake_wait_step,
    )

    api = object()
    assert paypal_bind_executor._click_paypal_create_account(api, on_progress=on_progress) is True
    assert create_captured["create_account_selectors"] == paypal_bind_executor.PAYPAL_CREATE_ACCOUNT_SELECTORS
    assert callable(create_captured["click_first"])
    assert create_captured["progress_event"] is paypal_bind_executor._progress_event
    assert create_captured["on_progress"] is on_progress

    assert paypal_bind_executor._paypal_signup_email_step_advanced(api, "https://www.paypal.com/pay") is True
    assert step_captured["before_url"] == "https://www.paypal.com/pay"
    assert step_captured["sync_payment_page"] is paypal_bind_executor._sync_relevant_payment_page
    assert step_captured["is_pay_entry_url"] is paypal_bind_executor._is_paypal_pay_entry_url
    assert step_captured["inspect_page"] is paypal_bind_executor._inspect_paypal_page

    assert (
        paypal_bind_executor._wait_paypal_signup_email_step_advanced(
            api,
            "https://www.paypal.com/pay",
            timeout_seconds=3.5,
        )
        is True
    )
    assert wait_captured["before_url"] == "https://www.paypal.com/pay"
    assert wait_captured["step_advanced"] is paypal_bind_executor._paypal_signup_email_step_advanced
    assert wait_captured["timeout_seconds"] == 3.5


def test_js_click_paypal_signup_email_submit_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}

    def fake_js_click(_api, **kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "js_click_paypal_signup_email_submit",
        fake_js_click,
    )

    api = object()
    assert paypal_bind_executor._js_click_paypal_signup_email_submit(api) is True
    assert captured["frames"] is paypal_bind_executor._iter_page_frames
    assert captured["logger"] is paypal_bind_executor.logger


def test_paypal_email_spinner_and_gate_wrappers_delegate_to_browser_service(monkeypatch):
    captured = {}

    def fake_recover(api, email):
        captured["recover"] = (api, email)
        return {"recovered": True, "detail": "ok"}

    def fake_gate(api):
        captured["gate"] = api
        return {"controls": []}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "js_recover_paypal_email_spinner",
        fake_recover,
    )
    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "inspect_paypal_email_gate",
        fake_gate,
    )

    api = object()
    assert paypal_bind_executor._js_recover_paypal_email_spinner(api, "demo@example.com") == {
        "recovered": True,
        "detail": "ok",
    }
    assert captured["recover"] == (api, "demo@example.com")

    assert paypal_bind_executor._inspect_paypal_email_gate(api) == {"controls": []}
    assert captured["gate"] is api


def test_submit_paypal_signup_email_step_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    progress_events = []
    on_progress = progress_events.append

    def fake_submit_email(_api, **kwargs):
        captured.update(kwargs)
        return True, ""

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "submit_paypal_signup_email_step",
        fake_submit_email,
    )

    api = object()
    signup_profile = {"email": "demo@example.com"}
    state = {"email_locator": object()}
    assert paypal_bind_executor._submit_paypal_signup_email_step(
        api,
        signup_profile=signup_profile,
        state=state,
        on_progress=on_progress,
    ) == (True, "")
    assert captured["signup_profile"] is signup_profile
    assert captured["state"] is state
    assert captured["submit_selectors"] == paypal_bind_executor.PAYPAL_SIGNUP_EMAIL_SUBMIT_SELECTORS
    assert captured["set_locator_value"] is paypal_bind_executor._set_locator_value
    assert callable(captured["click_first"])
    assert captured["wait_step_advanced"] is paypal_bind_executor._wait_paypal_signup_email_step_advanced
    assert captured["js_click_submit"] is paypal_bind_executor._js_click_paypal_signup_email_submit
    assert captured["inspect_gate"] is paypal_bind_executor._inspect_paypal_email_gate
    assert captured["body_excerpt"] is paypal_bind_executor._body_excerpt
    assert captured["progress_event"] is paypal_bind_executor._progress_event
    assert captured["on_progress"] is on_progress
    assert captured["logger"] is paypal_bind_executor.logger
    assert captured["url_summary"] is paypal_bind_executor._safe_url_summary
    assert captured["compact_log_text"] is paypal_bind_executor._compact_log_text


def test_replace_paypal_signup_phone_wrapper_passes_form_dependencies(monkeypatch):
    captured = {}
    progress_events = []
    on_progress = progress_events.append

    def fake_replace_phone(_api, **kwargs):
        captured.update(kwargs)
        return True, ""

    monkeypatch.setattr(
        paypal_bind_executor.payment_form_fields_service,
        "replace_paypal_signup_phone",
        fake_replace_phone,
    )

    api = object()
    signup_profile = {"phone": "8352880971", "country": "US"}
    assert paypal_bind_executor._replace_paypal_signup_phone(
        api,
        signup_profile=signup_profile,
        on_progress=on_progress,
    ) == (True, "")
    assert captured["signup_profile"] is signup_profile
    assert captured["phone_selectors"] == paypal_bind_executor.PAYPAL_PHONE_SELECTORS
    assert captured["phone_value_valid"] is paypal_bind_executor._paypal_phone_value_valid
    assert callable(captured["set_first_visible_value_with_locator"])
    assert captured["set_verified_value"] is paypal_bind_executor._set_verified_locator_value
    assert captured["read_value"] is paypal_bind_executor._read_locator_value
    assert captured["on_progress"] is on_progress
    assert captured["progress_event"] is paypal_bind_executor._progress_event


def test_replace_paypal_signup_card_wrapper_passes_form_dependencies(monkeypatch):
    captured = {}
    progress_events = []
    on_progress = progress_events.append

    def fake_replace_card(_api, **kwargs):
        captured.update(kwargs)
        return True, ""

    monkeypatch.setattr(
        paypal_bind_executor.payment_form_fields_service,
        "replace_paypal_signup_card",
        fake_replace_card,
    )

    api = object()
    signup_profile = {}
    assert paypal_bind_executor._replace_paypal_signup_card(
        api,
        signup_profile=signup_profile,
        on_progress=on_progress,
    ) == (True, "")
    assert captured["signup_profile"] is signup_profile
    assert captured["card_number_selectors"] == paypal_bind_executor.PAYPAL_CARD_NUMBER_SELECTORS
    assert captured["card_expiry_selectors"] == paypal_bind_executor.PAYPAL_CARD_EXPIRY_SELECTORS
    assert captured["card_cvv_selectors"] == paypal_bind_executor.PAYPAL_CARD_CVV_SELECTORS
    assert captured["generate_card_number"] is paypal_bind_executor._generate_paypal_card_number
    assert captured["generate_card_expiry"] is paypal_bind_executor._generate_paypal_card_expiry
    assert captured["generate_card_cvv"] is paypal_bind_executor._generate_paypal_card_cvv
    assert callable(captured["set_first_visible_value_with_locator"])
    assert captured["set_verified_value"] is paypal_bind_executor._set_verified_locator_value
    assert captured["read_value"] is paypal_bind_executor._read_locator_value
    assert captured["progress_event"] is paypal_bind_executor._progress_event
    assert captured["on_progress"] is on_progress


def test_retry_paypal_signup_after_card_rejected_wrapper_passes_form_dependencies(monkeypatch):
    captured = {}
    progress_events = []
    on_progress = progress_events.append

    def fake_retry(_api, **kwargs):
        captured.update(kwargs)
        return True, "", True

    monkeypatch.setattr(
        paypal_bind_executor.payment_form_fields_service,
        "retry_paypal_signup_after_card_rejected",
        fake_retry,
    )

    api = object()
    signup_profile = {"phone": "8352880971"}
    state = {"card_rejected": True}
    assert paypal_bind_executor._retry_paypal_signup_after_card_rejected(
        api,
        signup_profile=signup_profile,
        state=state,
        card_retry_count=2,
        current_url="https://www.paypal.com/checkoutweb/signup",
        on_progress=on_progress,
    ) == (True, "", True)
    assert captured["signup_profile"] is signup_profile
    assert captured["state"] is state
    assert captured["card_retry_count"] == 2
    assert captured["current_url"] == "https://www.paypal.com/checkoutweb/signup"
    assert captured["replace_signup_card"] is paypal_bind_executor._replace_paypal_signup_card
    assert captured["ensure_phone_lock"] is paypal_bind_executor._ensure_paypal_signup_phone_lock
    assert captured["release_phone_lock"] is paypal_bind_executor._release_paypal_signup_phone_lock
    assert captured["verify_required_values"] is paypal_bind_executor._verify_paypal_signup_required_values
    assert callable(captured["click_submit"])
    assert captured["progress_event"] is paypal_bind_executor._progress_event
    assert captured["on_progress"] is on_progress
    assert captured["now"] is paypal_bind_executor.time.time
    assert captured["sleep"] is paypal_bind_executor.time.sleep


def test_retry_paypal_signup_after_phone_rejected_wrapper_passes_form_dependencies(monkeypatch):
    captured = {}
    progress_events = []
    on_progress = progress_events.append

    def fake_retry(_api, **kwargs):
        captured.update(kwargs)
        return True, "", True

    monkeypatch.setattr(
        paypal_bind_executor.payment_form_fields_service,
        "retry_paypal_signup_after_phone_rejected",
        fake_retry,
    )

    api = object()
    signup_profile = {"phone": "8352880971"}
    state = {"phone_only_retry": True}
    submitted_phone_keys = {"8352881474"}
    assert paypal_bind_executor._retry_paypal_signup_after_phone_rejected(
        api,
        signup_profile=signup_profile,
        state=state,
        phone_key="8352880971",
        submitted_phone_keys=submitted_phone_keys,
        current_url="https://www.paypal.com/checkoutweb/signup",
        on_progress=on_progress,
    ) == (True, "", True)
    assert captured["signup_profile"] is signup_profile
    assert captured["state"] is state
    assert captured["phone_key"] == "8352880971"
    assert captured["submitted_phone_keys"] is submitted_phone_keys
    assert captured["current_url"] == "https://www.paypal.com/checkoutweb/signup"
    assert captured["ensure_phone_lock"] is paypal_bind_executor._ensure_paypal_signup_phone_lock
    assert captured["replace_signup_phone"] is paypal_bind_executor._replace_paypal_signup_phone
    assert captured["release_phone_lock"] is paypal_bind_executor._release_paypal_signup_phone_lock
    assert captured["verify_required_values"] is paypal_bind_executor._verify_paypal_signup_required_values
    assert callable(captured["click_submit"])
    assert captured["progress_event"] is paypal_bind_executor._progress_event
    assert captured["on_progress"] is on_progress
    assert captured["now"] is paypal_bind_executor.time.time
    assert captured["sleep"] is paypal_bind_executor.time.sleep


def test_submit_paypal_signup_registration_form_wrapper_passes_form_dependencies(monkeypatch):
    captured = {}
    progress_events = []
    on_progress = progress_events.append

    def fake_submit(_api, **kwargs):
        captured.update(kwargs)
        return True, "", True

    monkeypatch.setattr(
        paypal_bind_executor.payment_form_fields_service,
        "submit_paypal_signup_registration_form",
        fake_submit,
    )

    api = object()
    signup_profile = {"phone": "8352880971"}
    state = {}
    submitted_phone_keys = set()
    assert paypal_bind_executor._submit_paypal_signup_registration_form(
        api,
        signup_profile=signup_profile,
        state=state,
        phone_key="8352880971",
        submitted_phone_keys=submitted_phone_keys,
        current_url="https://www.paypal.com/checkoutweb/signup",
        on_progress=on_progress,
    ) == (True, "", True)
    assert captured["signup_profile"] is signup_profile
    assert captured["state"] is state
    assert captured["phone_key"] == "8352880971"
    assert captured["submitted_phone_keys"] is submitted_phone_keys
    assert captured["current_url"] == "https://www.paypal.com/checkoutweb/signup"
    assert captured["wait_dom_loaded"] is paypal_bind_executor._wait_paypal_signup_registration_dom
    assert captured["ensure_phone_lock"] is paypal_bind_executor._ensure_paypal_signup_phone_lock
    assert captured["fill_signup_form"] is paypal_bind_executor._fill_paypal_signup_form
    assert captured["release_phone_lock"] is paypal_bind_executor._release_paypal_signup_phone_lock
    assert captured["verify_required_values"] is paypal_bind_executor._verify_paypal_signup_required_values
    assert callable(captured["click_submit"])
    assert captured["progress_event"] is paypal_bind_executor._progress_event
    assert captured["on_progress"] is on_progress
    assert captured["logger"] is paypal_bind_executor.logger
    assert captured["now"] is paypal_bind_executor.time.time
    assert captured["sleep"] is paypal_bind_executor.time.sleep


def test_verify_paypal_signup_required_values_wrapper_passes_form_dependencies(monkeypatch):
    captured = {}

    def fake_verify(signup_profile, **kwargs):
        captured["signup_profile"] = signup_profile
        captured.update(kwargs)
        return True, ""

    monkeypatch.setattr(
        paypal_bind_executor.payment_form_fields_service,
        "verify_paypal_signup_required_values",
        fake_verify,
    )

    api = object()
    signup_profile = {"phone": "8352880971", "country": "US"}
    assert paypal_bind_executor._verify_paypal_signup_required_values(api, signup_profile) == (True, "")
    assert captured["signup_profile"] is signup_profile
    assert captured["phone_selectors"] == paypal_bind_executor.PAYPAL_PHONE_SELECTORS
    assert captured["card_number_selectors"] == paypal_bind_executor.PAYPAL_CARD_NUMBER_SELECTORS
    assert captured["card_expiry_selectors"] == paypal_bind_executor.PAYPAL_CARD_EXPIRY_SELECTORS
    assert captured["card_cvv_selectors"] == paypal_bind_executor.PAYPAL_CARD_CVV_SELECTORS
    assert captured["password_selectors"] == paypal_bind_executor.PAYPAL_PASSWORD_SELECTORS
    assert captured["first_name_selectors"] == paypal_bind_executor.PAYPAL_FIRST_NAME_SELECTORS
    assert captured["last_name_selectors"] == paypal_bind_executor.PAYPAL_LAST_NAME_SELECTORS
    assert captured["address1_selectors"] == paypal_bind_executor.PAYPAL_BILLING_LINE1_SELECTORS
    assert captured["city_selectors"] == paypal_bind_executor.PAYPAL_BILLING_CITY_SELECTORS
    assert captured["postal_selectors"] == paypal_bind_executor.PAYPAL_BILLING_POSTAL_SELECTORS
    assert captured["state_selectors"] == paypal_bind_executor.PAYPAL_BILLING_STATE_SELECTORS
    assert captured["phone_value_valid"] is paypal_bind_executor._paypal_phone_value_valid
    assert callable(captured["visible_locator"])
    assert captured["read_value"] is paypal_bind_executor._read_locator_value
    assert captured["field_value_matches"] is paypal_bind_executor._field_value_matches


def test_stripe_runtime_checksums_match_checkout_encoding():
    assert _stripe_js_checksum("pm_1TcY9qC6h1nxGoI3nnzNhtsS") == "qto~d^n0=QU>azbu]]ew#CoPd&m_]}q`U|_Oe}l>DWmcQ=ato?"
    assert _stripe_rv_timestamp().startswith("qto>n<Q=U&CyY&`>X^r<YNr<YN`")


def test_paypal_protocol_extracts_escaped_redirect_url():
    payload = {
        "setup_intent": {
            "next_action": {
                "redirect_to_url": {
                    "url": (
                        '{"href":"https:\\/\\/www.paypal.com\\/agreements\\/approve'
                        '?ba_token=BA-ESCAPED\\u0026country.x=US"}'
                    )
                }
            }
        }
    }

    url = paypal_bind_executor._find_paypal_redirect_url(payload)

    assert url == "https://www.paypal.com/agreements/approve?ba_token=BA-ESCAPED&country.x=US"


def test_paypal_protocol_resolve_accepts_pay_route_token_without_extra_http():
    http = FakeHttp([])

    approve_url, ba_token = paypal_bind_executor._paypal_protocol_resolve_approve_url(
        http,
        "https://www.paypal.com/pay?token=BA-PAYTOKEN&ul=1",
    )

    assert approve_url == "https://www.paypal.com/pay?token=BA-PAYTOKEN&ul=1"
    assert ba_token == "BA-PAYTOKEN"
    assert http.requests == []


def test_paypal_protocol_resolve_rejects_lookalike_paypal_host():
    http = FakeHttp([])

    approve_url, ba_token = paypal_bind_executor._paypal_protocol_resolve_approve_url(
        http,
        "https://evilpaypal.com/pay?token=BA-PAYTOKEN&ul=1",
    )

    assert approve_url == "https://evilpaypal.com/pay?token=BA-PAYTOKEN&ul=1"
    assert ba_token == "BA-PAYTOKEN"
    assert http.requests == []


def test_paypal_protocol_resolve_reads_html_location_redirect():
    http = FakeHttp(
        [
            (
                "GET",
                "pm-redirects.stripe.com/authorize",
                FakeResponse(
                    text=(
                        '<script>window.location = "https:\\/\\/www.paypal.com\\/agreements\\/approve'
                        '?ba_token=BA-HTML\\u0026country.x=US";</script>'
                    )
                ),
            )
        ]
    )

    approve_url, ba_token = paypal_bind_executor._paypal_protocol_resolve_approve_url(
        http,
        "https://pm-redirects.stripe.com/authorize",
    )

    assert approve_url == "https://www.paypal.com/agreements/approve?ba_token=BA-HTML&country.x=US"
    assert ba_token == "BA-HTML"


def test_paypal_checkout_payload_defaults_to_usd_for_paypal():
    payload = paypal_bind_executor._paypal_checkout_payload()

    assert payload["billing_details"]["country"] == "US"
    assert payload["billing_details"]["currency"] == "USD"
    assert payload["checkout_ui_mode"] == "hosted"


def test_paypal_extract_ba_link_uses_opll_eu_mode(monkeypatch):
    chat_http = FakeHttp(
        [
            ("GET", "chatgpt.com/backend-api/sentinel/ping", FakeResponse(json_data={"ok": True})),
            (
                "POST",
                "chatgpt.com/backend-api/payments/checkout",
                FakeResponse(
                    json_data={
                        "checkout_session_id": "cs_live_test",
                        "processor_entity": "openai_ie",
                        "stripe_publishable_key": "pk_live_TEST",
                    }
                ),
            ),
        ]
    )
    stripe_http = FakeHttp(
        [
            (
                "POST",
                "/v1/payment_pages/cs_live_test/init",
                FakeResponse(
                    json_data={
                        "init_checksum": "init",
                        "config_id": "cfg",
                        "currency": "eur",
                        "total_summary": {"due": 0},
                        "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_live_test",
                        "payment_method_types": ["card", "paypal"],
                    }
                ),
            ),
            ("POST", "/v1/payment_methods", FakeResponse(json_data={"id": "pm_test"})),
            (
                "POST",
                "/v1/payment_pages/cs_live_test/confirm",
                FakeResponse(
                    json_data={
                        "setup_intent": {
                            "next_action": {
                                "type": "redirect_to_url",
                                "redirect_to_url": {"url": "https://pm-redirects.stripe.com/authorize/test"},
                            },
                        }
                    }
                ),
            ),
        ]
    )
    sessions = [chat_http, stripe_http]
    session_proxy_urls = []

    def fake_new_http_session(proxy_url, **kwargs):
        session_proxy_urls.append(proxy_url)
        return sessions.pop(0)

    monkeypatch.setattr(paypal_bind_executor, "_new_http_session", fake_new_http_session)
    monkeypatch.setattr(paypal_bind_executor, "_configure_chatgpt_http_session", lambda *args, **kwargs: None)
    monkeypatch.setattr(paypal_bind_executor.time, "sleep", lambda *_args, **_kwargs: None)

    result = paypal_bind_executor._paypal_extract_ba_link_python(
        access_token="token",
        proxy_url="socks5h://jp.example:1080",
        provider_proxy_url="socks5h://us.example:1080",
        paypal_ba_mode="eu",
        timeout_seconds=1,
    )

    assert result["status"] == "success"
    assert result["ba_token"] == ""
    assert result["approve_url"] == "https://pm-redirects.stripe.com/authorize/test"
    assert result["provider_redirect_url"] == "https://pm-redirects.stripe.com/authorize/test"
    assert result["payment_link_type"] == "paypal_redirect"
    assert result["checkout_session_id"] == "cs_live_test"
    assert result["pm_id"] == "pm_test"
    assert result["checkout_url"] == "https://pay.openai.com/c/pay/cs_live_test"
    assert result["hosted_checkout_url"] == "https://pay.openai.com/c/pay/cs_live_test"
    assert result["paypal_ba_mode"] == "eu"
    assert session_proxy_urls == ["socks5h://jp.example:1080", "socks5h://jp.example:1080"]

    checkout_request = next(request for request in chat_http.requests if request["url"].endswith("/payments/checkout"))
    assert checkout_request["kwargs"]["json"]["billing_details"] == {"country": "FR", "currency": "EUR"}
    assert checkout_request["kwargs"]["json"]["checkout_ui_mode"] == "custom"

    payment_method_request = next(
        request for request in stripe_http.requests if request["url"].endswith("/v1/payment_methods")
    )
    confirm_request = next(request for request in stripe_http.requests if request["url"].endswith("/confirm"))
    assert payment_method_request["kwargs"]["data"]["billing_details[address][country]"] == "US"
    assert confirm_request["kwargs"]["data"]["payment_method"] == "pm_test"
    assert confirm_request["kwargs"]["data"]["expected_payment_method_type"] == "paypal"
    assert len(chat_http.responses) == 0
    assert len(stripe_http.responses) == 0


def test_paypal_extract_ba_link_uses_opll_br_mode(monkeypatch):
    chat_http = FakeHttp(
        [
            ("GET", "chatgpt.com/backend-api/sentinel/ping", FakeResponse(json_data={"ok": True})),
            (
                "POST",
                "chatgpt.com/backend-api/payments/checkout",
                FakeResponse(
                    json_data={
                        "checkout_session_id": "cs_live_br",
                        "processor_entity": "openai_ie",
                        "stripe_publishable_key": "pk_live_BR",
                    }
                ),
            ),
        ]
    )
    stripe_http = FakeHttp(
        [
            (
                "POST",
                "/v1/payment_pages/cs_live_br/init",
                FakeResponse(
                    json_data={
                        "init_checksum": "init-br",
                        "config_id": "cfg-br",
                        "currency": "brl",
                        "total_summary": {"due": 0},
                        "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_live_br",
                        "payment_method_types": ["card", "paypal"],
                    }
                ),
            ),
            ("POST", "/v1/payment_methods", FakeResponse(json_data={"id": "pm_br"})),
            (
                "POST",
                "/v1/payment_pages/cs_live_br/confirm",
                FakeResponse(
                    json_data={
                        "next_action": {
                            "type": "redirect_to_url",
                            "redirect_to_url": {"url": "https://pm-redirects.stripe.com/authorize/br"},
                        }
                    }
                ),
            ),
        ]
    )
    sessions = [chat_http, stripe_http]
    session_proxy_urls = []

    def fake_new_http_session(proxy_url, **kwargs):
        session_proxy_urls.append(proxy_url)
        return sessions.pop(0)

    monkeypatch.setattr(paypal_bind_executor, "_new_http_session", fake_new_http_session)
    monkeypatch.setattr(paypal_bind_executor, "_configure_chatgpt_http_session", lambda *args, **kwargs: None)
    monkeypatch.setattr(paypal_bind_executor.time, "sleep", lambda *_args, **_kwargs: None)

    result = paypal_bind_executor._paypal_extract_ba_link_python(
        access_token="token",
        proxy_url="socks5h://jp.example:1080",
        provider_proxy_url="socks5h://us.example:1080",
        paypal_ba_mode="br",
        timeout_seconds=1,
    )

    assert result["status"] == "success"
    assert result["ba_token"] == ""
    assert result["approve_url"] == "https://pm-redirects.stripe.com/authorize/br"
    assert result["provider_redirect_url"] == "https://pm-redirects.stripe.com/authorize/br"
    assert result["payment_link_type"] == "paypal_redirect"
    assert result["checkout_session_id"] == "cs_live_br"
    assert result["pm_id"] == "pm_br"
    assert result["checkout_url"] == "https://pay.openai.com/c/pay/cs_live_br"
    assert result["hosted_checkout_url"] == "https://pay.openai.com/c/pay/cs_live_br"
    assert result["paypal_ba_mode"] == "br"
    assert session_proxy_urls == ["socks5h://jp.example:1080", "socks5h://jp.example:1080"]

    checkout_request = next(request for request in chat_http.requests if request["url"].endswith("/payments/checkout"))
    assert checkout_request["kwargs"]["json"]["billing_details"] == {"country": "BR", "currency": "BRL"}
    assert checkout_request["kwargs"]["json"]["checkout_ui_mode"] == "custom"

    payment_method_request = next(
        request for request in stripe_http.requests if request["url"].endswith("/v1/payment_methods")
    )
    assert payment_method_request["kwargs"]["data"]["billing_details[address][country]"] == "BR"
    assert payment_method_request["kwargs"]["data"]["billing_details[address][state]"] == "BR"
    assert payment_method_request["kwargs"]["data"]["billing_details[phone]"].startswith("+55")
    assert len(chat_http.responses) == 0
    assert len(stripe_http.responses) == 0


def test_paypal_extract_ba_link_accepts_pm_redirect_when_link_shortcut_available(monkeypatch):
    chat_http = FakeHttp(
        [
            ("GET", "chatgpt.com/backend-api/sentinel/ping", FakeResponse(json_data={"ok": True})),
            (
                "POST",
                "chatgpt.com/backend-api/payments/checkout",
                FakeResponse(
                    json_data={
                        "checkout_session_id": "cs_live_fake_link",
                        "processor_entity": "openai_llc",
                        "stripe_publishable_key": "pk_live_FAKE",
                    }
                ),
            ),
        ]
    )
    stripe_http = FakeHttp(
        [
            (
                "POST",
                "/v1/payment_pages/cs_live_fake_link/init",
                FakeResponse(
                    json_data={
                        "init_checksum": "init-fake",
                        "config_id": "cfg-fake",
                        "currency": "usd",
                        "total_summary": {"due": 0},
                        "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_live_fake_link",
                        "payment_method_types": ["card", "link", "paypal"],
                    }
                ),
            ),
            ("POST", "/v1/payment_methods", FakeResponse(json_data={"id": "pm_fake_link"})),
            (
                "POST",
                "/v1/payment_pages/cs_live_fake_link/confirm",
                FakeResponse(
                    json_data={
                        "next_action": {
                            "type": "redirect_to_url",
                            "redirect_to_url": {"url": "https://pm-redirects.stripe.com/authorize/fake-link"},
                        }
                    }
                ),
            ),
        ]
    )
    sessions = [chat_http, stripe_http]

    def fake_new_http_session(proxy_url, **kwargs):
        return sessions.pop(0)

    monkeypatch.setattr(paypal_bind_executor, "_new_http_session", fake_new_http_session)
    monkeypatch.setattr(paypal_bind_executor, "_configure_chatgpt_http_session", lambda *args, **kwargs: None)
    monkeypatch.setattr(paypal_bind_executor.time, "sleep", lambda *_args, **_kwargs: None)

    result = paypal_bind_executor._paypal_extract_ba_link_python(
        access_token="token",
        proxy_url="socks5h://br.example:1080",
        provider_proxy_url="socks5h://br.example:1080",
        paypal_ba_mode="us",
        timeout_seconds=1,
    )

    assert result["status"] == "success"
    assert result["ba_token"] == ""
    assert result["approve_url"] == "https://pm-redirects.stripe.com/authorize/fake-link"
    assert result["provider_redirect_url"] == "https://pm-redirects.stripe.com/authorize/fake-link"
    assert result["payment_link_type"] == "paypal_redirect"
    assert result["link_shortcut_available"] is True
    assert result["checkout_session_id"] == "cs_live_fake_link"
    assert result["checkout_url"] == "https://pay.openai.com/c/pay/cs_live_fake_link"
    assert result["paypal_ba_mode"] == "us"
    assert len(stripe_http.responses) == 0
    assert any(request["url"].endswith("/v1/payment_methods") for request in stripe_http.requests)


def test_paypal_extract_ba_link_retries_curl_dns_thread_failure_with_requests(monkeypatch):
    curl_chat_http = FakeHttp(
        [
            ("GET", "chatgpt.com/backend-api/sentinel/ping", RuntimeError("curl: (6) getaddrinfo() thread failed to start")),
            ("POST", "chatgpt.com/backend-api/payments/checkout", RuntimeError("curl: (6) getaddrinfo() thread failed to start")),
        ]
    )
    curl_chat_http._autotoken_transport = "curl_cffi"
    curl_stripe_http = FakeHttp([])
    curl_stripe_http._autotoken_transport = "curl_cffi"
    requests_chat_http = FakeHttp(
        [
            ("GET", "chatgpt.com/backend-api/sentinel/ping", FakeResponse(json_data={"ok": True})),
            (
                "POST",
                "chatgpt.com/backend-api/payments/checkout",
                FakeResponse(
                    json_data={
                        "checkout_session_id": "cs_live_retry",
                        "processor_entity": "openai_llc",
                        "stripe_publishable_key": "pk_live_RETRY",
                    }
                ),
            ),
        ]
    )
    requests_chat_http._autotoken_transport = "requests"
    requests_stripe_http = FakeHttp(
        [
            (
                "POST",
                "/v1/payment_pages/cs_live_retry/init",
                FakeResponse(
                    json_data={
                        "init_checksum": "init-retry",
                        "config_id": "cfg-retry",
                        "currency": "usd",
                        "total_summary": {"due": 0},
                        "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_live_retry",
                        "payment_method_types": ["card", "link", "paypal"],
                    }
                ),
            ),
            ("POST", "/v1/payment_methods", FakeResponse(json_data={"id": "pm_retry"})),
            (
                "POST",
                "/v1/payment_pages/cs_live_retry/confirm",
                FakeResponse(
                    json_data={
                        "next_action": {
                            "type": "redirect_to_url",
                            "redirect_to_url": {"url": "https://pm-redirects.stripe.com/authorize/retry"},
                        }
                    }
                ),
            ),
        ]
    )
    requests_stripe_http._autotoken_transport = "requests"
    sessions = [curl_chat_http, curl_stripe_http, requests_chat_http, requests_stripe_http]
    force_requests_flags = []

    def fake_new_http_session(proxy_url, **kwargs):
        force_requests_flags.append(bool(kwargs.get("force_requests")))
        return sessions.pop(0)

    monkeypatch.setattr(paypal_bind_executor, "_new_http_session", fake_new_http_session)
    monkeypatch.setattr(paypal_bind_executor, "_configure_chatgpt_http_session", lambda *args, **kwargs: None)
    monkeypatch.setattr(paypal_bind_executor.time, "sleep", lambda *_args, **_kwargs: None)

    result = paypal_bind_executor._paypal_extract_ba_link_python(
        access_token="token",
        proxy_url="socks5h://br.example:1080",
        provider_proxy_url="socks5h://br.example:1080",
        paypal_ba_mode="us",
        timeout_seconds=1,
    )

    assert result["status"] == "success"
    assert result["approve_url"] == "https://pm-redirects.stripe.com/authorize/retry"
    assert result["payment_link_type"] == "paypal_redirect"
    assert result["checkout_session_id"] == "cs_live_retry"
    assert force_requests_flags == [False, False, True, True]
    assert len(requests_stripe_http.responses) == 0
    assert any(request["url"].endswith("/v1/payment_methods") for request in requests_stripe_http.requests)


def test_paypal_extract_ba_link_uses_opll_custom_checkout_and_approve_poll(monkeypatch):
    chat_http = FakeHttp(
        [
            ("GET", "chatgpt.com/backend-api/sentinel/ping", FakeResponse(json_data={"ok": True})),
            (
                "POST",
                "chatgpt.com/backend-api/payments/checkout",
                FakeResponse(
                    json_data={
                        "checkout_session_id": "cs_live_opll",
                        "processor_entity": "openai_llc",
                        "stripe_publishable_key": "pk_live_OPLL",
                    }
                ),
            ),
            ("GET", "chatgpt.com/backend-api/sentinel/ping", FakeResponse(json_data={"ok": True})),
            (
                "POST",
                "chatgpt.com/backend-api/payments/checkout/approve",
                FakeResponse(json_data={"result": "approved"}),
            ),
        ]
    )
    stripe_http = FakeHttp(
        [
            (
                "POST",
                "/v1/payment_pages/cs_live_opll/init",
                FakeResponse(
                    json_data={
                        "init_checksum": "init-opll",
                        "config_id": "cfg-opll",
                        "currency": "usd",
                        "total_summary": {"due": 0},
                        "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_live_opll",
                        "payment_method_types": ["card", "paypal"],
                    }
                ),
            ),
            ("POST", "/v1/payment_methods", FakeResponse(json_data={"id": "pm_opll"})),
            (
                "POST",
                "/v1/payment_pages/cs_live_opll/confirm",
                FakeResponse(json_data={"submission_attempt": {"state": "requires_approval"}}),
            ),
            (
                "GET",
                "/v1/payment_pages/cs_live_opll",
                FakeResponse(
                    json_data={
                        "setup_intent": {
                            "next_action": {
                                "type": "redirect_to_url",
                                "redirect_to_url": {"url": "https://pm-redirects.stripe.com/authorize/opll"},
                            }
                        }
                    }
                ),
            ),
        ]
    )
    sessions = [chat_http, stripe_http]
    session_proxy_urls = []

    def fake_new_http_session(proxy_url, **kwargs):
        session_proxy_urls.append(proxy_url)
        return sessions.pop(0)

    progress_events = []
    monkeypatch.setattr(paypal_bind_executor, "_new_http_session", fake_new_http_session)
    monkeypatch.setattr(paypal_bind_executor, "_configure_chatgpt_http_session", lambda *args, **kwargs: None)
    monkeypatch.setattr(paypal_bind_executor.time, "sleep", lambda *_args, **_kwargs: None)

    result = paypal_bind_executor._paypal_extract_ba_link_python(
        access_token="token",
        proxy_url="socks5h://jp.example:1080",
        provider_proxy_url="socks5h://us.example:1080",
        approve_proxy_url="socks5h://approve.example:1080",
        paypal_ba_mode="us",
        timeout_seconds=1,
        on_progress=progress_events.append,
    )

    assert result["status"] == "success"
    assert result["ba_token"] == ""
    assert result["approve_url"] == "https://pm-redirects.stripe.com/authorize/opll"
    assert result["provider_redirect_url"] == "https://pm-redirects.stripe.com/authorize/opll"
    assert result["payment_link_type"] == "paypal_redirect"
    assert result["checkout_session_id"] == "cs_live_opll"
    assert result["pm_id"] == "pm_opll"
    assert result["checkout_url"] == "https://pay.openai.com/c/pay/cs_live_opll"
    assert result["hosted_checkout_url"] == "https://pay.openai.com/c/pay/cs_live_opll"
    assert result["paypal_ba_mode"] == "us"
    assert session_proxy_urls == ["socks5h://jp.example:1080", "socks5h://us.example:1080"]

    checkout_request = next(request for request in chat_http.requests if request["url"].endswith("/payments/checkout"))
    assert checkout_request["kwargs"]["json"]["billing_details"] == {"country": "US", "currency": "USD"}
    assert checkout_request["kwargs"]["json"]["checkout_ui_mode"] == "custom"
    init_request = next(request for request in stripe_http.requests if request["url"].endswith("/init"))
    assert init_request["kwargs"]["data"]["elements_options_client[saved_payment_method][enable_save]"] == "never"
    payment_method_request = next(
        request for request in stripe_http.requests if request["url"].endswith("/v1/payment_methods")
    )
    assert payment_method_request["kwargs"]["data"]["billing_details[address][country]"] == "US"
    confirm_request = next(request for request in stripe_http.requests if request["url"].endswith("/confirm"))
    assert confirm_request["kwargs"]["data"]["payment_method"] == "pm_opll"
    approve_request = next(request for request in chat_http.requests if request["url"].endswith("/checkout/approve"))
    assert approve_request["kwargs"]["json"] == {"checkout_session_id": "cs_live_opll", "processor_entity": "openai_llc"}
    assert any(event["stage"] == "paypal_extract_approve" for event in progress_events)
    assert len(chat_http.responses) == 0
    assert len(stripe_http.responses) == 0


def test_paypal_extract_ba_link_uses_opll_us_mode(monkeypatch):
    chat_http = FakeHttp(
        [
            ("GET", "chatgpt.com/backend-api/sentinel/ping", FakeResponse(json_data={"ok": True})),
            (
                "POST",
                "chatgpt.com/backend-api/payments/checkout",
                FakeResponse(
                    json_data={
                        "checkout_session_id": "cs_live_us",
                        "processor_entity": "openai_llc",
                        "stripe_publishable_key": "pk_live_US",
                    }
                ),
            ),
        ]
    )
    stripe_http = FakeHttp(
        [
            (
                "POST",
                "/v1/payment_pages/cs_live_us/init",
                FakeResponse(
                    json_data={
                        "init_checksum": "init-us",
                        "config_id": "cfg-us",
                        "currency": "usd",
                        "total_summary": {"due": 0},
                        "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_live_us",
                        "payment_method_types": ["card", "paypal"],
                    }
                ),
            ),
            ("POST", "/v1/payment_methods", FakeResponse(json_data={"id": "pm_us"})),
            (
                "POST",
                "/v1/payment_pages/cs_live_us/confirm",
                FakeResponse(
                    json_data={
                        "next_action": {
                            "type": "redirect_to_url",
                            "redirect_to_url": {"url": "https://pm-redirects.stripe.com/authorize/us"},
                        }
                    }
                ),
            ),
        ]
    )
    sessions = [chat_http, stripe_http]
    session_proxy_urls = []

    def fake_new_http_session(proxy_url, **kwargs):
        session_proxy_urls.append(proxy_url)
        return sessions.pop(0)

    monkeypatch.setattr(paypal_bind_executor, "_new_http_session", fake_new_http_session)
    monkeypatch.setattr(paypal_bind_executor, "_configure_chatgpt_http_session", lambda *args, **kwargs: None)
    monkeypatch.setattr(paypal_bind_executor.time, "sleep", lambda *_args, **_kwargs: None)

    result = paypal_bind_executor._paypal_extract_ba_link_python(
        access_token="token",
        proxy_url="socks5h://jp.example:1080",
        provider_proxy_url="socks5h://us.example:1080",
        paypal_ba_mode="us",
        timeout_seconds=1,
    )

    assert result["status"] == "success"
    assert result["ba_token"] == ""
    assert result["approve_url"] == "https://pm-redirects.stripe.com/authorize/us"
    assert result["provider_redirect_url"] == "https://pm-redirects.stripe.com/authorize/us"
    assert result["payment_link_type"] == "paypal_redirect"
    assert result["paypal_ba_mode"] == "us"
    assert session_proxy_urls == ["socks5h://jp.example:1080", "socks5h://us.example:1080"]
    checkout_request = next(request for request in chat_http.requests if request["url"].endswith("/payments/checkout"))
    assert checkout_request["kwargs"]["json"]["billing_details"] == {"country": "US", "currency": "USD"}
    assert checkout_request["kwargs"]["json"]["checkout_ui_mode"] == "custom"
    payment_method_request = next(
        request for request in stripe_http.requests if request["url"].endswith("/v1/payment_methods")
    )
    confirm_request = next(request for request in stripe_http.requests if request["url"].endswith("/confirm"))
    assert payment_method_request["kwargs"]["data"]["billing_details[address][country]"] == "US"
    assert confirm_request["kwargs"]["data"]["expected_payment_method_type"] == "paypal"
    assert len(chat_http.responses) == 0
    assert len(stripe_http.responses) == 0


def test_paypal_extract_ba_link_python_stops_when_custom_checkout_lacks_paypal(monkeypatch):
    chat_http = FakeHttp(
        [
            ("GET", "chatgpt.com/backend-api/sentinel/ping", FakeResponse(json_data={"ok": True})),
            (
                "POST",
                "chatgpt.com/backend-api/payments/checkout",
                FakeResponse(
                    json_data={
                        "checkout_session_id": "cs_live_no_paypal",
                        "url": "https://pay.openai.com/c/pay/cs_live_no_paypal",
                        "client_secret": "cs_live_no_paypal_secret_secret",
                    }
                ),
            ),
        ]
    )
    stripe_http = FakeHttp([])
    sessions = [chat_http, stripe_http]

    def fake_new_http_session(*_args, **_kwargs):
        return sessions.pop(0)

    monkeypatch.setattr(paypal_bind_executor, "_new_http_session", fake_new_http_session)
    monkeypatch.setattr(paypal_bind_executor, "_configure_chatgpt_http_session", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        paypal_bind_executor,
        "_paypal_protocol_stripe_init",
        lambda *_args, **_kwargs: {
            "raw": {"payment_method_types": ["card", "link"]},
            "payment_method_types": {"card", "link"},
            "init_checksum": "init",
            "stripe_js_id": "js",
            "elements_session_id": "es",
            "elements_session_config_id": "esc",
            "config_id": "cfg",
            "expected_amount": "0",
            "currency": "jpy",
            "return_url": "",
            "stripe_hosted_url": "",
            "locale": "ja",
            "stripe_version": paypal_bind_executor.STRIPE_VERSION_FULL,
        },
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_paypal_protocol_elements_session",
        lambda *_args, **_kwargs: pytest.fail("elements session should not run without paypal support"),
    )

    result = paypal_bind_executor._paypal_extract_ba_link_python(
        access_token="token",
        proxy_url="socks5h://jp.example:1080",
        provider_proxy_url="socks5h://jp.example:1080",
        paypal_ba_mode="us",
        timeout_seconds=1,
    )

    assert result["status"] == "failed"
    assert result["failure_stage"] == "paypal_payment_method_unavailable"
    assert "card,link" in result["message"]
    assert result["checkout_session_id"] == "cs_live_no_paypal"
    assert chat_http.responses == []
    assert stripe_http.responses == []


def test_paypal_extract_ba_link_python_marks_checkout_token_invalidated(monkeypatch):
    chat_http = FakeHttp(
        [
            ("GET", "chatgpt.com/backend-api/sentinel/ping", FakeResponse(json_data={"ok": True})),
            (
                "POST",
                "chatgpt.com/backend-api/payments/checkout",
                FakeResponse(
                    status_code=401,
                    text='{"error":{"message":"Your authentication token has been invalidated.","code":"token_invalidated"}}',
                ),
            ),
        ]
    )
    stripe_http = FakeHttp([])
    sessions = [chat_http, stripe_http]

    def fake_new_http_session(proxy_url, **kwargs):
        return sessions.pop(0)

    monkeypatch.setattr(paypal_bind_executor, "_new_http_session", fake_new_http_session)
    monkeypatch.setattr(paypal_bind_executor, "_configure_chatgpt_http_session", lambda *args, **kwargs: None)

    result = paypal_bind_executor._paypal_extract_ba_link_python(
        access_token="token",
        proxy_url="socks5h://jp.example:1080",
        provider_proxy_url="socks5h://us.example:1080",
        paypal_ba_mode="us",
        timeout_seconds=1,
    )

    assert result["status"] == "failed"
    assert result["failure_stage"] == "token_invalidated"
    assert result["token_invalidated"] is True
    assert "token_invalidated" in result["message"]
    assert len(chat_http.responses) == 0
    assert len(stripe_http.responses) == 0


def test_paypal_extract_ba_link_python_marks_checkout_token_revoked(monkeypatch):
    chat_http = FakeHttp(
        [
            ("GET", "chatgpt.com/backend-api/sentinel/ping", FakeResponse(json_data={"ok": True})),
            (
                "POST",
                "chatgpt.com/backend-api/payments/checkout",
                FakeResponse(
                    status_code=401,
                    text='{"error":{"message":"Encountered invalidated oauth token for user","code":"token_revoked"}}',
                ),
            ),
        ]
    )
    stripe_http = FakeHttp([])
    sessions = [chat_http, stripe_http]

    def fake_new_http_session(proxy_url, **kwargs):
        return sessions.pop(0)

    monkeypatch.setattr(paypal_bind_executor, "_new_http_session", fake_new_http_session)
    monkeypatch.setattr(paypal_bind_executor, "_configure_chatgpt_http_session", lambda *args, **kwargs: None)

    result = paypal_bind_executor._paypal_extract_ba_link_python(
        access_token="token",
        proxy_url="socks5h://jp.example:1080",
        provider_proxy_url="socks5h://us.example:1080",
        paypal_ba_mode="us",
        timeout_seconds=1,
    )

    assert result["status"] == "failed"
    assert result["failure_stage"] == "token_invalidated"
    assert result["token_invalidated"] is True
    assert "token_revoked" in result["message"]
    assert len(chat_http.responses) == 0
    assert len(stripe_http.responses) == 0


def test_paypal_extract_ba_link_blocks_nonzero_amount_before_pm(monkeypatch):
    chat_http = FakeHttp(
        [
            ("GET", "chatgpt.com/backend-api/sentinel/ping", FakeResponse(json_data={"ok": True})),
            (
                "POST",
                "chatgpt.com/backend-api/payments/checkout",
                FakeResponse(
                    json_data={
                        "checkout_session_id": "cs_live_test",
                        "url": "https://pay.openai.com/c/pay/cs_live_test",
                    }
                ),
            ),
        ]
    )
    stripe_http = FakeHttp([])
    sessions = [chat_http, stripe_http]

    def fake_new_http_session(proxy_url, **kwargs):
        return sessions.pop(0)

    progress_events = []
    monkeypatch.setattr(paypal_bind_executor, "_new_http_session", fake_new_http_session)
    monkeypatch.setattr(paypal_bind_executor, "_configure_chatgpt_http_session", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        paypal_bind_executor,
        "_paypal_protocol_stripe_init",
        lambda *_args, **_kwargs: {
            "raw": {"payment_method_types": ["card", "paypal"]},
            "payment_method_types": {"card", "paypal"},
            "init_checksum": "init",
            "stripe_js_id": "js",
            "elements_session_id": "es",
            "elements_session_config_id": "esc",
            "config_id": "cfg",
            "expected_amount": "2000",
            "currency": "eur",
            "return_url": "",
            "stripe_hosted_url": "",
            "locale": "en",
            "stripe_version": paypal_bind_executor.STRIPE_VERSION_FULL,
        },
    )

    result = paypal_bind_executor._paypal_extract_ba_link_python(
        access_token="token",
        proxy_url="socks5h://jp.example:1080",
        provider_proxy_url="socks5h://jp.example:1080",
        paypal_ba_mode="eu",
        timeout_seconds=30,
        on_progress=progress_events.append,
    )

    assert result["status"] == "failed"
    assert result["failure_stage"] == "extract_ba_link_nonzero_amount"
    assert result["nonzero_amount"] == 2000
    assert result["checkout_session_id"] == "cs_live_test"
    assert result["paypal_ba_mode"] == "eu"
    assert any(event["stage"] == "paypal_extract_nonzero_amount_blocked" for event in progress_events)
    assert not any(request["url"].endswith("/v1/payment_methods") for request in stripe_http.requests)
    assert stripe_http.responses == []


def test_paypal_extract_ba_link_defaults_to_python_backend(monkeypatch):
    captured = {}

    def fake_python_backend(**kwargs):
        captured.update(kwargs)
        return {
            "status": "success",
            "ba_token": "BA-PY",
            "approve_url": "https://www.paypal.com/agreements/approve?ba_token=BA-PY",
            "paypal_ba_mode": "eu",
        }

    monkeypatch.delenv("PAYPAL_BA_EXTRACT_BACKEND", raising=False)
    monkeypatch.setattr(
        paypal_bind_executor,
        "_paypal_pplink_run_exe",
        lambda **_kwargs: pytest.fail("default PayPal BA extraction must not use bundled pplink.exe"),
    )
    monkeypatch.setattr(paypal_bind_executor, "_paypal_extract_ba_link_python", fake_python_backend)

    result = paypal_bind_executor._paypal_extract_ba_link(
        access_token="token",
        proxy_url="socks5://jp.example:1080",
        provider_proxy_url="socks5://us.example:1080",
        paypal_ba_mode="eu",
        timeout_seconds=30,
    )

    assert result["status"] == "success"
    assert result["ba_token"] == "BA-PY"
    assert captured["access_token"] == "token"
    assert captured["proxy_url"] == "socks5://jp.example:1080"
    assert captured["provider_proxy_url"] == "socks5://us.example:1080"
    assert captured["paypal_ba_mode"] == "eu"


def test_paypal_extract_ba_link_can_use_legacy_pplink_backend(monkeypatch):
    captured = {}

    def fake_run_exe(**kwargs):
        captured.update(kwargs)
        return {
            "status": "success",
            "ba_token": "BA-EXE",
            "approve_url": "https://www.paypal.com/agreements/approve?ba_token=BA-EXE",
            "paypal_ba_mode": "eu",
        }

    monkeypatch.setenv("PAYPAL_BA_EXTRACT_BACKEND", "legacy")
    monkeypatch.setattr(paypal_bind_executor, "_paypal_pplink_run_exe", fake_run_exe)

    result = paypal_bind_executor._paypal_extract_ba_link(
        access_token="token",
        proxy_url="socks5://jp.example:1080",
        provider_proxy_url="socks5://us.example:1080",
        paypal_ba_mode="eu",
        timeout_seconds=30,
    )

    assert result["status"] == "success"
    assert result["ba_token"] == "BA-EXE"
    assert captured["access_token"] == "token"
    assert captured["proxy_url"] == "socks5://jp.example:1080"
    assert captured["provider_proxy_url"] == "socks5://us.example:1080"
    assert captured["paypal_ba_mode"] == "eu"


def test_paypal_extract_ba_link_uses_python_backend_for_au_payment_country(monkeypatch):
    captured = {}

    def fake_python_backend(**kwargs):
        captured.update(kwargs)
        return {
            "status": "success",
            "ba_token": "BA-AU",
            "approve_url": "https://www.paypal.com/agreements/approve?ba_token=BA-AU",
            "paypal_ba_mode": "us",
        }

    monkeypatch.delenv("PAYPAL_BA_EXTRACT_BACKEND", raising=False)
    monkeypatch.setattr(
        paypal_bind_executor,
        "_paypal_pplink_run_exe",
        lambda **_kwargs: pytest.fail("AU payment country must not use bundled pplink.exe"),
    )
    monkeypatch.setattr(paypal_bind_executor, "_paypal_extract_ba_link_python", fake_python_backend)

    result = paypal_bind_executor._paypal_extract_ba_link(
        access_token="token",
        proxy_url="socks5://jp.example:1080",
        provider_proxy_url="socks5://au.example:1080",
        payment_method_country="AU",
        paypal_ba_mode="us",
        timeout_seconds=30,
    )

    assert result["status"] == "success"
    assert result["ba_token"] == "BA-AU"
    assert captured["payment_method_country"] == "AU"
    assert captured["provider_proxy_url"] == "socks5://au.example:1080"


def test_paypal_extract_ba_link_uses_python_backend_when_session_context_present(monkeypatch):
    captured = {}

    def fake_python_backend(**kwargs):
        captured.update(kwargs)
        return {
            "status": "success",
            "ba_token": "BA-SESSION",
            "approve_url": "https://www.paypal.com/agreements/approve?ba_token=BA-SESSION",
            "paypal_ba_mode": "us",
        }

    monkeypatch.delenv("PAYPAL_BA_EXTRACT_BACKEND", raising=False)
    monkeypatch.setattr(
        paypal_bind_executor,
        "_paypal_pplink_run_exe",
        lambda **_kwargs: pytest.fail("session-backed protocol extraction must not use bundled pplink.exe"),
    )
    monkeypatch.setattr(paypal_bind_executor, "_paypal_extract_ba_link_python", fake_python_backend)

    result = paypal_bind_executor._paypal_extract_ba_link(
        access_token="token",
        session_token="session-token",
        cookie_header="__Secure-next-auth.session-token=session-token",
        proxy_url="socks5://jp.example:1080",
        provider_proxy_url="socks5://us.example:1080",
        payment_method_country="US",
        paypal_ba_mode="us",
        timeout_seconds=30,
    )

    assert result["status"] == "success"
    assert result["ba_token"] == "BA-SESSION"
    assert captured["session_token"] == "session-token"
    assert captured["cookie_header"] == "__Secure-next-auth.session-token=session-token"
    assert captured["payment_method_country"] == "US"
    assert captured["provider_proxy_url"] == "socks5://us.example:1080"


def test_paypal_pplink_run_exe_writes_config_and_parses_authorize_url(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        config_path = args[args.index("-config") + 1]
        with open(config_path, encoding="utf-8") as fh:
            captured["config"] = json.load(fh)
        return types.SimpleNamespace(
            returncode=0,
            stdout=(
                "[stripe] checkout session: cs_live_exe, body={}\n"
                "Authorize URL: https://www.paypal.com/agreements/approve?ba_token=BA-EXE&country.x=US\n"
            ),
            stderr="",
        )

    monkeypatch.setenv("PAYPAL_BA_PPLINK_MAX_RETRY", "1")
    monkeypatch.setattr(paypal_bind_executor.subprocess, "run", fake_run)
    monkeypatch.setattr(paypal_bind_executor, "_new_http_session", lambda *_args, **_kwargs: FakeHttp([]))

    result = paypal_bind_executor._paypal_pplink_run_exe(
        access_token="token",
        proxy_url="socks5://jp.example:1080",
        provider_proxy_url="socks5://user-city-Los Angeles:pass@us.example:1080",
        approve_proxy_url="",
        paypal_ba_mode="us",
        timeout_seconds=30,
    )

    assert result["status"] == "success"
    assert result["ba_token"] == "BA-EXE"
    assert result["checkout_session_id"] == "cs_live_exe"
    assert result["paypal_ba_mode"] == "us"
    assert captured["config"] == {
        "proxy_jp": "socks5://jp.example:1080",
        "proxy_us": "socks5://user-city-Los%20Angeles:pass@us.example:1080",
    }
    assert "-stop-at-pm-redirects" in captured["args"]
    assert captured["args"][captured["args"].index("-mode") + 1] == "us"


def test_paypal_pplink_proxy_config_keeps_authenticated_socks_proxy():
    config = paypal_bind_executor._paypal_pplink_proxy_config(
        mode="eu",
        proxy_url="socks5://user:pass@jp.example:1080",
        provider_proxy_url="socks5h://us-user:us-pass@us.example:1080",
        approve_proxy_url="",
    )

    assert config == {
        "proxy_jp": "socks5://user:pass@jp.example:1080",
        "proxy_us": "socks5h://us-user:us-pass@us.example:1080",
    }


def test_paypal_pplink_billing_profile_supports_au_address():
    profile = paypal_bind_executor._paypal_pplink_billing_profile(country="AU", access_token="")

    assert profile["country"] == "AU"
    assert (profile["state"], profile["postal_code"]) in {
        ("NSW", "2000"),
        ("VIC", "3000"),
        ("South Australia", "5000"),
    }


def test_paypal_protocol_signup_keeps_onboard_referer_off_hermes(monkeypatch):
    monkeypatch.setattr(paypal_protocol_signup.time, "sleep", lambda *_args, **_kwargs: None)
    approve_html = (
        '<html><a href="/webapps/hermes?ulOnboardRedirect=true&token=EC-ABCDEFGHIJKLMNOPQ">'
        "Create account</a> EC-ABCDEFGHIJKLMNOPQ</html>"
    )
    http = FakeHttp(
        [
            ("GET", "paypal.com/", FakeResponse(text="ok")),
            ("GET", "/agreements/approve", FakeResponse(text=approve_html)),
            (
                "GET",
                "/agreements/approve",
                FakeResponse(headers={"location": "/checkoutweb/signup?token=EC-ABCDEFGHIJKLMNOPQ"}),
            ),
            ("GET", "/checkoutweb/signup", FakeResponse(text="<html>EC-ABCDEFGHIJKLMNOPQ signup</html>")),
        ]
    )

    ec_token, signup_url, _signup_html = paypal_protocol_signup._bootstrap(
        http,
        "BA-BOOTSTRAP",
        locale_country="US",
        locale_lang="en",
        timeout=10,
    )

    assert ec_token == "EC-ABCDEFGHIJKLMNOPQ"
    assert "/checkoutweb/signup" in signup_url
    prime_request = http.requests[2]
    assert "/checkoutweb/signup" in prime_request["url"]
    assert "Referer" not in prime_request["kwargs"]["headers"]
    assert prime_request["kwargs"]["allow_redirects"] is False
    assert len(http.requests) == 3


def test_paypal_protocol_signup_stops_approve_datadome_for_browser_fallback(monkeypatch):
    monkeypatch.setattr(paypal_protocol_signup.time, "sleep", lambda *_args, **_kwargs: None)
    http = FakeHttp(
        [
            ("GET", "paypal.com/", FakeResponse(text="ok")),
            ("GET", "/agreements/approve", FakeResponse(status_code=403, text="DataDome captcha_failed")),
        ]
    )

    with pytest.raises(RuntimeError) as excinfo:
        paypal_protocol_signup._bootstrap(
            http,
            "BA-BLOCKED",
            locale_country="JP",
            locale_lang="ja",
            timeout=10,
        )

    assert "paypal_human_verification|" in str(excinfo.value)
    assert "降级浏览器" in str(excinfo.value)
    approve_requests = [request["url"] for request in http.requests if "/agreements/approve" in request["url"]]
    assert approve_requests == [
        "https://www.paypal.com/agreements/approve?ba_token=BA-BLOCKED&country.x=JP&locale.x=ja_JP"
    ]


def test_paypal_protocol_datadome_detection_excludes_normal_checkout_pages():
    assert paypal_protocol_signup._is_datadome_blocked(FakeResponse(status_code=403, text="")) is True
    assert paypal_protocol_signup._is_datadome_blocked(FakeResponse(text="DataDome captcha_failed")) is True
    assert paypal_protocol_signup._is_datadome_blocked(
        FakeResponse(text="<html>captcha EC-ABCDEFGHIJKLMNOPQ checkoutweb signup</html>")
    ) is False
    assert paypal_protocol_signup._is_datadome_blocked(FakeResponse(text="<html>captcha only</html>")) is True
    assert paypal_protocol_signup._is_datadome_blocked(FakeResponse(text="<html>normal</html>")) is False


def test_paypal_protocol_checkout_url_for_wait_prefers_existing_url_or_session_id():
    assert paypal_bind_executor._paypal_protocol_checkout_url_for_wait(
        checkout_url="https://pay.openai.com/c/pay/cs_existing"
    ) == "https://pay.openai.com/c/pay/cs_existing"
    assert paypal_bind_executor._paypal_protocol_checkout_url_for_wait(
        hosted_checkout_url="https://checkout.stripe.com/c/pay/cs_hosted"
    ) == "https://checkout.stripe.com/c/pay/cs_hosted"
    assert paypal_bind_executor._paypal_protocol_checkout_url_for_wait(
        checkout_session_id="cs_from_ba_extract"
    ) == "https://pay.openai.com/c/pay/cs_from_ba_extract"
    assert paypal_bind_executor._paypal_protocol_checkout_url_for_wait(
        checkout_url="https://example.com/no-session",
        checkout_session_id="",
    ) == ""


def test_paypal_protocol_wait_checkout_result_follows_return_url_then_polls_stripe():
    http = FakeHttp(
        [
            (
                "GET",
                "chatgpt.com/checkout/verify",
                FakeResponse(url="https://checkout.stripe.com/c/pay/cs_returned?returned_from_redirect=true"),
            ),
            (
                "GET",
                "/v1/payment_pages/cs_returned",
                FakeResponse(json_data={"setup_intent": {"status": "succeeded"}}),
            ),
        ]
    )

    result = paypal_bind_executor._paypal_protocol_wait_checkout_result(
        http,
        checkout_url="https://pay.openai.com/c/pay/cs_initial",
        return_url="https://chatgpt.com/checkout/verify?stripe_session_id=cs_returned",
        timeout_seconds=30,
    )

    assert result["status"] == "success"
    assert "状态已确认成功" in result["message"]
    assert "/v1/payment_pages/cs_returned" in http.requests[1]["url"]


def test_paypal_protocol_pre_extracted_ba_uses_session_id_for_protocol_payment(monkeypatch):
    wait_calls = {}

    monkeypatch.setattr(paypal_bind_executor, "_new_http_session", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        paypal_bind_executor,
        "run_paypal_no_card_protocol_signup",
        lambda *_args, **_kwargs: {
            "status": "success",
            "return_url": "https://chatgpt.com/checkout/verify?stripe_session_id=cs_pre_extracted",
            "ba_token": "BA-DEMO",
            "paypal_user_id": "paypal-user",
        },
    )

    def fake_wait(_http, **kwargs):
        wait_calls.update(kwargs)
        return {"status": "success", "failure_stage": "", "message": "protocol paid"}

    monkeypatch.setattr(paypal_bind_executor, "_paypal_protocol_wait_checkout_result", fake_wait)

    result = paypal_bind_executor._run_paypal_protocol_flow(
        email="user@example.com",
        paypal_mode="create_account",
        signup_profile={"phone": "+819012345678", "sms_url": "https://sms.example", "country": "JP"},
        billing_payload={"country": "JP"},
        paypal_country="JP",
        paypal_lang="ja",
        pre_extracted={
            "ba_token": "BA-DEMO",
            "approve_url": "https://www.paypal.com/agreements/approve?ba_token=BA-DEMO",
            "checkout_session_id": "cs_pre_extracted",
            "pm_id": "pm_demo",
        },
    )

    assert result["status"] == "success"
    assert wait_calls["checkout_url"] == "https://pay.openai.com/c/pay/cs_pre_extracted"
    assert wait_calls["return_url"] == "https://chatgpt.com/checkout/verify?stripe_session_id=cs_pre_extracted"
    assert result["ba_token"] == "BA-DEMO"
    assert result["payment_method_id"] == "pm_demo"


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


def test_paypal_tunnel_connection_error_wrapper_delegates_to_proxy_service():
    assert paypal_bind_executor._is_tunnel_connection_error("ERR_TUNNEL_CONNECTION_FAILED") is True
    assert paypal_bind_executor._is_tunnel_connection_error("HTTP 500") is False


def test_paypal_protocol_proxy_fallback_wrappers_delegate_to_proxy_service():
    assert paypal_bind_executor._paypal_protocol_socks_invalid_response(RuntimeError("curl: (97) bad socks"))
    assert (
        paypal_bind_executor._paypal_protocol_http_proxy_fallback_url("socks5h://user:pass@proxy.example:1080")
        == "http://user:pass@proxy.example:1080"
    )
    assert paypal_bind_executor._paypal_protocol_http_proxy_fallback_url("socks5h://proxy.example:1080") == ""


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


def test_roxybrowser_launch_connects_with_python_playwright_keyword(monkeypatch):
    captured = {}

    class FakeLaunch:
        dir_id = "dir-1"
        workspace_id = "workspace-1"
        created_profile = False
        reused_existing_profile = False
        requested_os = "IOS"
        requested_os_version = "18.2"
        connection = {"http": "127.0.0.1:54510"}

    class FakeClient:
        def __init__(self, api_host, api_token):
            captured["client"] = (api_host, api_token)

        def launch(self, **kwargs):
            captured["launch"] = kwargs
            return FakeLaunch()

    class FakeContext:
        pages = []

        def new_page(self):
            return object()

    class FakeBrowser:
        contexts = [FakeContext()]

    class FakeChromium:
        def connect_over_cdp(self, **kwargs):
            captured["connect"] = kwargs
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    monkeypatch.setattr(
        chatgpt_api, "get_roxybrowser_config", lambda: {"api_host": "http://roxy", "api_token": "token"}
    )
    monkeypatch.setattr(chatgpt_api, "RoxyBrowserClient", FakeClient)
    monkeypatch.setattr(chatgpt_api, "sync_playwright", lambda: types.SimpleNamespace(start=lambda: FakePlaywright()))

    events = []
    api = chatgpt_api.ChatGPTTeamAPI()
    api._launch_browser_roxybrowser(
        proxy_url="socks5://127.0.0.1:1080",
        workspace_id="workspace-1",
        profile_id="dir-1",
        on_progress=events.append,
    )

    assert captured["connect"] == {"endpoint_url": "http://127.0.0.1:54510"}
    assert captured["launch"]["workspace_id"] == "workspace-1"
    assert captured["launch"]["dir_id"] == "dir-1"
    assert captured["launch"]["clear_profile_data"] is True
    assert [event["stage"] for event in events] == [
        "paypal_roxybrowser_cache_clear_started",
        "paypal_roxybrowser_cache_clear_done",
        "paypal_browser_data_clear_started",
        "paypal_browser_data_clear_done",
        "paypal_roxybrowser_runtime_fingerprint",
    ]
    assert api.context is not None
    assert api.page is not None


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


def test_roxybrowser_launch_waits_for_mobile_page_target_to_stabilize(monkeypatch):
    sleeps = []
    events = []

    class FakePage:
        def __init__(self, width):
            self.url = "about:blank"
            self.width = width

        def is_closed(self):
            return False

        def evaluate(self, _script):
            return {
                "platform": "iPhone",
                "user_agent": "iPhone",
                "max_touch_points": 5,
                "viewport_width": self.width,
                "viewport_height": 859,
            }

    old_page = FakePage(986)
    new_page = FakePage(400)

    class FakeContext:
        def __init__(self):
            self.calls = 0

        @property
        def pages(self):
            self.calls += 1
            return [old_page] if self.calls == 1 else [new_page]

    class FakeLaunch:
        workspace_id = "workspace-1"
        dir_id = "dir-1"
        requested_os = "IOS"
        requested_os_version = "18.2"

    api = chatgpt_api.ChatGPTTeamAPI()
    api.context = FakeContext()
    monkeypatch.setattr(chatgpt_api.time, "sleep", lambda seconds: sleeps.append(seconds))

    api._wait_for_roxybrowser_page_stable(launch=FakeLaunch(), on_progress=events.append)

    assert api.page is new_page
    assert sleeps
    assert any(event["stage"] == "paypal_roxybrowser_waiting_page_stable" for event in events)


def test_paypal_bind_task_roxybrowser_uses_roxybrowser_backend(monkeypatch):
    captured = {}

    class FakeApi:
        def _launch_browser(self, *args, **kwargs):
            captured["launch_kwargs"] = kwargs

        def stop(self):
            pass

    monkeypatch.setattr(paypal_bind_executor, "ChatGPTTeamAPI", FakeApi)
    monkeypatch.setattr(
        paypal_bind_executor,
        "_prepare_chatgpt_checkout_context",
        lambda *args, **kwargs: {
            "status": "success",
            "failure_stage": "",
            "message": "prepared",
            "screenshot_paths": [],
        },
    )

    result = paypal_bind_executor.run_paypal_bind_task(
        email="user@example.com",
        checkout_url="https://pay.openai.com/demo",
        manual_confirm=True,
        paypal_browser="roxybrowser",
        roxybrowser_workspace_id="workspace-1",
    )

    assert result["message"] == "prepared"
    assert captured["launch_kwargs"]["use_roxybrowser"] is True
    assert captured["launch_kwargs"]["use_camoufox"] is False
    assert captured["launch_kwargs"]["randomize_fingerprint"] is False
    assert captured["launch_kwargs"]["roxybrowser_workspace_id"] == "workspace-1"


def test_paypal_protocol_datadome_fallback_uses_roxybrowser_when_requested(monkeypatch):
    captured = {}

    class FakePage:
        def goto(self, *args, **kwargs):
            captured["goto"] = (args, kwargs)

    class FakeApi:
        def __init__(self):
            self.page = FakePage()

        def _launch_browser(self, *args, **kwargs):
            captured["launch_kwargs"] = kwargs
            self.page = FakePage()

        def stop(self):
            captured["stopped"] = True

    monkeypatch.setattr(paypal_bind_executor, "ChatGPTTeamAPI", FakeApi)
    monkeypatch.setattr(
        paypal_bind_executor,
        "_run_paypal_protocol_flow",
        lambda **_kwargs: {
            "status": "needs_review",
            "failure_stage": "paypal_human_verification",
            "message": "PayPal /agreements/approve 被 DataDome 风控拦截",
            "paypal_approve_url": "https://www.paypal.com/agreements/approve?ba_token=BA-DEMO",
            "ba_token": "BA-DEMO",
        },
    )
    monkeypatch.setattr(paypal_bind_executor, "_wait_ddc_pass", lambda *args, **kwargs: False)

    result = paypal_bind_executor.run_paypal_bind_task(
        email="user@example.com",
        checkout_url="https://pay.openai.com/c/pay/cs_demo",
        proxy_url="socks5://user:pass@127.0.0.1:1080",
        manual_confirm=False,
        paypal_browser="protocol",
        paypal_fallback_browser="roxybrowser",
        paypal_country="JP",
        paypal_lang="ja",
        paypal_mode="create_account",
        roxybrowser_workspace_id="workspace-1",
        roxybrowser_profile_id="profile-1",
        autofill_enabled=False,
        autofill_payload={
            "name": "Taro Yamada",
            "phone": "+819012345678",
            "country": "JP",
            "state": "Tokyo",
            "city": "Chiyoda",
            "zip": "100-0001",
            "address1": "1-1 Chiyoda",
        },
        sms_url="https://sms.example.test",
    )

    assert result["failure_stage"] == "paypal_datadome_blocked"
    assert captured["launch_kwargs"]["use_roxybrowser"] is True
    assert captured["launch_kwargs"]["use_camoufox"] is False
    assert captured["launch_kwargs"]["roxybrowser_workspace_id"] == "workspace-1"
    assert captured["launch_kwargs"]["roxybrowser_profile_id"] == "profile-1"
    assert captured["launch_kwargs"]["locale"] == "ja-JP"
    assert captured["goto"][0][0].startswith("https://www.paypal.com/agreements/approve?")
    assert "ba_token=BA-DEMO" in captured["goto"][0][0]
    assert "ulOnboardRedirect=true" in captured["goto"][0][0]
    assert "country.x=JP" in captured["goto"][0][0]


def test_paypal_protocol_transport_error_with_approve_url_uses_browser_fallback():
    assert paypal_bind_executor._paypal_protocol_needs_browser_fallback(
        {
            "status": "failed",
            "failure_stage": "paypal_protocol",
            "message": "Failed to perform, curl: (28) Recv failure: Connection was reset.",
            "paypal_approve_url": "https://www.paypal.com/agreements/approve?ba_token=BA-DEMO",
            "ba_token": "BA-DEMO",
        }
    )


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


def test_paypal_approve_checkout_http_preserves_session_token_context(monkeypatch):
    http = FakeHttp(
        [
            ("POST", "/backend-api/sentinel/ping", FakeResponse(json_data={})),
            ("POST", "/backend-api/payments/checkout/approve", FakeResponse(json_data={"result": "approved"})),
        ]
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_checkout_approval_sentinel_headers",
        lambda **kwargs: {"OpenAI-Sentinel-Token": "checkout-sentinel", "OAI-Telemetry": "[1,null]"},
    )

    result = paypal_bind_executor._paypal_approve_checkout_http(
        http,
        access_token="access",
        checkout_session_id="cs_test",
        processor_entity="openai_llc",
        session_token="session-token",
        cookie_header="",
        account_id="account",
        device_id="device",
        user_agent="UA",
        openai_sentinel_token="sentinel",
        oai_client_version="1.2.3",
        oai_client_build_number="456",
    )

    assert result == {"result": "approved"}
    assert http.headers["User-Agent"] == "UA"
    assert http.headers["Cookie"] == "__Secure-next-auth.session-token=session-token; _account=account; oai-did=device"
    assert http.headers["oai-client-version"] == "1.2.3"
    assert http.headers["oai-client-build-number"] == "456"
    assert http.headers["openai-sentinel-token"] == "sentinel"
    approve_headers = http.requests[1]["kwargs"]["headers"]
    assert approve_headers["authorization"] == "Bearer access"
    assert approve_headers["cookie"] == "__Secure-next-auth.session-token=session-token; _account=account; oai-did=device"
    assert approve_headers["OpenAI-Sentinel-Token"] == "checkout-sentinel"
    assert approve_headers["OAI-Telemetry"] == "[1,null]"
    assert "openai-sentinel-token" not in approve_headers


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


def test_classify_paypal_checkout_state_and_stage():
    success = paypal_bind_executor.classify_paypal_checkout_state(
        "https://www.paypal.com/checkoutnow",
        "Thanks for subscribing",
    )
    redirect_success = paypal_bind_executor.classify_paypal_checkout_state(
        "https://pay.openai.com/c/pay/cs_live_123?redirect_pm_type=paypal&redirect_status=succeeded&setup_intent=seti_123",
        "",
    )
    failed = paypal_bind_executor.classify_paypal_checkout_state(
        "https://www.paypal.com/checkoutnow",
        "Payment was not approved",
    )
    stage = paypal_bind_executor.infer_paypal_stage(
        "https://www.paypal.com/signin",
        "PayPal",
    )
    cancelled = paypal_bind_executor.classify_paypal_checkout_state(
        "https://pay.openai.com/cancel",
        "",
    )
    pending = paypal_bind_executor.classify_paypal_checkout_state(
        "https://pay.openai.com/checkout",
        "Payment pending",
    )
    limited = paypal_bind_executor.classify_paypal_checkout_state(
        "https://www.paypal.com/checkoutweb/genericError?code=UkVTVFJJQ1RFRF9VU0VS",
        "Your account is limited. Please check your PayPal Account Overview page for information on how to resolve this problem. Return to merchant",
    )
    limited_by_code = paypal_bind_executor.classify_paypal_checkout_state(
        "https://www.paypal.com/checkoutweb/genericError?code=UkVTVFJJQ1RFRF9VU0VS",
        "",
    )
    phone_rejected = paypal_bind_executor.classify_paypal_checkout_state(
        "https://www.paypal.com/checkoutweb/signup",
        "We're unable to complete your request Try a different phone number.",
    )
    jp_phone_rejected = paypal_bind_executor.classify_paypal_checkout_state(
        "https://www.paypal.com/checkoutweb/signup",
        "お客さまのリクエストを完了できませんでした。別の電話番号をお試しください。",
    )
    card_linked = paypal_bind_executor.classify_paypal_checkout_state(
        "https://www.paypal.com/checkoutweb/signup",
        "This card has already been added to another PayPal account. Remove the card from the other account or try a different way to pay.",
    )
    datadome_blocked = paypal_bind_executor.classify_paypal_checkout_state(
        "https://www.paypal.com/checkoutweb/genericError",
        "DataDome slider_timeout captcha_failed",
    )
    human_verification = paypal_bind_executor.classify_paypal_checkout_state(
        "https://www.paypal.com/agreements/approve",
        "Confirm you're human Move the slider all the way to the right",
    )
    stripe_return_success = paypal_bind_executor.classify_paypal_checkout_state(
        "https://pm-redirects.stripe.com/return/some_nonce?status=success",
        "",
    )
    chatgpt_return_success = paypal_bind_executor.classify_paypal_checkout_state(
        "https://chatgpt.com/payments/success?session_id=abc",
        "",
    )
    autofill_payload = paypal_bind_executor.normalize_autofill_payload(
        {
            "billingName": "James Smith",
            "billingZip": "10001",
            "billingAddress1": "123 Main St",
        }
    )

    assert success == {
        "status": "success",
        "failure_stage": "",
        "message": "检测到 PayPal/支付成功页面",
    }
    assert redirect_success == {
        "status": "success",
        "failure_stage": "",
        "message": "检测到 PayPal/支付成功页面",
    }
    assert failed == {
        "status": "failed",
        "failure_stage": "post_submit",
        "message": "检测到 PayPal/支付失败提示",
    }
    assert stage == ("paypal_authorize", "已进入 PayPal 页面，等待人工完成登录/授权")
    assert cancelled == {
        "status": "failed",
        "failure_stage": "post_submit",
        "message": "检测到 PayPal 支付已取消",
    }
    assert pending == {
        "status": "needs_review",
        "failure_stage": "post_submit",
        "message": "检测到 PayPal 支付处理中，需要人工确认最终状态",
    }
    assert limited == {
        "status": "failed",
        "failure_stage": "paypal_account_limited",
        "message": "PayPal 账号受限，无法完成授权",
    }
    assert limited_by_code == limited
    assert phone_rejected == {
        "status": "failed",
        "failure_stage": "paypal_phone_rejected",
        "message": "PayPal 拒绝当前手机号，请更换手机号",
    }
    assert jp_phone_rejected == phone_rejected
    assert card_linked == {
        "status": "failed",
        "failure_stage": "paypal_card_linked",
        "message": "当前卡片已绑定到其他 PayPal 账号，需要换卡/换身份信息",
    }
    assert datadome_blocked == {
        "status": "failed",
        "failure_stage": "paypal_datadome_blocked",
        "message": "PayPal DataDome/风控验证阻断当前环境",
    }
    assert human_verification == {
        "status": "needs_review",
        "failure_stage": "paypal_human_verification",
        "message": "PayPal 人机验证等待人工处理",
    }
    assert stripe_return_success == {
        "status": "success",
        "failure_stage": "",
        "message": "检测到 PayPal/支付成功页面",
    }
    assert chatgpt_return_success == {
        "status": "success",
        "failure_stage": "",
        "message": "检测到 PayPal/支付成功页面",
    }
    assert autofill_payload == {
        "name": "James Smith",
        "address1": "123 Main St",
        "postal_code": "10001",
    }


def test_paypal_checkout_state_readback_accepts_us_state_abbreviation():
    assert paypal_bind_executor._checkout_value_matches("state", "California", "CA") is True
    assert paypal_bind_executor._checkout_value_matches("state", "CA", "California") is True
    assert paypal_bind_executor._checkout_value_matches("state", "New York", "NY") is True
    assert paypal_bind_executor._checkout_value_matches("state", "California", "NY") is False


def test_paypal_signup_state_field_accepts_us_state_abbreviation():
    assert paypal_bind_executor._field_value_matches("California", "CA", field="state") is True
    assert paypal_bind_executor._field_value_matches("CA", "California", field="state") is True
    assert paypal_bind_executor._field_value_matches("New York", "NY", field="state") is True
    assert paypal_bind_executor._field_value_matches("California", "NY", field="state") is False


def test_paypal_signup_state_field_accepts_japanese_prefecture_label():
    assert paypal_bind_executor._field_value_matches("Tokyo", "東京都", field="state") is True
    assert paypal_bind_executor._field_value_matches("東京都", "東京", field="state") is True
    assert paypal_bind_executor._field_value_matches("Tokyo", "大阪府", field="state") is False


def test_paypal_signup_selects_japanese_prefecture_label():
    calls = []

    class FakeLocator:
        def evaluate(self, script, *args):
            if script == "el => el.tagName":
                return "SELECT"
            raise RuntimeError("not needed")

        def select_option(self, *, value=None, label=None, timeout=None):
            calls.append(("value" if value is not None else "label", value or label))
            if label == "東京都":
                return None
            raise RuntimeError("option not found")

    assert paypal_bind_executor._set_paypal_state_locator_value(FakeLocator(), "Tokyo", country="JP") is True
    assert ("label", "東京都") in calls


def test_paypal_signup_selectors_include_japanese_phone_and_prompt_labels():
    assert 'input[aria-label*="電話"]' in paypal_bind_executor.PAYPAL_PHONE_SELECTORS
    assert 'button:has-text("利用しない")' in paypal_bind_executor.PAYPAL_DISMISS_PROMPT_SELECTORS


def test_paypal_checkout_fast_autofill_falls_back_when_readback_mismatches(monkeypatch):
    class FakeLocator:
        def __init__(self, value=""):
            self.value = value
            self.set_calls = 0

        def evaluate(self, _script, *args):
            if args:
                self.value = str(args[0])
                self.set_calls += 1
                return True
            return self.value

        def click(self, timeout=0):
            return None

        def fill(self, value, timeout=0):
            self.value = str(value)
            self.set_calls += 1

    class FakeApi:
        page = types.SimpleNamespace(url="https://pay.openai.com/c/pay/cs_live_test")

        def __init__(self):
            self.locator = FakeLocator("wrong value")

        def _visible_locator_in_frames(self, selectors, timeout_ms=1000):
            return self.locator if "#billingAddressLine1" in selectors else None

    api = FakeApi()
    monkeypatch.setattr(paypal_bind_executor, "_fast_autofill_checkout_fields", lambda *_args, **_kwargs: ["address1"])
    result = paypal_bind_executor.autofill_checkout_fields(api, {"address1": "11 Main St"})

    assert result == {"filled": ["address1"], "skipped": []}
    assert api.locator.value == "11 Main St"
    assert api.locator.set_calls == 1


def test_paypal_checkout_fast_autofill_skips_fallback_only_after_readback_matches(monkeypatch):
    class FakeLocator:
        def __init__(self, value=""):
            self.value = value
            self.set_calls = 0

        def evaluate(self, _script, *args):
            if args:
                self.value = str(args[0])
                self.set_calls += 1
                return True
            return self.value

    class FakeApi:
        page = types.SimpleNamespace(url="https://pay.openai.com/c/pay/cs_live_test")

        def __init__(self):
            self.locator = FakeLocator("11 Main St")

        def _visible_locator_in_frames(self, selectors, timeout_ms=1000):
            return self.locator if "#billingAddressLine1" in selectors else None

    api = FakeApi()
    monkeypatch.setattr(paypal_bind_executor, "_fast_autofill_checkout_fields", lambda *_args, **_kwargs: ["address1"])
    result = paypal_bind_executor.autofill_checkout_fields(api, {"address1": "11 Main St"})

    assert result == {"filled": ["address1"], "skipped": []}
    assert api.locator.value == "11 Main St"
    assert api.locator.set_calls == 0


def test_classify_paypal_stripe_payment_page_success():
    result = paypal_bind_executor._classify_paypal_stripe_payment_page(
        {
            "setup_intent": {"status": "succeeded"},
            "payment_status": "paid",
            "status": "complete",
            "submission_attempt": {"state": "complete"},
        }
    )

    assert result == {
        "status": "success",
        "failure_stage": "",
        "message": "Stripe checkout 状态已确认成功: submission_attempt='complete' setup_intent='succeeded' payment_intent='' payment_status='paid' status='complete'",
    }


def test_wait_for_paypal_result_uses_stripe_state_when_page_text_is_ambiguous(monkeypatch):
    class FakePage:
        url = "https://www.paypal.com/checkoutweb/approve"

    class FakeApi:
        page = FakePage()

    progress_events = []

    monkeypatch.setattr(paypal_bind_executor, "_sync_relevant_payment_page", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(paypal_bind_executor, "_body_excerpt", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(paypal_bind_executor, "_ensure_paypal_hosted_captcha_bypass", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(paypal_bind_executor, "_ddc_slider_visible", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(paypal_bind_executor, "_has_ddc_iframe", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(paypal_bind_executor, "_wait_ddc_pass", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(paypal_bind_executor, "_is_checkout_host", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        paypal_bind_executor, "infer_paypal_stage", lambda *_args, **_kwargs: ("paypal_wait_result", "等待")
    )
    monkeypatch.setattr(paypal_bind_executor, "classify_paypal_checkout_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        paypal_bind_executor,
        "_fetch_paypal_stripe_payment_page_state",
        lambda *_args, **_kwargs: {"status": "success", "failure_stage": "", "message": "stripe confirmed"},
    )
    monkeypatch.setattr(paypal_bind_executor, "_capture_screenshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(paypal_bind_executor.time, "sleep", lambda *_args, **_kwargs: None)

    result = paypal_bind_executor._wait_for_paypal_result(
        FakeApi(),
        checkout_url="https://chatgpt.com/checkout/openai_llc/cs_live_123",
        proxy_url=None,
        session_id="sess123",
        screenshot_paths=[],
        timeout_seconds=15,
        on_progress=progress_events.append,
    )

    assert result["status"] == "success"
    assert result["message"] == "stripe confirmed"
    assert any(event.get("stage") == "paypal_result_confirmed_by_stripe" for event in progress_events)


def test_wait_for_paypal_result_does_not_autofill_when_disabled(monkeypatch):
    class FakePage:
        url = "https://checkout.openai.com/pay/cs_test"

    class FakeApi:
        page = FakePage()

    autofill_calls = []
    screenshot_paths = []

    monkeypatch.setattr(paypal_bind_executor, "_sync_relevant_payment_page", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(paypal_bind_executor, "_body_excerpt", lambda *_args, **_kwargs: "checkout")
    monkeypatch.setattr(paypal_bind_executor, "_is_checkout_host", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(paypal_bind_executor, "_autofill_allowed", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        paypal_bind_executor, "autofill_checkout_fields", lambda *args, **kwargs: autofill_calls.append((args, kwargs))
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "infer_paypal_stage",
        lambda *_args, **_kwargs: ("paypal_wait_result", "等待"),
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "classify_paypal_checkout_state",
        lambda *_args, **_kwargs: {"status": "success", "failure_stage": "", "message": "confirmed"},
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_capture_screenshot",
        lambda _api, _session_id, label, paths: paths.append(f"{label}.png"),
    )

    result = paypal_bind_executor._wait_for_paypal_result(
        FakeApi(),
        checkout_url="https://checkout.openai.com/pay/cs_test",
        proxy_url=None,
        session_id="sess123",
        screenshot_paths=screenshot_paths,
        timeout_seconds=15,
        autofill_enabled=False,
        autofill_payload={"name": "James Smith"},
    )

    assert result["status"] == "success"
    assert result["screenshot_paths"] == ["success.png"]
    assert autofill_calls == []


def test_merge_checkout_billing_payload_uses_generated_address_for_missing_fields(monkeypatch):
    monkeypatch.setattr(
        paypal_bind_executor,
        "_fetch_paypal_random_billing_profile",
        lambda: {
            "name": "John Auto",
            "country": "US",
            "state": "CA",
            "city": "Los Angeles",
            "zip": "90001",
            "address1": "742 Evergreen Terrace",
            "address2": "Apt 2",
            "phone_number": "3105550100",
        },
    )

    payload = paypal_bind_executor._merge_checkout_billing_payload(
        {
            "billingName": "James Smith",
            "billingEmail": "user@example.com",
        }
    )

    expected = {
        "name": "John Auto",
        "email": "user@example.com",
        "phone": "3105550100",
        "country": "US",
        "state": "CA",
        "city": "Los Angeles",
        "zip": "90001",
        "address1": "742 Evergreen Terrace",
        "address2": "Apt 2",
    }
    assert {key: payload[key] for key in expected} == expected
    assert paypal_bind_executor._is_luhn_valid(payload["card_number"])
    assert payload["card_expiry"]
    assert payload["card_cvv"]


def test_merge_checkout_billing_payload_forces_us_address_and_default_name(monkeypatch):
    monkeypatch.setattr(
        paypal_bind_executor,
        "_fetch_paypal_random_billing_profile",
        lambda: {
            "name": "Foreign Auto",
            "country": "US",
            "state": "WA",
            "city": "Seattle",
            "zip": "98101",
            "address1": "500 Pine St",
            "address2": "",
            "phone_number": "2065550100",
        },
    )

    payload = paypal_bind_executor._merge_checkout_billing_payload(
        {
            "billingCountry": "SG",
        }
    )

    expected = {
        "name": "Foreign Auto",
        "email": "",
        "phone": "2065550100",
        "country": "US",
        "state": "WA",
        "city": "Seattle",
        "zip": "98101",
        "address1": "500 Pine St",
        "address2": "",
    }
    assert {key: payload[key] for key in expected} == expected
    assert paypal_bind_executor._is_luhn_valid(payload["card_number"])
    assert payload["card_expiry"]
    assert payload["card_cvv"]


def test_merge_checkout_billing_payload_carries_generated_card_fields(monkeypatch):
    monkeypatch.setattr(
        paypal_bind_executor,
        "_fetch_paypal_random_billing_profile",
        lambda: {
            "name": "Card Source",
            "country": "US",
            "state": "CA",
            "city": "Los Angeles",
            "zip": "90001",
            "address1": "742 Evergreen Terrace",
            "address2": "",
            "phone_number": "3105550100",
            "card_number": "4111 1111 1111 1111",
            "card_expiry": "03/2030",
            "card_cvv": "996",
        },
    )

    payload = paypal_bind_executor._merge_checkout_billing_payload({})

    assert payload["country"] == "US"
    assert payload["address1"] == "742 Evergreen Terrace"
    assert payload["card_number"] == "4111111111111111"
    assert payload["card_expiry"] == "03/2030"
    assert payload["card_cvv"] == "996"


def test_paypal_generator_field_extracts_meiguodizhi_card_fields():
    address = {
        "Credit_Card_Number": "4111111111111111",
        "Expires": "04/2028",
        "CVV2": "123",
    }

    assert paypal_bind_executor._paypal_generator_field(address, "Credit_Card_Number") == "4111111111111111"
    assert paypal_bind_executor._paypal_generator_field(address, "Expires") == "04/2028"
    assert paypal_bind_executor._paypal_generator_field(address, "CVV2") == "123"


def test_paypal_card_number_generation_uses_allowed_luhn_brand():
    generated = paypal_bind_executor._generate_paypal_card_number()

    assert paypal_bind_executor._is_luhn_valid(generated)
    assert paypal_bind_executor._paypal_card_brand_allowed(generated)
    assert paypal_bind_executor._normalize_or_generate_paypal_card_number("3580264577581543") != "3580264577581543"
    assert paypal_bind_executor._normalize_or_generate_paypal_card_number("4111111111111111") == "4111111111111111"


def test_normalize_paypal_mode_and_signup_profile_generation():
    assert paypal_bind_executor._normalize_paypal_mode("") == "existing_account"
    assert paypal_bind_executor._normalize_paypal_mode("login") == "existing_account"
    assert paypal_bind_executor._normalize_paypal_mode("create-account") == "create_account"

    profile = paypal_bind_executor._build_paypal_signup_profile(
        billing_payload={
            "name": "James Smith",
            "phone": "+1 (310) 555-0100",
            "country": "US",
            "state": "CA",
            "city": "Los Angeles",
            "zip": "90001",
            "address1": "742 Evergreen Terrace",
            "address2": "Apt 2",
        },
        sms_url="https://sms.example.test/token=demo",
        otp_channel="sms",
        paypal_card_number="4111 1111 1111 1111",
        paypal_card_expiry="03/2030",
        paypal_card_cvv="996",
    )

    assert profile["generated_email"] is True
    assert profile["generated_password"] is True
    assert str(profile["email"]).endswith("@gmail.com")
    assert profile["phone"] == "3105550100"
    assert profile["first_name"] == "James"
    assert profile["last_name"] == "Smith"
    assert profile["card_number"] == "4111111111111111"
    assert profile["card_expiry"] == "03 / 30"
    assert profile["card_cvv"] == "996"

    generated_card_profile = paypal_bind_executor._build_paypal_signup_profile(
        billing_payload={
            "name": "James Smith",
            "phone": "+1 (310) 555-0100",
            "country": "US",
            "state": "CA",
            "city": "Los Angeles",
            "zip": "90001",
            "address1": "742 Evergreen Terrace",
            "card_number": "4000-0000-0000-3220",
            "card_expiry": "04/2031",
            "card_cvv": "123",
        },
        sms_url="https://sms.example.test/token=demo",
        otp_channel="sms",
    )

    assert generated_card_profile["card_number"] == "4000000000003220"
    assert generated_card_profile["card_expiry"] == "04 / 31"
    assert generated_card_profile["card_cvv"] == "123"


def test_normalize_paypal_bind_task_runtime_options_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_normalize(**kwargs):
        captured.update(kwargs)
        return {"paypal_mode": "existing_account"}

    monkeypatch.setattr(
        paypal_bind_executor.paypal_preflight_service,
        "normalize_paypal_bind_task_runtime_options",
        fake_normalize,
    )

    assert paypal_bind_executor._normalize_paypal_bind_task_runtime_options(
        manual_confirm=False,
        paypal_mode="create-account",
        paypal_browser="protocol",
        paypal_fallback_browser="roxybrowser",
        paypal_country="JP",
        paypal_lang="ja",
        proxy_url="socks5://proxy.example:1080",
        proxy_bypass="localhost",
        roxybrowser_workspace_id="workspace-1",
        roxybrowser_profile_id="profile-1",
        paypal_card_number="4111111111111111",
        paypal_card_expiry="03/30",
        paypal_card_cvv="123",
    ) == {"paypal_mode": "existing_account"}
    assert captured == {
        "manual_confirm": False,
        "paypal_mode": "create-account",
        "paypal_browser": "protocol",
        "paypal_fallback_browser": "roxybrowser",
        "paypal_country": "JP",
        "paypal_lang": "ja",
        "proxy_url": "socks5://proxy.example:1080",
        "proxy_bypass": "localhost",
        "roxybrowser_workspace_id": "workspace-1",
        "roxybrowser_profile_id": "profile-1",
        "paypal_card_number": "4111111111111111",
        "paypal_card_expiry": "03/30",
        "paypal_card_cvv": "123",
    }


def test_normalize_paypal_phone_accepts_jp_country_code():
    assert paypal_bind_executor._normalize_paypal_phone("+81 70-9487-0367") == "07094870367"
    assert paypal_bind_executor._normalize_paypal_phone("0081 70 9487 0367") == "07094870367"
    assert paypal_bind_executor._normalize_paypal_phone("070-9487-0367") == "07094870367"


def test_paypal_phone_value_rejects_country_code_only():
    assert paypal_bind_executor._paypal_phone_value_valid("+81", country="JP") is False
    assert paypal_bind_executor._paypal_phone_value_valid("81", country="JP") is False
    assert paypal_bind_executor._paypal_phone_value_valid("09026647330", country="JP") is True
    assert paypal_bind_executor._field_value_matches("09026647330", "+81 90-2664-7330", field="phone") is True
    assert paypal_bind_executor._field_value_matches("09026647330", "+81", field="phone") is False


def test_paypal_signup_profile_country_follows_paypal_country_over_checkout_billing():
    profile = paypal_bind_executor._build_paypal_signup_profile(
        billing_payload={
            "name": "",
            "phone": "+81 70 9487 0367",
            "country": "US",
            "state": "",
            "city": "",
            "zip": "",
            "address1": "",
        },
        paypal_country="JP",
        sms_url="https://sms.example.test/token=demo",
        otp_channel="sms",
    )

    assert profile["country"] == "JP"
    assert profile["state"] == "Tokyo"
    assert profile["city"] == "Chiyoda"
    assert profile["zip"] == "100-0001"
    assert profile["address1"] == "1-1 Chiyoda"


def test_paypal_signup_profiles_for_phone_pool_preserve_registration_identity():
    base = {
        "email": "pp-demo@gmail.com",
        "password": "Secret123!",
        "phone": "3105550100",
        "sms_url": "https://sms.example/one",
        "otp_channel": "sms",
        "card_number": "4111111111111111",
    }

    profiles = paypal_bind_executor._paypal_signup_profiles_for_phone_pool(
        base,
        [
            {"phone_number": "+18352880840", "sms_url": "https://sms.example/one"},
            {"phone_number": "+18352623053", "sms_url": "https://sms.example/two"},
        ],
    )

    assert [profile["phone"] for profile in profiles] == ["8352880840", "8352623053"]
    assert [profile["sms_url"] for profile in profiles] == ["https://sms.example/one", "https://sms.example/two"]
    assert all(profile["email"] == "pp-demo@gmail.com" for profile in profiles)
    assert all(profile["password"] == "Secret123!" for profile in profiles)
    assert all(profile["card_number"] == "4111111111111111" for profile in profiles)


def test_paypal_signup_profiles_for_phone_pool_drop_country_code_only_phone():
    base = {
        "email": "pp-demo@gmail.com",
        "password": "Secret123!",
        "phone": "+81",
        "country": "JP",
        "sms_url": "https://sms.example/one",
    }

    assert paypal_bind_executor._paypal_signup_profiles_for_phone_pool(base, []) == []


def test_paypal_jp_autogenerated_billing_profile_preserves_country():
    payload = paypal_bind_executor._merge_checkout_billing_payload(
        {
            "email": "user@example.com",
            "phone": "+819012345678",
            "country": "JP",
        }
    )

    assert payload["country"] == "JP"
    assert payload["state"] == "Tokyo"
    assert payload["city"] == "Chiyoda"
    assert payload["zip"] == "100-0001"
    assert payload["address1"] == "1-1 Chiyoda"
    assert payload["phone"] == "+819012345678"


def test_prepare_paypal_signup_billing_payload_uses_proxy_matched_jp_address(monkeypatch):
    monkeypatch.setattr(
        paypal_bind_executor,
        "_paypal_proxy_exit_location",
        lambda _proxy: {
            "country_code": "JP",
            "region": "Osaka",
            "city": "Osaka",
            "ip": "203.0.113.10",
        },
    )

    def fake_mockaddress_json(cache_key, _url):
        if cache_key == "jp_data":
            return {
                "prefectures": {
                    "TOKYO": {
                        "name": {"ja": "東京都"},
                        "phone_codes": ["03"],
                        "postal_prefix": ["100"],
                    },
                    "OSAKA": {
                        "name": {"ja": "大阪府"},
                        "phone_codes": ["06"],
                        "postal_prefix": ["530"],
                    },
                },
                "address_data": {},
            }
        if cache_key == "jp_real_areas":
            return {
                "data": [
                    {
                        "postcode": "5300001",
                        "prefecture": "大阪府",
                        "city": "大阪市北区",
                        "town": "梅田",
                    }
                ]
            }
        if cache_key == "jp_names":
            return {
                "surnames": {"kanji": ["山田"], "hiragana": ["やまだ"], "katakana": ["ヤマダ"]},
                "firstNames": {
                    "male": {"kanji": ["太郎"], "hiragana": ["たろう"], "katakana": ["タロウ"]},
                    "female": {"kanji": ["太郎"], "hiragana": ["たろう"], "katakana": ["タロウ"]},
                },
            }
        if cache_key == "global_names":
            return {
                "nameGroups": {
                    "western": {
                        "first": {"male": ["Taro"], "female": ["Taro"]},
                        "last": ["Yamada"],
                    }
                }
            }
        return {}

    monkeypatch.setattr(paypal_bind_executor, "_mockaddress_jp_json", fake_mockaddress_json)
    monkeypatch.setattr(paypal_bind_executor.random, "randint", lambda start, _end: start)

    payload = paypal_bind_executor._prepare_paypal_signup_billing_payload(
        {
            "name": "James Smith",
            "phone": "+817094870367",
            "country": "US",
            "state": "CA",
            "city": "Los Angeles",
            "zip": "90026",
            "address1": "3110 Sunset Boulevard",
            "card_number": "4111111111111111",
            "card_expiry": "03 / 30",
            "card_cvv": "123",
        },
        paypal_country="JP",
        proxy_url="socks5://proxy.example:1080",
        auto_generate=True,
    )

    assert payload["country"] == "JP"
    assert payload["state"] == "大阪府"
    assert payload["city"] == "大阪市北区"
    assert payload["zip"] == "530-0001"
    assert payload["address1"] == "梅田1-1"
    assert payload["name"] == "タロウ ヤマダ"
    assert payload["first_name"] == "タロウ"
    assert payload["last_name"] == "ヤマダ"
    assert payload["native_first_name"] == "太郎"
    assert payload["native_last_name"] == "山田"
    assert payload["phone"] == "+817094870367"
    assert payload["card_number"] == "4111111111111111"

    profile = paypal_bind_executor._build_paypal_signup_profile(
        billing_payload=payload,
        paypal_country="JP",
        sms_url="https://sms.example.test/token=demo",
    )
    assert profile["first_name"] == "タロウ"
    assert profile["last_name"] == "ヤマダ"
    assert profile["native_first_name"] == "太郎"
    assert profile["native_last_name"] == "山田"


def test_set_paypal_country_prefers_requested_country_before_us_fallback(monkeypatch):
    calls = []

    class FakeLocator:
        def select_option(self, *, value=None, label=None, timeout=None):
            calls.append(("value" if value is not None else "label", value or label))
            if value == "JP":
                return None
            raise RuntimeError("unexpected fallback")

    monkeypatch.setattr(paypal_bind_executor, "_visible_locator_in_frames", lambda *_args, **_kwargs: FakeLocator())

    assert paypal_bind_executor._set_paypal_country(object(), "JP") is True
    assert calls[0] == ("value", "JP")
    assert ("value", "US") not in calls


def test_paypal_protocol_signup_splits_japanese_phone_number():
    assert paypal_protocol_signup._phone_split("+819012345678") == ("81", "9012345678")
    assert paypal_protocol_signup._phone_split("09040524462", country="JP") == ("81", "9040524462")
    assert paypal_protocol_signup._phone_split("819040524462", country="JP") == ("81", "9040524462")
    assert paypal_protocol_signup._phone_split("7094219236", country="JP") == ("81", "7094219236")


def test_paypal_browser_signup_accepts_japanese_subscriber_without_leading_zero():
    assert paypal_bind_executor._paypal_phone_value_valid("7094219236", country="JP") is True


def test_paypal_protocol_signup_snapshots_existing_sms_otp(monkeypatch):
    monkeypatch.setattr(paypal_protocol_signup.sms_otp_service, "fetch_sms_code", lambda _url: "051637")

    assert paypal_protocol_signup._snapshot_existing_sms_otps("https://sms.example.test") == {"051637"}


def test_paypal_protocol_signup_builds_jp_signup_variables_like_protocol_reference():
    variables = paypal_protocol_signup._signup_variables(
        signup_profile={
            "email": "pp-demo@example.com",
            "password": "Secret123!",
            "phone": "09040524462",
            "first_name": "タロウ",
            "last_name": "ヤマダ",
            "native_first_name": "太郎",
            "native_last_name": "山田",
            "country": "JP",
            "state": "東京都",
            "city": "千代田区",
            "zip": "100-0001",
            "address1": "千代田1-1",
            "birth_date": "1985/01/15",
            "card_number": "5555555555554444",
            "card_expiry": "03 / 30",
            "card_cvv": "123",
        },
        ec_token="EC-12345678901234567",
        locale_country="JP",
        locale_lang="ja",
    )

    assert variables["phone"] == {"countryCode": "81", "number": "9040524462", "type": "MOBILE"}
    assert variables["dateOfBirth"] == {"day": "15", "month": "01", "year": "1985"}
    assert variables["firstName"] == "太郎"
    assert variables["lastName"] == "山田"
    assert variables["countrySpecificFirstName"] == "タロウ"
    assert variables["countrySpecificLastName"] == "ヤマダ"
    assert variables["card"] == {
        "cardNumber": "5555555555554444",
        "expirationDate": "03/2030",
        "securityCode": "123",
        "type": "MASTER_CARD",
    }
    assert "bank" not in variables
    assert variables["nationality"] == "JP"
    assert variables["billingAddress"]["state"] == "東京都"
    assert variables["billingAddress"]["city"] == "千代田区"
    assert variables["shippingAddress"]["line1"] == "千代田1-1"
    assert variables["shippingAddress"]["state"] == "東京都"
    assert variables["shippingAddress"]["postalCode"] == "100-0001"
    assert "city" not in variables["shippingAddress"]
    assert variables["billingAddress"]["accountQuality"]["isUserModified"] is True
    assert variables["contentIdentifier"] == "JP:ja:7b6ca42fbd7ddea17db0dcd181eeb3a4:compliance.signupTerms"
    assert variables["supportedThreeDsExperiences"] == ["IFRAME"]
    assert "threeDomainSecure(experiences: $supportedThreeDsExperiences)" in paypal_protocol_signup.Q_SIGNUP
    assert "signUpNewMember(" in paypal_protocol_signup.Q_SIGNUP
    assert "onboardAccount:" in paypal_protocol_signup.Q_SIGNUP
    assert "$password: String" in paypal_protocol_signup.Q_SIGNUP
    assert "$password: String!" not in paypal_protocol_signup.Q_SIGNUP


def test_paypal_protocol_signup_extracts_encoded_content_identifier():
    assert paypal_protocol_signup._extract_content_identifier(
        "JP%3Aja%3Aabc123abc123abc1%3Acompliance.signupTerms",
        "JP",
        "ja",
    ) == "JP:ja:abc123abc123abc1:compliance.signupTerms"
    assert paypal_protocol_signup._extract_content_identifier(
        r"JP\\u003Aja\\u003Aabc123abc123abc1\\u003Acompliance.signupTerms",
        "JP",
        "ja",
    ) == "JP:ja:abc123abc123abc1:compliance.signupTerms"


def test_paypal_protocol_signup_error_metadata_is_allowlisted():
    metadata = paypal_protocol_signup._signup_error_metadata(
        {
            "message": "OAS_ERROR",
            "checkpoints": ["RISK_DECLINED"],
            "path": ["signUpNewMember"],
            "extensions": {"code": "OAS_ERROR", "correlationId": "corr-123"},
            "errorData": {"accessToken": "secret", "email": "private@example.com", "statusCode": 403},
        }
    )

    assert metadata == {
        "checkpoints": ["RISK_DECLINED"],
        "path": ["signUpNewMember"],
        "code": "OAS_ERROR",
        "correlationId": "corr-123",
        "statusCode": "403",
    }
    assert "secret" not in json.dumps(metadata)
    assert "private@example.com" not in json.dumps(metadata)


def test_paypal_protocol_signup_classifies_create_member_oas_as_browser_context_required():
    assert paypal_protocol_signup._classify_signup_error(
        {
            "errors": [{"message": "OAS_ERROR"}],
            "first_error": {"message": "OAS_ERROR"},
            "error_code": "OAS_ERROR",
            "error_metadata": {"checkpoints": ["createMemberAccount"], "statusCode": "200"},
        }
    ) == (
        "paypal_browser_context_required",
        "PayPal 在 createMemberAccount 阶段拒绝纯协议请求，需要真实浏览器风险上下文",
    )


def test_paypal_protocol_signup_warmup_uses_jp_home_for_jp_locale():
    calls = []

    class FakeHttp:
        def get(self, url, *, headers=None, timeout=None, allow_redirects=None):
            calls.append((url, headers or {}, timeout, allow_redirects))

    paypal_protocol_signup._warmup_paypal_session(
        FakeHttp(),
        timeout=9,
        locale_country="JP",
        locale_lang="ja",
    )

    assert calls[0][0] == "https://www.paypal.com/jp/home"
    assert calls[0][1]["User-Agent"].startswith("Mozilla/5.0 (iPhone; CPU iPhone OS 18_2")
    assert calls[0][1]["Accept-Language"] == "en-US,en;q=0.9"
    assert "image/avif" in calls[0][1]["Accept"]


def test_paypal_protocol_signup_prime_matches_roxy_ios_navigation_headers():
    calls = []

    class FakeHttp:
        def get(self, url, *, headers=None, timeout=None, allow_redirects=None):
            calls.append((url, headers or {}, timeout, allow_redirects))
            return FakeResponse(text="<html>EC-12345678901234567 checkoutweb signup</html>", url=url)

    paypal_protocol_signup._prime_checkout_signup(
        FakeHttp(),
        signup_url="https://www.paypal.com/checkoutweb/signup?token=EC-12345678901234567",
        referer="https://www.paypal.com/agreements/approve?ba_token=BA-DEMO",
        locale_country="JP",
        locale_lang="ja",
        timeout=10,
    )

    headers = calls[0][1]
    assert headers["User-Agent"].startswith("Mozilla/5.0 (iPhone; CPU iPhone OS 18_2")
    assert headers["Accept-Language"] == "en-US,en;q=0.9"
    assert headers["Sec-Fetch-Site"] == "none"
    assert "Sec-Fetch-User" not in headers


def test_paypal_protocol_signup_coerce_removes_ul_onboard_redirect():
    url = paypal_protocol_signup._coerce_onboard_url(
        "https://www.paypal.com/agreements/approve?ba_token=BA-DEMO&ulOnboardRedirect=true&ssrt=123",
        ba_token="BA-DEMO",
        locale_country="JP",
        locale_lang="ja",
    )

    assert "ulOnboardRedirect" not in url
    assert "ssrt=123" in url
    assert "locale.x=ja_JP" in url


def test_paypal_protocol_signup_prime_rejects_datadome_interstitial_with_ec_context():
    class FakeHttp:
        def get(self, url, **_kwargs):
            return FakeResponse(
                status_code=403,
                text='<html><script src="https://ct.ddc.paypal.com/i.js"></script>'
                '<form id="ads-dd-captcha">EC-12345678901234567</form></html>',
                url=url,
            )

    with pytest.raises(RuntimeError, match="DataDome"):
        paypal_protocol_signup._prime_checkout_signup(
            FakeHttp(),
            signup_url="https://www.paypal.com/checkoutweb/signup?token=EC-12345678901234567",
            referer="https://www.paypal.com/agreements/approve?ba_token=BA-DEMO",
            locale_country="JP",
            locale_lang="ja",
            timeout=10,
        )


def test_tls_client_http_session_adapter_maps_requests_timeout_keyword():
    calls = []

    class FakeTlsSession:
        headers = {}
        cookies = {}

        def get(self, url, **kwargs):
            calls.append(("GET", url, kwargs))
            return types.SimpleNamespace(status_code=200)

        def post(self, url, **kwargs):
            calls.append(("POST", url, kwargs))
            return types.SimpleNamespace(status_code=200)

    adapter = paypal_bind_executor._TlsClientHttpSessionAdapter(FakeTlsSession())

    adapter.get("https://www.paypal.com/jp/home", timeout=12, allow_redirects=True)
    adapter.post("https://www.paypal.com/graphql", json={"ok": True}, timeout=13)

    assert calls[0] == (
        "GET",
        "https://www.paypal.com/jp/home",
        {"allow_redirects": True, "timeout_seconds": 12},
    )
    assert calls[1] == (
        "POST",
        "https://www.paypal.com/graphql",
        {"json": {"ok": True}, "timeout_seconds": 13},
    )


def test_paypal_protocol_signup_uses_jp_locale_and_phone_country(monkeypatch):
    captured = {}

    def fake_run_paypal_no_card_protocol_signup(_http, **kwargs):
        captured.update(kwargs)
        return {"status": "failed", "failure_stage": "paypal_protocol", "message": "stop"}

    monkeypatch.setattr(paypal_bind_executor, "_extract_checkout_session_id", lambda _url: "cs_live_demo")
    monkeypatch.setattr(paypal_bind_executor, "_new_http_session", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        paypal_bind_executor,
        "_paypal_protocol_stripe_init",
        lambda *_args, **_kwargs: {
            "init_checksum": "init",
            "stripe_js_id": "js",
            "elements_session_id": "es",
            "elements_session_config_id": "esc",
            "config_id": "cfg",
            "expected_amount": "0",
            "currency": "jpy",
            "return_url": "",
            "stripe_hosted_url": "",
            "locale": "ja",
            "stripe_version": "2025-03-31.basil",
        },
    )
    monkeypatch.setattr(paypal_bind_executor, "_paypal_protocol_elements_session", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        paypal_bind_executor, "_paypal_protocol_update_payment_page_address", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        paypal_bind_executor, "_paypal_protocol_create_payment_method", lambda *_args, **_kwargs: "pm_demo"
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_paypal_protocol_confirm_checkout",
        lambda *_args, **_kwargs: {
            "next_action": {"redirect_to_url": {"url": "https://www.paypal.com/pay?token=BA-DEMO&ul=1"}}
        },
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_paypal_protocol_resolve_approve_url",
        lambda *_args, **_kwargs: ("https://www.paypal.com/pay?token=BA-DEMO&ul=1", "BA-DEMO"),
    )
    monkeypatch.setattr(
        paypal_bind_executor, "run_paypal_no_card_protocol_signup", fake_run_paypal_no_card_protocol_signup
    )

    result = paypal_bind_executor._run_paypal_protocol_flow(
        email="user@example.com",
        checkout_url="https://pay.openai.com/c/pay/cs_live_demo",
        proxy_url=None,
        paypal_mode="create_account",
        signup_profile={
            "email": "pp-demo@gmail.com",
            "password": "Secret123!",
            "phone": "+819012345678",
            "sms_url": "https://sms.example",
            "country": "JP",
            "state": "Tokyo",
            "city": "Chiyoda",
            "zip": "100-0001",
            "address1": "1-1 Chiyoda",
        },
        phone_accounts=None,
        billing_payload={
            "name": "James Smith",
            "country": "JP",
            "state": "Tokyo",
            "city": "Chiyoda",
            "zip": "100-0001",
            "address1": "1-1 Chiyoda",
        },
        timeout_seconds=120,
        paypal_country="JP",
        paypal_lang="ja",
    )

    assert result["failure_stage"] == "paypal_protocol"
    assert captured["locale_country"] == "JP"
    assert captured["locale_lang"] == "ja"


def test_paypal_protocol_stops_when_checkout_session_lacks_paypal(monkeypatch):
    monkeypatch.setattr(paypal_bind_executor, "_extract_checkout_session_id", lambda _url: "cs_live_demo")
    monkeypatch.setattr(paypal_bind_executor, "_new_http_session", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        paypal_bind_executor,
        "_paypal_protocol_stripe_init",
        lambda *_args, **_kwargs: {
            "raw": {"payment_method_types": ["card"]},
            "init_checksum": "init",
            "stripe_js_id": "js",
            "elements_session_id": "es",
            "elements_session_config_id": "esc",
            "config_id": "cfg",
            "expected_amount": "0",
            "currency": "jpy",
            "return_url": "",
            "stripe_hosted_url": "",
            "locale": "ja",
            "stripe_version": "2025-03-31.basil",
        },
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_paypal_protocol_elements_session",
        lambda *_args, **_kwargs: pytest.fail("elements session should not run without paypal support"),
    )

    result = paypal_bind_executor._run_paypal_protocol_flow(
        email="user@example.com",
        checkout_url="https://pay.openai.com/c/pay/cs_live_demo",
        proxy_url=None,
        paypal_mode="create_account",
        signup_profile={"phone": "+819012345678", "sms_url": "https://sms.example", "country": "JP"},
        phone_accounts=None,
        billing_payload={
            "name": "James Smith",
            "country": "JP",
            "state": "Tokyo",
            "city": "Chiyoda",
            "zip": "100-0001",
            "address1": "1-1 Chiyoda",
        },
        timeout_seconds=120,
        paypal_country="JP",
        paypal_lang="ja",
    )

    assert result["status"] == "failed"
    assert result["failure_stage"] == "paypal_payment_method_unavailable"
    assert "未启用 PayPal" in result["message"]


def test_paypal_protocol_stripe_init_prefers_browser_full_version():
    http = FakeHttp(
        [
            (
                "POST",
                "/v1/payment_pages/cs_live_demo/init",
                FakeResponse(
                    json_data={
                        "init_checksum": "init",
                        "currency": "usd",
                        "payment_method_types": ["card", "link", "paypal"],
                    }
                ),
            )
        ]
    )

    result = paypal_bind_executor._paypal_protocol_stripe_init(http, "cs_live_demo", "pk_live_demo")

    request_data = http.requests[0]["kwargs"]["data"]
    assert request_data["_stripe_version"] == paypal_bind_executor.STRIPE_VERSION_FULL
    assert request_data["elements_session_client[client_betas][0]"] == "custom_checkout_server_updates_1"
    assert request_data["elements_session_client[client_betas][1]"] == "custom_checkout_manual_approval_1"
    assert request_data["elements_options_client[saved_payment_method][enable_save]"] == "never"
    assert result["payment_method_types"] == {"card", "link", "paypal"}
    assert result["elements_options_client"]["elements_options_client[saved_payment_method][enable_save]"] == "never"


def test_paypal_protocol_stripe_init_falls_back_to_base_version_when_full_rejected():
    http = FakeHttp(
        [
            ("POST", "/v1/payment_pages/cs_live_demo/init", FakeResponse(status_code=400, text="parameter_unknown")),
            (
                "POST",
                "/v1/payment_pages/cs_live_demo/init",
                FakeResponse(json_data={"init_checksum": "init", "currency": "usd"}),
            ),
        ]
    )

    result = paypal_bind_executor._paypal_protocol_stripe_init(http, "cs_live_demo", "pk_live_demo")

    assert http.requests[0]["kwargs"]["data"]["_stripe_version"] == paypal_bind_executor.STRIPE_VERSION_FULL
    assert http.requests[1]["kwargs"]["data"]["_stripe_version"] == paypal_bind_executor.STRIPE_VERSION_BASE
    assert "elements_session_client[client_betas][0]" not in http.requests[1]["kwargs"]["data"]
    assert result["stripe_version"] == paypal_bind_executor.STRIPE_VERSION_BASE
    assert result["elements_options_client"] == {}


def test_paypal_protocol_elements_session_matches_browser_payment_method_types():
    http = FakeHttp(
        [
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
            )
        ]
    )
    init_ctx = {
        "stripe_js_id": "stripe-js",
        "elements_session_id": "elements-session",
        "elements_session_config_id": "elements-config",
        "expected_amount": "0",
        "currency": "usd",
        "locale": "ja-JP",
        "stripe_version": paypal_bind_executor.STRIPE_VERSION_FULL,
    }

    paypal_bind_executor._paypal_protocol_elements_session(http, "cs_live_demo", "pk_live_demo", init_ctx)

    params = http.requests[0]["kwargs"]["params"]
    assert params["deferred_intent[payment_method_types][0]"] == "card"
    assert params["deferred_intent[payment_method_types][1]"] == "link"
    assert params["deferred_intent[payment_method_types][2]"] == "paypal"
    assert params["currency"] == "usd"
    assert params["client_betas[0]"] == "custom_checkout_server_updates_1"
    assert init_ctx["elements_session_id"] == "elements_session_real"
    assert init_ctx["config_id"] == "checkout_config_real"
    assert init_ctx["elements_session_config_id"] == "elements_config_real"


def test_paypal_protocol_retries_authenticated_socks_proxy_as_http_on_curl_97(monkeypatch):
    progress_events = []

    def fake_new_http_session(proxy_url, **_kwargs):
        return {"proxy_url": proxy_url}

    init_calls = []

    def fake_stripe_init(http, *_args, **_kwargs):
        init_calls.append(http["proxy_url"])
        if len(init_calls) == 1:
            raise RuntimeError("Failed to perform, curl: (97) Received invalid version in initial SOCKS5 response.")
        return _stripe_confirm_init_ctx(raw={"payment_method_types": ["card"]})

    monkeypatch.setattr(paypal_bind_executor, "_new_http_session", fake_new_http_session)
    monkeypatch.setattr(paypal_bind_executor, "_paypal_protocol_stripe_init", fake_stripe_init)

    result = paypal_bind_executor._run_paypal_protocol_flow(
        email="user@example.com",
        checkout_url="https://pay.openai.com/c/pay/cs_demo",
        proxy_url="socks5://user:pass@proxy.example:3010",
        paypal_mode="create_account",
        signup_profile={},
        phone_accounts=[],
        billing_payload={
            "name": "Taro Yamada",
            "country": "JP",
            "state": "Tokyo",
            "city": "Chiyoda",
            "zip": "100-0001",
            "address1": "1-1 Chiyoda",
        },
        timeout_seconds=60,
        paypal_country="JP",
        paypal_lang="ja",
        on_progress=progress_events.append,
    )

    assert result["failure_stage"] == "paypal_payment_method_unavailable"
    assert init_calls == [
        "socks5://user:pass@proxy.example:3010",
        "http://user:pass@proxy.example:3010",
    ]
    assert any(event["stage"] == "paypal_protocol_proxy_http_fallback" for event in progress_events)


def test_paypal_authorize_flow_rotates_phone_pool_on_phone_rejection(monkeypatch):
    used_phones = []
    events = []

    class FakePage:
        url = "https://www.paypal.com/checkoutweb/signup"

        class keyboard:
            @staticmethod
            def press(_key):
                return None

    class FakeApi:
        page = FakePage()

    classify_calls = {"count": 0}

    def fake_classify(_url, _body):
        classify_calls["count"] += 1
        if classify_calls["count"] == 1:
            return {
                "status": "failed",
                "failure_stage": "paypal_phone_rejected",
                "message": "PayPal 拒绝当前手机号，请更换手机号",
            }
        return None

    def fake_signup_flow(_api, *, signup_profile, state, **_kwargs):
        used_phones.append(signup_profile["phone"])
        return False, "stop", True

    monkeypatch.setattr(paypal_bind_executor, "_sync_relevant_payment_page", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(paypal_bind_executor, "_force_paypal_us_locale", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(paypal_bind_executor, "_ensure_paypal_hosted_captcha_bypass", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        paypal_bind_executor, "_inspect_paypal_page", lambda _api: {"body_text": "", "registration_ready": True}
    )
    monkeypatch.setattr(paypal_bind_executor, "classify_paypal_checkout_state", fake_classify)
    monkeypatch.setattr(paypal_bind_executor, "_dismiss_paypal_phone_rejected_prompt", lambda _api: True)
    monkeypatch.setattr(paypal_bind_executor, "_capture_screenshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(paypal_bind_executor, "_run_paypal_signup_flow", fake_signup_flow)
    monkeypatch.setattr(paypal_bind_executor.time, "sleep", lambda _seconds: None)

    result = paypal_bind_executor._run_paypal_authorize_flow(
        FakeApi(),
        paypal_mode="create_account",
        credentials={},
        signup_profile={
            "email": "pp-demo@gmail.com",
            "password": "Secret123!",
            "phone": "8352880840",
            "sms_url": "https://sms.example/one",
            "otp_channel": "sms",
        },
        phone_accounts=[
            {"phone_number": "+18352880840", "sms_url": "https://sms.example/one"},
            {"phone_number": "+18352623053", "sms_url": "https://sms.example/two"},
        ],
        session_id="demo",
        screenshot_paths=[],
        timeout_seconds=60,
        on_progress=lambda event: events.append(event),
    )

    assert result["status"] == "failed"
    assert used_phones == ["8352623053"]
    assert any(event.get("stage") == "paypal_phone_rejected_rotate" for event in events)


def test_paypal_authorize_flow_does_not_force_locale_after_phone_submitted(monkeypatch):
    calls = []

    class FakePage:
        url = "https://www.paypal.com/checkoutweb/signup"

    class FakeApi:
        page = FakePage()

    signup_calls = {"count": 0}

    def fake_signup_flow(_api, *, state, **_kwargs):
        signup_calls["count"] += 1
        calls.append(("signup_flow", bool(state.get("signup_submitted"))))
        state["signup_submitted"] = True
        if signup_calls["count"] == 1:
            return True, "", True
        return False, "stop", True

    def fake_force_locale(*_args, **_kwargs):
        calls.append(("force_locale", None))
        return False

    monkeypatch.setattr(paypal_bind_executor, "_sync_relevant_payment_page", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(paypal_bind_executor, "_force_paypal_us_locale", fake_force_locale)
    monkeypatch.setattr(paypal_bind_executor, "_ensure_paypal_hosted_captcha_bypass", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        paypal_bind_executor, "_inspect_paypal_page", lambda _api: {"body_text": "", "registration_ready": True}
    )
    monkeypatch.setattr(paypal_bind_executor, "classify_paypal_checkout_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(paypal_bind_executor, "_capture_screenshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(paypal_bind_executor, "_run_paypal_signup_flow", fake_signup_flow)
    monkeypatch.setattr(paypal_bind_executor.time, "sleep", lambda _seconds: None)

    result = paypal_bind_executor._run_paypal_authorize_flow(
        FakeApi(),
        paypal_mode="create_account",
        credentials={},
        signup_profile={
            "email": "pp-demo@gmail.com",
            "password": "Secret123!",
            "phone": "8352880840",
            "sms_url": "https://sms.example/one",
            "otp_channel": "sms",
        },
        session_id="demo",
        screenshot_paths=[],
        timeout_seconds=60,
        on_progress=lambda _event: None,
    )

    assert result["status"] == "failed"
    assert calls == [
        ("force_locale", None),
        ("signup_flow", False),
        ("signup_flow", True),
    ]


def test_paypal_create_account_entry_url_forces_onboard_redirect():
    url = paypal_bind_executor._paypal_create_account_entry_url(
        "https://www.paypal.com/pay?token=BA-123456789&ssrt=abc",
        country="JP",
        lang="ja",
    )

    assert url.startswith("https://www.paypal.com/agreements/approve?")
    assert "ba_token=BA-123456789" in url
    assert "ulOnboardRedirect=true" in url
    assert "modxo_redirect_reason=guest_user" in url
    assert "country.x=JP" in url
    assert "locale.x=ja_JP" in url


def test_paypal_signup_flow_redirects_login_page_to_create_account(monkeypatch):
    calls = []

    class FakePage:
        def __init__(self):
            self.url = "https://www.paypal.com/pay?token=BA-123456789"

        def goto(self, url, **_kwargs):
            calls.append(("goto", url))
            self.url = url

        def wait_for_timeout(self, _timeout):
            calls.append(("wait", _timeout))

    class FakeApi:
        def __init__(self):
            self.page = FakePage()

    monkeypatch.setattr(paypal_bind_executor, "_click_paypal_create_account", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        paypal_bind_executor,
        "_set_locator_value",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("login email field must not be filled as signup")
        ),
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_submit_paypal_login_step",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("login submit must not run in signup flow")),
    )

    ok, error, handled = paypal_bind_executor._run_paypal_signup_flow(
        FakeApi(),
        signup_profile={"email": "new-paypal@example.com"},
        state={
            "body_text": "Log in to your PayPal account",
            "needs_login": True,
            "email_locator": object(),
            "password_locator": object(),
        },
        paypal_country="JP",
        paypal_lang="ja",
        on_progress=lambda _event: None,
    )

    assert ok is True
    assert error == ""
    assert handled is True
    assert calls[0][0] == "goto"
    assert "ulOnboardRedirect=true" in calls[0][1]


def test_paypal_authorize_create_account_never_submits_login(monkeypatch):
    class FakePage:
        url = "https://www.paypal.com/signin"

    class FakeApi:
        page = FakePage()

    monkeypatch.setattr(paypal_bind_executor, "_sync_relevant_payment_page", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(paypal_bind_executor, "_force_paypal_us_locale", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(paypal_bind_executor, "_ensure_paypal_hosted_captcha_bypass", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(paypal_bind_executor, "_ddc_slider_visible", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(paypal_bind_executor, "_has_ddc_iframe", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(paypal_bind_executor, "_is_ddc_blocked_page", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        paypal_bind_executor,
        "_inspect_paypal_page",
        lambda _api: {"body_text": "Log in", "needs_login": True, "email_locator": object()},
    )
    monkeypatch.setattr(paypal_bind_executor, "classify_paypal_checkout_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(paypal_bind_executor, "_capture_screenshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(paypal_bind_executor, "_run_paypal_signup_flow", lambda *_args, **_kwargs: (True, "", False))
    monkeypatch.setattr(
        paypal_bind_executor,
        "_submit_paypal_login_step",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("login submit must not run for create_account")),
    )

    result = paypal_bind_executor._run_paypal_authorize_flow(
        FakeApi(),
        paypal_mode="create_account",
        credentials={"email": "existing@example.com", "password": "Secret123!"},
        signup_profile={"email": "new-paypal@example.com", "password": "Secret123!"},
        session_id="demo",
        screenshot_paths=[],
        timeout_seconds=20,
    )

    assert result["status"] == "failed"
    assert result["failure_stage"] == "paypal_signup"


def test_paypal_authorize_create_account_redirects_signin_with_saved_ba(monkeypatch):
    calls = []

    class FakePage:
        def __init__(self):
            self.url = "https://www.paypal.com/signin"

        def goto(self, url, **_kwargs):
            calls.append(url)
            self.url = "https://www.paypal.com/checkoutweb/signup?token=EC-DEMO"

        def wait_for_timeout(self, _timeout):
            return None

    class FakeApi:
        def __init__(self):
            self.page = FakePage()

    inspect_calls = {"count": 0}

    def fake_inspect(api):
        inspect_calls["count"] += 1
        if inspect_calls["count"] == 1:
            return {"body_text": "Log in", "needs_login": True, "email_locator": object()}
        return {"body_text": "signup", "registration_ready": True}

    def fake_signup_flow(_api, *, state, **_kwargs):
        if state.get("needs_login"):
            return True, "", False
        return {"status": "failed"}

    monkeypatch.setattr(paypal_bind_executor, "_sync_relevant_payment_page", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(paypal_bind_executor, "_force_paypal_us_locale", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(paypal_bind_executor, "_ensure_paypal_hosted_captcha_bypass", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(paypal_bind_executor, "_ddc_slider_visible", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(paypal_bind_executor, "_has_ddc_iframe", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(paypal_bind_executor, "_is_ddc_blocked_page", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(paypal_bind_executor, "_inspect_paypal_page", fake_inspect)
    monkeypatch.setattr(paypal_bind_executor, "classify_paypal_checkout_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(paypal_bind_executor, "_capture_screenshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(paypal_bind_executor.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        paypal_bind_executor,
        "_submit_paypal_login_step",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("login submit must not run for create_account")),
    )

    signup_calls = {"count": 0}

    def fake_run_signup_flow(_api, *, state, **_kwargs):
        signup_calls["count"] += 1
        if signup_calls["count"] == 1:
            return True, "", False
        return False, "stop", True

    monkeypatch.setattr(paypal_bind_executor, "_run_paypal_signup_flow", fake_run_signup_flow)

    result = paypal_bind_executor._run_paypal_authorize_flow(
        FakeApi(),
        paypal_mode="create_account",
        credentials={},
        signup_profile={"email": "new-paypal@example.com", "password": "Secret123!"},
        session_id="demo",
        screenshot_paths=[],
        timeout_seconds=20,
        paypal_country="JP",
        paypal_lang="ja",
        paypal_ba_token="BA-SAVED123",
    )

    assert result["status"] == "failed"
    assert calls
    assert "ba_token=BA-SAVED123" in calls[0]
    assert "ulOnboardRedirect=true" in calls[0]


def test_paypal_auto_flow_uses_long_authorize_timeout_for_signup(monkeypatch):
    captured = {}

    class FakePage:
        url = "https://www.paypal.com/checkoutweb/signup"

    class FakeApi:
        page = FakePage()

    def fake_authorize_flow(_api, **kwargs):
        captured["timeout_seconds"] = kwargs["timeout_seconds"]
        return {
            "status": "failed",
            "failure_stage": "paypal_signup",
            "message": "stop",
            "screenshot_paths": [],
        }

    monkeypatch.setattr(paypal_bind_executor, "_run_paypal_authorize_flow", fake_authorize_flow)

    result = paypal_bind_executor._run_paypal_auto_flow(
        FakeApi(),
        email="user@example.com",
        checkout_url="https://pay.openai.com/c/pay/cs_test",
        paypal_mode="create_account",
        paypal_credentials={},
        signup_profile={"email": "pp-demo@gmail.com", "password": "Secret123!", "phone": "8352880840"},
        session_id="demo",
        screenshot_paths=[],
        timeout_seconds=60,
    )

    assert result["status"] == "failed"
    assert captured["timeout_seconds"] >= paypal_bind_executor.PAYPAL_AUTO_AUTHORIZE_MIN_TIMEOUT_SECONDS


def test_paypal_result_timeout_has_long_minimum():
    minimum = paypal_bind_executor.PAYPAL_AUTO_RESULT_MIN_TIMEOUT_SECONDS

    assert paypal_bind_executor._paypal_result_timeout_seconds(60) == minimum
    assert paypal_bind_executor._paypal_result_timeout_seconds(0) == minimum
    assert paypal_bind_executor._paypal_result_timeout_seconds(minimum + 30) == minimum + 30


def test_paypal_auto_flow_uses_long_result_timeout_after_authorize(monkeypatch):
    captured = {}

    class FakePage:
        url = "https://www.paypal.com/checkoutweb/signup"

    class FakeApi:
        page = FakePage()

    def fake_wait_for_result(_api, **kwargs):
        captured["timeout_seconds"] = kwargs["timeout_seconds"]
        return {"status": "success", "failure_stage": "", "message": "done", "screenshot_paths": []}

    monkeypatch.setattr(paypal_bind_executor, "_run_paypal_authorize_flow", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(paypal_bind_executor, "_wait_for_paypal_result", fake_wait_for_result)

    result = paypal_bind_executor._run_paypal_auto_flow(
        FakeApi(),
        email="user@example.com",
        checkout_url="https://pay.openai.com/c/pay/cs_test",
        paypal_mode="create_account",
        paypal_credentials={},
        signup_profile={"email": "pp-demo@gmail.com", "password": "Secret123!", "phone": "8352880840"},
        session_id="demo",
        screenshot_paths=[],
        timeout_seconds=60,
    )

    assert result["status"] == "success"
    assert captured["timeout_seconds"] == paypal_bind_executor.PAYPAL_AUTO_RESULT_MIN_TIMEOUT_SECONDS


def test_wait_for_paypal_subscription_return_confirms_loaded_openai_page(monkeypatch):
    class FakePage:
        url = "https://pay.openai.com/c/pay/cs_live_return"

        def __init__(self):
            self.load_states = []

        def wait_for_load_state(self, state, timeout):
            self.load_states.append((state, timeout))

    class FakeApi:
        def __init__(self):
            self.page = FakePage()

    sleeps = []
    progress_events = []
    api = FakeApi()

    monkeypatch.setattr(paypal_bind_executor, "_sync_relevant_payment_page", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(paypal_bind_executor, "_capture_screenshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(paypal_bind_executor.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = paypal_bind_executor._wait_for_paypal_subscription_return(
        api,
        session_id="demo",
        screenshot_paths=[],
        timeout_seconds=paypal_bind_executor.PAYPAL_APPROVE_RETURN_TIMEOUT_SECONDS,
        on_progress=progress_events.append,
    )

    assert result["status"] == "success"
    assert result["message"] == "PayPal 授权后已回跳 ChatGPT/OpenAI 页面，确认绑定成功"
    assert api.page.load_states and api.page.load_states[0][0] == "load"
    assert sleeps == [paypal_bind_executor.PAYPAL_APPROVE_RETURN_SETTLE_SECONDS]
    assert [event["stage"] for event in progress_events] == ["paypal_return_wait", "paypal_return_confirmed"]


def test_wait_for_paypal_subscription_return_times_out_after_120_seconds(monkeypatch):
    class FakePage:
        url = "https://www.paypal.com/agreements/approve?ba_token=BA-123"

    class FakeApi:
        page = FakePage()

    times = iter([0, paypal_bind_executor.PAYPAL_APPROVE_RETURN_TIMEOUT_SECONDS + 1])
    monkeypatch.setattr(paypal_bind_executor.time, "time", lambda: next(times))
    monkeypatch.setattr(paypal_bind_executor, "_capture_screenshot", lambda *_args, **_kwargs: None)

    result = paypal_bind_executor._wait_for_paypal_subscription_return(
        FakeApi(),
        session_id="demo",
        screenshot_paths=[],
        timeout_seconds=paypal_bind_executor.PAYPAL_APPROVE_RETURN_TIMEOUT_SECONDS,
    )

    assert result["status"] == "needs_review"
    assert result["failure_stage"] == "paypal_return_timeout"


def test_wait_for_paypal_subscription_return_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}

    def fake_wait_for_return(_api, **kwargs):
        captured.update(kwargs)
        return {"status": "success"}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "wait_for_paypal_subscription_return",
        fake_wait_for_return,
    )

    api = object()
    screenshot_paths = []
    def on_progress(_event):
        return None
    def is_cancelled():
        return False
    assert paypal_bind_executor._wait_for_paypal_subscription_return(
        api,
        session_id="demo",
        screenshot_paths=screenshot_paths,
        timeout_seconds=120,
        is_cancelled=is_cancelled,
        on_progress=on_progress,
    ) == {"status": "success"}
    assert captured["session_id"] == "demo"
    assert captured["screenshot_paths"] is screenshot_paths
    assert captured["timeout_seconds"] == 120
    assert captured["settle_seconds"] == paypal_bind_executor.PAYPAL_APPROVE_RETURN_SETTLE_SECONDS
    assert captured["is_cancelled"] is is_cancelled
    assert captured["on_progress"] is on_progress
    assert captured["progress_event"] is paypal_bind_executor._progress_event
    assert captured["capture_screenshot"] is paypal_bind_executor._capture_screenshot
    assert captured["build_result"] is paypal_bind_executor._build_result
    assert captured["sync_relevant_payment_page"] is paypal_bind_executor._sync_relevant_payment_page
    assert captured["is_return_url"] is paypal_bind_executor._is_chatgpt_or_openai_return_url
    assert captured["is_paypal_host"] is paypal_bind_executor._is_paypal_host
    assert captured["classify_paypal_checkout_state"] is paypal_bind_executor.classify_paypal_checkout_state
    assert captured["body_excerpt"] is paypal_bind_executor._body_excerpt
    assert captured["time_fn"] is paypal_bind_executor.time.time
    assert captured["sleep"] is paypal_bind_executor.time.sleep


def test_handle_paypal_left_host_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    progress_events = []
    on_progress = progress_events.append

    def fake_handle(**kwargs):
        captured.update(kwargs)
        return {"action": "return_none", "otp_phone_lock_key": ""}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_left_host",
        fake_handle,
    )

    assert paypal_bind_executor._handle_paypal_left_host(
        current_url="https://chatgpt.com/checkout/success",
        otp_phone_lock_key="otp-lock",
        on_progress=on_progress,
    ) == {"action": "return_none", "otp_phone_lock_key": ""}
    assert captured["current_url"] == "https://chatgpt.com/checkout/success"
    assert captured["otp_phone_lock_key"] == "otp-lock"
    assert captured["paypal_host"] is paypal_bind_executor._is_paypal_host
    assert captured["release_otp_phone_lock"] is paypal_bind_executor._release_paypal_otp_phone_lock
    assert captured["progress_event"] is paypal_bind_executor._progress_event
    assert captured["on_progress"] is on_progress


def test_paypal_left_host_values_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_values(left_host_result):
        captured["left_host_result"] = left_host_result
        return "otp-lock"

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_left_host_values",
        fake_values,
    )

    left_host_result = {"action": "return_none"}
    assert paypal_bind_executor._paypal_left_host_values(left_host_result) == "otp-lock"
    assert captured["left_host_result"] is left_host_result


def test_prepare_paypal_authorize_flow_context_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    signup_profile = {"email": "signup@example.com"}
    phone_accounts = [{"phone": "+12025550123"}]
    credentials = {"email": "login@example.com", "password": "secret"}

    def fake_prepare(**kwargs):
        captured.update(kwargs)
        return {"deadline": 123.0}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "prepare_paypal_authorize_flow_context",
        fake_prepare,
    )

    assert paypal_bind_executor._prepare_paypal_authorize_flow_context(
        paypal_mode="create_account",
        credentials=credentials,
        signup_profile=signup_profile,
        phone_accounts=phone_accounts,
        timeout_seconds=120,
        paypal_country="JP",
        paypal_lang="ja",
    ) == {"deadline": 123.0}
    assert captured["paypal_mode"] == "create_account"
    assert captured["credentials"] is credentials
    assert captured["signup_profile"] is signup_profile
    assert captured["phone_accounts"] is phone_accounts
    assert captured["timeout_seconds"] == 120
    assert captured["paypal_country"] == "JP"
    assert captured["paypal_lang"] == "ja"
    assert captured["normalize_paypal_country"] is paypal_bind_executor._normalize_paypal_country
    assert captured["normalize_paypal_lang"] is paypal_bind_executor._normalize_paypal_lang
    assert captured["signup_profiles_for_phone_pool"] is paypal_bind_executor._paypal_signup_profiles_for_phone_pool
    assert captured["now"] is paypal_bind_executor.time.time


def test_prepare_paypal_authorize_flow_context_snapshots_existing_signup_otp(monkeypatch):
    def fake_prepare(**_kwargs):
        profile = {"phone": "09040524462", "sms_url": "https://sms.example.test"}
        return {
            "deadline": 123.0,
            "signup_profile_index": 0,
            "signup_profiles": [profile],
            "active_signup_profile": profile,
        }

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "prepare_paypal_authorize_flow_context",
        fake_prepare,
    )
    monkeypatch.setattr(paypal_bind_executor.sms_otp_service, "fetch_sms_code", lambda _url: "328238")

    context = paypal_bind_executor._prepare_paypal_authorize_flow_context(
        paypal_mode="create_account",
        credentials={},
        signup_profile={},
        phone_accounts=[],
        timeout_seconds=120,
        paypal_country="JP",
        paypal_lang="ja",
    )

    assert context["signup_profiles"][0]["_ignored_otps"] == ["328238"]
    assert context["active_signup_profile"]["_ignored_otps"] == ["328238"]


def test_handle_paypal_authorize_cancelled_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    progress_events = []
    on_progress = progress_events.append
    def is_cancelled():
        return True

    def fake_handle(**kwargs):
        captured.update(kwargs)
        return {"action": "failed"}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_authorize_cancelled",
        fake_handle,
    )

    assert paypal_bind_executor._handle_paypal_authorize_cancelled(
        is_cancelled=is_cancelled,
        otp_phone_lock_key="otp-lock",
        on_progress=on_progress,
    ) == {"action": "failed"}
    assert captured["is_cancelled"] is is_cancelled
    assert captured["otp_phone_lock_key"] == "otp-lock"
    assert captured["release_otp_phone_lock"] is paypal_bind_executor._release_paypal_otp_phone_lock
    assert captured["on_progress"] is on_progress


def test_paypal_authorize_cancelled_result_fields_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_fields(cancelled_result):
        captured["cancelled_result"] = cancelled_result
        return ("", "failed", "custom-cancelled", "post_submit", "cancelled")

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_authorize_cancelled_result_fields",
        fake_fields,
    )

    cancelled_result = {"action": "failed"}
    assert paypal_bind_executor._paypal_authorize_cancelled_result_fields(cancelled_result) == (
        "",
        "failed",
        "custom-cancelled",
        "post_submit",
        "cancelled",
    )
    assert captured["cancelled_result"] is cancelled_result


def test_handle_paypal_phone_rejected_rotation_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    progress_events = []
    on_progress = progress_events.append
    classified = {"failure_stage": "paypal_phone_rejected"}
    active_signup_profile = {"phone": "111"}
    signup_profiles = [active_signup_profile, {"phone": "222"}]

    def fake_handle(_api, **kwargs):
        captured["api"] = _api
        captured.update(kwargs)
        return {"action": "continue", "signup_profile_index": 1}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_phone_rejected_rotation",
        fake_handle,
    )

    api = object()
    assert paypal_bind_executor._handle_paypal_phone_rejected_rotation(
        api,
        paypal_mode="create_account",
        classified=classified,
        signup_profile_index=0,
        signup_profiles=signup_profiles,
        active_signup_profile=active_signup_profile,
        current_url="https://www.paypal.com/checkout",
        otp_phone_lock_key="otp-lock",
        on_progress=on_progress,
    ) == {"action": "continue", "signup_profile_index": 1}
    assert captured["api"] is api
    assert captured["paypal_mode"] == "create_account"
    assert captured["classified"] is classified
    assert captured["signup_profile_index"] == 0
    assert captured["signup_profiles"] is signup_profiles
    assert captured["active_signup_profile"] is active_signup_profile
    assert captured["current_url"] == "https://www.paypal.com/checkout"
    assert captured["otp_phone_lock_key"] == "otp-lock"
    assert captured["dismiss_phone_rejected_prompt"] is paypal_bind_executor._dismiss_paypal_phone_rejected_prompt
    assert captured["release_otp_phone_lock"] is paypal_bind_executor._release_paypal_otp_phone_lock
    assert captured["progress_event"] is paypal_bind_executor._progress_event
    assert captured["url_summary"] is paypal_bind_executor._safe_url_summary
    assert captured["on_progress"] is on_progress
    assert captured["sleep"] is paypal_bind_executor.time.sleep


def test_paypal_phone_rejected_rotation_values_wrapper_delegates(monkeypatch):
    captured = {}
    active_profile = {"phone": "111"}
    next_profile = {"phone": "222"}

    def fake_values(rotation_result, **kwargs):
        captured["rotation_result"] = rotation_result
        captured.update(kwargs)
        return ("", 1, next_profile, False, 0.0, True, 0)

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_phone_rejected_rotation_values",
        fake_values,
    )

    rotation_result = {"action": "continue"}
    assert paypal_bind_executor._paypal_phone_rejected_rotation_values(
        rotation_result,
        otp_phone_lock_key="otp-lock",
        signup_profile_index=0,
        active_signup_profile=active_profile,
        signup_form_submitted=True,
        signup_submitted_at=12.5,
        phone_only_retry=False,
        card_retry_count=3,
    ) == ("", 1, next_profile, False, 0.0, True, 0)
    assert captured["rotation_result"] is rotation_result
    assert captured["otp_phone_lock_key"] == "otp-lock"
    assert captured["signup_profile_index"] == 0
    assert captured["active_signup_profile"] is active_profile
    assert captured["signup_form_submitted"] is True
    assert captured["signup_submitted_at"] == 12.5
    assert captured["phone_only_retry"] is False
    assert captured["card_retry_count"] == 3


def test_handle_paypal_authorize_failed_classification_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    progress_events = []
    on_progress = progress_events.append
    classified = {"status": "failed", "failure_stage": "paypal_phone_rejected"}
    active_signup_profile = {"phone": "111"}
    signup_profiles = [active_signup_profile]

    def fake_handle(_api, **kwargs):
        captured["api"] = _api
        captured.update(kwargs)
        return {"action": "return_classified", "classified": classified}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_authorize_failed_classification",
        fake_handle,
    )

    api = object()
    assert paypal_bind_executor._handle_paypal_authorize_failed_classification(
        api,
        classified=classified,
        paypal_mode="create_account",
        active_signup_profile=active_signup_profile,
        signup_profile_index=0,
        signup_profiles=signup_profiles,
        current_url="https://www.paypal.com/checkout",
        otp_phone_lock_key="otp-lock",
        ddc_blocked_refresh_count=2,
        max_ddc_blocked_refreshes=3,
        on_progress=on_progress,
    ) == {"action": "return_classified", "classified": classified}
    assert captured["api"] is api
    assert captured["classified"] is classified
    assert captured["paypal_mode"] == "create_account"
    assert captured["active_signup_profile"] is active_signup_profile
    assert captured["signup_profile_index"] == 0
    assert captured["signup_profiles"] is signup_profiles
    assert captured["current_url"] == "https://www.paypal.com/checkout"
    assert captured["otp_phone_lock_key"] == "otp-lock"
    assert captured["ddc_blocked_refresh_count"] == 2
    assert captured["max_ddc_blocked_refreshes"] == 3
    assert captured["release_otp_phone_lock"] is paypal_bind_executor._release_paypal_otp_phone_lock
    assert captured["progress_event"] is paypal_bind_executor._progress_event
    assert captured["logger"] is paypal_bind_executor.logger
    assert captured["on_progress"] is on_progress
    assert captured["sleep"] is paypal_bind_executor.time.sleep


def test_paypal_authorize_classified_return_values_wrapper_delegates(monkeypatch):
    captured = {}
    fallback_classified = {"status": "failed"}
    returned_classified = {"status": "needs_review"}

    def fake_values(classification_result, fallback, **kwargs):
        captured["classification_result"] = classification_result
        captured["fallback"] = fallback
        captured.update(kwargs)
        return ("otp-lock", "custom-label", returned_classified)

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_authorize_classified_return_values",
        fake_values,
    )

    classification_result = {"action": "return_classified"}
    assert paypal_bind_executor._paypal_authorize_classified_return_values(
        classification_result,
        fallback_classified,
        default_screenshot_label="paypal-authorize-failed",
    ) == ("otp-lock", "custom-label", returned_classified)
    assert captured["classification_result"] is classification_result
    assert captured["fallback"] is fallback_classified
    assert captured["default_screenshot_label"] == "paypal-authorize-failed"


def test_paypal_authorize_classification_refresh_count_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_count(classification_result, **kwargs):
        captured["classification_result"] = classification_result
        captured.update(kwargs)
        return 3

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_authorize_classification_refresh_count",
        fake_count,
    )

    classification_result = {"action": "continue"}
    assert (
        paypal_bind_executor._paypal_authorize_classification_refresh_count(
            classification_result,
            ddc_blocked_refresh_count=2,
        )
        == 3
    )
    assert captured["classification_result"] is classification_result
    assert captured["ddc_blocked_refresh_count"] == 2


def test_paypal_authorize_datadome_failed_result_fields_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_fields(result, **kwargs):
        captured["result"] = result
        captured.update(kwargs)
        return ("otp-lock", "paypal_datadome_blocked", "blocked")

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_authorize_datadome_failed_result_fields",
        fake_fields,
    )

    result = {"failure_stage": "paypal_datadome_blocked"}
    assert paypal_bind_executor._paypal_authorize_datadome_failed_result_fields(
        result,
        default_message="fallback blocked",
    ) == ("otp-lock", "paypal_datadome_blocked", "blocked")
    assert captured["result"] is result
    assert captured["default_stage"] == "paypal_datadome_blocked"
    assert captured["default_message"] == "fallback blocked"


def test_handle_paypal_authorize_review_classification_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    progress_events = []
    on_progress = progress_events.append
    classified = {"status": "needs_review", "failure_stage": "paypal_human_verification"}

    def fake_handle(_api, **kwargs):
        captured["api"] = _api
        captured.update(kwargs)
        return {"action": "return_classified", "classified": classified}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_authorize_review_classification",
        fake_handle,
    )

    api = object()
    assert paypal_bind_executor._handle_paypal_authorize_review_classification(
        api,
        classified=classified,
        otp_phone_lock_key="otp-lock",
        ddc_blocked_refresh_count=2,
        max_ddc_blocked_refreshes=3,
        on_progress=on_progress,
    ) == {"action": "return_classified", "classified": classified}
    assert captured["api"] is api
    assert captured["classified"] is classified
    assert captured["otp_phone_lock_key"] == "otp-lock"
    assert captured["ddc_blocked_refresh_count"] == 2
    assert captured["max_ddc_blocked_refreshes"] == 3
    assert captured["is_ddc_blocked_page"] is paypal_bind_executor._is_ddc_blocked_page
    assert captured["release_otp_phone_lock"] is paypal_bind_executor._release_paypal_otp_phone_lock
    assert captured["progress_event"] is paypal_bind_executor._progress_event
    assert captured["logger"] is paypal_bind_executor.logger
    assert captured["on_progress"] is on_progress
    assert captured["sleep"] is paypal_bind_executor.time.sleep


def test_handle_paypal_authorize_ddc_blocked_page_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    def on_progress(event):
        return None

    def fake_handle(_api, **kwargs):
        captured["api"] = _api
        captured.update(kwargs)
        return {"action": "continue"}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_authorize_ddc_blocked_page",
        fake_handle,
    )

    api = object()
    assert paypal_bind_executor._handle_paypal_authorize_ddc_blocked_page(
        api,
        otp_phone_lock_key="otp-lock",
        ddc_blocked_refresh_count=1,
        max_ddc_blocked_refreshes=3,
        on_progress=on_progress,
    ) == {"action": "continue"}
    assert captured["api"] is api
    assert captured["otp_phone_lock_key"] == "otp-lock"
    assert captured["ddc_blocked_refresh_count"] == 1
    assert captured["max_ddc_blocked_refreshes"] == 3
    assert captured["is_ddc_blocked_page"] is paypal_bind_executor._is_ddc_blocked_page
    assert captured["release_otp_phone_lock"] is paypal_bind_executor._release_paypal_otp_phone_lock
    assert captured["progress_event"] is paypal_bind_executor._progress_event
    assert captured["logger"] is paypal_bind_executor.logger
    assert captured["on_progress"] is on_progress
    assert captured["sleep"] is paypal_bind_executor.time.sleep


def test_paypal_authorize_ddc_blocked_page_values_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_values(blocked_page_result, **kwargs):
        captured["blocked_page_result"] = blocked_page_result
        captured.update(kwargs)
        return ("", 3)

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_authorize_ddc_blocked_page_values",
        fake_values,
    )

    blocked_page_result = {"action": "continue"}
    assert paypal_bind_executor._paypal_authorize_ddc_blocked_page_values(
        blocked_page_result,
        otp_phone_lock_key="otp-lock",
        ddc_blocked_refresh_count=2,
    ) == ("", 3)
    assert captured["blocked_page_result"] is blocked_page_result
    assert captured["otp_phone_lock_key"] == "otp-lock"
    assert captured["ddc_blocked_refresh_count"] == 2


def test_handle_paypal_authorize_ddc_challenge_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    def on_progress(event):
        return None

    def fake_handle(_api, **kwargs):
        captured["api"] = _api
        captured.update(kwargs)
        return {"action": "passed"}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_authorize_ddc_challenge",
        fake_handle,
    )

    api = object()
    assert paypal_bind_executor._handle_paypal_authorize_ddc_challenge(
        api,
        otp_phone_lock_key="otp-lock",
        last_ddc_check_at=12.0,
        ddc_iframe_check_interval=15.0,
        ddc_pass_timeout_seconds=50,
        on_progress=on_progress,
    ) == {"action": "passed"}
    assert captured["api"] is api
    assert captured["otp_phone_lock_key"] == "otp-lock"
    assert captured["last_ddc_check_at"] == 12.0
    assert captured["ddc_iframe_check_interval"] == 15.0
    assert captured["ddc_pass_timeout_seconds"] == 50
    assert captured["ddc_slider_visible"] is paypal_bind_executor._ddc_slider_visible
    assert captured["has_ddc_iframe"] is paypal_bind_executor._has_ddc_iframe
    assert captured["wait_ddc_pass"] is paypal_bind_executor._wait_ddc_pass
    assert captured["release_otp_phone_lock"] is paypal_bind_executor._release_paypal_otp_phone_lock
    assert captured["on_progress"] is on_progress
    assert captured["now"] is paypal_bind_executor.time.time


def test_paypal_authorize_ddc_challenge_values_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_values(ddc_challenge_result, **kwargs):
        captured["ddc_challenge_result"] = ddc_challenge_result
        captured.update(kwargs)
        return ("", 0.0)

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_authorize_ddc_challenge_values",
        fake_values,
    )

    ddc_challenge_result = {"action": "failed"}
    assert paypal_bind_executor._paypal_authorize_ddc_challenge_values(
        ddc_challenge_result,
        otp_phone_lock_key="otp-lock",
        last_ddc_check_at=12.5,
    ) == ("", 0.0)
    assert captured["ddc_challenge_result"] is ddc_challenge_result
    assert captured["otp_phone_lock_key"] == "otp-lock"
    assert captured["last_ddc_check_at"] == 12.5


def test_handle_paypal_result_datadome_check_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    def on_progress(event):
        return None

    def fake_handle(_api, **kwargs):
        captured["api"] = _api
        captured.update(kwargs)
        return {"action": "checked"}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_result_datadome_check",
        fake_handle,
    )

    api = object()
    assert paypal_bind_executor._handle_paypal_result_datadome_check(
        api,
        last_ddc_check_at=12.0,
        ddc_iframe_check_interval=15.0,
        ddc_pass_timeout_seconds=50,
        on_progress=on_progress,
    ) == {"action": "checked"}
    assert captured["api"] is api
    assert captured["last_ddc_check_at"] == 12.0
    assert captured["ddc_iframe_check_interval"] == 15.0
    assert captured["ddc_pass_timeout_seconds"] == 50
    assert captured["is_ddc_blocked_page"] is paypal_bind_executor._is_ddc_blocked_page
    assert captured["ddc_slider_visible"] is paypal_bind_executor._ddc_slider_visible
    assert captured["has_ddc_iframe"] is paypal_bind_executor._has_ddc_iframe
    assert captured["wait_ddc_pass"] is paypal_bind_executor._wait_ddc_pass
    assert captured["logger"] is paypal_bind_executor.logger
    assert captured["on_progress"] is on_progress
    assert captured["now"] is paypal_bind_executor.time.time
    assert captured["sleep"] is paypal_bind_executor.time.sleep


def test_paypal_result_datadome_values_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_values(datadome_result, **kwargs):
        captured["datadome_result"] = datadome_result
        captured.update(kwargs)
        return 0.0

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_result_datadome_values",
        fake_values,
    )

    datadome_result = {"action": "checked"}
    assert (
        paypal_bind_executor._paypal_result_datadome_values(
            datadome_result,
            last_ddc_check_at=12.5,
        )
        == 0.0
    )
    assert captured["datadome_result"] is datadome_result
    assert captured["last_ddc_check_at"] == 12.5


def test_should_continue_after_paypal_result_datadome_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_should_continue(datadome_result):
        captured["datadome_result"] = datadome_result
        return True

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "should_continue_after_paypal_result_datadome",
        fake_should_continue,
    )

    datadome_result = {"action": "continue"}
    assert paypal_bind_executor._should_continue_after_paypal_result_datadome(datadome_result)
    assert captured["datadome_result"] is datadome_result


def test_paypal_result_datadome_transition_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_transition(datadome_result, **kwargs):
        captured["datadome_result"] = datadome_result
        captured.update(kwargs)
        return 20.0, True

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_result_datadome_transition",
        fake_transition,
    )

    datadome_result = {"action": "continue"}
    assert paypal_bind_executor._paypal_result_datadome_transition(
        datadome_result,
        last_ddc_check_at=10.0,
    ) == (20.0, True)
    assert captured["datadome_result"] is datadome_result
    assert captured["last_ddc_check_at"] == 10.0


def test_should_check_paypal_result_datadome_wrapper_passes_dependency(monkeypatch):
    captured = {}

    def fake_should_check(current_url, **kwargs):
        captured["current_url"] = current_url
        captured.update(kwargs)
        return True

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "should_check_paypal_result_datadome",
        fake_should_check,
    )

    assert paypal_bind_executor._should_check_paypal_result_datadome("https://www.paypal.com/checkoutnow")
    assert captured["current_url"] == "https://www.paypal.com/checkoutnow"
    assert captured["is_paypal_host"] is paypal_bind_executor._is_paypal_host


def test_paypal_result_browser_classification_wrapper_passes_classifier(monkeypatch):
    captured = {}
    classified = {"status": "success"}

    def fake_browser_classification(current_url, body_text, **kwargs):
        captured["current_url"] = current_url
        captured["body_text"] = body_text
        captured.update(kwargs)
        return classified

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_result_browser_classification",
        fake_browser_classification,
    )

    assert (
        paypal_bind_executor._paypal_result_browser_classification(
            "https://www.paypal.com/checkoutnow",
            "body",
        )
        is classified
    )
    assert captured["current_url"] == "https://www.paypal.com/checkoutnow"
    assert captured["body_text"] == "body"
    assert captured["classify_checkout_state"] is paypal_bind_executor.classify_paypal_checkout_state


def test_paypal_result_browser_classified_values_wrapper_passes_classifier(monkeypatch):
    captured = {}
    returned = ("success", {"status": "success"})

    def fake_browser_values(current_url, body_text, **kwargs):
        captured["current_url"] = current_url
        captured["body_text"] = body_text
        captured.update(kwargs)
        return returned

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_result_browser_classified_values",
        fake_browser_values,
    )

    assert (
        paypal_bind_executor._paypal_result_browser_classified_values(
            "https://www.paypal.com/checkoutnow",
            "body",
        )
        is returned
    )
    assert captured["current_url"] == "https://www.paypal.com/checkoutnow"
    assert captured["body_text"] == "body"
    assert captured["classify_checkout_state"] is paypal_bind_executor.classify_paypal_checkout_state


def test_paypal_result_classified_return_values_wrapper_delegates(monkeypatch):
    captured = {}
    returned = {"status": "success"}

    def fake_values(classified_result):
        captured["classified_result"] = classified_result
        return ("success", returned)

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_result_classified_return_values",
        fake_values,
    )

    classified_result = {"status": "success"}
    assert paypal_bind_executor._paypal_result_classified_return_values(classified_result) == ("success", returned)
    assert captured["classified_result"] is classified_result


def test_attach_paypal_result_screenshot_paths_wrapper_delegates(monkeypatch):
    captured = {}
    returned = {"status": "failed"}

    def fake_attach(classified_result, screenshot_paths):
        captured["classified_result"] = classified_result
        captured["screenshot_paths"] = screenshot_paths
        return returned

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "attach_paypal_result_screenshot_paths",
        fake_attach,
    )

    classified_result = {"status": "failed"}
    screenshot_paths = ["paypal-failed.png"]
    assert paypal_bind_executor._attach_paypal_result_screenshot_paths(classified_result, screenshot_paths) is returned
    assert captured["classified_result"] is classified_result
    assert captured["screenshot_paths"] is screenshot_paths


def test_capture_and_attach_paypal_result_screenshot_paths_captures_then_attaches(monkeypatch):
    calls = []
    api = object()
    classified_result = {"status": "success"}
    screenshot_paths = ["existing.png"]
    attached = {"status": "success", "screenshot_paths": screenshot_paths}

    def fake_capture(received_api, session_id, screenshot_label, received_paths):
        calls.append(("capture", received_api, session_id, screenshot_label, received_paths))

    def fake_attach(received_result, received_paths):
        calls.append(("attach", received_result, received_paths))
        return attached

    monkeypatch.setattr(paypal_bind_executor, "_capture_screenshot", fake_capture)
    monkeypatch.setattr(paypal_bind_executor, "_attach_paypal_result_screenshot_paths", fake_attach)

    assert (
        paypal_bind_executor._capture_and_attach_paypal_result_screenshot_paths(
            api,
            session_id="session-123",
            screenshot_label="success",
            classified_result=classified_result,
            screenshot_paths=screenshot_paths,
        )
        is attached
    )
    assert calls == [
        ("capture", api, "session-123", "success", screenshot_paths),
        ("attach", classified_result, screenshot_paths),
    ]


def test_paypal_result_cancelled_result_fields_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_fields(result=None):
        captured["result"] = result
        return ("failed", "paypal-cancelled", "post_submit", "cancelled")

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_result_cancelled_result_fields",
        fake_fields,
    )

    result = {"message": "cancelled"}
    assert paypal_bind_executor._paypal_result_cancelled_result_fields(result) == (
        "failed",
        "paypal-cancelled",
        "post_submit",
        "cancelled",
    )
    assert captured["result"] is result


def test_paypal_result_timeout_result_fields_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_fields(result=None):
        captured["result"] = result
        return ("needs_review", "paypal-timeout", "post_submit", "timeout")

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_result_timeout_result_fields",
        fake_fields,
    )

    result = {"message": "timeout"}
    assert paypal_bind_executor._paypal_result_timeout_result_fields(result) == (
        "needs_review",
        "paypal-timeout",
        "post_submit",
        "timeout",
    )
    assert captured["result"] is result


def test_paypal_result_wait_deadline_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_deadline(**kwargs):
        captured.update(kwargs)
        return 130.0

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_result_wait_deadline",
        fake_deadline,
    )

    assert paypal_bind_executor._paypal_result_wait_deadline(now=100.0, timeout_seconds=30) == 130.0
    assert captured == {"now": 100.0, "timeout_seconds": 30}


def test_should_continue_paypal_result_wait_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_should_continue(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "should_continue_paypal_result_wait",
        fake_should_continue,
    )

    assert paypal_bind_executor._should_continue_paypal_result_wait(now=109.0, deadline=110.0)
    assert captured == {"now": 109.0, "deadline": 110.0}


def test_should_cancel_paypal_result_wait_wrapper_delegates(monkeypatch):
    captured = {}

    def cancel_callback():
        return True

    def fake_should_cancel(is_cancelled):
        captured["is_cancelled"] = is_cancelled
        return True

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "should_cancel_paypal_result_wait",
        fake_should_cancel,
    )

    assert paypal_bind_executor._should_cancel_paypal_result_wait(cancel_callback)
    assert captured["is_cancelled"] is cancel_callback


def test_paypal_result_wait_initial_state_wrapper_delegates(monkeypatch):
    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_result_wait_initial_state",
        lambda: ("stage", 1.0, 2.0, 3.0),
    )

    assert paypal_bind_executor._paypal_result_wait_initial_state() == ("stage", 1.0, 2.0, 3.0)


def test_paypal_result_wait_sleep_seconds_wrapper_delegates(monkeypatch):
    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_result_wait_sleep_seconds",
        lambda: 4.0,
    )

    assert paypal_bind_executor._paypal_result_wait_sleep_seconds() == 4.0


def test_paypal_result_autofilled_url_keys_wrapper_delegates(monkeypatch):
    autofilled_url_keys = {"checkout-key"}
    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_result_autofilled_url_keys",
        lambda: autofilled_url_keys,
    )

    assert paypal_bind_executor._paypal_result_autofilled_url_keys() is autofilled_url_keys


def test_paypal_result_stripe_state_http_session_wrapper_passes_dependency(monkeypatch):
    captured = {}
    http_session = object()

    def fake_session(proxy_url, **kwargs):
        captured["proxy_url"] = proxy_url
        captured.update(kwargs)
        return http_session

    def fake_stripe_state_http_session(proxy_url, **kwargs):
        captured["service_proxy_url"] = proxy_url
        captured.update(kwargs)
        return kwargs["new_http_session"](proxy_url, require_curl_cffi=False)

    monkeypatch.setattr(paypal_bind_executor, "_new_http_session", fake_session)
    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_result_stripe_state_http_session",
        fake_stripe_state_http_session,
    )

    assert paypal_bind_executor._paypal_result_stripe_state_http_session("http://proxy.example:8080") is http_session
    assert captured["service_proxy_url"] == "http://proxy.example:8080"
    assert captured["new_http_session"] is fake_session
    assert captured["proxy_url"] == "http://proxy.example:8080"
    assert captured["require_curl_cffi"] is False


def test_paypal_result_page_snapshot_wrapper_passes_body_excerpt_dependency(monkeypatch):
    captured = {}
    api = object()

    def fake_page_snapshot(received_api, **kwargs):
        captured["api"] = received_api
        captured.update(kwargs)
        return "body", "https://www.paypal.com/checkoutnow"

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_result_page_snapshot",
        fake_page_snapshot,
    )

    assert paypal_bind_executor._paypal_result_page_snapshot(api) == (
        "body",
        "https://www.paypal.com/checkoutnow",
    )
    assert captured["api"] is api
    assert captured["body_excerpt"] is paypal_bind_executor._body_excerpt


def test_paypal_result_sync_prefer_paypal_wrapper_delegates(monkeypatch):
    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_result_sync_prefer_paypal",
        lambda: True,
    )

    assert paypal_bind_executor._paypal_result_sync_prefer_paypal() is True


def test_paypal_result_autofill_url_key_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_key(url):
        captured["url"] = url
        return "key"

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_result_autofill_url_key",
        fake_key,
    )

    assert paypal_bind_executor._paypal_result_autofill_url_key("https://checkout.openai.com/pay/cs_123?a=1") == "key"
    assert captured["url"] == "https://checkout.openai.com/pay/cs_123?a=1"


def test_should_autofill_paypal_result_checkout_wrapper_passes_dependencies(monkeypatch):
    captured = {}

    def fake_should_autofill(current_url, autofill_payload, **kwargs):
        captured["current_url"] = current_url
        captured["autofill_payload"] = autofill_payload
        captured.update(kwargs)
        return True

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "should_autofill_paypal_result_checkout",
        fake_should_autofill,
    )

    payload = {"name": "James Smith"}
    assert paypal_bind_executor._should_autofill_paypal_result_checkout(
        "https://checkout.openai.com/pay/cs_123",
        payload,
    )
    assert captured["current_url"] == "https://checkout.openai.com/pay/cs_123"
    assert captured["autofill_payload"] is payload
    assert captured["autofill_enabled"] is True
    assert captured["is_checkout_host"] is paypal_bind_executor._is_checkout_host
    assert captured["autofill_allowed"] is paypal_bind_executor._autofill_allowed


def test_should_run_paypal_result_autofill_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_should_run(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "should_run_paypal_result_autofill",
        fake_should_run,
    )

    autofilled_url_keys = {"existing-key"}
    assert paypal_bind_executor._should_run_paypal_result_autofill(
        should_autofill_checkout=True,
        autofill_key="checkout-key",
        autofilled_url_keys=autofilled_url_keys,
    )
    assert captured == {
        "should_autofill_checkout": True,
        "autofill_key": "checkout-key",
        "autofilled_url_keys": autofilled_url_keys,
    }


def test_paypal_result_autofill_transition_wrapper_passes_dependencies(monkeypatch):
    captured = {}

    def fake_transition(current_url, autofill_payload, **kwargs):
        captured["current_url"] = current_url
        captured["autofill_payload"] = autofill_payload
        captured.update(kwargs)
        return True, "checkout-key"

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_result_autofill_transition",
        fake_transition,
    )

    payload = {"name": "James Smith"}
    autofilled_url_keys = {"existing-key"}
    assert paypal_bind_executor._paypal_result_autofill_transition(
        "https://checkout.openai.com/pay/cs_123",
        payload,
        autofilled_url_keys=autofilled_url_keys,
        autofill_enabled=False,
    ) == (True, "checkout-key")
    assert captured["current_url"] == "https://checkout.openai.com/pay/cs_123"
    assert captured["autofill_payload"] is payload
    assert captured["autofilled_url_keys"] is autofilled_url_keys
    assert captured["autofill_enabled"] is False
    assert captured["is_checkout_host"] is paypal_bind_executor._is_checkout_host
    assert captured["autofill_allowed"] is paypal_bind_executor._autofill_allowed


def test_record_paypal_result_autofill_key_wrapper_delegates(monkeypatch):
    captured = {}
    returned = {"checkout-key"}

    def fake_record(autofilled_url_keys, autofill_key):
        captured["autofilled_url_keys"] = autofilled_url_keys
        captured["autofill_key"] = autofill_key
        return returned

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "record_paypal_result_autofill_key",
        fake_record,
    )

    autofilled_url_keys = {"existing-key"}
    assert paypal_bind_executor._record_paypal_result_autofill_key(autofilled_url_keys, "checkout-key") is returned
    assert captured["autofilled_url_keys"] is autofilled_url_keys
    assert captured["autofill_key"] == "checkout-key"


def test_paypal_result_stripe_progress_event_fields_wrapper_delegates(monkeypatch):
    captured = {}
    returned = ("stage", "message", {"url": "current"})

    def fake_fields(stripe_classified, **kwargs):
        captured["stripe_classified"] = stripe_classified
        captured.update(kwargs)
        return returned

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_result_stripe_progress_event_fields",
        fake_fields,
    )

    stripe_classified = {"status": "success"}
    assert (
        paypal_bind_executor._paypal_result_stripe_progress_event_fields(
            stripe_classified,
            checkout_url="checkout",
            current_url="current",
        )
        is returned
    )
    assert captured["stripe_classified"] is stripe_classified
    assert captured["checkout_url"] == "checkout"
    assert captured["current_url"] == "current"


def test_paypal_result_stripe_classified_values_wrapper_delegates(monkeypatch):
    captured = {}
    returned = ("stage", "message", {"url": "current"}, "success", {"status": "success"})

    def fake_values(stripe_classified, **kwargs):
        captured["stripe_classified"] = stripe_classified
        captured.update(kwargs)
        return returned

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_result_stripe_classified_values",
        fake_values,
    )

    stripe_classified = {"status": "success"}
    assert (
        paypal_bind_executor._paypal_result_stripe_classified_values(
            stripe_classified,
            checkout_url="checkout",
            current_url="current",
        )
        is returned
    )
    assert captured["stripe_classified"] is stripe_classified
    assert captured["checkout_url"] == "checkout"
    assert captured["current_url"] == "current"


def test_should_poll_paypal_result_stripe_state_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_should_poll(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "should_poll_paypal_result_stripe_state",
        fake_should_poll,
    )

    assert paypal_bind_executor._should_poll_paypal_result_stripe_state(
        checkout_url="checkout",
        now=10.0,
        last_poll_at=4.0,
    )
    assert captured == {
        "checkout_url": "checkout",
        "now": 10.0,
        "last_poll_at": 4.0,
        "poll_interval_seconds": paypal_bind_executor.PAYPAL_STRIPE_STATE_POLL_INTERVAL_SECONDS,
    }


def test_paypal_result_stripe_poll_transition_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_transition(**kwargs):
        captured.update(kwargs)
        return True, 10.0

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_result_stripe_poll_transition",
        fake_transition,
    )

    assert paypal_bind_executor._paypal_result_stripe_poll_transition(
        checkout_url="checkout",
        now=10.0,
        last_poll_at=4.0,
    ) == (True, 10.0)
    assert captured == {
        "checkout_url": "checkout",
        "now": 10.0,
        "last_poll_at": 4.0,
        "poll_interval_seconds": paypal_bind_executor.PAYPAL_STRIPE_STATE_POLL_INTERVAL_SECONDS,
    }


def test_should_emit_paypal_result_stage_progress_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_should_emit(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "should_emit_paypal_result_stage_progress",
        fake_should_emit,
    )

    assert paypal_bind_executor._should_emit_paypal_result_stage_progress(
        stage="paypal_pending",
        last_stage="",
    )
    assert captured == {"stage": "paypal_pending", "last_stage": ""}


def test_paypal_result_stage_values_wrapper_passes_inferer(monkeypatch):
    captured = {}

    def fake_stage_values(current_url, body_text, **kwargs):
        captured["current_url"] = current_url
        captured["body_text"] = body_text
        captured.update(kwargs)
        return "paypal_pending", "waiting"

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_result_stage_values",
        fake_stage_values,
    )

    assert paypal_bind_executor._paypal_result_stage_values(
        "https://www.paypal.com/checkoutnow",
        "body",
    ) == ("paypal_pending", "waiting")
    assert captured["current_url"] == "https://www.paypal.com/checkoutnow"
    assert captured["body_text"] == "body"
    assert captured["infer_stage"] is paypal_bind_executor.infer_paypal_stage


def test_paypal_result_stage_progress_transition_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_transition(**kwargs):
        captured.update(kwargs)
        return True, "paypal_pending"

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_result_stage_progress_transition",
        fake_transition,
    )

    assert paypal_bind_executor._paypal_result_stage_progress_transition(
        stage="paypal_pending",
        last_stage="",
    ) == (True, "paypal_pending")
    assert captured == {"stage": "paypal_pending", "last_stage": ""}


def test_paypal_result_stage_progress_event_fields_wrapper_delegates(monkeypatch):
    captured = {}
    returned = ("stage", "message", {"url": "current"})

    def fake_fields(**kwargs):
        captured.update(kwargs)
        return returned

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_result_stage_progress_event_fields",
        fake_fields,
    )

    assert (
        paypal_bind_executor._paypal_result_stage_progress_event_fields(
            stage="paypal_pending",
            message="waiting",
            current_url="current",
        )
        is returned
    )
    assert captured == {
        "stage": "paypal_pending",
        "message": "waiting",
        "current_url": "current",
    }


def test_should_log_paypal_result_wait_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_should_log(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "should_log_paypal_result_wait",
        fake_should_log,
    )

    assert paypal_bind_executor._should_log_paypal_result_wait(now=70.0, last_log_at=10.0)
    assert captured == {
        "now": 70.0,
        "last_log_at": 10.0,
        "log_interval_seconds": 60.0,
    }


def test_paypal_result_wait_log_transition_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_transition(**kwargs):
        captured.update(kwargs)
        return True, 70.0

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_result_wait_log_transition",
        fake_transition,
    )

    assert paypal_bind_executor._paypal_result_wait_log_transition(now=70.0, last_log_at=10.0) == (True, 70.0)
    assert captured == {
        "now": 70.0,
        "last_log_at": 10.0,
        "log_interval_seconds": 60.0,
    }


def test_paypal_result_wait_log_values_wrapper_delegates(monkeypatch):
    captured = {}
    returned = (12, "current")

    def fake_values(**kwargs):
        captured.update(kwargs)
        return returned

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_result_wait_log_values",
        fake_values,
    )

    assert (
        paypal_bind_executor._paypal_result_wait_log_values(
            deadline=100.0,
            now=88.0,
            current_url="current",
        )
        is returned
    )
    assert captured == {
        "deadline": 100.0,
        "now": 88.0,
        "current_url": "current",
    }


def test_handle_paypal_browser_fallback_ddc_wait_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    def on_progress(event):
        return None

    def fake_handle(page, **kwargs):
        captured["page"] = page
        captured.update(kwargs)
        return {"action": "continue"}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_browser_fallback_ddc_wait",
        fake_handle,
    )

    page = object()
    assert paypal_bind_executor._handle_paypal_browser_fallback_ddc_wait(
        page,
        timeout_seconds=50,
        on_progress=on_progress,
    ) == {"action": "continue"}
    assert captured["page"] is page
    assert captured["wait_ddc_pass"] is paypal_bind_executor._wait_ddc_pass
    assert captured["timeout_seconds"] == 50
    assert captured["on_progress"] is on_progress


def test_handle_paypal_protocol_browser_fallback_context_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    def on_progress(event):
        return None
    protocol_result = {"paypal_approve_url": "https://www.paypal.com/agreements/approve?ba_token=BA-DEMO"}

    def fake_handle(result, **kwargs):
        captured["protocol_result"] = result
        captured.update(kwargs)
        return {"action": "fallback"}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_protocol_browser_fallback_context",
        fake_handle,
    )

    assert paypal_bind_executor._handle_paypal_protocol_browser_fallback_context(
        protocol_result,
        paypal_mode="create_account",
        paypal_country="JP",
        paypal_lang="ja",
        on_progress=on_progress,
    ) == {"action": "fallback"}
    assert captured["protocol_result"] is protocol_result
    assert captured["paypal_mode"] == "create_account"
    assert captured["paypal_country"] == "JP"
    assert captured["paypal_lang"] == "ja"
    assert captured["extract_ba_token"] is paypal_bind_executor._paypal_protocol_extract_ba_token
    assert captured["create_account_entry_url"] is paypal_bind_executor._paypal_create_account_entry_url
    assert captured["safe_url_summary"] is paypal_bind_executor._safe_url_summary
    assert captured["progress_event"] is paypal_bind_executor._progress_event
    assert captured["on_progress"] is on_progress


def test_preserve_paypal_roxybrowser_on_failure_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    api = object()
    result = {"status": "failed"}

    def fake_preserve(_api, _result, **kwargs):
        captured["api"] = _api
        captured["result"] = _result
        captured.update(kwargs)
        return _result

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "preserve_paypal_roxybrowser_on_failure",
        fake_preserve,
    )

    assert (
        paypal_bind_executor._preserve_paypal_roxybrowser_on_failure(
            api,
            result,
            fallback_use_roxybrowser=True,
        )
        is result
    )
    assert captured["api"] is api
    assert captured["result"] is result
    assert captured["fallback_use_roxybrowser"] is True
    assert captured["keepalive_seconds"] == paypal_bind_executor.PAYPAL_ROXYBROWSER_FAILURE_KEEPALIVE_SECONDS


def test_handle_paypal_pre_extracted_checkout_without_ba_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    def on_progress(event):
        return None
    pre_extracted = {"checkout_url": "https://pay.openai.com/c/pay/cs_demo"}

    def fake_handle(value, **kwargs):
        captured["pre_extracted"] = value
        captured.update(kwargs)
        return {"action": "failed"}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_pre_extracted_checkout_without_ba",
        fake_handle,
    )

    assert paypal_bind_executor._handle_paypal_pre_extracted_checkout_without_ba(
        pre_extracted,
        on_progress=on_progress,
    ) == {"action": "failed"}
    assert captured["pre_extracted"] is pre_extracted
    assert captured["safe_url_summary"] is paypal_bind_executor._safe_url_summary
    assert captured["progress_event"] is paypal_bind_executor._progress_event
    assert captured["on_progress"] is on_progress


def test_handle_paypal_proxy_open_checkout_failure_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    def on_progress(event):
        return None
    prepare_result = {"failure_stage": "open_checkout"}

    def fake_handle(value, **kwargs):
        captured["prepare_result"] = value
        captured.update(kwargs)
        return {"action": "failed"}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_proxy_open_checkout_failure",
        fake_handle,
    )

    assert paypal_bind_executor._handle_paypal_proxy_open_checkout_failure(
        prepare_result,
        proxy_url="socks5://proxy.example:1080",
        on_progress=on_progress,
    ) == {"action": "failed"}
    assert captured["prepare_result"] is prepare_result
    assert captured["proxy_url"] == "socks5://proxy.example:1080"
    assert captured["is_tunnel_connection_error"] is paypal_bind_executor._is_tunnel_connection_error
    assert captured["safe_url_summary"] is paypal_bind_executor._safe_url_summary
    assert captured["progress_event"] is paypal_bind_executor._progress_event
    assert captured["logger"] is paypal_bind_executor.logger
    assert captured["on_progress"] is on_progress


def test_handle_paypal_manual_pre_wait_autofill_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    def on_progress(event):
        return None

    def fake_handle(_api, **kwargs):
        captured["api"] = _api
        captured.update(kwargs)
        return {"action": "autofilled"}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_manual_pre_wait_autofill",
        fake_handle,
    )

    api = object()
    payload = {"name": "Taro Yamada"}
    assert paypal_bind_executor._handle_paypal_manual_pre_wait_autofill(
        api,
        autofill_payload=payload,
        autofill_enabled=False,
        on_progress=on_progress,
    ) == {"action": "autofilled"}
    assert captured["api"] is api
    assert captured["autofill_payload"] is payload
    assert captured["autofill_enabled"] is False
    assert captured["autofill_checkout_fields"] is paypal_bind_executor.autofill_checkout_fields
    assert captured["on_progress"] is on_progress


def test_handle_paypal_open_checkout_cancelled_wrapper_delegates(monkeypatch):
    captured = {}
    def is_cancelled():
        return True

    def fake_handle(**kwargs):
        captured.update(kwargs)
        return {"action": "failed"}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_open_checkout_cancelled",
        fake_handle,
    )

    assert paypal_bind_executor._handle_paypal_open_checkout_cancelled(is_cancelled=is_cancelled) == {
        "action": "failed"
    }
    assert captured["is_cancelled"] is is_cancelled


def test_launch_paypal_checkout_browser_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    def on_progress(event):
        return None

    class FakeApi:
        def _launch_browser(self, **kwargs):
            captured["direct_launch"] = kwargs

    def fake_launch(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "launch_paypal_checkout_browser",
        fake_launch,
    )

    api = FakeApi()
    paypal_bind_executor._launch_paypal_checkout_browser(
        api,
        proxy_url="socks5://proxy.example:1080",
        proxy_bypass="localhost",
        use_fallback_browser=True,
        paypal_country="JP",
        paypal_lang="ja",
        use_camoufox=False,
        use_roxybrowser=False,
        fallback_use_camoufox=False,
        fallback_use_roxybrowser=True,
        roxybrowser_workspace_id="workspace-1",
        roxybrowser_profile_id="profile-1",
        on_progress=on_progress,
    )

    assert captured["proxy_url"] == "socks5://proxy.example:1080"
    assert captured["proxy_bypass"] == "localhost"
    assert captured["use_fallback_browser"] is True
    assert captured["paypal_country"] == "JP"
    assert captured["paypal_lang"] == "ja"
    assert captured["use_camoufox"] is False
    assert captured["use_roxybrowser"] is False
    assert captured["fallback_use_camoufox"] is False
    assert captured["fallback_use_roxybrowser"] is True
    assert captured["roxybrowser_workspace_id"] == "workspace-1"
    assert captured["roxybrowser_profile_id"] == "profile-1"
    assert captured["launch_browser"].__self__ is api
    assert captured["launch_browser"].__func__ is FakeApi._launch_browser
    assert captured["on_progress"] is on_progress


def test_handle_paypal_checkout_context_dispatch_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    def on_progress(event):
        return None
    screenshot_paths = []
    def is_cancelled():
        return False

    def fake_handle(_api, **kwargs):
        captured["api"] = _api
        captured.update(kwargs)
        return {"status": "success"}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_checkout_context_dispatch",
        fake_handle,
    )

    api = object()
    assert paypal_bind_executor._handle_paypal_checkout_context_dispatch(
        api,
        email=" user@example.com ",
        checkout_url="https://pay.openai.com/c/pay/cs_demo",
        proxy_url="socks5://proxy.example:1080",
        session_id="session-1",
        screenshot_paths=screenshot_paths,
        is_cancelled=is_cancelled,
        on_progress=on_progress,
    ) == {"status": "success"}
    assert captured["api"] is api
    assert captured["email"] == " user@example.com "
    assert captured["checkout_url"] == "https://pay.openai.com/c/pay/cs_demo"
    assert captured["proxy_url"] == "socks5://proxy.example:1080"
    assert captured["session_id"] == "session-1"
    assert captured["screenshot_paths"] is screenshot_paths
    assert captured["is_cancelled"] is is_cancelled
    assert captured["handle_open_checkout_cancelled"] is paypal_bind_executor._handle_paypal_open_checkout_cancelled
    assert captured["build_result"] is paypal_bind_executor._build_result
    assert captured["prepare_chatgpt_checkout_context"] is paypal_bind_executor._prepare_chatgpt_checkout_context
    assert captured["extract_auth_session_context"] is paypal_bind_executor._extract_auth_session_context
    assert (
        captured["handle_proxy_open_checkout_failure"]
        is paypal_bind_executor._handle_paypal_proxy_open_checkout_failure
    )
    assert captured["on_progress"] is on_progress


def test_handle_paypal_manual_result_wait_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    def on_progress(event):
        return None
    screenshot_paths = []
    def is_cancelled():
        return False
    payload = {"name": "Taro Yamada"}

    def fake_handle(_api, **kwargs):
        captured["api"] = _api
        captured.update(kwargs)
        return {"status": "success"}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_manual_result_wait",
        fake_handle,
    )

    api = object()
    assert paypal_bind_executor._handle_paypal_manual_result_wait(
        api,
        checkout_url="https://pay.openai.com/c/pay/cs_demo",
        proxy_url="socks5://proxy.example:1080",
        session_id="session-1",
        screenshot_paths=screenshot_paths,
        timeout_seconds=120,
        is_cancelled=is_cancelled,
        autofill_enabled=True,
        autofill_payload=payload,
        on_progress=on_progress,
    ) == {"status": "success"}
    assert captured["api"] is api
    assert captured["checkout_url"] == "https://pay.openai.com/c/pay/cs_demo"
    assert captured["proxy_url"] == "socks5://proxy.example:1080"
    assert captured["session_id"] == "session-1"
    assert captured["screenshot_paths"] is screenshot_paths
    assert captured["timeout_seconds"] == 120
    assert captured["is_cancelled"] is is_cancelled
    assert captured["autofill_enabled"] is True
    assert captured["autofill_payload"] is payload
    assert captured["manual_pre_wait_autofill"] is paypal_bind_executor._handle_paypal_manual_pre_wait_autofill
    assert captured["wait_for_paypal_result"] is paypal_bind_executor._wait_for_paypal_result
    assert captured["on_progress"] is on_progress


def test_handle_paypal_post_checkout_flow_dispatch_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    def on_progress(event):
        return None
    screenshot_paths = []
    phone_accounts = [{"phone": "+819012345678"}]
    payload = {"name": "Taro Yamada"}
    def is_cancelled():
        return False

    def fake_handle(_api, **kwargs):
        captured["api"] = _api
        captured.update(kwargs)
        return {"status": "success"}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_post_checkout_flow_dispatch",
        fake_handle,
    )

    api = object()
    assert paypal_bind_executor._handle_paypal_post_checkout_flow_dispatch(
        api,
        auto_mode=True,
        email=" user@example.com ",
        checkout_url="https://pay.openai.com/c/pay/cs_demo",
        proxy_url="socks5://proxy.example:1080",
        paypal_mode="create_account",
        paypal_country="JP",
        paypal_lang="ja",
        paypal_email="paypal@example.com",
        paypal_password="secret",
        sms_url="https://sms.example.test",
        otp_channel="sms",
        paypal_card_number="4111111111111111",
        paypal_card_expiry="03/30",
        paypal_card_cvv="123",
        phone_accounts=phone_accounts,
        session_id="session-1",
        screenshot_paths=screenshot_paths,
        timeout_seconds=120,
        is_cancelled=is_cancelled,
        autofill_enabled=True,
        autofill_payload=payload,
        on_progress=on_progress,
    ) == {"status": "success"}
    assert captured["api"] is api
    assert captured["auto_mode"] is True
    assert captured["email"] == " user@example.com "
    assert captured["checkout_url"] == "https://pay.openai.com/c/pay/cs_demo"
    assert captured["proxy_url"] == "socks5://proxy.example:1080"
    assert captured["paypal_mode"] == "create_account"
    assert captured["paypal_country"] == "JP"
    assert captured["paypal_lang"] == "ja"
    assert captured["paypal_email"] == "paypal@example.com"
    assert captured["paypal_password"] == "secret"
    assert captured["sms_url"] == "https://sms.example.test"
    assert captured["otp_channel"] == "sms"
    assert captured["paypal_card_number"] == "4111111111111111"
    assert captured["paypal_card_expiry"] == "03/30"
    assert captured["paypal_card_cvv"] == "123"
    assert captured["phone_accounts"] is phone_accounts
    assert captured["session_id"] == "session-1"
    assert captured["screenshot_paths"] is screenshot_paths
    assert captured["timeout_seconds"] == 120
    assert captured["is_cancelled"] is is_cancelled
    assert captured["autofill_enabled"] is True
    assert captured["autofill_payload"] is payload
    assert captured["handle_auto_flow_dispatch"] is paypal_bind_executor._handle_paypal_auto_flow_dispatch
    assert captured["handle_manual_result_wait"] is paypal_bind_executor._handle_paypal_manual_result_wait
    assert captured["paypal_result_timeout_seconds"] is paypal_bind_executor._paypal_result_timeout_seconds
    assert captured["on_progress"] is on_progress


def test_handle_paypal_unexpected_error_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    screenshot_paths = []
    exc = RuntimeError("boom")

    def fake_handle(_api, _exc, **kwargs):
        captured["api"] = _api
        captured["exc"] = _exc
        captured.update(kwargs)
        return {"status": "failed"}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_unexpected_error",
        fake_handle,
    )

    api = object()
    assert paypal_bind_executor._handle_paypal_unexpected_error(
        api,
        exc,
        session_id="session-1",
        screenshot_paths=screenshot_paths,
    ) == {"status": "failed"}
    assert captured["api"] is api
    assert captured["exc"] is exc
    assert captured["session_id"] == "session-1"
    assert captured["screenshot_paths"] is screenshot_paths
    assert captured["logger"] is paypal_bind_executor.logger
    assert captured["capture_screenshot"] is paypal_bind_executor._capture_screenshot
    assert captured["build_result"] is paypal_bind_executor._build_result


def test_stop_paypal_api_safely_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_stop(_api):
        captured["api"] = _api

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "stop_paypal_api_safely",
        fake_stop,
    )

    api = object()
    paypal_bind_executor._stop_paypal_api_safely(api)
    assert captured["api"] is api


def test_prepare_paypal_auto_flow_payloads_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    payload = {"name": "Taro Yamada"}

    def fake_prepare(**kwargs):
        captured.update(kwargs)
        return {"billing_payload": {}, "signup_billing_payload": {}}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "prepare_paypal_auto_flow_payloads",
        fake_prepare,
    )

    assert paypal_bind_executor._prepare_paypal_auto_flow_payloads(
        autofill_payload=payload,
        autofill_enabled=True,
        paypal_country="JP",
        proxy_url="socks5://proxy.example:1080",
    ) == {"billing_payload": {}, "signup_billing_payload": {}}
    assert captured["autofill_payload"] is payload
    assert captured["autofill_enabled"] is True
    assert captured["paypal_country"] == "JP"
    assert captured["proxy_url"] == "socks5://proxy.example:1080"
    assert captured["resolve_checkout_billing_payload"] is paypal_bind_executor._resolve_checkout_billing_payload
    assert captured["prepare_signup_billing_payload"] is paypal_bind_executor._prepare_paypal_signup_billing_payload


def test_prepare_paypal_auto_flow_identity_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    signup_billing_payload = {"country": "JP"}

    def fake_prepare(**kwargs):
        captured.update(kwargs)
        return {"paypal_credentials": {}, "signup_profile": {}}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "prepare_paypal_auto_flow_identity",
        fake_prepare,
    )

    assert paypal_bind_executor._prepare_paypal_auto_flow_identity(
        paypal_email="paypal@example.com",
        paypal_password="secret",
        signup_billing_payload=signup_billing_payload,
        paypal_country="JP",
        sms_url="https://sms.example.test",
        otp_channel="sms",
        paypal_card_number="4111111111111111",
        paypal_card_expiry="03/30",
        paypal_card_cvv="123",
    ) == {"paypal_credentials": {}, "signup_profile": {}}
    assert captured["paypal_email"] == "paypal@example.com"
    assert captured["paypal_password"] == "secret"
    assert captured["signup_billing_payload"] is signup_billing_payload
    assert captured["paypal_country"] == "JP"
    assert captured["sms_url"] == "https://sms.example.test"
    assert captured["otp_channel"] == "sms"
    assert captured["paypal_card_number"] == "4111111111111111"
    assert captured["paypal_card_expiry"] == "03/30"
    assert captured["paypal_card_cvv"] == "123"
    assert captured["normalize_paypal_credentials"] is paypal_bind_executor._normalize_paypal_credentials
    assert captured["build_paypal_signup_profile"] is paypal_bind_executor._build_paypal_signup_profile


def test_handle_paypal_auto_flow_dispatch_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    def on_progress(event):
        return None
    screenshot_paths = []
    phone_accounts = [{"phone": "+819012345678"}]
    payload = {"name": "Taro Yamada"}
    def is_cancelled():
        return False

    def fake_handle(_api, **kwargs):
        captured["api"] = _api
        captured.update(kwargs)
        return {"status": "success"}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_auto_flow_dispatch",
        fake_handle,
    )

    api = object()
    assert paypal_bind_executor._handle_paypal_auto_flow_dispatch(
        api,
        auto_mode=True,
        email=" user@example.com ",
        checkout_url="https://pay.openai.com/c/pay/cs_demo",
        proxy_url="socks5://proxy.example:1080",
        paypal_mode="create_account",
        paypal_country="JP",
        paypal_lang="ja",
        paypal_email="paypal@example.com",
        paypal_password="secret",
        sms_url="https://sms.example.test",
        otp_channel="sms",
        paypal_card_number="4111111111111111",
        paypal_card_expiry="03/30",
        paypal_card_cvv="123",
        phone_accounts=phone_accounts,
        session_id="session-1",
        screenshot_paths=screenshot_paths,
        timeout_seconds=120,
        is_cancelled=is_cancelled,
        autofill_enabled=True,
        autofill_payload=payload,
        on_progress=on_progress,
    ) == {"status": "success"}
    assert captured["api"] is api
    assert captured["auto_mode"] is True
    assert captured["email"] == " user@example.com "
    assert captured["checkout_url"] == "https://pay.openai.com/c/pay/cs_demo"
    assert captured["proxy_url"] == "socks5://proxy.example:1080"
    assert captured["paypal_mode"] == "create_account"
    assert captured["paypal_country"] == "JP"
    assert captured["paypal_lang"] == "ja"
    assert captured["paypal_email"] == "paypal@example.com"
    assert captured["paypal_password"] == "secret"
    assert captured["sms_url"] == "https://sms.example.test"
    assert captured["otp_channel"] == "sms"
    assert captured["paypal_card_number"] == "4111111111111111"
    assert captured["paypal_card_expiry"] == "03/30"
    assert captured["paypal_card_cvv"] == "123"
    assert captured["phone_accounts"] is phone_accounts
    assert captured["session_id"] == "session-1"
    assert captured["screenshot_paths"] is screenshot_paths
    assert captured["timeout_seconds"] == 120
    assert captured["is_cancelled"] is is_cancelled
    assert captured["autofill_enabled"] is True
    assert captured["autofill_payload"] is payload
    assert captured["prepare_auto_flow_payloads"] is paypal_bind_executor._prepare_paypal_auto_flow_payloads
    assert captured["prepare_auto_flow_identity"] is paypal_bind_executor._prepare_paypal_auto_flow_identity
    assert captured["run_paypal_auto_flow"] is paypal_bind_executor._run_paypal_auto_flow
    assert captured["on_progress"] is on_progress


def test_handle_paypal_auto_flow_checkout_handoff_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    screenshot_paths = []
    billing_payload = {"country": "JP"}
    def on_progress(event):
        return None
    def progress(stage, **kwargs):
        return None
    def is_cancelled():
        return False

    def fake_handle(_api, **kwargs):
        captured["api"] = _api
        captured.update(kwargs)
        return {"status": "needs_review"}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_auto_flow_checkout_handoff",
        fake_handle,
    )

    api = types.SimpleNamespace(page=types.SimpleNamespace(url="https://pay.openai.com/c/pay/cs_demo"))
    assert paypal_bind_executor._handle_paypal_auto_flow_checkout_handoff(
        api,
        current_url="https://pay.openai.com/c/pay/cs_demo",
        email="user@example.com",
        billing_payload=billing_payload,
        session_id="session-1",
        screenshot_paths=screenshot_paths,
        timeout_seconds=180,
        is_cancelled=is_cancelled,
        progress=progress,
        on_progress=on_progress,
    ) == {"status": "needs_review"}
    assert captured["api"] is api
    assert captured["current_url"] == "https://pay.openai.com/c/pay/cs_demo"
    assert captured["email"] == "user@example.com"
    assert captured["billing_payload"] is billing_payload
    assert captured["session_id"] == "session-1"
    assert captured["screenshot_paths"] is screenshot_paths
    assert captured["timeout_seconds"] == 180
    assert captured["is_cancelled"] is is_cancelled
    assert captured["progress"] is progress
    assert captured["is_checkout_host"] is paypal_bind_executor._is_checkout_host
    assert captured["page_url"]() == "https://pay.openai.com/c/pay/cs_demo"
    assert (
        captured["browser_checkout_nonzero_amount_hint"] is paypal_bind_executor._browser_checkout_nonzero_amount_hint
    )
    assert captured["capture_screenshot"] is paypal_bind_executor._capture_screenshot
    assert captured["build_result"] is paypal_bind_executor._build_result
    assert captured["select_paypal_option"] is paypal_bind_executor._select_paypal_option
    assert captured["autofill_allowed"] is paypal_bind_executor._autofill_allowed
    assert captured["has_complete_billing_payload"] is paypal_bind_executor._has_complete_billing_payload
    assert captured["emit_progress"] is paypal_bind_executor._emit_progress
    assert captured["progress_event"] is paypal_bind_executor._progress_event
    assert captured["fill_paypal_checkout_billing_form"] is paypal_bind_executor._fill_paypal_checkout_billing_form
    assert captured["accept_checkout_terms_on_page"] is paypal_bind_executor._accept_checkout_terms_on_page
    assert captured["submit_checkout_to_paypal"] is paypal_bind_executor._submit_checkout_to_paypal
    assert captured["on_progress"] is on_progress


def test_run_paypal_auto_flow_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    screenshot_paths = []
    paypal_credentials = {"email": "paypal@example.com"}
    signup_profile = {"email": "paypal@example.com"}
    phone_accounts = [{"phone": "+12025550123"}]
    billing_payload = {"country": "US"}
    autofill_payload = {"name": "Taro Yamada"}
    def is_cancelled():
        return False
    def on_progress(event):
        return None

    def fake_run(_api, **kwargs):
        captured["api"] = _api
        captured.update(kwargs)
        return {"status": "success"}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "run_paypal_auto_flow_sequence",
        fake_run,
    )

    api = types.SimpleNamespace(page=types.SimpleNamespace(url="https://pay.openai.com/c/pay/cs_demo"))
    assert paypal_bind_executor._run_paypal_auto_flow(
        api,
        email="user@example.com",
        checkout_url="https://pay.openai.com/c/pay/cs_demo",
        proxy_url="socks5://proxy.example:1080",
        paypal_mode="create_account",
        paypal_credentials=paypal_credentials,
        signup_profile=signup_profile,
        phone_accounts=phone_accounts,
        billing_payload=billing_payload,
        paypal_country="JP",
        paypal_lang="ja",
        session_id="session-1",
        screenshot_paths=screenshot_paths,
        timeout_seconds=180,
        is_cancelled=is_cancelled,
        on_progress=on_progress,
        autofill_enabled=True,
        autofill_payload=autofill_payload,
    ) == {"status": "success"}
    assert captured["api"] is api
    assert captured["email"] == "user@example.com"
    assert captured["checkout_url"] == "https://pay.openai.com/c/pay/cs_demo"
    assert captured["proxy_url"] == "socks5://proxy.example:1080"
    assert captured["paypal_mode"] == "create_account"
    assert captured["paypal_credentials"] is paypal_credentials
    assert captured["signup_profile"] is signup_profile
    assert captured["phone_accounts"] is phone_accounts
    assert captured["billing_payload"] is billing_payload
    assert captured["paypal_country"] == "JP"
    assert captured["paypal_lang"] == "ja"
    assert captured["session_id"] == "session-1"
    assert captured["screenshot_paths"] is screenshot_paths
    assert captured["timeout_seconds"] == 180
    assert captured["is_cancelled"] is is_cancelled
    assert captured["autofill_enabled"] is True
    assert captured["autofill_payload"] is autofill_payload
    assert captured["page_url"]() == "https://pay.openai.com/c/pay/cs_demo"
    assert captured["resolve_checkout_billing_payload"] is paypal_bind_executor._resolve_checkout_billing_payload
    assert captured["normalize_paypal_country"] is paypal_bind_executor._normalize_paypal_country
    assert captured["normalize_paypal_lang"] is paypal_bind_executor._normalize_paypal_lang
    assert captured["progress_adapter"] is paypal_bind_executor._progress_adapter
    assert captured["handle_checkout_handoff"] is paypal_bind_executor._handle_paypal_auto_flow_checkout_handoff
    assert captured["run_paypal_authorize_flow"] is paypal_bind_executor._run_paypal_authorize_flow
    assert captured["paypal_authorize_timeout_seconds"] is paypal_bind_executor._paypal_authorize_timeout_seconds
    assert captured["wait_for_paypal_result"] is paypal_bind_executor._wait_for_paypal_result
    assert captured["paypal_result_timeout_seconds"] is paypal_bind_executor._paypal_result_timeout_seconds
    assert captured["on_progress"] is on_progress


def test_handle_paypal_protocol_flow_dispatch_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    def on_progress(event):
        return None
    phone_accounts = [{"phone": "+819012345678"}]
    payload = {"name": "Taro Yamada"}
    pre_extracted = {"ba_token": "BA-DEMO"}
    def is_cancelled():
        return False

    def fake_handle(**kwargs):
        captured.update(kwargs)
        return {"protocol_result": {"status": "success"}}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_protocol_flow_dispatch",
        fake_handle,
    )

    assert paypal_bind_executor._handle_paypal_protocol_flow_dispatch(
        email=" user@example.com ",
        checkout_url="https://pay.openai.com/c/pay/cs_demo",
        proxy_url="socks5://proxy.example:1080",
        paypal_mode="create_account",
        paypal_country="JP",
        paypal_lang="ja",
        paypal_email="paypal@example.com",
        paypal_password="secret",
        sms_url="https://sms.example.test",
        otp_channel="sms",
        paypal_card_number="4111111111111111",
        paypal_card_expiry="03/30",
        paypal_card_cvv="123",
        phone_accounts=phone_accounts,
        timeout_seconds=120,
        is_cancelled=is_cancelled,
        autofill_enabled=True,
        autofill_payload=payload,
        pre_extracted=pre_extracted,
        on_progress=on_progress,
    ) == {"protocol_result": {"status": "success"}}
    assert captured["email"] == " user@example.com "
    assert captured["checkout_url"] == "https://pay.openai.com/c/pay/cs_demo"
    assert captured["proxy_url"] == "socks5://proxy.example:1080"
    assert captured["paypal_mode"] == "create_account"
    assert captured["paypal_country"] == "JP"
    assert captured["paypal_lang"] == "ja"
    assert captured["paypal_email"] == "paypal@example.com"
    assert captured["paypal_password"] == "secret"
    assert captured["sms_url"] == "https://sms.example.test"
    assert captured["otp_channel"] == "sms"
    assert captured["paypal_card_number"] == "4111111111111111"
    assert captured["paypal_card_expiry"] == "03/30"
    assert captured["paypal_card_cvv"] == "123"
    assert captured["phone_accounts"] is phone_accounts
    assert captured["timeout_seconds"] == 120
    assert captured["is_cancelled"] is is_cancelled
    assert captured["autofill_enabled"] is True
    assert captured["autofill_payload"] is payload
    assert captured["pre_extracted"] is pre_extracted
    assert captured["prepare_auto_flow_payloads"] is paypal_bind_executor._prepare_paypal_auto_flow_payloads
    assert captured["build_paypal_signup_profile"] is paypal_bind_executor._build_paypal_signup_profile
    assert captured["run_paypal_protocol_flow"] is paypal_bind_executor._run_paypal_protocol_flow
    assert captured["on_progress"] is on_progress


def test_handle_paypal_protocol_browser_fallback_dispatch_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    def on_progress(event):
        return None
    fallback_context = {"browser_entry_url": "https://www.paypal.com/signin?ba_token=BA-DEMO"}
    phone_accounts = [{"phone": "+819012345678"}]
    signup_billing_payload = {"country": "JP"}
    screenshot_paths = []
    def is_cancelled():
        return False

    class FakeApi:
        def _launch_browser(self, **kwargs):
            captured["launch_direct"] = kwargs

    def fake_handle(_api, **kwargs):
        captured["api"] = _api
        captured.update(kwargs)
        return {"status": "success"}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_protocol_browser_fallback_dispatch",
        fake_handle,
    )

    api = FakeApi()
    assert paypal_bind_executor._handle_paypal_protocol_browser_fallback_dispatch(
        api,
        fallback_context=fallback_context,
        fallback_approve_url="https://www.paypal.com/agreements/approve?ba_token=BA-DEMO",
        fallback_ba_token="BA-DEMO",
        proxy_url="socks5://proxy.example:1080",
        proxy_bypass="localhost",
        fallback_use_camoufox=True,
        fallback_use_roxybrowser=False,
        roxybrowser_workspace_id="workspace-1",
        roxybrowser_profile_id="profile-1",
        paypal_mode="create_account",
        paypal_country="JP",
        paypal_lang="ja",
        paypal_email="paypal@example.com",
        paypal_password="secret",
        sms_url="https://sms.example.test",
        otp_channel="sms",
        paypal_card_number="4111111111111111",
        paypal_card_expiry="03/30",
        paypal_card_cvv="123",
        phone_accounts=phone_accounts,
        signup_billing_payload=signup_billing_payload,
        checkout_url="https://pay.openai.com/c/pay/cs_demo",
        session_id="session-1",
        screenshot_paths=screenshot_paths,
        timeout_seconds=120,
        is_cancelled=is_cancelled,
        on_progress=on_progress,
    ) == {"status": "success"}
    assert captured["api"] is api
    assert captured["fallback_context"] is fallback_context
    assert captured["fallback_approve_url"] == "https://www.paypal.com/agreements/approve?ba_token=BA-DEMO"
    assert captured["fallback_ba_token"] == "BA-DEMO"
    assert captured["proxy_url"] == "socks5://proxy.example:1080"
    assert captured["proxy_bypass"] == "localhost"
    assert captured["fallback_use_camoufox"] is True
    assert captured["fallback_use_roxybrowser"] is False
    assert captured["roxybrowser_workspace_id"] == "workspace-1"
    assert captured["roxybrowser_profile_id"] == "profile-1"
    assert captured["paypal_mode"] == "create_account"
    assert captured["paypal_country"] == "JP"
    assert captured["paypal_lang"] == "ja"
    assert captured["paypal_email"] == "paypal@example.com"
    assert captured["paypal_password"] == "secret"
    assert captured["sms_url"] == "https://sms.example.test"
    assert captured["otp_channel"] == "sms"
    assert captured["paypal_card_number"] == "4111111111111111"
    assert captured["paypal_card_expiry"] == "03/30"
    assert captured["paypal_card_cvv"] == "123"
    assert captured["phone_accounts"] is phone_accounts
    assert captured["signup_billing_payload"] is signup_billing_payload
    assert captured["checkout_url"] == "https://pay.openai.com/c/pay/cs_demo"
    assert captured["session_id"] == "session-1"
    assert captured["screenshot_paths"] is screenshot_paths
    assert captured["timeout_seconds"] == 120
    assert captured["is_cancelled"] is is_cancelled
    assert captured["launch_browser"].__self__ is api
    assert captured["launch_browser"].__func__ is FakeApi._launch_browser
    assert captured["emit_progress"] is paypal_bind_executor._emit_progress
    assert captured["progress_event"] is paypal_bind_executor._progress_event
    assert captured["goto_paypal_page_with_retries"] is paypal_bind_executor._goto_paypal_page_with_retries
    assert captured["handle_browser_fallback_ddc_wait"] is paypal_bind_executor._handle_paypal_browser_fallback_ddc_wait
    assert captured["build_result"] is paypal_bind_executor._build_result
    assert captured["ensure_captcha_bypass"] is paypal_bind_executor._ensure_paypal_hosted_captcha_bypass
    assert captured["normalize_paypal_credentials"] is paypal_bind_executor._normalize_paypal_credentials
    assert captured["build_paypal_signup_profile"] is paypal_bind_executor._build_paypal_signup_profile
    assert captured["run_paypal_authorize_flow"] is paypal_bind_executor._run_paypal_authorize_flow
    assert captured["paypal_authorize_timeout_seconds"] is paypal_bind_executor._paypal_authorize_timeout_seconds
    assert captured["wait_for_paypal_result"] is paypal_bind_executor._wait_for_paypal_result
    assert captured["paypal_result_timeout_seconds"] is paypal_bind_executor._paypal_result_timeout_seconds
    assert captured["on_progress"] is on_progress
    assert captured["preserve_roxybrowser_on_failure"]({"status": "success"}) == {"status": "success"}


def test_handle_paypal_protocol_mode_dispatch_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    def on_progress(event):
        return None
    phone_accounts = [{"phone": "+819012345678"}]
    payload = {"name": "Taro Yamada"}
    pre_extracted = {"ba_token": "BA-DEMO"}
    screenshot_paths = []
    def is_cancelled():
        return False

    def fake_handle(_api, **kwargs):
        captured["api"] = _api
        captured.update(kwargs)
        return {"status": "success"}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_protocol_mode_dispatch",
        fake_handle,
    )

    api = object()
    assert paypal_bind_executor._handle_paypal_protocol_mode_dispatch(
        api,
        protocol_mode=True,
        pre_extracted=pre_extracted,
        email=" user@example.com ",
        checkout_url="https://pay.openai.com/c/pay/cs_demo",
        proxy_url="socks5://proxy.example:1080",
        proxy_bypass="localhost",
        paypal_mode="create_account",
        paypal_country="JP",
        paypal_lang="ja",
        paypal_email="paypal@example.com",
        paypal_password="secret",
        sms_url="https://sms.example.test",
        otp_channel="sms",
        paypal_card_number="4111111111111111",
        paypal_card_expiry="03/30",
        paypal_card_cvv="123",
        phone_accounts=phone_accounts,
        timeout_seconds=120,
        session_id="session-1",
        screenshot_paths=screenshot_paths,
        fallback_use_camoufox=True,
        fallback_use_roxybrowser=True,
        roxybrowser_workspace_id="workspace-1",
        roxybrowser_profile_id="profile-1",
        is_cancelled=is_cancelled,
        autofill_enabled=True,
        autofill_payload=payload,
        on_progress=on_progress,
    ) == {"status": "success"}
    assert captured["api"] is api
    assert captured["protocol_mode"] is True
    assert captured["pre_extracted"] is pre_extracted
    assert captured["email"] == " user@example.com "
    assert captured["checkout_url"] == "https://pay.openai.com/c/pay/cs_demo"
    assert captured["proxy_url"] == "socks5://proxy.example:1080"
    assert captured["proxy_bypass"] == "localhost"
    assert captured["paypal_mode"] == "create_account"
    assert captured["paypal_country"] == "JP"
    assert captured["paypal_lang"] == "ja"
    assert captured["paypal_email"] == "paypal@example.com"
    assert captured["paypal_password"] == "secret"
    assert captured["sms_url"] == "https://sms.example.test"
    assert captured["otp_channel"] == "sms"
    assert captured["paypal_card_number"] == "4111111111111111"
    assert captured["paypal_card_expiry"] == "03/30"
    assert captured["paypal_card_cvv"] == "123"
    assert captured["phone_accounts"] is phone_accounts
    assert captured["timeout_seconds"] == 120
    assert captured["is_cancelled"] is is_cancelled
    assert captured["autofill_enabled"] is True
    assert captured["autofill_payload"] is payload
    assert captured["session_id"] == "session-1"
    assert captured["screenshot_paths"] is screenshot_paths
    assert captured["fallback_use_camoufox"] is True
    assert captured["fallback_use_roxybrowser"] is True
    assert captured["roxybrowser_workspace_id"] == "workspace-1"
    assert captured["roxybrowser_profile_id"] == "profile-1"
    assert captured["handle_pre_extracted_checkout_without_ba"] is (
        paypal_bind_executor._handle_paypal_pre_extracted_checkout_without_ba
    )
    assert captured["build_result"] is paypal_bind_executor._build_result
    assert captured["prepare_auto_flow_payloads"] is paypal_bind_executor._prepare_paypal_auto_flow_payloads
    assert captured["handle_protocol_flow_dispatch"] is paypal_bind_executor._handle_paypal_protocol_flow_dispatch
    assert (
        captured["paypal_protocol_needs_browser_fallback"]
        is paypal_bind_executor._paypal_protocol_needs_browser_fallback
    )
    assert captured["handle_protocol_browser_fallback_context"] is (
        paypal_bind_executor._handle_paypal_protocol_browser_fallback_context
    )
    assert captured["handle_protocol_browser_fallback_dispatch"] is (
        paypal_bind_executor._handle_paypal_protocol_browser_fallback_dispatch
    )
    assert captured["on_progress"] is on_progress


def test_handle_paypal_signup_stop_before_otp_authorize_result_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_handle(state):
        captured["state"] = state
        return {"action": "needs_review"}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_signup_stop_before_otp_authorize_result",
        fake_handle,
    )

    state = {"_stop_before_signup_otp": True}
    assert paypal_bind_executor._handle_paypal_signup_stop_before_otp_authorize_result(state) == {
        "action": "needs_review"
    }
    assert captured["state"] is state


def test_paypal_signup_stop_before_otp_result_fields_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_fields(stop_before_otp_result):
        captured["stop_before_otp_result"] = stop_before_otp_result
        return ("needs_review", "custom-before-otp", "paypal_wait_signup_otp", "stop before otp")

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_signup_stop_before_otp_result_fields",
        fake_fields,
    )

    stop_before_otp_result = {"action": "needs_review"}
    assert paypal_bind_executor._paypal_signup_stop_before_otp_result_fields(stop_before_otp_result) == (
        "needs_review",
        "custom-before-otp",
        "paypal_wait_signup_otp",
        "stop before otp",
    )
    assert captured["stop_before_otp_result"] is stop_before_otp_result


def test_handle_paypal_signup_flow_failure_authorize_result_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    def on_progress(event):
        return None

    def fake_handle(**kwargs):
        captured.update(kwargs)
        return {"action": "failed"}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_signup_flow_failure_authorize_result",
        fake_handle,
    )

    assert paypal_bind_executor._handle_paypal_signup_flow_failure_authorize_result(
        ok=False,
        error="signup failed",
        otp_phone_lock_key="otp-lock",
        on_progress=on_progress,
    ) == {"action": "failed"}
    assert captured["ok"] is False
    assert captured["error"] == "signup failed"
    assert captured["otp_phone_lock_key"] == "otp-lock"
    assert captured["release_otp_phone_lock"] is paypal_bind_executor._release_paypal_otp_phone_lock
    assert captured["on_progress"] is on_progress


def test_paypal_signup_flow_failure_result_fields_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_fields(signup_failure_result, **kwargs):
        captured["signup_failure_result"] = signup_failure_result
        captured.update(kwargs)
        return ("otp-lock", "failed", "custom-signup", "paypal_signup", "signup failed")

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_signup_flow_failure_result_fields",
        fake_fields,
    )

    signup_failure_result = {"action": "failed"}
    assert paypal_bind_executor._paypal_signup_flow_failure_result_fields(
        signup_failure_result,
        fallback_error="fallback error",
    ) == ("otp-lock", "failed", "custom-signup", "paypal_signup", "signup failed")
    assert captured["signup_failure_result"] is signup_failure_result
    assert captured["fallback_error"] == "fallback error"


def test_handle_paypal_signup_login_redirect_authorize_result_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_handle(login_redirect_result):
        captured["login_redirect_result"] = login_redirect_result
        return {"action": "continue"}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_signup_login_redirect_authorize_result",
        fake_handle,
    )

    login_redirect_result = {"action": "continue", "signup_login_redirect_count": 1}
    assert paypal_bind_executor._handle_paypal_signup_login_redirect_authorize_result(login_redirect_result) == {
        "action": "continue"
    }
    assert captured["login_redirect_result"] is login_redirect_result


def test_paypal_signup_login_redirect_continue_values_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_values(login_redirect_action):
        captured["login_redirect_action"] = login_redirect_action
        return (2, True, 12.5, False, 0.0)

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_signup_login_redirect_continue_values",
        fake_values,
    )

    login_redirect_action = {"action": "continue", "signup_login_redirect_count": 2}
    assert paypal_bind_executor._paypal_signup_login_redirect_continue_values(login_redirect_action) == (
        2,
        True,
        12.5,
        False,
        0.0,
    )
    assert captured["login_redirect_action"] is login_redirect_action


def test_paypal_signup_login_redirect_failed_result_fields_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_fields(login_redirect_action):
        captured["login_redirect_action"] = login_redirect_action
        return ("failed", "custom-login", "paypal_signup", "still on login")

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_signup_login_redirect_failed_result_fields",
        fake_fields,
    )

    login_redirect_action = {"action": "failed", "message": "still on login"}
    assert paypal_bind_executor._paypal_signup_login_redirect_failed_result_fields(login_redirect_action) == (
        "failed",
        "custom-login",
        "paypal_signup",
        "still on login",
    )
    assert captured["login_redirect_action"] is login_redirect_action


def test_handle_paypal_signup_stuck_recover_authorize_result_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_handle(stuck_recover_result):
        captured["stuck_recover_result"] = stuck_recover_result
        return {"action": "continue"}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_signup_stuck_recover_authorize_result",
        fake_handle,
    )

    stuck_recover_result = {"action": "continue", "signup_email_submitted": False}
    assert paypal_bind_executor._handle_paypal_signup_stuck_recover_authorize_result(stuck_recover_result) == {
        "action": "continue"
    }
    assert captured["stuck_recover_result"] is stuck_recover_result


def test_paypal_signup_stuck_recover_failed_result_fields_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_fields(stuck_recover_action):
        captured["stuck_recover_action"] = stuck_recover_action
        return ("failed", "custom-timeout", "paypal_signup", "email timed out")

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_signup_stuck_recover_failed_result_fields",
        fake_fields,
    )

    stuck_recover_action = {"action": "failed", "message": "email timed out"}
    assert paypal_bind_executor._paypal_signup_stuck_recover_failed_result_fields(stuck_recover_action) == (
        "failed",
        "custom-timeout",
        "paypal_signup",
        "email timed out",
    )
    assert captured["stuck_recover_action"] is stuck_recover_action


def test_paypal_signup_stuck_recover_continue_values_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_values(stuck_recover_action):
        captured["stuck_recover_action"] = stuck_recover_action
        return (True, 12.5)

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_signup_stuck_recover_continue_values",
        fake_values,
    )

    stuck_recover_action = {"action": "continue", "signup_email_submitted": True}
    assert paypal_bind_executor._paypal_signup_stuck_recover_continue_values(stuck_recover_action) == (True, 12.5)
    assert captured["stuck_recover_action"] is stuck_recover_action


def test_handle_paypal_login_step_failure_authorize_result_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_handle(**kwargs):
        captured.update(kwargs)
        return {"action": "failed"}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_login_step_failure_authorize_result",
        fake_handle,
    )

    assert paypal_bind_executor._handle_paypal_login_step_failure_authorize_result(
        ok=False,
        error="missing password",
    ) == {"action": "failed"}
    assert captured == {"ok": False, "error": "missing password"}


def test_paypal_login_step_failure_result_fields_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_fields(login_failure_result, **kwargs):
        captured["login_failure_result"] = login_failure_result
        captured.update(kwargs)
        return ("failed", "custom-login", "paypal_login", "missing password")

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_login_step_failure_result_fields",
        fake_fields,
    )

    login_failure_result = {"action": "failed"}
    assert paypal_bind_executor._paypal_login_step_failure_result_fields(
        login_failure_result,
        fallback_error="fallback error",
    ) == ("failed", "custom-login", "paypal_login", "missing password")
    assert captured["login_failure_result"] is login_failure_result
    assert captured["fallback_error"] == "fallback error"


def test_handle_paypal_authorize_timeout_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    def on_progress(event):
        return None

    def fake_handle(**kwargs):
        captured.update(kwargs)
        return {"action": "needs_review"}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_authorize_timeout",
        fake_handle,
    )

    assert paypal_bind_executor._handle_paypal_authorize_timeout(
        otp_phone_lock_key="otp-lock",
        on_progress=on_progress,
    ) == {"action": "needs_review"}
    assert captured["otp_phone_lock_key"] == "otp-lock"
    assert captured["release_otp_phone_lock"] is paypal_bind_executor._release_paypal_otp_phone_lock
    assert captured["on_progress"] is on_progress


def test_paypal_authorize_timeout_result_fields_wrapper_delegates(monkeypatch):
    captured = {}

    def fake_fields(timeout_result):
        captured["timeout_result"] = timeout_result
        return ("otp-lock", "needs_review", "custom-timeout", "paypal_authorize", "timed out")

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_authorize_timeout_result_fields",
        fake_fields,
    )

    timeout_result = {"action": "needs_review"}
    assert paypal_bind_executor._paypal_authorize_timeout_result_fields(timeout_result) == (
        "otp-lock",
        "needs_review",
        "custom-timeout",
        "paypal_authorize",
        "timed out",
    )
    assert captured["timeout_result"] is timeout_result


def test_handle_paypal_signup_visible_state_wait_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}

    def fake_handle(state, **kwargs):
        captured["state"] = state
        captured.update(kwargs)
        return {"action": "continue"}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_signup_visible_state_wait",
        fake_handle,
    )

    state = {"email_locator": object()}
    assert paypal_bind_executor._handle_paypal_signup_visible_state_wait(state, sleep_seconds=2.0) == {
        "action": "continue"
    }
    assert captured["state"] is state
    assert captured["sleep_seconds"] == 2.0
    assert captured["sleep"] is paypal_bind_executor.time.sleep


def test_handle_paypal_authorize_idle_wait_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}

    def fake_handle(**kwargs):
        captured.update(kwargs)
        return {"action": "continue"}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_authorize_idle_wait",
        fake_handle,
    )

    assert paypal_bind_executor._handle_paypal_authorize_idle_wait(sleep_seconds=2.0) == {"action": "continue"}
    assert captured["sleep_seconds"] == 2.0
    assert captured["sleep"] is paypal_bind_executor.time.sleep


def test_handle_paypal_approve_ready_wrapper_passes_browser_dependencies(monkeypatch):
    captured = {}
    progress_events = []
    on_progress = progress_events.append
    def is_cancelled():
        return False

    def fake_handle(_api, **kwargs):
        captured.update(kwargs)
        return {"action": "return", "otp_phone_lock_key": "", "result": {"status": "success"}}

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "handle_paypal_approve_ready",
        fake_handle,
    )

    api = object()
    state = {"approve_ready": True}
    screenshot_paths = []
    assert paypal_bind_executor._handle_paypal_approve_ready(
        api,
        state=state,
        otp_phone_lock_key="otp-lock",
        session_id="demo",
        screenshot_paths=screenshot_paths,
        is_cancelled=is_cancelled,
        on_progress=on_progress,
    ) == {"action": "return", "otp_phone_lock_key": "", "result": {"status": "success"}}
    assert captured["state"] is state
    assert captured["otp_phone_lock_key"] == "otp-lock"
    assert captured["click_approve"] is paypal_bind_executor._click_paypal_approve
    assert captured["release_otp_phone_lock"] is paypal_bind_executor._release_paypal_otp_phone_lock
    assert callable(captured["wait_for_return"])
    assert captured["on_progress"] is on_progress


def test_paypal_approve_return_values_wrapper_delegates(monkeypatch):
    captured = {}
    paypal_result = {"status": "success"}

    def fake_values(approve_result):
        captured["approve_result"] = approve_result
        return ("otp-lock", paypal_result)

    monkeypatch.setattr(
        paypal_bind_executor.payment_checkout_browser_service,
        "paypal_approve_return_values",
        fake_values,
    )

    approve_result = {"action": "return", "result": paypal_result}
    assert paypal_bind_executor._paypal_approve_return_values(approve_result) == ("otp-lock", paypal_result)
    assert captured["approve_result"] is approve_result


def test_paypal_authorize_flow_waits_for_subscription_return_after_approve(monkeypatch):
    captured = {}

    class FakePage:
        url = "https://www.paypal.com/agreements/approve?ba_token=BA-123"

    class FakeApi:
        page = FakePage()

    def fake_wait_for_return(_api, **kwargs):
        captured.update(kwargs)
        return {"status": "success", "failure_stage": "", "message": "confirmed", "screenshot_paths": []}

    monkeypatch.setattr(paypal_bind_executor, "_sync_relevant_payment_page", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(paypal_bind_executor, "_force_paypal_us_locale", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(paypal_bind_executor, "_ensure_paypal_hosted_captcha_bypass", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(paypal_bind_executor, "_ddc_slider_visible", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(paypal_bind_executor, "_has_ddc_iframe", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        paypal_bind_executor, "_inspect_paypal_page", lambda _api: {"body_text": "", "approve_ready": True}
    )
    monkeypatch.setattr(paypal_bind_executor, "classify_paypal_checkout_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(paypal_bind_executor, "_click_paypal_approve", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(paypal_bind_executor, "_wait_for_paypal_subscription_return", fake_wait_for_return)

    result = paypal_bind_executor._run_paypal_authorize_flow(
        FakeApi(),
        paypal_mode="existing_account",
        credentials={},
        signup_profile=None,
        session_id="demo",
        screenshot_paths=[],
        timeout_seconds=60,
    )

    assert result["status"] == "success"
    assert captured["timeout_seconds"] == paypal_bind_executor.PAYPAL_APPROVE_RETURN_TIMEOUT_SECONDS


def test_inspect_paypal_page_marks_visible_phone_rejected_prompt(monkeypatch):
    class FakePage:
        url = "https://www.paypal.com/checkoutweb/signup"

    class FakeApi:
        page = FakePage()

    monkeypatch.setattr(paypal_bind_executor, "_ensure_paypal_hosted_captcha_bypass", lambda _api: True)
    monkeypatch.setattr(paypal_bind_executor, "_body_excerpt", lambda *_args, **_kwargs: "Create an account")
    monkeypatch.setattr(paypal_bind_executor, "_has_paypal_phone_rejected_prompt", lambda _api: True)
    monkeypatch.setattr(paypal_bind_executor, "_visible_locator_in_frames", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(paypal_bind_executor, "_has_paypal_otp_inputs", lambda _api: False)

    state = paypal_bind_executor._inspect_paypal_page(FakeApi())

    assert "Try a different phone number" in state["body_text"]
    assert (
        paypal_bind_executor.classify_paypal_checkout_state(
            "https://www.paypal.com/checkoutweb/signup",
            state["body_text"],
        )["failure_stage"]
        == "paypal_phone_rejected"
    )


def test_ensure_paypal_hosted_captcha_bypass_installs_once_and_runs_each_time():
    class FakeContext:
        def __init__(self):
            self.scripts = []

        def add_init_script(self, script):
            self.scripts.append(script)

    class FakePage:
        def __init__(self):
            self.evaluations = []

        def evaluate(self, script):
            self.evaluations.append(script)
            return {"installed": True, "removed": 2}

    class FakeApi:
        def __init__(self):
            self.context = FakeContext()
            self.page = FakePage()

    api = FakeApi()

    assert paypal_bind_executor._ensure_paypal_hosted_captcha_bypass(api) is True
    assert len(api.context.scripts) == 1
    assert len(api.page.evaluations) == 1
    assert "#captcha-standalone" in api.context.scripts[0]
    assert ".captcha-overlay" in api.context.scripts[0]
    assert "MutationObserver" in api.context.scripts[0]

    assert paypal_bind_executor._ensure_paypal_hosted_captcha_bypass(api) is True
    assert len(api.context.scripts) == 1
    assert len(api.page.evaluations) == 2


def test_paypal_ddc_wrappers_delegate_text_and_frame_classification():
    class FakeFrame:
        def __init__(self, url, body):
            self.url = url
            self.body = body

        def inner_text(self, selector):
            assert selector == "body"
            return self.body

    class FakePage:
        def __init__(self, body="", frames=None, url="https://www.paypal.com/checkoutweb/signup"):
            self.body = body
            self.frames = frames or []
            self.url = url

        def inner_text(self, selector):
            assert selector == "body"
            return self.body

    assert paypal_bind_executor._is_ddc_blocked_page(FakePage("Your request has been blocked")) is True
    assert paypal_bind_executor._is_ddc_frame_url("https://geo.captcha-delivery.com/captcha/?t=fe") is True
    assert paypal_bind_executor._is_ddc_frame_url("https://hcaptcha.com/challenge") is False
    assert paypal_bind_executor._ddc_slider_visible(FakePage("Slide to continue")) is True
    assert (
        paypal_bind_executor._ddc_slider_visible(
            FakePage(
                "",
                frames=[
                    FakeFrame("https://hcaptcha.com/challenge", "Slide to continue"),
                    FakeFrame("https://ddc.paypal.com/challenge", "确认您是人类"),
                ],
            )
        )
        is True
    )
    assert paypal_bind_executor._has_ddc_iframe(FakePage("", frames=[FakeFrame("https://datadome.co/frame", "")]))
    assert (
        paypal_bind_executor._ddc_slider_visible(
            FakePage("", frames=[FakeFrame("https://hcaptcha.com/challenge", "Slide to continue")])
        )
        is False
    )


def test_wait_ddc_pass_accepts_checkoutweb_before_invisible_iframe_detection(monkeypatch):
    class FakePage:
        url = "https://www.paypal.com/checkoutweb/signup?ba_token=BA-DEMO"

        def inner_text(self, selector):
            assert selector == "body"
            return ""

    monkeypatch.setattr(paypal_bind_executor.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        paypal_bind_executor,
        "_ddc_slider_visible",
        lambda _page: (_ for _ in ()).throw(AssertionError("slider detection should not run on checkoutweb")),
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_has_ddc_iframe",
        lambda _page: (_ for _ in ()).throw(AssertionError("iframe detection should not run on checkoutweb")),
    )
    events = []

    assert paypal_bind_executor._wait_ddc_pass(FakePage(), on_progress=events.append) is True
    assert events == []


def test_wait_ddc_pass_still_rejects_blocked_checkoutweb(monkeypatch):
    class FakePage:
        url = "https://www.paypal.com/checkoutweb/signup?ba_token=BA-DEMO"

        def inner_text(self, selector):
            assert selector == "body"
            return "Your request has been blocked"

    monkeypatch.setattr(paypal_bind_executor.time, "sleep", lambda _seconds: None)

    assert paypal_bind_executor._wait_ddc_pass(FakePage(), max_blocked_retries=0) is False


def test_run_paypal_signup_flow_prefers_otp_over_registration(monkeypatch):
    events = []

    monkeypatch.setattr(paypal_bind_executor, "_poll_paypal_signup_otp", lambda **_kwargs: "123456")
    monkeypatch.setattr(paypal_bind_executor, "_fill_paypal_otp_inputs", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(paypal_bind_executor, "_click_first", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        paypal_bind_executor,
        "_fill_paypal_signup_form",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("signup form should not run on OTP step")),
    )

    class FakePage:
        url = "https://www.paypal.com/checkoutweb/signup"

        class keyboard:
            @staticmethod
            def press(_key):
                return None

    class FakeApi:
        page = FakePage()

    ok, error, handled = paypal_bind_executor._run_paypal_signup_flow(
        FakeApi(),
        signup_profile={"sms_url": "https://sms.example.test/token=demo"},
        state={
            "body_text": "check your phone",
            "needs_otp": True,
            "otp_inputs_ready": True,
            "signup_submitted": True,
            "registration_ready": True,
        },
        on_progress=lambda event: events.append(event),
    )

    assert ok is True
    assert error == ""
    assert handled is True
    assert any(event.get("stage") == "paypal_submit_otp" for event in events)


def test_run_paypal_signup_flow_polls_otp_when_prompt_detected_without_input_flag(monkeypatch):
    events = []
    calls = []

    monkeypatch.setattr(
        paypal_bind_executor, "_poll_paypal_signup_otp", lambda **_kwargs: calls.append("poll_otp") or "123456"
    )
    monkeypatch.setattr(
        paypal_bind_executor, "_fill_paypal_otp_inputs", lambda *_args, **_kwargs: calls.append("fill_otp") or True
    )
    monkeypatch.setattr(
        paypal_bind_executor, "_click_paypal_otp_submit", lambda *_args, **_kwargs: calls.append("submit_otp") or True
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_fill_paypal_signup_form",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("signup form should not run on OTP prompt")),
    )

    class FakePage:
        url = "https://www.paypal.com/checkoutweb/signup"

        class keyboard:
            @staticmethod
            def press(_key):
                return None

    class FakeApi:
        page = FakePage()

    ok, error, handled = paypal_bind_executor._run_paypal_signup_flow(
        FakeApi(),
        signup_profile={"phone": "09026647330", "country": "JP", "sms_url": "https://sms.example.test/token=demo"},
        state={
            "body_text": "Enter your code We sent a 6-digit code",
            "needs_otp": True,
            "otp_inputs_ready": False,
            "signup_submitted": True,
            "registration_ready": True,
            "registration_text_hint": True,
        },
        on_progress=lambda event: events.append(event),
    )

    assert ok is True
    assert error == ""
    assert handled is True
    assert calls == ["poll_otp", "fill_otp", "submit_otp"]
    assert any(event.get("stage") == "paypal_submit_otp" for event in events)


def test_run_paypal_signup_flow_polls_otp_when_jp_prompt_detected_from_page(monkeypatch):
    events = []
    calls = []

    monkeypatch.setattr(
        paypal_bind_executor,
        "_body_excerpt",
        lambda *_args, **_kwargs: "コードを入力する 6桁のコードを090-2664-7330に送信しました 再送",
    )
    monkeypatch.setattr(paypal_bind_executor, "_has_paypal_otp_inputs", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        paypal_bind_executor, "_poll_paypal_signup_otp", lambda **_kwargs: calls.append("poll_otp") or "828993"
    )
    monkeypatch.setattr(
        paypal_bind_executor, "_fill_paypal_otp_inputs", lambda *_args, **_kwargs: calls.append("fill_otp") or True
    )
    monkeypatch.setattr(
        paypal_bind_executor, "_click_paypal_otp_submit", lambda *_args, **_kwargs: calls.append("submit_otp") or True
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_fill_paypal_signup_form",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("signup form should not run on JP OTP prompt")),
    )

    class FakePage:
        url = "https://www.paypal.com/checkoutweb/signup"

        class keyboard:
            @staticmethod
            def press(_key):
                return None

    class FakeApi:
        page = FakePage()

    state = {
        "needs_otp": False,
        "otp_inputs_ready": False,
        "signup_submitted": True,
        "registration_ready": True,
        "registration_text_hint": True,
    }

    ok, error, handled = paypal_bind_executor._run_paypal_signup_flow(
        FakeApi(),
        signup_profile={"sms_url": "https://sms.example.test/token=demo"},
        state=state,
        on_progress=lambda event: events.append(event),
    )

    assert ok is True
    assert error == ""
    assert handled is True
    assert calls == ["poll_otp", "fill_otp", "submit_otp"]
    assert state["needs_otp"] is True
    assert state["otp_inputs_ready"] is True
    assert any(event.get("stage") == "paypal_submit_otp" for event in events)


def test_run_paypal_signup_flow_can_stop_before_signup_otp(monkeypatch):
    events = []

    monkeypatch.setenv("AUTOTOKEN_PAYPAL_STOP_BEFORE_SIGNUP_OTP", "1")
    monkeypatch.setattr(
        paypal_bind_executor,
        "_poll_paypal_signup_otp",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("OTP must not be polled in stop-before-OTP mode")),
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_fill_paypal_otp_inputs",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("OTP must not be filled in stop-before-OTP mode")
        ),
    )

    class FakePage:
        url = "https://www.paypal.com/checkoutweb/signup"

    class FakeApi:
        page = FakePage()

    state = {
        "signup_submitted": True,
        "signup_submitted_at": 1000.0,
        "needs_otp": True,
        "otp_inputs_ready": True,
    }

    ok, error, handled = paypal_bind_executor._run_paypal_signup_flow(
        FakeApi(),
        signup_profile={"phone": "+817012345678", "sms_url": "https://sms.example.test"},
        state=state,
        on_progress=lambda event: events.append(event),
    )

    assert ok is True
    assert error == ""
    assert handled is False
    assert state["_stop_before_signup_otp"] is True
    assert any(event.get("stage") == "paypal_wait_signup_otp" for event in events)


def test_inspect_paypal_page_marks_otp_prompt_over_registration_form(monkeypatch):
    class FakePage:
        url = "https://www.paypal.com/checkoutweb/signup"

    class FakeApi:
        page = FakePage()

    monkeypatch.setattr(
        paypal_bind_executor,
        "_body_excerpt",
        lambda *_args, **_kwargs: (
            "Card number Billing address Enter your code We sent a 6-digit code to (835) 289-1698"
        ),
    )
    monkeypatch.setattr(paypal_bind_executor, "_ensure_paypal_hosted_captcha_bypass", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(paypal_bind_executor, "_has_paypal_phone_rejected_prompt", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(paypal_bind_executor, "_has_paypal_otp_inputs", lambda *_args, **_kwargs: False)

    def fake_visible(_api, selectors, timeout_ms=1000):
        joined = "\n".join(selectors)
        if "cardNumber" in joined or "card number" in joined:
            return object()
        if "phone" in joined:
            return object()
        return None

    monkeypatch.setattr(paypal_bind_executor, "_visible_locator_in_frames", fake_visible)

    state = paypal_bind_executor._inspect_paypal_page(FakeApi())

    assert state["needs_otp"] is True
    assert state["otp_inputs_ready"] is True
    assert state["registration_ready"] is False


def test_inspect_paypal_page_marks_jp_otp_prompt_over_registration_form(monkeypatch):
    class FakePage:
        url = "https://www.paypal.com/checkoutweb/signup"

    class FakeApi:
        page = FakePage()

    monkeypatch.setattr(
        paypal_bind_executor,
        "_body_excerpt",
        lambda *_args, **_kwargs: (
            "Card number Billing address コードを入力する 6桁のコードを090-2664-7330に送信しました"
        ),
    )
    monkeypatch.setattr(paypal_bind_executor, "_ensure_paypal_hosted_captcha_bypass", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(paypal_bind_executor, "_has_paypal_phone_rejected_prompt", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(paypal_bind_executor, "_has_paypal_otp_inputs", lambda *_args, **_kwargs: False)

    def fake_visible(_api, selectors, timeout_ms=1000):
        joined = "\n".join(selectors)
        if "cardNumber" in joined or "card number" in joined:
            return object()
        if "phone" in joined:
            return object()
        return None

    monkeypatch.setattr(paypal_bind_executor, "_visible_locator_in_frames", fake_visible)

    state = paypal_bind_executor._inspect_paypal_page(FakeApi())

    assert state["needs_otp"] is True
    assert state["otp_inputs_ready"] is True
    assert state["registration_ready"] is False


def test_inspect_paypal_page_marks_jp_registration_form(monkeypatch):
    class FakePage:
        url = "https://www.paypal.com/checkoutweb/signup"

    class FakeApi:
        page = FakePage()

    monkeypatch.setattr(
        paypal_bind_executor,
        "_body_excerpt",
        lambda *_args, **_kwargs: (
            "カード番号 有効期限 セキュリティコード 請求先住所 電話番号 パスワードの作成 生年月日 同意して続行"
        ),
    )
    monkeypatch.setattr(paypal_bind_executor, "_ensure_paypal_hosted_captcha_bypass", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(paypal_bind_executor, "_has_paypal_phone_rejected_prompt", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(paypal_bind_executor, "_has_paypal_otp_inputs", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(paypal_bind_executor, "_visible_locator_in_frames", lambda *_args, **_kwargs: None)

    state = paypal_bind_executor._inspect_paypal_page(FakeApi())

    assert state["registration_ready"] is True
    assert state["registration_text_hint"] is True
    assert state["needs_otp"] is False


def test_poll_paypal_signup_otp_clicks_resend_callback(monkeypatch):
    calls = []
    captured = {}

    class FakePage:
        url = "https://www.paypal.com/checkoutweb/signup"

    class FakeApi:
        page = FakePage()

    def fake_poll_otp_from_sms_url(sms_url, **kwargs):
        captured["sms_url"] = sms_url
        captured.update(kwargs)

        def provider():
            callback = getattr(provider, "_gopay_resend_callback", None)
            assert callable(callback)
            callback()
            return "123456"

        return provider

    monkeypatch.setattr(paypal_bind_executor, "_poll_otp_from_sms_url", fake_poll_otp_from_sms_url)
    monkeypatch.setattr(
        paypal_bind_executor,
        "_click_paypal_signup_otp_resend",
        lambda *_args, **_kwargs: calls.append("click_resend") or True,
    )

    otp = paypal_bind_executor._poll_paypal_signup_otp(
        api=FakeApi(),
        signup_profile={"sms_url": "https://sms.example.test/token=demo", "otp_channel": "sms"},
        timeout_seconds=180,
        on_progress=lambda _event: None,
    )

    assert otp == "123456"
    assert captured["sms_url"] == "https://sms.example.test/token=demo"
    assert captured["resend_after_seconds"] == 60
    assert captured["max_resend_attempts"] == paypal_bind_executor.PAYPAL_SIGNUP_OTP_MAX_RESEND_ATTEMPTS
    assert calls == ["click_resend"]


def test_poll_paypal_signup_otp_wrapper_passes_sms_dependencies(monkeypatch):
    captured = {}
    calls = []

    class FakePage:
        url = "https://www.paypal.com/checkoutweb/signup"

    class FakeApi:
        page = FakePage()

    def fake_poll_paypal_signup_otp(signup_profile, **kwargs):
        captured["signup_profile"] = signup_profile
        captured.update(kwargs)
        kwargs["click_resend"]()
        return "123456"

    monkeypatch.setattr(
        paypal_bind_executor.sms_otp_service,
        "poll_paypal_signup_otp",
        fake_poll_paypal_signup_otp,
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_click_paypal_signup_otp_resend",
        lambda *_args, **_kwargs: calls.append("click_resend") or True,
    )

    api = FakeApi()
    signup_profile = {"sms_url": "https://sms.example.test/token=demo"}
    def on_progress(_event):
        return None
    assert (
        paypal_bind_executor._poll_paypal_signup_otp(
            api=api,
            signup_profile=signup_profile,
            timeout_seconds=180,
            is_cancelled=lambda: False,
            on_progress=on_progress,
        )
        == "123456"
    )
    assert captured["signup_profile"] is signup_profile
    assert captured["otp_poll_timeout_seconds"] == paypal_bind_executor.PAYPAL_SIGNUP_OTP_POLL_TIMEOUT_SECONDS
    assert captured["resend_after_seconds"] == paypal_bind_executor.PAYPAL_SIGNUP_OTP_RESEND_AFTER_SECONDS
    assert captured["max_resend_attempts"] == paypal_bind_executor.PAYPAL_SIGNUP_OTP_MAX_RESEND_ATTEMPTS
    assert captured["on_progress"] is on_progress
    assert captured["progress_event"] is paypal_bind_executor._progress_event
    assert captured["url_summary"] is paypal_bind_executor._safe_url_summary
    assert captured["progress_adapter"] is paypal_bind_executor._progress_adapter
    assert captured["poll_otp_from_sms_url_fn"] is paypal_bind_executor._poll_otp_from_sms_url
    assert calls == ["click_resend"]


def test_click_paypal_signup_otp_resend_supports_japanese_selectors(monkeypatch):
    captured = {}

    class FakePage:
        url = "https://www.paypal.com/checkoutweb/signup"

    class FakeApi:
        page = FakePage()

    monkeypatch.setattr(paypal_bind_executor, "_iter_page_frames", lambda _api: [])

    def fake_click_first(_api, selectors, timeout_ms=0):
        captured["selectors"] = selectors
        captured["timeout_ms"] = timeout_ms
        return any("再送信" in selector or "もう一度送信" in selector for selector in selectors)

    monkeypatch.setattr(paypal_bind_executor, "_click_first", fake_click_first)
    monkeypatch.setattr(paypal_bind_executor.time, "sleep", lambda _seconds: None)

    assert paypal_bind_executor._click_paypal_signup_otp_resend(FakeApi()) is True
    assert captured["timeout_ms"] == 1500
    assert any("コードを再送信" in selector for selector in captured["selectors"])


def _mock_paypal_signup_submit_click(monkeypatch, calls):
    def fake_click_first(_api, selectors, **_kwargs):
        if selectors is paypal_bind_executor.PAYPAL_CREATE_SUBMIT_SELECTORS:
            calls.append("submit_signup")
            return True
        return False

    monkeypatch.setattr(paypal_bind_executor, "_click_first", fake_click_first)


def test_run_paypal_signup_flow_does_not_poll_otp_before_signup_submit(monkeypatch):
    calls = []

    monkeypatch.setattr(
        paypal_bind_executor,
        "_poll_paypal_signup_otp",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("OTP should not be polled before signup submit")),
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_fill_paypal_signup_form",
        lambda *_args, **_kwargs: calls.append("fill_signup") or (True, ""),
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_ensure_paypal_signup_phone_lock",
        lambda *_args, **_kwargs: calls.append("lock_phone") or (True, ""),
    )
    monkeypatch.setattr(
        paypal_bind_executor, "_verify_paypal_signup_required_values", lambda *_args, **_kwargs: (True, "")
    )
    _mock_paypal_signup_submit_click(monkeypatch, calls)
    monkeypatch.setattr(paypal_bind_executor.time, "sleep", lambda _seconds: None)

    class FakePage:
        url = "https://www.paypal.com/checkoutweb/signup"

    class FakeApi:
        page = FakePage()

    ok, error, handled = paypal_bind_executor._run_paypal_signup_flow(
        FakeApi(),
        signup_profile={"phone": "09026647330", "country": "JP", "sms_url": "https://sms.example.test/token=demo"},
        state={
            "body_text": "check your phone verification code",
            "needs_otp": False,
            "registration_ready": True,
        },
        on_progress=lambda _event: None,
    )

    assert ok is True
    assert error == ""
    assert handled is True
    assert calls == ["lock_phone", "fill_signup", "submit_signup"]


def test_run_paypal_signup_flow_ignores_otp_hint_before_signup_submit(monkeypatch):
    calls = []

    monkeypatch.setattr(
        paypal_bind_executor,
        "_poll_paypal_signup_otp",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("OTP should wait until signup form submit")),
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_fill_paypal_signup_form",
        lambda *_args, **_kwargs: calls.append("fill_signup") or (True, ""),
    )
    monkeypatch.setattr(
        paypal_bind_executor, "_verify_paypal_signup_required_values", lambda *_args, **_kwargs: (True, "")
    )
    _mock_paypal_signup_submit_click(monkeypatch, calls)
    monkeypatch.setattr(paypal_bind_executor.time, "sleep", lambda _seconds: None)

    class FakePage:
        url = "https://www.paypal.com/checkoutweb/signup"

    class FakeApi:
        page = FakePage()

    ok, error, handled = paypal_bind_executor._run_paypal_signup_flow(
        FakeApi(),
        signup_profile={"phone": "09026647330", "country": "JP", "sms_url": "https://sms.example.test/token=demo"},
        state={
            "body_text": "PayPal will text you a code to verify this number",
            "needs_otp": True,
            "signup_submitted": False,
            "registration_ready": True,
        },
        on_progress=lambda _event: None,
    )

    assert ok is True
    assert error == ""
    assert handled is True
    assert calls == ["fill_signup", "submit_signup"]


def test_run_paypal_signup_flow_rejects_country_code_only_phone_before_submit(monkeypatch):
    calls = []

    monkeypatch.setattr(paypal_bind_executor.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        paypal_bind_executor,
        "_fill_paypal_signup_form",
        lambda *_args, **_kwargs: calls.append("fill_signup") or (True, ""),
    )
    _mock_paypal_signup_submit_click(monkeypatch, calls)

    class FakePage:
        url = "https://www.paypal.com/checkoutweb/signup"

    class FakeApi:
        page = FakePage()

    ok, error, handled = paypal_bind_executor._run_paypal_signup_flow(
        FakeApi(),
        signup_profile={"phone": "+81", "country": "JP", "sms_url": "https://sms.example.test/token=demo"},
        state={
            "needs_otp": False,
            "signup_submitted": False,
            "registration_ready": True,
            "registration_text_hint": True,
        },
        on_progress=lambda _event: None,
    )

    assert ok is False
    assert "手机号无效" in error
    assert handled is False
    assert calls == []


def test_run_paypal_signup_flow_does_not_click_create_entry_on_registration_form(monkeypatch):
    calls = []

    monkeypatch.setattr(paypal_bind_executor.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        paypal_bind_executor,
        "_click_paypal_create_account",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("registration submit must not be treated as create-entry")
        ),
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_fill_paypal_signup_form",
        lambda *_args, **_kwargs: calls.append("fill_signup") or (True, ""),
    )
    monkeypatch.setattr(
        paypal_bind_executor, "_verify_paypal_signup_required_values", lambda *_args, **_kwargs: (True, "")
    )
    _mock_paypal_signup_submit_click(monkeypatch, calls)

    class FakePage:
        url = "https://www.paypal.com/checkoutweb/signup"

    class FakeApi:
        page = FakePage()

    ok, error, handled = paypal_bind_executor._run_paypal_signup_flow(
        FakeApi(),
        signup_profile={"phone": "09026647330", "country": "JP", "sms_url": "https://sms.example.test/token=demo"},
        state={
            "create_account_ready": True,
            "registration_ready": True,
            "registration_text_hint": True,
        },
        on_progress=lambda _event: None,
    )

    assert ok is True
    assert error == ""
    assert handled is True
    assert calls == ["fill_signup", "submit_signup"]


def test_run_paypal_signup_flow_does_not_refill_after_signup_submit(monkeypatch):
    events = []

    monkeypatch.setattr(paypal_bind_executor.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        paypal_bind_executor,
        "_click_paypal_create_account",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("create account must not be clicked after submit")
        ),
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_poll_paypal_signup_otp",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("OTP should wait for visible inputs")),
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_fill_paypal_signup_form",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("signup form must not be filled twice")),
    )

    class FakePage:
        url = "https://www.paypal.com/checkoutweb/signup"

    class FakeApi:
        page = FakePage()

    ok, error, handled = paypal_bind_executor._run_paypal_signup_flow(
        FakeApi(),
        signup_profile={"sms_url": "https://sms.example.test/token=demo", "otp_channel": "sms"},
        state={
            "body_text": "Create an account to get PayPal benefits",
            "needs_otp": False,
            "otp_inputs_ready": False,
            "signup_submitted": True,
            "signup_submitted_at": paypal_bind_executor.time.time(),
            "registration_ready": True,
            "registration_text_hint": True,
        },
        on_progress=lambda event: events.append(event),
    )

    assert ok is True
    assert error == ""
    assert handled is True
    assert any(event.get("stage") == "paypal_wait_signup_otp" for event in events)


def test_run_paypal_signup_flow_waits_when_approve_hint_over_signup_form_after_submit(monkeypatch):
    events = []

    monkeypatch.setattr(paypal_bind_executor.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        paypal_bind_executor,
        "_click_paypal_create_account",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("create account must not be clicked after submit")
        ),
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_fill_paypal_signup_form",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("signup form must not be filled after submit")),
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_click_first",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("signup submit must not be clicked after submit")
        ),
    )

    class FakePage:
        url = "https://www.paypal.com/checkoutweb/signup"

    class FakeApi:
        page = FakePage()

    ok, error, handled = paypal_bind_executor._run_paypal_signup_flow(
        FakeApi(),
        signup_profile={"phone": "8352880840", "sms_url": "https://sms.example.test/token=demo"},
        state={
            "body_text": "Agree & Create Account Create an account to get PayPal benefits",
            "needs_otp": False,
            "otp_inputs_ready": False,
            "signup_submitted": True,
            "signup_submitted_at": paypal_bind_executor.time.time(),
            "approve_ready": True,
            "create_account_ready": True,
            "registration_ready": True,
            "registration_text_hint": True,
        },
        on_progress=lambda event: events.append(event),
    )

    assert ok is True
    assert error == ""
    assert handled is True
    assert any(event.get("stage") == "paypal_wait_signup_otp" for event in events)


def test_run_paypal_signup_flow_never_resubmits_same_phone(monkeypatch):
    events = []

    monkeypatch.setattr(paypal_bind_executor.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        paypal_bind_executor,
        "_click_paypal_create_account",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("same phone must not restart create-account flow")
        ),
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_fill_paypal_signup_form",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("same phone must not refill signup form")),
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_click_first",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("same phone must not submit signup again")),
    )

    class FakePage:
        url = "https://www.paypal.com/checkoutweb/signup"

    class FakeApi:
        page = FakePage()

    ok, error, handled = paypal_bind_executor._run_paypal_signup_flow(
        FakeApi(),
        signup_profile={"phone": "8352880840", "sms_url": "https://sms.example.test/token=demo"},
        state={
            "body_text": "Create an account to get PayPal benefits",
            "needs_otp": False,
            "signup_submitted": False,
            "signup_submitted_at": paypal_bind_executor.time.time(),
            "submitted_phone_keys": {"8352880840"},
            "registration_ready": True,
            "registration_text_hint": True,
        },
        on_progress=lambda event: events.append(event),
    )

    assert ok is True
    assert error == ""
    assert handled is True
    assert any(event.get("stage") == "paypal_wait_signup_otp" for event in events)


def test_run_paypal_signup_flow_phone_pool_retry_replaces_only_phone(monkeypatch):
    events = []
    calls = []

    monkeypatch.setattr(paypal_bind_executor.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        paypal_bind_executor,
        "_fill_paypal_signup_form",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("phone rotation must not refill full signup form")
        ),
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_replace_paypal_signup_phone",
        lambda *_args, **_kwargs: calls.append("replace_phone") or (True, ""),
    )
    monkeypatch.setattr(
        paypal_bind_executor, "_verify_paypal_signup_required_values", lambda *_args, **_kwargs: (True, "")
    )
    _mock_paypal_signup_submit_click(monkeypatch, calls)

    class FakePage:
        url = "https://www.paypal.com/checkoutweb/signup"

    class FakeApi:
        page = FakePage()

    state = {
        "body_text": "Create an account to get PayPal benefits",
        "needs_otp": False,
        "signup_submitted": False,
        "registration_ready": True,
        "registration_text_hint": True,
        "phone_only_retry": True,
        "submitted_phone_keys": {"8352881474"},
    }
    ok, error, handled = paypal_bind_executor._run_paypal_signup_flow(
        FakeApi(),
        signup_profile={"phone": "8352880971", "sms_url": "https://sms.example.test/token=demo"},
        state=state,
        on_progress=lambda event: events.append(event),
    )

    assert ok is True
    assert error == ""
    assert handled is True
    assert calls == ["replace_phone", "submit_signup"]
    assert state["signup_submitted"] is True
    assert state["phone_only_retry"] is False
    assert "8352880971" in state["submitted_phone_keys"]


def test_run_paypal_signup_flow_card_rejection_replaces_only_card(monkeypatch):
    events = []
    calls = []

    monkeypatch.setattr(paypal_bind_executor.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        paypal_bind_executor,
        "_fill_paypal_signup_form",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("card retry must not refill full signup form")),
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_replace_paypal_signup_phone",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("card retry must not replace phone")),
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_replace_paypal_signup_card",
        lambda _api, *, signup_profile, **_kwargs: (
            calls.append("replace_card")
            or signup_profile.update({"card_number": "4000000000000002", "card_expiry": "05 / 30", "card_cvv": "123"})
            or (True, "")
        ),
    )
    monkeypatch.setattr(
        paypal_bind_executor, "_verify_paypal_signup_required_values", lambda *_args, **_kwargs: (True, "")
    )
    _mock_paypal_signup_submit_click(monkeypatch, calls)

    class FakePage:
        url = "https://www.paypal.com/checkoutweb/signup"

    class FakeApi:
        page = FakePage()

    profile = {
        "phone": "8352622954",
        "card_number": "4111111111111111",
        "card_expiry": "04 / 29",
        "card_cvv": "135",
    }
    state = {
        "body_text": "This card has already been added to another PayPal account. Remove the card from the other account or try a different way to pay.",
        "needs_otp": False,
        "signup_submitted": True,
        "signup_submitted_at": paypal_bind_executor.time.time(),
        "registration_ready": True,
        "registration_text_hint": True,
        "card_rejected": True,
        "card_retry_count": 0,
    }
    ok, error, handled = paypal_bind_executor._run_paypal_signup_flow(
        FakeApi(),
        signup_profile=profile,
        state=state,
        on_progress=lambda event: events.append(event),
    )

    assert ok is True
    assert error == ""
    assert handled is True
    assert calls == ["replace_card", "submit_signup"]
    assert profile["phone"] == "8352622954"
    assert profile["card_number"] == "4000000000000002"
    assert state["signup_submitted"] is True
    assert state["card_retry_count"] == 1
    assert any(event.get("stage") == "paypal_submit_signup" for event in events)


def test_run_paypal_signup_flow_times_out_waiting_after_signup_submit(monkeypatch):
    monkeypatch.setattr(paypal_bind_executor.time, "time", lambda: 1000.0)
    monkeypatch.setattr(paypal_bind_executor.time, "sleep", lambda _seconds: None)

    class FakePage:
        url = "https://www.paypal.com/checkoutweb/signup"

    class FakeApi:
        page = FakePage()

    ok, error, handled = paypal_bind_executor._run_paypal_signup_flow(
        FakeApi(),
        signup_profile={"sms_url": "https://sms.example.test/token=demo"},
        state={
            "needs_otp": False,
            "signup_submitted": True,
            "signup_submitted_at": 1000.0 - paypal_bind_executor.PAYPAL_SIGNUP_OTP_WAIT_TIMEOUT_SECONDS - 1,
            "registration_ready": True,
        },
        on_progress=lambda _event: None,
    )

    assert ok is False
    assert error == "等待 PayPal 验证码超时"
    assert handled is False


def test_run_paypal_signup_flow_handles_email_only_signup_step(monkeypatch):
    events = []
    calls = []

    class FakeEmailLocator:
        def press(self, *_args, **_kwargs):
            calls.append("press_enter")

    monkeypatch.setattr(
        paypal_bind_executor, "_set_locator_value", lambda *_args, **_kwargs: calls.append("fill_email") or True
    )
    monkeypatch.setattr(
        paypal_bind_executor, "_click_first", lambda *_args, **_kwargs: calls.append("click_continue") or True
    )
    monkeypatch.setattr(paypal_bind_executor.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        paypal_bind_executor,
        "_poll_paypal_signup_otp",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("OTP should not be polled on email-only signup step")),
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_fill_paypal_signup_form",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("full signup form is not visible yet")),
    )

    class FakePage:
        url = "https://www.paypal.com/checkoutweb/signup"

    class FakeApi:
        page = FakePage()

    ok, error, handled = paypal_bind_executor._run_paypal_signup_flow(
        FakeApi(),
        signup_profile={"email": "generated@example.com"},
        state={
            "body_text": "Create a PayPal account",
            "needs_otp": False,
            "registration_ready": False,
            "email_locator": FakeEmailLocator(),
        },
        on_progress=lambda event: events.append(event),
    )

    assert ok is True
    assert error == ""
    assert handled is True
    assert calls == ["fill_email", "click_continue"]
    assert any(event.get("stage") == "paypal_signup_email" for event in events)


def test_run_paypal_signup_flow_does_not_resubmit_email_step_while_loading(monkeypatch):
    events = []

    class FakeEmailLocator:
        def press(self, *_args, **_kwargs):
            raise AssertionError("email submit should not run twice while waiting for signup form")

    monkeypatch.setattr(paypal_bind_executor.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        paypal_bind_executor,
        "_set_locator_value",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("email should not be refilled while waiting for signup form")
        ),
    )
    monkeypatch.setattr(
        paypal_bind_executor,
        "_click_first",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("email submit button should not be clicked twice")
        ),
    )

    class FakePage:
        url = "https://www.paypal.com/pay/"

    class FakeApi:
        page = FakePage()

    ok, error, handled = paypal_bind_executor._run_paypal_signup_flow(
        FakeApi(),
        signup_profile={"email": "generated@example.com"},
        state={
            "body_text": "Create a PayPal account",
            "needs_otp": False,
            "registration_ready": False,
            "email_locator": FakeEmailLocator(),
            "signup_email_submitted": True,
            "signup_email_submitted_at": paypal_bind_executor.time.time(),
        },
        on_progress=lambda event: events.append(event),
    )

    assert ok is True
    assert error == ""
    assert handled is True
    assert any(event.get("stage") == "paypal_wait_signup_form" for event in events)


def test_paypal_dismiss_prompt_selectors_do_not_close_otp_modal():
    selectors = "\n".join(paypal_bind_executor.PAYPAL_DISMISS_PROMPT_SELECTORS).lower()

    assert 'has-text("close")' not in selectors
    assert 'has-text("关闭")' not in selectors
    assert "close" not in selectors


def test_fill_paypal_otp_inputs_scans_frames(monkeypatch):
    monkeypatch.setattr(paypal_bind_executor.time, "sleep", lambda _seconds: None)

    class FakeFrame:
        def __init__(self, result):
            self.result = result
            self.calls = 0

        def evaluate(self, _script, _digits):
            self.calls += 1
            return self.result

    class FakeApi:
        pass

    api = FakeApi()
    main_frame = FakeFrame({"filled": False, "count": 0})
    child_frame = FakeFrame({"filled": True, "count": 6})
    monkeypatch.setattr(paypal_bind_executor, "_iter_page_frames", lambda _api: [main_frame, child_frame])

    assert paypal_bind_executor._fill_paypal_otp_inputs(api, "123456") is True
    assert main_frame.calls == 1
    assert child_frame.calls == 1


def test_click_paypal_otp_submit_scans_frames():
    class FakeFrame:
        def __init__(self, result):
            self.result = result
            self.calls = 0

        def evaluate(self, _script):
            self.calls += 1
            return self.result

    class FakeApi:
        pass

    api = FakeApi()
    main_frame = FakeFrame(False)
    child_frame = FakeFrame(True)
    api.page = object()

    original_iter = paypal_bind_executor._iter_page_frames
    try:
        paypal_bind_executor._iter_page_frames = lambda _api: [main_frame, child_frame]
        assert paypal_bind_executor._click_paypal_otp_submit(api) is True
    finally:
        paypal_bind_executor._iter_page_frames = original_iter

    assert main_frame.calls == 1
    assert child_frame.calls == 1


def test_extract_sms_code():
    assert _extract_sms_code("验证码 123456，请勿泄露") == "123456"
    assert _extract_sms_code("SMS-OK|654321") == "654321"
    assert (
        _extract_sms_code(
            '{"code":0,"msg":"No verification code","data":{"code":"","expired_date":"2026-07-25 00:00:00"}}'
        )
        == ""
    )
    assert _extract_sms_code('{"code":0,"data":{"code":"345678","expired_date":"2026-07-25 00:00:00"}}') == "345678"
    assert (
        _extract_sms_code(
            '{"code":1,"msg":"ok","data":{"code":"(GOJEK) Ini OTP buat hubungkan OpenAI LLC ke GoPay. OTP: 511937 gojek.com/safety #511937"}}'
        )
        == "511937"
    )
    assert _extract_sms_code('{"code":0,"data":{"records":[{"sms_content":"Kode OTP GoPay kamu 456789"}]}}') == "456789"
    assert (
        _extract_sms_code('{"status":"ok","result":{"items":[{"message":"no code"},{"message":"OpenAI OTP: 567890"}]}}')
        == "567890"
    )
    assert _extract_sms_codes("old OTP: 111111\nnew OTP: 222222") == ["222222", "111111"]
    assert _extract_sms_code('{"code":1,"data":{"code":"GoPay 1234 is your verification code"}}') == ""
    assert _extract_sms_code("PayPal: 12345 is your security code. Do not share it.") == "12345"
    assert _extract_sms_code("Your PayPal security code is 654321.") == "654321"
    assert (
        _extract_sms_code(
            '{"code":0,"data":{"take_time":"2026-06-05 09:24:17","phone_number":"080*****085",'
            '"sms_content":[{"recv_time":"2026-06-05 23:08:50",'
            '"content":"PayPal: お客さまのセキュリティコードは564755です。コードを他の方と共有することはお控えください。"}]},'
            '"msg":"ok"}'
        )
        == "564755"
    )
    assert _extract_sms_code('{"code":1,"data":{"code":"PayPal code: 112233"}}') == "112233"
    assert (
        _extract_sms_code(
            '{"code":1,"msg":"ok","data":{"code":"PayPal: Thanks for confirming your phone number. '
            'Log in or get the app to get transaction alerts: https://py.pl/hxcYT",'
            '"code_time":"2026-05-21 04:10:04","expired_date":"2026-07-31 00:00:00"}}'
        )
        == ""
    )
    assert (
        _extract_sms_code(
            '{"code":1,"msg":"ok","data":{"code":"PayPal: transaction alerts enabled","expired_date":"20260731"}}'
        )
        == ""
    )


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


def test_paypal_protocol_otp_timeout_uses_paypal_label(monkeypatch):
    now = [0.0]

    monkeypatch.setattr(paypal_protocol_signup.time, "time", lambda: now[0])
    monkeypatch.setattr(paypal_protocol_signup.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    monkeypatch.setattr(paypal_protocol_signup.sms_otp_service, "fetch_sms_code", lambda *_args, **_kwargs: "")

    provider = paypal_protocol_signup._poll_otp_from_sms_url(
        "https://sms.example.test",
        timeout_seconds=60,
        initial_delay_seconds=0,
        resend_after_seconds=1,
        max_resend_attempts=0,
    )

    with pytest.raises(GoPayOTPCancelled, match="PayPal OTP"):
        provider()


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
