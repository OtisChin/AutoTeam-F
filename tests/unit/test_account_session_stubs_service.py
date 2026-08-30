from autotoken import accounts as accounts_module
from autotoken.services import account_session_stubs


def _normalize_email(value):
    return str(value or "").strip().lower()


def test_session_only_account_stub_uses_account_constants():
    stub = account_session_stubs.session_only_account_stub("user@example.com")

    assert stub == {
        "email": "user@example.com",
        "password": "",
        "cloudmail_account_id": None,
        "status": accounts_module.STATUS_ACTIVE,
        "account_type": accounts_module.ACCOUNT_TYPE_FREE,
        "seat_type": accounts_module.SEAT_CODEX,
        "auth_file": "",
        "created_at": 0,
        "last_active_at": None,
        "account_source": accounts_module.ACCOUNT_SOURCE_AUTH_SESSION_STUB,
    }


def test_load_accounts_without_session_stubs_returns_loaded_accounts(monkeypatch):
    loaded = [{"email": "managed@example.com"}]
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: loaded)

    assert account_session_stubs.load_accounts_with_session_stubs(
        include_session_stubs=False,
        normalize_email=_normalize_email,
    ) is loaded


def test_load_accounts_with_session_stubs_persists_free_stub(monkeypatch):
    created = {"email": "session@example.com", "account_source": accounts_module.ACCOUNT_SOURCE_AUTH_SESSION_STUB}
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [])
    monkeypatch.setattr("autotoken.auth_session_store.list_auth_session_emails", lambda: [" Session@Example.com "])
    monkeypatch.setattr("autotoken.auth_index.codex_auth_files_by_email", lambda _emails: {})
    monkeypatch.setattr("autotoken.bind_audit.list_bind_audits", lambda limit: [])
    monkeypatch.setattr(
        "autotoken.accounts.reconcile_auth_session_accounts",
        lambda emails, **_kwargs: {emails[0]: {**created, "email": emails[0]}},
    )

    result = account_session_stubs.load_accounts_with_session_stubs(
        normalize_email=_normalize_email,
    )

    assert result == [{"email": "session@example.com", "account_source": "auth_session_stub"}]


def test_load_accounts_with_session_stubs_restores_new_indexed_session_account(monkeypatch):
    captured = {}
    restored = {
        "email": "indexed@example.com",
        "status": accounts_module.STATUS_ACTIVE,
        "account_type": accounts_module.ACCOUNT_TYPE_FREE,
        "auth_file": "auth-indexed.json",
        "account_source": accounts_module.ACCOUNT_SOURCE_MANAGED,
    }
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [])
    monkeypatch.setattr("autotoken.auth_session_store.list_auth_session_emails", lambda: ["indexed@example.com"])
    monkeypatch.setattr("autotoken.auth_index.codex_auth_files_by_email", lambda emails: {emails[0]: "auth-indexed.json"})
    monkeypatch.setattr("autotoken.bind_audit.list_bind_audits", lambda limit: [])

    def fake_reconcile(emails, *, indexed_auth_files, gopay_success_emails):
        captured["emails"] = list(emails)
        captured["indexed"] = dict(indexed_auth_files)
        captured["gopay"] = set(gopay_success_emails)
        return {emails[0]: restored}

    monkeypatch.setattr("autotoken.accounts.reconcile_auth_session_accounts", fake_reconcile)

    result = account_session_stubs.load_accounts_with_session_stubs(normalize_email=_normalize_email)

    assert captured == {
        "emails": ["indexed@example.com"],
        "indexed": {"indexed@example.com": "auth-indexed.json"},
        "gopay": set(),
    }
    assert result == [restored]


def test_load_accounts_with_session_stubs_upgrades_existing_stub_after_gopay_success(monkeypatch):
    account = {
        "email": "plus@example.com",
        "account_type": accounts_module.ACCOUNT_TYPE_FREE,
        "seat_type": "",
        "auth_file": "",
        "account_source": accounts_module.ACCOUNT_SOURCE_AUTH_SESSION_STUB,
    }
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.auth_session_store.list_auth_session_emails", lambda: ["plus@example.com"])
    monkeypatch.setattr("autotoken.auth_index.codex_auth_files_by_email", lambda _emails: {})
    monkeypatch.setattr(
        "autotoken.bind_audit.list_bind_audits",
        lambda limit: [{"flow": "gopay", "status": "success", "successful_emails": ["Plus@Example.com"]}],
    )

    def fake_reconcile(emails, *, indexed_auth_files, gopay_success_emails):
        assert indexed_auth_files == {}
        assert gopay_success_emails == {"plus@example.com"}
        return {
            emails[0]: {
                "email": emails[0],
                "account_type": accounts_module.ACCOUNT_TYPE_PLUS,
                "seat_type": accounts_module.SEAT_CODEX,
                "auth_file": "",
                "account_source": accounts_module.ACCOUNT_SOURCE_MANAGED,
                "status": accounts_module.STATUS_ACTIVE,
            }
        }

    monkeypatch.setattr("autotoken.accounts.reconcile_auth_session_accounts", fake_reconcile)

    result = account_session_stubs.load_accounts_with_session_stubs(normalize_email=_normalize_email)

    assert result == [
        {
            "email": "plus@example.com",
            "account_type": accounts_module.ACCOUNT_TYPE_PLUS,
            "seat_type": accounts_module.SEAT_CODEX,
            "auth_file": "",
            "account_source": accounts_module.ACCOUNT_SOURCE_MANAGED,
            "status": accounts_module.STATUS_ACTIVE,
        }
    ]


