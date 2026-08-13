from __future__ import annotations

import pytest

from autotoken.payments import momo_vn


class _JsonResponse:
    def __init__(self, payload, status_code=200, text=None, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload) if text is None else text
        self.headers = headers or {}

    def json(self):
        return self._payload


class _ProxyContext:
    def __init__(self, url):
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _CaptureStripeSession:
    def __init__(self, payload=None):
        self.payload = payload or {}
        self.last_post = None
        self.last_get = None

    def post(self, url, data=None, timeout=None, **kwargs):
        self.last_post = {"url": url, "data": data or {}, "timeout": timeout, "kwargs": kwargs}
        return _JsonResponse(self.payload)

    def get(self, url, params=None, timeout=None, **kwargs):
        self.last_get = {"url": url, "params": params or {}, "timeout": timeout, "kwargs": kwargs}
        return _JsonResponse(self.payload)


def _eligible_context() -> dict[str, object]:
    return {
        "ok": True,
        "status": "eligible",
        "has_momo": True,
        "cs_id": "cs_test",
        "processor": "openai_llc",
        "stripe_pk": "pk_test",
        "device_id": "device-test",
        "checkout_proxy_url": "http://checkout-proxy",
        "promotion_proxy_url": "http://promo-proxy",
        "provider_proxy_url": "http://provider-proxy",
        "payment_method_types": ["card", "momo"],
        "ordered_payment_method_types": ["card", "momo"],
        "ctx": {
            "stripe_js_id": "stripe-js-id",
            "client_session_id": "client-session-id",
            "guid": "guid-test",
            "muid": "muid-test",
            "sid": "sid-test",
            "elements_session_id": "elements_session_test",
            "elements_session_config_id": "elements_config_test",
            "config_id": "cfg_test",
            "init_checksum": "init_test",
        },
        "billing": {
            "name": "Nguyen Van A",
            "email": "buyer@example.com",
            "country": "VN",
            "line1": "1 Nguyen Hue",
            "city": "Ho Chi Minh City",
            "postal_code": "700000",
            "state": "HCM",
        },
    }


def test_momo_job_config_defaults_to_vn_promotion_region():
    cfg = momo_vn.MomoVnJobConfig(access_token="token", direct_proxies=["proxy"])

    assert cfg.promotion_region == "VN"
    assert momo_vn._stage_region(cfg, 1) == "VN"


def test_extract_momo_result_recurses_nested_redirect():
    payload = {
        "setup_intent": {
            "next_action": {
                "type": "redirect_to_url",
                "redirect_to_url": {"url": "https://pm-redirects.stripe.com/authorize/acct/test_nested"},
            }
        },
        "submission_attempt": {"state": "processing"},
    }

    fields = momo_vn.extract_momo_result(payload, "cs_test")

    assert fields["stripe_redirect_url"] == "https://pm-redirects.stripe.com/authorize/acct/test_nested"
    assert fields["submission_state"] == "processing"
    assert fields["next_action_type"] == "redirect_to_url"


def test_momo_stripe_init_uses_vn_locale_and_timezone():
    stripe = _CaptureStripeSession({"config_id": "cfg_test", "init_checksum": "init_test"})
    ctx = dict(_eligible_context()["ctx"])

    momo_vn.stripe_init(stripe, "cs_test", "pk_test", ctx)

    assert stripe.last_post["url"].endswith("/v1/payment_pages/cs_test/init")
    assert stripe.last_post["data"]["browser_locale"] == "vi-VN"
    assert stripe.last_post["data"]["browser_timezone"] == "Asia/Ho_Chi_Minh"
    assert stripe.last_post["data"]["redirect_type"] == "url"
    assert stripe.last_post["data"]["elements_session_client[locale]"] == "vi"


def test_momo_page_get_uses_vn_locale_and_session_context():
    stripe = _CaptureStripeSession({"submission_attempt": {"state": "processing"}})
    ctx = dict(_eligible_context()["ctx"])

    payload = momo_vn.page_get(stripe, "cs_test", "pk_test", ctx)

    assert payload["submission_attempt"]["state"] == "processing"
    assert stripe.last_get["url"].endswith("/v1/payment_pages/cs_test")
    assert stripe.last_get["params"]["elements_session_client[session_id]"] == "elements_session_test"
    assert stripe.last_get["params"]["elements_session_client[locale]"] == "vi"


