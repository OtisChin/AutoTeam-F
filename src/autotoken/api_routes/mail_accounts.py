"""mail.com account management HTTP routes."""

from __future__ import annotations

import email as email_pkg
import imaplib
import os
import re
import time
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any

import requests
from fastapi import APIRouter, HTTPException
from pydantic import AliasChoices, BaseModel, Field

from autotoken.api_routes.input_limits import validate_list_payload_limit, validate_text_payload_limits
from autotoken.core.redaction import safe_error_summary

MAIL_ACCOUNTS_IMPORT_MAX_BYTES = 4 * 1024 * 1024
MAIL_ACCOUNTS_IMPORT_MAX_LINES = 20_000
MAIL_ACCOUNTS_BATCH_MAX_ITEMS = 2_000
MAILCOM_IMAP_HOST = "imap.mail.com"
MAILCOM_IMAP_PORT = 993
OPENAI_MOBILE_CLIENT_ID = "app_2SKx67EdpoN0G6j64rFvigXD"
OPENAI_MOBILE_REDIRECT_URI = "com.openai.chat://auth0.openai.com/ios/com.openai.chat/callback"
OPENAI_TOKEN_URL = "https://auth.openai.com/oauth/token"


class MailAccountImportParams(BaseModel):
    text: str
    sync_account_pool: bool = Field(True, validation_alias=AliasChoices("sync_account_pool", "syncAccountPool"))


class MailAccountUpsertParams(BaseModel):
    email: str = ""
    gpt_password: str = Field("", validation_alias=AliasChoices("gpt_password", "gptPassword"))
    mail_password: str = Field("", validation_alias=AliasChoices("mail_password", "mailPassword"))
    refresh_token: str = Field("", validation_alias=AliasChoices("refresh_token", "refreshToken"))
    status: str = "enabled"
    note: str = ""


class MailAccountBatchParams(BaseModel):
    emails: list[str] = Field(default_factory=list)
    note: str = ""


class MailAccountStatusParams(BaseModel):
    emails: list[str] = Field(default_factory=list)
    status: str = "enabled"


class MailAccountChangePasswordParams(BaseModel):
    emails: list[str] = Field(default_factory=list)
    new_password: str = Field("", validation_alias=AliasChoices("new_password", "newPassword"))


def _ensure_mailcom_account(account: dict[str, Any]) -> None:
    email = str(account.get("email") or "").strip().lower()
    if not email.endswith("@mail.com"):
        raise ValueError("当前模块只支持 @mail.com 邮箱")
    if not str(account.get("mail_password") or "").strip():
        raise ValueError("mail.com IMAP 检测/取件需要邮箱密码")


def _connect_mailcom(account: dict[str, Any]) -> imaplib.IMAP4_SSL:
    _ensure_mailcom_account(account)
    conn = imaplib.IMAP4_SSL(MAILCOM_IMAP_HOST, MAILCOM_IMAP_PORT, timeout=30)
    conn.login(str(account["email"]).strip(), str(account.get("mail_password") or "").strip())
    return conn


def check_mailcom_account(account: dict[str, Any]) -> dict[str, Any]:
    """Check mail.com availability using the official IMAP endpoint."""
    conn: imaplib.IMAP4_SSL | None = None
    try:
        conn = _connect_mailcom(account)
        status, data = conn.select("INBOX", readonly=True)
        if status != "OK":
            raise RuntimeError(f"IMAP INBOX 选择失败: {status}")
        count = 0
        if data and data[0]:
            try:
                count = int(data[0])
            except Exception:
                count = 0
        return {"ok": True, "message": "IMAP 登录成功", "inbox_count": count}
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


