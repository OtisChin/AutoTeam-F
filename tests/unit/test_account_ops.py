from autotoken import account_ops


def test_delete_managed_account_does_not_delete_cpa_files(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    auth_file = auth_dir / "codex-user@example.com-plus-deadbeef.json"
    auth_file.write_text("{}", encoding="utf-8")
    saved = {}

    monkeypatch.setattr(account_ops, "AUTH_DIR", auth_dir)
    monkeypatch.setattr(account_ops, "get_chatgpt_account_id", lambda: "account-123")
    monkeypatch.setattr(
        account_ops,
        "load_accounts",
        lambda: [{"email": "user@example.com", "auth_file": str(auth_file)}],
    )
    monkeypatch.setattr(account_ops, "save_accounts", lambda accounts: saved.setdefault("accounts", accounts))
    monkeypatch.setattr(
        "autotoken.cpa_sync.list_cpa_files",
        lambda: [{"email": "user@example.com", "name": auth_file.name}],
    )
    monkeypatch.setattr(
        "autotoken.cpa_sync.delete_from_cpa",
        lambda _name: (_ for _ in ()).throw(AssertionError("CPA files must not be deleted by account deletion")),
    )

    cleanup = account_ops.delete_managed_account("user@example.com", remove_remote=False)

    assert cleanup["local_record"] is True
    assert cleanup["local_auth_files"] == [auth_file.name]
    assert cleanup["cpa_files"] == []
    assert saved["accounts"] == []


def test_delete_managed_account_only_deletes_auth_files_inside_auth_dir(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    outside_file = tmp_path / "outside.json"
    matching_auth_file = auth_dir / "codex-user@example.com-plus-deadbeef.json"
    bracket_auth_file = auth_dir / "codex-userx@example.com-plus-deadbeef.json"
    outside_file.write_text("{}", encoding="utf-8")
    matching_auth_file.write_text("{}", encoding="utf-8")
    bracket_auth_file.write_text("{}", encoding="utf-8")
    saved = {}

    monkeypatch.setattr(account_ops, "AUTH_DIR", auth_dir)
    monkeypatch.setattr(account_ops, "get_chatgpt_account_id", lambda: "account-123")
    monkeypatch.setattr(
        account_ops,
        "load_accounts",
        lambda: [{"email": "user@example.com", "auth_file": str(outside_file)}],
    )
    monkeypatch.setattr(account_ops, "save_accounts", lambda accounts: saved.setdefault("accounts", accounts))

    cleanup = account_ops.delete_managed_account("user@example.com", remove_remote=False)

    assert cleanup["local_record"] is True
    assert cleanup["local_auth_files"] == [matching_auth_file.name]
    assert matching_auth_file.exists() is False
    assert outside_file.exists() is True
    assert bracket_auth_file.exists() is True
    assert saved["accounts"] == []


def test_delete_managed_account_treats_email_glob_characters_literally(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    literal_auth_file = auth_dir / "codex-user[abc]@example.com-plus-deadbeef.json"
    glob_like_match = auth_dir / "codex-usera@example.com-plus-deadbeef.json"
    literal_auth_file.write_text("{}", encoding="utf-8")
    glob_like_match.write_text("{}", encoding="utf-8")
    saved = {}

    monkeypatch.setattr(account_ops, "AUTH_DIR", auth_dir)
    monkeypatch.setattr(account_ops, "get_chatgpt_account_id", lambda: "account-123")
    monkeypatch.setattr(
        account_ops,
        "load_accounts",
        lambda: [{"email": "user[abc]@example.com", "auth_file": ""}],
    )
    monkeypatch.setattr(account_ops, "save_accounts", lambda accounts: saved.setdefault("accounts", accounts))

    cleanup = account_ops.delete_managed_account("user[abc]@example.com", remove_remote=False)

    assert cleanup["local_record"] is True
    assert cleanup["local_auth_files"] == [literal_auth_file.name]
    assert literal_auth_file.exists() is False
    assert glob_like_match.exists() is True
    assert saved["accounts"] == []
