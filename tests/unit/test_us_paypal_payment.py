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


def test_create_express_billing_agreement_returns_ba_url():
    calls = []

    class FakeStripe:
        def post(self, url, **kwargs):
            calls.append((url, kwargs.get("data")))
            return _JsonResponse({
                "paypal_billing_agreement_token": "BA-EXPRESS",
                "paypal_billing_agreement_client_secret": "secret_test",
            })

    fields = us_paypal.create_express_billing_agreement(FakeStripe(), stripe_pk="pk_test", sdk_version="v5")

    assert calls[0][0].endswith("/v1/elements/express_billing_agreement")
    assert calls[0][1]["key"] == "pk_test"
    assert calls[0][1]["paypal_sdk_version"] == "v5"
    assert fields["paypal_link"] == "https://www.paypal.com/agreements/approve?ba_token=BA-EXPRESS"
    assert fields["provider_redirect_url"] == fields["paypal_link"]
    assert fields["ba_token"] == "BA-EXPRESS"
    assert fields["link_source"] == "stripe_express_billing_agreement"
    assert fields["link_binding"] == "unbound_express"


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
        "total_summary": {"due": 0},
        "payment_method_types": ["card", "paypal"],
        "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_test",
    })
    monkeypatch.setattr(us_paypal, "stripe_update_tax_region", lambda *args, **kwargs: calls.append(("tax", "ok")))

    def fake_confirm(*args, **kwargs):
        captured["return_url"] = kwargs["return_url"]
        captured["billing"] = kwargs["billing"]
        return {"submission_attempt": {"state": "requires_approval"}}

    monkeypatch.setattr(us_paypal, "create_express_billing_agreement", lambda *args, **kwargs: pytest.fail("unbound express BA must not be used"))
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
    assert result["fields"]["amount"] == "0"
    assert result["fields"]["link_source"] == "stripe_checkout_approve_poll"
    assert result["fields"]["link_binding"] == "chatgpt_checkout_session"


def test_generate_paypal_trial_applies_promo_after_initial_us_stripe_init(monkeypatch):
    calls = []

    class FakeChatgptSession:
        def post(self, url, **kwargs):
            calls.append(("chatgpt_post", url, kwargs.get("json")))
            if url.endswith("/checkout/update"):
                return _JsonResponse({"success": True, "checkout_session": {}})
            return _JsonResponse({
                "checkout_session_id": "cs_test",
                "processor_entity": "openai_llc",
                "public_key": "pk_test",
            })

    init_payloads = iter([
        {
            "total_summary": {"due": 2120},
            "payment_method_types": ["card", "paypal"],
            "ordered_payment_method_types": ["card", "paypal", "apple_pay", "google_pay"],
            "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_test",
        },
        {
            "total_summary": {"due": 0},
            "payment_method_types": ["card", "paypal"],
            "ordered_payment_method_types": ["card", "paypal", "apple_pay", "google_pay"],
            "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_test",
        },
    ])

    monkeypatch.setattr(us_paypal, "pix_proxy_context", lambda local, dynamic, log: _ProxyContext(dynamic))
    monkeypatch.setattr(us_paypal, "build_chatgpt_session", lambda *args, **kwargs: FakeChatgptSession())
    monkeypatch.setattr(us_paypal, "build_stripe_session", lambda *args, **kwargs: object())
    monkeypatch.setattr(us_paypal, "stripe_init", lambda *args, **kwargs: next(init_payloads))
    monkeypatch.setattr(us_paypal, "create_express_billing_agreement", lambda *args, **kwargs: pytest.fail("unbound express BA must not be used"))
    monkeypatch.setattr(us_paypal, "_confirm_paypal_inline", lambda *args, **kwargs: {
        "_ba_approve_url": "https://www.paypal.com/agreements/approve?ba_token=BA-LATEPROMO",
        "submission_attempt": {"state": "requires_action"},
    })

    result = us_paypal.generate_paypal_trial(
        us_paypal.PaypalJobConfig(access_token="token", direct_proxies=["proxy"], apply_promo=True)
    )

    update_payload = next(payload for kind, url, payload in calls if kind == "chatgpt_post" and url.endswith("/checkout/update"))
    assert update_payload["billing_details"] == {"country": "JP", "currency": "JPY"}
    assert result["amount"] == "0"
    assert result["fields"]["pre_promo_amount"] == "2120"
    assert result["fields"]["post_promo_payment_method_types"] == ["card", "paypal"]
    assert result["fields"]["ba_token"] == "BA-LATEPROMO"
    assert result["fields"]["link_source"] == "stripe_payment_pages_confirm"
    assert result["fields"]["link_binding"] == "chatgpt_checkout_session"


