from __future__ import annotations

import json
import threading
import time

import pytest
from fastapi import HTTPException

from autotoken.api_routes import brazil_pix
from autotoken.services import proxy_runtime
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
    monkeypatch.setattr(proxy_runtime, "preflight_payment_proxy_url", lambda proxy_url: (True, "HTTP 200"))
    monkeypatch.setattr(proxy_runtime, "preflight_chatgpt_authenticated_proxy_url", lambda proxy_url, access_token: (True, "auth_api HTTP 200"))
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


def test_delete_account_artifacts_removes_links_and_status(monkeypatch, tmp_path):
    _isolate_files(monkeypatch, tmp_path)
    brazil_pix.LINKS_FILE.write_text(
        json.dumps(
            [
                {"id": "remove", "account_email": "Deleted@example.com", "hosted_instructions_url": "https://pay/remove"},
                {"id": "keep", "account_email": "keep@example.com", "hosted_instructions_url": "https://pay/keep"},
            ]
        ),
        encoding="utf-8",
    )
    brazil_pix.ACCOUNT_STATUS_FILE.write_text(
        json.dumps(
            {
                "deleted@example.com": {"status": "failed", "error": "boom"},
                "keep@example.com": {"status": "success", "error": ""},
            }
        ),
        encoding="utf-8",
    )

    result = brazil_pix.delete_account_artifacts("deleted@example.com")

    assert result == {"links_deleted": 1, "status_deleted": True}
    assert [item["id"] for item in brazil_pix._load_links()] == ["keep"]
    statuses = json.loads(brazil_pix.ACCOUNT_STATUS_FILE.read_text(encoding="utf-8"))
    assert "deleted@example.com" not in statuses
    assert "keep@example.com" in statuses


def test_load_links_pruning_deleted_accounts_removes_orphan_links(monkeypatch, tmp_path):
    auth_dir = _isolate_files(monkeypatch, tmp_path)
    _write_session(auth_dir, "keep@example.com")
    brazil_pix.LINKS_FILE.write_text(
        json.dumps(
            [
                {"id": "stale", "account_email": "deleted@example.com", "hosted_instructions_url": "https://pay/stale"},
                {"id": "keep", "account_email": "keep@example.com", "hosted_instructions_url": "https://pay/keep"},
                {"id": "manual", "account_email": "", "hosted_instructions_url": "https://pay/manual"},
            ]
        ),
        encoding="utf-8",
    )
    brazil_pix.ACCOUNT_STATUS_FILE.write_text(
        json.dumps({"deleted@example.com": {"status": "success"}, "keep@example.com": {"status": "success"}}),
        encoding="utf-8",
    )

    links, pruned = brazil_pix._load_links_pruning_deleted_accounts()

    assert pruned == 1
    assert [item["id"] for item in links] == ["keep", "manual"]
    stored = json.loads(brazil_pix.LINKS_FILE.read_text(encoding="utf-8"))
    assert [item["id"] for item in stored] == ["keep", "manual"]
    statuses = json.loads(brazil_pix.ACCOUNT_STATUS_FILE.read_text(encoding="utf-8"))
    assert "deleted@example.com" not in statuses
    assert "keep@example.com" in statuses


def test_auth_accounts_ignore_leftover_session_when_dashboard_pool_has_accounts(monkeypatch, tmp_path):
    auth_dir = _isolate_files(monkeypatch, tmp_path)
    _write_session(auth_dir, "deleted@example.com")
    _write_session(auth_dir, "keep@example.com")
    brazil_pix.account_store.save_accounts(
        [{"email": "keep@example.com", "status": "personal", "account_type": "free"}]
    )

    accounts = {item["email"] for item in brazil_pix._iter_auth_accounts_with_pix_status()}

    assert accounts == {"keep@example.com"}


def test_auth_accounts_order_by_dashboard_updated_at_desc(monkeypatch, tmp_path):
    auth_dir = _isolate_files(monkeypatch, tmp_path)
    _write_session(auth_dir, "old@example.com")
    _write_session(auth_dir, "new@example.com")
    _write_session(auth_dir, "middle@example.com")
    monkeypatch.setattr(brazil_pix.account_store, "load_accounts", lambda: [
        {"email": "old@example.com", "status": "active", "account_type": "free", "updated_at": 100.0},
        {"email": "new@example.com", "status": "active", "account_type": "free", "updated_at": 300.0},
        {"email": "middle@example.com", "status": "active", "account_type": "free", "updated_at": 200.0},
    ])

    accounts = brazil_pix._iter_auth_accounts(include_paid=True)

    assert [item["email"] for item in accounts] == ["new@example.com", "middle@example.com", "old@example.com"]


def test_auth_accounts_include_phone_registered_session_by_nested_user_email(monkeypatch, tmp_path):
    auth_dir = _isolate_files(monkeypatch, tmp_path)
    phone = "+5511999998888"
    auth_dir.mkdir(parents=True, exist_ok=True)
    (auth_dir / "5511999998888.json").write_text(
        json.dumps({"accessToken": "phone-token-" + "x" * 80, "user": {"email": phone}}),
        encoding="utf-8",
    )
    brazil_pix.account_store.save_accounts(
        [{"email": phone, "status": "active", "account_type": "free"}]
    )

    accounts = {item["email"]: item for item in brazil_pix._iter_auth_accounts_with_pix_status()}

    assert phone in accounts
    assert accounts[phone]["pix_status"] == "pending"


