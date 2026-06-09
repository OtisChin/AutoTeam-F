"""RoxyBrowser configuration HTTP routes."""

import os
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request


def normalize_roxybrowser_api_host(api_host: str | None) -> str:
    raw = str(api_host or "").strip().rstrip("/")
    if not raw:
        raw = "http://127.0.0.1:50000"
    if "://" not in raw:
        raw = f"http://{raw}"
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.port is None:
        raise ValueError("请使用 http://host:port，例如 http://127.0.0.1:50000")
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{parsed.scheme}://{host}:{parsed.port}"


def roxybrowser_env() -> dict[str, str]:
    from autotoken.settings.setup_wizard import _read_env

    env = _read_env()

    def pick(key: str, default: str = "") -> str:
        return str(env.get(key, "") or os.environ.get(key, "") or default).strip()

    return {
        "api_host": pick("ROXYBROWSER_API_HOST", "http://127.0.0.1:50000").rstrip("/"),
        "api_token": pick("ROXYBROWSER_API_TOKEN"),
    }


def build_roxybrowser_config_response(
    message: str = "",
    *,
    mask_secret: Callable[[str], str],
) -> dict[str, Any]:
    cfg = roxybrowser_env()
    try:
        api_host = normalize_roxybrowser_api_host(cfg["api_host"])
        host_valid = True
        host_error = ""
    except Exception as exc:
        api_host = cfg["api_host"] or "http://127.0.0.1:50000"
        host_valid = False
        host_error = str(exc)
    missing_keys = []
    if not cfg["api_token"]:
        missing_keys.append("ROXYBROWSER_API_TOKEN")
    if not host_valid:
        missing_keys.append("ROXYBROWSER_API_HOST")
    return {
        "message": message,
        "api_host": api_host,
        "api_host_valid": host_valid,
        "api_host_error": host_error,
        "api_token_present": bool(cfg["api_token"]),
        "api_token_masked": mask_secret(cfg["api_token"]),
        "configured": bool(cfg["api_token"] and host_valid),
        "missing_keys": missing_keys,
    }


def build_roxybrowser_workspaces_response() -> dict[str, Any]:
    cfg = roxybrowser_env()
    try:
        from autotoken.integrations.roxybrowser_client import RoxyBrowserClient

        client = RoxyBrowserClient(cfg["api_host"], cfg["api_token"])
        workspaces = client.list_workspaces()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"读取 RoxyBrowser 工作空间失败: {exc}") from exc
    return {"workspaces": workspaces, "count": len(workspaces)}


def build_roxybrowser_profiles_response() -> dict[str, Any]:
    cfg = roxybrowser_env()
    try:
        from autotoken.integrations.roxybrowser_client import RoxyBrowserClient

        client = RoxyBrowserClient(cfg["api_host"], cfg["api_token"])
        profiles = client.list_all_profiles()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"读取 RoxyBrowser 窗口失败: {exc}") from exc
    return {"profiles": profiles, "count": len(profiles)}


def create_roxybrowser_config_router(*, mask_secret: Callable[[str], str]) -> APIRouter:
    router = APIRouter()

    @router.get("/api/config/roxybrowser")
    def get_roxybrowser_config_api():
        return build_roxybrowser_config_response(mask_secret=mask_secret)

    @router.get("/api/config/roxybrowser/workspaces")
    def get_roxybrowser_workspaces_api():
        return build_roxybrowser_workspaces_response()

    @router.get("/api/config/roxybrowser/profiles")
    def get_roxybrowser_profiles_api():
        return build_roxybrowser_profiles_response()

    @router.put("/api/config/roxybrowser")
    async def save_roxybrowser_config_api(request: Request):
        from autotoken.settings.setup_wizard import _write_env

        data = await request.json()
        current = roxybrowser_env()
        raw_api_host = (
            data.get("api_host")
            or data.get("ROXYBROWSER_API_HOST")
            or current["api_host"]
            or "http://127.0.0.1:50000"
        )
        try:
            api_host = normalize_roxybrowser_api_host(raw_api_host)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"RoxyBrowser API 地址格式无效: {exc}") from exc

        api_token = str(data.get("api_token") or data.get("ROXYBROWSER_API_TOKEN") or "").strip()
        clear_api_token = bool(data.get("clear_api_token") or data.get("clearApiToken"))

        updates = {
            "ROXYBROWSER_API_HOST": api_host,
        }
        if clear_api_token:
            updates["ROXYBROWSER_API_TOKEN"] = ""
        elif api_token:
            updates["ROXYBROWSER_API_TOKEN"] = api_token

        for key, value in updates.items():
            _write_env(key, value)
            os.environ[key] = value

        return build_roxybrowser_config_response("RoxyBrowser 配置已保存", mask_secret=mask_secret)

    return router
