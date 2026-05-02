"""AutoTeam HTTP API - 将 CLI 功能暴露为 HTTP 接口"""

import json
import logging
import os
import re
import threading
import time
import uuid
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from autoteam.config import API_KEY
from autoteam.textio import read_text

logger = logging.getLogger(__name__)

app = FastAPI(
    title="AutoTeam API",
    description="ChatGPT Team 账号自动轮转管理 API",
    version="0.1.0",
)

# ---------------------------------------------------------------------------
# API Key 鉴权中间件
# ---------------------------------------------------------------------------

_AUTH_SKIP_PATHS = {"/api/auth/check", "/api/setup/status", "/api/setup/save"}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
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


@app.get("/api/auth/check")
def check_auth(request: Request):
    """验证 API Key 是否有效。未配置 API_KEY 时始终返回成功。"""
    if not API_KEY:
        return {"authenticated": True, "auth_required": False}
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer ") and auth_header[7:] == API_KEY:
        return {"authenticated": True, "auth_required": True}
    return JSONResponse(status_code=401, content={"authenticated": False, "auth_required": True})


# ---------------------------------------------------------------------------
# 初始配置 API（无需鉴权）
# ---------------------------------------------------------------------------


class SetupConfig(BaseModel):
    MAIL_PROVIDER: str = "cloudflare_temp_email"
    CLOUDFLARE_TEMP_EMAIL_BASE_URL: str = ""
    CLOUDFLARE_TEMP_EMAIL_ADMIN_PASSWORD: str = ""
    CLOUDFLARE_TEMP_EMAIL_DOMAIN: str = ""
    CLOUD_MAIL_API_URL: str = ""
    CLOUD_MAIL_ADMIN_EMAIL: str = ""
    CLOUD_MAIL_ADMIN_PASSWORD: str = ""
    CLOUD_MAIL_DOMAIN: str = ""
    CPA_URL: str = "http://127.0.0.1:8317"
    CPA_KEY: str = ""
    PLAYWRIGHT_PROXY_URL: str = ""
    PLAYWRIGHT_PROXY_BYPASS: str = ""
    PLAYWRIGHT_BACKGROUND: str = "1"
    API_KEY: str = ""


@app.get("/api/setup/status")
def get_setup_status():
    """检查配置是否完整"""
    from autoteam.setup_wizard import _read_env, get_required_configs_for_provider, get_setup_schema

    env = _read_env()
    schema = get_setup_schema(env)
    fields = []
    all_ok = True
    for key, prompt, default, optional in get_required_configs_for_provider(schema["provider"]):
        val = env.get(key, "") or os.environ.get(key, "")
        ok = bool(val)
        if not ok and not optional:
            all_ok = False
        fields.append({"key": key, "prompt": prompt, "default": default, "optional": optional, "configured": ok})
    schema["configured"] = all_ok
    schema["fields"] = fields
    return schema


@app.post("/api/setup/save")
def post_setup_save(config: SetupConfig):
    """保存配置到 .env 并验证连通性"""
    import secrets as _secrets

    from autoteam.setup_wizard import _write_env, get_mail_provider, get_required_configs_for_provider

    data = config.model_dump()
    provider = get_mail_provider(data.get("MAIL_PROVIDER"))
    data["MAIL_PROVIDER"] = provider
    defaults = {key: default for key, _prompt, default, _optional in get_required_configs_for_provider(provider)}
    if not data.get("CPA_URL"):
        data["CPA_URL"] = defaults.get("CPA_URL", "http://127.0.0.1:8317")
    if not data.get("API_KEY"):
        data["API_KEY"] = _secrets.token_urlsafe(24)

    clearable_fields = {"PLAYWRIGHT_PROXY_URL", "PLAYWRIGHT_PROXY_BYPASS"}
    provider_fields = {
        "cloudflare_temp_email": {
            "CLOUDFLARE_TEMP_EMAIL_BASE_URL",
            "CLOUDFLARE_TEMP_EMAIL_ADMIN_PASSWORD",
            "CLOUDFLARE_TEMP_EMAIL_DOMAIN",
        },
        "cloud-mail": {
            "CLOUD_MAIL_API_URL",
            "CLOUD_MAIL_ADMIN_EMAIL",
            "CLOUD_MAIL_ADMIN_PASSWORD",
            "CLOUD_MAIL_DOMAIN",
        },
    }
    allowed_keys = {
        "MAIL_PROVIDER",
        "CPA_URL",
        "CPA_KEY",
        "PLAYWRIGHT_PROXY_URL",
        "PLAYWRIGHT_PROXY_BYPASS",
        "PLAYWRIGHT_BACKGROUND",
        "API_KEY",
    }
    allowed_keys.update(provider_fields[provider])

    compat_mirrors = {
        "CLOUDFLARE_TEMP_EMAIL_BASE_URL": "CLOUDMAIL_BASE_URL",
        "CLOUDFLARE_TEMP_EMAIL_ADMIN_PASSWORD": "CLOUDMAIL_PASSWORD",
        "CLOUDFLARE_TEMP_EMAIL_DOMAIN": "CLOUDMAIL_DOMAIN",
        "CLOUD_MAIL_API_URL": "MAILLAB_API_URL",
        "CLOUD_MAIL_ADMIN_EMAIL": "MAILLAB_USERNAME",
        "CLOUD_MAIL_ADMIN_PASSWORD": "MAILLAB_PASSWORD",
        "CLOUD_MAIL_DOMAIN": "MAILLAB_DOMAIN",
    }

    for key, value in data.items():
        if key not in allowed_keys and key not in clearable_fields:
            continue
        if value or key in clearable_fields:
            _write_env(key, value)
            os.environ[key] = value
            compat_key = compat_mirrors.get(key)
            if compat_key:
                _write_env(compat_key, value)
                os.environ[compat_key] = value

    # 重新加载模块
    import importlib

    import autoteam.config

    importlib.reload(autoteam.config)
    try:
        import autoteam.cloudmail

        importlib.reload(autoteam.cloudmail)
    except Exception:
        pass

    # 验证连通性
    errors = []
    from autoteam.setup_wizard import _verify_temporary_email, _verify_cpa

    if not _verify_temporary_email():
        errors.append("临时邮箱服务连接失败")
    if not _verify_cpa():
        errors.append("CPA 连接失败")

    if errors:
        return JSONResponse(status_code=400, content={"message": "、".join(errors), "api_key": data["API_KEY"]})

    # 更新运行时 API_KEY
    global API_KEY
    API_KEY = data["API_KEY"]

    return {"message": "配置保存成功", "api_key": data["API_KEY"], "configured": True}


# ---------------------------------------------------------------------------
# 后台任务管理
# ---------------------------------------------------------------------------

_tasks: dict[str, dict] = {}
_playwright_lock = threading.Lock()
_current_task_id: str | None = None
_task_skip_signals: dict[str, threading.Event] = {}
_admin_login_api = None
_admin_login_step: str | None = None
_main_codex_flow = None
_main_codex_step: str | None = None
_manual_account_flow = None
MAX_TASK_HISTORY = 50


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


def _current_busy_detail(default_message: str):
    if _admin_login_api:
        return {
            "message": default_message,
            "running_task": {
                "task_id": "admin-login",
                "command": "admin-login",
                "started_at": None,
            },
        }

    if _main_codex_flow:
        return {
            "message": default_message,
            "running_task": {
                "task_id": "main-codex-sync",
                "command": "main-codex-sync",
                "started_at": None,
            },
        }

    running = _tasks.get(_current_task_id, {})
    return {
        "message": default_message,
        "running_task": {
            "task_id": _current_task_id,
            "command": running.get("command", "unknown"),
            "started_at": running.get("started_at"),
        },
    }


def _prune_tasks():
    """保留最近 MAX_TASK_HISTORY 个任务"""
    if len(_tasks) <= MAX_TASK_HISTORY:
        return
    sorted_ids = sorted(_tasks, key=lambda k: _tasks[k]["created_at"])
    for tid in sorted_ids[: len(_tasks) - MAX_TASK_HISTORY]:
        if _tasks[tid]["status"] in ("completed", "failed"):
            del _tasks[tid]


def _update_current_task_progress(progress: dict):
    """更新当前运行任务的实时进度。"""
    if not _current_task_id:
        return
    task = _tasks.get(_current_task_id)
    if not task:
        return
    now = time.time()
    event = {
        **dict(progress or {}),
        "event_id": uuid.uuid4().hex[:12],
        "updated_at": now,
    }
    task["progress"] = {
        **(task.get("progress") or {}),
        **event,
    }
    progress_events = task.setdefault("progress_events", [])
    progress_events.append(event)
    if len(progress_events) > 300:
        del progress_events[: len(progress_events) - 300]


def _run_task(task_id: str, func, *args, **kwargs):
    """在后台线程中执行任务"""
    from autoteam import cancel_signal

    global _current_task_id
    task = _tasks[task_id]

    _playwright_lock.acquire()
    # 顺序很关键: 先 reset() 再暴露 _current_task_id。否则 post_task_cancel 在
    # 两行之间读到新 task_id 并 request_cancel(),随后被我们的 reset() 清掉,
    # 用户的取消请求被静默吞掉。
    cancel_signal.reset()
    _current_task_id = task_id
    task["status"] = "running"
    task["started_at"] = time.time()

    try:
        result = func(*args, **kwargs)
        # 任务完成但中途确实收到取消 → 标 cancelled
        task["status"] = "cancelled" if cancel_signal.is_cancelled() else "completed"
        task["result"] = result
    except Exception as e:
        task["status"] = "cancelled" if cancel_signal.is_cancelled() else "failed"
        if getattr(e, "task_result", None) is not None:
            task["result"] = e.task_result
        task["error"] = str(e)
        logger.error("[API] 任务 %s %s: %s", task_id[:8], task["status"], e)
    finally:
        task["finished_at"] = time.time()
        _current_task_id = None
        _task_skip_signals.pop(task_id, None)
        _playwright_lock.release()


def _start_task(command: str, func, params: dict, *args, **kwargs) -> dict:
    """创建并启动后台任务，返回任务信息"""
    if not _playwright_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=_current_busy_detail("有任务正在执行，请等待完成后再试"))
    _playwright_lock.release()

    task_id = uuid.uuid4().hex[:12]
    task = {
        "task_id": task_id,
        "command": command,
        "params": params,
        "status": "pending",
        "created_at": time.time(),
        "started_at": None,
        "finished_at": None,
        "result": None,
        "error": None,
        "progress": None,
        "progress_events": [],
    }
    _tasks[task_id] = task
    _prune_tasks()

    thread = threading.Thread(target=_run_task, args=(task_id, func, *args), kwargs=kwargs, daemon=True)
    thread.start()

    return task


# ---------------------------------------------------------------------------
# 响应模型
# ---------------------------------------------------------------------------


class TaskParams(BaseModel):
    target: int = 5
    leave_workspace: bool = False  # cmd_fill 专用：True 表示生产免费号（注册后退出 Team 走 personal OAuth）


class CleanupParams(BaseModel):
    max_seats: int | None = None


class AdminEmailParams(BaseModel):
    email: str


class AdminSessionParams(BaseModel):
    email: str
    session_token: str


class AdminPasswordParams(BaseModel):
    password: str


class AdminCodeParams(BaseModel):
    code: str


class AdminWorkspaceParams(BaseModel):
    option_id: str


class ManualAccountCallbackParams(BaseModel):
    redirect_url: str


class TeamMemberRemoveParams(BaseModel):
    email: str
    user_id: str
    type: str


class RegisterDomainParams(BaseModel):
    domain: str
    verify: bool = True  # 默认写入前试探一次临时邮箱服务是否接受该域


class RegisterDomainsParams(BaseModel):
    domains: list[str]
    selected: str | None = None


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


class BindCardTaskParams(BaseModel):
    email: str
    card_item_id: str
    checkout_url: str
    proxy_url: str | None = None
    proxy_label: str = ""
    proxy_bypass: str | None = None
    manual_confirm: bool = True
    timeout_seconds: int = 900


class GoPayBindTaskParams(BaseModel):
    email: str
    account_emails: list[str] = []
    phone_number: str
    country_code: str = ""
    sms_url: str
    gopay_pin: str
    billing_name: str = ""
    billing_country: str = "US"
    billing_state: str = ""
    billing_city: str = ""
    billing_zip: str = ""
    billing_address1: str = ""
    billing_address2: str = ""
    checkout_url: str = ""
    proxy_url: str | None = None
    proxy_label: str = ""
    proxy_bypass: str | None = None
    timeout_seconds: int = 900
    delete_rejected_accounts: bool = False


class CardPoolImportParams(BaseModel):
    pool_type: str
    text: str
    provider: str = ""


class CardPoolDeleteParams(BaseModel):
    pool_type: str
    ids: list[str]


class CardPoolUpdateParams(BaseModel):
    pool_type: str
    item_id: str
    status: str | None = None
    provider: str | None = None
    used_by: str | None = None
    expires_at: str | None = None


class CardPoolRedeemParams(BaseModel):
    item_id: str


class CardPoolRedeemBatchParams(BaseModel):
    item_ids: list[str]