def test_load_links_pruning_deleted_accounts_removes_paid_links(monkeypatch, tmp_path):
    auth_dir = _isolate_files(monkeypatch, tmp_path)
    _write_session(auth_dir, "paid@example.com")
    _write_session(auth_dir, "free@example.com")
    brazil_pix.account_store.save_accounts(
        [
            {"email": "paid@example.com", "status": "active", "account_type": "plus"},
            {"email": "free@example.com", "status": "active", "account_type": "free"},
        ]
    )
    brazil_pix.LINKS_FILE.write_text(
        json.dumps(
            [
                {"id": "paid", "account_email": "paid@example.com", "hosted_instructions_url": "https://pay/paid"},
                {"id": "free", "account_email": "free@example.com", "hosted_instructions_url": "https://pay/free"},
            ]
        ),
        encoding="utf-8",
    )

    links, pruned = brazil_pix._load_links_pruning_deleted_accounts()

    assert pruned == 1
    assert [item["id"] for item in links] == ["free"]


def test_accounts_show_plus_as_paid_but_exclude_from_selectable_auth_pool(monkeypatch, tmp_path):
    auth_dir = _isolate_files(monkeypatch, tmp_path)
    _write_session(auth_dir, "plus@example.com")
    _write_session(auth_dir, "free@example.com")
    brazil_pix.account_store.save_accounts(
        [
            {"email": "plus@example.com", "status": "active", "account_type": "plus"},
            {"email": "free@example.com", "status": "active", "account_type": "free"},
        ]
    )

    accounts = {item["email"]: item for item in brazil_pix._iter_auth_accounts_with_pix_status()}
    selectable = {item["email"] for item in brazil_pix._iter_auth_accounts()}

    assert accounts["plus@example.com"]["pix_status"] == "paid"
    assert accounts["plus@example.com"]["pix_status_text"] == "已支付"
    assert accounts["plus@example.com"]["pix_selectable"] is False
    assert accounts["free@example.com"]["pix_status"] == "pending"
    assert "plus@example.com" not in selectable
    assert "free@example.com" in selectable


def test_accounts_show_pix_bound_success_as_paid_but_exclude_from_selectable_auth_pool(monkeypatch, tmp_path):
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

    accounts = {item["email"]: item for item in brazil_pix._iter_auth_accounts_with_pix_status()}
    selectable = {item["email"] for item in brazil_pix._iter_auth_accounts()}

    assert accounts["pixbound@example.com"]["pix_status"] == "paid"
    assert accounts["pixbound@example.com"]["pix_status_text"] == "已支付"
    assert accounts["pixbound@example.com"]["pix_selectable"] is False
    assert accounts["free@example.com"]["pix_status"] == "pending"
    assert "pixbound@example.com" not in selectable
    assert "free@example.com" in selectable


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


def test_batch_account_preflights_proxy_before_pix_generation(monkeypatch, tmp_path):
    auth_dir = _isolate_files(monkeypatch, tmp_path)
    _write_session(auth_dir, "blocked@example.com", "blocked-token-" + "x" * 80)
    preflighted: list[str] = []

    def fake_preflight(proxy_url):
        preflighted.append(proxy_url)
        return (False, "ProxyError: ruleset blocked")

    monkeypatch.setattr(proxy_runtime, "preflight_payment_proxy_url", fake_preflight)
    monkeypatch.setattr(brazil_pix, "generate_pix_trial", lambda cfg, log: pytest.fail("should not generate when proxy preflight fails"))
    job_id = "pix-preflight-job"
    brazil_pix.JOBS[job_id] = {
        "id": job_id,
        "status": "queued",
        "logs": [],
        "result": None,
        "error": None,
        "created_at": 1,
        "finished_at": None,
        "account_email": "",
        "total": 1,
        "completed": 0,
        "concurrency": 1,
        "cancel_requested": False,
        "running_count": 0,
        "skipped": [],
        "account_statuses": {},
    }

    req = brazil_pix.BrazilPixBatchStartRequest.model_validate({
        "accountEmails": ["blocked@example.com"],
        "proxies": "global.rotgb.711proxy.com:10000:USER-zone-custom-region-US-session-fixed-sessTime-120-sessAuto-1:pass",
        "maxAttempts": 5,
    })
    result = brazil_pix._run_batch_account(
        job_id,
        req,
        {"email": "blocked@example.com", "auth_file": "auth.json"},
        1,
        1,
        brazil_pix._parse_proxies(req.proxies),
    )

    assert result["ok"] is False
    assert len(preflighted) == 5
    assert "代理预检失败" in result["error"]["error"]
    assert "ruleset blocked" in result["error"]["error"]
    assert any("代理预检失败" in line for line in brazil_pix.JOBS[job_id]["logs"])


