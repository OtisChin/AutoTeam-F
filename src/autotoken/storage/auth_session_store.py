import hashlib
import json
import os
import re
import sys
import tempfile
import threading
from pathlib import Path

from autotoken.core.normalization import normalized_email as _core_normalized_email
from autotoken.core.paths import PROJECT_ROOT
from autotoken.core.textio import write_text
from autotoken.storage import sqlite_store

AUTH_SESSION_DIR = PROJECT_ROOT / "data" / "auth_session"
_SQLITE_QUERY_CHUNK_SIZE = 500
_LEGACY_SESSION_MAX_BYTES = 2 * 1024 * 1024
_SESSION_FILE_LOCKS = tuple(threading.RLock() for _ in range(64))
_LEGACY_FILE_LOCK = threading.RLock()


def _invalidate_payment_account_caches() -> None:
    try:
        module = sys.modules.get("autotoken.api_routes.brazil_pix")
        if module is not None:
            module.clear_auth_accounts_cache()
    except Exception:
        pass


def _legacy_safe_email_name(email: str) -> str:
    safe_name = (email or "").strip().lower().replace(".", "_")
    safe_name = re.sub(r"[^a-z0-9@_-]+", "_", safe_name)
    safe_name = re.sub(r"_+", "_", safe_name)
    return safe_name.strip("_") or "session"


def _safe_email_name(email: str) -> str:
    normalized = _normalized_email(email)
    readable = re.sub(r"[^a-z0-9@_-]+", "_", normalized.replace(".", "_")).strip("_")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"{(readable or 'session')[:64]}-{digest}"


def _target_path(email: str) -> Path:
    return AUTH_SESSION_DIR / f"{_safe_email_name(email)}.json"


def _legacy_target_path(email: str) -> Path:
    return AUTH_SESSION_DIR / f"{_legacy_safe_email_name(email)}.json"


def _normalized_email(email: str) -> str:
    return _core_normalized_email(email)


def _session_file_lock(email: str) -> threading.RLock:
    digest = hashlib.sha256(_normalized_email(email).encode("utf-8")).digest()
    return _SESSION_FILE_LOCKS[digest[0] % len(_SESSION_FILE_LOCKS)]


def _session_payload_email(session_data: dict) -> str:
    if not isinstance(session_data, dict):
        return ""
    candidates = [session_data.get("email")]
    for key in ("account", "user"):
        nested = session_data.get(key)
        if isinstance(nested, dict):
            candidates.append(nested.get("email"))
    for value in candidates:
        normalized = _normalized_email(str(value or ""))
        if normalized:
            return normalized
    return ""


def _legacy_file_owner_email(path: Path) -> str | None:
    try:
        if not path.is_file() or path.stat().st_size > _LEGACY_SESSION_MAX_BYTES:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return _session_payload_email(payload) or None


def _legacy_file_owned_by_email(path: Path, email: str) -> bool:
    return _legacy_file_owner_email(path) == _normalized_email(email)


def _same_resolved_path(first: str | Path, second: str | Path) -> bool:
    try:
        return Path(first).resolve() == Path(second).resolve()
    except (OSError, RuntimeError, ValueError):
        return False


def _path_lookup_variants(*paths: str | Path) -> tuple[str, ...]:
    variants: set[str] = set()
    for value in paths:
        raw = str(value or "")
        if not raw:
            continue
        candidates = {raw}
        try:
            candidates.add(str(Path(raw).resolve()))
        except (OSError, RuntimeError, ValueError):
            pass
        for candidate in candidates:
            variants.add(candidate)
            variants.add(candidate.replace("\\", "/"))
            variants.add(candidate.replace("/", "\\"))
    return tuple(sorted(variants))


