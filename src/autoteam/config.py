"""配置文件 - 从 .env 文件或环境变量加载"""

import os
from urllib.parse import quote, unquote, urlsplit

from autoteam.paths import PROJECT_ROOT
from autoteam.textio import parse_env_line, parse_env_value, read_text

# 加载 .env 文件（从项目根目录）
_env_file = PROJECT_ROOT / ".env"
if _env_file.exists():
    for line in read_text(_env_file).splitlines():
        parsed = parse_env_line(line)
        if parsed:
            key, value = parsed
            os.environ.setdefault(key, value)


def _get_int_env(name: str, default: int) -> int:
    return int(parse_env_value(os.environ.get(name, str(default))))


def _first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name, "")
        if value:
            return value
    return default


def normalize_mail_provider(raw: str | None) -> str:
    provider = (raw or "").strip().lower()
    if provider in ("", "cloudflare_temp_email", "cf_temp_email"):
        return "cloudflare_temp_email"
    if provider in ("cloud-mail", "cloud_mail", "maillab"):
        return "cloud-mail"
    if provider in ("outlook", "microsoft_outlook", "hotmail"):
        return "outlook"
    if provider in ("luckmail", "lucky_mail", "lucky-mail"):
        return "luckmail"
    return provider


MAIL_PROVIDER = normalize_mail_provider(os.environ.get("MAIL_PROVIDER"))

# Canonical cloudflare_temp_email config
CLOUDFLARE_TEMP_EMAIL_BASE_URL = _first_env("CLOUDFLARE_TEMP_EMAIL_BASE_URL", "CLOUDMAIL_BASE_URL")
CLOUDFLARE_TEMP_EMAIL_ADMIN_PASSWORD = _first_env(
    "CLOUDFLARE_TEMP_EMAIL_ADMIN_PASSWORD",
    "CLOUDMAIL_PASSWORD",
)
CLOUDFLARE_TEMP_EMAIL_DOMAIN = _first_env("CLOUDFLARE_TEMP_EMAIL_DOMAIN", "CLOUDMAIL_DOMAIN")

# Canonical cloud-mail config
CLOUD_MAIL_API_URL = _first_env("CLOUD_MAIL_API_URL", "MAILLAB_API_URL")
CLOUD_MAIL_ADMIN_EMAIL = _first_env("CLOUD_MAIL_ADMIN_EMAIL", "MAILLAB_USERNAME")
CLOUD_MAIL_ADMIN_PASSWORD = _first_env("CLOUD_MAIL_ADMIN_PASSWORD", "MAILLAB_PASSWORD")
CLOUD_MAIL_DOMAIN = _first_env("CLOUD_MAIL_DOMAIN", "MAILLAB_DOMAIN", "CLOUDMAIL_DOMAIN")

# Outlook account-pool registration provider
OUTLOOK_ACCOUNTS_FILE = _first_env("OUTLOOK_ACCOUNTS_FILE", default="")
OUTLOOK_ACCOUNTS = _first_env("OUTLOOK_ACCOUNTS", default="")
OUTLOOK_DEFAULT_CLIENT_ID = _first_env("OUTLOOK_DEFAULT_CLIENT_ID", default="24d9a0ed-8787-4584-883c-2fd79308940a")
OUTLOOK_PROVIDER_PRIORITY = _first_env("OUTLOOK_PROVIDER_PRIORITY", default="imap_old,imap_new,graph_api")
OUTLOOK_PROXY_URL = _first_env("OUTLOOK_PROXY_URL", default="")

# LuckMail purchased-token registration provider
LUCKMAIL_BASE_URL = _first_env("LUCKMAIL_BASE_URL", default="https://mail.luckyous.com")
LUCKMAIL_API_KEY = _first_env("LUCKMAIL_API_KEY", default="")
LUCKMAIL_PROJECT_CODE = _first_env("LUCKMAIL_PROJECT_CODE", default="openai")
LUCKMAIL_EMAIL_TYPE = _first_env("LUCKMAIL_EMAIL_TYPE", default="ms_graph")
LUCKMAIL_PREFERRED_DOMAIN = _first_env("LUCKMAIL_PREFERRED_DOMAIN", default="")
LUCKMAIL_ACCOUNTS_FILE = _first_env("LUCKMAIL_ACCOUNTS_FILE", default="")
LUCKMAIL_ACCOUNTS = _first_env("LUCKMAIL_ACCOUNTS", default="")

