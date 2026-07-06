from autotoken.payments import protocol_card_executor


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


class FakeHttp:
    def __init__(self):
        self.calls = []
        self.headers = {}
        self.proxies = {}

    def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        if url.endswith("/init"):
            return FakeResponse(
                payload={
                    "init_checksum": "init_123",
                    "config_id": "cfg_123",
                    "currency": "usd",
                    "total_summary": {"due": 2000},
                    "return_url": "https://chatgpt.com/checkout/verify",
                }
            )
        if url.endswith("/v1/payment_methods"):
            return FakeResponse(payload={"id": "pm_card_123"})
        if url.endswith("/confirm"):
            return FakeResponse(payload={"submission_attempt": {"state": "requires_approval"}})
        if url.endswith("/backend-api/payments/checkout/approve"):
            return FakeResponse(payload={"result": "approved"})
        if "/v1/payment_pages/" in url:
            return FakeResponse(payload={"session": {"id": "cs_test"}})
        return FakeResponse(payload={})

    def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        if url.endswith("/v1/elements/sessions"):
            return FakeResponse(payload={"session_id": "elements_session_real", "config_id": "cfg_real"})
        if url.startswith("https://api.stripe.com/v1/payment_intents/"):
            return FakeResponse(payload={"id": "pi_test_123", "status": "succeeded"})
        if url == "https://chatgpt.com/checkout/verify":
            return FakeResponse(status_code=200, text="ok")
        return FakeResponse(payload={})


def test_protocol_card_bind_task_posts_card_payment_method_and_approves(monkeypatch):
    fake_http = FakeHttp()
    progress = []

    monkeypatch.setattr(protocol_card_executor, "_new_http_session", lambda *args, **kwargs: fake_http)
    monkeypatch.setattr(
        protocol_card_executor,
        "_extract_auth_session_context",
        lambda email: {
            "access_token": f"token-{email}",
            "session_token": "session-token",
            "cookie_header": "__Secure-next-auth.session-token=session-token",
            "account_id": "account-id",
            "device_id": "device-id",
        },
    )
    monkeypatch.setattr(
        protocol_card_executor,
        "generate_tax_free_billing_address",
        lambda: {
            "name": "Jane Buyer",
            "country": "US",
            "address1": "800 SW 5th Ave",
            "city": "Portland",
            "state": "OR",
            "zip": "97201",
        },
    )
    monkeypatch.setattr(protocol_card_executor, "_stripe_js_checksum", lambda pm: f"checksum-{pm}")
    monkeypatch.setattr(protocol_card_executor, "_stripe_rv_timestamp", lambda: "rv_123")

    result = protocol_card_executor.run_protocol_card_bind_task(
        email="user@example.com",
        checkout_url="https://chatgpt.com/checkout/openai_llc/cs_test",
        card_item={
            "value": "4242 4242 4242 4242",
            "meta": {"content": {"expiry_date": "12/30", "cvv": "123"}},
        },
        progress_callback=lambda event: progress.append(event),
    )

    assert result["status"] == "success"
    assert result["checkout_session_id"] == "cs_test"
    assert result["payment_method_id"] == "pm_card_123"
    payment_method_call = next(call for call in fake_http.calls if call[1].endswith("/v1/payment_methods"))
    posted = payment_method_call[2]["data"]
    assert posted["type"] == "card"
    assert posted["card[number]"] == "4242424242424242"
    assert posted["card[cvc]"] == "123"
    assert posted["card[exp_month]"] == "12"
    assert posted["card[exp_year]"] == "2030"
    assert posted["billing_details[address][state]"] == "OR"
    assert "browser_locale" not in posted
    assert "browser_timezone" not in posted
    assert any(call[1].endswith("/backend-api/payments/checkout/approve") for call in fake_http.calls)
    assert any(call[0] == "get" and call[1] == "https://chatgpt.com/checkout/verify" for call in fake_http.calls)
    assert [item["stage"] for item in progress] == [
        "protocol_card_http_profile",
        "protocol_card_init",
        "protocol_card_elements_session",
        "protocol_card_address_update",
        "protocol_card_payment_method",
        "protocol_card_confirm",
        "protocol_card_approve",
        "protocol_card_verify",
        "payment_completed",
    ]



