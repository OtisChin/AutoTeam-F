from __future__ import annotations

import json
import threading
import time

from autotoken.api_routes import brazil_pix
from autotoken.storage import auth_session_store


def _write_session(directory, email: str, token: str = "token-" + "x" * 80) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{email.lower().replace('.', '_')}.json").write_text(
        json.dumps({"email": email, "accessToken": token}),
        encoding="utf-8",
    )


def _isolate_files(monkeypatch, tmp_path):
    auth_dir = tmp_path / "auth_session"
    monkeypatch.setattr(brazil_pix, "AUTH_SESSION_DIR", auth_dir)
    monkeypatch.setattr(auth_session_store, "AUTH_SESSION_DIR", auth_dir)
    monkeypatch.setattr(brazil_pix.account_store, "ACCOUNTS_FILE", tmp_path / "accounts.json")
    monkeypatch.setattr(brazil_pix, "LINKS_FILE", tmp_path / "brazil_pix_links.json")
    monkeypatch.setattr(brazil_pix, "ACCOUNT_STATUS_FILE", tmp_path / "brazil_pix_account_status.json")
    return auth_dir


def test_accounts_include_pix_status_from_links_and_status_file(monkeypatch, tmp_path):
    auth_dir = _isolate_files(monkeypatch, tmp_path)
    _write_session(auth_dir, "done@example.com")
    _write_session(auth_dir, "failed@example.com")
    _write_session(auth_dir, "new@example.com")
    brazil_pix.LINKS_FILE.write_text(
        json.dumps([{"account_email": "done@example.com", "hosted_instructions_url": "https://pay.example"}]),
        encoding="utf-8",
    )
    brazil_pix.ACCOUNT_STATUS_FILE.write_text(
        json.dumps({"failed@example.com": {"status": "failed", "error": "boom"}}),
        encoding="utf-8",
    )

    accounts = {item["email"]: item for item in brazil_pix._iter_auth_accounts_with_pix_status()}

    assert accounts["done@example.com"]["pix_status"] == "success"
    assert accounts["done@example.com"]["pix_status_text"] == "已提链"
    assert accounts["failed@example.com"]["pix_status"] == "failed"
    assert accounts["failed@example.com"]["pix_status_text"] == "提链失败"
    assert accounts["failed@example.com"]["pix_error"] == "boom"
    assert accounts["new@example.com"]["pix_status"] == "pending"
    assert accounts["new@example.com"]["pix_status_text"] == "未提链"


def test_append_link_replaces_existing_link_for_same_account(monkeypatch, tmp_path):
    _isolate_files(monkeypatch, tmp_path)
    brazil_pix._append_link(
        {
            "id": "old",
            "account_email": "replace@example.com",
            "hosted_instructions_url": "https://payments.stripe.com/qr/instructions/old",
            "created_at": "old-time",
        }
    )
    brazil_pix._append_link(
        {
            "id": "new",
            "account_email": "replace@example.com",
            "hosted_instructions_url": "https://payments.stripe.com/qr/instructions/new",
            "created_at": "new-time",
        }
    )

    links = brazil_pix._load_links()

    assert len(links) == 1
    assert links[0]["id"] == "new"
    assert links[0]["hosted_instructions_url"].endswith("/new")


def test_load_links_rewrites_legacy_duplicates(monkeypatch, tmp_path):
    _isolate_files(monkeypatch, tmp_path)
    brazil_pix.LINKS_FILE.write_text(
        json.dumps(
            [
                {"id": "latest", "account_email": "same@example.com", "hosted_instructions_url": "https://pay/new"},
                {"id": "old", "account_email": "same@example.com", "hosted_instructions_url": "https://pay/old"},
            ]
        ),
        encoding="utf-8",
    )

    links = brazil_pix._load_links()
    stored = json.loads(brazil_pix.LINKS_FILE.read_text(encoding="utf-8"))

    assert [item["id"] for item in links] == ["latest"]
    assert [item["id"] for item in stored] == ["latest"]