class CardPoolFetchSmsParams(BaseModel):
    url: str


class ManualRegisterParams(BaseModel):
    mode: str = "single"
    count: int = 1
    concurrency: int = 3
    interval_seconds: float = 12.0
    jitter_min_seconds: float = 8.0
    jitter_max_seconds: float = 20.0
    domain: str | None = None
    domains: list[str] = []
    prefix: str | None = None
    password: str | None = None


class DeleteBatchParams(BaseModel):
    emails: list[str]
    continue_on_error: bool = True  # 部分失败时继续剩余账号,False 则遇错即停


class AccountTypeUpdateParams(BaseModel):
    account_type: str


class AccountCredentialExportParams(BaseModel):
    emails: list[str] = []
    line_format: str = "{email}-----{password}"


def _normalized_email(value: str | None) -> str:
    return (value or "").strip().lower()


def _is_main_account_email(email: str | None) -> bool:
    from autoteam.admin_state import get_admin_email

    return bool(_normalized_email(email)) and _normalized_email(email) == _normalized_email(get_admin_email())


def _quota_snapshot_status(quota_info: dict | None) -> str:
    if not isinstance(quota_info, dict):
        return ""

    values = []
    for key in ("primary_pct", "weekly_pct"):
        value = quota_info.get(key)
        if isinstance(value, (int, float)):
            values.append(value)

    if not values:
        return ""
    return "exhausted" if any(value >= 100 for value in values) else "active"


def _resolve_status_auth_file(acc: dict) -> str:
    auth_file = (acc.get("auth_file") or "").strip()
    if auth_file and Path(auth_file).exists():
        return auth_file

    try:
        from autoteam.auth_session_store import get_auth_session_file

        session_file = get_auth_session_file(acc.get("email") or "")
        if session_file and Path(session_file).exists():
            return session_file
    except Exception:
        pass

    if _is_main_account_email(acc.get("email")):
        from autoteam.codex_auth import get_saved_main_auth_file

        saved_auth_file = get_saved_main_auth_file()
        if saved_auth_file and Path(saved_auth_file).exists():
            return saved_auth_file

    return ""


def _display_account_status(acc: dict, quota_snapshot: dict | None = None) -> str:
    status = acc.get("status", "")
    if status in ("personal", "plus"):
        status = "active"
    if not _is_main_account_email(acc.get("email")):
        return status

    quota_status = _quota_snapshot_status(quota_snapshot) or _quota_snapshot_status(acc.get("last_quota"))
    if quota_status:
        return quota_status

    return "active" if _resolve_status_auth_file(acc) else status


def _display_account_type(acc: dict) -> str:
    account_type = (acc.get("account_type") or "").strip().lower()
    if account_type in {"free", "team", "plus", "pro"}:
        return account_type
    status = (acc.get("status") or "").strip().lower()
    if status == "plus":
        return "plus"
    if status == "personal":
        return "free"
    if status in {"active", "exhausted", "standby"}:
        return "team"
    return "free"


def _sanitize_account(acc: dict, quota_snapshot: dict | None = None) -> dict:
    """脱敏账号信息（去掉 password 等敏感字段）"""
    sanitized = {k: v for k, v in acc.items() if k not in ("password", "cloudmail_account_id")}
    sanitized["is_main_account"] = _is_main_account_email(acc.get("email"))
    sanitized["status"] = _display_account_status(acc, quota_snapshot)
    sanitized["account_type"] = _display_account_type(acc)
    try:
        from autoteam.auth_session_store import get_auth_session_file

        sanitized["auth_session_file"] = get_auth_session_file(acc.get("email") or "")
    except Exception:
        sanitized["auth_session_file"] = ""
    return sanitized


def _admin_status():
    from autoteam.admin_state import get_admin_state_summary

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
                from autoteam.codex_auth import refresh_main_auth_file

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


def _is_bind_card_reusable_result(result: dict) -> bool:
    return (result.get("status") == "failed") and (result.get("failure_stage") in {"open_checkout", "fill_card"})


def _is_gopay_checkout_not_approved_result(result: dict) -> bool:
    if not isinstance(result, dict):
        return False
    stage = str(result.get("failure_stage") or "")
    if stage not in {"checkout_not_approved", "browser_checkout", "submit_checkout"}:
        return False
    message = str(result.get("message") or "")
    return bool(
        re.search(r"付款.*未获批准|未获批准", message)
        or re.search(r"payment\s+(?:was\s+)?not\s+approved|payment\s+(?:was\s+)?declined|not\s+approved", message, re.I)
    )


def _gopay_rejected_pool_emails(result: dict, actual_email: str) -> list[str]:
    seen = set()
    emails = []
    for raw_email in result.get("rejected_emails") or []:
        email = _normalized_email(raw_email)
        if email and email not in seen:
            seen.add(email)
            emails.append(email)
    if _is_gopay_checkout_not_approved_result(result):
        email = _normalized_email(actual_email)
        if email and email not in seen:
            emails.append(email)
    return emails


def _gopay_nonzero_blocked_pool_emails(result: dict, actual_email: str) -> list[str]:
    seen = set()
    emails = []
    for raw_email in result.get("nonzero_blocked_emails") or []:
        email = _normalized_email(raw_email)
        if email and email not in seen:
            seen.add(email)
            emails.append(email)
    if str(result.get("failure_stage") or "") in {"browser_charge_guard", "stripe_charge_guard", "midtrans_charge_guard"}:
        email = _normalized_email(actual_email)
        if email and email not in seen:
            emails.append(email)
    return emails


def _remove_gopay_rejected_accounts_from_pool(emails: list[str]) -> list[str]:
    if not emails:
        return []
    from autoteam.accounts import delete_account as delete_local_account, find_account, load_accounts
    from autoteam.auth_session_store import delete_auth_session
    from autoteam.mail import TemporaryEmailClient

    removed = []
    accounts = load_accounts()
    mail_client = None
    for email in emails:
        if not email or _is_main_account_email(email):
            continue
        account = find_account(accounts, email)
        mail_target = (account or {}).get("cloudmail_account_id") or email
        mail_deleted = False
        if mail_target:
            try:
                if mail_client is None:
                    mail_client = TemporaryEmailClient()
                    mail_client.login()
                resp = mail_client.delete_account(mail_target)
                mail_deleted = bool(isinstance(resp, dict) and resp.get("code") == 200)
            except Exception as exc:
                logger.warning("[gopay-bind] failed to delete rejected account from email service: email=%s error=%s", email, exc)
        record_deleted = delete_local_account(email)
        session_deleted = delete_auth_session(email)
        if record_deleted or session_deleted or mail_deleted:
            removed.append(email)
        logger.info(
            "[gopay-bind] rejected/nonzero account removed: email=%s record_deleted=%s auth_session_deleted=%s mail_deleted=%s mail_target=%s",
            email,
            record_deleted,
            session_deleted,
            mail_deleted,
            mail_target,
        )
    return removed


def _session_only_account_stub(email: str) -> dict:
    return {
        "email": email,
        "password": "",
        "cloudmail_account_id": None,
        "status": "active",
        "account_type": "free",
        "seat_type": "codex",
        "auth_file": "",
        "created_at": 0,
        "last_active_at": None,
    }


# ---------------------------------------------------------------------------
# 同步端点
# ---------------------------------------------------------------------------


@app.get("/api/admin/status")
def get_admin_status():
    """获取管理员登录状态。"""
    return _admin_status()


@app.post("/api/admin/fix-account-id")
def post_admin_fix_account_id():
    """
    基于当前已保存的 session_token,重新从 /backend-api/accounts 拉取真实 workspace 列表,
    覆盖写入 admin_state.account_id / workspace_name。适用于: 之前导入的 session 把
    account_id 误写成了 OAI 缓存的陈旧 UUID,导致所有 admin 接口 401。

    不需要用户手动退出重登 —— 只是重算 account_id。
    """
    from autoteam.admin_state import (
        get_admin_email,
        get_admin_session_token,
        get_chatgpt_account_id,
        update_admin_state,
    )
    from autoteam.chatgpt_api import ChatGPTTeamAPI

    if not get_admin_session_token():
        raise HTTPException(status_code=400, detail="尚未保存 session_token,请先导入")

    def _do():
        api = ChatGPTTeamAPI()
        try:
            api._launch_browser()
            logger.info("[修复 account_id] 打开 chatgpt.com 注入 session...")
            api.page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)
            api._wait_for_cloudflare()
            api._inject_session(get_admin_session_token())
            # 注入 session 后可能触发一次新的 CF 挑战,再等一次避免首个 _api_fetch 碰上 challenge 页
            api.page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=60000)
            time.sleep(2)
            api._wait_for_cloudflare()
            api._fetch_access_token()

            team, personal = api._list_real_workspaces()
            admin_roles = ("account-owner", "admin", "org-admin", "workspace-owner")
            chosen = None
            for acc in team:
                if str(acc.get("current_user_role") or "").lower() in admin_roles:
                    chosen = acc
                    break
            if not chosen and team:
                chosen = team[0]
            if not chosen:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"当前 session ({get_admin_email()}) 没有 Team workspace,"
                        f" 只有: {[a.get('structure') for a in personal]}。"
                        f"请确认该账号已被邀请加入 Team。"
                    ),
                )

            new_account_id = str(chosen.get("id") or "")
            new_workspace_name = str(chosen.get("name") or "")

            # 用新 account_id 验证接口是否真能访问
            api.account_id = new_account_id
            verify = api._api_fetch("GET", f"/backend-api/accounts/{new_account_id}/settings")
            if verify.get("status") != 200:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"新 account_id={new_account_id} 仍不可访问 "
                        f"status={verify.get('status')},session_token 可能已过期,请重新导入。"
                    ),
                )

            old_account_id = get_chatgpt_account_id()
            update_admin_state(account_id=new_account_id, workspace_name=new_workspace_name)
            logger.info(
                "[修复 account_id] 已更新: %s -> %s (workspace=%s)",
                old_account_id,
                new_account_id,
                new_workspace_name,
            )
            return {
                "message": "已修复",
                "old_account_id": old_account_id,
                "new_account_id": new_account_id,
                "workspace_name": new_workspace_name,
                "role": chosen.get("current_user_role"),
            }
        finally:
            try:
                api.stop()
            except Exception:
                pass

    if not _playwright_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=_current_busy_detail("有任务正在执行"))
    try:
        return _pw_executor.run(_do)
    finally:
        _playwright_lock.release()


@app.get("/api/admin/diagnose")
def get_admin_diagnose():
    """
    用当前管理员 session_token 探测 Team admin 接口,辅助诊断 401/403。
    返回四个关键接口的状态码 + body 前 200 字:
    - /api/auth/session  → access_token 是否拿到
    - /backend-api/me    → 当前登录用户是谁
    - /backend-api/accounts/<id>/settings  → workspace 是否可读
    - /backend-api/accounts/<id>/users     → admin 权限是否生效(真正的 fill-personal 卡点)
    """
    from autoteam.admin_state import get_admin_email, get_chatgpt_account_id
    from autoteam.chatgpt_api import ChatGPTTeamAPI

    def _do():
        # 只读诊断:必须走手动 launch+inject,不调 api.start()——start() 里的
        # _auto_detect_workspace 会写 admin_state,把诊断弄成副作用操作
        from autoteam.admin_state import get_admin_session_token

        api = ChatGPTTeamAPI()
        try:
            api._launch_browser()
            api.page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)
            api._wait_for_cloudflare()
            session_token = get_admin_session_token()
            if session_token:
                api.account_id = get_chatgpt_account_id() or ""  # 让 _inject_session 把 _account cookie 带上
                api._inject_session(session_token)
                api.page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=60000)
                time.sleep(2)
                api._wait_for_cloudflare()
            api._fetch_access_token()
            account_id = api.account_id or get_chatgpt_account_id() or ""
            probes = {}

            session_result = api.page.evaluate(
                "async () => { const r = await fetch('/api/auth/session'); "
                "return { status: r.status, body: (await r.text()).slice(0, 400) }; }"
            )
            probes["auth_session"] = session_result

            for name, path in [
                ("backend_me", "/backend-api/me"),
                ("backend_accounts", "/backend-api/accounts"),
                ("workspace_settings", f"/backend-api/accounts/{account_id}/settings"),
                ("workspace_users", f"/backend-api/accounts/{account_id}/users"),
            ]:
                r = api._api_fetch("GET", path)
                probes[name] = {"status": r.get("status"), "body": (r.get("body") or "")[:500]}

            return {
                "admin_email": get_admin_email(),
                "account_id": account_id,
                "access_token_present": bool(api.access_token),
                "access_token_prefix": (api.access_token or "")[:30],
                "probes": probes,
            }
        finally:
            try:
                api.stop()
            except Exception:
                pass

    if not _playwright_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=_current_busy_detail("有任务正在执行"))
    try:
        return _pw_executor.run(_do)
    finally:
        _playwright_lock.release()


