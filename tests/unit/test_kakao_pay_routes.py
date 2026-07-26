from __future__ import annotations

import json

import pytest
from fastapi import FastAPI

from autotoken.api_routes import kakao_pay
from autotoken.payments import kakao_pay as kakao_payment
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
    monkeypatch.setattr(kakao_pay, "_preflight_kakao_checkout_backend_proxy_url", lambda proxy_url, access_token, region: (True, "checkout_backend HTTP 200"))
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
    assert job["result"]["successes"][0]["link"]["kakao_link"] == "https://pay.nicepay.co.kr/v1/checkout/pay/test"
    assert job["result"]["successes"][0]["link"]["provider_redirect_url"] == "https://pay.nicepay.co.kr/v1/checkout/pay/test"
    assert job["result"]["successes"][0]["link"]["stripe_redirect_url"] == "https://pm-redirects.stripe.com/authorize/acct/test_nonce"
    assert captured["cfg"].access_token == "token-user@example.com"
    assert captured["cfg"].region == "KR"
    saved_link = json.loads(kakao_pay.LINKS_FILE.read_text(encoding="utf-8"))[0]
    assert saved_link["account_email"] == email
    assert saved_link["kakao_link"] == "https://pay.nicepay.co.kr/v1/checkout/pay/test"
    assert saved_link["kakao_ttl_seconds"] == 600
    assert saved_link["created_at_ts"] > 0
    assert saved_link["kakao_expires_at_ts"] - saved_link["created_at_ts"] == 600
    statuses = json.loads(kakao_pay.ACCOUNT_STATUS_FILE.read_text(encoding="utf-8"))
    assert statuses[email]["status"] == "success"


def test_preflight_kakao_proxies_preflights_same_seed_checkout_promotion_and_provider(monkeypatch):
    payment_calls = []
    auth_calls = []
    checkout_backend_calls = []

    def fake_payment_preflight(proxy_url):
        payment_calls.append(proxy_url)
        return True, f"payment {proxy_url}"

    def fake_auth_preflight(proxy_url, access_token):
        auth_calls.append((proxy_url, access_token))
        return True, f"auth {proxy_url}"

    monkeypatch.setattr(proxy_runtime, "preflight_payment_proxy_url", fake_payment_preflight)
    monkeypatch.setattr(proxy_runtime, "preflight_chatgpt_authenticated_proxy_url", fake_auth_preflight)
    monkeypatch.setattr(
        kakao_pay,
        "_preflight_kakao_checkout_backend_proxy_url",
        lambda proxy_url, access_token, region: checkout_backend_calls.append((proxy_url, access_token, region)) or (True, "checkout_backend HTTP 200"),
    )

    cfg = kakao_pay.KakaoPayJobConfig(
        access_token="token",
        direct_proxies=["http://checkout-proxy", "http://promotion-proxy", "http://provider-proxy"],
    )

    result = kakao_pay._preflight_kakao_proxies_or_raise(cfg, lambda _message: None)

    assert payment_calls == ["http://checkout-proxy", "http://checkout-proxy", "http://checkout-proxy"]
    assert auth_calls == [("http://checkout-proxy", "token"), ("http://checkout-proxy", "token")]
    assert checkout_backend_calls == [("http://checkout-proxy", "token", "KR"), ("http://checkout-proxy", "token", "KR")]
    assert result.preflighted_checkout_proxy_url == "http://checkout-proxy"
    assert result.preflighted_promotion_proxy_url == "http://checkout-proxy"
    assert result.preflighted_provider_proxy_url == "http://checkout-proxy"


def test_preflight_kakao_single_region_seed_derives_three_stage_chain(monkeypatch):
    payment_calls = []
    auth_calls = []
    seed = "socks5h://user-region-KR-session-fixed-sessTime-180-sessAuto-1:pass@example.com:3000"
    counter = {"value": 0}

    def fake_refresh(proxy_url, region):
        counter["value"] += 1
        return f"{proxy_url}|{region}|sid{counter['value']}", f"sid{counter['value']}"

    monkeypatch.setattr(kakao_payment, "kakao_proxy_with_fresh_sid", fake_refresh)
    monkeypatch.setattr(proxy_runtime, "preflight_payment_proxy_url", lambda proxy_url: payment_calls.append(proxy_url) or (True, "payment ok"))
    monkeypatch.setattr(proxy_runtime, "preflight_chatgpt_authenticated_proxy_url", lambda proxy_url, access_token: auth_calls.append(proxy_url) or (True, "auth ok"))
    monkeypatch.setattr(kakao_pay, "_preflight_kakao_checkout_backend_proxy_url", lambda proxy_url, access_token, region: (True, "checkout_backend ok"))

    cfg = kakao_pay.KakaoPayJobConfig(access_token="token", direct_proxies=[seed])

    result = kakao_pay._preflight_kakao_proxies_or_raise(cfg, lambda _message: None)

    assert payment_calls == [
        f"{seed}|KR|sid1",
        f"{seed}|VN|sid2",
        f"{seed}|KR|sid3",
    ]
    assert auth_calls == [payment_calls[0], payment_calls[2]]
    assert result.preflighted_checkout_proxy_url == payment_calls[0]
    assert result.preflighted_promotion_proxy_url == payment_calls[1]
    assert result.preflighted_provider_proxy_url == payment_calls[2]