def test_accounts_exclude_plus_from_pix_pool(monkeypatch, tmp_path):
    auth_dir = _isolate_files(monkeypatch, tmp_path)
    _write_session(auth_dir, "plus@example.com")
    _write_session(auth_dir, "free@example.com")
    brazil_pix.account_store.save_accounts(
        [
            {"email": "plus@example.com", "status": "active", "account_type": "plus"},
            {"email": "free@example.com", "status": "active", "account_type": "free"},
        ]
    )

    accounts = {item["email"] for item in brazil_pix._iter_auth_accounts_with_pix_status()}

    assert "plus@example.com" not in accounts
    assert "free@example.com" in accounts


def test_accounts_exclude_pix_bound_success_from_pix_pool(monkeypatch, tmp_path):
    auth_dir = _isolate_files(monkeypatch, tmp_path)
    _write_session(auth_dir, "pixbound@example.com")
    _write_session(auth_dir, "free@example.com")
    brazil_pix.account_store.save_accounts(
        [
            {
                "email": "pixbound@example.com",
                "status": "active",
                "account_type": "free",
                "last_bind_provider": "pix",
                "last_bind_status": "success",
            },
            {"email": "free@example.com", "status": "active", "account_type": "free"},
        ]
    )

    accounts = {item["email"] for item in brazil_pix._iter_auth_accounts_with_pix_status()}

    assert "pixbound@example.com" not in accounts
    assert "free@example.com" in accounts


def test_batch_job_updates_account_statuses(monkeypatch, tmp_path):
    auth_dir = _isolate_files(monkeypatch, tmp_path)
    _write_session(auth_dir, "ok@example.com", "ok-token-" + "x" * 80)
    _write_session(auth_dir, "bad@example.com", "bad-token-" + "x" * 80)
    brazil_pix.JOBS.clear()
    job_id = "pix-job"
    brazil_pix.JOBS[job_id] = {
        "id": job_id,
        "status": "queued",
        "logs": [],
        "result": None,
        "error": None,
        "created_at": 1,
        "finished_at": None,
        "account_email": "",
        "total": 0,
        "completed": 0,
        "account_statuses": {},
    }

    def fake_generate_pix_trial(cfg, log):
        if cfg.access_token.startswith("bad-token"):
            raise RuntimeError("pix failed")
        return {
            "fields": {
                "amount": "R$0.00",
                "cs_id": "cs_test",
                "pix_copy_paste": "pix-code",
                "hosted_instructions_url": "https://pay.example/pix",
            }
        }

    monkeypatch.setattr(brazil_pix, "generate_pix_trial", fake_generate_pix_trial)

    req = brazil_pix.BrazilPixBatchStartRequest.model_validate(
        {
            "accountEmails": ["ok@example.com", "bad@example.com"],
            "proxies": "socks5h://proxy.example:1080",
        }
    )
    brazil_pix._run_batch_job(job_id, req)

    job = brazil_pix.JOBS[job_id]
    assert job["status"] == "success"
    assert job["completed"] == 2
    assert job["concurrency"] == 1
    assert job["account_statuses"]["ok@example.com"]["status"] == "success"
    assert job["account_statuses"]["bad@example.com"]["status"] == "failed"
    assert job["result"]["successes"][0]["email"] == "ok@example.com"
    assert job["result"]["errors"][0]["email"] == "bad@example.com"

    statuses = json.loads(brazil_pix.ACCOUNT_STATUS_FILE.read_text(encoding="utf-8"))
    assert statuses["ok@example.com"]["status"] == "success"
    assert statuses["bad@example.com"]["status"] == "failed"


def test_batch_job_honors_concurrency(monkeypatch, tmp_path):
    auth_dir = _isolate_files(monkeypatch, tmp_path)
    for index in range(3):
        _write_session(auth_dir, f"user{index}@example.com", f"token-{index}-" + "x" * 80)
    brazil_pix.JOBS.clear()
    job_id = "pix-concurrent-job"
    brazil_pix.JOBS[job_id] = {
        "id": job_id,
        "status": "queued",
        "logs": [],
        "result": None,
        "error": None,
        "created_at": 1,
        "finished_at": None,
        "account_email": "",
        "total": 0,
        "completed": 0,
        "account_statuses": {},
    }
    lock = threading.Lock()
    active = 0
    max_active = 0

    def fake_generate_pix_trial(cfg, log):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return {
            "fields": {
                "amount": "R$0.00",
                "cs_id": f"cs_{cfg.access_token[:7]}",
                "pix_copy_paste": "pix-code",
                "hosted_instructions_url": "https://pay.example/pix",
            }
        }

    monkeypatch.setattr(brazil_pix, "generate_pix_trial", fake_generate_pix_trial)

    req = brazil_pix.BrazilPixBatchStartRequest.model_validate(
        {
            "accountEmails": ["user0@example.com", "user1@example.com", "user2@example.com"],
            "proxies": "socks5h://proxy.example:1080",
            "concurrency": 2,
        }
    )
    brazil_pix._run_batch_job(job_id, req)

    job = brazil_pix.JOBS[job_id]
    assert job["status"] == "success"
    assert job["completed"] == 3
    assert job["concurrency"] == 2
    assert len(job["result"]["successes"]) == 3
    assert max_active >= 2