@app.post("/api/admin/reconcile")
def post_admin_reconcile(request: Request):
    """对账 Team 实际成员 vs 本地状态,修复残废 / 错位 / 耗尽未抛弃 / ghost。

    与 /api/admin/diagnose 使用同款鉴权模式(auth_middleware 已处理 API_KEY)。
    查询参数:
        dry_run=1 → 只诊断,不 KICK、不改 accounts.json
    返回 _reconcile_team_members 的完整结果 dict。
    """
    from autoteam.manager import cmd_reconcile

    dry_run = str(request.query_params.get("dry_run", "")).strip().lower() in ("1", "true", "yes")

    def _do():
        return cmd_reconcile(dry_run=dry_run)

    if not _playwright_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=_current_busy_detail("有任务正在执行"))
    try:
        return _pw_executor.run(_do)
    finally:
        _playwright_lock.release()


@app.get("/api/main-codex/status")
def get_main_codex_status():
    """获取主号 Codex 同步状态。"""
    return _main_codex_status()


@app.get("/api/manual-account/status")
def get_manual_account_status():
    """获取手动添加账号状态。"""
    return _manual_account_status()


@app.post("/api/admin/login/start")
def post_admin_login_start(params: AdminEmailParams):
    """开始管理员登录流程。"""
    global _admin_login_api, _admin_login_step

    if _admin_login_api:
        try:
            _pw_executor.run(_admin_login_api.stop)
        except Exception:
            pass
        _admin_login_api = None
        _admin_login_step = None
        if _playwright_lock.locked():
            _playwright_lock.release()

    if not _playwright_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409, detail=_current_busy_detail("有任务正在执行，请等待完成后再进行管理员登录")
        )

    try:
        from autoteam.chatgpt_api import ChatGPTTeamAPI

        logger.info("[API] 开始管理员登录: %s", params.email.strip())

        def _do_start(email):
            api = ChatGPTTeamAPI()
            result = api.begin_admin_login(email)
            return api, result

        api, result = _pw_executor.run(_do_start, params.email.strip())
        step = result["step"]
        logger.info("[API] 管理员登录 start 返回: step=%s detail=%s", step, result.get("detail"))
        if step == "completed":
            _admin_login_api = api
            return _finish_admin_login(result)
        if step in ("password_required", "code_required", "workspace_required"):
            return _set_pending_admin_login(api, step)
        _pw_executor.run(api.stop)
        _playwright_lock.release()
        raise HTTPException(status_code=400, detail=result.get("detail") or "无法识别管理员登录步骤")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[API] 管理员登录 start 失败")
        if _playwright_lock.locked():
            _playwright_lock.release()
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/admin/login/session")
def post_admin_login_session(params: AdminSessionParams):
    """手动导入管理员 session_token。"""
    global _admin_login_api, _admin_login_step

    if _admin_login_api:
        post_admin_login_cancel()

    if not _playwright_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail=_current_busy_detail("有任务正在执行，请等待完成后再导入管理员 session_token"),
        )

    try:
        from autoteam.chatgpt_api import ChatGPTTeamAPI

        logger.info("[API] 导入管理员 session_token: %s", params.email.strip())

        def _do_import(email, session_token):
            api = ChatGPTTeamAPI()
            try:
                return api.import_admin_session(email, session_token)
            finally:
                api.stop()

        info = _pw_executor.run(_do_import, params.email.strip(), params.session_token.strip())
        if info.get("session_token") and info.get("account_id"):
            try:
                from autoteam.codex_auth import refresh_main_auth_file

                main_auth = _pw_executor.run(refresh_main_auth_file)
                if main_auth:
                    info["main_auth"] = main_auth
                    logger.info("[API] session_token 导入后已刷新主号认证文件: %s", main_auth.get("auth_file"))
            except Exception as exc:
                info["main_auth_error"] = str(exc)
                logger.warning("[API] session_token 导入完成，但刷新主号认证文件失败: %s", exc)
        _admin_login_api = None
        _admin_login_step = None
        return {"status": "completed", "admin": _admin_status(), "info": info}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[API] 导入管理员 session_token 失败")
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if _playwright_lock.locked():
            _playwright_lock.release()


@app.post("/api/admin/login/password")
def post_admin_login_password(params: AdminPasswordParams):
    """提交管理员密码。"""
    global _admin_login_api, _admin_login_step
    if not _admin_login_api or _admin_login_step != "password_required":
        raise HTTPException(status_code=409, detail="当前没有等待密码的管理员登录流程")

    try:
        logger.info("[API] 提交管理员密码 | current_step=%s", _admin_login_step)
        result = _pw_executor.run(_admin_login_api.submit_admin_password, params.password)
        step = result["step"]
        logger.info("[API] 管理员密码提交返回: step=%s detail=%s", step, result.get("detail"))
        if step == "completed":
            return _finish_admin_login(result)
        if step in ("password_required", "code_required", "workspace_required"):
            _admin_login_step = step
            return {"status": step, "admin": _admin_status()}
        raise HTTPException(status_code=400, detail=result.get("detail") or "管理员密码登录失败")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[API] 管理员密码提交失败")
        try:
            _pw_executor.run(_admin_login_api.stop)
        except Exception:
            pass
        _admin_login_api = None
        _admin_login_step = None
        if _playwright_lock.locked():
            _playwright_lock.release()
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/admin/login/code")
def post_admin_login_code(params: AdminCodeParams):
    """提交管理员验证码。"""
    global _admin_login_api, _admin_login_step
    if not _admin_login_api or _admin_login_step != "code_required":
        raise HTTPException(status_code=409, detail="当前没有等待验证码的管理员登录流程")

    try:
        logger.info("[API] 提交管理员验证码 | current_step=%s code_len=%d", _admin_login_step, len(params.code.strip()))
        result = _pw_executor.run(_admin_login_api.submit_admin_code, params.code.strip())
        step = result["step"]
        logger.info("[API] 管理员验证码提交返回: step=%s detail=%s", step, result.get("detail"))
        if step == "completed":
            return _finish_admin_login(result)
        if step in ("password_required", "code_required", "workspace_required"):
            _admin_login_step = step
            return {"status": step, "admin": _admin_status()}
        raise HTTPException(status_code=400, detail=result.get("detail") or "管理员验证码登录失败")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[API] 管理员验证码提交失败")
        try:
            _pw_executor.run(_admin_login_api.stop)
        except Exception:
            pass
        _admin_login_api = None
        _admin_login_step = None
        if _playwright_lock.locked():
            _playwright_lock.release()
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/admin/login/workspace")
def post_admin_login_workspace(params: AdminWorkspaceParams):
    """提交管理员 workspace 选择。"""
    global _admin_login_api, _admin_login_step
    if not _admin_login_api or _admin_login_step != "workspace_required":
        raise HTTPException(status_code=409, detail="当前没有等待组织选择的管理员登录流程")

    try:
        logger.info("[API] 提交管理员 workspace 选择 | option_id=%s", params.option_id)
        result = _pw_executor.run(_admin_login_api.select_workspace_option, params.option_id)
        step = result["step"]
        logger.info("[API] 管理员 workspace 选择返回: step=%s detail=%s", step, result.get("detail"))
        if step == "completed":
            return _finish_admin_login(result)
        if step in ("password_required", "code_required", "workspace_required"):
            _admin_login_step = step
            return {"status": step, "admin": _admin_status()}
        raise HTTPException(status_code=400, detail=result.get("detail") or "管理员组织选择失败")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[API] 管理员 workspace 选择失败")
        try:
            _pw_executor.run(_admin_login_api.stop)
        except Exception:
            pass
        _admin_login_api = None
        _admin_login_step = None
        if _playwright_lock.locked():
            _playwright_lock.release()
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/admin/login/cancel")
def post_admin_login_cancel():
    """取消管理员登录流程。"""
    global _admin_login_api, _admin_login_step
    if _admin_login_api:
        try:
            _pw_executor.run(_admin_login_api.stop)
        except Exception:
            pass
        _admin_login_api = None
        _admin_login_step = None
        if _playwright_lock.locked():
            _playwright_lock.release()
    return {"message": "管理员登录已取消", "admin": _admin_status()}


@app.post("/api/admin/logout")
def post_admin_logout():
    """清除已保存的管理员登录态。"""
    from autoteam.admin_state import clear_admin_state

    if _admin_login_api:
        post_admin_login_cancel()
    clear_admin_state()
    return {"message": "管理员登录态已清除", "admin": _admin_status()}


@app.post("/api/main-codex/start")
def post_main_codex_start():
    """开始主号 Codex 登录并同步到 CPA。"""
    global _main_codex_flow, _main_codex_step

    if _main_codex_flow:
        try:
            _pw_executor.run(_main_codex_flow.stop)
        except Exception:
            pass
        _main_codex_flow = None
        _main_codex_step = None
        if _playwright_lock.locked():
            _playwright_lock.release()

    from autoteam.codex_auth import get_saved_main_auth_file
    from autoteam.cpa_sync import sync_main_codex_to_cpa

    saved_auth_file = get_saved_main_auth_file()
    if saved_auth_file:
        sync_main_codex_to_cpa(saved_auth_file)
        return {
            "status": "completed",
            "message": "主号 Codex 已同步到 CPA",
            "codex": _main_codex_status(),
            "info": {"auth_file": saved_auth_file},
        }

    if not _playwright_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409, detail=_current_busy_detail("有任务正在执行，请等待完成后再同步主号 Codex")
        )

    try:
        from autoteam.codex_auth import MainCodexSyncFlow

        def _do_start():
            flow = MainCodexSyncFlow()
            result = flow.start()
            return flow, result

        flow, result = _pw_executor.run(_do_start)
        step = result["step"]
        if step == "completed":
            _main_codex_flow = flow
            return _finish_main_codex_sync()
        if step in ("password_required", "code_required"):
            return _set_pending_main_codex_sync(flow, step)
        _pw_executor.run(flow.stop)
        _playwright_lock.release()
        raise HTTPException(status_code=400, detail=result.get("detail") or "无法识别主号 Codex 登录步骤")
    except HTTPException:
        raise
    except Exception as exc:
        if _playwright_lock.locked():
            _playwright_lock.release()
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/main-codex/password")
def post_main_codex_password(params: AdminPasswordParams):
    """提交主号 Codex 登录密码。"""
    global _main_codex_flow, _main_codex_step
    if not _main_codex_flow or _main_codex_step != "password_required":
        raise HTTPException(status_code=409, detail="当前没有等待密码的主号 Codex 登录流程")

    try:
        result = _pw_executor.run(_main_codex_flow.submit_password, params.password)
        step = result["step"]
        if step == "completed":
            return _finish_main_codex_sync()
        if step in ("password_required", "code_required"):
            _main_codex_step = step
            return {"status": step, "codex": _main_codex_status()}
        raise HTTPException(status_code=400, detail=result.get("detail") or "主号 Codex 密码登录失败")
    except HTTPException:
        raise
    except Exception as exc:
        try:
            _pw_executor.run(_main_codex_flow.stop)
        except Exception:
            pass
        _main_codex_flow = None
        _main_codex_step = None
        if _playwright_lock.locked():
            _playwright_lock.release()
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/main-codex/code")
def post_main_codex_code(params: AdminCodeParams):
    """提交主号 Codex 登录验证码。"""
    global _main_codex_flow, _main_codex_step
    if not _main_codex_flow or _main_codex_step != "code_required":
        raise HTTPException(status_code=409, detail="当前没有等待验证码的主号 Codex 登录流程")

    try:
        result = _pw_executor.run(_main_codex_flow.submit_code, params.code.strip())
        step = result["step"]
        if step == "completed":
            return _finish_main_codex_sync()
        if step in ("password_required", "code_required"):
            _main_codex_step = step
            return {"status": step, "codex": _main_codex_status()}
        raise HTTPException(status_code=400, detail=result.get("detail") or "主号 Codex 验证码登录失败")
    except HTTPException:
        raise
    except Exception as exc:
        try:
            _pw_executor.run(_main_codex_flow.stop)
        except Exception:
            pass
        _main_codex_flow = None
        _main_codex_step = None
        if _playwright_lock.locked():
            _playwright_lock.release()
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/main-codex/cancel")
def post_main_codex_cancel():
    """取消主号 Codex 登录流程。"""
    global _main_codex_flow, _main_codex_step
    if _main_codex_flow:
        try:
            _pw_executor.run(_main_codex_flow.stop)
        except Exception:
            pass
        _main_codex_flow = None
        _main_codex_step = None
        if _playwright_lock.locked():
            _playwright_lock.release()
    return {"message": "主号 Codex 登录已取消", "codex": _main_codex_status()}


@app.post("/api/manual-account/start")
def post_manual_account_start():
    """开始手动添加账号流程，返回 OAuth 链接。"""
    global _manual_account_flow

    if _manual_account_flow:
        try:
            _manual_account_flow.stop()
        except Exception:
            pass
        _manual_account_flow = None

    try:
        from autoteam.manual_account import ManualAccountFlow

        flow = ManualAccountFlow()
        result = flow.start()
        return _set_pending_manual_account_flow(flow, result)
    except HTTPException:
        raise
    except Exception as exc:
        if _manual_account_flow:
            try:
                _manual_account_flow.stop()
            except Exception:
                pass
            _manual_account_flow = None
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/manual-account/callback")
def post_manual_account_callback(params: ManualAccountCallbackParams):
    """提交 OAuth 回调 URL，完成手动添加账号。"""
    global _manual_account_flow
    if not _manual_account_flow:
        raise HTTPException(status_code=409, detail="当前没有等待回调的手动添加账号流程")

    try:
        result = _manual_account_flow.submit_callback(params.redirect_url)
        return _finish_manual_account_flow(result)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/manual-account/cancel")
