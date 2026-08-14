from __future__ import annotations

import json

import pytest
from fastapi import FastAPI, HTTPException

from autotoken.api_routes import us_paypal
from autotoken.services import proxy_runtime


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
    monkeypatch.setattr(us_paypal, "PAY153_REMOTE_TASKS_FILE", tmp_path / "us_paypal_pay153_remote_tasks.json")
    monkeypatch.setattr(us_paypal.account_store, "ACCOUNTS_FILE", tmp_path / "accounts.json")
    monkeypatch.setattr(us_paypal.pix_routes, "AUTH_SESSION_DIR", tmp_path / "auth_session")
    monkeypatch.setattr("autotoken.storage.auth_session_store.AUTH_SESSION_DIR", tmp_path / "auth_session")
    monkeypatch.setattr(proxy_runtime, "preflight_payment_proxy_url", lambda proxy_url: (True, "HTTP 200"))
    monkeypatch.setattr(proxy_runtime, "preflight_chatgpt_authenticated_proxy_url", lambda proxy_url, access_token: (True, "auth_api HTTP 200"))
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


def test_paypal_link_batch_concurrency_allows_thirty():
    req = us_paypal.UsPaypalBatchStartRequest.model_validate({"accountEmails": [], "concurrency": 99})

    assert us_paypal._batch_concurrency(req, total=40) == 30


def test_paypal_proxy_preflight_attempts_cap_at_one_hundred():
    link_req = us_paypal.UsPaypalBatchStartRequest.model_validate({"accountEmails": [], "proxyPreflightAttempts": 200})
    protocol_req = us_paypal.UsPaypalProtocolStartRequest.model_validate({"proxyPreflightAttempts": 200})

    assert link_req.proxy_preflight_attempts == 100
    assert protocol_req.proxy_preflight_attempts == 100


def test_paypal_protocol_batch_concurrency_stays_capped_at_ten():
    req = us_paypal.UsPaypalProtocolBatchStartRequest.model_validate({"accountEmails": [], "concurrency": 25})

    assert us_paypal._protocol_batch_concurrency(req, total=30) == 10


def test_batch_account_preflights_proxy_before_paypal_generation(monkeypatch):
    email = "blocked@example.com"
    preflighted: list[str] = []
    monkeypatch.setattr(us_paypal, "_load_token_for_email", lambda value: "token-" + value)

    def fake_preflight(proxy_url):
        preflighted.append(proxy_url)
        return (False, "ProxyError: ruleset blocked")

    monkeypatch.setattr(proxy_runtime, "preflight_payment_proxy_url", fake_preflight)
    monkeypatch.setattr(us_paypal, "generate_paypal_trial", lambda cfg, log: pytest.fail("should not generate when proxy preflight fails"))
    job_id = "paypal-preflight-job"
    us_paypal.JOBS[job_id] = {
        "id": job_id, "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 1,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {},
    }

    req = us_paypal.UsPaypalBatchStartRequest.model_validate({
        "accountEmails": [email],
        "proxies": "global.rotgb.711proxy.com:10000:USER-zone-custom-region-US-session-fixed-sessTime-120-sessAuto-1:pass",
        "region": "NL",
        "maxAttempts": 5,
    })
    result = us_paypal._run_batch_account(
        job_id,
        req,
        {"email": email, "auth_file": "auth.json"},
        1,
        1,
        us_paypal._parse_proxies(req.proxies),
    )

    assert result["ok"] is False
    assert len(preflighted) == 10
    assert "代理预检失败" in result["error"]["error"]
    assert "ruleset blocked" in result["error"]["error"]
    assert any("代理预检失败" in line for line in us_paypal.JOBS[job_id]["logs"])


def test_batch_account_uses_configured_proxy_preflight_attempts(monkeypatch):
    email = "blocked-configured@example.com"
    preflighted: list[str] = []
    monkeypatch.setattr(us_paypal, "_load_token_for_email", lambda value: "token-" + value)

    def fake_preflight(proxy_url):
        preflighted.append(proxy_url)
        return (False, "ProxyError: ruleset blocked")

    monkeypatch.setattr(proxy_runtime, "preflight_payment_proxy_url", fake_preflight)
    monkeypatch.setattr(us_paypal, "generate_paypal_trial", lambda cfg, log: pytest.fail("should not generate when proxy preflight fails"))
    job_id = "paypal-configured-preflight-job"
    us_paypal.JOBS[job_id] = {
        "id": job_id, "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 1,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {},
    }

    req = us_paypal.UsPaypalBatchStartRequest.model_validate({
        "accountEmails": [email],
        "proxies": "proxy.example:1000:user-region-US-sid-old-t-120:pass",
        "region": "GB",
        "maxAttempts": 5,
        "proxyPreflightAttempts": 3,
    })
    result = us_paypal._run_batch_account(job_id, req, {"email": email}, 1, 1, us_paypal._parse_proxies(req.proxies))

    assert result["ok"] is False
    assert len(preflighted) == 3
    assert any("目标国家代理预检开始：3/3" in line for line in us_paypal.JOBS[job_id]["logs"])


def test_batch_account_auth_preflight_blocks_paypal_generation(monkeypatch):
    email = "auth-blocked@example.com"
    monkeypatch.setattr(us_paypal, "_load_token_for_email", lambda value: "token-" + value)
    monkeypatch.setattr(proxy_runtime, "preflight_payment_proxy_url", lambda proxy_url: (True, "trace HTTP 200; chatgpt_home HTTP 200"))
    monkeypatch.setattr(proxy_runtime, "preflight_chatgpt_authenticated_proxy_url", lambda proxy_url, access_token: (False, "auth_api HTTP 403; html_challenge"))
    monkeypatch.setattr(us_paypal, "generate_paypal_trial", lambda cfg, log: pytest.fail("should not generate when authenticated proxy preflight fails"))
    job_id = "paypal-auth-preflight-job"
    us_paypal.JOBS[job_id] = {
        "id": job_id, "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 1,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {},
    }

    req = us_paypal.UsPaypalBatchStartRequest.model_validate({
        "accountEmails": [email],
        "proxies": "proxy.example:1000:user-region-GB-sid-old-t-120:pass",
        "region": "GB",
        "maxAttempts": 5,
    })
    result = us_paypal._run_batch_account(job_id, req, {"email": email}, 1, 1, us_paypal._parse_proxies(req.proxies))

    assert result["ok"] is False
    assert "auth_api HTTP 403" in result["error"]["error"]
    assert any("认证接口预检失败" in line for line in us_paypal.JOBS[job_id]["logs"])


def test_paypal_proxy_preflight_has_separate_ten_attempt_budget(monkeypatch):
    email = "preflight-ok@example.com"
    captured = {}
    preflighted: list[str] = []
    monkeypatch.setattr(us_paypal, "_load_token_for_email", lambda value: "token-" + value)

    def fake_preflight(proxy_url):
        preflighted.append(proxy_url)
        return (len(preflighted) == 10, "HTTP 200" if len(preflighted) == 10 else "ProxyError: ruleset blocked")

    def fake_generate_paypal_trial(cfg, log):
        captured["cfg"] = cfg
        return {
            "ok": True,
            "amount": "0",
            "fields": {
                "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-PREFLIGHT",
                "ba_token": "BA-PREFLIGHT",
                "cs_id": "cs_test",
                "billing": {"country": "NL"},
            },
            "billing": {"country": "NL"},
        }

    monkeypatch.setattr(proxy_runtime, "preflight_payment_proxy_url", fake_preflight)
    monkeypatch.setattr(us_paypal, "generate_paypal_trial", fake_generate_paypal_trial)
    job_id = "paypal-preflight-ok-job"
    us_paypal.JOBS[job_id] = {
        "id": job_id, "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 1,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {},
    }

    req = us_paypal.UsPaypalBatchStartRequest.model_validate({
        "accountEmails": [email],
        "proxies": "\n".join([
            "proxy1.example:1000:user-region-US-sid-old1-t-120:pass",
            "proxy2.example:1000:user-region-US-sid-old2-t-120:pass",
            "proxy3.example:1000:user-region-US-sid-old3-t-120:pass",
            "proxy4.example:1000:user-region-US-sid-old4-t-120:pass",
            "proxy5.example:1000:user-region-US-sid-old5-t-120:pass",
            "proxy6.example:1000:user-region-US-sid-old6-t-120:pass",
        ]),
        "region": "NL",
        "promoMode": "skip",
        "maxAttempts": 1,
    })
    result = us_paypal._run_batch_account(job_id, req, {"email": email}, 1, 1, us_paypal._parse_proxies(req.proxies))

    assert result["ok"] is True
    assert len(preflighted) == 10
    assert "proxy4.example" in captured["cfg"].direct_proxies[0]
    assert us_paypal.build_paypal_dynamic_proxy(captured["cfg"], 0, "NL")[0] == preflighted[-1]
    assert any("proxy6.example" in proxy for proxy in preflighted)


def test_paypal_preflights_promo_region_before_generation(monkeypatch):
    email = "promo-preflight@example.com"
    preflighted: list[str] = []
    captured = {}
    monkeypatch.setattr(us_paypal, "_load_token_for_email", lambda value: "token-" + value)

    def fake_preflight(proxy_url):
        preflighted.append(proxy_url)
        return (True, "HTTP 200")

    def fake_generate_paypal_trial(cfg, log):
        captured["cfg"] = cfg
        return {
            "ok": True,
            "amount": "0",
            "fields": {
                "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-PROMO-PREFLIGHT",
                "ba_token": "BA-PROMO-PREFLIGHT",
                "cs_id": "cs_test",
                "billing": {"country": "US"},
            },
            "billing": {"country": "US"},
        }

    monkeypatch.setattr(proxy_runtime, "preflight_payment_proxy_url", fake_preflight)
    monkeypatch.setattr(us_paypal, "generate_paypal_trial", fake_generate_paypal_trial)
    job_id = "paypal-promo-preflight-job"
    us_paypal.JOBS[job_id] = {
        "id": job_id, "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 1,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {},
    }

    req = us_paypal.UsPaypalBatchStartRequest.model_validate({
        "accountEmails": [email],
        "proxies": "proxy.example:1000:user-region-US-sid-old-t-120:pass",
        "region": "US",
        "promoRegion": "JP",
        "promoMode": "promo",
        "maxAttempts": 1,
    })
    result = us_paypal._run_batch_account(job_id, req, {"email": email}, 1, 1, us_paypal._parse_proxies(req.proxies))

    assert result["ok"] is True
    assert any("-region-US-sid-" in proxy for proxy in preflighted)
    assert any("-region-JP-sid-" in proxy for proxy in preflighted)
    assert captured["cfg"].preflighted_promo_proxy_url
    assert us_paypal.build_paypal_dynamic_proxy(captured["cfg"], 2, "JP")[0] == captured["cfg"].preflighted_promo_proxy_url
    assert any("优惠区代理预检通过" in line for line in us_paypal.JOBS[job_id]["logs"])


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


