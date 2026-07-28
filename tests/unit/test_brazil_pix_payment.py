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


def test_build_chatgpt_session_includes_auth_session_cookie_and_client_headers():
    session = brazil_pix.build_chatgpt_session(
        "access-token",
        "",
        "device-test",
        session_token="session-token-value",
        cookie_header="_cfuvid=abc",
        account_id="acct_test",
        user_agent="UA-test",
        oai_client_version="client-version-test",
        oai_client_build_number="build-number-test",
    )

    assert session.headers["User-Agent"] == "UA-test"
    assert "__Secure-next-auth.session-token=session-token-value" in session.headers["Cookie"]
    assert "_cfuvid=abc" in session.headers["Cookie"]
    assert "_account=acct_test" in session.headers["Cookie"]
    assert "oai-did=device-test" in session.headers["Cookie"]
    assert session.headers["oai-session-id"] == "device-test"
    assert session.headers["oai-client-version"] == "client-version-test"
    assert session.headers["oai-client-build-number"] == "build-number-test"


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
    confirm_payload = next(payload for kind, url, payload in calls if kind == "stripe_post" and url.endswith("/confirm"))

    assert create_payload["promo_campaign"]["promo_campaign_id"] == "plus-1-month-free"
    assert create_payload["promo_campaign"]["is_coupon_from_query_param"] is False
    assert payment_method_payload["type"] == "pix"
    assert "success_return_url=" in confirm_payload["return_url"]
    assert confirm_payload["client_attribution_metadata[client_session_id]"] != confirm_payload[
        "elements_session_client[stripe_js_id]"
    ]
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


def test_generate_pix_trial_rotates_fresh_proxy_when_approve_proxy_is_blocked(monkeypatch):
    calls = []
    approve_proxies = []

    class FakeChatgptSession:
        def __init__(self, proxy_url=""):
            self.proxy_url = proxy_url

        def post(self, url, **kwargs):
            calls.append(("chatgpt_post", url, kwargs.get("json"), self.proxy_url))
            if url.endswith("/checkout/approve"):
                approve_proxies.append(self.proxy_url)
                if len(approve_proxies) == 1:
                    return _JsonResponse("<html>blocked</html>", status_code=403)
                return _JsonResponse({"result": "approved"})
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
                return _JsonResponse({"submission_attempt": {"state": "requires_approval"}})
            raise AssertionError(f"unexpected stripe post {url}")

    page_payloads = iter([
        {
            "submission_attempt": {"state": "processing"},
            "next_action": {
                "pix_display_qr_code": {
                    "data": "000201PIXTEST",
                    "hosted_instructions_url": "https://payments.stripe.com/qr/instructions/pix_test",
                },
            },
        }
    ])

    monkeypatch.setattr(brazil_pix, "pix_proxy_context", lambda local, dynamic, log: _ProxyContext(dynamic))
    monkeypatch.setattr(brazil_pix, "build_chatgpt_session", lambda _token, proxy_url="", *_args, **_kwargs: FakeChatgptSession(proxy_url))
    monkeypatch.setattr(brazil_pix, "build_stripe_session", lambda *args, **kwargs: FakeStripeSession())
    monkeypatch.setattr(brazil_pix, "stripe_init", lambda *args, **kwargs: {
        "total_summary": {"due": 0},
        "payment_method_types": ["card", "pix"],
        "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_test",
        "config_id": "cfg_test",
        "init_checksum": "chk_test",
    })
    monkeypatch.setattr(brazil_pix, "page_get", lambda *args, **kwargs: next(page_payloads))
    monkeypatch.setattr(brazil_pix.time, "sleep", lambda _seconds: None)

    result = brazil_pix.generate_pix_trial(
        brazil_pix.PixJobConfig(access_token="token", direct_proxies=["proxy-region-BR-session-first-t-120"])
    )

    assert result["ok"] is True
    assert len(approve_proxies) == 2
    assert approve_proxies[0] != approve_proxies[1]


