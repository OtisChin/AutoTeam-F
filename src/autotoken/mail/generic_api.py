"""Generic API receive-code-link account-pool mail provider.

Each configured mailbox is a pre-owned email address plus a receive-code URL:

    user@example.com----https://example.com/code/token

The receive-code URL may return JSON, HTML, or plain text.  Parsing intentionally
matches the iCloud receive-code provider because many pool vendors expose the
same one-link "show mailbox/code" shape, but this provider accepts any mailbox
domain.
"""

from __future__ import annotations

import logging
import os
import re
import threading

from dataclasses import dataclass

from curl_cffi import requests as curl_requests

from autotoken.core.files import read_lines_file
from autotoken.core.paths import PROJECT_ROOT, resolve_project_config_path
from autotoken.mail.base import normalize_email_addr
from autotoken.mail.icloud import ICloudMailProvider

logger = logging.getLogger(__name__)


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name, default) or "").strip()


@dataclass
class GenericApiAccount:
    email: str
    receive_code_url: str = ""

    def validate(self) -> bool:
        return bool(
            re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", self.email or "", re.IGNORECASE)
            and re.match(r"^https?://", self.receive_code_url or "", re.IGNORECASE)
        )


class GenericApiMailProvider(ICloudMailProvider):
    """邮箱池 + 通用收码链接 provider。

    复用 iCloud receive-code 链接的 JSON/HTML/纯文本解析能力，但不限制
    @icloud.com，适合导入 `邮箱----收码链接` 的任意域名邮箱池。
    """

    provider_name = "generic-api"

    def __init__(self):
        self.accounts = self._load_accounts()
        self._account_index = 0
        self._reserved_emails: set[str] = set()
        self._lock = threading.Lock()
        self.skip_registered = _env("GENERIC_API_SKIP_REGISTERED", "1").lower() not in (
            "0",
            "false",
            "no",
            "off",
        )

    # ------------------------------------------------------------------ config

    def _load_accounts(self) -> list[GenericApiAccount]:
        raw = _env("GENERIC_API_ACCOUNTS")
        file_value = _env("GENERIC_API_ACCOUNTS_FILE")
        if file_value:
            path = resolve_project_config_path(file_value, project_root=PROJECT_ROOT)
            if path and path.exists():
                raw += ("\n" if raw else "") + "\n".join(read_lines_file(path))
        else:
            default_path = PROJECT_ROOT / "data" / "generic_api_accounts.txt"
            if default_path.exists():
                raw += ("\n" if raw else "") + "\n".join(read_lines_file(default_path))

        accounts: list[GenericApiAccount] = []
        for line in raw.replace(";", "\n").splitlines():
            account = self._parse_account_line(line)
            if account and account.validate():
                accounts.append(account)

        seen: set[str] = set()
        unique: list[GenericApiAccount] = []
        for account in accounts:
            key = account.email.lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(account)
        return unique

    @staticmethod
    def _parse_account_line(line: str) -> GenericApiAccount | None:
        value = str(line or "").strip()
        if not value or value.startswith("#"):
            return None
        dash_split = re.split(r"\s*-{2,}\s*", value, maxsplit=1)
        if len(dash_split) >= 2:
            parts = [p.strip() for p in dash_split]
        elif "|" in value:
            parts = [p.strip() for p in value.split("|")]
        elif "," in value:
            parts = [p.strip() for p in value.split(",")]
        else:
            parts = [p.strip() for p in value.split()]

        email = normalize_email_addr(parts[0] if parts else "")
        receive_code_url = parts[1] if len(parts) > 1 else ""
        account = GenericApiAccount(email=email, receive_code_url=receive_code_url)
        return account if account.validate() else None

    # ------------------------------------------------------------------ public

    def login(self) -> str:
        if not self.accounts:
            raise RuntimeError(
                "通用API provider 未配置账号。请设置 GENERIC_API_ACCOUNTS_FILE 或 GENERIC_API_ACCOUNTS；"
                "格式: email@example.com----收码链接"
            )
        logger.info("[generic-api] 已加载 %d 个通用API邮箱", len(self.accounts))
        return f"generic-api:{len(self.accounts)}"

    def create_temp_email(self, prefix: str | None = None, domain: str | None = None) -> tuple[int | str, str]:
        requested_domain = str(domain or "").strip().lstrip("@").lower()
        if not self.accounts:
            self.login()

        used = self._registered_emails() if self.skip_registered else set()
        with self._lock:
            total = len(self.accounts)
            for offset in range(total):
                idx = (self._account_index + offset) % total
                account = self.accounts[idx]
                email = account.email.lower()
                if requested_domain and not email.endswith(f"@{requested_domain}"):
                    continue
                if email in self._reserved_emails:
                    continue
                if self.skip_registered and email in used:
                    continue
                self._account_index = (idx + 1) % total
                self._reserved_emails.add(email)
                logger.info("[generic-api] 选择通用API注册邮箱: %s", account.email)
                return account.email, account.email
        domain_hint = f" @{requested_domain}" if requested_domain else ""
        raise RuntimeError(f"没有可用的通用API邮箱{domain_hint}（可能都已注册/不可用或已被本轮占用）")

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
        logger.info("[generic-api] 通用API provider 不删除真实邮箱，仅释放本地占用: %s", email)
        return {"code": 0, "message": "generic-api account retained"}

    def search_emails_by_recipient(
        self, to_email: str, size: int = 10, account_id: int | str | None = None
    ) -> list[dict]:
        account = self._find_account(to_email=to_email, account_id=account_id)
        if not account:
            logger.warning("[generic-api] 未找到收件人对应通用API收码链接: %s", to_email)
            return []
        try:
            messages = self._fetch_receive_code_messages(account, count=max(1, int(size or 10)))
        except Exception as exc:
            logger.warning("[generic-api] 查询通用API收码链接失败，稍后可重试: %s", exc)
            return []
        messages = messages[: max(1, int(size or 10))]
        if messages:
            try:
                from autotoken.storage.generic_api_pool import cache_mail_message

                cache_mail_message(account.email, messages[0], source="generic-api-live")
            except Exception:
                logger.debug("[generic-api] 缓存最近邮件失败: %s", account.email, exc_info=True)
        return messages

    def delete_emails_for(self, to_email: str) -> int:
        logger.info("[generic-api] 暂不删除邮件: %s", to_email)
        return 0

    # ------------------------------------------------------------------ lookup

    @staticmethod
    def _registered_emails() -> set[str]:
        try:
            from autotoken.storage.accounts import load_accounts
            from autotoken.storage.generic_api_pool import list_registered_emails, list_unavailable_emails

            emails = {normalize_email_addr(a.get("email")) for a in load_accounts() if a.get("email")}
            emails.update(list_registered_emails())
            emails.update(list_unavailable_emails())
            return {email for email in emails if email}
        except Exception:
            logger.debug("[generic-api] 读取本地账号池失败，跳过已注册过滤", exc_info=True)
            return set()

    def _find_account(self, *, to_email: str, account_id: int | str | None = None) -> GenericApiAccount | None:
        wanted = normalize_email_addr(account_id or to_email)
        if not wanted:
            return None
        for account in self.accounts:
            if account.email.lower() == wanted.lower():
                return account
        return None

    # ------------------------------------------------------------------ parse adapters

    def _fetch_receive_code_messages(self, account: GenericApiAccount, *, count: int) -> list[dict]:
        resp = curl_requests.get(
            account.receive_code_url,
            timeout=30,
            impersonate="chrome110",
            headers={"Accept": "text/html,application/json;q=0.9,*/*;q=0.8"},
        )
        if resp.status_code in (404, 410):
            logger.debug("[generic-api] %s 收码链接暂无邮件: HTTP %s", account.email, resp.status_code)
            return []
        if resp.status_code != 200:
            raise RuntimeError(f"generic-api receive-code HTTP {resp.status_code}: {str(resp.text or '')[:200]}")

        text = str(resp.text or "")
        try:
            payload = resp.json()
        except Exception:
            payload = None

        if payload is not None:
            messages = self._messages_from_payload(account, payload)
            if messages:
                return messages[:count]
            if isinstance(payload, dict) and {"email", "code", "mail"} & set(payload.keys()):
                return []
        if not text.strip():
            return []
        messages = self._messages_from_receive_code_html(account, text, page_url=account.receive_code_url, count=count)
        if messages:
            return messages[:count]
        if isinstance(payload, dict) and {"email", "code", "mail"} & set(payload.keys()):
            return []
        return [self._item_to_legacy(account, text, index=0)]

    @classmethod
    def _payload_items(cls, payload) -> list:
        if isinstance(payload, dict) and {"email", "code", "mail"} & set(payload.keys()):
            code = str(payload.get("code") or "").strip()
            mail = payload.get("mail")
            if code:
                return [payload]
            if isinstance(mail, dict):
                return [payload] if cls._dict_has_message_content(mail) else []
            if str(mail or "").strip():
                return [payload]
            return []
        return super()._payload_items(payload)

    @classmethod
    def _item_to_legacy(cls, account: GenericApiAccount, item, *, index: int) -> dict:
        if isinstance(item, dict) and "mail" in item:
            mail = item.get("mail")
            merged = {key: value for key, value in item.items() if key != "mail"}
            if isinstance(mail, dict):
                merged = {**mail, **merged}
            elif str(mail or "").strip():
                merged.setdefault("content", str(mail or ""))
                merged.setdefault("message", str(mail or ""))
                merged.setdefault("body", str(mail or ""))
            if item.get("email"):
                merged.setdefault("toEmail", item.get("email"))
                merged.setdefault("recipient", item.get("email"))
            item = merged

        message = super()._item_to_legacy(account, item, index=index)
        if not message:
            return message
        message["provider"] = cls.provider_name
        message_id = str(message.get("id") or "")
        message["id"] = message_id.replace(":icloud-link:", ":generic-api-link:").replace(":icloud:", ":generic-api:")
        raw = message.get("raw")
        if isinstance(raw, dict):
            source = str(raw.get("source") or "")
            if source.startswith("icloud_"):
                raw["source"] = source.replace("icloud_", "generic_api_", 1)
        return message
