import logging

from fastapi import FastAPI, HTTPException

from autotoken.api_routes.bind_link import BindLinkOpenParams, BindLinkParams, create_bind_link_router


def _app(*, normalize_access_token=None, generate_checkout_link=None, generate_plus_trial_checkout_link=None):
    app = FastAPI()
    app.include_router(
        create_bind_link_router(
            normalize_access_token=normalize_access_token or (lambda value: str(value or "").strip()),
            generate_checkout_link=generate_checkout_link or (lambda _token, _payload: {"url": "https://pay.example"}),
            generate_plus_trial_checkout_link=generate_plus_trial_checkout_link,
            get_account_access_token=lambda email: f"token-for-{email}",
            open_checkout_url=lambda email, url, **kwargs: {"email": email, "url": url, "opened": True, **kwargs},
            logger=logging.getLogger("test.bind_link"),
        )
    )
    return app


def _endpoint(app, path, method):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"missing route {method} {path}")


def _params(**kwargs):
    payload = {
        "access_token": " Bearer token-1 ",
        "plan_name": "chatgptplusplan",
        "billing_details": {"country": "US", "currency": "USD"},
        "checkout_ui_mode": "hosted",
    }
    payload.update(kwargs)
    return BindLinkParams(**payload)


def test_bind_link_route_normalizes_token_and_builds_checkout_payload():
    captured = {}

    def fake_generate_checkout_link(token, payload):
        captured["token"] = token
        captured["payload"] = payload
        return {"url": "https://pay.openai.com/c/pay/cs_demo"}

    app = _app(
        normalize_access_token=lambda value: str(value).replace("Bearer ", "").strip(),
        generate_checkout_link=fake_generate_checkout_link,
    )

    result = _endpoint(app, "/api/bind/link", "POST")(
        _params(
            promo_campaign={"promo_campaign_id": "plus"},
            team_plan_data={"workspace_name": "Team"},
            entry_point="settings",
            promo_code="PROMO",
            cancel_url="https://example.test/cancel",
        )
    )

    assert result == {"url": "https://pay.openai.com/c/pay/cs_demo"}
    assert captured["token"] == "token-1"
    assert captured["payload"] == {
        "plan_name": "chatgptplusplan",
        "billing_details": {"country": "US", "currency": "USD"},
        "checkout_ui_mode": "hosted",
        "entry_point": "settings",
        "promo_campaign": {"promo_campaign_id": "plus"},
        "promo_code": "PROMO",
        "cancel_url": "https://example.test/cancel",
        "team_plan_data": {"workspace_name": "Team"},
    }


def test_bind_link_route_uses_plus_trial_extractor_for_trial_flow():
    captured = {}

    def regular_generator(_token, _payload):
        raise AssertionError("Plus 试用不应走普通 checkout 生成器")

    def trial_generator(token, payload):
        captured["token"] = token
        captured["payload"] = payload
        return {
            "url": "https://chatgpt.com/checkout/openai_llc/oaics_trial",
            "checkout_session_id": "oaics_trial",
            "processor_entity": "openai_llc",
            "amount_verification": "verified_zero",
        }

    app = _app(
        normalize_access_token=lambda value: str(value).replace("Bearer ", "").strip(),
        generate_checkout_link=regular_generator,
        generate_plus_trial_checkout_link=trial_generator,
    )

    result = _endpoint(app, "/api/bind/link", "POST")(
        _params(
            checkout_flow="plus_trial",
            plan_name="chatgptplusplan",
            billing_details={"country": "PH", "currency": "PHP"},
        )
    )

    assert result["url"] == "https://chatgpt.com/checkout/openai_llc/oaics_trial"
    assert result["amount_verification"] == "verified_zero"
    assert captured["token"] == "token-1"
    assert captured["payload"] == {
        "plan_name": "chatgptplusplan",
        "billing_details": {"country": "PH", "currency": "PHP"},
        "checkout_ui_mode": "hosted",
        "checkout_flow": "plus_trial",
    }


def test_bind_link_route_prefers_chatgpt_checkout_url_over_hosted_url():
    def fake_generate_checkout_link(_token, _payload, **_kwargs):
        return {
            "url": "https://pay.openai.com/c/pay/cs_live_demo#fid=test",
            "checkout_session_id": "cs_live_demo",
            "processor_entity": "openai_llc",
            "hosted_checkout_url": "https://pay.openai.com/c/pay/cs_live_demo#fid=test",
        }

    app = _app(generate_checkout_link=fake_generate_checkout_link)

    result = _endpoint(app, "/api/bind/link", "POST")(_params())

    assert result["url"] == "https://chatgpt.com/checkout/openai_llc/cs_live_demo"
    assert result["chatgpt_checkout_url"] == "https://chatgpt.com/checkout/openai_llc/cs_live_demo"
    assert result["hosted_checkout_url"] == "https://pay.openai.com/c/pay/cs_live_demo#fid=test"


