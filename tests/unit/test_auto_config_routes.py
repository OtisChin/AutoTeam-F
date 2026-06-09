import logging
import threading

from fastapi import FastAPI

from autotoken.api_routes.auto_config import AutoCheckConfig, AutoRefreshQuotaConfig, create_auto_config_router


def _endpoint(app, path, method):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"missing route {method} {path}")


def _client(auto_check=None, auto_refresh=None):
    saved = []
    app = FastAPI()
    check_restart = threading.Event()
    refresh_restart = threading.Event()
    auto_check_config = auto_check or {"enabled": False, "interval": 300, "threshold": 10, "min_low": 2}
    auto_refresh_config = auto_refresh or {"enabled": False, "interval": 0}

    app.include_router(
        create_auto_config_router(
            auto_check_config=auto_check_config,
            auto_check_restart=check_restart,
            auto_refresh_quota_config=auto_refresh_config,
            auto_refresh_quota_restart=refresh_restart,
            save_auto_refresh_quota_config=lambda: saved.append(auto_refresh_config.copy()),
            logger=logging.getLogger("test.auto_config_routes"),
        )
    )
    return app, auto_check_config, check_restart, auto_refresh_config, refresh_restart, saved


def test_auto_check_routes_return_copy_and_clamp_runtime_config():
    app, config, restart, _refresh, _refresh_restart, _saved = _client()

    assert _endpoint(app, "/api/config/auto-check", "GET")() == config

    response = _endpoint(app, "/api/config/auto-check", "PUT")(
        AutoCheckConfig(enabled=True, interval=10, threshold=200, min_low=0)
    )

    assert response == {"enabled": True, "interval": 60, "threshold": 100, "min_low": 1}
    assert config == response
    assert restart.is_set()


def test_auto_refresh_routes_disable_or_persist_enabled_runtime_config():
    app, _check, _check_restart, config, restart, saved = _client()

    disabled = _endpoint(app, "/api/config/auto-refresh-quota", "PUT")(
        AutoRefreshQuotaConfig(enabled=False, interval=500)
    )
    assert disabled == {"enabled": False, "interval": 0}
    assert saved[-1] == {"enabled": False, "interval": 0}
    assert restart.is_set()

    restart.clear()
    enabled = _endpoint(app, "/api/config/auto-refresh-quota", "PUT")(AutoRefreshQuotaConfig(interval=30))
    assert enabled == {"enabled": True, "interval": 60}
    assert config == {"enabled": True, "interval": 60}
    assert saved[-1] == {"enabled": True, "interval": 60}
    assert restart.is_set()
