from autotoken import session_cpa_converter
from autotoken.core.timestamps import epoch_seconds, normalized_utc_timestamp


def test_normalized_utc_timestamp_accepts_seconds_milliseconds_and_iso_values():
    assert normalized_utc_timestamp(0) == "1970-01-01T00:00:00Z"
    assert normalized_utc_timestamp(1000) == "1970-01-01T00:16:40Z"
    assert normalized_utc_timestamp(1_786_026_576_000) == "2026-08-06T14:29:36Z"
    assert normalized_utc_timestamp("2026-08-06T22:29:36+08:00") == "2026-08-06T14:29:36Z"
    assert normalized_utc_timestamp("bad") == ""


def test_epoch_seconds_uses_normalized_utc_timestamp():
    assert epoch_seconds("1970-01-01T00:00:01Z") == 1
    assert epoch_seconds("") == 0


def test_existing_session_converter_timestamp_helpers_delegate_to_core_helpers():
    assert session_cpa_converter._normalize_timestamp("2026-08-06T22:29:36+08:00") == normalized_utc_timestamp(
        "2026-08-06T22:29:36+08:00"
    )
    assert session_cpa_converter._epoch_seconds("1970-01-01T00:00:01Z") == epoch_seconds(
        "1970-01-01T00:00:01Z"
    )