def test_protocol_card_bind_task_uses_one_consistent_http_profile(monkeypatch):
    sessions = []
    created = []
    progress = []

    class ProfileHttp(FakeHttp):
        pass

    def fake_new_http_session(proxy_url=None, **kwargs):
        http = ProfileHttp()
        http.proxy_url = proxy_url
        created.append(kwargs)
        sessions.append(http)
        return http

    monkeypatch.setattr(protocol_card_executor, "_new_http_session", fake_new_http_session)
    monkeypatch.setattr(
        protocol_card_executor,
        "_select_protocol_http_profile",
        lambda: protocol_card_executor.ProtocolHttpProfile(
            name="test-chrome",
            tls_impersonate="chrome136",
            user_agent="Mozilla/5.0 Test Chrome/136.0.0.0",
            sec_ch_ua='"Google Chrome";v="136", "Chromium";v="136", "Not.A/Brand";v="99"',
            sec_ch_ua_platform='"Windows"',
            accept_language="en-US,en;q=0.9",
            browser_locale="en-US",
            browser_timezone="America/New_York",
        ),
    )
    monkeypatch.setattr(
        protocol_card_executor,
        "_extract_auth_session_context",
        lambda email: {
            "access_token": f"token-{email}",
            "session_token": "session-token",
            "cookie_header": "__Secure-next-auth.session-token=session-token",
            "account_id": "account-id",
            "device_id": "device-id",
        },
    )
    monkeypatch.setattr(
        protocol_card_executor,
        "generate_tax_free_billing_address",
        lambda: {
            "name": "Jane Buyer",
            "country": "US",
            "address1": "800 SW 5th Ave",
            "city": "Portland",
            "state": "OR",
            "zip": "97201",
        },
    )
    monkeypatch.setattr(protocol_card_executor, "_stripe_js_checksum", lambda pm: f"checksum-{pm}")
    monkeypatch.setattr(protocol_card_executor, "_stripe_rv_timestamp", lambda: "rv_123")

    result = protocol_card_executor.run_protocol_card_bind_task(
        email="user@example.com",
        checkout_url="https://chatgpt.com/checkout/openai_llc/cs_test",
        card_item={"value": "4242 4242 4242 4242", "meta": {"content": {"expiry_date": "12/30", "cvv": "123"}}},
        proxy_url="socks5h://proxy.example:1080",
        progress_callback=lambda event: progress.append(event),
    )

    assert result["status"] == "success"
    assert created == [
        {"require_curl_cffi": True, "tls_impersonate": "chrome136"},
        {"require_curl_cffi": True, "tls_impersonate": "chrome136"},
    ]
    assert len(sessions) == 2
    assert {session.proxy_url for session in sessions} == {"socks5h://proxy.example:1080"}
    for session in sessions:
        assert session.headers["User-Agent"] == "Mozilla/5.0 Test Chrome/136.0.0.0"
        assert session.headers["Accept-Language"] == "en-US,en;q=0.9"
        assert session.headers["sec-ch-ua"] == '"Google Chrome";v="136", "Chromium";v="136", "Not.A/Brand";v="99"'
        assert session.headers["sec-ch-ua-platform"] == '"Windows"'
    init_call = next(call for call in sessions[1].calls if call[1].endswith("/init"))
    assert init_call[2]["data"]["browser_locale"] == "en-US"
    assert init_call[2]["data"]["browser_timezone"] == "America/New_York"
    assert any(item["stage"] == "protocol_card_http_profile" for item in progress)


