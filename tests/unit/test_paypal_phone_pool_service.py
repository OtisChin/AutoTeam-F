from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from autotoken.payments import gopay_auto_register
from autotoken.services import paypal_phone_pool


@dataclass
class PhoneAccount:
    phone_number: str
    sms_url: str
    otp_channel: str = ""


def test_normalize_paypal_phone_accounts_deduplicates_and_uses_first_defaults():
    result = paypal_phone_pool.normalize_paypal_phone_accounts(
        [
            {"phoneNumber": "+1 (555) 000-0001", "smsUrl": "https://sms.example/1", "otpChannel": "whatsapp"},
            {"phone_number": "+1 (555) 000-0001", "sms_url": "https://sms.example/1", "otp_channel": "whatsapp"},
            PhoneAccount(phone_number="+1 555 000 0002", sms_url="https://sms.example/2"),
            {},
        ],
        otp_channel="sms",
    )

    assert result == {
        "phone_accounts": [
            {
                "phone_number": "+1 (555) 000-0001",
                "sms_url": "https://sms.example/1",
                "otp_channel": "whatsapp",
            },
            {
                "phone_number": "+1 555 000 0002",
                "sms_url": "https://sms.example/2",
                "otp_channel": "sms",
            },
        ],
        "sms_url": "https://sms.example/1",
        "otp_channel": "whatsapp",
        "billing_phone": "+1 (555) 000-0001",
    }


def test_normalize_paypal_phone_accounts_rejects_partial_or_invalid_entries():
    with pytest.raises(ValueError, match="phone_accounts 每项都必须填写 phone_number、sms_url"):
        paypal_phone_pool.normalize_paypal_phone_accounts([{"phoneNumber": "+15550000001"}])

    with pytest.raises(ValueError, match="phone_accounts otp_channel 只支持 sms 或 whatsapp"):
        paypal_phone_pool.normalize_paypal_phone_accounts(
            [{"phoneNumber": "+15550000001", "smsUrl": "https://sms.example/1", "otpChannel": "email"}]
        )


def test_paypal_sms_auto_provision_enabled_requires_protocol_create_account(monkeypatch):
    monkeypatch.setenv("PAYPAL_SMS_PROVIDER", "hero_sms")

    assert paypal_phone_pool.paypal_sms_auto_provision_enabled(
        paypal_mode="create_account",
        protocol_no_card=True,
        sms_url="",
        phone_accounts=[],
    ) is True
    assert paypal_phone_pool.paypal_sms_auto_provision_enabled(
        paypal_mode="existing_account",
        protocol_no_card=True,
        sms_url="",
        phone_accounts=[],
    ) is False
    assert paypal_phone_pool.paypal_sms_auto_provision_enabled(
        paypal_mode="create_account",
        protocol_no_card=False,
        sms_url="",
        phone_accounts=[],
    ) is False
    assert paypal_phone_pool.paypal_sms_auto_provision_enabled(
        paypal_mode="create_account",
        protocol_no_card=True,
        sms_url="https://sms.example",
        phone_accounts=[],
    ) is False


def test_explicit_paypal_phone_account_from_env(monkeypatch):
    monkeypatch.delenv("PAYPAL_SMS_URL", raising=False)
    monkeypatch.delenv("PAYPAL_PHONE_NUMBER", raising=False)
    monkeypatch.delenv("PAYPAL_SMS_PHONE_NUMBER", raising=False)
    monkeypatch.delenv("PAYPAL_BILLING_PHONE", raising=False)

    assert paypal_phone_pool.explicit_paypal_phone_account_from_env() is None

    monkeypatch.setenv("PAYPAL_SMS_URL", "https://sms.example/token")
    with pytest.raises(ValueError, match="PAYPAL_SMS_URL 与 PAYPAL_PHONE_NUMBER"):
        paypal_phone_pool.explicit_paypal_phone_account_from_env()

    monkeypatch.setenv("PAYPAL_PHONE_NUMBER", "+819012345678")
    monkeypatch.setenv("PAYPAL_OTP_CHANNEL", "sms")

    assert paypal_phone_pool.explicit_paypal_phone_account_from_env() == {
        "phone_number": "+819012345678",
        "sms_url": "https://sms.example/token",
        "otp_channel": "sms",
        "sms_provider": "explicit_env",
    }


