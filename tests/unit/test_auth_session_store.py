import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest

from autotoken import api_routes
from autotoken.storage import auth_session_store, sqlite_store

SQLITE_VARIABLE_LIMIT_REGRESSION_SIZE = 32_767


def _insert_auth_session_rows(db_file, rows):
    sqlite_store.initialize(db_file)
    conn = sqlite_store.connect(db_file)
    try:
        conn.executemany(
            "INSERT INTO auth_sessions(email, file_path, data, updated_at) VALUES (?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def _isolate_auth_session_store(tmp_path, monkeypatch):
    session_dir = tmp_path / "auth_session"
    db_file = tmp_path / "auth_session.sqlite3"
    monkeypatch.setattr(auth_session_store, "AUTH_SESSION_DIR", session_dir)
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(db_file))
    return session_dir, db_file


def test_colliding_legacy_email_names_use_distinct_session_files(tmp_path, monkeypatch):
    _isolate_auth_session_store(tmp_path, monkeypatch)

    dotted_path = auth_session_store.save_auth_session("a.b@example.com", {"token": "dotted"})
    underscored_path = auth_session_store.save_auth_session("a_b@example.com", {"token": "underscored"})

    assert dotted_path != underscored_path
    assert json.loads(Path(dotted_path).read_text(encoding="utf-8")) == {"token": "dotted"}
    assert json.loads(Path(underscored_path).read_text(encoding="utf-8")) == {"token": "underscored"}
    assert auth_session_store.load_auth_session("a.b@example.com") == {"token": "dotted"}
    assert auth_session_store.load_auth_session("a_b@example.com") == {"token": "underscored"}


def test_get_auth_session_file_migrates_legacy_database_path_without_deleting_shared_file(tmp_path, monkeypatch):
    session_dir, db_file = _isolate_auth_session_store(tmp_path, monkeypatch)
    session_dir.mkdir(parents=True)
    legacy_path = session_dir / "a_b@example_com.json"
    legacy_path.write_text('{"token":"legacy-shared"}', encoding="utf-8")
    _insert_auth_session_rows(
        db_file,
        [("a.b@example.com", str(legacy_path), '{"token":"from-database"}', 1)],
    )

    migrated_path = auth_session_store.get_auth_session_file("a.b@example.com")

    assert migrated_path != str(legacy_path)
    assert json.loads(Path(migrated_path).read_text(encoding="utf-8")) == {"token": "from-database"}
    assert legacy_path.exists()
    with sqlite_store.connect(db_file) as conn:
        row = conn.execute(
            "SELECT file_path FROM auth_sessions WHERE email = ?",
            ("a.b@example.com",),
        ).fetchone()
    assert row["file_path"] == migrated_path


def test_empty_sqlite_session_never_falls_back_to_stale_legacy_file(tmp_path, monkeypatch):
    session_dir, db_file = _isolate_auth_session_store(tmp_path, monkeypatch)
    session_dir.mkdir(parents=True)
    legacy_path = auth_session_store._legacy_target_path("empty@example.com")
    legacy_path.write_text(
        json.dumps({"email": "empty@example.com", "token": "stale-filesystem"}),
        encoding="utf-8",
    )
    _insert_auth_session_rows(
        db_file,
        [("empty@example.com", str(legacy_path), "{}", 1)],
    )

    resolved = Path(auth_session_store.get_auth_session_file("empty@example.com"))

    assert resolved == auth_session_store._target_path("empty@example.com")
    assert json.loads(resolved.read_text(encoding="utf-8")) == {}
    assert legacy_path.exists()


def test_legacy_collision_is_only_read_for_the_embedded_email_owner(tmp_path, monkeypatch):
    session_dir, _db_file = _isolate_auth_session_store(tmp_path, monkeypatch)
    session_dir.mkdir(parents=True)
    shared_path = auth_session_store._legacy_target_path("a.b@example.com")
    assert shared_path == auth_session_store._legacy_target_path("a_b@example.com")
    shared_path.write_text(
        json.dumps({"email": "a_b@example.com", "token": "underscored"}),
        encoding="utf-8",
    )

    assert auth_session_store.get_auth_session_file("a.b@example.com") == ""
    assert auth_session_store.get_auth_session_file("a_b@example.com") == str(shared_path)


def test_delete_legacy_file_only_session_checks_embedded_email_ownership(tmp_path, monkeypatch):
    session_dir, _db_file = _isolate_auth_session_store(tmp_path, monkeypatch)
    session_dir.mkdir(parents=True)
    owned_path = auth_session_store._legacy_target_path("owned@example.com")
    owned_path.write_text(
        json.dumps({"email": "owned@example.com", "token": "owned"}),
        encoding="utf-8",
    )
    shared_path = auth_session_store._legacy_target_path("a.b@example.com")
    shared_path.write_text(
        json.dumps({"email": "a_b@example.com", "token": "other-owner"}),
        encoding="utf-8",
    )

    assert auth_session_store.delete_auth_session("owned@example.com") is True
    assert not owned_path.exists()
    assert auth_session_store.delete_auth_session("a.b@example.com") is False
    assert shared_path.exists()


