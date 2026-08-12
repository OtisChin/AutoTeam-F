from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

from autotoken.payments import us_paypal


class Response:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)
        self.headers = {}

    def json(self):
        return self._payload


@contextmanager
def fake_proxy_context(_local_proxy, dynamic_proxy, _log):
    class Chain:
        url = dynamic_proxy

    yield Chain()


def test_generate_paypal_trial_routes_oaics_checkout_to_native_paypal(monkeypatch):
    events: list[tuple[str, object]] = []

    class ChatGPT:
        def post(self, url, **kwargs):
            events.append(("chatgpt_post", url, kwargs.get("json")))
            return Response(
                200,
                {
                    "checkout_session_id": "oaics_test",
                    "processor_entity": "openai_ie",
                    "checkout_url": "https://chatgpt.com/checkout/openai_ie/oaics_test",
                },
            )

        def get(self, *_args, **_kwargs):
            return Response(200, {})

    monkeypatch.setattr(us_paypal, "pix_proxy_context", fake_proxy_context)
    monkeypatch.setattr(us_paypal, "build_chatgpt_session", lambda *_args, **_kwargs: ChatGPT())
    monkeypatch.setattr(us_paypal, "warm_chatgpt_checkout_context", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        us_paypal,
        "build_paypal_dynamic_proxy",
        lambda _cfg, stage, region=None: (f"socks5://proxy-{stage}-{region}", f"sid-{stage}"),
    )

    def fake_oaics_flow(**kwargs):
        events.append(("oaics_flow", kwargs["cs_id"]))
        return {
            "ok": True,
            "amount": "0",
            "fields": {
                "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-OAICS",
                "provider_redirect_url": "https://www.paypal.com/agreements/approve?ba_token=BA-OAICS",
                "stripe_redirect_url": "https://pm-redirects.stripe.com/authorize/oaics",
                "ba_token": "BA-OAICS",
                "cs_id": "oaics_test",
                "link_source": "oaics_standard_paypal_intent_confirm",
                "link_binding": "chatgpt_oaics_checkout_session",
                "chatgpt_checkout_url": "https://chatgpt.com/checkout/openai_ie/oaics_test",
                "billing": {"country": "DE"},
            },
            "billing": {"country": "DE"},
        }

    monkeypatch.setattr(us_paypal, "generate_paypal_oaics_trial_experimental", fake_oaics_flow)

    result = us_paypal.generate_paypal_trial(
        us_paypal.PaypalJobConfig(
            access_token="at-test",
            direct_proxies=["proxy.example:1000:user-region-BR-sid-old-t-120:pass"],
            region="BR",
            promo_region="BR",
            apply_promo=True,
            only_oaics=True,
        )
    )

    assert result["ok"] is True
    assert result["fields"]["cs_id"] == "oaics_test"
    assert result["fields"]["ba_token"] == "BA-OAICS"
    assert ("oaics_flow", "oaics_test") in events
    create_body = events[0][2]
    assert create_body["promo_campaign"]["promo_campaign_id"] == "plus-1-month-free"


def test_generate_paypal_trial_frontloads_promo_for_only_oaics_any_country(monkeypatch):
    events: list[tuple[str, object]] = []

    class ChatGPT:
        def post(self, url, **kwargs):
            events.append(("chatgpt_post", url, kwargs.get("json")))
            return Response(
                200,
                {
                    "checkout_session_id": "oaics_nl_test",
                    "processor_entity": "openai_ie",
                    "checkout_url": "https://chatgpt.com/checkout/openai_ie/oaics_nl_test",
                },
            )

        def get(self, *_args, **_kwargs):
            return Response(200, {})

    monkeypatch.setattr(us_paypal, "pix_proxy_context", fake_proxy_context)
    monkeypatch.setattr(us_paypal, "build_chatgpt_session", lambda *_args, **_kwargs: ChatGPT())
    monkeypatch.setattr(us_paypal, "warm_chatgpt_checkout_context", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        us_paypal,
        "build_paypal_dynamic_proxy",
        lambda _cfg, stage, region=None: (f"socks5://proxy-{stage}-{region}", f"sid-{stage}"),
    )
    monkeypatch.setattr(
        us_paypal,
        "generate_paypal_oaics_trial_experimental",
        lambda **kwargs: events.append(("oaics_flow", kwargs["cs_id"])) or {
            "ok": True,
            "amount": "0",
            "fields": {
                "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-OAICS-NL",
                "provider_redirect_url": "https://www.paypal.com/agreements/approve?ba_token=BA-OAICS-NL",
                "ba_token": "BA-OAICS-NL",
                "cs_id": kwargs["cs_id"],
            },
            "billing": {"country": "NL"},
        },
    )

    result = us_paypal.generate_paypal_trial(
        us_paypal.PaypalJobConfig(
            access_token="at-test",
            direct_proxies=["proxy.example:1000:user-region-NL-sid-old-t-120:pass"],
            region="NL",
            promo_region="NL",
            apply_promo=True,
            only_oaics=True,
        )
    )

    assert result["ok"] is True
    create_body = events[0][2]
    assert create_body["promo_campaign"]["promo_campaign_id"] == "plus-1-month-free"