# Backward-compatible aliases used by existing code paths
CLOUDMAIL_BASE_URL = CLOUDFLARE_TEMP_EMAIL_BASE_URL
CLOUDMAIL_EMAIL = os.environ.get("CLOUDMAIL_EMAIL", "")
CLOUDMAIL_PASSWORD = CLOUDFLARE_TEMP_EMAIL_ADMIN_PASSWORD
CLOUDMAIL_DOMAIN = CLOUDFLARE_TEMP_EMAIL_DOMAIN
MAILLAB_API_URL = CLOUD_MAIL_API_URL
MAILLAB_USERNAME = CLOUD_MAIL_ADMIN_EMAIL
MAILLAB_PASSWORD = CLOUD_MAIL_ADMIN_PASSWORD
MAILLAB_DOMAIN = CLOUD_MAIL_DOMAIN

# ChatGPT Team 配置
CHATGPT_ACCOUNT_ID = os.environ.get("CHATGPT_ACCOUNT_ID", "")

# CPA (CLIProxyAPI) 配置
CPA_URL = os.environ.get("CPA_URL", "")
CPA_KEY = os.environ.get("CPA_KEY", "")

# 轮询邮件间隔/超时（秒）
EMAIL_POLL_INTERVAL = _get_int_env("EMAIL_POLL_INTERVAL", 3)
EMAIL_POLL_TIMEOUT = _get_int_env("EMAIL_POLL_TIMEOUT", 300)

# API 鉴权（不设置则不启用）
API_KEY = os.environ.get("API_KEY", "")

# 自动巡检配置
AUTO_CHECK_INTERVAL = _get_int_env("AUTO_CHECK_INTERVAL", 300)  # 巡检间隔（秒），默认 5 分钟
AUTO_CHECK_THRESHOLD = _get_int_env("AUTO_CHECK_THRESHOLD", 10)  # 额度低于此百分比触发轮转，默认 10%
AUTO_CHECK_MIN_LOW = _get_int_env("AUTO_CHECK_MIN_LOW", 2)  # 至少几个账号低于阈值才触发，默认 2


def _get_bool_env(name: str, default: bool) -> bool:
    raw = parse_env_value(os.environ.get(name, "1" if default else "0"))
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in ("1", "true", "yes", "on", "y", "t")


AUTO_CHECK_ENABLED = _get_bool_env("AUTO_CHECK_ENABLED", False)


# 对账策略开关
# RECONCILE_KICK_ORPHAN=true: 残废成员(workspace 有 + 本地 auth_file 缺失)自动 kick。
#   关掉后改为打 STATUS_ORPHAN 标记等人工处理,避免"席位卡死"时仍被本地策略自动清理。
RECONCILE_KICK_ORPHAN = _get_bool_env("RECONCILE_KICK_ORPHAN", True)
# RECONCILE_KICK_GHOST=true: ghost 成员(workspace 有但本地完全无记录)自动 kick。
#   关掉后仅记录日志,依赖 sync_account_states 把 ghost 反向补录回本地,再走一般对账。
RECONCILE_KICK_GHOST = _get_bool_env("RECONCILE_KICK_GHOST", True)

# Playwright 代理配置
PLAYWRIGHT_PROXY_URL = os.environ.get("PLAYWRIGHT_PROXY_URL", "").strip()
PLAYWRIGHT_PROXY_SERVER = os.environ.get("PLAYWRIGHT_PROXY_SERVER", "").strip()
PLAYWRIGHT_PROXY_USERNAME = os.environ.get("PLAYWRIGHT_PROXY_USERNAME", "").strip()
PLAYWRIGHT_PROXY_PASSWORD = os.environ.get("PLAYWRIGHT_PROXY_PASSWORD", "").strip()
PLAYWRIGHT_PROXY_BYPASS = os.environ.get("PLAYWRIGHT_PROXY_BYPASS", "").strip()
PLAYWRIGHT_BACKGROUND = _get_bool_env("PLAYWRIGHT_BACKGROUND", True)


def _format_proxy_host(hostname: str) -> str:
    if ":" in hostname and not hostname.startswith("["):
        return f"[{hostname}]"
    return hostname


