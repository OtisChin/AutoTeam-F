from __future__ import annotations

from fastapi import HTTPException

from autotoken.integrations.gpthel_ideal import app as ideal_app


class DummySession:
    headers: dict[str, str] = {}


class DummyResponse:
    status_code = 200
    text = "<html><title>ChatGPT</title></html>"
    headers = {"content-type": "text/html"}
    url = "https://chatgpt.com/backend-api/payments/checkout"

    def json(self):
        raise ValueError("not json")


class JsonResponse:
    status_code = 200
    text = "{}"
    headers = {"content-type": "application/json"}
    url = "https://chatgpt.com/backend-api/payments/checkout"

    def __init__(self, payload):
        self._payload = payload
        self.text = "{}"

    def json(self):
        return self._payload


def test_create_checkout_turns_html_success_response_into_retryable_http_error(monkeypatch):
    class HtmlSession:
        headers = {}

        def post(self, *_args, **_kwargs):
            return DummyResponse()

    req = ideal_app.LongLinkRequest(accessToken="header.payload.signature", link_type="ideal")
    monkeypatch.setattr(ideal_app, "record_diagnostic", lambda *args, **kwargs: None)

    try:
        ideal_app.create_checkout(req, HtmlSession())
    except HTTPException as exc:
        assert exc.status_code == 502
        assert ideal_app.retryable_transient_error(exc.detail)
        assert "HTML response instead of API JSON" in str(exc.detail)
    else:  # pragma: no cover - explicit assertion path for readability
        raise AssertionError("create_checkout should reject HTML responses")


def test_ideal_create_checkout_does_not_send_promo_campaign(monkeypatch):
    captured: dict[str, object] = {}

    class CaptureSession:
        headers = {}

        def post(self, url, **kwargs):
            captured["url"] = url
            captured["json"] = kwargs.get("json")
            return JsonResponse(
                {
                    "checkout_session_id": "cs_live_no_direct_promo",
                    "processor_entity": "openai_ie",
                    "publishable_key": "pk_live_test",
                }
            )

    monkeypatch.setattr(ideal_app, "record_diagnostic", lambda *args, **kwargs: None)
    req = ideal_app.LongLinkRequest(accessToken="header.payload.signature", link_type="ideal", billing_country="NL")

    checkout = ideal_app.create_checkout(req, CaptureSession())

    assert checkout["cs_id"] == "cs_live_no_direct_promo"
    assert captured["url"] == "https://chatgpt.com/backend-api/payments/checkout"
    assert "promo_campaign" not in captured["json"]
    assert captured["json"]["billing_details"] == {"country": "NL", "currency": "EUR"}


def test_ideal_generate_updates_checkout_promotion_before_stripe_init(monkeypatch):
    calls: list[str] = []

    def fake_create_checkout(req, chatgpt_session=None):
        calls.append("checkout")
        return {
            "cs_id": "cs_live_update_promo",
            "processor_entity": "openai_ie",
            "publishable_key": "pk_live_test",
            "billing_country": "NL",
            "currency": "EUR",
        }

    def fake_update_checkout_promotion(chatgpt, checkout, req, steps=None):
        calls.append("update")
        assert checkout["cs_id"] == "cs_live_update_promo"

    def fake_stripe_init(cs_id, req, proxy_override=""):
        calls.append("init")
        return {
            "stripe_hosted_url": f"https://checkout.stripe.com/c/pay/{cs_id}",
            "total_summary": {"due": 0},
            "payment_method_types": ["card", "ideal"],
        }

    monkeypatch.setattr(ideal_app, "ensure_proxy_region", lambda proxy, *_args, **_kwargs: proxy)
    monkeypatch.setattr(ideal_app, "build_chatgpt_session", lambda req: DummySession())
    monkeypatch.setattr(ideal_app, "create_checkout", fake_create_checkout)
    monkeypatch.setattr(ideal_app, "update_checkout_promotion", fake_update_checkout_promotion, raising=False)
    monkeypatch.setattr(ideal_app, "stripe_init", fake_stripe_init)
    monkeypatch.setattr(
        ideal_app,
        "create_provider_link",
        lambda *args, **kwargs: {
            "payment_method_id": "pm_test",
            "stripe_redirect_url": "https://pm-redirects.stripe.com/test",
            "provider_redirect_url": "https://pay.ideal.nl/test",
            "long_url": "https://pay.ideal.nl/test",
        },
    )

    req = ideal_app.LongLinkRequest(
        accessToken="header.payload.signature",
        proxy="socks5h://user-region-NL-sid-test-t-60:pass@example.test:3010",
        link_type="ideal",
        checkout_proxy_region="NL",
        provider_proxy_region="NL",
    )

    result = ideal_app.generate_long_link_once(req, use_explicit_proxy=True, steps=[])

    assert result.long_url == "https://pay.ideal.nl/test"
    assert calls == ["checkout", "update", "init"]


