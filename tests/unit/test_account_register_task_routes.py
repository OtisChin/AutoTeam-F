import pytest
from fastapi import HTTPException

from autotoken.api_routes.account_register_task import ManualRegisterParams, create_account_register_task_router
from autotoken.services.task_runtime import TASK_GROUP_REGISTER


def _logger():
    return type("Logger", (), {"info": lambda *_args, **_kwargs: None})()


def _routes(started, progress=None, *, oauth_env=None, proxy_meta=None, proxy_selector_calls=None):
    progress = progress if progress is not None else []
    oauth_env = oauth_env if oauth_env is not None else {}
    proxy_meta = proxy_meta if proxy_meta is not None else {}
    proxy_selector_calls = proxy_selector_calls if proxy_selector_calls is not None else []

    def build_oauth_proxy_selector(**kwargs):
        proxy_selector_calls.append(kwargs)
        return lambda: "http://proxy.example:8080", proxy_meta

    def start_task(command, func, params, *args, **kwargs):
        started.append({"command": command, "func": func, "params": params, "args": args, "kwargs": kwargs})
        return {"task_id": "task-1", "command": command, "params": params}

    router = create_account_register_task_router(
        start_task=start_task,
        normalize_proxy_url=lambda value: f"normalized:{value}",
        normalize_proxy_api_provider=lambda value: str(value or "").strip().lower(),
        build_oauth_proxy_selector=build_oauth_proxy_selector,
        normalize_oauth_phone_sms_provider=lambda value: str(value or "").strip().lower(),
        normalize_oauth_smsbower_country=lambda value: str(value or "").strip().upper(),
        normalize_oauth_smscloud_country=lambda value: f"cloud:{str(value or '').strip()}",
        normalize_oauth_hero_sms_country=lambda value: str(value or "").strip().lower(),
        oauth_phone_sms_env=lambda: oauth_env,
        append_task_progress=lambda task_id, item: progress.append({"task_id": task_id, **item}),
        task_group_register=TASK_GROUP_REGISTER,
        logger=_logger(),
    )
    return {route.endpoint.__name__: route.endpoint for route in router.routes}


def test_post_add_single_uses_default_domain_and_random_password(monkeypatch):
    started = []
    calls = []
    monkeypatch.setattr("autotoken.runtime_config.get_register_domains", lambda: ["example.com"])
    monkeypatch.setattr("autotoken.runtime_config.get_register_domain", lambda: "example.com")
    monkeypatch.setattr("autotoken.identity.random_password", lambda: "generated-pass")
    monkeypatch.setattr("autotoken.setup_wizard.get_mail_provider", lambda value=None: value or "cloudmail")
    monkeypatch.setattr("autotoken.manager.cmd_register_accounts", lambda **kwargs: calls.append(kwargs) or {"created": 1})

    routes = _routes(started)
    result = routes["post_add"](ManualRegisterParams(prefix=" demo ", password=""))

    assert result["command"] == "register"
    assert started[0]["params"]["domain"] == "example.com"
    assert started[0]["params"]["domains"] == ["example.com"]
    assert started[0]["params"]["password_mode"] == "random"
    assert started[0]["kwargs"]["task_group"] == TASK_GROUP_REGISTER
    assert started[0]["kwargs"]["pass_task_id"] is True

    assert started[0]["func"]("task-register") == {"created": 1}
    assert calls[0]["email_prefix"] == "demo"
    assert calls[0]["password"] == "generated-pass"
    assert calls[0]["domain"] == "example.com"
    assert calls[0]["progress_callback"] is not None


def test_post_add_batch_deduplicates_and_validates_domains(monkeypatch):
    started = []
    monkeypatch.setattr("autotoken.runtime_config.get_register_domains", lambda: ["a.com", "b.com"])
    monkeypatch.setattr("autotoken.runtime_config.get_register_domain", lambda: "a.com")
    monkeypatch.setattr("autotoken.identity.random_password", lambda: "generated-pass")
    monkeypatch.setattr("autotoken.setup_wizard.get_mail_provider", lambda value=None: value or "cloudmail")

    routes = _routes(started)
    result = routes["post_add"](ManualRegisterParams(mode="batch", count=4, concurrency=9, domains=["@a.com", "b.com", "a.com"]))

    assert result["params"]["mode"] == "batch"
    assert result["params"]["count"] == 4
    assert result["params"]["concurrency"] == 9
    assert result["params"]["domain"] == "a.com"
    assert result["params"]["domains"] == ["a.com", "b.com"]

    with pytest.raises(HTTPException) as exc_info:
        routes["post_add"](ManualRegisterParams(mode="batch", domains=["missing.com"]))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "域名 @missing.com 不在可选列表中"


