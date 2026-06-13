import pytest

from autotoken.services import paypal_ice_phone_pool


def test_empty_phone_pool_import_has_readable_error():
    with pytest.raises(ValueError, match="未能解析到有效的手机号"):
        paypal_ice_phone_pool.import_phones("")


def test_phone_pool_import_accepts_spaced_single_hyphen(monkeypatch):
    stored = []
    monkeypatch.setattr(paypal_ice_phone_pool, "_raw_items", lambda: [dict(item) for item in stored])
    monkeypatch.setattr(
        paypal_ice_phone_pool,
        "_save_items",
        lambda items: stored.__setitem__(slice(None), [dict(item) for item in items]) or items,
    )

    result = paypal_ice_phone_pool.import_phones(
        "08085022584 - https://api.yamasakisms.com/api/private/getphonecode?order_no=456073049305776129\n"
        "08085019173 - https://api.yamasakisms.com/api/private/getphonecode?order_no=456073049305776128"
    )

    assert result["added"] == 2
    assert {item["phone_number"] for item in result["items"]} == {"08085022584", "08085019173"}


def test_phone_pool_update_can_clear_optional_fields(monkeypatch):
    stored = [
        {
            "id": "phone-1",
            "phone_number": "08080051197",
            "sms_api": "https://sms.example.test/code",
            "status": "available",
            "note": "old note",
            "error_message": "old error",
        }
    ]

    monkeypatch.setattr(paypal_ice_phone_pool, "_raw_items", lambda: [dict(item) for item in stored])
    monkeypatch.setattr(
        paypal_ice_phone_pool,
        "_save_items",
        lambda items: stored.__setitem__(slice(None), [dict(item) for item in items]) or items,
    )

    result = paypal_ice_phone_pool.update_phone(
        "phone-1",
        {
            "phone_number": "08080051197",
            "sms_api": "https://sms.example.test/code",
            "status": "available",
            "note": "",
            "error_message": "",
        },
    )

    assert result["note"] == ""
    assert result["error_message"] == ""


def test_phone_is_exclusive_until_current_job_releases_it(monkeypatch):
    stored = [
        {
            "id": "phone-1",
            "phone_number": "08080051197",
            "sms_api": "https://sms.example.test/code",
            "status": "available",
        }
    ]
    monkeypatch.setattr(paypal_ice_phone_pool, "_raw_items", lambda: [dict(item) for item in stored])
    monkeypatch.setattr(
        paypal_ice_phone_pool,
        "_save_items",
        lambda items: stored.__setitem__(slice(None), [dict(item) for item in items]) or items,
    )
    paypal_ice_phone_pool._IN_USE.clear()
    paypal_ice_phone_pool._PHONE_TO_JOB.clear()
    paypal_ice_phone_pool._JOB_TO_PHONE.clear()

    first = paypal_ice_phone_pool.acquire_phone()
    paypal_ice_phone_pool.associate_job(first["id"], "job-1")
    second = paypal_ice_phone_pool.acquire_phone()
    paypal_ice_phone_pool.release_phone(first["id"])
    third = paypal_ice_phone_pool.acquire_phone()

    assert second is None
    assert paypal_ice_phone_pool.phone_for_job("job-1") is None
    assert third["id"] == "phone-1"
