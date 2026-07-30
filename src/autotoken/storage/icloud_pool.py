"""Persistent iCloud account-pool usage/unavailable state."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from autotoken.core.normalization import normalized_email
from autotoken.core.paths import PROJECT_ROOT
from autotoken.storage import sqlite_store

STATE_FILE = PROJECT_ROOT / "data" / "icloud_pool.json"
_NAMESPACE = "icloud_pool"
_KEY_UNAVAILABLE_EMAILS = "unavailable_emails"
_LOCK = threading.Lock()


def _db_path() -> Path:
    try:
        if Path(STATE_FILE).resolve() != (PROJECT_ROOT / "data" / "icloud_pool.json").resolve():
            return Path(STATE_FILE).with_suffix(".sqlite3")
    except Exception:
        pass
    return sqlite_store.default_db_path()


def _load_records() -> dict[str, dict[str, Any]]:
    raw = sqlite_store.get_json(_NAMESPACE, _KEY_UNAVAILABLE_EMAILS, {}, path=_db_path())
    if isinstance(raw, dict):
        records: dict[str, dict[str, Any]] = {}
        for key, value in raw.items():
            email = normalized_email(key)
            if not email:
                continue
            records[email] = dict(value) if isinstance(value, dict) else {"unavailable_at": 0, "source": str(value or "")}
        return records
    if isinstance(raw, list):
        return {
            email: {"unavailable_at": 0, "source": "legacy"}
            for item in raw
            if (email := normalized_email(item))
        }
    return {}


def list_unavailable_emails() -> set[str]:
    with _LOCK:
        return set(_load_records())


def unavailable_email_records() -> dict[str, dict[str, Any]]:
    with _LOCK:
        return _load_records()


def mark_unavailable_email(email: str, *, source: str = "") -> bool:
    normalized = normalized_email(email)
    if not normalized:
        return False
    now = time.time()
    with _LOCK:
        records = _load_records()
        existing = records.get(normalized, {})
        records[normalized] = {
            **existing,
            "unavailable_at": existing.get("unavailable_at") or now,
            "updated_at": now,
            "source": str(source or existing.get("source") or "account_deactivated"),
        }
        sqlite_store.set_json(_NAMESPACE, _KEY_UNAVAILABLE_EMAILS, records, path=_db_path())
    return True
