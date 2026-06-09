"""Local account-pool cleanup and failure marking helpers."""

import logging
import time
from collections.abc import Callable


def remove_pool_accounts_from_local_and_mail(
    emails: list[str],
    *,
    is_main_account_email: Callable[[str | None], bool],
    append_account_delete_audit: Callable[..., None],
    logger: logging.Logger,
    log_context: str = "account-cleanup",
    reason: str = "unspecified",
    message: str = "",
) -> list[str]:
    """Remove unusable accounts from the local pool without deleting mail-service accounts."""
    if not emails:
        return []
    from autotoken.storage.accounts import delete_account as delete_local_account
    from autotoken.storage.accounts import find_account, load_accounts
    from autotoken.storage.auth_session_store import delete_auth_session

    removed = []
    accounts = load_accounts()
    for email in emails:
        if not email or is_main_account_email(email):
            continue
        account = find_account(accounts, email)
        record_deleted = delete_local_account(email)
        session_deleted = delete_auth_session(email)
        if record_deleted or session_deleted:
            removed.append(email)
        append_account_delete_audit(
            email=email,
            log_context=log_context,
            reason=reason,
            message=message,
            account=account,
            record_deleted=record_deleted,
            auth_session_deleted=session_deleted,
            mail_service_deleted=False,
        )
        logger.info(
            "[%s] account removed locally: email=%s reason=%s record_deleted=%s auth_session_deleted=%s mail_service_deleted=%s cloudmail_account_id=%s",
            log_context,
            email,
            reason,
            record_deleted,
            session_deleted,
            False,
            (account or {}).get("cloudmail_account_id"),
        )
    return removed


def mark_pool_accounts_fail(
    emails: list[str],
    *,
    normalize_email: Callable[[str | None], str],
    is_main_account_email: Callable[[str | None], bool],
    logger: logging.Logger,
    reason: str,
    message: str,
    failure_stage: str = "token_invalidated",
    log_context: str = "account-fail",
    now: float | None = None,
) -> list[str]:
    """Mark unusable accounts as Fail without removing local/mail records."""
    if not emails:
        return []
    from autotoken.storage.accounts import STATUS_FAIL, find_account, load_accounts, update_account

    marked = []
    accounts = load_accounts()
    now_ts = time.time() if now is None else float(now)
    for email in emails:
        email = normalize_email(email)
        if not email or is_main_account_email(email):
            continue
        account = find_account(accounts, email)
        if not account:
            logger.info("[%s] account not found while marking Fail: email=%s", log_context, email)
            continue
        update_account(
            email,
            status=STATUS_FAIL,
            discarded_at=now_ts,
            discarded_reason=reason,
            last_bind_status="failed",
            last_bind_at=now_ts,
            last_bind_message=message,
            last_bind_failure_stage=failure_stage,
        )
        marked.append(email)
        logger.info(
            "[%s] account marked Fail: email=%s reason=%s cloudmail_account_id=%s",
            log_context,
            email,
            reason,
            account.get("cloudmail_account_id"),
        )
    return marked
