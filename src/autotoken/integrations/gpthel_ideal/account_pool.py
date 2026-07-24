from __future__ import annotations

import base64
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .mail_pool import CredentialCipher, EMAIL_RE


JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
FIELD_SPLIT_RE = re.compile(r"\s*(?:----|\|\||\t|,|，|\s+)\s*")


class AccountPoolError(Exception):
    pass


class AccountPoolNotFound(AccountPoolError):
    pass


@dataclass(slots=True)
class ParsedAccount:
    email: str
    access_token: str = ""
    refresh_token: str = ""
    session_token: str = ""
    cookie_header: str = ""
    account_id: str = ""
    source: str = "account_pool_import"
    raw_json: str = ""

    def credentials(self) -> dict[str, str]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "session_token": self.session_token,
            "cookie_header": self.cookie_header,
            "account_id": self.account_id,
            "raw_json": self.raw_json,
        }


class AccountPoolStore:
    def __init__(
        self,
        db_path: Path,
        key_path: Path | None = None,
        secret_key: bytes | None = None,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.cipher = CredentialCipher(
            key_path or self.db_path.with_suffix(".account_pool.key"),
            key=secret_key,
        )
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS registered_accounts (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                  account_id TEXT NOT NULL DEFAULT '',
                  credentials BLOB NOT NULL,
                  source TEXT NOT NULL DEFAULT '',
                  status TEXT NOT NULL DEFAULT 'ready',
                  fail_count INTEGER NOT NULL DEFAULT 0,
                  last_used_at REAL NOT NULL DEFAULT 0,
                  is_active INTEGER NOT NULL DEFAULT 1,
                  created_at REAL NOT NULL,
                  updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_registered_accounts_pick
                  ON registered_accounts(status, is_active, last_used_at, id);
                """
            )

    def import_accounts(self, text: str) -> dict[str, Any]:
        rows, skipped, first_error = parse_account_import(text)
        applied = 0
        updated = 0
        token_count = 0
        refresh_count = 0
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for row in rows:
                existing = connection.execute(
                    "SELECT credentials FROM registered_accounts WHERE email = ? LIMIT 1",
                    (row.email,),
                ).fetchone()
                credentials = self.cipher.decrypt(existing["credentials"]) if existing else {}
                for key, value in row.credentials().items():
                    if value:
                        credentials[key] = value
                encrypted = self.cipher.encrypt(credentials)
                result = connection.execute(
                    """
                    INSERT INTO registered_accounts(
                      email, account_id, credentials, source, status,
                      fail_count, last_used_at, is_active, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, 'ready', 0, 0, 1, ?, ?)
                    ON CONFLICT(email) DO UPDATE SET
                      account_id = CASE WHEN excluded.account_id != '' THEN excluded.account_id ELSE registered_accounts.account_id END,
                      credentials = excluded.credentials,
                      source = CASE WHEN excluded.source != '' THEN excluded.source ELSE registered_accounts.source END,
                      status = CASE WHEN registered_accounts.status = 'disabled' THEN 'ready' ELSE registered_accounts.status END,
                      is_active = 1,
                      updated_at = excluded.updated_at
                    """,
                    (row.email, row.account_id, encrypted, row.source, now, now),
                )
                applied += int(result.rowcount > 0)
                updated += int(existing is not None)
                token_count += int(bool(credentials.get("access_token")))
                refresh_count += int(bool(credentials.get("refresh_token")))
            connection.commit()
        return {
            "success": applied > 0 or not rows,
            "parsed": len(rows),
            "applied": applied,
            "updated": updated,
            "skipped": skipped,
            "token_count": token_count,
            "refresh_count": refresh_count,
            "first_error": first_error,
        }

    def list_accounts(self, status: str = "all", query: str = "", limit: int = 300) -> dict[str, Any]:
        conditions = ["is_active = 1"]
        args: list[Any] = []
        status = (status or "all").strip().lower()
        if status and status != "all":
            conditions.append("status = ?")
            args.append(status)
        query = (query or "").strip().lower()
        if query:
            like = f"%{query}%"
            conditions.append("(lower(email) LIKE ? OR lower(account_id) LIKE ? OR lower(source) LIKE ?)")
            args.extend([like, like, like])
        limit = max(1, min(int(limit or 300), 1000))
        args.append(limit)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id, email, account_id, credentials, source, status,
                       fail_count, last_used_at, is_active, created_at, updated_at
                FROM registered_accounts
                WHERE {' AND '.join(conditions)}
                ORDER BY CASE status WHEN 'ready' THEN 0 WHEN 'used' THEN 1 WHEN 'failed' THEN 2 WHEN 'disabled' THEN 3 ELSE 4 END,
                  last_used_at ASC,
                  id ASC
                LIMIT ?
                """,
                args,
            ).fetchall()
        items = [self._public_account(row) for row in rows]
        return {"items": items, "summary": summarize_accounts(items)}

    def reveal_access_token(self, account_id: int) -> dict[str, Any]:
        row, credentials = self._account_with_credentials(account_id)
        token = str(credentials.get("access_token") or "").strip()
        if not token:
            raise AccountPoolError("账号缺少 access_token")
        return {"success": True, "id": row["id"], "email": row["email"], "access_token": token}

    def mark_used(self, account_id: int) -> dict[str, Any]:
        return self._set_status(account_id, "used", touch_used=True)

    def reset_account(self, account_id: int) -> dict[str, Any]:
        return self._set_status(account_id, "ready", clear_failures=True)

    def disable_account(self, account_id: int) -> None:
        with self._connect() as connection:
            result = connection.execute(
                "UPDATE registered_accounts SET status = 'disabled', is_active = 0, updated_at = ? WHERE id = ?",
                (time.time(), account_id),
            )
        if result.rowcount == 0:
            raise AccountPoolNotFound("账号不存在")

    def disable_account_by_email(self, email: str) -> bool:
        target = str(email or "").strip()
        if not target:
            return False
        with self._connect() as connection:
            result = connection.execute(
                "UPDATE registered_accounts SET status = 'disabled', is_active = 0, updated_at = ? WHERE email = ?",
                (time.time(), target),
            )
        return bool(result.rowcount)

    def _set_status(
        self,
        account_id: int,
        status: str,
        touch_used: bool = False,
        clear_failures: bool = False,
    ) -> dict[str, Any]:
        now = time.time()
        with self._connect() as connection:
            result = connection.execute(
                """
                UPDATE registered_accounts
                SET status = ?,
                    last_used_at = CASE WHEN ? THEN ? ELSE last_used_at END,
                    fail_count = CASE WHEN ? THEN 0 ELSE fail_count END,
                    updated_at = ?
                WHERE id = ? AND is_active = 1
                """,
                (status, int(touch_used), now, int(clear_failures), now, account_id),
            )
        if result.rowcount == 0:
            raise AccountPoolNotFound("账号不存在")
        row, _ = self._account_with_credentials(account_id)
        return self._public_account(row)

    def _account_with_credentials(self, account_id: int) -> tuple[sqlite3.Row, dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, email, account_id, credentials, source, status,
                       fail_count, last_used_at, is_active, created_at, updated_at
                FROM registered_accounts
                WHERE id = ?
                LIMIT 1
                """,
                (account_id,),
            ).fetchone()
        if row is None:
            raise AccountPoolNotFound("账号不存在")
        return row, self.cipher.decrypt(row["credentials"])

    def _public_account(self, row: sqlite3.Row) -> dict[str, Any]:
        credentials = self.cipher.decrypt(row["credentials"])
        return {
            "id": row["id"],
            "email": row["email"],
            "account_id": row["account_id"],
            "source": row["source"],
            "status": row["status"],
            "fail_count": row["fail_count"],
            "last_used_at": row["last_used_at"],
            "is_active": bool(row["is_active"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "has_access_token": bool(str(credentials.get("access_token") or "").strip()),
            "has_refresh_token": bool(str(credentials.get("refresh_token") or "").strip()),
            "has_session_token": bool(str(credentials.get("session_token") or "").strip()),
            "has_cookie": bool(str(credentials.get("cookie_header") or "").strip()),
        }


def parse_account_import(text: str) -> tuple[list[ParsedAccount], int, str]:
    text = (text or "").strip()
    if not text:
        return [], 0, ""
    parsed_json = parse_json_accounts(text)
    rows: list[ParsedAccount] = []
    skipped = 0
    first_error = ""
    if parsed_json is not None:
        candidates = parsed_json
    else:
        candidates = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            parsed_line = parse_json_accounts(line)
            if parsed_line is not None:
                candidates.extend(parsed_line)
                continue
            account = parse_account_line(line)
            if account:
                candidates.append(account)
            else:
                skipped += 1
                if not first_error:
                    first_error = f"无法解析账号：{line[:80]}"
    seen: set[str] = set()
    for item in candidates:
        item.email = normalize_email(item.email)
        if not EMAIL_RE.match(item.email):
            skipped += 1
            if not first_error:
                first_error = f"账号缺少有效邮箱：{item.email or item.account_id or 'unknown'}"
            continue
        if not item.access_token and not item.refresh_token and not item.session_token:
            skipped += 1
            if not first_error:
                first_error = f"账号缺少 token：{item.email}"
            continue
        key = item.email.lower()
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        rows.append(item)
    return rows, skipped, first_error


def parse_json_accounts(text: str) -> list[ParsedAccount] | None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        if isinstance(payload.get("accounts"), list):
            values = payload["accounts"]
        elif isinstance(payload.get("items"), list):
            values = payload["items"]
        else:
            values = [payload]
    elif isinstance(payload, list):
        values = payload
    else:
        return []
    rows: list[ParsedAccount] = []
    for value in values:
        if isinstance(value, dict):
            account = account_from_mapping(value)
            if account:
                rows.append(account)
        elif isinstance(value, str):
            account = parse_account_line(value)
            if account:
                rows.append(account)
    return rows


def account_from_mapping(value: dict[str, Any]) -> ParsedAccount | None:
    email = first_string(value, "email", "mail", "username", "login")
    access_token = first_string(value, "access_token", "accessToken", "token")
    if not access_token:
        access_token = find_nested_string(value, {"access_token", "accessToken", "token"})
    if not email:
        email = email_from_token(access_token)
    refresh_token = first_string(value, "refresh_token", "refreshToken")
    session_token = first_string(value, "session_token", "sessionToken")
    cookie_header = first_string(value, "cookie_header", "cookieHeader", "cookie")
    account_id = first_string(value, "account_id", "accountId", "id", "chatgpt_account_id")
    source = first_string(value, "source", "source_tag", "sourceTag") or "account_pool_import"
    if not email and not account_id and not access_token:
        return None
    return ParsedAccount(
        email=email,
        access_token=access_token,
        refresh_token=refresh_token,
        session_token=session_token,
        cookie_header=cookie_header,
        account_id=account_id,
        source=source,
        raw_json=json.dumps(value, ensure_ascii=False, separators=(",", ":")),
    )


def parse_account_line(line: str) -> ParsedAccount | None:
    fields = [field.strip() for field in FIELD_SPLIT_RE.split(line) if field.strip()]
    if not fields:
        return None
    email = next((field for field in fields if EMAIL_RE.match(field)), "")
    token_match = JWT_RE.search(line)
    token = token_match.group(0) if token_match else ""
    if not email and token:
        email = email_from_token(token)
    if not token and len(fields) >= 2 and fields[0] == email:
        token = fields[1]
    if not email:
        return None
    return ParsedAccount(email=email, access_token=token, raw_json=line)


def summarize_accounts(items: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "total": len(items),
        "ready": 0,
        "used": 0,
        "failed": 0,
        "disabled": 0,
        "with_access_token": 0,
        "with_refresh_token": 0,
        "with_session_token": 0,
    }
    for item in items:
        status = str(item.get("status") or "")
        if status in summary:
            summary[status] += 1
        summary["with_access_token"] += int(bool(item.get("has_access_token")))
        summary["with_refresh_token"] += int(bool(item.get("has_refresh_token")))
        summary["with_session_token"] += int(bool(item.get("has_session_token")))
    return summary


def first_string(value: dict[str, Any], *keys: str) -> str:
    for key in keys:
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            return item.strip()
        if item is not None and not isinstance(item, (dict, list)):
            text = str(item).strip()
            if text:
                return text
    return ""


def find_nested_string(value: Any, keys: set[str], depth: int = 0) -> str:
    if depth > 5:
        return ""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys and isinstance(item, str) and item.strip():
                return item.strip()
        for item in value.values():
            found = find_nested_string(item, keys, depth + 1)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = find_nested_string(item, keys, depth + 1)
            if found:
                return found
    return ""


def email_from_token(token: str) -> str:
    token = (token or "").strip()
    if token.count(".") < 2:
        return ""
    try:
        payload = json.loads(base64url_decode(token.split(".")[1]))
    except Exception:
        return ""
    profile = payload.get("https://api.openai.com/profile") if isinstance(payload, dict) else None
    if isinstance(profile, dict):
        email = str(profile.get("email") or "").strip()
        if EMAIL_RE.match(email):
            return email
    email = str(payload.get("email") or "").strip() if isinstance(payload, dict) else ""
    return email if EMAIL_RE.match(email) else ""


def base64url_decode(value: str) -> str:
    padded = value + "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")


def normalize_email(value: str) -> str:
    return str(value or "").strip().lower()
