"""MailProvider 抽象基类 + 共享工具。

- `MailProvider`：所有 mail backend 的公开接口（与历史临时邮箱客户端 1:1 对齐）。
- `Email` / `Account`：内部统一 IR；现阶段对外仍返 dict（保现兼容），dataclass 留作未来迁移落点。
- 共享文本工具：MIME 解析、HTML→可见文本、OTP 提取、邀请链接提取、JWT payload 解码、`wait_for_email` 轮询。

子类只需实现 §「provider 必填」标记的方法；OTP/邀请链接/wait 等纯文本逻辑全部继承默认实现。
"""

from __future__ import annotations

import email as email_pkg
import html as html_lib
import logging
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from email.header import decode_header, make_header
from typing import Any

from autotoken.core.jwt import decode_jwt_payload as _decode_jwt_payload
from autotoken.core.normalization import normalized_email
from autotoken.settings.config import EMAIL_POLL_INTERVAL, EMAIL_POLL_TIMEOUT

logger = logging.getLogger(__name__)


_VERIFICATION_CODE_PATTERNS = (
    r"(?:temporary\s+(?:openai|chatgpt)\s+login\s+code(?:\s+is)?|verification\s+code(?:\s+is)?|login\s+code(?:\s+is)?|code(?:\s+is)?|临时验证码|一次性验证码|验证码(?:为|是)?)\D{0,80}(\d{6})",
    r"(?:openai|chatgpt)?\s*(?:临时验证码|一次性验证码|验证码|验证代码|登录代码|登入代码|代码)(?:为|是|以继续)?\D{0,80}(\d{6})",
    r"\b(\d{6})\b",
)

