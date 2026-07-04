from autotoken import api, gopay_executor
from autotoken.services import payment_results


def test_bind_card_reusable_result_matches_checkout_failure_stages():
    assert payment_results.is_bind_card_reusable_result({"status": "failed", "failure_stage": "open_checkout"}) is True
    assert payment_results.is_bind_card_reusable_result({"status": "failed", "failure_stage": "fill_card"}) is True
    assert payment_results.is_bind_card_reusable_result({"status": "success", "failure_stage": "open_checkout"}) is False
    assert payment_results.is_bind_card_reusable_result({"status": "failed", "failure_stage": "submit_checkout"}) is False
    assert payment_results.is_bind_card_reusable_result(None) is False


def test_gopay_checkout_not_approved_adds_actual_email_once():
    result = {
        "failure_stage": "checkout_not_approved",
        "message": "payment was not approved",
        "rejected_emails": ["FIRST@example.com", "first@example.com"],
    }

    assert payment_results.is_gopay_checkout_not_approved_result(result) is True
    assert payment_results.gopay_rejected_pool_emails(result, "SECOND@example.com") == [
        "first@example.com",
        "second@example.com",
    ]


def test_gopay_pool_classifiers_include_actual_email_by_failure_stage():
    assert payment_results.gopay_nonzero_blocked_pool_emails(
        {"failure_stage": "midtrans_charge_guard", "nonzero_blocked_emails": ["FIRST@example.com"]},
        "second@example.com",
    ) == ["first@example.com", "second@example.com"]
    assert payment_results.gopay_payment_failed_pool_emails(
        {"failure_stage": "gopay_payment_process", "payment_failed_emails": ["FIRST@example.com"]},
        "second@example.com",
    ) == ["first@example.com", "second@example.com"]
    assert payment_results.gopay_token_invalidated_pool_emails(
        {"status": "failed", "message": "Authentication token has been invalidated"},
        "USER@example.com",
    ) == ["user@example.com"]


def test_gopay_pending_retry_reason_preserves_rotation_rules():
    assert (
        payment_results.gopay_pending_retry_reason(
            {"status": "failed", "failure_stage": "gopay_payment_process", "message": '"code":"201" GOPAY_WALLET'}
        )
        == "gopay_payment_process"
    )
    assert (
        payment_results.gopay_pending_retry_reason(
            {"status": "failed", "failure_stage": "browser_checkout", "message": "too many attempts"}
        )
        == "rate_limited"
    )
    assert (
        payment_results.gopay_pending_retry_reason(
            {"status": "failed", "failure_stage": "post_submit", "message": "HTTP 403 forbidden"}
        )
        == "http_403"
    )
    assert payment_results.gopay_pending_retry_reason({"status": "failed", "failure_stage": "fetch_otp"}) == "gopay_otp"
    assert (
        payment_results.gopay_pending_retry_reason(
            {"status": "failed", "failure_stage": "midtrans_linking", "message": "already linked"}
        )
        == "gopay_already_linked"
    )
    assert (
        payment_results.gopay_pending_retry_reason(
            {"status": "failed", "failure_stage": "browser_charge_guard", "message": "今日应付非 0"}
        )
        == ""
    )
    assert (
        payment_results.gopay_pending_retry_reason(
            {"status": "failed", "failure_stage": "post_submit", "message": "Authentication token has been invalidated"}
        )
        == ""
    )


def test_gopay_pending_retry_source_stage_preserves_progress_stages():
    assert (
        payment_results.gopay_pending_retry_source_stage({}, "gopay_payment_process")
        == "gopay_payment_process_failed_rotate"
    )
    assert payment_results.gopay_pending_retry_source_stage({}, "rate_limited") == "gopay_rate_limited_retry"
    assert (
        payment_results.gopay_pending_retry_source_stage({}, "gopay_wallet_no_numbers")
        == "gopay_wallet_no_numbers_retry"
    )
    assert payment_results.gopay_pending_retry_source_stage({}, "gopay_otp") == "gopay_otp_retry"
    assert payment_results.gopay_pending_retry_source_stage({}, "http_403") == "gopay_retryable_failure_rotate"


