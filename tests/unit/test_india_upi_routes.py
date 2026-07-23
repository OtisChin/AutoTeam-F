from __future__ import annotations

import json

import pytest
from fastapi import FastAPI, HTTPException

from autotoken.api_routes import india_upi


def _app():
    app = FastAPI()
    app.include_router(india_upi.create_india_upi_router())
    return app


def _endpoint(app, path, method):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"missing route {method} {path}")


@pytest.fixture(autouse=True)
def isolated_files(monkeypatch, tmp_path):
    monkeypatch.setattr(india_upi, "LINKS_FILE", tmp_path / "india_upi_links.json")
    monkeypatch.setattr(india_upi, "ACCOUNT_STATUS_FILE", tmp_path / "india_upi_account_status.json")
    india_upi.JOBS.clear()
    yield
    india_upi.JOBS.clear()


def test_accounts_default_to_pending_upi_status(monkeypatch):
    app = _app()
    monkeypatch.setattr(india_upi.account_store, "load_accounts", lambda: [
        {"email": "user@example.com", "status": "active", "account_type": "free", "ttl_seconds": 3600},
        {"email": "plus@example.com", "status": "active", "account_type": "plus", "ttl_seconds": 7200},
    ])
    monkeypatch.setattr(india_upi, "_iter_auth_accounts", lambda include_paid=False: [
        {"email": "user@example.com", "auth_file": "auth-user.json"},
        {"email": "plus@example.com", "auth_file": "auth-plus.json"},
    ])

    result = _endpoint(app, "/api/india-upi/accounts", "GET")()

    assert [row["email"] for row in result["accounts"]] == ["user@example.com", "plus@example.com"]
    assert result["accounts"][0]["upi_status"] == "pending"
    assert result["accounts"][0]["upi_status_text"] == "未提链"
    assert result["accounts"][0]["upi_selectable"] is True
    assert result["accounts"][1]["upi_status"] == "paid"
    assert result["accounts"][1]["upi_status_text"] == "已支付"
    assert result["accounts"][1]["upi_selectable"] is False


def test_accounts_exclude_sensitive_account_fields(monkeypatch):
    app = _app()
    monkeypatch.setattr(india_upi.account_store, "load_accounts", lambda: [{
        "email": "user@example.com",
        "status": "active",
        "account_type": "plus",
        "seat_type": "individual",
        "ttl_seconds": 3600,
        "expires_at": "2026-07-21T00:00:00Z",
        "last_active_at": "2026-07-20T00:00:00Z",
        "note": "safe metadata",
        "password": "secret-password",
        "cloudmail_account_id": "cloudmail-id",
        "auth_file": "auth.json",
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "cookies": {"session": "secret-cookie"},
        "unexpected_secret": "must-not-leak",
    }])
    monkeypatch.setattr(india_upi, "_iter_auth_accounts", lambda include_paid=False: [
        {"email": "user@example.com", "auth_file": "auth.json", "ttl_seconds": 3600}
    ])

    row = _endpoint(app, "/api/india-upi/accounts", "GET")()["accounts"][0]

    assert {"email", "status", "account_type", "seat_type", "ttl_seconds", "expires_at", "last_active_at", "note"} <= row.keys()
    assert not {"password", "cloudmail_account_id", "auth_file", "access_token", "refresh_token", "cookies", "unexpected_secret"} & row.keys()


def test_accounts_list_only_auth_runnable_accounts(monkeypatch):
    app = _app()
    monkeypatch.setattr(india_upi.account_store, "load_accounts", lambda: [
        {"email": "with-auth@example.com", "status": "active", "account_type": "free"},
        {"email": "missing-auth@example.com", "status": "active", "account_type": "free"},
    ])
    monkeypatch.setattr(india_upi, "_iter_auth_accounts", lambda include_paid=False: [
        {"email": "with-auth@example.com", "auth_file": "auth.json"}
    ])

    result = _endpoint(app, "/api/india-upi/accounts", "GET")()

    assert [row["email"] for row in result["accounts"]] == ["with-auth@example.com"]


