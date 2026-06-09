from fastapi import FastAPI, HTTPException

from autotoken.api_routes.register_domain import (
    REGISTER_DOMAINS_MAX_ITEMS,
    RegisterDomainParams,
    RegisterDomainsParams,
    create_register_domain_router,
)


def _app():
    app = FastAPI()
    app.include_router(create_register_domain_router())
    return app


def _endpoint(app, path, method):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"missing route {method} {path}")


def test_get_register_domain_route_returns_runtime_and_env_defaults(monkeypatch):
    app = _app()

    monkeypatch.setattr("autotoken.runtime_config.get", lambda key, default=None: "mail-a.com" if key == "register_domain" else default)
    monkeypatch.setattr("autotoken.runtime_config.get_register_domain", lambda: "mail-a.com")
    monkeypatch.setattr("autotoken.runtime_config.get_register_domains", lambda: ["mail-a.com", "mail-b.com"])
    monkeypatch.setattr("autotoken.config.CLOUD_MAIL_DOMAIN", "@env-mail.com")
    monkeypatch.setattr("autotoken.config.CLOUDFLARE_TEMP_EMAIL_DOMAIN", "")

    result = _endpoint(app, "/api/config/register-domain", "GET")()

    assert result == {
        "domain": "mail-a.com",
        "domains": ["mail-a.com", "mail-b.com"],
        "override": "mail-a.com",
        "env_default": "env-mail.com",
    }


def test_put_register_domain_can_skip_mail_provider_probe(monkeypatch):
    app = _app()
    saved = []

    monkeypatch.setattr("autotoken.runtime_config.set_register_domain", lambda domain: saved.append(domain) or domain)

    result = _endpoint(app, "/api/config/register-domain", "PUT")(
        RegisterDomainParams(domain="@mail-a.com", verify=False)
    )

    assert result == {"message": "注册域名已切换为 @mail-a.com", "domain": "mail-a.com"}
    assert saved == ["mail-a.com"]


def test_put_register_domain_reports_probe_cleanup_warning(monkeypatch):
    app = _app()
    saved = []

    class FakeMailClient:
        def login(self):
            return None

        def create_temp_email(self, prefix, domain):
            return "acct-1", f"{prefix}@{domain}"

        def delete_account(self, acct_id):
            raise RuntimeError(f"delete failed {acct_id}")

    monkeypatch.setattr("autotoken.mail.TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr("autotoken.runtime_config.set_register_domain", lambda domain: saved.append(domain) or domain)

    result = _endpoint(app, "/api/config/register-domain", "PUT")(RegisterDomainParams(domain="mail-a.com"))

    assert result["domain"] == "mail-a.com"
    assert result["leaked_probe"]["acct_id"] == "acct-1"
    assert "回收失败" in result["warning"]
    assert saved == ["mail-a.com"]


def test_put_register_domain_rejects_empty_or_invalid_probe(monkeypatch):
    app = _app()

    try:
        _endpoint(app, "/api/config/register-domain", "PUT")(RegisterDomainParams(domain=" "))
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail == "域名不能为空"
    else:
        raise AssertionError("empty register domain must fail")

    class FakeMailClient:
        def login(self):
            return None

        def create_temp_email(self, prefix, domain):
            raise RuntimeError(f"invalid {domain}")

    monkeypatch.setattr("autotoken.mail.TemporaryEmailClient", FakeMailClient)
    try:
        _endpoint(app, "/api/config/register-domain", "PUT")(RegisterDomainParams(domain="bad.test"))
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail == "域名验证失败: invalid bad.test"
    else:
        raise AssertionError("invalid probed register domain must fail")


def test_put_register_domains_deduplicates_and_selects_active_domain(monkeypatch):
    app = _app()
    saved_domains = []
    active_domains = []

    monkeypatch.setattr("autotoken.runtime_config.set_register_domains", lambda domains: saved_domains.append(domains) or domains)
    monkeypatch.setattr("autotoken.runtime_config.set_register_domain", lambda domain: active_domains.append(domain) or domain)

    result = _endpoint(app, "/api/config/register-domains", "PUT")(
        RegisterDomainsParams(domains=[" @mail-a.com ", "mail-b.com", "mail-a.com"], selected="mail-b.com")
    )

    assert result == {
        "message": "已保存 2 个注册域名",
        "domains": ["mail-a.com", "mail-b.com"],
        "selected": "mail-b.com",
    }
    assert saved_domains == [["mail-a.com", "mail-b.com"]]
    assert active_domains == ["mail-b.com"]


def test_put_register_domains_rejects_empty_or_unknown_selected_domain():
    app = _app()

    try:
        _endpoint(app, "/api/config/register-domains", "PUT")(RegisterDomainsParams(domains=["", " "]))
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail == "domains 不能为空"
    else:
        raise AssertionError("empty register domain list must fail")

    try:
        _endpoint(app, "/api/config/register-domains", "PUT")(
            RegisterDomainsParams(domains=["mail-a.com"], selected="mail-b.com")
        )
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail == "selected 必须在 domains 列表中"
    else:
        raise AssertionError("unknown selected register domain must fail")


def test_put_register_domains_rejects_too_many_raw_domains():
    app = _app()

    try:
        _endpoint(app, "/api/config/register-domains", "PUT")(
            RegisterDomainsParams(domains=[f"mail-{index}.example.com" for index in range(REGISTER_DOMAINS_MAX_ITEMS + 1)])
        )
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "注册域名条目过多" in exc.detail
    else:
        raise AssertionError("oversized register domain list must fail")
