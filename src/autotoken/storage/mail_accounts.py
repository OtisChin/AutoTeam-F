"""SQLite-backed mail account management for the web console."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterable
from typing import Any

from autotoken.core.normalization import normalized_email
from autotoken.core.redaction import mask_log_value
from autotoken.storage import auth_session_store, sqlite_store

MAIL_ACCOUNT_STATUSES = {"enabled", "disabled"}
MAIL_ACCOUNT_CHECK_STATUSES = {"unchecked", "valid", "invalid", "error"}
REGISTERED_ACCOUNT_POOL_STATUSES = {
    "active",
    "auth_invalid",
    "exhausted",
    "orphan",
    "personal",
    "plus",
    "session_only",
    "standby",
}


def _connect() -> sqlite3.Connection:
    sqlite_store.initialize()
    conn = sqlite_store.connect()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mail_accounts (
            email TEXT PRIMARY KEY COLLATE NOCASE,
            gpt_password TEXT NOT NULL DEFAULT '',
            mail_password TEXT NOT NULL DEFAULT '',
            refresh_token TEXT NOT NULL DEFAULT '',
            access_token TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'enabled',
            check_status TEXT NOT NULL DEFAULT 'unchecked',
            note TEXT NOT NULL DEFAULT '',
            last_error TEXT NOT NULL DEFAULT '',
            last_checked_at REAL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mail_accounts_status ON mail_accounts(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mail_accounts_check_status ON mail_accounts(check_status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mail_accounts_updated_at ON mail_accounts(updated_at)")
    return conn


def _normalize_status(value: Any) -> str:
    status = str(value or "enabled").strip().lower()
    return status if status in MAIL_ACCOUNT_STATUSES else "enabled"


def _normalize_check_status(value: Any) -> str:
    status = str(value or "unchecked").strip().lower()
    return status if status in MAIL_ACCOUNT_CHECK_STATUSES else "unchecked"


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    refresh_token = str(data.get("refresh_token") or "")
    access_token = str(data.get("access_token") or "")
    data["refresh_token_masked"] = (
        mask_log_value(refresh_token, left=4, right=2)
        if len(refresh_token) <= 14
        else mask_log_value(refresh_token, left=8, right=6)
    )
    data["access_token_present"] = bool(access_token)
    return data


def _clean_payload(payload: dict[str, Any], *, require_refresh_token: bool = True) -> dict[str, Any]:
    email = normalized_email(payload.get("email"))
    if not email:
        raise ValueError("邮箱不能为空")
    if not email.endswith("@mail.com"):
        raise ValueError("mail邮箱管理只支持 @mail.com 邮箱")
    refresh_token = str(payload.get("refresh_token") or payload.get("refreshToken") or "").strip()
    if require_refresh_token and not refresh_token:
        raise ValueError("refreshToken 不能为空")
    return {
        "email": email,
        "gpt_password": str(payload.get("gpt_password") or payload.get("gptPassword") or "").strip(),
        "mail_password": str(payload.get("mail_password") or payload.get("mailPassword") or "").strip(),
        "refresh_token": refresh_token,
        "status": _normalize_status(payload.get("status")),
        "check_status": _normalize_check_status(payload.get("check_status") or payload.get("checkStatus")),
        "note": str(payload.get("note") or "").strip(),
    }


def list_mail_accounts() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT email, gpt_password, mail_password, refresh_token, access_token,
                   status, check_status, note, last_error, last_checked_at, created_at, updated_at
            FROM mail_accounts
            ORDER BY created_at ASC, email ASC
            """
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def get_mail_account(email: str) -> dict[str, Any] | None:
    normalized = normalized_email(email)
    if not normalized:
        return None
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT email, gpt_password, mail_password, refresh_token, access_token,
                   status, check_status, note, last_error, last_checked_at, created_at, updated_at
            FROM mail_accounts
            WHERE email = ?
            """,
            (normalized,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def upsert_mail_account(payload: dict[str, Any], *, require_refresh_token: bool = True) -> dict[str, Any]:
    item = _clean_payload(payload, require_refresh_token=require_refresh_token)
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO mail_accounts(
                email, gpt_password, mail_password, refresh_token, status,
                check_status, note, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                gpt_password=excluded.gpt_password,
                mail_password=excluded.mail_password,
                refresh_token=excluded.refresh_token,
                status=excluded.status,
                note=excluded.note,
                updated_at=excluded.updated_at
            """,
            (
                item["email"],
                item["gpt_password"],
                item["mail_password"],
                item["refresh_token"],
                item["status"],
                item["check_status"],
                item["note"],
                now,
                now,
            ),
        )
    result = get_mail_account(item["email"])
    assert result is not None
    return result


