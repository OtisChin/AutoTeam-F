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


def test_new_http_session_uses_chrome_impersonation_when_available(monkeypatch):
    created = {}

    class FakeCurlSession:
        def __init__(self, *, impersonate):
            created["impersonate"] = impersonate
            self.trust_env = True
            self.proxies = {}
            self.headers = {}

    monkeypatch.setattr(india_upi, "CurlCffiSession", FakeCurlSession, raising=False)

    session = india_upi.new_http_session("socks5h://user:pass@proxy.example:1000")

    assert created["impersonate"].startswith("chrome")
    assert session.trust_env is False
    assert session.proxies["https"] == "socks5h://user:pass@proxy.example:1000"


@pytest.fixture(autouse=True)
def _noop_tax_sync(monkeypatch, request):
    if request.node.name == "test_sync_upi_tax_region_posts_chatgpt_and_stripe_payloads":
        return
    monkeypatch.setattr(india_upi, "sync_upi_tax_region", lambda *args, **kwargs: None)


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


def test_extract_upi_result_uses_intent_status_not_unrelated_checkout_status():
    payload = {
        "status": "open",
        "tax_meta": {"status": "complete"},
        "setup_intent": {
            "id": "seti_test",
            "status": "requires_action",
            "client_secret": "seti_test_secret_123",
            "next_action": {
                "type": "upi_handle_redirect_or_display_qr_code",
                "upi_handle_redirect_or_display_qr_code": {
                    "hosted_instructions_url": "https://payments.stripe.com/upi/instructions/actionable",
                },
            },
        },
        "submission_attempt": {"state": "processing"},
    }

    fields = india_upi.extract_upi_result(payload, "cs_test")

    assert fields["payment_intent"] == "seti_test"
    assert fields["intent_state"] == "requires_action"
    assert fields["upi_link"] == "https://payments.stripe.com/upi/instructions/actionable"
    assert india_upi.is_success(fields) is True


def test_extract_upi_result_rejects_non_actionable_payment_intent_link():
    payload = {
        "payment_intent": {
            "id": "pi_requires_pm",
            "status": "requires_payment_method",
            "next_action": None,
        },
        "hosted_instructions_url": "https://payments.stripe.com/upi/instructions/stale_token",
        "submission_attempt": {"state": "failed"},
    }

    fields = india_upi.extract_upi_result(payload, "cs_test")

    assert fields["hosted_instructions_url"] == ""
    assert fields["upi_link"] == ""
    assert fields["payment_intent"] == "pi_requires_pm"
    assert fields["intent_state"] == "requires_payment_method"
    assert fields["submission_state"] == "failed"
    assert india_upi.is_success(fields) is False


def test_sync_upi_tax_region_posts_chatgpt_and_stripe_payloads():
    calls = []

    class FakeSession:
        def post(self, url, **kwargs):
            calls.append((url, kwargs))
            return _JsonResponse({"ok": True})

    billing = {
        "name": "Raj Kumar",
        "email": "raj@example.com",
        "line1": "123 MG Road",
        "city": "Mumbai",
        "state": "MH",
        "postal_code": "400001",
    }

    india_upi.sync_upi_tax_region(
        FakeSession(),
        FakeSession(),
        cs_id="cs_test",
        stripe_pk="pk_test",
        processor="openai_llc",
        checkout_email="buyer@example.com",
        billing=billing,
    )

    assert calls[0][0] == "https://chatgpt.com/backend-api/payments/checkout/taxes"
    assert calls[0][1]["json"]["checkout_session_id"] == "cs_test"
    assert calls[0][1]["json"]["checkout_email"] == "buyer@example.com"
    assert calls[0][1]["json"]["billing_address"]["country"] == "IN"
    assert calls[0][1]["headers"]["x-openai-target-path"] == "/backend-api/payments/checkout/taxes"
    assert calls[1][0] == "https://api.stripe.com/v1/payment_pages/cs_test"
    assert calls[1][1]["data"]["tax_region[country]"] == "IN"
    assert calls[1][1]["data"]["tax_region[postal_code]"] == "400001"
    assert calls[1][1]["data"]["key"] == "pk_test"


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
            "id": "pi_after_approve",
            "status": "requires_action",
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


