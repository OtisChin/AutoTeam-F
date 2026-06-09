"""Bind-card checkout link HTTP route."""

import logging
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class BindLinkParams(BaseModel):
    access_token: str
    plan_name: str
    promo_campaign: dict | None = None
    billing_details: dict
    checkout_ui_mode: str = "hosted"
    team_plan_data: dict | None = None
    entry_point: str | None = None
    promo_code: str | None = None
    cancel_url: str | None = None


def _checkout_payload(params: BindLinkParams) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "plan_name": params.plan_name,
        "billing_details": params.billing_details,
        "checkout_ui_mode": params.checkout_ui_mode,
    }
    if params.entry_point:
        payload["entry_point"] = params.entry_point
    if params.promo_campaign:
        payload["promo_campaign"] = params.promo_campaign
    if params.promo_code:
        payload["promo_code"] = params.promo_code
    if params.cancel_url:
        payload["cancel_url"] = params.cancel_url
    if params.team_plan_data:
        payload["team_plan_data"] = params.team_plan_data
    return payload


def create_bind_link_router(
    *,
    normalize_access_token: Callable[[str], str],
    generate_checkout_link: Callable[[str, dict[str, Any]], dict[str, Any]],
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
            return generate_checkout_link(access_token, _checkout_payload(params))
        except HTTPException:
            raise
        except Exception as exc:
            route_logger.exception("[bind/link] unexpected error")
            raise HTTPException(status_code=500, detail=f"生成绑卡链接失败: {exc}") from exc

    return router
