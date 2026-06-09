"""Reconcile decision helpers for Team/account drift cleanup."""

from __future__ import annotations

from typing import Any

from autotoken.storage.accounts import (
    STATUS_ACTIVE,
    STATUS_AUTH_INVALID,
    STATUS_EXHAUSTED,
    STATUS_ORPHAN,
    STATUS_PERSONAL,
    STATUS_STANDBY,
)


def quota_exhausted_snapshot(account: dict[str, Any] | None) -> bool:
    quota = (account or {}).get("last_quota") or {}
    if not quota:
        return False
    try:
        return int(quota.get("primary_pct", 0)) >= 100 and int(quota.get("weekly_pct", 0)) >= 100
    except (TypeError, ValueError):
        return False


def over_cap_priority(
    email: str,
    account_map: dict[str, dict[str, Any]],
    *,
    kick_ghost: bool,
) -> tuple[int, float]:
    account = account_map.get(email)
    if not account:
        return (0, 0) if kick_ghost else (99, 0)

    status = account.get("status")
    if status == STATUS_ORPHAN:
        return (1, 0)
    if status == STATUS_AUTH_INVALID:
        return (1, 1)
    if status == STATUS_EXHAUSTED:
        return (2, 0)
    if status == STATUS_PERSONAL:
        return (3, 0)
    if status == STATUS_STANDBY:
        return (4, 0)
    if status == STATUS_ACTIVE:
        quota = account.get("last_quota") or {}
        try:
            primary_pct = float(quota.get("primary_pct", 0) or 0)
        except (TypeError, ValueError):
            primary_pct = 0
        return (5, 100 - primary_pct)
    return (6, 0)


def over_cap_victims(
    remaining_emails: list[str],
    account_map: dict[str, dict[str, Any]],
    *,
    excess: int,
    kick_ghost: bool,
) -> list[str]:
    if excess <= 0:
        return []
    return sorted(
        remaining_emails,
        key=lambda email: over_cap_priority(email, account_map, kick_ghost=kick_ghost),
    )[:excess]
