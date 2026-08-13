"""Account Codex login task routes."""

import json
import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import AliasChoices, BaseModel, Field

from autotoken.core.redaction import safe_error_summary
from autotoken.services.task_runtime import TASK_GROUP_OAUTH

ACCOUNT_LOGIN_BATCH_MAX_EMAILS = 1_000
ACCOUNT_LOGIN_BATCH_DEFAULT_CONCURRENCY = 10
ACCOUNT_LOGIN_BATCH_FRAUD_GUARD_ABORT_THRESHOLD = 2
ACCOUNT_LOGIN_OAUTH_PROXY_PREFLIGHT_ATTEMPTS = 5


def _oauth_fraud_guard_abort_threshold() -> int:
    try:
        return max(
            0,
            int(
                os.environ.get(
                    "CODEX_OAUTH_FRAUD_GUARD_ABORT_THRESHOLD",
                    str(ACCOUNT_LOGIN_BATCH_FRAUD_GUARD_ABORT_THRESHOLD),
                )
                or str(ACCOUNT_LOGIN_BATCH_FRAUD_GUARD_ABORT_THRESHOLD)
            ),
        )
    except (TypeError, ValueError):
        return ACCOUNT_LOGIN_BATCH_FRAUD_GUARD_ABORT_THRESHOLD


def _is_similar_phone_fraud_guard_error(message: str | None) -> bool:
    text = str(message or "").lower()
    return "fraud_guard" in text and "phone numbers similar" in text


def _oauth_proxy_preflight_attempt_limit() -> int:
    try:
        return max(
            1,
            min(
                100,
                int(
                    os.environ.get(
                        "OAUTH_PROXY_PREFLIGHT_ATTEMPTS",
                        str(ACCOUNT_LOGIN_OAUTH_PROXY_PREFLIGHT_ATTEMPTS),
                    )
                    or str(ACCOUNT_LOGIN_OAUTH_PROXY_PREFLIGHT_ATTEMPTS)
                ),
            ),
        )
    except (TypeError, ValueError):
        return ACCOUNT_LOGIN_OAUTH_PROXY_PREFLIGHT_ATTEMPTS


def _is_retryable_oauth_proxy_error(message: str | None) -> bool:
    text = str(message or "").lower()
    if "未返回可用代理" in text or "no proxy" in text:
        return True
    if any(
        marker in text
        for marker in (
            "oauth 页面临时错误",
            "not valid json",
            "unexpected token '<'",
            'unexpected token "<"',
            "<!doctype",
        )
    ):
        return True
    if "403" not in text:
        return False
    return any(marker in text for marker in ("cloudflare", "challenge", "just a moment", "access denied", "html_challenge"))


class LoginAccountParams(BaseModel):
    email: str
    proxy_url: str | None = Field(None, validation_alias=AliasChoices("proxy_url", "proxyUrl"))
    proxy_pool: list[str] = Field(default_factory=list, validation_alias=AliasChoices("proxy_pool", "proxyPool"))
    proxy_pool_text: str = Field("", validation_alias=AliasChoices("proxy_pool_text", "proxyPoolText"))
    proxy_api_provider: str = Field("", validation_alias=AliasChoices("proxy_api_provider", "proxyApiProvider"))
    proxy_api_url: str = Field("", validation_alias=AliasChoices("proxy_api_url", "proxyApiUrl"))
    proxy_api_country: str = Field("US", validation_alias=AliasChoices("proxy_api_country", "proxyApiCountry"))
    proxy_bypass: str | None = Field(None, validation_alias=AliasChoices("proxy_bypass", "proxyBypass"))
    protocol_only: bool = Field(True, validation_alias=AliasChoices("protocol_only", "protocolOnly"))
    bind_email: bool = Field(True, validation_alias=AliasChoices("bind_email", "bindEmail"))
    bind_phone: bool = Field(False, validation_alias=AliasChoices("bind_phone", "bindPhone"))
    mail_provider: str = Field("", validation_alias=AliasChoices("mail_provider", "mailProvider"))
    luckmail_email_type: str = Field("", validation_alias=AliasChoices("luckmail_email_type", "luckmailEmailType"))
    luckmail_preferred_domain: str = Field(
        "",
        validation_alias=AliasChoices("luckmail_preferred_domain", "luckmailPreferredDomain"),
    )
    email_domain: str = Field("", validation_alias=AliasChoices("email_domain", "emailDomain", "domain"))
    oauth_phone_sms_provider: str = Field(
        "",
        validation_alias=AliasChoices("oauth_phone_sms_provider", "oauthPhoneSmsProvider", "phone_provider", "phoneProvider"),
    )
    oauth_phone_sms_country: str = Field(
        "",
        validation_alias=AliasChoices("oauth_phone_sms_country", "oauthPhoneSmsCountry", "phone_country", "phoneCountry"),
    )
    oauth_phone_sms_max_price: str = Field(
        "",
        validation_alias=AliasChoices("oauth_phone_sms_max_price", "oauthPhoneSmsMaxPrice"),
    )
    oauth_oasis_sms_cdks: str = Field(
        "",
        validation_alias=AliasChoices("oauth_oasis_sms_cdks", "oauthOasisSmsCdks", "oasis_sms_cdks", "oasisSmsCdks"),
    )
    refresh_auth_session: bool = Field(False, validation_alias=AliasChoices("refresh_auth_session", "refreshAuthSession"))
    oauth_browser_mode: str = Field(
        "",
        validation_alias=AliasChoices("oauth_browser_mode", "oauthBrowserMode", "browser_mode", "browserMode"),
    )
    exclusive: bool = Field(True, validation_alias=AliasChoices("exclusive", "task_exclusive", "taskExclusive"))