def test_detect_momo_eligibility_returns_eligible_when_methods_include_momo(monkeypatch):
    class FakeChatgptSession:
        def post(self, url, **kwargs):
            assert url.endswith("/payments/checkout")
            return _JsonResponse({
                "checkout_session_id": "cs_test",
                "processor_entity": "openai_llc",
                "publishable_key": "pk_test",
            })

    monkeypatch.setattr(momo_vn, "pix_proxy_context", lambda local, dynamic, log: _ProxyContext(dynamic))
    monkeypatch.setattr(momo_vn, "build_chatgpt_session", lambda *args, **kwargs: FakeChatgptSession())
    monkeypatch.setattr(momo_vn, "build_stripe_session", lambda *args, **kwargs: object())
    monkeypatch.setattr(momo_vn, "warm_chatgpt_checkout_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        momo_vn,
        "stripe_init",
        lambda stripe, cs_id, stripe_pk, ctx: {
            "total_summary": {"due": 350000},
            "currency": "vnd",
            "payment_method_types": ["card", "momo"],
            "ordered_payment_method_types": ["card", "momo", "link"],
            "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_test",
            "config_id": "cfg_test",
            "init_checksum": "init_test",
            "customer": {"email": "buyer@example.com"},
        },
    )

    result = momo_vn.detect_momo_eligibility(momo_vn.MomoVnJobConfig(access_token="token", direct_proxies=["proxy"]))

    assert result["status"] == "eligible"
    assert result["has_momo"] is True
    assert result["cs_id"] == "cs_test"
    assert result["stripe_pk"] == "pk_test"
    assert result["payment_method_types"] == ["card", "momo"]
    assert result["ordered_payment_method_types"] == ["card", "momo", "link"]


def test_detect_momo_eligibility_returns_ineligible_when_momo_missing(monkeypatch):
    class FakeChatgptSession:
        def post(self, url, **kwargs):
            return _JsonResponse({
                "checkout_session_id": "cs_test",
                "processor_entity": "openai_llc",
                "publishable_key": "pk_test",
            })

    monkeypatch.setattr(momo_vn, "pix_proxy_context", lambda local, dynamic, log: _ProxyContext(dynamic))
    monkeypatch.setattr(momo_vn, "build_chatgpt_session", lambda *args, **kwargs: FakeChatgptSession())
    monkeypatch.setattr(momo_vn, "build_stripe_session", lambda *args, **kwargs: object())
    monkeypatch.setattr(momo_vn, "warm_chatgpt_checkout_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        momo_vn,
        "stripe_init",
        lambda stripe, cs_id, stripe_pk, ctx: {
            "total_summary": {"due": 350000},
            "currency": "vnd",
            "payment_method_types": ["card"],
            "ordered_payment_method_types": ["card", "link"],
        },
    )

    result = momo_vn.detect_momo_eligibility(momo_vn.MomoVnJobConfig(access_token="token", direct_proxies=["proxy"]))

    assert result["status"] == "ineligible"
    assert result["has_momo"] is False
    assert result["payment_method_types"] == ["card"]


