"""Codex 认证管理 - OAuth 登录、token 管理、保存 CPA 兼容认证文件"""

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

import autotoken.core.display  # noqa: F401
from autotoken.core.jwt import decode_jwt_payload
from autotoken.core.oauth_helper import oauth_helper_auth_url
from autotoken.core.paths import PROJECT_ROOT
from autotoken.core.redaction import compact_log_text as _compact_log_text
from autotoken.core.textio import write_text
from autotoken.core.url_params import first_url_param, has_url_param
from autotoken.services import chatgpt_session as chatgpt_session_service
from autotoken.services import sms_otp as sms_otp_service
from autotoken.settings.admin_state import (
    get_admin_email,
    get_admin_session_token,
    get_chatgpt_account_id,
    get_chatgpt_workspace_name,
)
from autotoken.settings.config import get_playwright_launch_options, normalize_proxy_url
from autotoken.storage import sqlite_store
from autotoken.storage.auth_files import (
    codex_auth_path,
    delete_auth_file,
    iter_auth_files_for_email,
    iter_codex_auth_files,
)
from autotoken.storage.auth_index import delete_codex_auth_file, upsert_codex_auth_file
from autotoken.storage.auth_storage import AUTH_DIR, ensure_auth_dir, ensure_auth_file_permissions

logger = logging.getLogger(__name__)

SCREENSHOT_DIR = PROJECT_ROOT / "screenshots"
OAUTH_HELPER_EXTENSION_DIR = Path(__file__).resolve().parents[1] / "oauth_helper_extension"
LOGIN_OTP_TIMEOUT_SECONDS = max(10, int(os.environ.get("CODEX_OAUTH_OTP_TIMEOUT", "90") or "90"))
LOGIN_OTP_GRACE_SECONDS = max(0, int(os.environ.get("CODEX_OAUTH_OTP_GRACE_SECONDS", "120") or "120"))
LOGIN_OTP_INITIAL_DELAY_SECONDS = max(0, int(os.environ.get("CODEX_OAUTH_OTP_INITIAL_DELAY", "10") or "10"))

# Codex OAuth 配置
CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_AUTH_URL = "https://auth.openai.com/oauth/authorize"
CODEX_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_CALLBACK_PORT = 1455
CODEX_REDIRECT_URI = f"http://localhost:{CODEX_CALLBACK_PORT}/auth/callback"
DEFAULT_CHROME_CDP_URL = "http://127.0.0.1:9222"


def _launch_codex_oauth_chromium(
    playwright,
    *,
    headless: bool = False,
    proxy_url: str | None = None,
    proxy_bypass: str | None = None,
):
    """Launch the stable Chromium context used by Codex OAuth.

    Keep this path close to the original working flow: no random JS fingerprint
    injection and no persistent profile. Randomized stealth patches are useful in
    some scraping contexts, but OpenAI auth/Cloudflare is sensitive to incoherent
    browser surfaces.
    """
    launch_options = get_playwright_launch_options(
        proxy_url=proxy_url,
        proxy_bypass=proxy_bypass,
        headless=headless,
    )
    if proxy_url:
        logger.info("[Codex] OAuth browser proxy enabled")
    browser = playwright.chromium.launch(**launch_options)
    context = browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/146.0.0.0 Safari/537.36"
        ),
    )
    return browser, context


def _close_codex_oauth_chromium(browser, context) -> None:
    for obj in (context, browser):
        try:
            if obj:
                obj.close()
        except Exception:
            pass


class CodexOAuthPhoneRequired(RuntimeError):
    """Codex OAuth was blocked by OpenAI's phone verification gate."""

    def __init__(self, url: str = ""):
        self.url = url or ""
        message = "Codex OAuth 需要手机号验证"
        if self.url:
            message = f"{message}: {self.url}"
        super().__init__(message)


class CodexOAuthPhoneRateLimited(RuntimeError):
    """OpenAI rejected add-phone because the GPT account requested phone verification too often."""

    def __init__(self, detail: str = ""):
        self.detail = detail or ""
        message = "Codex OAuth 手机号验证请求次数过多，跳过当前账号"
        if self.detail:
            message = f"{message}: {self.detail}"
        super().__init__(message)


class CodexOAuthHeroSmsFirstCodeTimeout(RuntimeError):
    """Hero-SMS did not receive the first OTP within the expected window."""


class CodexOAuthLoginRequired(RuntimeError):
    """Codex OAuth stopped on the OpenAI login page instead of reaching the callback."""

    def __init__(self, url: str = ""):
        self.url = url or ""
        message = "Codex OAuth 停在登录页，未获取 authorization code"
        if self.url:
            message = f"{message}: {self.url}"
        super().__init__(message)


class CodexOAuthAccountDeactivated(RuntimeError):
    """Codex OAuth reported account_deactivated during verification."""

    def __init__(self, detail: str = ""):
        self.detail = detail or ""
        message = "Codex OAuth 账号已停用(account_deactivated)"
        if self.detail:
            message = f"{message}: {self.detail}"
        super().__init__(message)


class ChromeCDPUnavailable(RuntimeError):
    """Local Chrome remote debugging endpoint is not available."""


class ChromeCDPFlowError(RuntimeError):
    """Local Chrome CDP OAuth flow failed before returning an auth code."""


class WindowsUIFlowError(RuntimeError):
    """Windows desktop browser automation failed."""


class CodexProtocolOAuthError(RuntimeError):
    """Protocol-only Codex OAuth flow failed."""

    def __init__(self, message: str, *, final_url: str = "", body: str = ""):
        self.final_url = final_url or ""
        self.body = body or ""
        detail = message
        if self.final_url:
            detail = f"{detail}: {self.final_url}"
        super().__init__(detail)


def _generate_pkce():
    """生成 PKCE code_verifier 和 code_challenge"""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _parse_jwt_payload(token):
    """解析 JWT payload（不验证签名）"""
    return decode_jwt_payload(token)


def _extract_plan_from_token_claims(claims: dict) -> str:
    auth_claims = claims.get("https://api.openai.com/auth", {}) if isinstance(claims, dict) else {}
    if not isinstance(auth_claims, dict):
        return "unknown"
    return str(auth_claims.get("chatgpt_plan_type") or "unknown").strip().lower() or "unknown"


def _is_personal_codex_plan(plan: str | None) -> bool:
    return (plan or "").strip().lower() in {"free", "plus", "pro"}


def _build_bundle_from_token_response(token_data: dict, fallback_email=None):
    id_token = str(token_data.get("id_token") or "")
    access_token = str(token_data.get("access_token") or "")
    claims = _parse_jwt_payload(id_token)
    access_claims = _parse_jwt_payload(access_token)

    auth_claims = claims.get("https://api.openai.com/auth", {}) if isinstance(claims, dict) else {}
    if not isinstance(auth_claims, dict):
        auth_claims = {}
    access_auth_claims = access_claims.get("https://api.openai.com/auth", {}) if isinstance(access_claims, dict) else {}
    if not isinstance(access_auth_claims, dict):
        access_auth_claims = {}

    expires_in = token_data.get("expires_in", 3600)
    try:
        expires_in = int(expires_in)
    except (TypeError, ValueError):
        expires_in = 3600

    return {
        "access_token": access_token,
        "refresh_token": str(token_data.get("refresh_token") or ""),
        "id_token": id_token,
        "account_id": str(auth_claims.get("chatgpt_account_id") or access_auth_claims.get("chatgpt_account_id") or ""),
        "email": str(claims.get("email") or fallback_email or ""),
        "plan_type": _extract_plan_from_token_claims(claims)
        if id_token
        else _extract_plan_from_token_claims(access_claims),
        "expired": time.time() + expires_in,
    }


def _screenshot(page, name):
    try:
        SCREENSHOT_DIR.mkdir(exist_ok=True)
        page.screenshot(path=str(SCREENSHOT_DIR / name), full_page=True, timeout=5000)
    except Exception as exc:
        logger.debug("[Codex] 截图失败，继续 OAuth 流程: %s", exc)


def _build_auth_url(code_challenge, state, *, native_oauth=False):
    params = {
        "client_id": CODEX_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": CODEX_REDIRECT_URI,
        "scope": "openid email profile offline_access",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": "login" if native_oauth else "consent",
    }
    if native_oauth:
        params["id_token_add_organizations"] = "true"
        params["codex_cli_simplified_flow"] = "true"
    return f"{CODEX_AUTH_URL}?{urllib.parse.urlencode(params)}"


def _normalize_chrome_cdp_url(cdp_url: str | None = None) -> str:
    return (cdp_url or os.environ.get("OAUTH_CHROME_CDP_URL") or DEFAULT_CHROME_CDP_URL).rstrip("/")


def _extract_auth_code_from_url(url: str) -> str:
    if f"localhost:{CODEX_CALLBACK_PORT}/auth/callback" not in str(url or ""):
        return ""
    return first_url_param(url, "code", include_fragment=False)


def is_chrome_cdp_available(cdp_url: str | None = None, *, timeout=1.5) -> bool:
    """Return True when a local Chrome remote debugging endpoint can be reached."""
    import requests

    base_url = _normalize_chrome_cdp_url(cdp_url)
    try:
        resp = requests.get(f"{base_url}/json/version", timeout=timeout)
        return resp.status_code == 200 and bool(resp.json().get("webSocketDebuggerUrl"))
    except Exception:
        return False


def _open_chrome_cdp_tab(url: str, cdp_url: str | None = None) -> str:
    """Open a new local Chrome CDP tab and return its page websocket URL."""
    import requests

    base_url = _normalize_chrome_cdp_url(cdp_url)
    encoded_url = urllib.parse.quote(url, safe="")
    last_error = ""
    for method in ("put", "get"):
        try:
            resp = getattr(requests, method)(f"{base_url}/json/new?{encoded_url}", timeout=5)
        except Exception as exc:
            last_error = str(exc)
            continue
        if resp.status_code in (200, 201):
            payload = resp.json()
            ws_url = str(payload.get("webSocketDebuggerUrl") or "")
            if ws_url:
                return ws_url
            last_error = "Chrome CDP /json/new 未返回 webSocketDebuggerUrl"
            continue
        last_error = f"HTTP {resp.status_code} {resp.text[:200]}"
    raise ChromeCDPUnavailable(f"无法连接本机 Chrome CDP: {_normalize_chrome_cdp_url(cdp_url)} ({last_error})")


def _extract_session_token_from_cookie_header(cookie_header: str) -> str:
    """Extract ChatGPT session token from a Cookie header string."""
    return chatgpt_session_service.session_token_from_cookie_header(cookie_header)


def _extract_account_id_from_auth_session(data: dict) -> str:
    if not isinstance(data, dict):
        return ""
    account_id = str(
        data.get("accountId")
        or data.get("account_id")
        or (data.get("account") or {}).get("id")
        or (data.get("user") or {}).get("account_id")
        or ""
    ).strip()
    if account_id:
        return account_id

    token = str(data.get("accessToken") or data.get("access_token") or "").strip()
    claims = _parse_jwt_payload(token)
    auth_claims = claims.get("https://api.openai.com/auth", {}) if isinstance(claims, dict) else {}
    return str(auth_claims.get("chatgpt_account_id") or "").strip() if isinstance(auth_claims, dict) else ""


def _normalize_auth_session_payload(session_data: dict) -> dict:
    """Merge saved /api/auth/session data with captured browser context."""
    if not isinstance(session_data, dict):
        return {}
    raw_data = session_data.get("data") if isinstance(session_data.get("data"), dict) else session_data
    context = session_data.get("auth_context") if isinstance(session_data.get("auth_context"), dict) else {}
    merged = {}
    if isinstance(raw_data, dict):
        merged.update(raw_data)
    merged.update({key: value for key, value in context.items() if value})
    return merged


def _extract_auth_session_token(data: dict) -> str:
    token = _extract_session_token_from_cookie_header(str((data or {}).get("cookie_header") or ""))
    if token:
        return token
    return str((data or {}).get("sessionToken") or (data or {}).get("session_token") or "").strip()


def _make_protocol_oauth_session(proxy_url: str | None = None):
    """Create a browser-like HTTP session for protocol OAuth."""
    try:
        from curl_cffi.requests import Session as CurlCffiSession  # type: ignore

        session = CurlCffiSession(impersonate="chrome")
        session._autotoken_transport = "curl_cffi"  # type: ignore[attr-defined]
    except Exception:
        import requests

        session = requests.Session()
        session._autotoken_transport = "requests"  # type: ignore[attr-defined]
    raw_proxy = str(proxy_url or "").strip()
    if raw_proxy:
        proxy = normalize_proxy_url(raw_proxy)
        try:
            session.proxies = {"http": proxy, "https": proxy}
        except Exception:
            logger.debug("[Codex] 协议 OAuth 设置代理失败", exc_info=True)
            raise
        logger.info("[Codex] 协议 OAuth proxy enabled")
    return session


def _set_protocol_cookie(session, name: str, value: str, domain: str):
    value = str(value or "").strip()
    if not value:
        return
    try:
        session.cookies.set(name, value, domain=domain, path="/")
    except Exception:
        session.cookies.set(name, value)


def _seed_protocol_auth_cookies(session, *, session_token: str, account_id: str = "", device_id: str = ""):
    domains = ("auth.openai.com", ".auth.openai.com")
    session_cookie = chatgpt_session_service.CHATGPT_SESSION_COOKIE
    for domain in domains:
        if len(session_token) > 3800:
            _set_protocol_cookie(session, f"{session_cookie}.0", session_token[:3800], domain)
            _set_protocol_cookie(session, f"{session_cookie}.1", session_token[3800:], domain)
        else:
            _set_protocol_cookie(session, session_cookie, session_token, domain)
        _set_protocol_cookie(session, "_account", account_id, domain)
        _set_protocol_cookie(session, "oai-did", device_id, domain)


def _protocol_oauth_headers(referer: str = "") -> dict:
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
        ),
    }
    if referer:
        headers["Referer"] = referer
    return headers


def _is_codex_oauth_callback_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(str(url or ""))
    if "/auth/callback" not in (parsed.path or "").lower():
        return False
    return has_url_param(url, "code", "error", "error_description")


def _parse_codex_oauth_callback_url(url: str) -> dict:
    return {
        "code": first_url_param(url, "code"),
        "state": first_url_param(url, "state"),
        "error": first_url_param(url, "error", "error_description"),
        "raw_url": url,
    }


def _extract_meta_refresh_url(html: str, base_url: str) -> str:
    text = str(html or "")
    match = re.search(
        r"<meta[^>]+http-equiv=[\"']?refresh[\"']?[^>]+content=[\"'][^\"']*url=([^\"'>\s]+)",
        text,
        flags=re.I,
    )
    if not match:
        return ""
    return urllib.parse.urljoin(base_url, match.group(1).replace("&amp;", "&"))


def _exchange_auth_code_protocol(session, auth_code: str, code_verifier: str, fallback_email=None):
    logger.info("[Codex] 协议 OAuth 获取到 auth code，交换 token...")
    resp = session.post(
        CODEX_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": CODEX_CLIENT_ID,
            "code": auth_code,
            "redirect_uri": CODEX_REDIRECT_URI,
            "code_verifier": code_verifier,
        },
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": _protocol_oauth_headers()["User-Agent"],
        },
        timeout=30,
    )
    if getattr(resp, "status_code", 0) != 200:
        raise CodexProtocolOAuthError(
            f"Codex token 交换失败 HTTP {getattr(resp, 'status_code', '?')} {(getattr(resp, 'text', '') or '')[:200]}"
        )
    bundle = _build_bundle_from_token_response(resp.json(), fallback_email=fallback_email)
    if not bundle.get("access_token") or not bundle.get("refresh_token"):
        raise CodexProtocolOAuthError("Codex token 响应缺少 access_token 或 refresh_token")
    logger.info("[Codex] 协议 OAuth 登录成功: %s (plan: %s)", bundle["email"], bundle["plan_type"])
    return bundle


def _follow_codex_oauth_redirects_protocol(session, auth_url: str, *, expected_state: str, max_redirects: int = 18):
    current_url = auth_url
    referer = ""
    final_body = ""

    for index in range(max(1, int(max_redirects or 1))):
        if _is_codex_oauth_callback_url(current_url):
            parsed = _parse_codex_oauth_callback_url(current_url)
            if parsed.get("state") and parsed["state"] != expected_state:
                raise CodexProtocolOAuthError("Codex OAuth state 不匹配", final_url=current_url)
            return parsed

        logger.info("[Codex] 协议 OAuth 跟随重定向 %s/%s: %s", index + 1, max_redirects, current_url[:120])
        resp = session.get(
            current_url,
            headers=_protocol_oauth_headers(referer),
            allow_redirects=False,
            timeout=30,
        )
        final_body = str(getattr(resp, "text", "") or "")
        status = int(getattr(resp, "status_code", 0) or 0)
        location = str(getattr(resp, "headers", {}).get("Location") or "")

        if status in {301, 302, 303, 307, 308} and location:
            next_url = urllib.parse.urljoin(current_url, location)
            if _is_codex_oauth_callback_url(next_url):
                parsed = _parse_codex_oauth_callback_url(next_url)
                if parsed.get("state") and parsed["state"] != expected_state:
                    raise CodexProtocolOAuthError("Codex OAuth state 不匹配", final_url=next_url)
                return parsed
            referer = current_url
            current_url = next_url
            continue

        meta_url = _extract_meta_refresh_url(final_body, current_url)
        if meta_url:
            referer = current_url
            current_url = meta_url
            continue

        lower_url = current_url.lower()
        lower_body = final_body[:3000].lower()
        if "auth.openai.com/add-phone" in lower_url or "/add-phone" in lower_url:
            raise CodexOAuthPhoneRequired(current_url)
        if "add phone" in lower_body or "phone verification" in lower_body or "手机号" in lower_body:
            raise CodexOAuthPhoneRequired(current_url)
        if (
            "log-in" in lower_url
            or "login" in lower_url
            or "电子邮件地址" in final_body
            or "email address" in lower_body
        ):
            raise CodexProtocolOAuthError("Codex OAuth 协议流落到登录页", final_url=current_url, body=final_body[:500])

        raise CodexProtocolOAuthError(
            f"Codex OAuth 协议流未返回回调，HTTP {status}",
            final_url=current_url,
            body=final_body[:500],
        )

    raise CodexProtocolOAuthError("Codex OAuth 协议流重定向次数超限", final_url=current_url, body=final_body[:500])


