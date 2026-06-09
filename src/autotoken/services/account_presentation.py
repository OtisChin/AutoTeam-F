"""Account display and sanitization helpers for API responses."""

from collections.abc import Callable
from pathlib import Path

from autotoken.storage.auth_files import iter_auth_files_for_email, read_auth_json_file, trusted_auth_file_path


def quota_snapshot_status(quota_info: dict | None) -> str:
    if not isinstance(quota_info, dict):
        return ""

    values = []
    for key in ("primary_pct", "weekly_pct"):
        value = quota_info.get(key)
        if isinstance(value, (int, float)):
            values.append(value)

    if not values:
        return ""
    return "exhausted" if any(value >= 100 for value in values) else "active"


def resolve_status_auth_file(acc: dict, *, is_main_account_email: Callable[[str | None], bool]) -> str:
    auth_file = (acc.get("auth_file") or "").strip()
    if auth_file:
        try:
            from autotoken.storage.auth_storage import AUTH_DIR

            path = trusted_auth_file_path(auth_file, auth_dir=AUTH_DIR)
            if path:
                return str(path)
        except Exception:
            pass

    try:
        from autotoken.storage.auth_session_store import get_auth_session_file

        session_file = get_auth_session_file(acc.get("email") or "")
        if session_file and Path(session_file).exists():
            return session_file
    except Exception:
        pass

    if is_main_account_email(acc.get("email")):
        from autotoken.auth.codex_auth import get_saved_main_auth_file

        saved_auth_file = get_saved_main_auth_file()
        if saved_auth_file and Path(saved_auth_file).exists():
            return saved_auth_file

    return ""


