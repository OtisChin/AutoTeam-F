from fastapi import FastAPI, HTTPException

from autotoken import card_pool
from autotoken.api_routes import card_pool as card_pool_routes
from autotoken.api_routes.card_pool import (
    CARD_POOL_DELETE_MAX_IDS,
    CARD_POOL_IMPORT_MAX_BYTES,
    CARD_POOL_IMPORT_MAX_LINES,
    CARD_POOL_REDEEM_BATCH_MAX_IDS,
    CardPoolDeleteParams,
    CardPoolFetchSmsParams,
    CardPoolImportParams,
    CardPoolRedeemBatchParams,
    CardPoolRedeemParams,
    CardPoolUpdateParams,
    create_card_pool_router,
)


def _app():
    app = FastAPI()
    app.include_router(create_card_pool_router())
    return app


def _endpoint(app, path, method):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"missing route {method} {path}")


def test_card_pool_crud_routes_delegate_to_service(monkeypatch):
    app = _app()
    calls = {}

    monkeypatch.setattr(card_pool, "stats_for", lambda pool_type: {"pool": pool_type})
    monkeypatch.setattr(card_pool, "list_items", lambda pool_type: [{"type": pool_type}])
    monkeypatch.setattr(card_pool, "import_text_lines", lambda pool_type, text, provider="": [{"pool": pool_type, "text": text, "provider": provider}])
    monkeypatch.setattr(card_pool, "delete_items", lambda pool_type, ids: len(ids))

    def fake_update_item(pool_type, item_id, **kwargs):
        calls["update"] = (pool_type, item_id, kwargs)
        return {"id": item_id, "type": pool_type}

    monkeypatch.setattr(card_pool, "update_item", fake_update_item)

    assert _endpoint(app, "/api/card-pool/{pool_type}", "GET")("card") == {
        "pool_type": "card",
        "stats": {"pool": "card"},
        "items": [{"type": "card"}],
    }
    assert _endpoint(app, "/api/card-pool/import", "POST")(CardPoolImportParams(pool_type="card", text="line", provider="p")) == {
        "message": "导入成功，新增 1 条",
        "imported": [{"pool": "card", "text": "line", "provider": "p"}],
        "stats": {"pool": "card"},
    }
    assert _endpoint(app, "/api/card-pool/delete", "POST")(CardPoolDeleteParams(pool_type="card", ids=["a", "b"])) == {
        "message": "已删除 2 条记录",
        "deleted": 2,
        "stats": {"pool": "card"},
    }
    assert _endpoint(app, "/api/card-pool/update", "POST")(
        CardPoolUpdateParams(pool_type="card", item_id="item-1", status="used")
    ) == {
        "message": "更新成功",
        "item": {"id": "item-1", "type": "card"},
        "stats": {"pool": "card"},
    }
    assert calls["update"] == (
        "card",
        "item-1",
        {"status": "used", "provider": None, "used_by": None, "expires_at": None},
    )


def test_card_pool_update_maps_missing_and_invalid_pool_to_http_errors(monkeypatch):
    app = _app()

    monkeypatch.setattr(card_pool, "update_item", lambda *_args, **_kwargs: None)
    try:
        _endpoint(app, "/api/card-pool/update", "POST")(CardPoolUpdateParams(pool_type="card", item_id="missing"))
    except HTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "记录不存在"
    else:
        raise AssertionError("missing card pool item must fail")

    def invalid_pool(*_args, **_kwargs):
        raise ValueError("bad pool")

    monkeypatch.setattr(card_pool, "update_item", invalid_pool)
    try:
        _endpoint(app, "/api/card-pool/update", "POST")(CardPoolUpdateParams(pool_type="bad", item_id="item"))
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail == "bad pool"
    else:
        raise AssertionError("invalid pool must fail")


def test_card_pool_import_rejects_oversized_text_before_service(monkeypatch):
    app = _app()
    monkeypatch.setattr(card_pool, "import_text_lines", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()))

    try:
        _endpoint(app, "/api/card-pool/import", "POST")(
            CardPoolImportParams(pool_type="card", text=" " * (CARD_POOL_IMPORT_MAX_BYTES + 1))
        )
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "卡池导入内容过大" in exc.detail
    else:
        raise AssertionError("oversized card pool import must fail")


def test_card_pool_import_rejects_too_many_lines_before_service(monkeypatch):
    app = _app()
    monkeypatch.setattr(card_pool, "import_text_lines", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()))

    try:
        _endpoint(app, "/api/card-pool/import", "POST")(
            CardPoolImportParams(pool_type="redeem", text="\n".join(["line"] * (CARD_POOL_IMPORT_MAX_LINES + 1)))
        )
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "卡池导入行数过多" in exc.detail
    else:
        raise AssertionError("too many card pool import lines must fail")