def test_bind_link_route_uses_selected_proxy_for_checkout_generation():
    captured = {}

    def fake_generate_checkout_link(_token, _payload, **kwargs):
        captured["generate"] = kwargs
        return {"url": "https://pay.example"}

    app = FastAPI()

    def fake_select_proxy(**kwargs):
        captured["select_proxy"] = kwargs
        return "http://711-proxy.example:8080"

    app.include_router(
        create_bind_link_router(
            normalize_access_token=lambda value: str(value or "").strip(),
            generate_checkout_link=fake_generate_checkout_link,
            select_open_proxy_url=fake_select_proxy,
            logger=logging.getLogger("test.bind_link"),
        )
    )

    result = _endpoint(app, "/api/bind/link", "POST")(
        _params(
            proxy_api_enabled=True,
            proxy_api_provider="711proxy",
            proxy_api_country="JP",
            proxy_api_url="http://global.rotgbapi.711proxy.com:8089/gen?region=US",
        )
    )

    assert result["url"] == "https://pay.example"
    assert captured["select_proxy"] == {
        "provider": "711proxy",
        "country": "JP",
        "api_url": "http://global.rotgbapi.711proxy.com:8089/gen?region=US",
    }
    assert captured["generate"] == {"proxy_url": "http://711-proxy.example:8080"}


def test_bind_link_route_falls_back_to_direct_when_proxy_api_returns_empty():
    captured = {}

    def fake_generate_checkout_link(_token, _payload, **kwargs):
        captured["generate"] = kwargs
        return {"url": "https://pay.example"}

    app = FastAPI()
    app.include_router(
        create_bind_link_router(
            normalize_access_token=lambda value: str(value or "").strip(),
            generate_checkout_link=fake_generate_checkout_link,
            select_open_proxy_url=lambda **_kwargs: "",
            logger=logging.getLogger("test.bind_link"),
        )
    )

    result = _endpoint(app, "/api/bind/link", "POST")(
        _params(
            proxy_api_enabled=True,
            proxy_api_provider="cliproxy",
            proxy_api_country="US",
        )
    )

    assert result["url"] == "https://pay.example"
    assert captured["generate"] == {}


def test_bind_link_route_does_not_use_proxy_api_by_default():
    captured = {"select_called": False}

    def fake_generate_checkout_link(_token, _payload, **kwargs):
        captured["generate"] = kwargs
        return {"url": "https://pay.example"}

    def fail_if_selected(**_kwargs):
        captured["select_called"] = True
        raise AssertionError("proxy API should be opt-in on bind link generation")

    app = FastAPI()
    app.include_router(
        create_bind_link_router(
            normalize_access_token=lambda value: str(value or "").strip(),
            generate_checkout_link=fake_generate_checkout_link,
            select_open_proxy_url=fail_if_selected,
            logger=logging.getLogger("test.bind_link"),
        )
    )

    result = _endpoint(app, "/api/bind/link", "POST")(_params())

    assert result["url"] == "https://pay.example"
    assert captured["select_called"] is False
    assert captured["generate"] == {}


def test_bind_link_route_falls_back_to_direct_when_proxy_api_selector_fails():
    captured = {}

    def fake_generate_checkout_link(_token, _payload, **kwargs):
        captured["generate"] = kwargs
        return {"url": "https://pay.example"}

    def failing_select_proxy(**_kwargs):
        raise RuntimeError("Cliproxy US 代理 API 未返回可用代理")

    app = FastAPI()
    app.include_router(
        create_bind_link_router(
            normalize_access_token=lambda value: str(value or "").strip(),
            generate_checkout_link=fake_generate_checkout_link,
            select_open_proxy_url=failing_select_proxy,
            logger=logging.getLogger("test.bind_link"),
        )
    )

    result = _endpoint(app, "/api/bind/link", "POST")(
        _params(
            proxy_api_enabled=True,
            proxy_api_provider="cliproxy",
            proxy_api_country="US",
        )
    )

    assert result["url"] == "https://pay.example"
    assert captured["generate"] == {}


