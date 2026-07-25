from __future__ import annotations

import json

import pytest
from fastapi import FastAPI

from autotoken.api_routes import kakao_pay
from autotoken.services import proxy_runtime


def _app():
    app = FastAPI()
    app.include_router(kakao_pay.create_kakao_pay_router())
    return app


def _endpoint(app, path, method):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"missing route {method} {path}")


@pytest.fixture(autouse=True)
def isolated_files(monkeypatch, tmp_path):
    monkeypatch.setattr(kakao_pay, "LINKS_FILE", tmp_path / "kakao_pay_links.json")
    monkeypatch.setattr(kakao_pay, "ACCOUNT_STATUS_FILE", tmp_path / "kakao_pay_account_status.json")
    monkeypatch.setattr(proxy_runtime, "preflight_payment_proxy_url", lambda proxy_url: (True, "HTTP 200"))
    monkeypatch.setattr(proxy_runtime, "preflight_chatgpt_authenticated_proxy_url", lambda proxy_url, access_token: (True, "auth_api HTTP 200"))
    kakao_pay.JOBS.clear()
    yield
    kakao_pay.JOBS.clear()


def test_accounts_default_to_pending_kakao_status(monkeypatch):
    app = _app()
    monkeypatch.setattr(kakao_pay.account_store, "load_accounts", lambda: [
        {"email": "user@example.com", "status": "active", "account_type": "free", "ttl_seconds": 3600},
        {"email": "plus@example.com", "status": "active", "account_type": "plus", "ttl_seconds": 7200},
    ])
    monkeypatch.setattr(kakao_pay, "_iter_auth_accounts", lambda include_paid=False: [
        {"email": "user@example.com", "auth_file": "auth-user.json"},
        {"email": "plus@example.com", "auth_file": "auth-plus.json"},
    ])

    result = _endpoint(app, "/api/kakao-pay/accounts", "GET")()

    assert [row["email"] for row in result["accounts"]] == ["user@example.com", "plus@example.com"]
    assert result["accounts"][0]["kakao_status"] == "pending"
    assert result["accounts"][0]["kakao_status_text"] == "未提链"
    assert result["accounts"][0]["kakao_selectable"] is True
    assert result["accounts"][1]["kakao_status"] == "paid"
    assert result["accounts"][1]["kakao_status_text"] == "已支付"
    assert result["accounts"][1]["kakao_selectable"] is False


def test_batch_job_generates_kakao_link_and_records_status(monkeypatch):
    email = "user@example.com"
    captured = {}
    monkeypatch.setattr(kakao_pay, "_iter_auth_accounts", lambda include_paid=False: [{"email": email, "auth_file": "auth.json"}])
    monkeypatch.setattr(kakao_pay, "_load_token_for_email", lambda value: "token-" + value)

    def fake_generate_kakao_trial(cfg, log):
        captured["cfg"] = cfg
        log("fake kakao success")
        return {
            "ok": True,
            "amount": "29000",
            "fields": {
                "kakao_link": "https://pm-redirects.stripe.com/authorize/acct/test_nonce",
                "provider_redirect_url": "https://pay.nicepay.co.kr/v1/checkout/pay/test",
                "stripe_redirect_url": "https://pm-redirects.stripe.com/authorize/acct/test_nonce",
                "cs_id": "cs_test",
                "billing": {"country": "KR"},
            },
            "billing": {"country": "KR"},
        }

    monkeypatch.setattr(kakao_pay, "generate_kakao_trial", fake_generate_kakao_trial)
    job_id = "kakao-job"
    kakao_pay.JOBS[job_id] = {
        "id": job_id, "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 0,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {},
    }

    req = kakao_pay.KakaoPayBatchStartRequest.model_validate({
        "accountEmails": [email],
        "proxies": "host:1000:user-region-KR-sid-old-t-120:pass",
        "concurrency": 1,
    })
    kakao_pay._run_batch_job(job_id, req)

    job = kakao_pay.JOBS[job_id]
    assert job["status"] == "success"
    assert job["completed"] == 1
    assert job["result"]["successes"][0]["link"]["kakao_link"] == "https://pm-redirects.stripe.com/authorize/acct/test_nonce"
    assert captured["cfg"].access_token == "token-user@example.com"
    assert captured["cfg"].region == "KR"
    assert json.loads(kakao_pay.LINKS_FILE.read_text(encoding="utf-8"))[0]["account_email"] == email
    statuses = json.loads(kakao_pay.ACCOUNT_STATUS_FILE.read_text(encoding="utf-8"))
    assert statuses[email]["status"] == "success"


def test_kakao_routes_expose_job_and_link_management(monkeypatch):
    app = _app()
    monkeypatch.setattr(kakao_pay.threading, "Thread", lambda *args, **kwargs: type("DummyThread", (), {"start": lambda self: None})())

    start = _endpoint(app, "/api/kakao-pay/batch/start", "POST")(
        kakao_pay.KakaoPayBatchStartRequest.model_validate({"accountEmails": ["user@example.com"], "proxies": "host:1000:user:pass"})
    )
    job = _endpoint(app, "/api/kakao-pay/jobs/{job_id}", "GET")(start["job_id"])

    assert job["status"] == "queued"
    assert _endpoint(app, "/api/kakao-pay/links", "GET")() == {"links": [], "pruned_deleted_accounts": 0}
