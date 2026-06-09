import pytest

from autotoken.services import paypal_preflight


class PayPalParamsStub:
    def __init__(self, **kwargs):
        defaults = {
            "manual_confirm": False,
            "autofill_enabled": False,
            "paypal_email": "",
            "paypal_password": "",
            "billing_phone": "",
            "billing_name": "",
            "billing_country": "",
            "billing_state": "",
            "billing_city": "",
            "billing_zip": "",
            "billing_address1": "",
            "paypal_card_number": "",
            "paypal_card_expiry": "",
            "paypal_card_cvv": "",
            "email": "",
            "account_emails": [],
            "checkout_url": "",
            "sms_url": "",
            "otp_channel": "sms",
        }
        defaults.update(kwargs)
        self.__dict__.update(defaults)


def test_normalize_paypal_runner_and_mode_aliases():
    assert paypal_preflight.normalize_paypal_runner_mode("") == "manual_checkout"
    assert paypal_preflight.normalize_paypal_runner_mode(" manual_checkout ") == "manual_checkout"
    assert paypal_preflight.normalize_paypal_mode("existing-account") == "existing_account"
    assert paypal_preflight.normalize_paypal_mode("signup") == "create_account"
    assert paypal_preflight.normalize_paypal_mode_legacy("") == "existing_account"
    assert paypal_preflight.normalize_paypal_mode_legacy("register") == "create_account"
    assert paypal_preflight.normalize_paypal_mode_legacy("custom-mode") == "custom-mode"

    with pytest.raises(ValueError, match="不支持的 PayPal 运行模式"):
        paypal_preflight.normalize_paypal_runner_mode("legacy_pipeline")
    with pytest.raises(ValueError, match="paypal_mode 只支持 existing_account 或 create_account"):
        paypal_preflight.normalize_paypal_mode("bad")


def test_normalize_paypal_country_and_lang_helpers():
    assert paypal_preflight.normalize_paypal_country(" jp ") == "JP"
    assert paypal_preflight.normalize_paypal_country("", fallback="ca") == "CA"
    assert paypal_preflight.normalize_paypal_country("123") == "US"
    assert paypal_preflight.normalize_paypal_lang("EN-US", country="JP") == "en"
    assert paypal_preflight.normalize_paypal_lang("", country="JP") == "ja"
    assert paypal_preflight.normalize_paypal_lang("", country="US") == "en"


@pytest.mark.parametrize("value", ["1", "true", "TRUE", " yes ", "on"])
def test_paypal_stop_before_signup_otp_enabled_accepts_truthy_values(value):
    assert paypal_preflight.paypal_stop_before_signup_otp_enabled(value) is True


@pytest.mark.parametrize("value", ["", None, "0", "false", "off", "no", "enabled"])
def test_paypal_stop_before_signup_otp_enabled_rejects_other_values(value):
    assert paypal_preflight.paypal_stop_before_signup_otp_enabled(value) is False


def test_paypal_task_scalar_normalizers_preserve_existing_bounds():
    assert paypal_preflight.normalize_pending_retry_attempts(None) == 1
    assert paypal_preflight.normalize_pending_retry_attempts("bad") == 1
    assert paypal_preflight.normalize_pending_retry_attempts("-1") == 0
    assert paypal_preflight.normalize_pending_retry_attempts("99") == 3
    assert paypal_preflight.normalize_paypal_concurrency(None) == 1
    assert paypal_preflight.normalize_paypal_concurrency("bad") == 1
    assert paypal_preflight.normalize_paypal_concurrency("0") == 1
    assert paypal_preflight.normalize_paypal_concurrency("99") == 3


def test_validate_paypal_timeout_seconds_rejects_negative_values():
    paypal_preflight.validate_paypal_timeout_seconds(0)

    with pytest.raises(ValueError, match="超时时间不能为负数"):
        paypal_preflight.validate_paypal_timeout_seconds(-1)