def test_ideal_checkout_html_retries_next_attempt_with_nl_checkout_proxy(monkeypatch):
    seen_checkout_regions: list[str] = []
    create_calls = 0

    def fake_ensure_proxy_region(proxy, expected_region, stage, steps=None, max_checks=None):
        if str(stage).startswith("checkout"):
            seen_checkout_regions.append(expected_region)
        return ideal_app.proxy_for_region(proxy, expected_region)

    def fake_create_checkout(req, chatgpt_session=None):
        nonlocal create_calls
        create_calls += 1
        if create_calls == 1:
            raise HTTPException(status_code=502, detail="HTML response instead of API JSON; see diagnostics for redacted preview.")
        return {
            "cs_id": "cs_live_retry_nl",
            "processor_entity": "openai_ie",
            "publishable_key": "pk_live_test",
            "billing_country": "NL",
            "currency": "EUR",
        }

    monkeypatch.setattr(ideal_app, "ensure_proxy_region", fake_ensure_proxy_region)
    monkeypatch.setattr(ideal_app, "build_chatgpt_session", lambda req: DummySession())
    monkeypatch.setattr(ideal_app, "create_checkout", fake_create_checkout)
    monkeypatch.setattr(ideal_app, "update_checkout_promotion", lambda *args, **kwargs: None)
    monkeypatch.setattr(ideal_app, "stripe_init", lambda *args, **kwargs: {"stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_live_retry_nl", "total_summary": {"due": 0}})
    monkeypatch.setattr(
        ideal_app,
        "create_provider_link",
        lambda *args, **kwargs: {
            "payment_method_id": "pm_test",
            "stripe_redirect_url": "https://pm-redirects.stripe.com/test",
            "provider_redirect_url": "https://pay.ideal.nl/test",
            "long_url": "https://pay.ideal.nl/test",
        },
    )

    req = ideal_app.LongLinkRequest(
        accessToken="header.payload.signature",
        proxy="socks5h://user-region-JP-sid-test-t-60:pass@example.test:3010",
        link_type="ideal",
        checkout_proxy_region="JP",
        provider_proxy_region="NL",
    )

    result = ideal_app.generate_long_link_once(req, use_explicit_proxy=True, steps=[])

    assert result.long_url == "https://pay.ideal.nl/test"
    assert seen_checkout_regions[:2] == ["JP", "NL"]
    assert create_calls == 2


