from __future__ import annotations

import json
import threading

from fastapi import FastAPI

from autotoken.api_routes import momo_vn
from autotoken.interfaces import api as api_interface


def _app():
    app = FastAPI()
    app.include_router(momo_vn.create_momo_vn_router())
    return app


def _endpoint(app, path, method):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"missing route {method} {path}")


def _make_job(job_id: str) -> dict[str, object]:
    return {
        "id": job_id,
        "status": "queued",
        "logs": [],
        "result": None,
        "error": None,
        "created_at": 1.0,
        "finished_at": None,
        "account_email": "",
        "total": 0,
        "completed": 0,
        "concurrency": 1,
        "cancel_requested": False,
        "running_count": 0,
        "skipped": [],
        "account_statuses": {},
    }


def test_main_api_includes_momo_vn_router():
    paths = {getattr(route, "path", "") for route in api_interface.app.routes}
    assert "/api/momo-vn/accounts" in paths
    assert "/api/momo-vn/batch/start" in paths


def test_accounts_default_to_pending_momo_status(monkeypatch, tmp_path):
    app = _app()
    monkeypatch.setattr(momo_vn, "LINKS_FILE", tmp_path / "momo_vn_links.json")
    monkeypatch.setattr(momo_vn, "ACCOUNT_STATUS_FILE", tmp_path / "momo_vn_account_status.json")
    monkeypatch.setattr(momo_vn.account_store, "load_accounts", lambda: [
        {"email": "free@example.com", "status": "active", "account_type": "free", "ttl_seconds": 3600},
        {"email": "plus@example.com", "status": "active", "account_type": "plus", "ttl_seconds": 7200},
    ])
    monkeypatch.setattr(momo_vn, "_iter_auth_accounts", lambda include_paid=False: [
        {"email": "free@example.com", "auth_file": "auth-free.json"},
        {"email": "plus@example.com", "auth_file": "auth-plus.json"},
    ])

    result = _endpoint(app, "/api/momo-vn/accounts", "GET")()

    assert [row["email"] for row in result["accounts"]] == ["free@example.com", "plus@example.com"]
    assert result["accounts"][0]["momo_status"] == "pending"
    assert result["accounts"][0]["momo_status_text"] == "未提链"
    assert result["accounts"][0]["momo_selectable"] is True
    assert result["accounts"][1]["momo_status"] == "paid"
    assert result["accounts"][1]["momo_status_text"] == "已支付"
    assert result["accounts"][1]["momo_selectable"] is False


def test_batch_job_qualification_only_marks_eligible_and_ineligible_without_links(monkeypatch, tmp_path):
    monkeypatch.setattr(momo_vn, "LINKS_FILE", tmp_path / "momo_vn_links.json")
    monkeypatch.setattr(momo_vn, "ACCOUNT_STATUS_FILE", tmp_path / "momo_vn_account_status.json")
    monkeypatch.setattr(
        momo_vn,
        "_iter_auth_accounts",
        lambda include_paid=False: [
            {"email": "eligible@example.com", "auth_file": "eligible.json"},
            {"email": "ineligible@example.com", "auth_file": "ineligible.json"},
        ],
    )
    monkeypatch.setattr(momo_vn, "_load_token_for_email", lambda email: f"token-{email}")
    monkeypatch.setattr(
        momo_vn,
        "detect_momo_eligibility",
        lambda cfg, log=None: {"status": "eligible", "has_momo": True} if cfg.access_token == "token-eligible@example.com" else {"status": "ineligible", "has_momo": False},
    )
    monkeypatch.setattr(momo_vn, "generate_momo_vn_trial", lambda cfg, log=None: (_ for _ in ()).throw(AssertionError("qualificationOnly should not extract links")))

    job_id = "momo-qualification-only-job"
    momo_vn.JOBS.clear()
    momo_vn.JOBS[job_id] = _make_job(job_id)
    req = momo_vn.MomoVnBatchStartRequest.model_validate({
        "accountEmails": ["eligible@example.com", "ineligible@example.com"],
        "proxies": "proxy",
        "qualificationOnly": True,
    })

    momo_vn._run_batch_job(job_id, req)

    statuses = json.loads(momo_vn.ACCOUNT_STATUS_FILE.read_text(encoding="utf-8"))
    assert statuses["eligible@example.com"]["status"] == "eligible"
    assert statuses["ineligible@example.com"]["status"] == "ineligible"
    assert not momo_vn.LINKS_FILE.exists()
    assert momo_vn.JOBS[job_id]["status"] == "success"