def import_mail_accounts(text: str) -> dict[str, Any]:
    imported = 0
    skipped = 0
    imported_emails: list[str] = []
    seen_emails: set[str] = set()
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("----")]
        if len(parts) == 2:
            email, mail_password = parts
            gpt_password = ""
            refresh_token = ""
            required_parts = [email, mail_password]
        elif len(parts) == 3:
            email, mail_password, gpt_password = parts
            refresh_token = ""
            required_parts = [email, mail_password, gpt_password]
        elif len(parts) == 4:
            email, gpt_password, mail_password, refresh_token = parts
            required_parts = [email, gpt_password, mail_password, refresh_token]
        else:
            skipped += 1
            continue
        if any(not part for part in required_parts):
            skipped += 1
            continue
        try:
            current = get_mail_account(email) or {}
            updated = upsert_mail_account(
                {
                    "email": email,
                    "gpt_password": gpt_password,
                    "mail_password": mail_password,
                    "refresh_token": refresh_token,
                    "status": current.get("status") or "enabled",
                    "note": current.get("note") or "",
                },
                require_refresh_token=False,
            )
            imported += 1
            email = str(updated.get("email") or "").strip().lower()
            if email and email not in seen_emails:
                seen_emails.add(email)
                imported_emails.append(email)
        except ValueError:
            skipped += 1
    return {"imported": imported, "skipped": skipped, "total": len(list_mail_accounts()), "emails": imported_emails}


def update_mail_account(email: str, payload: dict[str, Any]) -> dict[str, Any]:
    current = get_mail_account(email)
    if not current:
        raise KeyError(email)
    merged = {
        **current,
        **payload,
        "email": current["email"],
        "refresh_token": payload.get("refresh_token", payload.get("refreshToken", current["refresh_token"])),
    }
    return upsert_mail_account(merged)


def set_account_statuses(emails: Iterable[str], status: str) -> dict[str, int]:
    normalized = [email for email in (normalized_email(item) for item in emails) if email]
    clean_status = _normalize_status(status)
    if not normalized:
        return {"updated": 0}
    now = time.time()
    with _connect() as conn:
        updated = 0
        for email in normalized:
            cur = conn.execute(
                "UPDATE mail_accounts SET status = ?, updated_at = ? WHERE email = ?",
                (clean_status, now, email),
            )
            updated += int(cur.rowcount or 0)
    return {"updated": updated}


def change_mail_passwords(emails: Iterable[str], new_password: str) -> dict[str, int]:
    normalized = [email for email in (normalized_email(item) for item in emails) if email]
    password = str(new_password or "").strip()
    if not password:
        raise ValueError("新密码不能为空")
    if not normalized:
        return {"updated": 0}
    now = time.time()
    with _connect() as conn:
        updated = 0
        for email in normalized:
            cur = conn.execute(
                """
                UPDATE mail_accounts
                SET mail_password = ?, updated_at = ?
                WHERE email = ?
                """,
                (password, now, email),
            )
            updated += int(cur.rowcount or 0)
    return {"updated": updated}


def update_notes(emails: Iterable[str], note: str) -> dict[str, int]:
    normalized = [email for email in (normalized_email(item) for item in emails) if email]
    if not normalized:
        return {"updated": 0}
    now = time.time()
    with _connect() as conn:
        updated = 0
        for email in normalized:
            cur = conn.execute(
                "UPDATE mail_accounts SET note = ?, updated_at = ? WHERE email = ?",
                (str(note or "").strip(), now, email),
            )
            updated += int(cur.rowcount or 0)
    return {"updated": updated}


