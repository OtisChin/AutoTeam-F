from autotoken.services import payment_checkout_state


def test_parse_display_amount_handles_currency_formats():
    assert payment_checkout_state.parse_display_amount("IDR 10,000.00") == 10000
    assert payment_checkout_state.parse_display_amount("Rp349,000") == 349000
    assert payment_checkout_state.parse_display_amount("$0.00") == 0
    assert payment_checkout_state.parse_display_amount("") is None


def test_extract_checkout_error_detects_visible_payment_not_approved():
    class FakePage:
        def evaluate(self, script):
            return ["开始免费试用 Plus 付款未获批准 付款方式 账单地址", "订阅"]

    class FakeApi:
        page = FakePage()

    assert (
        payment_checkout_state.extract_checkout_error(FakeApi(), body_excerpt=lambda api, limit: "") == "付款未获批准"
    )


def test_extract_checkout_error_detects_customer_location_tax_error():
    class FakePage:
        def evaluate(self, script):
            return [
                "The customer's location isn't recognized. Set a valid customer address in order to automatically calculate tax.",
                "Subscribe",
            ]

    class FakeApi:
        page = FakePage()

    error = payment_checkout_state.extract_checkout_error(FakeApi(), body_excerpt=lambda api, limit: "")

    assert "customer's location isn't recognized" in error.lower()
    assert payment_checkout_state.is_checkout_customer_location_error(error) is True


def test_extract_checkout_error_falls_back_to_body_excerpt():
    class FakePage:
        def evaluate(self, script):
            raise RuntimeError("page closed")

    class FakeApi:
        page = FakePage()

    error = payment_checkout_state.extract_checkout_error(
        FakeApi(),
        body_excerpt=lambda api, limit: "Header\nSomething went wrong. Please try again.\nFooter",
    )

    assert error == "Something went wrong"


def test_checkout_nonzero_amount_hint_uses_today_total():
    assert (
        payment_checkout_state.checkout_nonzero_amount_hint_from_text(
            "小计 IDR 349,000.00 ChatGPT Plus -IDR 349,000.00 今日应付合计 IDR 0.00"
        )
        == ""
    )
    assert (
        payment_checkout_state.checkout_nonzero_amount_hint_from_text(
            "小计 IDR 349,000.00 税 IDR 10,000.00 今日应付合计 IDR 10,000.00"
        )
        == "IDR 10,000.00"
    )
    assert (
        payment_checkout_state.checkout_nonzero_amount_hint_from_text(
            "Subtotal Rp349.000 Discount -Rp349.000 Total payment Rp1"
        )
        == "Rp1"
    )


def test_browser_checkout_nonzero_amount_hint_uses_supplied_body_excerpt():
    class FakeApi:
        pass

    hint = payment_checkout_state.browser_checkout_nonzero_amount_hint(
        FakeApi(),
        body_excerpt=lambda api, limit: "Subtotal $21.00",
    )

    assert hint == "$21.00"


def test_checkout_error_classifiers():
    assert payment_checkout_state.is_checkout_payment_not_approved_error("Payment was not approved")
    assert payment_checkout_state.is_checkout_rate_limited_error("HTTP 429 too many requests")
    assert not payment_checkout_state.is_checkout_payment_not_approved_error("HTTP 429 too many requests")
    assert payment_checkout_state.is_checkout_payment_not_approved_result(
        {"status": "failed", "failure_stage": "checkout_not_approved", "message": "付款未获批准"}
    )
    assert not payment_checkout_state.is_checkout_payment_not_approved_result(
        {"status": "success", "failure_stage": "checkout_not_approved", "message": "付款未获批准"}
    )


def test_paypal_auto_timeout_bounds_use_flow_specific_minimums_and_maximums():
    assert payment_checkout_state.bounded_timeout_seconds(None, minimum=10, maximum=20) == 10
    assert payment_checkout_state.bounded_timeout_seconds(5, minimum=10, maximum=20) == 10
    assert payment_checkout_state.bounded_timeout_seconds(15, minimum=10, maximum=20) == 15
    assert payment_checkout_state.bounded_timeout_seconds(30, minimum=10, maximum=20) == 20

    assert (
        payment_checkout_state.paypal_authorize_timeout_seconds(60)
        == payment_checkout_state.PAYPAL_AUTO_AUTHORIZE_MIN_TIMEOUT_SECONDS
    )
    assert (
        payment_checkout_state.paypal_authorize_timeout_seconds(999)
        == payment_checkout_state.PAYPAL_AUTO_AUTHORIZE_MAX_TIMEOUT_SECONDS
    )
    assert (
        payment_checkout_state.paypal_result_timeout_seconds(60)
        == payment_checkout_state.PAYPAL_AUTO_RESULT_MIN_TIMEOUT_SECONDS
    )
    assert (
        payment_checkout_state.paypal_result_timeout_seconds(999)
        == payment_checkout_state.PAYPAL_AUTO_RESULT_MAX_TIMEOUT_SECONDS
    )