def test_ideal_rebuilds_checkout_when_zero_amount_init_missing_ideal(monkeypatch):
    create_calls = 0
    init_calls = 0
    seen_provider_cs_ids: list[str] = []

    def fake_create_checkout(req, chatgpt_session=None):
        nonlocal create_calls
        create_calls += 1
        return {
            "cs_id": f"cs_live_methods_{create_calls}",
            "processor_entity": "openai_ie",
            "publishable_key": "pk_live_test",
            "billing_country": "NL",
            "currency": "EUR",
        }

    def fake_stripe_init(cs_id, req, proxy_override=""):
        nonlocal init_calls
        init_calls += 1
        if init_calls == 1:
            return {
                "stripe_hosted_url": f"https://checkout.stripe.com/c/pay/{cs_id}",
                "total_summary": {"due": 0},
                "payment_method_types": ["card", "link"],
                "ordered_payment_method_types": ["card", "link"],
            }
        return {
            "stripe_hosted_url": f"https://checkout.stripe.com/c/pay/{cs_id}",
            "total_summary": {"due": 0},
            "payment_method_types": ["card", "ideal"],
            "ordered_payment_method_types": ["card", "ideal"],
        }

    def fake_create_provider_link(chatgpt, checkout, init_payload, *args, **kwargs):
        seen_provider_cs_ids.append(checkout["cs_id"])
        methods = init_payload["payment_method_types"] + init_payload["ordered_payment_method_types"]
        assert "ideal" in methods
        return {
            "payment_method_id": "pm_test",
            "stripe_redirect_url": "https://pm-redirects.stripe.com/test",
            "provider_redirect_url": "https://pay.ideal.nl/test",
            "long_url": "https://pay.ideal.nl/test",
        }

    monkeypatch.setattr(ideal_app, "CHECKOUT_CREATE_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(ideal_app, "ensure_proxy_region", lambda proxy, *_args, **_kwargs: proxy)
    monkeypatch.setattr(ideal_app, "build_chatgpt_session", lambda req: DummySession())
    monkeypatch.setattr(ideal_app, "create_checkout", fake_create_checkout)
    monkeypatch.setattr(ideal_app, "update_checkout_promotion", lambda *args, **kwargs: None)
    monkeypatch.setattr(ideal_app, "stripe_init", fake_stripe_init)
    monkeypatch.setattr(ideal_app, "create_provider_link", fake_create_provider_link)

    req = ideal_app.LongLinkRequest(
        accessToken="header.payload.signature",
        proxy="socks5h://user-region-NL-sid-test-t-60:pass@example.test:3010",
        link_type="ideal",
        checkout_proxy_region="NL",
        provider_proxy_region="NL",
    )

    result = ideal_app.generate_long_link_once(req, use_explicit_proxy=True, steps=[])

    assert result.long_url == "https://pay.ideal.nl/test"
    assert create_calls == 2
    assert seen_provider_cs_ids == ["cs_live_methods_2"]


def test_ideal_rebuilds_checkout_after_payment_method_types_mismatch(monkeypatch):
    create_calls = 0
    provider_calls = 0

    def fake_create_checkout(req, chatgpt_session=None):
        nonlocal create_calls
        create_calls += 1
        return {
            "cs_id": f"cs_live_confirm_{create_calls}",
            "processor_entity": "openai_ie",
            "publishable_key": "pk_live_test",
            "billing_country": "NL",
            "currency": "EUR",
        }

    def fake_create_provider_link(*args, **kwargs):
        nonlocal provider_calls
        provider_calls += 1
        if provider_calls == 1:
            raise HTTPException(
                status_code=400,
                detail=(
                    'stripe confirm failed: {"error":{"code":"checkout_confirm_error",'
                    '"extra_fields":{"payment_method_type":"ideal",'
                    '"confirm_error_reason":"payment_method_types_mismatch"}}}'
                ),
            )
        return {
            "payment_method_id": "pm_test",
            "stripe_redirect_url": "https://pm-redirects.stripe.com/test",
            "provider_redirect_url": "https://pay.ideal.nl/test",
            "long_url": "https://pay.ideal.nl/test",
        }

    monkeypatch.setattr(ideal_app, "CHECKOUT_CREATE_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(ideal_app, "ensure_proxy_region", lambda proxy, *_args, **_kwargs: proxy)
    monkeypatch.setattr(ideal_app, "build_chatgpt_session", lambda req: DummySession())
    monkeypatch.setattr(ideal_app, "create_checkout", fake_create_checkout)
    monkeypatch.setattr(ideal_app, "update_checkout_promotion", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        ideal_app,
        "stripe_init",
        lambda cs_id, req, proxy_override="": {
            "stripe_hosted_url": f"https://checkout.stripe.com/c/pay/{cs_id}",
            "total_summary": {"due": 0},
            "payment_method_types": ["card", "ideal"],
        },
    )
    monkeypatch.setattr(ideal_app, "create_provider_link", fake_create_provider_link)

    req = ideal_app.LongLinkRequest(
        accessToken="header.payload.signature",
        proxy="socks5h://user-region-NL-sid-test-t-60:pass@example.test:3010",
        link_type="ideal",
        checkout_proxy_region="NL",
        provider_proxy_region="NL",
    )

    result = ideal_app.generate_long_link_once(req, use_explicit_proxy=True, steps=[])

    assert result.long_url == "https://pay.ideal.nl/test"
    assert create_calls == 2
    assert provider_calls == 2
