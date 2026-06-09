from fastapi import FastAPI, HTTPException
from starlette.requests import Request

from autotoken import account_hub
from autotoken.api_routes.account_hub import (
    ACCOUNT_HUB_INGEST_MAX_ITEMS,
    ACCOUNT_HUB_SYNC_MAX_EMAILS,
    AccountHubConfigParams,
    AccountHubIngestPayload,
    AccountHubSyncParams,
    create_account_hub_router,
)


def _app():
    app = FastAPI()
    app.include_router(create_account_hub_router(normalize_email=lambda value: (value or "").strip().lower()))
    return app


def _endpoint(app, path, method):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"missing route {method} {path}")


def _request(token: str = ""):
    headers = []
    if token:
        headers.append((b"x-account-hub-token", token.encode()))
    return Request({"type": "http", "method": "POST", "path": "/", "headers": headers})


def test_account_hub_config_routes_delegate_to_service(monkeypatch):
    app = _app()
    saved_config = {"url": "http://hub.local", "token": "secret", "name": "node", "auto_upload": True}

    monkeypatch.setattr(account_hub, "get_config", lambda: saved_config)
    monkeypatch.setattr(account_hub, "set_config", lambda data: {**data, "saved": True})

    assert _endpoint(app, "/api/account-hub/config", "GET")() == saved_config
    result = _endpoint(app, "/api/account-hub/config", "PUT")(
        AccountHubConfigParams(url="hub.local", token="secret", name="node", autoUpload=True)
    )

    assert result == {
        "message": "远程账号 Hub 配置已保存",
        "config": {"url": "hub.local", "token": "secret", "name": "node", "auto_upload": True, "saved": True},
    }


def test_account_hub_sync_normalizes_emails_and_rejects_empty_selection(monkeypatch):
    app = _app()
    captured = {}

    def fake_upload_to_hub(selected_emails):
        captured["selected_emails"] = selected_emails
        return {"uploaded_accounts": len(selected_emails)}

    monkeypatch.setattr(account_hub, "upload_to_hub", fake_upload_to_hub)

    result = _endpoint(app, "/api/account-hub/sync", "POST")(
        AccountHubSyncParams(emails=[" USER@example.com ", "", "Two@example.com"])
    )
    assert result == {"uploaded_accounts": 2}
    assert captured["selected_emails"] == ["user@example.com", "two@example.com"]

    try:
        _endpoint(app, "/api/account-hub/sync", "POST")(AccountHubSyncParams(emails=["", "  "]))
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail == "请选择要同步到账号 Hub 的账号"
    else:
        raise AssertionError("empty account Hub sync selection must fail")


def test_account_hub_sync_rejects_too_many_raw_emails(monkeypatch):
    app = _app()
    monkeypatch.setattr(account_hub, "upload_to_hub", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()))

    try:
        _endpoint(app, "/api/account-hub/sync", "POST")(
            AccountHubSyncParams(emails=[f"user{index}@example.com" for index in range(ACCOUNT_HUB_SYNC_MAX_EMAILS + 1)])
        )
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "账号 Hub 同步条目过多" in exc.detail
    else:
        raise AssertionError("oversized account Hub sync selection must fail")


def test_account_hub_inbound_routes_require_configured_token(monkeypatch):
    app = _app()

    monkeypatch.setattr(account_hub, "expected_inbound_token", lambda: "")
    try:
        _endpoint(app, "/api/account-hub/ping", "POST")(_request("secret"))
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("missing account Hub token config must fail")

    monkeypatch.setattr(account_hub, "expected_inbound_token", lambda: "secret")
    try:
        _endpoint(app, "/api/account-hub/ping", "POST")(_request("wrong"))
    except HTTPException as exc:
        assert exc.status_code == 401
    else:
        raise AssertionError("wrong account Hub token must fail")

    result = _endpoint(app, "/api/account-hub/ping", "POST")(_request("secret"))
    assert result["ok"] is True
    assert result["message"] == "账号 Hub 连接成功"


def test_account_hub_ingest_delegates_payload_after_token_check(monkeypatch):
    app = _app()
    captured = {}

    monkeypatch.setattr(account_hub, "expected_inbound_token", lambda: "secret")

    def fake_receive_payload(payload):
        captured["payload"] = payload
        return {"received_accounts": len(payload["accounts"])}

    monkeypatch.setattr(account_hub, "receive_payload", fake_receive_payload)

    payload = AccountHubIngestPayload(source={"name": "node"}, accounts=[{"email": "user@example.com"}])
    result = _endpoint(app, "/api/account-hub/ingest", "POST")(_request("secret"), payload)

    assert result == {"received_accounts": 1}
    assert captured["payload"]["source"] == {"name": "node"}
    assert captured["payload"]["accounts"] == [{"email": "user@example.com"}]


def test_account_hub_ingest_rejects_too_many_raw_items_before_service(monkeypatch):
    app = _app()
    monkeypatch.setattr(account_hub, "expected_inbound_token", lambda: "secret")
    monkeypatch.setattr(account_hub, "receive_payload", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()))

    payload = AccountHubIngestPayload(accounts=[{} for _ in range(ACCOUNT_HUB_INGEST_MAX_ITEMS + 1)])
    try:
        _endpoint(app, "/api/account-hub/ingest", "POST")(_request("secret"), payload)
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "账号 Hub 入站账号条目过多" in exc.detail
    else:
        raise AssertionError("oversized account Hub ingest payload must fail")
