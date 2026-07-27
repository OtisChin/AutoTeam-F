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


def test_detect_momo_eligibility_accepts_oaics_checkout_session_id(monkeypatch):
    seen = {}

    class FakeChatgptSession:
        def post(self, url, **kwargs):
            return _JsonResponse({
                "checkout_session_id": "oaics_test_custom",
                "processor_entity": "openai_llc",
                "publishable_key": "pk_test",
            })

    def fake_stripe_init(stripe, cs_id, stripe_pk, ctx):
        seen["cs_id"] = cs_id
        return {
            "total_summary": {"due": 0},
            "currency": "vnd",
            "payment_method_types": ["card", "momo"],
            "ordered_payment_method_types": ["card", "momo"],
        }

    monkeypatch.setattr(momo_vn, "pix_proxy_context", lambda local, dynamic, log: _ProxyContext(dynamic))
    monkeypatch.setattr(momo_vn, "build_chatgpt_session", lambda *args, **kwargs: FakeChatgptSession())
    monkeypatch.setattr(momo_vn, "build_stripe_session", lambda *args, **kwargs: object())
    monkeypatch.setattr(momo_vn, "warm_chatgpt_checkout_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(momo_vn, "stripe_init", fake_stripe_init)

    result = momo_vn.detect_momo_eligibility(momo_vn.MomoVnJobConfig(access_token="token", direct_proxies=["proxy"]))

    assert seen["cs_id"] == "oaics_test_custom"
    assert result["cs_id"] == "oaics_test_custom"
    assert result["status"] == "eligible"
    assert result["has_momo"] is True


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


def test_generate_momo_vn_trial_accepts_oaics_preflight_result(monkeypatch):
    eligibility = _eligible_context() | {"cs_id": "oaics_test_custom"}
    init_calls = []

    monkeypatch.setattr(momo_vn, "build_chatgpt_session", lambda *args, **kwargs: object())
    monkeypatch.setattr(momo_vn, "build_stripe_session", lambda *args, **kwargs: object())
    monkeypatch.setattr(momo_vn, "warm_chatgpt_checkout_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(momo_vn, "update_momo_checkout_promotion", lambda *args, **kwargs: None)
    monkeypatch.setattr(momo_vn, "sync_momo_tax_region", lambda *args, **kwargs: None)
    monkeypatch.setattr(momo_vn, "pix_proxy_context", lambda local, dynamic, log: _ProxyContext(dynamic))

    def fake_stripe_init(stripe, cs_id, stripe_pk, ctx):
        init_calls.append(cs_id)
        return {
            "total_summary": {"due": 1000},
            "currency": "vnd",
            "payment_method_types": ["card", "momo"],
            "ordered_payment_method_types": ["card", "momo"],
            "stripe_hosted_url": "https://checkout.stripe.com/c/pay/oaics_test_custom",
            "config_id": "cfg_test",
            "init_checksum": "init_test",
            "customer": {"email": "buyer@example.com"},
        }

    monkeypatch.setattr(momo_vn, "stripe_init", fake_stripe_init)

    with pytest.raises(RuntimeError, match="金额不是 0"):
        momo_vn.generate_momo_vn_trial(
            momo_vn.MomoVnJobConfig(
                access_token="token",
                direct_proxies=["proxy"],
                preflight_result=eligibility,
            )
        )

    assert init_calls == ["oaics_test_custom"]


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