def update_check_result(
    email: str,
    *,
    check_status: str,
    access_token: str = "",
    refresh_token: str = "",
    error: str = "",
) -> dict[str, Any]:
    normalized = normalized_email(email)
    if not normalized:
        raise ValueError("邮箱不能为空")
    now = time.time()
    with _connect() as conn:
        row = conn.execute("SELECT refresh_token FROM mail_accounts WHERE email = ?", (normalized,)).fetchone()
        if not row:
            raise KeyError(email)
        next_refresh_token = str(refresh_token or row["refresh_token"] or "").strip()
        conn.execute(
            """
            UPDATE mail_accounts
            SET check_status = ?, access_token = ?, refresh_token = ?,
                last_error = ?, last_checked_at = ?, updated_at = ?
            WHERE email = ?
            """,
            (
                _normalize_check_status(check_status),
                str(access_token or "").strip(),
                next_refresh_token,
                str(error or "").strip()[:1000],
                now,
                now,
                normalized,
            ),
        )
    result = get_mail_account(normalized)
    assert result is not None
    return result


def delete_mail_accounts(emails: Iterable[str]) -> dict[str, int]:
    normalized = [email for email in (normalized_email(item) for item in emails) if email]
    if not normalized:
        return {"deleted": 0}
    with _connect() as conn:
        deleted = 0
        for email in normalized:
            cur = conn.execute("DELETE FROM mail_accounts WHERE email = ?", (email,))
            deleted += int(cur.rowcount or 0)
    return {"deleted": deleted}


def clear_mail_accounts() -> dict[str, int]:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM mail_accounts")
        deleted = int(cur.rowcount or 0)
    return {"deleted": deleted}


def _account_pool_by_email() -> dict[str, dict[str, Any]]:
    try:
        from autotoken.storage.accounts import load_accounts

        return {
            normalized_email(account.get("email")): dict(account)
            for account in load_accounts()
            if normalized_email(account.get("email"))
        }
    except Exception:
        return {}


def _mailcom_registered_emails() -> set[str]:
    emails = set()
    for email, account in _account_pool_by_email().items():
        if not email:
            continue
        if str(account.get("auth_file") or "").strip():
            emails.add(email)
            continue
        status = str(account.get("status") or "").strip().lower()
        if status in REGISTERED_ACCOUNT_POOL_STATUSES:
            emails.add(email)
    try:
        emails.update(auth_session_store.list_auth_session_emails())
    except Exception:
        pass
    try:
        from autotoken.storage.register_failures import list_failures

        for failure in list_failures(500):
            email = normalized_email(failure.get("email"))
            if not email:
                continue
            category = str(failure.get("category") or "").strip().lower()
            reason = str(failure.get("reason") or "").strip().lower()
            if category == "email_already_in_use" or "email_already_in_use" in reason:
                emails.add(email)
    except Exception:
        pass
    return emails


def _mail_account_note_marks_registered(note: Any) -> bool:
    raw = str(note or "").strip()
    lowered = raw.lower()
    return "已注册" in raw or "registered" in lowered or "email_already_in_use" in lowered


def list_available_registration_accounts() -> list[dict[str, Any]]:
    registered = _mailcom_registered_emails()
    rows = []
    for row in list_mail_accounts():
        email = normalized_email(row.get("email"))
        if not email:
            continue
        if row.get("status") != "enabled":
            continue
        if email in registered:
            continue
        if _mail_account_note_marks_registered(row.get("note")):
            continue
        if not str(row.get("mail_password") or "").strip():
            continue
        rows.append(row)
    return rows


def sync_mail_accounts_to_account_pool(emails: Iterable[str] | None = None) -> dict[str, Any]:
    selected = None if emails is None else {email for email in (normalized_email(item) for item in emails) if email}
    rows = [
        row
        for row in list_mail_accounts()
        if selected is None or normalized_email(row.get("email")) in selected
    ]
    from autotoken.storage.accounts import SEAT_CODEX, add_account, update_account

    synced = []
    skipped = []
    for row in rows:
        email = normalized_email(row.get("email"))
        gpt_password = str(row.get("gpt_password") or "").strip()
        if not email:
            skipped.append({"email": str(row.get("email") or ""), "reason": "邮箱为空"})
            continue
        if not gpt_password:
            skipped.append({"email": email, "reason": "GPT密码为空"})
            continue
        add_account(
            email,
            gpt_password,
            cloudmail_account_id=email,
            seat_type=SEAT_CODEX,
            mail_provider="mail.com",
        )
        update_account(
            email,
            password=gpt_password,
            cloudmail_account_id=email,
            mail_provider="mail.com",
        )
        synced.append(email)
    return {"synced": len(synced), "skipped": skipped, "emails": synced}


