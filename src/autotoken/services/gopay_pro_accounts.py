"""GoPay Pro account update and auth-file payload helpers."""

from __future__ import annotations

import time
from typing import Any

from autotoken.core.normalization import normalized_email
from autotoken.services.gopay_pro_pool import normalize_access_token


def success_account_update_fields(
    *,
    task_id: str,
    message: str,
    marked_at: float,
    auth_file: str,
    status_plus: str,
    account_type_plus: str,
    seat_codex: str,
    account_source_managed: str,
) -> dict[str, Any]:
    update_fields: dict[str, Any] = {
        "status": status_plus,
        "account_type": account_type_plus,
        "seat_type": seat_codex,
        "account_source": account_source_managed,
        "last_bind_status": "success",
        "last_bind_provider": "gopay_pro",
        "last_bind_at": marked_at,
        "last_bind_task_id": task_id,
        "last_bind_message": message or "GoPay Pro 绑定成功",
        "last_bind_failure_stage": "",
        "plus_bound_at": marked_at,
    }
    if auth_file:
        update_fields["auth_file"] = auth_file
    return update_fields


def failed_account_update_fields(
    *,
    task_id: str,
    status: str,
    message: str,
    failure_stage: str,
    marked_at: float,
) -> dict[str, Any]:
    return {
        "last_bind_status": status,
        "last_bind_provider": "gopay_pro",
        "last_bind_at": marked_at,
        "last_bind_task_id": task_id,
        "last_bind_message": message,
        "last_bind_failure_stage": failure_stage,
    }


def account_already_plus(account: dict[str, Any], *, status_plus: str, account_type_plus: str) -> bool:
    status = str((account or {}).get("status") or "").strip().lower()
    account_type = str((account or {}).get("account_type") or "").strip().lower()
    return status == str(status_plus or "").strip().lower() or account_type == str(account_type_plus or "").strip().lower()


def normalized_account_emails(values: list[str] | tuple[str, ...] | None) -> list[str]:
    emails: list[str] = []
    seen = set()
    for value in values or []:
        email = normalized_email(value)
        if not email or email in seen:
            continue
        seen.add(email)
        emails.append(email)
    return emails


def account_token_item(*, email: str, auth_data: dict[str, Any], auth_file: str) -> dict[str, str]:
    tokens = auth_data.get("tokens") if isinstance(auth_data.get("tokens"), dict) else {}
    access_token = normalize_access_token(
        auth_data.get("access_token") or auth_data.get("accessToken") or tokens.get("access_token") or ""
    )
    refresh_token = str(auth_data.get("refresh_token") or auth_data.get("refreshToken") or "").strip()
    account_id = str(auth_data.get("account_id") or auth_data.get("accountId") or "").strip()
    return {
        "email": str(email or "").strip(),
        "access_token": access_token,
        "refresh_token": refresh_token,
        "account_id": account_id,
        "auth_file": str(auth_file or "").strip(),
    }


def account_token_item_access_error(item: dict[str, str], seen_tokens: set[str]) -> str:
    email = str((item or {}).get("email") or "").strip()
    access_token = str((item or {}).get("access_token") or "").strip()
    if not access_token:
        return f"账号认证文件缺少 access_token: {email}"
    if access_token in seen_tokens:
        return f"账号 access_token 重复: {email}"
    return ""


def refreshed_auth_data(auth_data: dict[str, Any], refreshed: dict[str, Any], *, now: float) -> dict[str, Any]:
    next_data = dict(auth_data)
    access_token = normalize_access_token(refreshed.get("access_token") or "")
    refresh_token = str(refreshed.get("refresh_token") or "").strip()
    id_token = str(refreshed.get("id_token") or "").strip()
    if access_token:
        next_data["access_token"] = access_token
        next_data["accessToken"] = access_token
    if refresh_token:
        next_data["refresh_token"] = refresh_token
        next_data["refreshToken"] = refresh_token
    if id_token:
        next_data["id_token"] = id_token
        next_data["idToken"] = id_token
    expires_in = refreshed.get("expires_in")
    try:
        expires_at = now + max(0, int(expires_in or 0))
    except Exception:
        expires_at = 0
    if expires_at:
        next_data["expired"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(expires_at))
    next_data["last_refresh"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    return next_data


def usage_probe_missing_token_result() -> dict[str, str]:
    return {"status": "missing_token", "plan_type": "", "message": "缺少 access_token"}


def plus_plan_auth_file_read_error_result(error: Any) -> dict[str, Any]:
    return {"ok": False, "plan_type": "", "message": f"CPA auth 文件读取失败: {error}"}


def usage_probe_exception_result(*, kind: str, error: Any) -> dict[str, str]:
    return {"status": "network_error", "plan_type": "", "message": f"wham/usage {kind}: {error}"}


def usage_probe_http_result(*, status_code: int, text: str = "") -> dict[str, str]:
    if status_code in (401, 403):
        return {"status": "auth_error", "plan_type": "", "message": f"wham/usage token 无效 HTTP {status_code}"}
    if status_code == 429 or 500 <= status_code < 600:
        return {"status": "network_error", "plan_type": "", "message": f"wham/usage 临时错误 HTTP {status_code}"}
    return {
        "status": "network_error",
        "plan_type": "",
        "message": f"wham/usage 非预期 HTTP {status_code}: {str(text or '')[:160]}",
    }


def usage_probe_json_error_result(error: Any) -> dict[str, str]:
    return {"status": "network_error", "plan_type": "", "message": f"wham/usage JSON 解析失败: {error}"}


def usage_probe_ok_result(plan_type: str) -> dict[str, str]:
    normalized_plan_type = str(plan_type or "").strip().lower()
    return {
        "status": "ok",
        "plan_type": normalized_plan_type,
        "message": f"wham/usage plan_type={normalized_plan_type or 'unknown'}",
    }


def plus_plan_verified_result(plan_type: str) -> dict[str, Any]:
    normalized_plan_type = str(plan_type or "").strip().lower()
    return {
        "ok": True,
        "plan_type": normalized_plan_type,
        "message": f"OpenAI 已确认 plan_type={normalized_plan_type}",
    }


def plus_plan_refresh_exception_probe(last_probe: dict[str, Any], *, plan_type: str, error: Any) -> dict[str, Any]:
    return {
        "status": last_probe.get("status") or "refresh_error",
        "plan_type": str(plan_type or "").strip().lower(),
        "message": f"{last_probe.get('message')}; refresh 异常: {error}",
    }


def plus_plan_unverified_result(*, email: str, last_probe: dict[str, Any]) -> dict[str, Any]:
    plan_type = str(last_probe.get("plan_type") or "").strip().lower()
    if plan_type == "free":
        message = "OpenAI wham/usage 仍返回 plan_type=free，未确认 Plus 生效"
    else:
        message = str(last_probe.get("message") or "OpenAI Plus 状态未确认")
    return {"ok": False, "plan_type": plan_type, "message": message, "email": email}
