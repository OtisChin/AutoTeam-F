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
                "link_source": "stripe_payment_pages_confirm",
                "link_binding": "chatgpt_checkout_session",
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
    assert saved["country"] == "US"
    assert saved["link_source"] == "stripe_payment_pages_confirm"
    assert saved["link_binding"] == "chatgpt_checkout_session"
    statuses = json.loads(us_paypal.ACCOUNT_STATUS_FILE.read_text(encoding="utf-8"))
    assert statuses[email]["status"] == "success"


def test_load_links_backfills_country_from_billing_for_old_records():
    us_paypal.LINKS_FILE.write_text(
        json.dumps(
            [
                {
                    "id": "old",
                    "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-OLD",
                    "billing": {"country": "nl"},
                }
            ]
        ),
        encoding="utf-8",
    )

    links = us_paypal._load_links()

    assert links[0]["country"] == "NL"


def test_accounts_show_country_only_for_successful_extracted_links(monkeypatch):
    app = _app()
    us_paypal.LINKS_FILE.write_text(
        json.dumps(
            [
                {
                    "id": "success-link",
                    "account_email": "success@example.com",
                    "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-SUCCESS",
                    "country": "NL",
                },
                {
                    "id": "failed-link",
                    "account_email": "failed@example.com",
                    "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-FAILED",
                    "country": "US",
                },
            ]
        ),
        encoding="utf-8",
    )
    us_paypal.ACCOUNT_STATUS_FILE.write_text(
        json.dumps({"failed@example.com": {"status": "failed", "error": "boom"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(us_paypal.account_store, "load_accounts", lambda: [])
    monkeypatch.setattr(us_paypal, "_iter_auth_accounts", lambda include_paid=False: [
        {"email": "success@example.com", "auth_file": "auth-success.json"},
        {"email": "failed@example.com", "auth_file": "auth-failed.json"},
        {"email": "pending@example.com", "auth_file": "auth-pending.json"},
    ])

    result = _endpoint(app, "/api/us-paypal/accounts", "GET")()
    rows = {row["email"]: row for row in result["accounts"]}

    assert rows["success@example.com"]["paypal_status"] == "success"
    assert rows["success@example.com"]["paypal_country"] == "NL"
    assert rows["failed@example.com"]["paypal_status"] == "failed"
    assert rows["failed@example.com"]["paypal_country"] == ""
    assert rows["pending@example.com"]["paypal_status"] == "pending"
    assert rows["pending@example.com"]["paypal_country"] == ""


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


def test_protocol_start_validates_and_starts_local_runner(monkeypatch):
    app = _app()
    captured = {}

    def fake_run(job_id, req):
        captured["job_id"] = job_id
        captured["req"] = req

    class FakeThread:
        def __init__(self, target, args, daemon):
            self.target = target
            self.args = args
            self.daemon = daemon

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(us_paypal.threading, "Thread", FakeThread)
    monkeypatch.setattr(us_paypal, "_run_protocol_payment_job", fake_run)

    result = _endpoint(app, "/api/us-paypal/protocol/start", "POST")(
        us_paypal.UsPaypalProtocolStartRequest.model_validate({
            "paypalLink": "https://www.paypal.com/agreements/approve?ba_token=BA-1ROUTE123",
            "phone": "+18350000000",
            "smsRecordUrl": "https://sms.example/api/record?token=secret",
            "proxies": "proxy.example:10000:user:pass",
            "country": "US",
        })
    )

    assert result["job_id"].startswith("ppay-")
    assert captured["job_id"] == result["job_id"]
    assert us_paypal.JOBS[result["job_id"]]["kind"] == "paypal_protocol_payment"


def test_protocol_start_allows_no_proxy_to_match_verified_runner(monkeypatch):
    app = _app()
    captured = {}

    class FakeThread:
        def __init__(self, target, args, daemon):
            self.target = target
            self.args = args
            self.daemon = daemon

        def start(self):
            captured["args"] = self.args

    monkeypatch.setattr(us_paypal.threading, "Thread", FakeThread)

    result = _endpoint(app, "/api/us-paypal/protocol/start", "POST")(
        us_paypal.UsPaypalProtocolStartRequest.model_validate({
            "paypalLink": "https://www.paypal.com/agreements/approve?ba_token=BA-1NOPROXY123",
            "phone": "+18350000000",
            "smsRecordUrl": "https://sms.example/api/record?token=secret",
            "country": "US",
        })
    )

    assert result["job_id"].startswith("ppay-")
    assert captured["args"][0] == result["job_id"]
    assert captured["args"][1].proxies == ""


def test_protocol_start_allows_herosms_without_fixed_sms_record(monkeypatch):
    app = _app()
    captured = {}

    class FakeThread:
        def __init__(self, target, args, daemon):
            self.target = target
            self.args = args
            self.daemon = daemon

        def start(self):
            captured["args"] = self.args

    monkeypatch.setattr(us_paypal.threading, "Thread", FakeThread)

    result = _endpoint(app, "/api/us-paypal/protocol/start", "POST")(
        us_paypal.UsPaypalProtocolStartRequest.model_validate({
            "paypalLink": "https://www.paypal.com/agreements/approve?ba_token=BA-1HEROROUTE123",
            "smsProvider": "hero-sms",
            "smsApiKey": "hero-secret",
            "smsService": "ts",
            "smsCountry": "187",
            "country": "US",
        })
    )

    assert result["job_id"].startswith("ppay-")
    assert captured["args"][1].sms_provider == "hero_sms"


def test_protocol_start_allows_gb_country(monkeypatch):
    app = _app()
    captured = {}

    class FakeThread:
        def __init__(self, target, args, daemon):
            self.target = target
            self.args = args
            self.daemon = daemon

        def start(self):
            captured["args"] = self.args

    monkeypatch.setattr(us_paypal.threading, "Thread", FakeThread)

    result = _endpoint(app, "/api/us-paypal/protocol/start", "POST")(
        us_paypal.UsPaypalProtocolStartRequest.model_validate({
            "paypalLink": "https://www.paypal.com/agreements/approve?ba_token=BA-1GBROUTE123",
            "smsProvider": "smsbower",
            "smsCountry": "16",
            "country": "GB",
        })
    )

    assert result["job_id"].startswith("ppay-")
    assert captured["args"][1].country == "GB"
    assert captured["args"][1].sms_provider == "smsbower"


def test_protocol_job_uses_local_runner_and_sanitizes_logs(monkeypatch):
    captured = {}
    job_id = us_paypal._new_protocol_job("buyer@example.com")

    def fake_runner(cfg, log, cancel_check):
        captured["cfg"] = cfg
        log("opened BA-1ROUTE123 with https://sms.example/api?token=secret via socks5h://u:p@proxy")
        assert cancel_check() is False
        captured["sms_wait"] = cfg.sms_record_wait_seconds
        captured["sms_poll"] = cfg.sms_record_poll_seconds
        return {"status": "success", "protocol_result": {"status": "success"}}

    monkeypatch.setattr(us_paypal, "run_paypal_protocol_payment", fake_runner)
    monkeypatch.setattr(us_paypal, "_mark_account_plus_paypal", lambda email, message: captured.setdefault("marked", (email, message)))
    monkeypatch.setattr(us_paypal, "_set_account_status", lambda email, status, **kwargs: captured.setdefault("status", (email, status)) or {"status": status})

    req = us_paypal.UsPaypalProtocolStartRequest.model_validate({
        "baToken": "BA-1ROUTE123",
        "phone": "+18350000000",
        "smsRecordUrl": "https://sms.example/api/record?token=secret",
        "proxyUrl": "proxy.example:10000:user:pass",
        "accountEmail": "buyer@example.com",
        "smsRecordWaitSeconds": 600,
        "smsRecordPollSeconds": 2,
    })
    us_paypal._run_protocol_payment_job(job_id, req)

    job = us_paypal.JOBS[job_id]
    assert job["status"] == "success"
    assert captured["cfg"].country == "US"
    assert captured["cfg"].proxy_url.startswith("socks5h://")
    assert captured["sms_wait"] == 600
    assert captured["sms_poll"] == 2
    assert captured["marked"][0] == "buyer@example.com"
    assert all("token=secret" not in line for line in job["logs"])
    assert all("u:p@" not in line for line in job["logs"])


def test_protocol_job_ignores_frontend_sms_provider_overrides(monkeypatch):
    captured = {}
    job_id = us_paypal._new_protocol_job("")

    def fake_runner(cfg, log, cancel_check):
        captured["cfg"] = cfg
        return {"status": "success", "protocol_result": {"status": "success"}}

    monkeypatch.setattr(us_paypal, "run_paypal_protocol_payment", fake_runner)

    req = us_paypal.UsPaypalProtocolStartRequest.model_validate({
        "baToken": "BA-1IGNOREOVERRIDE123",
        "smsProvider": "hero-sms",
        "smsApiKey": "frontend-secret",
        "smsBaseUrl": "https://frontend.invalid/stubs/handler_api.php",
        "smsService": "bad-service",
        "smsCountry": "999",
        "smsMinPrice": "0.01",
        "smsMaxPrice": "9.99",
        "smsPreferredPrice": "1.23",
        "country": "GB",
    })
    us_paypal._run_protocol_payment_job(job_id, req)

    cfg = captured["cfg"]
    assert cfg.sms_provider == "hero_sms"
    assert cfg.country == "GB"
    assert cfg.sms_api_key == ""
    assert cfg.sms_base_url == ""
    assert cfg.sms_service == ""
    assert cfg.sms_country == ""
    assert cfg.sms_min_price == ""
    assert cfg.sms_max_price == ""
    assert cfg.sms_preferred_price == ""


def test_main_api_mounts_us_paypal_protocol_routes():
    from autotoken.interfaces.api import app

    paths = {getattr(route, "path", "") for route in app.routes}

    assert "/api/us-paypal/protocol/start" in paths
    assert "/api/us-paypal/protocol/jobs/{job_id}" in paths