@pytest.mark.parametrize("country", ["BR", "TH", "TR", "KR"])
def test_post_add_proxy_api_country_is_passed_to_selector(monkeypatch, country):
    started = []
    proxy_selector_calls = []
    monkeypatch.setattr("autotoken.runtime_config.get_register_domains", lambda: ["example.com"])
    monkeypatch.setattr("autotoken.runtime_config.get_register_domain", lambda: "example.com")
    monkeypatch.setattr("autotoken.identity.random_password", lambda: "generated-pass")
    monkeypatch.setattr("autotoken.setup_wizard.get_mail_provider", lambda value=None: value or "cloudmail")

    routes = _routes(started, proxy_selector_calls=proxy_selector_calls)
    result = routes["post_add"](
        ManualRegisterParams(proxy_api_provider="cliproxy", proxy_api_country=country.lower())
    )

    assert result["params"]["proxy_api_provider"] == "cliproxy"
    assert result["params"]["proxy_api_country"] == country
    assert proxy_selector_calls[0]["proxy_api_provider"] == "cliproxy"
    assert proxy_selector_calls[0]["proxy_api_country"] == country


def test_post_add_passes_use_roxybrowser_to_register_worker(monkeypatch):
    started = []
    calls = []
    monkeypatch.setattr("autotoken.runtime_config.get_register_domains", lambda: ["example.com"])
    monkeypatch.setattr("autotoken.runtime_config.get_register_domain", lambda: "example.com")
    monkeypatch.setattr("autotoken.identity.random_password", lambda: "generated-pass")
    monkeypatch.setattr("autotoken.setup_wizard.get_mail_provider", lambda value=None: value or "cloudmail")
    monkeypatch.setattr("autotoken.manager.cmd_register_accounts", lambda **kwargs: calls.append(kwargs) or {"created": 1})

    class AvailableRoxyClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def list_workspaces(self):
            return [{"id": "workspace-1", "name": "Default"}]

    monkeypatch.setattr("autotoken.settings.config.get_roxybrowser_config", lambda: {"api_host": "http://127.0.0.1:50000", "api_token": "token"})
    monkeypatch.setattr("autotoken.roxybrowser_client.RoxyBrowserClient", AvailableRoxyClient)

    routes = _routes(started)
    result = routes["post_add"](ManualRegisterParams(use_roxybrowser=True))

    assert result["params"]["use_roxybrowser"] is True
    assert started[0]["func"]("task-register") == {"created": 1}
    assert calls[0]["use_roxybrowser"] is True


def test_post_add_rejects_unavailable_roxybrowser_before_starting_task(monkeypatch):
    started = []
    monkeypatch.setattr("autotoken.runtime_config.get_register_domains", lambda: ["example.com"])
    monkeypatch.setattr("autotoken.runtime_config.get_register_domain", lambda: "example.com")
    monkeypatch.setattr("autotoken.identity.random_password", lambda: "generated-pass")
    monkeypatch.setattr("autotoken.setup_wizard.get_mail_provider", lambda value=None: value or "cloudmail")

    class FailingRoxyClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def list_workspaces(self):
            raise RuntimeError("HTTPConnectionPool(host='127.0.0.1', port=50000): Failed to establish a new connection")

    monkeypatch.setattr("autotoken.settings.config.get_roxybrowser_config", lambda: {"api_host": "http://127.0.0.1:50000", "api_token": "token"})
    monkeypatch.setattr("autotoken.roxybrowser_client.RoxyBrowserClient", FailingRoxyClient)

    routes = _routes(started)
    with pytest.raises(HTTPException) as exc_info:
        routes["post_add"](ManualRegisterParams(use_roxybrowser=True))

    assert exc_info.value.status_code == 400
    assert "RoxyBrowser 未连接" in str(exc_info.value.detail)
    assert started == []


def test_post_add_rejects_invalid_registration_flow(monkeypatch):
    monkeypatch.setattr("autotoken.runtime_config.get_register_domains", lambda: ["example.com"])
    monkeypatch.setattr("autotoken.runtime_config.get_register_domain", lambda: "example.com")
    monkeypatch.setattr("autotoken.identity.random_password", lambda: "generated-pass")
    monkeypatch.setattr("autotoken.setup_wizard.get_mail_provider", lambda value=None: value or "cloudmail")

    routes = _routes([])
    with pytest.raises(HTTPException) as exc_info:
        routes["post_add"](ManualRegisterParams(registration_flow="bad"))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "registration_flow 只支持 standard 或 phone_cpa"


