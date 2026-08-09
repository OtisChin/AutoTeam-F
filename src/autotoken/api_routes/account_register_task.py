"""Account registration task launch route."""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import AliasChoices, BaseModel, Field


def _assert_roxybrowser_available() -> None:
    """Fail fast when RoxyBrowser mode is selected but the local API is unavailable."""

    try:
        from autotoken.roxybrowser_client import RoxyBrowserClient
        from autotoken.settings.config import get_roxybrowser_config

        cfg = get_roxybrowser_config()
        client = RoxyBrowserClient(cfg["api_host"], cfg["api_token"], timeout=3)
        workspaces = client.list_workspaces()
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                "RoxyBrowser 未连接或不可用，请启动 RoxyBrowser 客户端并确认设置页 API Host/Token 正确，"
                f"或取消“使用Roxy Browser”：{exc}"
            ),
        ) from exc
    if not workspaces:
        raise HTTPException(
            status_code=400,
            detail="RoxyBrowser 未找到可用工作空间，请先在客户端创建工作空间，或取消“使用Roxy Browser”",
        )


class ManualRegisterParams(BaseModel):
    mode: str = "single"
    registration_flow: str = Field("standard", validation_alias=AliasChoices("registration_flow", "registrationFlow"))
    count: int = 1
    concurrency: int = 3
    interval_seconds: float = 12.0
    jitter_min_seconds: float = 8.0
    jitter_max_seconds: float = 20.0
    domain: str | None = None
    domains: list[str] = Field(default_factory=list)
    prefix: str | None = None
    password: str | None = None
    mail_provider: str | None = Field(None, validation_alias=AliasChoices("mail_provider", "mailProvider"))
    luckmail_email_type: str | None = Field(
        None, validation_alias=AliasChoices("luckmail_email_type", "luckmailEmailType")
    )
    luckmail_preferred_domain: str | None = Field(
        None,
        validation_alias=AliasChoices("luckmail_preferred_domain", "luckmailPreferredDomain"),
    )
    luckmail_preferred_domains: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("luckmail_preferred_domains", "luckmailPreferredDomains"),
    )
    post_register_oauth: bool = False
    enable_totp_mfa: bool = Field(False, validation_alias=AliasChoices("enable_totp_mfa", "enableTotpMfa", "enable2fa", "enable2FA"))
    phone_only: bool = False
    protocol_register: bool = Field(False, validation_alias=AliasChoices("protocol_register", "protocolRegister"))
    use_roxybrowser: bool = Field(False, validation_alias=AliasChoices("use_roxybrowser", "useRoxyBrowser"))
    oauth_phone_sms_provider: str = Field(
        "",
        validation_alias=AliasChoices("oauth_phone_sms_provider", "oauthPhoneSmsProvider"),
    )
    oauth_phone_sms_country: str = Field(
        "",
        validation_alias=AliasChoices("oauth_phone_sms_country", "oauthPhoneSmsCountry"),
    )
    oauth_phone_sms_max_price: str = Field(
        "",
        validation_alias=AliasChoices("oauth_phone_sms_max_price", "oauthPhoneSmsMaxPrice"),
    )
    oauth_oasis_sms_cdks: str = Field(
        "",
        validation_alias=AliasChoices("oauth_oasis_sms_cdks", "oauthOasisSmsCdks", "oasis_sms_cdks", "oasisSmsCdks"),
    )
    proxy_url: str | None = Field(None, validation_alias=AliasChoices("proxy_url", "proxyUrl"))
    proxy_api_provider: str = Field("", validation_alias=AliasChoices("proxy_api_provider", "proxyApiProvider"))
    proxy_api_country: str = Field("JP", validation_alias=AliasChoices("proxy_api_country", "proxyApiCountry"))
    proxy_api_url: str = Field("", validation_alias=AliasChoices("proxy_api_url", "proxyApiUrl"))


