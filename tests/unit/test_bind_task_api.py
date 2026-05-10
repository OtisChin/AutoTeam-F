import base64
import json
import threading
from pathlib import Path

import pytest

from autoteam import api
from autoteam import accounts as accounts_module
from autoteam import gopay_executor


def test_remove_pool_accounts_persists_delete_audit(monkeypatch):
    audit_dir = Path(".pytest_tmp")
    audit_dir.mkdir(exist_ok=True)
    audit_path = audit_dir / "account_delete_audit.jsonl"
    if audit_path.exists():
        audit_path.unlink()
    account = {
        "email": "dead@example.com",
        "status": "active",
        "account_type": "plus",
        "cloudmail_account_id": "tok_dead",
        "mail_provider": "luckmail",
        "last_bind_task_id": "task-1",
    }

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autoteam.accounts.delete_account", lambda email: email == "dead@example.com")
    monkeypatch.setattr("autoteam.auth_session_store.delete_auth_session", lambda email: email == "dead@example.com")
    monkeypatch.setattr(api, "_account_delete_audit_path", lambda: audit_path)
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)

    removed = api._remove_pool_accounts_from_local_and_mail(
        ["dead@example.com"],
        log_context="oauth-account-deactivated",
        reason="oauth_account_deactivated",
    )

    assert removed == ["dead@example.com"]
    rows = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["email"] == "dead@example.com"
    assert rows[0]["source"] == "oauth-account-deactivated"
    assert rows[0]["reason"] == "oauth_account_deactivated"
    assert rows[0]["record_deleted"] is True
    assert rows[0]["auth_session_deleted"] is True
    assert rows[0]["cloudmail_account_id_present"] is True
    assert rows[0]["last_bind_task_id"] == "task-1"


class FakeUnlockedLock:
    def acquire(self, blocking=False):
        return False

    def release(self):
        raise AssertionError("release should not be called when acquire returns False")


def test_delete_accounts_batch_cleans_auth_session_only_accounts(monkeypatch):
    captured = {"deleted_sessions": [], "managed": []}

    monkeypatch.setattr(api, "_playwright_lock", FakeUnlockedLock())
    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: [])
    monkeypatch.setattr(
        "autoteam.auth_session_store.get_auth_session_file",
        lambda email: "data/auth_session/ghost@example_com.json" if email == "ghost@example.com" else "",
    )
    monkeypatch.setattr(
        "autoteam.auth_session_store.delete_auth_session",
        lambda email: captured["deleted_sessions"].append(email) or True,
    )

    def fake_delete_managed_account(email, **kwargs):
        captured["managed"].append((email, kwargs))
        return {"local_record": False, "local_auth_files": [], "cpa_files": []}

    monkeypatch.setattr("autoteam.account_ops.delete_managed_account", fake_delete_managed_account)

    result = api.delete_accounts_batch(api.DeleteBatchParams(emails=["ghost@example.com"], continue_on_error=True))

    assert result["summary"]["ok"] == 1
    assert result["results"][0]["ok"] is True
    assert result["results"][0]["cleanup"]["auth_session_deleted"] is True
    assert captured["deleted_sessions"] == ["ghost@example.com"]
    assert captured["managed"][0][0] == "ghost@example.com"


def test_delete_accounts_batch_reports_missing_only_when_no_record_or_session(monkeypatch):
    monkeypatch.setattr(api, "_playwright_lock", FakeUnlockedLock())
    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: [])
    monkeypatch.setattr("autoteam.auth_session_store.get_auth_session_file", lambda _email: "")

    result = api.delete_accounts_batch(api.DeleteBatchParams(emails=["missing@example.com"], continue_on_error=True))

    assert result["summary"]["ok"] == 0
    assert result["results"] == [{"email": "missing@example.com", "ok": False, "error": "账号不存在"}]


def test_post_bind_card_task_starts_background_task(monkeypatch):
    captured = {}

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr("autoteam.accounts.find_account", lambda accounts, email: accounts[0] if email == "user@example.com" else None)
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr("autoteam.card_pool.find_item", lambda pool_type, item_id: {"id": item_id, "status": "unused"})

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["command"] = command
        captured["func"] = func
        captured["params"] = params
        return {"task_id": "task-123", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    result = api.post_bind_card_task(
        api.BindCardTaskParams(
            email="user@example.com",
            card_item_id="card-1",
            checkout_url="https://chatgpt.com/checkout/demo",
            proxy_url="socks5://host:1080",
            proxy_label="res-us-01",
            manual_confirm=True,
        )
    )

    assert result["task_id"] == "task-123"
    assert captured["command"] == "bind-card"
    assert captured["params"] == {
        "email": "user@example.com",
        "card_item_id": "card-1",
        "checkout_url": "https://chatgpt.com/checkout/demo",
        "proxy_url": "socks5://host:1080",
        "proxy_label": "res-us-01",
        "proxy_bypass": None,
        "manual_confirm": True,
        "timeout_seconds": 900,
    }


def test_post_bind_card_task_requires_existing_account(monkeypatch):
    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: [])
    monkeypatch.setattr("autoteam.accounts.find_account", lambda accounts, email: None)

    with pytest.raises(api.HTTPException) as exc:
        api.post_bind_card_task(
            api.BindCardTaskParams(
                email="missing@example.com",
                card_item_id="card-1",
                checkout_url="https://chatgpt.com/checkout/demo",
            )
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "账号不存在"


def test_post_bind_card_task_rejects_unavailable_card(monkeypatch):
    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr("autoteam.accounts.find_account", lambda accounts, email: accounts[0])
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr("autoteam.card_pool.find_item", lambda pool_type, item_id: {"id": item_id, "status": "binding"})

    with pytest.raises(api.HTTPException) as exc:
        api.post_bind_card_task(
            api.BindCardTaskParams(
                email="user@example.com",
                card_item_id="card-1",
                checkout_url="https://chatgpt.com/checkout/demo",
            )
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "卡当前状态为 binding，不可用于绑卡"


def test_post_gopay_bind_task_starts_background_task(monkeypatch):
    captured = {}

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr("autoteam.accounts.find_account", lambda accounts, email: accounts[0] if email == "user@example.com" else None)
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["command"] = command
        captured["params"] = params
        return {"task_id": "task-456", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    result = api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="user@example.com",
            phone_number="+6287761973970",
            country_code="62",
            sms_url="https://it.tgflare.com/api/record?token=demo",
            gopay_pin="558023",
            checkout_ui_mode="hosted",
            pending_retry_attempts=5,
            billing_name="John Smith",
            billing_country="US",
            billing_state="MI",
            billing_city="MUSKEGON",
            billing_zip="49442",
            billing_address1="570 MARGARET ST",
        )
    )

    assert result["task_id"] == "task-456"
    assert captured["command"] == "gopay-bind"
    assert captured["params"]["email"] == "user@example.com"
    assert captured["params"]["country_code"] == "62"
    assert captured["params"]["phone_number"] == "+6287761973970"
    assert captured["params"]["checkout_ui_mode"] == "hosted"
    assert captured["params"]["pending_retry_attempts"] == 3


def test_post_gopay_bind_task_accepts_batch_accounts(monkeypatch):
    captured = {}
    accounts = [{"email": "user@example.com"}, {"email": "backup@example.com"}]

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autoteam.accounts.find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["params"] = params
        return {"task_id": "task-457", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    result = api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="user@example.com",
            account_emails=["user@example.com", "backup@example.com"],
            phone_number="+6287761973970",
            sms_url="https://it.tgflare.com/api/record?token=demo",
            gopay_pin="558023",
        )
    )

    assert result["task_id"] == "task-457"
    assert captured["params"]["account_emails"] == ["user@example.com", "backup@example.com"]


def test_gopay_task_runner_auto_registers_then_binds(monkeypatch):
    captured = {"mail_login": 0}

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: [{"email": "new@example.com"}])
    monkeypatch.setattr("autoteam.accounts.find_account", lambda accounts, email: accounts[0] if email == "new@example.com" else None)
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/new@example.com.json")
    monkeypatch.setattr("autoteam.auth_session_store.get_auth_session_file", lambda email: f"data/auth_session/{email}.json")
    monkeypatch.setattr("autoteam.runtime_config.get_register_domain", lambda: "openaibus.com")
    monkeypatch.setattr("autoteam.runtime_config.get_register_domains", lambda: ["openaibus.com", "rexmoxe.space"])
    monkeypatch.setattr("autoteam.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))
    monkeypatch.setattr("autoteam.accounts.update_account", lambda email, **kwargs: captured.setdefault("updates", []).append((email, kwargs)))
    monkeypatch.setattr(api, "_gopay_auto_register_bind_delay_seconds", lambda: 0)
    monkeypatch.setattr("autoteam.manager.time.sleep", lambda _seconds: None)

    class FakeMailClient:
        def login(self):
            captured["mail_login"] += 1

        def create_temp_email(self, *args, **kwargs):
            attempts = captured.setdefault("mail_probe_attempts", 0) + 1
            captured["mail_probe_attempts"] = attempts
            if attempts == 1:
                raise Exception("身份认证失效,请重新登录")
            return (949, "new@example.com")

    monkeypatch.setattr("autoteam.mail.TemporaryEmailClient", FakeMailClient)

    def fake_register(mail_client, **kwargs):
        captured["register_kwargs"] = kwargs
        mail_client.create_temp_email()
        return {"email": "new@example.com", "status": "success", "auth_file": "data/auth_session/new@example.com.json"}

    monkeypatch.setattr("autoteam.manager.create_account_direct", fake_register)

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "email_used": "new@example.com",
        }

    monkeypatch.setattr("autoteam.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["params"] = params
        captured["func"] = func
        return {"task_id": "task-auto", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    result = api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="",
            auto_register=True,
            auto_register_domains=["rexmoxe.space"],
            auto_register_prefix="gopay",
            auto_register_password="Password123!",
            phone_number="+6287761973970",
            country_code="62",
            sms_url="https://it.tgflare.com/api/record?token=demo",
            gopay_pin="558023",
        )
    )

    assert result["task_id"] == "task-auto"
    assert captured["params"]["auto_register"] is True
    assert captured["params"]["auto_register_count"] == 1
    assert captured["params"]["auto_register_domains"] == ["rexmoxe.space"]
    assert captured["params"]["auto_register_prefix"] == "gopay"
    assert captured["params"]["auto_register_password_present"] is True
    assert "auto_register_password" not in captured["params"]

    task_result = captured["func"]()

    assert captured["mail_login"] == 2
    assert captured["mail_probe_attempts"] == 2
    assert captured["register_kwargs"]["domain"] == "rexmoxe.space"
    assert captured["register_kwargs"]["email_prefix"] == "gopay"
    assert captured["register_kwargs"]["password"] == "Password123!"
    assert captured["register_kwargs"]["skip_post_register"] is True
    assert captured["register_kwargs"]["post_register_oauth"] is False
    assert captured["register_kwargs"]["check_team_membership"] is False
    assert captured["run_kwargs"]["email"] == "new@example.com"
    assert captured["run_kwargs"]["account_emails"] == []
    assert task_result["status"] == "success"
    assert task_result["email"] == "new@example.com"
    assert captured["audit"]["email"] == "new@example.com"