def test_batch_account_auth_preflight_blocks_pix_generation(monkeypatch, tmp_path):
    _isolate_files(monkeypatch, tmp_path)
    email = "auth-blocked@example.com"
    monkeypatch.setattr(brazil_pix, "_load_token_for_email", lambda value: "token-" + value)
    monkeypatch.setattr(proxy_runtime, "preflight_payment_proxy_url", lambda proxy_url: (True, "trace HTTP 200; chatgpt_home HTTP 200"))
    monkeypatch.setattr(proxy_runtime, "preflight_chatgpt_authenticated_proxy_url", lambda proxy_url, access_token: (False, "auth_api HTTP 403; html_challenge"))
    monkeypatch.setattr(brazil_pix, "generate_pix_trial", lambda cfg, log: pytest.fail("should not generate when authenticated proxy preflight fails"))
    job_id = "pix-auth-preflight-job"
    brazil_pix.JOBS[job_id] = {
        "id": job_id, "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1, "finished_at": None, "account_email": "", "total": 1,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {},
    }

    req = brazil_pix.BrazilPixBatchStartRequest.model_validate({
        "accountEmails": [email],
        "proxies": "proxy.example:1000:user-region-BR-sid-old-t-120:pass",
        "maxAttempts": 5,
    })
    result = brazil_pix._run_batch_account(job_id, req, {"email": email}, 1, 1, brazil_pix._parse_proxies(req.proxies))

    assert result["ok"] is False
    assert "auth_api HTTP 403" in result["error"]["error"]
    assert any("认证接口预检失败" in line for line in brazil_pix.JOBS[job_id]["logs"])


def test_pix_proxy_preflight_has_separate_five_attempt_budget(monkeypatch, tmp_path):
    _isolate_files(monkeypatch, tmp_path)
    email = "preflight-ok@example.com"
    monkeypatch.setattr(brazil_pix, "_load_token_for_email", lambda value: "token-" + value)
    preflighted: list[str] = []
    captured = {}

    def fake_preflight(proxy_url):
        preflighted.append(proxy_url)
        return (len(preflighted) == 5, "HTTP 200" if len(preflighted) == 5 else "ProxyError: ruleset blocked")

    def fake_generate_pix_trial(cfg, log):
        captured["cfg"] = cfg
        return {
            "fields": {
                "amount": "R$0.00",
                "cs_id": "cs_test",
                "pix_copy_paste": "pix-code",
                "hosted_instructions_url": "https://pay.example/pix",
            }
        }

    monkeypatch.setattr(proxy_runtime, "preflight_payment_proxy_url", fake_preflight)
    monkeypatch.setattr(brazil_pix, "generate_pix_trial", fake_generate_pix_trial)
    job_id = "pix-preflight-ok-job"
    brazil_pix.JOBS[job_id] = {
        "id": job_id, "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1, "finished_at": None, "account_email": "", "total": 1,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {},
    }

    req = brazil_pix.BrazilPixBatchStartRequest.model_validate({
        "accountEmails": [email],
        "proxies": "\n".join([
            "proxy1.example:1000:user-region-US-sid-old1-t-120:pass",
            "proxy2.example:1000:user-region-US-sid-old2-t-120:pass",
            "proxy3.example:1000:user-region-US-sid-old3-t-120:pass",
            "proxy4.example:1000:user-region-US-sid-old4-t-120:pass",
            "proxy5.example:1000:user-region-US-sid-old5-t-120:pass",
            "proxy6.example:1000:user-region-US-sid-old6-t-120:pass",
        ]),
        "maxAttempts": 1,
    })
    result = brazil_pix._run_batch_account(job_id, req, {"email": email}, 1, 1, brazil_pix._parse_proxies(req.proxies))

    assert result["ok"] is True
    assert len(preflighted) == 5
    assert "proxy5.example" in captured["cfg"].direct_proxies[0]
    assert brazil_pix.build_pix_dynamic_proxy(captured["cfg"], 0)[0] == preflighted[-1]
    assert not any("proxy6.example" in proxy for proxy in preflighted)


def test_single_job_deletes_token_revoked_account(monkeypatch, tmp_path):
    auth_dir = _isolate_files(monkeypatch, tmp_path)
    email = "single-revoked@example.com"
    _write_session(auth_dir, email, "single-revoked-token-" + "x" * 80)
    brazil_pix.account_store.save_accounts([{"email": email, "status": "active", "account_type": "free"}])
    brazil_pix.JOBS.clear()
    job_id = "pix-single-revoked-job"
    brazil_pix.JOBS[job_id] = {
        "id": job_id,
        "status": "queued",
        "logs": [],
        "result": None,
        "error": None,
        "created_at": 1,
        "finished_at": None,
        "account_email": "",
        "account_statuses": {},
        "cancel_requested": False,
        "running_count": 0,
    }

    def fake_generate_pix_trial(cfg, log):
        raise RuntimeError(
            'checkout failed: { "error": { "message": "Encountered invalidated oauth token for user, failing request", "code": "token_revoked" }, "status": 401 }'
        )

    monkeypatch.setattr(brazil_pix, "generate_pix_trial", fake_generate_pix_trial)

    req = brazil_pix.BrazilPixStartRequest.model_validate({"accountEmail": email, "proxies": "socks5h://proxy.example:1080"})
    brazil_pix._run_job(job_id, req)

    account = brazil_pix.account_store.find_account(brazil_pix.account_store.load_accounts(), email)
    job = brazil_pix.JOBS[job_id]
    assert job["status"] == "error"
    assert account is None
    assert not (auth_dir / "single-revoked@example_com.json").exists()
    assert "账号已失效，已从账号池删除" in job["error"]


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


