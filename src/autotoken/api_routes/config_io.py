"""Configuration import/export and account-pool routes."""

import json
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import AliasChoices, BaseModel, Field

from autotoken.core.paths import resolve_project_config_path
from autotoken.core.textio import parse_env_line, read_text

CONFIG_IMPORT_MAX_BYTES = 2 * 1024 * 1024
OUTLOOK_ACCOUNTS_IMPORT_MAX_BYTES = 2 * 1024 * 1024
ICLOUD_ACCOUNTS_IMPORT_MAX_BYTES = 2 * 1024 * 1024


class OutlookAccountsImportParams(BaseModel):
    filename: str = ""
    content: str


class OutlookAccountsDeleteParams(BaseModel):
    emails: list[str] = Field(default_factory=list)


class ICloudAccountsImportParams(BaseModel):
    filename: str = ""
    content: str


class ICloudAccountsDeleteParams(BaseModel):
    emails: list[str] = Field(default_factory=list)


class ConfigImportParams(BaseModel):
    config: dict | None = None
    content: str = ""
    overwrite_empty: bool = Field(True, validation_alias=AliasChoices("overwrite_empty", "overwriteEmpty"))


def _env_config_keys() -> list[str]:
    from autotoken.settings.setup_wizard import ENV_EXAMPLE

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
        "AUTOTOKEN_LOCAL_BASE_URL",
        "ROXYBROWSER_API_HOST",
        "ROXYBROWSER_API_TOKEN",
        "GOPAY_AUTO_REGISTER_BIND_DELAY_MIN",
        "GOPAY_AUTO_REGISTER_BIND_DELAY_MAX",
        "GOPAY_AUTO_SIGNUP_WALLET_ATTEMPTS",
        "GOPAY_AUTO_SIGNUP_WALLET_POOL_TTL_SECONDS",
        "OAUTH_PHONE_SMS_PROVIDER",
        "OAUTH_HERO_SMS_API_KEY",
        "OAUTH_HERO_SMS_MAX_PRICE",
        "OAUTH_HERO_SMS_BASE_URL",
        "OAUTH_HERO_SMS_COUNTRY",
        "OAUTH_HERO_SMS_SERVICE",
        "OAUTH_SMSBOWER_API_KEY",
        "OAUTH_SMSBOWER_MAX_PRICE",
        "OAUTH_SMSBOWER_BASE_URL",
        "OAUTH_SMSBOWER_COUNTRY",
        "OAUTH_SMSBOWER_SERVICE",
        "OAUTH_OASIS_SMS_BASE_URL",
        "OAUTH_OASIS_SMS_CDKS",
        "OAUTH_OASIS_SMS_CDK_FILE",
        "OAUTH_OASIS_SMS_POLL_ATTEMPTS",
        "OAUTH_OASIS_SMS_POLL_INTERVAL_MS",
        "OAUTH_OASIS_SMS_ACCOUNT_MAP_FILE",
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
        raw_text = str(params.content or "")
        if len(raw_text.encode("utf-8", errors="ignore")) > CONFIG_IMPORT_MAX_BYTES:
            raise HTTPException(status_code=400, detail="配置导入内容过大，最多支持 2MB JSON")
        text = raw_text.strip()
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

    from autotoken.settings import config as config_module

    importlib.reload(config_module)
    try:
        from autotoken import mail as mail_module

        importlib.reload(mail_module)
    except Exception:
        pass


def _resolve_outlook_accounts_file() -> Path:
    from autotoken.core.paths import PROJECT_ROOT
    from autotoken.settings.setup_wizard import _read_env, _write_env

    env = _read_env()
    raw = str(env.get("OUTLOOK_ACCOUNTS_FILE") or os.environ.get("OUTLOOK_ACCOUNTS_FILE") or "").strip()
    if not raw:
        raw = "data/outlook_accounts.txt"
        _write_env("OUTLOOK_ACCOUNTS_FILE", raw)
        os.environ["OUTLOOK_ACCOUNTS_FILE"] = raw
    path = resolve_project_config_path(raw, project_root=PROJECT_ROOT)
    if path is None:
        raise HTTPException(status_code=400, detail="OUTLOOK_ACCOUNTS_FILE 不能指向项目目录外")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_icloud_accounts_file() -> Path:
    from autotoken.core.paths import PROJECT_ROOT
    from autotoken.settings.setup_wizard import _read_env, _write_env

    env = _read_env()
    raw = str(env.get("ICLOUD_ACCOUNTS_FILE") or os.environ.get("ICLOUD_ACCOUNTS_FILE") or "").strip()
    if not raw:
        raw = "data/icloud_accounts.txt"
        _write_env("ICLOUD_ACCOUNTS_FILE", raw)
        os.environ["ICLOUD_ACCOUNTS_FILE"] = raw
    path = resolve_project_config_path(raw, project_root=PROJECT_ROOT)
    if path is None:
        raise HTTPException(status_code=400, detail="ICLOUD_ACCOUNTS_FILE 不能指向项目目录外")
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


