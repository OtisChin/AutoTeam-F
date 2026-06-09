from autotoken.services import paypal_billing_agreement as paypal_ba


def test_paypal_ba_extract_attempts_clamps_and_falls_back():
    assert paypal_ba.paypal_ba_extract_attempts("0") == 1
    assert paypal_ba.paypal_ba_extract_attempts("3") == 3
    assert paypal_ba.paypal_ba_extract_attempts("99") == 5
    assert paypal_ba.paypal_ba_extract_attempts("bad") == 5


def test_paypal_ba_payment_method_country_prefers_override_then_protocol_rules():
    assert (
        paypal_ba.paypal_ba_payment_method_country(
            override=" jp-123 ",
            protocol_no_card=True,
            paypal_country="ID",
        )
        == "JP"
    )
    assert (
        paypal_ba.paypal_ba_payment_method_country(
            override="",
            protocol_no_card=True,
            paypal_country="JP",
        )
        == "US"
    )
    assert (
        paypal_ba.paypal_ba_payment_method_country(
            override="",
            protocol_no_card=False,
            paypal_country="br",
        )
        == "BR"
    )
    assert (
        paypal_ba.paypal_ba_payment_method_country(
            override="",
            protocol_no_card=False,
            paypal_country="",
        )
        == "US"
    )


def test_paypal_ba_extract_kwargs_normalizes_protocol_request_fields():
    def is_cancelled():
        return False

    kwargs = paypal_ba.paypal_ba_extract_kwargs(
        auth_session_context={
            "session_token": "session-token",
            "cookie_header": "__Secure-next-auth.session-token=session-token",
            "account_id": 123,
            "device_id": None,
            "user_agent": "UA",
            "openai_sentinel_token": "sentinel",
            "oai_client_version": "1.2.3",
            "oai_client_build_number": "456",
        },
        access_token="access-token",
        proxy_url="socks5h://jp.example:1080",
        provider_proxy_url="socks5h://us.example:1080",
        paypal_country="JP",
        payment_method_country="US",
        timeout_seconds=120,
        is_cancelled=is_cancelled,
    )

    assert kwargs == {
        "access_token": "access-token",
        "session_token": "session-token",
        "cookie_header": "__Secure-next-auth.session-token=session-token",
        "account_id": "123",
        "device_id": "",
        "user_agent": "UA",
        "openai_sentinel_token": "sentinel",
        "oai_client_version": "1.2.3",
        "oai_client_build_number": "456",
        "proxy_url": "socks5h://jp.example:1080",
        "provider_proxy_url": "socks5h://us.example:1080",
        "approve_proxy_url": "socks5h://us.example:1080",
        "country": "US",
        "currency": "USD",
        "payment_method_country": "US",
        "timeout_seconds": 90,
        "is_cancelled": is_cancelled,
    }


def test_paypal_ba_extract_kwargs_preserves_non_jp_country_and_clamps_timeout_minimum():
    kwargs = paypal_ba.paypal_ba_extract_kwargs(
        auth_session_context={},
        access_token="access-token",
        proxy_url="",
        provider_proxy_url="",
        paypal_country="br",
        payment_method_country="BR",
        timeout_seconds=10,
        is_cancelled=lambda: True,
    )

    assert kwargs["country"] == "BR"
    assert kwargs["timeout_seconds"] == 30
    assert paypal_ba.paypal_ba_checkout_country("") == ""


def test_paypal_checkout_payload_uses_paypal_zero_trial_defaults():
    assert paypal_ba.paypal_checkout_payload() == {
        "entry_point": "all_plans_pricing_modal",
        "plan_name": "chatgptplusplan",
        "billing_details": {"country": "US", "currency": "USD"},
        "promo_campaign": {
            "promo_campaign_id": "plus-1-month-free",
            "is_coupon_from_query_param": False,
        },
        "checkout_ui_mode": "hosted",
        "cancel_url": "https://chatgpt.com/#pricing",
    }
    assert paypal_ba.paypal_checkout_payload(country="JP", currency="JPY", checkout_ui_mode="custom")[
        "billing_details"
    ] == {"country": "JP", "currency": "JPY"}


def test_paypal_extract_result_from_redirect_returns_success_payload():
    result = paypal_ba.paypal_extract_result_from_redirect(
        object(),
        "https://pm-redirects.stripe.com/authorize/test",
        "cs_test",
        "pm_test",
        resolve_approve_url=lambda _http, _url: ("https://www.paypal.com/pay?token=BA-DEMO", "BA-DEMO"),
    )

    assert result == {
        "status": "success",
        "ba_token": "BA-DEMO",
        "approve_url": "https://www.paypal.com/pay?token=BA-DEMO",
        "checkout_session_id": "cs_test",
        "pm_id": "pm_test",
    }


