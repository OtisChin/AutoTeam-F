from __future__ import annotations

from autotoken.payments import gcash_ph


class _JsonResponse:
    def __init__(self, payload=None, status_code=200, text="", headers=None):
        self._payload = payload or {}
        self.status_code = status_code
        self.text = text or str(self._payload)
        self.headers = headers or {}

    def json(self):
        return self._payload


class _StripeSession:
    def __init__(self):
        self.last_post = None
        self.get_calls = []

    def post(self, url, data=None, timeout=None, **kwargs):
        self.last_post = {"url": url, "data": data or {}, "timeout": timeout, "kwargs": kwargs}
        return _JsonResponse({"id": "pm_gcash_test"})

    def get(self, url, allow_redirects=False, timeout=None, **kwargs):
        self.get_calls.append({"url": url, "allow_redirects": allow_redirects, "timeout": timeout, "kwargs": kwargs})
        return _JsonResponse(
            {},
            text='<img src="https://payments.gcash.com/qr/test.png"><script>var qr="gcash://pay?token=test"</script>',
            headers={"Location": "https://payments.gcash.com/pay/test"} if not allow_redirects else {},
        )


def test_extract_gcash_result_accepts_stripe_redirect_and_qr_payload():
    fields = gcash_ph.extract_gcash_result(
        {
            "next_action": {"type": "redirect_to_url", "redirect_to_url": {"url": "https://pm-redirects.stripe.com/authorize/acct/gcash_test"}},
            "payment_intent": {"id": "pi_test", "status": "requires_action"},
            "gcash": {"qrCodeUrl": "https://payments.gcash.com/qr/test.png", "deepLink": "gcash://pay?token=test"},
        },
        "cs_test",
    )

    assert fields["gcash_link"] == ""
    assert fields["stripe_redirect_url"] == "https://pm-redirects.stripe.com/authorize/acct/gcash_test"
    assert fields["gcash_qr_url"] == "https://payments.gcash.com/qr/test.png"
    assert fields["gcash_qr_data"] == "gcash://pay?token=test"
    assert fields["payment_intent"] == "pi_test"


def test_finalize_gcash_result_resolves_provider_and_captures_qr():
    stripe = _StripeSession()
    fields = {"stripe_redirect_url": "https://pm-redirects.stripe.com/authorize/acct/gcash_test"}

    assert gcash_ph.finalize_gcash_result(stripe, fields, link_source="test_source") is True

    assert fields["gcash_link"] == "https://payments.gcash.com/pay/test"
    assert fields["provider_redirect_url"] == "https://payments.gcash.com/pay/test"
    assert fields["stripe_redirect_url"] == "https://pm-redirects.stripe.com/authorize/acct/gcash_test"
    assert fields["gcash_qr_url"] == "https://payments.gcash.com/qr/test.png"
    assert fields["gcash_qr_data"] == "gcash://pay?token=test"
    assert fields["link_source"] == "test_source"


def test_confirm_gcash_inline_posts_gcash_payment_method_type():
    stripe = _StripeSession()
    ctx = {
        "guid": "guid",
        "muid": "muid",
        "sid": "sid",
        "client_session_id": "client-session",
        "config_id": "config",
        "init_checksum": "checksum",
    }
    billing = {"name": "Juan Dela Cruz", "email": "buyer@example.com", "line1": "6819 Ayala Avenue", "city": "Makati", "postal_code": "1226", "state": "Metro Manila"}

    gcash_ph._confirm_gcash_inline(
        stripe,
        cs_id="cs_test",
        stripe_pk="pk_test",
        ctx=ctx,
        billing=billing,
        amount="0",
        return_url="https://chatgpt.com/return",
    )

    assert stripe.last_post["data"]["expected_payment_method_type"] == "gcash"
    assert stripe.last_post["data"]["return_url"] == "https://chatgpt.com/return"


def test_detect_gcash_standard_checkout_requires_zero_amount(monkeypatch):
    class ChatgptSession:
        headers = {}

        def post(self, url, json=None, headers=None, timeout=None):
            if url == "https://chatgpt.com/backend-api/payments/checkout":
                return _JsonResponse({"checkout_session_id": "cs_test", "publishable_key": "pk_test", "processor_entity": "openai_llc"})
            if url == "https://chatgpt.com/backend-api/payments/checkout/update":
                return _JsonResponse({"ok": True})
            raise AssertionError(url)

    monkeypatch.setattr(gcash_ph, "build_gcash_dynamic_proxy", lambda cfg, stage_index: ("socks5h://proxy", "test-sid"))
    monkeypatch.setattr(gcash_ph, "pix_proxy_context", lambda local, dynamic, log: type("ProxyContext", (), {"url": dynamic, "__enter__": lambda self: self, "__exit__": lambda self, *args: False})())
    monkeypatch.setattr(gcash_ph, "build_gcash_chatgpt_session", lambda *args, **kwargs: ChatgptSession())
    monkeypatch.setattr(gcash_ph, "warm_chatgpt_checkout_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(gcash_ph, "build_stripe_session", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        gcash_ph,
        "stripe_init",
        lambda *args, **kwargs: {
            "total_summary": {"due": 1299},
            "currency": "php",
            "payment_method_types": ["card", "gcash"],
            "ordered_payment_method_types": ["card", "gcash"],
        },
    )

    result = gcash_ph.detect_gcash_eligibility(gcash_ph.GCashPhJobConfig(access_token="token", direct_proxies=["proxy"]))

    assert result["has_gcash"] is True
    assert result["amount"] == "1299"
    assert result["status"] == "ineligible"