def exchange_openai_refresh_token(refresh_token: str, *, timeout: int = 30) -> dict[str, Any]:
    """Exchange an OpenAI/ChatGPT refresh token for an access token."""
    token = str(refresh_token or "").strip()
    if not token:
        raise ValueError("OpenAI refreshToken 不能为空")
    resp = requests.post(
        OPENAI_TOKEN_URL,
        json={
            "client_id": OPENAI_MOBILE_CLIENT_ID,
            "grant_type": "refresh_token",
            "redirect_uri": OPENAI_MOBILE_REDIRECT_URI,
            "refresh_token": token,
        },
        headers={"Content-Type": "application/json"},
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"OpenAI RT 换 AT 失败: HTTP {resp.status_code} {safe_error_summary(resp.text)}")
    try:
        data = resp.json()
    except Exception as exc:
        raise RuntimeError("OpenAI RT 换 AT 失败: 响应不是 JSON") from exc
    if not data.get("access_token"):
        raise RuntimeError("OpenAI RT 换 AT 失败: 响应缺少 access_token")
    return data


def _decode_header(value: Any) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(str(value))))
    except Exception:
        return str(value)


def _extract_body(msg) -> tuple[str, str]:
    texts: list[str] = []
    htmls: list[str] = []
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        content_type = part.get_content_type()
        if content_type not in {"text/plain", "text/html"}:
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            text = payload.decode(charset, errors="replace")
        except LookupError:
            text = payload.decode("utf-8", errors="replace")
        if content_type == "text/html":
            htmls.append(text)
        else:
            texts.append(text)
    return "\n".join(texts).strip(), "\n".join(htmls).strip()