def test_chatgpt_user_paid_success_preserves_existing_payload_and_fallbacks():
    payload = payment_results.chatgpt_user_paid_success(
        {"status": "failed", "failure_stage": "chatgpt_approve", "checkout_url": ""},
        checkout_url="https://checkout.example",
        billing_info={"email": "billing@example.com"},
    )
    existing = payment_results.chatgpt_user_paid_success(
        {"checkout_url": "https://existing.example", "billing_info": {"email": "existing@example.com"}},
        checkout_url="https://checkout.example",
        billing_info={"email": "billing@example.com"},
    )

    assert payload["status"] == "success"
    assert payload["failure_stage"] == ""
    assert payload["user_paid_skip"] is True
    assert payload["checkout_url"] == "https://checkout.example"
    assert payload["billing_info"] == {"email": "billing@example.com"}
    assert existing["checkout_url"] == "https://existing.example"
    assert existing["billing_info"] == {"email": "existing@example.com"}


def test_chatgpt_approve_blocked_message_preserves_takeover_guidance():
    payload = {"result": "blocked", "detail": "risk"}
    message = payment_results.chatgpt_approve_blocked_message(payload)

    assert "ChatGPT approve 未通过: {'result': 'blocked', 'detail': 'risk'}" in message
    assert "ChatGPT checkout approve 被风控拦截" in message
    assert "pm-redirects.stripe.com / app.midtrans.com/snap" in message
    assert gopay_executor._chatgpt_approve_blocked_message(payload) == message


def test_paypal_result_classifiers_preserve_retry_rules():
    assert payment_results.paypal_nonzero_blocked_pool_emails(
        {"failure_stage": "extract_ba_link_nonzero_amount", "nonzero_blocked_emails": ["FIRST@example.com"]},
        "second@example.com",
    ) == ["first@example.com", "second@example.com"]
    assert (
        payment_results.paypal_pending_retry_reason({"status": "failed", "failure_stage": "paypal_phone_rejected"})
        == "paypal_phone_rejected"
    )
    assert (
        payment_results.paypal_pending_retry_reason(
            {"status": "failed", "failure_stage": "paypal_checkout_proxy_country_mismatch"}
        )
        == "paypal_checkout_proxy_country_mismatch"
    )
    assert (
        payment_results.paypal_pending_retry_reason({"status": "needs_review", "failure_stage": ""}) == "needs_review"
    )
    assert (
        payment_results.paypal_pending_retry_reason(
            {"status": "failed", "message": "net::ERR_TUNNEL_CONNECTION_FAILED"}
        )
        == "transient_paypal_flow"
    )
    assert (
        payment_results.paypal_pending_retry_reason({"status": "failed", "failure_stage": "browser_charge_guard"}) == ""
    )
    assert payment_results.paypal_pending_retry_source_stage({"failure_stage": ""}, "proxy_api") == "proxy_api"


def test_api_keeps_payment_result_compatibility_aliases():
    assert api._is_bind_card_reusable_result is payment_results.is_bind_card_reusable_result
    assert api._is_gopay_checkout_not_approved_result is payment_results.is_gopay_checkout_not_approved_result
    assert api._gopay_pending_retry_reason is payment_results.gopay_pending_retry_reason
    assert api._gopay_pending_retry_source_stage is payment_results.gopay_pending_retry_source_stage
    assert api._as_chatgpt_user_paid_success is payment_results.chatgpt_user_paid_success
    assert api._paypal_pending_retry_reason is payment_results.paypal_pending_retry_reason
    assert api._paypal_pending_retry_source_stage is payment_results.paypal_pending_retry_source_stage