def test_protocol_card_bind_task_generates_checkout_with_same_proxy_and_profile(monkeypatch):
    sessions = []
    created = []
    progress = []

    class CheckoutHttp(FakeHttp):
        def post(self, url, **kwargs):
            self.calls.append(("post", url, kwargs))
            if url.endswith("/backend-api/payments/checkout"):
                return FakeResponse(
                    payload={
                        "checkout_session_id": "oaics_generated",
                        "processor_entity": "openai_llc",
                    },
                    text='{"checkout_session_id":"oaics_generated","processor_entity":"openai_llc"}',
                )
            if url.endswith("/backend-api/payments/checkout/taxes"):
                return FakeResponse(payload={"checkout_session": {"currency": "php"}})
            if url.endswith("/v1/confirmation_tokens"):
                return FakeResponse(payload={"id": "ctoken_test_123"})
            if url.endswith("/backend-api/payments/checkout/confirm"):
                return FakeResponse(payload={"status": "success", "client_secret": "pi_test_123_secret_demo"})
            return super().post(url, **kwargs)

    def fake_new_http_session(proxy_url=None, **kwargs):
        http = CheckoutHttp()
        http.proxy_url = proxy_url
        created.append(kwargs)
        sessions.append(http)
        return http

    monkeypatch.setattr(protocol_card_executor, "_new_http_session", fake_new_http_session)
    monkeypatch.setattr(
        protocol_card_executor,
        "_select_protocol_http_profile",
        lambda: protocol_card_executor.ProtocolHttpProfile(
            name="test-chrome",
            tls_impersonate="chrome136",
            user_agent="Mozilla/5.0 Test Chrome/136.0.0.0",
            sec_ch_ua='"Google Chrome";v="136", "Chromium";v="136", "Not.A/Brand";v="99"',
            sec_ch_ua_platform='"Windows"',
            accept_language="en-US,en;q=0.9",
            browser_locale="en-US",
            browser_timezone="America/New_York",
        ),
    )
    monkeypatch.setattr(
        protocol_card_executor,
        "_extract_auth_session_context",
        lambda email: {
            "access_token": f"token-{email}",
            "session_token": "session-token",
            "cookie_header": "__Secure-next-auth.session-token=session-token",
            "account_id": "account-id",
            "device_id": "device-id",
        },
    )
    monkeypatch.setattr(
        protocol_card_executor,
        "generate_tax_free_billing_address",
        lambda: {"name": "Jane Buyer", "country": "US", "address1": "2 Eagle Square", "city": "Concord", "state": "NH", "zip": "03301"},
    )
    monkeypatch.setattr(
        protocol_card_executor,
        "_checkout_approval_sentinel_headers",
        lambda *args, **kwargs: {"OpenAI-Sentinel-Token": "sentinel-token", "OAI-Telemetry": "[1,null]"},
    )

    result = protocol_card_executor.run_protocol_card_bind_task(
        email="user@example.com",
        checkout_url="",
        checkout_payload={
            "billing_details": {"country": "PH", "currency": "PHP"},
            "checkout_ui_mode": "hosted",
            "plan_name": "chatgptprolite",
        },
        card_item={"value": "4242 4242 4242 4242", "meta": {"content": {"expiry_date": "12/30", "cvv": "123"}}},
        proxy_url="socks5h://proxy.example:1080",
        progress_callback=progress.append,
    )

    assert result["status"] == "success"
    assert result["checkout_session_id"] == "oaics_generated"
    assert result["checkout_url"] == "https://chatgpt.com/checkout/openai_llc/oaics_generated"
    assert {session.proxy_url for session in sessions} == {"socks5h://proxy.example:1080"}
    assert created == [
        {"require_curl_cffi": True, "tls_impersonate": "chrome136"},
        {"require_curl_cffi": True, "tls_impersonate": "chrome136"},
    ]
    checkout_call = next(call for call in sessions[0].calls if call[1].endswith("/backend-api/payments/checkout"))
    assert checkout_call[2]["json"]["plan_name"] == "chatgptprolite"
    assert checkout_call[2]["headers"]["User-Agent"] == "Mozilla/5.0 Test Chrome/136.0.0.0"
    assert checkout_call[2]["headers"]["Accept-Language"] == "en-US,en;q=0.9"
    assert [event["stage"] for event in progress][:2] == [
        "protocol_card_http_profile",
        "protocol_openai_checkout_create",
    ]


