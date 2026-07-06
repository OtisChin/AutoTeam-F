"""首次启动初始化向导 — 交互式填写 .env 中的必填配置"""

import logging
import os
import re
import secrets
import sys

from autotoken.core.env import read_env_lines
from autotoken.core.paths import PROJECT_ROOT
from autotoken.core.textio import parse_env_line, read_text, write_text

logger = logging.getLogger(__name__)

ENV_FILE = PROJECT_ROOT / ".env"
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"

MAIL_PROVIDER_OPTIONS = [
    {
        "value": "cloudflare_temp_email",
        "label": "cloudflare_temp_email",
        "description": "dreamhunter2333/cloudflare_temp_email",
    },
    {
        "value": "cloud-mail",
        "label": "cloud-mail",
        "description": "cloud-mail",
    },
    {
        "value": "outlook",
        "label": "Outlook",
        "description": "Outlook/Hotmail 账号池注册",
    },
    {
        "value": "mail.com",
        "label": "mail.com",
        "description": "mail.com SQLite 邮箱池注册",
    },
    {
        "value": "luckmail",
        "label": "LuckMail",
        "description": "LuckMail 已购邮箱 token 接码",
    },
]

COMMON_SETUP_FIELDS = [
    ("CPA_URL", "CPA (CLIProxyAPI) 地址（可选）", "", True),
    ("CPA_KEY", "CPA 管理密钥（可选）", "", True),
    ("PLAYWRIGHT_PROXY_URL", "Playwright 浏览器代理 URL（可选，如 socks5://host:port）", "", True),
    ("PLAYWRIGHT_PROXY_BYPASS", "Playwright 代理绕过列表（可选，如 localhost,127.0.0.1）", "", True),
    ("PLAYWRIGHT_BACKGROUND", "Playwright 后台运行（1=最小化/屏幕外，0=显示窗口）", "1", True),
    ("API_KEY", "API 鉴权密钥（回车自动生成）", "", False),
]

PROVIDER_SETUP_FIELDS = {
    "cloudflare_temp_email": [
        ("CLOUDFLARE_TEMP_EMAIL_BASE_URL", "cloudflare_temp_email API 地址", "", False),
        ("CLOUDFLARE_TEMP_EMAIL_ADMIN_PASSWORD", "cloudflare_temp_email 管理员密码", "", False),
        ("CLOUDFLARE_TEMP_EMAIL_DOMAIN", "cloudflare_temp_email 邮箱域名（如 @example.com）", "", False),
    ],
    "cloud-mail": [
        ("CLOUD_MAIL_API_URL", "cloud-mail API 地址", "", False),
        ("CLOUD_MAIL_ADMIN_EMAIL", "cloud-mail 管理员邮箱", "", False),
        ("CLOUD_MAIL_ADMIN_PASSWORD", "cloud-mail 管理员密码", "", False),
        ("CLOUD_MAIL_DOMAIN", "cloud-mail 邮箱域名（如 @example.com）", "", False),
    ],
    "outlook": [
        (
            "OUTLOOK_ACCOUNTS_FILE",
            "Outlook 账号池文件路径（默认 data/outlook_accounts.txt）",
            "data/outlook_accounts.txt",
            True,
        ),
        ("OUTLOOK_ACCOUNTS", "Outlook 账号池内联（email----password，每行/分号分隔）", "", True),
        (
            "OUTLOOK_DEFAULT_CLIENT_ID",
            "Outlook OAuth 默认 Client ID（可选）",
            "24d9a0ed-8787-4584-883c-2fd79308940a",
            True,
        ),
        ("OUTLOOK_PROVIDER_PRIORITY", "Outlook 读取优先级", "imap_old,imap_new,graph_api", True),
        ("OUTLOOK_PROXY_URL", "Outlook 邮件读取代理 URL（可选）", "", True),
    ],
    "mail.com": [],
    "luckmail": [
        ("LUCKMAIL_BASE_URL", "LuckMail API 地址", "https://mail.luckyous.com", True),
        (
            "LUCKMAIL_ACCOUNTS_FILE",
            "LuckMail 已购邮箱文件路径（默认 data/luckmail_accounts.txt）",
            "data/luckmail_accounts.txt",
            True,
        ),
        ("LUCKMAIL_ACCOUNTS", "LuckMail 已购邮箱内联（email----tok_xxx，每行/分号分隔）", "", True),
        ("LUCKMAIL_API_KEY", "LuckMail API Key（可选，用于自动购买邮箱）", "", True),
        ("LUCKMAIL_PROJECT_CODE", "LuckMail 项目编码", "openai", True),
        ("LUCKMAIL_EMAIL_TYPE", "LuckMail 邮箱类型", "ms_graph", True),
        (
            "LUCKMAIL_PREFERRED_DOMAIN",
            "LuckMail 优先域名（可选，如 outlook.cl / outlook.my / outlook.ph）",
            "",
            True,
        ),
    ],
}