def test_normalize_paypal_task_inputs_trims_and_deduplicates_values():
    params = PayPalParamsStub(
        email=" User@Example.COM ",
        account_emails=[" user@example.com ", "SECOND@example.com", "second@example.com", ""],
        checkout_url=" https://checkout.example/path ",
        sms_url=" https://sms.example/poll ",
        otp_channel=" WhatsApp ",
    )

    result = paypal_preflight.normalize_paypal_task_inputs(
        params=params,
        normalize_email=lambda value: str(value or "").strip().lower(),
    )

    assert result == {
        "email": "user@example.com",
        "account_emails": ["user@example.com", "second@example.com"],
        "checkout_url": "https://checkout.example/path",
        "sms_url": "https://sms.example/poll",
        "otp_channel": "whatsapp",
    }


def test_include_primary_paypal_account_email_preserves_batch_rules():
    assert paypal_preflight.include_primary_paypal_account_email([], "primary@example.com") == []
    assert paypal_preflight.include_primary_paypal_account_email(
        ["primary@example.com", "other@example.com"],
        "primary@example.com",
    ) == ["primary@example.com", "other@example.com"]
    assert paypal_preflight.include_primary_paypal_account_email(
        ["other@example.com"],
        "primary@example.com",
    ) == ["primary@example.com", "other@example.com"]


def test_resolve_paypal_task_sms_url_applies_whatsapp_auto_register_default_only_when_needed():
    calls = []

    def default_whatsapp_sms_url():
        calls.append("called")
        return "http://127.0.0.1:8787/api/public/whatsapp-otp/latest"

    assert (
        paypal_preflight.resolve_paypal_task_sms_url(
            sms_url="",
            manual_confirm=False,
            paypal_mode="create_account",
            otp_channel="whatsapp",
            default_whatsapp_sms_url=default_whatsapp_sms_url,
        )
        == "http://127.0.0.1:8787/api/public/whatsapp-otp/latest"
    )
    assert calls == ["called"]
    assert (
        paypal_preflight.resolve_paypal_task_sms_url(
            sms_url="https://sms.example",
            manual_confirm=True,
            paypal_mode="create_account",
            otp_channel="whatsapp",
            default_whatsapp_sms_url=default_whatsapp_sms_url,
        )
        == "https://sms.example"
    )
    assert (
        paypal_preflight.resolve_paypal_task_sms_url(
            sms_url="https://sms.example",
            manual_confirm=False,
            paypal_mode="existing_account",
            otp_channel="whatsapp",
            default_whatsapp_sms_url=default_whatsapp_sms_url,
        )
        == "https://sms.example"
    )
    assert calls == ["called"]


def test_resolve_effective_paypal_concurrency_limits_create_account_by_phone_count():
    result = paypal_preflight.resolve_effective_paypal_concurrency(
        paypal_mode="create_account",
        phone_account_count=2,
        paypal_concurrency=3,
        paypal_browser="chromium",
        roxybrowser_profile_id="",
        roxybrowser_auto_create_profile=False,
    )

    assert result == {
        "concurrency": 2,
        "progress_events": [
            {
                "stage": "paypal_concurrency_limited",
                "requested_concurrency": 3,
                "concurrency": 2,
                "message": "PayPal 自动注册并发已按可独占的手机号数量限制",
                "level": "warn",
            }
        ],
    }


def test_resolve_effective_paypal_concurrency_limits_roxybrowser_single_profile():
    result = paypal_preflight.resolve_effective_paypal_concurrency(
        paypal_mode="existing_account",
        phone_account_count=0,
        paypal_concurrency=3,
        paypal_browser="roxybrowser",
        roxybrowser_profile_id="profile-1",
        roxybrowser_auto_create_profile=False,
    )

    assert result == {
        "concurrency": 1,
        "progress_events": [
            {
                "stage": "paypal_concurrency_limited",
                "requested_concurrency": 3,
                "concurrency": 1,
                "message": "RoxyBrowser 单 Profile 不能并发复用，PayPal 并发已降为 1",
                "level": "warn",
            }
        ],
    }


