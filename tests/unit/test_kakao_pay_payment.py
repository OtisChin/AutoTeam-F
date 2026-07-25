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

    assert fields["kakao_link"] == ""
    assert fields["stripe_redirect_url"] == "https://pm-redirects.stripe.com/authorize/acct/test_nonce"
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


def test_kakao_region_selector_proxy_refreshes_sid_across_stages():
    cfg = kakao_pay.KakaoPayJobConfig(
        access_token="token",
        direct_proxies=["socks5h://user-region-KR-sid-fixed-t-120:pass@example.com:3000"],
    )

    checkout_proxy, _ = kakao_pay.build_kakao_dynamic_proxy(cfg, 0)
    promotion_proxy, _ = kakao_pay.build_kakao_dynamic_proxy(cfg, 1)
    provider_proxy, _ = kakao_pay.build_kakao_dynamic_proxy(cfg, 2)

    assert "region-KR" in checkout_proxy
    assert "region-VN" in promotion_proxy
    assert "region-KR" in provider_proxy
    assert "sid-fixed" not in checkout_proxy
    assert "sid-fixed" not in promotion_proxy
    assert "sid-fixed" not in provider_proxy
    assert len({checkout_proxy, promotion_proxy, provider_proxy}) == 3


def test_kakao_dynamic_proxy_uses_first_proxy_template_and_ignores_extra_entries(monkeypatch):
    monkeypatch.setattr(
        kakao_pay,
        "kakao_proxy_with_fresh_sid",
        lambda proxy_url, region: (f"{proxy_url}|{region}|fresh", f"{region.lower()}-fresh"),
    )
    cfg = kakao_pay.KakaoPayJobConfig(
        access_token="token",
        direct_proxies=[
            "socks5h://user-region-KR-session-seed1-sessTime-180-sessAuto-1:pass@example.com:3000",
            "socks5h://user-region-KR-session-seed2-sessTime-180-sessAuto-1:pass@example.com:3000",
            "socks5h://user-region-KR-session-seed3-sessTime-180-sessAuto-1:pass@example.com:3000",
        ],
    )

    checkout_proxy, checkout_label = kakao_pay.build_kakao_dynamic_proxy(cfg, 0)
    promotion_proxy, promotion_label = kakao_pay.build_kakao_dynamic_proxy(cfg, 1)
    provider_proxy, provider_label = kakao_pay.build_kakao_dynamic_proxy(cfg, 2)

    assert "session-seed1-" in checkout_proxy
    assert "session-seed1-" in promotion_proxy
    assert "session-seed1-" in provider_proxy
    assert "session-seed2-" not in checkout_proxy + promotion_proxy + provider_proxy
    assert "session-seed3-" not in checkout_proxy + promotion_proxy + provider_proxy
    assert checkout_proxy.endswith("|KR|fresh")
    assert promotion_proxy.endswith("|VN|fresh")
    assert provider_proxy.endswith("|KR|fresh")
    assert checkout_label.startswith("direct-1 ")
    assert promotion_label.startswith("direct-1 ")
    assert provider_label.startswith("direct-1 ")


def test_normalize_kakao_proxy_url_upgrades_socks5_to_socks5h():
    assert (
        kakao_pay.normalize_kakao_proxy_url("socks5://user:pass@example.com:3000")
        == "socks5h://user:pass@example.com:3000"
    )


def test_build_kakao_chatgpt_session_uses_korean_checkout_headers():
    session = kakao_pay.build_kakao_chatgpt_session("token", "", "device-id")

    assert session.headers["Accept-Language"].startswith("ko-KR")
    assert session.headers["oai-language"] == "ko-KR"
    assert session.headers["Authorization"] == "Bearer token"
    assert session.headers["Cookie"] == "oai-did=device-id"