def resolve_codex_auth_file(acc: dict, *, normalize_email: Callable[[str | None], str]) -> str:
    auth_file = (acc.get("auth_file") or "").strip()
    from autotoken.storage.auth_storage import AUTH_DIR

    if auth_file:
        path = trusted_auth_file_path(auth_file, auth_dir=AUTH_DIR)
        if path:
            return str(path)

    email = normalize_email(acc.get("email"))
    if not email:
        return ""
    try:
        candidates = sorted(
            iter_auth_files_for_email(email, auth_dir=AUTH_DIR),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except Exception:
        return ""
    return str(candidates[0]) if candidates else ""


def valid_account_auth_file(acc: dict) -> str:
    auth_file = str(acc.get("auth_file") or "").strip()
    if not auth_file:
        return ""
    try:
        from autotoken.storage.auth_storage import AUTH_DIR

        path = trusted_auth_file_path(auth_file, auth_dir=AUTH_DIR)
        if path:
            return str(path)
    except Exception:
        return ""
    return ""


def codex_auth_file_is_synthetic(auth_file: str) -> bool:
    path_text = str(auth_file or "").strip()
    if not path_text:
        return False
    try:
        path = Path(path_text)
        if not path.exists() or not path.is_file():
            return False
        data = read_auth_json_file(path)
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    if bool(data.get("id_token_synthetic")):
        return True
    id_token = str(data.get("id_token") or data.get("idToken") or "")
    return ".synthetic" in id_token


def display_account_status(
    acc: dict,
    quota_snapshot: dict | None = None,
    *,
    is_main_account_email: Callable[[str | None], bool],
    resolve_status_auth_file_func: Callable[[dict], str],
) -> str:
    status = acc.get("status", "")
    if status in ("personal", "plus"):
        status = "active"
    if not is_main_account_email(acc.get("email")):
        return status

    quota_status = quota_snapshot_status(quota_snapshot) or quota_snapshot_status(acc.get("last_quota"))
    if quota_status:
        return quota_status

    return "active" if resolve_status_auth_file_func(acc) else status


def display_account_type(acc: dict) -> str:
    account_type = (acc.get("account_type") or "").strip().lower()
    if account_type in {"free", "team", "plus", "pro"}:
        return account_type
    status = (acc.get("status") or "").strip().lower()
    if status == "plus":
        return "plus"
    if status == "personal":
        return "free"
    if status in {"active", "exhausted", "standby"}:
        return "team"
    return "free"


def sanitize_account(
    acc: dict,
    quota_snapshot: dict | None = None,
    *,
    normalize_email: Callable[[str | None], str],
    is_main_account_email: Callable[[str | None], bool],
    resolve_status_auth_file_func: Callable[[dict], str],
    resolve_codex_auth_file_func: Callable[[dict], str],
) -> dict:
    return sanitize_accounts_batch(
        [acc],
        {acc.get("email"): quota_snapshot} if quota_snapshot else {},
        normalize_email=normalize_email,
        is_main_account_email=is_main_account_email,
        resolve_status_auth_file_func=resolve_status_auth_file_func,
        resolve_codex_auth_file_func=resolve_codex_auth_file_func,
    ).pop()


def sanitize_accounts_batch(
    accounts: list[dict],
    quota_cache: dict | None = None,
    *,
    normalize_email: Callable[[str | None], str],
    is_main_account_email: Callable[[str | None], bool],
    resolve_status_auth_file_func: Callable[[dict], str],
    resolve_codex_auth_file_func: Callable[[dict], str],
) -> list[dict]:
    quota_cache = quota_cache or {}
    emails = [normalize_email(acc.get("email")) for acc in accounts if normalize_email(acc.get("email"))]
    single_account = len(accounts) == 1
    try:
        from autotoken.settings.admin_state import get_admin_email

        main_email = normalize_email(get_admin_email())
    except Exception:
        main_email = ""
    if single_account and emails and not main_email:
        try:
            if is_main_account_email(emails[0]):
                main_email = emails[0]
        except Exception:
            pass
    try:
        from autotoken.storage.auth_index import codex_auth_metadata_by_email

        auth_metadata = codex_auth_metadata_by_email(emails)
    except Exception:
        auth_metadata = {}
    try:
        from autotoken.storage.auth_session_store import auth_session_files_by_email

        auth_session_files = auth_session_files_by_email(emails)
    except Exception:
        auth_session_files = {}
    if single_account and emails and not auth_session_files.get(emails[0]):
        try:
            from autotoken.storage.auth_session_store import get_auth_session_file

            auth_session_file = get_auth_session_file(emails[0]) or ""
            if auth_session_file:
                auth_session_files[emails[0]] = auth_session_file
        except Exception:
            pass

    sanitized_rows = []
    for acc in accounts:
        email = normalize_email(acc.get("email"))
        quota_snapshot = quota_cache.get(email) if isinstance(quota_cache, dict) else None
        sanitized_rows.append(
            sanitize_account_with_indexes(
                acc,
                quota_snapshot,
                auth_metadata,
                auth_session_files,
                main_email,
                normalize_email=normalize_email,
                resolve_status_auth_file_func=resolve_status_auth_file_func,
                resolve_codex_auth_file_func=resolve_codex_auth_file_func,
            )
        )
    return sanitized_rows


def sanitize_account_with_indexes(
    acc: dict,
    quota_snapshot: dict | None,
    auth_metadata: dict[str, dict],
    auth_session_files: dict[str, str],
    main_email: str = "",
    *,
    normalize_email: Callable[[str | None], str],
    resolve_status_auth_file_func: Callable[[dict], str],
    resolve_codex_auth_file_func: Callable[[dict], str],
) -> dict:
    sanitized = {k: v for k, v in acc.items() if k not in ("password", "cloudmail_account_id")}
    email = normalize_email(acc.get("email"))
    is_main = bool(email and main_email and email == main_email)
    sanitized["is_main_account"] = is_main
    status = acc.get("status", "")
    if status in ("personal", "plus"):
        status = "active"
    if is_main:
        quota_status = quota_snapshot_status(quota_snapshot) or quota_snapshot_status(acc.get("last_quota"))
        status = quota_status or ("active" if resolve_status_auth_file_func(acc) else status)
    sanitized["status"] = status
    sanitized["account_type"] = display_account_type(acc)
    sanitized["credentials_exported"] = bool(acc.get("credentials_exported"))
    sanitized["credentials_exported_at"] = acc.get("credentials_exported_at")
    sanitized["account_hub_synced"] = bool(acc.get("account_hub_synced"))
    sanitized["account_hub_synced_at"] = acc.get("account_hub_synced_at")
    indexed_auth = auth_metadata.get(email) if isinstance(auth_metadata, dict) else {}
    indexed_auth_file = str((indexed_auth or {}).get("file_path") or "").strip()
    if indexed_auth_file:
        try:
            from autotoken.storage.auth_storage import AUTH_DIR

            path = trusted_auth_file_path(indexed_auth_file, auth_dir=AUTH_DIR)
            indexed_auth_file = str(path) if path else ""
        except Exception:
            indexed_auth_file = ""
    codex_auth_file = indexed_auth_file or valid_account_auth_file(acc)
    if not codex_auth_file and sanitized["is_main_account"]:
        codex_auth_file = resolve_codex_auth_file_func(acc)
    sanitized["codex_auth_file"] = codex_auth_file
    sanitized["has_codex_auth_file"] = bool(codex_auth_file)
    if codex_auth_file and indexed_auth_file and codex_auth_file == indexed_auth_file:
        sanitized["codex_auth_synthetic"] = bool((indexed_auth or {}).get("synthetic"))
    else:
        sanitized["codex_auth_synthetic"] = codex_auth_file_is_synthetic(codex_auth_file)
    sanitized["needs_codex_login"] = not sanitized["is_main_account"] and (
        not bool(codex_auth_file) or bool(sanitized["codex_auth_synthetic"])
    )
    auth_session_file = auth_session_files.get(email, "")
    sanitized["auth_session_file"] = auth_session_file
    return sanitized
