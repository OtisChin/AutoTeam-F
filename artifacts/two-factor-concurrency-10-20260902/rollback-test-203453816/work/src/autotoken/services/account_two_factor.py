"""Account-level protocol TOTP setup orchestration."""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterable
from typing import Any

from loguru import logger

from autotoken.core.normalization import normalized_email
from autotoken.mail.base import wait_for_openai_otp
from autotoken.services.chatgpt_2fa_protocol import ChatGPT2FAProtocolSetupExecutor
from autotoken.services.chatgpt_2fa_setup import ChatGPT2FASetupStatus
from autotoken.services.totp import TOTPSecretError, generate_totp


def account_two_factor_enabled(account: dict[str, Any] | None) -> bool:
    source = account or {}
    return bool(source.get("two_factor_enabled")) or str(source.get("totp_status") or "").lower() == "enabled"


def _deduplicated_emails(emails: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in emails:
        email = normalized_email(value)
        if not email or email in seen:
            continue
        seen.add(email)
        result.append(email)
    return result


def get_account_totp_view(
    email: str,
    *,
    credentials_loader: Callable[[str], dict[str, Any] | None] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Return the locally stored TOTP secret and current code for the dashboard view."""
    from autotoken.storage.accounts import get_totp_credentials

    normalized = normalized_email(email)
    if not normalized:
        raise ValueError("email 不能为空")

    load_credentials = credentials_loader or get_totp_credentials
    credentials = load_credentials(normalized)
    if not credentials or not credentials.get("secret"):
        raise LookupError("该账号没有本地保存的 2FA 密钥")

    secret = str(credentials.get("secret") or "").strip()
    period = int(credentials.get("period") or 30)
    digits = int(credentials.get("digits") or 6)
    timestamp = float(time.time() if now is None else now)
    try:
        code = generate_totp(secret, for_time=timestamp, period=period, digits=digits)
    except TOTPSecretError as exc:
        raise ValueError(str(exc)) from exc

    elapsed = int(timestamp) % period
    remaining = period - elapsed
    if remaining <= 0:
        remaining = period

    return {
        "email": normalized,
        "enabled": True,
        "secret": secret,
        "masked_secret": str(credentials.get("masked_secret") or ""),
        "code": code,
        "period": period,
        "remaining": remaining,
        "issuer": str(credentials.get("issuer") or ""),
        "factor_label": str(credentials.get("factor_label") or ""),
        "enabled_at": credentials.get("enabled_at"),
        "status": str(credentials.get("status") or "enabled"),
    }


def _default_mail_client_factory(account: dict[str, Any]):
    from autotoken.interfaces.manager import _temporary_mail_provider
    from autotoken.mail import TemporaryEmailClient

    provider = str(account.get("mail_provider") or "").strip().lower()
    with _temporary_mail_provider(provider):
        client = TemporaryEmailClient()
    if provider not in {"generic-api", "generic_api", "genericapi"} or not account.get("mailapi_url"):
        client.login()
    return client


def setup_accounts_two_factor_protocol(
    emails: Iterable[str],
    *,
    accounts_loader: Callable[[], list[dict[str, Any]]] | None = None,
    session_loader: Callable[[str], dict[str, Any]] | None = None,
    mail_client_factory: Callable[[dict[str, Any]], Any] | None = None,
    executor_factory: Callable[..., Any] | None = None,
    save_metadata: Callable[..., Any] | None = None,
    otp_waiter: Callable[..., str] | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Enable TOTP sequentially for existing accounts using saved protocol sessions."""
    from autotoken.storage.accounts import load_accounts, save_totp_metadata
    from autotoken.storage.auth_session_store import load_auth_session

    targets = _deduplicated_emails(emails)
    load_account_rows = accounts_loader or load_accounts
    load_session = session_loader or load_auth_session
    create_mail_client = mail_client_factory or _default_mail_client_factory
    create_executor = executor_factory or ChatGPT2FAProtocolSetupExecutor
    persist_metadata = save_metadata or save_totp_metadata
    wait_for_otp = otp_waiter or wait_for_openai_otp
    emit = progress if callable(progress) else lambda _event: None
    accounts_by_email = {
        normalized_email(account.get("email")): account
        for account in load_account_rows()
        if normalized_email(account.get("email"))
    }
    enabled: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    logger.info("[2FA] 协议设置开始：{} 个账号", len(targets))

    for index, email in enumerate(targets, start=1):
        logger.info("[2FA] 正在处理账号 {}/{}：{}", index, len(targets), email)
        emit(
            {
                "stage": "account_2fa_account_started",
                "email": email,
                "current": index,
                "total": len(targets),
                "message": f"正在设置 2FA：{email} ({index}/{len(targets)})",
            }
        )
        account = accounts_by_email.get(email)
        if account is None:
            logger.warning("[2FA] 账号不存在：{}", email)
            failed.append({"email": email, "reason": "account_not_found"})
            continue
        if account_two_factor_enabled(account):
            logger.info("[2FA] 跳过已设置账号：{}", email)
            skipped.append({"email": email, "reason": "already_enabled"})
            continue
        session_data = load_session(email)
        if not isinstance(session_data, dict) or not session_data:
            logger.warning("[2FA] 缺少协议会话：{}", email)
            failed.append({"email": email, "reason": "auth_session_missing"})
            continue

        try:
            mail_client = create_mail_client(account)
            account_id = account.get("cloudmail_account_id") or email
            used_codes: set[str] = set()

            def email_code_provider(
                _target: str,
                *,
                issued_after=None,
                exclude_codes=None,
                _mail_client=mail_client,
                _email=email,
                _account_id=account_id,
                _used_codes=used_codes,
            ) -> str:
                excluded = set(_used_codes)
                excluded.update(str(code or "").strip() for code in (exclude_codes or set()) if str(code or "").strip())
                code = str(
                    wait_for_otp(
                        _mail_client,
                        _email,
                        account_id=_account_id,
                        timeout=max(30, int(os.environ.get("OPENAI_EMAIL_OTP_TIMEOUT", "120") or "120")),
                        issued_after=issued_after,
                        exclude_codes=excluded,
                        strict_issued_after=True,
                    )
                    or ""
                ).strip()
                if code:
                    _used_codes.add(code)
                return code

            executor = create_executor(email_code_provider=email_code_provider, save_metadata=persist_metadata)
            result = executor.enable(email, session_data, progress=emit)
            public_result = result.to_public_dict()
            if result.status == ChatGPT2FASetupStatus.ENABLED:
                logger.info("[2FA] 设置成功：{}", email)
                enabled.append({"email": email, "two_factor": public_result})
            else:
                logger.warning(
                    "[2FA] 设置失败：{} reason={}",
                    email,
                    public_result.get("reason") or public_result.get("status") or "setup_failed",
                )
                failed.append(
                    {
                        "email": email,
                        "reason": str(public_result.get("reason") or public_result.get("status") or "setup_failed"),
                    }
                )
        except Exception as exc:
            logger.exception("[2FA] 设置异常：{}", email)
            failed.append({"email": email, "reason": str(exc)})
        finally:
            emit(
                {
                    "stage": "account_2fa_progress",
                    "email": email,
                    "current": index,
                    "total": len(targets),
                    "enabled": len(enabled),
                    "skipped": len(skipped),
                    "failed": len(failed),
                }
            )

    logger.info(
        "[2FA] 协议设置结束：total={} enabled={} skipped={} failed={}",
        len(targets),
        len(enabled),
        len(skipped),
        len(failed),
    )

    return {
        "total": len(targets),
        "enabled": enabled,
        "skipped": skipped,
        "failed": failed,
    }
