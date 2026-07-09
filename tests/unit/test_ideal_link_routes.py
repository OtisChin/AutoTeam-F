from __future__ import annotations

import io

from fastapi import FastAPI

from autotoken.api_routes.ideal_link import IdealLongLinkRequest, IdealQrRequest, create_ideal_link_router


def _app():
    app = FastAPI()
    app.include_router(create_ideal_link_router())
    return app


def _endpoint(app, path, method):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"missing route {method} {path}")


def test_start_ideal_long_link_job_returns_job_id(monkeypatch):
    app = _app()

    def fake_start(req):
        assert req.link_type == "ideal"
        assert req.billing_country == "NL"
        assert req.payment_locale == "en"
        assert req.checkout_proxy_region == ""
        assert req.provider_proxy_region == ""
        assert req.proxy_chain_strategy == ""
        return {"job_id": "ideal-job-1"}

    monkeypatch.setattr("autotoken.api_routes.ideal_link.legacy.start_long_link_job", fake_start)

    result = _endpoint(app, "/api/ideal/long-link/start", "POST")(
        IdealLongLinkRequest.model_validate(
            {
                "accessToken": "token",
                "proxy": "http://127.0.0.1:8080",
                "link_type": "hosted",
                "billing_country": "US",
                "payment_locale": "en",
            }
        )
    )

    assert result == {"job_id": "ideal-job-1"}


def test_start_ideal_long_link_job_preserves_source_default_proxy_chain(monkeypatch):
    app = _app()

    def fake_start(req):
        assert req.link_type == "ideal"
        assert req.billing_country == "NL"
        assert req.checkout_proxy_region == "JP"
        assert req.provider_proxy_region == "NL"
        assert req.proxy_chain_strategy == ""
        assert req.approve_proxy_region == ""
        return {"job_id": "ideal-job-2"}

    monkeypatch.setattr("autotoken.api_routes.ideal_link.legacy.start_long_link_job", fake_start)

    result = _endpoint(app, "/api/ideal/long-link/start", "POST")(
        IdealLongLinkRequest.model_validate(
            {
                "accessToken": "token",
                "proxy": "socks5h://user-region-JP-sid-test-t-60:pass@example.test:3010",
                "link_type": "ideal",
                "billing_country": "NL",
                "payment_locale": "auto",
                "checkout_ui_mode": "hosted",
                "checkout_proxy_region": "JP",
                "provider_proxy_region": "NL",
                "proxy_chain_strategy": "",
                "approve_proxy_region": "",
            }
        )
    )

    assert result == {"job_id": "ideal-job-2"}


def test_get_ideal_long_link_job_returns_snapshot(monkeypatch):
    app = _app()
    monkeypatch.setattr(
        "autotoken.api_routes.ideal_link.legacy.job_snapshot",
        lambda job_id: {"status": "done", "result": {"long_url": "https://pay.openai.com/x"}, "job_id": job_id},
    )

    result = _endpoint(app, "/api/ideal/long-link/jobs/{job_id}", "GET")("ideal-job-1")

    assert result["status"] == "done"
    assert result["job_id"] == "ideal-job-1"


def test_create_ideal_qr_returns_png(monkeypatch):
    app = _app()

    def fake_qr_code(req):
        from fastapi.responses import StreamingResponse

        assert req.value == "https://pay.openai.com/test"
        return StreamingResponse(io.BytesIO(b"png-bytes"), media_type="image/png")

    monkeypatch.setattr("autotoken.api_routes.ideal_link.legacy.qr_code", fake_qr_code)

    response = _endpoint(app, "/api/ideal/qr", "POST")(IdealQrRequest(value="https://pay.openai.com/test"))

    assert response.media_type == "image/png"