def post_manual_account_cancel():
    """取消手动添加账号流程。"""
    global _manual_account_flow
    if _manual_account_flow:
        try:
            _manual_account_flow.stop()
        except Exception:
            pass
        _manual_account_flow = None
    return {"message": "手动添加账号流程已取消", "manual_account": _manual_account_status()}


@app.get("/api/accounts")
def get_accounts():
    """获取所有账号列表"""
    from autoteam.accounts import load_accounts
    from autoteam.auth_session_store import list_auth_session_emails

    accounts = load_accounts()
    existing_emails = {str(acc.get("email") or "").strip().lower() for acc in accounts}
    for email in list_auth_session_emails():
        if email in existing_emails:
            continue
        accounts.append(_session_only_account_stub(email))
    return [_sanitize_account(a) for a in accounts]


@app.get("/api/accounts/{email}/codex-auth")
def get_codex_auth(email: str):
    """导出账号的 Codex CLI 格式认证文件（~/.codex/auth.json）"""
    from autoteam.accounts import find_account, load_accounts
    from autoteam.auth_session_store import get_auth_session_file
    from autoteam.codex_auth import get_saved_main_auth_file

    email = email.strip().lower()
    auth_file = ""

    if _is_main_account_email(email):
        auth_file = get_saved_main_auth_file()
        if not auth_file or not Path(auth_file).exists():
            raise HTTPException(status_code=404, detail="主号没有可导出的认证文件")
    else:
        acc = find_account(load_accounts(), email)
        auth_file = ""
        if acc:
            auth_file = acc.get("auth_file") or ""
        if not auth_file:
            auth_file = get_auth_session_file(email) or ""
        if not auth_file or not Path(auth_file).exists():
            raise HTTPException(status_code=404, detail="该账号没有认证文件")

    auth_data = json.loads(Path(auth_file).read_text())

    access_token = auth_data.get("access_token", "")
    if not access_token:
        access_token = auth_data.get("accessToken", "")

    account_id = auth_data.get("account_id", "")
    if not account_id:
        account_id = ((auth_data.get("account") or {}).get("id") or "")

    # 转换为 Codex CLI 的 auth.json 格式
    codex_auth = {
        "auth_mode": "chatgpt",
        "OPENAI_API_KEY": None,
        "tokens": {
            "id_token": auth_data.get("id_token", ""),
            "access_token": access_token,
            "refresh_token": auth_data.get("refresh_token", ""),
            "account_id": account_id,
        },
        "last_refresh": auth_data.get("last_refresh", ""),
    }

    return {
        "email": email,
        "codex_auth": codex_auth,
        "auth_file": auth_file,
        "hint": "将内容保存到 ~/.codex/auth.json（Linux/macOS）或 %APPDATA%\\codex\\auth.json（Windows）",
    }


@app.get("/api/accounts/active")
def get_active():
    """获取活跃账号"""
    from autoteam.accounts import get_active_accounts

    return [_sanitize_account(a) for a in get_active_accounts()]


@app.get("/api/accounts/standby")
def get_standby():
    """获取待命账号"""
    from autoteam.accounts import get_standby_accounts

    accounts = get_standby_accounts()
    return [_sanitize_account(a) for a in accounts]


@app.delete("/api/accounts/{email}")
def delete_account(email: str):
    """删除本地管理账号及其关联资源。"""
    if not _playwright_lock.acquire(blocking=False):
        running = _tasks.get(_current_task_id, {})
        raise HTTPException(
            status_code=409,
            detail={
                "message": "有任务正在执行，请等待完成后再删除账号",
                "running_task": {
                    "task_id": _current_task_id,
                    "command": running.get("command", "unknown"),
                    "started_at": running.get("started_at"),
                },
            },
        )

    try:
        from autoteam.account_ops import delete_managed_account
        from autoteam.accounts import load_accounts
        from autoteam.admin_state import get_admin_session_token, get_chatgpt_account_id

        if _is_main_account_email(email):
            raise HTTPException(status_code=400, detail="主号不允许删除")

        accounts = load_accounts()
        if not any(a["email"].lower() == email.lower() for a in accounts):
            raise HTTPException(status_code=404, detail="账号不存在")

        remote_cleanup = bool(get_admin_session_token() and get_chatgpt_account_id())
        cleanup = _pw_executor.run(delete_managed_account, email, remove_remote=remote_cleanup)
        return {
            "message": "账号删除完成",
            "deleted_email": email,
            "cleanup": cleanup,
            "remote_cleanup": remote_cleanup,
        }
    finally:
        _playwright_lock.release()


@app.post("/api/accounts/{email}/type")
def update_account_type(email: str, params: AccountTypeUpdateParams):
    """手动更新账号类型。只改本地 accounts.json，不做 Team/CPA 侧操作。"""
    from autoteam.accounts import (
        ACCOUNT_TYPE_FREE,
        ACCOUNT_TYPE_PLUS,
        ACCOUNT_TYPE_PRO,
        ACCOUNT_TYPE_TEAM,
        find_account,
        load_accounts,
        update_account,
    )

    normalized_email = email.strip().lower()
    next_type = (params.account_type or "").strip().lower()
    allowed_types = {
        ACCOUNT_TYPE_FREE,
        ACCOUNT_TYPE_TEAM,
        ACCOUNT_TYPE_PLUS,
        ACCOUNT_TYPE_PRO,
    }
    if next_type not in allowed_types:
        raise HTTPException(status_code=400, detail=f"不支持的账号类型: {params.account_type}")
    if _is_main_account_email(normalized_email):
        raise HTTPException(status_code=400, detail="主号账号类型不允许手动修改")

    account = find_account(load_accounts(), normalized_email)
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")

    updated = update_account(normalized_email, account_type=next_type)
    return {
        "message": f"已将 {normalized_email} 账号类型更新为 {next_type}",
        "account": _sanitize_account(updated),
    }


@app.post("/api/accounts/export-credentials")
def export_account_credentials(params: AccountCredentialExportParams):
    """按自定义行格式导出本地账号池账密。"""
    from autoteam.accounts import load_accounts

    line_format = (params.line_format or "{email}-----{password}").strip()
    if not line_format:
        raise HTTPException(status_code=400, detail="导出格式不能为空")
    if len(line_format) > 500:
        raise HTTPException(status_code=400, detail="导出格式过长")

    requested = []
    seen = set()
    for email in params.emails or []:
        normalized = _normalized_email(email)
        if normalized and normalized not in seen:
            seen.add(normalized)
            requested.append(normalized)
    requested_set = set(requested)

    accounts = load_accounts()
    rows = []
    missing = []
    by_email = {_normalized_email(acc.get("email")): acc for acc in accounts if _normalized_email(acc.get("email"))}
    if requested:
        for email in requested:
            account = by_email.get(email)
            if account:
                rows.append(account)
            else:
                missing.append(email)
    else:
        rows = accounts

    def render_line(account: dict) -> str:
        values = {
            "email": str(account.get("email") or ""),
            "password": str(account.get("password") or ""),
        }
        line = line_format
        for key, value in values.items():
            line = line.replace("{" + key + "}", value)
        return line

    content = "\n".join(render_line(account) for account in rows)
    return {
        "content": content,
        "count": len(rows),
        "missing": missing,
        "filename": "accounts-credentials.txt",
        "format": line_format,
    }


@app.post("/api/accounts/delete-batch")
def delete_accounts_batch(params: DeleteBatchParams):
    """
    批量删除本地管理账号。整批共享一个 chatgpt_api + mail_client,
    Team 成员/邀请状态只拉一次,CPA 在整批结束后同步一次,避免重复开销。
    """
    from autoteam.account_ops import delete_managed_account, fetch_team_state
    from autoteam.accounts import load_accounts
    from autoteam.chatgpt_api import ChatGPTTeamAPI
    from autoteam.mail import TemporaryEmailClient
    from autoteam.cpa_sync import sync_to_cpa
    from autoteam.admin_state import get_admin_session_token, get_chatgpt_account_id

    raw_emails = [(e or "").strip() for e in (params.emails or [])]
    emails = [e for e in raw_emails if e]
    if not emails:
        raise HTTPException(status_code=400, detail="emails 不能为空")

    # 去重,保留首次出现顺序
    seen = set()
    dedup = []
    for e in emails:
        low = e.lower()
        if low in seen:
            continue
        seen.add(low)
        dedup.append(e)
    emails = dedup

    main_emails = [e for e in emails if _is_main_account_email(e)]
    if main_emails:
        raise HTTPException(status_code=400, detail=f"主号不允许删除: {main_emails}")

    if not _playwright_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=_current_busy_detail("有任务正在执行，请等待完成后再批量删除"))

    def _run():
        accounts = load_accounts()
        existing = {(a.get("email") or "").lower(): a for a in accounts}
        remote_cleanup = bool(get_admin_session_token() and get_chatgpt_account_id())

        chatgpt_api = None
        mail_client = None
        results = []
        try:
            if remote_cleanup:
                chatgpt_api = ChatGPTTeamAPI()
                chatgpt_api.start()
            mail_client = TemporaryEmailClient()
            mail_client.login()
            # 整批共享一次 Team 状态快照,避免每个删除都重查一次
            remote_state = fetch_team_state(chatgpt_api) if remote_cleanup else None

            for email in emails:
                if email.lower() not in existing:
                    results.append({"email": email, "ok": False, "error": "账号不存在"})
                    if not params.continue_on_error:
                        break
                    continue
                try:
                    cleanup = delete_managed_account(
                        email,
                        remove_remote=remote_cleanup,
                        chatgpt_api=chatgpt_api,
                        mail_client=mail_client,
                        remote_state=remote_state,
                        sync_cpa_after=False,  # 整批结束后统一同步
                    )
                    results.append({"email": email, "ok": True, "cleanup": cleanup})
                except Exception as exc:
                    logger.error("[批量删除] %s 失败: %s", email, exc)
                    results.append({"email": email, "ok": False, "error": str(exc)})
                    if not params.continue_on_error:
                        break
        finally:
            if chatgpt_api:
                try:
                    chatgpt_api.stop()
                except Exception as exc:
                    logger.debug("[批量删除] 关闭 chatgpt_api 异常: %s", exc)
            try:
                sync_to_cpa()
            except Exception as exc:
                logger.warning("[批量删除] 结尾 sync_to_cpa 失败: %s", exc)

        ok_count = sum(1 for r in results if r["ok"])
        return {
            "results": results,
            "summary": {
                "total": len(emails),
                "ok": ok_count,
                "failed": len(results) - ok_count,
                "skipped": len(emails) - len(results),
                "remote_cleanup": remote_cleanup,
            },
        }

    try:
        # 每个账号平均 30s (拉取 team 状态 + kick + delete cloudmail),再给 120s 兜底余量。
        # 若仍超时会抛 TimeoutError,worker 线程会在后台继续跑完,但锁会释放 → 用户可以再提。
        timeout = max(300, 30 * len(emails) + 120)
        return _pw_executor.run_with_timeout(timeout, _run)
    finally:
        _playwright_lock.release()


@app.post("/api/accounts/{email}/kick")
def post_kick_account(email: str):
    """将账号从 Team 中移出，状态变为 standby"""
    if not _playwright_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=_current_busy_detail("有任务正在执行，请等待完成后再操作"))

    try:
        from autoteam.accounts import find_account, load_accounts, update_account
        from autoteam.manager import remove_from_team

        email = email.strip().lower()
        if _is_main_account_email(email):
            raise HTTPException(status_code=400, detail="主号不允许移出 Team")
        accounts = load_accounts()
        acc = find_account(accounts, email)
        if not acc:
            raise HTTPException(status_code=404, detail="账号不存在")
        if acc["status"] != "active":
            raise HTTPException(status_code=400, detail=f"账号状态为 {acc['status']}，不是 active")

        def _do_kick():
            from autoteam.chatgpt_api import ChatGPTTeamAPI

            chatgpt = ChatGPTTeamAPI()
            chatgpt.start()
            try:
                return remove_from_team(chatgpt, email)
            finally:
                chatgpt.stop()

        ok = _pw_executor.run(_do_kick)
        if ok:
            update_account(email, status="standby")
            return {"message": f"已将 {email} 移出 Team", "email": email, "status": "standby"}
        raise HTTPException(status_code=500, detail=f"移出 {email} 失败")
    finally:
        _playwright_lock.release()


class LoginAccountParams(BaseModel):
    email: str


