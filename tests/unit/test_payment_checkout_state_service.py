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