def test_batch_concurrency_allows_twenty(monkeypatch, tmp_path):
    _isolate_files(monkeypatch, tmp_path)
    req = brazil_pix.BrazilPixBatchStartRequest.model_validate({"accountEmails": [], "concurrency": 25})

    assert brazil_pix._batch_concurrency(req, total=30) == 20


def test_batch_job_retries_failed_account_up_to_five_attempts(monkeypatch, tmp_path):
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
    monkeypatch.setattr(brazil_pix.time, "sleep", lambda _seconds: None)

    def fake_generate_pix_trial(cfg, log):
        nonlocal calls
        calls += 1
        if calls < 5:
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
    assert calls == 5
    assert job["status"] == "success"
    assert job["result"]["successes"][0]["email"] == "retry@example.com"
    assert job["result"]["successes"][0]["attempts"] == 5
    assert not job["result"]["errors"]


def test_batch_job_uses_requested_max_attempts(monkeypatch, tmp_path):
    auth_dir = _isolate_files(monkeypatch, tmp_path)
    _write_session(auth_dir, "retry-limit@example.com", "retry-token-" + "x" * 80)
    brazil_pix.JOBS.clear()
    job_id = "pix-max-attempts-job"
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
    monkeypatch.setattr(brazil_pix.time, "sleep", lambda _seconds: None)

    def fake_generate_pix_trial(cfg, log):
        nonlocal calls
        calls += 1
        raise RuntimeError(f"temporary failure {calls}")

    monkeypatch.setattr(brazil_pix, "generate_pix_trial", fake_generate_pix_trial)

    req = brazil_pix.BrazilPixBatchStartRequest.model_validate(
        {
            "accountEmails": ["retry-limit@example.com"],
            "proxies": "socks5h://proxy.example:1080",
            "maxAttempts": 2,
        }
    )
    brazil_pix._run_batch_job(job_id, req)

    job = brazil_pix.JOBS[job_id]
    assert calls == 2
    assert job["result"]["errors"][0]["attempts"] == 2


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


def test_batch_job_deletes_token_revoked_oauth_account(monkeypatch, tmp_path):
    auth_dir = _isolate_files(monkeypatch, tmp_path)
    email = "revoked@example.com"
    _write_session(auth_dir, email, "revoked-token-" + "x" * 80)
    brazil_pix.account_store.save_accounts([{"email": email, "status": "active", "account_type": "free"}])
    brazil_pix.JOBS.clear()
    job_id = "pix-revoked-job"
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
            'checkout failed: { "error": { "message": "Encountered invalidated oauth token for user, failing request", "type": null, "code": "token_revoked", "param": null }, "status": 401 }'
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
    assert not (auth_dir / "revoked@example_com.json").exists()
    assert "账号已失效，已从账号池删除" in job["result"]["errors"][0]["error"]


def test_batch_job_deletes_no_organization_account(monkeypatch, tmp_path):
    auth_dir = _isolate_files(monkeypatch, tmp_path)
    email = "no-org@example.com"
    _write_session(auth_dir, email, "no-org-token-" + "x" * 80)
    brazil_pix.account_store.save_accounts([{"email": email, "status": "active", "account_type": "free"}])
    brazil_pix.JOBS.clear()
    job_id = "pix-no-org-job"
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
            'checkout failed: { "error": { "message": "You must be a member of an organization to use the API.", "code": "no_organization" }, "status": 400 }'
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
    assert not (auth_dir / "no-org@example_com.json").exists()
    assert "账号缺少 Platform organization，已从账号池删除" in job["result"]["errors"][0]["error"]


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
    assert "金额非 0，已从账号池删除" in job["result"]["errors"][0]["error"]


def test_batch_job_deletes_any_non_zero_amount_account(monkeypatch, tmp_path):
    auth_dir = _isolate_files(monkeypatch, tmp_path)
    email = "nonzero@example.com"
    _write_session(auth_dir, email, "nonzero-token-" + "x" * 80)
    brazil_pix.account_store.save_accounts([{"email": email, "status": "active", "account_type": "free"}])
    brazil_pix.JOBS.clear()
    job_id = "pix-any-nonzero-job"
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
        raise RuntimeError("金额必须为 0: 1667")

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
    assert not (auth_dir / "nonzero@example_com.json").exists()
    assert job["result"]["errors"][0]["account_deleted"] is True
    assert "已从账号池删除" in job["result"]["errors"][0]["error"]


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


def test_payment_submit_request_accepts_legacy_payload_shapes():
    request = brazil_pix.BrazilPixPaymentSubmitRequest.model_validate(
        {
            "CDK": {"value": " PIX-LEGACY "},
            "paymentLink": {"url": " https://payments.stripe.com/qr/instructions/legacy "},
        }
    )

    assert request.cdk == "PIX-LEGACY"
    assert request.link == "https://payments.stripe.com/qr/instructions/legacy"