@app.post("/api/accounts/login", status_code=202)
def post_account_login(params: LoginAccountParams):
    """触发单个账号的 Codex 登录（后台执行）"""
    from autoteam.accounts import find_account, load_accounts

    email = params.email.strip().lower()
    if _is_main_account_email(email):
        raise HTTPException(status_code=400, detail="主号不属于账号池登录对象")
    accounts = load_accounts()
    acc = find_account(accounts, email)
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")

    def _run():
        from autoteam.accounts import ACCOUNT_TYPE_FREE, ACCOUNT_TYPE_TEAM, STATUS_ACTIVE, STATUS_PERSONAL, update_account
        from autoteam.mail import TemporaryEmailClient
        from autoteam.codex_auth import (
            check_codex_quota,
            login_codex_via_browser,
            quota_result_quota_info,
            quota_result_resets_at,
            save_auth_file,
        )

        # 账号类型决定登录模式：Free 走个人号 OAuth；Team 走 Team workspace OAuth。
        use_personal = acc.get("status") == STATUS_PERSONAL or (acc.get("account_type") or "").lower() == ACCOUNT_TYPE_FREE

        mail_client = TemporaryEmailClient()
        mail_client.login()
        bundle = login_codex_via_browser(
            email,
            acc.get("password", ""),
            mail_client=mail_client,
            use_personal=use_personal,
        )
        if bundle:
            auth_file = save_auth_file(bundle)
            update_account(email, auth_file=auth_file, last_active_at=time.time())
            plan_type = (bundle.get("plan_type") or "").lower()

            if use_personal:
                update_account(email, status=STATUS_ACTIVE, account_type=ACCOUNT_TYPE_FREE)
            elif plan_type == "team":
                update_account(email, status=STATUS_ACTIVE, account_type=ACCOUNT_TYPE_TEAM)
                token = bundle.get("access_token")
                if token:
                    st, info = check_codex_quota(token)
                    if st == "ok" and isinstance(info, dict):
                        update_account(email, last_quota=info)
                    elif st == "exhausted":
                        quota_info = quota_result_quota_info(info)
                        if quota_info:
                            update_account(email, last_quota=quota_info)
                        update_account(
                            email,
                            status="exhausted",
                            quota_exhausted_at=time.time(),
                            quota_resets_at=quota_result_resets_at(info) or int(time.time() + 18000),
                        )
            # 同步到 CPA
            from autoteam.cpa_sync import sync_to_cpa

            sync_to_cpa()
            return {
                "email": email,
                "plan": bundle.get("plan_type"),
                "auth_file": auth_file,
                "mode": "personal" if use_personal else "team",
            }
        raise RuntimeError(f"Codex 登录失败: {email}")

    task = _start_task(f"login:{email}", _run, {"email": email})
    return task


@app.get("/api/status")
def get_status():
    """获取所有账号状态 + active 账号实时额度"""
    from autoteam.accounts import (
        STATUS_ACTIVE,
        STATUS_AUTH_INVALID,
        STATUS_EXHAUSTED,
        STATUS_ORPHAN,
        STATUS_PENDING,
        STATUS_PERSONAL,
        STATUS_STANDBY,
        load_accounts,
    )
    from autoteam.codex_auth import check_codex_quota, quota_result_quota_info

    accounts = load_accounts()
    quota_cache = {}

    for acc in accounts:
        if acc["status"] not in (STATUS_ACTIVE, STATUS_PERSONAL) and not _is_main_account_email(acc.get("email")):
            continue

        auth_file = _resolve_status_auth_file(acc)
        if not auth_file:
            continue

        try:
            auth_data = json.loads(read_text(Path(auth_file)))
            access_token = auth_data.get("access_token")
            if access_token:
                status, info = check_codex_quota(access_token)
                if status == "ok" and isinstance(info, dict):
                    quota_cache[acc["email"]] = info
                elif status == "exhausted":
                    quota_info = quota_result_quota_info(info)
                    if quota_info:
                        quota_cache[acc["email"]] = quota_info
        except Exception:
            pass

    sanitized_accounts = [_sanitize_account(a, quota_cache.get(a.get("email"))) for a in accounts]

    summary = {
        "active": sum(1 for a in sanitized_accounts if a["status"] == STATUS_ACTIVE),
        "standby": sum(1 for a in sanitized_accounts if a["status"] == STATUS_STANDBY),
        "exhausted": sum(1 for a in sanitized_accounts if a["status"] == STATUS_EXHAUSTED),
        "pending": sum(1 for a in sanitized_accounts if a["status"] == STATUS_PENDING),
        "auth_invalid": sum(1 for a in sanitized_accounts if a["status"] == STATUS_AUTH_INVALID),
        "orphan": sum(1 for a in sanitized_accounts if a["status"] == STATUS_ORPHAN),
        "free": sum(1 for a in sanitized_accounts if a.get("account_type") == "free"),
        "team": sum(1 for a in sanitized_accounts if a.get("account_type") == "team"),
        "plus": sum(1 for a in sanitized_accounts if a.get("account_type") == "plus"),
        "pro": sum(1 for a in sanitized_accounts if a.get("account_type") == "pro"),
        "total": len(sanitized_accounts),
    }

    return {
        "accounts": sanitized_accounts,
        "summary": summary,
        "quota_cache": quota_cache,
    }


@app.post("/api/sync")
def post_sync():
    """同步认证文件到 CPA"""
    from autoteam.cpa_sync import sync_to_cpa

    sync_to_cpa()
    return {"message": "同步完成"}


@app.post("/api/sync/from-cpa")
def post_sync_from_cpa():
    """从 CPA 反向同步认证文件到本地。"""
    from autoteam.cpa_sync import sync_from_cpa

    result = sync_from_cpa()
    return {"message": "已从 CPA 同步到本地", "result": result}


@app.get("/api/register-failures")
def get_register_failures_api(limit: int = 50):
    """返回最近的注册/OAuth 失败明细，前端用来展示"为什么账号没生产出来"。"""
    from autoteam.register_failures import count_by_category, list_failures

    return {
        "items": list_failures(limit=max(1, min(limit, 500))),
        "counts": count_by_category(),
    }


@app.get("/api/config/register-domain")
def get_register_domain_api():
    """读取当前子号注册使用的临时邮箱域名。"""
    from autoteam.config import CLOUD_MAIL_DOMAIN, CLOUDFLARE_TEMP_EMAIL_DOMAIN
    from autoteam.runtime_config import get, get_register_domain, get_register_domains

    override = (get("register_domain") or "").strip()
    return {
        "domain": get_register_domain(),
        "domains": get_register_domains(),
        "override": override,
        "env_default": (CLOUD_MAIL_DOMAIN or CLOUDFLARE_TEMP_EMAIL_DOMAIN or "").lstrip("@").strip(),
    }


@app.put("/api/config/register-domain")
def put_register_domain_api(params: RegisterDomainParams):
    """
    更新子号注册域名。verify=True（默认）会试探性调用临时邮箱服务 new_address 验证服务端是否接受此域，
    成功则立即删除探测地址再保存；失败把原始错误透传给前端。
    """
    from autoteam.mail import TemporaryEmailClient
    from autoteam.runtime_config import set_register_domain

    cleaned = (params.domain or "").strip().lstrip("@").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="域名不能为空")

    leaked_probe = None
    if params.verify:
        probe_prefix = f"probe{int(time.time())}"
        acct_id = None
        probe_email = None
        try:
            client = TemporaryEmailClient()
            client.login()
            acct_id, probe_email = client.create_temp_email(prefix=probe_prefix, domain=cleaned)
        except Exception as exc:
            # 临时邮箱服务返回 "Invalid domain" 等错误直接透传
            raise HTTPException(status_code=400, detail=f"域名验证失败: {exc}") from exc
        # 探测地址用完立即回收;删除失败也要让前端看到,否则临时邮箱服务会积压僵尸地址
        try:
            if acct_id is not None:
                client.delete_account(acct_id)
        except Exception as exc:
            logger.warning("[config] 删除域名探测邮箱失败 (%s, id=%s): %s", probe_email, acct_id, exc)
            leaked_probe = {"email": probe_email, "acct_id": acct_id, "error": str(exc)}

    set_register_domain(cleaned)
    logger.info("[config] register_domain 已切换为 @%s", cleaned)
    resp = {"message": f"注册域名已切换为 @{cleaned}", "domain": cleaned}
    if leaked_probe:
        resp["warning"] = (
            f"域名已保存,但探测邮箱 {leaked_probe['email']} 回收失败,请手动在临时邮箱服务中删除"
            f" (id={leaked_probe['acct_id']}): {leaked_probe['error']}"
        )
        resp["leaked_probe"] = leaked_probe
    return resp


@app.put("/api/config/register-domains")
def put_register_domains_api(params: RegisterDomainsParams):
    """保存手动注册可选域名列表，并可同步切换当前默认域名。"""
    from autoteam.runtime_config import set_register_domain, set_register_domains

    cleaned = []
    seen = set()
    for domain in params.domains or []:
        value = (domain or "").strip().lstrip("@").strip()
        if not value:
            continue
        lowered = value.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        cleaned.append(value)

    if not cleaned:
        raise HTTPException(status_code=400, detail="domains 不能为空")

    selected = (params.selected or "").strip().lstrip("@").strip()
    if selected and selected not in cleaned:
        raise HTTPException(status_code=400, detail="selected 必须在 domains 列表中")

    saved = set_register_domains(cleaned)
    active = set_register_domain(selected or saved[0])
    return {
        "message": f"已保存 {len(saved)} 个注册域名",
        "domains": saved,
        "selected": active,
    }


@app.post("/api/sync/accounts")
def post_sync_accounts():
    """从 auths 目录和 Team 成员同步账号到 accounts.json"""
    from autoteam.manager import sync_account_states

    if not _playwright_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=_current_busy_detail("有任务正在执行，请等待完成后再同步"))

    try:
        _pw_executor.run(sync_account_states)
    finally:
        _playwright_lock.release()

    from autoteam.accounts import load_accounts

    accounts = load_accounts()
    return {"message": f"同步完成，共 {len(accounts)} 个账号", "total": len(accounts)}


@app.get("/api/team/members")
def get_team_members():
    """获取 Team 全部成员（包括手动添加的外部成员）"""
    from autoteam.admin_state import get_admin_session_token, get_chatgpt_account_id

    if not get_admin_session_token() or not get_chatgpt_account_id():
        raise HTTPException(status_code=400, detail="请先完成管理员登录")

    if not _playwright_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=_current_busy_detail("有任务正在执行，请等待完成后再查询"))

    try:

        def _fetch_team_members():
            from autoteam.account_ops import fetch_team_state
            from autoteam.accounts import load_accounts
            from autoteam.chatgpt_api import ChatGPTTeamAPI

            chatgpt = ChatGPTTeamAPI()
            chatgpt.start()
            try:
                members, invites = fetch_team_state(chatgpt)
                local_emails = {a["email"].lower() for a in load_accounts()}

                result = []
                for m in members:
                    email = (m.get("email") or "").lower()
                    result.append(
                        {
                            "email": m.get("email", ""),
                            "role": m.get("role", ""),
                            "user_id": m.get("user_id") or m.get("id", ""),
                            "is_local": email in local_emails,
                            "type": "member",
                        }
                    )
                for inv in invites:
                    email = (inv.get("email_address") or inv.get("email") or "").lower()
                    result.append(
                        {
                            "email": email,
                            "role": inv.get("role", ""),
                            "user_id": inv.get("id", ""),
                            "is_local": email in local_emails,
                            "type": "invite",
                        }
                    )
                return {"members": result, "total": len(members), "invites": len(invites)}
            finally:
                chatgpt.stop()

        return _pw_executor.run(_fetch_team_members)
    finally:
        _playwright_lock.release()


@app.post("/api/team/members/remove")
def post_team_members_remove(params: TeamMemberRemoveParams):
    """移出 Team 成员或取消邀请。"""
    from autoteam.admin_state import get_admin_session_token, get_chatgpt_account_id

    if not get_admin_session_token() or not get_chatgpt_account_id():
        raise HTTPException(status_code=400, detail="请先完成管理员登录")

    if not _playwright_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=_current_busy_detail("有任务正在执行，请等待完成后再操作"))

    try:
        from autoteam.accounts import find_account, load_accounts, update_account

        email = params.email.strip().lower()
        user_id = params.user_id.strip()
        member_type = params.type.strip().lower()

        if not email or not user_id:
            raise HTTPException(status_code=400, detail="缺少必要参数")
        if _is_main_account_email(email):
            raise HTTPException(status_code=400, detail="主号不允许从 Team 成员页移出")
        if member_type not in ("member", "invite"):
            raise HTTPException(status_code=400, detail="无效的成员类型")

        account_id = get_chatgpt_account_id()

        def _do_remove_team_member():
            from autoteam.chatgpt_api import ChatGPTTeamAPI

            chatgpt = ChatGPTTeamAPI()
            chatgpt.start()
            try:
                if member_type == "invite":
                    path = f"/backend-api/accounts/{account_id}/invites/{user_id}"
                    action_text = "取消邀请"
                else:
                    path = f"/backend-api/accounts/{account_id}/users/{user_id}"
                    action_text = "移出 Team"

                result = chatgpt._api_fetch("DELETE", path)
                return result, action_text
            finally:
                chatgpt.stop()

        result, action_text = _pw_executor.run(_do_remove_team_member)
        if result["status"] not in (200, 204):
            raise HTTPException(status_code=500, detail=f"{action_text}失败: HTTP {result['status']}")

        accounts = load_accounts()
        acc = find_account(accounts, email)
        if acc:
            update_account(email, status="standby")

        return {
            "message": f"已{action_text}: {email}",
            "email": email,
            "type": member_type,
        }
    finally:
        _playwright_lock.release()


