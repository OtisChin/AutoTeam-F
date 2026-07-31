from __future__ import annotations

import json

import pytest
from fastapi import FastAPI, HTTPException

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
    kakao_pay.KK_PAYMENT_JOBS.clear()
    yield
    kakao_pay.JOBS.clear()
    kakao_pay.KK_PAYMENT_JOBS.clear()


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
    assert kakao_pay.KAKAO_LINK_TTL_SECONDS == 900
    assert saved_link["kakao_ttl_seconds"] == kakao_pay.KAKAO_LINK_TTL_SECONDS
    assert saved_link["created_at_ts"] > 0
    assert saved_link["kakao_expires_at_ts"] - saved_link["created_at_ts"] == kakao_pay.KAKAO_LINK_TTL_SECONDS
    statuses = json.loads(kakao_pay.ACCOUNT_STATUS_FILE.read_text(encoding="utf-8"))
    assert statuses[email]["status"] == "success"


def test_batch_account_keeps_non_zero_amount_account(monkeypatch):
    email = "kakao-nonzero@example.com"
    deleted_accounts: list[str] = []
    deleted_sessions: list[str] = []
    monkeypatch.setattr(kakao_pay, "_load_token_for_email", lambda value: "token-" + value)
    monkeypatch.setattr(kakao_pay.account_store, "delete_account", lambda value: deleted_accounts.append(value) or True)
    monkeypatch.setattr(kakao_pay, "delete_auth_session", lambda value: deleted_sessions.append(value) or True)
    monkeypatch.setattr(
        kakao_pay,
        "generate_kakao_trial",
        lambda cfg, log: (_ for _ in ()).throw(
            RuntimeError("checkout_not_kakao_trial: stage=post_promo amount=29000 currency=krw methods=['card', 'kakao_pay']")
        ),
    )
    job_id = "kakao-nonzero-job"
    kakao_pay.JOBS[job_id] = {
        "id": job_id, "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 0,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {},
    }
    req = kakao_pay.KakaoPayBatchStartRequest.model_validate({
        "accountEmails": [email],
        "proxies": "host:1000:user-region-KR-sid-old-t-120:pass",
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
    assert result.get("account_deleted") is False
    assert result["error"]["account_deleted"] is False
    assert "金额非 0" in result["error"]["error"]
    assert "已从账号池删除" not in result["error"]["error"]
    assert deleted_accounts == []
    assert deleted_sessions == []


def test_batch_account_marks_already_paid_as_paid_status(monkeypatch):
    email = "kakao-paid@example.com"
    captured_updates = []
    monkeypatch.setattr(kakao_pay, "_load_token_for_email", lambda value: "token-" + value)
    monkeypatch.setattr(kakao_pay.account_store, "ensure_session_only_account", lambda value: None)
    monkeypatch.setattr(kakao_pay.account_store, "update_account", lambda email, **kwargs: captured_updates.append((email, kwargs)) or {"email": email, **kwargs})
    monkeypatch.setattr(
        kakao_pay,
        "generate_kakao_trial",
        lambda cfg, log: (_ for _ in ()).throw(RuntimeError("checkout failed: User is already pai")),
    )
    job_id = "kakao-paid-job"
    kakao_pay.JOBS[job_id] = {
        "id": job_id, "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 0,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {},
    }
    req = kakao_pay.KakaoPayBatchStartRequest.model_validate({
        "accountEmails": [email],
        "proxies": "host:1000:user-region-KR-sid-old-t-120:pass",
    })

    result = kakao_pay._run_batch_account(
        job_id,
        req,
        {"email": email, "auth_file": "auth.json"},
        1,
        1,
        kakao_pay._parse_proxies(req.proxies),
    )

    statuses = json.loads(kakao_pay.ACCOUNT_STATUS_FILE.read_text(encoding="utf-8"))
    assert result["skipped"] is True
    assert result["status"]["status"] == "paid"
    assert statuses[email]["status"] == "paid"
    assert captured_updates[0][0] == email
    assert captured_updates[0][1]["account_type"] == "plus"
    assert captured_updates[0][1]["last_bind_provider"] == "kakao_pay"
    assert captured_updates[0][1]["last_bind_status"] == "success"


def test_temp_batch_account_marks_already_paid_as_paid_status(monkeypatch):
    email = "kakao-temp-paid@example.com"
    captured_updates = []
    monkeypatch.setattr(kakao_pay, "_load_token_for_email", lambda value: "token-" + value)
    monkeypatch.setattr(kakao_pay.account_store, "ensure_session_only_account", lambda value: None)
    monkeypatch.setattr(kakao_pay.account_store, "update_account", lambda email, **kwargs: captured_updates.append((email, kwargs)) or {"email": email, **kwargs})
    monkeypatch.setattr(kakao_pay, "_create_kakao_temp_external_order", lambda access_token, cdk: {"ok": True, "job": {"job_id": "kscan-paid", "status": "queued"}})
    monkeypatch.setattr(
        kakao_pay,
        "_poll_kakao_temp_external_order",
        lambda order_id, cdk, cancel_check, progress_callback=None, poll_error_callback=None: (_ for _ in ()).throw(RuntimeError("User is already paid")),
    )
    job_id = "kakao-temp-paid-job"
    kakao_pay.JOBS[job_id] = {
        "id": job_id, "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 0,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {}, "temp": True,
        "external_jobs": {},
    }

    result = kakao_pay._run_temp_batch_account(job_id, {"email": email, "auth_file": "auth.json"}, "KSCAN-1", 1, 1)

    statuses = json.loads(kakao_pay.ACCOUNT_STATUS_FILE.read_text(encoding="utf-8"))
    assert result["skipped"] is True
    assert result["status"]["status"] == "paid"
    assert statuses[email]["status"] == "paid"
    assert captured_updates[0][0] == email
    assert captured_updates[0][1]["account_type"] == "plus"
    assert captured_updates[0][1]["last_bind_provider"] == "kakao_pay"
    assert captured_updates[0][1]["last_bind_status"] == "success"


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
        f"{seed}|JP|sid2",
        f"{seed}|KR|sid3",
    ]
    assert auth_calls == [payment_calls[0], payment_calls[2]]
    assert result.preflighted_checkout_proxy_url == payment_calls[0]
    assert result.preflighted_promotion_proxy_url == payment_calls[1]
    assert result.preflighted_provider_proxy_url == payment_calls[2]


def test_preflight_kakao_proxy_role_uses_configured_promotion_backend_region(monkeypatch):
    backend_calls = []
    monkeypatch.setattr(proxy_runtime, "preflight_payment_proxy_url", lambda proxy_url: (True, "payment ok"))
    monkeypatch.setattr(proxy_runtime, "preflight_chatgpt_authenticated_proxy_url", lambda proxy_url, access_token: (True, "auth ok"))
    monkeypatch.setattr(
        kakao_pay,
        "_preflight_kakao_checkout_backend_proxy_url",
        lambda proxy_url, access_token, region: backend_calls.append(region) or (True, "checkout_backend ok"),
    )
    cfg = kakao_pay.KakaoPayJobConfig(
        access_token="token",
        promotion_region="JP",
        direct_proxies=["socks5h://user-region-KR-session-fixed-sessTime-180-sessAuto-1:pass@example.com:3000"],
    )

    ok, _proxy_url, _message = kakao_pay._preflight_kakao_proxy_role(
        cfg,
        role="promotion",
        stage_index=1,
        require_auth=True,
        attempt=1,
        total_attempts=1,
        log=lambda _message: None,
    )

    assert ok is True
    assert backend_calls == ["JP"]


def test_preflight_kakao_single_seed_removes_failed_proxy_without_reusing_it(monkeypatch):
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

    assert payment_calls == [f"{seed}|KR|sid1"]


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


def test_preflight_kakao_rotates_extra_proxy_entries_when_template_is_challenged(monkeypatch):
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

    assert len(payment_calls) == 2
    assert seed1 in payment_calls[0]
    assert seed2 in payment_calls[1]


def test_preflight_kakao_logs_proxy_slot_label(monkeypatch):
    logs: list[str] = []
    seed1 = "proxy1.example:1000:user-region-KR-sid-old1-t-120:pass"
    seed2 = "proxy2.example:1000:user-region-KR-sid-old2-t-120:pass"

    monkeypatch.setattr(proxy_runtime, "preflight_payment_proxy_url", lambda proxy_url: (True, "payment ok"))
    monkeypatch.setattr(proxy_runtime, "preflight_chatgpt_authenticated_proxy_url", lambda proxy_url, access_token: (True, "auth ok"))
    monkeypatch.setattr(kakao_pay, "_preflight_kakao_checkout_backend_proxy_url", lambda proxy_url, access_token, region: (True, "checkout_backend ok"))

    cfg = kakao_pay.KakaoPayJobConfig(access_token="token", direct_proxies=[seed2])

    kakao_pay._preflight_kakao_proxies_or_raise(
        cfg,
        logs.append,
        proxy_label_fn=lambda proxy: kakao_pay._proxy_label_from_pool([seed1, seed2], proxy),
    )

    assert any("proxy#2/2 fp=" in line and "direct-1" not in line for line in logs)


def test_batch_account_rotates_proxy_pool_by_account_index(monkeypatch):
    email = "rotate-kakao@example.com"
    seen_direct_proxies = []
    monkeypatch.setattr(kakao_pay, "_load_token_for_email", lambda value: "token-" + value)

    def fake_preflight(cfg, log, max_attempts=None, on_proxy_failed=None, proxy_label_fn=None):
        seen_direct_proxies.append(list(cfg.direct_proxies))
        return cfg

    monkeypatch.setattr(kakao_pay, "_preflight_kakao_proxies_or_raise", fake_preflight)
    monkeypatch.setattr(kakao_pay, "generate_kakao_trial", lambda cfg, log: {"ok": True, "fields": {"provider_redirect_url": "https://pay.nicepay.co.kr/rotated", "billing": {"country": "KR"}}})
    job_id = "kakao-rotate-proxy-job"
    kakao_pay.JOBS[job_id] = {
        "id": job_id, "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 2,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
            "running_count": 0, "skipped": [], "account_statuses": {}, "proxy_pool": kakao_pay._parse_proxies("proxy-one:1000:user:pass\nproxy-two:1000:user:pass\nproxy-three:1000:user:pass"),
    }
    req = kakao_pay.KakaoPayBatchStartRequest.model_validate({
        "accountEmails": [email],
        "proxies": "proxy-one:1000:user:pass\nproxy-two:1000:user:pass\nproxy-three:1000:user:pass",
    })

    kakao_pay._run_batch_account(job_id, req, {"email": email, "auth_file": "auth.json"}, 2, 3, kakao_pay._parse_proxies(req.proxies))

    assert seen_direct_proxies[0] == ["proxy-two:1000:user:pass", "proxy-three:1000:user:pass", "proxy-one:1000:user:pass"]


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
    assert len(preflighted) == 6
    assert kakao_pay.JOBS[job_id]["proxy_pool"] == []
    assert len(kakao_pay.JOBS[job_id]["bad_proxies"]) == 6
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


def test_batch_account_stops_immediately_on_approve_blocked_without_burning_more_proxies(monkeypatch):
    email = "approve-blocked-kakao@example.com"
    calls = {"preflight": 0, "generate": 0}
    monkeypatch.setattr(kakao_pay, "_load_token_for_email", lambda value: "token-" + value)

    def fake_preflight(cfg, log, max_attempts=None, on_proxy_failed=None, proxy_label_fn=None):
        calls["preflight"] += 1
        return cfg

    def fake_generate(cfg, log):
        calls["generate"] += 1
        raise RuntimeError("approve failed: unexpected result: 'blocked'")

    monkeypatch.setattr(kakao_pay, "_preflight_kakao_proxies_or_raise", fake_preflight)
    monkeypatch.setattr(kakao_pay, "generate_kakao_trial", fake_generate)
    job_id = "kakao-approval-masked-job"
    kakao_pay.JOBS[job_id] = {
        "id": job_id, "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 1,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {},
    }
    req = kakao_pay.KakaoPayBatchStartRequest.model_validate({
        "accountEmails": [email],
        "proxies": "host:1000:user-region-KR-sid-old-t-120:pass",
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
    assert result["error"]["failure_stage"] == "approve_blocked"
    assert "approve failed: unexpected result: 'blocked'" in result["error"]["error"]
    assert "后续代理预检失败" not in result["error"]["error"]
    assert calls == {"preflight": 1, "generate": 1}
    assert any("Kakao approve 被拦截，停止重试避免继续消耗代理" in line for line in kakao_pay.JOBS[job_id]["logs"])
    statuses = json.loads(kakao_pay.ACCOUNT_STATUS_FILE.read_text(encoding="utf-8"))
    assert statuses[email]["failure_stage"] == "approve_blocked"


def test_kakao_proxy_preflight_attempts_cap_at_one_hundred():
    req = kakao_pay.KakaoPayBatchStartRequest.model_validate({
        "accountEmails": [],
        "proxyPreflightAttempts": 200,
    })

    assert req.proxy_preflight_attempts == 100


def test_job_snapshot_masks_bad_proxy_credentials():
    job_id = "kakao-bad-proxy-snapshot"
    raw_proxy = "gate2.ipweb.cc:7778:B_91859_KR_2528__90_E9aeHKHX:secret-pass"
    kakao_pay.JOBS[job_id] = {
        "id": job_id, "status": "running", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 1,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {}, "proxy_pool": [],
        "bad_proxies": [{"proxy": raw_proxy, "reason": "checkout: html_challenge"}],
    }

    snapshot = kakao_pay._job_snapshot(job_id)

    bad_proxy = snapshot["bad_proxies"][0]["proxy"]
    assert "secret-pass" not in bad_proxy
    assert "fp=" in bad_proxy
    assert snapshot["bad_proxies"][0]["proxy_fp"]


def test_kakao_routes_expose_job_and_link_management(monkeypatch):
    app = _app()
    monkeypatch.setattr(kakao_pay.threading, "Thread", lambda *args, **kwargs: type("DummyThread", (), {"start": lambda self: None})())

    start = _endpoint(app, "/api/kakao-pay/batch/start", "POST")(
        kakao_pay.KakaoPayBatchStartRequest.model_validate({"accountEmails": ["user@example.com"], "proxies": "host:1000:user:pass"})
    )
    job = _endpoint(app, "/api/kakao-pay/jobs/{job_id}", "GET")(start["job_id"])

    assert job["status"] == "queued"
    assert _endpoint(app, "/api/kakao-pay/links", "GET")() == {"links": [], "pruned_deleted_accounts": 0}


def test_kakao_temp_extract_order_routes_proxy_masi_api(monkeypatch):
    app = _app()
    calls = []

    class Resp:
        ok = True
        status_code = 201
        text = '{"ok": true}'

        def json(self):
            return {"ok": True, "job": {"job_id": "job_1", "status": "queued"}}

    def fake_post(url, **kwargs):
        calls.append(("post", url, kwargs))
        return Resp()

    monkeypatch.setattr(kakao_pay.requests, "post", fake_post)

    data = _endpoint(app, "/api/kakao-pay/temp/orders", "POST")(
        kakao_pay.KakaoPayTempOrderRequest.model_validate({"cdk": "KSCAN-1", "accessToken": "at-test"})
    )

    assert data["job"]["job_id"] == "job_1"
    assert calls[0][1] == "https://masi.cc.cd/v1/kakao/jobs"
    assert calls[0][2]["headers"]["X-CDK"] == "KSCAN-1"
    assert calls[0][2]["json"] == {"access_token": "at-test"}


def test_kakao_temp_extract_ticket_status_uses_extract_cdk_endpoint(monkeypatch):
    app = _app()
    calls = []

    class Resp:
        ok = True
        status_code = 200
        text = '{"ok": true}'

        def json(self):
            return {"ok": True, "cdk": {"total_uses": 5, "available_uses": 4, "pending_uses": 1}}

    def fake_get(url, **kwargs):
        calls.append(("get", url, kwargs))
        return Resp()

    monkeypatch.setattr(kakao_pay.requests, "get", fake_get)

    data = _endpoint(app, "/api/kakao-pay/temp/tickets/status", "POST")(
        kakao_pay.KakaoPayTempTicketRequest.model_validate({"cdk": "KSCAN-1"})
    )

    assert data["cdk"]["available_uses"] == 4
    assert calls[0][1] == "https://masi.cc.cd/v1/cdk/status"
    assert calls[0][2]["headers"]["X-CDK"] == "KSCAN-1"


def test_kakao_temp_extract_ticket_status_supports_get_for_compatibility(monkeypatch):
    app = _app()
    calls = []

    class Resp:
        ok = True
        status_code = 200
        text = '{"ok": true}'

        def json(self):
            return {"ok": True, "cdk": {"total_uses": 5, "available_uses": 3}}

    monkeypatch.setattr(kakao_pay.requests, "get", lambda url, **kwargs: calls.append((url, kwargs)) or Resp())

    data = _endpoint(app, "/api/kakao-pay/temp/tickets/status", "GET")(cdk="KSCAN-GET")

    assert data["cdk"]["available_uses"] == 3
    assert calls[0][0] == "https://masi.cc.cd/v1/cdk/status"
    assert calls[0][1]["headers"]["X-CDK"] == "KSCAN-GET"


def test_kakao_temp_batch_uses_selected_accounts_and_cdks(monkeypatch):
    emails = ["one@example.com", "two@example.com"]
    created_calls = []
    polled_calls = []
    monkeypatch.setattr(kakao_pay, "_iter_auth_accounts", lambda include_paid=False: [
        {"email": "one@example.com", "auth_file": "auth-one.json"},
        {"email": "two@example.com", "auth_file": "auth-two.json"},
        {"email": "unused@example.com", "auth_file": "auth-unused.json"},
    ])
    monkeypatch.setattr(kakao_pay, "_load_token_for_email", lambda email: f"token:{email}")

    def fake_create(access_token, cdk):
        created_calls.append((access_token, cdk))
        index = len(created_calls)
        return {"ok": True, "job": {"job_id": f"job_{index}", "status": "queued"}}

    def fake_poll(order_id, cdk, cancel_check, progress_callback=None, poll_error_callback=None):
        polled_calls.append((order_id, cdk, cancel_check()))
        if progress_callback:
            progress_callback({"job_id": order_id, "status": "extracting", "code": "FETCH_CHECKOUT", "message": "正在提取支付链接"})
        return {"ok": True, "job": {"job_id": order_id, "status": "completed", "output": {"long_url": f"https://pay.nicepay.co.kr/{order_id}"}}}

    monkeypatch.setattr(kakao_pay, "_create_kakao_temp_external_order", fake_create)
    monkeypatch.setattr(kakao_pay, "_poll_kakao_temp_external_order", fake_poll)
    job_id = "kakao-temp-job"
    kakao_pay.JOBS[job_id] = {
        "id": job_id, "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 0,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {}, "temp": True,
        "external_jobs": {},
    }
    req = kakao_pay.KakaoPayTempBatchStartRequest.model_validate({
        "accountEmails": emails,
        "cdks": ["KSCAN-ONE", "KSCAN-TWO"],
        "concurrency": 1,
    })

    kakao_pay._run_temp_batch_job(job_id, req)

    job = kakao_pay.JOBS[job_id]
    assert job["status"] == "success"
    assert job["temp"] is True
    assert job["completed"] == 2
    assert created_calls == [("token:one@example.com", "KSCAN-ONE"), ("token:two@example.com", "KSCAN-TWO")]
    assert polled_calls == [("job_1", "KSCAN-ONE", False), ("job_2", "KSCAN-TWO", False)]
    assert [item["cdk"] for item in job["result"]["successes"]] == ["KSCAN-ONE", "KSCAN-TWO"]
    assert any("FETCH_CHECKOUT" in line for line in job["logs"])
    saved_links = json.loads(kakao_pay.LINKS_FILE.read_text(encoding="utf-8"))
    assert [item["account_email"] for item in saved_links] == ["two@example.com", "one@example.com"]
    assert saved_links[0]["kakao_ttl_seconds"] == kakao_pay.KAKAO_LINK_TTL_SECONDS


def test_kakao_temp_poll_retries_transient_read_timeout(monkeypatch):
    calls = []
    errors = []
    sleeps = []

    def fake_get(order_id, cdk):
        calls.append((order_id, cdk))
        if len(calls) == 1:
            raise RuntimeError("Kakao 临时提链服务轮询失败：HTTPSConnectionPool(host='masi.cc.cd', port=443): Read timed out. (read timeout=20)")
        return {"ok": True, "job": {"job_id": order_id, "status": "completed", "output": {"long_url": "https://pay.nicepay.co.kr/ok"}}}

    monkeypatch.setattr(kakao_pay, "_get_kakao_temp_external_order", fake_get)
    monkeypatch.setattr(kakao_pay.time, "sleep", lambda value: sleeps.append(value))

    data = kakao_pay._poll_kakao_temp_external_order(
        "job-timeout",
        "KSCAN-1",
        lambda: False,
        poll_error_callback=lambda message, count: errors.append((message, count)),
    )

    assert data["job"]["status"] == "completed"
    assert len(calls) == 2
    assert sleeps == [2.0]
    assert errors and errors[0][1] == 1
    assert "继续等待" in errors[0][0]


def test_kakao_kk_payment_order_routes_use_customer_api_headers(monkeypatch):
    app = _app()
    calls = []

    class SubmitResp:
        ok = True
        status_code = 201
        text = '{"ok": true}'

        def json(self):
            return {
                "ok": True,
                "data": {
                    "order": {"id": "order_kk", "status": "PENDING"},
                    "customerToken": "customer-token",
                    "pollUrl": "/api/v1/customer/orders/order_kk",
                },
            }

    class PollResp:
        ok = True
        status_code = 200
        text = '{"ok": true}'

        def json(self):
            return {"ok": True, "data": {"order": {"id": "order_kk", "status": "SUCCESS"}}}

    def fake_post(url, **kwargs):
        calls.append(("post", url, kwargs))
        return SubmitResp()

    def fake_get(url, **kwargs):
        calls.append(("get", url, kwargs))
        return PollResp()

    monkeypatch.setattr(kakao_pay.requests, "post", fake_post)
    monkeypatch.setattr(kakao_pay.requests, "get", fake_get)

    created = _endpoint(app, "/api/kakao-pay/kk-payment/orders", "POST")(
        kakao_pay.KakaoPayCustomerOrderRequest.model_validate({
            "cdk": "PAY-CDK",
            "accessToken": "at-test",
            "paymentUrl": "https://pay.nicepay.co.kr/v1/checkout/pay/abc",
            "paymentMethod": "kakao_pay",
            "mode": "READY_LINK",
        })
    )
    polled = _endpoint(app, "/api/kakao-pay/kk-payment/orders/{order_id}", "GET")("order_kk", token="customer-token", cdk="")

    assert created["data"]["order"]["id"] == "order_kk"
    assert calls[0][1] == "https://customer.i7wap.xyz/api/v1/customer/orders"
    assert calls[0][2]["headers"]["X-CDK-Key"] == "PAY-CDK"
    assert calls[0][2]["json"]["channel"] == "KAKAO_KK"
    assert calls[0][2]["json"]["mode"] == "READY_LINK"
    assert calls[0][2]["json"]["productType"] == "KAKAO_AT"
    assert calls[0][2]["json"]["payment_url"].startswith("https://pay.nicepay.co.kr/")
    assert polled["data"]["order"]["status"] == "SUCCESS"
    assert calls[1][2]["headers"]["Authorization"] == "Bearer customer-token"


def test_kakao_kk_payment_cdk_status_uses_customer_check_api(monkeypatch):
    app = _app()
    calls = []

    class Resp:
        ok = True
        status_code = 200
        text = '{"ok": true}'

        def json(self):
            return {
                "ok": True,
                "data": {
                    "orders": [
                        {
                            "id": "order-1",
                            "cdk": {
                                "productType": "KAKAO_AT",
                                "totalCount": 10,
                                "usedCount": 2,
                                "frozenCount": 1,
                                "availableCount": 7,
                            },
                        }
                    ]
                },
            }

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return Resp()

    monkeypatch.setattr(kakao_pay.requests, "get", fake_get)

    data = _endpoint(app, "/api/kakao-pay/kk-payment/cdk/status", "POST")(
        kakao_pay.KakaoPayTempTicketRequest.model_validate({"cdk": "PAY-CDK"})
    )

    assert data["data"]["productType"] == "KAKAO_AT"
    assert data["data"]["availableCount"] == 7
    assert calls[0][0] == "https://customer.i7wap.xyz/api/v1/customer/orders"
    assert calls[0][1]["headers"]["X-CDK-Key"] == "PAY-CDK"
    assert calls[0][1]["params"] == {"page": 1, "pageSize": 100}


def test_kakao_kk_payment_cdk_status_uses_customer_cdk_orders_when_no_orders(monkeypatch):
    app = _app()
    calls = []

    class LegacyOrdersResp:
        ok = True
        status_code = 200
        text = '{"ok": true, "data": {"orders": []}}'

        def json(self):
            return {"ok": True, "data": {"orders": []}}

    class CdkOrdersResp:
        ok = True
        status_code = 200
        text = '{"ok": true}'

        def json(self):
            return {
                "ok": True,
                "data": {
                    "cdk": {
                        "code": "PAY-CDK",
                        "productType": "KAKAO_AT",
                        "totalCount": 20,
                        "usedCount": 0,
                        "frozenCount": 0,
                        "availableCount": 20,
                        "status": "ACTIVE",
                    },
                    "orders": [],
                },
            }

    def fake_get(url, **kwargs):
        calls.append(("GET", url, kwargs))
        return LegacyOrdersResp()

    def fake_post(url, **kwargs):
        calls.append(("POST", url, kwargs))
        return CdkOrdersResp()

    monkeypatch.setattr(kakao_pay.requests, "get", fake_get)
    monkeypatch.setattr(kakao_pay.requests, "post", fake_post)

    data = _endpoint(app, "/api/kakao-pay/kk-payment/cdk/status", "POST")(
        kakao_pay.KakaoPayTempTicketRequest.model_validate({"cdk": "PAY-CDK"})
    )

    assert data["data"]["availableCount"] == 20
    assert data["data"]["totalCount"] == 20
    assert data["orders"] == []
    assert calls == [
        (
            "GET",
            "https://customer.i7wap.xyz/api/v1/customer/orders",
            {
                "params": {"page": 1, "pageSize": 100},
                "headers": {"Accept": "application/json", "X-CDK-Key": "PAY-CDK"},
                "timeout": 20,
            },
        ),
        (
            "POST",
            "https://customer.i7wap.xyz/api/customer/cdk/orders",
            {
                "json": {"code": "PAY-CDK"},
                "headers": {"Accept": "application/json", "Content-Type": "application/json"},
                "timeout": 20,
            },
        ),
    ]


def test_kakao_kk_payment_submit_uses_account_session_cookie_and_extracted_link(monkeypatch):
    app = _app()
    email = "pay@example.com"
    link_id = "link-1"
    calls = []
    kakao_pay._append_link({
        "id": link_id,
        "account_email": email,
        "provider_redirect_url": "https://pay.nicepay.co.kr/v1/checkout/pay/kakao-1",
        "kakao_link": "https://pay.nicepay.co.kr/v1/checkout/pay/kakao-1",
        "created_at": "2026-07-30 10:00:00",
        "created_at_ts": 1785386400,
        "kakao_expires_at_ts": 1785387000,
        "country": "KR",
    })
    monkeypatch.setattr(kakao_pay, "_load_token_for_email", lambda value: f"token-for:{value}")
    monkeypatch.setattr(kakao_pay, "load_auth_session", lambda value: {"cookie_header": "__Secure-next-auth.session-token=session-for-pay", "accessToken": f"access-for:{value}"})

    class SubmitResp:
        ok = True
        status_code = 201
        text = '{"ok": true}'

        def json(self):
            return {"ok": True, "data": {"order": {"id": "kk-order-1", "status": "PENDING"}, "customerToken": "customer-token"}}

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return SubmitResp()

    monkeypatch.setattr(kakao_pay.requests, "post", fake_post)

    data = _endpoint(app, "/api/kakao-pay/kk-payment/submit", "POST")(
        kakao_pay.KakaoPayKkPaymentSubmitRequest.model_validate({
            "cdk": "KK-CDK-1",
            "linkId": link_id,
            "paymentMethod": "kakao_pay",
        })
    )

    assert data["account_email"] == email
    assert data["link_id"] == link_id
    assert data["payment_url"] == "https://pay.nicepay.co.kr/v1/checkout/pay/kakao-1"
    assert calls[0][0] == "https://customer.i7wap.xyz/api/v1/customer/orders"
    assert calls[0][1]["headers"]["X-CDK-Key"] == "KK-CDK-1"
    assert calls[0][1]["json"]["session_cookie"] == "__Secure-next-auth.session-token=session-for-pay"
    assert calls[0][1]["json"]["credential"] == "__Secure-next-auth.session-token=session-for-pay"
    assert calls[0][1]["json"]["access_token"] == f"access-for:{email}"
    assert calls[0][1]["json"]["payment_url"] == "https://pay.nicepay.co.kr/v1/checkout/pay/kakao-1"
    assert calls[0][1]["json"]["productType"] == "KAKAO_AT"
    assert kakao_pay.KK_PAYMENT_JOBS["kk-order-1"]["account_email"] == email


def test_kakao_kk_payment_submit_preserves_new_channel_disabled_error(monkeypatch):
    app = _app()
    email = "channel-disabled@example.com"
    link_id = "link-channel-disabled"
    calls = []
    kakao_pay._append_link({
        "id": link_id,
        "account_email": email,
        "provider_redirect_url": "https://pay.nicepay.co.kr/v1/checkout/pay/channel-disabled",
        "created_at_ts": 1785386400,
        "kakao_expires_at_ts": 1785387300,
        "country": "KR",
    })
    monkeypatch.setattr(kakao_pay, "_load_kakao_customer_credentials_for_email", lambda value: ("cookie-channel-disabled", f"token-for:{value}"))

    class DisabledResp:
        ok = False
        status_code = 422
        text = '{"error":{"code":"kakao_provider_error","message":"韩国 KK 渠道当前未开放 / Korea KK channel is disabled"}}'

        def json(self):
            return {"error": {"code": "kakao_provider_error", "message": "韩国 KK 渠道当前未开放 / Korea KK channel is disabled"}}

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return DisabledResp()

    monkeypatch.setattr(kakao_pay.requests, "post", fake_post)

    with pytest.raises(HTTPException) as exc:
        _endpoint(app, "/api/kakao-pay/kk-payment/submit", "POST")(
            kakao_pay.KakaoPayKkPaymentSubmitRequest.model_validate({
                "cdk": "KK-CDK-CHANNEL-DISABLED",
                "linkId": link_id,
                "paymentMethod": "kakao_pay",
            })
        )

    assert exc.value.status_code == 422
    assert exc.value.detail["error"]["code"] == "kakao_provider_error"
    assert len(calls) == 1
    assert calls[0][0] == "https://customer.i7wap.xyz/api/v1/customer/orders"


def test_kakao_kk_payment_cancel_and_resubmit_routes_call_customer_api(monkeypatch):
    app = _app()
    calls = []

    class Resp:
        ok = True
        status_code = 200
        text = '{"ok": true}'

        def json(self):
            return {"ok": True, "data": {"order": {"id": "order-cancel", "status": "CANCELLED", "problemReason": "customer_cancelled"}}}

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return Resp()

    monkeypatch.setattr(kakao_pay.requests, "post", fake_post)

    cancelled = _endpoint(app, "/api/kakao-pay/kk-payment/orders/{order_id}/cancel", "POST")("order-cancel", token="customer-token", cdk="")
    resubmitted = _endpoint(app, "/api/kakao-pay/kk-payment/orders/{order_id}/resubmit", "POST")("order-cancel", token="", cdk="PAY-CDK")

    assert cancelled["data"]["order"]["status"] == "CANCELLED"
    assert calls[0][0] == "https://customer.i7wap.xyz/api/v1/customer/orders/order-cancel/cancel"
    assert calls[0][1]["headers"]["Authorization"] == "Bearer customer-token"
    assert calls[1][0] == "https://customer.i7wap.xyz/api/v1/customer/orders/order-cancel/resubmit"
    assert calls[1][1]["headers"]["X-CDK-Key"] == "PAY-CDK"


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


def test_kk_payment_success_ignores_fastapi_query_default_email(monkeypatch):
    from fastapi import Query

    captured = {}

    def fake_mark_account_plus(email, message):
        captured["email"] = email
        captured["message"] = message
        return {"email": email, "account_type": "plus", "last_bind_provider": "kakao_pay"}

    monkeypatch.setattr(kakao_pay, "_mark_account_plus_kakao", fake_mark_account_plus)
    monkeypatch.setattr(kakao_pay, "_set_account_status", lambda email, status, job_id="": captured.setdefault("status_email", email))

    with kakao_pay.KK_PAYMENT_JOBS_LOCK:
        kakao_pay.KK_PAYMENT_JOBS.clear()
        kakao_pay.KK_PAYMENT_JOBS["kk-order-query-default"] = {
            "account_email": "real@example.com",
            "account_marked": False,
            "account_update": {},
        }

    result = kakao_pay._mark_kk_payment_success_account(
        "kk-order-query-default",
        Query("", alias="accountEmail"),
        "paid ok",
    )

    assert captured["email"] == "real@example.com"
    assert captured["status_email"] == "real@example.com"
    assert result["email"] == "real@example.com"
