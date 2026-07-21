from __future__ import annotations

import pytest

from autotoken.payments import us_paypal


class _JsonResponse:
    def __init__(self, payload, status_code=200, text=None, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload) if text is None else text
        self.headers = headers or {"content-type": "application/json"}

    def json(self):
        return self._payload


class _ProxyContext:
    def __init__(self, url):
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_extract_paypal_result_reads_stripe_and_ba_redirects():
    stripe_payload = {"next_action": {"type": "redirect_to_url", "redirect_to_url": {"url": "https://pm-redirects.stripe.com/authorize/test"}}}
    stripe_fields = us_paypal.extract_paypal_result(stripe_payload, "cs_test")
    assert stripe_fields["paypal_link"] == "https://pm-redirects.stripe.com/authorize/test"
    assert stripe_fields["stripe_redirect_url"] == "https://pm-redirects.stripe.com/authorize/test"
    assert us_paypal.is_success(stripe_fields) is True

    ba_payload = {"body": "https://www.paypal.com/agreements/approve?ba_token=BA-123ABC"}
    ba_fields = us_paypal.extract_paypal_result(ba_payload, "cs_test")
    assert ba_fields["paypal_link"] == "https://www.paypal.com/agreements/approve?ba_token=BA-123ABC"
    assert ba_fields["ba_token"] == "BA-123ABC"
    assert us_paypal.is_success(ba_fields) is True


def test_generate_paypal_trial_approves_then_polls_redirect(monkeypatch):
    calls = []
    captured = {}

    class FakeChatgptSession:
        def post(self, url, **kwargs):
            calls.append(("chatgpt_post", url, kwargs.get("json")))
            return _JsonResponse({
                "checkout_session_id": "cs_test",
                "processor_entity": "openai_llc",
                "public_key": "pk_test",
            })

    monkeypatch.setattr(us_paypal, "pix_proxy_context", lambda local, dynamic, log: _ProxyContext(dynamic))
    monkeypatch.setattr(us_paypal, "build_chatgpt_session", lambda *args, **kwargs: FakeChatgptSession())
    monkeypatch.setattr(us_paypal, "build_stripe_session", lambda *args, **kwargs: object())
    monkeypatch.setattr(us_paypal, "stripe_init", lambda *args, **kwargs: {
        "total_summary": {"due": 2000},
        "payment_method_types": ["card", "paypal"],
        "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_test",
    })
    monkeypatch.setattr(us_paypal, "stripe_update_tax_region", lambda *args, **kwargs: calls.append(("tax", "ok")))

    def fake_confirm(*args, **kwargs):
        captured["return_url"] = kwargs["return_url"]
        captured["billing"] = kwargs["billing"]
        return {"submission_attempt": {"state": "requires_approval"}}

    monkeypatch.setattr(us_paypal, "_confirm_paypal_inline", fake_confirm)

    def fake_approve(*args, **kwargs):
        calls.append(("approve", args[1]))

    monkeypatch.setattr(us_paypal, "chatgpt_approve", fake_approve)
    monkeypatch.setattr(us_paypal, "page_get", lambda *args, **kwargs: {
        "next_action": {"type": "redirect_to_url", "redirect_to_url": {"url": "https://pm-redirects.stripe.com/authorize/test"}},
        "submission_attempt": {"state": "processing"},
    })
    monkeypatch.setattr(us_paypal, "resolve_external_redirect", lambda stripe, url: "https://www.paypal.com/agreements/approve?ba_token=BA-TEST")

    result = us_paypal.generate_paypal_trial(us_paypal.PaypalJobConfig(access_token="token", direct_proxies=["proxy"]))

    assert ("approve", "cs_test") in calls
    assert "redirect_pm_type=paypal" in captured["return_url"]
    assert captured["billing"]["country"] == "US"
    assert result["fields"]["paypal_link"] == "https://www.paypal.com/agreements/approve?ba_token=BA-TEST"
    assert result["fields"]["ba_token"] == "BA-TEST"
    assert result["fields"]["amount"] == "2000"