class AccountEmailBatchParams(BaseModel):
    emails: list[str]
    proxy_url: str | None = Field(None, validation_alias=AliasChoices("proxy_url", "proxyUrl"))
    proxy_pool: list[str] = Field(default_factory=list, validation_alias=AliasChoices("proxy_pool", "proxyPool"))
    proxy_pool_text: str = Field("", validation_alias=AliasChoices("proxy_pool_text", "proxyPoolText"))
    proxy_api_provider: str = Field("", validation_alias=AliasChoices("proxy_api_provider", "proxyApiProvider"))
    proxy_api_url: str = Field("", validation_alias=AliasChoices("proxy_api_url", "proxyApiUrl"))
    proxy_api_country: str = Field("US", validation_alias=AliasChoices("proxy_api_country", "proxyApiCountry"))
    proxy_bypass: str | None = Field(None, validation_alias=AliasChoices("proxy_bypass", "proxyBypass"))
    protocol_only: bool = Field(True, validation_alias=AliasChoices("protocol_only", "protocolOnly"))
    bind_email: bool = Field(True, validation_alias=AliasChoices("bind_email", "bindEmail"))
    bind_phone: bool = Field(False, validation_alias=AliasChoices("bind_phone", "bindPhone"))
    mail_provider: str = Field("", validation_alias=AliasChoices("mail_provider", "mailProvider"))
    luckmail_email_type: str = Field("", validation_alias=AliasChoices("luckmail_email_type", "luckmailEmailType"))
    luckmail_preferred_domain: str = Field(
        "",
        validation_alias=AliasChoices("luckmail_preferred_domain", "luckmailPreferredDomain"),
    )
    email_domain: str = Field("", validation_alias=AliasChoices("email_domain", "emailDomain", "domain"))
    oauth_phone_sms_provider: str = Field(
        "",
        validation_alias=AliasChoices("oauth_phone_sms_provider", "oauthPhoneSmsProvider", "phone_provider", "phoneProvider"),
    )
    oauth_phone_sms_country: str = Field(
        "",
        validation_alias=AliasChoices("oauth_phone_sms_country", "oauthPhoneSmsCountry", "phone_country", "phoneCountry"),
    )
    oauth_phone_sms_max_price: str = Field(
        "",
        validation_alias=AliasChoices("oauth_phone_sms_max_price", "oauthPhoneSmsMaxPrice"),
    )
    oauth_oasis_sms_cdks: str = Field(
        "",
        validation_alias=AliasChoices("oauth_oasis_sms_cdks", "oauthOasisSmsCdks", "oasis_sms_cdks", "oasisSmsCdks"),
    )
    refresh_auth_session: bool = Field(False, validation_alias=AliasChoices("refresh_auth_session", "refreshAuthSession"))
    oauth_browser_mode: str = Field(
        "",
        validation_alias=AliasChoices("oauth_browser_mode", "oauthBrowserMode", "browser_mode", "browserMode"),
    )


class AccountEmailBatchAppendParams(BaseModel):
    emails: list[str]
    task_id: str = Field("", validation_alias=AliasChoices("task_id", "taskId"))


class MailAccountAuthSessionBatchParams(BaseModel):
    emails: list[str] = Field(default_factory=list)


def _oauth_login_kwargs(params: LoginAccountParams | AccountEmailBatchParams) -> dict[str, Any]:
    bind_phone = bool(getattr(params, "bind_phone", False))
    oauth_browser_mode = str(getattr(params, "oauth_browser_mode", "") or "").strip().lower()
    use_roxybrowser = oauth_browser_mode in {"roxy", "roxybrowser", "roxy-browser"}
    kwargs: dict[str, Any] = {
        "headless": False,
        "protocol_only": False if use_roxybrowser else bool(params.protocol_only),
        # 绑定邮箱/绑定手机号是互斥关系；旧前端或手工 API 同时传 true 时，手机号绑定优先。
        "bind_email": bool(params.bind_email) and not bind_phone,
    }
    if bind_phone:
        kwargs["bind_phone"] = True
    if bool(getattr(params, "refresh_auth_session", False)):
        kwargs["refresh_auth_session"] = True
    if use_roxybrowser:
        kwargs["use_roxybrowser"] = True
    text_fields = {
        "mail_provider": params.mail_provider,
        "luckmail_email_type": params.luckmail_email_type,
        "luckmail_preferred_domain": params.luckmail_preferred_domain,
        "email_domain": params.email_domain,
        "oauth_phone_sms_provider": params.oauth_phone_sms_provider,
        "oauth_phone_sms_country": params.oauth_phone_sms_country,
        "oauth_phone_sms_max_price": params.oauth_phone_sms_max_price,
        "oauth_oasis_sms_cdks": params.oauth_oasis_sms_cdks,
        "proxy_bypass": params.proxy_bypass,
    }
    for key, value in text_fields.items():
        cleaned = str(value or "").strip()
        if cleaned:
            kwargs[key] = cleaned
    return kwargs



def _apply_stored_totp_secret(login_kwargs: dict[str, Any], email: str) -> None:
    try:
        from autotoken.storage.accounts import get_totp_credentials

        totp_credentials = get_totp_credentials(email)
        if totp_credentials and totp_credentials.get("secret"):
            login_kwargs["totp_secret"] = str(totp_credentials.get("secret") or "")
    except Exception:
        pass


def relogin_account_auth_session_once(email: str, acc: dict, **kwargs: Any) -> dict[str, Any]:
    from autotoken.services.account_auth_session_relogin import relogin_account_auth_session_once as _relogin

    return _relogin(email, acc, **kwargs)


def _account_has_codex_auth_file(acc: dict) -> bool:
    auth_file = str((acc or {}).get("auth_file") or "").strip()
    return bool(auth_file)