def test_gopay_task_runner_auto_register_count_registers_and_binds_sequentially(monkeypatch):
    captured = {"mail_login": 0, "register_kwargs": [], "run_emails": [], "run_phone_numbers": []}
    registered_emails = ["new1@example.com", "new2@example.com"]

    def fake_load_accounts():
        return [{"email": email} for email in registered_emails]

    def fake_find_account(accounts, email):
        return next((account for account in accounts if account.get("email") == email), None)

    monkeypatch.setattr("autoteam.accounts.load_accounts", fake_load_accounts)
    monkeypatch.setattr("autoteam.accounts.find_account", fake_find_account)
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda acc: f"data/auth_session/{acc['email']}.json")
    monkeypatch.setattr("autoteam.auth_session_store.get_auth_session_file", lambda email: f"data/auth_session/{email}.json")
    monkeypatch.setattr("autoteam.runtime_config.get_register_domain", lambda: "openaibus.com")
    monkeypatch.setattr("autoteam.runtime_config.get_register_domains", lambda: ["openaibus.com"])
    monkeypatch.setattr("autoteam.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))
    monkeypatch.setattr("autoteam.accounts.update_account", lambda email, **kwargs: captured.setdefault("updates", []).append((email, kwargs)))
    monkeypatch.setattr(api, "_gopay_auto_register_bind_delay_seconds", lambda: 0)

    class FakeMailClient:
        def login(self):
            captured["mail_login"] += 1

    monkeypatch.setattr("autoteam.mail.TemporaryEmailClient", FakeMailClient)

    def fake_register(mail_client, **kwargs):
        index = len(captured["register_kwargs"])
        captured["register_kwargs"].append(kwargs)
        return {"email": registered_emails[index], "status": "success"}

    monkeypatch.setattr("autoteam.manager.create_account_direct", fake_register)

    def fake_run_gopay_bind_task(**kwargs):
        email = kwargs["email"]
        captured["run_emails"].append(email)
        captured["run_phone_numbers"].append(kwargs["phone_number"])
        return {
            "status": "success",
            "message": f"GoPay 绑定完成: {email}",
            "email_used": email,
        }

    monkeypatch.setattr("autoteam.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["params"] = params
        captured["func"] = func
        return {"task_id": "task-auto-count", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    result = api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="",
            auto_register=True,
            auto_register_count=2,
            phone_accounts=[
                {
                    "country_code": "62",
                    "phone_number": "+628111111111",
                    "sms_url": "https://it.tgflare.com/api/record?token=one",
                    "gopay_pin": "111111",
                },
                {
                    "country_code": "62",
                    "phone_number": "+628222222222",
                    "sms_url": "https://it.tgflare.com/api/record?token=two",
                    "gopay_pin": "222222",
                },
            ],
        )
    )

    assert result["task_id"] == "task-auto-count"
    assert captured["params"]["auto_register_count"] == 2

    task_result = captured["func"]()

    assert captured["mail_login"] == 2
    assert len(captured["register_kwargs"]) == 2
    assert all(kwargs["domain"] == "openaibus.com" for kwargs in captured["register_kwargs"])
    assert captured["run_emails"] == registered_emails
    assert captured["run_phone_numbers"] == ["+628111111111", "+628222222222"]
    assert task_result["status"] == "success"
    assert task_result["successful_emails"] == registered_emails
    assert task_result["auto_register_count"] == 2
    assert task_result["auto_register_attempted"] == 2
    assert "成功 2/2" in task_result["message"]
    updated_emails = [email for email, _kwargs in captured["updates"]]
    assert updated_emails == registered_emails


def test_gopay_task_runner_auto_register_retries_pending_after_first_round(monkeypatch):
    captured = {"mail_login": 0, "progress": [], "run_emails": [], "slept": []}
    registered_emails = ["new1@example.com", "new2@example.com"]

    def fake_load_accounts():
        return [{"email": email} for email in registered_emails]

    def fake_find_account(accounts, email):
        return next((account for account in accounts if account.get("email") == email), None)

    monkeypatch.setattr("autoteam.accounts.load_accounts", fake_load_accounts)
    monkeypatch.setattr("autoteam.accounts.find_account", fake_find_account)
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda acc: f"data/auth_session/{acc['email']}.json")
    monkeypatch.setattr("autoteam.auth_session_store.get_auth_session_file", lambda email: f"data/auth_session/{email}.json")
    monkeypatch.setattr("autoteam.runtime_config.get_register_domain", lambda: "openaibus.com")
    monkeypatch.setattr("autoteam.runtime_config.get_register_domains", lambda: ["openaibus.com"])
    monkeypatch.setattr("autoteam.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))
    monkeypatch.setattr("autoteam.accounts.update_account", lambda email, **kwargs: captured.setdefault("updates", []).append((email, kwargs)))
    monkeypatch.setattr(api, "_gopay_auto_register_bind_delay_seconds", lambda: 0)
    monkeypatch.setattr(api.time, "sleep", lambda seconds: captured["slept"].append(seconds))
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))

    class FakeMailClient:
        def login(self):
            captured["mail_login"] += 1

    monkeypatch.setattr("autoteam.mail.TemporaryEmailClient", FakeMailClient)

    def fake_register(_mail_client, **_kwargs):
        return {"email": registered_emails[captured["mail_login"] - 1], "status": "success"}

    monkeypatch.setattr("autoteam.manager.create_account_direct", fake_register)

    def fake_run_gopay_bind_task(**kwargs):
        email = kwargs["email"]
        captured["run_emails"].append(email)
        if email == "new1@example.com" and captured["run_emails"].count(email) == 1:
            return {
                "status": "failed",
                "failure_stage": "midtrans_linking",
                "message": "Midtrans linking 失败: HTTP 429",
                "email_used": email,
            }
        return {
            "status": "success",
            "message": f"GoPay 绑定完成: {email}",
            "email_used": email,
        }

    monkeypatch.setattr("autoteam.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: captured.update({"func": func, "params": params}) or {"task_id": "task-auto-retry", "command": command, "params": params},
    )

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="",
            auto_register=True,
            auto_register_count=2,
            pending_retry_attempts=1,
            phone_number="+6287761973970",
            country_code="62",
            sms_url="https://it.tgflare.com/api/record?token=demo",
            gopay_pin="558023",
        )
    )

    result = captured["func"]()

    assert captured["run_emails"] == ["new1@example.com", "new2@example.com", "new1@example.com"]
    assert result["status"] == "success"
    assert sorted(result["successful_emails"]) == registered_emails
    assert result["retried_emails"] == ["new1@example.com"]
    assert result["pending_retry_emails"] == []
    assert captured["slept"] == [60.0]
    assert any(progress["stage"] == "gopay_pending_retry_queued" for progress in captured["progress"])
    retry_events = [progress for progress in captured["progress"] if progress["stage"] == "gopay_pending_retry_account"]
    assert retry_events and retry_events[0]["retry_round"] == 1


def test_gopay_task_runner_auto_register_retries_gopay_payment_process(monkeypatch):
    captured = {"mail_login": 0, "progress": [], "run_emails": [], "slept": []}

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: [{"email": "wallet@example.com"}])
    monkeypatch.setattr("autoteam.accounts.find_account", lambda accounts, email: accounts[0] if email == "wallet@example.com" else None)
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/wallet@example.com.json")
    monkeypatch.setattr("autoteam.auth_session_store.get_auth_session_file", lambda email: f"data/auth_session/{email}.json")
    monkeypatch.setattr("autoteam.runtime_config.get_register_domain", lambda: "openaibus.com")
    monkeypatch.setattr("autoteam.runtime_config.get_register_domains", lambda: ["openaibus.com"])
    monkeypatch.setattr("autoteam.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))
    monkeypatch.setattr("autoteam.accounts.update_account", lambda email, **kwargs: captured.setdefault("updates", []).append((email, kwargs)))
    monkeypatch.setattr(api, "_gopay_auto_register_bind_delay_seconds", lambda: 0)
    monkeypatch.setattr(api.time, "sleep", lambda seconds: captured["slept"].append(seconds))
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))

    class FakeMailClient:
        def login(self):
            captured["mail_login"] += 1

    monkeypatch.setattr("autoteam.mail.TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr(
        "autoteam.manager.create_account_direct",
        lambda _mail_client, **_kwargs: {"email": "wallet@example.com", "status": "success"},
    )

    def fake_run_gopay_bind_task(**kwargs):
        email = kwargs["email"]
        captured["run_emails"].append(email)
        if captured["run_emails"].count(email) == 1:
            return {
                "status": "failed",
                "failure_stage": "gopay_payment_process",
                "message": (
                    'gopay_payment_process 失败: HTTP 400 {"success":false,'
                    '"errors":[{"code":"201","cause":"createAuth call to payment-switch '
                    'failed for payment_method: GOPAY_WALLET"}]}'
                ),
                "email_used": email,
            }
        return {"status": "success", "message": f"GoPay 绑定完成: {email}", "email_used": email}

    monkeypatch.setattr("autoteam.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: captured.update({"func": func, "params": params}) or {"task_id": "task-auto-wallet-retry", "command": command, "params": params},
    )

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="",
            auto_register=True,
            auto_register_count=1,
            pending_retry_attempts=1,
            phone_number="+6287761973970",
            country_code="62",
            sms_url="https://it.tgflare.com/api/record?token=demo",
            gopay_pin="558023",
        )
    )

    result = captured["func"]()

    assert captured["run_emails"] == ["wallet@example.com", "wallet@example.com"]
    assert result["status"] == "success"
    assert result["successful_emails"] == ["wallet@example.com"]
    assert result["failed_emails"] == []
    assert result["bind_failed_emails"] == []
    assert result["retried_emails"] == ["wallet@example.com"]
    assert captured["slept"] == [60.0]
    queued = [progress for progress in captured["progress"] if progress["stage"] == "gopay_pending_retry_queued"]
    assert queued and queued[0]["reason"] == "gopay_payment_process"


def test_gopay_task_runner_auto_register_does_not_retry_checkout_not_approved(monkeypatch):
    captured = {"mail_login": 0, "progress": [], "run_emails": [], "slept": []}

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: [{"email": "declined@example.com"}])
    monkeypatch.setattr("autoteam.accounts.find_account", lambda accounts, email: accounts[0] if email == "declined@example.com" else None)
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/declined@example.com.json")
    monkeypatch.setattr("autoteam.auth_session_store.get_auth_session_file", lambda email: f"data/auth_session/{email}.json")
    monkeypatch.setattr("autoteam.runtime_config.get_register_domain", lambda: "openaibus.com")
    monkeypatch.setattr("autoteam.runtime_config.get_register_domains", lambda: ["openaibus.com"])
    monkeypatch.setattr("autoteam.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))
    monkeypatch.setattr("autoteam.accounts.update_account", lambda email, **kwargs: None)
    monkeypatch.setattr(api, "_gopay_auto_register_bind_delay_seconds", lambda: 0)
    monkeypatch.setattr(api.time, "sleep", lambda seconds: captured["slept"].append(seconds))
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))

    class FakeMailClient:
        def login(self):
            captured["mail_login"] += 1

    monkeypatch.setattr("autoteam.mail.TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr(
        "autoteam.manager.create_account_direct",
        lambda _mail_client, **_kwargs: {"email": "declined@example.com", "status": "success"},
    )
    monkeypatch.setattr(
        "autoteam.gopay_executor.run_gopay_bind_task",
        lambda **kwargs: captured["run_emails"].append(kwargs["email"]) or {
            "status": "failed",
            "failure_stage": "checkout_not_approved",
            "message": "付款未获批准",
            "email_used": kwargs["email"],
        },
    )
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: captured.update({"func": func, "params": params}) or {"task_id": "task-auto-declined", "command": command, "params": params},
    )

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="",
            auto_register=True,
            auto_register_count=1,
            pending_retry_attempts=1,
            phone_number="+6287761973970",
            country_code="62",
            sms_url="https://it.tgflare.com/api/record?token=demo",
            gopay_pin="558023",
        )
    )

    try:
        captured["func"]()
    except api.TaskResultError as exc:
        result = exc.task_result
    else:
        raise AssertionError("expected checkout_not_approved to fail without retry")

    assert captured["run_emails"] == ["declined@example.com"]
    assert result["status"] == "failed"
    assert result["failed_emails"][0]["email"] == "declined@example.com"
    assert result["retried_emails"] == []
    assert not any(progress["stage"] == "gopay_pending_retry_queued" for progress in captured["progress"])