def test_generate_paypal_trial_stops_when_promo_keeps_non_zero_amount(monkeypatch):
    class FakeChatgptSession:
        def post(self, url, **kwargs):
            return _JsonResponse({
                "checkout_session_id": "cs_test",
                "processor_entity": "openai_llc",
                "public_key": "pk_test",
            })

    monkeypatch.setattr(us_paypal, "pix_proxy_context", lambda local, dynamic, log: _ProxyContext(dynamic))
    monkeypatch.setattr(us_paypal, "build_chatgpt_session", lambda *args, **kwargs: FakeChatgptSession())
    monkeypatch.setattr(us_paypal, "build_stripe_session", lambda *args, **kwargs: object())
    monkeypatch.setattr(us_paypal, "stripe_init", lambda *args, **kwargs: {"total_summary": {"due": 2000}, "payment_method_types": ["card", "paypal"]})
    monkeypatch.setattr(us_paypal, "_confirm_paypal_inline", lambda *args, **kwargs: pytest.fail("should not confirm PayPal"))

    with pytest.raises(RuntimeError, match="套 promo 后金额不是 0"):
        us_paypal.generate_paypal_trial(us_paypal.PaypalJobConfig(access_token="token", direct_proxies=["proxy"], apply_promo=True))


def test_confirm_paypal_inline_returns_ba_url_from_error_body():
    class FakeStripe:
        def post(self, url, **kwargs):
            return _JsonResponse(
                {},
                status_code=402,
                text='{"error":"needs action","next":"https://www.paypal.com/agreements/approve?ba_token=BA-ERR123"}',
            )

    payload = us_paypal._confirm_paypal_inline(
        FakeStripe(),
        cs_id="cs_test",
        stripe_pk="pk_test",
        ctx={
            "guid": "guid",
            "muid": "muid",
            "sid": "sid",
            "stripe_js_id": "stripe-js-id",
            "elements_session_id": "elements-session-id",
            "elements_session_config_id": "config-id",
            "config_id": "config-id",
            "init_checksum": "checksum",
        },
        billing={
            "name": "John Miller",
            "email": "john@example.com",
            "line1": "121 SW Morrison Street",
            "city": "Portland",
            "state": "OR",
            "postal_code": "97204",
        },
        amount="2000",
        return_url="https://pay.openai.com/c/pay/cs_test",
    )

    assert payload["_raw_status"] == 402
    assert payload["_ba_approve_url"] == "https://www.paypal.com/agreements/approve?ba_token=BA-ERR123"


def test_generate_paypal_trial_rechecks_promo_amount_after_tax_region(monkeypatch):
    class FakeChatgptSession:
        def post(self, url, **kwargs):
            return _JsonResponse({
                "checkout_session_id": "cs_test",
                "processor_entity": "openai_llc",
                "public_key": "pk_test",
            })

    init_payloads = iter([
        {"total_summary": {"due": 0}, "payment_method_types": ["card", "paypal"]},
        {"total_summary": {"due": 2000}, "payment_method_types": ["card", "paypal"]},
    ])

    monkeypatch.setattr(us_paypal, "pix_proxy_context", lambda local, dynamic, log: _ProxyContext(dynamic))
    monkeypatch.setattr(us_paypal, "build_chatgpt_session", lambda *args, **kwargs: FakeChatgptSession())
    monkeypatch.setattr(us_paypal, "build_stripe_session", lambda *args, **kwargs: object())
    monkeypatch.setattr(us_paypal, "stripe_init", lambda *args, **kwargs: next(init_payloads))
    monkeypatch.setattr(us_paypal, "stripe_update_tax_region", lambda *args, **kwargs: None)
    monkeypatch.setattr(us_paypal, "_confirm_paypal_inline", lambda *args, **kwargs: pytest.fail("should not confirm PayPal"))

    with pytest.raises(RuntimeError, match="套 promo 后金额不是 0: 2000"):
        us_paypal.generate_paypal_trial(us_paypal.PaypalJobConfig(access_token="token", direct_proxies=["proxy"], apply_promo=True))