@app.post("/api/bind/link")
def post_bind_link(params: BindLinkParams):
    """生成 ChatGPT 绑卡链接"""
    def _normalize_access_token(raw_value: str) -> str:
        raw = str(raw_value or "").strip()
        if not raw:
            return ""
        if raw.startswith("{") and "accessToken" in raw:
            try:
                parsed = json.loads(raw)
                token = parsed.get("accessToken")
                if token:
                    raw = str(token).strip()
            except Exception:
                pass
        raw = re.sub(r"^Bearer\s+", "", raw, flags=re.IGNORECASE).strip()
        raw = re.sub(r"^[\"']+|[\"',;\\s]+$", "", raw).strip()
        return raw

    access_token = _normalize_access_token(params.access_token)
    if not access_token:
        raise HTTPException(status_code=400, detail="请提供 access_token")

    def _do_generate_link():
        from autoteam.chatgpt_api import ChatGPTTeamAPI

        def _friendly_goto_error(exc):
            text = str(exc)
            if "ERR_CONNECTION_CLOSED" in text:
                return "打开 ChatGPT 首页失败：网络连接被关闭，可能是代理/IP/风控问题"
            if "ERR_TIMED_OUT" in text or "Timeout" in text:
                return "打开 ChatGPT 首页失败：请求超时，可能是网络波动、代理不稳定或风控问题"
            if "ERR_CONNECTION_RESET" in text:
                return "打开 ChatGPT 首页失败：网络连接被重置，可能是代理/IP/风控问题"
            return f"打开 ChatGPT 首页失败：{text}"

        payload = {
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

        api = ChatGPTTeamAPI()
        try:
            api._launch_browser()
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
            api.access_token = access_token

            result = api.page.evaluate(
                """async (payload) => {
                    try {
                        try {
                            await fetch("/api/auth/session", { credentials: "include" });
                        } catch (_) {}

                        const resp = await fetch("https://chatgpt.com/backend-api/payments/checkout", {
                            method: "POST",
                            credentials: "include",
                            headers: {
                                "Content-Type": "application/json",
                                "Authorization": `Bearer ${payload.access_token}`
                            },
                            body: JSON.stringify(payload.body)
                        });

                        const text = await resp.text();
                        let data = null;
                        try {
                            data = text ? JSON.parse(text) : {};
                        } catch (err) {
                            return {
                                ok: false,
                                status: resp.status,
                                non_json: true,
                                body: text.slice(0, 500)
                            };
                        }

                        return {
                            ok: resp.ok,
                            status: resp.status,
                            data
                        };
                    } catch (err) {
                        return {
                            ok: false,
                            status: 0,
                            fetch_error: String(err && err.message ? err.message : err)
                        };
                    }
                }""",
                {"access_token": access_token, "body": payload},
            )

            if result.get("fetch_error"):
                raise HTTPException(status_code=502, detail=f"页面请求失败: {result['fetch_error']}")

            if result.get("non_json"):
                raise HTTPException(
                    status_code=result.get("status") or 502,
                    detail=f"上游错误({result.get('status')})，返回非 JSON 响应: {(result.get('body') or '')[:200]}",
                )

            data = result.get("data") or {}
            if not result.get("ok"):
                detail = data.get("detail") if isinstance(data, dict) else None
                if isinstance(detail, dict):
                    detail = detail.get("message") or json.dumps(detail, ensure_ascii=False)
                raise HTTPException(
                    status_code=result.get("status") or 502,
                    detail=detail or f"上游错误({result.get('status')})",
                )

            if data.get("url") or data.get("checkout_session_id"):
                result_payload = {}
                if data.get("url"):
                    result_payload["url"] = data["url"]
                if data.get("checkout_session_id"):
                    result_payload["checkout_session_id"] = data["checkout_session_id"]
                return result_payload
            return {"detail": data.get("detail") or str(data)}
        finally:
            try:
                api.stop()
            except Exception:
                pass

    if not _playwright_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=_current_busy_detail("有任务正在执行"))

    try:
        try:
            result = _pw_executor.run(_do_generate_link)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("[bind/link] unexpected error")
            raise HTTPException(status_code=500, detail=f"生成绑卡链接失败: {exc}") from exc
        if "detail" in result:
            raise HTTPException(status_code=400, detail=result["detail"])
        return result
    finally:
        _playwright_lock.release()


# ---------------------------------------------------------------------------
# 卡池
# ---------------------------------------------------------------------------


