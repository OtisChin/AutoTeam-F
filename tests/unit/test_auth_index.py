import json

from autotoken.storage import auth_index


def test_sync_existing_codex_auth_files_skips_oversized_auth_json(tmp_path, monkeypatch):
    db_file = tmp_path / "autotoken.sqlite3"
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    valid = auth_dir / "codex-user@example.com-plus.json"
    oversized = auth_dir / "codex-huge@example.com-plus.json"
    valid.write_text(json.dumps({"email": "user@example.com", "plan_type": "plus"}), encoding="utf-8")
    oversized.write_text("x" * (auth_index.AUTH_INDEX_FILE_MAX_BYTES + 1), encoding="utf-8")

    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(db_file))
    monkeypatch.setattr("autotoken.storage.auth_storage.AUTH_DIR", auth_dir)

    assert auth_index.sync_existing_codex_auth_files() == 1
    assert auth_index.codex_auth_files_by_email() == {"user@example.com": str(valid.resolve())}