def test_protocol_card_bind_task_supports_openai_oaics_checkout(monkeypatch):
    fake_http = FakeHttp()
    progress = []

    monkeypatch.setattr(protocol_card_executor, "_new_http_session", lambda *args, **kwargs: fake_http)
    monkeypatch.setattr(
        protocol_card_executor,
        "_extract_auth_session_context",
        lambda email: {
            "access_token": f"token-{email}",
            "session_token": "session-token",
            "cookie_header": "__Secure-next-auth.session-token=session-token",
            "account_id": "account-id",
            "device_id": "device-id",
        },
    )
    monkeypatch.setattr(
        protocol_card_executor,
        "generate_tax_free_billing_address",
        lambda: {
            "name": "Jane Buyer",
            "country": "US",
            "address1": "2 Eagle Square",
            "city": "Concord",
            "state": "NH",
            "zip": "03301",
        },
    )
    monkeypatch.setattr(
        protocol_card_executor,
        "_checkout_approval_sentinel_headers",
        lambda *args, **kwargs: {"OpenAI-Sentinel-Token": "sentinel-token", "OAI-Telemetry": "[1,null]"},
    )

    original_post = fake_http.post

    def fake_post(url, **kwargs):
        fake_http.calls.append(("post", url, kwargs))
        if url.endswith("/backend-api/payments/checkout/taxes"):
            return FakeResponse(payload={"checkout_session": {"currency": "php"}})
        if url.endswith("/v1/confirmation_tokens"):
            return FakeResponse(payload={"id": "ctoken_test_123"})
        if url.endswith("/backend-api/payments/checkout/confirm"):
            return FakeResponse(
                payload={
                    "status": "success",
                    "type": "payment_intent",
                    "client_secret": "pi_test_123_secret_demo",
                }
            )
        return original_post(url, **kwargs)

    fake_http.post = fake_post

    result = protocol_card_executor.run_protocol_card_bind_task(
        email="user@example.com",
        checkout_url="https://chatgpt.com/checkout/openai_llc/oaics_test123",
        card_item={
            "value": "4242 4242 4242 4242",
            "meta": {"content": {"expiry_date": "12/30", "cvv": "123"}},
        },
        progress_callback=lambda event: progress.append(event),
    )

    assert result["status"] == "success"
    assert result["checkout_session_id"] == "oaics_test123"
    assert result["confirmation_token_id"] == "ctoken_test_123"
    assert result["protocol_checkout_provider"] == "open_ai"
    assert not any("/v1/payment_pages/" in call[1] for call in fake_http.calls)
    taxes_call = next(call for call in fake_http.calls if call[1].endswith("/backend-api/payments/checkout/taxes"))
    taxes_body = taxes_call[2]["json"]
    assert taxes_body["checkout_session_id"] == "oaics_test123"
    assert taxes_body["currency"] == "php"
    assert taxes_body["billing_address"]["state"] == "NH"
    token_call = next(call for call in fake_http.calls if call[1].endswith("/v1/confirmation_tokens"))
    token_body = token_call[2]["data"]
    assert token_body["payment_method_data[card][number]"] == "4242424242424242"
    assert token_body["payment_method_data[card][exp_year]"] == "30"
    assert token_body["payment_method_data[billing_details][address][state]"] == "NH"
    assert "payment_method_data[billing_details][email]" not in token_body
    assert token_body["payment_method_data[allow_redisplay]"] == "limited"
    assert token_body["payment_method_data[payment_user_agent]"].endswith("payment-element; deferred-intent")
    assert token_body["setup_future_usage"] == "off_session"
    assert token_body["client_context[currency]"] == "php"
    assert token_body["client_context[mode]"] == "subscription"
    assert token_body["client_context[payment_method_types][0]"] == "card"
    assert token_body["client_context[payment_method_types][1]"] == "link"
    assert token_body["client_attribution_metadata[payment_method_selection_flow]"] == "merchant_specified"
    assert token_body["client_attribution_metadata[merchant_integration_additional_elements][0]"] == "expressCheckout"
    assert "browser_locale" not in token_body
    assert "browser_timezone" not in token_body
    confirm_call = next(call for call in fake_http.calls if call[1].endswith("/backend-api/payments/checkout/confirm"))
    assert confirm_call[2]["json"] == {
        "checkout_session_id": "oaics_test123",
        "confirm_token": "ctoken_test_123",
        "selected_payment_method_type": "card",
    }
    pi_confirm_call = next(
        call for call in fake_http.calls
        if call[0] == "post" and call[1].endswith("/v1/payment_intents/pi_test_123/confirm")
    )
    pi_confirm_body = pi_confirm_call[2]["data"]
    assert pi_confirm_body["expected_payment_method_type"] == "card"
    assert pi_confirm_body["use_stripe_sdk"] == "true"
    assert pi_confirm_body["client_secret"] == "pi_test_123_secret_demo"
    assert pi_confirm_body["client_context[mode]"] == "subscription"
    assert "payment_method_data[billing_details][email]" not in pi_confirm_body
    assert (
        pi_confirm_body["payment_method_data[client_attribution_metadata][client_session_id]"]
        == token_body["payment_method_data[client_attribution_metadata][client_session_id]"]
    )
    assert (
        pi_confirm_body["payment_method_data[client_attribution_metadata][elements_session_id]"]
        == token_body["payment_method_data[client_attribution_metadata][elements_session_id]"]
    )
    assert [item["stage"] for item in progress] == [
        "protocol_card_http_profile",
        "protocol_openai_taxes",
        "protocol_openai_confirmation_token",
        "protocol_openai_confirm",
        "protocol_card_payment_intent_confirm",
        "protocol_card_payment_intent",
        "protocol_card_verify",
        "payment_completed",
    ]