def test_load_accounts_with_session_stubs_reconciles_all_rows_in_one_batch(monkeypatch):
    loaded = [
        {
            "email": "existing@example.com",
            "status": accounts_module.STATUS_ACTIVE,
            "account_source": accounts_module.ACCOUNT_SOURCE_AUTH_SESSION_STUB,
        }
    ]
    captured = {}
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: loaded)
    monkeypatch.setattr(
        "autotoken.auth_session_store.list_auth_session_emails",
        lambda: [" Existing@Example.com ", "new@example.com", "NEW@example.com"],
    )
    monkeypatch.setattr(
        "autotoken.auth_index.codex_auth_files_by_email",
        lambda emails: {"existing@example.com": "auth-existing.json"},
    )
    monkeypatch.setattr(
        "autotoken.bind_audit.list_bind_audits",
        lambda limit: [{"flow": "gopay", "status": "success", "email": "new@example.com"}],
    )

    def fake_reconcile(session_emails, *, indexed_auth_files, gopay_success_emails):
        captured["session_emails"] = list(session_emails)
        captured["indexed_auth_files"] = dict(indexed_auth_files)
        captured["gopay_success_emails"] = set(gopay_success_emails)
        return {
            "existing@example.com": {
                "email": "existing@example.com",
                "status": accounts_module.STATUS_ACTIVE,
                "auth_file": "auth-existing.json",
                "account_source": accounts_module.ACCOUNT_SOURCE_MANAGED,
            },
            "new@example.com": {
                "email": "new@example.com",
                "status": accounts_module.STATUS_ACTIVE,
                "account_type": accounts_module.ACCOUNT_TYPE_PLUS,
                "account_source": accounts_module.ACCOUNT_SOURCE_MANAGED,
            },
        }

    monkeypatch.setattr("autotoken.accounts.reconcile_auth_session_accounts", fake_reconcile)

    def legacy_row_write_called(*_args, **_kwargs):
        raise AssertionError("session reconciliation must not open a transaction per account")

    monkeypatch.setattr("autotoken.accounts.ensure_session_only_account", legacy_row_write_called)
    monkeypatch.setattr("autotoken.accounts.add_account", legacy_row_write_called)
    monkeypatch.setattr("autotoken.accounts.update_account", legacy_row_write_called)

    result = account_session_stubs.load_accounts_with_session_stubs(normalize_email=_normalize_email)

    assert captured == {
        "session_emails": ["existing@example.com", "new@example.com"],
        "indexed_auth_files": {"existing@example.com": "auth-existing.json"},
        "gopay_success_emails": {"new@example.com"},
    }
    assert result == [
        {
            "email": "existing@example.com",
            "status": accounts_module.STATUS_ACTIVE,
            "auth_file": "auth-existing.json",
            "account_source": accounts_module.ACCOUNT_SOURCE_MANAGED,
        },
        {
            "email": "new@example.com",
            "status": accounts_module.STATUS_ACTIVE,
            "account_type": accounts_module.ACCOUNT_TYPE_PLUS,
            "account_source": accounts_module.ACCOUNT_SOURCE_MANAGED,
        },
    ]


def test_load_accounts_with_session_stubs_skips_write_transaction_for_normalized_rows(monkeypatch):
    loaded = [
        {
            "email": "session@example.com",
            "status": accounts_module.STATUS_ACTIVE,
            "account_type": accounts_module.ACCOUNT_TYPE_FREE,
            "seat_type": accounts_module.SEAT_CODEX,
            "auth_file": None,
            "account_source": accounts_module.ACCOUNT_SOURCE_AUTH_SESSION_STUB,
        }
    ]
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: loaded)
    monkeypatch.setattr("autotoken.auth_session_store.list_auth_session_emails", lambda: ["session@example.com"])
    monkeypatch.setattr("autotoken.auth_index.codex_auth_files_by_email", lambda _emails: {})
    monkeypatch.setattr("autotoken.bind_audit.list_bind_audits", lambda limit: [])

    def unexpected_reconcile(*_args, **_kwargs):
        raise AssertionError("an unchanged account listing must stay read-only")

    monkeypatch.setattr("autotoken.accounts.reconcile_auth_session_accounts", unexpected_reconcile)

    result = account_session_stubs.load_accounts_with_session_stubs(normalize_email=_normalize_email)

    assert result is loaded
