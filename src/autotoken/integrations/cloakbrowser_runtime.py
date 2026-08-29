"""CloakBrowser runtime for browser-style registration."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on", "y", "headless", "无头"}


def _env_list(name: str) -> list[str]:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [str(item).strip() for item in data if str(item or "").strip()]
        except Exception:
            pass
    return [item.strip() for item in raw.replace("\n", ",").split(",") if item.strip()]


def _normalize_proxy(proxy_url: str | None) -> str:
    proxy = str(proxy_url or "").strip()
    if not proxy:
        return ""
    # CloakBrowser/Playwright expect socks5, while the rest of AutoToken often
    # normalizes outbound proxies to socks5h for HTTP clients.
    return proxy.replace("socks5h://", "socks5://", 1)


@dataclass
class CloakBrowserRuntime:
    browser: Any
    context: Any
    page: Any
    raw: dict[str, Any]

    def close(self) -> None:
        for obj in (self.context, self.browser):
            try:
                obj.close()
            except Exception:
                pass


def launch_cloakbrowser_context(proxy_url: str | None = None) -> CloakBrowserRuntime:
    """Launch CloakBrowser and return a Playwright-style browser/context/page."""

    try:
        from cloakbrowser import launch, launch_persistent_context  # type: ignore
    except ImportError as exc:
        raise RuntimeError("未安装 cloakbrowser，请先执行：uv add 'cloakbrowser[geoip]>=0.4.10' 或 pip install 'cloakbrowser[geoip]>=0.4.10'") from exc

    proxy = _normalize_proxy(proxy_url) if _env_bool("CLOAK_USE_PROXY", True) else ""
    locale = str(os.environ.get("CLOAK_LOCALE") or "").strip()
    timezone = str(os.environ.get("CLOAK_TIMEZONE") or "").strip()
    license_key = str(os.environ.get("CLOAK_LICENSE_KEY") or "").strip()
    seed = str(os.environ.get("CLOAK_FINGERPRINT_SEED") or "").strip()
    user_data_dir = str(os.environ.get("CLOAK_USER_DATA_DIR") or "").strip()
    args = _env_list("CLOAK_EXTRA_ARGS")
    if seed:
        args.append(f"--fingerprint={seed}")

    options: dict[str, Any] = {
        "headless": _env_bool("CLOAK_HEADLESS", True),
        "humanize": _env_bool("CLOAK_HUMANIZE", True),
        "geoip": _env_bool("CLOAK_GEOIP", True),
    }
    if proxy:
        options["proxy"] = proxy
    if locale:
        options["locale"] = locale
    if timezone:
        options["timezone"] = timezone
    if args:
        options["args"] = args
    if license_key:
        options["license_key"] = license_key

    context_kwargs: dict[str, Any] = {
        "viewport": {"width": 1280, "height": 800},
    }
    if locale:
        context_kwargs["locale"] = locale
        context_kwargs["extra_http_headers"] = {
            "Accept-Language": f"{locale},{locale.split('-')[0]};q=0.9,en-US;q=0.8,en;q=0.7"
        }
    if timezone:
        context_kwargs["timezone_id"] = timezone

    logger.info(
        "[Cloak注册] 启动 CloakBrowser: headless=%s humanize=%s geoip=%s proxy=%s locale=%s timezone=%s persistent=%s",
        options["headless"],
        options["humanize"],
        options["geoip"],
        "enabled" if proxy else "disabled",
        locale or "auto/default",
        timezone or "auto/default",
        bool(user_data_dir),
    )

    if user_data_dir:
        profile_dir = str(Path(user_data_dir).expanduser())
        context = launch_persistent_context(profile_dir, **options)
        page = context.new_page()
        browser = getattr(context, "browser", None) or context
    else:
        browser = launch(**options)
        context = browser.new_context(**context_kwargs)
        page = context.new_page()

    raw_options = {key: value for key, value in options.items() if key != "license_key"}
    return CloakBrowserRuntime(
        browser=browser,
        context=context,
        page=page,
        raw={"driver": "cloakbrowser", "proxy": proxy, "options": raw_options},
    )
