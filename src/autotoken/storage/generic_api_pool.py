"""Persistent generic-api account-pool usage state."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from autotoken.core.normalization import normalized_email
from autotoken.core.paths import PROJECT_ROOT
from autotoken.storage import sqlite_store

STATE_FILE = PROJECT_ROOT / "data" / "generic_api_pool.json"
_NAMESPACE = "generic_api_pool"
_KEY_REGISTERED_EMAILS = "registered_emails"
_KEY_UNAVAILABLE_EMAILS = "unavailable_emails"
_MAIL_CACHE_PREFIX = "mail_cache:"
_LOCK = threading.Lock()


def _db_path() -> Path:
    try:
        if Path(STATE_FILE).resolve() != (PROJECT_ROOT / "data" / "generic_api_pool.json").resolve():
            return Path(STATE_FILE).with_suffix(".sqlite3")
    except Exception:
        pass
    return sqlite_store.default_db_path()


def _load_records(key: str, default_time_field: str, default_source: str) -> dict[str, dict[str, Any]]:
    raw = sqlite_store.get_json(_NAMESPACE, key, {}, path=_db_path())
    if isinstance(raw, dict):
        records: dict[str, dict[str, Any]] = {}
        for item_key, value in raw.items():
            email = normalized_email(item_key)
            if not email:
                continue
            records[email] = (
                dict(value)
                if isinstance(value, dict)
                else {default_time_field: 0, "source": str(value or "")}
            )
        return records
    if isinstance(raw, list):
        return {
            email: {default_time_field: 0, "source": default_source}
            for item in raw
            if (email := normalized_email(item))
        }
    return {}


def list_registered_emails() -> set[str]:
    with _LOCK:
        return set(_load_records(_KEY_REGISTERED_EMAILS, "registered_at", "legacy"))


def registered_email_records() -> dict[str, dict[str, Any]]:
    with _LOCK:
        return _load_records(_KEY_REGISTERED_EMAILS, "registered_at", "legacy")


def mark_registered_email(email: str, *, source: str = "") -> bool:
    normalized = normalized_email(email)
    if not normalized:
        return False
    now = time.time()
    with _LOCK:
        records = _load_records(_KEY_REGISTERED_EMAILS, "registered_at", "legacy")
        existing = records.get(normalized, {})
        records[normalized] = {
            **existing,
            "registered_at": existing.get("registered_at") or now,
            "updated_at": now,
            "source": str(source or existing.get("source") or "register_success"),
        }
        sqlite_store.set_json(_NAMESPACE, _KEY_REGISTERED_EMAILS, records, path=_db_path())
    return True


def list_unavailable_emails() -> set[str]:
    with _LOCK:
        return set(_load_records(_KEY_UNAVAILABLE_EMAILS, "unavailable_at", "legacy"))


def unavailable_email_records() -> dict[str, dict[str, Any]]:
    with _LOCK:
        return _load_records(_KEY_UNAVAILABLE_EMAILS, "unavailable_at", "legacy")


def mark_unavailable_email(email: str, *, source: str = "") -> bool:
    normalized = normalized_email(email)
    if not normalized:
        return False
    now = time.time()
    with _LOCK:
        records = _load_records(_KEY_UNAVAILABLE_EMAILS, "unavailable_at", "legacy")
        existing = records.get(normalized, {})
        records[normalized] = {
            **existing,
            "unavailable_at": existing.get("unavailable_at") or now,
            "updated_at": now,
            "source": str(source or existing.get("source") or "unavailable"),
        }
        sqlite_store.set_json(_NAMESPACE, _KEY_UNAVAILABLE_EMAILS, records, path=_db_path())
    return True


def cache_mail_message(email: str, message: dict[str, Any], *, source: str = "") -> bool:
    normalized = normalized_email(email)
    if not normalized or not isinstance(message, dict) or not message:
        return False
    now = time.time()
    with _LOCK:
        record = {
            "email": normalized,
            "cached_at": now,
            "source": str(source or "generic-api"),
            "message": dict(message),
        }
        sqlite_store.set_json(_NAMESPACE, f"{_MAIL_CACHE_PREFIX}{normalized}", record, path=_db_path())
    return True


def get_cached_mail_message(email: str) -> dict[str, Any] | None:
    normalized = normalized_email(email)
    if not normalized:
        return None
    with _LOCK:
        record = sqlite_store.get_json(_NAMESPACE, f"{_MAIL_CACHE_PREFIX}{normalized}", None, path=_db_path())
    if not isinstance(record, dict):
        return None
    message = record.get("message")
    if not isinstance(message, dict) or not message:
        return None
    cached_message = dict(message)
    raw = cached_message.get("raw")
    if not isinstance(raw, dict):
        raw = {}
    cached_message["raw"] = {
        **raw,
        "cached": True,
        "cached_at": record.get("cached_at"),
        "cache_source": record.get("source") or "generic-api",
    }
    return cached_message