def test_generate_paypal_trial_uses_target_country_for_checkout_billing_and_proxy(monkeypatch):
    calls = []
    proxy_stages = []

    class FakeChatgptSession:
        def post(self, url, **kwargs):
            calls.append(("chatgpt_post", url, kwargs.get("json")))
            if url.endswith("/checkout/update"):
                return _JsonResponse({"success": True, "checkout_session": {}})
            return _JsonResponse({
                "checkout_session_id": "cs_test",
                "processor_entity": "openai_llc",
                "public_key": "pk_test",
            })

    init_payloads = iter([
        {"total_summary": {"due": 1800}, "payment_method_types": ["card", "paypal"]},
        {"total_summary": {"due": 0}, "payment_method_types": ["card", "paypal"]},
    ])

    def fake_proxy_context(local, dynamic, log):
        proxy_stages.append(dynamic)
        return _ProxyContext(dynamic)

    monkeypatch.setattr(us_paypal, "pix_proxy_context", fake_proxy_context)
    monkeypatch.setattr(us_paypal, "build_chatgpt_session", lambda *args, **kwargs: FakeChatgptSession())
    monkeypatch.setattr(us_paypal, "build_stripe_session", lambda *args, **kwargs: object())
    monkeypatch.setattr(us_paypal, "stripe_init", lambda *args, **kwargs: next(init_payloads))
    monkeypatch.setattr(us_paypal, "create_express_billing_agreement", lambda *args, **kwargs: pytest.fail("unbound express BA must not be used"))
    monkeypatch.setattr(us_paypal, "_confirm_paypal_inline", lambda *args, **kwargs: {
        "_ba_approve_url": "https://www.paypal.com/agreements/approve?ba_token=BA-GB",
    })

    result = us_paypal.generate_paypal_trial(
        us_paypal.PaypalJobConfig(
            access_token="token",
            direct_proxies=["socks5h://user-zone-custom-region-US-session-fixed:pass@proxy.example:10000"],
            region="GB",
            promo_region="JP",
            apply_promo=True,
        )
    )

    checkout_payload = next(payload for kind, url, payload in calls if kind == "chatgpt_post" and url.endswith("/checkout"))
    promo_payload = next(payload for kind, url, payload in calls if kind == "chatgpt_post" and url.endswith("/checkout/update"))
    assert checkout_payload["billing_details"] == {"country": "GB", "currency": "GBP"}
    assert promo_payload["billing_details"] == {"country": "JP", "currency": "JPY"}
    assert "-custom-region-GB-session-" in proxy_stages[0]
    assert "-custom-region-GB-session-" in proxy_stages[1]
    assert "-custom-region-JP-session-" in proxy_stages[2]
    assert "-custom-region-GB-session-" in proxy_stages[3]
    assert proxy_stages[3] != proxy_stages[1]
    assert result["fields"]["billing"]["country"] == "GB"
    assert result["fields"]["amount"] == "0"
    assert result["fields"]["link_source"] == "stripe_payment_pages_confirm"

def test_generate_paypal_trial_stops_when_amount_is_not_zero(monkeypatch):
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

    with pytest.raises(RuntimeError, match="PayPal 金额必须为 0: 2000"):
        us_paypal.generate_paypal_trial(us_paypal.PaypalJobConfig(access_token="token", direct_proxies=["proxy"], apply_promo=False))


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

    with pytest.raises(RuntimeError, match="PayPal 金额必须为 0: 2000"):
        us_paypal.generate_paypal_trial(us_paypal.PaypalJobConfig(access_token="token", direct_proxies=["proxy"], apply_promo=True))


def test_is_zero_amount_accepts_zero_formats_only():
    assert us_paypal.is_zero_amount(0) is True
    assert us_paypal.is_zero_amount("0.00") is True
    assert us_paypal.is_zero_amount(" 0.0 ") is True
    assert us_paypal.is_zero_amount(2000) is False
    assert us_paypal.is_zero_amount("") is False


def test_promo_currency_for_region_supports_zero_trial_regions():
    assert us_paypal.promo_currency_for_region("JP") == "JPY"
    assert us_paypal.promo_currency_for_region("br") == "BRL"
    assert us_paypal.promo_currency_for_region("VN") == "VND"
    assert us_paypal.promo_currency_for_region("US") == "USD"


