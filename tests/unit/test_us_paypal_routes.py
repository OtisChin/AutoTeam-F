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


def test_paypal_link_batch_concurrency_allows_twenty():
    req = us_paypal.UsPaypalBatchStartRequest.model_validate({"accountEmails": [], "concurrency": 25})

    assert us_paypal._batch_concurrency(req, total=30) == 20


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


def test_batch_account_deletes_paypal_nonzero_amount_account(monkeypatch):
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

    assert result["ok"] is False
    assert result["account_deleted"] is True
    assert result["error"]["cleanup"] == {"record_deleted": True, "auth_session_deleted": True}
    assert "已从账号池删除" in result["error"]["error"]
    assert deleted_accounts == [email]
    assert deleted_sessions == [email]


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
