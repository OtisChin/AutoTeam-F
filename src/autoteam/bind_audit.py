"""绑卡任务审计日志（持久化到 SQLite）。"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

from autoteam import sqlite_store
from autoteam.paths import PROJECT_ROOT

logger = logging.getLogger(__name__)

BIND_AUDIT_FILE = PROJECT_ROOT / "bind_audit.json"
BIND_AUDIT_FILE_MODE = 0o666
RECORD_LIMIT = 500
_EVENT_KIND = "bind_audit"

_LOCK = threading.Lock()


def _db_path() -> Path:
    try:
        if Path(BIND_AUDIT_FILE).resolve() != (PROJECT_ROOT / "bind_audit.json").resolve():
            return Path(BIND_AUDIT_FILE).with_suffix(".sqlite3")
    except Exception:
        pass
    return sqlite_store.default_db_path()


def _row_to_record(row):
    try:
        data = json.loads(row["data"] or "{}")
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("timestamp", row["timestamp"])
    return data


def _insert_record(conn, record):
    payload = dict(record or {})
    conn.execute(
        """
        INSERT INTO event_records(kind, timestamp, email, category, task_id, status, data)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _EVENT_KIND,
            float(payload.get("timestamp") or time.time()),
            str(payload.get("email") or payload.get("account_email") or ""),
            str(payload.get("category") or payload.get("flow") or ""),
            str(payload.get("task_id") or ""),
            str(payload.get("status") or ""),
            json.dumps(payload, ensure_ascii=False),
        ),
    )


def _load():
    sqlite_store.initialize(_db_path())
    with sqlite_store.connect(_db_path()) as conn:
        rows = conn.execute(
            "SELECT * FROM event_records WHERE kind = ? ORDER BY id ASC",
            (_EVENT_KIND,),
        ).fetchall()
    return [_row_to_record(row) for row in rows]


def _save(records):
    records = records[-RECORD_LIMIT:]
    sqlite_store.initialize(_db_path())
    with sqlite_store.connect(_db_path()) as conn:
        conn.execute("DELETE FROM event_records WHERE kind = ?", (_EVENT_KIND,))
        for record in records:
            _insert_record(conn, record)


def record_bind_audit(entry: dict):
    payload = dict(entry or {})
    payload.setdefault("timestamp", time.time())
    with _LOCK:
        records = _load()
        records.append(payload)
        _save(records)
    return payload


def list_bind_audits(limit: int = 50):
    with _LOCK:
        records = _load()
    return records[-limit:][::-1]