def test_generate_pix_trial_keeps_polling_after_failed_submission_if_qr_appears(monkeypatch):
    poll_states = []

    class FakeChatgptSession:
        def post(self, url, **kwargs):
            return _JsonResponse({
                "checkout_session_id": "cs_test",
                "processor_entity": "openai_llc",
                "public_key": "pk_test",
            })

    class FakeStripeSession:
        def post(self, url, **kwargs):
            if url.endswith("/payment_methods"):
                return _JsonResponse({"id": "pm_pix_test"})
            if url.endswith("/confirm"):
                return _JsonResponse({"submission_attempt": {"state": "requires_approval"}})
            raise AssertionError(f"unexpected stripe post {url}")

    page_payloads = iter([
        {
            "submission_attempt": {
                "state": "failed",
                "error": {
                    "code": "checkout_approval_payment_failure_with_payment_error",
                    "payment_error": {"code": "setup_attempt_failed", "decline_code": "generic_decline"},
                },
            },
        },
        {
            "submission_attempt": {"state": "processing"},
            "next_action": {
                "pix_display_qr_code": {
                    "data": "000201PIXTEST",
                    "hosted_instructions_url": "https://payments.stripe.com/qr/instructions/pix_test",
                },
            },
        },
    ])

    def fake_page_get(*args, **kwargs):
        payload = next(page_payloads)
        poll_states.append(payload["submission_attempt"]["state"])
        return payload

    monkeypatch.setattr(brazil_pix, "pix_proxy_context", lambda local, dynamic, log: _ProxyContext(dynamic))
    monkeypatch.setattr(brazil_pix, "build_chatgpt_session", lambda *args, **kwargs: FakeChatgptSession())
    monkeypatch.setattr(brazil_pix, "build_stripe_session", lambda *args, **kwargs: FakeStripeSession())
    monkeypatch.setattr(brazil_pix, "stripe_init", lambda *args, **kwargs: {
        "total_summary": {"due": 0},
        "payment_method_types": ["card", "pix"],
        "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_test",
        "config_id": "cfg_test",
        "init_checksum": "chk_test",
    })
    monkeypatch.setattr(brazil_pix, "chatgpt_approve", lambda *args, **kwargs: None)
    monkeypatch.setattr(brazil_pix, "page_get", fake_page_get)
    monkeypatch.setattr(brazil_pix.time, "sleep", lambda _seconds: None)

    result = brazil_pix.generate_pix_trial(brazil_pix.PixJobConfig(access_token="token", direct_proxies=["proxy"]))

    assert poll_states == ["failed", "processing"]
    assert result["ok"] is True
    assert result["fields"]["hosted_instructions_url"] == "https://payments.stripe.com/qr/instructions/pix_test"