def test_paypal_extract_result_from_redirect_reports_resolve_failures():
    result = paypal_ba.paypal_extract_result_from_redirect(
        object(),
        "https://pm-redirects.stripe.com/authorize/test",
        "cs_test",
        "pm_test",
        resolve_approve_url=lambda _http, _url: (_ for _ in ()).throw(RuntimeError("network down")),
    )

    assert result == {
        "status": "failed",
        "failure_stage": "extract_ba_link_resolve",
        "message": "Failed to resolve final PayPal URL: network down",
        "checkout_session_id": "cs_test",
        "pm_id": "pm_test",
    }


def test_paypal_extract_result_from_redirect_reports_missing_approve_url_or_ba_token():
    missing_approve = paypal_ba.paypal_extract_result_from_redirect(
        object(),
        "https://pm-redirects.stripe.com/authorize/test",
        "cs_test",
        "pm_test",
        resolve_approve_url=lambda _http, _url: ("", ""),
    )
    missing_token = paypal_ba.paypal_extract_result_from_redirect(
        object(),
        "https://pm-redirects.stripe.com/authorize/test",
        "cs_test",
        "pm_test",
        resolve_approve_url=lambda _http, _url: ("https://www.paypal.com/pay?token=", ""),
    )

    assert missing_approve["failure_stage"] == "extract_ba_link_resolve"
    assert missing_approve["message"] == "Failed to resolve final PayPal URL"
    assert missing_token["failure_stage"] == "extract_ba_link_parse"
    assert missing_token["approve_url"] == "https://www.paypal.com/pay?token="


def test_paypal_protocol_elements_options_match_stripe_checkout_contract():
    assert paypal_ba.paypal_protocol_elements_options() == {
        "elements_options_client[stripe_js_locale]": "auto",
        "elements_options_client[saved_payment_method][enable_save]": "never",
        "elements_options_client[saved_payment_method][enable_redisplay]": "never",
    }


def test_paypal_protocol_checkout_amount_prefers_summary_then_invoice_then_line_items():
    assert (
        paypal_ba.paypal_protocol_checkout_amount({"total_summary": {"due": 123}, "invoice": {"amount_due": 456}})
        == "123"
    )
    assert paypal_ba.paypal_protocol_checkout_amount({"invoice": {"amount_due": 456}}) == "456"
    assert paypal_ba.paypal_protocol_checkout_amount({"line_items": [{"amount": "100"}, {"amount": 250}]}) == "350"
    assert paypal_ba.paypal_protocol_checkout_amount({"line_items": [{"amount": "bad"}]}) == "0"
    assert paypal_ba.paypal_protocol_checkout_amount({}) == "0"


def test_paypal_protocol_amount_due_accepts_ints_and_display_text():
    assert paypal_ba.paypal_protocol_amount_due(123) == 123
    assert paypal_ba.paypal_protocol_amount_due("JPY 1,234") == 1234
    assert paypal_ba.paypal_protocol_amount_due("") == 0


def test_paypal_protocol_payment_method_types_finds_nested_lists():
    assert paypal_ba.paypal_protocol_payment_method_types(
        {
            "payment_method_types": ["card"],
            "nested": {
                "ordered_payment_method_types": ["PayPal", "link"],
                "items": [{"automatic_payment_method_types": ["US_Bank_Account", 123]}],
            },
            "unrelated": ["ignored"],
        }
    ) == {"card", "paypal", "link", "us_bank_account"}


def test_paypal_protocol_unescape_url_handles_html_json_escapes():
    assert (
        paypal_ba.paypal_protocol_unescape_url(
            "https:\\/\\/www.paypal.com\\/agreements\\/approve?ba_token=BA-DEMO\\u0026country.x=US&amp;ul=1"
        )
        == "https://www.paypal.com/agreements/approve?ba_token=BA-DEMO&country.x=US&ul=1"
    )


def test_paypal_protocol_extract_url_from_text_finds_paypal_and_stripe_urls():
    assert (
        paypal_ba.paypal_protocol_extract_url_from_text(
            '{"href":"https:\\/\\/www.paypal.com\\/agreements\\/approve?ba_token=BA-ESCAPED\\u0026country.x=US"}'
        )
        == "https://www.paypal.com/agreements/approve?ba_token=BA-ESCAPED&country.x=US"
    )
    assert (
        paypal_ba.paypal_protocol_extract_url_from_text("next=https://pm-redirects.stripe.com/authorize/test), done")
        == "https://pm-redirects.stripe.com/authorize/test"
    )
    assert paypal_ba.paypal_protocol_extract_url_from_text("https://example.com/ignore") == ""


