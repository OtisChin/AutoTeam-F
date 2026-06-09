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
        ACCOUNT_SOURCE_MANAGED,
        ACCOUNT_TYPE_FREE,
        ACCOUNT_TYPE_PLUS,
        SEAT_CODEX,
        STATUS_ACTIVE,
        add_account,
        ensure_session_only_account,
        load_accounts,
        update_account,
    )

    accounts = load_accounts()
    if not include_session_stubs:
        return accounts

    from autotoken.storage.auth_session_store import list_auth_session_emails

    session_emails = [normalize_email(email) for email in list_auth_session_emails()]
    session_emails = [email for email in session_emails if email]
    try:
        from autotoken.storage.auth_index import codex_auth_files_by_email

        indexed_auth_files = codex_auth_files_by_email(session_emails)
    except Exception:
        indexed_auth_files = {}
    gopay_success_emails = gopay_success_emails_from_bind_audit(normalize_email=normalize_email)

    existing_emails = {normalize_email(acc.get("email")) for acc in accounts if normalize_email(acc.get("email"))}
    for acc in list(accounts):
        normalized = normalize_email(acc.get("email"))
        if not normalized:
            continue
        indexed_auth_file = indexed_auth_files.get(normalized) or ""
        if str(acc.get("account_source") or "").strip().lower() == ACCOUNT_SOURCE_AUTH_SESSION_STUB and (
            indexed_auth_file or normalized in gopay_success_emails
        ):
            updated = update_account(
                normalized,
                status=STATUS_ACTIVE,
                account_type=ACCOUNT_TYPE_PLUS
                if normalized in gopay_success_emails
                else (acc.get("account_type") or ACCOUNT_TYPE_FREE),
                seat_type=acc.get("seat_type") or SEAT_CODEX,
                auth_file=indexed_auth_file or acc.get("auth_file"),
                account_source=ACCOUNT_SOURCE_MANAGED,
            )
            if updated:
                acc.update(updated)

    for email in session_emails:
        normalized = normalize_email(email)
        if not normalized or normalized in existing_emails:
            continue
        indexed_auth_file = indexed_auth_files.get(normalized) or ""
        if indexed_auth_file or normalized in gopay_success_emails:
            add_account(normalized, "", seat_type=SEAT_CODEX)
            restored = update_account(
                normalized,
                status=STATUS_ACTIVE,
                account_type=ACCOUNT_TYPE_PLUS if normalized in gopay_success_emails else ACCOUNT_TYPE_FREE,
                seat_type=SEAT_CODEX,
                auth_file=indexed_auth_file or None,
                account_source=ACCOUNT_SOURCE_MANAGED,
            )
            accounts.append(restored or session_only_account_stub_func(normalized))
        else:
            stub = ensure_session_only_account(normalized) or session_only_account_stub_func(normalized)
            accounts.append(stub)
        existing_emails.add(normalized)
    return accounts