@app.get("/api/card-pool/{pool_type}")
def get_card_pool(pool_type: str):
    from autoteam.card_pool import list_items, stats_for

    try:
        return {
            "pool_type": pool_type,
            "stats": stats_for(pool_type),
            "items": list_items(pool_type),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/card-pool/import")
def post_card_pool_import(params: CardPoolImportParams):
    from autoteam.card_pool import import_text_lines, stats_for

    try:
        items = import_text_lines(params.pool_type, params.text, provider=params.provider)
        return {
            "message": f"导入成功，新增 {len(items)} 条",
            "imported": items,
            "stats": stats_for(params.pool_type),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/card-pool/delete")
def post_card_pool_delete(params: CardPoolDeleteParams):
    from autoteam.card_pool import delete_items, stats_for

    try:
        deleted = delete_items(params.pool_type, params.ids)
        return {
            "message": f"已删除 {deleted} 条记录",
            "deleted": deleted,
            "stats": stats_for(params.pool_type),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/card-pool/update")
def post_card_pool_update(params: CardPoolUpdateParams):
    from autoteam.card_pool import stats_for, update_item

    try:
        item = update_item(
            params.pool_type,
            params.item_id,
            status=params.status,
            provider=params.provider,
            used_by=params.used_by,
            expires_at=params.expires_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not item:
        raise HTTPException(status_code=404, detail="记录不存在")

    return {
        "message": "更新成功",
        "item": item,
        "stats": stats_for(params.pool_type),
    }


@app.post("/api/card-pool/redeem")
def post_card_pool_redeem(params: CardPoolRedeemParams):
    from autoteam.card_pool import add_card_item, find_item, stats_for, update_item

    redeem_item = find_item("redeem", params.item_id)
    if not redeem_item:
        raise HTTPException(status_code=404, detail="兑换码不存在")

    code = str(redeem_item.get("value") or "").strip()
    provider = str(redeem_item.get("provider") or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="兑换码为空")
    if redeem_item.get("status") == "used":
        raise HTTPException(status_code=400, detail="该兑换码已使用")

    if provider not in {"988", "EFUN"}:
        raise HTTPException(status_code=400, detail="暂不支持该供应商兑换")

    if provider == "EFUN":
        url = "https://card.efuncard.com/api/external/redeem"
        headers = {
            "Authorization": "Bearer b352d13f20462ed46cff0aa417065496bd811eb8396b2e2fee11aeacb796fc00",
            "Content-Type": "application/json",
        }
        resp = requests.post(url, json={"code": code}, headers=headers, timeout=30, verify=False)
        try:
            data = resp.json()
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=f"EFUN 返回了非 JSON 响应: {(resp.text or '')[:200]}") from exc
        if not resp.ok or not data.get("success"):
            raise HTTPException(status_code=resp.status_code or 502, detail=data.get("message") or f"EFUN 兑换失败({resp.status_code})")
        card = data.get("data") or {}
        card_number = str(card.get("cardNumber") or "").strip()
        if not card_number:
            raise HTTPException(status_code=502, detail="EFUN 返回缺少卡券信息")
        card_item = add_card_item(
            value=card_number,
            provider=provider,
            status="unused",
            expires_at=str(card.get("autoCancelAt") or ""),
            meta=card,
        )
        update_item("redeem", params.item_id, status="used")
        return {
            "message": "兑换成功",
            "redeem_item": find_item("redeem", params.item_id),
            "card_item": card_item,
            "stats": {
                "redeem": stats_for("redeem"),
                "card": stats_for("card"),
            },
        }

    if provider == "988":
        url = "https://cards.779.chat/api/exchange/verify"
        resp = requests.post(url, json={"key": code}, timeout=30, verify=False)
        try:
            data = resp.json()
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=f"988 返回了非 JSON 响应: {(resp.text or '')[:200]}") from exc

        if not resp.ok or not data.get("success"):
            raise HTTPException(status_code=resp.status_code or 502, detail=data.get("message") or f"988 兑换失败({resp.status_code})")

        card_info = data.get("card") or {}
        content = data.get("content") or {}
        card_number = str(content.get("card_number") or content.get("cardNumber") or card_info.get("card_number") or card_info.get("cardNumber") or "").strip()
        if not card_number:
            raise HTTPException(status_code=502, detail="988 返回缺少卡券信息")

        expiry = card_info.get("expires_at") or content.get("expiry_date") or ""
        card_item = add_card_item(
            value=card_number,
            provider=provider,
            status="unused",
            expires_at=str(expiry or ""),
            meta=data,
        )
        update_item("redeem", params.item_id, status="used")
        return {
            "message": "兑换成功",
            "redeem_item": find_item("redeem", params.item_id),
            "card_item": card_item,
            "stats": {
                "redeem": stats_for("redeem"),
                "card": stats_for("card"),
            },
        }

    raise HTTPException(status_code=501, detail="暂不支持该供应商兑换")


@app.post("/api/card-pool/redeem-batch")
def post_card_pool_redeem_batch(params: CardPoolRedeemBatchParams):
    results = []
    for item_id in params.item_ids:
        try:
            result = post_card_pool_redeem(CardPoolRedeemParams(item_id=item_id))
            results.append({"item_id": item_id, "ok": True, "result": result})
        except HTTPException as exc:
            results.append({"item_id": item_id, "ok": False, "error": exc.detail, "status_code": exc.status_code})
        except Exception as exc:
            results.append({"item_id": item_id, "ok": False, "error": str(exc), "status_code": 500})

    ok_count = sum(1 for item in results if item["ok"])
    return {
        "message": f"批量兑换完成，成功 {ok_count}/{len(results)}",
        "results": results,
    }


@app.post("/api/card-pool/fetch-sms")
def post_card_pool_fetch_sms(params: CardPoolFetchSmsParams):
    sms_url = (params.url or "").strip()
    if not sms_url:
        raise HTTPException(status_code=400, detail="接码 API 为空")
    if not (sms_url.startswith("http://") or sms_url.startswith("https://")):
        raise HTTPException(status_code=400, detail="接码 API 格式无效")

    try:
        resp = requests.get(
            sms_url,
            timeout=20,
            verify=False,
            headers={
                "User-Agent": "Mozilla/5.0 AutoTeam/1.0",
                "Accept": "text/plain, text/html, */*",
            },
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"请求接码接口失败: {exc}") from exc

    text = (resp.text or "").strip()
    if not resp.ok:
        raise HTTPException(status_code=resp.status_code or 502, detail=text[:200] or f"接码接口返回异常({resp.status_code})")

    return {
        "url": sms_url,
        "status_code": resp.status_code,
        "text": text,
    }


# ---------------------------------------------------------------------------
# 日志收集
# ---------------------------------------------------------------------------

_log_buffer: list[dict] = []
_LOG_BUFFER_MAX = 500


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


@app.get("/api/logs")
def get_logs(limit: int = 100, since: float = 0):
    """获取最近的日志"""
    if since > 0:
        entries = [e for e in _log_buffer if e["time"] > since]
    else:
        entries = _log_buffer[-limit:]
    return {"logs": entries, "total": len(_log_buffer)}


@app.post("/api/sync/main-codex")
def post_sync_main_codex():
    """兼容旧接口：开始主号 Codex 登录并同步到 CPA。"""
    return post_main_codex_start()


@app.get("/api/cpa/files")
def get_cpa_files():
    """获取 CPA 中的认证文件列表"""
    from autoteam.cpa_sync import list_cpa_files

    return list_cpa_files()


# ---------------------------------------------------------------------------
# 后台任务端点
# ---------------------------------------------------------------------------


class CheckParams(BaseModel):
    include_standby: bool = False  # True 时额外探测 standby 池(限速+24h 去重)


@app.post("/api/tasks/bind-card", status_code=202)
def post_bind_card_task(params: BindCardTaskParams):
    from autoteam import cancel_signal
    from autoteam.accounts import find_account, load_accounts, save_accounts, update_account
    from autoteam.auth_session_store import get_auth_session_file
    from autoteam.bind_audit import record_bind_audit
    from autoteam.bind_executor import run_bind_task
    from autoteam.card_pool import finalize_card_binding, find_item, reserve_card_item

    email = _normalized_email(params.email)
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
            account = _session_only_account_stub(email)
            accounts.append(account)
            save_accounts(accounts)
        else:
            raise HTTPException(status_code=404, detail="账号不存在")
    if not _resolve_status_auth_file(account):
        raise HTTPException(status_code=400, detail="该账号缺少可用 auth_session/auth_file")

    card_item = find_item("card", params.card_item_id)
    if not card_item:
        raise HTTPException(status_code=404, detail="卡记录不存在")
    if card_item.get("status") != "unused":
        raise HTTPException(status_code=400, detail=f"卡当前状态为 {card_item.get('status')}，不可用于绑卡")

    def _run():
        task_id = _current_task_id or ""
        started_at = time.time()
        reserved = False
        result = None
        final_card_item = None

        try:
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

            _update_current_task_progress(
                {
                    "stage": "binding",
                    "email": email,
                    "card_item_id": params.card_item_id,
                    "proxy_label": params.proxy_label,
                }
            )

            result = run_bind_task(
                checkout_url=checkout_url,
                card_item=reserved_item,
                proxy_url=params.proxy_url,
                proxy_bypass=params.proxy_bypass,
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
                reusable=_is_bind_card_reusable_result(result),
            )
            result["card_status"] = (final_card_item or {}).get("status", "")

        update_account(
            email,
            last_bind_status="cancelled" if task_status == "cancelled" else result.get("status") or "failed",
            last_bind_at=time.time(),
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

        _update_current_task_progress(
            {
                "stage": "completed",
                "bind_status": result.get("status") or "failed",
                "task_status": task_status,
                "card_status": result.get("card_status") or "",
            }
        )

        if result.get("status") != "success":
            raise TaskResultError(result.get("message") or "绑卡失败", task_result=result)
        return result

    task = _start_task("bind-card", _run, params.model_dump())
    return task


@app.post("/api/tasks/gopay-bind", status_code=202)
def post_gopay_bind_task(params: GoPayBindTaskParams):
    from autoteam import cancel_signal
    from autoteam.accounts import ACCOUNT_TYPE_PLUS, STATUS_ACTIVE, find_account, load_accounts, save_accounts, update_account
    from autoteam.auth_session_store import get_auth_session_file
    from autoteam.bind_audit import record_bind_audit
    from autoteam.config import normalize_proxy_url
    from autoteam.gopay_executor import (
        _compact_log_text,
        _safe_email_summary,
        _safe_phone_summary,
        _safe_proxy_summary,
        _safe_url_summary,
        run_gopay_bind_task,
    )

    email = _normalized_email(params.email)
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
    billing_name = str(params.billing_name or "").strip()
    billing_country = str(params.billing_country or "").strip()
    billing_state = str(params.billing_state or "").strip()
    billing_city = str(params.billing_city or "").strip()
    billing_zip = str(params.billing_zip or "").strip()
    billing_address1 = str(params.billing_address1 or "").strip()
    billing_address2 = str(params.billing_address2 or "").strip()
    checkout_url = str(params.checkout_url or "").strip()
    proxy_url = str(params.proxy_url or "").strip()
    try:
        normalized_proxy_url = normalize_proxy_url(proxy_url) if proxy_url else ""
        proxy_config_state = "enabled" if normalized_proxy_url else "disabled"
        proxy_config_error = ""
    except Exception as exc:
        normalized_proxy_url = ""
        proxy_config_state = "invalid"
        proxy_config_error = _compact_log_text(exc, limit=160)

    if not email:
        raise HTTPException(status_code=400, detail="email 不能为空")
    if checkout_url:
        account_emails = []
    elif account_emails and email not in account_emails:
        account_emails.insert(0, email)
    if not phone_number:
        raise HTTPException(status_code=400, detail="phone_number 不能为空")
    if not sms_url:
        raise HTTPException(status_code=400, detail="sms_url 不能为空")
    if not gopay_pin:
        raise HTTPException(status_code=400, detail="gopay_pin 不能为空")
    logger.info(
        "[gopay-bind] task submitted: email=%s account_count=%s checkout=%s phone=%s proxy_label=%s proxy_state=%s proxy=%s proxy_error=%s timeout=%s",
        _safe_email_summary(email),
        len(account_emails) if account_emails else 1,
        _safe_url_summary(checkout_url) if checkout_url else "<auto-generate>",
        _safe_phone_summary(phone_number, country_code),
        params.proxy_label or "<none>",
        proxy_config_state,
        _safe_proxy_summary(normalized_proxy_url or proxy_url),
        proxy_config_error or "<none>",
        max(120, int(params.timeout_seconds or 900)),
    )

    accounts = load_accounts()
    account = find_account(accounts, email)
    if not account:
        auth_session_file = get_auth_session_file(email)
        if auth_session_file and Path(auth_session_file).exists():
            account = _session_only_account_stub(email)
            accounts.append(account)
            save_accounts(accounts)
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
                candidate = _session_only_account_stub(candidate_email)
                accounts.append(candidate)
                save_accounts(accounts)
            else:
                raise HTTPException(status_code=404, detail=f"批量账号不存在: {candidate_email}")
        if not _resolve_status_auth_file(candidate):
            raise HTTPException(status_code=400, detail=f"批量账号缺少可用 auth_session/auth_file: {candidate_email}")

    skip_current_signal = threading.Event()

    def _run():
        task_id = _current_task_id or ""
        started_at = time.time()
        result = None

        try:
            logger.info(
                "[gopay-bind] runner started: task_id=%s email=%s account_count=%s checkout=%s proxy_label=%s proxy_state=%s proxy=%s",
                task_id[:8] or "<unknown>",
                _safe_email_summary(email),
                len(account_emails) if account_emails else 1,
                _safe_url_summary(checkout_url) if checkout_url else "<auto-generate>",
                params.proxy_label or "<none>",
                proxy_config_state,
                _safe_proxy_summary(normalized_proxy_url or proxy_url),
            )
            _update_current_task_progress(
                {
                    "stage": "gopay_binding",
                    "email": email,
                    "phone_number": phone_number,
                    "country_code": country_code,
                    "proxy_label": params.proxy_label,
                    "account_count": len(account_emails) if account_emails else 1,
                }
            )
            result = run_gopay_bind_task(
                email=email,
                checkout_url=checkout_url,
                phone_number=phone_number,
                country_code=country_code,
                sms_url=sms_url,
                gopay_pin=gopay_pin,
                billing_info={
                    "name": billing_name,
                    "country": billing_country,
                    "state": billing_state,
                    "city": billing_city,
                    "zip": billing_zip,
                    "address1": billing_address1,
                    "address2": billing_address2,
                },
                proxy_url=proxy_url,
                proxy_bypass=params.proxy_bypass,
                timeout_seconds=max(120, int(params.timeout_seconds or 900)),
                account_emails=account_emails,
                is_cancelled=cancel_signal.is_cancelled,
                skip_current=skip_current_signal.is_set,
                clear_skip_current=skip_current_signal.clear,
                progress_callback=_update_current_task_progress,
            )
        except Exception as exc:
            logger.exception("[gopay-bind] unexpected error")
            result = {
                "status": "failed",
                "failure_stage": "post_submit",
                "message": f"GoPay 任务执行异常: {exc}",
                "screenshot_paths": [],
            }

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
        result["proxy_label"] = params.proxy_label
        result["proxy_state"] = proxy_config_state
        result["checkout_url"] = checkout_url or result.get("checkout_url") or ""
        result["account_emails"] = account_emails

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
            "last_checkout_url": checkout_url or result.get("checkout_url") or "",
            "last_proxy_label": params.proxy_label,
            "last_bind_task_id": task_id,
            "last_bind_message": result.get("message") or "",
            "last_bind_failure_stage": result.get("failure_stage") or "",
        }
        if result.get("status") == "success":
            account_update["status"] = STATUS_ACTIVE
            account_update["account_type"] = ACCOUNT_TYPE_PLUS
            account_update["plus_bound_at"] = finished_at
        update_account(actual_email, **account_update)

        removed_pool_emails = []
        rejected_pool_emails = _gopay_rejected_pool_emails(result, actual_email)
        nonzero_blocked_pool_emails = _gopay_nonzero_blocked_pool_emails(result, actual_email)
        cleanup_pool_emails = []
        for cleanup_email in [*rejected_pool_emails, *nonzero_blocked_pool_emails]:
            if cleanup_email and cleanup_email not in cleanup_pool_emails:
                cleanup_pool_emails.append(cleanup_email)
        if params.delete_rejected_accounts:
            removed_pool_emails = _remove_gopay_rejected_accounts_from_pool(cleanup_pool_emails)
        elif cleanup_pool_emails:
            result["rejected_pool_emails"] = rejected_pool_emails
            result["nonzero_blocked_pool_emails"] = nonzero_blocked_pool_emails
            logger.info(
                "[gopay-bind] rejected/nonzero accounts kept in pool: task_id=%s rejected=%s nonzero=%s",
                task_id[:8] or "<unknown>",
                rejected_pool_emails,
                nonzero_blocked_pool_emails,
            )
        if removed_pool_emails:
            result["removed_pool_emails"] = removed_pool_emails
            logger.info(
                "[gopay-bind] removed rejected/nonzero accounts from pool and email service: task_id=%s emails=%s",
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
                "billing_info": result.get("billing_info") or {},
                "removed_pool_emails": result.get("removed_pool_emails") or [],
            }
        )

        _update_current_task_progress(
            {
                "stage": "completed" if result.get("status") == "success" else "failed",
                "status": result.get("status") or "failed",
                "failure_stage": result.get("failure_stage") or "",
                "message": result.get("message") or "",
            }
        )

        if result.get("status") != "success":
            raise TaskResultError(result.get("message") or "GoPay 任务失败", task_result=result)
        return result

    task = _start_task("gopay-bind", _run, params.model_dump())
    _task_skip_signals[task["task_id"]] = skip_current_signal
    return task


@app.post("/api/tasks/check", status_code=202)
def post_check(params: CheckParams = CheckParams()):
    """检查所有 active 账号额度（后台执行）。include_standby=True 时追加探测 standby 池。"""
    from autoteam.manager import cmd_check

    include_standby = bool(params.include_standby)

    def _run():
        exhausted = cmd_check(include_standby=include_standby)
        return {"exhausted": [a["email"] for a in exhausted]}

    task = _start_task("check", _run, {"include_standby": include_standby})
    return task


@app.post("/api/tasks/rotate", status_code=202)
def post_rotate(params: TaskParams = TaskParams()):
    """智能轮转（后台执行）"""
    from autoteam.manager import cmd_rotate

    task = _start_task("rotate", cmd_rotate, {"target": params.target}, params.target)
    return task


class ReplaceParams(BaseModel):
    email: str
    reason: str = "manual"


@app.post("/api/tasks/replace", status_code=202)
def post_replace(params: ReplaceParams):
    """定点替换一个 Team 子号:kick + 补一个(标准行为:优先 standby 复用,否则新号)。

    失效一个立即轮换一个的手动触发入口,也可由 auto-check 自动调用 cmd_replace_batch。
    """
    from autoteam.manager import cmd_replace_one

    email = (params.email or "").strip()
    if not email:
        raise HTTPException(status_code=400, detail="email 不能为空")
    task = _start_task(
        "replace",
        cmd_replace_one,
        {"email": email, "reason": params.reason},
        email,
        params.reason,
    )
    return task


@app.post("/api/tasks/add", status_code=202)
def post_add(params: ManualRegisterParams = ManualRegisterParams()):
    """注册账号（后台执行，注册成功后继续执行 personal OAuth 并生成 auth_file）"""
    from autoteam.manager import cmd_register_accounts
    from autoteam.identity import random_password
    from autoteam.runtime_config import get_register_domain, get_register_domains

    prefix = (params.prefix or "").strip() or None
    password = (params.password or "").strip() or None
    resolved_password = password or random_password()
    mode = (params.mode or "single").strip().lower()
    count = max(1, int(params.count or 1))
    concurrency = max(1, min(20, int(params.concurrency or 1)))
    interval_seconds = max(0.0, float(params.interval_seconds or 0.0))
    jitter_min_seconds = max(0.0, float(params.jitter_min_seconds or 0.0))
    jitter_max_seconds = max(0.0, float(params.jitter_max_seconds or 0.0))
    if mode not in ("single", "batch"):
        raise HTTPException(status_code=400, detail="mode 只支持 single 或 batch")

    configured_domains = get_register_domains()

    def _clean_domain(value) -> str:
        return str(value or "").strip().lstrip("@").strip()

    def _validate_domain(value: str):
        if configured_domains and value not in configured_domains:
            raise HTTPException(status_code=400, detail=f"域名 @{value} 不在可选列表中")

    selected_domain = _clean_domain(params.domain)
    selected_domains = []
    if mode == "batch":
        seen = set()
        for raw_domain in params.domains or []:
            value = _clean_domain(raw_domain)
            if not value or value in seen:
                continue
            _validate_domain(value)
            seen.add(value)
            selected_domains.append(value)

    if not selected_domains:
        if selected_domain:
            _validate_domain(selected_domain)
        else:
            selected_domain = get_register_domain()
        if selected_domain:
            selected_domains = [selected_domain]

    if not selected_domains:
        raise HTTPException(status_code=400, detail="未配置可用注册域名")

    selected_domain = selected_domains[0]

    if mode == "single":
        count = 1
        concurrency = 1
        jitter_min_seconds = 0.0
        jitter_max_seconds = 0.0
        selected_domains = [selected_domain]
    if jitter_min_seconds > jitter_max_seconds:
        raise HTTPException(status_code=400, detail="随机抖动区间必须满足 min <= max")

    task = _start_task(
        "register",
        cmd_register_accounts,
        {
            "mode": mode,
            "count": count,
            "concurrency": concurrency,
            "interval_seconds": interval_seconds,
            "jitter_min_seconds": jitter_min_seconds,
            "jitter_max_seconds": jitter_max_seconds,
            "domain": selected_domain,
            "domains": selected_domains,
            "prefix": prefix or "",
            "password_mode": "provided" if password else "random",
        },
        count=count,
        concurrency=concurrency,
        interval_seconds=interval_seconds,
        jitter_min_seconds=jitter_min_seconds,
        jitter_max_seconds=jitter_max_seconds,
        email_prefix=prefix,
        password=resolved_password,
        domain=selected_domain,
        domains=selected_domains,
        progress_callback=_update_current_task_progress,
    )
    return task


@app.post("/api/tasks/fill", status_code=202)
def post_fill(params: TaskParams = TaskParams()):
    """补满 Team 成员（后台执行）。leave_workspace=True 时切换为"生产免费号"模式

    fill-personal 模式下额外做一次轻量预检:Team 子号已满 TEAM_SUB_ACCOUNT_HARD_CAP
    则直接返回 409,不启动后台任务(队列化拒绝,Solution C)。本地状态足够用,无需启动
    Playwright 远程查询,避免给前端按错按钮带来额外开销。
    """
    from autoteam.manager import TEAM_SUB_ACCOUNT_HARD_CAP, cmd_fill

    if params.leave_workspace:
        from autoteam.accounts import STATUS_ACTIVE, STATUS_EXHAUSTED, list_accounts

        in_team_local = sum(1 for a in list_accounts() if a.get("status") in (STATUS_ACTIVE, STATUS_EXHAUSTED))
        if in_team_local >= TEAM_SUB_ACCOUNT_HARD_CAP:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Team 子号已满 {in_team_local}/{TEAM_SUB_ACCOUNT_HARD_CAP},"
                    "fill-personal 拒绝执行。请先等子号自然 exhausted 或手动腾位置后再试"
                ),
            )

    command = "fill-personal" if params.leave_workspace else "fill"
    task = _start_task(
        command,
        cmd_fill,
        {"target": params.target, "leave_workspace": params.leave_workspace},
        params.target,
        leave_workspace=params.leave_workspace,
    )
    return task