REQUIRED_CONFIGS = [
    ("MAIL_PROVIDER", "Mail Provider", "cloudflare_temp_email", True),
    *COMMON_SETUP_FIELDS,
]


def _read_env() -> dict[str, str]:
    """读取 .env 文件为 dict"""
    result = {}
    for line in read_env_lines(ENV_FILE):
        parsed = parse_env_line(line)
        if parsed:
            key, value = parsed
            result[key] = value
    return result


def _write_env(key: str, value: str):
    """写入或更新 .env 中的某个 key"""
    if ENV_FILE.exists():
        content = read_text(ENV_FILE)
        pattern = rf"^{re.escape(key)}=.*$"
        if re.search(pattern, content, re.MULTILINE):
            content = re.sub(pattern, f"{key}={value}", content, flags=re.MULTILINE)
        else:
            content = content.rstrip() + f"\n{key}={value}\n"
        write_text(ENV_FILE, content)
    else:
        # 从 .env.example 复制再写入
        if ENV_EXAMPLE.exists():
            content = read_text(ENV_EXAMPLE)
            pattern = rf"^{re.escape(key)}=.*$"
            if re.search(pattern, content, re.MULTILINE):
                content = re.sub(pattern, f"{key}={value}", content, flags=re.MULTILINE)
            write_text(ENV_FILE, content)
        else:
            write_text(ENV_FILE, f"{key}={value}\n")


def _is_interactive() -> bool:
    """检测是否有终端交互能力（Docker 等非交互环境返回 False）"""
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


def _verify_cpa_enabled() -> bool:
    return os.environ.get("AUTOTOKEN_VERIFY_CPA", "").strip().lower() in ("1", "true", "yes", "on")


def get_mail_provider(raw: str | None = None) -> str:
    provider = (raw or os.environ.get("MAIL_PROVIDER") or "cloudflare_temp_email").strip().lower()
    if provider in ("cf_temp_email", "cloudflare_temp_email", ""):
        return "cloudflare_temp_email"
    if provider in ("maillab", "cloud-mail", "cloud_mail"):
        return "cloud-mail"
    if provider in ("outlook", "microsoft_outlook", "hotmail"):
        return "outlook"
    if provider in ("mail.com", "mailcom", "mail_com"):
        return "mail.com"
    if provider in ("luckmail", "lucky_mail", "lucky-mail"):
        return "luckmail"
    return provider


def get_required_configs_for_provider(provider: str | None = None):
    normalized = get_mail_provider(provider)
    return [
        ("MAIL_PROVIDER", "Mail Provider", normalized or "cloudflare_temp_email", True),
        *PROVIDER_SETUP_FIELDS.get(normalized, PROVIDER_SETUP_FIELDS["cloudflare_temp_email"]),
        *COMMON_SETUP_FIELDS,
    ]


def get_setup_schema(env: dict[str, str] | None = None) -> dict:
    env = env or _read_env()
    provider = get_mail_provider(env.get("MAIL_PROVIDER", "") or os.environ.get("MAIL_PROVIDER", ""))
    return {
        "provider": provider,
        "provider_options": MAIL_PROVIDER_OPTIONS,
        "provider_fields": {
            key: [
                {
                    "key": field_key,
                    "prompt": prompt,
                    "default": default,
                    "optional": optional,
                }
                for field_key, prompt, default, optional in fields
            ]
            for key, fields in PROVIDER_SETUP_FIELDS.items()
        },
        "fields": [
            {
                "key": key,
                "prompt": prompt,
                "default": default,
                "optional": optional,
            }
            for key, prompt, default, optional in get_required_configs_for_provider(provider)
        ],
    }


