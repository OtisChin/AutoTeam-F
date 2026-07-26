"""Account Codex login task routes."""

import json
import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import AliasChoices, BaseModel, Field

from autotoken.services.task_runtime import TASK_GROUP_OAUTH

ACCOUNT_LOGIN_BATCH_MAX_EMAILS = 1_000
ACCOUNT_LOGIN_BATCH_DEFAULT_CONCURRENCY = 10


class LoginAccountParams(BaseModel):
    email: str
    proxy_url: str | None = Field(None, validation_alias=AliasChoices("proxy_url", "proxyUrl"))
    proxy_pool: list[str] = Field(default_factory=list, validation_alias=AliasChoices("proxy_pool", "proxyPool"))
    proxy_pool_text: str = Field("", validation_alias=AliasChoices("proxy_pool_text", "proxyPoolText"))
    proxy_api_provider: str = Field("", validation_alias=AliasChoices("proxy_api_provider", "proxyApiProvider"))
    proxy_api_url: str = Field("", validation_alias=AliasChoices("proxy_api_url", "proxyApiUrl"))
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
    exclusive: bool = Field(True, validation_alias=AliasChoices("exclusive", "task_exclusive", "taskExclusive"))


class AccountEmailBatchParams(BaseModel):
    emails: list[str]
    proxy_url: str | None = Field(None, validation_alias=AliasChoices("proxy_url", "proxyUrl"))
    proxy_pool: list[str] = Field(default_factory=list, validation_alias=AliasChoices("proxy_pool", "proxyPool"))
    proxy_pool_text: str = Field("", validation_alias=AliasChoices("proxy_pool_text", "proxyPoolText"))
    proxy_api_provider: str = Field("", validation_alias=AliasChoices("proxy_api_provider", "proxyApiProvider"))
    proxy_api_url: str = Field("", validation_alias=AliasChoices("proxy_api_url", "proxyApiUrl"))
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


class MailAccountAuthSessionBatchParams(BaseModel):
    emails: list[str] = Field(default_factory=list)


def _oauth_login_kwargs(params: LoginAccountParams | AccountEmailBatchParams) -> dict[str, Any]:
    bind_phone = bool(getattr(params, "bind_phone", False))
    kwargs: dict[str, Any] = {
        "headless": False,
        "protocol_only": bool(params.protocol_only),
        # 绑定邮箱/绑定手机号是互斥关系；旧前端或手工 API 同时传 true 时，手机号绑定优先。
        "bind_email": bool(params.bind_email) and not bind_phone,
    }
    if bind_phone:
        kwargs["bind_phone"] = True
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


