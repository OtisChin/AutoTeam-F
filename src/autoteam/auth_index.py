"""SQLite index for Codex auth JSON files.

The auth JSON files under data/auths remain the compatibility/export format.
This module stores their structured metadata and payload in SQLite so account
views and sync flows are not dependent on directory scans long term.
"""

from __future__ import annotations

import json
from pathlib import Path

from autoteam import sqlite_store
from autoteam.textio import read_text


def _normalize(value) -> str:
    return str(value or "").strip()


def upsert_codex_auth_file(path: str | Path, auth_data: dict, *, main: bool = False) -> str:
    file_path = str(Path(path).resolve())
    payload = dict(auth_data or {})
    email = _normalize(payload.get("email")).lower()
    account_id = _normalize(payload.get("account_id") or payload.get("accountId"))
    plan_type = _normalize(payload.get("plan_type") or payload.get("planType") or "unknown").lower() or "unknown"

    sqlite_store.initialize()
    with sqlite_store.connect() as conn:
        conn.execute(
            """
            INSERT INTO codex_auth_files(
                file_path, filename, email, account_id, plan_type, is_main, data, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, strftime('%s','now'))
            ON CONFLICT(file_path) DO UPDATE SET
                filename=excluded.filename,
                email=excluded.email,
                account_id=excluded.account_id,
                plan_type=excluded.plan_type,
                is_main=excluded.is_main,
                data=excluded.data,
                updated_at=excluded.updated_at
            """,
            (
                file_path,
                Path(path).name,
                email,
                account_id,
                plan_type,
                1 if main else 0,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
    return file_path


def delete_codex_auth_file(path: str | Path) -> None:
    try:
        file_path = str(Path(path).resolve())
    except Exception:
        file_path = str(path or "")
    if not file_path:
        return
    sqlite_store.initialize()
    with sqlite_store.connect() as conn:
        conn.execute("DELETE FROM codex_auth_files WHERE file_path = ?", (file_path,))


def delete_codex_auths_for_email(email: str) -> None:
    normalized = _normalize(email).lower()
    if not normalized:
        return
    sqlite_store.initialize()
    with sqlite_store.connect() as conn:
        conn.execute("DELETE FROM codex_auth_files WHERE email = ? AND is_main = 0", (normalized,))


def sync_existing_codex_auth_files() -> int:
    """Index existing data/auths/codex-*.json files into SQLite."""
    from autoteam.auth_storage import AUTH_DIR

    count = 0
    if not AUTH_DIR.exists():
        return count
    for path in AUTH_DIR.glob("codex-*.json"):
        if not path.is_file():
            continue
        try:
            data = json.loads(read_text(path))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        upsert_codex_auth_file(path, data, main=path.name.startswith("codex-main-"))
        count += 1
    return count


def codex_auth_files_by_email(emails: list[str] | set[str] | tuple[str, ...] | None = None) -> dict[str, str]:
    """Return the latest indexed non-main Codex auth file for each email."""
    wanted = sorted({_normalize(email).lower() for email in (emails or []) if _normalize(email)})
    sqlite_store.initialize()
    with sqlite_store.connect() as conn:
        if wanted:
            placeholders = ",".join("?" for _ in wanted)
            rows = conn.execute(
                f"""
                SELECT email, file_path, updated_at
                FROM codex_auth_files
                WHERE is_main = 0 AND email IN ({placeholders})
                ORDER BY email, updated_at DESC
                """,
                wanted,
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT email, file_path, updated_at
                FROM codex_auth_files
                WHERE is_main = 0 AND email != ''
                ORDER BY email, updated_at DESC
                """
            ).fetchall()

    out: dict[str, str] = {}
    for row in rows:
        email = _normalize(row["email"]).lower()
        if email and email not in out:
            out[email] = _normalize(row["file_path"])
    return out