def test_bind_link_route_does_not_use_page_proxy_api_for_plus_trial_extraction():
    captured = {"selected": []}

    def regular_generator(_token, _payload, **_kwargs):
        raise AssertionError("Plus 试用不应走普通 checkout 生成器")

    def fake_select_proxy(**kwargs):
        captured["selected"].append(kwargs)
        return f"http://{kwargs['country'].lower()}.711proxy.example:8080"

    def trial_generator(_token, payload):
        captured["payload"] = payload
        return {
            "url": "https://chatgpt.com/checkout/openai_llc/oaics_trial",
            "checkout_session_id": "oaics_trial",
            "processor_entity": "openai_llc",
        }

    app = FastAPI()
    app.include_router(
        create_bind_link_router(
            normalize_access_token=lambda value: str(value or "").strip(),
            generate_checkout_link=regular_generator,
            generate_plus_trial_checkout_link=trial_generator,
            select_open_proxy_url=fake_select_proxy,
            logger=logging.getLogger("test.bind_link"),
        )
    )

    result = _endpoint(app, "/api/bind/link", "POST")(
        _params(
            checkout_flow="plus_trial",
            proxy_api_enabled=True,
            proxy_api_provider="711proxy",
            proxy_api_country="JP",
            proxy_api_url="http://global.rotgbapi.711proxy.com:8089/gen?region=JP",
        )
    )

    assert result["url"] == "https://chatgpt.com/checkout/openai_llc/oaics_trial"
    assert captured["selected"] == []
    assert "checkout_proxy" not in captured["payload"]
    assert "update_proxy" not in captured["payload"]


def test_bind_link_route_does_not_retry_plus_trial_with_page_proxy_api_after_extractor_proxy_error():
    captured = {"selected": [], "payloads": []}

    def regular_generator(_token, _payload, **_kwargs):
        raise AssertionError("Plus 试用不应走普通 checkout 生成器")

    def fake_select_proxy(**kwargs):
        captured["selected"].append(kwargs)
        country = str(kwargs["country"]).lower()
        attempt = 1 + (len([item for item in captured["selected"] if item["country"] == kwargs["country"]]) - 1)
        return f"http://{country}-{attempt}.711proxy.example:8080"

    def trial_generator(_token, payload):
        captured["payloads"].append(payload)
        if len(captured["payloads"]) == 1:
            raise RuntimeError("Failed to perform, curl: (56) Proxy CONNECT aborted")
        return {
            "url": "https://chatgpt.com/checkout/openai_llc/oaics_trial",
            "checkout_session_id": "oaics_trial",
            "processor_entity": "openai_llc",
        }

    app = FastAPI()
    app.include_router(
        create_bind_link_router(
            normalize_access_token=lambda value: str(value or "").strip(),
            generate_checkout_link=regular_generator,
            generate_plus_trial_checkout_link=trial_generator,
            select_open_proxy_url=fake_select_proxy,
            logger=logging.getLogger("test.bind_link"),
        )
    )

    try:
        _endpoint(app, "/api/bind/link", "POST")(
            _params(
                checkout_flow="plus_trial",
                proxy_api_enabled=True,
                proxy_api_provider="711proxy",
                proxy_api_country="JP",
            )
        )
    except HTTPException as exc:
        assert exc.status_code == 500
        assert "Proxy CONNECT aborted" in str(exc.detail)
    else:
        raise AssertionError("extractor proxy error must be reported without page-proxy retry")

    assert captured["selected"] == []
    assert len(captured["payloads"]) == 1
    assert "checkout_proxy" not in captured["payloads"][0]
    assert "update_proxy" not in captured["payloads"][0]