def test_delete_removes_unowned_legacy_file_when_database_reference_is_unique(tmp_path, monkeypatch):
    session_dir, db_file = _isolate_auth_session_store(tmp_path, monkeypatch)
    session_dir.mkdir(parents=True)
    legacy_path = auth_session_store._legacy_target_path("legacy@example.com")
    legacy_path.write_text(json.dumps({"token": "legacy-secret"}), encoding="utf-8")
    _insert_auth_session_rows(
        db_file,
        [("legacy@example.com", str(legacy_path), '{"token":"sqlite-secret"}', 1)],
    )

    assert auth_session_store.delete_auth_session("legacy@example.com") is True
    assert not legacy_path.exists()
    assert auth_session_store.get_auth_session_record("legacy@example.com") is None


def test_delete_preserves_unowned_legacy_file_until_its_last_database_reference(tmp_path, monkeypatch):
    session_dir, db_file = _isolate_auth_session_store(tmp_path, monkeypatch)
    session_dir.mkdir(parents=True)
    shared_path = auth_session_store._legacy_target_path("a.b@example.com")
    assert shared_path == auth_session_store._legacy_target_path("a_b@example.com")
    shared_path.write_text(json.dumps({"token": "legacy-shared"}), encoding="utf-8")
    _insert_auth_session_rows(
        db_file,
        [
            ("a.b@example.com", str(shared_path), '{"token":"dotted"}', 1),
            ("a_b@example.com", str(shared_path), '{"token":"underscored"}', 2),
        ],
    )

    assert auth_session_store.delete_auth_session("a.b@example.com") is True
    assert shared_path.exists()
    assert auth_session_store.delete_auth_session("a_b@example.com") is True
    assert not shared_path.exists()


def test_delete_preserves_unowned_legacy_file_across_equivalent_path_spellings(tmp_path, monkeypatch):
    session_dir, db_file = _isolate_auth_session_store(tmp_path, monkeypatch)
    session_dir.mkdir(parents=True)
    shared_path = auth_session_store._legacy_target_path("a.b@example.com")
    assert shared_path == auth_session_store._legacy_target_path("a_b@example.com")
    shared_path.write_text(json.dumps({"token": "legacy-shared"}), encoding="utf-8")
    native_path = str(shared_path)
    alternate_path = native_path.replace("\\", "/")
    assert native_path != alternate_path
    _insert_auth_session_rows(
        db_file,
        [
            ("a.b@example.com", native_path, '{"token":"dotted"}', 1),
            ("a_b@example.com", alternate_path, '{"token":"underscored"}', 2),
        ],
    )

    assert auth_session_store.delete_auth_session("a.b@example.com") is True
    assert shared_path.exists()
    assert auth_session_store.delete_auth_session("a_b@example.com") is True
    assert not shared_path.exists()


def test_delete_preserves_unowned_legacy_file_across_dotdot_path_alias(tmp_path, monkeypatch):
    session_dir, db_file = _isolate_auth_session_store(tmp_path, monkeypatch)
    session_dir.mkdir(parents=True)
    alias_dir = session_dir / "alias"
    alias_dir.mkdir()
    shared_path = auth_session_store._legacy_target_path("a.b@example.com")
    shared_path.write_text(json.dumps({"token": "legacy-shared"}), encoding="utf-8")
    alias_path = alias_dir / ".." / shared_path.name
    assert str(alias_path) != str(shared_path)
    assert alias_path.resolve() == shared_path.resolve()
    _insert_auth_session_rows(
        db_file,
        [
            ("a.b@example.com", str(shared_path), '{"token":"dotted"}', 1),
            ("a_b@example.com", str(alias_path), '{"token":"underscored"}', 2),
        ],
    )

    assert auth_session_store.delete_auth_session("a.b@example.com") is True
    assert shared_path.exists()
    assert auth_session_store.delete_auth_session("a_b@example.com") is True
    assert not shared_path.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ignores trailing dots in path components")
