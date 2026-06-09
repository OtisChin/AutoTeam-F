"""Shared HTTP/session helpers for payment and checkout flows."""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

from autotoken.core.normalization import normalized_email
from autotoken.core.redaction import safe_proxy_summary as _safe_proxy_summary
from autotoken.settings.config import normalize_proxy_url
from autotoken.storage.auth_files import read_auth_json_file, trusted_auth_file_path

try:
    from curl_cffi.requests import Session as _CurlCffiSession  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    _CurlCffiSession = None  # type: ignore

logger = logging.getLogger(__name__)


class PaymentHttpError(RuntimeError):
    def __init__(self, message: str, stage: str = "payment_http"):
        super().__init__(message)
        self.stage = stage


def new_http_session(
    proxy_url: str | None = None,
    *,
    require_curl_cffi: bool = False,
    tls_impersonate_env: str = "GOPAY_TLS_IMPERSONATE",
) -> Any:
    if _CurlCffiSession is not None:
        session = _CurlCffiSession(impersonate=os.environ.get(tls_impersonate_env, "chrome136"))
        try:
            session._autotoken_transport = "curl_cffi"  # type: ignore[attr-defined]
        except Exception:
            pass
    else:
        if require_curl_cffi:
            raise PaymentHttpError(
                "ChatGPT checkout/approve 需要 curl-cffi 的 Chrome TLS 指纹；"
                "当前环境未安装 curl_cffi，请执行 `pip install curl-cffi` 或重新安装项目依赖后重试",
                stage="chatgpt_http_session",
            )
        session = requests.Session()
        try:
            session._autotoken_transport = "requests"  # type: ignore[attr-defined]
        except Exception:
            pass
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    normalized_proxy_url = normalize_proxy_url(proxy_url)
    if normalized_proxy_url.lower().startswith("socks5://"):
        normalized_proxy_url = f"socks5h://{normalized_proxy_url[len('socks5://') :]}"
    if normalized_proxy_url:
        logger.info("HTTP session proxy enabled: %s", _safe_proxy_summary(normalized_proxy_url))
        try:
            session.proxies = {"http": normalized_proxy_url, "https": normalized_proxy_url}
        except Exception:
            logger.exception("HTTP session proxy assignment failed")
    return session


def http_transport_name(http: Any) -> str:
    try:
        value = getattr(http, "_autotoken_transport", "")
        if value:
            return str(value)
    except Exception:
        pass
    module = http.__class__.__module__
    if module.startswith("curl_cffi"):
        return "curl_cffi"
    return "requests"


def response_json(resp, stage: str, *, error_factory=None) -> dict:
    try:
        data = resp.json()
    except Exception as exc:
        message = (
            f"{stage} 返回非 JSON: HTTP {getattr(resp, 'status_code', '?')} {(getattr(resp, 'text', '') or '')[:300]}"
        )
        if callable(error_factory):
            raise error_factory(message, stage) from exc
        raise PaymentHttpError(message, stage=stage) from exc
    return data if isinstance(data, dict) else {"_raw": data}


def load_chatgpt_auth_file_context(
    email: str,
    *,
    account_lookup=None,
    file_reader=None,
) -> dict[str, str]:
    """Load the local Codex/CPA auth file as a fallback ChatGPT token source."""
    normalized = normalized_email(email)
    if not normalized:
        return {}

    auth_file = ""
    try:
        if account_lookup is None:
            from autotoken.storage.accounts import find_account, load_accounts

            account = find_account(load_accounts(), normalized)
        else:
            account = account_lookup(normalized)
        if account:
            auth_file = str(account.get("auth_file") or "").strip()
    except Exception:
        auth_file = ""

    if not auth_file:
        return {}

    try:
        if file_reader is None:
            path = trusted_auth_file_path(auth_file)
            if not path:
                return {}
            data = read_auth_json_file(path)
            auth_file = str(path)
        else:
            data = file_reader(auth_file)
    except Exception:
        return {}

    if not isinstance(data, dict):
        return {}
    account_data = data.get("account") if isinstance(data.get("account"), dict) else {}
    user_data = data.get("user") if isinstance(data.get("user"), dict) else {}
    return {
        "access_token": str(data.get("access_token") or data.get("accessToken") or "").strip(),
        "account_id": str(
            data.get("account_id")
            or data.get("accountId")
            or account_data.get("id")
            or account_data.get("account_id")
            or user_data.get("account_id")
            or user_data.get("accountId")
            or ""
        ).strip(),
        "id_token": str(data.get("id_token") or data.get("idToken") or "").strip(),
        "auth_file": auth_file,
    }
