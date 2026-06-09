"""Rotation and fill account-selection helpers."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from autotoken.core.normalization import normalized_email

GOOGLE_AUTO_REUSE_DOMAINS = {"gmail.com", "googlemail.com"}
GOOGLE_AUTO_REUSE_SKIP_REASON = "Google 登录账号暂不支持自动复用"


def account_login_provider(account: dict[str, Any] | None) -> str:
    account = account or {}
    for key in ("login_provider", "auth_provider", "oauth_provider"):
        provider = str(account.get(key) or "").strip().lower()
        if provider:
            return provider

    email = normalized_email(account.get("email"))
    if "@" in email and email.rsplit("@", 1)[-1] in GOOGLE_AUTO_REUSE_DOMAINS:
        return "google"

    return ""


def auto_reuse_skip_reason(account: dict[str, Any] | None) -> str | None:
    if account_login_provider(account) == "google":
        return GOOGLE_AUTO_REUSE_SKIP_REASON
    return None


def standby_reuse_candidates(
    accounts: Iterable[dict[str, Any]],
    *,
    is_main_account_email: Callable[[str | None], bool],
    recovered_only: bool = False,
    exclude_email: str | None = None,
) -> list[dict[str, Any]]:
    excluded = normalized_email(exclude_email)
    candidates: list[dict[str, Any]] = []
    for account in accounts:
        email = normalized_email(account.get("email"))
        if not email or is_main_account_email(email):
            continue
        if excluded and email == excluded:
            continue
        if recovered_only and not account.get("_quota_recovered"):
            continue
        candidates.append(account)
    return candidates


def estimate_current_member_count(
    *,
    api_count: int,
    initial_api_count: int,
    removed_now: int,
    local_active_count: int,
) -> tuple[int, bool, bool]:
    if api_count <= 0:
        return local_active_count, True, False

    estimates = [api_count]
    if initial_api_count > 0 and removed_now > 0:
        estimates.append(max(0, initial_api_count - removed_now))

    current_count = min(estimates)
    return current_count, False, current_count != api_count


def vacancy_count(*, target: int, current_count: int) -> int:
    return target - current_count


def _remaining_primary_quota(account: dict[str, Any]) -> float:
    quota = account.get("last_quota") or {}
    try:
        primary_pct = float(quota.get("primary_pct", 0) or 0)
    except (TypeError, ValueError):
        primary_pct = 0
    return 100 - primary_pct


def overfill_cleanup_candidates(
    accounts: Iterable[dict[str, Any]],
    *,
    is_main_account_email: Callable[[str | None], bool],
    active_status: str,
) -> list[dict[str, Any]]:
    candidates = [
        account
        for account in accounts
        if account.get("status") == active_status and not is_main_account_email(account.get("email"))
    ]
    return sorted(candidates, key=_remaining_primary_quota)