def test_card_pool_redeem_988_adds_card_and_marks_redeem_used(monkeypatch):
    app = _app()
    updates = []
    added = []
    redeem_item = {"id": "redeem-1", "value": "code-1", "provider": "988", "status": "unused"}

    def fake_find_item(pool_type, item_id):
        if pool_type == "redeem" and item_id == "redeem-1":
            return {**redeem_item, "status": "used" if updates else "unused"}
        return None

    class FakeResponse:
        ok = True
        status_code = 200
        text = '{"success": true}'

        def json(self):
            return {"success": True, "content": {"card_number": "4111111111111111", "expiry_date": "2030/05"}}

    monkeypatch.setattr(card_pool, "find_item", fake_find_item)
    monkeypatch.setattr(card_pool, "stats_for", lambda pool_type: {"pool": pool_type})
    monkeypatch.setattr(card_pool, "update_item", lambda pool_type, item_id, **kwargs: updates.append((pool_type, item_id, kwargs)) or fake_find_item(pool_type, item_id))
    monkeypatch.setattr(card_pool, "add_card_item", lambda **kwargs: added.append(kwargs) or {"id": "card-1", **kwargs})
    monkeypatch.setattr(card_pool_routes.requests, "post", lambda *args, **kwargs: FakeResponse())

    result = _endpoint(app, "/api/card-pool/redeem", "POST")(CardPoolRedeemParams(item_id="redeem-1"))

    assert result["message"] == "兑换成功"
    assert result["card_item"]["value"] == "4111111111111111"
    assert added[0]["provider"] == "988"
    assert updates == [("redeem", "redeem-1", {"status": "used"})]


def test_card_pool_redeem_and_batch_report_errors(monkeypatch):
    app = _app()

    monkeypatch.setattr(card_pool, "find_item", lambda pool_type, item_id: None)
    try:
        _endpoint(app, "/api/card-pool/redeem", "POST")(CardPoolRedeemParams(item_id="missing"))
    except HTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "兑换码不存在"
    else:
        raise AssertionError("missing redeem code must fail")

    result = _endpoint(app, "/api/card-pool/redeem-batch", "POST")(CardPoolRedeemBatchParams(item_ids=["missing"]))
    assert result == {
        "message": "批量兑换完成，成功 0/1",
        "results": [{"item_id": "missing", "ok": False, "error": "兑换码不存在", "status_code": 404}],
    }


def test_card_pool_delete_rejects_too_many_raw_ids_before_service(monkeypatch):
    app = _app()
    monkeypatch.setattr(card_pool, "delete_items", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()))

    try:
        _endpoint(app, "/api/card-pool/delete", "POST")(
            CardPoolDeleteParams(pool_type="card", ids=[str(index) for index in range(CARD_POOL_DELETE_MAX_IDS + 1)])
        )
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "卡池删除条目过多" in exc.detail
    else:
        raise AssertionError("oversized card pool delete must fail")


def test_card_pool_redeem_batch_rejects_too_many_raw_ids(monkeypatch):
    app = _app()
    monkeypatch.setattr(card_pool, "find_item", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()))

    try:
        _endpoint(app, "/api/card-pool/redeem-batch", "POST")(
            CardPoolRedeemBatchParams(item_ids=[str(index) for index in range(CARD_POOL_REDEEM_BATCH_MAX_IDS + 1)])
        )
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "卡池批量兑换条目过多" in exc.detail
    else:
        raise AssertionError("oversized card pool redeem batch must fail")


def test_card_pool_fetch_sms_validates_url_and_returns_text(monkeypatch):
    app = _app()

    try:
        _endpoint(app, "/api/card-pool/fetch-sms", "POST")(CardPoolFetchSmsParams(url=""))
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail == "接码 API 为空"
    else:
        raise AssertionError("empty SMS URL must fail")

    try:
        _endpoint(app, "/api/card-pool/fetch-sms", "POST")(CardPoolFetchSmsParams(url="ftp://example.test"))
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail == "接码 API 格式无效"
    else:
        raise AssertionError("invalid SMS URL must fail")

    class FakeResponse:
        ok = True
        status_code = 200
        text = "  OTP 123456  "

    monkeypatch.setattr(card_pool_routes.requests, "get", lambda *args, **kwargs: FakeResponse())

    assert _endpoint(app, "/api/card-pool/fetch-sms", "POST")(CardPoolFetchSmsParams(url="https://sms.example.test")) == {
        "url": "https://sms.example.test",
        "status_code": 200,
        "text": "OTP 123456",
    }
