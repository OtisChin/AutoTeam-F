"""Provider-neutral account-plan verification payload helpers."""

from __future__ import annotations

import time
from typing import Any

from autotoken.core.normalization import normalize_access_token


def verification_failure_update_fields(
    *,
    task_id: str,
    status: str,
    message: str,
    failure_stage: str,
    marked_at: float,
) -> dict[str, Any]:
    return {
        "last_bind_status": status,
        "last_bind_at": marked_at,
        "last_bind_task_id": task_id,
        "last_bind_message": message,
        "last_bind_failure_stage": failure_stage,
    }


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
    try:
        expires_at = now + max(0, int(refreshed.get("expires_in") or 0))
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
    message = (
        "OpenAI wham/usage 仍返回 plan_type=free，未确认 Plus 生效"
        if plan_type == "free"
        else str(last_probe.get("message") or "OpenAI Plus 状态未确认")
    )
    return {"ok": False, "plan_type": plan_type, "message": message, "email": email}
