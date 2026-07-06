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