def test_provision_paypal_phone_account_from_env_uses_hero_sms_bridge(monkeypatch):
    calls = {}

    monkeypatch.setenv("PAYPAL_SMS_PROVIDER", "hero")
    monkeypatch.setenv("PAYPAL_SMS_API_KEY", "secret")
    monkeypatch.setenv("PAYPAL_SMS_COUNTRY", "4")
    monkeypatch.setenv("PAYPAL_SMS_SERVICE", "paypal")
    monkeypatch.setenv("PAYPAL_SMS_PHONE_COUNTRY_CODE", "81")

    def fake_get_number(**kwargs):
        calls["get_number"] = kwargs
        return "activation-1", "9012345678", ""

    def fake_create_bridge(activation):
        calls["activation"] = activation
        return SimpleNamespace(token="bridge-token")

    monkeypatch.setattr(gopay_auto_register, "_hero_get_number", fake_get_number)
    monkeypatch.setattr(gopay_auto_register, "create_sms_bridge", fake_create_bridge)

    result = paypal_phone_pool.provision_paypal_phone_account_from_env(
        public_base_url="http://127.0.0.1:9999/"
    )

    assert result["phone_number"] == "+819012345678"
    assert result["sms_url"] == "http://127.0.0.1:9999/otp/gopay-signup/bridge-token"
    assert result["otp_channel"] == "sms"
    assert result["sms_provider"] == "hero_sms"
    assert result["activation_id"] == "activation-1"
    assert calls["get_number"]["service_code"] == "paypal"
    assert calls["get_number"]["country_id"] == "4"
    assert calls["activation"].activation_id == "activation-1"


def test_close_paypal_sms_bridges_deduplicates_bridge_tokens(monkeypatch):
    closed = []

    monkeypatch.setattr(
        gopay_auto_register,
        "close_sms_bridge",
        lambda token, *, success=True: closed.append((token, success)),
    )

    paypal_phone_pool.close_paypal_sms_bridges(
        [
            {"bridge_token": "bridge-1"},
            {"bridge_token": "bridge-1"},
            {"sms_bridge_token": "bridge-2"},
            {"phone_number": "+819012345678"},
        ],
        success=False,
    )

    assert closed == [("bridge-1", False), ("bridge-2", False)]


def test_paypal_sms_bridge_success_for_post_submit_result():
    assert paypal_phone_pool.paypal_sms_bridge_success_for_result({"status": "success"}) is True
    assert paypal_phone_pool.paypal_sms_bridge_success_for_result({"paypal_user_id": "user"}) is True
    assert paypal_phone_pool.paypal_sms_bridge_success_for_result({"return_url": "https://chatgpt.com/checkout/verify"}) is True
    assert paypal_phone_pool.paypal_sms_bridge_success_for_result({"failure_stage": "post_submit"}) is True
    assert paypal_phone_pool.paypal_sms_bridge_success_for_result({"failure_stage": "paypal_phone_rejected"}) is False


def test_paypal_phone_account_key_and_availability():
    assert paypal_phone_pool.normalize_paypal_phone_key("+1 (835) 288-0840") == "8352880840"
    assert paypal_phone_pool.paypal_phone_account_key({"billingPhone": "+1 835 288 0840"}) == "8352880840"
    assert paypal_phone_pool.paypal_phone_account_available({"phone_number": "+1 835 288 0840"}, set()) is True
    assert (
        paypal_phone_pool.paypal_phone_account_available({"phone_number": "+1 835 288 0840"}, {"8352880840"}) is False
    )
    assert (
        paypal_phone_pool.paypal_phone_account_available(
            {"phone_number": "+1 835 288 0840", "status": "disabled"}, set()
        )
        is False
    )