def _split_icloud_account_lines(content: str) -> list[str]:
    lines: list[str] = []
    for line in str(content or "").replace("\ufeff", "").replace(";", "\n").splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        lines.append(value)
    return lines


def _load_outlook_pool_status(target: Path) -> dict[str, Any]:
    from autotoken.mail.base import normalize_email_addr
    from autotoken.mail.outlook import OutlookMailProvider
    from autotoken.storage.accounts import load_accounts
    from autotoken.storage.outlook_pool import list_registered_emails

    content = read_text(target) if target.exists() else ""
    registered_emails = {normalize_email_addr(account.get("email")) for account in load_accounts() if account.get("email")}
    registered_emails.update(list_registered_emails())
    skipped_emails = OutlookMailProvider._registered_emails()

    entries: list[dict[str, Any]] = []
    invalid = 0
    seen: set[str] = set()
    for line in _split_outlook_account_lines(content):
        account = OutlookMailProvider._parse_account_line(line)
        if not account or not account.validate():
            invalid += 1
            continue
        email = account.email.lower()
        if email in seen:
            continue
        seen.add(email)
        registered = email in registered_emails
        unavailable = email in skipped_emails and not registered
        status = "registered" if registered else ("unavailable" if unavailable else "available")
        entries.append(
            {
                "email": account.email,
                "status": status,
                "registered": registered,
                "available": status == "available",
                "has_oauth": account.has_oauth(),
                "has_mailapi": account.has_mailapi(),
            }
        )

    registered_count = sum(1 for item in entries if item["status"] == "registered")
    unavailable_count = sum(1 for item in entries if item["status"] == "unavailable")
    available_count = sum(1 for item in entries if item["status"] == "available")
    return {
        "file": str(target),
        "total": len(entries),
        "available": available_count,
        "registered": registered_count,
        "unavailable": unavailable_count,
        "invalid": invalid,
        "accounts": entries[:500],
        "next_available_email": next((item["email"] for item in entries if item["status"] == "available"), ""),
    }


def _load_icloud_pool_status(target: Path) -> dict[str, Any]:
    from autotoken.mail.base import normalize_email_addr
    from autotoken.mail.icloud import ICloudMailProvider
    from autotoken.storage.accounts import load_accounts
    from autotoken.storage.icloud_pool import unavailable_email_records

    content = read_text(target) if target.exists() else ""
    local_accounts = {
        normalize_email_addr(account.get("email")): account
        for account in load_accounts()
        if account.get("email")
    }
    unavailable_records = unavailable_email_records()
    skipped_emails = ICloudMailProvider._registered_emails()

    entries: list[dict[str, Any]] = []
    invalid = 0
    seen: set[str] = set()
    for line in _split_icloud_account_lines(content):
        account = ICloudMailProvider._parse_account_line(line)
        if not account or not account.validate():
            invalid += 1
            continue
        email = account.email.lower()
        if email in seen:
            continue
        seen.add(email)
        local_account = local_accounts.get(email) or {}
        local_status = str(local_account.get("status") or "").strip().lower()
        last_error = str(local_account.get("last_error") or "").strip().lower()
        unavailable_record = unavailable_records.get(email) or {}
        unavailable_source = str(unavailable_record.get("source") or "").strip().lower()
        local_unavailable = (
            email in unavailable_records
            or local_status == "fail"
            or "account_deactivated" in last_error
        )
        registered = bool(local_account) and not local_unavailable
        unavailable = local_unavailable or (email in skipped_emails and not registered)
        status = "registered" if registered else ("unavailable" if unavailable else "available")
        unavailable_reason = last_error or unavailable_source
        entries.append(
            {
                "email": account.email,
                "status": status,
                "registered": registered,
                "available": status == "available",
                "unavailable": status == "unavailable",
                "unavailable_reason": unavailable_reason if status == "unavailable" else "",
                "has_receive_code_url": bool(account.receive_code_url),
            }
        )

    registered_count = sum(1 for item in entries if item["status"] == "registered")
    unavailable_count = sum(1 for item in entries if item["status"] == "unavailable")
    available_count = sum(1 for item in entries if item["status"] == "available")
    available_entries = [item for item in entries if item["status"] == "available"]
    return {
        "file": str(target),
        "total": len(entries),
        "available": available_count,
        "registered": registered_count,
        "unavailable": unavailable_count,
        "invalid": invalid,
        "accounts": available_entries[:500],
        "all_accounts": entries[:500],
        "registered_accounts": [item for item in entries if item["status"] == "registered"][:500],
        "unavailable_accounts": [item for item in entries if item["status"] == "unavailable"][:500],
        "next_available_email": next((item["email"] for item in entries if item["status"] == "available"), ""),
    }


