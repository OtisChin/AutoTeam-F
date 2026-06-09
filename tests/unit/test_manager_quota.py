import time

from autotoken import manager


class _GbkStdout:
    encoding = "gbk"


def test_pending_historical_exhausted_info_blocks_weekly_window_before_reset():
    now = int(time.time())
    quota_info = {
        "primary_pct": 0,
        "primary_resets_at": now - 300,
        "weekly_pct": 100,
        "weekly_resets_at": now + 3600,
    }

    exhausted_info = manager._pending_historical_exhausted_info(quota_info, now=now)

    assert exhausted_info is not None
    assert exhausted_info["window"] == "weekly"
    assert manager._quota_window_label(exhausted_info["window"]) == "周"


def test_pending_historical_exhausted_info_ignores_expired_weekly_snapshot():
    now = int(time.time())
    quota_info = {
        "primary_pct": 0,
        "primary_resets_at": now - 300,
        "weekly_pct": 100,
        "weekly_resets_at": now - 60,
    }

    assert manager._pending_historical_exhausted_info(quota_info, now=now) is None


def test_status_table_symbols_fall_back_for_gbk_stdout():
    symbols = manager._status_table_symbols(_GbkStdout())

    assert symbols == {
        "active": "*",
        "exhausted": "x",
        "standby": "o",
        "pending": "...",
    }
