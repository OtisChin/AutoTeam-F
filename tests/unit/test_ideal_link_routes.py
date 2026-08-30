from __future__ import annotations

import base64
import io
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI, HTTPException

from autotoken.api_routes.ideal_link import (
    IdealBatchStartRequest,
    IdealDeleteLinksRequest,
    IdealLongLinkRequest,
    IdealQrRequest,
    create_ideal_link_router,
)
from autotoken.integrations.gpthel_ideal import app as ideal_app
from autotoken.services import proxy_runtime


def _app():
    app = FastAPI()
    app.include_router(create_ideal_link_router())
    return app


def _endpoint(app, path, method):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"missing route {method} {path}")


@pytest.fixture(autouse=True)
def _isolate_long_link_client_request_store(monkeypatch, tmp_path):
    from autotoken.api_routes import ideal_link

    monkeypatch.setattr(
        ideal_link,
        "LONG_LINK_CLIENT_REQUESTS_FILE",
        tmp_path / "ideal_long_link_client_requests.json",
        raising=False,
    )
    ideal_link.LONG_LINK_CLIENT_REQUESTS.clear()
    yield
    ideal_link.LONG_LINK_CLIENT_REQUESTS.clear()


def test_start_ideal_long_link_job_returns_job_id(monkeypatch):
    app = _app()

    def fake_start(req):
        assert req.link_type == "ideal"
        assert req.billing_country == "NL"
        assert req.payment_locale == "en"
        assert req.checkout_proxy_region == ""
        assert req.provider_proxy_region == ""
        assert req.proxy_chain_strategy == ""
        return {"job_id": "ideal-job-1"}

    monkeypatch.setattr("autotoken.api_routes.ideal_link.legacy.start_long_link_job", fake_start)

    result = _endpoint(app, "/api/ideal/long-link/start", "POST")(
        IdealLongLinkRequest.model_validate(
            {
                "accessToken": "token",
                "proxy": "http://127.0.0.1:8080",
                "link_type": "hosted",
                "billing_country": "US",
                "payment_locale": "en",
            }
        )
    )

    assert result == {"job_id": "ideal-job-1"}


def test_start_ideal_long_link_job_preserves_source_default_proxy_chain(monkeypatch):
    app = _app()

    def fake_start(req):
        assert req.link_type == "ideal"
        assert req.billing_country == "NL"
        assert req.checkout_proxy_region == "JP"
        assert req.provider_proxy_region == "NL"
        assert req.proxy_chain_strategy == ""
        assert req.approve_proxy_region == ""
        return {"job_id": "ideal-job-2"}

    monkeypatch.setattr("autotoken.api_routes.ideal_link.legacy.start_long_link_job", fake_start)

    result = _endpoint(app, "/api/ideal/long-link/start", "POST")(
        IdealLongLinkRequest.model_validate(
            {
                "accessToken": "token",
                "proxy": "socks5h://user-region-JP-sid-test-t-60:pass@example.test:3010",
                "link_type": "ideal",
                "billing_country": "NL",
                "payment_locale": "auto",
                "checkout_ui_mode": "hosted",
                "checkout_proxy_region": "JP",
                "provider_proxy_region": "NL",
                "proxy_chain_strategy": "",
                "approve_proxy_region": "",
            }
        )
    )

    assert result == {"job_id": "ideal-job-2"}


def test_start_ideal_long_link_job_is_idempotent_by_client_request_id(monkeypatch):
    from autotoken.api_routes import ideal_link

    app = _app()
    started_requests = []

    def fake_start(req):
        started_requests.append(req)
        return {"job_id": "ideal-idempotent-job"}

    monkeypatch.setattr(ideal_link.legacy, "start_long_link_job", fake_start)
    ideal_link.LONG_LINK_CLIENT_REQUESTS.clear()
    request = IdealLongLinkRequest.model_validate(
        {
            "accessToken": "token",
            "proxy": "http://127.0.0.1:8080",
            "clientRequestId": "ideal-submit-1",
        }
    )
    start = _endpoint(app, "/api/ideal/long-link/start", "POST")

    first = start(request)
    second = start(request.model_copy(deep=True))

    assert first == {"job_id": "ideal-idempotent-job", "client_request_id": "ideal-submit-1"}
    assert second == first
    assert len(started_requests) == 1
    assert started_requests[0].client_request_id == "ideal-submit-1"


def test_start_ideal_long_link_job_recovers_idempotency_after_memory_reset(monkeypatch):
    from autotoken.api_routes import ideal_link

    app = _app()
    started_requests = []

    def fake_start(req):
        started_requests.append(req)
        return {"job_id": f"ideal-persisted-job-{len(started_requests)}"}

    monkeypatch.setattr(ideal_link.legacy, "start_long_link_job", fake_start)
    request = IdealLongLinkRequest.model_validate(
        {"accessToken": "token", "clientRequestId": "ideal-persisted-1"}
    )
    start = _endpoint(app, "/api/ideal/long-link/start", "POST")

    first = start(request)
    ideal_link.LONG_LINK_CLIENT_REQUESTS.clear()
    second = start(request.model_copy(deep=True))

    assert second == first
    assert second == {
        "job_id": "ideal-persisted-job-1",
        "client_request_id": "ideal-persisted-1",
    }
    assert len(started_requests) == 1


def test_start_ideal_long_link_job_reserves_key_before_unknown_start_outcome(monkeypatch):
    from autotoken.api_routes import ideal_link

    app = _app()
    starts = 0
    states_seen_during_start = []

    def ambiguous_start(req):
        nonlocal starts
        starts += 1
        path = ideal_link.LONG_LINK_CLIENT_REQUESTS_FILE
        if path.exists():
            stored = json.loads(path.read_text(encoding="utf-8"))
            states_seen_during_start.append(stored["ideal-reserved-1"].get("state"))
        else:
            states_seen_during_start.append(None)
        raise RuntimeError("legacy start response was lost")

    monkeypatch.setattr(ideal_link.legacy, "start_long_link_job", ambiguous_start)
    request = IdealLongLinkRequest.model_validate(
        {"accessToken": "token", "clientRequestId": "ideal-reserved-1"}
    )
    start = _endpoint(app, "/api/ideal/long-link/start", "POST")

    with pytest.raises(HTTPException) as first:
        start(request)
    assert first.value.status_code == 503
    assert first.value.detail["code"] == "idempotency_result_unknown"

    ideal_link.LONG_LINK_CLIENT_REQUESTS.clear()
    with pytest.raises(HTTPException) as retry:
        start(request.model_copy(deep=True))

    assert retry.value.status_code == 503
    assert retry.value.detail["code"] == "idempotency_result_unknown"
    assert states_seen_during_start == ["reserved"]
    assert starts == 1


def test_start_ideal_long_link_job_fails_closed_for_invalid_persistent_record(monkeypatch):
    from autotoken.api_routes import ideal_link

    invalid_contents = '{"ideal-corrupt-1": {"state": "started"}}'
    ideal_link.LONG_LINK_CLIENT_REQUESTS_FILE.write_text(invalid_contents, encoding="utf-8")
    starts = 0

    def fake_start(req):
        nonlocal starts
        starts += 1
        return {"job_id": "must-not-start"}

    monkeypatch.setattr(ideal_link.legacy, "start_long_link_job", fake_start)
    request = IdealLongLinkRequest.model_validate(
        {"accessToken": "token", "clientRequestId": "ideal-corrupt-1"}
    )

    with pytest.raises(HTTPException) as exc:
        _endpoint(_app(), "/api/ideal/long-link/start", "POST")(request)

    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "idempotency_store_unavailable"
    assert starts == 0
    assert ideal_link.LONG_LINK_CLIENT_REQUESTS_FILE.read_text(encoding="utf-8") == invalid_contents


