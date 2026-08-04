import json

import pytest

from autotoken.auth import tujie_sms


class FakeResponse:
    def __init__(self, payload, *, status_code=200, headers=None):
        self.payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = json.dumps(payload)

    def json(self):
        return self.payload


@pytest.fixture(autouse=True)
def reset_tujie_runtime(monkeypatch):
    monkeypatch.setenv("OAUTH_TUJIE_SMS_REQUEST_INTERVAL_MS", "0")
    monkeypatch.delenv("OAUTH_TUJIE_SMS_MODE", raising=False)
    tujie_sms._TUJIE_NEXT_REQUEST_AT = 0.0
    tujie_sms._USED_CDKS.clear()
    tujie_sms._RESERVED_CDKS.clear()


def test_normalize_tujie_cdks_accepts_long_sms_tokens():
    assert tujie_sms.normalize_tujie_cdks(
        "SMS-AE4H6TLEZV5H69SJGQ\nSMS-3VBXJBRT5UWHB2RW7E SMS-HR5RZ9ENE5C69Q9F83"
    ) == [
        "SMS-AE4H6TLEZV5H69SJGQ",
        "SMS-3VBXJBRT5UWHB2RW7E",
        "SMS-HR5RZ9ENE5C69Q9F83",
    ]


def test_acquire_tujie_phone_reads_number_from_page(monkeypatch, tmp_path):
    map_file = tmp_path / "tujie-map.jsonl"
    monkeypatch.setenv("OAUTH_TUJIE_SMS_ACCOUNT_MAP_FILE", str(map_file))
    monkeypatch.setenv("OAUTH_TUJIE_SMS_MODE", "page")
    calls = []

    def fake_open(cdk, *, base_url):
        calls.append({"cdk": cdk, "base_url": base_url})
        return {"ok": True, "phone": "+573151040254", "sms": "手机号：+573151040254"}, {"page": object()}

    monkeypatch.setattr(tujie_sms, "_open_tujie_page_runtime", fake_open)

    item, error = tujie_sms.acquire_tujie_phone(
        email="user@example.com",
        base_url="https://tujie.example",
        cdks="SMS-AE4H6TLEZV5H69SJGQ",
    )

    assert error == ""
    assert item["source"] == "tujie"
    assert item["provider"] == "tujie"
    assert item["cdk"] == "SMS-AE4H6TLEZV5H69SJGQ"
    assert item["phone_number"] == "+573151040254"
    assert item["activation"].mode == "page"
    assert len(calls) == 1


def test_tujie_activation_waits_for_sms_code_from_page(monkeypatch):
    calls = []

    def fake_fetch(cdk, *, base_url, runtime=None):
        calls.append((cdk, base_url, runtime))
        return {"ok": True, "sms": "Your OpenAI code is 123456"}

    monkeypatch.setattr(tujie_sms, "_fetch_tujie_page_state", fake_fetch)

    activation = tujie_sms.TuJieActivation(
        cdk="SMS-AE4H6TLEZV5H69SJGQ",
        phone="+573151040254",
        base_url="https://tujie.example",
        mode="page",
    )

    assert activation.wait_code(timeout_sec=5) == "123456"
    assert calls == [
        ("SMS-AE4H6TLEZV5H69SJGQ", "https://tujie.example", {}),
    ]


def test_tujie_api_mode_keeps_legacy_check_endpoint(monkeypatch, tmp_path):
    map_file = tmp_path / "tujie-map.jsonl"
    monkeypatch.setenv("OAUTH_TUJIE_SMS_ACCOUNT_MAP_FILE", str(map_file))
    monkeypatch.setenv("OAUTH_TUJIE_SMS_MODE", "legacy_api")
    calls = []

    def fake_post(url, json=None, headers=None, timeout=30):
        del headers
        calls.append({"url": url, "json": json, "timeout": timeout})
        assert url == "https://tujie.example/api.php?action=check_cdk"
        assert json == {"code": "SMS-AE4H6TLEZV5H69SJGQ"}
        return FakeResponse({"ok": True, "phone": "+573151040254"})

    monkeypatch.setattr(tujie_sms.requests, "post", fake_post)

    item, error = tujie_sms.acquire_tujie_phone(
        email="user@example.com",
        base_url="https://tujie.example",
        cdks="SMS-AE4H6TLEZV5H69SJGQ",
    )

    assert error == ""
    assert item["activation"].mode == "legacy_api"
    assert len(calls) == 1


def test_tujie_api_mode_checks_then_assigns_phone(monkeypatch, tmp_path):
    map_file = tmp_path / "tujie-map.jsonl"
    monkeypatch.setenv("OAUTH_TUJIE_SMS_ACCOUNT_MAP_FILE", str(map_file))
    calls = []

    def fake_post(url, json=None, headers=None, timeout=30):
        calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        if url.endswith("/user/cdk/check"):
            return FakeResponse({"code": 0, "message": "Success", "data": {"status": "AVAILABLE", "available": True}})
        if url.endswith("/user/cdk/assign"):
            return FakeResponse(
                {
                    "code": 0,
                    "message": "Success",
                    "data": {
                        "status": "ASSIGNED",
                        "session_id": "session-1",
                        "resource_value": "19383133663",
                        "phone_number": "19383133663",
                    },
                }
            )
        raise AssertionError(url)

    monkeypatch.setattr(tujie_sms.requests, "post", fake_post)

    item, error = tujie_sms.acquire_tujie_phone(
        email="user@example.com",
        base_url="https://tujie.xyz/api",
        cdks="SMS-AE4H6TLEZV5H69SJGQ",
    )

    assert error == ""
    assert item["phone_number"] == "19383133663"
    assert item["session_id"] == "session-1"
    assert item["activation"].mode == "api"
    assert [call["url"] for call in calls] == [
        "https://tujie.xyz/api/user/cdk/check",
        "https://tujie.xyz/api/user/cdk/assign",
    ]


def test_record_tujie_account_mapping_marks_success_used(monkeypatch, tmp_path):
    map_file = tmp_path / "tujie-map.jsonl"
    monkeypatch.setenv("OAUTH_TUJIE_SMS_ACCOUNT_MAP_FILE", str(map_file))
    tujie_sms._RESERVED_CDKS.add("SMS-AE4H6TLEZV5H69SJGQ")

    tujie_sms.record_tujie_account_mapping(
        {"cdk": "SMS-AE4H6TLEZV5H69SJGQ", "phone_number": "+573151040254"},
        email="user@example.com",
        status="success",
    )

    assert "SMS-AE4H6TLEZV5H69SJGQ" in tujie_sms._USED_CDKS
    assert "SMS-AE4H6TLEZV5H69SJGQ" not in tujie_sms._RESERVED_CDKS
    saved = json.loads(map_file.read_text(encoding="utf-8").strip())
    assert saved["provider"] == "tujie"
    assert saved["email"] == "user@example.com"