def test_chatgpt_approve_rejects_blocked_result(monkeypatch):
    calls = []

    class FakeChatgptSession:
        def post(self, url, **kwargs):
            calls.append(url)
            if url.endswith("/backend-api/sentinel/ping"):
                return _JsonResponse({})
            return _JsonResponse({"result": "blocked"})

    monkeypatch.setattr(india_upi, "build_chatgpt_session", lambda *args, **kwargs: FakeChatgptSession())
    monkeypatch.setattr(india_upi.time, "sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="blocked"):
        india_upi.chatgpt_approve("token", "cs_test", "openai_llc", "proxy", "device", lambda _message: None)

    assert sum(url.endswith("/backend-api/sentinel/ping") for url in calls) == 3
    assert sum(url.endswith("/backend-api/payments/checkout/approve") for url in calls) == 3


def test_chatgpt_approve_refreshes_proxy_sid_between_blocked_retries(monkeypatch):
    proxies = []

    class FakeChatgptSession:
        def post(self, url, **kwargs):
            return _JsonResponse({"result": "blocked"})

    def fake_build_chatgpt_session(_token, proxy_url="", _device_id=""):
        proxies.append(proxy_url)
        return FakeChatgptSession()

    monkeypatch.setattr(india_upi, "build_chatgpt_session", fake_build_chatgpt_session)
    monkeypatch.setattr(india_upi.time, "sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="blocked"):
        india_upi.chatgpt_approve(
            "token",
            "cs_test",
            "openai_llc",
            "socks5h://user:pass@gate.example:10000?session=old",
            "device",
            lambda _message: None,
        )

    assert len(proxies) == 3
    assert proxies[0].endswith("session=old")
    assert proxies[1] != proxies[0]
    assert proxies[2] != proxies[0]
    assert "session=old" not in proxies[1]
    assert "session=old" not in proxies[2]


def test_build_upi_dynamic_proxy_rewrites_direct_proxy_region_for_promo():
    cfg = india_upi.UpiJobConfig(
        access_token="token",
        direct_proxies=["http://user:pass-IN-oldsid@gate.kookeey.info:1000"],
        region="IN",
    )

    proxy, sid = india_upi.build_upi_dynamic_proxy(cfg, 1, "VN")

    assert "-VN-" in proxy
    assert "-IN-" not in proxy
    assert sid and sid != "static"


def test_build_upi_dynamic_proxy_rewrites_711_region_for_promo():
    cfg = india_upi.UpiJobConfig(
        access_token="token",
        direct_proxies=["global.rotgb.711proxy.com:10000:USER105777-zone-custom-region-IN:d74d61"],
        region="IN",
    )

    proxy, sid = india_upi.build_upi_dynamic_proxy(cfg, 1, "VN")

    assert "region-VN" in proxy
    assert "region-IN" not in proxy
    assert "-session-" in proxy
    assert "-sessTime-180-sessAuto-1" in proxy
    assert proxy.startswith("socks5h://")
    assert sid and sid != "static"


def test_build_upi_dynamic_proxy_injects_session_for_short_711_on_every_attempt():
    cfg = india_upi.UpiJobConfig(
        access_token="token",
        direct_proxies=["global.rotgb.711proxy.com:10000:USER105777-zone-custom-region-IN:d74d61"],
        region="IN",
    )

    first_proxy, first_sid = india_upi.build_upi_dynamic_proxy(cfg, 0, "IN")
    second_proxy, second_sid = india_upi.build_upi_dynamic_proxy(cfg, 0, "IN")
    first_value = first_sid.rsplit("sid=", 1)[-1]
    second_value = second_sid.rsplit("sid=", 1)[-1]

    assert first_sid != second_sid
    assert first_proxy != second_proxy
    assert f"-session-{first_value}-" in first_proxy
    assert f"-session-{second_value}-" in second_proxy
    assert "region-IN" in first_proxy


def test_build_upi_dynamic_proxy_refreshes_711_session_for_promo():
    cfg = india_upi.UpiJobConfig(
        access_token="token",
        direct_proxies=[
            "global.rotgb.711proxy.com:10000:"
            "USER105777-zone-custom-region-IN-session-90442815-sessTime-180-sessAuto-1:d74d61"
        ],
        region="IN",
    )

    proxy, sid = india_upi.build_upi_dynamic_proxy(cfg, 1, "VN")

    assert "region-VN" in proxy
    assert "region-IN" not in proxy
    assert "session-90442815" not in proxy
    assert "session-" in proxy
    assert proxy.startswith("socks5h://")
    assert sid and sid != "static"


def test_build_upi_dynamic_proxy_rewrites_arxlabs_region_for_promo():
    cfg = india_upi.UpiJobConfig(
        access_token="token",
        direct_proxies=["us.arxlabs.io:3010:hyrj1177789-region-IN-sid-3uhM836v-t-5:smhwqe9f"],
        region="IN",
    )

    proxy, sid = india_upi.build_upi_dynamic_proxy(cfg, 1, "VN")

    assert "region-VN" in proxy
    assert "region-IN" not in proxy
    assert "sid-3uhM836v-t-5" not in proxy
    assert proxy.startswith("socks5h://")
    assert sid and sid != "static"


def test_generate_upi_trial_uses_vn_proxy_for_promo_update(monkeypatch):
    dynamic_proxies = []
    update_payloads = []

    class FakeChatgptSession:
        def post(self, url, **kwargs):
            if url.endswith("/payments/checkout"):
                return _JsonResponse({
                    "checkout_session_id": "cs_test",
                    "processor_entity": "openai_llc",
                    "public_key": "pk_test",
                })
            if url.endswith("/payments/checkout/update"):
                update_payloads.append(kwargs.get("json") or {})
                return _JsonResponse({"success": True})
            raise AssertionError(url)

    def fake_proxy_context(local, dynamic, log):
        dynamic_proxies.append(dynamic)
        return _ProxyContext(dynamic)

    def fake_stripe_init(*args, **kwargs):
        return {
            "total_summary": {"due": 0},
            "payment_method_types": ["card", "upi"],
            "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_test",
        }

    monkeypatch.setattr(india_upi, "pix_proxy_context", fake_proxy_context)
    monkeypatch.setattr(india_upi, "build_chatgpt_session", lambda *args, **kwargs: FakeChatgptSession())
    monkeypatch.setattr(india_upi, "build_stripe_session", lambda *args, **kwargs: object())
    monkeypatch.setattr(india_upi, "stripe_init", fake_stripe_init)
    monkeypatch.setattr(india_upi.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(india_upi, "_create_upi_payment_method", lambda *args, **kwargs: "pm_test")
    monkeypatch.setattr(india_upi, "_confirm_upi", lambda *args, **kwargs: {
        "payment_intent": {
            "id": "pi_test",
            "status": "requires_action",
            "next_action": {
                "type": "upi_handle_redirect_or_display_qr_code",
                "upi_handle_redirect_or_display_qr_code": {
                    "hosted_instructions_url": "https://payments.stripe.com/upi/instructions/vn-promo",
                },
            },
        }
    })

    india_upi.generate_upi_trial(
        india_upi.UpiJobConfig(
            access_token="token",
            kookeey_user="user",
            kookeey_pass="pass",
            kookeey_endpoint="gate.kookeey.info:1000",
            region="IN",
            apply_promo=True,
        )
    )

    assert "-IN-" in dynamic_proxies[0]
    assert "-VN-" in dynamic_proxies[1]
    assert "-IN-" in dynamic_proxies[2]
    assert update_payloads[0]["billing_details"] == {"country": "VN", "currency": "VND"}


def test_generate_upi_trial_warms_chatgpt_context_before_checkout(monkeypatch):
    calls = []

    class FakeChatgptSession:
        def get(self, url, **kwargs):
            calls.append(("get", url))
            return _JsonResponse({})

        def post(self, url, **kwargs):
            calls.append(("post", url))
            if url.endswith("/payments/checkout"):
                return _JsonResponse({
                    "checkout_session_id": "cs_test",
                    "processor_entity": "openai_llc",
                    "public_key": "pk_test",
                })
            raise AssertionError(url)

    monkeypatch.setattr(india_upi, "pix_proxy_context", lambda local, dynamic, log: _ProxyContext(dynamic))
    monkeypatch.setattr(india_upi, "build_chatgpt_session", lambda *args, **kwargs: FakeChatgptSession())
    monkeypatch.setattr(india_upi, "build_stripe_session", lambda *args, **kwargs: object())
    monkeypatch.setattr(india_upi, "stripe_init", lambda *args, **kwargs: {
        "total_summary": {"due": 199900},
        "payment_method_types": ["card", "upi"],
        "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_test",
    })
    monkeypatch.setattr(india_upi, "_create_upi_payment_method", lambda *args, **kwargs: "pm_test")
    monkeypatch.setattr(india_upi, "_confirm_upi", lambda *args, **kwargs: {
        "payment_intent": {
            "id": "pi_test",
            "next_action": {
                "type": "upi_handle_redirect_or_display_qr_code",
                "upi_handle_redirect_or_display_qr_code": {
                    "hosted_instructions_url": "https://payments.stripe.com/upi/instructions/warm",
                },
            },
        }
    })

    india_upi.generate_upi_trial(india_upi.UpiJobConfig(access_token="token", direct_proxies=["proxy"], apply_promo=False))

    checkout_index = calls.index(("post", "https://chatgpt.com/backend-api/payments/checkout"))
    assert any(kind == "get" and "/backend-api/checkout_pricing_config/configs/IN" in url for kind, url in calls[:checkout_index])
    assert any(kind == "get" and "/backend-api/accounts/check/" in url for kind, url in calls[:checkout_index])


def test_generate_upi_trial_warms_stripe_before_applying_promo(monkeypatch):
    calls = []

    class FakeChatgptSession:
        def post(self, url, **kwargs):
            if url.endswith("/payments/checkout"):
                calls.append("checkout")
                return _JsonResponse({
                    "checkout_session_id": "cs_test",
                    "processor_entity": "openai_llc",
                    "public_key": "pk_test",
                })
            if url.endswith("/payments/checkout/update"):
                calls.append("promo_update")
                return _JsonResponse({"success": True})
            raise AssertionError(url)

    def fake_stripe_init(*args, **kwargs):
        calls.append("stripe_init")
        amount = 199900 if calls.count("stripe_init") == 1 else 0
        return {
            "total_summary": {"due": amount},
            "payment_method_types": ["card", "upi"],
            "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_test",
        }

    monkeypatch.setattr(india_upi, "pix_proxy_context", lambda local, dynamic, log: _ProxyContext(dynamic))
    monkeypatch.setattr(india_upi, "build_chatgpt_session", lambda *args, **kwargs: FakeChatgptSession())
    monkeypatch.setattr(india_upi, "build_stripe_session", lambda *args, **kwargs: object())
    monkeypatch.setattr(india_upi, "stripe_init", fake_stripe_init)
    monkeypatch.setattr(india_upi, "_create_upi_payment_method", lambda *args, **kwargs: "pm_test")
    monkeypatch.setattr(india_upi, "_confirm_upi", lambda *args, **kwargs: {
        "payment_intent": {
            "id": "pi_test",
            "status": "requires_action",
            "next_action": {
                "type": "upi_handle_redirect_or_display_qr_code",
                "upi_handle_redirect_or_display_qr_code": {
                    "hosted_instructions_url": "https://payments.stripe.com/upi/instructions/promo",
                },
            },
        }
    })

    result = india_upi.generate_upi_trial(
        india_upi.UpiJobConfig(access_token="token", direct_proxies=["proxy"], apply_promo=True)
    )

    assert calls[:4] == ["checkout", "stripe_init", "promo_update", "stripe_init"]
    assert result["amount"] == "0"
    assert result["fields"]["upi_link"] == "https://payments.stripe.com/upi/instructions/promo"


def test_generate_upi_trial_retries_post_promo_init_until_amount_zero(monkeypatch):
    calls = []
    sleep_calls = []

    class FakeChatgptSession:
        def post(self, url, **kwargs):
            if url.endswith("/payments/checkout"):
                calls.append("checkout")
                return _JsonResponse({
                    "checkout_session_id": "cs_test",
                    "processor_entity": "openai_llc",
                    "public_key": "pk_test",
                })
            if url.endswith("/payments/checkout/update"):
                calls.append("promo_update")
                return _JsonResponse({"success": True})
            raise AssertionError(url)

    def fake_stripe_init(*args, **kwargs):
        calls.append("stripe_init")
        init_count = calls.count("stripe_init")
        amount = 199900 if init_count < 3 else 0
        return {
            "total_summary": {"due": amount},
            "payment_method_types": ["card", "upi"],
            "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_test",
        }

    monkeypatch.setattr(india_upi, "pix_proxy_context", lambda local, dynamic, log: _ProxyContext(dynamic))
    monkeypatch.setattr(india_upi, "build_chatgpt_session", lambda *args, **kwargs: FakeChatgptSession())
    monkeypatch.setattr(india_upi, "build_stripe_session", lambda *args, **kwargs: object())
    monkeypatch.setattr(india_upi, "stripe_init", fake_stripe_init)
    monkeypatch.setattr(india_upi.time, "sleep", lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr(india_upi, "_create_upi_payment_method", lambda *args, **kwargs: "pm_test")
    monkeypatch.setattr(india_upi, "_confirm_upi", lambda *args, **kwargs: {
        "payment_intent": {
            "id": "pi_test",
            "status": "requires_action",
            "next_action": {
                "type": "upi_handle_redirect_or_display_qr_code",
                "upi_handle_redirect_or_display_qr_code": {
                    "hosted_instructions_url": "https://payments.stripe.com/upi/instructions/promo-delayed",
                },
            },
        }
    })

    result = india_upi.generate_upi_trial(
        india_upi.UpiJobConfig(access_token="token", direct_proxies=["proxy"], apply_promo=True)
    )

    assert calls.count("stripe_init") == 4
    assert 0.8 in sleep_calls
    assert result["amount"] == "0"
    assert result["fields"]["upi_link"] == "https://payments.stripe.com/upi/instructions/promo-delayed"


def test_generate_upi_trial_logs_upi_intent_state_when_polling_times_out(monkeypatch):
    logs = []

    class FakeChatgptSession:
        def post(self, url, **kwargs):
            if url.endswith("/payments/checkout"):
                return _JsonResponse({
                    "checkout_session_id": "cs_test",
                    "processor_entity": "openai_llc",
                    "public_key": "pk_test",
                })
            if url.endswith("/payments/checkout/update"):
                return _JsonResponse({"success": True})
            if url.endswith("/payments/checkout/approve"):
                return _JsonResponse({"ok": True})
            raise AssertionError(url)

    monkeypatch.setattr(india_upi, "pix_proxy_context", lambda local, dynamic, log: _ProxyContext(dynamic))
    monkeypatch.setattr(india_upi, "build_chatgpt_session", lambda *args, **kwargs: FakeChatgptSession())
    monkeypatch.setattr(india_upi, "build_stripe_session", lambda *args, **kwargs: object())
    monkeypatch.setattr(india_upi, "stripe_init", lambda *args, **kwargs: {
        "total_summary": {"due": 0},
        "payment_method_types": ["card", "upi"],
        "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_test",
    })
    monkeypatch.setattr(india_upi.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(india_upi, "_create_upi_payment_method", lambda *args, **kwargs: "pm_test")
    monkeypatch.setattr(india_upi, "_confirm_upi", lambda *args, **kwargs: {
        "payment_intent": {"id": "pi_confirm", "status": "processing"},
        "submission_attempt": {"state": "requires_approval"},
    })
    monkeypatch.setattr(india_upi, "page_get", lambda *args, **kwargs: {
        "payment_intent": {"id": "pi_poll", "status": "requires_payment_method"},
        "submission_attempt": {"state": "processing"},
    })

    try:
        india_upi.generate_upi_trial(
            india_upi.UpiJobConfig(access_token="token", direct_proxies=["proxy"], apply_promo=True),
            log=logs.append,
        )
    except RuntimeError:
        pass

    joined = "\n".join(logs)
    assert "intent=pi_confirm" in joined
    assert "intent_state=processing" in joined
    assert "intent=pi_poll" in joined
    assert "intent_state=requires_payment_method" in joined
    assert "next_action=" in joined


def test_generate_upi_trial_reports_setup_intent_decline_details(monkeypatch):
    class FakeChatgptSession:
        def post(self, url, **kwargs):
            if url.endswith("/payments/checkout"):
                return _JsonResponse({
                    "checkout_session_id": "cs_test",
                    "processor_entity": "openai_llc",
                    "public_key": "pk_test",
                })
            if url.endswith("/payments/checkout/update"):
                return _JsonResponse({"success": True})
            raise AssertionError(url)

    monkeypatch.setattr(india_upi, "pix_proxy_context", lambda local, dynamic, log: _ProxyContext(dynamic))
    monkeypatch.setattr(india_upi, "build_chatgpt_session", lambda *args, **kwargs: FakeChatgptSession())
    monkeypatch.setattr(india_upi, "build_stripe_session", lambda *args, **kwargs: object())
    monkeypatch.setattr(india_upi, "stripe_init", lambda *args, **kwargs: {
        "total_summary": {"due": 0},
        "payment_method_types": ["card", "upi"],
        "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_test",
    })
    monkeypatch.setattr(india_upi.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(india_upi, "_create_upi_payment_method", lambda *args, **kwargs: "pm_test")
    monkeypatch.setattr(india_upi, "_confirm_upi", lambda *args, **kwargs: {
        "submission_attempt": {"state": "requires_approval"},
    })
    monkeypatch.setattr(india_upi, "chatgpt_approve", lambda *args, **kwargs: None)
    monkeypatch.setattr(india_upi, "page_get", lambda *args, **kwargs: {
        "setup_intent": {
            "id": "seti_test",
            "status": "requires_payment_method",
            "usage": "off_session",
            "last_setup_error": {
                "code": "setup_attempt_failed",
                "decline_code": "generic_decline",
                "payment_method": {"type": "upi", "upi": {"vpa": None}},
            },
        },
        "submission_attempt": {
            "state": "failed",
            "error": {
                "code": "checkout_approval_payment_failure_with_payment_error",
                "payment_error": {"code": "setup_attempt_failed", "decline_code": "generic_decline"},
            },
        },
    })

    with pytest.raises(RuntimeError) as excinfo:
        india_upi.generate_upi_trial(
            india_upi.UpiJobConfig(access_token="token", direct_proxies=["proxy"], apply_promo=True),
            log=lambda _message: None,
        )

    message = str(excinfo.value)
    assert "payment_error=setup_attempt_failed/generic_decline" in message
    assert "intent_type=setup_intent" in message
    assert "intent_state=requires_payment_method" in message
    assert "intent_usage=off_session" in message
    assert "intent_error=setup_attempt_failed/generic_decline" in message
    assert "upi_vpa=no" in message


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
            "id": "pi_direct",
            "status": "requires_action",
            "next_action": {
                "type": "upi_handle_redirect_or_display_qr_code",
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
    assert chatgpt_proxies == ["http://chain-1", "http://chain-2"]
    assert stripe_proxies == ["http://chain-2"]
