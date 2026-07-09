from __future__ import annotations

import base64
import csv
import html
import imaplib
import json
import os
import re
import sqlite3
import ssl
import time
import uuid
from dataclasses import dataclass
from email import message_from_bytes
from email.message import Message
from email.policy import default
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import requests
from cryptography.fernet import Fernet, InvalidToken


EMAIL_RE = re.compile(r"^[^@\s]{1,128}@[^@\s]{1,190}\.[^@\s]{2,32}$")
SIX_DIGIT_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
HTML_TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
GENERIC_VERIFICATION_RE = re.compile(
    r"(?i)verification|verify|security code|one[-\s]*time|passcode|验证码|校验码"
)
STALE_LOCK_SECONDS = 30 * 60

PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "microsoft": {
        "imap_host": "outlook.office365.com",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "scope": "https://outlook.office.com/IMAP.AccessAsUser.All offline_access",
    },
    "yahoo": {
        "imap_host": "imap.mail.yahoo.com",
        "token_url": "https://api.login.yahoo.com/oauth2/get_token",
        "scope": "",
    },
    "gmail": {
        "imap_host": "imap.gmail.com",
        "token_url": "https://oauth2.googleapis.com/token",
        "scope": "",
    },
}


class MailPoolError(Exception):
    pass


class MailPoolNotFound(MailPoolError):
    pass


class MailPoolConflict(MailPoolError):
    pass


class MailPoolOTPTimeout(MailPoolError):
    pass


@dataclass(slots=True)
class ParsedMailbox:
    email: str
    password: str = ""
    client_id: str = ""
    refresh_token: str = ""
    client_secret: str = ""
    provider: str = ""
    imap_host: str = ""
    token_url: str = ""
    scope: str = ""
    include_junk: bool = True
    source: str = "mail_pool_import"

    def credential_dict(self) -> dict[str, Any]:
        return {
            "password": self.password,
            "client_id": self.client_id,
            "refresh_token": self.refresh_token,
            "client_secret": self.client_secret,
            "token_url": self.token_url,
            "scope": self.scope,
            "include_junk": self.include_junk,
        }


@dataclass(slots=True)
class RecentMail:
    mailbox: str
    subject: str
    sender: str
    date: str
    date_ts: float
    snippet: str
    body: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "mailbox": self.mailbox,
            "subject": self.subject,
            "from": self.sender,
            "date": self.date,
            "snippet": self.snippet,
        }


class CredentialCipher:
    def __init__(self, key_path: Path, key: bytes | None = None):
        key_bytes = key or self._load_or_create_key(key_path)
        try:
            self._fernet = Fernet(key_bytes)
        except (TypeError, ValueError) as exc:
            raise MailPoolError("MAIL_POOL_SECRET_KEY 格式无效") from exc

    @staticmethod
    def _load_or_create_key(key_path: Path) -> bytes:
        configured = os.getenv("MAIL_POOL_SECRET_KEY", "").strip()
        if configured:
            return configured.encode("ascii")
        if key_path.exists():
            return key_path.read_bytes().strip()
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        temp_path = key_path.with_suffix(key_path.suffix + ".tmp")
        temp_path.write_bytes(key + b"\n")
        os.chmod(temp_path, 0o600)
        temp_path.replace(key_path)
        os.chmod(key_path, 0o600)
        return key

    def encrypt(self, value: dict[str, Any]) -> bytes:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return self._fernet.encrypt(payload)

    def decrypt(self, value: bytes | str) -> dict[str, Any]:
        token = value.encode("ascii") if isinstance(value, str) else value
        try:
            decoded = self._fernet.decrypt(token)
            result = json.loads(decoded.decode("utf-8"))
        except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MailPoolError("邮箱凭证无法解密") from exc
        if not isinstance(result, dict):
            raise MailPoolError("邮箱凭证格式无效")
        return result