def test_batch_job_retries_failed_account_up_to_three_attempts(monkeypatch, tmp_path):
    auth_dir = _isolate_files(monkeypatch, tmp_path)
    _write_session(auth_dir, "retry@example.com", "retry-token-" + "x" * 80)
    brazil_pix.JOBS.clear()
    job_id = "pix-retry-job"
    brazil_pix.JOBS[job_id] = {
        "id": job_id,
        "status": "queued",
        "logs": [],
        "result": None,
        "error": None,
        "created_at": 1,
        "finished_at": None,
        "account_email": "",
        "total": 0,
        "completed": 0,
        "account_statuses": {},
    }
    calls = 0

    def fake_generate_pix_trial(cfg, log):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError(f"temporary failure {calls}")
        return {
            "fields": {
                "amount": "R$0.00",
                "cs_id": "cs_retry",
                "pix_copy_paste": "pix-code",
                "hosted_instructions_url": "https://pay.example/pix",
            }
        }

    monkeypatch.setattr(brazil_pix, "generate_pix_trial", fake_generate_pix_trial)

    req = brazil_pix.BrazilPixBatchStartRequest.model_validate(
        {
            "accountEmails": ["retry@example.com"],
            "proxies": "socks5h://proxy.example:1080",
        }
    )
    brazil_pix._run_batch_job(job_id, req)

    job = brazil_pix.JOBS[job_id]
    assert calls == 3
    assert job["status"] == "success"
    assert job["result"]["successes"][0]["email"] == "retry@example.com"
    assert job["result"]["successes"][0]["attempts"] == 3
    assert not job["result"]["errors"]


def test_batch_job_marks_already_paid_account_plus_pix(monkeypatch, tmp_path):
    auth_dir = _isolate_files(monkeypatch, tmp_path)
    email = "paid@example.com"
    _write_session(auth_dir, email, "paid-token-" + "x" * 80)
    brazil_pix.account_store.save_accounts([{"email": email, "status": "active", "account_type": "free"}])
    brazil_pix.JOBS.clear()
    job_id = "pix-paid-job"
    brazil_pix.JOBS[job_id] = {
        "id": job_id,
        "status": "queued",
        "logs": [],
        "result": None,
        "error": None,
        "created_at": 1,
        "finished_at": None,
        "account_email": "",
        "total": 0,
        "completed": 0,
        "account_statuses": {},
    }

    def fake_generate_pix_trial(cfg, log):
        raise RuntimeError("checkout failed: User is already paid")

    monkeypatch.setattr(brazil_pix, "generate_pix_trial", fake_generate_pix_trial)

    req = brazil_pix.BrazilPixBatchStartRequest.model_validate(
        {
            "accountEmails": [email],
            "proxies": "socks5h://proxy.example:1080",
        }
    )
    brazil_pix._run_batch_job(job_id, req)

    account = brazil_pix.account_store.find_account(brazil_pix.account_store.load_accounts(), email)
    job = brazil_pix.JOBS[job_id]
    assert job["status"] == "success"
    assert job["result"]["skipped"][0]["reason"] == "账号已是 Plus，已标记绑定渠道 Pix"
    assert not job["result"]["errors"]
    assert account["account_type"] == "plus"
    assert account["last_bind_provider"] == "pix"
    assert account["last_bind_status"] == "success"


