"""注册失败明细日志（持久化到 SQLite）。

用户要求：失败账号不能污染账号列表，但失败原因必须能追溯 —— 比如 add-phone 触发了几次、
哪些临时邮箱在 OAuth 阶段挂了、哪些被判 duplicate。本模块单独存这类明细，不与 accounts.json 混。

记录只保留最近 N 条（RECORD_LIMIT），避免长期运行后文件膨胀。

并发：`_cmd_fill_personal` 等任务跑在 ThreadPoolExecutor 里，多个 worker 会同时命中
record_failure —— 无锁的读-改-写会互相覆盖导致丢记录。全部写入走 _LOCK 串行化。
"""

import json
import logging
import threading
import time
from pathlib import Path

from autoteam import sqlite_store
from autoteam.paths import PROJECT_ROOT

logger = logging.getLogger(__name__)

FAILURES_FILE = PROJECT_ROOT / "register_failures.json"
FAILURES_FILE_MODE = 0o666
RECORD_LIMIT = 500
_EVENT_KIND = "register_failure"

_LOCK = threading.Lock()


def _db_path() -> Path:
    try:
        if Path(FAILURES_FILE).resolve() != (PROJECT_ROOT / "register_failures.json").resolve():
            return Path(FAILURES_FILE).with_suffix(".sqlite3")
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
    data.setdefault("email", row["email"])
    data.setdefault("category", row["category"])
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
            str(payload.get("email") or ""),
            str(payload.get("category") or ""),
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


def record_failure(email, category, reason, **extra):
    """追加一条失败记录。

    category: 'phone_blocked' / 'duplicate_exhausted' / 'register_failed' / 'oauth_failed'
              / 'kick_failed' / 'team_oauth_failed' / 'exception'
    reason:   面向人的简短描述（会显示在日志和面板）
    extra:    任意附加字段（attempts, duplicate_swaps, step, url ...）
    """
    with _LOCK:
        records = _load()
        records.append(
            {
                "timestamp": time.time(),
                "email": email or "",
                "category": category,
                "reason": reason or "",
                **extra,
            }
        )
        _save(records)


def list_failures(limit=50):
    with _LOCK:
        records = _load()
    return records[-limit:][::-1]


def count_by_category(since_ts=0):
    with _LOCK:
        records = _load()
    counts = {}
    for r in records:
        if r.get("timestamp", 0) < since_ts:
            continue
        cat = r.get("category", "unknown")
        counts[cat] = counts.get(cat, 0) + 1
    return counts