def test_remember_invalid_paypal_phone_deduplicates_normalized_keys():
    invalid_keys = set()
    invalid_pool = []

    assert paypal_phone_pool.remember_invalid_paypal_phone("+1 (835) 288-0840", invalid_keys, invalid_pool) is True
    assert paypal_phone_pool.remember_invalid_paypal_phone("8352880840", invalid_keys, invalid_pool) is False

    assert invalid_keys == {"8352880840"}
    assert invalid_pool == ["+1 (835) 288-0840"]


def test_lease_paypal_phone_accounts_reserves_first_available_and_returns_details():
    phones = [
        {"phone_number": "+1 835 288 0840", "sms_url": "https://sms.example/1", "otp_channel": "whatsapp"},
        {"phone_number": "+1 835 288 0841", "sms_url": "https://sms.example/2", "otp_channel": "sms"},
    ]
    reserved_keys = set()

    leased, sms_url, otp_channel, billing_phone = paypal_phone_pool.lease_paypal_phone_accounts(
        phones,
        sms_url="https://default.example",
        otp_channel="sms",
        invalid_keys=set(),
        reserved_keys=reserved_keys,
        effective_concurrency=3,
    )

    assert leased == [phones[0]]
    assert sms_url == "https://sms.example/1"
    assert otp_channel == "whatsapp"
    assert billing_phone == "+1 835 288 0840"
    assert reserved_keys == {"8352880840"}


def test_lease_paypal_phone_accounts_falls_back_to_defaults_without_pool():
    leased, sms_url, otp_channel, billing_phone = paypal_phone_pool.lease_paypal_phone_accounts(
        [],
        sms_url="https://default.example",
        otp_channel="sms",
        invalid_keys=set(),
        reserved_keys=set(),
        effective_concurrency=1,
    )

    assert leased == []
    assert sms_url == "https://default.example"
    assert otp_channel == "sms"
    assert billing_phone == ""


def test_lease_paypal_phone_accounts_for_item_single_concurrency_falls_back_to_unassigned_phone():
    phones = [
        {"phone_number": "+1 835 288 0840", "sms_url": "https://sms.example/1", "otp_channel": "sms"},
        {"phone_number": "+1 835 288 0841", "sms_url": "https://sms.example/2", "otp_channel": "sms"},
    ]
    invalid_keys = {"8352880840"}
    reserved_keys = set()

    leased, sms_url, _otp_channel, billing_phone = paypal_phone_pool.lease_paypal_phone_accounts_for_item(
        {"phone_accounts": [phones[0]]},
        phone_accounts=phones,
        sms_url="https://default.example",
        otp_channel="sms",
        invalid_keys=invalid_keys,
        reserved_keys=reserved_keys,
        effective_concurrency=1,
    )

    assert leased == [phones[1]]
    assert sms_url == "https://sms.example/2"
    assert billing_phone == "+1 835 288 0841"
    assert reserved_keys == {"8352880841"}


def test_assign_release_and_retry_round_concurrency_use_available_phones():
    phones = [
        {"phone_number": "+1 835 288 0840", "sms_url": "https://sms.example/1", "otp_channel": "sms"},
        {"phone_number": "+1 835 288 0841", "sms_url": "https://sms.example/2", "otp_channel": "sms"},
    ]
    invalid_keys = {"8352880840"}

    assigned = paypal_phone_pool.assign_paypal_phone_accounts_to_items(
        [{"email": "one@example.com"}, {"email": "two@example.com"}],
        paypal_mode="create_account",
        phone_accounts=phones,
        invalid_keys=invalid_keys,
    )

    assert assigned[0]["phone_accounts"] == [phones[1]]
    assert "phone_accounts" not in assigned[1]
    assert (
        paypal_phone_pool.paypal_phone_retry_round_concurrency(
            base_concurrency=3,
            round_item_count=3,
            paypal_mode="create_account",
            phone_accounts=phones,
            invalid_keys=invalid_keys,
        )
        == 1
    )

    reserved_keys = {"8352880841"}
    paypal_phone_pool.release_paypal_phone_accounts([phones[1]], reserved_keys)
    assert reserved_keys == set()