def _delete_outlook_pool_accounts(target: Path, emails: list[str]) -> dict[str, Any]:
    from autotoken.mail.base import normalize_email_addr
    from autotoken.mail.outlook import OutlookMailProvider

    requested = [normalize_email_addr(email) for email in emails or []]
    targets = {email for email in requested if email}
    if not targets:
        raise HTTPException(status_code=400, detail="请选择要删除的 Outlook 邮箱")

    content = read_text(target) if target.exists() else ""
    kept_lines: list[str] = []
    deleted_emails: list[str] = []
    deleted_seen: set[str] = set()
    for raw_line in content.replace("\ufeff", "").replace(";", "\n").splitlines():
        line = raw_line.strip()
        account = OutlookMailProvider._parse_account_line(line)
        email = account.email.lower() if account and account.validate() else ""
        if email and email in targets:
            if email not in deleted_seen:
                deleted_seen.add(email)
                deleted_emails.append(email)
            continue
        kept_lines.append(raw_line)

    next_content = "\n".join(kept_lines)
    if next_content:
        next_content += "\n"
    target.write_text(next_content, encoding="utf-8")

    missing = sorted(targets - deleted_seen)
    return {
        "file": str(target),
        "requested": len(targets),
        "deleted": len(deleted_seen),
        "deleted_emails": deleted_emails[:50],
        "missing_emails": missing[:50],
    }


def _delete_icloud_pool_accounts(target: Path, emails: list[str]) -> dict[str, Any]:
    from autotoken.mail.base import normalize_email_addr
    from autotoken.mail.icloud import ICloudMailProvider

    requested = [normalize_email_addr(email) for email in emails or []]
    targets = {email for email in requested if email}
    if not targets:
        raise HTTPException(status_code=400, detail="请选择要删除的 iCloud 邮箱")

    content = read_text(target) if target.exists() else ""
    kept_lines: list[str] = []
    deleted_emails: list[str] = []
    deleted_seen: set[str] = set()
    for raw_line in content.replace("\ufeff", "").replace(";", "\n").splitlines():
        line = raw_line.strip()
        account = ICloudMailProvider._parse_account_line(line)
        email = account.email.lower() if account and account.validate() else ""
        if email and email in targets:
            if email not in deleted_seen:
                deleted_seen.add(email)
                deleted_emails.append(email)
            continue
        kept_lines.append(raw_line)

    next_content = "\n".join(kept_lines)
    if next_content:
        next_content += "\n"
    target.write_text(next_content, encoding="utf-8")

    missing = sorted(targets - deleted_seen)
    return {
        "file": str(target),
        "requested": len(targets),
        "deleted": len(deleted_seen),
        "deleted_emails": deleted_emails[:50],
        "missing_emails": missing[:50],
    }


