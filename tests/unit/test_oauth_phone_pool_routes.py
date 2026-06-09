from fastapi import FastAPI, HTTPException

from autotoken import oauth_phone_pool, oauth_phone_records
from autotoken.api_routes.oauth_phone_pool import (
    OAUTH_PHONE_POOL_DELETE_MAX_IDS,
    OAUTH_PHONE_POOL_IMPORT_MAX_BYTES,
    OAUTH_PHONE_POOL_IMPORT_MAX_LINES,
    OAuthPhonePoolDeleteParams,
    OAuthPhonePoolImportParams,
    OAuthPhonePoolUpsertParams,
    create_oauth_phone_pool_router,
)


def _app():
    app = FastAPI()
    app.include_router(create_oauth_phone_pool_router())
    return app


def _endpoint(app, path, method):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"missing route {method} {path}")


def test_oauth_phone_pool_list_and_records_routes_report_counts(monkeypatch):
    app = _app()
    phones = [
        {"id": "a", "status": "available"},
        {"id": "b", "status": "full"},
        {"id": "c", "status": "invalid"},
        {"id": "d", "status": "cooldown"},
        {"id": "e", "status": "disabled"},
    ]
    records = [
        {"status": "success_bound"},
        {"status": "acquired"},
        {"status": "cancelled"},
        {"status": "failed"},
        {"status": "invalid"},
        {"status": "cooldown"},
    ]
    captured = {}

    monkeypatch.setattr(oauth_phone_pool, "list_phones", lambda: phones)

    def fake_list_records(limit=300):
        captured["limit"] = limit
        return records

    monkeypatch.setattr(oauth_phone_records, "list_records", fake_list_records)

    assert _endpoint(app, "/api/oauth-phone-pool", "GET")() == {
        "items": phones,
        "total": 5,
        "available_count": 1,
        "full_count": 1,
        "invalid_count": 1,
        "cooldown_count": 1,
        "disabled_count": 1,
    }
    assert _endpoint(app, "/api/oauth-phone-records", "GET")(limit=25) == {
        "items": records,
        "total": 6,
        "success_count": 1,
        "active_count": 1,
        "cancelled_count": 1,
        "failed_count": 3,
    }
    assert captured["limit"] == 25


def test_oauth_phone_pool_crud_routes_delegate_to_service(monkeypatch):
    app = _app()
    calls = {}

    monkeypatch.setattr(oauth_phone_pool, "import_phones", lambda text: {"text": text})

    def fake_upsert_phone(payload):
        calls["upsert"] = payload
        return {"id": "new"}

    monkeypatch.setattr(oauth_phone_pool, "upsert_phone", fake_upsert_phone)

    def fake_update_phone(item_id, payload):
        calls["update"] = (item_id, payload)
        return {"id": item_id}

    monkeypatch.setattr(oauth_phone_pool, "update_phone", fake_update_phone)
    monkeypatch.setattr(oauth_phone_pool, "delete_phones", lambda ids: len(ids))
    monkeypatch.setattr(oauth_phone_pool, "list_phones", lambda: [{"id": "kept"}])

    assert _endpoint(app, "/api/oauth-phone-pool/import", "POST")(OAuthPhonePoolImportParams(text="line")) == {
        "text": "line"
    }
    result = _endpoint(app, "/api/oauth-phone-pool", "POST")(
        OAuthPhonePoolUpsertParams(phoneNumber="+12025550123", smsUrl="https://sms.example", boundCount=1)
    )
    assert result == {"id": "new"}
    assert calls["upsert"]["phone_number"] == "+12025550123"
    assert calls["upsert"]["sms_url"] == "https://sms.example"
    assert calls["upsert"]["bound_count"] == 1

    assert _endpoint(app, "/api/oauth-phone-pool/{item_id}", "PUT")(
        "phone-1",
        OAuthPhonePoolUpsertParams(phone_number="+12025550124", sms_url="https://sms.example/2"),
    ) == {"id": "phone-1"}
    assert calls["update"][0] == "phone-1"
    assert calls["update"][1]["phone_number"] == "+12025550124"

    assert _endpoint(app, "/api/oauth-phone-pool/delete", "POST")(OAuthPhonePoolDeleteParams(ids=["a", "b"])) == {
        "deleted": 2,
        "items": [{"id": "kept"}],
        "total": 1,
    }


