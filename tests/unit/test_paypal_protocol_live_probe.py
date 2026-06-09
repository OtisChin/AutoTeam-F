import argparse
import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "paypal_protocol_live_probe.py"
SPEC = importlib.util.spec_from_file_location("paypal_protocol_live_probe", SCRIPT_PATH)
assert SPEC and SPEC.loader
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


PAYPAL_SMS_ENV_KEYS = (
    "PAYPAL_SMS_URL",
    "PAYPAL_PHONE_NUMBER",
    "PAYPAL_SMS_PHONE_NUMBER",
    "PAYPAL_BILLING_PHONE",
    "PAYPAL_SMS_PROVIDER",
    "PAYPAL_SMS_API_KEY",
    "PAYPAL_HERO_SMS_API_KEY",
    "PAYPAL_SMSBOWER_API_KEY",
    "PAYPAL_SMSCODE_API_TOKEN",
    "PAYPAL_SMSCLOUD_XI_TOKEN",
)


def clear_paypal_sms_env(monkeypatch):
    for key in PAYPAL_SMS_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_live_probe_requires_explicit_live_confirmation():
    with pytest.raises(SystemExit, match="--yes-live"):
        probe._require_live_confirmation(argparse.Namespace(yes_live=False))


def test_live_probe_redacts_sensitive_payload_values():
    payload = {
        "message": (
            "Extracted BA token BA-123456789 from https://paypal.com/pay?token=BA-123456789 "
            "checkout cs_live_123456789 phone +819012345678"
        ),
        "ba_token": "BA-123456789",
        "checkout_url": "https://pay.openai.com/c/pay/cs_live_123456789?secret=1",
        "phone_number": "+819012345678",
        "nested": {"pm_id": "pm_live_123456789"},
    }

    redacted = probe.redact_payload(payload)
    text = str(redacted)

    assert redacted["ba_token"] is True
    assert redacted["checkout_url"] is True
    assert redacted["phone_number"] == "+819***5678"
    assert redacted["nested"]["pm_id"] == "<token:redacted>"
    assert "BA-123456789" not in text
    assert "cs_live_123456789" not in text
    assert "token=" not in text
    assert "+819012345678" not in text


def test_explicit_phone_account_requires_sms_url_and_phone_number():
    args = argparse.Namespace(sms_url="https://sms.example/token", phone_number="", otp_channel="sms")

    with pytest.raises(SystemExit, match="--sms-url and --phone-number"):
        probe.explicit_phone_account(args)

    result = probe.explicit_phone_account(
        argparse.Namespace(sms_url="https://sms.example/token", phone_number="+819012345678", otp_channel="sms")
    )

    assert result == {
        "phone_number": "+819012345678",
        "sms_url": "https://sms.example/token",
        "otp_channel": "sms",
    }


def test_explicit_phone_account_reads_env_fallback(monkeypatch):
    monkeypatch.setenv("PAYPAL_SMS_URL", "https://sms.example/env-token")
    monkeypatch.setenv("PAYPAL_PHONE_NUMBER", "+819087654321")

    result = probe.explicit_phone_account(argparse.Namespace(sms_url="", phone_number="", otp_channel="sms"))

    assert result == {
        "phone_number": "+819087654321",
        "sms_url": "https://sms.example/env-token",
        "otp_channel": "sms",
    }


def test_pre_extracted_ba_result_requires_checkout_reference():
    class FakeBillingAgreement:
        @staticmethod
        def paypal_protocol_extract_ba_token(url):
            return "BA-EXTRACTED" if "BA-EXTRACTED" in url else ""

    with pytest.raises(SystemExit, match="Direct BA/link mode requires"):
        probe.pre_extracted_ba_result(
            argparse.Namespace(
                approve_url="https://www.paypal.com/pay?token=BA-EXTRACTED",
                ba_token="",
                checkout_session_id="",
                checkout_url="",
                hosted_checkout_url="",
                payment_method_id="",
            ),
            FakeBillingAgreement,
        )

    result = probe.pre_extracted_ba_result(
        argparse.Namespace(
            approve_url="https://www.paypal.com/pay?token=BA-EXTRACTED",
            ba_token="",
            checkout_session_id="cs_test_123",
            checkout_url="",
            hosted_checkout_url="",
            payment_method_id="pm_test_123",
        ),
        FakeBillingAgreement,
    )

    assert result == {
        "status": "success",
        "ba_token": "BA-EXTRACTED",
        "approve_url": "https://www.paypal.com/pay?token=BA-EXTRACTED",
        "checkout_session_id": "cs_test_123",
        "checkout_url": "",
        "hosted_checkout_url": "",
        "pm_id": "pm_test_123",
    }


def test_check_prereqs_accepts_direct_ba_with_explicit_cli_sms(monkeypatch):
    clear_paypal_sms_env(monkeypatch)

    result = probe.check_prereqs(
        argparse.Namespace(
            email="user@example.com",
            approve_url="https://www.paypal.com/pay?token=BA-EXTRACTED",
            ba_token="",
            checkout_session_id="cs_test_123",
            checkout_url="",
            hosted_checkout_url="",
            payment_method_id="",
            sms_url="https://sms.example/token",
            phone_number="+819012345678",
            otp_channel="sms",
        ),
        access_token_loader=lambda _email: "",
        ba_token_extractor=lambda url: "BA-EXTRACTED" if "BA-EXTRACTED" in url else "",
    )

    assert result["ok"] is True
    assert result["mode"] == "direct_ba"
    assert result["checks"]["local_auth"] == "not_required"
    assert result["checks"]["live_actions"] is False
    assert result["sms_source"] == "explicit_cli"
    assert result["missing"] == []


def test_check_prereqs_reports_missing_sms_for_direct_ba(monkeypatch):
    clear_paypal_sms_env(monkeypatch)

    result = probe.check_prereqs(
        argparse.Namespace(
            email="user@example.com",
            approve_url="",
            ba_token="BA-EXTRACTED",
            checkout_session_id="cs_test_123",
            checkout_url="",
            hosted_checkout_url="",
            payment_method_id="",
            sms_url="",
            phone_number="",
            otp_channel="sms",
        ),
        ba_token_extractor=lambda _url: "",
    )

    assert result["ok"] is False
    assert result["mode"] == "direct_ba"
    assert result["sms_source"] == "missing"
    assert result["checks"]["sms"] is False
    assert any("PAYPAL_SMS_PROVIDER" in item for item in result["missing"])


def test_check_prereqs_extract_ba_requires_local_access_token_and_sms_provider(monkeypatch):
    clear_paypal_sms_env(monkeypatch)
    monkeypatch.setenv("PAYPAL_SMS_PROVIDER", "smsbower")
    monkeypatch.setenv("PAYPAL_SMS_API_KEY", "sms-key")

    result = probe.check_prereqs(
        argparse.Namespace(
            email="user@example.com",
            approve_url="",
            ba_token="",
            checkout_session_id="",
            checkout_url="",
            hosted_checkout_url="",
            payment_method_id="",
            sms_url="",
            phone_number="",
            otp_channel="sms",
        ),
        access_token_loader=lambda _email: "access-token",
    )

    assert result["ok"] is True
    assert result["mode"] == "extract_ba"
    assert result["checks"]["local_auth"] is True
    assert result["sms_source"] == "auto_provision"
    assert result["sms_provider"] == "smsbower"