def _html_to_text(html: str) -> str:
    text = re.sub(r"<(br|p|div|tr|li)\b[^>]*>", "\n", str(html or ""), flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _first_html_class_text(html: str, class_name: str) -> str:
    pattern = (
        r"<[^>]*class=[\"'][^\"']*"
        + re.escape(class_name)
        + r"[^\"']*[\"'][^>]*>(.*?)</[^>]+>"
    )
    match = re.search(pattern, str(html or ""), flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return unescape(_html_to_text(match.group(1)))


def _first_html_href(html: str, class_name: str) -> str:
    pattern = (
        r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*class=[\"'][^\"']*"
        + re.escape(class_name)
        + r"[^\"']*[\"'][^>]*>"
    )
    match = re.search(pattern, str(html or ""), flags=re.IGNORECASE | re.DOTALL)
    if match:
        return unescape(match.group(1))
    pattern = (
        r"<a\b[^>]*class=[\"'][^\"']*"
        + re.escape(class_name)
        + r"[^\"']*[\"'][^>]*href=[\"']([^\"']+)[\"']"
    )
    match = re.search(pattern, str(html or ""), flags=re.IGNORECASE | re.DOTALL)
    return unescape(match.group(1)) if match else ""


def _parse_raw_email(raw: bytes, *, fallback_id: str) -> dict[str, Any]:
    msg = email_pkg.message_from_bytes(raw)
    text, html = _extract_body(msg)
    received_at = 0
    try:
        received_at = int(parsedate_to_datetime(_decode_header(msg.get("Date", ""))).timestamp())
    except Exception:
        received_at = int(time.time())
    return {
        "id": str(msg.get("Message-ID") or fallback_id).strip(),
        "subject": _decode_header(msg.get("Subject", "")),
        "sendEmail": _decode_header(msg.get("From", "")),
        "toEmail": _decode_header(msg.get("To", "")),
        "text": text or _html_to_text(html),
        "html": html,
        "content": html or text,
        "createTime": received_at,
        "createdAt": received_at,
    }


def _normalize_web_message(item: Any, *, account: dict[str, Any], index: int) -> dict[str, Any] | None:
    if isinstance(item, str):
        item = {"text": item}
    if not isinstance(item, dict):
        return None
    subject = str(item.get("subject") or item.get("title") or item.get("mail_subject") or "").strip()
    sender = str(item.get("from") or item.get("sendEmail") or item.get("sender") or item.get("mail_from") or "").strip()
    text = str(item.get("text") or item.get("bodyPreview") or item.get("body") or item.get("message") or item.get("content") or "").strip()
    html = str(item.get("html") or item.get("mail_html") or "").strip()
    if not text and html:
        text = _html_to_text(html)
    if not (subject or sender or text or html):
        return None
    created = item.get("createTime") or item.get("createdAt") or item.get("timestamp") or item.get("received_at") or item.get("date")
    try:
        created_at = int(float(created))
        if created_at > 10_000_000_000:
            created_at = int(created_at / 1000)
    except Exception:
        created_at = int(time.time())
    result = {
        "id": str(item.get("id") or item.get("message_id") or f"web:{index}"),
        "subject": subject,
        "sendEmail": sender,
        "toEmail": str(item.get("to") or item.get("toEmail") or account.get("email") or "").strip(),
        "text": text,
        "html": html,
        "content": html or text,
        "createTime": created_at,
        "createdAt": created_at,
        "raw": item,
    }
    if item.get("viewUrl"):
        result["viewUrl"] = str(item.get("viewUrl") or "")
    return result


def _json_items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("messages", "mails", "emails", "items", "list", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _json_items(value)
            if nested:
                return nested
    return [payload] if any(payload.get(key) for key in ("subject", "text", "html", "content", "body")) else []


def _parse_web_html_messages(html: str, *, account: dict[str, Any], size: int) -> list[dict[str, Any]]:
    text = str(html or "")
    if "empty-state" in text or "收件箱暂无邮件" in text:
        return []
    if "error-msg" in text and "获取邮件失败" in text:
        raise RuntimeError("网页取件失败：获取邮件失败")

    chunks = [
        chunk
        for chunk in re.findall(r"<li\b[^>]*>(.*?)</li>", text, flags=re.IGNORECASE | re.DOTALL)
        if "email-card" in chunk or "mail" in chunk.lower()
    ]
    if not chunks:
        chunks = re.findall(
            r"<article\b[^>]*class=[\"'][^\"']*(?:mail|message|email)[^\"']*[\"'][^>]*>(.*?)</article>",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    messages: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks[: max(1, int(size or 10))]):
        subject = _first_html_class_text(chunk, "email-subject")
        sender = _first_html_class_text(chunk, "email-meta")
        date_text = _first_html_class_text(chunk, "email-date")
        view_url = _first_html_href(chunk, "btn-view")
        plain = unescape(_html_to_text(chunk))
        if not subject:
            subject_match = re.search(r"(?:主题|Subject)[:：]\s*([^\n]+)", plain, flags=re.IGNORECASE)
            subject = subject_match.group(1).strip() if subject_match else plain[:120]
        if not sender:
            from_match = re.search(r"(?:来自|发件人|From)[:：]\s*([^\n]+)", plain, flags=re.IGNORECASE)
            sender = from_match.group(1).strip() if from_match else ""
        normalized = _normalize_web_message(
            {
                "id": f"html:{index}",
                "subject": subject,
                "from": sender,
                "text": plain,
                "html": chunk,
                "date": date_text,
                "viewUrl": view_url,
            },
            account=account,
            index=index,
        )
        if normalized:
            if view_url:
                normalized["viewUrl"] = view_url
            messages.append(normalized)
    return messages


def fetch_mail_messages_via_web(account: dict[str, Any], size: int = 10) -> list[dict[str, Any]]:
    from autotoken.services.mailcom_webmail import fetch_mailcom_messages

    return fetch_mailcom_messages(account, size=size)


def fetch_mail_messages_via_imap(account: dict[str, Any], size: int = 10) -> list[dict[str, Any]]:
    """Fetch recent messages from mail.com via official IMAP fallback."""
    conn: imaplib.IMAP4_SSL | None = None
    try:
        conn = _connect_mailcom(account)
        status, _ = conn.select("INBOX", readonly=True)
        if status != "OK":
            raise RuntimeError(f"IMAP INBOX 选择失败: {status}")
        status, data = conn.search(None, "ALL")
        if status != "OK" or not data or not data[0]:
            return []
        ids = data[0].split()
        result: list[dict[str, Any]] = []
        for msg_id in ids[-max(1, int(size or 10)) :][::-1]:
            status, raw_data = conn.fetch(msg_id, "(RFC822)")
            if status != "OK" or not raw_data:
                continue
            raw = next((part[1] for part in raw_data if isinstance(part, tuple) and len(part) > 1), b"")
            if raw:
                result.append(_parse_raw_email(raw, fallback_id=msg_id.decode(errors="ignore")))
        return result
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


def fetch_mail_messages(account: dict[str, Any], size: int = 10) -> list[dict[str, Any]]:
    """Fetch recent messages using the official mail.com website login by default."""
    if str(os.environ.get("MAILCOM_FETCH_MODE") or "web").strip().lower() == "imap":
        return fetch_mail_messages_via_imap(account, size=size)
    return fetch_mail_messages_via_web(account, size=size)


def _response(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "items": items,
        "total": len(items),
        "enabled_count": sum(1 for item in items if item.get("status") == "enabled"),
        "disabled_count": sum(1 for item in items if item.get("status") == "disabled"),
        "valid_count": sum(1 for item in items if item.get("check_status") == "valid"),
        "invalid_count": sum(1 for item in items if item.get("check_status") in {"invalid", "error"}),
        "unchecked_count": sum(1 for item in items if item.get("check_status") == "unchecked"),
    }


def _validate_batch(emails: list[str]) -> None:
    validate_list_payload_limit(emails, max_items=MAIL_ACCOUNTS_BATCH_MAX_ITEMS, label="mail邮箱账号批量操作")


def create_mail_accounts_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/mail-accounts")
    def get_mail_accounts():
        from autotoken.storage import mail_accounts

        return _response(mail_accounts.list_mail_accounts())

    @router.post("/api/mail-accounts/import")
    def post_mail_accounts_import(params: MailAccountImportParams):
        from autotoken.storage import mail_accounts

        try:
            validate_text_payload_limits(
                params.text,
                max_bytes=MAIL_ACCOUNTS_IMPORT_MAX_BYTES,
                max_lines=MAIL_ACCOUNTS_IMPORT_MAX_LINES,
                label="mail邮箱导入",
            )
            result = mail_accounts.import_mail_accounts(params.text)
            imported_emails = list(result.get("emails") or [])
            sync_result = (
                mail_accounts.sync_mail_accounts_to_account_pool(imported_emails)
                if params.sync_account_pool and imported_emails
                else {"synced": 0, "emails": [], "skipped": []}
            )
            pool_status = mail_accounts.mailcom_pool_status()
            synced_emails = {
                str(email or "").strip().lower()
                for email in (sync_result.get("emails") or [])
                if str(email or "").strip()
            }
            login_emails = []
            for item in pool_status.get("items") or []:
                email = str((item or {}).get("email") or "").strip().lower()
                if not email or email not in synced_emails:
                    continue
                if str((item or {}).get("status") or "").strip().lower() != "enabled":
                    continue
                if str((item or {}).get("auth_session_status") or "").strip().lower() == "ready":
                    continue
                login_emails.append(email)
            return {
                **result,
                **_response(mail_accounts.list_mail_accounts()),
                "synced_account_pool": sync_result,
                "pool_status": pool_status,
                "login_emails": login_emails,
            }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/api/mail-accounts/pool-status")
    def get_mail_accounts_pool_status():
        from autotoken.storage import mail_accounts

        return mail_accounts.mailcom_pool_status()

    @router.post("/api/mail-accounts/sync-account-pool")
    def post_mail_accounts_sync_account_pool(params: MailAccountBatchParams):
        from autotoken.storage import mail_accounts

        _validate_batch(params.emails)
        emails = params.emails or None
        return mail_accounts.sync_mail_accounts_to_account_pool(emails)

    @router.post("/api/mail-accounts")
    def post_mail_account(params: MailAccountUpsertParams):
        from autotoken.storage import mail_accounts

        try:
            return mail_accounts.upsert_mail_account(params.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.put("/api/mail-accounts/{email}")
    def put_mail_account(email: str, params: MailAccountUpsertParams):
        from autotoken.storage import mail_accounts

        try:
            payload = params.model_dump()
            payload["email"] = email
            return mail_accounts.update_mail_account(email, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/mail-accounts/delete")
    def post_mail_accounts_delete(params: MailAccountBatchParams):
        from autotoken.storage import mail_accounts

        _validate_batch(params.emails)
        return mail_accounts.delete_mail_accounts(params.emails)

    @router.post("/api/mail-accounts/clear")
    def post_mail_accounts_clear():
        from autotoken.storage import mail_accounts

        return mail_accounts.clear_mail_accounts()

    @router.post("/api/mail-accounts/status")
    def post_mail_accounts_status(params: MailAccountStatusParams):
        from autotoken.storage import mail_accounts

        _validate_batch(params.emails)
        return mail_accounts.set_account_statuses(params.emails, params.status)

    @router.post("/api/mail-accounts/note")
    def post_mail_accounts_note(params: MailAccountBatchParams):
        from autotoken.storage import mail_accounts

        _validate_batch(params.emails)
        return mail_accounts.update_notes(params.emails, params.note)

    @router.post("/api/mail-accounts/change-password")
    def post_mail_accounts_change_password(params: MailAccountChangePasswordParams):
        from autotoken.services.mailcom_password import change_mailcom_password
        from autotoken.storage import mail_accounts

        try:
            _validate_batch(params.emails)
            new_password = str(params.new_password or "").strip()
            if not new_password:
                raise ValueError("新密码不能为空")

            results = []
            updated = 0
            failed = 0
            for email in params.emails:
                account = mail_accounts.get_mail_account(email)
                if not account:
                    failed += 1
                    results.append({"email": email, "status": "failed", "error": "mail邮箱账号不存在"})
                    continue
                try:
                    change_mailcom_password(account["email"], account.get("mail_password", ""), new_password)
                    store_result = mail_accounts.change_mail_passwords([account["email"]], new_password)
                    updated += int(store_result.get("updated") or 0)
                    results.append({"email": account["email"], "status": "success"})
                except Exception as exc:
                    failed += 1
                    results.append(
                        {
                            "email": account.get("email", email),
                            "status": "failed",
                            "error": safe_error_summary(str(exc)),
                        }
                    )
            return {"updated": updated, "failed": failed, "results": results}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/api/mail-accounts/export")
    def get_mail_accounts_export():
        from autotoken.storage import mail_accounts

        return {"content": mail_accounts.export_mail_accounts()}

    @router.post("/api/mail-accounts/check")
    def post_mail_accounts_check(params: MailAccountBatchParams):
        from autotoken.storage import mail_accounts

        _validate_batch(params.emails)
        results = []
        for email in params.emails:
            account = mail_accounts.get_mail_account(email)
            if not account:
                raise HTTPException(status_code=404, detail=f"mail邮箱账号不存在: {email}")
            try:
                token_data = exchange_openai_refresh_token(account.get("refresh_token", ""))
                updated = mail_accounts.update_check_result(
                    account["email"],
                    check_status="valid",
                    access_token=str(token_data.get("access_token") or ""),
                    refresh_token=str(token_data.get("refresh_token") or account.get("refresh_token") or ""),
                    error="",
                )
            except Exception as exc:
                updated = mail_accounts.update_check_result(
                    account["email"],
                    check_status="invalid",
                    access_token="",
                    refresh_token=str(account.get("refresh_token") or ""),
                    error=safe_error_summary(exc),
                )
            results.append(updated)
        return {"checked": len(results), "results": results}

    @router.post("/api/mail-accounts/fetch")
    def post_mail_accounts_fetch(params: MailAccountBatchParams):
        from autotoken.storage import mail_accounts

        _validate_batch(params.emails)
        results = []
        for email in params.emails:
            account = mail_accounts.get_mail_account(email)
            if not account:
                raise HTTPException(status_code=404, detail=f"mail邮箱账号不存在: {email}")
            try:
                messages = fetch_mail_messages(account, size=10)
                mail_accounts.update_check_result(
                    account["email"],
                    check_status="valid",
                    access_token="",
                    refresh_token=str(account.get("refresh_token") or ""),
                    error="",
                )
                results.append({"email": account["email"], "status": "ok", "messages": messages})
            except Exception as exc:
                results.append({"email": account["email"], "status": "error", "error": safe_error_summary(exc)})
        return {"fetched": len(results), "results": results}

    return router