def create_account_login_router(
    *,
    start_task: Callable[..., dict[str, Any]],
    normalize_email: Callable[[str | None], str],
    is_main_account_email: Callable[[str | None], bool],
    build_oauth_proxy_selector: Callable[..., tuple[Callable[[], str], dict[str, Any]]],
    preflight_oauth_proxy_url: Callable[..., tuple[bool, str]],
    run_account_codex_login_once: Callable[..., dict[str, Any]],
    append_task_progress: Callable[[str | None, dict], Any],
    oauth_phone_required_result: Callable[[str, Exception], dict],
    oauth_phone_rate_limited_result: Callable[[str, Exception], dict],
    oauth_login_required_result: Callable[[str, Exception], dict],
    oauth_account_deactivated_result: Callable[[str, Exception], dict],
    task_result_error: type[Exception],
    logger: Any,
    current_oauth_task: Callable[[], dict | None] | None = None,
    init_oauth_batch_control: Callable[[str, list[str]], Any] | None = None,
    append_oauth_batch_emails: Callable[[str, list[str]], dict[str, Any]] | None = None,
    drain_oauth_batch_emails: Callable[[str, set[str]], list[str]] | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/accounts/login", status_code=202)
    def post_account_login(params: LoginAccountParams):
        """触发单个账号的 Codex 登录（后台执行）"""
        from autotoken.storage.accounts import find_account, load_accounts

        email = params.email.strip().lower()
        if is_main_account_email(email):
            raise HTTPException(status_code=400, detail="主号不属于账号池登录对象")
        accounts = load_accounts()
        acc = find_account(accounts, email)
        if not acc:
            raise HTTPException(status_code=404, detail="账号不存在")
        try:
            oauth_proxy_selector, oauth_proxy_meta = build_oauth_proxy_selector(
                proxy_url=params.proxy_url,
                proxy_pool=params.proxy_pool,
                proxy_pool_text=params.proxy_pool_text,
                proxy_api_provider=params.proxy_api_provider,
                proxy_api_url=params.proxy_api_url,
                proxy_api_country=params.proxy_api_country,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        plain_relogin = (
            bool(params.refresh_auth_session)
            and not _account_has_codex_auth_file(acc)
            and str(params.oauth_browser_mode or "").strip().lower() not in {"roxy", "roxybrowser", "roxy-browser"}
        )
        oauth_proxy_api_enabled = bool(oauth_proxy_meta.get("proxy_api_url_present")) or int(
            oauth_proxy_meta.get("proxy_pool_count") or 0
        ) > 0
        oauth_proxy_attempts = _oauth_proxy_preflight_attempt_limit() if oauth_proxy_api_enabled else 1

        def _run(task_id: str = ""):
            from autotoken.auth.codex_auth import (
                CodexOAuthAccountDeactivated,
                CodexOAuthLoginRequired,
                CodexOAuthPhoneRateLimited,
                CodexOAuthPhoneRequired,
                CodexOAuthTransientPageError,
            )

            def _resolve_oauth_proxy_or_raise(proxy_attempt: int) -> str:
                try:
                    selected_proxy = oauth_proxy_selector()
                except Exception as exc:
                    selected_proxy = ""
                    if oauth_proxy_api_enabled:
                        last_error = f"OAuth 代理 API 未返回可用代理: {safe_error_summary(exc, limit=120)}"
                        append_task_progress(
                            task_id,
                            {
                                "stage": "account_login_proxy_preflight_failed",
                                "email": email,
                                **oauth_proxy_meta,
                                "proxy_attempt": proxy_attempt,
                                "proxy_attempts": oauth_proxy_attempts,
                                "message": last_error,
                                "level": "warn",
                            },
                        )
                        raise RuntimeError(last_error) from exc
                    return ""
                if not selected_proxy:
                    if oauth_proxy_api_enabled:
                        raise RuntimeError("OAuth 代理 API 未返回可用代理")
                    return ""
                if not oauth_proxy_api_enabled:
                    return selected_proxy

                ok, message = preflight_oauth_proxy_url(
                    selected_proxy,
                    email=email,
                    proxy_api_provider=oauth_proxy_meta.get("proxy_api_provider") or "",
                )
                if ok:
                    return selected_proxy

                last_error = str(message or "OAuth 代理预检失败")
                append_task_progress(
                    task_id,
                    {
                        "stage": "account_login_proxy_preflight_failed",
                        "email": email,
                        **oauth_proxy_meta,
                        "proxy_attempt": proxy_attempt,
                        "proxy_attempts": oauth_proxy_attempts,
                        "proxy_url": selected_proxy,
                        "message": last_error,
                        "level": "warn",
                    },
                )
                logger.warning(
                    "[账号登录] OAuth 代理预检失败: email=%s attempt=%s/%s error=%s",
                    email,
                    proxy_attempt,
                    oauth_proxy_attempts,
                    last_error,
                )
                raise RuntimeError(f"OAuth 代理预检失败: {last_error}")

            try:
                append_task_progress(
                    task_id,
                    {
                        "stage": "account_login",
                        "email": email,
                        "message": f"正在补登录 {email}",
                    },
                )
                last_error = ""
                for proxy_attempt in range(1, oauth_proxy_attempts + 1):
                    try:
                        selected_oauth_proxy = _resolve_oauth_proxy_or_raise(proxy_attempt)
                        if selected_oauth_proxy:
                            append_task_progress(
                                task_id,
                                {
                                    "stage": "account_login_proxy_selected",
                                    "email": email,
                                    **oauth_proxy_meta,
                                    "proxy_attempt": proxy_attempt,
                                    "proxy_attempts": oauth_proxy_attempts,
                                    "message": "OAuth 补登录已选择并预检通过代理",
                                },
                            )
                        elif oauth_proxy_meta.get("proxy_api_url_present"):
                            append_task_progress(
                                task_id,
                                {
                                    "stage": "account_login_proxy_unavailable",
                                    "email": email,
                                    **oauth_proxy_meta,
                                    "message": "OAuth 代理 API 未返回可用代理，本次将直连",
                                    "level": "warn",
                                },
                            )
                        login_kwargs: dict[str, Any] = _oauth_login_kwargs(params)
                        login_kwargs["progress_callback"] = lambda event: append_task_progress(
                            task_id,
                            {
                                **dict(event or {}),
                                "email": str((event or {}).get("email") or email),
                            },
                        )
                        if selected_oauth_proxy:
                            login_kwargs["proxy_url"] = selected_oauth_proxy
                        _apply_stored_totp_secret(login_kwargs, email)
                        if plain_relogin:
                            login_kwargs.pop("refresh_auth_session", None)
                            login_kwargs.pop("protocol_only", None)
                            login_kwargs.pop("bind_email", None)
                            login_kwargs.pop("bind_phone", None)
                            return relogin_account_auth_session_once(
                                email,
                                acc,
                                **login_kwargs,
                            )
                        if (
                            bool(params.refresh_auth_session)
                            and _account_has_codex_auth_file(acc)
                            and not bool(login_kwargs.get("use_roxybrowser"))
                        ):
                            login_kwargs["protocol_only"] = True
                        return run_account_codex_login_once(email, acc, **login_kwargs)
                    except Exception as exc:
                        last_error = safe_error_summary(exc, limit=220)
                        if (
                            oauth_proxy_api_enabled
                            and proxy_attempt < oauth_proxy_attempts
                            and (
                                isinstance(exc, CodexOAuthTransientPageError)
                                or _is_retryable_oauth_proxy_error(last_error)
                            )
                        ):
                            append_task_progress(
                                task_id,
                                {
                                    "stage": "account_login_proxy_retry",
                                    "email": email,
                                    **oauth_proxy_meta,
                                    "proxy_attempt": proxy_attempt,
                                    "proxy_attempts": oauth_proxy_attempts,
                                    "message": f"OAuth 代理遇到可重试错误，重试下一条代理: {last_error}",
                                    "level": "warn",
                                },
                            )
                            logger.warning(
                                "[账号登录] OAuth 代理遇到可重试错误，切换下一条代理: email=%s attempt=%s/%s error=%s",
                                email,
                                proxy_attempt,
                                oauth_proxy_attempts,
                                last_error,
                            )
                            continue
                        if oauth_proxy_api_enabled and (
                            _is_retryable_oauth_proxy_error(last_error)
                            or "OAuth 代理预检失败" in last_error
                            or "OAuth 代理 API" in last_error
                        ):
                            raise RuntimeError(f"OAuth 代理预检失败: {last_error}") from exc
                        raise
            except CodexOAuthPhoneRequired as exc:
                result = oauth_phone_required_result(email, exc)
                append_task_progress(
                    task_id,
                    {
                        "stage": "account_login_phone_required",
                        "email": email,
                        "removed_pool_emails": result["removed_pool_emails"],
                        "message": result["message"],
                        "level": "warn",
                    },
                )
                raise task_result_error(result["message"], task_result=result) from exc
            except CodexOAuthPhoneRateLimited as exc:
                result = oauth_phone_rate_limited_result(email, exc)
                append_task_progress(
                    task_id,
                    {
                        "stage": "account_login_phone_rate_limited",
                        "email": email,
                        "message": result["message"],
                        "level": "warn",
                    },
                )
                raise task_result_error(result["message"], task_result=result) from exc
            except CodexOAuthLoginRequired as exc:
                result = oauth_login_required_result(email, exc)
                append_task_progress(
                    task_id,
                    {
                        "stage": "account_login_required",
                        "email": email,
                        "message": result["message"],
                        "level": "warn",
                    },
                )
                raise task_result_error(result["message"], task_result=result) from exc
            except CodexOAuthAccountDeactivated as exc:
                result = oauth_account_deactivated_result(email, exc)
                append_task_progress(
                    task_id,
                    {
                        "stage": "account_login_deactivated_removed",
                        "email": email,
                        "removed_pool_emails": result["removed_pool_emails"],
                        "message": result["message"],
                        "level": "warn",
                    },
                )
                raise task_result_error(result["message"], task_result=result) from exc

        return start_task(
            f"login:{email}",
            _run,
            {"email": email},
            task_group=TASK_GROUP_OAUTH,
            pass_task_id=True,
            exclusive=bool(params.exclusive),
        )

    @router.post("/api/accounts/login-batch", status_code=202)
    def post_accounts_login_batch(params: AccountEmailBatchParams):
        """批量触发账号 Codex 补登录（后台并发执行）。"""
        from autotoken.storage.accounts import find_account, load_accounts

        if len(params.emails or []) > ACCOUNT_LOGIN_BATCH_MAX_EMAILS:
            raise HTTPException(status_code=400, detail=f"批量补登录账号过多，最多支持 {ACCOUNT_LOGIN_BATCH_MAX_EMAILS} 个")
        emails = []
        seen = set()
        for item in params.emails or []:
            email = normalize_email(item)
            if email and email not in seen:
                seen.add(email)
                emails.append(email)
        if not emails:
            raise HTTPException(status_code=400, detail="emails 不能为空")
        if any(is_main_account_email(email) for email in emails):
            raise HTTPException(status_code=400, detail="主号不属于账号池登录对象")

        account_list = load_accounts()
        accounts_by_email = {}
        missing = []
        for email in emails:
            acc = find_account(account_list, email)
            if not acc:
                missing.append(email)
                continue
            accounts_by_email[email] = acc
        if not accounts_by_email:
            raise HTTPException(status_code=404, detail="账号不存在")
        try:
            oauth_proxy_selector, oauth_proxy_meta = build_oauth_proxy_selector(
                proxy_url=params.proxy_url,
                proxy_pool=params.proxy_pool,
                proxy_pool_text=params.proxy_pool_text,
                proxy_api_provider=params.proxy_api_provider,
                proxy_api_url=params.proxy_api_url,
                proxy_api_country=params.proxy_api_country,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        plain_relogin = bool(params.refresh_auth_session) and str(params.oauth_browser_mode or "").strip().lower() not in {
            "roxy",
            "roxybrowser",
            "roxy-browser",
        }
        oauth_proxy_api_enabled = bool(oauth_proxy_meta.get("proxy_api_url_present")) or int(
            oauth_proxy_meta.get("proxy_pool_count") or 0
        ) > 0
        oauth_proxy_attempts = _oauth_proxy_preflight_attempt_limit() if oauth_proxy_api_enabled else 1

        def _run(task_id: str = ""):
            from autotoken.auth.codex_auth import (
                CodexOAuthAccountDeactivated,
                CodexOAuthLoginRequired,
                CodexOAuthPhoneRateLimited,
                CodexOAuthPhoneRequired,
                CodexOAuthTransientPageError,
            )
            from autotoken.storage.accounts import update_account

            def _persist_mailcom_login_failure(item_email: str, account: dict[str, Any], kind: str, message: str) -> None:
                provider = str(params.mail_provider or account.get("mail_provider") or "").strip().lower()
                if provider != "mail.com":
                    return
                try:
                    from autotoken.storage import mail_accounts

                    mail_accounts.mark_mailcom_login_failure(
                        item_email,
                        message,
                        check_status="invalid" if kind in {"account_deactivated", "login_required"} else "error",
                    )
                except Exception as exc:
                    logger.warning("[账号登录] 持久化 mail.com 登录失败状态失败: email=%s error=%s", item_email, exc)

            def _refresh_token_from_login_result(result: Any) -> str:
                if not isinstance(result, dict):
                    return ""
                candidates = [
                    result.get("refresh_token"),
                    result.get("refreshToken"),
                    (result.get("bundle") or {}).get("refresh_token") if isinstance(result.get("bundle"), dict) else "",
                    (result.get("codex_oauth_bundle") or {}).get("refresh_token")
                    if isinstance(result.get("codex_oauth_bundle"), dict)
                    else "",
                ]
                for candidate in candidates:
                    token = str(candidate or "").strip()
                    if token:
                        return token

                auth_file = str(result.get("auth_file") or result.get("authFile") or "").strip()
                if not auth_file:
                    return ""
                try:
                    path = Path(auth_file)
                    if not path.is_absolute():
                        path = Path.cwd() / path
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception as exc:
                    log_debug = getattr(logger, "debug", None)
                    if callable(log_debug):
                        log_debug("[账号登录] 读取 auth_file 提取 refresh_token 失败: file=%s error=%s", auth_file, exc)
                    return ""
                if not isinstance(data, dict):
                    return ""
                return str(data.get("refresh_token") or data.get("refreshToken") or "").strip()

            def _persist_mailcom_login_success(item_email: str, account: dict[str, Any], result: Any) -> None:
                provider = str(params.mail_provider or account.get("mail_provider") or "").strip().lower()
                if provider != "mail.com":
                    return
                refresh_token = _refresh_token_from_login_result(result)
                if not refresh_token:
                    return
                try:
                    from autotoken.storage import mail_accounts

                    mail_accounts.mark_mailcom_registered(
                        item_email,
                        gpt_password=str(account.get("password") or ""),
                        refresh_token=refresh_token,
                        source="account_login_success",
                    )
                except Exception as exc:
                    logger.warning("[账号登录] 同步 mail.com 登录成功 refreshToken 失败: email=%s error=%s", item_email, exc)

            if callable(init_oauth_batch_control):
                init_oauth_batch_control(task_id, list(accounts_by_email))

            ok = []
            failed = []
            phone_required = []
            skipped = []
            all_emails: list[str] = list(accounts_by_email)
            processed_emails: set[str] = set()
            total = len(all_emails)
            result_lock = threading.Lock()
            abort_event = threading.Event()
            abort_reason = ""
            consecutive_fraud_guard = 0
            fraud_guard_abort_threshold = _oauth_fraud_guard_abort_threshold()

            def _prefill_missing_mail_ids(target_accounts: dict[str, dict]) -> None:
                missing_mail_ids = [
                    email for email, acc in target_accounts.items() if not acc.get("cloudmail_account_id")
                ]
                if not missing_mail_ids:
                    return
                try:
                    from autotoken.mail import TemporaryEmailClient

                    mail_client = TemporaryEmailClient()
                    mail_client.login()
                    if hasattr(mail_client, "list_accounts"):
                        rows = mail_client.list_accounts(size=0)
                        by_email = {
                            normalize_email(row.get("email")): row.get("accountId")
                            for row in rows
                            if row.get("email") and row.get("accountId")
                        }
                        filled = 0
                        for email in missing_mail_ids:
                            account_id = by_email.get(email)
                            if not account_id:
                                continue
                            target_accounts[email]["cloudmail_account_id"] = account_id
                            update_account(email, cloudmail_account_id=account_id)
                            filled += 1
                        if filled:
                            append_task_progress(
                                task_id,
                                {
                                    "stage": "account_login_mail_ids_prefilled",
                                    "total": total,
                                    "filled": filled,
                                    "message": f"已预热 {filled} 个邮箱 accountId，后续验证码查询走直查",
                                },
                            )
                except Exception as exc:
                    logger.warning("[账号登录] 批量补登录预热 cloud-mail accountId 失败: %s", exc)

            _prefill_missing_mail_ids(accounts_by_email)

            def _run_one(index: int, email: str, acc: dict, current_total: int) -> dict:
                if abort_event.is_set():
                    return {"kind": "skipped", "email": email, "index": index, "reason": abort_reason or "批量任务已终止"}
                started_at = time.time()
                logger.info(
                    "[账号登录] 批量 worker 开始: email=%s index=%s/%s thread=%s",
                    email,
                    index,
                    current_total,
                    threading.current_thread().name,
                )
                append_task_progress(
                    task_id,
                    {
                        "stage": "account_login",
                        "email": email,
                        "current": index,
                        "total": current_total,
                        "ok": len(ok),
                        "failed": len(failed),
                        "message": f"正在补登录 {email} ({index}/{current_total})",
                    },
                )
                try:
                    last_error = ""

                    def _resolve_oauth_proxy_or_raise(proxy_attempt: int) -> str:
                        try:
                            selected_proxy = oauth_proxy_selector()
                        except Exception as exc:
                            selected_proxy = ""
                            if oauth_proxy_api_enabled:
                                last_error = f"OAuth 代理 API 未返回可用代理: {safe_error_summary(exc, limit=120)}"
                                append_task_progress(
                                    task_id,
                                    {
                                        "stage": "account_login_proxy_preflight_failed",
                                        "email": email,
                                        "current": index,
                                        "total": current_total,
                                        **oauth_proxy_meta,
                                        "proxy_attempt": proxy_attempt,
                                        "proxy_attempts": oauth_proxy_attempts,
                                        "message": last_error,
                                        "level": "warn",
                                    },
                                )
                                raise RuntimeError(last_error) from exc
                            return ""
                        if not selected_proxy:
                            if oauth_proxy_api_enabled:
                                raise RuntimeError("OAuth 代理 API 未返回可用代理")
                            return ""
                        if not oauth_proxy_api_enabled:
                            return selected_proxy

                        ok, message = preflight_oauth_proxy_url(
                            selected_proxy,
                            email=email,
                            proxy_api_provider=oauth_proxy_meta.get("proxy_api_provider") or "",
                        )
                        if ok:
                            return selected_proxy

                        last_error = str(message or "OAuth 代理预检失败")
                        append_task_progress(
                            task_id,
                            {
                                "stage": "account_login_proxy_preflight_failed",
                                "email": email,
                                "current": index,
                                "total": current_total,
                                **oauth_proxy_meta,
                                "proxy_attempt": proxy_attempt,
                                "proxy_attempts": oauth_proxy_attempts,
                                "proxy_url": selected_proxy,
                                "message": last_error,
                                "level": "warn",
                            },
                        )
                        logger.warning(
                            "[账号登录] OAuth 代理预检失败: email=%s attempt=%s/%s error=%s",
                            email,
                            proxy_attempt,
                            oauth_proxy_attempts,
                            last_error,
                        )
                        raise RuntimeError(f"OAuth 代理预检失败: {last_error}")

                    for proxy_attempt in range(1, oauth_proxy_attempts + 1):
                        try:
                            selected_oauth_proxy = _resolve_oauth_proxy_or_raise(proxy_attempt)
                            if selected_oauth_proxy:
                                append_task_progress(
                                    task_id,
                                    {
                                        "stage": "account_login_proxy_selected",
                                        "email": email,
                                        "current": index,
                                        "total": current_total,
                                        **oauth_proxy_meta,
                                        "proxy_attempt": proxy_attempt,
                                        "proxy_attempts": oauth_proxy_attempts,
                                        "message": "OAuth 补登录已选择并预检通过代理",
                                    },
                                )
                            elif oauth_proxy_meta.get("proxy_api_url_present"):
                                append_task_progress(
                                    task_id,
                                    {
                                        "stage": "account_login_proxy_unavailable",
                                        "email": email,
                                        "current": index,
                                        "total": current_total,
                                        **oauth_proxy_meta,
                                        "message": "OAuth 代理 API 未返回可用代理，本账号将直连",
                                        "level": "warn",
                                    },
                                )
                            login_kwargs: dict[str, Any] = _oauth_login_kwargs(params)
                            login_kwargs["progress_callback"] = lambda event: append_task_progress(
                                task_id,
                                {
                                    **dict(event or {}),
                                    "email": str((event or {}).get("email") or email),
                                    "current": index,
                                    "total": current_total,
                                },
                            )
                            if selected_oauth_proxy:
                                login_kwargs["proxy_url"] = selected_oauth_proxy
                            _apply_stored_totp_secret(login_kwargs, email)
                            if plain_relogin and not _account_has_codex_auth_file(acc):
                                login_kwargs.pop("refresh_auth_session", None)
                                login_kwargs.pop("protocol_only", None)
                                login_kwargs.pop("bind_email", None)
                                login_kwargs.pop("bind_phone", None)
                                login_result = relogin_account_auth_session_once(
                                    email,
                                    acc,
                                    **login_kwargs,
                                )
                            else:
                                if bool(params.refresh_auth_session) and _account_has_codex_auth_file(acc) and not bool(login_kwargs.get("use_roxybrowser")):
                                    login_kwargs["protocol_only"] = True
                                login_result = run_account_codex_login_once(email, acc, **login_kwargs)
                            logger.info(
                                "[账号登录] 批量 worker 成功: email=%s elapsed=%.1fs thread=%s",
                                email,
                                time.time() - started_at,
                                threading.current_thread().name,
                            )
                            return {"kind": "ok", "email": email, "index": index, "result": login_result}
                        except Exception as exc:
                            error_summary = safe_error_summary(exc, limit=220)
                            if (
                                oauth_proxy_api_enabled
                                and proxy_attempt < oauth_proxy_attempts
                                and (
                                    isinstance(exc, CodexOAuthTransientPageError)
                                    or _is_retryable_oauth_proxy_error(error_summary)
                                )
                            ):
                                append_task_progress(
                                    task_id,
                                    {
                                        "stage": "account_login_proxy_retry",
                                        "email": email,
                                        "current": index,
                                        "total": current_total,
                                        **oauth_proxy_meta,
                                        "proxy_attempt": proxy_attempt,
                                        "proxy_attempts": oauth_proxy_attempts,
                                        "message": f"OAuth 代理遇到可重试错误，重试下一条代理: {error_summary}",
                                        "level": "warn",
                                    },
                                )
                                logger.warning(
                                    "[账号登录] OAuth 代理遇到可重试错误，切换下一条代理: email=%s attempt=%s/%s error=%s",
                                    email,
                                    proxy_attempt,
                                    oauth_proxy_attempts,
                                    error_summary,
                                )
                                last_error = error_summary
                                continue
                            if oauth_proxy_api_enabled and (
                                _is_retryable_oauth_proxy_error(error_summary)
                                or "OAuth 代理预检失败" in error_summary
                                or "OAuth 代理 API" in error_summary
                            ):
                                raise RuntimeError(f"OAuth 代理预检失败: {error_summary}") from exc
                            raise
                except CodexOAuthPhoneRequired as exc:
                    result = oauth_phone_required_result(email, exc)
                    logger.warning("[账号登录] 批量 worker 手机验证: email=%s elapsed=%.1fs", email, time.time() - started_at)
                    return {"kind": "phone_required", "email": email, "index": index, "result": result}
                except CodexOAuthPhoneRateLimited as exc:
                    result = oauth_phone_rate_limited_result(email, exc)
                    logger.warning("[账号登录] 批量 worker 手机验证请求次数过多，跳过账号: email=%s elapsed=%.1fs", email, time.time() - started_at)
                    return {"kind": "phone_rate_limited", "email": email, "index": index, "result": result}
                except CodexOAuthLoginRequired as exc:
                    result = oauth_login_required_result(email, exc)
                    logger.warning("[账号登录] 批量 worker 停在登录页: email=%s elapsed=%.1fs", email, time.time() - started_at)
                    return {"kind": "login_required", "email": email, "index": index, "result": result}
                except CodexOAuthAccountDeactivated as exc:
                    result = oauth_account_deactivated_result(email, exc)
                    logger.warning("[账号登录] 批量 worker 账号停用: email=%s elapsed=%.1fs", email, time.time() - started_at)
                    return {"kind": "account_deactivated", "email": email, "index": index, "result": result}
                except Exception as exc:
                    error_summary = safe_error_summary(exc, limit=220)
                    logger.error(
                        "[账号登录] 批量 worker 异常: email=%s elapsed=%.1fs error=%s",
                        email,
                        time.time() - started_at,
                        error_summary,
                    )
                    return {"kind": "failed", "email": email, "index": index, "error": error_summary}

            try:
                configured_workers = int(
                    os.environ.get(
                        "CODEX_OAUTH_BATCH_CONCURRENCY",
                        str(ACCOUNT_LOGIN_BATCH_DEFAULT_CONCURRENCY),
                    )
                    or str(ACCOUNT_LOGIN_BATCH_DEFAULT_CONCURRENCY)
                )
            except (TypeError, ValueError):
                configured_workers = ACCOUNT_LOGIN_BATCH_DEFAULT_CONCURRENCY
            max_workers = max(1, min(total, configured_workers))
            logger.info("[账号登录] 批量补登录并发启动: total=%s max_workers=%s", total, max_workers)

            def _handle_completed_item(item: dict) -> None:
                nonlocal abort_reason, consecutive_fraud_guard, total
                item_email = item["email"]
                item_account = accounts_by_email.get(item_email) or {}
                if item["kind"] == "skipped":
                    reason = str(item.get("reason") or abort_reason or "批量任务已终止")
                    skipped.append({"email": item_email, "reason": reason})
                    append_task_progress(
                        task_id,
                        {
                            "stage": "account_login_batch_skipped",
                            "email": item_email,
                            "current": item["index"],
                            "total": total,
                            "ok": len(ok),
                            "failed": len(failed),
                            "message": f"批量补登录已终止，跳过: {item_email}",
                            "level": "warn",
                        },
                    )
                    return
                with result_lock:
                    if item["kind"] == "ok":
                        ok.append(item["result"])
                    elif item["kind"] in {"phone_required", "phone_rate_limited", "login_required", "account_deactivated"}:
                        if item["kind"] == "phone_required":
                            phone_required.append(item["result"])
                        failed.append(item["result"])
                    else:
                        failed.append({"email": item_email, "error": item["error"]})

                    ok_count = len(ok)
                    failed_count = len(failed)

                item_error_text = str(item.get("error") or "")
                if isinstance(item.get("result"), dict):
                    item_error_text = str(item["result"].get("message") or item_error_text)
                if _is_similar_phone_fraud_guard_error(item_error_text):
                    consecutive_fraud_guard += 1
                elif item["kind"] in {"ok", "phone_required", "login_required", "account_deactivated", "failed"}:
                    consecutive_fraud_guard = 0

                if (
                    fraud_guard_abort_threshold > 0
                    and consecutive_fraud_guard >= fraud_guard_abort_threshold
                    and not abort_event.is_set()
                ):
                    abort_reason = (
                        f"连续 {consecutive_fraud_guard} 个账号命中 OpenAI fraud_guard "
                        "（phone numbers similar），已终止整个批量补登录任务"
                    )
                    abort_event.set()
                    logger.warning("[账号登录] %s", abort_reason)
                    append_task_progress(
                        task_id,
                        {
                            "stage": "account_login_batch_aborted",
                            "email": item_email,
                            "current": item["index"],
                            "total": total,
                            "ok": ok_count,
                            "failed": failed_count,
                            "message": abort_reason,
                            "level": "error",
                        },
                    )

                if item["kind"] == "ok":
                    _persist_mailcom_login_success(item_email, item_account, item["result"])
                    append_task_progress(
                        task_id,
                        {
                            "stage": "account_login_done",
                            "email": item_email,
                            "current": item["index"],
                            "total": total,
                            "ok": ok_count,
                            "failed": failed_count,
                            "message": f"补登录成功: {item_email}",
                        },
                    )
                elif item["kind"] in {"phone_required", "phone_rate_limited", "login_required", "account_deactivated"}:
                    _persist_mailcom_login_failure(
                        item_email,
                        item_account,
                        item["kind"],
                        str(item["result"].get("message") or f"补登录失败: {item_email}"),
                    )
                    stage = {
                        "account_deactivated": "account_login_deactivated_removed",
                        "login_required": "account_login_required",
                        "phone_rate_limited": "account_login_phone_rate_limited",
                    }.get(item["kind"], "account_login_phone_required")
                    append_task_progress(
                        task_id,
                        {
                            "stage": stage,
                            "email": item_email,
                            "current": item["index"],
                            "total": total,
                            "ok": ok_count,
                            "failed": failed_count,
                            "removed_pool_emails": item["result"].get("removed_pool_emails") or [],
                            "message": item["result"].get("message") or f"OAuth 需要手机验证，已从号池删除账号: {item_email}",
                            "level": "warn",
                        },
                    )
                else:
                    _persist_mailcom_login_failure(item_email, item_account, item["kind"], str(item.get("error") or ""))
                    append_task_progress(
                        task_id,
                        {
                            "stage": "account_login_failed",
                            "email": item_email,
                            "current": item["index"],
                            "total": total,
                            "ok": ok_count,
                            "failed": failed_count,
                            "message": f"补登录失败: {item_email}: {safe_error_summary(item['error'], limit=220)}",
                        },
                    )
                    logger.error(
                        "[账号登录] 批量补登录失败: email=%s error=%s",
                        item_email,
                        safe_error_summary(item.get("error") or "", limit=220),
                    )

            def _load_appended_accounts() -> dict[str, dict]:
                nonlocal total
                if not callable(drain_oauth_batch_emails):
                    return {}
                appended = drain_oauth_batch_emails(task_id, set(all_emails))
                if not appended:
                    return {}
                account_list_latest = load_accounts()
                appended_accounts: dict[str, dict] = {}
                for email in appended:
                    if is_main_account_email(email) or email in set(all_emails):
                        continue
                    acc = find_account(account_list_latest, email)
                    if not acc:
                        missing.append(email)
                        continue
                    appended_accounts[email] = acc
                    accounts_by_email[email] = acc
                    all_emails.append(email)
                if appended_accounts:
                    total = len(all_emails)
                    _prefill_missing_mail_ids(appended_accounts)
                    append_task_progress(
                        task_id,
                        {
                            "stage": "account_login_batch_appended",
                            "total": total,
                            "added": len(appended_accounts),
                            "message": f"已追加 OAuth 补登录账号 {len(appended_accounts)} 个，当前总数 {total}",
                            "level": "success",
                        },
                    )
                return appended_accounts

            next_round: dict[str, dict] = dict(accounts_by_email)
            with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="codex-oauth") as executor:
                def _run_round(round_accounts: dict[str, dict]) -> None:
                    items = list(round_accounts.items())
                    next_index = len(processed_emails) + 1
                    cursor = 0
                    pending: dict[Any, tuple[int, str]] = {}

                    def submit_available() -> None:
                        nonlocal cursor, next_index
                        while not abort_event.is_set() and cursor < len(items) and len(pending) < max_workers:
                            email, acc = items[cursor]
                            index = next_index
                            cursor += 1
                            next_index += 1
                            pending[executor.submit(_run_one, index, email, acc, total)] = (index, email)

                    submit_available()
                    while pending:
                        done, _not_done = wait(pending, return_when=FIRST_COMPLETED)
                        for future in done:
                            pending.pop(future, None)
                            item = future.result()
                            processed_emails.add(item["email"])
                            _handle_completed_item(item)
                        if abort_event.is_set():
                            break
                        submit_available()

                    if abort_event.is_set():
                        for email, _acc in items[cursor:]:
                            processed_emails.add(email)
                            _handle_completed_item(
                                {
                                    "kind": "skipped",
                                    "email": email,
                                    "index": len(processed_emails),
                                    "reason": abort_reason or "批量任务已终止",
                                }
                            )
                        for future, (_index, email) in list(pending.items()):
                            if future.cancel():
                                processed_emails.add(email)
                                _handle_completed_item(
                                    {
                                        "kind": "skipped",
                                        "email": email,
                                        "index": len(processed_emails),
                                        "reason": abort_reason or "批量任务已终止",
                                    }
                                )
                            else:
                                item = future.result()
                                processed_emails.add(item["email"])
                                _handle_completed_item(item)

                while next_round:
                    round_accounts = next_round
                    next_round = {}
                    _run_round(round_accounts)
                    if abort_event.is_set():
                        break
                    next_round = _load_appended_accounts()

            return {
                "ok": ok,
                "failed": failed,
                "phone_required": phone_required,
                "missing": missing,
                "total": total,
                "concurrency": max_workers,
                "aborted": abort_event.is_set(),
                "abort_reason": abort_reason,
                "skipped": skipped,
            }

        task_params = {"emails": emails, "missing": missing}
        if bool(params.refresh_auth_session):
            task_params["refresh_auth_session"] = True
        return start_task(
            "login-batch",
            _run,
            task_params,
            task_group=TASK_GROUP_OAUTH,
            pass_task_id=True,
        )

    @router.post("/api/accounts/login-batch/append")
    def post_accounts_login_batch_append(params: AccountEmailBatchAppendParams):
        """向正在运行的 OAuth 批量补登录任务追加账号。"""
        from autotoken.storage.accounts import find_account, load_accounts

        if not callable(current_oauth_task) or not callable(append_oauth_batch_emails):
            raise HTTPException(status_code=409, detail="当前后端不支持追加 OAuth 批量任务")
        task = current_oauth_task() or {}
        if not task:
            raise HTTPException(status_code=404, detail="当前没有正在运行的 OAuth 批量任务")
        if str(task.get("command") or "") != "login-batch":
            raise HTTPException(status_code=409, detail="当前 OAuth 任务不是批量补登录任务，不能追加账号")
        requested_task_id = str(getattr(params, "task_id", "") or "").strip()
        task_id = str(requested_task_id or task.get("task_id") or "").strip()
        if requested_task_id and requested_task_id != str(task.get("task_id") or ""):
            raise HTTPException(status_code=404, detail="指定任务不是当前运行的 OAuth 批量任务")
        if len(params.emails or []) > ACCOUNT_LOGIN_BATCH_MAX_EMAILS:
            raise HTTPException(status_code=400, detail=f"追加账号过多，最多支持 {ACCOUNT_LOGIN_BATCH_MAX_EMAILS} 个")
        emails = []
        seen = set()
        for item in params.emails or []:
            email = normalize_email(item)
            if email and email not in seen:
                seen.add(email)
                emails.append(email)
        if not emails:
            raise HTTPException(status_code=400, detail="emails 不能为空")
        if any(is_main_account_email(email) for email in emails):
            raise HTTPException(status_code=400, detail="主号不属于账号池登录对象")

        account_list = load_accounts()
        appendable = []
        missing = []
        for email in emails:
            if find_account(account_list, email):
                appendable.append(email)
            else:
                missing.append(email)
        if not appendable:
            raise HTTPException(status_code=404, detail="账号不存在")

        result = append_oauth_batch_emails(task_id, appendable) or {}
        added = list(result.get("added_emails") or [])
        append_task_progress(
            task_id,
            {
                "stage": "account_login_batch_append_queued",
                "added": len(added),
                "missing": missing,
                "message": f"已追加 OAuth 补登录账号 {len(added)} 个" + (f"，跳过不存在账号 {len(missing)} 个" if missing else ""),
                "level": "success",
            },
        )
        return {
            "task_id": task_id,
            "added_emails": added,
            "duplicates": list(result.get("duplicates") or []),
            "missing": missing,
            "message": f"已追加 {len(added)} 个账号到当前 OAuth 批量任务",
        }

    @router.post("/api/mail-accounts/login-auth-session", status_code=202)
    def post_mail_accounts_login_auth_session(params: MailAccountAuthSessionBatchParams):
        """普通 ChatGPT 登录 mail.com 成品号，只保存 auth_session，不执行 OAuth 补登录。"""

        if len(params.emails or []) > ACCOUNT_LOGIN_BATCH_MAX_EMAILS:
            raise HTTPException(status_code=400, detail=f"批量登录账号过多，最多支持 {ACCOUNT_LOGIN_BATCH_MAX_EMAILS} 个")
        emails = []
        seen = set()
        for item in params.emails or []:
            email = normalize_email(item)
            if email and email not in seen:
                seen.add(email)
                emails.append(email)
        if not emails:
            raise HTTPException(status_code=400, detail="emails 不能为空")

        def _run(task_id: str = ""):
            from autotoken.services.mailcom_auth_session import login_mailcom_auth_session_once

            ok = []
            failed = []
            total = len(emails)
            for index, email in enumerate(emails, start=1):
                append_task_progress(
                    task_id,
                    {
                        "stage": "mail_account_auth_session_login",
                        "email": email,
                        "current": index,
                        "total": total,
                        "ok": len(ok),
                        "failed": len(failed),
                        "message": f"正在登陆 ChatGPT 获取 auth_session: {email} ({index}/{total})",
                    },
                )
                try:
                    result = login_mailcom_auth_session_once(
                        email,
                        progress_callback=lambda event, item_email=email, current=index: append_task_progress(
                            task_id,
                            {
                                **dict(event or {}),
                                "email": str((event or {}).get("email") or item_email),
                                "current": current,
                                "total": total,
                            },
                        ),
                    )
                    ok.append(result)
                    append_task_progress(
                        task_id,
                        {
                            "stage": "mail_account_auth_session_login_done",
                            "email": email,
                            "current": index,
                            "total": total,
                            "ok": len(ok),
                            "failed": len(failed),
                            "message": f"登陆成功，已保存 auth_session: {email}",
                        },
                    )
                except Exception as exc:
                    failed.append({"email": email, "error": str(exc)})
                    try:
                        from autotoken.storage import mail_accounts

                        mail_accounts.mark_mailcom_login_failure(email, str(exc))
                    except Exception as mark_exc:
                        logger.warning("[mail.com] 登陆失败状态写入失败: email=%s error=%s", email, mark_exc)
                    append_task_progress(
                        task_id,
                        {
                            "stage": "mail_account_auth_session_login_failed",
                            "email": email,
                            "current": index,
                            "total": total,
                            "ok": len(ok),
                            "failed": len(failed),
                            "message": f"登陆失败: {email}: {exc}",
                        },
                    )
            return {"ok": ok, "failed": failed, "total": total}

        return start_task(
            "mail-auth-session",
            _run,
            {"emails": emails},
            task_group=TASK_GROUP_OAUTH,
            pass_task_id=True,
        )

    return router