def test_delete_preserves_unowned_legacy_file_across_trailing_dot_alias(tmp_path, monkeypatch):
    session_dir, db_file = _isolate_auth_session_store(tmp_path, monkeypatch)
    session_dir.mkdir(parents=True)
    shared_path = auth_session_store._legacy_target_path("a.b@example.com")
    shared_path.write_text(json.dumps({"token": "legacy-shared"}), encoding="utf-8")
    alias_path = Path(f"{shared_path}.")
    assert alias_path.exists()
    assert alias_path.resolve() == shared_path.resolve()
    _insert_auth_session_rows(
        db_file,
        [
            ("a.b@example.com", str(shared_path), '{"token":"dotted"}', 1),
            ("a_b@example.com", str(alias_path), '{"token":"underscored"}', 2),
        ],
    )

    assert auth_session_store.delete_auth_session("a.b@example.com") is True
    assert shared_path.exists()
    assert auth_session_store.delete_auth_session("a_b@example.com") is True
    assert not shared_path.exists()


def test_delete_preserves_legacy_file_owned_by_other_email_when_database_reference_is_unique(
    tmp_path,
    monkeypatch,
):
    session_dir, db_file = _isolate_auth_session_store(tmp_path, monkeypatch)
    session_dir.mkdir(parents=True)
    dotted_email = "a.b@example.com"
    underscored_email = "a_b@example.com"
    shared_path = auth_session_store._legacy_target_path(dotted_email)
    assert shared_path == auth_session_store._legacy_target_path(underscored_email)
    shared_path.write_text(
        json.dumps({"email": dotted_email, "token": "dotted-secret"}),
        encoding="utf-8",
    )
    _insert_auth_session_rows(
        db_file,
        [(underscored_email, str(shared_path), '{"token":"underscored"}', 1)],
    )

    assert auth_session_store.delete_auth_session(underscored_email) is True
    assert shared_path.exists()
    assert auth_session_store.get_auth_session_file(dotted_email) == str(shared_path)


def test_delete_rolls_back_sqlite_when_canonical_unlink_fails(tmp_path, monkeypatch):
    _session_dir, _db_file = _isolate_auth_session_store(tmp_path, monkeypatch)
    email = "unlink-failure@example.com"
    payload = {"email": email, "token": "still-authoritative"}
    canonical_path = Path(auth_session_store.save_auth_session(email, payload))
    real_unlink = Path.unlink

    def fail_canonical_unlink(path, *args, **kwargs):
        if path == canonical_path:
            raise PermissionError("injected canonical unlink failure")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_canonical_unlink)

    with pytest.raises(PermissionError, match="injected canonical unlink failure"):
        auth_session_store.delete_auth_session(email)

    assert auth_session_store.load_auth_session(email) == payload
    assert auth_session_store.get_auth_session_file(email) == str(canonical_path)


def test_orphaned_canonical_file_cannot_revive_deleted_session(tmp_path, monkeypatch):
    _session_dir, db_file = _isolate_auth_session_store(tmp_path, monkeypatch)
    email = "orphan@example.com"
    canonical_path = Path(
        auth_session_store.save_auth_session(email, {"email": email, "token": "orphan-secret"})
    )
    with sqlite_store.connect(db_file) as conn:
        conn.execute("DELETE FROM auth_sessions WHERE email = ?", (email,))

    assert canonical_path.exists()
    assert auth_session_store.get_auth_session_file(email) == ""


def test_auth_sessions_file_path_index_is_initialized(tmp_path):
    db_file = tmp_path / "autotoken.sqlite3"
    sqlite_store.initialize(db_file)

    with sqlite_store.connect(db_file) as conn:
        index_names = {
            str(row["name"] or "")
            for row in conn.execute("PRAGMA index_list(auth_sessions)").fetchall()
        }

    assert "idx_auth_sessions_file_path" in index_names


def test_bulk_file_index_returns_distinct_canonical_paths_for_legacy_collisions(tmp_path, monkeypatch):
    _session_dir, db_file = _isolate_auth_session_store(tmp_path, monkeypatch)
    shared_path = str(auth_session_store._legacy_target_path("a.b@example.com"))
    _insert_auth_session_rows(
        db_file,
        [
            ("a.b@example.com", shared_path, '{"token":"dotted"}', 1),
            ("a_b@example.com", shared_path, '{"token":"underscored"}', 2),
        ],
    )

    indexed = auth_session_store.auth_session_files_by_email(
        ["a.b@example.com", "a_b@example.com"]
    )

    assert indexed == {
        "a.b@example.com": str(auth_session_store._target_path("a.b@example.com")),
        "a_b@example.com": str(auth_session_store._target_path("a_b@example.com")),
    }
    assert indexed["a.b@example.com"] != indexed["a_b@example.com"]


