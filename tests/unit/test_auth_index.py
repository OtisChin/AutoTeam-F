import json

from autotoken.storage import auth_index, sqlite_store

SQLITE_VARIABLE_LIMIT_REGRESSION_SIZE = 32_767


def _insert_auth_index_rows(db_file, rows):
    sqlite_store.initialize(db_file)
    conn = sqlite_store.connect(db_file)
    try:
        conn.executemany(
            """
            INSERT INTO codex_auth_files(
                file_path, filename, email, account_id, plan_type, is_main, data, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()


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


def test_codex_auth_files_by_email_chunks_more_than_sqlite_variable_limit_and_keeps_latest(tmp_path, monkeypatch):
    db_file = tmp_path / "autotoken.sqlite3"
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(db_file))
    _insert_auth_index_rows(
        db_file,
        [
            ("old.json", "old.json", "target@example.com", "old", "free", 0, "{}", 1),
            ("latest.json", "latest.json", "target@example.com", "latest", "plus", 0, "{}", 2),
        ],
    )
    emails = ["target@example.com", "TARGET@example.com", "target@example.com"]
    emails.extend(f"missing-{index}@example.com" for index in range(SQLITE_VARIABLE_LIMIT_REGRESSION_SIZE))

    assert auth_index.codex_auth_files_by_email(emails) == {"target@example.com": "latest.json"}


def test_codex_auth_metadata_by_email_chunks_more_than_sqlite_variable_limit_and_keeps_latest(tmp_path, monkeypatch):
    db_file = tmp_path / "autotoken.sqlite3"
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(db_file))
    _insert_auth_index_rows(
        db_file,
        [
            ("old.json", "old.json", "target@example.com", "old", "free", 0, "{}", 1),
            (
                "latest.json",
                "latest.json",
                "target@example.com",
                "latest",
                "plus",
                0,
                json.dumps({"id_token_synthetic": True}),
                2,
            ),
        ],
    )
    emails = ["target@example.com", "TARGET@example.com", "target@example.com"]
    emails.extend(f"missing-{index}@example.com" for index in range(SQLITE_VARIABLE_LIMIT_REGRESSION_SIZE))

    assert auth_index.codex_auth_metadata_by_email(emails) == {
        "target@example.com": {"file_path": "latest.json", "synthetic": True}
    }


def test_codex_auth_bulk_queries_with_empty_filter_return_all_latest_rows(tmp_path, monkeypatch):
    db_file = tmp_path / "autotoken.sqlite3"
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(db_file))
    _insert_auth_index_rows(
        db_file,
        [
            ("a-old.json", "a-old.json", "a@example.com", "a-old", "free", 0, "{}", 1),
            (
                "a-latest.json",
                "a-latest.json",
                "a@example.com",
                "a-latest",
                "plus",
                0,
                json.dumps({"idToken": "header.synthetic.signature"}),
                2,
            ),
            ("b.json", "b.json", "b@example.com", "b", "free", 0, "{}", 3),
        ],
    )

    assert auth_index.codex_auth_files_by_email([]) == {
        "a@example.com": "a-latest.json",
        "b@example.com": "b.json",
    }
    assert auth_index.codex_auth_metadata_by_email([]) == {
        "a@example.com": {"file_path": "a-latest.json", "synthetic": True},
        "b@example.com": {"file_path": "b.json", "synthetic": False},
    }
