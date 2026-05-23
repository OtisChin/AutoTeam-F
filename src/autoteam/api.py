"""AutoTeam HTTP API - 将 CLI 功能暴露为 HTTP 接口"""

import base64
import io
import json
import logging
import os
import random
import re
import threading
import time
import uuid
import zipfile
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AliasChoices, BaseModel, Field

from autoteam.config import API_KEY
from autoteam.textio import parse_env_line, read_text

logger = logging.getLogger(__name__)
_account_delete_audit_lock = threading.Lock()
_GOPAY_REUSABLE_WALLET_POOL_LOCK = threading.Lock()
_GOPAY_REUSABLE_WALLET_POOL: list[dict[str, Any]] = []


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)) or default)
    except Exception:
        return default


def _gopay_auto_register_bind_delay_seconds() -> float:
    min_seconds = max(0.0, _env_float("GOPAY_AUTO_REGISTER_BIND_DELAY_MIN", 10.0))
    max_seconds = max(0.0, _env_float("GOPAY_AUTO_REGISTER_BIND_DELAY_MAX", 20.0))
    if max_seconds < min_seconds:
        min_seconds, max_seconds = max_seconds, min_seconds
    if max_seconds <= 0:
        return 0.0
    if max_seconds == min_seconds:
        return min_seconds
    return random.uniform(min_seconds, max_seconds)


def _gopay_auto_signup_no_transfer_bind_wait_seconds() -> float:
    return max(0.0, _env_float("GOPAY_AUTO_SIGNUP_NO_TRANSFER_BIND_WAIT_SECONDS", 60.0))


def _gopay_auto_signup_no_transfer_retry_waits_seconds() -> list[float]:
    raw = str(os.environ.get("GOPAY_AUTO_SIGNUP_NO_TRANSFER_RETRY_WAITS", "30,60,120") or "").strip()
    waits: list[float] = []
    for part in re.split(r"[\s,;|]+", raw):
        if not part:
            continue
        try:
            seconds = float(part)
        except Exception:
            continue
        if seconds > 0:
            waits.append(seconds)
    return waits


def _gopay_auto_signup_prefetch_wallets() -> int:
    try:
        return max(0, min(2, int(os.environ.get("GOPAY_AUTO_SIGNUP_PREFETCH_WALLETS", "1") or "1")))
    except Exception:
        return 1


def _default_whatsapp_otp_url() -> str:
    base_url = str(os.environ.get("AUTOTEAM_LOCAL_BASE_URL") or "http://127.0.0.1:8787").strip().rstrip("/")
    return f"{base_url}/otp/whatsapp/latest"


def _request_public_base_url(request: Request | None) -> str:
    if request is None:
        return str(os.environ.get("AUTOTEAM_LOCAL_BASE_URL") or "").strip().rstrip("/")
    try:
        forwarded_host = str(request.headers.get("x-forwarded-host") or "").split(",", 1)[0].strip()
        forwarded_proto = str(request.headers.get("x-forwarded-proto") or "").split(",", 1)[0].strip()
        host = forwarded_host or str(request.headers.get("host") or "").strip()
        if host:
            scheme = forwarded_proto or str(request.url.scheme or "http")
            return f"{scheme}://{host}".rstrip("/")
        return str(request.base_url).strip().rstrip("/")
    except Exception:
        return str(os.environ.get("AUTOTEAM_LOCAL_BASE_URL") or "").strip().rstrip("/")


def _rewrite_local_gopay_signup_url_for_base(sms_url: str, base_url: str) -> str:
    raw = str(sms_url or "").strip()
    base = str(base_url or "").strip().rstrip("/")
    if not raw or not base or "/otp/gopay-signup/" not in raw:
        return raw
    try:
        parsed = urlsplit(raw)
        base_parsed = urlsplit(base)
    except Exception:
        return raw
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return raw
    if not base_parsed.scheme or not base_parsed.netloc:
        return raw
    return urlunsplit((base_parsed.scheme, base_parsed.netloc, parsed.path, parsed.query, parsed.fragment))


def _rewrite_phone_account_sms_url_for_base(account: dict[str, Any], base_url: str) -> dict[str, Any]:
    rewritten = dict(account or {})
    sms_url = str(rewritten.get("sms_url") or rewritten.get("smsUrl") or "").strip()
    if sms_url:
        rewritten["sms_url"] = _rewrite_local_gopay_signup_url_for_base(sms_url, base_url)
    return rewritten


def _mask_gopay_phone_for_log(phone: str) -> str:
    digits = re.sub(r"\D+", "", str(phone or ""))
    if not digits:
        return ""
    if len(digits) <= 4:
        return "***"
    return f"***{digits[-4:]}(len={len(digits)})"


def _normalized_gopay_pool_country(value: Any) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    return digits or "62"


def _gopay_reusable_wallet_ttl_seconds() -> int:
    return max(60, int(_env_float("GOPAY_AUTO_SIGNUP_WALLET_POOL_TTL_SECONDS", 20 * 60)))


def _gopay_wallet_phone(wallet: Any) -> str:
    phone = str(getattr(wallet, "phone_number", "") or "").strip()
    if phone:
        return phone
    try:
        return str((wallet.as_phone_account() or {}).get("phone_number") or "").strip()
    except Exception:
        return ""


def _gopay_wallet_bridge_token(wallet: Any) -> str:
    token = str(getattr(wallet, "bridge_token", "") or "").strip()
    if token:
        return token
    try:
        account = wallet.as_phone_account() or {}
    except Exception:
        account = {}
    raw = str(account.get("bridge_token") or account.get("bridgeToken") or "").strip()
    if raw:
        return raw
    sms_url = str(account.get("sms_url") or account.get("smsUrl") or "").strip()
    matched = re.search(r"/otp/gopay-signup/([^/?#]+)", sms_url)
    return matched.group(1) if matched else ""


def _gopay_wallet_account(wallet: Any) -> dict[str, Any]:
    try:
        account = dict(wallet.as_phone_account() or {})
    except Exception:
        account = {}
    if "phone_number" not in account:
        account["phone_number"] = _gopay_wallet_phone(wallet)
    if "bridge_token" not in account:
        bridge_token = _gopay_wallet_bridge_token(wallet)
        if bridge_token:
            account["bridge_token"] = bridge_token
    return account


def _prune_gopay_reusable_wallet_pool(now: float | None = None) -> None:
    current = time.time() if now is None else float(now)
    expired: list[dict[str, Any]] = []
    with _GOPAY_REUSABLE_WALLET_POOL_LOCK:
        kept = []
        for entry in _GOPAY_REUSABLE_WALLET_POOL:
            if float(entry.get("expires_at") or 0) <= current:
                expired.append(entry)
            else:
                kept.append(entry)
        _GOPAY_REUSABLE_WALLET_POOL[:] = kept
    for entry in expired:
        wallet = entry.get("wallet")
        try:
            if wallet is not None:
                wallet.close(success=False)
        except Exception:
            logger.debug("[gopay-bind] close expired reusable GoPay wallet failed", exc_info=True)


def _push_gopay_reusable_wallet(
    wallet: Any,
    *,
    task_id: str = "",
    created_at: float | None = None,
    funded: bool = False,
) -> dict[str, Any] | None:
    if wallet is None:
        return None
    account = _gopay_wallet_account(wallet)
    phone = str(account.get("phone_number") or "").strip()
    if not phone:
        return None
    current = time.time()
    started_at = float(created_at or current)
    expires_at = started_at + _gopay_reusable_wallet_ttl_seconds()
    if expires_at <= current:
        return None
    entry = {
        "wallet": wallet,
        "phone_number": phone,
        "country_code": _normalized_gopay_pool_country(account.get("country_code") or "62"),
        "gopay_pin": str(account.get("gopay_pin") or "").strip(),
        "sms_url": str(account.get("sms_url") or "").strip(),
        "bridge_token": str(account.get("bridge_token") or "").strip(),
        "created_at": started_at,
        "expires_at": expires_at,
        "funded": bool(funded),
        "task_id": task_id,
    }
    with _GOPAY_REUSABLE_WALLET_POOL_LOCK:
        _GOPAY_REUSABLE_WALLET_POOL[:] = [
            item
            for item in _GOPAY_REUSABLE_WALLET_POOL
            if str(item.get("phone_number") or "") != phone and item.get("wallet") is not wallet
        ]
        _GOPAY_REUSABLE_WALLET_POOL.append(entry)
    return entry


def _pop_gopay_reusable_wallet(*, gopay_pin: str, country_code: str = "62") -> dict[str, Any] | None:
    _prune_gopay_reusable_wallet_pool()
    pin = str(gopay_pin or "").strip()
    country = _normalized_gopay_pool_country(country_code)
    with _GOPAY_REUSABLE_WALLET_POOL_LOCK:
        for index, entry in enumerate(_GOPAY_REUSABLE_WALLET_POOL):
            if pin and str(entry.get("gopay_pin") or "").strip() != pin:
                continue
            if _normalized_gopay_pool_country(entry.get("country_code") or "62") != country:
                continue
            return _GOPAY_REUSABLE_WALLET_POOL.pop(index)
    return None


