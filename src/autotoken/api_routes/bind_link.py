"""Bind-card checkout link HTTP route."""

import logging
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import AliasChoices, BaseModel, Field


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
    proxy_api_enabled: bool = Field(False, validation_alias=AliasChoices("proxy_api_enabled", "proxyApiEnabled"))
    proxy_api_provider: str = Field("cliproxy", validation_alias=AliasChoices("proxy_api_provider", "proxyApiProvider"))
    proxy_api_url: str = Field("", validation_alias=AliasChoices("proxy_api_url", "proxyApiUrl"))
    proxy_api_country: str = Field("US", validation_alias=AliasChoices("proxy_api_country", "proxyApiCountry"))


class BindLinkOpenParams(BaseModel):
    email: str
    access_token: str = ""
    plan_name: str
    checkout_flow: str = ""
    billing_details: dict
    checkout_ui_mode: str = "hosted"
    team_plan_data: dict | None = None
    entry_point: str | None = None
    proxy_api_enabled: bool = Field(False, validation_alias=AliasChoices("proxy_api_enabled", "proxyApiEnabled"))
    proxy_api_provider: str = Field("cliproxy", validation_alias=AliasChoices("proxy_api_provider", "proxyApiProvider"))
    proxy_api_url: str = Field("", validation_alias=AliasChoices("proxy_api_url", "proxyApiUrl"))
    proxy_api_country: str = Field("US", validation_alias=AliasChoices("proxy_api_country", "proxyApiCountry"))


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


def _proxy_api_kwargs(params: BindLinkParams | BindLinkOpenParams, *, country: str | None = None) -> dict[str, str]:
    return {
        "provider": str(params.proxy_api_provider or "cliproxy").strip() or "cliproxy",
        "country": str(country or params.proxy_api_country or "US").strip().upper() or "US",
        "api_url": str(params.proxy_api_url or "").strip(),
    }


def _select_proxy_url(
    selector: Callable[..., str] | None,
    params: BindLinkParams | BindLinkOpenParams,
    *,
    country: str | None = None,
    strict: bool = False,
) -> str:
    if not selector or not params.proxy_api_enabled:
        return ""
    try:
        proxy_url = str(selector(**_proxy_api_kwargs(params, country=country)) or "").strip()
    except Exception as exc:
        if strict:
            raise HTTPException(status_code=502, detail=f"打开浏览器代理 API 获取失败: {exc}") from exc
        logging.getLogger(__name__).info("[bind/link] proxy API unavailable; falling back to direct: %s", exc)
        return ""
    if strict and not proxy_url:
        raise HTTPException(status_code=502, detail="打开浏览器代理 API 未返回可用代理")
    return proxy_url


def _select_preflighted_open_proxy_url(
    selector: Callable[..., str] | None,
    params: BindLinkParams | BindLinkOpenParams,
    *,
    preflight_proxy_url: Callable[[str], tuple[bool, str]] | None = None,
    country: str | None = None,
    attempts: int = 3,
) -> str:
    if not selector or not params.proxy_api_enabled:
        return ""
    max_attempts = max(1, int(attempts or 1))
    last_message = ""
    for attempt_index in range(max_attempts):
        proxy_url = _select_proxy_url(selector, params, country=country, strict=True)
        if not proxy_url or not preflight_proxy_url:
            return proxy_url
        ok, message = preflight_proxy_url(proxy_url)
        if ok:
            return proxy_url
        last_message = str(message or "unknown")
        logging.getLogger(__name__).info(
            "[bind/link/open] browser proxy preflight failed (%s/%s): %s",
            attempt_index + 1,
            max_attempts,
            last_message,
        )
    raise HTTPException(status_code=502, detail=f"打开浏览器代理预检失败: {last_message}")


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
    generate_checkout_link: Callable[..., dict[str, Any]],
    generate_plus_trial_checkout_link: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    get_account_access_token: Callable[[str], str] | None = None,
    open_checkout_url: Callable[..., dict[str, Any]] | None = None,
    select_open_proxy_url: Callable[..., str] | None = None,
    preflight_open_proxy_url: Callable[[str], tuple[bool, str]] | None = None,
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
            proxy_url = _select_proxy_url(select_open_proxy_url, params)
            if proxy_url:
                return _prefer_chatgpt_checkout_url(generate_checkout_link(access_token, payload, proxy_url=proxy_url))
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
            generated_proxy_url = ""
            if _is_plus_trial_flow(payload):
                if not generate_plus_trial_checkout_link:
                    raise HTTPException(status_code=500, detail="当前服务未配置 Plus 试用提链器")
                generated = _prefer_chatgpt_checkout_url(generate_plus_trial_checkout_link(access_token, payload))
            else:
                generated_proxy_url = _select_preflighted_open_proxy_url(
                    select_open_proxy_url,
                    params,
                    preflight_proxy_url=preflight_open_proxy_url,
                )
                if generated_proxy_url:
                    generated = _prefer_chatgpt_checkout_url(
                        generate_checkout_link(access_token, payload, proxy_url=generated_proxy_url)
                    )
                else:
                    generated = _prefer_chatgpt_checkout_url(generate_checkout_link(access_token, payload))
            checkout_url = str(generated.get("url") or "").strip()
            if not checkout_url:
                raise HTTPException(status_code=502, detail="生成 checkout 返回缺少 url")
            open_proxy_url = generated_proxy_url or _select_preflighted_open_proxy_url(
                select_open_proxy_url,
                params,
                preflight_proxy_url=preflight_open_proxy_url,
            )
            open_kwargs: dict[str, Any] = {"open_mode": "roxybrowser"}
            if open_proxy_url:
                open_kwargs["proxy_url"] = open_proxy_url
            opened = open_checkout_url(email, checkout_url, **open_kwargs)
            return {**generated, **(opened or {}), "opened": bool((opened or {}).get("opened", True))}
        except HTTPException:
            raise
        except Exception as exc:
            route_logger.exception("[bind/link/open] unexpected error")
            raise HTTPException(status_code=500, detail=f"打开绑卡链接失败: {exc}") from exc

    return router
