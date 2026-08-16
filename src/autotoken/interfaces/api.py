"""AutoToken HTTP API - 将 CLI 功能暴露为 HTTP 接口"""

import json
import logging
import os
import queue
import random
import re
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
from starlette.convertors import Convertor, register_url_convertor

from autotoken import install_no_traceback_filter
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
from autotoken.auth.protocol_register import preflight_oauth_proxy_url as _preflight_oauth_proxy_url
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
from autotoken.api_routes.brazil_pix import create_brazil_pix_router
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
from autotoken.api_routes.ideal_link import create_ideal_link_router
from autotoken.api_routes.india_upi import create_india_upi_router
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
from autotoken.api_routes.kakao_pay import create_kakao_pay_router
from autotoken.api_routes.mail_accounts import create_mail_accounts_router
from autotoken.api_routes.mail_provider_config import create_mail_provider_config_router
from autotoken.api_routes.momo_vn import create_momo_vn_router
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
    normalize_oauth_smscloud_country as _normalize_oauth_smscloud_country,
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
from autotoken.api_routes.us_paypal import create_us_paypal_router
from autotoken.api_routes.whatsapp_otp import create_whatsapp_otp_router
from autotoken.core.normalization import normalize_access_token as _core_normalize_access_token
from autotoken.core.normalization import normalized_email as _core_normalized_email
from autotoken.core.redaction import (
    compact_log_text as _compact_log_text,
)
from autotoken.core.redaction import (
    safe_email_summary as _safe_email_summary,
)
from autotoken.core.redaction import (
    safe_error_summary as _safe_error_summary,
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
from autotoken.services import account_plan_verification as account_plan_verification_service
from autotoken.services import account_pool_cleanup as account_pool_cleanup_service
from autotoken.services import account_presentation as account_presentation_service
from autotoken.services import account_session_stubs as account_session_stubs_service
from autotoken.services import api_helpers as api_helpers_service
from autotoken.services import chatgpt_session as chatgpt_session_service
from autotoken.services import checkout_response as checkout_response_service
from autotoken.services import gopay_pending_retry as gopay_pending_retry_service
from autotoken.services import gopay_runtime as gopay_runtime_service
from autotoken.services import gopay_task_payloads as gopay_task_payloads_service
from autotoken.services import gopay_wallet_pool as gopay_wallet_pool_service
from autotoken.services import payment_results as payment_results_service
from autotoken.services import proxy_runtime as proxy_runtime_service
from autotoken.services.task_runtime import (
    TASK_GROUP_BIND_CARD,
    TASK_GROUP_DEFAULT,
    TASK_GROUP_GOPAY,
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
from autotoken.settings.config import API_KEY, PROXY_DEFAULT_AUTH_SCHEME, normalize_proxy_url
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
LoginAccountParams = _LoginAccountParams
AccountEmailBatchParams = _AccountEmailBatchParams
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
app.include_router(create_mail_accounts_router())


def _mask_secret_for_config(value: str) -> str:
    return api_helpers_service.mask_secret_for_config(value)


app.include_router(create_roxybrowser_config_router(mask_secret=_mask_secret_for_config))
app.include_router(create_rekberinaja_config_router(mask_secret=_mask_secret_for_config))
app.include_router(create_oauth_phone_sms_config_router(mask_secret=_mask_secret_for_config))
app.include_router(create_gopay_auto_signup_config_router(mask_secret=_mask_secret_for_config))

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
app.include_router(create_brazil_pix_router())
app.include_router(create_india_upi_router())
app.include_router(create_kakao_pay_router())
app.include_router(create_momo_vn_router())
app.include_router(create_us_paypal_router())
app.include_router(create_ideal_link_router())


def _normalize_gopay_runtime_concurrency(value: int | str | None, default: int = 1) -> int:
    return gopay_runtime_service.normalize_runtime_concurrency(value, default)


def _gopay_runtime_control(task_id: str, *, create: bool = False) -> dict[str, Any]:
    return runtime_control(_task_runtime_controls, _task_runtime_controls_lock, task_id, create=create)


def _init_oauth_batch_control(task_id: str, account_emails: list[str]) -> dict[str, Any]:
    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id:
        return {}
    normalized = []
    seen = set()
    for raw_email in account_emails or []:
        email = _normalized_email(raw_email)
        if email and email not in seen:
            seen.add(email)
            normalized.append(email)
    with _task_runtime_controls_lock:
        control = _task_runtime_controls.setdefault(normalized_task_id, {})
        control.setdefault("pending_account_emails", [])
        existing = control.get("all_account_emails") if isinstance(control.get("all_account_emails"), list) else []
        merged = []
        merged_seen = set()
        for email in [*normalized, *existing]:
            cleaned = _normalized_email(email)
            if cleaned and cleaned not in merged_seen:
                merged_seen.add(cleaned)
                merged.append(cleaned)
        control["all_account_emails"] = merged
        control["version"] = int(control.get("version") or 0)
        return dict(control)


def _append_oauth_batch_emails(task_id: str, account_emails: list[str]) -> dict[str, Any]:
    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id:
        return {"added_emails": [], "duplicates": []}
    with _task_runtime_controls_lock:
        control = _task_runtime_controls.setdefault(normalized_task_id, {})
        all_emails = control.get("all_account_emails") if isinstance(control.get("all_account_emails"), list) else []
        pending = control.get("pending_account_emails") if isinstance(control.get("pending_account_emails"), list) else []
        task = _tasks.get(normalized_task_id)
        if task:
            params = task.get("params") if isinstance(task.get("params"), dict) else {}
            public_emails = params.get("emails") if isinstance(params.get("emails"), list) else []
            all_seen = {_normalized_email(item) for item in all_emails}
            for raw_email in public_emails:
                email = _normalized_email(raw_email)
                if email and email not in all_seen:
                    all_seen.add(email)
                    all_emails.append(email)
        seen = {_normalized_email(email) for email in all_emails}
        pending_seen = {_normalized_email(email) for email in pending}
        added: list[str] = []
        duplicates: list[str] = []
        for raw_email in account_emails or []:
            email = _normalized_email(raw_email)
            if not email:
                continue
            if email in seen or email in pending_seen:
                duplicates.append(email)
                continue
            seen.add(email)
            pending_seen.add(email)
            all_emails.append(email)
            pending.append(email)
            added.append(email)
        control["all_account_emails"] = all_emails
        control["pending_account_emails"] = pending
        control["version"] = int(control.get("version") or 0) + 1

        if task:
            params = task.get("params") if isinstance(task.get("params"), dict) else {}
            public_emails = params.get("emails") if isinstance(params.get("emails"), list) else []
            public_seen = {_normalized_email(email) for email in public_emails}
            for email in added:
                if email not in public_seen:
                    public_seen.add(email)
                    public_emails.append(email)
            params["emails"] = public_emails
            if duplicates:
                params["duplicate_append_emails"] = duplicates
            task["params"] = params
        return {"added_emails": added, "duplicates": duplicates, "version": control["version"]}


def _drain_oauth_batch_emails(task_id: str, existing_emails: set[str]) -> list[str]:
    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id:
        return []
    with _task_runtime_controls_lock:
        control = _task_runtime_controls.get(normalized_task_id)
        if not isinstance(control, dict):
            return []
        pending = control.get("pending_account_emails")
        if not isinstance(pending, list) or not pending:
            return []
        control["pending_account_emails"] = []
    existing = {_normalized_email(email) for email in existing_emails or set()}
    drained = []
    for raw_email in pending:
        email = _normalized_email(raw_email)
        if email and email not in existing:
            existing.add(email)
            drained.append(email)
    return drained


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


def _select_bind_link_open_proxy_url(
    *,
    provider: str = "cliproxy",
    country: str = "US",
    api_url: str = "",
) -> str:
    normalized_provider = proxy_runtime_service.normalize_proxy_api_provider(provider or "cliproxy")
    normalized_country = "".join(ch for ch in str(country or "US").strip().upper() if ch.isalpha())[:2] or "US"
    resolved_api_url = str(api_url or "").strip()
    if resolved_api_url:
        resolved_api_url = proxy_runtime_service.proxy_api_url_with_region(resolved_api_url, normalized_country)
    else:
        resolved_api_url = proxy_runtime_service.default_proxy_api_url(normalized_provider, country=normalized_country)
    proxy_url = proxy_runtime_service.fetch_proxy_from_api_url(
        resolved_api_url,
        default_auth_scheme=proxy_runtime_service.default_proxy_auth_scheme(normalized_provider),
        provider=normalized_provider,
    )
    if not proxy_url:
        provider_label = {
            "cliproxy": "Cliproxy",
            "711proxy": "711Proxy",
            "1024proxy": "1024proxy",
        }.get(normalized_provider, normalized_provider)
        raise RuntimeError(f"{provider_label} {normalized_country} 代理 API 未返回可用代理")
    return proxy_url


def _build_oauth_proxy_selector(
    *,
    proxy_url: str | None = None,
    proxy_pool: list[Any] | tuple[Any, ...] | None = None,
    proxy_pool_text: str | None = None,
    proxy_api_provider: str | None = None,
    proxy_api_url: str | None = None,
    proxy_api_country: str | None = None,
):
    """Return a per-account OAuth proxy selector.

    OAuth uses the same static proxy / proxy pool / provider API semantics as
    OAuth flows keep selection local so batch login can rotate per account.
    """
    try:
        return proxy_runtime_service.build_oauth_proxy_selector(
            proxy_url=proxy_url,
            proxy_pool=proxy_pool,
            proxy_pool_text=proxy_pool_text,
            proxy_api_provider=proxy_api_provider,
            proxy_api_url=proxy_api_url,
            proxy_api_country=proxy_api_country,
            default_auth_scheme=PROXY_DEFAULT_AUTH_SCHEME,
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
    return _core_normalize_access_token(raw_value)


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
            "[checkout] refresh access token from session failed: email=%s error=%s", _safe_email_summary(normalized), exc
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


def _generate_plus_trial_checkout_link(access_token: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        from autotoken.payments.plus_trial import generate_plus_trial_checkout_link

        return generate_plus_trial_checkout_link(
            _normalize_access_token(access_token),
            payload,
            logger=lambda message: logger.info("[bind/link plus_trial] %s", message),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[bind/link plus_trial] extractor failed")
        raise HTTPException(status_code=502, detail=f"Plus 试用提链失败: {exc}") from exc


_bind_checkout_browser_sessions: list[Any] = []


def _open_bind_checkout_with_auth_session(
    email: str,
    checkout_url: str,
    *,
    open_mode: str = "roxybrowser",
    proxy_url: str | None = None,
) -> dict[str, Any]:
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
    normalized_open_mode = str(open_mode or "roxybrowser").strip().lower()
    use_roxybrowser = normalized_open_mode in {"roxy", "roxybrowser", "roxy-browser"}

    api = ChatGPTTeamAPI()
    api.oai_device_id = device_id or getattr(api, "oai_device_id", "")
    api._launch_browser(
        proxy_url=proxy_url,
        background=False,
        headless=False,
        randomize_fingerprint=False,
        use_roxybrowser=use_roxybrowser,
    )
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
    return {
        "opened": True,
        "current_url": str(getattr(api.page, "url", "") or checkout_url),
        "open_mode": "roxybrowser" if use_roxybrowser else "playwright",
        "open_proxy_url_present": bool(proxy_url),
    }


def _generate_checkout_link_via_browser(
    access_token: str,
    payload: dict[str, Any],
    *,
    email: str = "",
    proxy_url: str | None = None,
    proxy_bypass: str | None = None,
    browser: str = "chromium",
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
        browser = str(browser or "chromium").strip().lower()
        use_camoufox = browser in {"camoufox", "firefox"}
        use_roxybrowser = browser in {"roxybrowser", "roxy-browser", "roxy"}
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


def _mark_account_plan_verification_failed(
    email: str,
    *,
    task_id: str,
    status: str,
    message: str,
    failure_stage: str,
) -> None:
    from autotoken.storage.accounts import update_account

    normalized = _normalized_email(email)
    if not normalized:
        return
    update_account(
        normalized,
        **account_plan_verification_service.verification_failure_update_fields(
            task_id=task_id,
            status=status,
            message=message,
            failure_stage=failure_stage,
            marked_at=time.time(),
        ),
    )


def _probe_openai_plan(access_token: str, account_id: str = "", *, timeout: float = 25.0) -> dict:
    token = _normalize_access_token(access_token)
    if not token:
        return account_plan_verification_service.usage_probe_missing_token_result()
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
        response = requests.get(
            "https://chatgpt.com/backend-api/wham/usage",
            headers=headers,
            params={"account_id": account_id} if account_id else None,
            timeout=max(5.0, float(timeout or 25.0)),
        )
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.SSLError) as exc:
        return account_plan_verification_service.usage_probe_exception_result(kind="网络异常", error=exc)
    except requests.exceptions.RequestException as exc:
        return account_plan_verification_service.usage_probe_exception_result(kind="请求异常", error=exc)
    except Exception as exc:
        return account_plan_verification_service.usage_probe_exception_result(kind="未知异常", error=exc)
    if response.status_code != 200:
        return account_plan_verification_service.usage_probe_http_result(
            status_code=response.status_code,
            text=response.text,
        )
    try:
        payload = response.json()
    except Exception as exc:
        return account_plan_verification_service.usage_probe_json_error_result(exc)
    return account_plan_verification_service.usage_probe_ok_result(
        str((payload or {}).get("plan_type") or "").strip().lower()
    )


def _save_refreshed_auth_file(auth_file: str, auth_data: dict, refreshed: dict) -> None:
    path = _trusted_token_auth_path(auth_file)
    if not path or not isinstance(auth_data, dict) or not isinstance(refreshed, dict):
        return
    next_data = account_plan_verification_service.refreshed_auth_data(auth_data, refreshed, now=time.time())
    path.write_text(json.dumps(next_data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        from autotoken.storage.auth_index import upsert_codex_auth_file
        from autotoken.storage.auth_storage import ensure_auth_file_permissions

        ensure_auth_file_permissions(path)
        upsert_codex_auth_file(path, next_data, main=path.name.startswith("codex-main-"))
    except Exception as exc:
        logger.warning("[account-plan] refreshed CPA auth index update failed: %s", exc)


def _verify_plus_plan(item: dict[str, str]) -> dict:
    email = str(item.get("email") or "").strip()
    auth_file = _valid_token_item_auth_file(item)
    auth_data: dict[str, Any] = {}
    if auth_file:
        try:
            auth_path = _trusted_token_auth_path(auth_file)
            if auth_path:
                auth_data = read_auth_json_file(auth_path)
        except Exception as exc:
            return account_plan_verification_service.plus_plan_auth_file_read_error_result(exc)
    access_token = _normalize_access_token(
        item.get("access_token") or auth_data.get("access_token") or auth_data.get("accessToken") or ""
    )
    refresh_token = str(
        item.get("refresh_token") or auth_data.get("refresh_token") or auth_data.get("refreshToken") or ""
    ).strip()
    account_id = str(item.get("account_id") or auth_data.get("account_id") or auth_data.get("accountId") or "").strip()
    attempts = max(1, int(_env_float("OPENAI_PLAN_VERIFY_ATTEMPTS", 3)))
    wait_seconds = max(0.0, _env_float("OPENAI_PLAN_VERIFY_INTERVAL_SECONDS", 5.0))
    refreshed_once = False
    last_probe: dict = account_plan_verification_service.usage_probe_missing_token_result()

    for attempt in range(1, attempts + 1):
        last_probe = _probe_openai_plan(access_token, account_id)
        plan_type = str(last_probe.get("plan_type") or "").strip().lower()
        if plan_type in {"plus", "pro"}:
            return account_plan_verification_service.plus_plan_verified_result(plan_type)

        if refresh_token and not refreshed_once:
            refreshed_once = True
            try:
                from autotoken.auth.codex_auth import refresh_access_token

                refreshed = refresh_access_token(refresh_token)
            except Exception as exc:
                refreshed = None
                last_probe = account_plan_verification_service.plus_plan_refresh_exception_probe(
                    last_probe,
                    plan_type=plan_type,
                    error=exc,
                )
            if refreshed and refreshed.get("access_token"):
                access_token = _normalize_access_token(refreshed.get("access_token") or access_token)
                refresh_token = str(refreshed.get("refresh_token") or refresh_token)
                _save_refreshed_auth_file(auth_file, auth_data, refreshed)
                continue

        if attempt < attempts and wait_seconds > 0:
            time.sleep(wait_seconds)

    return account_plan_verification_service.plus_plan_unverified_result(email=email, last_probe=last_probe)


def _normalize_observed_auth_plan(email: str, auth_file: str, plan_type: str) -> None:
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
            "[account-plan] observed auth plan sync failed: email=%s plan=%s",
            _safe_email_summary(email),
            observed_plan,
            exc_info=True,
        )


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
        verify_plus_plan=_verify_plus_plan,
        normalize_observed_auth_plan=_normalize_observed_auth_plan,
        mark_failed_account=_mark_account_plan_verification_failed,
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
    use_roxybrowser: bool = False,
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
    totp_secret: str | None = None,
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
    if refresh_auth_session and str(acc.get("auth_file") or "").strip() and not protocol_only and not use_roxybrowser:
        logger.info("[账号登录] 有 Codex auth 文件的补登录强制使用协议 OAuth，避免浏览器 OAuth: %s", email)
        protocol_only = True

    phone_only_target = "@" not in str(email or "")
    requested_mail_provider = str(mail_provider or "").strip().lower()
    account_mail_provider = str(acc.get("mail_provider") or "").strip().lower()
    # 已有邮箱账号必须优先使用账号自身保存的邮箱 provider；仪表盘 OAuth 配置里的
    # mail_provider 只作为手机号账号绑邮箱/账号缺失 provider 时的兜底，避免把 Outlook
    # 成品号误按全局 LuckMail 配置查询验证码。
    effective_mail_provider = (
        (requested_mail_provider or account_mail_provider)
        if phone_only_target
        else (account_mail_provider or requested_mail_provider)
    )
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
    effective_oauth_phone_sms_provider = str(oauth_phone_sms_provider or "").strip()
    effective_oauth_phone_sms_country = str(oauth_phone_sms_country or "").strip()
    effective_oauth_phone_sms_max_price = str(oauth_phone_sms_max_price or "").strip()
    effective_oauth_oasis_sms_cdks = str(oauth_oasis_sms_cdks or "").strip()
    if (protocol_only or bind_phone) and not effective_oauth_phone_sms_provider:
        oauth_phone_cfg = _oauth_phone_sms_env()
        effective_oauth_phone_sms_provider = str(oauth_phone_cfg.get("provider") or "phone_pool").strip()
        if not effective_oauth_phone_sms_country:
            provider_key = effective_oauth_phone_sms_provider.replace("-", "_")
            if provider_key == "hero_sms":
                effective_oauth_phone_sms_country = str(oauth_phone_cfg.get("hero_sms_country") or "").strip()
                effective_oauth_phone_sms_max_price = (
                    effective_oauth_phone_sms_max_price
                    or str(oauth_phone_cfg.get("hero_sms_max_price") or "").strip()
                )
            elif provider_key == "smsbower":
                effective_oauth_phone_sms_country = str(oauth_phone_cfg.get("smsbower_country") or "").strip()
                effective_oauth_phone_sms_max_price = (
                    effective_oauth_phone_sms_max_price
                    or str(oauth_phone_cfg.get("smsbower_max_price") or "").strip()
                )
            elif provider_key == "smscloud":
                effective_oauth_phone_sms_country = str(oauth_phone_cfg.get("smscloud_country") or "").strip()
                effective_oauth_phone_sms_max_price = (
                    effective_oauth_phone_sms_max_price
                    or str(oauth_phone_cfg.get("smscloud_max_price") or "").strip()
                )
            elif provider_key == "oasis":
                effective_oauth_oasis_sms_cdks = (
                    effective_oauth_oasis_sms_cdks
                    or str(oauth_phone_cfg.get("oasis_sms_cdks") or "").strip()
                )
            elif provider_key == "tujie":
                effective_oauth_oasis_sms_cdks = (
                    effective_oauth_oasis_sms_cdks
                    or str(oauth_phone_cfg.get("tujie_sms_cdks") or "").strip()
                )
    session_payload: dict | None = None

    def _auth_session_from_codex_bundle(bundle_data: dict | None) -> dict:
        if not isinstance(bundle_data, dict):
            return {}
        access_token = str(bundle_data.get("access_token") or bundle_data.get("accessToken") or "").strip()
        if not access_token:
            return {}
        refresh_token = str(bundle_data.get("refresh_token") or bundle_data.get("refreshToken") or "").strip()
        id_token = str(bundle_data.get("id_token") or bundle_data.get("idToken") or "").strip()
        bundle_email = _normalized_email(str(bundle_data.get("email") or email))
        account_id = str(bundle_data.get("account_id") or bundle_data.get("accountId") or "").strip()
        plan_type = str(bundle_data.get("plan_type") or bundle_data.get("chatgpt_plan_type") or "").strip().lower()
        try:
            from autotoken.core.jwt import decode_jwt_payload

            claims = decode_jwt_payload(access_token)
            auth_claims = claims.get("https://api.openai.com/auth", {}) if isinstance(claims, dict) else {}
            profile = claims.get("https://api.openai.com/profile", {}) if isinstance(claims, dict) else {}
            if isinstance(auth_claims, dict):
                account_id = account_id or str(auth_claims.get("chatgpt_account_id") or "").strip()
                plan_type = plan_type or str(auth_claims.get("chatgpt_plan_type") or "").strip().lower()
            if isinstance(profile, dict):
                bundle_email = _normalized_email(str(profile.get("email") or bundle_email))
        except Exception:
            pass

        session = {
            "accessToken": access_token,
            "access_token": access_token,
            "chatgpt_access_token": access_token,
            "refreshToken": refresh_token,
            "refresh_token": refresh_token,
            "idToken": id_token,
            "id_token": id_token,
            "user": {"email": bundle_email or email},
        }
        if account_id:
            session["accountId"] = account_id
            session["account"] = {"id": account_id}
        if plan_type:
            session["planType"] = plan_type
            session["plan_type"] = plan_type
            session.setdefault("account", {})["planType"] = plan_type
        return session

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
                    oauth_phone_sms_provider=effective_oauth_phone_sms_provider,
                    oauth_phone_sms_country=effective_oauth_phone_sms_country,
                    oauth_phone_sms_max_price=effective_oauth_phone_sms_max_price,
                    oauth_oasis_sms_cdks=effective_oauth_oasis_sms_cdks,
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
                    oauth_phone_sms_provider=effective_oauth_phone_sms_provider,
                    oauth_phone_sms_country=effective_oauth_phone_sms_country,
                    oauth_phone_sms_max_price=effective_oauth_phone_sms_max_price,
                    oauth_oasis_sms_cdks=effective_oauth_oasis_sms_cdks,
                    totp_secret=totp_secret,
                    progress_callback=progress_callback,
                    **({"auth_session_only": True} if refresh_auth_session else {}),
                )
                bundle = (session_payload or {}).get("codex_oauth_bundle")
                if not isinstance(bundle, dict):
                    if refresh_auth_session and session_payload:
                        protocol_session_email = _normalized_email((session_payload or {}).get("email") or email)
                        protocol_session_file = save_auth_session(protocol_session_email, session_payload)
                        update_fields = {
                            "status": STATUS_ACTIVE,
                            "account_type": account_type,
                            "last_active_at": time.time(),
                        }
                        if acc.get("cloudmail_account_id"):
                            update_fields["cloudmail_account_id"] = acc.get("cloudmail_account_id")
                        if effective_mail_provider:
                            update_fields["mail_provider"] = effective_mail_provider
                        update_account(email, **update_fields)
                        return {
                            "email": protocol_session_email or email,
                            "auth_session_file": protocol_session_file,
                            "codex_auth_updated": False,
                            "mode": "auth_session",
                        }
                    raise RuntimeError(f"协议补登录未返回 Codex OAuth bundle: {email}")
        except (CodexOAuthPhoneRequired, CodexOAuthAccountDeactivated):
            raise
        except Exception as exc:
            logger.error("[账号登录] 协议补登录失败: %s error=%s", email, _safe_error_summary(exc, limit=220))
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
    elif auth_session_data and not protocol_only:
        logger.info("[账号登录] 跳过 auth_session 协议 OAuth，直接走浏览器邮箱验证码流程: %s", email)

    auth_session_refresh_outcome = {}

    if not bundle:
        browser_login_kwargs = {
            "mail_client": mail_client,
            "use_personal": use_personal,
            "native_oauth": native_oauth,
            "headless": headless,
            "mail_account_id": acc.get("cloudmail_account_id"),
        }
        if use_roxybrowser:
            browser_login_kwargs["use_roxybrowser"] = True
        if oauth_proxy_url:
            browser_login_kwargs["proxy_url"] = oauth_proxy_url
            if oauth_proxy_bypass:
                browser_login_kwargs["proxy_bypass"] = oauth_proxy_bypass
        if bind_phone or effective_oauth_phone_sms_provider:
            browser_login_kwargs["phone_sms_provider"] = effective_oauth_phone_sms_provider or None
            browser_login_kwargs["phone_sms_country"] = effective_oauth_phone_sms_country or None
            browser_login_kwargs["phone_sms_oasis_cdks"] = effective_oauth_oasis_sms_cdks or None
        bundle = login_codex_via_browser(
            email,
            acc.get("password", ""),
            **browser_login_kwargs,
        )
    if not bundle:
        raise RuntimeError(f"Codex 登录失败: {email}")
    if refresh_auth_session and protocol_only and session_payload:
        try:
            protocol_session_file = save_auth_session(
                _normalized_email((session_payload or {}).get("email") or email),
                session_payload,
            )
            auth_session_refresh_outcome.update(
                {
                    "status": "success",
                    "auth_file": protocol_session_file,
                    "auth_session_file": protocol_session_file,
                }
            )
        except Exception as exc:
            auth_session_refresh_outcome.update({"status": "failed", "reason": f"保存协议 auth_session 失败: {exc}"})
    elif refresh_auth_session:
        try:
            bundle_session = _auth_session_from_codex_bundle(bundle)
            if bundle_session:
                bundle_session_email = _normalized_email(str(bundle_session.get("user", {}).get("email") or email))
                bundle_session_file = save_auth_session(bundle_session_email, bundle_session)
                auth_session_refresh_outcome.update(
                    {
                        "status": "success",
                        "auth_file": bundle_session_file,
                        "auth_session_file": bundle_session_file,
                    }
                )
            else:
                auth_session_refresh_outcome.update({"status": "failed", "reason": "Codex 认证文件缺少 access_token"})
        except Exception as exc:
            auth_session_refresh_outcome.update({"status": "failed", "reason": f"保存 Codex access_token 到 auth_session 失败: {exc}"})
    auth_session_refresh_warning = ""
    if refresh_auth_session and auth_session_refresh_outcome.get("status") != "success":
        auth_session_refresh_warning = auth_session_refresh_outcome.get("reason") or f"刷新 auth_session 失败: {email}"
        if protocol_only:
            raise RuntimeError(auth_session_refresh_warning)
        logger.warning(
            "[账号登录] 浏览器 OAuth 已成功，但刷新 auth_session 失败，继续保存 Codex auth_file: %s reason=%s",
            email,
            auth_session_refresh_warning,
        )

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
    if protocol_only and session_payload and not (refresh_auth_session and auth_session_refresh_outcome.get("status") == "success"):
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
    elif auth_session_refresh_warning:
        result_payload["auth_session_refresh_warning"] = auth_session_refresh_warning
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
    preflight_oauth_proxy_url=lambda *args, **kwargs: _preflight_oauth_proxy_url(*args, **kwargs),
    run_account_codex_login_once=lambda *args, **kwargs: _run_account_codex_login_once(*args, **kwargs),
    append_task_progress=lambda task_id, progress: _append_task_progress(task_id, progress),
    oauth_phone_required_result=_oauth_phone_required_result,
    oauth_phone_rate_limited_result=_oauth_phone_rate_limited_result,
    oauth_login_required_result=_oauth_login_required_result,
    oauth_account_deactivated_result=lambda email, exc: _oauth_account_deactivated_result(email, exc),
    task_result_error=TaskResultError,
    current_oauth_task=lambda: _running_task_for_group(TASK_GROUP_OAUTH),
    init_oauth_batch_control=lambda task_id, emails: _init_oauth_batch_control(task_id, emails),
    append_oauth_batch_emails=lambda task_id, emails: _append_oauth_batch_emails(task_id, emails),
    drain_oauth_batch_emails=lambda task_id, existing: _drain_oauth_batch_emails(task_id, existing),
    logger=logger,
)
app.include_router(_account_login_router)
_account_login_endpoints = {route.endpoint.__name__: route.endpoint for route in _account_login_router.routes}
post_account_login = _account_login_endpoints["post_account_login"]
post_accounts_login_batch = _account_login_endpoints["post_accounts_login_batch"]
post_accounts_login_batch_append = _account_login_endpoints["post_accounts_login_batch_append"]


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
        generate_plus_trial_checkout_link=_generate_plus_trial_checkout_link,
        get_account_access_token=_extract_account_access_token,
        open_checkout_url=_open_bind_checkout_with_auth_session,
        select_open_proxy_url=_select_bind_link_open_proxy_url,
        preflight_open_proxy_url=proxy_runtime_service.preflight_payment_proxy_url,
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
install_no_traceback_filter(_log_collector)
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
        if auto_register_mail_provider not in {"luckmail", "outlook", "icloud"} and not auto_register_domains:
            default_domain = str(get_register_domain() or "").strip().lstrip("@")
            if default_domain:
                auto_register_domains = [default_domain]
            elif configured_domains:
                auto_register_domains = [configured_domains[0]]
        if auto_register_mail_provider not in {"luckmail", "outlook", "icloud"} and not auto_register_domains:
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
                    default_auth_scheme=proxy_runtime_service.default_proxy_auth_scheme(
                        proxy_api_provider or "cliproxy"
                    ),
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
            if auto_register_mail_provider not in {"luckmail", "outlook", "icloud"} and not register_domain:
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



_account_register_task_router = create_account_register_task_router(
    start_task=lambda *args, **kwargs: _start_task(*args, **kwargs),
    normalize_proxy_url=normalize_proxy_url,
    normalize_proxy_api_provider=_normalize_proxy_api_provider,
    build_oauth_proxy_selector=lambda **kwargs: _build_oauth_proxy_selector(**kwargs),
    normalize_oauth_phone_sms_provider=_normalize_oauth_phone_sms_provider,
    normalize_oauth_smsbower_country=_normalize_oauth_smsbower_country,
    normalize_oauth_smscloud_country=_normalize_oauth_smscloud_country,
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
        logger.warning("[刷新额度] 读取自动刷新配置失败，使用默认关闭: %s", exc)
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
        logger.warning("[刷新额度] 保存自动刷新配置失败: %s", exc)


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
                logger.info("[刷新额度] 自动刷新已关闭，等待重新启用")
                logged_disabled = True
            _auto_refresh_quota_restart.wait(60)
            continue

        logged_disabled = False
        logger.info("[刷新额度] 等待 %d 分钟后执行下一轮自动刷新", max(1, interval // 60))
        _auto_refresh_quota_restart.clear()
        if _auto_refresh_quota_stop.wait(interval):
            break
        if _auto_refresh_quota_restart.is_set():
            continue

        try:
            logger.info("[刷新额度] 开始自动提交刷新额度任务")
            post_accounts_refresh_quota(AccountEmailBatchParams(emails=[]))
        except HTTPException as exc:
            if exc.status_code == 409:
                logger.info("[刷新额度] 已有刷新额度任务在执行，本轮自动刷新跳过")
            elif exc.status_code == 404:
                logger.info("[刷新额度] 没有可刷新额度的账号，本轮跳过")
            else:
                logger.warning("[刷新额度] 自动刷新提交失败: %s", exc.detail)
        except Exception as exc:
            logger.warning("[刷新额度] 自动刷新提交异常: %s", exc)


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
NOTIFICATION_SOUNDS_DIR = Path(__file__).resolve().parents[3] / "assets"


class _FrontendPathConvertor(Convertor[str]):
    regex = r"(?!api(?:/|$)).*"

    def convert(self, value: str) -> str:
        return value

    def to_string(self, value: str) -> str:
        return value


register_url_convertor("frontend_path", _FrontendPathConvertor())


if NOTIFICATION_SOUNDS_DIR.exists():
    app.mount(
        "/notification-sounds",
        StaticFiles(directory=str(NOTIFICATION_SOUNDS_DIR)),
        name="notification_sounds",
    )


if DIST_DIR.exists():
    # Vite 构建的 assets 目录
    assets_dir = DIST_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{path:frontend_path}")
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
        "/api/accounts",
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

    local_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    local_server_base = f"http://{local_host}:{port}"
    if not os.environ.get("AUTOTOKEN_LOCAL_BASE_URL"):
        os.environ["AUTOTOKEN_LOCAL_BASE_URL"] = local_server_base
    os.environ.setdefault("AUTOTEAM_API_BASE_URL", local_server_base)
    os.environ.setdefault("AUTOTOKEN_API_BASE_URL", local_server_base)
    os.environ.setdefault("PAYPAL_PROTOCOL_INTERNAL_BASE_URL", local_server_base)

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
