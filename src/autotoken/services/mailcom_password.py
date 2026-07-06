"""Protocol-level mail.com password change implementation."""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urljoin

import requests

from autotoken.core.redaction import safe_error_summary

MAILCOM_CISS_LOGIN_URL = "https://account.mail.com/ciss/login"


def _headers(referer: str = "") -> dict[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def _first_form(html_text: str, *, form_id: str) -> str:
    match = re.search(
        rf"<form\b(?=[^>]*id=[\"']{re.escape(form_id)}[\"'])[^>]*>.*?</form>",
        str(html_text or ""),
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        raise RuntimeError(f"mail.com 页面缺少表单: {form_id}")
    return match.group(0)


def _attr(tag: str, name: str) -> str:
    match = re.search(rf"{re.escape(name)}=[\"']([^\"']*)[\"']", tag, flags=re.IGNORECASE | re.DOTALL)
    return html.unescape(match.group(1)) if match else ""


def _form_action(form_html: str, base_url: str) -> str:
    form_open = re.search(r"<form\b[^>]*>", form_html, flags=re.IGNORECASE | re.DOTALL)
    if not form_open:
        raise RuntimeError("mail.com 表单缺少 form 标签")
    action = _attr(form_open.group(0), "action")
    if not action:
        raise RuntimeError("mail.com 表单缺少 action")
    return urljoin(base_url, action)


def _input_fields(form_html: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for match in re.finditer(r"<input\b([^>]*)>", str(form_html or ""), flags=re.IGNORECASE | re.DOTALL):
        tag = match.group(0)
        name = _attr(tag, "name")
        if not name:
            continue
        fields[name] = _attr(tag, "value")
    return fields


def _find_name(fields: dict[str, str], contains: str) -> str:
    needle = contains.lower()
    for name in fields:
        if needle in name.lower():
            return name
    raise RuntimeError(f"mail.com 改密表单缺少字段: {contains}")


def _extract_change_password_link(overview_html: str) -> str:
    for href in re.findall(r"href=[\"']([^\"']+)[\"']", str(overview_html or ""), flags=re.IGNORECASE):
        value = html.unescape(href)
        if "changePasswordLink" in value:
            return value
    raise RuntimeError("mail.com My Account 未找到 Change password 链接")


def _page_error_message(html_text: str) -> str:
    text = str(html_text or "")
    error_match = re.search(
        r"<section\b[^>]*class=[\"'][^\"']*hint-error[^\"']*[\"'][^>]*>(.*?)</section>",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if error_match:
        clean = re.sub(r"<[^>]+>", " ", error_match.group(1))
        return re.sub(r"\s+", " ", html.unescape(clean)).strip()
    return ""


def change_mailcom_password(
    email: str,
    old_password: str,
    new_password: str,
    *,
    session_factory=requests.Session,
    timeout: int = 30,
) -> dict[str, Any]:
    """Log in to mail.com CISS and submit the official password-change form."""
    email = str(email or "").strip().lower()
    old_password = str(old_password or "")
    new_password = str(new_password or "")
    if not email.endswith("@mail.com"):
        raise ValueError("只支持 @mail.com 邮箱")
    if not old_password:
        raise ValueError("旧邮箱密码不能为空")
    if len(new_password) < 12:
        raise ValueError("mail.com 新密码至少需要 12 个字符")

    session = session_factory()
    login_page = session.get(MAILCOM_CISS_LOGIN_URL, headers=_headers(), timeout=timeout)
    if login_page.status_code != 200:
        raise RuntimeError(f"mail.com CISS 登录页获取失败: HTTP {login_page.status_code}")

    login_form = _first_form(login_page.text, form_id="loginForm")
    login_action = _form_action(login_form, login_page.url or MAILCOM_CISS_LOGIN_URL)
    login_data = _input_fields(login_form)
    login_data["username"] = email
    login_data["password"] = old_password
    login_resp = session.post(
        login_action,
        data=login_data,
        headers={**_headers(MAILCOM_CISS_LOGIN_URL), "Origin": "https://account.mail.com"},
        timeout=timeout,
        allow_redirects=False,
    )
    location = login_resp.headers.get("location", "")
    if login_resp.status_code not in {302, 303} or not location:
        error = _page_error_message(login_resp.text)
        raise RuntimeError(error or f"mail.com CISS 登录失败: HTTP {login_resp.status_code}")

    overview = session.get(urljoin(login_action, location), headers=_headers(MAILCOM_CISS_LOGIN_URL), timeout=timeout)
    if overview.status_code != 200:
        raise RuntimeError(f"mail.com My Account 打开失败: HTTP {overview.status_code}")
    change_link = _extract_change_password_link(overview.text)

    password_page = session.get(urljoin(overview.url, change_link), headers=_headers(overview.url), timeout=timeout)
    if password_page.status_code != 200:
        raise RuntimeError(f"mail.com 改密页打开失败: HTTP {password_page.status_code}")
    password_form = _first_form(password_page.text, form_id="id3")
    password_action = _form_action(password_form, password_page.url)
    separator = "&" if "?" in password_action else "?"
    password_action = f"{password_action}{separator}saveChanges=x"
    fields = _input_fields(password_form)
    current_name = _find_name(fields, "currentPasswordPanel")
    new_name = _find_name(fields, "newPasswordFieldPanel")
    retype_name = _find_name(fields, "retypeNewPasswordFieldPanel")
    fields[current_name] = old_password
    fields[new_name] = new_password
    fields[retype_name] = new_password

    result = session.post(
        password_action,
        data=fields,
        headers={
            **_headers(password_page.url),
            "Origin": "https://account.mail.com",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        timeout=timeout,
        allow_redirects=True,
    )
    if result.status_code != 200:
        raise RuntimeError(f"mail.com 改密提交失败: HTTP {result.status_code} {safe_error_summary(result.text)}")
    error = _page_error_message(result.text)
    if error:
        raise RuntimeError(error)
    if "hint-success" not in result.text and "Password changed" not in result.text and "My Account" not in result.text:
        raise RuntimeError("mail.com 改密结果未知")
    return {"status": "success", "email": email}