def test_batch_job_full_flow_marks_failed_when_extraction_fails_after_eligibility(monkeypatch, tmp_path):
    monkeypatch.setattr(momo_vn, "LINKS_FILE", tmp_path / "momo_vn_links.json")
    monkeypatch.setattr(momo_vn, "ACCOUNT_STATUS_FILE", tmp_path / "momo_vn_account_status.json")
    monkeypatch.setattr(momo_vn, "_load_token_for_email", lambda email: f"token-{email}")
    monkeypatch.setattr(momo_vn, "detect_momo_eligibility", lambda cfg, log=None: {"status": "eligible", "has_momo": True})
    monkeypatch.setattr(momo_vn, "generate_momo_vn_trial", lambda cfg, log=None: (_ for _ in ()).throw(RuntimeError("approve failed")))

    job_id = "momo-failed-job"
    momo_vn.JOBS.clear()
    momo_vn.JOBS[job_id] = _make_job(job_id)
    req = momo_vn.MomoVnBatchStartRequest.model_validate({
        "accountEmails": ["user@example.com"],
        "proxies": "proxy",
    })

    result = momo_vn._run_batch_account(
        job_id,
        req,
        {"email": "user@example.com", "auth_file": "auth.json"},
        1,
        1,
        momo_vn._parse_proxies(req.proxies),
    )

    statuses = json.loads(momo_vn.ACCOUNT_STATUS_FILE.read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert statuses["user@example.com"]["status"] == "failed"


def test_batch_account_keeps_non_zero_amount_account(monkeypatch, tmp_path):
    email = "momo-nonzero@example.com"
    deleted_accounts: list[str] = []
    deleted_sessions: list[str] = []
    monkeypatch.setattr(momo_vn, "LINKS_FILE", tmp_path / "momo_vn_links.json")
    monkeypatch.setattr(momo_vn, "ACCOUNT_STATUS_FILE", tmp_path / "momo_vn_account_status.json")
    monkeypatch.setattr(momo_vn, "_load_token_for_email", lambda value: f"token-{value}")
    monkeypatch.setattr(momo_vn, "detect_momo_eligibility", lambda cfg, log=None: {"status": "eligible", "has_momo": True})
    monkeypatch.setattr(
        momo_vn,
        "generate_momo_vn_trial",
        lambda cfg, log=None: (_ for _ in ()).throw(RuntimeError("套 promo 后金额不是 0: 1667")),
    )
    monkeypatch.setattr(momo_vn.account_store, "delete_account", lambda value: deleted_accounts.append(value) or True)
    monkeypatch.setattr(momo_vn, "delete_auth_session", lambda value: deleted_sessions.append(value) or True)

    job_id = "momo-nonzero-job"
    momo_vn.JOBS.clear()
    momo_vn.JOBS[job_id] = _make_job(job_id)
    req = momo_vn.MomoVnBatchStartRequest.model_validate({
        "accountEmails": [email],
        "proxies": "proxy",
        "maxAttempts": 5,
    })

    result = momo_vn._run_batch_account(
        job_id,
        req,
        {"email": email, "auth_file": "auth.json"},
        1,
        1,
        momo_vn._parse_proxies(req.proxies),
    )

    statuses = json.loads(momo_vn.ACCOUNT_STATUS_FILE.read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert result.get("account_deleted") is False
    assert result["error"]["account_deleted"] is False
    assert "金额非 0" in result["error"]["error"]
    assert "已从账号池删除" not in result["error"]["error"]
    assert statuses[email]["status"] == "failed"
    assert deleted_accounts == []
    assert deleted_sessions == []


def test_batch_account_qualification_only_marks_failed_when_network_error_occurs(monkeypatch, tmp_path):
    monkeypatch.setattr(momo_vn, "LINKS_FILE", tmp_path / "momo_vn_links.json")
    monkeypatch.setattr(momo_vn, "ACCOUNT_STATUS_FILE", tmp_path / "momo_vn_account_status.json")
    monkeypatch.setattr(momo_vn, "_load_token_for_email", lambda email: f"token-{email}")
    monkeypatch.setattr(
        momo_vn,
        "detect_momo_eligibility",
        lambda cfg, log=None: (_ for _ in ()).throw(RuntimeError("curl: (97) connection to proxy closed")),
    )

    job_id = "momo-qualification-failed-job"
    momo_vn.JOBS.clear()
    momo_vn.JOBS[job_id] = _make_job(job_id)
    req = momo_vn.MomoVnBatchStartRequest.model_validate({
        "accountEmails": ["user@example.com"],
        "proxies": "proxy",
        "qualificationOnly": True,
        "maxAttempts": 1,
    })

    result = momo_vn._run_batch_account(
        job_id,
        req,
        {"email": "user@example.com", "auth_file": "auth.json"},
        1,
        1,
        momo_vn._parse_proxies(req.proxies),
    )

    statuses = json.loads(momo_vn.ACCOUNT_STATUS_FILE.read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert result["error"]["attempts"] == 1
    assert statuses["user@example.com"]["status"] == "failed"
    assert "proxy closed" in statuses["user@example.com"]["error"]


def test_batch_account_retries_after_proxy_failure_before_success(monkeypatch, tmp_path):
    monkeypatch.setattr(momo_vn, "LINKS_FILE", tmp_path / "momo_vn_links.json")
    monkeypatch.setattr(momo_vn, "ACCOUNT_STATUS_FILE", tmp_path / "momo_vn_account_status.json")
    monkeypatch.setattr(momo_vn, "_load_token_for_email", lambda email: f"token-{email}")
    monkeypatch.setattr(momo_vn.time, "sleep", lambda _seconds: None)
    calls = {"detect": 0, "generate": 0}

    def fake_detect(cfg, log=None):
        calls["detect"] += 1
        if calls["detect"] == 1:
            raise RuntimeError("curl: (35) TLS connect error")
        return {"status": "eligible", "has_momo": True, "cs_id": "oaics_test_custom"}

    def fake_generate(cfg, log=None):
        calls["generate"] += 1
        assert cfg.preflight_result["cs_id"] == "oaics_test_custom"
        return {
            "ok": True,
            "amount": "0",
            "fields": {
                "momo_link": "https://payment.momo.vn/pay/app?token=test",
                "provider_redirect_url": "https://payment.momo.vn/pay/app?token=test",
                "stripe_redirect_url": "https://pm-redirects.stripe.com/authorize/acct/test_nonce",
                "cs_id": "oaics_test_custom",
                "billing": {"country": "VN"},
            },
            "billing": {"country": "VN"},
        }

    monkeypatch.setattr(momo_vn, "detect_momo_eligibility", fake_detect)
    monkeypatch.setattr(momo_vn, "generate_momo_vn_trial", fake_generate)

    job_id = "momo-retry-success-job"
    momo_vn.JOBS.clear()
    momo_vn.JOBS[job_id] = _make_job(job_id)
    req = momo_vn.MomoVnBatchStartRequest.model_validate({
        "accountEmails": ["user@example.com"],
        "proxies": "proxy",
        "maxAttempts": 2,
    })

    result = momo_vn._run_batch_account(
        job_id,
        req,
        {"email": "user@example.com", "auth_file": "auth.json"},
        1,
        1,
        momo_vn._parse_proxies(req.proxies),
    )

    statuses = json.loads(momo_vn.ACCOUNT_STATUS_FILE.read_text(encoding="utf-8"))
    saved_link = json.loads(momo_vn.LINKS_FILE.read_text(encoding="utf-8"))[0]
    assert result["ok"] is True
    assert result["success"]["attempts"] == 2
    assert calls == {"detect": 2, "generate": 1}
    assert statuses["user@example.com"]["status"] == "success"
    assert saved_link["cs_id"] == "oaics_test_custom"


def test_batch_job_saves_momo_link_and_success_status(monkeypatch, tmp_path):
    monkeypatch.setattr(momo_vn, "LINKS_FILE", tmp_path / "momo_vn_links.json")
    monkeypatch.setattr(momo_vn, "ACCOUNT_STATUS_FILE", tmp_path / "momo_vn_account_status.json")
    monkeypatch.setattr(momo_vn, "_iter_auth_accounts", lambda include_paid=False: [{"email": "user@example.com", "auth_file": "auth.json"}])
    monkeypatch.setattr(momo_vn, "_load_token_for_email", lambda email: f"token-{email}")
    monkeypatch.setattr(momo_vn, "detect_momo_eligibility", lambda cfg, log=None: {"status": "eligible", "has_momo": True})
    monkeypatch.setattr(
        momo_vn,
        "generate_momo_vn_trial",
        lambda cfg, log=None: {
            "ok": True,
            "amount": "0",
            "fields": {
                "momo_link": "https://payment.momo.vn/pay/app?token=test",
                "provider_redirect_url": "https://payment.momo.vn/pay/app?token=test",
                "stripe_redirect_url": "https://pm-redirects.stripe.com/authorize/acct/test_nonce",
                "cs_id": "cs_test",
                "billing": {"country": "VN"},
            },
            "billing": {"country": "VN"},
        },
    )

    job_id = "momo-success-job"
    momo_vn.JOBS.clear()
    momo_vn.JOBS[job_id] = _make_job(job_id)
    req = momo_vn.MomoVnBatchStartRequest.model_validate({
        "accountEmails": ["user@example.com"],
        "proxies": "proxy",
    })

    momo_vn._run_batch_job(job_id, req)

    saved_link = json.loads(momo_vn.LINKS_FILE.read_text(encoding="utf-8"))[0]
    statuses = json.loads(momo_vn.ACCOUNT_STATUS_FILE.read_text(encoding="utf-8"))
    assert saved_link["account_email"] == "user@example.com"
    assert saved_link["currency"] == "VND"
    assert saved_link["momo_link"] == "https://payment.momo.vn/pay/app?token=test"
    assert saved_link["provider_redirect_url"] == "https://payment.momo.vn/pay/app?token=test"
    assert statuses["user@example.com"]["status"] == "success"
    assert momo_vn.JOBS[job_id]["status"] == "success"


def test_append_link_preserves_all_records_under_concurrent_writes(monkeypatch, tmp_path):
    monkeypatch.setattr(momo_vn, "LINKS_FILE", tmp_path / "momo_vn_links.json")
    original_load_links = momo_vn._load_links

    def slow_load_links():
        items = original_load_links()
        momo_vn.time.sleep(0.05)
        return items

    monkeypatch.setattr(momo_vn, "_load_links", slow_load_links)

    records = [
        {"id": "id-1", "account_email": "a@example.com", "momo_link": "https://payment.momo.vn/pay/a"},
        {"id": "id-2", "account_email": "b@example.com", "momo_link": "https://payment.momo.vn/pay/b"},
        {"id": "id-3", "account_email": "c@example.com", "momo_link": "https://payment.momo.vn/pay/c"},
    ]
    threads = [threading.Thread(target=momo_vn._append_link, args=(record,)) for record in records]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    saved = json.loads(momo_vn.LINKS_FILE.read_text(encoding="utf-8"))
    assert {item["account_email"] for item in saved} == {"a@example.com", "b@example.com", "c@example.com"}
    assert len(saved) == 3


def test_accounts_route_uses_canonical_status_text_even_if_stored_text_is_dirty(monkeypatch, tmp_path):
    app = _app()
    monkeypatch.setattr(momo_vn, "LINKS_FILE", tmp_path / "momo_vn_links.json")
    monkeypatch.setattr(momo_vn, "ACCOUNT_STATUS_FILE", tmp_path / "momo_vn_account_status.json")
    monkeypatch.setattr(momo_vn.account_store, "load_accounts", lambda: [{"email": "user@example.com", "status": "active", "account_type": "free"}])
    monkeypatch.setattr(momo_vn, "_iter_auth_accounts", lambda include_paid=False: [{"email": "user@example.com", "auth_file": "auth.json"}])
    momo_vn.ACCOUNT_STATUS_FILE.write_text(
        json.dumps({
            "user@example.com": {
                "status": "failed",
                "status_text": "戻全払移",
                "error": "timeout",
                "updated_at": "2026-07-27 12:00:00",
            }
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    result = _endpoint(app, "/api/momo-vn/accounts", "GET")()

    assert result["accounts"][0]["momo_status"] == "failed"
    assert result["accounts"][0]["momo_status_text"] == "提链失败"
    assert result["accounts"][0]["momo_error"] == "timeout"


def test_momo_routes_expose_job_and_link_management(monkeypatch, tmp_path):
    app = _app()
    monkeypatch.setattr(momo_vn, "LINKS_FILE", tmp_path / "momo_vn_links.json")
    monkeypatch.setattr(momo_vn, "ACCOUNT_STATUS_FILE", tmp_path / "momo_vn_account_status.json")
    monkeypatch.setattr(momo_vn.threading, "Thread", lambda *args, **kwargs: type("DummyThread", (), {"start": lambda self: None})())

    start = _endpoint(app, "/api/momo-vn/batch/start", "POST")(
        momo_vn.MomoVnBatchStartRequest.model_validate({"accountEmails": ["user@example.com"], "proxies": "host:1000:user:pass"})
    )
    job = _endpoint(app, "/api/momo-vn/jobs/{job_id}", "GET")(start["job_id"])

    assert job["status"] == "queued"
    assert _endpoint(app, "/api/momo-vn/links", "GET")() == {"links": [], "pruned_deleted_accounts": 0}