def test_classify_paypal_checkout_state_detects_terminal_results():
    assert payment_checkout_state.classify_paypal_checkout_state(
        "https://www.paypal.com/checkoutnow",
        "Thanks for subscribing",
    ) == {
        "status": "success",
        "failure_stage": "",
        "message": "检测到 PayPal/支付成功页面",
    }
    assert payment_checkout_state.classify_paypal_checkout_state(
        "https://pay.openai.com/cancel",
        "",
    ) == {
        "status": "failed",
        "failure_stage": "post_submit",
        "message": "检测到 PayPal 支付已取消",
    }
    assert payment_checkout_state.classify_paypal_checkout_state(
        "https://pay.openai.com/checkout",
        "Payment pending",
    ) == {
        "status": "needs_review",
        "failure_stage": "post_submit",
        "message": "检测到 PayPal 支付处理中，需要人工确认最终状态",
    }


def test_classify_paypal_checkout_state_detects_paypal_risk_failures():
    assert payment_checkout_state.classify_paypal_checkout_state(
        "https://www.paypal.com/checkoutweb/signup",
        "We're unable to complete your request Try a different phone number.",
    ) == {
        "status": "failed",
        "failure_stage": "paypal_phone_rejected",
        "message": "PayPal 拒绝当前手机号，请更换手机号",
    }
    assert payment_checkout_state.classify_paypal_checkout_state(
        "https://www.paypal.com/checkoutweb/signup",
        "create_card_account_candidate_validation_error",
    ) == {
        "status": "failed",
        "failure_stage": "paypal_card_candidate_rejected",
        "message": "PayPal 拒绝当前卡片/身份组合，需要换卡或账单身份信息",
    }
    assert payment_checkout_state.classify_paypal_checkout_state(
        "https://www.paypal.com/checkoutweb/signup",
        "Funding source was declined",
    ) == {
        "status": "failed",
        "failure_stage": "paypal_funding_rejected",
        "message": "PayPal 拒绝当前资金来源，需要换卡/换身份信息",
    }


def test_classify_paypal_checkout_state_detects_return_success_urls():
    assert payment_checkout_state.classify_paypal_checkout_state(
        "https://pm-redirects.stripe.com/return/some_nonce?status=success",
        "",
    ) == {
        "status": "success",
        "failure_stage": "",
        "message": "检测到 PayPal/支付成功页面",
    }


def test_classify_paypal_stripe_payment_page_detects_success_statuses():
    result = payment_checkout_state.classify_paypal_stripe_payment_page(
        {
            "setup_intent": {"status": "succeeded"},
            "payment_status": "paid",
            "status": "complete",
            "submission_attempt": {"state": "complete"},
        }
    )

    assert result == {
        "status": "success",
        "failure_stage": "",
        "message": "Stripe checkout 状态已确认成功: submission_attempt='complete' setup_intent='succeeded' payment_intent='' payment_status='paid' status='complete'",
    }


def test_classify_paypal_stripe_payment_page_detects_processing_and_failure_statuses():
    processing = payment_checkout_state.classify_paypal_stripe_payment_page(
        {"session": {"submission_attempt": {"state": "requires_approval"}}, "status": "open"}
    )
    failed = payment_checkout_state.classify_paypal_stripe_payment_page(
        {"payment_intent": {"status": "requires_payment_method"}, "payment_status": "unpaid"}
    )

    assert processing["status"] == "needs_review"
    assert processing["failure_stage"] == "post_submit"
    assert "requires_approval" in processing["message"]
    assert failed["status"] == "failed"
    assert failed["failure_stage"] == "post_submit"
    assert payment_checkout_state.classify_paypal_stripe_payment_page({"status": "unknown"}) is None
    assert payment_checkout_state.classify_paypal_stripe_payment_page(None) is None


def test_infer_paypal_stage_describes_manual_payment_positions():
    assert payment_checkout_state.infer_paypal_stage("https://www.paypal.com/signin", "PayPal") == (
        "paypal_authorize",
        "已进入 PayPal 页面，等待人工完成登录/授权",
    )
    assert payment_checkout_state.infer_paypal_stage("https://pay.openai.com/c/pay/cs_123", "PayPal") == (
        "paypal_option_ready",
        "已打开支付页，可人工切换到 PayPal 继续",
    )
    assert payment_checkout_state.infer_paypal_stage("https://checkout.stripe.com/c/pay/cs_123", "Card") == (
        "checkout_opened",
        "已打开支付页，等待人工处理",
    )
    assert payment_checkout_state.infer_paypal_stage("https://chatgpt.com/checkout/test", "") == (
        "checkout_opened",
        "已打开 ChatGPT Checkout，等待人工处理",
    )
    assert payment_checkout_state.infer_paypal_stage("about:blank", "") == (
        "paypal_wait_manual",
        "等待人工完成 PayPal 支付流程",
    )


