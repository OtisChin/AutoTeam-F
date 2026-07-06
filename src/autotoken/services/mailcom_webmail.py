"""Protocol-level mail.com Lightmailer inbox fetching."""

from __future__ import annotations

import html
import re
import time
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import requests

from autotoken.core.redaction import safe_error_summary
from autotoken.services.mailcom_password import _attr, _form_action, _headers, _input_fields

MAILCOM_HOME_URL = "https://www.mail.com/"
MAILCOM_LIGHTMAILER_FOLDERLIST_URL = "https://lightmailer.mail.com/folderlist?tep=startup&fcs=true"


def _clean_text(value: str) -> str:
    value = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", str(value or ""), flags=re.IGNORECASE | re.DOTALL)
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"</(?:p|div|li|tr|h[1-6])>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _first_html_class_text(text: str, class_name: str) -> str:
    match = re.search(
        rf"<[^>]*class=[\"'][^\"']*{re.escape(class_name)}[^\"']*[\"'][^>]*>(.*?)</[^>]+>",
        str(text or ""),
        flags=re.IGNORECASE | re.DOTALL,
    )
    return _clean_text(match.group(1)) if match else ""


def _first_html_class_attr(text: str, class_name: str, attr_name: str) -> str:
    match = re.search(
        rf"<[^>]*class=[\"'][^\"']*{re.escape(class_name)}[^\"']*[\"'][^>]*>",
        str(text or ""),
        flags=re.IGNORECASE | re.DOTALL,
    )
    return _attr(match.group(0), attr_name) if match else ""


def _first_href(text: str, class_name: str = "") -> str:
    pattern = (
        rf"<a\b(?=[^>]*class=[\"'][^\"']*{re.escape(class_name)}[^\"']*[\"'])[^>]*href=[\"']([^\"']+)[\"']"
        if class_name
        else r"<a\b[^>]*href=[\"']([^\"']+)[\"']"
    )
    match = re.search(pattern, str(text or ""), flags=re.IGNORECASE | re.DOTALL)
    return html.unescape(match.group(1)) if match else ""


