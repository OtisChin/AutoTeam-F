from autoteam import account_ops


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
        "autoteam.cpa_sync.list_cpa_files",
        lambda: [{"email": "user@example.com", "name": auth_file.name}],
    )
    monkeypatch.setattr(
        "autoteam.cpa_sync.delete_from_cpa",
        lambda _name: (_ for _ in ()).throw(AssertionError("CPA files must not be deleted by account deletion")),
    )

    cleanup = account_ops.delete_managed_account("user@example.com", remove_remote=False)

    assert cleanup["local_record"] is True
    assert cleanup["local_auth_files"] == [auth_file.name]
    assert cleanup["cpa_files"] == []
    assert saved["accounts"] == []
