"""Pure planning helpers for personal/free-account fill flows."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from autotoken.core.normalization import normalized_email


@dataclass(frozen=True)
class PersonalFillCapacityPlan:
    requested_count: int
    baseline_count: int
    cap: int
    available_slots: int
    target_count: int
    rejected: bool
    clamped: bool

    @property
    def should_run(self) -> bool:
        return self.target_count > 0 and not self.rejected


def _normalized_email_set(emails: Iterable[str]) -> set[str]:
    return {email for email in (normalized_email(value) for value in emails) if email}


def capacity_plan(*, requested_count: int, baseline_emails: Iterable[str], cap: int) -> PersonalFillCapacityPlan:
    requested = max(0, int(requested_count or 0))
    baseline_count = len(_normalized_email_set(baseline_emails))
    safe_cap = max(0, int(cap or 0))
    available_slots = max(0, safe_cap - baseline_count)
    rejected = baseline_count >= safe_cap
    target_count = 0 if rejected else min(requested, available_slots)
    return PersonalFillCapacityPlan(
        requested_count=requested,
        baseline_count=baseline_count,
        cap=safe_cap,
        available_slots=available_slots,
        target_count=target_count,
        rejected=rejected,
        clamped=not rejected and target_count < requested,
    )


def batch_size(*, max_batch_size: int, remaining: int, baseline_emails: Iterable[str], cap: int) -> int:
    baseline_count = len(_normalized_email_set(baseline_emails))
    available_slots = max(0, int(cap or 0) - baseline_count)
    return max(0, min(max(0, int(max_batch_size or 0)), max(0, int(remaining or 0)), available_slots))


def new_member_emails(current_non_master_emails: Iterable[str], baseline_emails: Iterable[str]) -> set[str]:
    return _normalized_email_set(current_non_master_emails) - _normalized_email_set(baseline_emails)


def outcome_with_default_status(outcome: dict[str, Any] | None, *, email: str | None) -> dict[str, Any]:
    result = dict(outcome or {})
    if not result.get("status"):
        result["status"] = "success" if email else "unknown_failure"
    return result


def summarize_outcomes(outcomes: Iterable[dict[str, Any] | None]) -> OrderedDict[str, int]:
    counts: OrderedDict[str, int] = OrderedDict()
    for outcome in outcomes:
        status = (outcome or {}).get("status") or "unknown"
        counts[status] = counts.get(status, 0) + 1
    return counts
