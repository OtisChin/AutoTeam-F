"""Outlook account-pool mail provider.

This ports the useful parts of codex-console's Outlook registration mode into
AutoTeam's `MailProvider` interface: pick a pre-owned Outlook/Hotmail mailbox
for registration, then poll that same mailbox for OpenAI verification mail.
"""

from __future__ import annotations

import email as email_pkg
import imaplib
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from curl_cffi import requests as curl_requests

from autoteam.mail.base import MailProvider, html_to_visible_text, normalize_email_addr
from autoteam.paths import PROJECT_ROOT
from autoteam.textio import read_text

logger = logging.getLogger(__name__)


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name, default) or "").strip()


@dataclass
class OutlookAccount:
    email: str
    password: str = ""
    client_id: str = ""
    refresh_token: str = ""

    def has_oauth(self) -> bool:
        return bool(self.client_id and self.refresh_token)

    def validate(self) -> bool:
        return bool(self.email and (self.password or self.has_oauth()))


@dataclass
class OutlookMessage:
    id: str
    subject: str
    sender: str
    recipients: list[str]
    text: str
    html: str
    received_at: int
    raw: dict[str, Any]


class OutlookMailProvider(MailProvider):
    provider_name = "outlook"

    IMAP_OLD_HOST = "outlook.office365.com"
    IMAP_NEW_HOST = "outlook.live.com"
    IMAP_PORT = 993
    SEARCH_MAILBOXES = (
        "INBOX",
        "Junk",
        "Junk Email",
        "Junk E-mail",
        "Spam",
        "Deleted Items",
        "Trash",
        "Clutter",
        "Archive",
    )
    GRAPH_FOLDERS = ("inbox", "junkemail", "deleteditems", "archive")
    TOKEN_ENDPOINTS = {
        "imap_old": ("https://login.live.com/oauth20_token.srf", ""),
        "imap_new": (
            "https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
            "https://outlook.office.com/IMAP.AccessAsUser.All offline_access",
        ),
        "graph_api": ("https://login.microsoftonline.com/common/oauth2/v2.0/token", "https://graph.microsoft.com/.default"),
    }

    _token_cache: dict[tuple[str, str], dict[str, Any]] = {}
    _token_lock = threading.Lock()

    def __init__(self):
        self.accounts = self._load_accounts()
        self._account_index = 0
        self._reserved_emails: set[str] = set()
        self._lock = threading.Lock()
        self.provider_priority = [
            p.strip().lower()
            for p in _env("OUTLOOK_PROVIDER_PRIORITY", "imap_old,imap_new,graph_api").split(",")
            if p.strip()
        ]
        self.proxy_url = _env("OUTLOOK_PROXY_URL")
        self.skip_registered = _env("OUTLOOK_SKIP_REGISTERED", "1").lower() not in (
            "0",
            "false",
            "no",
            "off",
        )

    # ------------------------------------------------------------------ config

    def _load_accounts(self) -> list[OutlookAccount]:
        raw = _env("OUTLOOK_ACCOUNTS")
        file_value = _env("OUTLOOK_ACCOUNTS_FILE")
        if file_value:
            path = Path(file_value)
            if not path.is_absolute():
                path = PROJECT_ROOT / path
            if path.exists():
                raw += ("\n" if raw else "") + read_text(path)
        else:
            default_path = PROJECT_ROOT / "data" / "outlook_accounts.txt"
            if default_path.exists():
                raw += ("\n" if raw else "") + read_text(default_path)

        accounts: list[OutlookAccount] = []
        for line in raw.replace(";", "\n").splitlines():
            account = self._parse_account_line(line)
            if account and account.validate():
                accounts.append(account)

        seen: set[str] = set()
        unique: list[OutlookAccount] = []
        for account in accounts:
            key = account.email.lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(account)
        return unique

    @staticmethod
    def _parse_account_line(line: str) -> OutlookAccount | None:
        value = str(line or "").strip()
        if not value or value.startswith("#"):
            return None
        if "----" in value:
            parts = [p.strip() for p in value.split("----")]
        elif "|" in value:
            parts = [p.strip() for p in value.split("|")]
        elif "," in value:
            parts = [p.strip() for p in value.split(",")]
        else:
            parts = [p.strip() for p in value.split(":")]

        email = normalize_email_addr(parts[0] if parts else "")
        if "@" not in email:
            return None
        password = parts[1] if len(parts) > 1 else ""
        client_id = parts[2] if len(parts) > 2 else ""
        refresh_token = parts[3] if len(parts) > 3 else ""
        if OutlookMailProvider._looks_like_refresh_token(client_id) and OutlookMailProvider._looks_like_client_id(refresh_token):
            client_id, refresh_token = refresh_token, client_id
        if not client_id and refresh_token:
            client_id = _env("OUTLOOK_DEFAULT_CLIENT_ID", "24d9a0ed-8787-4584-883c-2fd79308940a")
        return OutlookAccount(email=email, password=password, client_id=client_id, refresh_token=refresh_token)

    @staticmethod
    def _looks_like_client_id(value: str) -> bool:
        return bool(re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", str(value or "").strip()))

    @staticmethod
    def _looks_like_refresh_token(value: str) -> bool:
        token = str(value or "").strip()
        return token.startswith("M.") or len(token) > 80

    # ------------------------------------------------------------------ public

    def login(self) -> str:
        if not self.accounts:
            raise RuntimeError(
                "Outlook provider 未配置账号。请设置 OUTLOOK_ACCOUNTS_FILE 或 OUTLOOK_ACCOUNTS；"
                "格式: email----mail_password、email----mail_password----client_id----refresh_token，"
                "或 email|mail_password|refresh_token|client_id"
            )
        logger.info("[outlook] 已加载 %d 个 Outlook 账号", len(self.accounts))
        return f"outlook:{len(self.accounts)}"

    def create_temp_email(self, prefix: str | None = None, domain: str | None = None) -> tuple[int | str, str]:
        if not self.accounts:
            self.login()

        registered = self._registered_emails() if self.skip_registered else set()
        with self._lock:
            total = len(self.accounts)
            for offset in range(total):
                idx = (self._account_index + offset) % total
                account = self.accounts[idx]
                email = account.email.lower()
                if email in self._reserved_emails:
                    continue
                if self.skip_registered and email in registered:
                    continue
                if domain and not email.endswith("@" + str(domain).strip().lstrip("@").lower()):
                    continue
                self._account_index = (idx + 1) % total
                self._reserved_emails.add(email)
                logger.info("[outlook] 选择 Outlook 注册邮箱: %s", account.email)
                return account.email, account.email

        raise RuntimeError("没有可用的 Outlook 账号可用于注册（可能都已注册或已被本轮占用）")

    def list_accounts(self, size: int = 200) -> list[dict]:
        result = []
        for account in self.accounts[: max(1, int(size or 200))]:
            result.append(
                {
                    "id": account.email,
                    "email": account.email,
                    "accountEmail": account.email,
                    "has_oauth": account.has_oauth(),
                    "provider": self.provider_name,
                }
            )
        return result

    def delete_account(self, account_id: int | str) -> dict:
        email = normalize_email_addr(account_id)
        with self._lock:
            self._reserved_emails.discard(email)
        logger.info("[outlook] Outlook provider 不会删除真实邮箱账号，仅释放本地占用: %s", account_id)
        return {"code": 0, "message": "outlook account retained"}

    def search_emails_by_recipient(
        self, to_email: str, size: int = 10, account_id: int | str | None = None
    ) -> list[dict]:
        account = self._find_account(account_id or to_email)
        if not account:
            logger.warning("[outlook] 未找到收件人对应 Outlook 账号: %s", to_email)
            return []

        messages = self._fetch_recent_messages(account, count=max(1, int(size or 10)))
        target = normalize_email_addr(to_email)
        filtered = [
            msg
            for msg in messages
            if not target
            or account.email.lower() == target
            or any(normalize_email_addr(r) == target for r in msg.recipients)
        ]
        return [self._to_legacy_dict(account, msg) for msg in filtered[:size]]

    def list_emails(self, account_id: int | str, size: int = 10) -> list[dict]:
        return self.search_emails_by_recipient(str(account_id), size=size, account_id=account_id)

    def delete_emails_for(self, to_email: str) -> int:
        logger.info("[outlook] Outlook provider 暂不删除邮件: %s", to_email)
        return 0

    # ------------------------------------------------------------------ lookup

    @staticmethod
    def _registered_emails() -> set[str]:
        try:
            from autoteam.accounts import load_accounts

            return {normalize_email_addr(a.get("email")) for a in load_accounts() if a.get("email")}
        except Exception:
            logger.debug("[outlook] 读取本地账号池失败，跳过已注册过滤", exc_info=True)
            return set()

    def _find_account(self, value: int | str | None) -> OutlookAccount | None:
        target = normalize_email_addr(value)
        for account in self.accounts:
            if account.email.lower() == target:
                return account
        return None

    # ------------------------------------------------------------------ fetch

    def _fetch_recent_messages(self, account: OutlookAccount, *, count: int) -> list[OutlookMessage]:
        errors: list[str] = []
        for provider in self.provider_priority:
            try:
                if provider == "graph_api":
                    if not account.has_oauth():
                        continue
                    messages = self._fetch_graph_messages(account, count=count)
                elif provider == "imap_new":
                    if not account.has_oauth():
                        continue
                    messages = self._fetch_imap_messages(account, host=self.IMAP_NEW_HOST, provider="imap_new", count=count)
                else:
                    messages = self._fetch_imap_messages(account, host=self.IMAP_OLD_HOST, provider="imap_old", count=count)
                if messages:
                    logger.info("[outlook] %s 通过 %s 获取到 %d 封邮件", account.email, provider, len(messages))
                    return messages
            except Exception as exc:
                errors.append(f"{provider}: {exc}")
                logger.warning("[outlook] %s 获取邮件失败(%s): %s", account.email, provider, exc)
        if errors:
            logger.debug("[outlook] %s 所有 provider 均失败: %s", account.email, "; ".join(errors))
        return []

    def _fetch_imap_messages(self, account: OutlookAccount, *, host: str, provider: str, count: int) -> list[OutlookMessage]:
        conn: imaplib.IMAP4_SSL | None = None
        try:
            conn = imaplib.IMAP4_SSL(host, self.IMAP_PORT, timeout=30)
            authenticated = False
            if account.has_oauth():
                token = self._get_access_token(account, provider)
                if token:
                    auth_string = f"user={account.email}\x01auth=Bearer {token}\x01\x01"
                    try:
                        conn.authenticate("XOAUTH2", lambda _: auth_string.encode("utf-8"))
                        authenticated = True
                    except Exception:
                        logger.debug("[outlook] %s XOAUTH2 认证失败，尝试密码认证", account.email, exc_info=True)
                        self._clear_token(account, provider)
            if not authenticated:
                if provider == "imap_new" or not account.password:
                    return []
                conn.login(account.email, account.password)

            messages: list[OutlookMessage] = []
            seen: set[str] = set()
            for mailbox in self.SEARCH_MAILBOXES:
                try:
                    status, _ = conn.select(mailbox, readonly=True)
                    if status != "OK":
                        continue
                    status, data = conn.search(None, "ALL")
                    if status != "OK" or not data or not data[0]:
                        continue
                    for msg_id in data[0].split()[-count:][::-1]:
                        status, raw_data = conn.fetch(msg_id, "(RFC822)")
                        if status != "OK" or not raw_data:
                            continue
                        raw = next((part[1] for part in raw_data if isinstance(part, tuple) and len(part) > 1), b"")
                        if not raw:
                            continue
                        msg = self._parse_raw_email(raw, fallback_id=f"{mailbox}:{msg_id.decode(errors='ignore')}")
                        if msg.id in seen:
                            continue
                        seen.add(msg.id)
                        messages.append(msg)
                except Exception:
                    logger.debug("[outlook] %s 跳过邮箱文件夹 %s", account.email, mailbox, exc_info=True)
            return messages
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
                try:
                    conn.logout()
                except Exception:
                    pass

    def _fetch_graph_messages(self, account: OutlookAccount, *, count: int) -> list[OutlookMessage]:
        token = self._get_access_token(account, "graph_api")
        if not token:
            return []
        proxies = self._proxies()
        result: list[OutlookMessage] = []
        seen: set[str] = set()
        for folder in self.GRAPH_FOLDERS:
            resp = curl_requests.get(
                f"https://graph.microsoft.com/v1.0/me/mailFolders/{folder}/messages",
                params={
                    "$top": count,
                    "$select": "id,subject,from,toRecipients,receivedDateTime,bodyPreview,body",
                    "$orderby": "receivedDateTime desc",
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Prefer": "outlook.body-content-type='text'",
                },
                proxies=proxies,
                timeout=30,
                impersonate="chrome110",
            )
            if resp.status_code == 401:
                self._clear_token(account, "graph_api")
                return []
            if resp.status_code != 200:
                continue
            for item in (resp.json() or {}).get("value", []):
                msg = self._parse_graph_message(item)
                if msg.id in seen:
                    continue
                seen.add(msg.id)
                result.append(msg)
        return result

    # ------------------------------------------------------------------ tokens

    def _get_access_token(self, account: OutlookAccount, provider: str) -> str:
        key = (account.email.lower(), provider)
        with self._token_lock:
            cached = self._token_cache.get(key)
            if cached and time.time() < cached.get("expires_at", 0) - 120:
                return str(cached.get("access_token") or "")

        token_url, scope = self.TOKEN_ENDPOINTS.get(provider, self.TOKEN_ENDPOINTS["imap_old"])
        data = {
            "client_id": account.client_id,
            "refresh_token": account.refresh_token,
            "grant_type": "refresh_token",
        }
        if scope:
            data["scope"] = scope
        resp = curl_requests.post(
            token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            proxies=self._proxies(),
            timeout=30,
            impersonate="chrome110",
        )
        if resp.status_code != 200:
            logger.warning("[outlook] %s token 刷新失败(%s): HTTP %s %s", account.email, provider, resp.status_code, resp.text[:200])
            return ""
        payload = resp.json() or {}
        token = str(payload.get("access_token") or "")
        if token:
            with self._token_lock:
                self._token_cache[key] = {
                    "access_token": token,
                    "expires_at": time.time() + int(payload.get("expires_in") or 3600),
                }
        return token

    def _clear_token(self, account: OutlookAccount, provider: str) -> None:
        with self._token_lock:
            self._token_cache.pop((account.email.lower(), provider), None)

    def _proxies(self) -> dict[str, str] | None:
        if not self.proxy_url:
            return None
        return {"http": self.proxy_url, "https": self.proxy_url}

    # ------------------------------------------------------------------ parsing

    @staticmethod
    def _decode_header(value: Any) -> str:
        if not value:
            return ""
        try:
            return str(make_header(decode_header(str(value))))
        except Exception:
            return str(value)

    @classmethod
    def _parse_raw_email(cls, raw: bytes, *, fallback_id: str) -> OutlookMessage:
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        msg = email_pkg.message_from_bytes(raw)
        subject = cls._decode_header(msg.get("Subject", ""))
        sender = cls._decode_header(msg.get("From", ""))
        recipients = [
            cls._decode_header(value)
            for value in (msg.get("To", ""), msg.get("Delivered-To", ""), msg.get("X-Original-To", ""))
            if value
        ]
        text, html = cls._extract_body(msg)
        received_at = 0
        try:
            received_at = int(parsedate_to_datetime(cls._decode_header(msg.get("Date", ""))).timestamp())
        except Exception:
            pass
        message_id = str(msg.get("Message-ID") or fallback_id).strip()
        return OutlookMessage(
            id=message_id,
            subject=subject,
            sender=sender,
            recipients=recipients,
            text=text or html_to_visible_text(html),
            html=html,
            received_at=received_at,
            raw={"message_id": message_id},
        )

    @staticmethod
    def _extract_body(msg) -> tuple[str, str]:
        texts: list[str] = []
        htmls: list[str] = []
        parts = msg.walk() if msg.is_multipart() else [msg]
        for part in parts:
            content_type = part.get_content_type()
            if content_type not in ("text/plain", "text/html"):
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            try:
                value = payload.decode(charset, errors="replace")
            except LookupError:
                value = payload.decode("utf-8", errors="replace")
            if content_type == "text/html":
                htmls.append(value)
            else:
                texts.append(value)
        return "\n".join(texts).strip(), "\n".join(htmls).strip()

    @staticmethod
    def _parse_graph_message(item: dict) -> OutlookMessage:
        sender = ((item.get("from") or {}).get("emailAddress") or {}).get("address") or ""
        recipients = [
            ((recipient.get("emailAddress") or {}).get("address") or "")
            for recipient in (item.get("toRecipients") or [])
        ]
        received_at = 0
        try:
            from datetime import datetime

            received_at = int(datetime.fromisoformat(str(item.get("receivedDateTime") or "").replace("Z", "+00:00")).timestamp())
        except Exception:
            pass
        body = (item.get("body") or {}).get("content") or ""
        return OutlookMessage(
            id=str(item.get("id") or ""),
            subject=str(item.get("subject") or ""),
            sender=str(sender),
            recipients=[r for r in recipients if r],
            text=str(item.get("bodyPreview") or body),
            html="",
            received_at=received_at,
            raw=item,
        )

    @staticmethod
    def _to_legacy_dict(account: OutlookAccount, msg: OutlookMessage) -> dict:
        text = msg.text or html_to_visible_text(msg.html)
        return {
            "id": msg.id,
            "accountId": account.email,
            "accountEmail": account.email,
            "toEmail": account.email,
            "sendEmail": msg.sender,
            "subject": msg.subject,
            "text": text,
            "content": msg.html or text,
            "html": msg.html,
            "message": msg.html or text,
            "createTime": msg.received_at,
            "createdAt": msg.received_at,
            "raw": msg.raw,
        }


def _dump_accounts_for_debug(accounts: list[OutlookAccount]) -> str:
    """Small helper kept for tests and log debugging."""
    return json.dumps([{"email": a.email, "has_oauth": a.has_oauth()} for a in accounts], ensure_ascii=False)