def test_build_paypal_dynamic_proxy_aligns_711_region_to_us():
    raw = "global.rotgb.711proxy.com:10000:USER-zone-custom-region-IN-session-abc123-sessTime-120:pass"

    proxy, sid_label = us_paypal.build_paypal_dynamic_proxy(
        us_paypal.PaypalJobConfig(access_token="token", region="US", direct_proxies=[raw]),
        0,
    )

    assert "custom-region-US-session-" in proxy
    assert "custom-region-IN-session-" not in proxy
    assert "sid=abc123" not in sid_label

    promo_proxy, promo_sid_label = us_paypal.build_paypal_dynamic_proxy(
        us_paypal.PaypalJobConfig(access_token="token", region="US", direct_proxies=[raw]),
        0,
        "JP",
    )
    assert "custom-region-JP-session-" in promo_proxy
    assert "region=JP" in promo_sid_label


def test_paypal_proxy_rewrites_arxlabs_region_and_rotates_sid():
    raw = "us.arxlabs.io:3010:hyrj1177789-region-US-sid-1zdnMWQi-t-120:smhwqe9f"

    proxy, sid_label = us_paypal.build_paypal_dynamic_proxy(
        us_paypal.PaypalJobConfig(access_token="token", region="GB", direct_proxies=[raw]),
        0,
    )

    assert proxy.startswith("socks5h://")
    assert "-region-GB-sid-" in proxy
    assert "-region-US-sid-" not in proxy
    assert "1zdnMWQi" not in proxy
    assert "sid=" in sid_label

    promo_proxy, promo_sid_label = us_paypal.build_paypal_dynamic_proxy(
        us_paypal.PaypalJobConfig(access_token="token", region="GB", direct_proxies=[raw]),
        1,
        "JP",
    )
    assert "-region-JP-sid-" in promo_proxy
    assert "-region-US-sid-" not in promo_proxy
    assert "region=JP" in promo_sid_label


def test_paypal_proxy_injects_session_for_711_region_only_proxy():
    raw = "global.rotgb.711proxy.com:10000:USER105777-zone-custom-region-US:d74d61"

    proxy, sid_label = us_paypal.build_paypal_dynamic_proxy(
        us_paypal.PaypalJobConfig(access_token="token", region="CA", direct_proxies=[raw]),
        0,
    )

    assert "custom-region-CA-session-" in proxy
    assert "custom-region-US" not in proxy
    assert "-sessTime-180-sessAuto-1" in proxy
    assert "sid=" in sid_label



def test_generate_paypal_trial_allows_promo_when_initial_stripe_has_no_paypal(monkeypatch):
    calls = []

    class FakeChatgptSession:
        def post(self, url, **kwargs):
            calls.append(("chatgpt_post", url, kwargs.get("json")))
            if url.endswith("/checkout/update"):
                return _JsonResponse({"success": True, "checkout_session": {}})
            return _JsonResponse({
                "checkout_session_id": "cs_test",
                "processor_entity": "openai_llc",
                "public_key": "pk_test",
            })

    init_payloads = iter([
        {"total_summary": {"due": 2120}, "payment_method_types": ["card"], "ordered_payment_method_types": ["card"]},
        {"total_summary": {"due": 0}, "payment_method_types": ["card", "paypal"], "ordered_payment_method_types": ["card", "paypal"]},
    ])

    monkeypatch.setattr(us_paypal, "pix_proxy_context", lambda local, dynamic, log: _ProxyContext(dynamic))
    monkeypatch.setattr(us_paypal, "build_chatgpt_session", lambda *args, **kwargs: FakeChatgptSession())
    monkeypatch.setattr(us_paypal, "build_stripe_session", lambda *args, **kwargs: object())
    monkeypatch.setattr(us_paypal, "stripe_init", lambda *args, **kwargs: next(init_payloads))
    monkeypatch.setattr(us_paypal, "create_express_billing_agreement", lambda *args, **kwargs: pytest.fail("unbound express BA must not be used"))
    monkeypatch.setattr(us_paypal, "_confirm_paypal_inline", lambda *args, **kwargs: {
        "_ba_approve_url": "https://www.paypal.com/agreements/approve?ba_token=BA-LATEPAYPAL",
    })

    result = us_paypal.generate_paypal_trial(
        us_paypal.PaypalJobConfig(access_token="token", direct_proxies=["proxy"], apply_promo=True)
    )

    assert any(kind == "chatgpt_post" and url.endswith("/checkout/update") for kind, url, _payload in calls)
    assert result["fields"]["ba_token"] == "BA-LATEPAYPAL"
    assert result["fields"]["link_binding"] == "chatgpt_checkout_session"