def test_start_ideal_long_link_job_fails_closed_for_non_utf8_persistent_store(monkeypatch):
    from autotoken.api_routes import ideal_link

    corrupt_contents = b"\xff\xfe\x00\x80"
    ideal_link.LONG_LINK_CLIENT_REQUESTS_FILE.write_bytes(corrupt_contents)
    starts = 0

    def fake_start(req):
        nonlocal starts
        starts += 1
        return {"job_id": "must-not-start"}

    monkeypatch.setattr(ideal_link.legacy, "start_long_link_job", fake_start)
    request = IdealLongLinkRequest.model_validate(
        {"accessToken": "token", "clientRequestId": "ideal-corrupt-utf8-1"}
    )

    with pytest.raises(HTTPException) as exc:
        _endpoint(_app(), "/api/ideal/long-link/start", "POST")(request)

    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "idempotency_store_unavailable"
    assert starts == 0
    assert ideal_link.LONG_LINK_CLIENT_REQUESTS_FILE.read_bytes() == corrupt_contents


def test_start_ideal_long_link_job_fails_closed_when_persistent_store_cannot_be_checked(monkeypatch):
    from autotoken.api_routes import ideal_link

    class UnavailablePath:
        def exists(self):
            raise OSError("storage unavailable")

    starts = 0

    def fake_start(req):
        nonlocal starts
        starts += 1
        return {"job_id": "must-not-start"}

    monkeypatch.setattr(ideal_link, "LONG_LINK_CLIENT_REQUESTS_FILE", UnavailablePath())
    monkeypatch.setattr(ideal_link.legacy, "start_long_link_job", fake_start)
    request = IdealLongLinkRequest.model_validate(
        {"accessToken": "token", "clientRequestId": "ideal-store-unavailable-1"}
    )

    with pytest.raises(HTTPException) as exc:
        _endpoint(_app(), "/api/ideal/long-link/start", "POST")(request)

    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "idempotency_store_unavailable"
    assert starts == 0


def test_start_ideal_long_link_job_fails_closed_when_reservation_cannot_be_saved(monkeypatch):
    from autotoken.api_routes import ideal_link

    class UnwritablePath:
        @property
        def parent(self):
            return self

        def exists(self):
            return False

        def mkdir(self, **kwargs):
            raise OSError("storage is read-only")

    starts = 0

    def fake_start(req):
        nonlocal starts
        starts += 1
        return {"job_id": "must-not-start"}

    monkeypatch.setattr(ideal_link, "LONG_LINK_CLIENT_REQUESTS_FILE", UnwritablePath())
    monkeypatch.setattr(ideal_link.legacy, "start_long_link_job", fake_start)
    request = IdealLongLinkRequest.model_validate(
        {"accessToken": "token", "clientRequestId": "ideal-store-read-only-1"}
    )

    with pytest.raises(HTTPException) as exc:
        _endpoint(_app(), "/api/ideal/long-link/start", "POST")(request)

    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "idempotency_store_unavailable"
    assert starts == 0


def test_concurrent_ideal_long_link_starts_share_one_legacy_worker(monkeypatch):
    from autotoken.api_routes import ideal_link

    app = _app()
    starts = 0
    starts_lock = threading.Lock()

    def slow_start(req):
        nonlocal starts
        with starts_lock:
            starts += 1
        time.sleep(0.03)
        return {"job_id": "ideal-concurrent-job"}

    monkeypatch.setattr(ideal_link.legacy, "start_long_link_job", slow_start)
    ideal_link.LONG_LINK_CLIENT_REQUESTS.clear()
    request = IdealLongLinkRequest.model_validate(
        {"accessToken": "token", "clientRequestId": "ideal-concurrent-1"}
    )
    start = _endpoint(app, "/api/ideal/long-link/start", "POST")

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: start(request.model_copy(deep=True)), range(2)))

    assert results == [
        {"job_id": "ideal-concurrent-job", "client_request_id": "ideal-concurrent-1"},
        {"job_id": "ideal-concurrent-job", "client_request_id": "ideal-concurrent-1"},
    ]
    assert starts == 1


def test_start_ideal_long_link_job_rejects_reused_key_with_different_payload(monkeypatch):
    from autotoken.api_routes import ideal_link

    app = _app()
    starts = 0

    def fake_start(req):
        nonlocal starts
        starts += 1
        return {"job_id": "ideal-conflict-job"}

    monkeypatch.setattr(ideal_link.legacy, "start_long_link_job", fake_start)
    ideal_link.LONG_LINK_CLIENT_REQUESTS.clear()
    start = _endpoint(app, "/api/ideal/long-link/start", "POST")
    first = IdealLongLinkRequest.model_validate(
        {"accessToken": "token", "proxy": "http://proxy-one.test:8080", "clientRequestId": "ideal-conflict-1"}
    )
    changed = IdealLongLinkRequest.model_validate(
        {"accessToken": "token", "proxy": "http://proxy-two.test:8080", "clientRequestId": "ideal-conflict-1"}
    )

    assert start(first)["job_id"] == "ideal-conflict-job"
    with pytest.raises(HTTPException) as exc:
        start(changed)

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "idempotency_conflict"
    assert starts == 1


def test_start_ideal_long_link_job_keeps_conflict_after_memory_reset(monkeypatch):
    from autotoken.api_routes import ideal_link

    app = _app()
    starts = 0

    def fake_start(req):
        nonlocal starts
        starts += 1
        return {"job_id": "ideal-persisted-conflict-job"}

    monkeypatch.setattr(ideal_link.legacy, "start_long_link_job", fake_start)
    start = _endpoint(app, "/api/ideal/long-link/start", "POST")
    first = IdealLongLinkRequest.model_validate(
        {"accessToken": "token", "proxy": "http://proxy-one.test:8080", "clientRequestId": "ideal-conflict-2"}
    )
    changed = IdealLongLinkRequest.model_validate(
        {"accessToken": "token", "proxy": "http://proxy-two.test:8080", "clientRequestId": "ideal-conflict-2"}
    )
    start(first)

    ideal_link.LONG_LINK_CLIENT_REQUESTS.clear()
    with pytest.raises(HTTPException) as exc:
        start(changed)

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "idempotency_conflict"
    assert starts == 1


def test_get_ideal_long_link_job_by_client_request_id_recovers_original_job(monkeypatch):
    from autotoken.api_routes import ideal_link

    app = _app()
    ideal_link.LONG_LINK_CLIENT_REQUESTS.clear()
    monkeypatch.setattr(ideal_link.legacy, "start_long_link_job", lambda req: {"job_id": "ideal-recovered-job"})
    monkeypatch.setattr(
        ideal_link.legacy,
        "job_snapshot",
        lambda job_id: {
            "job_id": job_id,
            "status": "running",
            "steps": [],
            "diagnostic_url": f"/api/long-link/jobs/{job_id}/diagnostics",
        },
    )
    request = IdealLongLinkRequest.model_validate(
        {"accessToken": "token", "clientRequestId": "ideal-recover-1"}
    )
    _endpoint(app, "/api/ideal/long-link/start", "POST")(request)

    recovered = _endpoint(
        app,
        "/api/ideal/long-link/jobs/by-client-request/{client_request_id}",
        "GET",
    )("ideal-recover-1")

    assert recovered["job_id"] == "ideal-recovered-job"
    assert recovered["client_request_id"] == "ideal-recover-1"
    assert recovered["status"] == "running"
    assert recovered["diagnostic_url"] == "/api/ideal/long-link/jobs/ideal-recovered-job/diagnostics"


