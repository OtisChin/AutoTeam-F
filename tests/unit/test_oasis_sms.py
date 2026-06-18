import json

import pytest

from autotoken.auth import oasis_sms


class FakeResponse:
    def __init__(self, payload, *, status_code=200, headers=None):
        self.payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = json.dumps(payload)

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


@pytest.fixture(autouse=True)
def reset_oasis_runtime(monkeypatch):
    monkeypatch.setenv("OAUTH_OASIS_SMS_REQUEST_INTERVAL_MS", "0")
    monkeypatch.setenv("OAUTH_OASIS_SMS_429_BACKOFF_MS", "1")
    monkeypatch.setenv("OAUTH_OASIS_SMS_429_RETRIES", "4")
    oasis_sms._OASIS_NEXT_REQUEST_AT = 0.0


def test_acquire_oasis_phone_reuses_failed_mapped_cdks(monkeypatch, tmp_path):
    map_file = tmp_path / "oasis-map.jsonl"
    map_file.write_text(
        json.dumps(
            {
                "provider": "oasis",
                "status": "failed",
                "cdk": "SMS-6L2A-6TAH-Q7BA",
                "email": "used@example.com",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OAUTH_OASIS_SMS_ACCOUNT_MAP_FILE", str(map_file))
    monkeypatch.delenv("OAUTH_OASIS_SMS_CDKS", raising=False)
    monkeypatch.delenv("OAUTH_OASIS_SMS_CDK_FILE", raising=False)
    oasis_sms._USED_CDKS.clear()
    oasis_sms._RESERVED_CDKS.clear()
    calls = []

    def fake_post(url, json=None, timeout=30):
        calls.append({"url": url, "json": json})
        assert url.endswith("/api.php?action=check_cdk")
        assert json["code"] == "SMS-6L2A-6TAH-Q7BA"
        return FakeResponse({"ok": True, "phone": "+15551234567"})

    monkeypatch.setattr(oasis_sms.requests, "post", fake_post)

    item, error = oasis_sms.acquire_oasis_phone(
        email="next@example.com",
        cdks="SMS-6L2A-6TAH-Q7BA\nSMS-8EQ6-8E5G-KN2C",
    )

    assert error == ""
    assert item["cdk"] == "SMS-6L2A-6TAH-Q7BA"
    assert item["phone_number"] == "+15551234567"
    assert len(calls) == 1


def test_acquire_oasis_phone_skips_successfully_mapped_cdks(monkeypatch, tmp_path):
    map_file = tmp_path / "oasis-map.jsonl"
    map_file.write_text(
        json.dumps(
            {
                "provider": "oasis",
                "status": "success",
                "reason": "",
                "cdk": "SMS-6L2A-6TAH-Q7BA",
                "email": "used@example.com",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OAUTH_OASIS_SMS_ACCOUNT_MAP_FILE", str(map_file))
    monkeypatch.delenv("OAUTH_OASIS_SMS_CDKS", raising=False)
    monkeypatch.delenv("OAUTH_OASIS_SMS_CDK_FILE", raising=False)
    oasis_sms._USED_CDKS.clear()
    oasis_sms._RESERVED_CDKS.clear()
    calls = []

    def fake_post(url, json=None, timeout=30):
        calls.append({"url": url, "json": json})
        assert url.endswith("/api.php?action=check_cdk")
        assert json["code"] == "SMS-8EQ6-8E5G-KN2C"
        return FakeResponse({"ok": True, "phone": "+15551234567"})

    monkeypatch.setattr(oasis_sms.requests, "post", fake_post)

    item, error = oasis_sms.acquire_oasis_phone(
        email="next@example.com",
        cdks="SMS-6L2A-6TAH-Q7BA\nSMS-8EQ6-8E5G-KN2C",
    )

    assert error == ""
    assert item["cdk"] == "SMS-8EQ6-8E5G-KN2C"
    assert item["phone_number"] == "+15551234567"
    assert len(calls) == 1


def test_oasis_reservation_released_after_non_consuming_failure(monkeypatch, tmp_path):
    map_file = tmp_path / "oasis-map.jsonl"
    monkeypatch.setenv("OAUTH_OASIS_SMS_ACCOUNT_MAP_FILE", str(map_file))
    oasis_sms._USED_CDKS.clear()
    oasis_sms._RESERVED_CDKS.clear()
    monkeypatch.setattr(
        oasis_sms.requests,
        "post",
        lambda url, json=None, timeout=30: FakeResponse({"ok": True, "phone": "+15551234567"}),
    )

    item, error = oasis_sms.acquire_oasis_phone(
        email="first@example.com",
        cdks="SMS-6L2A-6TAH-Q7BA",
    )
    assert error == ""
    assert item["cdk"] == "SMS-6L2A-6TAH-Q7BA"
    assert "SMS-6L2A-6TAH-Q7BA" in oasis_sms._RESERVED_CDKS

    oasis_sms.record_oasis_account_mapping(
        item,
        email="first@example.com",
        status="failed",
        reason="phone_first_register_exception: OpenAI 拒绝创建账号",
    )

    assert "SMS-6L2A-6TAH-Q7BA" not in oasis_sms._RESERVED_CDKS
    assert "SMS-6L2A-6TAH-Q7BA" not in oasis_sms._USED_CDKS


def test_oasis_reservation_becomes_used_after_success(monkeypatch, tmp_path):
    map_file = tmp_path / "oasis-map.jsonl"
    monkeypatch.setenv("OAUTH_OASIS_SMS_ACCOUNT_MAP_FILE", str(map_file))
    oasis_sms._USED_CDKS.clear()
    oasis_sms._RESERVED_CDKS.clear()
    monkeypatch.setattr(
        oasis_sms.requests,
        "post",
        lambda url, json=None, timeout=30: FakeResponse({"ok": True, "phone": "+15551234567"}),
    )

    item, error = oasis_sms.acquire_oasis_phone(
        email="first@example.com",
        cdks="SMS-6L2A-6TAH-Q7BA",
    )
    assert error == ""

    oasis_sms.record_oasis_account_mapping(
        item,
        email="first@example.com",
        status="success",
        reason="",
    )

    assert "SMS-6L2A-6TAH-Q7BA" not in oasis_sms._RESERVED_CDKS
    assert "SMS-6L2A-6TAH-Q7BA" in oasis_sms._USED_CDKS


def test_oasis_failed_registered_reason_does_not_consume_cdk(monkeypatch, tmp_path):
    map_file = tmp_path / "oasis-map.jsonl"
    monkeypatch.setenv("OAUTH_OASIS_SMS_ACCOUNT_MAP_FILE", str(map_file))
    oasis_sms._USED_CDKS.clear()
    oasis_sms._RESERVED_CDKS.clear()
    oasis_sms._RESERVED_CDKS.add("SMS-6L2A-6TAH-Q7BA")
    oasis_sms._USED_CDKS.add("SMS-6L2A-6TAH-Q7BA")

    oasis_sms.record_oasis_account_mapping(
        {"cdk": "SMS-6L2A-6TAH-Q7BA", "phone_number": "+15551234567"},
        email="first@example.com",
        status="failed",
        reason="PHONE_ALREADY_REGISTERED: 手机号已注册或进入登录页",
    )

    assert "SMS-6L2A-6TAH-Q7BA" not in oasis_sms._RESERVED_CDKS
    assert "SMS-6L2A-6TAH-Q7BA" not in oasis_sms._USED_CDKS


def test_acquire_oasis_phone_reports_reserved_pool_separately(monkeypatch, tmp_path):
    map_file = tmp_path / "oasis-map.jsonl"
    monkeypatch.setenv("OAUTH_OASIS_SMS_ACCOUNT_MAP_FILE", str(map_file))
    monkeypatch.delenv("OAUTH_OASIS_SMS_CDKS", raising=False)
    monkeypatch.delenv("OAUTH_OASIS_SMS_CDK_FILE", raising=False)
    oasis_sms._USED_CDKS.clear()
    oasis_sms._RESERVED_CDKS.clear()
    oasis_sms._RESERVED_CDKS.add("SMS-6L2A-6TAH-Q7BA")

    item, error = oasis_sms.acquire_oasis_phone(
        email="next@example.com",
        cdks="SMS-6L2A-6TAH-Q7BA",
    )

    assert item is None
    assert error == "Oasis CDK 池中的可用 CDK 正由其他 worker 使用"


def test_oasis_post_retries_429_then_returns_success(monkeypatch):
    calls = []
    sleeps = []

    def fake_post(url, json=None, timeout=30):
        calls.append({"url": url, "json": json})
        if len(calls) == 1:
            return FakeResponse({"error": "Too Many Requests"}, status_code=429, headers={"Retry-After": "0.5"})
        return FakeResponse({"ok": True, "phone": "+15551234567"})

    monkeypatch.setattr(oasis_sms.requests, "post", fake_post)
    monkeypatch.setattr(oasis_sms.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = oasis_sms._post_oasis(
        "check_cdk",
        {"code": "SMS-6L2A-6TAH-Q7BA"},
        base_url="https://sms.oapi.vip",
    )

    assert result["phone"] == "+15551234567"
    assert len(calls) == 2
    assert sleeps == [0.5]


def test_acquire_oasis_phone_stops_pool_scan_after_429(monkeypatch, tmp_path):
    map_file = tmp_path / "oasis-map.jsonl"
    monkeypatch.setenv("OAUTH_OASIS_SMS_ACCOUNT_MAP_FILE", str(map_file))
    monkeypatch.setenv("OAUTH_OASIS_SMS_429_RETRIES", "2")
    monkeypatch.delenv("OAUTH_OASIS_SMS_CDKS", raising=False)
    monkeypatch.delenv("OAUTH_OASIS_SMS_CDK_FILE", raising=False)
    oasis_sms._USED_CDKS.clear()
    oasis_sms._RESERVED_CDKS.clear()
    calls = []

    def fake_post(url, json=None, timeout=30):
        calls.append(json["code"])
        return FakeResponse({"error": "Too Many Requests"}, status_code=429)

    monkeypatch.setattr(oasis_sms.requests, "post", fake_post)
    monkeypatch.setattr(oasis_sms.time, "sleep", lambda _seconds: None)

    item, error = oasis_sms.acquire_oasis_phone(
        email="next@example.com",
        cdks="SMS-6L2A-6TAH-Q7BA\nSMS-8EQ6-8E5G-KN2C",
    )

    assert item is None
    assert "Oasis HTTP 429 Too Many Requests" in error
    assert calls == ["SMS-6L2A-6TAH-Q7BA", "SMS-6L2A-6TAH-Q7BA"]


def test_oasis_wait_code_does_not_parse_timestamp_as_code(monkeypatch):
    activation = oasis_sms.OasisActivation(
        cdk="SMS-6L2A-6TAH-Q7BA",
        phone="+12185525713",
        base_url="https://sms.oapi.vip",
    )

    def fake_post(_action, _payload, *, base_url):
        return {
            "ok": True,
            "sms": "暂无短信",
            "remaining": -1,
            "synced_at": "2026-06-15T09:54:13.885Z",
            "_http_status": 200,
        }

    monkeypatch.setattr(oasis_sms, "_post_oasis", fake_post)
    monkeypatch.setenv("OAUTH_OASIS_SMS_POLL_ATTEMPTS", "1")
    monkeypatch.setenv("OAUTH_OASIS_SMS_POLL_INTERVAL_MS", "500")

    with pytest.raises(TimeoutError):
        activation.wait_code(timeout_sec=1)


def test_oasis_wait_code_accepts_explicit_six_digit_code(monkeypatch):
    activation = oasis_sms.OasisActivation(
        cdk="SMS-6L2A-6TAH-Q7BA",
        phone="+12185525713",
        base_url="https://sms.oapi.vip",
    )
    monkeypatch.setattr(
        oasis_sms,
        "_post_oasis",
        lambda _action, _payload, *, base_url: {
            "ok": True,
            "sms": "yes|Your ChatGPT verification code is: 740768",
            "code": "740768",
        },
    )

    assert activation.wait_code(timeout_sec=1) == "740768"