def create_config_io_router(
    *,
    auto_check_config: dict[str, Any],
    auto_check_restart: Any,
    auto_refresh_quota_config: dict[str, Any],
    auto_refresh_quota_restart: Any,
    save_auto_refresh_quota_config: Callable[[], None],
    get_api_key: Callable[[], str],
    set_api_key: Callable[[str], None],
    current_time: Callable[[], float] = time.time,
    logger: logging.Logger | None = None,
) -> APIRouter:
    router = APIRouter()
    route_logger = logger or logging.getLogger(__name__)

    @router.get("/api/config/export")
    def export_config_api():
        """导出设置页相关配置。包含密钥，请只在可信环境保存。"""
        from autotoken.integrations.account_hub import get_config as get_account_hub_config
        from autotoken.settings.runtime_config import get_register_domain, get_register_domains
        from autotoken.settings.setup_wizard import _read_env

        env = _read_env()
        env_keys = _env_config_keys()
        return {
            "version": 1,
            "exported_at": current_time(),
            "env": {key: str(env.get(key, os.environ.get(key, "")) or "") for key in env_keys},
            "runtime": {
                "register_domain": get_register_domain(),
                "register_domains": get_register_domains(),
            },
            "account_hub": get_account_hub_config(),
            "auto_check": auto_check_config.copy(),
            "auto_refresh_quota": auto_refresh_quota_config.copy(),
        }

    @router.post("/api/config/import")
    def import_config_api(params: ConfigImportParams):
        """导入设置页配置并写回 .env / SQLite 配置。"""
        from autotoken.integrations.account_hub import set_config as set_account_hub_config
        from autotoken.settings.runtime_config import set_register_domain, set_register_domains
        from autotoken.settings.setup_wizard import _write_env

        payload = _normalize_imported_config(params)
        allowed_env_keys = set(_env_config_keys())
        section_keys = {"version", "exported_at", "env", "runtime", "account_hub", "auto_check", "auto_refresh_quota"}
        raw_env = (
            payload.get("env")
            if isinstance(payload.get("env"), dict)
            else (payload if not (set(payload) & section_keys) else {})
        )
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

        if isinstance(payload.get("auto_check"), dict):
            cfg = payload["auto_check"]
            auto_check_config.update(
                {
                    "enabled": bool(cfg.get("enabled", auto_check_config.get("enabled", True))),
                    "interval": max(60, int(cfg.get("interval") or auto_check_config.get("interval") or 300)),
                    "threshold": max(1, min(100, int(cfg.get("threshold") or auto_check_config.get("threshold") or 10))),
                    "min_low": max(1, int(cfg.get("min_low") or auto_check_config.get("min_low") or 1)),
                }
            )
            auto_check_restart.set()
            updated_sections.append("auto_check")

        if isinstance(payload.get("auto_refresh_quota"), dict):
            cfg = payload["auto_refresh_quota"]
            interval = max(0, int(cfg.get("interval") or 0))
            enabled = bool(cfg.get("enabled")) and interval > 0
            auto_refresh_quota_config.update({"enabled": enabled, "interval": max(60, interval) if enabled else 0})
            save_auto_refresh_quota_config()
            auto_refresh_quota_restart.set()
            updated_sections.append("auto_refresh_quota")

        _reload_env_backed_modules()
        set_api_key(os.environ.get("API_KEY", get_api_key()))

        return {
            "message": f"配置导入完成：更新 {len(updated_env)} 个 .env 项",
            "updated_env": updated_env,
            "skipped_env": [key for key in skipped_env if key],
            "updated_runtime": updated_runtime,
            "updated_sections": updated_sections,
        }

    @router.post("/api/config/outlook-accounts/import")
    def post_import_outlook_accounts(params: OutlookAccountsImportParams):
        """导入 Outlook/Hotmail 账号池 txt 内容，复用 Outlook provider 的账号行解析规则。"""
        content = str(params.content or "")
        if not content.strip():
            raise HTTPException(status_code=400, detail="上传文件为空")
        if len(content.encode("utf-8", errors="ignore")) > OUTLOOK_ACCOUNTS_IMPORT_MAX_BYTES:
            raise HTTPException(status_code=400, detail="上传文件过大，最多支持 2MB txt")

        from autotoken.mail.outlook import OutlookMailProvider

        target = _resolve_outlook_accounts_file()
        if target.exists() and target.stat().st_size > OUTLOOK_ACCOUNTS_IMPORT_MAX_BYTES:
            raise HTTPException(status_code=400, detail="现有 Outlook 账号池文件过大，最多支持 2MB txt")
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

        route_logger.info(
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

    @router.get("/api/config/outlook-accounts/status")
    def get_outlook_accounts_status():
        """读取 Outlook 邮箱池状态。只返回邮箱和能力标记，不返回密码或 token。"""
        target = _resolve_outlook_accounts_file()
        if target.exists() and target.stat().st_size > OUTLOOK_ACCOUNTS_IMPORT_MAX_BYTES:
            raise HTTPException(status_code=400, detail="现有 Outlook 账号池文件过大，最多支持 2MB txt")
        return _load_outlook_pool_status(target)

    @router.post("/api/config/outlook-accounts/delete")
    def post_delete_outlook_accounts(params: OutlookAccountsDeleteParams):
        """从 Outlook 邮箱池文件删除指定邮箱行，不删除本地已注册账号。"""
        target = _resolve_outlook_accounts_file()
        if target.exists() and target.stat().st_size > OUTLOOK_ACCOUNTS_IMPORT_MAX_BYTES:
            raise HTTPException(status_code=400, detail="现有 Outlook 账号池文件过大，最多支持 2MB txt")
        result = _delete_outlook_pool_accounts(target, params.emails)
        route_logger.info(
            "[outlook] 删除账号池邮箱: file=%s requested=%d deleted=%d",
            target,
            result["requested"],
            result["deleted"],
        )
        return result

    @router.post("/api/config/icloud-accounts/import")
    def post_import_icloud_accounts(params: ICloudAccountsImportParams):
        """导入 iCloud 账号池内容，格式 email@icloud.com----收码链接。"""
        content = str(params.content or "")
        if not content.strip():
            raise HTTPException(status_code=400, detail="上传文件为空")
        if len(content.encode("utf-8", errors="ignore")) > ICLOUD_ACCOUNTS_IMPORT_MAX_BYTES:
            raise HTTPException(status_code=400, detail="上传文件过大，最多支持 2MB txt")

        from autotoken.mail.icloud import ICloudMailProvider

        target = _resolve_icloud_accounts_file()
        if target.exists() and target.stat().st_size > ICLOUD_ACCOUNTS_IMPORT_MAX_BYTES:
            raise HTTPException(status_code=400, detail="现有 iCloud 账号池文件过大，最多支持 2MB txt")
        existing_content = read_text(target) if target.exists() else ""
        existing_accounts: dict[str, str] = {}
        for line in _split_icloud_account_lines(existing_content):
            account = ICloudMailProvider._parse_account_line(line)
            if account and account.validate():
                existing_accounts[account.email.lower()] = line

        imported: list[str] = []
        imported_emails: list[str] = []
        duplicates: list[str] = []
        invalid: list[dict[str, Any]] = []
        seen_upload: set[str] = set()
        for line_no, line in enumerate(_split_icloud_account_lines(content), start=1):
            account = ICloudMailProvider._parse_account_line(line)
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

        route_logger.info(
            "[icloud] 导入账号池: file=%s imported=%d duplicate=%d invalid=%d source=%s",
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
            "total": len(_split_icloud_account_lines(content)),
            "duplicate_emails": duplicates[:20],
            "imported_emails": imported_emails[:20],
            "first_imported_email": imported_emails[0] if imported_emails else "",
            "invalid_lines": invalid[:20],
        }

    @router.get("/api/config/icloud-accounts/status")
    def get_icloud_accounts_status():
        """读取 iCloud 邮箱池状态。只返回邮箱和能力标记，不返回收码链接。"""
        target = _resolve_icloud_accounts_file()
        if target.exists() and target.stat().st_size > ICLOUD_ACCOUNTS_IMPORT_MAX_BYTES:
            raise HTTPException(status_code=400, detail="现有 iCloud 账号池文件过大，最多支持 2MB txt")
        return _load_icloud_pool_status(target)

    @router.post("/api/config/icloud-accounts/delete")
    def post_delete_icloud_accounts(params: ICloudAccountsDeleteParams):
        """从 iCloud 邮箱池删除指定邮箱行，不删除本地已注册账号。"""
        target = _resolve_icloud_accounts_file()
        if target.exists() and target.stat().st_size > ICLOUD_ACCOUNTS_IMPORT_MAX_BYTES:
            raise HTTPException(status_code=400, detail="现有 iCloud 账号池文件过大，最多支持 2MB txt")
        result = _delete_icloud_pool_accounts(target, params.emails)
        route_logger.info(
            "[icloud] 删除账号池邮箱: file=%s requested=%d deleted=%d",
            target,
            result["requested"],
            result["deleted"],
        )
        return result

    return router