def test_get_ideal_long_link_job_by_client_request_id_recovers_after_memory_reset(monkeypatch):
    from autotoken.api_routes import ideal_link

    app = _app()
    monkeypatch.setattr(
        ideal_link.legacy,
        "start_long_link_job",
        lambda req: {"job_id": "ideal-restarted-query-job"},
    )
    monkeypatch.setattr(
        ideal_link.legacy,
        "job_snapshot",
        lambda job_id: {"job_id": job_id, "status": "running", "steps": []},
    )
    request = IdealLongLinkRequest.model_validate(
        {"accessToken": "token", "clientRequestId": "ideal-restarted-query-1"}
    )
    _endpoint(app, "/api/ideal/long-link/start", "POST")(request)

    ideal_link.LONG_LINK_CLIENT_REQUESTS.clear()
    recovered = _endpoint(
        app,
        "/api/ideal/long-link/jobs/by-client-request/{client_request_id}",
        "GET",
    )("ideal-restarted-query-1")

    assert recovered["job_id"] == "ideal-restarted-query-job"
    assert recovered["client_request_id"] == "ideal-restarted-query-1"
    assert recovered["status"] == "running"


def test_get_ideal_long_link_job_by_reserved_client_request_fails_closed(monkeypatch):
    from autotoken.api_routes import ideal_link

    app = _app()
    snapshots = 0

    def ambiguous_start(req):
        raise RuntimeError("legacy start response was lost")

    def snapshot(job_id):
        nonlocal snapshots
        snapshots += 1
        return {"job_id": job_id, "status": "running", "steps": []}

    monkeypatch.setattr(ideal_link.legacy, "start_long_link_job", ambiguous_start)
    monkeypatch.setattr(ideal_link.legacy, "job_snapshot", snapshot)
    request = IdealLongLinkRequest.model_validate(
        {"accessToken": "token", "clientRequestId": "ideal-reserved-query-1"}
    )
    with pytest.raises(HTTPException):
        _endpoint(app, "/api/ideal/long-link/start", "POST")(request)

    ideal_link.LONG_LINK_CLIENT_REQUESTS.clear()
    with pytest.raises(HTTPException) as exc:
        _endpoint(
            app,
            "/api/ideal/long-link/jobs/by-client-request/{client_request_id}",
            "GET",
        )("ideal-reserved-query-1")

    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "idempotency_result_unknown"
    assert snapshots == 0


def test_get_ideal_long_link_job_by_client_request_fails_closed_for_corrupt_store(monkeypatch):
    from autotoken.api_routes import ideal_link

    corrupt_contents = "{not-valid-json"
    ideal_link.LONG_LINK_CLIENT_REQUESTS_FILE.write_text(corrupt_contents, encoding="utf-8")
    snapshots = 0

    def snapshot(job_id):
        nonlocal snapshots
        snapshots += 1
        return {"job_id": job_id, "status": "running", "steps": []}

    monkeypatch.setattr(ideal_link.legacy, "job_snapshot", snapshot)

    with pytest.raises(HTTPException) as exc:
        _endpoint(
            _app(),
            "/api/ideal/long-link/jobs/by-client-request/{client_request_id}",
            "GET",
        )("ideal-corrupt-query-1")

    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "idempotency_store_unavailable"
    assert snapshots == 0
    assert ideal_link.LONG_LINK_CLIENT_REQUESTS_FILE.read_text(encoding="utf-8") == corrupt_contents


def test_get_ideal_long_link_job_by_client_request_id_keeps_missing_legacy_job_unknown(monkeypatch):
    from autotoken.api_routes import ideal_link

    app = _app()
    ideal_link.LONG_LINK_CLIENT_REQUESTS.clear()
    monkeypatch.setattr(ideal_link.legacy, "start_long_link_job", lambda req: {"job_id": "ideal-missing-job"})
    request = IdealLongLinkRequest.model_validate(
        {"accessToken": "token", "clientRequestId": "ideal-missing-1"}
    )
    _endpoint(app, "/api/ideal/long-link/start", "POST")(request)

    def missing_snapshot(job_id):
        raise HTTPException(status_code=404, detail="job not found")

    monkeypatch.setattr(ideal_link.legacy, "job_snapshot", missing_snapshot)
    recovered = _endpoint(
        app,
        "/api/ideal/long-link/jobs/by-client-request/{client_request_id}",
        "GET",
    )("ideal-missing-1")

    assert recovered["job_id"] == "ideal-missing-job"
    assert recovered["client_request_id"] == "ideal-missing-1"
    assert recovered["status"] == "unknown_outcome"
    assert "不会自动重提" in recovered["error"]