def test_resolve_effective_paypal_concurrency_preserves_combined_limit_event_order():
    result = paypal_preflight.resolve_effective_paypal_concurrency(
        paypal_mode="create_account",
        phone_account_count=1,
        paypal_concurrency=3,
        paypal_browser="roxybrowser",
        roxybrowser_profile_id="profile-1",
        roxybrowser_auto_create_profile=False,
    )

    assert result["concurrency"] == 1
    assert [event["message"] for event in result["progress_events"]] == [
        "PayPal 自动注册并发已按可独占的手机号数量限制",
        "RoxyBrowser 单 Profile 不能并发复用，PayPal 并发已降为 1",
    ]


def test_paypal_locale_redirect_url_updates_country_and_locale_query():
    url = paypal_preflight.paypal_locale_redirect_url(
        "https://www.paypal.com/checkoutweb/signup?ba_token=BA-DEMO&country.x=US#frag",
        country="jp",
        lang="",
    )

    assert url == "https://www.paypal.com/checkoutweb/signup?ba_token=BA-DEMO&country.x=JP&locale.x=ja_JP#frag"
    assert (
        paypal_preflight.paypal_locale_redirect_url(
            "https://www.paypal.com/checkoutweb/signup?country.x=JP&locale.x=ja_JP",
            country="JP",
            lang="ja",
        )
        == ""
    )


def test_normalize_paypal_runtime_options_defaults_jp_nocard_to_pure_protocol():
    result = paypal_preflight.normalize_paypal_runtime_options(
        paypal_mode="create_account",
        paypal_browser="protocol",
        paypal_fallback_browser="",
        paypal_region="JP_NOCARD",
        paypal_country="US",
        billing_country="US",
        paypal_lang="",
        bind_link_payload={"billing_details": {"country": "JP", "currency": "JPY"}},
        roxybrowser_workspace_id="workspace-1",
        roxybrowser_profile_id="profile-1",
        roxybrowser_auto_create_profile=False,
        paypal_card_number="",
        paypal_card_expiry="",
        paypal_card_cvv="",
    )

    assert result["paypal_browser"] == "protocol"
    assert result["paypal_fallback_browser"] == ""
    assert result["paypal_region"] == "JP_NOCARD"
    assert result["paypal_country"] == "JP"
    assert result["paypal_lang"] == "ja"
    assert result["protocol_no_card"] is True
    assert result["bind_link_payload"]["billing_details"] == {"country": "US", "currency": "USD"}
    assert result["bind_link_payload"]["checkout_ui_mode"] == "hosted"
    assert result["roxybrowser_profile_id"] == "profile-1"


def test_normalize_paypal_runtime_options_preserves_disabled_fallback_for_jp_nocard():
    result = paypal_preflight.normalize_paypal_runtime_options(
        paypal_mode="create_account",
        paypal_browser="protocol",
        paypal_fallback_browser="disabled",
        paypal_region="JP_NOCARD",
        paypal_country="US",
        billing_country="US",
        paypal_lang="",
        bind_link_payload={},
        roxybrowser_workspace_id="workspace-1",
        roxybrowser_profile_id="profile-1",
        roxybrowser_auto_create_profile=False,
        paypal_card_number="",
        paypal_card_expiry="",
        paypal_card_cvv="",
    )

    assert result["paypal_browser"] == "protocol"
    assert result["paypal_fallback_browser"] == "disabled"
    assert result["paypal_country"] == "JP"
    assert result["protocol_no_card"] is True


def test_normalize_paypal_runtime_options_defaults_and_roxybrowser_auto_create():
    result = paypal_preflight.normalize_paypal_runtime_options(
        paypal_mode="existing_account",
        paypal_browser="roxy-browser",
        paypal_fallback_browser="",
        paypal_region="",
        paypal_country="",
        billing_country="CA",
        paypal_lang="EN-US",
        bind_link_payload=None,
        roxybrowser_workspace_id=" workspace-1 ",
        roxybrowser_profile_id=" profile-1 ",
        roxybrowser_auto_create_profile=True,
        paypal_card_number="4111111111111111",
        paypal_card_expiry="03/30",
        paypal_card_cvv="123",
    )

    assert result["paypal_browser"] == "roxy-browser"
    assert result["paypal_country"] == "CA"
    assert result["paypal_lang"] == "en"
    assert result["protocol_no_card"] is False
    assert result["bind_link_payload"] == {}
    assert result["roxybrowser_workspace_id"] == "workspace-1"
    assert result["roxybrowser_profile_id"] == ""
    assert result["roxybrowser_auto_create_profile"] is True


