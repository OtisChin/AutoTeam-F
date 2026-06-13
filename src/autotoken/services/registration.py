"""Pure registration/OAuth result helpers."""

from __future__ import annotations

from typing import Any

from autotoken.storage.accounts import (
    ACCOUNT_SOURCE_MANAGED,
    ACCOUNT_TYPE_FREE,
    SEAT_CHATGPT,
    SEAT_CODEX,
    STATUS_ACTIVE,
    STATUS_PERSONAL,
)

PERSONAL_OAUTH_FAILED_REASON = "personal Codex OAuth 未返回 bundle"
TEAM_AUTH_MISSING_REASON = "已入 Team 席位但 Codex OAuth 未返回 bundle,需要补登录"
INVITE_REGISTER_FAILED_REASON = "invite 注册链路失败（register_with_invite 返回 False）"


def outcome_payload(email: str, status: str, **extra: Any) -> dict[str, Any]:
    return {"status": status, "email": email, **extra}


def replace_outcome(outcome: dict[str, Any] | None, *, email: str, status: str, **extra: Any) -> None:
    if outcome is None:
        return
    outcome.clear()
    outcome.update(outcome_payload(email, status, **extra))


def direct_registration_outcome(
    *,
    last_email: str,
    status: str,
    register_attempts: int,
    duplicate_swaps: int,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "status": status,
        "last_email": last_email,
        "register_attempts": register_attempts,
        "duplicate_swaps": duplicate_swaps,
        **extra,
    }


def replace_direct_registration_outcome(
    outcome: dict[str, Any] | None,
    *,
    last_email: str,
    status: str,
    register_attempts: int,
    duplicate_swaps: int,
    **extra: Any,
) -> None:
    if outcome is None:
        return
    outcome.clear()
    outcome.update(
        direct_registration_outcome(
            last_email=last_email,
            status=status,
            register_attempts=register_attempts,
            duplicate_swaps=duplicate_swaps,
            **extra,
        )
    )


def register_failed_outcome(email: str) -> dict[str, Any]:
    return {
        "status": "register_failed",
        "reason": INVITE_REGISTER_FAILED_REASON,
        "last_email": email,
    }


def kick_failed_reason(remove_status: str) -> str:
    return f"主号踢出失败 status={remove_status}"


def personal_success_update_fields(*, auth_file: str, last_active_at: float) -> dict[str, Any]:
    return {
        "status": STATUS_PERSONAL,
        "seat_type": SEAT_CODEX,
        "auth_file": auth_file,
        "last_active_at": last_active_at,
    }


def team_success_seat_label(plan_type: str | None) -> str:
    return SEAT_CHATGPT if (plan_type or "").lower() == "team" else SEAT_CODEX


def team_success_update_fields(*, plan_type: str | None, auth_file: str, last_active_at: float) -> dict[str, Any]:
    return {
        "status": STATUS_ACTIVE,
        "seat_type": team_success_seat_label(plan_type),
        "auth_file": auth_file,
        "last_active_at": last_active_at,
    }


def team_auth_missing_update_fields() -> dict[str, Any]:
    return {"status": STATUS_ACTIVE}


def auth_session_update_fields(*, last_active_at: float) -> dict[str, Any]:
    return {
        "status": STATUS_ACTIVE,
        "seat_type": SEAT_CODEX,
        "auth_file": None,
        "account_source": ACCOUNT_SOURCE_MANAGED,
        "last_active_at": last_active_at,
    }


def free_codex_oauth_update_fields(*, auth_file: str, last_active_at: float) -> dict[str, Any]:
    return {
        "status": STATUS_ACTIVE,
        "account_type": ACCOUNT_TYPE_FREE,
        "seat_type": SEAT_CODEX,
        "auth_file": auth_file,
        "last_active_at": last_active_at,
    }


def free_codex_oauth_bundle(
    bundle: dict[str, Any],
    *,
    email: str | None = None,
    force_email: bool = False,
) -> dict[str, Any]:
    normalized = dict(bundle)
    if force_email:
        normalized["email"] = str(email or "").strip()
    elif email is not None:
        normalized["email"] = str(normalized.get("email") or email or "").strip()
    normalized["plan_type"] = "free"
    normalized["chatgpt_plan_type"] = "free"
    return normalized


def account_codex_oauth_bundle(
    bundle: dict[str, Any],
    *,
    account_type: str | None = None,
    account_id: str | None = None,
) -> dict[str, Any]:
    """Align OAuth metadata with the locally confirmed account state."""
    normalized = dict(bundle)
    local_plan = str(account_type or "").strip().lower()
    token_plan = str(
        normalized.get("plan_type") or normalized.get("chatgpt_plan_type") or ""
    ).strip().lower()
    known_plans = {"free", "team", "plus", "pro"}

    effective_plan = token_plan if token_plan in known_plans else local_plan
    if local_plan in {"plus", "pro"} and effective_plan == "free":
        effective_plan = local_plan
    if effective_plan not in known_plans:
        effective_plan = "unknown"

    normalized["plan_type"] = effective_plan
    normalized["chatgpt_plan_type"] = effective_plan
    if not str(normalized.get("account_id") or "").strip() and str(account_id or "").strip():
        normalized["account_id"] = str(account_id).strip()
    return normalized


def free_codex_oauth_result(
    *,
    email: str,
    auth_file: str,
    password: str | None = None,
    cloudmail_account_id: str | None = None,
    mail_provider: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    result = {
        "email": email,
        "status": "success",
        "plan_type": "free",
        "auth_file": auth_file,
    }
    if password is not None:
        result["password"] = password
    if cloudmail_account_id is not None:
        result["cloudmail_account_id"] = cloudmail_account_id
    if mail_provider is not None:
        result["mail_provider"] = mail_provider
    if source is not None:
        result["source"] = source
    return result
