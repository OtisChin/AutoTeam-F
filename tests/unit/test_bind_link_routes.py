import logging

from fastapi import FastAPI, HTTPException

from autotoken.api_routes.bind_link import BindLinkParams, create_bind_link_router


def _app(*, normalize_access_token=None, generate_checkout_link=None):
    app = FastAPI()
    app.include_router(
        create_bind_link_router(
            normalize_access_token=normalize_access_token or (lambda value: str(value or "").strip()),
            generate_checkout_link=generate_checkout_link or (lambda _token, _payload: {"url": "https://pay.example"}),
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
