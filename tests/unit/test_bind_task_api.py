import pytest

from autoteam import api
from autoteam import accounts as accounts_module


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
    assert captured["deleted_accounts"] == ["user@example.com"]
    assert captured["deleted_sessions"] == ["user@example.com"]
    assert captured["run_kwargs"]["country_code"] == "62"
    assert progress_updates[-1]["stage"] == "failed"


def test_gopay_task_runner_marks_success_account_plus(monkeypatch):
    captured = {"updates": []}

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr("autoteam.accounts.find_account", lambda accounts, email: accounts[0] if email == "user@example.com" else None)
    monkeypatch.setattr("autoteam.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs)))
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_update_current_task_progress", lambda _progress: None)
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
    assert update["status"] == accounts_module.STATUS_PLUS
    assert update["plus_bound_at"] == update["last_bind_at"]
    assert update["last_bind_status"] == "success"
    assert captured["audit"]["task_status"] == "completed"


def test_gopay_task_runner_removes_rejected_batch_accounts(monkeypatch):
    captured = {"updates": [], "deleted_accounts": [], "deleted_sessions": []}
    accounts = [{"email": "primary@example.com"}, {"email": "backup@example.com"}]

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
        )
    )

    result = captured["func"]()

    assert result["task_status"] == "completed"
    assert result["removed_pool_emails"] == ["primary@example.com"]
    assert captured["deleted_accounts"] == ["primary@example.com"]
    assert captured["deleted_sessions"] == ["primary@example.com"]
    assert captured["updates"][-1][0] == "backup@example.com"
    assert captured["updates"][-1][1]["status"] == accounts_module.STATUS_PLUS
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