def test_batch_job_deletes_token_invalidated_account(monkeypatch, tmp_path):
    auth_dir = _isolate_files(monkeypatch, tmp_path)
    email = "invalid@example.com"
    _write_session(auth_dir, email, "invalid-token-" + "x" * 80)
    brazil_pix.account_store.save_accounts([{"email": email, "status": "active", "account_type": "free"}])
    brazil_pix.JOBS.clear()
    job_id = "pix-invalid-job"
    brazil_pix.JOBS[job_id] = {
        "id": job_id,
        "status": "queued",
        "logs": [],
        "result": None,
        "error": None,
        "created_at": 1,
        "finished_at": None,
        "account_email": "",
        "total": 0,
        "completed": 0,
        "account_statuses": {},
    }

    def fake_generate_pix_trial(cfg, log):
        raise RuntimeError(
            'checkout failed: { "error": { "message": "Your authentication token has been invalidated. Please try signing in again.", "code": "token_invalidated" }, "status": 401 }'
        )

    monkeypatch.setattr(brazil_pix, "generate_pix_trial", fake_generate_pix_trial)

    req = brazil_pix.BrazilPixBatchStartRequest.model_validate(
        {
            "accountEmails": [email],
            "proxies": "socks5h://proxy.example:1080",
        }
    )
    brazil_pix._run_batch_job(job_id, req)

    account = brazil_pix.account_store.find_account(brazil_pix.account_store.load_accounts(), email)
    job = brazil_pix.JOBS[job_id]
    assert job["status"] == "error"
    assert account is None
    assert not (auth_dir / "invalid@example_com.json").exists()
    assert "账号已失效，已从账号池删除" in job["result"]["errors"][0]["error"]


def test_batch_job_deletes_non_zero_after_promo_account(monkeypatch, tmp_path):
    auth_dir = _isolate_files(monkeypatch, tmp_path)
    email = "promo@example.com"
    _write_session(auth_dir, email, "promo-token-" + "x" * 80)
    brazil_pix.account_store.save_accounts([{"email": email, "status": "active", "account_type": "free"}])
    brazil_pix.JOBS.clear()
    job_id = "pix-promo-job"
    brazil_pix.JOBS[job_id] = {
        "id": job_id,
        "status": "queued",
        "logs": [],
        "result": None,
        "error": None,
        "created_at": 1,
        "finished_at": None,
        "account_email": "",
        "total": 0,
        "completed": 0,
        "account_statuses": {},
    }

    def fake_generate_pix_trial(cfg, log):
        raise RuntimeError("套 promo 后金额不是 0: 9990")

    monkeypatch.setattr(brazil_pix, "generate_pix_trial", fake_generate_pix_trial)

    req = brazil_pix.BrazilPixBatchStartRequest.model_validate(
        {
            "accountEmails": [email],
            "proxies": "socks5h://proxy.example:1080",
        }
    )
    brazil_pix._run_batch_job(job_id, req)

    account = brazil_pix.account_store.find_account(brazil_pix.account_store.load_accounts(), email)
    job = brazil_pix.JOBS[job_id]
    assert job["status"] == "error"
    assert account is None
    assert not (auth_dir / "promo@example_com.json").exists()
    assert "套 promo 后金额非 0，已从账号池删除" in job["result"]["errors"][0]["error"]


def test_batch_job_cancel_skips_not_started_accounts(monkeypatch, tmp_path):
    auth_dir = _isolate_files(monkeypatch, tmp_path)
    for index in range(3):
        _write_session(auth_dir, f"cancel{index}@example.com", f"cancel-token-{index}-" + "x" * 80)
    brazil_pix.JOBS.clear()
    job_id = "pix-cancel-job"
    brazil_pix.JOBS[job_id] = {
        "id": job_id,
        "status": "queued",
        "logs": [],
        "result": None,
        "error": None,
        "created_at": 1,
        "finished_at": None,
        "account_email": "",
        "total": 0,
        "completed": 0,
        "concurrency": 1,
        "running_count": 0,
        "cancel_requested": False,
        "skipped": [],
        "account_statuses": {},
    }
    calls = 0

    def fake_generate_pix_trial(cfg, log):
        nonlocal calls
        calls += 1
        with brazil_pix.JOBS_LOCK:
            brazil_pix.JOBS[job_id]["cancel_requested"] = True
            brazil_pix.JOBS[job_id]["status"] = "cancelling"
        return {
            "fields": {
                "amount": "R$0.00",
                "cs_id": "cs_cancel",
                "pix_copy_paste": "pix-code",
                "hosted_instructions_url": "https://pay.example/pix",
            }
        }

    monkeypatch.setattr(brazil_pix, "generate_pix_trial", fake_generate_pix_trial)

    req = brazil_pix.BrazilPixBatchStartRequest.model_validate(
        {
            "accountEmails": ["cancel0@example.com", "cancel1@example.com", "cancel2@example.com"],
            "proxies": "socks5h://proxy.example:1080",
            "concurrency": 1,
        }
    )
    brazil_pix._run_batch_job(job_id, req)

    job = brazil_pix.JOBS[job_id]
    assert calls == 1
    assert job["status"] == "cancelled"
    assert job["completed"] == 3
    assert len(job["result"]["successes"]) == 1
    assert len(job["result"]["skipped"]) == 2
    assert job["running_count"] == 0


