"""SQLite persistence helpers for AutoTeam runtime data.

The store uses one local database under ``data/autoteam.sqlite3`` by default.
Modules can pass an explicit path in tests to keep fixtures isolated.
"""

from __future__ import annotations

import os
import json
import sqlite3
import threading
from pathlib import Path

from autoteam.paths import PROJECT_ROOT

DB_FILE = PROJECT_ROOT / "data" / "autoteam.sqlite3"

_LOCK = threading.RLock()


def default_db_path() -> Path:
    override = str(os.environ.get("AUTOTEAM_DB_FILE") or "").strip()
    if override:
        path = Path(override)
        return path if path.is_absolute() else PROJECT_ROOT / path
    return DB_FILE


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    db_path = Path(path) if path else default_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def initialize(path: str | Path | None = None) -> None:
    with _LOCK:
        with connect(path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at REAL NOT NULL DEFAULT (strftime('%s','now'))
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    email TEXT PRIMARY KEY COLLATE NOCASE,
                    status TEXT NOT NULL DEFAULT 'pending',
                    account_type TEXT NOT NULL DEFAULT 'free',
                    seat_type TEXT NOT NULL DEFAULT 'unknown',
                    password TEXT NOT NULL DEFAULT '',
                    cloudmail_account_id TEXT,
                    mail_provider TEXT,
                    auth_file TEXT,
                    credentials_exported INTEGER NOT NULL DEFAULT 0,
                    created_at REAL,
                    updated_at REAL NOT NULL DEFAULT (strftime('%s','now')),
                    data TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_accounts_status ON accounts(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_accounts_account_type ON accounts(account_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_accounts_updated_at ON accounts(updated_at)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS kv_store (
                    namespace TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_at REAL NOT NULL DEFAULT (strftime('%s','now')),
                    PRIMARY KEY (namespace, key)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS card_pool_items (
                    id TEXT PRIMARY KEY,
                    pool_type TEXT NOT NULL,
                    value TEXT NOT NULL,
                    provider TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'unused',
                    created_at REAL,
                    expires_at TEXT NOT NULL DEFAULT '',
                    used_by TEXT NOT NULL DEFAULT '',
                    used_at REAL,
                    meta TEXT NOT NULL DEFAULT '{}',
                    updated_at REAL NOT NULL DEFAULT (strftime('%s','now'))
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_card_pool_items_type ON card_pool_items(pool_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_card_pool_items_status ON card_pool_items(status)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS event_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    email TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT '',
                    task_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '',
                    data TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_event_records_kind_id ON event_records(kind, id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_event_records_kind_timestamp ON event_records(kind, timestamp)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    email TEXT PRIMARY KEY COLLATE NOCASE,
                    file_path TEXT NOT NULL DEFAULT '',
                    data TEXT NOT NULL DEFAULT '{}',
                    updated_at REAL NOT NULL DEFAULT (strftime('%s','now'))
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_auth_sessions_updated_at ON auth_sessions(updated_at)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS codex_auth_files (
                    file_path TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    email TEXT NOT NULL DEFAULT '',
                    account_id TEXT NOT NULL DEFAULT '',
                    plan_type TEXT NOT NULL DEFAULT 'unknown',
                    is_main INTEGER NOT NULL DEFAULT 0,
                    data TEXT NOT NULL DEFAULT '{}',
                    updated_at REAL NOT NULL DEFAULT (strftime('%s','now'))
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_codex_auth_email ON codex_auth_files(email)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_codex_auth_account_id ON codex_auth_files(account_id)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS task_snapshots (
                    task_id TEXT PRIMARY KEY,
                    command TEXT NOT NULL DEFAULT '',
                    task_group TEXT NOT NULL DEFAULT 'default',
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at REAL NOT NULL,
                    started_at REAL,
                    finished_at REAL,
                    owner_pid INTEGER,
                    data TEXT NOT NULL DEFAULT '{}',
                    updated_at REAL NOT NULL DEFAULT (strftime('%s','now'))
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_task_snapshots_created_at ON task_snapshots(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_task_snapshots_status ON task_snapshots(status)")


def get_json(namespace: str, key: str, default=None, path: str | Path | None = None):
    initialize(path)
    with _LOCK:
        with connect(path) as conn:
            row = conn.execute(
                "SELECT value FROM kv_store WHERE namespace = ? AND key = ?",
                (str(namespace), str(key)),
            ).fetchone()
            if not row:
                return default
            try:
                return json.loads(row["value"])
            except Exception:
                return default


def set_json(namespace: str, key: str, value, path: str | Path | None = None):
    initialize(path)
    with _LOCK:
        with connect(path) as conn:
            conn.execute(
                """
                INSERT INTO kv_store(namespace, key, value, updated_at)
                VALUES (?, ?, ?, strftime('%s','now'))
                ON CONFLICT(namespace, key) DO UPDATE SET
                    value=excluded.value,
                    updated_at=excluded.updated_at
                """,
                (str(namespace), str(key), json.dumps(value, ensure_ascii=False)),
            )
    return value


def delete_key(namespace: str, key: str, path: str | Path | None = None) -> None:
    initialize(path)
    with _LOCK:
        with connect(path) as conn:
            conn.execute(
                "DELETE FROM kv_store WHERE namespace = ? AND key = ?",
                (str(namespace), str(key)),
            )
