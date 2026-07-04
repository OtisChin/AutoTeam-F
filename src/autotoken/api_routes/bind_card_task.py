"""Card binding task launch route."""

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import AliasChoices, BaseModel, Field


class BindCardTaskParams(BaseModel):
    email: str
    card_item_id: str
    checkout_url: str
    proxy_url: str | None = None
    proxy_label: str = ""
    proxy_api_provider: str = Field("", validation_alias=AliasChoices("proxy_api_provider", "proxyApiProvider"))
    proxy_api_url: str = Field("", validation_alias=AliasChoices("proxy_api_url", "proxyApiUrl"))
    proxy_api_country: str = Field("US", validation_alias=AliasChoices("proxy_api_country", "proxyApiCountry"))
    proxy_bypass: str | None = None
    roxybrowser_workspace_id: str = Field(
        "",
        validation_alias=AliasChoices("roxybrowser_workspace_id", "roxybrowserWorkspaceId"),
    )
    roxybrowser_profile_id: str = Field(
        "",
        validation_alias=AliasChoices(
            "roxybrowser_profile_id", "roxybrowserProfileId", "roxybrowser_dir_id", "roxybrowserDirId"
        ),
    )
    roxybrowser_auto_create_profile: bool = Field(
        True,
        validation_alias=AliasChoices("roxybrowser_auto_create_profile", "roxybrowserAutoCreateProfile"),
    )
    manual_confirm: bool = False
    timeout_seconds: int = 900


