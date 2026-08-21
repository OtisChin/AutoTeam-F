"""自建 Mailu mail-api provider.

对接自建 Mailu 的 mail-api 网关（如 https://mail.rexoox.com/mail-api/）：
- 支持指定前缀 + 域名随机生成邮箱（依赖 Mailu catch-all 转发到收件箱）
- 通过 `/code?to=...` 按目标地址取验证码
- 通过 `/latest` 拉取最近邮件
- 认证支持 `?key=` 查询参数或 `X-API-Key` 请求头

环境变量：
  MAILU_BASE_URL     mail-api 根地址，如 https://mail.rexoox.com/mail-api/
  MAILU_API_KEY      API Key
  MAILU_DOMAIN       默认邮箱域名（可选，注册时也可由任务域名指定）
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime
from typing import Any

from curl_cffi import requests as curl_requests

from autotoken.mail.base import MailProvider, html_to_visible_text, normalize_email_addr

logger = logging.getLogger(__name__)


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name, default) or "").strip()


class MailuMailProvider(MailProvider):
    provider_name = "mailu"

    def __init__(self):
        self.base_url = (_env("MAILU_BASE_URL") or _env("MAILU_API_URL") or "").rstrip("/")
        self.api_key = _env("MAILU_API_KEY")
        self.default_domain = _env("MAILU_DOMAIN").lstrip("@").strip()
        self._created_emails: list[str] = []
        self._reserved_emails: set[str] = set()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ helpers

    def _url(self, path: str) -> str:
        if not self.base_url:
            raise RuntimeError("Mailu provider 未配置 MAILU_BASE_URL")
        path = path.lstrip("/")
        return f"{self.base_url}/{path}"

    def _auth_params(self) -> dict[str, str]:
        return {"key": self.api_key} if self.api_key else {}

    def _auth_headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json,text/html;q=0.9,*/*;q=0.8"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    @staticmethod
    def _sanitize_prefix(prefix: str | None) -> str:
        """Mailu 本地部分只允许字母数字点下划线，其余剔除；空则随机。"""
        if not prefix:
            return uuid.uuid4().hex[:10]
        cleaned = re.sub(r"[^A-Za-z0-9._]", "", str(prefix))
        cleaned = cleaned.strip("._")
        return cleaned[:60] or uuid.uuid4().hex[:10]

    def _request(self, path: str, params: dict[str, Any] | None = None) -> dict:
        query = {**(self._auth_params()), **{k: v for k, v in (params or {}).items() if v not in (None, "")}}
        resp = curl_requests.get(
            self._url(path), params=query, headers=self._auth_headers(), timeout=30, impersonate="chrome110"
        )
        if resp.status_code in (401, 403):
            raise RuntimeError(f"Mailu mail-api 认证失败 (HTTP {resp.status_code}): {str(resp.text or '')[:200]}")
        if resp.status_code != 200:
            raise RuntimeError(f"Mailu mail-api HTTP {resp.status_code}: {str(resp.text or '')[:200]}")
        try:
            payload = resp.json()
        except Exception:
            raise RuntimeError(f"Mailu mail-api 返回非 JSON: {str(resp.text or '')[:200]}")
        if not isinstance(payload, dict):
            raise RuntimeError(f"Mailu mail-api 响应格式异常: {str(payload or '')[:200]}")
        return payload

    # ------------------------------------------------------------------ auth

    def login(self) -> str:
        if not self.base_url:
            raise RuntimeError("Mailu provider 未配置。请设置 MAILU_BASE_URL 和 MAILU_API_KEY。")
        if not self.api_key:
            raise RuntimeError("Mailu provider 未配置 API Key。请设置 MAILU_API_KEY。")
        payload = self._request("/health")
        if not payload.get("ok"):
            raise RuntimeError(f"Mailu mail-api 健康检查未通过: {payload}")
        logger.info("[mailu] mail-api 鉴权通过: %s", self.base_url)
        return f"mailu:{self.base_url}"

    # ------------------------------------------------------------------ accounts

    def create_temp_email(self, prefix: str | None = None, domain: str | None = None) -> tuple[int | str, str]:
        requested_domain = str(domain or "").strip().lstrip("@").lower()
        resolved_domain = requested_domain or self.default_domain
        if not resolved_domain:
            raise RuntimeError("Mailu provider 未配置邮箱域名，请设置 MAILU_DOMAIN 或在注册任务中指定域名")

        local = self._sanitize_prefix(prefix)
        with self._lock:
            for _attempt in range(20):
                email = f"{local}@{resolved_domain}".lower()
                if email not in self._reserved_emails:
                    self._reserved_emails.add(email)
                    self._created_emails.append(email)
                    logger.info("[mailu] 生成注册邮箱: %s", email)
                    return email, email
                local = f"{self._sanitize_prefix(prefix)}{uuid.uuid4().hex[:6]}"
        raise RuntimeError("Mailu provider 无法生成可用邮箱（冲突过多）")

    def list_accounts(self, size: int = 200) -> list[dict]:
        limit = max(1, int(size or 200))
        return [
            {
                "id": email,
                "email": email,
                "accountEmail": email,
                "has_receive_code_url": True,
                "provider": self.provider_name,
            }
            for email in self._created_emails[:limit]
        ]

    def delete_account(self, account_id: int | str) -> dict:
        email = normalize_email_addr(account_id)
        with self._lock:
            self._reserved_emails.discard(email)
        logger.info("[mailu] Mailu provider 不删除真实邮箱，仅释放本地占用: %s", email)
        return {"code": 0, "message": "mailu account retained"}

    # ------------------------------------------------------------------ emails

    def search_emails_by_recipient(
        self, to_email: str, size: int = 10, account_id: int | str | None = None
    ) -> list[dict]:
        target = normalize_email_addr(account_id or to_email)
        if not target:
            return []
        try:
            payload = self._request("/code", params={"to": target, "limit": max(1, int(size or 10))})
        except Exception as exc:
            logger.warning("[mailu] 查询验证码失败，稍后可重试: %s", exc)
            return []
        if not payload.get("ok"):
            logger.debug("[mailu] %s 暂无验证码: %s", target, payload.get("error") or "")
            return []
        message = self._code_payload_to_legacy(payload, target)
        return [message] if message else []

    def list_emails(self, account_id: int | str, size: int = 10) -> list[dict]:
        target = normalize_email_addr(account_id)
        if not target:
            return []
        try:
            payload = self._request("/latest", params={"limit": max(1, int(size or 10))})
        except Exception as exc:
            logger.warning("[mailu] 查询最近邮件失败，稍后可重试: %s", exc)
            return []
        messages = []
        for item in payload.get("messages") or []:
            if not isinstance(item, dict):
                continue
            to_value = str(item.get("to") or "").strip().lower()
            if to_value and to_value != target:
                continue
            message = self._latest_item_to_legacy(item, target)
            if message:
                messages.append(message)
        return messages[: max(1, int(size or 10))]

    def delete_emails_for(self, to_email: str) -> int:
        logger.info("[mailu] Mailu provider 暂不删除邮件: %s", to_email)
        return 0

    # ------------------------------------------------------------------ parse

    @staticmethod
    def _code_payload_to_legacy(payload: dict[str, Any], target: str) -> dict[str, Any]:
        code = str(payload.get("code") or "").strip()
        if not code:
            return {}
        subject = str(payload.get("subject") or "").strip()
        sender = str(payload.get("from") or "").strip()
        message_id = str(payload.get("message_id") or "").strip()
        uid = str(payload.get("uid") or message_id or code)
        body = ""
        text = " ".join(part for part in (subject, f"verification code: {code}") if part).strip()
        return {
            "id": uid,
            "accountId": target,
            "accountEmail": target,
            "email": target,
            "toEmail": target,
            "sendEmail": sender,
            "subject": subject,
            "verification_code": code,
            "text": text,
            "html": "",
            "content": body or text,
            "message": body or text,
            "createTime": MailuMailProvider._parse_date(payload.get("date")) or 0,
            "createdAt": MailuMailProvider._parse_date(payload.get("date")) or 0,
            "provider": "mailu",
            "raw": payload,
        }

    @staticmethod
    def _latest_item_to_legacy(item: dict[str, Any], target: str) -> dict[str, Any]:
        subject = str(item.get("subject") or "").strip()
        sender = str(item.get("from") or "").strip()
        code = str(item.get("code") or "").strip()
        body = html_to_visible_text(str(item.get("body") or ""))
        message_id = str(item.get("message_id") or "").strip()
        uid = str(item.get("uid") or message_id or code or str(time.time()))
        text_parts = []
        if code:
            text_parts.append(f"verification code: {code}")
        if body:
            text_parts.append(body)
        text = "\n".join(part for part in text_parts if part).strip()
        return {
            "id": uid,
            "accountId": target,
            "accountEmail": target,
            "email": target,
            "toEmail": str(item.get("to") or target),
            "sendEmail": sender,
            "subject": subject,
            "verification_code": code,
            "text": text,
            "html": "",
            "content": body or text,
            "message": body or text,
            "createTime": MailuMailProvider._parse_date(item.get("date")) or 0,
            "createdAt": MailuMailProvider._parse_date(item.get("date")) or 0,
            "provider": "mailu",
            "raw": item,
        }

    @staticmethod
    def _parse_date(value: Any) -> int:
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
        normalized = text.replace("Z", "+0000")
        for fmt in (
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S %Z",
            "%Y-%m-%d %H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f%z",
        ):
            try:
                return int(datetime.strptime(normalized, fmt).timestamp())
            except Exception:
                continue
        return 0