def test_normalize_paypal_bind_task_runtime_options_preserves_executor_defaults_and_aliases():
    result = paypal_preflight.normalize_paypal_bind_task_runtime_options(
        manual_confirm=False,
        paypal_mode="create-account",
        paypal_browser=" Protocol ",
        paypal_fallback_browser=" roxy-browser ",
        paypal_country="jp",
        paypal_lang="",
        proxy_url=" socks5://proxy.example:1080 ",
        proxy_bypass=" localhost ",
        roxybrowser_workspace_id=" workspace-1 ",
        roxybrowser_profile_id=" profile-1 ",
        paypal_card_number="",
        paypal_card_expiry="",
        paypal_card_cvv="",
    )

    assert result == {
        "auto_mode": True,
        "paypal_mode": "create_account",
        "paypal_browser": "protocol",
        "paypal_fallback_browser": "roxy-browser",
        "paypal_country": "JP",
        "paypal_lang": "ja",
        "protocol_mode": True,
        "use_camoufox": False,
        "use_roxybrowser": False,
        "browser_fallback_enabled": True,
        "fallback_use_roxybrowser": True,
        "fallback_use_camoufox": False,
        "launch_proxy_url": "socks5://proxy.example:1080",
        "launch_proxy_bypass": "localhost",
        "roxybrowser_workspace_id": "workspace-1",
        "roxybrowser_profile_id": "profile-1",
    }


def test_normalize_paypal_bind_task_runtime_options_defaults_to_chromium_camoufox_fallback():
    result = paypal_preflight.normalize_paypal_bind_task_runtime_options(
        manual_confirm=True,
        paypal_mode="",
        paypal_browser="",
        paypal_fallback_browser="",
        paypal_country="",
        paypal_lang="EN-US",
        proxy_url="",
        proxy_bypass=None,
        roxybrowser_workspace_id="",
        roxybrowser_profile_id="",
        paypal_card_number="4111111111111111",
        paypal_card_expiry="03/30",
        paypal_card_cvv="123",
    )

    assert result["auto_mode"] is False
    assert result["paypal_mode"] == "existing_account"
    assert result["paypal_browser"] == "chromium"
    assert result["paypal_country"] == "US"
    assert result["paypal_lang"] == "en"
    assert result["protocol_mode"] is False
    assert result["use_camoufox"] is False
    assert result["use_roxybrowser"] is False
    assert result["browser_fallback_enabled"] is True
    assert result["fallback_use_roxybrowser"] is False
    assert result["fallback_use_camoufox"] is True
    assert result["launch_proxy_url"] is None
    assert result["launch_proxy_bypass"] is None


def test_normalize_paypal_bind_task_runtime_options_defaults_protocol_to_no_browser_fallback():
    result = paypal_preflight.normalize_paypal_bind_task_runtime_options(
        manual_confirm=False,
        paypal_mode="create_account",
        paypal_browser="protocol",
        paypal_fallback_browser="",
        paypal_country="JP",
        paypal_lang="ja",
        proxy_url="",
        proxy_bypass=None,
        roxybrowser_workspace_id="",
        roxybrowser_profile_id="",
        paypal_card_number="",
        paypal_card_expiry="",
        paypal_card_cvv="",
    )

    assert result["protocol_mode"] is True
    assert result["browser_fallback_enabled"] is False
    assert result["fallback_use_roxybrowser"] is False
    assert result["fallback_use_camoufox"] is False


def test_normalize_paypal_bind_task_runtime_options_disables_browser_fallback():
    result = paypal_preflight.normalize_paypal_bind_task_runtime_options(
        manual_confirm=False,
        paypal_mode="create_account",
        paypal_browser="protocol",
        paypal_fallback_browser="disabled",
        paypal_country="JP",
        paypal_lang="ja",
        proxy_url="",
        proxy_bypass=None,
        roxybrowser_workspace_id="",
        roxybrowser_profile_id="",
        paypal_card_number="",
        paypal_card_expiry="",
        paypal_card_cvv="",
    )

    assert result["browser_fallback_enabled"] is False
    assert result["fallback_use_camoufox"] is False
    assert result["fallback_use_roxybrowser"] is False


