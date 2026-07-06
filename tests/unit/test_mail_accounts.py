import pytest

from autotoken.storage import mail_accounts


def test_import_mail_accounts_persists_rows_in_sqlite(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "mail.sqlite3"))

    result = mail_accounts.import_mail_accounts(
        "aharvey183195@mail.com----gpt-pass----mail-pass----rt.1.token\n"
        "bad-line\n"
        " second@mail.com ---- g2 ---- m2 ---- rt.2.token "
    )

    assert result == {"imported": 2, "skipped": 1, "total": 2}
    rows = mail_accounts.list_mail_accounts()
    assert [row["email"] for row in rows] == ["aharvey183195@mail.com", "second@mail.com"]
    assert rows[0]["gpt_password"] == "gpt-pass"
    assert rows[0]["mail_password"] == "mail-pass"
    assert rows[0]["refresh_token"] == "rt.1.token"
    assert rows[0]["refresh_token_masked"].startswith("rt.1")
    assert rows[0]["check_status"] == "unchecked"


def test_change_mail_password_updates_selected_accounts(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "mail.sqlite3"))
    mail_accounts.import_mail_accounts(
        "one@mail.com----gpt----old----rt-one\n"
        "two@mail.com----gpt----old----rt-two\n"
    )

    result = mail_accounts.change_mail_passwords(["one@mail.com"], "new-password")

    assert result == {"updated": 1}
    rows = {row["email"]: row for row in mail_accounts.list_mail_accounts()}
    assert rows["one@mail.com"]["mail_password"] == "new-password"
    assert rows["two@mail.com"]["mail_password"] == "old"


def test_update_check_result_records_status_and_rotated_refresh_token(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "mail.sqlite3"))
    mail_accounts.import_mail_accounts("one@mail.com----gpt----mail----old-rt")

    updated = mail_accounts.update_check_result(
        "one@mail.com",
        check_status="valid",
        access_token="access-token",
        refresh_token="new-rt",
        error="",
    )

    assert updated["email"] == "one@mail.com"
    assert updated["check_status"] == "valid"
    assert updated["refresh_token"] == "new-rt"
    assert updated["access_token_present"] is True


def test_delete_and_clear_mail_accounts(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "mail.sqlite3"))
    mail_accounts.import_mail_accounts(
        "one@mail.com----gpt----mail----rt-one\n"
        "two@mail.com----gpt----mail----rt-two\n"
    )

    assert mail_accounts.delete_mail_accounts(["one@mail.com"]) == {"deleted": 1}
    assert [row["email"] for row in mail_accounts.list_mail_accounts()] == ["two@mail.com"]
    assert mail_accounts.clear_mail_accounts() == {"deleted": 1}
    assert mail_accounts.list_mail_accounts() == []


def test_mail_account_validation_rejects_missing_required_values(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "mail.sqlite3"))

    with pytest.raises(ValueError, match="邮箱不能为空"):
        mail_accounts.upsert_mail_account({"email": "", "refresh_token": "rt"})
    with pytest.raises(ValueError, match="refreshToken 不能为空"):
        mail_accounts.upsert_mail_account({"email": "one@mail.com", "refresh_token": ""})
    with pytest.raises(ValueError, match="只支持 @mail.com"):
        mail_accounts.upsert_mail_account({"email": "one@outlook.com", "refresh_token": "rt"})


def test_mailcom_pool_status_derives_account_pool_and_auth_session(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "mail.sqlite3"))
    mail_accounts.import_mail_accounts(
        "ready@mail.com----gpt1----mail1----rt1\n"
        "fresh@mail.com----gpt2----mail2----rt2\n"
        "disabled@mail.com----gpt3----mail3----rt3\n"
    )
    mail_accounts.set_account_statuses(["disabled@mail.com"], "disabled")

    monkeypatch.setattr(
        "autotoken.storage.accounts.load_accounts",
        lambda: [
            {"email": "ready@mail.com", "status": "active", "mail_provider": "mail.com"},
            {"email": "failed@mail.com", "status": "fail", "mail_provider": "mail.com"},
        ],
    )
    monkeypatch.setattr(
        "autotoken.storage.auth_session_store.get_auth_session_file",
        lambda email: f"session/{email}.json" if email == "ready@mail.com" else "",
    )

    status = mail_accounts.mailcom_pool_status()

    assert status["total"] == 3
    assert status["available"] == 1
    assert status["auth_session_ready"] == 1
    assert status["not_logged_in"] == 1
    assert status["disabled"] == 1
    assert status["next_available_email"] == "fresh@mail.com"
    by_email = {item["email"]: item for item in status["items"]}
    assert by_email["ready@mail.com"]["auth_session_status"] == "ready"
    assert by_email["fresh@mail.com"]["account_pool_status"] == "missing"


def test_sync_mail_accounts_to_account_pool_creates_and_updates_managed_accounts(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "mail.sqlite3"))
    mail_accounts.import_mail_accounts("one@mail.com----gpt-pass----mail-pass----rt-one")
    created = []
    updated = []

    monkeypatch.setattr("autotoken.storage.accounts.add_account", lambda *args, **kwargs: created.append((args, kwargs)))
    monkeypatch.setattr(
        "autotoken.storage.accounts.update_account",
        lambda email, **kwargs: updated.append((email, kwargs)) or {"email": email, **kwargs},
    )
    monkeypatch.setattr("autotoken.storage.accounts.load_accounts", lambda: [])

    result = mail_accounts.sync_mail_accounts_to_account_pool()

    assert result["synced"] == 1
    assert result["emails"] == ["one@mail.com"]
    assert created[0][0] == ("one@mail.com", "gpt-pass")
    assert created[0][1]["cloudmail_account_id"] == "one@mail.com"
    assert created[0][1]["mail_provider"] == "mail.com"
    assert updated[0] == (
        "one@mail.com",
        {
            "password": "gpt-pass",
            "cloudmail_account_id": "one@mail.com",
            "mail_provider": "mail.com",
        },
    )


def test_list_available_registration_accounts_skips_registered_disabled_and_missing_password(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "mail.sqlite3"))
    mail_accounts.import_mail_accounts(
        "used@mail.com----gpt----mail----rt\n"
        "fresh@mail.com----gpt----mail----rt\n"
        "nomailpass@mail.com----gpt--------rt\n"
        "disabled@mail.com----gpt----mail----rt\n"
    )
    mail_accounts.set_account_statuses(["disabled@mail.com"], "disabled")
    monkeypatch.setattr("autotoken.storage.accounts.load_accounts", lambda: [{"email": "used@mail.com"}])

    rows = mail_accounts.list_available_registration_accounts()

    assert [row["email"] for row in rows] == ["fresh@mail.com"]


def test_mark_mailcom_registered_updates_gpt_password_and_note(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "mail.sqlite3"))
    mail_accounts.import_mail_accounts("one@mail.com----old-gpt----mail----rt-old")

    updated = mail_accounts.mark_mailcom_registered(
        "one@mail.com",
        gpt_password="new-gpt",
        refresh_token="rt-new",
        source="auth_session_saved",
    )

    assert updated["email"] == "one@mail.com"
    assert updated["gpt_password"] == "new-gpt"
    assert updated["refresh_token"] == "rt-new"
    assert updated["check_status"] == "valid"
    assert "已注册" in updated["note"]
