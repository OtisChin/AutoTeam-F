from fastapi import FastAPI, HTTPException

from autotoken import trade
from autotoken.api_routes.trade import (
    TradeCdkStatusParams,
    TradeCreateCdkParams,
    TradeHistoryDownloadParams,
    TradeQueryParams,
    TradeRedeemParams,
    TradeSetPasswordParams,
    create_trade_router,
)


def _app():
    app = FastAPI()
    app.include_router(create_trade_router())
    return app


def _endpoint(app, path, method):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"missing route {method} {path}")


def test_trade_admin_routes_delegate_to_trade_service(monkeypatch):
    app = _app()
    captured = {}

    monkeypatch.setattr(trade, "inventory_summary", lambda: {"available": 2})
    monkeypatch.setattr(trade, "list_cdks", lambda limit: [{"limit": limit}])
    monkeypatch.setattr(trade, "create_cdk", lambda quota_total, note="": {"quota_total": quota_total, "note": note})
    monkeypatch.setattr(trade, "get_cdk", lambda code: {"code": code})
    monkeypatch.setattr(trade, "revoke_cdk", lambda code: {"revoked": code})
    monkeypatch.setattr(trade, "download_cdk_redemptions", lambda code: {"download": code})

    assert _endpoint(app, "/api/trade/summary", "GET")() == {"available": 2}
    assert _endpoint(app, "/api/trade/cdks", "GET")(limit=7) == {"items": [{"limit": 7}]}
    assert _endpoint(app, "/api/trade/cdks", "POST")(TradeCreateCdkParams(quotaTotal=3, note="n")) == {
        "quota_total": 3,
        "note": "n",
    }
    assert _endpoint(app, "/api/trade/cdks/{code}", "GET")("CDK-1") == {"code": "CDK-1"}
    assert _endpoint(app, "/api/trade/cdks/{code}/revoke", "POST")("CDK-1") == {"revoked": "CDK-1"}
    assert _endpoint(app, "/api/trade/cdks/{code}/redemptions/download", "GET")("CDK-1") == {"download": "CDK-1"}
    assert captured == {}


def test_public_plus_extractor_routes_delegate_to_trade_service(monkeypatch):
    app = _app()
    captured = {}

    def fake_redeem(code, password, count, formats):
        captured["redeem"] = (code, password, count, formats)
        return {"redeemed": True}

    monkeypatch.setattr(trade, "redeem_cdk", fake_redeem)
    monkeypatch.setattr(trade, "query_cdk_remaining", lambda code, password: {"remaining": code, "password": password})
    monkeypatch.setattr(trade, "list_cdk_redemption_history", lambda code, password: {"history": code, "password": password})
    monkeypatch.setattr(
        trade,
        "download_cdk_redemption_batch",
        lambda code, password, batch_id: {"download": code, "password": password, "batch_id": batch_id},
    )
    monkeypatch.setattr(trade, "set_cdk_password", lambda code, password: {"set": code, "password": password})
    monkeypatch.setattr(trade, "public_cdk_status", lambda code: {"status": code})

    assert _endpoint(app, "/api/public/plus-extractor/redeem", "POST")(
        TradeRedeemParams(code="CDK-1", password="pw", count=2, formats=["cpa", "sub"])
    ) == {"redeemed": True}
    assert captured["redeem"] == ("CDK-1", "pw", 2, ["cpa", "sub"])
    assert _endpoint(app, "/api/public/plus-extractor/query", "POST")(TradeQueryParams(code="CDK-1", password="pw")) == {
        "remaining": "CDK-1",
        "password": "pw",
    }
    assert _endpoint(app, "/api/public/plus-extractor/history", "POST")(TradeQueryParams(code="CDK-1", password="pw")) == {
        "history": "CDK-1",
        "password": "pw",
    }
    assert _endpoint(app, "/api/public/plus-extractor/history/download", "POST")(
        TradeHistoryDownloadParams(code="CDK-1", password="pw", batchId="batch-1")
    ) == {"download": "CDK-1", "password": "pw", "batch_id": "batch-1"}
    assert _endpoint(app, "/api/public/plus-extractor/set-password", "POST")(
        TradeSetPasswordParams(code="CDK-1", password="pw")
    ) == {"set": "CDK-1", "password": "pw"}
    assert _endpoint(app, "/api/public/plus-extractor/cdk-status", "POST")(TradeCdkStatusParams(code="CDK-1")) == {
        "status": "CDK-1"
    }


def test_trade_routes_translate_trade_errors_to_http_status(monkeypatch):
    app = _app()

    def fail():
        raise trade.TradeError("gone", status_code=410)

    monkeypatch.setattr(trade, "inventory_summary", fail)

    try:
        _endpoint(app, "/api/trade/summary", "GET")()
    except HTTPException as exc:
        assert exc.status_code == 410
        assert exc.detail == "gone"
    else:
        raise AssertionError("trade errors must be translated to HTTPException")