def test_gopay_task_runner_auto_register_splits_register_success_from_bind_failure(monkeypatch):
    captured = {"mail_login": 0, "progress": [], "slept": []}

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: [{"email": "new@example.com"}])
    monkeypatch.setattr("autoteam.accounts.find_account", lambda accounts, email: accounts[0] if email == "new@example.com" else None)
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/new@example.com.json")
    monkeypatch.setattr("autoteam.auth_session_store.get_auth_session_file", lambda email: f"data/auth_session/{email}.json")
    monkeypatch.setattr("autoteam.runtime_config.get_register_domain", lambda: "openaibus.com")
    monkeypatch.setattr("autoteam.runtime_config.get_register_domains", lambda: ["openaibus.com"])
    monkeypatch.setattr("autoteam.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))
    monkeypatch.setattr("autoteam.accounts.update_account", lambda email, **kwargs: None)
    monkeypatch.setattr(api, "_gopay_auto_register_bind_delay_seconds", lambda: 12.5)
    monkeypatch.setattr(api.time, "sleep", lambda seconds: captured["slept"].append(seconds))
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))

    class FakeMailClient:
        def login(self):
            captured["mail_login"] += 1

    monkeypatch.setattr("autoteam.mail.TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr(
        "autoteam.manager.create_account_direct",
        lambda _mail_client, **_kwargs: {"email": "new@example.com", "status": "success"},
    )
    monkeypatch.setattr(
        "autoteam.gopay_executor.run_gopay_bind_task",
        lambda **_kwargs: {
            "status": "failed",
            "failure_stage": "chatgpt_approve",
            "message": "ChatGPT approve blocked",
            "email_used": "new@example.com",
        },
    )

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-auto-fail", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="",
            auto_register=True,
            auto_register_count=1,
            phone_number="+6287761973970",
            country_code="62",
            sms_url="https://it.tgflare.com/api/record?token=demo",
            gopay_pin="558023",
        )
    )

    try:
        captured["func"]()
    except api.TaskResultError as exc:
        result = exc.task_result
    else:
        raise AssertionError("expected GoPay bind failure to raise TaskResultError")

    assert result["status"] == "failed"
    assert result["registered_emails"] == ["new@example.com"]
    assert result["bind_failed_emails"][0]["email"] == "new@example.com"
    assert result["failed_emails"][0]["register_status"] == "success"
    assert result["failed_emails"][0]["bind_status"] == "failed"
    assert result["auto_register_results"][0]["message"].startswith("注册已成功，GoPay 绑定失败")
    assert any(progress["stage"] == "gopay_auto_register_bind_wait" for progress in captured["progress"])
    assert any(progress["stage"] == "gopay_pending_retry_queued" for progress in captured["progress"])
    assert any(progress["stage"] == "gopay_pending_retry_failed" for progress in captured["progress"])
    assert 12.5 in captured["slept"]


def test_gopay_params_accept_camel_case_auto_register_payload():
    params = api.GoPayBindTaskParams.model_validate(
        {
            "autoRegister": True,
            "autoRegisterCount": 2,
            "autoRegisterDomain": "openaibus.com",
            "autoRegisterDomains": ["openaibus.com", "rexmoxe.space"],
            "autoRegisterPrefix": "gopay",
            "autoRegisterPassword": "Password123!",
            "pendingRetryAttempts": 2,
            "phone_number": "+6287761973970",
            "country_code": "62",
            "sms_url": "https://it.tgflare.com/api/record?token=demo",
            "gopay_pin": "558023",
        }
    )

    assert params.email == ""
    assert params.auto_register is True
    assert params.auto_register_count == 2
    assert params.auto_register_domain == "openaibus.com"
    assert params.auto_register_domains == ["openaibus.com", "rexmoxe.space"]
    assert params.auto_register_prefix == "gopay"
    assert params.auto_register_password == "Password123!"
    assert params.pending_retry_attempts == 2


def test_post_task_skip_current_sets_gopay_skip_signal(monkeypatch):
    signal = api.threading.Event()
    progress_updates = []
    task = {
        "task_id": "task-skip",
        "command": "gopay-bind",
        "status": "running",
        "params": {"account_emails": ["user@example.com", "backup@example.com"]},
    }

    monkeypatch.setattr(api, "_current_task_id", "task-skip")
    monkeypatch.setattr(api, "_update_current_task_progress", lambda progress: progress_updates.append(progress))
    api._tasks["task-skip"] = task
    api._task_skip_signals["task-skip"] = signal
    try:
        result = api.post_task_skip_current()
    finally:
        api._tasks.pop("task-skip", None)
        api._task_skip_signals.pop("task-skip", None)

    assert signal.is_set()
    assert task["skip_current_requested"] is True
    assert result["task_id"] == "task-skip"
    assert progress_updates[-1]["stage"] == "gopay_skip_current_requested"


def test_run_gopay_bind_task_skips_current_account_and_continues(monkeypatch):
    skip_state = {"requested": False}
    cleared = []
    calls = []

    def fake_run_once(**kwargs):
        calls.append(kwargs["email"])
        if kwargs["email"] == "first@example.com":
            skip_state["requested"] = True
            return {"status": "failed", "failure_stage": "cancelled", "message": "任务已取消"}
        return {"status": "success", "message": "GoPay 绑定完成"}

    monkeypatch.setattr(gopay_executor, "_run_gopay_bind_task_once", fake_run_once)

    result = gopay_executor.run_gopay_bind_task(
        email="first@example.com",
        checkout_url="",
        phone_number="+6287761973970",
        sms_url="https://it.tgflare.com/api/record?token=demo",
        gopay_pin="558023",
        account_emails=["first@example.com", "second@example.com"],
        is_cancelled=lambda: False,
        skip_current=lambda: skip_state["requested"],
        clear_skip_current=lambda: (cleared.append(True), skip_state.update(requested=False)),
    )

    assert calls == ["first@example.com", "second@example.com"]
    assert cleared == [True]
    assert result["status"] == "success"
    assert result["email_used"] == "second@example.com"
    assert result["skipped_emails"] == ["first@example.com"]


def test_run_gopay_bind_task_rotates_phone_accounts_with_candidates(monkeypatch):
    calls = []

    def fake_run_once(**kwargs):
        calls.append((kwargs["email"], kwargs["country_code"], kwargs["phone_number"], kwargs["sms_url"], kwargs["gopay_pin"]))
        if kwargs["email"] == "first@example.com":
            return {"status": "failed", "failure_stage": "post_submit", "message": "first failed"}
        return {"status": "success", "message": "GoPay 绑定完成"}

    monkeypatch.setattr(gopay_executor, "_run_gopay_bind_task_once", fake_run_once)

    result = gopay_executor.run_gopay_bind_task(
        email="first@example.com",
        checkout_url="",
        phone_number="+628111111111",
        sms_url="https://sms.example/one",
        gopay_pin="111111",
        phone_accounts=[
            {
                "country_code": "62",
                "phone_number": "+628111111111",
                "sms_url": "https://sms.example/one",
                "gopay_pin": "111111",
            },
            {
                "country_code": "62",
                "phone_number": "+628222222222",
                "sms_url": "https://sms.example/two",
                "gopay_pin": "222222",
            },
        ],
        account_emails=["first@example.com", "second@example.com"],
        is_cancelled=lambda: False,
    )

    assert calls == [
        ("first@example.com", "62", "+628111111111", "https://sms.example/one", "111111"),
        ("second@example.com", "62", "+628222222222", "https://sms.example/two", "222222"),
    ]
    assert result["status"] == "success"
    assert result["email_used"] == "second@example.com"


def test_run_gopay_bind_task_rotates_on_gopay_wallet_payment_process_failure(monkeypatch):
    calls = []
    progress_events = []
    slept = []

    def fake_run_once(**kwargs):
        calls.append(kwargs["email"])
        if kwargs["email"] == "first@example.com":
            return {
                "status": "failed",
                "failure_stage": "gopay_payment_process",
                "message": (
                    'gopay_payment_process 失败: HTTP 400 {"success":false,'
                    '"errors":[{"code":"201","cause":"createAuth call to payment-switch '
                    'failed for payment_method: GOPAY_WALLET"}]}'
                ),
            }
        return {"status": "success", "message": "GoPay 绑定完成"}

    monkeypatch.setattr(gopay_executor, "_run_gopay_bind_task_once", fake_run_once)
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda seconds: slept.append(seconds))

    result = gopay_executor.run_gopay_bind_task(
        email="first@example.com",
        checkout_url="",
        phone_number="+6287761973970",
        sms_url="https://it.tgflare.com/api/record?token=demo",
        gopay_pin="558023",
        account_emails=["first@example.com", "second@example.com"],
        is_cancelled=lambda: False,
        progress_callback=progress_events.append,
    )

    assert calls == ["first@example.com", "second@example.com", "first@example.com"]
    assert result["status"] == "success"
    assert result["email_used"] == "second@example.com"
    assert result["payment_failed_emails"] == ["first@example.com"]
    assert result["retried_emails"] == ["first@example.com"]
    assert slept == [60.0]
    assert any(event["stage"] == "gopay_payment_process_failed_rotate" for event in progress_events)


def test_run_gopay_bind_task_retries_pending_blocked_candidate_once(monkeypatch):
    calls = []
    progress_events = []
    slept = []

    def fake_run_once(**kwargs):
        calls.append(kwargs["email"])
        if kwargs["email"] == "first@example.com" and calls.count("first@example.com") == 1:
            return {
                "status": "failed",
                "failure_stage": "chatgpt_approve",
                "message": "ChatGPT approve blocked",
            }
        return {"status": "success", "message": "GoPay 绑定完成"}

    monkeypatch.setattr(gopay_executor, "_run_gopay_bind_task_once", fake_run_once)
    monkeypatch.setattr(gopay_executor, "_mark_approve_blocked", lambda _email: 1)
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda seconds: slept.append(seconds))

    result = gopay_executor.run_gopay_bind_task(
        email="first@example.com",
        checkout_url="",
        phone_number="+6287761973970",
        sms_url="https://it.tgflare.com/api/record?token=demo",
        gopay_pin="558023",
        account_emails=["first@example.com", "second@example.com"],
        is_cancelled=lambda: False,
        progress_callback=progress_events.append,
    )

    assert calls == ["first@example.com", "second@example.com", "first@example.com"]
    assert result["status"] == "success"
    assert sorted(result["successful_emails"]) == ["first@example.com", "second@example.com"]
    assert result["pending_retry_emails"] == []
    assert result["retried_emails"] == ["first@example.com"]
    assert result.get("blocked_emails", []) == []
    assert any(event["stage"] == "gopay_pending_retry_queued" for event in progress_events)
    assert any(event["stage"] == "gopay_pending_retry_wait" for event in progress_events)
    assert any(event["stage"] == "gopay_pending_retry_account" for event in progress_events)
    assert slept == [60.0]


def test_run_gopay_bind_task_retries_http_403_candidate_once(monkeypatch):
    calls = []
    progress_events = []
    slept = []

    def fake_run_once(**kwargs):
        email = kwargs["email"]
        calls.append(email)
        if email == "first@example.com" and calls.count("first@example.com") == 1:
            return {
                "status": "failed",
                "failure_stage": "post_submit",
                "message": "执行 GoPay 任务时出现异常: HTTP 403: HTTP 403",
            }
        return {"status": "success", "message": "GoPay 绑定完成"}

    monkeypatch.setattr(gopay_executor, "_run_gopay_bind_task_once", fake_run_once)
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda seconds: slept.append(seconds))

    result = gopay_executor.run_gopay_bind_task(
        email="first@example.com",
        checkout_url="",
        phone_number="+6287761973970",
        sms_url="https://it.tgflare.com/api/record?token=demo",
        gopay_pin="558023",
        account_emails=["first@example.com", "second@example.com"],
        is_cancelled=lambda: False,
        progress_callback=progress_events.append,
    )

    assert calls == ["first@example.com", "second@example.com", "first@example.com"]
    assert result["status"] == "success"
    assert sorted(result["successful_emails"]) == ["first@example.com", "second@example.com"]
    assert result["pending_retry_emails"] == []
    assert result["retried_emails"] == ["first@example.com"]
    queued = [event for event in progress_events if event["stage"] == "gopay_pending_retry_queued"]
    assert queued
    assert queued[0]["reason"] == "http_403"
    assert any(event["stage"] == "gopay_retryable_failure_rotate" for event in progress_events)
    assert slept == [60.0]