def test_payment_submit_bad_body_returns_400_not_validation_422(monkeypatch):
    def should_not_post(*args, **kwargs):
        raise AssertionError("empty payment submit body should not call PIX CDK API")

    monkeypatch.setattr(brazil_pix.requests, "post", should_not_post)

    endpoint = _route_endpoint("/api/brazil-pix/payment/submit", "POST")
    with pytest.raises(HTTPException) as exc:
        endpoint(None)

    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "bad_body"


def test_payment_submit_returns_upstream_rejection_as_data(monkeypatch):
    def fake_post(url, **kwargs):
        return _FakeResponse(
            422,
            {
                "ok": False,
                "code": "invalid_link",
                "message": "不是受支持的 Stripe PIX 链接",
            },
        )

    monkeypatch.setattr(brazil_pix.requests, "post", fake_post)

    endpoint = _route_endpoint("/api/brazil-pix/payment/submit", "POST")
    data = endpoint(brazil_pix.BrazilPixPaymentSubmitRequest(cdk="PIX-1", link="https://payments.stripe.com/qr/instructions/bad"))

    assert data == {
        "ok": False,
        "code": "invalid_link",
        "message": "不是受支持的 Stripe PIX 链接",
        "http_status": 422,
    }


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


def test_delete_pix_account_removes_dashboard_account_session_and_pix_artifacts(monkeypatch, tmp_path):
    auth_dir = _isolate_files(monkeypatch, tmp_path)
    email = "delete-me@example.com"
    _write_session(auth_dir, email, "delete-token-" + "x" * 80)
    brazil_pix.account_store.save_accounts(
        [
            {"email": email, "status": "active", "account_type": "free"},
            {"email": "keep@example.com", "status": "active", "account_type": "free"},
        ]
    )
    brazil_pix.LINKS_FILE.write_text(
        json.dumps(
            [
                {"id": "remove", "account_email": email, "hosted_instructions_url": "https://pay/remove"},
                {"id": "keep", "account_email": "keep@example.com", "hosted_instructions_url": "https://pay/keep"},
            ]
        ),
        encoding="utf-8",
    )
    brazil_pix.ACCOUNT_STATUS_FILE.write_text(
        json.dumps({email: {"status": "failed", "error": "boom"}, "keep@example.com": {"status": "success"}}),
        encoding="utf-8",
    )

    endpoint = _route_endpoint("/api/brazil-pix/accounts/{email}", "DELETE")
    data = endpoint(email)

    assert data["ok"] is True
    assert data["email"] == email
    assert data["dashboard_account_deleted"] is True
    assert data["auth_session_deleted"] is True
    assert data["pix"]["links_deleted"] == 1
    assert data["pix"]["status_deleted"] is True
    assert brazil_pix.account_store.find_account(brazil_pix.account_store.load_accounts(), email) is None
    assert brazil_pix.account_store.find_account(brazil_pix.account_store.load_accounts(), "keep@example.com") is not None
    assert not (auth_dir / "delete-me@example_com.json").exists()
    links = brazil_pix._load_links()
    assert [item["id"] for item in links] == ["keep"]
    statuses = json.loads(brazil_pix.ACCOUNT_STATUS_FILE.read_text(encoding="utf-8"))
    assert email not in statuses
    assert "keep@example.com" in statuses


def test_delete_pix_accounts_batch_removes_each_account_and_keeps_others(monkeypatch, tmp_path):
    auth_dir = _isolate_files(monkeypatch, tmp_path)
    remove_emails = ["remove-a@example.com", "remove-b@example.com"]
    keep_email = "keep@example.com"
    for email in [*remove_emails, keep_email]:
        _write_session(auth_dir, email, f"token-{email}-" + "x" * 80)
    brazil_pix.account_store.save_accounts(
        [{"email": email, "status": "active", "account_type": "free"} for email in [*remove_emails, keep_email]]
    )
    brazil_pix.LINKS_FILE.write_text(
        json.dumps(
            [
                {"id": "remove-a", "account_email": remove_emails[0], "hosted_instructions_url": "https://pay/remove-a"},
                {"id": "remove-b", "account_email": remove_emails[1], "hosted_instructions_url": "https://pay/remove-b"},
                {"id": "keep", "account_email": keep_email, "hosted_instructions_url": "https://pay/keep"},
            ]
        ),
        encoding="utf-8",
    )
    brazil_pix.ACCOUNT_STATUS_FILE.write_text(
        json.dumps({email: {"status": "failed"} for email in [*remove_emails, keep_email]}),
        encoding="utf-8",
    )

    endpoint = _route_endpoint("/api/brazil-pix/accounts/delete", "POST")
    data = endpoint(brazil_pix.BrazilPixDeleteAccountsRequest(emails=[*remove_emails, remove_emails[0], ""]))

    assert data["ok"] is True
    assert data["deleted"] == 2
    assert [item["email"] for item in data["results"]] == remove_emails
    assert all(item["dashboard_account_deleted"] for item in data["results"])
    assert all(item["auth_session_deleted"] for item in data["results"])
    assert [item["pix"]["links_deleted"] for item in data["results"]] == [1, 1]
    remaining_accounts = {item["email"] for item in brazil_pix.account_store.load_accounts()}
    assert remaining_accounts == {keep_email}
    assert [item["id"] for item in brazil_pix._load_links()] == ["keep"]
    statuses = json.loads(brazil_pix.ACCOUNT_STATUS_FILE.read_text(encoding="utf-8"))
    assert set(statuses) == {keep_email}
    for email in remove_emails:
        assert not (auth_dir / f"{email.replace('.', '_')}.json").exists()