def test_protocol_card_bind_task_does_not_success_when_verify_200_but_payment_intent_not_succeeded(monkeypatch):
    class RequiresPaymentMethodHttp(FakeHttp):
        def get(self, url, **kwargs):
            self.calls.append(("get", url, kwargs))
            if url.startswith("https://api.stripe.com/v1/payment_intents/"):
                return FakeResponse(
                    payload={
                        "id": "pi_test_123",
                        "status": "requires_payment_method",
                        "last_payment_error": {
                            "code": "card_declined",
                            "decline_code": "do_not_honor",
                            "message": "Your card was declined.",
                            "type": "card_error",
                        },
                    }
                )
            if url == "https://chatgpt.com/checkout/verify":
                return FakeResponse(status_code=200, text="ok")
            if url.endswith("/v1/elements/sessions"):
                return FakeResponse(payload={"session_id": "elements_session_real", "config_id": "cfg_real"})
            return FakeResponse(payload={})

    fake_http = RequiresPaymentMethodHttp()
    monkeypatch.setattr(protocol_card_executor, "_new_http_session", lambda *args, **kwargs: fake_http)
    monkeypatch.setattr(
        protocol_card_executor,
        "_extract_auth_session_context",
        lambda email: {
            "access_token": f"token-{email}",
            "session_token": "session-token",
            "cookie_header": "__Secure-next-auth.session-token=session-token",
            "account_id": "account-id",
            "device_id": "device-id",
        },
    )
    monkeypatch.setattr(
        protocol_card_executor,
        "generate_tax_free_billing_address",
        lambda: {
            "name": "Jane Buyer",
            "country": "US",
            "address1": "2 Eagle Square",
            "city": "Concord",
            "state": "NH",
            "zip": "03301",
        },
    )
    monkeypatch.setattr(
        protocol_card_executor,
        "_checkout_approval_sentinel_headers",
        lambda *args, **kwargs: {"OpenAI-Sentinel-Token": "sentinel-token", "OAI-Telemetry": "[1,null]"},
    )

    original_post = fake_http.post

    def fake_post(url, **kwargs):
        fake_http.calls.append(("post", url, kwargs))
        if url.endswith("/backend-api/payments/checkout/taxes"):
            return FakeResponse(payload={"checkout_session": {"currency": "php"}})
        if url.endswith("/v1/confirmation_tokens"):
            return FakeResponse(payload={"id": "ctoken_test_123"})
        if url.endswith("/backend-api/payments/checkout/confirm"):
            return FakeResponse(
                payload={
                    "status": "success",
                    "type": "payment_intent",
                    "client_secret": "pi_test_123_secret_demo",
                }
            )
        return original_post(url, **kwargs)

    fake_http.post = fake_post

    result = protocol_card_executor.run_protocol_card_bind_task(
        email="user@example.com",
        checkout_url="https://chatgpt.com/checkout/openai_llc/oaics_test123",
        card_item={
            "value": "4242 4242 4242 4242",
            "meta": {"content": {"expiry_date": "12/30", "cvv": "123"}},
        },
    )

    assert result["status"] == "needs_review"
    assert result["failure_stage"] == "post_submit"
    assert result["payment_intent"]["status"] == "requires_payment_method"
    assert result["payment_intent"]["failure_reason"]["code"] == "card_declined"
    assert result["payment_intent"]["failure_reason"]["decline_code"] == "do_not_honor"
    assert "card_declined" in result["message"]
    assert "do_not_honor" in result["message"]


