import json
import re
from pathlib import Path

from autotoken.core.normalization import normalized_email as _core_normalized_email
from autotoken.core.paths import PROJECT_ROOT
from autotoken.core.textio import write_text
from autotoken.storage import sqlite_store

AUTH_SESSION_DIR = PROJECT_ROOT / "data" / "auth_session"


def _invalidate_payment_account_caches() -> None:
    try:
        from autotoken.api_routes import brazil_pix

        brazil_pix.clear_auth_accounts_cache()
    except Exception:
        pass


def _safe_email_name(email: str) -> str:
    safe_name = (email or "").strip().lower().replace(".", "_")
    safe_name = re.sub(r"[^a-z0-9@_-]+", "_", safe_name)
    safe_name = re.sub(r"_+", "_", safe_name)
    return safe_name.strip("_") or "session"


def _target_path(email: str) -> Path:
    return AUTH_SESSION_DIR / f"{_safe_email_name(email)}.json"


def _normalized_email(email: str) -> str:
    return _core_normalized_email(email)


def _db_path() -> Path:
    try:
        if Path(AUTH_SESSION_DIR).resolve() != (PROJECT_ROOT / "data" / "auth_session").resolve():
            return Path(AUTH_SESSION_DIR).parent / "auth_session.sqlite3"
    except Exception:
        pass
    return sqlite_store.default_db_path()


def _upsert_session(email: str, session_data: dict) -> str:
    normalized = _normalized_email(email)
    if not normalized:
        return ""
    path = _target_path(normalized)
    sqlite_store.initialize(_db_path())
    with sqlite_store.connect(_db_path()) as conn:
        conn.execute(
            """
            INSERT INTO auth_sessions(email, file_path, data, updated_at)
            VALUES (?, ?, ?, strftime('%s','now'))
            ON CONFLICT(email) DO UPDATE SET
                file_path=excluded.file_path,
                data=excluded.data,
                updated_at=excluded.updated_at
            """,
            (normalized, str(path), json.dumps(session_data or {}, ensure_ascii=False)),
        )
    return str(path)


def _session_row(email: str):
    normalized = _normalized_email(email)
    if not normalized:
        return None
    sqlite_store.initialize(_db_path())
    with sqlite_store.connect(_db_path()) as conn:
        return conn.execute("SELECT * FROM auth_sessions WHERE email = ?", (normalized,)).fetchone()


def _materialize_file(email: str, session_data: dict) -> str:
    AUTH_SESSION_DIR.mkdir(parents=True, exist_ok=True)
    path = _target_path(email)
    write_text(path, json.dumps(session_data or {}, indent=2, ensure_ascii=False))
    return str(path)


def save_auth_session(email: str, session_data: dict) -> str:
    normalized = _normalized_email(email)
    path = _upsert_session(email, session_data)
    if path:
        _materialize_file(normalized, session_data)
        try:
            from autotoken.storage.accounts import ensure_session_only_account

            ensure_session_only_account(normalized)
        except Exception:
            pass
        _invalidate_payment_account_caches()
    return path


def get_auth_session_file(email: str) -> str:
    session_data = load_auth_session(email)
    if session_data:
        return _materialize_file(_normalized_email(email), session_data)
    path = _target_path(email)
    return str(path) if path.exists() else ""


def delete_auth_session(email: str) -> bool:
    normalized = _normalized_email(email)
    deleted = False
    if normalized:
        sqlite_store.initialize(_db_path())
        with sqlite_store.connect(_db_path()) as conn:
            cursor = conn.execute("DELETE FROM auth_sessions WHERE email = ?", (normalized,))
            deleted = cursor.rowcount > 0
    path = _target_path(email)
    if path.exists():
        path.unlink()
        deleted = True
    if deleted:
        _invalidate_payment_account_caches()
    return deleted


def load_auth_session(email: str) -> dict:
    row = _session_row(email)
    if row:
        try:
            data = json.loads(row["data"] or "{}")
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def list_auth_session_emails() -> list[str]:
    emails = []
    sqlite_store.initialize(_db_path())
    with sqlite_store.connect(_db_path()) as conn:
        rows = conn.execute("SELECT email FROM auth_sessions ORDER BY email").fetchall()
        emails.extend(str(row["email"] or "") for row in rows)
    return sorted({normalized for email in emails if (normalized := _normalized_email(email))})


def list_auth_session_records() -> list[dict]:
    """Return all stored auth sessions without materializing every JSON file."""
    sqlite_store.initialize(_db_path())
    records: list[dict] = []
    with sqlite_store.connect(_db_path()) as conn:
        rows = conn.execute("SELECT email, file_path, data, updated_at FROM auth_sessions ORDER BY email").fetchall()
    for row in rows:
        email = _normalized_email(str(row["email"] or ""))
        if not email:
            continue
        try:
            data = json.loads(row["data"] or "{}")
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        records.append(
            {
                "email": email,
                "file_path": str(row["file_path"] or _target_path(email)),
                "data": data,
                "updated_at": float(row["updated_at"] or 0) if str(row["updated_at"] or "").strip() else 0.0,
            }
        )
    return records


def auth_session_files_by_email(emails: list[str] | set[str] | tuple[str, ...] | None = None) -> dict[str, str]:
    wanted = sorted({_normalized_email(email) for email in (emails or []) if _normalized_email(email)})
    sqlite_store.initialize(_db_path())
    with sqlite_store.connect(_db_path()) as conn:
        if wanted:
            placeholders = ",".join("?" for _ in wanted)
            rows = conn.execute(
                f"SELECT email, file_path FROM auth_sessions WHERE email IN ({placeholders})",
                wanted,
            ).fetchall()
        else:
            rows = conn.execute("SELECT email, file_path FROM auth_sessions").fetchall()
    return {
        _normalized_email(row["email"]): str(row["file_path"] or "")
        for row in rows
        if _normalized_email(row["email"])
    }
