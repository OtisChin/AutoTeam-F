"""ChatGPT HTTP/session cookie helpers shared by payment flows."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Any

from autotoken.core.jwt import decode_jwt_payload

logger = logging.getLogger(__name__)

CHATGPT_SESSION_COOKIE = "__Secure-next-auth.session-token"


def access_token_claims(access_token: str) -> dict[str, Any]:
    return decode_jwt_payload(access_token)


def account_id_from_access_token(access_token: str) -> str:
    claims = access_token_claims(access_token)
    auth_claims = claims.get("https://api.openai.com/auth")
    if isinstance(auth_claims, dict):
        return str(auth_claims.get("chatgpt_account_id") or "").strip()
    return ""


def email_from_access_token(access_token: str) -> str:
    claims = access_token_claims(access_token)
    profile = claims.get("https://api.openai.com/profile")
    if isinstance(profile, dict):
        return str(profile.get("email") or "").strip()
    return ""


def extract_auth_session_context(
    email: str,
    *,
    load_session: Callable[[str], Any],
    auth_file_context: dict[str, Any] | None = None,
) -> dict[str, str]:
    session = load_session(email)
    session = session if isinstance(session, dict) else {}
    account = session.get("account") if isinstance(session.get("account"), dict) else {}
    auth_file_context = auth_file_context if isinstance(auth_file_context, dict) else {}
    session_access_token = str(session.get("accessToken") or session.get("access_token") or "").strip()
    access_token = session_access_token or str(auth_file_context.get("access_token") or "").strip()
    jwt_account_id = account_id_from_access_token(access_token) if access_token else ""
    return {
        "access_token": access_token,
        "session_token": str(session.get("sessionToken") or session.get("session_token") or "").strip(),
        "cookie_header": str(session.get("cookie_header") or "").strip(),
        "account_id": str(
            session.get("account_id")
            or session.get("accountId")
            or account.get("id")
            or account.get("account_id")
            or auth_file_context.get("account_id")
            or jwt_account_id
            or ""
        ).strip(),
        "device_id": str(
            session.get("device_id") or session.get("oai_device_id") or session.get("oaiDeviceId") or ""
        ).strip(),
        "user_agent": str(session.get("user_agent") or session.get("userAgent") or "").strip(),
        "openai_sentinel_token": str(
            session.get("openai_sentinel_token")
            or session.get("openaiSentinelToken")
            or session.get("sentinel_token")
            or ""
        ).strip(),
        "oai_client_version": str(session.get("oai_client_version") or session.get("oaiClientVersion") or "").strip(),
        "oai_client_build_number": str(
            session.get("oai_client_build_number") or session.get("oaiClientBuildNumber") or ""
        ).strip(),
    }


def chatgpt_cookie_header(session_token: str = "", account_id: str = "", device_id: str = "") -> str:
    parts: list[str] = []
    token = str(session_token or "").strip()
    if token:
        if len(token) > 3800:
            parts.append(f"{CHATGPT_SESSION_COOKIE}.0={token[:3800]}")
            parts.append(f"{CHATGPT_SESSION_COOKIE}.1={token[3800:]}")
        else:
            parts.append(f"{CHATGPT_SESSION_COOKIE}={token}")
    if account_id:
        parts.append(f"_account={account_id}")
    if device_id:
        parts.append(f"oai-did={device_id}")
    return "; ".join(parts)


def chatgpt_reference_cookie_header(
    session_token: str = "",
    account_id: str = "",
    device_id: str = "",
    cookie_header: str = "",
) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for raw in str(cookie_header or "").split(";"):
        item = raw.strip()
        if not item or "=" not in item:
            continue
        name = item.split("=", 1)[0].strip()
        if name and name not in seen:
            seen.add(name)
            parts.append(item)

    token = str(session_token or "").strip()
    has_session_cookie = any(
        name == CHATGPT_SESSION_COOKIE or name.startswith(f"{CHATGPT_SESSION_COOKIE}.")
        for name in seen
    )
    if token and not has_session_cookie:
        parts.append(f"{CHATGPT_SESSION_COOKIE}={token}")
        seen.add(CHATGPT_SESSION_COOKIE)
    if account_id and "_account" not in seen:
        parts.append(f"_account={account_id}")
        seen.add("_account")
    if device_id and "oai-did" not in seen:
        parts.append(f"oai-did={device_id}")
    return "; ".join(parts)


def merge_cookie_headers(*headers: str) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for header in headers:
        for raw in str(header or "").split(";"):
            item = raw.strip()
            if not item or "=" not in item:
                continue
            name = item.split("=", 1)[0].strip()
            if not name or name in seen:
                continue
            seen.add(name)
            parts.append(item)
    return "; ".join(parts)


def cookie_header_from_cookie_items(cookies: Any) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for cookie in cookies or []:
        if not isinstance(cookie, dict):
            continue
        name = str(cookie.get("name") or "").strip()
        value = str(cookie.get("value") or "").strip()
        if not name or not value or name in seen:
            continue
        seen.add(name)
        parts.append(f"{name}={value}")
    return "; ".join(parts)


def chatgpt_checkout_headers(
    *,
    access_token: str,
    checkout_session_id: str,
    processor_entity: str,
    cookie_header: str = "",
    account_id: str = "",
    device_id: str = "",
    target_path: str = "",
    openai_sentinel_token: str = "",
) -> dict[str, str]:
    headers = {
        "accept": "*/*",
        "content-type": "application/json",
        "origin": "https://chatgpt.com",
        "referer": f"https://chatgpt.com/checkout/{processor_entity}/{checkout_session_id}",
        "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
    }
    if target_path:
        headers["x-openai-target-path"] = target_path
        headers["x-openai-target-route"] = target_path
    if access_token:
        headers["authorization"] = f"Bearer {access_token}"
    if cookie_header:
        headers["cookie"] = cookie_header
    if device_id:
        headers["oai-device-id"] = device_id
    if account_id:
        headers["chatgpt-account-id"] = account_id
    if openai_sentinel_token:
        headers["openai-sentinel-token"] = openai_sentinel_token
    return headers


def chatgpt_verify_checkout_result(status_code: int, body: str = "") -> dict[str, Any]:
    if status_code == 200:
        return {"state": "succeeded", "verify": {"status": status_code}}
    return {"state": "verify_timeout", "verify": {"status": status_code, "body": str(body or "")[:500]}}


def session_token_from_cookie_header(cookie_header: str) -> str:
    parts: dict[str, str] = {}
    token = ""
    for raw_part in str(cookie_header or "").split(";"):
        if "=" not in raw_part:
            continue
        name, value = raw_part.split("=", 1)
        name = name.strip()
        value = value.strip()
        if name == CHATGPT_SESSION_COOKIE:
            token = value
        elif name.startswith(f"{CHATGPT_SESSION_COOKIE}."):
            suffix = name.rsplit(".", 1)[-1]
            if suffix.isdigit():
                parts[suffix] = value
    if token:
        return token
    if parts:
        return "".join(parts[key] for key in sorted(parts, key=lambda item: int(item)))
    return ""


def session_token_from_cookie_items(cookies: Any) -> str:
    parts: dict[str, str] = {}
    token = ""
    for cookie in cookies or []:
        if not isinstance(cookie, dict):
            continue
        name = str(cookie.get("name") or "").strip()
        value = str(cookie.get("value") or "").strip()
        if not name or not value:
            continue
        if name == CHATGPT_SESSION_COOKIE:
            token = value
        elif name.startswith(f"{CHATGPT_SESSION_COOKIE}."):
            suffix = name.rsplit(".", 1)[-1]
            if suffix.isdigit():
                parts[suffix] = value
    if token:
        return token
    if parts:
        return "".join(parts[key] for key in sorted(parts, key=lambda item: int(item)))
    return ""


def session_token_from_cookie_jar(cookies: Any, *, domain_contains: str = "") -> str:
    try:
        direct = cookies.get(CHATGPT_SESSION_COOKIE, "") or ""
    except Exception:
        direct = ""
    if direct:
        return str(direct)

    cookie_items: list[dict[str, str]] = []
    try:
        jar_iter = list(cookies)
    except Exception:
        jar_iter = []
    domain_filter = str(domain_contains or "").strip().lower()
    for cookie in jar_iter:
        try:
            name = str(getattr(cookie, "name", "") or "").strip()
            value = str(getattr(cookie, "value", "") or "").strip()
            domain = str(getattr(cookie, "domain", "") or "").strip().lower()
        except Exception:
            continue
        if domain_filter and domain and domain_filter not in domain:
            continue
        if not name or not value:
            continue
        cookie_items.append({"name": name, "value": value})
    return session_token_from_cookie_items(cookie_items)


def http_session_cookie_header(http: Any, *, domain: str = "chatgpt.com") -> str:
    try:
        cookies = getattr(http, "cookies", None)
        if not cookies:
            return ""
        if hasattr(cookies, "get_dict"):
            items = cookies.get_dict(domain=domain).items()
            fallback_items = cookies.get_dict().items()
            pairs = list(items) or list(fallback_items)
        else:
            pairs = [(cookie.name, cookie.value) for cookie in cookies]
        return "; ".join(f"{name}={value}" for name, value in pairs if name and value)
    except Exception:
        return ""


def configure_chatgpt_http_session(
    http: Any,
    *,
    access_token: str,
    session_token: str = "",
    cookie_header: str = "",
    account_id: str = "",
    device_id: str = "",
    user_agent: str = "",
    openai_sentinel_token: str = "",
    oai_client_version: str = "",
    oai_client_build_number: str = "",
) -> dict[str, str]:
    resolved_device_id = str(device_id or "").strip() or str(uuid.uuid4())
    resolved_user_agent = str(user_agent or "").strip() or (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
    )
    resolved_cookie = chatgpt_reference_cookie_header(
        session_token=session_token,
        account_id=account_id,
        device_id=resolved_device_id,
        cookie_header=cookie_header,
    )
    headers = {
        "User-Agent": resolved_user_agent,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://chatgpt.com",
        "Referer": "https://chatgpt.com/",
        "Content-Type": "application/json",
        "oai-device-id": resolved_device_id,
        "oai-language": "en-US",
        "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    if openai_sentinel_token:
        headers["openai-sentinel-token"] = openai_sentinel_token
    if oai_client_version:
        headers["oai-client-version"] = oai_client_version
    if oai_client_build_number:
        headers["oai-client-build-number"] = oai_client_build_number
    if resolved_cookie:
        headers["Cookie"] = resolved_cookie
    try:
        http.headers.update(headers)
        http._oai_device_id = resolved_device_id  # type: ignore[attr-defined]
        http._chatgpt_cookie_header = resolved_cookie  # type: ignore[attr-defined]
    except Exception:
        pass
    return {"device_id": resolved_device_id, "cookie_header": resolved_cookie}


def playwright_cookie_items_from_header(cookie_header: str) -> list[dict[str, str]]:
    cookies: list[dict[str, str]] = []
    seen: set[str] = set()
    cookie_attribute_names = {"domain", "expires", "httponly", "max-age", "path", "samesite", "secure"}
    for raw in str(cookie_header or "").split(";"):
        if "=" not in raw:
            continue
        name, value = raw.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name or not value or name in seen:
            continue
        if name.lower() in cookie_attribute_names:
            continue
        if any(ord(ch) < 33 or ch in '()<>@,;:\\"/[]?={} ' for ch in name):
            continue
        if name == CHATGPT_SESSION_COOKIE and len(value) > 3800:
            for split_name, split_value in (
                (f"{CHATGPT_SESSION_COOKIE}.0", value[:3800]),
                (f"{CHATGPT_SESSION_COOKIE}.1", value[3800:]),
            ):
                if split_name not in seen:
                    seen.add(split_name)
                    cookies.append({"name": split_name, "value": split_value, "url": "https://chatgpt.com/"})
            seen.add(name)
            continue
        seen.add(name)
        cookies.append({"name": name, "value": value, "url": "https://chatgpt.com/"})
    return cookies


def inject_chatgpt_browser_cookies(
    api: Any,
    *,
    session_token: str = "",
    cookie_header: str = "",
    account_id: str = "",
    device_id: str = "",
    missing_context_error_factory: Callable[[], Exception] | None = None,
) -> None:
    if not getattr(api, "context", None):
        if callable(missing_context_error_factory):
            raise missing_context_error_factory()
        raise RuntimeError("浏览器上下文未初始化，无法注入 ChatGPT 登录态")

    cookies = playwright_cookie_items_from_header(cookie_header)
    seen = {str(cookie.get("name") or "") for cookie in cookies}

    token = str(session_token or "").strip()
    has_session_cookie = any(
        name in seen
        for name in (
            CHATGPT_SESSION_COOKIE,
            f"{CHATGPT_SESSION_COOKIE}.0",
            f"{CHATGPT_SESSION_COOKIE}.1",
        )
    )
    if token and not has_session_cookie:
        if len(token) > 4000:
            token_cookies = [
                (f"{CHATGPT_SESSION_COOKIE}.0", token[:4000]),
                (f"{CHATGPT_SESSION_COOKIE}.1", token[4000:]),
            ]
        else:
            token_cookies = [(CHATGPT_SESSION_COOKIE, token)]
        for name, value in token_cookies:
            seen.add(name)
            cookies.append({"name": name, "value": value, "url": "https://chatgpt.com/"})

    if account_id and "_account" not in seen:
        cookies.append({"name": "_account", "value": account_id, "url": "https://chatgpt.com/"})
    if device_id and "oai-did" not in seen:
        cookies.append({"name": "oai-did", "value": device_id, "url": "https://chatgpt.com/"})
    if cookies:
        api.context.add_cookies(cookies)
        logger.info(
            "[chatgpt_session] injected ChatGPT browser cookies: count=%s session_split=%s full_session=%s",
            len(cookies),
            any(cookie.get("name") == f"{CHATGPT_SESSION_COOKIE}.0" for cookie in cookies),
            any(cookie.get("name") == CHATGPT_SESSION_COOKIE for cookie in cookies),
        )