def check_and_setup(interactive: bool = True) -> bool:
    """
    检查必填配置是否齐全，缺失时交互式提示输入。
    返回 True 表示配置完整，False 表示用户中断或非交互模式下缺配置。
    """
    interactive = interactive and _is_interactive()
    env = _read_env()
    missing = []

    provider = get_mail_provider(env.get("MAIL_PROVIDER", "") or os.environ.get("MAIL_PROVIDER", ""))
    required_configs = get_required_configs_for_provider(provider)

    for key, prompt, default, optional in required_configs:
        val = env.get(key, "") or os.environ.get(key, "")
        if not val and not optional:
            missing.append((key, prompt, default, optional))

    if not missing:
        # 配置齐全，每次启动验证连通性
        _skip = os.environ.get("AUTOTOKEN_SKIP_VERIFY", "").strip().lower() in ("1", "true", "yes")
        if not _verify_temporary_email():
            if _skip:
                logger.warning("[验证] 临时邮箱服务验证失败，已根据 AUTOTOKEN_SKIP_VERIFY 继续启动")
            else:
                logger.error(
                    "[验证] 临时邮箱服务配置有误，请修改 .env 后重新启动（或设置 AUTOTOKEN_SKIP_VERIFY=1 跳过）"
                )
                sys.exit(1)
        if not _verify_cpa():
            if _skip:
                logger.warning("[验证] CPA 验证失败，已根据 AUTOTOKEN_SKIP_VERIFY 继续启动")
            else:
                logger.error("[验证] CPA 配置有误，请修改 .env 后重新启动（或设置 AUTOTOKEN_SKIP_VERIFY=1 跳过）")
                sys.exit(1)
        return True

    if not interactive:
        for key, prompt, _, _ in missing:
            logger.warning("[配置] 缺少必填项: %s (%s)", key, prompt)
        logger.warning("[配置] 请通过 Web 面板或编辑 .env 文件填入配置")
        return False

    print("\n=== AutoToken 首次配置 ===\n")
    print("检测到以下配置项需要填写，直接回车使用默认值（如有）:\n")

    for key, prompt, default, optional in missing:
        hint = f" [{default}]" if default else ""
        if key == "API_KEY":
            hint = " [回车自动生成]"

        try:
            value = input(f"  {prompt}{hint}: ").strip()
        except KeyboardInterrupt:
            print("\n\n已取消配置。")
            raise SystemExit(130) from None

        if not value:
            if key == "API_KEY":
                value = secrets.token_urlsafe(24)
                print(f"    -> 已自动生成: {value}")
            elif default:
                value = default
                print(f"    -> 使用默认值: {value}")
            elif not optional:
                print("    -> 跳过（必填项，后续可在 .env 中补充）")
                continue

        if value:
            _write_env(key, value)
            # 同步到当前进程的环境变量
            os.environ[key] = value

    print("\n配置已保存到 .env\n")

    # 重新加载 config 和依赖模块
    import importlib

    from autotoken.settings import config as config_module

    importlib.reload(config_module)
    try:
        from autotoken import mail as mail_module

        importlib.reload(mail_module)
    except Exception:
        pass

    # 验证配置连通性
    if not _verify_temporary_email():
        logger.error("[验证] 临时邮箱服务配置有误，请修改 .env 后重新启动")
        sys.exit(1)
    if not _verify_cpa():
        logger.error("[验证] CPA 配置有误，请修改 .env 后重新启动")
        sys.exit(1)

    return True


def _sniff_provider_mismatch(provider: str) -> None:
    """轻量探测 base_url 的路由指纹,与 MAIL_PROVIDER 不匹配时打 warning。

    cloudflare_temp_email:`/admin/address` 不带 admin auth 应回 401(认 x-admin-auth header)
    cloud-mail:优先探测 `POST /api/login`,兼容旧部署再尝试 `POST /login`
    任一探测失败仅 warning,不阻断启动 — 真正校验在后续 login/create 调用。
    """
    import requests

    base = ""
    if provider == "cloudflare_temp_email":
        base = (os.environ.get("CLOUDFLARE_TEMP_EMAIL_BASE_URL") or os.environ.get("CLOUDMAIL_BASE_URL") or "").rstrip(
            "/"
        )
    elif provider == "cloud-mail":
        base = (os.environ.get("CLOUD_MAIL_API_URL") or os.environ.get("MAILLAB_API_URL") or "").rstrip("/")
    if not base:
        return

    try:
        # /admin/address 是 cloudflare_temp_email 独有路由
        r_admin = requests.get(f"{base}/admin/address", timeout=5)
        admin_route_alive = r_admin.status_code in (200, 401, 403)
    except Exception:
        admin_route_alive = False

    try:
        # cloud-mail 现部署通常挂在 /api/login,且必须 POST 才能正确判断。
        login_route_alive = False
        probe_body = {"email": "__probe__@example.com", "password": "__probe__"}
        for path in ("/api/login", "/login"):
            try:
                r_login = requests.post(f"{base}{path}", json=probe_body, timeout=5)
                if r_login.status_code != 404:
                    login_route_alive = True
                    break
            except Exception:
                continue
    except Exception:
        login_route_alive = False

    if provider == "cloudflare_temp_email":
        # 期待 admin_route_alive=True;若 admin 路由 404 而 login 路由活跃 → 错配
        if not admin_route_alive and login_route_alive:
            logger.warning(
                "[验证] CLOUDFLARE_TEMP_EMAIL_BASE_URL=%s 看起来不是 dreamhunter2333/cloudflare_temp_email"
                "(/admin/address 不可达,但 cloud-mail 登录路由活跃)。如果你用的是 cnitlrt 原版的"
                "'cloudmail' 服务器,那其实是 cloud-mail,请改 MAIL_PROVIDER=cloud-mail。",
                base,
            )
    elif provider == "cloud-mail" and not login_route_alive and admin_route_alive:
        logger.warning(
            "[验证] CLOUD_MAIL_API_URL=%s 看起来不是 cloud-mail"
            "(cloud-mail 登录路由不可达,但 /admin/address 活跃)。这是 dreamhunter2333/cloudflare_temp_email,"
            "请改 MAIL_PROVIDER=cloudflare_temp_email 并配置 CLOUDFLARE_TEMP_EMAIL_BASE_URL/CLOUDFLARE_TEMP_EMAIL_ADMIN_PASSWORD。",
            base,
        )


