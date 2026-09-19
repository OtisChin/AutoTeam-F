"""Canonical mapping of OpenAI plan-type strings to internal account types."""

from __future__ import annotations

ACCOUNT_TYPE_FREE = "free"
ACCOUNT_TYPE_TEAM = "team"
ACCOUNT_TYPE_PLUS = "plus"
ACCOUNT_TYPE_PRO = "pro"

# OpenAI is not consistent about plan-type identifiers: the wham/usage API and
# the JWT claims use values such as ``self_serve_business_prolite``,
# ``chatgptteamplan``, ``team_codex_plan`` or ``chatgptplusplan``.  Matching on
# exact strings therefore misses legitimate Team/Plus accounts, so classify by
# marker.  ``business`` is checked before ``pro`` because
# ``business_prolite``/``business_pro`` also contain ``pro``.
_TEAM_MARKERS = ("team", "business", "enterprise", "edu")


def normalize_plan_type(plan_type: object) -> str:
    """Return the internal account type for an OpenAI plan-type string.

    Returns one of ``free``/``plus``/``pro``/``team`` or an empty string when
    the value is unknown, so callers can decide whether to preserve existing
    state instead of downgrading.
    """
    normalized = str(plan_type or "").strip().lower()
    if not normalized:
        return ""
    if normalized in {ACCOUNT_TYPE_FREE, ACCOUNT_TYPE_PLUS, ACCOUNT_TYPE_PRO, ACCOUNT_TYPE_TEAM}:
        return normalized
    if any(marker in normalized for marker in _TEAM_MARKERS):
        return ACCOUNT_TYPE_TEAM
    if "pro" in normalized:
        return ACCOUNT_TYPE_PRO
    if "plus" in normalized:
        return ACCOUNT_TYPE_PLUS
    if "free" in normalized:
        return ACCOUNT_TYPE_FREE
    return ""