def test_generate_pix_trial_approves_with_checkout_proxy_not_stripe_proxy(monkeypatch):
    approve_proxies = []

    class FakeChatgptSession:
        def post(self, url, **kwargs):
            return _JsonResponse({
                "checkout_session_id": "cs_test",
                "processor_entity": "openai_llc",
                "public_key": "pk_test",
            })

    class FakeStripeSession:
        def post(self, url, **kwargs):
            if url.endswith("/payment_methods"):
                return _JsonResponse({"id": "pm_pix_test"})
            if url.endswith("/confirm"):
                return _JsonResponse({"submission_attempt": {"state": "requires_approval"}})
            raise AssertionError(f"unexpected stripe post {url}")

    page_payloads = iter([
        {
            "submission_attempt": {"state": "processing"},
            "next_action": {
                "pix_display_qr_code": {
                    "data": "000201PIXTEST",
                    "hosted_instructions_url": "https://payments.stripe.com/qr/instructions/pix_test",
                },
            },
        }
    ])

    def fake_build_proxy(_cfg, stage_index):
        if stage_index == 0:
            return "checkout-proxy", "checkout"
        if stage_index == 1:
            return "stripe-proxy", "stripe"
        return f"approve-proxy-{stage_index}", f"approve-{stage_index}"

    monkeypatch.setattr(brazil_pix, "build_pix_dynamic_proxy", fake_build_proxy)
    monkeypatch.setattr(brazil_pix, "pix_proxy_context", lambda local, dynamic, log: _ProxyContext(dynamic))
    monkeypatch.setattr(brazil_pix, "build_chatgpt_session", lambda *args, **kwargs: FakeChatgptSession())
    monkeypatch.setattr(brazil_pix, "build_stripe_session", lambda *args, **kwargs: FakeStripeSession())
    monkeypatch.setattr(brazil_pix, "stripe_init", lambda *args, **kwargs: {
        "total_summary": {"due": 0},
        "payment_method_types": ["card", "pix"],
        "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_test",
        "config_id": "cfg_test",
        "init_checksum": "chk_test",
    })
    monkeypatch.setattr(
        brazil_pix,
        "approve_pix_with_proxy_rotation",
        lambda *args, **kwargs: approve_proxies.append(kwargs["primary_proxy_url"]),
    )
    monkeypatch.setattr(brazil_pix, "page_get", lambda *args, **kwargs: next(page_payloads))
    monkeypatch.setattr(brazil_pix.time, "sleep", lambda _seconds: None)

    result = brazil_pix.generate_pix_trial(brazil_pix.PixJobConfig(access_token="token", direct_proxies=["proxy"]))

    assert result["ok"] is True
    assert approve_proxies == ["checkout-proxy"]


def test_generate_pix_trial_reuses_checkout_chatgpt_session_for_primary_approve(monkeypatch):
    approve_session_labels = []
    session_count = 0

    class FakeChatgptSession:
        def __init__(self, label):
            self.label = label
            self.headers = {}

        def get(self, url, **kwargs):
            return _JsonResponse({})

        def post(self, url, **kwargs):
            if url.endswith("/checkout/approve"):
                approve_session_labels.append(self.label)
                return _JsonResponse({"result": "approved"})
            if url.endswith("/checkout"):
                return _JsonResponse({
                    "checkout_session_id": "cs_test",
                    "processor_entity": "openai_llc",
                    "public_key": "pk_test",
                })
            return _JsonResponse({})

    class FakeStripeSession:
        def post(self, url, **kwargs):
            if url.endswith("/payment_methods"):
                return _JsonResponse({"id": "pm_pix_test"})
            if url.endswith("/confirm"):
                return _JsonResponse({"submission_attempt": {"state": "requires_approval"}})
            raise AssertionError(f"unexpected stripe post {url}")

    def fake_build_chatgpt_session(*args, **kwargs):
        nonlocal session_count
        session_count += 1
        return FakeChatgptSession("checkout" if session_count == 1 else f"new-{session_count}")

    monkeypatch.setattr(brazil_pix, "pix_proxy_context", lambda local, dynamic, log: _ProxyContext(dynamic))
    monkeypatch.setattr(brazil_pix, "build_chatgpt_session", fake_build_chatgpt_session)
    monkeypatch.setattr(brazil_pix, "build_stripe_session", lambda *args, **kwargs: FakeStripeSession())
    monkeypatch.setattr(brazil_pix, "stripe_init", lambda *args, **kwargs: {
        "total_summary": {"due": 0},
        "payment_method_types": ["card", "pix"],
        "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_test",
        "config_id": "cfg_test",
        "init_checksum": "chk_test",
    })
    monkeypatch.setattr(brazil_pix, "page_get", lambda *args, **kwargs: {
        "submission_attempt": {"state": "processing"},
        "next_action": {
            "pix_display_qr_code": {
                "data": "000201PIXTEST",
                "hosted_instructions_url": "https://payments.stripe.com/qr/instructions/pix_test",
            },
        },
    })
    monkeypatch.setattr(brazil_pix.time, "sleep", lambda _seconds: None)

    result = brazil_pix.generate_pix_trial(brazil_pix.PixJobConfig(access_token="token", direct_proxies=["proxy"]))

    assert result["ok"] is True
    assert approve_session_labels == ["checkout"]