def test_post_add_requires_sms_api_key_for_sms_oauth_provider(monkeypatch):
    monkeypatch.setattr("autotoken.runtime_config.get_register_domains", lambda: ["example.com"])
    monkeypatch.setattr("autotoken.runtime_config.get_register_domain", lambda: "example.com")
    monkeypatch.setattr("autotoken.identity.random_password", lambda: "generated-pass")
    monkeypatch.setattr("autotoken.setup_wizard.get_mail_provider", lambda value=None: value or "cloudmail")

    routes = _routes([], oauth_env={})
    with pytest.raises(HTTPException) as exc_info:
        routes["post_add"](ManualRegisterParams(post_register_oauth=True, oauth_phone_sms_provider="hero_sms"))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "启用 hero_sms 前需要先在设置页配置 API Key"


def test_post_add_allows_oasis_with_cdk_pool_without_api_key(monkeypatch):
    started = []
    monkeypatch.setattr("autotoken.runtime_config.get_register_domains", lambda: ["example.com"])
    monkeypatch.setattr("autotoken.runtime_config.get_register_domain", lambda: "example.com")
    monkeypatch.setattr("autotoken.identity.random_password", lambda: "generated-pass")
    monkeypatch.setattr("autotoken.setup_wizard.get_mail_provider", lambda value=None: value or "cloudmail")

    routes = _routes(started, oauth_env={"oasis_sms_cdks": "SMS-6L2A-6TAH-Q7BA"})
    result = routes["post_add"](
        ManualRegisterParams(
            post_register_oauth=True,
            oauth_phone_sms_provider="oasis",
            oauth_phone_sms_country="187",
            oauth_phone_sms_max_price="0.05",
        )
    )

    assert result["params"]["oauth_phone_sms_provider"] == "oasis"
    assert result["params"]["oauth_phone_sms_country"] == ""
    assert result["params"]["oauth_phone_sms_max_price"] == ""
    assert started[0]["kwargs"]["oauth_phone_sms_provider"] == "oasis"
    assert started[0]["kwargs"]["oauth_phone_sms_country"] is None
    assert started[0]["kwargs"]["oauth_phone_sms_max_price"] == ""
    assert started[0]["kwargs"]["oauth_oasis_sms_cdks"] is None


def test_post_add_allows_smscloud_oauth_provider(monkeypatch):
    started = []
    monkeypatch.setattr("autotoken.runtime_config.get_register_domains", lambda: ["example.com"])
    monkeypatch.setattr("autotoken.runtime_config.get_register_domain", lambda: "example.com")
    monkeypatch.setattr("autotoken.identity.random_password", lambda: "generated-pass")
    monkeypatch.setattr("autotoken.setup_wizard.get_mail_provider", lambda value=None: value or "cloudmail")

    routes = _routes(started, oauth_env={"smscloud_api_key": "cloud-key"})
    result = routes["post_add"](
        ManualRegisterParams(
            post_register_oauth=True,
            oauth_phone_sms_provider="smscloud",
            oauth_phone_sms_country="44",
            oauth_phone_sms_max_price="0.08",
        )
    )

    assert result["params"]["oauth_phone_sms_provider"] == "smscloud"
    assert result["params"]["oauth_phone_sms_country"] == "cloud:44"
    assert result["params"]["oauth_phone_sms_max_price"] == "0.08"
    assert started[0]["kwargs"]["oauth_phone_sms_provider"] == "smscloud"
    assert started[0]["kwargs"]["oauth_phone_sms_country"] == "cloud:44"
    assert started[0]["kwargs"]["oauth_phone_sms_max_price"] == "0.08"


def test_post_add_allows_oasis_with_inline_task_cdks(monkeypatch):
    started = []
    monkeypatch.setattr("autotoken.runtime_config.get_register_domains", lambda: ["example.com"])
    monkeypatch.setattr("autotoken.runtime_config.get_register_domain", lambda: "example.com")
    monkeypatch.setattr("autotoken.identity.random_password", lambda: "generated-pass")
    monkeypatch.setattr("autotoken.setup_wizard.get_mail_provider", lambda value=None: value or "cloudmail")

    routes = _routes(started, oauth_env={})
    result = routes["post_add"](
        ManualRegisterParams(
            post_register_oauth=True,
            oauth_phone_sms_provider="oasis",
            oauth_oasis_sms_cdks="SMS-6L2A-6TAH-Q7BA\nSMS-8EQ6-8E5G-KN2C",
        )
    )

    assert result["params"]["oauth_phone_sms_provider"] == "oasis"
    assert result["params"]["oauth_oasis_sms_cdk_count"] == 2
    assert started[0]["kwargs"]["oauth_oasis_sms_cdks"] == "SMS-6L2A-6TAH-Q7BA\nSMS-8EQ6-8E5G-KN2C"


