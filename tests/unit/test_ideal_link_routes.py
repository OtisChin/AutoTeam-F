from __future__ import annotations

import base64
import io
import json

import pytest
from fastapi import FastAPI, HTTPException

from autotoken.api_routes.ideal_link import (
    IdealBatchStartRequest,
    IdealDeleteLinksRequest,
    IdealLongLinkRequest,
    IdealQrRequest,
    create_ideal_link_router,
)
from autotoken.integrations.gpthel_ideal import app as ideal_app
from autotoken.services import proxy_runtime


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


def test_ideal_long_link_job_keeps_account_on_non_zero_amount(monkeypatch):
    email = "ideal-nonzero@example.com"
    payload = base64.urlsafe_b64encode(json.dumps({"email": email}).encode("utf-8")).decode("ascii").rstrip("=")
    access_token = f"eyJhbGciOiJub25lIn0.{payload}.sig"
    deleted_accounts: list[str] = []
    deleted_sessions: list[str] = []
    disabled_legacy: list[str] = []

    class ImmediateThread:
        def __init__(self, target, daemon=False):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(ideal_app.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(ideal_app, "prepare_request_proxy", lambda req: False)
    monkeypatch.setattr(ideal_app, "save_diagnostics", lambda req, job_id, final_status: "")
    monkeypatch.setattr(ideal_app.account_store, "delete_account", lambda value: deleted_accounts.append(value) or True)
    monkeypatch.setattr(ideal_app, "delete_auth_session", lambda value: deleted_sessions.append(value) or True)
    monkeypatch.setattr(ideal_app.account_pool_store, "disable_account_by_email", lambda value: disabled_legacy.append(value) or True)

    def fake_generate(req, use_explicit_proxy, steps=None):
        raise HTTPException(status_code=502, detail="amount policy failed after retries: amount=1667, allowed<= 0")

    monkeypatch.setattr(ideal_app, "generate_long_link_once", fake_generate)
    ideal_app.LONG_LINK_JOBS.clear()

    result = ideal_app.start_long_link_job(
        ideal_app.LongLinkRequest.model_validate(
            {
                "accessToken": access_token,
                "proxy": "",
                "link_type": "ideal",
                "billing_country": "NL",
            }
        )
    )

    job = ideal_app.job_snapshot(result["job_id"])
    assert job["status"] == "error"
    assert "金额非 0" in job["error"]
    assert "已从账号池删除" not in job["error"]
    assert deleted_accounts == []
    assert deleted_sessions == []
    assert disabled_legacy == []


def test_ideal_prepare_request_proxy_uses_configured_preflight_attempts(monkeypatch):
    preflighted: list[str] = []

    def fake_payment_preflight(proxy_url):
        preflighted.append(proxy_url)
        return (False, "ProxyError: ruleset blocked")

    monkeypatch.setattr(proxy_runtime, "preflight_payment_proxy_url", fake_payment_preflight)
    monkeypatch.setattr(proxy_runtime, "preflight_chatgpt_authenticated_proxy_url", lambda proxy_url, access_token: (True, "auth_api HTTP 200"))

    req = ideal_app.LongLinkRequest.model_validate(
        {
            "accessToken": "token",
            "proxy": "proxy.example:1000:user-region-US-sid-old-t-120:pass",
            "link_type": "ideal",
            "billing_country": "NL",
            "proxyPreflightAttempts": 3,
        }
    )

    with pytest.raises(HTTPException, match="代理预检失败"):
        ideal_app.prepare_request_proxy(req)

    assert len(preflighted) == 3


def test_ideal_amount_policy_accepts_one_minor_unit():
    assert ideal_app.is_acceptable_low_amount("0") is True
    assert ideal_app.is_acceptable_low_amount(0) is True
    assert ideal_app.is_acceptable_low_amount("1") is True


def test_ideal_accounts_default_to_pending_status(monkeypatch, tmp_path):
    app = _app()
    from autotoken.api_routes import ideal_link

    monkeypatch.setattr(ideal_link, "LINKS_FILE", tmp_path / "ideal_links.json")
    monkeypatch.setattr(ideal_link, "ACCOUNT_STATUS_FILE", tmp_path / "ideal_account_status.json")
    monkeypatch.setattr(ideal_link.pix_routes, "_iter_auth_accounts", lambda include_paid=False: [
        {"email": "ideal@example.com", "ttl_seconds": 3600, "updated_at": 1},
    ])
    monkeypatch.setattr(ideal_link.account_store, "load_accounts", lambda: [
        {"email": "ideal@example.com", "status": "active"},
    ])

    result = _endpoint(app, "/api/ideal/accounts", "GET")()

    assert result["accounts"][0]["email"] == "ideal@example.com"
    assert result["accounts"][0]["ideal_status"] == "pending"
    assert result["accounts"][0]["ideal_status_text"] == "未提链"
    assert result["accounts"][0]["ideal_selectable"] is True


def test_ideal_batch_start_runs_accounts_and_persists_link(monkeypatch, tmp_path):
    app = _app()
    from autotoken.api_routes import ideal_link

    class ImmediateThread:
        def __init__(self, target, daemon=False):
            self.target = target

        def start(self):
            self.target()

    class FakeResult:
        def model_dump(self):
            return {
                "ok": True,
                "cs_id": "cs_ideal",
                "billing_country": "NL",
                "currency": "EUR",
                "link_type": "ideal",
                "long_url": "https://pay.openai.com/ideal",
                "amount": "0",
                "amount_display": "€0.00",
                "steps": [{"time": "12:00:00", "name": "done", "status": "ok", "detail": ""}],
            }

    monkeypatch.setattr(ideal_link, "LINKS_FILE", tmp_path / "ideal_links.json")
    monkeypatch.setattr(ideal_link, "ACCOUNT_STATUS_FILE", tmp_path / "ideal_account_status.json")
    monkeypatch.setattr(ideal_link.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(ideal_link.pix_routes, "_iter_auth_accounts", lambda include_paid=False: [
        {"email": "ideal@example.com", "ttl_seconds": 3600, "updated_at": 1},
    ])
    monkeypatch.setattr(ideal_link.pix_routes, "_load_token_for_email", lambda email: "token-for-" + email)
    monkeypatch.setattr(ideal_link.account_store, "load_accounts", lambda: [])
    monkeypatch.setattr(ideal_link.legacy, "prepare_request_proxy", lambda req: False)
    monkeypatch.setattr(ideal_link.legacy, "generate_long_link_once", lambda req, use_explicit_proxy, steps=None: FakeResult())
    ideal_link.JOBS.clear()

    result = _endpoint(app, "/api/ideal/batch/start", "POST")(
        IdealBatchStartRequest.model_validate({"accountEmails": ["ideal@example.com"], "concurrency": 1})
    )
    job = _endpoint(app, "/api/ideal/jobs/{job_id}", "GET")(result["job_id"])
    links = _endpoint(app, "/api/ideal/links", "GET")()

    assert job["status"] == "success"
    assert job["successes"][0]["email"] == "ideal@example.com"
    assert links["links"][0]["ideal_link"] == "https://pay.openai.com/ideal"
    assert links["links"][0]["account_email"] == "ideal@example.com"


def test_ideal_batch_propagates_proxy_preflight_attempts(monkeypatch, tmp_path):
    app = _app()
    from autotoken.api_routes import ideal_link

    class ImmediateThread:
        def __init__(self, target, daemon=False):
            self.target = target

        def start(self):
            self.target()

    class FakeResult:
        def model_dump(self):
            return {
                "ok": True,
                "cs_id": "cs_ideal",
                "billing_country": "NL",
                "currency": "EUR",
                "link_type": "ideal",
                "long_url": "https://pay.openai.com/ideal",
                "amount": "0",
                "amount_display": "€0.00",
            }

    captured: dict[str, int] = {}

    def fake_prepare(req):
        captured["attempts"] = req.proxy_preflight_attempts
        return False

    monkeypatch.setattr(ideal_link, "LINKS_FILE", tmp_path / "ideal_links.json")
    monkeypatch.setattr(ideal_link, "ACCOUNT_STATUS_FILE", tmp_path / "ideal_account_status.json")
    monkeypatch.setattr(ideal_link.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(ideal_link.pix_routes, "_iter_auth_accounts", lambda include_paid=False: [
        {"email": "ideal@example.com", "ttl_seconds": 3600, "updated_at": 1},
    ])
    monkeypatch.setattr(ideal_link.pix_routes, "_load_token_for_email", lambda email: "token-for-" + email)
    monkeypatch.setattr(ideal_link.account_store, "load_accounts", lambda: [])
    monkeypatch.setattr(ideal_link.legacy, "prepare_request_proxy", fake_prepare)
    monkeypatch.setattr(ideal_link.legacy, "generate_long_link_once", lambda req, use_explicit_proxy, steps=None: FakeResult())
    ideal_link.JOBS.clear()

    result = _endpoint(app, "/api/ideal/batch/start", "POST")(
        IdealBatchStartRequest.model_validate({
            "accountEmails": ["ideal@example.com"],
            "concurrency": 1,
            "proxyPreflightAttempts": 4,
        })
    )

    assert _endpoint(app, "/api/ideal/jobs/{job_id}", "GET")(result["job_id"])["status"] == "success"
    assert captured["attempts"] == 4


def test_ideal_proxy_preflight_attempts_cap_at_one_hundred():
    batch_req = IdealBatchStartRequest.model_validate({
        "accountEmails": [],
        "proxyPreflightAttempts": 200,
    })
    long_req = ideal_app.LongLinkRequest.model_validate({
        "accessToken": "token",
        "proxyPreflightAttempts": 200,
    })

    assert batch_req.proxy_preflight_attempts == 100
    assert long_req.proxy_preflight_attempts == 100


def test_ideal_links_delete_and_clear_use_ideal_file(tmp_path, monkeypatch):
    app = _app()
    from autotoken.api_routes import ideal_link

    links_file = tmp_path / "ideal_links.json"
    links_file.write_text(json.dumps([
        {"id": "keep", "ideal_link": "https://pay.openai.com/keep"},
        {"id": "remove", "ideal_link": "https://pay.openai.com/remove"},
    ]), encoding="utf-8")
    monkeypatch.setattr(ideal_link, "LINKS_FILE", links_file)

    deleted = _endpoint(app, "/api/ideal/links/delete", "POST")(IdealDeleteLinksRequest(ids=["remove", "missing"]))
    cleared = _endpoint(app, "/api/ideal/links/clear", "POST")()

    assert deleted["deleted"] == 1
    assert cleared["deleted"] == 1
    assert json.loads(links_file.read_text(encoding="utf-8")) == []
