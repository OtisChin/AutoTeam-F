from autotoken.payments import brazil_pix


class _JsonResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


class _ProxyContext:
    def __init__(self, url):
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_generate_pix_trial_creates_checkout_with_promo_campaign(monkeypatch):
    calls = []

    class FakeChatgptSession:
        def post(self, url, **kwargs):
            calls.append(("chatgpt_post", url, kwargs.get("json")))
            assert not url.endswith("/checkout/update")
            return _JsonResponse({
                "checkout_session_id": "cs_test",
                "processor_entity": "openai_llc",
                "public_key": "pk_test",
            })

    class FakeStripeSession:
        def post(self, url, **kwargs):
            calls.append(("stripe_post", url, kwargs.get("data")))
            if url.endswith("/payment_methods"):
                return _JsonResponse({"id": "pm_pix_test"})
            if url.endswith("/confirm"):
                return _JsonResponse({
                    "submission_attempt": {"state": "succeeded"},
                    "next_action": {
                        "pix_display_qr_code": {
                            "data": "000201PIXTEST",
                            "hosted_instructions_url": "https://payments.stripe.com/qr/instructions/pix_test",
                        },
                    },
                })
            raise AssertionError(f"unexpected stripe post {url}")

    init_payloads = iter([
        {
            "total_summary": {"due": 0},
            "payment_method_types": ["card", "pix"],
            "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_test",
            "config_id": "cfg_test",
            "init_checksum": "chk_test",
        },
    ])

    monkeypatch.setattr(brazil_pix, "pix_proxy_context", lambda local, dynamic, log: _ProxyContext(dynamic))
    monkeypatch.setattr(brazil_pix, "build_chatgpt_session", lambda *args, **kwargs: FakeChatgptSession())
    monkeypatch.setattr(brazil_pix, "build_stripe_session", lambda *args, **kwargs: FakeStripeSession())
    monkeypatch.setattr(brazil_pix, "stripe_init", lambda *args, **kwargs: next(init_payloads))
    monkeypatch.setattr(brazil_pix, "chatgpt_approve", lambda *args, **kwargs: None)
    monkeypatch.setattr(brazil_pix.time, "sleep", lambda _seconds: None)

    result = brazil_pix.generate_pix_trial(brazil_pix.PixJobConfig(access_token="token", direct_proxies=["proxy"]))

    create_payload = next(payload for kind, url, payload in calls if kind == "chatgpt_post" and url.endswith("/checkout"))
    payment_method_payload = next(payload for kind, url, payload in calls if kind == "stripe_post" and url.endswith("/payment_methods"))

    assert create_payload["promo_campaign"]["promo_campaign_id"] == "plus-1-month-free"
    assert create_payload["promo_campaign"]["is_coupon_from_query_param"] is False
    assert payment_method_payload["type"] == "pix"
    assert result["ok"] is True
    assert result["amount"] == "0"
    assert result["fields"]["hosted_instructions_url"] == "https://payments.stripe.com/qr/instructions/pix_test"



def test_pix_proxy_rewrites_711_session_region_and_sid():
    raw = "global.rotgb.711proxy.com:10000:USER-zone-custom-region-IN-session-abc123-sessTime-120:pass"

    proxy, sid = brazil_pix.pix_proxy_with_fresh_sid(brazil_pix.normalize_pix_proxy_url(raw), "BR")

    assert sid != "static"
    assert "custom-region-BR-session-" in proxy
    assert "custom-region-IN-session-abc123" not in proxy


def test_pix_proxy_injects_711_session_when_missing():
    raw = "global.rotgb.711proxy.com:10000:USER105777-zone-custom-region-US:pass"

    proxy, sid = brazil_pix.pix_proxy_with_fresh_sid(brazil_pix.normalize_pix_proxy_url(raw), "BR")

    assert sid != "static"
    assert "custom-region-BR-session-" in proxy
    assert "custom-region-US" not in proxy


def test_generate_pix_trial_retries_paypal_style_stripe_init_when_promo_init_has_no_pix(monkeypatch):
    calls = []

    class FakeChatgptSession:
        def post(self, url, **kwargs):
            calls.append(("chatgpt_post", url, kwargs.get("json")))
            assert not url.endswith("/checkout/update")
            return _JsonResponse({
                "checkout_session_id": "cs_test",
                "processor_entity": "openai_llc",
                "public_key": "pk_test",
            })

    class FakeStripeSession:
        def post(self, url, **kwargs):
            calls.append(("stripe_post", url, kwargs.get("data")))
            if url.endswith("/payment_methods"):
                return _JsonResponse({"id": "pm_pix_test"})
            if url.endswith("/confirm"):
                return _JsonResponse({
                    "submission_attempt": {"state": "succeeded"},
                    "next_action": {
                        "pix_display_qr_code": {
                            "data": "000201PIXTEST",
                            "hosted_instructions_url": "https://payments.stripe.com/qr/instructions/pix_test",
                        },
                    },
                })
            raise AssertionError(f"unexpected stripe post {url}")

    init_payloads = iter([
        {"total_summary": {"due": 0}, "payment_method_types": ["card"]},
    ])

    def fake_stripe_init(*args, **kwargs):
        calls.append(("stripe_init", "standard", None))
        return next(init_payloads)

    def fake_paypal_style_stripe_init(*args, **kwargs):
        calls.append(("stripe_init", "paypal_style", None))
        return {
            "total_summary": {"due": 0},
            "payment_method_types": ["card", "pix"],
            "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_test",
            "config_id": "cfg_test",
            "init_checksum": "chk_test",
        }

    monkeypatch.setattr(brazil_pix, "pix_proxy_context", lambda local, dynamic, log: _ProxyContext(dynamic))
    monkeypatch.setattr(brazil_pix, "build_chatgpt_session", lambda *args, **kwargs: FakeChatgptSession())
    monkeypatch.setattr(brazil_pix, "build_stripe_session", lambda *args, **kwargs: FakeStripeSession())
    monkeypatch.setattr(brazil_pix, "stripe_init", fake_stripe_init)
    monkeypatch.setattr(brazil_pix, "paypal_style_stripe_init", fake_paypal_style_stripe_init)
    monkeypatch.setattr(brazil_pix, "chatgpt_approve", lambda *args, **kwargs: None)
    monkeypatch.setattr(brazil_pix.time, "sleep", lambda _seconds: None)

    result = brazil_pix.generate_pix_trial(brazil_pix.PixJobConfig(access_token="token", direct_proxies=["proxy"]))

    assert ("stripe_init", "paypal_style", None) in calls
    assert result["ok"] is True
    assert result["fields"]["hosted_instructions_url"] == "https://payments.stripe.com/qr/instructions/pix_test"