def test_protocol_card_bind_task_reports_payment_intent_confirm_error(monkeypatch):
    class ConfirmDeclinedHttp(FakeHttp):
        def get(self, url, **kwargs):
            self.calls.append(("get", url, kwargs))
            if url.startswith("https://api.stripe.com/v1/payment_intents/"):
                return FakeResponse(
                    payload={
                        "id": "pi_test_123",
                        "status": "requires_payment_method",
                        "last_payment_error": {"code": "card_declined", "decline_code": "generic_decline"},
                    }
                )
            return super().get(url, **kwargs)

    fake_http = ConfirmDeclinedHttp()
    monkeypatch.setattr(protocol_card_executor, "_new_http_session", lambda *args, **kwargs: fake_http)
    monkeypatch.setattr(
        protocol_card_executor,
        "_extract_auth_session_context",
        lambda email: {
            "access_token": f"token-{email}",
            "session_token": "session-token",
            "cookie_header": "__Secure-next-auth.session-token=session-token",
        },
    )
    monkeypatch.setattr(
        protocol_card_executor,
        "generate_tax_free_billing_address",
        lambda: {"name": "Jane Buyer", "country": "US", "address1": "2 Eagle Square", "city": "Concord", "state": "NH", "zip": "03301"},
    )
    monkeypatch.setattr(
        protocol_card_executor,
        "_checkout_approval_sentinel_headers",
        lambda *args, **kwargs: {"OpenAI-Sentinel-Token": "sentinel-token", "OAI-Telemetry": "[1,null]"},
    )

    original_post = fake_http.post

    def fake_post(url, **kwargs):
        fake_http.calls.append(("post", url, kwargs))
        if url.endswith("/backend-api/payments/checkout/taxes"):
            return FakeResponse(payload={"checkout_session": {"currency": "php"}})
        if url.endswith("/v1/confirmation_tokens"):
            return FakeResponse(payload={"id": "ctoken_test_123"})
        if url.endswith("/backend-api/payments/checkout/confirm"):
            return FakeResponse(payload={"status": "success", "client_secret": "pi_test_123_secret_demo"})
        if url.endswith("/v1/payment_intents/pi_test_123/confirm"):
            return FakeResponse(
                status_code=402,
                payload={
                    "error": {
                        "code": "card_declined",
                        "decline_code": "generic_decline",
                        "message": "Your card was declined.",
                        "type": "card_error",
                    }
                },
            )
        return original_post(url, **kwargs)

    fake_http.post = fake_post

    result = protocol_card_executor.run_protocol_card_bind_task(
        email="user@example.com",
        checkout_url="https://chatgpt.com/checkout/openai_llc/oaics_test123",
        card_item={"value": "4242 4242 4242 4242", "meta": {"content": {"expiry_date": "12/30", "cvv": "123"}}},
    )

    assert result["status"] == "needs_review"
    confirm_error = result["payment_intent"]["confirm_result"]
    assert confirm_error["http_status"] == 402
    assert confirm_error["error"]["code"] == "card_declined"
    assert confirm_error["error"]["decline_code"] == "generic_decline"


