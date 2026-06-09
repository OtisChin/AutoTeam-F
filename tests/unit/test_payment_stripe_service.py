from autotoken.services import payment_stripe


def test_extract_checkout_session_id_from_payload_or_url():
    assert payment_stripe.extract_checkout_session_id(raw={"checkout_session_id": "cs_test_123"}) == "cs_test_123"
    assert payment_stripe.extract_checkout_session_id(raw={"session_id": "cs_session_456"}) == "cs_session_456"
    assert payment_stripe.extract_checkout_session_id(raw={"id": "not_checkout"}) == ""
    assert (
        payment_stripe.extract_checkout_session_id("https://chatgpt.com/checkout/openai_llc/cs_live_abc")
        == "cs_live_abc"
    )
    assert (
        payment_stripe.extract_checkout_session_id("https://pay.openai.com/c/pay/cs_live_a1Hosted123#fid=test")
        == "cs_live_a1Hosted123"
    )


def test_stripe_runtime_from_env_uses_defaults_and_overrides(monkeypatch):
    monkeypatch.delenv("GOPAY_STRIPE_RUNTIME_VERSION", raising=False)
    monkeypatch.delenv("GOPAY_STRIPE_JS_CHECKSUM", raising=False)
    monkeypatch.delenv("GOPAY_STRIPE_RV_TIMESTAMP", raising=False)

    assert payment_stripe.stripe_runtime_from_env() == {
        "version": payment_stripe.DEFAULT_STRIPE_RUNTIME_VERSION,
        "js_checksum": "",
        "rv_timestamp": "",
    }

    monkeypatch.setenv("GOPAY_STRIPE_RUNTIME_VERSION", "runtime-v")
    monkeypatch.setenv("GOPAY_STRIPE_JS_CHECKSUM", "checksum")
    monkeypatch.setenv("GOPAY_STRIPE_RV_TIMESTAMP", "timestamp")

    assert payment_stripe.stripe_runtime_from_env() == {
        "version": "runtime-v",
        "js_checksum": "checksum",
        "rv_timestamp": "timestamp",
    }
