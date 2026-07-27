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
            open_checkout_url=lambda email, url: {"email": email, "url": url, "opened": True},
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
    def fake_generate_checkout_link(_token, _payload):
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

    def fake_open_checkout_url(email, url):
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
