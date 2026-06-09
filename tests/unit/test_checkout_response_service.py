from autotoken import api
from autotoken.services import checkout_response


def test_html_and_cloudflare_detection_are_stable():
    assert checkout_response.looks_like_html_error("<!doctype html><html><head></head></html>") is True
    assert checkout_response.looks_like_html_error("plain text") is False
    assert checkout_response.looks_like_cloudflare_challenge("Enable JavaScript and cookies to continue") is True
    assert checkout_response.looks_like_cloudflare_challenge("verify you are human") is True
    assert checkout_response.looks_like_cloudflare_challenge("ordinary upstream error") is False


def test_friendly_checkout_error_handles_html_and_forbidden_text():
    assert checkout_response.friendly_checkout_error("", 503) == "上游错误(503)"
    assert "HTML 风控页" in checkout_response.friendly_checkout_error("<html><head></head></html>", 403)
    assert "HTTP 502" in checkout_response.friendly_checkout_error("<html><body>bad</body></html>", 502)
    assert "上游 403 拦截" in checkout_response.friendly_checkout_error("Forbidden", 403)
    assert checkout_response.friendly_checkout_error("plain detail", 500) == "plain detail"


def test_parse_checkout_response_json_wraps_non_dict_and_non_json_payloads():
    assert checkout_response.parse_checkout_response_json('{"url":"https://pay.example"}') == {
        "url": "https://pay.example"
    }
    assert checkout_response.parse_checkout_response_json("[1,2]") == {"data": [1, 2]}
    assert checkout_response.parse_checkout_response_json("not-json") == {"detail": "not-json"}
    assert checkout_response.parse_checkout_response_json("") == {}


def test_find_hosted_checkout_url_searches_nested_payloads_breadth_first():
    payload = {
        "outer": [
            {"ignored": "https://example.com/c/pay/cs_bad"},
            {"nested": {"url": " https://checkout.stripe.com/c/pay/cs_stripe "}},
        ],
        "later": {"url": "https://pay.openai.com/c/pay/cs_openai"},
    }

    assert checkout_response.find_hosted_checkout_url(payload) == "https://pay.openai.com/c/pay/cs_openai"
    assert checkout_response.find_hosted_checkout_url({"url": "https://example.com/c/pay/cs_bad"}) == ""


def test_choose_checkout_error_status_preserves_client_retriable_statuses():
    assert checkout_response.choose_checkout_error_status(400) == 400
    assert checkout_response.choose_checkout_error_status(429) == 429
    assert checkout_response.choose_checkout_error_status(500) == 502


def test_normalize_checkout_payload_for_http_adds_plus_defaults_and_billing_uppercase():
    payload = checkout_response.normalize_checkout_payload_for_http(
        {
            "billing_details": {"country": " jp ", "currency": " jpy "},
            "checkout_ui_mode": "Hosted",
        }
    )

    assert payload["plan_name"] == "chatgptplusplan"
    assert payload["entry_point"] == "all_plans_pricing_modal"
    assert payload["promo_campaign"] == {
        "promo_campaign_id": "plus-1-month-free",
        "is_coupon_from_query_param": False,
    }
    assert payload["billing_details"] == {"country": "JP", "currency": "JPY"}
    assert payload["checkout_ui_mode"] == "hosted"


def test_normalize_checkout_payload_for_http_preserves_non_plus_plan_and_custom_mode():
    payload = checkout_response.normalize_checkout_payload_for_http(
        {"plan_name": "enterprise", "billing_details": {}, "checkout_ui_mode": "embedded"}
    )

    assert payload["plan_name"] == "enterprise"
    assert "entry_point" not in payload
    assert "promo_campaign" not in payload
    assert payload["billing_details"] == {"country": "US", "currency": "USD"}
    assert payload["checkout_ui_mode"] == "custom"


def test_api_keeps_checkout_response_compatibility_wrappers():
    assert api._parse_checkout_response_json("[1]") == {"data": [1]}
    assert api._find_hosted_checkout_url({"url": "https://pay.openai.com/c/pay/cs_demo"}) == (
        "https://pay.openai.com/c/pay/cs_demo"
    )
    assert api._choose_checkout_error_status(503) == 502
