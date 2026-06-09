"""Shared helpers for local Codex auth-file paths."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from hashlib import md5
from pathlib import Path

from autotoken.core.normalization import normalized_email
from autotoken.core.paths import is_inside_directory

AUTH_JSON_FILE_MAX_BYTES = 2 * 1024 * 1024


def _default_auth_dir() -> Path:
    from autotoken.storage.auth_storage import AUTH_DIR

    return AUTH_DIR


def safe_auth_filename_fragment(value: object) -> str:
    text = str(value or "").strip()
    safe = re.sub(r"[^A-Za-z0-9@._+-]+", "_", text).strip("._")
    return safe or "unknown"


def is_inside_auth_dir(path: Path, *, auth_dir: Path | None = None) -> bool:
    root = auth_dir or _default_auth_dir()
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def trusted_auth_file_path(auth_file: str | Path | None, *, auth_dir: Path | None = None) -> Path | None:
    if not auth_file:
        return None
    path = Path(auth_file)
    if path.exists() and path.is_file() and is_inside_auth_dir(path, auth_dir=auth_dir):
        return path
    return None


def trusted_auth_or_session_path(
    auth_file: str | Path | None,
    *,
    auth_dir: Path | None = None,
    auth_session_dir: Path | None = None,
) -> Path | None:
    trusted = trusted_auth_file_path(auth_file, auth_dir=auth_dir)
    if trusted:
        return trusted
    if not auth_file:
        return None
    path = Path(auth_file)
    if not path.exists() or not path.is_file():
        return None
    try:
        from autotoken.storage.auth_session_store import AUTH_SESSION_DIR

        root = auth_session_dir or AUTH_SESSION_DIR
    except Exception:
        return None
    return path if is_inside_directory(path, root) else None


def iter_codex_auth_files(*, auth_dir: Path | None = None) -> Iterable[Path]:
    root = auth_dir or _default_auth_dir()
    if not root.exists():
        return
    for path in root.glob("codex-*.json"):
        if path.is_file() and is_inside_auth_dir(path, auth_dir=root):
            yield path


def iter_auth_files_for_email(email: str, *, auth_dir: Path | None = None, plan_type: str = "") -> Iterable[Path]:
    root = auth_dir or _default_auth_dir()
    email_prefix = f"codex-{normalized_email(email)}-"
    plan_prefix = f"{email_prefix}{str(plan_type or '').strip().lower()}-" if plan_type else ""
    for path in iter_codex_auth_files(auth_dir=root):
        name = path.name.lower()
        if plan_prefix:
            if name.startswith(plan_prefix):
                yield path
        elif name.startswith(email_prefix):
            yield path


def delete_auth_file(path: Path, *, auth_dir: Path | None = None) -> bool:
    if not is_inside_auth_dir(path, auth_dir=auth_dir):
        return False
    if not path.exists() or not path.is_file():
        return False
    path.unlink()
    return True


def read_auth_json_file(path: str | Path, *, max_bytes: int = AUTH_JSON_FILE_MAX_BYTES) -> dict:
    auth_path = Path(path)
    if auth_path.stat().st_size > max_bytes:
        raise ValueError(f"认证文件过大，无法一次性读取: {auth_path}")
    data = json.loads(auth_path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("认证文件必须是 JSON object")
    return data


def codex_auth_path(
    *,
    email: str,
    plan_type: str,
    account_id: str = "",
    auth_dir: Path | None = None,
    main: bool = False,
) -> Path:
    root = auth_dir or _default_auth_dir()
    if main:
        suffix = safe_auth_filename_fragment(account_id or md5(str(email or "").encode()).hexdigest()[:8])
        return root / f"codex-main-{suffix}.json"
    hash_id = md5(str(account_id or "").encode()).hexdigest()[:8] if account_id else "unknown"
    return root / (
        f"codex-{safe_auth_filename_fragment(email)}-"
        f"{safe_auth_filename_fragment(plan_type or 'unknown')}-"
        f"{hash_id}.json"
    )
