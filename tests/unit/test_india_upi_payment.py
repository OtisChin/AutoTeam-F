from __future__ import annotations

import pytest

from autotoken.payments import india_upi


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


def test_extract_upi_result_reads_hosted_instruction_and_qr_fields():
    payload = {
        "payment_intent": {
            "id": "pi_test",
            "next_action": {
                "type": "upi_handle_redirect_or_display_qr_code",
                "upi_handle_redirect_or_display_qr_code": {
                    "hosted_instructions_url": "https://payments.stripe.com/upi/instructions/test_token",
                    "qr_code": {
                        "image_url_png": "https://payments.stripe.com/qr/test.png",
                        "image_url_svg": "https://payments.stripe.com/qr/test.svg",
                        "expires_at": 123,
                    },
                },
            },
        },
        "submission_attempt": {"state": "processing"},
    }

    fields = india_upi.extract_upi_result(payload, "cs_test")

    assert fields["upi_link"] == "https://payments.stripe.com/upi/instructions/test_token"
    assert fields["hosted_instructions_url"] == "https://payments.stripe.com/upi/instructions/test_token"
    assert fields["qr_image_url_png"] == "https://payments.stripe.com/qr/test.png"
    assert fields["qr_image_url_svg"] == "https://payments.stripe.com/qr/test.svg"
    assert fields["qr_expires_at"] == "123"
    assert fields["payment_intent"] == "pi_test"
    assert fields["submission_state"] == "processing"
    assert india_upi.is_success(fields) is True


def test_generate_upi_trial_approves_requires_approval_before_polling(monkeypatch):
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

    monkeypatch.setattr(india_upi, "pix_proxy_context", lambda local, dynamic, log: _ProxyContext(dynamic))
    monkeypatch.setattr(india_upi, "build_chatgpt_session", lambda *args, **kwargs: FakeChatgptSession())
    monkeypatch.setattr(india_upi, "build_stripe_session", lambda *args, **kwargs: object())
    monkeypatch.setattr(india_upi, "stripe_init", lambda *args, **kwargs: {
        "total_summary": {"due": 199900},
        "payment_method_types": ["card", "upi"],
        "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_test",
    })
    monkeypatch.setattr(india_upi, "_create_upi_payment_method", lambda *args, **kwargs: "pm_test")

    def fake_confirm(*args, **kwargs):
        captured["return_url"] = kwargs["return_url"]
        return {"submission_attempt": {"state": "requires_approval"}}

    monkeypatch.setattr(india_upi, "_confirm_upi", fake_confirm)

    def fake_approve(*args, **kwargs):
        calls.append(("approve", args[1]))

    monkeypatch.setattr(india_upi, "chatgpt_approve", fake_approve)
    monkeypatch.setattr(india_upi, "page_get", lambda *args, **kwargs: {
        "payment_intent": {
            "next_action": {
                "type": "upi_handle_redirect_or_display_qr_code",
                "upi_handle_redirect_or_display_qr_code": {
                    "hosted_instructions_url": "https://payments.stripe.com/upi/instructions/after_approve",
                },
            },
        },
        "submission_attempt": {"state": "processing"},
    })

    result = india_upi.generate_upi_trial(india_upi.UpiJobConfig(access_token="token", direct_proxies=["proxy"]))

    assert ("approve", "cs_test") in calls
    assert captured["return_url"] == "https://pay.openai.com/c/pay/cs_test"
    assert result["fields"]["upi_link"] == "https://payments.stripe.com/upi/instructions/after_approve"
    assert result["fields"]["amount"] == "199900"
    assert result["billing"]["country"] == "IN"


def test_generate_upi_trial_stops_when_promo_keeps_non_zero_amount(monkeypatch):
    class FakeChatgptSession:
        def post(self, url, **kwargs):
            return _JsonResponse({
                "checkout_session_id": "cs_test",
                "processor_entity": "openai_llc",
                "public_key": "pk_test",
            })

    monkeypatch.setattr(india_upi, "pix_proxy_context", lambda local, dynamic, log: _ProxyContext(dynamic))
    monkeypatch.setattr(india_upi, "build_chatgpt_session", lambda *args, **kwargs: FakeChatgptSession())
    monkeypatch.setattr(india_upi, "build_stripe_session", lambda *args, **kwargs: object())
    monkeypatch.setattr(india_upi, "stripe_init", lambda *args, **kwargs: {
        "total_summary": {"due": 199900},
        "payment_method_types": ["card", "upi"],
    })
    monkeypatch.setattr(india_upi, "_create_upi_payment_method", lambda *args, **kwargs: pytest.fail("should not create UPI pm"))

    with pytest.raises(RuntimeError, match="套 promo 后金额不是 0"):
        india_upi.generate_upi_trial(
            india_upi.UpiJobConfig(access_token="token", direct_proxies=["proxy"], apply_promo=True)
        )


def test_generate_upi_trial_uses_local_proxy_chain_when_configured(monkeypatch):
    proxy_context_calls = []
    chatgpt_proxies = []
    stripe_proxies = []

    class FakeChatgptSession:
        def post(self, url, **kwargs):
            return _JsonResponse({
                "checkout_session_id": "cs_test",
                "processor_entity": "openai_llc",
                "public_key": "pk_test",
            })

    def fake_proxy_context(local, dynamic, log):
        proxy_context_calls.append((local, dynamic))
        return _ProxyContext(f"http://chain-{len(proxy_context_calls)}")

    def fake_build_chatgpt_session(token, proxy_url="", device_id=""):
        chatgpt_proxies.append(proxy_url)
        return FakeChatgptSession()

    def fake_build_stripe_session(proxy_url=""):
        stripe_proxies.append(proxy_url)
        return object()

    monkeypatch.setattr(india_upi, "pix_proxy_context", fake_proxy_context)
    monkeypatch.setattr(india_upi, "build_chatgpt_session", fake_build_chatgpt_session)
    monkeypatch.setattr(india_upi, "build_stripe_session", fake_build_stripe_session)
    monkeypatch.setattr(india_upi, "stripe_init", lambda *args, **kwargs: {
        "total_summary": {"due": 199900},
        "payment_method_types": ["card", "upi"],
        "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_test",
    })
    monkeypatch.setattr(india_upi, "_create_upi_payment_method", lambda *args, **kwargs: "pm_test")
    monkeypatch.setattr(india_upi, "_confirm_upi", lambda *args, **kwargs: {
        "payment_intent": {
            "next_action": {
                "upi_handle_redirect_or_display_qr_code": {
                    "hosted_instructions_url": "https://payments.stripe.com/upi/instructions/direct",
                },
            },
        }
    })

    india_upi.generate_upi_trial(
        india_upi.UpiJobConfig(access_token="token", local_proxy="http://127.0.0.1:7897", direct_proxies=["socks5h://dyn"])
    )

    assert proxy_context_calls[0] == ("http://127.0.0.1:7897", "socks5h://dyn")
    assert proxy_context_calls[1] == ("http://127.0.0.1:7897", "socks5h://dyn")
    assert chatgpt_proxies == ["http://chain-1"]
    assert stripe_proxies == ["http://chain-2"]
