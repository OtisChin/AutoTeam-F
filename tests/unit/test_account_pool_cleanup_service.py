import logging

from autotoken import accounts as accounts_module
from autotoken.services import account_pool_cleanup


def _normalize_email(value):
    return str(value or "").strip().lower()


def test_remove_pool_accounts_from_local_and_mail_deletes_records_sessions_and_audits(monkeypatch):
    accounts = [
        {"email": "dead@example.com", "cloudmail_account_id": "cloud-1"},
        {"email": "main@example.com", "cloudmail_account_id": "cloud-main"},
    ]
    audits = []
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda account_list, email: next((account for account in account_list if account["email"] == email), None),
    )
    monkeypatch.setattr("autotoken.accounts.delete_account", lambda email: email == "dead@example.com")
    monkeypatch.setattr("autotoken.auth_session_store.delete_auth_session", lambda email: email == "session@example.com")

    removed = account_pool_cleanup.remove_pool_accounts_from_local_and_mail(
        ["", "main@example.com", "dead@example.com", "session@example.com"],
        is_main_account_email=lambda email: email == "main@example.com",
        append_account_delete_audit=lambda **kwargs: audits.append(kwargs),
        logger=logging.getLogger("test-account-pool-cleanup"),
        log_context="cleanup-test",
        reason="bad_account",
        message="removed locally",
    )

    assert removed == ["dead@example.com", "session@example.com"]
    assert [audit["email"] for audit in audits] == ["dead@example.com", "session@example.com"]
    assert audits[0]["account"] == accounts[0]
    assert audits[0]["record_deleted"] is True
    assert audits[0]["auth_session_deleted"] is False
    assert audits[1]["account"] is None
    assert audits[1]["record_deleted"] is False
    assert audits[1]["auth_session_deleted"] is True
    assert all(audit["mail_service_deleted"] is False for audit in audits)


def test_mark_pool_accounts_fail_updates_non_main_existing_accounts(monkeypatch):
    accounts = [
        {"email": "bad@example.com", "cloudmail_account_id": "cloud-1"},
        {"email": "main@example.com", "cloudmail_account_id": "cloud-main"},
    ]
    updates = []
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda account_list, email: next((account for account in account_list if account["email"] == email), None),
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **fields: updates.append((email, fields)))

    marked = account_pool_cleanup.mark_pool_accounts_fail(
        [" Bad@Example.com ", "missing@example.com", "main@example.com", ""],
        normalize_email=_normalize_email,
        is_main_account_email=lambda email: email == "main@example.com",
        logger=logging.getLogger("test-account-pool-cleanup"),
        reason="token_invalidated",
        message="token expired",
        failure_stage="refresh_failed",
        log_context="fail-test",
        now=123.0,
    )

    assert marked == ["bad@example.com"]
    assert updates == [
        (
            "bad@example.com",
            {
                "status": accounts_module.STATUS_FAIL,
                "discarded_at": 123.0,
                "discarded_reason": "token_invalidated",
                "last_bind_status": "failed",
                "last_bind_at": 123.0,
                "last_bind_message": "token expired",
                "last_bind_failure_stage": "refresh_failed",
            },
        )
    ]


def test_account_pool_cleanup_empty_inputs_are_noops():
    assert account_pool_cleanup.remove_pool_accounts_from_local_and_mail(
        [],
        is_main_account_email=lambda _email: False,
        append_account_delete_audit=lambda **_kwargs: None,
        logger=logging.getLogger("test-account-pool-cleanup"),
    ) == []
    assert account_pool_cleanup.mark_pool_accounts_fail(
        [],
        normalize_email=_normalize_email,
        is_main_account_email=lambda _email: False,
        logger=logging.getLogger("test-account-pool-cleanup"),
        reason="reason",
        message="message",
    ) == []
