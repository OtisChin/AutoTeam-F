"""Initial setup and authentication check HTTP routes."""

import importlib
import os
import secrets
from collections.abc import Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel


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


def create_setup_router(
    *,
    get_api_key: Callable[[], str],
    set_api_key: Callable[[str], None],
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/auth/check")
    def check_auth(request: Request):
        """验证 API Key 是否有效。未配置 API_KEY 时始终返回成功。"""
        api_key = get_api_key()
        if not api_key:
            return {"authenticated": True, "auth_required": False}
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer ") and auth_header[7:] == api_key:
            return {"authenticated": True, "auth_required": True}
        return JSONResponse(status_code=401, content={"authenticated": False, "auth_required": True})

    @router.get("/api/setup/status")
    def get_setup_status():
        """检查配置是否完整"""
        from autotoken.settings.setup_wizard import _read_env, get_required_configs_for_provider, get_setup_schema

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

    @router.post("/api/setup/save")
    def post_setup_save(config: SetupConfig):
        """保存配置到 .env 并验证连通性"""
        from autotoken.settings.setup_wizard import _write_env, get_mail_provider

        data = config.model_dump()
        provider = get_mail_provider(data.get("MAIL_PROVIDER"))
        data["MAIL_PROVIDER"] = provider
        if not data.get("API_KEY"):
            data["API_KEY"] = secrets.token_urlsafe(24)

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

        from autotoken.settings import config as config_module

        importlib.reload(config_module)
        try:
            from autotoken import mail as mail_module

            importlib.reload(mail_module)
        except Exception:
            pass

        errors = []
        from autotoken.settings.setup_wizard import _verify_cpa, _verify_temporary_email

        if not _verify_temporary_email():
            errors.append("临时邮箱服务连接失败")
        if not _verify_cpa():
            errors.append("CPA 连接失败")

        if errors:
            return JSONResponse(status_code=400, content={"message": "、".join(errors), "api_key": data["API_KEY"]})

        set_api_key(data["API_KEY"])
        return {"message": "配置保存成功", "api_key": data["API_KEY"], "configured": True}

    return router