def test_bind_link_open_route_generates_and_opens_with_account_auth_session():
    captured = {}

    def fake_generate_checkout_link(token, payload):
        captured["token"] = token
        captured["payload"] = payload
        return {
            "checkout_session_id": "oaics_demo",
            "processor_entity": "openai_llc",
            "url": "",
        }

    def fake_open_checkout_url(email, url, **_kwargs):
        captured["open"] = {"email": email, "url": url}
        return {"opened": True, "current_url": url}

    app = FastAPI()
    app.include_router(
        create_bind_link_router(
            normalize_access_token=lambda value: str(value or "").strip(),
            generate_checkout_link=fake_generate_checkout_link,
            get_account_access_token=lambda email: f"token-for-{email}",
            open_checkout_url=fake_open_checkout_url,
            logger=logging.getLogger("test.bind_link"),
        )
    )

    result = _endpoint(app, "/api/bind/link/open", "POST")(
        BindLinkOpenParams(
            email=" User@Example.com ",
            plan_name="chatgptpro",
            billing_details={"country": "PH", "currency": "PHP"},
            checkout_ui_mode="hosted",
            entry_point="all_plans_pricing_modal",
        )
    )

    assert captured["token"] == "token-for-user@example.com"
    assert captured["payload"] == {
        "plan_name": "chatgptpro",
        "billing_details": {"country": "PH", "currency": "PHP"},
        "checkout_ui_mode": "hosted",
        "entry_point": "all_plans_pricing_modal",
    }
    assert captured["open"] == {
        "email": "user@example.com",
        "url": "https://chatgpt.com/checkout/openai_llc/oaics_demo",
    }
    assert result["opened"] is True
    assert result["url"] == "https://chatgpt.com/checkout/openai_llc/oaics_demo"


def test_bind_link_open_route_uses_roxybrowser_open_mode():
    captured = {}

    def fake_generate_checkout_link(_token, _payload, **kwargs):
        captured["generate"] = kwargs
        return {
            "checkout_session_id": "oaics_demo",
            "processor_entity": "openai_llc",
            "url": "",
        }

    def fake_open_checkout_url(email, url, *, open_mode=""):
        captured["open"] = {"email": email, "url": url, "open_mode": open_mode}
        return {"opened": True, "current_url": url, "open_mode": open_mode}

    app = FastAPI()
    app.include_router(
        create_bind_link_router(
            normalize_access_token=lambda value: str(value or "").strip(),
            generate_checkout_link=fake_generate_checkout_link,
            get_account_access_token=lambda email: f"token-for-{email}",
            open_checkout_url=fake_open_checkout_url,
            logger=logging.getLogger("test.bind_link"),
        )
    )

    result = _endpoint(app, "/api/bind/link/open", "POST")(
        BindLinkOpenParams(
            email="user@example.com",
            plan_name="chatgptplusplan",
            billing_details={"country": "PH", "currency": "PHP"},
            checkout_ui_mode="hosted",
            proxy_api_enabled=True,
        )
    )

    assert captured["open"] == {
        "email": "user@example.com",
        "url": "https://chatgpt.com/checkout/openai_llc/oaics_demo",
        "open_mode": "roxybrowser",
    }
    assert result["open_mode"] == "roxybrowser"


def test_bind_link_open_route_passes_selected_proxy_to_roxybrowser():
    captured = {}

    def fake_generate_checkout_link(_token, _payload, **kwargs):
        captured["generate"] = kwargs
        return {
            "checkout_session_id": "oaics_demo",
            "processor_entity": "openai_llc",
            "url": "",
        }

    def fake_open_checkout_url(email, url, *, open_mode="", proxy_url=None):
        captured["open"] = {
            "email": email,
            "url": url,
            "open_mode": open_mode,
            "proxy_url": proxy_url,
        }
        return {
            "opened": True,
            "current_url": url,
            "open_mode": open_mode,
            "open_proxy_url_present": bool(proxy_url),
        }

    app = FastAPI()
    app.include_router(
        create_bind_link_router(
            normalize_access_token=lambda value: str(value or "").strip(),
            generate_checkout_link=fake_generate_checkout_link,
            get_account_access_token=lambda email: f"token-for-{email}",
            open_checkout_url=fake_open_checkout_url,
            select_open_proxy_url=lambda **_kwargs: "socks5h://us-proxy.example:3010",
            logger=logging.getLogger("test.bind_link"),
        )
    )

    result = _endpoint(app, "/api/bind/link/open", "POST")(
        BindLinkOpenParams(
            email="user@example.com",
            plan_name="chatgptplusplan",
            billing_details={"country": "PH", "currency": "PHP"},
            checkout_ui_mode="hosted",
            proxy_api_enabled=True,
        )
    )

    assert captured["open"] == {
        "email": "user@example.com",
        "url": "https://chatgpt.com/checkout/openai_llc/oaics_demo",
        "open_mode": "roxybrowser",
        "proxy_url": "socks5h://us-proxy.example:3010",
    }
    assert result["open_proxy_url_present"] is True