def test_generate_kakao_trial_syncs_tax_then_approves_and_polls_redirect(monkeypatch):
    calls = []
    captured = {}
    stripe_inits = []

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

    def fake_stripe_init(*args, **kwargs):
        stripe_inits.append(1)
        return {
            "total_summary": {"due": 29000 if len(stripe_inits) == 1 else 0},
            "currency": "krw",
            "payment_method_types": ["card", "kakao_pay"],
            "ordered_payment_method_types": ["card", "kakao_pay", "naver_pay"],
            "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_test",
            "customer": {"email": "buyer@example.com"},
        }

    monkeypatch.setattr(kakao_pay, "stripe_init", fake_stripe_init)

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
    monkeypatch.setattr(kakao_pay, "resolve_kakao_redirect", lambda stripe, redirect_url, max_hops=3: "https://pay.nicepay.co.kr/v1/checkout/pay/test")
    monkeypatch.setattr(kakao_pay, "page_get", lambda *args, **kwargs: {
        "next_action": {"type": "redirect_to_url", "redirect_to_url": {"url": "https://pm-redirects.stripe.com/authorize/acct/test_nonce"}},
        "submission_attempt": {"state": "processing"},
    })

    result = kakao_pay.generate_kakao_trial(kakao_pay.KakaoPayJobConfig(access_token="token", direct_proxies=["proxy"]))

    assert ("tax_sync", "cs_test", "KR") in calls
    assert ("approve", "cs_test", "KR") in calls
    assert captured["return_url"].startswith("https://checkout.stripe.com/c/pay/cs_test?")
    assert "returned_from_redirect=true" in captured["return_url"]
    assert captured["billing"]["country"] == "KR"
    assert captured["amount"] == "0"
    assert result["fields"]["kakao_link"] == "https://pay.nicepay.co.kr/v1/checkout/pay/test"
    assert result["fields"]["provider_redirect_url"] == "https://pay.nicepay.co.kr/v1/checkout/pay/test"
    assert result["fields"]["stripe_redirect_url"] == "https://pm-redirects.stripe.com/authorize/acct/test_nonce"
    assert result["fields"]["amount"] == "0"
    assert result["fields"]["link_source"] == "stripe_checkout_approve_poll"