def test_batch_start_creates_queued_job(monkeypatch):
    app = _app()
    monkeypatch.setattr(india_upi.account_store, "load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(india_upi.threading, "Thread", lambda *args, **kwargs: type("DummyThread", (), {"start": lambda self: None})())

    result = _endpoint(app, "/api/india-upi/batch/start", "POST")(
        india_upi.IndiaUpiBatchStartRequest.model_validate({
            "accountEmails": ["user@example.com"],
            "proxies": "host:port:user:pass",
            "concurrency": 2,
        })
    )
    job = _endpoint(app, "/api/india-upi/jobs/{job_id}", "GET")(result["job_id"])

    assert job["status"] == "queued"
    assert job["total"] == 1
    assert job["concurrency"] == 2


def test_batch_job_generates_upi_link_and_records_status(monkeypatch, tmp_path):
    email = "user@example.com"
    captured = {}
    monkeypatch.setattr(india_upi, "_iter_auth_accounts", lambda include_paid=False: [{"email": email, "auth_file": "auth.json"}])
    monkeypatch.setattr(india_upi, "_load_token_for_email", lambda value: "token-" + value)

    def fake_generate_upi_trial(cfg, log):
        captured["cfg"] = cfg
        log("fake upi success")
        return {
            "ok": True,
            "amount": "199900",
            "fields": {
                "upi_link": "https://payments.stripe.com/upi/instructions/test",
                "hosted_instructions_url": "https://payments.stripe.com/upi/instructions/test",
                "qr_image_url_png": "https://payments.stripe.com/qr/test.png",
                "cs_id": "cs_test",
                "billing": {"country": "IN"},
            },
            "billing": {"country": "IN"},
        }

    monkeypatch.setattr(india_upi, "generate_upi_trial", fake_generate_upi_trial)
    job_id = "upi-job"
    india_upi.JOBS[job_id] = {
        "id": job_id, "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 0,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {},
    }

    req = india_upi.IndiaUpiBatchStartRequest.model_validate({
        "accountEmails": [email],
        "proxies": "host:1000:user:pass",
        "concurrency": 1,
        "promoMode": "skip",
    })
    india_upi._run_batch_job(job_id, req)

    job = india_upi.JOBS[job_id]
    assert job["status"] == "success"
    assert job["completed"] == 1
    assert job["result"]["successes"][0]["link"]["upi_link"] == "https://payments.stripe.com/upi/instructions/test"
    assert captured["cfg"].access_token == "token-user@example.com"
    assert captured["cfg"].apply_promo is False
    assert json.loads(india_upi.LINKS_FILE.read_text(encoding="utf-8"))[0]["account_email"] == email
    statuses = json.loads(india_upi.ACCOUNT_STATUS_FILE.read_text(encoding="utf-8"))
    assert statuses[email]["status"] == "success"


def test_link_record_includes_five_minute_upi_expiry(monkeypatch):
    monkeypatch.setattr(india_upi.time, "time", lambda: 1000.0)
    monkeypatch.setattr(india_upi.time, "strftime", lambda fmt, *_args: "2026-07-22 14:35:00" if _args else "2026-07-22 14:30:00")

    record = india_upi._link_record_from_result(
        "job-1",
        "user@example.com",
        {
            "amount": "0",
            "fields": {
                "upi_link": "https://payments.stripe.com/upi/instructions/token",
                "cs_id": "cs_test",
            },
        },
    )

    assert record["upi_ttl_seconds"] == 300
    assert record["created_at_ts"] == 1000.0
    assert record["upi_expires_at_ts"] == 1300.0
    assert record["upi_expires_at"] == "2026-07-22 14:35:00"


def test_batch_job_defaults_to_apply_promo_mode(monkeypatch):
    email = "default-promo@example.com"
    captured = {}
    monkeypatch.setattr(india_upi, "_iter_auth_accounts", lambda include_paid=False: [{"email": email, "auth_file": "auth.json"}])
    monkeypatch.setattr(india_upi, "_load_token_for_email", lambda _email: "token")

    def fake_generate_upi_trial(cfg, log):
        captured["apply_promo"] = cfg.apply_promo
        return {"ok": True, "amount": "0", "fields": {"upi_link": "upi://ok", "cs_id": "cs_test"}, "billing": {}}

    monkeypatch.setattr(india_upi, "generate_upi_trial", fake_generate_upi_trial)
    job_id = "upi-default-promo-job"
    india_upi.JOBS[job_id] = {
        "id": job_id, "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 0,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {},
    }

    req = india_upi.IndiaUpiBatchStartRequest.model_validate({"accountEmails": [email], "proxies": "p"})
    india_upi._run_batch_job(job_id, req)

    assert captured["apply_promo"] is True


def test_batch_job_passes_apply_promo_mode(monkeypatch):
    email = "promo@example.com"
    captured = {}
    monkeypatch.setattr(india_upi, "_iter_auth_accounts", lambda include_paid=False: [{"email": email, "auth_file": "auth.json"}])
    monkeypatch.setattr(india_upi, "_load_token_for_email", lambda _email: "token")

    def fake_generate_upi_trial(cfg, log):
        captured["apply_promo"] = cfg.apply_promo
        return {"ok": True, "amount": "0", "fields": {"upi_link": "upi://ok", "cs_id": "cs_test"}, "billing": {}}

    monkeypatch.setattr(india_upi, "generate_upi_trial", fake_generate_upi_trial)
    job_id = "upi-promo-job"
    india_upi.JOBS[job_id] = {
        "id": job_id, "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 0,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {},
    }

    req = india_upi.IndiaUpiBatchStartRequest.model_validate({"accountEmails": [email], "proxies": "p", "promoMode": "promo"})
    india_upi._run_batch_job(job_id, req)

    assert captured["apply_promo"] is True


def test_batch_job_uses_requested_max_attempts(monkeypatch):
    email = "retry-limit@example.com"
    calls = 0
    monkeypatch.setattr(india_upi, "_iter_auth_accounts", lambda include_paid=False: [{"email": email, "auth_file": "auth.json"}])
    monkeypatch.setattr(india_upi, "_load_token_for_email", lambda _email: "token")
    monkeypatch.setattr(india_upi.time, "sleep", lambda _seconds: None)

    def fake_generate_upi_trial(cfg, log):
        nonlocal calls
        calls += 1
        raise RuntimeError(f"temporary failure {calls}")

    monkeypatch.setattr(india_upi, "generate_upi_trial", fake_generate_upi_trial)
    job_id = "upi-max-attempts-job"
    india_upi.JOBS[job_id] = {
        "id": job_id, "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 0,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {},
    }

    req = india_upi.IndiaUpiBatchStartRequest.model_validate({"accountEmails": [email], "proxies": "p", "maxAttempts": 2})
    india_upi._run_batch_job(job_id, req)

    job = india_upi.JOBS[job_id]
    assert calls == 2
    assert job["result"]["errors"][0]["attempts"] == 2


def test_batch_job_deletes_non_zero_after_promo_account(monkeypatch):
    email = "promo@example.com"
    deleted_accounts = []
    deleted_auth = []
    monkeypatch.setattr(india_upi, "_iter_auth_accounts", lambda include_paid=False: [{"email": email, "auth_file": "auth.json"}])
    monkeypatch.setattr(india_upi, "_load_token_for_email", lambda _email: "token")
    monkeypatch.setattr(india_upi.account_store, "delete_account", lambda value: deleted_accounts.append(value) or True)
    monkeypatch.setattr(india_upi, "delete_auth_session", lambda value: deleted_auth.append(value) or True)

    def fake_generate_upi_trial(cfg, log):
        raise RuntimeError("套 promo 后金额不是 0: 9990")

    monkeypatch.setattr(india_upi, "generate_upi_trial", fake_generate_upi_trial)
    job_id = "upi-nonzero-promo-job"
    india_upi.JOBS[job_id] = {
        "id": job_id, "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 0,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {},
    }

    req = india_upi.IndiaUpiBatchStartRequest.model_validate({"accountEmails": [email], "proxies": "p"})
    india_upi._run_batch_job(job_id, req)

    job = india_upi.JOBS[job_id]
    assert deleted_accounts == [email]
    assert deleted_auth == [email]
    assert job["result"]["errors"][0]["account_deleted"] is True
    assert job["result"]["errors"][0]["failure_category"] == "upi_promo_nonzero_account_ineligible"
    assert job["result"]["errors"][0]["failure_stage"] == "promo_amount"
    assert "删除账号" in job["result"]["errors"][0]["retry_hint"]
    assert "套 promo 后金额非 0，已从账号池删除" in job["result"]["errors"][0]["error"]


def test_classify_upi_setup_generic_decline():
    failure = india_upi.classify_upi_failure(
        "approve 后失败: checkout_approval_payment_failure_with_payment_error "
        "payment_error=setup_attempt_failed/generic_decline "
        "intent_type=setup_intent intent_state=requires_payment_method"
    )

    assert failure["failure_category"] == "upi_setup_generic_decline"
    assert failure["failure_stage"] == "stripe_setup_intent"
    assert "不删除账号" in failure["retry_hint"]


def test_batch_job_keeps_account_for_setup_generic_decline(monkeypatch):
    email = "generic-decline@example.com"
    deleted_accounts = []
    deleted_auth = []
    monkeypatch.setattr(india_upi, "_iter_auth_accounts", lambda include_paid=False: [{"email": email, "auth_file": "auth.json"}])
    monkeypatch.setattr(india_upi, "_load_token_for_email", lambda _email: "token")
    monkeypatch.setattr(india_upi.account_store, "delete_account", lambda value: deleted_accounts.append(value) or True)
    monkeypatch.setattr(india_upi, "delete_auth_session", lambda value: deleted_auth.append(value) or True)
    monkeypatch.setattr(india_upi.time, "sleep", lambda _seconds: None)

    def fake_generate_upi_trial(cfg, log):
        raise RuntimeError(
            "approve 后失败: checkout_approval_payment_failure_with_payment_error "
            "payment_error=setup_attempt_failed/generic_decline "
            "intent_type=setup_intent intent_state=requires_payment_method"
        )

    monkeypatch.setattr(india_upi, "generate_upi_trial", fake_generate_upi_trial)
    job_id = "upi-setup-decline-job"
    india_upi.JOBS[job_id] = {
        "id": job_id, "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 0,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {},
    }

    req = india_upi.IndiaUpiBatchStartRequest.model_validate({"accountEmails": [email], "proxies": "p", "maxAttempts": 1})
    india_upi._run_batch_job(job_id, req)

    job = india_upi.JOBS[job_id]
    error = job["result"]["errors"][0]
    assert deleted_accounts == []
    assert deleted_auth == []
    assert error["failure_category"] == "upi_setup_generic_decline"
    assert error["failure_stage"] == "stripe_setup_intent"
    assert "不删除账号" in error["retry_hint"]
    statuses = json.loads(india_upi.ACCOUNT_STATUS_FILE.read_text(encoding="utf-8"))
    assert statuses[email]["failure_category"] == "upi_setup_generic_decline"
    assert statuses[email]["failure_stage"] == "stripe_setup_intent"


def test_accounts_surface_upi_failure_classification(monkeypatch):
    app = _app()
    email = "failed@example.com"
    monkeypatch.setattr(india_upi.account_store, "load_accounts", lambda: [{"email": email, "status": "active", "account_type": "free"}])
    monkeypatch.setattr(india_upi, "_iter_auth_accounts", lambda include_paid=False: [{"email": email, "auth_file": "auth.json"}])
    india_upi._set_account_status(
        email,
        india_upi.UPI_STATUS_FAILED,
        error="approve failed: blocked",
        failure=india_upi.classify_upi_failure("approve failed: blocked"),
    )

    row = _endpoint(app, "/api/india-upi/accounts", "GET")()["accounts"][0]

    assert row["upi_failure_category"] == "upi_approve_blocked"
    assert row["upi_failure_stage"] == "chatgpt_approve"
    assert row["upi_failure_label"] == "ChatGPT approve 被拦截"
    assert "checkout" in row["upi_retry_hint"]


def test_start_requires_selected_account():
    app = _app()

    with pytest.raises(HTTPException) as exc:
        _endpoint(app, "/api/india-upi/batch/start", "POST")(
            india_upi.IndiaUpiBatchStartRequest.model_validate({"accountEmails": [], "concurrency": 1})
        )

    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "bad_body"


def test_cancel_marks_non_terminal_job_cancelling():
    app = _app()
    india_upi.JOBS["job-1"] = {
        "id": "job-1", "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 1,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {},
    }

    result = _endpoint(app, "/api/india-upi/jobs/{job_id}/cancel", "POST")("job-1")

    assert result["ok"] is True
    assert result["status"] == "cancelling"
    assert india_upi.JOBS["job-1"]["status"] == "cancelling"
    assert india_upi.JOBS["job-1"]["cancel_requested"] is True
    assert india_upi.JOBS["job-1"]["finished_at"] is None
    assert "收到取消请求" in "\n".join(india_upi.JOBS["job-1"]["logs"])


def test_cancel_does_not_rewrite_failed_job():
    app = _app()
    india_upi.JOBS["job-1"] = {
        "id": "job-1", "status": "failed", "logs": [], "result": None, "error": "upstream failed",
        "created_at": 1.0, "finished_at": 2.0, "account_email": "", "total": 1,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {},
    }

    result = _endpoint(app, "/api/india-upi/jobs/{job_id}/cancel", "POST")("job-1")

    assert result == {"ok": True, "job_id": "job-1", "status": "failed", "cancel_requested": False}
    assert india_upi.JOBS["job-1"]["status"] == "failed"
    assert india_upi.JOBS["job-1"]["finished_at"] == 2.0


def test_links_delete_and_clear_use_upi_file():
    app = _app()
    india_upi.LINKS_FILE.write_text(json.dumps([
        {"id": "keep", "upi_link": "upi://keep"},
        {"id": "remove", "upi_link": "upi://remove"},
    ]), encoding="utf-8")

    deleted = _endpoint(app, "/api/india-upi/links/delete", "POST")(india_upi.IndiaUpiDeleteLinksRequest(ids=["remove", "missing"]))
    cleared = _endpoint(app, "/api/india-upi/links/clear", "POST")()

    assert deleted["deleted"] == 1
    assert [item["id"] for item in deleted["links"]] == ["keep"]
    assert cleared == {"deleted": 1, "links": []}


def test_temp_batch_job_calls_public_upi_generate_api_and_records_payment_uri(monkeypatch):
    email = "temp-upi@example.com"
    calls = []
    monkeypatch.setattr(india_upi, "_iter_auth_accounts", lambda include_paid=False: [{"email": email, "auth_file": "auth.json"}])
    monkeypatch.setattr(india_upi, "_load_token_for_email", lambda _email: "chatgpt-token")
    monkeypatch.setattr(india_upi.time, "sleep", lambda _seconds: None)

    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload
            self.text = json.dumps(payload)
            self.ok = 200 <= status_code < 300

        def json(self):
            return self._payload

    def fake_post(url, **kwargs):
        calls.append(("POST", url, kwargs))
        assert url == "https://ahwuoc.site/api/run"
        assert kwargs["json"] == {"accessToken": "chatgpt-token", "cdk": "UPI-GEN-1"}
        return FakeResponse(200, {"ok": True, "jobId": "remote-1", "jobToken": "token-1", "status": "running"})

    def fake_get(url, **kwargs):
        calls.append(("GET", url, kwargs))
        assert url == "https://ahwuoc.site/api/jobs/remote-1"
        assert kwargs["headers"]["X-Job-Token"] == "token-1"
        return FakeResponse(
            200,
            {
                "id": "remote-1",
                "status": "success",
                "upiUrl": "https://payments.stripe.com/upi/instructions/temp",
                "upiPaymentUri": "https://qr.stripe.com/temp.svg?border=0",
                "upiExpiresAt": 1784700000,
            },
        )

    monkeypatch.setattr(india_upi.requests, "post", fake_post)
    monkeypatch.setattr(india_upi.requests, "get", fake_get)
    job_id = "upi-temp-job"
    india_upi.JOBS[job_id] = {
        "id": job_id, "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 0,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {}, "temp": True, "external_jobs": {},
    }

    req = india_upi.IndiaUpiTempBatchStartRequest.model_validate({"accountEmails": [email], "cdk": "UPI-GEN-1"})
    india_upi._run_temp_batch_job(job_id, req)

    assert [call[0] for call in calls] == ["POST", "GET"]
    job = india_upi.JOBS[job_id]
    assert job["status"] == "success"
    link = job["result"]["successes"][0]["link"]
    assert link["account_email"] == email
    assert link["hosted_instructions_url"] == "https://payments.stripe.com/upi/instructions/temp"
    assert link["upi_payment_uri"] == "https://qr.stripe.com/temp.svg?border=0"
    assert link["qr_image_url_svg"] == "https://qr.stripe.com/temp.svg?border=0"
    assert link["upi_expires_at_ts"] == 1784700000


def test_cancel_temp_job_posts_public_upi_stop(monkeypatch):
    app = _app()
    calls = []
    india_upi.JOBS["temp-job"] = {
        "id": "temp-job", "status": "running", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 1,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 1, "skipped": [], "account_statuses": {}, "temp": True,
        "external_jobs": {"temp-upi@example.com": {"job_id": "remote-1", "job_token": "token-1"}},
    }

    class FakeResponse:
        status_code = 200
        ok = True
        text = "{}"

        def json(self):
            return {"ok": True, "status": "stopped"}

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    monkeypatch.setattr(india_upi.requests, "post", fake_post)

    result = _endpoint(app, "/api/india-upi/jobs/{job_id}/cancel", "POST")("temp-job")

    assert result["status"] == "cancelling"
    assert calls == [(
        "https://ahwuoc.site/api/jobs/remote-1/stop",
        {"headers": {"X-Job-Token": "token-1"}, "timeout": 20},
    )]


def test_delete_upi_account_removes_account_auth_links_and_status(monkeypatch):
    app = _app()
    deleted_accounts = []
    deleted_auth = []
    monkeypatch.setattr(india_upi.account_store, "delete_account", lambda email: deleted_accounts.append(email) or True)
    monkeypatch.setattr(india_upi, "delete_auth_session", lambda email: deleted_auth.append(email) or True)
    india_upi.LINKS_FILE.write_text(json.dumps([
        {"id": "remove", "account_email": "user@example.com", "upi_link": "upi://remove"},
        {"id": "keep", "account_email": "other@example.com", "upi_link": "upi://keep"},
    ]), encoding="utf-8")
    india_upi.ACCOUNT_STATUS_FILE.write_text(json.dumps({
        "user@example.com": {"status": "failed"},
        "other@example.com": {"status": "success"},
    }), encoding="utf-8")

    result = _endpoint(app, "/api/india-upi/accounts/{email}", "DELETE")("user@example.com")

    assert result["ok"] is True
    assert result["upi"] == {"links_deleted": 1, "status_deleted": True}
    assert deleted_accounts == ["user@example.com"]
    assert deleted_auth == ["user@example.com"]
    assert [item["id"] for item in json.loads(india_upi.LINKS_FILE.read_text(encoding="utf-8"))] == ["keep"]
    assert set(json.loads(india_upi.ACCOUNT_STATUS_FILE.read_text(encoding="utf-8"))) == {"other@example.com"}


def test_main_api_mounts_india_upi_router():
    from autotoken.interfaces.api import app

    paths = {getattr(route, "path", "") for route in app.routes}

    assert "/api/india-upi/accounts" in paths
    assert "/api/india-upi/accounts/{email}" in paths
    assert "/api/india-upi/batch/start" in paths
    assert "/api/india-upi/temp/batch/start" in paths
    assert "/api/india-upi/jobs/{job_id}" in paths
    assert "/api/india-upi/links" in paths