def create_bind_card_task_router(
    *,
    start_task: Callable[..., dict[str, Any]],
    normalize_email: Callable[[str | None], str],
    resolve_status_auth_file: Callable[[dict], str | None],
    session_only_account_stub: Callable[[str], dict],
    is_bind_card_reusable_result: Callable[[dict], bool],
    current_task_id_for_group: Callable[[], str | None],
    append_task_progress: Callable[[str | None, dict], Any],
    task_result_error: type[Exception],
    task_group_bind_card: str,
    logger: Any,
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/tasks/bind-card", status_code=202)
    def post_bind_card_task(params: BindCardTaskParams):
        from autotoken.core import cancel_signal
        from autotoken.core.redaction import safe_proxy_summary
        from autotoken.payments.bind_audit import record_bind_audit
        from autotoken.payments.bind_executor import run_bind_task
        from autotoken.payments.card_pool import finalize_card_binding, find_item, reserve_card_item
        from autotoken.services import proxy_runtime
        from autotoken.settings.config import normalize_proxy_url
        from autotoken.storage.accounts import (
            ensure_session_only_account,
            find_account,
            load_accounts,
            update_account,
        )
        from autotoken.storage.auth_session_store import get_auth_session_file

        email = normalize_email(params.email)
        checkout_url = str(params.checkout_url or "").strip()
        if not email:
            raise HTTPException(status_code=400, detail="email 不能为空")
        if not params.card_item_id:
            raise HTTPException(status_code=400, detail="card_item_id 不能为空")
        if not checkout_url:
            raise HTTPException(status_code=400, detail="checkout_url 不能为空")

        accounts = load_accounts()
        account = find_account(accounts, email)
        if not account:
            auth_session_file = get_auth_session_file(email)
            if auth_session_file and Path(auth_session_file).exists():
                account = ensure_session_only_account(email) or session_only_account_stub(email)
            else:
                raise HTTPException(status_code=404, detail="账号不存在")
        if not resolve_status_auth_file(account):
            raise HTTPException(status_code=400, detail="该账号缺少可用 auth_session/auth_file")

        card_item = find_item("card", params.card_item_id)
        if not card_item:
            raise HTTPException(status_code=404, detail="卡记录不存在")
        if card_item.get("status") != "unused":
            raise HTTPException(status_code=400, detail=f"卡当前状态为 {card_item.get('status')}，不可用于绑卡")

        def _run():
            task_id = current_task_id_for_group() or ""
            started_at = time.time()
            reserved = False
            result = None

            try:
                effective_proxy_url = str(params.proxy_url or "").strip()
                proxy_api_provider = (
                    proxy_runtime.normalize_proxy_api_provider(params.proxy_api_provider)
                    if str(params.proxy_api_provider or "").strip()
                    else ""
                )
                proxy_api_url = str(params.proxy_api_url or "").strip()
                proxy_api_country = "".join(
                    ch for ch in str(params.proxy_api_country or "US").strip().upper() if ch.isalpha()
                )[:2] or "US"
                if proxy_api_url and not proxy_api_provider:
                    proxy_api_provider = proxy_runtime.infer_proxy_api_provider_from_url(proxy_api_url)
                if proxy_api_provider and not proxy_api_url:
                    proxy_api_url = proxy_runtime.default_paypal_proxy_api_url(
                        proxy_api_provider,
                        country=proxy_api_country,
                    )
                if proxy_api_url:
                    proxy_api_url = proxy_runtime.proxy_api_url_with_region(proxy_api_url, proxy_api_country)
                    fetched_proxy = proxy_runtime.fetch_proxy_from_api_url(
                        proxy_api_url,
                        default_auth_scheme="socks5h",
                        provider=proxy_api_provider or "cliproxy",
                    )
                    if fetched_proxy:
                        effective_proxy_url = fetched_proxy
                    elif effective_proxy_url:
                        effective_proxy_url = normalize_proxy_url(effective_proxy_url, default_auth_scheme="socks5h")
                    else:
                        raise RuntimeError("Cliproxy API 未返回可用代理；请检查 Cliproxy API 地址、白名单或套餐配置")
                    append_task_progress(
                        task_id,
                        {
                            "stage": "bind_proxy_api_selected",
                            "email": email,
                            "proxy_label": params.proxy_label,
                            "proxy_api_provider": proxy_api_provider or "",
                            "proxy_api_country": proxy_api_country,
                            "proxy_api_url_present": True,
                            "message": (
                                f"已通过 {proxy_api_provider or 'cliproxy'} API 获取绑卡代理"
                                f"({proxy_api_country}): {safe_proxy_summary(effective_proxy_url)}"
                            ),
                        },
                    )

                reserved_item = reserve_card_item(
                    params.card_item_id,
                    account_email=email,
                    proxy_label=params.proxy_label,
                    checkout_url=checkout_url,
                    task_id=task_id,
                )
                if not reserved_item:
                    raise RuntimeError("预占绑卡卡片失败：记录不存在")
                reserved = True

                append_task_progress(
                    task_id,
                    {
                        "stage": "binding",
                        "email": email,
                        "card_item_id": params.card_item_id,
                        "proxy_label": params.proxy_label,
                    },
                )

                result = run_bind_task(
                    email=email,
                    checkout_url=checkout_url,
                    card_item=reserved_item,
                    proxy_url=effective_proxy_url,
                    proxy_bypass=params.proxy_bypass,
                    use_roxybrowser=True,
                    roxybrowser_workspace_id=params.roxybrowser_workspace_id,
                    roxybrowser_profile_id=params.roxybrowser_profile_id,
                    roxybrowser_auto_create_profile=params.roxybrowser_auto_create_profile,
                    manual_confirm=params.manual_confirm,
                    timeout_seconds=max(60, int(params.timeout_seconds or 900)),
                    is_cancelled=cancel_signal.is_cancelled,
                )
            except Exception as exc:
                logger.exception("[bind-card] unexpected error")
                result = {
                    "status": "failed",
                    "failure_stage": "post_submit",
                    "message": f"绑卡任务执行异常: {exc}",
                    "screenshot_paths": [],
                }

            result = dict(result or {})
            result.setdefault("status", "failed")
            result.setdefault("failure_stage", "")
            result.setdefault("message", "")
            result.setdefault("screenshot_paths", [])
            result["email"] = email
            result["card_item_id"] = params.card_item_id
            result["checkout_url"] = checkout_url
            result["proxy_label"] = params.proxy_label
            result["proxy_api_provider"] = params.proxy_api_provider or ""
            result["proxy_api_country"] = params.proxy_api_country or ""
            result["manual_confirm"] = params.manual_confirm

            if cancel_signal.is_cancelled() and result.get("status") != "success":
                task_status = "cancelled"
            elif result.get("status") == "success":
                task_status = "completed"
            else:
                task_status = "failed"
            result["task_status"] = task_status

            if reserved:
                final_card_item = finalize_card_binding(
                    params.card_item_id,
                    result_status="cancelled" if task_status == "cancelled" else result.get("status") or "failed",
                    failure_stage=result.get("failure_stage") or "",
                    message=result.get("message") or "",
                    account_email=email,
                    proxy_label=params.proxy_label,
                    checkout_url=checkout_url,
                    task_id=task_id,
                    reusable=is_bind_card_reusable_result(result),
                )
                result["card_status"] = (final_card_item or {}).get("status", "")

            update_account(
                email,
                last_bind_status="cancelled" if task_status == "cancelled" else result.get("status") or "failed",
                last_bind_at=time.time(),
                last_bind_provider="card",
                last_checkout_url=checkout_url,
                last_card_id=params.card_item_id,
                last_proxy_label=params.proxy_label,
                last_bind_task_id=task_id,
                last_bind_message=result.get("message") or "",
                last_bind_failure_stage=result.get("failure_stage") or "",
            )

            record_bind_audit(
                {
                    "task_id": task_id,
                    "email": email,
                    "card_item_id": params.card_item_id,
                    "checkout_url": checkout_url,
                    "proxy_label": params.proxy_label,
                    "proxy_url": params.proxy_url or "",
                    "proxy_api_provider": params.proxy_api_provider or "",
                    "proxy_api_country": params.proxy_api_country or "",
                    "proxy_api_url_present": bool(str(params.proxy_api_url or "").strip()),
                    "manual_confirm": params.manual_confirm,
                    "status": result.get("status") or "failed",
                    "task_status": task_status,
                    "failure_stage": result.get("failure_stage") or "",
                    "message": result.get("message") or "",
                    "started_at": started_at,
                    "finished_at": time.time(),
                    "screenshot_paths": result.get("screenshot_paths") or [],
                    "card_status": result.get("card_status") or "",
                }
            )

            append_task_progress(
                task_id,
                {
                    "stage": "completed",
                    "bind_status": result.get("status") or "failed",
                    "task_status": task_status,
                    "card_status": result.get("card_status") or "",
                },
            )

            if result.get("status") != "success":
                raise task_result_error(result.get("message") or "绑卡失败", task_result=result)
            return result

        return start_task("bind-card", _run, params.model_dump(), task_group=task_group_bind_card)

    return router