def test_oaics_native_paypal_confirm_blocked_is_not_success(monkeypatch):
    class Http:
        def get(self, url, **kwargs):
            if "backend-api/payments/checkout/" in url:
                return Response(
                    200,
                    {
                        "checkout_session_id": "oaics_blocked",
                        "publishable_key": "pk_live_test",
                        "customer_session_client_secret": "cuss_live_test",
                        "currency": "eur",
                        "total_summary": {"due": 0},
                        "payment_method_types": ["paypal", "link", "card"],
                    },
                )
            if "elements/sessions" in url:
                return Response(200, {"id": "elements_session_test", "config_id": "cfg_test"})
            raise AssertionError(f"unexpected GET {url}")

        def post(self, url, **kwargs):
            if "checkout/taxes" in url:
                return Response(
                    200,
                    {
                        "checkout_session_id": "oaics_blocked",
                        "currency": "eur",
                        "total_summary": {"due": 0},
                        "payment_method_types": ["paypal", "link", "card"],
                        "publishable_key": "pk_live_test",
                        "customer_session_client_secret": "cuss_live_test",
                    },
                )
            if "confirmation_tokens" in url:
                return Response(200, {"id": "ctoken_paypal"})
            if "checkout/confirm" in url:
                return Response(200, {"status": "blocked"})
            raise AssertionError(f"unexpected POST {url}")

    monkeypatch.setattr(us_paypal, "build_stripe_session", lambda *_args, **_kwargs: Http())
    monkeypatch.setattr(us_paypal, "build_chatgpt_session", lambda *_args, **_kwargs: Http())

    with pytest.raises(RuntimeError, match="blocked"):
        us_paypal.generate_paypal_oaics_trial_experimental(
            access_token="at-test",
            cs_id="oaics_blocked",
            processor="openai_ie",
            proxy_url="socks5://proxy.example:1000",
            device_id="device-test",
            billing={
                "name": "Owner",
                "email": "owner@example.com",
                "country": "DE",
                "line1": "Teststrasse 1",
                "city": "Berlin",
                "postal_code": "10117",
            },
            country="DE",
            currency="EUR",
            log=lambda _message: None,
        )


def test_oaics_native_paypal_setup_intent_redirect_resolves_to_ba(monkeypatch):
    events: list[str] = []

    class Http:
        def get(self, url, **kwargs):
            if "backend-api/payments/checkout/" in url:
                events.append("checkout_state")
                return Response(
                    200,
                    {
                        "checkout_session_id": "oaics_success",
                        "publishable_key": "pk_live_test",
                        "customer_session_client_secret": "cuss_live_test",
                        "currency": "eur",
                        "total_summary": {"due": 0},
                        "payment_method_types": ["paypal", "link", "card"],
                    },
                )
            if "elements/sessions" in url:
                events.append("elements")
                return Response(200, {"id": "elements_session_test", "config_id": "cfg_test"})
            if "pm-redirects.stripe.com/authorize/oaics" in url:
                events.append("resolve")
                response = Response(302, {})
                response.headers["Location"] = "https://www.paypal.com/agreements/approve?ba_token=BA-OAICS-SUCCESS"
                return response
            raise AssertionError(f"unexpected GET {url}")

        def post(self, url, **kwargs):
            if "checkout/taxes" in url:
                events.append("taxes")
                return Response(
                    200,
                    {
                        "checkout_session_id": "oaics_success",
                        "currency": "eur",
                        "total_summary": {"due": 0},
                        "payment_method_types": ["paypal", "link", "card"],
                        "publishable_key": "pk_live_test",
                        "customer_session_client_secret": "cuss_live_test",
                    },
                )
            if "confirmation_tokens" in url:
                events.append("ctoken")
                return Response(200, {"id": "ctoken_paypal"})
            if "checkout/confirm" in url:
                events.append("openai_confirm")
                return Response(
                    200,
                    {
                        "status": "success",
                        "type": "setup_intent",
                        "client_secret": "seti_oaics_secret_value",
                        "confirm_return_url": "https://chatgpt.com/checkout/verify?stripe_session_id=oaics_success",
                    },
                )
            if "setup_intents/seti_oaics/confirm" in url:
                events.append("intent_confirm")
                return Response(
                    200,
                    {
                        "status": "requires_action",
                        "next_action": {
                            "redirect_to_url": {
                                "url": "https://pm-redirects.stripe.com/authorize/oaics"
                            }
                        },
                    },
                )
            raise AssertionError(f"unexpected POST {url}")

    monkeypatch.setattr(us_paypal, "build_stripe_session", lambda *_args, **_kwargs: Http())
    monkeypatch.setattr(us_paypal, "build_chatgpt_session", lambda *_args, **_kwargs: Http())

    result = us_paypal.generate_paypal_oaics_trial_experimental(
        access_token="at-test",
        cs_id="oaics_success",
        processor="openai_ie",
        proxy_url="socks5://proxy.example:1000",
        device_id="device-test",
        billing={
            "name": "Owner",
            "email": "owner@example.com",
            "country": "DE",
            "line1": "Teststrasse 1",
            "city": "Berlin",
            "postal_code": "10117",
        },
        country="DE",
        currency="EUR",
        log=lambda _message: None,
    )

    assert result["ok"] is True
    assert result["fields"]["cs_id"] == "oaics_success"
    assert result["fields"]["ba_token"] == "BA-OAICS-SUCCESS"
    assert result["fields"]["link_source"] == "oaics_standard_paypal_intent_confirm"
    assert result["fields"]["link_binding"] == "chatgpt_oaics_checkout_session"
    assert events == [
        "checkout_state",
        "taxes",
        "elements",
        "ctoken",
        "openai_confirm",
        "intent_confirm",
        "resolve",
    ]