def _has_equivalent_file_path_reference(conn, target: Path, *known_paths: str | Path) -> bool:
    path_variants = _path_lookup_variants(target, *known_paths)
    placeholders = ",".join("?" for _ in path_variants)
    if conn.execute(
        f"SELECT 1 FROM auth_sessions WHERE file_path IN ({placeholders}) LIMIT 1",
        path_variants,
    ).fetchone():
        return True

    escaped_name = target.name.replace("!", "!!").replace("%", "!%").replace("_", "!_")
    candidate_rows = conn.execute(
        "SELECT file_path FROM auth_sessions WHERE file_path LIKE ? ESCAPE '!'",
        (f"%{escaped_name}%",),
    )
    return any(_same_resolved_path(str(row["file_path"] or ""), target) for row in candidate_rows)


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
    descriptor, temporary_name = tempfile.mkstemp(
        dir=AUTH_SESSION_DIR,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        write_text(temporary_path, json.dumps(session_data or {}, indent=2, ensure_ascii=False))
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return str(path)


def _session_data_from_row(row) -> dict:
    if not row:
        return {}
    try:
        data = json.loads(row["data"] or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _update_session_file_path(email: str, previous_path: str, target_path: str) -> None:
    if previous_path == target_path:
        return
    sqlite_store.initialize(_db_path())
    with sqlite_store.connect(_db_path()) as conn:
        conn.execute(
            "UPDATE auth_sessions SET file_path = ? WHERE email = ? AND file_path = ?",
            (target_path, _normalized_email(email), previous_path),
        )


def save_auth_session(email: str, session_data: dict) -> str:
    normalized = _normalized_email(email)
    if not normalized:
        return ""
    with _session_file_lock(normalized):
        path = _upsert_session(normalized, session_data)
        _materialize_file(normalized, session_data)
    if path:
        try:
            from autotoken.storage.accounts import ensure_session_only_account

            ensure_session_only_account(normalized)
        except Exception:
            pass
        _invalidate_payment_account_caches()
    return path


def get_auth_session_file(email: str) -> str:
    normalized = _normalized_email(email)
    if not normalized:
        return ""
    with _session_file_lock(normalized):
        row = _session_row(normalized)
        if row is not None:
            session_data = _session_data_from_row(row)
            path = _materialize_file(normalized, session_data)
            _update_session_file_path(normalized, str(row["file_path"] or ""), path)
            return path
        legacy_path = _legacy_target_path(normalized)
        return str(legacy_path) if _legacy_file_owned_by_email(legacy_path, normalized) else ""


def delete_auth_session(email: str) -> bool:
    normalized = _normalized_email(email)
    if not normalized:
        return False
    deleted = False
    with _LEGACY_FILE_LOCK, _session_file_lock(normalized):
        sqlite_store.initialize(_db_path())
        path = _target_path(normalized)
        legacy_path = _legacy_target_path(normalized)
        legacy_row_path = ""
        legacy_still_referenced = False
        with sqlite_store.connect(_db_path()) as conn:
            row = conn.execute(
                "SELECT file_path FROM auth_sessions WHERE email = ?",
                (normalized,),
            ).fetchone()
            if row and _same_resolved_path(str(row["file_path"] or ""), legacy_path):
                legacy_row_path = str(row["file_path"] or "")
            cursor = conn.execute("DELETE FROM auth_sessions WHERE email = ?", (normalized,))
            deleted = cursor.rowcount > 0
            if legacy_row_path:
                legacy_still_referenced = _has_equivalent_file_path_reference(
                    conn,
                    legacy_path,
                    legacy_row_path,
                )
            legacy_owner = _legacy_file_owner_email(legacy_path)
            if path.exists():
                path.unlink()
                deleted = True
            if legacy_path != path and legacy_path.exists() and (
                legacy_owner == normalized
                or (legacy_owner is None and bool(legacy_row_path) and not legacy_still_referenced)
            ):
                legacy_path.unlink()
                deleted = True
    if deleted:
        _invalidate_payment_account_caches()
    return deleted


def load_auth_session(email: str) -> dict:
    record = get_auth_session_record(email)
    return dict(record["data"]) if record is not None else {}


def get_auth_session_record(email: str) -> dict | None:
    """Return the authoritative SQLite session row for one email, if present."""
    normalized = _normalized_email(email)
    if not normalized:
        return None
    with _session_file_lock(normalized):
        row = _session_row(normalized)
        if row is None:
            return None
        return {
            "email": normalized,
            "file_path": str(_target_path(normalized)),
            "data": _session_data_from_row(row),
            "updated_at": float(row["updated_at"] or 0) if str(row["updated_at"] or "").strip() else 0.0,
        }


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
                # SQLite data is authoritative. Never expose a legacy path that
                # can collide with another normalized email.
                "file_path": str(_target_path(email)),
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
            rows = []
            for start in range(0, len(wanted), _SQLITE_QUERY_CHUNK_SIZE):
                chunk = wanted[start : start + _SQLITE_QUERY_CHUNK_SIZE]
                placeholders = ",".join("?" for _ in chunk)
                rows.extend(
                    conn.execute(
                        f"SELECT email FROM auth_sessions WHERE email IN ({placeholders})",
                        chunk,
                    ).fetchall()
                )
        else:
            rows = conn.execute("SELECT email FROM auth_sessions").fetchall()
    return {
        normalized: str(_target_path(normalized))
        for row in rows
        if (normalized := _normalized_email(row["email"]))
    }
