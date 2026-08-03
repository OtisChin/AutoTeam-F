"""iCloud account-pool mail provider backed by receive-code links.

Each configured mailbox is a pre-owned iCloud address plus a third-party
receive-code URL:

    email@icloud.com----https://icloud-api.top/show/.../email@icloud.com
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from base64 import b64decode
from dataclasses import dataclass
from html import unescape
from typing import Any
from urllib.parse import unquote_to_bytes, urljoin

from curl_cffi import requests as curl_requests

from autotoken.core.files import read_lines_file
from autotoken.core.paths import PROJECT_ROOT, resolve_project_config_path
from autotoken.mail.base import MailProvider, html_to_visible_text, normalize_email_addr

logger = logging.getLogger(__name__)


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name, default) or "").strip()


@dataclass
class ICloudAccount:
    email: str
    receive_code_url: str = ""

    def validate(self) -> bool:
        return bool(self.email.endswith("@icloud.com") and self.receive_code_url.startswith(("http://", "https://")))


class ICloudMailProvider(MailProvider):
    provider_name = "icloud"

    def __init__(self):
        self.accounts = self._load_accounts()
        self._account_index = 0
        self._reserved_emails: set[str] = set()
        self._lock = threading.Lock()
        self.skip_registered = _env("ICLOUD_SKIP_REGISTERED", "1").lower() not in ("0", "false", "no", "off")

    # ------------------------------------------------------------------ config

    def _load_accounts(self) -> list[ICloudAccount]:
        raw = _env("ICLOUD_ACCOUNTS")
        file_value = _env("ICLOUD_ACCOUNTS_FILE")
        if file_value:
            path = resolve_project_config_path(file_value, project_root=PROJECT_ROOT)
            if path and path.exists():
                raw += ("\n" if raw else "") + "\n".join(read_lines_file(path))
        else:
            default_path = PROJECT_ROOT / "data" / "icloud_accounts.txt"
            if default_path.exists():
                raw += ("\n" if raw else "") + "\n".join(read_lines_file(default_path))

        accounts: list[ICloudAccount] = []
        for line in raw.replace(";", "\n").splitlines():
            account = self._parse_account_line(line)
            if account and account.validate():
                accounts.append(account)

        seen: set[str] = set()
        unique: list[ICloudAccount] = []
        for account in accounts:
            key = account.email.lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(account)
        return unique

    @staticmethod
    def _parse_account_line(line: str) -> ICloudAccount | None:
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
            parts = [p.strip() for p in value.split()]

        email = normalize_email_addr(parts[0] if parts else "")
        receive_code_url = parts[1] if len(parts) > 1 else ""
        if not email.endswith("@icloud.com") or not re.match(r"^https?://", receive_code_url, re.IGNORECASE):
            return None
        return ICloudAccount(email=email, receive_code_url=receive_code_url)

    # ------------------------------------------------------------------ public

    def login(self) -> str:
        if not self.accounts:
            raise RuntimeError(
                "iCloud provider 未配置账号。请设置 ICLOUD_ACCOUNTS_FILE 或 ICLOUD_ACCOUNTS；"
                "格式: email@icloud.com----收码链接"
            )
        logger.info("[icloud] 已加载 %d 个 iCloud 账号", len(self.accounts))
        return f"icloud:{len(self.accounts)}"

    def create_temp_email(self, prefix: str | None = None, domain: str | None = None) -> tuple[int | str, str]:
        requested_domain = str(domain or "").strip().lstrip("@").lower()
        if requested_domain and requested_domain != "icloud.com":
            raise RuntimeError(f"iCloud provider 不支持 @{requested_domain} 域名")
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
                self._account_index = (idx + 1) % total
                self._reserved_emails.add(email)
                logger.info("[icloud] 选择 iCloud 注册邮箱: %s", account.email)
                return account.email, account.email
        raise RuntimeError("没有可用的 iCloud 账号（可能都已注册或已被本轮占用）")

    def list_accounts(self, size: int = 200) -> list[dict]:
        limit = len(self.accounts) if int(size or 0) <= 0 else max(1, int(size or 200))
        return [
            {
                "id": account.email,
                "email": account.email,
                "accountEmail": account.email,
                "has_receive_code_url": bool(account.receive_code_url),
                "provider": self.provider_name,
            }
            for account in self.accounts[:limit]
        ]

    def delete_account(self, account_id: int | str) -> dict:
        email = normalize_email_addr(account_id)
        with self._lock:
            self._reserved_emails.discard(email)
        logger.info("[icloud] iCloud provider 不删除真实邮箱，仅释放本地占用: %s", email)
        return {"code": 0, "message": "icloud account retained"}

    def search_emails_by_recipient(
        self, to_email: str, size: int = 10, account_id: int | str | None = None
    ) -> list[dict]:
        account = self._find_account(to_email=to_email, account_id=account_id)
        if not account:
            logger.warning("[icloud] 未找到收件人对应 iCloud 收码链接: %s", to_email)
            return []
        try:
            messages = self._fetch_receive_code_messages(account, count=max(1, int(size or 10)))
        except Exception as exc:
            logger.warning("[icloud] 查询 iCloud 收码链接失败，稍后可重试: %s", exc)
            return []
        return messages[: max(1, int(size or 10))]

    def list_emails(self, account_id: int | str, size: int = 10) -> list[dict]:
        return self.search_emails_by_recipient(str(account_id), size=size, account_id=account_id)

    def delete_emails_for(self, to_email: str) -> int:
        logger.info("[icloud] 暂不删除邮件: %s", to_email)
        return 0

    # ------------------------------------------------------------------ lookup

    @staticmethod
    def _registered_emails() -> set[str]:
        try:
            from autotoken.storage.accounts import load_accounts
            from autotoken.storage.icloud_pool import list_unavailable_emails

            emails = {normalize_email_addr(a.get("email")) for a in load_accounts() if a.get("email")}
            emails.update(list_unavailable_emails())
            return emails
        except Exception:
            logger.debug("[icloud] 读取本地账号池失败，跳过已注册过滤", exc_info=True)
            return set()

    def _find_account(self, *, to_email: str, account_id: int | str | None = None) -> ICloudAccount | None:
        wanted = normalize_email_addr(account_id or to_email)
        if not wanted:
            return None
        for account in self.accounts:
            if account.email.lower() == wanted.lower():
                return account
        return None

    # ------------------------------------------------------------------ fetch/parse

    def _fetch_receive_code_messages(self, account: ICloudAccount, *, count: int) -> list[dict]:
        resp = curl_requests.get(
            account.receive_code_url,
            timeout=30,
            impersonate="chrome110",
            headers={"Accept": "text/html,application/json;q=0.9,*/*;q=0.8"},
        )
        if resp.status_code in (404, 410):
            logger.debug("[icloud] %s 收码链接暂无邮件: HTTP %s", account.email, resp.status_code)
            return []
        if resp.status_code != 200:
            raise RuntimeError(f"iCloud receive-code HTTP {resp.status_code}: {str(resp.text or '')[:200]}")

        text = str(resp.text or "")
        try:
            payload = resp.json()
        except Exception:
            payload = None

        if payload is not None:
            messages = self._messages_from_payload(account, payload)
            if messages:
                return messages[:count]
        if not text.strip():
            return []
        messages = self._messages_from_receive_code_html(account, text, page_url=account.receive_code_url, count=count)
        if messages:
            return messages[:count]
        return [self._item_to_legacy(account, text, index=0)]

    def _messages_from_receive_code_html(
        self,
        account: ICloudAccount,
        html: str,
        *,
        page_url: str,
        count: int,
    ) -> list[dict]:
        """Read mail detail JSON from receive-code list pages such as yangyang.website/messages/..."""
        detail_base = self._html_js_string(html, "detailBase")
        detail_suffix = self._html_js_string(html, "detailSuffix")
        if not detail_base or not detail_suffix:
            return []

        message_ids = self._html_message_ids(html)
        messages: list[dict] = []
        for message_id in message_ids[: max(1, int(count or 10))]:
            detail_url = urljoin(page_url, f"{detail_base}{message_id}{detail_suffix}")
            try:
                resp = curl_requests.get(
                    detail_url,
                    timeout=30,
                    impersonate="chrome110",
                    headers={"Accept": "application/json,text/html;q=0.9,*/*;q=0.8"},
                )
            except Exception as exc:
                logger.debug("[icloud] 查询收码详情失败: %s url=%s", exc, detail_url)
                continue
            if resp.status_code != 200:
                logger.debug("[icloud] 收码详情 HTTP %s url=%s", resp.status_code, detail_url)
                continue
            try:
                payload = resp.json()
            except Exception:
                payload = str(resp.text or "")
            for item in self._payload_items(payload):
                message = self._item_to_legacy(account, item, index=len(messages))
                if message:
                    message["raw"] = {
                        **(message.get("raw") if isinstance(message.get("raw"), dict) else {}),
                        "source": "icloud_receive_code_detail_link",
                        "detail_url": detail_url,
                    }
                    messages.append(message)
                    break
        return messages

    @staticmethod
    def _html_js_string(html: str, variable: str) -> str:
        match = re.search(
            rf"\bvar\s+{re.escape(variable)}\s*=\s*(['\"])(.*?)\1",
            str(html or ""),
            re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return ""
        return unescape(match.group(2)).strip()

    @staticmethod
    def _html_message_ids(html: str) -> list[str]:
        ids: list[str] = []
        seen: set[str] = set()
        for pattern in (
            r"\bdata-id\s*=\s*(['\"])(\d+)\1",
            r"href\s*=\s*(['\"])#mail-(\d+)\1",
        ):
            for match in re.finditer(pattern, str(html or ""), re.IGNORECASE):
                value = match.group(2).strip()
                if value and value not in seen:
                    seen.add(value)
                    ids.append(value)
        return ids

    @classmethod
    def _messages_from_payload(cls, account: ICloudAccount, payload: Any) -> list[dict]:
        return [
            message
            for idx, item in enumerate(cls._payload_items(payload))
            if (message := cls._item_to_legacy(account, item, index=idx))
        ]

    @classmethod
    def _payload_items(cls, payload: Any) -> list[Any]:
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return [payload] if str(payload or "").strip() else []

        for key in ("mails", "emails", "messages", "list", "items", "records", "rows"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                nested = cls._payload_items(value)
                if nested:
                    return nested

        data = payload.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            nested = cls._payload_items(data)
            if nested:
                return nested
            if cls._dict_has_message_content(data):
                return [data]

        if cls._dict_has_message_content(payload):
            return [payload]
        return []

    @staticmethod
    def _dict_has_message_content(value: dict[str, Any]) -> bool:
        keys = {
            "subject",
            "title",
            "content",
            "body",
            "message",
            "text",
            "html",
            "code",
            "verification_code",
            "verificationCode",
        }
        return any(str(value.get(key) or "").strip() for key in keys)

    @classmethod
    def _item_to_legacy(cls, account: ICloudAccount, item: Any, *, index: int) -> dict:
        now = int(time.time())
        if isinstance(item, str):
            html = item
            visible = html_to_visible_text(html)
            return {
                "id": f"{account.email}:icloud-link:{index}",
                "accountId": account.email,
                "accountEmail": account.email,
                "email": account.email,
                "toEmail": account.email,
                "sendEmail": "",
                "subject": cls._subject_from_text(visible),
                "text": visible,
                "html": html,
                "content": html,
                "message": html,
                "createTime": now,
                "createdAt": now,
                "provider": cls.provider_name,
                "raw": {"source": "icloud_receive_code_link"},
            }
        if not isinstance(item, dict):
            return {}

        subject = cls._first_text(item, "subject", "mail_subject", "title")
        sender = cls._first_text(item, "from", "mail_from", "sender", "sendEmail", "fromEmail")
        html = cls._decode_data_uri_text(cls._first_text(item, "html", "html_body", "body_html", "mail_html", "raw_html"))
        body = cls._decode_data_uri_text(
            cls._first_text(
                item,
                "text",
                "plain_text",
                "body_text",
                "text_body",
                "mail_text",
                "mail_body",
                "mail_content",
                "content",
                "message",
                "body",
                "snippet",
                "summary",
                "preview",
            )
        )
        code = cls._first_text(
            item,
            "verification_code",
            "verificationCode",
            "verify_code",
            "verifyCode",
            "email_code",
            "mail_code",
            "otp",
            "otp_code",
            "code",
        )
        created = cls._first_text(
            item,
            "received_at",
            "receivedAt",
            "receive_time",
            "receiveTime",
            "created_at",
            "createdAt",
            "create_time",
            "createTime",
            "date",
            "time",
            "timestamp",
        )
        created_at = cls._to_timestamp(created) or now
        text_parts = []
        if code:
            text_parts.append(f"verification code: {code}")
        if body:
            text_parts.append(html_to_visible_text(body))
        if html:
            text_parts.append(html_to_visible_text(html))
        text = "\n".join(part for part in text_parts if part).strip()

        return {
            "id": cls._first_text(item, "id", "message_id", "messageId", "mail_id", "mailId") or f"{account.email}:icloud:{index}",
            "accountId": account.email,
            "accountEmail": account.email,
            "email": account.email,
            "toEmail": cls._first_text(item, "to", "toEmail", "recipient") or account.email,
            "sendEmail": sender,
            "subject": subject,
            "verification_code": code,
            "text": text,
            "html": html,
            "content": html or body or text,
            "message": html or body or text,
            "createTime": created_at,
            "createdAt": created_at,
            "provider": cls.provider_name,
            "raw": item,
        }

    @staticmethod
    def _first_text(item: dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = item.get(key)
            if isinstance(value, bool):
                continue
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""

    @staticmethod
    def _decode_data_uri_text(value: str) -> str:
        text = str(value or "").strip()
        if not text.lower().startswith("data:text/"):
            return text
        header, separator, data = text.partition(",")
        if not separator:
            return text
        try:
            if ";base64" in header.lower():
                return b64decode(data).decode("utf-8", errors="replace")
            return unquote_to_bytes(data).decode("utf-8", errors="replace")
        except Exception:
            return text

    @staticmethod
    def _to_timestamp(value: Any) -> int:
        if value is None:
            return 0
        if isinstance(value, (int, float)):
            ts = float(value)
            return int(ts / 1000) if ts > 10_000_000_000 else int(ts)
        text = str(value or "").strip()
        if not text:
            return 0
        if text.isdigit():
            ts = float(text)
            return int(ts / 1000) if ts > 10_000_000_000 else int(ts)
        return 0

    @staticmethod
    def _subject_from_text(text: str) -> str:
        first_line = next((line.strip() for line in str(text or "").splitlines() if line.strip()), "")
        return first_line[:120]
