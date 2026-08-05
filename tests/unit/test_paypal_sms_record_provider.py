from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[2] / "src" / "autotoken" / "_paypal_protocol_engine"
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

import main as paypal_engine_main  # noqa: E402


class _FakeHttpResponse:
    def __init__(self, body: str):
        self.body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.body


def _record_body(code: str, code_time: float) -> str:
    return json.dumps(
        {
            "code": 1,
            "msg": "ok",
            "data": {
                "code": f"PayPal: {code} is your security code. Don't share it.",
                "code_time": dt.datetime.fromtimestamp(code_time).strftime("%Y-%m-%d %H:%M:%S"),
            },
        }
    )


def test_sms_record_provider_returns_fresh_paypal_code(monkeypatch):
    provider = paypal_engine_main.SmsRecordOtpProvider(
        "+447383350124",
        "https://sms.example/api/record?token=secret",
        wait_seconds=0.05,
        poll_interval=0.001,
    )
    activation = provider.reserve_number()
    provider.mark_sms_sent(activation)
    body = _record_body("123456", provider._sent_at + 5)

    monkeypatch.setattr(
        paypal_engine_main.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _FakeHttpResponse(body),
    )

    assert provider.wait_for_code(activation, timeout_seconds=0.05) == "123456"


def test_sms_record_provider_submits_latest_code_when_timestamp_is_skewed(monkeypatch):
    provider = paypal_engine_main.SmsRecordOtpProvider(
        "+447383350124",
        "https://sms.example/api/record?token=secret",
        wait_seconds=0.01,
        poll_interval=0.001,
    )
    activation = provider.reserve_number()
    provider.mark_sms_sent(activation)
    body = _record_body("654321", provider._sent_at - 10)

    monkeypatch.setattr(
        paypal_engine_main.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _FakeHttpResponse(body),
    )

    assert provider.wait_for_code(activation, timeout_seconds=0.01) == "654321"