def mailcom_pool_status() -> dict[str, Any]:
    accounts_by_email = _account_pool_by_email()
    registered_emails = _mailcom_registered_emails()
    items = []
    for row in list_mail_accounts():
        email = normalized_email(row.get("email"))
        account = accounts_by_email.get(email or "")
        auth_session_file = auth_session_store.get_auth_session_file(email) if email else ""
        auth_ready = bool(auth_session_file)
        check_status = str(row.get("check_status") or "").strip().lower()
        last_error = str(row.get("last_error") or "").strip()
        account_status = "missing" if not account else str(account.get("status") or "pending")
        registered = bool(
            email
            and (
                email in registered_emails
                or account_status in REGISTERED_ACCOUNT_POOL_STATUSES
                or _mail_account_note_marks_registered(row.get("note"))
            )
        )
        if row.get("status") == "disabled":
            login_status = "disabled"
            login_error = ""
        elif auth_ready:
            login_status = "ready"
            login_error = ""
        elif check_status in {"error", "invalid"} and last_error:
            login_status = "failed"
            login_error = last_error
        elif str(row.get("mail_password") or "").strip():
            login_status = "available"
            login_error = ""
        else:
            login_status = "not_logged_in"
            login_error = ""
        item = {
            **row,
            "login_status": login_status,
            "login_error": login_error,
            "registered": registered,
            "registered_status": "registered" if registered else "unused",
            "account_pool_status": account_status,
            "auth_session_status": "ready" if auth_ready else "missing",
            "auth_session_file": auth_session_file,
            "pool_status": login_status,
        }
        items.append(item)

    available_items = [item for item in items if item.get("login_status") == "available"]
    return {
        "items": items,
        "total": len(items),
        "available": len(available_items),
        "auth_session_ready": sum(1 for item in items if item.get("auth_session_status") == "ready"),
        "registered": sum(1 for item in items if item.get("registered")),
        "not_logged_in": sum(
            1 for item in items if item.get("login_status") in {"available", "not_logged_in"}
        ),
        "disabled": sum(1 for item in items if item.get("status") == "disabled"),
        "login_failed": sum(1 for item in items if item.get("login_status") == "failed"),
        "next_available_email": available_items[0]["email"] if available_items else "",
    }


def mark_mailcom_login_failure(
    email: str,
    error: str,
    *,
    check_status: str = "error",
) -> dict[str, Any] | None:
    normalized = normalized_email(email)
    if not normalized:
        raise ValueError("邮箱不能为空")
    now = time.time()
    with _connect() as conn:
        row = conn.execute("SELECT email FROM mail_accounts WHERE email = ?", (normalized,)).fetchone()
        if not row:
            return None
        conn.execute(
            """
            UPDATE mail_accounts
            SET check_status = ?, last_error = ?, last_checked_at = ?, updated_at = ?
            WHERE email = ?
            """,
            (_normalize_check_status(check_status), str(error or "").strip()[:1000], now, now, normalized),
        )
    return get_mail_account(normalized)


def mark_mailcom_registered(
    email: str,
    *,
    gpt_password: str = "",
    refresh_token: str = "",
    source: str = "",
) -> dict[str, Any] | None:
    current = get_mail_account(email)
    if not current:
        return None
    note_parts = [part for part in [str(current.get("note") or "").strip(), f"已注册:{source or 'registered'}"] if part]
    payload = {
        **current,
        "gpt_password": str(gpt_password or current.get("gpt_password") or "").strip(),
        "refresh_token": str(refresh_token or current.get("refresh_token") or "").strip(),
        "check_status": "valid",
        "note": "；".join(dict.fromkeys(note_parts)),
    }
    updated = upsert_mail_account(payload, require_refresh_token=False)
    update_check_result(
        updated["email"],
        check_status="valid",
        access_token=str(updated.get("access_token") or ""),
        refresh_token=str(updated.get("refresh_token") or ""),
        error="",
    )
    return get_mail_account(updated["email"])


def export_mail_accounts() -> str:
    lines = []
    for row in list_mail_accounts():
        lines.append(
            "----".join(
                [
                    row["email"],
                    str(row.get("gpt_password") or ""),
                    str(row.get("mail_password") or ""),
                    str(row.get("refresh_token") or ""),
                ]
            )
        )
    return "\n".join(lines)
