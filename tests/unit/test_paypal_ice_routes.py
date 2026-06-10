import anyio
import pytest
from fastapi import HTTPException

from autotoken.api_routes.paypal_ice import create_paypal_ice_router


class FakeRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


def _routes():
    return {route.endpoint.__name__: route.endpoint for route in create_paypal_ice_router(mask_secret=lambda value: f"masked:{value}").routes}


def test_paypal_ice_config_masks_api_key(monkeypatch):
    monkeypatch.setattr(
        "autotoken.settings.setup_wizard._read_env",
        lambda: {"PAYPAL_ICE_BASE_URL": "https://plus.example.test", "PAYPAL_ICE_API_KEY": "ice-key"},
    )

    result = _routes()["get_paypal_ice_config"]()

    assert result == {
        "base_url": "https://plus.example.test",
        "api_key_present": True,
        "api_key_masked": "masked:ice-key",
        "configured": True,
    }


def test_save_paypal_ice_config_writes_env(monkeypatch):
    written = {}
    monkeypatch.setattr("autotoken.settings.setup_wizard._read_env", lambda: {})
    monkeypatch.setattr("autotoken.settings.setup_wizard._write_env", lambda key, value: written.update({key: value}))

    result = anyio.run(
        _routes()["save_paypal_ice_config"],
        FakeRequest({"base_url": "https://plus.example.test/", "api_key": "ice-key"}),
    )

    assert written["PAYPAL_ICE_BASE_URL"] == "https://plus.example.test"
    assert written["PAYPAL_ICE_API_KEY"] == "ice-key"
    assert result["configured"] is True
    assert result["message"] == "PayPal ICE 配置已保存"


def test_paypal_ice_job_uses_bearer_and_idempotency(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "autotoken.settings.setup_wizard._read_env",
        lambda: {"PAYPAL_ICE_BASE_URL": "https://plus.example.test", "PAYPAL_ICE_API_KEY": "ice-key"},
    )

    def fake_request(method, url, **kwargs):
        captured.update({"method": method, "url": url, **kwargs})
        return FakeResponse({"job_id": "job-1", "status": "queued"})

    monkeypatch.setattr("autotoken.api_routes.paypal_ice.requests.request", fake_request)

    result = _routes()["post_paypal_ice_job"](
        type(
            "Params",
            (),
            {
                "input": "token-1",
                "client_ref": "user@example.com",
                "callback_url": "",
                "proxy": "",
                "proxy_jp": "",
                "phone": "08012345678",
                "sms_api": "https://sms.example.test",
                "email": "",
                "cookies": None,
                "pplink_retry": 3,
                "otp_timeout": 180,
                "idempotency_key": "idem-1",
            },
        )()
    )

    assert result["job_id"] == "job-1"
    assert captured["method"] == "POST"
    assert captured["url"] == "https://plus.example.test/api/v1/jobs"
    assert captured["headers"]["Authorization"] == "Bearer ice-key"
    assert captured["headers"]["Idempotency-Key"] == "idem-1"
    assert captured["json"]["input"] == "token-1"
    assert captured["json"]["phone"] == "08012345678"
    assert captured["json"]["sms_api"] == "https://sms.example.test"


def test_paypal_ice_job_requires_phone_sms_pair():
    with pytest.raises(HTTPException) as exc_info:
        _routes()["post_paypal_ice_job"](
            type(
                "Params",
                (),
                {
                    "input": "token-1",
                    "client_ref": "",
                    "callback_url": "",
                    "proxy": "",
                    "proxy_jp": "",
                    "phone": "08012345678",
                    "sms_api": "",
                    "email": "",
                    "cookies": None,
                    "pplink_retry": None,
                    "otp_timeout": None,
                    "idempotency_key": "",
                },
            )()
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "自定义接码必须同时提供 phone 和 sms_api"