class MailPoolStore:
    def __init__(
        self,
        db_path: Path,
        key_path: Path | None = None,
        secret_key: bytes | None = None,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.cipher = CredentialCipher(
            key_path or self.db_path.with_suffix(".key"),
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
                CREATE TABLE IF NOT EXISTS mail_pool (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                  provider TEXT NOT NULL DEFAULT '',
                  imap_host TEXT NOT NULL DEFAULT '',
                  credentials BLOB NOT NULL,
                  source TEXT NOT NULL DEFAULT '',
                  registered INTEGER NOT NULL DEFAULT 0,
                  registered_at REAL NOT NULL DEFAULT 0,
                  in_use INTEGER NOT NULL DEFAULT 0,
                  locked_at REAL NOT NULL DEFAULT 0,
                  locked_by TEXT NOT NULL DEFAULT '',
                  is_active INTEGER NOT NULL DEFAULT 1,
                  created_at REAL NOT NULL,
                  updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_mail_pool_pick
                  ON mail_pool(registered, is_active, in_use, locked_at, id);

                CREATE TABLE IF NOT EXISTS registration_jobs (
                  id TEXT PRIMARY KEY,
                  mailbox_id INTEGER NOT NULL,
                  owner TEXT NOT NULL DEFAULT '',
                  service TEXT NOT NULL DEFAULT 'verification',
                  status TEXT NOT NULL DEFAULT 'reserved',
                  created_at REAL NOT NULL,
                  updated_at REAL NOT NULL,
                  FOREIGN KEY(mailbox_id) REFERENCES mail_pool(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_registration_jobs_created
                  ON registration_jobs(created_at DESC);
                """
            )

    def import_mailboxes(self, text: str) -> dict[str, Any]:
        rows, skipped, first_error = parse_mailbox_import(text)
        applied = 0
        provider_counts: dict[str, int] = {}
        password_count = 0
        oauth_count = 0

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for row in rows:
                try:
                    self._upsert_mailbox(connection, row)
                except MailPoolError as exc:
                    skipped += 1
                    if not first_error:
                        first_error = str(exc)
                    continue
                applied += 1
                provider_counts[row.provider or "custom"] = provider_counts.get(row.provider or "custom", 0) + 1
                password_count += int(bool(row.password))
                oauth_count += int(bool(row.client_id and row.refresh_token))
            connection.commit()

        return {
            "success": applied > 0 or not rows,
            "applied": applied,
            "parsed": len(rows),
            "skipped": skipped,
            "password_count": password_count,
            "oauth_count": oauth_count,
            "provider_counts": provider_counts,
            "first_error": first_error,
        }

    def _upsert_mailbox(self, connection: sqlite3.Connection, row: ParsedMailbox) -> None:
        if not valid_email(row.email):
            raise MailPoolError(f"邮箱格式无效：{row.email}")
        if not row.password and not (row.client_id and row.refresh_token):
            raise MailPoolError(f"邮箱缺少密码或 OAuth2 凭证：{row.email}")
        if row.client_id.startswith("app_") or row.refresh_token.startswith("rt_"):
            raise MailPoolError(f"检测到非邮箱 OAuth 凭证，已拒绝导入：{row.email}")

        existing = connection.execute(
            "SELECT credentials FROM mail_pool WHERE email = ? LIMIT 1",
            (row.email,),
        ).fetchone()
        credentials = self.cipher.decrypt(existing["credentials"]) if existing else {}
        incoming = row.credential_dict()
        for key, value in incoming.items():
            if value not in ("", None):
                credentials[key] = value
        encrypted = self.cipher.encrypt(credentials)
        now = time.time()
        connection.execute(
            """
            INSERT INTO mail_pool(
              email, provider, imap_host, credentials, source,
              registered, registered_at, in_use, locked_at, locked_by,
              is_active, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 0, 0, 0, 0, '', 1, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
              provider = CASE WHEN excluded.provider != '' THEN excluded.provider ELSE mail_pool.provider END,
              imap_host = CASE WHEN excluded.imap_host != '' THEN excluded.imap_host ELSE mail_pool.imap_host END,
              credentials = excluded.credentials,
              source = CASE WHEN excluded.source != '' THEN excluded.source ELSE mail_pool.source END,
              is_active = 1,
              updated_at = excluded.updated_at
            """,
            (
                row.email,
                row.provider,
                row.imap_host,
                encrypted,
                row.source,
                now,
                now,
            ),
        )

    def list_mailboxes(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, email, provider, imap_host, credentials, source,
                       registered, registered_at, in_use, locked_at, locked_by,
                       is_active, created_at, updated_at
                FROM mail_pool
                WHERE is_active = 1
                ORDER BY id ASC
                """
            ).fetchall()
        return [self._public_mailbox(row) for row in rows]

    def get_mailbox(self, mailbox_id: int) -> dict[str, Any]:
        row, _ = self._mailbox_with_credentials(mailbox_id)
        return self._public_mailbox(row)

    def _mailbox_with_credentials(
        self,
        mailbox_id: int,
    ) -> tuple[sqlite3.Row, dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, email, provider, imap_host, credentials, source,
                       registered, registered_at, in_use, locked_at, locked_by,
                       is_active, created_at, updated_at
                FROM mail_pool
                WHERE id = ?
                LIMIT 1
                """,
                (mailbox_id,),
            ).fetchone()
        if row is None:
            raise MailPoolNotFound("邮箱不存在")
        return row, self.cipher.decrypt(row["credentials"])

    def _mailbox_with_credentials_by_email(
        self,
        email: str,
    ) -> tuple[sqlite3.Row, dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, email, provider, imap_host, credentials, source,
                       registered, registered_at, in_use, locked_at, locked_by,
                       is_active, created_at, updated_at
                FROM mail_pool
                WHERE email = ?
                LIMIT 1
                """,
                (normalize_email(email),),
            ).fetchone()
        if row is None:
            raise MailPoolNotFound("邮箱不存在")
        return row, self.cipher.decrypt(row["credentials"])

    def resolve_mailbox_with_credentials(
        self,
        mailbox_id: int = 0,
        email: str = "",
    ) -> tuple[sqlite3.Row, dict[str, Any]]:
        if mailbox_id > 0:
            return self._mailbox_with_credentials(mailbox_id)
        if normalize_email(email):
            return self._mailbox_with_credentials_by_email(email)
        raise MailPoolNotFound("邮箱不存在")

    def _public_mailbox(self, row: sqlite3.Row) -> dict[str, Any]:
        credentials = self.cipher.decrypt(row["credentials"])
        return {
            "id": row["id"],
            "email": row["email"],
            "provider": row["provider"] or "custom",
            "imap_host": row["imap_host"],
            "source": row["source"],
            "registered": bool(row["registered"]),
            "registered_at": row["registered_at"],
            "in_use": bool(row["in_use"]),
            "locked_at": row["locked_at"],
            "locked_by": row["locked_by"],
            "is_active": bool(row["is_active"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "has_password": bool(str(credentials.get("password") or "").strip()),
            "has_oauth": bool(
                str(credentials.get("client_id") or "").strip()
                and str(credentials.get("refresh_token") or "").strip()
            ),
        }

    def delete_mailbox(self, mailbox_id: int) -> None:
        with self._connect() as connection:
            result = connection.execute("DELETE FROM mail_pool WHERE id = ?", (mailbox_id,))
        if result.rowcount == 0:
            raise MailPoolNotFound("邮箱不存在")

    def reset_mailbox(self, mailbox_id: int) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            result = connection.execute(
                """
                UPDATE mail_pool
                SET registered = 0, registered_at = 0, in_use = 0,
                    locked_at = 0, locked_by = '', is_active = 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (time.time(), mailbox_id),
            )
            if result.rowcount == 0:
                raise MailPoolNotFound("邮箱不存在")
            connection.execute(
                """
                UPDATE registration_jobs
                SET status = 'released', updated_at = ?
                WHERE mailbox_id = ? AND status IN ('reserved', 'verified')
                """,
                (time.time(), mailbox_id),
            )
            connection.commit()

    def list_messages(self, mailbox_id: int, limit: int = 20) -> list[dict[str, Any]]:
        row, credentials = self._mailbox_with_credentials(mailbox_id)
        reader = MailboxReader(row, credentials)
        return [message.public_dict() for message in reader.list_recent_messages(limit)]

    def wait_for_mailbox_otp(
        self,
        mailbox_id: int = 0,
        email: str = "",
        timeout: int = 60,
        issued_after: float = 0,
        service: str = "verification",
        exclude_code: str = "",
    ) -> dict[str, Any]:
        row, credentials = self.resolve_mailbox_with_credentials(mailbox_id, email)
        code = MailboxReader(row, credentials).wait_for_otp(
            timeout=timeout,
            issued_after=issued_after,
            service=service,
            exclude_code=exclude_code,
        )
        return {
            "success": True,
            "email": row["email"],
            "service": service,
            "code": code,
        }

    def create_registration_job(self, owner: str, service: str) -> dict[str, Any]:
        owner = sanitize_text(owner, 64) or "authorized_registration"
        service = sanitize_text(service, 80) or "verification"
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE mail_pool
                SET in_use = 0, locked_at = 0, locked_by = '', updated_at = ?
                WHERE registered = 0 AND in_use = 1
                  AND (locked_at = 0 OR locked_at < ?)
                """,
                (now, now - STALE_LOCK_SECONDS),
            )
            mailbox = connection.execute(
                """
                SELECT id, email, provider, imap_host, credentials, source,
                       registered, registered_at, in_use, locked_at, locked_by,
                       is_active, created_at, updated_at
                FROM mail_pool
                WHERE is_active = 1 AND registered = 0 AND in_use = 0
                ORDER BY id ASC
                LIMIT 1
                """
            ).fetchone()
            if mailbox is None:
                raise MailPoolConflict("邮箱池里没有可用邮箱")
            updated = connection.execute(
                """
                UPDATE mail_pool
                SET in_use = 1, locked_at = ?, locked_by = ?, updated_at = ?
                WHERE id = ? AND registered = 0 AND in_use = 0
                """,
                (now, owner, now, mailbox["id"]),
            )
            if updated.rowcount == 0:
                raise MailPoolConflict("邮箱刚被其他任务占用，请重试")
            job_id = uuid.uuid4().hex
            connection.execute(
                """
                INSERT INTO registration_jobs(id, mailbox_id, owner, service, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'reserved', ?, ?)
                """,
                (job_id, mailbox["id"], owner, service, now, now),
            )
            connection.commit()
        return self.get_registration_job(job_id)

    def list_registration_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT j.id, j.mailbox_id, j.owner, j.service, j.status,
                       j.created_at, j.updated_at,
                       m.email, m.provider
                FROM registration_jobs j
                JOIN mail_pool m ON m.id = j.mailbox_id
                ORDER BY j.created_at DESC
                LIMIT ?
                """,
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_registration_job(self, job_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT j.id, j.mailbox_id, j.owner, j.service, j.status,
                       j.created_at, j.updated_at,
                       m.email, m.provider
                FROM registration_jobs j
                JOIN mail_pool m ON m.id = j.mailbox_id
                WHERE j.id = ?
                LIMIT 1
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            raise MailPoolNotFound("注册任务不存在")
        return dict(row)

    def wait_for_job_otp(
        self,
        job_id: str,
        timeout: int,
        exclude_code: str = "",
    ) -> dict[str, Any]:
        job = self.get_registration_job(job_id)
        if job["status"] not in {"reserved", "verified"}:
            raise MailPoolConflict("当前注册任务不能读取验证码")
        row, credentials = self._mailbox_with_credentials(int(job["mailbox_id"]))
        code = MailboxReader(row, credentials).wait_for_otp(
            timeout=timeout,
            issued_after=float(job["created_at"]),
            service=str(job["service"]),
            exclude_code=exclude_code,
        )
        now = time.time()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE registration_jobs
                SET status = 'verified', updated_at = ?
                WHERE id = ? AND status IN ('reserved', 'verified')
                """,
                (now, job_id),
            )
        return {
            "success": True,
            "job_id": job_id,
            "email": job["email"],
            "service": job["service"],
            "code": code,
        }

    def complete_registration_job(self, job_id: str) -> dict[str, Any]:
        job = self.get_registration_job(job_id)
        if job["status"] == "completed":
            return job
        if job["status"] == "released":
            raise MailPoolConflict("已释放的注册任务不能完成")
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE mail_pool
                SET registered = 1, registered_at = ?, in_use = 0,
                    locked_at = 0, locked_by = '', updated_at = ?
                WHERE id = ?
                """,
                (now, now, job["mailbox_id"]),
            )
            connection.execute(
                """
                UPDATE registration_jobs
                SET status = 'completed', updated_at = ?
                WHERE id = ?
                """,
                (now, job_id),
            )
            connection.commit()
        return self.get_registration_job(job_id)

    def release_registration_job(self, job_id: str) -> dict[str, Any]:
        job = self.get_registration_job(job_id)
        if job["status"] == "completed":
            raise MailPoolConflict("已完成的注册任务不能释放")
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE mail_pool
                SET in_use = 0, locked_at = 0, locked_by = '', updated_at = ?
                WHERE id = ? AND registered = 0
                """,
                (now, job["mailbox_id"]),
            )
            connection.execute(
                """
                UPDATE registration_jobs
                SET status = 'released', updated_at = ?
                WHERE id = ?
                """,
                (now, job_id),
            )
            connection.commit()
        return self.get_registration_job(job_id)


class MailboxReader:
    def __init__(self, row: sqlite3.Row, credentials: dict[str, Any]):
        self.email = str(row["email"])
        self.provider = normalize_provider(str(row["provider"] or ""), self.email)
        defaults = PROVIDER_DEFAULTS.get(self.provider, {})
        self.host = str(row["imap_host"] or defaults.get("imap_host") or "").strip()
        self.password = str(credentials.get("password") or "").strip()
        self.client_id = str(credentials.get("client_id") or "").strip()
        self.refresh_token = str(credentials.get("refresh_token") or "").strip()
        self.client_secret = str(credentials.get("client_secret") or "").strip()
        self.token_url = str(credentials.get("token_url") or defaults.get("token_url") or "").strip()
        self.scope = str(credentials.get("scope") or defaults.get("scope") or "").strip()
        self.include_junk = bool(credentials.get("include_junk", True))

    def _login(self) -> imaplib.IMAP4_SSL:
        if not self.host:
            raise MailPoolError("邮箱缺少 IMAP Host")
        context = ssl.create_default_context()
        client = imaplib.IMAP4_SSL(self.host, 993, ssl_context=context, timeout=20)
        try:
            if self.client_id and self.refresh_token:
                access_token = self._refresh_access_token()
                auth = f"user={self.email}\x01auth=Bearer {access_token}\x01\x01".encode()
                client.authenticate("XOAUTH2", lambda _: auth)
            elif self.password:
                client.login(self.email, self.password)
            else:
                raise MailPoolError("邮箱缺少密码或 OAuth2 凭证")
        except Exception:
            try:
                client.logout()
            except Exception:
                pass
            raise
        return client

    def _refresh_access_token(self) -> str:
        if not self.token_url:
            raise MailPoolError("邮箱 OAuth2 缺少 token_url")
        form = {
            "client_id": self.client_id,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
        }
        if self.scope:
            form["scope"] = self.scope
        headers: dict[str, str] = {}
        if self.provider == "yahoo" and self.client_secret:
            raw = f"{self.client_id}:{self.client_secret}".encode()
            headers["Authorization"] = f"Basic {base64.b64encode(raw).decode()}"
        elif self.client_secret:
            form["client_secret"] = self.client_secret
        try:
            response = requests.post(
                self.token_url,
                data=form,
                headers=headers,
                timeout=20,
            )
        except requests.RequestException as exc:
            raise MailPoolError(f"刷新邮箱 access_token 失败：{exc}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise MailPoolError("刷新邮箱 access_token 返回非 JSON") from exc
        if not response.ok:
            detail = payload.get("error_description") or payload.get("error") or response.status_code
            raise MailPoolError(f"刷新邮箱 access_token 失败：{detail}")
        access_token = str(payload.get("access_token") or "").strip()
        if not access_token:
            raise MailPoolError("刷新邮箱 access_token 未返回 access_token")
        return access_token

    def list_recent_messages(self, limit: int = 20) -> list[RecentMail]:
        limit = max(1, min(limit, 80))
        client = self._login()
        try:
            messages: list[RecentMail] = []
            for mailbox in self._mailboxes(client):
                try:
                    messages.extend(self._messages_from_mailbox(client, mailbox, limit))
                except (imaplib.IMAP4.error, MailPoolError):
                    continue
            messages.sort(key=lambda item: item.date_ts, reverse=True)
            return messages[:limit]
        finally:
            try:
                client.logout()
            except Exception:
                pass

    def _mailboxes(self, client: imaplib.IMAP4_SSL) -> list[str]:
        mailboxes = ["INBOX"]
        if not self.include_junk:
            return mailboxes
        status, rows = client.list()
        if status != "OK":
            return mailboxes
        for raw in rows or []:
            text = raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw)
            match = re.search(r'(?:"([^"]+)"|([^\s]+))\s*$', text)
            name = (match.group(1) or match.group(2)) if match else ""
            lower = name.lower()
            if name and any(word in lower for word in ("junk", "spam", "bulk", "垃圾")):
                mailboxes.append(name)
        return list(dict.fromkeys(mailboxes))

    def _messages_from_mailbox(
        self,
        client: imaplib.IMAP4_SSL,
        mailbox: str,
        limit: int,
    ) -> list[RecentMail]:
        status, _ = client.select(f'"{mailbox}"', readonly=True)
        if status != "OK":
            return []
        status, data = client.search(None, "ALL")
        if status != "OK" or not data or not data[0]:
            return []
        message_ids = data[0].split()[-limit:]
        output: list[RecentMail] = []
        for message_id in reversed(message_ids):
            status, payload = client.fetch(message_id, "(RFC822)")
            if status != "OK":
                continue
            raw_message = next(
                (
                    part[1]
                    for part in payload or []
                    if isinstance(part, tuple) and len(part) > 1 and isinstance(part[1], bytes)
                ),
                b"",
            )
            if raw_message:
                output.append(parse_mail_message(raw_message, mailbox))
        return output

    def wait_for_otp(
        self,
        timeout: int,
        issued_after: float,
        service: str,
        exclude_code: str = "",
    ) -> str:
        timeout = max(5, min(int(timeout), 180))
        cutoff = issued_after - 3 if issued_after > 0 else time.time() - 5
        deadline = time.time() + timeout
        while time.time() < deadline:
            messages = self.list_recent_messages(80)
            for message in messages:
                if message.date_ts and message.date_ts < cutoff:
                    continue
                if not looks_like_service(message, service):
                    continue
                for code in SIX_DIGIT_RE.findall(f"{message.subject}\n{message.body}"):
                    if code and code != exclude_code:
                        return code
            time.sleep(5)
        raise MailPoolOTPTimeout(f"邮箱验证码读取超时：{self.email}")


def parse_mail_message(raw: bytes, mailbox: str) -> RecentMail:
    message = message_from_bytes(raw, policy=default)
    subject = str(message.get("Subject") or "").strip()
    sender = str(message.get("From") or "").strip()
    body = extract_message_text(message)
    date_ts = 0.0
    date_value = ""
    try:
        parsed = parsedate_to_datetime(str(message.get("Date") or ""))
        if parsed is not None:
            date_ts = parsed.timestamp()
            date_value = parsed.isoformat()
    except (TypeError, ValueError, OverflowError):
        pass
    return RecentMail(
        mailbox=mailbox,
        subject=subject,
        sender=sender,
        date=date_value,
        date_ts=date_ts,
        snippet=truncate_text(body, 400),
        body=body,
    )


def extract_message_text(message: Message) -> str:
    parts: list[str] = []
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if str(part.get("Content-Disposition") or "").lower().startswith("attachment"):
                continue
            content_type = part.get_content_type()
            if content_type not in {"text/plain", "text/html"}:
                continue
            try:
                content = part.get_content()
            except Exception:
                payload = part.get_payload(decode=True) or b""
                content = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
            parts.append(strip_html(str(content)) if content_type == "text/html" else str(content))
    else:
        try:
            content = message.get_content()
        except Exception:
            payload = message.get_payload(decode=True) or b""
            content = payload.decode(message.get_content_charset() or "utf-8", errors="replace")
        parts.append(strip_html(str(content)) if message.get_content_type() == "text/html" else str(content))
    return WHITESPACE_RE.sub(" ", "\n".join(parts)).strip()


def strip_html(value: str) -> str:
    return WHITESPACE_RE.sub(" ", HTML_TAG_RE.sub(" ", html.unescape(value))).strip()


def looks_like_service(message: RecentMail, service: str) -> bool:
    haystack = f"{message.subject}\n{message.body}".lower()
    normalized = sanitize_text(service, 80).lower()
    if normalized and normalized not in {"generic", "verification", "verify"}:
        return normalized in haystack
    return bool(GENERIC_VERIFICATION_RE.search(haystack))


def parse_mailbox_import(text: str) -> tuple[list[ParsedMailbox], int, str]:
    value = str(text or "").strip()
    if not value:
        return [], 0, ""
    if value.startswith("{") or value.startswith("["):
        parsed = parse_mailbox_json(value)
        if parsed is not None:
            return parsed

    rows: list[ParsedMailbox] = []
    skipped = 0
    first_error = ""
    for line_number, raw_line in enumerate(value.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            row = parse_mailbox_line(line)
            validate_parsed_mailbox(row)
            rows.append(row)
        except MailPoolError as exc:
            skipped += 1
            if not first_error:
                first_error = f"第 {line_number} 行：{exc}"
    return deduplicate_mailboxes(rows), skipped, first_error


def parse_mailbox_json(value: str) -> tuple[list[ParsedMailbox], int, str] | None:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return None
    items = payload if isinstance(payload, list) else [payload]
    rows: list[ParsedMailbox] = []
    skipped = 0
    first_error = ""
    for index, item in enumerate(items, start=1):
        try:
            if not isinstance(item, dict):
                raise MailPoolError("不是 JSON 对象")
            row = mailbox_from_mapping(item)
            validate_parsed_mailbox(row)
            rows.append(row)
        except MailPoolError as exc:
            skipped += 1
            if not first_error:
                first_error = f"第 {index} 项：{exc}"
    return deduplicate_mailboxes(rows), skipped, first_error


def mailbox_from_mapping(item: dict[str, Any]) -> ParsedMailbox:
    nested = next(
        (
            value
            for key in ("mailbox", "mail", "email_credentials", "imap", "outlook", "yahoo")
            if isinstance((value := item.get(key)), dict)
        ),
        None,
    )
    source = nested or item
    email = first_text(
        source,
        "email",
        "mail_email",
        "email_address",
        "mailbox_email",
        "outlook_email",
        "yahoo_email",
        "imap_email",
        "username",
    )
    provider = normalize_provider(
        first_text(source, "provider", "mail_provider"),
        email,
    )
    defaults = PROVIDER_DEFAULTS.get(provider, {})
    return ParsedMailbox(
        email=normalize_email(email),
        password=first_text(
            source,
            "password",
            "mail_password",
            "email_password",
            "mailbox_password",
            "outlook_password",
            "yahoo_password",
            "imap_password",
        ),
        client_id=first_text(
            source,
            "client_id",
            "mail_client_id",
            "email_client_id",
            "mailbox_client_id",
            "outlook_client_id",
            "yahoo_client_id",
            "imap_client_id",
        ),
        refresh_token=first_text(
            source,
            "refresh_token",
            "mail_refresh_token",
            "email_refresh_token",
            "mailbox_refresh_token",
            "outlook_refresh_token",
            "yahoo_refresh_token",
            "imap_refresh_token",
        ),
        client_secret=first_text(
            source,
            "client_secret",
            "mail_client_secret",
            "email_client_secret",
            "mailbox_client_secret",
            "outlook_client_secret",
            "yahoo_client_secret",
            "imap_client_secret",
        ),
        provider=provider,
        imap_host=first_text(source, "imap_host", "host") or defaults.get("imap_host", ""),
        token_url=first_text(source, "token_url", "oauth_token_url") or defaults.get("token_url", ""),
        scope=first_text(source, "scope", "oauth_scope") or defaults.get("scope", ""),
        include_junk=bool(source.get("include_junk", True)),
        source="mail_pool_import",
    )


def parse_mailbox_line(line: str) -> ParsedMailbox:
    if "----" in line:
        parts = [part.strip() for part in line.split("----")]
    elif "," in line:
        try:
            parts = [part.strip() for part in next(csv.reader([line]))]
        except (csv.Error, StopIteration) as exc:
            raise MailPoolError("CSV 格式错误") from exc
    else:
        parts = line.split(maxsplit=1)

    if len(parts) < 2:
        raise MailPoolError("支持 email----password 或 email----password----client_id----refresh_token")
    email = normalize_email(parts[0])
    password = parts[1] if len(parts) > 1 else ""
    client_id = parts[2] if len(parts) > 2 else ""
    refresh_token = parts[3] if len(parts) > 3 else ""
    client_secret = "----".join(parts[4:]).strip() if len(parts) > 4 else ""
    provider = normalize_provider("", email)
    defaults = PROVIDER_DEFAULTS.get(provider, {})
    return ParsedMailbox(
        email=email,
        password=password,
        client_id=client_id,
        refresh_token=refresh_token,
        client_secret=client_secret,
        provider=provider,
        imap_host=defaults.get("imap_host", ""),
        token_url=defaults.get("token_url", ""),
        scope=defaults.get("scope", ""),
    )


def validate_parsed_mailbox(row: ParsedMailbox) -> None:
    if not valid_email(row.email):
        raise MailPoolError("邮箱格式无效")
    if not row.password and not (row.client_id and row.refresh_token):
        raise MailPoolError("缺少密码或 OAuth2 凭证")
    if not row.imap_host:
        raise MailPoolError("无法识别 IMAP Host，请使用 JSON 提供 imap_host")


def deduplicate_mailboxes(rows: list[ParsedMailbox]) -> list[ParsedMailbox]:
    by_email: dict[str, ParsedMailbox] = {}
    for row in rows:
        by_email[row.email] = row
    return list(by_email.values())


def normalize_provider(provider: str, email: str) -> str:
    value = str(provider or "").strip().lower()
    aliases = {
        "outlook": "microsoft",
        "hotmail": "microsoft",
        "live": "microsoft",
        "msn": "microsoft",
        "ymail": "yahoo",
        "google": "gmail",
    }
    if value:
        return aliases.get(value, value)
    domain = normalize_email(email).partition("@")[2]
    if domain in {"outlook.com", "hotmail.com", "live.com", "msn.com"}:
        return "microsoft"
    if domain in {"yahoo.com", "ymail.com"}:
        return "yahoo"
    if domain in {"gmail.com", "googlemail.com"}:
        return "gmail"
    return "custom"


def normalize_email(value: str) -> str:
    return str(value or "").strip().lower()


def valid_email(value: str) -> bool:
    return bool(EMAIL_RE.fullmatch(normalize_email(value)))


def sanitize_text(value: str, limit: int) -> str:
    return str(value or "").strip()[:limit]


def first_text(mapping: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = mapping.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def truncate_text(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit]
