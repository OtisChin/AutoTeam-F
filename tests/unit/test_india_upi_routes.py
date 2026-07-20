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

    result = _endpoint(app, "/api/india-upi/accounts", "GET")()

    assert [row["email"] for row in result["accounts"]] == ["user@example.com", "plus@example.com"]
    assert result["accounts"][0]["upi_status"] == "pending"
    assert result["accounts"][0]["upi_status_text"] == "未提链"
    assert result["accounts"][0]["upi_selectable"] is True


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

    row = _endpoint(app, "/api/india-upi/accounts", "GET")()["accounts"][0]

    assert {"email", "status", "account_type", "seat_type", "ttl_seconds", "expires_at", "last_active_at", "note"} <= row.keys()
    assert not {"password", "cloudmail_account_id", "auth_file", "access_token", "refresh_token", "cookies", "unexpected_secret"} & row.keys()


def test_batch_start_creates_not_implemented_job(monkeypatch):
    app = _app()
    monkeypatch.setattr(india_upi.account_store, "load_accounts", lambda: [{"email": "user@example.com"}])

    result = _endpoint(app, "/api/india-upi/batch/start", "POST")(
        india_upi.IndiaUpiBatchStartRequest.model_validate({
            "accountEmails": ["user@example.com"],
            "proxies": "host:port:user:pass",
            "concurrency": 2,
        })
    )
    job = _endpoint(app, "/api/india-upi/jobs/{job_id}", "GET")(result["job_id"])

    assert job["status"] == "not_implemented"
    assert job["total"] == 1
    assert job["completed"] == 0
    assert job["result"]["implemented"] is False
    assert "印度UPI 后端核心提链功能待接入" in "\n".join(job["logs"])


def test_start_requires_selected_account():
    app = _app()

    with pytest.raises(HTTPException) as exc:
        _endpoint(app, "/api/india-upi/batch/start", "POST")(
            india_upi.IndiaUpiBatchStartRequest.model_validate({"accountEmails": [], "concurrency": 1})
        )

    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "bad_body"


def test_cancel_marks_non_terminal_job_cancelled():
    app = _app()
    india_upi.JOBS["job-1"] = {
        "id": "job-1", "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 1,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {},
    }

    result = _endpoint(app, "/api/india-upi/jobs/{job_id}/cancel", "POST")("job-1")

    assert result["ok"] is True
    assert result["status"] == "cancelled"
    assert india_upi.JOBS["job-1"]["cancel_requested"] is True
    assert india_upi.JOBS["job-1"]["finished_at"] is not None


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


def test_main_api_mounts_india_upi_router():
    from autotoken.interfaces.api import app

    paths = {getattr(route, "path", "") for route in app.routes}

    assert "/api/india-upi/accounts" in paths
    assert "/api/india-upi/batch/start" in paths
    assert "/api/india-upi/jobs/{job_id}" in paths
    assert "/api/india-upi/links" in paths