def _verify_temporary_email():
    """验证 mail provider 配置:登录 + 创建测试邮箱 + 删除。

    根据 MAIL_PROVIDER 自动走对应分支:
      - cloudflare_temp_email(默认):需要 CLOUDFLARE_TEMP_EMAIL_BASE_URL / CLOUDFLARE_TEMP_EMAIL_ADMIN_PASSWORD / CLOUDFLARE_TEMP_EMAIL_DOMAIN
      - cloud-mail:需要 CLOUD_MAIL_API_URL / CLOUD_MAIL_ADMIN_EMAIL / CLOUD_MAIL_ADMIN_PASSWORD / CLOUD_MAIL_DOMAIN
      - outlook:需要 OUTLOOK_ACCOUNTS_FILE 或 OUTLOOK_ACCOUNTS 提供 Outlook 账号池
      - luckmail:需要 LUCKMAIL_ACCOUNTS_FILE / LUCKMAIL_ACCOUNTS，或 LUCKMAIL_API_KEY 自动购买
    """
    provider = get_mail_provider()

    if provider == "cloudflare_temp_email":
        base_url = os.environ.get("CLOUDFLARE_TEMP_EMAIL_BASE_URL") or os.environ.get("CLOUDMAIL_BASE_URL", "")
        password = os.environ.get("CLOUDFLARE_TEMP_EMAIL_ADMIN_PASSWORD") or os.environ.get("CLOUDMAIL_PASSWORD", "")
        domain = os.environ.get("CLOUDFLARE_TEMP_EMAIL_DOMAIN") or os.environ.get("CLOUDMAIL_DOMAIN", "")
        if not all([base_url, password, domain]):
            return
        check_keys = "CLOUDFLARE_TEMP_EMAIL_BASE_URL、CLOUDFLARE_TEMP_EMAIL_ADMIN_PASSWORD"
        domain_key = "CLOUDFLARE_TEMP_EMAIL_DOMAIN"
        label = "cloudflare_temp_email"
    elif provider == "cloud-mail":
        api_url = os.environ.get("CLOUD_MAIL_API_URL") or os.environ.get("MAILLAB_API_URL", "")
        username = os.environ.get("CLOUD_MAIL_ADMIN_EMAIL") or os.environ.get("MAILLAB_USERNAME", "")
        password = os.environ.get("CLOUD_MAIL_ADMIN_PASSWORD") or os.environ.get("MAILLAB_PASSWORD", "")
        domain = (
            os.environ.get("CLOUD_MAIL_DOMAIN")
            or os.environ.get("MAILLAB_DOMAIN")
            or os.environ.get("CLOUDMAIL_DOMAIN", "")
        )
        if not all([api_url, username, password, domain]):
            return
        check_keys = "CLOUD_MAIL_API_URL、CLOUD_MAIL_ADMIN_EMAIL、CLOUD_MAIL_ADMIN_PASSWORD"
        domain_key = "CLOUD_MAIL_DOMAIN"
        label = "cloud-mail"
    elif provider == "outlook":
        accounts_file = os.environ.get("OUTLOOK_ACCOUNTS_FILE", "")
        accounts_inline = os.environ.get("OUTLOOK_ACCOUNTS", "")
        default_file = PROJECT_ROOT / "data" / "outlook_accounts.txt"
        if not accounts_inline and not accounts_file and not default_file.exists():
            return
        check_keys = "OUTLOOK_ACCOUNTS_FILE 或 OUTLOOK_ACCOUNTS"
        domain_key = "OUTLOOK_ACCOUNTS_FILE"
        label = "outlook"
    elif provider == "mail.com":
        check_keys = "mail_accounts SQLite"
        domain_key = "mail_accounts"
        label = "mail.com"
    elif provider == "luckmail":
        accounts_file = os.environ.get("LUCKMAIL_ACCOUNTS_FILE", "")
        accounts_inline = os.environ.get("LUCKMAIL_ACCOUNTS", "")
        api_key = os.environ.get("LUCKMAIL_API_KEY", "")
        default_file = PROJECT_ROOT / "data" / "luckmail_accounts.txt"
        if not accounts_inline and not accounts_file and not default_file.exists() and not api_key:
            return
        check_keys = "LUCKMAIL_ACCOUNTS_FILE / LUCKMAIL_ACCOUNTS 或 LUCKMAIL_API_KEY"
        domain_key = "LUCKMAIL_ACCOUNTS_FILE"
        label = "luckmail"
    else:
        logger.error(
            "[验证] 未知 MAIL_PROVIDER=%s,可选: cloudflare_temp_email | cloud-mail | outlook | mail.com | luckmail",
            provider,
        )
        return False

    logger.info("[验证] %s 配置...", label)

    # 启动前轻量协议嗅探:base_url 路由指纹与 MAIL_PROVIDER 不一致时提前提示,
    # 避免用户看到"登录成功 → 创建失败"这种半成功假象(issue #1)。
    _sniff_provider_mismatch(provider)

    try:
        from autotoken.mail import TemporaryEmailClient

        client = TemporaryEmailClient()
        client.login()
        logger.info("[验证] %s 登录成功", label)
    except Exception as e:
        logger.error("[验证] %s 登录失败: %s", label, e)
        logger.error("[验证] 请检查 %s", check_keys)
        return False

    if provider in ("outlook", "mail.com", "luckmail"):
        logger.info("[验证] %s 配置验证通过", label)
        return True

    test_account_id = None
    try:
        import uuid as _uuid

        test_account_id, test_email = client.create_temp_email(prefix=f"at-test-{_uuid.uuid4().hex[:6]}")
        logger.info("[验证] %s 创建测试邮箱成功: %s", label, test_email)
    except Exception as e:
        logger.error("[验证] %s 创建邮箱失败: %s", label, e)
        logger.error("[验证] 请检查 %s 是否正确", domain_key)
        return False

    try:
        if test_account_id:
            client.delete_account(test_account_id)
            logger.info("[验证] %s 测试邮箱已清理", label)
    except Exception as e:
        logger.warning("[验证] %s 清理测试邮箱失败: %s(不影响使用)", label, e)

    logger.info("[验证] %s 配置验证通过", label)
    return True


