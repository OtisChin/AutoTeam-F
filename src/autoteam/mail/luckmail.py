"""LuckMail purchased-token mail provider.

LuckMail has two useful modes:
- purchased mailboxes: `email----tok_xxx`, then query code by token without IMAP
- API-key purchase: buy a mailbox through OpenAPI, then use the returned token

This provider is intentionally token-first because purchased LuckMail accounts do
not need, and often do not have, mailbox passwords.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from curl_cffi import requests as curl_requests

from autoteam.mail.base import MailProvider, html_to_visible_text, normalize_email_addr
from autoteam.paths import PROJECT_ROOT
from autoteam.textio import read_text

logger = logging.getLogger(__name__)


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name, default) or "").strip()


@dataclass
class LuckMailAccount:
    email: str
    token: str
    purchase_id: str = ""

    def validate(self) -> bool:
        return bool(self.email and "@" in self.email and self.token)


class LuckMailProvider(MailProvider):
    provider_name = "luckmail"

    def __init__(self):
        self.base_url = (_env("LUCKMAIL_BASE_URL", "https://mail.luckyous.com") or "https://mail.luckyous.com").rstrip("/")
        self.api_key = _env("LUCKMAIL_API_KEY")
        self.project_code = _env("LUCKMAIL_PROJECT_CODE", "openai") or "openai"
        self.email_type = _env("LUCKMAIL_EMAIL_TYPE", "ms_graph") or "ms_graph"
        self.preferred_domain = _env("LUCKMAIL_PREFERRED_DOMAIN")
        self.variant_mode = _env("LUCKMAIL_VARIANT_MODE")
        self.accounts = self._load_accounts()
        self._tokens_by_email = {account.email.lower(): account.token for account in self.accounts}
        self._emails_by_token = {account.token: account.email for account in self.accounts}
        self._account_index = 0
        self._reserved: set[str] = set()
        self._lock = threading.Lock()
        self.skip_registered = _env("LUCKMAIL_SKIP_REGISTERED", "1").lower() not in (
            "0",
            "false",
            "no",
            "off",
        )

    # ------------------------------------------------------------------ config

    def _load_accounts(self) -> list[LuckMailAccount]:
        raw = _env("LUCKMAIL_ACCOUNTS")
        file_value = _env("LUCKMAIL_ACCOUNTS_FILE")
        if file_value:
            path = Path(file_value)
            if not path.is_absolute():
                path = PROJECT_ROOT / path
            if path.exists():
                raw += ("\n" if raw else "") + read_text(path)
        else:
            default_path = PROJECT_ROOT / "data" / "luckmail_accounts.txt"
            if default_path.exists():
                raw += ("\n" if raw else "") + read_text(default_path)

        accounts: list[LuckMailAccount] = []
        for line in raw.replace(";", "\n").splitlines():
            account = self._parse_account_line(line)
            if account and account.validate():
                accounts.append(account)

        seen: set[str] = set()
        unique: list[LuckMailAccount] = []
        for account in accounts:
            key = account.email.lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(account)
        return unique

    @staticmethod
    def _parse_account_line(line: str) -> LuckMailAccount | None:
        value = str(line or "").strip()
        if not value or value.startswith("#"):
            return None
        if "----" in value:
            parts = [p.strip() for p in value.split("----")]
        elif "," in value:
            parts = [p.strip() for p in value.split(",")]
        else:
            parts = [p.strip() for p in value.split()]
        email = normalize_email_addr(parts[0] if parts else "")
        token = parts[1] if len(parts) > 1 else ""
        purchase_id = parts[2] if len(parts) > 2 else ""
        if "@" not in email or not token:
            return None
        return LuckMailAccount(email=email, token=token, purchase_id=purchase_id)

    # ------------------------------------------------------------------ public

    def login(self) -> str:
        if self.accounts:
            logger.info("[luckmail] 已加载 %d 个 LuckMail 已购邮箱 token", len(self.accounts))
            return f"luckmail:{len(self.accounts)}"
        if self.api_key:
            logger.info("[luckmail] 已配置 LuckMail API Key，可在运行时购买邮箱")
            return "luckmail:api-key"
        raise RuntimeError(
            "LuckMail provider 未配置。请设置 LUCKMAIL_ACCOUNTS_FILE 或 LUCKMAIL_ACCOUNTS；"
            "格式: email@example.com----tok_xxx。也可配置 LUCKMAIL_API_KEY 用于自动购买。"
        )

    def create_temp_email(self, prefix: str | None = None, domain: str | None = None) -> tuple[int | str, str]:
        if not self.accounts and self.api_key:
            account = self._purchase_account(domain=domain)
            with self._lock:
                self.accounts.append(account)
                self._tokens_by_email[account.email.lower()] = account.token
                self._emails_by_token[account.token] = account.email
                self._reserved.add(account.email.lower())
            logger.info("[luckmail] 购买并选择 LuckMail 邮箱: %s", account.email)
            return account.token, account.email

        if not self.accounts:
            self.login()

        registered = self._registered_emails() if self.skip_registered else set()
        wanted_domain = str(domain or "").strip().lstrip("@").lower()
        with self._lock:
            total = len(self.accounts)
            for offset in range(total):
                idx = (self._account_index + offset) % total
                account = self.accounts[idx]
                email = account.email.lower()
                if email in self._reserved:
                    continue
                if self.skip_registered and email in registered:
                    continue
                if wanted_domain and not email.endswith("@" + wanted_domain):
                    continue
                self._account_index = (idx + 1) % total
                self._reserved.add(email)
                logger.info("[luckmail] 选择 LuckMail 注册邮箱: %s", account.email)
                return account.token, account.email

        if self.api_key:
            account = self._purchase_account(domain=domain)
            with self._lock:
                self.accounts.append(account)
                self._tokens_by_email[account.email.lower()] = account.token
                self._emails_by_token[account.token] = account.email
                self._reserved.add(account.email.lower())
            logger.info("[luckmail] 已购邮箱池无可用账号，重新购买并选择 LuckMail 邮箱: %s", account.email)
            return account.token, account.email

        raise RuntimeError("没有可用的 LuckMail 已购邮箱（可能都已注册、已被本轮占用或不匹配域名）")

    def list_accounts(self, size: int = 200) -> list[dict]:
        return [
            {
                "id": account.token,
                "email": account.email,
                "accountEmail": account.email,
                "provider": self.provider_name,
            }
            for account in self.accounts[: max(1, int(size or 200))]
        ]

    def delete_account(self, account_id: int | str) -> dict:
        value = str(account_id or "").strip()
        email = self._emails_by_token.get(value) or normalize_email_addr(value)
        with self._lock:
            self._reserved.discard(email)
        logger.info("[luckmail] LuckMail provider 不删除真实邮箱，仅释放本地占用: %s", email or value)
        return {"code": 0, "message": "luckmail account retained"}

    def search_emails_by_recipient(
        self, to_email: str, size: int = 10, account_id: int | str | None = None
    ) -> list[dict]:
        account = self._find_account(to_email=to_email, account_id=account_id)
        if not account:
            logger.warning("[luckmail] 未找到收件人对应 LuckMail token: %s", to_email)
            return []

        try:
            mails = self._fetch_token_mails(account.token, account.email)
        except Exception as exc:
            logger.warning("[luckmail] 查询 LuckMail 邮件失败，稍后可重试: %s", exc)
            return []
        target = normalize_email_addr(to_email)
        filtered = [
            mail
            for mail in mails
            if not target
            or normalize_email_addr(mail.get("toEmail")) == target
            or normalize_email_addr(mail.get("accountEmail")) == target
        ]
        return filtered[: max(1, int(size or 10))]

    def list_emails(self, account_id: int | str, size: int = 10) -> list[dict]:
        return self.search_emails_by_recipient(str(account_id), size=size, account_id=account_id)

    def delete_emails_for(self, to_email: str) -> int:
        logger.info("[luckmail] LuckMail provider 暂不删除邮件: %s", to_email)
        return 0

    # ------------------------------------------------------------------ lookup

    @staticmethod
    def _registered_emails() -> set[str]:
        try:
            from autoteam.accounts import load_accounts

            return {normalize_email_addr(a.get("email")) for a in load_accounts() if a.get("email")}
        except Exception:
            logger.debug("[luckmail] 读取本地账号池失败，跳过已注册过滤", exc_info=True)
            return set()

    def _find_account(self, *, to_email: str, account_id: int | str | None = None) -> LuckMailAccount | None:
        token = str(account_id or "").strip()
        if token and token in self._emails_by_token:
            email = self._emails_by_token[token]
            return LuckMailAccount(email=email, token=token)
        if token.startswith("tok_") and normalize_email_addr(to_email):
            return LuckMailAccount(email=normalize_email_addr(to_email), token=token)
        email = normalize_email_addr(to_email or account_id)
        token = self._tokens_by_email.get(email)
        if token:
            return LuckMailAccount(email=email, token=token)
        return None

    # ------------------------------------------------------------------ api

    def _request(self, method: str, path: str, **kwargs):
        url = f"{self.base_url}{path}"
        headers = dict(kwargs.pop("headers", {}) or {})
        if self.api_key:
            headers.setdefault("X-API-Key", self.api_key)
        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                if method.upper() == "GET":
                    return curl_requests.get(url, headers=headers, timeout=30, impersonate="chrome110", **kwargs)
                if method.upper() == "POST":
                    return curl_requests.post(url, headers=headers, timeout=30, impersonate="chrome110", **kwargs)
                raise ValueError(f"unsupported method: {method}")
            except Exception as exc:
                last_exc = exc
                if attempt >= 3:
                    break
                logger.warning("[luckmail] %s %s 失败，%.1fs 后重试(%d/3): %s", method.upper(), path, attempt * 1.5, attempt, exc)
                time.sleep(attempt * 1.5)
        raise last_exc or RuntimeError(f"LuckMail request failed: {method} {path}")

    def _purchase_account(self, *, domain: str | None = None) -> LuckMailAccount:
        payload: dict[str, Any] = {
            "project_code": self.project_code,
            "email_type": self.email_type,
            "quantity": 1,
        }
        wanted_domain = str(domain or self.preferred_domain or "").strip().lstrip("@")
        if wanted_domain:
            payload["domain"] = wanted_domain
        if self.variant_mode:
            payload["variant_mode"] = self.variant_mode

        resp = self._request(
            "POST",
            "/api/v1/openapi/email/purchase",
            json=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"LuckMail 购买邮箱失败: HTTP {resp.status_code} {(resp.text or '')[:200]}")
        body = resp.json() or {}
        if body.get("code") not in (0, "0", None):
            raise RuntimeError(f"LuckMail 购买邮箱失败: {body}")
        purchases = ((body.get("data") or {}).get("purchases") or [])
        if not purchases:
            raise RuntimeError(f"LuckMail 购买邮箱响应缺少 purchases: {body}")
        item = purchases[0]
        email = normalize_email_addr(item.get("email_address") or item.get("address") or item.get("email"))
        token = str(item.get("token") or "").strip()
        if not email or not token:
            raise RuntimeError(f"LuckMail 购买邮箱响应缺少 email/token: {item}")
        return LuckMailAccount(email=email, token=token, purchase_id=str(item.get("id") or ""))

    def _fetch_token_mails(self, token: str, fallback_email: str = "") -> list[dict]:
        code_mail = self._fetch_latest_code(token, fallback_email)
        mails = [code_mail] if code_mail else []

        try:
            resp = self._request(
                "GET",
                f"/api/v1/openapi/email/token/{quote(token, safe='')}/mails",
                headers={"Accept": "application/json"},
            )
            if resp.status_code != 200:
                logger.warning("[luckmail] 查询 token 邮件列表失败: HTTP %s %s", resp.status_code, (resp.text or "")[:160])
                return mails
            body = resp.json() or {}
            data = body.get("data") or {}
            email = normalize_email_addr(data.get("email_address") or fallback_email)
            for item in data.get("mails") or []:
                mail = self._mail_item_to_legacy(token, email, item)
                if not any(existing.get("id") == mail.get("id") for existing in mails):
                    mails.append(mail)
        except Exception as exc:
            logger.debug("[luckmail] 查询 token 邮件列表异常: %s", exc, exc_info=True)
        return mails

    def _fetch_latest_code(self, token: str, fallback_email: str = "") -> dict | None:
        resp = self._request(
            "GET",
            f"/api/v1/openapi/email/token/{quote(token, safe='')}/code",
            headers={"Accept": "application/json"},
        )
        if resp.status_code != 200:
            logger.warning("[luckmail] 查询 token 验证码失败: HTTP %s %s", resp.status_code, (resp.text or "")[:160])
            return None
        body = resp.json() or {}
        data = body.get("data") or {}
        email = normalize_email_addr(data.get("email_address") or fallback_email)
        code = str(data.get("code") or data.get("verification_code") or "").strip()
        mail = data.get("mail") if isinstance(data.get("mail"), dict) else {}
        if not code:
            return None
        item = dict(mail)
        item.setdefault("verification_code", code)
        item.setdefault("subject", f"LuckMail verification code {code}")
        return self._mail_item_to_legacy(token, email, item)

    @staticmethod
    def _mail_item_to_legacy(token: str, email: str, item: dict[str, Any]) -> dict:
        code = str(item.get("verification_code") or item.get("code") or "").strip()
        subject = str(item.get("subject") or item.get("mail_subject") or "")
        sender = str(item.get("from") or item.get("mail_from") or "")
        body = str(item.get("body") or item.get("mail_body") or item.get("mail_body_html") or "")
        html = str(item.get("html_body") or item.get("html") or "")
        text_parts = [subject, html_to_visible_text(body), html_to_visible_text(html)]
        if code:
            text_parts.insert(0, f"verification code: {code}")
        text = "\n".join(part for part in text_parts if part).strip()
        message_id = str(item.get("message_id") or item.get("id") or code or token)
        return {
            "id": message_id,
            "accountId": token,
            "accountEmail": email,
            "toEmail": email,
            "sendEmail": sender,
            "subject": subject,
            "text": text,
            "content": html or body or text,
            "html": html,
            "message": html or body or text,
            "createTime": item.get("received_at") or item.get("created_at") or item.get("code_time") or 0,
            "createdAt": item.get("received_at") or item.get("created_at") or item.get("code_time") or 0,
            "raw": item,
        }