def create_account_register_task_router(
    *,
    start_task: Callable[..., dict[str, Any]],
    normalize_proxy_url: Callable[[str], str],
    normalize_proxy_api_provider: Callable[[str | None], str],
    build_oauth_proxy_selector: Callable[..., tuple[Callable[[], str], dict[str, Any]]],
    normalize_oauth_phone_sms_provider: Callable[[str | None], str],
    normalize_oauth_smsbower_country: Callable[[str | None], str],
    normalize_oauth_smscloud_country: Callable[[str | None], str],
    normalize_oauth_hero_sms_country: Callable[[str | None], str],
    oauth_phone_sms_env: Callable[[], dict[str, str]],
    append_task_progress: Callable[[str | None, dict], Any],
    task_group_register: str,
    logger: Any,
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/tasks/add", status_code=202)
    def post_add(params: ManualRegisterParams | None = None):
        """注册账号（后台执行，注册成功后继续执行 personal OAuth 并生成 auth_file）"""
        from autotoken.core.identity import random_password
        from autotoken.interfaces.manager import cmd_register_accounts
        from autotoken.settings.runtime_config import get_register_domain, get_register_domains
        from autotoken.settings.setup_wizard import get_mail_provider

        params = params or ManualRegisterParams()
        prefix = (params.prefix or "").strip() or None
        password = (params.password or "").strip() or None
        mail_provider = get_mail_provider(params.mail_provider) if params.mail_provider else ""
        luckmail_email_type = (params.luckmail_email_type or "").strip()
        luckmail_preferred_domain = (params.luckmail_preferred_domain or "").strip().lstrip("@")
        luckmail_preferred_domains = []
        seen_luckmail_domains = set()
        for raw_domain in list(params.luckmail_preferred_domains or []) + (
            [luckmail_preferred_domain] if luckmail_preferred_domain else []
        ):
            cleaned = str(raw_domain or "").strip().lstrip("@")
            key = cleaned.lower()
            if key in seen_luckmail_domains:
                continue
            seen_luckmail_domains.add(key)
            luckmail_preferred_domains.append(cleaned)
        resolved_password = password or random_password()
        mode = (params.mode or "single").strip().lower()
        count = max(1, int(params.count or 1))
        concurrency = max(1, min(20, int(params.concurrency or 1)))
        interval_seconds = max(0.0, float(params.interval_seconds or 0.0))
        jitter_min_seconds = max(0.0, float(params.jitter_min_seconds or 0.0))
        jitter_max_seconds = max(0.0, float(params.jitter_max_seconds or 0.0))
        registration_flow = str(params.registration_flow or "standard").strip().lower()
        if registration_flow not in {"standard", "phone_cpa"}:
            raise HTTPException(status_code=400, detail="registration_flow 只支持 standard 或 phone_cpa")
        use_roxybrowser = registration_flow == "standard" and bool(params.use_roxybrowser)
        if use_roxybrowser:
            _assert_roxybrowser_available()
        register_mode = (
            "protocol"
            if registration_flow == "phone_cpa" or (bool(params.protocol_register) and not use_roxybrowser)
            else "browser"
        )
        phone_only = bool(params.phone_only)
        post_register_oauth = (registration_flow == "phone_cpa" and not phone_only) or bool(params.post_register_oauth)
        enable_totp_mfa = bool(params.enable_totp_mfa)
        oauth_phone_sms_provider = (
            normalize_oauth_phone_sms_provider(params.oauth_phone_sms_provider)
            if params.oauth_phone_sms_provider
            else ""
        )
        if params.oauth_phone_sms_country:
            if oauth_phone_sms_provider in {"oasis", "tujie"}:
                oauth_phone_sms_country = ""
            elif oauth_phone_sms_provider == "smsbower":
                oauth_phone_sms_country = normalize_oauth_smsbower_country(params.oauth_phone_sms_country)
            elif oauth_phone_sms_provider == "smscloud":
                oauth_phone_sms_country = normalize_oauth_smscloud_country(params.oauth_phone_sms_country)
            else:
                oauth_phone_sms_country = normalize_oauth_hero_sms_country(params.oauth_phone_sms_country)
        else:
            oauth_phone_sms_country = ""
        oauth_phone_sms_max_price = str(params.oauth_phone_sms_max_price or "").strip()
        oauth_oasis_sms_cdks = str(params.oauth_oasis_sms_cdks or "").strip()
        if registration_flow == "phone_cpa" and not oauth_phone_sms_provider:
            oauth_phone_sms_provider = normalize_oauth_phone_sms_provider(
                oauth_phone_sms_env().get("provider") or "phone_pool"
            )
        if post_register_oauth and oauth_phone_sms_provider in {"hero_sms", "smsbower", "smscloud"}:
            oauth_sms_cfg = oauth_phone_sms_env()
            key_field = "hero_sms_api_key" if oauth_phone_sms_provider == "hero_sms" else f"{oauth_phone_sms_provider}_api_key"
            key_present = bool(oauth_sms_cfg.get(key_field))
            if not key_present:
                raise HTTPException(
                    status_code=400, detail=f"启用 {oauth_phone_sms_provider} 前需要先在设置页配置 API Key"
                )
            logger.info(
                "[注册账号] OAuth 接码参数: provider=%s country=%s max_price=%s",
                oauth_phone_sms_provider,
                oauth_phone_sms_country or "<default>",
                oauth_phone_sms_max_price or "<default>",
            )
        if post_register_oauth and oauth_phone_sms_provider in {"oasis", "tujie"}:
            oauth_sms_cfg = oauth_phone_sms_env()
            cdk_field = "oasis_sms_cdks" if oauth_phone_sms_provider == "oasis" else "tujie_sms_cdks"
            cdk_file_field = "oasis_sms_cdk_file" if oauth_phone_sms_provider == "oasis" else "tujie_sms_cdk_file"
            provider_label = "Oasis" if oauth_phone_sms_provider == "oasis" else "TuJie"
            if not (
                oauth_oasis_sms_cdks
                or str(oauth_sms_cfg.get(cdk_field) or "").strip()
                or str(oauth_sms_cfg.get(cdk_file_field) or "").strip()
            ):
                raise HTTPException(status_code=400, detail=f"启用 {provider_label} 前需要先在设置页配置 CDK 池")
            oauth_phone_sms_country = ""
            oauth_phone_sms_max_price = ""
            logger.info(
                "[注册账号] OAuth 接码参数: provider=%s cdk_pool=%s",
                oauth_phone_sms_provider,
                "task_inline" if oauth_oasis_sms_cdks else "configured",
            )
        if mode not in ("single", "batch"):
            raise HTTPException(status_code=400, detail="mode 只支持 single 或 batch")
        if jitter_min_seconds > jitter_max_seconds:
            raise HTTPException(status_code=400, detail="随机抖动区间必须满足 min <= max")

        configured_domains = get_register_domains()
        domain_required = mail_provider not in {"luckmail", "outlook", "icloud", "mail.com"} and not phone_only

        def _clean_domain(value) -> str:
            return str(value or "").strip().lstrip("@").strip()

        def _validate_domain(value: str):
            if configured_domains and value not in configured_domains:
                raise HTTPException(status_code=400, detail=f"域名 @{value} 不在可选列表中")

        selected_domain = _clean_domain(params.domain)
        selected_domains = []
        if mode == "batch":
            seen = set()
            for raw_domain in params.domains or []:
                value = _clean_domain(raw_domain)
                if not value or value in seen:
                    continue
                _validate_domain(value)
                seen.add(value)
                selected_domains.append(value)

        if not selected_domains and domain_required:
            if selected_domain:
                _validate_domain(selected_domain)
            else:
                selected_domain = get_register_domain()
            if selected_domain:
                selected_domains = [selected_domain]

        if not selected_domains and domain_required:
            raise HTTPException(status_code=400, detail="未配置可用注册域名")

        if selected_domains:
            selected_domain = selected_domains[0]
        elif domain_required:
            selected_domain = ""

        if mode == "single":
            count = 1
            concurrency = 1
            jitter_min_seconds = 0.0
            jitter_max_seconds = 0.0
            selected_domains = [selected_domain] if selected_domain else []
        raw_proxy_url = str(params.proxy_url or "").strip()
        try:
            normalized_proxy_url = normalize_proxy_url(raw_proxy_url) if raw_proxy_url else ""
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"注册代理格式错误: {raw_proxy_url} ({exc})") from exc

        register_proxy_selector = None
        register_proxy_meta = {}
        proxy_api_provider = (
            normalize_proxy_api_provider(params.proxy_api_provider) if params.proxy_api_provider else ""
        )
        proxy_api_country = "".join(
            ch for ch in str(params.proxy_api_country or "JP").strip().upper() if ch.isalpha()
        )[:2] or "JP"
        proxy_api_url = str(params.proxy_api_url or "").strip()
        if proxy_api_provider or proxy_api_url:
            register_proxy_selector, register_proxy_meta = build_oauth_proxy_selector(
                proxy_url=normalized_proxy_url,
                proxy_api_provider=proxy_api_provider or "1024proxy",
                proxy_api_url=proxy_api_url,
                proxy_api_country=proxy_api_country,
            )

        task_params = {
            "mode": mode,
            "registration_flow": registration_flow,
            "count": count,
            "concurrency": concurrency,
            "interval_seconds": interval_seconds,
            "jitter_min_seconds": jitter_min_seconds,
            "jitter_max_seconds": jitter_max_seconds,
            "domain": selected_domain,
            "domains": selected_domains,
            "prefix": prefix or "",
            "password_mode": "provided" if password else "random",
            "mail_provider": mail_provider or "<default>",
            "luckmail_email_type": luckmail_email_type or "",
            "luckmail_preferred_domain": luckmail_preferred_domain or "",
            "luckmail_preferred_domains": luckmail_preferred_domains,
            "post_register_oauth": post_register_oauth,
            "enable_totp_mfa": enable_totp_mfa,
            "phone_only": phone_only,
            "oauth_phone_sms_provider": oauth_phone_sms_provider or "<default>",
            "oauth_phone_sms_country": oauth_phone_sms_country or "",
            "oauth_phone_sms_max_price": oauth_phone_sms_max_price,
            "oauth_oasis_sms_cdk_count": len(
                [item for item in oauth_oasis_sms_cdks.replace(",", "\n").replace(";", "\n").splitlines() if item.strip()]
            ),
            "register_mode": register_mode,
            "use_roxybrowser": use_roxybrowser,
            "proxy_url_present": bool(normalized_proxy_url),
            "proxy_api_provider": proxy_api_provider,
            "proxy_api_country": proxy_api_country if (proxy_api_provider or proxy_api_url) else "",
            "proxy_api_url_present": bool(proxy_api_url),
            **register_proxy_meta,
        }

        def _run_register(task_id: str, **_ignored_kwargs):
            def _register_progress(progress: dict):
                append_task_progress(task_id, progress)

            return cmd_register_accounts(
                count=count,
                concurrency=concurrency,
                interval_seconds=interval_seconds,
                jitter_min_seconds=jitter_min_seconds,
                jitter_max_seconds=jitter_max_seconds,
                email_prefix=prefix,
                password=resolved_password,
                domain=selected_domain,
                domains=selected_domains,
                mail_provider=mail_provider or None,
                luckmail_email_type=luckmail_email_type or None,
                luckmail_preferred_domain=luckmail_preferred_domain,
                luckmail_preferred_domains=luckmail_preferred_domains,
                post_register_oauth=post_register_oauth,
                enable_totp_mfa=enable_totp_mfa,
                phone_only=phone_only,
                registration_flow=registration_flow,
                register_mode=register_mode,
                proxy_url=normalized_proxy_url,
                use_roxybrowser=use_roxybrowser,
                register_proxy_selector=register_proxy_selector,
                register_proxy_meta=register_proxy_meta,
                oauth_phone_sms_provider=oauth_phone_sms_provider or None,
                oauth_phone_sms_country=oauth_phone_sms_country or None,
                oauth_phone_sms_max_price=oauth_phone_sms_max_price,
                oauth_oasis_sms_cdks=(oauth_oasis_sms_cdks or None) if oauth_phone_sms_provider in {"oasis", "tujie"} else None,
                progress_callback=_register_progress,
            )

        return start_task(
            "register",
            _run_register,
            task_params,
            count=count,
            concurrency=concurrency,
            interval_seconds=interval_seconds,
            jitter_min_seconds=jitter_min_seconds,
            jitter_max_seconds=jitter_max_seconds,
            email_prefix=prefix,
            password=resolved_password,
            domain=selected_domain,
            domains=selected_domains,
            mail_provider=mail_provider or None,
            luckmail_email_type=luckmail_email_type or None,
            luckmail_preferred_domain=luckmail_preferred_domain,
            luckmail_preferred_domains=luckmail_preferred_domains,
            post_register_oauth=post_register_oauth,
            enable_totp_mfa=enable_totp_mfa,
            phone_only=phone_only,
            registration_flow=registration_flow,
            register_mode=register_mode,
            proxy_url=normalized_proxy_url,
            use_roxybrowser=use_roxybrowser,
            oauth_phone_sms_provider=oauth_phone_sms_provider or None,
            oauth_phone_sms_country=oauth_phone_sms_country or None,
            oauth_phone_sms_max_price=oauth_phone_sms_max_price,
            oauth_oasis_sms_cdks=(oauth_oasis_sms_cdks or None) if oauth_phone_sms_provider in {"oasis", "tujie"} else None,
            task_group=task_group_register,
            pass_task_id=True,
        )

    return router
