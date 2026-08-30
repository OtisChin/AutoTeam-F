import sqlite3
import sys
import time
from types import SimpleNamespace

import pytest

from autotoken import accounts


def test_payment_cache_invalidation_does_not_import_an_unloaded_route(monkeypatch):
    from autotoken import api_routes

    module_name = "autotoken.api_routes.brazil_pix"
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    monkeypatch.delattr(api_routes, "brazil_pix", raising=False)

    accounts._invalidate_payment_account_caches()

    assert module_name not in sys.modules


def test_payment_cache_invalidation_clears_an_already_loaded_route(monkeypatch):
    calls = []
    module_name = "autotoken.api_routes.brazil_pix"
    fake_module = SimpleNamespace(clear_auth_accounts_cache=lambda: calls.append("clear"))
    monkeypatch.setitem(sys.modules, module_name, fake_module)

    accounts._invalidate_payment_account_caches()

    assert calls == ["clear"]


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

def test_add_account_preserves_original_email_case(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(accounts, "get_admin_email", lambda: "")

    accounts.add_account("AmandaMiller143152@hotmail.com", "secret", mail_provider="outlook")
    created = accounts.load_accounts()[0]

    assert created["email"] == "amandamiller143152@hotmail.com"
    assert created["original_email"] == "AmandaMiller143152@hotmail.com"

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


def test_save_totp_metadata_persists_raw_secret_for_privileged_lookup(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(accounts, "get_admin_email", lambda: "")

    accounts.add_account("User@Example.com", "secret")
    updated = accounts.save_totp_metadata(
        "user@example.com",
        secret="ABCDEFGH234567AB",
        otpauth_uri="otpauth://totp/OpenAI:user@example.com?secret=ABCDEFGH234567AB&issuer=OpenAI",
        issuer="OpenAI",
        factor_label="OpenAI:user@example.com",
        enabled_at=1234.5,
    )

    assert updated["two_factor_enabled"] is True
    assert updated["totp_status"] == accounts.TOTP_STATUS_ENABLED
    assert updated["totp_secret_masked"] == "ABCD…67AB"
    assert "totp_secret" not in updated

    privileged = accounts.get_totp_credentials("USER@example.com")
    assert privileged["secret"] == "ABCDEFGH234567AB"
    assert privileged["otpauth_uri"].startswith("otpauth://totp/")
    assert privileged["masked_secret"] == "ABCD…67AB"
    assert privileged["issuer"] == "OpenAI"


def test_legacy_accounts_default_to_no_two_factor(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(accounts, "get_admin_email", lambda: "")

    accounts.save_accounts([{"email": "legacy@example.com", "status": accounts.STATUS_ACTIVE}])
    loaded = accounts.load_accounts()[0]

    assert loaded["two_factor_enabled"] is False
    assert loaded["totp_status"] == accounts.TOTP_STATUS_DISABLED
    assert loaded["totp_secret_masked"] == ""
    assert accounts.get_totp_credentials("legacy@example.com") is None


def test_save_totp_metadata_rejects_blank_or_invalid_secret_without_corrupting_existing(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(accounts, "get_admin_email", lambda: "")

    accounts.add_account("user@example.com", "secret")
    accounts.save_totp_metadata("user@example.com", secret="ABCDEFGH234567AB")

    for invalid in ["", "ABCDEF10"]:
        try:
            accounts.save_totp_metadata("user@example.com", secret=invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid TOTP secret should be rejected")

    assert accounts.get_totp_credentials("user@example.com")["secret"] == "ABCDEFGH234567AB"


def test_account_listing_never_exposes_raw_totp_secret(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(accounts, "get_admin_email", lambda: "")

    accounts.add_account("user@example.com", "secret")
    accounts.save_totp_metadata("user@example.com", secret="ABCDEFGH234567AB")

    listed = accounts.load_accounts()[0]
    serialized = str(listed)

    assert "totp_secret" not in listed
    assert "ABCDEFGH234567AB" not in serialized
    assert listed["totp_secret_masked"] == "ABCD…67AB"


def test_update_accounts_export_status_batch_uses_constant_database_connections_for_one_thousand_rows(
    tmp_path,
    monkeypatch,
):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    accounts.save_accounts(
        [
            {
                "email": f"user-{index}@example.com",
                "credentials_exported": False,
            }
            for index in range(1_000)
        ]
    )
    initialize_calls = 0
    connect_calls = 0
    real_initialize = accounts.sqlite_store.initialize
    real_connect = accounts.sqlite_store.connect

    def counted_initialize(*args, **kwargs):
        nonlocal initialize_calls
        initialize_calls += 1
        return real_initialize(*args, **kwargs)

    def counted_connect(*args, **kwargs):
        nonlocal connect_calls
        connect_calls += 1
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(accounts.sqlite_store, "initialize", counted_initialize)
    monkeypatch.setattr(accounts.sqlite_store, "connect", counted_connect)

    result = accounts.update_accounts_export_status_batch(
        [f"user-{index}@example.com" for index in range(1_000)],
        exported=True,
        exported_at=1234.5,
    )

    assert initialize_calls == 1
    assert connect_calls == 2
    assert len(result["accounts"]) == 1_000
    assert result["missing"] == []
    assert all(item["credentials_exported"] is True for item in result["accounts"])
    assert all(item["credentials_exported_at"] == 1234.5 for item in result["accounts"])


def test_update_accounts_export_status_batch_rolls_back_every_row_when_one_update_fails(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    accounts.save_accounts(
        [{"email": f"user-{index}@example.com", "credentials_exported": False} for index in range(3)]
    )
    real_upsert = accounts._upsert_account
    upsert_calls = 0

    def fail_second_upsert(conn, account):
        nonlocal upsert_calls
        upsert_calls += 1
        if upsert_calls == 2:
            raise RuntimeError("injected batch write failure")
        return real_upsert(conn, account)

    monkeypatch.setattr(accounts, "_upsert_account", fail_second_upsert)

    with pytest.raises(RuntimeError, match="injected batch write failure"):
        accounts.update_accounts_export_status_batch(
            [f"user-{index}@example.com" for index in range(3)],
            exported=True,
            exported_at=1234.5,
        )

    persisted = accounts.load_accounts()
    assert [item["credentials_exported"] for item in persisted] == [False, False, False]
    assert [item["credentials_exported_at"] for item in persisted] == [None, None, None]


def test_update_accounts_export_status_batch_clears_trade_allocations_in_same_transaction(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    accounts.save_accounts(
        [
            {"email": "first@example.com", "credentials_exported": True},
            {"email": "second@example.com", "credentials_exported": True},
        ]
    )
    db_file = accounts._db_path()
    with accounts.sqlite_store.connect(db_file) as conn:
        conn.execute(
            "INSERT INTO plus_cdks(code, quota_total, created_at, expires_at) VALUES (?, ?, ?, ?)",
            ("2-20260830-PLUS-ABCDEFGHIJKL", 2, 1.0, 9_999_999_999.0),
        )
        conn.executemany(
            "INSERT INTO plus_cdk_allocations(email, code, allocated_at) VALUES (?, ?, ?)",
            [
                ("first@example.com", "2-20260830-PLUS-ABCDEFGHIJKL", 2.0),
                ("second@example.com", "2-20260830-PLUS-ABCDEFGHIJKL", 2.0),
            ],
        )

    result = accounts.update_accounts_export_status_batch(
        ["FIRST@example.com", "second@example.com"],
        exported=False,
        exported_at=None,
    )

    assert result["trade_allocations"] == {
        "cleared": 2,
        "codes": ["2-20260830-PLUS-ABCDEFGHIJKL"],
    }
    assert all(item["credentials_exported"] is False for item in result["accounts"])
    with accounts.sqlite_store.connect(db_file) as conn:
        assert conn.execute("SELECT count(*) FROM plus_cdk_allocations").fetchone()[0] == 0


def test_reconcile_auth_session_accounts_batches_new_and_upgraded_rows(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(accounts, "get_admin_email", lambda: "")

    accounts.save_accounts(
        [
            {
                "email": "existing-stub@example.com",
                "status": accounts.STATUS_ACTIVE,
                "account_type": accounts.ACCOUNT_TYPE_FREE,
                "seat_type": accounts.SEAT_CODEX,
                "account_source": accounts.ACCOUNT_SOURCE_AUTH_SESSION_STUB,
            },
            {
                "email": "managed@example.com",
                "status": accounts.STATUS_PENDING,
                "account_type": accounts.ACCOUNT_TYPE_TEAM,
                "account_source": accounts.ACCOUNT_SOURCE_MANAGED,
            },
        ]
    )

    initialize_calls = 0
    connect_calls = 0
    real_initialize = accounts.sqlite_store.initialize
    real_connect = accounts.sqlite_store.connect

    def counted_initialize(*args, **kwargs):
        nonlocal initialize_calls
        initialize_calls += 1
        return real_initialize(*args, **kwargs)

    def counted_connect(*args, **kwargs):
        nonlocal connect_calls
        connect_calls += 1
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(accounts.sqlite_store, "initialize", counted_initialize)
    monkeypatch.setattr(accounts.sqlite_store, "connect", counted_connect)

    reconciled = accounts.reconcile_auth_session_accounts(
        [
            " New-Stub@Example.com ",
            "new-indexed@example.com",
            "new-plus@example.com",
            "existing-stub@example.com",
            "managed@example.com",
            "new-stub@example.com",
        ],
        indexed_auth_files={"new-indexed@example.com": "auth-indexed.json"},
        gopay_success_emails={"new-plus@example.com", "existing-stub@example.com"},
    )

    assert initialize_calls == 1
    # One connection initializes the schema and one performs the entire batch.
    assert connect_calls == 2
    assert list(reconciled) == [
        "new-stub@example.com",
        "new-indexed@example.com",
        "new-plus@example.com",
        "existing-stub@example.com",
        "managed@example.com",
    ]
    assert reconciled["new-stub@example.com"]["account_source"] == accounts.ACCOUNT_SOURCE_AUTH_SESSION_STUB
    assert reconciled["new-indexed@example.com"]["auth_file"] == "auth-indexed.json"
    assert reconciled["new-indexed@example.com"]["account_source"] == accounts.ACCOUNT_SOURCE_MANAGED
    assert reconciled["new-plus@example.com"]["account_type"] == accounts.ACCOUNT_TYPE_PLUS
    assert reconciled["existing-stub@example.com"]["account_type"] == accounts.ACCOUNT_TYPE_PLUS
    assert reconciled["existing-stub@example.com"]["account_source"] == accounts.ACCOUNT_SOURCE_MANAGED
    assert reconciled["managed@example.com"]["status"] == accounts.STATUS_PENDING
    assert reconciled["managed@example.com"]["account_type"] == accounts.ACCOUNT_TYPE_TEAM

    persisted = {item["email"]: item for item in accounts.load_accounts()}
    assert persisted["new-stub@example.com"]["account_source"] == accounts.ACCOUNT_SOURCE_AUTH_SESSION_STUB
    assert persisted["new-indexed@example.com"]["auth_file"] == "auth-indexed.json"
    assert persisted["new-plus@example.com"]["account_type"] == accounts.ACCOUNT_TYPE_PLUS


def test_reconcile_auth_session_accounts_normalizes_legacy_rows_without_downgrading_paid_accounts(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(accounts, "get_admin_email", lambda: "")
    accounts.save_accounts(
        [
            {
                "email": "legacy@example.com",
                "status": accounts.STATUS_SESSION_ONLY,
                "account_type": accounts.ACCOUNT_TYPE_FREE,
                "seat_type": accounts.SEAT_UNKNOWN,
                "account_source": accounts.ACCOUNT_SOURCE_MANAGED,
            },
            {
                "email": "paid@example.com",
                "status": accounts.STATUS_SESSION_ONLY,
                "account_type": accounts.ACCOUNT_TYPE_PLUS,
                "seat_type": accounts.SEAT_UNKNOWN,
                "account_source": accounts.ACCOUNT_SOURCE_AUTH_SESSION_STUB,
            },
            {
                "email": "auth@example.com",
                "status": accounts.STATUS_SESSION_ONLY,
                "account_type": accounts.ACCOUNT_TYPE_FREE,
                "seat_type": accounts.SEAT_UNKNOWN,
                "auth_file": "auth.json",
                "account_source": accounts.ACCOUNT_SOURCE_AUTH_SESSION_STUB,
            },
        ]
    )

    reconciled = accounts.reconcile_auth_session_accounts(
        ["legacy@example.com", "paid@example.com", "auth@example.com"]
    )

    assert reconciled["legacy@example.com"]["status"] == accounts.STATUS_ACTIVE
    assert reconciled["legacy@example.com"]["account_type"] == accounts.ACCOUNT_TYPE_FREE
    assert reconciled["legacy@example.com"]["seat_type"] == accounts.SEAT_CODEX
    assert reconciled["legacy@example.com"]["account_source"] == accounts.ACCOUNT_SOURCE_AUTH_SESSION_STUB
    assert reconciled["paid@example.com"]["status"] == accounts.STATUS_ACTIVE
    assert reconciled["paid@example.com"]["account_type"] == accounts.ACCOUNT_TYPE_PLUS
    assert reconciled["paid@example.com"]["account_source"] == accounts.ACCOUNT_SOURCE_MANAGED
    assert reconciled["auth@example.com"]["status"] == accounts.STATUS_ACTIVE
    assert reconciled["auth@example.com"]["auth_file"] == "auth.json"
    assert reconciled["auth@example.com"]["account_source"] == accounts.ACCOUNT_SOURCE_MANAGED
    assert all("updated_at" in account for account in reconciled.values())
