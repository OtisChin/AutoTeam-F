"""Plain ChatGPT relogin for account-pool rows.

This refreshes ChatGPT Web ``auth_session`` only.  It intentionally does not
create or update local Codex/CPA auth JSON because ChatGPT Web sessions do not
provide the Codex refresh_token required by CPA.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any


@contextmanager
def _temporary_env(overrides: dict[str, str]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in overrides}
    try:
        for key, value in overrides.items():
            os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _plain_login_env() -> dict[str, str]:
    return {
        "AUTH_SESSION_ONLY": "1",
        "SKIP_OAUTH_TOKEN_EXCHANGE": "1",
        "OAUTH_EXCHANGE_BEFORE_CALLBACK": "0",
        "OAUTH_CODEX_RT_BEFORE_CALLBACK": "0",
        "OAUTH_CODEX_RT_EXCHANGE": "0",
        "OAUTH_SECONDARY_AUTHORIZE_EXCHANGE": "0",
    }


def _auth_session_has_web_session(session_data: dict[str, Any] | None) -> bool:
    if not isinstance(session_data, dict):
        return False
    data = session_data.get("data") if isinstance(session_data.get("data"), dict) else session_data
    if not isinstance(data, dict):
        return False
    return bool(
        str(data.get("sessionToken") or data.get("session_token") or "").strip()
        or str(data.get("cookie_header") or "").strip()
        or str(data.get("accessToken") or data.get("access_token") or data.get("chatgpt_access_token") or "").strip()
    )


def _promote_auth_session_fields(session_data: dict[str, Any]) -> dict[str, Any]:
    """Expose commonly used auth_session fields at top level.

    Protocol login returns the refreshed ChatGPT Web session under ``data``.
    Dashboard actions such as 获取ac/订阅查询 also read auth_session files
    directly, so keep top-level aliases in sync with the nested payload.
    """

    if not isinstance(session_data, dict):
        return {}
    promoted = dict(session_data)
    data = promoted.get("data") if isinstance(promoted.get("data"), dict) else {}
    if not data:
        return promoted

    for top_key, nested_keys in {
        "accessToken": ("accessToken", "access_token", "chatgpt_access_token"),
        "access_token": ("access_token", "accessToken", "chatgpt_access_token"),
        "chatgpt_access_token": ("chatgpt_access_token", "access_token", "accessToken"),
        "sessionToken": ("sessionToken", "session_token"),
        "session_token": ("session_token", "sessionToken"),
        "refreshToken": ("refreshToken", "refresh_token"),
        "refresh_token": ("refresh_token", "refreshToken"),
        "idToken": ("idToken", "id_token"),
        "id_token": ("id_token", "idToken"),
        "accountId": ("accountId", "account_id"),
        "account_id": ("account_id", "accountId"),
        "device_id": ("device_id", "oai_device_id"),
        "oai_device_id": ("oai_device_id", "device_id"),
        "cookie_header": ("cookie_header",),
    }.items():
        if str(promoted.get(top_key) or "").strip():
            continue
        for nested_key in nested_keys:
            value = data.get(nested_key)
            if value not in (None, ""):
                promoted[top_key] = value
                break

    if not isinstance(promoted.get("account"), dict) and isinstance(data.get("account"), dict):
        promoted["account"] = dict(data["account"])
    if not isinstance(promoted.get("user"), dict) and isinstance(data.get("user"), dict):
        promoted["user"] = dict(data["user"])
    return promoted


def relogin_account_auth_session_once(
    email: str,
    account: dict,
    *,
    proxy_url: str | None = None,
    mail_provider: str | None = None,
    luckmail_email_type: str | None = None,
    luckmail_preferred_domain: str | None = None,
    email_domain: str | None = None,
    oauth_phone_sms_provider: str | None = None,
    oauth_phone_sms_country: str | None = None,
    oauth_phone_sms_max_price: str | None = None,
    oauth_oasis_sms_cdks: str | None = None,
    totp_secret: str | None = None,
    progress_callback: Callable[[dict], Any] | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Login ChatGPT normally and save auth_session only."""

    from autotoken.auth.protocol_register import login_once
    from autotoken.core.normalization import normalized_email
    from autotoken.mail import TemporaryEmailClient
    from autotoken.storage import auth_session_store
    from autotoken.storage.accounts import (
        ACCOUNT_SOURCE_MANAGED,
        SEAT_CODEX,
        STATUS_ACTIVE,
        STATUS_PENDING,
        STATUS_SESSION_ONLY,
        update_account,
    )

    normalized = normalized_email(email)
    if not normalized:
        raise ValueError("邮箱不能为空")
    password = str((account or {}).get("password") or "").strip()

    requested_mail_provider = str(mail_provider or "").strip().lower()
    account_mail_provider = str((account or {}).get("mail_provider") or "").strip().lower()
    effective_mail_provider = account_mail_provider or requested_mail_provider
    mail_provider_overrides = {}
    if effective_mail_provider == "luckmail":
        if luckmail_email_type:
            mail_provider_overrides["LUCKMAIL_EMAIL_TYPE"] = str(luckmail_email_type).strip()
        if luckmail_preferred_domain is not None:
            mail_provider_overrides["LUCKMAIL_PREFERRED_DOMAIN"] = str(luckmail_preferred_domain).strip().lstrip("@")

    try:
        from autotoken.interfaces.manager import _temporary_mail_provider
    except Exception:
        provider_context = _temporary_env({"MAIL_PROVIDER": effective_mail_provider}) if effective_mail_provider else _temporary_env({})
    else:
        provider_context = _temporary_mail_provider(effective_mail_provider, mail_provider_overrides)

    with provider_context:
        mail_client = TemporaryEmailClient()
        mail_client.login()
        if not (account or {}).get("cloudmail_account_id") and hasattr(mail_client, "_resolve_account_id"):
            try:
                resolved_mail_id = mail_client._resolve_account_id(normalized)
            except Exception:
                resolved_mail_id = None
            if resolved_mail_id:
                account["cloudmail_account_id"] = resolved_mail_id
                update_account(normalized, cloudmail_account_id=resolved_mail_id)

    with _temporary_env(_plain_login_env()):
        session_payload = login_once(
            mail_client,
            email=normalized,
            password=password,
            account_id=(account or {}).get("cloudmail_account_id") or normalized,
            proxy=str(proxy_url or "").strip() or None,
            oauth_phone_sms_provider=str(oauth_phone_sms_provider or "").strip() or None,
            oauth_phone_sms_country=str(oauth_phone_sms_country or "").strip() or None,
            oauth_phone_sms_max_price=str(oauth_phone_sms_max_price or "").strip() or None,
            oauth_oasis_sms_cdks=str(oauth_oasis_sms_cdks or "").strip() or None,
            totp_secret=totp_secret,
            progress_callback=progress_callback,
            auth_session_only=True,
        )

    if not _auth_session_has_web_session(session_payload):
        raise RuntimeError(f"补登录未返回有效 auth_session: {normalized}")

    session_payload = _promote_auth_session_fields(session_payload)
    auth_session_file = auth_session_store.save_auth_session(normalized, session_payload)
    current_status = str((account or {}).get("status") or "").strip().lower()
    update_fields: dict[str, Any] = {
        "password": password,
        "cloudmail_account_id": (account or {}).get("cloudmail_account_id"),
        "seat_type": (account or {}).get("seat_type") or SEAT_CODEX,
        "last_active_at": time.time(),
        "account_source": ACCOUNT_SOURCE_MANAGED,
    }
    if effective_mail_provider:
        update_fields["mail_provider"] = effective_mail_provider
    if current_status in {"", STATUS_PENDING, STATUS_SESSION_ONLY, "auth_invalid", "auth_revoked"}:
        update_fields["status"] = STATUS_ACTIVE
    update_account(normalized, **update_fields)

    result: dict[str, Any] = {
        "email": normalized,
        "status": "success",
        "auth_session_file": auth_session_file,
        "codex_auth_updated": False,
    }
    return result
