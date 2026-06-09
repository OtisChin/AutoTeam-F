from autotoken import auth_storage


def test_ensure_auth_file_permissions_only_touches_auth_dir_files(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    auth_file = auth_dir / "codex-user@example.com.json"
    outside_file = tmp_path / "outside.json"
    auth_dir.mkdir()
    auth_file.write_text("{}", encoding="utf-8")
    outside_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(auth_storage, "AUTH_DIR", auth_dir)

    assert auth_storage.ensure_auth_file_permissions(auth_file) == 1
    assert auth_storage.ensure_auth_file_permissions(outside_file) == 0


def test_ensure_auth_file_permissions_bulk_scans_codex_files_in_auth_dir(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    (auth_dir / "codex-one.json").write_text("{}", encoding="utf-8")
    (auth_dir / "codex-two.json").write_text("{}", encoding="utf-8")
    (auth_dir / "other.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(auth_storage, "AUTH_DIR", auth_dir)

    assert auth_storage.ensure_auth_file_permissions() == 2