def test_oauth_phone_pool_delete_rejects_too_many_raw_ids_before_service(monkeypatch):
    app = _app()
    monkeypatch.setattr(oauth_phone_pool, "delete_phones", lambda _ids: (_ for _ in ()).throw(AssertionError()))

    try:
        _endpoint(app, "/api/oauth-phone-pool/delete", "POST")(
            OAuthPhonePoolDeleteParams(ids=[str(index) for index in range(OAUTH_PHONE_POOL_DELETE_MAX_IDS + 1)])
        )
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "OAuth 手机池删除条目过多" in exc.detail
    else:
        raise AssertionError("oversized OAuth phone pool delete must fail")


def test_oauth_phone_pool_routes_translate_service_errors(monkeypatch):
    app = _app()

    monkeypatch.setattr(oauth_phone_pool, "import_phones", lambda _text: (_ for _ in ()).throw(ValueError("bad import")))
    try:
        _endpoint(app, "/api/oauth-phone-pool/import", "POST")(OAuthPhonePoolImportParams(text="bad"))
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail == "bad import"
    else:
        raise AssertionError("bad phone import must fail")

    monkeypatch.setattr(oauth_phone_pool, "upsert_phone", lambda _payload: (_ for _ in ()).throw(ValueError("bad item")))
    try:
        _endpoint(app, "/api/oauth-phone-pool", "POST")(OAuthPhonePoolUpsertParams())
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail == "bad item"
    else:
        raise AssertionError("bad phone upsert must fail")

    monkeypatch.setattr(oauth_phone_pool, "update_phone", lambda *_args: (_ for _ in ()).throw(KeyError("missing")))
    try:
        _endpoint(app, "/api/oauth-phone-pool/{item_id}", "PUT")("missing", OAuthPhonePoolUpsertParams())
    except HTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "'missing'"
    else:
        raise AssertionError("missing phone update must fail")

    monkeypatch.setattr(oauth_phone_pool, "update_phone", lambda *_args: (_ for _ in ()).throw(ValueError("bad update")))
    try:
        _endpoint(app, "/api/oauth-phone-pool/{item_id}", "PUT")("bad", OAuthPhonePoolUpsertParams())
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail == "bad update"
    else:
        raise AssertionError("bad phone update must fail")


def test_oauth_phone_pool_import_rejects_oversized_text_before_service(monkeypatch):
    app = _app()
    monkeypatch.setattr(oauth_phone_pool, "import_phones", lambda _text: (_ for _ in ()).throw(AssertionError()))

    try:
        _endpoint(app, "/api/oauth-phone-pool/import", "POST")(
            OAuthPhonePoolImportParams(text=" " * (OAUTH_PHONE_POOL_IMPORT_MAX_BYTES + 1))
        )
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "OAuth 手机池导入内容过大" in exc.detail
    else:
        raise AssertionError("oversized OAuth phone pool import must fail")


def test_oauth_phone_pool_import_rejects_too_many_lines_before_service(monkeypatch):
    app = _app()
    monkeypatch.setattr(oauth_phone_pool, "import_phones", lambda _text: (_ for _ in ()).throw(AssertionError()))

    try:
        _endpoint(app, "/api/oauth-phone-pool/import", "POST")(
            OAuthPhonePoolImportParams(
                text="\n".join(["+12025550123----https://sms.example"] * (OAUTH_PHONE_POOL_IMPORT_MAX_LINES + 1))
            )
        )
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "OAuth 手机池导入行数过多" in exc.detail
    else:
        raise AssertionError("too many OAuth phone pool import lines must fail")