def test_validate_paypal_task_request_rejects_common_input_errors():
    params = PayPalParamsStub()

    with pytest.raises(ValueError, match="email 不能为空"):
        paypal_preflight.validate_paypal_task_request(
            params=params,
            email="",
            checkout_url="https://checkout.example",
            bind_link_payload={},
            paypal_mode="existing_account",
            otp_channel="sms",
            sms_url="",
            protocol_no_card=False,
        )

    with pytest.raises(ValueError, match="otp_channel 只支持 sms 或 whatsapp"):
        paypal_preflight.validate_paypal_task_request(
            params=params,
            email="user@example.com",
            checkout_url="https://checkout.example",
            bind_link_payload={},
            paypal_mode="existing_account",
            otp_channel="email",
            sms_url="",
            protocol_no_card=False,
        )

    with pytest.raises(ValueError, match="checkout_url 不能为空"):
        paypal_preflight.validate_paypal_task_request(
            params=params,
            email="user@example.com",
            checkout_url="",
            bind_link_payload={},
            paypal_mode="existing_account",
            otp_channel="sms",
            sms_url="",
            protocol_no_card=False,
        )


def test_validate_paypal_task_request_rejects_manual_confirm_autofill_conflict():
    params = PayPalParamsStub(manual_confirm=True, autofill_enabled=True)

    with pytest.raises(ValueError, match="手动确认模式与自动生成账单信息不能同时开启"):
        paypal_preflight.validate_paypal_task_request(
            params=params,
            email="user@example.com",
            checkout_url="https://checkout.example",
            bind_link_payload={},
            paypal_mode="existing_account",
            otp_channel="sms",
            sms_url="",
            protocol_no_card=False,
        )


def test_validate_paypal_task_request_requires_existing_account_credentials():
    params = PayPalParamsStub()

    with pytest.raises(ValueError, match="已有账号模式需要 paypal_email"):
        paypal_preflight.validate_paypal_task_request(
            params=params,
            email="user@example.com",
            checkout_url="https://checkout.example",
            bind_link_payload={},
            paypal_mode="existing_account",
            otp_channel="sms",
            sms_url="",
            protocol_no_card=False,
        )

    params.paypal_email = "paypal@example.com"
    with pytest.raises(ValueError, match="已有账号模式需要 paypal_password"):
        paypal_preflight.validate_paypal_task_request(
            params=params,
            email="user@example.com",
            checkout_url="https://checkout.example",
            bind_link_payload={},
            paypal_mode="existing_account",
            otp_channel="sms",
            sms_url="",
            protocol_no_card=False,
        )


def test_validate_paypal_task_request_checks_create_account_fields_and_protocol_no_card():
    params = PayPalParamsStub(billing_phone="+15550001")

    with pytest.raises(ValueError, match="自动注册模式需要 sms_url"):
        paypal_preflight.validate_paypal_task_request(
            params=params,
            email="user@example.com",
            checkout_url="https://checkout.example",
            bind_link_payload={},
            paypal_mode="create_account",
            otp_channel="sms",
            sms_url="",
            protocol_no_card=False,
        )

    params.billing_name = "User Example"
    params.billing_country = "US"
    params.billing_state = "CA"
    params.billing_city = "San Francisco"
    params.billing_zip = "94105"
    params.billing_address1 = "1 Market St"

    with pytest.raises(ValueError, match="自动注册模式需要 paypal_card_number"):
        paypal_preflight.validate_paypal_task_request(
            params=params,
            email="user@example.com",
            checkout_url="https://checkout.example",
            bind_link_payload={},
            paypal_mode="create_account",
            otp_channel="sms",
            sms_url="https://sms.example",
            protocol_no_card=False,
        )

    paypal_preflight.validate_paypal_task_request(
        params=params,
        email="user@example.com",
        checkout_url="https://checkout.example",
        bind_link_payload={},
        paypal_mode="create_account",
        otp_channel="sms",
        sms_url="https://sms.example",
        protocol_no_card=True,
    )