def test_paypal_protocol_extract_ba_token_uses_known_query_names_text_and_fallback():
    assert paypal_ba.paypal_protocol_extract_ba_token("https://www.paypal.com/pay?token=BA-PAYTOKEN") == "BA-PAYTOKEN"
    assert (
        paypal_ba.paypal_protocol_extract_ba_token(
            "https://www.paypal.com/agreements/approve?billingAgreementId=BA-BILLING"
        )
        == "BA-BILLING"
    )
    assert paypal_ba.paypal_protocol_extract_ba_token("body BA-IN-TEXT-123456 done") == "BA-IN-TEXT-123456"
    assert (
        paypal_ba.paypal_protocol_extract_ba_token("https://www.paypal.com/pay?token=EC-TOKEN", "BA-FALLBACK")
        == "BA-FALLBACK"
    )


def test_find_paypal_redirect_url_walks_nested_payloads_and_ignores_cycles():
    payload: dict = {
        "setup_intent": {
            "next_action": {
                "redirect_to_url": {
                    "url": (
                        '{"href":"https:\\/\\/www.paypal.com\\/agreements\\/approve'
                        '?ba_token=BA-ESCAPED\\u0026country.x=US"}'
                    )
                }
            }
        }
    }
    payload["cycle"] = payload

    assert (
        paypal_ba.find_paypal_redirect_url(payload)
        == "https://www.paypal.com/agreements/approve?ba_token=BA-ESCAPED&country.x=US"
    )
    assert paypal_ba.find_paypal_redirect_url({"url": "https://example.com/ignore", "items": []}) == ""


def test_paypal_create_account_entry_url_forces_onboard_redirect_with_locale():
    url = paypal_ba.paypal_create_account_entry_url(
        "https://www.paypal.com/pay?token=BA-123456789&ssrt=abc",
        country="JP",
        lang="ja",
    )

    assert url.startswith("https://www.paypal.com/agreements/approve?")
    assert "ssrt=abc" in url
    assert "ba_token=BA-123456789" in url
    assert "ul=1" in url
    assert "ulOnboardRedirect=true" in url
    assert "modxo_redirect_reason=guest_user" in url
    assert "country.x=JP" in url
    assert "locale.x=ja_JP" in url


def test_paypal_create_account_entry_url_uses_fallback_token_and_rejects_invalid_inputs():
    assert paypal_ba.paypal_create_account_entry_url(
        "https://www.paypal.com/agreements/approve?country.x=US",
        ba_token="BA-FALLBACK",
        country="us",
        lang="",
    ) == (
        "https://www.paypal.com/agreements/approve?country.x=US&ul=1&locale.x=en_US"
        "&modxo_redirect_reason=guest_user&ulOnboardRedirect=true&ba_token=BA-FALLBACK"
    )
    assert paypal_ba.paypal_create_account_entry_url("https://evilpaypal.com/pay?token=BA-DEMO") == ""
    assert paypal_ba.paypal_create_account_entry_url("https://www.paypal.com/pay?token=EC-DEMO") == ""


def test_paypal_ba_auth_context_uses_trimmed_access_token_in_minimal_mode():
    context = paypal_ba.paypal_ba_auth_context(
        "user@example.com",
        "fallback-token",
        session_context_loader=lambda _email: {
            "access_token": " session-token ",
            "session_token": "hidden",
            "cookie_header": "cookie",
            "user_agent": "UA",
        },
        use_full_context=False,
    )

    assert context == {
        "access_token": "session-token",
        "session_token": "",
        "cookie_header": "",
        "account_id": "",
        "device_id": "",
        "user_agent": "UA",
        "openai_sentinel_token": "",
        "oai_client_version": "",
        "oai_client_build_number": "",
    }


def test_paypal_ba_auth_context_preserves_full_context_when_enabled():
    context = paypal_ba.paypal_ba_auth_context(
        "user@example.com",
        "fallback-token",
        session_context_loader=lambda _email: {
            "access_token": "",
            "session_token": "session-token",
            "cookie_header": None,
            "account_id": 123,
        },
        use_full_context=True,
    )

    assert context == {
        "access_token": "fallback-token",
        "session_token": "session-token",
        "cookie_header": "",
        "account_id": "123",
    }


def test_paypal_ba_auth_context_falls_back_when_loader_fails():
    errors = []

    def fail(_email):
        raise RuntimeError("missing session")

    context = paypal_ba.paypal_ba_auth_context(
        "user@example.com",
        "fallback-token",
        session_context_loader=fail,
        use_full_context=False,
        log_failure=errors.append,
    )

    assert context["access_token"] == "fallback-token"
    assert context["user_agent"] == ""
    assert str(errors[0]) == "missing session"