def _exchange_auth_code(auth_code, code_verifier, fallback_email=None):
    logger.info("[Codex] 获取到 auth code，交换 token...")

    import requests

    resp = requests.post(
        CODEX_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": CODEX_CLIENT_ID,
            "code": auth_code,
            "redirect_uri": CODEX_REDIRECT_URI,
            "code_verifier": code_verifier,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    if resp.status_code != 200:
        logger.error("[Codex] Token 交换失败: %d %s", resp.status_code, resp.text[:200])
        return None

    token_data = resp.json()
    bundle = _build_bundle_from_token_response(token_data, fallback_email=fallback_email)

    logger.info("[Codex] 登录成功: %s (plan: %s)", bundle["email"], bundle["plan_type"])
    return bundle


def _write_auth_file(filepath, bundle):
    filepath = Path(filepath)
    ensure_auth_dir()
    filepath.parent.mkdir(exist_ok=True)

    auth_data = bundle.get("session_json")
    if not isinstance(auth_data, dict):
        auth_data = {
            "type": "codex",
            "id_token": bundle.get("id_token", ""),
            "access_token": bundle.get("access_token", ""),
            "refresh_token": bundle.get("refresh_token", ""),
            "account_id": bundle.get("account_id", ""),
            "email": bundle.get("email", ""),
            "plan_type": bundle.get("plan_type", "unknown"),
            "chatgpt_plan_type": bundle.get("plan_type", "unknown"),
            "expired": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(bundle.get("expired", 0))),
            "last_refresh": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    auth_data.setdefault("plan_type", bundle.get("plan_type", "unknown"))
    auth_data.setdefault("chatgpt_plan_type", bundle.get("plan_type", "unknown"))
    write_text(filepath, json.dumps(auth_data, indent=2))
    ensure_auth_file_permissions(filepath)
    try:
        upsert_codex_auth_file(filepath, auth_data, main=filepath.name.startswith("codex-main-"))
    except Exception as exc:
        logger.warning("[Codex] SQLite auth 索引写入失败: %s", exc)
    logger.info("[Codex] 认证文件已保存: %s", filepath)
    return str(filepath)


def _click_primary_auth_button(page, field, labels):
    """
    只点击当前输入框所在表单的主按钮，避免误点 Continue with Google/Apple/Microsoft。
    """
    label_re = re.compile(rf"^(?:{'|'.join(re.escape(label) for label in labels)})$", re.I)

    def click_if_ready(btn):
        try:
            if not btn.is_visible(timeout=2000):
                return False
            if not btn.is_enabled(timeout=2000):
                return False
            aria_disabled = (btn.get_attribute("aria-disabled", timeout=1000) or "").lower()
            if aria_disabled == "true":
                return False
            btn.click()
            return True
        except Exception:
            return False

    try:
        form = field.locator("xpath=ancestor::form[1]").first
        btn = form.get_by_role("button", name=label_re).first
        if click_if_ready(btn):
            return True
    except Exception:
        pass

    try:
        form = field.locator("xpath=ancestor::form[1]").first
        btn = form.locator('button[type="submit"], input[type="submit"]').first
        if click_if_ready(btn):
            return True
    except Exception:
        pass

    try:
        btn = page.get_by_role("button", name=label_re).last
        if click_if_ready(btn):
            return True
    except Exception:
        pass

    try:
        field.press("Enter")
        return True
    except Exception:
        return False


_OAUTH_CONSENT_TEXTS = (
    "Continue",
    "继续",
    "繼續",
    "Allow",
    "Allow access",
    "Authorize",
    "授权",
    "授權",
    "同意",
    "允许",
    "允許",
    "Confirm",
    "确认",
    "確認",
    "Agree",
)


def _has_visible_auth_input(page) -> bool:
    if _is_email_verification_page(page):
        return True
    for selector in (_OTP_INPUT_SELECTORS, _PASSWORD_INPUT_SELECTORS, _EMAIL_INPUT_SELECTORS):
        try:
            field = page.locator(selector).first
            if field.is_visible(timeout=150):
                return True
        except Exception:
            continue
    return False


def _click_oauth_consent_if_present(page, *, timeout=1000) -> bool:
    """Click the OAuth consent/continue button without touching login form steps."""
    if _has_visible_auth_input(page):
        return False

    def click_candidate(control) -> bool:
        try:
            if not control.is_visible(timeout=timeout):
                return False
            try:
                if not control.is_enabled(timeout=timeout):
                    return False
            except Exception:
                pass
            try:
                control.scroll_into_view_if_needed(timeout=1000)
            except Exception:
                pass
            try:
                control.click(timeout=2000)
                return True
            except Exception:
                try:
                    control.click(timeout=2000, force=True)
                    return True
                except Exception:
                    pass
            try:
                handle = control.element_handle(timeout=1000)
                if handle:
                    page.evaluate("(el) => el.click()", handle)
                    return True
            except Exception:
                pass
        except Exception:
            return False
        return False

    label_selectors = []
    for text in _OAUTH_CONSENT_TEXTS:
        label_selectors.extend(
            [
                f'button:has-text("{text}")',
                f'a:has-text("{text}")',
                f'[role="button"]:has-text("{text}")',
                f'input[type="submit"][value*="{text}" i]',
            ]
        )
    try:
        consent_url = "consent" in (page.url or "").lower()
    except Exception:
        consent_url = False
    if consent_url:
        label_selectors.extend(['button[type="submit"]', 'input[type="submit"]'])

    for selector in label_selectors:
        try:
            control = page.locator(selector).first
            if click_candidate(control):
                return True
        except Exception:
            continue

    try:
        clicked = page.evaluate(
            """({labels, consentUrl}) => {
              const visible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style && style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
              };
              const norm = (text) => String(text || '').replace(/\\s+/g, ' ').trim().toLowerCase();
              const blocked = /(google|apple|microsoft|resend|重新发送|重發|password|密码|密碼|email code|验证码登录|驗證碼登入|privacy|terms|隐私|使用条款)/i;
              const zhConsent = /(继续|繼續|同意|授权|授權|允许|允許|确认|確認)/;
              const enConsent = /^(continue|allow|allow access|authorize|confirm|agree)(\\b|$)|continue to|allow access/i;
              const targets = Array.from(document.querySelectorAll('button, a, [role="button"], input[type="submit"]'));
              for (const el of targets) {
                if (!visible(el) || el.disabled || el.getAttribute('aria-disabled') === 'true') continue;
                const text = norm(el.innerText || el.textContent || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || '');
                if (text && blocked.test(text)) continue;
                if (text && labels.some((label) => text.includes(norm(label)))) {
                  el.scrollIntoView({block: 'center', inline: 'center'});
                  el.click();
                  return text;
                }
                if (text && (zhConsent.test(text) || enConsent.test(text))) {
                  el.scrollIntoView({block: 'center', inline: 'center'});
                  el.click();
                  return text;
                }
                if (consentUrl && el.matches('button[type="submit"], input[type="submit"]')) {
                  el.scrollIntoView({block: 'center', inline: 'center'});
                  el.click();
                  return text || 'submit';
                }
              }
              return '';
            }""",
            {"labels": list(_OAUTH_CONSENT_TEXTS), "consentUrl": consent_url},
        )
        return bool(clicked)
    except Exception:
        return False


def _is_google_redirect(page):
    url = (page.url or "").lower()
    if "accounts.google.com" in url:
        return True

    try:
        text = page.locator("body").inner_text(timeout=1000).lower()
        return "sign in with google" in text[:300]
    except Exception:
        return False


_OTP_INPUT_SELECTORS = (
    'input[name="code"], input[inputmode="numeric"], input[autocomplete="one-time-code"], '
    'input[placeholder*="验证码"], input[placeholder*="code" i], '
    'input[aria-label*="验证码"], input[aria-label*="verification" i], '
    'input[name*="verification" i], input[id*="verification" i]'
)
_EMAIL_INPUT_SELECTORS = (
    'input[name="email"], input[name="username"], input[id="email-input"], input[id="email"], '
    'input[id*="email" i], input[type="email"], input[placeholder*="email" i], '
    'input[placeholder*="邮箱"], input[placeholder*="电子邮件"], input[aria-label*="email" i], '
    'input[aria-label*="邮箱"], input[aria-label*="电子邮件"], input[autocomplete="email"], '
    'input[autocomplete="username"]'
)
_PASSWORD_INPUT_SELECTORS = 'input[name="password"], input[type="password"]'
_EMAIL_CODE_LOGIN_TEXTS = (
    "一次性验证码",
    "邮箱验证码",
    "验证码登录",
    "验证码登陆",
    "使用验证码登录",
    "使用验证码登陆",
    "用验证码登录",
    "用验证码登陆",
    "改用验证码",
    "改用邮箱验证码",
    "使用电子邮件验证码",
    "通过电子邮件接收验证码",
    "透过电子邮件接收验证码",
    "Email code",
    "email code",
    "Email login",
    "email login",
    "Continue with email code",
    "Log in with code",
    "Login with code",
    "Sign in with code",
    "Use a code",
    "Use code",
    "one-time",
    "One-time",
    "OTP",
    "otp",
)
_EMAIL_CODE_LOGIN_SELECTOR = ", ".join(
    [f'button:has-text("{text}")' for text in _EMAIL_CODE_LOGIN_TEXTS]
    + [f'a:has-text("{text}")' for text in _EMAIL_CODE_LOGIN_TEXTS]
    + [f'[role="button"]:has-text("{text}")' for text in _EMAIL_CODE_LOGIN_TEXTS]
)
_OTP_INVALID_HINTS = (
    "invalid code",
    "incorrect code",
    "wrong code",
    "expired code",
    "check the code and try again",
    "验证码无效",
    "验证码错误",
    "验证码已过期",
)
_PHONE_INPUT_SELECTORS = (
    'input[type="tel"], input[name*="phone" i], input[id*="phone" i], '
    'input[autocomplete="tel"], input[inputmode="tel"], input[placeholder*="phone" i], '
    'input[aria-label*="phone" i], input[placeholder*="手机"], input[aria-label*="手机"]'
)
_PHONE_REJECT_HINTS = (
    "invalid phone",
    "not a valid phone",
    "phone number is not valid",
    "try a different phone",
    "unsupported phone",
    "maximum number of accounts",
    "max number of accounts",
    "associated with the maximum",
    "unable to send",
    "can't send",
    "cannot send",
    "try again later",
    "too many attempts",
    "too many requests",
    "use a different phone",
    "手机号无效",
    "手机号码无效",
    "换一个手机号",
    "更换手机号",
    "无法发送",
    "无法向此电话号码发送验证码",
    "请求过多",
    "请稍后重试",
    "此电话号码已关联到可关联的最多账户",
    "已关联到可关联的最多账户",
)
_PHONE_RATE_LIMIT_HINTS = (
    "too many phone verification",
    "too many verification requests",
    "too many requests to verify",
    "requested phone verification too many",
    "phone verification requests",
    "你请求手机验证的次数过多",
    "请求手机验证的次数过多",
    "手机验证的次数过多",
)
_PHONE_FULL_HINTS = (
    "maximum number of accounts",
    "max number of accounts",
    "associated with the maximum",
    "此电话号码已关联到可关联的最多账户",
    "已关联到可关联的最多账户",
)
_PHONE_COOLDOWN_HINTS = (
    "unable to send",
    "can't send",
    "cannot send",
    "try again later",
    "too many attempts",
    "too many requests",
    "无法向此电话号码发送验证码",
    "无法发送验证码",
    "请求过多",
    "请稍后重试",
    "稍后再试",
)


def _is_email_verification_page(page) -> bool:
    try:
        url = (page.url or "").lower()
        if "auth.openai.com/email-verification" in url or "/email-verification" in url:
            return True
    except Exception:
        pass
    try:
        text = page.locator("body").inner_text(timeout=500).lower()
        inbox_hints = (
            "检查您的收件箱",
            "检查你的收件箱",
            "检查收件箱",
            "check your inbox",
            "check your email",
        )
        return any(hint in text for hint in inbox_hints) and ("验证码" in text or "verification code" in text)
    except Exception:
        return False


def _field_input_value(field) -> str:
    try:
        return str(field.input_value(timeout=1000) or "")
    except Exception:
        return ""


def _fill_text_field_like_user(page, field, value: str) -> bool:
    """Use keyboard input first so React/Turnstile-gated auth forms enable submit."""
    try:
        field.click(force=True)
        field.press("Control+A")
        field.press("Backspace")
        page.keyboard.type(value, delay=25)
        time.sleep(0.3)
        if _field_input_value(field).strip() == value.strip():
            return True
    except Exception:
        pass

    try:
        field.fill(value)
        time.sleep(0.3)
    except Exception:
        return False

    if _field_input_value(field).strip() == value.strip():
        return True

    try:
        field.evaluate(
            """(el, value) => {
                const proto = Object.getPrototypeOf(el);
                const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
                if (descriptor && descriptor.set) {
                  descriptor.set.call(el, value);
                } else {
                  el.value = value;
                }
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }""",
            value,
        )
        time.sleep(0.3)
    except Exception:
        pass

    return _field_input_value(field).strip() == value.strip()


def _otp_input_locator(page):
    try:
        specific = page.locator(_OTP_INPUT_SELECTORS).first
        if specific.is_visible(timeout=300):
            return specific
    except Exception:
        pass

    if not _is_email_verification_page(page):
        return None

    try:
        generic = page.locator(
            'input:not([type="hidden"]):not([type="email"]):not([type="password"]):not([name="email"]):not([autocomplete="email"])'
        ).first
        if generic.is_visible(timeout=300):
            return generic
    except Exception:
        pass
    return None


def _is_otp_input_visible(page, timeout=500):
    try:
        locator = _otp_input_locator(page)
        return bool(locator and locator.is_visible(timeout=timeout))
    except Exception:
        return False


def _is_auth_login_url(url: str) -> bool:
    lower = (url or "").lower()
    return "auth.openai.com/log-in" in lower or "auth.openai.com/login" in lower


def _email_input_locator(page):
    if _is_email_verification_page(page):
        return None
    if not _is_auth_login_url(page.url or ""):
        return None

    try:
        specific = page.locator(_EMAIL_INPUT_SELECTORS).first
        if specific.is_visible(timeout=300):
            return specific
    except Exception:
        pass

    try:
        generic = page.locator(
            'input:not([type="hidden"]):not([type="password"]):not([type="checkbox"]):not([name="code"]):not([autocomplete="one-time-code"])'
        ).first
        if generic.is_visible(timeout=300):
            return generic
    except Exception:
        pass
    return None


def _is_auth_login_page(page):
    if _is_auth_login_url(page.url or ""):
        return True
    try:
        return bool(_email_input_locator(page))
    except Exception:
        return False


def _looks_like_account_deactivated_text(text: str) -> bool:
    lower = (text or "").lower()
    return (
        "account_deactivated" in lower
        or "account deactivated" in lower
        or "account is deactivated" in lower
        or "验证过程中出错" in lower
    )


def _detect_account_deactivated(page):
    try:
        text = page.locator("body").inner_text(timeout=1000)
    except Exception:
        return ""
    if _looks_like_account_deactivated_text(text):
        return text[:500]
    return ""


def _looks_like_operation_timed_out_text(text: str) -> bool:
    lower = (text or "").lower()
    return (
        "operation timed out" in lower
        or "操作超时" in lower
        or "糟糕，出错了" in lower
        or "oops, an error occurred" in lower
        or "not valid json" in lower
        or "unexpected token '<'" in lower
    )


def _click_auth_retry_if_timed_out(page):
    try:
        text = page.locator("body").inner_text(timeout=1000)
    except Exception:
        return False
    if not _looks_like_operation_timed_out_text(text):
        return False
    for selector in (
        'button:has-text("重试")',
        'button:has-text("Retry")',
        'button:has-text("Try again")',
        'button:has-text("再试一次")',
        '[role="button"]:has-text("重试")',
        '[role="button"]:has-text("Retry")',
        '[role="button"]:has-text("Try again")',
        'a:has-text("Try again")',
    ):
        try:
            btn = page.locator(selector).first
            if btn.is_visible(timeout=1000):
                btn.click()
                return True
        except Exception:
            continue
    return False


def _fill_auth_email_if_present(page, email, *, timeout=800):
    try:
        if _is_email_verification_page(page):
            return False
        try:
            password_input = page.locator(_PASSWORD_INPUT_SELECTORS).first
            if password_input.is_visible(timeout=100):
                return False
        except Exception:
            pass
        deadline = time.time() + max(timeout, 0) / 1000
        email_input = None
        while time.time() <= deadline:
            if _is_email_verification_page(page):
                return False
            try:
                password_input = page.locator(_PASSWORD_INPUT_SELECTORS).first
                if password_input.is_visible(timeout=100):
                    return False
            except Exception:
                pass
            email_input = _email_input_locator(page)
            if email_input:
                break
            time.sleep(0.1)
        if not email_input:
            return False
        if not _fill_text_field_like_user(page, email_input, email):
            return False
        deadline = time.time() + 3
        while time.time() <= deadline:
            if _click_primary_auth_button(page, email_input, ["Continue", "继续"]):
                return True
            time.sleep(0.25)
        return False
    except Exception:
        return False


def _fill_auth_password_if_present(page, password, *, timeout=5000):
    try:
        pwd_input = page.locator(_PASSWORD_INPUT_SELECTORS).first
        if not pwd_input.is_visible(timeout=timeout):
            return False
        if _click_email_code_login_if_present(page):
            logger.info("[Codex] 检测到密码页，已切换邮箱验证码登录")
            return True
        if password:
            if not _fill_text_field_like_user(page, pwd_input, password):
                return False
            if not _click_primary_auth_button(page, pwd_input, ["Continue", "继续", "Log in", "登录"]):
                return False
        else:
            otp_btn = page.locator(_EMAIL_CODE_LOGIN_SELECTOR).first
            if otp_btn.is_visible(timeout=3000):
                otp_btn.click()
            else:
                if not _click_primary_auth_button(page, pwd_input, ["Continue", "继续", "Log in", "登录"]):
                    return False
        return True
    except Exception:
        return False


def _detect_otp_error(page):
    try:
        body = page.locator("body").inner_text(timeout=1500).lower().replace("\n", " ")
    except Exception:
        return None

    for hint in _OTP_INVALID_HINTS:
        if hint in body:
            return hint
    return None


def _wait_for_otp_submit_result(page, timeout=12):
    """
    等待验证码提交结果：
    - accepted: 验证码输入框已消失 / 页面已前进
    - invalid: 页面明确提示验证码错误
    - pending: 既没报错也没明显前进（常见于页面较慢或状态未稳定）
    """
    deadline = time.time() + timeout

    while time.time() < deadline:
        err = _detect_otp_error(page)
        if err:
            return "invalid", err
        if not _is_otp_input_visible(page, timeout=250):
            return "accepted", None
        time.sleep(0.5)

    err = _detect_otp_error(page)
    if err:
        return "invalid", err
    return "pending", None


def _is_add_phone_page(page) -> bool:
    try:
        url = (page.url or "").lower()
        if "auth.openai.com/add-phone" in url or "/add-phone" in url:
            return True
    except Exception:
        pass
    try:
        text = page.locator("body").inner_text(timeout=600).lower()
        return any(
            hint in text
            for hint in (
                "add phone",
                "phone verification",
                "phone number is required",
                "continue adding your phone number",
                "添加手机号",
                "手机号验证",
                "电话号码是必填项",
                "电话号码",
                "电话号",
            )
        )
    except Exception:
        return False


def _phone_input_locator(page):
    for selector in (
        'input[type="tel"]',
        "input#tel",
        'input[name*="PhoneNumber" i]',
        'input[name*="phone" i]',
        'input[id*="phone" i]',
        'input[autocomplete="tel"]',
        'input[inputmode="tel"]',
        'input[placeholder*="电话号码"]',
        'input[placeholder*="phone" i]',
    ):
        try:
            candidate = page.locator(selector).first
            if candidate.is_visible(timeout=500):
                return candidate
        except Exception:
            continue
    try:
        specific = page.locator(_PHONE_INPUT_SELECTORS).first
        if specific.is_visible(timeout=500):
            return specific
    except Exception:
        pass
    try:
        generic = page.locator(
            'input:not([type="hidden"]):not([type="email"]):not([type="password"]):not([type="checkbox"]):not([name="code"]):not([autocomplete="one-time-code"])'
        ).first
        if generic.is_visible(timeout=500):
            return generic
    except Exception:
        pass
    return None


def _visible_input_snapshots(page) -> list[dict]:
    try:
        return page.evaluate(
            """() => {
              const visible = (el) => {
                const rect = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                return rect.width > 0 && rect.height > 0
                  && style.visibility !== 'hidden'
                  && style.display !== 'none'
                  && !el.disabled;
              };
              const labelText = (el) => {
                const id = el.getAttribute('id');
                const labels = [];
                if (id) {
                  const label = document.querySelector(`label[for="${CSS.escape(id)}"]`);
                  if (label) labels.push(label.innerText || label.textContent || '');
                }
                let node = el;
                for (let i = 0; i < 4 && node; i += 1, node = node.parentElement) {
                  const text = (node.innerText || node.textContent || '').trim();
                  if (text) labels.push(text);
                }
                return labels.join(' | ').replace(/\\s+/g, ' ').slice(0, 180);
              };
              return Array.from(document.querySelectorAll('input, textarea'))
                .filter(visible)
                .map((el, idx) => ({
                  idx,
                  tag: el.tagName.toLowerCase(),
                  type: el.getAttribute('type') || '',
                  name: el.getAttribute('name') || '',
                  id: el.getAttribute('id') || '',
                  autocomplete: el.getAttribute('autocomplete') || '',
                  inputmode: el.getAttribute('inputmode') || '',
                  placeholder: el.getAttribute('placeholder') || '',
                  aria: el.getAttribute('aria-label') || '',
                  value: el.value || '',
                  label: labelText(el),
                }));
            }"""
        )
    except Exception:
        return []


def _compact_input_snapshots(page) -> str:
    rows = [
        "idx={idx} type={type} name={name} id={id} placeholder={placeholder} aria={aria} value={value} label={label}".format(
            idx=item.get("idx", ""),
            type=item.get("type", ""),
            name=_compact_log_text(item.get("name", ""), limit=32),
            id=_compact_log_text(item.get("id", ""), limit=32),
            placeholder=_compact_log_text(item.get("placeholder", ""), limit=32),
            aria=_compact_log_text(item.get("aria", ""), limit=32),
            value=_compact_log_text(item.get("value", ""), limit=32),
            label=_compact_log_text(item.get("label", ""), limit=80),
        )
        for item in _visible_input_snapshots(page)
    ]
    return " || ".join(rows) or "<no visible inputs>"


def _is_phone_otp_page(page) -> bool:
    try:
        text = page.locator("body").inner_text(timeout=700).lower()
    except Exception:
        text = ""
    otp_hints = (
        "verification code",
        "enter code",
        "enter the code",
        "code we sent",
        "验证码",
        "输入代码",
        "输入验证码",
        "我们发送",
    )
    phone_entry_hints = (
        "phone number is required",
        "电话号码是必填项",
        "继续添加电话号码",
        "continue adding your phone number",
    )
    return any(hint in text for hint in otp_hints) and not any(hint in text for hint in phone_entry_hints)


def _phone_otp_input_locator(page):
    if not _is_phone_otp_page(page):
        return None
    try:
        specific = page.locator(_OTP_INPUT_SELECTORS).first
        if specific.is_visible(timeout=500):
            return specific
    except Exception:
        pass
    try:
        generic = page.locator(
            'input:not([type="hidden"]):not([type="email"]):not([type="password"]):not([type="tel"]):not([name="email"]):not([autocomplete="email"])'
        ).first
        if generic.is_visible(timeout=500):
            return generic
    except Exception:
        pass
    return None


def _detect_phone_rejected(page) -> str:
    try:
        text = page.locator("body").inner_text(timeout=1000)
    except Exception:
        return ""
    lower = text.lower()
    if any(hint in lower for hint in _PHONE_RATE_LIMIT_HINTS):
        return ""
    for hint in _PHONE_REJECT_HINTS:
        if hint in lower:
            return _compact_log_text(text, limit=260)
    return ""


def _detect_phone_rate_limited(page) -> str:
    try:
        text = page.locator("body").inner_text(timeout=1000)
    except Exception:
        return ""
    lower = text.lower()
    for hint in _PHONE_RATE_LIMIT_HINTS:
        if hint in lower:
            return _compact_log_text(text, limit=260)
    return ""


def _click_phone_resend_if_present(page) -> bool:
    for selector in (
        'button:has-text("Resend")',
        'button:has-text("Send again")',
        'button:has-text("重新发送")',
        'button:has-text("再次发送")',
        '[role="button"]:has-text("Resend")',
        'a:has-text("Resend")',
    ):
        try:
            control = page.locator(selector).first
            if control.is_visible(timeout=500) and control.is_enabled(timeout=500):
                control.click()
                return True
        except Exception:
            continue
    return False


def _format_oauth_phone_for_input(page, phone_input, phone: str, *, force_us: bool = False) -> str:
    raw = str(phone or "").strip()
    digits = re.sub(r"\D+", "", raw)
    if not digits:
        return raw
    try:
        body = page.locator("body").inner_text(timeout=500)
    except Exception:
        body = ""
    try:
        existing = phone_input.input_value(timeout=500)
    except Exception:
        existing = ""
    country_is_us = (
        force_us
        or "(+1)" in body
        or "美国 (+1)" in body
        or "united states (+1)" in body.lower()
        or str(existing or "").strip() in {"+1", "1"}
    )
    if country_is_us and digits.startswith("1") and len(digits) == 11:
        return digits[1:]
    return raw


def _read_true_oauth_phone_value(page) -> dict:
    try:
        result = page.evaluate(
            """() => {
              const visible = (el) => {
                const rect = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                return rect.width > 0 && rect.height > 0
                  && style.visibility !== 'hidden'
                  && style.display !== 'none'
                  && !el.disabled;
              };
              const scoreFor = (el) => {
                const type = (el.getAttribute('type') || '').toLowerCase();
                const name = (el.getAttribute('name') || '').toLowerCase();
                const id = (el.getAttribute('id') || '').toLowerCase();
                const placeholder = (el.getAttribute('placeholder') || '').toLowerCase();
                const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                const text = [
                  type, name, id, placeholder, aria,
                  el.parentElement ? (el.parentElement.innerText || el.parentElement.textContent || '') : '',
                  el.parentElement && el.parentElement.parentElement
                    ? (el.parentElement.parentElement.innerText || el.parentElement.parentElement.textContent || '')
                    : '',
                ].join(' ').replace(/\\s+/g, ' ').toLowerCase();
                let score = 0;
                if (type === 'tel') score += 200;
                if (id === 'tel') score += 120;
                if (name.includes('reservedforphonenumber')) score += 120;
                if (name.includes('phone')) score += 100;
                if (id.includes('phone')) score += 100;
                if (placeholder.includes('电话号码') || placeholder.includes('phone')) score += 100;
                if (aria.includes('电话号码') || aria.includes('phone')) score += 60;
                if (text.includes('phone number') || text.includes('电话号码') || text.includes('手机号')) score += 40;
                if ((el.value || '').trim() === '+1' || (el.value || '').trim() === '1') score -= 40;
                if (text.includes('阿尔巴尼亚') || text.includes('阿富汗') || text.length > 900) score -= 120;
                return score;
              };
              const candidates = Array.from(document.querySelectorAll('input, textarea'))
                .filter(visible)
                .filter((el) => {
                  const type = (el.getAttribute('type') || '').toLowerCase();
                  return !['hidden', 'email', 'password', 'checkbox', 'radio', 'submit', 'button'].includes(type);
                })
                .map((el, idx) => ({
                  idx,
                  score: scoreFor(el),
                  type: el.getAttribute('type') || '',
                  name: el.getAttribute('name') || '',
                  id: el.getAttribute('id') || '',
                  placeholder: el.getAttribute('placeholder') || '',
                  aria: el.getAttribute('aria-label') || '',
                  value: el.value || '',
                }))
                .sort((a, b) => b.score - a.score);
              return candidates[0] || {};
            }"""
        )
        return result if isinstance(result, dict) else {}
    except Exception as exc:
        return {"error": str(exc)}


def _true_oauth_phone_has_digits(page, expected_digits: str) -> tuple[bool, dict]:
    true_field = _read_true_oauth_phone_value(page)
    value_digits = re.sub(r"\D+", "", str(true_field.get("value") or ""))
    ok = bool(expected_digits and expected_digits in value_digits and int(true_field.get("score") or 0) > 0)
    return ok, true_field


def _fill_oauth_phone_field(page, phone_input, phone_for_input: str) -> tuple[bool, str]:
    expected_digits = re.sub(r"\D+", "", phone_for_input)
    before = _compact_input_snapshots(page)
    if _fill_text_field_like_user(page, phone_input, phone_for_input):
        ok, true_field = _true_oauth_phone_has_digits(page, expected_digits)
        if ok:
            logger.info(
                "[Codex] add-phone 手机号键盘写入成功: true_field=%s inputs=%s",
                true_field,
                _compact_input_snapshots(page),
            )
            return True, ""

    try:
        direct_result = phone_input.evaluate(
            """(el, value) => {
              const proto = Object.getPrototypeOf(el);
              const desc = Object.getOwnPropertyDescriptor(proto, 'value');
              el.focus();
              if (desc && desc.set) desc.set.call(el, value);
              else el.value = value;
              el.dispatchEvent(new InputEvent('input', { bubbles: true, data: value, inputType: 'insertText' }));
              el.dispatchEvent(new Event('change', { bubbles: true }));
              el.dispatchEvent(new Event('blur', { bubbles: true }));
              return el.value || '';
            }""",
            phone_for_input,
        )
        ok, true_field = _true_oauth_phone_has_digits(page, expected_digits)
        if ok:
            logger.info(
                "[Codex] add-phone 手机号直接写入成功: value=%s true_field=%s inputs=%s",
                direct_result,
                true_field,
                _compact_input_snapshots(page),
            )
            return True, ""
    except Exception:
        pass

    try:
        result = page.evaluate(
            """(value) => {
              const expectedDigits = String(value || '').replace(/\\D+/g, '');
              const visible = (el) => {
                const rect = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                return rect.width > 0 && rect.height > 0
                  && style.visibility !== 'hidden'
                  && style.display !== 'none'
                  && !el.disabled && !el.readOnly;
              };
              const textFor = (el) => {
                const parts = [
                  el.getAttribute('type') || '',
                  el.getAttribute('name') || '',
                  el.getAttribute('id') || '',
                  el.getAttribute('autocomplete') || '',
                  el.getAttribute('inputmode') || '',
                  el.getAttribute('placeholder') || '',
                  el.getAttribute('aria-label') || '',
                ];
                const id = el.getAttribute('id');
                if (id) {
                  const label = document.querySelector(`label[for="${CSS.escape(id)}"]`);
                  if (label) parts.push(label.innerText || label.textContent || '');
                }
                let node = el;
                for (let i = 0; i < 4 && node; i += 1, node = node.parentElement) {
                  parts.push(node.innerText || node.textContent || '');
                }
                return parts.join(' ').replace(/\\s+/g, ' ').toLowerCase();
              };
              const candidates = Array.from(document.querySelectorAll('input, textarea'))
                .filter(visible)
                .filter((el) => {
                  const type = (el.getAttribute('type') || '').toLowerCase();
                  return !['hidden', 'email', 'password', 'checkbox', 'radio', 'submit', 'button'].includes(type);
                })
                .map((el, idx) => {
                const text = textFor(el);
                let score = 0;
                  const type = (el.getAttribute('type') || '').toLowerCase();
                  const name = (el.getAttribute('name') || '').toLowerCase();
                  const id = (el.getAttribute('id') || '').toLowerCase();
                  const placeholder = (el.getAttribute('placeholder') || '').toLowerCase();
                  const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                  if (type === 'tel') score += 100;
                  if (name.includes('phone') || id.includes('phone')) score += 80;
                  if (id === 'tel' || name.includes('reservedforphonenumber')) score += 80;
                  if (placeholder.includes('phone') || placeholder.includes('电话号码') || placeholder.includes('手机号')) score += 70;
                  if (aria.includes('phone') || aria.includes('电话号码') || aria.includes('手机号')) score += 35;
                  if (text.includes('phone number') || text.includes('电话号码') || text.includes('手机号')) score += 30;
                  if ((el.value || '').trim() === '+1' || (el.value || '').trim() === '1') score -= 20;
                  if (text.includes('country') || text.includes('国家/地区') || text.includes('国家地区')) score -= 50;
                  if (text.includes('阿尔巴尼亚') || text.includes('阿富汗') || text.includes('united states (+1)')) score -= 80;
                  if (text.length > 800) score -= 60;
                  return { el, idx, score, text: text.slice(0, 120), before: el.value || '' };
                })
                .sort((a, b) => b.score - a.score);
              const picked = candidates[0];
              if (!picked || picked.score <= 0) {
                return { ok: false, reason: 'no_candidate', candidates: candidates.slice(0, 5).map(({idx, score, text, before}) => ({idx, score, text, before})) };
              }
              const el = picked.el;
              el.focus();
              const proto = Object.getPrototypeOf(el);
              const desc = Object.getOwnPropertyDescriptor(proto, 'value');
              if (desc && desc.set) desc.set.call(el, value);
              else el.value = value;
              el.dispatchEvent(new InputEvent('input', { bubbles: true, data: value, inputType: 'insertText' }));
              el.dispatchEvent(new Event('change', { bubbles: true }));
              el.dispatchEvent(new Event('blur', { bubbles: true }));
              const after = el.value || '';
              return {
                ok: expectedDigits ? after.replace(/\\D+/g, '').includes(expectedDigits) : !!after,
                idx: picked.idx,
                score: picked.score,
                before: picked.before,
                after,
                text: picked.text,
                candidates: candidates.slice(0, 5).map(({idx, score, text, before}) => ({idx, score, text, before})),
              };
            }""",
            phone_for_input,
        )
    except Exception as exc:
        return False, f"页面填写失败: JS 注入手机号异常: {exc}; before={before}"

    after = _compact_input_snapshots(page)
    ok, true_field = _true_oauth_phone_has_digits(page, expected_digits)
    if isinstance(result, dict) and result.get("ok") and ok:
        logger.info("[Codex] add-phone 手机号写入成功: result=%s true_field=%s inputs=%s", result, true_field, after)
        return True, ""
    logger.warning(
        "[Codex] add-phone 手机号写入校验失败: result=%s true_field=%s before=%s after=%s",
        result,
        true_field,
        before,
        after,
    )
    return (
        False,
        f"页面填写失败: 手机号未写入真实手机号输入框; result={result}; true_field={true_field}; inputs={after}",
    )


def _wait_for_phone_otp(sms_url: str) -> str:
    return _make_phone_otp_provider(sms_url)()


def _normalize_oauth_phone_sms_provider(value: str | None = None) -> str:
    normalized = (
        str(value or os.environ.get("OAUTH_PHONE_SMS_PROVIDER") or "phone_pool").strip().lower().replace("-", "_")
    )
    if normalized in {"hero_sms", "herosms", "hero"}:
        return "hero_sms"
    if normalized in {"smsbower", "sms_bower"}:
        return "smsbower"
    if normalized in {"oasis", "oasis_sms", "oasissms", "oapi"}:
        return "oasis"
    return "phone_pool"


def _oauth_add_phone_provider_order(provider_mode: str) -> list[str]:
    """Try the selected provider first, then any configured fallback provider.

    OAuth add-phone must complete if possible. A single provider can fail due to
    service-code or inventory issues, so do not stop until all configured sources
    have been tried.
    """
    primary = _normalize_oauth_phone_sms_provider(provider_mode)
    order = [primary]
    if os.environ.get("OAUTH_HERO_SMS_API_KEY") and "hero_sms" not in order:
        order.append("hero_sms")
    if os.environ.get("OAUTH_SMSBOWER_API_KEY") and "smsbower" not in order:
        order.append("smsbower")
    try:
        from autotoken.auth.oasis_sms import oasis_configured

        if oasis_configured() and "oasis" not in order:
            order.append("oasis")
    except Exception:
        logger.debug("[Codex] 检查 Oasis 配置失败", exc_info=True)
    if "phone_pool" not in order:
        order.append("phone_pool")
    return order


def _normalize_oauth_hero_sms_service(value: str | None = None) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    # Hero-SMS uses SMS-Activate service codes. OpenAI / ChatGPT is "dr".
    if text in {"", "openai", "chatgpt", "chat_gpt", "gpt"}:
        return "dr"
    return text


def _normalize_oauth_hero_sms_country(value: str | None = None) -> str:
    text = str(value or "").strip().lower()
    if text in {"all", "any", "*", "全部", "所有", "不限", "global"}:
        return "all"
    if text and re.fullmatch(r"\d+", text):
        return text
    if text in {"", "us", "usa", "united_states", "united states", "+1"}:
        return "187"
    if text in {"id", "idn", "indonesia", "indonesian", "印度尼西亚", "印尼", "+62"}:
        return "6"
    if text in {"co", "colombia", "colombian", "哥伦比亚", "哥伦比亚共和国", "+57"}:
        return "33"
    return text


def _normalize_oauth_smsbower_country(value: str | None = None) -> str:
    text = str(value or "").strip().lower()
    if text in {"all", "any", "*", "全部", "所有", "不限", "global"}:
        return "all"
    if text and re.fullmatch(r"\d+", text):
        return text
    if text in {"", "us", "usa", "united_states", "united states", "+1"}:
        return "187"
    if text in {"id", "idn", "indonesia", "indonesian", "印度尼西亚", "印尼", "+62"}:
        return "6"
    if text in {"co", "colombia", "colombian", "哥伦比亚", "哥伦比亚共和国", "+57"}:
        return "33"
    return text


def _oauth_hero_sms_config(country: str | None = None, max_price: str | None = None) -> dict[str, str]:
    return {
        "base_url": str(
            os.environ.get("OAUTH_HERO_SMS_BASE_URL")
            or os.environ.get("GOPAY_AUTO_SIGNUP_HERO_SMS_BASE_URL")
            or "https://hero-sms.com/stubs/handler_api.php"
        ).strip(),
        "api_key": str(os.environ.get("OAUTH_HERO_SMS_API_KEY") or "").strip(),
        "country": _normalize_oauth_hero_sms_country(country or os.environ.get("OAUTH_HERO_SMS_COUNTRY")),
        "service": _normalize_oauth_hero_sms_service(os.environ.get("OAUTH_HERO_SMS_SERVICE")),
        "max_price": str(max_price if max_price is not None else os.environ.get("OAUTH_HERO_SMS_MAX_PRICE") or "").strip(),
    }


def _oauth_smsbower_config(country: str | None = None, max_price: str | None = None) -> dict[str, str]:
    return {
        "base_url": str(
            os.environ.get("OAUTH_SMSBOWER_BASE_URL") or "https://smsbower.page/stubs/handler_api.php"
        ).strip(),
        "api_key": str(os.environ.get("OAUTH_SMSBOWER_API_KEY") or "").strip(),
        "country": _normalize_oauth_smsbower_country(country or os.environ.get("OAUTH_SMSBOWER_COUNTRY")),
        "service": _normalize_oauth_hero_sms_service(os.environ.get("OAUTH_SMSBOWER_SERVICE")),
        "max_price": str(max_price if max_price is not None else os.environ.get("OAUTH_SMSBOWER_MAX_PRICE") or "").strip(),
    }


_OAUTH_HERO_SMS_REUSE_LOCK = threading.Lock()
_OAUTH_HERO_SMS_REUSE: dict[str, Any] = {}
_OAUTH_HERO_SMS_REUSE_NAMESPACE = "oauth_hero_sms"
_OAUTH_HERO_SMS_REUSE_KEY = "current"
_OAUTH_HERO_SMS_CANCEL_RECONCILER_LOCK = threading.Lock()
_OAUTH_HERO_SMS_CANCEL_RECONCILER_STOP: threading.Event | None = None
_OAUTH_HERO_SMS_CANCEL_RECONCILER_THREAD: threading.Thread | None = None
_OAUTH_SMSBOWER_REUSE_LOCK = threading.Lock()
_OAUTH_SMSBOWER_REUSE: dict[str, Any] = {}
_OAUTH_SMSBOWER_REUSE_NAMESPACE = "oauth_smsbower"
_OAUTH_SMSBOWER_REUSE_KEY = "current"


def _oauth_hero_sms_ttl_seconds() -> int:
    return max(60, int(float(os.environ.get("OAUTH_HERO_SMS_REUSE_TTL_SECONDS", "1200") or "1200")))


def _oauth_hero_sms_max_binds() -> int:
    return max(1, int(float(os.environ.get("OAUTH_HERO_SMS_MAX_BINDS", "3") or "3")))


def _oauth_smsbower_ttl_seconds() -> int:
    return max(60, int(float(os.environ.get("OAUTH_SMSBOWER_REUSE_TTL_SECONDS", "1200") or "1200")))


def _oauth_smsbower_max_binds() -> int:
    return max(1, int(float(os.environ.get("OAUTH_SMSBOWER_MAX_BINDS", "3") or "3")))


def _oauth_hero_sms_remaining_seconds(entry: dict[str, Any], *, now: float | None = None) -> int:
    current = time.time() if now is None else float(now)
    expires_at = float(entry.get("expires_at") or 0)
    return max(0, int(expires_at - current))


def _oauth_hero_sms_entry_reusable(entry: dict[str, Any], *, now: float | None = None) -> bool:
    if not entry:
        return False
    if entry.get("reserved_by"):
        return False
    if int(entry.get("bound_count") or 0) >= _oauth_hero_sms_max_binds():
        return False
    # Keep a small safety window so we do not submit a phone that may expire
    # while waiting for an OTP.
    return _oauth_hero_sms_remaining_seconds(entry, now=now) > 90


def _oauth_hero_sms_activation_used_codes(entry: dict[str, Any]) -> list[str]:
    activation = (entry or {}).get("activation")
    used_codes = getattr(activation, "used_codes", set()) if activation else (entry or {}).get("used_codes", [])
    return sorted({str(code or "").strip() for code in (used_codes or []) if str(code or "").strip()})


def _oauth_hero_sms_config_fingerprint(cfg: dict[str, str] | None = None) -> str:
    data = cfg or _oauth_hero_sms_config()
    raw = "|".join(str(data.get(key) or "") for key in ("base_url", "api_key", "country", "service", "max_price"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _reconcile_pending_oauth_hero_sms_cancels_once(*, now: float | None = None, limit: int = 100) -> dict[str, int]:
    try:
        from autotoken.auth.oauth_phone_records import list_records, update_record
        from autotoken.payments.gopay_auto_register import (
            DEFAULT_EXISTING_NUMBER_CANCEL_DELAY_SEC,
            SmsActivation,
            _hero_request,
            _is_early_cancel_denied,
        )
    except Exception as exc:
        logger.debug("[Codex] add-phone hero-sms 取消补偿器初始化失败: %s", exc)
        return {"checked": 0, "cancelled": 0, "finished": 0, "pending": 0, "failed": 0}

    cfg = _oauth_hero_sms_config()
    if not cfg.get("api_key"):
        return {"checked": 0, "cancelled": 0, "finished": 0, "pending": 0, "failed": 0}
    current = time.time() if now is None else float(now)
    checked = cancelled = finished = pending = failed = 0
    for record in list_records(1000):
        if checked >= max(1, int(limit or 100)):
            break
        if str(record.get("provider") or "").strip().lower() != "hero_sms":
            continue
        status = str(record.get("status") or "").strip().lower()
        if status not in {"cancel_pending", "cancel_failed"}:
            continue
        try:
            created_at = float(record.get("created_at") or current)
        except Exception:
            created_at = current
        if current - created_at < DEFAULT_EXISTING_NUMBER_CANCEL_DELAY_SEC:
            continue
        activation_id = str(record.get("activation_id") or "").strip()
        record_id = str(record.get("id") or "").strip()
        if not activation_id or not record_id:
            continue
        checked += 1
        try:
            ok, text, _ = _hero_request(
                cfg["base_url"],
                cfg["api_key"],
                "getStatus",
                {"id": activation_id},
                timeout=10,
            )
            provider_status = str(text or "").strip().upper()
            if ok and provider_status in {"STATUS_CANCEL", "STATUS_FINISH", "NO_ACTIVATION"}:
                update_record(record_id, status="cancelled", reason=record.get("reason") or "")
                cancelled += 1
                continue
            country_raw = str(record.get("country") or cfg.get("country") or "187").strip()
            try:
                country_id: int | str = int(float(country_raw))
            except Exception:
                country_id = country_raw or 187
            activation = SmsActivation(
                activation_id=activation_id,
                phone=str(record.get("phone_number") or ""),
                country_id=country_id,
                base_url=cfg["base_url"],
                api_key=cfg["api_key"],
                provider="hero_sms",
                log=logger.info,
            )
            activation.cancel()
            update_record(record_id, status="cancelled", reason=record.get("reason") or "")
            cancelled += 1
        except Exception as exc:
            error_text = str(exc or "")
            error_upper = error_text.upper()
            if "ACTIVATION_NOT_ACTIVE" in error_upper or "NO_ACTIVATION" in error_upper:
                update_record(record_id, status="cancelled", reason=record.get("reason") or "")
                cancelled += 1
                continue
            if "OTP_RECEIVED" in error_upper:
                update_record(record_id, status="finished", reason=f"{record.get('reason') or ''}; otp_received")
                finished += 1
                continue
            if _is_early_cancel_denied(exc):
                update_record(record_id, status="cancel_pending", reason=record.get("reason") or "")
                pending += 1
                continue
            failed += 1
            update_record(
                record_id,
                status="cancel_failed",
                reason=f"{record.get('reason') or ''}; reconcile_cancel_error={exc}",
            )
            logger.info("[Codex] add-phone hero-sms 取消补偿失败: activation=%s error=%s", activation_id, exc)
    if checked:
        logger.info(
            "[Codex] add-phone hero-sms 取消补偿完成: checked=%s cancelled=%s pending=%s failed=%s",
            checked,
            cancelled,
            pending,
            failed,
        )
    return {"checked": checked, "cancelled": cancelled, "finished": finished, "pending": pending, "failed": failed}


def start_oauth_hero_sms_cancel_reconciler(*, interval_seconds: int = 15) -> None:
    global _OAUTH_HERO_SMS_CANCEL_RECONCILER_STOP, _OAUTH_HERO_SMS_CANCEL_RECONCILER_THREAD
    with _OAUTH_HERO_SMS_CANCEL_RECONCILER_LOCK:
        if _OAUTH_HERO_SMS_CANCEL_RECONCILER_THREAD and _OAUTH_HERO_SMS_CANCEL_RECONCILER_THREAD.is_alive():
            return
        stop_event = threading.Event()
        _OAUTH_HERO_SMS_CANCEL_RECONCILER_STOP = stop_event

        def worker() -> None:
            while not stop_event.is_set():
                try:
                    _reconcile_pending_oauth_hero_sms_cancels_once()
                except Exception:
                    logger.debug("[Codex] add-phone hero-sms 取消补偿循环异常", exc_info=True)
                stop_event.wait(max(1, int(interval_seconds or 15)))

        _OAUTH_HERO_SMS_CANCEL_RECONCILER_THREAD = threading.Thread(
            target=worker,
            name="oauth-hero-sms-cancel-reconciler",
            daemon=True,
        )
        _OAUTH_HERO_SMS_CANCEL_RECONCILER_THREAD.start()


def stop_oauth_hero_sms_cancel_reconciler() -> None:
    global _OAUTH_HERO_SMS_CANCEL_RECONCILER_STOP, _OAUTH_HERO_SMS_CANCEL_RECONCILER_THREAD
    with _OAUTH_HERO_SMS_CANCEL_RECONCILER_LOCK:
        stop_event = _OAUTH_HERO_SMS_CANCEL_RECONCILER_STOP
        thread = _OAUTH_HERO_SMS_CANCEL_RECONCILER_THREAD
        _OAUTH_HERO_SMS_CANCEL_RECONCILER_STOP = None
        _OAUTH_HERO_SMS_CANCEL_RECONCILER_THREAD = None
    if stop_event:
        stop_event.set()
    if thread and thread.is_alive():
        thread.join(timeout=2)


def _oauth_hero_sms_persist_entry(entry: dict[str, Any] | None) -> None:
    if not entry:
        sqlite_store.set_json(_OAUTH_HERO_SMS_REUSE_NAMESPACE, _OAUTH_HERO_SMS_REUSE_KEY, {})
        return
    payload = {
        "activation_id": str(entry.get("activation_id") or "").strip(),
        "phone_number": str(entry.get("phone_number") or "").strip(),
        "country_id": str(entry.get("country_id") or "").strip(),
        "created_at": float(entry.get("created_at") or time.time()),
        "expires_at": float(entry.get("expires_at") or 0),
        "bound_count": int(entry.get("bound_count") or 0),
        "used_codes": _oauth_hero_sms_activation_used_codes(entry),
        "config_fingerprint": _oauth_hero_sms_config_fingerprint(),
        "updated_at": time.time(),
    }
    if payload["activation_id"] and payload["phone_number"]:
        sqlite_store.set_json(_OAUTH_HERO_SMS_REUSE_NAMESPACE, _OAUTH_HERO_SMS_REUSE_KEY, payload)
    else:
        sqlite_store.set_json(_OAUTH_HERO_SMS_REUSE_NAMESPACE, _OAUTH_HERO_SMS_REUSE_KEY, {})


def _oauth_hero_sms_persist_used_codes(activation_id: str) -> None:
    target = str(activation_id or "").strip()
    if not target:
        return
    with _OAUTH_HERO_SMS_REUSE_LOCK:
        entry = _OAUTH_HERO_SMS_REUSE.get("current")
        if entry and str(entry.get("activation_id") or "").strip() == target:
            _oauth_hero_sms_persist_entry(entry)


def _oauth_hero_sms_restore_entry(cfg: dict[str, str], activation_cls) -> dict[str, Any] | None:
    payload = sqlite_store.get_json(_OAUTH_HERO_SMS_REUSE_NAMESPACE, _OAUTH_HERO_SMS_REUSE_KEY, default={})
    if not isinstance(payload, dict) or not payload.get("activation_id") or not payload.get("phone_number"):
        return None
    if str(payload.get("config_fingerprint") or "") != _oauth_hero_sms_config_fingerprint(cfg):
        _oauth_hero_sms_persist_entry(None)
        return None
    country_raw = str(payload.get("country_id") or cfg.get("country") or "187").strip().lower()
    if country_raw in {"all", "any", "*"}:
        country_id = "all"
    else:
        try:
            country_id = int(float(country_raw))
        except Exception:
            country_id = 187
    activation = activation_cls(
        activation_id=str(payload.get("activation_id") or "").strip(),
        phone=str(payload.get("phone_number") or "").strip(),
        country_id=country_id,
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        log=logger.info,
    )
    try:
        activation.used_codes.update(
            {str(code or "").strip() for code in (payload.get("used_codes") or []) if str(code or "").strip()}
        )
    except Exception:
        pass
    entry = {
        "activation": activation,
        "activation_id": str(payload.get("activation_id") or "").strip(),
        "phone_number": str(payload.get("phone_number") or "").strip(),
        "country_id": str(country_id),
        "created_at": float(payload.get("created_at") or time.time()),
        "expires_at": float(payload.get("expires_at") or 0),
        "bound_count": int(payload.get("bound_count") or 0),
        "reserved_by": "",
    }
    if not _oauth_hero_sms_entry_reusable(entry):
        _oauth_hero_sms_persist_entry(None)
        _oauth_hero_sms_finish_or_cancel(
            entry,
            finish=int(entry.get("bound_count") or 0) > 0,
            cancel=int(entry.get("bound_count") or 0) <= 0,
            reason="expired_or_full_after_restore",
        )
        return None
    logger.info(
        "[Codex] add-phone 已恢复 hero-sms 可复用号码: activation=%s phone=%s bound=%s/%s remaining=%ss",
        entry.get("activation_id"),
        entry.get("phone_number"),
        entry.get("bound_count") or 0,
        _oauth_hero_sms_max_binds(),
        _oauth_hero_sms_remaining_seconds(entry),
    )
    return entry


def _oauth_hero_sms_item_from_entry(entry: dict[str, Any], email: str = "") -> dict[str, Any]:
    return {
        "id": f"hero_sms:{entry.get('activation_id') or ''}",
        "source": "hero_sms",
        "phone_number": entry.get("phone_number") or "",
        "sms_url": "",
        "activation": entry.get("activation"),
        "activation_id": entry.get("activation_id") or "",
        "country_id": str(entry.get("country_id") or ""),
        "created_at": float(entry.get("created_at") or time.time()),
        "expires_at": float(entry.get("expires_at") or 0),
        "hero_reuse": True,
        "hero_remaining_seconds": _oauth_hero_sms_remaining_seconds(entry),
        "hero_bound_count": int(entry.get("bound_count") or 0),
        "hero_reserved_by": entry.get("reserved_by") or "",
    }


def _oauth_hero_sms_finish_or_cancel(
    entry: dict[str, Any] | None,
    *,
    finish: bool = False,
    cancel: bool = False,
    reason: str = "",
    record_id: str = "",
) -> str:
    if not entry:
        return "noop"
    activation = entry.get("activation")
    if not activation:
        return "noop"
    try:
        if finish:
            activation.finish()
            logger.info(
                "[Codex] add-phone hero-sms 会话已完成: activation=%s reason=%s", entry.get("activation_id"), reason
            )
            return "updated"
        elif cancel:
            activation.cancel()
            logger.info(
                "[Codex] add-phone hero-sms 会话已取消: activation=%s reason=%s", entry.get("activation_id"), reason
            )
            return "updated"
    except Exception as exc:
        if cancel and _schedule_oauth_hero_sms_delayed_cancel(entry, exc, reason=reason, record_id=record_id):
            return "pending"
        logger.info(
            "[Codex] add-phone hero-sms 会话状态更新失败: activation=%s finish=%s cancel=%s reason=%s error=%s",
            entry.get("activation_id"),
            finish,
            cancel,
            reason,
            exc,
        )
        return "failed"
    return "noop"


def _schedule_oauth_hero_sms_delayed_cancel(
    entry: dict[str, Any],
    exc: Exception,
    *,
    reason: str = "",
    record_id: str = "",
) -> bool:
    try:
        from autotoken.payments.gopay_auto_register import _delayed_cancel_activation, _early_cancel_min_activation_time

        min_activation_time = _early_cancel_min_activation_time(exc)
    except Exception:
        return False
    if min_activation_time <= 0:
        return False
    activation = entry.get("activation")
    if not activation:
        return False
    try:
        created_at = float(entry.get("created_at") or 0)
    except Exception:
        created_at = 0
    elapsed = max(0, int(time.time() - created_at)) if created_at > 0 else 0
    delay_seconds = max(1, min_activation_time - elapsed + 1)

    def mark_success() -> None:
        if not record_id:
            return
        try:
            from autotoken.auth.oauth_phone_records import update_record

            update_record(record_id, status="cancelled", reason=reason)
        except Exception:
            logger.debug("[Codex] add-phone 更新 hero-sms 延迟取消成功记录失败", exc_info=True)

    def mark_failure(failure: Exception) -> None:
        if not record_id:
            return
        try:
            from autotoken.auth.oauth_phone_records import update_record

            update_record(record_id, status="cancel_failed", reason=f"{reason}; delayed_cancel_error={failure}")
        except Exception:
            logger.debug("[Codex] add-phone 更新 hero-sms 延迟取消失败记录失败", exc_info=True)

    _delayed_cancel_activation(
        activation,
        delay_seconds=delay_seconds,
        log=logger.info,
        reason=reason or "early_cancel_denied",
        on_success=mark_success,
        on_failure=mark_failure,
    )
    logger.info(
        "[Codex] add-phone hero-sms 取消过早，已安排延迟取消: activation=%s delay=%ss reason=%s error=%s",
        entry.get("activation_id"),
        delay_seconds,
        reason,
        exc,
    )
    return True


def _oauth_smsbower_remaining_seconds(entry: dict[str, Any], *, now: float | None = None) -> int:
    current = time.time() if now is None else float(now)
    expires_at = float(entry.get("expires_at") or 0)
    return max(0, int(expires_at - current))


def _oauth_smsbower_entry_reusable(entry: dict[str, Any], *, now: float | None = None) -> bool:
    if not entry:
        return False
    if entry.get("reserved_by"):
        return False
    if int(entry.get("bound_count") or 0) >= _oauth_smsbower_max_binds():
        return False
    return _oauth_smsbower_remaining_seconds(entry, now=now) > 90


def _oauth_smsbower_config_fingerprint(cfg: dict[str, str] | None = None) -> str:
    data = cfg or _oauth_smsbower_config()
    raw = "|".join(str(data.get(key) or "") for key in ("base_url", "api_key", "country", "service", "max_price"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _oauth_smsbower_persist_entry(entry: dict[str, Any] | None) -> None:
    if not entry:
        sqlite_store.set_json(_OAUTH_SMSBOWER_REUSE_NAMESPACE, _OAUTH_SMSBOWER_REUSE_KEY, {})
        return
    payload = {
        "activation_id": str(entry.get("activation_id") or "").strip(),
        "phone_number": str(entry.get("phone_number") or "").strip(),
        "country_id": str(entry.get("country_id") or "").strip(),
        "created_at": float(entry.get("created_at") or time.time()),
        "expires_at": float(entry.get("expires_at") or 0),
        "bound_count": int(entry.get("bound_count") or 0),
        "used_codes": _oauth_hero_sms_activation_used_codes(entry),
        "config_fingerprint": _oauth_smsbower_config_fingerprint(),
        "updated_at": time.time(),
    }
    if payload["activation_id"] and payload["phone_number"]:
        sqlite_store.set_json(_OAUTH_SMSBOWER_REUSE_NAMESPACE, _OAUTH_SMSBOWER_REUSE_KEY, payload)
    else:
        sqlite_store.set_json(_OAUTH_SMSBOWER_REUSE_NAMESPACE, _OAUTH_SMSBOWER_REUSE_KEY, {})


def _oauth_smsbower_persist_used_codes(activation_id: str) -> None:
    target = str(activation_id or "").strip()
    if not target:
        return
    with _OAUTH_SMSBOWER_REUSE_LOCK:
        entry = _OAUTH_SMSBOWER_REUSE.get("current")
        if entry and str(entry.get("activation_id") or "").strip() == target:
            _oauth_smsbower_persist_entry(entry)


def _oauth_smsbower_finish_or_cancel(
    entry: dict[str, Any] | None, *, finish: bool = False, cancel: bool = False, reason: str = ""
) -> None:
    if not entry:
        return
    activation = entry.get("activation")
    if not activation:
        return
    try:
        if finish:
            activation.finish()
            logger.info(
                "[Codex] add-phone smsbower 会话已完成: activation=%s reason=%s", entry.get("activation_id"), reason
            )
        elif cancel:
            activation.cancel()
            logger.info(
                "[Codex] add-phone smsbower 会话已取消: activation=%s reason=%s", entry.get("activation_id"), reason
            )
    except Exception as exc:
        logger.info(
            "[Codex] add-phone smsbower 会话状态更新失败: activation=%s finish=%s cancel=%s reason=%s error=%s",
            entry.get("activation_id"),
            finish,
            cancel,
            reason,
            exc,
        )


def _oauth_smsbower_restore_entry(cfg: dict[str, str], activation_cls) -> dict[str, Any] | None:
    payload = sqlite_store.get_json(_OAUTH_SMSBOWER_REUSE_NAMESPACE, _OAUTH_SMSBOWER_REUSE_KEY, default={})
    if not isinstance(payload, dict) or not payload.get("activation_id") or not payload.get("phone_number"):
        return None
    if str(payload.get("config_fingerprint") or "") != _oauth_smsbower_config_fingerprint(cfg):
        _oauth_smsbower_persist_entry(None)
        return None
    country_raw = str(payload.get("country_id") or cfg.get("country") or "187").strip().lower()
    if country_raw in {"all", "any", "*"}:
        country_id = "all"
    else:
        try:
            country_id = int(float(country_raw))
        except Exception:
            country_id = 187
    activation = activation_cls(
        activation_id=str(payload.get("activation_id") or "").strip(),
        phone=str(payload.get("phone_number") or "").strip(),
        country_id=country_id,
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        provider="smsbower",
        log=logger.info,
    )
    try:
        activation.used_codes.update(
            {str(code or "").strip() for code in (payload.get("used_codes") or []) if str(code or "").strip()}
        )
    except Exception:
        pass
    entry = {
        "activation": activation,
        "activation_id": str(payload.get("activation_id") or "").strip(),
        "phone_number": str(payload.get("phone_number") or "").strip(),
        "country_id": str(country_id),
        "created_at": float(payload.get("created_at") or time.time()),
        "expires_at": float(payload.get("expires_at") or 0),
        "bound_count": int(payload.get("bound_count") or 0),
        "reserved_by": "",
    }
    if not _oauth_smsbower_entry_reusable(entry):
        _oauth_smsbower_persist_entry(None)
        _oauth_smsbower_finish_or_cancel(
            entry,
            finish=int(entry.get("bound_count") or 0) > 0,
            cancel=int(entry.get("bound_count") or 0) <= 0,
            reason="expired_or_full_after_restore",
        )
        return None
    logger.info(
        "[Codex] add-phone 已恢复 smsbower 可复用号码: activation=%s phone=%s bound=%s/%s remaining=%ss",
        entry.get("activation_id"),
        entry.get("phone_number"),
        entry.get("bound_count") or 0,
        _oauth_smsbower_max_binds(),
        _oauth_smsbower_remaining_seconds(entry),
    )
    return entry


def _oauth_smsbower_item_from_entry(entry: dict[str, Any], email: str = "") -> dict[str, Any]:
    return {
        "id": f"smsbower:{entry.get('activation_id') or ''}",
        "record_id": f"smsbower:{entry.get('activation_id') or ''}",
        "source": "smsbower",
        "phone_number": entry.get("phone_number") or "",
        "sms_url": "",
        "activation": entry.get("activation"),
        "activation_id": entry.get("activation_id") or "",
        "country_id": str(entry.get("country_id") or ""),
        "created_at": float(entry.get("created_at") or time.time()),
        "expires_at": float(entry.get("expires_at") or 0),
        "smsbower_reuse": True,
        "smsbower_remaining_seconds": _oauth_smsbower_remaining_seconds(entry),
        "smsbower_bound_count": int(entry.get("bound_count") or 0),
        "smsbower_reserved_by": entry.get("reserved_by") or "",
    }


def _acquire_oauth_hero_sms_phone(
    email: str = "",
    *,
    country: str | None = None,
    max_price: str | None = None,
    reservation_owner: str | None = None,
    allow_reuse: bool = True,
) -> tuple[dict | None, str]:
    try:
        from autotoken.payments.gopay_auto_register import SmsActivation, _hero_get_number
    except Exception as exc:
        return None, f"hero-sms 模块不可用: {exc}"

    cfg = _oauth_hero_sms_config(country, max_price=max_price)
    if not cfg["api_key"]:
        return None, "缺少 OAUTH_HERO_SMS_API_KEY 配置"
    country_raw = str(cfg["country"] or "187").strip().lower()
    if country_raw in {"all", "any", "*"}:
        country_id = "all"
    else:
        try:
            country_id = int(float(country_raw))
        except Exception:
            country_id = 187
    now = time.time()
    owner = str(reservation_owner or email or f"anonymous:{threading.get_ident()}").strip()
    cached = None
    if allow_reuse:
        with _OAUTH_HERO_SMS_REUSE_LOCK:
            cached = _OAUTH_HERO_SMS_REUSE.get("current")
            if not cached:
                cached = _oauth_hero_sms_restore_entry(cfg, SmsActivation)
                if cached:
                    _OAUTH_HERO_SMS_REUSE["current"] = cached
            if _oauth_hero_sms_entry_reusable(cached or {}, now=now):
                cached["reserved_by"] = owner
                logger.info(
                    "[Codex] add-phone 复用 hero-sms 号码: email=%s activation=%s phone=%s bound=%s/%s remaining=%ss",
                    email,
                    cached.get("activation_id"),
                    cached.get("phone_number"),
                    cached.get("bound_count") or 0,
                    _oauth_hero_sms_max_binds(),
                    _oauth_hero_sms_remaining_seconds(cached, now=now),
                )
                return _oauth_hero_sms_item_from_entry(cached, email), ""
            if cached and not _oauth_hero_sms_entry_reusable(cached, now=now):
                _OAUTH_HERO_SMS_REUSE.pop("current", None)
                _oauth_hero_sms_persist_entry(None)
                finish_old = int(cached.get("bound_count") or 0) > 0
            else:
                cached = None
                finish_old = False
        if cached:
            _oauth_hero_sms_finish_or_cancel(
                cached,
                finish=finish_old,
                cancel=not finish_old,
                reason="expired_or_full_before_new_acquire",
            )

    activation_id, phone, error = _hero_get_number(
        service_code=cfg["service"] or "dr",
        country_id=country_id,
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        max_price=cfg["max_price"],
    )
    if not activation_id or not phone:
        return None, error or "hero-sms 未返回可用号码"
    activation = SmsActivation(
        activation_id=activation_id,
        phone=phone,
        country_id=country_id,
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        log=logger.info,
    )
    logger.info(
        "[Codex] add-phone hero-sms 已取号: email=%s activation=%s service=%s country=%s max_price=%s",
        email,
        activation_id,
        cfg["service"] or "openai",
        country_id,
        cfg["max_price"] or "-",
    )
    entry = {
        "activation": activation,
        "activation_id": activation_id,
        "phone_number": phone,
        "country_id": str(country_id),
        "created_at": now,
        "expires_at": now + _oauth_hero_sms_ttl_seconds(),
        "bound_count": 0,
        "reserved_by": owner,
    }
    if allow_reuse:
        with _OAUTH_HERO_SMS_REUSE_LOCK:
            _OAUTH_HERO_SMS_REUSE["current"] = entry
            _oauth_hero_sms_persist_entry(entry)
    item = _oauth_hero_sms_item_from_entry(entry, email)
    item["hero_reuse"] = allow_reuse
    item["record_id"] = f"hero_sms:{activation_id}"
    try:
        from autotoken.auth.oauth_phone_records import record_acquired

        record_acquired(
            {
                "id": item["record_id"],
                "provider": "hero_sms",
                "activation_id": activation_id,
                "phone_number": phone,
                "country": str(country_id),
                "service": cfg["service"] or "dr",
                "price": cfg["max_price"] or "",
                "price_limit": cfg["max_price"] or "",
                "price_source": "max_price_config" if cfg["max_price"] else "unknown",
                "email": email,
                "status": "acquired",
            }
        )
    except Exception:
        logger.debug("[Codex] add-phone 记录 hero-sms 取号失败", exc_info=True)
    return item, ""


def _acquire_oauth_smsbower_phone(
    email: str = "",
    *,
    country: str | None = None,
    max_price: str | None = None,
    reservation_owner: str | None = None,
    allow_reuse: bool = True,
) -> tuple[dict | None, str]:
    try:
        from autotoken.payments.gopay_auto_register import SmsActivation, _smsbower_get_number
    except Exception as exc:
        return None, f"smsbower 模块不可用: {exc}"

    cfg = _oauth_smsbower_config(country, max_price=max_price)
    if not cfg["api_key"]:
        return None, "缺少 OAUTH_SMSBOWER_API_KEY 配置"
    country_raw = str(cfg["country"] or "187").strip().lower()
    if country_raw in {"all", "any", "*"}:
        country_id = "all"
    else:
        try:
            country_id = int(float(country_raw))
        except Exception:
            country_id = 187
    logger.info(
        "[Codex] add-phone smsbower 取号参数: email=%s service=%s country_raw=%s country_id=%s max_price=%s",
        email,
        cfg["service"] or "dr",
        country_raw,
        country_id,
        cfg["max_price"] or "-",
    )
    now = time.time()
    owner = str(reservation_owner or email or f"anonymous:{threading.get_ident()}").strip()
    cached = None
    if allow_reuse:
        with _OAUTH_SMSBOWER_REUSE_LOCK:
            cached = _OAUTH_SMSBOWER_REUSE.get("current")
            if not cached:
                cached = _oauth_smsbower_restore_entry(cfg, SmsActivation)
                if cached:
                    _OAUTH_SMSBOWER_REUSE["current"] = cached
            if _oauth_smsbower_entry_reusable(cached or {}, now=now):
                cached["reserved_by"] = owner
                logger.info(
                    "[Codex] add-phone 复用 smsbower 号码: email=%s activation=%s phone=%s bound=%s/%s remaining=%ss",
                    email,
                    cached.get("activation_id"),
                    cached.get("phone_number"),
                    cached.get("bound_count") or 0,
                    _oauth_smsbower_max_binds(),
                    _oauth_smsbower_remaining_seconds(cached, now=now),
                )
                return _oauth_smsbower_item_from_entry(cached, email), ""
            if cached and not _oauth_smsbower_entry_reusable(cached, now=now):
                _OAUTH_SMSBOWER_REUSE.pop("current", None)
                _oauth_smsbower_persist_entry(None)
                finish_old = int(cached.get("bound_count") or 0) > 0
            else:
                cached = None
                finish_old = False
        if cached:
            _oauth_smsbower_finish_or_cancel(
                cached,
                finish=finish_old,
                cancel=not finish_old,
                reason="expired_or_full_before_new_acquire",
            )

    meta: dict[str, Any] = {}
    activation_id, phone, error = _smsbower_get_number(
        service_code=cfg["service"] or "dr",
        country_id=country_id,
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        max_price=cfg["max_price"],
        meta_out=meta,
    )
    if not activation_id or not phone:
        return None, error or "smsbower 未返回可用号码"
    activation = SmsActivation(
        activation_id=activation_id,
        phone=phone,
        country_id=country_id,
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        provider="smsbower",
        log=logger.info,
    )
    logger.info(
        "[Codex] add-phone smsbower 已取号: email=%s activation=%s service=%s country=%s max_price=%s",
        email,
        activation_id,
        cfg["service"] or "openai",
        country_id,
        cfg["max_price"] or "-",
    )
    record_id = f"smsbower:{activation_id}"
    entry = {
        "activation": activation,
        "activation_id": activation_id,
        "phone_number": phone,
        "country_id": str(country_id),
        "created_at": now,
        "expires_at": now + _oauth_smsbower_ttl_seconds(),
        "bound_count": 0,
        "reserved_by": owner,
    }
    if allow_reuse:
        with _OAUTH_SMSBOWER_REUSE_LOCK:
            _OAUTH_SMSBOWER_REUSE["current"] = entry
            _oauth_smsbower_persist_entry(entry)
    try:
        from autotoken.auth.oauth_phone_records import record_acquired

        price = str(meta.get("price") or "").strip()
        price_source = str(meta.get("price_source") or "").strip()
        if not price and cfg["max_price"]:
            price = cfg["max_price"]
            price_source = "max_price_config"
        record_acquired(
            {
                "id": record_id,
                "provider": "smsbower",
                "activation_id": activation_id,
                "phone_number": phone,
                "country": str(country_id),
                "service": cfg["service"] or "dr",
                "price": price,
                "price_limit": cfg["max_price"] or "",
                "price_source": price_source or "unknown",
                "email": email,
                "status": "acquired",
                "meta": meta,
            }
        )
    except Exception:
        logger.debug("[Codex] add-phone 记录 smsbower 取号失败", exc_info=True)
    item = _oauth_smsbower_item_from_entry(entry, email)
    item["smsbower_reuse"] = allow_reuse
    return item, ""


def _release_oauth_sms_activation_phone(
    phone_item: dict,
    *,
    email: str = "",
    finish: bool = False,
    cancel: bool = False,
    reason: str = "",
    reservation_owner: str | None = None,
) -> None:
    if str(phone_item.get("source") or "").lower() == "smsbower":
        _release_oauth_smsbower_phone(
            phone_item,
            email=email,
            finish=finish,
            cancel=cancel,
            reason=reason,
            reservation_owner=reservation_owner,
        )
        return
    activation = phone_item.get("activation")
    activation_id = str(phone_item.get("activation_id") or "").strip()
    record_id = str(phone_item.get("record_id") or phone_item.get("id") or "").strip()
    if not activation:
        return
    try:
        if finish:
            activation.finish()
            logger.info(
                "[Codex] add-phone 短信会话已完成: source=%s activation=%s reason=%s",
                phone_item.get("source"),
                activation_id,
                reason,
            )
            if record_id:
                from autotoken.auth.oauth_phone_records import update_record

                update_record(record_id, status="success", reason=reason)
        elif cancel:
            activation.cancel()
            logger.info(
                "[Codex] add-phone 短信会话已取消: source=%s activation=%s reason=%s",
                phone_item.get("source"),
                activation_id,
                reason,
            )
            if record_id:
                from autotoken.auth.oauth_phone_records import update_record

                update_record(record_id, status="cancelled", reason=reason)
    except Exception as exc:
        logger.info(
            "[Codex] add-phone 短信会话状态更新失败: source=%s activation=%s finish=%s cancel=%s reason=%s error=%s",
            phone_item.get("source"),
            activation_id,
            finish,
            cancel,
            reason,
            exc,
        )


def _release_oauth_smsbower_phone(
    phone_item: dict,
    *,
    email: str = "",
    finish: bool = False,
    cancel: bool = False,
    reason: str = "",
    reservation_owner: str | None = None,
) -> None:
    activation_id = str(phone_item.get("activation_id") or "").strip()
    record_id = str(phone_item.get("record_id") or phone_item.get("id") or "").strip()
    if not activation_id:
        return
    owner = str(reservation_owner or phone_item.get("smsbower_reserved_by") or email or "").strip()
    entry_to_close: dict[str, Any] | None = None
    close_finish = False
    close_cancel = False
    with _OAUTH_SMSBOWER_REUSE_LOCK:
        entry = _OAUTH_SMSBOWER_REUSE.get("current")
        if entry and str(entry.get("activation_id") or "") == activation_id:
            if finish or cancel:
                entry_to_close = _OAUTH_SMSBOWER_REUSE.pop("current", None)
                _oauth_smsbower_persist_entry(None)
                close_finish = finish
                close_cancel = cancel
            else:
                if not owner or str(entry.get("reserved_by") or "") == owner:
                    entry["reserved_by"] = ""
                _oauth_smsbower_persist_entry(entry)
                logger.info(
                    "[Codex] add-phone smsbower 号码已释放供复用: activation=%s phone=%s bound=%s/%s remaining=%ss reason=%s",
                    activation_id,
                    entry.get("phone_number"),
                    entry.get("bound_count") or 0,
                    _oauth_smsbower_max_binds(),
                    _oauth_smsbower_remaining_seconds(entry),
                    reason,
                )
                if record_id:
                    try:
                        from autotoken.auth.oauth_phone_records import update_record

                        update_record(record_id, status="released", reason=reason)
                    except Exception:
                        logger.debug("[Codex] add-phone 更新 smsbower 释放记录失败", exc_info=True)
                return
    if entry_to_close:
        _oauth_smsbower_finish_or_cancel(entry_to_close, finish=close_finish, cancel=close_cancel, reason=reason)
        if record_id:
            try:
                from autotoken.auth.oauth_phone_records import update_record

                update_record(record_id, status="success" if close_finish else "cancelled", reason=reason)
            except Exception:
                logger.debug("[Codex] add-phone 更新 smsbower 记录失败", exc_info=True)
        return
    fallback = {
        "activation": phone_item.get("activation"),
        "activation_id": activation_id,
    }
    _oauth_smsbower_finish_or_cancel(fallback, finish=finish, cancel=cancel, reason=reason)
    if record_id:
        try:
            from autotoken.auth.oauth_phone_records import update_record

            update_record(
                record_id, status="success" if finish else "cancelled" if cancel else "released", reason=reason
            )
        except Exception:
            logger.debug("[Codex] add-phone 更新 smsbower fallback 记录失败", exc_info=True)


def _mark_oauth_smsbower_bound(phone_item: dict, *, email: str = "") -> None:
    activation_id = str(phone_item.get("activation_id") or "").strip()
    record_id = str(phone_item.get("record_id") or phone_item.get("id") or "").strip()
    if not activation_id:
        return
    entry_to_finish: dict[str, Any] | None = None
    with _OAUTH_SMSBOWER_REUSE_LOCK:
        entry = _OAUTH_SMSBOWER_REUSE.get("current")
        if entry and str(entry.get("activation_id") or "") == activation_id:
            entry["bound_count"] = int(entry.get("bound_count") or 0) + 1
            entry["reserved_by"] = ""
            remaining = _oauth_smsbower_remaining_seconds(entry)
            if entry["bound_count"] >= _oauth_smsbower_max_binds() or remaining <= 90:
                entry_to_finish = _OAUTH_SMSBOWER_REUSE.pop("current", None)
                _oauth_smsbower_persist_entry(None)
            else:
                _oauth_smsbower_persist_entry(entry)
                logger.info(
                    "[Codex] add-phone smsbower 绑定成功后保留号码复用: email=%s activation=%s phone=%s bound=%s/%s remaining=%ss",
                    email,
                    activation_id,
                    entry.get("phone_number"),
                    entry["bound_count"],
                    _oauth_smsbower_max_binds(),
                    remaining,
                )
                if record_id:
                    try:
                        from autotoken.auth.oauth_phone_records import update_record

                        update_record(record_id, status="reusable", email=email, reason="success_reusable")
                    except Exception:
                        logger.debug("[Codex] add-phone 更新 smsbower 复用记录失败", exc_info=True)
                return
    if entry_to_finish:
        _oauth_smsbower_finish_or_cancel(entry_to_finish, finish=True, reason="max_binds_or_expiring_after_success")
        if record_id:
            try:
                from autotoken.auth.oauth_phone_records import update_record

                update_record(record_id, status="success", email=email, reason="max_binds_or_expiring_after_success")
            except Exception:
                logger.debug("[Codex] add-phone 更新 smsbower 完成记录失败", exc_info=True)
        return
    fallback = {"activation": phone_item.get("activation"), "activation_id": activation_id}
    _oauth_smsbower_finish_or_cancel(fallback, finish=True, reason="success_without_reusable_entry")
    if record_id:
        try:
            from autotoken.auth.oauth_phone_records import update_record

            update_record(record_id, status="success", email=email, reason="success_without_reusable_entry")
        except Exception:
            logger.debug("[Codex] add-phone 更新 smsbower fallback 完成记录失败", exc_info=True)


def _release_oauth_hero_sms_phone(
    phone_item: dict,
    *,
    email: str = "",
    finish: bool = False,
    cancel: bool = False,
    reason: str = "",
    reservation_owner: str | None = None,
) -> None:
    activation_id = str(phone_item.get("activation_id") or "").strip()
    record_id = str(phone_item.get("record_id") or phone_item.get("id") or "").strip()
    if not activation_id:
        return
    owner = str(reservation_owner or phone_item.get("hero_reserved_by") or email or "").strip()
    entry_to_close: dict[str, Any] | None = None
    close_finish = False
    close_cancel = False
    with _OAUTH_HERO_SMS_REUSE_LOCK:
        entry = _OAUTH_HERO_SMS_REUSE.get("current")
        if entry and str(entry.get("activation_id") or "") == activation_id:
            if finish or cancel:
                entry_to_close = _OAUTH_HERO_SMS_REUSE.pop("current", None)
                _oauth_hero_sms_persist_entry(None)
                close_finish = finish
                close_cancel = cancel
            else:
                if not owner or str(entry.get("reserved_by") or "") == owner:
                    entry["reserved_by"] = ""
                _oauth_hero_sms_persist_entry(entry)
                logger.info(
                    "[Codex] add-phone hero-sms 号码已释放供复用: activation=%s phone=%s bound=%s/%s remaining=%ss reason=%s",
                    activation_id,
                    entry.get("phone_number"),
                    entry.get("bound_count") or 0,
                    _oauth_hero_sms_max_binds(),
                    _oauth_hero_sms_remaining_seconds(entry),
                    reason,
                )
                if record_id:
                    try:
                        from autotoken.auth.oauth_phone_records import update_record

                        update_record(record_id, status="released", reason=reason)
                    except Exception:
                        logger.debug("[Codex] add-phone 更新 hero-sms 释放记录失败", exc_info=True)
                return
    if entry_to_close:
        update_result = _oauth_hero_sms_finish_or_cancel(
            entry_to_close,
            finish=close_finish,
            cancel=close_cancel,
            reason=reason,
            record_id=record_id,
        )
        if record_id:
            try:
                from autotoken.auth.oauth_phone_records import update_record

                if close_finish:
                    status = "success"
                elif update_result == "pending":
                    status = "cancel_pending"
                elif update_result == "updated":
                    status = "cancelled"
                else:
                    status = "cancel_failed"
                update_record(record_id, status=status, reason=reason)
            except Exception:
                logger.debug("[Codex] add-phone 更新 hero-sms 记录失败", exc_info=True)
        return
    # Fallback for entries that were not the current reusable session.
    fallback = {
        "activation": phone_item.get("activation"),
        "activation_id": activation_id,
        "created_at": phone_item.get("created_at"),
    }
    update_result = _oauth_hero_sms_finish_or_cancel(
        fallback,
        finish=finish,
        cancel=cancel,
        reason=reason,
        record_id=record_id,
    )
    if record_id:
        try:
            from autotoken.auth.oauth_phone_records import update_record

            if finish:
                status = "success"
            elif cancel and update_result == "pending":
                status = "cancel_pending"
            elif cancel and update_result == "updated":
                status = "cancelled"
            elif cancel:
                status = "cancel_failed"
            else:
                status = "released"
            update_record(record_id, status=status, reason=reason)
        except Exception:
            logger.debug("[Codex] add-phone 更新 hero-sms fallback 记录失败", exc_info=True)


def _mark_oauth_hero_sms_bound(phone_item: dict, *, email: str = "") -> None:
    activation_id = str(phone_item.get("activation_id") or "").strip()
    record_id = str(phone_item.get("record_id") or phone_item.get("id") or "").strip()
    if not activation_id:
        return
    entry_to_finish: dict[str, Any] | None = None
    with _OAUTH_HERO_SMS_REUSE_LOCK:
        entry = _OAUTH_HERO_SMS_REUSE.get("current")
        if entry and str(entry.get("activation_id") or "") == activation_id:
            entry["bound_count"] = int(entry.get("bound_count") or 0) + 1
            entry["reserved_by"] = ""
            remaining = _oauth_hero_sms_remaining_seconds(entry)
            if entry["bound_count"] >= _oauth_hero_sms_max_binds() or remaining <= 90:
                entry_to_finish = _OAUTH_HERO_SMS_REUSE.pop("current", None)
                _oauth_hero_sms_persist_entry(None)
            else:
                _oauth_hero_sms_persist_entry(entry)
                logger.info(
                    "[Codex] add-phone hero-sms 绑定成功后保留号码复用: email=%s activation=%s phone=%s bound=%s/%s remaining=%ss",
                    email,
                    activation_id,
                    entry.get("phone_number"),
                    entry["bound_count"],
                    _oauth_hero_sms_max_binds(),
                    remaining,
                )
                if record_id:
                    try:
                        from autotoken.auth.oauth_phone_records import update_record

                        update_record(
                            record_id,
                            status="success_reusable",
                            reason="bound_and_reusable",
                            bound_count=entry["bound_count"],
                        )
                    except Exception:
                        logger.debug("[Codex] add-phone 更新 hero-sms 绑定记录失败", exc_info=True)
                return
    if entry_to_finish:
        _oauth_hero_sms_finish_or_cancel(entry_to_finish, finish=True, reason="max_binds_or_expiring_after_success")
        if record_id:
            try:
                from autotoken.auth.oauth_phone_records import update_record

                update_record(record_id, status="success", reason="max_binds_or_expiring_after_success")
            except Exception:
                logger.debug("[Codex] add-phone 更新 hero-sms 完成记录失败", exc_info=True)
        return
    fallback = {"activation": phone_item.get("activation"), "activation_id": activation_id}
    _oauth_hero_sms_finish_or_cancel(fallback, finish=True, reason="success_without_reusable_entry")
    if record_id:
        try:
            from autotoken.auth.oauth_phone_records import update_record

            update_record(record_id, status="success", reason="success_without_reusable_entry")
        except Exception:
            logger.debug("[Codex] add-phone 更新 hero-sms fallback 完成记录失败", exc_info=True)


def _make_phone_item_otp_provider(phone_item: dict):
    source = str(phone_item.get("source") or "").lower()
    if source in {"hero_sms", "smsbower", "oasis"}:
        activation = phone_item.get("activation")
        if not activation:
            raise RuntimeError(f"{source} activation 为空")

        def _provider() -> str:
            ignored = getattr(_provider, "_gopay_ignored_otps", set())
            try:
                activation.used_codes.update({str(item or "").strip() for item in ignored if str(item or "").strip()})
            except Exception:
                pass
            code = activation.wait_code(
                timeout_sec=max(60, int(os.environ.get("CODEX_OAUTH_PHONE_OTP_TIMEOUT", "120") or "120")),
                label="oauth-add-phone",
                max_resends=0,
            )
            if source == "hero_sms":
                _oauth_hero_sms_persist_used_codes(str(phone_item.get("activation_id") or ""))
            elif source == "smsbower":
                _oauth_smsbower_persist_used_codes(str(phone_item.get("activation_id") or ""))
            if not code:
                if not getattr(_provider, "_dynamic_sms_first_code_received", False):
                    raise CodexOAuthHeroSmsFirstCodeTimeout(f"{source} 120s 内未收到第一个验证码")
                raise TimeoutError(f"{source} 120s 内未收到验证码")
            _provider._dynamic_sms_first_code_received = True
            return code

        return _provider
    return _make_phone_otp_provider(str(phone_item.get("sms_url") or ""))


def _make_phone_otp_provider(sms_url: str):
    return sms_otp_service.poll_otp_from_sms_url(
        sms_url,
        timeout_seconds=max(60, int(os.environ.get("CODEX_OAUTH_PHONE_OTP_TIMEOUT", "120") or "120")),
        initial_delay_seconds=max(0.0, float(os.environ.get("CODEX_OAUTH_PHONE_OTP_INITIAL_DELAY", "5") or "5")),
        resend_after_seconds=max(0.0, float(os.environ.get("CODEX_OAUTH_PHONE_OTP_RESEND_AFTER", "60") or "60")),
        max_resend_attempts=0,
        progress=lambda stage, **kwargs: logger.info(
            "[Codex] add-phone 等待短信验证码: stage=%s detail=%s", stage, kwargs
        ),
    )


def _submit_oauth_add_phone_candidate(page, *, email: str, phone_item: dict) -> tuple[bool, str]:
    phone = str(phone_item.get("phone_number") or "").strip()
    sms_url = str(phone_item.get("sms_url") or "").strip()
    dynamic_sms_source = str(phone_item.get("source") or "").lower()
    is_dynamic_sms = dynamic_sms_source in {"hero_sms", "smsbower", "oasis"}
    if not phone or (not sms_url and not is_dynamic_sms):
        return False, "手机号或接码链接为空"
    if not _is_add_phone_page(page):
        return True, ""

    logger.info(
        "[Codex] add-phone 使用%s号码: email=%s phone=%s",
        f"{dynamic_sms_source} 动态" if is_dynamic_sms else "手机号池",
        email,
        phone,
    )
    phone_input = _phone_input_locator(page)
    if not phone_input:
        return False, "未找到 add-phone 手机号输入框"
    phone_for_input = _format_oauth_phone_for_input(
        page,
        phone_input,
        phone,
        force_us=is_dynamic_sms and str(phone_item.get("country_id") or "") == "187",
    )
    ok, fill_error = _fill_oauth_phone_field(page, phone_input, phone_for_input)
    if not ok:
        return False, fill_error or "页面填写失败: 手机号输入框填写失败"
    confirmed, true_field = _true_oauth_phone_has_digits(page, re.sub(r"\D+", "", phone_for_input))
    if not confirmed:
        return (
            False,
            f"页面填写失败: 提交前真实手机号输入框校验失败; true_field={true_field}; inputs={_compact_input_snapshots(page)}",
        )
    _screenshot(page, "codex_add_phone_01_after_phone_fill.png")
    if not _click_primary_auth_button(page, phone_input, ["Continue", "继续", "Send code", "发送验证码", "Verify"]):
        return False, "手机号提交按钮点击失败"
    time.sleep(1)
    _screenshot(page, "codex_add_phone_02_after_phone_submit.png")

    deadline = time.time() + 35
    otp_input = None
    while time.time() < deadline:
        rate_limited = _detect_phone_rate_limited(page)
        if rate_limited:
            raise CodexOAuthPhoneRateLimited(rate_limited)
        rejected = _detect_phone_rejected(page)
        if rejected:
            return False, rejected
        otp_input = _phone_otp_input_locator(page)
        if otp_input:
            break
        if not _is_add_phone_page(page) and "phone-verification" not in (page.url or "").lower():
            break
        time.sleep(1)
    if not otp_input:
        otp_input = _phone_otp_input_locator(page)
    if not otp_input:
        rate_limited = _detect_phone_rate_limited(page)
        if rate_limited:
            raise CodexOAuthPhoneRateLimited(rate_limited)
        rejected = _detect_phone_rejected(page)
        return (
            False,
            rejected or f"页面填写失败: 手机号提交后未进入验证码输入页; inputs={_compact_input_snapshots(page)}",
        )

    provider = _make_phone_item_otp_provider(phone_item)
    ignored_codes: set[str] = set()
    max_invalid_retries = max(1, int(os.environ.get("CODEX_OAUTH_PHONE_OTP_INVALID_RETRIES", "2") or "2"))
    for code_attempt in range(1, max_invalid_retries + 2):
        rate_limited = _detect_phone_rate_limited(page)
        if rate_limited:
            raise CodexOAuthPhoneRateLimited(rate_limited)
        try:
            provider._gopay_ignored_otps = ignored_codes
            code = provider()
        except CodexOAuthHeroSmsFirstCodeTimeout as exc:
            return False, f"HERO_SMS_FIRST_CODE_TIMEOUT:{exc}"
        except Exception as exc:
            return False, f"等待手机验证码超时: {exc}"
        otp_input = _phone_otp_input_locator(page) or otp_input
        if not _fill_otp_input_and_verify(otp_input, code):
            return False, "手机验证码输入框填写失败"
        page.locator(
            'button[type="submit"], button:has-text("Continue"), button:has-text("继续"), button:has-text("Verify")'
        ).first.click()
        logger.info("[Codex] add-phone 已提交手机验证码: email=%s phone=%s attempt=%s", email, phone, code_attempt)

        submit_status, submit_detail = _wait_for_otp_submit_result(page, timeout=20)
        rate_limited = _detect_phone_rate_limited(page)
        if rate_limited:
            raise CodexOAuthPhoneRateLimited(rate_limited)
        if submit_status != "invalid":
            if submit_status == "pending" and _phone_otp_input_locator(page):
                return False, "手机验证码提交后页面未前进"
            return True, ""

        ignored_codes.add(str(code or "").strip())
        if code_attempt > max_invalid_retries:
            return False, f"手机验证码无效，已重发 {max_invalid_retries} 次仍失败: {submit_detail or ''}".strip()
        if not _click_phone_resend_if_present(page):
            return False, f"手机验证码无效且未找到重新发送按钮: {submit_detail or ''}".strip()
        if is_dynamic_sms:
            try:
                activation = phone_item.get("activation")
                if activation:
                    activation.resend()
            except Exception as exc:
                logger.info(
                    "[Codex] add-phone 动态短信标记重发失败: source=%s activation=%s error=%s",
                    dynamic_sms_source,
                    phone_item.get("activation_id"),
                    exc,
                )
        logger.info(
            "[Codex] add-phone 手机验证码无效，已点击重新发送并等待新验证码: email=%s phone=%s attempt=%s/%s",
            email,
            phone,
            code_attempt,
            max_invalid_retries,
        )
        time.sleep(max(1.0, float(os.environ.get("CODEX_OAUTH_PHONE_OTP_AFTER_INVALID_RESEND_DELAY", "2") or "2")))
    return False, "手机验证码处理失败"


def _should_invalidate_oauth_phone(error: str) -> bool:
    text = str(error or "")
    if not text:
        return False
    if text.startswith("页面填写失败:"):
        return False
    if text.startswith("手机验证码无效且未找到重新发送按钮"):
        return False
    return not text.startswith("手机验证码提交后页面未前进")


def _classify_oauth_phone_failure(error: str) -> str:
    text = str(error or "").lower()
    if not text:
        return ""
    if "hero_sms_first_code_timeout" in text:
        return "hero_release"
    if any(hint in text for hint in _PHONE_FULL_HINTS):
        return "invalid"
    if any(hint in text for hint in _PHONE_COOLDOWN_HINTS):
        return "cooldown"
    return "invalid" if _should_invalidate_oauth_phone(error) else ""


def _classify_oauth_phone_rate_limit_exception(error: str) -> str:
    """Separate GPT-account add-phone throttling from phone-number throttling."""
    text = str(error or "").lower()
    if not text:
        return ""
    if any(hint in text for hint in _PHONE_RATE_LIMIT_HINTS):
        return "account_rate_limited"
    return _classify_oauth_phone_failure(error)


def _handle_oauth_add_phone_if_present(
    page,
    *,
    email: str,
    phone_sms_provider: str | None = None,
    phone_sms_country: str | None = None,
    phone_sms_oasis_cdks: str | None = None,
) -> bool:
    if not _is_add_phone_page(page):
        return False
    provider_mode = _normalize_oauth_phone_sms_provider(phone_sms_provider)
    provider_order = _oauth_add_phone_provider_order(provider_mode)
    if phone_sms_country and provider_mode == "smsbower":
        country_override = _normalize_oauth_smsbower_country(phone_sms_country)
    else:
        country_override = _normalize_oauth_hero_sms_country(phone_sms_country) if phone_sms_country else None
    logger.info(
        "[Codex] add-phone 取号配置: email=%s provider=%s providers=%s country=%s",
        email,
        provider_mode,
        ",".join(provider_order),
        country_override or "<env/default>",
    )
    pool_api: dict[str, Any] = {}
    if "phone_pool" in provider_order:
        try:
            from autotoken.auth.oauth_phone_pool import (
                acquire_available_phone,
                mark_phone_bound,
                mark_phone_cooldown,
                mark_phone_invalid,
                release_phone_reservation,
            )

            pool_api = {
                "acquire": acquire_available_phone,
                "cooldown": mark_phone_cooldown,
                "bound": mark_phone_bound,
                "invalid": mark_phone_invalid,
                "release": release_phone_reservation,
            }
        except Exception as exc:
            logger.warning("[Codex] add-phone 手机号池不可用: %s", exc)
            pool_api = {}

    def acquire_phone_item() -> tuple[dict | None, str]:
        errors: list[str] = []
        for candidate in provider_order:
            phone_item: dict | None = None
            error = ""
            if candidate == "hero_sms":
                phone_item, error = _acquire_oauth_hero_sms_phone(email, country=country_override)
            elif candidate == "smsbower":
                phone_item, error = _acquire_oauth_smsbower_phone(email, country=country_override)
            elif candidate == "oasis":
                from autotoken.auth.oasis_sms import acquire_oasis_phone

                phone_item, error = acquire_oasis_phone(email, cdks=phone_sms_oasis_cdks)
            elif pool_api.get("acquire"):
                phone_item = pool_api["acquire"](email)
            else:
                error = "手机号池不可用"

            if phone_item:
                if candidate != provider_mode:
                    logger.info(
                        "[Codex] add-phone %s取号失败后已切换到%s: email=%s",
                        provider_mode,
                        candidate,
                        email,
                    )
                return phone_item, ""
            errors.append(f"{candidate}: {error or '无可用号码'}")
            if candidate == provider_mode:
                logger.warning(
                    "[Codex] add-phone 当前配置服务商取号失败，将尝试备用服务商: provider=%s email=%s error=%s",
                    candidate,
                    email,
                    error or "无可用号码",
                )
        return None, "; ".join(errors)

    def release_phone_item(phone_item: dict, reason: str = "") -> None:
        source = str(phone_item.get("source") or "").lower()
        if source == "hero_sms":
            _release_oauth_hero_sms_phone(phone_item, email=email, reason=reason)
            return
        if source == "smsbower":
            _release_oauth_sms_activation_phone(phone_item, email=email, reason=reason)
            return
        if source == "oasis":
            from autotoken.auth.oasis_sms import record_oasis_account_mapping

            record_oasis_account_mapping(phone_item, email=email, status="failed", reason=reason)
            return
        pool_api["release"](str(phone_item.get("id") or ""), email)

    def mark_phone_success(phone_item: dict) -> None:
        source = str(phone_item.get("source") or "").lower()
        if source == "hero_sms":
            _mark_oauth_hero_sms_bound(phone_item, email=email)
            return
        if source == "smsbower":
            _mark_oauth_smsbower_bound(phone_item, email=email)
            return
        if source == "oasis":
            from autotoken.auth.oasis_sms import record_oasis_account_mapping

            record_oasis_account_mapping(phone_item, email=email, status="success")
            return
        pool_api["bound"](str(phone_item.get("id") or ""), email)

    def mark_phone_failed(phone_item: dict, action: str, reason: str) -> None:
        source = str(phone_item.get("source") or "").lower()
        if source == "hero_sms":
            if action == "hero_release":
                _release_oauth_hero_sms_phone(phone_item, email=email, cancel=True, reason=reason)
                return
            if action in {"cooldown", "invalid"}:
                _release_oauth_hero_sms_phone(phone_item, email=email, cancel=True, reason=reason)
            else:
                _release_oauth_hero_sms_phone(phone_item, email=email, reason=reason)
            return
        if source == "smsbower":
            if action in {"cooldown", "invalid", "hero_release"}:
                _release_oauth_sms_activation_phone(phone_item, email=email, cancel=True, reason=reason)
            else:
                _release_oauth_sms_activation_phone(phone_item, email=email, reason=reason)
            return
        if source == "oasis":
            from autotoken.auth.oasis_sms import record_oasis_account_mapping

            record_oasis_account_mapping(phone_item, email=email, status="failed", reason=reason)
            return
        if action == "cooldown":
            pool_api["cooldown"](str(phone_item.get("id") or ""), reason)
        elif action == "invalid":
            pool_api["invalid"](str(phone_item.get("id") or ""), reason)
        else:
            pool_api["release"](str(phone_item.get("id") or ""), email)

    attempted = 0
    last_error = ""
    while attempted < 10 and _is_add_phone_page(page):
        phone_item, acquire_error = acquire_phone_item()
        if not phone_item:
            logger.warning(
                "[Codex] add-phone 需要手机号，但所有可用来源取号失败: email=%s providers=%s error=%s",
                email,
                ",".join(provider_order),
                acquire_error,
            )
            return False
        attempted += 1
        try:
            ok, error = _submit_oauth_add_phone_candidate(page, email=email, phone_item=phone_item)
        except CodexOAuthPhoneRateLimited as exc:
            rate_limit_detail = str(getattr(exc, "detail", "") or exc)
            rate_limit_action = _classify_oauth_phone_rate_limit_exception(rate_limit_detail)
            if rate_limit_action in {"cooldown", "invalid", "hero_release"}:
                mark_phone_failed(phone_item, rate_limit_action, rate_limit_detail)
                logger.warning(
                    "[Codex] add-phone 手机号请求受限，已处理号码并切换下一个: action=%s email=%s phone=%s reason=%s",
                    rate_limit_action,
                    email,
                    phone_item.get("phone_number"),
                    rate_limit_detail,
                )
                last_error = rate_limit_detail
                continue
            release_phone_item(phone_item, "account_phone_rate_limited")
            logger.warning(
                "[Codex] add-phone 当前账号手机验证请求次数过多，已释放手机号并跳过账号: email=%s phone=%s",
                email,
                phone_item.get("phone_number"),
            )
            raise
        except Exception as exc:
            release_phone_item(phone_item, str(exc))
            logger.warning(
                "[Codex] add-phone 手机号尝试异常，已释放占用: email=%s phone=%s error=%s",
                email,
                phone_item.get("phone_number"),
                exc,
            )
            return False
        if ok:
            mark_phone_success(phone_item)
            logger.info("[Codex] add-phone 手机号绑定成功: email=%s phone=%s", email, phone_item.get("phone_number"))
            return True
        last_error = error or "手机号绑定失败"
        failure_action = _classify_oauth_phone_failure(last_error)
        mark_phone_failed(phone_item, failure_action, last_error)
        action_text = ""
        if failure_action == "cooldown":
            action_text = "，已标记冷却 2 小时并切换下一个"
        elif failure_action == "invalid":
            action_text = "，已标记失效并切换下一个"
        elif failure_action == "hero_release":
            action_text = "，2 分钟未收到首个验证码，已释放该 hero-sms 号码并切换下一个"
        logger.warning(
            "[Codex] add-phone 手机号尝试失败%s: email=%s phone=%s reason=%s",
            action_text,
            email,
            phone_item.get("phone_number"),
            last_error,
        )
        if not failure_action:
            return False
        try:
            page.reload(wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)
        except Exception:
            pass
    logger.warning("[Codex] add-phone 手机号池尝试耗尽: email=%s last_error=%s", email, last_error)
    return False


def _fill_otp_input_and_verify(otp_input, otp: str) -> bool:
    otp = str(otp or "").strip()
    if not otp:
        return False

    def _page_level_fill() -> bool:
        try:
            return bool(
                otp_input.evaluate(
                    """(el, code) => {
                      const doc = el && el.ownerDocument;
                      if (!doc) return false;
                      const visible = (node) => {
                        if (!node || node.disabled || node.readOnly) return false;
                        const style = doc.defaultView.getComputedStyle(node);
                        const rect = node.getBoundingClientRect();
                        return style && style.visibility !== 'hidden' && style.display !== 'none'
                          && rect.width > 0 && rect.height > 0;
                      };
                      const setValue = (node, value) => {
                        node.focus();
                        const proto = Object.getPrototypeOf(node);
                        const desc = Object.getOwnPropertyDescriptor(proto, 'value');
                        if (desc && desc.set) desc.set.call(node, value);
                        else node.value = value;
                        node.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: value }));
                        node.dispatchEvent(new Event('change', { bubbles: true }));
                        node.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: value.slice(-1) || '' }));
                      };
                      const inputs = Array.from(doc.querySelectorAll('input')).filter((node) => {
                        const type = String(node.getAttribute('type') || '').toLowerCase();
                        const name = String(node.getAttribute('name') || '').toLowerCase();
                        const autocomplete = String(node.getAttribute('autocomplete') || '').toLowerCase();
                        if (!visible(node)) return false;
                        if (type === 'hidden' || type === 'email' || type === 'password') return false;
                        if (name === 'email' || autocomplete === 'email' || autocomplete === 'username') return false;
                        return true;
                      });
                      const oneChar = inputs.filter((node) => Number(node.maxLength || 0) === 1);
                      if (oneChar.length >= code.length && code.length > 1) {
                        for (let i = 0; i < code.length; i++) setValue(oneChar[i], code[i]);
                        return oneChar.slice(0, code.length).map((node) => String(node.value || '')).join('') === code;
                      }
                      setValue(el, code);
                      return String(el.value || '').trim() === code;
                    }""",
                    otp,
                )
            )
        except Exception:
            return False

    if _page_level_fill():
        time.sleep(0.5)
        return True

    try:
        otp_input.fill(otp)
    except Exception:
        pass
    time.sleep(0.5)
    try:
        current = str(otp_input.input_value(timeout=1000) or "").strip()
    except Exception:
        current = ""
    if current == otp:
        return True
    if current:
        logger.warning("[Codex] 验证码输入不完整: expected_len=%s actual_len=%s", len(otp), len(current))
    return False


def _poll_login_otp(
    *,
    email: str,
    mail_client,
    search_login_emails,
    latest_email_id: int,
    used_email_ids: set[int],
    window_started_at: float,
    timeout: int | None = None,
    require_openai_sender: bool = False,
):
    timeout = LOGIN_OTP_TIMEOUT_SECONDS if timeout is None else max(5, int(timeout))
    start = time.time()
    last_error = ""
    while time.time() - start < timeout:
        try:
            emails = search_login_emails(size=10)
        except Exception as exc:
            last_error = str(exc)
            logger.warning("[Codex] 查询 %s 验证码失败: %s", email, exc)
            emails = []
        for em in emails:
            code = mail_client.extract_verification_code(em)
            if code:
                logger.info(
                    "[Codex] 首轮/轮询已从邮件提取验证码: email=%s emailId=%s subject=%s",
                    email,
                    em.get("emailId") or "",
                    _compact_log_text(em.get("subject") or "", limit=80),
                )
                return str(code), int(em.get("emailId") or 0)
        if emails:
            logger.info(
                "[Codex] 查询到 %d 封邮件但未提取到验证码: email=%s subjects=%s",
                len(emails),
                email,
                [_compact_log_text(str(item.get("subject") or ""), limit=60) for item in emails[:3]],
            )
        time.sleep(3)
    detail = f"，最后一次查询错误: {last_error}" if last_error else ""
    raise CodexOAuthLoginRequired(f"等待邮箱验证码超时({timeout}s): {email}{detail}")


def _merge_mail_records(*groups: list[dict]) -> list[dict]:
    merged = []
    seen = set()
    for group in groups:
        for item in group or []:
            key = (
                str(item.get("accountId") or ""),
                str(item.get("emailId") or item.get("messageId") or id(item)),
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


def _click_resend_login_otp(page) -> bool:
    selectors = (
        'button:has-text("重新发送电子邮件")',
        'button:has-text("重新发送邮件")',
        'button:has-text("重新发送验证码")',
        'button:has-text("Resend email")',
        'button:has-text("Resend code")',
        'button:has-text("Send again")',
        'a:has-text("重新发送电子邮件")',
        'a:has-text("重新发送邮件")',
        'a:has-text("重新发送验证码")',
        'a:has-text("Resend email")',
        'a:has-text("Resend code")',
        'a:has-text("Send again")',
    )
    for selector in selectors:
        try:
            control = page.locator(selector).first
            if control.is_visible(timeout=1000):
                control.click()
                return True
        except Exception:
            continue
    return False


def _poll_login_otp_then_resend_once(
    *,
    page,
    email: str,
    mail_client,
    search_login_emails,
    latest_email_id: int,
    used_email_ids: set[int],
    window_started_at: float,
    require_openai_sender: bool = False,
):
    try:
        return _poll_login_otp(
            email=email,
            mail_client=mail_client,
            search_login_emails=search_login_emails,
            latest_email_id=latest_email_id,
            used_email_ids=used_email_ids,
            window_started_at=window_started_at,
            require_openai_sender=require_openai_sender,
        )
    except CodexOAuthLoginRequired as first_error:
        if not _is_otp_input_visible(page, timeout=300):
            raise
        if not _click_resend_login_otp(page):
            raise first_error
        resend_started_at = time.time()
        logger.info("[Codex] 首轮未收到验证码，已点击重新发送，继续等待: %s", email)
        time.sleep(2)
        return _poll_login_otp(
            email=email,
            mail_client=mail_client,
            search_login_emails=search_login_emails,
            latest_email_id=latest_email_id,
            used_email_ids=used_email_ids,
            window_started_at=resend_started_at,
            require_openai_sender=require_openai_sender,
        )


def _click_email_code_login_if_present(page) -> bool:
    try:
        control = page.locator(_EMAIL_CODE_LOGIN_SELECTOR).first
        if control.is_visible(timeout=500):
            control.click()
            return True
    except Exception:
        pass
    try:
        clicked = page.evaluate(
            """(labels) => {
              const visible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style && style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
              };
              const norm = (text) => String(text || '').replace(/\\s+/g, ' ').trim().toLowerCase();
              const skip = /重新发送|重發|resend|send again/i;
              const zhCode = /验证码|驗證碼|验证代码|驗證代碼/;
              const zhAction = /登录|登陆|登入|使用|改用|切换|切換|通过|透过|繼續|继续/;
              const enCode = /(email\\s*)?(code|one[-\\s]?time|otp)/i;
              const enAction = /(log\\s*in|login|sign\\s*in|continue|use|try|switch)/i;
              const targets = Array.from(document.querySelectorAll('button, a, [role="button"], [tabindex]'));
              for (const el of targets) {
                if (!visible(el) || el.disabled || el.getAttribute('aria-disabled') === 'true') continue;
                const text = norm(el.innerText || el.textContent || el.value || el.getAttribute('aria-label') || '');
                if (!text || skip.test(text)) continue;
                if (labels.some((label) => text.includes(norm(label)))) {
                  el.click();
                  return text;
                }
                if ((zhCode.test(text) && zhAction.test(text)) || (enCode.test(text) && enAction.test(text))) {
                  el.click();
                  return text;
                }
              }
              return '';
            }""",
            list(_EMAIL_CODE_LOGIN_TEXTS),
        )
        return bool(clicked)
    except Exception:
        pass
    return False


def _simple_fill_about_you_if_present(page) -> bool:
    if "about-you" not in (page.url or ""):
        return False
    try:
        name_input = page.locator('input[name="name"]').first
        if name_input.is_visible(timeout=1000):
            name_input.fill("User")
        age_input = page.locator('input[name="age"], input[placeholder*="年龄"]').first
        try:
            if age_input.is_visible(timeout=1000):
                age_input.fill("25")
        except Exception:
            pass
        page.locator(
            'button:has-text("继续"), button:has-text("Continue"), button:has-text("完成帐户创建"), button[type="submit"]'
        ).first.click()
        time.sleep(3)
        return True
    except Exception:
        return False


def _login_codex_via_browser_simple(
    email,
    password,
    mail_client=None,
    *,
    use_personal=False,
    native_oauth=False,
    headless=False,
    mail_account_id=None,
    auth_session_callback=None,
    proxy_url: str | None = None,
    proxy_bypass: str | None = None,
    phone_sms_provider: str | None = None,
    phone_sms_country: str | None = None,
    phone_sms_oasis_cdks: str | None = None,
):
    """
    极简 OAuth 登录：输入邮箱 -> 邮箱验证码 -> 授权。

    这条路径用于 personal/native OAuth 补登录，刻意不复用 Team workspace 预登录逻辑。
    邮件验证码查询与账号注册保持一致：查最近邮件，能提取到验证码就填。
    """
    code_verifier, code_challenge = _generate_pkce()
    state = secrets.token_urlsafe(16)
    auth_url = _build_auth_url(code_challenge, state, native_oauth=True)
    auth_code = None
    phone_required_url = ""
    final_oauth_url = ""
    password_required_detail = ""

    def search_login_emails(size=10):
        if not mail_client:
            return []
        by_account = []
        try:
            if mail_account_id is not None:
                by_account = mail_client.search_emails_by_recipient(email, size=size, account_id=mail_account_id)
        except TypeError:
            by_account = []
        except Exception as exc:
            logger.warning(
                "[Codex] 极简 OAuth 按 accountId 查询验证码失败，将按邮箱兜底: email=%s accountId=%s error=%s",
                email,
                mail_account_id,
                exc,
            )
            by_account = []
        try:
            by_email = mail_client.search_emails_by_recipient(email, size=size)
        except Exception as exc:
            logger.warning("[Codex] 极简 OAuth 按邮箱查询验证码失败: email=%s error=%s", email, exc)
            by_email = []
        merged = _merge_mail_records(by_account, by_email)
        logger.info(
            "[Codex] 极简 OAuth 邮件查询: email=%s accountId=%s direct=%d by_email=%d merged=%d",
            email,
            mail_account_id if mail_account_id is not None else "",
            len(by_account),
            len(by_email),
            len(merged),
        )
        return merged

    logger.info("[Codex] 开始极简 OAuth 登录: %s", email)
    with sync_playwright() as p:
        browser, context = _launch_codex_oauth_chromium(
            p,
            headless=headless,
            proxy_url=proxy_url,
            proxy_bypass=proxy_bypass,
        )

        def on_request(request):
            nonlocal auth_code
            url = request.url
            if f"localhost:{CODEX_CALLBACK_PORT}/auth/callback" in url:
                parsed = urllib.parse.urlparse(url)
                qs = urllib.parse.parse_qs(parsed.query)
                auth_code = qs.get("code", [None])[0]
                if auth_code:
                    logger.info("[Codex] 极简 OAuth 捕获到 auth code")

        def on_response(response):
            nonlocal auth_code
            url = response.url
            if f"localhost:{CODEX_CALLBACK_PORT}/auth/callback" in url and not auth_code:
                parsed = urllib.parse.urlparse(url)
                qs = urllib.parse.parse_qs(parsed.query)
                auth_code = qs.get("code", [None])[0]
                if auth_code:
                    logger.info("[Codex] 极简 OAuth 从 response 捕获到 auth code")

        page = context.new_page()
        page.on("request", on_request)
        page.on("response", on_response)
        logger.info("[Codex] 极简 OAuth 打开授权页: %s", email)
        page.goto(auth_url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(2)
        logger.info("[Codex] 极简 OAuth 授权页已加载: email=%s url=%s", email, page.url)
        _screenshot(page, "codex_simple_01_auth_page.png")

        used_email_ids: set[int] = set()
        login_started_at = time.time()
        password_submitted = False
        password_submitted_at = 0.0
        for step in range(30):
            if auth_code:
                break

            current_url = page.url or ""
            if "auth.openai.com/add-phone" in current_url:
                if _handle_oauth_add_phone_if_present(
                    page,
                    email=email,
                    phone_sms_provider=phone_sms_provider,
                    phone_sms_country=phone_sms_country,
                    phone_sms_oasis_cdks=phone_sms_oasis_cdks,
                ):
                    time.sleep(2)
                    continue
                phone_required_url = current_url
                break
            deactivated_detail = _detect_account_deactivated(page)
            if deactivated_detail:
                _close_codex_oauth_chromium(browser, context)
                raise CodexOAuthAccountDeactivated(deactivated_detail)

            if _click_auth_retry_if_timed_out(page):
                logger.info("[Codex] 极简 OAuth 点击重试: %s", email)
                time.sleep(3)
                continue
            otp_input = _otp_input_locator(page)
            if otp_input and otp_input.is_visible(timeout=500):
                logger.info("[Codex] 极简 OAuth 检测到验证码输入框: %s", email)
                if not mail_client:
                    logger.warning("[Codex] 极简 OAuth 需要验证码但没有 mail_client")
                    break
                if LOGIN_OTP_INITIAL_DELAY_SECONDS:
                    logger.info(
                        "[Codex] 已进入验证码页，先等待 %ss 再查询邮箱: %s",
                        LOGIN_OTP_INITIAL_DELAY_SECONDS,
                        email,
                    )
                    time.sleep(LOGIN_OTP_INITIAL_DELAY_SECONDS)
                otp_code, otp_email_id = _poll_login_otp_then_resend_once(
                    page=page,
                    email=email,
                    mail_client=mail_client,
                    search_login_emails=search_login_emails,
                    latest_email_id=0,
                    used_email_ids=used_email_ids,
                    window_started_at=login_started_at,
                )
                used_email_ids.add(otp_email_id)
                logger.info("[Codex] 极简 OAuth 获取到验证码: %s", otp_code)
                if not _fill_otp_input_and_verify(otp_input, otp_code):
                    raise CodexOAuthLoginRequired(f"验证码输入框仍为空，停止提交: {email}")
                page.locator(
                    'button[type="submit"], button:has-text("Continue"), button:has-text("继续")'
                ).first.click()
                time.sleep(3)
                _screenshot(page, "codex_simple_02_after_otp.png")
                continue
            try:
                pwd_input = page.locator(_PASSWORD_INPUT_SELECTORS).first
                password_visible = pwd_input.is_visible(timeout=500)
            except Exception:
                pwd_input = None
                password_visible = False
            if password_visible:
                if _click_email_code_login_if_present(page):
                    logger.info("[Codex] 极简 OAuth 检测到密码页，已切换邮箱验证码登录: %s", email)
                    time.sleep(2)
                    continue
                if password:
                    if password_submitted:
                        if time.time() - password_submitted_at < 15:
                            time.sleep(1)
                            continue
                        password_required_detail = f"OAuth 密码提交后仍停留在密码页: {email}"
                        final_oauth_url = page.url or ""
                        break
                    logger.info("[Codex] 极简 OAuth 检测到密码页，按注册流程填写密码: %s", email)
                    if not _fill_text_field_like_user(page, pwd_input, password):
                        password_required_detail = f"OAuth 密码输入框填写失败: {email}"
                        final_oauth_url = page.url or ""
                        break
                    time.sleep(0.5)
                    _click_primary_auth_button(page, pwd_input, ["Continue", "继续", "Log in", "登录"])
                    password_submitted = True
                    password_submitted_at = time.time()
                    time.sleep(3)
                    _screenshot(page, "codex_simple_02_after_password.png")
                    continue
                if _click_primary_auth_button(page, pwd_input, ["Continue", "继续", "Log in", "登录"]):
                    logger.info("[Codex] 极简 OAuth 密码页未找到验证码入口，已提交继续按钮等待页面反馈: %s", email)
                    time.sleep(3)
                    continue
                password_required_detail = f"OAuth 需要密码但账号没有保存密码，且未找到邮箱验证码入口: {email}"
                final_oauth_url = page.url or ""
                break

            if _fill_auth_email_if_present(page, email, timeout=800):
                logger.info("[Codex] 极简 OAuth 已提交邮箱: %s", email)
                time.sleep(2)
                continue
            if _click_email_code_login_if_present(page):
                logger.info("[Codex] 极简 OAuth 已切换邮箱验证码登录: %s", email)
                time.sleep(2)
                continue

            if _simple_fill_about_you_if_present(page):
                _screenshot(page, "codex_simple_03_after_about_you.png")
                continue

            if _handle_oauth_add_phone_if_present(
                page,
                email=email,
                phone_sms_provider=phone_sms_provider,
                phone_sms_country=phone_sms_country,
                phone_sms_oasis_cdks=phone_sms_oasis_cdks,
            ):
                _screenshot(page, "codex_simple_03b_after_add_phone.png")
                time.sleep(2)
                continue

            if _click_oauth_consent_if_present(page, timeout=1000):
                logger.info("[Codex] 极简 OAuth 点击授权/继续按钮: %s", email)
                time.sleep(3)
                _screenshot(page, f"codex_simple_04_consent_{step + 1}.png")
                continue

            time.sleep(1)

        if not phone_required_url:
            for _ in range(30):
                if auth_code:
                    break
                try:
                    cur = page.url
                    if f"localhost:{CODEX_CALLBACK_PORT}/auth/callback" in cur:
                        parsed = urllib.parse.urlparse(cur)
                        qs = urllib.parse.parse_qs(parsed.query)
                        auth_code = qs.get("code", [None])[0]
                        if auth_code:
                            break
                except Exception:
                    pass
                time.sleep(1)

        if not auth_code:
            _screenshot(page, "codex_simple_05_no_callback.png")
            final_oauth_url = page.url or ""

        if auth_code and callable(auth_session_callback):
            try:
                auth_session_callback(page, context)
            except Exception:
                logger.warning("[Codex] 极简 OAuth 刷新 auth_session 回调失败: %s", email, exc_info=True)

        _close_codex_oauth_chromium(browser, context)

    if phone_required_url:
        raise CodexOAuthPhoneRequired(phone_required_url)
    if password_required_detail:
        raise CodexOAuthLoginRequired(password_required_detail)
    if not auth_code:
        raise CodexOAuthLoginRequired(final_oauth_url or auth_url)

    bundle = _exchange_auth_code(auth_code, code_verifier, fallback_email=email)
    if not bundle:
        return None

    if use_personal:
        plan = (bundle.get("plan_type") or "").lower()
        if not _is_personal_codex_plan(plan):
            logger.error("[Codex] personal 极简 OAuth 拒收非个人 plan_type=%s", plan or "unknown")
            return None
    return bundle


def login_codex_via_browser(
    email,
    password,
    mail_client=None,
    *,
    use_personal=False,
    native_oauth=False,
    headless=False,
    mail_account_id=None,
    auth_session_callback=None,
    proxy_url: str | None = None,
    proxy_bypass: str | None = None,
    phone_sms_provider: str | None = None,
    phone_sms_country: str | None = None,
    phone_sms_oasis_cdks: str | None = None,
):
    """
    通过 Playwright 自动完成 Codex OAuth 登录。
    mail_client: 临时邮箱客户端实例，用于自动读取登录验证码。
    mail_account_id: cloud-mail accountId；有值时按 accountId 直查邮件，避免按邮箱扫全量账号。
    use_personal: 若为 True，则走"个人账号"流程 —— 不注入 Team _account cookie，
                  workspace 选择时跳过 Team 直接用 Personal。用于已退出 Team 的子账号生成 free plan 的 rt/at。
    native_oauth: 若为 True，则走 CLIProxyAPI 风格原生 Codex OAuth，不预登录 ChatGPT、
                  不注入 Team _account cookie，适用于 Plus/Pro/Free 个人账号补登录。
    返回 auth bundle: {access_token, refresh_token, id_token, account_id, email, plan_type}
    """
    if use_personal or native_oauth:
        return _login_codex_via_browser_simple(
            email,
            password,
            mail_client,
            use_personal=use_personal,
            native_oauth=native_oauth,
            headless=headless,
            mail_account_id=mail_account_id,
            auth_session_callback=auth_session_callback,
            proxy_url=proxy_url,
            proxy_bypass=proxy_bypass,
            phone_sms_provider=phone_sms_provider,
            phone_sms_country=phone_sms_country,
            phone_sms_oasis_cdks=phone_sms_oasis_cdks,
        )

    code_verifier, code_challenge = _generate_pkce()
    state = secrets.token_urlsafe(16)
    _used_email_ids: set[int] = set()  # 记录已尝试过的邮件，避免重复提交同一封验证码邮件

    def search_login_emails(size=5):
        if not mail_client:
            return []
        try:
            return mail_client.search_emails_by_recipient(email, size=size, account_id=mail_account_id)
        except TypeError:
            return mail_client.search_emails_by_recipient(email, size=size)

    team_mode = not use_personal and not native_oauth
    # personal/native 模式下不引导到 Team workspace
    chatgpt_account_id = get_chatgpt_account_id() if team_mode else ""

    auth_url = _build_auth_url(code_challenge, state, native_oauth=(use_personal or native_oauth))

    logger.info("[Codex] 开始 OAuth 登录: %s", email)
    login_started_at = time.time()

    auth_code = None
    phone_required_url = ""
    final_oauth_url = ""

    with sync_playwright() as p:
        browser, context = _launch_codex_oauth_chromium(
            p,
            headless=headless,
            proxy_url=proxy_url,
            proxy_bypass=proxy_bypass,
        )

        # === Step 0: 先登录 ChatGPT 并切换到 Team workspace ===
        # 仅 Team 模式需要:登录前注入 _account cookie 引导登录进入 Team workspace。
        # personal 模式 chatgpt_account_id="" 无 cookie 可注入,step-0 反而会留下半成品
        # session(新账号 ChatGPT 登录 12s 内通常走不完) → auth_url 在同 context 下会看到
        # "欢迎回来"页,邮箱灰禁、consent 循环误点 Continue → OpenAI 返回 Operation timed out。
        # 所以 personal 模式直接跳过 step-0,auth_url 在干净 context 里自己走邮箱/密码/OTP。

        # 在登录开始前记录当前最新邮件 ID,后续只接受比这个更新的
        _email_id_before_login = 0
        if mail_client:
            try:
                _pre = search_login_emails(size=1)
                if _pre:
                    _email_id_before_login = _pre[0].get("emailId", 0)
            except Exception:
                pass

        if use_personal:
            logger.info("[Codex] personal 模式: 跳过 step-0 ChatGPT 预登录,直接走 auth_url")
        elif native_oauth:
            logger.info("[Codex] native 模式: 跳过 step-0 ChatGPT 预登录,不注入 Team _account,直接走 auth_url")
        else:
            if chatgpt_account_id:
                context.add_cookies(
                    [
                        {
                            "name": "_account",
                            "value": chatgpt_account_id,
                            "domain": "chatgpt.com",
                            "path": "/",
                            "secure": True,
                            "sameSite": "Lax",
                        },
                        {
                            "name": "_account",
                            "value": chatgpt_account_id,
                            "domain": "auth.openai.com",
                            "path": "/",
                            "secure": True,
                            "sameSite": "Lax",
                        },
                    ]
                )
                logger.debug("[Codex] 登录前已注入 _account cookie = %s", chatgpt_account_id)

            logger.info("[Codex] 先登录 ChatGPT 选择 Team workspace...")
            _page = context.new_page()
            _page.goto("https://chatgpt.com/auth/login", wait_until="domcontentloaded", timeout=60000)
            time.sleep(5)

            # Cloudflare
            for _i in range(12):
                if "verify you are human" not in _page.content()[:2000].lower():
                    break
                time.sleep(5)

            # 点击登录
            try:
                _page.locator('button:has-text("登录"), button:has-text("Log in")').first.click()
                time.sleep(3)
            except Exception:
                pass

            # 输入邮箱（避免误点 Google/Microsoft 第三方登录按钮）
            try:
                ei = _page.locator(_EMAIL_INPUT_SELECTORS).first
                if ei.is_visible(timeout=5000):
                    ei.fill(email)
                    time.sleep(0.5)
                    _click_primary_auth_button(_page, ei, ["Continue", "继续"])
                    time.sleep(3)
            except Exception:
                pass

            # 输入密码 / 点击一次性验证码登录
            try:
                pi = _page.locator(_PASSWORD_INPUT_SELECTORS).first
                if pi.is_visible(timeout=5000):
                    if _click_email_code_login_if_present(_page):
                        logger.info("[Codex] ChatGPT 登录密码页已切换邮箱验证码登录")
                    elif password:
                        pi.fill(password)
                        time.sleep(0.5)
                        _click_primary_auth_button(_page, pi, ["Continue", "继续", "Log in"])
                    else:
                        # 没有密码，点击"使用一次性验证码登录"
                        otp_btn = _page.locator(_EMAIL_CODE_LOGIN_SELECTOR).first
                        if otp_btn.is_visible(timeout=3000):
                            logger.info("[Codex] 无密码，点击一次性验证码登录")
                            otp_btn.click()
                        else:
                            # fallback: 提交空密码让页面报错，然后找验证码按钮
                            _click_primary_auth_button(_page, pi, ["Continue", "继续", "Log in"])
                    time.sleep(8)
            except Exception:
                pass

            # 可能需要邮箱验证码
            try:
                ci = _page.locator('input[name="code"]').first
                if ci.is_visible(timeout=5000) and mail_client:
                    logger.info("[Codex] ChatGPT 登录需要验证码，按注册流程查询最近验证码邮件...")
                    otp, otp_email_id = _poll_login_otp_then_resend_once(
                        page=_page,
                        email=email,
                        mail_client=mail_client,
                        search_login_emails=search_login_emails,
                        latest_email_id=int(_email_id_before_login or 0),
                        used_email_ids=_used_email_ids,
                        window_started_at=login_started_at,
                    )
                    if otp:
                        ci.fill(otp)
                        time.sleep(0.5)
                        _page.locator('button[type="submit"]').first.click()
                        time.sleep(5)
            except Exception:
                pass

            _screenshot(_page, "codex_00_chatgpt_login.png")
            logger.info("[Codex] ChatGPT 登录后 URL: %s", _page.url)

            # 如果是 workspace 选择页面，Team 模式选配置的 workspace
            if "workspace" in _page.url:
                workspace_name = get_chatgpt_workspace_name()
                logger.info("[Codex] 检测到 workspace 选择页面...")
                try:
                    ws_btn = _page.locator(f'text="{workspace_name}"').first
                    if workspace_name and ws_btn.is_visible(timeout=3000):
                        logger.info("[Codex] 选择 workspace: %s", workspace_name)
                        ws_btn.click()
                        time.sleep(5)
                    else:
                        # fallback: 选第二个选项（第一个通常是"个人"）
                        options = _page.locator('a, button, [role="button"]').all()
                        for opt in options:
                            try:
                                text = opt.inner_text(timeout=1000).strip()
                                if (
                                    text
                                    and "个人" not in text
                                    and "Personal" not in text
                                    and text not in ("ChatGPT", "")
                                ):
                                    logger.info("[Codex] 选择 workspace: %s", text)
                                    opt.click()
                                    time.sleep(5)
                                    break
                            except Exception:
                                continue
                except Exception:
                    pass
                _screenshot(_page, "codex_00_after_workspace.png")
                logger.info("[Codex] 选择 workspace 后 URL: %s", _page.url)

            # _account cookie 已在登录前注入

            # 关闭 ChatGPT 页面但保留 context
            _page.close()

        # 通过监听请求来捕获 OAuth callback redirect
        def on_request(request):
            nonlocal auth_code
            url = request.url
            if f"localhost:{CODEX_CALLBACK_PORT}/auth/callback" in url:
                parsed = urllib.parse.urlparse(url)
                qs = urllib.parse.parse_qs(parsed.query)
                auth_code = qs.get("code", [None])[0]
                if auth_code:
                    logger.info("[Codex] 捕获到 auth code!")

        # 也监听 response/framenavigated 来捕获 redirect URL
        def on_response(response):
            nonlocal auth_code
            url = response.url
            if f"localhost:{CODEX_CALLBACK_PORT}/auth/callback" in url and not auth_code:
                parsed = urllib.parse.urlparse(url)
                qs = urllib.parse.parse_qs(parsed.query)
                auth_code = qs.get("code", [None])[0]
                if auth_code:
                    logger.info("[Codex] 从 response 捕获到 auth code!")

        page = context.new_page()
        page.on("request", on_request)
        page.on("response", on_response)
        page.goto(auth_url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)
        _screenshot(page, "codex_01_auth_page.png")

        # 输入邮箱（注意避免点到 Google/Microsoft/Apple 第三方登录按钮）
        try:
            for attempt in range(2):
                if not _fill_auth_email_if_present(page, email, timeout=800):
                    break
                time.sleep(2)

                if not _is_google_redirect(page):
                    break

                _screenshot(page, f"codex_02_google_redirect_attempt{attempt + 1}.png")
                logger.warning("[Codex] 邮箱步骤误跳转到 Google 登录，返回重试... (attempt %d)", attempt + 1)
                page.go_back(wait_until="domcontentloaded", timeout=30000)
                time.sleep(2)
            _screenshot(page, "codex_02_after_email.png")
        except Exception:
            _screenshot(page, "codex_02_no_email.png")

        # 输入密码
        try:
            for attempt in range(2):
                pwd_input = page.locator(_PASSWORD_INPUT_SELECTORS).first
                if not pwd_input.is_visible(timeout=5000):
                    break

                pwd_input.fill(password)
                time.sleep(0.5)
                _click_primary_auth_button(page, pwd_input, ["Continue", "继续", "Log in"])
                time.sleep(5)

                if not _is_google_redirect(page):
                    break

                _screenshot(page, f"codex_03_google_redirect_attempt{attempt + 1}.png")
                logger.warning("[Codex] 密码步骤误跳转到 Google 登录，返回重试... (attempt %d)", attempt + 1)
                page.go_back(wait_until="domcontentloaded", timeout=30000)
                time.sleep(2)
            _screenshot(page, "codex_03_after_password.png")
        except Exception:
            _screenshot(page, "codex_03_no_password.png")

        # 可能需要邮箱登录验证码
        _screenshot(page, "codex_03b_check_otp.png")
        code_input = None
        try:
            code_input = page.locator(
                'input[name="code"], input[placeholder*="验证码"], input[placeholder*="code" i]'
            ).first
            if not code_input.is_visible(timeout=5000):
                code_input = None
        except Exception:
            code_input = None

        if code_input and mail_client:
            logger.info("[Codex] 需要登录验证码，按注册流程查询最近验证码邮件...")

            otp_code, otp_email_id = _poll_login_otp_then_resend_once(
                page=page,
                email=email,
                mail_client=mail_client,
                search_login_emails=search_login_emails,
                latest_email_id=int(_email_id_before_login or 0),
                used_email_ids=_used_email_ids,
                window_started_at=login_started_at,
                require_openai_sender=False,
            )
            _used_email_ids.add(otp_email_id)
            logger.info("[Codex] 获取到验证码: %s", otp_code)
            if not _fill_otp_input_and_verify(code_input, otp_code):
                raise CodexOAuthLoginRequired(f"验证码输入框仍为空，停止提交: {email}")
            page.locator('button:has-text("Continue"), button:has-text("继续"), button[type="submit"]').first.click()
            time.sleep(3)
            _screenshot(page, "codex_03c_after_otp.png")
        elif code_input:
            logger.warning("[Codex] 需要验证码但无 mail_client，无法自动获取")

        # 处理 about-you 页面（可能出现在 OAuth 流程中）
        if "about-you" in page.url:
            logger.info("[Codex] 检测到 about-you 页面，填写个人信息...")
            try:
                name_input = page.locator('input[name="name"]').first
                if name_input.is_visible(timeout=3000):
                    name_input.fill("User")

                # 自适应：生日日期（spinbutton）或年龄（普通 input）
                spinbuttons = page.locator('[role="spinbutton"]').all()
                if len(spinbuttons) >= 3:
                    # 类型 A：React Aria DateField
                    try:
                        page.locator("text=生日日期").click()
                        time.sleep(0.5)
                    except Exception:
                        pass
                    for sb, val in zip(spinbuttons[:3], ["1995", "06", "15"]):
                        sb.click(force=True)
                        time.sleep(0.2)
                        page.keyboard.type(val, delay=80)
                        time.sleep(0.3)
                    logger.info("[Codex] 填入生日: 1995/06/15 (spinbutton)")
                else:
                    # 类型 B：普通年龄数字输入框
                    age_input = page.locator('input[name="age"], input[placeholder*="年龄"]').first
                    try:
                        if age_input.is_visible(timeout=3000):
                            age_input.fill("25")
                            logger.info("[Codex] 填入年龄: 25")
                    except Exception:
                        logger.warning("[Codex] 未找到年龄/生日输入框")

                time.sleep(0.5)
                page.locator(
                    'button:has-text("继续"), button:has-text("Continue"), button:has-text("完成帐户创建"), button[type="submit"]'
                ).first.click()
                time.sleep(5)
                _screenshot(page, "codex_03d_after_aboutyou.png")
                logger.info("[Codex] about-you 完成，当前 URL: %s", page.url)
            except Exception as e:
                logger.error("[Codex] about-you 处理失败: %s", e)

        # 处理多个授权/同意页面（可能有多步）
        for step in range(10):
            if auth_code:
                break

            try:
                current_url = page.url or ""
                if "auth.openai.com/add-phone" in current_url:
                    if _handle_oauth_add_phone_if_present(
                        page,
                        email=email,
                        phone_sms_provider=phone_sms_provider,
                        phone_sms_country=phone_sms_country,
                        phone_sms_oasis_cdks=phone_sms_oasis_cdks,
                    ):
                        _screenshot(page, "codex_04_add_phone_handled.png")
                        time.sleep(2)
                        continue
                    _screenshot(page, "codex_04_add_phone_blocked.png")
                    logger.error("[Codex] OAuth 被 add-phone 阻断，当前 URL: %s", current_url)
                    phone_required_url = current_url
                    break
                deactivated_detail = _detect_account_deactivated(page)
                if deactivated_detail:
                    _screenshot(page, "codex_04_account_deactivated.png")
                    logger.error("[Codex] OAuth 检测到 account_deactivated: %s", deactivated_detail)
                    raise CodexOAuthAccountDeactivated(deactivated_detail)
            except CodexOAuthAccountDeactivated:
                raise
            except Exception:
                pass

            _screenshot(page, f"codex_04_step{step + 1}_before.png")

            if _click_auth_retry_if_timed_out(page):
                logger.warning("[Codex] OAuth 遇到 Operation timed out，已点击重试 (step %d)", step + 1)
                time.sleep(5)
                continue

            if _is_auth_login_page(page):
                logger.info("[Codex] OAuth 仍在登录页，尝试继续登录 (step %d): %s", step + 1, page.url)
                if _fill_auth_email_if_present(page, email, timeout=500):
                    time.sleep(2)
                    continue
                if _fill_auth_password_if_present(page, password, timeout=2000):
                    time.sleep(5)
                    continue

            # 在任何页面中，如果有 workspace/组织选择，Team 模式选 Team；personal/native 模式优先 Personal。
            try:
                page_text = page.inner_text("body")[:1000]

                prefer_personal_workspace = use_personal or native_oauth
                if prefer_personal_workspace and (
                    "选择一个工作空间" in page_text or "Select a workspace" in page_text or "选择工作空间" in page_text
                ):
                    _screenshot(page, f"codex_04_personal_ws_{step + 1}_before.png")
                    logger.info("[Codex] 检测到工作空间选择页 (step %d, 非 Team 模式)", step + 1)
                    personal_selected = False
                    try:
                        personal_btn = page.locator("text=/个人|Personal/").first
                        if personal_btn.is_visible(timeout=2000):
                            personal_btn.click(force=True)
                            time.sleep(1)
                            personal_selected = True
                            logger.info("[Codex] 已选择 Personal workspace (step %d)", step + 1)
                    except Exception as e:
                        logger.warning("[Codex] 选择 Personal 失败: %s", e)
                    _screenshot(page, f"codex_04_personal_ws_{step + 1}_after.png")
                    if personal_selected:
                        try:
                            cont_btn = page.locator('button:has-text("继续"), button:has-text("Continue")').first
                            if cont_btn.is_visible(timeout=3000):
                                cont_btn.click()
                                time.sleep(3)
                        except Exception:
                            pass
                        continue

                # 选择 Team workspace（用配置的名称精确匹配）
                workspace_name = get_chatgpt_workspace_name() if team_mode else ""
                # 检测"选择一个工作空间"页面，点击 Team workspace
                if workspace_name and (
                    "选择一个工作空间" in page_text or "Select a workspace" in page_text or "选择工作空间" in page_text
                ):
                    selected = False
                    _screenshot(page, f"codex_04_workspace_{step + 1}_before.png")
                    logger.info("[Codex] 检测到工作空间选择页 (step %d)，尝试选择: %s", step + 1, workspace_name)

                    # 用 JS 直接点击包含 workspace 名称的元素（最可靠）
                    try:
                        clicked = page.evaluate(
                            """(name) => {
                            const els = document.querySelectorAll('*');
                            for (const el of els) {
                                const text = (el.textContent || '').trim();
                                if (text === name && !text.includes('个人') && !text.includes('Personal')) {
                                    // 找到最近的可点击父元素
                                    let target = el;
                                    while (target && target.tagName !== 'BODY') {
                                        const tag = target.tagName.toLowerCase();
                                        if (['button', 'a', 'li', 'label'].includes(tag)
                                            || target.getAttribute('role')
                                            || target.onclick
                                            || target.classList.length > 0) {
                                            target.click();
                                            return true;
                                        }
                                        target = target.parentElement;
                                    }
                                    el.click();
                                    return true;
                                }
                            }
                            return false;
                        }""",
                            workspace_name,
                        )
                        if clicked:
                            time.sleep(1)
                            selected = True
                            logger.info("[Codex] 已选择 workspace (JS): %s (step %d)", workspace_name, step + 1)
                    except Exception as e:
                        logger.warning("[Codex] JS 选择 workspace 失败: %s", e)

                    if not selected:
                        # fallback: Playwright 选择器
                        try:
                            ws_el = page.locator(f"text={workspace_name}").first
                            if ws_el.is_visible(timeout=2000):
                                ws_el.click(force=True)
                                time.sleep(1)
                                selected = True
                                logger.info(
                                    "[Codex] 已选择 workspace (force click): %s (step %d)", workspace_name, step + 1
                                )
                        except Exception:
                            pass

                    _screenshot(page, f"codex_04_workspace_{step + 1}_after.png")
                    if selected:
                        # 选完 workspace 后点"继续"按钮提交
                        try:
                            cont_btn = page.locator('button:has-text("继续"), button:has-text("Continue")').first
                            if cont_btn.is_visible(timeout=3000):
                                cont_btn.click()
                                time.sleep(3)
                                logger.info("[Codex] 已点击继续 (step %d)", step + 1)
                        except Exception:
                            pass
                        continue
                    else:
                        logger.warning("[Codex] 无法选择 workspace '%s' (step %d)", workspace_name, step + 1)

                elif workspace_name:
                    # 非工作空间选择页，但可能有 workspace 文本（如 organization 页）
                    try:
                        ws_btn = page.locator(f'text="{workspace_name}"').first
                        if ws_btn.is_visible(timeout=1000):
                            ws_btn.click()
                            time.sleep(1)
                            logger.info("[Codex] 已选择 workspace: %s (step %d)", workspace_name, step + 1)
                    except Exception:
                        pass

                # Organization 页面的下拉选择
                if "organization" in page.url:
                    dropdown = page.locator("[aria-expanded], [aria-haspopup]").first
                    if dropdown.is_visible(timeout=2000):
                        dropdown.click()
                        time.sleep(1)
                        options = page.locator('[role="option"]').all()
                        for opt in options:
                            text = opt.inner_text(timeout=1000).strip()
                            if text and "新组织" not in text and "New" not in text:
                                opt.click()
                                logger.info("[Codex] 选择已有组织: %s", text)
                                break
                        else:
                            if options:
                                options[0].click()
                        time.sleep(1)
            except Exception:
                pass

            # 处理密码页面（可能在 consent 流程中出现）
            try:
                pwd_field = page.locator(_PASSWORD_INPUT_SELECTORS).first
                if pwd_field.is_visible(timeout=2000):
                    if _click_email_code_login_if_present(page):
                        logger.info("[Codex] 密码页已切换邮箱验证码登录 (step %d)", step + 1)
                    elif password:
                        logger.info("[Codex] 需要重新输入密码 (step %d)...", step + 1)
                        pwd_field.fill(password)
                        time.sleep(0.5)
                        _click_primary_auth_button(page, pwd_field, ["Continue", "继续", "Log in"])
                    else:
                        # 没密码，点"使用一次性验证码登录"
                        otp_btn = page.locator(_EMAIL_CODE_LOGIN_SELECTOR).first
                        if otp_btn.is_visible(timeout=3000):
                            logger.info("[Codex] 无密码，点击一次性验证码登录 (step %d)", step + 1)
                            otp_btn.click()
                        else:
                            _click_primary_auth_button(page, pwd_field, ["Continue", "继续", "Log in"])
                    time.sleep(5)
                    _screenshot(page, f"codex_04_password_{step + 1}.png")
                    continue
            except Exception:
                pass

            # 处理邮箱验证码页面（可能在 consent 流程中出现）
            try:
                otp_input = _otp_input_locator(page)
                if otp_input and otp_input.is_visible(timeout=500) and mail_client:
                    logger.info(
                        "[Codex] 需要邮箱验证码 (step %d)，按注册流程查询最近验证码邮件...",
                        step + 1,
                    )
                    otp = None
                    otp_email_id = 0
                    page_left_code = False
                    try:
                        otp, otp_email_id = _poll_login_otp_then_resend_once(
                            page=page,
                            email=email,
                            mail_client=mail_client,
                            search_login_emails=search_login_emails,
                            latest_email_id=int(_email_id_before_login or 0),
                            used_email_ids=_used_email_ids,
                            window_started_at=login_started_at,
                            require_openai_sender=False,
                        )
                    except CodexOAuthLoginRequired:
                        if not _is_otp_input_visible(page, timeout=300):
                            page_left_code = True
                            logger.info("[Codex] 验证码页已退出，继续后续授权流程")
                        else:
                            raise
                    if otp:
                        submit_ok = False
                        for submit_attempt in range(1, 3):
                            otp_input = _otp_input_locator(page)
                            if not otp_input or not otp_input.is_visible(timeout=500):
                                submit_ok = True
                                break

                            if not _fill_otp_input_and_verify(otp_input, otp):
                                logger.warning("[Codex] 验证码输入框仍为空，跳过点击继续并等待重新填写")
                                time.sleep(2)
                                continue
                            page.locator(
                                'button[type="submit"], button:has-text("Continue"), button:has-text("继续")'
                            ).first.click()
                            logger.info("[Codex] 已输入验证码: %s", otp)

                            submit_status, submit_detail = _wait_for_otp_submit_result(page, timeout=12)
                            if submit_status == "accepted":
                                submit_ok = True
                                break
                            if submit_status == "invalid":
                                _used_email_ids.add(otp_email_id)
                                detail_suffix = f"，命中提示: {submit_detail}" if submit_detail else ""
                                logger.warning(
                                    "[Codex] 验证码邮件 %s（code=%s）被页面判定无效%s，标记并跳过该邮件",
                                    otp_email_id,
                                    otp,
                                    detail_suffix,
                                )
                                break

                            if submit_attempt < 2:
                                logger.warning(
                                    "[Codex] 验证码邮件 %s（code=%s）提交后未确认成功，准备重试第 %d/2 次",
                                    otp_email_id,
                                    otp,
                                    submit_attempt + 1,
                                )
                                time.sleep(2)
                            else:
                                _used_email_ids.add(otp_email_id)
                                logger.warning(
                                    "[Codex] 验证码邮件 %s（code=%s）提交后仍未确认成功，标记并跳过该邮件",
                                    otp_email_id,
                                    otp,
                                )

                        if submit_ok:
                            _used_email_ids.add(otp_email_id)
                        continue
                    if page_left_code:
                        continue
            except CodexOAuthLoginRequired:
                raise
            except Exception:
                pass

            if _click_oauth_consent_if_present(page, timeout=5000):
                logger.info("[Codex] 点击同意/继续按钮 (step %d)...", step + 1)
                time.sleep(5)
                _screenshot(page, f"codex_04_consent_{step + 1}.png")
            else:
                break

        # 等待 redirect callback 获取 auth code。add-phone 已经是确定失败，不继续空等。
        if not phone_required_url:
            for _ in range(30):
                if auth_code:
                    break
                # 也从当前 URL 尝试提取（CPA 可能接收了回调）
                try:
                    cur = page.url
                    if f"localhost:{CODEX_CALLBACK_PORT}/auth/callback" in cur:
                        parsed = urllib.parse.urlparse(cur)
                        qs = urllib.parse.parse_qs(parsed.query)
                        auth_code = qs.get("code", [None])[0]
                        if auth_code:
                            logger.info("[Codex] 从 URL 捕获到 auth code!")
                            break
                except Exception:
                    pass
                try:
                    if _click_auth_retry_if_timed_out(page):
                        logger.warning("[Codex] OAuth 等待回调时遇到 Operation timed out，已点击重试")
                        time.sleep(5)
                        continue
                except Exception:
                    pass
                time.sleep(1)

        if not auth_code:
            _screenshot(page, "codex_05_no_callback.png")
            final_oauth_url = page.url or ""
            if "auth.openai.com/add-phone" in (page.url or ""):
                if _handle_oauth_add_phone_if_present(
                    page,
                    email=email,
                    phone_sms_provider=phone_sms_provider,
                    phone_sms_country=phone_sms_country,
                    phone_sms_oasis_cdks=phone_sms_oasis_cdks,
                ):
                    logger.info("[Codex] OAuth add-phone 已处理，继续等待回调: %s", email)
                    for _ in range(30):
                        if auth_code:
                            break
                        try:
                            cur = page.url
                            if f"localhost:{CODEX_CALLBACK_PORT}/auth/callback" in cur:
                                parsed = urllib.parse.urlparse(cur)
                                qs = urllib.parse.parse_qs(parsed.query)
                                auth_code = qs.get("code", [None])[0]
                                if auth_code:
                                    break
                        except Exception:
                            pass
                        time.sleep(1)
                    final_oauth_url = page.url or final_oauth_url
                else:
                    logger.error("[Codex] OAuth 被 add-phone 阻断，未获取到 auth code，当前 URL: %s", page.url)
                    phone_required_url = page.url or phone_required_url
            elif _detect_account_deactivated(page):
                raise CodexOAuthAccountDeactivated(_detect_account_deactivated(page))
            elif _is_auth_login_page(page):
                logger.warning("[Codex] OAuth 停在登录页，未获取到 auth code，当前 URL: %s", page.url)
            else:
                logger.warning("[Codex] 未获取到 auth code，当前 URL: %s", page.url)

        _close_codex_oauth_chromium(browser, context)

    if phone_required_url:
        raise CodexOAuthPhoneRequired(phone_required_url)

    if not auth_code:
        lower_final_url = final_oauth_url.lower()
        if "auth.openai.com/log-in" in lower_final_url or "auth.openai.com/login" in lower_final_url:
            raise CodexOAuthLoginRequired(final_oauth_url)
        logger.error("[Codex] OAuth 登录失败: 未获取到 authorization code")
        return None

    bundle = _exchange_auth_code(auth_code, code_verifier, fallback_email=email)
    if not bundle:
        return None

    # Personal 模式强校验 plan_type:当子号还挂在 Team workspace(OpenAI 后端 kick 同步延迟 /
    # default workspace 为 Team)时,auth.openai.com 会默认选 Team 颁发 token,拿到 plan_type=team
    # 的 bundle —— 这个 token 绑在 Team account_id 上,一旦子号离开 Team 就作废(refresh 401)。
    # 但 GoPay 绑定成功后的个人账号会返回 plus/pro,这些仍是个人 Codex token,必须接受。
    if use_personal:
        plan = (bundle.get("plan_type") or "").lower()
        if not _is_personal_codex_plan(plan):
            logger.error(
                "[Codex] personal 模式拿到 plan_type=%s(期望 free/plus/pro),account_id=%s。"
                "说明账号仍在 Team workspace,OAuth 默认选了 Team → token 绑 Team 后会随踢出作废。"
                "拒收本次 bundle,触发上游 oauth_failed 分类。",
                plan or "unknown",
                bundle.get("account_id"),
            )
            return None

    return bundle


def login_codex_via_session():
    """使用主号 session 直接完成 Codex OAuth 登录。"""
    code_verifier, code_challenge = _generate_pkce()
    state = secrets.token_urlsafe(16)
    auth_url = _build_auth_url(code_challenge, state)

    from autotoken.integrations.chatgpt_api import ChatGPTTeamAPI

    logger.info("[Codex] 开始使用 session 登录主号 Codex...")
    auth_code = None
    chatgpt = ChatGPTTeamAPI()

    try:
        chatgpt.start()
        session_token = chatgpt.session_token
        if not session_token:
            logger.error("[Codex] 主号会话中未提取到 session token")
            return None
        cookies = []
        if len(session_token) > 3800:
            cookies.extend(
                [
                    {
                        "name": f"{chatgpt_session_service.CHATGPT_SESSION_COOKIE}.0",
                        "value": session_token[:3800],
                        "domain": "auth.openai.com",
                        "path": "/",
                        "httpOnly": True,
                        "secure": True,
                        "sameSite": "Lax",
                    },
                    {
                        "name": f"{chatgpt_session_service.CHATGPT_SESSION_COOKIE}.1",
                        "value": session_token[3800:],
                        "domain": "auth.openai.com",
                        "path": "/",
                        "httpOnly": True,
                        "secure": True,
                        "sameSite": "Lax",
                    },
                ]
            )
        else:
            cookies.append(
                {
                    "name": chatgpt_session_service.CHATGPT_SESSION_COOKIE,
                    "value": session_token,
                    "domain": "auth.openai.com",
                    "path": "/",
                    "httpOnly": True,
                    "secure": True,
                    "sameSite": "Lax",
                }
            )

        cookies.extend(
            [
                {
                    "name": "_account",
                    "value": chatgpt.account_id,
                    "domain": "auth.openai.com",
                    "path": "/",
                    "secure": True,
                    "sameSite": "Lax",
                },
                {
                    "name": "oai-did",
                    "value": chatgpt.oai_device_id,
                    "domain": "auth.openai.com",
                    "path": "/",
                    "secure": True,
                    "sameSite": "Lax",
                },
            ]
        )
        chatgpt.context.add_cookies(cookies)
        page = chatgpt.context.new_page()

        def on_request(request):
            nonlocal auth_code
            url = request.url
            if f"localhost:{CODEX_CALLBACK_PORT}/auth/callback" in url:
                parsed = urllib.parse.urlparse(url)
                qs = urllib.parse.parse_qs(parsed.query)
                auth_code = qs.get("code", [None])[0]

        def on_response(response):
            nonlocal auth_code
            url = response.url
            if f"localhost:{CODEX_CALLBACK_PORT}/auth/callback" in url and not auth_code:
                parsed = urllib.parse.urlparse(url)
                qs = urllib.parse.parse_qs(parsed.query)
                auth_code = qs.get("code", [None])[0]

        def open_oauth_page(tag):
            page.goto(auth_url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)
            _screenshot(page, f"codex_main_{tag}.png")

        page.on("request", on_request)
        page.on("response", on_response)
        open_oauth_page("01_auth_page")

        needs_login = False
        try:
            email_input = page.locator('input[name="email"], input[id="email-input"], input[id="email"]').first
            needs_login = email_input.is_visible(timeout=3000)
        except Exception:
            needs_login = False

        if needs_login:
            logger.warning("[Codex] 主号 OAuth 先落到了登录页，尝试先建立 ChatGPT 登录态后重试...")
            page.goto("https://chatgpt.com/auth/login", wait_until="domcontentloaded", timeout=60000)
            time.sleep(5)
            _screenshot(page, "codex_main_login_bootstrap.png")
            open_oauth_page("02_auth_retry")

            try:
                email_input = page.locator('input[name="email"], input[id="email-input"], input[id="email"]').first
                if email_input.is_visible(timeout=3000):
                    logger.error("[Codex] session 无法直接用于主号 Codex OAuth，仍落在登录页")
                    _screenshot(page, "codex_main_invalid_session.png")
                    return None
            except Exception:
                pass

        for step in range(10):
            if auth_code:
                break

            try:
                workspace_name = get_chatgpt_workspace_name()
                if "workspace" in page.url and workspace_name:
                    ws_btn = page.locator(f'text="{workspace_name}"').first
                    if ws_btn.is_visible(timeout=2000):
                        ws_btn.click()
                        time.sleep(2)
                        logger.info("[Codex] 主号选择 workspace: %s", workspace_name)
                        continue
            except Exception:
                pass

            if _click_oauth_consent_if_present(page, timeout=3000):
                logger.info("[Codex] 主号点击继续/授权 (step %d)...", step + 1)
                time.sleep(4)
                continue

            try:
                cur = page.url
                if f"localhost:{CODEX_CALLBACK_PORT}/auth/callback" in cur:
                    parsed = urllib.parse.urlparse(cur)
                    qs = urllib.parse.parse_qs(parsed.query)
                    auth_code = qs.get("code", [None])[0]
                    if auth_code:
                        break
            except Exception:
                pass

            time.sleep(1)

        if not auth_code:
            _screenshot(page, "codex_main_no_callback.png")
            logger.warning("[Codex] 主号未获取到 auth code，当前 URL: %s", page.url)
            return None
    finally:
        chatgpt.stop()

    return _exchange_auth_code(auth_code, code_verifier)


class SessionCodexAuthFlow:
    EMAIL_SELECTORS = [
        'input[name="email"]',
        'input[name="username"]',
        'input[id="email-input"]',
        'input[id="email"]',
        'input[id*="email" i]',
        'input[type="email"]',
        'input[placeholder*="email" i]',
        'input[placeholder*="邮箱"]',
        'input[placeholder*="电子邮件"]',
        'input[aria-label*="email" i]',
        'input[aria-label*="邮箱"]',
        'input[aria-label*="电子邮件"]',
        'input[autocomplete="email"]',
        'input[autocomplete="username"]',
    ]
    PASSWORD_SELECTORS = [
        'input[name="password"]',
        'input[type="password"]',
    ]
    CODE_SELECTORS = [
        'input[name="code"]',
        'input[placeholder*="验证码"]',
        'input[placeholder*="code" i]',
        'input[inputmode="numeric"]',
        'input[autocomplete="one-time-code"]',
    ]
    OTP_OPTION_SELECTORS = [
        _EMAIL_CODE_LOGIN_SELECTOR,
    ]

    def __init__(
        self,
        *,
        email,
        session_token,
        account_id,
        workspace_name="",
        password="",
        device_id="",
        native_oauth=False,
        password_callback=None,
        auth_file_callback=None,
        proxy_url=None,
        auth_cookies=None,
        phone_sms_provider=None,
        phone_sms_country=None,
        phone_sms_oasis_cdks=None,
    ):
        self.email = email or ""
        self.password = password or ""
        self.workspace_name = workspace_name or ""
        self.account_id = account_id or ""
        self.session_token = session_token or ""
        self.device_id = device_id or ""
        self.native_oauth = bool(native_oauth)
        self.password_callback = password_callback
        self.auth_file_callback = auth_file_callback or save_auth_file
        self.proxy_url = str(proxy_url or "").strip()
        self.auth_cookies = auth_cookies if isinstance(auth_cookies, list) else []
        self.phone_sms_provider = str(phone_sms_provider or "").strip()
        self.phone_sms_country = str(phone_sms_country or "").strip()
        self.phone_sms_oasis_cdks = str(phone_sms_oasis_cdks or "").strip()
        self.code_verifier, code_challenge = _generate_pkce()
        self.state = secrets.token_urlsafe(16)
        self.auth_url = _build_auth_url(code_challenge, self.state, native_oauth=self.native_oauth)
        self.auth_code = None
        self.chatgpt = None
        self.page = None

    def _visible_locator(self, selectors, timeout_ms=5000):
        if not self.page:
            return None

        selector = ", ".join(selectors)
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            frames = [self.page.main_frame]
            frames.extend(frame for frame in self.page.frames if frame != self.page.main_frame)
            for frame in frames:
                try:
                    locator = frame.locator(selector).first
                    if locator.is_visible(timeout=250):
                        return locator
                except Exception:
                    pass
            time.sleep(0.2)
        return None

    def _detect_step(self):
        if self.auth_code:
            return "completed", None

        cur = self.page.url if self.page else ""
        if f"localhost:{CODEX_CALLBACK_PORT}/auth/callback" in cur:
            parsed = urllib.parse.urlparse(cur)
            qs = urllib.parse.parse_qs(parsed.query)
            self.auth_code = qs.get("code", [None])[0]
            if self.auth_code:
                return "completed", None

        lower_url = cur.lower()
        if "auth.openai.com/add-phone" in lower_url or "/add-phone" in lower_url:
            return "phone_required", cur
        if "auth.openai.com/choose-an-account" in lower_url or "/choose-an-account" in lower_url:
            return "choose_account", cur
        if "auth.openai.com/email-verification" in lower_url or "/email-verification" in lower_url:
            return "code_required", cur
        if _is_auth_login_url(cur):
            return "email_required", cur
        try:
            body = self.page.locator("body").inner_text(timeout=500).lower()
        except Exception:
            body = ""
        if _looks_like_account_deactivated_text(body):
            return "account_deactivated", body[:500]
        if _looks_like_operation_timed_out_text(body):
            return "retryable_error", body[:500]
        if "add phone" in body or "phone verification" in body or "手机号" in body or "手机号码" in body:
            return "phone_required", cur
        if ("检查您的收件箱" in body or "check your inbox" in body) and (
            "验证码" in body or "verification code" in body
        ):
            return "code_required", cur

        if self._visible_locator(self.CODE_SELECTORS, timeout_ms=800):
            return "code_required", None
        if self._visible_locator(self.PASSWORD_SELECTORS, timeout_ms=800):
            return "password_required", None
        if self._visible_locator(self.EMAIL_SELECTORS, timeout_ms=800):
            return "email_required", None
        return "unknown", cur

    def _attach_callback_listeners(self):
        def on_request(request):
            if f"localhost:{CODEX_CALLBACK_PORT}/auth/callback" in request.url:
                parsed = urllib.parse.urlparse(request.url)
                qs = urllib.parse.parse_qs(parsed.query)
                self.auth_code = qs.get("code", [None])[0]

        def on_response(response):
            if self.auth_code:
                return
            if f"localhost:{CODEX_CALLBACK_PORT}/auth/callback" in response.url:
                parsed = urllib.parse.urlparse(response.url)
                qs = urllib.parse.parse_qs(parsed.query)
                self.auth_code = qs.get("code", [None])[0]

        self.page.on("request", on_request)
        self.page.on("response", on_response)

    def _inject_auth_cookies(self):
        cookies = []
        if len(self.session_token) > 3800:
            cookies.extend(
                [
                    {
                        "name": f"{chatgpt_session_service.CHATGPT_SESSION_COOKIE}.0",
                        "value": self.session_token[:3800],
                        "domain": "auth.openai.com",
                        "path": "/",
                        "httpOnly": True,
                        "secure": True,
                        "sameSite": "Lax",
                    },
                    {
                        "name": f"{chatgpt_session_service.CHATGPT_SESSION_COOKIE}.1",
                        "value": self.session_token[3800:],
                        "domain": "auth.openai.com",
                        "path": "/",
                        "httpOnly": True,
                        "secure": True,
                        "sameSite": "Lax",
                    },
                ]
            )
        else:
            cookies.append(
                {
                    "name": chatgpt_session_service.CHATGPT_SESSION_COOKIE,
                    "value": self.session_token,
                    "domain": "auth.openai.com",
                    "path": "/",
                    "httpOnly": True,
                    "secure": True,
                    "sameSite": "Lax",
                }
            )

        if self.account_id:
            cookies.append(
                {
                    "name": "_account",
                    "value": self.account_id,
                    "domain": "auth.openai.com",
                    "path": "/",
                    "secure": True,
                    "sameSite": "Lax",
                }
            )

        cookies.append(
            {
                "name": "oai-did",
                "value": self.chatgpt.oai_device_id,
                "domain": "auth.openai.com",
                "path": "/",
                "secure": True,
                "sameSite": "Lax",
            }
        )
        self.chatgpt.context.add_cookies(cookies)

    def _click_workspace_or_consent(self):
        acted = False

        try:
            if "workspace" in self.page.url and self.workspace_name:
                ws_btn = self.page.locator(f'text="{self.workspace_name}"').first
                if ws_btn.is_visible(timeout=1000):
                    ws_btn.click()
                    logger.info("[Codex] 主号选择 workspace: %s", self.workspace_name)
                    time.sleep(2)
                    acted = True
        except Exception:
            pass

        if _click_oauth_consent_if_present(self.page, timeout=1000):
            logger.info("[Codex] 主号点击继续/授权")
            time.sleep(3)
            acted = True

        return acted

    def _choose_current_account(self):
        if not self.page:
            return False
        try:
            clicked = self.page.evaluate(
                """(email) => {
                const targetEmail = String(email || '').trim().toLowerCase();
                const visible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style && style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
                };
                const norm = (text) => String(text || '').replace(/\\s+/g, ' ').trim();
                const candidates = Array.from(document.querySelectorAll('button, a, [role="button"], [role="option"], div, li, span, p'));
                const emailMatches = [];
                const fallbacks = [];
                for (const el of candidates) {
                    if (!visible(el)) continue;
                    const text = norm(el.innerText || el.textContent || el.getAttribute('aria-label') || '');
                    if (!text) continue;
                    const lower = text.toLowerCase();
                    if (/(remove|delete|移除|删除|刪除)/i.test(lower)) continue;
                    const clickable = el.closest('button, a, [role="button"], [role="option"], li') || el;
                    const rect = clickable.getBoundingClientRect();
                    const item = { el: clickable, text, score: text.length + Math.round(rect.width * rect.height / 1000) };
                    if (targetEmail && lower.includes(targetEmail)) {
                        emailMatches.push(item);
                        continue;
                    }
                    if (lower.includes('@') || lower.includes('continue') || lower.includes('继续')) {
                        fallbacks.push(item);
                    }
                }
                const chosen = (emailMatches.length ? emailMatches : fallbacks).sort((a, b) => a.score - b.score)[0];
                if (chosen) {
                    chosen.el.scrollIntoView({block: 'center', inline: 'center'});
                    chosen.el.click();
                    return chosen.text;
                }
                return '';
            }""",
                self.email,
            )
        except Exception:
            clicked = ""
        if clicked:
            logger.info("[Codex] 已选择 OAuth 账号: %s", str(clicked)[:120])
            time.sleep(3)
            return True
        return False

    def _auto_fill_email(self):
        if _is_email_verification_page(self.page):
            return False

        if _fill_auth_email_if_present(self.page, self.email, timeout=500):
            time.sleep(2)
            return True

        email_input = self._visible_locator(self.EMAIL_SELECTORS, timeout_ms=1000)
        if not email_input or not self.email:
            return False

        try:
            current_value = (email_input.input_value(timeout=1000) or "").strip().lower()
        except Exception:
            current_value = ""
        try:
            enabled = email_input.is_enabled(timeout=1000)
        except Exception:
            enabled = True

        if enabled:
            try:
                email_input.fill(self.email)
            except Exception:
                if current_value != self.email.strip().lower():
                    raise
        elif current_value != self.email.strip().lower():
            return False

        time.sleep(0.5)
        _click_primary_auth_button(self.page, email_input, ["Continue", "继续", "Log in"])
        time.sleep(3)
        return True

    def _auto_fill_password(self):
        password_input = self._visible_locator(self.PASSWORD_SELECTORS, timeout_ms=1000)
        if not password_input or not self.password:
            return False

        password_input.fill(self.password)
        time.sleep(0.5)
        _click_primary_auth_button(self.page, password_input, ["Continue", "继续", "Log in"])
        time.sleep(5)
        return True

    def _switch_password_to_otp(self):
        try:
            if _click_email_code_login_if_present(self.page):
                logger.info("[Codex] 主号流程检测到密码页，自动切换到一次性验证码登录")
                time.sleep(3)
                return True
        except Exception:
            pass
        otp_entry = self._visible_locator(self.OTP_OPTION_SELECTORS, timeout_ms=1500)
        if not otp_entry:
            return False

        try:
            otp_entry.click()
        except Exception:
            try:
                otp_entry.click(force=True)
            except Exception:
                return False

        logger.info("[Codex] 主号流程检测到密码页，自动切换到一次性验证码登录")
        time.sleep(3)
        return True

    def _advance(self, attempts=12):
        for _ in range(attempts):
            step, detail = self._detect_step()
            if step == "completed":
                return {"step": "completed", "detail": detail}
            if step == "phone_required":
                if _handle_oauth_add_phone_if_present(
                    self.page,
                    email=self.email,
                    phone_sms_provider=self.phone_sms_provider,
                    phone_sms_country=self.phone_sms_country,
                    phone_sms_oasis_cdks=self.phone_sms_oasis_cdks,
                ):
                    time.sleep(2)
                    continue
                return {"step": "phone_required", "detail": detail}
            if step == "account_deactivated":
                return {"step": "account_deactivated", "detail": detail}
            if step == "retryable_error":
                if _click_auth_retry_if_timed_out(self.page):
                    logger.warning("[Codex] OAuth 遇到 Operation timed out，已点击重试")
                    time.sleep(5)
                    continue
                return {"step": "retryable_error", "detail": detail}
            if step == "code_required":
                return {"step": "code_required", "detail": detail}
            if step == "password_required":
                if self._switch_password_to_otp():
                    continue
                return {
                    "step": "unsupported_password",
                    "detail": "主号 Codex 当前停留在密码页，且未找到一次性验证码入口",
                }

            if step == "email_required":
                if self._auto_fill_email():
                    continue
                return {"step": "email_required", "detail": detail}

            if step == "choose_account":
                if self._choose_current_account():
                    continue
                return {"step": "choose_account", "detail": detail}

            if self._click_workspace_or_consent():
                continue

            time.sleep(1)

        final_step, detail = self._detect_step()
        return {"step": final_step, "detail": detail}

    def start(self):
        if not self.session_token:
            raise RuntimeError("缺少登录 session")
        if not self.email:
            raise RuntimeError("缺少登录邮箱")

        from autotoken.integrations.chatgpt_api import ChatGPTTeamAPI

        self.chatgpt = ChatGPTTeamAPI()
        if self.device_id:
            self.chatgpt.oai_device_id = self.device_id
        self.chatgpt.start_with_session(
            self.session_token,
            self.account_id,
            self.workspace_name,
            proxy_url=self.proxy_url,
            cookies=self.auth_cookies,
        )
        self.page = self.chatgpt.context.new_page()
        self._attach_callback_listeners()
        self._inject_auth_cookies()
        self.page.goto(self.auth_url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)
        return self._advance()

    def submit_password(self, password):
        self.password = password
        if self.password_callback:
            self.password_callback(password)
        password_input = self._visible_locator(self.PASSWORD_SELECTORS, timeout_ms=5000)
        if not password_input:
            raise RuntimeError("当前 Codex 登录不是密码输入步骤")

        password_input.fill(password)
        time.sleep(0.5)
        _click_primary_auth_button(self.page, password_input, ["Continue", "继续", "Log in"])
        time.sleep(5)
        return self._advance()

    def submit_code(self, code):
        code = str(code or "").strip()
        if not code:
            raise RuntimeError("验证码不能为空，请输入邮件中的验证码后再提交")

        code_input = self._visible_locator(self.CODE_SELECTORS, timeout_ms=5000)
        if not code_input:
            raise RuntimeError("当前 Codex 登录不是验证码输入步骤")

        code_input.fill(code)
        time.sleep(0.5)
        _click_primary_auth_button(self.page, code_input, ["Continue", "继续", "Verify"])
        time.sleep(5)
        return self._advance()

    def complete(self):
        if not self.auth_code:
            raise RuntimeError("未获取到 Codex authorization code")

        bundle = _exchange_auth_code(self.auth_code, self.code_verifier, fallback_email=self.email)
        if not bundle:
            raise RuntimeError("Codex token 交换失败")

        filepath = self.auth_file_callback(bundle)
        return {
            "email": bundle.get("email"),
            "auth_file": filepath,
            "plan_type": bundle.get("plan_type"),
            "bundle": bundle,
        }

    def stop(self):
        if self.chatgpt:
            self.chatgpt.stop()
        self.chatgpt = None
        self.page = None


class MainCodexSyncFlow(SessionCodexAuthFlow):
    def __init__(self):
        super().__init__(
            email=get_admin_email(),
            session_token=get_admin_session_token(),
            account_id=get_chatgpt_account_id(),
            workspace_name=get_chatgpt_workspace_name(),
            password="",
            password_callback=None,
            auth_file_callback=save_main_auth_file,
        )

    def complete(self):
        info = super().complete()

        from autotoken.integrations.cpa_sync import sync_main_codex_to_cpa

        sync_main_codex_to_cpa(info["auth_file"])
        return {
            "email": info.get("email"),
            "auth_file": info.get("auth_file"),
            "plan_type": info.get("plan_type"),
        }


class ChromeCDPCodexAuthFlow:
    """Drive OAuth in the user's real Chrome through DevTools Protocol."""

    def __init__(
        self,
        *,
        email,
        password="",
        mail_client=None,
        native_oauth=True,
        otp_timeout=120,
        cdp_url=None,
        auth_file_callback=None,
    ):
        self.email = email or ""
        self.password = password or ""
        self.mail_client = mail_client
        self.native_oauth = bool(native_oauth)
        self.otp_timeout = int(otp_timeout or 120)
        self.cdp_url = _normalize_chrome_cdp_url(cdp_url)
        self.auth_file_callback = auth_file_callback or save_auth_file
        self.code_verifier, code_challenge = _generate_pkce()
        self.state = secrets.token_urlsafe(16)
        self.auth_url = _build_auth_url(code_challenge, self.state, native_oauth=self.native_oauth)
        self.auth_code = ""
        self._ws = None
        self._command_id = 0
        self._latest_email_id = 0
        self._submitted_codes: set[str] = set()

    async def _send(self, method, params=None, *, timeout=12):
        self._command_id += 1
        command_id = self._command_id
        await self._ws.send(json.dumps({"id": command_id, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=max(0.2, deadline - time.time()))
            except asyncio.TimeoutError as exc:
                raise ChromeCDPFlowError(f"Chrome CDP {method} timed out") from exc
            payload = json.loads(raw)
            if payload.get("id") != command_id:
                continue
            if payload.get("error"):
                raise ChromeCDPFlowError(f"Chrome CDP {method} failed: {payload['error']}")
            return payload.get("result") or {}
        raise ChromeCDPFlowError(f"Chrome CDP {method} timed out")

    async def _eval(self, expression, *, timeout=12):
        result = await self._send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": False,
            },
            timeout=timeout,
        )
        value = (result.get("result") or {}).get("value")
        return value

    async def _page_state(self):
        selectors = {
            "email": SessionCodexAuthFlow.EMAIL_SELECTORS,
            "password": SessionCodexAuthFlow.PASSWORD_SELECTORS,
            "code": SessionCodexAuthFlow.CODE_SELECTORS,
        }
        js = f"""
(() => {{
  const selectors = {json.dumps(selectors)};
  const visible = (el) => {{
    if (!el) return false;
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style && style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
  }};
  const hasVisible = (items) => items.some((selector) => Array.from(document.querySelectorAll(selector)).some(visible));
  const isEmailVerification = location.href.toLowerCase().includes('/email-verification');
  const isAuthLogin = /auth\\.openai\\.com\\/(log-in|login)/.test(location.href.toLowerCase());
  const body = (document.body && document.body.innerText || '').slice(0, 3000);
  return {{
    url: location.href,
    title: document.title || '',
    body,
    hasEmail: isAuthLogin || hasVisible(selectors.email),
    hasPassword: hasVisible(selectors.password),
    hasCode: isEmailVerification || hasVisible(selectors.code),
  }};
}})()
"""
        state = await self._eval(js)
        return state if isinstance(state, dict) else {}

    def _detect_step_from_state(self, state):
        url = str(state.get("url") or "")
        auth_code = _extract_auth_code_from_url(url)
        if auth_code:
            self.auth_code = auth_code
            return "completed", None

        lower_url = url.lower()
        body = str(state.get("body") or "").lower()
        if "auth.openai.com/add-phone" in lower_url or "/add-phone" in lower_url:
            return "phone_required", url
        if "auth.openai.com/email-verification" in lower_url or "/email-verification" in lower_url:
            return "code_required", url
        if _is_auth_login_url(url):
            return "email_required", url
        if _looks_like_account_deactivated_text(body):
            return "account_deactivated", body[:500]
        if _looks_like_operation_timed_out_text(body):
            return "retryable_error", body[:500]
        if "add phone" in body or "phone verification" in body or "手机号" in body or "手机号码" in body:
            return "phone_required", url
        if ("检查您的收件箱" in body or "check your inbox" in body) and (
            "验证码" in body or "verification code" in body
        ):
            return "code_required", url
        if state.get("hasCode"):
            return "code_required", None
        if state.get("hasPassword"):
            return "password_required", None
        if state.get("hasEmail"):
            return "email_required", None
        return "unknown", url

    async def _click_by_text(self, labels):
        js = f"""
(() => {{
  const labels = {json.dumps(labels)};
  const visible = (el) => {{
    if (!el) return false;
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style && style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
  }};
  const norm = (text) => String(text || '').replace(/\\s+/g, ' ').trim().toLowerCase();
  const targets = Array.from(document.querySelectorAll('button, input[type="submit"], a, [role="button"]'));
  for (const el of targets) {{
    if (!visible(el) || el.disabled || el.getAttribute('aria-disabled') === 'true') continue;
    const text = norm(el.innerText || el.value || el.getAttribute('aria-label') || '');
    if (!text) continue;
    if (labels.some((label) => text === norm(label) || text.includes(norm(label)))) {{
      el.click();
      return text;
    }}
  }}
  return '';
}})()
"""
        return await self._eval(js)

    async def _fill_input(self, selectors, value, *, allow_disabled_match=False):
        js = f"""
(() => {{
  const selectors = {json.dumps(selectors)};
  const value = {json.dumps(value or "")};
  const allowDisabledMatch = {json.dumps(bool(allow_disabled_match))};
  const isEmailFill = selectors.some((selector) => String(selector).toLowerCase().includes('email') || String(selector).toLowerCase().includes('username'));
  const visible = (el) => {{
    if (!el) return false;
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style && style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
  }};
  const setValue = (el, newValue) => {{
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
    el.focus();
    if (descriptor && descriptor.set) descriptor.set.call(el, newValue);
    else el.value = newValue;
    el.dispatchEvent(new InputEvent('input', {{ bubbles: true, inputType: 'insertText', data: newValue }}));
    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
  }};
  for (const selector of selectors) {{
    for (const el of Array.from(document.querySelectorAll(selector))) {{
      if (!visible(el)) continue;
      const current = String(el.value || '').trim().toLowerCase();
      if (el.disabled || el.readOnly) {{
        if (allowDisabledMatch && current === String(value).trim().toLowerCase()) return 'disabled_match';
        continue;
      }}
      setValue(el, value);
      return 'filled';
    }}
  }}
  if (isEmailFill && /auth\\.openai\\.com\\/(log-in|login)/.test(location.href.toLowerCase())) {{
    for (const el of Array.from(document.querySelectorAll('input'))) {{
      const type = String(el.getAttribute('type') || '').toLowerCase();
      const name = String(el.getAttribute('name') || '').toLowerCase();
      const autocomplete = String(el.getAttribute('autocomplete') || '').toLowerCase();
      if (!visible(el) || el.disabled || el.readOnly) continue;
      if (type === 'hidden' || type === 'password' || type === 'checkbox') continue;
      if (name === 'code' || autocomplete === 'one-time-code') continue;
      setValue(el, value);
      return 'filled_generic_email';
    }}
  }}
  return '';
}})()
"""
        return await self._eval(js)

    async def _fill_otp_code(self, code):
        js = f"""
(() => {{
  const code = String({json.dumps(code or "")} || '').trim();
  if (!code) return false;
  const selectors = {json.dumps(SessionCodexAuthFlow.CODE_SELECTORS)};
  const visible = (el) => {{
    if (!el) return false;
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style && style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
  }};
  const setValue = (el, newValue) => {{
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
    el.focus();
    if (descriptor && descriptor.set) descriptor.set.call(el, newValue);
    else el.value = newValue;
    el.dispatchEvent(new InputEvent('input', {{ bubbles: true, inputType: 'insertText', data: newValue }}));
    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
  }};
  const inputs = [];
  for (const selector of selectors) {{
    for (const el of Array.from(document.querySelectorAll(selector))) {{
      if (visible(el) && !el.disabled && !el.readOnly && !inputs.includes(el)) inputs.push(el);
    }}
  }}
  if (!inputs.length && location.href.toLowerCase().includes('/email-verification')) {{
    for (const el of Array.from(document.querySelectorAll('input'))) {{
      const type = String(el.getAttribute('type') || '').toLowerCase();
      const name = String(el.getAttribute('name') || '').toLowerCase();
      const autocomplete = String(el.getAttribute('autocomplete') || '').toLowerCase();
      if (!visible(el) || el.disabled || el.readOnly) continue;
      if (type === 'hidden' || type === 'email' || type === 'password') continue;
      if (name === 'email' || autocomplete === 'email' || autocomplete === 'username') continue;
      inputs.push(el);
      break;
    }}
  }}
  if (!inputs.length) return false;
  const oneCharInputs = inputs.filter((el) => Number(el.maxLength || 0) === 1 || el.getAttribute('aria-label'));
  if (oneCharInputs.length >= code.length && code.length > 1) {{
    for (let i = 0; i < code.length; i++) setValue(oneCharInputs[i], code[i]);
    return oneCharInputs.slice(0, code.length).every((el) => String(el.value || '').trim());
  }} else {{
    setValue(inputs[0], code);
    return String(inputs[0].value || '').trim().length > 0;
  }}
}})()
"""
        return bool(await self._eval(js))

    def _prime_latest_email_id(self):
        if not self.mail_client:
            return
        try:
            emails = self.mail_client.search_emails_by_recipient(self.email, size=1)
            if emails:
                self._latest_email_id = int(emails[0].get("emailId") or 0)
        except Exception:
            self._latest_email_id = 0

    def _poll_email_otp_once(self):
        if not self.mail_client:
            return "", 0
        try:
            emails = self.mail_client.search_emails_by_recipient(self.email, size=10)
        except Exception as exc:
            logger.warning("[Codex] Chrome CDP OAuth 查询验证码失败: %s", exc)
            return "", 0
        for item in emails:
            email_id = int(item.get("emailId") or 0)
            code = self.mail_client.extract_verification_code(item)
            if code:
                return str(code), email_id
        return "", 0

    async def _handle_email_step(self):
        result = await self._fill_input(SessionCodexAuthFlow.EMAIL_SELECTORS, self.email, allow_disabled_match=True)
        if result:
            logger.info("[Codex] Chrome CDP OAuth 已处理邮箱步骤: %s", self.email)
            await asyncio.sleep(0.4)
            await self._click_by_text(["Continue", "继续", "Log in", "登录"])
            await asyncio.sleep(2)
            return True
        return False

    async def _handle_password_step(self):
        clicked = await self._click_by_text(list(_EMAIL_CODE_LOGIN_TEXTS))
        if clicked:
            logger.info("[Codex] Chrome CDP OAuth 已切换邮箱验证码登录")
            await asyncio.sleep(2)
            return True
        if self.password:
            result = await self._fill_input(SessionCodexAuthFlow.PASSWORD_SELECTORS, self.password)
            if result:
                logger.info("[Codex] Chrome CDP OAuth 已填写密码")
                await asyncio.sleep(0.4)
                await self._click_by_text(["Continue", "继续", "Log in", "登录"])
                await asyncio.sleep(3)
                return True
        return False

    async def _handle_code_step(self):
        if not self.mail_client:
            logger.info("[Codex] Chrome CDP OAuth 等待用户在本机浏览器手动输入邮箱验证码")
            await asyncio.sleep(3)
            return True

        start = time.time()
        while time.time() - start < self.otp_timeout:
            code, email_id = self._poll_email_otp_once()
            if not code:
                await asyncio.sleep(3)
                state = await self._page_state()
                step, _ = self._detect_step_from_state(state)
                if step != "code_required":
                    return True
                continue
            self._submitted_codes.add(code)
            self._latest_email_id = max(self._latest_email_id, email_id)
            logger.info("[Codex] Chrome CDP OAuth 收到邮箱验证码: %s", code)
            if not await self._fill_otp_code(code):
                logger.warning("[Codex] Chrome CDP OAuth 验证码未成功填入，跳过点击继续")
                return False
            await asyncio.sleep(0.4)
            await self._click_by_text(["Continue", "继续", "Verify", "验证"])
            await asyncio.sleep(4)
            return True

        logger.warning("[Codex] Chrome CDP OAuth 未收到邮箱验证码")
        return False

    async def _run_browser(self):
        import websockets

        ws_url = _open_chrome_cdp_tab(self.auth_url, self.cdp_url)
        logger.info("[Codex] 已在本机 Chrome 打开 OAuth: cdp=%s email=%s", self.cdp_url, self.email)
        self._prime_latest_email_id()
        async with websockets.connect(ws_url, max_size=16 * 1024 * 1024) as ws:
            self._ws = ws
            await self._send("Page.enable")
            await self._send("Runtime.enable")
            deadline = time.time() + int(os.environ.get("OAUTH_CHROME_CDP_TIMEOUT", "240"))
            last_unknown_log = 0
            while time.time() < deadline:
                state = await self._page_state()
                step, detail = self._detect_step_from_state(state)
                if step == "completed":
                    return
                if step == "phone_required":
                    raise CodexOAuthPhoneRequired(str(detail or ""))
                if step == "account_deactivated":
                    raise CodexOAuthAccountDeactivated(str(detail or ""))
                if step == "retryable_error":
                    clicked = await self._click_by_text(["重试", "Retry", "Try again"])
                    if clicked:
                        logger.warning("[Codex] Chrome CDP OAuth 遇到 Operation timed out，已点击重试: %s", clicked)
                        await asyncio.sleep(5)
                        continue
                if step == "email_required":
                    if await self._handle_email_step():
                        continue
                elif step == "password_required":
                    if await self._handle_password_step():
                        continue
                elif step == "code_required":
                    if await self._handle_code_step():
                        continue
                    return
                else:
                    clicked = await self._click_by_text(
                        ["Continue", "继续", "Allow", "Authorize", "授权", "Confirm", "确认"]
                    )
                    if clicked:
                        logger.info("[Codex] Chrome CDP OAuth 点击继续/授权: %s", clicked)
                        await asyncio.sleep(3)
                        continue
                    if time.time() - last_unknown_log > 10:
                        logger.info("[Codex] Chrome CDP OAuth 等待页面推进: %s", detail or "")
                        last_unknown_log = time.time()
                await asyncio.sleep(1)

        raise ChromeCDPFlowError("Chrome CDP OAuth 超时，未获取到 authorization code")

    def run(self):
        if not self.email:
            raise RuntimeError("缺少登录邮箱")
        asyncio.run(self._run_browser())
        if not self.auth_code:
            raise ChromeCDPFlowError("Chrome CDP OAuth 未获取到 authorization code")
        bundle = _exchange_auth_code(self.auth_code, self.code_verifier, fallback_email=self.email)
        if not bundle:
            raise RuntimeError("Codex token 交换失败")
        returned_email = str(bundle.get("email") or "").strip().lower()
        if returned_email and returned_email != self.email.strip().lower():
            raise RuntimeError(f"Chrome CDP OAuth 返回了非目标账号: {returned_email}")
        filepath = self.auth_file_callback(bundle)
        return {
            "email": bundle.get("email"),
            "auth_file": filepath,
            "plan_type": bundle.get("plan_type"),
            "bundle": bundle,
        }


def login_codex_via_chrome_cdp(
    email,
    mail_client=None,
    *,
    password="",
    native_oauth=True,
    otp_timeout=120,
    cdp_url=None,
):
    """Complete Codex OAuth in the user's real Chrome through local CDP."""
    flow = ChromeCDPCodexAuthFlow(
        email=email,
        password=password,
        mail_client=mail_client,
        native_oauth=native_oauth,
        otp_timeout=otp_timeout,
        cdp_url=cdp_url,
    )
    return flow.run()


def _is_browser_open_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(str(url or "").strip())
    except Exception:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _open_default_browser_url(url: str) -> bool:
    if not _is_browser_open_url(url):
        logger.warning("[Codex] refused to open non-http OAuth helper URL")
        return False
    if os.name == "nt" and hasattr(os, "startfile"):
        os.startfile(url)  # type: ignore[attr-defined]
        return True
    opener = ["open", url] if sys.platform == "darwin" else ["xdg-open", url]
    subprocess.Popen(opener, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def _open_real_chrome_url(url: str) -> bool:
    if not _is_browser_open_url(url):
        logger.warning("[Codex] refused to open non-http OAuth helper URL")
        return False
    chrome_path = (
        os.environ.get("OAUTH_WINDOWS_CHROME_PATH") or r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    )
    profile_dir = os.environ.get("OAUTH_REAL_CHROME_PROFILE") or "Default"
    user_data_dir = os.environ.get("OAUTH_REAL_CHROME_USER_DATA_DIR") or str(
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"
    )
    args = [
        chrome_path,
        f"--user-data-dir={user_data_dir}",
        f"--profile-directory={profile_dir}",
        f"--load-extension={OAUTH_HELPER_EXTENSION_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        url,
    ]
    if Path(chrome_path).exists():
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    return _open_default_browser_url(url)


class _OAuthHelperServer:
    def __init__(self, *, email, password, token):
        self.email = email or ""
        self.password = password or ""
        self.token = token
        self.otp = ""
        self.events: list[dict] = []
        self.auth_code = ""
        self.callback_url = ""
        self.phone_required_url = ""
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.port = 0

    def start(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def _send_json(self, status, payload):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _valid_token(self):
                parsed = urllib.parse.urlparse(self.path)
                qs = urllib.parse.parse_qs(parsed.query)
                return qs.get("token", [""])[0] == owner.token

            def do_OPTIONS(self):
                self._send_json(200, {"ok": True})

            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path != "/state" or not self._valid_token():
                    self._send_json(404, {"ok": False})
                    return
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "email": owner.email,
                        "password": owner.password,
                        "otp": owner.otp,
                    },
                )

            def do_POST(self):
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path != "/event" or not self._valid_token():
                    self._send_json(404, {"ok": False})
                    return
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                except Exception:
                    payload = {}
                owner.events.append(payload)
                url = str(payload.get("url") or "")
                if payload.get("type") == "callback":
                    owner.callback_url = url
                    owner.auth_code = _extract_auth_code_from_url(url)
                if payload.get("type") == "phone_required":
                    owner.phone_required_url = url
                self._send_json(200, {"ok": True})

            def log_message(self, *_args):
                return

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = int(self.httpd.server_address[1])
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
        self.httpd = None


class WindowsUICodexAuthFlow:
    """Drive OAuth in the user's normal desktop Chrome through a locked helper extension."""

    def __init__(
        self,
        *,
        email,
        password="",
        mail_client=None,
        native_oauth=True,
        otp_timeout=120,
        auth_file_callback=None,
    ):
        self.email = email or ""
        self.password = password or ""
        self.mail_client = mail_client
        self.native_oauth = bool(native_oauth)
        self.otp_timeout = int(otp_timeout or 120)
        self.auth_file_callback = auth_file_callback or save_auth_file
        self.code_verifier, code_challenge = _generate_pkce()
        self.state = secrets.token_urlsafe(16)
        self.auth_url = _build_auth_url(code_challenge, self.state, native_oauth=self.native_oauth)
        self._latest_email_id = 0
        self._submitted_codes: set[str] = set()
        self._server: _OAuthHelperServer | None = None

    def _prime_latest_email_id(self):
        if not self.mail_client:
            return
        try:
            emails = self.mail_client.search_emails_by_recipient(self.email, size=1)
            if emails:
                self._latest_email_id = int(emails[0].get("emailId") or 0)
        except Exception:
            self._latest_email_id = 0

    def _poll_email_otp_once(self):
        if not self.mail_client:
            return "", 0
        try:
            emails = self.mail_client.search_emails_by_recipient(self.email, size=10)
        except Exception as exc:
            logger.warning("[Codex] Windows UI OAuth 查询验证码失败: %s", exc)
            return "", 0
        for item in emails:
            email_id = int(item.get("emailId") or 0)
            code = self.mail_client.extract_verification_code(item)
            if code:
                return str(code), email_id
        return "", 0

    def _helper_auth_url(self):
        if not self._server:
            raise WindowsUIFlowError("OAuth helper server not started")
        return oauth_helper_auth_url(self._server.token, self._server.port, self.auth_url)

    def _wait_for_helper(self, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._server and self._server.auth_code:
                return "completed", self._server.auth_code, ""
            if self._server and self._server.phone_required_url:
                return "phone_required", "", self._server.phone_required_url
            time.sleep(1)
        return "timeout", "", ""

    def _submit_email(self):
        logger.info("[Codex] Windows UI OAuth 打开真实 Chrome Profile 并锁定 OpenAI 登录页: %s", self.email)
        _open_real_chrome_url(self._helper_auth_url())

    def _submit_code(self):
        if not self.mail_client:
            logger.info("[Codex] Windows UI OAuth 等待用户手动输入邮箱验证码")
            return
        start = time.time()
        while time.time() - start < self.otp_timeout:
            if self._server and self._server.auth_code:
                return
            if self._server and self._server.phone_required_url:
                return
            code, email_id = self._poll_email_otp_once()
            if not code:
                time.sleep(3)
                continue
            self._submitted_codes.add(code)
            self._latest_email_id = max(self._latest_email_id, email_id)
            logger.info("[Codex] Windows UI OAuth 收到邮箱验证码: %s", code)
            if self._server:
                self._server.otp = code
            return
        raise WindowsUIFlowError("Windows UI OAuth 未收到邮箱验证码")

    def run(self):
        if os.name != "nt":
            raise WindowsUIFlowError("Windows UI OAuth 仅支持 Windows 桌面")
        if not self.email:
            raise RuntimeError("缺少登录邮箱")

        self._prime_latest_email_id()
        self._server = _OAuthHelperServer(
            email=self.email, password=self.password, token=secrets.token_urlsafe(18)
        ).start()
        try:
            self._submit_email()
            start = time.time()
            callback_timeout = int(os.environ.get("OAUTH_WINDOWS_UI_CALLBACK_TIMEOUT", "240"))
            otp_started = False
            while time.time() - start < callback_timeout:
                if self._server.auth_code:
                    break
                if self._server.phone_required_url:
                    raise CodexOAuthPhoneRequired(self._server.phone_required_url)
                if not otp_started and any(event.get("type") == "email_filled" for event in self._server.events):
                    otp_started = True
                    self._submit_code()
                time.sleep(1)
            auth_code = self._server.auth_code
            if not auth_code:
                last_event = self._server.events[-1] if self._server.events else {}
                raise WindowsUIFlowError(f"Windows UI OAuth 未获取到 authorization code，last_event={last_event}")
        finally:
            if self._server:
                self._server.stop()

        bundle = _exchange_auth_code(auth_code, self.code_verifier, fallback_email=self.email)
        if not bundle:
            raise RuntimeError("Codex token 交换失败")
        returned_email = str(bundle.get("email") or "").strip().lower()
        if returned_email and returned_email != self.email.strip().lower():
            raise RuntimeError(f"Windows UI OAuth 返回了非目标账号: {returned_email}")
        filepath = self.auth_file_callback(bundle)
        return {
            "email": bundle.get("email"),
            "auth_file": filepath,
            "plan_type": bundle.get("plan_type"),
            "bundle": bundle,
        }


def login_codex_via_windows_ui(
    email,
    mail_client=None,
    *,
    password="",
    native_oauth=True,
    otp_timeout=120,
):
    """Complete Codex OAuth in the user's normal desktop Chrome via Windows UI."""
    flow = WindowsUICodexAuthFlow(
        email=email,
        password=password,
        mail_client=mail_client,
        native_oauth=native_oauth,
        otp_timeout=otp_timeout,
    )
    return flow.run()


def login_codex_via_auth_session_protocol(
    email,
    session_data,
    *,
    native_oauth=True,
    auth_file_callback=None,
    proxy_url=None,
):
    """Finish Codex OAuth by following auth redirects with the saved ChatGPT session cookies.

    This is the codex-console style path: no Playwright, no local browser UI. It only succeeds
    when the existing ChatGPT session can be accepted by auth.openai.com and redirected to the
    local OAuth callback URL directly.
    """
    if not isinstance(session_data, dict):
        logger.warning("[Codex] 协议 OAuth 失败: session_data 格式无效")
        return None

    merged = _normalize_auth_session_payload(session_data)
    session_token = _extract_auth_session_token(merged)
    account_id = _extract_account_id_from_auth_session(merged)
    device_id = str(merged.get("oai_device_id") or merged.get("device_id") or "").strip()
    if not session_token:
        logger.warning("[Codex] 协议 OAuth 失败: 缺少 session cookie")
        return None

    code_verifier, code_challenge = _generate_pkce()
    state = secrets.token_urlsafe(16)
    auth_url = _build_auth_url(code_challenge, state, native_oauth=native_oauth)
    http = _make_protocol_oauth_session(proxy_url=proxy_url) if proxy_url else _make_protocol_oauth_session()
    _seed_protocol_auth_cookies(
        http,
        session_token=session_token,
        account_id=account_id,
        device_id=device_id,
    )

    callback = _follow_codex_oauth_redirects_protocol(http, auth_url, expected_state=state)
    if callback.get("error"):
        raise CodexProtocolOAuthError(
            f"Codex OAuth 返回错误: {callback['error']}", final_url=callback.get("raw_url", "")
        )
    auth_code = str(callback.get("code") or "").strip()
    if not auth_code:
        raise CodexProtocolOAuthError("Codex OAuth 回调缺少 code", final_url=callback.get("raw_url", ""))

    bundle = _exchange_auth_code_protocol(http, auth_code, code_verifier, fallback_email=email)
    filepath = (auth_file_callback or save_auth_file)(bundle)
    return {
        "email": bundle.get("email"),
        "auth_file": filepath,
        "plan_type": bundle.get("plan_type"),
        "bundle": bundle,
    }


def login_codex_via_auth_session(
    email,
    session_data,
    mail_client=None,
    *,
    password="",
    native_oauth=True,
    otp_timeout=120,
    proxy_url=None,
    phone_sms_provider=None,
    phone_sms_country=None,
    phone_sms_oasis_cdks=None,
):
    """Complete Codex OAuth by reusing a freshly registered ChatGPT auth session."""
    if not isinstance(session_data, dict):
        logger.warning("[Codex] auth_session 复用 OAuth 失败: session_data 格式无效")
        return None

    merged = _normalize_auth_session_payload(session_data)
    session_token = _extract_auth_session_token(merged)
    account_id = _extract_account_id_from_auth_session(merged)
    device_id = str(merged.get("oai_device_id") or merged.get("device_id") or "").strip()
    auth_cookies = merged.get("cookies") if isinstance(merged.get("cookies"), list) else []
    if not session_token:
        logger.warning("[Codex] auth_session 复用 OAuth 失败: 缺少 session cookie")
        return None
    if not account_id:
        logger.warning("[Codex] auth_session 复用 OAuth 失败: 缺少 account_id")
        return None

    flow = SessionCodexAuthFlow(
        email=email,
        session_token=session_token,
        account_id=account_id,
        workspace_name="",
        password=password,
        device_id=device_id,
        native_oauth=native_oauth,
        proxy_url=proxy_url,
        auth_cookies=auth_cookies,
        phone_sms_provider=phone_sms_provider,
        phone_sms_country=phone_sms_country,
        phone_sms_oasis_cdks=phone_sms_oasis_cdks,
    )
    try:
        state = flow.start()
        for _ in range(4):
            step = state.get("step")
            if step == "completed":
                return flow.complete()
            if step == "phone_required":
                raise CodexOAuthPhoneRequired(str(state.get("detail") or ""))
            if step == "account_deactivated":
                raise CodexOAuthAccountDeactivated(str(state.get("detail") or ""))
            if step != "code_required":
                logger.warning("[Codex] auth_session 复用 OAuth 未完成: %s", state)
                return None
            if not mail_client:
                logger.warning("[Codex] auth_session 复用 OAuth 需要邮箱验证码，但缺少 mail_client")
                return None

            otp = None
            start = time.time()
            while time.time() - start < otp_timeout:
                try:
                    emails = mail_client.search_emails_by_recipient(email, size=10)
                except Exception as exc:
                    logger.warning("[Codex] auth_session 复用 OAuth 查询验证码失败: %s", exc)
                    emails = []
                for item in emails:
                    code = mail_client.extract_verification_code(item)
                    if code:
                        otp = code
                        break
                if otp:
                    break
                time.sleep(3)

            if not otp:
                logger.warning("[Codex] auth_session 复用 OAuth 未收到邮箱验证码")
                return None
            logger.info("[Codex] auth_session 复用 OAuth 收到验证码: %s", otp)
            state = flow.submit_code(otp)
        logger.warning("[Codex] auth_session 复用 OAuth 超出验证码重试次数")
        return None
    finally:
        flow.stop()


def login_main_codex():
    """主号 Codex 登录：使用已保存的管理员 session。"""
    return login_codex_via_session()


def save_auth_file(bundle):
    """保存 CPA 兼容的认证文件。同一邮箱只保留一个文件，优先 team。"""
    ensure_auth_dir()

    email = bundle["email"]
    plan_type = bundle.get("plan_type", "unknown")
    account_id = bundle.get("account_id", "")

    # 清理同一邮箱的旧文件（避免 free/team 并存）
    for old in iter_auth_files_for_email(email, auth_dir=AUTH_DIR):
        delete_codex_auth_file(old)
        if delete_auth_file(old, auth_dir=AUTH_DIR):
            logger.info("[Codex] 清理旧文件: %s", old.name)

    filepath = codex_auth_path(email=email, plan_type=plan_type, account_id=account_id, auth_dir=AUTH_DIR)
    return _write_auth_file(filepath, bundle)


def save_main_auth_file(bundle):
    """保存主号 Codex 认证文件，不进入账号池。"""
    account_id = bundle.get("account_id") or hashlib.md5(bundle.get("email", "main").encode()).hexdigest()[:8]

    for old in iter_codex_auth_files(auth_dir=AUTH_DIR):
        if not old.name.startswith("codex-main-"):
            continue
        delete_codex_auth_file(old)
        if delete_auth_file(old, auth_dir=AUTH_DIR):
            logger.info("[Codex] 清理旧主号文件: %s", old.name)

    filepath = codex_auth_path(email=bundle.get("email", "main"), plan_type="", account_id=account_id, auth_dir=AUTH_DIR, main=True)
    return _write_auth_file(filepath, bundle)


def get_saved_main_auth_file():
    """获取本地已保存的主号 Codex 认证文件路径。"""
    candidates = []
    for path in AUTH_DIR.glob("codex-main-*.json"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except Exception:
            continue
        candidates.append((stat.st_mtime, path.name, path))

    if not candidates:
        return ""

    candidates.sort(reverse=True)
    return str(candidates[0][2].resolve())


def refresh_main_auth_file():
    """基于已保存的管理员登录态，刷新并保存主号 Codex 认证文件。"""
    bundle = login_codex_via_session()
    if not bundle:
        raise RuntimeError("无法基于管理员登录态生成主号 Codex 认证文件")

    auth_file = save_main_auth_file(bundle)
    return {
        "email": bundle.get("email"),
        "auth_file": auth_file,
        "plan_type": bundle.get("plan_type"),
    }


def quota_result_quota_info(info):
    """从 check_codex_quota 返回值中提取额度快照。"""
    if not isinstance(info, dict):
        return None
    quota_info = info.get("quota_info")
    if isinstance(quota_info, dict):
        return quota_info
    if "primary_pct" in info or "weekly_pct" in info:
        return info
    return None


def quota_result_resets_at(info):
    """从 check_codex_quota 返回值中提取恢复时间。"""
    if isinstance(info, dict):
        value = info.get("resets_at")
    else:
        value = info

    try:
        return int(value or 0)
    except Exception:
        return 0


def get_quota_exhausted_info(quota_info, *, limit_reached=False):
    """根据额度快照判断是否已耗尽，并返回耗尽详情。"""
    if not isinstance(quota_info, dict):
        return None

    primary_pct = int(quota_info.get("primary_pct", 0) or 0)
    weekly_pct = int(quota_info.get("weekly_pct", 0) or 0)
    monthly_pct = int(quota_info.get("monthly_pct", 0) or 0)
    primary_reset = int(quota_info.get("primary_resets_at", 0) or 0)
    weekly_reset = int(quota_info.get("weekly_resets_at", 0) or 0)
    monthly_reset = int(quota_info.get("monthly_resets_at", 0) or 0)

    primary_exhausted = primary_pct >= 100
    weekly_exhausted = weekly_pct >= 100
    monthly_exhausted = monthly_pct >= 100
    if not (limit_reached or primary_exhausted or weekly_exhausted or monthly_exhausted):
        return None

    reset_candidates = []
    if primary_exhausted and primary_reset:
        reset_candidates.append(primary_reset)
    if weekly_exhausted and weekly_reset:
        reset_candidates.append(weekly_reset)
    if monthly_exhausted and monthly_reset:
        reset_candidates.append(monthly_reset)

    if not reset_candidates:
        if primary_reset:
            reset_candidates.append(primary_reset)
        if weekly_reset:
            reset_candidates.append(weekly_reset)
        if monthly_reset:
            reset_candidates.append(monthly_reset)

    resets_at = max(reset_candidates) if reset_candidates else int(time.time() + 18000)

    if primary_exhausted and weekly_exhausted:
        window = "combined"
    elif weekly_exhausted:
        window = "weekly"
    elif primary_exhausted:
        window = "primary"
    elif monthly_exhausted:
        window = "monthly"
    else:
        window = "limit"

    return {
        "window": window,
        "resets_at": resets_at,
        "quota_info": quota_info,
        "limit_reached": bool(limit_reached),
    }


def _int_or_none(value):
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _quota_reset_at(window: dict, *, checked_at: int) -> int | None:
    reset_at = _int_or_none((window or {}).get("reset_at"))
    if reset_at:
        return reset_at
    reset_after = _int_or_none((window or {}).get("reset_after_seconds"))
    if reset_after is not None:
        return checked_at + max(0, reset_after)
    return None


def _quota_window_label(window: dict, fallback: str) -> str:
    seconds = _int_or_none((window or {}).get("limit_window_seconds"))
    if seconds == 18000:
        return "primary"
    if seconds == 604800:
        return "weekly"
    if seconds == 2592000:
        return "monthly"
    return fallback


def _normalize_wham_usage_quota(data: dict, *, checked_at: int | None = None) -> dict:
    checked_at = int(checked_at or time.time())
    payload = data if isinstance(data, dict) else {}
    rate_limit = payload.get("rate_limit") or {}
    if not isinstance(rate_limit, dict):
        rate_limit = {}

    quota_info = {
        "plan_type": str(payload.get("plan_type") or "").strip().lower(),
        "allowed": bool(rate_limit.get("allowed")) if "allowed" in rate_limit else None,
        "limit_reached": bool(rate_limit.get("limit_reached")),
        "rate_limit_reached_type": payload.get("rate_limit_reached_type"),
        "checked_at": checked_at,
        "windows": {},
    }

    for source_key, fallback_label in (("primary_window", "primary"), ("secondary_window", "weekly")):
        window = rate_limit.get(source_key) or {}
        if not isinstance(window, dict) or not window:
            continue
        label = _quota_window_label(window, fallback_label)
        used_percent = window.get("used_percent")
        reset_at = _quota_reset_at(window, checked_at=checked_at)
        limit_seconds = _int_or_none(window.get("limit_window_seconds"))
        reset_after = _int_or_none(window.get("reset_after_seconds"))
        normalized_window = {
            "source": source_key,
            "used_percent": used_percent,
            "reset_at": reset_at,
            "reset_after_seconds": reset_after,
            "limit_window_seconds": limit_seconds,
        }
        quota_info["windows"][label] = normalized_window
        if label in {"primary", "weekly", "monthly"}:
            quota_info[f"{label}_pct"] = used_percent
            quota_info[f"{label}_resets_at"] = reset_at
            quota_info[f"{label}_window_seconds"] = limit_seconds
            quota_info[f"{label}_reset_after_seconds"] = reset_after

    return quota_info


def check_codex_quota(access_token, account_id=None, *, timeout=30):
    """
    通过 /backend-api/wham/usage 查询 Codex 额度状态，不消耗额度。
    返回:
        ("ok", quota_info)         — HTTP 200 + 成功解析,额度未触发上限
        ("exhausted", info)        — HTTP 200 + quota 用尽(get_quota_exhausted_info 命中)
        ("auth_error", None)       — **仅** HTTP 401/403,token/seat 真失效
        ("network_error", None)    — DNS/timeout/SSL/连接异常 / 5xx / 429 / json 解析失败 / 其他临时错误

    auth_error 与 network_error 必须严格区分:auth_error 会触发"标记 AUTH_INVALID/重登"等
    破坏性流程,网络抖动绝不能落入该分支(否则一次网络故障可能批量误删账号)。
    quota_info 按 limit_window_seconds 归类：primary=5h(18000s)、weekly=7天(604800s)、monthly=30天(2592000s)，并保留 plan_type
    """
    import requests

    if not account_id:
        account_id = get_chatgpt_account_id()

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    if account_id:
        headers["Chatgpt-Account-Id"] = account_id

    try:
        resp = requests.get(
            "https://chatgpt.com/backend-api/wham/usage",
            headers=headers,
            timeout=timeout,
        )
    except (
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.SSLError,
    ) as e:
        logger.warning("[Codex] 网络异常(归类 network_error): %s", e)
        return "network_error", None
    except requests.exceptions.RequestException as e:
        # 其他 requests 异常(ChunkedEncodingError 等)同样归为 network_error,而不是 auth_error
        logger.warning("[Codex] requests 异常(归类 network_error): %s", e)
        return "network_error", None
    except Exception as e:
        # 兜底:未知异常宁可归 network_error,避免因为一次网络抖动批量误标 AUTH_INVALID
        logger.warning("[Codex] 未知异常(归类 network_error,保守处理): %s", e)
        return "network_error", None

    if resp.status_code in (401, 403):
        return "auth_error", None

    # 429 限流 / 5xx 服务端错误 → 临时性故障,归为 network_error,不动账号 status
    if resp.status_code == 429 or 500 <= resp.status_code < 600:
        logger.warning("[Codex] wham/usage 临时错误 %d(归类 network_error): %s", resp.status_code, resp.text[:200])
        return "network_error", None

    if resp.status_code != 200:
        # 4xx(非 401/403/429) 也归为 network_error:可能是 OpenAI 接口在调整,
        # 不能因为一次接口变更把全部账号误判 token 失效
        logger.warning("[Codex] wham/usage 非预期状态 %d(归类 network_error): %s", resp.status_code, resp.text[:200])
        return "network_error", None

    try:
        data = resp.json()
    except Exception as e:
        logger.warning("[Codex] wham/usage 响应 JSON 解析失败(归类 network_error): %s", e)
        return "network_error", None

    rate_limit = data.get("rate_limit") or {}
    quota_info = _normalize_wham_usage_quota(data)

    exhausted_info = get_quota_exhausted_info(quota_info, limit_reached=bool(rate_limit.get("limit_reached")))
    if exhausted_info:
        return "exhausted", exhausted_info

    return "ok", quota_info


def refresh_access_token(refresh_token):
    """刷新 access token"""
    import requests

    resp = requests.post(
        CODEX_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": CODEX_CLIENT_ID,
            "refresh_token": refresh_token,
            "scope": "openid profile email",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    if resp.status_code != 200:
        logger.error("[Codex] Token 刷新失败: %d", resp.status_code)
        return None

    data = resp.json()
    return {
        "access_token": data.get("access_token"),
        "refresh_token": data.get("refresh_token", refresh_token),
        "id_token": data.get("id_token", ""),
        "expires_in": data.get("expires_in", 3600),
    }