_OTP_CODE_KEYS = (
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

_MESSAGE_SUBJECT_KEYS = ("subject", "mail_subject", "title")
_MESSAGE_SENDER_KEYS = ("sendEmail", "from", "fromEmail", "mail_from", "sender", "fromName", "sendName")
_MESSAGE_BODY_KEYS = (
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
    "bodyPreview",
    "bodyText",
    "html",
    "html_body",
    "body_html",
    "mail_html",
    "raw_html",
)

_NON_OTP_SUBJECT_MARKERS = (
    "new sign-in",
    "new sign in",
    "new login",
    "account activity",
    "security alert",
    "安全提醒",
    "新登录",
    "新登入",
)

_GENERIC_OTP_MARKERS = (
    "verification code",
    "login code",
    "one-time code",
    "one time code",
    "otp",
)


@dataclass
class Email:
    """统一邮件 IR — provider 无关的中间表示。"""

    id: int
    recipient: str
    sender: str
    subject: str
    text: str | None
    html: str | None
    received_at: int
    raw: dict = field(default_factory=dict)


@dataclass
class Account:
    """临时邮箱账户。"""

    account_id: int
    email: str
    password: str | None = None
    create_time: int | None = None
    extra: dict = field(default_factory=dict)


# ----------------------------------------------------------------------- helpers


def decode_mime_header(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return str(value)


def decode_jwt_payload(jwt: str) -> dict:
    return _decode_jwt_payload(jwt)


def _part_to_text(part) -> str:
    try:
        payload = part.get_payload(decode=True)
        if payload is None:
            return ""
        charset = part.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    except Exception:
        try:
            return str(part.get_payload())
        except Exception:
            return ""


def parse_mime(raw: str | None) -> tuple[str, str, str, str, str, str]:
    """解析 MIME 消息，返回 (subject, text, html, from_addr, to_addr, message_id)。"""
    if not raw:
        return "", "", "", "", "", ""
    try:
        msg = email_pkg.message_from_string(raw)
    except Exception:
        return "", raw, "", "", "", ""

    subject = decode_mime_header(msg.get("Subject", ""))
    from_addr = decode_mime_header(msg.get("From", ""))
    to_addr = decode_mime_header(msg.get("To", ""))
    message_id = (msg.get("Message-ID") or "").strip()

    text_body = ""
    html_body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.is_multipart():
                continue
            ctype = part.get_content_type()
            dispo = (part.get("Content-Disposition") or "").lower()
            if "attachment" in dispo:
                continue
            if ctype == "text/plain" and not text_body:
                text_body = _part_to_text(part)
            elif ctype == "text/html" and not html_body:
                html_body = _part_to_text(part)
    else:
        decoded = _part_to_text(msg)
        if msg.get_content_type() == "text/html":
            html_body = decoded
        else:
            text_body = decoded

    return subject, text_body, html_body, from_addr, to_addr, message_id


def html_to_visible_text(value: Any) -> str:
    content = str(value or "")
    if not content:
        return ""

    content = re.sub(r"(?is)<(script|style)\b.*?>.*?</\1>", " ", content)
    content = re.sub(r"(?is)<!--.*?-->", " ", content)
    content = re.sub(r"(?i)<br\s*/?>", "\n", content)
    content = re.sub(r"(?i)</(?:p|div|tr|table|h[1-6]|li|td|section|article)>", "\n", content)
    content = re.sub(r"(?s)<[^>]+>", " ", content)
    content = html_lib.unescape(content)
    content = re.sub(r"[\t\r\f\v ]+", " ", content)
    content = re.sub(r"\n\s+", "\n", content)
    content = re.sub(r"\n{2,}", "\n", content)
    return content.strip()


def normalize_email_addr(value: Any) -> str:
    return normalized_email(value)


def _message_values(email_data: dict, keys: tuple[str, ...]) -> list[str]:
    """Collect compatible mail fields from the normalized item and its raw payload."""
    if not isinstance(email_data, dict):
        return []
    containers = [email_data]
    raw = email_data.get("raw")
    if isinstance(raw, dict):
        containers.append(raw)
        nested_mail = raw.get("mail")
        if isinstance(nested_mail, dict):
            containers.append(nested_mail)

    values: list[str] = []
    for item in containers:
        for key in keys:
            value = item.get(key)
            if isinstance(value, dict):
                nested_items = [value]
                email_address = value.get("emailAddress")
                if isinstance(email_address, dict):
                    nested_items.append(email_address)
                for nested_item in nested_items:
                    for nested_key in ("address", "email", "name"):
                        nested = nested_item.get(nested_key)
                        if nested is not None and str(nested).strip():
                            values.append(str(nested).strip())
            elif value is not None and str(value).strip():
                values.append(str(value).strip())
    return values


def is_openai_otp_message(email_data: dict) -> bool:
    """Identify OpenAI OTP mail by structured identity before localized wording.

    Browser mode is deliberately irrelevant here: Roxy, Cloak and protocol
    registration all pass provider-normalized mail dictionaries through this
    one classifier.
    """
    if not isinstance(email_data, dict):
        return False

    subjects = _message_values(email_data, _MESSAGE_SUBJECT_KEYS)
    subject_text = "\n".join(subjects).lower()
    if any(marker in subject_text for marker in _NON_OTP_SUBJECT_MARKERS):
        return False

    if _message_values(email_data, _OTP_CODE_KEYS):
        return True

    senders = "\n".join(_message_values(email_data, _MESSAGE_SENDER_KEYS)).lower()
    if "openai" in senders or "chatgpt" in senders:
        return True

    body = "\n".join(_message_values(email_data, _MESSAGE_BODY_KEYS)).lower()
    identity_text = f"{subject_text}\n{body}"
    if "openai" in identity_text or "chatgpt" in identity_text:
        return True

    return any(marker in identity_text for marker in _GENERIC_OTP_MARKERS)


def _parse_message_timestamp(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        timestamp = float(value)
        return timestamp / 1000 if timestamp > 10_000_000_000 else timestamp
    text = str(value or "").strip()
    if not text:
        return 0.0
    if text.isdigit():
        return _parse_message_timestamp(int(text))
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
    ):
        try:
            return datetime.strptime(text.replace("Z", "+0000"), fmt).timestamp()
        except (TypeError, ValueError):
            continue
    return 0.0


def _message_received_at(email_data: dict) -> float:
    timestamp_keys = (
        "received_at",
        "receive_time",
        "receivedAt",
        "create_time",
        "createTime",
        "date",
        "time",
        "timestamp",
        "code_time",
    )
    for value in _message_values(email_data, timestamp_keys):
        timestamp = _parse_message_timestamp(value)
        if timestamp:
            return timestamp
    return 0.0


def _requires_fresh_otp(email_data: dict, mail_client: Any = None) -> bool:
    provider = str(getattr(mail_client, "provider_name", "") or "").strip().lower()
    if provider in {"icloud", "generic-api", "generic_api", "genericapi"}:
        return True
    for value in _message_values(email_data, ("provider", "source")):
        item_provider = value.lower()
        if item_provider == "icloud" or item_provider.startswith("icloud_"):
            return True
        if item_provider in {"generic-api", "generic_api", "genericapi"} or item_provider.startswith("generic_api_"):
            return True
    return False


def wait_for_openai_otp(
    mail_client,
    email: str,
    *,
    account_id: str | int | None = None,
    timeout: int = 60,
    issued_after: float | None = None,
    exclude_codes: set[str] | list[str] | tuple[str, ...] | None = None,
    strict_issued_after: bool = False,
) -> str:
    """Shared OpenAI email OTP polling for browser and protocol registration."""
    target = str(email or "").strip()
    deadline = time.time() + max(1, int(timeout or 60))
    issued_after_ts = float(issued_after or 0)
    excluded = {str(value or "").strip() for value in (exclude_codes or []) if str(value or "").strip()}
    last_seen = ""
    last_no_code_signature = ""
    next_wait_log_at = 0.0
    logger.info("[邮箱验证码] 等待 OpenAI 验证码: email=%s timeout=%ss", target, int(timeout or 60))
    try:
        initial_delay = max(0.0, float(os.environ.get("OPENAI_EMAIL_OTP_INITIAL_DELAY", "3") or "3"))
    except (TypeError, ValueError):
        initial_delay = 3.0
    if initial_delay > 0:
        time.sleep(min(initial_delay, max(0.0, deadline - time.time())))

    while time.time() < deadline:
        try:
            try:
                emails = mail_client.search_emails_by_recipient(target, size=10, account_id=account_id)
            except TypeError:
                emails = mail_client.search_emails_by_recipient(target, size=10)
        except Exception as exc:
            logger.warning("[邮箱验证码] 查询失败，稍后重试: %s", exc)
            emails = []

        if time.time() >= next_wait_log_at:
            logger.info("[邮箱验证码] 正在查询: email=%s matched=%d", target, len(emails or []))
            next_wait_log_at = time.time() + 15

        email_items = [
            item
            for _, item in sorted(
                enumerate(emails or []),
                key=lambda pair: (
                    1 if _message_received_at(pair[1]) else 0,
                    _message_received_at(pair[1]) or -pair[0],
                ),
                reverse=True,
            )
        ]
        for item in email_items:
            if not isinstance(item, dict):
                continue
            received_at = _message_received_at(item)
            if issued_after_ts and received_at and 86400 < (issued_after_ts - received_at):
                continue
            if (strict_issued_after or _requires_fresh_otp(item, mail_client)) and issued_after_ts and received_at:
                stale_tolerance = 0 if strict_issued_after else 5
                if received_at < issued_after_ts - stale_tolerance:
                    logger.info(
                        "[邮箱验证码] 跳过旧邮件: subject=%s received_at=%s issued_after=%s",
                        str(item.get("subject") or "")[:80],
                        int(received_at),
                        int(issued_after_ts),
                    )
                    continue

            try:
                code = str(mail_client.extract_verification_code(item) or "").strip()
            except Exception:
                code = ""
            if code:
                if not is_openai_otp_message(item):
                    logger.info(
                        "[邮箱验证码] 跳过非 OpenAI 邮件中的数字: subject=%s received_at=%s",
                        str(item.get("subject") or "")[:80],
                        received_at or "",
                    )
                    continue
                if code in excluded:
                    logger.info("[邮箱验证码] 跳过已使用验证码: %s***len=%d", code[:1], len(code))
                    continue
                logger.info("[邮箱验证码] 已收到验证码: %s***len=%d", code[:1], len(code))
                return code

            raw = item.get("raw")
            raw_keys = sorted(raw.keys())[:12] if isinstance(raw, dict) else []
            item_keys = sorted(item.keys())[:12]
            signature = (
                f"{item.get('id') or item.get('message_id') or ''}|"
                f"{item.get('subject') or ''}|{item_keys}|{raw_keys}"
            )
            if signature != last_no_code_signature:
                logger.info(
                    "[邮箱验证码] 候选邮件未解析出验证码: subject=%s received_at=%s keys=%s raw_keys=%s",
                    str(item.get("subject") or "")[:80],
                    received_at or "",
                    item_keys,
                    raw_keys,
                )
                last_no_code_signature = signature
            if not last_seen:
                last_seen = str(item.get("subject") or item.get("text") or item.get("content") or "")[:180]

        time.sleep(3)

    detail = f"未收到 OpenAI 邮箱验证码: {target}"
    if last_seen:
        detail += f"；最近邮件摘要: {last_seen}"
    raise TimeoutError(detail)


# ----------------------------------------------------------------------- ABC


class MailProvider(ABC):
    """所有 mail backend 必须实现的接口。命名/语义保持与历史临时邮箱客户端一致。"""

    # provider 名字（日志展示用），子类覆写。
    provider_name: str = "mail"

    # ---- 鉴权 ----
    @abstractmethod
    def login(self) -> str:
        """初始化鉴权，返回不透明 token 字符串（仅作日志）。失败抛异常。"""

    # ---- 账户管理 ----
    @abstractmethod
    def create_temp_email(self, prefix: str | None = None, domain: str | None = None) -> tuple[int | str, str]:
        """创建临时邮箱，返回 (account_id, email)。"""

    def create_registration_email(self, prefix: str | None = None, domain: str | None = None) -> tuple[int | str, str]:
        """创建注册专用邮箱。默认复用普通创建逻辑；provider 可覆写为强制新购。"""
        return self.create_temp_email(prefix=prefix, domain=domain)

    @abstractmethod
    def list_accounts(self, size: int = 200) -> list[dict]:
        """列出已创建的临时邮箱。返回兼容字段的 dict 列表。"""

    @abstractmethod
    def delete_account(self, account_id: int | str) -> dict:
        """删除账户。account_id 可以是数字 id 或 email。返回 {code, message?}。"""

    # ---- 邮件读取 ----
    @abstractmethod
    def search_emails_by_recipient(
        self, to_email: str, size: int = 10, account_id: int | str | None = None
    ) -> list[dict]:
        """按收件人查邮件（最新优先）。"""

    @abstractmethod
    def list_emails(self, account_id: int | str, size: int = 10) -> list[dict]:
        """按 account_id 查邮件。"""

    def get_latest_emails(self, account_id: int | str, email_id: int = 0, all_receive: int = 0) -> list[dict]:
        """旧接口兼容：默认委托 list_emails。子类可覆写。"""
        return self.list_emails(account_id, size=5)

    # ---- 邮件删除 ----
    @abstractmethod
    def delete_emails_for(self, to_email: str) -> int:
        """删除指定收件人全部邮件，返回删除数量（或 1 表示批量成功）。"""

    # ---- 等待（共用实现） ----
    def wait_for_email(self, to_email: str, timeout: int | None = None, sender_keyword: str | None = None) -> dict:
        """轮询等待邮件到达。"""
        timeout = timeout or EMAIL_POLL_TIMEOUT
        logger.info("[%s] 等待邮件到达 %s... (超时 %ds)", self.provider_name, to_email, timeout)
        start = time.time()

        while time.time() - start < timeout:
            try:
                emails = self.search_emails_by_recipient(to_email, size=10)
            except Exception as exc:
                logger.warning("[%s] 轮询查询邮件失败,稍后重试: %s", self.provider_name, exc)
                emails = []
            for em in emails:
                sender = em.get("sendEmail", "") or ""
                if sender_keyword and sender_keyword.lower() not in sender.lower():
                    continue
                subject = em.get("subject", "")
                logger.info("[%s] 收到邮件: %s (from: %s)", self.provider_name, subject, sender)
                return em

            elapsed = int(time.time() - start)
            print(f"\r[{self.provider_name}] 等待中... ({elapsed}s)", end="", flush=True)
            time.sleep(EMAIL_POLL_INTERVAL)

        print()
        raise TimeoutError("等待邮件超时")

    # ---- OTP / 邀请链接（共用实现，纯文本） ----
    def extract_verification_code(self, email_data: dict) -> str | None:
        """从邮件标题/正文中提取 6 位验证码。"""
        sources: list[str] = []

        def add_source(value: Any, *, html: bool = False):
            if html:
                text = html_to_visible_text(value)
            else:
                text = str(value or "").strip()
            if text and text not in sources:
                sources.append(text)

        # OpenAI 登录验证码经常直接出现在 subject；部分邮件列表接口首轮只返回标题/摘要。
        add_source(email_data.get("subject"))
        code_keys = (
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
        text_keys = (
            "text",
            "plain_text",
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
        html_keys = (
            "html",
            "html_body",
            "body_html",
            "mail_html",
            "mail_body_html",
            "raw_html",
        )

        for key in code_keys:
            add_source(email_data.get(key))
        for key in text_keys:
            add_source(email_data.get(key))
        for key in html_keys:
            add_source(email_data.get(key), html=True)

        raw = email_data.get("raw")
        if isinstance(raw, dict):
            raw_items = [raw]
            nested_mail = raw.get("mail")
            if isinstance(nested_mail, dict):
                raw_items.append(nested_mail)
            for raw_item in raw_items:
                add_source(raw_item.get("subject") or raw_item.get("mail_subject"))
                for key in code_keys:
                    add_source(raw_item.get(key))
                for key in text_keys:
                    add_source(raw_item.get(key))
                for key in html_keys:
                    add_source(raw_item.get(key), html=True)
        elif isinstance(raw, str):
            add_source(raw)

        for source in sources:
            for pattern in _VERIFICATION_CODE_PATTERNS:
                match = re.search(pattern, source, re.IGNORECASE)
                if match:
                    return match.group(1)
        return None

    def extract_invite_link(self, email_data: dict) -> str | None:
        """从 OpenAI 邀请邮件中提取邀请链接。"""
        html_body = email_data.get("content", "") or ""
        text = email_data.get("text", "") or ""

        links = re.findall(r'href="(https://chatgpt\.com/auth/login\?[^"]*)"', html_body)
        if links:
            link = links[0]
            logger.info("[%s] 提取到邀请链接: %s...", self.provider_name, link[:80])
            return link

        links = re.findall(r'(https://chatgpt\.com/auth/login\?[^\s<>"\']+)', text)
        if links:
            link = links[0]
            logger.info("[%s] 提取到邀请链接: %s...", self.provider_name, link[:80])
            return link

        link_pattern = r'https?://[^\s<>"\']+(?:invite|accept|join|workspace)[^\s<>"\']*'
        match = re.search(link_pattern, html_body or text, re.IGNORECASE)
        if match:
            link = match.group(0)
            logger.info("[%s] 提取到链接: %s...", self.provider_name, link[:80])
            return link
        return None
