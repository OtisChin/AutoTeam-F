from autotoken import api
from autotoken.api_routes.payment_task_models import (
    GoPayBindTaskParams,
    GoPayPhoneAccountParams,
    PayPalTaskParams,
)


def test_api_exports_payment_task_models_from_route_module():
    assert api.GoPayPhoneAccountParams is GoPayPhoneAccountParams
    assert api.GoPayBindTaskParams is GoPayBindTaskParams
    assert api.PayPalTaskParams is PayPalTaskParams


def test_gopay_bind_task_params_preserve_aliases_and_nested_phone_accounts():
    params = GoPayBindTaskParams.model_validate(
        {
            "account_emails": ["first@example.com", "second@example.com"],
            "autoRegister": True,
            "gopayAutoSignupHeroSmsPriceTier": "cheap",
            "gopayBalanceWaitFallbackTransfer": True,
            "phoneAccounts": [
                {
                    "countryCode": "+1",
                    "phoneNumber": "5550001",
                    "smsUrl": "https://sms.example/1",
                    "gopayPin": "123456",
                    "otpChannel": "whatsapp",
                }
            ],
        }
    )

    assert params.account_emails == ["first@example.com", "second@example.com"]
    assert params.auto_register is True
    assert params.gopay_auto_signup_hero_sms_preferred_price == "cheap"
    assert params.gopay_balance_wait_fallback_transfer is True
    assert params.phone_accounts == [
        GoPayPhoneAccountParams(
            country_code="+1",
            phone_number="5550001",
            sms_url="https://sms.example/1",
            gopay_pin="123456",
            otp_channel="whatsapp",
        )
    ]


def test_paypal_task_params_preserve_aliases_and_defaults():
    params = PayPalTaskParams.model_validate(
        {
            "accountEmails": ["user@example.com"],
            "checkoutUrl": "https://chatgpt.com/checkout/demo",
            "bindLinkPayload": {"plan": "plus"},
            "roxybrowserDirId": "profile-1",
            "manualConfirm": False,
            "paypalMode": "create_account",
            "phoneAccounts": [{"phoneNumber": "5550002", "smsUrl": "https://sms.example/2"}],
            "autoOauthAfterSuccess": True,
            "pendingRetryAttempts": 3,
            "paypalConcurrency": 2,
        }
    )

    assert params.account_emails == ["user@example.com"]
    assert params.checkout_url == "https://chatgpt.com/checkout/demo"
    assert params.bind_link_payload == {"plan": "plus"}
    assert params.roxybrowser_profile_id == "profile-1"
    assert params.manual_confirm is False
    assert params.paypal_mode == "create_account"
    assert params.phone_accounts[0].phone_number == "5550002"
    assert params.auto_oauth_after_success is True
    assert params.pending_retry_attempts == 3
    assert params.paypal_concurrency == 2
    assert params.paypal_browser == "chromium"
    assert params.billing_country == "US"
