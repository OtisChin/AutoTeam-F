import sqlite3
import time

from autotoken import accounts


def test_add_and_update_account_persists_data(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(accounts, "get_admin_email", lambda: "")

    accounts.add_account("user@example.com", "secret", cloudmail_account_id=123)
    created = accounts.load_accounts()

    assert len(created) == 1
    assert created[0]["email"] == "user@example.com"
    assert created[0]["cloudmail_account_id"] == 123
    assert created[0]["status"] == accounts.STATUS_PENDING
    assert created[0]["account_type"] == accounts.ACCOUNT_TYPE_FREE

    updated = accounts.update_account("user@example.com", status=accounts.STATUS_ACTIVE, auth_file="auth.json")

    assert updated["status"] == accounts.STATUS_ACTIVE
    assert updated["auth_file"] == "auth.json"
    assert accounts.load_accounts()[0]["auth_file"] == "auth.json"


def test_update_account_only_rewrites_target_row(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(accounts, "get_admin_email", lambda: "")

    accounts.add_account("first@example.com", "secret")
    accounts.add_account("second@example.com", "secret")
    with sqlite3.connect(accounts._db_path()) as conn:
        before = conn.execute(
            "SELECT updated_at FROM accounts WHERE email = ?",
            ("second@example.com",),
        ).fetchone()[0]

    time.sleep(0.01)
    accounts.update_account("first@example.com", account_type=accounts.ACCOUNT_TYPE_PLUS)

    with sqlite3.connect(accounts._db_path()) as conn:
        after = conn.execute(
            "SELECT updated_at FROM accounts WHERE email = ?",
            ("second@example.com",),
        ).fetchone()[0]

    assert after == before


def test_ensure_session_only_account_persists_auth_session_stub(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(accounts, "get_admin_email", lambda: "")

    created = accounts.ensure_session_only_account("User@Example.com")

    assert created["email"] == "user@example.com"
    assert created["status"] == accounts.STATUS_ACTIVE
    assert created["account_type"] == accounts.ACCOUNT_TYPE_FREE
    assert created["seat_type"] == accounts.SEAT_CODEX
    assert created["account_source"] == accounts.ACCOUNT_SOURCE_AUTH_SESSION_STUB
    assert accounts.load_accounts()[0]["account_source"] == accounts.ACCOUNT_SOURCE_AUTH_SESSION_STUB


def test_ensure_session_only_account_does_not_overwrite_managed_account(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(accounts, "get_admin_email", lambda: "")

    accounts.add_account("user@example.com", "secret")
    original = accounts.ensure_session_only_account("user@example.com")

    assert original["status"] == accounts.STATUS_PENDING
    assert original["account_source"] == accounts.ACCOUNT_SOURCE_MANAGED
    assert original["password"] == "secret"


def test_get_active_accounts_excludes_main_account(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(accounts, "get_admin_email", lambda: "owner@example.com")

    accounts.save_accounts(
        [
            {"email": "owner@example.com", "status": accounts.STATUS_ACTIVE},
            {"email": "member@example.com", "status": accounts.STATUS_ACTIVE},
            {"email": "standby@example.com", "status": accounts.STATUS_STANDBY},
        ]
    )

    active = accounts.get_active_accounts()

    assert [item["email"] for item in active] == ["member@example.com"]


def test_get_standby_accounts_orders_recovered_first_and_skips_main_account(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(accounts, "get_admin_email", lambda: "owner@example.com")

    now = time.time()
    accounts.save_accounts(
        [
            {
                "email": "owner@example.com",
                "status": accounts.STATUS_STANDBY,
                "quota_resets_at": None,
                "quota_exhausted_at": None,
            },
            {
                "email": "ready@example.com",
                "status": accounts.STATUS_STANDBY,
                "quota_resets_at": now - 60,
                "quota_exhausted_at": now - 120,
            },
            {
                "email": "later@example.com",
                "status": accounts.STATUS_STANDBY,
                "quota_resets_at": now + 600,
                "quota_exhausted_at": now - 30,
            },
            {
                "email": "always@example.com",
                "status": accounts.STATUS_STANDBY,
                "quota_resets_at": None,
                "quota_exhausted_at": None,
            },
        ]
    )

    standby = accounts.get_standby_accounts()

    assert [item["email"] for item in standby] == [
        "always@example.com",
        "ready@example.com",
        "later@example.com",
    ]
    assert standby[0]["_quota_recovered"] is True
    assert standby[1]["_quota_recovered"] is True
    assert standby[2]["_quota_recovered"] is False
    assert accounts.get_next_reusable_account()["email"] == "always@example.com"