_verify_cloudmail = _verify_temporary_email


def _verify_cpa():
    """验证 CPA 配置是否正确：获取认证文件列表"""
    cpa_url = os.environ.get("CPA_URL", "")
    cpa_key = os.environ.get("CPA_KEY", "")

    if not cpa_url or not cpa_key:
        return True  # 没配就跳过
    if not _verify_cpa_enabled():
        logger.info("[验证] CPA 连通性检测已关闭（设置 AUTOTOKEN_VERIFY_CPA=1 可开启）")
        return True

    logger.info("[验证] CPA 配置...")

    try:
        import requests

        resp = requests.get(
            f"{cpa_url}/v0/management/auth-files",
            headers={"Authorization": f"Bearer {cpa_key}"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            count = len(data.get("files", []))
            logger.info("[验证] CPA 连接成功（当前 %d 个认证文件）", count)
            return True
        if resp.status_code == 401:
            logger.error("[验证] CPA 连接失败: 密钥无效 (401)")
            logger.error("[验证] 请检查 CPA_KEY 是否正确")
            return False
        logger.error("[验证] CPA 连接失败: HTTP %d", resp.status_code)
        logger.error("[验证] 请检查 CPA_URL 是否正确")
        return False
    except requests.exceptions.ConnectionError:
        logger.error("[验证] CPA 连接失败: 无法连接到 %s", cpa_url)
        logger.error("[验证] 请检查 CPA_URL 是否正确，CPA 服务是否已启动")
        return False
    except Exception as e:
        logger.error("[验证] CPA 连接失败: %s", e)
        return False