def _first_form_by_login_marker(text: str) -> str:
    match = re.search(
        r"<form\b(?=[^>]*data-mod-name=[\"']loginform[\"'])[^>]*>.*?</form>",
        str(text or ""),
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        raise RuntimeError("mail.com 首页缺少登录表单")
    return match.group(0)


def _extract_lightmailer_url(text: str) -> str:
    match = re.search(r"https://lightmailer\.mail\.com/start\?[^\"' <]+", str(text or ""), flags=re.IGNORECASE)
    if not match:
        raise RuntimeError("mail.com 登录跳转页缺少 Lightmailer 地址")
    return html.unescape(match.group(0))


def _extract_inbox_url(folderlist_html: str, base_url: str) -> str:
    match = re.search(
        r"<a\b(?=[^>]*href=[\"']([^\"']*messagelist\?folderId=[^\"']+)[\"'])(?=[^>]*data-webdriver=[\"']INBOX:Inbox[\"'])",
        str(folderlist_html or ""),
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        raise RuntimeError("mail.com Lightmailer 未找到 Inbox 链接")
    return urljoin(base_url, html.unescape(match.group(1)))


def _message_chunks(message_list_html: str) -> list[str]:
    text = str(message_list_html or "")
    starts = [
        match.start()
        for match in re.finditer(
            r"<li\b[^>]*class=[\"'][^\"']*message-list__item[^\"']*mail-panel[^\"']*[\"'][^>]*>",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    ]
    chunks = [text[start : (starts[index + 1] if index + 1 < len(starts) else len(text))] for index, start in enumerate(starts)]
    return [chunk for chunk in chunks if "message-list__link" in chunk]


def _parse_mailcom_date(value: str) -> int:
    text = str(value or "").strip()
    for fmt in ("%A, %B %d, %Y at %I:%M %p", "%B %d, %Y at %I:%M %p", "%m/%d/%y"):
        try:
            return int(datetime.strptime(text, fmt).timestamp())
        except Exception:
            pass
    return int(time.time())


def _mail_id_from_href(href: str, fallback: str) -> str:
    query = parse_qs(urlparse(str(href or "")).query)
    return str((query.get("mailId") or [fallback])[0])


def _body_url_from_detail(detail_html: str, detail_url: str) -> str:
    match = re.search(
        r"<iframe\b(?=[^>]*id=[\"']bodyIFrame[\"'])[^>]*src=[\"']([^\"']+)[\"']",
        str(detail_html or ""),
        flags=re.IGNORECASE | re.DOTALL,
    )
    return urljoin(detail_url, html.unescape(match.group(1))) if match else ""


def _normalize_message(
    chunk: str,
    *,
    account: dict[str, Any],
    index: int,
    base_url: str,
) -> dict[str, Any] | None:
    href = _first_href(chunk, "message-list__link")
    subject = _first_html_class_text(chunk, "mail-header__subject")
    sender = _first_html_class_attr(chunk, "mail-header__sender", "title") or _first_html_class_text(chunk, "mail-header__sender")
    date_text = _first_html_class_attr(chunk, "mail-header__date", "title") or _first_html_class_text(chunk, "mail-header__date")
    if not (href or subject or sender):
        return None
    view_url = urljoin(base_url, href) if href else ""
    created_at = _parse_mailcom_date(date_text)
    mail_id = _mail_id_from_href(href, f"lightmailer:{index}")
    return {
        "id": mail_id,
        "subject": subject,
        "sendEmail": sender,
        "toEmail": str(account.get("email") or "").strip(),
        "text": "",
        "html": "",
        "content": "",
        "createTime": created_at,
        "createdAt": created_at,
        "viewUrl": view_url,
        "raw": {"date": date_text, "source": "mail.com-lightmailer"},
    }


def _login_lightmailer(account: dict[str, Any], *, session: requests.Session, timeout: int) -> str:
    email = str(account.get("email") or "").strip().lower()
    password = str(account.get("mail_password") or "").strip()
    if not email.endswith("@mail.com"):
        raise ValueError("只支持 @mail.com 邮箱")
    if not password:
        raise ValueError("mail.com 官网取件需要邮箱密码")

    home = session.get(MAILCOM_HOME_URL, headers=_headers(), timeout=timeout)
    if home.status_code != 200:
        raise RuntimeError(f"mail.com 首页获取失败: HTTP {home.status_code}")

    login_form = _first_form_by_login_marker(home.text)
    login_action = _form_action(login_form, home.url or MAILCOM_HOME_URL)
    login_data = _input_fields(login_form)
    login_data["username"] = email
    login_data["password"] = password
    login_resp = session.post(
        login_action,
        data=login_data,
        headers={**_headers(home.url or MAILCOM_HOME_URL), "Origin": "https://www.mail.com"},
        timeout=timeout,
        allow_redirects=False,
    )
    location = login_resp.headers.get("location", "")
    if login_resp.status_code not in {302, 303} or not location:
        raise RuntimeError(f"mail.com 官网登录失败: HTTP {login_resp.status_code} {safe_error_summary(login_resp.text)}")

    navigator = session.get(urljoin(login_action, location), headers=_headers(login_action), timeout=timeout)
    if navigator.status_code != 200:
        raise RuntimeError(f"mail.com 登录跳转页打开失败: HTTP {navigator.status_code}")
    lightmailer_url = _extract_lightmailer_url(navigator.text)
    start = session.get(lightmailer_url, headers=_headers(navigator.url), timeout=timeout, allow_redirects=True)
    if start.status_code != 200:
        raise RuntimeError(f"mail.com Lightmailer 启动失败: HTTP {start.status_code}")
    return start.url


def fetch_mailcom_messages(
    account: dict[str, Any],
    *,
    size: int = 10,
    session_factory=requests.Session,
    timeout: int = 30,
) -> list[dict[str, Any]]:
    """Log in to the official mail.com Lightmailer and fetch recent Inbox messages."""
    session = session_factory()
    start_url = _login_lightmailer(account, session=session, timeout=timeout)

    folderlist = session.get(MAILCOM_LIGHTMAILER_FOLDERLIST_URL, headers=_headers(start_url), timeout=timeout)
    if folderlist.status_code != 200:
        raise RuntimeError(f"mail.com 文件夹列表获取失败: HTTP {folderlist.status_code}")
    inbox_url = _extract_inbox_url(folderlist.text, folderlist.url)

    message_list = session.get(inbox_url, headers=_headers(folderlist.url), timeout=timeout)
    if message_list.status_code != 200:
        raise RuntimeError(f"mail.com 收件箱获取失败: HTTP {message_list.status_code}")

    messages: list[dict[str, Any]] = []
    for index, chunk in enumerate(_message_chunks(message_list.text)[: max(1, int(size or 10))]):
        message = _normalize_message(chunk, account=account, index=index, base_url=message_list.url)
        if not message:
            continue
        if message.get("viewUrl"):
            detail = session.get(str(message["viewUrl"]), headers=_headers(message_list.url), timeout=timeout)
            if detail.status_code == 200:
                body_url = _body_url_from_detail(detail.text, detail.url)
                if body_url:
                    body = session.get(body_url, headers=_headers(detail.url), timeout=timeout)
                    if body.status_code == 200:
                        message["html"] = body.text
                        message["text"] = _clean_text(body.text)
                        message["content"] = body.text
        messages.append(message)
    return messages