def test_run_gopay_bind_task_queues_gopay_authorize_too_many_attempts(monkeypatch):
    calls = []
    progress_events = []
    slept = []
    rate_limit_message = "GoPay 授权页提示尝试过多，请稍后重试，或更换 GoPay 手机号/钱包"

    def fake_run_once(**kwargs):
        email = kwargs["email"]
        calls.append(email)
        if email == "first@example.com" and calls.count("first@example.com") == 1:
            return {
                "status": "failed",
                "failure_stage": "browser_checkout",
                "message": rate_limit_message,
            }
        return {"status": "success", "message": "GoPay 绑定完成"}

    monkeypatch.setattr(gopay_executor, "_run_gopay_bind_task_once", fake_run_once)
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda seconds: slept.append(seconds))

    result = gopay_executor.run_gopay_bind_task(
        email="first@example.com",
        checkout_url="",
        phone_number="+6287761973970",
        sms_url="https://it.tgflare.com/api/record?token=demo",
        gopay_pin="558023",
        account_emails=["first@example.com", "second@example.com"],
        is_cancelled=lambda: False,
        progress_callback=progress_events.append,
    )

    assert calls == ["first@example.com", "second@example.com", "first@example.com"]
    assert result["status"] == "success"
    assert sorted(result["successful_emails"]) == ["first@example.com", "second@example.com"]
    assert result["retried_emails"] == ["first@example.com"]
    queued = [event for event in progress_events if event["stage"] == "gopay_pending_retry_queued"]
    assert queued
    assert queued[0]["reason"] == "rate_limited"
    assert any(event["stage"] == "gopay_rate_limited_retry" for event in progress_events)
    assert slept == [60.0]


def test_run_gopay_bind_task_retries_local_cooldown_skip_once(monkeypatch):
    calls = []
    slept = []

    def fake_run_once(**kwargs):
        calls.append(kwargs["email"])
        return {"status": "success", "message": "GoPay 绑定完成"}

    monkeypatch.setattr(gopay_executor, "_run_gopay_bind_task_once", fake_run_once)
    monkeypatch.setattr(gopay_executor, "_approve_blocked_remaining", lambda email: 30 if email == "first@example.com" else 0)
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda seconds: slept.append(seconds))

    result = gopay_executor.run_gopay_bind_task(
        email="first@example.com",
        checkout_url="",
        phone_number="+6287761973970",
        sms_url="https://it.tgflare.com/api/record?token=demo",
        gopay_pin="558023",
        account_emails=["first@example.com", "second@example.com"],
        is_cancelled=lambda: False,
    )

    assert calls == ["second@example.com", "first@example.com"]
    assert result["status"] == "success"
    assert sorted(result["successful_emails"]) == ["first@example.com", "second@example.com"]
    assert result["retried_emails"] == ["first@example.com"]
    assert result.get("skipped_cooldown_emails", []) == []
    assert slept == [60.0]


def test_run_gopay_bind_task_retries_pending_blocked_candidate_by_round(monkeypatch):
    calls = []
    slept = []
    progress_events = []

    def fake_run_once(**kwargs):
        email = kwargs["email"]
        calls.append(email)
        if email == "first@example.com" and calls.count("first@example.com") < 3:
            return {
                "status": "failed",
                "failure_stage": "chatgpt_approve",
                "message": "ChatGPT approve blocked",
            }
        return {"status": "success", "message": "GoPay 绑定完成"}

    monkeypatch.setattr(gopay_executor, "_run_gopay_bind_task_once", fake_run_once)
    monkeypatch.setattr(gopay_executor, "_mark_approve_blocked", lambda _email: 1)
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda seconds: slept.append(seconds))

    result = gopay_executor.run_gopay_bind_task(
        email="first@example.com",
        checkout_url="",
        phone_number="+6287761973970",
        sms_url="https://it.tgflare.com/api/record?token=demo",
        gopay_pin="558023",
        account_emails=["first@example.com", "second@example.com"],
        pending_retry_attempts=2,
        is_cancelled=lambda: False,
        progress_callback=progress_events.append,
    )

    assert calls == ["first@example.com", "second@example.com", "first@example.com", "first@example.com"]
    assert result["status"] == "success"
    assert sorted(result["successful_emails"]) == ["first@example.com", "second@example.com"]
    assert result["pending_retry_emails"] == []
    assert result["retried_emails"] == ["first@example.com"]
    assert result.get("blocked_emails", []) == []
    assert slept == [60.0, 180.0]
    retry_rounds = [
        event.get("retry_round")
        for event in progress_events
        if event.get("stage") == "gopay_pending_retry_account"
    ]
    assert retry_rounds == [1, 2]


def test_run_gopay_bind_task_rotates_on_nonzero_amount_guard(monkeypatch):
    calls = []
    progress_events = []

    def fake_run_once(**kwargs):
        calls.append(kwargs["email"])
        if kwargs["email"] == "first@example.com":
            return {
                "status": "failed",
                "failure_stage": "midtrans_charge_guard",
                "message": "Midtrans gross_amount=34900000 IDR 非 0，已在 GoPay 绑定前停止",
            }
        return {"status": "success", "message": "GoPay 绑定完成"}

    monkeypatch.setattr(gopay_executor, "_run_gopay_bind_task_once", fake_run_once)

    result = gopay_executor.run_gopay_bind_task(
        email="first@example.com",
        checkout_url="",
        phone_number="+6287761973970",
        sms_url="https://it.tgflare.com/api/record?token=demo",
        gopay_pin="558023",
        account_emails=["first@example.com", "second@example.com"],
        is_cancelled=lambda: False,
        progress_callback=progress_events.append,
    )

    assert calls == ["first@example.com", "second@example.com"]
    assert result["status"] == "success"
    assert result["email_used"] == "second@example.com"
    assert result["nonzero_blocked_emails"] == ["first@example.com"]
    assert any(event["stage"] == "gopay_nonzero_amount_blocked_rotate" for event in progress_events)


def test_run_gopay_bind_task_rotates_on_token_invalidated(monkeypatch):
    calls = []
    progress_events = []

    def fake_run_once(**kwargs):
        calls.append(kwargs["email"])
        if kwargs["email"] == "first@example.com":
            return {
                "status": "failed",
                "failure_stage": "post_submit",
                "message": (
                    "执行 GoPay 任务时出现异常: {'message': 'Your authentication token has been "
                    "invalidated. Please try signing in again.', 'code': 'token_invalidated'}: HTTP 401"
                ),
            }
        return {"status": "success", "message": "GoPay 绑定完成"}

    monkeypatch.setattr(gopay_executor, "_run_gopay_bind_task_once", fake_run_once)

    result = gopay_executor.run_gopay_bind_task(
        email="first@example.com",
        checkout_url="",
        phone_number="+6287761973970",
        sms_url="https://it.tgflare.com/api/record?token=demo",
        gopay_pin="558023",
        account_emails=["first@example.com", "second@example.com"],
        is_cancelled=lambda: False,
        progress_callback=progress_events.append,
    )

    assert calls == ["first@example.com", "second@example.com"]
    assert result["status"] == "success"
    assert result["email_used"] == "second@example.com"
    assert result["failed_emails"] == ["first@example.com"]
    assert result["token_invalidated_emails"] == ["first@example.com"]
    assert any(
        event["stage"] == "gopay_account_failed_rotate" and event["token_invalidated"] is True
        for event in progress_events
    )
    assert not any(event["stage"] == "gopay_pending_retry_queued" for event in progress_events)


def test_run_gopay_bind_task_marks_token_invalidated_without_auth_session_refresh(monkeypatch):
    calls = []
    refresh_calls = []
    progress_events = []
    slept = []

    def fake_run_once(**kwargs):
        email = kwargs["email"]
        calls.append(email)
        if email == "first@example.com" and calls.count(email) == 1:
            return {
                "status": "failed",
                "failure_stage": "post_submit",
                "message": (
                    "执行 GoPay 任务时出现异常: {'message': 'Your authentication token has been "
                    "invalidated. Please try signing in again.', 'code': 'token_invalidated'}: HTTP 401"
                ),
            }
        return {"status": "success", "message": "GoPay 绑定完成"}

    def fake_refresh(email, result):
        refresh_calls.append((email, result["failure_stage"]))
        return {"status": "success", "auth_session_file": f"data/auth_session/{email}.json"}

    monkeypatch.setattr(gopay_executor, "_run_gopay_bind_task_once", fake_run_once)
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda seconds: slept.append(seconds))

    result = gopay_executor.run_gopay_bind_task(
        email="first@example.com",
        checkout_url="",
        phone_number="+6287761973970",
        sms_url="https://it.tgflare.com/api/record?token=demo",
        gopay_pin="558023",
        account_emails=["first@example.com", "second@example.com"],
        pending_retry_attempts=1,
        auth_session_refresh_callback=fake_refresh,
        is_cancelled=lambda: False,
        progress_callback=progress_events.append,
    )

    assert calls == ["first@example.com", "second@example.com"]
    assert refresh_calls == []
    assert result["status"] == "success"
    assert result["successful_emails"] == ["second@example.com"]
    assert result["failed_emails"] == ["first@example.com"]
    assert result["auth_session_refreshed_emails"] == []
    assert result["auth_session_refresh_failed_emails"] == ["first@example.com"]
    assert result["token_invalidated_emails"] == ["first@example.com"]
    assert result["retried_emails"] == []
    assert slept == []
    assert not any(event["stage"] == "gopay_auth_session_refresh_started" for event in progress_events)
    assert not any(event["stage"] == "gopay_auth_session_refresh_done" for event in progress_events)
    assert any(event["stage"] == "gopay_auth_session_refresh_failed" for event in progress_events)


def test_run_gopay_bind_task_treats_user_is_paid_as_success(monkeypatch):
    calls = []
    progress_events = []

    def fake_run_once(**kwargs):
        calls.append(kwargs["email"])
        if kwargs["email"] != "paid@example.com":
            return {"status": "success", "message": "GoPay 绑定完成"}
        return {
            "status": "failed",
            "failure_stage": "generate_checkout",
            "message": "生成印尼区支付链接失败: user is paid",
        }

    monkeypatch.setattr(gopay_executor, "_run_gopay_bind_task_once", fake_run_once)

    result = gopay_executor.run_gopay_bind_task(
        email="paid@example.com",
        checkout_url="",
        phone_number="+6287761973970",
        sms_url="https://it.tgflare.com/api/record?token=demo",
        gopay_pin="558023",
        account_emails=["paid@example.com", "second@example.com"],
        is_cancelled=lambda: False,
        progress_callback=progress_events.append,
    )

    assert calls == ["paid@example.com", "second@example.com"]
    assert result["status"] == "success"
    assert result["user_paid_skip_emails"] == ["paid@example.com"]
    assert sorted(result["successful_emails"]) == ["paid@example.com", "second@example.com"]
    assert result["pending_retry_emails"] == []
    assert result["message"] == "GoPay 批量绑定完成: 成功 2/2 个账号"
    assert any(event["stage"] == "chatgpt_user_paid_skip" for event in progress_events)