def test_link_record_uses_target_region_and_three_hour_expiry(monkeypatch):
    monkeypatch.setattr(us_paypal.time, "time", lambda: 1_785_600_000.0)
    monkeypatch.setattr(us_paypal.time, "strftime", lambda fmt: "2026-08-09 05:00:00")

    record = us_paypal._link_record_from_result(
        "job-target-country",
        "target@example.com",
        {
            "fields": {
                "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-TARGET",
                "country": "DE",
                "billing": {"country": "DE"},
            },
        },
        target_country="TH",
    )

    assert record["country"] == "TH"
    assert record["target_country"] == "TH"
    assert record["created_at_ts"] == 1_785_600_000.0
    assert record["paypal_expires_at_ts"] == 1_785_600_000.0 + 3 * 3600


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


def test_start_request_parses_only_oaics_flag():
    req = us_paypal.UsPaypalBatchStartRequest.model_validate({"accountEmails": ["user@example.com"], "onlyOaics": True})

    assert req.only_oaics is True


def test_batch_account_maps_only_oaics_cs_checkout_to_skipped(monkeypatch):
    email = "cs-skip@example.com"
    captured = {}
    monkeypatch.setattr(us_paypal, "_load_token_for_email", lambda _email: "token")

    def fake_generate_paypal_trial(cfg, log):
        captured["only_oaics"] = cfg.only_oaics
        raise us_paypal.PaypalOnlyOaicsSkipped("非 OAICS checkout，已跳过: cs_live_skip")

    monkeypatch.setattr(us_paypal, "generate_paypal_trial", fake_generate_paypal_trial)
    job_id = "paypal-only-oaics-skip-job"
    us_paypal.JOBS[job_id] = {
        "id": job_id, "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 1,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {},
    }

    req = us_paypal.UsPaypalBatchStartRequest.model_validate({
        "accountEmails": [email],
        "proxies": "proxy.example:1000:user-region-BR-sid-old-t-120:pass",
        "region": "BR",
        "promoMode": "promo",
        "onlyOaics": True,
    })
    result = us_paypal._run_batch_account(job_id, req, {"email": email}, 1, 1, us_paypal._parse_proxies(req.proxies))

    assert captured["only_oaics"] is True
    assert result["skipped"] is True
    assert result["reason"] == "非 OAICS checkout，已跳过"
    assert result["status"]["status"] == "non_oaics"
    assert result["status"]["status_text"] == "非Oaics"
    statuses = json.loads(us_paypal.ACCOUNT_STATUS_FILE.read_text(encoding="utf-8"))
    assert statuses[email]["status"] == "non_oaics"


