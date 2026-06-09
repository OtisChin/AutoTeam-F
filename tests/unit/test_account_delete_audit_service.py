import json
import logging
import threading

from autotoken.services import account_delete_audit


class FakeConnection:
    def __init__(self, store):
        self.store = store

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params):
        self.store.executed.append((sql, params))


class FakeSqliteStore:
    def __init__(self):
        self.initialized = []
        self.executed = []
        self.markers = {}

    def initialize(self, path=None):
        self.initialized.append(path)

    def connect(self, path=None):
        self.connected_path = path
        return FakeConnection(self)

    def get_json(self, namespace, key, default=None):
        return self.markers.get((namespace, key), default)

    def set_json(self, namespace, key, value):
        self.markers[(namespace, key)] = value


def test_build_delete_audit_payload_preserves_account_context():
    payload = account_delete_audit.build_delete_audit_payload(
        email=" User@Example.COM ",
        log_context="gopay-bind",
        reason="token_invalidated",
        message="removed",
        account={
            "status": "active",
            "account_type": "plus",
            "seat_type": "codex",
            "mail_provider": "luckmail",
            "cloudmail_account_id": "cloud-1",
            "auth_file": "auth.json",
            "last_bind_task_id": "task-1",
        },
        record_deleted=True,
        auth_session_deleted=False,
        normalize_email=lambda value: value.strip().lower(),
        now=123.0,
    )

    assert payload["ts"] == 123.0
    assert payload["email"] == "user@example.com"
    assert payload["source"] == "gopay-bind"
    assert payload["reason"] == "token_invalidated"
    assert payload["record_deleted"] is True
    assert payload["auth_session_deleted"] is False
    assert payload["cloudmail_account_id_present"] is True
    assert payload["last_bind_task_id"] == "task-1"


def test_audit_db_path_uses_sidecar_sqlite_for_non_default_path(tmp_path):
    project_root = tmp_path / "project"
    default_db = tmp_path / "default.sqlite3"

    assert account_delete_audit.audit_db_path(
        project_root / "data" / "account_delete_audit.jsonl",
        project_root=project_root,
        default_db_path=lambda: default_db,
    ) == default_db
    assert account_delete_audit.audit_db_path(
        tmp_path / "custom.jsonl",
        project_root=project_root,
        default_db_path=lambda: default_db,
    ) == tmp_path / "custom.sqlite3"


def test_append_delete_audit_writes_sqlite_and_jsonl(tmp_path):
    store = FakeSqliteStore()
    audit_path = tmp_path / "audit" / "account_delete_audit.jsonl"
    db_path = tmp_path / "audit.sqlite3"

    account_delete_audit.append_delete_audit(
        path=audit_path,
        db_path=db_path,
        audit_lock=threading.Lock(),
        email="dead@example.com",
        log_context="cleanup",
        reason="oauth_account_deactivated",
        account={"status": "fail", "account_type": "plus", "last_bind_task_id": "task-2"},
        record_deleted=True,
        auth_session_deleted=True,
        normalize_email=lambda value: value,
        sqlite_store=store,
        logger=logging.getLogger("test-account-delete-audit"),
        now=456.0,
    )

    assert store.initialized == [db_path]
    assert store.connected_path == db_path
    assert store.executed[0][1][0] == "account_delete_audit"
    assert store.executed[0][1][1] == 456.0
    assert store.executed[0][1][4] == "task-2"
    rows = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["email"] == "dead@example.com"
    assert rows[0]["record_deleted"] is True
    assert rows[0]["auth_session_deleted"] is True


def test_migrate_delete_audit_jsonl_imports_valid_rows_and_marks_done(tmp_path):
    store = FakeSqliteStore()
    audit_path = tmp_path / "account_delete_audit.jsonl"
    audit_path.write_text(
        "\n".join(
            [
                json.dumps({"ts": 10, "email": "a@example.com", "reason": "old", "status": "fail"}),
                "not-json",
                json.dumps({"timestamp": 20, "email": "b@example.com", "last_bind_task_id": "task-b"}),
            ]
        ),
        encoding="utf-8",
    )

    count = account_delete_audit.migrate_delete_audit_jsonl(
        path=audit_path,
        sqlite_store=store,
        logger=logging.getLogger("test-account-delete-audit"),
    )

    assert count == 2
    assert len(store.executed) == 2
    assert store.executed[0][1][1] == 10.0
    assert store.executed[1][1][1] == 20.0
    assert store.markers[("migrations", "account_delete_audit_jsonl")] == {"done": True, "count": 2}


def test_migrate_delete_audit_jsonl_streams_without_read_text(tmp_path, monkeypatch):
    store = FakeSqliteStore()
    audit_path = tmp_path / "account_delete_audit.jsonl"
    audit_path.write_text(json.dumps({"ts": 10, "email": "a@example.com"}) + "\n", encoding="utf-8")

    def fail_read_text(*_args, **_kwargs):
        raise AssertionError("migration should stream JSONL instead of reading the full file")

    monkeypatch.setattr(account_delete_audit.Path, "read_text", fail_read_text)

    count = account_delete_audit.migrate_delete_audit_jsonl(
        path=audit_path,
        sqlite_store=store,
        logger=logging.getLogger("test-account-delete-audit"),
    )

    assert count == 1
    assert len(store.executed) == 1


def test_migrate_delete_audit_jsonl_skips_when_marker_done(tmp_path):
    store = FakeSqliteStore()
    store.markers[("migrations", "account_delete_audit_jsonl")] = {"done": True, "count": 3}
    audit_path = tmp_path / "account_delete_audit.jsonl"
    audit_path.write_text(json.dumps({"email": "a@example.com"}), encoding="utf-8")

    assert account_delete_audit.migrate_delete_audit_jsonl(
        path=audit_path,
        sqlite_store=store,
        logger=logging.getLogger("test-account-delete-audit"),
    ) == 0
    assert store.executed == []