def test_temp_batch_job_uses_olimap_cdk_api_and_saves_link(monkeypatch, tmp_path):
    auth_dir = _isolate_files(monkeypatch, tmp_path)
    _write_session(auth_dir, "temp@example.com", "temp-token-" + "x" * 80)
    brazil_pix.account_store.save_accounts([{"email": "temp@example.com", "status": "active", "account_type": "free"}])
    brazil_pix.JOBS.clear()
    job_id = "temp-job"
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
        "cancel_requested": False,
        "running_count": 0,
        "skipped": [],
        "account_statuses": {},
        "temp": True,
    }
    calls = []

    def fake_post(url, **kwargs):
        calls.append(("post", url, kwargs))
        return _FakeResponse(202, {"job_id": "remote-1", "job_token": "remote-token"})

    def fake_get(url, **kwargs):
        calls.append(("get", url, kwargs))
        return _FakeResponse(
            200,
            {
                "job": {
                    "job_id": "remote-1",
                    "status": "success",
                    "result": {
                        "pix_hosted_instructions_url": "https://payments.stripe.com/qr/instructions/temp",
                        "pix_copy_paste": "pix-temp-code",
                        "pix_image_url_png": "https://pay.example/qr.png",
                        "amount": "0",
                    },
                }
            },
        )

    monkeypatch.setattr(brazil_pix.requests, "post", fake_post)
    monkeypatch.setattr(brazil_pix.requests, "get", fake_get)

    req = brazil_pix.BrazilPixTempBatchStartRequest.model_validate(
        {"accountEmails": ["temp@example.com"], "cdk": "CDK-TEMP", "concurrency": 1}
    )
    brazil_pix._run_temp_batch_job(job_id, req)

    assert calls[0][0] == "post"
    assert calls[0][1] == "https://pix.olimap.top/api/v1/jobs"
    assert calls[0][2]["json"]["cdk"] == "CDK-TEMP"
    assert calls[0][2]["json"]["credential"] == "temp-token-" + "x" * 80
    assert calls[1][0] == "get"
    assert calls[1][1] == "https://pix.olimap.top/api/v1/jobs/remote-1"
    assert calls[1][2]["headers"]["Authorization"] == "Bearer remote-token"
    job = brazil_pix.JOBS[job_id]
    assert job["status"] == "success"
    assert job["result"]["successes"][0]["email"] == "temp@example.com"
    links = brazil_pix._load_links()
    assert links[0]["account_email"] == "temp@example.com"
    assert links[0]["hosted_instructions_url"] == "https://payments.stripe.com/qr/instructions/temp"
    assert links[0]["pix_copy_paste"] == "pix-temp-code"
    assert links[0]["image_url_png"] == "https://pay.example/qr.png"


def test_temp_batch_job_distributes_multiple_cdks_across_accounts(monkeypatch, tmp_path):
    auth_dir = _isolate_files(monkeypatch, tmp_path)
    emails = [f"multi{index}@example.com" for index in range(3)]
    for index, email in enumerate(emails):
        _write_session(auth_dir, email, f"multi-token-{index}-" + "x" * 80)
    brazil_pix.account_store.save_accounts([{"email": email, "status": "active", "account_type": "free"} for email in emails])
    brazil_pix.JOBS.clear()
    job_id = "temp-multi-cdk-job"
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
        "cancel_requested": False,
        "running_count": 0,
        "skipped": [],
        "account_statuses": {},
        "temp": True,
    }
    posted_cdks = []

    def fake_post(url, **kwargs):
        if url.endswith("/cdk/status"):
            return _FakeResponse(200, {"ok": True, "cdk": {"valid": True, "balance": 1}})
        cdk = kwargs["json"]["cdk"]
        posted_cdks.append(cdk)
        return _FakeResponse(
            202,
            {
                "job_id": f"remote-{len(posted_cdks)}",
                "job_token": "remote-token",
                "status": "success",
                "link": f"https://payments.stripe.com/qr/instructions/{cdk}",
                "pix_copy_paste": f"pix-{cdk}",
                "amount": "0",
            },
        )

    monkeypatch.setattr(brazil_pix.requests, "post", fake_post)

    req = brazil_pix.BrazilPixTempBatchStartRequest.model_validate(
        {"accountEmails": emails, "cdks": ["CDK-1", "CDK-2", "CDK-3"], "concurrency": 1}
    )
    brazil_pix._run_temp_batch_job(job_id, req)

    assert posted_cdks == ["CDK-1", "CDK-2", "CDK-3"]
    assert brazil_pix.JOBS[job_id]["status"] == "success"
    assert len(brazil_pix.JOBS[job_id]["result"]["successes"]) == 3


