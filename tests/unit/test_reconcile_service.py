from autotoken.accounts import (
    STATUS_ACTIVE,
    STATUS_AUTH_INVALID,
    STATUS_EXHAUSTED,
    STATUS_ORPHAN,
    STATUS_PERSONAL,
    STATUS_STANDBY,
)
from autotoken.services import reconcile


def test_quota_exhausted_snapshot_requires_primary_and_weekly_exhausted():
    assert reconcile.quota_exhausted_snapshot({"last_quota": {"primary_pct": 100, "weekly_pct": 100}})
    assert not reconcile.quota_exhausted_snapshot({"last_quota": {"primary_pct": 100, "weekly_pct": 99}})
    assert not reconcile.quota_exhausted_snapshot({"last_quota": {"primary_pct": "bad", "weekly_pct": 100}})
    assert not reconcile.quota_exhausted_snapshot({})


def test_over_cap_priority_respects_ghost_kick_flag():
    assert reconcile.over_cap_priority("ghost@example.com", {}, kick_ghost=True) == (0, 0)
    assert reconcile.over_cap_priority("ghost@example.com", {}, kick_ghost=False) == (99, 0)


def test_over_cap_victims_follow_status_priority_then_active_remaining_quota():
    account_map = {
        "active-high@example.com": {
            "status": STATUS_ACTIVE,
            "last_quota": {"primary_pct": 90},
        },
        "active-low@example.com": {
            "status": STATUS_ACTIVE,
            "last_quota": {"primary_pct": 10},
        },
        "standby@example.com": {"status": STATUS_STANDBY},
        "personal@example.com": {"status": STATUS_PERSONAL},
        "exhausted@example.com": {"status": STATUS_EXHAUSTED},
        "auth-invalid@example.com": {"status": STATUS_AUTH_INVALID},
        "orphan@example.com": {"status": STATUS_ORPHAN},
    }
    remaining = [
        "active-low@example.com",
        "active-high@example.com",
        "standby@example.com",
        "personal@example.com",
        "exhausted@example.com",
        "auth-invalid@example.com",
        "orphan@example.com",
    ]

    assert reconcile.over_cap_victims(remaining, account_map, excess=7, kick_ghost=True) == [
        "orphan@example.com",
        "auth-invalid@example.com",
        "exhausted@example.com",
        "personal@example.com",
        "standby@example.com",
        "active-high@example.com",
        "active-low@example.com",
    ]


def test_over_cap_victims_keep_ghost_last_when_ghost_kick_is_disabled():
    account_map = {
        "active@example.com": {
            "status": STATUS_ACTIVE,
            "last_quota": {"primary_pct": 50},
        },
    }

    assert reconcile.over_cap_victims(
        ["ghost@example.com", "active@example.com"],
        account_map,
        excess=1,
        kick_ghost=False,
    ) == ["active@example.com"]
