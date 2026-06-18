"""PayPal ICE Plus activation API proxy routes."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import requests
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from autotoken.storage import sqlite_store

DEFAULT_PAYPAL_ICE_BASE_URL = "https://plus.iceaix.com"
DEFAULT_PAYPAL_ICE_TRIAL_CHECK_URL = "https://cha.nerver.cc/api/v1/check"
DEFAULT_PAYPAL_ICE_SUBSCRIPTION_URL = "https://cha.nerver.cc/api/v1/subscription"
PAYPAL_ICE_TIMEOUT_SECONDS = 75
MAX_PAYPAL_ICE_INPUT_CHARS = 8192
PAYPAL_ICE_JOB_HISTORY_NAMESPACE = "paypal_ice_jobs"
PAYPAL_ICE_JOB_HISTORY_KEY = "items"
PAYPAL_ICE_JOB_HISTORY_LIMIT = 100
PAYPAL_ICE_OAUTH_CONFIG_NAMESPACE = "paypal_ice_oauth_login"
PAYPAL_ICE_OAUTH_LOGIN_MAX_RETRIES = 3
_PAYPAL_ICE_JOB_LOCK = threading.RLock()


class PayPalIceTrialCheckParams(BaseModel):
    token: str = ""
    proxy_jp: str = ""


class PayPalIceOAuthLoginParams(BaseModel):
    protocol_only: bool = True
    bind_email: bool = True
    mail_provider: str = ""
    luckmail_email_type: str = ""
    luckmail_preferred_domain: str = ""
    email_domain: str = ""
    oauth_phone_sms_provider: str = ""
    oauth_phone_sms_country: str = ""
    proxy_url: str = ""
    proxy_pool: list[str] = Field(default_factory=list)
    proxy_pool_text: str = ""
    proxy_api_provider: str = ""
    proxy_api_url: str = ""
    proxy_bypass: str = ""


class PayPalIceJobParams(BaseModel):
    input: str = ""
    client_ref: str = ""
    callback_url: str = ""
    proxy: str = ""
    proxy_jp: str = ""
    phone: str = ""
    sms_api: str = ""
    use_pool: bool = False
    email: str = ""
    cookies: Any = None
    pplink_retry: int = Field(default=3, ge=0, le=10)
    otp_timeout: int = Field(default=30, ge=30, le=900)
    idempotency_key: str = ""
    auto_oauth_login: bool = False
    oauth_login_config: PayPalIceOAuthLoginParams = Field(default_factory=PayPalIceOAuthLoginParams)


class PayPalIceCancelJobsParams(BaseModel):
    job_ids: list[str] = Field(default_factory=list)


def _paypal_ice_env() -> dict[str, str]:
    from autotoken.settings.setup_wizard import _read_env

    env = _read_env()

    def pick(key: str, default: str = "") -> str:
        return str(env.get(key, "") or os.environ.get(key, "") or default).strip()

    return {
        "base_url": _normalize_base_url(pick("PAYPAL_ICE_BASE_URL", DEFAULT_PAYPAL_ICE_BASE_URL)),
        "api_key": pick("PAYPAL_ICE_API_KEY"),
    }


def _normalize_base_url(value: str) -> str:
    base_url = str(value or DEFAULT_PAYPAL_ICE_BASE_URL).strip().rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="PAYPAL_ICE_BASE_URL 必须是 http(s) URL")
    return base_url


def _configured_client() -> tuple[str, str]:
    cfg = _paypal_ice_env()
    api_key = cfg["api_key"]
    if not api_key:
        raise HTTPException(status_code=400, detail="请先配置 PAYPAL_ICE_API_KEY")
    return cfg["base_url"], api_key


def _json_response(resp: requests.Response) -> dict[str, Any]:
    try:
        data = resp.json()
    except Exception:
        data = {"raw_text": str(resp.text or "")[:1000]}
    if resp.status_code >= 400:
        detail: Any = data
        if isinstance(data, dict):
            detail = data.get("detail") or data.get("message") or data
        raise HTTPException(status_code=resp.status_code, detail=detail)
    return data if isinstance(data, dict) else {"data": data}


def _paypal_ice_request(method: str, path: str, *, payload: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
    base_url, api_key = _configured_client()
    request_headers = {
        "Authorization": f"Bearer {api_key}",
        "X-API-Key": api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    request_headers.update(headers or {})
    try:
        resp = requests.request(
            method.upper(),
            f"{base_url}{path}",
            headers=request_headers,
            json=payload if method.upper() != "GET" else None,
            timeout=PAYPAL_ICE_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"PayPal ICE 请求失败: {exc}") from exc
    return _json_response(resp)


def _paypal_ice_trial_check_url() -> str:
    url = str(os.environ.get("PAYPAL_ICE_TRIAL_CHECK_URL") or DEFAULT_PAYPAL_ICE_TRIAL_CHECK_URL).strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="PAYPAL_ICE_TRIAL_CHECK_URL 必须是 http(s) URL")
    return url


def _paypal_ice_subscription_url() -> str:
    url = str(os.environ.get("PAYPAL_ICE_SUBSCRIPTION_URL") or DEFAULT_PAYPAL_ICE_SUBSCRIPTION_URL).strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="PAYPAL_ICE_SUBSCRIPTION_URL 必须是 http(s) URL")
    return url


def _paypal_ice_subscription_check(token: str) -> dict[str, Any]:
    payload = {"token": _nonempty_text(token, "token")}
    try:
        resp = requests.post(
            _paypal_ice_subscription_url(),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json=payload,
            timeout=PAYPAL_ICE_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"订阅查询接口请求失败: {exc}") from exc
    try:
        data = resp.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"订阅查询接口返回非 JSON: {str(resp.text or '')[:300]}") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="订阅查询接口返回格式无效")
    if resp.status_code >= 400:
        detail: Any = data.get("detail") or data.get("message") or data
        raise HTTPException(status_code=resp.status_code, detail=detail)
    return data


def _normalize_trial_check_response(data: dict[str, Any]) -> dict[str, Any]:
    result = dict(data)
    if isinstance(result.get("results"), list) and result["results"]:
        first = result["results"][0]
        if isinstance(first, dict):
            result = dict(first) | {
                "batch_total": result.get("total"),
                "batch_ok_count": result.get("ok_count"),
                "batch_eligible_count": result.get("eligible_count"),
            }

    reason = str(result.get("reason") or "").strip()
    message = str(result.get("message") or "").strip()
    coupon_state = str(result.get("coupon_state") or "").strip()
    raw_status = result.get("status")
    eligible = bool(result.get("eligible"))

    blocked_reasons = {
        "blocked",
        "trial_blocked",
        "coupon_blocked",
        "rate_limited",
        "risk_blocked",
    }
    result["eligible"] = eligible
    result["token_ok"] = bool(result.get("token_ok", True))
    result["blocked"] = bool(result.get("blocked")) or reason in blocked_reasons
    if coupon_state and not result.get("resource_mode"):
        result["resource_mode"] = coupon_state
    if raw_status not in (None, "") and "status_code" not in result:
        result["status_code"] = raw_status
    if not eligible:
        result["status"] = message or reason or str(raw_status or "")
    return result


def _paypal_ice_trial_check(token: str) -> dict[str, Any]:
    payload = {"token": _nonempty_text(token, "token")}
    url = _paypal_ice_trial_check_url()
    try:
        resp = requests.post(
            url,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json=payload,
            timeout=PAYPAL_ICE_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"试用资格检测接口请求失败: {exc}") from exc
    try:
        data = resp.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"试用资格检测接口返回非 JSON: {str(resp.text or '')[:300]}") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="试用资格检测接口返回格式无效")
    if resp.status_code >= 400 and not ({"eligible", "token_ok", "results"} & set(data.keys())):
        detail: Any = data.get("detail") or data.get("message") or data
        raise HTTPException(status_code=resp.status_code, detail=detail)
    return _normalize_trial_check_response(data)


def _nonempty_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail=f"{field} 不能为空")
    if len(text) > MAX_PAYPAL_ICE_INPUT_CHARS:
        raise HTTPException(status_code=400, detail=f"{field} 过长")
    return text


def _paypal_ice_progress_sources(source: dict[str, Any]):
    yield source
    for key in ("progress", "progress_info", "progress_detail", "current_progress"):
        value = source.get(key)
        if isinstance(value, dict):
            yield value
    for key in ("steps", "logs", "events", "progress_logs", "history"):
        value = source.get(key)
        if not isinstance(value, list):
            continue
        for item in reversed(value):
            if isinstance(item, dict):
                yield item
            elif item not in (None, ""):
                yield {"message": item}


def _paypal_ice_progress_percent(source: dict[str, Any]) -> int | None:
    for candidate in _paypal_ice_progress_sources(source):
        for key in ("progress_percent", "progress", "percent", "percentage", "value"):
            if key not in candidate:
                continue
            value = candidate.get(key)
            if isinstance(value, dict):
                continue
            if isinstance(value, str):
                value = value.strip().rstrip("%")
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if number <= 1:
                number *= 100
            return max(0, min(100, int(round(number))))
    status = str(source.get("status") or "").strip().lower()
    if status in {"success", "failed"}:
        return 100
    return None


def _paypal_ice_progress_text(source: dict[str, Any], *keys: str) -> str:
    for candidate in _paypal_ice_progress_sources(source):
        for key in keys:
            value = str(candidate.get(key) or "").strip()
            if value:
                return value
    return ""


def _paypal_ice_progress_available(source: dict[str, Any]) -> bool:
    for candidate in _paypal_ice_progress_sources(source):
        for key in (
            "progress_percent",
            "progress",
            "percent",
            "percentage",
            "value",
            "progress_stage",
            "stage",
            "step",
            "current_step",
            "stage_name",
            "step_name",
            "progress_message",
            "message",
            "detail",
            "status_message",
            "text",
            "description",
        ):
            value = candidate.get(key)
            if value not in (None, ""):
                if key == "progress" and isinstance(value, dict):
                    return bool(value)
                return True
    return False


def _paypal_ice_job_summary(data: dict[str, Any], *, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    now = time.time()
    source = dict(fallback or {})
    source.update({key: value for key, value in dict(data or {}).items() if value not in (None, "")})
    job_id = str(source.get("job_id") or "").strip()
    status = str(source.get("status") or "").strip()
    result_code = str(source.get("result_code") or "").strip()
    finished_at = source.get("finished_at") or ""
    if not finished_at and (status in {"success", "failed"} or result_code.upper() == "SUCCESS"):
        finished_at = now
    oauth_progress_events = source.get("oauth_login_progress_events")
    if not isinstance(oauth_progress_events, list):
        oauth_progress_events = []
    local_cancelled = bool(source.get("local_cancelled"))
    oauth_login_cancelled = bool(source.get("oauth_login_cancelled"))
    summary = {
        "job_id": job_id,
        "status": status,
        "client_ref": str(source.get("client_ref") or "").strip(),
        "result_code": result_code,
        "error_message": str(source.get("error_message") or "").strip(),
        "billing_status": str(source.get("billing_status") or "").strip(),
        "resource_mode": str(source.get("resource_mode") or "").strip(),
        "cost_units": source.get("cost_units"),
        "progress_percent": _paypal_ice_progress_percent(source),
        "progress_stage": _paypal_ice_progress_text(
            source,
            "progress_stage",
            "stage",
            "step",
            "current_step",
            "stage_name",
            "step_name",
            "status_text",
        ),
        "progress_message": _paypal_ice_progress_text(
            source,
            "progress_message",
            "message",
            "detail",
            "status_message",
            "text",
            "description",
            "error_message",
        ),
        "progress_available": _paypal_ice_progress_available(source),
        "otp_pending": bool(source.get("otp_pending")) if "otp_pending" in source else False,
        "done": bool(source.get("done")) if "done" in source else status in {"success", "failed"},
        "created_at": float(source.get("created_at_ts") or source.get("_created_at") or now),
        "updated_at": now,
        "finished_at": finished_at,
        "phone": str(source.get("phone") or "").strip(),
        "auto_oauth_login": bool(source.get("auto_oauth_login")),
        "oauth_login_task_id": str(source.get("oauth_login_task_id") or "").strip(),
        "oauth_login_status": str(source.get("oauth_login_status") or "").strip(),
        "oauth_login_error": str(source.get("oauth_login_error") or "").strip(),
        "oauth_login_result_email": str(source.get("oauth_login_result_email") or "").strip(),
        "oauth_login_progress_stage": str(source.get("oauth_login_progress_stage") or "").strip(),
        "oauth_login_progress_message": str(source.get("oauth_login_progress_message") or "").strip(),
        "oauth_login_progress_email": str(source.get("oauth_login_progress_email") or "").strip(),
        "oauth_login_progress_events": oauth_progress_events[-12:],
        "oauth_login_retry_count": _int_value(source.get("oauth_login_retry_count"), 0),
        "local_cancelled": local_cancelled,
        "oauth_login_cancelled": oauth_login_cancelled,
    }
    if local_cancelled:
        summary["status"] = "cancelled"
        summary["done"] = True
        summary["progress_percent"] = 100
        summary["progress_stage"] = "cancelled"
        summary["progress_message"] = str(source.get("progress_message") or "已本地取消 PayPal ICE 任务").strip()
        summary["progress_available"] = True
        summary["error_message"] = str(source.get("error_message") or "已本地取消 PayPal ICE 任务").strip()
        if summary["auto_oauth_login"] and summary["oauth_login_status"] not in {"completed", "failed", "cancelled"}:
            summary["oauth_login_status"] = "cancelled"
            summary["oauth_login_error"] = "已本地取消 PayPal ICE 任务"
    elif oauth_login_cancelled and summary["oauth_login_status"] not in {"completed", "failed", "cancelled"}:
        summary["oauth_login_status"] = "cancelled"
        summary["oauth_login_error"] = "已本地取消协议补登录"
    return summary


def _paypal_ice_job_history() -> list[dict[str, Any]]:
    data = sqlite_store.get_json(PAYPAL_ICE_JOB_HISTORY_NAMESPACE, PAYPAL_ICE_JOB_HISTORY_KEY, default=[])
    if not isinstance(data, list):
        return []
    items = []
    for raw_item in data:
        if not isinstance(raw_item, dict):
            continue
        item = dict(raw_item)
        status = str(item.get("status") or "").strip().lower()
        result_code = str(item.get("result_code") or "").strip().upper()
        if not item.get("finished_at") and (status == "success" or result_code == "SUCCESS"):
            item["finished_at"] = item.get("updated_at") or item.get("created_at") or ""
        items.append(item)
    return sorted(items, key=lambda item: float(item.get("updated_at") or item.get("created_at") or 0), reverse=True)[
        :PAYPAL_ICE_JOB_HISTORY_LIMIT
    ]


def _save_paypal_ice_job_history(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trimmed = sorted(
        [item for item in items if isinstance(item, dict) and str(item.get("job_id") or "").strip()],
        key=lambda item: float(item.get("updated_at") or item.get("created_at") or 0),
        reverse=True,
    )[:PAYPAL_ICE_JOB_HISTORY_LIMIT]
    sqlite_store.set_json(PAYPAL_ICE_JOB_HISTORY_NAMESPACE, PAYPAL_ICE_JOB_HISTORY_KEY, trimmed)
    return trimmed


def _paypal_ice_bind_at(item: dict[str, Any]) -> float:
    from autotoken.core.timestamps import epoch_seconds

    return float(
        epoch_seconds((item or {}).get("finished_at"))
        or epoch_seconds((item or {}).get("updated_at"))
        or epoch_seconds((item or {}).get("created_at"))
        or time.time()
    )


def _paypal_ice_bind_update_fields(item: dict[str, Any]) -> dict[str, Any]:
    from autotoken.storage.accounts import ACCOUNT_TYPE_PLUS, STATUS_ACTIVE

    bind_at = _paypal_ice_bind_at(item)
    return {
        "status": STATUS_ACTIVE,
        "account_type": ACCOUNT_TYPE_PLUS,
        "last_bind_status": "success",
        "last_bind_at": bind_at,
        "last_bind_provider": "paypal_ice",
        "last_bind_task_id": str((item or {}).get("job_id") or "").strip(),
        "last_bind_message": "PayPal ICE 激活成功",
        "last_bind_failure_stage": "",
        "plus_bound_at": bind_at,
    }


def _oauth_login_config_for_job(job_id: str) -> dict[str, Any]:
    data = sqlite_store.get_json(PAYPAL_ICE_OAUTH_CONFIG_NAMESPACE, job_id, default={})
    return data if isinstance(data, dict) else {}


def _clean_oauth_login_config(raw_config: Any) -> dict[str, Any]:
    raw = raw_config.model_dump() if hasattr(raw_config, "model_dump") else dict(raw_config or {})
    provider = str(raw.get("mail_provider") or "").strip().lower()
    payload: dict[str, Any] = {
        "protocol_only": True,
        "bind_email": True,
    }
    if provider:
        payload["mail_provider"] = provider
    if provider == "luckmail":
        luckmail_email_type = str(raw.get("luckmail_email_type") or "").strip()
        luckmail_preferred_domain = str(raw.get("luckmail_preferred_domain") or "").strip().lstrip("@")
        if luckmail_email_type:
            payload["luckmail_email_type"] = luckmail_email_type
        if luckmail_preferred_domain:
            payload["luckmail_preferred_domain"] = luckmail_preferred_domain
    elif provider and provider != "outlook":
        email_domain = str(raw.get("email_domain") or "").strip().lstrip("@")
        if email_domain:
            payload["email_domain"] = email_domain

    for key in (
        "proxy_url",
        "proxy_pool_text",
        "proxy_api_provider",
        "proxy_api_url",
        "proxy_bypass",
    ):
        value = str(raw.get(key) or "").strip()
        if value:
            payload[key] = value
    proxy_pool = raw.get("proxy_pool")
    if isinstance(proxy_pool, list):
        cleaned_proxy_pool = [str(item or "").strip() for item in proxy_pool if str(item or "").strip()]
        if cleaned_proxy_pool:
            payload["proxy_pool"] = cleaned_proxy_pool
    return payload


def _save_oauth_login_config(job_id: str, params: PayPalIceJobParams) -> None:
    if not bool(getattr(params, "auto_oauth_login", False)) or not job_id:
        return
    raw_config = getattr(params, "oauth_login_config", None) or PayPalIceOAuthLoginParams()
    payload = _clean_oauth_login_config(raw_config)
    sqlite_store.set_json(PAYPAL_ICE_OAUTH_CONFIG_NAMESPACE, job_id, payload)


def _int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _paypal_ice_oauth_retry_available(item: dict[str, Any], error: str) -> bool:
    retry_count = max(0, _int_value(item.get("oauth_login_retry_count"), 0))
    if retry_count >= PAYPAL_ICE_OAUTH_LOGIN_MAX_RETRIES:
        item["oauth_login_status"] = "failed"
        item["oauth_login_error"] = f"{error}，已重试 {PAYPAL_ICE_OAUTH_LOGIN_MAX_RETRIES} 次"
        return False

    retry_count += 1
    item["oauth_login_retry_count"] = retry_count
    item["oauth_login_task_id"] = ""
    item["oauth_login_status"] = "retrying"
    item["oauth_login_error"] = f"{error}，准备重试 {retry_count}/{PAYPAL_ICE_OAUTH_LOGIN_MAX_RETRIES}"
    return True


def _paypal_ice_oauth_progress_event(event: Any) -> dict[str, Any]:
    if not isinstance(event, dict):
        return {}
    return {
        "stage": str(event.get("stage") or "").strip(),
        "message": str(event.get("message") or "").strip(),
        "email": str(event.get("email") or "").strip(),
        "level": str(event.get("level") or "").strip(),
        "current": event.get("current"),
        "total": event.get("total"),
        "updated_at": event.get("updated_at"),
    }


def _apply_paypal_ice_oauth_progress(item: dict[str, Any], task: dict[str, Any]) -> None:
    raw_events = task.get("progress_events") if isinstance(task.get("progress_events"), list) else []
    events = [
        event
        for event in (_paypal_ice_oauth_progress_event(raw_event) for raw_event in raw_events)
        if event.get("stage") or event.get("message")
    ][-12:]
    raw_progress = task.get("progress") if isinstance(task.get("progress"), dict) else {}
    progress = _paypal_ice_oauth_progress_event(raw_progress)
    latest = events[-1] if events else progress
    if latest.get("stage") or latest.get("message"):
        item["oauth_login_progress_stage"] = str(latest.get("stage") or "").strip()
        item["oauth_login_progress_message"] = str(latest.get("message") or "").strip()
        item["oauth_login_progress_email"] = str(latest.get("email") or "").strip()
    if events:
        item["oauth_login_progress_events"] = events
    elif not isinstance(item.get("oauth_login_progress_events"), list):
        item["oauth_login_progress_events"] = []


def _paypal_ice_conflict_message(detail: Any) -> str:
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("detail") or "").strip() or "同类任务正在执行，请等待完成后再试"
    return str(detail or "").strip()


def _paypal_ice_conflict_running_task(detail: Any, client_ref: str) -> dict[str, Any]:
    if not isinstance(detail, dict):
        return {}
    running_task = detail.get("running_task")
    if not isinstance(running_task, dict):
        return {}
    target = str(client_ref or "").strip().lower()
    command = str(running_task.get("command") or "").strip().lower()
    params = running_task.get("params") if isinstance(running_task.get("params"), dict) else {}
    task_email = str(params.get("email") or "").strip().lower()
    if command == f"login:{target}" or task_email == target:
        return running_task
    return {}


def _sync_paypal_ice_oauth_login(
    item: dict[str, Any],
    *,
    start_oauth_login: Callable[[dict[str, Any]], dict[str, Any]] | None,
    get_task: Callable[[str], dict[str, Any] | None] | None,
) -> dict[str, Any]:
    if item.get("local_cancelled"):
        if str(item.get("oauth_login_status") or "").strip().lower() not in {"completed", "failed", "cancelled"}:
            item["oauth_login_status"] = "cancelled"
            item["oauth_login_error"] = "已本地取消 PayPal ICE 任务"
        return item
    if item.get("oauth_login_cancelled"):
        item["oauth_login_status"] = "cancelled"
        item["oauth_login_error"] = item.get("oauth_login_error") or "已本地取消协议补登录"
        return item
    if not item.get("auto_oauth_login"):
        return item
    if str(item.get("status") or "").lower() != "success" and str(item.get("result_code") or "").upper() != "SUCCESS":
        return item

    job_id = str(item.get("job_id") or "").strip()
    client_ref = str(item.get("client_ref") or "").strip()
    if not client_ref:
        item["oauth_login_task_id"] = ""
        item["oauth_login_status"] = "skipped"
        item["oauth_login_error"] = "ICE 任务缺少 client_ref，无法定位本地账号"
        sqlite_store.delete_key(PAYPAL_ICE_OAUTH_CONFIG_NAMESPACE, job_id)
        return item

    task_id = str(item.get("oauth_login_task_id") or "").strip()
    if task_id:
        task = get_task(task_id) if get_task else None
        if not isinstance(task, dict):
            return item
        task_status = str(task.get("status") or "").strip().lower()
        item["oauth_login_status"] = task_status or item.get("oauth_login_status") or "submitted"
        _apply_paypal_ice_oauth_progress(item, task)
        if task_status == "completed":
            result = task.get("result") if isinstance(task.get("result"), dict) else {}
            item["oauth_login_result_email"] = str(result.get("email") or "").strip()
            item["oauth_login_error"] = ""
            sqlite_store.delete_key(PAYPAL_ICE_OAUTH_CONFIG_NAMESPACE, job_id)
            return item
        elif task_status in {"failed", "cancelled"}:
            error = str(task.get("error") or "协议补登录失败").strip()
            if not _paypal_ice_oauth_retry_available(item, error):
                sqlite_store.delete_key(PAYPAL_ICE_OAUTH_CONFIG_NAMESPACE, job_id)
                return item
        else:
            return item

    if not start_oauth_login:
        error = "本地协议补登录服务不可用"
        if not _paypal_ice_oauth_retry_available(item, error):
            sqlite_store.delete_key(PAYPAL_ICE_OAUTH_CONFIG_NAMESPACE, job_id)
        return item

    payload = {"email": client_ref, **_oauth_login_config_for_job(job_id)}
    payload["protocol_only"] = True
    payload["bind_email"] = True
    payload["exclusive"] = False
    try:
        task = start_oauth_login(payload)
    except HTTPException as exc:
        detail = exc.detail
        if exc.status_code == 409:
            running_task = _paypal_ice_conflict_running_task(detail, client_ref)
            running_task_id = str(running_task.get("task_id") or "").strip()
            if running_task_id:
                item["oauth_login_task_id"] = running_task_id
                task_snapshot = get_task(running_task_id) if get_task else None
                if isinstance(task_snapshot, dict):
                    task_status = str(task_snapshot.get("status") or "running").strip().lower()
                    item["oauth_login_status"] = task_status
                    _apply_paypal_ice_oauth_progress(item, task_snapshot)
                    if task_status == "completed":
                        result = task_snapshot.get("result") if isinstance(task_snapshot.get("result"), dict) else {}
                        item["oauth_login_result_email"] = str(result.get("email") or "").strip()
                        sqlite_store.delete_key(PAYPAL_ICE_OAUTH_CONFIG_NAMESPACE, job_id)
                    elif task_status in {"failed", "cancelled"}:
                        error = str(task_snapshot.get("error") or "协议补登录失败").strip()
                        if not _paypal_ice_oauth_retry_available(item, error):
                            sqlite_store.delete_key(PAYPAL_ICE_OAUTH_CONFIG_NAMESPACE, job_id)
                else:
                    item["oauth_login_status"] = "running"
                if item["oauth_login_status"] not in {"failed", "cancelled"}:
                    if item["oauth_login_status"] != "retrying":
                        item["oauth_login_error"] = ""
                return item
        error = _paypal_ice_conflict_message(detail)
        if exc.status_code == 409:
            item["oauth_login_status"] = "waiting"
            item["oauth_login_error"] = error
        elif not _paypal_ice_oauth_retry_available(item, error):
            sqlite_store.delete_key(PAYPAL_ICE_OAUTH_CONFIG_NAMESPACE, job_id)
        return item
    except Exception as exc:
        if not _paypal_ice_oauth_retry_available(item, str(exc)):
            sqlite_store.delete_key(PAYPAL_ICE_OAUTH_CONFIG_NAMESPACE, job_id)
        return item

    item["oauth_login_task_id"] = str((task or {}).get("task_id") or "").strip()
    item["oauth_login_status"] = str((task or {}).get("status") or "submitted").strip()
    item["oauth_login_error"] = ""
    return item


def _record_paypal_ice_job(
    data: dict[str, Any],
    *,
    fallback: dict[str, Any] | None = None,
    start_oauth_login: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    get_task: Callable[[str], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    with _PAYPAL_ICE_JOB_LOCK:
        items = _paypal_ice_job_history()
        job_id = str((data or {}).get("job_id") or (fallback or {}).get("job_id") or "").strip()
        existing = next((row for row in items if str(row.get("job_id") or "") == job_id), {})
        item = _paypal_ice_job_summary(data, fallback={**existing, **dict(fallback or {})})
        if not item["job_id"]:
            return item
        item = _sync_paypal_ice_oauth_login(
            item,
            start_oauth_login=start_oauth_login,
            get_task=get_task,
        )
        _mark_paypal_ice_account_plus(item)
        merged = [item]
        merged.extend(existing for existing in items if str(existing.get("job_id") or "") != item["job_id"])
        _save_paypal_ice_job_history(merged)
        return item


def _paypal_ice_phone_failure_marker(item: dict[str, Any]) -> tuple[str, str]:
    text = " ".join(
        str(item.get(key) or "").strip()
        for key in ("result_code", "error_message", "progress_message", "progress_stage")
    )
    upper_text = text.upper()
    if "PHONE_CONFIRMATION_REQUIRED" in upper_text:
        return "PHONE_CONFIRMATION_REQUIRED", "PHONE_CONFIRMATION_REQUIRED"
    if "SMS OTP 超时未收到" in text or ("SMS OTP" in upper_text and "超时" in text):
        return "SMS_OTP_TIMEOUT", "SMS OTP 超时未收到"
    return "", ""


def _mark_paypal_ice_phone_failure(job_id: str, item: dict[str, Any]) -> None:
    code, reason = _paypal_ice_phone_failure_marker(item)
    if not reason:
        return
    try:
        from autotoken.services.paypal_ice_phone_pool import (
            mark_phone_error,
            mark_phone_error_by_number,
            phone_for_job,
        )

        phone_id = phone_for_job(job_id)
        if phone_id:
            mark_phone_error(phone_id, reason, code=code)
            return
        mark_phone_error_by_number(str(item.get("phone") or ""), reason, code=code)
    except Exception:
        pass


def _clear_paypal_ice_phone_failure(job_id: str, item: dict[str, Any]) -> None:
    try:
        from autotoken.services.paypal_ice_phone_pool import (
            clear_phone_failure_marker,
            clear_phone_failure_marker_by_number,
            phone_for_job,
        )

        phone_id = phone_for_job(job_id)
        if phone_id:
            clear_phone_failure_marker(phone_id)
            return
        clear_phone_failure_marker_by_number(str(item.get("phone") or ""))
    except Exception:
        pass


def _cancel_paypal_ice_jobs(job_ids: list[str]) -> dict[str, Any]:
    targets = {str(job_id or "").strip() for job_id in job_ids}
    targets.discard("")
    if not targets:
        raise HTTPException(status_code=400, detail="请选择要取消的 ICE job")

    cancelled: list[str] = []
    with _PAYPAL_ICE_JOB_LOCK:
        items = _paypal_ice_job_history()
        next_items: list[dict[str, Any]] = []
        now = time.time()
        for item in items:
            job_id = str(item.get("job_id") or "").strip()
            if job_id not in targets:
                next_items.append(item)
                continue

            updated = dict(item)
            updated["updated_at"] = now
            status = str(updated.get("status") or "").strip().lower()
            result_code = str(updated.get("result_code") or "").strip().upper()
            ice_terminal = status in {"success", "failed", "skipped", "cancelled"} or result_code == "SUCCESS"
            if ice_terminal:
                updated["oauth_login_cancelled"] = True
            else:
                updated["local_cancelled"] = True
                updated["status"] = "cancelled"
                updated["done"] = True
                updated["progress_percent"] = 100
                updated["progress_stage"] = "cancelled"
                updated["progress_message"] = "已本地取消 PayPal ICE 任务"
                updated["progress_available"] = True
                updated["error_message"] = "已本地取消 PayPal ICE 任务"
            oauth_status = str(updated.get("oauth_login_status") or "").strip().lower()
            if oauth_status not in {"completed", "failed", "cancelled"}:
                updated["oauth_login_status"] = "cancelled"
                updated["oauth_login_error"] = "已本地取消协议补登录" if ice_terminal else "已本地取消 PayPal ICE 任务"
            next_items.append(updated)
            sqlite_store.delete_key(PAYPAL_ICE_OAUTH_CONFIG_NAMESPACE, job_id)
            cancelled.append(job_id)
        _save_paypal_ice_job_history(next_items)

    for job_id in cancelled:
        try:
            from autotoken.services.paypal_ice_phone_pool import phone_for_job, release_phone

            phone_id = phone_for_job(job_id)
            if phone_id:
                release_phone(phone_id)
        except Exception:
            pass

    return {"cancelled": cancelled, "count": len(cancelled)}


def _mark_paypal_ice_account_plus(item: dict[str, Any]) -> None:
    status = str((item or {}).get("status") or "").strip().lower()
    result_code = str((item or {}).get("result_code") or "").strip().upper()
    if status != "success" and result_code != "SUCCESS":
        return
    client_ref = str((item or {}).get("client_ref") or "").strip()
    if not client_ref:
        return
    try:
        from autotoken.storage.accounts import update_account

        fields = _paypal_ice_bind_update_fields(item)
        update_account(client_ref, **fields)
        result_email = str((item or {}).get("oauth_login_result_email") or "").strip()
        if result_email and result_email.lower() != client_ref.lower():
            update_account(result_email, **fields)
    except Exception:
        pass


def repair_paypal_ice_account_bind_metadata() -> int:
    """Backfill bind metadata for PayPal ICE accounts, including migrated email rows."""
    try:
        from autotoken.storage.accounts import find_account, load_accounts, update_account

        accounts = load_accounts()
    except Exception:
        return 0

    repaired = 0
    for item in _paypal_ice_job_history():
        status = str((item or {}).get("status") or "").strip().lower()
        result_code = str((item or {}).get("result_code") or "").strip().upper()
        if status != "success" and result_code != "SUCCESS":
            continue
        fields = _paypal_ice_bind_update_fields(item)
        candidates = [
            str((item or {}).get("client_ref") or "").strip(),
            str((item or {}).get("oauth_login_result_email") or "").strip(),
        ]
        seen: set[str] = set()
        for email in candidates:
            normalized = email.lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            account = find_account(accounts, email)
            if not account:
                continue
            if (
                account.get("plus_bound_at")
                and account.get("last_bind_at")
                and str(account.get("last_bind_provider") or "").strip().lower() == "paypal_ice"
                and str(account.get("account_type") or "").strip().lower() == "plus"
            ):
                continue
            if update_account(email, **fields):
                repaired += 1
    return repaired


def _job_payload_acquire_phone(params: PayPalIceJobParams) -> tuple[dict[str, Any], str | None]:
    """Build job payload. If phone/sms_api not provided, acquire from pool.
    Returns (payload, phone_id_or_None)."""
    payload: dict[str, Any] = {
        "input": _nonempty_text(params.input, "input"),
    }
    phone_id: str | None = None
    phone = str(params.phone or "").strip()
    sms_api = str(params.sms_api or "").strip()

    use_pool = bool(getattr(params, "use_pool", False))

    if phone and sms_api:
        # Direct mode: explicit phone/sms_api provided
        payload["phone"] = _nonempty_text(phone, "phone")
        payload["sms_api"] = _nonempty_text(sms_api, "sms_api")
    elif use_pool or (not phone and not sms_api):
        # Pool mode: acquire from phone pool
        from autotoken.services.paypal_ice_phone_pool import acquire_phone, available_count

        acq = acquire_phone()
        if not acq:
            avail = available_count()
            detail = "手机号池已无可用号码" if avail <= 0 else f"手机号池 {avail} 个可用但分配失败，请重试"
            raise HTTPException(status_code=429, detail=detail)
        payload["phone"] = _nonempty_text(acq["phone_number"], "phone")
        payload["sms_api"] = _nonempty_text(acq["sms_api"], "sms_api")
        phone_id = acq["id"]
    else:
        raise HTTPException(status_code=400, detail="phone 和 sms_api 必须同时提供，或设置 use_pool=true 自动分配")

    for field in ("client_ref", "callback_url", "proxy", "proxy_jp", "email"):
        value = str(getattr(params, field) or "").strip()
        if value:
            payload[field] = value
    if params.cookies not in (None, ""):
        payload["cookies"] = params.cookies
    payload["pplink_retry"] = params.pplink_retry
    payload["otp_timeout"] = params.otp_timeout
    return payload, phone_id


def create_paypal_ice_router(
    *,
    mask_secret: Callable[[str], str],
    start_oauth_login: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    get_task: Callable[[str], dict[str, Any] | None] | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/paypal-ice/config")
    def get_paypal_ice_config():
        cfg = _paypal_ice_env()
        return {
            "base_url": cfg["base_url"],
            "api_key_present": bool(cfg["api_key"]),
            "api_key_masked": mask_secret(cfg["api_key"]),
            "configured": bool(cfg["api_key"]),
        }

    @router.put("/api/paypal-ice/config")
    async def save_paypal_ice_config(request: Request):
        from autotoken.settings.setup_wizard import _write_env

        data = await request.json()
        current = _paypal_ice_env()
        base_url = _normalize_base_url(str(data.get("base_url") or current["base_url"] or DEFAULT_PAYPAL_ICE_BASE_URL))
        api_key = str(data.get("api_key") or data.get("PAYPAL_ICE_API_KEY") or "").strip()
        _write_env("PAYPAL_ICE_BASE_URL", base_url)
        os.environ["PAYPAL_ICE_BASE_URL"] = base_url
        if api_key:
            _write_env("PAYPAL_ICE_API_KEY", api_key)
            os.environ["PAYPAL_ICE_API_KEY"] = api_key
        return get_paypal_ice_config() | {"message": "PayPal ICE 配置已保存"}

    @router.get("/api/paypal-ice/account")
    def get_paypal_ice_account():
        return _paypal_ice_request("GET", "/api/v1/account")

    @router.post("/api/paypal-ice/trial-check")
    def post_paypal_ice_trial_check(params: PayPalIceTrialCheckParams):
        return _paypal_ice_trial_check(params.token)

    @router.post("/api/paypal-ice/subscription")
    def post_paypal_ice_subscription(params: PayPalIceTrialCheckParams):
        return _paypal_ice_subscription_check(params.token)

    @router.get("/api/paypal-ice/jobs")
    def list_paypal_ice_jobs():
        return {"items": _paypal_ice_job_history()}

    @router.post("/api/paypal-ice/jobs")
    def post_paypal_ice_job(params: PayPalIceJobParams):
        headers = {}
        idempotency_key = str(params.idempotency_key or "").strip()
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        payload, phone_id = _job_payload_acquire_phone(params)
        try:
            result = _paypal_ice_request("POST", "/api/v1/jobs", payload=payload, headers=headers)
        except HTTPException:
            if phone_id:
                from autotoken.services.paypal_ice_phone_pool import release_phone
                release_phone(phone_id)
            raise
        if phone_id:
            from autotoken.services.paypal_ice_phone_pool import associate_job
            job_id = str(result.get("job_id") or "").strip()
            if job_id:
                associate_job(phone_id, job_id)
        job_id = str(result.get("job_id") or "").strip()
        if job_id:
            _save_oauth_login_config(job_id, params)
        item = _record_paypal_ice_job(
            result,
            fallback={**payload, "auto_oauth_login": bool(getattr(params, "auto_oauth_login", False))},
            start_oauth_login=start_oauth_login,
            get_task=get_task,
        )
        return {**result, **item}

    @router.post("/api/paypal-ice/jobs/cancel-local")
    def cancel_paypal_ice_jobs(params: PayPalIceCancelJobsParams):
        return _cancel_paypal_ice_jobs(params.job_ids)

    @router.get("/api/paypal-ice/jobs/{job_id}")
    def get_paypal_ice_job(job_id: str):
        result = _paypal_ice_request("GET", f"/api/v1/jobs/{_nonempty_text(job_id, 'job_id')}")
        item = _record_paypal_ice_job(
            result,
            fallback={"job_id": job_id},
            start_oauth_login=start_oauth_login,
            get_task=get_task,
        )
        # Auto-release phone when job reaches terminal status
        status = str(result.get("status") or "").strip()
        if status in ("success", "failed"):
            try:
                if status == "failed":
                    _mark_paypal_ice_phone_failure(job_id, item)
                else:
                    _clear_paypal_ice_phone_failure(job_id, item)
                from autotoken.services.paypal_ice_phone_pool import phone_for_job, release_phone
                pid = phone_for_job(job_id)
                if pid:
                    release_phone(pid)
            except Exception:
                pass
        return {**result, **item}

    @router.post("/api/paypal-ice/jobs/{job_id}/release-phone")
    def release_phone_for_job(job_id: str):
        """Manually release the phone associated with a job."""
        from autotoken.services.paypal_ice_phone_pool import phone_for_job, release_phone

        pid = phone_for_job(_nonempty_text(job_id, "job_id"))
        if not pid:
            return {"released": False, "reason": "no phone associated with this job"}
        release_phone(pid)
        return {"released": True, "phone_id": pid}

    return router
