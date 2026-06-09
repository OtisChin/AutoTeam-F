"""Pure selection helpers for Team cleanup commands."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from autotoken.core.normalization import normalized_email


def local_account_emails(
    accounts: Iterable[dict[str, Any]],
    *,
    is_main_account_email: Callable[[str | None], bool],
) -> set[str]:
    return {
        email
        for account in accounts
        if (email := normalized_email(account.get("email"))) and not is_main_account_email(email)
    }


def split_local_and_external_members(
    members: Iterable[dict[str, Any]],
    local_emails: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    normalized_local_emails = {normalized_email(email) for email in local_emails if normalized_email(email)}
    local_members: list[dict[str, Any]] = []
    external_members: list[dict[str, Any]] = []

    for member in members:
        email = normalized_email(member.get("email"))
        if email in normalized_local_emails:
            local_members.append(member)
        else:
            external_members.append(member)
    return local_members, external_members


def removal_count(*, total_members: int, max_seats: int | None, default_max_seats: int = 5) -> tuple[int, int]:
    effective_max_seats = default_max_seats if max_seats is None else int(max_seats)
    return max(0, int(total_members) - effective_max_seats), effective_max_seats


def removable_members(
    local_members: Iterable[dict[str, Any]],
    accounts: Iterable[dict[str, Any]],
    *,
    exhausted_status: str,
) -> list[dict[str, Any]]:
    accounts_by_email = {normalized_email(account.get("email")): account for account in accounts}

    def priority(member: dict[str, Any]) -> tuple[int, Any]:
        account = accounts_by_email.get(normalized_email(member.get("email"))) or {}
        exhausted_rank = 0 if account.get("status") == exhausted_status else 1
        return exhausted_rank, account.get("created_at", 0)

    return sorted(local_members, key=priority)


def pending_invites_for_local_accounts(invites: Iterable[dict[str, Any]], local_emails: set[str]) -> list[dict[str, Any]]:
    normalized_local_emails = {normalized_email(email) for email in local_emails if normalized_email(email)}
    return [
        invite
        for invite in invites
        if normalized_email(invite.get("email_address")) in normalized_local_emails and invite.get("id")
    ]