def _safe_url_for_log(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    try:
        from urllib.parse import urlsplit

        parts = urlsplit(text)
        host = parts.netloc or parts.path.split("/", 1)[0]
        path = parts.path or ""
        return f"host={host} path={path[:40]}{'...' if len(path) > 40 else ''}"
    except Exception:
        return text[:80]

app = FastAPI(
    title="AutoTeam API",
    description="ChatGPT Team 账号自动轮转管理 API",
    version="0.1.0",
)

_cors_origins = [
    origin.strip()
    for origin in str(os.environ.get("PLUS_EXTRACTOR_CORS_ORIGINS") or "*").split(",")
    if origin.strip()
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
    OUTLOOK_ACCOUNTS_FILE: str = ""
    OUTLOOK_ACCOUNTS: str = ""
    OUTLOOK_DEFAULT_CLIENT_ID: str = ""
    OUTLOOK_PROVIDER_PRIORITY: str = ""
    OUTLOOK_PROXY_URL: str = ""
    LUCKMAIL_BASE_URL: str = ""
    LUCKMAIL_API_KEY: str = ""
    LUCKMAIL_PROJECT_CODE: str = ""
    LUCKMAIL_EMAIL_TYPE: str = ""
    LUCKMAIL_PREFERRED_DOMAIN: str = ""
    LUCKMAIL_ACCOUNTS_FILE: str = ""
    LUCKMAIL_ACCOUNTS: str = ""
    CPA_URL: str = ""
    CPA_KEY: str = ""
    PLAYWRIGHT_PROXY_URL: str = ""
    PLAYWRIGHT_PROXY_BYPASS: str = ""
    PLAYWRIGHT_BACKGROUND: str = "1"
    API_KEY: str = ""


class OutlookAccountsImportParams(BaseModel):
    filename: str = ""
    content: str


class ConfigImportParams(BaseModel):
    config: dict | None = None
    content: str = ""
    overwrite_empty: bool = Field(True, validation_alias=AliasChoices("overwrite_empty", "overwriteEmpty"))


def _env_config_keys() -> list[str]:
    from autoteam.setup_wizard import ENV_EXAMPLE

    keys: list[str] = []
    seen: set[str] = set()
    for source in (ENV_EXAMPLE, Path(".env.example")):
        try:
            text = read_text(source)
        except Exception:
            continue
        for line in text.splitlines():
            parsed = parse_env_line(line)
            if not parsed:
                continue
            key, _value = parsed
            if key and key not in seen:
                seen.add(key)
                keys.append(key)
    extra_keys = [
        "CLOUDFLARE_TEMP_EMAIL_BASE_URL",
        "CLOUDFLARE_TEMP_EMAIL_ADMIN_PASSWORD",
        "CLOUDFLARE_TEMP_EMAIL_DOMAIN",
        "CLOUD_MAIL_API_URL",
        "CLOUD_MAIL_ADMIN_EMAIL",
        "CLOUD_MAIL_ADMIN_PASSWORD",
        "CLOUD_MAIL_DOMAIN",
        "CLOUDMAIL_BASE_URL",
        "CLOUDMAIL_PASSWORD",
        "CLOUDMAIL_DOMAIN",
        "MAILLAB_API_URL",
        "MAILLAB_USERNAME",
        "MAILLAB_PASSWORD",
        "MAILLAB_DOMAIN",
        "PLAYWRIGHT_PROXY_SERVER",
        "PLAYWRIGHT_PROXY_USERNAME",
        "PLAYWRIGHT_PROXY_PASSWORD",
        "AUTOTEAM_LOCAL_BASE_URL",
        "GOPAY_AUTO_REGISTER_BIND_DELAY_MIN",
        "GOPAY_AUTO_REGISTER_BIND_DELAY_MAX",
        "GOPAY_AUTO_SIGNUP_WALLET_ATTEMPTS",
        "GOPAY_AUTO_SIGNUP_WALLET_POOL_TTL_SECONDS",
        "OUTLOOK_REGISTER_CODE_TIMEOUT",
    ]
    for key in extra_keys:
        if key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


def _normalize_imported_config(params: ConfigImportParams) -> dict:
    if isinstance(params.config, dict):
        payload = params.config
    else:
        text = str(params.content or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="导入内容不能为空")
        try:
            payload = json.loads(text)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"配置 JSON 解析失败: {exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="配置内容必须是 JSON object")
    return payload


def _reload_env_backed_modules() -> None:
    import importlib

    import autoteam.config

    importlib.reload(autoteam.config)
    try:
        import autoteam.cloudmail

        importlib.reload(autoteam.cloudmail)
    except Exception:
        pass


@app.get("/api/config/export")
def export_config_api():
    """导出设置页相关配置。包含密钥，请只在可信环境保存。"""
    from autoteam.account_hub import get_config as get_account_hub_config
    from autoteam.runtime_config import get_register_domain, get_register_domains
    from autoteam.setup_wizard import _read_env

    env = _read_env()
    env_keys = _env_config_keys()
    return {
        "version": 1,
        "exported_at": time.time(),
        "env": {key: str(env.get(key, os.environ.get(key, "")) or "") for key in env_keys},
        "runtime": {
            "register_domain": get_register_domain(),
            "register_domains": get_register_domains(),
        },
        "account_hub": get_account_hub_config(),
        "auto_check": _auto_check_config.copy() if "_auto_check_config" in globals() else {},
        "auto_refresh_quota": _auto_refresh_quota_config.copy() if "_auto_refresh_quota_config" in globals() else {},
    }


@app.post("/api/config/import")
def import_config_api(params: ConfigImportParams):
    """导入设置页配置并写回 .env / SQLite 配置。"""
    from autoteam.account_hub import set_config as set_account_hub_config
    from autoteam.runtime_config import set_register_domain, set_register_domains
    from autoteam.setup_wizard import _write_env

    payload = _normalize_imported_config(params)
    allowed_env_keys = set(_env_config_keys())
    section_keys = {"version", "exported_at", "env", "runtime", "account_hub", "auto_check", "auto_refresh_quota"}
    raw_env = payload.get("env") if isinstance(payload.get("env"), dict) else (payload if not (set(payload) & section_keys) else {})
    updated_env: list[str] = []
    skipped_env: list[str] = []
    for key, value in (raw_env or {}).items():
        key = str(key or "").strip()
        if key not in allowed_env_keys:
            skipped_env.append(key)
            continue
        text = "" if value is None else str(value)
        if not text and not params.overwrite_empty:
            skipped_env.append(key)
            continue
        _write_env(key, text)
        os.environ[key] = text
        updated_env.append(key)

    runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
    updated_runtime: list[str] = []
    if isinstance(runtime.get("register_domains"), list):
        set_register_domains(runtime.get("register_domains") or [])
        updated_runtime.append("register_domains")
    if "register_domain" in runtime:
        set_register_domain(runtime.get("register_domain") or "")
        updated_runtime.append("register_domain")

    updated_sections: list[str] = []
    if isinstance(payload.get("account_hub"), dict):
        set_account_hub_config(payload["account_hub"])
        updated_sections.append("account_hub")

    if isinstance(payload.get("auto_check"), dict) and "_auto_check_config" in globals():
        cfg = payload["auto_check"]
        _auto_check_config.update(
            {
                "enabled": bool(cfg.get("enabled", _auto_check_config.get("enabled", True))),
                "interval": max(60, int(cfg.get("interval") or _auto_check_config.get("interval") or 300)),
                "threshold": max(1, min(100, int(cfg.get("threshold") or _auto_check_config.get("threshold") or 10))),
                "min_low": max(1, int(cfg.get("min_low") or _auto_check_config.get("min_low") or 1)),
            }
        )
        _auto_check_restart.set()
        updated_sections.append("auto_check")

    if isinstance(payload.get("auto_refresh_quota"), dict) and "_auto_refresh_quota_config" in globals():
        cfg = payload["auto_refresh_quota"]
        interval = max(0, int(cfg.get("interval") or 0))
        enabled = bool(cfg.get("enabled")) and interval > 0
        _auto_refresh_quota_config.update({"enabled": enabled, "interval": max(60, interval) if enabled else 0})
        _save_auto_refresh_quota_config()
        _auto_refresh_quota_restart.set()
        updated_sections.append("auto_refresh_quota")

    _reload_env_backed_modules()
    global API_KEY
    API_KEY = os.environ.get("API_KEY", API_KEY)

    return {
        "message": f"配置导入完成：更新 {len(updated_env)} 个 .env 项",
        "updated_env": updated_env,
        "skipped_env": [key for key in skipped_env if key],
        "updated_runtime": updated_runtime,
        "updated_sections": updated_sections,
    }


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

    from autoteam.setup_wizard import _write_env, get_mail_provider

    data = config.model_dump()
    provider = get_mail_provider(data.get("MAIL_PROVIDER"))
    data["MAIL_PROVIDER"] = provider
    if not data.get("API_KEY"):
        data["API_KEY"] = _secrets.token_urlsafe(24)

    clearable_fields = {"CPA_URL", "CPA_KEY", "PLAYWRIGHT_PROXY_URL", "PLAYWRIGHT_PROXY_BYPASS"}
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
        "outlook": {
            "OUTLOOK_ACCOUNTS_FILE",
            "OUTLOOK_ACCOUNTS",
            "OUTLOOK_DEFAULT_CLIENT_ID",
            "OUTLOOK_PROVIDER_PRIORITY",
            "OUTLOOK_PROXY_URL",
        },
        "luckmail": {
            "LUCKMAIL_BASE_URL",
            "LUCKMAIL_API_KEY",
            "LUCKMAIL_PROJECT_CODE",
            "LUCKMAIL_EMAIL_TYPE",
            "LUCKMAIL_PREFERRED_DOMAIN",
            "LUCKMAIL_ACCOUNTS_FILE",
            "LUCKMAIL_ACCOUNTS",
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


def _mail_provider_field_keys(provider: str) -> set[str]:
    fields = {
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
        "outlook": {
            "OUTLOOK_ACCOUNTS_FILE",
            "OUTLOOK_ACCOUNTS",
            "OUTLOOK_DEFAULT_CLIENT_ID",
            "OUTLOOK_PROVIDER_PRIORITY",
            "OUTLOOK_PROXY_URL",
        },
        "luckmail": {
            "LUCKMAIL_BASE_URL",
            "LUCKMAIL_API_KEY",
            "LUCKMAIL_PROJECT_CODE",
            "LUCKMAIL_EMAIL_TYPE",
            "LUCKMAIL_PREFERRED_DOMAIN",
            "LUCKMAIL_ACCOUNTS_FILE",
            "LUCKMAIL_ACCOUNTS",
        },
    }
    if provider not in fields:
        raise HTTPException(status_code=400, detail=f"未知 MAIL_PROVIDER={provider}")
    return fields[provider]


def _resolve_outlook_accounts_file() -> Path:
    from autoteam.paths import PROJECT_ROOT
    from autoteam.setup_wizard import _read_env, _write_env

    env = _read_env()
    raw = str(env.get("OUTLOOK_ACCOUNTS_FILE") or os.environ.get("OUTLOOK_ACCOUNTS_FILE") or "").strip()
    if not raw:
        raw = "data/outlook_accounts.txt"
        _write_env("OUTLOOK_ACCOUNTS_FILE", raw)
        os.environ["OUTLOOK_ACCOUNTS_FILE"] = raw
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _split_outlook_account_lines(content: str) -> list[str]:
    lines: list[str] = []
    for line in str(content or "").replace("\ufeff", "").replace(";", "\n").splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        lines.append(value)
    return lines


@app.post("/api/config/outlook-accounts/import")
def post_import_outlook_accounts(params: OutlookAccountsImportParams):
    """导入 Outlook/Hotmail 账号池 txt 内容，复用 Outlook provider 的账号行解析规则。"""
    content = str(params.content or "")
    if not content.strip():
        raise HTTPException(status_code=400, detail="上传文件为空")
    if len(content.encode("utf-8", errors="ignore")) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="上传文件过大，最多支持 2MB txt")

    from autoteam.mail.outlook import OutlookMailProvider

    target = _resolve_outlook_accounts_file()
    existing_content = read_text(target) if target.exists() else ""
    existing_accounts: dict[str, str] = {}
    for line in _split_outlook_account_lines(existing_content):
        account = OutlookMailProvider._parse_account_line(line)
        if account and account.validate():
            existing_accounts[account.email.lower()] = line

    imported: list[str] = []
    imported_emails: list[str] = []
    duplicates: list[str] = []
    invalid: list[dict[str, Any]] = []
    seen_upload: set[str] = set()
    for line_no, line in enumerate(_split_outlook_account_lines(content), start=1):
        account = OutlookMailProvider._parse_account_line(line)
        if not account or not account.validate():
            invalid.append({"line": line_no, "preview": line[:120]})
            continue
        email_key = account.email.lower()
        if email_key in existing_accounts or email_key in seen_upload:
            duplicates.append(account.email)
            continue
        seen_upload.add(email_key)
        imported.append(line)
        imported_emails.append(account.email)

    if imported:
        suffix = "\n" if existing_content and not existing_content.startswith(("\n", "\r")) else ""
        target.write_text("\n".join(imported) + suffix + existing_content, encoding="utf-8")

    logger.info(
        "[outlook] 导入账号池: file=%s imported=%d duplicate=%d invalid=%d source=%s",
        target,
        len(imported),
        len(duplicates),
        len(invalid),
        params.filename or "<inline>",
    )
    return {
        "file": str(target),
        "imported": len(imported),
        "duplicates": len(duplicates),
        "invalid": len(invalid),
        "total": len(_split_outlook_account_lines(content)),
        "duplicate_emails": duplicates[:20],
        "imported_emails": imported_emails[:20],
        "first_imported_email": imported_emails[0] if imported_emails else "",
        "invalid_lines": invalid[:20],
    }


def _normalize_gopay_auto_signup_sms_provider(raw: str | None = None) -> str:
    value = str(raw or "").strip().lower().replace("-", "_")
    if value in {"hero_sms", "herosms"}:
        return "hero_sms"
    return "smscloud"


def _normalize_gopay_auto_signup_mode(raw: str | None = None) -> str:
    value = str(raw or "").strip().lower()
    return "appium" if value == "appium" else "http"


def _gopay_auto_signup_env() -> dict[str, str]:
    from autoteam.setup_wizard import _read_env

    env = _read_env()

    def pick(key: str, default: str = "") -> str:
        return str(env.get(key, "") or os.environ.get(key, "") or default).strip()

    return {
        "provider": _normalize_gopay_auto_signup_sms_provider(pick("GOPAY_AUTO_SIGNUP_SMS_PROVIDER", "smscloud")),
        "smscloud_xi_token": pick("GOPAY_AUTO_SIGNUP_SMSCLOUD_XI_TOKEN"),
        "hero_sms_api_key": pick("GOPAY_AUTO_SIGNUP_HERO_SMS_API_KEY"),
        "hero_sms_max_price": pick("GOPAY_AUTO_SIGNUP_HERO_SMS_MAX_PRICE"),
        "proxy_url": pick("GOPAY_AUTO_SIGNUP_PROXY_URL"),
        "country_code": pick("GOPAY_AUTO_SIGNUP_COUNTRY_CODE", "+62"),
        "signup_mode": _normalize_gopay_auto_signup_mode(pick("GOPAY_AUTO_SIGNUP_MODE", "http")),
        "appium_url": pick("GOPAY_APPIUM_URL", "http://127.0.0.1:4723"),
        "appium_adb_serial": pick("GOPAY_APPIUM_ADB_SERIAL"),
    }


def _rekberinaja_env() -> dict[str, str]:
    from autoteam.rekberinaja import (
        DEFAULT_BASE_URL,
        DEFAULT_GOPAY_PRODUCT_ID,
        DEFAULT_GOPAY_SERVICE_ID,
        DEFAULT_STORE,
    )
    from autoteam.setup_wizard import _read_env

    env = _read_env()

    def pick(key: str, default: str = "") -> str:
        return str(env.get(key, "") or os.environ.get(key, "") or default).strip()

    return {
        "enabled": pick("REKBERINAJA_ENABLED", "0"),
        "transfer_enabled": pick("REKBERINAJA_TRANSFER_ENABLED", "0"),
        "email": pick("REKBERINAJA_EMAIL"),
        "password": pick("REKBERINAJA_PASSWORD"),
        "base_url": pick("REKBERINAJA_BASE_URL", DEFAULT_BASE_URL),
        "store": pick("REKBERINAJA_STORE", DEFAULT_STORE),
        "gopay_product_id": pick("REKBERINAJA_GOPAY_PRODUCT_ID", DEFAULT_GOPAY_PRODUCT_ID),
        "gopay_service_id": pick("REKBERINAJA_GOPAY_SERVICE_ID", DEFAULT_GOPAY_SERVICE_ID),
        "min_balance": pick("REKBERINAJA_MIN_BALANCE", "5000"),
        "poll_interval": pick("REKBERINAJA_POLL_INTERVAL", "5"),
        "poll_timeout": pick("REKBERINAJA_POLL_TIMEOUT", "180"),
        "invoice_email": pick("REKBERINAJA_INVOICE_EMAIL"),
    }


def _mask_secret_for_config(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 8:
        return f"{text[:2]}******{text[-2:]}" if len(text) > 4 else "******"
    return f"{text[:4]}******{text[-4:]}"


@app.get("/api/config/rekberinaja")
def get_rekberinaja_config():
    cfg = _rekberinaja_env()
    transfer_enabled = str(cfg["transfer_enabled"]).strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return {
        "enabled": transfer_enabled,
        "transfer_enabled": transfer_enabled,
        "email": cfg["email"],
        "email_present": bool(cfg["email"]),
        "password_present": bool(cfg["password"]),
        "password_masked": _mask_secret_for_config(cfg["password"]),
        "credentials_configured": bool(cfg["email"] and cfg["password"]),
        "configured": bool(transfer_enabled and cfg["email"] and cfg["password"]),
        "min_balance": cfg["min_balance"],
        "poll_timeout": cfg["poll_timeout"],
        "invoice_email": cfg["invoice_email"],
    }


@app.put("/api/config/rekberinaja")
async def save_rekberinaja_config(request: Request):
    from autoteam.setup_wizard import _write_env

    data = await request.json()
    transfer_enabled = bool(data.get("transfer_enabled") or data.get("enabled") or data.get("REKBERINAJA_TRANSFER_ENABLED"))
    email = str(data.get("email") or data.get("REKBERINAJA_EMAIL") or "").strip()
    password = str(data.get("password") or data.get("REKBERINAJA_PASSWORD") or "").strip()
    min_balance = str(data.get("min_balance") or data.get("REKBERINAJA_MIN_BALANCE") or "5000").strip() or "5000"
    poll_timeout = str(data.get("poll_timeout") or data.get("REKBERINAJA_POLL_TIMEOUT") or "180").strip() or "180"
    invoice_email = str(data.get("invoice_email") or data.get("REKBERINAJA_INVOICE_EMAIL") or "").strip()

    updates = {
        "REKBERINAJA_ENABLED": "1" if transfer_enabled else "0",
        "REKBERINAJA_TRANSFER_ENABLED": "1" if transfer_enabled else "0",
        "REKBERINAJA_MIN_BALANCE": min_balance,
        "REKBERINAJA_POLL_TIMEOUT": poll_timeout,
        "REKBERINAJA_BASE_URL": str(data.get("base_url") or os.environ.get("REKBERINAJA_BASE_URL") or "https://api.rekberinaja.com/api").strip(),
        "REKBERINAJA_STORE": str(data.get("store") or os.environ.get("REKBERINAJA_STORE") or "rekberinaja").strip(),
        "REKBERINAJA_GOPAY_PRODUCT_ID": str(
            data.get("gopay_product_id")
            or os.environ.get("REKBERINAJA_GOPAY_PRODUCT_ID")
            or "5668ba3f-9b70-409d-9079-e0aafa798e69"
        ).strip(),
        "REKBERINAJA_GOPAY_SERVICE_ID": str(
            data.get("gopay_service_id")
            or os.environ.get("REKBERINAJA_GOPAY_SERVICE_ID")
            or "81b3fe9a-13ee-11f1-aa7e-c81f66de8b22"
        ).strip(),
        "REKBERINAJA_INVOICE_EMAIL": invoice_email,
    }
    if email:
        updates["REKBERINAJA_EMAIL"] = email
    if password:
        updates["REKBERINAJA_PASSWORD"] = password

    for key, value in updates.items():
        _write_env(key, value)
        os.environ[key] = value

    cfg = _rekberinaja_env()
    saved_transfer_enabled = str(cfg["transfer_enabled"]).strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return {
        "message": "Rekberinaja 配置已保存",
        "enabled": saved_transfer_enabled,
        "transfer_enabled": saved_transfer_enabled,
        "email": cfg["email"],
        "email_present": bool(cfg["email"]),
        "password_present": bool(cfg["password"]),
        "password_masked": _mask_secret_for_config(cfg["password"]),
        "credentials_configured": bool(cfg["email"] and cfg["password"]),
        "configured": bool(saved_transfer_enabled and cfg["email"] and cfg["password"]),
        "min_balance": cfg["min_balance"],
        "poll_timeout": cfg["poll_timeout"],
        "invoice_email": cfg["invoice_email"],
    }


@app.get("/api/config/gopay-auto-signup")
def get_gopay_auto_signup_config():
    cfg = _gopay_auto_signup_env()
    provider = cfg["provider"]
    return {
        "provider": provider,
        "country_code": cfg["country_code"] or "+62",
        "providers": [
            {
                "value": "smscloud",
                "label": "smscloud",
                "configured": bool(cfg["smscloud_xi_token"]),
                "secret_key": "GOPAY_AUTO_SIGNUP_SMSCLOUD_XI_TOKEN",
            },
            {
                "value": "hero_sms",
                "label": "hero-sms",
                "configured": bool(cfg["hero_sms_api_key"]),
                "secret_key": "GOPAY_AUTO_SIGNUP_HERO_SMS_API_KEY",
            },
        ],
        "configured": bool(cfg["smscloud_xi_token"] if provider == "smscloud" else cfg["hero_sms_api_key"]),
        "smscloud_xi_token_present": bool(cfg["smscloud_xi_token"]),
        "hero_sms_api_key_present": bool(cfg["hero_sms_api_key"]),
        "smscloud_xi_token_masked": _mask_secret_for_config(cfg["smscloud_xi_token"]),
        "hero_sms_api_key_masked": _mask_secret_for_config(cfg["hero_sms_api_key"]),
        "hero_sms_max_price": cfg["hero_sms_max_price"],
        "proxy_url": cfg["proxy_url"],
        "proxy_url_present": bool(cfg["proxy_url"]),
        "signup_mode": cfg.get("signup_mode") or "http",
        "appium_url": cfg.get("appium_url") or "http://127.0.0.1:4723",
        "appium_adb_serial": cfg.get("appium_adb_serial") or "",
    }


@app.put("/api/config/gopay-auto-signup")
async def save_gopay_auto_signup_config(request: Request):
    from autoteam.setup_wizard import _write_env

    data = await request.json()
    provider = _normalize_gopay_auto_signup_sms_provider(data.get("provider") or data.get("GOPAY_AUTO_SIGNUP_SMS_PROVIDER"))
    country_code = str(data.get("country_code") or data.get("GOPAY_AUTO_SIGNUP_COUNTRY_CODE") or "+62").strip() or "+62"
    smscloud_xi_token = str(
        data.get("smscloud_xi_token")
        or data.get("GOPAY_AUTO_SIGNUP_SMSCLOUD_XI_TOKEN")
        or ""
    ).strip()
    hero_sms_api_key = str(data.get("hero_sms_api_key") or data.get("GOPAY_AUTO_SIGNUP_HERO_SMS_API_KEY") or "").strip()
    hero_sms_max_price = str(data.get("hero_sms_max_price") or data.get("GOPAY_AUTO_SIGNUP_HERO_SMS_MAX_PRICE") or "").strip()
    proxy_url = str(data.get("proxy_url") or data.get("GOPAY_AUTO_SIGNUP_PROXY_URL") or "").strip()
    signup_mode = _normalize_gopay_auto_signup_mode(data.get("signup_mode") or data.get("GOPAY_AUTO_SIGNUP_MODE") or "http")
    appium_url = str(data.get("appium_url") or data.get("GOPAY_APPIUM_URL") or "").strip()
    appium_adb_serial = str(data.get("appium_adb_serial") or data.get("GOPAY_APPIUM_ADB_SERIAL") or "").strip()

    updates = {
        "GOPAY_AUTO_SIGNUP_SMS_PROVIDER": provider,
        "GOPAY_AUTO_SIGNUP_COUNTRY_CODE": country_code,
        "GOPAY_AUTO_SIGNUP_PROXY_URL": proxy_url,
        "GOPAY_AUTO_SIGNUP_MODE": signup_mode,
    }
    if smscloud_xi_token:
        updates["GOPAY_AUTO_SIGNUP_SMSCLOUD_XI_TOKEN"] = smscloud_xi_token
    if hero_sms_api_key:
        updates["GOPAY_AUTO_SIGNUP_HERO_SMS_API_KEY"] = hero_sms_api_key
    updates["GOPAY_AUTO_SIGNUP_HERO_SMS_MAX_PRICE"] = hero_sms_max_price
    if appium_url:
        updates["GOPAY_APPIUM_URL"] = appium_url
    if appium_adb_serial:
        updates["GOPAY_APPIUM_ADB_SERIAL"] = appium_adb_serial

    for key, value in updates.items():
        _write_env(key, value)
        os.environ[key] = value

    cfg = _gopay_auto_signup_env()
    return {
        "message": "GoPay 自动注册配置已保存",
        "provider": provider,
        "country_code": country_code,
        "configured": bool(cfg["smscloud_xi_token"] if provider == "smscloud" else cfg["hero_sms_api_key"]),
        "smscloud_xi_token_present": bool(cfg["smscloud_xi_token"]),
        "hero_sms_api_key_present": bool(cfg["hero_sms_api_key"]),
        "smscloud_xi_token_masked": _mask_secret_for_config(cfg["smscloud_xi_token"]),
        "hero_sms_api_key_masked": _mask_secret_for_config(cfg["hero_sms_api_key"]),
        "hero_sms_max_price": cfg["hero_sms_max_price"],
        "proxy_url": cfg["proxy_url"],
        "proxy_url_present": bool(cfg["proxy_url"]),
    }


@app.get("/api/config/mail-provider")
def get_mail_provider_config():
    from autoteam.setup_wizard import _read_env, get_mail_provider, get_setup_schema

    env = _read_env()
    schema = get_setup_schema(env)
    provider = get_mail_provider(env.get("MAIL_PROVIDER", "") or os.environ.get("MAIL_PROVIDER", ""))

    provider_fields = {}
    for name, fields in (schema.get("provider_fields") or {}).items():
        provider_fields[name] = []
        for field in fields:
            key = field["key"]
            provider_fields[name].append(
                {
                    **field,
                    "value": env.get(key, "") or os.environ.get(key, "") or field.get("default", ""),
                    "configured": bool(env.get(key, "") or os.environ.get(key, "")),
                }
            )

    return {
        "provider": provider,
        "provider_options": schema.get("provider_options") or [],
        "provider_fields": provider_fields,
    }


@app.put("/api/config/mail-provider")
async def save_mail_provider_config(request: Request):
    from autoteam.setup_wizard import _verify_temporary_email, _write_env, get_mail_provider

    data = await request.json()
    provider = get_mail_provider(data.get("MAIL_PROVIDER"))
    allowed = {"MAIL_PROVIDER"} | _mail_provider_field_keys(provider)

    for key, value in data.items():
        if key not in allowed:
            continue
        text = "" if value is None else str(value)
        _write_env(key, text)
        os.environ[key] = text

    _write_env("MAIL_PROVIDER", provider)
    os.environ["MAIL_PROVIDER"] = provider

    import importlib

    import autoteam.config

    importlib.reload(autoteam.config)

    if not _verify_temporary_email():
        raise HTTPException(status_code=400, detail="邮件 Provider 验证失败，请检查配置")

    return {"message": "邮件 Provider 配置已保存", "provider": provider}


# ---------------------------------------------------------------------------
# 后台任务管理
# ---------------------------------------------------------------------------

_tasks: dict[str, dict] = {}
_playwright_lock = threading.Lock()
_current_task_id: str | None = None
_task_context = threading.local()
TASK_GROUP_DEFAULT = "default"
TASK_GROUP_REGISTER = "register"
TASK_GROUP_BIND_CARD = "bind_card"
TASK_GROUP_GOPAY = "gopay"
TASK_GROUP_PAYPAL = "paypal"
TASK_GROUP_OAUTH = "oauth"
TASK_GROUP_QUOTA = "quota"
TASK_GROUP_TEAM = "team"
_task_group_locks: dict[str, threading.Lock] = {}
_current_task_ids: dict[str, str | None] = {}
_task_skip_signals: dict[str, threading.Event] = {}
_task_cancel_signals: dict[str, threading.Event] = {}
_admin_login_api = None
_admin_login_step: str | None = None
_main_codex_flow = None
_main_codex_step: str | None = None
_manual_account_flow = None
MAX_TASK_HISTORY = 50


def _task_group_lock(task_group: str) -> threading.Lock:
    group = str(task_group or TASK_GROUP_DEFAULT)
    lock = _task_group_locks.get(group)
    if lock is None:
        lock = threading.Lock()
        _task_group_locks[group] = lock
    return lock


def _normalize_task_group(task_group: str | None, command: str = "") -> str:
    explicit = str(task_group or "").strip()
    if explicit:
        return explicit
    raw_command = str(command or "").strip()
    mapping = {
        "register": TASK_GROUP_REGISTER,
        "add": TASK_GROUP_REGISTER,
        "bind-card": TASK_GROUP_BIND_CARD,
        "gopay-bind": TASK_GROUP_GOPAY,
        "paypal": TASK_GROUP_PAYPAL,
        "login": TASK_GROUP_OAUTH,
        "login-batch": TASK_GROUP_OAUTH,
        "refresh-quota": TASK_GROUP_QUOTA,
        "check": TASK_GROUP_QUOTA,
        "rotate": TASK_GROUP_TEAM,
        "replace": TASK_GROUP_TEAM,
        "fill": TASK_GROUP_TEAM,
        "fill-personal": TASK_GROUP_TEAM,
        "cleanup": TASK_GROUP_TEAM,
    }
    if raw_command.startswith("login:"):
        return TASK_GROUP_OAUTH
    return mapping.get(raw_command, TASK_GROUP_DEFAULT)


def _running_task_for_group(task_group: str | None) -> dict:
    group = str(task_group or TASK_GROUP_DEFAULT)
    task_id = _current_task_ids.get(group)
    return _tasks.get(task_id or "", {}) if task_id else {}


def _current_task_id_for_group(task_group: str | None = None) -> str | None:
    current = getattr(_task_context, "task_id", None)
    if current:
        return current
    if task_group:
        return _current_task_ids.get(str(task_group or TASK_GROUP_DEFAULT))
    return _current_task_id


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

    running = _running_task_for_group(task_group) if task_group else _tasks.get(_current_task_id, {})
    return {
        "message": default_message,
        "running_task": {
            "task_id": running.get("task_id") or _current_task_id,
            "command": running.get("command", "unknown"),
            "task_group": running.get("task_group") or task_group,
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


def _task_public_snapshot(task: dict) -> dict:
    snapshot = dict(task or {})
    snapshot.pop("_group_lock_preacquired", None)
    return snapshot


_TASK_LIST_PARAM_ALLOW_KEYS = {
    "account_count",
    "account_emails_count",
    "auto_register",
    "auto_register_count",
    "checkout_ui_mode",
    "count",
    "emails_count",
    "link_type",
    "mode",
    "phone_country_code",
    "proxy_label",
    "task_id",
    "timeout",
}

_TASK_LIST_PROGRESS_DROP_KEYS = {
    "account_emails",
    "auth_session",
    "billing_info",
    "checkout",
    "checkout_url",
    "cookie_header",
    "raw",
    "removed_pool_emails",
    "screenshot_paths",
    "successful_emails",
}

_TASK_LIST_RESULT_ALLOW_KEYS = {
    "concurrency",
    "failed",
    "failure_stage",
    "message",
    "missing",
    "ok",
    "status",
    "success",
    "successful",
    "total",
}


def _truncate_task_list_value(value, *, max_string: int = 240):
    if isinstance(value, str):
        return value if len(value) <= max_string else f"{value[:max_string]}..."
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        if len(value) <= 6 and all(not isinstance(item, (dict, list)) for item in value):
            return value
        return {"count": len(value)}
    if isinstance(value, dict):
        return {
            str(k): _truncate_task_list_value(v, max_string=120)
            for k, v in list(value.items())[:12]
            if str(k) not in _TASK_LIST_PROGRESS_DROP_KEYS
        }
    return str(value)


def _compact_task_params(params: dict | None) -> dict:
    if not isinstance(params, dict):
        return {}
    compact = {
        key: _truncate_task_list_value(params.get(key))
        for key in _TASK_LIST_PARAM_ALLOW_KEYS
        if key in params
    }
    for key in ("account_emails", "emails"):
        value = params.get(key)
        if isinstance(value, list):
            compact[f"{key}_count"] = len(value)
    return compact


def _compact_task_progress(progress: dict | None) -> dict:
    if not isinstance(progress, dict):
        return {}
    return {
        str(key): _truncate_task_list_value(value)
        for key, value in progress.items()
        if str(key) not in _TASK_LIST_PROGRESS_DROP_KEYS
    }


def _compact_task_result(result):
    if not isinstance(result, dict):
        return _truncate_task_list_value(result)
    return {
        key: _truncate_task_list_value(result.get(key))
        for key in _TASK_LIST_RESULT_ALLOW_KEYS
        if key in result
    }


def _task_list_snapshot(task: dict) -> dict:
    """Lightweight task snapshot for list polling.

    Full progress history stays available from /api/tasks/{task_id}. The
    dashboard polls /api/tasks frequently; returning 50 tasks * 300 progress
    events makes the first screen slow once the system has real history.
    """
    snapshot = _task_public_snapshot(task)
    progress_events = snapshot.pop("progress_events", None)
    if isinstance(progress_events, list):
        snapshot["progress_event_count"] = len(progress_events)
    snapshot["params"] = _compact_task_params(snapshot.get("params"))
    snapshot["progress"] = _compact_task_progress(snapshot.get("progress"))
    snapshot["result"] = _compact_task_result(snapshot.get("result"))
    if snapshot.get("error"):
        snapshot["error"] = _truncate_task_list_value(snapshot.get("error"))
    return snapshot


def _persist_task_snapshot(task: dict | None) -> None:
    if not task or not task.get("task_id"):
        return
    try:
        from autoteam import sqlite_store

        snapshot = _task_public_snapshot(task)
        sqlite_store.initialize()
        with sqlite_store.connect() as conn:
            conn.execute(
                """
                INSERT INTO task_snapshots(
                    task_id, command, task_group, status, created_at, started_at,
                    finished_at, owner_pid, data, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s','now'))
                ON CONFLICT(task_id) DO UPDATE SET
                    command=excluded.command,
                    task_group=excluded.task_group,
                    status=excluded.status,
                    started_at=excluded.started_at,
                    finished_at=excluded.finished_at,
                    owner_pid=excluded.owner_pid,
                    data=excluded.data,
                    updated_at=excluded.updated_at
                """,
                (
                    str(snapshot.get("task_id") or ""),
                    str(snapshot.get("command") or ""),
                    str(snapshot.get("task_group") or TASK_GROUP_DEFAULT),
                    str(snapshot.get("status") or "pending"),
                    float(snapshot.get("created_at") or time.time()),
                    snapshot.get("started_at"),
                    snapshot.get("finished_at"),
                    os.getpid(),
                    json.dumps(snapshot, ensure_ascii=False),
                ),
            )
    except Exception:
        logger.debug("[tasks] failed to persist task snapshot", exc_info=True)


def _process_is_running(pid: int | None) -> bool:
    try:
        value = int(pid or 0)
    except Exception:
        return False
    if value <= 0:
        return False
    if value == os.getpid():
        return True

    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            process_query_limited_information = 0x1000
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel32.GetExitCodeProcess.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            handle = kernel32.OpenProcess(process_query_limited_information, False, value)
            if not handle:
                return False
            try:
                exit_code = wintypes.DWORD()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return False
                return exit_code.value == 259  # STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False

    try:
        os.kill(value, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


def _cancel_orphaned_task_snapshots() -> int:
    """Mark persisted running tasks as cancelled when their owner process is gone."""
    try:
        from autoteam import sqlite_store

        sqlite_store.initialize()
        with sqlite_store.connect() as conn:
            rows = conn.execute(
                """
                SELECT task_id, owner_pid, data
                FROM task_snapshots
                WHERE status IN ('running', 'pending')
                """
            ).fetchall()
            cancelled = 0
            now = time.time()
            for row in rows:
                owner_pid = row["owner_pid"]
                if _process_is_running(owner_pid):
                    continue
                try:
                    data = json.loads(row["data"] or "{}")
                except Exception:
                    data = {}
                if not isinstance(data, dict):
                    data = {}
                data.setdefault("task_id", row["task_id"])
                data["status"] = "cancelled"
                data["finished_at"] = now
                data["error"] = "后端已重启，旧任务已中断"
                event = {
                    "stage": "task_interrupted_on_startup",
                    "message": "后端已重启，旧任务已中断，可重新提交任务",
                    "event_id": uuid.uuid4().hex[:12],
                    "updated_at": now,
                }
                data["progress"] = {**(data.get("progress") or {}), **event}
                progress_events = data.setdefault("progress_events", [])
                if isinstance(progress_events, list):
                    progress_events.append(event)
                    if len(progress_events) > 300:
                        del progress_events[: len(progress_events) - 300]
                else:
                    data["progress_events"] = [event]
                conn.execute(
                    """
                    UPDATE task_snapshots
                    SET status = 'cancelled',
                        finished_at = ?,
                        data = ?,
                        updated_at = strftime('%s','now')
                    WHERE task_id = ?
                    """,
                    (now, json.dumps(data, ensure_ascii=False), row["task_id"]),
                )
                cancelled += 1
            return cancelled
    except Exception:
        logger.debug("[tasks] failed to cancel orphaned task snapshots", exc_info=True)
        return 0


def _interrupted_task_snapshot(data: dict, *, now: float | None = None) -> dict:
    timestamp = now or time.time()
    snapshot = dict(data or {})
    snapshot["status"] = "cancelled"
    snapshot["finished_at"] = timestamp
    snapshot["error"] = "后端已重启，旧任务已中断"
    event = {
        "stage": "task_interrupted_on_startup",
        "message": "后端已重启，旧任务已中断，可重新提交任务",
        "event_id": uuid.uuid4().hex[:12],
        "updated_at": timestamp,
    }
    snapshot["progress"] = {**(snapshot.get("progress") or {}), **event}
    progress_events = snapshot.get("progress_events")
    if isinstance(progress_events, list):
        progress_events = [*progress_events, event]
        if len(progress_events) > 300:
            progress_events = progress_events[-300:]
    else:
        progress_events = [event]
    snapshot["progress_events"] = progress_events
    return snapshot


def _load_task_snapshots(limit: int = MAX_TASK_HISTORY) -> list[dict]:
    try:
        from autoteam import sqlite_store

        sqlite_store.initialize()
        with sqlite_store.connect() as conn:
            rows = conn.execute(
                """
                SELECT task_id, owner_pid, status, data
                FROM task_snapshots
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
            tasks = []
            stale_updates = []
            now = time.time()
            for row in rows:
                try:
                    data = json.loads(row["data"] or "{}")
                except Exception:
                    continue
                if not isinstance(data, dict):
                    continue
                data.setdefault("task_id", row["task_id"])
                status = str(row["status"] or data.get("status") or "")
                if status in ("running", "pending") and not _process_is_running(row["owner_pid"]):
                    data = _interrupted_task_snapshot(data, now=now)
                    stale_updates.append((json.dumps(data, ensure_ascii=False), row["task_id"], now))
                if data.get("task_id"):
                    tasks.append(data)
            for data_json, task_id, finished_at in stale_updates:
                conn.execute(
                    """
                    UPDATE task_snapshots
                    SET status = 'cancelled',
                        finished_at = ?,
                        data = ?,
                        updated_at = strftime('%s','now')
                    WHERE task_id = ?
                    """,
                    (finished_at, data_json, task_id),
                )
            return tasks
    except Exception:
        logger.debug("[tasks] failed to load task snapshots", exc_info=True)
        return []


def _merged_task_snapshots(*, compact: bool = False) -> list[dict]:
    snapshot_fn = _task_list_snapshot if compact else _task_public_snapshot
    merged = {str(task.get("task_id") or ""): snapshot_fn(task) for task in _load_task_snapshots()}
    for task_id, task in _tasks.items():
        merged[str(task_id)] = snapshot_fn(task)
    return sorted(
        [task for task in merged.values() if task.get("task_id")],
        key=lambda t: float(t.get("created_at") or 0),
        reverse=True,
    )


def _append_task_progress(task_id: str | None, progress: dict):
    """Append a progress event to a specific task, even from detached worker threads."""
    if not task_id:
        return
    task = _tasks.get(task_id)
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
    _persist_task_snapshot(task)


def _update_current_task_progress(progress: dict, task_group: str | None = None):
    """更新当前运行任务的实时进度。"""
    _append_task_progress(_current_task_id_for_group(task_group), progress)


def _run_task(task_id: str, func, pass_task_id: bool = False, *args, **kwargs):
    """在后台线程中执行任务"""
    from autoteam import cancel_signal

    global _current_task_id
    task = _tasks[task_id]
    task_group = str(task.get("task_group") or TASK_GROUP_DEFAULT)
    group_lock = _task_group_lock(task_group)

    lock_preacquired = bool(task.pop("_group_lock_preacquired", False))
    if not lock_preacquired:
        group_lock.acquire()
    cancel_event = _task_cancel_signals.get(task_id) or threading.Event()
    _task_context.task_id = task_id
    _task_context.task_group = task_group
    _task_context.cancel_event = cancel_event
    cancel_signal.set_current_event(cancel_event)
    _task_cancel_signals[task_id] = cancel_event
    _current_task_id = task_id
    _current_task_ids[task_group] = task_id
    task["status"] = "running"
    task["started_at"] = time.time()
    if cancel_event.is_set():
        task["status"] = "cancelled"
        task["result"] = {"status": "cancelled", "message": "任务启动前已取消"}
        task["finished_at"] = time.time()
        _persist_task_snapshot(task)
        if _current_task_id == task_id:
            _current_task_id = None
        if _current_task_ids.get(task_group) == task_id:
            _current_task_ids[task_group] = None
        cancel_signal.clear_current_event()
        for attr in ("task_id", "task_group", "cancel_event"):
            try:
                delattr(_task_context, attr)
            except AttributeError:
                pass
        _task_skip_signals.pop(task_id, None)
        _task_cancel_signals.pop(task_id, None)
        group_lock.release()
        return

    try:
        result = func(task_id, *args, **kwargs) if pass_task_id else func(*args, **kwargs)
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
        _persist_task_snapshot(task)
        if _current_task_id == task_id:
            _current_task_id = None
        if _current_task_ids.get(task_group) == task_id:
            _current_task_ids[task_group] = None
        cancel_signal.clear_current_event()
        for attr in ("task_id", "task_group", "cancel_event"):
            try:
                delattr(_task_context, attr)
            except AttributeError:
                pass
        _task_skip_signals.pop(task_id, None)
        _task_cancel_signals.pop(task_id, None)
        group_lock.release()


def _run_task_nonexclusive(task_id: str, func, pass_task_id: bool = False, *args, **kwargs):
    """Run a task without occupying the global Playwright task lock."""
    from autoteam import cancel_signal

    task = _tasks[task_id]
    task_group = str(task.get("task_group") or TASK_GROUP_DEFAULT)
    cancel_event = _task_cancel_signals.get(task_id) or threading.Event()
    _task_context.task_id = task_id
    _task_context.task_group = task_group
    _task_context.cancel_event = cancel_event
    cancel_signal.set_current_event(cancel_event)
    _task_cancel_signals[task_id] = cancel_event
    task["status"] = "running"
    task["started_at"] = time.time()
    if cancel_event.is_set():
        task["status"] = "cancelled"
        task["result"] = {"status": "cancelled", "message": "任务启动前已取消"}
        task["finished_at"] = time.time()
        _persist_task_snapshot(task)
        cancel_signal.clear_current_event()
        for attr in ("task_id", "task_group", "cancel_event"):
            try:
                delattr(_task_context, attr)
            except AttributeError:
                pass
        _task_skip_signals.pop(task_id, None)
        _task_cancel_signals.pop(task_id, None)
        return

    try:
        result = func(task_id, *args, **kwargs) if pass_task_id else func(*args, **kwargs)
        task["status"] = "completed"
        task["result"] = result
    except Exception as e:
        task["status"] = "failed"
        if getattr(e, "task_result", None) is not None:
            task["result"] = e.task_result
        task["error"] = str(e)
        logger.error("[API] 非独占任务 %s failed: %s", task_id[:8], e)
    finally:
        task["finished_at"] = time.time()
        _persist_task_snapshot(task)
        cancel_signal.clear_current_event()
        for attr in ("task_id", "task_group", "cancel_event"):
            try:
                delattr(_task_context, attr)
            except AttributeError:
                pass
        _task_skip_signals.pop(task_id, None)
        _task_cancel_signals.pop(task_id, None)


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
    group_lock_preacquired = False
    if exclusive:
        group_lock = _task_group_lock(normalized_group)
        if not group_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail=_current_busy_detail("同类任务正在执行，请等待完成后再试", normalized_group))
        group_lock_preacquired = True

    task_id = uuid.uuid4().hex[:12]
    task = {
        "task_id": task_id,
        "command": command,
        "task_group": normalized_group,
        "params": params,
        "exclusive": exclusive,
        "status": "pending",
        "created_at": time.time(),
        "started_at": None,
        "finished_at": None,
        "result": None,
        "error": None,
        "progress": None,
        "progress_events": [],
    }
    if group_lock_preacquired:
        task["_group_lock_preacquired"] = True
    _tasks[task_id] = task
    _task_cancel_signals[task_id] = threading.Event()
    _persist_task_snapshot(task)
    _prune_tasks()

    target = _run_task if exclusive else _run_task_nonexclusive
    try:
        thread = threading.Thread(target=target, args=(task_id, func, pass_task_id, *args), kwargs=kwargs, daemon=True)
        thread.start()
    except Exception:
        if group_lock_preacquired:
            _task_group_lock(normalized_group).release()
        _tasks.pop(task_id, None)
        _task_cancel_signals.pop(task_id, None)
        raise

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


class ManualAccountStartParams(BaseModel):
    email: str = ""


def _clean_required_code(code: str) -> str:
    cleaned = str(code or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="验证码不能为空，请输入邮件中的验证码后再提交")
    return cleaned


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


class GoPayPhoneAccountParams(BaseModel):
    country_code: str = Field("", validation_alias=AliasChoices("country_code", "countryCode"))
    phone_number: str = Field("", validation_alias=AliasChoices("phone_number", "phoneNumber"))
    sms_url: str = Field("", validation_alias=AliasChoices("sms_url", "smsUrl"))
    gopay_pin: str = Field("", validation_alias=AliasChoices("gopay_pin", "gopayPin"))
    otp_channel: str = Field("", validation_alias=AliasChoices("otp_channel", "otpChannel"))


class GoPayBindTaskParams(BaseModel):
    email: str = ""
    account_emails: list[str] = []
    auto_register: bool = Field(False, validation_alias=AliasChoices("auto_register", "autoRegister"))
    auto_register_count: int = Field(1, validation_alias=AliasChoices("auto_register_count", "autoRegisterCount"))
    auto_register_protocol: bool = Field(False, validation_alias=AliasChoices("auto_register_protocol", "autoRegisterProtocol"))
    gopay_auto_signup: bool = Field(False, validation_alias=AliasChoices("gopay_auto_signup", "gopayAutoSignup"))
    gopay_auto_signup_sms_provider: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_sms_provider", "gopayAutoSignupSmsProvider"),
    )
    gopay_auto_signup_hero_sms_api_key: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_hero_sms_api_key", "gopayAutoSignupHeroSmsApiKey"),
    )
    gopay_auto_signup_hero_sms_base_url: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_hero_sms_base_url", "gopayAutoSignupHeroSmsBaseUrl"),
    )
    gopay_auto_signup_hero_sms_country: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_hero_sms_country", "gopayAutoSignupHeroSmsCountry"),
    )
    gopay_auto_signup_hero_sms_service: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_hero_sms_service", "gopayAutoSignupHeroSmsService"),
    )
    gopay_auto_signup_hero_sms_timeout: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_hero_sms_timeout", "gopayAutoSignupHeroSmsTimeout"),
    )
    gopay_auto_signup_hero_sms_max_price: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_hero_sms_max_price", "gopayAutoSignupHeroSmsMaxPrice"),
    )
    gopay_auto_signup_smscloud_base_url: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_smscloud_base_url", "gopayAutoSignupSmscloudBaseUrl"),
    )
    gopay_auto_signup_smscloud_country: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_smscloud_country", "gopayAutoSignupSmscloudCountry"),
    )
    gopay_auto_signup_smscloud_service: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_smscloud_service", "gopayAutoSignupSmscloudService"),
    )
    gopay_auto_signup_smscloud_max_price: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_smscloud_max_price", "gopayAutoSignupSmscloudMaxPrice"),
    )
    gopay_auto_signup_smscloud_timeout: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_smscloud_timeout", "gopayAutoSignupSmscloudTimeout"),
    )
    gopay_auto_signup_mode: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_mode", "gopayAutoSignupMode"),
    )
    gopay_appium_url: str = Field(
        "",
        validation_alias=AliasChoices("gopay_appium_url", "gopayAppiumUrl"),
    )
    gopay_appium_adb_serial: str = Field(
        "",
        validation_alias=AliasChoices("gopay_appium_adb_serial", "gopayAppiumAdbSerial"),
    )
    auto_register_mail_provider: str | None = Field(
        None,
        validation_alias=AliasChoices("auto_register_mail_provider", "autoRegisterMailProvider"),
    )
    auto_register_luckmail_email_type: str | None = Field(
        None,
        validation_alias=AliasChoices("auto_register_luckmail_email_type", "autoRegisterLuckmailEmailType"),
    )
    auto_register_luckmail_preferred_domain: str | None = Field(
        None,
        validation_alias=AliasChoices("auto_register_luckmail_preferred_domain", "autoRegisterLuckmailPreferredDomain"),
    )
    auto_register_luckmail_preferred_domains: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("auto_register_luckmail_preferred_domains", "autoRegisterLuckmailPreferredDomains"),
    )
    auto_register_domain: str = Field("", validation_alias=AliasChoices("auto_register_domain", "autoRegisterDomain"))
    auto_register_domains: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("auto_register_domains", "autoRegisterDomains"),
    )
    auto_register_prefix: str = Field("", validation_alias=AliasChoices("auto_register_prefix", "autoRegisterPrefix"))
    auto_register_password: str = Field("", validation_alias=AliasChoices("auto_register_password", "autoRegisterPassword"))
    phone_accounts: list[GoPayPhoneAccountParams] = Field(
        default_factory=list,
        validation_alias=AliasChoices("phone_accounts", "phoneAccounts"),
    )
    phone_number: str = ""
    country_code: str = ""
    sms_url: str = ""
    gopay_pin: str = ""
    otp_channel: str = Field("sms", validation_alias=AliasChoices("otp_channel", "otpChannel"))
    billing_name: str = ""
    billing_country: str = "US"
    billing_state: str = ""
    billing_city: str = ""
    billing_zip: str = ""
    billing_address1: str = ""
    billing_address2: str = ""
    checkout_url: str = ""
    checkout_ui_mode: str = "custom"
    proxy_url: str | None = None
    proxy_label: str = ""
    proxy_bypass: str | None = None
    timeout_seconds: int = 900
    delete_rejected_accounts: bool = False
    auto_oauth_after_success: bool = False
    pending_retry_attempts: int = Field(1, validation_alias=AliasChoices("pending_retry_attempts", "pendingRetryAttempts"))


class PayPalTaskParams(BaseModel):
    runner_mode: str = Field("", validation_alias=AliasChoices("runner_mode", "runnerMode"))
    email: str = ""
    account_emails: list[str] = Field(default_factory=list, validation_alias=AliasChoices("account_emails", "accountEmails"))
    checkout_url: str = Field("", validation_alias=AliasChoices("checkout_url", "checkoutUrl"))
    bind_link_payload: dict = Field(default_factory=dict, validation_alias=AliasChoices("bind_link_payload", "bindLinkPayload"))
    proxy_url: str | None = Field(None, validation_alias=AliasChoices("proxy_url", "proxyUrl"))
    proxy_pool: list[str] = Field(default_factory=list, validation_alias=AliasChoices("proxy_pool", "proxyPool"))
    proxy_pool_text: str = Field("", validation_alias=AliasChoices("proxy_pool_text", "proxyPoolText"))
    proxy_label: str = Field("", validation_alias=AliasChoices("proxy_label", "proxyLabel"))
    proxy_bypass: str | None = Field(None, validation_alias=AliasChoices("proxy_bypass", "proxyBypass"))
    paypal_browser: str = Field("camoufox", validation_alias=AliasChoices("paypal_browser", "paypalBrowser"))
    manual_confirm: bool = Field(True, validation_alias=AliasChoices("manual_confirm", "manualConfirm"))
    paypal_mode: str = Field("existing_account", validation_alias=AliasChoices("paypal_mode", "paypalMode"))
    paypal_email: str = Field("", validation_alias=AliasChoices("paypal_email", "paypalEmail"))
    paypal_password: str = Field("", validation_alias=AliasChoices("paypal_password", "paypalPassword"))
    phone_accounts: list[GoPayPhoneAccountParams] = Field(
        default_factory=list,
        validation_alias=AliasChoices("phone_accounts", "phoneAccounts"),
    )
    sms_url: str = Field("", validation_alias=AliasChoices("sms_url", "smsUrl"))
    otp_channel: str = Field("sms", validation_alias=AliasChoices("otp_channel", "otpChannel"))
    paypal_card_number: str = Field("", validation_alias=AliasChoices("paypal_card_number", "paypalCardNumber"))
    paypal_card_expiry: str = Field("", validation_alias=AliasChoices("paypal_card_expiry", "paypalCardExpiry"))
    paypal_card_cvv: str = Field("", validation_alias=AliasChoices("paypal_card_cvv", "paypalCardCvv"))
    autofill_enabled: bool = Field(False, validation_alias=AliasChoices("autofill_enabled", "autofillEnabled"))
    billing_name: str = Field("", validation_alias=AliasChoices("billing_name", "billingName"))
    billing_email: str = Field("", validation_alias=AliasChoices("billing_email", "billingEmail"))
    billing_phone: str = Field("", validation_alias=AliasChoices("billing_phone", "billingPhone"))
    billing_country: str = Field("US", validation_alias=AliasChoices("billing_country", "billingCountry"))
    billing_state: str = Field("", validation_alias=AliasChoices("billing_state", "billingState"))
    billing_city: str = Field("", validation_alias=AliasChoices("billing_city", "billingCity"))
    billing_zip: str = Field("", validation_alias=AliasChoices("billing_zip", "billingZip"))
    billing_address1: str = Field("", validation_alias=AliasChoices("billing_address1", "billingAddress1"))
    billing_address2: str = Field("", validation_alias=AliasChoices("billing_address2", "billingAddress2"))
    timeout_seconds: int = Field(0, validation_alias=AliasChoices("timeout_seconds", "timeoutSeconds"))
    auto_oauth_after_success: bool = Field(
        False,
        validation_alias=AliasChoices("auto_oauth_after_success", "autoOauthAfterSuccess"),
    )


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


class WhatsAppOtpStartParams(BaseModel):
    profile_dir: str = Field("", validation_alias=AliasChoices("profile_dir", "profileDir"))
    headless: bool = False
    adb_path: str = Field("", validation_alias=AliasChoices("adb_path", "adbPath"))
    adb_serial: str = Field("", validation_alias=AliasChoices("adb_serial", "adbSerial"))
    adb_port: str = Field("", validation_alias=AliasChoices("adb_port", "adbPort"))
    poll_interval_seconds: float = Field(2.0, validation_alias=AliasChoices("poll_interval_seconds", "pollIntervalSeconds"))


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
    mail_provider: str | None = Field(None, validation_alias=AliasChoices("mail_provider", "mailProvider"))
    luckmail_email_type: str | None = Field(None, validation_alias=AliasChoices("luckmail_email_type", "luckmailEmailType"))
    luckmail_preferred_domain: str | None = Field(
        None,
        validation_alias=AliasChoices("luckmail_preferred_domain", "luckmailPreferredDomain"),
    )
    luckmail_preferred_domains: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("luckmail_preferred_domains", "luckmailPreferredDomains"),
    )
    post_register_oauth: bool = False
    protocol_register: bool = Field(False, validation_alias=AliasChoices("protocol_register", "protocolRegister"))


class DeleteBatchParams(BaseModel):
    emails: list[str]
    continue_on_error: bool = True  # 部分失败时继续剩余账号,False 则遇错即停


class AccountEmailBatchParams(BaseModel):
    emails: list[str]


class AccountTypeUpdateParams(BaseModel):
    account_type: str


class AccountCredentialExportParams(BaseModel):
    emails: list[str] = []
    line_format: str = "{email}-----{password}"


class AccountExportStatusUpdateParams(BaseModel):
    emails: list[str]
    exported: bool


class AccountSessionCpaConvertParams(BaseModel):
    emails: list[str] = []


class AccountHubConfigParams(BaseModel):
    url: str = ""
    token: str = ""
    name: str = ""
    auto_upload: bool = Field(False, validation_alias=AliasChoices("auto_upload", "autoUpload"))


class AccountHubIngestPayload(BaseModel):
    source: dict = {}
    accounts: list[dict] = []
    auths: list[dict] = []
    auth_sessions: list[dict] = []


class AccountHubSyncParams(BaseModel):
    emails: list[str] = Field(default_factory=list)


class TradeCreateCdkParams(BaseModel):
    quota_total: int = Field(1, validation_alias=AliasChoices("quota_total", "quotaTotal"))
    note: str = ""


class TradeRedeemParams(BaseModel):
    code: str = ""
    password: str = ""
    count: int = 1
    format: str = "cpa"
    formats: list[str] = Field(default_factory=list)


class TradeQueryParams(BaseModel):
    code: str = ""
    password: str = ""


class TradeSetPasswordParams(BaseModel):
    code: str = ""
    password: str = ""


class TradeCdkStatusParams(BaseModel):
    code: str = ""


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


def _resolve_codex_auth_file(acc: dict) -> str:
    auth_file = (acc.get("auth_file") or "").strip()
    from autoteam.auth_storage import AUTH_DIR

    if auth_file:
        path = Path(auth_file)
        if path.exists() and path.is_file():
            try:
                path.resolve().relative_to(AUTH_DIR.resolve())
                return str(path)
            except Exception:
                pass

    email = _normalized_email(acc.get("email"))
    if not email:
        return ""
    try:
        candidates = sorted(
            AUTH_DIR.glob(f"codex-{email}-*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except Exception:
        return ""
    return str(candidates[0]) if candidates else ""


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
    return _sanitize_accounts_batch([acc], {acc.get("email"): quota_snapshot} if quota_snapshot else {}).pop()


def _sanitize_accounts_batch(accounts: list[dict], quota_cache: dict | None = None) -> list[dict]:
    """Batch sanitize accounts without per-row filesystem scans."""
    quota_cache = quota_cache or {}
    emails = [_normalized_email(acc.get("email")) for acc in accounts if _normalized_email(acc.get("email"))]
    try:
        from autoteam.admin_state import get_admin_email

        main_email = _normalized_email(get_admin_email())
    except Exception:
        main_email = ""
    try:
        from autoteam.auth_index import codex_auth_files_by_email

        auth_files = codex_auth_files_by_email(emails)
    except Exception:
        auth_files = {}
    try:
        from autoteam.auth_session_store import auth_session_files_by_email

        auth_session_files = auth_session_files_by_email(emails)
    except Exception:
        auth_session_files = {}

    sanitized_rows = []
    for acc in accounts:
        email = _normalized_email(acc.get("email"))
        quota_snapshot = quota_cache.get(email) if isinstance(quota_cache, dict) else None
        sanitized_rows.append(_sanitize_account_with_indexes(acc, quota_snapshot, auth_files, auth_session_files, main_email))
    return sanitized_rows


def _sanitize_account_with_indexes(
    acc: dict,
    quota_snapshot: dict | None,
    auth_files: dict[str, str],
    auth_session_files: dict[str, str],
    main_email: str = "",
) -> dict:
    sanitized = {k: v for k, v in acc.items() if k not in ("password", "cloudmail_account_id")}
    email = _normalized_email(acc.get("email"))
    is_main = bool(email and (email == main_email or _is_main_account_email(email)))
    sanitized["is_main_account"] = is_main
    status = acc.get("status", "")
    if status in ("personal", "plus"):
        status = "active"
    if is_main:
        quota_status = _quota_snapshot_status(quota_snapshot) or _quota_snapshot_status(acc.get("last_quota"))
        status = quota_status or ("active" if _resolve_status_auth_file(acc) else status)
    sanitized["status"] = status
    sanitized["account_type"] = _display_account_type(acc)
    sanitized["credentials_exported"] = bool(acc.get("credentials_exported"))
    sanitized["credentials_exported_at"] = acc.get("credentials_exported_at")
    sanitized["account_hub_synced"] = bool(acc.get("account_hub_synced"))
    sanitized["account_hub_synced_at"] = acc.get("account_hub_synced_at")
    indexed_auth_file = auth_files.get(email) or ""
    if indexed_auth_file:
        try:
            from autoteam.auth_storage import AUTH_DIR

            Path(indexed_auth_file).resolve().relative_to(AUTH_DIR.resolve())
        except Exception:
            indexed_auth_file = ""
    codex_auth_file = _resolve_codex_auth_file(acc) or indexed_auth_file
    if not codex_auth_file and sanitized["is_main_account"]:
        codex_auth_file = _resolve_codex_auth_file(acc)
    sanitized["codex_auth_file"] = codex_auth_file
    sanitized["has_codex_auth_file"] = bool(codex_auth_file)
    sanitized["needs_codex_login"] = not sanitized["is_main_account"] and not bool(codex_auth_file)
    auth_session_file = auth_session_files.get(email, "")
    if not auth_session_file:
        try:
            from autoteam.auth_session_store import get_auth_session_file

            auth_session_file = get_auth_session_file(email) or ""
        except Exception:
            auth_session_file = ""
    sanitized["auth_session_file"] = auth_session_file
    return sanitized


def _account_id_from_auth_data(auth_data: dict) -> str:
    account = auth_data.get("account") if isinstance(auth_data.get("account"), dict) else {}
    return str(
        account.get("id")
        or auth_data.get("account_id")
        or auth_data.get("accountId")
        or ""
    ).strip()


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


def _gopay_payment_failed_pool_emails(result: dict, actual_email: str) -> list[str]:
    seen = set()
    emails = []
    for raw_email in result.get("payment_failed_emails") or []:
        email = _normalized_email(raw_email)
        if email and email not in seen:
            seen.add(email)
            emails.append(email)
    if str(result.get("failure_stage") or "") == "gopay_payment_process":
        email = _normalized_email(actual_email)
        if email and email not in seen:
            emails.append(email)
    return emails


def _gopay_token_invalidated_pool_emails(result: dict, actual_email: str) -> list[str]:
    seen = set()
    emails = []
    for raw_email in result.get("token_invalidated_emails") or []:
        email = _normalized_email(raw_email)
        if email and email not in seen:
            seen.add(email)
            emails.append(email)
    message = str(result.get("message") or "").lower()
    if result.get("status") != "success" and (
        "token_invalidated" in message
        or "authentication token has been invalidated" in message
        or ("http 401" in message and "invalidated" in message)
    ):
        email = _normalized_email(actual_email)
        if email and email not in seen:
            emails.append(email)
    return emails


def _paypal_nonzero_blocked_pool_emails(result: dict, actual_email: str) -> list[str]:
    seen = set()
    emails = []
    for raw_email in result.get("nonzero_blocked_emails") or []:
        email = _normalized_email(raw_email)
        if email and email not in seen:
            seen.add(email)
            emails.append(email)
    if str(result.get("failure_stage") or "") == "browser_charge_guard":
        email = _normalized_email(actual_email)
        if email and email not in seen:
            emails.append(email)
    return emails


def _parse_proxy_pool_values(values: list[Any] | tuple[Any, ...] | None = None, text: str | None = None) -> list[str]:
    candidates: list[str] = []
    for raw_value in values or []:
        candidates.append(str(raw_value or ""))
    for raw_line in re.split(r"[\r\n,]+", str(text or "")):
        candidates.append(raw_line)

    proxies: list[str] = []
    seen: set[str] = set()
    for raw_proxy in candidates:
        proxy = str(raw_proxy or "").strip()
        if not proxy:
            continue
        if proxy.startswith("#"):
            continue
        if "#" in proxy:
            proxy = proxy.split("#", 1)[0].strip()
        if not proxy:
            continue
        normalized = proxy.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        proxies.append(proxy)
    return proxies


def _account_delete_audit_path() -> Path:
    from autoteam.paths import PROJECT_ROOT

    return PROJECT_ROOT / "data" / "account_delete_audit.jsonl"


def _account_delete_audit_db_path(path: Path) -> Path:
    from autoteam.paths import PROJECT_ROOT

    default_path = PROJECT_ROOT / "data" / "account_delete_audit.jsonl"
    try:
        if Path(path).resolve() != default_path.resolve():
            return Path(path).with_suffix(".sqlite3")
    except Exception:
        pass
    from autoteam.sqlite_store import default_db_path

    return default_db_path()


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
    payload = {
        "ts": time.time(),
        "email": _normalized_email(email),
        "source": log_context,
        "reason": reason,
        "message": message,
        "record_deleted": bool(record_deleted),
        "auth_session_deleted": bool(auth_session_deleted),
        "mail_service_deleted": bool(mail_service_deleted),
        "account_existed": bool(account),
        "status": (account or {}).get("status"),
        "account_type": (account or {}).get("account_type"),
        "seat_type": (account or {}).get("seat_type"),
        "mail_provider": (account or {}).get("mail_provider"),
        "cloudmail_account_id_present": bool((account or {}).get("cloudmail_account_id")),
        "auth_file": (account or {}).get("auth_file"),
        "last_bind_status": (account or {}).get("last_bind_status"),
        "last_bind_failure_stage": (account or {}).get("last_bind_failure_stage"),
        "last_bind_message": (account or {}).get("last_bind_message"),
        "last_bind_task_id": (account or {}).get("last_bind_task_id"),
        "last_bind_at": (account or {}).get("last_bind_at"),
    }
    try:
        path = _account_delete_audit_path()
        from autoteam import sqlite_store

        sqlite_store.initialize(_account_delete_audit_db_path(path))
        with sqlite_store.connect(_account_delete_audit_db_path(path)) as conn:
            conn.execute(
                """
                INSERT INTO event_records(kind, timestamp, email, category, task_id, status, data)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "account_delete_audit",
                    float(payload.get("ts") or time.time()),
                    str(payload.get("email") or ""),
                    str(payload.get("reason") or ""),
                    str(payload.get("last_bind_task_id") or ""),
                    str(payload.get("status") or ""),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with _account_delete_audit_lock:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception as exc:
        logger.warning("[account-delete-audit] failed to persist delete audit: email=%s error=%s", email, exc)
    logger.warning(
        "[account-delete-audit] account removed: email=%s source=%s reason=%s record_deleted=%s auth_session_deleted=%s account_type=%s status=%s task_id=%s",
        email,
        log_context,
        reason,
        record_deleted,
        auth_session_deleted,
        payload.get("account_type"),
        payload.get("status"),
        payload.get("last_bind_task_id") or "",
    )


def _migrate_account_delete_audit_jsonl() -> int:
    path = _account_delete_audit_path()
    if not path.exists():
        return 0
    try:
        from autoteam import sqlite_store

        marker = sqlite_store.get_json("migrations", "account_delete_audit_jsonl", default=None)
        if isinstance(marker, dict) and marker.get("done"):
            return 0

        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except Exception:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        if not rows:
            sqlite_store.set_json("migrations", "account_delete_audit_jsonl", {"done": True, "count": 0})
            return 0

        sqlite_store.initialize()
        with sqlite_store.connect() as conn:
            for payload in rows:
                conn.execute(
                    """
                    INSERT INTO event_records(kind, timestamp, email, category, task_id, status, data)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "account_delete_audit",
                        float(payload.get("ts") or payload.get("timestamp") or time.time()),
                        str(payload.get("email") or ""),
                        str(payload.get("reason") or ""),
                        str(payload.get("last_bind_task_id") or ""),
                        str(payload.get("status") or ""),
                        json.dumps(payload, ensure_ascii=False),
                    ),
                )
        sqlite_store.set_json("migrations", "account_delete_audit_jsonl", {"done": True, "count": len(rows)})
        return len(rows)
    except Exception as exc:
        logger.warning("[启动] 迁移账号删除审计 JSONL 失败: %s", exc)
        return 0


def _remove_pool_accounts_from_local_and_mail(
    emails: list[str],
    *,
    log_context: str = "account-cleanup",
    reason: str = "unspecified",
    message: str = "",
) -> list[str]:
    """Remove unusable accounts from the local pool without deleting mail-service accounts."""
    if not emails:
        return []
    from autoteam.accounts import delete_account as delete_local_account, find_account, load_accounts
    from autoteam.auth_session_store import delete_auth_session

    removed = []
    accounts = load_accounts()
    for email in emails:
        if not email or _is_main_account_email(email):
            continue
        account = find_account(accounts, email)
        record_deleted = delete_local_account(email)
        session_deleted = delete_auth_session(email)
        if record_deleted or session_deleted:
            removed.append(email)
        _append_account_delete_audit(
            email=email,
            log_context=log_context,
            reason=reason,
            message=message,
            account=account,
            record_deleted=record_deleted,
            auth_session_deleted=session_deleted,
            mail_service_deleted=False,
        )
        logger.info(
            "[%s] account removed locally: email=%s reason=%s record_deleted=%s auth_session_deleted=%s mail_service_deleted=%s cloudmail_account_id=%s",
            log_context,
            email,
            reason,
            record_deleted,
            session_deleted,
            False,
            (account or {}).get("cloudmail_account_id"),
        )
    return removed


def _mark_pool_accounts_fail(
    emails: list[str],
    *,
    reason: str,
    message: str,
    failure_stage: str = "token_invalidated",
    log_context: str = "account-fail",
) -> list[str]:
    """Mark unusable accounts as Fail without removing local/mail records."""
    if not emails:
        return []
    from autoteam.accounts import STATUS_FAIL, find_account, load_accounts, update_account

    marked = []
    accounts = load_accounts()
    now_ts = time.time()
    for email in emails:
        email = _normalized_email(email)
        if not email or _is_main_account_email(email):
            continue
        account = find_account(accounts, email)
        if not account:
            logger.info("[%s] account not found while marking Fail: email=%s", log_context, email)
            continue
        update_account(
            email,
            status=STATUS_FAIL,
            discarded_at=now_ts,
            discarded_reason=reason,
            last_bind_status="failed",
            last_bind_at=now_ts,
            last_bind_message=message,
            last_bind_failure_stage=failure_stage,
        )
        marked.append(email)
        logger.info(
            "[%s] account marked Fail: email=%s reason=%s cloudmail_account_id=%s",
            log_context,
            email,
            reason,
            account.get("cloudmail_account_id"),
        )
    return marked


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
    from autoteam.accounts import ACCOUNT_SOURCE_AUTH_SESSION_STUB, ACCOUNT_TYPE_FREE, SEAT_CODEX, STATUS_ACTIVE

    return {
        "email": email,
        "password": "",
        "cloudmail_account_id": None,
        "status": STATUS_ACTIVE,
        "account_type": ACCOUNT_TYPE_FREE,
        "seat_type": SEAT_CODEX,
        "auth_file": "",
        "created_at": 0,
        "last_active_at": None,
        "account_source": ACCOUNT_SOURCE_AUTH_SESSION_STUB,
    }


def _load_accounts_with_session_stubs(*, include_session_stubs: bool = True) -> list[dict]:
    """Load accounts and persist auth-session-only records when requested."""
    from autoteam.accounts import (
        ACCOUNT_SOURCE_AUTH_SESSION_STUB,
        ACCOUNT_SOURCE_MANAGED,
        ACCOUNT_TYPE_FREE,
        ACCOUNT_TYPE_PLUS,
        SEAT_CODEX,
        STATUS_ACTIVE,
        add_account,
        ensure_session_only_account,
        load_accounts,
        update_account,
    )

    accounts = load_accounts()
    if not include_session_stubs:
        return accounts

    from autoteam.auth_session_store import list_auth_session_emails

    session_emails = [_normalized_email(email) for email in list_auth_session_emails()]
    session_emails = [email for email in session_emails if email]
    try:
        from autoteam.auth_index import codex_auth_files_by_email

        indexed_auth_files = codex_auth_files_by_email(session_emails)
    except Exception:
        indexed_auth_files = {}
    try:
        from autoteam.bind_audit import list_bind_audits

        gopay_success_emails = set()
        for item in list_bind_audits(limit=1000):
            if (
                str(item.get("flow") or "").lower() != "gopay"
                or str(item.get("status") or "").lower() != "success"
            ):
                continue
            for value in [
                item.get("email"),
                item.get("requested_email"),
                *(item.get("successful_emails") if isinstance(item.get("successful_emails"), list) else []),
            ]:
                normalized = _normalized_email(value)
                if normalized:
                    gopay_success_emails.add(normalized)
    except Exception:
        gopay_success_emails = set()

    existing_emails = {_normalized_email(acc.get("email")) for acc in accounts if _normalized_email(acc.get("email"))}
    for acc in list(accounts):
        normalized = _normalized_email(acc.get("email"))
        if not normalized:
            continue
        indexed_auth_file = indexed_auth_files.get(normalized) or ""
        if (
            str(acc.get("account_source") or "").strip().lower() == ACCOUNT_SOURCE_AUTH_SESSION_STUB
            and (indexed_auth_file or normalized in gopay_success_emails)
        ):
            updated = update_account(
                normalized,
                status=STATUS_ACTIVE,
                account_type=ACCOUNT_TYPE_PLUS if normalized in gopay_success_emails else (acc.get("account_type") or ACCOUNT_TYPE_FREE),
                seat_type=acc.get("seat_type") or SEAT_CODEX,
                auth_file=indexed_auth_file or acc.get("auth_file"),
                account_source=ACCOUNT_SOURCE_MANAGED,
            )
            if updated:
                acc.update(updated)

    for email in session_emails:
        normalized = _normalized_email(email)
        if not normalized or normalized in existing_emails:
            continue
        indexed_auth_file = indexed_auth_files.get(normalized) or ""
        if indexed_auth_file or normalized in gopay_success_emails:
            add_account(normalized, "", seat_type=SEAT_CODEX)
            restored = update_account(
                normalized,
                status=STATUS_ACTIVE,
                account_type=ACCOUNT_TYPE_PLUS if normalized in gopay_success_emails else ACCOUNT_TYPE_FREE,
                seat_type=SEAT_CODEX,
                auth_file=indexed_auth_file or None,
                account_source=ACCOUNT_SOURCE_MANAGED,
            )
            accounts.append(restored or _session_only_account_stub(normalized))
        else:
            stub = ensure_session_only_account(normalized) or _session_only_account_stub(normalized)
            accounts.append(stub)
        existing_emails.add(normalized)
    return accounts


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
        code = _clean_required_code(params.code)
        logger.info("[API] 提交管理员验证码 | current_step=%s code_len=%d", _admin_login_step, len(code))
        result = _pw_executor.run(_admin_login_api.submit_admin_code, code)
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
        code = _clean_required_code(params.code)
        result = _pw_executor.run(_main_codex_flow.submit_code, code)
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
def post_manual_account_start(params: ManualAccountStartParams = ManualAccountStartParams()):
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

        flow = ManualAccountFlow(email=params.email, auto_open_helper=True)
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
def get_accounts(include_session_stubs: bool = True):
    """获取所有账号列表"""
    accounts = _load_accounts_with_session_stubs(include_session_stubs=include_session_stubs)
    return _sanitize_accounts_batch(accounts)


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


def _extract_account_access_token(email: str) -> str:
    from autoteam.accounts import find_account, load_accounts
    from autoteam.auth_session_store import get_auth_session_file
    from autoteam.codex_auth import get_saved_main_auth_file

    normalized = _normalized_email(email)
    if not normalized:
        return ""

    auth_file = ""
    if _is_main_account_email(normalized):
        auth_file = get_saved_main_auth_file() or ""
    else:
        acc = find_account(load_accounts(), normalized)
        if acc:
            auth_file = str(acc.get("auth_file") or "").strip()
        if not auth_file:
            auth_file = str(get_auth_session_file(normalized) or "").strip()
    if not auth_file or not Path(auth_file).exists():
        return ""

    try:
        auth_data = json.loads(Path(auth_file).read_text(encoding="utf-8"))
    except Exception:
        return ""
    return _normalize_access_token(auth_data.get("access_token") or auth_data.get("accessToken") or "")


def _refresh_account_access_token(email: str) -> str:
    from autoteam.auth_session_store import load_auth_session, save_auth_session
    from autoteam.gopay_executor import _configure_chatgpt_http_session, _safe_email_summary

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
        _configure_chatgpt_http_session(
            http,
            access_token="",
            session_token=session_token,
            cookie_header=cookie_header,
            device_id=device_id,
            user_agent=user_agent,
        )
        response = http.get("https://chatgpt.com/api/auth/session", timeout=max(10.0, _env_float("CHECKOUT_HTTP_TIMEOUT_SECONDS", 30.0)))
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
        logger.info("[paypal] refresh access token from session failed: email=%s error=%s", _safe_email_summary(normalized), exc)
        return ""
    finally:
        try:
            http.close()
        except Exception:
            pass


def _looks_like_html_error(text: str) -> bool:
    compact = str(text or "").strip().lower()
    if not compact:
        return False
    return compact.startswith("<!doctype html") or compact.startswith("<html") or "<head" in compact[:200]


def _friendly_checkout_error(detail: str, status: int | None = None) -> str:
    text = str(detail or "").strip()
    if not text:
        return f"上游错误({status or 502})"
    if _looks_like_html_error(text):
        if status == 403:
            return "生成 checkout 被上游 403 拦截，返回了 HTML 风控页；通常是账号 access_token 失效、Cloudflare 未通过，或当前 IP/环境被风控"
        return f"生成 checkout 返回了 HTML 页面（HTTP {status or 502}），通常是会话未通过或遭遇风控"
    lowered = text.lower()
    if status == 403 and ("forbidden" in lowered or "denied" in lowered):
        return "生成 checkout 被上游 403 拦截；通常是账号 access_token 失效、Cloudflare 未通过，或当前 IP/环境被风控"
    return text


def _looks_like_cloudflare_challenge(text: str) -> bool:
    lowered = str(text or "").lower()
    return (
        "_cf_chl_opt" in lowered
        or "enable javascript and cookies to continue" in lowered
        or "cf-chl" in lowered
        or "verify you are human" in lowered
    )


def _parse_checkout_response_json(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text or "{}")
        return parsed if isinstance(parsed, dict) else {"data": parsed}
    except json.JSONDecodeError:
        return {"detail": text or "upstream returned non-json response"}


def _find_hosted_checkout_url(payload: Any) -> str:
    pay_openai_pattern = re.compile(r"^https://(?:pay\.openai\.com|checkout\.stripe\.com)/c/pay/", re.I)
    stack = [payload]
    while stack:
        current = stack.pop(0)
        if isinstance(current, list):
            stack.extend(current)
            continue
        if not isinstance(current, dict):
            continue
        for value in current.values():
            if isinstance(value, str) and pay_openai_pattern.match(value.strip()):
                return value.strip()
            if isinstance(value, (dict, list)):
                stack.append(value)
    return ""


def _choose_checkout_error_status(upstream_status: int) -> int:
    if upstream_status in (400, 401, 403, 404, 409, 422, 429):
        return upstream_status
    return 502


def _normalize_checkout_payload_for_http(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload or {})
    plan_name = str(normalized.get("plan_name") or "").strip().lower()
    if not plan_name:
        normalized["plan_name"] = "chatgptplusplan"
        plan_name = "chatgptplusplan"
    if plan_name == "chatgptplusplan":
        normalized.setdefault("entry_point", "all_plans_pricing_modal")
        normalized.setdefault(
            "promo_campaign",
            {
                "promo_campaign_id": "plus-1-month-free",
                "is_coupon_from_query_param": False,
            },
        )
    billing_details = normalized.get("billing_details") if isinstance(normalized.get("billing_details"), dict) else {}
    normalized["billing_details"] = {
        "country": str(billing_details.get("country") or "US").strip().upper() or "US",
        "currency": str(billing_details.get("currency") or "USD").strip().upper() or "USD",
    }
    checkout_ui_mode = str(normalized.get("checkout_ui_mode") or "").strip().lower()
    if checkout_ui_mode:
        normalized["checkout_ui_mode"] = "hosted" if checkout_ui_mode == "hosted" else "custom"
    return normalized


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
        session._autoteam_transport = "curl_cffi"  # type: ignore[attr-defined]
    except Exception:
        pass
    return session


def _generate_checkout_link_via_http(access_token: str, payload: dict[str, Any]) -> dict[str, Any]:
    from autoteam.gopay_executor import _configure_chatgpt_http_session

    normalized_access_token = _normalize_access_token(access_token)
    if not normalized_access_token:
        raise HTTPException(status_code=400, detail="请提供 access_token")

    payload = _normalize_checkout_payload_for_http(payload)

    primary_impersonate = str(os.environ.get("CHECKOUT_IMPERSONATE_BROWSER") or "chrome136").strip() or "chrome136"
    fallback_impersonate = str(os.environ.get("CHECKOUT_FALLBACK_IMPERSONATE_BROWSER") or "chrome133a").strip() or "chrome133a"
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    )
    request_timeout = max(10.0, _env_float("CHECKOUT_HTTP_TIMEOUT_SECONDS", 30.0))

    def _post_once_requests() -> tuple[Any, str]:
        http = requests.Session()
        try:
            _configure_chatgpt_http_session(
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
            _configure_chatgpt_http_session(
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
            raise HTTPException(status_code=502, detail="upstream checkout request failed: " + " | ".join(request_errors)) from exc

    if _looks_like_cloudflare_challenge(raw_text) and fallback_impersonate and fallback_impersonate != primary_impersonate:
        logger.info(
            "[bind/link] upstream returned Cloudflare challenge; retrying with fallback impersonate=%s",
            fallback_impersonate,
        )
        try:
            response, raw_text = _post_once(fallback_impersonate)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"upstream checkout retry failed: {type(exc).__name__}: {exc}") from exc

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
    preferred_checkout_url = hosted_checkout_url if checkout_ui_mode == "hosted" and hosted_checkout_url else chatgpt_checkout_url
    return {
        "url": preferred_checkout_url,
        "checkout_session_id": checkout_session_id,
        "processor_entity": processor_entity,
        "hosted_checkout_url": hosted_checkout_url,
        "chatgpt_checkout_url": chatgpt_checkout_url,
        "upstream_status": upstream_status,
        "attempt": "http",
    }


def _generate_checkout_link(access_token: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _generate_checkout_link_via_http(access_token, payload)


def _generate_checkout_link_via_browser(
    access_token: str,
    payload: dict[str, Any],
    *,
    email: str = "",
    proxy_url: str | None = None,
    proxy_bypass: str | None = None,
) -> dict[str, Any]:
    from autoteam.auth_session_store import load_auth_session
    from autoteam.chatgpt_api import ChatGPTTeamAPI
    from autoteam.gopay_executor import _inject_chatgpt_browser_cookies

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
        session_data: dict[str, Any] = {}
        normalized_email = _normalized_email(email)
        if normalized_email:
            session_data = load_auth_session(normalized_email)
        device_id = str(session_data.get("device_id") or session_data.get("oai_device_id") or "").strip()
        api.oai_device_id = device_id or getattr(api, "oai_device_id", "")
        api._launch_browser(proxy_url=proxy_url, proxy_bypass=proxy_bypass, headless=False, background=True)
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
            _inject_chatgpt_browser_cookies(
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
    lock_acquired = _playwright_lock.acquire(blocking=False)
    try:
        from autoteam.account_ops import delete_managed_account
        from autoteam.accounts import load_accounts
        from autoteam.admin_state import get_admin_session_token, get_chatgpt_account_id
        from autoteam.auth_session_store import delete_auth_session, get_auth_session_file

        if _is_main_account_email(email):
            raise HTTPException(status_code=400, detail="主号不允许删除")

        accounts = load_accounts()
        if not any(a["email"].lower() == email.lower() for a in accounts) and not get_auth_session_file(email):
            raise HTTPException(status_code=404, detail="账号不存在")

        remote_cleanup = bool(lock_acquired and get_admin_session_token() and get_chatgpt_account_id())
        if lock_acquired:
            cleanup = _pw_executor.run(delete_managed_account, email, remove_remote=remote_cleanup, remove_cloudmail=False)
        else:
            cleanup = delete_managed_account(email, remove_remote=False, remove_cloudmail=False)
        cleanup["auth_session_deleted"] = delete_auth_session(email)
        return {
            "message": "账号删除完成",
            "deleted_email": email,
            "cleanup": cleanup,
            "remote_cleanup": remote_cleanup,
            "remote_cleanup_skipped": not lock_acquired,
        }
    finally:
        if lock_acquired:
            _playwright_lock.release()


@app.post("/api/accounts/{email}/type")
def update_account_type(email: str, params: AccountTypeUpdateParams):
    """手动更新账号类型。只改本地 accounts.json，不做 Team/CPA 侧操作。"""
    from autoteam.accounts import (
        ACCOUNT_SOURCE_MANAGED,
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
    from autoteam.accounts import ACCOUNT_SOURCE_AUTH_SESSION_STUB, load_accounts, update_account
    from autoteam.trade import credential_password_for_account

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

    skipped_session_only = []
    export_rows = []
    for account in rows:
        if str(account.get("account_source") or "").strip().lower() == ACCOUNT_SOURCE_AUTH_SESSION_STUB:
            skipped_session_only.append(_normalized_email(account.get("email")))
            continue
        export_rows.append(account)

    def render_line(account: dict) -> str:
        values = {
            "email": str(account.get("email") or ""),
            "password": credential_password_for_account(account),
        }
        line = line_format
        for key, value in values.items():
            line = line.replace("{" + key + "}", value)
        return line

    content = "\n".join(render_line(account) for account in export_rows)
    exported_at = time.time()
    exported_emails = []
    for account in export_rows:
        exported_email = _normalized_email(account.get("email"))
        if not exported_email:
            continue
        update_account(
            exported_email,
            credentials_exported=True,
            credentials_exported_at=exported_at,
        )
        exported_emails.append(exported_email)
    return {
        "content": content,
        "count": len(export_rows),
        "missing": missing,
        "skipped_session_only": [email for email in skipped_session_only if email],
        "exported_emails": exported_emails,
        "exported_at": exported_at,
        "filename": "accounts-credentials.txt",
        "format": line_format,
    }


@app.post("/api/accounts/export-cpa-auths")
def export_account_cpa_auths(params: AccountEmailBatchParams):
    """导出 data/auths 下的 CPA 兼容认证 JSON。单个返回 JSON，多个返回 zip。"""
    from autoteam.accounts import ACCOUNT_SOURCE_MANAGED, SEAT_CODEX, STATUS_ACTIVE, find_account, load_accounts, update_account

    requested = []
    seen = set()
    for email in params.emails or []:
        normalized = _normalized_email(email)
        if normalized and normalized not in seen:
            seen.add(normalized)
            requested.append(normalized)
    if not requested:
        raise HTTPException(status_code=400, detail="emails 不能为空")

    accounts = load_accounts()
    files = []
    missing = []
    for email in requested:
        account = find_account(accounts, email)
        if not account:
            missing.append(email)
            continue
        auth_file = _resolve_codex_auth_file(account)
        if not auth_file:
            missing.append(email)
            continue
        path = Path(auth_file)
        try:
            content = read_text(path)
            json.loads(content)
        except Exception as exc:
            logger.warning("[API] CPA auth 导出跳过无效文件: email=%s path=%s error=%s", email, path, exc)
            missing.append(email)
            continue
        files.append({"email": email, "filename": path.name, "content": content})

    if not files:
        raise HTTPException(status_code=404, detail="选中的账号没有可导出的 data/auths 认证文件")

    exported_at = time.time()
    exported_emails = []
    for file in files:
        email = _normalized_email(file.get("email"))
        if not email:
            continue
        update_account(
            email,
            credentials_exported=True,
            credentials_exported_at=exported_at,
        )
        exported_emails.append(email)

    if len(files) == 1:
        file = files[0]
        raw = file["content"].encode("utf-8")
        filename = file["filename"]
        content_type = "application/json"
    else:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            used_names = set()
            for file in files:
                name = file["filename"]
                if name in used_names:
                    stem = Path(name).stem
                    suffix = Path(name).suffix or ".json"
                    name = f"{stem}-{file['email']}{suffix}"
                used_names.add(name)
                archive.writestr(name, file["content"])
        raw = buffer.getvalue()
        filename = f"cpa-auths-{time.strftime('%Y%m%d-%H%M%S')}.zip"
        content_type = "application/zip"

    return {
        "filename": filename,
        "content_type": content_type,
        "content_base64": base64.b64encode(raw).decode("ascii"),
        "count": len(files),
        "missing": missing,
        "exported_emails": exported_emails,
        "exported_at": exported_at,
        "files": [{"email": file["email"], "filename": file["filename"]} for file in files],
    }


@app.post("/api/accounts/export-sub-auths")
def export_account_sub_auths(params: AccountEmailBatchParams):
    """导出所选账号的 Sub2API 导入 JSON。"""
    from autoteam.accounts import ACCOUNT_SOURCE_MANAGED, SEAT_CODEX, STATUS_ACTIVE, find_account, load_accounts, update_account
    from autoteam.sub2api_converter import ConversionError, ExportSettings, export_records, generate_default_filename, inspect_sources

    requested = []
    seen = set()
    for email in params.emails or []:
        normalized = _normalized_email(email)
        if normalized and normalized not in seen:
            seen.add(normalized)
            requested.append(normalized)
    if not requested:
        raise HTTPException(status_code=400, detail="emails 不能为空")

    accounts = load_accounts()
    sources = []
    missing = []
    for email in requested:
        account = find_account(accounts, email)
        if not account:
            missing.append(email)
            continue
        auth_file = _resolve_codex_auth_file(account)
        if not auth_file:
            missing.append(email)
            continue
        path = Path(auth_file)
        try:
            content = read_text(path)
            json.loads(content)
        except Exception as exc:
            logger.warning("[API] Sub auth 导出跳过无效文件: email=%s path=%s error=%s", email, path, exc)
            missing.append(email)
            continue
        sources.append({"email": email, "filename": path.name, "content": content})

    if not sources:
        raise HTTPException(status_code=404, detail="选中的账号没有可转换的 data/auths 认证文件")

    try:
        records = inspect_sources([(item["filename"], item["content"]) for item in sources])
        filename = generate_default_filename()
        payload = export_records(records, ExportSettings(output_filename=filename))
    except ConversionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    valid_filenames = {record.file_name for record in records if record.is_valid and record.selected}
    exported_sources = [item for item in sources if item["filename"] in valid_filenames]
    invalid = [
        {
            "filename": record.file_name,
            "error": record.error_message or record.status_text,
        }
        for record in records
        if not record.is_valid
    ]

    exported_at = time.time()
    exported_emails = []
    for item in exported_sources:
        email = _normalized_email(item.get("email"))
        if not email:
            continue
        update_account(
            email,
            credentials_exported=True,
            credentials_exported_at=exported_at,
        )
        exported_emails.append(email)

    content = json.dumps(payload, ensure_ascii=False, indent=2)
    return {
        "filename": filename,
        "content_type": "application/json",
        "content_base64": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "count": len(payload.get("accounts") or []),
        "missing": missing,
        "invalid": invalid,
        "exported_emails": exported_emails,
        "exported_at": exported_at,
        "files": [{"email": item["email"], "filename": item["filename"]} for item in exported_sources],
    }


@app.post("/api/accounts/convert-session-cpa-auths")
def convert_account_session_cpa_auths(params: AccountSessionCpaConvertParams):
    """直接把 ChatGPT Web auth_session 转成本地 CPA codex auth 文件，不走 Codex OAuth。"""
    from autoteam.accounts import find_account, load_accounts
    from autoteam.session_cpa_converter import SessionConversionError

    requested = []
    seen = set()
    for email in params.emails or []:
        normalized = _normalized_email(email)
        if normalized and normalized not in seen:
            seen.add(normalized)
            requested.append(normalized)
    if not requested:
        raise HTTPException(status_code=400, detail="emails 不能为空")

    accounts = load_accounts()
    converted = []
    missing = []
    invalid = []
    for email in requested:
        account = find_account(accounts, email)
        if not account or _is_main_account_email(email):
            missing.append(email)
            continue
        try:
            result = _convert_account_auth_session_to_cpa_auth(email, account=account)
        except SessionConversionError as exc:
            invalid.append({"email": email, "error": str(exc)})
            continue
        converted.append(result)

    if not converted and not invalid:
        raise HTTPException(status_code=404, detail="选中的账号没有可转换的 auth_session")

    return {
        "converted": len(converted),
        "missing": missing,
        "invalid": invalid,
        "files": [
            {
                "email": item["email"],
                "filename": item["filename"],
                "auth_file": item["auth_file"],
                "id_token_synthetic": item["id_token_synthetic"],
                "refresh_token_present": item["refresh_token_present"],
            }
            for item in converted
        ],
        "accounts": [item["account"] for item in converted if item.get("account")],
    }


def _convert_account_auth_session_to_cpa_auth(
    email: str,
    *,
    account: dict | None = None,
    force_account_type: str | None = None,
) -> dict:
    """把账号已有 auth_session 转成本地 CPA codex auth 文件，并写回账号池。"""
    from autoteam.accounts import (
        ACCOUNT_SOURCE_MANAGED,
        ACCOUNT_TYPE_FREE,
        ACCOUNT_TYPE_PLUS,
        ACCOUNT_TYPE_PRO,
        ACCOUNT_TYPE_TEAM,
        SEAT_CODEX,
        STATUS_ACTIVE,
        find_account,
        load_accounts,
        update_account,
    )
    from autoteam.auth_session_store import load_auth_session
    from autoteam.session_cpa_converter import SessionConversionError, save_cpa_auth_from_session

    normalized_email = _normalized_email(email)
    if not normalized_email:
        raise SessionConversionError("邮箱为空，无法转换 CPA 认证")
    if account is None:
        account = find_account(load_accounts(), normalized_email) or {"email": normalized_email}
    session = load_auth_session(normalized_email)
    if not session:
        raise SessionConversionError(f"未找到 auth_session: {normalized_email}")

    existing_account_type = str(account.get("account_type") or "").strip().lower()
    force_plan_type = ""
    if force_account_type:
        force_plan_type = str(force_account_type or "").strip().lower()
    elif existing_account_type in {ACCOUNT_TYPE_PLUS, ACCOUNT_TYPE_PRO, ACCOUNT_TYPE_TEAM}:
        force_plan_type = existing_account_type

    result = save_cpa_auth_from_session(
        session,
        source_name=normalized_email,
        force_plan_type=force_plan_type,
    )
    converted_plan = str(result.get("plan_type") or "").strip().lower()
    next_account_type = (
        force_account_type
        or (converted_plan if converted_plan in {ACCOUNT_TYPE_FREE, ACCOUNT_TYPE_PLUS, ACCOUNT_TYPE_PRO, ACCOUNT_TYPE_TEAM} else None)
        or account.get("account_type")
    )
    saved = update_account(
        normalized_email,
        auth_file=result["auth_file"],
        account_type=next_account_type,
        seat_type=account.get("seat_type") or SEAT_CODEX,
        status=STATUS_ACTIVE,
        account_source=ACCOUNT_SOURCE_MANAGED,
    )
    return {
        **result,
        "account": _sanitize_account(saved) if saved else None,
    }


@app.post("/api/accounts/export-status")
def update_accounts_export_status(params: AccountExportStatusUpdateParams):
    """批量修改本地账号账密导出状态。"""
    from autoteam.accounts import find_account, load_accounts, update_account

    requested = []
    seen = set()
    for email in params.emails or []:
        normalized = _normalized_email(email)
        if normalized and normalized not in seen:
            seen.add(normalized)
            requested.append(normalized)
    if not requested:
        raise HTTPException(status_code=400, detail="emails 不能为空")

    accounts = load_accounts()
    exported_at = time.time() if params.exported else None
    updated = []
    updated_emails = []
    missing = []
    for email in requested:
        if _is_main_account_email(email):
            missing.append(email)
            continue
        account = find_account(accounts, email)
        if not account:
            missing.append(email)
            continue
        saved = update_account(
            email,
            credentials_exported=bool(params.exported),
            credentials_exported_at=exported_at,
        )
        if saved:
            updated_emails.append(email)
            updated.append(_sanitize_account(saved))
    trade_allocations = {"cleared": 0, "codes": []}
    if not params.exported and updated_emails:
        from autoteam.trade import clear_trade_allocations_for_emails

        trade_allocations = clear_trade_allocations_for_emails(updated_emails)

    return {
        "message": f"已更新 {len(updated)} 个账号导出状态",
        "updated": len(updated),
        "exported": bool(params.exported),
        "exported_at": exported_at,
        "missing": missing,
        "trade_allocations": trade_allocations,
        "accounts": updated,
    }


@app.post("/api/accounts/delete-batch")
def delete_accounts_batch(params: DeleteBatchParams):
    """
    批量删除本地管理账号。整批共享一个 chatgpt_api,
    Team 成员/邀请状态只拉一次；CPA 自动同步已禁用，需要时手动同步。
    不删除临时邮箱服务中的邮箱账号。
    """
    from autoteam.account_ops import delete_managed_account, fetch_team_state
    from autoteam.accounts import load_accounts
    from autoteam.chatgpt_api import ChatGPTTeamAPI
    from autoteam.admin_state import get_admin_session_token, get_chatgpt_account_id
    from autoteam.auth_session_store import delete_auth_session, get_auth_session_file

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

    lock_acquired = _playwright_lock.acquire(blocking=False)

    def _run():
        accounts = load_accounts()
        existing = {(a.get("email") or "").lower(): a for a in accounts}
        remote_cleanup = bool(lock_acquired and get_admin_session_token() and get_chatgpt_account_id())

        chatgpt_api = None
        results = []
        try:
            if remote_cleanup:
                chatgpt_api = ChatGPTTeamAPI()
                chatgpt_api.start()
            # 整批共享一次 Team 状态快照,避免每个删除都重查一次
            remote_state = fetch_team_state(chatgpt_api) if remote_cleanup else None

            for email in emails:
                if email.lower() not in existing and not get_auth_session_file(email):
                    results.append({"email": email, "ok": False, "error": "账号不存在"})
                    if not params.continue_on_error:
                        break
                    continue
                try:
                    cleanup = delete_managed_account(
                        email,
                        remove_remote=remote_cleanup,
                        remove_cloudmail=False,
                        chatgpt_api=chatgpt_api,
                        remote_state=remote_state,
                        sync_cpa_after=False,
                    )
                    cleanup["auth_session_deleted"] = delete_auth_session(email)
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
            logger.info("[批量删除] 自动 CPA 同步已禁用，需要时请手动执行“同步 CPA”")

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
        if not lock_acquired:
            return _run()
        # 每个账号平均 30s (拉取 team 状态 + kick + 清理本地文件),再给 120s 兜底余量。
        # 若仍超时会抛 TimeoutError,worker 线程会在后台继续跑完,但锁会释放 → 用户可以再提。
        timeout = max(300, 30 * len(emails) + 120)
        return _pw_executor.run_with_timeout(timeout, _run)
    finally:
        if lock_acquired:
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


def _run_account_codex_login_once(email: str, acc: dict, *, headless: bool = False, refresh_auth_session: bool = False) -> dict:
    from autoteam.accounts import (
        ACCOUNT_SOURCE_MANAGED,
        ACCOUNT_TYPE_FREE,
        ACCOUNT_TYPE_PLUS,
        ACCOUNT_TYPE_PRO,
        ACCOUNT_TYPE_TEAM,
        STATUS_ACTIVE,
        STATUS_PERSONAL,
        update_account,
    )
    from autoteam.mail import TemporaryEmailClient
    from autoteam.codex_auth import (
        CodexOAuthAccountDeactivated,
        CodexOAuthLoginRequired,
        CodexOAuthPhoneRequired,
        CodexProtocolOAuthError,
        check_codex_quota,
        login_codex_via_auth_session_protocol,
        login_codex_via_browser,
        quota_result_quota_info,
        quota_result_resets_at,
        save_auth_file,
    )
    from autoteam.auth_session_store import load_auth_session

    try:
        from autoteam.account_hub import _restore_luckmail_tokens_for_accounts

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

    mail_provider = str(acc.get("mail_provider") or "").strip().lower()
    if not mail_provider and str(acc.get("cloudmail_account_id") or "").strip().startswith("tok_"):
        mail_provider = "luckmail"
    if mail_provider:
        from autoteam.manager import _temporary_mail_provider

        with _temporary_mail_provider(mail_provider):
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
    use_protocol_oauth = (not refresh_auth_session) and str(os.environ.get("CODEX_OAUTH_USE_AUTH_SESSION_PROTOCOL") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
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
        except CodexOAuthPhoneRequired:
            raise
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
        from autoteam.manager import _fetch_auth_session_from_page, _save_auth_from_session_page

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

    auth_file = save_auth_file(bundle)
    plan_type = (bundle.get("plan_type") or "").lower()
    next_account_type = {
        "free": ACCOUNT_TYPE_FREE,
        "team": ACCOUNT_TYPE_TEAM,
        "plus": ACCOUNT_TYPE_PLUS,
        "pro": ACCOUNT_TYPE_PRO,
    }.get(plan_type, account_type)

    update_account(
        email,
        status=STATUS_ACTIVE,
        account_type=next_account_type,
        auth_file=auth_file,
        last_active_at=time.time(),
    )

    token = bundle.get("access_token")
    account_id = bundle.get("account_id")
    if token and account_id:
        st, info = check_codex_quota(token, account_id=account_id)
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

    logger.info("[账号登录] 自动 CPA 同步已禁用，需要时请手动执行“同步 CPA”")
    result_payload = {
        "email": email,
        "plan": bundle.get("plan_type"),
        "auth_file": auth_file,
        "mode": "native" if native_oauth else "team",
    }
    if refresh_auth_session and auth_session_refresh_outcome.get("auth_session_file"):
        result_payload["auth_session_file"] = auth_session_refresh_outcome.get("auth_session_file")
    return result_payload


def _oauth_phone_required_result(email: str, exc: Exception) -> dict:
    removed = _remove_oauth_phone_required_accounts_from_pool([email])
    return {
        "email": email,
        "status": "failed",
        "failure_stage": "oauth_phone_required",
        "message": f"OAuth 需要手机验证，已从号池删除账号: {email}",
        "error": str(exc),
        "removed_pool_emails": removed,
    }


def _oauth_login_required_result(email: str, exc: Exception) -> dict:
    return {
        "email": email,
        "status": "failed",
        "failure_stage": "oauth_login_required",
        "message": f"OAuth 停在登录页，未获取 authorization code，账号已保留: {email}",
        "error": str(exc),
        "removed_pool_emails": [],
    }


def _oauth_account_deactivated_result(email: str, exc: Exception) -> dict:
    removed = _remove_oauth_account_deactivated_accounts_from_pool([email])
    return {
        "email": email,
        "status": "failed",
        "failure_stage": "oauth_account_deactivated",
        "message": f"OAuth 检测到 account_deactivated，已从号池删除账号: {email}",
        "error": str(exc),
        "removed_pool_emails": removed,
    }


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

    def _run(task_id: str = ""):
        from autoteam.codex_auth import CodexOAuthAccountDeactivated, CodexOAuthLoginRequired, CodexOAuthPhoneRequired

        try:
            _append_task_progress(
                task_id,
                {
                    "stage": "account_login",
                    "email": email,
                    "message": f"正在补登录 {email}",
                },
            )
            return _run_account_codex_login_once(email, acc, headless=False)
        except CodexOAuthPhoneRequired as exc:
            result = _oauth_phone_required_result(email, exc)
            _append_task_progress(
                task_id,
                {
                    "stage": "account_login_phone_required_removed",
                    "email": email,
                    "removed_pool_emails": result["removed_pool_emails"],
                    "message": result["message"],
                    "level": "warn",
                }
            )
            raise TaskResultError(result["message"], task_result=result) from exc
        except CodexOAuthLoginRequired as exc:
            result = _oauth_login_required_result(email, exc)
            _append_task_progress(
                task_id,
                {
                    "stage": "account_login_required",
                    "email": email,
                    "message": result["message"],
                    "level": "warn",
                },
            )
            raise TaskResultError(result["message"], task_result=result) from exc
        except CodexOAuthAccountDeactivated as exc:
            result = _oauth_account_deactivated_result(email, exc)
            _append_task_progress(
                task_id,
                {
                    "stage": "account_login_deactivated_removed",
                    "email": email,
                    "removed_pool_emails": result["removed_pool_emails"],
                    "message": result["message"],
                    "level": "warn",
                },
            )
            raise TaskResultError(result["message"], task_result=result) from exc

    task = _start_task(f"login:{email}", _run, {"email": email}, task_group=TASK_GROUP_OAUTH, pass_task_id=True)
    return task


@app.post("/api/accounts/login-batch", status_code=202)
def post_accounts_login_batch(params: AccountEmailBatchParams):
    """批量触发账号 Codex 补登录（后台并发执行）。"""
    from autoteam.accounts import find_account, load_accounts

    emails = []
    seen = set()
    for item in params.emails or []:
        email = _normalized_email(item)
        if email and email not in seen:
            seen.add(email)
            emails.append(email)
    if not emails:
        raise HTTPException(status_code=400, detail="emails 不能为空")
    if any(_is_main_account_email(email) for email in emails):
        raise HTTPException(status_code=400, detail="主号不属于账号池登录对象")

    account_list = load_accounts()
    accounts_by_email = {}
    missing = []
    for email in emails:
        acc = find_account(account_list, email)
        if not acc:
            missing.append(email)
            continue
        accounts_by_email[email] = acc
    if not accounts_by_email:
        raise HTTPException(status_code=404, detail="账号不存在")

    def _run(task_id: str = ""):
        from autoteam.codex_auth import CodexOAuthAccountDeactivated, CodexOAuthLoginRequired, CodexOAuthPhoneRequired
        from autoteam.accounts import update_account

        ok = []
        failed = []
        phone_required = []
        total = len(accounts_by_email)
        result_lock = threading.Lock()

        missing_mail_ids = [
            email for email, acc in accounts_by_email.items() if not acc.get("cloudmail_account_id")
        ]
        if missing_mail_ids:
            try:
                from autoteam.mail import TemporaryEmailClient

                mail_client = TemporaryEmailClient()
                mail_client.login()
                if hasattr(mail_client, "list_accounts"):
                    rows = mail_client.list_accounts(size=0)
                    by_email = {
                        _normalized_email(row.get("email")): row.get("accountId")
                        for row in rows
                        if row.get("email") and row.get("accountId")
                    }
                    filled = 0
                    for email in missing_mail_ids:
                        account_id = by_email.get(email)
                        if not account_id:
                            continue
                        accounts_by_email[email]["cloudmail_account_id"] = account_id
                        update_account(email, cloudmail_account_id=account_id)
                        filled += 1
                    if filled:
                        _append_task_progress(
                            task_id,
                            {
                                "stage": "account_login_mail_ids_prefilled",
                                "total": total,
                                "filled": filled,
                                "message": f"已预热 {filled} 个邮箱 accountId，后续验证码查询走直查",
                            },
                        )
            except Exception as exc:
                logger.warning("[账号登录] 批量补登录预热 cloud-mail accountId 失败: %s", exc)

        def _run_one(index: int, email: str, acc: dict) -> dict:
            started_at = time.time()
            logger.info(
                "[账号登录] 批量 worker 开始: email=%s index=%s/%s thread=%s",
                email,
                index,
                total,
                threading.current_thread().name,
            )
            _append_task_progress(
                task_id,
                {
                    "stage": "account_login",
                    "email": email,
                    "current": index,
                    "total": total,
                    "ok": len(ok),
                    "failed": len(failed),
                    "message": f"正在补登录 {email} ({index}/{total})",
                }
            )
            try:
                login_result = _run_account_codex_login_once(email, acc, headless=False)
                logger.info(
                    "[账号登录] 批量 worker 成功: email=%s elapsed=%.1fs thread=%s",
                    email,
                    time.time() - started_at,
                    threading.current_thread().name,
                )
                return {"kind": "ok", "email": email, "index": index, "result": login_result}
            except CodexOAuthPhoneRequired as exc:
                result = _oauth_phone_required_result(email, exc)
                logger.warning("[账号登录] 批量 worker 手机验证: email=%s elapsed=%.1fs", email, time.time() - started_at)
                return {"kind": "phone_required", "email": email, "index": index, "result": result}
            except CodexOAuthLoginRequired as exc:
                result = _oauth_login_required_result(email, exc)
                logger.warning("[账号登录] 批量 worker 停在登录页: email=%s elapsed=%.1fs", email, time.time() - started_at)
                return {"kind": "login_required", "email": email, "index": index, "result": result}
            except CodexOAuthAccountDeactivated as exc:
                result = _oauth_account_deactivated_result(email, exc)
                logger.warning("[账号登录] 批量 worker 账号停用: email=%s elapsed=%.1fs", email, time.time() - started_at)
                return {"kind": "account_deactivated", "email": email, "index": index, "result": result}
            except Exception as exc:
                logger.exception("[账号登录] 批量 worker 异常: email=%s elapsed=%.1fs", email, time.time() - started_at)
                return {"kind": "failed", "email": email, "index": index, "error": str(exc), "exception": exc}

        try:
            configured_workers = int(os.environ.get("CODEX_OAUTH_BATCH_CONCURRENCY", "3") or "3")
        except (TypeError, ValueError):
            configured_workers = 3
        max_workers = max(1, min(total, configured_workers))
        logger.info("[账号登录] 批量补登录并发启动: total=%s max_workers=%s", total, max_workers)
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="codex-oauth") as executor:
            future_map = {
                executor.submit(_run_one, index, email, acc): (index, email)
                for index, (email, acc) in enumerate(accounts_by_email.items(), start=1)
            }
            for future in as_completed(future_map):
                item = future.result()
                item_email = item["email"]
                with result_lock:
                    if item["kind"] == "ok":
                        ok.append(item["result"])
                    elif item["kind"] in {"phone_required", "login_required", "account_deactivated"}:
                        if item["kind"] == "phone_required":
                            phone_required.append(item["result"])
                        failed.append(item["result"])
                    else:
                        failed.append({"email": item_email, "error": item["error"]})

                    ok_count = len(ok)
                    failed_count = len(failed)

                if item["kind"] == "ok":
                    _append_task_progress(
                        task_id,
                        {
                            "stage": "account_login_done",
                            "email": item_email,
                            "current": item["index"],
                            "total": total,
                            "ok": ok_count,
                            "failed": failed_count,
                            "message": f"补登录成功: {item_email}",
                        },
                    )
                elif item["kind"] in {"phone_required", "login_required", "account_deactivated"}:
                    stage = {
                        "account_deactivated": "account_login_deactivated_removed",
                        "login_required": "account_login_required",
                    }.get(item["kind"], "account_login_phone_required_removed")
                    _append_task_progress(
                        task_id,
                        {
                            "stage": stage,
                            "email": item_email,
                            "current": item["index"],
                            "total": total,
                            "ok": ok_count,
                            "failed": failed_count,
                            "removed_pool_emails": item["result"].get("removed_pool_emails") or [],
                            "message": item["result"].get("message") or f"OAuth 需要手机验证，已从号池删除账号: {item_email}",
                            "level": "warn",
                        },
                    )
                else:
                    _append_task_progress(
                        task_id,
                        {
                            "stage": "account_login_failed",
                            "email": item_email,
                            "current": item["index"],
                            "total": total,
                            "ok": ok_count,
                            "failed": failed_count,
                            "message": f"补登录失败: {item_email}: {item['error']}",
                        },
                    )
                    exc = item.get("exception")
                    logger.error(
                        "[账号登录] 批量补登录失败: email=%s",
                        item_email,
                        exc_info=(type(exc), exc, getattr(exc, "__traceback__", None)) if exc else None,
                    )

        return {
            "ok": ok,
            "failed": failed,
            "phone_required": phone_required,
            "missing": missing,
            "total": total,
            "concurrency": max_workers,
        }

    task = _start_task("login-batch", _run, {"emails": emails, "missing": missing}, task_group=TASK_GROUP_OAUTH, pass_task_id=True)
    return task


@app.post("/api/accounts/refresh-quota", status_code=202)
def post_accounts_refresh_quota(params: AccountEmailBatchParams):
    """刷新账号额度；emails 为空时默认刷新全部非主号账号，401/403 直接标记为废弃 Fail。"""
    from autoteam.accounts import find_account, load_accounts

    emails = []
    seen = set()
    for item in params.emails or []:
        email = _normalized_email(item)
        if email and email not in seen:
            seen.add(email)
            emails.append(email)

    account_list = load_accounts()
    if not emails:
        for acc in account_list:
            email = _normalized_email(acc.get("email"))
            if (
                email
                and email not in seen
                and not _is_main_account_email(email)
                and str(acc.get("status") or "").strip().lower() != "fail"
            ):
                seen.add(email)
                emails.append(email)

    accounts_by_email = {}
    missing = []
    for email in emails:
        acc = find_account(account_list, email)
        if not acc:
            missing.append(email)
            continue
        accounts_by_email[email] = acc
    if not accounts_by_email:
        raise HTTPException(status_code=404, detail="账号不存在")

    def _run(task_id: str = ""):
        from autoteam.accounts import (
            ACCOUNT_TYPE_FREE,
            STATUS_ACTIVE,
            STATUS_EXHAUSTED,
            STATUS_FAIL,
            STATUS_PERSONAL,
            STATUS_PLUS,
            STATUS_STANDBY,
            update_account,
        )
        from autoteam.codex_auth import check_codex_quota, quota_result_quota_info, quota_result_resets_at

        ok = []
        exhausted = []
        failed = []
        skipped = []
        network_error = []
        total = len(accounts_by_email)
        completed = 0
        progress_lock = threading.Lock()
        update_lock = threading.Lock()

        def _int_env(name: str, default: int, *, minimum: int = 0, maximum: int = 9999) -> int:
            try:
                value = int(os.environ.get(name, str(default)) or default)
            except (TypeError, ValueError):
                value = default
            return max(minimum, min(maximum, value))

        max_workers = min(total, _int_env("REFRESH_QUOTA_CONCURRENCY", 8, minimum=1, maximum=32))
        retry_count = _int_env("REFRESH_QUOTA_RETRIES", 1, minimum=0, maximum=5)
        account_timeout = _int_env("REFRESH_QUOTA_ACCOUNT_TIMEOUT", 25, minimum=10, maximum=60)

        _append_task_progress(
            task_id,
            {
                "stage": "refresh_quota_started",
                "current": 0,
                "total": total,
                "ok": 0,
                "failed": 0,
                "skipped": 0,
                "network_error": 0,
                "concurrency": max_workers,
                "retry_count": retry_count,
                "account_timeout": account_timeout,
                "message": f"开始并发刷新凭证: {total} 个账号，并发 {max_workers}，超时 {account_timeout}s，失败重试 {retry_count} 次",
            },
        )

        def _emit(progress: dict):
            with progress_lock:
                _append_task_progress(task_id, progress)

        def _run_one(index: int, email: str, acc: dict) -> dict:
            _emit(
                {
                    "stage": "refresh_quota_account",
                    "email": email,
                    "current": completed,
                    "account_index": index,
                    "total": total,
                    "ok": len(ok),
                    "failed": len(failed),
                    "skipped": len(skipped),
                    "network_error": len(network_error),
                    "message": f"正在刷新账号额度: {email} ({index}/{total})",
                }
            )
            if _is_main_account_email(email):
                return {"kind": "skipped", "email": email, "index": index, "reason": "main_account", "message": f"跳过主账号: {email}"}
            if str(acc.get("status") or "").strip().lower() == STATUS_FAIL:
                return {"kind": "skipped", "email": email, "index": index, "reason": "fail_account", "message": f"跳过废弃账号: {email}"}

            auth_file = _resolve_status_auth_file(acc)
            if not auth_file:
                return {"kind": "skipped", "email": email, "index": index, "reason": "missing_auth_file", "message": f"跳过 {email}: 缺少认证文件"}

            try:
                auth_data = json.loads(read_text(Path(auth_file)))
            except Exception as exc:
                return {
                    "kind": "skipped",
                    "email": email,
                    "index": index,
                    "reason": "invalid_auth_file",
                    "error": str(exc),
                    "message": f"跳过 {email}: 认证文件无法读取",
                }

            access_token = str(auth_data.get("access_token") or "").strip()
            if not access_token:
                return {
                    "kind": "skipped",
                    "email": email,
                    "index": index,
                    "reason": "missing_access_token",
                    "message": f"跳过 {email}: 认证文件缺少 access_token",
                }

            now_ts = time.time()
            attempts = 0
            status = "network_error"
            info = None
            for attempt in range(retry_count + 1):
                attempts = attempt + 1
                status, info = check_codex_quota(
                    access_token,
                    account_id=_account_id_from_auth_data(auth_data) or None,
                    timeout=account_timeout,
                )
                if status != "network_error" or attempt >= retry_count:
                    break
                _emit(
                    {
                        "stage": "refresh_quota_retry",
                        "email": email,
                        "current": completed,
                        "account_index": index,
                        "total": total,
                        "attempt": attempts,
                        "retry_count": retry_count,
                        "message": f"刷新凭证临时失败，准备重试: {email} ({attempts}/{retry_count + 1})",
                        "level": "warn",
                    },
                )

            current_status = str(acc.get("status") or "").strip().lower()
            account_type = str(acc.get("account_type") or "").strip().lower()
            is_free_personal_account = account_type == ACCOUNT_TYPE_FREE or current_status == STATUS_PERSONAL
            recoverable_free_statuses = {"", STATUS_ACTIVE, STATUS_EXHAUSTED, STATUS_PERSONAL, "pending", "session_only"}

            if status == "ok":
                update_payload = {"last_quota": info, "last_quota_check_at": now_ts}
                if account_type == ACCOUNT_TYPE_FREE and current_status in recoverable_free_statuses:
                    update_payload["status"] = STATUS_PERSONAL
                elif (acc.get("status") or "") not in {STATUS_PERSONAL, STATUS_PLUS, STATUS_STANDBY}:
                    update_payload["status"] = STATUS_ACTIVE
                with update_lock:
                    update_account(email, **update_payload)
                return {"kind": "ok", "email": email, "index": index, "quota": info, "attempts": attempts, "message": f"额度刷新成功: {email}"}

            if status == "exhausted":
                quota_info = quota_result_quota_info(info) or {}
                update_payload = {
                    "quota_exhausted_at": now_ts,
                    "quota_resets_at": quota_result_resets_at(info) or int(now_ts + 18000),
                    "last_quota_check_at": now_ts,
                }
                if quota_info:
                    update_payload["last_quota"] = quota_info
                if is_free_personal_account:
                    if account_type == ACCOUNT_TYPE_FREE and current_status in recoverable_free_statuses:
                        update_payload["status"] = STATUS_PERSONAL
                else:
                    update_payload["status"] = STATUS_EXHAUSTED
                with update_lock:
                    update_account(email, **update_payload)
                return {
                    "kind": "exhausted",
                    "email": email,
                    "index": index,
                    "quota": quota_info,
                    "info": info,
                    "attempts": attempts,
                    "message": (
                        f"个人 Free 额度已用完，仅记录额度快照: {email}"
                        if is_free_personal_account
                        else f"额度已用完: {email}"
                    ),
                }

            if status == "auth_error":
                update_payload = {
                    "status": STATUS_FAIL,
                    "discarded_at": now_ts,
                    "discarded_reason": "quota_refresh_401",
                    "last_quota_check_at": now_ts,
                    "last_bind_status": "failed",
                    "last_bind_failure_stage": "auth_401",
                    "last_bind_message": "刷新额度返回 401/403，账号已标记为 Fail/废弃",
                }
                with update_lock:
                    update_account(email, **update_payload)
                return {
                    "kind": "failed",
                    "email": email,
                    "index": index,
                    "reason": "auth_error",
                    "attempts": attempts,
                    "message": f"刷新额度返回 401/403，已标记 Fail/废弃: {email}",
                }

            return {
                "kind": "network_error",
                "email": email,
                "index": index,
                "reason": status,
                "attempts": attempts,
                "message": f"刷新额度遇到临时错误，未改状态: {email}",
            }

        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="quota-refresh") as executor:
            future_map = {
                executor.submit(_run_one, index, email, acc): (index, email)
                for index, (email, acc) in enumerate(accounts_by_email.items(), start=1)
            }
            for future in as_completed(future_map):
                index, email = future_map[future]
                try:
                    item = future.result()
                except Exception as exc:
                    item = {
                        "kind": "network_error",
                        "email": email,
                        "index": index,
                        "reason": "exception",
                        "error": str(exc),
                        "attempts": 1,
                        "message": f"刷新凭证异常，未改状态: {email}: {exc}",
                    }
                    logger.exception("[刷新凭证] worker 异常: email=%s", email)

                completed += 1
                kind = item.get("kind")
                if kind == "ok":
                    ok.append({"email": item["email"], "quota": item.get("quota"), "attempts": item.get("attempts", 1)})
                    stage = "refresh_quota_done"
                    level = "info"
                elif kind == "exhausted":
                    exhausted.append({"email": item["email"], "quota": item.get("quota") or {}, "info": item.get("info")})
                    stage = "refresh_quota_exhausted"
                    level = "warn"
                elif kind == "failed":
                    failed.append({"email": item["email"], "reason": item.get("reason") or "failed"})
                    stage = "refresh_quota_auth_failed"
                    level = "error"
                elif kind == "skipped":
                    skipped_item = {
                        "email": item["email"],
                        "reason": item.get("reason") or "skipped",
                    }
                    if item.get("error"):
                        skipped_item["error"] = item.get("error")
                    skipped.append(skipped_item)
                    stage = "refresh_quota_skipped"
                    level = "warn"
                else:
                    network_error.append({"email": item.get("email") or email, "reason": item.get("reason") or "network_error"})
                    stage = "refresh_quota_network_error"
                    level = "warn"

                _append_task_progress(
                    task_id,
                    {
                        "stage": stage,
                        "email": item.get("email") or email,
                        "current": completed,
                        "account_index": item.get("index") or index,
                        "total": total,
                        "ok": len(ok),
                        "failed": len(failed),
                        "exhausted": len(exhausted),
                        "skipped": len(skipped),
                        "network_error": len(network_error),
                        "attempts": item.get("attempts", 1),
                        "message": item.get("message") or f"刷新凭证完成: {email}",
                        "level": level,
                    },
                )

        return {
            "ok": ok,
            "exhausted": exhausted,
            "failed": failed,
            "skipped": skipped,
            "network_error": network_error,
            "missing": missing,
            "total": total,
            "concurrency": max_workers,
            "retry_count": retry_count,
            "account_timeout": account_timeout,
        }

    task = _start_task(
        "refresh-quota",
        _run,
        {"emails": emails, "missing": missing},
        task_group=TASK_GROUP_QUOTA,
        pass_task_id=True,
    )
    return task


@app.get("/api/status")
def get_status(include_session_stubs: bool = True):
    """获取所有账号状态。

    不在页面读取路径里批量请求 Codex quota。真实账号较多时逐个实时探测会让
    仪表盘卡死；额度刷新应走 /api/accounts/refresh-quota 后台任务，状态页只读取
    已持久化的 last_quota 快照。
    """
    from autoteam.accounts import (
        STATUS_ACTIVE,
        STATUS_AUTH_INVALID,
        STATUS_EXHAUSTED,
        STATUS_FAIL,
        STATUS_ORPHAN,
        STATUS_PENDING,
        STATUS_STANDBY,
    )

    accounts = _load_accounts_with_session_stubs(include_session_stubs=include_session_stubs)
    quota_cache = {
        acc["email"]: acc.get("last_quota")
        for acc in accounts
        if isinstance(acc.get("last_quota"), dict) and acc.get("email")
    }

    sanitized_accounts = _sanitize_accounts_batch(accounts, quota_cache)

    summary = {
        "active": sum(1 for a in sanitized_accounts if a["status"] == STATUS_ACTIVE),
        "standby": sum(1 for a in sanitized_accounts if a["status"] == STATUS_STANDBY),
        "exhausted": sum(1 for a in sanitized_accounts if a["status"] == STATUS_EXHAUSTED),
        "pending": sum(1 for a in sanitized_accounts if a["status"] == STATUS_PENDING),
        "auth_invalid": sum(1 for a in sanitized_accounts if a["status"] == STATUS_AUTH_INVALID),
        "orphan": sum(1 for a in sanitized_accounts if a["status"] == STATUS_ORPHAN),
        "fail": sum(1 for a in sanitized_accounts if a["status"] == STATUS_FAIL),
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


@app.get("/api/account-hub/config")
def get_account_hub_config():
    from autoteam.account_hub import get_config

    return get_config()


@app.put("/api/account-hub/config")
def put_account_hub_config(params: AccountHubConfigParams):
    from autoteam.account_hub import set_config

    saved = set_config(params.model_dump())
    return {"message": "远程账号 Hub 配置已保存", "config": saved}


@app.post("/api/account-hub/test")
def post_account_hub_test(params: AccountHubConfigParams):
    from autoteam.account_hub import test_connection

    try:
        result = test_connection(params.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@app.post("/api/account-hub/sync")
def post_account_hub_sync(params: AccountHubSyncParams):
    from autoteam.account_hub import upload_to_hub

    emails = [_normalized_email(email) for email in (params.emails or []) if _normalized_email(email)]
    if not emails:
        raise HTTPException(status_code=400, detail="请选择要同步到账号 Hub 的账号")
    try:
        result = upload_to_hub(selected_emails=emails)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


def _require_account_hub_token(request: Request):
    from autoteam.account_hub import expected_inbound_token

    expected = expected_inbound_token()
    if not expected:
        raise HTTPException(status_code=403, detail="账号 Hub Token 未配置")
    token = request.headers.get("x-account-hub-token", "")
    if token != expected:
        raise HTTPException(status_code=401, detail="账号 Hub Token 无效")


@app.post("/api/account-hub/ping")
def post_account_hub_ping(request: Request):
    _require_account_hub_token(request)
    return {"ok": True, "message": "账号 Hub 连接成功", "time": time.time()}


@app.post("/api/account-hub/ingest")
def post_account_hub_ingest(request: Request, payload: AccountHubIngestPayload):
    _require_account_hub_token(request)
    from autoteam.account_hub import receive_payload

    try:
        return receive_payload(payload.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _trade_http_error(exc: Exception):
    from autoteam.trade import TradeError

    if isinstance(exc, TradeError):
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/trade/summary")
def get_trade_summary():
    from autoteam.trade import inventory_summary

    try:
        return inventory_summary()
    except Exception as exc:
        _trade_http_error(exc)


@app.get("/api/trade/cdks")
def get_trade_cdks(limit: int = 200):
    from autoteam.trade import list_cdks

    try:
        return {"items": list_cdks(limit=limit)}
    except Exception as exc:
        _trade_http_error(exc)


@app.post("/api/trade/cdks")
def post_trade_cdk(params: TradeCreateCdkParams):
    from autoteam.trade import create_cdk

    try:
        return create_cdk(params.quota_total, note=params.note)
    except Exception as exc:
        _trade_http_error(exc)


@app.get("/api/trade/cdks/{code}")
def get_trade_cdk(code: str):
    from autoteam.trade import get_cdk

    try:
        return get_cdk(code)
    except Exception as exc:
        _trade_http_error(exc)


@app.post("/api/trade/cdks/{code}/revoke")
def post_trade_cdk_revoke(code: str):
    from autoteam.trade import revoke_cdk

    try:
        return revoke_cdk(code)
    except Exception as exc:
        _trade_http_error(exc)


@app.post("/api/public/plus-extractor/redeem")
def post_public_plus_extractor_redeem(params: TradeRedeemParams):
    from autoteam.trade import redeem_cdk

    try:
        return redeem_cdk(params.code, params.password, params.count, params.formats or params.format)
    except Exception as exc:
        _trade_http_error(exc)


@app.post("/api/public/plus-extractor/query")
def post_public_plus_extractor_query(params: TradeQueryParams):
    from autoteam.trade import query_cdk_remaining

    try:
        return query_cdk_remaining(params.code, params.password)
    except Exception as exc:
        _trade_http_error(exc)


@app.post("/api/public/plus-extractor/set-password")
def post_public_plus_extractor_set_password(params: TradeSetPasswordParams):
    from autoteam.trade import set_cdk_password

    try:
        return set_cdk_password(params.code, params.password)
    except Exception as exc:
        _trade_http_error(exc)


@app.post("/api/public/plus-extractor/cdk-status")
def post_public_plus_extractor_cdk_status(params: TradeCdkStatusParams):
    from autoteam.trade import public_cdk_status

    try:
        return public_cdk_status(params.code)
    except Exception as exc:
        _trade_http_error(exc)


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
    access_token = _normalize_access_token(params.access_token)
    if not access_token:
        raise HTTPException(status_code=400, detail="请提供 access_token")
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

    try:
        try:
            result = _generate_checkout_link(access_token, payload)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("[bind/link] unexpected error")
            raise HTTPException(status_code=500, detail=f"生成绑卡链接失败: {exc}") from exc
        return result
    finally:
        pass


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


@app.get("/api/whatsapp-otp/status")
def get_whatsapp_otp_status():
    from autoteam.whatsapp_otp import get_default_listener

    return get_default_listener().status()


@app.post("/api/whatsapp-otp/start")
def post_whatsapp_otp_start(params: WhatsAppOtpStartParams = WhatsAppOtpStartParams()):
    from autoteam.whatsapp_otp import DEFAULT_ADB_PATH, DEFAULT_PROFILE_DIR, WhatsAppOtpListener, get_default_listener

    global _whatsapp_otp_listener
    profile_dir = Path(params.profile_dir).expanduser() if str(params.profile_dir or "").strip() else DEFAULT_PROFILE_DIR
    adb_path = str(params.adb_path or "").strip()
    adb_serial = str(params.adb_serial or "").strip()
    adb_port = re.sub(r"\D+", "", str(params.adb_port or ""))
    if not adb_serial and adb_port:
        adb_serial = f"emulator-{adb_port}"
    requested_adb_path = adb_path or DEFAULT_ADB_PATH
    poll_interval_seconds = float(params.poll_interval_seconds or 2.0)
    listener = get_default_listener()
    if (
        str(listener.profile_dir) != str(profile_dir)
        or listener.headless != bool(params.headless)
        or getattr(listener, "adb_path", "") != requested_adb_path
        or getattr(listener, "adb_serial", "") != adb_serial
        or float(getattr(listener, "poll_interval_seconds", 2.0)) != poll_interval_seconds
    ):
        listener.stop()
        _whatsapp_otp_listener = WhatsAppOtpListener(
            profile_dir=profile_dir,
            headless=bool(params.headless),
            adb_path=requested_adb_path,
            adb_serial=adb_serial,
            poll_interval_seconds=poll_interval_seconds,
        )
        listener = _whatsapp_otp_listener
        import autoteam.whatsapp_otp as whatsapp_otp_module

        whatsapp_otp_module._DEFAULT_LISTENER = listener
    return listener.start()


@app.post("/api/whatsapp-otp/stop")
def post_whatsapp_otp_stop():
    from autoteam.whatsapp_otp import get_default_listener

    return get_default_listener().stop()


@app.post("/api/whatsapp-otp/clear")
def post_whatsapp_otp_clear():
    from autoteam.whatsapp_otp import get_default_listener

    return get_default_listener().clear()


@app.get("/api/whatsapp-otp/latest")
def get_whatsapp_otp_latest(max_age_seconds: int = 600):
    from autoteam.whatsapp_otp import get_default_listener

    return get_default_listener().latest_response(max_age_seconds=max_age_seconds)


@app.get("/otp/whatsapp/latest")
def get_whatsapp_otp_latest_public(max_age_seconds: int = 600):
    """Local, auth-free OTP endpoint compatible with existing GoPay sms_url polling."""
    from autoteam.whatsapp_otp import get_default_listener

    return get_default_listener().latest_response(max_age_seconds=max_age_seconds)


@app.get("/otp/gopay-signup/{bridge_token}")
def get_gopay_signup_otp_public(bridge_token: str, resend: bool = False):
    """Local, auth-free OTP endpoint for auto-registered GoPay wallets."""
    from autoteam.gopay_auto_register import get_sms_bridge_payload

    try:
        return get_sms_bridge_payload(bridge_token, resend=resend)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="GoPay OTP bridge 不存在或已关闭") from exc


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


class CpaToSub2ApiSource(BaseModel):
    filename: str
    content: str


class CpaToSub2ApiProxyParams(BaseModel):
    enabled: bool = False
    name: str = "批量导入代理"
    protocol: str = "http"
    host: str = ""
    port: int = 7890
    username: str = ""
    password: str = ""
    status: str = "active"


class CpaToSub2ApiSettingsParams(BaseModel):
    output_dir: str = ""
    output_filename: str = ""
    concurrency: int = 10
    priority: int = 1
    rate_multiplier: float = 1.0
    auto_pause_on_expired: bool = True
    proxy: CpaToSub2ApiProxyParams = CpaToSub2ApiProxyParams()


class CpaToSub2ApiInspectParams(BaseModel):
    files: list[CpaToSub2ApiSource]


class CpaToSub2ApiConvertParams(BaseModel):
    files: list[CpaToSub2ApiSource]
    selected_filenames: list[str] | None = None
    settings: CpaToSub2ApiSettingsParams = CpaToSub2ApiSettingsParams()


class CpaToSub2ApiOpenDirParams(BaseModel):
    output_dir: str


class CpaToSub2ApiSelectDirParams(BaseModel):
    current_dir: str = ""


def _default_cpa_to_sub2api_output_dir() -> Path:
    desktop = Path.home() / "Desktop"
    return desktop if desktop.exists() and desktop.is_dir() else Path.home()


def _sub2api_record_to_dict(record):
    return {
        "file_name": record.file_name,
        "selected": record.selected,
        "is_valid": record.is_valid,
        "variant": record.variant,
        "email": record.email,
        "target_name": record.target_name,
        "plan_type": record.plan_type,
        "status_text": record.status_text,
        "error_message": record.error_message,
    }


def _sub2api_settings_from_params(params: CpaToSub2ApiSettingsParams):
    from autoteam.sub2api_converter import ExportSettings, ProxyConfig, generate_default_filename

    proxy = ProxyConfig(**params.proxy.model_dump())
    return ExportSettings(
        output_filename=params.output_filename.strip() or generate_default_filename(),
        concurrency=params.concurrency,
        priority=params.priority,
        rate_multiplier=params.rate_multiplier,
        auto_pause_on_expired=params.auto_pause_on_expired,
        proxy=proxy,
    )


def _write_cpa_to_sub2api_output(output_dir: str, filename: str, content: str) -> str:
    directory_text = output_dir.strip()
    directory = Path(directory_text).expanduser() if directory_text else _default_cpa_to_sub2api_output_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        if not directory.is_dir():
            raise OSError("输出路径不是目录")
        output_path = directory / filename
        output_path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"无法写入输出文件：{exc}") from exc
    return str(output_path.resolve())


@app.post("/api/cpa-to-sub2api/inspect")
def inspect_cpa_to_sub2api(params: CpaToSub2ApiInspectParams):
    """检查 CPA JSON 文件是否可转换为 Sub2API 导入格式。"""
    from autoteam.sub2api_converter import inspect_sources

    records = inspect_sources([(item.filename, item.content) for item in params.files])
    return {
        "records": [_sub2api_record_to_dict(record) for record in records],
        "total": len(records),
        "valid": sum(1 for record in records if record.is_valid),
        "invalid": sum(1 for record in records if not record.is_valid),
    }


@app.post("/api/cpa-to-sub2api/convert")
def convert_cpa_to_sub2api(params: CpaToSub2ApiConvertParams):
    """将 CPA JSON 批量转换为 Sub2API 账号导入 JSON。"""
    from autoteam.sub2api_converter import ConversionError, export_records, inspect_sources, validate_output_filename

    try:
        records = inspect_sources([(item.filename, item.content) for item in params.files])
        settings = _sub2api_settings_from_params(params.settings)
        selected = set(params.selected_filenames or []) if params.selected_filenames is not None else None
        payload = export_records(records, settings, selected_file_names=selected)
        filename = validate_output_filename(settings.output_filename)
    except ConversionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    content = json.dumps(payload, ensure_ascii=False, indent=2)
    output_path = _write_cpa_to_sub2api_output(params.settings.output_dir, filename, content)
    return {
        "filename": filename,
        "content": content,
        "output_path": output_path,
        "payload": payload,
        "records": [_sub2api_record_to_dict(record) for record in records],
        "total": len(records),
        "converted": len(payload.get("accounts") or []),
        "invalid": sum(1 for record in records if not record.is_valid),
    }


@app.post("/api/cpa-to-sub2api/open-output-dir")
def open_cpa_to_sub2api_output_dir(params: CpaToSub2ApiOpenDirParams):
    """打开 Sub2API 转换输出目录。"""
    directory_text = params.output_dir.strip()
    if not directory_text:
        raise HTTPException(status_code=400, detail="输出目录不能为空")
    directory = Path(directory_text).expanduser()
    if not directory.exists() or not directory.is_dir():
        raise HTTPException(status_code=404, detail="输出目录不存在")
    try:
        if os.name == "nt":
            os.startfile(str(directory.resolve()))  # type: ignore[attr-defined]
        else:
            import subprocess

            subprocess.Popen(["xdg-open", str(directory.resolve())])
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"打开输出目录失败：{exc}") from exc
    return {"message": "已打开输出目录"}


@app.get("/api/cpa-to-sub2api/default-output-dir")
def get_cpa_to_sub2api_default_output_dir():
    """获取默认 Sub2API 转换输出目录。"""
    return {"output_dir": str(_default_cpa_to_sub2api_output_dir())}


@app.post("/api/cpa-to-sub2api/select-output-dir")
def select_cpa_to_sub2api_output_dir(params: CpaToSub2ApiSelectDirParams):
    """弹出本机目录选择框并返回完整输出目录。"""
    try:
        import tkinter as tk
        from tkinter import filedialog

        initial_dir = Path(params.current_dir.strip()).expanduser()
        if not initial_dir.exists() or not initial_dir.is_dir():
            initial_dir = Path.cwd()

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(
            title="选择输出目录",
            initialdir=str(initial_dir),
            mustexist=False,
            parent=root,
        )
        root.destroy()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"选择输出目录失败：{exc}") from exc
    return {"output_dir": selected or ""}


# ---------------------------------------------------------------------------
# 后台任务端点
# ---------------------------------------------------------------------------


class CheckParams(BaseModel):
    include_standby: bool = False  # True 时额外探测 standby 池(限速+24h 去重)


class TaskControlParams(BaseModel):
    task_id: str = ""
    task_group: str = ""


def _find_control_task(params: TaskControlParams | None, *, default_group: str | None = None, command: str | None = None) -> dict:
    requested_id = str((params.task_id if params else "") or "").strip()
    if requested_id:
        task = _tasks.get(requested_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        return task

    requested_group = str((params.task_group if params else "") or default_group or "").strip()
    if requested_group:
        task = _running_task_for_group(requested_group)
        if task:
            return task

    running = [
        task
        for task in _tasks.values()
        if task.get("status") in ("running", "pending")
        and (not command or task.get("command") == command)
        and (not requested_group or task.get("task_group") == requested_group)
    ]
    if not running:
        raise HTTPException(status_code=404, detail="当前没有正在运行的任务")
    return sorted(running, key=lambda item: item.get("started_at") or item.get("created_at") or 0, reverse=True)[0]


@app.post("/api/tasks/bind-card", status_code=202)
def post_bind_card_task(params: BindCardTaskParams):
    from autoteam import cancel_signal
    from autoteam.accounts import (
        ACCOUNT_SOURCE_MANAGED,
        ACCOUNT_TYPE_PLUS,
        SEAT_CODEX,
        STATUS_ACTIVE,
        add_account,
        ensure_session_only_account,
        find_account,
        load_accounts,
        update_account,
    )
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
            account = ensure_session_only_account(email) or _session_only_account_stub(email)
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
        task_id = _current_task_id_for_group() or ""
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

            _append_task_progress(
                task_id,
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

        _append_task_progress(
            task_id,
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

    task = _start_task("bind-card", _run, params.model_dump(), task_group=TASK_GROUP_BIND_CARD)
    return task


@app.post("/api/tasks/gopay-bind", status_code=202)
def post_gopay_bind_task(params: GoPayBindTaskParams, request: Request = None):
    from autoteam import cancel_signal
    from autoteam.accounts import (
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
    from autoteam.auth_session_store import get_auth_session_file
    from autoteam.bind_audit import record_bind_audit
    from autoteam.config import normalize_proxy_url
    from autoteam.gopay_executor import (
        _compact_log_text,
        _looks_like_gopay_rate_limit_text,
        _gopay_pending_retry_reason,
        _gopay_pending_retry_source_stage,
        _safe_email_summary,
        _safe_phone_summary,
        _safe_proxy_summary,
        _safe_url_summary,
        run_gopay_bind_task,
    )

    email = _normalized_email(params.email)
    gopay_task_public_base_url = _request_public_base_url(request)
    auto_register = bool(params.auto_register)
    gopay_auto_signup = bool(params.gopay_auto_signup)
    gopay_auto_signup_env_config = _gopay_auto_signup_env()
    gopay_auto_signup_sms_provider = _normalize_gopay_auto_signup_sms_provider(
        params.gopay_auto_signup_sms_provider
        or gopay_auto_signup_env_config.get("provider")
        or "smscloud"
    )
    gopay_auto_signup_hero_sms_config = {
        "api_key": str(params.gopay_auto_signup_hero_sms_api_key or "").strip(),
        "base_url": str(params.gopay_auto_signup_hero_sms_base_url or "").strip(),
        "country": str(params.gopay_auto_signup_hero_sms_country or "").strip(),
        "service": str(params.gopay_auto_signup_hero_sms_service or "").strip(),
        "timeout_sec": str(params.gopay_auto_signup_hero_sms_timeout or "").strip(),
        "max_price": str(params.gopay_auto_signup_hero_sms_max_price or "").strip(),
    }
    gopay_auto_signup_smscloud_config = {
        "base_url": str(params.gopay_auto_signup_smscloud_base_url or "").strip(),
        "country": str(params.gopay_auto_signup_smscloud_country or "").strip(),
        "service": str(params.gopay_auto_signup_smscloud_service or "").strip(),
        "max_price": str(params.gopay_auto_signup_smscloud_max_price or "").strip(),
        "timeout_sec": str(params.gopay_auto_signup_smscloud_timeout or "").strip(),
    }
    requested_signup_mode = _normalize_gopay_auto_signup_mode(
        getattr(params, "gopay_auto_signup_mode", "")
        or gopay_auto_signup_env_config.get("signup_mode")
        or "http"
    )
    gopay_auto_signup_appium_config = {
        "signup_mode": requested_signup_mode,
        "appium_url": str(
            getattr(params, "gopay_appium_url", "")
            or gopay_auto_signup_env_config.get("appium_url")
            or ""
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
        pending_retry_attempts = max(0, min(3, int(params.pending_retry_attempts if params.pending_retry_attempts is not None else 1)))
    except Exception:
        pending_retry_attempts = 1
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
                "curl: (6)",
                "curl: (7)",
                "curl: (28)",
                "curl: (35)",
                "curl: (56)",
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
            raise HTTPException(status_code=400, detail="phone_accounts 每项都必须填写 phone_number、sms_url、gopay_pin")
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
    if not phone_accounts and (phone_number or sms_url or gopay_pin):
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
    from autoteam.setup_wizard import get_mail_provider

    auto_register_mail_provider = get_mail_provider(params.auto_register_mail_provider) if params.auto_register_mail_provider else ""
    auto_register_luckmail_email_type = str(params.auto_register_luckmail_email_type or "").strip()
    auto_register_luckmail_preferred_domain = str(params.auto_register_luckmail_preferred_domain or "").strip().lstrip("@")
    auto_register_luckmail_preferred_domains = []
    seen_luckmail_domains = set()
    for raw_domain in list(params.auto_register_luckmail_preferred_domains or []) + ([auto_register_luckmail_preferred_domain] if auto_register_luckmail_preferred_domain else []):
        cleaned = str(raw_domain or "").strip().lstrip("@")
        key = cleaned.lower()
        if key in seen_luckmail_domains:
            continue
        seen_luckmail_domains.add(key)
        auto_register_luckmail_preferred_domains.append(cleaned)
    proxy_url = str(params.proxy_url or "").strip()
    try:
        normalized_proxy_url = normalize_proxy_url(proxy_url) if proxy_url else ""
        proxy_config_state = "enabled" if normalized_proxy_url else "disabled"
        proxy_config_error = ""
    except Exception as exc:
        normalized_proxy_url = ""
        proxy_config_state = "invalid"
        proxy_config_error = _compact_log_text(exc, limit=160)
    bind_proxy_url = proxy_url

    if normalized_proxy_url.lower().startswith(("socks4://", "socks5://", "socks5h://")):
        # SOCKS proxies are only needed for GoPay wallet signup/PIN setup.
        bind_proxy_url = ""

    if auto_register and checkout_url:
        raise HTTPException(status_code=400, detail="自动注册模式不支持手动 checkout 链接")
    if not auto_register and not email:
        raise HTTPException(status_code=400, detail="email 不能为空")
    auto_register_domains: list[str] = []
    if auto_register:
        from autoteam.runtime_config import get_register_domain, get_register_domains

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
    logger.info(
        "[gopay-bind] task submitted: email=%s auto_register=%s auto_register_count=%s gopay_auto_signup=%s account_count=%s pending_retry_attempts=%s checkout=%s checkout_mode=%s phone=%s proxy_label=%s proxy_state=%s proxy=%s proxy_error=%s timeout=%s",
        _safe_email_summary(email) if email else "<auto-register>",
        auto_register,
        auto_register_count,
        gopay_auto_signup,
        len(account_emails) if account_emails else 1,
        pending_retry_attempts,
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
                    candidate = ensure_session_only_account(candidate_email) or _session_only_account_stub(candidate_email)
                    accounts = load_accounts()
                else:
                    raise HTTPException(status_code=404, detail=f"批量账号不存在: {candidate_email}")
            if not _resolve_status_auth_file(candidate):
                raise HTTPException(status_code=400, detail=f"批量账号缺少可用 auth_session/auth_file: {candidate_email}")

    skip_current_signal = threading.Event()

    def _run():
        nonlocal email, account_emails
        task_id = _current_task_id_for_group() or ""
        started_at = time.time()
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

        def _gopay_success_progress_fields() -> dict:
            successful_list = sorted(realtime_successful_emails)
            return {
                "successful": len(successful_list),
                "successful_emails": successful_list,
            }

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
                account_exists_after_update = bool(updated_account) or bool(find_account(load_accounts(), success_email))
            if updated_account or account_exists_after_update:
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
                if success_email in session_cpa_scheduled_emails:
                    return _gopay_success_progress_fields()
                session_cpa_scheduled_emails.add(success_email)
                _append_task_progress(
                    task_id,
                    {
                        "stage": "gopay_session_cpa_convert_started",
                        "email": success_email,
                        "message": f"GoPay 绑定成功，正在直接转换 CPA 认证: {success_email}",
                    },
                )
                try:
                    cpa_result = _convert_account_auth_session_to_cpa_auth(
                        success_email,
                        force_account_type=ACCOUNT_TYPE_PLUS,
                    )
                    session_cpa_converted_emails.append(success_email)
                    _append_task_progress(
                        task_id,
                        {
                            "stage": "gopay_session_cpa_convert_done",
                            "email": success_email,
                            "auth_file": cpa_result.get("auth_file") or "",
                            "filename": cpa_result.get("filename") or "",
                            "id_token_synthetic": bool(cpa_result.get("id_token_synthetic")),
                            **_gopay_success_progress_fields(),
                            "message": f"CPA 认证已生成: {success_email}",
                            "level": "success",
                        },
                    )
                    logger.info(
                        "[gopay-bind] CPA auth converted from auth_session after GoPay success: task_id=%s email=%s auth_file=%s",
                        task_id[:8] or "<unknown>",
                        _safe_email_summary(success_email),
                        cpa_result.get("auth_file") or "",
                    )
                except Exception as exc:
                    session_cpa_failed_auths.append({"email": success_email, "error": str(exc)})
                    _append_task_progress(
                        task_id,
                        {
                            "stage": "gopay_session_cpa_convert_failed",
                            "email": success_email,
                            **_gopay_success_progress_fields(),
                            "message": f"CPA 认证转换失败，GoPay 绑定已成功: {success_email}: {exc}",
                            "level": "warn",
                        },
                    )
                    logger.warning(
                        "[gopay-bind] CPA auth conversion after GoPay success failed: task_id=%s email=%s error=%s",
                        task_id[:8] or "<unknown>",
                        _safe_email_summary(success_email),
                        exc,
                    )
                return _gopay_success_progress_fields()

            if success_email in oauth_scheduled_emails:
                return _gopay_success_progress_fields()
            oauth_scheduled_emails.add(success_email)

            _append_task_progress(
                task_id,
                {
                    "stage": "gopay_oauth_login_started",
                    "email": success_email,
                    "message": f"GoPay 绑定成功，已在后台开始 OAuth 补登录: {success_email}",
                }
            )

            def _oauth_worker():
                from autoteam.codex_auth import CodexOAuthPhoneRequired

                max_attempts = 3
                retry_delay_seconds = 3
                for attempt in range(1, max_attempts + 1):
                    try:
                        latest_account = find_account(load_accounts(), success_email) or {"email": success_email}
                        oauth_result = _run_account_codex_login_once(success_email, latest_account, headless=False)
                        oauth_successful_emails.append(success_email)
                        _append_task_progress(
                            task_id,
                            {
                                "stage": "gopay_oauth_login_done",
                                "email": success_email,
                                "auth_file": oauth_result.get("auth_file") or "",
                                "attempt": attempt,
                                "max_attempts": max_attempts,
                                "message": f"OAuth 补登录成功: {success_email}",
                            },
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
                        realtime_successful_emails.difference_update(removed_after_success)
                        oauth_failed_emails.append(
                            {
                                "email": success_email,
                                "error": str(exc),
                                "failure_stage": "oauth_phone_required",
                                "removed_pool_emails": result_payload.get("removed_pool_emails") or [],
                            }
                        )
                        _append_task_progress(
                            task_id,
                            {
                                "stage": "gopay_oauth_phone_required_removed",
                                "email": success_email,
                                "removed_pool_emails": result_payload.get("removed_pool_emails") or [],
                                "attempt": attempt,
                                "max_attempts": max_attempts,
                                **_gopay_success_progress_fields(),
                                "message": result_payload["message"],
                                "level": "warn",
                            },
                        )
                        return
                    except Exception as exc:
                        if attempt < max_attempts:
                            _append_task_progress(
                                task_id,
                                {
                                    "stage": "gopay_oauth_login_retrying",
                                    "email": success_email,
                                    "attempt": attempt,
                                    "next_attempt": attempt + 1,
                                    "max_attempts": max_attempts,
                                    "message": f"OAuth 补登录失败，准备重试 {attempt + 1}/{max_attempts}: {success_email}: {exc}",
                                    "level": "warn",
                                },
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
                        oauth_failed_emails.append({"email": success_email, "error": str(exc), "attempts": max_attempts})
                        _append_task_progress(
                            task_id,
                            {
                                "stage": "gopay_oauth_login_failed",
                                "email": success_email,
                                "attempt": attempt,
                                "max_attempts": max_attempts,
                                "message": f"OAuth 补登录失败: {success_email}: {exc}",
                            },
                        )
                        logger.exception(
                            "[gopay-bind] OAuth login after GoPay success failed: task_id=%s email=%s attempts=%d",
                            task_id[:8] or "<unknown>",
                            _safe_email_summary(success_email),
                            max_attempts,
                        )

            threading.Thread(
                target=_oauth_worker,
                name=f"gopay-oauth-{success_email[:24]}",
                daemon=True,
            ).start()
            return _gopay_success_progress_fields()

        def _mark_gopay_token_invalidated_fail(email_value: str, *, reason: str, message: str, failure_stage: str = "token_invalidated"):
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
            if normalized in auth_session_refresh_attempted:
                return {"status": "failed", "message": f"auth_session access token 已失效，账号已标记废弃: {normalized}"}
            auth_session_refresh_attempted.add(normalized)
            message = (
                "auth_session access token 已失效，说明账号已无法使用当前凭证登录，"
                f"账号已标记 Fail/废弃: {normalized}"
            )
            _mark_gopay_token_invalidated_fail(
                normalized,
                reason="gopay_token_invalidated",
                message=message,
                failure_stage=(failure_result or {}).get("failure_stage") or "token_invalidated",
            )
            _append_task_progress(
                task_id,
                {
                    "stage": "gopay_auth_session_refresh_failed",
                    "email": normalized,
                    "failure_stage": (failure_result or {}).get("failure_stage") or "token_invalidated",
                    "message": message,
                    "level": "warn",
                },
            )
            return {"status": "failed", "message": message}

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
            if stage not in {"gopay_validate_otp", "gopay_tokenize_pin", "gopay_validate_pin", "midtrans_create_charge"}:
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
            if stage in {"browser_charge_guard", "stripe_charge_guard", "midtrans_charge_guard", "gopay_wallet_funding"}:
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
            if stage in {"midtrans_create_charge", "gopay_payment_validate", "gopay_payment_confirm", "gopay_payment_process"}:
                return False
            text = json.dumps(result_payload, ensure_ascii=False).lower()
            if stage in {"generate_checkout", "chatgpt_http_session", "chatgpt_verify"}:
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
                result_payload.get(key)
                for key in ("successful_emails", "rejected_emails", "payment_failed_emails")
            )
            return not has_consuming_failure

        def _is_no_transfer_balance_pending_result(result_payload: dict | None) -> bool:
            from autoteam.rekberinaja import is_rekberinaja_enabled

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
            if stage == "post_submit" and not any(marker in text for marker in ("gopay", "midtrans", "payment/process")):
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

        def _preserve_gopay_wallet(wallet) -> None:
            if wallet in reusable_gopay_wallets:
                return
            reusable_gopay_wallets.append(wallet)
            pool_entry = _push_gopay_reusable_wallet(
                wallet,
                task_id=task_id,
                created_at=gopay_wallet_created_at.get(id(wallet)),
                funded=id(wallet) in funded_gopay_wallet_ids or id(wallet) in gopay_wallet_funding_attempted_ids,
            )
            ttl_seconds = max(0, int(float((pool_entry or {}).get("expires_at") or 0) - time.time())) if pool_entry else 0
            _append_task_progress(
                task_id,
                {
                    "stage": "gopay_wallet_preserved",
                    "phone_number": _mask_gopay_phone_for_log(_gopay_wallet_phone(wallet)),
                    "expires_in_seconds": ttl_seconds,
                    "message": "当前失败未完成 GoPay 绑定，钱包已放入可复用池，后续账号/新任务会优先复用",
                    "level": "warn",
                },
            )

        def _take_reusable_gopay_wallet_for_bind(*, index: int = 1, total: int = 1):
            from autoteam.gopay_auto_register import is_sms_bridge_reusable

            while True:
                entry = _pop_gopay_reusable_wallet(gopay_pin=gopay_pin, country_code=country_code)
                if not entry:
                    return None
                wallet = entry.get("wallet")
                if wallet is None:
                    continue
                bridge_token = str(entry.get("bridge_token") or _gopay_wallet_bridge_token(wallet) or "").strip()
                reusable, reason = is_sms_bridge_reusable(bridge_token) if bridge_token else (False, "bridge_token_missing")
                if reusable:
                    break
                _append_task_progress(
                    task_id,
                    {
                        "stage": "gopay_wallet_reuse_discarded",
                        "current": index,
                        "total": total,
                        "phone_number": _mask_gopay_phone_for_log(_gopay_wallet_phone(wallet)),
                        "reason": reason,
                        "message": "复用 GoPay 钱包的短信会话已不可用，丢弃该钱包并重新注册",
                        "level": "warn",
                    },
                )
            active_gopay_wallets.append(wallet)
            gopay_wallet_created_at[id(wallet)] = float(entry.get("created_at") or time.time())
            if entry.get("funded"):
                funded_gopay_wallet_ids.add(id(wallet))
                gopay_wallet_funding_attempted_ids.add(id(wallet))
            _append_task_progress(
                task_id,
                {
                    "stage": "gopay_wallet_reused",
                    "current": index,
                    "total": total,
                    "phone_number": _mask_gopay_phone_for_log(_gopay_wallet_phone(wallet)),
                    "expires_in_seconds": max(0, int(float(entry.get("expires_at") or 0) - time.time())),
                    "message": f"优先复用 20 分钟有效期内未完成绑定的 GoPay 钱包 ({index}/{total})",
                },
            )
            return wallet

        class _GoPayWalletBalanceNotReady(RuntimeError):
            pass

        def _gopay_wallet_balance_poll_intervals() -> list[float]:
            poll_intervals = _gopay_auto_signup_no_transfer_retry_waits_seconds()
            return poll_intervals or [30.0, 60.0, 120.0]

        def _wait_for_gopay_wallet_balance_ready(
            wallet,
            *,
            index: int = 1,
            total: int = 1,
            poll_intervals: list[float] | None = None,
            initial_wait: float | None = None,
            not_ready_message: str = "GoPay 余额三次查询仍未到账，舍弃该钱包并重新注册",
            ready_message: str = "GoPay 钱包余额已到账，开始绑定",
            raise_on_not_ready: bool = True,
        ) -> bool:
            if wallet is None:
                return False
            if id(wallet) in gopay_wallet_balance_ready_ids:
                return True
            access_token = str(getattr(wallet, "access_token", "") or "").strip()
            if not access_token:
                return False

            from autoteam.gopay_auto_register import query_gopay_balance

            intervals = list(poll_intervals if poll_intervals is not None else _gopay_wallet_balance_poll_intervals())
            if initial_wait is not None:
                intervals = [float(initial_wait), *intervals]
            if not intervals:
                intervals = [0.0]
            max_checks = max(1, len(intervals))
            for check_index, wait_seconds in enumerate(intervals, 1):
                wait_seconds = max(0.0, float(wait_seconds))
                if wait_seconds > 0:
                    _append_task_progress(
                        task_id,
                        {
                            "stage": "gopay_wallet_balance_wait",
                            "current": index,
                            "total": total,
                            "phone_number": _mask_gopay_phone_for_log(_gopay_wallet_phone(wallet)),
                            "delay_seconds": round(wait_seconds, 1),
                            "attempt": check_index,
                            "max_attempts": max_checks,
                            "message": f"等待 {wait_seconds:.1f}s 后第 {check_index}/{max_checks} 次查询 GoPay 余额",
                            "level": "warn",
                        },
                    )
                    time.sleep(wait_seconds)
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
                        {
                            "stage": "gopay_wallet_balance_check_failed",
                            "current": index,
                            "total": total,
                            "phone_number": _mask_gopay_phone_for_log(_gopay_wallet_phone(wallet)),
                            "attempt": check_index,
                            "max_attempts": max_checks,
                            "message": f"GoPay 余额查询失败 ({check_index}/{max_checks}): {_compact_log_text(exc, limit=160)}",
                            "level": "warn",
                        },
                    )
                    continue
                value = float(balance.get("value") or 0)
                _append_task_progress(
                    task_id,
                    {
                        "stage": "gopay_wallet_balance_checked",
                        "current": index,
                        "total": total,
                        "phone_number": _mask_gopay_phone_for_log(_gopay_wallet_phone(wallet)),
                        "balance": value,
                        "currency": balance.get("currency") or "IDR",
                        "display_value": balance.get("display_value") or "",
                        "attempt": check_index,
                        "max_attempts": max_checks,
                        "message": f"GoPay 钱包余额查询: {balance.get('display_value') or value} ({check_index}/{max_checks})",
                    },
                )
                if value >= 1:
                    _append_task_progress(
                        task_id,
                        {
                            "stage": "gopay_wallet_balance_ready",
                            "current": index,
                            "total": total,
                            "phone_number": _mask_gopay_phone_for_log(_gopay_wallet_phone(wallet)),
                            "balance": value,
                            "currency": balance.get("currency") or "IDR",
                            "display_value": balance.get("display_value") or "",
                            "message": ready_message,
                            "level": "success",
                        },
                    )
                    gopay_wallet_balance_ready_ids.add(id(wallet))
                    return True
            _append_task_progress(
                task_id,
                {
                    "stage": "gopay_wallet_balance_not_ready",
                    "current": index,
                    "total": total,
                    "phone_number": _mask_gopay_phone_for_log(_gopay_wallet_phone(wallet)),
                    "message": not_ready_message,
                    "level": "warn",
                },
            )
            if not raise_on_not_ready:
                return False
            raise _GoPayWalletBalanceNotReady(not_ready_message)

        def _fund_gopay_wallet_for_bind(wallet, *, index: int = 1, total: int = 1) -> dict | None:
            from autoteam.rekberinaja import fund_gopay_wallet_if_enabled, is_rekberinaja_enabled

            if wallet is None or not is_rekberinaja_enabled():
                return None
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
                    {
                        "stage": "gopay_wallet_funding_skipped",
                        "current": index,
                        "total": total,
                        "phone_number": _mask_gopay_phone_for_log(phone),
                        "message": "GoPay 钱包已有 ≥1Rp 余额，本次跳过 Rekberinaja 转账",
                    },
                )
                return None
            if id(wallet) in funded_gopay_wallet_ids:
                _append_task_progress(
                    task_id,
                    {
                        "stage": "gopay_wallet_funding_skipped",
                        "current": index,
                        "total": total,
                        "phone_number": _mask_gopay_phone_for_log(phone),
                        "message": "复用的 GoPay 钱包已记录为已充值或已提交过充值订单，本次不重复转账",
                    },
                )
                _wait_for_gopay_wallet_balance_ready(
                    wallet,
                    index=index,
                    total=total,
                    poll_intervals=_gopay_wallet_balance_poll_intervals(),
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
                {
                    "stage": "gopay_wallet_funding_started",
                    "current": index,
                    "total": total,
                    "phone_number": _mask_gopay_phone_for_log(phone),
                    "message": f"正在通过 Rekberinaja 站内余额给 GoPay 钱包充值 ({index}/{total})",
                },
            )
            try:
                result = fund_gopay_wallet_if_enabled(phone, log=logger.info, progress=_funding_progress)
            except Exception as exc:
                if bool(getattr(exc, "debited_possible", False)):
                    funded_gopay_wallet_ids.add(id(wallet))
                    gopay_wallet_funding_attempted_ids.add(id(wallet))
                _append_task_progress(
                    task_id,
                    {
                        "stage": "gopay_wallet_funding_failed",
                        "current": index,
                        "total": total,
                        "phone_number": _mask_gopay_phone_for_log(phone),
                        "transaction_id": str(getattr(exc, "transaction_id", "") or ""),
                        "rekberinaja_stage": str(getattr(exc, "stage", "") or ""),
                        "debited_possible": bool(getattr(exc, "debited_possible", False)),
                        "message": (
                            "Rekberinaja 充值失败；订单已进入站内支付阶段，后续复用该钱包时不会重复充值"
                            if bool(getattr(exc, "debited_possible", False))
                            else f"Rekberinaja 充值失败: {_compact_log_text(exc, limit=180)}"
                        ),
                        "level": "warn",
                    },
                )
                raise
            funded_gopay_wallet_ids.add(id(wallet))
            gopay_wallet_funding_attempted_ids.add(id(wallet))
            _append_task_progress(
                task_id,
                {
                    "stage": "gopay_wallet_funding_done",
                    "current": index,
                    "total": total,
                    "phone_number": _mask_gopay_phone_for_log(phone),
                    "transaction_id": (result or {}).get("transaction_id") or "",
                    "message": f"Rekberinaja GoPay 钱包充值完成 ({index}/{total})",
                },
            )
            _wait_for_gopay_wallet_balance_ready(
                wallet,
                index=index,
                total=total,
                poll_intervals=[0.0, *_gopay_wallet_balance_poll_intervals()],
                not_ready_message="Rekberinaja 转账后 GoPay 余额仍未到账，舍弃该钱包并重新注册",
            )
            return result

        def _wait_after_gopay_pin_when_transfer_disabled(wallet, *, index: int = 1, total: int = 1) -> None:
            from autoteam.rekberinaja import is_rekberinaja_enabled

            if wallet is None or is_rekberinaja_enabled():
                return
            if id(wallet) in gopay_wallet_balance_ready_ids:
                return
            access_token = str(getattr(wallet, "access_token", "") or "").strip()
            if access_token:
                _wait_for_gopay_wallet_balance_ready(
                    wallet,
                    index=index,
                    total=total,
                    poll_intervals=_gopay_wallet_balance_poll_intervals(),
                )
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
                {
                    "stage": "gopay_wallet_no_transfer_bind_wait",
                    "current": index,
                    "total": total,
                    "phone_number": _mask_gopay_phone_for_log(_gopay_wallet_phone(wallet)),
                    "delay_seconds": round(wait_seconds, 1),
                    "message": f"未启用 GoPay 充值/转账，等待 {wait_seconds:.1f}s 后开始绑定 ({index}/{total})",
                },
            )
            time.sleep(wait_seconds)

        def _register_gopay_wallet_for_bind(*, index: int = 1, total: int = 1):
            from autoteam.gopay_auto_register import GoPaySignupProbeError, register_gopay_wallet

            max_wallet_attempts = max(1, int(os.environ.get("GOPAY_AUTO_SIGNUP_WALLET_ATTEMPTS", "10") or "10"))
            last_exc: Exception | None = None
            for wallet_attempt in range(1, max_wallet_attempts + 1):
                def _signup_log(message: str, *, _attempt: int = wallet_attempt) -> None:
                    text = _compact_log_text(message, limit=220)
                    logger.info(text)
                    if not text:
                        return
                    _append_task_progress(
                        task_id,
                        {
                            "stage": "gopay_wallet_auto_signup_detail",
                            "current": index,
                            "total": total,
                            "attempt": _attempt,
                            "max_attempts": max_wallet_attempts,
                            "message": text,
                        },
                    )

                _append_task_progress(
                    task_id,
                    {
                        "stage": "gopay_wallet_auto_signup_started",
                        "current": index,
                        "total": total,
                        "attempt": wallet_attempt,
                        "max_attempts": max_wallet_attempts,
                        "message": f"正在自动注册 GoPay 钱包 ({index}/{total})，取号尝试 {wallet_attempt}/{max_wallet_attempts}",
                    },
                )
                try:
                    wallet = register_gopay_wallet(
                        pin=gopay_pin,
                        proxy_url=proxy_url,
                        country_code=country_code,
                        sms_provider=gopay_auto_signup_sms_provider,
                        hero_sms_config=gopay_auto_signup_hero_sms_config,
                        smscloud_config=gopay_auto_signup_smscloud_config,
                        public_base_url=gopay_task_public_base_url,
                        appium_config=gopay_auto_signup_appium_config,
                        log=_signup_log,
                    )
                    break
                except GoPaySignupProbeError as exc:
                    _append_task_progress(
                        task_id,
                        {
                            "stage": "gopay_wallet_auto_signup_probe_failed",
                            "current": index,
                            "total": total,
                            "attempt": wallet_attempt,
                            "max_attempts": max_wallet_attempts,
                            "message": f"GoPay 注册前探测异常，已停止继续取号: {_compact_log_text(exc, limit=220)}",
                            "level": "error",
                        },
                    )
                    raise
                except Exception as exc:
                    last_exc = exc
                    if _looks_like_gopay_wallet_signup_rate_limited(exc):
                        message = f"GoPay 钱包自动注册触发 rate_limited，已停止任务: {_compact_log_text(exc, limit=220)}"
                        _append_task_progress(
                            task_id,
                            {
                                "stage": "gopay_wallet_auto_signup_rate_limited",
                                "current": index,
                                "total": total,
                                "attempt": wallet_attempt,
                                "max_attempts": max_wallet_attempts,
                                "message": message,
                                "level": "error",
                            },
                        )
                        raise _GoPayWalletSignupRateLimited(message) from exc
                    if _looks_like_gopay_wallet_signup_network_error(exc):
                        message = f"GoPay 钱包自动注册遇到网络中断，已停止继续换号: {_compact_log_text(exc, limit=220)}"
                        _append_task_progress(
                            task_id,
                            {
                                "stage": "gopay_wallet_auto_signup_network_error",
                                "current": index,
                                "total": total,
                                "attempt": wallet_attempt,
                                "max_attempts": max_wallet_attempts,
                                "message": message,
                                "level": "warn",
                            },
                        )
                        raise _GoPayWalletSignupNetworkError(message) from exc
                    if wallet_attempt >= max_wallet_attempts:
                        raise
                    _append_task_progress(
                        task_id,
                        {
                            "stage": "gopay_wallet_auto_signup_retry",
                            "current": index,
                            "total": total,
                            "attempt": wallet_attempt + 1,
                            "max_attempts": max_wallet_attempts,
                            "message": f"GoPay 钱包自动注册失败，准备换号重试: {_compact_log_text(exc, limit=160)}",
                            "level": "warn",
                        },
                    )
                    time.sleep(2)
            else:
                raise last_exc or RuntimeError("GoPay 钱包自动注册失败")
            active_gopay_wallets.append(wallet)
            gopay_wallet_created_at[id(wallet)] = time.time()
            _append_task_progress(
                task_id,
                {
                    "stage": "gopay_wallet_auto_signup_done",
                    "current": index,
                    "total": total,
                    "phone_number": _mask_gopay_phone_for_log(wallet.phone_number),
                    "message": f"GoPay 钱包自动注册完成 ({index}/{total})",
                },
            )
            return wallet

        def _discard_gopay_wallet_for_balance_not_ready(wallet, *, index: int = 1, total: int = 1) -> None:
            if wallet is None:
                return
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
                {
                    "stage": "gopay_wallet_balance_abandoned",
                    "current": index,
                    "total": total,
                    "phone_number": _mask_gopay_phone_for_log(_gopay_wallet_phone(wallet)),
                    "message": "GoPay 余额未到账，已取消该短信会话并准备重新注册钱包",
                    "level": "warn",
                },
            )

        def _discard_gopay_wallet_bound_elsewhere(wallet, *, index: int = 1, total: int = 1) -> None:
            if wallet is None:
                return
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
                {
                    "stage": "gopay_wallet_already_linked_discarded",
                    "current": index,
                    "total": total,
                    "phone_number": _mask_gopay_phone_for_log(_gopay_wallet_phone(wallet)),
                    "message": "该 GoPay 手机号已绑定其他账号，已舍弃该钱包并重新注册",
                    "level": "warn",
                },
            )

        def _prepare_gopay_wallet_for_bind(wallet=None, *, index: int = 1, total: int = 1):
            max_wallet_attempts = max(1, int(os.environ.get("GOPAY_AUTO_SIGNUP_WALLET_ATTEMPTS", "10") or "10"))
            last_exc: Exception | None = None
            for wallet_attempt in range(1, max_wallet_attempts + 1):
                current_wallet = wallet
                wallet = None
                if current_wallet is None:
                    current_wallet = _register_gopay_wallet_for_bind(index=index, total=total)
                try:
                    _fund_gopay_wallet_for_bind(current_wallet, index=index, total=total)
                    _wait_after_gopay_pin_when_transfer_disabled(current_wallet, index=index, total=total)
                    return current_wallet
                except _GoPayWalletBalanceNotReady as exc:
                    last_exc = exc
                    _discard_gopay_wallet_for_balance_not_ready(current_wallet, index=index, total=total)
                    if wallet_attempt >= max_wallet_attempts:
                        raise
                    _append_task_progress(
                        task_id,
                        {
                            "stage": "gopay_wallet_auto_signup_retry",
                            "current": index,
                            "total": total,
                            "attempt": wallet_attempt + 1,
                            "max_attempts": max_wallet_attempts,
                            "message": "GoPay 余额未到账，准备重新注册 GoPay 钱包",
                            "level": "warn",
                        },
                    )
            raise last_exc or RuntimeError("GoPay 钱包准备失败")

        class _GoPayWalletPrefetcher:
            def __init__(self, *, total: int):
                self.total = max(0, int(total or 0))
                self.max_workers = _gopay_auto_signup_prefetch_wallets() if gopay_auto_signup and self.total > 1 else 0
                self.executor = ThreadPoolExecutor(max_workers=self.max_workers) if self.max_workers > 0 else None
                self.futures: list[tuple[Any, int]] = []
                self.next_index = 1

            def ensure_ahead(self, completed_index: int) -> None:
                if self.executor is None or cancel_signal.is_cancelled():
                    return
                self.next_index = max(self.next_index, int(completed_index or 0) + 1)
                while len(self.futures) < self.max_workers and self.next_index <= self.total:
                    prefetch_index = self.next_index
                    self.next_index += 1
                    _append_task_progress(
                        task_id,
                        {
                            "stage": "gopay_wallet_prefetch_started",
                            "current": prefetch_index,
                            "total": self.total,
                            "message": f"后台预注册 GoPay 钱包 ({prefetch_index}/{self.total})",
                        },
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
                        {
                            "stage": "gopay_wallet_prefetch_wait",
                            "current": index,
                            "total": self.total,
                            "message": f"等待后台预注册 GoPay 钱包完成 ({index}/{self.total})",
                        },
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
                        {
                            "stage": "gopay_wallet_prefetch_failed",
                            "current": index,
                            "total": self.total,
                            "prefetch_index": prefetch_index,
                            "message": f"后台预注册 GoPay 钱包失败，回退同步注册: {_compact_log_text(exc, limit=180)}",
                            "level": "warn",
                        },
                    )
                    return None
                _append_task_progress(
                    task_id,
                    {
                        "stage": "gopay_wallet_prefetch_used",
                        "current": index,
                        "total": self.total,
                        "prefetch_index": prefetch_index,
                        "phone_number": _mask_gopay_phone_for_log(_gopay_wallet_phone(wallet)),
                        "message": f"使用后台预注册 GoPay 钱包 ({index}/{self.total})",
                    },
                )
                return wallet

            def close(self) -> None:
                if self.executor is None:
                    return
                self.executor.shutdown(wait=True, cancel_futures=True)

        def _register_one_for_gopay(*, index: int = 1, total: int = 1) -> str:
            from autoteam.mail import TemporaryEmailClient
            from autoteam.manager import _temporary_mail_provider, create_account_direct, wrap_mail_client_with_auth_retry

            register_domain = auto_register_domains[(index - 1) % len(auto_register_domains)] if auto_register_domains else ""
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
                {
                    "stage": "gopay_auto_register_started",
                    "current": index,
                    "total": total,
                    "message": (
                        f"自动注册已开始 ({index}/{total}): LuckMail/{auto_register_luckmail_email_type or '默认'}"
                        + (f"/@{luckmail_register_domain}" if luckmail_register_domain else "/自动分配")
                        if auto_register_mail_provider == "luckmail"
                        else (
                            f"自动注册已开始 ({index}/{total}): Outlook账号池"
                            if auto_register_mail_provider == "outlook"
                            else f"自动注册已开始 ({index}/{total}): domain=@{register_domain}"
                        )
                    ),
                },
            )
            with _temporary_mail_provider(auto_register_mail_provider, mail_provider_overrides):
                raw_mail_client = TemporaryEmailClient()
            raw_mail_client.login()
            mail_client = wrap_mail_client_with_auth_retry(raw_mail_client, log_prefix="GoPay自动注册")
            outcome = {}

            def _register_progress(progress: dict):
                if not isinstance(progress, dict):
                    return
                stage = str(progress.get("stage") or "gopay_auto_register_progress")
                message = str(progress.get("message") or stage)
                _append_task_progress(
                    task_id,
                    {
                        **progress,
                        "stage": stage,
                        "current": index,
                        "total": total,
                        "message": f"自动注册 ({index}/{total})：{message}",
                    },
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
                        str(register_payload.get("password") or outcome.get("password") or auto_register_password or ""),
                        cloudmail_account_id=register_payload.get("cloudmail_account_id") or outcome.get("cloudmail_account_id"),
                        seat_type=SEAT_CODEX,
                        mail_provider=register_payload.get("mail_provider") or outcome.get("mail_provider") or auto_register_mail_provider or None,
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
                {
                    "stage": "gopay_auto_register_done",
                    "email": registered_email,
                    "current": index,
                    "total": total,
                    "message": f"自动注册完成 ({index}/{total})，开始 GoPay 绑定: {registered_email}",
                },
            )
            return registered_email

        def _phone_accounts_for_attempt(index: int) -> list[dict]:
            if not phone_accounts:
                return []
            selected = phone_accounts[(max(1, int(index or 1)) - 1) % len(phone_accounts)]
            return [dict(selected)]

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
                pending_retry_attempts=pending_retry_attempts if pending_retry_override is None else pending_retry_override,
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
            elif auto_wallet in reusable_gopay_wallets:
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
                                selected_phone_accounts=[auto_wallet.as_phone_account()],
                                pending_retry_override=0,
                            )
                            or {}
                        )
                    finally:
                        gopay_wallet_prefetch_context.update({"prefetcher": None, "index": 0, "total": 0, "triggered": False})
                except Exception as exc:
                    if isinstance(exc, (_GoPayWalletSignupRateLimited, _GoPayWalletSignupNetworkError)):
                        raise
                    logger.exception(
                        "[gopay-bind] GoPay auto-signup bind failed: index=%s/%s email=%s",
                        index,
                        total,
                        _safe_email_summary(bind_email),
                    )
                    single_result = {
                        "status": "failed",
                        "failure_stage": "gopay_wallet_funding" if "Rekberinaja" in str(exc) else "post_submit",
                        "message": f"{exception_message_prefix}: {exc}",
                        "screenshot_paths": [],
                    }

                last_result = single_result
                if not _is_gopay_wallet_bound_elsewhere_result(single_result):
                    return single_result, auto_wallet

                _discard_gopay_wallet_bound_elsewhere(auto_wallet, index=index, total=total)
                auto_wallet = None
                if wallet_attempt >= max_wallet_attempts:
                    break
                _append_task_progress(
                    task_id,
                    {
                        "stage": "gopay_wallet_already_linked_retry",
                        "email": bind_email,
                        "current": index,
                        "total": total,
                        "attempt": wallet_attempt + 1,
                        "max_attempts": max_wallet_attempts,
                        "message": "GoPay 手机号已绑定其他账号，正在重新注册 GoPay 钱包后重试当前账号",
                        "level": "warn",
                    },
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
                    {
                        "stage": "gopay_auto_register_next",
                        "current": index,
                        "total": auto_register_count,
                        "message": f"自动注册 GoPay 进度: {index}/{auto_register_count}",
                    },
                )
                try:
                    current_email = _register_one_for_gopay(index=index, total=auto_register_count)
                    _append_unique(registered_emails, current_email)
                    email = current_email
                    account_emails = []
                except Exception as exc:
                    logger.exception("[gopay-bind] auto-register failed before GoPay bind: index=%s/%s", index, auto_register_count)
                    single_result = {
                        "status": "failed",
                        "failure_stage": "gopay_auto_register",
                        "register_status": "failed",
                        "bind_status": "not_started",
                        "message": f"自动注册失败: {exc}",
                        "screenshot_paths": [],
                    }
                else:
                    delay_seconds = _gopay_auto_register_bind_delay_seconds()
                    if delay_seconds > 0:
                        _append_task_progress(
                            task_id,
                            {
                                "stage": "gopay_auto_register_bind_wait",
                                "email": current_email,
                                "current": index,
                                "total": auto_register_count,
                                "delay_seconds": round(delay_seconds, 1),
                                "message": f"注册已成功，等待 {delay_seconds:.1f}s 后开始 GoPay 绑定: {current_email}",
                            },
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
                            failure_result = {
                                "status": "failed",
                                "failure_stage": "gopay_wallet_rate_limited",
                                "register_status": "success" if failed_email else "failed",
                                "bind_status": "failed" if failed_email else "not_started",
                                "message": str(exc),
                                "screenshot_paths": [],
                                "auto_register_results": aggregate_results,
                                "auto_register_count": auto_register_count,
                                "auto_register_attempted": index,
                                "registered_emails": registered_emails,
                                "successful_emails": successful_emails,
                                "failed_emails": failed_emails
                                + (
                                    [
                                        {
                                            "email": failed_email,
                                            "failure_stage": "gopay_wallet_rate_limited",
                                            "message": str(exc),
                                            "register_status": "success",
                                            "bind_status": "failed",
                                        }
                                    ]
                                    if failed_email
                                    else []
                                ),
                                "bind_failed_emails": bind_failed_emails
                                + (
                                    [
                                        {
                                            "email": failed_email,
                                            "failure_stage": "gopay_wallet_rate_limited",
                                            "message": str(exc),
                                        }
                                    ]
                                    if failed_email
                                    else []
                                ),
                                "pending_retry_emails": [item["email"] for item in pending_retry_items if item.get("email")],
                                "retried_emails": retried_emails,
                                "rejected_emails": rejected_emails,
                                "payment_failed_emails": payment_failed_emails,
                                "nonzero_blocked_emails": nonzero_blocked_emails,
                                "blocked_emails": blocked_emails,
                                "email_used": failed_email or last_success_email or _normalized_email(email),
                            }
                            if failed_email:
                                failure_result["auto_register_results"] = aggregate_results + [
                                    {
                                        "status": "failed",
                                        "failure_stage": "gopay_wallet_rate_limited",
                                        "register_status": "success",
                                        "bind_status": "failed",
                                        "message": str(exc),
                                        "screenshot_paths": [],
                                        "email_used": failed_email,
                                        "auto_register_index": index,
                                        "auto_register_total": auto_register_count,
                                    }
                                ]
                            return failure_result
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
                            single_result = {
                                "status": "failed",
                                "failure_stage": "post_submit",
                                "register_status": "success",
                                "bind_status": "failed",
                                "message": f"注册已成功，GoPay 绑定异常: {exc}",
                                "screenshot_paths": [],
                            }
                single_result.setdefault("status", "failed")
                single_result.setdefault("failure_stage", "")
                single_result.setdefault("message", "")
                single_result.setdefault("screenshot_paths", [])
                single_email = _normalized_email(single_result.get("email_used") or single_result.get("email") or current_email)
                if single_email:
                    single_result["email_used"] = single_email
                if current_email:
                    single_result.setdefault("register_status", "success")
                single_result.setdefault(
                    "bind_status",
                    "success" if single_result.get("status") == "success" else "failed" if current_email else "not_started",
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
                retry_reason = "" if _is_gopay_wallet_bound_elsewhere_result(single_result) else _gopay_pending_retry_reason(single_result)
                if current_email and single_result.get("status") != "success" and retry_reason and pending_retry_attempts > 0:
                    source_stage = _gopay_pending_retry_source_stage(single_result, retry_reason)
                    single_result["bind_status"] = "retry_pending"
                    pending_retry_items.append(
                        {
                            "email": single_email,
                            "index": index,
                            "phone_accounts": (
                                [auto_wallet.as_phone_account()]
                                if auto_wallet is not None
                                else _phone_accounts_for_attempt(index)
                            ),
                            "reason": retry_reason,
                        }
                    )
                    _append_task_progress(
                        task_id,
                        {
                            "stage": "gopay_pending_retry_queued",
                            "email": single_email,
                            "current": index,
                            "total": auto_register_count,
                            "reason": retry_reason,
                            "source_stage": source_stage,
                            "pending_retry": len(pending_retry_items),
                            "message": f"自动注册账号加入待重试: {single_email}",
                            "level": "warn",
                        },
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
                if single_email and single_failure_stage in {"browser_charge_guard", "stripe_charge_guard", "midtrans_charge_guard"}:
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

            pending_retry_backoffs = [60.0, 180.0, 300.0]
            for retry_round in range(1, pending_retry_attempts + 1):
                retry_candidates = pending_retry_items[:]
                if not retry_candidates or cancel_signal.is_cancelled():
                    break
                pending_retry_items.clear()
                wait_seconds = pending_retry_backoffs[min(retry_round - 1, len(pending_retry_backoffs) - 1)]
                _append_task_progress(
                    task_id,
                    {
                        "stage": "gopay_pending_retry_wait",
                        "retry_round": retry_round,
                        "max_retry_rounds": pending_retry_attempts,
                        "delay_seconds": wait_seconds,
                        "pending_retry": len(retry_candidates),
                        "message": f"自动注册待重试第 {retry_round}/{pending_retry_attempts} 轮将在 {wait_seconds:.0f}s 后开始",
                    },
                )
                if wait_seconds > 0:
                    time.sleep(wait_seconds)
                if cancel_signal.is_cancelled():
                    break
                _append_task_progress(
                    task_id,
                    {
                        "stage": "gopay_pending_retry_started",
                        "retry_round": retry_round,
                        "max_retry_rounds": pending_retry_attempts,
                        "pending_retry": len(retry_candidates),
                        "message": f"开始自动注册待重试第 {retry_round}/{pending_retry_attempts} 轮，共 {len(retry_candidates)} 个账号",
                    },
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
                        {
                            "stage": "gopay_pending_retry_account",
                            "email": retry_email,
                            "attempt": retry_offset,
                            "total": len(retry_candidates),
                            "current": retry_index,
                            "auto_register_total": auto_register_count,
                            "retry_round": retry_round,
                            "max_retry_rounds": pending_retry_attempts,
                            "pending_retry": len(pending_retry_items),
                            "message": f"正在执行自动注册待重试第 {retry_round}/{pending_retry_attempts} 轮: {retry_email} ({retry_offset}/{len(retry_candidates)})",
                        },
                    )
                    try:
                        single_result = dict(
                            _run_one_gopay_bind(
                                retry_email,
                                [],
                                selected_phone_accounts=item.get("phone_accounts") or _phone_accounts_for_attempt(retry_index),
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
                        single_result = {
                            "status": "failed",
                            "failure_stage": "post_submit",
                            "register_status": "success",
                            "bind_status": "failed",
                            "message": f"注册已成功，GoPay 待重试异常: {exc}",
                            "screenshot_paths": [],
                        }
                    single_result.setdefault("status", "failed")
                    single_result.setdefault("failure_stage", "")
                    single_result.setdefault("message", "")
                    single_result.setdefault("screenshot_paths", [])
                    single_email = _normalized_email(single_result.get("email_used") or single_result.get("email") or retry_email)
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
                    if single_result.get("status") != "success" and retry_reason and retry_round < pending_retry_attempts:
                        pending_retry_items.append(
                            {
                                "email": single_email,
                                "index": retry_index,
                                "phone_accounts": item.get("phone_accounts") or _phone_accounts_for_attempt(retry_index),
                                "reason": retry_reason,
                            }
                        )
                        _append_task_progress(
                            task_id,
                            {
                                "stage": "gopay_pending_retry_queued",
                                "email": single_email,
                                "current": retry_index,
                                "total": auto_register_count,
                                "retry_round": retry_round,
                                "max_retry_rounds": pending_retry_attempts,
                                "reason": retry_reason,
                                "pending_retry": len(pending_retry_items),
                                "message": f"自动注册账号继续加入下一轮待重试: {single_email}",
                                "level": "warn",
                            },
                        )
                        continue

                    if single_result.get("status") != "success":
                        _append_task_progress(
                            task_id,
                            {
                                "stage": "gopay_pending_retry_failed",
                                "email": single_email,
                                "current": retry_index,
                                "total": auto_register_count,
                                "retry_round": retry_round,
                                "max_retry_rounds": pending_retry_attempts,
                                "failure_stage": single_result.get("failure_stage") or "",
                                "register_status": single_result.get("register_status") or "",
                                "bind_status": single_result.get("bind_status") or "",
                                "message": single_result.get("message") or "自动注册 GoPay 待重试失败",
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
                    if single_email and single_failure_stage in {"browser_charge_guard", "stripe_charge_guard", "midtrans_charge_guard"}:
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
                return {
                    "status": "cancelled" if cancel_signal.is_cancelled() else "failed",
                    "failure_stage": "cancelled" if cancel_signal.is_cancelled() else "gopay_auto_register",
                    "message": "自动注册 GoPay 任务已取消" if cancel_signal.is_cancelled() else "自动注册 GoPay 未执行",
                    "screenshot_paths": [],
                    "auto_register_results": [],
                    "successful_emails": [],
                    "failed_emails": [],
                }

            success_count = len(successful_emails)
            attempted_count = auto_register_attempted_count
            aggregate_status = "success" if success_count else ("cancelled" if cancel_signal.is_cancelled() else "failed")
            failure_stage = ""
            if success_count and failed_emails:
                failure_stage = "partial_failed"
            elif not success_count:
                failure_stage = last_result.get("failure_stage") or "gopay_auto_register"
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
                    "email_used": last_success_email or _normalized_email(last_result.get("email_used") or email),
                }
            )
            return result_payload

        def _run_gopay_auto_signup_existing_accounts_batch() -> dict:
            candidates = account_emails[:] if account_emails else [email]
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
                    {
                        "stage": "gopay_auto_signup_account",
                        "email": normalized_candidate,
                        "attempt": index,
                        "total": len(candidates),
                        "message": f"正在为账号注册/复用 GoPay 钱包: {normalized_candidate} ({index}/{len(candidates)})",
                    },
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
                    return {
                        "status": "failed",
                        "failure_stage": "gopay_wallet_rate_limited",
                        "message": str(exc),
                        "screenshot_paths": [],
                        "auto_signup_account_results": aggregate_results
                        + [
                            {
                                "status": "failed",
                                "failure_stage": "gopay_wallet_rate_limited",
                                "message": str(exc),
                                "screenshot_paths": [],
                                "email_used": normalized_candidate,
                                "auto_signup_account_index": index,
                                "auto_signup_account_total": len(candidates),
                            }
                        ],
                        "attempted_emails": attempted_emails,
                        "successful_emails": successful_emails,
                        "rejected_emails": rejected_emails,
                        "payment_failed_emails": payment_failed_emails,
                        "nonzero_blocked_emails": nonzero_blocked_emails,
                        "blocked_emails": blocked_emails,
                        "failed_emails": failed_emails
                        + [
                            {
                                "email": normalized_candidate,
                                "failure_stage": "gopay_wallet_rate_limited",
                                "message": str(exc),
                            }
                        ],
                    }
                reusable_auto_wallet = None

                single_result.setdefault("status", "failed")
                single_result.setdefault("failure_stage", "")
                single_result.setdefault("message", "")
                single_result.setdefault("screenshot_paths", [])
                single_email = _normalized_email(single_result.get("email_used") or single_result.get("email") or normalized_candidate)
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
                if single_email and single_failure_stage in {"browser_charge_guard", "stripe_charge_guard", "midtrans_charge_guard"}:
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
                        {
                            "stage": "gopay_auto_signup_account_success",
                            "email": single_email,
                            "attempt": index,
                            "total": len(candidates),
                            "successful": len(successful_emails),
                            "message": f"GoPay 自动注册绑定账号成功: {single_email} ({index}/{len(candidates)})",
                            **_gopay_success_progress_fields(),
                        },
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
                    {
                        "stage": "gopay_auto_signup_account_failed",
                        "email": single_email,
                        "attempt": index,
                        "total": len(candidates),
                        "failure_stage": single_result.get("failure_stage") or "",
                        "message": single_result.get("message") or "GoPay 自动注册绑定失败",
                        "level": "warn",
                    },
                )

            wallet_prefetcher.close()

            if not aggregate_results:
                return {
                    "status": "cancelled" if cancel_signal.is_cancelled() else "failed",
                    "failure_stage": "cancelled" if cancel_signal.is_cancelled() else "gopay_auto_signup",
                    "message": "GoPay 自动注册绑定任务已取消" if cancel_signal.is_cancelled() else "GoPay 自动注册绑定未执行",
                    "screenshot_paths": [],
                    "auto_signup_account_results": [],
                    "attempted_emails": attempted_emails,
                    "successful_emails": [],
                    "failed_emails": failed_emails,
                }

            success_count = len(successful_emails)
            attempted_count = len(attempted_emails)
            aggregate_status = "success" if success_count else ("cancelled" if cancel_signal.is_cancelled() else "failed")
            failure_stage = ""
            if success_count and failed_emails:
                failure_stage = "partial_failed"
            elif not success_count:
                failure_stage = last_result.get("failure_stage") or ("cancelled" if cancel_signal.is_cancelled() else "gopay_auto_signup")
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
                }
            )
            return result_payload

        try:
            logger.info(
                "[gopay-bind] runner started: task_id=%s email=%s auto_register=%s auto_register_count=%s gopay_auto_signup=%s account_count=%s pending_retry_attempts=%s checkout=%s checkout_mode=%s proxy_label=%s proxy_state=%s proxy=%s",
                task_id[:8] or "<unknown>",
                _safe_email_summary(email) if email else "<auto-register>",
                auto_register,
                auto_register_count,
                gopay_auto_signup,
                len(account_emails) if account_emails else 1,
                pending_retry_attempts,
                _safe_url_summary(checkout_url) if checkout_url else "<auto-generate>",
                checkout_ui_mode,
                params.proxy_label or "<none>",
                proxy_config_state,
                _safe_proxy_summary(normalized_proxy_url or proxy_url),
            )
            _append_task_progress(
                task_id,
                {
                    "stage": "gopay_binding",
                    "email": email,
                "auto_register": auto_register,
                "auto_register_count": auto_register_count,
                "auto_register_protocol": bool(params.auto_register_protocol),
                "gopay_auto_signup": gopay_auto_signup,
                    "phone_number": phone_number,
                    "country_code": country_code,
                    "phone_account_count": len(phone_accounts),
                    "checkout_ui_mode": checkout_ui_mode,
                    "proxy_label": params.proxy_label,
                    "account_count": auto_register_count if auto_register else len(account_emails) if account_emails else 1,
                    "pending_retry_attempts": pending_retry_attempts,
                }
            )
            if proxy_url and not bind_proxy_url:
                _append_task_progress(
                    task_id,
                    {
                        "stage": "gopay_bind_proxy_bypassed",
                        "message": "GoPay 绑定阶段不使用 SOCKS 代理，checkout/Stripe/Midtrans 将直连",
                    },
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
            if isinstance(exc, _GoPayWalletSignupNetworkError):
                failure_stage = "gopay_wallet_network_error"
            if "Rekberinaja" in str(exc):
                failure_stage = "gopay_wallet_funding"
            result = {
                "status": "failed",
                "failure_stage": failure_stage,
                "message": f"GoPay 任务执行异常: {exc}",
                "screenshot_paths": [],
            }
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
                            {
                                "stage": "gopay_wallet_otp_session_retained",
                                "phone_number": _mask_gopay_phone_for_log(wallet.phone_number),
                                "message": "GoPay 绑定未完整成功，已保留短信接码会话，未标记完成或取消",
                                "level": "warn",
                            },
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
        if result.get("status") == "success":
            success_email = _normalized_email(actual_email)
            if success_email and success_email not in successful_emails:
                successful_emails.append(success_email)

        pending_successful_emails = [success_email for success_email in successful_emails if success_email not in realtime_successful_emails]
        if pending_successful_emails:
            for success_email in pending_successful_emails:
                _mark_gopay_success_account(
                    success_email,
                    message=result.get("message") or "GoPay 绑定成功",
                    success_checkout_url=result.get("checkout_url") or checkout_url or "",
                )
            if result.get("status") != "success" and actual_email not in successful_emails:
                update_account(actual_email, **account_update)
        elif not successful_emails and actual_email:
            update_account(actual_email, **account_update)

        if realtime_successful_emails:
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
        token_invalidated_pool_emails = _gopay_token_invalidated_pool_emails(result, actual_email)
        cleanup_pool_emails = []
        for cleanup_email in [*rejected_pool_emails, *nonzero_blocked_pool_emails, *payment_failed_pool_emails]:
            if cleanup_email and cleanup_email not in cleanup_pool_emails:
                cleanup_pool_emails.append(cleanup_email)
        if params.delete_rejected_accounts:
            removed_pool_emails = _remove_gopay_rejected_accounts_from_pool(cleanup_pool_emails)
        if token_invalidated_pool_emails:
            token_invalidated_failed = _mark_pool_accounts_fail(
                token_invalidated_pool_emails,
                reason="gopay_token_invalidated",
                message="GoPay 返回 token_invalidated，重新登录刷新失败或重试后仍失效，账号已标记为 Fail/废弃",
                failure_stage="token_invalidated",
                log_context="gopay-token-invalidated",
            )
            result["token_invalidated_pool_emails"] = token_invalidated_pool_emails
            result["token_invalidated_failed_emails"] = token_invalidated_failed
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
            }
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
    task_params["pending_retry_attempts"] = pending_retry_attempts
    task_params.pop("auto_register_password", None)
    task_params.pop("gopay_auto_signup_hero_sms_api_key", None)
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
    _task_skip_signals[task["task_id"]] = skip_current_signal
    return task


@app.post("/api/tasks/paypal", status_code=202)
def post_paypal_task(params: PayPalTaskParams):
    if params.timeout_seconds < 0:
        raise HTTPException(status_code=400, detail="超时时间不能为负数")

    runner_mode = str(params.runner_mode or "").strip().lower()
    if runner_mode and runner_mode != "manual_checkout":
        raise HTTPException(status_code=400, detail="不支持的 PayPal 运行模式")
    paypal_mode = str(params.paypal_mode or "existing_account").strip().lower()
    if paypal_mode in {"login", "existing", "existing-account"}:
        paypal_mode = "existing_account"
    elif paypal_mode in {"signup", "register", "create-account"}:
        paypal_mode = "create_account"
    elif paypal_mode not in {"existing_account", "create_account"}:
        raise HTTPException(status_code=400, detail="paypal_mode 只支持 existing_account 或 create_account")

    from autoteam import cancel_signal
    from autoteam.accounts import (
        ACCOUNT_SOURCE_MANAGED,
        ACCOUNT_TYPE_PLUS,
        SEAT_CODEX,
        STATUS_ACTIVE,
        add_account,
        ensure_session_only_account,
        find_account,
        load_accounts,
        update_account,
    )
    from autoteam.auth_session_store import get_auth_session_file
    from autoteam.bind_audit import record_bind_audit
    from autoteam.config import normalize_proxy_url
    from autoteam.gopay_executor import _safe_email_summary, _safe_proxy_summary
    from autoteam.paypal_bind_executor import run_paypal_bind_task

    email = _normalized_email(params.email)
    account_emails = []
    seen_account_emails = set()
    for raw_email in params.account_emails or []:
        normalized = _normalized_email(raw_email)
        if normalized and normalized not in seen_account_emails:
            seen_account_emails.add(normalized)
            account_emails.append(normalized)
    checkout_url = str(params.checkout_url or "").strip()
    bind_link_payload = params.bind_link_payload if isinstance(params.bind_link_payload, dict) else {}
    sms_url = str(params.sms_url or "").strip()
    otp_channel = str(params.otp_channel or "sms").strip().lower() or "sms"
    proxy_url = str(params.proxy_url or "").strip()
    proxy_pool = _parse_proxy_pool_values(params.proxy_pool, params.proxy_pool_text)
    phone_accounts: list[dict] = []
    seen_phone_accounts: set[tuple[str, str, str]] = set()
    for raw_phone_account in params.phone_accounts or []:
        account_phone_number = str(raw_phone_account.phone_number or "").strip()
        account_sms_url = str(raw_phone_account.sms_url or "").strip()
        account_otp_channel = str(raw_phone_account.otp_channel or otp_channel or "sms").strip().lower()
        if account_otp_channel not in {"sms", "whatsapp"}:
            raise HTTPException(status_code=400, detail="phone_accounts otp_channel 只支持 sms 或 whatsapp")
        if not account_phone_number and not account_sms_url:
            continue
        if not account_phone_number or not account_sms_url:
            raise HTTPException(status_code=400, detail="phone_accounts 每项都必须填写 phone_number、sms_url")
        phone_key = (account_phone_number, account_sms_url, account_otp_channel)
        if phone_key in seen_phone_accounts:
            continue
        seen_phone_accounts.add(phone_key)
        phone_accounts.append(
            {
                "phone_number": account_phone_number,
                "sms_url": account_sms_url,
                "otp_channel": account_otp_channel,
            }
        )
    if phone_accounts:
        sms_url = str(phone_accounts[0].get("sms_url") or "").strip()
        otp_channel = str(phone_accounts[0].get("otp_channel") or otp_channel).strip().lower() or "sms"
        if not str(params.billing_phone or "").strip():
            params.billing_phone = str(phone_accounts[0].get("phone_number") or "").strip()
    try:
        normalized_proxy_url = normalize_proxy_url(proxy_url) if proxy_url else ""
    except Exception:
        normalized_proxy_url = ""
    normalized_proxy_pool: list[str] = []
    for raw_pool_proxy in proxy_pool:
        try:
            normalized = normalize_proxy_url(raw_pool_proxy)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"动态代理池格式错误: {raw_pool_proxy} ({exc})") from exc
        if normalized and normalized not in normalized_proxy_pool:
            normalized_proxy_pool.append(normalized)
    bind_proxy_url = proxy_url

    def _select_paypal_proxy() -> str:
        if normalized_proxy_pool:
            return random.choice(normalized_proxy_pool)
        return bind_proxy_url

    def _paypal_already_paid_text(value: Any) -> bool:
        normalized = re.sub(r"\s+", " ", str(value or "")).strip().lower()
        return bool(normalized) and any(
            marker in normalized
            for marker in (
                "user is paid",
                "user already paid",
                "user is already paid",
                "already a paid user",
                "already paid user",
                "already subscribed",
                "already has an active subscription",
                "用户已付费",
                "已是付费用户",
                "已有有效订阅",
            )
        )

    def _paypal_user_paid_success(candidate_email: str, message: str = "") -> dict:
        return {
            "status": "success",
            "failure_stage": "",
            "message": message or "ChatGPT 返回 User is already paid，账号已是付费用户，标记为 PayPal 绑定成功",
            "screenshot_paths": [],
            "email": candidate_email,
            "user_paid_skip": True,
        }

    if not email:
        raise HTTPException(status_code=400, detail="email 不能为空")
    if otp_channel not in {"sms", "whatsapp"}:
        raise HTTPException(status_code=400, detail="otp_channel 只支持 sms 或 whatsapp")
    if account_emails and email not in account_emails:
        account_emails.insert(0, email)
    if not checkout_url and not bind_link_payload:
        raise HTTPException(status_code=400, detail="checkout_url 不能为空，或提供 bind_link_payload 用于自动生成链接")
    if not params.manual_confirm:
        if paypal_mode == "existing_account":
            if not str(params.paypal_email or "").strip():
                raise HTTPException(status_code=400, detail="已有账号模式需要 paypal_email")
            if not str(params.paypal_password or "").strip():
                raise HTTPException(status_code=400, detail="已有账号模式需要 paypal_password")
        elif paypal_mode == "create_account":
            if not str(params.billing_phone or "").strip():
                raise HTTPException(status_code=400, detail="自动注册模式需要 billing_phone")
            if otp_channel == "whatsapp":
                sms_url = _default_whatsapp_otp_url()
            if not sms_url:
                raise HTTPException(status_code=400, detail="自动注册模式需要 sms_url")
            if not bool(params.autofill_enabled):
                if not str(params.billing_name or "").strip():
                    raise HTTPException(status_code=400, detail="手动账单信息模式需要 billing_name")
                if not str(params.billing_country or "").strip():
                    raise HTTPException(status_code=400, detail="手动账单信息模式需要 billing_country")
                if not str(params.billing_state or "").strip():
                    raise HTTPException(status_code=400, detail="手动账单信息模式需要 billing_state")
                if not str(params.billing_city or "").strip():
                    raise HTTPException(status_code=400, detail="手动账单信息模式需要 billing_city")
                if not str(params.billing_zip or "").strip():
                    raise HTTPException(status_code=400, detail="手动账单信息模式需要 billing_zip")
                if not str(params.billing_address1 or "").strip():
                    raise HTTPException(status_code=400, detail="手动账单信息模式需要 billing_address1")
                if not str(params.paypal_card_number or "").strip():
                    raise HTTPException(status_code=400, detail="自动注册模式需要 paypal_card_number")
                if not str(params.paypal_card_expiry or "").strip():
                    raise HTTPException(status_code=400, detail="自动注册模式需要 paypal_card_expiry")
                if not str(params.paypal_card_cvv or "").strip():
                    raise HTTPException(status_code=400, detail="自动注册模式需要 paypal_card_cvv")

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

    payload = {
        "runner_mode": "manual_checkout",
        "email": email,
        "account_emails": account_emails,
        "checkout_url": checkout_url,
        "bind_link_payload": bind_link_payload,
        "proxy_url": params.proxy_url,
        "proxy_pool_count": len(normalized_proxy_pool),
        "proxy_label": params.proxy_label,
        "proxy_bypass": params.proxy_bypass,
        "manual_confirm": bool(params.manual_confirm),
        "paypal_mode": paypal_mode,
        "paypal_email": params.paypal_email,
        "sms_url_present": bool(sms_url),
        "otp_channel": otp_channel,
        "phone_account_count": len(phone_accounts),
        "paypal_card_number_present": bool(str(params.paypal_card_number or "").strip()),
        "paypal_card_expiry_present": bool(str(params.paypal_card_expiry or "").strip()),
        "paypal_card_cvv_present": bool(str(params.paypal_card_cvv or "").strip()),
        "paypal_auto_login": (not bool(params.manual_confirm)) and bool(str(params.paypal_password or "").strip()),
        "autofill_enabled": bool(params.autofill_enabled),
        "billing_name": params.billing_name,
        "billing_email": params.billing_email,
        "billing_phone": params.billing_phone,
        "billing_country": params.billing_country,
        "billing_state": params.billing_state,
        "billing_city": params.billing_city,
        "billing_zip": params.billing_zip,
        "billing_address1": params.billing_address1,
        "billing_address2": params.billing_address2,
        "timeout_seconds": int(params.timeout_seconds or 60),
        "auto_oauth_after_success": bool(params.auto_oauth_after_success),
    }
    autofill_payload = {
        "name": params.billing_name,
        "email": params.billing_email or email,
        "phone": params.billing_phone,
        "country": params.billing_country,
        "state": params.billing_state,
        "city": params.billing_city,
        "zip": params.billing_zip,
        "address1": params.billing_address1,
        "address2": params.billing_address2,
        "card_number": params.paypal_card_number,
        "card_expiry": params.paypal_card_expiry,
        "card_cvv": params.paypal_card_cvv,
    }

    def _candidate_autofill_payload(candidate_email: str) -> dict:
        payload = dict(autofill_payload)
        payload["email"] = params.billing_email or candidate_email
        return payload

    def _normalize_paypal_phone_key(value: Any) -> str:
        raw = str(value or "").strip()
        digits = re.sub(r"\D+", "", raw)
        return digits or raw.lower()

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

        def _remember_invalid_phone(phone: Any) -> None:
            raw_phone = str(phone or "").strip()
            phone_key = _normalize_paypal_phone_key(raw_phone)
            if not phone_key or phone_key in invalid_phone_numbers:
                return
            invalid_phone_numbers.add(phone_key)
            invalid_phone_pool.append(raw_phone or phone_key)

        def _paypal_success_progress_fields() -> dict:
            return {
                "successful": len(successful_emails),
                "successful_emails": successful_emails[:],
            }

        def _handle_paypal_success_auth(success_email_value: str) -> None:
            success_email = _normalized_email(success_email_value)
            if not success_email:
                return
            if not params.auto_oauth_after_success:
                if success_email in session_cpa_scheduled_emails:
                    return
                session_cpa_scheduled_emails.add(success_email)
                _append_task_progress(
                    task_id,
                    {
                        "stage": "paypal_session_cpa_convert_started",
                        "email": success_email,
                        **_paypal_success_progress_fields(),
                        "message": f"PayPal 绑定成功，正在直接转换 CPA 认证: {success_email}",
                    },
                )
                try:
                    cpa_result = _convert_account_auth_session_to_cpa_auth(
                        success_email,
                        force_account_type=ACCOUNT_TYPE_PLUS,
                    )
                    session_cpa_converted_emails.append(success_email)
                    _append_task_progress(
                        task_id,
                        {
                            "stage": "paypal_session_cpa_convert_done",
                            "email": success_email,
                            "auth_file": cpa_result.get("auth_file") or "",
                            "filename": cpa_result.get("filename") or "",
                            "id_token_synthetic": bool(cpa_result.get("id_token_synthetic")),
                            **_paypal_success_progress_fields(),
                            "message": f"CPA 认证已生成: {success_email}",
                            "level": "success",
                        },
                    )
                    logger.info(
                        "[paypal] CPA auth converted from auth_session after PayPal success: task_id=%s email=%s auth_file=%s",
                        task_id[:8] or "<unknown>",
                        _safe_email_summary(success_email),
                        cpa_result.get("auth_file") or "",
                    )
                except Exception as exc:
                    session_cpa_failed_auths.append({"email": success_email, "error": str(exc)})
                    _append_task_progress(
                        task_id,
                        {
                            "stage": "paypal_session_cpa_convert_failed",
                            "email": success_email,
                            **_paypal_success_progress_fields(),
                            "message": f"CPA 认证转换失败，PayPal 绑定已成功: {success_email}: {exc}",
                            "level": "warn",
                        },
                    )
                    logger.warning(
                        "[paypal] CPA auth conversion after PayPal success failed: task_id=%s email=%s error=%s",
                        task_id[:8] or "<unknown>",
                        _safe_email_summary(success_email),
                        exc,
                    )
                return

            if success_email in oauth_scheduled_emails:
                return
            oauth_scheduled_emails.add(success_email)
            _append_task_progress(
                task_id,
                {
                    "stage": "paypal_oauth_login_started",
                    "email": success_email,
                    **_paypal_success_progress_fields(),
                    "message": f"PayPal 绑定成功，已在后台开始 OAuth 补登录: {success_email}",
                },
            )

            def _oauth_worker():
                from autoteam.codex_auth import CodexOAuthPhoneRequired

                max_attempts = 3
                retry_delay_seconds = 3
                for attempt in range(1, max_attempts + 1):
                    try:
                        latest_account = find_account(load_accounts(), success_email) or {"email": success_email}
                        oauth_result = _run_account_codex_login_once(success_email, latest_account, headless=False)
                        oauth_successful_emails.append(success_email)
                        _append_task_progress(
                            task_id,
                            {
                                "stage": "paypal_oauth_login_done",
                                "email": success_email,
                                "auth_file": oauth_result.get("auth_file") or "",
                                "attempt": attempt,
                                "max_attempts": max_attempts,
                                **_paypal_success_progress_fields(),
                                "message": f"OAuth 补登录成功: {success_email}",
                                "level": "success",
                            },
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
                        oauth_failed_emails.append(
                            {
                                "email": success_email,
                                "error": str(exc),
                                "failure_stage": "oauth_phone_required",
                                "removed_pool_emails": result_payload.get("removed_pool_emails") or [],
                            }
                        )
                        _append_task_progress(
                            task_id,
                            {
                                "stage": "paypal_oauth_phone_required_removed",
                                "email": success_email,
                                "removed_pool_emails": result_payload.get("removed_pool_emails") or [],
                                "attempt": attempt,
                                "max_attempts": max_attempts,
                                **_paypal_success_progress_fields(),
                                "message": result_payload["message"],
                                "level": "warn",
                            },
                        )
                        return
                    except Exception as exc:
                        if attempt < max_attempts:
                            _append_task_progress(
                                task_id,
                                {
                                    "stage": "paypal_oauth_login_retrying",
                                    "email": success_email,
                                    "attempt": attempt,
                                    "next_attempt": attempt + 1,
                                    "max_attempts": max_attempts,
                                    **_paypal_success_progress_fields(),
                                    "message": f"OAuth 补登录失败，准备重试 {attempt + 1}/{max_attempts}: {success_email}: {exc}",
                                    "level": "warn",
                                },
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
                        oauth_failed_emails.append({"email": success_email, "error": str(exc), "attempts": max_attempts})
                        _append_task_progress(
                            task_id,
                            {
                                "stage": "paypal_oauth_login_failed",
                                "email": success_email,
                                "attempt": attempt,
                                "max_attempts": max_attempts,
                                **_paypal_success_progress_fields(),
                                "message": f"OAuth 补登录失败: {success_email}: {exc}",
                                "level": "error",
                            },
                        )
                        logger.exception(
                            "[paypal] OAuth login after PayPal success failed: task_id=%s email=%s attempts=%d",
                            task_id[:8] or "<unknown>",
                            _safe_email_summary(success_email),
                            max_attempts,
                        )
                        return

            threading.Thread(target=_oauth_worker, name=f"paypal-oauth-{success_email[:24]}", daemon=True).start()

        try:
            for index, candidate_email in enumerate(candidates, start=1):
                if cancel_signal.is_cancelled():
                    break
                stop_after_current_candidate = False
                current_candidate_phone = ""
                selected_proxy_url = _select_paypal_proxy()
                _append_task_progress(
                    task_id,
                    {
                        "stage": "paypal_starting",
                        "email": candidate_email,
                        "current": index,
                        "total": len(candidates),
                        "proxy_label": params.proxy_label,
                        "message": len(candidates) > 1
                            and f"PayPal 批量任务启动中 ({index}/{len(candidates)}): {candidate_email}"
                            or "PayPal 任务启动中",
                    },
                )
                if normalized_proxy_pool:
                    _append_task_progress(
                        task_id,
                        {
                            "stage": "paypal_proxy_selected",
                            "email": candidate_email,
                            "current": index,
                            "total": len(candidates),
                            "proxy_label": params.proxy_label,
                            "proxy_pool_count": len(normalized_proxy_pool),
                            "message": f"已从动态代理池随机选择代理: {_safe_proxy_summary(selected_proxy_url)}",
                        },
                    )
                try:
                    effective_checkout_url = checkout_url
                    if not effective_checkout_url:
                        access_token = _extract_account_access_token(candidate_email)
                        if not access_token:
                            single_result = {
                                "status": "failed",
                                "failure_stage": "generate_checkout",
                                "message": f"账号缺少可用 access_token，无法自动生成 checkout 链接: {candidate_email}",
                                "screenshot_paths": [],
                                "email": candidate_email,
                            }
                        else:
                            try:
                                generated = _generate_checkout_link(access_token, bind_link_payload)
                            except HTTPException as exc:
                                checkout_exc = exc
                                fallback_access_token = access_token
                                if getattr(exc, "status_code", None) == 401:
                                    refreshed_access_token = _refresh_account_access_token(candidate_email)
                                    if refreshed_access_token and refreshed_access_token != access_token:
                                        fallback_access_token = refreshed_access_token
                                        _append_task_progress(
                                            task_id,
                                            {
                                                "stage": "paypal_checkout_token_refreshed",
                                                "email": candidate_email,
                                                "current": index,
                                                "total": len(candidates),
                                                "message": f"生成 checkout 返回 401，已刷新 access_token 并重试: {candidate_email}",
                                            },
                                        )
                                        try:
                                            generated = _generate_checkout_link(refreshed_access_token, bind_link_payload)
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
                                        raise checkout_exc
                                    _append_task_progress(
                                        task_id,
                                        {
                                            "stage": "paypal_checkout_browser_fallback",
                                            "email": candidate_email,
                                            "current": index,
                                            "total": len(candidates),
                                            "message": f"HTTP 生成 checkout 失败，改用浏览器登录态回退: {candidate_email}",
                                            "level": "warn",
                                        },
                                    )
                                    try:
                                        generated = _generate_checkout_link_via_browser(
                                            fallback_access_token,
                                            bind_link_payload,
                                            email=candidate_email,
                                            proxy_url=selected_proxy_url,
                                            proxy_bypass=params.proxy_bypass,
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
                                        {
                                            "stage": "paypal_checkout_browser_generated",
                                            "email": candidate_email,
                                            "current": index,
                                            "total": len(candidates),
                                            "message": f"浏览器登录态已生成 checkout 链接 ({index}/{len(candidates)}): {candidate_email}",
                                        },
                                    )
                            effective_checkout_url = str(generated.get("url") or "").strip()
                            last_checkout_url = effective_checkout_url or last_checkout_url
                            _append_task_progress(
                                task_id,
                                {
                                    "stage": "paypal_checkout_generated",
                                    "email": candidate_email,
                                    "current": index,
                                    "total": len(candidates),
                                    "checkout_url": effective_checkout_url,
                                    "message": f"已生成 checkout 链接 ({index}/{len(candidates)}): {candidate_email}",
                                },
                            )
                            single_result = None
                    else:
                        single_result = None
                    if single_result is None:
                        active_phone_accounts = phone_accounts
                        current_sms_url = sms_url
                        current_otp_channel = otp_channel
                        current_autofill_payload = _candidate_autofill_payload(candidate_email)
                        if phone_accounts:
                            active_phone_accounts = [
                                account_phone
                                for account_phone in phone_accounts
                                if _normalize_paypal_phone_key(account_phone.get("phone_number")) not in invalid_phone_numbers
                            ]
                            if not active_phone_accounts:
                                _append_task_progress(
                                    task_id,
                                    {
                                        "stage": "paypal_phone_pool_exhausted",
                                        "email": candidate_email,
                                        "current": index,
                                        "total": len(candidates),
                                        "message": "手机号池已无可用号码，停止后续 PayPal 绑定任务",
                                        "level": "error",
                                    },
                                )
                                single_result = {
                                    "status": "failed",
                                    "failure_stage": "paypal_phone_pool_exhausted",
                                    "message": "手机号池已无可用号码",
                                    "screenshot_paths": [],
                                    "email": candidate_email,
                                }
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
                            def _handle_paypal_progress(event: dict[str, Any]) -> None:
                                stage = str(event.get("stage") or "").strip()
                                if stage in {
                                    "paypal_phone_rejected_waiting_dismiss",
                                    "paypal_phone_rejected_rotate",
                                    "paypal_phone_rejected_final",
                                }:
                                    _remember_invalid_phone(event.get("rejected_phone"))
                                _append_task_progress(
                                    task_id,
                                    {**event, "email": candidate_email, "current": index, "total": len(candidates)},
                                )

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
                                paypal_browser=params.paypal_browser,
                            )
                except HTTPException as exc:
                    exc_message = str(exc.detail) if getattr(exc, "detail", None) else str(exc)
                    if _paypal_already_paid_text(exc_message):
                        single_result = _paypal_user_paid_success(candidate_email, exc_message)
                    else:
                        single_result = {
                            "status": "failed",
                            "failure_stage": "generate_checkout",
                            "message": exc_message,
                            "screenshot_paths": [],
                            "email": candidate_email,
                        }
                except Exception as exc:
                    logger.exception("[paypal] candidate error: email=%s", candidate_email)
                    single_result = {
                        "status": "failed",
                        "failure_stage": "post_submit",
                        "message": f"PayPal 账号执行异常: {exc}",
                        "screenshot_paths": [],
                        "email": candidate_email,
                    }
                single_result = dict(single_result or {})
                single_result["email"] = candidate_email
                single_result["checkout_url"] = effective_checkout_url or single_result.get("checkout_url") or ""
                if single_result.get("failure_stage") == "paypal_phone_rejected":
                    _remember_invalid_phone(single_result.get("rejected_phone") or current_candidate_phone)
                    single_result["invalid_phone_numbers"] = invalid_phone_pool[:]
                last_checkout_url = single_result["checkout_url"] or last_checkout_url
                result = single_result
                update_fields = {
                    "last_bind_status": "cancelled" if cancel_signal.is_cancelled() and single_result.get("status") != "success" else single_result.get("status") or "failed",
                    "last_bind_at": time.time(),
                    "last_checkout_url": single_result.get("checkout_url") or "",
                    "last_proxy_label": params.proxy_label,
                    "last_bind_task_id": task_id,
                    "last_bind_message": single_result.get("message") or "",
                    "last_bind_failure_stage": single_result.get("failure_stage") or "",
                }
                if single_result.get("status") == "success":
                    update_fields.update(
                        {
                            "status": STATUS_ACTIVE,
                            "account_type": ACCOUNT_TYPE_PLUS,
                            "seat_type": SEAT_CODEX,
                            "account_source": ACCOUNT_SOURCE_MANAGED,
                            "last_bind_provider": "paypal",
                            "plus_bound_at": update_fields["last_bind_at"],
                        }
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
                if single_result.get("status") == "success" and not updated_account:
                    logger.warning(
                        "[paypal] PayPal success account was not persisted: task_id=%s email=%s",
                        task_id[:8] or "<unknown>",
                        _safe_email_summary(candidate_email),
                    )
                if single_result.get("status") == "success":
                    if candidate_email not in successful_emails:
                        successful_emails.append(candidate_email)
                    _handle_paypal_success_auth(candidate_email)
                else:
                    if candidate_email not in failed_emails:
                        failed_emails.append(candidate_email)
                    if candidate_email in _paypal_nonzero_blocked_pool_emails(single_result, candidate_email):
                        if candidate_email not in nonzero_blocked_emails:
                            nonzero_blocked_emails.append(candidate_email)
                        removed = _remove_pool_accounts_from_local_and_mail(
                            [candidate_email],
                            log_context="paypal-nonzero",
                            reason="paypal_nonzero_amount_blocked",
                            message="PayPal checkout 今日应付金额非 0，账号已从本地号池删除",
                        )
                        for removed_email in removed:
                            if removed_email not in removed_pool_emails:
                                removed_pool_emails.append(removed_email)
                        _append_task_progress(
                            task_id,
                            {
                                "stage": "paypal_nonzero_amount_blocked_rotate",
                                "email": candidate_email,
                                "current": index,
                                "total": len(candidates),
                                "message": f"今日应付非 0，已删除并跳过账号: {candidate_email}",
                                "level": "warn",
                            },
                        )
                record_bind_audit(
                    {
                        "task_id": task_id,
                        "email": candidate_email,
                        "checkout_url": single_result.get("checkout_url") or "",
                        "proxy_label": params.proxy_label,
                        "proxy_url": selected_proxy_url or "",
                        "manual_confirm": bool(params.manual_confirm),
                        "paypal_mode": paypal_mode,
                        "paypal_auto_login": (not bool(params.manual_confirm)) and bool(str(params.paypal_password or "").strip()),
                        "autofill_enabled": bool(params.autofill_enabled),
                        "status": single_result.get("status") or "failed",
                        "task_status": "completed" if single_result.get("status") == "success" else "failed",
                        "failure_stage": single_result.get("failure_stage") or "",
                        "message": single_result.get("message") or "",
                        "started_at": started_at,
                        "finished_at": time.time(),
                        "screenshot_paths": single_result.get("screenshot_paths") or [],
                        "flow": f"paypal_{paypal_mode}",
                        "category": "paypal",
                        "provider": "paypal",
                    }
                )
                if stop_after_current_candidate:
                    break
        except Exception as exc:
            logger.exception("[paypal] unexpected error")
            result = {
                "status": "failed",
                "failure_stage": "post_submit",
                "message": f"PayPal 任务执行异常: {exc}",
                "screenshot_paths": [],
            }

        result = dict(result or {})
        result.setdefault("status", "failed")
        result.setdefault("failure_stage", "")
        result.setdefault("message", "")
        result.setdefault("screenshot_paths", [])
        result["email"] = result.get("email") or email
        result["checkout_url"] = result.get("checkout_url") or last_checkout_url or checkout_url
        result["proxy_label"] = params.proxy_label
        result["manual_confirm"] = bool(params.manual_confirm)
        result["paypal_mode"] = paypal_mode
        result["paypal_auto_login"] = (not bool(params.manual_confirm)) and bool(str(params.paypal_password or "").strip())
        result["autofill_enabled"] = bool(params.autofill_enabled)
        result["provider"] = "paypal"
        result["account_emails"] = candidates
        result["successful_emails"] = successful_emails
        result["failed_emails"] = failed_emails
        result["nonzero_blocked_emails"] = nonzero_blocked_emails
        result["removed_pool_emails"] = removed_pool_emails
        if invalid_phone_pool:
            result["invalid_phone_numbers"] = invalid_phone_pool[:]
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
        if len(candidates) > 1:
            if successful_emails:
                result["status"] = "success"
                result["failure_stage"] = ""
                result["message"] = f"PayPal 批量绑定完成: 成功 {len(successful_emails)}/{len(candidates)} 个账号"
            elif nonzero_blocked_emails and len(nonzero_blocked_emails) == len(candidates):
                result["status"] = "failed"
                result["failure_stage"] = "browser_charge_guard"
                result["message"] = f"PayPal 批量绑定失败: {len(candidates)} 个账号今日应付均非 0"
            else:
                result["status"] = "failed"
                result["message"] = result.get("message") or f"PayPal 批量绑定失败: 尝试 {len(candidates)} 个账号均未成功"

        if cancel_signal.is_cancelled() and result.get("status") != "success":
            task_status = "cancelled"
        elif result.get("status") == "success":
            task_status = "completed"
        else:
            task_status = "failed"
        result["task_status"] = task_status

        _append_task_progress(
            task_id,
            {
                "stage": "paypal_completed" if result.get("status") == "success" else "paypal_finished",
                "bind_status": result.get("status") or "failed",
                "task_status": task_status,
                "successful": len(successful_emails),
                "failed": len(failed_emails),
                "total": len(candidates),
                "message": result.get("message") or "",
            },
        )

        if result.get("status") != "success":
            raise TaskResultError(result.get("message") or "PayPal 任务失败", task_result=result)
        return result

    task = _start_task("paypal", _run, payload, task_group=TASK_GROUP_PAYPAL)
    return task


@app.post("/api/tasks/check", status_code=202)
def post_check(params: CheckParams = CheckParams()):
    """检查所有 active 账号额度（后台执行）。include_standby=True 时追加探测 standby 池。"""
    from autoteam.manager import cmd_check

    include_standby = bool(params.include_standby)

    def _run():
        exhausted = cmd_check(include_standby=include_standby)
        return {"exhausted": [a["email"] for a in exhausted]}

    task = _start_task("check", _run, {"include_standby": include_standby}, task_group=TASK_GROUP_QUOTA)
    return task


@app.post("/api/tasks/rotate", status_code=202)
def post_rotate(params: TaskParams = TaskParams()):
    """智能轮转（后台执行）"""
    from autoteam.manager import cmd_rotate

    task = _start_task("rotate", cmd_rotate, {"target": params.target}, params.target, task_group=TASK_GROUP_TEAM)
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
        task_group=TASK_GROUP_TEAM,
    )
    return task


@app.post("/api/tasks/add", status_code=202)
def post_add(params: ManualRegisterParams = ManualRegisterParams()):
    """注册账号（后台执行，注册成功后继续执行 personal OAuth 并生成 auth_file）"""
    from autoteam.manager import cmd_register_accounts
    from autoteam.identity import random_password
    from autoteam.runtime_config import get_register_domain, get_register_domains

    from autoteam.setup_wizard import get_mail_provider

    prefix = (params.prefix or "").strip() or None
    password = (params.password or "").strip() or None
    mail_provider = get_mail_provider(params.mail_provider) if params.mail_provider else ""
    luckmail_email_type = (params.luckmail_email_type or "").strip()
    luckmail_preferred_domain = (params.luckmail_preferred_domain or "").strip().lstrip("@")
    luckmail_preferred_domains = []
    seen_luckmail_domains = set()
    for raw_domain in list(params.luckmail_preferred_domains or []) + ([luckmail_preferred_domain] if luckmail_preferred_domain else []):
        cleaned = str(raw_domain or "").strip().lstrip("@")
        key = cleaned.lower()
        if key in seen_luckmail_domains:
            continue
        seen_luckmail_domains.add(key)
        luckmail_preferred_domains.append(cleaned)
    resolved_password = password or random_password()
    mode = (params.mode or "single").strip().lower()
    register_mode = "protocol" if bool(params.protocol_register) else "browser"
    count = max(1, int(params.count or 1))
    concurrency = max(1, min(20, int(params.concurrency or 1)))
    interval_seconds = max(0.0, float(params.interval_seconds or 0.0))
    jitter_min_seconds = max(0.0, float(params.jitter_min_seconds or 0.0))
    jitter_max_seconds = max(0.0, float(params.jitter_max_seconds or 0.0))
    if mode not in ("single", "batch"):
        raise HTTPException(status_code=400, detail="mode 只支持 single 或 batch")

    configured_domains = get_register_domains()
    domain_required = mail_provider not in {"luckmail", "outlook"}

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

    if not selected_domains and domain_required:
        if selected_domain:
            _validate_domain(selected_domain)
        else:
            selected_domain = get_register_domain()
        if selected_domain:
            selected_domains = [selected_domain]

    if not selected_domains and domain_required:
        raise HTTPException(status_code=400, detail="未配置可用注册域名")

    if selected_domains:
        selected_domain = selected_domains[0]
    elif domain_required:
        selected_domain = ""

    if mode == "single":
        count = 1
        concurrency = 1
        jitter_min_seconds = 0.0
        jitter_max_seconds = 0.0
        selected_domains = [selected_domain] if selected_domain else []
    if jitter_min_seconds > jitter_max_seconds:
        raise HTTPException(status_code=400, detail="随机抖动区间必须满足 min <= max")

    task_params = {
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
        "mail_provider": mail_provider or "<default>",
        "luckmail_email_type": luckmail_email_type or "",
        "luckmail_preferred_domain": luckmail_preferred_domain or "",
        "luckmail_preferred_domains": luckmail_preferred_domains,
        "post_register_oauth": bool(params.post_register_oauth),
        "register_mode": register_mode,
    }

    def _run_register(task_id: str, **_ignored_kwargs):
        def _register_progress(progress: dict):
            _append_task_progress(task_id, progress)

        return cmd_register_accounts(
            count=count,
            concurrency=concurrency,
            interval_seconds=interval_seconds,
            jitter_min_seconds=jitter_min_seconds,
            jitter_max_seconds=jitter_max_seconds,
            email_prefix=prefix,
            password=resolved_password,
            domain=selected_domain,
            domains=selected_domains,
            mail_provider=mail_provider or None,
            luckmail_email_type=luckmail_email_type or None,
            luckmail_preferred_domain=luckmail_preferred_domain,
            luckmail_preferred_domains=luckmail_preferred_domains,
            post_register_oauth=bool(params.post_register_oauth),
            register_mode=register_mode,
            progress_callback=_register_progress,
        )

    task = _start_task(
        "register",
        _run_register,
        task_params,
        count=count,
        concurrency=concurrency,
        interval_seconds=interval_seconds,
        jitter_min_seconds=jitter_min_seconds,
        jitter_max_seconds=jitter_max_seconds,
        email_prefix=prefix,
        password=resolved_password,
        domain=selected_domain,
        domains=selected_domains,
        mail_provider=mail_provider or None,
        luckmail_email_type=luckmail_email_type or None,
        luckmail_preferred_domain=luckmail_preferred_domain,
        luckmail_preferred_domains=luckmail_preferred_domains,
        post_register_oauth=bool(params.post_register_oauth),
        task_group=TASK_GROUP_REGISTER,
        pass_task_id=True,
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
        task_group=TASK_GROUP_TEAM,
    )
    return task


@app.post("/api/tasks/cleanup", status_code=202)
def post_cleanup(params: CleanupParams = CleanupParams()):
    """清理多余成员（后台执行）"""
    from autoteam.manager import cmd_cleanup

    task = _start_task("cleanup", cmd_cleanup, {"max_seats": params.max_seats}, params.max_seats, task_group=TASK_GROUP_TEAM)
    return task


@app.get("/api/tasks")
def get_tasks(detail: bool = False):
    """查看所有任务。

    默认返回轻量摘要，避免仪表盘轮询时传输完整 progress_events。
    需要完整日志时使用 /api/tasks/{task_id} 或 detail=true。
    """
    return _merged_task_snapshots(compact=not detail)


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str):
    """查看任务状态"""
    task = _tasks.get(task_id)
    if not task:
        for snapshot in _load_task_snapshots():
            if str(snapshot.get("task_id") or "") == task_id:
                return snapshot
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _task_public_snapshot(task)


@app.post("/api/tasks/cancel", status_code=202)
def post_task_cancel(params: TaskControlParams = TaskControlParams()):
    """
    请求当前正在运行的任务在下一个安全点退出。
    协作式:后台 worker 在每个批次/账号边界检查 cancel_signal.is_cancelled(),
    调用这里后等 10-30s 让当前步骤跑完,任务状态会在 task["status"] 里显示为 "cancelled"。
    """
    from autoteam import cancel_signal

    task = _find_control_task(params)
    task_id = str(task.get("task_id") or "")
    if task.get("status") not in ("running", "pending"):
        raise HTTPException(status_code=400, detail=f"任务当前状态 {task.get('status')} 无法取消")
    cancel_event = _task_cancel_signals.get(task_id)
    if cancel_event is not None:
        cancel_signal.request_cancel_event(cancel_event, f"手动停止 task={task_id[:8]}")
    else:
        cancel_signal.request_cancel(f"手动停止 task={task_id[:8]}")
    task["cancel_requested"] = True
    return {
        "message": "已请求中止,等待当前步骤安全退出",
        "task_id": task_id,
        "command": task.get("command"),
        "task_group": task.get("task_group"),
    }


@app.post("/api/tasks/skip-current", status_code=202)
def post_task_skip_current(params: TaskControlParams = TaskControlParams()):
    """请求 GoPay 批量任务跳过当前账号，并在安全点切换到下一个账号。"""
    task = _find_control_task(params, default_group=TASK_GROUP_GOPAY, command="gopay-bind")
    task_id = str(task.get("task_id") or "")
    if task.get("status") not in ("running", "pending"):
        raise HTTPException(status_code=400, detail=f"任务当前状态 {task.get('status')} 无法跳过")
    if task.get("command") != "gopay-bind":
        raise HTTPException(status_code=400, detail="当前任务不支持跳过账号")

    params = task.get("params") if isinstance(task.get("params"), dict) else {}
    account_emails = params.get("account_emails") if isinstance(params.get("account_emails"), list) else []
    if len(account_emails) <= 1:
        raise HTTPException(status_code=400, detail="当前 GoPay 任务没有下一个账号可切换")

    skip_signal = _task_skip_signals.get(task_id)
    if skip_signal is None:
        raise HTTPException(status_code=400, detail="当前 GoPay 任务不支持跳过账号")
    skip_signal.set()
    task["skip_current_requested"] = True
    _append_task_progress(
        task_id,
        {
            "stage": "gopay_skip_current_requested",
            "message": "已请求跳过当前账号，等待当前步骤在安全点退出后切换下一个账号",
        }
    )
    logger.info("[API] requested GoPay current-account skip: task=%s", task_id[:8])
    return {
        "message": "已请求跳过当前账号，等待切换下一个账号",
        "task_id": task_id,
        "command": task.get("command"),
        "task_group": task.get("task_group"),
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
        from autoteam import sqlite_store

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
        from autoteam import sqlite_store

        sqlite_store.set_json("config", "auto_refresh_quota", _auto_refresh_quota_config.copy())
    except Exception as exc:
        logger.warning("[刷新凭证] 保存自动刷新配置失败: %s", exc)


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
                    from autoteam.manager import cmd_rotate

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
                        task_group=TASK_GROUP_TEAM,
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


class AutoRefreshQuotaConfig(BaseModel):
    enabled: bool | None = None
    interval: int = 0  # 自动刷新凭证间隔（秒），0 表示关闭


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


@app.get("/api/config/auto-refresh-quota")
def get_auto_refresh_quota_config():
    """获取自动刷新凭证配置。"""
    return _auto_refresh_quota_config.copy()


@app.put("/api/config/auto-refresh-quota")
def set_auto_refresh_quota_config(cfg: AutoRefreshQuotaConfig):
    """修改自动刷新凭证配置（运行时生效，写入 SQLite）。"""
    interval = max(0, int(cfg.interval or 0))
    enabled = bool(cfg.enabled) if cfg.enabled is not None else interval > 0
    if not enabled or interval <= 0:
        _auto_refresh_quota_config["enabled"] = False
        _auto_refresh_quota_config["interval"] = 0
    else:
        _auto_refresh_quota_config["enabled"] = True
        _auto_refresh_quota_config["interval"] = max(60, interval)
    _save_auto_refresh_quota_config()
    _auto_refresh_quota_restart.set()
    logger.info(
        "[刷新凭证] 自动刷新配置已更新: enabled=%s interval=%ds",
        _auto_refresh_quota_config["enabled"],
        _auto_refresh_quota_config["interval"],
    )
    return _auto_refresh_quota_config.copy()


@app.on_event("startup")
def _start_auto_check():
    try:
        from autoteam import sqlite_store

        sqlite_store.initialize()
        _load_auto_refresh_quota_config()
        cancelled_tasks = _cancel_orphaned_task_snapshots()
        if cancelled_tasks:
            logger.warning("[启动] 已取消 %d 个后端重启后残留的运行中任务快照", cancelled_tasks)
    except Exception as exc:
        logger.warning("[启动] 初始化 SQLite 存储失败: %s", exc)

    try:
        from autoteam.auth_storage import ensure_auth_file_permissions

        fixed = ensure_auth_file_permissions()
        if fixed:
            logger.info("[启动] 已修复 %d 个 auths 认证文件权限", fixed)
    except Exception as exc:
        logger.warning("[启动] 修复 auths 认证文件权限失败: %s", exc)

    try:
        from autoteam.account_hub import start_auto_upload_loop

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


@app.on_event("shutdown")
def _stop_auto_check():
    _auto_check_stop.set()
    _auto_refresh_quota_stop.set()
    _auto_refresh_quota_restart.set()
    try:
        from autoteam.account_hub import stop_auto_upload_loop

        stop_auto_upload_loop()
    except Exception:
        pass
    try:
        from autoteam.whatsapp_otp import get_default_listener

        get_default_listener().stop()
    except Exception:
        pass


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

    if not os.environ.get("AUTOTEAM_LOCAL_BASE_URL"):
        local_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
        os.environ["AUTOTEAM_LOCAL_BASE_URL"] = f"http://{local_host}:{port}"

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