def test_concurrent_saves_keep_sqlite_and_materialized_file_on_the_same_version(tmp_path, monkeypatch):
    _isolate_auth_session_store(tmp_path, monkeypatch)
    first_materialize_started = threading.Event()
    second_materialized = threading.Event()
    real_materialize = auth_session_store._materialize_file

    def ordered_materialize(email, session_data):
        token = session_data.get("token")
        if token == "first":
            first_materialize_started.set()
            second_materialized.wait(timeout=0.25)
            return real_materialize(email, session_data)
        result = real_materialize(email, session_data)
        second_materialized.set()
        return result

    monkeypatch.setattr(auth_session_store, "_materialize_file", ordered_materialize)
    first = threading.Thread(
        target=auth_session_store.save_auth_session,
        args=("race@example.com", {"token": "first"}),
    )
    second = threading.Thread(
        target=auth_session_store.save_auth_session,
        args=("race@example.com", {"token": "second"}),
    )

    first.start()
    assert first_materialize_started.wait(2)
    second.start()
    first.join(3)
    second.join(3)

    assert not first.is_alive() and not second.is_alive()
    assert auth_session_store.load_auth_session("race@example.com") == {"token": "second"}
    assert json.loads(
        auth_session_store._target_path("race@example.com").read_text(encoding="utf-8")
    ) == {"token": "second"}


def test_concurrent_session_file_reads_do_not_cross_account_tokens(tmp_path, monkeypatch):
    _isolate_auth_session_store(tmp_path, monkeypatch)
    expected = {
        "a.b@example.com": "dotted",
        "a_b@example.com": "underscored",
    }
    for email, token in expected.items():
        auth_session_store.save_auth_session(email, {"token": token})
    ready = Barrier(len(expected))

    def read_after_both_files_are_materialized(email):
        path = auth_session_store.get_auth_session_file(email)
        ready.wait(timeout=5)
        return json.loads(Path(path).read_text(encoding="utf-8"))["token"]

    with ThreadPoolExecutor(max_workers=2) as executor:
        observed = dict(zip(expected, executor.map(read_after_both_files_are_materialized, expected), strict=True))

    assert observed == expected


def test_materialize_session_file_writes_a_temporary_file_before_atomic_replace(tmp_path, monkeypatch):
    _isolate_auth_session_store(tmp_path, monkeypatch)
    writes = []
    real_write_text = auth_session_store.write_text

    def record_write(path, content):
        writes.append(Path(path))
        real_write_text(path, content)

    monkeypatch.setattr(auth_session_store, "write_text", record_write)

    materialized_path = Path(auth_session_store._materialize_file("atomic@example.com", {"token": "atomic"}))

    assert writes and writes[0] != materialized_path
    assert json.loads(materialized_path.read_text(encoding="utf-8")) == {"token": "atomic"}
    assert list(materialized_path.parent.glob(f".{materialized_path.name}.*.tmp")) == []


def test_payment_cache_invalidation_does_not_import_an_unloaded_route(monkeypatch):
    module_name = "autotoken.api_routes.brazil_pix"
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    monkeypatch.delattr(api_routes, "brazil_pix", raising=False)

    auth_session_store._invalidate_payment_account_caches()

    assert module_name not in sys.modules


def test_payment_cache_invalidation_clears_an_already_loaded_route(monkeypatch):
    calls = []
    module_name = "autotoken.api_routes.brazil_pix"
    fake_module = SimpleNamespace(clear_auth_accounts_cache=lambda: calls.append("clear"))
    monkeypatch.setitem(sys.modules, module_name, fake_module)

    auth_session_store._invalidate_payment_account_caches()

    assert calls == ["clear"]


def test_auth_session_files_by_email_chunks_more_than_sqlite_variable_limit(tmp_path, monkeypatch):
    db_file = tmp_path / "autotoken.sqlite3"
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(db_file))
    _insert_auth_session_rows(
        db_file,
        [("target@example.com", "target-session.json", "{}", 1)],
    )
    emails = ["target@example.com", "TARGET@example.com", "target@example.com"]
    emails.extend(f"missing-{index}@example.com" for index in range(SQLITE_VARIABLE_LIMIT_REGRESSION_SIZE))

    assert auth_session_store.auth_session_files_by_email(emails) == {
        "target@example.com": str(auth_session_store._target_path("target@example.com"))
    }


def test_auth_session_files_by_email_with_empty_filter_returns_all_rows(tmp_path, monkeypatch):
    db_file = tmp_path / "autotoken.sqlite3"
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(db_file))
    _insert_auth_session_rows(
        db_file,
        [
            ("a@example.com", "a-session.json", "{}", 1),
            ("b@example.com", "b-session.json", "{}", 2),
        ],
    )

    assert auth_session_store.auth_session_files_by_email([]) == {
        "a@example.com": str(auth_session_store._target_path("a@example.com")),
        "b@example.com": str(auth_session_store._target_path("b@example.com")),
    }
