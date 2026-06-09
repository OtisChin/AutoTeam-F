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
    monkeypatch.setattr("autotoken.accounts.ensure_session_only_account", lambda email: {**created, "email": email})

    result = account_session_stubs.load_accounts_with_session_stubs(
        normalize_email=_normalize_email,
    )

    assert result == [{"email": "session@example.com", "account_source": "auth_session_stub"}]


def test_load_accounts_with_session_stubs_restores_new_indexed_session_account(monkeypatch):
    captured = {"added": [], "updated": []}
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
    monkeypatch.setattr("autotoken.accounts.add_account", lambda email, password, seat_type: captured["added"].append((email, password, seat_type)))

    def fake_update_account(email, **fields):
        captured["updated"].append((email, fields))
        return {**restored, **fields}

    monkeypatch.setattr("autotoken.accounts.update_account", fake_update_account)

    result = account_session_stubs.load_accounts_with_session_stubs(normalize_email=_normalize_email)

    assert captured["added"] == [("indexed@example.com", "", accounts_module.SEAT_CODEX)]
    assert captured["updated"][0] == (
        "indexed@example.com",
        {
            "status": accounts_module.STATUS_ACTIVE,
            "account_type": accounts_module.ACCOUNT_TYPE_FREE,
            "seat_type": accounts_module.SEAT_CODEX,
            "auth_file": "auth-indexed.json",
            "account_source": accounts_module.ACCOUNT_SOURCE_MANAGED,
        },
    )
    assert result == [{**restored, **captured["updated"][0][1]}]


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

    def fake_update_account(email, **fields):
        return {"email": email, **fields}

    monkeypatch.setattr("autotoken.accounts.update_account", fake_update_account)

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