def normalize_proxy_url(proxy_url: str | None) -> str:
    raw = str(proxy_url or "").strip()
    if not raw:
        return ""

    if "://" not in raw:
        parts = raw.split(":")
        if len(parts) == 4 and parts[1].isdigit():
            host, port, username, password = parts
            raw = f"http://{quote(username, safe='')}:{quote(password, safe='')}@{host}:{port}"
        else:
            raw = f"http://{raw}"
    else:
        scheme, rest = raw.split("://", 1)
        parts = rest.split(":")
        if "@" not in rest and len(parts) == 4 and parts[1].isdigit():
            host, port, username, password = parts
            raw = f"{scheme}://{quote(username, safe='')}:{quote(password, safe='')}@{host}:{port}"

    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https", "socks4", "socks5", "socks5h"} or not parsed.hostname:
        raise ValueError(
            "代理 URL 格式无效，请使用 http://user:pass@host:port 或 socks5h://user:pass@host:port"
        )
    try:
        if parsed.port is None:
            raise ValueError
    except ValueError as exc:
        raise ValueError(
            "代理 URL 格式无效，请确认包含有效端口，例如 http://host:port"
        ) from exc

    host = _format_proxy_host(parsed.hostname)
    auth = ""
    if parsed.username:
        auth = quote(unquote(parsed.username), safe="")
        if parsed.password:
            auth = f"{auth}:{quote(unquote(parsed.password), safe='')}"
        auth = f"{auth}@"
    return f"{parsed.scheme}://{auth}{host}:{parsed.port}"


def _parse_proxy_url(proxy_url: str):
    proxy_url = normalize_proxy_url(proxy_url)

    parsed = urlsplit(proxy_url)

    host = _format_proxy_host(parsed.hostname)
    scheme = "socks5" if parsed.scheme == "socks5h" else parsed.scheme
    if scheme.startswith("socks") and (parsed.username or parsed.password):
        # Chromium/Playwright cannot launch with authenticated SOCKS proxies.
        # Many residential proxy endpoints expose HTTP and SOCKS on the same
        # host:port, so use HTTP for browser traffic while keeping
        # normalize_proxy_url unchanged for non-browser clients.
        scheme = "http"
    server = f"{scheme}://{host}"
    if parsed.port:
        server = f"{server}:{parsed.port}"

    proxy = {"server": server}
    if parsed.username:
        proxy["username"] = unquote(parsed.username)
    if parsed.password:
        proxy["password"] = unquote(parsed.password)
    return proxy


def get_playwright_launch_options(
    proxy_url: str | None = None,
    proxy_bypass: str | None = None,
    *,
    headless: bool | None = None,
    background: bool | None = None,
):
    """统一的 Playwright Chromium 启动参数。"""
    resolved_headless = False if headless is None else bool(headless)
    resolved_background = PLAYWRIGHT_BACKGROUND if background is None else bool(background)
    args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-quic",
        "--disable-features=UseDnsHttpsSvcb,UseDnsHttpsSvcbAlpn",
        "--no-sandbox",
    ]
    if resolved_background and not resolved_headless:
        args.extend(
            [
                "--window-position=-32000,-32000",
                "--window-size=1280,800",
                "--start-minimized",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
            ]
        )
    options = {
        "headless": resolved_headless,
        "args": args,
    }

    proxy = None
    resolved_bypass = PLAYWRIGHT_PROXY_BYPASS if proxy_bypass is None else str(proxy_bypass or "").strip()

    if proxy_url is not None:
        resolved_proxy_url = str(proxy_url or "").strip()
        if resolved_proxy_url:
            proxy = _parse_proxy_url(resolved_proxy_url)
    elif PLAYWRIGHT_PROXY_URL:
        proxy = _parse_proxy_url(PLAYWRIGHT_PROXY_URL)
    elif PLAYWRIGHT_PROXY_SERVER:
        proxy = {"server": PLAYWRIGHT_PROXY_SERVER}
        if PLAYWRIGHT_PROXY_USERNAME:
            proxy["username"] = PLAYWRIGHT_PROXY_USERNAME
        if PLAYWRIGHT_PROXY_PASSWORD:
            proxy["password"] = PLAYWRIGHT_PROXY_PASSWORD

    if proxy:
        if resolved_bypass:
            proxy["bypass"] = resolved_bypass
        options["proxy"] = proxy

    return options