def test_protocol_card_bind_task_reports_payment_intent_next_action(monkeypatch):
    class RequiresActionHttp(FakeHttp):
        def get(self, url, **kwargs):
            self.calls.append(("get", url, kwargs))
            if url.startswith("https://api.stripe.com/v1/payment_intents/"):
                return FakeResponse(
                    payload={
                        "id": "pi_test_123",
                        "status": "requires_action",
                        "next_action": {
                            "type": "use_stripe_sdk",
                            "use_stripe_sdk": {
                                "type": "three_d_secure_redirect",
                                "stripe_js": "https://hooks.stripe.com/redirect/authenticate/src_123",
                            },
                        },
                    }
                )
            return super().get(url, **kwargs)

    fake_http = RequiresActionHttp()
    monkeypatch.setattr(protocol_card_executor, "_new_http_session", lambda *args, **kwargs: fake_http)
    monkeypatch.setattr(
        protocol_card_executor,
        "_extract_auth_session_context",
        lambda email: {
            "access_token": f"token-{email}",
            "session_token": "session-token",
            "cookie_header": "__Secure-next-auth.session-token=session-token",
        },
    )
    monkeypatch.setattr(
        protocol_card_executor,
        "generate_tax_free_billing_address",
        lambda: {"name": "Jane Buyer", "country": "US", "address1": "2 Eagle Square", "city": "Concord", "state": "NH", "zip": "03301"},
    )
    monkeypatch.setattr(
        protocol_card_executor,
        "_checkout_approval_sentinel_headers",
        lambda *args, **kwargs: {"OpenAI-Sentinel-Token": "sentinel-token", "OAI-Telemetry": "[1,null]"},
    )

    original_post = fake_http.post

    def fake_post(url, **kwargs):
        fake_http.calls.append(("post", url, kwargs))
        if url.endswith("/backend-api/payments/checkout/taxes"):
            return FakeResponse(payload={"checkout_session": {"currency": "php"}})
        if url.endswith("/v1/confirmation_tokens"):
            return FakeResponse(payload={"id": "ctoken_test_123"})
        if url.endswith("/backend-api/payments/checkout/confirm"):
            return FakeResponse(payload={"status": "success", "client_secret": "pi_test_123_secret_demo"})
        if url.endswith("/v1/payment_intents/pi_test_123/confirm"):
            return FakeResponse(payload={"id": "pi_test_123", "status": "requires_action"})
        return original_post(url, **kwargs)

    fake_http.post = fake_post

    result = protocol_card_executor.run_protocol_card_bind_task(
        email="user@example.com",
        checkout_url="https://chatgpt.com/checkout/openai_llc/oaics_test123",
        card_item={"value": "4242 4242 4242 4242", "meta": {"content": {"expiry_date": "12/30", "cvv": "123"}}},
    )

    assert result["status"] == "needs_review"
    assert result["payment_intent"]["status"] == "requires_action"
    assert result["payment_intent"]["next_action"]["type"] == "use_stripe_sdk"
    assert result["payment_intent"]["next_action"]["use_stripe_sdk"]["type"] == "three_d_secure_redirect"


def test_payment_intent_failure_reason_reads_latest_charge_outcome():
    reason = protocol_card_executor._payment_intent_failure_reason(
        {
            "status": "requires_payment_method",
            "latest_charge": {
                "outcome": {
                    "type": "issuer_declined",
                    "reason": "generic_decline",
                    "seller_message": "The bank did not approve this payment.",
                }
            },
        }
    )

    assert reason == {
        "code": "",
        "decline_code": "",
        "message": "The bank did not approve this payment.",
        "type": "issuer_declined",
        "outcome_reason": "generic_decline",
        "charge_status": "",
        "network_status": "",
        "risk_level": "",
        "cancellation_reason": "",
    }


def test_payment_intent_failure_reason_leaves_missing_charge_unclassified():
    reason = protocol_card_executor._payment_intent_failure_reason({"status": "requires_payment_method"})

    assert reason["code"] == ""
    assert reason["message"] == ""


def test_protocol_card_bind_task_requires_checkout_session(monkeypatch):
    monkeypatch.setattr(protocol_card_executor, "_extract_auth_session_context", lambda _email: {"access_token": "token"})

    result = protocol_card_executor.run_protocol_card_bind_task(
        email="user@example.com",
        checkout_url="https://example.test/no-session",
        card_item={"value": "4242424242424242", "meta": {"content": {"expiry_date": "12/30", "cvv": "123"}}},
    )

    assert result["status"] == "failed"
    assert result["failure_stage"] == "protocol_checkout_session"
