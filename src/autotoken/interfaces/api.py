"""AutoToken HTTP API - 将 CLI 功能暴露为 HTTP 接口"""

import json
import logging
import os
import queue
import random
import re
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from autotoken.api_routes.account_cpa_auths import create_account_cpa_auths_router
from autotoken.api_routes.account_exports import create_account_exports_router
from autotoken.api_routes.account_hub import create_account_hub_router
from autotoken.api_routes.account_login import (
    AccountEmailBatchParams as _AccountEmailBatchParams,
)
from autotoken.api_routes.account_login import (
    LoginAccountParams as _LoginAccountParams,
)
from autotoken.api_routes.account_login import (
    create_account_login_router,
)
from autotoken.api_routes.account_management import create_account_management_router
from autotoken.api_routes.account_overview import create_account_overview_router
from autotoken.api_routes.account_refresh_quota import create_account_refresh_quota_router
from autotoken.api_routes.account_register_task import (
    ManualRegisterParams as _ManualRegisterParams,
)
from autotoken.api_routes.account_register_task import (
    create_account_register_task_router,
)
from autotoken.api_routes.admin_maintenance import create_admin_maintenance_router
from autotoken.api_routes.auto_config import create_auto_config_router
from autotoken.api_routes.bind_card_task import (
    BindCardTaskParams as _BindCardTaskParams,
)
from autotoken.api_routes.bind_card_task import (
    create_bind_card_task_router,
)
from autotoken.api_routes.bind_link import create_bind_link_router
from autotoken.api_routes.card_pool import create_card_pool_router
from autotoken.api_routes.config_io import create_config_io_router
from autotoken.api_routes.cpa_to_sub2api import create_cpa_to_sub2api_router
from autotoken.api_routes.finished_account_import import create_finished_account_import_router
from autotoken.api_routes.gopay_auto_signup_config import (
    create_gopay_auto_signup_config_router,
)
from autotoken.api_routes.gopay_auto_signup_config import (
    gopay_auto_signup_env as _gopay_auto_signup_env,
)
from autotoken.api_routes.gopay_auto_signup_config import (
    normalize_gopay_auto_signup_mode as _normalize_gopay_auto_signup_mode,
)
from autotoken.api_routes.gopay_auto_signup_config import (
    normalize_gopay_auto_signup_sms_provider as _normalize_gopay_auto_signup_sms_provider,
)
from autotoken.api_routes.gopay_pro_config import (
    GoPayProConfigParams as _GoPayProConfigParams,
)
from autotoken.api_routes.gopay_pro_config import (
    GoPayProNumbersParams as _GoPayProNumbersParams,
)
from autotoken.api_routes.gopay_pro_config import (
    GoPayProSlotParams as _GoPayProSlotParams,
)
from autotoken.api_routes.gopay_pro_config import (
    create_gopay_pro_config_router,
)
from autotoken.api_routes.gopay_pro_tasks import (
    GoPayProBatchParams as _GoPayProBatchParams,
)
from autotoken.api_routes.gopay_pro_tasks import (
    GoPayProTaskParams as _GoPayProTaskParams,
)
from autotoken.api_routes.gopay_pro_tasks import (
    create_gopay_pro_tasks_router,
)
from autotoken.api_routes.interactive_login import (
    AdminCodeParams as _AdminCodeParams,
)
from autotoken.api_routes.interactive_login import (
    AdminEmailParams as _AdminEmailParams,
)
from autotoken.api_routes.interactive_login import (
    AdminPasswordParams as _AdminPasswordParams,
)
from autotoken.api_routes.interactive_login import (
    AdminSessionParams as _AdminSessionParams,
)
from autotoken.api_routes.interactive_login import (
    AdminWorkspaceParams as _AdminWorkspaceParams,
)
from autotoken.api_routes.interactive_login import (
    ManualAccountCallbackParams as _ManualAccountCallbackParams,
)
from autotoken.api_routes.interactive_login import (
    ManualAccountStartParams as _ManualAccountStartParams,
)
from autotoken.api_routes.interactive_login import (
    clean_required_code as _interactive_clean_required_code,
)
from autotoken.api_routes.interactive_login import (
    create_interactive_login_router,
)
from autotoken.api_routes.mail_provider_config import create_mail_provider_config_router
from autotoken.api_routes.oauth_phone_pool import create_oauth_phone_pool_router
from autotoken.api_routes.oauth_phone_sms_config import (
    create_oauth_phone_sms_config_router,
)
from autotoken.api_routes.oauth_phone_sms_config import (
    normalize_oauth_hero_sms_country as _normalize_oauth_hero_sms_country,
)
from autotoken.api_routes.oauth_phone_sms_config import (
    normalize_oauth_phone_sms_provider as _normalize_oauth_phone_sms_provider,
)
from autotoken.api_routes.oauth_phone_sms_config import (
    normalize_oauth_smsbower_country as _normalize_oauth_smsbower_country,
)
from autotoken.api_routes.oauth_phone_sms_config import (
    oauth_phone_sms_env as _oauth_phone_sms_env,
)
from autotoken.api_routes.payment_task_models import (
    GoPayBindTaskParams as _GoPayBindTaskParams,
)
from autotoken.api_routes.payment_task_models import (
    GoPayPhoneAccountParams as _GoPayPhoneAccountParams,
)
from autotoken.api_routes.payment_task_models import (
    PayPalTaskParams as _PayPalTaskParams,
)
from autotoken.api_routes.paypal_ice import create_paypal_ice_router, repair_paypal_ice_account_bind_metadata
from autotoken.api_routes.paypal_ice_phone_pool import create_paypal_ice_phone_pool_router
from autotoken.api_routes.paypal_sms_config import create_paypal_sms_config_router
from autotoken.api_routes.register_domain import create_register_domain_router
from autotoken.api_routes.rekberinaja_config import create_rekberinaja_config_router
from autotoken.api_routes.roxybrowser_config import create_roxybrowser_config_router
from autotoken.api_routes.setup import create_setup_router
from autotoken.api_routes.status import create_status_router
from autotoken.api_routes.support import create_support_router
from autotoken.api_routes.task_actions import (
    CheckParams as _CheckParams,
)
from autotoken.api_routes.task_actions import (
    CleanupParams as _CleanupParams,
)
from autotoken.api_routes.task_actions import (
    ReplaceParams as _ReplaceParams,
)
from autotoken.api_routes.task_actions import (
    TaskParams as _TaskParams,
)
from autotoken.api_routes.task_actions import (
    create_task_actions_router,
)
from autotoken.api_routes.task_control import (
    GoPayRuntimeControlParams as _GoPayRuntimeControlParams,
)
from autotoken.api_routes.task_control import (
    TaskControlParams as _TaskControlParams,
)
from autotoken.api_routes.task_control import (
    create_task_control_router,
)
from autotoken.api_routes.team_members import create_team_members_router
from autotoken.api_routes.trade import create_trade_router
from autotoken.api_routes.whatsapp_otp import create_whatsapp_otp_router
from autotoken.core.files import (
    active_non_comment_lines,
    append_unique_non_comment_lines,
    read_json_file,
    read_lines_file,
    write_json_atomic,
)
from autotoken.core.normalization import normalized_email as _core_normalized_email
from autotoken.core.redaction import (
    compact_log_text as _compact_log_text,
)
from autotoken.core.redaction import (
    safe_email_summary as _safe_email_summary,
)
from autotoken.core.redaction import (
    safe_phone_summary as _safe_phone_summary,
)
from autotoken.core.redaction import (
    safe_proxy_summary as _safe_proxy_summary,
)
from autotoken.core.redaction import (
    safe_url_summary as _safe_url_summary,
)
from autotoken.services import account_cpa_auth as account_cpa_auth_service
from autotoken.services import account_delete_audit as account_delete_audit_service
from autotoken.services import account_oauth_results as account_oauth_results_service
from autotoken.services import account_pool_cleanup as account_pool_cleanup_service
from autotoken.services import account_presentation as account_presentation_service
from autotoken.services import account_session_stubs as account_session_stubs_service
from autotoken.services import api_helpers as api_helpers_service
from autotoken.services import chatgpt_session as chatgpt_session_service
from autotoken.services import checkout_response as checkout_response_service
from autotoken.services import gopay_pending_retry as gopay_pending_retry_service
from autotoken.services import gopay_pro_accounts as gopay_pro_accounts_service
from autotoken.services import gopay_pro_events as gopay_pro_events_service
from autotoken.services import gopay_pro_pool as gopay_pro_pool_service
from autotoken.services import gopay_pro_task_payloads as gopay_pro_task_payloads_service
from autotoken.services import gopay_runtime as gopay_runtime_service
from autotoken.services import gopay_task_payloads as gopay_task_payloads_service
from autotoken.services import gopay_wallet_pool as gopay_wallet_pool_service
from autotoken.services import payment_results as payment_results_service
from autotoken.services import paypal_billing_agreement as paypal_ba_service
from autotoken.services import paypal_pending_retry as paypal_pending_retry_service
from autotoken.services import paypal_phone_pool as paypal_phone_pool_service
from autotoken.services import paypal_preflight as paypal_preflight_service
from autotoken.services import paypal_proxy as paypal_proxy_service
from autotoken.services import paypal_task_payloads as paypal_task_payloads_service
from autotoken.services import proxy_runtime as proxy_runtime_service
from autotoken.services.task_runtime import (
    TASK_GROUP_BIND_CARD,
    TASK_GROUP_DEFAULT,
    TASK_GROUP_GOPAY,
    TASK_GROUP_PAYPAL,
    TASK_GROUP_QUOTA,
    TASK_GROUP_REGISTER,
    TASK_GROUP_TEAM,
    acquire_task_run_slot,
    acquire_task_start_slot,
    activate_current_task_index,
    append_live_task_progress,
    bind_task_thread_context,
    busy_task_detail,
    cancel_orphaned_task_snapshots,
    clear_task_runtime_state,
    clear_task_thread_context,
    current_task_id_for_group,
    drain_gopay_pending_account_emails,
    ensure_task_cancel_event,
    execute_task_callable,
    init_gopay_runtime_control,
    interrupted_task_snapshot,
    launch_task_thread,
    load_task_snapshots,
    mark_task_run_finished,
    mark_task_run_prestart_cancelled,
    mark_task_running,
    merged_task_snapshots,
    normalize_task_group,
    persist_task_snapshot,
    prepare_task_start,
    process_is_running,
    register_task_cancel_hook,
    release_task_run_slot,
    rollback_task_start,
    run_task_cancel_hooks,
    running_task_for_group,
    runtime_control,
    task_group_lock,
)
from autotoken.services.task_runtime import (
    TASK_GROUP_OAUTH as _TASK_GROUP_OAUTH,
)
from autotoken.settings.config import API_KEY, PAYPAL_PROXY_DEFAULT_SCHEME, normalize_proxy_url
from autotoken.storage.auth_files import read_auth_json_file

logger = logging.getLogger(__name__)
TaskParams = _TaskParams
CleanupParams = _CleanupParams
CheckParams = _CheckParams
ReplaceParams = _ReplaceParams
TaskControlParams = _TaskControlParams
GoPayRuntimeControlParams = _GoPayRuntimeControlParams
BindCardTaskParams = _BindCardTaskParams
GoPayPhoneAccountParams = _GoPayPhoneAccountParams
GoPayBindTaskParams = _GoPayBindTaskParams
PayPalTaskParams = _PayPalTaskParams
LoginAccountParams = _LoginAccountParams
AccountEmailBatchParams = _AccountEmailBatchParams
GoPayProNumbersParams = _GoPayProNumbersParams
GoPayProConfigParams = _GoPayProConfigParams
GoPayProSlotParams = _GoPayProSlotParams
GoPayProTaskParams = _GoPayProTaskParams
GoPayProBatchParams = _GoPayProBatchParams
AdminEmailParams = _AdminEmailParams
AdminSessionParams = _AdminSessionParams
AdminPasswordParams = _AdminPasswordParams
AdminCodeParams = _AdminCodeParams
AdminWorkspaceParams = _AdminWorkspaceParams
ManualAccountCallbackParams = _ManualAccountCallbackParams
ManualAccountStartParams = _ManualAccountStartParams
ManualRegisterParams = _ManualRegisterParams
TASK_GROUP_OAUTH = _TASK_GROUP_OAUTH
_account_delete_audit_lock = threading.Lock()
_GOPAY_REUSABLE_WALLET_POOL_LOCK = gopay_wallet_pool_service.GOPAY_REUSABLE_WALLET_POOL_LOCK
_GOPAY_REUSABLE_WALLET_POOL = gopay_wallet_pool_service.GOPAY_REUSABLE_WALLET_POOL


def _env_float(name: str, default: float) -> float:
    return gopay_runtime_service.env_float(name, default)


def _gopay_auto_register_bind_delay_seconds() -> float:
    return gopay_runtime_service.auto_register_bind_delay_seconds()


def _gopay_auto_signup_no_transfer_bind_wait_seconds() -> float:
    return gopay_runtime_service.auto_signup_no_transfer_bind_wait_seconds()


def _gopay_auto_signup_no_transfer_retry_waits_seconds() -> list[float]:
    return gopay_runtime_service.auto_signup_no_transfer_retry_waits_seconds()


def _gopay_wallet_balance_poll_intervals_from_env() -> list[float]:
    return gopay_runtime_service.wallet_balance_poll_intervals_from_env()


def _default_gopay_wallet_balance_poll_interval_seconds() -> float:
    return gopay_runtime_service.default_wallet_balance_poll_interval_seconds()


def _default_gopay_wallet_balance_wait_seconds() -> float:
    return gopay_runtime_service.default_wallet_balance_wait_seconds()


def _normalize_gopay_runtime_seconds(
    value: int | float | str | None,
    default: int | float,
    *,
    minimum: float = 0.0,
    maximum: float = 1800.0,
) -> float:
    return gopay_runtime_service.normalize_runtime_seconds(value, default, minimum=minimum, maximum=maximum)


def _build_gopay_balance_poll_intervals(total_wait_seconds: float, interval_seconds: float) -> list[float]:
    return gopay_runtime_service.build_balance_poll_intervals(total_wait_seconds, interval_seconds)


def _gopay_auto_signup_prefetch_wallets() -> int:
    return gopay_runtime_service.auto_signup_prefetch_wallets()


def _default_whatsapp_otp_url() -> str:
    return gopay_runtime_service.default_whatsapp_otp_url()


def _request_public_base_url(request: Request | None) -> str:
    return api_helpers_service.request_public_base_url(request)


def _rewrite_local_gopay_signup_url_for_base(sms_url: str, base_url: str) -> str:
    return gopay_runtime_service.rewrite_local_signup_url_for_base(sms_url, base_url)


def _rewrite_phone_account_sms_url_for_base(account: dict[str, Any], base_url: str) -> dict[str, Any]:
    return gopay_runtime_service.rewrite_phone_account_sms_url_for_base(account, base_url)


def _mask_gopay_phone_for_log(phone: str) -> str:
    return gopay_runtime_service.mask_phone_for_log(phone)


def _normalized_gopay_pool_country(value: Any) -> str:
    return gopay_runtime_service.normalized_pool_country(value)


def _gopay_reusable_wallet_ttl_seconds() -> int:
    return gopay_wallet_pool_service.reusable_wallet_ttl_seconds()


def _gopay_wallet_phone(wallet: Any) -> str:
    return gopay_wallet_pool_service.wallet_phone(wallet)


def _paypal_preflight_sms_source(
    *,
    params: Any,
    paypal_mode: str,
    protocol_no_card: bool,
    sms_url: str,
    phone_accounts: list[dict],
) -> dict[str, Any]:
    if phone_accounts:
        return {"ok": True, "source": "phone_accounts", "provider": "", "missing": []}
    if str(sms_url or "").strip():
        missing = [] if str(getattr(params, "billing_phone", "") or "").strip() else ["billing_phone"]
        return {"ok": not missing, "source": "request_sms_url", "provider": "", "missing": missing}
    if paypal_mode != "create_account" or not protocol_no_card:
        return {"ok": True, "source": "not_required", "provider": "", "missing": []}
    try:
        explicit_phone = paypal_phone_pool_service.explicit_paypal_phone_account_from_env()
    except ValueError as exc:
        return {"ok": False, "source": "explicit_env", "provider": "explicit_env", "missing": [str(exc)]}
    if explicit_phone:
        return {"ok": True, "source": "explicit_env", "provider": "explicit_env", "missing": []}

    from autotoken.api_routes.paypal_sms_config import paypal_sms_env

    cfg = paypal_sms_env()
    provider = str(cfg.get("provider") or "").strip()
    provider_secret_present = {
        "hero_sms": bool(cfg.get("hero_sms_api_key")),
        "smsbower": bool(cfg.get("smsbower_api_key")),
        "smscode": bool(cfg.get("smscode_api_token")),
        "smscloud": bool(cfg.get("smscloud_xi_token")),
    }
    if provider in provider_secret_present and provider_secret_present[provider]:
        return {"ok": True, "source": "auto_provision", "provider": provider, "missing": []}
    return {
        "ok": False,
        "source": "missing",
        "provider": provider,
        "missing": ["sms_url/phone_accounts or PAYPAL_SMS_URL/PAYPAL_PHONE_NUMBER or PayPal SMS provider config"],
    }


def _paypal_task_preflight_payload(params: PayPalTaskParams) -> dict[str, Any]:
    missing: list[str] = []
    checks: dict[str, Any] = {}
    try:
        paypal_preflight_service.validate_paypal_timeout_seconds(params.timeout_seconds)
        paypal_preflight_service.normalize_paypal_runner_mode(params.runner_mode)
        paypal_mode = paypal_preflight_service.normalize_paypal_mode(params.paypal_mode)
    except ValueError as exc:
        return {"kind": "paypal_preflight", "ok": False, "mode": "", "checks": {}, "missing": [str(exc)]}

    paypal_inputs = paypal_preflight_service.normalize_paypal_task_inputs(
        params=params,
        normalize_email=_normalized_email,
    )
    email = paypal_inputs["email"]
    account_emails = paypal_inputs["account_emails"]
    checkout_url = paypal_inputs["checkout_url"]
    sms_url = paypal_inputs["sms_url"]
    otp_channel = paypal_inputs["otp_channel"]
    direct_ba_pre_extracted = None
    try:
        direct_ba_pre_extracted = paypal_ba_service.paypal_direct_ba_pre_extracted(
            params,
            fallback_checkout_url=checkout_url,
        )
    except ValueError as exc:
        missing.append(str(exc))
    try:
        paypal_options = paypal_preflight_service.normalize_paypal_runtime_options(
            paypal_mode=paypal_mode,
            paypal_browser=params.paypal_browser,
            paypal_fallback_browser=params.paypal_fallback_browser,
            paypal_region=params.paypal_region,
            paypal_country=params.paypal_country,
            billing_country=params.billing_country,
            paypal_lang=params.paypal_lang,
            bind_link_payload=params.bind_link_payload,
            roxybrowser_workspace_id=params.roxybrowser_workspace_id,
            roxybrowser_profile_id=params.roxybrowser_profile_id,
            roxybrowser_auto_create_profile=params.roxybrowser_auto_create_profile,
            paypal_card_number=params.paypal_card_number,
            paypal_card_expiry=params.paypal_card_expiry,
            paypal_card_cvv=params.paypal_card_cvv,
        )
    except ValueError as exc:
        paypal_options = {"protocol_no_card": False, "bind_link_payload": {}}
        missing.append(str(exc))
    protocol_no_card = bool(paypal_options.get("protocol_no_card"))
    bind_link_payload = paypal_options.get("bind_link_payload") or {}
    checks["email"] = bool(email)
    if not email:
        missing.append("email")
    checks["direct_ba_link"] = bool(direct_ba_pre_extracted)
    checks["browser_fallback"] = bool(paypal_options.get("paypal_fallback_browser"))
    checks["checkout_reference"] = bool(
        direct_ba_pre_extracted
        and (
            direct_ba_pre_extracted.get("checkout_session_id")
            or direct_ba_pre_extracted.get("checkout_url")
            or direct_ba_pre_extracted.get("hosted_checkout_url")
        )
    )
    if direct_ba_pre_extracted and account_emails:
        missing.append("direct BA/link mode supports only one account")
    if direct_ba_pre_extracted and (paypal_mode != "create_account" or not protocol_no_card):
        missing.append("direct BA/link mode requires create_account + protocol/no-card")
    if not direct_ba_pre_extracted and not checkout_url and not bind_link_payload:
        missing.append("checkout_url or bind_link_payload")

    try:
        phone_account_result = paypal_phone_pool_service.normalize_paypal_phone_accounts(
            list(params.phone_accounts or []),
            otp_channel=otp_channel,
        )
        phone_accounts = phone_account_result["phone_accounts"]
        if phone_accounts:
            sms_url = phone_account_result["sms_url"]
    except ValueError as exc:
        phone_accounts = []
        missing.append(str(exc))
    sms_check = _paypal_preflight_sms_source(
        params=params,
        paypal_mode=paypal_mode,
        protocol_no_card=protocol_no_card,
        sms_url=sms_url,
        phone_accounts=phone_accounts,
    )
    checks["sms"] = bool(sms_check.get("ok"))
    missing.extend(str(item) for item in sms_check.get("missing") or [])

    from autotoken.storage.accounts import find_account, load_accounts
    from autotoken.storage.auth_session_store import get_auth_session_file

    account_ok = False
    auth_file_ok = False
    if email:
        accounts = load_accounts()
        account = find_account(accounts, email)
        if account:
            account_ok = True
            auth_file_ok = bool(_resolve_status_auth_file(account))
        else:
            auth_session_file = get_auth_session_file(email)
            account_ok = bool(auth_session_file and Path(auth_session_file).exists())
            auth_file_ok = account_ok
    checks["account"] = account_ok
    checks["auth_file"] = auth_file_ok
    if email and not account_ok:
        missing.append(f"local account/auth_session for {email}")
    elif email and not auth_file_ok:
        missing.append(f"auth_session/auth_file for {email}")

    needs_access_token = bool((protocol_no_card or not checkout_url) and not direct_ba_pre_extracted)
    if needs_access_token and email:
        access_token = _extract_account_access_token(email)
        checks["local_access_token"] = bool(access_token)
        if not access_token:
            missing.append(f"local access token for {email}")
    elif direct_ba_pre_extracted:
        checks["local_access_token"] = "not_required"
    else:
        checks["local_access_token"] = "not_checked"

    mode = "direct_ba" if direct_ba_pre_extracted else ("protocol_extract_ba" if protocol_no_card else "browser")
    deduped_missing = list(dict.fromkeys(item for item in missing if item))
    return {
        "kind": "paypal_preflight",
        "ok": not deduped_missing,
        "mode": mode,
        "checks": checks,
        "sms_source": sms_check.get("source") or "",
        "sms_provider": sms_check.get("provider") or "",
        "missing": deduped_missing,
    }


def _gopay_wallet_bridge_token(wallet: Any) -> str:
    return gopay_wallet_pool_service.wallet_bridge_token(wallet)


def _gopay_wallet_account(wallet: Any) -> dict[str, Any]:
    return gopay_wallet_pool_service.wallet_account(wallet)


def _prune_gopay_reusable_wallet_pool(now: float | None = None) -> None:
    gopay_wallet_pool_service.prune_reusable_wallet_pool(now)


def _push_gopay_reusable_wallet(
    wallet: Any,
    *,
    task_id: str = "",
    run_id: str = "",
    created_at: float | None = None,
    funded: bool = False,
) -> dict[str, Any] | None:
    return gopay_wallet_pool_service.push_reusable_wallet(
        wallet,
        task_id=task_id,
        run_id=run_id,
        created_at=created_at,
        funded=funded,
    )


def _pop_gopay_reusable_wallet(*, gopay_pin: str, country_code: str = "62") -> dict[str, Any] | None:
    return gopay_wallet_pool_service.pop_reusable_wallet(gopay_pin=gopay_pin, country_code=country_code)


def _safe_url_for_log(url: str) -> str:
    return api_helpers_service.safe_url_for_log(url)


@asynccontextmanager
async def _api_lifespan(_app: FastAPI):
    _start_auto_check()
    from autotoken.auth.codex_auth import start_oauth_hero_sms_cancel_reconciler, stop_oauth_hero_sms_cancel_reconciler

    start_oauth_hero_sms_cancel_reconciler()
    try:
        yield
    finally:
        stop_oauth_hero_sms_cancel_reconciler()
        _stop_auto_check()


app = FastAPI(
    title="AutoToken API",
    description="ChatGPT Team 账号自动轮转管理 API",
    version="0.1.0",
    lifespan=_api_lifespan,
)

_cors_origins = [
    origin.strip() for origin in str(os.environ.get("PLUS_EXTRACTOR_CORS_ORIGINS") or "*").split(",") if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["*"],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# API Key 鉴权中间件
# ---------------------------------------------------------------------------

_AUTH_SKIP_PATHS = {
    "/api/auth/check",
    "/api/setup/status",
    "/api/setup/save",
    "/api/account-hub/ping",
    "/api/account-hub/ingest",
    "/api/public/plus-extractor/redeem",
    "/api/public/plus-extractor/query",
    "/api/public/plus-extractor/history",
    "/api/public/plus-extractor/history/download",
    "/api/public/plus-extractor/cdk-status",
    "/api/public/plus-extractor/set-password",
}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS":
        return await call_next(request)
    # 不鉴权的路径：非 /api 路径、auth/check 端点
    if not path.startswith("/api/") or path in _AUTH_SKIP_PATHS:
        return await call_next(request)
    # 未配置 API_KEY 则跳过鉴权
    if not API_KEY:
        return await call_next(request)
    # 从 header 或 query param 获取 key
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    else:
        token = request.query_params.get("key", "")
    if token != API_KEY:
        return JSONResponse(status_code=401, content={"detail": "未授权，请提供有效的 API Key"})
    return await call_next(request)


def _get_api_key() -> str:
    return API_KEY


def _set_api_key(value: str) -> None:
    global API_KEY
    API_KEY = value


app.include_router(create_setup_router(get_api_key=_get_api_key, set_api_key=_set_api_key))
app.include_router(create_mail_provider_config_router())


def _mask_secret_for_config(value: str) -> str:
    return api_helpers_service.mask_secret_for_config(value)


app.include_router(create_roxybrowser_config_router(mask_secret=_mask_secret_for_config))
app.include_router(create_rekberinaja_config_router(mask_secret=_mask_secret_for_config))
app.include_router(create_oauth_phone_sms_config_router(mask_secret=_mask_secret_for_config))
app.include_router(create_gopay_auto_signup_config_router(mask_secret=_mask_secret_for_config))
app.include_router(create_paypal_sms_config_router(mask_secret=_mask_secret_for_config))
app.include_router(
    create_paypal_ice_router(
        mask_secret=_mask_secret_for_config,
        start_oauth_login=lambda payload: post_account_login(_LoginAccountParams(**payload)),
        get_task=lambda task_id: _tasks.get(task_id)
        or next(
            (task for task in _merged_task_snapshots(compact=False) if str(task.get("task_id") or "") == task_id),
            None,
        ),
    )
)
app.include_router(create_paypal_ice_phone_pool_router())


# ---------------------------------------------------------------------------
# 后台任务管理
# ---------------------------------------------------------------------------

_tasks: dict[str, dict] = {}
_playwright_lock = threading.Lock()
_current_task_id: str | None = None
_task_context = threading.local()
_task_group_locks: dict[str, threading.Lock] = {}
_current_task_ids: dict[str, str | None] = {}
_task_skip_signals: dict[str, threading.Event] = {}
_task_cancel_signals: dict[str, threading.Event] = {}
_task_cancel_hooks: dict[str, list[Callable[[], None]]] = {}
_task_cancel_hooks_lock = threading.RLock()
_task_runtime_controls: dict[str, dict[str, Any]] = {}
_task_runtime_controls_lock = threading.RLock()
_admin_login_api = None
_admin_login_step: str | None = None
_main_codex_flow = None
_main_codex_step: str | None = None
_manual_account_flow = None
MAX_TASK_HISTORY = 50


def _task_group_lock(task_group: str) -> threading.Lock:
    return task_group_lock(_task_group_locks, task_group, lock_factory=threading.Lock)


def _normalize_task_group(task_group: str | None, command: str = "") -> str:
    return normalize_task_group(task_group, command)


def _running_task_for_group(task_group: str | None) -> dict:
    return running_task_for_group(_tasks, _current_task_ids, task_group)


def _current_task_id_for_group(task_group: str | None = None, *, fallback_task_id: str | None = None) -> str | None:
    return current_task_id_for_group(
        thread_task_id=getattr(_task_context, "task_id", None),
        fallback_task_id=fallback_task_id,
        current_task_ids=_current_task_ids,
        current_task_id=_current_task_id,
        task_group=task_group,
    )


def _log_task_cancel_hook_error(task_id: str, stage: str) -> None:
    if stage == "late_registration":
        logger.exception("[API] task cancel hook failed after late registration: task=%s", task_id[:8])
    else:
        logger.exception("[API] task cancel hook failed: task=%s", task_id[:8])


def _register_task_cancel_hook(task_id: str, hook: Callable[[], None]) -> Callable[[], None]:
    """Register a best-effort callback that runs as soon as a task is cancelled."""
    return register_task_cancel_hook(
        _task_cancel_hooks,
        _task_cancel_signals,
        _task_cancel_hooks_lock,
        task_id,
        hook,
        on_error=_log_task_cancel_hook_error,
    )


def _run_task_cancel_hooks(task_id: str) -> None:
    run_task_cancel_hooks(_task_cancel_hooks, _task_cancel_hooks_lock, task_id, on_error=_log_task_cancel_hook_error)


def _clear_task_runtime_controls(task_id: str) -> None:
    clear_task_runtime_state(
        task_id,
        skip_signals=_task_skip_signals,
        cancel_signals=_task_cancel_signals,
        cancel_hooks=_task_cancel_hooks,
        cancel_hooks_lock=_task_cancel_hooks_lock,
        controls=_task_runtime_controls,
        controls_lock=_task_runtime_controls_lock,
    )


# ---------------------------------------------------------------------------
# Playwright 专用线程执行器（解决跨线程调用问题）
# ---------------------------------------------------------------------------

import queue as _queue


class _PlaywrightExecutor:
    """将 Playwright 操作派发到专用线程执行，避免跨线程错误"""

    def __init__(self):
        self._queue: _queue.Queue = _queue.Queue()
        self._thread: threading.Thread | None = None

    def _worker(self):
        while True:
            item = self._queue.get()
            if item is None:
                break
            func, args, kwargs, result_event, result_holder = item
            try:
                result_holder["result"] = func(*args, **kwargs)
            except Exception as e:
                result_holder["error"] = e
            finally:
                result_event.set()

    def ensure_started(self):
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._worker, daemon=True)
            self._thread.start()

    def run(self, func, *args, **kwargs):
        """在专用线程中执行函数，阻塞等待结果(默认 5 分钟)"""
        return self.run_with_timeout(300, func, *args, **kwargs)

    def run_with_timeout(self, timeout: float, func, *args, **kwargs):
        """
        明确指定超时时间(秒)。适用于批量/长耗时操作。

        注意:超时后 worker 线程仍会继续跑完当前 func(Playwright 操作无法安全中断),
        后续通过 _pw_executor 提交的调用会在队列里等它自然完成。调用方需要自己
        确保不会越过 _playwright_lock 边界并发触发这种情况。
        """
        self.ensure_started()
        result_event = threading.Event()
        result_holder: dict = {}
        self._queue.put((func, args, kwargs, result_event, result_holder))
        if not result_event.wait(timeout=timeout):
            raise TimeoutError(
                f"Playwright executor timed out after {timeout}s while running {getattr(func, '__name__', repr(func))}"
            )
        if "error" in result_holder:
            raise result_holder["error"]
        return result_holder.get("result")

    def stop(self):
        if self._thread and self._thread.is_alive():
            self._queue.put(None)
            self._thread.join(timeout=5)
            self._thread = None


_pw_executor = _PlaywrightExecutor()


class TaskResultError(RuntimeError):
    """允许任务以失败/取消状态结束，同时保留结构化结果。"""

    def __init__(self, message: str, *, task_result: dict | None = None):
        super().__init__(message)
        self.task_result = task_result


def _current_busy_detail(default_message: str, task_group: str | None = None):
    if _admin_login_api:
        return busy_task_detail(
            default_message,
            _tasks,
            _current_task_ids,
            current_task_id=_current_task_id,
            special_running_task={
                "task_id": "admin-login",
                "command": "admin-login",
                "started_at": None,
            },
        )

    if _main_codex_flow:
        return busy_task_detail(
            default_message,
            _tasks,
            _current_task_ids,
            current_task_id=_current_task_id,
            special_running_task={
                "task_id": "main-codex-sync",
                "command": "main-codex-sync",
                "started_at": None,
            },
        )

    return busy_task_detail(
        default_message,
        _tasks,
        _current_task_ids,
        current_task_id=_current_task_id,
        task_group=task_group,
    )


def _persist_task_snapshot(task: dict | None) -> None:
    try:
        persist_task_snapshot(task)
    except Exception:
        logger.debug("[tasks] failed to persist task snapshot", exc_info=True)


def _process_is_running(pid: int | None) -> bool:
    return process_is_running(pid)


def _cancel_orphaned_task_snapshots() -> int:
    """Mark persisted running tasks as cancelled when their owner process is gone."""
    try:
        return cancel_orphaned_task_snapshots()
    except Exception:
        logger.debug("[tasks] failed to cancel orphaned task snapshots", exc_info=True)
        return 0


def _interrupted_task_snapshot(data: dict, *, now: float | None = None) -> dict:
    return interrupted_task_snapshot(data, now=now)


def _load_task_snapshots(limit: int = MAX_TASK_HISTORY) -> list[dict]:
    try:
        return load_task_snapshots(limit)
    except Exception:
        logger.debug("[tasks] failed to load task snapshots", exc_info=True)
        return []


def _merged_task_snapshots(*, compact: bool = False) -> list[dict]:
    return merged_task_snapshots(_tasks, limit=MAX_TASK_HISTORY, compact=compact)


def _append_task_progress(task_id: str | None, progress: dict):
    """Append a progress event to a specific task, even from detached worker threads."""
    worker_label = str(getattr(_task_context, "gopay_worker_label", "") or "").strip()
    worker_index = int(getattr(_task_context, "gopay_worker_index", 0) or 0)
    task = append_live_task_progress(
        _tasks,
        task_id,
        progress,
        worker_label=worker_label,
        worker_index=worker_index,
    )
    if task:
        _persist_task_snapshot(task)


def _update_current_task_progress(progress: dict, task_group: str | None = None):
    """更新当前运行任务的实时进度。"""
    _append_task_progress(_current_task_id_for_group(task_group), progress)


def _bind_task_thread_context(task_id: str, task_group: str, cancel_event: threading.Event) -> None:
    from autotoken.core import cancel_signal

    bind_task_thread_context(
        _task_context,
        task_id=task_id,
        task_group=task_group,
        cancel_event=cancel_event,
        set_cancel_event=cancel_signal.set_current_event,
    )


def _clear_task_thread_context() -> None:
    from autotoken.core import cancel_signal

    clear_task_thread_context(
        _task_context,
        clear_cancel_event=cancel_signal.clear_current_event,
    )


def _run_task(task_id: str, func, pass_task_id: bool = False, *args, **kwargs):
    """在后台线程中执行任务"""
    from autotoken.core import cancel_signal

    global _current_task_id
    task = _tasks[task_id]
    task_group = str(task.get("task_group") or TASK_GROUP_DEFAULT)
    group_lock = _task_group_lock(task_group)

    run_slot = acquire_task_run_slot(task, task_group, group_lock)
    cancel_event = ensure_task_cancel_event(_task_cancel_signals, task_id, cancel_event_factory=threading.Event)
    _bind_task_thread_context(task_id, task_group, cancel_event)
    _current_task_id = activate_current_task_index(_current_task_ids, task_group, task_id)
    mark_task_running(task)
    if cancel_event.is_set():
        _current_task_id = mark_task_run_prestart_cancelled(
            task,
            task_id,
            current_task_ids=_current_task_ids,
            current_task_id=_current_task_id,
            task_group=task_group,
        )
        _persist_task_snapshot(task)
        _clear_task_thread_context()
        _clear_task_runtime_controls(task_id)
        release_task_run_slot(run_slot)
        return

    try:
        error = execute_task_callable(
            task,
            task_id,
            func,
            args,
            kwargs,
            pass_task_id=pass_task_id,
            is_cancelled=cancel_signal.is_cancelled,
        )
        if error:
            logger.error("[API] 任务 %s %s: %s", task_id[:8], task["status"], error)
    finally:
        _current_task_id = mark_task_run_finished(
            task,
            task_id,
            current_task_ids=_current_task_ids,
            current_task_id=_current_task_id,
            task_group=task_group,
        )
        _persist_task_snapshot(task)
        _clear_task_thread_context()
        _clear_task_runtime_controls(task_id)
        release_task_run_slot(run_slot)


def _run_task_nonexclusive(task_id: str, func, pass_task_id: bool = False, *args, **kwargs):
    """Run a task without occupying the global Playwright task lock."""
    from autotoken.core import cancel_signal

    task = _tasks[task_id]
    task_group = str(task.get("task_group") or TASK_GROUP_DEFAULT)
    cancel_event = ensure_task_cancel_event(_task_cancel_signals, task_id, cancel_event_factory=threading.Event)
    _bind_task_thread_context(task_id, task_group, cancel_event)
    mark_task_running(task)
    if cancel_event.is_set():
        mark_task_run_prestart_cancelled(task, task_id)
        _persist_task_snapshot(task)
        _clear_task_thread_context()
        _clear_task_runtime_controls(task_id)
        return

    try:
        error = execute_task_callable(
            task,
            task_id,
            func,
            args,
            kwargs,
            pass_task_id=pass_task_id,
            is_cancelled=cancel_signal.is_cancelled,
        )
        if error:
            logger.error("[API] 非独占任务 %s failed: %s", task_id[:8], error)
    finally:
        mark_task_run_finished(task, task_id)
        _persist_task_snapshot(task)
        _clear_task_thread_context()
        _clear_task_runtime_controls(task_id)


def _start_task(
    command: str,
    func,
    params: dict,
    *args,
    exclusive: bool = True,
    pass_task_id: bool = False,
    task_group: str | None = None,
    **kwargs,
) -> dict:
    """创建并启动后台任务，返回任务信息"""
    normalized_group = _normalize_task_group(task_group, command)
    start_slot = acquire_task_start_slot(
        _task_group_locks,
        normalized_group,
        exclusive=exclusive,
        lock_factory=threading.Lock,
    )
    if start_slot.conflict:
        raise HTTPException(
            status_code=409, detail=_current_busy_detail("同类任务正在执行，请等待完成后再试", normalized_group)
        )

    task = prepare_task_start(
        _tasks,
        _task_cancel_signals,
        command,
        params,
        task_group=normalized_group,
        exclusive=exclusive,
        group_lock_preacquired=start_slot.acquired,
        cancel_event_factory=threading.Event,
        max_history=MAX_TASK_HISTORY,
    )
    task_id = str(task["task_id"])
    _persist_task_snapshot(task)

    target = _run_task if exclusive else _run_task_nonexclusive
    launch_task_thread(
        thread_factory=threading.Thread,
        target=target,
        task_id=task_id,
        func=func,
        pass_task_id=pass_task_id,
        args=args,
        kwargs=kwargs,
        on_start_error=lambda: rollback_task_start(
            _tasks,
            task_id,
            start_slot,
            skip_signals=_task_skip_signals,
            cancel_signals=_task_cancel_signals,
            cancel_hooks=_task_cancel_hooks,
            cancel_hooks_lock=_task_cancel_hooks_lock,
            controls=_task_runtime_controls,
            controls_lock=_task_runtime_controls_lock,
        ),
    )

    return task


# ---------------------------------------------------------------------------
# 响应模型
# ---------------------------------------------------------------------------


def _clean_required_code(code: str) -> str:
    return _interactive_clean_required_code(code)


def _normalized_email(value: str | None) -> str:
    return _core_normalized_email(value)


app.include_router(create_account_hub_router(normalize_email=_normalized_email))
app.include_router(create_card_pool_router())
app.include_router(create_register_domain_router())
app.include_router(create_trade_router())
app.include_router(create_whatsapp_otp_router())


def _normalize_gopay_runtime_concurrency(value: int | str | None, default: int = 1) -> int:
    return gopay_runtime_service.normalize_runtime_concurrency(value, default)


def _gopay_runtime_control(task_id: str, *, create: bool = False) -> dict[str, Any]:
    return runtime_control(_task_runtime_controls, _task_runtime_controls_lock, task_id, create=create)


def _init_gopay_runtime_control(
    task_id: str,
    *,
    gopay_concurrency: int,
    sms_provider: str,
    account_emails: list[str],
    balance_poll_interval_seconds: int | float | str | None = None,
    transfer_balance_wait_seconds: int | float | str | None = None,
) -> dict[str, Any]:
    return init_gopay_runtime_control(
        _task_runtime_controls,
        _task_runtime_controls_lock,
        task_id,
        gopay_concurrency=_normalize_gopay_runtime_concurrency(gopay_concurrency, 1),
        sms_provider=_normalize_gopay_auto_signup_sms_provider(sms_provider or "smscloud"),
        account_emails=account_emails or [],
        balance_poll_interval_seconds=_normalize_gopay_runtime_seconds(
            balance_poll_interval_seconds,
            _default_gopay_wallet_balance_poll_interval_seconds(),
            maximum=300.0,
        ),
        transfer_balance_wait_seconds=_normalize_gopay_runtime_seconds(
            transfer_balance_wait_seconds,
            _default_gopay_wallet_balance_wait_seconds(),
            maximum=1800.0,
        ),
    )


def _is_main_account_email(email: str | None) -> bool:
    from autotoken.settings.admin_state import get_admin_email

    return bool(_normalized_email(email)) and _normalized_email(email) == _normalized_email(get_admin_email())


def _quota_snapshot_status(quota_info: dict | None) -> str:
    return account_presentation_service.quota_snapshot_status(quota_info)


def _resolve_status_auth_file(acc: dict) -> str:
    return account_presentation_service.resolve_status_auth_file(acc, is_main_account_email=_is_main_account_email)


def _resolve_codex_auth_file(acc: dict) -> str:
    return account_presentation_service.resolve_codex_auth_file(acc, normalize_email=_normalized_email)


def _valid_account_auth_file(acc: dict) -> str:
    return account_presentation_service.valid_account_auth_file(acc)


def _valid_token_item_auth_file(item: dict[str, str]) -> str:
    auth_file = str(item.get("auth_file") or "").strip()
    if not auth_file:
        return ""

    valid_auth_file = _valid_account_auth_file({"auth_file": auth_file})
    if valid_auth_file:
        return valid_auth_file

    email = _normalized_email(item.get("email"))
    if not email:
        return ""
    try:
        from autotoken.storage.auth_session_store import get_auth_session_file

        session_file = str(get_auth_session_file(email) or "").strip()
        trusted = _trusted_token_auth_path(auth_file)
        if session_file and trusted and trusted.resolve() == Path(session_file).resolve():
            return str(trusted)
    except Exception:
        return ""
    return ""


def _trusted_token_auth_path(auth_file: str) -> Path | None:
    from autotoken.storage.auth_files import trusted_auth_or_session_path

    return trusted_auth_or_session_path(auth_file)


def _auto_check_active_auth_items(accounts: list[dict]) -> list[tuple[dict, str]]:
    from autotoken.storage.accounts import STATUS_ACTIVE

    items = []
    for account in accounts:
        if account.get("status") != STATUS_ACTIVE or _is_main_account_email(account.get("email")):
            continue
        auth_file = _valid_account_auth_file(account)
        if auth_file:
            items.append((account, auth_file))
    return items


def _codex_auth_file_is_synthetic(auth_file: str) -> bool:
    return account_presentation_service.codex_auth_file_is_synthetic(auth_file)


def _display_account_status(acc: dict, quota_snapshot: dict | None = None) -> str:
    return account_presentation_service.display_account_status(
        acc,
        quota_snapshot,
        is_main_account_email=_is_main_account_email,
        resolve_status_auth_file_func=_resolve_status_auth_file,
    )


def _display_account_type(acc: dict) -> str:
    return account_presentation_service.display_account_type(acc)


def _sanitize_account(acc: dict, quota_snapshot: dict | None = None) -> dict:
    """脱敏账号信息（去掉 password 等敏感字段）"""
    return account_presentation_service.sanitize_account(
        acc,
        quota_snapshot,
        normalize_email=_normalized_email,
        is_main_account_email=_is_main_account_email,
        resolve_status_auth_file_func=_resolve_status_auth_file,
        resolve_codex_auth_file_func=_resolve_codex_auth_file,
    )


def _sanitize_accounts_batch(accounts: list[dict], quota_cache: dict | None = None) -> list[dict]:
    """Batch sanitize accounts without per-row filesystem scans."""
    return account_presentation_service.sanitize_accounts_batch(
        accounts,
        quota_cache,
        normalize_email=_normalized_email,
        is_main_account_email=_is_main_account_email,
        resolve_status_auth_file_func=_resolve_status_auth_file,
        resolve_codex_auth_file_func=_resolve_codex_auth_file,
    )


def _sanitize_account_with_indexes(
    acc: dict,
    quota_snapshot: dict | None,
    auth_metadata: dict[str, dict],
    auth_session_files: dict[str, str],
    main_email: str = "",
) -> dict:
    return account_presentation_service.sanitize_account_with_indexes(
        acc,
        quota_snapshot,
        auth_metadata,
        auth_session_files,
        main_email,
        normalize_email=_normalized_email,
        resolve_status_auth_file_func=_resolve_status_auth_file,
        resolve_codex_auth_file_func=_resolve_codex_auth_file,
    )


def _account_id_from_auth_data(auth_data: dict) -> str:
    return account_cpa_auth_service.account_id_from_auth_data(auth_data)


def _admin_status():
    from autotoken.settings.admin_state import get_admin_state_summary

    status = get_admin_state_summary()
    status["login_step"] = _admin_login_step
    status["login_in_progress"] = _admin_login_api is not None
    if _admin_login_api and _admin_login_step == "workspace_required":
        status["workspace_options"] = getattr(_admin_login_api, "workspace_options_cache", []) or []
    else:
        status["workspace_options"] = []
    return status


def _main_codex_status():
    return {
        "in_progress": _main_codex_flow is not None,
        "step": _main_codex_step,
    }


def _manual_account_status():
    status = {
        "in_progress": False,
        "status": "idle",
        "state": "",
        "auth_url": "",
        "started_at": None,
        "message": "",
        "error": "",
        "account": None,
        "callback_received": False,
        "callback_source": "",
        "auto_callback_available": False,
        "auto_callback_error": "",
    }
    if _manual_account_flow:
        status.update(_manual_account_flow.status())
    return status


def _finish_admin_login(completed: dict):
    global _admin_login_api, _admin_login_step
    api = _admin_login_api
    info = None
    try:
        info = _pw_executor.run(api.complete_admin_login)
    finally:
        if api:
            try:
                _pw_executor.run(api.stop)
            except Exception:
                pass
        _admin_login_api = None
        _admin_login_step = None
        if info and info.get("session_token") and info.get("account_id"):
            try:
                from autotoken.auth.codex_auth import refresh_main_auth_file

                main_auth = _pw_executor.run(refresh_main_auth_file)
                if main_auth:
                    info["main_auth"] = main_auth
                    logger.info("[API] 管理员登录后已刷新主号认证文件: %s", main_auth.get("auth_file"))
            except Exception as exc:
                info["main_auth_error"] = str(exc)
                logger.warning("[API] 管理员登录完成，但刷新主号认证文件失败: %s", exc)
        if _playwright_lock.locked():
            _playwright_lock.release()
    return {"status": "completed", "admin": _admin_status(), "info": info}


def _set_pending_admin_login(api, step):
    global _admin_login_api, _admin_login_step
    _admin_login_api = api
    _admin_login_step = step
    return {"status": step, "admin": _admin_status()}


def _finish_main_codex_sync():
    global _main_codex_flow, _main_codex_step
    flow = _main_codex_flow
    try:
        info = _pw_executor.run(flow.complete)
    finally:
        if flow:
            try:
                _pw_executor.run(flow.stop)
            except Exception:
                pass
        _main_codex_flow = None
        _main_codex_step = None
        if _playwright_lock.locked():
            _playwright_lock.release()
    return {
        "status": "completed",
        "message": "主号 Codex 已同步到 CPA",
        "codex": _main_codex_status(),
        "info": info,
    }


def _set_pending_main_codex_sync(flow, step):
    global _main_codex_flow, _main_codex_step
    _main_codex_flow = flow
    _main_codex_step = step
    return {"status": step, "codex": _main_codex_status()}


def _finish_manual_account_flow(result: dict):
    return {**result, "manual_account": _manual_account_status()}


def _set_pending_manual_account_flow(flow, result):
    global _manual_account_flow
    _manual_account_flow = flow
    return {**result, "manual_account": _manual_account_status()}


_is_bind_card_reusable_result = payment_results_service.is_bind_card_reusable_result
_is_gopay_checkout_not_approved_result = payment_results_service.is_gopay_checkout_not_approved_result
_gopay_rejected_pool_emails = payment_results_service.gopay_rejected_pool_emails
_gopay_nonzero_blocked_pool_emails = payment_results_service.gopay_nonzero_blocked_pool_emails
_gopay_payment_failed_pool_emails = payment_results_service.gopay_payment_failed_pool_emails
_gopay_token_invalidated_pool_emails = payment_results_service.gopay_token_invalidated_pool_emails
_gopay_pending_retry_reason = payment_results_service.gopay_pending_retry_reason
_gopay_pending_retry_source_stage = payment_results_service.gopay_pending_retry_source_stage
_is_chatgpt_token_invalidated_result = payment_results_service.is_chatgpt_token_invalidated_result
_is_chatgpt_user_paid_result = payment_results_service.is_chatgpt_user_paid_result
_as_chatgpt_user_paid_success = payment_results_service.chatgpt_user_paid_success
_looks_like_gopay_rate_limit_text = payment_results_service.looks_like_gopay_rate_limit_text
_paypal_nonzero_blocked_pool_emails = payment_results_service.paypal_nonzero_blocked_pool_emails
_paypal_pending_retry_reason = payment_results_service.paypal_pending_retry_reason
_paypal_pending_retry_source_stage = payment_results_service.paypal_pending_retry_source_stage


def _parse_proxy_pool_values(values: list[Any] | tuple[Any, ...] | None = None, text: str | None = None) -> list[str]:
    return proxy_runtime_service.parse_proxy_pool_values(values, text)


def _is_proxy_api_url(value: str) -> bool:
    return proxy_runtime_service.is_proxy_api_url(value)


def _infer_proxy_api_provider_from_url(value: str) -> str:
    return proxy_runtime_service.infer_proxy_api_provider_from_url(value)


def _normalize_proxy_api_provider(value: str) -> str:
    try:
        return proxy_runtime_service.normalize_proxy_api_provider(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _default_proxy_api_url(provider: str, proxy_url: str = "") -> str:
    return proxy_runtime_service.default_proxy_api_url(provider, proxy_url)


def _default_paypal_proxy_api_url(provider: str, *, country: str = "US", protocol_no_card: bool = False) -> str:
    return proxy_runtime_service.default_paypal_proxy_api_url(
        provider,
        country=country,
        protocol_no_card=protocol_no_card,
    )


def _default_gopay_proxy_api_url(provider: str, proxy_url: str = "") -> str:
    return proxy_runtime_service.default_gopay_proxy_api_url(provider, proxy_url)


def _proxy_api_url_with_region(api_url: str, region: str) -> str:
    return proxy_runtime_service.proxy_api_url_with_region(api_url, region)


def _proxy_url_for_region(proxy_url: str, region: str) -> str:
    return proxy_runtime_service.proxy_url_for_region(proxy_url, region)


def _random_proxy_sid() -> str:
    return uuid.uuid4().hex[:10]


def _default_proxy_entry(provider: str, *, rotate_session: bool = False) -> str:
    return ""


def _extract_proxy_candidate_from_api_payload(payload: Any) -> str:
    return proxy_runtime_service.extract_proxy_candidate_from_api_payload(payload)


def _fetch_proxy_from_api_url(api_url: str, *, default_auth_scheme: str, provider: str = "") -> str:
    return proxy_runtime_service.fetch_proxy_from_api_url(
        api_url,
        default_auth_scheme=default_auth_scheme,
        provider=provider,
    )


def _build_oauth_proxy_selector(
    *,
    proxy_url: str | None = None,
    proxy_pool: list[Any] | tuple[Any, ...] | None = None,
    proxy_pool_text: str | None = None,
    proxy_api_provider: str | None = None,
    proxy_api_url: str | None = None,
):
    """Return a per-account OAuth proxy selector.

    OAuth uses the same static proxy / proxy pool / provider API semantics as
    PayPal, but keeps selection local so batch login can rotate per account.
    """
    try:
        return proxy_runtime_service.build_oauth_proxy_selector(
            proxy_url=proxy_url,
            proxy_pool=proxy_pool,
            proxy_pool_text=proxy_pool_text,
            proxy_api_provider=proxy_api_provider,
            proxy_api_url=proxy_api_url,
            default_auth_scheme=PAYPAL_PROXY_DEFAULT_SCHEME,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _probe_proxy_exit_ip(proxy_url: str) -> str:
    """探测代理出口 IP。

    仅用于日志和问题定位，不影响主流程。失败时返回空字符串。
    """
    proxy = str(proxy_url or "").strip()
    if not proxy:
        return ""
    try:
        session = requests.Session()
        session.trust_env = False
        session.proxies = {"http": proxy, "https": proxy}
        resp = session.get("https://api.ipify.org?format=json", timeout=12)
        if resp.status_code >= 400:
            return ""
        try:
            payload = resp.json()
            ip = str(payload.get("ip") or "").strip()
            if ip:
                return ip
        except Exception:
            pass
        text = str(resp.text or "").strip()
        if text and len(text) < 64:
            return text
    except Exception:
        return ""
    return ""


def _account_delete_audit_path() -> Path:
    from autotoken.core.paths import PROJECT_ROOT

    return PROJECT_ROOT / "data" / "account_delete_audit.jsonl"


def _account_delete_audit_db_path(path: Path) -> Path:
    from autotoken.core.paths import PROJECT_ROOT
    from autotoken.storage.sqlite_store import default_db_path

    return account_delete_audit_service.audit_db_path(path, project_root=PROJECT_ROOT, default_db_path=default_db_path)


def _append_account_delete_audit(
    *,
    email: str,
    log_context: str,
    reason: str,
    account: dict | None,
    record_deleted: bool,
    auth_session_deleted: bool,
    mail_service_deleted: bool = False,
    message: str = "",
) -> None:
    path = _account_delete_audit_path()
    from autotoken.storage import sqlite_store

    account_delete_audit_service.append_delete_audit(
        path=path,
        db_path=_account_delete_audit_db_path(path),
        audit_lock=_account_delete_audit_lock,
        email=email,
        log_context=log_context,
        reason=reason,
        account=account,
        record_deleted=record_deleted,
        auth_session_deleted=auth_session_deleted,
        normalize_email=_normalized_email,
        sqlite_store=sqlite_store,
        logger=logger,
        mail_service_deleted=mail_service_deleted,
        message=message,
    )


def _migrate_account_delete_audit_jsonl() -> int:
    path = _account_delete_audit_path()
    from autotoken.storage import sqlite_store

    return account_delete_audit_service.migrate_delete_audit_jsonl(path=path, sqlite_store=sqlite_store, logger=logger)


def _remove_pool_accounts_from_local_and_mail(
    emails: list[str],
    *,
    log_context: str = "account-cleanup",
    reason: str = "unspecified",
    message: str = "",
) -> list[str]:
    return account_pool_cleanup_service.remove_pool_accounts_from_local_and_mail(
        emails,
        is_main_account_email=_is_main_account_email,
        append_account_delete_audit=_append_account_delete_audit,
        logger=logger,
        log_context=log_context,
        reason=reason,
        message=message,
    )


def _mark_pool_accounts_fail(
    emails: list[str],
    *,
    reason: str,
    message: str,
    failure_stage: str = "token_invalidated",
    log_context: str = "account-fail",
) -> list[str]:
    return account_pool_cleanup_service.mark_pool_accounts_fail(
        emails,
        normalize_email=_normalized_email,
        is_main_account_email=_is_main_account_email,
        logger=logger,
        reason=reason,
        message=message,
        failure_stage=failure_stage,
        log_context=log_context,
    )


def _remove_gopay_rejected_accounts_from_pool(emails: list[str]) -> list[str]:
    return _remove_pool_accounts_from_local_and_mail(
        emails,
        log_context="gopay-bind",
        reason="gopay_rejected_or_unusable",
    )


def _remove_oauth_phone_required_accounts_from_pool(emails: list[str]) -> list[str]:
    return _remove_pool_accounts_from_local_and_mail(
        emails,
        log_context="oauth-phone-required",
        reason="oauth_phone_required",
    )


def _remove_oauth_account_deactivated_accounts_from_pool(emails: list[str]) -> list[str]:
    return _remove_pool_accounts_from_local_and_mail(
        emails,
        log_context="oauth-account-deactivated",
        reason="oauth_account_deactivated",
    )


def _session_only_account_stub(email: str) -> dict:
    return account_session_stubs_service.session_only_account_stub(email)


def _load_accounts_with_session_stubs(*, include_session_stubs: bool = True) -> list[dict]:
    repair_paypal_ice_account_bind_metadata()
    return account_session_stubs_service.load_accounts_with_session_stubs(
        include_session_stubs=include_session_stubs,
        normalize_email=_normalized_email,
        session_only_account_stub_func=_session_only_account_stub,
    )


# ---------------------------------------------------------------------------
# 同步端点
# ---------------------------------------------------------------------------


_admin_maintenance_router = create_admin_maintenance_router(
    playwright_lock=_playwright_lock,
    playwright_executor=_pw_executor,
    current_busy_detail=_current_busy_detail,
    logger=logger,
)
app.include_router(_admin_maintenance_router)
_admin_maintenance_endpoints = {route.endpoint.__name__: route.endpoint for route in _admin_maintenance_router.routes}
post_admin_fix_account_id = _admin_maintenance_endpoints["post_admin_fix_account_id"]
get_admin_diagnose = _admin_maintenance_endpoints["get_admin_diagnose"]
post_admin_reconcile = _admin_maintenance_endpoints["post_admin_reconcile"]


def _get_admin_login_api():
    return _admin_login_api


def _get_admin_login_step() -> str | None:
    return _admin_login_step


def _set_admin_login_state(api, step: str | None) -> None:
    global _admin_login_api, _admin_login_step
    _admin_login_api = api
    _admin_login_step = step


def _get_main_codex_flow():
    return _main_codex_flow


def _get_main_codex_step() -> str | None:
    return _main_codex_step


def _set_main_codex_state(flow, step: str | None) -> None:
    global _main_codex_flow, _main_codex_step
    _main_codex_flow = flow
    _main_codex_step = step


def _get_manual_account_flow():
    return _manual_account_flow


def _set_manual_account_flow(flow) -> None:
    global _manual_account_flow
    _manual_account_flow = flow


_interactive_login_router = create_interactive_login_router(
    playwright_lock=_playwright_lock,
    playwright_executor=_pw_executor,
    current_busy_detail=_current_busy_detail,
    logger=logger,
    admin_status=_admin_status,
    main_codex_status=_main_codex_status,
    manual_account_status=_manual_account_status,
    get_admin_login_api=_get_admin_login_api,
    get_admin_login_step=_get_admin_login_step,
    set_admin_login_state=_set_admin_login_state,
    finish_admin_login=_finish_admin_login,
    set_pending_admin_login=_set_pending_admin_login,
    get_main_codex_flow=_get_main_codex_flow,
    get_main_codex_step=_get_main_codex_step,
    set_main_codex_state=_set_main_codex_state,
    finish_main_codex_sync=_finish_main_codex_sync,
    set_pending_main_codex_sync=_set_pending_main_codex_sync,
    get_manual_account_flow=_get_manual_account_flow,
    set_manual_account_flow=_set_manual_account_flow,
    finish_manual_account_flow=_finish_manual_account_flow,
    set_pending_manual_account_flow=_set_pending_manual_account_flow,
)
app.include_router(_interactive_login_router)
_interactive_login_endpoints = {route.endpoint.__name__: route.endpoint for route in _interactive_login_router.routes}
get_admin_status = _interactive_login_endpoints["get_admin_status"]
get_main_codex_status = _interactive_login_endpoints["get_main_codex_status"]
get_manual_account_status = _interactive_login_endpoints["get_manual_account_status"]
post_admin_login_start = _interactive_login_endpoints["post_admin_login_start"]
post_admin_login_session = _interactive_login_endpoints["post_admin_login_session"]
post_admin_login_password = _interactive_login_endpoints["post_admin_login_password"]
post_admin_login_code = _interactive_login_endpoints["post_admin_login_code"]
post_admin_login_workspace = _interactive_login_endpoints["post_admin_login_workspace"]
post_admin_login_cancel = _interactive_login_endpoints["post_admin_login_cancel"]
post_admin_logout = _interactive_login_endpoints["post_admin_logout"]
post_main_codex_start = _interactive_login_endpoints["post_main_codex_start"]
post_main_codex_password = _interactive_login_endpoints["post_main_codex_password"]
post_main_codex_code = _interactive_login_endpoints["post_main_codex_code"]
post_main_codex_cancel = _interactive_login_endpoints["post_main_codex_cancel"]
post_manual_account_start = _interactive_login_endpoints["post_manual_account_start"]
post_manual_account_callback = _interactive_login_endpoints["post_manual_account_callback"]
post_manual_account_cancel = _interactive_login_endpoints["post_manual_account_cancel"]


app.include_router(
    create_account_overview_router(
        load_accounts_with_session_stubs=_load_accounts_with_session_stubs,
        sanitize_accounts_batch=_sanitize_accounts_batch,
        sanitize_account=_sanitize_account,
        is_main_account_email=_is_main_account_email,
    )
)
app.include_router(
    create_account_management_router(
        playwright_lock=_playwright_lock,
        playwright_executor=_pw_executor,
        current_busy_detail=_current_busy_detail,
        is_main_account_email=_is_main_account_email,
        sanitize_account=_sanitize_account,
    )
)
app.include_router(
    create_account_exports_router(
        normalize_email=_normalized_email,
        is_main_account_email=_is_main_account_email,
        sanitize_account=_sanitize_account,
        current_time=time.time,
    )
)


def _normalize_access_token(raw_value: str) -> str:
    return gopay_pro_pool_service.normalize_access_token(raw_value)


def _extract_account_access_token(email: str) -> str:
    from autotoken.auth.codex_auth import get_saved_main_auth_file
    from autotoken.storage.accounts import find_account, load_accounts
    from autotoken.storage.auth_session_store import get_auth_session_file

    normalized = _normalized_email(email)
    if not normalized:
        return ""

    auth_file = ""
    if _is_main_account_email(normalized):
        auth_file = get_saved_main_auth_file() or ""
    else:
        acc = find_account(load_accounts(), normalized)
        if acc:
            auth_file = _resolve_status_auth_file(acc)
        if not auth_file:
            auth_file = str(get_auth_session_file(normalized) or "").strip()
    auth_path = _trusted_token_auth_path(auth_file)
    if not auth_path:
        return ""

    try:
        auth_data = read_auth_json_file(auth_path)
    except Exception:
        return ""
    return _normalize_access_token(auth_data.get("access_token") or auth_data.get("accessToken") or "")


def _refresh_account_access_token(email: str) -> str:
    from autotoken.storage.auth_session_store import load_auth_session, save_auth_session

    normalized = _normalized_email(email)
    if not normalized:
        return ""
    session_data = load_auth_session(normalized)
    session_token = str(session_data.get("sessionToken") or session_data.get("session_token") or "").strip()
    cookie_header = str(session_data.get("cookie_header") or "").strip()
    if not session_token and not cookie_header:
        return ""
    device_id = str(session_data.get("device_id") or session_data.get("oai_device_id") or "").strip()
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    )
    http = requests.Session()
    try:
        chatgpt_session_service.configure_chatgpt_http_session(
            http,
            access_token="",
            session_token=session_token,
            cookie_header=cookie_header,
            device_id=device_id,
            user_agent=user_agent,
        )
        response = http.get(
            "https://chatgpt.com/api/auth/session", timeout=max(10.0, _env_float("CHECKOUT_HTTP_TIMEOUT_SECONDS", 30.0))
        )
        if int(getattr(response, "status_code", 0) or 0) >= 400:
            return ""
        payload = response.json()
        if not isinstance(payload, dict):
            return ""
        access_token = _normalize_access_token(payload.get("accessToken") or payload.get("access_token") or "")
        if not access_token:
            return ""
        refreshed = dict(session_data)
        refreshed["accessToken"] = access_token
        refreshed["access_token"] = access_token
        if payload.get("user") and isinstance(payload.get("user"), dict):
            refreshed["user"] = payload.get("user")
        if str(getattr(http, "_chatgpt_cookie_header", "") or "").strip():
            refreshed["cookie_header"] = str(getattr(http, "_chatgpt_cookie_header", "") or "").strip()
        if str(getattr(http, "_oai_device_id", "") or "").strip():
            refreshed["device_id"] = str(getattr(http, "_oai_device_id", "") or "").strip()
            refreshed["oai_device_id"] = str(getattr(http, "_oai_device_id", "") or "").strip()
        save_auth_session(normalized, refreshed)
        return access_token
    except Exception as exc:
        logger.info(
            "[paypal] refresh access token from session failed: email=%s error=%s", _safe_email_summary(normalized), exc
        )
        return ""
    finally:
        try:
            http.close()
        except Exception:
            pass


def _looks_like_html_error(text: str) -> bool:
    return checkout_response_service.looks_like_html_error(text)


def _friendly_checkout_error(detail: str, status: int | None = None) -> str:
    return checkout_response_service.friendly_checkout_error(detail, status)


def _looks_like_cloudflare_challenge(text: str) -> bool:
    return checkout_response_service.looks_like_cloudflare_challenge(text)


def _parse_checkout_response_json(text: str) -> dict[str, Any]:
    return checkout_response_service.parse_checkout_response_json(text)


def _find_hosted_checkout_url(payload: Any) -> str:
    return checkout_response_service.find_hosted_checkout_url(payload)


def _choose_checkout_error_status(upstream_status: int) -> int:
    return checkout_response_service.choose_checkout_error_status(upstream_status)


def _normalize_checkout_payload_for_http(payload: dict[str, Any]) -> dict[str, Any]:
    return checkout_response_service.normalize_checkout_payload_for_http(payload)


def _new_checkout_http_session(impersonate_browser: str):
    try:
        from curl_cffi.requests import Session as CurlCffiSession  # type: ignore
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="当前环境缺少 curl_cffi，无法使用 HTTP Hosted 生成器",
        ) from exc
    session = CurlCffiSession(impersonate=impersonate_browser)
    try:
        session._autotoken_transport = "curl_cffi"  # type: ignore[attr-defined]
    except Exception:
        pass
    return session


def _generate_checkout_link_via_http(
    access_token: str, payload: dict[str, Any], *, proxy_url: str = ""
) -> dict[str, Any]:
    normalized_access_token = _normalize_access_token(access_token)
    if not normalized_access_token:
        raise HTTPException(status_code=400, detail="请提供 access_token")

    payload = _normalize_checkout_payload_for_http(payload)
    normalized_proxy_url = normalize_proxy_url(proxy_url) if str(proxy_url or "").strip() else ""
    checkout_proxies = {"http": normalized_proxy_url, "https": normalized_proxy_url} if normalized_proxy_url else {}

    primary_impersonate = str(os.environ.get("CHECKOUT_IMPERSONATE_BROWSER") or "chrome136").strip() or "chrome136"
    fallback_impersonate = (
        str(os.environ.get("CHECKOUT_FALLBACK_IMPERSONATE_BROWSER") or "chrome133a").strip() or "chrome133a"
    )
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    )
    request_timeout = max(10.0, _env_float("CHECKOUT_HTTP_TIMEOUT_SECONDS", 30.0))

    def _post_once_requests() -> tuple[Any, str]:
        http = requests.Session()
        try:
            if checkout_proxies:
                http.proxies.update(checkout_proxies)
            chatgpt_session_service.configure_chatgpt_http_session(
                http,
                access_token=normalized_access_token,
                user_agent=user_agent,
            )
            http.headers.update(
                {
                    "Accept": "application/json",
                    "Origin": "https://chatgpt.com",
                    "Referer": "https://chatgpt.com/",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                }
            )
            resp = http.post(
                "https://chatgpt.com/backend-api/payments/checkout",
                json=payload,
                timeout=request_timeout,
            )
            return resp, str(getattr(resp, "text", "") or "")
        finally:
            try:
                http.close()
            except Exception:
                pass

    def _post_once(impersonate_browser: str) -> tuple[Any, str]:
        http = _new_checkout_http_session(impersonate_browser)
        try:
            if checkout_proxies:
                http.proxies.update(checkout_proxies)
            chatgpt_session_service.configure_chatgpt_http_session(
                http,
                access_token=normalized_access_token,
                user_agent=user_agent,
            )
            http.headers.update(
                {
                    "Accept": "application/json",
                    "Origin": "https://chatgpt.com",
                    "Referer": "https://chatgpt.com/",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                }
            )
            resp = http.post(
                "https://chatgpt.com/backend-api/payments/checkout",
                json=payload,
                timeout=request_timeout,
            )
            return resp, str(getattr(resp, "text", "") or "")
        finally:
            try:
                http.close()
            except Exception:
                pass

    response = None
    raw_text = ""
    request_errors: list[str] = []
    try:
        response, raw_text = _post_once_requests()
    except Exception as exc:
        request_errors.append(f"requests: {type(exc).__name__}: {exc}")
        logger.warning("[bind/link] requests checkout path failed: %s", request_errors[-1])

    if response is None or _looks_like_cloudflare_challenge(raw_text):
        try:
            response, raw_text = _post_once(primary_impersonate)
        except HTTPException:
            raise
        except Exception as exc:
            request_errors.append(f"curl_cffi: {type(exc).__name__}: {exc}")
            raise HTTPException(
                status_code=502, detail="upstream checkout request failed: " + " | ".join(request_errors)
            ) from exc

    if (
        _looks_like_cloudflare_challenge(raw_text)
        and fallback_impersonate
        and fallback_impersonate != primary_impersonate
    ):
        logger.info(
            "[bind/link] upstream returned Cloudflare challenge; retrying with fallback impersonate=%s",
            fallback_impersonate,
        )
        try:
            response, raw_text = _post_once(fallback_impersonate)
        except Exception as exc:
            raise HTTPException(
                status_code=502, detail=f"upstream checkout retry failed: {type(exc).__name__}: {exc}"
            ) from exc

    if _looks_like_cloudflare_challenge(raw_text):
        raise HTTPException(status_code=502, detail="upstream blocked by Cloudflare challenge")

    upstream_data = _parse_checkout_response_json(raw_text)
    upstream_status = int(getattr(response, "status_code", 0) or 0)
    checkout_session_id = str(upstream_data.get("checkout_session_id") or "").strip()
    if upstream_status >= 400 or not checkout_session_id:
        detail = (
            upstream_data.get("detail")
            or upstream_data.get("message")
            or upstream_data.get("error")
            or f"upstream returned HTTP {upstream_status or 502}"
        )
        raise HTTPException(status_code=_choose_checkout_error_status(upstream_status or 502), detail=detail)

    processor_entity = str(upstream_data.get("processor_entity") or "openai_llc").strip() or "openai_llc"
    hosted_checkout_url = _find_hosted_checkout_url(upstream_data)
    chatgpt_checkout_url = f"https://chatgpt.com/checkout/{processor_entity}/{checkout_session_id}"
    checkout_ui_mode = str(payload.get("checkout_ui_mode") or "").strip().lower()
    preferred_checkout_url = (
        hosted_checkout_url if checkout_ui_mode == "hosted" and hosted_checkout_url else chatgpt_checkout_url
    )
    return {
        "url": preferred_checkout_url,
        "checkout_session_id": checkout_session_id,
        "processor_entity": processor_entity,
        "hosted_checkout_url": hosted_checkout_url,
        "chatgpt_checkout_url": chatgpt_checkout_url,
        "upstream_status": upstream_status,
        "attempt": "http",
    }


def _generate_checkout_link(access_token: str, payload: dict[str, Any], *, proxy_url: str = "") -> dict[str, Any]:
    return _generate_checkout_link_via_http(access_token, payload, proxy_url=proxy_url)


_bind_checkout_browser_sessions: list[Any] = []


def _open_bind_checkout_with_auth_session(email: str, checkout_url: str) -> dict[str, Any]:
    from autotoken.integrations.chatgpt_api import ChatGPTTeamAPI
    from autotoken.storage.auth_session_store import load_auth_session

    normalized_email = _normalized_email(email)
    if not normalized_email:
        raise HTTPException(status_code=400, detail="请选择号池账号")
    session_data = load_auth_session(normalized_email)
    if not session_data:
        raise HTTPException(status_code=400, detail=f"账号缺少可用 auth_session: {normalized_email}")
    session_token = str(session_data.get("sessionToken") or session_data.get("session_token") or "").strip()
    cookie_header = str(session_data.get("cookie_header") or "").strip()
    if not session_token and not cookie_header:
        raise HTTPException(status_code=400, detail=f"账号 auth_session 缺少 sessionToken/cookie_header: {normalized_email}")

    user_data = session_data.get("user") if isinstance(session_data.get("user"), dict) else {}
    account_data = session_data.get("account") if isinstance(session_data.get("account"), dict) else {}
    account_id = str(
        session_data.get("account_id")
        or session_data.get("accountId")
        or user_data.get("account_id")
        or user_data.get("accountId")
        or account_data.get("id")
        or account_data.get("account_id")
        or ""
    ).strip()
    device_id = str(session_data.get("device_id") or session_data.get("oai_device_id") or "").strip()

    api = ChatGPTTeamAPI()
    api.oai_device_id = device_id or getattr(api, "oai_device_id", "")
    api._launch_browser(background=False, headless=False, randomize_fingerprint=False)
    chatgpt_session_service.inject_chatgpt_browser_cookies(
        api,
        session_token=session_token,
        cookie_header=cookie_header,
        account_id=account_id,
        device_id=device_id,
    )
    api.page.goto(checkout_url, wait_until="domcontentloaded", timeout=60000)
    try:
        api._wait_for_cloudflare()
    except Exception:
        logger.info("[bind/link/open] wait for cloudflare skipped/failed", exc_info=True)
    _bind_checkout_browser_sessions.append(api)
    if len(_bind_checkout_browser_sessions) > 5:
        old_api = _bind_checkout_browser_sessions.pop(0)
        try:
            old_api.stop()
        except Exception:
            pass
    return {"opened": True, "current_url": str(getattr(api.page, "url", "") or checkout_url)}


def _generate_checkout_link_for_paypal_task(
    access_token: str, payload: dict[str, Any], *, proxy_url: str = ""
) -> dict[str, Any]:
    try:
        return _generate_checkout_link(access_token, payload, proxy_url=proxy_url)
    except TypeError as exc:
        if "proxy_url" in str(exc):
            return _generate_checkout_link(access_token, payload)
        raise


def _generate_checkout_link_via_browser(
    access_token: str,
    payload: dict[str, Any],
    *,
    email: str = "",
    proxy_url: str | None = None,
    proxy_bypass: str | None = None,
    paypal_browser: str = "chromium",
    roxybrowser_workspace_id: str = "",
    roxybrowser_profile_id: str = "",
) -> dict[str, Any]:
    from autotoken.integrations.chatgpt_api import ChatGPTTeamAPI
    from autotoken.storage.auth_session_store import load_auth_session

    normalized_access_token = _normalize_access_token(access_token)
    if not normalized_access_token:
        raise HTTPException(status_code=400, detail="请提供 access_token")

    def _friendly_goto_error(exc):
        text = str(exc)
        if "ERR_CONNECTION_CLOSED" in text:
            return "打开 ChatGPT 首页失败：网络连接被关闭，可能是代理/IP/风控问题"
        if "ERR_TIMED_OUT" in text or "Timeout" in text:
            return "打开 ChatGPT 首页失败：请求超时，可能是网络波动、代理不稳定或风控问题"
        if "ERR_CONNECTION_RESET" in text:
            return "打开 ChatGPT 首页失败：网络连接被重置，可能是代理/IP/风控问题"
        return f"打开 ChatGPT 首页失败：{text}"

    api = ChatGPTTeamAPI()
    try:
        paypal_browser = str(paypal_browser or "chromium").strip().lower()
        use_camoufox = paypal_browser in {"camoufox", "firefox"}
        use_roxybrowser = paypal_browser in {"roxybrowser", "roxy-browser", "roxy"}
        session_data: dict[str, Any] = {}
        normalized_email = _normalized_email(email)
        if normalized_email:
            session_data = load_auth_session(normalized_email)
        device_id = str(session_data.get("device_id") or session_data.get("oai_device_id") or "").strip()
        api.oai_device_id = device_id or getattr(api, "oai_device_id", "")
        api._launch_browser(
            proxy_url=proxy_url,
            proxy_bypass=proxy_bypass,
            headless=False,
            background=False,
            locale="en-US",
            accept_language="en-US,en;q=0.9",
            randomize_fingerprint=False,
            use_camoufox=use_camoufox,
            use_roxybrowser=use_roxybrowser,
            roxybrowser_workspace_id=roxybrowser_workspace_id,
            roxybrowser_profile_id=roxybrowser_profile_id,
        )
        if session_data:
            user_data = session_data.get("user") if isinstance(session_data.get("user"), dict) else {}
            account_data = session_data.get("account") if isinstance(session_data.get("account"), dict) else {}
            account_id = str(
                session_data.get("account_id")
                or session_data.get("accountId")
                or user_data.get("account_id")
                or user_data.get("accountId")
                or account_data.get("id")
                or account_data.get("account_id")
                or ""
            ).strip()
            chatgpt_session_service.inject_chatgpt_browser_cookies(
                api,
                session_token=str(session_data.get("sessionToken") or session_data.get("session_token") or "").strip(),
                cookie_header=str(session_data.get("cookie_header") or "").strip(),
                account_id=account_id,
                device_id=device_id,
            )
        logger.info("[bind/link] open chatgpt.com to pass Cloudflare")
        goto_ok = False
        last_goto_exc = None
        for attempt in range(3):
            try:
                api.page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=60000)
                goto_ok = True
                break
            except Exception as exc:
                last_goto_exc = exc
                logger.warning(
                    "[bind/link] 打开 ChatGPT 首页失败，第 %d/3 次: %s",
                    attempt + 1,
                    _friendly_goto_error(exc),
                )
                if attempt < 2:
                    time.sleep(3)
        if not goto_ok:
            raise RuntimeError(_friendly_goto_error(last_goto_exc))

        time.sleep(5)
        api._wait_for_cloudflare()
        api.access_token = normalized_access_token

        script = """async (args) => {
                const accessToken = (args && args.accessToken) || "";
                const payload = (args && args.payload) || {};
                const fetchWithTimeout = async (url, init = {}, timeoutMs = 12000) => {
                    const controller = new AbortController();
                    const timer = setTimeout(() => controller.abort(), timeoutMs);
                    try {
                        return await fetch(url, { ...init, signal: controller.signal });
                    } finally {
                        clearTimeout(timer);
                    }
                };
                let pageAccessToken = "";
                let sessionStatus = 0;
                let sessionDetail = "";
                try {
                    const sessionResp = await fetchWithTimeout("/api/auth/session", {
                        method: "GET",
                        credentials: "include",
                        headers: { Accept: "application/json" }
                    }, 12000);
                    sessionStatus = sessionResp.status;
                    const sessionText = await sessionResp.text();
                    try {
                        const sessionData = sessionText ? JSON.parse(sessionText) : {};
                        pageAccessToken = (sessionData && sessionData.accessToken) || "";
                    } catch (_) {
                        sessionDetail = sessionText.slice(0, 300);
                    }
                } catch (e) {
                    sessionDetail = String(e && e.message ? e.message : e);
                }
                const token = pageAccessToken || accessToken;
                if (!token) {
                    return { ok: false, status: sessionStatus || 0, detail: sessionDetail || "缺少 accessToken", raw: {}, attempt: "browser_session" };
                }
                const timezoneOffset = new Date().getTimezoneOffset();
                const warmups = [
                    [`/backend-api/accounts/check/v4-2023-04-27?timezone_offset_min=${timezoneOffset}`, { method: "GET" }],
                    ["/backend-api/accounts/domain-density-eligibility", { method: "GET" }],
                    ["/backend-api/checkout_pricing_config/countries", { method: "GET" }],
                    ["/backend-api/checkout_pricing_config/configs/ID", { method: "GET" }]
                ];
                for (const [url, init] of warmups) {
                    try {
                        await fetchWithTimeout(url, {
                            ...init,
                            credentials: "include",
                            headers: {
                                Authorization: "Bearer " + token,
                                Accept: "application/json",
                                "x-openai-target-path": url.split("?")[0],
                                "x-openai-target-route": url.split("?")[0]
                            }
                        }, 8000);
                    } catch (_) {}
                }
                try {
                    await fetchWithTimeout("/backend-api/sentinel/ping", {
                        method: "POST",
                        credentials: "include",
                        headers: { "Content-Type": "application/json" },
                        body: "{}"
                    }, 8000);
                } catch (_) {}

                const attempts = [
                    {
                        label: "basic",
                        headers: {
                            Authorization: "Bearer " + token,
                            "Content-Type": "application/json",
                        }
                    },
                    {
                        label: "target",
                        headers: {
                            Authorization: "Bearer " + token,
                            "Content-Type": "application/json",
                            Accept: "*/*",
                            "oai-language": navigator.language || "en-US",
                            "oai-session-id": crypto.randomUUID ? crypto.randomUUID() : String(Date.now()),
                            "x-openai-target-path": "/backend-api/payments/checkout",
                            "x-openai-target-route": "/backend-api/payments/checkout"
                        }
                    }
                ];

                let last = { ok: false, status: 0, detail: "未执行 checkout 请求", raw: {} };
                for (const attempt of attempts) {
                    let resp;
                    try {
                        resp = await fetchWithTimeout("https://chatgpt.com/backend-api/payments/checkout", {
                            method: "POST",
                            credentials: "include",
                            headers: attempt.headers,
                            body: JSON.stringify(payload),
                        }, 20000);
                    } catch (e) {
                        last = { ok: false, status: 0, detail: String(e && e.message ? e.message : e), raw: {}, attempt: attempt.label };
                        continue;
                    }
                    const text = await resp.text();
                    let data = {};
                    try {
                        data = text ? JSON.parse(text) : {};
                    } catch (_) {
                        data = { raw: text.slice(0, 500) };
                    }
                    if (resp.ok) {
                        const checkoutSessionId = data.checkout_session_id || "";
                        const processorEntity = data.processor_entity || "openai_llc";
                        const url = data.url || (checkoutSessionId ? `https://chatgpt.com/checkout/${processorEntity}/${checkoutSessionId}` : "");
                        return {
                            ok: Boolean(url),
                            status: resp.status,
                            url,
                            checkout_session_id: checkoutSessionId,
                            processor_entity: processorEntity,
                            raw: data,
                            detail: url ? "" : "生成 checkout 返回缺少 url",
                            attempt: "browser_" + attempt.label,
                            session_status: sessionStatus,
                            page_token_used: Boolean(pageAccessToken)
                        };
                    }
                    last = {
                        ok: false,
                        status: resp.status,
                        detail: data.detail || data.error || (data.raw ? String(data.raw).slice(0, 200) : `HTTP ${resp.status}`),
                        raw: data,
                        attempt: "browser_" + attempt.label,
                        session_status: sessionStatus,
                        page_token_used: Boolean(pageAccessToken)
                    };
                    if (resp.status !== 403) {
                        break;
                    }
                }
                return last;
            }"""

        result = None
        last_result = None
        for eval_attempt in range(3):
            result = api.page.evaluate(
                script,
                {"accessToken": normalized_access_token, "payload": payload},
            )
            last_result = result
            if result.get("ok"):
                break
            status = int(result.get("status") or 0)
            detail = str(result.get("detail") or "").strip()
            if status != 403 and not _looks_like_html_error(detail):
                break
            logger.warning(
                "[bind/link] checkout blocked, retrying browser warmup: attempt=%s/3 status=%s detail=%s",
                eval_attempt + 1,
                status,
                _friendly_checkout_error(detail, status),
            )
            if eval_attempt >= 2:
                break
            try:
                api.page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=60000)
                time.sleep(3)
                api._wait_for_cloudflare()
            except Exception as exc:
                logger.warning("[bind/link] retry warmup goto failed: %s", _friendly_goto_error(exc))
                time.sleep(2)

        if not result.get("ok"):
            status = int((result or last_result or {}).get("status") or 0) or 502
            detail = _friendly_checkout_error((result or last_result or {}).get("detail") or "", status)
            raise HTTPException(status_code=status, detail=detail)

        return {
            "url": result.get("url") or "",
            "checkout_session_id": result.get("checkout_session_id") or "",
            "processor_entity": result.get("processor_entity") or "",
            "attempt": result.get("attempt") or "",
        }
    finally:
        try:
            api.stop()
        except Exception:
            pass


_GOPAY_PRO_SLOT_STATES = {
    "EMPTY",
    "GOPAY_REGISTERING",
    "WALLET_WAITING",
    "WALLET_READY",
    "PLUS_PAYING",
    "NO_TRIAL",
    "PLUS_DONE",
    "REBINDING",
    "RELEASED",
    "FAILED",
}

_GOPAY_PRO_TASK_KINDS = {
    "register",
    "harvest",
    "rebind",
    "status",
    "refresh",
    "linkedapps",
    "profile",
    "fix-failed",
    "link-only",
}


def _gopay_pro_root() -> Path:
    from autotoken.core.paths import PROJECT_ROOT

    configured = str(os.environ.get("CNGOPAY_ROOT") or "").strip()
    return Path(configured).expanduser().resolve() if configured else (PROJECT_ROOT / "CNgopay").resolve()


def _gopay_pro_paths(root: Path | None = None) -> dict[str, Path]:
    base = root or _gopay_pro_root()
    config_path = base / "config.json"
    config = read_json_file(config_path, {})
    pool = config.get("pool") if isinstance(config, dict) and isinstance(config.get("pool"), dict) else {}

    def _pool_file(key: str, default: str) -> Path:
        raw = str(pool.get(key) or default).strip() or default
        path = Path(raw).expanduser()
        return path.resolve() if path.is_absolute() else (base / path).resolve()

    return {
        "root": base,
        "config": config_path,
        "state": base / "runs" / "pool" / "state.json",
        "cooldowns": base / "runs" / "pool" / "cooldowns.json",
        "token_map": base / "runs" / "pool" / "token_map.json",
        "numbers": _pool_file("number_pool_file", "pool_numbers.txt"),
        "tokens": _pool_file("provided_tokens_file", "pool_tokens.txt"),
    }


def _read_json_file(path: Path, fallback):
    return read_json_file(path, fallback)


def _write_json_atomic(path: Path, value) -> None:
    write_json_atomic(path, value)


def _gopay_pro_waf_cooldown_seconds() -> int:
    try:
        return max(60, min(6 * 3600, int(os.environ.get("GOPAY_PRO_WAF_COOLDOWN_SECONDS", "3600") or "3600")))
    except Exception:
        return 3600


def _gopay_pro_text_has_waf_block(value: Any) -> bool:
    return gopay_pro_events_service.text_has_waf_block(value)


def _gopay_pro_waf_cooldown_info(paths: dict[str, Path] | None = None) -> dict[str, Any]:
    resolved = paths or _gopay_pro_paths()
    data = _read_json_file(resolved["cooldowns"], {})
    if not isinstance(data, dict):
        data = {}
    try:
        until = float(data.get("register_waf_until") or 0)
    except Exception:
        until = 0
    remaining = max(0, int(until - time.time())) if until > 0 else 0
    return {
        "until": int(until) if until > 0 else 0,
        "remaining_seconds": remaining,
        "reason": str(data.get("register_waf_reason") or ""),
    }


def _mark_gopay_pro_waf_cooldown(task_id: str, *, source: str = "") -> dict[str, Any]:
    paths = _gopay_pro_paths()
    cooldown_seconds = _gopay_pro_waf_cooldown_seconds()
    until = int(time.time() + cooldown_seconds)
    data = _read_json_file(paths["cooldowns"], {})
    if not isinstance(data, dict):
        data = {}
    data["register_waf_until"] = until
    data["register_waf_reason"] = source or "GoPay signup 403 WAF Block Page"
    data["updated_at"] = int(time.time())
    _write_json_atomic(paths["cooldowns"], data)
    info = _gopay_pro_waf_cooldown_info(paths)
    _append_task_progress(
        task_id,
        gopay_pro_task_payloads_service.gopay_pro_register_waf_blocked_progress(
            cooldown_remaining_seconds=info["remaining_seconds"],
        ),
    )
    return info


_GOPAY_PRO_NUMBER_COOLDOWN_PREFIX = gopay_pro_pool_service.NUMBER_COOLDOWN_PREFIX


def _gopay_pro_register_ratelimit_cooldown_seconds() -> int:
    try:
        return max(60, min(6 * 3600, int(os.environ.get("GOPAY_PRO_RATELIMIT_COOLDOWN_SECONDS", "3600") or "3600")))
    except Exception:
        return 3600


def _gopay_pro_text_has_register_ratelimit(value: Any) -> bool:
    return gopay_pro_events_service.text_has_register_ratelimit(value)


def _gopay_pro_number_cooldown_key() -> str:
    return gopay_pro_pool_service.NUMBER_COOLDOWN_KEY


def _gopay_pro_pool_line_phone(line: str) -> str:
    return gopay_pro_pool_service.pool_line_phone(line)


def _gopay_pro_phone_key(value: Any) -> str:
    return gopay_pro_pool_service.phone_key(value)


def _gopay_pro_pool_cooldown_original_line(line: str) -> tuple[int, str]:
    return gopay_pro_pool_service.pool_cooldown_original_line(line)


def _gopay_pro_apply_number_cooldowns(
    paths: dict[str, Path] | None = None, *, task_id: str | None = None
) -> dict[str, int]:
    resolved = paths or _gopay_pro_paths()
    cooldowns = _read_json_file(resolved["cooldowns"], {})
    if not isinstance(cooldowns, dict):
        cooldowns = {}
    entries = cooldowns.get(_gopay_pro_number_cooldown_key())
    if not isinstance(entries, dict):
        entries = {}
    now = int(time.time())
    active_entries: dict[str, dict] = {}
    expired_keys: set[str] = set()
    for phone_key, entry in list(entries.items()):
        if not isinstance(entry, dict):
            expired_keys.add(str(phone_key))
            continue
        try:
            until = int(entry.get("until") or 0)
        except Exception:
            until = 0
        if until > now:
            active_entries[str(phone_key)] = entry
        else:
            expired_keys.add(str(phone_key))

    lines = _read_lines_file(resolved["numbers"])
    next_lines: list[str] = []
    changed = False
    cooled = 0
    restored = 0
    for line in lines:
        stripped = line.strip()
        until, original = _gopay_pro_pool_cooldown_original_line(stripped)
        if original:
            phone_key = _gopay_pro_phone_key(_gopay_pro_pool_line_phone(original))
            if until <= now or phone_key not in active_entries:
                next_lines.append(original)
                changed = True
                restored += 1
            else:
                next_lines.append(line)
            continue
        if stripped and not stripped.startswith("#"):
            phone_key = _gopay_pro_phone_key(_gopay_pro_pool_line_phone(stripped))
            entry = active_entries.get(phone_key)
            if entry:
                until = int(entry.get("until") or now)
                next_lines.append(f"{_GOPAY_PRO_NUMBER_COOLDOWN_PREFIX}until={until} reason=ratelimited {stripped}")
                changed = True
                cooled += 1
                continue
        next_lines.append(line)

    if changed:
        text = "\n".join(next_lines)
        if text or lines:
            text += "\n"
        resolved["numbers"].write_text(text, encoding="utf-8")

    if expired_keys:
        for key in expired_keys:
            entries.pop(key, None)
        cooldowns[_gopay_pro_number_cooldown_key()] = entries
        cooldowns["updated_at"] = now
        _write_json_atomic(resolved["cooldowns"], cooldowns)

    if task_id and restored:
        _append_task_progress(
            task_id,
            gopay_pro_task_payloads_service.gopay_pro_register_ratelimit_cooldown_restored_progress(
                count=restored,
            ),
        )
    return {"cooled": cooled, "restored": restored, "active": len(active_entries)}


def _gopay_pro_register_ratelimited_slots_from_log(log_text: str) -> list[str]:
    return gopay_pro_events_service.register_ratelimited_slots_from_log(log_text)


def _gopay_pro_register_ratelimited_slots_from_state(paths: dict[str, Path] | None = None) -> list[str]:
    resolved = paths or _gopay_pro_paths()
    state = _read_json_file(resolved["state"], {"slots": {}})
    slots = state.get("slots") if isinstance(state, dict) else {}
    if not isinstance(slots, dict):
        return []
    result: list[str] = []
    for slot_key, slot in slots.items():
        if not isinstance(slot, dict):
            continue
        message = " ".join(
            [
                str(slot.get("state") or ""),
                str(slot.get("error") or ""),
                str(slot.get("remark") or ""),
                str(slot.get("note") or ""),
            ]
        )
        if _gopay_pro_text_has_register_ratelimit(message):
            result.append(str(slot.get("id") or slot_key or ""))
    return result


def _mark_gopay_pro_register_ratelimit_cooldowns(
    task_id: str,
    slot_ids: set[str] | list[str],
    *,
    paths: dict[str, Path] | None = None,
    reason: str = "",
) -> dict[str, Any]:
    resolved = paths or _gopay_pro_paths()
    state = _read_json_file(resolved["state"], {"slots": {}})
    slots = state.get("slots") if isinstance(state, dict) else {}
    if not isinstance(slots, dict):
        slots = {}
    slot_lookup: dict[str, dict] = {}
    for slot_key, slot in slots.items():
        if isinstance(slot, dict):
            slot_lookup[str(slot.get("id") or slot_key or "")] = slot

    number_lines = _read_lines_file(resolved["numbers"])
    active_line_by_phone = {
        _gopay_pro_phone_key(_gopay_pro_pool_line_phone(line)): line.strip()
        for line in _active_pool_lines(number_lines)
    }
    cooldowns = _read_json_file(resolved["cooldowns"], {})
    if not isinstance(cooldowns, dict):
        cooldowns = {}
    entries = cooldowns.get(_gopay_pro_number_cooldown_key())
    if not isinstance(entries, dict):
        entries = {}
    until = int(time.time() + _gopay_pro_register_ratelimit_cooldown_seconds())
    added: list[str] = []
    for slot_id in slot_ids:
        slot = slot_lookup.get(str(slot_id or ""))
        if not isinstance(slot, dict):
            continue
        phone = str(
            slot.get("full_phone") or _gopay_pro_pool_line_phone(str(slot.get("card") or "")) or slot.get("phone") or ""
        ).strip()
        phone_key = _gopay_pro_phone_key(phone)
        if not phone_key:
            continue
        line = active_line_by_phone.get(phone_key) or str(slot.get("card") or "").strip()
        if not line or line.startswith("#") or "----" not in line:
            continue
        entries[phone_key] = {
            "phone": _gopay_pro_pool_line_phone(line) or phone,
            "line": line,
            "slot_id": str(slot_id),
            "until": until,
            "reason": reason or str(slot.get("error") or "GoPay 注册限流"),
            "updated_at": int(time.time()),
        }
        added.append(str(slot_id))
    if not added:
        return {"count": 0, "slot_ids": []}
    cooldowns[_gopay_pro_number_cooldown_key()] = entries
    cooldowns["updated_at"] = int(time.time())
    _write_json_atomic(resolved["cooldowns"], cooldowns)
    apply_result = _gopay_pro_apply_number_cooldowns(resolved)
    minutes = max(1, int(_gopay_pro_register_ratelimit_cooldown_seconds() / 60))
    _append_task_progress(
        task_id,
        gopay_pro_task_payloads_service.gopay_pro_register_ratelimit_cooldown_progress(
            slot_ids=added,
            cooldown_minutes=minutes,
        ),
    )
    return {"count": len(added), "slot_ids": added, **apply_result}


def _gopay_pro_token_fingerprint(value: Any) -> str:
    return gopay_pro_pool_service.token_fingerprint(value)


def _write_gopay_pro_token_map(paths: dict[str, Path], token_items: list[dict[str, str]]) -> None:
    _write_json_atomic(paths["token_map"], gopay_pro_pool_service.build_token_map_payload(token_items, updated_at=int(time.time())))


def _gopay_pro_slot_email_from_token_map(paths: dict[str, Path], slot_id: str) -> str:
    state = _read_json_file(paths["state"], {"slots": {}})
    token_map = _read_json_file(paths["token_map"], {})
    return gopay_pro_pool_service.slot_email_from_token_map(state, token_map, slot_id)


def _gopay_pro_local_phone(value: str) -> str:
    return gopay_pro_pool_service.local_phone(value)


def _gopay_pro_slot_pick_score(slot_key: str, slot: dict, expected_key: str) -> tuple[int, int, int, int]:
    return gopay_pro_pool_service.slot_pick_score(slot_key, slot, expected_key)


def _normalize_gopay_pro_slot_ids(paths: dict[str, Path] | None = None) -> int:
    resolved = paths or _gopay_pro_paths()
    state_path = resolved["state"]
    state = _read_json_file(state_path, {"slots": {}})
    slots = state.get("slots") if isinstance(state, dict) else {}
    if not isinstance(slots, dict):
        return 0

    number_lines = _active_pool_lines(_read_lines_file(resolved["numbers"]))
    normalized_slots, changed = gopay_pro_pool_service.normalize_slots_for_number_lines(
        slots,
        number_lines,
        now=int(time.time()),
    )
    if changed:
        state["slots"] = normalized_slots
        _write_json_atomic(state_path, state)
    return changed


def _read_lines_file(path: Path) -> list[str]:
    return read_lines_file(path)


def _active_pool_lines(lines: list[str]) -> list[str]:
    return active_non_comment_lines(lines)


def _gopay_pro_pool_line_access_token(line: str) -> str:
    return gopay_pro_pool_service.pool_line_access_token(line)


def _append_unique_pool_lines(path: Path, incoming: list[str]) -> dict:
    return append_unique_non_comment_lines(path, incoming)


def _mask_gopay_pro_phone(value: Any) -> str:
    return gopay_pro_pool_service.mask_phone(value)


def _gopay_pro_status_payload() -> dict:
    root = _gopay_pro_root()
    paths = _gopay_pro_paths(root)
    _gopay_pro_apply_number_cooldowns(paths)
    _normalize_gopay_pro_slot_ids(paths)
    config = _read_json_file(paths["config"], {})
    state = _read_json_file(paths["state"], {"slots": {}})
    number_lines = _read_lines_file(paths["numbers"])
    token_lines = _read_lines_file(paths["tokens"])
    waf_cooldown = _gopay_pro_waf_cooldown_info(paths)
    tasks = [
        task
        for task in _merged_task_snapshots(compact=True)
        if str(task.get("command") or "") in {"gopay-pro", "gopay-pro-batch"}
    ][:8]
    return gopay_pro_pool_service.build_status_payload(
        root=str(root),
        exists=root.exists(),
        config=config,
        state=state,
        number_lines=number_lines,
        token_lines=token_lines,
        waf_cooldown=waf_cooldown,
        tasks=tasks,
        commands=_GOPAY_PRO_TASK_KINDS,
    )


_gopay_pro_config_router = create_gopay_pro_config_router(
    gopay_pro_paths=_gopay_pro_paths,
    read_json_file=_read_json_file,
    write_json_atomic=_write_json_atomic,
    read_lines_file=_read_lines_file,
    active_pool_lines=_active_pool_lines,
    append_unique_pool_lines=_append_unique_pool_lines,
    status_payload=_gopay_pro_status_payload,
    slot_states=_GOPAY_PRO_SLOT_STATES,
)
app.include_router(_gopay_pro_config_router)
_gopay_pro_config_endpoints = {route.endpoint.__name__: route.endpoint for route in _gopay_pro_config_router.routes}
get_gopay_pro_status = _gopay_pro_config_endpoints["get_gopay_pro_status"]
update_gopay_pro_config = _gopay_pro_config_endpoints["update_gopay_pro_config"]
import_gopay_pro_numbers = _gopay_pro_config_endpoints["import_gopay_pro_numbers"]
update_gopay_pro_slot = _gopay_pro_config_endpoints["update_gopay_pro_slot"]


def _mark_gopay_pro_success_account(email: str, *, task_id: str, message: str = "", auth_file: str = "") -> dict | None:
    from autotoken.storage.accounts import (
        ACCOUNT_SOURCE_MANAGED,
        ACCOUNT_TYPE_PLUS,
        SEAT_CODEX,
        STATUS_PLUS,
        update_account,
    )

    normalized = _normalized_email(email)
    if not normalized:
        return None
    marked_at = time.time()
    valid_auth_file = _valid_account_auth_file({"auth_file": auth_file}) if auth_file else ""
    resolved_auth_file = str(Path(valid_auth_file).resolve()) if valid_auth_file else ""
    update_fields = gopay_pro_accounts_service.success_account_update_fields(
        task_id=task_id,
        message=message,
        marked_at=marked_at,
        auth_file=resolved_auth_file,
        status_plus=STATUS_PLUS,
        account_type_plus=ACCOUNT_TYPE_PLUS,
        seat_codex=SEAT_CODEX,
        account_source_managed=ACCOUNT_SOURCE_MANAGED,
    )
    updated = update_account(
        normalized,
        **update_fields,
    )
    try:
        account_for_plan = updated if isinstance(updated, dict) else {}
        if resolved_auth_file and not account_for_plan.get("auth_file"):
            account_for_plan = {**account_for_plan, "auth_file": resolved_auth_file}
        plan_update = _update_account_cpa_auth_plan_type(
            normalized, account=account_for_plan, plan_type=ACCOUNT_TYPE_PLUS
        )
        if isinstance(updated, dict) and plan_update.get("auth_file"):
            updated["auth_file"] = plan_update["auth_file"]
    except Exception:
        logger.warning(
            "[gopay-pro] failed to update CPA auth plan_type: email=%s", _safe_email_summary(normalized), exc_info=True
        )
    return updated


def _mark_gopay_pro_failed_account(email: str, *, task_id: str, status: str, message: str, failure_stage: str) -> None:
    from autotoken.storage.accounts import update_account

    normalized = _normalized_email(email)
    if not normalized:
        return
    update_account(
        normalized,
        **gopay_pro_accounts_service.failed_account_update_fields(
            task_id=task_id,
            status=status,
            message=message,
            failure_stage=failure_stage,
            marked_at=time.time(),
        ),
    )


def _gopay_pro_probe_openai_plan(access_token: str, account_id: str = "", *, timeout: float = 25.0) -> dict:
    token = _normalize_access_token(access_token)
    if not token:
        return gopay_pro_accounts_service.usage_probe_missing_token_result()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    account_id = str(account_id or "").strip()
    if account_id:
        headers["Chatgpt-Account-Id"] = account_id
    try:
        resp = requests.get(
            "https://chatgpt.com/backend-api/wham/usage",
            headers=headers,
            params={"account_id": account_id} if account_id else None,
            timeout=max(5.0, float(timeout or 25.0)),
        )
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.SSLError) as exc:
        return gopay_pro_accounts_service.usage_probe_exception_result(kind="网络异常", error=exc)
    except requests.exceptions.RequestException as exc:
        return gopay_pro_accounts_service.usage_probe_exception_result(kind="请求异常", error=exc)
    except Exception as exc:
        return gopay_pro_accounts_service.usage_probe_exception_result(kind="未知异常", error=exc)

    if resp.status_code != 200:
        return gopay_pro_accounts_service.usage_probe_http_result(status_code=resp.status_code, text=resp.text)

    try:
        payload = resp.json()
    except Exception as exc:
        return gopay_pro_accounts_service.usage_probe_json_error_result(exc)
    plan_type = str((payload or {}).get("plan_type") or "").strip().lower()
    return gopay_pro_accounts_service.usage_probe_ok_result(plan_type)


def _gopay_pro_save_refreshed_auth_file(auth_file: str, auth_data: dict, refreshed: dict) -> None:
    path = _trusted_token_auth_path(auth_file)
    if not path or not isinstance(auth_data, dict) or not isinstance(refreshed, dict):
        return
    next_data = gopay_pro_accounts_service.refreshed_auth_data(auth_data, refreshed, now=time.time())
    path.write_text(json.dumps(next_data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        from autotoken.storage.auth_index import upsert_codex_auth_file
        from autotoken.storage.auth_storage import ensure_auth_file_permissions

        ensure_auth_file_permissions(path)
        upsert_codex_auth_file(path, next_data, main=path.name.startswith("codex-main-"))
    except Exception as exc:
        logger.warning("[gopay-pro] 刷新后的 CPA auth 索引写入失败: %s", exc)


def _gopay_pro_verify_plus_plan(item: dict[str, str]) -> dict:
    email = str(item.get("email") or "").strip()
    auth_file = _valid_token_item_auth_file(item)
    auth_data: dict[str, Any] = {}
    if auth_file:
        try:
            auth_path = _trusted_token_auth_path(auth_file)
            if auth_path:
                auth_data = read_auth_json_file(auth_path)
        except Exception as exc:
            return gopay_pro_accounts_service.plus_plan_auth_file_read_error_result(exc)
    access_token = _normalize_access_token(
        item.get("access_token") or auth_data.get("access_token") or auth_data.get("accessToken") or ""
    )
    refresh_token = str(
        item.get("refresh_token") or auth_data.get("refresh_token") or auth_data.get("refreshToken") or ""
    ).strip()
    account_id = str(item.get("account_id") or auth_data.get("account_id") or auth_data.get("accountId") or "").strip()
    attempts = max(1, int(_env_float("GOPAY_PRO_PLUS_VERIFY_ATTEMPTS", 3)))
    wait_seconds = max(0.0, _env_float("GOPAY_PRO_PLUS_VERIFY_INTERVAL_SECONDS", 5.0))
    refreshed_once = False
    last_probe: dict = gopay_pro_accounts_service.usage_probe_missing_token_result()

    for attempt in range(1, attempts + 1):
        last_probe = _gopay_pro_probe_openai_plan(access_token, account_id)
        plan_type = str(last_probe.get("plan_type") or "").strip().lower()
        if plan_type in {"plus", "pro"}:
            return gopay_pro_accounts_service.plus_plan_verified_result(plan_type)

        if refresh_token and not refreshed_once:
            refreshed_once = True
            try:
                from autotoken.auth.codex_auth import refresh_access_token

                refreshed = refresh_access_token(refresh_token)
            except Exception as exc:
                refreshed = None
                last_probe = gopay_pro_accounts_service.plus_plan_refresh_exception_probe(
                    last_probe,
                    plan_type=plan_type,
                    error=exc,
                )
            if refreshed and refreshed.get("access_token"):
                access_token = _normalize_access_token(refreshed.get("access_token") or access_token)
                refresh_token = str(refreshed.get("refresh_token") or refresh_token)
                _gopay_pro_save_refreshed_auth_file(auth_file, auth_data, refreshed)
                continue

        if attempt < attempts and wait_seconds > 0:
            time.sleep(wait_seconds)

    return gopay_pro_accounts_service.plus_plan_unverified_result(email=email, last_probe=last_probe)


def _gopay_pro_normalize_observed_auth_plan(email: str, auth_file: str, plan_type: str) -> None:
    observed_plan = str(plan_type or "").strip().lower()
    if observed_plan not in {"free", "plus", "pro", "team"}:
        return
    try:
        _update_account_cpa_auth_plan_type(
            email,
            account={"auth_file": auth_file},
            plan_type=observed_plan,
        )
    except Exception:
        logger.warning(
            "[gopay-pro] 同步实测 auth plan_type 失败: email=%s plan=%s",
            _safe_email_summary(email),
            observed_plan,
            exc_info=True,
        )


def _gopay_pro_account_token_items(account_emails: list[str]) -> list[dict[str, str]]:
    from autotoken.storage.accounts import ACCOUNT_TYPE_PLUS, STATUS_PLUS, find_account
    from autotoken.storage.auth_session_store import get_auth_session_file

    accounts = _load_accounts_with_session_stubs(include_session_stubs=True)
    items: list[dict[str, str]] = []
    seen_tokens: set[str] = set()
    for email in gopay_pro_accounts_service.normalized_account_emails(account_emails):
        account = find_account(accounts, email)
        if not account:
            raise HTTPException(status_code=404, detail=f"账号不在当前项目号池中: {email}")
        if gopay_pro_accounts_service.account_already_plus(
            account,
            status_plus=STATUS_PLUS,
            account_type_plus=ACCOUNT_TYPE_PLUS,
        ):
            raise HTTPException(status_code=400, detail=f"账号已是 Plus，无需重复绑定: {email}")
        auth_file = _resolve_codex_auth_file(account or {"email": email}) if account else ""
        if not auth_file:
            candidate = get_auth_session_file(email) or ""
            if candidate and Path(candidate).exists():
                auth_file = candidate
        auth_path = _trusted_token_auth_path(auth_file)
        if not auth_path:
            raise HTTPException(status_code=400, detail=f"账号缺少可用 auth_file/auth_session: {email}")
        try:
            auth_data = read_auth_json_file(auth_path)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"账号认证文件不是有效 JSON: {email} ({exc})") from exc
        item = gopay_pro_accounts_service.account_token_item(
            email=email,
            auth_data=auth_data,
            auth_file=str(auth_path.resolve()),
        )
        access_token = item["access_token"]
        access_error = gopay_pro_accounts_service.account_token_item_access_error(item, seen_tokens)
        if access_error:
            raise HTTPException(status_code=400, detail=access_error)
        seen_tokens.add(access_token)
        items.append(item)
    if not items:
        raise HTTPException(status_code=400, detail="请选择至少一个号池账号")
    return items


def _run_gopay_pro_script(
    kind: str,
    task_id: str,
    *,
    stage: str = "",
    args: list[str] | None = None,
    suppress_status_table: bool = False,
    account_emails: list[str] | None = None,
) -> dict:
    from autotoken.core import cancel_signal

    root = _gopay_pro_root()
    paths = _gopay_pro_paths(root)
    if kind == "register":
        _gopay_pro_apply_number_cooldowns(paths, task_id=task_id)
        existing_ratelimited_slots = set(_gopay_pro_register_ratelimited_slots_from_state(paths))
        if existing_ratelimited_slots:
            _mark_gopay_pro_register_ratelimit_cooldowns(
                task_id,
                existing_ratelimited_slots,
                paths=paths,
                reason="GoPay 注册限流",
            )
            _gopay_pro_apply_number_cooldowns(paths, task_id=task_id)
    _normalize_gopay_pro_slot_ids(paths)
    scripts = {
        "register": "reg.cmd" if os.name == "nt" else "reg.sh",
        "harvest": "harvest.cmd" if os.name == "nt" else "harvest.sh",
        "rebind": "rebind.cmd" if os.name == "nt" else "rebind.sh",
        "status": "status.cmd" if os.name == "nt" else "status.sh",
        "refresh": "refresh.cmd" if os.name == "nt" else "refresh.sh",
        "linkedapps": "linkedapps.cmd" if os.name == "nt" else "linkedapps.sh",
        "profile": "profile.cmd" if os.name == "nt" else "profile.sh",
        "fix-failed": "fix-failed.cmd" if os.name == "nt" else "fix-failed.sh",
        "link-only": "link-only.cmd" if os.name == "nt" else "link-only.sh",
    }
    script = scripts.get(str(kind or ""))
    if not script:
        raise RuntimeError("未知 GoPay Pro 任务")
    script_path = root / script
    if not script_path.exists():
        raise RuntimeError(f"脚本不存在: {script_path}")
    script_args = _safe_gopay_pro_script_args(args or [])
    if kind == "register":
        cooldown = _gopay_pro_waf_cooldown_info(paths)
        if cooldown["remaining_seconds"] > 0:
            _append_task_progress(
                task_id,
                gopay_pro_task_payloads_service.gopay_pro_register_waf_cooling_progress(
                    cooldown_remaining_seconds=cooldown["remaining_seconds"],
                ),
            )
            return {
                "kind": kind,
                "script": script,
                "args": script_args,
                "exit_code": 75,
                "log_tail": "",
                "log_text": "",
                "waf_blocked": True,
                "cooldown_remaining_seconds": cooldown["remaining_seconds"],
            }
    command = (
        ["cmd.exe", "/c", str(script_path), *script_args]
        if os.name == "nt"
        else ["bash", str(script_path), *script_args]
    )
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )

    def _terminate_process() -> None:
        try:
            if process.poll() is None:
                process.terminate()
        except Exception:
            logger.debug("[gopay-pro] terminate failed", exc_info=True)

    unregister = _register_task_cancel_hook(task_id, _terminate_process)
    log_tail = ""
    log_text = ""
    in_status_table = False
    waf_blocked = False
    waf_cooldown: dict[str, Any] | None = None
    register_ratelimited_slots: set[str] = set()
    harvest_slot_emails: dict[str, str] = {}
    try:
        assert process.stdout is not None
        for line in process.stdout:
            stripped = line.strip()
            if suppress_status_table:
                if re.match(r"^SLOT\s+状态\s+号码\s+余额\s+备注", stripped):
                    in_status_table = True
                    continue
                if in_status_table:
                    if stripped.startswith("汇总:"):
                        in_status_table = False
                    continue
            log_tail = (log_tail + line)[-6000:]
            log_text = (log_text + line)[-200000:]
            display_message = stripped or f"{script} 输出"
            if kind == "harvest":
                started = re.search(r"\[(slot-[^\]\s]+)\]\s+开\s*Plus", stripped, re.IGNORECASE)
                if started:
                    slot_id = started.group(1)
                    email = _gopay_pro_slot_email_from_token_map(paths, slot_id)
                    if email:
                        harvest_slot_emails[slot_id] = email
                current = re.search(r"\[(slot-[^\]\s]+)\]", stripped)
                slot_id = current.group(1) if current else ""
                email = harvest_slot_emails.get(slot_id, "") if slot_id else ""
                if not email and slot_id:
                    email = _gopay_pro_slot_email_from_token_map(paths, slot_id)
                    if email:
                        harvest_slot_emails[slot_id] = email
                if email and ("开 Plus" in stripped or "Plus 开通成功" in stripped or "换绑完成" in stripped):
                    display_message = f"{stripped} | email={email}"
            _append_task_progress(
                task_id,
                {
                    "stage": stage or f"gopay_pro_{kind}",
                    "message": display_message,
                    "script": script,
                    "log_tail": log_tail,
                },
            )
            if kind == "register" and not waf_blocked and _gopay_pro_text_has_waf_block(stripped):
                waf_blocked = True
                waf_cooldown = _mark_gopay_pro_waf_cooldown(task_id, source=stripped[:500])
            if kind == "register" and _gopay_pro_text_has_register_ratelimit(stripped):
                match = re.search(r"\[(slot-[^\]\s]+)\]", stripped)
                if match:
                    register_ratelimited_slots.add(match.group(1))
            if cancel_signal.is_cancelled():
                _terminate_process()
                break
        exit_code = process.wait()
    finally:
        unregister()
        if kind == "register":
            register_ratelimited_slots.update(_gopay_pro_register_ratelimited_slots_from_log(log_text))
            register_ratelimited_slots.update(_gopay_pro_register_ratelimited_slots_from_state(paths))
            if register_ratelimited_slots:
                _mark_gopay_pro_register_ratelimit_cooldowns(
                    task_id,
                    register_ratelimited_slots,
                    paths=paths,
                    reason="GoPay 注册限流",
                )
            _gopay_pro_apply_number_cooldowns(paths, task_id=task_id)
        if kind == "harvest":
            charge_202_slots = _gopay_pro_midtrans_charge_202_slots(log_text)
            if charge_202_slots:
                _mark_gopay_pro_midtrans_charge_202_slots(task_id, charge_202_slots, paths=paths)
        _normalize_gopay_pro_slot_ids(paths)
    return {
        "kind": kind,
        "script": script,
        "args": script_args,
        "exit_code": exit_code,
        "log_tail": log_tail,
        "log_text": log_text,
        "waf_blocked": waf_blocked,
        "cooldown_remaining_seconds": (waf_cooldown or {}).get("remaining_seconds", 0),
        "register_ratelimited_slots": sorted(register_ratelimited_slots),
        "slot_emails": harvest_slot_emails,
    }


_GOPAY_PRO_SCRIPT_ARG_RE = re.compile(r"^[A-Za-z0-9@._:+=,/%-]+$")


def _safe_gopay_pro_script_args(args: list[str]) -> list[str]:
    safe_args: list[str] = []
    for raw in args:
        value = str(raw or "").strip()
        if not value:
            continue
        if not _GOPAY_PRO_SCRIPT_ARG_RE.fullmatch(value):
            raise RuntimeError(f"GoPay Pro 脚本参数包含不安全字符: {value[:40]}")
        safe_args.append(value)
    return safe_args


def _set_gopay_pro_no_trial_slots_ready(
    round_tokens: set[str] | None, task_id: str, slot_ids: set[str] | None = None
) -> int:
    paths = _gopay_pro_paths()
    state = _read_json_file(paths["state"], {"slots": {}})
    slots = state.get("slots") if isinstance(state, dict) else {}
    if not isinstance(slots, dict):
        return 0
    next_slots, changed = gopay_pro_pool_service.release_no_trial_slots(
        slots,
        round_tokens=round_tokens,
        slot_ids=slot_ids,
        now=int(time.time()),
    )
    if changed:
        state["slots"] = next_slots
        _write_json_atomic(paths["state"], state)
        _append_task_progress(
            task_id,
            gopay_pro_task_payloads_service.gopay_pro_no_trial_wallets_released_progress(count=changed),
        )
    return changed


def _gopay_pro_harvest_started_slots(log_text: str) -> list[str]:
    return gopay_pro_events_service.harvest_started_slots(log_text)


def _gopay_pro_text_has_token_invalidated(value: Any) -> bool:
    return gopay_pro_events_service.text_has_token_invalidated(value)


def _gopay_pro_text_has_chatgpt_checkout_unauthorized(value: Any) -> bool:
    return gopay_pro_events_service.text_has_chatgpt_checkout_unauthorized(value)


def _gopay_pro_slot_log_has_token_invalidated(log_text: str, slot_id: str) -> bool:
    return gopay_pro_events_service.slot_log_has_token_invalidated(log_text, slot_id)


def _gopay_pro_slot_log_has_chatgpt_checkout_unauthorized(log_text: str, slot_id: str) -> bool:
    return gopay_pro_events_service.slot_log_has_chatgpt_checkout_unauthorized(log_text, slot_id)


def _gopay_pro_harvest_checkout_unauthorized_slots(log_text: str) -> list[str]:
    return gopay_pro_events_service.harvest_checkout_unauthorized_slots(log_text)


def _gopay_pro_midtrans_charge_202_slots(log_text: str) -> list[str]:
    return gopay_pro_events_service.midtrans_charge_202_slots(log_text)


def _mark_gopay_pro_midtrans_charge_202_slots(
    task_id: str,
    slot_ids: list[str] | set[str],
    *,
    paths: dict[str, Path] | None = None,
) -> int:
    wanted = {str(slot_id or "").strip() for slot_id in slot_ids if str(slot_id or "").strip()}
    if not wanted:
        return 0
    resolved = paths or _gopay_pro_paths()
    state = _read_json_file(resolved["state"], {"slots": {}})
    slots = state.get("slots") if isinstance(state, dict) else {}
    if not isinstance(slots, dict):
        return 0
    next_slots, marked = gopay_pro_pool_service.mark_midtrans_charge_202_slots(slots, wanted, now=int(time.time()))
    if not marked:
        return 0
    state["slots"] = next_slots
    _write_json_atomic(resolved["state"], state)
    _append_task_progress(
        task_id,
        gopay_pro_task_payloads_service.gopay_pro_midtrans_charge_202_marked_progress(slot_ids=marked),
    )
    return len(marked)


def _gopay_pro_slot_log_has_success(log_text: str, slot_id: str) -> bool:
    return gopay_pro_events_service.slot_log_has_success(log_text, slot_id)


def _gopay_pro_harvest_terminal_events(log_text: str) -> list[dict[str, str]]:
    return gopay_pro_events_service.harvest_terminal_events(log_text)


def _gopay_pro_payment_validate_failed_slots(log_text: str) -> list[str]:
    return gopay_pro_events_service.payment_validate_failed_slots(log_text)


def _gopay_pro_slots_in_states(slot_ids: list[str], states: set[str]) -> list[str]:
    paths = _gopay_pro_paths()
    state = _read_json_file(paths["state"], {"slots": {}})
    slots = state.get("slots") if isinstance(state, dict) else {}
    if not isinstance(slots, dict):
        return []
    return gopay_pro_pool_service.slots_in_states(slots, slot_ids, states)


def _run_gopay_pro_recovery_command(task_id: str, *, stage: str, reason: str) -> dict:
    _append_task_progress(
        task_id,
        gopay_pro_task_payloads_service.gopay_pro_recovery_started_progress(stage=stage, reason=reason),
    )
    result = _run_gopay_pro_script("fix-failed", task_id, stage=stage, suppress_status_table=True)
    exit_code = int(result.get("exit_code") or 0)
    if exit_code != 0:
        _append_task_progress(
            task_id,
            gopay_pro_task_payloads_service.gopay_pro_recovery_failed_progress(
                stage=stage,
                exit_code=exit_code,
            ),
        )
    return result


def _run_gopay_pro_refresh_command(task_id: str) -> dict:
    _append_task_progress(
        task_id,
        gopay_pro_task_payloads_service.gopay_pro_refresh_started_progress(),
    )
    result = _run_gopay_pro_script("refresh", task_id, stage="gopay_pro_refresh", suppress_status_table=True)
    exit_code = int(result.get("exit_code") or 0)
    if exit_code != 0:
        _append_task_progress(
            task_id,
            gopay_pro_task_payloads_service.gopay_pro_refresh_failed_progress(exit_code=exit_code),
        )
    return result


def _repair_gopay_pro_payment_validate_failed_slots(task_id: str, slot_ids: list[str]) -> None:
    slots = [slot_id for slot_id in slot_ids if re.fullmatch(r"slot-\d+", str(slot_id or ""))]
    if not slots:
        return
    _run_gopay_pro_recovery_command(
        task_id,
        stage="gopay_pro_fix_failed_after_validate",
        reason=f"检测到 {len(slots)} 个 payment/validate 失败 slot，先执行 fix-failed 无损恢复",
    )
    _reset_gopay_pro_stuck_paying_slots(task_id)
    remaining_failed = _gopay_pro_slots_in_states(slots, {"FAILED"})
    if not remaining_failed:
        _append_task_progress(
            task_id,
            gopay_pro_task_payloads_service.gopay_pro_validate_failed_recovered_progress(slots=slots),
        )
        return
    slots = remaining_failed
    _append_task_progress(
        task_id,
        gopay_pro_task_payloads_service.gopay_pro_validate_failed_repair_started_progress(slots=slots),
    )
    repaired = 0
    for slot_id in slots:
        result = _run_gopay_pro_script(
            "rebind",
            task_id,
            stage="gopay_pro_validate_failed_rebind",
            args=["--slot", slot_id],
            suppress_status_table=True,
        )
        if int(result.get("exit_code") or 0) == 0:
            repaired += 1
        else:
            _append_task_progress(
                task_id,
                gopay_pro_task_payloads_service.gopay_pro_validate_failed_rebind_failed_progress(
                    slot=slot_id,
                    exit_code=result.get("exit_code"),
                ),
            )
    if repaired:
        _append_task_progress(
            task_id,
            gopay_pro_task_payloads_service.gopay_pro_validate_failed_register_started_progress(
                slots=slots,
                repaired=repaired,
            ),
        )
        _run_gopay_pro_script("register", task_id, stage="gopay_pro_validate_failed_register")


def _reset_gopay_pro_unusable_ready_slots(task_id: str) -> int:
    paths = _gopay_pro_paths()
    state = _read_json_file(paths["state"], {"slots": {}})
    slots = state.get("slots") if isinstance(state, dict) else {}
    if not isinstance(slots, dict):
        return 0
    next_slots, changed = gopay_pro_pool_service.reset_unusable_ready_slots(slots, now=int(time.time()))
    if changed:
        state["slots"] = next_slots
        _write_json_atomic(paths["state"], state)
        _append_task_progress(
            task_id,
            gopay_pro_task_payloads_service.gopay_pro_unusable_wallets_reset_progress(count=changed),
        )
    return changed


def _reset_gopay_pro_stuck_paying_slots(task_id: str) -> int:
    paths = _gopay_pro_paths()
    state = _read_json_file(paths["state"], {"slots": {}})
    slots = state.get("slots") if isinstance(state, dict) else {}
    if not isinstance(slots, dict):
        return 0
    next_slots, changed = gopay_pro_pool_service.reset_stuck_paying_slots(slots, now=int(time.time()))
    if changed:
        state["slots"] = next_slots
        _write_json_atomic(paths["state"], state)
        _append_task_progress(
            task_id,
            gopay_pro_task_payloads_service.gopay_pro_stuck_paying_slots_released_progress(count=changed),
        )
    return changed


def _gopay_pro_slot_index(slot: dict | str) -> int:
    return gopay_pro_pool_service.slot_index(slot)


def _gopay_pro_ready_slot_prefix(paths: dict[str, Path], required: int) -> tuple[int, int]:
    state = _read_json_file(paths["state"], {"slots": {}})
    slots = (state.get("slots") or {}) if isinstance(state, dict) else {}
    return gopay_pro_pool_service.ready_slot_prefix_from_slots(slots, required)


def _set_gopay_pro_runtime_slots(paths: dict[str, Path], slot_count: int) -> None:
    config = _read_json_file(paths["config"], {})
    if not isinstance(config, dict):
        config = {}
    pool = config.setdefault("pool", {})
    if not isinstance(pool, dict):
        pool = {}
        config["pool"] = pool
    pool["slots"] = max(1, min(50, int(slot_count or 1)))
    _write_json_atomic(paths["config"], config)


def _run_gopay_pro_batch_task(
    task_id: str, account_emails: list[str], concurrency: int | None = None, max_attempts: int = 3
) -> dict:
    from autotoken.core import cancel_signal

    paths = _gopay_pro_paths()
    if not paths["root"].exists():
        raise RuntimeError(f"CNgopay 目录不存在: {paths['root']}")
    _gopay_pro_apply_number_cooldowns(paths, task_id=task_id)
    _normalize_gopay_pro_slot_ids(paths)
    token_items = _gopay_pro_account_token_items(account_emails)
    config = _read_json_file(paths["config"], {})
    pool_cfg = config.get("pool") if isinstance(config.get("pool"), dict) else {}
    number_count = len(_active_pool_lines(_read_lines_file(paths["numbers"])))
    configured_slots = max(1, int(number_count or pool_cfg.get("slots") or 1))
    configured_concurrency = max(1, int(pool_cfg.get("concurrency") or configured_slots))
    round_size = max(1, min(50, int(concurrency or configured_concurrency or configured_slots), configured_slots))
    max_attempts = max(1, min(10, int(max_attempts or 3)))
    token_to_item = {item["access_token"]: item for item in token_items}
    pending = [item["access_token"] for item in token_items]
    attempts = {token: 0 for token in pending}
    successful: list[str] = []
    failed: list[dict] = []
    retried: list[str] = []
    terminal_consumed_tokens: set[str] = set()
    original_tokens_text = paths["tokens"].read_text(encoding="utf-8") if paths["tokens"].exists() else ""

    def _restore_token_file() -> None:
        paths["tokens"].parent.mkdir(parents=True, exist_ok=True)
        if not terminal_consumed_tokens:
            paths["tokens"].write_text(original_tokens_text, encoding="utf-8")
            return
        restored_lines = []
        for line in original_tokens_text.splitlines():
            token = _gopay_pro_pool_line_access_token(line)
            if token and token in terminal_consumed_tokens:
                continue
            restored_lines.append(line)
        restored_text = "\n".join(restored_lines)
        if restored_text or original_tokens_text.endswith("\n"):
            restored_text += "\n"
        paths["tokens"].write_text(restored_text, encoding="utf-8")

    _append_task_progress(
        task_id,
        gopay_pro_task_payloads_service.gopay_pro_batch_started_progress(
            total=len(token_items),
            concurrency=round_size,
            max_attempts=max_attempts,
        ),
    )

    try:
        _run_gopay_pro_refresh_command(task_id)
        _run_gopay_pro_recovery_command(
            task_id,
            stage="gopay_pro_fix_failed_before_batch",
            reason="批量开始前执行 fix-failed，先恢复钱未扣且 token 还可用的 FAILED 钱包",
        )
        _set_gopay_pro_no_trial_slots_ready(None, task_id)
        _reset_gopay_pro_unusable_ready_slots(task_id)
        _reset_gopay_pro_stuck_paying_slots(task_id)
        round_index = 0
        while pending and not cancel_signal.is_cancelled():
            round_index += 1
            _gopay_pro_apply_number_cooldowns(paths, task_id=task_id)
            _reset_gopay_pro_unusable_ready_slots(task_id)
            _reset_gopay_pro_stuck_paying_slots(task_id)
            number_count = len(_active_pool_lines(_read_lines_file(paths["numbers"])))
            if number_count <= 0:
                raise RuntimeError("稳定号池为空，请先添加稳定手机号")
            current_round_size = min(round_size, number_count, len(pending))
            round_tokens = pending[:current_round_size]
            pending = pending[current_round_size:]
            for token in round_tokens:
                attempts[token] += 1
            round_emails = [token_to_item[token]["email"] for token in round_tokens]
            _write_gopay_pro_token_map(paths, [token_to_item[token] for token in round_tokens])
            paths["tokens"].write_text("\n".join(round_tokens) + "\n", encoding="utf-8")
            ready_count, ready_prefix = _gopay_pro_ready_slot_prefix(paths, len(round_tokens))
            runtime_slot_count = min(number_count, max(len(round_tokens), ready_prefix or len(round_tokens)))
            _set_gopay_pro_runtime_slots(paths, runtime_slot_count)
            _append_task_progress(
                task_id,
                gopay_pro_task_payloads_service.gopay_pro_round_started_progress(
                    round_index=round_index,
                    current=len(successful) + len(failed),
                    total=len(token_items),
                    round_total=len(round_tokens),
                    ready_slots=ready_count,
                    runtime_slots=runtime_slot_count,
                    account_emails=round_emails,
                ),
            )
            reg_result = {"exit_code": 0, "log_tail": ""}
            if ready_count >= len(round_tokens):
                _append_task_progress(
                    task_id,
                    gopay_pro_task_payloads_service.gopay_pro_register_skipped_progress(
                        round_index=round_index,
                        ready_slots=ready_count,
                        round_total=len(round_tokens),
                    ),
                )
            else:
                reg_result = _run_gopay_pro_script("register", task_id, stage="gopay_pro_register")
            if reg_result.get("waf_blocked"):
                remaining = int(reg_result.get("cooldown_remaining_seconds") or 0)
                _append_task_progress(
                    task_id,
                    gopay_pro_task_payloads_service.gopay_pro_register_waf_abort_progress(
                        round_index=round_index,
                        cooldown_remaining_seconds=remaining,
                    ),
                )
                raise RuntimeError("GoPay 注册触发 WAF Block，已停止批量任务，避免继续撞风控")
            if int(reg_result["exit_code"] or 0) != 0:
                _append_task_progress(
                    task_id,
                    gopay_pro_task_payloads_service.gopay_pro_register_failed_progress(
                        round_index=round_index,
                        exit_code=reg_result["exit_code"],
                    ),
                )
            if cancel_signal.is_cancelled():
                break
            harvest_result = _run_gopay_pro_script(
                "harvest",
                task_id,
                stage="gopay_pro_harvest",
                account_emails=round_emails,
            )
            harvest_log_text = str(harvest_result.get("log_text") or harvest_result.get("log_tail") or "")
            validate_failed_slots = _gopay_pro_payment_validate_failed_slots(harvest_log_text)
            harvest_ok = int(harvest_result.get("exit_code") or 0) == 0
            if not harvest_ok:
                _append_task_progress(
                    task_id,
                    gopay_pro_task_payloads_service.gopay_pro_harvest_failed_progress(
                        round_index=round_index,
                        exit_code=harvest_result.get("exit_code"),
                    ),
                )
            _repair_gopay_pro_payment_validate_failed_slots(task_id, validate_failed_slots)
            _reset_gopay_pro_stuck_paying_slots(task_id)
            remaining_tokens = set(_active_pool_lines(_read_lines_file(paths["tokens"])))
            state = _read_json_file(paths["state"], {"slots": {}})
            slots = (state.get("slots") or {}) if isinstance(state, dict) else {}
            slot_by_id = {
                str(slot_id or slot.get("id") or ""): {**slot, "id": str(slot_id or slot.get("id") or "")}
                for slot_id, slot in slots.items()
                if isinstance(slot, dict)
            }
            started_slots = _gopay_pro_harvest_started_slots(harvest_log_text)
            token_slot_ids = {
                token: started_slots[index] for index, token in enumerate(round_tokens) if index < len(started_slots)
            }
            token_by_slot_id = {slot_id: token for token, slot_id in token_slot_ids.items() if slot_id}
            token_by_email = {
                str(item.get("email") or "").strip(): token
                for token, item in token_to_item.items()
                if str(item.get("email") or "").strip()
            }
            consumed_tokens = [token for token in round_tokens if token not in remaining_tokens]
            success_tokens: list[str] = []
            no_trial_tokens: set[str] = set()
            no_trial_slot_ids: set[str] = set()
            token_invalidated_tokens: set[str] = set()
            checkout_unauthorized_tokens: set[str] = set()
            ambiguous_tokens: list[str] = []
            harvest_log_tail = harvest_log_text
            for token in round_tokens:
                slot_id = token_slot_ids.get(token, "")
                slot = slot_by_id.get(slot_id) or {}
                slot_error = str(slot.get("error") or "")
                if slot_id and (
                    _gopay_pro_text_has_token_invalidated(slot_error)
                    or _gopay_pro_slot_log_has_token_invalidated(harvest_log_tail, slot_id)
                ):
                    token_invalidated_tokens.add(token)
                if slot_id and (
                    _gopay_pro_text_has_chatgpt_checkout_unauthorized(slot_error)
                    or _gopay_pro_slot_log_has_chatgpt_checkout_unauthorized(harvest_log_tail, slot_id)
                ):
                    checkout_unauthorized_tokens.add(token)
            for slot_id in _gopay_pro_harvest_checkout_unauthorized_slots(harvest_log_tail):
                token = token_by_slot_id.get(slot_id, "")
                if not token:
                    slot = slot_by_id.get(slot_id) or {}
                    slot_token = _normalize_access_token(slot.get("access_token") or slot.get("accessToken") or "")
                    if slot_token in token_to_item:
                        token = slot_token
                if not token:
                    email = _gopay_pro_slot_email_from_token_map(paths, slot_id)
                    token = token_by_email.get(email, "")
                if token and token in token_to_item:
                    checkout_unauthorized_tokens.add(token)
            consumed_queue = [
                token
                for token in consumed_tokens
                if token not in token_invalidated_tokens and token not in checkout_unauthorized_tokens
            ]
            terminal_events = _gopay_pro_harvest_terminal_events(harvest_log_tail)
            for event in terminal_events:
                slot_id = str(event.get("slot_id") or "")
                kind = str(event.get("kind") or "")
                if kind in {"checkout_unauthorized", "token_invalidated"}:
                    event_token = token_by_slot_id.get(slot_id, "")
                    if not event_token:
                        slot = slot_by_id.get(slot_id) or {}
                        slot_token = _normalize_access_token(slot.get("access_token") or slot.get("accessToken") or "")
                        if slot_token in token_to_item:
                            event_token = slot_token
                    if not event_token:
                        email = _gopay_pro_slot_email_from_token_map(paths, slot_id)
                        event_token = token_by_email.get(email, "")
                    if event_token:
                        if kind == "checkout_unauthorized":
                            checkout_unauthorized_tokens.add(event_token)
                        else:
                            token_invalidated_tokens.add(event_token)
                        if event_token in consumed_queue:
                            consumed_queue.remove(event_token)
                        continue
                if not consumed_queue:
                    break
                token = consumed_queue.pop(0)
                if kind == "success":
                    success_tokens.append(token)
                elif kind == "no_trial":
                    no_trial_tokens.add(token)
                    if slot_id:
                        no_trial_slot_ids.add(slot_id)
                elif kind == "token_invalidated":
                    token_invalidated_tokens.add(token)
                elif kind == "checkout_unauthorized":
                    checkout_unauthorized_tokens.add(token)

            if consumed_queue and not terminal_events:
                for token in list(consumed_queue):
                    slot_id = token_slot_ids.get(token, "")
                    slot_state = str((slot_by_id.get(slot_id) or {}).get("state") or "")
                    if slot_state == "RELEASED" or _gopay_pro_slot_log_has_success(harvest_log_tail, slot_id):
                        success_tokens.append(token)
                        consumed_queue.remove(token)
                    elif slot_state == "NO_TRIAL":
                        no_trial_tokens.add(token)
                        if slot_id:
                            no_trial_slot_ids.add(slot_id)
                        consumed_queue.remove(token)

            ambiguous_tokens.extend(consumed_queue)
            terminal_consumed_tokens.update(success_tokens)
            terminal_consumed_tokens.update(no_trial_tokens)
            terminal_consumed_tokens.update(token_invalidated_tokens)
            terminal_consumed_tokens.update(checkout_unauthorized_tokens)
            terminal_consumed_tokens.update(ambiguous_tokens)
            terminal_round_tokens = (
                set(success_tokens)
                | set(no_trial_tokens)
                | set(token_invalidated_tokens)
                | set(checkout_unauthorized_tokens)
                | set(ambiguous_tokens)
            )
            retry_tokens = [token for token in round_tokens if token not in terminal_round_tokens]

            for token in success_tokens:
                email = token_to_item[token]["email"]
                plan_verification = _gopay_pro_verify_plus_plan(token_to_item[token])
                if not plan_verification.get("ok"):
                    plan_message = str(plan_verification.get("message") or "OpenAI Plus 状态未确认")
                    _gopay_pro_normalize_observed_auth_plan(
                        email,
                        token_to_item[token].get("auth_file") or "",
                        str(plan_verification.get("plan_type") or ""),
                    )
                    failed.append(
                        {
                            "email": email,
                            "failure_stage": "post_payment_plan_verify",
                            "message": plan_message,
                        }
                    )
                    _mark_gopay_pro_failed_account(
                        email,
                        task_id=task_id,
                        status="pending_manual",
                        message=f"GoPay Pro 支付链路完成，但 {plan_message}",
                        failure_stage="post_payment_plan_verify",
                    )
                    _append_task_progress(
                        task_id,
                        gopay_pro_task_payloads_service.gopay_pro_account_plan_unconfirmed_progress(
                            email=email,
                            failed=len(failed),
                            total=len(token_items),
                            plan_message=plan_message,
                        ),
                    )
                    continue
                if email not in successful:
                    successful.append(email)
                _mark_gopay_pro_success_account(
                    email,
                    task_id=task_id,
                    message="GoPay Pro 全自动绑定成功",
                    auth_file=token_to_item[token].get("auth_file") or "",
                )
                _append_task_progress(
                    task_id,
                    gopay_pro_task_payloads_service.gopay_pro_account_success_progress(
                        email=email,
                        successful=len(successful),
                        total=len(token_items),
                    ),
                )

            for token in no_trial_tokens:
                email = token_to_item[token]["email"]
                failed.append({"email": email, "failure_stage": "no_trial", "message": "账号无免费试用资格"})
                removed = _remove_pool_accounts_from_local_and_mail(
                    [email],
                    log_context="gopay-pro",
                    reason="no_trial",
                    message="GoPay Pro 账号无免费试用资格，已从号池删除",
                )
                _append_task_progress(
                    task_id,
                    gopay_pro_task_payloads_service.gopay_pro_account_no_trial_progress(
                        email=email,
                        failed=len(failed),
                        total=len(token_items),
                        removed=email in removed,
                    ),
                )
            _set_gopay_pro_no_trial_slots_ready(no_trial_tokens, task_id, no_trial_slot_ids)

            for token in token_invalidated_tokens:
                email = token_to_item[token]["email"]
                failed.append(
                    {"email": email, "failure_stage": "token_invalidated", "message": "OpenAI access token 已失效"}
                )
                removed = _remove_pool_accounts_from_local_and_mail(
                    [email],
                    log_context="gopay-pro",
                    reason="token_invalidated",
                    message="GoPay Pro 检测到 OpenAI token_invalidated，已从号池删除",
                )
                _append_task_progress(
                    task_id,
                    gopay_pro_task_payloads_service.gopay_pro_account_token_invalidated_progress(
                        email=email,
                        failed=len(failed),
                        total=len(token_items),
                        removed=email in removed,
                    ),
                )

            for token in checkout_unauthorized_tokens:
                email = token_to_item[token]["email"]
                failed.append(
                    {
                        "email": email,
                        "failure_stage": "chatgpt_checkout_401",
                        "message": "ChatGPT checkout 401，OpenAI token 无效",
                    }
                )
                removed = _remove_pool_accounts_from_local_and_mail(
                    [email],
                    log_context="gopay-pro",
                    reason="chatgpt_checkout_401",
                    message="GoPay Pro ChatGPT checkout 401，OpenAI token 无效，已从号池删除",
                )
                _append_task_progress(
                    task_id,
                    gopay_pro_task_payloads_service.gopay_pro_account_checkout_unauthorized_progress(
                        email=email,
                        failed=len(failed),
                        total=len(token_items),
                        removed=email in removed,
                    ),
                )

            for token in ambiguous_tokens:
                email = token_to_item[token]["email"]
                failed.append(
                    {
                        "email": email,
                        "failure_stage": "harvest_ambiguous",
                        "message": "token 已被消费，但未匹配到明确成功 slot，未自动回写 Plus",
                    }
                )
                _mark_gopay_pro_failed_account(
                    email,
                    task_id=task_id,
                    status="failed",
                    failure_stage="harvest_ambiguous",
                    message="GoPay Pro token 已被消费，但未匹配到明确成功 slot，请人工核对是否已开通 Plus",
                )
                _append_task_progress(
                    task_id,
                    gopay_pro_task_payloads_service.gopay_pro_account_ambiguous_progress(
                        email=email,
                        failed=len(failed),
                        total=len(token_items),
                    ),
                )

            for token in retry_tokens:
                email = token_to_item[token]["email"]
                if attempts[token] < max_attempts:
                    pending.append(token)
                    if email not in retried:
                        retried.append(email)
                    _append_task_progress(
                        task_id,
                        gopay_pro_task_payloads_service.gopay_pro_account_requeued_progress(
                            email=email,
                            attempt=attempts[token],
                            max_attempts=max_attempts,
                        ),
                    )
                else:
                    failed.append(
                        {"email": email, "failure_stage": "max_attempts", "message": "达到最大重试次数仍未完成"}
                    )
                    _mark_gopay_pro_failed_account(
                        email,
                        task_id=task_id,
                        status="failed",
                        failure_stage="max_attempts",
                        message="GoPay Pro 达到最大重试次数仍未完成",
                    )
                    _append_task_progress(
                        task_id,
                        gopay_pro_task_payloads_service.gopay_pro_account_failed_progress(
                            email=email,
                            failed=len(failed),
                            total=len(token_items),
                        ),
                    )

            _append_task_progress(
                task_id,
                gopay_pro_task_payloads_service.gopay_pro_round_completed_progress(
                    round_index=round_index,
                    exit_code=harvest_result["exit_code"],
                    successful=len(successful),
                    failed=len(failed),
                    pending=len(pending),
                    total=len(token_items),
                ),
            )
        status = "cancelled" if cancel_signal.is_cancelled() else ("success" if successful else "failed")
        return gopay_pro_task_payloads_service.gopay_pro_batch_result(
            cancelled=status == "cancelled",
            successful_emails=successful,
            failed_emails=failed,
            pending_count=len(pending),
            total=len(token_items),
            retried_emails=retried,
            concurrency=round_size,
            max_attempts=max_attempts,
        )
    finally:
        _restore_token_file()
        try:
            number_count = len(_active_pool_lines(_read_lines_file(paths["numbers"])))
            _set_gopay_pro_runtime_slots(paths, number_count or configured_slots)
        except Exception:
            logger.debug("[gopay-pro] failed to restore configured slot count", exc_info=True)


def _run_gopay_pro_script_task(task_id: str, kind: str):
    from autotoken.core import cancel_signal

    script_result = _run_gopay_pro_script(kind, task_id)
    exit_code = int(script_result.get("exit_code") or 0)
    script = str(script_result.get("script") or kind)
    log_tail = str(script_result.get("log_tail") or "")
    if cancel_signal.is_cancelled():
        return gopay_pro_task_payloads_service.gopay_pro_script_cancelled_result(
            kind=kind,
            script=script,
            exit_code=exit_code,
            log_tail=log_tail,
        )
    result = {
        "status": "completed" if exit_code == 0 else "failed",
        "kind": kind,
        "script": script,
        "exit_code": exit_code,
        "log_tail": log_tail,
    }
    if exit_code != 0:
        raise TaskResultError(f"{script} 退出码 {exit_code}", task_result=result)
    return result


_gopay_pro_tasks_router = create_gopay_pro_tasks_router(
    task_kinds=_GOPAY_PRO_TASK_KINDS,
    start_task=_start_task,
    run_script_task=_run_gopay_pro_script_task,
    run_batch_task=_run_gopay_pro_batch_task,
    account_token_items=_gopay_pro_account_token_items,
)
app.include_router(_gopay_pro_tasks_router)
_gopay_pro_task_endpoints = {route.endpoint.__name__: route.endpoint for route in _gopay_pro_tasks_router.routes}
start_gopay_pro_task = _gopay_pro_task_endpoints["start_gopay_pro_task"]
start_gopay_pro_batch = _gopay_pro_task_endpoints["start_gopay_pro_batch"]


def _convert_account_auth_session_to_cpa_auth(
    email: str,
    *,
    account: dict | None = None,
    force_account_type: str | None = None,
) -> dict:
    return account_cpa_auth_service.convert_account_auth_session_to_cpa_auth(
        email,
        account=account,
        force_account_type=force_account_type,
        normalize_email=_normalized_email,
        sanitize_account=_sanitize_account,
    )


def _update_account_cpa_auth_plan_type(email: str, *, account: dict | None = None, plan_type: str = "plus") -> dict:
    return account_cpa_auth_service.update_account_cpa_auth_plan_type(
        email,
        account=account,
        plan_type=plan_type,
        normalize_email=_normalized_email,
    )


app.include_router(
    create_account_cpa_auths_router(
        normalize_email=_normalized_email,
        resolve_codex_auth_file=_resolve_codex_auth_file,
        update_account_cpa_auth_plan_type=_update_account_cpa_auth_plan_type,
        convert_account_auth_session_to_cpa_auth=_convert_account_auth_session_to_cpa_auth,
        is_main_account_email=_is_main_account_email,
        verify_plus_plan=_gopay_pro_verify_plus_plan,
        normalize_observed_auth_plan=_gopay_pro_normalize_observed_auth_plan,
        mark_failed_account=_mark_gopay_pro_failed_account,
        safe_email_summary=_safe_email_summary,
        current_time=time.time,
    )
)
app.include_router(create_finished_account_import_router())


def _run_account_codex_login_once(
    email: str,
    acc: dict,
    *,
    headless: bool = False,
    refresh_auth_session: bool = False,
    proxy_url: str | None = None,
    proxy_bypass: str | None = None,
    protocol_only: bool = False,
    bind_email: bool = False,
    bind_phone: bool = False,
    mail_provider: str | None = None,
    luckmail_email_type: str | None = None,
    luckmail_preferred_domain: str | None = None,
    email_domain: str | None = None,
    oauth_phone_sms_provider: str | None = None,
    oauth_phone_sms_country: str | None = None,
    oauth_phone_sms_max_price: str | None = None,
    oauth_oasis_sms_cdks: str | None = None,
    progress_callback: Callable[[dict], Any] | None = None,
) -> dict:
    from autotoken.auth.codex_auth import (
        CodexOAuthAccountDeactivated,
        CodexOAuthPhoneRequired,
        CodexProtocolOAuthError,
        _extract_account_id_from_auth_session,
        _normalize_auth_session_payload,
        check_codex_quota,
        login_codex_via_auth_session_protocol,
        login_codex_via_browser,
        quota_result_quota_info,
        quota_result_resets_at,
        save_auth_file,
    )
    from autotoken.mail import TemporaryEmailClient
    from autotoken.storage.accounts import (
        ACCOUNT_TYPE_FREE,
        ACCOUNT_TYPE_PLUS,
        ACCOUNT_TYPE_PRO,
        ACCOUNT_TYPE_TEAM,
        STATUS_ACTIVE,
        STATUS_PERSONAL,
        STATUS_PLUS,
        replace_account_email,
        update_account,
    )
    from autotoken.storage.auth_session_store import delete_auth_session, load_auth_session, save_auth_session

    try:
        from autotoken.integrations.account_hub import _restore_luckmail_tokens_for_accounts

        if _restore_luckmail_tokens_for_accounts([acc]):
            update_account(
                email,
                cloudmail_account_id=acc.get("cloudmail_account_id"),
                mail_provider=acc.get("mail_provider") or "luckmail",
            )
            logger.info("[账号登录] 已自动恢复 LuckMail token: %s", email)
    except Exception as exc:
        logger.warning("[账号登录] 自动恢复 LuckMail token 失败，将继续尝试现有邮箱配置: %s error=%s", email, exc)

    # 账号类型决定登录模式：
    # - Team 走旧 Team workspace OAuth；
    # - Free/Plus/Pro 走原生 Codex OAuth，避免被强行注入 Team _account。
    account_type = (acc.get("account_type") or ACCOUNT_TYPE_FREE).lower()
    use_personal = acc.get("status") == STATUS_PERSONAL or account_type == ACCOUNT_TYPE_FREE
    native_oauth = acc.get("status") == STATUS_PERSONAL or account_type in {
        ACCOUNT_TYPE_FREE,
        ACCOUNT_TYPE_PLUS,
        ACCOUNT_TYPE_PRO,
    }

    requested_mail_provider = str(mail_provider or "").strip().lower()
    effective_mail_provider = requested_mail_provider or str(acc.get("mail_provider") or "").strip().lower()
    if not effective_mail_provider and str(acc.get("cloudmail_account_id") or "").strip().startswith("tok_"):
        effective_mail_provider = "luckmail"
    mail_provider_overrides = {}
    if effective_mail_provider == "luckmail":
        if luckmail_email_type:
            mail_provider_overrides["LUCKMAIL_EMAIL_TYPE"] = str(luckmail_email_type).strip()
        if luckmail_preferred_domain is not None:
            mail_provider_overrides["LUCKMAIL_PREFERRED_DOMAIN"] = str(luckmail_preferred_domain).strip().lstrip("@")
    if effective_mail_provider or mail_provider_overrides:
        from autotoken.interfaces.manager import _temporary_mail_provider

        with _temporary_mail_provider(effective_mail_provider, mail_provider_overrides):
            mail_client = TemporaryEmailClient()
    else:
        mail_client = TemporaryEmailClient()
    mail_client.login()
    if not acc.get("cloudmail_account_id") and hasattr(mail_client, "_resolve_account_id"):
        try:
            resolved_mail_id = mail_client._resolve_account_id(email)
        except Exception:
            resolved_mail_id = None
        if resolved_mail_id:
            acc["cloudmail_account_id"] = resolved_mail_id
            update_account(email, cloudmail_account_id=resolved_mail_id)
    bundle = None
    auth_session_data = load_auth_session(email)
    oauth_proxy_url = str(proxy_url or "").strip()
    oauth_proxy_bypass = str(proxy_bypass or "").strip() or None
    phone_only_target = "@" not in str(email or "")
    session_payload: dict | None = None

    if protocol_only:
        try:
            if phone_only_target:
                if not auth_session_data:
                    raise RuntimeError(f"手机号账号缺少 auth_session，无法协议补登录/绑邮箱: {email}")
                if not bind_email:
                    raise RuntimeError(f"手机号账号补登录必须启用邮箱绑定: {email}")

                bind_account_id = None
                bind_email_value = ""

                def _create_bind_mailbox():
                    nonlocal bind_account_id, bind_email_value
                    bind_account_id, bind_email_value = mail_client.create_temp_email(
                        prefix="oauth",
                        domain=str(email_domain or "").strip().lstrip("@") or None,
                    )
                    return bind_account_id, bind_email_value

                from autotoken.auth.protocol_register import oauth_from_auth_session_once

                session_payload = oauth_from_auth_session_once(
                    mail_client,
                    session_data=auth_session_data,
                    email=email,
                    password=acc.get("password", ""),
                    account_id=acc.get("cloudmail_account_id"),
                    mailbox_factory=_create_bind_mailbox,
                    proxy=oauth_proxy_url or None,
                    oauth_phone_sms_provider=oauth_phone_sms_provider,
                    oauth_phone_sms_country=oauth_phone_sms_country,
                    oauth_phone_sms_max_price=oauth_phone_sms_max_price,
                    oauth_oasis_sms_cdks=oauth_oasis_sms_cdks,
                    progress_callback=progress_callback,
                )
                if session_payload.get("mailbox_account_id"):
                    acc["cloudmail_account_id"] = session_payload.get("mailbox_account_id")
                if effective_mail_provider:
                    acc["mail_provider"] = effective_mail_provider
            else:
                from autotoken.auth.protocol_register import login_once as protocol_login_once

                session_payload = protocol_login_once(
                    mail_client,
                    email=email,
                    password=acc.get("password", ""),
                    account_id=acc.get("cloudmail_account_id"),
                    proxy=oauth_proxy_url or None,
                    oauth_phone_sms_provider=oauth_phone_sms_provider,
                    oauth_phone_sms_country=oauth_phone_sms_country,
                    oauth_phone_sms_max_price=oauth_phone_sms_max_price,
                    oauth_oasis_sms_cdks=oauth_oasis_sms_cdks,
                    progress_callback=progress_callback,
                )
            bundle = (session_payload or {}).get("codex_oauth_bundle")
            if not isinstance(bundle, dict):
                raise RuntimeError(f"协议补登录未返回 Codex OAuth bundle: {email}")
        except (CodexOAuthPhoneRequired, CodexOAuthAccountDeactivated):
            raise
        except Exception:
            logger.exception("[账号登录] 协议补登录失败: %s", email)
            raise

    use_protocol_oauth = (
        (not refresh_auth_session)
        and (not protocol_only)
        and not oauth_proxy_url
        and str(os.environ.get("CODEX_OAUTH_USE_AUTH_SESSION_PROTOCOL") or "").strip().lower()
        in {
            "1",
            "true",
            "yes",
            "on",
        }
    )
    if oauth_proxy_url:
        logger.info("[账号登录] OAuth 浏览器将使用代理: %s", email)
    if auth_session_data and use_protocol_oauth:
        try:
            logger.info("[账号登录] 优先复用 auth_session 协议 OAuth: %s", email)
            oauth_result = login_codex_via_auth_session_protocol(
                email,
                auth_session_data,
                native_oauth=True,
                auth_file_callback=lambda raw_bundle: "",
            )
            bundle = (oauth_result or {}).get("bundle")
            protocol_plan = (bundle or {}).get("plan_type", "")
            if bundle and use_personal and str(protocol_plan).lower() not in {"free", "plus", "pro"}:
                logger.warning(
                    "[账号登录] auth_session 协议 OAuth 返回非个人 plan=%s，回退浏览器 OAuth: %s",
                    protocol_plan or "unknown",
                    email,
                )
                bundle = None
        except CodexOAuthPhoneRequired as exc:
            try:
                from autotoken.auth.oauth_phone_pool import list_phones

                has_phone_pool = any(item.get("status") == "available" for item in list_phones())
            except Exception:
                has_phone_pool = False
            if not has_phone_pool:
                raise
            logger.info(
                "[账号登录] auth_session 协议 OAuth 命中 add-phone，改用浏览器流程绑定手机号: %s detail=%s", email, exc
            )
            bundle = None
        except CodexOAuthAccountDeactivated:
            raise
        except CodexProtocolOAuthError as exc:
            logger.warning("[账号登录] auth_session 协议 OAuth 未完成，回退浏览器 OAuth: %s", exc)
            if "登录页" in str(exc) or "log-in" in str(getattr(exc, "final_url", "")).lower():
                logger.info("[账号登录] 协议 OAuth 落到登录页，将尝试浏览器兜底: %s", email)
        except Exception as exc:
            logger.warning("[账号登录] auth_session 协议 OAuth 异常，回退浏览器 OAuth: %s", exc)
    elif auth_session_data:
        logger.info("[账号登录] 跳过 auth_session 协议 OAuth，直接走浏览器邮箱验证码流程: %s", email)

    auth_session_refresh_outcome = {}

    def _capture_refreshed_auth_session(page, context):
        if not refresh_auth_session:
            return
        from autotoken.interfaces.manager import _fetch_auth_session_from_page, _save_auth_from_session_page

        session_data = _fetch_auth_session_from_page(page, context, max_attempts=4, retry_delay_seconds=3.0)
        auth_session_result = _save_auth_from_session_page(
            email,
            acc.get("password", ""),
            acc.get("cloudmail_account_id"),
            session_data,
            out_outcome=auth_session_refresh_outcome,
        )
        auth_session_file = ""
        if isinstance(auth_session_result, dict):
            auth_session_file = str(auth_session_result.get("auth_file") or "")
        auth_session_file = auth_session_file or str(auth_session_refresh_outcome.get("auth_file") or "")
        if auth_session_file:
            auth_session_refresh_outcome["auth_session_file"] = auth_session_file

    if not bundle:
        browser_login_kwargs = {
            "mail_client": mail_client,
            "use_personal": use_personal,
            "native_oauth": native_oauth,
            "headless": headless,
            "mail_account_id": acc.get("cloudmail_account_id"),
        }
        if oauth_proxy_url:
            browser_login_kwargs["proxy_url"] = oauth_proxy_url
            if oauth_proxy_bypass:
                browser_login_kwargs["proxy_bypass"] = oauth_proxy_bypass
        if refresh_auth_session:
            browser_login_kwargs["auth_session_callback"] = _capture_refreshed_auth_session
        bundle = login_codex_via_browser(
            email,
            acc.get("password", ""),
            **browser_login_kwargs,
        )
    if not bundle:
        raise RuntimeError(f"Codex 登录失败: {email}")
    if refresh_auth_session and auth_session_refresh_outcome.get("status") != "success":
        raise RuntimeError(auth_session_refresh_outcome.get("reason") or f"刷新 auth_session 失败: {email}")

    session_account_id = ""
    for source in (session_payload, auth_session_data):
        candidate = _extract_account_id_from_auth_session(_normalize_auth_session_payload(source or {}))
        if candidate:
            session_account_id = candidate
            break
    from autotoken.services.registration import account_codex_oauth_bundle

    bundle = account_codex_oauth_bundle(
        bundle,
        account_type=account_type,
        account_id=session_account_id,
    )
    auth_file = save_auth_file(bundle)
    plan_type = (bundle.get("plan_type") or "").lower()
    next_account_type = {
        "free": ACCOUNT_TYPE_FREE,
        "team": ACCOUNT_TYPE_TEAM,
        "plus": ACCOUNT_TYPE_PLUS,
        "pro": ACCOUNT_TYPE_PRO,
    }.get(plan_type, account_type)
    if account_type in {ACCOUNT_TYPE_PLUS, ACCOUNT_TYPE_PRO} and next_account_type == ACCOUNT_TYPE_FREE:
        next_account_type = account_type

    actual_email = _normalized_email((bundle or {}).get("email") or (session_payload or {}).get("email") or email)
    target_email = email
    current_status = str(acc.get("status") or "").strip().lower()
    current_bind_provider = str(acc.get("last_bind_provider") or "").strip().lower()
    if (
        next_account_type == ACCOUNT_TYPE_PLUS
        and current_status == STATUS_ACTIVE
        and current_bind_provider in {"paypal", "paypal_ice"}
    ):
        next_status = STATUS_ACTIVE
    else:
        next_status = STATUS_PLUS if next_account_type == ACCOUNT_TYPE_PLUS else STATUS_ACTIVE
    update_fields = {
        "status": next_status,
        "account_type": next_account_type,
        "auth_file": auth_file,
        "last_active_at": time.time(),
    }
    if acc.get("cloudmail_account_id"):
        update_fields["cloudmail_account_id"] = acc.get("cloudmail_account_id")
    if effective_mail_provider:
        update_fields["mail_provider"] = effective_mail_provider
    if protocol_only and session_payload:
        if actual_email:
            try:
                save_auth_session(actual_email, session_payload)
            except Exception as exc:
                logger.warning("[账号登录] 保存协议 auth_session 失败: %s error=%s", actual_email, exc)
    if phone_only_target and actual_email and "@" in actual_email and actual_email != email:
        replace_account_email(email, actual_email, **update_fields)
        try:
            delete_auth_session(email)
        except Exception as exc:
            logger.warning("[账号登录] 清理手机号旧 auth_session 失败: %s error=%s", email, exc)
        target_email = actual_email
        logger.info("[账号登录] 手机号账号已绑定邮箱并迁移: %s -> %s", email, actual_email)
    else:
        update_account(email, **update_fields)

    token = bundle.get("access_token")
    account_id = bundle.get("account_id")
    if token and account_id:
        st, info = check_codex_quota(token, account_id=account_id)
        if st == "ok" and isinstance(info, dict):
            update_account(target_email, last_quota=info)
        elif st == "exhausted":
            quota_info = quota_result_quota_info(info)
            if quota_info:
                update_account(target_email, last_quota=quota_info)
            update_account(
                target_email,
                status="exhausted",
                quota_exhausted_at=time.time(),
                quota_resets_at=quota_result_resets_at(info) or int(time.time() + 18000),
            )

    logger.info("[账号登录] 自动 CPA 同步已禁用，需要时请手动执行“同步 CPA”")
    result_payload = {
        "email": target_email,
        "plan": bundle.get("plan_type"),
        "auth_file": auth_file,
        "mode": "native" if native_oauth else "team",
    }
    if target_email != email:
        result_payload["previous_email"] = email
    if refresh_auth_session and auth_session_refresh_outcome.get("auth_session_file"):
        result_payload["auth_session_file"] = auth_session_refresh_outcome.get("auth_session_file")
    return result_payload


def _oauth_phone_required_result(email: str, exc: Exception) -> dict:
    return account_oauth_results_service.oauth_phone_required_result(email, exc)


def _oauth_phone_rate_limited_result(email: str, exc: Exception) -> dict:
    return account_oauth_results_service.oauth_phone_rate_limited_result(email, exc)


def _oauth_login_required_result(email: str, exc: Exception) -> dict:
    return account_oauth_results_service.oauth_login_required_result(email, exc)


def _oauth_account_deactivated_result(email: str, exc: Exception) -> dict:
    return account_oauth_results_service.oauth_account_deactivated_result(
        email,
        exc,
        remove_account_from_pool=_remove_oauth_account_deactivated_accounts_from_pool,
    )


_account_login_router = create_account_login_router(
    start_task=lambda *args, **kwargs: _start_task(*args, **kwargs),
    normalize_email=_normalized_email,
    is_main_account_email=lambda email: _is_main_account_email(email),
    build_oauth_proxy_selector=lambda **kwargs: _build_oauth_proxy_selector(**kwargs),
    run_account_codex_login_once=lambda *args, **kwargs: _run_account_codex_login_once(*args, **kwargs),
    append_task_progress=lambda task_id, progress: _append_task_progress(task_id, progress),
    oauth_phone_required_result=_oauth_phone_required_result,
    oauth_phone_rate_limited_result=_oauth_phone_rate_limited_result,
    oauth_login_required_result=_oauth_login_required_result,
    oauth_account_deactivated_result=lambda email, exc: _oauth_account_deactivated_result(email, exc),
    task_result_error=TaskResultError,
    logger=logger,
)
app.include_router(_account_login_router)
_account_login_endpoints = {route.endpoint.__name__: route.endpoint for route in _account_login_router.routes}
post_account_login = _account_login_endpoints["post_account_login"]
post_accounts_login_batch = _account_login_endpoints["post_accounts_login_batch"]


_account_refresh_quota_router = create_account_refresh_quota_router(
    start_task=lambda *args, **kwargs: _start_task(*args, **kwargs),
    normalize_email=_normalized_email,
    is_main_account_email=lambda email: _is_main_account_email(email),
    resolve_status_auth_file=lambda account: _resolve_status_auth_file(account),
    account_id_from_auth_data=lambda auth_data: _account_id_from_auth_data(auth_data),
    append_task_progress=lambda task_id, progress: _append_task_progress(task_id, progress),
    task_group_quota=TASK_GROUP_QUOTA,
    logger=logger,
)
app.include_router(_account_refresh_quota_router)
_account_refresh_quota_endpoints = {
    route.endpoint.__name__: route.endpoint for route in _account_refresh_quota_router.routes
}
post_accounts_refresh_quota = _account_refresh_quota_endpoints["post_accounts_refresh_quota"]


app.include_router(
    create_status_router(
        load_accounts_with_session_stubs=_load_accounts_with_session_stubs,
        sanitize_accounts_batch=_sanitize_accounts_batch,
        playwright_lock=_playwright_lock,
        playwright_executor=_pw_executor,
        current_busy_detail=_current_busy_detail,
    )
)


app.include_router(
    create_team_members_router(
        playwright_lock=_playwright_lock,
        playwright_executor=_pw_executor,
        current_busy_detail=_current_busy_detail,
        is_main_account_email=_is_main_account_email,
    )
)


app.include_router(
    create_bind_link_router(
        normalize_access_token=_normalize_access_token,
        generate_checkout_link=_generate_checkout_link,
        get_account_access_token=_extract_account_access_token,
        open_checkout_url=_open_bind_checkout_with_auth_session,
        logger=logger,
    )
)


app.include_router(create_oauth_phone_pool_router())


# ---------------------------------------------------------------------------
# 日志收集
# ---------------------------------------------------------------------------

_log_buffer: list[dict] = []
_LOG_BUFFER_MAX = 5000


class _LogCollector(logging.Handler):
    """收集日志到内存 buffer，供前端查询"""

    def emit(self, record):
        entry = {
            "time": record.created,
            "level": record.levelname,
            "message": self.format(record),
        }
        _log_buffer.append(entry)
        if len(_log_buffer) > _LOG_BUFFER_MAX:
            del _log_buffer[: len(_log_buffer) - _LOG_BUFFER_MAX]


_log_collector = _LogCollector()
_log_collector.setFormatter(logging.Formatter("%(message)s"))
logging.getLogger().addHandler(_log_collector)


app.include_router(create_support_router(log_buffer=_log_buffer, start_main_codex_sync=post_main_codex_start))


app.include_router(create_cpa_to_sub2api_router())


# ---------------------------------------------------------------------------
# 后台任务端点
# ---------------------------------------------------------------------------


_bind_card_task_router = create_bind_card_task_router(
    start_task=lambda *args, **kwargs: _start_task(*args, **kwargs),
    normalize_email=_normalized_email,
    resolve_status_auth_file=lambda account: _resolve_status_auth_file(account),
    session_only_account_stub=_session_only_account_stub,
    is_bind_card_reusable_result=_is_bind_card_reusable_result,
    current_task_id_for_group=lambda: _current_task_id_for_group(),
    append_task_progress=lambda task_id, progress: _append_task_progress(task_id, progress),
    task_result_error=TaskResultError,
    task_group_bind_card=TASK_GROUP_BIND_CARD,
    logger=logger,
)
app.include_router(_bind_card_task_router)
_bind_card_task_endpoints = {route.endpoint.__name__: route.endpoint for route in _bind_card_task_router.routes}
post_bind_card_task = _bind_card_task_endpoints["post_bind_card_task"]


@app.post("/api/tasks/gopay-bind", status_code=202)
def post_gopay_bind_task(params: GoPayBindTaskParams, request: Request = None):
    from autotoken.core import cancel_signal
    from autotoken.payments.bind_audit import record_bind_audit
    from autotoken.payments.gopay_executor import run_gopay_bind_task
    from autotoken.settings.config import normalize_proxy_url
    from autotoken.storage.accounts import (
        ACCOUNT_SOURCE_MANAGED,
        ACCOUNT_TYPE_FREE,
        ACCOUNT_TYPE_PLUS,
        SEAT_CODEX,
        STATUS_ACTIVE,
        STATUS_FAIL,
        STATUS_PERSONAL,
        add_account,
        ensure_session_only_account,
        find_account,
        load_accounts,
        update_account,
    )
    from autotoken.storage.auth_session_store import get_auth_session_file

    email = _normalized_email(params.email)
    gopay_task_public_base_url = _request_public_base_url(request)
    auto_register = bool(params.auto_register)
    gopay_auto_signup = bool(params.gopay_auto_signup)
    gopay_auto_signup_env_config = _gopay_auto_signup_env()
    gopay_auto_signup_sms_provider = _normalize_gopay_auto_signup_sms_provider(
        params.gopay_auto_signup_sms_provider or gopay_auto_signup_env_config.get("provider") or "smscloud"
    )
    gopay_auto_signup_hero_sms_config = {
        "api_key": str(params.gopay_auto_signup_hero_sms_api_key or "").strip(),
        "base_url": str(params.gopay_auto_signup_hero_sms_base_url or "").strip(),
        "country": str(params.gopay_auto_signup_hero_sms_country or "").strip(),
        "service": str(params.gopay_auto_signup_hero_sms_service or "").strip(),
        "timeout_sec": str(params.gopay_auto_signup_hero_sms_timeout or "").strip(),
        "min_price": str(params.gopay_auto_signup_hero_sms_min_price or "").strip(),
        "max_price": str(params.gopay_auto_signup_hero_sms_max_price or "").strip(),
        "preferred_price": str(params.gopay_auto_signup_hero_sms_preferred_price or "").strip(),
    }
    gopay_auto_signup_smscloud_config = {
        "base_url": str(params.gopay_auto_signup_smscloud_base_url or "").strip(),
        "country": str(params.gopay_auto_signup_smscloud_country or "").strip(),
        "service": str(params.gopay_auto_signup_smscloud_service or "").strip(),
        "max_price": str(params.gopay_auto_signup_smscloud_max_price or "").strip(),
        "timeout_sec": str(params.gopay_auto_signup_smscloud_timeout or "").strip(),
    }
    gopay_auto_signup_smsbower_config = {
        "api_key": str(params.gopay_auto_signup_smsbower_api_key or "").strip(),
        "base_url": str(params.gopay_auto_signup_smsbower_base_url or "").strip(),
        "country": str(params.gopay_auto_signup_smsbower_country or "").strip(),
        "service": str(params.gopay_auto_signup_smsbower_service or "").strip(),
        "timeout_sec": str(params.gopay_auto_signup_smsbower_timeout or "").strip(),
        "min_price": str(params.gopay_auto_signup_smsbower_min_price or "").strip(),
        "max_price": str(params.gopay_auto_signup_smsbower_max_price or "").strip(),
        "preferred_price": str(params.gopay_auto_signup_smsbower_preferred_price or "").strip(),
    }
    gopay_auto_signup_smscode_config = {
        "api_token": str(params.gopay_auto_signup_smscode_api_token or "").strip(),
        "base_url": str(params.gopay_auto_signup_smscode_base_url or "").strip(),
        "country_id": str(params.gopay_auto_signup_smscode_country_id or "").strip(),
        "platform_id": str(params.gopay_auto_signup_smscode_platform_id or "").strip(),
        "platform_query": str(params.gopay_auto_signup_smscode_platform_query or "").strip(),
        "product_id": str(params.gopay_auto_signup_smscode_product_id or "").strip(),
        "min_price": str(params.gopay_auto_signup_smscode_min_price or "").strip(),
        "max_price": str(params.gopay_auto_signup_smscode_max_price or "").strip(),
        "timeout_sec": str(params.gopay_auto_signup_smscode_timeout or "").strip(),
    }
    requested_signup_mode = _normalize_gopay_auto_signup_mode(
        getattr(params, "gopay_auto_signup_mode", "") or gopay_auto_signup_env_config.get("signup_mode") or "http"
    )
    gopay_auto_signup_appium_config = {
        "signup_mode": requested_signup_mode,
        "appium_url": str(
            getattr(params, "gopay_appium_url", "") or gopay_auto_signup_env_config.get("appium_url") or ""
        ).strip(),
        "adb_serial": str(
            getattr(params, "gopay_appium_adb_serial", "")
            or gopay_auto_signup_env_config.get("appium_adb_serial")
            or ""
        ).strip(),
    }
    try:
        auto_register_count = max(1, min(100, int(params.auto_register_count or 1)))
    except Exception:
        auto_register_count = 1
    if not auto_register:
        auto_register_count = 1
    try:
        pending_retry_attempts = max(
            0, min(3, int(params.pending_retry_attempts if params.pending_retry_attempts is not None else 1))
        )
    except Exception:
        pending_retry_attempts = 1
    try:
        requested_gopay_concurrency = max(1, min(10, int(params.gopay_concurrency or 1)))
    except Exception:
        requested_gopay_concurrency = 1
    gopay_concurrency = requested_gopay_concurrency
    gopay_balance_wait_fallback_transfer = bool(params.gopay_balance_wait_fallback_transfer)
    account_emails = []
    seen_account_emails = set()
    for raw_email in params.account_emails or []:
        normalized = _normalized_email(raw_email)
        if normalized and normalized not in seen_account_emails:
            seen_account_emails.add(normalized)
            account_emails.append(normalized)
    phone_number = str(params.phone_number or "").strip()
    country_code = str(params.country_code or "").strip()
    sms_url = str(params.sms_url or "").strip()
    gopay_pin = str(params.gopay_pin or "").strip()
    if gopay_auto_signup and requested_signup_mode == "appium":
        if not gopay_pin:
            raise HTTPException(status_code=400, detail="Appium 自动注册要求填写 gopay_pin")
        if not re.fullmatch(r"\d{6}", gopay_pin):
            raise HTTPException(status_code=400, detail="Appium 自动注册要求 gopay_pin 为 6 位数字")
        if not gopay_auto_signup_appium_config["appium_url"]:
            raise HTTPException(status_code=400, detail="Appium 自动注册缺少 gopay_appium_url")
    otp_channel = str(params.otp_channel or "sms").strip().lower()
    if otp_channel not in {"sms", "whatsapp"}:
        raise HTTPException(status_code=400, detail="otp_channel 只支持 sms 或 whatsapp")

    class _GoPayWalletSignupRateLimited(RuntimeError):
        pass

    class _GoPayWalletSignupNetworkError(RuntimeError):
        pass

    class _GoPayWalletSignupNoNumbers(RuntimeError):
        pass

    def _looks_like_gopay_wallet_signup_rate_limited(exc: Exception | str) -> bool:
        text = _compact_log_text(exc, limit=400)
        normalized = str(text or "").strip().lower()
        if not normalized:
            return False
        if any(
            marker in normalized
            for marker in (
                "scp-cvs:error:ratelimit:init_verification",
                "ratelimit:init_verification",
                "rate_limited",
                "rate limited",
            )
        ):
            return True
        return _looks_like_gopay_rate_limit_text(normalized)

    def _looks_like_gopay_wallet_signup_network_error(exc: Exception | str) -> bool:
        normalized = str(_compact_log_text(exc, limit=400) or "").strip().lower()
        if not normalized or _looks_like_gopay_wallet_signup_rate_limited(normalized):
            return False
        return any(
            marker in normalized
            for marker in (
                "recv failure",
                "connection was reset",
                "connection reset",
                "could not resolve host",
                "operation timed out",
                "timed out",
                "connection timed out",
                "connection refused",
                "connection aborted",
                "network is unreachable",
                "remote disconnected",
                "waf block page",
                "domain-config-1256704386",
                "cos.accelerate.myqcloud",
                "<title>waf block page</title>",
                "blocked by waf",
                "curl: (6)",
                "curl: (7)",
                "curl: (28)",
                "curl: (35)",
                "curl: (56)",
            )
        )

    def _looks_like_gopay_wallet_signup_no_numbers(exc: Exception | str) -> bool:
        normalized = str(_compact_log_text(exc, limit=500) or "").strip().lower()
        if not normalized:
            return False
        return any(
            marker in normalized
            for marker in (
                "no_numbers",
                "no numbers",
                "smscode 当前价格区间内没有可用号码",
                "herosms 当前价格区间内没有可用号码",
                "hero-sms 取号失败: no_numbers",
                "smscode 取号失败",
            )
        )

    def _looks_like_gopay_wallet_signup_provider_error(exc: Exception | str) -> bool:
        normalized = str(_compact_log_text(exc, limit=500) or "").strip().lower()
        if not normalized:
            return False
        if _looks_like_gopay_wallet_signup_no_numbers(normalized):
            return False
        return any(
            marker in normalized
            for marker in (
                "xi_token",
                "登录凭证无效",
                "缺少 gopay_auto_signup",
                "缺少 gopay_auto_signup_smscloud",
                "缺少 gopay_auto_signup_hero",
                "缺少 gopay_auto_signup_smscode",
                "缺少 gopay_auto_signup_smsbower",
                "smsbower api key",
                "no access",
                "smscode",
                "bad_key",
                "bad service",
                "no_balance",
            )
        )

    phone_accounts: list[dict] = []
    seen_phone_accounts: set[tuple[str, str, str]] = set()
    for raw_phone_account in params.phone_accounts or []:
        account_country_code = str(raw_phone_account.country_code or country_code or "").strip()
        account_phone_number = str(raw_phone_account.phone_number or "").strip()
        account_sms_url = str(raw_phone_account.sms_url or "").strip()
        account_gopay_pin = str(raw_phone_account.gopay_pin or "").strip()
        account_otp_channel = str(raw_phone_account.otp_channel or otp_channel or "sms").strip().lower()
        if account_otp_channel not in {"sms", "whatsapp"}:
            raise HTTPException(status_code=400, detail="phone_accounts otp_channel 只支持 sms 或 whatsapp")
        if not account_phone_number and not account_sms_url and not account_gopay_pin:
            continue
        if account_otp_channel == "whatsapp":
            account_sms_url = _default_whatsapp_otp_url()
        if not account_phone_number or not account_sms_url or not account_gopay_pin:
            raise HTTPException(
                status_code=400, detail="phone_accounts 每项都必须填写 phone_number、sms_url、gopay_pin"
            )
        phone_key = (account_country_code, account_phone_number, account_sms_url)
        if phone_key in seen_phone_accounts:
            continue
        seen_phone_accounts.add(phone_key)
        phone_accounts.append(
            {
                "country_code": account_country_code,
                "phone_number": account_phone_number,
                "sms_url": account_sms_url,
                "gopay_pin": account_gopay_pin,
                "otp_channel": account_otp_channel,
            }
        )
    if otp_channel == "whatsapp":
        sms_url = _default_whatsapp_otp_url()
    if not gopay_auto_signup and not phone_accounts and (phone_number or sms_url or gopay_pin):
        phone_accounts.append(
            {
                "country_code": country_code,
                "phone_number": phone_number,
                "sms_url": sms_url,
                "gopay_pin": gopay_pin,
                "otp_channel": otp_channel,
            }
        )
    if phone_accounts:
        primary_phone_account = phone_accounts[0]
        phone_number = str(primary_phone_account.get("phone_number") or "").strip()
        country_code = str(primary_phone_account.get("country_code") or "").strip()
        sms_url = str(primary_phone_account.get("sms_url") or "").strip()
        gopay_pin = str(primary_phone_account.get("gopay_pin") or "").strip()
        otp_channel = str(primary_phone_account.get("otp_channel") or otp_channel or "sms").strip().lower()
    logger.info(
        "[API] GoPay OTP config resolved: otp_channel=%s sms_url=%s phone_accounts=%s",
        otp_channel,
        _safe_url_for_log(sms_url) if sms_url else "<empty>",
        [
            {
                "country_code": item.get("country_code") or "",
                "phone_number": _mask_gopay_phone_for_log(item.get("phone_number") or ""),
                "otp_channel": item.get("otp_channel") or otp_channel,
                "sms_url": _safe_url_for_log(item.get("sms_url") or "") if item.get("sms_url") else "<empty>",
            }
            for item in phone_accounts
        ],
    )
    billing_name = str(params.billing_name or "").strip()
    billing_country = str(params.billing_country or "").strip()
    billing_state = str(params.billing_state or "").strip()
    billing_city = str(params.billing_city or "").strip()
    billing_zip = str(params.billing_zip or "").strip()
    billing_address1 = str(params.billing_address1 or "").strip()
    billing_address2 = str(params.billing_address2 or "").strip()
    checkout_url = str(params.checkout_url or "").strip()
    checkout_ui_mode = "hosted" if str(params.checkout_ui_mode or "").strip().lower() == "hosted" else "custom"
    auto_register_prefix = str(params.auto_register_prefix or "").strip()
    auto_register_password = str(params.auto_register_password or "").strip()
    auto_register_mode = "protocol" if bool(params.auto_register_protocol) else "browser"
    from autotoken.settings.setup_wizard import get_mail_provider

    auto_register_mail_provider = (
        get_mail_provider(params.auto_register_mail_provider) if params.auto_register_mail_provider else ""
    )
    auto_register_luckmail_email_type = str(params.auto_register_luckmail_email_type or "").strip()
    auto_register_luckmail_preferred_domain = (
        str(params.auto_register_luckmail_preferred_domain or "").strip().lstrip("@")
    )
    auto_register_luckmail_preferred_domains = []
    seen_luckmail_domains = set()
    for raw_domain in list(params.auto_register_luckmail_preferred_domains or []) + (
        [auto_register_luckmail_preferred_domain] if auto_register_luckmail_preferred_domain else []
    ):
        cleaned = str(raw_domain or "").strip().lstrip("@")
        key = cleaned.lower()
        if key in seen_luckmail_domains:
            continue
        seen_luckmail_domains.add(key)
        auto_register_luckmail_preferred_domains.append(cleaned)
    proxy_url = str(params.proxy_url or gopay_auto_signup_env_config.get("proxy_url") or "").strip()
    proxy_api_url = str(params.proxy_api_url or "").strip()
    proxy_api_provider = _normalize_proxy_api_provider(params.proxy_api_provider) if params.proxy_api_provider else ""
    if proxy_api_provider and not proxy_api_url:
        proxy_api_url = _default_gopay_proxy_api_url(proxy_api_provider, proxy_url)
    proxy_pool = _parse_proxy_pool_values(params.proxy_pool, params.proxy_pool_text)
    static_proxy_pool: list[str] = []
    for raw_proxy_entry in proxy_pool:
        if _is_proxy_api_url(raw_proxy_entry):
            if not proxy_api_url:
                proxy_api_url = raw_proxy_entry
                proxy_api_provider = _normalize_proxy_api_provider(proxy_api_provider or "cliproxy")
            continue
        static_proxy_pool.append(raw_proxy_entry)
    proxy_pool = static_proxy_pool
    try:
        normalized_proxy_url = normalize_proxy_url(proxy_url) if proxy_url else ""
        proxy_config_state = "enabled" if normalized_proxy_url else "disabled"
        proxy_config_error = ""
    except Exception as exc:
        normalized_proxy_url = ""
        proxy_config_state = "invalid"
        proxy_config_error = _compact_log_text(exc, limit=160)
    bind_proxy_url = normalized_proxy_url
    normalized_proxy_pool: list[str] = []
    for raw_pool_proxy in proxy_pool:
        try:
            normalized = normalize_proxy_url(raw_pool_proxy)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"GoPay 动态代理池格式错误: {raw_pool_proxy} ({exc})") from exc
        if normalized and normalized not in normalized_proxy_pool:
            normalized_proxy_pool.append(normalized)
    if proxy_api_url:
        proxy_config_state = "api"
    elif normalized_proxy_pool:
        proxy_config_state = "pool"

    if normalized_proxy_url.lower().startswith(("socks4://", "socks5://", "socks5h://")):
        # SOCKS proxies are only needed for GoPay wallet signup/PIN setup.
        bind_proxy_url = ""

    if auto_register and checkout_url:
        raise HTTPException(status_code=400, detail="自动注册模式不支持手动 checkout 链接")
    if not auto_register and not email:
        raise HTTPException(status_code=400, detail="email 不能为空")
    auto_register_domains: list[str] = []
    if auto_register:
        from autotoken.settings.runtime_config import get_register_domain, get_register_domains

        configured_domains = [str(domain or "").strip().lstrip("@") for domain in get_register_domains()]
        configured_domains = [domain for domain in configured_domains if domain]
        requested_domains = []
        for raw_domain in [params.auto_register_domain, *(params.auto_register_domains or [])]:
            cleaned = str(raw_domain or "").strip().lstrip("@")
            if cleaned and cleaned.lower() not in {d.lower() for d in requested_domains}:
                requested_domains.append(cleaned)
        if requested_domains and configured_domains:
            allowed = {domain.lower() for domain in configured_domains}
            invalid_domains = [domain for domain in requested_domains if domain.lower() not in allowed]
            if invalid_domains:
                raise HTTPException(status_code=400, detail=f"自动注册域名未配置: {', '.join(invalid_domains)}")
        auto_register_domains = requested_domains
        if auto_register_mail_provider not in {"luckmail", "outlook"} and not auto_register_domains:
            default_domain = str(get_register_domain() or "").strip().lstrip("@")
            if default_domain:
                auto_register_domains = [default_domain]
            elif configured_domains:
                auto_register_domains = [configured_domains[0]]
        if auto_register_mail_provider not in {"luckmail", "outlook"} and not auto_register_domains:
            raise HTTPException(status_code=400, detail="未配置可用注册域名")
        account_emails = []
    elif checkout_url:
        account_emails = []
    elif account_emails and email not in account_emails:
        account_emails.insert(0, email)
    if not gopay_auto_signup and not phone_accounts:
        raise HTTPException(status_code=400, detail="phone_number 不能为空")
    if not gopay_auto_signup and not phone_number:
        raise HTTPException(status_code=400, detail="phone_number 不能为空")
    if not gopay_auto_signup and not sms_url:
        raise HTTPException(status_code=400, detail="sms_url 不能为空")
    if not gopay_pin:
        raise HTTPException(status_code=400, detail="gopay_pin 不能为空")
    if checkout_url or auto_register or not account_emails:
        gopay_concurrency = 1
    if not gopay_auto_signup and phone_accounts and gopay_concurrency > len(phone_accounts):
        gopay_concurrency = max(1, len(phone_accounts))
    logger.info(
        "[gopay-bind] task submitted: email=%s auto_register=%s auto_register_count=%s gopay_auto_signup=%s account_count=%s pending_retry_attempts=%s concurrency=%s/%s checkout=%s checkout_mode=%s phone=%s proxy_label=%s proxy_state=%s proxy=%s proxy_error=%s timeout=%s",
        _safe_email_summary(email) if email else "<auto-register>",
        auto_register,
        auto_register_count,
        gopay_auto_signup,
        len(account_emails) if account_emails else 1,
        pending_retry_attempts,
        gopay_concurrency,
        requested_gopay_concurrency,
        _safe_url_summary(checkout_url) if checkout_url else "<auto-generate>",
        checkout_ui_mode,
        (
            "GoPay 自动注册"
            if gopay_auto_signup
            else (
                f"{_safe_phone_summary(phone_number, country_code)} (+{max(0, len(phone_accounts) - 1)} backup)"
                if len(phone_accounts) > 1
                else _safe_phone_summary(phone_number, country_code)
            )
        ),
        params.proxy_label or "<none>",
        proxy_config_state,
        _safe_proxy_summary(normalized_proxy_url or proxy_url),
        proxy_config_error or "<none>",
        max(120, int(params.timeout_seconds or 900)),
    )

    if not auto_register:
        accounts = load_accounts()
        account = find_account(accounts, email)
        if not account:
            auth_session_file = get_auth_session_file(email)
            if auth_session_file and Path(auth_session_file).exists():
                account = ensure_session_only_account(email) or _session_only_account_stub(email)
                accounts = load_accounts()
            else:
                raise HTTPException(status_code=404, detail="账号不存在")
        if not _resolve_status_auth_file(account):
            raise HTTPException(status_code=400, detail="该账号缺少可用 auth_session/auth_file")
        for candidate_email in account_emails:
            if candidate_email == email:
                continue
            candidate = find_account(accounts, candidate_email)
            if not candidate:
                auth_session_file = get_auth_session_file(candidate_email)
                if auth_session_file and Path(auth_session_file).exists():
                    candidate = ensure_session_only_account(candidate_email) or _session_only_account_stub(
                        candidate_email
                    )
                    accounts = load_accounts()
                else:
                    raise HTTPException(status_code=404, detail=f"批量账号不存在: {candidate_email}")
            if not _resolve_status_auth_file(candidate):
                raise HTTPException(
                    status_code=400, detail=f"批量账号缺少可用 auth_session/auth_file: {candidate_email}"
                )

    skip_current_signal = threading.Event()
    submitted_gopay_task_id = ""

    def _run():
        nonlocal email, account_emails
        task_id = _current_task_id_for_group(TASK_GROUP_GOPAY, fallback_task_id=submitted_gopay_task_id) or ""
        _init_gopay_runtime_control(
            task_id,
            gopay_concurrency=gopay_concurrency,
            sms_provider=gopay_auto_signup_sms_provider,
            account_emails=account_emails or ([email] if email else []),
        )
        started_at = time.time()
        gopay_run_id = uuid.uuid4().hex
        result = None
        realtime_successful_emails: set[str] = set()
        oauth_scheduled_emails: set[str] = set()
        oauth_successful_emails: list[str] = []
        oauth_failed_emails: list[dict] = []
        session_cpa_scheduled_emails: set[str] = set()
        session_cpa_converted_emails: list[str] = []
        session_cpa_failed_auths: list[dict] = []
        auth_session_refresh_attempted: set[str] = set()
        active_gopay_wallets = []
        reusable_gopay_wallets = []
        retained_gopay_wallets = []
        funded_gopay_wallet_ids: set[int] = set()
        gopay_wallet_funding_attempted_ids: set[int] = set()
        gopay_wallet_balance_ready_ids: set[int] = set()
        gopay_wallet_created_at: dict[int, float] = {}
        gopay_no_transfer_balance_miss_count = 0
        gopay_no_transfer_balance_fallback_forced = False
        gopay_transfer_1001_balance_count = 0
        gopay_transfer_disabled_for_official_gift = False
        gopay_funded_balance_insufficient_count = 0
        gopay_balance_insufficient_stop_requested = False
        gopay_state_lock = threading.RLock()
        gopay_worker_context = threading.local()
        gopay_balance_insufficient_stop_message = (
            "连续 3 次 Rekberinaja 转账后 GoPay 余额仍不足，已停止任务，不再取新的 SMS 手机号注册"
        )

        def _current_gopay_concurrency() -> int:
            control = _gopay_runtime_control(task_id)
            return _normalize_gopay_runtime_concurrency(control.get("gopay_concurrency"), gopay_concurrency)

        def _current_gopay_auto_signup_sms_provider() -> str:
            control = _gopay_runtime_control(task_id)
            return _normalize_gopay_auto_signup_sms_provider(
                control.get("gopay_auto_signup_sms_provider") or gopay_auto_signup_sms_provider or "smscloud"
            )

        def _current_gopay_balance_poll_interval_seconds() -> float:
            control = _gopay_runtime_control(task_id)
            return _normalize_gopay_runtime_seconds(
                control.get("gopay_balance_poll_interval_seconds"),
                _default_gopay_wallet_balance_poll_interval_seconds(),
                maximum=300.0,
            )

        def _current_gopay_transfer_balance_wait_seconds() -> float:
            control = _gopay_runtime_control(task_id)
            return _normalize_gopay_runtime_seconds(
                control.get("gopay_transfer_balance_wait_seconds"),
                _default_gopay_wallet_balance_wait_seconds(),
                maximum=1800.0,
            )

        def _gopay_wallet_balance_poll_intervals(total_wait_seconds: float | None = None) -> list[float]:
            total_wait = (
                _default_gopay_wallet_balance_wait_seconds() if total_wait_seconds is None else total_wait_seconds
            )
            return _build_gopay_balance_poll_intervals(total_wait, _current_gopay_balance_poll_interval_seconds())

        def _gopay_transfer_balance_poll_intervals() -> list[float]:
            return _gopay_wallet_balance_poll_intervals(_current_gopay_transfer_balance_wait_seconds())

        def _runtime_account_total(default: int = 0) -> int:
            control = _gopay_runtime_control(task_id)
            accounts = control.get("all_account_emails") if isinstance(control, dict) else []
            return max(int(default or 0), len(accounts) if isinstance(accounts, list) else 0)

        def _drain_runtime_added_account_emails(existing_emails: set[str]) -> list[str]:
            return drain_gopay_pending_account_emails(
                _task_runtime_controls,
                _task_runtime_controls_lock,
                task_id,
                existing_emails,
            )

        def _reset_no_transfer_balance_misses() -> None:
            nonlocal gopay_no_transfer_balance_miss_count
            with gopay_state_lock:
                gopay_no_transfer_balance_miss_count = 0

        def _reset_funded_balance_insufficient_count() -> None:
            nonlocal gopay_funded_balance_insufficient_count
            with gopay_state_lock:
                gopay_funded_balance_insufficient_count = 0

        def _transfer_disabled_for_official_gift() -> bool:
            with gopay_state_lock:
                return bool(gopay_transfer_disabled_for_official_gift)

        def _gopay_balance_insufficient_stop_requested() -> bool:
            with gopay_state_lock:
                return bool(gopay_balance_insufficient_stop_requested)

        def _gopay_wallet_funding_attempted(wallet) -> bool:
            if wallet is None:
                return False
            wallet_id = id(wallet)
            with gopay_state_lock:
                return wallet_id in funded_gopay_wallet_ids or wallet_id in gopay_wallet_funding_attempted_ids

        def _record_funded_balance_insufficient(wallet, *, index: int = 1, total: int = 1) -> bool:
            nonlocal gopay_funded_balance_insufficient_count, gopay_balance_insufficient_stop_requested
            with gopay_state_lock:
                gopay_funded_balance_insufficient_count += 1
                insufficient_count = gopay_funded_balance_insufficient_count
                if insufficient_count >= 3 and not gopay_balance_insufficient_stop_requested:
                    gopay_balance_insufficient_stop_requested = True
                    stop_now = True
                else:
                    stop_now = gopay_balance_insufficient_stop_requested
            if stop_now:
                _append_task_progress(
                    task_id,
                    gopay_task_payloads_service.gopay_wallet_balance_insufficient_limit_progress(
                        current=index,
                        total=total,
                        phone_number=_mask_gopay_phone_for_log(_gopay_wallet_phone(wallet)),
                        balance_insufficient_count=insufficient_count,
                        message=gopay_balance_insufficient_stop_message,
                    ),
                )
            return stop_now

        def _record_no_transfer_balance_miss(wallet, *, index: int = 1, total: int = 1) -> bool:
            nonlocal gopay_no_transfer_balance_miss_count, gopay_no_transfer_balance_fallback_forced
            nonlocal gopay_transfer_disabled_for_official_gift, gopay_transfer_1001_balance_count
            with gopay_state_lock:
                gopay_no_transfer_balance_miss_count += 1
                miss_count = gopay_no_transfer_balance_miss_count
                if miss_count >= 3 and not gopay_no_transfer_balance_fallback_forced:
                    gopay_no_transfer_balance_fallback_forced = True
                    gopay_transfer_disabled_for_official_gift = False
                    gopay_transfer_1001_balance_count = 0
                    switch_now = True
                else:
                    switch_now = gopay_no_transfer_balance_fallback_forced
            if switch_now:
                _append_task_progress(
                    task_id,
                    gopay_task_payloads_service.gopay_wallet_balance_auto_transfer_enabled_progress(
                        current=index,
                        total=total,
                        phone_number=_mask_gopay_phone_for_log(_gopay_wallet_phone(wallet)),
                        balance_miss_count=miss_count,
                    ),
                )
            return switch_now

        def _record_transfer_balance_ready(
            wallet, value: float, balance: dict, *, index: int = 1, total: int = 1
        ) -> None:
            nonlocal gopay_no_transfer_balance_miss_count, gopay_no_transfer_balance_fallback_forced
            nonlocal gopay_transfer_1001_balance_count, gopay_transfer_disabled_for_official_gift
            rounded_value = int(float(value or 0))
            with gopay_state_lock:
                if rounded_value == 1001:
                    gopay_transfer_1001_balance_count += 1
                else:
                    gopay_transfer_1001_balance_count = 0
                match_count = gopay_transfer_1001_balance_count
                if match_count >= 3 and not gopay_transfer_disabled_for_official_gift:
                    gopay_transfer_disabled_for_official_gift = True
                    gopay_no_transfer_balance_fallback_forced = False
                    gopay_no_transfer_balance_miss_count = 0
                    switch_now = True
                else:
                    switch_now = False
            if switch_now:
                _append_task_progress(
                    task_id,
                    gopay_task_payloads_service.gopay_wallet_transfer_auto_disabled_progress(
                        current=index,
                        total=total,
                        phone_number=_mask_gopay_phone_for_log(_gopay_wallet_phone(wallet)),
                        balance=value,
                        currency=balance.get("currency") or "IDR",
                        display_value=balance.get("display_value") or "",
                        balance_1001_count=match_count,
                    ),
                )

        def _gopay_worker_progress_fields() -> dict:
            label = str(getattr(gopay_worker_context, "label", "") or "").strip()
            if not label:
                return {}
            worker_index = int(getattr(gopay_worker_context, "index", 0) or 0)
            fields = {
                "worker": label,
                "worker_label": label,
            }
            if worker_index > 0:
                fields["worker_index"] = worker_index
            return fields

        def _select_gopay_wallet_signup_proxy(*, index: int = 1, total: int = 1) -> str:
            if proxy_api_url:
                selected = _fetch_proxy_from_api_url(
                    proxy_api_url,
                    default_auth_scheme=PAYPAL_PROXY_DEFAULT_SCHEME,
                    provider=proxy_api_provider or "cliproxy",
                )
                if not selected:
                    raise RuntimeError("GoPay 代理 API 已触发换 IP，但未返回代理")
                _append_task_progress(
                    task_id,
                    gopay_task_payloads_service.gopay_proxy_api_selected_progress(
                        current=index,
                        total=total,
                        proxy_label=params.proxy_label,
                        proxy_api_provider=proxy_api_provider or "cliproxy",
                        selected_proxy_summary=_safe_proxy_summary(selected),
                    ),
                )
                return selected
            if normalized_proxy_pool:
                selected = random.choice(normalized_proxy_pool)
                _append_task_progress(
                    task_id,
                    gopay_task_payloads_service.gopay_proxy_selected_progress(
                        current=index,
                        total=total,
                        proxy_label=params.proxy_label,
                        proxy_pool_count=len(normalized_proxy_pool),
                        selected_proxy_summary=_safe_proxy_summary(selected),
                    ),
                )
                return selected
            return proxy_url

        def _gopay_success_progress_fields() -> dict:
            with gopay_state_lock:
                successful_list = sorted(realtime_successful_emails)
            return gopay_task_payloads_service.gopay_success_progress_fields(successful_list)

        def _mark_gopay_success_account(email_value: str, *, message: str = "", success_checkout_url: str = "") -> dict:
            success_email = _normalized_email(email_value)
            if not success_email:
                return _gopay_success_progress_fields()
            marked_at = time.time()
            success_fields = {
                "last_bind_status": "success",
                "last_bind_at": marked_at,
                "last_bind_provider": "gopay",
                "last_checkout_url": success_checkout_url or checkout_url,
                "last_proxy_label": params.proxy_label,
                "last_bind_task_id": task_id,
                "last_bind_message": message or "GoPay 绑定成功",
                "last_bind_failure_stage": "",
                "status": STATUS_ACTIVE,
                "account_type": ACCOUNT_TYPE_PLUS,
                "seat_type": SEAT_CODEX,
                "account_source": ACCOUNT_SOURCE_MANAGED,
                "plus_bound_at": marked_at,
            }
            updated_account = update_account(success_email, **success_fields)
            account_exists_after_update = bool(updated_account) or bool(find_account(load_accounts(), success_email))
            if not updated_account and not account_exists_after_update:
                auth_session_file = get_auth_session_file(success_email)
                add_account(success_email, "", seat_type=SEAT_CODEX)
                if auth_session_file and Path(auth_session_file).exists():
                    success_fields["auth_file"] = auth_session_file
                updated_account = update_account(success_email, **success_fields)
                account_exists_after_update = bool(updated_account) or bool(
                    find_account(load_accounts(), success_email)
                )
            if updated_account or account_exists_after_update:
                try:
                    plan_update = _update_account_cpa_auth_plan_type(
                        success_email,
                        account=updated_account if isinstance(updated_account, dict) else None,
                        plan_type=ACCOUNT_TYPE_PLUS,
                    )
                    if plan_update.get("auth_file") and isinstance(updated_account, dict):
                        updated_account["auth_file"] = plan_update["auth_file"]
                except Exception:
                    logger.warning(
                        "[gopay-bind] failed to update CPA auth plan_type after Plus upgrade: %s",
                        _safe_email_summary(success_email),
                        exc_info=True,
                    )
                with gopay_state_lock:
                    realtime_successful_emails.add(success_email)
                logger.info(
                    "[gopay-bind] marked account Plus immediately after GoPay success: task_id=%s email=%s",
                    task_id[:8] or "<unknown>",
                    _safe_email_summary(success_email),
                )
            else:
                logger.warning(
                    "[gopay-bind] GoPay success account was not persisted: task_id=%s email=%s",
                    task_id[:8] or "<unknown>",
                    _safe_email_summary(success_email),
                )
            if not params.auto_oauth_after_success:
                with gopay_state_lock:
                    already_scheduled = success_email in session_cpa_scheduled_emails
                    if not already_scheduled:
                        session_cpa_scheduled_emails.add(success_email)
                if already_scheduled:
                    return _gopay_success_progress_fields()
                _append_task_progress(
                    task_id,
                    gopay_task_payloads_service.gopay_oauth_login_skipped_progress(
                        success_email=success_email,
                        successful_emails=_gopay_success_progress_fields()["successful_emails"],
                    ),
                )
                logger.info(
                    "[gopay-bind] skipped CPA conversion after GoPay success because OAuth login was not enabled: task_id=%s email=%s",
                    task_id[:8] or "<unknown>",
                    _safe_email_summary(success_email),
                )
                return _gopay_success_progress_fields()

            with gopay_state_lock:
                already_scheduled = success_email in oauth_scheduled_emails
                if not already_scheduled:
                    oauth_scheduled_emails.add(success_email)
            if already_scheduled:
                return _gopay_success_progress_fields()

            _append_task_progress(
                task_id,
                gopay_task_payloads_service.gopay_oauth_login_started_progress(success_email=success_email),
            )

            def _oauth_worker():
                from autotoken.auth.codex_auth import CodexOAuthPhoneRequired

                max_attempts = 3
                retry_delay_seconds = 3
                for attempt in range(1, max_attempts + 1):
                    try:
                        latest_account = find_account(load_accounts(), success_email) or {"email": success_email}
                        oauth_proxy_url = bind_proxy_url or normalized_proxy_url
                        if oauth_proxy_url:
                            _append_task_progress(
                                task_id,
                                gopay_task_payloads_service.gopay_oauth_proxy_selected_progress(
                                    success_email=success_email,
                                    proxy_label=params.proxy_label,
                                ),
                            )
                        oauth_login_kwargs: dict[str, Any] = {"headless": False}
                        if oauth_proxy_url:
                            oauth_login_kwargs["proxy_url"] = oauth_proxy_url
                        if params.proxy_bypass:
                            oauth_login_kwargs["proxy_bypass"] = params.proxy_bypass
                        oauth_result = _run_account_codex_login_once(
                            success_email, latest_account, **oauth_login_kwargs
                        )
                        oauth_successful_emails.append(success_email)
                        _append_task_progress(
                            task_id,
                            gopay_task_payloads_service.gopay_oauth_login_done_progress(
                                success_email=success_email,
                                auth_file=oauth_result.get("auth_file") or "",
                                attempt=attempt,
                                max_attempts=max_attempts,
                            ),
                        )
                        logger.info(
                            "[gopay-bind] OAuth login after GoPay success completed: task_id=%s email=%s auth_file=%s attempt=%d/%d",
                            task_id[:8] or "<unknown>",
                            _safe_email_summary(success_email),
                            oauth_result.get("auth_file") or "",
                            attempt,
                            max_attempts,
                        )
                        return
                    except CodexOAuthPhoneRequired as exc:
                        result_payload = _oauth_phone_required_result(success_email, exc)
                        removed_after_success = {
                            _normalized_email(raw_email)
                            for raw_email in (result_payload.get("removed_pool_emails") or [])
                            if _normalized_email(raw_email)
                        }
                        if not removed_after_success:
                            removed_after_success.add(success_email)
                        with gopay_state_lock:
                            realtime_successful_emails.difference_update(removed_after_success)
                            oauth_failed_emails.append(
                                gopay_task_payloads_service.gopay_oauth_phone_required_failure_record(
                                    success_email=success_email,
                                    error=exc,
                                    removed_pool_emails=result_payload.get("removed_pool_emails") or [],
                                )
                            )
                        _append_task_progress(
                            task_id,
                            gopay_task_payloads_service.gopay_oauth_phone_required_progress(
                                success_email=success_email,
                                removed_pool_emails=result_payload.get("removed_pool_emails") or [],
                                attempt=attempt,
                                max_attempts=max_attempts,
                                successful_emails=_gopay_success_progress_fields()["successful_emails"],
                                message=result_payload["message"],
                            ),
                        )
                        return
                    except Exception as exc:
                        if attempt < max_attempts:
                            _append_task_progress(
                                task_id,
                                gopay_task_payloads_service.gopay_oauth_login_retrying_progress(
                                    success_email=success_email,
                                    attempt=attempt,
                                    max_attempts=max_attempts,
                                    error=exc,
                                ),
                            )
                            logger.warning(
                                "[gopay-bind] OAuth login after GoPay success failed, retrying: task_id=%s email=%s attempt=%d/%d error=%s",
                                task_id[:8] or "<unknown>",
                                _safe_email_summary(success_email),
                                attempt,
                                max_attempts,
                                exc,
                            )
                            time.sleep(retry_delay_seconds)
                            continue
                        with gopay_state_lock:
                            oauth_failed_emails.append(
                                gopay_task_payloads_service.gopay_oauth_failed_record(
                                    success_email=success_email,
                                    error=exc,
                                    attempts=max_attempts,
                                )
                            )
                        _append_task_progress(
                            task_id,
                            gopay_task_payloads_service.gopay_oauth_login_failed_progress(
                                success_email=success_email,
                                attempt=attempt,
                                max_attempts=max_attempts,
                                error=exc,
                            ),
                        )
                        logger.exception(
                            "[gopay-bind] OAuth login after GoPay success failed: task_id=%s email=%s attempts=%d",
                            task_id[:8] or "<unknown>",
                            _safe_email_summary(success_email),
                            max_attempts,
                        )

            threading.Thread(
                target=_oauth_worker,
                name=gopay_task_payloads_service.gopay_oauth_thread_name(success_email),
                daemon=True,
            ).start()
            return _gopay_success_progress_fields()

        def _mark_gopay_token_invalidated_fail(
            email_value: str, *, reason: str, message: str, failure_stage: str = "token_invalidated"
        ):
            fail_email = _normalized_email(email_value)
            if not fail_email or _is_main_account_email(fail_email):
                return
            update_account(
                fail_email,
                status=STATUS_FAIL,
                discarded_at=time.time(),
                discarded_reason=reason,
                last_bind_status="failed",
                last_bind_at=time.time(),
                last_bind_provider="gopay",
                last_checkout_url=checkout_url,
                last_proxy_label=params.proxy_label,
                last_bind_task_id=task_id,
                last_bind_message=message,
                last_bind_failure_stage=failure_stage,
            )

        def _refresh_gopay_auth_session(refresh_email: str, failure_result: dict | None = None) -> dict:
            normalized = _normalized_email(refresh_email)
            if not normalized:
                return {"status": "failed", "message": "auth_session access token 已失效，但邮箱为空，无法标记废弃"}
            with gopay_state_lock:
                if normalized in auth_session_refresh_attempted:
                    return {
                        "status": "failed",
                        "message": f"auth_session access token 已失效，账号已从号池删除: {normalized}",
                    }
                auth_session_refresh_attempted.add(normalized)
            message = (
                f"auth_session access token 已失效，说明账号已无法使用当前凭证登录，账号已从号池删除: {normalized}"
            )
            removed = _remove_pool_accounts_from_local_and_mail(
                [normalized],
                log_context="gopay-token-invalidated",
                reason="gopay_token_invalidated",
                message=message,
            )
            _append_task_progress(
                task_id,
                gopay_task_payloads_service.gopay_auth_session_refresh_failed_progress(
                    email=normalized,
                    failure_stage=(failure_result or {}).get("failure_stage") or "token_invalidated",
                    removed_pool_emails=removed,
                    message=message,
                ),
            )
            return {"status": "failed", "message": message, "removed_pool_emails": removed}

        gopay_wallet_prefetch_context = {"prefetcher": None, "index": 0, "total": 0, "triggered": False}

        def _gopay_progress(progress: dict):
            if isinstance(progress, dict) and progress.get("stage") == "gopay_account_bound":
                success_fields = _mark_gopay_success_account(
                    str(progress.get("email") or ""),
                    message=str(progress.get("message") or "GoPay 绑定成功"),
                    success_checkout_url=str(progress.get("checkout_url") or ""),
                )
                progress = {**progress, **success_fields}
            _append_task_progress(task_id, progress)
            if not isinstance(progress, dict):
                return
            if gopay_wallet_prefetch_context.get("triggered"):
                return
            stage = str(progress.get("stage") or "")
            if stage not in {
                "gopay_validate_otp",
                "gopay_tokenize_pin",
                "gopay_validate_pin",
                "midtrans_create_charge",
            }:
                return
            prefetcher = gopay_wallet_prefetch_context.get("prefetcher")
            if prefetcher is None:
                return
            gopay_wallet_prefetch_context["triggered"] = True
            try:
                prefetcher.ensure_ahead(int(gopay_wallet_prefetch_context.get("index") or 0))
            except Exception:
                logger.debug("[gopay-bind] schedule GoPay wallet prefetch failed", exc_info=True)

        def _append_unique(target: list, value: str):
            normalized = _normalized_email(value)
            if normalized and normalized not in target:
                target.append(normalized)

        def _merge_email_list(result_payload: dict, key: str, target: list[str]):
            for raw_email in result_payload.get(key) or []:
                _append_unique(target, raw_email)

        def _dedupe_failed_email_results(items: list[dict]) -> list[dict]:
            deduped: list[dict] = []
            positions: dict[str, int] = {}
            for item in items:
                if not isinstance(item, dict):
                    continue
                email = _normalized_email(item.get("email") or "")
                if not email:
                    deduped.append(item)
                    continue
                normalized_item = dict(item)
                normalized_item["email"] = email
                if email in positions:
                    deduped[positions[email]] = normalized_item
                else:
                    positions[email] = len(deduped)
                    deduped.append(normalized_item)
            return deduped

        def _is_gopay_wallet_bound_elsewhere_result(result_payload: dict | None) -> bool:
            if not isinstance(result_payload, dict) or result_payload.get("status") == "success":
                return False
            stage = str(result_payload.get("failure_stage") or "")
            text = json.dumps(result_payload, ensure_ascii=False).lower()
            return (
                stage in {"midtrans_already_linked", "midtrans_already_linked_failed"}
                or "gopay_already_linked" in text
                or "already linked" in text
                or "已绑定其他账号" in text
                or "绑定其他账号" in text
            )

        def _is_unused_gopay_wallet_result(result_payload: dict | None) -> bool:
            if not isinstance(result_payload, dict) or result_payload.get("status") == "success":
                return False
            if _is_gopay_wallet_bound_elsewhere_result(result_payload):
                return False
            stage = str(result_payload.get("failure_stage") or "")
            if stage in {
                "browser_charge_guard",
                "stripe_charge_guard",
                "midtrans_charge_guard",
                "gopay_wallet_funding",
            }:
                return True
            if stage in {
                "resolve_midtrans_redirect",
                "pm_redirect",
                "midtrans_load_transaction",
                "midtrans_linking",
                "gopay_validate_reference",
                "gopay_user_consent",
                "trigger_sms_otp",
                "fetch_otp",
                "gopay_validate_otp",
                "gopay_tokenize_pin",
                "gopay_validate_pin",
            }:
                return True
            if stage in {
                "midtrans_create_charge",
                "gopay_payment_validate",
                "gopay_payment_confirm",
                "gopay_payment_process",
            }:
                return False
            text = json.dumps(result_payload, ensure_ascii=False).lower()
            if stage in {"proxy_config", "generate_checkout", "chatgpt_http_session", "chatgpt_verify"}:
                return True
            if (
                "token_invalidated" in text
                or "authentication token has been invalidated" in text
                or "http 403" in text
                or "status 403" in text
                or "forbidden" in text
                or "user is paid" in text
                or "already a paid user" in text
                or "already subscribed" in text
                or "已是付费用户" in text
                or "已有有效订阅" in text
            ):
                return True
            nonzero = {
                _normalized_email(raw_email)
                for raw_email in (result_payload.get("nonzero_blocked_emails") or [])
                if _normalized_email(raw_email)
            }
            if not nonzero:
                return False
            has_consuming_failure = any(
                result_payload.get(key) for key in ("successful_emails", "rejected_emails", "payment_failed_emails")
            )
            return not has_consuming_failure

        def _is_no_transfer_balance_pending_result(result_payload: dict | None) -> bool:
            from autotoken.integrations.rekberinaja import is_rekberinaja_enabled

            if is_rekberinaja_enabled():
                return False
            if not isinstance(result_payload, dict) or result_payload.get("status") == "success":
                return False
            stage = str(result_payload.get("failure_stage") or "")
            text = json.dumps(result_payload, ensure_ascii=False).lower()
            known_payment_stage = stage in {
                "midtrans_create_charge",
                "gopay_payment_validate",
                "gopay_payment_confirm",
                "gopay_payment_process",
            }
            if not known_payment_stage and stage != "post_submit":
                return False
            if stage == "post_submit" and not any(
                marker in text for marker in ("gopay", "midtrans", "payment/process")
            ):
                return False
            return any(
                marker in text
                for marker in (
                    "insufficient",
                    "insufficient funds",
                    "insufficient balance",
                    "not enough",
                    "balance",
                    "saldo",
                    "余额",
                    "gopay balance",
                    "dana tidak cukup",
                    "dana kurang",
                    "saldo tidak cukup",
                    "saldo kurang",
                    "limit tidak cukup",
                    "payment/process 未成功",
                )
            )

        def _is_gopay_wallet_charge_denied_result(result_payload: dict | None) -> bool:
            if not isinstance(result_payload, dict) or result_payload.get("status") == "success":
                return False
            if str(result_payload.get("failure_stage") or "") != "gopay_payment_process":
                return False
            text = json.dumps(result_payload, ensure_ascii=False).lower()
            return (
                "transaction is denied" in text
                or "try another payment method" in text
                or ("transaction_status" in text and "deny" in text)
                or ("fraud_status" in text and "deny" in text)
            )

        def _is_gopay_account_side_failure_result(result_payload: dict | None, retry_reason: str = "") -> bool:
            if not isinstance(result_payload, dict) or result_payload.get("status") == "success":
                return False
            if _is_chatgpt_token_invalidated_result(result_payload):
                return True
            text = json.dumps(result_payload, ensure_ascii=False).lower()
            return "token_invalidated" in text or "authentication token has been invalidated" in text

        def _is_gopay_wallet_signup_failure_result(result_payload: dict | None, retry_reason: str = "") -> bool:
            if not isinstance(result_payload, dict) or result_payload.get("status") == "success":
                return False
            stage = str(result_payload.get("failure_stage") or "")
            reason = str(retry_reason or "")
            wallet_signup_failure_stages = {
                "gopay_wallet_no_numbers",
                "gopay_wallet_provider_unavailable",
                "gopay_wallet_network_error",
                "gopay_wallet_rate_limited",
            }
            return stage in wallet_signup_failure_stages or reason in wallet_signup_failure_stages

        def _preserve_gopay_wallet(wallet) -> None:
            with gopay_state_lock:
                if wallet in reusable_gopay_wallets:
                    return
                reusable_gopay_wallets.append(wallet)
                pool_entry = _push_gopay_reusable_wallet(
                    wallet,
                    task_id=task_id,
                    run_id=gopay_run_id,
                    created_at=gopay_wallet_created_at.get(id(wallet)),
                    funded=id(wallet) in funded_gopay_wallet_ids or id(wallet) in gopay_wallet_funding_attempted_ids,
                )
            ttl_seconds = (
                max(0, int(float((pool_entry or {}).get("expires_at") or 0) - time.time())) if pool_entry else 0
            )
            _append_task_progress(
                task_id,
                gopay_task_payloads_service.gopay_wallet_preserved_progress(
                    phone_number=_mask_gopay_phone_for_log(_gopay_wallet_phone(wallet)),
                    expires_in_seconds=ttl_seconds,
                ),
            )

        def _take_reusable_gopay_wallet_for_bind(*, index: int = 1, total: int = 1):
            from autotoken.payments.gopay_auto_register import is_sms_bridge_reusable

            while True:
                entry = _pop_gopay_reusable_wallet(gopay_pin=gopay_pin, country_code=country_code)
                if not entry:
                    return None
                wallet = entry.get("wallet")
                if wallet is None:
                    continue
                bridge_token = str(entry.get("bridge_token") or _gopay_wallet_bridge_token(wallet) or "").strip()
                reusable, reason = (
                    is_sms_bridge_reusable(bridge_token) if bridge_token else (False, "bridge_token_missing")
                )
                if (
                    not reusable
                    and str(entry.get("run_id") or "") == gopay_run_id
                    and reason
                    in {
                        "bridge_missing",
                        "bridge_token_missing",
                    }
                ):
                    reusable = True
                if reusable:
                    break
                logger.warning(
                    "[gopay-bind] reusable wallet discarded before bind: index=%s/%s phone=%s reason=%s",
                    index,
                    total,
                    _mask_gopay_phone_for_log(_gopay_wallet_phone(wallet)),
                    reason,
                )
                _append_task_progress(
                    task_id,
                    gopay_task_payloads_service.gopay_wallet_reuse_discarded_progress(
                        current=index,
                        total=total,
                        phone_number=_mask_gopay_phone_for_log(_gopay_wallet_phone(wallet)),
                        reason=reason,
                    ),
                )
            with gopay_state_lock:
                active_gopay_wallets.append(wallet)
                gopay_wallet_created_at[id(wallet)] = float(entry.get("created_at") or time.time())
                if entry.get("funded"):
                    funded_gopay_wallet_ids.add(id(wallet))
                    gopay_wallet_funding_attempted_ids.add(id(wallet))
            _append_task_progress(
                task_id,
                gopay_task_payloads_service.gopay_wallet_reused_progress(
                    current=index,
                    total=total,
                    phone_number=_mask_gopay_phone_for_log(_gopay_wallet_phone(wallet)),
                    expires_in_seconds=max(0, int(float(entry.get("expires_at") or 0) - time.time())),
                ),
            )
            logger.info(
                "[gopay-bind] reusable wallet selected for bind: index=%s/%s phone=%s funded=%s",
                index,
                total,
                _mask_gopay_phone_for_log(_gopay_wallet_phone(wallet)),
                bool(entry.get("funded")),
            )
            return wallet

        class _GoPayWalletBalanceNotReady(RuntimeError):
            pass

        class _GoPayWalletBalanceInsufficientLimit(RuntimeError):
            pass

        def _rekberinaja_fallback_after_balance_wait_enabled() -> bool:
            from autotoken.integrations.rekberinaja import is_rekberinaja_enabled

            if is_rekberinaja_enabled():
                return False
            with gopay_state_lock:
                forced_fallback = gopay_no_transfer_balance_fallback_forced
                official_gift_mode = gopay_transfer_disabled_for_official_gift
            if official_gift_mode:
                return False
            return bool(gopay_balance_wait_fallback_transfer or forced_fallback)

        def _wait_for_gopay_wallet_balance_ready(
            wallet,
            *,
            index: int = 1,
            total: int = 1,
            poll_intervals: list[float] | None = None,
            poll_intervals_runtime_mode: str = "",
            initial_wait: float | None = None,
            not_ready_message: str = "GoPay 余额三次查询仍未到账，舍弃该钱包并重新注册",
            ready_message: str = "GoPay 钱包余额已到账，开始绑定",
            raise_on_not_ready: bool = True,
            ready_callback=None,
        ) -> bool:
            if wallet is None:
                return False
            with gopay_state_lock:
                if id(wallet) in gopay_wallet_balance_ready_ids:
                    return True
            access_token = str(getattr(wallet, "access_token", "") or "").strip()
            if not access_token:
                return False

            from autotoken.payments.gopay_auto_register import query_gopay_balance

            runtime_mode = str(poll_intervals_runtime_mode or "").strip().lower()
            if poll_intervals is None:
                runtime_mode = runtime_mode or "balance"
            intervals = list(poll_intervals if poll_intervals is not None else _gopay_wallet_balance_poll_intervals())
            if initial_wait is not None:
                intervals = [float(initial_wait), *intervals]
            if not intervals:
                intervals = [0.0]
            max_checks = max(1, len(intervals))

            def _latest_runtime_intervals() -> list[float]:
                if runtime_mode == "transfer":
                    return _gopay_transfer_balance_poll_intervals()
                if runtime_mode == "balance":
                    return _gopay_wallet_balance_poll_intervals()
                return []

            def _sleep_balance_wait(wait_seconds: float, check_index: int) -> None:
                wait_seconds = max(0.0, float(wait_seconds or 0.0))
                if wait_seconds <= 0:
                    return
                latest_intervals = _latest_runtime_intervals()
                if check_index <= len(latest_intervals):
                    wait_seconds = min(wait_seconds, max(0.0, float(latest_intervals[check_index - 1] or 0.0)))
                if wait_seconds > 0:
                    time.sleep(wait_seconds)

            for check_index, wait_seconds in enumerate(intervals, 1):
                latest_intervals = _latest_runtime_intervals()
                if latest_intervals:
                    if check_index > len(latest_intervals):
                        break
                    wait_seconds = latest_intervals[check_index - 1]
                    max_checks = len(latest_intervals)
                wait_seconds = max(0.0, float(wait_seconds))
                if wait_seconds > 0:
                    _append_task_progress(
                        task_id,
                        gopay_task_payloads_service.gopay_wallet_balance_wait_progress(
                            current=index,
                            total=total,
                            phone_number=_mask_gopay_phone_for_log(_gopay_wallet_phone(wallet)),
                            delay_seconds=wait_seconds,
                            attempt=check_index,
                            max_attempts=max_checks,
                        ),
                    )
                    _sleep_balance_wait(wait_seconds, check_index)
                try:
                    balance = query_gopay_balance(
                        access_token=access_token,
                        gopay_cfg=getattr(wallet, "gopay_cfg", None) or {},
                        session=getattr(wallet, "session", None),
                        timeout=20,
                    )
                except Exception as exc:
                    _append_task_progress(
                        task_id,
                        gopay_task_payloads_service.gopay_wallet_balance_check_failed_progress(
                            current=index,
                            total=total,
                            phone_number=_mask_gopay_phone_for_log(_gopay_wallet_phone(wallet)),
                            attempt=check_index,
                            max_attempts=max_checks,
                            error_summary=_compact_log_text(exc, limit=160),
                        ),
                    )
                    continue
                value = float(balance.get("value") or 0)
                _append_task_progress(
                    task_id,
                    gopay_task_payloads_service.gopay_wallet_balance_checked_progress(
                        current=index,
                        total=total,
                        phone_number=_mask_gopay_phone_for_log(_gopay_wallet_phone(wallet)),
                        balance=value,
                        currency=balance.get("currency") or "IDR",
                        display_value=balance.get("display_value") or "",
                        attempt=check_index,
                        max_attempts=max_checks,
                    ),
                )
                if value >= 1:
                    if callable(ready_callback):
                        try:
                            ready_callback(value, balance)
                        except Exception:
                            logger.debug("[gopay-bind] GoPay balance ready callback failed", exc_info=True)
                    _append_task_progress(
                        task_id,
                        gopay_task_payloads_service.gopay_wallet_balance_ready_progress(
                            current=index,
                            total=total,
                            phone_number=_mask_gopay_phone_for_log(_gopay_wallet_phone(wallet)),
                            balance=value,
                            currency=balance.get("currency") or "IDR",
                            display_value=balance.get("display_value") or "",
                            message=ready_message,
                        ),
                    )
                    with gopay_state_lock:
                        gopay_wallet_balance_ready_ids.add(id(wallet))
                    _reset_funded_balance_insufficient_count()
                    return True
            _append_task_progress(
                task_id,
                gopay_task_payloads_service.gopay_wallet_balance_not_ready_progress(
                    current=index,
                    total=total,
                    phone_number=_mask_gopay_phone_for_log(_gopay_wallet_phone(wallet)),
                    message=not_ready_message,
                ),
            )
            if not raise_on_not_ready:
                return False
            raise _GoPayWalletBalanceNotReady(not_ready_message)

        def _fund_gopay_wallet_for_bind(
            wallet,
            *,
            index: int = 1,
            total: int = 1,
            allow_when_transfer_disabled: bool = False,
        ) -> dict | None:
            from dataclasses import replace

            from autotoken.integrations.rekberinaja import (
                fund_gopay_wallet_if_enabled,
                is_rekberinaja_enabled,
                load_rekberinaja_config,
            )

            transfer_enabled = is_rekberinaja_enabled()
            if (
                wallet is None
                or _transfer_disabled_for_official_gift()
                or not (transfer_enabled or allow_when_transfer_disabled)
            ):
                return None
            funding_config = None
            if allow_when_transfer_disabled and not transfer_enabled:
                funding_config = replace(load_rekberinaja_config(), enabled=True, transfer_enabled=False)
            phone = str(getattr(wallet, "phone_number", "") or "").strip()
            if not phone:
                try:
                    phone = str((wallet.as_phone_account() or {}).get("phone_number") or "").strip()
                except Exception:
                    phone = ""
            if _wait_for_gopay_wallet_balance_ready(
                wallet,
                index=index,
                total=total,
                poll_intervals=[0.0],
                not_ready_message="GoPay 钱包余额不足，准备通过 Rekberinaja 转账",
                ready_message="GoPay 钱包已有余额，跳过 Rekberinaja 转账并开始绑定",
                raise_on_not_ready=False,
            ):
                _append_task_progress(
                    task_id,
                    gopay_task_payloads_service.gopay_wallet_funding_skipped_progress(
                        current=index,
                        total=total,
                        phone_number=_mask_gopay_phone_for_log(phone),
                        message="GoPay 钱包已有 ≥1Rp 余额，本次跳过 Rekberinaja 转账",
                    ),
                )
                return None
            with gopay_state_lock:
                wallet_already_funded = id(wallet) in funded_gopay_wallet_ids
            if wallet_already_funded:
                _append_task_progress(
                    task_id,
                    gopay_task_payloads_service.gopay_wallet_funding_skipped_progress(
                        current=index,
                        total=total,
                        phone_number=_mask_gopay_phone_for_log(phone),
                        message="复用的 GoPay 钱包已记录为已充值或已提交过充值订单，本次不重复转账",
                    ),
                )
                _wait_for_gopay_wallet_balance_ready(
                    wallet,
                    index=index,
                    total=total,
                    poll_intervals=_gopay_transfer_balance_poll_intervals(),
                    poll_intervals_runtime_mode="transfer",
                    not_ready_message="GoPay 已提交过充值订单但余额仍未到账，舍弃该钱包并重新注册",
                )
                return None

            def _funding_progress(stage: str, payload: dict[str, Any] | None = None) -> None:
                data = dict(payload or {})
                if data.get("phone_number"):
                    data["phone_number"] = _mask_gopay_phone_for_log(str(data.get("phone_number") or ""))
                data.setdefault("stage", stage)
                data.setdefault("current", index)
                data.setdefault("total", total)
                _append_task_progress(task_id, data)

            _append_task_progress(
                task_id,
                gopay_task_payloads_service.gopay_wallet_funding_started_progress(
                    current=index,
                    total=total,
                    phone_number=_mask_gopay_phone_for_log(phone),
                ),
            )
            try:
                result = fund_gopay_wallet_if_enabled(
                    phone, config=funding_config, log=logger.info, progress=_funding_progress
                )
            except Exception as exc:
                if bool(getattr(exc, "debited_possible", False)):
                    with gopay_state_lock:
                        funded_gopay_wallet_ids.add(id(wallet))
                        gopay_wallet_funding_attempted_ids.add(id(wallet))
                _append_task_progress(
                    task_id,
                    gopay_task_payloads_service.gopay_wallet_funding_failed_progress(
                        current=index,
                        total=total,
                        phone_number=_mask_gopay_phone_for_log(phone),
                        transaction_id=str(getattr(exc, "transaction_id", "") or ""),
                        rekberinaja_stage=str(getattr(exc, "stage", "") or ""),
                        debited_possible=bool(getattr(exc, "debited_possible", False)),
                        error_summary=_compact_log_text(exc, limit=180),
                    ),
                )
                raise
            with gopay_state_lock:
                funded_gopay_wallet_ids.add(id(wallet))
                gopay_wallet_funding_attempted_ids.add(id(wallet))
            _append_task_progress(
                task_id,
                gopay_task_payloads_service.gopay_wallet_funding_submitted_progress(
                    current=index,
                    total=total,
                    phone_number=_mask_gopay_phone_for_log(phone),
                    transaction_id=(result or {}).get("transaction_id") or "",
                ),
            )
            _wait_for_gopay_wallet_balance_ready(
                wallet,
                index=index,
                total=total,
                poll_intervals=_gopay_transfer_balance_poll_intervals(),
                poll_intervals_runtime_mode="transfer",
                not_ready_message="Rekberinaja 转账后 GoPay 余额仍未到账，舍弃该钱包并重新注册",
                ready_callback=lambda value, balance: _record_transfer_balance_ready(
                    wallet,
                    value,
                    balance,
                    index=index,
                    total=total,
                ),
            )
            _append_task_progress(
                task_id,
                gopay_task_payloads_service.gopay_wallet_funding_done_progress(
                    current=index,
                    total=total,
                    phone_number=_mask_gopay_phone_for_log(phone),
                    transaction_id=(result or {}).get("transaction_id") or "",
                ),
            )
            return result

        def _wait_after_gopay_pin_when_transfer_disabled(wallet, *, index: int = 1, total: int = 1) -> None:
            from autotoken.integrations.rekberinaja import is_rekberinaja_enabled

            if wallet is None or (is_rekberinaja_enabled() and not _transfer_disabled_for_official_gift()):
                return
            with gopay_state_lock:
                if id(wallet) in gopay_wallet_balance_ready_ids:
                    return
            access_token = str(getattr(wallet, "access_token", "") or "").strip()
            if access_token:
                fallback_to_transfer = _rekberinaja_fallback_after_balance_wait_enabled()
                if fallback_to_transfer:
                    balance_wait_intervals = _gopay_wallet_balance_poll_intervals()
                    ready = _wait_for_gopay_wallet_balance_ready(
                        wallet,
                        index=index,
                        total=total,
                        poll_intervals=balance_wait_intervals,
                        not_ready_message="GoPay 余额等待超时，准备回退到 Rekberinaja 转账",
                        raise_on_not_ready=False,
                    )
                    if ready:
                        _reset_no_transfer_balance_misses()
                        return
                    _append_task_progress(
                        task_id,
                        gopay_task_payloads_service.gopay_wallet_balance_fallback_transfer_progress(
                            current=index,
                            total=total,
                            phone_number=_mask_gopay_phone_for_log(_gopay_wallet_phone(wallet)),
                            wait_seconds_total=sum(max(0.0, float(item)) for item in balance_wait_intervals),
                        ),
                    )
                    _fund_gopay_wallet_for_bind(
                        wallet,
                        index=index,
                        total=total,
                        allow_when_transfer_disabled=True,
                    )
                    return
                _wait_for_gopay_wallet_balance_ready(
                    wallet,
                    index=index,
                    total=total,
                    poll_intervals=_gopay_wallet_balance_poll_intervals(),
                )
                _reset_no_transfer_balance_misses()
                return
            delay_seconds = _gopay_auto_signup_no_transfer_bind_wait_seconds()
            if delay_seconds <= 0:
                return
            created_at = float(gopay_wallet_created_at.get(id(wallet)) or time.time())
            elapsed = max(0.0, time.time() - created_at)
            wait_seconds = max(0.0, delay_seconds - elapsed)
            if wait_seconds <= 0:
                return
            _append_task_progress(
                task_id,
                gopay_task_payloads_service.gopay_wallet_no_transfer_bind_wait_progress(
                    current=index,
                    total=total,
                    phone_number=_mask_gopay_phone_for_log(_gopay_wallet_phone(wallet)),
                    delay_seconds=wait_seconds,
                ),
            )
            time.sleep(wait_seconds)

        def _register_gopay_wallet_for_bind(*, index: int = 1, total: int = 1):
            from autotoken.payments.gopay_auto_register import GoPaySignupProbeError, register_gopay_wallet

            max_wallet_attempts = max(1, int(os.environ.get("GOPAY_AUTO_SIGNUP_WALLET_ATTEMPTS", "10") or "10"))
            no_numbers_attempts = max(1, int(os.environ.get("GOPAY_AUTO_SIGNUP_NO_NUMBERS_ATTEMPTS", "3") or "3"))
            last_exc: Exception | None = None
            wallet_attempt = 1
            no_numbers_attempt = 0
            while wallet_attempt <= max_wallet_attempts:

                def _signup_log(message: str, *, _attempt: int = wallet_attempt) -> None:
                    text = _compact_log_text(message, limit=220)
                    logger.info(text)
                    if not text:
                        return
                    _append_task_progress(
                        task_id,
                        gopay_task_payloads_service.gopay_wallet_auto_signup_detail_progress(
                            current=index,
                            total=total,
                            attempt=_attempt,
                            max_attempts=max_wallet_attempts,
                            message=text,
                            worker_fields=_gopay_worker_progress_fields(),
                        ),
                    )

                _append_task_progress(
                    task_id,
                    gopay_task_payloads_service.gopay_wallet_auto_signup_started_progress(
                        current=index,
                        total=total,
                        wallet_attempt=wallet_attempt,
                        max_wallet_attempts=max_wallet_attempts,
                        sms_provider=_current_gopay_auto_signup_sms_provider(),
                    ),
                )
                try:
                    signup_proxy_url = _select_gopay_wallet_signup_proxy(index=index, total=total)
                    signup_sms_provider = _current_gopay_auto_signup_sms_provider()
                    wallet = register_gopay_wallet(
                        pin=gopay_pin,
                        proxy_url=signup_proxy_url,
                        network_retry_proxy_provider=(
                            lambda: (
                                _select_gopay_wallet_signup_proxy(index=index, total=total)
                                if (proxy_api_url or normalized_proxy_pool)
                                else ""
                            )
                        ),
                        country_code=country_code,
                        sms_provider=signup_sms_provider,
                        hero_sms_config=gopay_auto_signup_hero_sms_config,
                        smscloud_config=gopay_auto_signup_smscloud_config,
                        smsbower_config=gopay_auto_signup_smsbower_config,
                        smscode_config=gopay_auto_signup_smscode_config,
                        public_base_url=gopay_task_public_base_url,
                        appium_config=gopay_auto_signup_appium_config,
                        log=_signup_log,
                    )
                    break
                except GoPaySignupProbeError as exc:
                    _append_task_progress(
                        task_id,
                        gopay_task_payloads_service.gopay_wallet_auto_signup_probe_failed_progress(
                            current=index,
                            total=total,
                            attempt=wallet_attempt,
                            max_attempts=max_wallet_attempts,
                            error_summary=_compact_log_text(exc, limit=220),
                        ),
                    )
                    raise
                except Exception as exc:
                    last_exc = exc
                    if _looks_like_gopay_wallet_signup_rate_limited(exc):
                        progress = gopay_task_payloads_service.gopay_wallet_auto_signup_rate_limited_progress(
                            current=index,
                            total=total,
                            attempt=wallet_attempt,
                            max_attempts=max_wallet_attempts,
                            no_numbers_attempt=no_numbers_attempt,
                            no_numbers_max_attempts=no_numbers_attempts,
                            error_summary=_compact_log_text(exc, limit=220),
                        )
                        message = str(progress.get("message") or "")
                        _append_task_progress(task_id, progress)
                        raise _GoPayWalletSignupRateLimited(message) from exc
                    if _looks_like_gopay_wallet_signup_no_numbers(exc):
                        no_numbers_attempt += 1
                        if no_numbers_attempt < no_numbers_attempts:
                            _append_task_progress(
                                task_id,
                                gopay_task_payloads_service.gopay_wallet_auto_signup_no_numbers_retry_progress(
                                    current=index,
                                    total=total,
                                    attempt=wallet_attempt,
                                    max_attempts=max_wallet_attempts,
                                    no_numbers_attempt=no_numbers_attempt,
                                    no_numbers_max_attempts=no_numbers_attempts,
                                    error_summary=_compact_log_text(exc, limit=220),
                                ),
                            )
                            time.sleep(3)
                            continue
                        progress = gopay_task_payloads_service.gopay_wallet_auto_signup_no_numbers_progress(
                            current=index,
                            total=total,
                            attempt=wallet_attempt,
                            max_attempts=max_wallet_attempts,
                            no_numbers_attempt=no_numbers_attempt,
                            no_numbers_max_attempts=no_numbers_attempts,
                            error_summary=_compact_log_text(exc, limit=220),
                        )
                        message = str(progress.get("message") or "")
                        _append_task_progress(task_id, progress)
                        raise _GoPayWalletSignupNoNumbers(message) from exc
                    if _looks_like_gopay_wallet_signup_provider_error(exc):
                        _append_task_progress(
                            task_id,
                            gopay_task_payloads_service.gopay_wallet_auto_signup_provider_error_progress(
                                current=index,
                                total=total,
                                attempt=wallet_attempt,
                                max_attempts=max_wallet_attempts,
                                error_summary=_compact_log_text(exc, limit=220),
                            ),
                        )
                        raise
                    if _looks_like_gopay_wallet_signup_network_error(exc):
                        progress = gopay_task_payloads_service.gopay_wallet_auto_signup_network_error_progress(
                            current=index,
                            total=total,
                            attempt=wallet_attempt,
                            max_attempts=max_wallet_attempts,
                            error_summary=_compact_log_text(exc, limit=220),
                        )
                        message = str(progress.get("message") or "")
                        _append_task_progress(task_id, progress)
                        raise _GoPayWalletSignupNetworkError(message) from exc
                    if wallet_attempt >= max_wallet_attempts:
                        raise
                    _append_task_progress(
                        task_id,
                        gopay_task_payloads_service.gopay_wallet_auto_signup_retry_progress(
                            current=index,
                            total=total,
                            next_attempt=wallet_attempt + 1,
                            max_attempts=max_wallet_attempts,
                            error_summary=_compact_log_text(exc, limit=160),
                        ),
                    )
                    time.sleep(2)
                    wallet_attempt += 1
            else:
                raise last_exc or RuntimeError("GoPay 钱包自动注册失败")
            with gopay_state_lock:
                active_gopay_wallets.append(wallet)
                gopay_wallet_created_at[id(wallet)] = time.time()
            _append_task_progress(
                task_id,
                gopay_task_payloads_service.gopay_wallet_auto_signup_done_progress(
                    current=index,
                    total=total,
                    phone_number=_mask_gopay_phone_for_log(wallet.phone_number),
                ),
            )
            return wallet

        def _discard_gopay_wallet_for_balance_not_ready(wallet, *, index: int = 1, total: int = 1) -> None:
            if wallet is None:
                return
            with gopay_state_lock:
                if wallet in reusable_gopay_wallets:
                    reusable_gopay_wallets.remove(wallet)
                if wallet in active_gopay_wallets:
                    active_gopay_wallets.remove(wallet)
                retained_gopay_wallets[:] = [item for item in retained_gopay_wallets if item is not wallet]
            try:
                wallet.close(success=False)
            except Exception:
                logger.debug("[gopay-bind] close abandoned GoPay wallet failed", exc_info=True)
            _append_task_progress(
                task_id,
                gopay_task_payloads_service.gopay_wallet_balance_abandoned_progress(
                    current=index,
                    total=total,
                    phone_number=_mask_gopay_phone_for_log(_gopay_wallet_phone(wallet)),
                ),
            )

        def _discard_gopay_wallet_bound_elsewhere(wallet, *, index: int = 1, total: int = 1) -> None:
            if wallet is None:
                return
            with gopay_state_lock:
                if wallet in reusable_gopay_wallets:
                    reusable_gopay_wallets.remove(wallet)
                if wallet in active_gopay_wallets:
                    active_gopay_wallets.remove(wallet)
                retained_gopay_wallets[:] = [item for item in retained_gopay_wallets if item is not wallet]
                funded_gopay_wallet_ids.discard(id(wallet))
                gopay_wallet_funding_attempted_ids.discard(id(wallet))
                gopay_wallet_balance_ready_ids.discard(id(wallet))
                gopay_wallet_created_at.pop(id(wallet), None)
            try:
                wallet.close(success=False)
            except Exception:
                logger.debug("[gopay-bind] close already-linked GoPay wallet failed", exc_info=True)
            _append_task_progress(
                task_id,
                gopay_task_payloads_service.gopay_wallet_already_linked_discarded_progress(
                    current=index,
                    total=total,
                    phone_number=_mask_gopay_phone_for_log(_gopay_wallet_phone(wallet)),
                ),
            )

        def _discard_gopay_wallet_charge_denied(wallet, *, index: int = 1, total: int = 1) -> None:
            if wallet is None:
                return
            with gopay_state_lock:
                if wallet in reusable_gopay_wallets:
                    reusable_gopay_wallets.remove(wallet)
                if wallet in active_gopay_wallets:
                    active_gopay_wallets.remove(wallet)
                retained_gopay_wallets[:] = [item for item in retained_gopay_wallets if item is not wallet]
                funded_gopay_wallet_ids.discard(id(wallet))
                gopay_wallet_funding_attempted_ids.discard(id(wallet))
                gopay_wallet_balance_ready_ids.discard(id(wallet))
                gopay_wallet_created_at.pop(id(wallet), None)
            try:
                wallet.close(success=False)
            except Exception:
                logger.debug("[gopay-bind] close denied GoPay wallet failed", exc_info=True)
            _append_task_progress(
                task_id,
                gopay_task_payloads_service.gopay_wallet_charge_denied_discarded_progress(
                    current=index,
                    total=total,
                    phone_number=_mask_gopay_phone_for_log(_gopay_wallet_phone(wallet)),
                ),
            )

        def _prepare_gopay_wallet_for_bind(wallet=None, *, index: int = 1, total: int = 1):
            max_wallet_attempts = max(1, int(os.environ.get("GOPAY_AUTO_SIGNUP_WALLET_ATTEMPTS", "10") or "10"))
            last_exc: Exception | None = None
            for wallet_attempt in range(1, max_wallet_attempts + 1):
                if _gopay_balance_insufficient_stop_requested():
                    raise _GoPayWalletBalanceInsufficientLimit(gopay_balance_insufficient_stop_message)
                current_wallet = wallet
                wallet = None
                if current_wallet is None:
                    current_wallet = _register_gopay_wallet_for_bind(index=index, total=total)

                def _retry_after_balance_not_ready(
                    exc: Exception,
                    *,
                    retry_wallet=current_wallet,
                    retry_attempt=wallet_attempt,
                ) -> None:
                    nonlocal last_exc
                    last_exc = exc
                    _discard_gopay_wallet_for_balance_not_ready(retry_wallet, index=index, total=total)
                    if retry_attempt >= max_wallet_attempts:
                        raise exc
                    _append_task_progress(
                        task_id,
                        gopay_task_payloads_service.gopay_wallet_auto_signup_retry_progress(
                            current=index,
                            total=total,
                            next_attempt=retry_attempt + 1,
                            max_attempts=max_wallet_attempts,
                            message="GoPay 余额未到账，准备重新注册 GoPay 钱包",
                        ),
                    )

                try:
                    _fund_gopay_wallet_for_bind(current_wallet, index=index, total=total)
                    _wait_after_gopay_pin_when_transfer_disabled(current_wallet, index=index, total=total)
                    return current_wallet
                except _GoPayWalletBalanceNotReady as exc:
                    last_exc = exc
                    if _gopay_wallet_funding_attempted(current_wallet):
                        stop_now = _record_funded_balance_insufficient(current_wallet, index=index, total=total)
                        _discard_gopay_wallet_for_balance_not_ready(current_wallet, index=index, total=total)
                        if stop_now:
                            raise _GoPayWalletBalanceInsufficientLimit(gopay_balance_insufficient_stop_message) from exc
                        if wallet_attempt >= max_wallet_attempts:
                            raise
                        _append_task_progress(
                            task_id,
                            gopay_task_payloads_service.gopay_wallet_auto_signup_retry_progress(
                                current=index,
                                total=total,
                                next_attempt=wallet_attempt + 1,
                                max_attempts=max_wallet_attempts,
                                message="GoPay 余额未到账，准备重新注册 GoPay 钱包",
                            ),
                        )
                        continue
                    if _record_no_transfer_balance_miss(current_wallet, index=index, total=total):
                        try:
                            _fund_gopay_wallet_for_bind(
                                current_wallet,
                                index=index,
                                total=total,
                                allow_when_transfer_disabled=True,
                            )
                        except _GoPayWalletBalanceNotReady as funded_exc:
                            if _record_funded_balance_insufficient(current_wallet, index=index, total=total):
                                _discard_gopay_wallet_for_balance_not_ready(current_wallet, index=index, total=total)
                                raise _GoPayWalletBalanceInsufficientLimit(
                                    gopay_balance_insufficient_stop_message
                                ) from funded_exc
                            _retry_after_balance_not_ready(funded_exc)
                            continue
                        return current_wallet
                    _retry_after_balance_not_ready(exc)
            raise last_exc or RuntimeError("GoPay 钱包准备失败")

        class _GoPayWalletPrefetcher:
            def __init__(self, *, total: int):
                self.total = max(0, int(total or 0))
                self.max_workers = _gopay_auto_signup_prefetch_wallets() if gopay_auto_signup and self.total > 1 else 0
                self.executor = ThreadPoolExecutor(max_workers=self.max_workers) if self.max_workers > 0 else None
                self.futures: list[tuple[Any, int]] = []
                self.next_index = 1

            def ensure_ahead(self, completed_index: int) -> None:
                if (
                    self.executor is None
                    or cancel_signal.is_cancelled()
                    or _gopay_balance_insufficient_stop_requested()
                ):
                    return
                self.next_index = max(self.next_index, int(completed_index or 0) + 1)
                while (
                    len(self.futures) < self.max_workers
                    and self.next_index <= self.total
                    and not _gopay_balance_insufficient_stop_requested()
                ):
                    prefetch_index = self.next_index
                    self.next_index += 1
                    _append_task_progress(
                        task_id,
                        gopay_task_payloads_service.gopay_wallet_prefetch_started_progress(
                            current=prefetch_index,
                            total=self.total,
                        ),
                    )
                    future = self.executor.submit(
                        _prepare_gopay_wallet_for_bind,
                        None,
                        index=prefetch_index,
                        total=self.total,
                    )
                    self.futures.append((future, prefetch_index))

            def take(self, *, index: int) -> Any | None:
                if not self.futures:
                    return None
                done = [item for item in self.futures if item[0].done()]
                if not done:
                    _append_task_progress(
                        task_id,
                        gopay_task_payloads_service.gopay_wallet_prefetch_wait_progress(
                            current=index,
                            total=self.total,
                        ),
                    )
                    completed, _ = wait([future for future, _label in self.futures], return_when=FIRST_COMPLETED)
                    done = [item for item in self.futures if item[0] in completed]
                future, prefetch_index = done[0]
                self.futures = [item for item in self.futures if item[0] is not future]
                try:
                    wallet = future.result()
                except (_GoPayWalletSignupRateLimited, _GoPayWalletSignupNetworkError):
                    raise
                except Exception as exc:
                    _append_task_progress(
                        task_id,
                        gopay_task_payloads_service.gopay_wallet_prefetch_failed_progress(
                            current=index,
                            total=self.total,
                            prefetch_index=prefetch_index,
                            error_summary=_compact_log_text(exc, limit=180),
                        ),
                    )
                    return None
                _append_task_progress(
                    task_id,
                    gopay_task_payloads_service.gopay_wallet_prefetch_used_progress(
                        current=index,
                        total=self.total,
                        prefetch_index=prefetch_index,
                        phone_number=_mask_gopay_phone_for_log(_gopay_wallet_phone(wallet)),
                    ),
                )
                return wallet

            def close(self) -> None:
                if self.executor is None:
                    return
                self.executor.shutdown(wait=True, cancel_futures=True)

        def _register_one_for_gopay(*, index: int = 1, total: int = 1) -> str:
            from autotoken.interfaces.manager import (
                _temporary_mail_provider,
                create_account_direct,
                wrap_mail_client_with_auth_retry,
            )
            from autotoken.mail import TemporaryEmailClient

            register_domain = (
                auto_register_domains[(index - 1) % len(auto_register_domains)] if auto_register_domains else ""
            )
            register_domain = str(register_domain or "").strip().lstrip("@")
            if auto_register_mail_provider not in {"luckmail", "outlook"} and not register_domain:
                raise RuntimeError("未配置可用注册域名")
            luckmail_register_domain = (
                auto_register_luckmail_preferred_domains[(index - 1) % len(auto_register_luckmail_preferred_domains)]
                if auto_register_luckmail_preferred_domains
                else auto_register_luckmail_preferred_domain
            )
            mail_provider_overrides = {}
            if auto_register_mail_provider == "luckmail":
                if auto_register_luckmail_email_type:
                    mail_provider_overrides["LUCKMAIL_EMAIL_TYPE"] = auto_register_luckmail_email_type
                if luckmail_register_domain is not None:
                    mail_provider_overrides["LUCKMAIL_PREFERRED_DOMAIN"] = luckmail_register_domain

            _append_task_progress(
                task_id,
                gopay_task_payloads_service.gopay_auto_register_started_progress(
                    current=index,
                    total=total,
                    mail_provider=auto_register_mail_provider,
                    luckmail_email_type=auto_register_luckmail_email_type,
                    luckmail_register_domain=luckmail_register_domain,
                    register_domain=register_domain,
                ),
            )
            with _temporary_mail_provider(auto_register_mail_provider, mail_provider_overrides):
                raw_mail_client = TemporaryEmailClient()
            raw_mail_client.login()
            mail_client = wrap_mail_client_with_auth_retry(raw_mail_client, log_prefix="GoPay自动注册")
            outcome = {}

            def _register_progress(progress: dict):
                if not isinstance(progress, dict):
                    return
                _append_task_progress(
                    task_id,
                    gopay_task_payloads_service.gopay_auto_register_child_progress(
                        progress,
                        current=index,
                        total=total,
                    ),
                )

            register_result = create_account_direct(
                mail_client,
                out_outcome=outcome,
                domain=register_domain,
                email_prefix=auto_register_prefix or None,
                password=auto_register_password or None,
                skip_post_register=True,
                post_register_oauth=False,
                check_team_membership=False,
                register_mode=auto_register_mode,
                progress_callback=_register_progress,
            )
            registered_email = _normalized_email(
                (register_result or {}).get("email") if isinstance(register_result, dict) else register_result
            )
            if not registered_email:
                registered_email = _normalized_email(outcome.get("email") or outcome.get("last_email"))
            if not registered_email:
                raise RuntimeError(outcome.get("reason") or "自动注册未返回邮箱")

            auth_session_file = get_auth_session_file(registered_email)
            registered_account = find_account(load_accounts(), registered_email)
            has_auth_file = bool(registered_account and _resolve_status_auth_file(registered_account))
            if not has_auth_file:
                if not auth_session_file or not Path(auth_session_file).exists():
                    raise RuntimeError(f"自动注册账号缺少可用 auth_session/auth_file: {registered_email}")
                register_payload = register_result if isinstance(register_result, dict) else {}
                if not registered_account:
                    add_account(
                        registered_email,
                        str(
                            register_payload.get("password") or outcome.get("password") or auto_register_password or ""
                        ),
                        cloudmail_account_id=register_payload.get("cloudmail_account_id")
                        or outcome.get("cloudmail_account_id"),
                        seat_type=SEAT_CODEX,
                        mail_provider=register_payload.get("mail_provider")
                        or outcome.get("mail_provider")
                        or auto_register_mail_provider
                        or None,
                    )
                update_account(
                    registered_email,
                    status=STATUS_PERSONAL,
                    account_type=ACCOUNT_TYPE_FREE,
                    seat_type=SEAT_CODEX,
                    auth_file=auth_session_file,
                    last_active_at=time.time(),
                )

            _append_task_progress(
                task_id,
                gopay_task_payloads_service.gopay_auto_register_done_progress(
                    email=registered_email,
                    current=index,
                    total=total,
                ),
            )
            return registered_email

        def _phone_accounts_for_attempt(index: int) -> list[dict]:
            if not phone_accounts:
                return []
            selected = phone_accounts[(max(1, int(index or 1)) - 1) % len(phone_accounts)]
            return [dict(selected)]

        def _auto_signup_wallet_phone_account(wallet) -> dict:
            account = dict(wallet.as_phone_account() or {})
            account["auto_signup_wallet"] = True
            return account

        def _run_one_gopay_bind(
            bind_email: str,
            bind_account_emails: list[str],
            *,
            selected_phone_accounts: list[dict] | None = None,
            pending_retry_override: int | None = None,
        ) -> dict:
            active_phone_accounts = [
                _rewrite_phone_account_sms_url_for_base(account, gopay_task_public_base_url)
                for account in (selected_phone_accounts or phone_accounts)
            ]
            active_phone_account = active_phone_accounts[0] if active_phone_accounts else {}
            return run_gopay_bind_task(
                email=bind_email,
                checkout_url=checkout_url,
                checkout_ui_mode=checkout_ui_mode,
                phone_number=str(active_phone_account.get("phone_number") or phone_number),
                country_code=str(active_phone_account.get("country_code") or country_code),
                sms_url=str(active_phone_account.get("sms_url") or sms_url),
                gopay_pin=str(active_phone_account.get("gopay_pin") or gopay_pin),
                otp_channel=str(active_phone_account.get("otp_channel") or otp_channel),
                phone_accounts=active_phone_accounts,
                billing_info={
                    "name": billing_name,
                    "country": billing_country,
                    "state": billing_state,
                    "city": billing_city,
                    "zip": billing_zip,
                    "address1": billing_address1,
                    "address2": billing_address2,
                },
                proxy_url=bind_proxy_url,
                proxy_bypass=params.proxy_bypass,
                timeout_seconds=max(120, int(params.timeout_seconds or 900)),
                account_emails=bind_account_emails,
                pending_retry_attempts=pending_retry_attempts
                if pending_retry_override is None
                else pending_retry_override,
                auth_session_refresh_callback=_refresh_gopay_auth_session,
                is_cancelled=cancel_signal.is_cancelled,
                skip_current=skip_current_signal.is_set,
                clear_skip_current=skip_current_signal.clear,
                progress_callback=_gopay_progress,
            )

        def _take_or_register_gopay_wallet_for_bind(
            *,
            index: int,
            total: int,
            wallet_prefetcher=None,
            reusable_wallet=None,
        ):
            auto_wallet = reusable_wallet
            if auto_wallet is None and wallet_prefetcher is not None:
                auto_wallet = wallet_prefetcher.take(index=index)
            if auto_wallet is None:
                auto_wallet = _take_reusable_gopay_wallet_for_bind(index=index, total=total)
            if auto_wallet is None:
                auto_wallet = _register_gopay_wallet_for_bind(index=index, total=total)
            else:
                with gopay_state_lock:
                    if auto_wallet in reusable_gopay_wallets:
                        reusable_gopay_wallets.remove(auto_wallet)
            return _prepare_gopay_wallet_for_bind(auto_wallet, index=index, total=total)

        def _run_one_gopay_bind_with_wallet_retry(
            bind_email: str,
            bind_account_emails: list[str],
            *,
            index: int,
            total: int,
            wallet_prefetcher=None,
            reusable_wallet=None,
            exception_message_prefix: str,
        ) -> tuple[dict, Any | None]:
            max_wallet_attempts = max(1, int(os.environ.get("GOPAY_AUTO_SIGNUP_WALLET_ATTEMPTS", "10") or "10"))
            auto_wallet = reusable_wallet
            last_result: dict = {}
            for wallet_attempt in range(1, max_wallet_attempts + 1):
                try:
                    auto_wallet = _take_or_register_gopay_wallet_for_bind(
                        index=index,
                        total=total,
                        wallet_prefetcher=wallet_prefetcher,
                        reusable_wallet=auto_wallet,
                    )
                    gopay_wallet_prefetch_context.update(
                        {"prefetcher": wallet_prefetcher, "index": index, "total": total, "triggered": False}
                    )
                    try:
                        single_result = dict(
                            _run_one_gopay_bind(
                                bind_email,
                                bind_account_emails,
                                selected_phone_accounts=[_auto_signup_wallet_phone_account(auto_wallet)],
                                pending_retry_override=0,
                            )
                            or {}
                        )
                        _append_task_progress(
                            task_id,
                            gopay_task_payloads_service.gopay_bind_attempt_finished_progress(
                                email=_normalized_email(
                                    single_result.get("email_used") or single_result.get("email") or bind_email
                                ),
                                current=index,
                                total=total,
                                wallet_attempt=wallet_attempt,
                                status=single_result.get("status") or "failed",
                                failure_stage=single_result.get("failure_stage") or "",
                                detail=_compact_log_text(single_result.get("message") or "", limit=220) or "-",
                            ),
                        )
                    finally:
                        gopay_wallet_prefetch_context.update(
                            {"prefetcher": None, "index": 0, "total": 0, "triggered": False}
                        )
                except Exception as exc:
                    if isinstance(exc, (_GoPayWalletSignupRateLimited, _GoPayWalletSignupNetworkError)):
                        raise
                    logger.exception(
                        "[gopay-bind] GoPay auto-signup bind failed: index=%s/%s email=%s",
                        index,
                        total,
                        _safe_email_summary(bind_email),
                    )
                    if isinstance(exc, _GoPayWalletSignupNoNumbers) or _looks_like_gopay_wallet_signup_no_numbers(exc):
                        failure_stage = "gopay_wallet_no_numbers"
                    elif _looks_like_gopay_wallet_signup_provider_error(exc):
                        failure_stage = "gopay_wallet_provider_unavailable"
                    elif isinstance(exc, _GoPayWalletBalanceInsufficientLimit):
                        failure_stage = "gopay_wallet_balance_insufficient"
                    elif "Rekberinaja" in str(exc):
                        failure_stage = "gopay_wallet_funding"
                    else:
                        failure_stage = "post_submit"
                    single_result = gopay_task_payloads_service.gopay_bind_failure_result(
                        failure_stage=failure_stage,
                        message=f"{exception_message_prefix}: {exc}",
                    )
                    if failure_stage in {"gopay_wallet_no_numbers"} and wallet_attempt < max_wallet_attempts:
                        last_result = single_result
                        auto_wallet = None
                        _append_task_progress(
                            task_id,
                            gopay_task_payloads_service.gopay_wallet_signup_retry_same_account_progress(
                                email=bind_email,
                                current=index,
                                total=total,
                                next_attempt=wallet_attempt + 1,
                                max_attempts=max_wallet_attempts,
                                failure_stage=failure_stage,
                                error_summary=_compact_log_text(exc, limit=180),
                            ),
                        )
                        continue

                last_result = single_result
                if not _is_gopay_wallet_bound_elsewhere_result(single_result):
                    if not _is_gopay_wallet_charge_denied_result(single_result):
                        return single_result, auto_wallet
                    _discard_gopay_wallet_charge_denied(auto_wallet, index=index, total=total)
                    auto_wallet = None
                    if wallet_attempt >= max_wallet_attempts:
                        break
                    _append_task_progress(
                        task_id,
                        gopay_task_payloads_service.gopay_wallet_charge_denied_retry_progress(
                            email=bind_email,
                            current=index,
                            total=total,
                            next_attempt=wallet_attempt + 1,
                            max_attempts=max_wallet_attempts,
                        ),
                    )
                    continue

                _discard_gopay_wallet_bound_elsewhere(auto_wallet, index=index, total=total)
                auto_wallet = None
                if wallet_attempt >= max_wallet_attempts:
                    break
                _append_task_progress(
                    task_id,
                    gopay_task_payloads_service.gopay_wallet_already_linked_retry_progress(
                        email=bind_email,
                        current=index,
                        total=total,
                        next_attempt=wallet_attempt + 1,
                        max_attempts=max_wallet_attempts,
                    ),
                )
            return last_result, None

        def _run_auto_register_gopay_batch() -> dict:
            nonlocal email, account_emails
            aggregate_results: list[dict] = []
            successful_emails: list[str] = []
            failed_emails: list[dict] = []
            rejected_emails: list[str] = []
            payment_failed_emails: list[str] = []
            nonzero_blocked_emails: list[str] = []
            blocked_emails: list[str] = []
            registered_emails: list[str] = []
            bind_failed_emails: list[dict] = []
            pending_retry_items: list[dict] = []
            retried_emails: list[str] = []
            last_result: dict = {}
            last_success_email = ""
            auto_register_attempted_count = 0
            reusable_auto_wallet = None
            wallet_prefetcher = _GoPayWalletPrefetcher(total=auto_register_count)

            for index in range(1, auto_register_count + 1):
                if cancel_signal.is_cancelled():
                    break
                auto_register_attempted_count = max(auto_register_attempted_count, index)
                current_email = ""
                auto_wallet = None
                _append_task_progress(
                    task_id,
                    gopay_task_payloads_service.gopay_auto_register_next_progress(
                        current=index,
                        total=auto_register_count,
                    ),
                )
                try:
                    current_email = _register_one_for_gopay(index=index, total=auto_register_count)
                    _append_unique(registered_emails, current_email)
                    email = current_email
                    account_emails = []
                except Exception as exc:
                    logger.exception(
                        "[gopay-bind] auto-register failed before GoPay bind: index=%s/%s", index, auto_register_count
                    )
                    single_result = gopay_task_payloads_service.gopay_auto_register_failed_result(error=exc)
                else:
                    delay_seconds = _gopay_auto_register_bind_delay_seconds()
                    if delay_seconds > 0:
                        _append_task_progress(
                            task_id,
                            gopay_task_payloads_service.gopay_auto_register_bind_wait_progress(
                                email=current_email,
                                current=index,
                                total=auto_register_count,
                                delay_seconds=delay_seconds,
                            ),
                        )
                        time.sleep(delay_seconds)
                    if gopay_auto_signup:
                        try:
                            single_result, auto_wallet = _run_one_gopay_bind_with_wallet_retry(
                                current_email,
                                [],
                                index=index,
                                total=auto_register_count,
                                wallet_prefetcher=wallet_prefetcher,
                                reusable_wallet=reusable_auto_wallet,
                                exception_message_prefix="注册已成功，GoPay 绑定异常",
                            )
                        except _GoPayWalletSignupRateLimited as exc:
                            wallet_prefetcher.close()
                            failed_email = _normalized_email(current_email)
                            return gopay_task_payloads_service.gopay_auto_register_rate_limited_result(
                                failed_email=failed_email,
                                fallback_email=last_success_email or _normalized_email(email),
                                current=index,
                                total=auto_register_count,
                                message=exc,
                                auto_register_results=aggregate_results,
                                registered_emails=registered_emails,
                                successful_emails=successful_emails,
                                failed_emails=failed_emails,
                                bind_failed_emails=bind_failed_emails,
                                pending_retry_emails=[
                                    item["email"] for item in pending_retry_items if item.get("email")
                                ],
                                retried_emails=retried_emails,
                                rejected_emails=rejected_emails,
                                payment_failed_emails=payment_failed_emails,
                                nonzero_blocked_emails=nonzero_blocked_emails,
                                blocked_emails=blocked_emails,
                            )
                        reusable_auto_wallet = None
                    else:
                        try:
                            single_result = dict(
                                _run_one_gopay_bind(
                                    current_email,
                                    [],
                                    selected_phone_accounts=_phone_accounts_for_attempt(index),
                                    pending_retry_override=0,
                                )
                                or {}
                            )
                        except Exception as exc:
                            logger.exception(
                                "[gopay-bind] GoPay bind failed after auto-register success: index=%s/%s email=%s",
                                index,
                                auto_register_count,
                                _safe_email_summary(current_email),
                            )
                            single_result = gopay_task_payloads_service.gopay_auto_register_bind_failure_result(
                                error=exc
                            )
                single_result.setdefault("status", "failed")
                single_result.setdefault("failure_stage", "")
                single_result.setdefault("message", "")
                single_result.setdefault("screenshot_paths", [])
                single_email = _normalized_email(
                    single_result.get("email_used") or single_result.get("email") or current_email
                )
                if single_email:
                    single_result["email_used"] = single_email
                if current_email:
                    single_result.setdefault("register_status", "success")
                single_result.setdefault(
                    "bind_status",
                    "success"
                    if single_result.get("status") == "success"
                    else "failed"
                    if current_email
                    else "not_started",
                )
                if (
                    current_email
                    and single_result.get("status") != "success"
                    and single_result.get("bind_status") == "failed"
                    and not str(single_result.get("message") or "").startswith("注册已成功")
                ):
                    original_message = str(single_result.get("message") or "GoPay 绑定失败")
                    single_result["message"] = f"注册已成功，GoPay 绑定失败: {original_message}"
                single_result["auto_register_index"] = index
                single_result["auto_register_total"] = auto_register_count
                aggregate_results.append(single_result)
                last_result = single_result
                single_failure_stage = str(single_result.get("failure_stage") or "")
                if _is_gopay_wallet_bound_elsewhere_result(single_result):
                    retry_reason = ""
                elif single_failure_stage == "gopay_wallet_network_error":
                    retry_reason = "gopay_wallet_network_error"
                else:
                    retry_reason = _gopay_pending_retry_reason(single_result)
                if (
                    current_email
                    and single_result.get("status") != "success"
                    and retry_reason
                    and pending_retry_attempts > 0
                ):
                    source_stage = _gopay_pending_retry_source_stage(single_result, retry_reason)
                    single_result["bind_status"] = "retry_pending"
                    pending_retry_items.append(
                        gopay_pending_retry_service.pending_retry_item(
                            email=single_email,
                            index=index,
                            phone_accounts=(
                                [_auto_signup_wallet_phone_account(auto_wallet)]
                                if auto_wallet is not None
                                else _phone_accounts_for_attempt(index)
                            ),
                            reason=retry_reason,
                        )
                    )
                    _append_task_progress(
                        task_id,
                        gopay_pending_retry_service.auto_register_pending_retry_queued_progress(
                            email=single_email,
                            current=index,
                            total=auto_register_count,
                            retry_round=1,
                            source_retry_round=0,
                            max_retry_rounds=pending_retry_attempts,
                            reason=retry_reason,
                            pending_retry=len(pending_retry_items),
                            source_stage=source_stage,
                        ),
                    )
                    continue
                if single_result.get("status") != "success":
                    _append_task_progress(
                        task_id,
                        {
                            "stage": (
                                "gopay_auto_register_bind_failed"
                                if single_result.get("register_status") == "success"
                                else "gopay_auto_register_failed"
                            ),
                            "email": single_email,
                            "current": index,
                            "total": auto_register_count,
                            "failure_stage": single_result.get("failure_stage") or "",
                            "register_status": single_result.get("register_status") or "",
                            "bind_status": single_result.get("bind_status") or "",
                            "message": single_result.get("message") or "自动注册 GoPay 失败",
                            "level": "error",
                        },
                    )

                _merge_email_list(single_result, "successful_emails", successful_emails)
                _merge_email_list(single_result, "rejected_emails", rejected_emails)
                _merge_email_list(single_result, "payment_failed_emails", payment_failed_emails)
                _merge_email_list(single_result, "nonzero_blocked_emails", nonzero_blocked_emails)
                _merge_email_list(single_result, "blocked_emails", blocked_emails)
                single_failure_stage = str(single_result.get("failure_stage") or "")
                if single_email and _is_gopay_checkout_not_approved_result(single_result):
                    _append_unique(rejected_emails, single_email)
                if single_email and single_failure_stage in {
                    "browser_charge_guard",
                    "stripe_charge_guard",
                    "midtrans_charge_guard",
                }:
                    _append_unique(nonzero_blocked_emails, single_email)
                if single_email and single_failure_stage == "gopay_payment_process":
                    _append_unique(payment_failed_emails, single_email)
                if single_result.get("status") == "success":
                    if auto_wallet is not None and auto_wallet in reusable_gopay_wallets:
                        reusable_gopay_wallets.remove(auto_wallet)
                    _append_unique(successful_emails, single_email)
                    if single_email:
                        _mark_gopay_success_account(
                            single_email,
                            message=single_result.get("message") or "GoPay 绑定成功",
                            success_checkout_url=single_result.get("checkout_url") or checkout_url or "",
                        )
                    last_success_email = single_email or last_success_email
                else:
                    if auto_wallet is not None and _is_unused_gopay_wallet_result(single_result):
                        reusable_auto_wallet = auto_wallet
                        _preserve_gopay_wallet(auto_wallet)
                    if single_email and single_result.get("register_status") == "success":
                        bind_failed_emails.append(
                            {
                                "email": single_email,
                                "failure_stage": single_result.get("failure_stage") or "",
                                "message": single_result.get("message") or "",
                            }
                        )
                    failed_emails.append(
                        {
                            "email": single_email,
                            "failure_stage": single_result.get("failure_stage") or "",
                            "message": single_result.get("message") or "",
                            "register_status": single_result.get("register_status") or "",
                            "bind_status": single_result.get("bind_status") or "",
                        }
                    )
                if _gopay_balance_insufficient_stop_requested():
                    break

            pending_retry_backoffs = gopay_pending_retry_service.DEFAULT_TASK_PENDING_RETRY_BACKOFFS
            for retry_round in range(1, pending_retry_attempts + 1):
                if _gopay_balance_insufficient_stop_requested():
                    break
                retry_candidates = pending_retry_items[:]
                if not retry_candidates or cancel_signal.is_cancelled():
                    break
                pending_retry_items.clear()
                wait_seconds = gopay_pending_retry_service.pending_retry_wait_seconds(
                    retry_round,
                    pending_retry_backoffs,
                )
                _append_task_progress(
                    task_id,
                    gopay_pending_retry_service.auto_register_pending_retry_wait_progress(
                        retry_round=retry_round,
                        max_retry_rounds=pending_retry_attempts,
                        delay_seconds=wait_seconds,
                        pending_retry=len(retry_candidates),
                    ),
                )
                if wait_seconds > 0:
                    time.sleep(wait_seconds)
                if cancel_signal.is_cancelled():
                    break
                _append_task_progress(
                    task_id,
                    gopay_pending_retry_service.auto_register_pending_retry_started_progress(
                        retry_round=retry_round,
                        max_retry_rounds=pending_retry_attempts,
                        pending_retry=len(retry_candidates),
                    ),
                )
                for retry_offset, item in enumerate(retry_candidates, 1):
                    if cancel_signal.is_cancelled():
                        break
                    retry_email = _normalized_email(item.get("email") or "")
                    retry_index = int(item.get("index") or retry_offset)
                    if not retry_email:
                        continue
                    _append_unique(retried_emails, retry_email)
                    _append_task_progress(
                        task_id,
                        gopay_pending_retry_service.auto_register_pending_retry_account_progress(
                            email=retry_email,
                            attempt=retry_offset,
                            total=len(retry_candidates),
                            current=retry_index,
                            auto_register_total=auto_register_count,
                            retry_round=retry_round,
                            max_retry_rounds=pending_retry_attempts,
                            pending_retry=len(pending_retry_items),
                        ),
                    )
                    try:
                        single_result = dict(
                            _run_one_gopay_bind(
                                retry_email,
                                [],
                                selected_phone_accounts=item.get("phone_accounts")
                                or _phone_accounts_for_attempt(retry_index),
                                pending_retry_override=0,
                            )
                            or {}
                        )
                    except Exception as exc:
                        logger.exception(
                            "[gopay-bind] auto-register pending retry raised: round=%s/%s email=%s",
                            retry_round,
                            pending_retry_attempts,
                            _safe_email_summary(retry_email),
                        )
                        single_result = gopay_pending_retry_service.auto_register_pending_retry_exception_result(exc)
                    single_result.setdefault("status", "failed")
                    single_result.setdefault("failure_stage", "")
                    single_result.setdefault("message", "")
                    single_result.setdefault("screenshot_paths", [])
                    single_email = _normalized_email(
                        single_result.get("email_used") or single_result.get("email") or retry_email
                    )
                    if single_email:
                        single_result["email_used"] = single_email
                    single_result.setdefault("register_status", "success")
                    single_result.setdefault(
                        "bind_status",
                        "success" if single_result.get("status") == "success" else "failed",
                    )
                    if (
                        single_result.get("status") != "success"
                        and single_result.get("bind_status") == "failed"
                        and not str(single_result.get("message") or "").startswith("注册已成功")
                    ):
                        original_message = str(single_result.get("message") or "GoPay 绑定失败")
                        single_result["message"] = f"注册已成功，GoPay 绑定失败: {original_message}"
                    single_result["auto_register_index"] = retry_index
                    single_result["auto_register_total"] = auto_register_count
                    single_result["auto_register_retry_round"] = retry_round
                    aggregate_results.append(single_result)
                    last_result = single_result

                    retry_reason = _gopay_pending_retry_reason(single_result)
                    if (
                        single_result.get("status") != "success"
                        and retry_reason
                        and retry_round < pending_retry_attempts
                    ):
                        pending_retry_items.append(
                            gopay_pending_retry_service.pending_retry_item(
                                email=single_email,
                                index=retry_index,
                                phone_accounts=item.get("phone_accounts") or _phone_accounts_for_attempt(retry_index),
                                reason=retry_reason,
                            )
                        )
                        _append_task_progress(
                            task_id,
                            gopay_pending_retry_service.auto_register_pending_retry_queued_progress(
                                email=single_email,
                                current=retry_index,
                                total=auto_register_count,
                                retry_round=retry_round + 1,
                                source_retry_round=retry_round,
                                max_retry_rounds=pending_retry_attempts,
                                reason=retry_reason,
                                pending_retry=len(pending_retry_items),
                            ),
                        )
                        continue

                    if single_result.get("status") != "success":
                        _append_task_progress(
                            task_id,
                            gopay_pending_retry_service.auto_register_pending_retry_failed_progress(
                                email=single_email,
                                current=retry_index,
                                total=auto_register_count,
                                retry_round=retry_round,
                                max_retry_rounds=pending_retry_attempts,
                                result=single_result,
                            ),
                        )

                    _merge_email_list(single_result, "successful_emails", successful_emails)
                    _merge_email_list(single_result, "rejected_emails", rejected_emails)
                    _merge_email_list(single_result, "payment_failed_emails", payment_failed_emails)
                    _merge_email_list(single_result, "nonzero_blocked_emails", nonzero_blocked_emails)
                    _merge_email_list(single_result, "blocked_emails", blocked_emails)
                    single_failure_stage = str(single_result.get("failure_stage") or "")
                    if single_email and _is_gopay_checkout_not_approved_result(single_result):
                        _append_unique(rejected_emails, single_email)
                    if single_email and single_failure_stage in {
                        "browser_charge_guard",
                        "stripe_charge_guard",
                        "midtrans_charge_guard",
                    }:
                        _append_unique(nonzero_blocked_emails, single_email)
                    if single_email and single_failure_stage == "gopay_payment_process":
                        _append_unique(payment_failed_emails, single_email)
                    if single_result.get("status") == "success":
                        _append_unique(successful_emails, single_email)
                        last_success_email = single_email or last_success_email
                    else:
                        if single_email and single_result.get("register_status") == "success":
                            bind_failed_emails.append(
                                {
                                    "email": single_email,
                                    "failure_stage": single_result.get("failure_stage") or "",
                                    "message": single_result.get("message") or "",
                                }
                            )
                        failed_emails.append(
                            {
                                "email": single_email,
                                "failure_stage": single_result.get("failure_stage") or "",
                                "message": single_result.get("message") or "",
                                "register_status": single_result.get("register_status") or "",
                                "bind_status": single_result.get("bind_status") or "",
                            }
                        )

            wallet_prefetcher.close()

            if not aggregate_results:
                return gopay_task_payloads_service.gopay_auto_register_not_executed_result(
                    cancelled=cancel_signal.is_cancelled()
                )

            success_set = {_normalized_email(item) for item in successful_emails if _normalized_email(item)}
            failed_emails = _dedupe_failed_email_results(
                [item for item in failed_emails if _normalized_email(item.get("email")) not in success_set]
            )
            bind_failed_emails = _dedupe_failed_email_results(
                [item for item in bind_failed_emails if _normalized_email(item.get("email")) not in success_set]
            )
            rejected_emails = [item for item in rejected_emails if _normalized_email(item) not in success_set]
            payment_failed_emails = [
                item for item in payment_failed_emails if _normalized_email(item) not in success_set
            ]
            nonzero_blocked_emails = [
                item for item in nonzero_blocked_emails if _normalized_email(item) not in success_set
            ]
            blocked_emails = [item for item in blocked_emails if _normalized_email(item) not in success_set]

            success_count = len(successful_emails)
            attempted_count = auto_register_attempted_count
            aggregate_status = (
                "success" if success_count else ("cancelled" if cancel_signal.is_cancelled() else "failed")
            )
            failure_stage = ""
            if success_count and failed_emails:
                failure_stage = "partial_failed"
            elif not success_count:
                first_failed_stage = ""
                for failed_item in failed_emails:
                    if isinstance(failed_item, dict):
                        first_failed_stage = str(failed_item.get("failure_stage") or "")
                        if first_failed_stage:
                            break
                failure_stage = first_failed_stage or last_result.get("failure_stage") or "gopay_auto_register"
            message = f"自动注册 GoPay 绑定完成: 成功 {success_count}/{auto_register_count} 个账号"
            if failed_emails:
                message += f"，失败 {len(failed_emails)} 个"
            if cancel_signal.is_cancelled() and attempted_count < auto_register_count:
                message += "，任务已取消"

            result_payload = dict(last_result)
            result_payload.update(
                {
                    "status": aggregate_status,
                    "failure_stage": failure_stage,
                    "message": message,
                    "auto_register_results": aggregate_results,
                    "auto_register_count": auto_register_count,
                    "auto_register_attempted": attempted_count,
                    "registered_emails": registered_emails,
                    "successful_emails": successful_emails,
                    "failed_emails": failed_emails,
                    "bind_failed_emails": bind_failed_emails,
                    "pending_retry_emails": [item["email"] for item in pending_retry_items if item.get("email")],
                    "retried_emails": retried_emails,
                    "rejected_emails": rejected_emails,
                    "payment_failed_emails": payment_failed_emails,
                    "nonzero_blocked_emails": nonzero_blocked_emails,
                    "blocked_emails": blocked_emails,
                    "email_used": last_success_email
                    or (successful_emails[-1] if successful_emails else "")
                    or _normalized_email(last_result.get("email_used") or email),
                }
            )
            return result_payload

        def _run_gopay_auto_signup_existing_accounts_batch_parallel(candidates: list[str]) -> dict:
            total = len(candidates)
            aggregate_results: list[dict] = []
            attempted_emails: list[str] = []
            successful_emails: list[str] = []
            retried_emails: list[str] = []
            rejected_emails: list[str] = []
            payment_failed_emails: list[str] = []
            nonzero_blocked_emails: list[str] = []
            blocked_emails: list[str] = []
            failed_emails: list[dict] = []
            pending_retry_items: list[dict[str, Any]] = []
            last_result: dict = {}
            wallet_signup_hard_stop = False

            _append_task_progress(
                task_id,
                gopay_task_payloads_service.gopay_parallel_started_progress(
                    total=total,
                    concurrency=_current_gopay_concurrency(),
                ),
            )

            def _worker(item: tuple[int, Any, int, int, queue.Queue | int]) -> tuple[int, str, int, dict, Any | None]:
                index, candidate_payload, round_total, retry_round, worker_slots = item
                worker_slots_is_queue = hasattr(worker_slots, "get") and hasattr(worker_slots, "put")
                worker_index = int(worker_slots.get() if worker_slots_is_queue else worker_slots)
                worker_label = f"worker-{worker_index}" if worker_index > 0 else ""
                if worker_label:
                    gopay_worker_context.label = worker_label
                    gopay_worker_context.index = worker_index
                    _task_context.gopay_worker_label = worker_label
                    _task_context.gopay_worker_index = worker_index
                reusable_wallet = None
                if isinstance(candidate_payload, dict):
                    candidate_email = str(candidate_payload.get("email") or "")
                    reusable_wallet = candidate_payload.get("wallet")
                else:
                    candidate_email = str(candidate_payload or "")
                normalized_candidate = _normalized_email(candidate_email)
                try:
                    if not normalized_candidate:
                        return (
                            index,
                            "",
                            retry_round,
                            gopay_task_payloads_service.gopay_invalid_email_result(),
                            None,
                        )
                    if cancel_signal.is_cancelled():
                        return (
                            index,
                            normalized_candidate,
                            retry_round,
                            gopay_task_payloads_service.gopay_cancelled_result(),
                            None,
                        )
                    _append_task_progress(
                        task_id,
                        gopay_task_payloads_service.gopay_parallel_account_progress(
                            email=normalized_candidate,
                            current=index,
                            total=round_total,
                            retry_round=retry_round,
                            max_retry_rounds=pending_retry_attempts,
                            worker_fields=_gopay_worker_progress_fields(),
                        ),
                    )
                    single_result, auto_wallet = _run_one_gopay_bind_with_wallet_retry(
                        normalized_candidate,
                        [],
                        index=index,
                        total=round_total,
                        wallet_prefetcher=None,
                        reusable_wallet=reusable_wallet,
                        exception_message_prefix="GoPay 自动注册后绑定异常",
                    )
                    return index, normalized_candidate, retry_round, single_result, auto_wallet
                finally:
                    if worker_label:
                        gopay_worker_context.label = ""
                        gopay_worker_context.index = 0
                        _task_context.gopay_worker_label = ""
                        _task_context.gopay_worker_index = 0
                    if worker_slots_is_queue:
                        worker_slots.put(worker_index)

            def _record_parallel_result(
                *,
                index: int,
                round_total: int,
                retry_round: int,
                normalized_candidate: str,
                single_result: dict,
                auto_wallet: Any | None,
            ) -> None:
                nonlocal last_result
                single_result = dict(single_result or {})
                single_result.setdefault("status", "failed")
                single_result.setdefault("failure_stage", "")
                single_result.setdefault("message", "")
                single_result.setdefault("screenshot_paths", [])
                single_email = _normalized_email(
                    single_result.get("email_used") or single_result.get("email") or normalized_candidate
                )
                if single_email:
                    single_result["email_used"] = single_email
                single_result["auto_signup_account_index"] = index
                single_result["auto_signup_account_total"] = round_total
                single_result["retry_round"] = retry_round
                aggregate_results.append(single_result)
                last_result = single_result

                _merge_email_list(single_result, "successful_emails", successful_emails)
                _merge_email_list(single_result, "rejected_emails", rejected_emails)
                _merge_email_list(single_result, "payment_failed_emails", payment_failed_emails)
                _merge_email_list(single_result, "nonzero_blocked_emails", nonzero_blocked_emails)
                _merge_email_list(single_result, "blocked_emails", blocked_emails)
                single_failure_stage = str(single_result.get("failure_stage") or "")
                if single_email and _is_gopay_checkout_not_approved_result(single_result):
                    _append_unique(rejected_emails, single_email)
                if single_email and single_failure_stage in {
                    "browser_charge_guard",
                    "stripe_charge_guard",
                    "midtrans_charge_guard",
                }:
                    _append_unique(nonzero_blocked_emails, single_email)
                if single_email and single_failure_stage == "gopay_payment_process":
                    _append_unique(payment_failed_emails, single_email)

                if auto_wallet is not None and _is_no_transfer_balance_pending_result(single_result):
                    _discard_gopay_wallet_for_balance_not_ready(auto_wallet, index=index, total=round_total)

                if single_result.get("status") == "success":
                    if auto_wallet is not None:

                        def _should_remove_wallet_retry_item(item: dict[str, Any]) -> bool:
                            if item.get("wallet") is not auto_wallet:
                                return False
                            if _normalized_email(item.get("email") or "") == single_email:
                                return True
                            return int(item.get("retry_round") or 0) <= 1

                        pending_retry_items[:] = [
                            item for item in pending_retry_items if not _should_remove_wallet_retry_item(item)
                        ]
                        scheduled_retry_items[:] = [
                            item for item in scheduled_retry_items if not _should_remove_wallet_retry_item(item)
                        ]
                    _append_unique(successful_emails, single_email)
                    if single_email:
                        _mark_gopay_success_account(
                            single_email,
                            message=single_result.get("message") or "GoPay 绑定成功",
                            success_checkout_url=single_result.get("checkout_url") or checkout_url or "",
                        )
                    _append_task_progress(
                        task_id,
                        gopay_task_payloads_service.gopay_auto_signup_account_success_progress(
                            email=single_email,
                            current=index,
                            total=round_total,
                            retry_round=retry_round,
                            max_retry_rounds=pending_retry_attempts,
                            successful_count=len(successful_emails),
                            message=f"GoPay 自动注册绑定账号成功: {single_email} ({index}/{round_total})",
                            success_progress_fields=_gopay_success_progress_fields(),
                        ),
                    )
                    return

                if auto_wallet is not None and (
                    _is_unused_gopay_wallet_result(single_result)
                    or _is_no_transfer_balance_pending_result(single_result)
                ):
                    _preserve_gopay_wallet(auto_wallet)

                if _is_chatgpt_user_paid_result(single_result):
                    paid_success = _as_chatgpt_user_paid_success(
                        single_result,
                        checkout_url=str(single_result.get("checkout_url") or checkout_url or ""),
                        billing_info=single_result.get("billing_info")
                        if isinstance(single_result.get("billing_info"), dict)
                        else None,
                    )
                    _append_unique(successful_emails, single_email)
                    if single_email:
                        _mark_gopay_success_account(
                            single_email,
                            message=paid_success.get("message") or "ChatGPT account is already Plus",
                            success_checkout_url=paid_success.get("checkout_url") or checkout_url or "",
                        )
                    _append_task_progress(
                        task_id,
                        gopay_task_payloads_service.gopay_auto_signup_account_success_progress(
                            email=single_email,
                            current=index,
                            total=round_total,
                            retry_round=retry_round,
                            max_retry_rounds=pending_retry_attempts,
                            successful_count=len(successful_emails),
                            message=f"GoPay account is already Plus, counted as success: {single_email} ({index}/{round_total})",
                            success_progress_fields=_gopay_success_progress_fields(),
                            position_field="current",
                        ),
                    )
                    return

                failed_emails.append(
                    {
                        "email": single_email,
                        "failure_stage": single_result.get("failure_stage") or "",
                        "message": single_result.get("message") or "",
                        "retry_round": retry_round,
                    }
                )
                retry_reason = _gopay_pending_retry_reason(single_result)
                if not retry_reason and _is_gopay_wallet_bound_elsewhere_result(single_result):
                    retry_reason = "gopay_already_linked"
                account_side_failure = _is_gopay_account_side_failure_result(single_result, retry_reason)
                wallet_signup_failure = _is_gopay_wallet_signup_failure_result(single_result, retry_reason)
                if wallet_signup_failure:
                    _append_task_progress(
                        task_id,
                        gopay_task_payloads_service.gopay_wallet_signup_failed_no_account_retry_progress(
                            email=single_email,
                            retry_round=retry_round,
                            max_retry_rounds=pending_retry_attempts,
                            reason=retry_reason,
                            failure_stage=single_result.get("failure_stage") or "",
                        ),
                    )
                if (
                    account_side_failure
                    and auto_wallet is not None
                    and not _is_gopay_wallet_bound_elsewhere_result(single_result)
                ):
                    _preserve_gopay_wallet(auto_wallet)
                    _append_task_progress(
                        task_id,
                        gopay_task_payloads_service.gopay_account_failed_wallet_preserved_progress(
                            email=single_email,
                            retry_round=retry_round,
                            max_retry_rounds=pending_retry_attempts,
                            reason=retry_reason,
                            failure_stage=single_result.get("failure_stage") or "",
                        ),
                    )
                if (
                    single_email
                    and retry_reason
                    and not account_side_failure
                    and not wallet_signup_failure
                    and retry_round < pending_retry_attempts
                ):
                    retry_source_stage = _gopay_pending_retry_source_stage(single_result, retry_reason)
                    failure_stage = str(single_result.get("failure_stage") or "")
                    failure_detail = _compact_log_text(single_result.get("message") or "", limit=220)
                    retry_wallet = (
                        auto_wallet
                        if auto_wallet is not None
                        and not _is_no_transfer_balance_pending_result(single_result)
                        and not _is_gopay_wallet_bound_elsewhere_result(single_result)
                        else None
                    )
                    pending_retry_items.append(
                        gopay_pending_retry_service.pending_retry_item(
                            email=single_email,
                            index=index,
                            reason=retry_reason,
                            retry_round=retry_round,
                            source_stage=retry_source_stage,
                            failure_stage=failure_stage,
                            message=failure_detail,
                            wallet=retry_wallet,
                        )
                    )
                    logger.warning(
                        "[gopay-bind] parallel account queued for retry: email=%s reason=%s source_stage=%s failure_stage=%s reuse_wallet=%s message=%s",
                        _safe_email_summary(single_email),
                        retry_reason,
                        retry_source_stage,
                        failure_stage,
                        bool(retry_wallet),
                        failure_detail,
                    )
                    _append_task_progress(
                        task_id,
                        gopay_pending_retry_service.parallel_pending_retry_queued_progress(
                            email=single_email,
                            retry_round=retry_round + 1,
                            source_retry_round=retry_round,
                            max_retry_rounds=pending_retry_attempts,
                            reason=retry_reason,
                            source_stage=retry_source_stage,
                            failure_stage=failure_stage,
                            reuse_wallet=bool(retry_wallet),
                            pending_retry=len(pending_retry_items),
                            detail=failure_detail,
                        ),
                    )
                _append_task_progress(
                    task_id,
                    gopay_task_payloads_service.gopay_auto_signup_account_failed_progress(
                        email=single_email,
                        current=index,
                        total=round_total,
                        retry_round=retry_round,
                        max_retry_rounds=pending_retry_attempts,
                        failure_stage=single_result.get("failure_stage") or "",
                        message=single_result.get("message") or "GoPay 自动注册绑定失败",
                    ),
                )

            def _candidate_payload_email(candidate_payload: Any) -> str:
                if isinstance(candidate_payload, dict):
                    return _normalized_email(candidate_payload.get("email") or "")
                return _normalized_email(candidate_payload)

            def _run_parallel_round(round_candidates: list[Any], *, retry_round: int = 0) -> None:
                round_total = len(round_candidates)
                if round_total <= 0:
                    return
                with ThreadPoolExecutor(
                    max_workers=max(1, min(gopay_concurrency, round_total)), thread_name_prefix="gopay-bind"
                ) as executor:
                    worker_count = max(1, min(gopay_concurrency, round_total))
                    worker_slots: queue.Queue[int] = queue.Queue()
                    for worker_index in range(1, worker_count + 1):
                        worker_slots.put(worker_index)
                    futures = {
                        executor.submit(_worker, (index, candidate_payload, round_total, retry_round, worker_slots)): (
                            index,
                            _candidate_payload_email(candidate_payload),
                        )
                        for index, candidate_payload in enumerate(round_candidates, 1)
                        if _candidate_payload_email(candidate_payload)
                    }
                    for _future, (_index, _email) in futures.items():
                        if _email:
                            _append_unique(attempted_emails, _email)
                            if retry_round:
                                _append_unique(retried_emails, _email)
                    for future in as_completed(futures):
                        index, normalized_candidate = futures[future]
                        auto_wallet = None
                        try:
                            index, normalized_candidate, result_retry_round, single_result, auto_wallet = (
                                future.result()
                            )
                        except _GoPayWalletSignupRateLimited as exc:
                            result_retry_round = retry_round
                            single_result = gopay_task_payloads_service.gopay_bind_failure_result(
                                failure_stage="gopay_wallet_rate_limited",
                                message=exc,
                            )
                        except _GoPayWalletSignupNetworkError as exc:
                            result_retry_round = retry_round
                            single_result = gopay_task_payloads_service.gopay_bind_failure_result(
                                failure_stage="gopay_wallet_network_error",
                                message=exc,
                            )
                        except _GoPayWalletSignupNoNumbers as exc:
                            result_retry_round = retry_round
                            single_result = gopay_task_payloads_service.gopay_bind_failure_result(
                                failure_stage="gopay_wallet_no_numbers",
                                message=exc,
                            )
                        except Exception as exc:
                            result_retry_round = retry_round
                            logger.exception(
                                "[gopay-bind] parallel GoPay auto-signup bind failed: index=%s/%s email=%s retry_round=%s",
                                index,
                                round_total,
                                _safe_email_summary(normalized_candidate),
                                retry_round,
                            )
                            single_result = gopay_task_payloads_service.gopay_bind_failure_result(
                                failure_stage="post_submit",
                                message=f"GoPay 自动注册后绑定异常: {exc}",
                            )
                        _record_parallel_result(
                            index=index,
                            round_total=round_total,
                            retry_round=result_retry_round,
                            normalized_candidate=normalized_candidate,
                            single_result=single_result,
                            auto_wallet=auto_wallet,
                        )

            scheduled_retry_items: list[dict[str, Any]] = []

            def _pending_retry_emails() -> list[str]:
                emails: list[str] = []
                for item in [*pending_retry_items, *scheduled_retry_items]:
                    candidate_email = _normalized_email(item.get("email") or "")
                    if candidate_email:
                        _append_unique(emails, candidate_email)
                return emails

            def _run_parallel_dynamic() -> None:
                retry_backoffs = [60.0, 120.0]

                def retry_wait_seconds(retry_round: int) -> float:
                    return retry_backoffs[min(max(0, retry_round - 1), len(retry_backoffs) - 1)]

                def schedule_pending_retries() -> None:
                    while pending_retry_items:
                        item = pending_retry_items.pop(0)
                        retry_round = int(item.get("retry_round") or 0) + 1
                        if retry_round > pending_retry_attempts:
                            continue
                        wait_seconds = retry_wait_seconds(retry_round)
                        scheduled = dict(item)
                        scheduled["retry_round"] = retry_round
                        scheduled["due_at"] = time.time() + wait_seconds
                        scheduled_retry_items.append(scheduled)
                        retry_email = _normalized_email(scheduled.get("email") or "")
                        _append_task_progress(
                            task_id,
                            gopay_pending_retry_service.parallel_pending_retry_wait_progress(
                                email=retry_email,
                                retry_round=retry_round,
                                max_retry_rounds=pending_retry_attempts,
                                pending_retry=len(_pending_retry_emails()),
                                delay_seconds=wait_seconds,
                            ),
                        )

                def pop_due_retry() -> dict[str, Any] | None:
                    if not scheduled_retry_items:
                        return None
                    scheduled_retry_items.sort(
                        key=lambda item: (float(item.get("due_at") or 0), int(item.get("retry_round") or 0))
                    )
                    if float(scheduled_retry_items[0].get("due_at") or 0) <= time.time():
                        return scheduled_retry_items.pop(0)
                    return None

                def next_retry_due_in() -> float | None:
                    if not scheduled_retry_items:
                        return None
                    return max(0.0, min(float(item.get("due_at") or 0) for item in scheduled_retry_items) - time.time())

                def finish_future(
                    future, *, index: int, round_total: int, retry_round: int, normalized_candidate: str
                ) -> None:
                    nonlocal wallet_signup_hard_stop
                    auto_wallet = None
                    try:
                        index, normalized_candidate, result_retry_round, single_result, auto_wallet = future.result()
                    except _GoPayWalletSignupRateLimited as exc:
                        wallet_signup_hard_stop = True
                        result_retry_round = retry_round
                        single_result = gopay_task_payloads_service.gopay_bind_failure_result(
                            failure_stage="gopay_wallet_rate_limited",
                            message=exc,
                        )
                    except _GoPayWalletSignupNetworkError as exc:
                        wallet_signup_hard_stop = True
                        result_retry_round = retry_round
                        single_result = gopay_task_payloads_service.gopay_bind_failure_result(
                            failure_stage="gopay_wallet_network_error",
                            message=exc,
                        )
                    except _GoPayWalletSignupNoNumbers as exc:
                        result_retry_round = retry_round
                        single_result = gopay_task_payloads_service.gopay_bind_failure_result(
                            failure_stage="gopay_wallet_no_numbers",
                            message=exc,
                        )
                    except Exception as exc:
                        result_retry_round = retry_round
                        logger.exception(
                            "[gopay-bind] parallel GoPay auto-signup bind failed: index=%s/%s email=%s retry_round=%s",
                            index,
                            round_total,
                            _safe_email_summary(normalized_candidate),
                            retry_round,
                        )
                        single_result = gopay_task_payloads_service.gopay_bind_failure_result(
                            failure_stage="post_submit",
                            message=f"GoPay 自动注册后绑定异常: {exc}",
                        )
                    _record_parallel_result(
                        index=index,
                        round_total=round_total,
                        retry_round=result_retry_round,
                        normalized_candidate=normalized_candidate,
                        single_result=single_result,
                        auto_wallet=auto_wallet,
                    )
                    schedule_pending_retries()

                initial_items: list[tuple[int, Any, int, int]] = [
                    (index, candidate_payload, total, 0)
                    for index, candidate_payload in enumerate(candidates, 1)
                    if _candidate_payload_email(candidate_payload)
                ]
                queued_emails = {
                    _candidate_payload_email(item[1]) for item in initial_items if _candidate_payload_email(item[1])
                }
                next_index = len(initial_items) + 1
                active_worker_indexes: set[int] = set()
                active: dict[Any, tuple[int, int, int, str, int]] = {}

                def acquire_worker_index() -> int:
                    for worker_index in range(1, _current_gopay_concurrency() + 1):
                        if worker_index not in active_worker_indexes:
                            active_worker_indexes.add(worker_index)
                            return worker_index
                    return 0

                def release_worker_index(worker_index: int) -> None:
                    if worker_index > 0:
                        active_worker_indexes.discard(worker_index)

                def append_runtime_accounts() -> None:
                    nonlocal next_index
                    added = _drain_runtime_added_account_emails(queued_emails)
                    if not added:
                        return
                    round_total = _runtime_account_total(total)
                    for added_email in added:
                        initial_items.append((next_index, added_email, round_total, 0))
                        next_index += 1
                    _append_task_progress(
                        task_id,
                        gopay_task_payloads_service.gopay_runtime_accounts_added_progress(
                            added=len(added),
                            added_emails=added,
                            pending=len(initial_items),
                            total=_runtime_account_total(total),
                        ),
                    )

                def submit_item(executor: ThreadPoolExecutor, item: tuple[int, Any, int, int]) -> None:
                    index, candidate_payload, round_total, retry_round = item
                    candidate_email = _candidate_payload_email(candidate_payload)
                    if not candidate_email:
                        return
                    worker_index = acquire_worker_index()
                    future = executor.submit(
                        _worker, (index, candidate_payload, round_total, retry_round, worker_index)
                    )
                    active[future] = (index, round_total, retry_round, candidate_email, worker_index)
                    _append_unique(attempted_emails, candidate_email)
                    if retry_round:
                        _append_unique(retried_emails, candidate_email)
                        _append_task_progress(
                            task_id,
                            gopay_pending_retry_service.parallel_pending_retry_started_progress(
                                email=candidate_email,
                                retry_round=retry_round,
                                max_retry_rounds=pending_retry_attempts,
                                pending_retry=len(_pending_retry_emails()),
                                concurrency=_current_gopay_concurrency(),
                            ),
                        )

                def submit_available(executor: ThreadPoolExecutor) -> None:
                    append_runtime_accounts()
                    worker_count = _current_gopay_concurrency()
                    while (
                        len(active) < worker_count
                        and not wallet_signup_hard_stop
                        and not cancel_signal.is_cancelled()
                        and not _gopay_balance_insufficient_stop_requested()
                    ):
                        if initial_items:
                            submit_item(executor, initial_items.pop(0))
                            continue
                        retry_item = pop_due_retry()
                        if not retry_item:
                            break
                        retry_email = _normalized_email(retry_item.get("email") or "")
                        if not retry_email:
                            continue
                        submit_item(
                            executor,
                            (
                                int(retry_item.get("index") or 1),
                                {"email": retry_email, "wallet": retry_item.get("wallet")},
                                total,
                                int(retry_item.get("retry_round") or 0),
                            ),
                        )

                executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="gopay-bind")
                try:
                    while (
                        (initial_items or active or pending_retry_items or scheduled_retry_items)
                        and not wallet_signup_hard_stop
                        and not cancel_signal.is_cancelled()
                        and not _gopay_balance_insufficient_stop_requested()
                    ):
                        append_runtime_accounts()
                        worker_count = _current_gopay_concurrency()
                        schedule_pending_retries()
                        submit_available(executor)
                        if not active:
                            next_due = next_retry_due_in()
                            if next_due is None:
                                break
                            cancel_event = _task_cancel_signals.get(task_id)
                            wait_seconds = min(float(next_due or 0.0), 1.0)
                            if cancel_event is not None:
                                if cancel_event.wait(wait_seconds):
                                    break
                            elif wait_seconds > 0:
                                time.sleep(wait_seconds)
                            continue
                        timeout = None
                        if len(active) < worker_count and not initial_items:
                            timeout = next_retry_due_in()
                        if timeout is None:
                            timeout = 1.0
                        else:
                            timeout = min(float(timeout or 0.0), 1.0)
                        done, _ = wait(active.keys(), timeout=timeout, return_when=FIRST_COMPLETED)
                        if cancel_signal.is_cancelled():
                            break
                        if not done:
                            if _gopay_balance_insufficient_stop_requested():
                                break
                            continue
                        for future in done:
                            index, round_total, retry_round, normalized_candidate, worker_index = active.pop(future)
                            release_worker_index(worker_index)
                            finish_future(
                                future,
                                index=index,
                                round_total=round_total,
                                retry_round=retry_round,
                                normalized_candidate=normalized_candidate,
                            )
                        if _gopay_balance_insufficient_stop_requested():
                            break
                finally:
                    if cancel_signal.is_cancelled():
                        for future in list(active.keys()):
                            future.cancel()
                        _append_task_progress(
                            task_id,
                            gopay_task_payloads_service.gopay_parallel_cancelled_progress(
                                active=len(active),
                                pending=len(initial_items) + len(pending_retry_items) + len(scheduled_retry_items),
                            ),
                        )
                        executor.shutdown(wait=False, cancel_futures=True)
                    else:
                        executor.shutdown(wait=True)

            _run_parallel_dynamic()

            pending_retry_backoffs = gopay_pending_retry_service.DEFAULT_TASK_PENDING_RETRY_BACKOFFS
            for retry_round in range(0):
                if _gopay_balance_insufficient_stop_requested():
                    break
                retry_candidates = pending_retry_items[:]
                if not retry_candidates or cancel_signal.is_cancelled():
                    break
                pending_retry_items.clear()
                wait_seconds = gopay_pending_retry_service.pending_retry_wait_seconds(
                    retry_round,
                    pending_retry_backoffs,
                )
                _append_task_progress(
                    task_id,
                    gopay_pending_retry_service.parallel_pending_retry_wait_progress(
                        retry_round=retry_round,
                        max_retry_rounds=pending_retry_attempts,
                        pending_retry=len(retry_candidates),
                        delay_seconds=wait_seconds,
                    ),
                )
                cancel_event = _task_cancel_signals.get(task_id)
                if cancel_event is not None:
                    if cancel_event.wait(wait_seconds):
                        break
                elif wait_seconds > 0:
                    # Fallback for unexpected task context loss: keep the task cancellable.
                    deadline = time.time() + wait_seconds
                    while time.time() < deadline:
                        if cancel_signal.is_cancelled():
                            break
                        time.sleep(min(1.0, max(0.0, deadline - time.time())))
                    if cancel_signal.is_cancelled():
                        break
                _append_task_progress(
                    task_id,
                    gopay_pending_retry_service.parallel_pending_retry_started_progress(
                        retry_round=retry_round,
                        max_retry_rounds=pending_retry_attempts,
                        pending_retry=len(retry_candidates),
                        concurrency=gopay_concurrency,
                    ),
                )
                _run_parallel_round(retry_candidates, retry_round=retry_round)

            if not aggregate_results:
                return gopay_task_payloads_service.gopay_auto_signup_not_executed_result(
                    cancelled=cancel_signal.is_cancelled(),
                    attempted_emails=attempted_emails,
                    failed_emails=failed_emails,
                )

            success_set = {_normalized_email(item) for item in successful_emails if _normalized_email(item)}
            pending_retry_emails = _pending_retry_emails()
            pending_retry_set = {_normalized_email(item) for item in pending_retry_emails if _normalized_email(item)}
            failed_emails = _dedupe_failed_email_results(
                [
                    item
                    for item in failed_emails
                    if _normalized_email(item.get("email")) not in success_set
                    and _normalized_email(item.get("email")) not in pending_retry_set
                ]
            )
            rejected_emails = [item for item in rejected_emails if _normalized_email(item) not in success_set]
            payment_failed_emails = [
                item for item in payment_failed_emails if _normalized_email(item) not in success_set
            ]
            nonzero_blocked_emails = [
                item for item in nonzero_blocked_emails if _normalized_email(item) not in success_set
            ]
            blocked_emails = [item for item in blocked_emails if _normalized_email(item) not in success_set]

            success_count = len(successful_emails)
            attempted_count = len(attempted_emails)
            final_total = _runtime_account_total(total)
            aggregate_status = (
                "success" if success_count else ("cancelled" if cancel_signal.is_cancelled() else "failed")
            )
            failure_stage = ""
            if success_count and failed_emails:
                failure_stage = "partial_failed"
            elif not success_count:
                first_failed_stage = ""
                for failed_item in failed_emails:
                    if isinstance(failed_item, dict):
                        first_failed_stage = str(failed_item.get("failure_stage") or "")
                        if first_failed_stage:
                            break
                failure_stage = (
                    first_failed_stage
                    or last_result.get("failure_stage")
                    or ("cancelled" if cancel_signal.is_cancelled() else "gopay_auto_signup")
                )
            message = f"GoPay 自动注册绑定完成: 成功 {success_count}/{final_total} 个账号"
            if failed_emails:
                message += f"，失败 {len(failed_emails)} 个"
            if cancel_signal.is_cancelled() and attempted_count < final_total:
                message += "，任务已取消"

            result_payload = dict(last_result)
            result_payload.update(
                {
                    "status": aggregate_status,
                    "failure_stage": failure_stage,
                    "message": message,
                    "auto_signup_account_results": aggregate_results,
                    "attempted_emails": attempted_emails,
                    "successful_emails": successful_emails,
                    "rejected_emails": rejected_emails,
                    "payment_failed_emails": payment_failed_emails,
                    "nonzero_blocked_emails": nonzero_blocked_emails,
                    "blocked_emails": blocked_emails,
                    "failed_emails": failed_emails,
                    "pending_retry_emails": pending_retry_emails,
                    "retried_emails": retried_emails,
                    "concurrency": _current_gopay_concurrency(),
                    "email_used": (successful_emails[-1] if successful_emails else "")
                    or _normalized_email(last_result.get("email_used") or email),
                }
            )
            return result_payload

        def _run_gopay_auto_signup_existing_accounts_batch() -> dict:
            candidates = account_emails[:] if account_emails else [email]
            if len(candidates) > 1:
                return _run_gopay_auto_signup_existing_accounts_batch_parallel(candidates)
            aggregate_results: list[dict] = []
            attempted_emails: list[str] = []
            successful_emails: list[str] = []
            rejected_emails: list[str] = []
            payment_failed_emails: list[str] = []
            nonzero_blocked_emails: list[str] = []
            blocked_emails: list[str] = []
            failed_emails: list[dict] = []
            last_result: dict = {}
            reusable_auto_wallet = None
            wallet_prefetcher = _GoPayWalletPrefetcher(total=len(candidates))

            for index, candidate_email in enumerate(candidates, 1):
                if cancel_signal.is_cancelled():
                    break
                normalized_candidate = _normalized_email(candidate_email)
                if not normalized_candidate:
                    continue
                _append_unique(attempted_emails, normalized_candidate)
                _append_task_progress(
                    task_id,
                    gopay_task_payloads_service.gopay_auto_signup_account_progress(
                        email=normalized_candidate,
                        current=index,
                        total=len(candidates),
                    ),
                )

                auto_wallet = None
                try:
                    single_result, auto_wallet = _run_one_gopay_bind_with_wallet_retry(
                        normalized_candidate,
                        [],
                        index=index,
                        total=len(candidates),
                        wallet_prefetcher=wallet_prefetcher,
                        reusable_wallet=reusable_auto_wallet,
                        exception_message_prefix="GoPay 自动注册后绑定异常",
                    )
                except _GoPayWalletSignupRateLimited as exc:
                    wallet_prefetcher.close()
                    return gopay_task_payloads_service.gopay_auto_signup_rate_limited_result(
                        email=normalized_candidate,
                        current=index,
                        total=len(candidates),
                        message=exc,
                        auto_signup_account_results=aggregate_results,
                        attempted_emails=attempted_emails,
                        successful_emails=successful_emails,
                        rejected_emails=rejected_emails,
                        payment_failed_emails=payment_failed_emails,
                        nonzero_blocked_emails=nonzero_blocked_emails,
                        blocked_emails=blocked_emails,
                        failed_emails=failed_emails,
                    )
                reusable_auto_wallet = None

                single_result.setdefault("status", "failed")
                single_result.setdefault("failure_stage", "")
                single_result.setdefault("message", "")
                single_result.setdefault("screenshot_paths", [])
                single_email = _normalized_email(
                    single_result.get("email_used") or single_result.get("email") or normalized_candidate
                )
                if single_email:
                    single_result["email_used"] = single_email
                single_result["auto_signup_account_index"] = index
                single_result["auto_signup_account_total"] = len(candidates)
                aggregate_results.append(single_result)
                last_result = single_result

                _merge_email_list(single_result, "successful_emails", successful_emails)
                _merge_email_list(single_result, "rejected_emails", rejected_emails)
                _merge_email_list(single_result, "payment_failed_emails", payment_failed_emails)
                _merge_email_list(single_result, "nonzero_blocked_emails", nonzero_blocked_emails)
                _merge_email_list(single_result, "blocked_emails", blocked_emails)
                single_failure_stage = str(single_result.get("failure_stage") or "")
                if single_email and _is_gopay_checkout_not_approved_result(single_result):
                    _append_unique(rejected_emails, single_email)
                if single_email and single_failure_stage in {
                    "browser_charge_guard",
                    "stripe_charge_guard",
                    "midtrans_charge_guard",
                }:
                    _append_unique(nonzero_blocked_emails, single_email)
                if single_email and single_failure_stage == "gopay_payment_process":
                    _append_unique(payment_failed_emails, single_email)

                if auto_wallet is not None and _is_no_transfer_balance_pending_result(single_result):
                    _discard_gopay_wallet_for_balance_not_ready(auto_wallet, index=index, total=len(candidates))

                if single_result.get("status") == "success":
                    _append_unique(successful_emails, single_email)
                    if single_email:
                        _mark_gopay_success_account(
                            single_email,
                            message=single_result.get("message") or "GoPay 绑定成功",
                            success_checkout_url=single_result.get("checkout_url") or checkout_url or "",
                        )
                    _append_task_progress(
                        task_id,
                        gopay_task_payloads_service.gopay_auto_signup_account_success_progress(
                            email=single_email,
                            current=index,
                            total=len(candidates),
                            successful_count=len(successful_emails),
                            message=f"GoPay 自动注册绑定账号成功: {single_email} ({index}/{len(candidates)})",
                            success_progress_fields=_gopay_success_progress_fields(),
                        ),
                    )
                    continue

                if auto_wallet is not None and (
                    _is_unused_gopay_wallet_result(single_result)
                    or _is_no_transfer_balance_pending_result(single_result)
                ):
                    reusable_auto_wallet = auto_wallet
                    _preserve_gopay_wallet(auto_wallet)

                failed_emails.append(
                    {
                        "email": single_email,
                        "failure_stage": single_result.get("failure_stage") or "",
                        "message": single_result.get("message") or "",
                    }
                )
                _append_task_progress(
                    task_id,
                    gopay_task_payloads_service.gopay_auto_signup_account_failed_progress(
                        email=single_email,
                        current=index,
                        total=len(candidates),
                        failure_stage=single_result.get("failure_stage") or "",
                        message=single_result.get("message") or "GoPay 自动注册绑定失败",
                    ),
                )
                if _gopay_balance_insufficient_stop_requested():
                    break

            wallet_prefetcher.close()

            if not aggregate_results:
                return gopay_task_payloads_service.gopay_auto_signup_not_executed_result(
                    cancelled=cancel_signal.is_cancelled(),
                    attempted_emails=attempted_emails,
                    failed_emails=failed_emails,
                )

            success_set = {_normalized_email(item) for item in successful_emails if _normalized_email(item)}
            failed_emails = _dedupe_failed_email_results(
                [item for item in failed_emails if _normalized_email(item.get("email")) not in success_set]
            )
            rejected_emails = [item for item in rejected_emails if _normalized_email(item) not in success_set]
            payment_failed_emails = [
                item for item in payment_failed_emails if _normalized_email(item) not in success_set
            ]
            nonzero_blocked_emails = [
                item for item in nonzero_blocked_emails if _normalized_email(item) not in success_set
            ]
            blocked_emails = [item for item in blocked_emails if _normalized_email(item) not in success_set]

            success_count = len(successful_emails)
            attempted_count = len(attempted_emails)
            aggregate_status = (
                "success" if success_count else ("cancelled" if cancel_signal.is_cancelled() else "failed")
            )
            failure_stage = ""
            if success_count and failed_emails:
                failure_stage = "partial_failed"
            elif not success_count:
                first_failed_stage = ""
                for failed_item in failed_emails:
                    if isinstance(failed_item, dict):
                        first_failed_stage = str(failed_item.get("failure_stage") or "")
                        if first_failed_stage:
                            break
                failure_stage = (
                    first_failed_stage
                    or last_result.get("failure_stage")
                    or ("cancelled" if cancel_signal.is_cancelled() else "gopay_auto_signup")
                )
            message = f"GoPay 自动注册绑定完成: 成功 {success_count}/{len(candidates)} 个账号"
            if failed_emails:
                message += f"，失败 {len(failed_emails)} 个"
            if cancel_signal.is_cancelled() and attempted_count < len(candidates):
                message += "，任务已取消"

            result_payload = dict(last_result)
            result_payload.update(
                {
                    "status": aggregate_status,
                    "failure_stage": failure_stage,
                    "message": message,
                    "auto_signup_account_results": aggregate_results,
                    "attempted_emails": attempted_emails,
                    "successful_emails": successful_emails,
                    "rejected_emails": rejected_emails,
                    "payment_failed_emails": payment_failed_emails,
                    "nonzero_blocked_emails": nonzero_blocked_emails,
                    "blocked_emails": blocked_emails,
                    "failed_emails": failed_emails,
                    "email_used": (successful_emails[-1] if successful_emails else "")
                    or _normalized_email(last_result.get("email_used") or email),
                }
            )
            return result_payload

        try:
            logger.info(
                "[gopay-bind] runner started: task_id=%s email=%s auto_register=%s auto_register_count=%s gopay_auto_signup=%s account_count=%s pending_retry_attempts=%s concurrency=%s checkout=%s checkout_mode=%s proxy_label=%s proxy_state=%s proxy=%s",
                task_id[:8] or "<unknown>",
                _safe_email_summary(email) if email else "<auto-register>",
                auto_register,
                auto_register_count,
                gopay_auto_signup,
                len(account_emails) if account_emails else 1,
                pending_retry_attempts,
                gopay_concurrency,
                _safe_url_summary(checkout_url) if checkout_url else "<auto-generate>",
                checkout_ui_mode,
                params.proxy_label or "<none>",
                proxy_config_state,
                _safe_proxy_summary(normalized_proxy_url or proxy_url),
            )
            _append_task_progress(
                task_id,
                gopay_task_payloads_service.gopay_binding_progress(
                    email=email,
                    auto_register=auto_register,
                    auto_register_count=auto_register_count,
                    auto_register_protocol=bool(params.auto_register_protocol),
                    gopay_auto_signup=gopay_auto_signup,
                    phone_number=phone_number,
                    country_code=country_code,
                    phone_account_count=len(phone_accounts),
                    checkout_ui_mode=checkout_ui_mode,
                    proxy_label=params.proxy_label,
                    account_count=auto_register_count
                    if auto_register
                    else len(account_emails)
                    if account_emails
                    else 1,
                    pending_retry_attempts=pending_retry_attempts,
                    concurrency=gopay_concurrency,
                ),
            )
            if requested_gopay_concurrency > gopay_concurrency:
                _append_task_progress(
                    task_id,
                    gopay_task_payloads_service.gopay_concurrency_limited_progress(
                        requested_concurrency=requested_gopay_concurrency,
                        concurrency=gopay_concurrency,
                    ),
                )
            if proxy_url and not bind_proxy_url:
                _append_task_progress(
                    task_id,
                    gopay_task_payloads_service.gopay_bind_proxy_bypassed_progress(),
                )
            if auto_register:
                result = _run_auto_register_gopay_batch()
            elif gopay_auto_signup and account_emails:
                result = _run_gopay_auto_signup_existing_accounts_batch()
            else:
                active_phone_accounts = phone_accounts
                if gopay_auto_signup:
                    result, auto_wallet = _run_one_gopay_bind_with_wallet_retry(
                        email,
                        account_emails,
                        index=1,
                        total=1,
                        exception_message_prefix="GoPay 自动注册后绑定异常",
                    )
                else:
                    result = _run_one_gopay_bind(email, account_emails, selected_phone_accounts=active_phone_accounts)
                if gopay_auto_signup and auto_wallet is not None and _is_no_transfer_balance_pending_result(result):
                    _discard_gopay_wallet_for_balance_not_ready(auto_wallet, index=1, total=1)
        except Exception as exc:
            logger.exception("[gopay-bind] unexpected error")
            failure_stage = "gopay_auto_register" if auto_register and not email else "post_submit"
            if isinstance(exc, _GoPayWalletSignupRateLimited):
                failure_stage = "gopay_wallet_rate_limited"
            elif isinstance(exc, _GoPayWalletSignupNetworkError):
                failure_stage = "gopay_wallet_network_error"
            elif isinstance(exc, _GoPayWalletBalanceInsufficientLimit):
                failure_stage = "gopay_wallet_balance_insufficient"
            elif "Rekberinaja" in str(exc):
                failure_stage = "gopay_wallet_funding"
            result = gopay_task_payloads_service.gopay_task_exception_result(
                failure_stage=failure_stage,
                error=exc,
            )
        finally:
            for wallet in active_gopay_wallets:
                try:
                    if _is_gopay_wallet_bound_elsewhere_result(result):
                        _discard_gopay_wallet_bound_elsewhere(wallet, index=1, total=1)
                        continue
                    if (
                        wallet in reusable_gopay_wallets
                        or _is_unused_gopay_wallet_result(result)
                        or _is_no_transfer_balance_pending_result(result)
                    ):
                        _preserve_gopay_wallet(wallet)
                        continue
                    if isinstance(result, dict) and result.get("status") == "success":
                        wallet.close(success=True)
                    else:
                        if wallet not in retained_gopay_wallets:
                            retained_gopay_wallets.append(wallet)
                        _append_task_progress(
                            task_id,
                            gopay_task_payloads_service.gopay_wallet_otp_session_retained_progress(
                                phone_number=_mask_gopay_phone_for_log(wallet.phone_number),
                            ),
                        )
                except Exception:
                    logger.exception("[gopay-bind] close auto-registered GoPay wallet bridge failed")

        result = dict(result or {})
        result.setdefault("status", "failed")
        result.setdefault("failure_stage", "")
        result.setdefault("message", "")
        result.setdefault("screenshot_paths", [])
        actual_email = str(result.get("email_used") or email).strip().lower() or email
        result["email"] = actual_email
        result["requested_email"] = email
        result["phone_number"] = phone_number
        result["country_code"] = country_code
        result["phone_account_count"] = len(phone_accounts)
        result["proxy_label"] = params.proxy_label
        result["proxy_state"] = "disabled" if proxy_url and not bind_proxy_url else proxy_config_state
        if proxy_url and not bind_proxy_url:
            result["signup_proxy_state"] = proxy_config_state
        result["checkout_url"] = checkout_url or result.get("checkout_url") or ""
        result["account_emails"] = account_emails
        result["pending_retry_attempts"] = pending_retry_attempts
        result["concurrency"] = _current_gopay_concurrency()
        result["gopay_auto_signup_sms_provider"] = _current_gopay_auto_signup_sms_provider()
        if oauth_scheduled_emails:
            result["oauth_scheduled_emails"] = sorted(oauth_scheduled_emails)
        if oauth_successful_emails:
            result["oauth_successful_emails"] = oauth_successful_emails[:]
        if oauth_failed_emails:
            result["oauth_failed_emails"] = oauth_failed_emails[:]
        if session_cpa_converted_emails:
            result["session_cpa_converted_emails"] = session_cpa_converted_emails[:]
        if session_cpa_failed_auths:
            result["session_cpa_failed_auths"] = session_cpa_failed_auths[:]
        if reusable_gopay_wallets:
            result["reusable_gopay_wallets"] = [wallet.as_phone_account() for wallet in reusable_gopay_wallets]
        if retained_gopay_wallets:
            result["retained_gopay_wallets"] = [wallet.as_phone_account() for wallet in retained_gopay_wallets]

        if cancel_signal.is_cancelled() and result.get("status") != "success":
            task_status = "cancelled"
        elif result.get("status") == "success":
            task_status = "completed"
        else:
            task_status = "failed"
        result["task_status"] = task_status
        logger.info(
            "[gopay-bind] runner finished: task_id=%s status=%s failure_stage=%s actual_email=%s message=%s checkout=%s",
            task_id[:8] or "<unknown>",
            result.get("status") or "",
            result.get("failure_stage") or "",
            _safe_email_summary(actual_email),
            _compact_log_text(result.get("message") or "", limit=220),
            _safe_url_summary(result.get("checkout_url") or ""),
        )

        finished_at = time.time()
        account_update = {
            "last_bind_status": "cancelled" if task_status == "cancelled" else result.get("status") or "failed",
            "last_bind_at": finished_at,
            "last_bind_provider": "gopay",
            "last_checkout_url": checkout_url or result.get("checkout_url") or "",
            "last_proxy_label": params.proxy_label,
            "last_bind_task_id": task_id,
            "last_bind_message": result.get("message") or "",
            "last_bind_failure_stage": result.get("failure_stage") or "",
        }
        successful_emails = []
        for raw_email in result.get("successful_emails") or []:
            success_email = _normalized_email(raw_email)
            if success_email and success_email not in successful_emails:
                successful_emails.append(success_email)
        if result.get("status") == "success" and not successful_emails:
            success_email = _normalized_email(actual_email)
            if success_email and success_email not in successful_emails:
                successful_emails.append(success_email)

        token_invalidated_pool_emails = _gopay_token_invalidated_pool_emails(result, actual_email)
        token_invalidated_pool_set = {
            _normalized_email(token_email)
            for token_email in token_invalidated_pool_emails
            if _normalized_email(token_email)
        }

        pending_successful_emails = [
            success_email
            for success_email in successful_emails
            if success_email not in realtime_successful_emails and success_email not in token_invalidated_pool_set
        ]
        if pending_successful_emails:
            for success_email in pending_successful_emails:
                _mark_gopay_success_account(
                    success_email,
                    message=result.get("message") or "GoPay 绑定成功",
                    success_checkout_url=result.get("checkout_url") or checkout_url or "",
                )
            if (
                result.get("status") != "success"
                and actual_email not in successful_emails
                and _normalized_email(actual_email) not in token_invalidated_pool_set
            ):
                update_account(actual_email, **account_update)
        elif (
            not successful_emails and actual_email and _normalized_email(actual_email) not in token_invalidated_pool_set
        ):
            update_account(actual_email, **account_update)

        result["successful_emails"] = sorted(realtime_successful_emails)

        if oauth_scheduled_emails:
            result["oauth_scheduled_emails"] = sorted(oauth_scheduled_emails)
        if oauth_successful_emails:
            result["oauth_successful_emails"] = oauth_successful_emails[:]
        if oauth_failed_emails:
            result["oauth_failed_emails"] = oauth_failed_emails[:]
        if session_cpa_converted_emails:
            result["session_cpa_converted_emails"] = session_cpa_converted_emails[:]
        if session_cpa_failed_auths:
            result["session_cpa_failed_auths"] = session_cpa_failed_auths[:]

        removed_pool_emails = []
        rejected_pool_emails = _gopay_rejected_pool_emails(result, actual_email)
        nonzero_blocked_pool_emails = _gopay_nonzero_blocked_pool_emails(result, actual_email)
        payment_failed_pool_emails = _gopay_payment_failed_pool_emails(result, actual_email)
        cleanup_pool_emails = []
        for cleanup_email in [*rejected_pool_emails, *nonzero_blocked_pool_emails, *payment_failed_pool_emails]:
            if cleanup_email and cleanup_email not in cleanup_pool_emails:
                cleanup_pool_emails.append(cleanup_email)
        if params.delete_rejected_accounts:
            removed_pool_emails = _remove_gopay_rejected_accounts_from_pool(cleanup_pool_emails)
        if token_invalidated_pool_emails:
            token_invalidated_removed = [
                token_email
                for token_email in token_invalidated_pool_emails
                if _normalized_email(token_email) in auth_session_refresh_attempted
            ]
            token_invalidated_to_remove = [
                token_email
                for token_email in token_invalidated_pool_emails
                if _normalized_email(token_email) not in auth_session_refresh_attempted
            ]
            newly_removed = _remove_pool_accounts_from_local_and_mail(
                token_invalidated_to_remove,
                log_context="gopay-token-invalidated",
                reason="gopay_token_invalidated",
                message="GoPay 返回 token_invalidated，重新登录刷新失败或重试后仍失效，账号已从号池删除",
            )
            for removed_email in newly_removed:
                if removed_email not in token_invalidated_removed:
                    token_invalidated_removed.append(removed_email)
            result["token_invalidated_pool_emails"] = token_invalidated_pool_emails
            result["token_invalidated_removed_emails"] = token_invalidated_removed
            for removed_email in token_invalidated_removed:
                if removed_email not in removed_pool_emails:
                    removed_pool_emails.append(removed_email)
        if not params.delete_rejected_accounts and cleanup_pool_emails:
            result["rejected_pool_emails"] = rejected_pool_emails
            result["nonzero_blocked_pool_emails"] = nonzero_blocked_pool_emails
            result["payment_failed_pool_emails"] = payment_failed_pool_emails
            logger.info(
                "[gopay-bind] rejected/nonzero/payment-failed accounts kept in pool: task_id=%s rejected=%s nonzero=%s payment_failed=%s",
                task_id[:8] or "<unknown>",
                rejected_pool_emails,
                nonzero_blocked_pool_emails,
                payment_failed_pool_emails,
            )
        if removed_pool_emails:
            result["removed_pool_emails"] = removed_pool_emails
            logger.info(
                "[gopay-bind] removed unusable accounts from local pool only: task_id=%s emails=%s",
                task_id[:8] or "<unknown>",
                removed_pool_emails,
            )

        record_bind_audit(
            {
                "task_id": task_id,
                "email": actual_email,
                "requested_email": email,
                "account_emails": account_emails,
                "card_item_id": "",
                "checkout_url": checkout_url or result.get("checkout_url") or "",
                "proxy_label": params.proxy_label,
                "proxy_url": proxy_url,
                "manual_confirm": False,
                "status": result.get("status") or "failed",
                "task_status": task_status,
                "failure_stage": result.get("failure_stage") or "",
                "message": result.get("message") or "",
                "started_at": started_at,
                "finished_at": finished_at,
                "screenshot_paths": result.get("screenshot_paths") or [],
                "card_status": "",
                "flow": "gopay",
                "phone_number": phone_number,
                "country_code": country_code,
                "phone_account_count": len(phone_accounts),
                "billing_info": result.get("billing_info") or {},
                "removed_pool_emails": result.get("removed_pool_emails") or [],
                "successful_emails": result.get("successful_emails") or [],
            }
        )

        _append_task_progress(
            task_id,
            {
                "stage": "completed" if result.get("status") == "success" else "failed",
                "status": result.get("status") or "failed",
                "failure_stage": result.get("failure_stage") or "",
                "message": result.get("message") or "",
                **_gopay_success_progress_fields(),
            },
        )

        if result.get("status") != "success":
            raise TaskResultError(result.get("message") or "GoPay 任务失败", task_result=result)
        return result

    task_params = params.model_dump()
    task_params["auto_register_count"] = auto_register_count
    task_params["auto_register_protocol"] = bool(params.auto_register_protocol)
    task_params["auto_register_domains"] = auto_register_domains
    task_params["auto_register_domain"] = auto_register_domains[0] if auto_register_domains else ""
    task_params["auto_register_mail_provider"] = auto_register_mail_provider or "<default>"
    task_params["auto_register_luckmail_email_type"] = auto_register_luckmail_email_type or ""
    task_params["auto_register_luckmail_preferred_domain"] = auto_register_luckmail_preferred_domain or ""
    task_params["auto_register_luckmail_preferred_domains"] = auto_register_luckmail_preferred_domains
    task_params["auto_register_prefix"] = auto_register_prefix
    task_params["auto_register_password_present"] = bool(auto_register_password)
    task_params["gopay_auto_signup_sms_provider"] = gopay_auto_signup_sms_provider
    task_params["gopay_auto_signup_mode"] = requested_signup_mode
    task_params["gopay_appium_url"] = gopay_auto_signup_appium_config.get("appium_url") or ""
    task_params["gopay_appium_adb_serial"] = gopay_auto_signup_appium_config.get("adb_serial") or ""
    task_params["gopay_task_public_base_url"] = gopay_task_public_base_url
    task_params["gopay_auto_signup_hero_sms_api_key_present"] = bool(gopay_auto_signup_hero_sms_config.get("api_key"))
    task_params["gopay_auto_signup_smsbower_api_key_present"] = bool(gopay_auto_signup_smsbower_config.get("api_key"))
    task_params["gopay_auto_signup_smscode_api_token_present"] = bool(gopay_auto_signup_smscode_config.get("api_token"))
    task_params["pending_retry_attempts"] = pending_retry_attempts
    task_params["gopay_concurrency"] = gopay_concurrency
    task_params["requested_gopay_concurrency"] = requested_gopay_concurrency
    task_params["gopay_balance_wait_fallback_transfer"] = gopay_balance_wait_fallback_transfer
    task_params["proxy_pool_count"] = len(normalized_proxy_pool)
    task_params["proxy_api_url_present"] = bool(proxy_api_url)
    task_params["proxy_api_provider"] = proxy_api_provider
    task_params.pop("auto_register_password", None)
    task_params.pop("gopay_auto_signup_hero_sms_api_key", None)
    task_params.pop("gopay_auto_signup_smsbower_api_key", None)
    task_params.pop("gopay_auto_signup_smscode_api_token", None)
    task_params["phone_account_count"] = len(phone_accounts)
    task_params["phone_accounts"] = [
        {
            "country_code": item.get("country_code") or "",
            "phone_number": item.get("phone_number") or "",
            "sms_url_present": bool(item.get("sms_url")),
            "gopay_pin_present": bool(item.get("gopay_pin")),
            "otp_channel": item.get("otp_channel") or otp_channel,
        }
        for item in phone_accounts
    ]
    task_params.pop("gopay_pin", None)
    task = _start_task("gopay-bind", _run, task_params, task_group=TASK_GROUP_GOPAY)
    submitted_gopay_task_id = str(task.get("task_id") or "")
    _init_gopay_runtime_control(
        submitted_gopay_task_id,
        gopay_concurrency=gopay_concurrency,
        sms_provider=gopay_auto_signup_sms_provider,
        account_emails=account_emails or ([email] if email else []),
    )
    _task_skip_signals[submitted_gopay_task_id] = skip_current_signal
    _register_task_cancel_hook(submitted_gopay_task_id, skip_current_signal.set)
    return task


@app.post("/api/tasks/paypal/preflight")
def post_paypal_task_preflight(params: PayPalTaskParams):
    return _paypal_task_preflight_payload(params)


@app.post("/api/tasks/paypal", status_code=202)
def post_paypal_task(params: PayPalTaskParams, request: Request = None):
    try:
        paypal_preflight_service.validate_paypal_timeout_seconds(params.timeout_seconds)
        paypal_preflight_service.normalize_paypal_runner_mode(params.runner_mode)
        paypal_mode = paypal_preflight_service.normalize_paypal_mode(params.paypal_mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    pending_retry_attempts = paypal_preflight_service.normalize_pending_retry_attempts(params.pending_retry_attempts)
    paypal_concurrency = paypal_preflight_service.normalize_paypal_concurrency(params.paypal_concurrency)

    from autotoken.core import cancel_signal
    from autotoken.payments.bind_audit import record_bind_audit
    from autotoken.payments.paypal_bind_executor import (
        _extract_auth_session_context,
        _paypal_extract_ba_link,
        run_paypal_bind_task,
    )
    from autotoken.storage.accounts import (
        ACCOUNT_TYPE_PLUS,
        SEAT_CODEX,
        add_account,
        ensure_session_only_account,
        find_account,
        load_accounts,
        update_account,
    )
    from autotoken.storage.auth_session_store import get_auth_session_file

    paypal_inputs = paypal_preflight_service.normalize_paypal_task_inputs(
        params=params,
        normalize_email=_normalized_email,
    )
    email = paypal_inputs["email"]
    account_emails = paypal_inputs["account_emails"]
    checkout_url = paypal_inputs["checkout_url"]
    try:
        direct_ba_pre_extracted = paypal_ba_service.paypal_direct_ba_pre_extracted(
            params,
            fallback_checkout_url=checkout_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if direct_ba_pre_extracted and account_emails:
        raise HTTPException(status_code=400, detail="直连 PayPal BA/link 模式只支持单账号任务，不能与 account_emails 批量复用")
    paypal_options = paypal_preflight_service.normalize_paypal_runtime_options(
        paypal_mode=paypal_mode,
        paypal_browser=params.paypal_browser,
        paypal_fallback_browser=params.paypal_fallback_browser,
        paypal_region=params.paypal_region,
        paypal_country=params.paypal_country,
        billing_country=params.billing_country,
        paypal_lang=params.paypal_lang,
        bind_link_payload=params.bind_link_payload,
        roxybrowser_workspace_id=params.roxybrowser_workspace_id,
        roxybrowser_profile_id=params.roxybrowser_profile_id,
        roxybrowser_auto_create_profile=params.roxybrowser_auto_create_profile,
        paypal_card_number=params.paypal_card_number,
        paypal_card_expiry=params.paypal_card_expiry,
        paypal_card_cvv=params.paypal_card_cvv,
    )
    bind_link_payload = paypal_options["bind_link_payload"]
    roxybrowser_workspace_id = paypal_options["roxybrowser_workspace_id"]
    roxybrowser_profile_id = paypal_options["roxybrowser_profile_id"]
    roxybrowser_auto_create_profile = paypal_options["roxybrowser_auto_create_profile"]
    paypal_browser = paypal_options["paypal_browser"]
    paypal_fallback_browser = paypal_options["paypal_fallback_browser"]
    paypal_region = paypal_options["paypal_region"]
    paypal_country = paypal_options["paypal_country"]
    paypal_lang = paypal_options["paypal_lang"]
    protocol_no_card = paypal_options["protocol_no_card"]
    paypal_ba_mode = paypal_ba_service.paypal_ba_extract_mode(getattr(params, "paypal_ba_mode", "eu"))
    if direct_ba_pre_extracted and (paypal_mode != "create_account" or not protocol_no_card):
        raise HTTPException(status_code=400, detail="直连 PayPal BA/link 模式只支持 create_account + protocol/no-card")
    sms_url = paypal_inputs["sms_url"]
    otp_channel = paypal_inputs["otp_channel"]
    requested_paypal_ba_payment_method_country = str(
        getattr(params, "paypal_ba_payment_method_country", "") or ""
    ).strip()
    paypal_ba_payment_method_country = paypal_ba_service.paypal_ba_payment_method_country(
        override=requested_paypal_ba_payment_method_country or os.environ.get("PAYPAL_BA_PAYMENT_METHOD_COUNTRY"),
        protocol_no_card=protocol_no_card,
        paypal_country=paypal_country,
        paypal_ba_mode=paypal_ba_mode,
    )
    paypal_ba_proxy_region = str(os.environ.get("PAYPAL_BA_PROXY_REGION") or paypal_ba_payment_method_country)
    try:
        paypal_proxy_runtime = paypal_proxy_service.prepare_paypal_proxy_runtime(
            proxy_url=params.proxy_url,
            proxy_pool=params.proxy_pool,
            proxy_pool_text=params.proxy_pool_text,
            proxy_api_provider=params.proxy_api_provider,
            proxy_api_url=params.proxy_api_url,
            paypal_jp_proxy_url=params.paypal_jp_proxy_url,
            paypal_us_proxy_url=params.paypal_us_proxy_url,
            paypal_country=paypal_country,
            protocol_no_card=protocol_no_card,
            paypal_ba_proxy_region=paypal_ba_proxy_region,
            default_proxy_entry=lambda provider: _default_proxy_entry(provider),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    proxy_api_url = paypal_proxy_runtime.proxy_api_url
    proxy_api_provider = paypal_proxy_runtime.proxy_api_provider
    normalized_proxy_pool = paypal_proxy_runtime.normalized_proxy_pool
    bind_proxy_url = paypal_proxy_runtime.bind_proxy_url
    try:
        phone_account_result = paypal_phone_pool_service.normalize_paypal_phone_accounts(
            list(params.phone_accounts or []),
            otp_channel=otp_channel,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    phone_accounts = phone_account_result["phone_accounts"]
    if phone_accounts:
        sms_url = phone_account_result["sms_url"]
        otp_channel = phone_account_result["otp_channel"]
        if not str(params.billing_phone or "").strip():
            params.billing_phone = phone_account_result["billing_phone"]
    paypal_sms_auto_provisioned = False
    paypal_sms_provider = ""
    if not phone_accounts and not sms_url and paypal_mode == "create_account" and protocol_no_card:
        try:
            explicit_phone = paypal_phone_pool_service.explicit_paypal_phone_account_from_env()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if explicit_phone:
            phone_accounts = [
                {
                    "phone_number": str(explicit_phone.get("phone_number") or "").strip(),
                    "sms_url": str(explicit_phone.get("sms_url") or "").strip(),
                    "otp_channel": str(explicit_phone.get("otp_channel") or "sms").strip().lower() or "sms",
                    "sms_provider": str(explicit_phone.get("sms_provider") or "").strip(),
                }
            ]
            sms_url = str(phone_accounts[0].get("sms_url") or "").strip()
            otp_channel = str(phone_accounts[0].get("otp_channel") or otp_channel or "sms").strip().lower() or "sms"
            if not str(params.billing_phone or "").strip():
                params.billing_phone = str(phone_accounts[0].get("phone_number") or "").strip()
    if paypal_phone_pool_service.paypal_sms_auto_provision_enabled(
        paypal_mode=paypal_mode,
        protocol_no_card=protocol_no_card,
        sms_url=sms_url,
        phone_accounts=phone_accounts,
    ):
        try:
            provisioned_phone = paypal_phone_pool_service.provision_paypal_phone_account_from_env(
                public_base_url=_request_public_base_url(request),
                log=lambda message: logger.info(_compact_log_text(message, limit=180)),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        phone_accounts = [
            {
                "phone_number": str(provisioned_phone.get("phone_number") or "").strip(),
                "sms_url": str(provisioned_phone.get("sms_url") or "").strip(),
                "otp_channel": str(provisioned_phone.get("otp_channel") or "sms").strip().lower() or "sms",
                "bridge_token": str(provisioned_phone.get("bridge_token") or "").strip(),
                "sms_provider": str(provisioned_phone.get("sms_provider") or "").strip(),
            }
        ]
        sms_url = str(phone_accounts[0].get("sms_url") or "").strip()
        otp_channel = str(phone_accounts[0].get("otp_channel") or otp_channel or "sms").strip().lower() or "sms"
        if not str(params.billing_phone or "").strip():
            params.billing_phone = str(phone_accounts[0].get("phone_number") or "").strip()
        paypal_sms_auto_provisioned = True
        paypal_sms_provider = str(provisioned_phone.get("sms_provider") or "").strip()

    def _select_paypal_proxy() -> str:
        return paypal_proxy_service.select_paypal_proxy(
            paypal_proxy_runtime,
            fetch_proxy_from_api_url=_fetch_proxy_from_api_url,
            default_auth_scheme=PAYPAL_PROXY_DEFAULT_SCHEME,
        )

    def _select_paypal_provider_proxy(selected_proxy_url: str) -> str:
        return paypal_proxy_service.select_paypal_provider_proxy(
            paypal_proxy_runtime,
            selected_proxy_url=selected_proxy_url,
            protocol_no_card=protocol_no_card,
            fetch_proxy_from_api_url=_fetch_proxy_from_api_url,
            default_auth_scheme=PAYPAL_PROXY_DEFAULT_SCHEME,
        )

    def _paypal_ba_extract_attempts() -> int:
        return paypal_ba_service.paypal_ba_extract_attempts(os.environ.get("PAYPAL_BA_EXTRACT_ATTEMPTS", "15"))

    def _paypal_ba_payment_method_country() -> str:
        return paypal_ba_payment_method_country

    def _paypal_checkout_proxy_exit_location(selected_proxy_url: str) -> dict[str, str]:
        return paypal_proxy_service.paypal_proxy_exit_location(
            selected_proxy_url,
            on_error=lambda exc: logger.info("[paypal_extract] checkout proxy geo probe failed: %s", exc),
        )

    def _paypal_checkout_proxy_country_mismatch_result(
        candidate_email: str,
        *,
        selected_proxy_url: str,
    ) -> dict[str, Any] | None:
        if not protocol_no_card or direct_ba_pre_extracted:
            return None
        if not str(selected_proxy_url or "").strip():
            return {
                "status": "failed",
                "failure_stage": "paypal_checkout_proxy_country_mismatch",
                "message": "PayPal checkout 缺少 JP 代理，当前账号跳过",
                "email": candidate_email,
                "checkout_proxy_url": "",
                "checkout_proxy_country": "",
                "checkout_proxy_region": "",
                "checkout_proxy_city": "",
                "checkout_proxy_ip": "",
            }
        exit_location = _paypal_checkout_proxy_exit_location(selected_proxy_url)
        detected_country = str(exit_location.get("country_code") or "").strip().upper()
        if detected_country == "JP":
            return None
        proxy_region = str(exit_location.get("region") or "").strip()
        proxy_city = str(exit_location.get("city") or "").strip()
        proxy_ip = str(exit_location.get("ip") or "").strip()
        reason = "不是 JP" if detected_country else "无法确认是否为 JP"
        return {
            "status": "failed",
            "failure_stage": "paypal_checkout_proxy_country_mismatch",
            "message": (
                f"PayPal checkout 代理出口{reason}，当前账号跳过: "
                f"country={detected_country or '-'} "
                f"region={proxy_region or '-'} "
                f"city={proxy_city or '-'} "
                f"ip={proxy_ip or '-'}"
            ),
            "email": candidate_email,
            "checkout_proxy_url": selected_proxy_url,
            "checkout_proxy_country": detected_country,
            "checkout_proxy_region": proxy_region,
            "checkout_proxy_city": proxy_city,
            "checkout_proxy_ip": proxy_ip,
        }

    def _paypal_ba_auth_context(email: str, fallback_access_token: str) -> dict[str, str]:
        use_full_context = protocol_no_card or str(
            os.environ.get("PAYPAL_BA_USE_AUTH_SESSION_CONTEXT") or ""
        ).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        return paypal_ba_service.paypal_ba_auth_context(
            email,
            fallback_access_token,
            session_context_loader=_extract_auth_session_context,
            use_full_context=use_full_context,
            log_failure=lambda exc: logger.info(
                "[paypal_extract] auth_session context load failed, using access_token only: %s",
                exc,
            ),
        )

    def _paypal_already_paid_text(value: Any) -> bool:
        return paypal_ba_service.paypal_already_paid_text(value)

    def _paypal_user_paid_success(candidate_email: str, message: str = "") -> dict:
        return paypal_ba_service.paypal_user_paid_success(candidate_email, message)

    account_emails = paypal_preflight_service.include_primary_paypal_account_email(account_emails, email)
    sms_url = paypal_preflight_service.resolve_paypal_task_sms_url(
        sms_url=sms_url,
        manual_confirm=params.manual_confirm,
        paypal_mode=paypal_mode,
        otp_channel=otp_channel,
        default_whatsapp_sms_url=_default_whatsapp_otp_url,
    )
    try:
        paypal_preflight_service.validate_paypal_task_request(
            params=params,
            email=email,
            checkout_url=checkout_url,
            bind_link_payload=bind_link_payload,
            paypal_mode=paypal_mode,
            otp_channel=otp_channel,
            sms_url=sms_url,
            protocol_no_card=protocol_no_card,
            direct_ba_pre_extracted=direct_ba_pre_extracted,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    accounts = load_accounts()
    account = find_account(accounts, email)
    if not account:
        auth_session_file = get_auth_session_file(email)
        if auth_session_file and Path(auth_session_file).exists():
            account = ensure_session_only_account(email) or _session_only_account_stub(email)
        else:
            raise HTTPException(status_code=404, detail="账号不存在")
    if not _resolve_status_auth_file(account):
        raise HTTPException(status_code=400, detail="该账号缺少可用 auth_session/auth_file")
    for candidate_email in account_emails:
        if candidate_email == email:
            continue
        candidate = find_account(accounts, candidate_email)
        if not candidate:
            auth_session_file = get_auth_session_file(candidate_email)
            if auth_session_file and Path(auth_session_file).exists():
                candidate = ensure_session_only_account(candidate_email) or _session_only_account_stub(candidate_email)
                accounts = load_accounts()
            else:
                raise HTTPException(status_code=404, detail=f"批量账号不存在: {candidate_email}")
        if not _resolve_status_auth_file(candidate):
            raise HTTPException(status_code=400, detail=f"批量账号缺少可用 auth_session/auth_file: {candidate_email}")

    payload = paypal_task_payloads_service.build_paypal_task_payload(
        params=params,
        email=email,
        account_emails=account_emails,
        checkout_url=checkout_url,
        bind_link_payload=bind_link_payload,
        proxy_pool_count=len(normalized_proxy_pool),
        proxy_api_url=proxy_api_url,
        proxy_api_provider=proxy_api_provider,
        roxybrowser_workspace_id=roxybrowser_workspace_id,
        roxybrowser_profile_id=roxybrowser_profile_id,
        roxybrowser_auto_create_profile=roxybrowser_auto_create_profile,
        paypal_browser=paypal_browser,
        paypal_mode=paypal_mode,
        paypal_country=paypal_country,
        paypal_lang=paypal_lang,
        paypal_region=paypal_region,
        paypal_fallback_browser=paypal_fallback_browser,
        sms_url=sms_url,
        otp_channel=otp_channel,
        phone_account_count=len(phone_accounts),
        pending_retry_attempts=pending_retry_attempts,
        paypal_concurrency=paypal_concurrency,
        direct_ba_pre_extracted=direct_ba_pre_extracted,
    )
    if paypal_sms_auto_provisioned:
        payload["paypal_sms_auto_provisioned"] = True
        payload["paypal_sms_provider"] = paypal_sms_provider
    if phone_accounts:
        payload["phone_accounts"] = [
            {
                "phone_number": item.get("phone_number") or "",
                "sms_url_present": bool(item.get("sms_url")),
                "otp_channel": item.get("otp_channel") or otp_channel,
            }
            for item in phone_accounts
        ]
    autofill_payload = paypal_task_payloads_service.build_paypal_autofill_payload(params=params, email=email)

    def _candidate_autofill_payload(candidate_email: str) -> dict:
        return paypal_task_payloads_service.paypal_candidate_autofill_payload(
            autofill_payload,
            candidate_email=candidate_email,
            billing_email=params.billing_email,
        )

    _paypal_phone_account_available = paypal_phone_pool_service.paypal_phone_account_available

    def _run():
        task_id = _current_task_id_for_group() or ""
        started_at = time.time()
        result = None
        candidates = account_emails[:] if account_emails else [email]
        successful_emails: list[str] = []
        failed_emails: list[str] = []
        nonzero_blocked_emails: list[str] = []
        removed_pool_emails: list[str] = []
        oauth_scheduled_emails: set[str] = set()
        oauth_successful_emails: list[str] = []
        oauth_failed_emails: list[dict] = []
        session_cpa_scheduled_emails: set[str] = set()
        session_cpa_converted_emails: list[str] = []
        session_cpa_failed_auths: list[dict] = []
        last_checkout_url = checkout_url
        invalid_phone_numbers: set[str] = set()
        invalid_phone_pool: list[str] = []
        pending_retry_queue: list[dict[str, Any]] = []
        pending_retry_emails: list[str] = []
        retried_emails: list[str] = []
        pending_retry_backoffs = paypal_pending_retry_service.DEFAULT_PENDING_RETRY_BACKOFFS
        retry_round_waited: set[int] = set()
        state_lock = threading.Lock()
        phone_lock = threading.Lock()
        reserved_phone_keys: set[str] = set()
        paypal_success_account_fields = paypal_task_payloads_service.paypal_success_account_update_fields()
        concurrency_result = paypal_preflight_service.resolve_effective_paypal_concurrency(
            paypal_mode=paypal_mode,
            phone_account_count=len(phone_accounts),
            paypal_concurrency=paypal_concurrency,
            paypal_browser=paypal_browser,
            roxybrowser_profile_id=roxybrowser_profile_id,
            roxybrowser_auto_create_profile=roxybrowser_auto_create_profile,
        )
        effective_paypal_concurrency = concurrency_result["concurrency"]
        for progress_event in concurrency_result["progress_events"]:
            _append_task_progress(task_id, progress_event)

        def _remember_invalid_phone(phone: Any) -> None:
            paypal_phone_pool_service.remember_invalid_paypal_phone(phone, invalid_phone_numbers, invalid_phone_pool)

        def _remember_invalid_phone_threadsafe(phone: Any) -> None:
            with phone_lock:
                _remember_invalid_phone(phone)

        def _lease_paypal_phone_accounts_from_candidates(candidates: list[dict]) -> tuple[list[dict], str, str, str]:
            with phone_lock:
                return paypal_phone_pool_service.lease_paypal_phone_accounts_from_candidates(
                    candidates,
                    invalid_keys=invalid_phone_numbers,
                    reserved_keys=reserved_phone_keys,
                    otp_channel=otp_channel,
                    effective_concurrency=effective_paypal_concurrency,
                )

        def _lease_paypal_phone_accounts() -> tuple[list[dict], str, str, str]:
            with phone_lock:
                return paypal_phone_pool_service.lease_paypal_phone_accounts(
                    phone_accounts,
                    sms_url=sms_url,
                    otp_channel=otp_channel,
                    invalid_keys=invalid_phone_numbers,
                    reserved_keys=reserved_phone_keys,
                    effective_concurrency=effective_paypal_concurrency,
                )

        def _lease_paypal_phone_accounts_for_item(queue_item: dict[str, Any]) -> tuple[list[dict], str, str, str]:
            with phone_lock:
                return paypal_phone_pool_service.lease_paypal_phone_accounts_for_item(
                    queue_item,
                    phone_accounts=phone_accounts,
                    sms_url=sms_url,
                    otp_channel=otp_channel,
                    invalid_keys=invalid_phone_numbers,
                    reserved_keys=reserved_phone_keys,
                    effective_concurrency=effective_paypal_concurrency,
                )

        def _assign_paypal_phone_accounts_to_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            with phone_lock:
                return paypal_phone_pool_service.assign_paypal_phone_accounts_to_items(
                    items,
                    paypal_mode=paypal_mode,
                    phone_accounts=phone_accounts,
                    invalid_keys=invalid_phone_numbers,
                )

        def _release_paypal_phone_accounts(active_phone_accounts: list[dict]) -> None:
            if not active_phone_accounts:
                return
            with phone_lock:
                paypal_phone_pool_service.release_paypal_phone_accounts(active_phone_accounts, reserved_phone_keys)

        def _close_paypal_sms_bridges_for_result(active_phone_accounts: list[dict], result_payload: dict | None) -> None:
            if not active_phone_accounts:
                return
            try:
                paypal_phone_pool_service.close_paypal_sms_bridges(
                    active_phone_accounts,
                    success=paypal_phone_pool_service.paypal_sms_bridge_success_for_result(result_payload),
                )
            except Exception:
                logger.debug("[paypal] close PayPal SMS bridge failed", exc_info=True)

        def _append_task_progress_threadsafe(progress: dict[str, Any]) -> None:
            with state_lock:
                _append_task_progress(task_id, progress)

        def _paypal_success_progress_fields() -> dict:
            return paypal_task_payloads_service.paypal_success_progress_fields(successful_emails)

        def _append_unique(target: list[str], value: Any) -> None:
            paypal_pending_retry_service.append_unique_email(target, value, normalizer=_normalized_email)

        def _remove_email(target: list[str], value: Any) -> None:
            paypal_pending_retry_service.remove_email(target, value, normalizer=_normalized_email)

        def _queue_paypal_pending_retry(
            candidate_email: str,
            *,
            reason: str,
            result_payload: dict,
            retry_round: int,
            current_index: int,
            total_count: int,
        ) -> None:
            _append_task_progress(
                task_id,
                paypal_pending_retry_service.queue_pending_retry(
                    pending_retry_emails=pending_retry_emails,
                    pending_retry_queue=pending_retry_queue,
                    candidate_queue=candidate_queue,
                    candidate_email=candidate_email,
                    reason=reason,
                    result_payload=result_payload,
                    retry_round=retry_round,
                    current_index=current_index,
                    total_count=total_count,
                    max_retry_rounds=pending_retry_attempts,
                    source_stage=_paypal_pending_retry_source_stage,
                    normalizer=_normalized_email,
                ),
            )

        def _maybe_wait_pending_retry_round(retry_round: int, pending_count: int) -> None:
            wait_seconds = paypal_pending_retry_service.pending_retry_wait_seconds(
                retry_round,
                retry_round_waited,
                pending_retry_backoffs,
            )
            if wait_seconds is None:
                return
            _append_task_progress(
                task_id,
                paypal_pending_retry_service.pending_retry_wait_progress(
                    retry_round=retry_round,
                    max_retry_rounds=pending_retry_attempts,
                    pending_count=pending_count,
                    wait_seconds=wait_seconds,
                ),
            )
            time.sleep(wait_seconds)
            _append_task_progress(
                task_id,
                paypal_pending_retry_service.pending_retry_started_progress(
                    retry_round=retry_round,
                    max_retry_rounds=pending_retry_attempts,
                    pending_count=pending_count,
                ),
            )

        def _remove_from_pending_retry(candidate_email: str) -> None:
            paypal_pending_retry_service.remove_pending_retry(
                candidate_email=candidate_email,
                pending_retry_emails=pending_retry_emails,
                pending_retry_queue=pending_retry_queue,
                normalizer=_normalized_email,
            )

        def _paypal_retryable_result(result_payload: dict | None) -> str:
            return _paypal_pending_retry_reason(result_payload)

        def _paypal_candidate_retry_reason(result_payload: dict | None) -> str:
            with phone_lock:
                return paypal_pending_retry_service.candidate_retry_reason(
                    result_payload,
                    retry_reason=_paypal_retryable_result,
                    phone_accounts=phone_accounts,
                    invalid_phone_keys=invalid_phone_numbers,
                    phone_available=_paypal_phone_account_available,
                )

        def _paypal_retry_round_concurrency(round_items: list[dict[str, Any]]) -> int:
            with phone_lock:
                return paypal_phone_pool_service.paypal_phone_retry_round_concurrency(
                    base_concurrency=effective_paypal_concurrency,
                    round_item_count=len(round_items),
                    paypal_mode=paypal_mode,
                    phone_accounts=phone_accounts,
                    invalid_keys=invalid_phone_numbers,
                )

        def _update_paypal_success_plan_type(candidate_email: str, updated_account):
            try:
                update_request = paypal_task_payloads_service.paypal_success_plan_update_request(
                    candidate_email=candidate_email,
                    updated_account=updated_account,
                    plan_type=ACCOUNT_TYPE_PLUS,
                )
                plan_update = _update_account_cpa_auth_plan_type(
                    update_request["email"],
                    account=update_request["account"],
                    plan_type=update_request["plan_type"],
                )
                return paypal_task_payloads_service.apply_paypal_success_plan_update(
                    updated_account=updated_account,
                    plan_update=plan_update,
                )
            except Exception:
                logger.warning(
                    "[paypal] failed to update CPA auth plan_type after Plus upgrade: %s",
                    _safe_email_summary(candidate_email),
                    exc_info=True,
                )
                return updated_account

        def _handle_paypal_success_auth(success_email_value: str, oauth_proxy_url_for_account: str = "") -> None:
            success_email = _normalized_email(success_email_value)
            if not success_email:
                return
            if not params.auto_oauth_after_success:
                if success_email in session_cpa_scheduled_emails:
                    return
                session_cpa_scheduled_emails.add(success_email)
                _append_task_progress(
                    task_id,
                    paypal_task_payloads_service.paypal_oauth_login_skipped_progress(
                        success_email=success_email,
                        successful_emails=successful_emails,
                    ),
                )
                logger.info(
                    "[paypal] skipped CPA conversion after PayPal success because OAuth login was not enabled: task_id=%s email=%s",
                    task_id[:8] or "<unknown>",
                    _safe_email_summary(success_email),
                )
                return

            if success_email in oauth_scheduled_emails:
                return
            oauth_scheduled_emails.add(success_email)
            _append_task_progress(
                task_id,
                paypal_task_payloads_service.paypal_oauth_login_started_progress(
                    success_email=success_email,
                    successful_emails=successful_emails,
                ),
            )

            def _oauth_worker():
                from autotoken.auth.codex_auth import CodexOAuthPhoneRequired

                max_attempts = 3
                retry_delay_seconds = 3
                for attempt in range(1, max_attempts + 1):
                    try:
                        latest_account = find_account(load_accounts(), success_email) or {"email": success_email}
                        oauth_proxy_url = oauth_proxy_url_for_account or bind_proxy_url
                        if oauth_proxy_url:
                            _append_task_progress(
                                task_id,
                                paypal_task_payloads_service.paypal_oauth_proxy_selected_progress(
                                    success_email=success_email,
                                    proxy_label=params.proxy_label,
                                    proxy_api_provider=proxy_api_provider,
                                ),
                            )
                        oauth_login_kwargs: dict[str, Any] = {"headless": False}
                        if oauth_proxy_url:
                            oauth_login_kwargs["proxy_url"] = oauth_proxy_url
                        if params.proxy_bypass:
                            oauth_login_kwargs["proxy_bypass"] = params.proxy_bypass
                        oauth_result = _run_account_codex_login_once(
                            success_email, latest_account, **oauth_login_kwargs
                        )
                        oauth_successful_emails.append(success_email)
                        _append_task_progress(
                            task_id,
                            paypal_task_payloads_service.paypal_oauth_login_done_progress(
                                success_email=success_email,
                                auth_file=oauth_result.get("auth_file") or "",
                                attempt=attempt,
                                max_attempts=max_attempts,
                                successful_emails=successful_emails,
                            ),
                        )
                        logger.info(
                            "[paypal] OAuth login after PayPal success completed: task_id=%s email=%s auth_file=%s attempt=%d/%d",
                            task_id[:8] or "<unknown>",
                            _safe_email_summary(success_email),
                            oauth_result.get("auth_file") or "",
                            attempt,
                            max_attempts,
                        )
                        return
                    except CodexOAuthPhoneRequired as exc:
                        result_payload = _oauth_phone_required_result(success_email, exc)
                        removed_pool_emails = result_payload.get("removed_pool_emails") or []
                        oauth_failed_emails.append(
                            paypal_task_payloads_service.paypal_oauth_phone_required_failure_record(
                                success_email=success_email,
                                error=exc,
                                removed_pool_emails=removed_pool_emails,
                            )
                        )
                        _append_task_progress(
                            task_id,
                            paypal_task_payloads_service.paypal_oauth_phone_required_progress(
                                success_email=success_email,
                                removed_pool_emails=removed_pool_emails,
                                attempt=attempt,
                                max_attempts=max_attempts,
                                successful_emails=successful_emails,
                                message=result_payload["message"],
                            ),
                        )
                        return
                    except Exception as exc:
                        if attempt < max_attempts:
                            _append_task_progress(
                                task_id,
                                paypal_task_payloads_service.paypal_oauth_login_retrying_progress(
                                    success_email=success_email,
                                    attempt=attempt,
                                    max_attempts=max_attempts,
                                    successful_emails=successful_emails,
                                    error=exc,
                                ),
                            )
                            logger.warning(
                                "[paypal] OAuth login after PayPal success failed, retrying: task_id=%s email=%s attempt=%d/%d error=%s",
                                task_id[:8] or "<unknown>",
                                _safe_email_summary(success_email),
                                attempt,
                                max_attempts,
                                exc,
                            )
                            time.sleep(retry_delay_seconds)
                            continue
                        oauth_failed_emails.append(
                            paypal_task_payloads_service.paypal_oauth_failed_record(
                                success_email=success_email,
                                error=exc,
                                attempts=max_attempts,
                            )
                        )
                        _append_task_progress(
                            task_id,
                            paypal_task_payloads_service.paypal_oauth_login_failed_progress(
                                success_email=success_email,
                                attempt=attempt,
                                max_attempts=max_attempts,
                                successful_emails=successful_emails,
                                error=exc,
                            ),
                        )
                        logger.exception(
                            "[paypal] OAuth login after PayPal success failed: task_id=%s email=%s attempts=%d",
                            task_id[:8] or "<unknown>",
                            _safe_email_summary(success_email),
                            max_attempts,
                        )
                        return

            threading.Thread(
                target=_oauth_worker,
                name=paypal_task_payloads_service.paypal_oauth_thread_name(success_email),
                daemon=True,
            ).start()

        def _run_paypal_candidate_worker(queue_item: dict[str, Any]) -> dict[str, Any]:
            candidate_email = _normalized_email(queue_item.get("email"))
            index = int(queue_item.get("current") or 0) or 1
            retry_round = int(queue_item.get("retry_round") or 0)
            selected_proxy_url = ""
            effective_checkout_url = checkout_url
            current_candidate_phone = ""
            active_phone_accounts: list[dict] = []
            single_result = None
            try:
                selected_proxy_url = _select_paypal_proxy()
            except Exception as exc:
                return paypal_task_payloads_service.paypal_proxy_api_failed_candidate_result(
                    email=candidate_email,
                    current=index,
                    retry_round=retry_round,
                    error=exc,
                )

            _append_task_progress_threadsafe(
                paypal_task_payloads_service.paypal_starting_progress(
                    email=candidate_email,
                    current=index,
                    total=len(candidates),
                    retry_round=retry_round,
                    concurrency=effective_paypal_concurrency,
                    proxy_label=params.proxy_label,
                )
            )
            if proxy_api_provider or proxy_api_url or normalized_proxy_pool:
                _append_task_progress_threadsafe(
                    paypal_proxy_service.paypal_proxy_selected_progress(
                        email=candidate_email,
                        current=index,
                        total=len(candidates),
                        retry_round=retry_round,
                        proxy_label=params.proxy_label,
                        proxy_pool_count=len(normalized_proxy_pool),
                        proxy_api_url_present=bool(proxy_api_url),
                        proxy_api_provider=proxy_api_provider,
                        selected_proxy_summary=_safe_proxy_summary(selected_proxy_url),
                        using_proxy_api=bool(proxy_api_provider or proxy_api_url),
                    )
                )
            proxy_country_mismatch = _paypal_checkout_proxy_country_mismatch_result(
                candidate_email,
                selected_proxy_url=selected_proxy_url,
            )
            if proxy_country_mismatch is not None:
                _append_task_progress_threadsafe(
                    paypal_ba_service.paypal_checkout_proxy_country_mismatch_progress(
                        email=candidate_email,
                        current=index,
                        total=len(candidates),
                        retry_round=retry_round,
                        detected_country=str(proxy_country_mismatch.get("checkout_proxy_country") or ""),
                        proxy_region=str(proxy_country_mismatch.get("checkout_proxy_region") or ""),
                        proxy_city=str(proxy_country_mismatch.get("checkout_proxy_city") or ""),
                        proxy_ip=str(proxy_country_mismatch.get("checkout_proxy_ip") or ""),
                    )
                )
                return proxy_country_mismatch

            try:
                access_token = ""
                candidate_direct_ba = dict(direct_ba_pre_extracted or {})
                if not candidate_direct_ba and (protocol_no_card or not effective_checkout_url):
                    access_token = _extract_account_access_token(candidate_email)
                if candidate_direct_ba:
                    single_result = None
                elif not effective_checkout_url:
                    if not access_token:
                        single_result = paypal_task_payloads_service.paypal_missing_checkout_access_token_result(
                            email=candidate_email
                        )
                    elif protocol_no_card:
                        single_result = None
                    else:
                        try:
                            generated = _generate_checkout_link_for_paypal_task(
                                access_token, bind_link_payload, proxy_url=selected_proxy_url
                            )
                        except HTTPException as exc:
                            checkout_exc = exc
                            fallback_access_token = access_token
                            if getattr(exc, "status_code", None) == 401:
                                refreshed_access_token = _refresh_account_access_token(candidate_email)
                                if refreshed_access_token and refreshed_access_token != access_token:
                                    fallback_access_token = refreshed_access_token
                                    try:
                                        generated = _generate_checkout_link_for_paypal_task(
                                            refreshed_access_token, bind_link_payload, proxy_url=selected_proxy_url
                                        )
                                        checkout_exc = None
                                    except HTTPException as retry_exc:
                                        checkout_exc = retry_exc
                            if checkout_exc is not None:
                                status_code = int(getattr(checkout_exc, "status_code", 0) or 0)
                                if status_code not in (401, 403, 429, 502, 503, 504):
                                    if checkout_exc is exc:
                                        raise
                                    raise checkout_exc from exc
                                _append_task_progress_threadsafe(
                                    paypal_task_payloads_service.paypal_checkout_browser_fallback_progress(
                                        email=candidate_email,
                                        current=index,
                                        total=len(candidates),
                                        retry_round=retry_round,
                                    )
                                )
                                generated = _generate_checkout_link_via_browser(
                                    fallback_access_token,
                                    bind_link_payload,
                                    email=candidate_email,
                                    proxy_url=selected_proxy_url,
                                    proxy_bypass=params.proxy_bypass,
                                    paypal_browser=paypal_browser,
                                    roxybrowser_workspace_id=roxybrowser_workspace_id,
                                    roxybrowser_profile_id=roxybrowser_profile_id,
                                )
                        effective_checkout_url = str(generated.get("url") or "").strip()
                        _append_task_progress_threadsafe(
                            paypal_task_payloads_service.paypal_checkout_generated_progress(
                                email=candidate_email,
                                current=index,
                                total=len(candidates),
                                retry_round=retry_round,
                                checkout_url=effective_checkout_url,
                            )
                        )
                        single_result = None
                else:
                    single_result = None

                if single_result is None:
                    # ---- Protocol mode: try direct BA link extraction (pplink-style) ----
                    pre_extracted_data = candidate_direct_ba or None
                    if protocol_no_card and access_token and not pre_extracted_data:
                        try:
                            auth_session_context = _paypal_ba_auth_context(candidate_email, access_token)
                            extract_access_token = (
                                str(auth_session_context.get("access_token") or "").strip() or access_token
                            )
                            provider_proxy_url = ""
                            try:
                                provider_proxy_url = _select_paypal_provider_proxy(selected_proxy_url)
                                if provider_proxy_url and provider_proxy_url != selected_proxy_url:
                                    _append_task_progress_threadsafe(
                                        paypal_ba_service.paypal_provider_proxy_selected_progress(
                                            email=candidate_email,
                                            current=index,
                                            total=len(candidates),
                                            retry_round=retry_round,
                                            proxy_label=params.proxy_label,
                                            proxy_api_provider=proxy_api_provider,
                                            proxy_summary=_safe_proxy_summary(provider_proxy_url),
                                        )
                                    )
                            except Exception as provider_proxy_exc:
                                provider_proxy_url = (
                                    _proxy_url_for_region(selected_proxy_url, _paypal_ba_payment_method_country())
                                    or selected_proxy_url
                                )
                                _append_task_progress_threadsafe(
                                    paypal_ba_service.paypal_provider_proxy_failed_progress(
                                        email=candidate_email,
                                        current=index,
                                        total=len(candidates),
                                        retry_round=retry_round,
                                        proxy_label=params.proxy_label,
                                        proxy_api_provider=proxy_api_provider,
                                        error=provider_proxy_exc,
                                    )
                                )
                            pre_extracted_data = _paypal_extract_ba_link(
                                **paypal_ba_service.paypal_ba_extract_kwargs(
                                    auth_session_context=auth_session_context,
                                    access_token=extract_access_token,
                                    proxy_url=selected_proxy_url,
                                    provider_proxy_url=provider_proxy_url,
                                    paypal_country=paypal_country,
                                    payment_method_country=_paypal_ba_payment_method_country(),
                                    paypal_ba_mode=paypal_ba_mode,
                                    timeout_seconds=params.timeout_seconds or 90,
                                    is_cancelled=cancel_signal.is_cancelled,
                                )
                            )
                            max_ba_attempts = _paypal_ba_extract_attempts()
                            if pre_extracted_data.get("status") != "success":
                                _append_task_progress_threadsafe(
                                    paypal_ba_service.paypal_ba_extract_attempt_failed_progress(
                                        email=candidate_email,
                                        current=index,
                                        total=len(candidates),
                                        retry_round=retry_round,
                                        ba_attempt=1,
                                        max_ba_attempts=max_ba_attempts,
                                        result_payload=pre_extracted_data,
                                    )
                                )
                            for ba_attempt in range(2, max_ba_attempts + 1):
                                if pre_extracted_data.get("status") == "success" or cancel_signal.is_cancelled():
                                    break
                                _append_task_progress_threadsafe(
                                    paypal_ba_service.paypal_ba_extract_retry_progress(
                                        email=candidate_email,
                                        current=index,
                                        total=len(candidates),
                                        retry_round=retry_round,
                                        ba_attempt=ba_attempt,
                                        max_ba_attempts=max_ba_attempts,
                                    )
                                )
                                retry_proxy_url = selected_proxy_url
                                retry_provider_proxy_url = provider_proxy_url or retry_proxy_url
                                pre_extracted_data = _paypal_extract_ba_link(
                                    **paypal_ba_service.paypal_ba_extract_kwargs(
                                        auth_session_context=auth_session_context,
                                        access_token=extract_access_token,
                                        proxy_url=retry_proxy_url,
                                        provider_proxy_url=retry_provider_proxy_url,
                                        paypal_country=paypal_country,
                                        payment_method_country=_paypal_ba_payment_method_country(),
                                        paypal_ba_mode=paypal_ba_mode,
                                        timeout_seconds=params.timeout_seconds or 90,
                                        is_cancelled=cancel_signal.is_cancelled,
                                    )
                                )
                                if pre_extracted_data.get("status") != "success":
                                    _append_task_progress_threadsafe(
                                        paypal_ba_service.paypal_ba_extract_attempt_failed_progress(
                                            email=candidate_email,
                                            current=index,
                                            total=len(candidates),
                                            retry_round=retry_round,
                                            ba_attempt=ba_attempt,
                                            max_ba_attempts=max_ba_attempts,
                                            result_payload=pre_extracted_data,
                                        )
                                    )
                            extracted_checkout_url = str(pre_extracted_data.get("checkout_url") or "").strip()
                            if extracted_checkout_url:
                                effective_checkout_url = extracted_checkout_url
                                _append_task_progress_threadsafe(
                                    paypal_ba_service.paypal_checkout_long_link_extracted_progress(
                                        email=candidate_email,
                                        current=index,
                                        total=len(candidates),
                                        checkout_url=effective_checkout_url,
                                    )
                                )
                            if pre_extracted_data.get("status") == "success":
                                pre_extracted_data.setdefault("checkout_url", effective_checkout_url)
                                _append_task_progress_threadsafe(
                                    paypal_ba_service.paypal_ba_extracted_progress(
                                        email=candidate_email,
                                        current=index,
                                        total=len(candidates),
                                        ba_token=pre_extracted_data.get("ba_token"),
                                    )
                                )
                            else:
                                _append_task_progress_threadsafe(
                                    paypal_ba_service.paypal_ba_extract_failed_progress(
                                        email=candidate_email,
                                        current=index,
                                        total=len(candidates),
                                        result_payload=pre_extracted_data,
                                    )
                                )
                        except Exception as extract_exc:
                            logger.info("[paypal_extract] ba link extraction exception: %s", extract_exc)
                            pre_extracted_data = None

                    active_phone_accounts, current_sms_url, current_otp_channel, current_candidate_phone = (
                        _lease_paypal_phone_accounts_for_item(queue_item)
                    )
                    if phone_accounts and not active_phone_accounts:
                        with phone_lock:
                            reserved_count = len(reserved_phone_keys)
                            invalid_count = len(invalid_phone_numbers)
                        phone_pool_message = (
                            "手机号池没有未占用的可用号码，当前账号不会启动浏览器"
                            f"（本任务已占用 {reserved_count} 个，已失效 {invalid_count} 个）"
                        )
                        _append_task_progress_threadsafe(
                            paypal_task_payloads_service.paypal_phone_pool_exhausted_progress(
                                email=candidate_email,
                                current=index,
                                total=len(candidates),
                                retry_round=retry_round,
                                reserved_phone_count=reserved_count,
                                invalid_phone_count=invalid_count,
                                message=phone_pool_message,
                                level="warn",
                            )
                        )
                        single_result = paypal_task_payloads_service.paypal_phone_pool_exhausted_result(
                            email=candidate_email,
                            message="手机号池没有未占用的可用号码，当前账号未启动浏览器",
                        )
                    else:
                        current_autofill_payload = _candidate_autofill_payload(candidate_email)
                        if current_candidate_phone:
                            current_autofill_payload["phone"] = current_candidate_phone

                        def _handle_paypal_progress(event: dict[str, Any]) -> None:
                            stage = str(event.get("stage") or "").strip()
                            if stage in {
                                "paypal_phone_rejected_waiting_dismiss",
                                "paypal_phone_rejected_rotate",
                                "paypal_phone_rejected_final",
                            }:
                                _remember_invalid_phone_threadsafe(event.get("rejected_phone"))
                                with phone_lock:
                                    event = {**event, "invalid_phone_numbers": invalid_phone_pool[:]}
                            _append_task_progress_threadsafe(
                                {**event, "email": candidate_email, "current": index, "total": len(candidates)}
                            )

                        if (
                            protocol_no_card
                            and pre_extracted_data
                            and pre_extracted_data.get("status") != "success"
                            and not pre_extracted_data.get("ba_token")
                        ):
                            single_result = dict(pre_extracted_data)
                        else:
                            single_result = run_paypal_bind_task(
                                email=candidate_email,
                                checkout_url=effective_checkout_url,
                                proxy_url=selected_proxy_url,
                                proxy_bypass=params.proxy_bypass,
                                manual_confirm=params.manual_confirm,
                                timeout_seconds=max(60, int(params.timeout_seconds or 60)),
                                is_cancelled=cancel_signal.is_cancelled,
                                on_progress=_handle_paypal_progress,
                                autofill_enabled=bool(params.autofill_enabled),
                                autofill_payload=current_autofill_payload,
                                paypal_mode=paypal_mode,
                                paypal_email=params.paypal_email,
                                paypal_password=params.paypal_password,
                                sms_url=current_sms_url,
                                otp_channel=current_otp_channel,
                                phone_accounts=active_phone_accounts,
                                paypal_card_number=params.paypal_card_number,
                                paypal_card_expiry=params.paypal_card_expiry,
                                paypal_card_cvv=params.paypal_card_cvv,
                                paypal_browser=paypal_browser,
                                paypal_fallback_browser=paypal_fallback_browser,
                                paypal_country=paypal_country,
                                paypal_lang=paypal_lang,
                                roxybrowser_workspace_id=roxybrowser_workspace_id,
                                roxybrowser_profile_id=roxybrowser_profile_id,
                                pre_extracted=pre_extracted_data,
                            )
            except HTTPException as exc:
                exc_message = str(exc.detail) if getattr(exc, "detail", None) else str(exc)
                single_result = (
                    _paypal_user_paid_success(candidate_email, exc_message)
                    if _paypal_already_paid_text(exc_message)
                    else paypal_task_payloads_service.paypal_checkout_failed_result(
                        email=candidate_email,
                        message=exc_message,
                    )
                )
            except Exception as exc:
                logger.exception("[paypal] candidate error: email=%s", candidate_email)
                single_result = paypal_task_payloads_service.paypal_candidate_exception_result(
                    email=candidate_email,
                    error=exc,
                )
            finally:
                if isinstance(single_result, dict) and single_result.get("failure_stage") == "paypal_phone_rejected":
                    _remember_invalid_phone_threadsafe(single_result.get("rejected_phone") or current_candidate_phone)
                _release_paypal_phone_accounts(active_phone_accounts)

            single_result = paypal_task_payloads_service.normalize_paypal_candidate_result(
                single_result=single_result,
                candidate_email=candidate_email,
                effective_checkout_url=effective_checkout_url,
            )
            with phone_lock:
                rejected_phone, single_result = paypal_task_payloads_service.paypal_candidate_phone_rejection_update(
                    single_result=single_result,
                    current_candidate_phone=current_candidate_phone,
                    invalid_phone_pool=invalid_phone_pool,
                )
            if rejected_phone:
                _remember_invalid_phone_threadsafe(rejected_phone)
            return {
                "email": candidate_email,
                "index": index,
                "retry_round": retry_round,
                "selected_proxy_url": selected_proxy_url,
                "current_candidate_phone": current_candidate_phone,
                "active_phone_accounts": active_phone_accounts,
                "result": single_result,
            }

        def _apply_paypal_candidate_outcome(item: dict[str, Any]) -> None:
            nonlocal result, last_checkout_url
            candidate_email = _normalized_email(item.get("email"))
            index = int(item.get("index") or 0) or 1
            selected_proxy_url = str(item.get("selected_proxy_url") or "")
            single_result = dict(item.get("result") or {})
            active_phone_accounts = item.get("active_phone_accounts") if isinstance(item.get("active_phone_accounts"), list) else []
            if not candidate_email:
                return
            _close_paypal_sms_bridges_for_result(active_phone_accounts, single_result)
            last_checkout_url = single_result.get("checkout_url") or last_checkout_url
            result = single_result
            update_fields = paypal_task_payloads_service.paypal_bind_update_fields(
                single_result=single_result,
                is_cancelled=cancel_signal.is_cancelled(),
                proxy_label=params.proxy_label,
                task_id=task_id,
                bind_at=time.time(),
                success_account_fields=paypal_success_account_fields,
            )
            updated_account = update_account(candidate_email, **update_fields)
            if single_result.get("status") == "success" and not updated_account:
                add_account(candidate_email, "", seat_type=SEAT_CODEX)
                updated_account = update_account(candidate_email, **update_fields)
            if paypal_task_payloads_service.paypal_success_persistence_warning_needed(
                single_result=single_result,
                updated_account=updated_account,
            ):
                logger.warning(
                    "[paypal] PayPal success account was not persisted: task_id=%s email=%s",
                    task_id[:8] or "<unknown>",
                    _safe_email_summary(candidate_email),
                )
            outcome_flags = paypal_task_payloads_service.paypal_candidate_outcome_flags(
                single_result=single_result,
                candidate_email=candidate_email,
                nonzero_blocked_pool_emails=_paypal_nonzero_blocked_pool_emails(single_result, candidate_email),
            )
            if outcome_flags["success"]:
                updated_account = _update_paypal_success_plan_type(candidate_email, updated_account)
                _append_unique(successful_emails, candidate_email)
                _handle_paypal_success_auth(candidate_email, selected_proxy_url)
            else:
                _append_unique(failed_emails, candidate_email)
                if outcome_flags["nonzero_blocked"]:
                    _append_unique(nonzero_blocked_emails, candidate_email)
                    cleanup_request = paypal_task_payloads_service.paypal_nonzero_amount_blocked_cleanup_request(
                        candidate_email=candidate_email,
                        current=index,
                        total=len(candidates),
                    )
                    removed = _remove_pool_accounts_from_local_and_mail(
                        cleanup_request["emails"],
                        log_context=cleanup_request["log_context"],
                        reason=cleanup_request["reason"],
                        message=cleanup_request["message"],
                    )
                    for removed_email in removed:
                        _append_unique(removed_pool_emails, removed_email)
                    _append_task_progress(task_id, cleanup_request["progress"])
            record_bind_audit(
                paypal_task_payloads_service.paypal_bind_audit_record(
                    task_id=task_id,
                    candidate_email=candidate_email,
                    single_result=single_result,
                    proxy_label=params.proxy_label,
                    selected_proxy_url=selected_proxy_url,
                    manual_confirm=params.manual_confirm,
                    paypal_mode=paypal_mode,
                    paypal_country=paypal_country,
                    paypal_lang=paypal_lang,
                    paypal_password=params.paypal_password,
                    autofill_enabled=params.autofill_enabled,
                    started_at=started_at,
                    finished_at=time.time(),
                )
            )

        parallel_completed = False
        parallel_retry_items: list[dict[str, Any]] = []
        if effective_paypal_concurrency > 1 and len(candidates) > 1:
            parallel_completed = True
            initial_items = [
                {"email": candidate_email, "current": index, "retry_round": 0}
                for index, candidate_email in enumerate(candidates, start=1)
            ]
            initial_items = _assign_paypal_phone_accounts_to_items(initial_items)
            _append_task_progress(
                task_id,
                paypal_task_payloads_service.paypal_parallel_started_progress(
                    total=len(candidates),
                    concurrency=effective_paypal_concurrency,
                ),
            )
            with ThreadPoolExecutor(
                max_workers=effective_paypal_concurrency, thread_name_prefix="paypal-bind"
            ) as executor:
                future_map = {executor.submit(_run_paypal_candidate_worker, item): item for item in initial_items}
                for future in as_completed(future_map):
                    item = future.result()
                    single_result = dict(item.get("result") or {})
                    retry_reason = _paypal_candidate_retry_reason(single_result)
                    if single_result.get("status") != "success" and retry_reason and pending_retry_attempts > 0:
                        candidate_email = _normalized_email(item.get("email"))
                        _append_unique(pending_retry_emails, candidate_email)
                        parallel_retry_items.append(
                            {
                                "email": candidate_email,
                                "current": int(item.get("index") or 0) or 1,
                                "retry_round": 1,
                            }
                        )
                        _append_task_progress(
                            task_id,
                            paypal_pending_retry_service.parallel_first_round_queued_progress(
                                candidate_email=candidate_email,
                                current_index=int(item.get("index") or 0) or 1,
                                total_count=len(candidates),
                                retry_round=1,
                                max_retry_rounds=pending_retry_attempts,
                                reason=retry_reason,
                                result_payload=single_result,
                                source_stage=_paypal_pending_retry_source_stage,
                            ),
                        )
                    else:
                        _apply_paypal_candidate_outcome(item)

        def _run_paypal_parallel_retry_rounds(items: list[dict[str, Any]]) -> None:
            current_items = list(items or [])
            while current_items and not cancel_signal.is_cancelled():
                retry_round = min(max(1, int(item.get("retry_round") or 1)) for item in current_items)
                round_items = [item for item in current_items if int(item.get("retry_round") or 1) == retry_round]
                current_items = [item for item in current_items if int(item.get("retry_round") or 1) != retry_round]
                if not round_items:
                    continue
                round_items = _assign_paypal_phone_accounts_to_items(round_items)
                round_concurrency = _paypal_retry_round_concurrency(round_items)
                _maybe_wait_pending_retry_round(retry_round, len(round_items))
                for round_item in round_items:
                    candidate_email = _normalized_email(round_item.get("email"))
                    if not candidate_email:
                        continue
                    _remove_from_pending_retry(candidate_email)
                    _append_unique(retried_emails, candidate_email)
                    _append_task_progress(
                        task_id,
                        paypal_task_payloads_service.paypal_pending_retry_account_progress(
                            email=candidate_email,
                            current=int(round_item.get("current") or 0) or 1,
                            total=len(candidates),
                            retry_round=retry_round,
                            max_retry_rounds=pending_retry_attempts,
                            pending_retry=len(pending_retry_emails),
                            concurrency=round_concurrency,
                        ),
                    )
                _append_task_progress(
                    task_id,
                    paypal_pending_retry_service.pending_retry_started_progress(
                        retry_round=retry_round,
                        max_retry_rounds=pending_retry_attempts,
                        pending_count=len(round_items),
                        concurrency=round_concurrency,
                    ),
                )
                next_round_items: list[dict[str, Any]] = []
                with ThreadPoolExecutor(
                    max_workers=round_concurrency, thread_name_prefix=f"paypal-retry-{retry_round}"
                ) as executor:
                    future_map = {executor.submit(_run_paypal_candidate_worker, item): item for item in round_items}
                    for future in as_completed(future_map):
                        item = future.result()
                        single_result = dict(item.get("result") or {})
                        candidate_email = _normalized_email(item.get("email"))
                        index = int(item.get("index") or 0) or 1
                        retry_reason = _paypal_candidate_retry_reason(single_result)
                        if (
                            candidate_email
                            and single_result.get("status") != "success"
                            and retry_reason
                            and retry_round < pending_retry_attempts
                        ):
                            _append_unique(pending_retry_emails, candidate_email)
                            next_item = {
                                "email": candidate_email,
                                "current": index,
                                "retry_round": retry_round + 1,
                            }
                            next_round_items.append(next_item)
                            _append_task_progress(
                                task_id,
                                paypal_pending_retry_service.parallel_next_round_queued_progress(
                                    candidate_email=candidate_email,
                                    current_index=index,
                                    total_count=len(candidates),
                                    pending_retry_count=len(pending_retry_emails),
                                    source_retry_round=retry_round,
                                    retry_round=retry_round + 1,
                                    max_retry_rounds=pending_retry_attempts,
                                    reason=retry_reason,
                                    result_payload=single_result,
                                    source_stage=_paypal_pending_retry_source_stage,
                                ),
                            )
                        else:
                            _apply_paypal_candidate_outcome(item)
                current_items.extend(next_round_items)

        try:
            candidate_queue: list[dict[str, Any]] = [
                {"email": candidate_email, "current": index, "retry_round": 0}
                for index, candidate_email in enumerate(candidates, start=1)
            ]
            if parallel_completed:
                _run_paypal_parallel_retry_rounds(parallel_retry_items)
                candidate_queue = []
            queue_offset = 0
            while queue_offset < len(candidate_queue):
                if cancel_signal.is_cancelled():
                    break
                queue_item = candidate_queue[queue_offset]
                queue_offset += 1
                candidate_email = _normalized_email(queue_item.get("email"))
                if not candidate_email:
                    continue
                index = int(queue_item.get("current") or 0) or min(queue_offset, len(candidates))
                retry_round = int(queue_item.get("retry_round") or 0)
                if retry_round > 0:
                    _maybe_wait_pending_retry_round(retry_round, len(pending_retry_emails) or 1)
                    _remove_from_pending_retry(candidate_email)
                    _append_unique(retried_emails, candidate_email)
                    _append_task_progress(
                        task_id,
                        paypal_task_payloads_service.paypal_pending_retry_account_progress(
                            email=candidate_email,
                            current=index,
                            total=len(candidates),
                            retry_round=retry_round,
                            max_retry_rounds=pending_retry_attempts,
                            pending_retry=len(pending_retry_emails),
                        ),
                    )
                stop_after_current_candidate = False
                current_candidate_phone = ""
                active_phone_accounts: list[dict] = []
                single_result = None
                selected_proxy_url = ""
                effective_checkout_url = checkout_url
                try:
                    selected_proxy_url = _select_paypal_proxy()
                except Exception as exc:
                    single_result = paypal_task_payloads_service.paypal_proxy_api_failed_result(
                        email=candidate_email,
                        error=exc,
                    )
                    retry_reason = _paypal_retryable_result(single_result)
                    if retry_reason and retry_round < pending_retry_attempts:
                        _queue_paypal_pending_retry(
                            candidate_email,
                            reason=retry_reason,
                            result_payload=single_result,
                            retry_round=retry_round + 1,
                            current_index=index,
                            total_count=len(candidates),
                        )
                        result = single_result
                        continue
                    _append_task_progress(
                        task_id,
                        paypal_proxy_service.paypal_proxy_api_failed_progress(
                            email=candidate_email,
                            current=index,
                            total=len(candidates),
                            proxy_label=params.proxy_label,
                            proxy_api_provider=proxy_api_provider,
                            error=exc,
                        ),
                    )
                    _append_unique(failed_emails, candidate_email)
                    result = single_result
                    continue
                _append_task_progress(
                    task_id,
                    paypal_task_payloads_service.paypal_starting_progress(
                        email=candidate_email,
                        current=index,
                        total=len(candidates),
                        proxy_label=params.proxy_label,
                    ),
                )
                if proxy_api_provider or proxy_api_url or normalized_proxy_pool:
                    _append_task_progress(
                        task_id,
                        paypal_proxy_service.paypal_proxy_selected_progress(
                            email=candidate_email,
                            current=index,
                            total=len(candidates),
                            proxy_label=params.proxy_label,
                            proxy_pool_count=len(normalized_proxy_pool),
                            proxy_api_url_present=bool(proxy_api_url),
                            proxy_api_provider=proxy_api_provider,
                            selected_proxy_summary=_safe_proxy_summary(selected_proxy_url),
                            using_proxy_api=bool(proxy_api_provider or proxy_api_url),
                        ),
                    )
                    exit_ip = _probe_proxy_exit_ip(selected_proxy_url) if (proxy_api_provider or proxy_api_url) else ""
                    if exit_ip:
                        _append_task_progress(
                            task_id,
                            paypal_proxy_service.paypal_proxy_api_probe_progress(
                                email=candidate_email,
                                current=index,
                                total=len(candidates),
                                proxy_label=params.proxy_label,
                                proxy_api_provider=proxy_api_provider,
                                exit_ip=exit_ip,
                            ),
                        )
                proxy_country_mismatch = _paypal_checkout_proxy_country_mismatch_result(
                    candidate_email,
                    selected_proxy_url=selected_proxy_url,
                )
                if proxy_country_mismatch is not None:
                    _append_task_progress(
                        task_id,
                        paypal_ba_service.paypal_checkout_proxy_country_mismatch_progress(
                            email=candidate_email,
                            current=index,
                            total=len(candidates),
                            detected_country=str(proxy_country_mismatch.get("checkout_proxy_country") or ""),
                            proxy_region=str(proxy_country_mismatch.get("checkout_proxy_region") or ""),
                            proxy_city=str(proxy_country_mismatch.get("checkout_proxy_city") or ""),
                            proxy_ip=str(proxy_country_mismatch.get("checkout_proxy_ip") or ""),
                        ),
                    )
                    retry_reason = _paypal_retryable_result(proxy_country_mismatch)
                    if retry_reason and retry_round < pending_retry_attempts:
                        _queue_paypal_pending_retry(
                            candidate_email,
                            reason=retry_reason,
                            result_payload=proxy_country_mismatch,
                            retry_round=retry_round + 1,
                            current_index=index,
                            total_count=len(candidates),
                        )
                        result = proxy_country_mismatch
                        continue
                    _append_unique(failed_emails, candidate_email)
                    result = proxy_country_mismatch
                    continue
                try:
                    effective_checkout_url = checkout_url
                    access_token = ""
                    candidate_direct_ba = dict(direct_ba_pre_extracted or {})
                    if not candidate_direct_ba and (protocol_no_card or not effective_checkout_url):
                        access_token = _extract_account_access_token(candidate_email)
                    if candidate_direct_ba:
                        single_result = None
                    elif not effective_checkout_url:
                        if not access_token:
                            single_result = paypal_task_payloads_service.paypal_missing_checkout_access_token_result(
                                email=candidate_email
                            )
                        elif protocol_no_card:
                            single_result = None
                        else:
                            try:
                                generated = _generate_checkout_link_for_paypal_task(
                                    access_token, bind_link_payload, proxy_url=selected_proxy_url
                                )
                            except HTTPException as exc:
                                checkout_exc = exc
                                fallback_access_token = access_token
                                if getattr(exc, "status_code", None) == 401:
                                    refreshed_access_token = _refresh_account_access_token(candidate_email)
                                    if refreshed_access_token and refreshed_access_token != access_token:
                                        fallback_access_token = refreshed_access_token
                                        _append_task_progress(
                                            task_id,
                                            paypal_task_payloads_service.paypal_checkout_token_refreshed_progress(
                                                email=candidate_email,
                                                current=index,
                                                total=len(candidates),
                                            ),
                                        )
                                        try:
                                            generated = _generate_checkout_link_for_paypal_task(
                                                refreshed_access_token, bind_link_payload, proxy_url=selected_proxy_url
                                            )
                                            checkout_exc = None
                                        except HTTPException as retry_exc:
                                            checkout_exc = retry_exc
                                    elif refreshed_access_token:
                                        checkout_exc = HTTPException(
                                            status_code=401,
                                            detail="生成 checkout 返回 401，session 刷新后 access_token 未变化；请重新登录/刷新该账号 auth_session 后再试",
                                        )
                                if checkout_exc is not None:
                                    status_code = int(getattr(checkout_exc, "status_code", 0) or 0)
                                    if status_code not in (401, 403, 429, 502, 503, 504):
                                        if checkout_exc is exc:
                                            raise
                                        raise checkout_exc from exc
                                    _append_task_progress(
                                        task_id,
                                        paypal_task_payloads_service.paypal_checkout_browser_fallback_progress(
                                            email=candidate_email,
                                            current=index,
                                            total=len(candidates),
                                        ),
                                    )
                                    try:
                                        generated = _generate_checkout_link_via_browser(
                                            fallback_access_token,
                                            bind_link_payload,
                                            email=candidate_email,
                                            proxy_url=selected_proxy_url,
                                            proxy_bypass=params.proxy_bypass,
                                            paypal_browser=paypal_browser,
                                            roxybrowser_workspace_id=roxybrowser_workspace_id,
                                            roxybrowser_profile_id=roxybrowser_profile_id,
                                        )
                                    except HTTPException as browser_exc:
                                        raise HTTPException(
                                            status_code=getattr(browser_exc, "status_code", None) or status_code or 502,
                                            detail=(
                                                f"HTTP 生成 checkout 失败: {getattr(checkout_exc, 'detail', checkout_exc)}；"
                                                f"浏览器回退失败: {getattr(browser_exc, 'detail', browser_exc)}"
                                            ),
                                        ) from browser_exc
                                    _append_task_progress(
                                        task_id,
                                        paypal_task_payloads_service.paypal_checkout_browser_generated_progress(
                                            email=candidate_email,
                                            current=index,
                                            total=len(candidates),
                                        ),
                                    )
                            effective_checkout_url = str(generated.get("url") or "").strip()
                            last_checkout_url = effective_checkout_url or last_checkout_url
                            _append_task_progress(
                                task_id,
                                paypal_task_payloads_service.paypal_checkout_generated_progress(
                                    email=candidate_email,
                                    current=index,
                                    total=len(candidates),
                                    checkout_url=effective_checkout_url,
                                ),
                            )
                            single_result = None
                    else:
                        single_result = None
                    if single_result is None:
                        pre_extracted_data = candidate_direct_ba or None
                        if protocol_no_card and access_token and not pre_extracted_data:
                            try:
                                auth_session_context = _paypal_ba_auth_context(candidate_email, access_token)
                                extract_access_token = (
                                    str(auth_session_context.get("access_token") or "").strip() or access_token
                                )
                                provider_proxy_url = ""
                                try:
                                    provider_proxy_url = _select_paypal_provider_proxy(selected_proxy_url)
                                    if provider_proxy_url and provider_proxy_url != selected_proxy_url:
                                        _append_task_progress(
                                            task_id,
                                            paypal_ba_service.paypal_provider_proxy_selected_progress(
                                                email=candidate_email,
                                                current=index,
                                                total=len(candidates),
                                                proxy_label=params.proxy_label,
                                                proxy_api_provider=proxy_api_provider,
                                                proxy_summary=_safe_proxy_summary(provider_proxy_url),
                                            ),
                                        )
                                except Exception as provider_proxy_exc:
                                    provider_proxy_url = (
                                        _proxy_url_for_region(selected_proxy_url, _paypal_ba_payment_method_country())
                                        or selected_proxy_url
                                    )
                                    _append_task_progress(
                                        task_id,
                                        paypal_ba_service.paypal_provider_proxy_failed_progress(
                                            email=candidate_email,
                                            current=index,
                                            total=len(candidates),
                                            proxy_label=params.proxy_label,
                                            proxy_api_provider=proxy_api_provider,
                                            error=provider_proxy_exc,
                                        ),
                                    )
                                pre_extracted_data = _paypal_extract_ba_link(
                                    **paypal_ba_service.paypal_ba_extract_kwargs(
                                        auth_session_context=auth_session_context,
                                        access_token=extract_access_token,
                                        proxy_url=selected_proxy_url,
                                        provider_proxy_url=provider_proxy_url,
                                        paypal_country=paypal_country,
                                        payment_method_country=_paypal_ba_payment_method_country(),
                                        paypal_ba_mode=paypal_ba_mode,
                                        timeout_seconds=params.timeout_seconds or 90,
                                        is_cancelled=cancel_signal.is_cancelled,
                                    )
                                )
                                max_ba_attempts = _paypal_ba_extract_attempts()
                                if pre_extracted_data.get("status") != "success":
                                    _append_task_progress(
                                        task_id,
                                        paypal_ba_service.paypal_ba_extract_attempt_failed_progress(
                                            email=candidate_email,
                                            current=index,
                                            total=len(candidates),
                                            ba_attempt=1,
                                            max_ba_attempts=max_ba_attempts,
                                            result_payload=pre_extracted_data,
                                        ),
                                    )
                                for ba_attempt in range(2, max_ba_attempts + 1):
                                    if pre_extracted_data.get("status") == "success" or cancel_signal.is_cancelled():
                                        break
                                    _append_task_progress(
                                        task_id,
                                        paypal_ba_service.paypal_ba_extract_retry_progress(
                                            email=candidate_email,
                                            current=index,
                                            total=len(candidates),
                                            ba_attempt=ba_attempt,
                                            max_ba_attempts=max_ba_attempts,
                                        ),
                                    )
                                    retry_proxy_url = selected_proxy_url
                                    retry_provider_proxy_url = provider_proxy_url or retry_proxy_url
                                    if retry_provider_proxy_url and retry_provider_proxy_url != retry_proxy_url:
                                        _append_task_progress(
                                            task_id,
                                            paypal_ba_service.paypal_approve_proxy_selected_progress(
                                                email=candidate_email,
                                                current=index,
                                                total=len(candidates),
                                                proxy_label=params.proxy_label,
                                                proxy_api_provider=proxy_api_provider,
                                                proxy_summary=_safe_proxy_summary(retry_provider_proxy_url),
                                                ba_attempt=ba_attempt,
                                            ),
                                        )
                                    pre_extracted_data = _paypal_extract_ba_link(
                                        **paypal_ba_service.paypal_ba_extract_kwargs(
                                            auth_session_context=auth_session_context,
                                            access_token=extract_access_token,
                                            proxy_url=retry_proxy_url,
                                            provider_proxy_url=retry_provider_proxy_url,
                                            paypal_country=paypal_country,
                                            payment_method_country=_paypal_ba_payment_method_country(),
                                            paypal_ba_mode=paypal_ba_mode,
                                            timeout_seconds=params.timeout_seconds or 90,
                                            is_cancelled=cancel_signal.is_cancelled,
                                        )
                                    )
                                    if pre_extracted_data.get("status") != "success":
                                        _append_task_progress(
                                            task_id,
                                            paypal_ba_service.paypal_ba_extract_attempt_failed_progress(
                                                email=candidate_email,
                                                current=index,
                                                total=len(candidates),
                                                ba_attempt=ba_attempt,
                                                max_ba_attempts=max_ba_attempts,
                                                result_payload=pre_extracted_data,
                                            ),
                                        )
                                extracted_checkout_url = str(pre_extracted_data.get("checkout_url") or "").strip()
                                if extracted_checkout_url:
                                    effective_checkout_url = extracted_checkout_url
                                    last_checkout_url = effective_checkout_url or last_checkout_url
                                    _append_task_progress(
                                        task_id,
                                        paypal_ba_service.paypal_checkout_long_link_extracted_progress(
                                            email=candidate_email,
                                            current=index,
                                            total=len(candidates),
                                            checkout_url=effective_checkout_url,
                                        ),
                                    )
                                if pre_extracted_data.get("status") == "success":
                                    pre_extracted_data.setdefault("checkout_url", effective_checkout_url)
                                    _append_task_progress(
                                        task_id,
                                        paypal_ba_service.paypal_ba_extracted_progress(
                                            email=candidate_email,
                                            current=index,
                                            total=len(candidates),
                                            ba_token=pre_extracted_data.get("ba_token"),
                                        ),
                                    )
                                else:
                                    _append_task_progress(
                                        task_id,
                                        paypal_ba_service.paypal_ba_extract_failed_progress(
                                            email=candidate_email,
                                            current=index,
                                            total=len(candidates),
                                            result_payload=pre_extracted_data,
                                        ),
                                    )
                            except Exception as extract_exc:
                                logger.info("[paypal_extract] ba link extraction exception: %s", extract_exc)
                                pre_extracted_data = None

                        active_phone_accounts = phone_accounts
                        current_sms_url = sms_url
                        current_otp_channel = otp_channel
                        current_autofill_payload = _candidate_autofill_payload(candidate_email)
                        if phone_accounts:
                            active_phone_accounts = [
                                account_phone
                                for account_phone in phone_accounts
                                if _paypal_phone_account_available(account_phone, invalid_phone_numbers)
                            ]
                            if not active_phone_accounts:
                                _append_task_progress(
                                    task_id,
                                    paypal_task_payloads_service.paypal_phone_pool_exhausted_progress(
                                        email=candidate_email,
                                        current=index,
                                        total=len(candidates),
                                        message="手机号池已无可用号码，停止后续 PayPal 绑定任务",
                                        level="error",
                                    ),
                                )
                                single_result = paypal_task_payloads_service.paypal_phone_pool_exhausted_result(
                                    email=candidate_email,
                                    message="手机号池已无可用号码",
                                )
                                stop_after_current_candidate = True
                            else:
                                first_active_phone = active_phone_accounts[0]
                                current_sms_url = str(first_active_phone.get("sms_url") or "").strip()
                                current_otp_channel = (
                                    str(first_active_phone.get("otp_channel") or otp_channel or "sms").strip().lower()
                                    or "sms"
                                )
                                current_billing_phone = str(first_active_phone.get("phone_number") or "").strip()
                                if current_billing_phone:
                                    current_candidate_phone = current_billing_phone
                                    current_autofill_payload["phone"] = current_billing_phone
                        if single_result is None:

                            def _handle_paypal_progress(
                                event: dict[str, Any],
                                *,
                                progress_email: str = candidate_email,
                                progress_index: int = index,
                                progress_total: int = len(candidates),
                            ) -> None:
                                stage = str(event.get("stage") or "").strip()
                                if stage in {
                                    "paypal_phone_rejected_waiting_dismiss",
                                    "paypal_phone_rejected_rotate",
                                    "paypal_phone_rejected_final",
                                }:
                                    _remember_invalid_phone(event.get("rejected_phone"))
                                    event = {
                                        **event,
                                        "invalid_phone_numbers": invalid_phone_pool[:],
                                    }
                                _append_task_progress(
                                    task_id,
                                    {
                                        **event,
                                        "email": progress_email,
                                        "current": progress_index,
                                        "total": progress_total,
                                    },
                                )

                            if (
                                protocol_no_card
                                and pre_extracted_data
                                and pre_extracted_data.get("status") != "success"
                                and not pre_extracted_data.get("ba_token")
                            ):
                                single_result = dict(pre_extracted_data)
                            else:
                                single_result = run_paypal_bind_task(
                                    email=candidate_email,
                                    checkout_url=effective_checkout_url,
                                    proxy_url=selected_proxy_url,
                                    proxy_bypass=params.proxy_bypass,
                                    manual_confirm=params.manual_confirm,
                                    timeout_seconds=max(60, int(params.timeout_seconds or 60)),
                                    is_cancelled=cancel_signal.is_cancelled,
                                    on_progress=_handle_paypal_progress,
                                    autofill_enabled=bool(params.autofill_enabled),
                                    autofill_payload=current_autofill_payload,
                                    paypal_mode=paypal_mode,
                                    paypal_email=params.paypal_email,
                                    paypal_password=params.paypal_password,
                                    sms_url=current_sms_url,
                                    otp_channel=current_otp_channel,
                                    phone_accounts=active_phone_accounts,
                                    paypal_card_number=params.paypal_card_number,
                                    paypal_card_expiry=params.paypal_card_expiry,
                                    paypal_card_cvv=params.paypal_card_cvv,
                                    paypal_browser=paypal_browser,
                                    paypal_fallback_browser=paypal_fallback_browser,
                                    paypal_country=paypal_country,
                                    paypal_lang=paypal_lang,
                                    roxybrowser_workspace_id=roxybrowser_workspace_id,
                                    roxybrowser_profile_id=roxybrowser_profile_id,
                                    pre_extracted=pre_extracted_data,
                                )
                except HTTPException as exc:
                    exc_message = str(exc.detail) if getattr(exc, "detail", None) else str(exc)
                    if _paypal_already_paid_text(exc_message):
                        single_result = _paypal_user_paid_success(candidate_email, exc_message)
                    else:
                        single_result = paypal_task_payloads_service.paypal_checkout_failed_result(
                            email=candidate_email,
                            message=exc_message,
                        )
                except Exception as exc:
                    logger.exception("[paypal] candidate error: email=%s", candidate_email)
                    single_result = paypal_task_payloads_service.paypal_candidate_exception_result(
                        email=candidate_email,
                        error=exc,
                    )
                single_result = paypal_task_payloads_service.normalize_paypal_candidate_result(
                    single_result=single_result,
                    candidate_email=candidate_email,
                    effective_checkout_url=effective_checkout_url,
                )
                rejected_phone, single_result = paypal_task_payloads_service.paypal_candidate_phone_rejection_update(
                    single_result=single_result,
                    current_candidate_phone=current_candidate_phone,
                    invalid_phone_pool=invalid_phone_pool,
                )
                if rejected_phone:
                    _remember_invalid_phone(rejected_phone)
                last_checkout_url = single_result["checkout_url"] or last_checkout_url
                result = single_result
                retry_reason = _paypal_candidate_retry_reason(single_result)
                if single_result.get("status") != "success" and retry_reason and retry_round < pending_retry_attempts:
                    _queue_paypal_pending_retry(
                        candidate_email,
                        reason=retry_reason,
                        result_payload=single_result,
                        retry_round=retry_round + 1,
                        current_index=index,
                        total_count=len(candidates),
                    )
                    continue
                _close_paypal_sms_bridges_for_result(active_phone_accounts, single_result)
                update_fields = paypal_task_payloads_service.paypal_bind_update_fields(
                    single_result=single_result,
                    is_cancelled=cancel_signal.is_cancelled(),
                    proxy_label=params.proxy_label,
                    task_id=task_id,
                    bind_at=time.time(),
                    success_account_fields=paypal_success_account_fields,
                )
                updated_account = update_account(
                    candidate_email,
                    **update_fields,
                )
                if single_result.get("status") == "success" and not updated_account:
                    add_account(candidate_email, "", seat_type=SEAT_CODEX)
                    updated_account = update_account(
                        candidate_email,
                        **update_fields,
                    )
                if paypal_task_payloads_service.paypal_success_persistence_warning_needed(
                    single_result=single_result,
                    updated_account=updated_account,
                ):
                    logger.warning(
                        "[paypal] PayPal success account was not persisted: task_id=%s email=%s",
                        task_id[:8] or "<unknown>",
                        _safe_email_summary(candidate_email),
                    )
                outcome_flags = paypal_task_payloads_service.paypal_candidate_outcome_flags(
                    single_result=single_result,
                    candidate_email=candidate_email,
                    nonzero_blocked_pool_emails=_paypal_nonzero_blocked_pool_emails(single_result, candidate_email),
                )
                if outcome_flags["success"]:
                    updated_account = _update_paypal_success_plan_type(candidate_email, updated_account)
                    _append_unique(successful_emails, candidate_email)
                    _handle_paypal_success_auth(candidate_email, selected_proxy_url)
                else:
                    _append_unique(failed_emails, candidate_email)
                    if outcome_flags["nonzero_blocked"]:
                        _append_unique(nonzero_blocked_emails, candidate_email)
                        cleanup_request = paypal_task_payloads_service.paypal_nonzero_amount_blocked_cleanup_request(
                            candidate_email=candidate_email,
                            current=index,
                            total=len(candidates),
                        )
                        removed = _remove_pool_accounts_from_local_and_mail(
                            cleanup_request["emails"],
                            log_context=cleanup_request["log_context"],
                            reason=cleanup_request["reason"],
                            message=cleanup_request["message"],
                        )
                        for removed_email in removed:
                            _append_unique(removed_pool_emails, removed_email)
                        _append_task_progress(task_id, cleanup_request["progress"])
                record_bind_audit(
                    paypal_task_payloads_service.paypal_bind_audit_record(
                        task_id=task_id,
                        candidate_email=candidate_email,
                        single_result=single_result,
                        proxy_label=params.proxy_label,
                        selected_proxy_url=selected_proxy_url,
                        manual_confirm=params.manual_confirm,
                        paypal_mode=paypal_mode,
                        paypal_country=paypal_country,
                        paypal_lang=paypal_lang,
                        paypal_password=params.paypal_password,
                        autofill_enabled=params.autofill_enabled,
                        started_at=started_at,
                        finished_at=time.time(),
                    )
                )
                if stop_after_current_candidate:
                    break
        except Exception as exc:
            logger.exception("[paypal] unexpected error")
            result = paypal_task_payloads_service.paypal_task_exception_result(error=exc)

        result, task_status = paypal_task_payloads_service.finalize_paypal_task_result(
            result=result,
            email=email,
            checkout_url=checkout_url,
            last_checkout_url=last_checkout_url,
            proxy_label=params.proxy_label,
            manual_confirm=params.manual_confirm,
            paypal_mode=paypal_mode,
            paypal_country=paypal_country,
            paypal_lang=paypal_lang,
            paypal_password=params.paypal_password,
            autofill_enabled=params.autofill_enabled,
            effective_concurrency=effective_paypal_concurrency,
            candidates=candidates,
            successful_emails=successful_emails,
            failed_emails=failed_emails,
            pending_retry_emails=pending_retry_emails,
            retried_emails=retried_emails,
            nonzero_blocked_emails=nonzero_blocked_emails,
            removed_pool_emails=removed_pool_emails,
            invalid_phone_pool=invalid_phone_pool,
            oauth_scheduled_emails=oauth_scheduled_emails,
            oauth_successful_emails=oauth_successful_emails,
            oauth_failed_emails=oauth_failed_emails,
            session_cpa_converted_emails=session_cpa_converted_emails,
            session_cpa_failed_auths=session_cpa_failed_auths,
            is_cancelled=cancel_signal.is_cancelled(),
        )

        _append_task_progress(
            task_id,
            paypal_task_payloads_service.paypal_completion_progress(
                result=result,
                task_status=task_status,
                successful_count=len(successful_emails),
                failed_count=len(failed_emails),
                total_count=len(candidates),
            ),
        )

        if result.get("status") != "success":
            raise TaskResultError(result.get("message") or "PayPal 任务失败", task_result=result)
        return result

    task = _start_task("paypal", _run, payload, task_group=TASK_GROUP_PAYPAL)
    return task


_account_register_task_router = create_account_register_task_router(
    start_task=lambda *args, **kwargs: _start_task(*args, **kwargs),
    normalize_proxy_url=normalize_proxy_url,
    normalize_proxy_api_provider=_normalize_proxy_api_provider,
    build_oauth_proxy_selector=lambda **kwargs: _build_oauth_proxy_selector(**kwargs),
    normalize_oauth_phone_sms_provider=_normalize_oauth_phone_sms_provider,
    normalize_oauth_smsbower_country=_normalize_oauth_smsbower_country,
    normalize_oauth_hero_sms_country=_normalize_oauth_hero_sms_country,
    oauth_phone_sms_env=_oauth_phone_sms_env,
    append_task_progress=lambda task_id, progress: _append_task_progress(task_id, progress),
    task_group_register=TASK_GROUP_REGISTER,
    logger=logger,
)
app.include_router(_account_register_task_router)
_account_register_task_endpoints = {
    route.endpoint.__name__: route.endpoint for route in _account_register_task_router.routes
}
post_add = _account_register_task_endpoints["post_add"]


_task_actions_router = create_task_actions_router(start_task=_start_task)
app.include_router(_task_actions_router)
_task_actions_endpoints = {route.endpoint.__name__: route.endpoint for route in _task_actions_router.routes}
post_check = _task_actions_endpoints["post_check"]
post_rotate = _task_actions_endpoints["post_rotate"]
post_replace = _task_actions_endpoints["post_replace"]
post_fill = _task_actions_endpoints["post_fill"]
post_cleanup = _task_actions_endpoints["post_cleanup"]


_task_control_router = create_task_control_router(
    tasks=lambda: _tasks,
    current_task_ids=lambda: _current_task_ids,
    task_cancel_signals=lambda: _task_cancel_signals,
    task_skip_signals=lambda: _task_skip_signals,
    task_runtime_controls=lambda: _task_runtime_controls,
    task_runtime_controls_lock=lambda: _task_runtime_controls_lock,
    load_task_snapshots=_load_task_snapshots,
    merged_task_snapshots=_merged_task_snapshots,
    run_task_cancel_hooks=_run_task_cancel_hooks,
    append_task_progress=_append_task_progress,
    persist_task_snapshot=_persist_task_snapshot,
    normalize_gopay_runtime_concurrency=_normalize_gopay_runtime_concurrency,
    normalize_gopay_runtime_seconds=_normalize_gopay_runtime_seconds,
    normalize_gopay_auto_signup_sms_provider=_normalize_gopay_auto_signup_sms_provider,
    default_gopay_wallet_balance_poll_interval_seconds=_default_gopay_wallet_balance_poll_interval_seconds,
    default_gopay_wallet_balance_wait_seconds=_default_gopay_wallet_balance_wait_seconds,
    logger=logger,
)
app.include_router(_task_control_router)
_task_control_endpoints = {route.endpoint.__name__: route.endpoint for route in _task_control_router.routes}
get_tasks = _task_control_endpoints["get_tasks"]
get_task = _task_control_endpoints["get_task"]
post_task_cancel = _task_control_endpoints["post_task_cancel"]
post_task_skip_current = _task_control_endpoints["post_task_skip_current"]
post_gopay_runtime_control = _task_control_endpoints["post_gopay_runtime_control"]


# ---------------------------------------------------------------------------
# 后台自动巡检
# ---------------------------------------------------------------------------

from autotoken.settings.config import (
    AUTO_CHECK_ENABLED as _DEFAULT_ENABLED,
)
from autotoken.settings.config import (
    AUTO_CHECK_INTERVAL as _DEFAULT_INTERVAL,
)
from autotoken.settings.config import (
    AUTO_CHECK_MIN_LOW as _DEFAULT_MIN_LOW,
)
from autotoken.settings.config import (
    AUTO_CHECK_THRESHOLD as _DEFAULT_THRESHOLD,
)

# 运行时可修改的巡检配置
_auto_check_config = {
    "enabled": _DEFAULT_ENABLED,
    "interval": _DEFAULT_INTERVAL,
    "threshold": _DEFAULT_THRESHOLD,
    "min_low": _DEFAULT_MIN_LOW,
}
_auto_check_stop = threading.Event()
_auto_check_restart = threading.Event()  # 配置变更时通知线程重启
_auto_refresh_quota_config = {
    "enabled": False,
    "interval": 0,
}
_auto_refresh_quota_stop = threading.Event()
_auto_refresh_quota_restart = threading.Event()

# auto-fill watchdog 冷却:防止反复触发 cmd_rotate 导致 OpenAI 对短时间内
# 多次 invite/kick 的子号批量 revoke token。30 分钟内只触发一次,给 OpenAI
# 风控系统冷却时间。0 表示从未触发过。
_auto_fill_last_trigger_ts = 0.0
_AUTO_FILL_COOLDOWN_SECONDS = 1800  # 30 min


def _load_auto_refresh_quota_config() -> None:
    """Load persisted automatic credential refresh settings from SQLite."""
    try:
        from autotoken.storage import sqlite_store

        saved = sqlite_store.get_json("config", "auto_refresh_quota", default={})
    except Exception as exc:
        logger.warning("[刷新凭证] 读取自动刷新配置失败，使用默认关闭: %s", exc)
        saved = {}
    try:
        interval = int((saved or {}).get("interval") or os.environ.get("AUTO_REFRESH_QUOTA_INTERVAL", "0") or 0)
    except (TypeError, ValueError):
        interval = 0
    enabled = bool((saved or {}).get("enabled", False)) and interval > 0
    _auto_refresh_quota_config.update(
        {
            "enabled": enabled,
            "interval": max(60, interval) if enabled else 0,
        }
    )


def _save_auto_refresh_quota_config() -> None:
    try:
        from autotoken.storage import sqlite_store

        sqlite_store.set_json("config", "auto_refresh_quota", _auto_refresh_quota_config.copy())
    except Exception as exc:
        logger.warning("[刷新凭证] 保存自动刷新配置失败: %s", exc)


app.include_router(
    create_config_io_router(
        auto_check_config=_auto_check_config,
        auto_check_restart=_auto_check_restart,
        auto_refresh_quota_config=_auto_refresh_quota_config,
        auto_refresh_quota_restart=_auto_refresh_quota_restart,
        save_auto_refresh_quota_config=_save_auto_refresh_quota_config,
        get_api_key=_get_api_key,
        set_api_key=_set_api_key,
        current_time=time.time,
        logger=logger,
    )
)

app.include_router(
    create_auto_config_router(
        auto_check_config=_auto_check_config,
        auto_check_restart=_auto_check_restart,
        auto_refresh_quota_config=_auto_refresh_quota_config,
        auto_refresh_quota_restart=_auto_refresh_quota_restart,
        save_auto_refresh_quota_config=_save_auto_refresh_quota_config,
        logger=logger,
    )
)


def _auto_refresh_quota_loop():
    """Periodically submit the refresh-quota task without blocking other task groups."""
    logged_disabled = False
    while not _auto_refresh_quota_stop.is_set():
        cfg = _auto_refresh_quota_config.copy()
        enabled = bool(cfg.get("enabled"))
        interval = int(cfg.get("interval") or 0)
        if not enabled or interval <= 0:
            _auto_refresh_quota_restart.clear()
            if not logged_disabled:
                logger.info("[刷新凭证] 自动刷新已关闭，等待重新启用")
                logged_disabled = True
            _auto_refresh_quota_restart.wait(60)
            continue

        logged_disabled = False
        logger.info("[刷新凭证] 等待 %d 分钟后执行下一轮自动刷新", max(1, interval // 60))
        _auto_refresh_quota_restart.clear()
        if _auto_refresh_quota_stop.wait(interval):
            break
        if _auto_refresh_quota_restart.is_set():
            continue

        try:
            logger.info("[刷新凭证] 开始自动提交刷新凭证任务")
            post_accounts_refresh_quota(AccountEmailBatchParams(emails=[]))
        except HTTPException as exc:
            if exc.status_code == 409:
                logger.info("[刷新凭证] 已有刷新凭证任务在执行，本轮自动刷新跳过")
            elif exc.status_code == 404:
                logger.info("[刷新凭证] 没有可刷新凭证的账号，本轮跳过")
            else:
                logger.warning("[刷新凭证] 自动刷新提交失败: %s", exc.detail)
        except Exception as exc:
            logger.warning("[刷新凭证] 自动刷新提交异常: %s", exc)


def _auto_check_loop():
    """后台巡检线程：定期检查额度，多个账号低于阈值时自动轮转"""
    from autotoken.auth.codex_auth import check_codex_quota
    from autotoken.storage.accounts import load_accounts

    while not _auto_check_stop.is_set():
        cfg = _auto_check_config
        if not cfg["enabled"]:
            _auto_check_restart.clear()
            logger.info("[巡检] 自动巡检已关闭，等待重新启用")
            _auto_check_restart.wait(60)
            continue
        logger.info(
            "[巡检] 等待 %d 分钟后执行下一轮检查（阈值: %d%%, 模式: 任意失效立即 1v1 替换）",
            cfg["interval"] // 60,
            cfg["threshold"],
        )

        # 等待 interval 秒，期间可被 restart 或 stop 唤醒
        _auto_check_restart.clear()
        if _auto_check_stop.wait(cfg["interval"]):
            break
        if _auto_check_restart.is_set():
            continue  # 配置变更，跳到下一轮重新读取配置

        try:
            cfg = _auto_check_config  # 重新读取
            accounts = load_accounts()
            active_auth_items = _auto_check_active_auth_items(accounts)
            active = [account for account, _auth_file in active_auth_items]

            # Watchdog:active 账号数 < TEAM_SUB_ACCOUNT_HARD_CAP 时自动补位。
            # 之前的 `if not active: continue` 在 4 个 active 全 kick 进 standby
            # 之后会让 Team 永远萎缩。但触发频率必须节制 —— OpenAI 对短时间内反复
            # invite/kick 同一批子号会 revoke token(token_revoked 错误),所以加
            # 30 分钟冷却,避免巡检每 5 分钟无脑触发 cmd_rotate 把账号全洗成废号。
            from autotoken.interfaces.manager import TEAM_SUB_ACCOUNT_HARD_CAP

            global _auto_fill_last_trigger_ts
            if len(active) < TEAM_SUB_ACCOUNT_HARD_CAP:
                now_ts = time.time()
                cooldown_remaining = (_auto_fill_last_trigger_ts + _AUTO_FILL_COOLDOWN_SECONDS) - now_ts
                if cooldown_remaining > 0:
                    logger.info(
                        "[巡检] active=%d < %d,但 auto-fill 冷却中(还剩 %d 分钟)",
                        len(active),
                        TEAM_SUB_ACCOUNT_HARD_CAP,
                        int(cooldown_remaining / 60),
                    )
                    # 冷却期内仍然继续做"低额度替换"(下面的 low_accounts 逻辑),
                    # 只是不触发全量 cmd_rotate
                else:
                    team_lock = _task_group_lock(TASK_GROUP_TEAM)
                    if not team_lock.acquire(blocking=False):
                        logger.info(
                            "[巡检] active=%d < %d 但有任务在跑,本轮先跳过自动补位",
                            len(active),
                            TEAM_SUB_ACCOUNT_HARD_CAP,
                        )
                        continue
                    team_lock.release()
                    logger.warning(
                        "[巡检] active 账号 %d < %d,触发 auto-fill(cmd_rotate 全流程补位)",
                        len(active),
                        TEAM_SUB_ACCOUNT_HARD_CAP,
                    )
                    from autotoken.interfaces.manager import cmd_rotate

                    try:
                        _start_task(
                            "auto-fill",
                            cmd_rotate,
                            {"target_seats": TEAM_SUB_ACCOUNT_HARD_CAP + 1},
                            TEAM_SUB_ACCOUNT_HARD_CAP + 1,
                            task_group=TASK_GROUP_TEAM,
                        )
                        _auto_fill_last_trigger_ts = now_ts
                    except Exception as e:
                        logger.error("[巡检] auto-fill 启动失败: %s", e)
                    # 触发后本轮不再做"低额度替换",免得跟 cmd_rotate 抢锁
                    continue

            if not active:
                continue

            low_accounts = []
            for acc, auth_file in active_auth_items:
                try:
                    auth_data = read_auth_json_file(Path(auth_file))
                    access_token = auth_data.get("access_token")
                    if not access_token:
                        continue
                    status, info = check_codex_quota(access_token)
                    if status == "ok" and isinstance(info, dict):
                        remaining = 100 - info.get("primary_pct", 0)
                        if remaining < cfg["threshold"]:
                            low_accounts.append((acc["email"], remaining))
                    elif status == "exhausted":
                        low_accounts.append((acc["email"], 0))
                except Exception:
                    pass

            if low_accounts:
                logger.info(
                    "[巡检] %d 个账号额度不足: %s", len(low_accounts), ", ".join(f"{e}({r}%)" for e, r in low_accounts)
                )

                # 有任务在跑则本轮跳过(下轮再替换,避免重复 kick)
                team_lock = _task_group_lock(TASK_GROUP_TEAM)
                if not team_lock.acquire(blocking=False):
                    logger.info("[巡检] 有任务正在执行，本轮跳过即时替换")
                    continue
                team_lock.release()

                # 先标记 exhausted,cmd_check 入口的对账在此之后再看到就会补 kick(双保险)。
                # 必须同时写 quota_resets_at —— 否则 get_standby_accounts() 看到 None 就默认
                # _quota_recovered=True,导致后续 rotate/replace 立刻把这个 0% 账号当可复用号
                # 反复 reinvite 进 Team,席位来回洗同一批耗尽账号永远不换新鲜的。
                # 阈值默认 5h(18000s),与 check_codex_quota 无返回 resets_at 时的 fallback 一致。
                from autotoken.storage.accounts import STATUS_EXHAUSTED, update_account

                now_ts = time.time()
                emails_to_replace = []
                for email, remaining in low_accounts:
                    logger.info("[巡检] %s 剩余 %d%%，立即替换", email, remaining)
                    update_account(
                        email,
                        status=STATUS_EXHAUSTED,
                        quota_exhausted_at=now_ts,
                        quota_resets_at=now_ts + 18000,
                    )
                    emails_to_replace.append(email)

                # 失效一个立即轮换一个:逐个 kick+补一个,不等凑 min_low 也不走全量 cmd_rotate。
                # min_low 字段保留作兼容(当前不参与判断),前端可继续配置但无语义效果。
                logger.info("[巡检] 触发即时替换 (%d 个)...", len(emails_to_replace))
                from autotoken.interfaces.manager import cmd_replace_batch

                try:
                    _start_task(
                        "auto-replace",
                        cmd_replace_batch,
                        {"emails": emails_to_replace, "trigger": "auto-check"},
                        emails_to_replace,
                        "auto-check",
                        task_group=TASK_GROUP_TEAM,
                    )
                except Exception as e:
                    logger.error("[巡检] 即时替换启动失败: %s", e)
            else:
                logger.info("[巡检] 额度正常，无需替换")

        except Exception as e:
            logger.error("[巡检] 巡检异常: %s", e)


def _start_auto_check():
    try:
        from autotoken.storage import sqlite_store

        sqlite_store.initialize()
        _load_auto_refresh_quota_config()
        cancelled_tasks = _cancel_orphaned_task_snapshots()
        if cancelled_tasks:
            logger.warning("[启动] 已取消 %d 个后端重启后残留的运行中任务快照", cancelled_tasks)
    except Exception as exc:
        logger.warning("[启动] 初始化 SQLite 存储失败: %s", exc)

    try:
        from autotoken.storage.auth_storage import ensure_auth_file_permissions

        fixed = ensure_auth_file_permissions()
        if fixed:
            logger.info("[启动] 已修复 %d 个 auths 认证文件权限", fixed)
    except Exception as exc:
        logger.warning("[启动] 修复 auths 认证文件权限失败: %s", exc)

    try:
        from autotoken.integrations.account_hub import start_auto_upload_loop

        start_auto_upload_loop()
    except Exception as exc:
        logger.warning("[启动] 启动账号 Hub 自动同步线程失败: %s", exc)

    if not _auto_check_config["enabled"]:
        logger.info("[巡检] 自动巡检已关闭，启动时跳过后台线程")
    else:
        thread = threading.Thread(target=_auto_check_loop, daemon=True)
        thread.start()

    quota_thread = threading.Thread(target=_auto_refresh_quota_loop, daemon=True)
    quota_thread.start()


def _stop_auto_check():
    _auto_check_stop.set()
    _auto_refresh_quota_stop.set()
    _auto_refresh_quota_restart.set()
    try:
        from autotoken.integrations.account_hub import stop_auto_upload_loop

        stop_auto_upload_loop()
    except Exception:
        pass
    try:
        from autotoken.payments.whatsapp_otp import get_default_listener

        get_default_listener().stop()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 前端静态文件
# ---------------------------------------------------------------------------

DIST_DIR = Path(__file__).resolve().parents[1] / "web" / "dist"

if DIST_DIR.exists():
    # Vite 构建的 assets 目录
    assets_dir = DIST_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{path:path}")
    def serve_frontend(path: str):
        """兜底路由：serve 前端 SPA"""
        file = DIST_DIR / path
        if file.is_file() and ".." not in path:
            headers = {"Cache-Control": "no-store"} if file.name == "index.html" else None
            return FileResponse(str(file), headers=headers)
        return FileResponse(str(DIST_DIR / "index.html"), headers={"Cache-Control": "no-store"})


class _QuietAccessLog(logging.Filter):
    """过滤前端轮询产生的高频访问日志"""

    _quiet_paths = (
        "/api/status",
        "/api/tasks",
        "/api/config/auto-check",
        "/api/admin/status",
        "/api/main-codex/status",
        "/api/manual-account/status",
        "/api/auth/check",
        "/api/setup/status",
    )

    def filter(self, record):
        msg = record.getMessage()
        return not any(p in msg for p in self._quiet_paths)


def start_server(host: str = "0.0.0.0", port: int = 8787, build: bool = False):
    """启动 API 服务器"""
    import uvicorn

    if build:
        import subprocess
        web_dir = Path(__file__).resolve().parents[3] / "web"
        logger.info("[API] --build 已指定，正在编译前端...")
        result = subprocess.run(
            "npm run build",
            cwd=str(web_dir),
            shell=True,
            capture_output=True,
            text=False,
        )
        if result.returncode != 0:
            stderr_text = result.stderr.decode("utf-8", errors="replace")
            logger.error("[API] 前端编译失败:\n%s", stderr_text[:2000])
            raise RuntimeError("前端编译失败")
        logger.info("[API] 前端编译完成")

    if not os.environ.get("AUTOTOKEN_LOCAL_BASE_URL"):
        local_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
        os.environ["AUTOTOKEN_LOCAL_BASE_URL"] = f"http://{local_host}:{port}"

    # 过滤轮询日志，避免刷屏
    logging.getLogger("uvicorn.access").addFilter(_QuietAccessLog())
    # 首次启动检查配置
    from autotoken.settings.setup_wizard import check_and_setup

    check_and_setup(interactive=True)

    # 重新读取 API_KEY（可能刚刚被向导写入）
    global API_KEY
    from autotoken.settings.config import API_KEY as _fresh_key

    API_KEY = _fresh_key or os.environ.get("API_KEY", "")
    if API_KEY:
        logger.info("[API] API Key 鉴权已启用")
    else:
        logger.warning("[API] 未设置 API_KEY，所有接口无需认证")
    logger.info("[API] 启动 AutoToken API 服务器 http://%s:%d", host, port)
    if DIST_DIR.exists():
        logger.info("[API] 前端面板 http://%s:%d", host, port)
    logger.info("[API] API 文档 http://%s:%d/docs", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")
