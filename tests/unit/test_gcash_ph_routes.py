from __future__ import annotations

from fastapi import FastAPI

from autotoken.api_routes import gcash_ph
from autotoken.interfaces import api as api_interface


def _app():
    app = FastAPI()
    app.include_router(gcash_ph.create_gcash_ph_router())
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


def test_main_api_includes_gcash_ph_router():
    paths = {getattr(route, "path", "") for route in api_interface.app.routes}
    assert "/api/gcash-ph/accounts" in paths
    assert "/api/gcash-ph/batch/start" in paths
    assert "/api/gcash-ph/links" in paths


def test_accounts_default_to_pending_gcash_status(monkeypatch, tmp_path):
    app = _app()
    monkeypatch.setattr(gcash_ph, "LINKS_FILE", tmp_path / "gcash_ph_links.json")
    monkeypatch.setattr(gcash_ph, "ACCOUNT_STATUS_FILE", tmp_path / "gcash_ph_account_status.json")
    monkeypatch.setattr(gcash_ph.account_store, "load_accounts", lambda: [
        {"email": "free@example.com", "status": "active", "account_type": "free", "ttl_seconds": 3600},
        {"email": "plus@example.com", "status": "active", "account_type": "plus", "ttl_seconds": 7200},
    ])
    monkeypatch.setattr(gcash_ph, "_iter_auth_accounts", lambda include_paid=False: [
        {"email": "free@example.com", "auth_file": "auth-free.json"},
        {"email": "plus@example.com", "auth_file": "auth-plus.json"},
    ])

    result = _endpoint(app, "/api/gcash-ph/accounts", "GET")()

    assert [row["email"] for row in result["accounts"]] == ["free@example.com", "plus@example.com"]
    assert result["accounts"][0]["gcash_status"] == "pending"
    assert result["accounts"][0]["gcash_status_text"] == "未提链"
    assert result["accounts"][0]["gcash_selectable"] is True
    assert result["accounts"][1]["gcash_status"] == "paid"
    assert result["accounts"][1]["gcash_status_text"] == "已支付"
    assert result["accounts"][1]["gcash_selectable"] is False


def test_batch_job_saves_gcash_link_and_qr(monkeypatch, tmp_path):
    monkeypatch.setattr(gcash_ph, "LINKS_FILE", tmp_path / "gcash_ph_links.json")
    monkeypatch.setattr(gcash_ph, "ACCOUNT_STATUS_FILE", tmp_path / "gcash_ph_account_status.json")
    monkeypatch.setattr(gcash_ph, "_iter_auth_accounts", lambda include_paid=False: [{"email": "user@example.com", "auth_file": "auth.json"}])
    monkeypatch.setattr(gcash_ph, "_load_token_for_email", lambda email: f"token-{email}")
    monkeypatch.setattr(gcash_ph, "detect_gcash_eligibility", lambda cfg, log=None: {"status": "eligible", "has_gcash": True})
    monkeypatch.setattr(
        gcash_ph,
        "generate_gcash_ph_trial",
        lambda cfg, log=None: {
            "ok": True,
            "amount": "0",
            "currency": "PHP",
            "fields": {
                "gcash_link": "https://pm-redirects.stripe.com/authorize/acct/gcash_test",
                "provider_redirect_url": "https://pm-redirects.stripe.com/authorize/acct/gcash_test",
                "cs_id": "cs_test",
                "gcash_qr_url": "https://payments.gcash.com/qr/test.png",
                "gcash_qr_data": "gcash://pay?token=test",
            },
        },
    )

    job_id = "gcash-success-job"
    gcash_ph.JOBS.clear()
    gcash_ph.JOBS[job_id] = _make_job(job_id)
    req = gcash_ph.GCashPhBatchStartRequest.model_validate({
        "accountEmails": ["user@example.com"],
        "proxies": "host:1000:user:pass",
    })
    gcash_ph._run_batch_job(job_id, req)

    saved_link = gcash_ph._load_links()[0]
    assert saved_link["gcash_link"] == "https://pm-redirects.stripe.com/authorize/acct/gcash_test"
    assert saved_link["currency"] == "PHP"
    assert saved_link["gcash_qr_url"] == "https://payments.gcash.com/qr/test.png"
    assert saved_link["gcash_qr_data"] == "gcash://pay?token=test"
    assert gcash_ph.JOBS[job_id]["status"] == "success"


def test_batch_account_deletes_token_invalidated_account(monkeypatch, tmp_path):
    monkeypatch.setattr(gcash_ph, "LINKS_FILE", tmp_path / "gcash_ph_links.json")
    monkeypatch.setattr(gcash_ph, "ACCOUNT_STATUS_FILE", tmp_path / "gcash_ph_account_status.json")
    monkeypatch.setattr(gcash_ph, "_gcash_paid_emails", lambda: set())
    monkeypatch.setattr(gcash_ph, "_load_token_for_email", lambda email: "access-token")

    error_text = (
        'checkout failed: { "error": { "message": '
        '"Your authentication token has been invalidated. Please try signing in again.", '
        '"type": "invalid_request_error", "code": "token_invalidated", "param": null }, "status": 401 }'
    )
    monkeypatch.setattr(gcash_ph, "detect_gcash_eligibility", lambda cfg, log=None: (_ for _ in ()).throw(RuntimeError(error_text)))

    deleted: dict[str, str] = {}
    monkeypatch.setattr(gcash_ph.account_store, "delete_account", lambda email: deleted.setdefault("record", email) or True)
    monkeypatch.setattr(gcash_ph, "delete_auth_session", lambda email: deleted.setdefault("auth", email) or True)

    job_id = "gcash-token-invalidated-job"
    gcash_ph.JOBS.clear()
    gcash_ph.JOBS[job_id] = _make_job(job_id)
    req = gcash_ph.GCashPhBatchStartRequest.model_validate({
        "accountEmails": ["bad@example.com"],
        "proxies": "host:1000:user:pass",
        "maxAttempts": 5,
    })

    result = gcash_ph._run_batch_account(job_id, req, {"email": "bad@example.com"}, 1, 1, ["host:1000:user:pass"])

    assert result["ok"] is False
    assert result["account_deleted"] is True
    assert "已从账号池删除" in result["error"]["error"]
    assert result["error"]["attempts"] == 1
    assert result["error"]["cleanup"] == {"record_deleted": True, "auth_session_deleted": True}
    assert deleted == {"record": "bad@example.com", "auth": "bad@example.com"}

