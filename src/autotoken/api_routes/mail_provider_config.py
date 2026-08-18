"""Mail provider configuration HTTP routes."""

import importlib
import os

from fastapi import APIRouter, HTTPException, Request


def mail_provider_field_keys(provider: str) -> set[str]:
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
        "icloud": {
            "ICLOUD_ACCOUNTS_FILE",
            "ICLOUD_ACCOUNTS",
        },
        "generic-api": {
            "GENERIC_API_ACCOUNTS_FILE",
            "GENERIC_API_ACCOUNTS",
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


def create_mail_provider_config_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/config/mail-provider")
    def get_mail_provider_config():
        from autotoken.settings.setup_wizard import _read_env, get_mail_provider, get_setup_schema

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

    @router.put("/api/config/mail-provider")
    async def save_mail_provider_config(request: Request):
        from autotoken.settings.setup_wizard import _verify_temporary_email, _write_env, get_mail_provider

        data = await request.json()
        provider = get_mail_provider(data.get("MAIL_PROVIDER"))
        allowed = {"MAIL_PROVIDER"} | mail_provider_field_keys(provider)

        for key, value in data.items():
            if key not in allowed:
                continue
            text = "" if value is None else str(value)
            _write_env(key, text)
            os.environ[key] = text

        _write_env("MAIL_PROVIDER", provider)
        os.environ["MAIL_PROVIDER"] = provider

        from autotoken.settings import config as config_module

        importlib.reload(config_module)

        if not _verify_temporary_email():
            raise HTTPException(status_code=400, detail="邮件 Provider 验证失败，请检查配置")

        return {"message": "邮件 Provider 配置已保存", "provider": provider}

    return router
