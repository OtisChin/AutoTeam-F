from autotoken import api
from autotoken.api_routes.payment_task_models import (
    GoPayBindTaskParams,
    GoPayPhoneAccountParams,
)

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