def test_oaics_custom_payment_methods_sorts_paypal_first():
    methods = us_paypal.oaics_custom_payment_methods(
        {
            "custom_payment_methods": [
                {"id": "cpmt_card_like", "name": "Other"},
                {"id": "cpmt_paypal", "name": "PayPal"},
            ]
        }
    )

    assert [item["id"] for item in methods] == ["cpmt_paypal", "cpmt_card_like"]


def test_oaics_confirmation_token_uses_single_stripe_version_channel():
    captured = {}

    class Http:
        def post(self, _url, **kwargs):
            captured.update(kwargs)
            return Response(200, {"id": "ctoken_test"})

    token = us_paypal.create_oaics_paypal_confirmation_token(
        Http(),
        {
            "_oaics_publishable_key": "pk_live_test",
            "_oaics_payment_method_types": ["paypal", "link", "card"],
            "id": "elements_session_test",
            "config_id": "cfg_test",
        },
        billing={
            "name": "Owner",
            "email": "owner@example.com",
            "country": "DE",
            "line1": "Teststrasse 1",
            "city": "Berlin",
            "postal_code": "10117",
        },
        currency="EUR",
    )

    assert token == "ctoken_test"
    assert captured["headers"]["Stripe-Version"] == us_paypal.PAYPAL_STRIPE_VERSION
    assert "_stripe_version" not in captured["data"]


def test_oaics_custom_payment_method_fallback_returns_ba(monkeypatch):
    events: list[str] = []

    class Http:
        def get(self, url, **kwargs):
            if "backend-api/payments/checkout/" in url:
                events.append("checkout_state")
                return Response(
                    200,
                    {
                        "checkout_session_id": "oaics_cpmt",
                        "currency": "eur",
                        "total_summary": {"due": 0},
                        "payment_method_types": [],
                        "custom_payment_methods": [
                            {"id": "cpmt_other", "name": "Other"},
                            {"id": "cpmt_paypal", "name": "PayPal"},
                        ],
                    },
                )
            raise AssertionError(f"unexpected GET {url}")

        def post(self, url, **kwargs):
            if "checkout/taxes" in url:
                events.append("taxes")
                return Response(
                    200,
                    {
                        "checkout_session_id": "oaics_cpmt",
                        "currency": "eur",
                        "total_summary": {"due": 0},
                        "payment_method_types": [],
                        "custom_payment_methods": [
                            {"id": "cpmt_other", "name": "Other"},
                            {"id": "cpmt_paypal", "name": "PayPal"},
                        ],
                    },
                )
            if "checkout/confirm" in url:
                events.append("cpmt_confirm")
                assert kwargs["json"]["selected_payment_method_type"] == "cpmt_paypal"
                return Response(200, {"status": "success"})
            if "custom_payment_method/start" in url:
                events.append("cpmt_start")
                assert kwargs["json"]["custom_payment_method_type_id"] == "cpmt_paypal"
                return Response(
                    200,
                    {
                        "status": "requires_action",
                        "next_action": {
                            "paymentMethodType": "paypal",
                            "url": "https://www.paypal.com/agreements/approve?ba_token=BA-OAICS-CPMT",
                        },
                    },
                )
            raise AssertionError(f"unexpected POST {url}")

    monkeypatch.setattr(us_paypal, "build_stripe_session", lambda *_args, **_kwargs: Http())
    monkeypatch.setattr(us_paypal, "build_chatgpt_session", lambda *_args, **_kwargs: Http())

    result = us_paypal.generate_paypal_oaics_trial_experimental(
        access_token="at-test",
        cs_id="oaics_cpmt",
        processor="openai_ie",
        proxy_url="socks5://proxy.example:1000",
        device_id="device-test",
        billing={
            "name": "Owner",
            "email": "owner@example.com",
            "country": "DE",
            "line1": "Teststrasse 1",
            "city": "Berlin",
            "postal_code": "10117",
        },
        country="DE",
        currency="EUR",
        log=lambda _message: None,
    )

    assert result["ok"] is True
    assert result["fields"]["ba_token"] == "BA-OAICS-CPMT"
    assert result["fields"]["link_source"] == "oaics_custom_payment_method_start"
    assert events == ["checkout_state", "taxes", "cpmt_confirm", "cpmt_start"]
