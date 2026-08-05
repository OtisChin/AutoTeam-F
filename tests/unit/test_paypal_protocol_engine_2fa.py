from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2] / "src" / "autotoken" / "_paypal_protocol_engine"
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

import paypal.flow as flow_module  # noqa: E402
from paypal.flow import PayPalFlow  # noqa: E402


def test_initiate_2fa_rejects_sms_limit_exceeded(monkeypatch):
    flow = PayPalFlow.__new__(PayPalFlow)
    flow.session = object()
    flow.state = SimpleNamespace(ec_token="EC-TEST")
    flow.address = SimpleNamespace(country="GB")
    flow.user = SimpleNamespace(phone_local="7383350124")

    monkeypatch.setattr(flow, "_masked_phone", lambda: "********0124")
    monkeypatch.setattr(flow_module, "send_weasley_log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        flow,
        "_graphql_with_authchallenge_frontend_retry",
        lambda *_args, **_kwargs: {
            "data": {
                "initiateRiskBasedTwoFactorPhoneConfirmation": {
                    "authId": "AUTH-1",
                    "challengeId": "CHAL-1",
                    "state": "SMS_LIMIT_EXCEEDED",
                }
            }
        },
    )

    with pytest.raises(RuntimeError, match="SMS_LIMIT_EXCEEDED"):
        flow._initiate_2fa_phone_confirmation("TOKEN", "https://www.paypal.com/signup")