def test_run_gopay_bind_task_rotates_on_generic_account_failure(monkeypatch):
    calls = []

    def fake_run_once(**kwargs):
        calls.append(kwargs["email"])
        if kwargs["email"] == "first@example.com":
            return {
                "status": "failed",
                "failure_stage": "post_submit",
                "message": "执行 GoPay 任务时出现异常: transient checkout failure",
            }
        return {"status": "success", "message": "GoPay 绑定完成"}

    monkeypatch.setattr(gopay_executor, "_run_gopay_bind_task_once", fake_run_once)

    result = gopay_executor.run_gopay_bind_task(
        email="first@example.com",
        checkout_url="",
        phone_number="+6287761973970",
        sms_url="https://it.tgflare.com/api/record?token=demo",
        gopay_pin="558023",
        account_emails=["first@example.com", "second@example.com"],
        is_cancelled=lambda: False,
    )

    assert calls == ["first@example.com", "second@example.com"]
    assert result["status"] == "success"
    assert result["email_used"] == "second@example.com"
    assert result["failed_emails"] == ["first@example.com"]
    assert result["token_invalidated_emails"] == []


def test_run_gopay_bind_task_retries_already_linked_once(monkeypatch):
    calls = []
    progress_events = []
    slept = []

    def fake_run_once(**kwargs):
        calls.append(kwargs["email"])
        return {
            "status": "failed",
            "failure_stage": "midtrans_linking",
            "message": "该 GoPay 手机号已绑定其他账号；请先在 GoPay 侧解绑其他账号后再重试",
        }

    monkeypatch.setattr(gopay_executor, "_run_gopay_bind_task_once", fake_run_once)
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda seconds: slept.append(seconds))

    result = gopay_executor.run_gopay_bind_task(
        email="first@example.com",
        checkout_url="",
        phone_number="+6287761973970",
        sms_url="https://it.tgflare.com/api/record?token=demo",
        gopay_pin="558023",
        account_emails=["first@example.com", "second@example.com"],
        is_cancelled=lambda: False,
        progress_callback=progress_events.append,
    )

    assert calls == ["first@example.com", "second@example.com", "first@example.com", "second@example.com"]
    assert result["status"] == "failed"
    assert result["failure_stage"] == "midtrans_linking"
    assert result["failed_emails"] == ["first@example.com", "second@example.com"]
    assert result["retried_emails"] == ["first@example.com", "second@example.com"]
    assert result["pending_retry_emails"] == []
    assert slept == [60.0]
    assert any(event["stage"] == "gopay_already_linked_retry" for event in progress_events)


def test_run_gopay_bind_task_shows_rate_limit_message_for_midtrans_429(monkeypatch):
    calls = []
    slept = []

    def fake_run_once(**kwargs):
        calls.append(kwargs["email"])
        return {
            "status": "failed",
            "failure_stage": "midtrans_linking",
            "message": "Midtrans linking 失败: HTTP 429",
        }

    monkeypatch.setattr(gopay_executor, "_run_gopay_bind_task_once", fake_run_once)
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda seconds: slept.append(seconds))

    result = gopay_executor.run_gopay_bind_task(
        email="first@example.com",
        checkout_url="",
        phone_number="+6287761973970",
        sms_url="https://it.tgflare.com/api/record?token=demo",
        gopay_pin="558023",
        account_emails=["first@example.com", "second@example.com"],
        is_cancelled=lambda: False,
    )

    assert calls == ["first@example.com", "second@example.com", "first@example.com", "second@example.com"]
    assert result["status"] == "failed"
    assert result["failure_stage"] == "midtrans_linking"
    assert result["message"] == "GoPay/Midtrans 限流，请稍后重试"
    assert result["failed_emails"] == ["first@example.com", "second@example.com"]
    assert result["retried_emails"] == ["first@example.com", "second@example.com"]
    assert slept == [60.0]


def test_run_gopay_bind_task_retries_gopay_otp_failure_once(monkeypatch):
    calls = []
    progress_events = []
    slept = []

    def fake_run_once(**kwargs):
        calls.append(kwargs["email"])
        if kwargs["email"] == "first@example.com":
            return {
                "status": "failed",
                "failure_stage": "fetch_otp",
                "message": "等待 GoPay OTP 超时",
            }
        return {"status": "success", "message": "GoPay 绑定完成"}

    monkeypatch.setattr(gopay_executor, "_run_gopay_bind_task_once", fake_run_once)
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda seconds: slept.append(seconds))

    result = gopay_executor.run_gopay_bind_task(
        email="first@example.com",
        checkout_url="",
        phone_number="+6287761973970",
        sms_url="https://it.tgflare.com/api/record?token=demo",
        gopay_pin="558023",
        account_emails=["first@example.com", "second@example.com"],
        is_cancelled=lambda: False,
        progress_callback=progress_events.append,
    )

    assert calls == ["first@example.com", "second@example.com", "first@example.com"]
    assert result["status"] == "success"
    assert result["email_used"] == "second@example.com"
    assert result["failed_emails"] == ["first@example.com"]
    assert result["retried_emails"] == ["first@example.com"]
    assert slept == [60.0]
    assert any(event["stage"] == "gopay_otp_retry" for event in progress_events)


def test_gopay_task_runner_raises_on_failed_executor_result(monkeypatch):
    captured = {}
    progress_updates = []

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr("autoteam.accounts.find_account", lambda accounts, email: accounts[0] if email == "user@example.com" else None)
    monkeypatch.setattr("autoteam.accounts.update_account", lambda *args, **kwargs: None)
    monkeypatch.setattr("autoteam.accounts.delete_account", lambda email: captured.setdefault("deleted_accounts", []).append(email) or True)
    monkeypatch.setattr("autoteam.auth_session_store.delete_auth_session", lambda email: captured.setdefault("deleted_sessions", []).append(email) or True)
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_update_current_task_progress", lambda progress: progress_updates.append(progress))
    monkeypatch.setattr("autoteam.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))
    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "failed",
            "failure_stage": "submit_checkout",
            "message": "点击订阅重试 3 次后仍失败: 付款未获批准",
            "screenshot_paths": [],
            "checkout_url": "https://chatgpt.com/checkout/demo",
            "billing_info": {"name": "John Smith"},
        }

    monkeypatch.setattr("autoteam.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-789", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="user@example.com",
            phone_number="+6287761973970",
            country_code="62",
            sms_url="https://it.tgflare.com/api/record?token=demo",
            gopay_pin="558023",
        )
    )

    with pytest.raises(api.TaskResultError) as exc:
        captured["func"]()

    assert "付款未获批准" in str(exc.value)
    assert exc.value.task_result["task_status"] == "failed"
    assert captured["audit"]["task_status"] == "failed"
    assert captured.get("deleted_accounts") is None
    assert captured.get("deleted_sessions") is None
    assert exc.value.task_result["rejected_pool_emails"] == ["user@example.com"]
    assert captured["run_kwargs"]["country_code"] == "62"
    assert progress_updates[-1]["stage"] == "failed"


def test_gopay_task_runner_marks_success_account_plus(monkeypatch):
    captured = {"updates": [], "progress": []}

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr("autoteam.accounts.find_account", lambda accounts, email: accounts[0] if email == "user@example.com" else None)
    monkeypatch.setattr("autoteam.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs)))
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_update_current_task_progress", lambda progress: captured["progress"].append(progress))
    monkeypatch.setattr("autoteam.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "checkout_url": "https://chatgpt.com/checkout/demo",
            "email_used": "user@example.com",
        }

    monkeypatch.setattr("autoteam.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-790", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="user@example.com",
            phone_number="+6287761973970",
            country_code="62",
            sms_url="https://it.tgflare.com/api/record?token=demo",
            gopay_pin="558023",
        )
    )

    result = captured["func"]()

    assert result["task_status"] == "completed"
    assert captured["updates"]
    email, update = captured["updates"][-1]
    assert email == "user@example.com"
    assert update["status"] == accounts_module.STATUS_ACTIVE
    assert update["account_type"] == accounts_module.ACCOUNT_TYPE_PLUS
    assert update["plus_bound_at"] == update["last_bind_at"]
    assert "auth_file" not in update
    assert update["last_bind_status"] == "success"
    assert "cpa_sync" not in result
    assert captured["audit"]["task_status"] == "completed"


