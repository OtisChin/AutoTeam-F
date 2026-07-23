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