def test_temp_batch_job_allocates_multiple_cdks_by_balance(monkeypatch, tmp_path):
    auth_dir = _isolate_files(monkeypatch, tmp_path)
    emails = [f"quota{index}@example.com" for index in range(4)]
    for index, email in enumerate(emails):
        _write_session(auth_dir, email, f"quota-token-{index}-" + "x" * 80)
    brazil_pix.account_store.save_accounts([{"email": email, "status": "active", "account_type": "free"} for email in emails])
    brazil_pix.JOBS.clear()
    job_id = "temp-cdk-balance-job"
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
        "cancel_requested": False,
        "running_count": 0,
        "skipped": [],
        "account_statuses": {},
        "temp": True,
    }
    balances = {"CDK-A": 3, "CDK-B": 1}
    posted_cdks = []

    def fake_post(url, **kwargs):
        if url.endswith("/cdk/status"):
            cdk = kwargs["json"]["cdk"]
            return _FakeResponse(200, {"ok": True, "cdk": {"valid": True, "balance": balances[cdk]}})
        cdk = kwargs["json"]["cdk"]
        posted_cdks.append(cdk)
        return _FakeResponse(
            202,
            {
                "job_id": f"remote-{len(posted_cdks)}",
                "job_token": "remote-token",
                "status": "success",
                "link": f"https://payments.stripe.com/qr/instructions/{cdk}-{len(posted_cdks)}",
                "pix_copy_paste": f"pix-{cdk}",
                "amount": "0",
            },
        )

    monkeypatch.setattr(brazil_pix.requests, "post", fake_post)

    req = brazil_pix.BrazilPixTempBatchStartRequest.model_validate(
        {"accountEmails": emails, "cdks": ["CDK-A", "CDK-B"], "concurrency": 1}
    )
    brazil_pix._run_temp_batch_job(job_id, req)

    assert posted_cdks == ["CDK-A", "CDK-A", "CDK-A", "CDK-B"]
    assert brazil_pix.JOBS[job_id]["status"] == "success"
    assert len(brazil_pix.JOBS[job_id]["result"]["successes"]) == 4


def test_temp_cdk_assignments_stop_balance_checks_once_enough_quota(monkeypatch):
    checked_cdks = []

    def fake_balance(cdk):
        checked_cdks.append(cdk)
        return {"CDK-A": 3, "CDK-B": 2, "CDK-C": 99}[cdk]

    monkeypatch.setattr(brazil_pix, "_temp_cdk_balance", fake_balance)

    assignments = brazil_pix._temp_cdk_assignments(["CDK-A", "CDK-B", "CDK-C"], 4)

    assert assignments == ["CDK-A", "CDK-A", "CDK-A", "CDK-B"]
    assert checked_cdks == ["CDK-A", "CDK-B"]


def test_temp_cdk_balance_treats_api_ok_false_as_zero():
    assert brazil_pix._temp_cdk_balance_from_status({"ok": False, "message": "invalid cdk"}) == 0


