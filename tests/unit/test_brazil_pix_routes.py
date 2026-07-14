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
