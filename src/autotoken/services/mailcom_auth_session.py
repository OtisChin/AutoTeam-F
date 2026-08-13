"""Plain ChatGPT auth_session login for finished mail.com accounts."""

from __future__ import annotations

import os
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


def _first_token(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def login_mailcom_auth_session_once(
    email: str,
    *,
    progress_callback: Callable[[dict], Any] | None = None,
) -> dict[str, Any]:
    """Login a finished ChatGPT account and save only ChatGPT auth_session.

    This is intentionally not Codex/OAuth "补登录". It logs in to ChatGPT with
    the stored GPT password, reads `/api/auth/session`, and stores the
    auth_session payload. A refresh token is accepted if the protocol happens to
    expose one, but absence of refresh_token is not an error.
    """

    from autotoken.auth.protocol_register import login_once
    from autotoken.core.normalization import normalized_email
    from autotoken.mail.mailcom import MailComMailProvider
    from autotoken.storage import accounts, auth_session_store, mail_accounts

    normalized = normalized_email(email)
    if not normalized:
        raise ValueError("邮箱不能为空")

    account = mail_accounts.get_mail_account(normalized)
    if not account:
        raise KeyError(normalized)
    password = str(account.get("gpt_password") or "").strip()
    if not password:
        raise ValueError("ChatGPT 密码不能为空")

    mail_client = MailComMailProvider()
    mail_client.login()
    env = {
        "AUTH_SESSION_ONLY": "1",
        "SKIP_OAUTH_TOKEN_EXCHANGE": "1",
        "OAUTH_EXCHANGE_BEFORE_CALLBACK": "0",
        "OAUTH_CODEX_RT_BEFORE_CALLBACK": "0",
        "OAUTH_CODEX_RT_EXCHANGE": "0",
        "OAUTH_SECONDARY_AUTHORIZE_EXCHANGE": "0",
    }
    with _temporary_env(env):
        session_payload = login_once(
            mail_client,
            email=normalized,
            password=password,
            account_id=normalized,
            totp_secret=((accounts.get_totp_credentials(normalized) or {}).get("secret") or None),
            progress_callback=progress_callback,
            auth_session_only=True,
        )

    auth_session_file = auth_session_store.save_auth_session(normalized, session_payload)
    try:
        from autotoken.storage.accounts import (
            SEAT_CODEX,
            STATUS_ACTIVE,
            STATUS_PENDING,
            STATUS_SESSION_ONLY,
            find_account,
            load_accounts,
            update_account,
        )

        existing = find_account(load_accounts(), normalized) or {}
        current_status = str(existing.get("status") or "").strip().lower()
        fields = {
            "password": password,
            "cloudmail_account_id": normalized,
            "mail_provider": "mail.com",
            "seat_type": existing.get("seat_type") or SEAT_CODEX,
        }
        if current_status in {"", STATUS_PENDING, STATUS_SESSION_ONLY}:
            fields["status"] = STATUS_ACTIVE
        update_account(normalized, **fields)
    except Exception:
        pass
    data = session_payload.get("data") if isinstance(session_payload, dict) else {}
    data = data if isinstance(data, dict) else {}
    refresh_token = _first_token(session_payload, "refresh_token", "refreshToken") or _first_token(
        data, "refresh_token", "refreshToken"
    )
    access_token = _first_token(session_payload, "access_token", "accessToken") or _first_token(
        data, "access_token", "accessToken", "chatgpt_access_token"
    )

    mail_accounts.mark_mailcom_registered(
        normalized,
        gpt_password=password,
        refresh_token=refresh_token,
        source="auth_session_login",
    )
    mail_accounts.update_check_result(
        normalized,
        check_status="valid",
        access_token=access_token,
        refresh_token=refresh_token,
        error="",
    )

    return {
        "email": normalized,
        "status": "success",
        "auth_session_file": auth_session_file,
        "refresh_token_present": bool(refresh_token),
    }