def test_bind_link_open_route_selects_proxy_from_request_settings():
    captured = {}

    def fake_generate_checkout_link(_token, _payload, **kwargs):
        captured["generate"] = kwargs
        return {
            "checkout_session_id": "oaics_demo",
            "processor_entity": "openai_llc",
            "url": "",
        }

    def fake_select_open_proxy_url(**kwargs):
        captured["select_proxy"] = kwargs
        return "http://711-proxy.example:8080"

    def fake_open_checkout_url(_email, _url, **kwargs):
        captured["open"] = kwargs
        return {"opened": True, **kwargs}

    app = FastAPI()
    app.include_router(
        create_bind_link_router(
            normalize_access_token=lambda value: str(value or "").strip(),
            generate_checkout_link=fake_generate_checkout_link,
            get_account_access_token=lambda email: f"token-for-{email}",
            open_checkout_url=fake_open_checkout_url,
            select_open_proxy_url=fake_select_open_proxy_url,
            logger=logging.getLogger("test.bind_link"),
        )
    )

    result = _endpoint(app, "/api/bind/link/open", "POST")(
        BindLinkOpenParams(
            email="user@example.com",
            plan_name="chatgptplusplan",
            billing_details={"country": "PH", "currency": "PHP"},
            checkout_ui_mode="hosted",
            proxy_api_enabled=True,
            proxy_api_provider="711proxy",
            proxy_api_country="JP",
            proxy_api_url="http://global.rotgbapi.711proxy.com:8089/gen?region=US",
        )
    )

    assert captured["select_proxy"] == {
        "provider": "711proxy",
        "country": "JP",
        "api_url": "http://global.rotgbapi.711proxy.com:8089/gen?region=US",
    }
    assert captured["generate"]["proxy_url"] == "http://711-proxy.example:8080"
    assert captured["open"]["proxy_url"] == "http://711-proxy.example:8080"
    assert result["proxy_url"] == "http://711-proxy.example:8080"


def test_bind_link_open_route_uses_page_proxy_only_for_opening_plus_trial():
    captured = {"selected": []}

    def trial_generator(_token, payload):
        captured["payload"] = payload
        return {
            "url": "https://chatgpt.com/checkout/openai_llc/oaics_trial",
            "checkout_session_id": "oaics_trial",
            "processor_entity": "openai_llc",
        }

    def fake_select_proxy(**kwargs):
        captured["selected"].append(kwargs)
        return f"http://{kwargs['country'].lower()}.711proxy.example:8080"

    def fake_open_checkout_url(_email, _url, **kwargs):
        captured["open"] = kwargs
        return {"opened": True, **kwargs}

    app = FastAPI()
    app.include_router(
        create_bind_link_router(
            normalize_access_token=lambda value: str(value or "").strip(),
            generate_checkout_link=lambda *_args, **_kwargs: {"url": "https://pay.example"},
            generate_plus_trial_checkout_link=trial_generator,
            get_account_access_token=lambda email: f"token-for-{email}",
            open_checkout_url=fake_open_checkout_url,
            select_open_proxy_url=fake_select_proxy,
            logger=logging.getLogger("test.bind_link"),
        )
    )

    result = _endpoint(app, "/api/bind/link/open", "POST")(
        BindLinkOpenParams(
            email="user@example.com",
            plan_name="chatgptplusplan",
            checkout_flow="plus_trial",
            billing_details={"country": "PH", "currency": "PHP"},
            checkout_ui_mode="hosted",
            proxy_api_enabled=True,
            proxy_api_provider="711proxy",
            proxy_api_country="JP",
        )
    )

    assert result["opened"] is True
    assert "checkout_proxy" not in captured["payload"]
    assert "update_proxy" not in captured["payload"]
    assert captured["open"]["proxy_url"] == "http://jp.711proxy.example:8080"
    assert [item["country"] for item in captured["selected"]] == ["JP"]


