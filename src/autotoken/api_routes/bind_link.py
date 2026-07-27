"""Bind-card checkout link HTTP route."""

import logging
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class BindLinkParams(BaseModel):
    access_token: str
    plan_name: str
    checkout_flow: str = ""
    promo_campaign: dict | None = None
    billing_details: dict
    checkout_ui_mode: str = "hosted"
    team_plan_data: dict | None = None
    entry_point: str | None = None
    promo_code: str | None = None
    cancel_url: str | None = None


class BindLinkOpenParams(BaseModel):
    email: str
    access_token: str = ""
    plan_name: str
    checkout_flow: str = ""
    billing_details: dict
    checkout_ui_mode: str = "hosted"
    team_plan_data: dict | None = None
    entry_point: str | None = None


def _checkout_payload(params: BindLinkParams) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "plan_name": params.plan_name,
        "billing_details": params.billing_details,
        "checkout_ui_mode": params.checkout_ui_mode,
    }
    if params.checkout_flow:
        payload["checkout_flow"] = params.checkout_flow
    if params.entry_point:
        payload["entry_point"] = params.entry_point
    if getattr(params, "promo_campaign", None):
        payload["promo_campaign"] = params.promo_campaign
    if getattr(params, "promo_code", None):
        payload["promo_code"] = params.promo_code
    if getattr(params, "cancel_url", None):
        payload["cancel_url"] = params.cancel_url
    if params.team_plan_data:
        payload["team_plan_data"] = params.team_plan_data
    return payload


def _is_plus_trial_flow(payload: dict[str, Any]) -> bool:
    return str(payload.get("checkout_flow") or "").strip().lower() == "plus_trial"


def _prefer_chatgpt_checkout_url(result: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(result)
    checkout_session_id = str(normalized.get("checkout_session_id") or "").strip()
    if not checkout_session_id:
        return normalized

    processor_entity = str(normalized.get("processor_entity") or "openai_llc").strip() or "openai_llc"
    chatgpt_checkout_url = str(normalized.get("chatgpt_checkout_url") or "").strip()
    if not chatgpt_checkout_url:
        chatgpt_checkout_url = f"https://chatgpt.com/checkout/{processor_entity}/{checkout_session_id}"

    normalized["chatgpt_checkout_url"] = chatgpt_checkout_url
    normalized["url"] = chatgpt_checkout_url
    return normalized


def create_bind_link_router(
    *,
    normalize_access_token: Callable[[str], str],
    generate_checkout_link: Callable[[str, dict[str, Any]], dict[str, Any]],
    generate_plus_trial_checkout_link: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    get_account_access_token: Callable[[str], str] | None = None,
    open_checkout_url: Callable[[str, str], dict[str, Any]] | None = None,
    logger: logging.Logger | None = None,
) -> APIRouter:
    router = APIRouter()
    route_logger = logger or logging.getLogger(__name__)

    @router.post("/api/bind/link")
    def post_bind_link(params: BindLinkParams):
        """生成 ChatGPT 绑卡链接"""
        access_token = normalize_access_token(params.access_token)
        if not access_token:
            raise HTTPException(status_code=400, detail="请提供 access_token")

        try:
            payload = _checkout_payload(params)
            if _is_plus_trial_flow(payload):
                if not generate_plus_trial_checkout_link:
                    raise HTTPException(status_code=500, detail="当前服务未配置 Plus 试用提链器")
                return _prefer_chatgpt_checkout_url(generate_plus_trial_checkout_link(access_token, payload))
            return _prefer_chatgpt_checkout_url(generate_checkout_link(access_token, payload))
        except HTTPException:
            raise
        except Exception as exc:
            route_logger.exception("[bind/link] unexpected error")
            raise HTTPException(status_code=500, detail=f"生成绑卡链接失败: {exc}") from exc

    @router.post("/api/bind/link/open")
    def post_bind_link_open(params: BindLinkOpenParams):
        """生成 ChatGPT 绑卡链接并用该账号 auth_session 打开"""
        email = str(params.email or "").strip().lower()
        if not email:
            raise HTTPException(status_code=400, detail="请选择号池账号")
        if not get_account_access_token or not open_checkout_url:
            raise HTTPException(status_code=500, detail="当前服务未配置 auth_session 打开能力")

        access_token = normalize_access_token(params.access_token) or normalize_access_token(
            get_account_access_token(email)
        )
        if not access_token:
            raise HTTPException(status_code=400, detail=f"账号缺少可用 access_token: {email}")

        try:
            payload = _checkout_payload(params)
            if _is_plus_trial_flow(payload):
                if not generate_plus_trial_checkout_link:
                    raise HTTPException(status_code=500, detail="当前服务未配置 Plus 试用提链器")
                generated = _prefer_chatgpt_checkout_url(generate_plus_trial_checkout_link(access_token, payload))
            else:
                generated = _prefer_chatgpt_checkout_url(generate_checkout_link(access_token, payload))
            checkout_url = str(generated.get("url") or "").strip()
            if not checkout_url:
                raise HTTPException(status_code=502, detail="生成 checkout 返回缺少 url")
            opened = open_checkout_url(email, checkout_url)
            return {**generated, **(opened or {}), "opened": bool((opened or {}).get("opened", True))}
        except HTTPException:
            raise
        except Exception as exc:
            route_logger.exception("[bind/link/open] unexpected error")
            raise HTTPException(status_code=500, detail=f"打开绑卡链接失败: {exc}") from exc

    return router