def test_preflight_kakao_single_seed_retries_with_fresh_sid(monkeypatch):
    payment_calls = []
    seed = "socks5h://user-region-KR-session-fixed-sessTime-180-sessAuto-1:pass@example.com:3000"
    counter = {"value": 0}

    def fake_refresh(proxy_url, region):
        counter["value"] += 1
        return f"{proxy_url}|{region}|sid{counter['value']}", f"sid{counter['value']}"

    monkeypatch.setattr(kakao_payment, "kakao_proxy_with_fresh_sid", fake_refresh)
    monkeypatch.setattr(proxy_runtime, "preflight_payment_proxy_url", lambda proxy_url: payment_calls.append(proxy_url) or (False, "trace HTTP 200; chatgpt_home HTTP 403; html_challenge"))
    monkeypatch.setattr(proxy_runtime, "preflight_chatgpt_authenticated_proxy_url", lambda proxy_url, access_token: (True, "auth ok"))
    monkeypatch.setattr(kakao_pay, "_preflight_kakao_checkout_backend_proxy_url", lambda proxy_url, access_token, region: (True, "checkout_backend ok"))

    cfg = kakao_pay.KakaoPayJobConfig(access_token="token", direct_proxies=[seed])

    with pytest.raises(RuntimeError, match="Kakao 代理预检失败"):
        kakao_pay._preflight_kakao_proxies_or_raise(cfg, lambda _message: None)

    assert payment_calls == [f"{seed}|KR|sid{i}" for i in range(1, 11)]


def test_preflight_kakao_rejects_auth_ok_but_checkout_backend_challenged(monkeypatch):
    monkeypatch.setattr(proxy_runtime, "preflight_payment_proxy_url", lambda proxy_url: (True, "payment ok"))
    monkeypatch.setattr(proxy_runtime, "preflight_chatgpt_authenticated_proxy_url", lambda proxy_url, access_token: (True, "auth ok"))
    monkeypatch.setattr(
        kakao_pay,
        "_preflight_kakao_checkout_backend_proxy_url",
        lambda proxy_url, access_token, region: (False, "checkout_backend HTTP 403; html_challenge"),
    )

    cfg = kakao_pay.KakaoPayJobConfig(access_token="token", direct_proxies=["http://proxy"])

    with pytest.raises(RuntimeError, match="checkout_backend HTTP 403"):
        kakao_pay._preflight_kakao_proxies_or_raise(cfg, lambda _message: None)


def test_preflight_kakao_ignores_extra_proxy_entries_when_first_template_is_challenged(monkeypatch):
    seed1 = "socks5h://user-region-KR-session-seed1-sessTime-180-sessAuto-1:pass@example.com:3000"
    seed2 = "socks5h://user-region-KR-session-seed2-sessTime-180-sessAuto-1:pass@example.com:3000"
    payment_calls = []
    counter = {"value": 0}

    def fake_refresh(proxy_url, region):
        counter["value"] += 1
        return f"{proxy_url}|{region}|sid{counter['value']}", f"sid{counter['value']}"

    monkeypatch.setattr(kakao_payment, "kakao_proxy_with_fresh_sid", fake_refresh)
    monkeypatch.setattr(proxy_runtime, "preflight_payment_proxy_url", lambda proxy_url: payment_calls.append(proxy_url) or (False, "trace HTTP 200; chatgpt_home HTTP 403; html_challenge"))
    monkeypatch.setattr(proxy_runtime, "preflight_chatgpt_authenticated_proxy_url", lambda proxy_url, access_token: (True, "auth ok"))
    monkeypatch.setattr(kakao_pay, "_preflight_kakao_checkout_backend_proxy_url", lambda proxy_url, access_token, region: (True, "checkout_backend ok"))

    cfg = kakao_pay.KakaoPayJobConfig(access_token="token", direct_proxies=[seed1, seed2])

    with pytest.raises(RuntimeError, match="Kakao 代理预检失败"):
        kakao_pay._preflight_kakao_proxies_or_raise(cfg, lambda _message: None)

    assert payment_calls == [f"{seed1}|KR|sid{i}" for i in range(1, 11)]
    assert all(seed2 not in proxy_url for proxy_url in payment_calls)