def test_paypal_already_paid_text_and_success_payload():
    assert paypal_ba.paypal_already_paid_text("User is already paid for this plan")
    assert paypal_ba.paypal_already_paid_text("账号已有有效订阅")
    assert not paypal_ba.paypal_already_paid_text("payment method was declined")

    payload = paypal_ba.paypal_user_paid_success("user@example.com")
    assert payload["status"] == "success"
    assert payload["email"] == "user@example.com"
    assert payload["user_paid_skip"] is True


def test_paypal_provider_proxy_progress_preserves_optional_retry_fields():
    selected = paypal_ba.paypal_provider_proxy_selected_progress(
        email="user@example.com",
        current=1,
        total=2,
        retry_round=1,
        ba_attempt=3,
        proxy_label="pool-a",
        proxy_api_provider="cliproxy",
        proxy_summary="socks5h://***",
    )
    failed = paypal_ba.paypal_provider_proxy_failed_progress(
        email="user@example.com",
        current=1,
        total=2,
        proxy_label="pool-a",
        proxy_api_provider="cliproxy",
        error=RuntimeError("api down"),
    )

    assert selected == {
        "stage": "paypal_provider_proxy_selected",
        "email": "user@example.com",
        "current": 1,
        "total": 2,
        "retry_round": 1,
        "ba_attempt": 3,
        "proxy_label": "pool-a",
        "proxy_api_provider": "cliproxy",
        "message": "PayPal provider 阶段已切换代理: socks5h://***",
    }
    assert "retry_round" not in failed
    assert failed["stage"] == "paypal_provider_proxy_failed"
    assert failed["level"] == "warn"
    assert "api down" in failed["message"]


def test_paypal_ba_attempt_retry_and_result_progress_payloads():
    failed_attempt = paypal_ba.paypal_ba_extract_attempt_failed_progress(
        email="user@example.com",
        current=1,
        total=2,
        retry_round=0,
        ba_attempt=2,
        max_ba_attempts=5,
        result_payload={"failure_stage": "extract_ba_link_poll", "message": "timeout"},
    )
    retrying = paypal_ba.paypal_ba_extract_retry_progress(
        email="user@example.com",
        current=1,
        total=2,
        ba_attempt=3,
        max_ba_attempts=5,
    )
    extracted = paypal_ba.paypal_ba_extracted_progress(
        email="user@example.com",
        current=1,
        total=2,
        ba_token="BA-1234567890abcdef",
    )
    failed = paypal_ba.paypal_ba_extract_failed_progress(
        email="user@example.com",
        current=1,
        total=2,
        result_payload={"message": "not found"},
    )

    assert failed_attempt["retry_round"] == 0
    assert failed_attempt["ba_attempt"] == 2
    assert failed_attempt["max_ba_attempts"] == 5
    assert failed_attempt["failure_stage"] == "extract_ba_link_poll"
    assert failed_attempt["message"] == "PayPal BA 第 2/5 次失败: timeout"
    assert retrying["message"] == "PayPal BA 第 3/5 次重试，重新获取代理和 checkout"
    assert "retry_round" not in retrying
    assert extracted["message"] == "已通过 HTTP 协议提取 PayPal BA 链接: BA-123456789..."
    assert failed["message"] == "HTTP 提取 BA 链接失败: not found"


def test_paypal_approve_proxy_and_checkout_long_link_progress_payloads():
    approve = paypal_ba.paypal_approve_proxy_selected_progress(
        email="user@example.com",
        current=1,
        total=2,
        proxy_label="pool-a",
        proxy_api_provider="cliproxy",
        proxy_summary="socks5h://***",
        ba_attempt=2,
    )
    checkout = paypal_ba.paypal_checkout_long_link_extracted_progress(
        email="user@example.com",
        current=1,
        total=2,
        checkout_url="https://pay.openai.com/c/pay/cs_demo",
    )

    assert approve == {
        "stage": "paypal_approve_proxy_selected",
        "email": "user@example.com",
        "current": 1,
        "total": 2,
        "proxy_label": "pool-a",
        "proxy_api_provider": "cliproxy",
        "ba_attempt": 2,
        "message": "PayPal BA 重试将使用 provider 代理执行 ChatGPT approve: socks5h://***",
    }
    assert checkout == {
        "stage": "paypal_checkout_long_link_extracted",
        "email": "user@example.com",
        "current": 1,
        "total": 2,
        "checkout_url": "https://pay.openai.com/c/pay/cs_demo",
        "message": "已通过 HTTP 协议获取 PayPal 可用长 checkout 链接，继续后续流程",
    }