def test_paypal_risk_challenge_text_hint_detects_datadome_and_human_verification():
    assert payment_checkout_state.paypal_risk_challenge_text_hint("DataDome slider_timeout captcha_failed") is True
    assert payment_checkout_state.paypal_risk_challenge_text_hint("CONFIRM YOU'RE HUMAN") is True
    assert payment_checkout_state.paypal_risk_challenge_text_hint("安全验证 请移动滑块") is True
    assert payment_checkout_state.paypal_risk_challenge_text_hint("Payment complete") is False


def test_datadome_text_and_frame_helpers_match_paypal_ddc_artifacts():
    assert payment_checkout_state.datadome_blocked_text_hint("Access denied") is True
    assert payment_checkout_state.datadome_blocked_text_hint("您的访问已被阻止") is True
    assert payment_checkout_state.datadome_blocked_text_hint("Payment complete") is False
    assert payment_checkout_state.datadome_slider_text_hint("Slide to continue") is True
    assert payment_checkout_state.datadome_slider_text_hint("确认您是人类") is True
    assert payment_checkout_state.datadome_slider_text_hint("Card number") is False
    assert payment_checkout_state.is_datadome_frame_url("https://geo.captcha-delivery.com/captcha/?t=fe") is True
    assert payment_checkout_state.is_datadome_frame_url("https://ddc.paypal.com/challenge") is True
    assert payment_checkout_state.is_datadome_frame_url("https://hcaptcha.com/challenge") is False


def test_paypal_signup_otp_text_hint_detects_strict_and_loose_prompts():
    assert payment_checkout_state.paypal_signup_otp_text_hint("Enter your code We sent a 6-digit code") is True
    assert payment_checkout_state.paypal_signup_otp_text_hint("セキュリティコードを送信しました") is True
    assert (
        payment_checkout_state.paypal_signup_otp_text_hint(
            "この番号を確認するためのセキュリティコードをSMSでお客さまに送信します。"
        )
        is False
    )
    assert payment_checkout_state.paypal_signup_otp_text_hint("check your phone") is False
    assert payment_checkout_state.paypal_signup_otp_text_hint("check your phone", loose=True) is True
    assert payment_checkout_state.paypal_signup_otp_entry_text_hint("Security code") is True
    assert payment_checkout_state.paypal_signup_otp_entry_text_hint("check your phone") is False


def test_paypal_signup_registration_text_hints_detect_form_markers():
    assert payment_checkout_state.paypal_signup_registration_text_hint("Card number Billing address") is True
    assert (
        payment_checkout_state.paypal_signup_registration_text_hint("Pay with debit or credit card and create password")
        is True
    )
    assert payment_checkout_state.paypal_signup_registration_text_hint("電話番号だけ") is False
    assert payment_checkout_state.paypal_signup_registration_form_text_visible("Card number Create password") is True
    assert payment_checkout_state.paypal_signup_registration_form_text_visible("Card number only") is False


def test_paypal_login_passkey_and_approve_text_hints():
    assert payment_checkout_state.paypal_login_text_hint("Welcome back, log in to continue") is True
    assert payment_checkout_state.paypal_login_text_hint("Create an account") is False
    assert payment_checkout_state.paypal_passkey_text_hint("Use password instead or try another way") is True
    assert payment_checkout_state.paypal_passkey_text_hint("Password field") is False
    assert payment_checkout_state.paypal_approve_text_hint("Agree and continue to authorize") is True
    assert payment_checkout_state.paypal_approve_text_hint("Create account") is False


def test_paypal_rejected_text_hints_match_configured_hints_case_insensitively():
    phone_hints = ("try a different phone number", "別の電話番号")
    card_hints = ("card already linked", "try a different card")

    assert (
        payment_checkout_state.paypal_phone_rejected_text_hint(
            "TRY A DIFFERENT PHONE NUMBER",
            hints=phone_hints,
        )
        is True
    )
    assert (
        payment_checkout_state.paypal_phone_rejected_text_hint("別の電話番号をお試しください", hints=phone_hints)
        is True
    )
    assert payment_checkout_state.paypal_phone_rejected_text_hint("", hints=phone_hints) is False
    assert payment_checkout_state.paypal_card_rejected_text_hint("This card already linked.", hints=card_hints) is True
    assert payment_checkout_state.paypal_card_rejected_text_hint("Payment approved", hints=card_hints) is False