@app.post("/api/tasks/cleanup", status_code=202)
def post_cleanup(params: CleanupParams = CleanupParams()):
    """清理多余成员（后台执行）"""
    from autoteam.manager import cmd_cleanup

    task = _start_task("cleanup", cmd_cleanup, {"max_seats": params.max_seats}, params.max_seats)
    return task


@app.get("/api/tasks")
def get_tasks():
    """查看所有任务"""
    sorted_tasks = sorted(_tasks.values(), key=lambda t: t["created_at"], reverse=True)
    return sorted_tasks


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str):
    """查看任务状态"""
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@app.post("/api/tasks/cancel", status_code=202)
def post_task_cancel():
    """
    请求当前正在运行的任务在下一个安全点退出。
    协作式:后台 worker 在每个批次/账号边界检查 cancel_signal.is_cancelled(),
    调用这里后等 10-30s 让当前步骤跑完,任务状态会在 task["status"] 里显示为 "cancelled"。
    """
    from autoteam import cancel_signal

    if not _current_task_id:
        raise HTTPException(status_code=404, detail="当前没有正在运行的任务")
    task = _tasks.get(_current_task_id) or {}
    if task.get("status") not in ("running", "pending"):
        raise HTTPException(status_code=400, detail=f"任务当前状态 {task.get('status')} 无法取消")
    cancel_signal.request_cancel(f"手动停止 task={_current_task_id[:8]}")
    task["cancel_requested"] = True
    return {
        "message": "已请求中止,等待当前步骤安全退出",
        "task_id": _current_task_id,
        "command": task.get("command"),
    }


@app.post("/api/tasks/skip-current", status_code=202)
def post_task_skip_current():
    """请求 GoPay 批量任务跳过当前账号，并在安全点切换到下一个账号。"""
    if not _current_task_id:
        raise HTTPException(status_code=404, detail="当前没有正在运行的任务")
    task = _tasks.get(_current_task_id) or {}
    if task.get("status") not in ("running", "pending"):
        raise HTTPException(status_code=400, detail=f"任务当前状态 {task.get('status')} 无法跳过")
    if task.get("command") != "gopay-bind":
        raise HTTPException(status_code=400, detail="当前任务不支持跳过账号")

    params = task.get("params") if isinstance(task.get("params"), dict) else {}
    account_emails = params.get("account_emails") if isinstance(params.get("account_emails"), list) else []
    if len(account_emails) <= 1:
        raise HTTPException(status_code=400, detail="当前 GoPay 任务没有下一个账号可切换")

    skip_signal = _task_skip_signals.get(_current_task_id)
    if skip_signal is None:
        raise HTTPException(status_code=400, detail="当前 GoPay 任务不支持跳过账号")
    skip_signal.set()
    task["skip_current_requested"] = True
    _update_current_task_progress(
        {
            "stage": "gopay_skip_current_requested",
            "message": "已请求跳过当前账号，等待当前步骤在安全点退出后切换下一个账号",
        }
    )
    logger.info("[API] requested GoPay current-account skip: task=%s", _current_task_id[:8])
    return {
        "message": "已请求跳过当前账号，等待切换下一个账号",
        "task_id": _current_task_id,
        "command": task.get("command"),
    }


# ---------------------------------------------------------------------------
# 后台自动巡检
# ---------------------------------------------------------------------------

from autoteam.config import (
    AUTO_CHECK_ENABLED as _DEFAULT_ENABLED,
)
from autoteam.config import (
    AUTO_CHECK_INTERVAL as _DEFAULT_INTERVAL,
)
from autoteam.config import (
    AUTO_CHECK_MIN_LOW as _DEFAULT_MIN_LOW,
)
from autoteam.config import (
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

# auto-fill watchdog 冷却:防止反复触发 cmd_rotate 导致 OpenAI 对短时间内
# 多次 invite/kick 的子号批量 revoke token。30 分钟内只触发一次,给 OpenAI
# 风控系统冷却时间。0 表示从未触发过。
_auto_fill_last_trigger_ts = 0.0
_AUTO_FILL_COOLDOWN_SECONDS = 1800  # 30 min


def _auto_check_loop():
    """后台巡检线程：定期检查额度，多个账号低于阈值时自动轮转"""
    from autoteam.accounts import STATUS_ACTIVE, load_accounts
    from autoteam.codex_auth import check_codex_quota

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
            active = [
                a
                for a in accounts
                if a["status"] == STATUS_ACTIVE
                and not _is_main_account_email(a.get("email"))
                and a.get("auth_file")
                and Path(a["auth_file"]).exists()
            ]

            # Watchdog:active 账号数 < TEAM_SUB_ACCOUNT_HARD_CAP 时自动补位。
            # 之前的 `if not active: continue` 在 4 个 active 全 kick 进 standby
            # 之后会让 Team 永远萎缩。但触发频率必须节制 —— OpenAI 对短时间内反复
            # invite/kick 同一批子号会 revoke token(token_revoked 错误),所以加
            # 30 分钟冷却,避免巡检每 5 分钟无脑触发 cmd_rotate 把账号全洗成废号。
            from autoteam.manager import TEAM_SUB_ACCOUNT_HARD_CAP

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
                    if not _playwright_lock.acquire(blocking=False):
                        logger.info(
                            "[巡检] active=%d < %d 但有任务在跑,本轮先跳过自动补位",
                            len(active),
                            TEAM_SUB_ACCOUNT_HARD_CAP,
                        )
                        continue
                    _playwright_lock.release()
                    logger.warning(
                        "[巡检] active 账号 %d < %d,触发 auto-fill(cmd_rotate 全流程补位)",
                        len(active),
                        TEAM_SUB_ACCOUNT_HARD_CAP,
                    )
                    from autoteam.manager import cmd_rotate

                    try:
                        _start_task(
                            "auto-fill",
                            cmd_rotate,
                            {"target_seats": TEAM_SUB_ACCOUNT_HARD_CAP + 1},
                            TEAM_SUB_ACCOUNT_HARD_CAP + 1,
                        )
                        _auto_fill_last_trigger_ts = now_ts
                    except Exception as e:
                        logger.error("[巡检] auto-fill 启动失败: %s", e)
                    # 触发后本轮不再做"低额度替换",免得跟 cmd_rotate 抢锁
                    continue

            if not active:
                continue

            low_accounts = []
            for acc in active:
                try:
                    auth_data = json.loads(read_text(Path(acc["auth_file"])))
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
                if not _playwright_lock.acquire(blocking=False):
                    logger.info("[巡检] 有任务正在执行，本轮跳过即时替换")
                    continue
                _playwright_lock.release()

                # 先标记 exhausted,cmd_check 入口的对账在此之后再看到就会补 kick(双保险)。
                # 必须同时写 quota_resets_at —— 否则 get_standby_accounts() 看到 None 就默认
                # _quota_recovered=True,导致后续 rotate/replace 立刻把这个 0% 账号当可复用号
                # 反复 reinvite 进 Team,席位来回洗同一批耗尽账号永远不换新鲜的。
                # 阈值默认 5h(18000s),与 check_codex_quota 无返回 resets_at 时的 fallback 一致。
                from autoteam.accounts import STATUS_EXHAUSTED, update_account

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
                from autoteam.manager import cmd_replace_batch

                try:
                    _start_task(
                        "auto-replace",
                        cmd_replace_batch,
                        {"emails": emails_to_replace, "trigger": "auto-check"},
                        emails_to_replace,
                        "auto-check",
                    )
                except Exception as e:
                    logger.error("[巡检] 即时替换启动失败: %s", e)
            else:
                logger.info("[巡检] 额度正常，无需替换")

        except Exception as e:
            logger.error("[巡检] 巡检异常: %s", e)


class AutoCheckConfig(BaseModel):
    enabled: bool | None = None
    interval: int = 300  # 巡检间隔（秒）
    threshold: int = 10  # 额度阈值（%）
    min_low: int = 2  # 触发轮转的最少账号数


@app.get("/api/config/auto-check")
def get_auto_check_config():
    """获取巡检配置"""
    return _auto_check_config.copy()


@app.put("/api/config/auto-check")
def set_auto_check_config(cfg: AutoCheckConfig):
    """修改巡检配置（运行时生效）"""
    if cfg.enabled is not None:
        _auto_check_config["enabled"] = bool(cfg.enabled)
    _auto_check_config["interval"] = max(60, cfg.interval)  # 最少 1 分钟
    _auto_check_config["threshold"] = max(1, min(100, cfg.threshold))
    _auto_check_config["min_low"] = max(1, cfg.min_low)
    _auto_check_restart.set()  # 唤醒巡检线程，立即应用新配置
    logger.info(
        "[巡检] 配置已更新: enabled=%s 间隔=%ds 阈值=%d%%（min_low 已废弃,任意失效立即 1v1 替换）",
        _auto_check_config["enabled"],
        _auto_check_config["interval"],
        _auto_check_config["threshold"],
    )
    return _auto_check_config.copy()


@app.on_event("startup")
def _start_auto_check():
    try:
        from autoteam.auth_storage import ensure_auth_file_permissions

        fixed = ensure_auth_file_permissions()
        if fixed:
            logger.info("[启动] 已修复 %d 个 auths 认证文件权限", fixed)
    except Exception as exc:
        logger.warning("[启动] 修复 auths 认证文件权限失败: %s", exc)

    if not _auto_check_config["enabled"]:
        logger.info("[巡检] 自动巡检已关闭，启动时跳过后台线程")
        return

    thread = threading.Thread(target=_auto_check_loop, daemon=True)
    thread.start()


@app.on_event("shutdown")
def _stop_auto_check():
    _auto_check_stop.set()


# ---------------------------------------------------------------------------
# 前端静态文件
# ---------------------------------------------------------------------------

DIST_DIR = Path(__file__).parent / "web" / "dist"

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
            return FileResponse(str(file))
        return FileResponse(str(DIST_DIR / "index.html"))


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


def start_server(host: str = "0.0.0.0", port: int = 8787):
    """启动 API 服务器"""
    import uvicorn

    # 过滤轮询日志，避免刷屏
    logging.getLogger("uvicorn.access").addFilter(_QuietAccessLog())
    # 首次启动检查配置
    from autoteam.setup_wizard import check_and_setup

    check_and_setup(interactive=True)

    # 重新读取 API_KEY（可能刚刚被向导写入）
    global API_KEY
    from autoteam.config import API_KEY as _fresh_key

    API_KEY = _fresh_key or os.environ.get("API_KEY", "")
    if API_KEY:
        logger.info("[API] API Key 鉴权已启用")
    else:
        logger.warning("[API] 未设置 API_KEY，所有接口无需认证")
    logger.info("[API] 启动 AutoTeam API 服务器 http://%s:%d", host, port)
    if DIST_DIR.exists():
        logger.info("[API] 前端面板 http://%s:%d", host, port)
    logger.info("[API] API 文档 http://%s:%d/docs", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")
