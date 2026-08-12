"""Account Codex quota refresh task routes."""

import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from typing import Any

from fastapi import APIRouter, HTTPException

from autotoken.api_routes.account_login import AccountEmailBatchParams
from autotoken.storage.auth_files import read_auth_json_file, trusted_auth_or_session_path


def create_account_refresh_quota_router(
    *,
    start_task: Callable[..., dict[str, Any]],
    normalize_email: Callable[[str | None], str],
    is_main_account_email: Callable[[str | None], bool],
    resolve_status_auth_file: Callable[[dict], str | None],
    account_id_from_auth_data: Callable[[dict], str],
    append_task_progress: Callable[[str | None, dict], Any],
    task_group_quota: str,
    logger: Any,
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/accounts/refresh-quota", status_code=202)
    def post_accounts_refresh_quota(params: AccountEmailBatchParams):
        """刷新账号额度；emails 为空时默认刷新全部非主号账号，401 直接标记为废弃 Fail。"""
        from autotoken.storage.accounts import find_account, load_accounts

        emails = []
        seen = set()
        for item in params.emails or []:
            email = normalize_email(item)
            if email and email not in seen:
                seen.add(email)
                emails.append(email)

        account_list = load_accounts()
        if not emails:
            for acc in account_list:
                email = normalize_email(acc.get("email"))
                if (
                    email
                    and email not in seen
                    and not is_main_account_email(email)
                    and str(acc.get("status") or "").strip().lower() != "fail"
                ):
                    seen.add(email)
                    emails.append(email)

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

        def _run(task_id: str = ""):
            from autotoken.auth.codex_auth import check_codex_quota, quota_result_quota_info, quota_result_resets_at
            from autotoken.storage.accounts import (
                ACCOUNT_TYPE_FREE,
                ACCOUNT_TYPE_PLUS,
                ACCOUNT_TYPE_PRO,
                ACCOUNT_TYPE_TEAM,
                STATUS_ACTIVE,
                STATUS_AUTH_INVALID,
                STATUS_EXHAUSTED,
                STATUS_FAIL,
                STATUS_PERSONAL,
                STATUS_PLUS,
                STATUS_STASHED,
                STATUS_STANDBY,
                update_account,
            )

            ok = []
            exhausted = []
            failed = []
            skipped = []
            network_error = []
            total = len(accounts_by_email)
            completed = 0
            progress_lock = threading.Lock()

            def _int_env(name: str, default: int, *, minimum: int = 0, maximum: int = 9999) -> int:
                try:
                    value = int(os.environ.get(name, str(default)) or default)
                except (TypeError, ValueError):
                    value = default
                return max(minimum, min(maximum, value))

            def _account_type_from_quota_info(info: dict | None) -> str:
                if not isinstance(info, dict):
                    return ""
                plan_type = str(info.get("plan_type") or "").strip().lower()
                if plan_type in {ACCOUNT_TYPE_FREE, ACCOUNT_TYPE_PLUS, ACCOUNT_TYPE_PRO, ACCOUNT_TYPE_TEAM}:
                    return plan_type
                if plan_type in {"business", "enterprise", "edu"}:
                    return ACCOUNT_TYPE_TEAM
                return ""

            def _existing_paid_plan(current_account_type: str, current_last_quota: dict | None = None) -> str:
                normalized_account_type = str(current_account_type or "").strip().lower()
                if normalized_account_type in {ACCOUNT_TYPE_PLUS, ACCOUNT_TYPE_PRO, ACCOUNT_TYPE_TEAM}:
                    return normalized_account_type
                quota_plan = _account_type_from_quota_info(current_last_quota)
                if quota_plan in {ACCOUNT_TYPE_PLUS, ACCOUNT_TYPE_PRO, ACCOUNT_TYPE_TEAM}:
                    return quota_plan
                return ""

            def _is_token_expired_quota_failure(acc: dict | None) -> bool:
                if not isinstance(acc, dict):
                    return False
                if str(acc.get("discarded_reason") or "").strip().lower() != "quota_refresh_401":
                    return False
                message = str(acc.get("last_bind_message") or "").strip().lower()
                return "token_expired" in message

            def _is_token_revoked_quota_failure(acc: dict | None) -> bool:
                if not isinstance(acc, dict):
                    return False
                if str(acc.get("discarded_reason") or "").strip().lower() != "quota_refresh_401":
                    return False
                message = str(acc.get("last_bind_message") or "").strip().lower()
                return (
                    "token_revoked" in message
                    or "token_invalidated" in message
                    or "authentication token has been invalidated" in message
                    or "invalidated oauth token" in message
                )

            def _clear_quota_401_discard_marker(update_payload: dict, acc: dict | None) -> None:
                if not isinstance(acc, dict):
                    return
                if str(acc.get("discarded_reason") or "").strip().lower() != "quota_refresh_401":
                    return
                update_payload.update(
                    {
                        "discarded_at": None,
                        "discarded_reason": "",
                        "last_bind_status": "",
                        "last_bind_failure_stage": "",
                        "last_bind_message": "",
                    }
                )

            def _apply_plan_type(
                update_payload: dict,
                info: dict | None,
                *,
                current_account_type: str = "",
                current_last_quota: dict | None = None,
                allow_free_downgrade: bool = False,
            ) -> None:
                next_account_type = _account_type_from_quota_info(info)
                if not next_account_type:
                    return
                existing_paid_plan = _existing_paid_plan(current_account_type, current_last_quota)
                if next_account_type == ACCOUNT_TYPE_FREE and existing_paid_plan and not allow_free_downgrade:
                    update_payload["account_type"] = existing_paid_plan
                    if isinstance(update_payload.get("last_quota"), dict):
                        update_payload["last_quota"] = _quota_with_subscription_plan(
                            update_payload["last_quota"],
                            existing_paid_plan,
                        )
                    return
                update_payload["account_type"] = next_account_type

            def _quota_plan_type(info: dict | None) -> str:
                return _account_type_from_quota_info(info)

            def _has_primary_or_weekly_quota_window(info: dict | None) -> bool:
                if not isinstance(info, dict):
                    return False
                windows = info.get("windows") if isinstance(info.get("windows"), dict) else {}
                for label, seconds in (("primary", 18000), ("weekly", 604800)):
                    window = windows.get(label)
                    if isinstance(window, dict):
                        try:
                            if int(window.get("limit_window_seconds") or 0) == seconds:
                                return True
                        except (TypeError, ValueError):
                            return True
                    if info.get(f"{label}_pct") is not None:
                        return True
                return False

            def _looks_like_free_monthly_quota(info: dict | None) -> bool:
                if not isinstance(info, dict):
                    return False
                if _quota_plan_type(info) != ACCOUNT_TYPE_FREE:
                    return False
                if _has_primary_or_weekly_quota_window(info):
                    return False
                windows = info.get("windows") if isinstance(info.get("windows"), dict) else {}
                return isinstance(windows.get("monthly"), dict) or info.get("monthly_pct") is not None

            def _subscription_account_type(access_token: str, account_id: str) -> tuple[str, bool]:
                if not access_token or not account_id:
                    return "", False
                try:
                    from autotoken.api_routes.account_overview import (
                        normalize_chatgpt_subscription,
                        query_chatgpt_subscription,
                    )

                    result = query_chatgpt_subscription(access_token, account_id=account_id)
                    normalized = normalize_chatgpt_subscription(result.get("raw") or {}, account_id=account_id)
                except Exception as exc:
                    logger.debug("[刷新额度] 订阅接口校验账号类型失败: account_id=%s error=%s", account_id, exc)
                    return "", False
                plan_type = _account_type_from_quota_info({"plan_type": normalized.get("plan_type")})
                if not plan_type:
                    return "", True
                if normalized.get("active") is False and normalized.get("paid") is False:
                    return ACCOUNT_TYPE_FREE, True
                return plan_type, True

            def _quota_with_subscription_plan(info: dict | None, plan_type: str) -> dict | None:
                if not isinstance(info, dict) or plan_type not in {ACCOUNT_TYPE_PLUS, ACCOUNT_TYPE_PRO, ACCOUNT_TYPE_TEAM}:
                    return info
                patched = deepcopy(info)
                patched["plan_type"] = plan_type
                if _has_primary_or_weekly_quota_window(patched):
                    return patched

                windows = patched.setdefault("windows", {})
                if not isinstance(windows, dict):
                    windows = {}
                    patched["windows"] = windows
                monthly = windows.get("monthly") if isinstance(windows.get("monthly"), dict) else {}
                used_percent = monthly.get("used_percent") if monthly else patched.get("monthly_pct")
                if used_percent is None:
                    return patched

                weekly_window = {
                    "source": "primary_window",
                    "used_percent": used_percent,
                    "reset_at": None,
                    "reset_after_seconds": None,
                    "limit_window_seconds": 604800,
                }
                windows["weekly"] = weekly_window
                patched["weekly_pct"] = used_percent
                patched["weekly_resets_at"] = None
                patched["weekly_window_seconds"] = 604800
                patched["weekly_reset_after_seconds"] = None
                return patched

            def _align_free_monthly_quota_with_subscription(
                *,
                access_token: str,
                account_id: str,
                info: dict | None,
                auth_data: dict,
                existing_paid_plan: str = "",
            ) -> tuple[dict | None, bool]:
                if not _looks_like_free_monthly_quota(info):
                    return info, False
                subscription_plan, subscription_confirmed = _subscription_account_type(access_token, account_id)
                if subscription_plan == ACCOUNT_TYPE_FREE and subscription_confirmed:
                    return info, True
                if subscription_plan not in {ACCOUNT_TYPE_PLUS, ACCOUNT_TYPE_PRO, ACCOUNT_TYPE_TEAM}:
                    if existing_paid_plan:
                        return _quota_with_subscription_plan(info, existing_paid_plan), False
                    return info, False

                retry_status, retry_info = check_codex_quota(
                    access_token,
                    account_id=account_id or None,
                    timeout=account_timeout,
                    auth_data=auth_data,
                )
                if retry_status == "ok" and isinstance(retry_info, dict):
                    retry_plan = _quota_plan_type(retry_info)
                    if retry_plan in {ACCOUNT_TYPE_PLUS, ACCOUNT_TYPE_PRO, ACCOUNT_TYPE_TEAM} or _has_primary_or_weekly_quota_window(
                        retry_info
                    ):
                        return _quota_with_subscription_plan(retry_info, retry_plan or subscription_plan), False

                return _quota_with_subscription_plan(info, subscription_plan), False

            def _align_paid_account_with_subscription(
                *,
                access_token: str,
                account_id: str,
                info: dict | None,
                current_account_type: str,
            ) -> tuple[dict | None, bool]:
                if current_account_type not in {ACCOUNT_TYPE_PLUS, ACCOUNT_TYPE_PRO, ACCOUNT_TYPE_TEAM}:
                    return info, False
                subscription_plan, subscription_confirmed = _subscription_account_type(access_token, account_id)
                if subscription_plan == ACCOUNT_TYPE_FREE and subscription_confirmed:
                    patched = deepcopy(info) if isinstance(info, dict) else {}
                    patched["plan_type"] = ACCOUNT_TYPE_FREE
                    return patched, True
                return info, False

            def _access_token_from_auth_data(auth_data: dict) -> str:
                data = auth_data.get("data") if isinstance(auth_data.get("data"), dict) else {}
                return str(
                    auth_data.get("access_token")
                    or auth_data.get("accessToken")
                    or auth_data.get("chatgpt_access_token")
                    or data.get("access_token")
                    or data.get("accessToken")
                    or data.get("chatgpt_access_token")
                    or ""
                ).strip()

            def _account_id_from_auth_data(auth_data: dict) -> str:
                account = auth_data.get("account") if isinstance(auth_data.get("account"), dict) else {}
                data = auth_data.get("data") if isinstance(auth_data.get("data"), dict) else {}
                data_account = data.get("account") if isinstance(data.get("account"), dict) else {}
                return str(
                    account_id_from_auth_data(auth_data)
                    or auth_data.get("accountId")
                    or account.get("id")
                    or data.get("account_id")
                    or data.get("accountId")
                    or data_account.get("id")
                    or ""
                ).strip()

            max_workers = min(total, _int_env("REFRESH_QUOTA_CONCURRENCY", 8, minimum=1, maximum=32))
            retry_count = _int_env("REFRESH_QUOTA_RETRIES", 1, minimum=0, maximum=5)
            account_timeout = _int_env("REFRESH_QUOTA_ACCOUNT_TIMEOUT", 25, minimum=10, maximum=60)

            append_task_progress(
                task_id,
                {
                    "stage": "refresh_quota_started",
                    "current": 0,
                    "total": total,
                    "ok": 0,
                    "failed": 0,
                    "skipped": 0,
                    "network_error": 0,
                    "concurrency": max_workers,
                    "retry_count": retry_count,
                    "account_timeout": account_timeout,
                    "message": f"开始并发刷新额度: {total} 个账号，并发 {max_workers}，超时 {account_timeout}s，失败重试 {retry_count} 次",
                },
            )

            def _emit(progress: dict):
                with progress_lock:
                    append_task_progress(task_id, progress)

            def _run_one(index: int, email: str, acc: dict) -> dict:
                _emit(
                    {
                        "stage": "refresh_quota_account",
                        "email": email,
                        "current": completed,
                        "account_index": index,
                        "total": total,
                        "ok": len(ok),
                        "failed": len(failed),
                        "skipped": len(skipped),
                        "network_error": len(network_error),
                        "message": f"正在刷新账号额度: {email} ({index}/{total})",
                    }
                )
                if is_main_account_email(email):
                    return {
                        "kind": "skipped",
                        "email": email,
                        "index": index,
                        "reason": "main_account",
                        "message": f"跳过主账号: {email}",
                    }
                if (
                    str(acc.get("status") or "").strip().lower() == STATUS_FAIL
                    and not _is_token_expired_quota_failure(acc)
                    and not _is_token_revoked_quota_failure(acc)
                ):
                    return {
                        "kind": "skipped",
                        "email": email,
                        "index": index,
                        "reason": "fail_account",
                        "message": f"跳过废弃账号: {email}",
                    }

                auth_path = trusted_auth_or_session_path(resolve_status_auth_file(acc))
                if not auth_path:
                    return {
                        "kind": "skipped",
                        "email": email,
                        "index": index,
                        "reason": "missing_auth_file",
                        "message": f"跳过 {email}: 缺少认证文件",
                    }

                try:
                    auth_data = read_auth_json_file(auth_path)
                except Exception as exc:
                    return {
                        "kind": "skipped",
                        "email": email,
                        "index": index,
                        "reason": "invalid_auth_file",
                        "error": str(exc),
                        "message": f"跳过 {email}: 认证文件无法读取",
                    }

                access_token = _access_token_from_auth_data(auth_data)
                if not access_token:
                    return {
                        "kind": "skipped",
                        "email": email,
                        "index": index,
                        "reason": "missing_access_token",
                        "message": f"跳过 {email}: 认证文件缺少 access_token",
                    }

                now_ts = time.time()
                attempts = 0
                status = "network_error"
                info = None
                for attempt in range(retry_count + 1):
                    attempts = attempt + 1
                    status, info = check_codex_quota(
                        access_token,
                        account_id=_account_id_from_auth_data(auth_data) or None,
                        timeout=account_timeout,
                        auth_data=auth_data,
                    )
                    if status != "network_error" or attempt >= retry_count:
                        break
                    _emit(
                        {
                            "stage": "refresh_quota_retry",
                            "email": email,
                            "current": completed,
                            "account_index": index,
                            "total": total,
                            "attempt": attempts,
                            "retry_count": retry_count,
                            "message": f"刷新额度临时失败，准备重试: {email} ({attempts}/{retry_count + 1})",
                            "level": "warn",
                        },
                    )

                current_status = str(acc.get("status") or "").strip().lower()
                account_type = str(acc.get("account_type") or "").strip().lower()
                recoverable_free_statuses = {"", STATUS_ACTIVE, STATUS_EXHAUSTED, STATUS_PERSONAL, "pending", "session_only"}
                quota_preserved_statuses = {STATUS_PLUS, STATUS_STANDBY, STATUS_STASHED}

                if status == "ok":
                    account_id = _account_id_from_auth_data(auth_data)
                    info, allow_free_downgrade = _align_free_monthly_quota_with_subscription(
                        access_token=access_token,
                        account_id=account_id,
                        info=info,
                        auth_data=auth_data,
                        existing_paid_plan=_existing_paid_plan(account_type, acc.get("last_quota")),
                    )
                    if not allow_free_downgrade:
                        info, allow_free_downgrade = _align_paid_account_with_subscription(
                            access_token=access_token,
                            account_id=account_id,
                            info=info,
                            current_account_type=account_type,
                        )
                    update_payload = {"last_quota": info, "last_quota_check_at": now_ts}
                    _apply_plan_type(
                        update_payload,
                        info,
                        current_account_type=account_type,
                        current_last_quota=acc.get("last_quota"),
                        allow_free_downgrade=allow_free_downgrade,
                    )
                    effective_account_type = update_payload.get("account_type") or account_type
                    if effective_account_type == ACCOUNT_TYPE_FREE and current_status in recoverable_free_statuses:
                        update_payload["status"] = STATUS_PERSONAL
                    elif effective_account_type == ACCOUNT_TYPE_FREE and allow_free_downgrade:
                        update_payload["status"] = STATUS_PERSONAL
                    elif current_status not in quota_preserved_statuses:
                        update_payload["status"] = STATUS_ACTIVE
                    _clear_quota_401_discard_marker(update_payload, acc)
                    return {
                        "kind": "ok",
                        "email": email,
                        "index": index,
                        "quota": info,
                        "attempts": attempts,
                        "update": update_payload,
                        "message": f"额度刷新成功: {email}",
                    }

                if status == "exhausted":
                    quota_info = quota_result_quota_info(info) or {}
                    update_payload = {
                        "quota_exhausted_at": now_ts,
                        "quota_resets_at": quota_result_resets_at(info) or int(now_ts + 18000),
                        "last_quota_check_at": now_ts,
                    }
                    if quota_info:
                        update_payload["last_quota"] = quota_info
                    _apply_plan_type(
                        update_payload,
                        quota_info,
                        current_account_type=account_type,
                        current_last_quota=acc.get("last_quota"),
                    )
                    effective_account_type = update_payload.get("account_type") or account_type
                    is_free_personal_account = effective_account_type == ACCOUNT_TYPE_FREE
                    if is_free_personal_account:
                        if effective_account_type == ACCOUNT_TYPE_FREE and current_status in recoverable_free_statuses:
                            update_payload["status"] = STATUS_PERSONAL
                    elif current_status not in quota_preserved_statuses:
                        update_payload["status"] = STATUS_EXHAUSTED
                    _clear_quota_401_discard_marker(update_payload, acc)
                    return {
                        "kind": "exhausted",
                        "email": email,
                        "index": index,
                        "quota": quota_info,
                        "info": info,
                        "attempts": attempts,
                        "update": update_payload,
                        "message": (
                            f"个人 Free 额度已用完，仅记录额度快照: {email}"
                            if is_free_personal_account
                            else f"额度已用完: {email}"
                        ),
                    }

                if status == "auth_error":
                    auth_error_code = ""
                    auth_error_detail = ""
                    if isinstance(info, dict):
                        auth_error_code = str(info.get("code") or "").strip().lower()
                        auth_error_detail = str(
                            info.get("message") or info.get("error") or info.get("response_excerpt") or ""
                        ).strip()
                    elif info:
                        auth_error_detail = str(info).strip()
                    if auth_error_code == "token_expired" or auth_error_detail.lower().startswith("token_expired"):
                        return {
                            "kind": "network_error",
                            "email": email,
                            "index": index,
                            "reason": "token_expired",
                            "attempts": attempts,
                            "update": {
                                "status": STATUS_AUTH_INVALID,
                                "last_quota_check_at": now_ts,
                                "last_bind_status": "failed",
                                "last_bind_failure_stage": "auth_token_expired",
                                "last_bind_message": (
                                    f"刷新额度返回 {auth_error_detail}，账号需刷新 auth_session，未标记废弃"
                                    if auth_error_detail
                                    else "刷新额度返回 token_expired，账号需刷新 auth_session，未标记废弃"
                                ),
                            },
                            "message": (
                                f"刷新额度返回 token_expired，未标记废弃: {email}"
                                if not auth_error_detail
                                else f"刷新额度返回 {auth_error_detail}，未标记废弃: {email}"
                            ),
                        }
                    auth_error_detail_lower = auth_error_detail.lower()
                    if (
                        auth_error_code in {"token_revoked", "token_invalidated"}
                        or auth_error_detail_lower.startswith("token_revoked")
                        or auth_error_detail_lower.startswith("token_invalidated")
                        or "authentication token has been invalidated" in auth_error_detail_lower
                        or "invalidated oauth token" in auth_error_detail_lower
                    ):
                        reason = "token_invalidated" if auth_error_code == "token_invalidated" or auth_error_detail_lower.startswith("token_invalidated") else "token_revoked"
                        return {
                            "kind": "network_error",
                            "email": email,
                            "index": index,
                            "reason": reason,
                            "attempts": attempts,
                            "update": {
                                "status": "auth_revoked",
                                "last_quota_check_at": now_ts,
                                "last_bind_status": "failed",
                                "last_bind_failure_stage": "auth_token_revoked",
                                "last_bind_message": (
                                    f"刷新额度返回 {auth_error_detail}，账号掉授权，未标记废弃"
                                    if auth_error_detail
                                    else "刷新额度返回 token_revoked，账号掉授权，未标记废弃"
                                ),
                            },
                            "message": (
                                f"刷新额度返回 {reason}，账号掉授权，未标记废弃: {email}"
                                if not auth_error_detail
                                else f"刷新额度返回 {auth_error_detail}，账号掉授权，未标记废弃: {email}"
                            ),
                        }
                    auth_error_message = (
                        f"刷新额度返回 401: {auth_error_detail}，账号已标记为 Fail/废弃"
                        if auth_error_detail
                        else "刷新额度返回 401，账号已标记为 Fail/废弃"
                    )
                    update_payload = {
                        "status": STATUS_FAIL,
                        "discarded_at": now_ts,
                        "discarded_reason": "quota_refresh_401",
                        "last_quota_check_at": now_ts,
                        "last_bind_status": "failed",
                        "last_bind_failure_stage": "auth_401",
                        "last_bind_message": auth_error_message,
                    }
                    failed_item = {
                        "kind": "failed",
                        "email": email,
                        "index": index,
                        "reason": "auth_error",
                        "attempts": attempts,
                        "update": update_payload,
                        "message": (
                            f"刷新额度返回 401: {auth_error_detail}，已标记 Fail/废弃: {email}"
                            if auth_error_detail
                            else f"刷新额度返回 401，已标记 Fail/废弃: {email}"
                        ),
                    }
                    if auth_error_detail:
                        failed_item["error_detail"] = auth_error_detail
                    return failed_item

                return {
                    "kind": "network_error",
                    "email": email,
                    "index": index,
                    "reason": status,
                    "attempts": attempts,
                    "message": f"刷新额度遇到临时错误，未改状态: {email}",
                }

            with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="quota-refresh") as executor:
                future_map = {
                    executor.submit(_run_one, index, email, acc): (index, email)
                    for index, (email, acc) in enumerate(accounts_by_email.items(), start=1)
                }
                results_by_index = {}
                for future in as_completed(future_map):
                    index, email = future_map[future]
                    try:
                        item = future.result()
                    except Exception as exc:
                        item = {
                            "kind": "network_error",
                            "email": email,
                            "index": index,
                            "reason": "exception",
                            "error": str(exc),
                            "attempts": 1,
                            "message": f"刷新额度异常，未改状态: {email}: {exc}",
                        }
                        logger.exception("[刷新额度] worker 异常: email=%s", email)

                    results_by_index[index] = (item, email)

            for index in sorted(results_by_index):
                item, email = results_by_index[index]
                update_payload = item.get("update")
                update_email = item.get("email") or email
                if isinstance(update_payload, dict) and update_payload:
                    update_account(update_email, **update_payload)

                completed += 1
                kind = item.get("kind")
                if kind == "ok":
                    ok.append({"email": item["email"], "quota": item.get("quota"), "attempts": item.get("attempts", 1)})
                    stage = "refresh_quota_done"
                    level = "info"
                elif kind == "exhausted":
                    exhausted.append({"email": item["email"], "quota": item.get("quota") or {}, "info": item.get("info")})
                    stage = "refresh_quota_exhausted"
                    level = "warn"
                elif kind == "failed":
                    failed_item = {"email": item["email"], "reason": item.get("reason") or "failed"}
                    if item.get("error_detail"):
                        failed_item["error_detail"] = item.get("error_detail")
                    failed.append(failed_item)
                    stage = "refresh_quota_auth_failed"
                    level = "error"
                elif kind == "skipped":
                    skipped_item = {
                        "email": item["email"],
                        "reason": item.get("reason") or "skipped",
                    }
                    if item.get("error"):
                        skipped_item["error"] = item.get("error")
                    skipped.append(skipped_item)
                    stage = "refresh_quota_skipped"
                    level = "warn"
                else:
                    network_error.append({"email": item.get("email") or email, "reason": item.get("reason") or "network_error"})
                    stage = "refresh_quota_network_error"
                    level = "warn"

                append_task_progress(
                    task_id,
                    {
                        "stage": stage,
                        "email": item.get("email") or email,
                        "current": completed,
                        "account_index": item.get("index") or index,
                        "total": total,
                        "ok": len(ok),
                        "failed": len(failed),
                        "exhausted": len(exhausted),
                        "skipped": len(skipped),
                        "network_error": len(network_error),
                        "attempts": item.get("attempts", 1),
                        "message": item.get("message") or f"刷新额度完成: {email}",
                        "level": level,
                    },
                )

            return {
                "ok": ok,
                "exhausted": exhausted,
                "failed": failed,
                "skipped": skipped,
                "network_error": network_error,
                "missing": missing,
                "total": total,
                "concurrency": max_workers,
                "retry_count": retry_count,
                "account_timeout": account_timeout,
            }

        return start_task(
            "refresh-quota",
            _run,
            {"emails": emails, "missing": missing},
            task_group=task_group_quota,
            pass_task_id=True,
        )

    return router
