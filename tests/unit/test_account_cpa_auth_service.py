import pytest

from autotoken import accounts as accounts_module
from autotoken.services import account_cpa_auth


def _normalize_email(value):
    return str(value or "").strip().lower()


def _sanitize_account(account):
    return {**account, "sanitized": True}


def test_account_id_from_auth_data_reads_nested_and_flat_shapes():
    assert account_cpa_auth.account_id_from_auth_data({"account": {"id": "nested"}}) == "nested"
    assert account_cpa_auth.account_id_from_auth_data({"account_id": "flat"}) == "flat"
    assert account_cpa_auth.account_id_from_auth_data({"accountId": "camel"}) == "camel"
    assert account_cpa_auth.account_id_from_auth_data({"account": "bad"}) == ""


def test_update_account_cpa_auth_plan_type_skips_empty_email():
    assert account_cpa_auth.update_account_cpa_auth_plan_type(
        " ",
        normalize_email=_normalize_email,
    ) == {"status": "skipped", "reason": "email_empty"}


def test_update_account_cpa_auth_plan_type_updates_account_when_auth_file_changes(monkeypatch):
    updates = {}
    monkeypatch.setattr(
        "autotoken.cpa_sync.update_local_auth_plan_type",
        lambda email, preferred_path, plan_type: {
            "status": "updated",
            "email": email,
            "preferred_path": preferred_path,
            "plan_type": plan_type,
            "auth_file": "new-auth.json",
        },
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **fields: updates.update({email: fields}))

    result = account_cpa_auth.update_account_cpa_auth_plan_type(
        " USER@Example.com ",
        account={"auth_file": "old-auth.json"},
        plan_type="pro",
        normalize_email=_normalize_email,
    )

    assert result["account_updated"] is True
    assert result["email"] == "user@example.com"
    assert result["preferred_path"] == "old-auth.json"
    assert result["plan_type"] == "pro"
    assert updates == {"user@example.com": {"auth_file": "new-auth.json"}}


def test_update_account_cpa_auth_plan_type_does_not_update_account_for_same_auth_file(monkeypatch):
    updates = []
    monkeypatch.setattr(
        "autotoken.cpa_sync.update_local_auth_plan_type",
        lambda _email, preferred_path, plan_type: {"status": "updated", "auth_file": preferred_path},
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda *args, **kwargs: updates.append((args, kwargs)))

    result = account_cpa_auth.update_account_cpa_auth_plan_type(
        "user@example.com",
        account={"auth_file": "same-auth.json"},
        normalize_email=_normalize_email,
    )

    assert result == {"status": "updated", "auth_file": "same-auth.json"}
    assert updates == []


def test_convert_account_auth_session_to_cpa_auth_updates_account_and_sanitizes(monkeypatch):
    account = {"email": "user@example.com", "account_type": accounts_module.ACCOUNT_TYPE_FREE, "seat_type": ""}
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda loaded, email: account if loaded == [account] and email == "user@example.com" else None,
    )
    monkeypatch.setattr("autotoken.auth_session_store.load_auth_session", lambda email: {"email": email})
    monkeypatch.setattr(
        "autotoken.session_cpa_converter.save_cpa_auth_from_session",
        lambda session, source_name, force_plan_type: {
            "auth_file": "converted.json",
            "filename": "converted.json",
            "plan_type": "plus",
        },
    )
    monkeypatch.setattr(
        "autotoken.accounts.update_account",
        lambda email, **fields: {"email": email, **fields},
    )

    result = account_cpa_auth.convert_account_auth_session_to_cpa_auth(
        " User@Example.com ",
        normalize_email=_normalize_email,
        sanitize_account=_sanitize_account,
    )

    assert result["auth_file"] == "converted.json"
    assert result["account"] == {
        "email": "user@example.com",
        "auth_file": "converted.json",
        "account_type": accounts_module.ACCOUNT_TYPE_PLUS,
        "seat_type": accounts_module.SEAT_CODEX,
        "status": accounts_module.STATUS_ACTIVE,
        "account_source": accounts_module.ACCOUNT_SOURCE_MANAGED,
        "sanitized": True,
    }


def test_convert_account_auth_session_to_cpa_auth_preserves_existing_plus_plan(monkeypatch):
    captured = {}
    account = {"email": "plus@example.com", "account_type": accounts_module.ACCOUNT_TYPE_PLUS}
    monkeypatch.setattr("autotoken.auth_session_store.load_auth_session", lambda email: {"email": email})

    def fake_save_cpa_auth_from_session(session, source_name, force_plan_type):
        captured["force_plan_type"] = force_plan_type
        return {"auth_file": "converted.json", "plan_type": "free"}

    monkeypatch.setattr("autotoken.session_cpa_converter.save_cpa_auth_from_session", fake_save_cpa_auth_from_session)
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **fields: {"email": email, **fields})

    result = account_cpa_auth.convert_account_auth_session_to_cpa_auth(
        "plus@example.com",
        account=account,
        normalize_email=_normalize_email,
        sanitize_account=lambda account: account,
    )

    assert captured["force_plan_type"] == accounts_module.ACCOUNT_TYPE_PLUS
    assert result["account"]["account_type"] == accounts_module.ACCOUNT_TYPE_PLUS


def test_convert_account_auth_session_to_cpa_auth_raises_for_missing_session():
    from autotoken.session_cpa_converter import SessionConversionError

    with pytest.raises(SessionConversionError, match="邮箱为空"):
        account_cpa_auth.convert_account_auth_session_to_cpa_auth(
            "",
            normalize_email=_normalize_email,
            sanitize_account=_sanitize_account,
        )