def test_post_add_requires_oasis_cdk_pool(monkeypatch):
    monkeypatch.setattr("autotoken.runtime_config.get_register_domains", lambda: ["example.com"])
    monkeypatch.setattr("autotoken.runtime_config.get_register_domain", lambda: "example.com")
    monkeypatch.setattr("autotoken.identity.random_password", lambda: "generated-pass")
    monkeypatch.setattr("autotoken.setup_wizard.get_mail_provider", lambda value=None: value or "cloudmail")

    routes = _routes([], oauth_env={})
    with pytest.raises(HTTPException) as exc_info:
        routes["post_add"](ManualRegisterParams(post_register_oauth=True, oauth_phone_sms_provider="oasis"))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "启用 Oasis 前需要先在设置页配置 CDK 池"


def test_post_add_mailcom_does_not_require_register_domain(monkeypatch):
    started = []
    calls = []
    monkeypatch.setattr("autotoken.runtime_config.get_register_domains", lambda: [])
    monkeypatch.setattr("autotoken.runtime_config.get_register_domain", lambda: "")
    monkeypatch.setattr("autotoken.identity.random_password", lambda: "generated-pass")
    monkeypatch.setattr("autotoken.setup_wizard.get_mail_provider", lambda value=None: value or "mail.com")
    monkeypatch.setattr("autotoken.manager.cmd_register_accounts", lambda **kwargs: calls.append(kwargs) or {"created": 1})

    routes = _routes(started)
    result = routes["post_add"](ManualRegisterParams(mail_provider="mail.com", domain="", domains=[]))

    assert result["command"] == "register"
    assert started[0]["params"]["domain"] == ""
    assert started[0]["params"]["domains"] == []
    assert started[0]["kwargs"]["mail_provider"] == "mail.com"
    assert started[0]["func"]("task-register") == {"created": 1}
    assert calls[0]["mail_provider"] == "mail.com"


def test_post_add_enable_totp_mfa_flag_passes_to_register_command(monkeypatch):
    started = []
    calls = []
    monkeypatch.setattr("autotoken.runtime_config.get_register_domains", lambda: ["example.com"])
    monkeypatch.setattr("autotoken.runtime_config.get_register_domain", lambda: "example.com")
    monkeypatch.setattr("autotoken.identity.random_password", lambda: "generated-pass")
    monkeypatch.setattr("autotoken.setup_wizard.get_mail_provider", lambda value=None: value or "cloudmail")
    monkeypatch.setattr("autotoken.manager.cmd_register_accounts", lambda **kwargs: calls.append(kwargs) or {"created": 1})

    routes = _routes(started)
    result = routes["post_add"](ManualRegisterParams(enable2fa=True))

    assert result["params"]["enable_totp_mfa"] is True
    assert started[0]["kwargs"]["enable_totp_mfa"] is True
    assert started[0]["func"]("task-register") == {"created": 1}
    assert calls[0]["enable_totp_mfa"] is True


def test_post_add_passes_use_roxybrowser_and_enable_totp_to_register_worker(monkeypatch):
    started = []
    calls = []
    monkeypatch.setattr("autotoken.runtime_config.get_register_domains", lambda: ["example.com"])
    monkeypatch.setattr("autotoken.runtime_config.get_register_domain", lambda: "example.com")
    monkeypatch.setattr("autotoken.identity.random_password", lambda: "generated-pass")
    monkeypatch.setattr("autotoken.setup_wizard.get_mail_provider", lambda value=None: value or "cloudmail")
    monkeypatch.setattr("autotoken.manager.cmd_register_accounts", lambda **kwargs: calls.append(kwargs) or {"created": 1})

    class AvailableRoxyClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def list_workspaces(self):
            return [{"id": "workspace-1", "name": "Default"}]

    monkeypatch.setattr("autotoken.settings.config.get_roxybrowser_config", lambda: {"api_host": "http://127.0.0.1:50000", "api_token": "token"})
    monkeypatch.setattr("autotoken.roxybrowser_client.RoxyBrowserClient", AvailableRoxyClient)

    routes = _routes(started)
    result = routes["post_add"](ManualRegisterParams(useRoxyBrowser=True, enable2FA=True))

    assert result["params"]["register_mode"] == "browser"
    assert result["params"]["use_roxybrowser"] is True
    assert result["params"]["enable_totp_mfa"] is True
    assert started[0]["kwargs"]["use_roxybrowser"] is True
    assert started[0]["kwargs"]["enable_totp_mfa"] is True
    assert started[0]["func"]("task-register") == {"created": 1}
    assert calls[0]["use_roxybrowser"] is True
    assert calls[0]["enable_totp_mfa"] is True
