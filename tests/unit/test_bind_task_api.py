import base64
import json
import threading

import pytest

from autoteam import api
from autoteam import accounts as accounts_module
from autoteam import gopay_executor


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
    monkeypatch.setattr("autoteam.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))
    monkeypatch.setattr("autoteam.accounts.update_account", lambda email, **kwargs: captured.setdefault("updates", []).append((email, kwargs)))

    class FakeMailClient:
        def login(self):
            captured["mail_login"] += 1

    monkeypatch.setattr("autoteam.mail.TemporaryEmailClient", FakeMailClient)

    def fake_register(mail_client, **kwargs):
        captured["register_kwargs"] = kwargs
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
            phone_number="+6287761973970",
            country_code="62",
            sms_url="https://it.tgflare.com/api/record?token=demo",
            gopay_pin="558023",
        )
    )

    assert result["task_id"] == "task-auto"
    assert captured["params"]["auto_register"] is True
    assert captured["params"]["auto_register_count"] == 1

    task_result = captured["func"]()

    assert captured["mail_login"] == 1
    assert captured["register_kwargs"]["domain"] == "openaibus.com"
    assert captured["register_kwargs"]["skip_post_register"] is True
    assert captured["register_kwargs"]["post_register_oauth"] is False
    assert captured["register_kwargs"]["check_team_membership"] is False
    assert captured["run_kwargs"]["email"] == "new@example.com"
    assert captured["run_kwargs"]["account_emails"] == []
    assert task_result["status"] == "success"
    assert task_result["email"] == "new@example.com"
    assert captured["audit"]["email"] == "new@example.com"


def test_gopay_task_runner_auto_register_count_registers_and_binds_sequentially(monkeypatch):
    captured = {"mail_login": 0, "register_kwargs": [], "run_emails": []}
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
    monkeypatch.setattr("autoteam.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))
    monkeypatch.setattr("autoteam.accounts.update_account", lambda email, **kwargs: captured.setdefault("updates", []).append((email, kwargs)))

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
            phone_number="+6287761973970",
            country_code="62",
            sms_url="https://it.tgflare.com/api/record?token=demo",
            gopay_pin="558023",
        )
    )

    assert result["task_id"] == "task-auto-count"
    assert captured["params"]["auto_register_count"] == 2

    task_result = captured["func"]()

    assert captured["mail_login"] == 2
    assert len(captured["register_kwargs"]) == 2
    assert all(kwargs["domain"] == "openaibus.com" for kwargs in captured["register_kwargs"])
    assert captured["run_emails"] == registered_emails
    assert task_result["status"] == "success"
    assert task_result["successful_emails"] == registered_emails
    assert task_result["auto_register_count"] == 2
    assert task_result["auto_register_attempted"] == 2
    assert "成功 2/2" in task_result["message"]
    updated_emails = [email for email, _kwargs in captured["updates"]]
    assert updated_emails == registered_emails


def test_gopay_params_accept_camel_case_auto_register_payload():
    params = api.GoPayBindTaskParams.model_validate(
        {
            "autoRegister": True,
            "autoRegisterCount": 2,
            "phone_number": "+6287761973970",
            "country_code": "62",
            "sms_url": "https://it.tgflare.com/api/record?token=demo",
            "gopay_pin": "558023",
        }
    )

    assert params.email == ""
    assert params.auto_register is True
    assert params.auto_register_count == 2


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


def test_run_gopay_bind_task_rotates_on_gopay_wallet_payment_process_failure(monkeypatch):
    calls = []
    progress_events = []

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
    assert result["payment_failed_emails"] == ["first@example.com"]
    assert any(event["stage"] == "gopay_payment_process_failed_rotate" for event in progress_events)


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
        captured["oauth_calls"].append((email, acc))
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
    assert sorted(email for email, _acc in captured["oauth_calls"]) == ["first@example.com", "second@example.com"]
    stages = [progress["stage"] for progress in captured["progress"]]
    assert stages.count("gopay_oauth_login_started") == 2
    assert stages.count("gopay_oauth_login_done") == 2
    assert all(update["account_type"] == accounts_module.ACCOUNT_TYPE_PLUS for _email, update in captured["updates"])


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


def test_post_accounts_login_batch_starts_single_background_task(monkeypatch):
    captured = {"progress": []}
    rows = [
        {"email": "first@example.com", "password": "pw1", "account_type": "free", "status": "active"},
        {"email": "second@example.com", "password": "pw2", "account_type": "plus", "status": "active"},
    ]

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
        api.AccountEmailBatchParams(emails=["FIRST@example.com", "second@example.com"])
    )

    assert result["task_id"] == "task-login-batch"
    assert captured["command"] == "login-batch"
    assert captured["exclusive"] is False
    assert captured["pass_task_id"] is True
    assert captured["params"]["emails"] == ["first@example.com", "second@example.com"]
    assert captured["result"]["total"] == 2
    assert sorted(item["email"] for item in captured["result"]["ok"]) == ["first@example.com", "second@example.com"]
    assert any(progress["message"] == "补登录成功: second@example.com" for progress in captured["progress"])


def test_post_account_login_removes_account_when_oauth_requires_phone(monkeypatch):
    from autoteam.codex_auth import CodexOAuthPhoneRequired

    captured = {"progress": []}
    account = {"email": "phone@example.com", "password": "pw", "account_type": "free", "status": "active"}

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autoteam.accounts.find_account", lambda items, email: account if email == account["email"] else None)
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)
    monkeypatch.setattr(api, "_run_account_codex_login_once", lambda *_args, **_kwargs: (_ for _ in ()).throw(CodexOAuthPhoneRequired("https://auth.openai.com/add-phone")))
    monkeypatch.setattr(api, "_remove_oauth_phone_required_accounts_from_pool", lambda emails: captured.setdefault("removed", list(emails)))
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
    monkeypatch.setattr(api, "_remove_oauth_phone_required_accounts_from_pool", lambda emails: captured.setdefault("removed", list(emails)))
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