def create_account_login_router(
    *,
    start_task: Callable[..., dict[str, Any]],
    normalize_email: Callable[[str | None], str],
    is_main_account_email: Callable[[str | None], bool],
    build_oauth_proxy_selector: Callable[..., tuple[Callable[[], str], dict[str, Any]]],
    run_account_codex_login_once: Callable[..., dict[str, Any]],
    append_task_progress: Callable[[str | None, dict], Any],
    oauth_phone_required_result: Callable[[str, Exception], dict],
    oauth_phone_rate_limited_result: Callable[[str, Exception], dict],
    oauth_login_required_result: Callable[[str, Exception], dict],
    oauth_account_deactivated_result: Callable[[str, Exception], dict],
    task_result_error: type[Exception],
    logger: Any,
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
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        def _run(task_id: str = ""):
            from autotoken.auth.codex_auth import (
                CodexOAuthAccountDeactivated,
                CodexOAuthLoginRequired,
                CodexOAuthPhoneRateLimited,
                CodexOAuthPhoneRequired,
            )

            try:
                append_task_progress(
                    task_id,
                    {
                        "stage": "account_login",
                        "email": email,
                        "message": f"正在补登录 {email}",
                    },
                )
                selected_oauth_proxy = oauth_proxy_selector()
                if selected_oauth_proxy:
                    append_task_progress(
                        task_id,
                        {
                            "stage": "account_login_proxy_selected",
                            "email": email,
                            **oauth_proxy_meta,
                            "message": "OAuth 补登录已选择代理",
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
                return run_account_codex_login_once(email, acc, **login_kwargs)
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
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        def _run(task_id: str = ""):
            from autotoken.auth.codex_auth import (
                CodexOAuthAccountDeactivated,
                CodexOAuthLoginRequired,
                CodexOAuthPhoneRateLimited,
                CodexOAuthPhoneRequired,
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

            ok = []
            failed = []
            phone_required = []
            total = len(accounts_by_email)
            result_lock = threading.Lock()

            missing_mail_ids = [
                email for email, acc in accounts_by_email.items() if not acc.get("cloudmail_account_id")
            ]
            if missing_mail_ids:
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
                            accounts_by_email[email]["cloudmail_account_id"] = account_id
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

            def _run_one(index: int, email: str, acc: dict) -> dict:
                started_at = time.time()
                logger.info(
                    "[账号登录] 批量 worker 开始: email=%s index=%s/%s thread=%s",
                    email,
                    index,
                    total,
                    threading.current_thread().name,
                )
                append_task_progress(
                    task_id,
                    {
                        "stage": "account_login",
                        "email": email,
                        "current": index,
                        "total": total,
                        "ok": len(ok),
                        "failed": len(failed),
                        "message": f"正在补登录 {email} ({index}/{total})",
                    },
                )
                try:
                    selected_oauth_proxy = oauth_proxy_selector()
                    if selected_oauth_proxy:
                        append_task_progress(
                            task_id,
                            {
                                "stage": "account_login_proxy_selected",
                                "email": email,
                                "current": index,
                                "total": total,
                                **oauth_proxy_meta,
                                "message": "OAuth 补登录已选择代理",
                            },
                        )
                    login_kwargs: dict[str, Any] = _oauth_login_kwargs(params)
                    login_kwargs["progress_callback"] = lambda event: append_task_progress(
                        task_id,
                        {
                            **dict(event or {}),
                            "email": str((event or {}).get("email") or email),
                            "current": index,
                            "total": total,
                        },
                    )
                    if selected_oauth_proxy:
                        login_kwargs["proxy_url"] = selected_oauth_proxy
                    login_result = run_account_codex_login_once(email, acc, **login_kwargs)
                    logger.info(
                        "[账号登录] 批量 worker 成功: email=%s elapsed=%.1fs thread=%s",
                        email,
                        time.time() - started_at,
                        threading.current_thread().name,
                    )
                    return {"kind": "ok", "email": email, "index": index, "result": login_result}
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
                    logger.exception("[账号登录] 批量 worker 异常: email=%s elapsed=%.1fs", email, time.time() - started_at)
                    return {"kind": "failed", "email": email, "index": index, "error": str(exc), "exception": exc}

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
            with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="codex-oauth") as executor:
                future_map = {
                    executor.submit(_run_one, index, email, acc): (index, email)
                    for index, (email, acc) in enumerate(accounts_by_email.items(), start=1)
                }
                for future in as_completed(future_map):
                    item = future.result()
                    item_email = item["email"]
                    item_account = accounts_by_email.get(item_email) or {}
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
                                "message": f"补登录失败: {item_email}: {item['error']}",
                            },
                        )
                        exc = item.get("exception")
                        logger.error(
                            "[账号登录] 批量补登录失败: email=%s",
                            item_email,
                            exc_info=(type(exc), exc, getattr(exc, "__traceback__", None)) if exc else None,
                        )

            return {
                "ok": ok,
                "failed": failed,
                "phone_required": phone_required,
                "missing": missing,
                "total": total,
                "concurrency": max_workers,
            }

        return start_task(
            "login-batch",
            _run,
            {"emails": emails, "missing": missing},
            task_group=TASK_GROUP_OAUTH,
            pass_task_id=True,
        )

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