def test_accounts_show_non_oaics_paypal_status(monkeypatch):
    email = "non-oaics@example.com"
    us_paypal.ACCOUNT_STATUS_FILE.write_text(
        json.dumps({email: {"status": "non_oaics", "error": ""}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(us_paypal.account_store, "load_accounts", lambda: [])
    monkeypatch.setattr(us_paypal, "_iter_auth_accounts", lambda include_paid=False: [
        {"email": email, "auth_file": "auth.json"},
    ])

    result = _endpoint(_app(), "/api/us-paypal/accounts", "GET")()

    assert result["accounts"][0]["paypal_status"] == "non_oaics"
    assert result["accounts"][0]["paypal_status_text"] == "非Oaics"


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


def test_accounts_show_no_promo_paypal_status(monkeypatch):
    app = _app()
    email = "nopromo@example.com"
    us_paypal.ACCOUNT_STATUS_FILE.write_text(
        json.dumps({email: {"status": "no_promo", "error": "PayPal 金额非 0"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(us_paypal.account_store, "load_accounts", lambda: [])
    monkeypatch.setattr(us_paypal, "_iter_auth_accounts", lambda include_paid=False: [
        {"email": email, "auth_file": "auth.json"},
    ])

    result = _endpoint(app, "/api/us-paypal/accounts", "GET")()

    assert result["accounts"][0]["paypal_status"] == "no_promo"
    assert result["accounts"][0]["paypal_status_text"] == "无优惠"


def test_batch_account_marks_paypal_nonzero_amount_as_no_promo_skip(monkeypatch):
    email = "AngelesGuttman0186@outlook.com"
    deleted_accounts: list[str] = []
    deleted_sessions: list[str] = []
    monkeypatch.setattr(us_paypal, "_load_token_for_email", lambda _email: "token")
    monkeypatch.setattr(us_paypal, "generate_paypal_trial", lambda cfg, log: (_ for _ in ()).throw(RuntimeError("金额必须为 0: 1667")))
    monkeypatch.setattr(us_paypal.account_store, "delete_account", lambda value: deleted_accounts.append(value) or True)
    monkeypatch.setattr(us_paypal, "delete_auth_session", lambda value: deleted_sessions.append(value) or True)
    job_id = "paypal-nonzero-job"
    us_paypal.JOBS[job_id] = {
        "id": job_id, "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 1,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {},
    }

    req = us_paypal.UsPaypalBatchStartRequest.model_validate({
        "accountEmails": [email],
        "proxies": "proxy.example:1000:user-region-GB-sid-old-t-120:pass",
        "region": "GB",
        "promoMode": "promo",
        "maxAttempts": 5,
    })
    result = us_paypal._run_batch_account(job_id, req, {"email": email}, 1, 1, us_paypal._parse_proxies(req.proxies))

    assert result["skipped"] is True
    assert result["reason"].startswith("账号无优惠")
    assert result["status"]["status"] == "no_promo"
    assert result.get("account_deleted") is not True
    assert deleted_accounts == []
    assert deleted_sessions == []
    statuses = json.loads(us_paypal.ACCOUNT_STATUS_FILE.read_text(encoding="utf-8"))
    assert statuses[email.lower()]["status"] == "no_promo"


def test_batch_job_excludes_paypal_nonzero_amount_from_retry_errors(monkeypatch):
    email = "nopromo-batch@example.com"
    monkeypatch.setattr(us_paypal, "_iter_auth_accounts", lambda include_paid=False: [{"email": email, "auth_file": "auth.json"}])
    monkeypatch.setattr(us_paypal, "_load_token_for_email", lambda _email: "token")
    monkeypatch.setattr(us_paypal, "generate_paypal_trial", lambda cfg, log: (_ for _ in ()).throw(RuntimeError("PayPal 金额必须为 0: 1667")))
    job_id = "paypal-nonzero-batch-job"
    us_paypal.JOBS[job_id] = {
        "id": job_id, "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 0,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {},
    }

    req = us_paypal.UsPaypalBatchStartRequest.model_validate({
        "accountEmails": [email],
        "proxies": "proxy.example:1000:user-region-BR-sid-old-t-120:pass",
        "region": "BR",
        "promoMode": "promo",
        "maxAttempts": 5,
    })
    us_paypal._run_batch_job(job_id, req)

    job = us_paypal.JOBS[job_id]
    assert job["status"] == "success"
    assert job["result"]["errors"] == []
    assert job["result"]["skipped"] == [{"email": email, "reason": "账号无优惠，账单金额非 0"}]
    assert job["account_statuses"][email]["status"] == "no_promo"


def test_protocol_batch_job_assigns_account_link_phone_and_proxy(monkeypatch):
    us_paypal.LINKS_FILE.write_text(
        json.dumps(
            [
                {
                    "account_email": "gb@example.com",
                    "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-GB12345",
                    "country": "GB",
                },
                {
                    "account_email": "nl@example.com",
                    "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-NL12345",
                    "country": "NL",
                },
            ]
        ),
        encoding="utf-8",
    )
    captured = []

    def fake_run(cfg, log, cancel_check):
        captured.append(cfg)
        log(f"paid {cfg.ba_token}")
        return {"status": "success", "ba_token": cfg.ba_token}

    monkeypatch.setattr(us_paypal, "run_paypal_protocol_payment", fake_run)
    monkeypatch.setattr(us_paypal, "_mark_account_plus_paypal", lambda email, message="": {"email": email})
    job_id = us_paypal._new_protocol_batch_job(["gb@example.com", "nl@example.com"], concurrency=2)
    req = us_paypal.UsPaypalProtocolBatchStartRequest.model_validate({
        "accountEmails": ["gb@example.com", "nl@example.com"],
        "smsProvider": "hero_sms_rent",
        "phone": "+447700900111\n+31612345678",
        "proxies": "proxy1.example:1000:user1:pass1\nproxy2.example:1000:user2:pass2",
        "concurrency": 2,
    })

    us_paypal._run_protocol_batch_payment_job(job_id, req)

    assert us_paypal.JOBS[job_id]["status"] == "success"
    assert us_paypal.JOBS[job_id]["completed"] == 2
    assert [cfg.ba_token for cfg in captured] == ["BA-GB12345", "BA-NL12345"]
    assert [cfg.country for cfg in captured] == ["GB", "NL"]
    assert [cfg.phone for cfg in captured] == ["+447700900111", "+31612345678"]
    assert captured[0].proxy_url == "socks5h://user1:pass1@proxy1.example:1000"
    assert captured[1].proxy_url == "socks5h://user2:pass2@proxy2.example:1000"


def test_protocol_batch_sms_record_phone_pool_assigns_unique_numbers_concurrently(monkeypatch):
    us_paypal.LINKS_FILE.write_text(
        json.dumps(
            [
                {"account_email": "a@example.com", "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-A12345", "country": "GB"},
                {"account_email": "b@example.com", "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-B12345", "country": "GB"},
            ]
        ),
        encoding="utf-8",
    )
    captured = []

    def fake_run(cfg, log, cancel_check):
        captured.append((cfg.phone, cfg.sms_record_url, cfg.ba_token))
        return {"status": "success"}

    monkeypatch.setattr(us_paypal, "run_paypal_protocol_payment", fake_run)
    monkeypatch.setattr(us_paypal, "_mark_account_plus_paypal", lambda email, message="": {"email": email})
    monkeypatch.setattr(us_paypal, "_preflight_protocol_proxy_or_raise", lambda proxies, country, log, attempts: "")

    job_id = us_paypal._new_protocol_batch_job(["a@example.com", "b@example.com"], concurrency=2)
    req = us_paypal.UsPaypalProtocolBatchStartRequest.model_validate({
        "accountEmails": ["a@example.com", "b@example.com"],
        "smsProvider": "sms_record",
        "phonePool": "+447383370667----https://api.sms8.net/api/record?token=one\n+447383370668----https://api.sms8.net/api/record?token=two",
        "concurrency": 2,
    })

    us_paypal._run_protocol_batch_payment_job(job_id, req)

    assigned = sorted((phone, url) for phone, url, _ba in captured)
    assert assigned == [
        ("+447383370667", "https://api.sms8.net/api/record?token=one"),
        ("+447383370668", "https://api.sms8.net/api/record?token=two"),
    ]
    assert us_paypal.JOBS[job_id]["status"] == "success"


def test_protocol_batch_job_marks_account_running_before_runner(monkeypatch):
    email = "running-protocol@example.com"
    us_paypal.LINKS_FILE.write_text(
        json.dumps(
            [
                {
                    "account_email": email,
                    "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-RUNNING123",
                    "country": "GB",
                },
            ]
        ),
        encoding="utf-8",
    )

    job_id = us_paypal._new_protocol_batch_job([email], concurrency=1)

    def fake_run(cfg, log, cancel_check):
        assert us_paypal.JOBS[job_id]["account_statuses"][email]["status"] == us_paypal.PAYPAL_STATUS_RUNNING
        return {"status": "success"}

    monkeypatch.setattr(us_paypal, "run_paypal_protocol_payment", fake_run)
    monkeypatch.setattr(us_paypal, "_mark_account_plus_paypal", lambda email, message="": {"email": email})
    monkeypatch.setattr(us_paypal, "_preflight_protocol_proxy_or_raise", lambda proxies, country, log, attempts: "")

    req = us_paypal.UsPaypalProtocolBatchStartRequest.model_validate({
        "accountEmails": [email],
        "smsProvider": "hero_sms",
        "concurrency": 1,
    })

    us_paypal._run_protocol_batch_payment_job(job_id, req)

    assert us_paypal.JOBS[job_id]["status"] == "success"


def test_protocol_batch_start_rejects_rent_payment_when_phone_count_is_short():
    us_paypal.LINKS_FILE.write_text(
        json.dumps(
            [
                {"account_email": "a@example.com", "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-A12345", "country": "GB"},
                {"account_email": "b@example.com", "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-B12345", "country": "GB"},
            ]
        ),
        encoding="utf-8",
    )
    app = _app()
    endpoint = _endpoint(app, "/api/us-paypal/protocol/batch/start", "POST")
    req = us_paypal.UsPaypalProtocolBatchStartRequest.model_validate({
        "accountEmails": ["a@example.com", "b@example.com"],
        "smsProvider": "hero_sms_rent",
        "phone": "+447700900111",
    })

    with pytest.raises(HTTPException) as exc:
        endpoint(req)

    assert exc.value.status_code == 400
    assert "每个账号" in exc.value.detail["message"]


def test_pay153_batch_job_assigns_account_link_phone_country_and_proxy(monkeypatch):
    us_paypal.LINKS_FILE.write_text(
        json.dumps(
            [
                {
                    "account_email": "gb@example.com",
                    "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-A12345",
                    "country": "GB",
                },
                {
                    "account_email": "id@example.com",
                    "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-B12345",
                    "country": "ID",
                },
            ]
        ),
        encoding="utf-8",
    )
    captured_create_payloads = []

    def fake_create_job(paypal_url, phone, country, proxies, buyer_mode, client=None):
        captured_create_payloads.append(
            {
                "paypal_url": paypal_url,
                "phone": phone,
                "country": country,
                "proxies": proxies,
                "buyer_mode": buyer_mode,
            }
        )
        return {
            "job": {
                "id": f"remote-{country.lower()}",
                "status": "completed",
                "stage": "done",
                "logs": [f"completed {country}"],
                "result": {"status": "success", "ba_token": us_paypal.extract_protocol_ba_token(paypal_url), "billing_country": country},
            }
        }

    monkeypatch.setattr(us_paypal, "_pay153_create_job", fake_create_job)
    monkeypatch.setattr(us_paypal, "_pay153_get_job", lambda remote_job_id, client=None: {"id": remote_job_id, "status": "completed", "stage": "done", "logs": [], "result": {"status": "success"}})
    monkeypatch.setattr(us_paypal, "_mark_account_plus_paypal", lambda email, message="": {"email": email})
    job_id = us_paypal._new_pay153_batch_job(["gb@example.com", "id@example.com"], concurrency=2)
    req = us_paypal.UsPaypal153BatchStartRequest.model_validate({
        "accountEmails": ["gb@example.com", "id@example.com"],
        "phone": "+447700900001\n+6281234567890",
        "smsRecordUrl": "https://sms.example/gb\nhttps://sms.example/id",
        "proxies": "proxy-one\nproxy-two",
        "buyerMode": "identity_elevation",
        "concurrency": 2,
    })

    us_paypal._run_pay153_batch_payment_job(job_id, req)

    assert us_paypal.JOBS[job_id]["status"] == "success"
    assert us_paypal.JOBS[job_id]["completed"] == 2
    assert captured_create_payloads[0]["paypal_url"].endswith("BA-A12345")
    assert captured_create_payloads[0]["phone"] == "+447700900001"
    assert captured_create_payloads[0]["country"] == "GB"
    assert captured_create_payloads[0]["proxies"] == ["proxy-one", "proxy-two"]
    assert captured_create_payloads[0]["buyer_mode"] == "identity_elevation"
    statuses = json.loads(us_paypal.ACCOUNT_STATUS_FILE.read_text(encoding="utf-8"))
    assert statuses["gb@example.com"]["status"] == "paid"
    assert statuses["id@example.com"]["status"] == "paid"


def test_pay153_batch_job_marks_account_running_before_remote_create(monkeypatch):
    email = "running-pay153@example.com"
    us_paypal.LINKS_FILE.write_text(
        json.dumps(
            [
                {
                    "account_email": email,
                    "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-153RUNNING123",
                    "country": "TH",
                },
            ]
        ),
        encoding="utf-8",
    )

    class FakeActivation:
        phone_number = "+66812345678"

    class FakeOtpProvider:
        def reserve_number(self):
            return FakeActivation()

        def register_confirmation_result(self, activation, confirmed):
            return None

    job_id = us_paypal._new_pay153_batch_job([email], concurrency=1)

    def fake_create_job(paypal_url, phone, country, proxies, buyer_mode, client=None):
        assert us_paypal.JOBS[job_id]["account_statuses"][email]["status"] == us_paypal.PAYPAL_STATUS_RUNNING
        return {"job": {"id": "remote-running", "status": "completed", "stage": "done", "logs": [], "result": {"status": "success"}}}

    monkeypatch.setattr(us_paypal, "_build_pay153_otp_provider", lambda sms_provider, phone, country, req: FakeOtpProvider())
    monkeypatch.setattr(us_paypal, "_pay153_create_job", fake_create_job)
    monkeypatch.setattr(us_paypal, "_pay153_get_job", lambda remote_job_id, client=None: {"id": remote_job_id, "status": "completed", "stage": "done", "logs": [], "result": {"status": "success"}})
    monkeypatch.setattr(us_paypal, "_mark_account_plus_paypal", lambda email, message="": {"email": email})

    req = us_paypal.UsPaypal153BatchStartRequest.model_validate({
        "accountEmails": [email],
        "smsProvider": "hero_sms",
        "proxies": "proxy-one",
        "buyerMode": "identity_elevation",
        "concurrency": 1,
    })

    us_paypal._run_pay153_batch_payment_job(job_id, req)

    assert us_paypal.JOBS[job_id]["status"] == "success"


def test_pay153_batch_account_retries_failed_payment_three_times_then_succeeds(monkeypatch):
    create_attempts = []
    reserved_numbers = []

    class FakeActivation:
        def __init__(self, phone):
            self.phone_number = phone

    class FakeOtpProvider:
        def reserve_number(self):
            phone = f"+44770090000{len(reserved_numbers) + 1}"
            reserved_numbers.append(phone)
            return FakeActivation(phone)

        def register_confirmation_result(self, activation, confirmed):
            return None

        def abandon(self, activation, reason):
            return None

    def fake_create_job(paypal_url, phone, country, proxies, buyer_mode, client=None):
        create_attempts.append(phone)
        if len(create_attempts) < 4:
            return {
                "job": {
                    "id": f"remote-retry-{len(create_attempts)}",
                    "status": "failed",
                    "stage": "AUTHORIZE_EMPTY",
                    "error": "AUTHORIZE_EMPTY",
                    "logs": [],
                    "result": {"status": "failed"},
                }
            }
        return {
            "job": {
                "id": "remote-retry-success",
                "status": "completed",
                "stage": "done",
                "logs": [],
                "result": {"status": "success"},
            }
        }

    monkeypatch.setattr(us_paypal, "_build_pay153_otp_provider", lambda sms_provider, phone, country, req: FakeOtpProvider())
    monkeypatch.setattr(us_paypal, "_pay153_create_job", fake_create_job)
    monkeypatch.setattr(us_paypal, "_mark_account_plus_paypal", lambda email, message="": {"email": email})
    monkeypatch.setattr(us_paypal.time, "sleep", lambda seconds: None)

    job_id = us_paypal._new_pay153_batch_job(["gb@example.com"], concurrency=1)
    req = us_paypal.UsPaypal153BatchStartRequest.model_validate({
        "accountEmails": ["gb@example.com"],
        "smsProvider": "hero_sms",
        "country": "GB",
        "proxies": "proxy-one",
    })

    result = us_paypal._run_pay153_batch_account(
        job_id,
        req,
        {
            "email": "gb@example.com",
            "ba_token": "BA-A12345",
            "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-A12345",
            "country": "GB",
        },
        1,
        1,
        [],
        ["proxy-one"],
    )

    assert result["ok"] is True
    assert create_attempts == ["+447700900001", "+447700900002", "+447700900003", "+447700900004"]
    assert reserved_numbers == create_attempts
    assert json.loads(us_paypal.ACCOUNT_STATUS_FILE.read_text(encoding="utf-8"))["gb@example.com"]["status"] == "paid"
    logs = "\n".join(us_paypal.JOBS[job_id]["logs"])
    assert "153支付失败，准备重试 1/3" in logs
    assert "153支付失败，准备重试 2/3" in logs
    assert "153支付失败，准备重试 3/3" in logs


def test_pay153_sms_record_phone_pool_import_assigns_unique_numbers_concurrently(monkeypatch):
    us_paypal.LINKS_FILE.write_text(
        json.dumps(
            [
                {"account_email": "a@example.com", "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-A12345", "country": "GB"},
                {"account_email": "b@example.com", "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-B12345", "country": "GB"},
            ]
        ),
        encoding="utf-8",
    )
    captured_create_payloads = []
    provider_urls = []

    def fake_create_job(paypal_url, phone, country, proxies, buyer_mode, client=None):
        captured_create_payloads.append({"ba": us_paypal.extract_protocol_ba_token(paypal_url), "phone": phone, "country": country})
        return {"job": {"id": f"remote-{phone[-3:]}", "status": "completed", "stage": "done", "logs": [], "result": {"status": "success"}}}

    def fake_build_provider(sms_provider, phone, country, req):
        provider_urls.append((phone, req.sms_record_url))

        class FakeActivation:
            phone_number = phone

        class FakeProvider:
            def reserve_number(self):
                return FakeActivation()

        return FakeProvider()

    monkeypatch.setattr(us_paypal, "_pay153_create_job", fake_create_job)
    monkeypatch.setattr(us_paypal, "_build_pay153_otp_provider", fake_build_provider)
    monkeypatch.setattr(us_paypal, "_mark_account_plus_paypal", lambda email, message="": {"email": email})

    job_id = us_paypal._new_pay153_batch_job(["a@example.com", "b@example.com"], concurrency=2)
    req = us_paypal.UsPaypal153BatchStartRequest.model_validate({
        "accountEmails": ["a@example.com", "b@example.com"],
        "smsProvider": "sms_record",
        "phonePool": "+447383370667----https://api.sms8.net/api/record?token=one\n+447383370668----https://api.sms8.net/api/record?token=two",
        "proxies": "proxy-one",
        "concurrency": 2,
    })

    us_paypal._run_pay153_batch_payment_job(job_id, req)

    phones = sorted(item["phone"] for item in captured_create_payloads)
    assert phones == ["+447383370667", "+447383370668"]
    assert sorted(provider_urls) == [
        ("+447383370667", "https://api.sms8.net/api/record?token=one"),
        ("+447383370668", "https://api.sms8.net/api/record?token=two"),
    ]
    assert us_paypal.JOBS[job_id]["status"] == "success"
    result_successes = sorted(us_paypal.JOBS[job_id]["result"]["successes"], key=lambda item: item["phone"])
    assert [(item["phone"], item["sms_record_url"]) for item in result_successes] == [
        ("+447383370667", "https://api.sms8.net/api/record?token=one"),
        ("+447383370668", "https://api.sms8.net/api/record?token=two"),
    ]


def test_pay153_batch_uses_selected_country_and_sms_provider_phone(monkeypatch):
    us_paypal.LINKS_FILE.write_text(
        json.dumps(
            [
                {
                    "account_email": "gb@example.com",
                    "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-A12345",
                    "country": "US",
                },
            ]
        ),
        encoding="utf-8",
    )
    captured_create_payloads = []
    submitted_codes = []

    class FakeActivation:
        phone_number = "+447700900222"

    class FakeOtpProvider:
        def __init__(self):
            self.activation = FakeActivation()
            self.marked = False
            self.confirmed = None

        def reserve_number(self):
            return self.activation

        def mark_sms_sent(self, activation):
            self.marked = activation is self.activation

        def wait_for_code(self, activation, timeout_seconds=None):
            assert self.marked is True
            return "654321"

        def register_confirmation_result(self, activation, confirmed):
            self.confirmed = confirmed

    provider = FakeOtpProvider()

    def fake_create_job(paypal_url, phone, country, proxies, buyer_mode, client=None):
        captured_create_payloads.append({"phone": phone, "country": country})
        return {"job": {"id": "remote-auto", "status": "awaiting_otp", "stage": "Waiting for SMS code / new phone", "awaiting_otp": True, "logs": []}}

    def fake_get_job(remote_job_id, client=None):
        return {"id": remote_job_id, "status": "completed", "stage": "done", "logs": [], "result": {"status": "success"}}

    monkeypatch.setattr(us_paypal, "_build_pay153_otp_provider", lambda sms_provider, phone, country, req: provider)
    monkeypatch.setattr(us_paypal, "_pay153_create_job", fake_create_job)
    monkeypatch.setattr(us_paypal, "_pay153_submit_otp", lambda remote_job_id, value, client=None: submitted_codes.append(value) or {"job": {"id": remote_job_id, "status": "running"}})
    monkeypatch.setattr(us_paypal, "_pay153_get_job", fake_get_job)
    monkeypatch.setattr(us_paypal, "_mark_account_plus_paypal", lambda email, message="": {"email": email})
    monkeypatch.setattr(us_paypal.time, "sleep", lambda seconds: None)

    job_id = us_paypal._new_pay153_batch_job(["gb@example.com"], concurrency=1)
    req = us_paypal.UsPaypal153BatchStartRequest.model_validate({
        "accountEmails": ["gb@example.com"],
        "smsProvider": "hero_sms",
        "country": "GB",
        "proxies": "proxy-one",
    })

    us_paypal._run_pay153_batch_payment_job(job_id, req)

    assert captured_create_payloads == [{"phone": "+447700900222", "country": "GB"}]
    assert submitted_codes == ["654321"]
    assert provider.confirmed is True
    assert us_paypal.JOBS[job_id]["status"] == "success"


def test_pay153_hero_sms_auto_changes_number_after_60s_without_code(monkeypatch):
    submitted_values = []
    abandoned = []
    waits = []

    class FakeActivation:
        def __init__(self, phone):
            self.phone_number = phone

    class FakeOtpProvider:
        def __init__(self):
            self.activations = [FakeActivation("+447700900001"), FakeActivation("+447700900002")]
            self.confirmed = None

        def reserve_number(self):
            return self.activations.pop(0)

        def mark_sms_sent(self, activation):
            return None

        def wait_for_code(self, activation, timeout_seconds=None):
            waits.append((activation.phone_number, timeout_seconds))
            return None if activation.phone_number.endswith("001") else "654321"

        def abandon(self, activation, reason):
            abandoned.append((activation.phone_number, reason))

        def register_confirmation_result(self, activation, confirmed):
            self.confirmed = (activation.phone_number, confirmed)

    provider = FakeOtpProvider()

    def fake_create_job(paypal_url, phone, country, proxies, buyer_mode, client=None):
        return {"job": {"id": "remote-auto-change", "status": "awaiting_otp", "stage": "Waiting for SMS code / new phone", "awaiting_otp": True, "logs": []}}

    def fake_submit_otp(remote_job_id, value, client=None):
        submitted_values.append(value)
        return {"job": {"id": remote_job_id, "status": "awaiting_otp" if value.startswith("+") else "running", "stage": "otp", "awaiting_otp": value.startswith("+"), "logs": []}}

    def fake_get_job(remote_job_id, client=None):
        return {"id": remote_job_id, "status": "completed", "stage": "done", "logs": [], "result": {"status": "success"}}

    monkeypatch.setattr(us_paypal, "_build_pay153_otp_provider", lambda sms_provider, phone, country, req: provider)
    monkeypatch.setattr(us_paypal, "_pay153_create_job", fake_create_job)
    monkeypatch.setattr(us_paypal, "_pay153_submit_otp", fake_submit_otp)
    monkeypatch.setattr(us_paypal, "_pay153_get_job", fake_get_job)
    monkeypatch.setattr(us_paypal, "_mark_account_plus_paypal", lambda email, message="": {"email": email})
    monkeypatch.setattr(us_paypal.time, "sleep", lambda seconds: None)

    job_id = us_paypal._new_pay153_batch_job(["gb@example.com"], concurrency=1)
    req = us_paypal.UsPaypal153BatchStartRequest.model_validate({
        "accountEmails": ["gb@example.com"],
        "smsProvider": "hero_sms",
        "country": "GB",
        "proxies": "proxy-one",
        "smsRecordWaitSeconds": 300,
    })

    result = us_paypal._run_pay153_batch_account(
        job_id,
        req,
        {
            "email": "gb@example.com",
            "ba_token": "BA-A12345",
            "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-A12345",
            "country": "GB",
        },
        1,
        1,
        [],
        ["proxy-one"],
    )

    assert result["ok"] is True
    assert submitted_values == ["+447700900002", "654321"]
    assert waits == [("+447700900001", 60.0), ("+447700900002", 60.0)]
    assert abandoned == [("+447700900001", "pay153_otp_timeout_60s_change_phone")]
    assert provider.confirmed == ("+447700900002", True)


def test_pay153_smsbower_auto_change_number_stops_after_three_changes(monkeypatch):
    submitted_values = []
    abandoned = []

    class FakeActivation:
        def __init__(self, phone):
            self.phone_number = phone

    class FakeOtpProvider:
        def __init__(self):
            self.index = 0

        def reserve_number(self):
            self.index += 1
            return FakeActivation(f"+44770090000{self.index}")

        def mark_sms_sent(self, activation):
            return None

        def wait_for_code(self, activation, timeout_seconds=None):
            assert timeout_seconds == 60.0
            return None

        def abandon(self, activation, reason):
            abandoned.append((activation.phone_number, reason))

        def register_confirmation_result(self, activation, confirmed):
            return None

    provider = FakeOtpProvider()

    monkeypatch.setattr(us_paypal, "_build_pay153_otp_provider", lambda sms_provider, phone, country, req: provider)
    monkeypatch.setattr(us_paypal, "_pay153_create_job", lambda paypal_url, phone, country, proxies, buyer_mode, client=None: {"job": {"id": "remote-max-change", "status": "awaiting_otp", "stage": "Waiting for SMS code / new phone", "awaiting_otp": True, "logs": []}})
    monkeypatch.setattr(us_paypal, "_pay153_submit_otp", lambda remote_job_id, value, client=None: submitted_values.append(value) or {"job": {"id": remote_job_id, "status": "awaiting_otp", "stage": "otp", "awaiting_otp": True, "logs": []}})
    monkeypatch.setattr(us_paypal.time, "sleep", lambda seconds: None)

    job_id = us_paypal._new_pay153_batch_job(["gb@example.com"], concurrency=1)
    req = us_paypal.UsPaypal153BatchStartRequest.model_validate({
        "accountEmails": ["gb@example.com"],
        "smsProvider": "smsbower",
        "country": "GB",
        "proxies": "proxy-one",
    })

    result = us_paypal._run_pay153_batch_account(
        job_id,
        req,
        {
            "email": "gb@example.com",
            "ba_token": "BA-A12345",
            "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-A12345",
            "country": "GB",
        },
        1,
        1,
        [],
        ["proxy-one"],
    )

    assert result["ok"] is False
    assert "已换号 3 次" in result["error"]["error"]
    assert submitted_values == ["+447700900002", "+447700900003", "+447700900004"]
    assert len(abandoned) == 4


def test_pay153_batch_account_reuses_session_client_for_create_and_poll(monkeypatch):
    seen_clients = []

    def fake_create_job(paypal_url, phone, country, proxies, buyer_mode, client=None):
        seen_clients.append(("create", client))
        return {"job": {"id": "remote-session", "status": "running", "stage": "created", "logs": []}}

    def fake_get_job(remote_job_id, client=None):
        seen_clients.append(("poll", client))
        return {"id": remote_job_id, "status": "completed", "stage": "done", "logs": [], "result": {"status": "success"}}

    monkeypatch.setattr(us_paypal, "_pay153_create_job", fake_create_job)
    monkeypatch.setattr(us_paypal, "_pay153_get_job", fake_get_job)
    monkeypatch.setattr(us_paypal, "_mark_account_plus_paypal", lambda email, message="": {"email": email})
    monkeypatch.setattr(us_paypal.time, "sleep", lambda seconds: None)

    job_id = us_paypal._new_pay153_batch_job(["gb@example.com"], concurrency=1)
    req = us_paypal.UsPaypal153BatchStartRequest.model_validate({
        "accountEmails": ["gb@example.com"],
        "phone": "+447700900001",
        "proxies": "proxy-one",
    })

    result = us_paypal._run_pay153_batch_account(
        job_id,
        req,
        {
            "email": "gb@example.com",
            "ba_token": "BA-A12345",
            "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-A12345",
            "country": "GB",
        },
        1,
        1,
        ["+447700900001"],
        ["proxy-one"],
    )

    assert result["ok"] is True
    assert seen_clients[0][0] == "create"
    assert seen_clients[1][0] == "poll"
    assert seen_clients[0][1] is not None
    assert seen_clients[0][1] is seen_clients[1][1]


def test_pay153_client_serializes_cookie_jar_access():
    client = us_paypal.Pay153Client(base_url="https://pay153.test/api")
    lock_owned_during_open = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"ok":true}'

    class FakeOpener:
        def open(self, request, timeout):
            lock_owned_during_open.append(client._lock._is_owned())
            return FakeResponse()

    client.opener = FakeOpener()

    assert client.request("GET", "/jobs/remote-session") == {"ok": True}
    assert lock_owned_during_open == [True]


def test_pay153_client_cookie_snapshot_roundtrip():
    client = us_paypal.Pay153Client(base_url="https://pay153.test/api")
    cookie = us_paypal.http.cookiejar.Cookie(
        version=0,
        name="pay153_session",
        value="session-abc",
        port=None,
        port_specified=False,
        domain="pay.153.ink",
        domain_specified=True,
        domain_initial_dot=False,
        path="/",
        path_specified=True,
        secure=True,
        expires=None,
        discard=True,
        comment=None,
        comment_url=None,
        rest={"HttpOnly": None},
        rfc2109=False,
    )
    client.cookie_jar.set_cookie(cookie)

    restored = us_paypal.Pay153Client.from_cookie_snapshot(client.cookie_snapshot(), base_url=client.base_url)

    assert [(item.name, item.value, item.domain, item.path, item.secure) for item in restored.cookie_jar] == [
        ("pay153_session", "session-abc", "pay.153.ink", "/", True)
    ]


def test_pay153_snapshot_hides_client_and_remote_sensitive_fields():
    job_id = "p153-sensitive"
    us_paypal.JOBS[job_id] = {
        "id": job_id,
        "kind": "paypal_153_payment",
        "status": "running",
        "logs": ["153支付开始：gb@example.com"],
        "result": None,
        "error": None,
        "created_at": 1.0,
        "finished_at": None,
        "account_email": "",
        "total": 1,
        "completed": 0,
        "concurrency": 1,
        "cancel_requested": False,
        "running_count": 0,
        "skipped": [],
        "account_statuses": {},
        "pay153_clients": {"remote-1": object()},
        "children": {
            "remote-1": {
                "email": "gb@example.com",
                "remote_job_id": "remote-1",
                "country": "GB",
                "ba_token": "BA-SENSITIVE",
                "status": "running",
                "stage": "otp",
                "logs": ["phone +447700900001 proxy user:pass@host datadome=secret"],
                "result": {"ba_token": "BA-SENSITIVE", "proxy": "user:pass@host"},
                "error": "",
                "awaiting_otp": True,
                "awaiting_captcha": False,
                "awaiting_prompt": "输入验证码",
                "challenge_url": "https://paypal.example/challenge?token=secret",
                "cancellable": True,
            }
        },
    }

    snapshot = us_paypal._job_snapshot(job_id)
    child = snapshot["children"]["remote-1"]

    assert "pay153_clients" not in snapshot
    assert child == {
        "email": "gb@example.com",
        "remote_job_id": "remote-1",
        "country": "GB",
        "status": "running",
        "stage": "otp",
        "error": "",
        "awaiting_otp": True,
        "awaiting_captcha": False,
        "awaiting_prompt": "输入验证码",
        "cancellable": True,
    }


def test_pay153_batch_account_cancel_requested_maps_to_skipped_not_failed(monkeypatch):
    def fake_create_job(paypal_url, phone, country, proxies, buyer_mode, client=None):
        return {"job": {"id": "remote-cancel", "status": "running", "stage": "created", "logs": []}}

    def fake_get_job(remote_job_id, client=None):
        with us_paypal.JOBS_LOCK:
            us_paypal.JOBS[job_id]["cancel_requested"] = True
        return {"id": remote_job_id, "status": "running", "stage": "still-running", "logs": []}

    monkeypatch.setattr(us_paypal, "_pay153_create_job", fake_create_job)
    monkeypatch.setattr(us_paypal, "_pay153_get_job", fake_get_job)
    monkeypatch.setattr(us_paypal.time, "sleep", lambda seconds: None)

    job_id = us_paypal._new_pay153_batch_job(["gb@example.com"], concurrency=1)
    req = us_paypal.UsPaypal153BatchStartRequest.model_validate({
        "accountEmails": ["gb@example.com"],
        "phone": "+447700900001",
        "proxies": "proxy-one",
    })

    result = us_paypal._run_pay153_batch_account(
        job_id,
        req,
        {
            "email": "gb@example.com",
            "ba_token": "BA-A12345",
            "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-A12345",
            "country": "GB",
        },
        1,
        1,
        ["+447700900001"],
        ["proxy-one"],
    )

    assert result["skipped"] is True
    assert result["reason"] == "任务已取消"
    assert result["status"]["status"] == us_paypal.PAYPAL_STATUS_SUCCESS
    assert us_paypal.JOBS[job_id]["children"]["remote-cancel"]["status"] == "cancelled"


def test_pay153_batch_account_failure_marks_account_payment_failed(monkeypatch):
    def fake_create_job(paypal_url, phone, country, proxies, buyer_mode, client=None):
        return {"job": {"id": "remote-failed", "status": "failed", "stage": "auth challenge", "logs": [], "error": "PAYPAL_GRAPHQL_AUTH_CHALLENGE"}}

    monkeypatch.setattr(us_paypal, "_pay153_create_job", fake_create_job)

    job_id = us_paypal._new_pay153_batch_job(["gb@example.com"], concurrency=1)
    req = us_paypal.UsPaypal153BatchStartRequest.model_validate({
        "accountEmails": ["gb@example.com"],
        "phone": "+447700900001",
        "proxies": "proxy-one",
    })

    result = us_paypal._run_pay153_batch_account(
        job_id,
        req,
        {
            "email": "gb@example.com",
            "ba_token": "BA-A12345",
            "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-A12345",
            "country": "GB",
        },
        1,
        1,
        ["+447700900001"],
        ["proxy-one"],
    )

    assert result["ok"] is False
    assert result["status"]["status"] == us_paypal.PAYPAL_STATUS_FAILED
    assert result["error"]["phone"] == "+447700900001"


def test_pay153_already_processing_error_is_not_retried(monkeypatch):
    calls = []
    cancelled = []

    def fake_create_job(paypal_url, phone, country, proxies, buyer_mode, client=None):
        calls.append(phone)
        raise RuntimeError("This PayPal link is already being processed by another task")

    monkeypatch.setattr(us_paypal, "_pay153_create_job", fake_create_job)
    monkeypatch.setattr(us_paypal, "_pay153_list_jobs", lambda client=None: {"jobs": []})
    monkeypatch.setattr(us_paypal, "_pay153_cancel_job", lambda remote_job_id, client=None: cancelled.append(remote_job_id) or {"job": {"id": remote_job_id, "status": "cancelled"}})

    job_id = us_paypal._new_pay153_batch_job(["gb@example.com"], concurrency=1)
    req = us_paypal.UsPaypal153BatchStartRequest.model_validate({
        "accountEmails": ["gb@example.com"],
        "phonePool": "+447700900001----https://api.sms8.net/api/record?token=one\n+447700900002----https://api.sms8.net/api/record?token=two",
        "proxies": "proxy-one",
    })
    pool = us_paypal._pay153_sms_record_pool(req)
    lock = us_paypal.threading.Lock()

    result = us_paypal._run_pay153_batch_account(
        job_id,
        req,
        {
            "email": "gb@example.com",
            "ba_token": "BA-A12345",
            "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-A12345",
            "country": "GB",
        },
        1,
        1,
        [],
        ["proxy-one"],
        [],
        pool,
        lock,
    )

    assert calls == ["+447700900001"]
    assert cancelled == []
    assert result["ok"] is False
    assert result["status"]["status"] == us_paypal.PAYPAL_STATUS_FAILED
    assert "already being processed" in result["error"]["error"]
    assert result["error"]["remote_cancelled"] == []


def test_pay153_cancel_existing_jobs_for_ba_uses_local_child_session(monkeypatch):
    client = object()
    us_paypal.JOBS["old-job"] = {
        "id": "old-job",
        "kind": "paypal_153_payment",
        "status": "running",
        "logs": [],
        "result": None,
        "error": None,
        "created_at": 1.0,
        "finished_at": None,
        "children": {
            "remote-local": {
                "remote_job_id": "remote-local",
                "status": "running",
                "ba_token": "BA-4PL91052NS685551N",
            }
        },
        "pay153_clients": {"remote-local": client},
    }
    cancelled = []
    monkeypatch.setattr(us_paypal, "_pay153_list_jobs", lambda client=None: {"jobs": []})
    monkeypatch.setattr(us_paypal, "_pay153_cancel_job", lambda remote_job_id, client=None: cancelled.append((remote_job_id, client)) or {"job": {"id": remote_job_id, "status": "cancelled"}})

    result = us_paypal._pay153_cancel_existing_jobs_for_ba("BA-4PL91052NS685551N")

    assert result == ["remote-local"]
    assert cancelled == [("remote-local", client)]
    assert us_paypal.JOBS["old-job"]["children"]["remote-local"]["status"] == "cancelled"


def test_pay153_cancel_existing_jobs_for_ba_returns_local_cancel_when_remote_list_fails(monkeypatch):
    client = object()
    us_paypal.JOBS["old-job"] = {
        "id": "old-job",
        "kind": "paypal_153_payment",
        "status": "running",
        "logs": [],
        "result": None,
        "error": None,
        "created_at": 1.0,
        "finished_at": None,
        "children": {
            "remote-local": {"remote_job_id": "remote-local", "status": "running", "ba_token": "BA-4PL91052NS685551N"}
        },
        "pay153_clients": {"remote-local": client},
    }
    monkeypatch.setattr(us_paypal, "_pay153_cancel_job", lambda remote_job_id, client=None: {"job": {"id": remote_job_id, "status": "cancelled"}})
    monkeypatch.setattr(us_paypal, "_pay153_list_jobs", lambda client=None: (_ for _ in ()).throw(RuntimeError("list unavailable")))

    assert us_paypal._pay153_cancel_existing_jobs_for_ba("BA-4PL91052NS685551N") == ["remote-local"]


def test_pay153_child_persists_remote_task_index_with_session():
    client = us_paypal.Pay153Client(base_url="https://pay153.test/api")
    client.cookie_jar.set_cookie(us_paypal.http.cookiejar.Cookie(
        version=0,
        name="pay153_session",
        value="session-abc",
        port=None,
        port_specified=False,
        domain="pay.153.ink",
        domain_specified=True,
        domain_initial_dot=False,
        path="/",
        path_specified=True,
        secure=True,
        expires=None,
        discard=True,
        comment=None,
        comment_url=None,
        rest={},
        rfc2109=False,
    ))
    job_id = us_paypal._new_pay153_batch_job(["gb@example.com"], concurrency=1)
    us_paypal._set_pay153_child_client(job_id, "remote-persist", client)

    us_paypal._set_pay153_child(job_id, {
        "email": "gb@example.com",
        "remote_job_id": "remote-persist",
        "country": "GB",
        "ba_token": "BA-PERSIST",
        "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-PERSIST",
        "status": "running",
    })

    tasks = json.loads(us_paypal.PAY153_REMOTE_TASKS_FILE.read_text(encoding="utf-8"))
    assert tasks["remote-persist"]["ba_token"] == "BA-PERSIST"
    assert tasks["remote-persist"]["local_job_id"] == job_id
    assert tasks["remote-persist"]["cookies"][0]["name"] == "pay153_session"
    assert tasks["remote-persist"]["cookies"][0]["value"] == "session-abc"


def test_pay153_cancel_existing_jobs_for_ba_uses_persisted_remote_task_after_restart(monkeypatch):
    us_paypal._save_pay153_remote_tasks({
        "remote-old": {
            "remote_job_id": "remote-old",
            "local_job_id": "p153-before-restart",
            "email": "gb@example.com",
            "country": "GB",
            "ba_token": "BA-4PL91052NS685551N",
            "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-4PL91052NS685551N",
            "status": "running",
            "base_url": "https://pay153.test/api",
            "cookies": [
                {
                    "version": 0,
                    "name": "pay153_session",
                    "value": "session-abc",
                    "port": None,
                    "port_specified": False,
                    "domain": "pay.153.ink",
                    "domain_specified": True,
                    "domain_initial_dot": False,
                    "path": "/",
                    "path_specified": True,
                    "secure": True,
                    "expires": None,
                    "discard": True,
                    "comment": None,
                    "comment_url": None,
                    "rest": {},
                    "rfc2109": False,
                }
            ],
        }
    })
    us_paypal.JOBS.clear()
    cancelled = []
    monkeypatch.setattr(us_paypal, "_pay153_list_jobs", lambda client=None: {"jobs": []})

    def fake_cancel(remote_job_id, client=None):
        cancelled.append((remote_job_id, [cookie.value for cookie in client.cookie_jar]))
        return {"job": {"id": remote_job_id, "status": "cancelled"}}

    monkeypatch.setattr(us_paypal, "_pay153_cancel_job", fake_cancel)

    assert us_paypal._pay153_cancel_existing_jobs_for_ba("BA-4PL91052NS685551N") == ["remote-old"]
    assert cancelled == [("remote-old", ["session-abc"])]
    assert us_paypal._load_pay153_remote_tasks()["remote-old"]["status"] == "cancelled"


def test_pay153_cancel_existing_jobs_for_ba_skips_failed_persisted_cancel_and_continues(monkeypatch):
    us_paypal._save_pay153_remote_tasks({
        "remote-bad": {
            "remote_job_id": "remote-bad",
            "ba_token": "BA-4PL91052NS685551N",
            "status": "running",
            "base_url": "https://pay153.test/api",
            "cookies": [],
        },
        "remote-good": {
            "remote_job_id": "remote-good",
            "ba_token": "BA-4PL91052NS685551N",
            "status": "running",
            "base_url": "https://pay153.test/api",
            "cookies": [],
        },
    })
    monkeypatch.setattr(us_paypal, "_pay153_list_jobs", lambda client=None: {"jobs": []})

    def fake_cancel(remote_job_id, client=None):
        if remote_job_id == "remote-bad":
            raise RuntimeError("session expired")
        return {"job": {"id": remote_job_id, "status": "cancelled"}}

    monkeypatch.setattr(us_paypal, "_pay153_cancel_job", fake_cancel)

    assert us_paypal._pay153_cancel_existing_jobs_for_ba("BA-4PL91052NS685551N") == ["remote-good"]
    tasks = us_paypal._load_pay153_remote_tasks()
    assert tasks["remote-bad"]["status"] == "running"
    assert tasks["remote-bad"]["error"] == "session expired"
    assert tasks["remote-good"]["status"] == "cancelled"


def test_pay153_already_processing_retries_after_cancelled_stale_remote(monkeypatch):
    calls = []
    monkeypatch.setattr(us_paypal, "_pay153_cancel_existing_jobs_for_ba", lambda paypal_link, client=None: ["remote-stale"])

    class FakeActivation:
        phone_number = ""

    class FakeOtpProvider:
        def reserve_number(self):
            return FakeActivation()

    monkeypatch.setattr(us_paypal, "_build_pay153_otp_provider", lambda sms_provider, phone, country, req: FakeOtpProvider())

    def fake_create_job(paypal_url, phone, country, proxies, buyer_mode, client=None):
        calls.append(phone)
        if len(calls) == 1:
            raise RuntimeError("This PayPal link is already being processed by another task")
        return {"job": {"id": "remote-ok", "status": "completed", "stage": "done", "logs": [], "result": {"status": "success"}}}

    monkeypatch.setattr(us_paypal, "_pay153_create_job", fake_create_job)

    job_id = us_paypal._new_pay153_batch_job(["gb@example.com"], concurrency=1)
    req = us_paypal.UsPaypal153BatchStartRequest.model_validate({
        "accountEmails": ["gb@example.com"],
        "phonePool": "+447700900001----https://api.sms8.net/api/record?token=one\n+447700900002----https://api.sms8.net/api/record?token=two",
        "proxies": "proxy-one",
    })
    pool = us_paypal._pay153_sms_record_pool(req)

    result = us_paypal._run_pay153_batch_account(
        job_id,
        req,
        {
            "email": "gb@example.com",
            "ba_token": "BA-91G197898H813770D",
            "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-91G197898H813770D",
            "country": "GB",
        },
        1,
        1,
        [],
        ["proxy-one"],
        [],
        pool,
        us_paypal.threading.Lock(),
    )

    assert result["ok"] is True
    assert calls == ["+447700900001", "+447700900002"]


def test_pay153_cancel_remote_by_ba_route(monkeypatch):
    app = _app()
    cancelled = []
    monkeypatch.setattr(us_paypal, "_pay153_list_jobs", lambda client=None: {
        "jobs": [
            {"id": "remote-match", "status": "awaiting_otp", "ba_token": "BA-91G197898H813770D"},
            {"id": "remote-other", "status": "running", "ba_token": "BA-OTHER"},
        ]
    })
    monkeypatch.setattr(us_paypal, "_pay153_cancel_job", lambda remote_job_id, client=None: cancelled.append(remote_job_id) or {"job": {"id": remote_job_id, "status": "cancelled"}})

    result = _endpoint(app, "/api/us-paypal/pay153/remote/cancel-by-ba", "POST")(
        us_paypal.UsPaypal153CancelByBaRequest.model_validate({
            "paypalLink": "https://www.paypal.com/agreements/approve?ba_token=BA-91G197898H813770D",
        })
    )

    assert result == {"ok": True, "ba_token": "BA-91G197898H813770D", "remote_cancelled": ["remote-match"]}
    assert cancelled == ["remote-match"]


def test_pay153_batch_job_records_worker_exception_without_failing_whole_batch(monkeypatch):
    monkeypatch.setattr(us_paypal, "_validate_pay153_batch_start", lambda req: [
        {"email": "a@example.com", "ba_token": "BA-91G197898H813770D", "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-91G197898H813770D", "country": "TH"},
    ])
    monkeypatch.setattr(us_paypal, "_run_pay153_batch_account", lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("[WinError 32] cache busy")))

    job_id = us_paypal._new_pay153_batch_job(["a@example.com"], concurrency=1)
    req = us_paypal.UsPaypal153BatchStartRequest.model_validate({
        "accountEmails": ["a@example.com"],
        "smsProvider": "hero_sms",
        "proxies": "proxy-one",
    })

    us_paypal._run_pay153_batch_payment_job(job_id, req)

    job = us_paypal.JOBS[job_id]
    assert job["status"] == "error"
    assert job["error"] == "全部账号153支付失败"
    assert job["result"]["errors"][0]["email"] == "a@example.com"
    assert "[WinError 32] cache busy" in job["result"]["errors"][0]["error"]
    assert job["completed"] == 1


def test_pay153_batch_start_route_returns_local_job_id(monkeypatch):
    us_paypal.LINKS_FILE.write_text(
        json.dumps([
            {"account_email": "gb@example.com", "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-A12345", "country": "GB"},
        ]),
        encoding="utf-8",
    )
    app = _app()
    captured = {}

    class FakeThread:
        def __init__(self, target, args, daemon):
            self.target = target
            self.args = args

        def start(self):
            captured["args"] = self.args

    monkeypatch.setattr(us_paypal.threading, "Thread", FakeThread)

    result = _endpoint(app, "/api/us-paypal/pay153/batch/start", "POST")(
        us_paypal.UsPaypal153BatchStartRequest.model_validate({
            "accountEmails": ["gb@example.com"],
            "phone": "+447700900001",
            "smsRecordUrl": "https://sms.example/gb",
            "proxies": "proxy-one",
        })
    )

    assert result["job_id"].startswith("p153-")
    assert captured["args"][0] == result["job_id"]


def test_pay153_otp_and_captcha_forward_only_owned_remote_job(monkeypatch):
    app = _app()
    job_id = "p153-local"
    us_paypal.JOBS[job_id] = {
        "id": job_id,
        "kind": "paypal_153_payment",
        "status": "running",
        "logs": [],
        "result": None,
        "error": None,
        "created_at": 1.0,
        "finished_at": None,
        "account_email": "",
        "total": 1,
        "completed": 0,
        "concurrency": 1,
        "cancel_requested": False,
        "running_count": 0,
        "skipped": [],
        "account_statuses": {},
        "children": {"remote-1": {"remote_job_id": "remote-1", "email": "gb@example.com"}},
    }
    captured = []
    monkeypatch.setattr(us_paypal, "_pay153_submit_otp", lambda remote_job_id, value, client=None: captured.append(("otp", remote_job_id, value)) or {"job": {"id": remote_job_id, "status": "running"}})
    monkeypatch.setattr(us_paypal, "_pay153_submit_captcha", lambda remote_job_id, value, client=None: captured.append(("captcha", remote_job_id, value)) or {"job": {"id": remote_job_id, "status": "running"}})

    otp_result = _endpoint(app, "/api/us-paypal/pay153/jobs/{job_id}/otp", "POST")(
        job_id,
        us_paypal.UsPaypal153InteractiveRequest.model_validate({"remoteJobId": "remote-1", "value": "123456"}),
    )
    captcha_result = _endpoint(app, "/api/us-paypal/pay153/jobs/{job_id}/captcha", "POST")(
        job_id,
        us_paypal.UsPaypal153InteractiveRequest.model_validate({"remoteJobId": "remote-1", "value": "datadome=abc"}),
    )

    assert otp_result["ok"] is True
    assert captcha_result["ok"] is True
    assert captured == [("otp", "remote-1", "123456"), ("captcha", "remote-1", "datadome=abc")]
    with pytest.raises(HTTPException) as exc:
        _endpoint(app, "/api/us-paypal/pay153/jobs/{job_id}/otp", "POST")(
            job_id,
            us_paypal.UsPaypal153InteractiveRequest.model_validate({"remoteJobId": "remote-other", "value": "123456"}),
        )
    assert exc.value.status_code == 400


def test_pay153_interactive_routes_reuse_stored_session_client(monkeypatch):
    app = _app()
    job_id = "p153-local"
    client = object()
    us_paypal.JOBS[job_id] = {
        "id": job_id,
        "kind": "paypal_153_payment",
        "status": "running",
        "logs": [],
        "result": None,
        "error": None,
        "created_at": 1.0,
        "finished_at": None,
        "account_email": "",
        "total": 1,
        "completed": 0,
        "concurrency": 1,
        "cancel_requested": False,
        "running_count": 0,
        "skipped": [],
        "account_statuses": {},
        "children": {"remote-1": {"remote_job_id": "remote-1", "email": "gb@example.com", "status": "running"}},
        "pay153_clients": {"remote-1": client},
    }
    captured = []
    monkeypatch.setattr(us_paypal, "_pay153_submit_otp", lambda remote_job_id, value, client=None: captured.append(("otp", client)) or {"job": {"id": remote_job_id, "status": "running"}})
    monkeypatch.setattr(us_paypal, "_pay153_submit_captcha", lambda remote_job_id, value, client=None: captured.append(("captcha", client)) or {"job": {"id": remote_job_id, "status": "running"}})
    monkeypatch.setattr(us_paypal, "_pay153_cancel_job", lambda remote_job_id, client=None: captured.append(("cancel", client)) or {"job": {"id": remote_job_id, "status": "cancelled"}})

    _endpoint(app, "/api/us-paypal/pay153/jobs/{job_id}/otp", "POST")(
        job_id,
        us_paypal.UsPaypal153InteractiveRequest.model_validate({"remoteJobId": "remote-1", "value": "123456"}),
    )
    _endpoint(app, "/api/us-paypal/pay153/jobs/{job_id}/captcha", "POST")(
        job_id,
        us_paypal.UsPaypal153InteractiveRequest.model_validate({"remoteJobId": "remote-1", "value": "datadome=abc"}),
    )
    _endpoint(app, "/api/us-paypal/pay153/jobs/{job_id}/cancel", "POST")(job_id)

    assert captured == [("otp", client), ("captcha", client), ("cancel", client)]


def test_pay153_cancel_forwards_to_active_remote_children(monkeypatch):
    app = _app()
    job_id = "p153-local"
    us_paypal.JOBS[job_id] = {
        "id": job_id,
        "kind": "paypal_153_payment",
        "status": "running",
        "logs": [],
        "result": None,
        "error": None,
        "created_at": 1.0,
        "finished_at": None,
        "account_email": "",
        "total": 2,
        "completed": 0,
        "concurrency": 1,
        "cancel_requested": False,
        "running_count": 0,
        "skipped": [],
        "account_statuses": {},
        "children": {
            "remote-1": {"remote_job_id": "remote-1", "status": "running"},
            "remote-2": {"remote_job_id": "remote-2", "status": "completed"},
        },
    }
    cancelled = []
    monkeypatch.setattr(us_paypal, "_pay153_cancel_job", lambda remote_job_id, client=None: cancelled.append(remote_job_id) or {"job": {"id": remote_job_id, "status": "cancelled"}})

    result = _endpoint(app, "/api/us-paypal/pay153/jobs/{job_id}/cancel", "POST")(job_id)

    assert result["ok"] is True
    assert result["status"] == "cancelling"
    assert cancelled == ["remote-1"]
    assert us_paypal.JOBS[job_id]["cancel_requested"] is True


def test_pay153_supported_countries_and_stats_proxy(monkeypatch):
    app = _app()
    captured = []

    def fake_request(method, path, payload=None, timeout=30.0):
        captured.append((method, path))
        if path == "/supported-countries":
            return {"countries": [{"code": "GB"}]}
        return {"success_total": 10}

    monkeypatch.setattr(us_paypal, "_pay153_request", fake_request)

    countries = _endpoint(app, "/api/us-paypal/pay153/supported-countries", "GET")()
    stats = _endpoint(app, "/api/us-paypal/pay153/stats", "GET")()

    assert countries["countries"][0]["code"] == "GB"
    assert stats["success_total"] == 10
    assert captured == [("GET", "/supported-countries"), ("GET", "/stats")]


def test_pay153_provider_factories_respect_phone_pool_reuse_enabled(monkeypatch):
    from autotoken._paypal_protocol_engine.paypal import smsbower as paypal_sms_providers

    hero_calls = []
    rent_calls = []

    def fake_build_sms_activate_provider(**kwargs):
        hero_calls.append(kwargs)
        return object()

    def fake_build_hero_sms_rent_provider(**kwargs):
        rent_calls.append(kwargs)
        return object()

    monkeypatch.setattr(paypal_sms_providers, "build_sms_activate_provider", fake_build_sms_activate_provider)
    monkeypatch.setattr(paypal_sms_providers, "build_hero_sms_rent_provider", fake_build_hero_sms_rent_provider)

    req = us_paypal.UsPaypal153BatchStartRequest.model_validate({
        "accountEmails": ["user@example.com"],
        "phonePoolReuseEnabled": False,
    })

    us_paypal._build_pay153_otp_provider("hero_sms", "", "GB", req)
    us_paypal._build_pay153_otp_provider("hero_sms_rent", "+447700900001", "GB", req)

    assert hero_calls[0]["reuse_enabled"] is False
    assert rent_calls[0]["reuse_enabled"] is False


def test_start_request_caps_configurable_attempts():
    req = us_paypal.UsPaypalBatchStartRequest.model_validate({"accountEmails": ["user@example.com"], "maxAttempts": 99})

    assert req.max_attempts == 20


def test_mark_account_plus_paypal_sets_dashboard_plus_snapshot(monkeypatch):
    captured = {}
    monkeypatch.setattr(us_paypal.account_store, "ensure_session_only_account", lambda email: captured.setdefault("ensured", email))

    def fake_update_account(email, **payload):
        captured["email"] = email
        captured["payload"] = payload
        return {"email": email, **payload}

    monkeypatch.setattr(us_paypal.account_store, "update_account", fake_update_account)

    updated = us_paypal._mark_account_plus_paypal("paid@example.com", "paid ok")

    assert captured["ensured"] == "paid@example.com"
    assert updated["account_type"] == us_paypal.account_store.ACCOUNT_TYPE_PLUS
    assert updated["last_bind_provider"] == "paypal"
    assert updated["last_bind_status"] == "success"
    assert updated["last_quota"]["plan_type"] == "plus"


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


def test_protocol_start_allows_herosms_rent_with_phone(monkeypatch):
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
            "paypalLink": "https://www.paypal.com/agreements/approve?ba_token=BA-1HERORENTROUTE123",
            "smsProvider": "hero-sms-rent",
            "phone": "+31612345678",
            "country": "NL",
        })
    )

    assert result["job_id"].startswith("ppay-")
    assert captured["args"][1].sms_provider == "hero_sms_rent"
    assert captured["args"][1].phone == "+31612345678"
    assert captured["args"][1].country == "NL"


def test_protocol_start_rejects_herosms_rent_without_phone():
    app = _app()

    with pytest.raises(HTTPException) as exc:
        _endpoint(app, "/api/us-paypal/protocol/start", "POST")(
            us_paypal.UsPaypalProtocolStartRequest.model_validate({
                "paypalLink": "https://www.paypal.com/agreements/approve?ba_token=BA-1HERORENTPHONE123",
                "smsProvider": "hero-sms-rent",
                "country": "NL",
            })
        )

    assert exc.value.status_code == 400
    assert "HeroSMS 长效号码" in exc.value.detail["message"]


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


def test_protocol_start_passes_phone_pool_reuse_enabled_to_runner(monkeypatch):
    app = _app()
    captured = {}

    def fake_runner(cfg, log, cancel_check):
        captured["cfg"] = cfg
        return {"status": "success", "protocol_result": {"status": "success"}}

    class FakeThread:
        def __init__(self, target, args, daemon):
            self.target = target
            self.args = args
            self.daemon = daemon

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(us_paypal.threading, "Thread", FakeThread)
    monkeypatch.setattr(us_paypal, "run_paypal_protocol_payment", fake_runner)

    _endpoint(app, "/api/us-paypal/protocol/start", "POST")(
        us_paypal.UsPaypalProtocolStartRequest.model_validate({
            "paypalLink": "https://www.paypal.com/agreements/approve?ba_token=BA-1REUSEFLAG123",
            "smsProvider": "hero-sms",
            "phonePoolReuseEnabled": False,
            "proxyUrl": "proxy.example:10000:user:pass",
            "country": "GB",
        })
    )

    assert captured["cfg"].phone_pool_reuse_enabled is False


def test_protocol_command_sets_sms_reuse_env_from_config():
    cfg = us_paypal.PaypalProtocolRunConfig(
        ba_token="BA-1ENVFLAG123",
        phone="+447700900001",
        sms_record_url="https://sms.example/api/record?token=secret",
        sms_provider="hero_sms",
        proxy_url="proxy.example:10000:user:pass",
        country="GB",
        phone_pool_reuse_enabled=False,
    )

    _, env_off, _ = us_paypal.paypal_protocol_service.build_protocol_command(cfg)
    _, env_on, _ = us_paypal.paypal_protocol_service.build_protocol_command(
        us_paypal.PaypalProtocolRunConfig(
            ba_token="BA-1ENVFLAG124",
            phone="+447700900002",
            sms_record_url="https://sms.example/api/record?token=secret",
            sms_provider="hero_sms",
            proxy_url="proxy.example:10000:user:pass",
            country="GB",
            phone_pool_reuse_enabled=True,
        )
    )

    assert env_off["PAYPAL_SMS_REUSE_ENABLED"] == "0"
    assert env_on["PAYPAL_SMS_REUSE_ENABLED"] == "1"


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


def test_protocol_job_rewrites_proxy_region_and_sid_for_payment_country(monkeypatch):
    captured = {}
    job_id = us_paypal._new_protocol_job("buyer@example.com")

    def fake_runner(cfg, log, cancel_check):
        captured["cfg"] = cfg
        return {"status": "success", "protocol_result": {"status": "success"}}

    monkeypatch.setattr(us_paypal, "run_paypal_protocol_payment", fake_runner)
    monkeypatch.setattr(us_paypal, "_mark_account_plus_paypal", lambda email, message: None)
    monkeypatch.setattr(us_paypal, "_set_account_status", lambda email, status, **kwargs: {"status": status})

    req = us_paypal.UsPaypalProtocolStartRequest.model_validate({
        "baToken": "BA-1PROXYGB123",
        "smsProvider": "hero-sms",
        "proxyUrl": "global.rotgb.711proxy.com:10000:USER-zone-custom-region-US-session-fixed-sessTime-120-sessAuto-1:pass",
        "accountEmail": "buyer@example.com",
        "country": "GB",
    })
    us_paypal._run_protocol_payment_job(job_id, req)

    assert "-custom-region-GB-session-" in captured["cfg"].proxy_url
    assert "-custom-region-US-session-fixed" not in captured["cfg"].proxy_url


def test_protocol_job_preflights_proxy_before_runner(monkeypatch):
    job_id = us_paypal._new_protocol_job("buyer@example.com")
    preflighted: list[str] = []

    def fake_preflight(proxy_url):
        preflighted.append(proxy_url)
        return (False, "ProxyError: ruleset blocked")

    monkeypatch.setattr(proxy_runtime, "preflight_payment_proxy_url", fake_preflight)
    monkeypatch.setattr(us_paypal, "run_paypal_protocol_payment", lambda cfg, log, cancel_check: pytest.fail("should not run protocol engine when proxy preflight fails"))

    req = us_paypal.UsPaypalProtocolStartRequest.model_validate({
        "baToken": "BA-1PROXYFAIL123",
        "smsProvider": "hero-sms",
        "proxyUrl": "global.rotgb.711proxy.com:10000:USER-zone-custom-region-US-session-fixed-sessTime-120-sessAuto-1:pass",
        "accountEmail": "buyer@example.com",
        "country": "GB",
    })
    us_paypal._run_protocol_payment_job(job_id, req)

    job = us_paypal.JOBS[job_id]
    assert job["status"] == "error"
    assert len(preflighted) == 10
    assert "代理预检失败" in job["error"]
    assert "ruleset blocked" in job["error"]
    assert any("代理预检失败" in line for line in job["logs"])


def test_protocol_job_uses_configured_proxy_preflight_attempts(monkeypatch):
    job_id = us_paypal._new_protocol_job("buyer@example.com")
    preflighted: list[str] = []

    def fake_preflight(proxy_url):
        preflighted.append(proxy_url)
        return (False, "ProxyError: ruleset blocked")

    monkeypatch.setattr(proxy_runtime, "preflight_payment_proxy_url", fake_preflight)
    monkeypatch.setattr(us_paypal, "run_paypal_protocol_payment", lambda cfg, log, cancel_check: pytest.fail("should not run protocol engine when proxy preflight fails"))

    req = us_paypal.UsPaypalProtocolStartRequest.model_validate({
        "baToken": "BA-1PROXYFAIL123",
        "smsProvider": "hero-sms",
        "proxyUrl": "global.rotgb.711proxy.com:10000:USER-zone-custom-region-US-session-fixed-sessTime-120-sessAuto-1:pass",
        "accountEmail": "buyer@example.com",
        "country": "GB",
        "proxyPreflightAttempts": 4,
    })
    us_paypal._run_protocol_payment_job(job_id, req)

    job = us_paypal.JOBS[job_id]
    assert job["status"] == "error"
    assert len(preflighted) == 4
    assert any("协议支付代理预检开始：4/4" in line for line in job["logs"])


def test_protocol_proxy_preflight_has_separate_ten_attempt_budget(monkeypatch):
    captured = {}
    preflighted: list[str] = []
    job_id = us_paypal._new_protocol_job("buyer@example.com")

    def fake_preflight(proxy_url):
        preflighted.append(proxy_url)
        return (len(preflighted) == 10, "HTTP 200" if len(preflighted) == 10 else "ProxyError: ruleset blocked")

    def fake_runner(cfg, log, cancel_check):
        captured["cfg"] = cfg
        return {"status": "success", "protocol_result": {"status": "success"}}

    monkeypatch.setattr(proxy_runtime, "preflight_payment_proxy_url", fake_preflight)
    monkeypatch.setattr(us_paypal, "run_paypal_protocol_payment", fake_runner)
    monkeypatch.setattr(us_paypal, "_mark_account_plus_paypal", lambda email, message: None)
    monkeypatch.setattr(us_paypal, "_set_account_status", lambda email, status, **kwargs: {"status": status})

    req = us_paypal.UsPaypalProtocolStartRequest.model_validate({
        "baToken": "BA-1PROXYPASS123",
        "smsProvider": "hero-sms",
        "proxies": "\n".join([
            "proxy1.example:1000:user-region-US-sid-old1-t-120:pass",
            "proxy2.example:1000:user-region-US-sid-old2-t-120:pass",
            "proxy3.example:1000:user-region-US-sid-old3-t-120:pass",
            "proxy4.example:1000:user-region-US-sid-old4-t-120:pass",
            "proxy5.example:1000:user-region-US-sid-old5-t-120:pass",
            "proxy6.example:1000:user-region-US-sid-old6-t-120:pass",
        ]),
        "accountEmail": "buyer@example.com",
        "country": "GB",
    })
    us_paypal._run_protocol_payment_job(job_id, req)

    assert us_paypal.JOBS[job_id]["status"] == "success"
    assert len(preflighted) == 10
    assert "proxy4.example" in captured["cfg"].proxy_url
    assert "-region-GB-sid-" in captured["cfg"].proxy_url
    assert any("proxy6.example" in proxy for proxy in preflighted)


def test_protocol_batch_account_rewrites_proxy_region_and_sid_for_link_country(monkeypatch):
    captured = {}
    job_id = us_paypal._new_protocol_batch_job(["buyer@example.com"], 1)

    def fake_runner(cfg, log, cancel_check):
        captured["cfg"] = cfg
        return {"status": "success", "protocol_result": {"status": "success"}}

    monkeypatch.setattr(us_paypal, "run_paypal_protocol_payment", fake_runner)
    monkeypatch.setattr(us_paypal, "_mark_account_plus_paypal", lambda email, message: None)
    monkeypatch.setattr(us_paypal, "_set_account_status", lambda email, status, **kwargs: {"status": status})

    req = us_paypal.UsPaypalProtocolBatchStartRequest.model_validate({
        "accountEmails": ["buyer@example.com"],
        "smsProvider": "hero-sms",
        "proxies": "us.arxlabs.io:3010:user-region-US-sid-oldsid-t-120:pass",
        "country": "US",
    })
    result = us_paypal._run_protocol_batch_account(
        job_id,
        req,
        {
            "email": "buyer@example.com",
            "ba_token": "BA-1BATCHPROXY123",
            "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-1BATCHPROXY123",
            "country": "NL",
        },
        1,
        1,
        us_paypal._parse_proxies(req.proxies),
        [],
        [],
    )

    assert result["ok"] is True
    assert "-region-NL-sid-" in captured["cfg"].proxy_url
    assert "-region-US-sid-oldsid-" not in captured["cfg"].proxy_url


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