def test_paypal_url_classifiers_detect_hosts_and_return_urls():
    assert payment_checkout_state.safe_host("https://www.paypal.com/pay") == "www.paypal.com"
    assert payment_checkout_state.is_paypal_host("https://www.paypal.com/pay") is True
    assert payment_checkout_state.is_paypal_host("https://evilpaypal.com/pay") is False
    assert payment_checkout_state.is_checkout_host("https://pay.openai.com/c/pay/cs_123") is True
    assert payment_checkout_state.is_checkout_host("https://checkout.stripe.com/c/pay/cs_123") is True
    assert payment_checkout_state.is_checkout_host("https://chatgpt.com/checkout/test") is True
    assert payment_checkout_state.is_checkout_host("https://chatgpt.com/") is False
    assert payment_checkout_state.is_chatgpt_or_openai_return_url("https://chatgpt.com/payments/success") is True
    assert payment_checkout_state.is_chatgpt_or_openai_return_url("https://api.openai.com/return") is True
    assert payment_checkout_state.is_chatgpt_or_openai_return_url("https://example.com/return") is False


def test_is_paypal_ssl_protocol_error_page_requires_paypal_context():
    assert (
        payment_checkout_state.is_paypal_ssl_protocol_error_page(
            "https://www.paypal.com/pay",
            "ERR_SSL_PROTOCOL_ERROR",
        )
        is True
    )
    assert (
        payment_checkout_state.is_paypal_ssl_protocol_error_page(
            "chrome-error://chromewebdata/",
            "This site can't provide a secure connection paypal.com sent an invalid response",
        )
        is True
    )
    assert (
        payment_checkout_state.is_paypal_ssl_protocol_error_page(
            "https://example.com/",
            "ERR_SSL_PROTOCOL_ERROR",
        )
        is False
    )


def test_paypal_autofill_allowed_rejects_paypal_and_allows_checkout_hosts():
    assert payment_checkout_state.paypal_autofill_allowed("https://www.paypal.com/checkout") is False
    assert payment_checkout_state.paypal_autofill_allowed("https://evilpaypal.com/checkout") is False
    assert payment_checkout_state.paypal_autofill_allowed("https://pay.openai.com/c/pay/cs_123") is True
    assert payment_checkout_state.paypal_autofill_allowed("https://checkout.stripe.com/c/pay/cs_123") is True
    assert payment_checkout_state.paypal_autofill_allowed("https://hooks.stripe.com/redirect") is True
    assert payment_checkout_state.paypal_autofill_allowed("https://example.com/checkout") is False


def test_is_paypal_pay_entry_url_matches_only_paypal_pay_path():
    assert payment_checkout_state.is_paypal_pay_entry_url("https://www.paypal.com/pay?token=BA-DEMO") is True
    assert payment_checkout_state.is_paypal_pay_entry_url("https://www.paypal.com/pay/") is True
    assert payment_checkout_state.is_paypal_pay_entry_url("https://www.paypal.com/agreements/approve") is False
    assert payment_checkout_state.is_paypal_pay_entry_url("https://evilpaypal.com/pay") is False


def test_paypal_protocol_browser_fallback_rules_require_risk_or_transient_error():
    assert payment_checkout_state.paypal_protocol_transient_transport_error(
        "Failed to perform, curl: (28) Recv failure: Connection was reset."
    )
    assert payment_checkout_state.paypal_protocol_needs_browser_fallback(
        {
            "status": "failed",
            "failure_stage": "paypal_protocol",
            "message": "Failed to perform, curl: (28) Recv failure: Connection was reset.",
            "paypal_approve_url": "https://www.paypal.com/agreements/approve?ba_token=BA-DEMO",
        }
    )
    assert payment_checkout_state.paypal_protocol_needs_browser_fallback(
        {
            "status": "failed",
            "failure_stage": "paypal_human_verification",
            "ba_token": "BA-DEMO",
        }
    )
    assert (
        payment_checkout_state.paypal_protocol_needs_browser_fallback(
            {
                "status": "failed",
                "failure_stage": "paypal_protocol",
                "message": "checkout session missing paypal payment method",
                "paypal_approve_url": "https://www.paypal.com/agreements/approve?ba_token=BA-DEMO",
            }
        )
        is False
    )
    assert (
        payment_checkout_state.paypal_protocol_needs_browser_fallback(
            {
                "status": "success",
                "failure_stage": "paypal_human_verification",
                "ba_token": "BA-DEMO",
            }
        )
        is False
    )
    assert (
        payment_checkout_state.paypal_protocol_needs_browser_fallback(
            {
                "status": "failed",
                "failure_stage": "paypal_protocol_authorize",
            }
        )
        is False
    )
    assert payment_checkout_state.classify_paypal_checkout_state(
        "https://chatgpt.com/payments/success?session_id=abc",
        "",
    ) == {
        "status": "success",
        "failure_stage": "",
        "message": "检测到 PayPal/支付成功页面",
    }
