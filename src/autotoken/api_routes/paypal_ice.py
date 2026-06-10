"""PayPal ICE Plus activation API proxy routes."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import requests
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

DEFAULT_PAYPAL_ICE_BASE_URL = "https://plus.iceaix.com"
PAYPAL_ICE_TIMEOUT_SECONDS = 75
MAX_PAYPAL_ICE_INPUT_CHARS = 8192


class PayPalIceTrialCheckParams(BaseModel):
    token: str = ""
    proxy_jp: str = ""


class PayPalIceJobParams(BaseModel):
    input: str = ""
    client_ref: str = ""
    callback_url: str = ""
    proxy: str = ""
    proxy_jp: str = ""
    phone: str = ""
    sms_api: str = ""
    email: str = ""
    cookies: Any = None
    pplink_retry: int | None = Field(default=None, ge=0, le=10)
    otp_timeout: int | None = Field(default=None, ge=30, le=900)
    idempotency_key: str = ""


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


def _nonempty_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail=f"{field} 不能为空")
    if len(text) > MAX_PAYPAL_ICE_INPUT_CHARS:
        raise HTTPException(status_code=400, detail=f"{field} 过长")
    return text


def _job_payload(params: PayPalIceJobParams) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "input": _nonempty_text(params.input, "input"),
    }
    for field in ("client_ref", "callback_url", "proxy", "proxy_jp", "phone", "sms_api", "email"):
        value = str(getattr(params, field) or "").strip()
        if value:
            payload[field] = value
    if ("phone" in payload) != ("sms_api" in payload):
        raise HTTPException(status_code=400, detail="自定义接码必须同时提供 phone 和 sms_api")
    if params.cookies not in (None, ""):
        payload["cookies"] = params.cookies
    if params.pplink_retry is not None:
        payload["pplink_retry"] = int(params.pplink_retry)
    if params.otp_timeout is not None:
        payload["otp_timeout"] = int(params.otp_timeout)
    return payload


def create_paypal_ice_router(*, mask_secret: Callable[[str], str]) -> APIRouter:
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
        payload = {"token": _nonempty_text(params.token, "token")}
        proxy_jp = str(params.proxy_jp or "").strip()
        if proxy_jp:
            payload["proxy_jp"] = proxy_jp
        return _paypal_ice_request("POST", "/api/v1/trial/check", payload=payload)

    @router.post("/api/paypal-ice/jobs")
    def post_paypal_ice_job(params: PayPalIceJobParams):
        headers = {}
        idempotency_key = str(params.idempotency_key or "").strip()
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return _paypal_ice_request("POST", "/api/v1/jobs", payload=_job_payload(params), headers=headers)

    @router.get("/api/paypal-ice/jobs/{job_id}")
    def get_paypal_ice_job(job_id: str):
        return _paypal_ice_request("GET", f"/api/v1/jobs/{_nonempty_text(job_id, 'job_id')}")

    return router