def test_gopay_task_runner_passes_whatsapp_otp_channel_and_default_url(monkeypatch):
    captured = {"updates": [], "progress": []}

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr("autoteam.accounts.find_account", lambda accounts, email: accounts[0] if email == "user@example.com" else None)
    monkeypatch.setattr("autoteam.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs)))
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_update_current_task_progress", lambda progress: captured["progress"].append(progress))
    monkeypatch.setattr("autoteam.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "checkout_url": "https://chatgpt.com/checkout/demo",
            "email_used": "user@example.com",
        }

    monkeypatch.setattr("autoteam.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)
    monkeypatch.setattr(api, "_default_whatsapp_otp_url", lambda: "http://127.0.0.1:8787/otp/whatsapp/latest")

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["params"] = params
        captured["func"] = func
        return {"task_id": "task-wa", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="user@example.com",
            phone_number="15825989172",
            country_code="86",
            sms_url="https://it.tgflare.com/api/record?token=stale",
            gopay_pin="558023",
            otp_channel="whatsapp",
        )
    )

    result = captured["func"]()

    assert result["task_status"] == "completed"
    assert captured["params"]["phone_accounts"][0]["otp_channel"] == "whatsapp"
    assert captured["run_kwargs"]["otp_channel"] == "whatsapp"
    assert captured["run_kwargs"]["sms_url"] == "http://127.0.0.1:8787/otp/whatsapp/latest"
    assert captured["run_kwargs"]["phone_accounts"][0]["sms_url"] == "http://127.0.0.1:8787/otp/whatsapp/latest"


def test_gopay_task_runner_marks_all_batch_success_accounts_plus(monkeypatch):
    captured = {"updates": [], "progress": []}
    accounts = [{"email": "first@example.com"}, {"email": "second@example.com"}]

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autoteam.accounts.find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    monkeypatch.setattr("autoteam.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs)))
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/account.json")
    monkeypatch.setattr(api, "_update_current_task_progress", lambda progress: captured["progress"].append(progress))
    monkeypatch.setattr("autoteam.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "success",
            "message": "GoPay 批量绑定完成: 成功 2/2 个账号",
            "email_used": "second@example.com",
            "successful_emails": ["first@example.com", "second@example.com"],
        }

    monkeypatch.setattr("autoteam.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-790", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="first@example.com",
            account_emails=["first@example.com", "second@example.com"],
            phone_number="+6287761973970",
            country_code="62",
            sms_url="https://it.tgflare.com/api/record?token=demo",
            gopay_pin="558023",
        )
    )

    result = captured["func"]()

    assert result["task_status"] == "completed"
    assert [email for email, _update in captured["updates"]] == ["first@example.com", "second@example.com"]
    for _email, update in captured["updates"]:
        assert update["last_bind_status"] == "success"
        assert update["status"] == accounts_module.STATUS_ACTIVE
        assert update["account_type"] == accounts_module.ACCOUNT_TYPE_PLUS
        assert update["plus_bound_at"] == update["last_bind_at"]


def test_gopay_task_runner_marks_batch_success_account_plus_immediately(monkeypatch):
    captured = {"updates": [], "progress": []}
    accounts = [{"email": "first@example.com"}, {"email": "second@example.com"}]

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autoteam.accounts.find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    monkeypatch.setattr("autoteam.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs)))
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/account.json")
    monkeypatch.setattr(api, "_update_current_task_progress", lambda progress: captured["progress"].append(progress))
    monkeypatch.setattr("autoteam.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))

    def fake_run_gopay_bind_task(**kwargs):
        kwargs["progress_callback"](
            {
                "stage": "gopay_account_bound",
                "email": "first@example.com",
                "checkout_url": "https://pay.openai.com/c/pay/cs_first",
                "message": "当前账号 GoPay 绑定成功: first@example.com",
            }
        )
        captured["updates_after_first_success"] = list(captured["updates"])
        kwargs["progress_callback"](
            {
                "stage": "gopay_account_bound",
                "email": "second@example.com",
                "checkout_url": "https://pay.openai.com/c/pay/cs_second",
                "message": "当前账号 GoPay 绑定成功: second@example.com",
            }
        )
        return {
            "status": "success",
            "message": "GoPay 批量绑定完成: 成功 2/2 个账号",
            "email_used": "second@example.com",
            "successful_emails": ["first@example.com", "second@example.com"],
        }

    monkeypatch.setattr("autoteam.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-793", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="first@example.com",
            account_emails=["first@example.com", "second@example.com"],
            phone_number="+6287761973970",
            country_code="62",
            sms_url="https://it.tgflare.com/api/record?token=demo",
            gopay_pin="558023",
        )
    )

    result = captured["func"]()

    assert result["task_status"] == "completed"
    assert [email for email, _update in captured["updates_after_first_success"]] == ["first@example.com"]
    assert [email for email, _update in captured["updates"]] == ["first@example.com", "second@example.com"]
    assert captured["updates"][0][1]["last_checkout_url"] == "https://pay.openai.com/c/pay/cs_first"
    assert captured["updates"][1][1]["last_checkout_url"] == "https://pay.openai.com/c/pay/cs_second"
    assert all(update["account_type"] == accounts_module.ACCOUNT_TYPE_PLUS for _email, update in captured["updates"])
    success_progress = [progress for progress in captured["progress"] if progress["stage"] == "gopay_account_bound"]
    assert [progress["successful"] for progress in success_progress] == [1, 2]
    assert success_progress[-1]["successful_emails"] == ["first@example.com", "second@example.com"]


def test_gopay_task_runner_auto_oauth_after_success(monkeypatch):
    captured = {"updates": [], "progress": [], "oauth_calls": []}
    oauth_done = threading.Event()
    accounts = [
        {"email": "first@example.com", "password": "pw1", "account_type": "free"},
        {"email": "second@example.com", "password": "pw2", "account_type": "free"},
    ]

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autoteam.accounts.find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    monkeypatch.setattr("autoteam.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs)))
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/account.json")
    monkeypatch.setattr(api, "_update_current_task_progress", lambda progress: captured["progress"].append(progress))
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autoteam.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "success",
            "message": "GoPay 批量绑定完成: 成功 2/2 个账号",
            "email_used": "second@example.com",
            "checkout_url": "https://pay.openai.com/c/pay/cs_done",
            "successful_emails": ["first@example.com", "second@example.com"],
        }

    monkeypatch.setattr("autoteam.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_codex_login(email, acc, *, headless=False):
        captured["oauth_calls"].append((email, acc, headless))
        if len(captured["oauth_calls"]) >= 2:
            oauth_done.set()
        return {"email": email, "plan": "plus", "auth_file": f"data/auths/{email}.json"}

    monkeypatch.setattr(api, "_run_account_codex_login_once", fake_codex_login)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-794", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="first@example.com",
            account_emails=["first@example.com", "second@example.com"],
            phone_number="+6287761973970",
            country_code="62",
            sms_url="https://it.tgflare.com/api/record?token=demo",
            gopay_pin="558023",
            auto_oauth_after_success=True,
        )
    )

    result = captured["func"]()

    assert result["task_status"] == "completed"
    assert result["oauth_scheduled_emails"] == ["first@example.com", "second@example.com"]
    assert oauth_done.wait(2)
    assert sorted(email for email, _acc, _headless in captured["oauth_calls"]) == ["first@example.com", "second@example.com"]
    assert all(headless is False for _email, _acc, headless in captured["oauth_calls"])
    stages = [progress["stage"] for progress in captured["progress"]]
    assert stages.count("gopay_oauth_login_started") == 2
    assert stages.count("gopay_oauth_login_done") == 2
    assert all(update["account_type"] == accounts_module.ACCOUNT_TYPE_PLUS for _email, update in captured["updates"])
    assert all("credentials_exported" not in update for _email, update in captured["updates"])
    assert all("credentials_exported_at" not in update for _email, update in captured["updates"])


def test_gopay_task_runner_auto_oauth_retries_twice_after_success(monkeypatch):
    captured = {"updates": [], "progress": [], "oauth_calls": []}
    oauth_done = threading.Event()
    account = {"email": "retry@example.com", "password": "pw1", "account_type": "free"}

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autoteam.accounts.find_account",
        lambda loaded, email: account if email == account["email"] else None,
    )
    monkeypatch.setattr("autoteam.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs)))
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/account.json")
    monkeypatch.setattr(api, "_update_current_task_progress", lambda progress: captured["progress"].append(progress))
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autoteam.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))
    monkeypatch.setattr(api.time, "sleep", lambda _seconds: None)

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "success",
            "message": "GoPay 批量绑定完成: 成功 1/1 个账号",
            "email_used": "retry@example.com",
            "checkout_url": "https://pay.openai.com/c/pay/cs_done",
            "successful_emails": ["retry@example.com"],
        }

    monkeypatch.setattr("autoteam.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_codex_login(email, acc, *, headless=False):
        captured["oauth_calls"].append((email, acc, headless))
        if len(captured["oauth_calls"]) < 3:
            raise RuntimeError(f"temporary oauth failure {len(captured['oauth_calls'])}")
        oauth_done.set()
        return {"email": email, "plan": "plus", "auth_file": f"data/auths/{email}.json"}

    monkeypatch.setattr(api, "_run_account_codex_login_once", fake_codex_login)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-795", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="retry@example.com",
            account_emails=["retry@example.com"],
            phone_number="+6287761973970",
            country_code="62",
            sms_url="https://it.tgflare.com/api/record?token=demo",
            gopay_pin="558023",
            auto_oauth_after_success=True,
        )
    )

    result = captured["func"]()

    assert result["task_status"] == "completed"
    assert result["oauth_scheduled_emails"] == ["retry@example.com"]
    assert oauth_done.wait(2)
    assert len(captured["oauth_calls"]) == 3
    assert all(headless is False for _email, _acc, headless in captured["oauth_calls"])
    stages = [progress["stage"] for progress in captured["progress"]]
    assert stages.count("gopay_oauth_login_retrying") == 2
    assert stages.count("gopay_oauth_login_done") == 1
    assert "gopay_oauth_login_failed" not in stages


def test_update_account_type_updates_local_account(monkeypatch):
    captured = {}
    account = {"email": "user@example.com", "status": "pending", "account_type": "free"}

    monkeypatch.setattr("autoteam.admin_state.get_admin_email", lambda: "owner@example.com")
    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autoteam.accounts.update_account", lambda email, **kwargs: captured.setdefault("updated", {"email": email, **kwargs}) or {**account, **kwargs})

    result = api.update_account_type("USER@example.com", api.AccountTypeUpdateParams(account_type="plus"))

    assert captured["updated"] == {"email": "user@example.com", "account_type": "plus"}
    assert result["account"]["email"] == "user@example.com"
    assert result["account"]["account_type"] == "plus"


def test_update_account_type_rejects_invalid_type(monkeypatch):
    monkeypatch.setattr("autoteam.admin_state.get_admin_email", lambda: "owner@example.com")

    with pytest.raises(api.HTTPException) as exc:
        api.update_account_type("user@example.com", api.AccountTypeUpdateParams(account_type="bad"))

    assert exc.value.status_code == 400


def test_update_account_type_rejects_main_account(monkeypatch):
    monkeypatch.setattr("autoteam.admin_state.get_admin_email", lambda: "owner@example.com")

    with pytest.raises(api.HTTPException) as exc:
        api.update_account_type("owner@example.com", api.AccountTypeUpdateParams(account_type="team"))

    assert exc.value.status_code == 400