def test_bind_link_open_route_retries_until_open_proxy_preflight_passes():
    captured = {"selected": [], "preflighted": []}
    proxies = iter(["http://bad.711proxy.example:8080", "http://good.711proxy.example:8080"])

    def trial_generator(_token, payload):
        captured["payload"] = payload
        return {
            "url": "https://chatgpt.com/checkout/openai_llc/oaics_trial",
            "checkout_session_id": "oaics_trial",
            "processor_entity": "openai_llc",
        }

    def fake_select_proxy(**kwargs):
        captured["selected"].append(kwargs)
        return next(proxies)

    def fake_preflight(proxy_url):
        captured["preflighted"].append(proxy_url)
        return (proxy_url.startswith("http://good."), "ok" if proxy_url.startswith("http://good.") else "tunnel failed")

    def fake_open_checkout_url(_email, _url, **kwargs):
        captured["open"] = kwargs
        return {"opened": True, **kwargs}

    app = FastAPI()
    app.include_router(
        create_bind_link_router(
            normalize_access_token=lambda value: str(value or "").strip(),
            generate_checkout_link=lambda *_args, **_kwargs: {"url": "https://pay.example"},
            generate_plus_trial_checkout_link=trial_generator,
            get_account_access_token=lambda email: f"token-for-{email}",
            open_checkout_url=fake_open_checkout_url,
            select_open_proxy_url=fake_select_proxy,
            preflight_open_proxy_url=fake_preflight,
            logger=logging.getLogger("test.bind_link"),
        )
    )

    result = _endpoint(app, "/api/bind/link/open", "POST")(
        BindLinkOpenParams(
            email="user@example.com",
            plan_name="chatgptplusplan",
            checkout_flow="plus_trial",
            billing_details={"country": "PH", "currency": "PHP"},
            checkout_ui_mode="hosted",
            proxy_api_enabled=True,
            proxy_api_provider="711proxy",
            proxy_api_country="US",
        )
    )

    assert captured["preflighted"] == ["http://bad.711proxy.example:8080", "http://good.711proxy.example:8080"]
    assert len(captured["selected"]) == 2
    assert captured["open"]["proxy_url"] == "http://good.711proxy.example:8080"
    assert result["proxy_url"] == "http://good.711proxy.example:8080"


def test_bind_link_open_route_requires_open_proxy_when_proxy_api_enabled():
    captured = {}

    def trial_generator(_token, payload):
        captured["payload"] = payload
        return {
            "url": "https://chatgpt.com/checkout/openai_llc/oaics_trial",
            "checkout_session_id": "oaics_trial",
            "processor_entity": "openai_llc",
        }

    def fake_open_checkout_url(*_args, **_kwargs):
        raise AssertionError("proxy API enabled but empty proxy must not open directly")

    app = FastAPI()
    app.include_router(
        create_bind_link_router(
            normalize_access_token=lambda value: str(value or "").strip(),
            generate_checkout_link=lambda *_args, **_kwargs: {"url": "https://pay.example"},
            generate_plus_trial_checkout_link=trial_generator,
            get_account_access_token=lambda email: f"token-for-{email}",
            open_checkout_url=fake_open_checkout_url,
            select_open_proxy_url=lambda **_kwargs: "",
            logger=logging.getLogger("test.bind_link"),
        )
    )

    try:
        _endpoint(app, "/api/bind/link/open", "POST")(
            BindLinkOpenParams(
                email="user@example.com",
                plan_name="chatgptplusplan",
                checkout_flow="plus_trial",
                billing_details={"country": "PH", "currency": "PHP"},
                checkout_ui_mode="hosted",
                proxy_api_enabled=True,
                proxy_api_provider="711proxy",
                proxy_api_country="JP",
            )
        )
    except HTTPException as exc:
        assert exc.status_code == 502
        assert exc.detail == "打开浏览器代理 API 未返回可用代理"
    else:
        raise AssertionError("empty open proxy must fail when proxy API is enabled")

    assert "checkout_proxy" not in captured["payload"]
    assert "update_proxy" not in captured["payload"]


def test_bind_link_route_rejects_empty_token():
    app = _app(normalize_access_token=lambda _value: "")

    try:
        _endpoint(app, "/api/bind/link", "POST")(_params(access_token=""))
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail == "请提供 access_token"
    else:
        raise AssertionError("empty access token must fail")


def test_bind_link_route_preserves_http_exception_from_generator():
    def fake_generate_checkout_link(_token, _payload):
        raise HTTPException(status_code=403, detail="forbidden")

    app = _app(generate_checkout_link=fake_generate_checkout_link)

    try:
        _endpoint(app, "/api/bind/link", "POST")(_params())
    except HTTPException as exc:
        assert exc.status_code == 403
        assert exc.detail == "forbidden"
    else:
        raise AssertionError("generator HTTPException must propagate")


def test_bind_link_route_maps_unexpected_generator_errors_to_500():
    def fake_generate_checkout_link(_token, _payload):
        raise RuntimeError("boom")

    app = _app(generate_checkout_link=fake_generate_checkout_link)

    try:
        _endpoint(app, "/api/bind/link", "POST")(_params())
    except HTTPException as exc:
        assert exc.status_code == 500
        assert exc.detail == "生成绑卡链接失败: boom"
    else:
        raise AssertionError("unexpected generator error must fail")