def test_temp_cdk_status_proxies_olimap_balance_api(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return _FakeResponse(
            200,
            {
                "ok": True,
                "cdk": {
                    "valid": True,
                    "state": "active",
                    "balance": 7,
                    "quota_total": 10,
                    "used_success": 2,
                    "reserved": 1,
                    "active_jobs": 1,
                    "max_concurrency": 10,
                },
            },
        )

    monkeypatch.setattr(brazil_pix.requests, "post", fake_post)

    endpoint = _route_endpoint("/api/brazil-pix/temp/cdk/status", "POST")
    data = endpoint(brazil_pix.BrazilPixTempCdkStatusRequest(cdk="CDK-TEMP"))

    assert calls[0][0] == "https://pix.olimap.top/api/v1/cdk/status"
    assert calls[0][1]["json"] == {"cdk": "CDK-TEMP"}
    assert calls[0][1]["timeout"] == 20
    assert data["cdk"]["balance"] == 7
    assert data["cdk"]["max_concurrency"] == 10


def test_temp_cdk_status_uses_short_ttl_cache(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return _FakeResponse(200, {"ok": True, "cdk": {"valid": True, "balance": 9}})

    monkeypatch.setattr(brazil_pix.requests, "post", fake_post)

    endpoint = _route_endpoint("/api/brazil-pix/temp/cdk/status", "POST")
    first = endpoint(brazil_pix.BrazilPixTempCdkStatusRequest(cdk="CDK-CACHED"))
    second = endpoint(brazil_pix.BrazilPixTempCdkStatusRequest(cdk="CDK-CACHED"))

    assert first["cdk"]["balance"] == 9
    assert second["cdk"]["balance"] == 9
    assert len(calls) == 1


def test_temp_cdk_status_returns_cached_value_when_upstream_rate_limited(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        if len(calls) == 1:
            return _FakeResponse(200, {"ok": True, "cdk": {"valid": True, "balance": 5}})
        return _FakeResponse(429, {"ok": False, "message": "Too Many Requests"})

    monkeypatch.setattr(brazil_pix.requests, "post", fake_post)
    endpoint = _route_endpoint("/api/brazil-pix/temp/cdk/status", "POST")

    first = endpoint(brazil_pix.BrazilPixTempCdkStatusRequest(cdk="CDK-RATE"))
    second = endpoint(brazil_pix.BrazilPixTempCdkStatusRequest(cdk="CDK-RATE", force=True))

    assert first["cdk"]["balance"] == 5
    assert second["cdk"]["balance"] == 5
    assert second["cached"] is True
    assert second["stale"] is True
    assert len(calls) == 2


def test_temp_batch_job_allows_concurrency_above_ten(monkeypatch, tmp_path):
    auth_dir = _isolate_files(monkeypatch, tmp_path)
    emails = [f"temp{index}@example.com" for index in range(12)]
    for index, email in enumerate(emails):
        _write_session(auth_dir, email, f"temp-token-{index}-" + "x" * 80)
    brazil_pix.account_store.save_accounts([{"email": email, "status": "active", "account_type": "free"} for email in emails])
    brazil_pix.JOBS.clear()
    job_id = "temp-concurrency-job"
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
        "concurrency": 12,
        "cancel_requested": False,
        "running_count": 0,
        "skipped": [],
        "account_statuses": {},
        "temp": True,
    }
    lock = threading.Lock()
    active = 0
    max_active = 0
    above_ten = threading.Event()

    def fake_post(url, **kwargs):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
            if active > 10:
                above_ten.set()
        above_ten.wait(0.25)
        with lock:
            active -= 1
        remote_id = str(kwargs["json"]["credential"]).split("-")[2]
        return _FakeResponse(
            202,
            {
                "job_id": f"remote-{remote_id}",
                "job_token": "remote-token",
                "status": "success",
                "link": f"https://payments.stripe.com/qr/instructions/{remote_id}",
                "pix_copy_paste": "pix-temp-code",
                "amount": "0",
            },
        )

    monkeypatch.setattr(brazil_pix.requests, "post", fake_post)

    req = brazil_pix.BrazilPixTempBatchStartRequest.model_validate(
        {"accountEmails": emails, "cdk": "CDK-TEMP", "concurrency": 12}
    )
    brazil_pix._run_temp_batch_job(job_id, req)

    job = brazil_pix.JOBS[job_id]
    assert job["status"] == "success"
    assert job["concurrency"] == 12
    assert len(job["result"]["successes"]) == 12
    assert max_active > 10


def test_temp_batch_job_keeps_requested_concurrency_when_cdk_reports_one_slot(monkeypatch, tmp_path):
    auth_dir = _isolate_files(monkeypatch, tmp_path)
    emails = [f"slot{index}@example.com" for index in range(10)]
    for index, email in enumerate(emails):
        _write_session(auth_dir, email, f"slot-token-{index}-" + "x" * 80)
    brazil_pix.account_store.save_accounts([{"email": email, "status": "active", "account_type": "free"} for email in emails])
    brazil_pix.JOBS.clear()
    job_id = "temp-keep-concurrency-job"
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
        "concurrency": 10,
        "cancel_requested": False,
        "running_count": 0,
        "skipped": [],
        "account_statuses": {},
        "temp": True,
    }

    def fake_post(url, **kwargs):
        if url.endswith("/cdk/status"):
            return _FakeResponse(200, {"ok": True, "cdk": {"valid": True, "balance": 10, "max_concurrency": 1}})
        remote_id = str(kwargs["json"]["credential"]).split("-")[2]
        return _FakeResponse(
            202,
            {
                "job_id": f"remote-{remote_id}",
                "job_token": "remote-token",
                "status": "success",
                "link": f"https://payments.stripe.com/qr/instructions/{remote_id}",
                "pix_copy_paste": "pix-temp-code",
                "amount": "0",
            },
        )

    monkeypatch.setattr(brazil_pix.requests, "post", fake_post)

    req = brazil_pix.BrazilPixTempBatchStartRequest.model_validate(
        {"accountEmails": emails, "cdk": "CDK-ONE-SLOT", "concurrency": 10}
    )
    brazil_pix._run_temp_batch_job(job_id, req)

    job = brazil_pix.JOBS[job_id]
    assert job["status"] == "success"
    assert job["concurrency"] == 10
    assert len(job["result"]["successes"]) == 10


def test_mark_account_plus_pix_sets_dashboard_plus_snapshot(monkeypatch):
    captured = {}
    monkeypatch.setattr(brazil_pix.account_store, "ensure_session_only_account", lambda email: captured.setdefault("ensured", email))

    def fake_update_account(email, **payload):
        captured["email"] = email
        captured["payload"] = payload
        return {"email": email, **payload}

    monkeypatch.setattr(brazil_pix.account_store, "update_account", fake_update_account)

    updated = brazil_pix._mark_account_plus_pix("paid@example.com", "paid ok")

    assert captured["ensured"] == "paid@example.com"
    assert updated["account_type"] == brazil_pix.account_store.ACCOUNT_TYPE_PLUS
    assert updated["last_bind_provider"] == "pix"
    assert updated["last_bind_status"] == "success"
    assert updated["last_quota"]["plan_type"] == "plus"