def test_ideal_batch_defaults_to_nl_checkout_and_provider(monkeypatch, tmp_path):
    from autotoken.api_routes import ideal_link

    app = _app()
    captured = {}

    class ImmediateThread:
        def __init__(self, target, daemon=False):
            self._target = target

        def start(self):
            self._target()

    class FakeResult:
        def model_dump(self):
            return {
                "cs_id": "cs_ideal",
                "billing_country": "NL",
                "currency": "EUR",
                "link_type": "ideal",
                "long_url": "https://pay.openai.com/ideal",
                "amount": "0",
                "amount_display": "€0.00",
                "provider_redirect_url": "https://pay.openai.com/ideal",
                "stripe_redirect_url": "",
                "stripe_hosted_url": "",
            }

    def fake_prepare(long_req):
        captured["checkout_proxy_region"] = long_req.checkout_proxy_region
        captured["provider_proxy_region"] = long_req.provider_proxy_region
        return False

    monkeypatch.setattr(ideal_link, "LINKS_FILE", tmp_path / "ideal_links.json")
    monkeypatch.setattr(ideal_link, "ACCOUNT_STATUS_FILE", tmp_path / "ideal_account_status.json")
    monkeypatch.setattr(ideal_link.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(ideal_link.pix_routes, "_iter_auth_accounts", lambda include_paid=False: [
        {"email": "ideal@example.com", "ttl_seconds": 3600, "updated_at": 1},
    ])
    monkeypatch.setattr(ideal_link.pix_routes, "_load_token_for_email", lambda email: "token-for-" + email)
    monkeypatch.setattr(ideal_link.account_store, "load_accounts", lambda: [])
    monkeypatch.setattr(ideal_link.legacy, "prepare_request_proxy", fake_prepare)
    monkeypatch.setattr(ideal_link.legacy, "generate_long_link_once", lambda req, use_explicit_proxy, steps=None: FakeResult())
    ideal_link.JOBS.clear()

    result = _endpoint(app, "/api/ideal/batch/start", "POST")(
        IdealBatchStartRequest.model_validate({"accountEmails": ["ideal@example.com"], "concurrency": 1})
    )

    assert _endpoint(app, "/api/ideal/jobs/{job_id}", "GET")(result["job_id"])["status"] == "success"
    assert captured == {"checkout_proxy_region": "NL", "provider_proxy_region": "NL"}


def test_get_ideal_long_link_job_returns_snapshot(monkeypatch):
    app = _app()
    monkeypatch.setattr(
        "autotoken.api_routes.ideal_link.legacy.job_snapshot",
        lambda job_id: {"status": "done", "result": {"long_url": "https://pay.openai.com/x"}, "job_id": job_id},
    )

    result = _endpoint(app, "/api/ideal/long-link/jobs/{job_id}", "GET")("ideal-job-1")

    assert result["status"] == "done"
    assert result["job_id"] == "ideal-job-1"


def test_create_ideal_qr_returns_png(monkeypatch):
    app = _app()

    def fake_qr_code(req):
        from fastapi.responses import StreamingResponse

        assert req.value == "https://pay.openai.com/test"
        return StreamingResponse(io.BytesIO(b"png-bytes"), media_type="image/png")

    monkeypatch.setattr("autotoken.api_routes.ideal_link.legacy.qr_code", fake_qr_code)

    response = _endpoint(app, "/api/ideal/qr", "POST")(IdealQrRequest(value="https://pay.openai.com/test"))

    assert response.media_type == "image/png"


def test_ideal_long_link_job_keeps_account_on_non_zero_amount(monkeypatch):
    email = "ideal-nonzero@example.com"
    payload = base64.urlsafe_b64encode(json.dumps({"email": email}).encode("utf-8")).decode("ascii").rstrip("=")
    access_token = f"eyJhbGciOiJub25lIn0.{payload}.sig"
    deleted_accounts: list[str] = []
    deleted_sessions: list[str] = []
    disabled_legacy: list[str] = []

    class ImmediateThread:
        def __init__(self, target, daemon=False):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(ideal_app.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(ideal_app, "prepare_request_proxy", lambda req: False)
    monkeypatch.setattr(ideal_app, "save_diagnostics", lambda req, job_id, final_status: "")
    monkeypatch.setattr(ideal_app.account_store, "delete_account", lambda value: deleted_accounts.append(value) or True)
    monkeypatch.setattr(ideal_app, "delete_auth_session", lambda value: deleted_sessions.append(value) or True)
    monkeypatch.setattr(ideal_app.account_pool_store, "disable_account_by_email", lambda value: disabled_legacy.append(value) or True)

    def fake_generate(req, use_explicit_proxy, steps=None):
        raise HTTPException(status_code=502, detail="amount policy failed after retries: amount=1667, allowed<= 0")

    monkeypatch.setattr(ideal_app, "generate_long_link_once", fake_generate)
    ideal_app.LONG_LINK_JOBS.clear()

    result = ideal_app.start_long_link_job(
        ideal_app.LongLinkRequest.model_validate(
            {
                "accessToken": access_token,
                "proxy": "",
                "link_type": "ideal",
                "billing_country": "NL",
            }
        )
    )

    job = ideal_app.job_snapshot(result["job_id"])
    assert job["status"] == "error"
    assert "金额非 0" in job["error"]
    assert "已从账号池删除" not in job["error"]
    assert deleted_accounts == []
    assert deleted_sessions == []
    assert disabled_legacy == []


def test_ideal_prepare_request_proxy_uses_configured_preflight_attempts(monkeypatch):
    preflighted: list[str] = []

    def fake_payment_preflight(proxy_url):
        preflighted.append(proxy_url)
        return (False, "ProxyError: ruleset blocked")

    monkeypatch.setattr(proxy_runtime, "preflight_payment_proxy_url", fake_payment_preflight)
    monkeypatch.setattr(proxy_runtime, "preflight_chatgpt_authenticated_proxy_url", lambda proxy_url, access_token: (True, "auth_api HTTP 200"))

    req = ideal_app.LongLinkRequest.model_validate(
        {
            "accessToken": "token",
            "proxy": "proxy.example:1000:user-region-US-sid-old-t-120:pass",
            "link_type": "ideal",
            "billing_country": "NL",
            "proxyPreflightAttempts": 3,
        }
    )

    with pytest.raises(HTTPException, match="代理预检失败"):
        ideal_app.prepare_request_proxy(req)

    assert len(preflighted) == 3


def test_ideal_prepare_request_proxy_normalizes_711_colon_proxy_and_applies_region(monkeypatch):
    raw_proxy = (
        "global.rotgb.711proxy.com:10000:"
        "USER000000-zone-custom-region-VN-session-39391603-sessTime-10-sessAuto-1:"
        "secret"
    )
    expected_proxy = (
        "http://USER000000-zone-custom-region-NL-session-39391603-sessTime-10-sessAuto-1:"
        "secret@global.rotgb.711proxy.com:10000"
    )
    preflighted: list[str] = []
    auth_preflighted: list[str] = []

    def fake_payment_preflight(proxy_url):
        preflighted.append(proxy_url)
        return (True, "ok")

    def fake_auth_preflight(proxy_url, access_token):
        auth_preflighted.append(proxy_url)
        return (True, "auth_api HTTP 200")

    monkeypatch.setattr(ideal_app, "refresh_711_proxy", lambda proxy_or_region: True)
    monkeypatch.setattr(proxy_runtime, "preflight_payment_proxy_url", fake_payment_preflight)
    monkeypatch.setattr(proxy_runtime, "preflight_chatgpt_authenticated_proxy_url", fake_auth_preflight)

    req = ideal_app.LongLinkRequest.model_validate(
        {
            "accessToken": "token",
            "proxy": raw_proxy,
            "link_type": "ideal",
            "billing_country": "NL",
            "checkoutProxyRegion": "NL",
        }
    )

    assert ideal_app.prepare_request_proxy(req) is True
    assert req.proxy == expected_proxy
    assert preflighted == [expected_proxy]
    assert auth_preflighted == [expected_proxy]


def test_ideal_amount_policy_requires_exact_zero():
    assert ideal_app.is_acceptable_low_amount("0") is True
    assert ideal_app.is_acceptable_low_amount(0) is True
    assert ideal_app.is_acceptable_low_amount("1") is False
    assert ideal_app.is_acceptable_low_amount(1) is False
    assert ideal_app.is_acceptable_low_amount("-1") is False


def test_ideal_accounts_default_to_pending_status(monkeypatch, tmp_path):
    app = _app()
    from autotoken.api_routes import ideal_link

    monkeypatch.setattr(ideal_link, "LINKS_FILE", tmp_path / "ideal_links.json")
    monkeypatch.setattr(ideal_link, "ACCOUNT_STATUS_FILE", tmp_path / "ideal_account_status.json")
    monkeypatch.setattr(ideal_link.pix_routes, "_iter_auth_accounts", lambda include_paid=False: [
        {"email": "ideal@example.com", "ttl_seconds": 3600, "updated_at": 1},
    ])
    monkeypatch.setattr(ideal_link.account_store, "load_accounts", lambda: [
        {"email": "ideal@example.com", "status": "active"},
    ])

    result = _endpoint(app, "/api/ideal/accounts", "GET")()

    assert result["accounts"][0]["email"] == "ideal@example.com"
    assert result["accounts"][0]["ideal_status"] == "pending"
    assert result["accounts"][0]["ideal_status_text"] == "未提链"
    assert result["accounts"][0]["ideal_selectable"] is True


def test_ideal_batch_start_runs_accounts_and_persists_link(monkeypatch, tmp_path):
    app = _app()
    from autotoken.api_routes import ideal_link

    class ImmediateThread:
        def __init__(self, target, daemon=False):
            self.target = target

        def start(self):
            self.target()

    class FakeResult:
        def model_dump(self):
            return {
                "ok": True,
                "cs_id": "cs_ideal",
                "billing_country": "NL",
                "currency": "EUR",
                "link_type": "ideal",
                "long_url": "https://pay.openai.com/ideal",
                "amount": "0",
                "amount_display": "€0.00",
                "steps": [{"time": "12:00:00", "name": "done", "status": "ok", "detail": ""}],
            }

    monkeypatch.setattr(ideal_link, "LINKS_FILE", tmp_path / "ideal_links.json")
    monkeypatch.setattr(ideal_link, "ACCOUNT_STATUS_FILE", tmp_path / "ideal_account_status.json")
    monkeypatch.setattr(ideal_link.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(ideal_link.pix_routes, "_iter_auth_accounts", lambda include_paid=False: [
        {"email": "ideal@example.com", "ttl_seconds": 3600, "updated_at": 1},
    ])
    monkeypatch.setattr(ideal_link.pix_routes, "_load_token_for_email", lambda email: "token-for-" + email)
    monkeypatch.setattr(ideal_link.account_store, "load_accounts", lambda: [])
    monkeypatch.setattr(ideal_link.legacy, "prepare_request_proxy", lambda req: False)
    monkeypatch.setattr(ideal_link.legacy, "generate_long_link_once", lambda req, use_explicit_proxy, steps=None: FakeResult())
    ideal_link.JOBS.clear()

    result = _endpoint(app, "/api/ideal/batch/start", "POST")(
        IdealBatchStartRequest.model_validate({"accountEmails": ["ideal@example.com"], "concurrency": 1})
    )
    job = _endpoint(app, "/api/ideal/jobs/{job_id}", "GET")(result["job_id"])
    links = _endpoint(app, "/api/ideal/links", "GET")()

    assert job["status"] == "success"
    assert job["successes"][0]["email"] == "ideal@example.com"
    assert links["links"][0]["ideal_link"] == "https://pay.openai.com/ideal"
    assert links["links"][0]["account_email"] == "ideal@example.com"


def test_ideal_batch_propagates_proxy_preflight_attempts(monkeypatch, tmp_path):
    app = _app()
    from autotoken.api_routes import ideal_link

    class ImmediateThread:
        def __init__(self, target, daemon=False):
            self.target = target

        def start(self):
            self.target()

    class FakeResult:
        def model_dump(self):
            return {
                "ok": True,
                "cs_id": "cs_ideal",
                "billing_country": "NL",
                "currency": "EUR",
                "link_type": "ideal",
                "long_url": "https://pay.openai.com/ideal",
                "amount": "0",
                "amount_display": "€0.00",
            }

    captured: dict[str, int] = {}

    def fake_prepare(req):
        captured["attempts"] = req.proxy_preflight_attempts
        return False

    monkeypatch.setattr(ideal_link, "LINKS_FILE", tmp_path / "ideal_links.json")
    monkeypatch.setattr(ideal_link, "ACCOUNT_STATUS_FILE", tmp_path / "ideal_account_status.json")
    monkeypatch.setattr(ideal_link.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(ideal_link.pix_routes, "_iter_auth_accounts", lambda include_paid=False: [
        {"email": "ideal@example.com", "ttl_seconds": 3600, "updated_at": 1},
    ])
    monkeypatch.setattr(ideal_link.pix_routes, "_load_token_for_email", lambda email: "token-for-" + email)
    monkeypatch.setattr(ideal_link.account_store, "load_accounts", lambda: [])
    monkeypatch.setattr(ideal_link.legacy, "prepare_request_proxy", fake_prepare)
    monkeypatch.setattr(ideal_link.legacy, "generate_long_link_once", lambda req, use_explicit_proxy, steps=None: FakeResult())
    ideal_link.JOBS.clear()

    result = _endpoint(app, "/api/ideal/batch/start", "POST")(
        IdealBatchStartRequest.model_validate({
            "accountEmails": ["ideal@example.com"],
            "concurrency": 1,
            "proxyPreflightAttempts": 4,
        })
    )

    assert _endpoint(app, "/api/ideal/jobs/{job_id}", "GET")(result["job_id"])["status"] == "success"
    assert captured["attempts"] == 4


def test_ideal_proxy_preflight_attempts_cap_at_one_hundred():
    batch_req = IdealBatchStartRequest.model_validate({
        "accountEmails": [],
        "proxyPreflightAttempts": 200,
    })
    long_req = ideal_app.LongLinkRequest.model_validate({
        "accessToken": "token",
        "proxyPreflightAttempts": 200,
    })

    assert batch_req.proxy_preflight_attempts == 100
    assert long_req.proxy_preflight_attempts == 100


def test_ideal_links_delete_and_clear_use_ideal_file(tmp_path, monkeypatch):
    app = _app()
    from autotoken.api_routes import ideal_link

    links_file = tmp_path / "ideal_links.json"
    links_file.write_text(json.dumps([
        {"id": "keep", "ideal_link": "https://pay.openai.com/keep"},
        {"id": "remove", "ideal_link": "https://pay.openai.com/remove"},
    ]), encoding="utf-8")
    monkeypatch.setattr(ideal_link, "LINKS_FILE", links_file)

    deleted = _endpoint(app, "/api/ideal/links/delete", "POST")(IdealDeleteLinksRequest(ids=["remove", "missing"]))
    cleared = _endpoint(app, "/api/ideal/links/clear", "POST")()

    assert deleted["deleted"] == 1
    assert cleared["deleted"] == 1
    assert json.loads(links_file.read_text(encoding="utf-8")) == []


def test_ideal_batch_reserves_account_before_worker_start_and_blocks_duplicate_and_delete(monkeypatch, tmp_path):
    from autotoken.api_routes import ideal_link

    pending_threads = []

    class DeferredThread:
        def __init__(self, target, daemon=False):
            self.target = target

        def start(self):
            pending_threads.append(self.target)

    monkeypatch.setattr(ideal_link, "LINKS_FILE", tmp_path / "ideal_links.json")
    monkeypatch.setattr(ideal_link, "ACCOUNT_STATUS_FILE", tmp_path / "ideal_account_status.json")
    monkeypatch.setattr(ideal_link.threading, "Thread", DeferredThread)
    monkeypatch.setattr(ideal_link.pix_routes, "_iter_auth_accounts", lambda include_paid=False: [
        {"email": "occupied@example.com", "ttl_seconds": 3600, "updated_at": 1},
    ])
    monkeypatch.setattr(ideal_link.account_store, "load_accounts", lambda: [
        {"email": "occupied@example.com", "status": "active"},
    ])
    ideal_link.JOBS.clear()
    app = _app()
    start = _endpoint(app, "/api/ideal/batch/start", "POST")

    first = start(IdealBatchStartRequest.model_validate({"accountEmails": ["occupied@example.com"]}))

    with pytest.raises(HTTPException) as duplicate:
        start(IdealBatchStartRequest.model_validate({"accountEmails": ["occupied@example.com"]}))
    assert duplicate.value.status_code == 409
    assert first["job_id"] in str(duplicate.value.detail)
    accounts = _endpoint(app, "/api/ideal/accounts", "GET")()["accounts"]
    assert accounts[0]["ideal_status"] == "queued"
    assert accounts[0]["ideal_selectable"] is False
    with pytest.raises(HTTPException) as deleting:
        _endpoint(app, "/api/ideal/accounts/{email}", "DELETE")("occupied@example.com")
    assert deleting.value.status_code == 409
    assert len(pending_threads) == 1


def test_ideal_restart_quarantines_orphaned_job_and_account(monkeypatch, tmp_path):
    from autotoken.api_routes import ideal_link

    status_file = tmp_path / "ideal_account_status.json"
    status_file.write_text(json.dumps({
        "orphan@example.com": {
            "status": "running",
            "status_text": "提链中",
            "error": "",
            "job_id": "job-before-restart",
            "updated_at": "2026-08-30 10:00:00",
        },
    }), encoding="utf-8")
    monkeypatch.setattr(ideal_link, "LINKS_FILE", tmp_path / "ideal_links.json")
    monkeypatch.setattr(ideal_link, "ACCOUNT_STATUS_FILE", status_file)
    monkeypatch.setattr(ideal_link.pix_routes, "_iter_auth_accounts", lambda include_paid=False: [
        {"email": "orphan@example.com", "ttl_seconds": 3600, "updated_at": 1},
    ])
    monkeypatch.setattr(ideal_link.account_store, "load_accounts", lambda: [
        {"email": "orphan@example.com", "status": "active"},
    ])
    ideal_link.JOBS.clear()
    app = _app()

    snapshot = _endpoint(app, "/api/ideal/jobs/{job_id}", "GET")("job-before-restart")
    assert snapshot["status"] == "unknown_outcome"
    assert snapshot["account_emails"] == ["orphan@example.com"]
    accounts = _endpoint(app, "/api/ideal/accounts", "GET")()["accounts"]
    assert accounts[0]["ideal_status"] == "unknown_outcome"
    assert accounts[0]["ideal_selectable"] is False
    with pytest.raises(HTTPException) as duplicate:
        _endpoint(app, "/api/ideal/batch/start", "POST")(
            IdealBatchStartRequest.model_validate({"accountEmails": ["orphan@example.com"]})
        )
    assert duplicate.value.status_code == 409
    assert "job-before-restart" in str(duplicate.value.detail)
    with pytest.raises(HTTPException) as deleting:
        _endpoint(app, "/api/ideal/accounts/{email}", "DELETE")("orphan@example.com")
    assert deleting.value.status_code == 409


def test_ideal_account_reservation_fails_closed_when_status_store_is_corrupt(monkeypatch, tmp_path):
    from autotoken.api_routes import ideal_link

    status_file = tmp_path / "ideal_account_status.json"
    corrupt_contents = '{"occupied@example.com":'
    status_file.write_text(corrupt_contents, encoding="utf-8")
    monkeypatch.setattr(ideal_link, "ACCOUNT_STATUS_FILE", status_file)
    ideal_link.JOBS.clear()

    with pytest.raises(HTTPException) as exc:
        with ideal_link.JOBS_LOCK:
            ideal_link._reserve_accounts_locked("replacement-job", ["occupied@example.com"])

    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "account_status_store_unavailable"
    assert status_file.read_text(encoding="utf-8") == corrupt_contents


def test_ideal_cancel_keeps_account_reserved_until_job_reaches_terminal_state(monkeypatch, tmp_path):
    from autotoken.api_routes import ideal_link

    pending_threads = []

    class DeferredThread:
        def __init__(self, target, daemon=False):
            self.target = target

        def start(self):
            pending_threads.append(self.target)

    monkeypatch.setattr(ideal_link, "LINKS_FILE", tmp_path / "ideal_links.json")
    monkeypatch.setattr(ideal_link, "ACCOUNT_STATUS_FILE", tmp_path / "ideal_account_status.json")
    monkeypatch.setattr(ideal_link.threading, "Thread", DeferredThread)
    monkeypatch.setattr(ideal_link.pix_routes, "_iter_auth_accounts", lambda include_paid=False: [
        {"email": "cancel@example.com", "ttl_seconds": 3600, "updated_at": 1},
    ])
    monkeypatch.setattr(ideal_link.account_store, "load_accounts", lambda: [
        {"email": "cancel@example.com", "status": "active"},
    ])
    ideal_link.JOBS.clear()
    app = _app()
    start = _endpoint(app, "/api/ideal/batch/start", "POST")
    first = start(IdealBatchStartRequest.model_validate({"accountEmails": ["cancel@example.com"]}))

    cancelled = _endpoint(app, "/api/ideal/jobs/{job_id}/cancel", "POST")(first["job_id"])
    assert cancelled["status"] == "cancelling"
    during_cancel = _endpoint(app, "/api/ideal/accounts", "GET")()["accounts"][0]
    assert during_cancel["ideal_status"] == "cancelling"
    assert during_cancel["ideal_selectable"] is False
    with pytest.raises(HTTPException) as duplicate:
        start(IdealBatchStartRequest.model_validate({"accountEmails": ["cancel@example.com"]}))
    assert duplicate.value.status_code == 409

    pending_threads[0]()

    assert _endpoint(app, "/api/ideal/jobs/{job_id}", "GET")(first["job_id"])["status"] == "cancelled"
    after_cancel = _endpoint(app, "/api/ideal/accounts", "GET")()["accounts"][0]
    assert after_cancel["ideal_selectable"] is True
    second = start(IdealBatchStartRequest.model_validate({"accountEmails": ["cancel@example.com"]}))
    assert second["job_id"] != first["job_id"]


def test_ideal_unhandled_worker_failure_quarantines_reserved_account(monkeypatch, tmp_path):
    from autotoken.api_routes import ideal_link

    pending_threads = []

    class DeferredThread:
        def __init__(self, target, daemon=False):
            self.target = target

        def start(self):
            pending_threads.append(self.target)

    monkeypatch.setattr(ideal_link, "LINKS_FILE", tmp_path / "ideal_links.json")
    monkeypatch.setattr(ideal_link, "ACCOUNT_STATUS_FILE", tmp_path / "ideal_account_status.json")
    monkeypatch.setattr(ideal_link.threading, "Thread", DeferredThread)
    monkeypatch.setattr(ideal_link.pix_routes, "_iter_auth_accounts", lambda include_paid=False: [
        {"email": "crash@example.com", "ttl_seconds": 3600, "updated_at": 1},
    ])
    monkeypatch.setattr(ideal_link.account_store, "load_accounts", lambda: [
        {"email": "crash@example.com", "status": "active"},
    ])
    ideal_link.JOBS.clear()
    app = _app()
    start = _endpoint(app, "/api/ideal/batch/start", "POST")
    result = start(IdealBatchStartRequest.model_validate({"accountEmails": ["crash@example.com"]}))
    monkeypatch.setattr(ideal_link, "_run_batch_job", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("worker crashed")))

    pending_threads[0]()

    snapshot = _endpoint(app, "/api/ideal/jobs/{job_id}", "GET")(result["job_id"])
    assert snapshot["status"] == "unknown_outcome"
    assert snapshot["unknown_outcome"] is True
    account = _endpoint(app, "/api/ideal/accounts", "GET")()["accounts"][0]
    assert account["ideal_status"] == "unknown_outcome"
    assert account["ideal_selectable"] is False


def test_ideal_completed_account_stays_reserved_until_batch_is_terminal(monkeypatch, tmp_path):
    from autotoken.api_routes import ideal_link

    class FakeResult:
        def model_dump(self):
            return {
                "cs_id": "cs_reserved",
                "billing_country": "NL",
                "currency": "EUR",
                "link_type": "ideal",
                "long_url": "https://pay.openai.com/reserved",
                "amount": "0",
                "amount_display": "€0.00",
            }

    monkeypatch.setattr(ideal_link, "LINKS_FILE", tmp_path / "ideal_links.json")
    monkeypatch.setattr(ideal_link, "ACCOUNT_STATUS_FILE", tmp_path / "ideal_account_status.json")
    monkeypatch.setattr(ideal_link.pix_routes, "_iter_auth_accounts", lambda include_paid=False: [
        {"email": "reserved@example.com", "ttl_seconds": 3600, "updated_at": 1},
    ])
    monkeypatch.setattr(ideal_link.pix_routes, "_load_token_for_email", lambda email: "token")
    monkeypatch.setattr(ideal_link.account_store, "load_accounts", lambda: [
        {"email": "reserved@example.com", "status": "active"},
    ])
    monkeypatch.setattr(ideal_link.legacy, "prepare_request_proxy", lambda req: False)
    monkeypatch.setattr(ideal_link.legacy, "generate_long_link_once", lambda req, use_explicit_proxy, steps=None: FakeResult())
    ideal_link.JOBS.clear()
    ideal_link.JOBS["batch-running"] = {
        "job_id": "batch-running",
        "status": "running",
        "account_emails": ["reserved@example.com"],
        "cancel_requested": False,
    }
    ideal_link._set_account_status("reserved@example.com", ideal_link.IDEAL_STATUS_QUEUED, job_id="batch-running")

    ideal_link._run_account(
        "batch-running",
        IdealBatchStartRequest.model_validate({"accountEmails": ["reserved@example.com"]}),
        {"email": "reserved@example.com"},
        0,
    )

    account = _endpoint(_app(), "/api/ideal/accounts", "GET")()["accounts"][0]
    assert account["ideal_status"] == "running"
    assert account["ideal_selectable"] is False


def test_ideal_manual_reconcile_release_unlocks_only_unknown_job_and_keeps_audit(monkeypatch, tmp_path):
    from autotoken.api_routes import ideal_link

    pending_threads = []

    class DeferredThread:
        def __init__(self, target, daemon=False):
            self.target = target

        def start(self):
            pending_threads.append(self.target)

    monkeypatch.setattr(ideal_link, "LINKS_FILE", tmp_path / "ideal_links.json")
    monkeypatch.setattr(ideal_link, "ACCOUNT_STATUS_FILE", tmp_path / "ideal_account_status.json")
    monkeypatch.setattr(ideal_link.threading, "Thread", DeferredThread)
    monkeypatch.setattr(ideal_link.pix_routes, "_iter_auth_accounts", lambda include_paid=False: [
        {"email": "reviewed@example.com", "ttl_seconds": 3600, "updated_at": 1},
    ])
    monkeypatch.setattr(ideal_link.account_store, "load_accounts", lambda: [
        {"email": "reviewed@example.com", "status": "active"},
    ])
    ideal_link.JOBS.clear()
    ideal_link.JOBS["unknown-reviewed"] = ideal_link._unknown_job_snapshot(
        "unknown-reviewed",
        ["reviewed@example.com"],
    )
    ideal_link._set_account_status(
        "reviewed@example.com",
        ideal_link.IDEAL_STATUS_UNKNOWN,
        error="remote result unknown",
        job_id="unknown-reviewed",
    )
    app = _app()

    released = _endpoint(app, "/api/ideal/jobs/{job_id}/reconcile-release", "POST")("unknown-reviewed")

    assert released == {
        "ok": True,
        "job_id": "unknown-reviewed",
        "released": True,
        "already_released": False,
        "account_emails": ["reviewed@example.com"],
    }
    job = ideal_link.JOBS["unknown-reviewed"]
    assert job["status"] == "cancelled"
    assert job["unknown_outcome"] is False
    assert job["error_code"] == "manual_reconciled_release"
    assert len(job["reconciliation_history"]) == 1
    account_status = ideal_link._load_account_statuses()["reviewed@example.com"]
    assert account_status["status"] == "failed"
    assert account_status["reconciled_job_id"] == "unknown-reviewed"
    assert account_status["reconciled_at"]
    account = _endpoint(app, "/api/ideal/accounts", "GET")()["accounts"][0]
    assert account["ideal_selectable"] is True
    restarted = _endpoint(app, "/api/ideal/batch/start", "POST")(
        IdealBatchStartRequest.model_validate({"accountEmails": ["reviewed@example.com"]})
    )
    assert restarted["job_id"] != "unknown-reviewed"
    assert len(pending_threads) == 1
    durable_audit = json.loads((tmp_path / "ideal_reconciliation_audit.json").read_text(encoding="utf-8"))
    assert len(durable_audit) == 1
    assert durable_audit[0]["job_id"] == "unknown-reviewed"
    assert durable_audit[0]["action"] == "manual_reconciled_release"
    assert durable_audit[0]["account_emails"] == ["reviewed@example.com"]


def test_ideal_manual_reconcile_release_rejects_non_unknown_job(monkeypatch, tmp_path):
    from autotoken.api_routes import ideal_link

    monkeypatch.setattr(ideal_link, "ACCOUNT_STATUS_FILE", tmp_path / "ideal_account_status.json")
    ideal_link.JOBS.clear()
    ideal_link.JOBS["still-running"] = {
        "job_id": "still-running",
        "status": "running",
        "account_emails": ["running@example.com"],
        "unknown_outcome": False,
    }
    ideal_link._set_account_status(
        "running@example.com",
        ideal_link.IDEAL_STATUS_RUNNING,
        job_id="still-running",
    )

    with pytest.raises(HTTPException) as rejected:
        _endpoint(_app(), "/api/ideal/jobs/{job_id}/reconcile-release", "POST")("still-running")

    assert rejected.value.status_code == 409
    assert ideal_link.JOBS["still-running"]["status"] == "running"
    assert ideal_link._load_account_statuses()["running@example.com"]["status"] == "running"


def test_ideal_manual_reconcile_release_is_idempotent_under_concurrency(monkeypatch, tmp_path):
    from autotoken.api_routes import ideal_link

    monkeypatch.setattr(ideal_link, "ACCOUNT_STATUS_FILE", tmp_path / "ideal_account_status.json")
    ideal_link.JOBS.clear()
    ideal_link.JOBS["unknown-concurrent"] = ideal_link._unknown_job_snapshot(
        "unknown-concurrent",
        ["concurrent@example.com"],
    )
    ideal_link._set_account_status(
        "concurrent@example.com",
        ideal_link.IDEAL_STATUS_UNKNOWN,
        error="remote result unknown",
        job_id="unknown-concurrent",
    )
    release = _endpoint(_app(), "/api/ideal/jobs/{job_id}/reconcile-release", "POST")

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: release("unknown-concurrent"), range(8)))

    assert sum(result["released"] is True for result in results) == 1
    assert sum(result["already_released"] is True for result in results) == 7
    assert all(result["account_emails"] == ["concurrent@example.com"] for result in results)
    assert len(ideal_link.JOBS["unknown-concurrent"]["reconciliation_history"]) == 1
    status = ideal_link._load_account_statuses()["concurrent@example.com"]
    assert status["status"] == "failed"
    assert status["reconciled_job_id"] == "unknown-concurrent"


def test_ideal_concurrent_cancel_drains_running_futures_and_skips_pending_remote_work(monkeypatch, tmp_path):
    from autotoken.api_routes import ideal_link

    emails = ["success@example.com", "error@example.com", "pending@example.com"]
    both_started = threading.Event()
    release_success = threading.Event()
    release_error = threading.Event()
    started_lock = threading.Lock()
    started: list[str] = []

    class FakeResult:
        def __init__(self, email):
            self.email = email

        def model_dump(self):
            return {
                "cs_id": f"cs_{self.email.split('@')[0]}",
                "billing_country": "NL",
                "currency": "EUR",
                "link_type": "ideal",
                "long_url": f"https://pay.openai.com/{self.email.split('@')[0]}",
                "amount": "0",
                "amount_display": "€0.00",
            }

    def fake_generate(req, use_explicit_proxy, steps=None):
        email = str(req.access_token).removeprefix("token-")
        with started_lock:
            started.append(email)
            if len(started) == 2:
                both_started.set()
        if email == "success@example.com":
            assert release_success.wait(5)
            return FakeResult(email)
        if email == "error@example.com":
            assert release_error.wait(5)
            raise RuntimeError("remote failed after cancel")
        raise AssertionError("pending account must not begin remote work after cancellation")

    monkeypatch.setattr(ideal_link, "LINKS_FILE", tmp_path / "ideal_links.json")
    monkeypatch.setattr(ideal_link, "ACCOUNT_STATUS_FILE", tmp_path / "ideal_account_status.json")
    monkeypatch.setattr(ideal_link.pix_routes, "_iter_auth_accounts", lambda include_paid=False: [
        {"email": email, "ttl_seconds": 3600, "updated_at": 1} for email in emails
    ])
    monkeypatch.setattr(ideal_link.pix_routes, "_load_token_for_email", lambda email: f"token-{email}")
    monkeypatch.setattr(ideal_link.account_store, "load_accounts", lambda: [
        {"email": email, "status": "active"} for email in emails
    ])
    monkeypatch.setattr(ideal_link.legacy, "prepare_request_proxy", lambda req: False)
    monkeypatch.setattr(ideal_link.legacy, "generate_long_link_once", fake_generate)
    ideal_link.JOBS.clear()
    request = IdealBatchStartRequest.model_validate({"accountEmails": emails, "concurrency": 2})
    with ideal_link.JOBS_LOCK:
        ideal_link.JOBS["cancel-drain"] = {
            "job_id": "cancel-drain",
            "status": "queued",
            "total": 3,
            "completed": 0,
            "concurrency": 2,
            "successes": [],
            "errors": [],
            "logs": [],
            "current_result": None,
            "error": "",
            "cancel_requested": False,
            "account_emails": emails,
            "started_at": time.time(),
            "updated_at": time.time(),
        }
        ideal_link._reserve_accounts_locked("cancel-drain", emails)

    worker = threading.Thread(target=ideal_link._run_batch_job_safely, args=("cancel-drain", request, [
        {"email": email} for email in emails
    ]))
    worker.start()
    assert both_started.wait(5)
    cancelled = _endpoint(_app(), "/api/ideal/jobs/{job_id}/cancel", "POST")("cancel-drain")
    assert cancelled["status"] == "cancelling"
    release_success.set()
    deadline = time.time() + 5
    while time.time() < deadline:
        links = ideal_link._load_links()
        if any(item.get("account_email") == "success@example.com" for item in links):
            break
        time.sleep(0.01)
    else:
        raise AssertionError("successful in-flight future did not persist its link")
    release_error.set()
    worker.join(5)
    assert not worker.is_alive()

    job = ideal_link.JOBS["cancel-drain"]
    assert job["status"] == "cancelled"
    assert [item["email"] for item in job["successes"]] == ["success@example.com"]
    errors_by_email = {item["email"]: item["error"] for item in job["errors"]}
    assert "remote failed after cancel" in errors_by_email["error@example.com"]
    assert "任务已取消" in errors_by_email["pending@example.com"]
    links = ideal_link._load_links()
    assert any(item["account_email"] == "success@example.com" for item in links)
    statuses = ideal_link._load_account_statuses()
    assert statuses["success@example.com"]["status"] == "success"
    assert statuses["error@example.com"]["status"] == "failed"
    assert "remote failed after cancel" in statuses["error@example.com"]["error"]
    assert statuses["pending@example.com"]["status"] == "failed"
    assert len(started) == 2
    assert set(started) == {"success@example.com", "error@example.com"}


def test_ideal_concurrent_cancel_records_every_remote_success_that_finishes_in_flight(monkeypatch, tmp_path):
    from autotoken.api_routes import ideal_link

    emails = ["a@example.com", "b@example.com", "pending@example.com"]
    both_started = threading.Event()
    release_a = threading.Event()
    release_b = threading.Event()
    state_lock = threading.Lock()
    started: list[str] = []
    remote_completed: list[str] = []

    class FakeResult:
        def __init__(self, email):
            self.email = email

        def model_dump(self):
            name = self.email.split("@")[0]
            return {
                "cs_id": f"cs_{name}",
                "billing_country": "NL",
                "currency": "EUR",
                "link_type": "ideal",
                "long_url": f"https://pay.openai.com/{name}",
                "amount": "0",
                "amount_display": "€0.00",
            }

    def fake_generate(req, use_explicit_proxy, steps=None):
        email = str(req.access_token).removeprefix("token-")
        with state_lock:
            started.append(email)
            if len(started) == 2:
                both_started.set()
        if email == "a@example.com":
            assert release_a.wait(5)
        elif email == "b@example.com":
            assert release_b.wait(5)
        else:
            raise AssertionError("pending account must not begin remote work after cancellation")
        with state_lock:
            remote_completed.append(email)
        return FakeResult(email)

    monkeypatch.setattr(ideal_link, "LINKS_FILE", tmp_path / "ideal_links.json")
    monkeypatch.setattr(ideal_link, "ACCOUNT_STATUS_FILE", tmp_path / "ideal_account_status.json")
    monkeypatch.setattr(
        ideal_link.pix_routes,
        "_iter_auth_accounts",
        lambda include_paid=False: [{"email": email, "ttl_seconds": 3600, "updated_at": 1} for email in emails],
    )
    monkeypatch.setattr(ideal_link.pix_routes, "_load_token_for_email", lambda email: f"token-{email}")
    monkeypatch.setattr(
        ideal_link.account_store,
        "load_accounts",
        lambda: [{"email": email, "status": "active"} for email in emails],
    )
    monkeypatch.setattr(ideal_link.legacy, "prepare_request_proxy", lambda req: False)
    monkeypatch.setattr(ideal_link.legacy, "generate_long_link_once", fake_generate)
    ideal_link.JOBS.clear()
    request = IdealBatchStartRequest.model_validate({"accountEmails": emails, "concurrency": 2})
    with ideal_link.JOBS_LOCK:
        ideal_link.JOBS["cancel-two-successes"] = {
            "job_id": "cancel-two-successes",
            "status": "queued",
            "total": 3,
            "completed": 0,
            "concurrency": 2,
            "successes": [],
            "errors": [],
            "logs": [],
            "current_result": None,
            "error": "",
            "cancel_requested": False,
            "account_emails": emails,
            "started_at": time.time(),
            "updated_at": time.time(),
        }
        ideal_link._reserve_accounts_locked("cancel-two-successes", emails)

    worker = threading.Thread(
        target=ideal_link._run_batch_job_safely,
        args=("cancel-two-successes", request, [{"email": email} for email in emails]),
    )
    worker.start()
    assert both_started.wait(5)
    cancelled = _endpoint(_app(), "/api/ideal/jobs/{job_id}/cancel", "POST")("cancel-two-successes")
    assert cancelled["status"] == "cancelling"

    release_a.set()
    deadline = time.time() + 5
    while time.time() < deadline:
        if any(item.get("account_email") == "a@example.com" for item in ideal_link._load_links()):
            break
        time.sleep(0.01)
    else:
        raise AssertionError("first in-flight success was not recorded")
    release_b.set()
    worker.join(5)
    assert not worker.is_alive()

    job = ideal_link.JOBS["cancel-two-successes"]
    assert remote_completed == ["a@example.com", "b@example.com"]
    assert sorted(item["email"] for item in job["successes"]) == ["a@example.com", "b@example.com"]
    assert job["errors"] == [{"email": "pending@example.com", "error": "任务已取消，账号未开始提链"}]
    assert sorted(started) == ["a@example.com", "b@example.com"]