class _FakeResponse:
    def __init__(self, status_code: int, data: dict):
        self.status_code = status_code
        self._data = data
        self.text = json.dumps(data)
        self.ok = 200 <= status_code < 400

    def json(self):
        return self._data


def _route_endpoint(path: str, method: str):
    router = brazil_pix.create_brazil_pix_router()
    for route in router.routes:
        if getattr(route, "path", "") == path and method.upper() in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


def test_payment_submit_proxies_pix_cdk_api(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return _FakeResponse(
            202,
            {
                "ok": True,
                "job_id": "job123",
                "status_token": "token123",
                "status": "queued",
                "message": "已进入支付队列",
            },
        )

    monkeypatch.setattr(brazil_pix.requests, "post", fake_post)

    endpoint = _route_endpoint("/api/brazil-pix/payment/submit", "POST")
    data = endpoint(brazil_pix.BrazilPixPaymentSubmitRequest(cdk="PIX-1", link="https://payments.stripe.com/qr/instructions/abc"))

    assert data["job_id"] == "job123"
    assert calls[0][0] == "https://pix.iceaix.com/api/submit"
    assert calls[0][1]["json"] == {"cdk": "PIX-1", "link": "https://payments.stripe.com/qr/instructions/abc"}
    assert calls[0][1]["timeout"] == 70


def test_payment_job_query_proxies_pix_cdk_api(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return _FakeResponse(200, {"ok": True, "job": {"job_id": "job123", "status": "succeeded", "message": ""}})

    monkeypatch.setattr(brazil_pix.requests, "get", fake_get)

    endpoint = _route_endpoint("/api/brazil-pix/payment/jobs/{job_id}", "GET")
    data = endpoint("job123", token="token123")

    assert data["job"]["status"] == "succeeded"
    assert calls[0][0] == "https://pix.iceaix.com/api/jobs/job123"
    assert calls[0][1]["params"] == {"token": "token123"}


def test_payment_success_marks_link_account_plus_pix(monkeypatch, tmp_path):
    _isolate_files(monkeypatch, tmp_path)
    email = "buyer@example.com"
    link = "https://payments.stripe.com/qr/instructions/abc"
    brazil_pix.account_store.save_accounts([{"email": email, "status": "active", "account_type": "free"}])
    brazil_pix.LINKS_FILE.write_text(json.dumps([{"account_email": email, "hosted_instructions_url": link}]), encoding="utf-8")
    brazil_pix.PAYMENT_JOBS.clear()
    brazil_pix.PAYMENT_JOBS["job123"] = {"job_id": "job123", "link": link, "status_token": "token123"}

    def fake_get(url, **kwargs):
        return _FakeResponse(200, {"ok": True, "job": {"job_id": "job123", "status": "succeeded", "message": "支付成功"}})

    monkeypatch.setattr(brazil_pix.requests, "get", fake_get)

    endpoint = _route_endpoint("/api/brazil-pix/payment/jobs/{job_id}", "GET")
    data = endpoint("job123", token="token123")

    account = brazil_pix.account_store.find_account(brazil_pix.account_store.load_accounts(), email)
    assert data["job"]["account_email"] == email
    assert data["job"]["account_type"] == "plus"
    assert data["job"]["last_bind_provider"] == "pix"
    assert data["job"]["account_marked_plus"] is True
    assert account["account_type"] == "plus"
    assert account["last_bind_provider"] == "pix"
    assert account["last_bind_status"] == "success"