def test_export_account_credentials_uses_custom_format(monkeypatch):
    captured = {"updates": []}
    monkeypatch.setattr(
        "autoteam.accounts.load_accounts",
        lambda: [
            {"email": "first@example.com", "password": "pw1", "status": "active", "seat_type": "codex"},
            {"email": "second@example.com", "password": "pw2", "status": "plus", "seat_type": "unknown"},
        ],
    )
    monkeypatch.setattr("autoteam.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs)))
    monkeypatch.setattr(api.time, "time", lambda: 1777777777.0)

    result = api.export_account_credentials(
        api.AccountCredentialExportParams(
            emails=["SECOND@example.com", "missing@example.com"],
            line_format="{email}-----{password}",
        )
    )

    assert result["count"] == 1
    assert result["content"] == "second@example.com-----pw2"
    assert result["missing"] == ["missing@example.com"]
    assert result["filename"].endswith(".txt")
    assert result["exported_emails"] == ["second@example.com"]
    assert result["exported_at"] == 1777777777.0
    assert captured["updates"] == [
        (
            "second@example.com",
            {"credentials_exported": True, "credentials_exported_at": 1777777777.0},
        )
    ]


def test_export_account_credentials_allows_already_exported_accounts(monkeypatch):
    monkeypatch.setattr(
        "autoteam.accounts.load_accounts",
        lambda: [
            {
                "email": "exported@example.com",
                "password": "pw",
                "credentials_exported": True,
                "credentials_exported_at": 1770000000.0,
            }
        ],
    )
    monkeypatch.setattr("autoteam.accounts.update_account", lambda _email, **_kwargs: None)

    result = api.export_account_credentials(
        api.AccountCredentialExportParams(
            emails=["exported@example.com"],
            line_format="{email}-----{password}",
        )
    )

    assert result["count"] == 1
    assert result["content"] == "exported@example.com-----pw"
    assert result["exported_emails"] == ["exported@example.com"]


def test_export_account_credentials_rejects_empty_format():
    with pytest.raises(api.HTTPException) as exc:
        api.export_account_credentials(api.AccountCredentialExportParams(line_format=" "))

    assert exc.value.status_code == 400


def test_export_account_cpa_auths_returns_existing_data_auths_file(tmp_path, monkeypatch):
    auth_dir = tmp_path / "data" / "auths"
    auth_file = auth_dir / "codex-user@example.com-plus-deadbeef.json"
    auth_dir.mkdir(parents=True)
    payload = {"email": "user@example.com", "access_token": "token", "refresh_token": "refresh"}
    auth_file.write_text(json.dumps(payload), encoding="utf-8")
    captured = {"updates": []}

    monkeypatch.setattr("autoteam.auth_storage.AUTH_DIR", auth_dir)
    monkeypatch.setattr(
        "autoteam.accounts.load_accounts",
        lambda: [{"email": "user@example.com", "auth_file": str(auth_file)}],
    )
    monkeypatch.setattr("autoteam.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs)))
    monkeypatch.setattr(api.time, "time", lambda: 1778888888.0)

    result = api.export_account_cpa_auths(api.AccountEmailBatchParams(emails=["USER@example.com"]))

    assert result["filename"] == auth_file.name
    assert result["content_type"] == "application/json"
    assert result["count"] == 1
    assert result["missing"] == []
    assert result["exported_emails"] == ["user@example.com"]
    assert result["exported_at"] == 1778888888.0
    assert captured["updates"] == [
        (
            "user@example.com",
            {"credentials_exported": True, "credentials_exported_at": 1778888888.0},
        )
    ]
    decoded = json.loads(base64.b64decode(result["content_base64"]).decode("utf-8"))
    assert decoded == payload


def test_export_account_sub_auths_returns_sub2api_json(tmp_path, monkeypatch):
    def fake_jwt(payload):
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        encoded = base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")
        return f"header.{encoded}.signature"

    auth_dir = tmp_path / "data" / "auths"
    auth_file = auth_dir / "codex-user@example.com-plus-deadbeef.json"
    auth_dir.mkdir(parents=True)
    payload = {
        "email": "user@example.com",
        "access_token": fake_jwt(
            {
                "client_id": "app_client",
                "https://api.openai.com/profile": {"email": "user@example.com"},
                "https://api.openai.com/auth": {"chatgpt_account_id": "account-1"},
            }
        ),
        "refresh_token": "refresh-token",
        "expired": "2026-04-18T12:20:50+08:00",
    }
    auth_file.write_text(json.dumps(payload), encoding="utf-8")
    captured = {"updates": []}

    monkeypatch.setattr("autoteam.auth_storage.AUTH_DIR", auth_dir)
    monkeypatch.setattr(
        "autoteam.accounts.load_accounts",
        lambda: [{"email": "user@example.com", "auth_file": str(auth_file)}],
    )
    monkeypatch.setattr("autoteam.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs)))
    monkeypatch.setattr(api.time, "time", lambda: 1779999999.0)

    result = api.export_account_sub_auths(api.AccountEmailBatchParams(emails=["USER@example.com"]))

    assert result["filename"].startswith("sub2api-account-")
    assert result["filename"].endswith(".json")
    assert result["content_type"] == "application/json"
    assert result["count"] == 1
    assert result["missing"] == []
    assert result["invalid"] == []
    assert result["exported_emails"] == ["user@example.com"]
    assert result["exported_at"] == 1779999999.0
    assert captured["updates"] == [
        (
            "user@example.com",
            {"credentials_exported": True, "credentials_exported_at": 1779999999.0},
        )
    ]
    decoded = json.loads(base64.b64decode(result["content_base64"]).decode("utf-8"))
    assert decoded["accounts"][0]["name"] == "user"
    assert decoded["accounts"][0]["platform"] == "openai"
    assert decoded["accounts"][0]["credentials"]["email"] == "user@example.com"
    assert decoded["accounts"][0]["credentials"]["refresh_token"] == "refresh-token"


def test_post_accounts_login_batch_starts_single_background_task(monkeypatch):
    captured = {"progress": []}
    rows = [
        {"email": "first@example.com", "password": "pw1", "account_type": "free", "status": "active"},
        {"email": "second@example.com", "password": "pw2", "account_type": "plus", "status": "active"},
        {"email": "third@example.com", "password": "pw3", "account_type": "plus", "status": "active"},
        {"email": "fourth@example.com", "password": "pw4", "account_type": "pro", "status": "active"},
    ]

    monkeypatch.delenv("CODEX_OAUTH_BATCH_CONCURRENCY", raising=False)
    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: rows)
    monkeypatch.setattr(
        "autoteam.accounts.find_account",
        lambda items, email: next((account for account in items if account["email"] == email), None),
    )
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)
    monkeypatch.setattr(
        api,
        "_run_account_codex_login_once",
        lambda email, _acc, *, headless=False: {"email": email, "plan": "plus", "auth_file": f"data/auths/{email}.json"},
    )
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["command"] = command
        captured["params"] = params
        captured["exclusive"] = kwargs.get("exclusive")
        captured["pass_task_id"] = kwargs.get("pass_task_id")
        captured["result"] = func("task-login-batch")
        return {"task_id": "task-login-batch", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    result = api.post_accounts_login_batch(
        api.AccountEmailBatchParams(
            emails=["FIRST@example.com", "second@example.com", "third@example.com", "fourth@example.com"]
        )
    )

    assert result["task_id"] == "task-login-batch"
    assert captured["command"] == "login-batch"
    assert captured["exclusive"] is False
    assert captured["pass_task_id"] is True
    assert captured["params"]["emails"] == [
        "first@example.com",
        "second@example.com",
        "third@example.com",
        "fourth@example.com",
    ]
    assert captured["result"]["total"] == 4
    assert captured["result"]["concurrency"] == 3
    assert sorted(item["email"] for item in captured["result"]["ok"]) == [
        "first@example.com",
        "fourth@example.com",
        "second@example.com",
        "third@example.com",
    ]
    assert any(progress["message"] == "补登录成功: second@example.com" for progress in captured["progress"])


def test_post_accounts_refresh_quota_marks_401_account_fail(tmp_path, monkeypatch):
    auth_file = tmp_path / "codex-user.json"
    auth_file.write_text(
        json.dumps(
            {
                "access_token": "expired-token",
                "account": {"id": "account-123"},
            }
        ),
        encoding="utf-8",
    )
    account = {
        "email": "user@example.com",
        "status": "active",
        "auth_file": str(auth_file),
    }
    updates = {}

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autoteam.accounts.find_account",
        lambda accounts, email: account if email == "user@example.com" else None,
    )
    monkeypatch.setattr("autoteam.accounts.update_account", lambda email, **kwargs: updates.setdefault(email, {}).update(kwargs))
    monkeypatch.setattr("autoteam.codex_auth.check_codex_quota", lambda token, account_id=None: ("auth_error", None))

    def fake_start_task(command, func, params, *args, **kwargs):
        return {
            "task_id": "task-refresh",
            "command": command,
            "params": params,
            "result": func("task-refresh"),
        }

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    result = api.post_accounts_refresh_quota(api.AccountEmailBatchParams(emails=["USER@example.com"]))

    assert result["command"] == "refresh-quota"
    assert result["result"]["failed"] == [{"email": "user@example.com", "reason": "auth_error"}]
    assert updates["user@example.com"]["status"] == "fail"
    assert updates["user@example.com"]["discarded_reason"] == "quota_refresh_401"
    assert updates["user@example.com"]["last_bind_failure_stage"] == "auth_401"


def test_post_accounts_refresh_quota_skips_fail_accounts_without_reactivating(tmp_path, monkeypatch):
    auth_file = tmp_path / "codex-user.json"
    auth_file.write_text(
        json.dumps(
            {
                "access_token": "token",
                "plan_type": "free",
            }
        ),
        encoding="utf-8",
    )
    account = {
        "email": "discarded@example.com",
        "status": "fail",
        "account_type": "plus",
        "auth_file": str(auth_file),
    }
    updates = {}
    quota_calls = []

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autoteam.accounts.find_account",
        lambda accounts, email: account if email == "discarded@example.com" else None,
    )
    monkeypatch.setattr("autoteam.accounts.update_account", lambda email, **kwargs: updates.setdefault(email, {}).update(kwargs))
    monkeypatch.setattr(
        "autoteam.codex_auth.check_codex_quota",
        lambda token, account_id=None: quota_calls.append(token) or ("ok", {"primary_pct": 1, "weekly_pct": 2}),
    )

    def fake_start_task(command, func, params, *args, **kwargs):
        return {
            "task_id": "task-refresh",
            "command": command,
            "params": params,
            "result": func("task-refresh"),
        }

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    result = api.post_accounts_refresh_quota(api.AccountEmailBatchParams(emails=["discarded@example.com"]))

    assert result["result"]["skipped"] == [{"email": "discarded@example.com", "reason": "fail_account"}]
    assert updates == {}
    assert quota_calls == []


def test_post_accounts_refresh_quota_keeps_network_errors_out_of_fail(tmp_path, monkeypatch):
    auth_file = tmp_path / "codex-user.json"
    auth_file.write_text(json.dumps({"access_token": "token"}), encoding="utf-8")
    account = {
        "email": "user@example.com",
        "status": "active",
        "auth_file": str(auth_file),
    }
    updates = {}

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autoteam.accounts.find_account",
        lambda accounts, email: account if email == "user@example.com" else None,
    )
    monkeypatch.setattr("autoteam.accounts.update_account", lambda email, **kwargs: updates.setdefault(email, {}).update(kwargs))
    monkeypatch.setattr("autoteam.codex_auth.check_codex_quota", lambda token, account_id=None: ("network_error", None))

    def fake_start_task(command, func, params, *args, **kwargs):
        return {
            "task_id": "task-refresh",
            "command": command,
            "params": params,
            "result": func("task-refresh"),
        }

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    result = api.post_accounts_refresh_quota(api.AccountEmailBatchParams(emails=["user@example.com"]))

    assert result["result"]["network_error"] == [{"email": "user@example.com", "reason": "network_error"}]
    assert updates == {}


def test_post_accounts_refresh_quota_empty_emails_defaults_to_all_non_main(tmp_path, monkeypatch):
    auth_file = tmp_path / "codex-user.json"
    auth_file.write_text(json.dumps({"access_token": "token"}), encoding="utf-8")
    rows = [
        {"email": "owner@example.com", "status": "active", "auth_file": str(auth_file)},
        {"email": "first@example.com", "status": "active", "auth_file": str(auth_file)},
        {"email": "second@example.com", "status": "active", "auth_file": str(auth_file)},
    ]
    checked = []

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: rows)
    monkeypatch.setattr(
        "autoteam.accounts.find_account",
        lambda accounts, email: next((account for account in accounts if account["email"] == email), None),
    )
    monkeypatch.setattr(api, "_is_main_account_email", lambda email: email == "owner@example.com")
    monkeypatch.setattr("autoteam.accounts.update_account", lambda email, **kwargs: checked.append(email))
    monkeypatch.setattr(
        "autoteam.codex_auth.check_codex_quota",
        lambda token, account_id=None: ("ok", {"primary_pct": 1, "weekly_pct": 2}),
    )

    def fake_start_task(command, func, params, *args, **kwargs):
        return {
            "task_id": "task-refresh",
            "command": command,
            "params": params,
            "result": func("task-refresh"),
        }

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    result = api.post_accounts_refresh_quota(api.AccountEmailBatchParams(emails=[]))

    assert result["params"]["emails"] == ["first@example.com", "second@example.com"]
    assert checked == ["first@example.com", "second@example.com"]


