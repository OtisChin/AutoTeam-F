"""mail.com account-pool mail provider backed by the local SQLite mail_accounts table."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from autotoken.mail.base import MailProvider, normalize_email_addr

logger = logging.getLogger(__name__)


class MailComMailProvider(MailProvider):
    provider_name = "mail.com"

    def __init__(self):
        self._reserved_emails: set[str] = set()
        self._lock = threading.Lock()

    def login(self) -> str:
        from autotoken.storage import mail_accounts

        total = len(mail_accounts.list_mail_accounts())
        if total <= 0:
            raise RuntimeError("mail.com provider 未导入账号。请先在注册账户页导入 mail.com 邮箱池")
        logger.info("[mail.com] 已加载 %d 个 mail.com 账号", total)
        return f"mail.com:{total}"

    def create_temp_email(self, prefix: str | None = None, domain: str | None = None) -> tuple[int | str, str]:
        requested_domain = str(domain or "").strip().lstrip("@").lower()
        if requested_domain and requested_domain != "mail.com":
            raise RuntimeError(f"mail.com provider 不支持 @{requested_domain} 域名")
        from autotoken.storage import mail_accounts

        with self._lock:
            for account in mail_accounts.list_available_registration_accounts():
                email = normalize_email_addr(account.get("email"))
                if not email or email in self._reserved_emails:
                    continue
                self._reserved_emails.add(email)
                logger.info("[mail.com] 选择注册邮箱: %s", email)
                return email, email
        raise RuntimeError("没有可用的 mail.com 账号可用于注册（可能都已注册、已禁用或缺少邮箱密码）")

    def list_accounts(self, size: int = 200) -> list[dict]:
        from autotoken.storage import mail_accounts

        limit = max(1, int(size or 200))
        return [
            {
                "id": row["email"],
                "email": row["email"],
                "accountEmail": row["email"],
                "provider": self.provider_name,
                "status": row.get("status"),
                "check_status": row.get("check_status"),
            }
            for row in mail_accounts.list_mail_accounts()[:limit]
        ]

    def delete_account(self, account_id: int | str) -> dict:
        email = normalize_email_addr(account_id)
        with self._lock:
            self._reserved_emails.discard(email)
        return {"code": 0, "message": "mail.com account retained"}

    def _resolve_account_id(self, value: int | str | None) -> str:
        return normalize_email_addr(value)

    def search_emails_by_recipient(
        self, to_email: str, size: int = 10, account_id: int | str | None = None
    ) -> list[dict]:
        email = normalize_email_addr(account_id or to_email)
        if not email:
            return []
        from autotoken.services.mailcom_webmail import fetch_mailcom_messages
        from autotoken.storage import mail_accounts

        account = mail_accounts.get_mail_account(email)
        if not account:
            logger.warning("[mail.com] 未找到收件人对应 mail.com 账号: %s", email)
            return []
        messages = fetch_mailcom_messages(account, size=max(1, int(size or 10)))
        return [self._to_legacy_dict(account, message) for message in messages[:size]]

    def list_emails(self, account_id: int | str, size: int = 10) -> list[dict]:
        return self.search_emails_by_recipient(str(account_id), size=size, account_id=account_id)

    def delete_emails_for(self, to_email: str) -> int:
        logger.info("[mail.com] 暂不删除邮件: %s", to_email)
        return 0

    @staticmethod
    def _to_legacy_dict(account: dict[str, Any], message: dict[str, Any]) -> dict[str, Any]:
        email = normalize_email_addr(account.get("email"))
        created = message.get("createTime") or message.get("createdAt") or int(time.time())
        try:
            created_at = int(float(created))
        except Exception:
            created_at = int(time.time())
        html = str(message.get("html") or message.get("content") or "")
        text = str(message.get("text") or "")
        return {
            "id": str(message.get("id") or f"{email}:{created_at}"),
            "accountId": email,
            "email": email,
            "toEmail": str(message.get("toEmail") or email),
            "sendEmail": str(message.get("sendEmail") or message.get("from") or ""),
            "subject": str(message.get("subject") or ""),
            "text": text,
            "html": html,
            "content": html or text,
            "createTime": created_at,
            "createdAt": created_at,
            "raw": message,
        }