def test_generate_kakao_trial_matches_open_source_kakao_flow(monkeypatch):
    calls = []
    stripe_inits = []
    stripe_pages = []
    seed = "socks5h://user-region-KR-session-seed-main-sessTime-180-sessAuto-1:pass@example.com:3000"

    class FakeChatgptSession:
        def __init__(self, proxy_url):
            self.proxy_url = proxy_url

        def post(self, url, **kwargs):
            calls.append(("chatgpt_post", self.proxy_url, url, kwargs.get("json")))
            if url.endswith("/payments/checkout"):
                return _JsonResponse({
                    "checkout_session_id": "cs_test",
                    "processor_entity": "openai_llc",
                    "publishable_key": "pk_test",
                })
            if url.endswith("/payments/checkout/update"):
                return _JsonResponse({"success": True})
            if url.endswith("/payments/checkout/taxes"):
                return _JsonResponse({"success": True})
            if url.endswith("/payments/checkout/approve"):
                return _JsonResponse({"result": "approved"})
            raise AssertionError(url)

    class FakeStripeSession:
        def __init__(self, proxy_url):
            self.proxy_url = proxy_url

        def post(self, url, **kwargs):
            calls.append(("stripe_post", self.proxy_url, url, kwargs.get("data")))
            if url.endswith("/pre_confirm"):
                return _JsonResponse({"ok": True})
            if url.endswith("/v1/payment_methods"):
                return _JsonResponse({"id": "pm_kakao"})
            if url.endswith("/v1/payment_pages/cs_test"):
                return _JsonResponse({"ok": True})
            if url.endswith("/confirm"):
                assert kwargs["data"]["payment_method"] == "pm_kakao"
                assert "payment_method_data[type]" not in kwargs["data"]
                return _JsonResponse({"submission_attempt": {"state": "requires_approval"}})
            raise AssertionError(url)

        def get(self, url, **kwargs):
            calls.append(("stripe_get", self.proxy_url, url, kwargs.get("params")))
            return _JsonResponse({}, headers={"Location": "https://pay.nicepay.co.kr/v1/checkout/pay/test"})

    monkeypatch.setattr(kakao_pay, "pix_proxy_context", lambda local, dynamic, log: _ProxyContext(dynamic))
    monkeypatch.setattr(
        kakao_pay,
        "kakao_proxy_with_fresh_sid",
        lambda proxy_url, region: (f"{proxy_url}|{region}|fresh", f"{region.lower()}-fresh"),
    )
    monkeypatch.setattr(kakao_pay, "build_chatgpt_session", lambda token, proxy_url, device_id: FakeChatgptSession(proxy_url))
    monkeypatch.setattr(kakao_pay, "build_stripe_session", lambda proxy_url: FakeStripeSession(proxy_url))
    monkeypatch.setattr(kakao_pay, "warm_chatgpt_checkout_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(kakao_pay, "resolve_kakao_redirect", lambda stripe, redirect_url, max_hops=3: "https://pay.nicepay.co.kr/v1/checkout/pay/test")

    def fake_stripe_init(stripe, cs_id, pk, ctx):
        stripe_inits.append(stripe.proxy_url)
        due = 29000 if len(stripe_inits) == 1 else 0
        return {
            "total_summary": {"due": due},
            "currency": "krw",
            "payment_method_types": ["card", "kakao_pay", "naver_pay"],
            "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_test",
            "customer": {"email": "buyer@example.com"},
            "config_id": "cfg_test",
            "init_checksum": "init_test",
        }

    monkeypatch.setattr(kakao_pay, "stripe_init", fake_stripe_init)

    def fake_page_get(stripe, cs_id, pk, ctx):
        stripe_pages.append(stripe.proxy_url)
        return {
            "next_action": {"type": "redirect_to_url", "redirect_to_url": {"url": "https://pm-redirects.stripe.com/authorize/acct/test_nonce"}},
            "submission_attempt": {"state": "processing"},
        }

    monkeypatch.setattr(kakao_pay, "page_get", fake_page_get)
    monkeypatch.setattr(kakao_pay, "time", type("FakeTime", (), {"sleep": staticmethod(lambda _seconds: None), "time": staticmethod(lambda: 1.0)})())

    result = kakao_pay.generate_kakao_trial(kakao_pay.KakaoPayJobConfig(
        access_token="token",
        direct_proxies=[seed, "unused-seed-2", "unused-seed-3"],
    ))

    checkout_payload = next(payload for kind, _proxy, url, payload in calls if kind == "chatgpt_post" and url.endswith("/payments/checkout"))
    update_proxy, update_payload = next((proxy, payload) for kind, proxy, url, payload in calls if kind == "chatgpt_post" and url.endswith("/payments/checkout/update"))
    payment_method_proxy, payment_method_payload = next((proxy, payload) for kind, proxy, url, payload in calls if kind == "stripe_post" and url.endswith("/v1/payment_methods"))
    confirm_proxy, confirm_payload = next((proxy, payload) for kind, proxy, url, payload in calls if kind == "stripe_post" and url.endswith("/confirm"))

    assert checkout_payload["promo_campaign"]["promo_campaign_id"] == "plus-1-month-free"
    assert update_proxy == f"{seed}|VN|fresh"
    assert update_payload["promo_campaign"]["promo_campaign_id"] == "plus-1-month-free"
    assert stripe_inits == [f"{seed}|KR|fresh", f"{seed}|KR|fresh", f"{seed}|KR|fresh"]
    assert payment_method_proxy == f"{seed}|KR|fresh"
    assert payment_method_payload["type"] == "kakao_pay"
    assert confirm_proxy == f"{seed}|KR|fresh"
    assert confirm_payload["payment_method"] == "pm_kakao"
    assert confirm_payload["return_url"].startswith("https://checkout.stripe.com/c/pay/cs_test?")
    assert "return_url=https%3A%2F%2Fchatgpt.com%2Fbackend-api%2Fpayments%2Fcheckout%2Fopenai_llc%2Fcs_test%2Fsuccess" in confirm_payload["return_url"]
    assert result["fields"]["kakao_link"] == "https://pay.nicepay.co.kr/v1/checkout/pay/test"
    assert result["fields"]["provider_redirect_url"] == "https://pay.nicepay.co.kr/v1/checkout/pay/test"
    assert result["fields"]["stripe_redirect_url"] == "https://pm-redirects.stripe.com/authorize/acct/test_nonce"
    assert result["fields"]["link_source"] == "stripe_checkout_approve_poll"
