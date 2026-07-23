from __future__ import annotations

import json

import pytest
from fastapi import FastAPI, HTTPException

from autotoken.api_routes import us_paypal


def _app():
    app = FastAPI()
    app.include_router(us_paypal.create_us_paypal_router())
    return app


def _endpoint(app, path, method):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"missing route {method} {path}")


@pytest.fixture(autouse=True)
def isolated_files(monkeypatch, tmp_path):
    monkeypatch.setattr(us_paypal, "LINKS_FILE", tmp_path / "us_paypal_links.json")
    monkeypatch.setattr(us_paypal, "ACCOUNT_STATUS_FILE", tmp_path / "us_paypal_account_status.json")
    us_paypal.JOBS.clear()
    yield
    us_paypal.JOBS.clear()


def test_accounts_default_to_pending_paypal_status(monkeypatch):
    app = _app()
    monkeypatch.setattr(us_paypal.account_store, "load_accounts", lambda: [
        {"email": "user@example.com", "status": "active", "account_type": "free", "ttl_seconds": 3600},
        {"email": "plus@example.com", "status": "active", "account_type": "plus", "ttl_seconds": 7200},
    ])
    monkeypatch.setattr(us_paypal, "_iter_auth_accounts", lambda include_paid=False: [
        {"email": "user@example.com", "auth_file": "auth-user.json"},
        {"email": "plus@example.com", "auth_file": "auth-plus.json"},
    ])

    result = _endpoint(app, "/api/us-paypal/accounts", "GET")()

    assert [row["email"] for row in result["accounts"]] == ["user@example.com", "plus@example.com"]
    assert result["accounts"][0]["paypal_status"] == "pending"
    assert result["accounts"][0]["paypal_status_text"] == "未提链"
    assert result["accounts"][0]["paypal_selectable"] is True
    assert result["accounts"][1]["paypal_status"] == "paid"
    assert result["accounts"][1]["paypal_selectable"] is False


def test_batch_job_generates_paypal_link_and_records_status(monkeypatch):
    email = "user@example.com"
    captured = {}
    monkeypatch.setattr(us_paypal, "_iter_auth_accounts", lambda include_paid=False: [{"email": email, "auth_file": "auth.json"}])
    monkeypatch.setattr(us_paypal, "_load_token_for_email", lambda value: "token-" + value)

    def fake_generate_paypal_trial(cfg, log):
        captured["cfg"] = cfg
        log("fake paypal success")
        return {
            "ok": True,
            "amount": "0",
            "fields": {
                "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-TEST",
                "provider_redirect_url": "https://www.paypal.com/agreements/approve?ba_token=BA-TEST",
                "stripe_redirect_url": "https://pm-redirects.stripe.com/authorize/test",
                "ba_token": "BA-TEST",
                "cs_id": "cs_test",
                "billing": {"country": "US"},
            },
            "billing": {"country": "US"},
        }

    monkeypatch.setattr(us_paypal, "generate_paypal_trial", fake_generate_paypal_trial)
    job_id = "paypal-job"
    us_paypal.JOBS[job_id] = {
        "id": job_id, "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 0,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {},
    }

    req = us_paypal.UsPaypalBatchStartRequest.model_validate({
        "accountEmails": [email],
        "proxies": "host:1000:user:pass",
        "concurrency": 1,
        "promoMode": "skip",
    })
    us_paypal._run_batch_job(job_id, req)

    job = us_paypal.JOBS[job_id]
    assert job["status"] == "success"
    assert job["completed"] == 1
    assert job["result"]["successes"][0]["link"]["paypal_link"].startswith("https://www.paypal.com/agreements/approve")
    assert captured["cfg"].access_token == "token-user@example.com"
    assert captured["cfg"].region == "US"
    assert captured["cfg"].promo_region == "JP"
    assert captured["cfg"].apply_promo is False
    saved = json.loads(us_paypal.LINKS_FILE.read_text(encoding="utf-8"))[0]
    assert saved["ba_token"] == "BA-TEST"
    statuses = json.loads(us_paypal.ACCOUNT_STATUS_FILE.read_text(encoding="utf-8"))
    assert statuses[email]["status"] == "success"


def test_batch_job_passes_apply_promo_mode(monkeypatch):
    email = "promo@example.com"
    captured = {}
    monkeypatch.setattr(us_paypal, "_iter_auth_accounts", lambda include_paid=False: [{"email": email, "auth_file": "auth.json"}])
    monkeypatch.setattr(us_paypal, "_load_token_for_email", lambda _email: "token")

    def fake_generate_paypal_trial(cfg, log):
        captured["apply_promo"] = cfg.apply_promo
        return {"ok": True, "amount": "0", "fields": {"paypal_link": "https://pm-redirects.stripe.com/authorize/test", "cs_id": "cs_test"}, "billing": {}}

    monkeypatch.setattr(us_paypal, "generate_paypal_trial", fake_generate_paypal_trial)
    job_id = "paypal-promo-job"
    us_paypal.JOBS[job_id] = {
        "id": job_id, "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 0,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {},
    }

    req = us_paypal.UsPaypalBatchStartRequest.model_validate({"accountEmails": [email], "proxies": "p", "promoMode": "promo"})
    us_paypal._run_batch_job(job_id, req)

    assert captured["apply_promo"] is True


