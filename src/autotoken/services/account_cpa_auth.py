"""Account CPA auth conversion and metadata helpers."""

from collections.abc import Callable


def account_id_from_auth_data(auth_data: dict) -> str:
    account = auth_data.get("account") if isinstance(auth_data.get("account"), dict) else {}
    return str(account.get("id") or auth_data.get("account_id") or auth_data.get("accountId") or "").strip()


def convert_account_auth_session_to_cpa_auth(
    email: str,
    *,
    account: dict | None = None,
    force_account_type: str | None = None,
    normalize_email: Callable[[str | None], str],
    sanitize_account: Callable[[dict], dict],
) -> dict:
    """Convert an account auth_session into a local CPA codex auth file and update the account pool."""
    from autotoken.integrations.session_cpa_converter import SessionConversionError, save_cpa_auth_from_session
    from autotoken.storage.accounts import (
        ACCOUNT_SOURCE_MANAGED,
        ACCOUNT_TYPE_FREE,
        ACCOUNT_TYPE_PLUS,
        ACCOUNT_TYPE_PRO,
        ACCOUNT_TYPE_TEAM,
        SEAT_CODEX,
        STATUS_ACTIVE,
        find_account,
        load_accounts,
        update_account,
    )
    from autotoken.storage.auth_session_store import load_auth_session

    normalized_email = normalize_email(email)
    if not normalized_email:
        raise SessionConversionError("邮箱为空，无法转换 CPA 认证")
    if account is None:
        account = find_account(load_accounts(), normalized_email) or {"email": normalized_email}
    session = load_auth_session(normalized_email)
    if not session:
        raise SessionConversionError(f"未找到 auth_session: {normalized_email}")

    existing_account_type = str(account.get("account_type") or "").strip().lower()
    force_plan_type = ""
    if force_account_type:
        force_plan_type = str(force_account_type or "").strip().lower()
    elif existing_account_type in {ACCOUNT_TYPE_PLUS, ACCOUNT_TYPE_PRO, ACCOUNT_TYPE_TEAM}:
        force_plan_type = existing_account_type

    result = save_cpa_auth_from_session(
        session,
        source_name=normalized_email,
        force_plan_type=force_plan_type,
    )
    converted_plan = str(result.get("plan_type") or "").strip().lower()
    next_account_type = (
        force_account_type
        or (force_plan_type if force_plan_type in {ACCOUNT_TYPE_PLUS, ACCOUNT_TYPE_PRO, ACCOUNT_TYPE_TEAM} else None)
        or (
            converted_plan
            if converted_plan in {ACCOUNT_TYPE_FREE, ACCOUNT_TYPE_PLUS, ACCOUNT_TYPE_PRO, ACCOUNT_TYPE_TEAM}
            else None
        )
        or account.get("account_type")
    )
    saved = update_account(
        normalized_email,
        auth_file=result["auth_file"],
        account_type=next_account_type,
        seat_type=account.get("seat_type") or SEAT_CODEX,
        status=STATUS_ACTIVE,
        account_source=ACCOUNT_SOURCE_MANAGED,
    )
    return {
        **result,
        "account": sanitize_account(saved) if saved else None,
    }


def update_account_cpa_auth_plan_type(
    email: str,
    *,
    account: dict | None = None,
    plan_type: str = "plus",
    normalize_email: Callable[[str | None], str],
) -> dict:
    """Keep imported CPA auth JSON metadata aligned after a payment upgrade."""
    from autotoken.integrations.cpa_sync import update_local_auth_plan_type
    from autotoken.storage.accounts import update_account

    normalized_email = normalize_email(email)
    if not normalized_email:
        return {"status": "skipped", "reason": "email_empty"}
    preferred_path = str((account or {}).get("auth_file") or "").strip()
    result = update_local_auth_plan_type(normalized_email, preferred_path, plan_type=plan_type)
    auth_file = str(result.get("auth_file") or "").strip()
    if result.get("status") == "updated" and auth_file and auth_file != preferred_path:
        update_account(normalized_email, auth_file=auth_file)
        result["account_updated"] = True
    return result
