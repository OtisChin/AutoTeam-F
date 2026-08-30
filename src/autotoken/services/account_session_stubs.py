"""Auth-session-only account loading and restoration helpers."""

from collections.abc import Callable


def session_only_account_stub(email: str) -> dict:
    from autotoken.storage.accounts import (
        ACCOUNT_SOURCE_AUTH_SESSION_STUB,
        ACCOUNT_TYPE_FREE,
        SEAT_CODEX,
        STATUS_ACTIVE,
    )

    return {
        "email": email,
        "password": "",
        "cloudmail_account_id": None,
        "status": STATUS_ACTIVE,
        "account_type": ACCOUNT_TYPE_FREE,
        "seat_type": SEAT_CODEX,
        "auth_file": "",
        "created_at": 0,
        "last_active_at": None,
        "account_source": ACCOUNT_SOURCE_AUTH_SESSION_STUB,
    }


def gopay_success_emails_from_bind_audit(*, normalize_email: Callable[[str | None], str]) -> set[str]:
    try:
        from autotoken.payments.bind_audit import list_bind_audits

        gopay_success_emails = set()
        for item in list_bind_audits(limit=1000):
            if str(item.get("flow") or "").lower() != "gopay" or str(item.get("status") or "").lower() != "success":
                continue
            for value in [
                item.get("email"),
                item.get("requested_email"),
                *(item.get("successful_emails") if isinstance(item.get("successful_emails"), list) else []),
            ]:
                normalized = normalize_email(value)
                if normalized:
                    gopay_success_emails.add(normalized)
        return gopay_success_emails
    except Exception:
        return set()


def load_accounts_with_session_stubs(
    *,
    include_session_stubs: bool = True,
    normalize_email: Callable[[str | None], str],
    session_only_account_stub_func: Callable[[str], dict] = session_only_account_stub,
) -> list[dict]:
    """Load accounts and persist auth-session-only records when requested."""
    from autotoken.storage.accounts import (
        ACCOUNT_SOURCE_AUTH_SESSION_STUB,
        ACCOUNT_TYPE_FREE,
        ACCOUNT_TYPE_PLUS,
        ACCOUNT_TYPE_PRO,
        ACCOUNT_TYPE_TEAM,
        SEAT_CODEX,
        STATUS_ACTIVE,
        STATUS_SESSION_ONLY,
        load_accounts,
        reconcile_auth_session_accounts,
    )

    accounts = load_accounts()
    if not include_session_stubs:
        return accounts

    from autotoken.storage.auth_session_store import list_auth_session_emails

    session_emails = []
    seen_session_emails = set()
    for value in list_auth_session_emails():
        email = normalize_email(value)
        if not email or email in seen_session_emails:
            continue
        seen_session_emails.add(email)
        session_emails.append(email)
    try:
        from autotoken.storage.auth_index import codex_auth_files_by_email

        indexed_auth_files = codex_auth_files_by_email(session_emails)
    except Exception:
        indexed_auth_files = {}
    gopay_success_emails = gopay_success_emails_from_bind_audit(normalize_email=normalize_email)

    positions = {
        email: index
        for index, account in enumerate(accounts)
        if (email := normalize_email(account.get("email")))
    }
    candidate_emails = []
    for email in session_emails:
        account = accounts[positions[email]] if email in positions else None
        if account is None:
            candidate_emails.append(email)
            continue
        source = str(account.get("account_source") or "").strip().lower()
        status = str(account.get("status") or "").strip().lower()
        if status == STATUS_SESSION_ONLY:
            candidate_emails.append(email)
            continue
        if source != ACCOUNT_SOURCE_AUTH_SESSION_STUB:
            continue
        account_type = str(account.get("account_type") or "").strip().lower()
        has_managed_evidence = bool(
            indexed_auth_files.get(email)
            or email in gopay_success_emails
            or account.get("auth_file")
            or account_type in {ACCOUNT_TYPE_PLUS, ACCOUNT_TYPE_PRO, ACCOUNT_TYPE_TEAM}
        )
        is_normalized_stub = (
            status == STATUS_ACTIVE
            and account_type == ACCOUNT_TYPE_FREE
            and str(account.get("seat_type") or "").strip().lower() == SEAT_CODEX
        )
        if has_managed_evidence or not is_normalized_stub:
            candidate_emails.append(email)

    reconciled = (
        reconcile_auth_session_accounts(
            candidate_emails,
            indexed_auth_files=indexed_auth_files,
            gopay_success_emails=gopay_success_emails,
        )
        if candidate_emails
        else {}
    )
    for email in candidate_emails:
        account = reconciled.get(email) or session_only_account_stub_func(email)
        if email in positions:
            accounts[positions[email]] = account
        else:
            positions[email] = len(accounts)
            accounts.append(account)
    return accounts
