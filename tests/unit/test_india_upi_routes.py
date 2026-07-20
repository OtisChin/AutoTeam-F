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