def test_batch_job_passes_custom_promo_region(monkeypatch):
    email = "promo-region@example.com"
    captured = {}
    monkeypatch.setattr(us_paypal, "_iter_auth_accounts", lambda include_paid=False: [{"email": email, "auth_file": "auth.json"}])
    monkeypatch.setattr(us_paypal, "_load_token_for_email", lambda _email: "token")

    def fake_generate_paypal_trial(cfg, log):
        captured["promo_region"] = cfg.promo_region
        return {"ok": True, "amount": "0", "fields": {"paypal_link": "https://pm-redirects.stripe.com/authorize/test", "cs_id": "cs_test"}, "billing": {}}

    monkeypatch.setattr(us_paypal, "generate_paypal_trial", fake_generate_paypal_trial)
    job_id = "paypal-promo-region-job"
    us_paypal.JOBS[job_id] = {
        "id": job_id, "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 0,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {},
    }

    req = us_paypal.UsPaypalBatchStartRequest.model_validate({"accountEmails": [email], "proxies": "p", "promoRegion": "vn"})
    us_paypal._run_batch_job(job_id, req)

    assert captured["promo_region"] == "VN"


def test_batch_job_passes_target_region_and_configurable_attempts(monkeypatch):
    email = "region-attempts@example.com"
    captured = {"regions": [], "attempts": 0}
    monkeypatch.setattr(us_paypal, "_iter_auth_accounts", lambda include_paid=False: [{"email": email, "auth_file": "auth.json"}])
    monkeypatch.setattr(us_paypal, "_load_token_for_email", lambda _email: "token")

    def fake_generate_paypal_trial(cfg, log):
        captured["attempts"] += 1
        captured["regions"].append((cfg.region, cfg.promo_region))
        if captured["attempts"] < 3:
            raise RuntimeError("temporary failure")
        return {"ok": True, "amount": "0", "fields": {"paypal_link": "https://pm-redirects.stripe.com/authorize/test", "cs_id": "cs_test"}, "billing": {}}

    monkeypatch.setattr(us_paypal, "generate_paypal_trial", fake_generate_paypal_trial)
    monkeypatch.setattr(us_paypal.time, "sleep", lambda _seconds: None)
    job_id = "paypal-region-attempts-job"
    us_paypal.JOBS[job_id] = {
        "id": job_id, "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 0,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {},
    }

    req = us_paypal.UsPaypalBatchStartRequest.model_validate({
        "accountEmails": [email],
        "proxies": "p",
        "region": "gb",
        "promoRegion": "vn",
        "maxAttempts": 3,
    })
    us_paypal._run_batch_job(job_id, req)

    assert captured["attempts"] == 3
    assert captured["regions"] == [("GB", "VN"), ("GB", "VN"), ("GB", "VN")]


def test_start_request_caps_configurable_attempts():
    req = us_paypal.UsPaypalBatchStartRequest.model_validate({"accountEmails": ["user@example.com"], "maxAttempts": 99})

    assert req.max_attempts == 20


def test_start_requests_default_to_apply_promo():
    single = us_paypal.UsPaypalStartRequest.model_validate({"accountEmail": "user@example.com"})
    batch = us_paypal.UsPaypalBatchStartRequest.model_validate({"accountEmails": ["user@example.com"]})

    assert single.promo_mode == "promo"
    assert batch.promo_mode == "promo"
    assert single.promo_region == "JP"
    assert batch.promo_region == "JP"


def test_start_requires_selected_account():
    app = _app()

    with pytest.raises(HTTPException) as exc:
        _endpoint(app, "/api/us-paypal/batch/start", "POST")(
            us_paypal.UsPaypalBatchStartRequest.model_validate({"accountEmails": [], "concurrency": 1})
        )

    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "bad_body"


def test_links_delete_and_clear_use_paypal_file():
    app = _app()
    us_paypal.LINKS_FILE.write_text(json.dumps([
        {"id": "keep", "paypal_link": "https://pm-redirects.stripe.com/authorize/keep"},
        {"id": "remove", "paypal_link": "https://pm-redirects.stripe.com/authorize/remove"},
    ]), encoding="utf-8")

    deleted = _endpoint(app, "/api/us-paypal/links/delete", "POST")(us_paypal.UsPaypalDeleteLinksRequest(ids=["remove", "missing"]))
    cleared = _endpoint(app, "/api/us-paypal/links/clear", "POST")()

    assert deleted["deleted"] == 1
    assert [item["id"] for item in deleted["links"]] == ["keep"]
    assert cleared == {"deleted": 1, "links": []}


def test_main_api_mounts_us_paypal_router():
    from autotoken.interfaces.api import app

    paths = {getattr(route, "path", "") for route in app.routes}

    assert "/api/us-paypal/accounts" in paths
    assert "/api/us-paypal/accounts/{email}" in paths
    assert "/api/us-paypal/batch/start" in paths
    assert "/api/us-paypal/jobs/{job_id}" in paths
    assert "/api/us-paypal/links" in paths
