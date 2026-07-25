from __future__ import annotations

from autotoken.payments import kakao_pay


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


def test_extract_kakao_result_accepts_stripe_and_nicepay_redirects():
    stripe_payload = {
        "next_action": {
            "type": "redirect_to_url",
            "redirect_to_url": {"url": "https://pm-redirects.stripe.com/authorize/acct/test_nonce"},
        },
        "submission_attempt": {"state": "processing"},
    }

    fields = kakao_pay.extract_kakao_result(stripe_payload, "cs_test")

    assert fields["kakao_link"] == "https://pm-redirects.stripe.com/authorize/acct/test_nonce"
    assert fields["stripe_redirect_url"] == fields["kakao_link"]
    assert fields["submission_state"] == "processing"
    assert kakao_pay.is_success(fields) is True

    nicepay_fields = kakao_pay.extract_kakao_result(
        {"next_action": {"type": "redirect_to_url", "redirect_to_url": {"url": "https://pay.nicepay.co.kr/v1/checkout/pay/test"}}},
        "cs_test",
    )

    assert nicepay_fields["kakao_link"] == "https://pay.nicepay.co.kr/v1/checkout/pay/test"
    assert nicepay_fields["provider_redirect_url"] == nicepay_fields["kakao_link"]
    assert kakao_pay.is_success(nicepay_fields) is True


def test_sync_kakao_tax_region_posts_chatgpt_and_stripe_payloads():
    calls = []

    class FakeSession:
        def post(self, url, **kwargs):
            calls.append((url, kwargs))
            return _JsonResponse({"ok": True})

    billing = {
        "name": "Min Kim",
        "email": "min@example.com",
        "line1": "1 Sejong-daero",
        "city": "Seoul",
        "postal_code": "04524",
    }

    kakao_pay.sync_kakao_tax_region(
        FakeSession(),
        FakeSession(),
        cs_id="cs_test",
        stripe_pk="pk_test",
        processor="openai_llc",
        checkout_email="buyer@example.com",
        billing=billing,
    )

    assert calls[0][0] == "https://chatgpt.com/backend-api/payments/checkout/taxes"
    assert calls[0][1]["json"]["billing_country"] == "KR"
    assert calls[0][1]["json"]["currency"] == "KRW"
    assert calls[0][1]["json"]["billing_address"]["postal_code"] == "04524"
    assert calls[1][0] == "https://api.stripe.com/v1/payment_pages/cs_test"
    assert calls[1][1]["data"]["tax_region[country]"] == "KR"
    assert calls[1][1]["data"]["tax_region[postal_code]"] == "04524"
    assert calls[1][1]["data"]["key"] == "pk_test"


def test_generate_kakao_trial_syncs_tax_then_approves_and_polls_redirect(monkeypatch):
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

    monkeypatch.setattr(kakao_pay, "pix_proxy_context", lambda local, dynamic, log: _ProxyContext(dynamic))
    monkeypatch.setattr(kakao_pay, "build_chatgpt_session", lambda *args, **kwargs: FakeChatgptSession())
    monkeypatch.setattr(kakao_pay, "build_stripe_session", lambda *args, **kwargs: object())
    monkeypatch.setattr(kakao_pay, "stripe_init", lambda *args, **kwargs: {
        "total_summary": {"due": 29000},
        "payment_method_types": ["card", "kakao_pay"],
        "ordered_payment_method_types": ["card", "kakao_pay", "naver_pay"],
        "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_test",
        "customer": {"email": "buyer@example.com"},
    })

    def fake_tax_sync(*args, **kwargs):
        calls.append(("tax_sync", kwargs["cs_id"], kwargs["billing"]["country"]))

    monkeypatch.setattr(kakao_pay, "sync_kakao_tax_region", fake_tax_sync)

    def fake_confirm(*args, **kwargs):
        captured["return_url"] = kwargs["return_url"]
        captured["billing"] = kwargs["billing"]
        captured["amount"] = kwargs["amount"]
        return {"submission_attempt": {"state": "requires_approval"}}

    monkeypatch.setattr(kakao_pay, "_confirm_kakao_inline", fake_confirm)
    monkeypatch.setattr(kakao_pay, "chatgpt_approve", lambda *args, **kwargs: calls.append(("approve", args[1], kwargs.get("country"))))
    monkeypatch.setattr(kakao_pay, "page_get", lambda *args, **kwargs: {
        "next_action": {"type": "redirect_to_url", "redirect_to_url": {"url": "https://pm-redirects.stripe.com/authorize/acct/test_nonce"}},
        "submission_attempt": {"state": "processing"},
    })

    result = kakao_pay.generate_kakao_trial(kakao_pay.KakaoPayJobConfig(access_token="token", direct_proxies=["proxy"]))

    assert ("tax_sync", "cs_test", "KR") in calls
    assert ("approve", "cs_test", "KR") in calls
    assert "redirect_pm_type=kakao_pay" in captured["return_url"]
    assert captured["billing"]["country"] == "KR"
    assert captured["amount"] == "29000"
    assert result["fields"]["kakao_link"] == "https://pm-redirects.stripe.com/authorize/acct/test_nonce"
    assert result["fields"]["amount"] == "29000"
    assert result["fields"]["link_source"] == "stripe_checkout_approve_poll"