def test_detect_momo_eligibility_handles_oaics_without_payment_pages(monkeypatch):
    stripe_init_called = {"value": False}
    fetched = {"value": False}
    promoted = {"value": False}

    class FakeChatgptSession:
        def post(self, url, **kwargs):
            return _JsonResponse({
                "checkout_session_id": "oaics_test_custom",
                "processor_entity": "openai_llc",
                "publishable_key": "pk_test",
            })

    def fake_stripe_init(stripe, cs_id, stripe_pk, ctx):
        stripe_init_called["value"] = True
        raise AssertionError("oaics flow should not call payment_pages stripe_init")

    monkeypatch.setattr(momo_vn, "pix_proxy_context", lambda local, dynamic, log: _ProxyContext(dynamic))
    monkeypatch.setattr(momo_vn, "build_chatgpt_session", lambda *args, **kwargs: FakeChatgptSession())
    monkeypatch.setattr(momo_vn, "build_stripe_session", lambda *args, **kwargs: object())
    monkeypatch.setattr(momo_vn, "warm_chatgpt_checkout_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(momo_vn, "stripe_init", fake_stripe_init)
    monkeypatch.setattr(momo_vn, "update_momo_checkout_promotion", lambda *args, **kwargs: promoted.__setitem__("value", True))
    monkeypatch.setattr(
        momo_vn,
        "fetch_oaics_checkout_session",
        lambda *args, **kwargs: (
            pytest.fail("oaics eligibility must inject promo before fetch") if not promoted["value"] else fetched.__setitem__("value", True)
        )
        or {
            "checkout_amount_minor": 0,
            "currency": "vnd",
            "payment_method_types": ["card", "momo"],
            "publishable_key": "pk_test",
            "customer_session_client_secret": "cuss_test",
        },
    )
    monkeypatch.setattr(
        momo_vn,
        "submit_oaics_checkout_taxes",
        lambda *args, **kwargs: {
            "checkout_amount_minor": 0,
            "currency": "vnd",
            "payment_method_types": ["card", "momo"],
        },
    )

    result = momo_vn.detect_momo_eligibility(momo_vn.MomoVnJobConfig(access_token="token", direct_proxies=["proxy"]))

    assert stripe_init_called["value"] is False
    assert promoted["value"] is True
    assert fetched["value"] is True
    assert result["status"] == "eligible"
    assert result["has_momo"] is True
    assert result["cs_id"] == "oaics_test_custom"
    assert result["payment_method_types"] == ["card", "momo"]
    assert result["checkout_flow"] == "oaics"


def test_detect_momo_eligibility_can_create_checkout_with_front_promo(monkeypatch):
    checkout_body = {}

    class FakeChatgptSession:
        def post(self, url, **kwargs):
            if url.endswith("/payments/checkout"):
                checkout_body.update(kwargs.get("json") or {})
                return _JsonResponse({
                    "checkout_session_id": "oaics_test_custom",
                    "processor_entity": "openai_llc",
                    "publishable_key": "pk_test",
                })
            raise AssertionError("front-promo oaics probe should not update promo after checkout")

    monkeypatch.setattr(momo_vn, "pix_proxy_context", lambda local, dynamic, log: _ProxyContext(dynamic))
    monkeypatch.setattr(momo_vn, "build_chatgpt_session", lambda *args, **kwargs: FakeChatgptSession())
    monkeypatch.setattr(momo_vn, "build_stripe_session", lambda *args, **kwargs: object())
    monkeypatch.setattr(momo_vn, "warm_chatgpt_checkout_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        momo_vn,
        "fetch_oaics_checkout_session",
        lambda *args, **kwargs: {
            "checkout_amount_minor": 0,
            "currency": "vnd",
            "payment_method_types": ["card", "momo"],
            "publishable_key": "pk_test",
            "customer_session_client_secret": "cuss_test",
        },
    )
    monkeypatch.setattr(
        momo_vn,
        "submit_oaics_checkout_taxes",
        lambda *args, **kwargs: {"checkout_amount_minor": 0, "currency": "vnd", "payment_method_types": ["card", "momo"]},
    )

    result = momo_vn.detect_momo_eligibility(
        momo_vn.MomoVnJobConfig(access_token="token", direct_proxies=["proxy"], front_promo=True)
    )

    assert checkout_body["promo_campaign"]["promo_campaign_id"] == "plus-1-month-free"
    assert result["checkout_flow"] == "oaics"
    assert result["front_promo"] is True


def test_detect_momo_eligibility_reports_oaics_nonzero_as_ineligible(monkeypatch):
    class FakeChatgptSession:
        def post(self, url, **kwargs):
            return _JsonResponse({
                "checkout_session_id": "oaics_test_custom",
                "processor_entity": "openai_llc",
                "publishable_key": "pk_test",
            })

    monkeypatch.setattr(momo_vn, "pix_proxy_context", lambda local, dynamic, log: _ProxyContext(dynamic))
    monkeypatch.setattr(momo_vn, "build_chatgpt_session", lambda *args, **kwargs: FakeChatgptSession())
    monkeypatch.setattr(momo_vn, "build_stripe_session", lambda *args, **kwargs: object())
    monkeypatch.setattr(momo_vn, "warm_chatgpt_checkout_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(momo_vn, "update_momo_checkout_promotion", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        momo_vn,
        "fetch_oaics_checkout_session",
        lambda *args, **kwargs: {
            "total": {"total": 522500},
            "amount_total": 522500,
            "currency": "vnd",
            "payment_method_types": ["card", "momo"],
            "publishable_key": "pk_test",
            "customer_session_client_secret": "cuss_test",
        },
    )
    monkeypatch.setattr(
        momo_vn,
        "submit_oaics_checkout_taxes",
        lambda *args, **kwargs: {"total": {"total": 522500}, "amount_total": 522500, "payment_method_types": ["card", "momo"]},
    )

    result = momo_vn.detect_momo_eligibility(
        momo_vn.MomoVnJobConfig(access_token="token", direct_proxies=["proxy"], front_promo=True)
    )

    assert result["checkout_flow"] == "oaics"
    assert result["status"] == "ineligible"
    assert result["has_momo"] is True
    assert result["amount"] == "522500"
    assert "金额必须为 0" in result["error"]


def test_generate_momo_vn_trial_requires_eligibility_before_extract(monkeypatch):
    called = {"detect": 0}

    def fake_detect(cfg, log=None):
        called["detect"] += 1
        return {"status": "ineligible", "has_momo": False, "payment_method_types": ["card"]}

    monkeypatch.setattr(momo_vn, "detect_momo_eligibility", fake_detect)

    with pytest.raises(RuntimeError, match="无 MoMo 资格"):
        momo_vn.generate_momo_vn_trial(momo_vn.MomoVnJobConfig(access_token="token", direct_proxies=["proxy"]))

    assert called["detect"] == 1


def test_generate_momo_vn_trial_rejects_nonzero_after_promo(monkeypatch):
    eligibility = _eligible_context()
    init_calls = []

    monkeypatch.setattr(momo_vn, "detect_momo_eligibility", lambda cfg, log=None: eligibility)
    monkeypatch.setattr(momo_vn, "build_chatgpt_session", lambda *args, **kwargs: object())
    monkeypatch.setattr(momo_vn, "build_stripe_session", lambda *args, **kwargs: object())
    monkeypatch.setattr(momo_vn, "warm_chatgpt_checkout_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(momo_vn, "update_momo_checkout_promotion", lambda *args, **kwargs: None)
    monkeypatch.setattr(momo_vn, "sync_momo_tax_region", lambda *args, **kwargs: None)
    monkeypatch.setattr(momo_vn, "pix_proxy_context", lambda local, dynamic, log: _ProxyContext(dynamic))

    def fake_stripe_init(stripe, cs_id, stripe_pk, ctx):
        init_calls.append(1)
        return {
            "total_summary": {"due": 1000},
            "currency": "vnd",
            "payment_method_types": ["card", "momo"],
            "ordered_payment_method_types": ["card", "momo"],
            "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_test",
            "config_id": "cfg_test",
            "init_checksum": "init_test",
            "customer": {"email": "buyer@example.com"},
        }

    monkeypatch.setattr(momo_vn, "stripe_init", fake_stripe_init)

    with pytest.raises(RuntimeError, match="金额不是 0"):
        momo_vn.generate_momo_vn_trial(momo_vn.MomoVnJobConfig(access_token="token", direct_proxies=["proxy"]))

    assert init_calls


def test_generate_momo_vn_trial_routes_oaics_preflight_result(monkeypatch):
    eligibility = _eligible_context() | {"cs_id": "oaics_test_custom", "front_promo": True}
    called = {}

    def fake_oaics_trial(**kwargs):
        called.update(kwargs)
        return {"ok": True, "amount": "0", "fields": {"momo_link": "https://payment.momo.vn/pay/app?token=test"}}

    monkeypatch.setattr(momo_vn, "generate_momo_oaics_trial_experimental", fake_oaics_trial)

    result = momo_vn.generate_momo_vn_trial(
        momo_vn.MomoVnJobConfig(
            access_token="token",
            direct_proxies=["proxy"],
            preflight_result=eligibility,
        )
    )

    assert result["ok"] is True
    assert called["cs_id"] == "oaics_test_custom"
    assert called["processor"] == "openai_llc"
    assert called["country"] == "VN"
    assert called["currency"] == "VND"
    assert called["promo_already_applied"] is True


def test_generate_momo_oaics_standard_flow_resolves_provider_redirect(monkeypatch):
    class FakeChatgptSession:
        pass

    stripe = object()
    calls = []

    monkeypatch.setattr(momo_vn, "build_momo_chatgpt_session", lambda *args, **kwargs: FakeChatgptSession())
    monkeypatch.setattr(momo_vn, "build_stripe_session", lambda *args, **kwargs: stripe)
    monkeypatch.setattr(momo_vn, "warm_chatgpt_checkout_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(momo_vn, "update_momo_checkout_promotion", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        momo_vn,
        "fetch_oaics_checkout_session",
        lambda *args, **kwargs: {
            "checkout_amount_minor": 0,
            "payment_method_types": ["card", "momo"],
            "publishable_key": "pk_test",
            "customer_session_client_secret": "cuss_test",
        },
    )
    monkeypatch.setattr(
        momo_vn,
        "submit_oaics_checkout_taxes",
        lambda *args, **kwargs: {"checkout_amount_minor": 0, "payment_method_types": ["card", "momo"]},
    )
    monkeypatch.setattr(
        momo_vn,
        "create_oaics_elements_session",
        lambda *args, **kwargs: {
            "_oaics_publishable_key": "pk_test",
            "_oaics_payment_method_types": ["card", "momo"],
            "session_id": "elements_session_test",
            "config_id": "config_test",
        },
    )
    monkeypatch.setattr(momo_vn, "create_oaics_momo_confirmation_token", lambda *args, **kwargs: "ctoken_test")
    monkeypatch.setattr(
        momo_vn,
        "confirm_oaics_standard_momo",
        lambda *args, **kwargs: {"client_secret": "seti_test_secret_123", "confirm_return_url": "https://chatgpt.com/checkout/success"},
    )
    monkeypatch.setattr(
        momo_vn,
        "confirm_oaics_momo_intent",
        lambda *args, **kwargs: {
            "next_action": {
                "type": "redirect_to_url",
                "redirect_to_url": {"url": "https://pm-redirects.stripe.com/authorize/acct/momo_test"},
            }
        },
    )
    monkeypatch.setattr(
        momo_vn,
        "resolve_momo_redirect",
        lambda stripe_arg, redirect_url, max_hops=3: calls.append((stripe_arg, redirect_url))
        or "https://payment.momo.vn/pay/app?token=test",
    )

    result = momo_vn.generate_momo_oaics_trial_experimental(
        access_token="token",
        cs_id="oaics_test_custom",
        processor="openai_llc",
        proxy_url="http://proxy",
        device_id="device-test",
        billing=dict(_eligible_context()["billing"]),
        country="VN",
        currency="VND",
    )

    assert calls == [(stripe, "https://pm-redirects.stripe.com/authorize/acct/momo_test")]
    assert result["fields"]["momo_link"] == "https://payment.momo.vn/pay/app?token=test"
    assert result["fields"]["stripe_redirect_url"] == "https://pm-redirects.stripe.com/authorize/acct/momo_test"
    assert result["fields"]["link_source"] == "oaics_standard_momo_intent_confirm"
    assert result["fields"]["link_binding"] == "chatgpt_oaics_checkout_session"


def test_generate_momo_oaics_skips_update_when_front_promo_already_applied(monkeypatch):
    promoted = {"value": False}

    monkeypatch.setattr(momo_vn, "build_momo_chatgpt_session", lambda *args, **kwargs: object())
    monkeypatch.setattr(momo_vn, "build_stripe_session", lambda *args, **kwargs: object())
    monkeypatch.setattr(momo_vn, "warm_chatgpt_checkout_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(momo_vn, "update_momo_checkout_promotion", lambda *args, **kwargs: promoted.__setitem__("value", True))
    monkeypatch.setattr(
        momo_vn,
        "fetch_oaics_checkout_session",
        lambda *args, **kwargs: {
            "checkout_amount_minor": 0,
            "payment_method_types": ["momo"],
            "publishable_key": "pk_test",
            "customer_session_client_secret": "cuss_test",
        },
    )
    monkeypatch.setattr(momo_vn, "submit_oaics_checkout_taxes", lambda *args, **kwargs: {"checkout_amount_minor": 0, "payment_method_types": ["momo"]})
    monkeypatch.setattr(momo_vn, "create_oaics_elements_session", lambda *args, **kwargs: {"_oaics_publishable_key": "pk_test", "_oaics_payment_method_types": ["momo"]})
    monkeypatch.setattr(momo_vn, "create_oaics_momo_confirmation_token", lambda *args, **kwargs: "ctoken_test")
    monkeypatch.setattr(
        momo_vn,
        "confirm_oaics_standard_momo",
        lambda *args, **kwargs: {"next_action": {"redirect_to_url": {"url": "https://pm-redirects.stripe.com/authorize/acct/momo_test"}}},
    )
    monkeypatch.setattr(momo_vn, "resolve_momo_redirect", lambda *args, **kwargs: "https://payment.momo.vn/pay/app?token=test")

    momo_vn.generate_momo_oaics_trial_experimental(
        access_token="token",
        cs_id="oaics_test_custom",
        processor="openai_llc",
        proxy_url="http://proxy",
        device_id="device-test",
        billing=dict(_eligible_context()["billing"]),
        country="VN",
        currency="VND",
        promo_already_applied=True,
    )

    assert promoted["value"] is False


def test_oaics_momo_custom_payment_methods_filters_to_momo():
    payload = {
        "custom_payment_methods": [
            {"id": "cpmt_card_like", "display_name": "Bank redirect"},
            {"id": "cpmt_momo", "display_name": "MoMo"},
        ]
    }

    assert momo_vn.oaics_momo_custom_payment_methods(payload) == [{"id": "cpmt_momo", "display_name": "MoMo"}]


def test_generate_momo_vn_trial_approve_poll_resolves_provider_redirect(monkeypatch):
    calls = []
    eligibility = _eligible_context()

    monkeypatch.setattr(momo_vn, "detect_momo_eligibility", lambda cfg, log=None: eligibility)
    monkeypatch.setattr(momo_vn, "pix_proxy_context", lambda local, dynamic, log: _ProxyContext(dynamic))
    monkeypatch.setattr(momo_vn, "build_chatgpt_session", lambda *args, **kwargs: object())
    monkeypatch.setattr(momo_vn, "build_stripe_session", lambda *args, **kwargs: object())
    monkeypatch.setattr(momo_vn, "warm_chatgpt_checkout_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(momo_vn, "update_momo_checkout_promotion", lambda *args, **kwargs: calls.append("promo"))
    monkeypatch.setattr(momo_vn, "sync_momo_tax_region", lambda *args, **kwargs: calls.append("tax"))
    monkeypatch.setattr(
        momo_vn,
        "stripe_init",
        lambda stripe, cs_id, stripe_pk, ctx: {
            "total_summary": {"due": 0},
            "currency": "vnd",
            "payment_method_types": ["card", "momo"],
            "ordered_payment_method_types": ["card", "momo"],
            "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_test",
            "customer": {"email": "buyer@example.com"},
        },
    )
    monkeypatch.setattr(
        momo_vn,
        "_confirm_momo_inline",
        lambda *args, **kwargs: {
            "next_action": {
                "type": "redirect_to_url",
                "redirect_to_url": {"url": "https://pm-redirects.stripe.com/authorize/acct/test_nonce"},
            },
            "submission_attempt": {"state": "requires_approval"},
        },
    )
    monkeypatch.setattr(
        momo_vn,
        "chatgpt_approve",
        lambda *args, **kwargs: calls.append(("approve", args[1], kwargs.get("country"))),
    )
    monkeypatch.setattr(
        momo_vn,
        "page_get",
        lambda stripe, cs_id, stripe_pk, ctx: {
            "next_action": {
                "type": "redirect_to_url",
                "redirect_to_url": {"url": "https://pm-redirects.stripe.com/authorize/acct/test_nonce"},
            },
            "submission_attempt": {"state": "processing"},
        },
    )
    monkeypatch.setattr(
        momo_vn,
        "resolve_momo_redirect",
        lambda stripe, redirect_url, max_hops=3: "https://payment.momo.vn/pay/app?token=test",
    )

    result = momo_vn.generate_momo_vn_trial(momo_vn.MomoVnJobConfig(access_token="token", direct_proxies=["proxy"]))

    assert "promo" in calls
    assert "tax" in calls
    assert ("approve", "cs_test", "VN") in calls
    assert result["fields"]["momo_link"] == "https://payment.momo.vn/pay/app?token=test"
    assert result["fields"]["provider_redirect_url"] == "https://payment.momo.vn/pay/app?token=test"
    assert result["fields"]["stripe_redirect_url"] == "https://pm-redirects.stripe.com/authorize/acct/test_nonce"
    assert result["fields"]["amount"] == "0"
    assert result["fields"]["link_source"] == "stripe_checkout_approve_poll"
