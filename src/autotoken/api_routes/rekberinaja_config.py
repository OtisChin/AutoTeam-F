"""Rekberinaja funding configuration HTTP routes."""

import os
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request


def rekberinaja_env() -> dict[str, str]:
    from autotoken.integrations.rekberinaja import (
        DEFAULT_BASE_URL,
        DEFAULT_GOPAY_PRODUCT_ID,
        DEFAULT_GOPAY_SERVICE_ID,
        DEFAULT_STORE,
    )
    from autotoken.settings.setup_wizard import _read_env

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


def _enabled_flag(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def build_rekberinaja_config_response(
    message: str = "",
    *,
    mask_secret: Callable[[str], str],
) -> dict[str, Any]:
    cfg = rekberinaja_env()
    transfer_enabled = _enabled_flag(cfg["transfer_enabled"])
    response = {
        "enabled": transfer_enabled,
        "transfer_enabled": transfer_enabled,
        "email": cfg["email"],
        "email_present": bool(cfg["email"]),
        "password_present": bool(cfg["password"]),
        "password_masked": mask_secret(cfg["password"]),
        "credentials_configured": bool(cfg["email"] and cfg["password"]),
        "configured": bool(transfer_enabled and cfg["email"] and cfg["password"]),
        "min_balance": cfg["min_balance"],
        "poll_timeout": cfg["poll_timeout"],
        "invoice_email": cfg["invoice_email"],
    }
    if message:
        response["message"] = message
    return response


def create_rekberinaja_config_router(*, mask_secret: Callable[[str], str]) -> APIRouter:
    router = APIRouter()

    @router.get("/api/config/rekberinaja")
    def get_rekberinaja_config():
        return build_rekberinaja_config_response(mask_secret=mask_secret)

    @router.put("/api/config/rekberinaja")
    async def save_rekberinaja_config(request: Request):
        from autotoken.settings.setup_wizard import _write_env

        data = await request.json()
        transfer_enabled = bool(
            data.get("transfer_enabled") or data.get("enabled") or data.get("REKBERINAJA_TRANSFER_ENABLED")
        )
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
            "REKBERINAJA_BASE_URL": str(
                data.get("base_url") or os.environ.get("REKBERINAJA_BASE_URL") or "https://api.rekberinaja.com/api"
            ).strip(),
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

        return build_rekberinaja_config_response("Rekberinaja 配置已保存", mask_secret=mask_secret)

    return router
