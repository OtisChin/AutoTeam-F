"""Runtime automation configuration routes."""

import logging
import threading
from collections.abc import Callable

from fastapi import APIRouter
from pydantic import BaseModel


class AutoCheckConfig(BaseModel):
    enabled: bool | None = None
    interval: int = 300
    threshold: int = 10
    min_low: int = 2


class AutoRefreshQuotaConfig(BaseModel):
    enabled: bool | None = None
    interval: int = 0


def create_auto_config_router(
    *,
    auto_check_config: dict,
    auto_check_restart: threading.Event,
    auto_refresh_quota_config: dict,
    auto_refresh_quota_restart: threading.Event,
    save_auto_refresh_quota_config: Callable[[], None],
    logger: logging.Logger,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/config/auto-check")
    def get_auto_check_config():
        """Get runtime quota-check configuration."""
        return auto_check_config.copy()

    @router.put("/api/config/auto-check")
    def set_auto_check_config(cfg: AutoCheckConfig):
        """Update runtime quota-check configuration."""
        if cfg.enabled is not None:
            auto_check_config["enabled"] = bool(cfg.enabled)
        auto_check_config["interval"] = max(60, cfg.interval)
        auto_check_config["threshold"] = max(1, min(100, cfg.threshold))
        auto_check_config["min_low"] = max(1, cfg.min_low)
        auto_check_restart.set()
        logger.info(
            "[巡检] 配置已更新: enabled=%s 间隔=%ds 阈值=%d%%（min_low 已废弃,任意失效立即 1v1 替换）",
            auto_check_config["enabled"],
            auto_check_config["interval"],
            auto_check_config["threshold"],
        )
        return auto_check_config.copy()

    @router.get("/api/config/auto-refresh-quota")
    def get_auto_refresh_quota_config():
        """Get automatic credential refresh configuration."""
        return auto_refresh_quota_config.copy()

    @router.put("/api/config/auto-refresh-quota")
    def set_auto_refresh_quota_config(cfg: AutoRefreshQuotaConfig):
        """Update automatic credential refresh configuration."""
        interval = max(0, int(cfg.interval or 0))
        enabled = bool(cfg.enabled) if cfg.enabled is not None else interval > 0
        if not enabled or interval <= 0:
            auto_refresh_quota_config["enabled"] = False
            auto_refresh_quota_config["interval"] = 0
        else:
            auto_refresh_quota_config["enabled"] = True
            auto_refresh_quota_config["interval"] = max(60, interval)
        save_auto_refresh_quota_config()
        auto_refresh_quota_restart.set()
        logger.info(
            "[刷新额度] 自动刷新配置已更新: enabled=%s interval=%ds",
            auto_refresh_quota_config["enabled"],
            auto_refresh_quota_config["interval"],
        )
        return auto_refresh_quota_config.copy()

    return router