def test_batch_account_stops_after_kakao_proxy_preflight_budget(monkeypatch):
    email = "blocked-kakao@example.com"
    preflighted = []
    monkeypatch.setattr(kakao_pay, "_load_token_for_email", lambda value: "token-" + value)

    def fake_payment_preflight(proxy_url):
        preflighted.append(proxy_url)
        return False, "trace HTTP 200; chatgpt_home HTTP 403; html_challenge"

    monkeypatch.setattr(proxy_runtime, "preflight_payment_proxy_url", fake_payment_preflight)
    monkeypatch.setattr(kakao_pay, "generate_kakao_trial", lambda cfg, log: pytest.fail("should not generate when proxy preflight fails"))
    job_id = "kakao-preflight-fail-job"
    kakao_pay.JOBS[job_id] = {
        "id": job_id, "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 1,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {},
    }

    req = kakao_pay.KakaoPayBatchStartRequest.model_validate({
        "accountEmails": [email],
        "proxies": "\n".join([
            "proxy1.example:1000:user-region-KR-sid-old1-t-120:pass",
            "proxy2.example:1000:user-region-KR-sid-old2-t-120:pass",
            "proxy3.example:1000:user-region-KR-sid-old3-t-120:pass",
            "proxy4.example:1000:user-region-KR-sid-old4-t-120:pass",
            "proxy5.example:1000:user-region-KR-sid-old5-t-120:pass",
            "proxy6.example:1000:user-region-KR-sid-old6-t-120:pass",
        ]),
        "maxAttempts": 5,
    })

    result = kakao_pay._run_batch_account(
        job_id,
        req,
        {"email": email, "auth_file": "auth.json"},
        1,
        1,
        kakao_pay._parse_proxies(req.proxies),
    )

    assert result["ok"] is False
    assert result["error"]["attempts"] == 1
    assert len(preflighted) == 10
    assert "Kakao 代理预检失败" in result["error"]["error"]
    assert any("代理预检已达到上限，停止真实提链" in line for line in kakao_pay.JOBS[job_id]["logs"])


def test_batch_account_uses_configured_proxy_preflight_attempts(monkeypatch):
    email = "blocked-kakao-configured@example.com"
    preflighted = []
    monkeypatch.setattr(kakao_pay, "_load_token_for_email", lambda value: "token-" + value)

    def fake_payment_preflight(proxy_url):
        preflighted.append(proxy_url)
        return False, "trace HTTP 200; chatgpt_home HTTP 403; html_challenge"

    monkeypatch.setattr(proxy_runtime, "preflight_payment_proxy_url", fake_payment_preflight)
    monkeypatch.setattr(kakao_pay, "generate_kakao_trial", lambda cfg, log: pytest.fail("should not generate when proxy preflight fails"))
    job_id = "kakao-configured-preflight-job"
    kakao_pay.JOBS[job_id] = {
        "id": job_id, "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 1,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {},
    }

    req = kakao_pay.KakaoPayBatchStartRequest.model_validate({
        "accountEmails": [email],
        "proxies": "\n".join([
            "proxy1.example:1000:user-region-KR-sid-old1-t-120:pass",
            "proxy2.example:1000:user-region-KR-sid-old2-t-120:pass",
            "proxy3.example:1000:user-region-KR-sid-old3-t-120:pass",
        ]),
        "maxAttempts": 5,
        "proxyPreflightAttempts": 2,
    })

    result = kakao_pay._run_batch_account(
        job_id,
        req,
        {"email": email, "auth_file": "auth.json"},
        1,
        1,
        kakao_pay._parse_proxies(req.proxies),
    )

    assert result["ok"] is False
    assert len(preflighted) == 2
    assert any("Kakao checkout 代理预检开始：2/2" in line for line in kakao_pay.JOBS[job_id]["logs"])


def test_kakao_proxy_preflight_attempts_cap_at_one_hundred():
    req = kakao_pay.KakaoPayBatchStartRequest.model_validate({
        "accountEmails": [],
        "proxyPreflightAttempts": 200,
    })

    assert req.proxy_preflight_attempts == 100


def test_kakao_routes_expose_job_and_link_management(monkeypatch):
    app = _app()
    monkeypatch.setattr(kakao_pay.threading, "Thread", lambda *args, **kwargs: type("DummyThread", (), {"start": lambda self: None})())

    start = _endpoint(app, "/api/kakao-pay/batch/start", "POST")(
        kakao_pay.KakaoPayBatchStartRequest.model_validate({"accountEmails": ["user@example.com"], "proxies": "host:1000:user:pass"})
    )
    job = _endpoint(app, "/api/kakao-pay/jobs/{job_id}", "GET")(start["job_id"])

    assert job["status"] == "queued"
    assert _endpoint(app, "/api/kakao-pay/links", "GET")() == {"links": [], "pruned_deleted_accounts": 0}


def test_mark_account_plus_kakao_sets_dashboard_plus_snapshot(monkeypatch):
    captured = {}
    monkeypatch.setattr(kakao_pay.account_store, "ensure_session_only_account", lambda email: captured.setdefault("ensured", email))

    def fake_update_account(email, **payload):
        captured["email"] = email
        captured["payload"] = payload
        return {"email": email, **payload}

    monkeypatch.setattr(kakao_pay.account_store, "update_account", fake_update_account)

    updated = kakao_pay._mark_account_plus_kakao("paid@example.com", "paid ok")

    assert captured["ensured"] == "paid@example.com"
    assert updated["account_type"] == kakao_pay.account_store.ACCOUNT_TYPE_PLUS
    assert updated["last_bind_provider"] == "kakao_pay"
    assert updated["last_bind_status"] == "success"
    assert updated["last_quota"]["plan_type"] == "plus"