def test_post_account_login_removes_account_when_oauth_requires_phone(monkeypatch):
    from autoteam.codex_auth import CodexOAuthPhoneRequired

    captured = {"progress": []}
    account = {"email": "phone@example.com", "password": "pw", "account_type": "free", "status": "active"}

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autoteam.accounts.find_account", lambda items, email: account if email == account["email"] else None)
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)
    monkeypatch.setattr(api, "_run_account_codex_login_once", lambda *_args, **_kwargs: (_ for _ in ()).throw(CodexOAuthPhoneRequired("https://auth.openai.com/add-phone")))
    monkeypatch.setattr(
        api,
        "_remove_oauth_account_deactivated_accounts_from_pool",
        lambda emails: captured.setdefault("removed", list(emails)),
    )
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["command"] = command
        captured["exclusive"] = kwargs.get("exclusive")
        captured["pass_task_id"] = kwargs.get("pass_task_id")
        try:
            func("task-login-phone")
        except api.TaskResultError as exc:
            captured["error"] = exc
        return {"task_id": "task-login-phone", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_account_login(api.LoginAccountParams(email="phone@example.com"))

    assert captured["removed"] == ["phone@example.com"]
    assert captured["exclusive"] is False
    assert captured["pass_task_id"] is True
    assert captured["error"].task_result["failure_stage"] == "oauth_phone_required"
    assert captured["progress"][-1]["stage"] == "account_login_phone_required_removed"


def test_post_account_login_removes_account_when_oauth_account_deactivated(monkeypatch):
    from autoteam.codex_auth import CodexOAuthAccountDeactivated

    captured = {"progress": []}
    account = {"email": "dead@example.com", "password": "pw", "account_type": "free", "status": "active"}

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autoteam.accounts.find_account", lambda items, email: account if email == account["email"] else None)
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)
    monkeypatch.setattr(api, "_run_account_codex_login_once", lambda *_args, **_kwargs: (_ for _ in ()).throw(CodexOAuthAccountDeactivated("account_deactivated")))
    monkeypatch.setattr(
        api,
        "_remove_oauth_account_deactivated_accounts_from_pool",
        lambda emails: captured.setdefault("removed", list(emails)),
    )
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))

    def fake_start_task(command, func, params, *args, **kwargs):
        try:
            func("task-login-dead")
        except api.TaskResultError as exc:
            captured["error"] = exc
        return {"task_id": "task-login-dead", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_account_login(api.LoginAccountParams(email="dead@example.com"))

    assert captured["removed"] == ["dead@example.com"]
    assert captured["error"].task_result["failure_stage"] == "oauth_account_deactivated"
    assert captured["progress"][-1]["stage"] == "account_login_deactivated_removed"


def test_post_accounts_login_batch_continues_after_phone_required(monkeypatch):
    from autoteam.codex_auth import CodexOAuthPhoneRequired

    captured = {"progress": []}
    rows = [
        {"email": "phone@example.com", "password": "pw1", "account_type": "free", "status": "active"},
        {"email": "ok@example.com", "password": "pw2", "account_type": "plus", "status": "active"},
    ]

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: rows)
    monkeypatch.setattr(
        "autoteam.accounts.find_account",
        lambda items, email: next((account for account in items if account["email"] == email), None),
    )
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)

    def fake_codex_login(email, _acc, *, headless=False):
        if email == "phone@example.com":
            raise CodexOAuthPhoneRequired("https://auth.openai.com/add-phone")
        return {"email": email, "plan": "plus", "auth_file": f"data/auths/{email}.json"}

    monkeypatch.setattr(api, "_run_account_codex_login_once", fake_codex_login)
    monkeypatch.setattr(api, "_remove_oauth_phone_required_accounts_from_pool", lambda emails: list(emails))
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["exclusive"] = kwargs.get("exclusive")
        captured["pass_task_id"] = kwargs.get("pass_task_id")
        captured["result"] = func("task-login-batch")
        return {"task_id": "task-login-batch", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_accounts_login_batch(
        api.AccountEmailBatchParams(emails=["phone@example.com", "ok@example.com"])
    )

    assert [item["email"] for item in captured["result"]["ok"]] == ["ok@example.com"]
    assert captured["exclusive"] is False
    assert captured["pass_task_id"] is True
    assert captured["result"]["phone_required"][0]["email"] == "phone@example.com"
    assert any(progress["stage"] == "account_login_phone_required_removed" for progress in captured["progress"])


def test_gopay_task_runner_removes_rejected_batch_accounts(monkeypatch):
    captured = {"updates": [], "deleted_accounts": [], "deleted_sessions": [], "mail_deleted": []}
    accounts = [
        {"email": "primary@example.com", "cloudmail_account_id": 123},
        {"email": "backup@example.com"},
    ]

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autoteam.accounts.find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    monkeypatch.setattr("autoteam.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs)))
    monkeypatch.setattr("autoteam.accounts.delete_account", lambda email: captured["deleted_accounts"].append(email) or True)
    monkeypatch.setattr("autoteam.auth_session_store.delete_auth_session", lambda email: captured["deleted_sessions"].append(email) or True)
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/account.json")
    monkeypatch.setattr(api, "_update_current_task_progress", lambda _progress: None)
    monkeypatch.setattr("autoteam.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))

    class FakeMailClient:
        def login(self):
            captured["mail_login"] = True

        def delete_account(self, account_id):
            captured["mail_deleted"].append(account_id)
            return {"code": 200}

    monkeypatch.setattr("autoteam.mail.TemporaryEmailClient", FakeMailClient)

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "email_used": "backup@example.com",
            "rejected_emails": ["primary@example.com"],
        }

    monkeypatch.setattr("autoteam.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-791", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="primary@example.com",
            account_emails=["primary@example.com", "backup@example.com"],
            phone_number="+6287761973970",
            country_code="62",
            sms_url="https://it.tgflare.com/api/record?token=demo",
            gopay_pin="558023",
            delete_rejected_accounts=True,
        )
    )

    result = captured["func"]()

    assert result["task_status"] == "completed"
    assert result["removed_pool_emails"] == ["primary@example.com"]
    assert captured["deleted_accounts"] == ["primary@example.com"]
    assert captured["deleted_sessions"] == ["primary@example.com"]
    assert captured["mail_deleted"] == []
    assert captured["updates"][-1][0] == "backup@example.com"
    assert captured["updates"][-1][1]["status"] == accounts_module.STATUS_ACTIVE
    assert captured["updates"][-1][1]["account_type"] == accounts_module.ACCOUNT_TYPE_PLUS
    assert captured["audit"]["removed_pool_emails"] == ["primary@example.com"]


def test_gopay_task_runner_removes_nonzero_blocked_accounts(monkeypatch):
    captured = {"updates": [], "deleted_accounts": [], "deleted_sessions": [], "mail_deleted": []}
    accounts = [
        {"email": "primary@example.com", "cloudmail_account_id": None},
        {"email": "backup@example.com"},
    ]

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autoteam.accounts.find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    monkeypatch.setattr("autoteam.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs)))
    monkeypatch.setattr("autoteam.accounts.delete_account", lambda email: captured["deleted_accounts"].append(email) or True)
    monkeypatch.setattr("autoteam.auth_session_store.delete_auth_session", lambda email: captured["deleted_sessions"].append(email) or True)
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/account.json")
    monkeypatch.setattr(api, "_update_current_task_progress", lambda _progress: None)
    monkeypatch.setattr("autoteam.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))

    class FakeMailClient:
        def login(self):
            captured["mail_login"] = True

        def delete_account(self, account_id):
            captured["mail_deleted"].append(account_id)
            return {"code": 200}

    monkeypatch.setattr("autoteam.mail.TemporaryEmailClient", FakeMailClient)

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "email_used": "backup@example.com",
            "nonzero_blocked_emails": ["primary@example.com"],
        }

    monkeypatch.setattr("autoteam.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-792", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="primary@example.com",
            account_emails=["primary@example.com", "backup@example.com"],
            phone_number="+6287761973970",
            country_code="62",
            sms_url="https://it.tgflare.com/api/record?token=demo",
            gopay_pin="558023",
            delete_rejected_accounts=True,
        )
    )

    result = captured["func"]()

    assert result["task_status"] == "completed"
    assert result["removed_pool_emails"] == ["primary@example.com"]
    assert captured["deleted_accounts"] == ["primary@example.com"]
    assert captured["deleted_sessions"] == ["primary@example.com"]
    assert captured["mail_deleted"] == []
    assert captured["updates"][-1][0] == "backup@example.com"


def test_gopay_task_runner_removes_payment_process_failed_accounts(monkeypatch):
    captured = {"updates": [], "deleted_accounts": [], "deleted_sessions": [], "mail_deleted": []}
    accounts = [
        {"email": "primary@example.com", "cloudmail_account_id": "mail-123"},
        {"email": "backup@example.com"},
    ]

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autoteam.accounts.find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    monkeypatch.setattr("autoteam.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs)))
    monkeypatch.setattr("autoteam.accounts.delete_account", lambda email: captured["deleted_accounts"].append(email) or True)
    monkeypatch.setattr("autoteam.auth_session_store.delete_auth_session", lambda email: captured["deleted_sessions"].append(email) or True)
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/account.json")
    monkeypatch.setattr(api, "_update_current_task_progress", lambda _progress: None)
    monkeypatch.setattr("autoteam.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))

    class FakeMailClient:
        def login(self):
            captured["mail_login"] = True

        def delete_account(self, account_id):
            captured["mail_deleted"].append(account_id)
            return {"code": 200}

    monkeypatch.setattr("autoteam.mail.TemporaryEmailClient", FakeMailClient)

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "email_used": "backup@example.com",
            "payment_failed_emails": ["primary@example.com"],
        }

    monkeypatch.setattr("autoteam.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-793", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="primary@example.com",
            account_emails=["primary@example.com", "backup@example.com"],
            phone_number="+6287761973970",
            country_code="62",
            sms_url="https://it.tgflare.com/api/record?token=demo",
            gopay_pin="558023",
            delete_rejected_accounts=True,
        )
    )

    result = captured["func"]()

    assert result["task_status"] == "completed"
    assert result["removed_pool_emails"] == ["primary@example.com"]
    assert captured["deleted_accounts"] == ["primary@example.com"]
    assert captured["deleted_sessions"] == ["primary@example.com"]
    assert captured["mail_deleted"] == []
    assert captured["updates"][-1][0] == "backup@example.com"
    assert captured["audit"]["removed_pool_emails"] == ["primary@example.com"]


def test_gopay_task_runner_marks_token_invalidated_accounts_fail(monkeypatch):
    captured = {"updates": [], "deleted_accounts": [], "deleted_sessions": []}
    accounts = [
        {"email": "primary@example.com", "cloudmail_account_id": "mail-123"},
        {"email": "backup@example.com"},
    ]

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autoteam.accounts.find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    monkeypatch.setattr("autoteam.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs)))
    monkeypatch.setattr("autoteam.accounts.delete_account", lambda email: captured["deleted_accounts"].append(email) or True)
    monkeypatch.setattr("autoteam.auth_session_store.delete_auth_session", lambda email: captured["deleted_sessions"].append(email) or True)
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/account.json")
    monkeypatch.setattr(api, "_update_current_task_progress", lambda _progress: None)
    monkeypatch.setattr("autoteam.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "success",
            "message": "GoPay 批量绑定完成: 成功 1/2 个账号",
            "email_used": "backup@example.com",
            "successful_emails": ["backup@example.com"],
            "failed_emails": ["primary@example.com"],
            "token_invalidated_emails": ["primary@example.com"],
        }

    monkeypatch.setattr("autoteam.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-794", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="primary@example.com",
            account_emails=["primary@example.com", "backup@example.com"],
            phone_number="+6287761973970",
            country_code="62",
            sms_url="https://it.tgflare.com/api/record?token=demo",
            gopay_pin="558023",
            delete_rejected_accounts=False,
        )
    )

    result = captured["func"]()

    assert result["task_status"] == "completed"
    assert result["token_invalidated_pool_emails"] == ["primary@example.com"]
    assert result["token_invalidated_failed_emails"] == ["primary@example.com"]
    assert result.get("removed_pool_emails", []) == []
    assert captured["deleted_accounts"] == []
    assert captured["deleted_sessions"] == []
    failed_updates = [item for item in captured["updates"] if item[0] == "primary@example.com"]
    assert failed_updates
    assert failed_updates[-1][1]["status"] == accounts_module.STATUS_FAIL
    assert failed_updates[-1][1]["discarded_reason"] == "gopay_token_invalidated"
    assert captured["audit"]["removed_pool_emails"] == []


def test_gopay_task_runner_refreshes_auth_session_before_retry(monkeypatch):
    captured = {"updates": [], "progress": []}
    accounts = [
        {"email": "primary@example.com", "password": "pw", "cloudmail_account_id": "mail-123"},
        {"email": "backup@example.com"},
    ]

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autoteam.accounts.find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    monkeypatch.setattr("autoteam.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs)))
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/account.json")
    monkeypatch.setattr(api, "_update_current_task_progress", lambda _progress: None)
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autoteam.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        refresh_result = kwargs["auth_session_refresh_callback"](
            "primary@example.com",
            {"failure_stage": "post_submit", "message": "token_invalidated"},
        )
        captured["refresh_result"] = refresh_result
        return {
            "status": "success",
            "message": "GoPay 批量绑定完成: 成功 1/1 个账号",
            "email_used": "primary@example.com",
            "successful_emails": ["primary@example.com"],
            "token_invalidated_emails": ["primary@example.com"],
            "auth_session_refresh_failed_emails": ["primary@example.com"],
        }

    monkeypatch.setattr("autoteam.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-795", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="primary@example.com",
            account_emails=["primary@example.com"],
            phone_number="+6287761973970",
            country_code="62",
            sms_url="https://it.tgflare.com/api/record?token=demo",
            gopay_pin="558023",
        )
    )

    result = captured["func"]()

    assert result["task_status"] == "completed"
    assert captured["refresh_result"]["status"] == "failed"
    assert "access token 已失效" in captured["refresh_result"]["message"]
    fail_updates = [item for item in captured["updates"] if item[0] == "primary@example.com"]
    assert fail_updates
    assert fail_updates[-1][1]["status"] == accounts_module.STATUS_FAIL
    assert fail_updates[-1][1]["discarded_reason"] == "gopay_token_invalidated"
    assert any(progress["stage"] == "gopay_auth_session_refresh_failed" for progress in captured["progress"])


def test_post_gopay_bind_task_requires_phone(monkeypatch):
    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr("autoteam.accounts.find_account", lambda accounts, email: accounts[0])
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")

    with pytest.raises(api.HTTPException) as exc:
        api.post_gopay_bind_task(
            api.GoPayBindTaskParams(
                email="user@example.com",
                phone_number="",
                sms_url="https://it.tgflare.com/api/record?token=demo",
                gopay_pin="558023",
            )
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "phone_number 不能为空"
