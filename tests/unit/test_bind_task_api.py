import base64
import json
import threading
from pathlib import Path

import pytest

from autotoken import accounts as accounts_module
from autotoken import api, gopay_auto_register, gopay_executor
from autotoken.api_routes.roxybrowser_config import build_roxybrowser_config_response
from autotoken.api_routes.trade import TradeHistoryDownloadParams, TradeQueryParams


@pytest.fixture(autouse=True)
def _clear_gopay_reusable_wallet_pool(monkeypatch):
    monkeypatch.setattr(api, "_gopay_auto_signup_no_transfer_bind_wait_seconds", lambda: 0)
    monkeypatch.setattr(
        api,
        "_gopay_auto_signup_env",
        lambda: {
            "provider": "smscloud",
            "smscloud_xi_token": "",
            "hero_sms_api_key": "",
            "hero_sms_max_price": "",
            "proxy_url": "",
            "country_code": "+62",
            "signup_mode": "http",
            "appium_url": "http://127.0.0.1:4723",
            "appium_adb_serial": "",
        },
    )
    with api._task_runtime_controls_lock:
        api._task_runtime_controls.clear()
    with api._task_cancel_hooks_lock:
        api._task_cancel_hooks.clear()
    api._task_cancel_signals.clear()
    api._task_skip_signals.clear()
    api._current_task_ids.clear()
    api._current_task_id = None
    with api._GOPAY_REUSABLE_WALLET_POOL_LOCK:
        api._GOPAY_REUSABLE_WALLET_POOL.clear()
    yield
    with api._task_runtime_controls_lock:
        api._task_runtime_controls.clear()
    with api._task_cancel_hooks_lock:
        api._task_cancel_hooks.clear()
    api._task_cancel_signals.clear()
    api._task_skip_signals.clear()
    api._current_task_ids.clear()
    api._current_task_id = None
    with api._GOPAY_REUSABLE_WALLET_POOL_LOCK:
        api._GOPAY_REUSABLE_WALLET_POOL.clear()


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

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.accounts.delete_account", lambda email: email == "dead@example.com")
    monkeypatch.setattr("autotoken.auth_session_store.delete_auth_session", lambda email: email == "dead@example.com")
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
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [])
    monkeypatch.setattr(
        "autotoken.auth_session_store.get_auth_session_file",
        lambda email: "data/auth_session/ghost@example_com.json" if email == "ghost@example.com" else "",
    )
    monkeypatch.setattr(
        "autotoken.auth_session_store.delete_auth_session",
        lambda email: captured["deleted_sessions"].append(email) or True,
    )

    def fake_delete_managed_account(email, **kwargs):
        captured["managed"].append((email, kwargs))
        return {"local_record": False, "local_auth_files": [], "cpa_files": []}

    monkeypatch.setattr("autotoken.account_ops.delete_managed_account", fake_delete_managed_account)

    result = _account_management_delete_accounts_batch(["ghost@example.com"], continue_on_error=True)

    assert result["summary"]["ok"] == 1
    assert result["results"][0]["ok"] is True
    assert result["results"][0]["cleanup"]["auth_session_deleted"] is True
    assert captured["deleted_sessions"] == ["ghost@example.com"]
    assert captured["managed"][0][0] == "ghost@example.com"


def test_delete_accounts_batch_reports_missing_only_when_no_record_or_session(monkeypatch):
    monkeypatch.setattr(api, "_playwright_lock", FakeUnlockedLock())
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [])
    monkeypatch.setattr("autotoken.auth_session_store.get_auth_session_file", lambda _email: "")

    result = _account_management_delete_accounts_batch(["missing@example.com"], continue_on_error=True)

    assert result["summary"]["ok"] == 0
    assert result["results"] == [{"email": "missing@example.com", "ok": False, "error": "账号不存在"}]


def test_update_accounts_export_status_marks_selected_accounts(monkeypatch):
    saved = {}
    existing = [
        {"email": "first@example.com", "credentials_exported": False},
        {"email": "second@example.com", "credentials_exported": False},
    ]

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: existing)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda rows, email: next((acc for acc in rows if acc["email"] == email), None),
    )
    monkeypatch.setattr(api, "_is_main_account_email", lambda email: email == "owner@example.com")
    monkeypatch.setattr(
        "autotoken.trade.clear_trade_allocations_for_emails",
        lambda _emails: (_ for _ in ()).throw(AssertionError("should not clear allocations")),
    )

    def fake_update_account(email, **kwargs):
        saved[email] = kwargs
        return {"email": email, **kwargs}

    monkeypatch.setattr("autotoken.accounts.update_account", fake_update_account)

    result = _update_accounts_export_status(
        emails=["first@example.com", "first@example.com", "owner@example.com", "missing@example.com"],
        exported=True,
    )

    assert result["updated"] == 1
    assert result["exported"] is True
    assert result["missing"] == ["owner@example.com", "missing@example.com"]
    assert saved["first@example.com"]["credentials_exported"] is True
    assert isinstance(saved["first@example.com"]["credentials_exported_at"], float)


def test_update_accounts_export_status_can_clear_export_flag(monkeypatch):
    account = {"email": "first@example.com", "credentials_exported": True, "credentials_exported_at": 123.0}
    captured = {}
    cleared = {}

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda rows, email: account if email == "first@example.com" else None
    )
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)

    def fake_update_account(email, **kwargs):
        captured[email] = kwargs
        return {"email": email, **kwargs}

    monkeypatch.setattr("autotoken.accounts.update_account", fake_update_account)

    def fake_clear_trade_allocations(emails):
        cleared["emails"] = emails
        return {"cleared": len(emails), "codes": ["PLUS-ABCDEF123456"]}

    monkeypatch.setattr("autotoken.trade.clear_trade_allocations_for_emails", fake_clear_trade_allocations)

    result = _update_accounts_export_status(emails=["first@example.com"], exported=False)

    assert result["updated"] == 1
    assert result["exported"] is False
    assert result["trade_allocations"] == {"cleared": 1, "codes": ["PLUS-ABCDEF123456"]}
    assert cleared["emails"] == ["first@example.com"]
    assert captured["first@example.com"] == {
        "credentials_exported": False,
        "credentials_exported_at": None,
    }


def test_post_bind_card_task_starts_background_task(monkeypatch):
    captured = {}

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: accounts[0] if email == "user@example.com" else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr("autotoken.card_pool.find_item", lambda pool_type, item_id: {"id": item_id, "status": "unused"})

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
        "bind_link_payload": {},
        "proxy_url": "socks5://host:1080",
        "proxy_label": "res-us-01",
        "proxy_api_provider": "",
        "proxy_api_url": "",
        "proxy_api_country": "US",
        "proxy_bypass": None,
        "payment_flow": "playwright",
        "roxybrowser_workspace_id": "",
        "roxybrowser_profile_id": "",
        "roxybrowser_auto_create_profile": True,
        "manual_confirm": True,
        "timeout_seconds": 900,
    }


def test_post_bind_card_task_requires_existing_account(monkeypatch):
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda accounts, email: None)

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
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda accounts, email: accounts[0])
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(
        "autotoken.card_pool.find_item", lambda pool_type, item_id: {"id": item_id, "status": "binding"}
    )

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


def test_post_paypal_task_starts_manual_checkout_task(monkeypatch):
    captured = {}

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: accounts[0] if email == "user@example.com" else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["command"] = command
        captured["func"] = func
        captured["params"] = params
        captured["kwargs"] = kwargs
        return {"task_id": "task-paypal", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    result = api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="user@example.com",
            checkout_url="https://pay.openai.com/demo",
            proxy_url="socks5://host:1080",
            proxy_label="res-us-01",
            manual_confirm=False,
            paypal_email="paypal@example.com",
            paypal_password="secret-pass",
            autofill_enabled=True,
            billing_name="James Smith",
            billing_phone="1234567890",
            billing_country="US",
            billing_state="NY",
            billing_city="New York",
            billing_zip="10001",
            billing_address1="123 Main St",
            billing_address2="Apt 1",
            timeout_seconds=900,
            pending_retry_attempts=5,
            paypal_concurrency=5,
        )
    )

    assert result["task_id"] == "task-paypal"
    assert captured["command"] == "paypal"
    assert captured["params"] == {
        "runner_mode": "manual_checkout",
        "email": "user@example.com",
        "account_emails": [],
        "checkout_url": "https://pay.openai.com/demo",
        "bind_link_payload": {},
        "proxy_url": "socks5://host:1080",
        "proxy_pool_count": 0,
        "proxy_api_url_present": False,
        "proxy_label": "res-us-01",
        "proxy_bypass": None,
        "manual_confirm": False,
        "paypal_browser": "chromium",
        "paypal_mode": "existing_account",
        "paypal_country": "US",
        "paypal_lang": "en",
        "paypal_email": "paypal@example.com",
        "sms_url_present": False,
        "otp_channel": "sms",
        "phone_account_count": 0,
        "paypal_direct_ba_link_present": False,
        "paypal_direct_ba_checkout_reference_present": False,
        "paypal_card_number_present": False,
        "paypal_card_expiry_present": False,
        "paypal_card_cvv_present": False,
        "paypal_auto_login": True,
        "autofill_enabled": True,
        "billing_name": "James Smith",
        "billing_email": "",
        "billing_phone": "1234567890",
        "billing_country": "US",
        "billing_state": "NY",
        "billing_city": "New York",
        "billing_zip": "10001",
        "billing_address1": "123 Main St",
        "billing_address2": "Apt 1",
        "timeout_seconds": 900,
        "auto_oauth_after_success": False,
        "pending_retry_attempts": 3,
        "paypal_concurrency": 3,
        "roxybrowser_workspace_id": "",
        "roxybrowser_profile_id": "",
        "roxybrowser_auto_create_profile": False,
    }
    assert "pass_task_id" not in captured["kwargs"]


def test_post_paypal_task_requires_checkout_url(monkeypatch):
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: accounts[0] if email == "user@example.com" else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")

    with pytest.raises(api.HTTPException) as exc:
        api.post_paypal_task(
            api.PayPalTaskParams(
                runner_mode="manual_checkout",
                email="user@example.com",
                checkout_url="",
            )
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "checkout_url 不能为空，或提供 bind_link_payload 用于自动生成链接"


def test_post_paypal_task_auto_mode_requires_paypal_credentials(monkeypatch):
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: accounts[0] if email == "user@example.com" else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")

    with pytest.raises(api.HTTPException) as exc:
        api.post_paypal_task(
            api.PayPalTaskParams(
                runner_mode="manual_checkout",
                email="user@example.com",
                checkout_url="https://pay.openai.com/demo",
                manual_confirm=False,
                paypal_email="paypal@example.com",
            )
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "已有账号模式需要 paypal_password"


def test_post_paypal_task_accepts_create_account_mode(monkeypatch):
    captured = {}

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: accounts[0] if email == "user@example.com" else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["command"] = command
        captured["params"] = params
        return {"task_id": "task-paypal-signup", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    result = api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="user@example.com",
            checkout_url="https://pay.openai.com/demo",
            manual_confirm=False,
            paypal_mode="create_account",
            autofill_enabled=True,
            billing_name="James Smith",
            billing_phone="+13105550100",
            sms_url="https://sms.example.test/token=demo",
            paypal_card_number="4111111111111111",
            paypal_card_expiry="03/30",
            paypal_card_cvv="996",
        )
    )

    assert result["task_id"] == "task-paypal-signup"
    assert captured["command"] == "paypal"
    assert captured["params"]["paypal_mode"] == "create_account"
    assert captured["params"]["sms_url_present"] is True
    assert captured["params"]["paypal_card_number_present"] is True
    assert captured["params"]["paypal_card_expiry_present"] is True
    assert captured["params"]["paypal_card_cvv_present"] is True
    assert captured["params"]["paypal_auto_login"] is False


def test_post_paypal_task_create_account_mode_requires_sms_and_card(monkeypatch):
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: accounts[0] if email == "user@example.com" else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")

    with pytest.raises(api.HTTPException) as exc:
        api.post_paypal_task(
            api.PayPalTaskParams(
                runner_mode="manual_checkout",
                email="user@example.com",
                checkout_url="https://pay.openai.com/demo",
                manual_confirm=False,
                paypal_mode="create_account",
                autofill_enabled=True,
                billing_phone="+13105550100",
            )
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "自动注册模式需要 sms_url"

    with pytest.raises(api.HTTPException) as exc:
        api.post_paypal_task(
            api.PayPalTaskParams(
                runner_mode="manual_checkout",
                email="user@example.com",
                checkout_url="https://pay.openai.com/demo",
                manual_confirm=False,
                paypal_mode="create_account",
                billing_phone="+13105550100",
                sms_url="https://sms.example.test/token=demo",
                billing_name="James Smith",
                billing_country="US",
                billing_state="CA",
                billing_city="Los Angeles",
                billing_zip="90001",
                billing_address1="742 Evergreen Terrace",
            )
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "自动注册模式需要 paypal_card_number"


def test_post_paypal_task_create_account_autofill_allows_generator_card(monkeypatch):
    captured = {}

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: accounts[0] if email == "user@example.com" else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"command": command, "params": params})
            or {"task_id": "task-paypal-autofill-card", "command": command, "params": params}
        ),
    )

    result = api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="user@example.com",
            checkout_url="https://pay.openai.com/demo",
            manual_confirm=False,
            paypal_mode="create_account",
            billing_phone="+13105550100",
            sms_url="https://sms.example.test/token=demo",
            autofill_enabled=True,
        )
    )

    assert result["task_id"] == "task-paypal-autofill-card"


def test_post_paypal_task_protocol_jp_create_account_allows_no_card(monkeypatch):
    captured = {}

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: accounts[0] if email == "user@example.com" else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"command": command, "params": params})
            or {"task_id": "task-paypal-jp-nocard", "command": command, "params": params}
        ),
    )

    result = api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="user@example.com",
            checkout_url="https://pay.openai.com/demo",
            manual_confirm=False,
            paypal_mode="create_account",
            paypal_browser="protocol",
            paypal_fallback_browser="roxybrowser",
            paypal_country="JP",
            paypal_lang="ja",
            billing_name="James Smith",
            billing_phone="+819012345678",
            billing_country="JP",
            billing_state="Tokyo",
            billing_city="Chiyoda",
            billing_zip="100-0001",
            billing_address1="1-1 Chiyoda",
            sms_url="https://sms.example.test/token=demo",
            autofill_enabled=False,
        )
    )

    assert result["task_id"] == "task-paypal-jp-nocard"
    assert captured["command"] == "paypal"
    assert captured["params"]["paypal_browser"] == "protocol"
    assert captured["params"]["paypal_country"] == "JP"
    assert captured["params"]["paypal_lang"] == "ja"
    assert captured["params"]["paypal_card_number_present"] is False
    assert captured["params"]["autofill_enabled"] is False
    assert captured["params"]["paypal_card_number_present"] is False


def test_post_paypal_task_protocol_auto_provisions_sms_from_env(monkeypatch):
    captured = {}

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: accounts[0] if email == "user@example.com" else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(
        api.paypal_phone_pool_service,
        "paypal_sms_auto_provision_enabled",
        lambda **kwargs: kwargs["paypal_mode"] == "create_account" and kwargs["protocol_no_card"],
    )
    monkeypatch.setattr(
        api.paypal_phone_pool_service,
        "provision_paypal_phone_account_from_env",
        lambda **_kwargs: {
            "phone_number": "+819012345678",
            "sms_url": "http://127.0.0.1:8787/otp/gopay-signup/bridge-token",
            "otp_channel": "sms",
            "sms_provider": "hero_sms",
            "activation_id": "activation-1",
            "bridge_token": "bridge-token",
        },
    )
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"command": command, "params": params})
            or {"task_id": "task-paypal-auto-sms", "command": command, "params": params}
        ),
    )

    result = api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="user@example.com",
            checkout_url="https://pay.openai.com/demo",
            manual_confirm=False,
            paypal_mode="create_account",
            paypal_browser="protocol",
            paypal_fallback_browser="roxybrowser",
            paypal_country="JP",
            paypal_lang="ja",
            billing_name="James Smith",
            billing_country="JP",
            billing_state="Tokyo",
            billing_city="Chiyoda",
            billing_zip="100-0001",
            billing_address1="1-1 Chiyoda",
            autofill_enabled=False,
        )
    )

    assert result["task_id"] == "task-paypal-auto-sms"
    assert captured["command"] == "paypal"
    assert captured["params"]["phone_account_count"] == 1
    assert captured["params"]["phone_accounts"] == [
        {
            "phone_number": "+819012345678",
            "sms_url_present": True,
            "otp_channel": "sms",
        }
    ]
    assert captured["params"]["sms_url_present"] is True
    assert captured["params"]["paypal_sms_auto_provisioned"] is True
    assert captured["params"]["paypal_sms_provider"] == "hero_sms"
    assert "bridge-token" not in str(captured["params"])
    assert "activation-1" not in str(captured["params"])


def test_post_paypal_task_protocol_uses_explicit_paypal_sms_env(monkeypatch):
    captured = {}

    monkeypatch.setenv("PAYPAL_SMS_URL", "https://sms.example/token")
    monkeypatch.setenv("PAYPAL_PHONE_NUMBER", "+819012345678")
    monkeypatch.delenv("PAYPAL_SMS_PROVIDER", raising=False)
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: accounts[0] if email == "user@example.com" else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(
        api.paypal_phone_pool_service,
        "provision_paypal_phone_account_from_env",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("explicit env must not buy a phone")),
    )
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"command": command, "params": params})
            or {"task_id": "task-paypal-explicit-sms-env", "command": command, "params": params}
        ),
    )

    result = api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="user@example.com",
            checkout_url="https://pay.openai.com/demo",
            manual_confirm=False,
            paypal_mode="create_account",
            paypal_browser="protocol",
            paypal_fallback_browser="roxybrowser",
            paypal_country="JP",
            paypal_lang="ja",
            billing_name="James Smith",
            billing_country="JP",
            billing_state="Tokyo",
            billing_city="Chiyoda",
            billing_zip="100-0001",
            billing_address1="1-1 Chiyoda",
            autofill_enabled=False,
        )
    )

    assert result["task_id"] == "task-paypal-explicit-sms-env"
    assert captured["params"]["sms_url_present"] is True
    assert captured["params"]["phone_account_count"] == 1
    assert captured["params"]["phone_accounts"] == [
        {
            "phone_number": "+819012345678",
            "sms_url_present": True,
            "otp_channel": "sms",
        }
    ]
    assert captured["params"]["billing_phone"] == "+819012345678"
    assert "https://sms.example/token" not in str(captured["params"])


def test_post_paypal_task_protocol_auto_provisioned_sms_bridge_closed_after_success(monkeypatch):
    captured = {"progress": []}
    closed = []
    accounts = [{"email": "user@example.com"}]

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda rows, email: accounts[0] if email == "user@example.com" else None
    )
    monkeypatch.setattr("autotoken.storage.accounts.update_account", lambda email, **kwargs: {"email": email, **kwargs})
    monkeypatch.setattr("autotoken.storage.accounts.add_account", lambda *args, **kwargs: None)
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda _payload: None)
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_extract_account_access_token", lambda email: f"token-{email}")
    monkeypatch.setattr(
        "autotoken.services.paypal_proxy.paypal_proxy_exit_location",
        lambda *_args, **_kwargs: {"country_code": "JP", "region": "Tokyo", "city": "Tokyo", "ip": "198.51.100.8"},
    )
    monkeypatch.setattr(
        api.paypal_phone_pool_service,
        "paypal_sms_auto_provision_enabled",
        lambda **kwargs: kwargs["paypal_mode"] == "create_account" and kwargs["protocol_no_card"],
    )
    monkeypatch.setattr(
        api.paypal_phone_pool_service,
        "provision_paypal_phone_account_from_env",
        lambda **_kwargs: {
            "phone_number": "+819012345678",
            "sms_url": "http://127.0.0.1:8787/otp/gopay-signup/bridge-token",
            "otp_channel": "sms",
            "sms_provider": "hero_sms",
            "bridge_token": "bridge-token",
        },
    )
    monkeypatch.setattr(
        api.paypal_phone_pool_service,
        "close_paypal_sms_bridges",
        lambda phone_accounts, *, success: closed.append((phone_accounts, success)),
    )
    monkeypatch.setattr(
        "autotoken.paypal_bind_executor._extract_auth_session_context",
        lambda _email: {"access_token": "extract-token"},
    )
    monkeypatch.setattr(
        "autotoken.paypal_bind_executor._paypal_extract_ba_link",
        lambda **_kwargs: {
            "status": "success",
            "ba_token": "BA-TEST",
            "approve_url": "https://www.paypal.com/agreements/approve?ba_token=BA-TEST",
            "checkout_url": "https://pay.openai.com/c/pay/cs_demo#hash",
            "checkout_session_id": "cs_demo",
        },
    )
    monkeypatch.setattr(
        "autotoken.paypal_bind_executor.run_paypal_bind_task",
        lambda **kwargs: {
            "status": "success",
            "failure_stage": "",
            "message": "PayPal 绑定完成",
            "checkout_url": kwargs["checkout_url"],
            "return_url": "https://chatgpt.com/checkout/verify?stripe_session_id=cs_demo",
            "paypal_user_id": "paypal-user",
        },
    )
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"func": func, "params": params})
            or {"task_id": "task-paypal-auto-sms-close", "command": command, "params": params}
        ),
    )

    api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="user@example.com",
            checkout_url="https://pay.openai.com/demo",
            manual_confirm=False,
            paypal_mode="create_account",
            paypal_browser="protocol",
            paypal_country="JP",
            paypal_lang="ja",
            paypal_jp_proxy_url="socks5://jp.example.test:1080",
            autofill_enabled=True,
        )
    )
    result = captured["func"]()

    assert result["status"] == "success"
    assert closed == [
        (
            [
                {
                    "phone_number": "+819012345678",
                    "sms_url": "http://127.0.0.1:8787/otp/gopay-signup/bridge-token",
                    "otp_channel": "sms",
                    "bridge_token": "bridge-token",
                    "sms_provider": "hero_sms",
                }
            ],
            True,
        )
    ]


def test_post_paypal_task_passes_gb_mode_to_proxy_runtime(monkeypatch):
    captured = {}
    real_prepare = api.paypal_proxy_service.prepare_paypal_proxy_runtime

    def capture_prepare(**kwargs):
        captured.update(kwargs)
        return real_prepare(**kwargs)

    monkeypatch.setattr(api.paypal_proxy_service, "prepare_paypal_proxy_runtime", capture_prepare)
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: {
            "task_id": "task-paypal-gb-runtime",
            "command": command,
            "params": params,
        },
    )

    api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="user@example.com",
            bind_link_payload={"plan_name": "chatgptplusplan"},
            paypal_mode="create_account",
            paypal_browser="protocol",
            paypal_country="JP",
            paypal_ba_mode="gb",
            paypal_jp_proxy_url=(
                "socks5://user-region-JP-sid-base-t-120:pass@proxy.example:3010"
            ),
            billing_phone="+819012345678",
            sms_url="https://sms.example.test/token=demo",
            manual_confirm=False,
            autofill_enabled=True,
        )
    )

    assert captured["paypal_ba_mode"] == "gb"


def test_post_paypal_task_protocol_uses_direct_ba_link_without_checkout_generation(monkeypatch):
    captured = {"progress": []}
    accounts = [{"email": "user@example.com"}]

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda rows, email: accounts[0] if email == "user@example.com" else None
    )
    monkeypatch.setattr("autotoken.storage.accounts.update_account", lambda email, **kwargs: {"email": email, **kwargs})
    monkeypatch.setattr("autotoken.storage.accounts.add_account", lambda *args, **kwargs: None)
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda _payload: None)
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(
        api,
        "_extract_account_access_token",
        lambda _email: (_ for _ in ()).throw(AssertionError("direct BA mode should not load access token")),
    )
    monkeypatch.setattr(
        "autotoken.paypal_bind_executor._paypal_extract_ba_link",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("direct BA mode should not extract BA link")),
    )

    def fake_run_paypal_bind_task(**kwargs):
        captured["bind_kwargs"] = kwargs
        return {
            "status": "success",
            "failure_stage": "",
            "message": "PayPal 绑定完成",
            "checkout_url": kwargs["checkout_url"],
            "return_url": "https://chatgpt.com/checkout/verify?stripe_session_id=cs_direct",
            "paypal_user_id": "paypal-user",
        }

    monkeypatch.setattr("autotoken.paypal_bind_executor.run_paypal_bind_task", fake_run_paypal_bind_task)
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"func": func, "params": params})
            or {"task_id": "task-paypal-direct-ba", "command": command, "params": params}
        ),
    )

    api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="user@example.com",
            checkout_url="",
            manual_confirm=False,
            paypal_mode="create_account",
            paypal_browser="protocol",
            paypal_fallback_browser="roxybrowser",
            paypal_country="JP",
            paypal_lang="ja",
            autofill_enabled=True,
            billing_phone="+819012345678",
            sms_url="https://sms.example/token",
            paypal_approve_url="https://www.paypal.com/pay?token=BA-DIRECT123",
            paypal_checkout_session_id="cs_direct",
            paypal_payment_method_id="pm_direct",
        )
    )
    result = captured["func"]()

    assert result["status"] == "success"
    assert captured["params"]["checkout_url"] == ""
    assert captured["params"].get("paypal_fallback_browser", "") == "roxybrowser"
    assert captured["params"]["paypal_direct_ba_link_present"] is True
    assert captured["params"]["paypal_direct_ba_checkout_reference_present"] is True
    assert captured["bind_kwargs"]["checkout_url"] == ""
    assert captured["bind_kwargs"]["paypal_fallback_browser"] == "roxybrowser"
    assert captured["bind_kwargs"]["pre_extracted"] == {
        "status": "success",
        "ba_token": "BA-DIRECT123",
        "approve_url": "https://www.paypal.com/pay?token=BA-DIRECT123",
        "checkout_session_id": "cs_direct",
        "checkout_url": "",
        "hosted_checkout_url": "",
        "pm_id": "pm_direct",
    }


def test_post_paypal_task_preflight_accepts_direct_ba_without_access_token(monkeypatch):
    accounts = [{"email": "user@example.com", "auth_file": "data/auth_session/user@example.com.json"}]

    monkeypatch.setattr("autotoken.storage.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.storage.accounts.find_account",
        lambda rows, email: accounts[0] if email == "user@example.com" else None,
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(
        api,
        "_extract_account_access_token",
        lambda _email: (_ for _ in ()).throw(AssertionError("direct BA preflight should not load access token")),
    )

    result = api.post_paypal_task_preflight(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="user@example.com",
            checkout_url="",
            manual_confirm=False,
            paypal_mode="create_account",
            paypal_browser="protocol",
            paypal_country="JP",
            billing_phone="+819012345678",
            sms_url="https://sms.example/token",
            paypal_approve_url="https://www.paypal.com/pay?token=BA-DIRECT123",
            paypal_checkout_session_id="cs_direct",
        )
    )

    assert result["ok"] is True
    assert result["mode"] == "direct_ba"
    assert result["checks"]["browser_fallback"] is False
    assert result["checks"]["local_access_token"] == "not_required"
    assert result["sms_source"] == "request_sms_url"
    assert result["missing"] == []


def test_post_paypal_task_preflight_reports_missing_sms_config(monkeypatch):
    accounts = [{"email": "user@example.com", "auth_file": "data/auth_session/user@example.com.json"}]

    monkeypatch.setattr("autotoken.storage.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.storage.accounts.find_account",
        lambda rows, email: accounts[0] if email == "user@example.com" else None,
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(
        "autotoken.settings.setup_wizard._read_env",
        lambda: {},
    )

    result = api.post_paypal_task_preflight(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="user@example.com",
            checkout_url="",
            manual_confirm=False,
            paypal_mode="create_account",
            paypal_browser="protocol",
            paypal_country="JP",
            billing_phone="",
            paypal_ba_token="BA-DIRECT123",
            paypal_checkout_session_id="cs_direct",
        )
    )

    assert result["ok"] is False
    assert result["mode"] == "direct_ba"
    assert result["checks"]["sms"] is False
    assert any("PAYPAL_SMS_URL" in item or "PayPal SMS provider" in item for item in result["missing"])


def test_post_paypal_task_protocol_rejects_direct_ba_batch_reuse(monkeypatch):
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda accounts, email: accounts[0])
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")

    with pytest.raises(api.HTTPException) as exc:
        api.post_paypal_task(
            api.PayPalTaskParams(
                runner_mode="manual_checkout",
                email="user@example.com",
                account_emails=["user@example.com", "second@example.com"],
                checkout_url="",
                manual_confirm=False,
                paypal_mode="create_account",
                paypal_browser="protocol",
                paypal_country="JP",
                billing_phone="+819012345678",
                sms_url="https://sms.example/token",
                paypal_ba_token="BA-DIRECT123",
                paypal_checkout_session_id="cs_direct",
            )
        )

    assert exc.value.status_code == 400
    assert "只支持单账号任务" in exc.value.detail


def test_post_paypal_task_rejects_direct_ba_outside_protocol_create_account(monkeypatch):
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda accounts, email: accounts[0])
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")

    with pytest.raises(api.HTTPException) as exc:
        api.post_paypal_task(
            api.PayPalTaskParams(
                runner_mode="manual_checkout",
                email="user@example.com",
                checkout_url="",
                manual_confirm=False,
                paypal_mode="existing_account",
                paypal_browser="chromium",
                paypal_email="paypal@example.com",
                paypal_password="secret-pass",
                paypal_ba_token="BA-DIRECT123",
                paypal_checkout_session_id="cs_direct",
            )
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "直连 PayPal BA/link 模式只支持 create_account + protocol/no-card"


def test_post_paypal_task_legacy_jp_nocard_region_forces_protocol(monkeypatch):
    captured = {}

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: accounts[0] if email == "user@example.com" else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"command": command, "params": params})
            or {"task_id": "task-paypal-jp-nocard-legacy", "command": command, "params": params}
        ),
    )

    result = api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="user@example.com",
            checkout_url="https://pay.openai.com/demo",
            bind_link_payload={
                "billing_details": {"country": "JP", "currency": "JPY"},
                "checkout_ui_mode": "hosted",
            },
            manual_confirm=False,
            paypal_mode="create_account",
            paypal_region="JP_NOCARD",
            paypal_browser="protocol",
            billing_name="James Smith",
            billing_phone="+819012345678",
            billing_state="Tokyo",
            billing_city="Chiyoda",
            billing_zip="100-0001",
            billing_address1="1-1 Chiyoda",
            sms_url="https://sms.example.test/token=demo",
            autofill_enabled=False,
        )
    )

    assert result["task_id"] == "task-paypal-jp-nocard-legacy"
    assert captured["params"]["paypal_browser"] == "protocol"
    assert captured["params"].get("paypal_fallback_browser", "") == ""
    assert captured["params"]["paypal_region"] == "JP_NOCARD"
    assert captured["params"]["paypal_country"] == "JP"
    assert captured["params"]["paypal_lang"] == "ja"
    assert captured["params"]["bind_link_payload"]["billing_details"]["country"] == "US"
    assert captured["params"]["bind_link_payload"]["billing_details"]["currency"] == "USD"


def test_post_paypal_task_rejects_manual_confirm_with_autofill():
    with pytest.raises(api.HTTPException) as exc:
        api.post_paypal_task(
            api.PayPalTaskParams(
                runner_mode="manual_checkout",
                email="user@example.com",
                checkout_url="https://pay.openai.com/demo",
                manual_confirm=True,
                autofill_enabled=True,
            )
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "手动确认模式与自动生成账单信息不能同时开启"


def test_post_paypal_task_rejects_legacy_runner_mode():
    with pytest.raises(api.HTTPException) as exc:
        api.post_paypal_task(api.PayPalTaskParams(runner_mode="legacy_pipeline"))

    assert exc.value.status_code == 400
    assert exc.value.detail == "不支持的 PayPal 运行模式"


def test_paypal_task_runner_create_account_records_success(monkeypatch):
    captured = {"progress": [], "cpa_calls": [], "plan_updates": []}

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: accounts[0] if email == "user@example.com" else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(
        "autotoken.accounts.update_account",
        lambda email, **kwargs: (
            captured.setdefault("updates", []).append((email, kwargs)) or {"email": email, **kwargs}
        ),
    )
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))

    def fake_convert_session(email, *, account=None, force_account_type=None):
        captured["cpa_calls"].append((email, force_account_type))
        return {
            "email": email,
            "auth_file": f"data/auths/{email}.json",
            "filename": f"codex-{email}-plus-demo.json",
            "plan_type": "plus",
            "id_token_synthetic": True,
            "refresh_token_present": False,
            "account": None,
        }

    monkeypatch.setattr(api, "_convert_account_auth_session_to_cpa_auth", fake_convert_session)

    def fake_update_account_cpa_auth_plan_type(email, *, account=None, plan_type="plus"):
        captured["plan_updates"].append((email, account, plan_type))
        return {"auth_file": f"data/auths/{email}.json", "plan_type": plan_type}

    monkeypatch.setattr(api, "_update_account_cpa_auth_plan_type", fake_update_account_cpa_auth_plan_type)

    def fake_run_paypal_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        kwargs["on_progress"]({"stage": "paypal_authorize", "message": "已进入 PayPal 页面"})
        return {
            "status": "success",
            "failure_stage": "",
            "message": "PayPal 绑定完成",
            "screenshot_paths": ["data/paypal-success.png"],
        }

    monkeypatch.setattr("autotoken.paypal_bind_executor.run_paypal_bind_task", fake_run_paypal_bind_task)
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"func": func, "params": params, "command": command, "task_kwargs": kwargs})
            or {"task_id": "task-paypal-local-success", "command": command, "params": params}
        ),
    )

    result = api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="user@example.com",
            checkout_url="https://pay.openai.com/demo",
            proxy_url="socks5://user:pass@proxy.example.test:1080",
            manual_confirm=False,
            paypal_mode="create_account",
            paypal_email="fresh@example.com",
            paypal_password="Secret123!",
            sms_url="https://sms.example.test/token=demo",
            otp_channel="sms",
            paypal_card_number="4111111111111111",
            paypal_card_expiry="03/30",
            paypal_card_cvv="996",
            autofill_enabled=True,
            billing_name="James Smith",
            billing_phone="+13105550100",
            billing_country="US",
            billing_state="CA",
            billing_city="Los Angeles",
            billing_zip="90001",
            billing_address1="742 Evergreen Terrace",
            billing_address2="Apt 2",
            timeout_seconds=180,
        )
    )

    assert result["task_id"] == "task-paypal-local-success"
    assert captured["command"] == "paypal"
    assert captured["params"]["paypal_mode"] == "create_account"

    task_result = captured["func"]()

    assert task_result["status"] == "success"
    assert task_result["task_status"] == "completed"
    assert task_result["provider"] == "paypal"
    assert task_result["email"] == "user@example.com"
    assert task_result["paypal_mode"] == "create_account"
    assert task_result["paypal_auto_login"] is True
    assert task_result["autofill_enabled"] is True
    assert task_result["screenshot_paths"] == ["data/paypal-success.png"]
    assert "session_cpa_converted_emails" not in task_result
    assert captured["cpa_calls"] == []
    assert len(captured["plan_updates"]) == 1
    plan_email, plan_account, plan_type = captured["plan_updates"][0]
    assert plan_email == "user@example.com"
    assert plan_type == "plus"
    assert plan_account["email"] == "user@example.com"
    assert plan_account["account_type"] == "plus"
    assert plan_account["auth_file"] == "data/auths/user@example.com.json"
    assert captured["run_kwargs"]["paypal_mode"] == "create_account"
    assert captured["run_kwargs"]["paypal_email"] == "fresh@example.com"
    assert captured["run_kwargs"]["paypal_password"] == "Secret123!"
    assert captured["run_kwargs"]["proxy_url"] == "socks5://user:pass@proxy.example.test:1080"
    assert captured["run_kwargs"]["sms_url"] == "https://sms.example.test/token=demo"
    assert captured["run_kwargs"]["otp_channel"] == "sms"
    assert captured["run_kwargs"]["phone_accounts"] == []
    assert captured["run_kwargs"]["timeout_seconds"] == 180
    assert captured["run_kwargs"]["autofill_payload"] == {
        "name": "James Smith",
        "email": "user@example.com",
        "phone": "+13105550100",
        "country": "US",
        "state": "CA",
        "city": "Los Angeles",
        "zip": "90001",
        "address1": "742 Evergreen Terrace",
        "address2": "Apt 2",
        "card_number": "4111111111111111",
        "card_expiry": "03/30",
        "card_cvv": "996",
    }
    assert captured["updates"] == [
        (
            "user@example.com",
            {
                "last_bind_status": "success",
                "last_bind_at": captured["updates"][0][1]["last_bind_at"],
                "last_bind_provider": "paypal",
                "last_checkout_url": "https://pay.openai.com/demo",
                "last_proxy_label": "",
                "last_bind_task_id": captured["updates"][0][1]["last_bind_task_id"],
                "last_bind_message": "PayPal 绑定完成",
                "last_bind_failure_stage": "",
                "status": "active",
                "account_type": "plus",
                "seat_type": "codex",
                "account_source": "managed",
                "plus_bound_at": captured["updates"][0][1]["plus_bound_at"],
            },
        )
    ]
    assert captured["audit"]["status"] == "success"
    assert captured["audit"]["task_status"] == "completed"
    assert captured["audit"]["flow"] == "paypal_create_account"
    assert captured["audit"]["provider"] == "paypal"
    assert [event["stage"] for event in captured["progress"]] == [
        "paypal_starting",
        "paypal_authorize",
        "paypal_oauth_login_skipped",
        "paypal_completed",
    ]


def test_post_paypal_task_create_account_passes_phone_accounts(monkeypatch):
    captured = {}

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: accounts[0] if email == "user@example.com" else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: {"email": email, **kwargs})
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda _payload: None)
    monkeypatch.setattr(api, "_append_task_progress", lambda *_args, **_kwargs: None)

    def fake_run_paypal_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "failed",
            "failure_stage": "paypal_phone_rejected",
            "message": "PayPal 拒绝当前手机号，请更换手机号",
            "screenshot_paths": [],
        }

    monkeypatch.setattr("autotoken.paypal_bind_executor.run_paypal_bind_task", fake_run_paypal_bind_task)
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"func": func, "params": params})
            or {"task_id": "task-paypal-phone-pool", "command": command, "params": params}
        ),
    )

    api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="user@example.com",
            checkout_url="https://pay.openai.com/demo",
            manual_confirm=False,
            paypal_mode="create_account",
            autofill_enabled=True,
            pending_retry_attempts=0,
            phone_accounts=[
                api.GoPayPhoneAccountParams(
                    phone_number="+18352880840",
                    sms_url="https://sms.example/one",
                    otp_channel="sms",
                ),
                api.GoPayPhoneAccountParams(
                    phone_number="+18352623053",
                    sms_url="https://sms.example/two",
                    otp_channel="sms",
                ),
            ],
        )
    )

    with pytest.raises(api.TaskResultError):
        captured["func"]()

    assert captured["params"]["phone_account_count"] == 2
    assert captured["run_kwargs"]["sms_url"] == "https://sms.example/one"
    assert captured["run_kwargs"]["phone_accounts"] == [
        {"phone_number": "+18352880840", "sms_url": "https://sms.example/one", "otp_channel": "sms"},
        {"phone_number": "+18352623053", "sms_url": "https://sms.example/two", "otp_channel": "sms"},
    ]
    assert captured["run_kwargs"]["autofill_payload"]["phone"] == "+18352880840"


def test_post_paypal_task_keeps_roxybrowser_mode(monkeypatch):
    captured = {}

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: accounts[0] if email == "user@example.com" else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: {"email": email, **kwargs})
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda _payload: None)
    monkeypatch.setattr(api, "_append_task_progress", lambda *_args, **_kwargs: None)

    def fake_run_paypal_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "failed",
            "failure_stage": "post_submit",
            "message": "PayPal 任务失败",
            "screenshot_paths": [],
        }

    monkeypatch.setattr("autotoken.paypal_bind_executor.run_paypal_bind_task", fake_run_paypal_bind_task)
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"func": func, "params": params})
            or {"task_id": "task-paypal-roxybrowser", "command": command, "params": params}
        ),
    )

    api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="user@example.com",
            checkout_url="https://pay.openai.com/demo",
            manual_confirm=True,
            paypal_browser="roxybrowser",
            roxybrowser_workspace_id="workspace-1",
            pending_retry_attempts=0,
        )
    )

    with pytest.raises(api.TaskResultError):
        captured["func"]()

    assert captured["run_kwargs"]["paypal_browser"] == "roxybrowser"
    assert captured["run_kwargs"]["roxybrowser_workspace_id"] == "workspace-1"


def test_post_paypal_task_roxybrowser_auto_create_allows_parallel_without_profile(monkeypatch):
    captured = {"calls": [], "progress": []}
    accounts = [{"email": "first@example.com"}, {"email": "second@example.com"}]

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda rows, email: next((account for account in rows if account["email"] == email), None),
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: {"email": email, **kwargs})
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda _payload: None)
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))

    def fake_run_paypal_bind_task(**kwargs):
        captured["calls"].append(kwargs)
        return {
            "status": "success",
            "failure_stage": "",
            "message": "ok",
            "checkout_url": kwargs["checkout_url"],
            "screenshot_paths": [],
        }

    monkeypatch.setattr("autotoken.paypal_bind_executor.run_paypal_bind_task", fake_run_paypal_bind_task)
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"func": func, "params": params})
            or {"task_id": "task-paypal-roxybrowser-auto", "command": command, "params": params}
        ),
    )

    api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="first@example.com",
            account_emails=["first@example.com", "second@example.com"],
            checkout_url="https://pay.openai.com/demo",
            manual_confirm=True,
            paypal_browser="roxybrowser",
            roxybrowser_profile_id="should-be-ignored",
            roxybrowser_auto_create_profile=True,
            paypal_concurrency=2,
            pending_retry_attempts=0,
        )
    )

    result = captured["func"]()

    assert result["status"] == "success"
    assert result["concurrency"] == 2
    assert captured["params"]["roxybrowser_auto_create_profile"] is True
    assert captured["params"]["roxybrowser_profile_id"] == ""
    assert all(call["roxybrowser_profile_id"] == "" for call in captured["calls"])
    assert any(event["stage"] == "paypal_parallel_started" for event in captured["progress"])


def test_post_paypal_task_batch_skips_invalid_phone_within_same_task(monkeypatch):
    captured = {"calls": []}
    progress_events = []
    accounts = [
        {"email": "first@example.com"},
        {"email": "second@example.com"},
    ]

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda rows, email: next((account for account in rows if account["email"] == email), None),
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: {"email": email, **kwargs})
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda _payload: None)
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: progress_events.append(progress))

    def fake_run_paypal_bind_task(**kwargs):
        captured["calls"].append(kwargs)
        if kwargs["email"] == "first@example.com":
            kwargs["on_progress"](
                {
                    "stage": "paypal_phone_rejected_waiting_dismiss",
                    "rejected_phone": "+18352880840",
                    "message": "PayPal 拒绝当前手机号，请更换手机号",
                }
            )
            return {
                "status": "failed",
                "failure_stage": "paypal_phone_rejected",
                "message": "PayPal 拒绝当前手机号，请更换手机号",
                "screenshot_paths": [],
            }
        return {
            "status": "failed",
            "failure_stage": "post_submit",
            "message": "second failed",
            "screenshot_paths": [],
        }

    monkeypatch.setattr("autotoken.paypal_bind_executor.run_paypal_bind_task", fake_run_paypal_bind_task)
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"func": func, "params": params})
            or {"task_id": "task-paypal-phone-pool-batch", "command": command, "params": params}
        ),
    )

    api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="first@example.com",
            account_emails=["first@example.com", "second@example.com"],
            checkout_url="https://pay.openai.com/demo",
            manual_confirm=False,
            paypal_mode="create_account",
            autofill_enabled=True,
            pending_retry_attempts=0,
            phone_accounts=[
                api.GoPayPhoneAccountParams(
                    phone_number="+18352880840",
                    sms_url="https://sms.example/one",
                    otp_channel="sms",
                ),
                api.GoPayPhoneAccountParams(
                    phone_number="+18352623053",
                    sms_url="https://sms.example/two",
                    otp_channel="sms",
                ),
            ],
        )
    )

    with pytest.raises(api.TaskResultError):
        captured["func"]()

    assert len(captured["calls"]) == 2
    assert captured["calls"][0]["phone_accounts"] == [
        {"phone_number": "+18352880840", "sms_url": "https://sms.example/one", "otp_channel": "sms"},
        {"phone_number": "+18352623053", "sms_url": "https://sms.example/two", "otp_channel": "sms"},
    ]
    assert captured["calls"][0]["sms_url"] == "https://sms.example/one"
    assert captured["calls"][0]["autofill_payload"]["phone"] == "+18352880840"
    assert captured["calls"][1]["phone_accounts"] == [
        {"phone_number": "+18352623053", "sms_url": "https://sms.example/two", "otp_channel": "sms"},
    ]
    assert captured["calls"][1]["sms_url"] == "https://sms.example/two"
    assert captured["calls"][1]["autofill_payload"]["phone"] == "+18352623053"
    assert any(
        event.get("stage") == "paypal_phone_rejected_waiting_dismiss"
        and event.get("invalid_phone_numbers") == ["+18352880840"]
        for event in progress_events
    )


def test_post_paypal_task_batch_skips_invalid_phone_when_account_uses_phone_field(monkeypatch):
    captured = {"calls": []}
    accounts = [
        {"email": "first@example.com"},
        {"email": "second@example.com"},
    ]

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda rows, email: next((account for account in rows if account["email"] == email), None),
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: {"email": email, **kwargs})
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda _payload: None)
    monkeypatch.setattr(api, "_append_task_progress", lambda *_args, **_kwargs: None)

    def fake_run_paypal_bind_task(**kwargs):
        captured["calls"].append(kwargs)
        if kwargs["email"] == "first@example.com":
            kwargs["on_progress"](
                {
                    "stage": "paypal_phone_rejected_final",
                    "rejected_phone": "+18352880840",
                    "message": "PayPal 拒绝当前手机号，请更换手机号",
                }
            )
            return {
                "status": "failed",
                "failure_stage": "paypal_phone_rejected",
                "message": "PayPal 拒绝当前手机号，请更换手机号",
                "screenshot_paths": [],
            }
        return {
            "status": "failed",
            "failure_stage": "post_submit",
            "message": "second failed",
            "screenshot_paths": [],
        }

    monkeypatch.setattr("autotoken.paypal_bind_executor.run_paypal_bind_task", fake_run_paypal_bind_task)
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"func": func, "params": params})
            or {"task_id": "task-paypal-phone-key-batch", "command": command, "params": params}
        ),
    )

    params = api.PayPalTaskParams(
        runner_mode="manual_checkout",
        email="first@example.com",
        account_emails=["first@example.com", "second@example.com"],
        checkout_url="https://pay.openai.com/demo",
        manual_confirm=False,
        paypal_mode="create_account",
        autofill_enabled=True,
        pending_retry_attempts=0,
    )
    params.phone_accounts = [
        {"phone": "+18352880840", "sms_url": "https://sms.example/one", "otp_channel": "sms"},
        {"phone": "+18352623053", "sms_url": "https://sms.example/two", "otp_channel": "sms"},
    ]

    api.post_paypal_task(params)

    with pytest.raises(api.TaskResultError):
        captured["func"]()

    assert len(captured["calls"]) == 2
    assert captured["calls"][1]["phone_accounts"] == [
        {"phone_number": "+18352623053", "sms_url": "https://sms.example/two", "otp_channel": "sms"},
    ]
    assert captured["calls"][1]["sms_url"] == "https://sms.example/two"
    assert captured["calls"][1]["autofill_payload"]["phone"] == "+18352623053"


def test_post_paypal_task_parallel_leases_distinct_phone_accounts(monkeypatch):
    captured = {"calls": [], "progress": []}
    call_lock = threading.Lock()
    accounts = [
        {"email": "first@example.com"},
        {"email": "second@example.com"},
        {"email": "third@example.com"},
    ]

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda rows, email: next((account for account in rows if account["email"] == email), None),
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: {"email": email, **kwargs})
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda _payload: None)
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))

    def fake_run_paypal_bind_task(**kwargs):
        with call_lock:
            captured["calls"].append(kwargs)
        return {
            "status": "success",
            "failure_stage": "",
            "message": "ok",
            "checkout_url": kwargs["checkout_url"],
            "screenshot_paths": [],
        }

    monkeypatch.setattr("autotoken.paypal_bind_executor.run_paypal_bind_task", fake_run_paypal_bind_task)
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"func": func, "params": params})
            or {"task_id": "task-paypal-parallel", "command": command, "params": params}
        ),
    )

    api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="first@example.com",
            account_emails=["first@example.com", "second@example.com", "third@example.com"],
            checkout_url="https://pay.openai.com/demo",
            manual_confirm=False,
            paypal_mode="create_account",
            autofill_enabled=True,
            pending_retry_attempts=0,
            paypal_concurrency=3,
            phone_accounts=[
                api.GoPayPhoneAccountParams(phone_number="+18352880840", sms_url="https://sms.example/one"),
                api.GoPayPhoneAccountParams(phone_number="+18352623053", sms_url="https://sms.example/two"),
                api.GoPayPhoneAccountParams(phone_number="+18352881761", sms_url="https://sms.example/three"),
            ],
        )
    )

    result = captured["func"]()

    used_phones = sorted(call["phone_accounts"][0]["phone_number"] for call in captured["calls"])
    assert result["status"] == "success"
    assert result["concurrency"] == 3
    assert used_phones == sorted(["+18352880840", "+18352623053", "+18352881761"])
    assert any(event["stage"] == "paypal_parallel_started" for event in captured["progress"])


def test_paypal_task_runner_auto_oauth_after_success(monkeypatch):
    captured = {"progress": [], "oauth_calls": [], "updates": []}
    oauth_done = threading.Event()
    account = {"email": "user@example.com", "password": "pw", "account_type": "free"}

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda accounts, email: account if email == "user@example.com" else None,
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(
        "autotoken.accounts.update_account",
        lambda email, **kwargs: captured["updates"].append((email, kwargs)) or {"email": email, **kwargs},
    )
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr(api, "_extract_account_access_token", lambda _email: "access-token-demo")
    monkeypatch.setattr(
        api,
        "_convert_account_auth_session_to_cpa_auth",
        lambda *_args, **_kwargs: pytest.fail("CPA conversion should not run when auto_oauth_after_success is true"),
    )

    def fake_run_paypal_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "success",
            "failure_stage": "",
            "message": "PayPal 绑定完成",
            "screenshot_paths": [],
        }

    def fake_codex_login(email, acc, *, headless=False):
        captured["oauth_calls"].append((email, acc, headless))
        oauth_done.set()
        return {"email": email, "plan": "plus", "auth_file": f"data/auths/{email}.json"}

    monkeypatch.setattr("autotoken.paypal_bind_executor.run_paypal_bind_task", fake_run_paypal_bind_task)
    monkeypatch.setattr(api, "_run_account_codex_login_once", fake_codex_login)
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"func": func, "params": params})
            or {"task_id": "task-paypal-oauth", "command": command, "params": params}
        ),
    )

    api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="user@example.com",
            checkout_url="https://pay.openai.com/demo",
            manual_confirm=False,
            paypal_mode="create_account",
            autofill_enabled=True,
            billing_phone="+13105550100",
            sms_url="https://sms.example.test/token=demo",
            auto_oauth_after_success=True,
        )
    )

    result = captured["func"]()

    assert result["status"] == "success"
    assert result["task_status"] == "completed"
    assert result["oauth_scheduled_emails"] == ["user@example.com"]
    assert "session_cpa_converted_emails" not in result
    assert oauth_done.wait(2)
    assert captured["oauth_calls"] == [("user@example.com", account, False)]
    stages = [event["stage"] for event in captured["progress"]]
    assert "paypal_oauth_login_started" in stages
    assert "paypal_oauth_login_done" in stages
    assert "paypal_session_cpa_convert_started" not in stages


def test_paypal_task_runner_marks_already_paid_as_success(monkeypatch):
    captured = {"progress": [], "cpa_calls": []}

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: accounts[0] if email == "user@example.com" else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(
        "autotoken.accounts.update_account",
        lambda email, **kwargs: (
            captured.setdefault("updates", []).append((email, kwargs)) or {"email": email, **kwargs}
        ),
    )
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr(api, "_extract_account_access_token", lambda _email: "access-token-demo")
    monkeypatch.setattr(
        api,
        "_convert_account_auth_session_to_cpa_auth",
        lambda email, *, account=None, force_account_type=None: (
            captured["cpa_calls"].append((email, force_account_type))
            or {
                "email": email,
                "auth_file": f"data/auths/{email}.json",
                "filename": f"codex-{email}-plus-demo.json",
                "id_token_synthetic": True,
            }
        ),
    )
    monkeypatch.setattr(
        api,
        "_generate_checkout_link",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            api.HTTPException(status_code=400, detail="User is already paid")
        ),
    )
    monkeypatch.setattr(
        "autotoken.paypal_bind_executor.run_paypal_bind_task",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("already-paid checkout should not open browser")),
    )
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"func": func, "params": params})
            or {"task_id": "task-paypal-paid", "command": command, "params": params}
        ),
    )

    api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="user@example.com",
            bind_link_payload={"plan_name": "chatgptplusplan"},
            manual_confirm=False,
            paypal_mode="create_account",
            autofill_enabled=True,
            billing_phone="+13105550100",
            sms_url="https://sms.example.test/token=demo",
        )
    )

    task_result = captured["func"]()

    assert task_result["status"] == "success"
    assert task_result["task_status"] == "completed"
    assert task_result["user_paid_skip"] is True
    assert captured["updates"][0][1]["last_bind_status"] == "success"
    assert captured["updates"][0][1]["account_type"] == "plus"
    assert captured["updates"][0][1]["status"] == "active"
    assert captured["audit"]["status"] == "success"
    assert captured["audit"]["task_status"] == "completed"
    assert captured["cpa_calls"] == []
    assert [event["stage"] for event in captured["progress"]] == [
        "paypal_starting",
        "paypal_oauth_login_skipped",
        "paypal_completed",
    ]


def test_paypal_batch_uses_candidate_email_for_autofill_payload(monkeypatch):
    captured = {"run_kwargs": [], "progress": [], "updates": [], "progress_callbacks": []}
    accounts = [{"email": "first@example.com"}, {"email": "second@example.com"}]

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda rows, email: next((account for account in rows if account["email"] == email), None),
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(
        "autotoken.accounts.update_account",
        lambda email, **kwargs: captured["updates"].append((email, kwargs)) or {"email": email, **kwargs},
    )
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda _payload: None)
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))

    def fake_run_paypal_bind_task(**kwargs):
        captured["run_kwargs"].append(kwargs)
        captured["progress_callbacks"].append(kwargs["on_progress"])
        return {
            "status": "success",
            "failure_stage": "",
            "message": "PayPal 绑定完成",
            "screenshot_paths": [],
        }

    monkeypatch.setattr("autotoken.paypal_bind_executor.run_paypal_bind_task", fake_run_paypal_bind_task)
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"func": func, "params": params})
            or {"task_id": "task-paypal-batch", "command": command, "params": params}
        ),
    )

    api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="first@example.com",
            account_emails=["first@example.com", "second@example.com"],
            checkout_url="https://pay.openai.com/demo",
            manual_confirm=False,
            paypal_mode="create_account",
            autofill_enabled=True,
            billing_phone="+13105550100",
            sms_url="https://sms.example.test/token=demo",
        )
    )

    result = captured["func"]()

    assert result["status"] == "success"
    assert result["successful_emails"] == ["first@example.com", "second@example.com"]
    assert [kwargs["email"] for kwargs in captured["run_kwargs"]] == ["first@example.com", "second@example.com"]
    assert [kwargs["autofill_payload"]["email"] for kwargs in captured["run_kwargs"]] == [
        "first@example.com",
        "second@example.com",
    ]
    captured["progress_callbacks"][0]({"stage": "paypal_delayed_probe"})
    captured["progress_callbacks"][1]({"stage": "paypal_delayed_probe"})
    delayed_progress = [
        progress for progress in captured["progress"] if progress["stage"] == "paypal_delayed_probe"
    ]
    assert [(progress["email"], progress["current"], progress["total"]) for progress in delayed_progress] == [
        ("first@example.com", 1, 2),
        ("second@example.com", 2, 2),
    ]


def test_paypal_batch_refreshes_access_token_after_checkout_401(monkeypatch):
    captured = {"run_kwargs": [], "progress": [], "updates": [], "removed": []}
    accounts = [{"email": "first@example.com"}, {"email": "second@example.com"}]

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda rows, email: next((account for account in rows if account["email"] == email), None),
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_extract_account_access_token", lambda email: f"token-{email}")
    monkeypatch.setattr(
        api, "_refresh_account_access_token", lambda email: f"fresh-{email}" if email == "first@example.com" else ""
    )
    monkeypatch.setattr(
        "autotoken.accounts.update_account",
        lambda email, **kwargs: captured["updates"].append((email, kwargs)) or {"email": email, **kwargs},
    )
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda _payload: None)
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr(
        api,
        "_remove_pool_accounts_from_local_and_mail",
        lambda emails, **_kwargs: captured["removed"].append((list(emails), _kwargs)) or list(emails),
    )

    checkout_calls = []

    def fake_generate_checkout(access_token, _payload):
        checkout_calls.append(access_token)
        if access_token == "token-first@example.com":
            raise api.HTTPException(status_code=401, detail={"code": "unauthorized_unknown"})
        if access_token == "fresh-first@example.com":
            return {"url": "https://pay.openai.com/c/pay/cs_first"}
        return {"url": "https://pay.openai.com/c/pay/cs_second"}

    monkeypatch.setattr(api, "_generate_checkout_link", fake_generate_checkout)

    def fake_run_paypal_bind_task(**kwargs):
        captured["run_kwargs"].append(kwargs)
        return {
            "status": "success",
            "failure_stage": "",
            "message": "检测到 PayPal/支付成功页面",
            "screenshot_paths": [],
            "checkout_url": kwargs["checkout_url"],
        }

    monkeypatch.setattr("autotoken.paypal_bind_executor.run_paypal_bind_task", fake_run_paypal_bind_task)
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"func": func, "params": params})
            or {"task_id": "task-paypal-checkout-401", "command": command, "params": params}
        ),
    )

    api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="first@example.com",
            account_emails=["first@example.com", "second@example.com"],
            bind_link_payload={"plan_name": "chatgptplusplan"},
            manual_confirm=False,
            paypal_mode="create_account",
            autofill_enabled=True,
            billing_phone="+13105550100",
            sms_url="https://sms.example.test/token=demo",
        )
    )

    result = captured["func"]()

    assert result["status"] == "success"
    assert result["task_status"] == "completed"
    assert result["successful_emails"] == ["first@example.com", "second@example.com"]
    assert result["failed_emails"] == []
    assert result["removed_pool_emails"] == []
    assert checkout_calls == ["token-first@example.com", "fresh-first@example.com", "token-second@example.com"]
    assert [kwargs["email"] for kwargs in captured["run_kwargs"]] == ["first@example.com", "second@example.com"]
    assert captured["run_kwargs"][0]["checkout_url"] == "https://pay.openai.com/c/pay/cs_first"
    assert captured["run_kwargs"][1]["checkout_url"] == "https://pay.openai.com/c/pay/cs_second"
    assert captured["removed"] == []
    assert not any(event["stage"] == "paypal_checkout_auth_invalid_rotate" for event in captured["progress"])
    assert any(event["stage"] == "paypal_checkout_token_refreshed" for event in captured["progress"])
    assert captured["updates"][0][0] == "first@example.com"
    assert captured["updates"][0][1]["last_bind_provider"] == "paypal"
    assert captured["updates"][1][0] == "second@example.com"
    assert captured["updates"][1][1]["last_bind_provider"] == "paypal"


def test_paypal_batch_falls_back_to_browser_checkout_when_refresh_token_unchanged(monkeypatch):
    captured = {"run_kwargs": [], "progress": [], "updates": []}
    accounts = [{"email": "first@example.com"}]

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda rows, email: accounts[0] if email == "first@example.com" else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/first@example.com.json")
    monkeypatch.setattr(api, "_extract_account_access_token", lambda email: f"token-{email}")
    monkeypatch.setattr(api, "_refresh_account_access_token", lambda email: f"token-{email}")
    monkeypatch.setattr(
        "autotoken.accounts.update_account",
        lambda email, **kwargs: captured["updates"].append((email, kwargs)) or {"email": email, **kwargs},
    )
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda _payload: None)
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))

    checkout_calls = []
    browser_calls = []

    def fake_generate_checkout(access_token, _payload):
        checkout_calls.append(access_token)
        raise api.HTTPException(status_code=401, detail={"code": "unauthorized_unknown"})

    def fake_generate_checkout_via_browser(access_token, _payload, **kwargs):
        browser_calls.append((access_token, kwargs))
        return {"url": "https://pay.openai.com/c/pay/cs_browser", "attempt": "browser_target"}

    monkeypatch.setattr(api, "_generate_checkout_link", fake_generate_checkout)
    monkeypatch.setattr(api, "_generate_checkout_link_via_browser", fake_generate_checkout_via_browser)

    def fake_run_paypal_bind_task(**kwargs):
        captured["run_kwargs"].append(kwargs)
        return {
            "status": "success",
            "failure_stage": "",
            "message": "检测到 PayPal/支付成功页面",
            "screenshot_paths": [],
            "checkout_url": kwargs["checkout_url"],
        }

    monkeypatch.setattr("autotoken.paypal_bind_executor.run_paypal_bind_task", fake_run_paypal_bind_task)
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"func": func, "params": params})
            or {"task_id": "task-paypal-browser-fallback", "command": command, "params": params}
        ),
    )

    api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="first@example.com",
            account_emails=["first@example.com"],
            bind_link_payload={"plan_name": "chatgptplusplan"},
            proxy_url="socks5://user:pass@127.0.0.1:1080",
            proxy_bypass="<local>",
            manual_confirm=False,
            paypal_mode="create_account",
            paypal_browser="camoufox",
            autofill_enabled=True,
            billing_phone="+13105550100",
            sms_url="https://sms.example.test/token=demo",
        )
    )

    result = captured["func"]()

    assert result["status"] == "success"
    assert checkout_calls == ["token-first@example.com"]
    assert browser_calls == [
        (
            "token-first@example.com",
            {
                "email": "first@example.com",
                "proxy_url": "socks5://user:pass@127.0.0.1:1080",
                "proxy_bypass": "<local>",
                "paypal_browser": "camoufox",
                "roxybrowser_workspace_id": "",
                "roxybrowser_profile_id": "",
            },
        )
    ]
    assert captured["run_kwargs"][0]["checkout_url"] == "https://pay.openai.com/c/pay/cs_browser"
    assert any(event["stage"] == "paypal_checkout_browser_fallback" for event in captured["progress"])
    assert any(event["stage"] == "paypal_checkout_browser_generated" for event in captured["progress"])


def test_generate_checkout_browser_uses_autoregister_like_launch_args(monkeypatch):
    captured = {}

    class FakePage:
        def __init__(self):
            self.url = "about:blank"

        def goto(self, *args, **kwargs):
            captured.setdefault("goto", []).append((args, kwargs))

        def evaluate(self, script, payload):
            captured["evaluate_payload"] = payload
            return {
                "ok": True,
                "status": 200,
                "url": "https://chatgpt.com/checkout/openai_llc/cs_demo",
                "checkout_session_id": "cs_demo",
                "processor_entity": "openai_llc",
                "attempt": "browser_target",
            }

    class FakeChatGPTApi:
        def __init__(self):
            self.page = FakePage()
            self.oai_device_id = ""

        def _launch_browser(self, **kwargs):
            captured["launch_kwargs"] = kwargs
            self.page = FakePage()

        def _wait_for_cloudflare(self):
            captured["wait_for_cloudflare"] = True

        def stop(self):
            captured["stopped"] = True

    monkeypatch.setattr("autotoken.chatgpt_api.ChatGPTTeamAPI", FakeChatGPTApi)
    monkeypatch.setattr(
        "autotoken.auth_session_store.load_auth_session",
        lambda _email: {"device_id": "device-1", "sessionToken": "session-1", "cookie_header": "cookie-1"},
    )
    monkeypatch.setattr(
        "autotoken.services.chatgpt_session.inject_chatgpt_browser_cookies",
        lambda *args, **kwargs: captured.setdefault("cookies", []).append((args, kwargs)),
    )
    monkeypatch.setattr(api.time, "sleep", lambda _seconds: None)

    result = api._generate_checkout_link_via_browser(
        "token-demo",
        {"checkout_ui_mode": "hosted"},
        email="user@example.com",
        proxy_url="socks5://user:pass@127.0.0.1:1080",
        proxy_bypass="<local>",
        paypal_browser="camoufox",
    )

    assert result["url"] == "https://chatgpt.com/checkout/openai_llc/cs_demo"
    assert captured["launch_kwargs"]["background"] is False
    assert captured["launch_kwargs"]["locale"] == "en-US"
    assert captured["launch_kwargs"]["accept_language"] == "en-US,en;q=0.9"
    assert captured["launch_kwargs"]["randomize_fingerprint"] is False
    assert captured["launch_kwargs"]["use_camoufox"] is True
    assert captured["launch_kwargs"]["use_roxybrowser"] is False
    assert captured["launch_kwargs"]["proxy_url"] == "socks5://user:pass@127.0.0.1:1080"
    assert captured["launch_kwargs"]["proxy_bypass"] == "<local>"
    assert captured["evaluate_payload"]["accessToken"] == "token-demo"
    assert captured["stopped"] is True


def test_paypal_batch_randomizes_proxy_pool_per_candidate(monkeypatch):
    captured = {"run_kwargs": [], "progress": [], "updates": []}
    accounts = [{"email": "first@example.com"}, {"email": "second@example.com"}]

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda rows, email: next((account for account in rows if account["email"] == email), None),
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_extract_account_access_token", lambda email: f"token-{email}")
    monkeypatch.setattr(
        "autotoken.accounts.update_account",
        lambda email, **kwargs: captured["updates"].append((email, kwargs)) or {"email": email, **kwargs},
    )
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda _payload: None)
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))

    selected = []

    def fake_choice(values):
        value = values[len(selected) % len(values)]
        selected.append(value)
        return value

    monkeypatch.setattr(api.random, "choice", fake_choice)
    monkeypatch.setattr(
        api,
        "_generate_checkout_link",
        lambda _token, _payload, **_kwargs: {"url": "https://pay.openai.com/c/pay/cs_demo"},
    )

    def fake_run_paypal_bind_task(**kwargs):
        captured["run_kwargs"].append(kwargs)
        return {
            "status": "success",
            "failure_stage": "",
            "message": "PayPal 绑定完成",
            "screenshot_paths": [],
            "checkout_url": kwargs["checkout_url"],
        }

    monkeypatch.setattr("autotoken.paypal_bind_executor.run_paypal_bind_task", fake_run_paypal_bind_task)
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"func": func, "params": params})
            or {"task_id": "task-paypal-proxy-pool", "command": command, "params": params}
        ),
    )

    api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="first@example.com",
            account_emails=["first@example.com", "second@example.com"],
            bind_link_payload={"plan_name": "chatgptplusplan"},
            proxy_pool_text="1.1.1.1:8080:user:pass\nsocks5://u:p@2.2.2.2:1080",
            manual_confirm=False,
            paypal_mode="create_account",
            autofill_enabled=True,
            billing_phone="+13105550100",
            sms_url="https://sms.example.test/token=demo",
        )
    )

    result = captured["func"]()

    assert result["status"] == "success"
    assert selected == ["http://user:pass@1.1.1.1:8080", "socks5://u:p@2.2.2.2:1080"]
    assert [kwargs["proxy_url"] for kwargs in captured["run_kwargs"]] == selected
    assert [event["stage"] for event in captured["progress"]].count("paypal_proxy_selected") == 2


def test_paypal_batch_fetches_proxy_api_per_candidate(monkeypatch):
    captured = {"run_kwargs": [], "progress": [], "updates": []}
    accounts = [{"email": "first@example.com"}, {"email": "second@example.com"}]
    api_proxies = [
        "1.1.1.1:8080:user-a:pass-a",
        "2.2.2.2:8080:user-b:pass-b",
    ]

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda rows, email: next((account for account in rows if account["email"] == email), None),
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_extract_account_access_token", lambda email: f"token-{email}")
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: {"email": email, **kwargs})
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda _payload: None)
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr(
        api,
        "_generate_checkout_link",
        lambda _token, _payload, **_kwargs: {"url": "https://pay.openai.com/c/pay/cs_demo"},
    )

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/plain"}

        def __init__(self, text):
            self.text = text

    def fake_get(url, timeout):
        assert "dashboard.1024proxy.com/getporxy/traffic" in url
        return FakeResponse(api_proxies.pop(0))

    monkeypatch.setattr(api.requests, "get", fake_get)

    def fake_run_paypal_bind_task(**kwargs):
        captured["run_kwargs"].append(kwargs)
        return {
            "status": "success",
            "failure_stage": "",
            "message": "PayPal 绑定完成",
            "screenshot_paths": [],
            "checkout_url": kwargs["checkout_url"],
        }

    monkeypatch.setattr("autotoken.paypal_bind_executor.run_paypal_bind_task", fake_run_paypal_bind_task)
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"func": func, "params": params})
            or {"task_id": "task-paypal-proxy-api", "command": command, "params": params}
        ),
    )

    api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="first@example.com",
            account_emails=["first@example.com", "second@example.com"],
            bind_link_payload={"plan_name": "chatgptplusplan"},
            proxy_api_url="https://dashboard.1024proxy.com/getporxy/traffic?demo=1",
            manual_confirm=False,
            paypal_mode="create_account",
            autofill_enabled=True,
            billing_phone="+13105550100",
            sms_url="https://sms.example.test/token=demo",
        )
    )

    result = captured["func"]()

    assert result["status"] == "success"
    assert [kwargs["proxy_url"] for kwargs in captured["run_kwargs"]] == [
        "socks5h://user-a:pass-a@1.1.1.1:8080",
        "socks5h://user-b:pass-b@2.2.2.2:8080",
    ]
    assert [event["stage"] for event in captured["progress"]].count("paypal_proxy_api_selected") == 2


def test_paypal_proxy_pool_text_can_contain_proxy_api_url(monkeypatch):
    captured = {"run_kwargs": [], "progress": []}
    accounts = [{"email": "first@example.com"}]

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda rows, email: accounts[0] if email == "first@example.com" else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_extract_account_access_token", lambda email: f"token-{email}")
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: {"email": email, **kwargs})
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda _payload: None)
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr(
        api,
        "_generate_checkout_link",
        lambda _token, _payload, **_kwargs: {"url": "https://pay.openai.com/c/pay/cs_demo"},
    )

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = '{"data":["3.3.3.3:8080:user-c:pass-c"]}'

        def json(self):
            return {"data": ["3.3.3.3:8080:user-c:pass-c"]}

    monkeypatch.setattr(api.requests, "get", lambda url, timeout: FakeResponse())
    monkeypatch.setattr(
        "autotoken.paypal_bind_executor.run_paypal_bind_task",
        lambda **kwargs: (
            captured["run_kwargs"].append(kwargs)
            or {
                "status": "success",
                "failure_stage": "",
                "message": "PayPal 绑定完成",
                "screenshot_paths": [],
                "checkout_url": kwargs["checkout_url"],
            }
        ),
    )
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"func": func, "params": params})
            or {"task_id": "task-paypal-proxy-api-text", "command": command, "params": params}
        ),
    )

    api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="first@example.com",
            bind_link_payload={"plan_name": "chatgptplusplan"},
            proxy_pool_text="https://dashboard.1024proxy.com/getporxy/traffic?demo=1",
            manual_confirm=False,
            paypal_mode="create_account",
            autofill_enabled=True,
            billing_phone="+13105550100",
            sms_url="https://sms.example.test/token=demo",
        )
    )

    result = captured["func"]()

    assert result["status"] == "success"
    assert captured["params"]["proxy_api_url_present"] is True
    assert captured["params"]["proxy_pool_count"] == 0
    assert captured["run_kwargs"][0]["proxy_url"] == "socks5h://user-c:pass-c@3.3.3.3:8080"


def test_paypal_cliproxy_api_uses_fixed_proxy_entry(monkeypatch):
    captured = {"run_kwargs": [], "progress": [], "api_calls": []}
    accounts = [{"email": "first@example.com"}]

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda rows, email: accounts[0] if email == "first@example.com" else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_extract_account_access_token", lambda email: f"token-{email}")
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: {"email": email, **kwargs})
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda _payload: None)
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr(
        api,
        "_generate_checkout_link",
        lambda _token, _payload, **_kwargs: {"url": "https://pay.openai.com/c/pay/cs_demo"},
    )

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = '{"code":0,"msg":"success"}'

        def json(self):
            return {"code": 0, "msg": "success"}

    def fake_get(url, timeout):
        captured["api_calls"].append((url, timeout))
        return FakeResponse()

    monkeypatch.setattr(api.requests, "get", fake_get)
    monkeypatch.setattr(
        "autotoken.paypal_bind_executor.run_paypal_bind_task",
        lambda **kwargs: (
            captured["run_kwargs"].append(kwargs)
            or {
                "status": "success",
                "failure_stage": "",
                "message": "PayPal 绑定完成",
                "screenshot_paths": [],
                "checkout_url": kwargs["checkout_url"],
            }
        ),
    )
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"func": func, "params": params})
            or {"task_id": "task-paypal-cliproxy-api", "command": command, "params": params}
        ),
    )

    api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="first@example.com",
            bind_link_payload={"plan_name": "chatgptplusplan"},
            proxy_url="socks5://user:pass@cliproxy.example:3010",
            proxy_api_url="https://api.cliproxy.example/rotate?port=3010",
            proxy_api_provider="cliproxy",
            manual_confirm=False,
            paypal_mode="create_account",
            autofill_enabled=True,
            billing_phone="+13105550100",
            sms_url="https://sms.example.test/token=demo",
        )
    )

    result = captured["func"]()

    assert result["status"] == "success"
    assert captured["api_calls"] == [("https://api.cliproxy.example/rotate?port=3010", 30)]
    assert captured["run_kwargs"][0]["proxy_url"] == "socks5://user:pass@cliproxy.example:3010"
    assert captured["params"]["proxy_api_provider"] == "cliproxy"
    selected_events = [event for event in captured["progress"] if event.get("stage") == "paypal_proxy_api_selected"]
    assert selected_events[0]["proxy_api_provider"] == "cliproxy"


def test_paypal_1024proxy_provider_uses_backend_default_api(monkeypatch):
    captured = {"run_kwargs": [], "progress": [], "api_calls": []}
    accounts = [{"email": "first@example.com"}]

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda rows, email: accounts[0] if email == "first@example.com" else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_extract_account_access_token", lambda email: f"token-{email}")
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: {"email": email, **kwargs})
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda _payload: None)
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr(
        api,
        "_generate_checkout_link",
        lambda _token, _payload, **_kwargs: {"url": "https://pay.openai.com/c/pay/cs_demo"},
    )

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = '[{"host":"4.4.4.4","port":"8080"}]'

        def json(self):
            return [{"host": "4.4.4.4", "port": "8080"}]

    def fake_get(url, timeout):
        captured["api_calls"].append((url, timeout))
        return FakeResponse()

    monkeypatch.setattr(api.requests, "get", fake_get)
    monkeypatch.setattr(
        "autotoken.paypal_bind_executor.run_paypal_bind_task",
        lambda **kwargs: (
            captured["run_kwargs"].append(kwargs)
            or {
                "status": "success",
                "failure_stage": "",
                "message": "PayPal 绑定完成",
                "screenshot_paths": [],
                "checkout_url": kwargs["checkout_url"],
            }
        ),
    )
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"func": func, "params": params})
            or {"task_id": "task-paypal-default-proxy-api", "command": command, "params": params}
        ),
    )

    api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="first@example.com",
            bind_link_payload={"plan_name": "chatgptplusplan"},
            proxy_api_provider="1024proxy",
            manual_confirm=False,
            paypal_mode="create_account",
            autofill_enabled=True,
            billing_phone="+13105550100",
            sms_url="https://sms.example.test/token=demo",
        )
    )

    result = captured["func"]()

    assert result["status"] == "success"
    assert captured["api_calls"] == [
        ("https://white.1024proxy.com/white/api?region=US&num=1&time=10&format=1&type=json", 30)
    ]
    assert captured["run_kwargs"][0]["proxy_url"] == "socks5h://4.4.4.4:8080"
    assert captured["params"]["proxy_api_provider"] == "1024proxy"
    selected_events = [event for event in captured["progress"] if event.get("stage") == "paypal_proxy_api_selected"]
    assert selected_events[0]["proxy_api_provider"] == "1024proxy"


def test_paypal_cliproxy_provider_uses_backend_default_api(monkeypatch):
    captured = {"run_kwargs": [], "progress": [], "api_calls": []}
    accounts = [{"email": "first@example.com"}]

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda rows, email: accounts[0] if email == "first@example.com" else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_extract_account_access_token", lambda email: f"token-{email}")
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: {"email": email, **kwargs})
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda _payload: None)
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr(
        api,
        "_generate_checkout_link",
        lambda _token, _payload, **_kwargs: {"url": "https://pay.openai.com/c/pay/cs_demo"},
    )

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = '[{"host":"5.5.5.5","port":"9090"}]'

        def json(self):
            return [{"host": "5.5.5.5", "port": "9090"}]

    monkeypatch.setattr(
        api.requests, "get", lambda url, timeout: captured["api_calls"].append((url, timeout)) or FakeResponse()
    )
    monkeypatch.setattr(
        "autotoken.paypal_bind_executor.run_paypal_bind_task",
        lambda **kwargs: (
            captured["run_kwargs"].append(kwargs)
            or {
                "status": "success",
                "failure_stage": "",
                "message": "PayPal 绑定完成",
                "screenshot_paths": [],
                "checkout_url": kwargs["checkout_url"],
            }
        ),
    )
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"func": func, "params": params})
            or {"task_id": "task-paypal-default-cliproxy", "command": command, "params": params}
        ),
    )

    api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="first@example.com",
            bind_link_payload={"plan_name": "chatgptplusplan"},
            proxy_api_provider="cliproxy",
            manual_confirm=False,
            paypal_mode="create_account",
            autofill_enabled=True,
            billing_phone="+13105550100",
            sms_url="https://sms.example.test/token=demo",
        )
    )

    result = captured["func"]()

    assert result["status"] == "success"
    assert captured["api_calls"] == [
        ("https://api.cliproxy.io/white/api?region=US&num=1&time=30&format=n&type=json", 30)
    ]
    assert captured["run_kwargs"][0]["proxy_url"] == "socks5h://5.5.5.5:9090"


def test_paypal_protocol_cliproxy_api_uses_us_provider_stage_proxy(monkeypatch):
    captured = {"extract_kwargs": {}, "run_kwargs": [], "progress": [], "api_calls": []}
    accounts = [{"email": "first@example.com"}]

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda rows, email: accounts[0] if email == "first@example.com" else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_extract_account_access_token", lambda email: f"token-{email}")
    monkeypatch.setattr(api, "_probe_proxy_exit_ip", lambda _proxy: "")
    monkeypatch.setattr(
        "autotoken.services.paypal_proxy.paypal_proxy_exit_location",
        lambda *_args, **_kwargs: {"country_code": "JP", "region": "Tokyo", "city": "Tokyo", "ip": "198.51.100.8"},
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: {"email": email, **kwargs})
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda _payload: None)
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr(
        api,
        "_generate_checkout_link",
        lambda _token, _payload, **_kwargs: {"url": "https://pay.openai.com/c/pay/cs_demo"},
    )

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/plain"}

        def __init__(self, text):
            self.text = text

    def fake_get(url, timeout):
        captured["api_calls"].append((url, timeout))
        if "region=US" in url:
            return FakeResponse("107.150.109.49:7104")
        return FakeResponse("103.49.62.181:19004")

    monkeypatch.setattr(api.requests, "get", fake_get)
    monkeypatch.setattr(
        "autotoken.paypal_bind_executor._extract_auth_session_context",
        lambda _email: {
            "access_token": "extract-token",
            "session_token": "session-token",
            "cookie_header": "__Secure-next-auth.session-token=session-token",
        },
    )

    def fake_extract(**kwargs):
        captured["extract_kwargs"] = kwargs
        return {
            "status": "success",
            "ba_token": "BA-US",
            "approve_url": "https://www.paypal.com/agreements/approve?ba_token=BA-US",
            "checkout_url": "https://pay.openai.com/c/pay/cs_demo#hash",
        }

    monkeypatch.setattr("autotoken.paypal_bind_executor._paypal_extract_ba_link", fake_extract)
    monkeypatch.setattr(
        "autotoken.paypal_bind_executor.run_paypal_bind_task",
        lambda **kwargs: (
            captured["run_kwargs"].append(kwargs)
            or {
                "status": "success",
                "failure_stage": "",
                "message": "PayPal 绑定完成",
                "screenshot_paths": [],
                "checkout_url": kwargs["checkout_url"],
            }
        ),
    )
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"func": func, "params": params})
            or {"task_id": "task-paypal-protocol-provider-proxy", "command": command, "params": params}
        ),
    )

    api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="first@example.com",
            bind_link_payload={"plan_name": "chatgptplusplan"},
            proxy_api_url="https://api.cliproxy.io/white/api?region=JP&num=1&time=10&format=n&type=txt",
            paypal_browser="protocol",
            paypal_country="JP",
            paypal_ba_mode="us",
            manual_confirm=False,
            paypal_mode="create_account",
            autofill_enabled=True,
            billing_phone="+819012345678",
            sms_url="https://sms.example.test/token=demo",
        )
    )

    result = captured["func"]()

    assert result["status"] == "success"
    assert captured["api_calls"][:2] == [
        ("https://api.cliproxy.io/white/api?region=JP&num=1&time=10&format=n&type=txt", 30),
        ("https://api.cliproxy.io/white/api?region=US&num=1&time=10&format=n&type=txt", 30),
    ]
    assert captured["extract_kwargs"]["proxy_url"] == "socks5h://103.49.62.181:19004"
    assert captured["extract_kwargs"]["provider_proxy_url"] == "socks5h://107.150.109.49:7104"
    assert captured["extract_kwargs"]["paypal_ba_mode"] == "us"
    assert captured["params"]["proxy_api_provider"] == "cliproxy"
    assert any(event.get("stage") == "paypal_provider_proxy_selected" for event in captured["progress"])


def test_paypal_protocol_cliproxy_provider_defaults_to_jp_then_us_provider(monkeypatch):
    captured = {"extract_kwargs": {}, "progress": [], "api_calls": []}
    accounts = [{"email": "first@example.com"}]

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda rows, email: accounts[0] if email == "first@example.com" else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_extract_account_access_token", lambda email: f"token-{email}")
    monkeypatch.setattr(api, "_probe_proxy_exit_ip", lambda _proxy: "")
    monkeypatch.setattr(
        "autotoken.services.paypal_proxy.paypal_proxy_exit_location",
        lambda *_args, **_kwargs: {"country_code": "JP", "region": "Tokyo", "city": "Tokyo", "ip": "198.51.100.8"},
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: {"email": email, **kwargs})
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda _payload: None)
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr(
        api,
        "_generate_checkout_link",
        lambda _token, _payload, **_kwargs: {"url": "https://pay.openai.com/c/pay/cs_demo"},
    )

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/plain"}

        def __init__(self, text):
            self.text = text

    def fake_get(url, timeout):
        captured["api_calls"].append((url, timeout))
        if "region=US" in url:
            return FakeResponse("107.150.109.49:7104")
        return FakeResponse("103.49.62.181:19004")

    monkeypatch.setattr(api.requests, "get", fake_get)
    monkeypatch.setattr(
        "autotoken.paypal_bind_executor._extract_auth_session_context",
        lambda _email: {
            "access_token": "extract-token",
            "session_token": "session-token",
            "cookie_header": "__Secure-next-auth.session-token=session-token",
        },
    )
    monkeypatch.setattr(
        "autotoken.paypal_bind_executor._paypal_extract_ba_link",
        lambda **kwargs: (
            captured.update({"extract_kwargs": kwargs})
            or {
                "status": "success",
                "ba_token": "BA-TEST",
                "approve_url": "https://www.paypal.com/agreements/approve?ba_token=BA-TEST",
                "checkout_url": "https://pay.openai.com/c/pay/cs_demo#hash",
            }
        ),
    )
    monkeypatch.setattr(
        "autotoken.paypal_bind_executor.run_paypal_bind_task",
        lambda **kwargs: {
            "status": "success",
            "failure_stage": "",
            "message": "PayPal 绑定完成",
            "screenshot_paths": [],
            "checkout_url": kwargs["checkout_url"],
        },
    )
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"func": func, "params": params})
            or {"task_id": "task-paypal-default-jp-cliproxy", "command": command, "params": params}
        ),
    )

    api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="first@example.com",
            bind_link_payload={"plan_name": "chatgptplusplan"},
            proxy_api_provider="cliproxy",
            paypal_browser="protocol",
            paypal_country="JP",
            manual_confirm=False,
            paypal_mode="create_account",
            autofill_enabled=True,
            billing_phone="+819012345678",
            sms_url="https://sms.example.test/token=demo",
        )
    )

    result = captured["func"]()

    assert result["status"] == "success"
    assert captured["api_calls"][:2] == [
        ("https://api.cliproxy.io/white/api?region=JP&num=1&time=30&format=n&type=json", 30),
        ("https://api.cliproxy.io/white/api?region=US&num=1&time=30&format=n&type=json", 30),
    ]
    assert captured["extract_kwargs"]["proxy_url"] == "socks5h://103.49.62.181:19004"
    assert captured["extract_kwargs"]["provider_proxy_url"] == "socks5h://107.150.109.49:7104"
    assert captured["extract_kwargs"]["payment_method_country"] == "US"
    assert captured["extract_kwargs"]["paypal_ba_mode"] == "eu"
    assert captured["params"]["proxy_api_provider"] == "cliproxy"
    assert captured["params"]["proxy_api_url_present"] is True


def test_paypal_protocol_payment_country_override_updates_provider_region(monkeypatch):
    captured = {"extract_kwargs": {}, "progress": [], "api_calls": []}
    accounts = [{"email": "first@example.com"}]

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda rows, email: accounts[0] if email == "first@example.com" else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_extract_account_access_token", lambda email: f"token-{email}")
    monkeypatch.setattr(api, "_probe_proxy_exit_ip", lambda _proxy: "")
    monkeypatch.setattr(
        "autotoken.services.paypal_proxy.paypal_proxy_exit_location",
        lambda *_args, **_kwargs: {"country_code": "JP", "region": "Tokyo", "city": "Tokyo", "ip": "198.51.100.8"},
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: {"email": email, **kwargs})
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda _payload: None)
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/plain"}

        def __init__(self, text):
            self.text = text

    def fake_get(url, timeout):
        captured["api_calls"].append((url, timeout))
        if "region=AU" in url:
            return FakeResponse("203.0.113.7:7104")
        return FakeResponse("103.49.62.181:19004")

    monkeypatch.setattr(api.requests, "get", fake_get)
    monkeypatch.setattr(
        "autotoken.paypal_bind_executor._extract_auth_session_context",
        lambda _email: {
            "access_token": "extract-token",
            "session_token": "session-token",
            "cookie_header": "__Secure-next-auth.session-token=session-token",
        },
    )
    monkeypatch.setattr(
        "autotoken.paypal_bind_executor._paypal_extract_ba_link",
        lambda **kwargs: (
            captured.update({"extract_kwargs": kwargs})
            or {
                "status": "success",
                "ba_token": "BA-AU",
                "approve_url": "https://www.paypal.com/agreements/approve?ba_token=BA-AU",
                "checkout_url": "https://pay.openai.com/c/pay/cs_demo#hash",
            }
        ),
    )
    monkeypatch.setattr(
        "autotoken.paypal_bind_executor.run_paypal_bind_task",
        lambda **kwargs: {
            "status": "success",
            "failure_stage": "",
            "message": "PayPal 绑定完成",
            "screenshot_paths": [],
            "checkout_url": kwargs["checkout_url"],
        },
    )
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"func": func, "params": params})
            or {"task_id": "task-paypal-au-provider-proxy", "command": command, "params": params}
        ),
    )

    api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="first@example.com",
            bind_link_payload={"plan_name": "chatgptplusplan"},
            proxy_api_provider="cliproxy",
            paypal_browser="protocol",
            paypal_country="JP",
            paypal_ba_mode="us",
            paypal_ba_payment_method_country="AU",
            manual_confirm=False,
            paypal_mode="create_account",
            autofill_enabled=True,
            billing_phone="+819012345678",
            sms_url="https://sms.example.test/token=demo",
        )
    )

    result = captured["func"]()

    assert result["status"] == "success"
    assert captured["api_calls"][:2] == [
        ("https://api.cliproxy.io/white/api?region=JP&num=1&time=30&format=n&type=json", 30),
        ("https://api.cliproxy.io/white/api?region=AU&num=1&time=30&format=n&type=json", 30),
    ]
    assert captured["extract_kwargs"]["provider_proxy_url"] == "socks5h://203.0.113.7:7104"
    assert captured["extract_kwargs"]["payment_method_country"] == "AU"


def test_paypal_protocol_requires_jp_checkout_proxy_before_extract(monkeypatch):
    captured = {"progress": []}
    accounts = [{"email": "first@example.com"}]

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda rows, email: accounts[0] if email == "first@example.com" else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_extract_account_access_token", lambda email: f"token-{email}")
    monkeypatch.setattr(api, "_probe_proxy_exit_ip", lambda _proxy: "")
    monkeypatch.setattr(
        "autotoken.services.paypal_proxy.paypal_proxy_exit_location",
        lambda *_args, **_kwargs: {
            "country_code": "US",
            "region": "California",
            "city": "Los Angeles",
            "ip": "203.0.113.20",
        },
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: {"email": email, **kwargs})
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda _payload: None)
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr(
        "autotoken.paypal_bind_executor._paypal_extract_ba_link",
        lambda **_kwargs: pytest.fail("BA extraction should not start when checkout proxy is not JP"),
    )
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"func": func, "params": params})
            or {"task_id": "task-paypal-jp-guard", "command": command, "params": params}
        ),
    )

    api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="first@example.com",
            bind_link_payload={"plan_name": "chatgptplusplan"},
            proxy_url="socks5h://198.51.100.8:1080",
            paypal_browser="protocol",
            paypal_country="JP",
            manual_confirm=False,
            paypal_mode="create_account",
            autofill_enabled=True,
            billing_phone="+819012345678",
            sms_url="https://sms.example.test/token=demo",
            pending_retry_attempts=0,
        )
    )

    with pytest.raises(api.TaskResultError) as exc_info:
        captured["func"]()

    result = exc_info.value.task_result
    assert result["status"] == "failed"
    assert result["failure_stage"] == "paypal_checkout_proxy_country_mismatch"
    assert result["checkout_proxy_country"] == "US"
    assert any(event["stage"] == "paypal_checkout_proxy_country_mismatch" for event in captured["progress"])


def test_paypal_protocol_blocks_when_checkout_proxy_country_probe_is_unknown(monkeypatch):
    captured = {"progress": []}
    accounts = [{"email": "first@example.com"}]

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda rows, email: accounts[0] if email == "first@example.com" else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_extract_account_access_token", lambda email: f"token-{email}")
    monkeypatch.setattr(api, "_probe_proxy_exit_ip", lambda _proxy: "")
    monkeypatch.setattr("autotoken.services.paypal_proxy.paypal_proxy_exit_location", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: {"email": email, **kwargs})
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda _payload: None)
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr(
        "autotoken.paypal_bind_executor._paypal_extract_ba_link",
        lambda **_kwargs: pytest.fail("BA extraction should not start when checkout proxy country is unknown"),
    )
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"func": func, "params": params})
            or {"task_id": "task-paypal-jp-guard-unknown", "command": command, "params": params}
        ),
    )

    api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="first@example.com",
            bind_link_payload={"plan_name": "chatgptplusplan"},
            proxy_url="socks5h://198.51.100.8:1080",
            paypal_browser="protocol",
            paypal_country="JP",
            manual_confirm=False,
            paypal_mode="create_account",
            autofill_enabled=True,
            billing_phone="+819012345678",
            sms_url="https://sms.example.test/token=demo",
            pending_retry_attempts=0,
        )
    )

    with pytest.raises(api.TaskResultError) as exc_info:
        captured["func"]()

    result = exc_info.value.task_result
    assert result["status"] == "failed"
    assert result["failure_stage"] == "paypal_checkout_proxy_country_mismatch"
    assert result["checkout_proxy_country"] == ""
    assert "无法确认是否为 JP" in result["message"]
    assert any(event["stage"] == "paypal_checkout_proxy_country_mismatch" for event in captured["progress"])


def test_paypal_protocol_ba_retry_reuses_same_sticky_proxies(monkeypatch):
    captured = {"progress": [], "api_calls": [], "extract_calls": []}
    accounts = [{"email": "first@example.com"}]

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda rows, email: accounts[0] if email == "first@example.com" else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_extract_account_access_token", lambda email: f"token-{email}")
    monkeypatch.setattr(api, "_probe_proxy_exit_ip", lambda _proxy: "")
    monkeypatch.setattr(
        "autotoken.services.paypal_proxy.paypal_proxy_exit_location",
        lambda *_args, **_kwargs: {"country_code": "JP", "region": "Tokyo", "city": "Tokyo", "ip": "198.51.100.8"},
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: {"email": email, **kwargs})
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda _payload: None)
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/plain"}

        def __init__(self, text):
            self.text = text

    def fake_get(url, timeout):
        captured["api_calls"].append((url, timeout))
        if "region=US" in url:
            return FakeResponse("107.150.109.49:7104")
        return FakeResponse("103.49.62.181:19004")

    monkeypatch.setattr(api.requests, "get", fake_get)
    monkeypatch.setattr(
        "autotoken.paypal_bind_executor._extract_auth_session_context",
        lambda _email: {
            "access_token": "extract-token",
            "session_token": "session-token",
            "cookie_header": "__Secure-next-auth.session-token=session-token",
        },
    )

    attempt = {"count": 0}

    def fake_extract(**kwargs):
        attempt["count"] += 1
        captured["extract_calls"].append((kwargs["proxy_url"], kwargs["provider_proxy_url"]))
        if attempt["count"] == 1:
            return {
                "status": "failed",
                "failure_stage": "extract_ba_link_pplink_timeout",
                "message": "timeout",
            }
        return {
            "status": "success",
            "ba_token": "BA-RETRY",
            "approve_url": "https://www.paypal.com/agreements/approve?ba_token=BA-RETRY",
            "checkout_url": "https://pay.openai.com/c/pay/cs_demo#hash",
        }

    monkeypatch.setattr("autotoken.paypal_bind_executor._paypal_extract_ba_link", fake_extract)
    monkeypatch.setattr(
        "autotoken.paypal_bind_executor.run_paypal_bind_task",
        lambda **kwargs: {
            "status": "success",
            "failure_stage": "",
            "message": "PayPal 绑定完成",
            "screenshot_paths": [],
            "checkout_url": kwargs["checkout_url"],
        },
    )
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"func": func, "params": params})
            or {"task_id": "task-paypal-sticky-retry", "command": command, "params": params}
        ),
    )

    api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="first@example.com",
            bind_link_payload={"plan_name": "chatgptplusplan"},
            proxy_api_provider="cliproxy",
            paypal_browser="protocol",
            paypal_country="JP",
            paypal_ba_mode="us",
            manual_confirm=False,
            paypal_mode="create_account",
            autofill_enabled=True,
            billing_phone="+819012345678",
            sms_url="https://sms.example.test/token=demo",
        )
    )

    result = captured["func"]()

    assert result["status"] == "success"
    assert captured["api_calls"][:2] == [
        ("https://api.cliproxy.io/white/api?region=JP&num=1&time=30&format=n&type=json", 30),
        ("https://api.cliproxy.io/white/api?region=US&num=1&time=30&format=n&type=json", 30),
    ]
    assert len(captured["api_calls"]) == 2
    assert captured["extract_calls"] == [
        ("socks5h://103.49.62.181:19004", "socks5h://107.150.109.49:7104"),
        ("socks5h://103.49.62.181:19004", "socks5h://107.150.109.49:7104"),
    ]


def test_paypal_proxy_api_rejects_html_response(monkeypatch):
    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/html"}
        text = "<!doctype html><html><body>login</body></html>"

    monkeypatch.setattr(api.requests, "get", lambda url, timeout: FakeResponse())

    with pytest.raises(RuntimeError, match="返回 HTML 页面"):
        api._fetch_proxy_from_api_url(
            "https://dashboard.1024proxy.com/getporxy/traffic?demo=1",
            default_auth_scheme="socks5h",
            provider="1024proxy",
        )


def test_paypal_task_runner_existing_account_raises_task_result_error(monkeypatch):
    captured = {"progress": []}

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: accounts[0] if email == "user@example.com" else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(
        "autotoken.accounts.update_account",
        lambda email, **kwargs: captured.setdefault("updates", []).append((email, kwargs)),
    )
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))

    def fake_run_paypal_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        kwargs["on_progress"]({"stage": "paypal_login_password", "message": "正在填写 PayPal 密码"})
        return {
            "status": "needs_review",
            "failure_stage": "paypal_authorize",
            "message": "等待 PayPal 登录/授权超时，需要人工确认",
            "screenshot_paths": ["data/paypal-needs-review.png"],
        }

    monkeypatch.setattr("autotoken.paypal_bind_executor.run_paypal_bind_task", fake_run_paypal_bind_task)
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"func": func, "params": params})
            or {"task_id": "task-paypal-local-fail", "command": command, "params": params}
        ),
    )

    api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="user@example.com",
            checkout_url="https://pay.openai.com/demo",
            manual_confirm=False,
            paypal_mode="existing_account",
            paypal_email="paypal@example.com",
            paypal_password="Secret123!",
            timeout_seconds=180,
            pending_retry_attempts=0,
        )
    )

    with pytest.raises(api.TaskResultError) as exc:
        captured["func"]()

    task_result = exc.value.task_result

    assert task_result["status"] == "needs_review"
    assert task_result["failure_stage"] == "paypal_authorize"
    assert task_result["task_status"] == "failed"
    assert task_result["provider"] == "paypal"
    assert task_result["paypal_mode"] == "existing_account"
    assert task_result["paypal_auto_login"] is True
    assert task_result["screenshot_paths"] == ["data/paypal-needs-review.png"]
    assert captured["run_kwargs"]["paypal_mode"] == "existing_account"
    assert captured["run_kwargs"]["paypal_email"] == "paypal@example.com"
    assert captured["run_kwargs"]["paypal_password"] == "Secret123!"
    assert captured["updates"] == [
        (
            "user@example.com",
            {
                "last_bind_status": "needs_review",
                "last_bind_at": captured["updates"][0][1]["last_bind_at"],
                "last_checkout_url": "https://pay.openai.com/demo",
                "last_proxy_label": "",
                "last_bind_task_id": captured["updates"][0][1]["last_bind_task_id"],
                "last_bind_message": "等待 PayPal 登录/授权超时，需要人工确认",
                "last_bind_failure_stage": "paypal_authorize",
            },
        )
    ]
    assert captured["audit"]["status"] == "needs_review"
    assert captured["audit"]["task_status"] == "failed"
    assert captured["audit"]["flow"] == "paypal_existing_account"
    assert [event["stage"] for event in captured["progress"]] == [
        "paypal_starting",
        "paypal_login_password",
        "paypal_finished",
    ]


def test_paypal_task_runner_retries_transient_failure_from_pending_pool(monkeypatch):
    captured = {"progress": [], "calls": []}

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: accounts[0] if email == "user@example.com" else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: {"email": email, **kwargs})
    monkeypatch.setattr("autotoken.accounts.add_account", lambda *args, **kwargs: None)
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda _payload: None)
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr(api.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        api,
        "_convert_account_auth_session_to_cpa_auth",
        lambda _email, **_kwargs: {"auth_file": "cpa.json", "filename": "cpa.json"},
    )

    def fake_run_paypal_bind_task(**kwargs):
        captured["calls"].append(kwargs)
        if len(captured["calls"]) == 1:
            return {
                "status": "needs_review",
                "failure_stage": "paypal_authorize",
                "message": "等待 PayPal 登录/授权超时，需要人工确认",
                "screenshot_paths": [],
            }
        return {
            "status": "success",
            "failure_stage": "",
            "message": "PayPal 绑定完成",
            "screenshot_paths": [],
        }

    monkeypatch.setattr("autotoken.paypal_bind_executor.run_paypal_bind_task", fake_run_paypal_bind_task)
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"func": func, "params": params})
            or {"task_id": "task-paypal-retry", "command": command, "params": params}
        ),
    )

    api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="user@example.com",
            checkout_url="https://pay.openai.com/demo",
            manual_confirm=False,
            paypal_mode="existing_account",
            paypal_email="paypal@example.com",
            paypal_password="Secret123!",
            pending_retry_attempts=1,
        )
    )

    result = captured["func"]()

    assert result["status"] == "success"
    assert result.get("pending_retry_emails") in (None, [])
    assert result["retried_emails"] == ["user@example.com"]
    assert len(captured["calls"]) == 2
    assert any(event["stage"] == "paypal_pending_retry_queued" for event in captured["progress"])
    wait_events = [event for event in captured["progress"] if event["stage"] == "paypal_pending_retry_wait"]
    assert wait_events
    assert wait_events[0]["wait_seconds"] == 60.0
    assert any(event["stage"] == "paypal_pending_retry_account" for event in captured["progress"])


def test_paypal_task_runner_pending_retry_backoff_uses_60_then_120(monkeypatch):
    captured = {"progress": [], "calls": [], "sleeps": []}

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: accounts[0] if email == "user@example.com" else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: {"email": email, **kwargs})
    monkeypatch.setattr("autotoken.accounts.add_account", lambda *args, **kwargs: None)
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda _payload: None)
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr(api.time, "sleep", lambda seconds: captured["sleeps"].append(seconds))

    def fake_run_paypal_bind_task(**kwargs):
        captured["calls"].append(kwargs)
        if len(captured["calls"]) < 3:
            return {
                "status": "failed",
                "failure_stage": "paypal_card_linked",
                "message": "This card has already been added to another PayPal account.",
                "screenshot_paths": [],
            }
        return {
            "status": "success",
            "failure_stage": "",
            "message": "PayPal 绑定完成",
            "screenshot_paths": [],
        }

    monkeypatch.setattr("autotoken.paypal_bind_executor.run_paypal_bind_task", fake_run_paypal_bind_task)
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"func": func, "params": params})
            or {"task_id": "task-paypal-retry-backoff", "command": command, "params": params}
        ),
    )

    api.post_paypal_task(
        api.PayPalTaskParams(
            runner_mode="manual_checkout",
            email="user@example.com",
            checkout_url="https://pay.openai.com/demo",
            manual_confirm=False,
            paypal_mode="create_account",
            autofill_enabled=True,
            pending_retry_attempts=2,
            phone_accounts=[
                api.GoPayPhoneAccountParams(
                    phone_number="+18352880840",
                    sms_url="https://sms.example/one",
                    otp_channel="sms",
                ),
            ],
        )
    )

    result = captured["func"]()

    assert result["status"] == "success"
    assert len(captured["calls"]) == 3
    assert captured["sleeps"] == [60.0, 120.0]
    wait_events = [event for event in captured["progress"] if event["stage"] == "paypal_pending_retry_wait"]
    assert [event["wait_seconds"] for event in wait_events] == [60.0, 120.0]


def test_paypal_pending_retry_reason_treats_phone_limit_card_limit_and_return_timeout_as_retryable():
    assert (
        api._paypal_pending_retry_reason(
            {
                "status": "failed",
                "failure_stage": "paypal_phone_rejected",
                "message": "PayPal 拒绝当前手机号，请更换手机号",
            }
        )
        == "paypal_phone_rejected"
    )
    assert (
        api._paypal_pending_retry_reason(
            {
                "status": "failed",
                "failure_stage": "paypal_account_limited",
                "message": "Your account is limited. Please check your PayPal Account Overview page for information on how to resolve this problem.",
            }
        )
        == "paypal_account_limited"
    )
    assert (
        api._paypal_pending_retry_reason(
            {
                "status": "failed",
                "failure_stage": "paypal_card_linked",
                "message": "This card has already been added to another PayPal account.",
            }
        )
        == "paypal_card_linked"
    )
    assert (
        api._paypal_pending_retry_reason(
            {
                "status": "needs_review",
                "failure_stage": "paypal_return_timeout",
                "message": "等待回跳超时，需要人工确认",
            }
        )
        == "paypal_return_timeout"
    )


def test_post_gopay_bind_task_starts_background_task(monkeypatch):
    captured = {}

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: accounts[0] if email == "user@example.com" else None
    )
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

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
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

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "new@example.com"}])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: accounts[0] if email == "new@example.com" else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/new@example.com.json")
    monkeypatch.setattr(
        "autotoken.auth_session_store.get_auth_session_file", lambda email: f"data/auth_session/{email}.json"
    )
    monkeypatch.setattr("autotoken.runtime_config.get_register_domain", lambda: "openaibus.com")
    monkeypatch.setattr("autotoken.runtime_config.get_register_domains", lambda: ["openaibus.com", "rexmoxe.space"])
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))
    monkeypatch.setattr(
        "autotoken.accounts.update_account",
        lambda email, **kwargs: captured.setdefault("updates", []).append((email, kwargs)),
    )
    monkeypatch.setattr(api, "_gopay_auto_register_bind_delay_seconds", lambda: 0)
    monkeypatch.setattr("autotoken.manager.time.sleep", lambda _seconds: None)

    class FakeMailClient:
        def login(self):
            captured["mail_login"] += 1

        def create_temp_email(self, *args, **kwargs):
            attempts = captured.setdefault("mail_probe_attempts", 0) + 1
            captured["mail_probe_attempts"] = attempts
            if attempts == 1:
                raise Exception("身份认证失效,请重新登录")
            return (949, "new@example.com")

    monkeypatch.setattr("autotoken.mail.TemporaryEmailClient", FakeMailClient)

    def fake_register(mail_client, **kwargs):
        captured["register_kwargs"] = kwargs
        mail_client.create_temp_email()
        return {"email": "new@example.com", "status": "success", "auth_file": "data/auth_session/new@example.com.json"}

    monkeypatch.setattr("autotoken.manager.create_account_direct", fake_register)

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "email_used": "new@example.com",
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

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

    monkeypatch.setattr("autotoken.accounts.load_accounts", fake_load_accounts)
    monkeypatch.setattr("autotoken.accounts.find_account", fake_find_account)
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda acc: f"data/auth_session/{acc['email']}.json")
    monkeypatch.setattr(
        "autotoken.auth_session_store.get_auth_session_file", lambda email: f"data/auth_session/{email}.json"
    )
    monkeypatch.setattr("autotoken.runtime_config.get_register_domain", lambda: "openaibus.com")
    monkeypatch.setattr("autotoken.runtime_config.get_register_domains", lambda: ["openaibus.com"])
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))
    monkeypatch.setattr(
        "autotoken.accounts.update_account",
        lambda email, **kwargs: captured.setdefault("updates", []).append((email, kwargs)),
    )
    monkeypatch.setattr(api, "_gopay_auto_register_bind_delay_seconds", lambda: 0)

    class FakeMailClient:
        def login(self):
            captured["mail_login"] += 1

    monkeypatch.setattr("autotoken.mail.TemporaryEmailClient", FakeMailClient)

    def fake_register(mail_client, **kwargs):
        index = len(captured["register_kwargs"])
        captured["register_kwargs"].append(kwargs)
        return {"email": registered_emails[index], "status": "success"}

    monkeypatch.setattr("autotoken.manager.create_account_direct", fake_register)

    def fake_run_gopay_bind_task(**kwargs):
        email = kwargs["email"]
        captured["run_emails"].append(email)
        captured["run_phone_numbers"].append(kwargs["phone_number"])
        return {
            "status": "success",
            "message": f"GoPay 绑定完成: {email}",
            "email_used": email,
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

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
    for _email, update in captured["updates"]:
        assert update["last_bind_status"] == "success"
        assert update["status"] == accounts_module.STATUS_ACTIVE
        assert update["account_type"] == accounts_module.ACCOUNT_TYPE_PLUS
        assert update["plus_bound_at"] == update["last_bind_at"]


def test_gopay_task_runner_auto_register_retries_pending_after_first_round(monkeypatch):
    captured = {"mail_login": 0, "progress": [], "run_emails": [], "slept": []}
    registered_emails = ["new1@example.com", "new2@example.com"]

    def fake_load_accounts():
        return [{"email": email} for email in registered_emails]

    def fake_find_account(accounts, email):
        return next((account for account in accounts if account.get("email") == email), None)

    monkeypatch.setattr("autotoken.accounts.load_accounts", fake_load_accounts)
    monkeypatch.setattr("autotoken.accounts.find_account", fake_find_account)
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda acc: f"data/auth_session/{acc['email']}.json")
    monkeypatch.setattr(
        "autotoken.auth_session_store.get_auth_session_file", lambda email: f"data/auth_session/{email}.json"
    )
    monkeypatch.setattr("autotoken.runtime_config.get_register_domain", lambda: "openaibus.com")
    monkeypatch.setattr("autotoken.runtime_config.get_register_domains", lambda: ["openaibus.com"])
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))
    monkeypatch.setattr(
        "autotoken.accounts.update_account",
        lambda email, **kwargs: captured.setdefault("updates", []).append((email, kwargs)),
    )
    monkeypatch.setattr(api, "_gopay_auto_register_bind_delay_seconds", lambda: 0)
    monkeypatch.setattr(api.time, "sleep", lambda seconds: captured["slept"].append(seconds))
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))

    class FakeMailClient:
        def login(self):
            captured["mail_login"] += 1

    monkeypatch.setattr("autotoken.mail.TemporaryEmailClient", FakeMailClient)

    def fake_register(_mail_client, **_kwargs):
        return {"email": registered_emails[captured["mail_login"] - 1], "status": "success"}

    monkeypatch.setattr("autotoken.manager.create_account_direct", fake_register)

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

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"func": func, "params": params})
            or {"task_id": "task-auto-retry", "command": command, "params": params}
        ),
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

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "wallet@example.com"}])
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda accounts, email: accounts[0] if email == "wallet@example.com" else None,
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/wallet@example.com.json")
    monkeypatch.setattr(
        "autotoken.auth_session_store.get_auth_session_file", lambda email: f"data/auth_session/{email}.json"
    )
    monkeypatch.setattr("autotoken.runtime_config.get_register_domain", lambda: "openaibus.com")
    monkeypatch.setattr("autotoken.runtime_config.get_register_domains", lambda: ["openaibus.com"])
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))
    monkeypatch.setattr(
        "autotoken.accounts.update_account",
        lambda email, **kwargs: captured.setdefault("updates", []).append((email, kwargs)),
    )
    monkeypatch.setattr(api, "_gopay_auto_register_bind_delay_seconds", lambda: 0)
    monkeypatch.setattr(api.time, "sleep", lambda seconds: captured["slept"].append(seconds))
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))

    class FakeMailClient:
        def login(self):
            captured["mail_login"] += 1

    monkeypatch.setattr("autotoken.mail.TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr(
        "autotoken.manager.create_account_direct",
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

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"func": func, "params": params})
            or {"task_id": "task-auto-wallet-retry", "command": command, "params": params}
        ),
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

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "declined@example.com"}])
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda accounts, email: accounts[0] if email == "declined@example.com" else None,
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/declined@example.com.json")
    monkeypatch.setattr(
        "autotoken.auth_session_store.get_auth_session_file", lambda email: f"data/auth_session/{email}.json"
    )
    monkeypatch.setattr("autotoken.runtime_config.get_register_domain", lambda: "openaibus.com")
    monkeypatch.setattr("autotoken.runtime_config.get_register_domains", lambda: ["openaibus.com"])
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: None)
    monkeypatch.setattr(api, "_gopay_auto_register_bind_delay_seconds", lambda: 0)
    monkeypatch.setattr(api.time, "sleep", lambda seconds: captured["slept"].append(seconds))
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))

    class FakeMailClient:
        def login(self):
            captured["mail_login"] += 1

    monkeypatch.setattr("autotoken.mail.TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr(
        "autotoken.manager.create_account_direct",
        lambda _mail_client, **_kwargs: {"email": "declined@example.com", "status": "success"},
    )
    monkeypatch.setattr(
        "autotoken.gopay_executor.run_gopay_bind_task",
        lambda **kwargs: (
            captured["run_emails"].append(kwargs["email"])
            or {
                "status": "failed",
                "failure_stage": "checkout_not_approved",
                "message": "付款未获批准",
                "email_used": kwargs["email"],
            }
        ),
    )
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: (
            captured.update({"func": func, "params": params})
            or {"task_id": "task-auto-declined", "command": command, "params": params}
        ),
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

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "new@example.com"}])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: accounts[0] if email == "new@example.com" else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/new@example.com.json")
    monkeypatch.setattr(
        "autotoken.auth_session_store.get_auth_session_file", lambda email: f"data/auth_session/{email}.json"
    )
    monkeypatch.setattr("autotoken.runtime_config.get_register_domain", lambda: "openaibus.com")
    monkeypatch.setattr("autotoken.runtime_config.get_register_domains", lambda: ["openaibus.com"])
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: None)
    monkeypatch.setattr(api, "_gopay_auto_register_bind_delay_seconds", lambda: 12.5)
    monkeypatch.setattr(api.time, "sleep", lambda seconds: captured["slept"].append(seconds))
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))

    class FakeMailClient:
        def login(self):
            captured["mail_login"] += 1

    monkeypatch.setattr("autotoken.mail.TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr(
        "autotoken.manager.create_account_direct",
        lambda _mail_client, **_kwargs: {"email": "new@example.com", "status": "success"},
    )
    monkeypatch.setattr(
        "autotoken.gopay_executor.run_gopay_bind_task",
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
        "task_group": api.TASK_GROUP_GOPAY,
        "status": "running",
        "params": {"account_emails": ["user@example.com", "backup@example.com"]},
    }

    api._tasks["task-skip"] = task
    api._task_skip_signals["task-skip"] = signal
    try:
        result = api.post_task_skip_current()
        progress_updates.extend(task.get("progress_events") or [])
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
        calls.append(
            (kwargs["email"], kwargs["country_code"], kwargs["phone_number"], kwargs["sms_url"], kwargs["gopay_pin"])
        )
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


def test_auto_signup_wallet_already_linked_fails_without_midtrans_sleep(monkeypatch):
    progress_events = []
    slept = []

    class FakeResponse:
        status_code = 406
        text = '{"error_messages":["already linked"]}'

        def json(self):
            return {"error_messages": ["already linked"]}

    class FakeHttp:
        def __init__(self):
            self.calls = []

        def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return FakeResponse()

    fake_http = FakeHttp()
    monkeypatch.setattr(gopay_executor.time, "sleep", lambda seconds: slept.append(seconds))
    charger = gopay_executor.GoPayHttpCharger(
        http=fake_http,
        phone_number="87761973970",
        country_code="62",
        gopay_pin="558023",
        otp_provider=lambda: "123456",
        fail_already_linked_immediately=True,
        progress_callback=progress_events.append,
    )

    with pytest.raises(gopay_executor.GoPayAlreadyLinked):
        charger._midtrans_init_linking("snap-token")

    assert len(fake_http.calls) == 1
    assert slept == []
    stages = [event["stage"] for event in progress_events]
    assert "midtrans_already_linked_auto_wallet_failed" in stages
    assert "midtrans_already_linked" not in stages


def test_run_gopay_bind_task_retries_local_cooldown_skip_once(monkeypatch):
    calls = []
    slept = []

    def fake_run_once(**kwargs):
        calls.append(kwargs["email"])
        return {"status": "success", "message": "GoPay 绑定完成"}

    monkeypatch.setattr(gopay_executor, "_run_gopay_bind_task_once", fake_run_once)
    monkeypatch.setattr(
        gopay_executor, "_approve_blocked_remaining", lambda email: 30 if email == "first@example.com" else 0
    )
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
        event.get("retry_round") for event in progress_events if event.get("stage") == "gopay_pending_retry_account"
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

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: accounts[0] if email == "user@example.com" else None
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "autotoken.accounts.delete_account",
        lambda email: captured.setdefault("deleted_accounts", []).append(email) or True,
    )
    monkeypatch.setattr(
        "autotoken.auth_session_store.delete_auth_session",
        lambda email: captured.setdefault("deleted_sessions", []).append(email) or True,
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: progress_updates.append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))

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

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

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

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: accounts[0] if email == "user@example.com" else None
    )
    monkeypatch.setattr(
        "autotoken.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs))
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "checkout_url": "https://chatgpt.com/checkout/demo",
            "email_used": "user@example.com",
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

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

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: accounts[0] if email == "user@example.com" else None
    )
    monkeypatch.setattr(
        "autotoken.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs))
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "checkout_url": "https://chatgpt.com/checkout/demo",
            "email_used": "user@example.com",
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)
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

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    monkeypatch.setattr(
        "autotoken.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs))
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/account.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "success",
            "message": "GoPay 批量绑定完成: 成功 2/2 个账号",
            "email_used": "second@example.com",
            "successful_emails": ["first@example.com", "second@example.com"],
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

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


def test_gopay_task_runner_persists_session_only_batch_success_as_plus(monkeypatch, tmp_path):
    captured = {"progress": []}
    accounts_file = tmp_path / "accounts.json"
    auth_dir = tmp_path / "auth_session"
    auth_dir.mkdir()
    first_auth = auth_dir / "first.json"
    second_auth = auth_dir / "second.json"
    first_auth.write_text("{}", encoding="utf-8")
    second_auth.write_text("{}", encoding="utf-8")
    auth_files = {
        "first@example.com": str(first_auth),
        "second@example.com": str(second_auth),
    }

    monkeypatch.setattr(accounts_module, "ACCOUNTS_FILE", accounts_file)
    accounts_module.save_accounts([])
    monkeypatch.setattr("autotoken.auth_session_store.get_auth_session_file", lambda email: auth_files.get(email, ""))
    monkeypatch.setattr(
        api, "_resolve_status_auth_file", lambda acc: auth_files.get((acc.get("email") or "").lower(), "")
    )
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "success",
            "message": "GoPay 批量绑定完成: 成功 2/2 个账号",
            "email_used": "second@example.com",
            "successful_emails": ["first@example.com", "second@example.com"],
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-session-only-plus", "command": command, "params": params}

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
    saved = {account["email"]: account for account in accounts_module.load_accounts()}

    assert result["task_status"] == "completed"
    assert saved["first@example.com"]["account_type"] == accounts_module.ACCOUNT_TYPE_PLUS
    assert saved["second@example.com"]["account_type"] == accounts_module.ACCOUNT_TYPE_PLUS
    assert saved["first@example.com"]["status"] == accounts_module.STATUS_ACTIVE
    assert saved["second@example.com"]["status"] == accounts_module.STATUS_ACTIVE


def test_gopay_auto_signup_existing_accounts_continues_after_success(monkeypatch):
    captured = {"updates": [], "progress": [], "calls": [], "registered": 0}
    accounts = [{"email": "first@example.com"}, {"email": "second@example.com"}]

    class FakeWallet:
        def __init__(self, index):
            self.phone_number = f"8770000000{index}"
            self.closed = []

        def as_phone_account(self):
            return {
                "country_code": "62",
                "phone_number": self.phone_number,
                "sms_url": f"http://local/otp/{self.phone_number}",
                "gopay_pin": "558023",
            }

        def close(self, success=False):
            self.closed.append(success)

    monkeypatch.setenv("REKBERINAJA_ENABLED", "0")
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    monkeypatch.setattr(
        "autotoken.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs))
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/account.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))

    def fake_register_gopay_wallet(**_kwargs):
        captured["registered"] += 1
        return FakeWallet(captured["registered"])

    monkeypatch.setattr("autotoken.gopay_auto_register.register_gopay_wallet", fake_register_gopay_wallet)

    def fake_run_gopay_bind_task(**kwargs):
        captured["calls"].append(kwargs["email"])
        return {
            "status": "success",
            "message": f"GoPay 绑定完成: {kwargs['email']}",
            "email_used": kwargs["email"],
            "successful_emails": [kwargs["email"]],
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-auto-signup-batch-success", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="first@example.com",
            account_emails=["first@example.com", "second@example.com"],
            gopay_pin="558023",
            gopay_auto_signup=True,
        )
    )

    result = captured["func"]()

    assert result["task_status"] == "completed"
    assert captured["calls"] == ["first@example.com", "second@example.com"]
    assert result["successful_emails"] == ["first@example.com", "second@example.com"]
    assert len(result["auto_signup_account_results"]) == 2
    assert [email for email, _update in captured["updates"]] == ["first@example.com", "second@example.com"]


def test_gopay_auto_signup_existing_accounts_continues_after_failure(monkeypatch):
    captured = {"updates": [], "progress": [], "calls": [], "registered": 0}
    accounts = [{"email": "first@example.com"}, {"email": "second@example.com"}]

    class FakeWallet:
        phone_number = "87700000001"

        def as_phone_account(self):
            return {
                "country_code": "62",
                "phone_number": self.phone_number,
                "sms_url": f"http://local/otp/{self.phone_number}",
                "gopay_pin": "558023",
            }

        def close(self, success=False):
            pass

    monkeypatch.setenv("REKBERINAJA_ENABLED", "0")
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    monkeypatch.setattr(
        "autotoken.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs))
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/account.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))

    def fake_register_gopay_wallet(**_kwargs):
        captured["registered"] += 1
        return FakeWallet()

    monkeypatch.setattr("autotoken.gopay_auto_register.register_gopay_wallet", fake_register_gopay_wallet)

    def fake_run_gopay_bind_task(**kwargs):
        captured["calls"].append(kwargs["email"])
        if kwargs["email"] == "first@example.com":
            return {
                "status": "failed",
                "failure_stage": "fetch_otp",
                "message": "GoPay 绑定 OTP 未收到",
                "email_used": kwargs["email"],
            }
        return {
            "status": "success",
            "message": f"GoPay 绑定完成: {kwargs['email']}",
            "email_used": kwargs["email"],
            "successful_emails": [kwargs["email"]],
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-auto-signup-batch-failure", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="first@example.com",
            account_emails=["first@example.com", "second@example.com"],
            gopay_pin="558023",
            gopay_auto_signup=True,
        )
    )

    result = captured["func"]()

    assert result["task_status"] == "completed"
    assert result["failure_stage"] == "partial_failed"
    assert captured["calls"] == ["first@example.com", "second@example.com"]
    assert result["successful_emails"] == ["second@example.com"]
    assert result["failed_emails"][0]["email"] == "first@example.com"
    assert [email for email, _update in captured["updates"]] == ["second@example.com"]


def test_gopay_auto_signup_probe_error_does_not_keep_buying_numbers(monkeypatch):
    captured = {"progress": [], "registered": 0}
    accounts = [{"email": "first@example.com"}]

    monkeypatch.setenv("GOPAY_AUTO_SIGNUP_WALLET_ATTEMPTS", "3")
    monkeypatch.setenv("REKBERINAJA_ENABLED", "0")
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/account.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))

    def fake_register_gopay_wallet(**_kwargs):
        captured["registered"] += 1
        raise gopay_auto_register.GoPaySignupProbeError("GoPay 注册前探测异常: status=403")

    monkeypatch.setattr("autotoken.gopay_auto_register.register_gopay_wallet", fake_register_gopay_wallet)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-auto-signup-probe-failed", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="first@example.com",
            account_emails=["first@example.com"],
            gopay_pin="558023",
            gopay_auto_signup=True,
        )
    )

    with pytest.raises(api.TaskResultError) as exc_info:
        captured["func"]()
    result = exc_info.value.task_result

    assert captured["registered"] == 1
    assert result["task_status"] == "failed"
    assert any(item.get("stage") == "gopay_wallet_auto_signup_probe_failed" for item in captured["progress"])


def test_gopay_auto_signup_rate_limited_stops_auto_register_batch(monkeypatch):
    captured = {"mail_login": 0, "progress": [], "registered": 0, "registered_accounts": []}
    registered_emails = ["new1@example.com", "new2@example.com"]

    def fake_load_accounts():
        return [{"email": email} for email in registered_emails]

    def fake_find_account(accounts, email):
        return next((account for account in accounts if account.get("email") == email), None)

    monkeypatch.setenv("GOPAY_AUTO_SIGNUP_WALLET_ATTEMPTS", "3")
    monkeypatch.setenv("REKBERINAJA_ENABLED", "0")
    monkeypatch.setattr("autotoken.accounts.load_accounts", fake_load_accounts)
    monkeypatch.setattr("autotoken.accounts.find_account", fake_find_account)
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda acc: f"data/auth_session/{acc['email']}.json")
    monkeypatch.setattr(
        "autotoken.auth_session_store.get_auth_session_file", lambda email: f"data/auth_session/{email}.json"
    )
    monkeypatch.setattr("autotoken.runtime_config.get_register_domain", lambda: "openaibus.com")
    monkeypatch.setattr("autotoken.runtime_config.get_register_domains", lambda: ["openaibus.com"])
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))
    monkeypatch.setattr(
        "autotoken.accounts.update_account",
        lambda email, **kwargs: captured.setdefault("updates", []).append((email, kwargs)),
    )
    monkeypatch.setattr(api, "_gopay_auto_register_bind_delay_seconds", lambda: 0)
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))

    class FakeMailClient:
        def login(self):
            captured["mail_login"] += 1

    monkeypatch.setattr("autotoken.mail.TemporaryEmailClient", FakeMailClient)

    def fake_register(_mail_client, **_kwargs):
        email = registered_emails[len(captured["registered_accounts"])]
        captured["registered_accounts"].append(email)
        return {"email": email, "status": "success"}

    monkeypatch.setattr("autotoken.manager.create_account_direct", fake_register)

    def fake_register_gopay_wallet(**_kwargs):
        captured["registered"] += 1
        raise RuntimeError(
            'signup initiate 未返回 otp_token: {"success":false,"errors":[{"code":"scp-cvs:error:ratelimit:init_verification","message":"Please contact Customer Service for assistance"}]}'
        )

    monkeypatch.setattr("autotoken.gopay_auto_register.register_gopay_wallet", fake_register_gopay_wallet)
    monkeypatch.setattr(
        "autotoken.gopay_executor.run_gopay_bind_task",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("bind task should not run after signup rate limit")),
    )

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-auto-signup-rate-limited", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="",
            auto_register=True,
            auto_register_count=2,
            gopay_auto_signup=True,
            gopay_pin="558023",
        )
    )

    with pytest.raises(api.TaskResultError) as exc_info:
        captured["func"]()
    result = exc_info.value.task_result

    assert captured["mail_login"] == 1
    assert captured["registered_accounts"] == ["new1@example.com"]
    assert captured["registered"] == 1
    assert result["failure_stage"] == "gopay_wallet_rate_limited"
    assert result["auto_register_attempted"] == 1
    assert result["failed_emails"][0]["email"] == "new1@example.com"
    assert any(item.get("stage") == "gopay_wallet_auto_signup_rate_limited" for item in captured["progress"])
    assert not any(item.get("stage") == "gopay_wallet_auto_signup_retry" for item in captured["progress"])


def test_gopay_auto_signup_rate_limited_stops_existing_accounts_batch(monkeypatch):
    captured = {"progress": [], "registered": 0, "calls": []}
    accounts = [{"email": "first@example.com"}, {"email": "second@example.com"}]

    monkeypatch.setenv("GOPAY_AUTO_SIGNUP_WALLET_ATTEMPTS", "3")
    monkeypatch.setenv("REKBERINAJA_ENABLED", "0")
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/account.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))

    def fake_register_gopay_wallet(**_kwargs):
        captured["registered"] += 1
        raise RuntimeError(
            'signup initiate 未返回 otp_token: {"success":false,"errors":[{"code":"scp-cvs:error:ratelimit:init_verification","message":"Please contact Customer Service for assistance"}]}'
        )

    monkeypatch.setattr("autotoken.gopay_auto_register.register_gopay_wallet", fake_register_gopay_wallet)
    monkeypatch.setattr(
        "autotoken.gopay_executor.run_gopay_bind_task",
        lambda **kwargs: captured["calls"].append(kwargs["email"]) or {"status": "success"},
    )

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-existing-signup-rate-limited", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="first@example.com",
            account_emails=["first@example.com", "second@example.com"],
            gopay_pin="558023",
            gopay_auto_signup=True,
        )
    )

    with pytest.raises(api.TaskResultError) as exc_info:
        captured["func"]()
    result = exc_info.value.task_result

    assert captured["registered"] == 1
    assert captured["calls"] == []
    assert result["failure_stage"] == "gopay_wallet_rate_limited"
    assert result["failed_emails"][0]["email"] == "first@example.com"
    assert result["attempted_emails"] == ["first@example.com"]
    assert any(item.get("stage") == "gopay_wallet_auto_signup_rate_limited" for item in captured["progress"])
    assert not any(item.get("stage") == "gopay_wallet_auto_signup_retry" for item in captured["progress"])


def test_gopay_auto_signup_network_error_does_not_buy_new_number(monkeypatch):
    captured = {"progress": [], "registered": 0, "calls": []}
    accounts = [{"email": "first@example.com"}, {"email": "second@example.com"}]

    monkeypatch.setenv("GOPAY_AUTO_SIGNUP_WALLET_ATTEMPTS", "3")
    monkeypatch.setenv("REKBERINAJA_ENABLED", "0")
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/account.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))

    def fake_register_gopay_wallet(**_kwargs):
        captured["registered"] += 1
        raise RuntimeError(
            "Failed to perform, curl: (97) Recv failure: Connection was reset. "
            "See https://curl.se/libcurl/c/libcurl-errors.html first for more details."
        )

    monkeypatch.setattr("autotoken.gopay_auto_register.register_gopay_wallet", fake_register_gopay_wallet)
    monkeypatch.setattr(
        "autotoken.gopay_executor.run_gopay_bind_task",
        lambda **kwargs: captured["calls"].append(kwargs["email"]) or {"status": "success"},
    )

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-existing-signup-network-error", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="first@example.com",
            account_emails=["first@example.com", "second@example.com"],
            gopay_pin="558023",
            gopay_auto_signup=True,
        )
    )

    with pytest.raises(api.TaskResultError) as exc_info:
        captured["func"]()
    result = exc_info.value.task_result

    assert captured["registered"] == 1
    assert captured["calls"] == []
    assert result["failure_stage"] == "gopay_wallet_network_error"
    assert any(item.get("stage") == "gopay_wallet_auto_signup_network_error" for item in captured["progress"])
    assert not any(item.get("stage") == "gopay_wallet_auto_signup_retry" for item in captured["progress"])


def test_gopay_task_runner_marks_batch_success_account_plus_immediately(monkeypatch):
    captured = {"updates": [], "progress": []}
    accounts = [{"email": "first@example.com"}, {"email": "second@example.com"}]

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    monkeypatch.setattr(
        "autotoken.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs))
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/account.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))

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

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

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

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    monkeypatch.setattr(
        "autotoken.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs))
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/account.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "success",
            "message": "GoPay 批量绑定完成: 成功 2/2 个账号",
            "email_used": "second@example.com",
            "checkout_url": "https://pay.openai.com/c/pay/cs_done",
            "successful_emails": ["first@example.com", "second@example.com"],
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

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
    assert sorted(email for email, _acc, _headless in captured["oauth_calls"]) == [
        "first@example.com",
        "second@example.com",
    ]
    assert all(headless is False for _email, _acc, headless in captured["oauth_calls"])
    stages = [progress["stage"] for progress in captured["progress"]]
    assert stages.count("gopay_oauth_login_started") == 2
    assert stages.count("gopay_oauth_login_done") == 2
    assert all(update["account_type"] == accounts_module.ACCOUNT_TYPE_PLUS for _email, update in captured["updates"])
    assert all("credentials_exported" not in update for _email, update in captured["updates"])
    assert all("credentials_exported_at" not in update for _email, update in captured["updates"])


def test_gopay_task_runner_converts_session_to_cpa_when_oauth_not_selected(monkeypatch):
    captured = {"updates": [], "progress": [], "cpa_calls": []}
    account = {"email": "first@example.com", "password": "pw1", "account_type": "free"}

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda loaded, email: account if email == account["email"] else None,
    )
    monkeypatch.setattr(
        "autotoken.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs))
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/account.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "email_used": "first@example.com",
            "checkout_url": "https://pay.openai.com/c/pay/cs_done",
            "successful_emails": ["first@example.com"],
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)
    monkeypatch.setattr(
        api,
        "_run_account_codex_login_once",
        lambda *_args, **_kwargs: pytest.fail("OAuth login should not run when auto_oauth_after_success is false"),
    )

    def fake_convert_session(email, *, account=None, force_account_type=None):
        captured["cpa_calls"].append((email, force_account_type))
        return {
            "email": email,
            "auth_file": f"data/auths/{email}.json",
            "filename": f"codex-{email}-plus-demo.json",
            "plan_type": "plus",
            "id_token_synthetic": True,
            "refresh_token_present": False,
            "account": None,
        }

    monkeypatch.setattr(api, "_convert_account_auth_session_to_cpa_auth", fake_convert_session)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-796", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="first@example.com",
            account_emails=["first@example.com"],
            phone_number="+6287761973970",
            country_code="62",
            sms_url="https://it.tgflare.com/api/record?token=demo",
            gopay_pin="558023",
            auto_oauth_after_success=False,
        )
    )

    result = captured["func"]()

    assert result["task_status"] == "completed"
    assert captured["cpa_calls"] == []
    assert "session_cpa_converted_emails" not in result
    assert "oauth_scheduled_emails" not in result
    stages = [progress["stage"] for progress in captured["progress"]]
    assert "gopay_oauth_login_skipped" in stages
    assert "gopay_session_cpa_convert_started" not in stages
    assert "gopay_session_cpa_convert_done" not in stages
    assert "gopay_oauth_login_started" not in stages
    assert all(update["account_type"] == accounts_module.ACCOUNT_TYPE_PLUS for _email, update in captured["updates"])


def test_gopay_task_runner_auto_oauth_retries_twice_after_success(monkeypatch):
    captured = {"updates": [], "progress": [], "oauth_calls": []}
    oauth_done = threading.Event()
    account = {"email": "retry@example.com", "password": "pw1", "account_type": "free"}

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda loaded, email: account if email == account["email"] else None,
    )
    monkeypatch.setattr(
        "autotoken.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs))
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/account.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))
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

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

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

    monkeypatch.setattr("autotoken.admin_state.get_admin_email", lambda: "owner@example.com")
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.update_account",
        lambda email, **kwargs: captured.setdefault("updated", {"email": email, **kwargs}) or {**account, **kwargs},
    )

    result = _account_management_update_account_type("USER@example.com", "plus")

    assert captured["updated"] == {"email": "user@example.com", "account_type": "plus"}
    assert result["account"]["email"] == "user@example.com"
    assert result["account"]["account_type"] == "plus"


def test_update_account_type_rejects_invalid_type(monkeypatch):
    monkeypatch.setattr("autotoken.admin_state.get_admin_email", lambda: "owner@example.com")

    with pytest.raises(api.HTTPException) as exc:
        _account_management_update_account_type("user@example.com", "bad")

    assert exc.value.status_code == 400


def test_update_account_type_rejects_main_account(monkeypatch):
    monkeypatch.setattr("autotoken.admin_state.get_admin_email", lambda: "owner@example.com")

    with pytest.raises(api.HTTPException) as exc:
        _account_management_update_account_type("owner@example.com", "team")

    assert exc.value.status_code == 400


def _account_management_update_account_type(email, account_type):
    from autotoken.api_routes.account_management import AccountTypeUpdateParams

    routes = _account_management_routes()
    return routes["update_account_type"](email, AccountTypeUpdateParams(account_type=account_type))


def _account_management_delete_accounts_batch(emails, continue_on_error=True):
    from autotoken.api_routes.account_management import DeleteBatchParams

    routes = _account_management_routes()
    return routes["delete_accounts_batch"](DeleteBatchParams(emails=emails, continue_on_error=continue_on_error))


def _account_management_routes():
    from autotoken.api_routes.account_management import create_account_management_router

    return {
        route.endpoint.__name__: route.endpoint
        for route in create_account_management_router(
            playwright_lock=api._playwright_lock,
            playwright_executor=api._pw_executor,
            current_busy_detail=api._current_busy_detail,
            is_main_account_email=api._is_main_account_email,
            sanitize_account=api._sanitize_account,
        ).routes
    }


def _account_exports_routes():
    from autotoken.api_routes.account_exports import (
        AccountCredentialExportParams,
        AccountExportStatusUpdateParams,
        create_account_exports_router,
    )

    routes = {
        route.endpoint.__name__: route.endpoint
        for route in create_account_exports_router(
            normalize_email=api._normalized_email,
            is_main_account_email=api._is_main_account_email,
            sanitize_account=api._sanitize_account,
            current_time=api.time.time,
        ).routes
    }
    return routes, AccountCredentialExportParams, AccountExportStatusUpdateParams


def _export_account_credentials(**kwargs):
    routes, AccountCredentialExportParams, _AccountExportStatusUpdateParams = _account_exports_routes()
    return routes["export_account_credentials"](AccountCredentialExportParams(**kwargs))


def _update_accounts_export_status(**kwargs):
    routes, _AccountCredentialExportParams, AccountExportStatusUpdateParams = _account_exports_routes()
    return routes["update_accounts_export_status"](AccountExportStatusUpdateParams(**kwargs))


def _export_account_sub_auths(emails):
    from autotoken.api_routes.account_cpa_auths import AccountEmailBatchParams, create_account_cpa_auths_router

    routes = {
        route.endpoint.__name__: route.endpoint
        for route in create_account_cpa_auths_router(
            normalize_email=api._normalized_email,
            resolve_codex_auth_file=api._resolve_codex_auth_file,
            update_account_cpa_auth_plan_type=api._update_account_cpa_auth_plan_type,
            current_time=api.time.time,
        ).routes
    }
    return routes["export_account_sub_auths"](AccountEmailBatchParams(emails=emails))


def _export_account_cpa_auths(emails):
    from autotoken.api_routes.account_cpa_auths import AccountEmailBatchParams, create_account_cpa_auths_router

    routes = {
        route.endpoint.__name__: route.endpoint
        for route in create_account_cpa_auths_router(
            normalize_email=api._normalized_email,
            resolve_codex_auth_file=api._resolve_codex_auth_file,
            update_account_cpa_auth_plan_type=api._update_account_cpa_auth_plan_type,
            verify_plus_plan=api._verify_plus_plan,
            normalize_observed_auth_plan=api._normalize_observed_auth_plan,
            mark_failed_account=api._mark_account_plan_verification_failed,
            safe_email_summary=api._safe_email_summary,
            current_time=api.time.time,
        ).routes
    }
    return routes["export_account_cpa_auths"](AccountEmailBatchParams(emails=emails))


def test_export_account_credentials_uses_fixed_three_column_format(monkeypatch):
    captured = {"updates": []}
    monkeypatch.setattr(
        "autotoken.accounts.load_accounts",
        lambda: [
            {"email": "first@example.com", "password": "pw1", "status": "active", "seat_type": "codex"},
            {"email": "second@example.com", "password": "pw2", "status": "plus", "seat_type": "unknown"},
        ],
    )
    monkeypatch.setattr(
        "autotoken.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs))
    )
    monkeypatch.setattr(api.time, "time", lambda: 1777777777.0)

    result = _export_account_credentials(
        emails=["SECOND@example.com", "missing@example.com"],
        line_format="{email}-----{password}",
    )

    assert result["count"] == 1
    assert result["content"] == "second@example.com-----pw2-----https://gptcode.external.cc.cd/"
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


def test_export_account_credentials_skips_session_only_stubs(monkeypatch):
    from autotoken import accounts as accounts_module

    captured = {"updates": []}
    monkeypatch.setattr(
        "autotoken.accounts.load_accounts",
        lambda: [
            {
                "email": "stub@example.com",
                "status": accounts_module.STATUS_ACTIVE,
                "account_source": accounts_module.ACCOUNT_SOURCE_AUTH_SESSION_STUB,
            },
            {"email": "real@example.com", "password": "pw", "status": accounts_module.STATUS_ACTIVE},
        ],
    )
    monkeypatch.setattr(
        "autotoken.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs))
    )
    monkeypatch.setattr(api.time, "time", lambda: 1777777777.0)

    result = _export_account_credentials()

    assert result["content"] == "real@example.com-----pw-----https://gptcode.external.cc.cd/"
    assert result["count"] == 1
    assert result["skipped_session_only"] == ["stub@example.com"]
    assert result["exported_emails"] == ["real@example.com"]
    assert captured["updates"] == [
        (
            "real@example.com",
            {"credentials_exported": True, "credentials_exported_at": 1777777777.0},
        )
    ]


def test_export_account_credentials_uses_luckmail_token_as_password(monkeypatch):
    monkeypatch.setattr(
        "autotoken.accounts.load_accounts",
        lambda: [
            {
                "email": "luck@example.com",
                "password": "login-password",
                "cloudmail_account_id": "tok_luckmail_secret",
                "mail_provider": "luckmail",
            }
        ],
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda _email, **_kwargs: None)

    result = _export_account_credentials(
        emails=["luck@example.com"],
        line_format="{email}-----{password}",
    )

    assert result["content"] == "luck@example.com-----tok_luckmail_secret-----https://mail.cpacc.us.ci/"


def test_export_account_credentials_uses_hotmail_mailapi_url(monkeypatch):
    monkeypatch.setattr(
        "autotoken.accounts.load_accounts",
        lambda: [
            {
                "email": "user@hotmail.com",
                "password": "login-password",
                "cloudmail_account_id": "user@hotmail.com",
                "mail_provider": "outlook",
            }
        ],
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda _email, **_kwargs: None)
    monkeypatch.setattr(
        "autotoken.trade.outlook_mailapi_urls_by_email",
        lambda: {"user@hotmail.com": "https://mailapi.icu/key?type=html&orderNo=abc"},
    )

    result = _export_account_credentials(emails=["user@hotmail.com"])

    assert result["content"] == (
        "user@hotmail.com-----login-password-----https://mailapi.icu/key?type=html&orderNo=abc"
    )


def test_export_account_credentials_allows_already_exported_accounts(monkeypatch):
    monkeypatch.setattr(
        "autotoken.accounts.load_accounts",
        lambda: [
            {
                "email": "exported@example.com",
                "password": "pw",
                "credentials_exported": True,
                "credentials_exported_at": 1770000000.0,
            }
        ],
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda _email, **_kwargs: None)

    result = _export_account_credentials(
        emails=["exported@example.com"],
        line_format="{email}-----{password}",
    )

    assert result["count"] == 1
    assert result["content"] == "exported@example.com-----pw-----https://gptcode.external.cc.cd/"
    assert result["exported_emails"] == ["exported@example.com"]


def test_public_plus_extractor_history_routes_to_trade(monkeypatch):
    captured = {}

    def fake_history(code, password):
        captured["history"] = (code, password)
        return {"history": []}

    def fake_download(code, password, batch_id):
        captured["download"] = (code, password, batch_id)
        return {"batch_id": batch_id, "content_base64": ""}

    monkeypatch.setattr("autotoken.trade.list_cdk_redemption_history", fake_history)
    monkeypatch.setattr("autotoken.trade.download_cdk_redemption_batch", fake_download)

    from autotoken.api_routes.trade import create_trade_router

    routes = {route.endpoint.__name__: route.endpoint for route in create_trade_router().routes}
    history = routes["post_public_plus_extractor_history"](
        TradeQueryParams(code="100-20260526-PLUS-ABCDEF123456", password="secret")
    )
    downloaded = routes["post_public_plus_extractor_history_download"](
        TradeHistoryDownloadParams(code="100-20260526-PLUS-ABCDEF123456", password="secret", batch_id="batch-1")
    )

    assert history == {"history": []}
    assert downloaded == {"batch_id": "batch-1", "content_base64": ""}
    assert captured["history"] == ("100-20260526-PLUS-ABCDEF123456", "secret")
    assert captured["download"] == ("100-20260526-PLUS-ABCDEF123456", "secret", "batch-1")


def test_export_account_credentials_ignores_legacy_empty_format(monkeypatch):
    monkeypatch.setattr(
        "autotoken.accounts.load_accounts",
        lambda: [{"email": "user@example.com", "password": "pw"}],
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda _email, **_kwargs: None)

    result = _export_account_credentials(line_format=" ")

    assert result["content"] == "user@example.com-----pw-----https://gptcode.external.cc.cd/"


def test_export_account_cpa_auths_returns_existing_data_auths_file(tmp_path, monkeypatch):
    auth_dir = tmp_path / "data" / "auths"
    auth_file = auth_dir / "codex-user@example.com-plus-deadbeef.json"
    auth_dir.mkdir(parents=True)
    payload = {"email": "user@example.com", "access_token": "token", "refresh_token": "refresh"}
    auth_file.write_text(json.dumps(payload), encoding="utf-8")
    captured = {"updates": []}

    monkeypatch.setattr("autotoken.auth_storage.AUTH_DIR", auth_dir)
    monkeypatch.setattr(
        "autotoken.accounts.load_accounts",
        lambda: [{"email": "user@example.com", "auth_file": str(auth_file)}],
    )
    monkeypatch.setattr(
        "autotoken.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs))
    )
    monkeypatch.setattr(api.time, "time", lambda: 1778888888.0)

    result = _export_account_cpa_auths(["USER@example.com"])

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

    monkeypatch.setattr("autotoken.auth_storage.AUTH_DIR", auth_dir)
    monkeypatch.setattr(
        "autotoken.accounts.load_accounts",
        lambda: [{"email": "user@example.com", "auth_file": str(auth_file)}],
    )
    monkeypatch.setattr(
        "autotoken.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs))
    )
    monkeypatch.setattr(api.time, "time", lambda: 1779999999.0)

    result = _export_account_sub_auths(["USER@example.com"])

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
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: rows)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda items, email: next((account for account in items if account["email"] == email), None),
    )
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)
    monkeypatch.setattr(
        api,
        "_run_account_codex_login_once",
        lambda email, _acc, **_kwargs: {
            "email": email,
            "plan": "plus",
            "auth_file": f"data/auths/{email}.json",
        },
    )
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["command"] = command
        captured["params"] = params
        captured["exclusive"] = kwargs.get("exclusive")
        captured["task_group"] = kwargs.get("task_group")
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
    assert captured["task_group"] == api.TASK_GROUP_OAUTH
    assert captured["exclusive"] is None
    assert captured["pass_task_id"] is True
    assert captured["params"]["emails"] == [
        "first@example.com",
        "second@example.com",
        "third@example.com",
        "fourth@example.com",
    ]
    assert captured["result"]["total"] == 4
    assert captured["result"]["concurrency"] == 4
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
    monkeypatch.setattr("autotoken.storage.auth_storage.AUTH_DIR", tmp_path)
    account = {
        "email": "user@example.com",
        "status": "active",
        "auth_file": str(auth_file),
    }
    updates = {}

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda accounts, email: account if email == "user@example.com" else None,
    )
    monkeypatch.setattr(
        "autotoken.accounts.update_account", lambda email, **kwargs: updates.setdefault(email, {}).update(kwargs)
    )
    monkeypatch.setattr(
        "autotoken.codex_auth.check_codex_quota", lambda token, account_id=None, **_kwargs: ("auth_error", None)
    )

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

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda accounts, email: account if email == "discarded@example.com" else None,
    )
    monkeypatch.setattr(
        "autotoken.accounts.update_account", lambda email, **kwargs: updates.setdefault(email, {}).update(kwargs)
    )
    monkeypatch.setattr(
        "autotoken.codex_auth.check_codex_quota",
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


def test_post_accounts_refresh_quota_does_not_mark_free_account_exhausted(tmp_path, monkeypatch):
    auth_file = tmp_path / "codex-user.json"
    auth_file.write_text(json.dumps({"access_token": "token", "account": {"id": "account-free"}}), encoding="utf-8")
    monkeypatch.setattr("autotoken.storage.auth_storage.AUTH_DIR", tmp_path)
    account = {
        "email": "free@example.com",
        "status": "personal",
        "account_type": "free",
        "auth_file": str(auth_file),
    }
    updates = {}
    quota_info = {
        "quota_info": {"primary_pct": 100, "primary_resets_at": 1710000000, "weekly_pct": 0, "weekly_resets_at": 0},
        "resets_at": 1710000000,
    }

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda accounts, email: account if email == "free@example.com" else None,
    )
    monkeypatch.setattr(
        "autotoken.accounts.update_account", lambda email, **kwargs: updates.setdefault(email, {}).update(kwargs)
    )
    monkeypatch.setattr(
        "autotoken.codex_auth.check_codex_quota", lambda token, account_id=None, timeout=25: ("exhausted", quota_info)
    )

    def fake_start_task(command, func, params, *args, **kwargs):
        return {
            "task_id": "task-refresh",
            "command": command,
            "params": params,
            "result": func("task-refresh"),
        }

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    result = api.post_accounts_refresh_quota(api.AccountEmailBatchParams(emails=["free@example.com"]))

    assert result["result"]["exhausted"][0]["email"] == "free@example.com"
    assert updates["free@example.com"]["status"] == "personal"
    assert updates["free@example.com"]["last_quota"]["primary_pct"] == 100
    assert updates["free@example.com"]["quota_resets_at"] == 1710000000


def test_post_accounts_refresh_quota_keeps_network_errors_out_of_fail(tmp_path, monkeypatch):
    auth_file = tmp_path / "codex-user.json"
    auth_file.write_text(json.dumps({"access_token": "token"}), encoding="utf-8")
    monkeypatch.setattr("autotoken.storage.auth_storage.AUTH_DIR", tmp_path)
    account = {
        "email": "user@example.com",
        "status": "active",
        "auth_file": str(auth_file),
    }
    updates = {}

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda accounts, email: account if email == "user@example.com" else None,
    )
    monkeypatch.setattr(
        "autotoken.accounts.update_account", lambda email, **kwargs: updates.setdefault(email, {}).update(kwargs)
    )
    monkeypatch.setattr(
        "autotoken.codex_auth.check_codex_quota", lambda token, account_id=None, **_kwargs: ("network_error", None)
    )

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
    monkeypatch.setattr("autotoken.storage.auth_storage.AUTH_DIR", tmp_path)
    rows = [
        {"email": "owner@example.com", "status": "active", "auth_file": str(auth_file)},
        {"email": "first@example.com", "status": "active", "auth_file": str(auth_file)},
        {"email": "second@example.com", "status": "active", "auth_file": str(auth_file)},
    ]
    checked = []

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: rows)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda accounts, email: next((account for account in accounts if account["email"] == email), None),
    )
    monkeypatch.setattr(api, "_is_main_account_email", lambda email: email == "owner@example.com")
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: checked.append(email))
    monkeypatch.setattr(
        "autotoken.codex_auth.check_codex_quota",
        lambda token, account_id=None, **_kwargs: ("ok", {"primary_pct": 1, "weekly_pct": 2}),
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


def test_post_account_login_keeps_account_when_oauth_requires_phone(monkeypatch):
    from autotoken.codex_auth import CodexOAuthPhoneRequired

    captured = {"progress": []}
    account = {"email": "phone@example.com", "password": "pw", "account_type": "free", "status": "active"}

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda items, email: account if email == account["email"] else None
    )
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)
    monkeypatch.setattr(
        api,
        "_run_account_codex_login_once",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(CodexOAuthPhoneRequired("https://auth.openai.com/add-phone")),
    )
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["command"] = command
        captured["exclusive"] = kwargs.get("exclusive")
        captured["task_group"] = kwargs.get("task_group")
        captured["pass_task_id"] = kwargs.get("pass_task_id")
        try:
            func("task-login-phone")
        except api.TaskResultError as exc:
            captured["error"] = exc
        return {"task_id": "task-login-phone", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_account_login(api.LoginAccountParams(email="phone@example.com"))

    assert captured["task_group"] == api.TASK_GROUP_OAUTH
    assert captured["exclusive"] is True
    assert captured["pass_task_id"] is True
    assert captured["error"].task_result["failure_stage"] == "oauth_phone_required"
    assert captured["error"].task_result["removed_pool_emails"] == []
    assert captured["progress"][-1]["stage"] == "account_login_phone_required"


def test_post_account_login_removes_account_when_oauth_account_deactivated(monkeypatch):
    from autotoken.codex_auth import CodexOAuthAccountDeactivated

    captured = {"progress": []}
    account = {"email": "dead@example.com", "password": "pw", "account_type": "free", "status": "active"}

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda items, email: account if email == account["email"] else None
    )
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)
    monkeypatch.setattr(
        api,
        "_run_account_codex_login_once",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(CodexOAuthAccountDeactivated("account_deactivated")),
    )
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
    from autotoken.codex_auth import CodexOAuthPhoneRequired

    captured = {"progress": []}
    rows = [
        {"email": "phone@example.com", "password": "pw1", "account_type": "free", "status": "active"},
        {"email": "ok@example.com", "password": "pw2", "account_type": "plus", "status": "active"},
    ]

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: rows)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda items, email: next((account for account in items if account["email"] == email), None),
    )
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)

    def fake_codex_login(email, _acc, **_kwargs):
        if email == "phone@example.com":
            raise CodexOAuthPhoneRequired("https://auth.openai.com/add-phone")
        return {"email": email, "plan": "plus", "auth_file": f"data/auths/{email}.json"}

    monkeypatch.setattr(api, "_run_account_codex_login_once", fake_codex_login)
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["exclusive"] = kwargs.get("exclusive")
        captured["task_group"] = kwargs.get("task_group")
        captured["pass_task_id"] = kwargs.get("pass_task_id")
        captured["result"] = func("task-login-batch")
        return {"task_id": "task-login-batch", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_accounts_login_batch(api.AccountEmailBatchParams(emails=["phone@example.com", "ok@example.com"]))

    assert [item["email"] for item in captured["result"]["ok"]] == ["ok@example.com"]
    assert captured["task_group"] == api.TASK_GROUP_OAUTH
    assert captured["exclusive"] is None
    assert captured["pass_task_id"] is True
    assert captured["result"]["phone_required"][0]["email"] == "phone@example.com"
    assert any(progress["stage"] == "account_login_phone_required" for progress in captured["progress"])


def test_gopay_task_runner_removes_rejected_batch_accounts(monkeypatch):
    captured = {"updates": [], "deleted_accounts": [], "deleted_sessions": [], "mail_deleted": []}
    accounts = [
        {"email": "primary@example.com", "cloudmail_account_id": 123},
        {"email": "backup@example.com"},
    ]

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    monkeypatch.setattr(
        "autotoken.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs))
    )
    monkeypatch.setattr(
        "autotoken.accounts.delete_account", lambda email: captured["deleted_accounts"].append(email) or True
    )
    monkeypatch.setattr(
        "autotoken.auth_session_store.delete_auth_session",
        lambda email: captured["deleted_sessions"].append(email) or True,
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/account.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, _progress: None)
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))

    class FakeMailClient:
        def login(self):
            captured["mail_login"] = True

        def delete_account(self, account_id):
            captured["mail_deleted"].append(account_id)
            return {"code": 200}

    monkeypatch.setattr("autotoken.mail.TemporaryEmailClient", FakeMailClient)

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "email_used": "backup@example.com",
            "rejected_emails": ["primary@example.com"],
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

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

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    monkeypatch.setattr(
        "autotoken.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs))
    )
    monkeypatch.setattr(
        "autotoken.accounts.delete_account", lambda email: captured["deleted_accounts"].append(email) or True
    )
    monkeypatch.setattr(
        "autotoken.auth_session_store.delete_auth_session",
        lambda email: captured["deleted_sessions"].append(email) or True,
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/account.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, _progress: None)
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))

    class FakeMailClient:
        def login(self):
            captured["mail_login"] = True

        def delete_account(self, account_id):
            captured["mail_deleted"].append(account_id)
            return {"code": 200}

    monkeypatch.setattr("autotoken.mail.TemporaryEmailClient", FakeMailClient)

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "email_used": "backup@example.com",
            "nonzero_blocked_emails": ["primary@example.com"],
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

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

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    monkeypatch.setattr(
        "autotoken.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs))
    )
    monkeypatch.setattr(
        "autotoken.accounts.delete_account", lambda email: captured["deleted_accounts"].append(email) or True
    )
    monkeypatch.setattr(
        "autotoken.auth_session_store.delete_auth_session",
        lambda email: captured["deleted_sessions"].append(email) or True,
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/account.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, _progress: None)
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))

    class FakeMailClient:
        def login(self):
            captured["mail_login"] = True

        def delete_account(self, account_id):
            captured["mail_deleted"].append(account_id)
            return {"code": 200}

    monkeypatch.setattr("autotoken.mail.TemporaryEmailClient", FakeMailClient)

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "email_used": "backup@example.com",
            "payment_failed_emails": ["primary@example.com"],
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

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


def test_gopay_task_runner_removes_token_invalidated_accounts(monkeypatch):
    captured = {"updates": [], "deleted_accounts": [], "deleted_sessions": []}
    accounts = [
        {"email": "primary@example.com", "cloudmail_account_id": "mail-123"},
        {"email": "backup@example.com"},
    ]

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    monkeypatch.setattr(
        "autotoken.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs))
    )
    monkeypatch.setattr(
        "autotoken.accounts.delete_account", lambda email: captured["deleted_accounts"].append(email) or True
    )
    monkeypatch.setattr(
        "autotoken.auth_session_store.delete_auth_session",
        lambda email: captured["deleted_sessions"].append(email) or True,
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/account.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, _progress: None)
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))

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

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

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
    assert result["token_invalidated_removed_emails"] == ["primary@example.com"]
    assert result["removed_pool_emails"] == ["primary@example.com"]
    assert captured["deleted_accounts"] == ["primary@example.com"]
    assert captured["deleted_sessions"] == ["primary@example.com"]
    failed_updates = [item for item in captured["updates"] if item[0] == "primary@example.com"]
    assert failed_updates == []
    assert captured["audit"]["removed_pool_emails"] == ["primary@example.com"]


def test_gopay_task_runner_removes_token_invalidated_account_from_checkout_message(monkeypatch):
    captured = {"updates": [], "deleted_accounts": [], "deleted_sessions": []}
    accounts = [{"email": "primary@example.com", "cloudmail_account_id": "mail-123"}]

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    monkeypatch.setattr(
        "autotoken.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs))
    )
    monkeypatch.setattr(
        "autotoken.accounts.delete_account", lambda email: captured["deleted_accounts"].append(email) or True
    )
    monkeypatch.setattr(
        "autotoken.auth_session_store.delete_auth_session",
        lambda email: captured["deleted_sessions"].append(email) or True,
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/account.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, _progress: None)
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "failed",
            "failure_stage": "checkout",
            "message": (
                "生成印尼区支付链接失败: HTTP checkout 生成失败: HTTP 401 "
                '{ "error": { "message": "Your authentication token has been invalidated. '
                'Please try signing in again.", "type": "invalid_request_error", '
                '"code": "token_invalidated", "param": null }, "status": 401 }'
            ),
            "email_used": "primary@example.com",
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-794b", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="primary@example.com",
            account_emails=["primary@example.com"],
            phone_number="+6287761973970",
            country_code="62",
            sms_url="https://it.tgflare.com/api/record?token=demo",
            gopay_pin="558023",
            delete_rejected_accounts=False,
        )
    )

    with pytest.raises(api.TaskResultError) as exc:
        captured["func"]()
    result = exc.value.task_result

    assert result["task_status"] == "failed"
    assert result["token_invalidated_pool_emails"] == ["primary@example.com"]
    assert result["token_invalidated_removed_emails"] == ["primary@example.com"]
    assert result["removed_pool_emails"] == ["primary@example.com"]
    assert captured["deleted_accounts"] == ["primary@example.com"]
    assert captured["deleted_sessions"] == ["primary@example.com"]
    assert captured["updates"] == []
    assert captured["audit"]["removed_pool_emails"] == ["primary@example.com"]


def test_gopay_task_runner_removes_account_when_auth_session_refresh_fails(monkeypatch):
    captured = {"updates": [], "progress": [], "deleted_accounts": [], "deleted_sessions": []}
    accounts = [
        {"email": "primary@example.com", "password": "pw", "cloudmail_account_id": "mail-123"},
        {"email": "backup@example.com"},
    ]

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    monkeypatch.setattr(
        "autotoken.accounts.update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs))
    )
    monkeypatch.setattr(
        "autotoken.accounts.delete_account", lambda email: captured["deleted_accounts"].append(email) or True
    )
    monkeypatch.setattr(
        "autotoken.auth_session_store.delete_auth_session",
        lambda email: captured["deleted_sessions"].append(email) or True,
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/account.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, _progress: None)
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda payload: captured.setdefault("audit", payload))

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

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

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
    assert "已从号池删除" in captured["refresh_result"]["message"]
    fail_updates = [item for item in captured["updates"] if item[0] == "primary@example.com"]
    assert fail_updates == []
    assert captured["deleted_accounts"] == ["primary@example.com"]
    assert captured["deleted_sessions"] == ["primary@example.com"]
    assert result["token_invalidated_removed_emails"] == ["primary@example.com"]
    assert any(progress["stage"] == "gopay_auth_session_refresh_failed" for progress in captured["progress"])


def test_post_gopay_bind_task_requires_phone(monkeypatch):
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda accounts, email: accounts[0])
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


def test_post_gopay_bind_task_allows_gopay_auto_signup_without_phone(monkeypatch):
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda accounts, email: accounts[0])
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda *_args, **_kwargs: None)

    captured = {}

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["command"] = command
        captured["params"] = params
        captured["func"] = func
        return {"task_id": "task-auto-signup", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    result = api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="user@example.com",
            phone_number="",
            sms_url="",
            gopay_pin="558023",
            gopay_auto_signup=True,
            gopay_auto_signup_hero_sms_api_key="hero-key",
            gopay_auto_signup_hero_sms_base_url="https://sms.example.test",
            gopay_auto_signup_hero_sms_country="6",
            gopay_auto_signup_hero_sms_service="ni",
            gopay_auto_signup_hero_sms_timeout="180",
            gopay_auto_signup_hero_sms_min_price="0.02",
            gopay_auto_signup_hero_sms_max_price="0.045",
            gopay_auto_signup_hero_sms_preferred_price="0.04",
        )
    )

    assert result["task_id"] == "task-auto-signup"
    assert captured["command"] == "gopay-bind"
    assert captured["params"]["gopay_auto_signup"] is True
    assert captured["params"]["gopay_auto_signup_sms_provider"] == "smscloud"
    assert captured["params"]["gopay_auto_signup_hero_sms_api_key_present"] is True
    assert "gopay_auto_signup_hero_sms_api_key" not in captured["params"]


def test_post_gopay_bind_task_uses_saved_appium_signup_config(monkeypatch):
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda accounts, email: accounts[0])
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(
        api,
        "_gopay_auto_signup_env",
        lambda: {
            "provider": "hero_sms",
            "smscloud_xi_token": "",
            "hero_sms_api_key": "saved-hero-key",
            "hero_sms_max_price": "0.045",
            "proxy_url": "",
            "country_code": "+62",
            "signup_mode": "appium",
            "appium_url": "http://127.0.0.1:4724",
            "appium_adb_serial": "emulator-5564",
        },
    )

    captured = {}

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["command"] = command
        captured["params"] = params
        captured["func"] = func
        return {"task_id": "task-appium-config", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    result = api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="user@example.com",
            gopay_pin="558023",
            gopay_auto_signup=True,
        )
    )

    assert result["task_id"] == "task-appium-config"
    assert captured["command"] == "gopay-bind"
    assert captured["params"]["gopay_auto_signup_sms_provider"] == "hero_sms"
    assert captured["params"]["gopay_auto_signup_mode"] == "appium"
    assert captured["params"]["gopay_appium_url"] == "http://127.0.0.1:4724"
    assert captured["params"]["gopay_appium_adb_serial"] == "emulator-5564"


def test_gopay_task_runner_passes_saved_appium_config_to_wallet_signup(monkeypatch):
    captured = {"progress": [], "closed": []}
    account = {"email": "user@example.com"}

    monkeypatch.setenv("REKBERINAJA_ENABLED", "0")
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: account if email == account["email"] else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        api,
        "_gopay_auto_signup_env",
        lambda: {
            "provider": "hero_sms",
            "smscloud_xi_token": "",
            "hero_sms_api_key": "saved-hero-key",
            "hero_sms_max_price": "0.045",
            "proxy_url": "",
            "country_code": "+62",
            "signup_mode": "appium",
            "appium_url": "http://127.0.0.1:4724",
            "appium_adb_serial": "emulator-5564",
        },
    )

    class FakeWallet:
        phone_number = "87761973970"

        def as_phone_account(self):
            return {
                "country_code": "62",
                "phone_number": self.phone_number,
                "sms_url": "http://127.0.0.1:8787/otp/gopay-signup/demo",
                "gopay_pin": "558023",
                "otp_channel": "sms",
            }

        def close(self, *, success=True):
            captured["closed"].append(success)

    def fake_register_gopay_wallet(**kwargs):
        captured["signup_kwargs"] = kwargs
        return FakeWallet()

    monkeypatch.setattr("autotoken.gopay_auto_register.register_gopay_wallet", fake_register_gopay_wallet)

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "email_used": "user@example.com",
            "successful_emails": ["user@example.com"],
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-appium-runner", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="user@example.com",
            gopay_pin="558023",
            gopay_auto_signup=True,
        )
    )

    result = captured["func"]()

    assert result["task_status"] == "completed"
    assert captured["signup_kwargs"]["sms_provider"] == "hero_sms"
    assert captured["signup_kwargs"]["appium_config"] == {
        "signup_mode": "appium",
        "appium_url": "http://127.0.0.1:4724",
        "adb_serial": "emulator-5564",
    }
    assert captured["run_kwargs"]["phone_number"] == "87761973970"
    assert captured["closed"] == [True]


def test_gopay_auto_signup_existing_accounts_can_run_in_parallel(monkeypatch):
    captured = {"progress": [], "run_emails": [], "wallets": [], "closed": []}
    emails = [f"user{i}@example.com" for i in range(1, 11)]
    accounts = [{"email": email} for email in emails]
    wallet_lock = threading.Lock()

    monkeypatch.setenv("REKBERINAJA_ENABLED", "0")
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda account_list, email: next((account for account in account_list if account["email"] == email), None),
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **fields: {"email": email, **fields})
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda account: f"data/auth_session/{account['email']}.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda *_args, **_kwargs: None)

    class FakeWallet:
        def __init__(self, index):
            self.index = index
            self.phone_number = f"8776197397{index}"

        def as_phone_account(self):
            return {
                "country_code": "62",
                "phone_number": self.phone_number,
                "sms_url": f"http://127.0.0.1:8787/otp/gopay-signup/{self.index}",
                "gopay_pin": "558023",
                "otp_channel": "sms",
            }

        def close(self, *, success=True):
            captured["closed"].append((self.index, success))

    def fake_register_gopay_wallet(**_kwargs):
        with wallet_lock:
            index = len(captured["wallets"]) + 1
            captured["wallets"].append(index)
        return FakeWallet(index)

    monkeypatch.setattr("autotoken.gopay_auto_register.register_gopay_wallet", fake_register_gopay_wallet)

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_emails"].append(kwargs["email"])
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "email_used": kwargs["email"],
            "successful_emails": [kwargs["email"]],
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        captured["params"] = params
        return {"task_id": "task-gopay-parallel", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email=emails[0],
            account_emails=emails,
            gopay_pin="558023",
            gopay_auto_signup=True,
            gopay_concurrency=10,
        )
    )

    result = captured["func"]()

    assert result["task_status"] == "completed"
    assert result["concurrency"] == 10
    assert captured["params"]["gopay_concurrency"] == 10
    assert set(captured["run_emails"]) == set(emails)
    assert len(captured["wallets"]) == 10
    assert any(progress["stage"] == "gopay_parallel_started" for progress in captured["progress"])


def test_gopay_auto_signup_parallel_honors_configured_concurrency(monkeypatch):
    captured = {
        "progress": [],
        "max_active_wallets": 0,
        "active_wallets": 0,
        "max_active_binds": 0,
        "active_binds": 0,
    }
    emails = [f"user{i}@example.com" for i in range(12)]
    accounts = [{"email": email} for email in emails]
    lock = threading.Lock()

    monkeypatch.setenv("REKBERINAJA_ENABLED", "0")
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda account_list, email: next((account for account in account_list if account["email"] == email), None),
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **fields: {"email": email, **fields})
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda account: f"data/auth_session/{account['email']}.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda *_args, **_kwargs: None)

    class FakeWallet:
        def __init__(self, index):
            self.index = index
            self.phone_number = f"8776197397{index}"

        def as_phone_account(self):
            return {
                "country_code": "62",
                "phone_number": self.phone_number,
                "sms_url": f"http://127.0.0.1:8787/otp/gopay-signup/{self.index}",
                "gopay_pin": "558023",
                "otp_channel": "sms",
            }

        def close(self, *, success=True):
            pass

    def fake_register_gopay_wallet(**_kwargs):
        with lock:
            captured["active_wallets"] += 1
            captured["max_active_wallets"] = max(captured["max_active_wallets"], captured["active_wallets"])
            index = captured["max_active_wallets"]
        try:
            api.time.sleep(0.02)
            return FakeWallet(index)
        finally:
            with lock:
                captured["active_wallets"] -= 1

    monkeypatch.setattr("autotoken.gopay_auto_register.register_gopay_wallet", fake_register_gopay_wallet)

    def fake_run_gopay_bind_task(**kwargs):
        with lock:
            captured["active_binds"] += 1
            captured["max_active_binds"] = max(captured["max_active_binds"], captured["active_binds"])
        try:
            api.time.sleep(0.02)
            return {
                "status": "success",
                "message": "GoPay 绑定完成",
                "email_used": kwargs["email"],
                "successful_emails": [kwargs["email"]],
            }
        finally:
            with lock:
                captured["active_binds"] -= 1

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        captured["params"] = params
        return {"task_id": "task-gopay-parallel-limit", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email=emails[0],
            account_emails=emails,
            gopay_pin="558023",
            gopay_auto_signup=True,
            gopay_concurrency=5,
        )
    )

    result = captured["func"]()

    assert result["task_status"] == "completed"
    assert result["concurrency"] == 5
    assert captured["params"]["gopay_concurrency"] == 5
    assert captured["max_active_wallets"] <= 5
    assert captured["max_active_binds"] <= 5
    assert any(
        progress["stage"] == "gopay_parallel_started" and progress["concurrency"] == 5
        for progress in captured["progress"]
    )
    worker_indexes = [
        int(progress.get("worker_index") or 0)
        for progress in captured["progress"]
        if progress.get("stage") == "gopay_parallel_account"
    ]
    assert max(worker_indexes) <= 5


def test_gopay_auto_signup_parallel_counts_retried_failure_once(monkeypatch):
    captured = {"progress": [], "calls": [], "registered": 0}
    emails = ["failed@example.com", "success@example.com"]
    accounts = [{"email": email} for email in emails]
    clock = {"value": 0.0}

    monkeypatch.setenv("REKBERINAJA_ENABLED", "0")
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda account_list, email: next((account for account in account_list if account["email"] == email), None),
    )
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **fields: {"email": email, **fields})
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda account: f"data/auth_session/{account['email']}.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(api.time, "sleep", lambda _seconds: None)

    def fake_time():
        clock["value"] += 61.0
        return clock["value"]

    monkeypatch.setattr(api.time, "time", fake_time)

    class FakeWallet:
        def __init__(self, index):
            self.phone_number = f"8776197397{index}"

        def as_phone_account(self):
            return {
                "country_code": "62",
                "phone_number": self.phone_number,
                "sms_url": f"http://127.0.0.1:8787/otp/gopay-signup/{self.phone_number}",
                "gopay_pin": "558023",
                "otp_channel": "sms",
            }

        def close(self, *, success=True):
            pass

    def fake_register_gopay_wallet(**_kwargs):
        captured["registered"] += 1
        return FakeWallet(captured["registered"])

    monkeypatch.setattr("autotoken.gopay_auto_register.register_gopay_wallet", fake_register_gopay_wallet)

    def fake_run_gopay_bind_task(**kwargs):
        captured["calls"].append(kwargs["email"])
        if kwargs["email"] == "failed@example.com":
            return {
                "status": "failed",
                "failure_stage": "fetch_otp",
                "message": "GoPay OTP 未收到",
                "email_used": kwargs["email"],
            }
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "email_used": kwargs["email"],
            "successful_emails": [kwargs["email"]],
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-gopay-parallel-retry-count", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email=emails[0],
            account_emails=emails,
            gopay_pin="558023",
            gopay_auto_signup=True,
            gopay_concurrency=2,
            pending_retry_attempts=2,
        )
    )

    result = captured["func"]()

    assert result["task_status"] == "completed"
    assert len(result["auto_signup_account_results"]) == 4
    assert result["successful_emails"] == ["success@example.com"]
    assert result["failed_emails"] == [
        {
            "email": "failed@example.com",
            "failure_stage": "fetch_otp",
            "message": "GoPay OTP 未收到",
            "retry_round": 2,
        }
    ]
    assert result["message"] == "GoPay 自动注册绑定完成: 成功 1/2 个账号，失败 1 个"
    queued_events = [event for event in captured["progress"] if event["stage"] == "gopay_pending_retry_queued"]
    assert [event["retry_round"] for event in queued_events] == [1, 2]
    assert [event["source_retry_round"] for event in queued_events] == [0, 1]


def test_gopay_task_runner_auto_signs_up_wallet_before_bind(monkeypatch):
    captured = {"progress": [], "closed": []}
    account = {"email": "user@example.com"}

    monkeypatch.setenv("AUTOTOKEN_LOCAL_BASE_URL", "http://127.0.0.1:8787")
    monkeypatch.setenv("REKBERINAJA_ENABLED", "0")
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: account if email == account["email"] else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda *_args, **_kwargs: None)

    class FakeWallet:
        phone_number = "87761973970"

        def as_phone_account(self):
            return {
                "country_code": "62",
                "phone_number": "87761973970",
                "sms_url": "http://127.0.0.1:8787/otp/gopay-signup/demo",
                "gopay_pin": "558023",
                "otp_channel": "sms",
            }

        def close(self, *, success=True):
            captured["closed"].append(success)

    monkeypatch.setattr(
        "autotoken.gopay_auto_register.register_gopay_wallet",
        lambda **kwargs: captured.setdefault("signup_kwargs", kwargs) and FakeWallet(),
    )

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "email_used": "user@example.com",
            "successful_emails": ["user@example.com"],
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-bridge", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="user@example.com",
            gopay_pin="558023",
            gopay_auto_signup=True,
            gopay_auto_signup_hero_sms_api_key="hero-key",
            gopay_auto_signup_hero_sms_base_url="https://sms.example.test",
            gopay_auto_signup_hero_sms_country="6",
            gopay_auto_signup_hero_sms_service="ni",
            gopay_auto_signup_hero_sms_timeout="180",
            gopay_auto_signup_hero_sms_min_price="0.02",
            gopay_auto_signup_hero_sms_max_price="0.045",
            gopay_auto_signup_hero_sms_preferred_price="0.04",
        )
    )

    result = captured["func"]()

    assert result["task_status"] == "completed"
    assert captured["run_kwargs"]["phone_number"] == "87761973970"
    assert captured["run_kwargs"]["sms_url"] == "http://127.0.0.1:8787/otp/gopay-signup/demo"
    assert captured["run_kwargs"]["phone_accounts"][0]["gopay_pin"] == "558023"
    assert captured["run_kwargs"]["phone_accounts"][0]["auto_signup_wallet"] is True
    assert captured["signup_kwargs"]["sms_provider"] == "smscloud"
    assert captured["signup_kwargs"]["hero_sms_config"]["api_key"] == "hero-key"
    assert captured["signup_kwargs"]["hero_sms_config"]["base_url"] == "https://sms.example.test"
    assert captured["signup_kwargs"]["hero_sms_config"]["timeout_sec"] == "180"
    assert captured["signup_kwargs"]["hero_sms_config"]["min_price"] == "0.02"
    assert captured["signup_kwargs"]["hero_sms_config"]["max_price"] == "0.045"
    assert captured["signup_kwargs"]["hero_sms_config"]["preferred_price"] == "0.04"
    assert any(progress["stage"] == "gopay_wallet_auto_signup_started" for progress in captured["progress"])
    assert any(progress["stage"] == "gopay_wallet_auto_signup_done" for progress in captured["progress"])
    assert captured["closed"] == [True]


def test_gopay_task_runner_retains_sms_session_when_bind_fails_after_signup(monkeypatch):
    captured = {"progress": [], "closed": []}
    account = {"email": "user@example.com"}

    monkeypatch.setenv("REKBERINAJA_ENABLED", "0")
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: account if email == account["email"] else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda *_args, **_kwargs: None)

    class FakeWallet:
        phone_number = "87761973970"

        def as_phone_account(self):
            return {
                "country_code": "62",
                "phone_number": self.phone_number,
                "sms_url": "http://127.0.0.1:8787/otp/gopay-signup/demo",
                "gopay_pin": "558023",
                "otp_channel": "sms",
            }

        def close(self, *, success=True):
            captured["closed"].append(success)

    monkeypatch.setattr("autotoken.gopay_auto_register.register_gopay_wallet", lambda **_kwargs: FakeWallet())

    def fake_run_gopay_bind_task(**_kwargs):
        return {
            "status": "failed",
            "failure_stage": "fetch_otp",
            "message": "GoPay 绑定 OTP 未收到",
            "email_used": "user@example.com",
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-retain-sms", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="user@example.com",
            gopay_pin="558023",
            gopay_auto_signup=True,
        )
    )

    with pytest.raises(api.TaskResultError) as exc:
        captured["func"]()
    result = exc.value.task_result

    assert result["task_status"] == "failed"
    assert captured["closed"] == []
    assert result["reusable_gopay_wallets"][0]["sms_url"] == "http://127.0.0.1:8787/otp/gopay-signup/demo"
    assert any(progress["stage"] == "gopay_wallet_preserved" for progress in captured["progress"])


def test_gopay_auto_signup_discards_already_linked_wallet_and_reregisters(monkeypatch):
    captured = {"progress": [], "closed": [], "run_kwargs": [], "signup_calls": 0}
    account = {"email": "user@example.com"}

    monkeypatch.setenv("REKBERINAJA_ENABLED", "0")
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: account if email == account["email"] else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda *_args, **_kwargs: None)

    class FakeWallet:
        def __init__(self, index):
            self.index = index
            self.phone_number = f"8776197397{index}"

        def as_phone_account(self):
            return {
                "country_code": "62",
                "phone_number": self.phone_number,
                "sms_url": f"http://127.0.0.1:8787/otp/gopay-signup/{self.index}",
                "gopay_pin": "558023",
                "otp_channel": "sms",
            }

        def close(self, *, success=True):
            captured["closed"].append((self.index, success))

    def fake_register_wallet(**_kwargs):
        captured["signup_calls"] += 1
        return FakeWallet(captured["signup_calls"])

    monkeypatch.setattr("autotoken.gopay_auto_register.register_gopay_wallet", fake_register_wallet)

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"].append(kwargs)
        if len(captured["run_kwargs"]) == 1:
            return {
                "status": "failed",
                "failure_stage": "midtrans_linking",
                "message": "该 GoPay 手机号已绑定其他账号；请先在 GoPay 侧解绑其他账号后再重试",
                "email_used": "user@example.com",
            }
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "email_used": "user@example.com",
            "successful_emails": ["user@example.com"],
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-already-linked-reregister", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(email="user@example.com", gopay_pin="558023", gopay_auto_signup=True)
    )
    result = captured["func"]()

    assert result["task_status"] == "completed"
    assert captured["signup_calls"] == 2
    assert [item["phone_number"] for item in captured["run_kwargs"]] == ["87761973971", "87761973972"]
    assert captured["closed"] == [(1, False), (2, True)]
    assert any(progress["stage"] == "gopay_wallet_already_linked_discarded" for progress in captured["progress"])
    assert any(progress["stage"] == "gopay_wallet_already_linked_retry" for progress in captured["progress"])
    assert not any(progress["stage"] == "gopay_wallet_preserved" for progress in captured["progress"])


def test_gopay_auto_signup_discards_charge_denied_wallet_and_reregisters(monkeypatch):
    captured = {"progress": [], "closed": [], "run_kwargs": [], "signup_calls": 0}
    account = {"email": "user@example.com"}

    monkeypatch.setenv("REKBERINAJA_ENABLED", "0")
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: account if email == account["email"] else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda *_args, **_kwargs: None)

    class FakeWallet:
        def __init__(self, index):
            self.index = index
            self.phone_number = f"8776197397{index}"

        def as_phone_account(self):
            return {
                "country_code": "62",
                "phone_number": self.phone_number,
                "sms_url": f"http://127.0.0.1:8787/otp/gopay-signup/{self.index}",
                "gopay_pin": "558023",
                "otp_channel": "sms",
            }

        def close(self, *, success=True):
            captured["closed"].append((self.index, success))

    def fake_register_wallet(**_kwargs):
        captured["signup_calls"] += 1
        return FakeWallet(captured["signup_calls"])

    monkeypatch.setattr("autotoken.gopay_auto_register.register_gopay_wallet", fake_register_wallet)

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"].append(kwargs)
        if len(captured["run_kwargs"]) == 1:
            return {
                "status": "failed",
                "failure_stage": "gopay_payment_process",
                "message": "Midtrans GoPay charge denied: transaction_status=deny; fraud_status=deny; try another payment method",
                "email_used": "user@example.com",
            }
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "email_used": "user@example.com",
            "successful_emails": ["user@example.com"],
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-charge-denied-reregister", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(email="user@example.com", gopay_pin="558023", gopay_auto_signup=True)
    )
    result = captured["func"]()

    assert result["task_status"] == "completed"
    assert captured["signup_calls"] == 2
    assert [item["phone_number"] for item in captured["run_kwargs"]] == ["87761973971", "87761973972"]
    assert captured["closed"] == [(1, False), (2, True)]
    assert any(progress["stage"] == "gopay_wallet_charge_denied_discarded" for progress in captured["progress"])
    assert any(progress["stage"] == "gopay_wallet_charge_denied_retry" for progress in captured["progress"])
    assert not any(progress["stage"] == "gopay_wallet_preserved" for progress in captured["progress"])


def test_gopay_auto_signup_reuses_wallet_pool_across_tasks(monkeypatch):
    captured = {"progress": [], "closed": [], "run_kwargs": [], "signup_calls": 0, "funcs": []}
    accounts = [{"email": "first@example.com"}, {"email": "second@example.com"}]

    monkeypatch.setenv("REKBERINAJA_ENABLED", "0")
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda acc: f"data/auth_session/{acc['email']}.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda *_args, **_kwargs: None)

    class FakeWallet:
        phone_number = "87761973970"

        def as_phone_account(self):
            return {
                "country_code": "62",
                "phone_number": self.phone_number,
                "sms_url": "http://127.0.0.1:8787/otp/gopay-signup/reuse",
                "gopay_pin": "558023",
                "otp_channel": "sms",
            }

        def close(self, *, success=True):
            captured["closed"].append(success)

    def fake_register_wallet(**_kwargs):
        captured["signup_calls"] += 1
        return FakeWallet()

    monkeypatch.setattr("autotoken.gopay_auto_register.register_gopay_wallet", fake_register_wallet)
    monkeypatch.setattr("autotoken.gopay_auto_register.is_sms_bridge_reusable", lambda _token: (True, "active"))

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"].append(kwargs)
        if kwargs["email"] == "first@example.com":
            return {
                "status": "failed",
                "failure_stage": "fetch_otp",
                "message": "GoPay 绑定 OTP 未收到",
                "email_used": "first@example.com",
            }
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "email_used": "second@example.com",
            "successful_emails": ["second@example.com"],
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["funcs"].append(func)
        return {"task_id": f"task-{len(captured['funcs'])}", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(email="first@example.com", gopay_pin="558023", gopay_auto_signup=True)
    )
    with pytest.raises(api.TaskResultError):
        captured["funcs"][0]()

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(email="second@example.com", gopay_pin="558023", gopay_auto_signup=True)
    )
    result = captured["funcs"][1]()

    assert result["task_status"] == "completed"
    assert captured["signup_calls"] == 1
    assert [item["phone_number"] for item in captured["run_kwargs"]] == ["87761973970", "87761973970"]
    assert any(progress["stage"] == "gopay_wallet_reused" for progress in captured["progress"])


def _account_overview_get_accounts(include_session_stubs=True):
    from autotoken.api_routes.account_overview import create_account_overview_router

    routes = {
        route.endpoint.__name__: route.endpoint
        for route in create_account_overview_router(
            load_accounts_with_session_stubs=api._load_accounts_with_session_stubs,
            sanitize_accounts_batch=api._sanitize_accounts_batch,
            sanitize_account=api._sanitize_account,
            is_main_account_email=api._is_main_account_email,
        ).routes
    }
    return routes["get_accounts"](include_session_stubs=include_session_stubs)


def test_get_accounts_can_include_auth_session_only_free_stubs(monkeypatch):
    from autotoken import accounts as accounts_module

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [])
    monkeypatch.setattr(
        "autotoken.accounts.ensure_session_only_account", lambda email: api._session_only_account_stub(email)
    )
    monkeypatch.setattr("autotoken.auth_session_store.list_auth_session_emails", lambda: ["free@example.com"])
    monkeypatch.setattr(
        "autotoken.auth_session_store.auth_session_files_by_email",
        lambda _emails=None: {"free@example.com": "data/auth_session/free@example_com.json"},
    )

    rows = _account_overview_get_accounts(include_session_stubs=True)

    assert len(rows) == 1
    assert rows[0]["email"] == "free@example.com"
    assert rows[0]["account_type"] == "free"
    assert rows[0]["status"] == accounts_module.STATUS_ACTIVE
    assert rows[0]["account_source"] == accounts_module.ACCOUNT_SOURCE_AUTH_SESSION_STUB
    assert rows[0]["auth_session_file"]


def test_get_accounts_can_opt_out_of_auth_session_stubs(monkeypatch):
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [])
    monkeypatch.setattr("autotoken.auth_session_store.list_auth_session_emails", lambda: ["free@example.com"])

    assert _account_overview_get_accounts(include_session_stubs=False) == []


def test_gopay_auto_signup_discards_reused_wallet_when_sms_bridge_is_unusable(monkeypatch):
    captured = {"progress": [], "closed": [], "run_kwargs": [], "signup_calls": 0, "funcs": []}
    accounts = [{"email": "first@example.com"}, {"email": "second@example.com"}]

    monkeypatch.setenv("REKBERINAJA_ENABLED", "0")
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda acc: f"data/auth_session/{acc['email']}.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda *_args, **_kwargs: None)

    class FakeWallet:
        def __init__(self, index):
            self.index = index
            self.phone_number = f"8776197397{index}"

        def as_phone_account(self):
            return {
                "country_code": "62",
                "phone_number": self.phone_number,
                "sms_url": f"http://127.0.0.1:8787/otp/gopay-signup/reuse-{self.index}",
                "gopay_pin": "558023",
                "otp_channel": "sms",
            }

        def close(self, *, success=True):
            captured["closed"].append(success)

    def fake_register_wallet(**_kwargs):
        captured["signup_calls"] += 1
        return FakeWallet(captured["signup_calls"])

    monkeypatch.setattr("autotoken.gopay_auto_register.register_gopay_wallet", fake_register_wallet)

    def fake_bridge_reusable(token):
        return (False, "bridge_missing") if str(token) == "reuse-1" else (True, "active")

    monkeypatch.setattr("autotoken.gopay_auto_register.is_sms_bridge_reusable", fake_bridge_reusable)

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"].append(kwargs)
        if kwargs["email"] == "first@example.com":
            return {
                "status": "failed",
                "failure_stage": "fetch_otp",
                "message": "GoPay 绑定 OTP 未收到",
                "email_used": "first@example.com",
            }
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "email_used": "second@example.com",
            "successful_emails": ["second@example.com"],
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["funcs"].append(func)
        return {"task_id": f"task-{len(captured['funcs'])}", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(email="first@example.com", gopay_pin="558023", gopay_auto_signup=True)
    )
    with pytest.raises(api.TaskResultError):
        captured["funcs"][0]()

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(email="second@example.com", gopay_pin="558023", gopay_auto_signup=True)
    )
    result = captured["funcs"][1]()

    assert result["task_status"] == "completed"
    assert captured["signup_calls"] == 2
    assert [item["phone_number"] for item in captured["run_kwargs"]] == ["87761973971", "87761973972"]
    assert any(progress["stage"] == "gopay_wallet_reuse_discarded" for progress in captured["progress"])


def test_gopay_task_runner_funds_auto_wallet_before_bind_when_rekberinaja_enabled(monkeypatch):
    captured = {"progress": [], "closed": [], "funded": []}
    account = {"email": "user@example.com"}

    monkeypatch.setenv("REKBERINAJA_ENABLED", "1")
    monkeypatch.setenv("REKBERINAJA_TRANSFER_ENABLED", "1")
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: account if email == account["email"] else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda *_args, **_kwargs: None)

    class FakeWallet:
        phone_number = "87761973970"

        def as_phone_account(self):
            return {
                "country_code": "62",
                "phone_number": self.phone_number,
                "sms_url": "http://127.0.0.1:8787/otp/gopay-signup/demo",
                "gopay_pin": "558023",
                "otp_channel": "sms",
            }

        def close(self, *, success=True):
            captured["closed"].append(success)

    monkeypatch.setattr("autotoken.gopay_auto_register.register_gopay_wallet", lambda **_kwargs: FakeWallet())

    def fake_fund(phone_number, **_kwargs):
        captured["funded"].append(phone_number)
        return {"transaction_id": "trx-1", "status": "completed"}

    monkeypatch.setattr("autotoken.rekberinaja.fund_gopay_wallet_if_enabled", fake_fund)

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "email_used": "user@example.com",
            "successful_emails": ["user@example.com"],
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-bridge", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="user@example.com",
            gopay_pin="558023",
            gopay_auto_signup=True,
        )
    )

    result = captured["func"]()

    assert result["task_status"] == "completed"
    assert captured["funded"] == ["87761973970"]
    assert captured["run_kwargs"]["phone_number"] == "87761973970"
    assert any(progress["stage"] == "gopay_wallet_funding_started" for progress in captured["progress"])
    assert any(progress["stage"] == "gopay_wallet_funding_done" for progress in captured["progress"])


def test_gopay_auto_signup_transfer_skips_rekberinaja_when_gopay_balance_ready(monkeypatch):
    captured = {"progress": [], "funded": [], "run_kwargs": None, "balance_calls": []}
    account = {"email": "user@example.com"}

    monkeypatch.setenv("REKBERINAJA_ENABLED", "1")
    monkeypatch.setenv("REKBERINAJA_TRANSFER_ENABLED", "1")
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: account if email == account["email"] else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda *_args, **_kwargs: None)

    class FakeWallet:
        phone_number = "87761973970"
        access_token = "gopay-token"
        session = object()
        gopay_cfg = {"unique_id": "device-1"}

        def as_phone_account(self):
            return {
                "country_code": "62",
                "phone_number": self.phone_number,
                "sms_url": "http://127.0.0.1:8787/otp/gopay-signup/demo",
                "gopay_pin": "558023",
                "otp_channel": "sms",
            }

        def close(self, *, success=True):
            pass

    monkeypatch.setattr("autotoken.gopay_auto_register.register_gopay_wallet", lambda **_kwargs: FakeWallet())
    monkeypatch.setattr(
        "autotoken.gopay_auto_register.query_gopay_balance",
        lambda **kwargs: (
            captured["balance_calls"].append(kwargs) or {"value": 1, "currency": "IDR", "display_value": "Rp1"}
        ),
    )
    monkeypatch.setattr(
        "autotoken.rekberinaja.fund_gopay_wallet_if_enabled",
        lambda phone_number, **_kwargs: captured["funded"].append(phone_number) or {"transaction_id": "trx-1"},
    )

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "email_used": "user@example.com",
            "successful_emails": ["user@example.com"],
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-transfer-skip", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(email="user@example.com", gopay_pin="558023", gopay_auto_signup=True)
    )
    result = captured["func"]()

    assert result["task_status"] == "completed"
    assert len(captured["balance_calls"]) == 1
    assert captured["funded"] == []
    assert captured["run_kwargs"]["phone_number"] == "87761973970"
    assert any(progress["stage"] == "gopay_wallet_funding_skipped" for progress in captured["progress"])


def test_gopay_auto_signup_transfer_polls_gopay_balance_after_rekberinaja(monkeypatch):
    captured = {"progress": [], "sleep": [], "funded": [], "run_kwargs": None, "balance_calls": []}
    account = {"email": "user@example.com"}

    monkeypatch.setenv("REKBERINAJA_ENABLED", "1")
    monkeypatch.setenv("REKBERINAJA_TRANSFER_ENABLED", "1")
    monkeypatch.setattr(api.time, "sleep", lambda seconds: captured["sleep"].append(seconds))
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: account if email == account["email"] else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda *_args, **_kwargs: None)

    class FakeWallet:
        phone_number = "87761973970"
        access_token = "gopay-token"
        session = object()
        gopay_cfg = {"unique_id": "device-1"}

        def as_phone_account(self):
            return {
                "country_code": "62",
                "phone_number": self.phone_number,
                "sms_url": "http://127.0.0.1:8787/otp/gopay-signup/demo",
                "gopay_pin": "558023",
                "otp_channel": "sms",
            }

        def close(self, *, success=True):
            pass

    monkeypatch.setattr("autotoken.gopay_auto_register.register_gopay_wallet", lambda **_kwargs: FakeWallet())

    def fake_query_balance(**kwargs):
        captured["balance_calls"].append(kwargs)
        value = 1 if len(captured["balance_calls"]) >= 3 else 0
        return {"value": value, "currency": "IDR", "display_value": f"Rp{value}"}

    monkeypatch.setattr("autotoken.gopay_auto_register.query_gopay_balance", fake_query_balance)
    monkeypatch.setattr(
        "autotoken.rekberinaja.fund_gopay_wallet_if_enabled",
        lambda phone_number, **_kwargs: captured["funded"].append(phone_number) or {"transaction_id": "trx-1"},
    )

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "email_used": "user@example.com",
            "successful_emails": ["user@example.com"],
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-transfer-poll", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(email="user@example.com", gopay_pin="558023", gopay_auto_signup=True)
    )
    result = captured["func"]()

    assert result["task_status"] == "completed"
    assert captured["funded"] == ["87761973970"]
    assert len(captured["balance_calls"]) == 3
    assert captured["sleep"] == [20.0, 20.0]
    assert captured["run_kwargs"]["phone_number"] == "87761973970"
    assert any(progress["stage"] == "gopay_wallet_funding_done" for progress in captured["progress"])
    assert any(progress["stage"] == "gopay_wallet_balance_ready" for progress in captured["progress"])


def test_gopay_auto_signup_waits_before_bind_when_rekberinaja_transfer_disabled(monkeypatch):
    captured = {"progress": [], "sleep": [], "run_kwargs": None}
    account = {"email": "user@example.com"}

    monkeypatch.setenv("REKBERINAJA_ENABLED", "1")
    monkeypatch.setenv("REKBERINAJA_TRANSFER_ENABLED", "0")
    monkeypatch.setattr(api, "_gopay_auto_signup_no_transfer_bind_wait_seconds", lambda: 60)
    monkeypatch.setattr(api.time, "sleep", lambda seconds: captured["sleep"].append(seconds))
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: account if email == account["email"] else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda *_args, **_kwargs: None)

    class FakeWallet:
        phone_number = "87761973970"

        def as_phone_account(self):
            return {
                "country_code": "62",
                "phone_number": self.phone_number,
                "sms_url": "http://127.0.0.1:8787/otp/gopay-signup/demo",
                "gopay_pin": "558023",
                "otp_channel": "sms",
            }

        def close(self, *, success=True):
            pass

    monkeypatch.setattr("autotoken.gopay_auto_register.register_gopay_wallet", lambda **_kwargs: FakeWallet())
    monkeypatch.setattr(
        "autotoken.rekberinaja.fund_gopay_wallet_if_enabled",
        lambda *_args, **_kwargs: pytest.fail("transfer must stay disabled"),
    )

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "email_used": "user@example.com",
            "successful_emails": ["user@example.com"],
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-no-transfer-wait", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="user@example.com",
            gopay_pin="558023",
            gopay_auto_signup=True,
        )
    )

    result = captured["func"]()

    assert result["task_status"] == "completed"
    assert captured["run_kwargs"]["phone_number"] == "87761973970"
    assert captured["sleep"] and captured["sleep"][0] <= 60
    assert any(progress["stage"] == "gopay_wallet_no_transfer_bind_wait" for progress in captured["progress"])
    assert not any(progress["stage"] == "gopay_wallet_funding_started" for progress in captured["progress"])


def test_gopay_auto_signup_queries_balance_before_bind_when_token_available(monkeypatch):
    captured = {"progress": [], "sleep": [], "run_kwargs": None, "balance_calls": []}
    account = {"email": "user@example.com"}

    monkeypatch.setenv("REKBERINAJA_ENABLED", "1")
    monkeypatch.setenv("REKBERINAJA_TRANSFER_ENABLED", "0")
    monkeypatch.setattr(api.time, "sleep", lambda seconds: captured["sleep"].append(seconds))
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: account if email == account["email"] else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda *_args, **_kwargs: None)

    class FakeWallet:
        phone_number = "87761973970"
        access_token = "gopay-token"
        session = object()
        gopay_cfg = {"unique_id": "device-1"}

        def as_phone_account(self):
            return {
                "country_code": "62",
                "phone_number": self.phone_number,
                "sms_url": "http://127.0.0.1:8787/otp/gopay-signup/demo",
                "gopay_pin": "558023",
                "otp_channel": "sms",
            }

        def close(self, *, success=True):
            pass

    monkeypatch.setattr("autotoken.gopay_auto_register.register_gopay_wallet", lambda **_kwargs: FakeWallet())

    def fake_query_balance(**kwargs):
        captured["balance_calls"].append(kwargs)
        return {"value": 1, "currency": "IDR", "display_value": "Rp1"}

    monkeypatch.setattr("autotoken.gopay_auto_register.query_gopay_balance", fake_query_balance)

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "email_used": "user@example.com",
            "successful_emails": ["user@example.com"],
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-balance-query", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="user@example.com",
            gopay_pin="558023",
            gopay_auto_signup=True,
        )
    )

    result = captured["func"]()

    assert result["task_status"] == "completed"
    assert captured["run_kwargs"]["phone_number"] == "87761973970"
    assert len(captured["balance_calls"]) == 1
    assert captured["balance_calls"][0]["access_token"] == "gopay-token"
    assert captured["sleep"] == [20.0]
    assert any(progress["stage"] == "gopay_wallet_balance_checked" for progress in captured["progress"])
    assert any(progress["stage"] == "gopay_wallet_balance_ready" for progress in captured["progress"])
    assert not any(progress["stage"] == "gopay_wallet_no_transfer_bind_wait" for progress in captured["progress"])


def test_gopay_auto_signup_discards_wallet_and_reregisters_when_balance_not_ready(monkeypatch):
    captured = {"progress": [], "sleep": [], "run_kwargs": None, "balance_calls": [], "closed": [], "signup_calls": 0}
    account = {"email": "user@example.com"}

    monkeypatch.setenv("REKBERINAJA_ENABLED", "1")
    monkeypatch.setenv("REKBERINAJA_TRANSFER_ENABLED", "0")
    monkeypatch.setattr(api.time, "sleep", lambda seconds: captured["sleep"].append(seconds))
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: account if email == account["email"] else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda *_args, **_kwargs: None)

    class FakeWallet:
        session = object()
        gopay_cfg = {"unique_id": "device-1"}

        def __init__(self, index):
            self.index = index
            self.phone_number = f"8776197397{index}"
            self.access_token = f"gopay-token-{index}"

        def as_phone_account(self):
            return {
                "country_code": "62",
                "phone_number": self.phone_number,
                "sms_url": f"http://127.0.0.1:8787/otp/gopay-signup/{self.index}",
                "gopay_pin": "558023",
                "otp_channel": "sms",
            }

        def close(self, *, success=True):
            captured["closed"].append((self.index, success))

    def fake_register_wallet(**_kwargs):
        captured["signup_calls"] += 1
        return FakeWallet(captured["signup_calls"])

    monkeypatch.setattr("autotoken.gopay_auto_register.register_gopay_wallet", fake_register_wallet)

    def fake_query_balance(**kwargs):
        captured["balance_calls"].append(kwargs)
        if kwargs["access_token"] == "gopay-token-1":
            return {"value": 0, "currency": "IDR", "display_value": "Rp0"}
        return {"value": 1, "currency": "IDR", "display_value": "Rp1"}

    monkeypatch.setattr("autotoken.gopay_auto_register.query_gopay_balance", fake_query_balance)

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "email_used": "user@example.com",
            "successful_emails": ["user@example.com"],
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-balance-reregister", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="user@example.com",
            gopay_pin="558023",
            gopay_auto_signup=True,
        )
    )

    result = captured["func"]()

    assert result["task_status"] == "completed"
    assert captured["signup_calls"] == 2
    assert captured["run_kwargs"]["phone_number"] == "87761973972"
    assert [call["access_token"] for call in captured["balance_calls"]] == [
        "gopay-token-1",
        "gopay-token-1",
        "gopay-token-1",
        "gopay-token-1",
        "gopay-token-1",
        "gopay-token-1",
        "gopay-token-2",
    ]
    assert captured["sleep"] == [20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0]
    assert captured["closed"] == [(1, False), (2, True)]
    assert any(progress["stage"] == "gopay_wallet_balance_abandoned" for progress in captured["progress"])
    retry_progress = [
        progress for progress in captured["progress"] if progress["stage"] == "gopay_wallet_auto_signup_retry"
    ]
    assert [(progress["current"], progress["attempt"], progress["max_attempts"]) for progress in retry_progress] == [
        (1, 2, 10)
    ]


def test_gopay_auto_signup_switches_to_transfer_after_three_missing_official_rp(monkeypatch):
    captured = {
        "progress": [],
        "sleep": [],
        "run_kwargs": None,
        "balance_calls": [],
        "closed": [],
        "funded": [],
        "signup_calls": 0,
    }
    account = {"email": "user@example.com"}

    monkeypatch.setenv("REKBERINAJA_ENABLED", "1")
    monkeypatch.setenv("REKBERINAJA_TRANSFER_ENABLED", "0")
    monkeypatch.setattr(api, "_gopay_wallet_balance_poll_intervals_from_env", lambda: [0])
    monkeypatch.setattr(api.time, "sleep", lambda seconds: captured["sleep"].append(seconds))
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: account if email == account["email"] else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda *_args, **_kwargs: None)

    class FakeWallet:
        session = object()
        gopay_cfg = {"unique_id": "device-1"}

        def __init__(self, index):
            self.index = index
            self.phone_number = f"8776197397{index}"
            self.access_token = f"gopay-token-{index}"

        def as_phone_account(self):
            return {
                "country_code": "62",
                "phone_number": self.phone_number,
                "sms_url": f"http://127.0.0.1:8787/otp/gopay-signup/{self.index}",
                "gopay_pin": "558023",
                "otp_channel": "sms",
            }

        def close(self, *, success=True):
            captured["closed"].append((self.index, success))

    def fake_register_wallet(**_kwargs):
        captured["signup_calls"] += 1
        return FakeWallet(captured["signup_calls"])

    monkeypatch.setattr("autotoken.gopay_auto_register.register_gopay_wallet", fake_register_wallet)

    def fake_query_balance(**kwargs):
        captured["balance_calls"].append(kwargs)
        token = kwargs["access_token"]
        if token == "gopay-token-3" and "87761973973" in captured["funded"]:
            return {"value": 1, "currency": "IDR", "display_value": "Rp1"}
        return {"value": 0, "currency": "IDR", "display_value": "Rp0"}

    monkeypatch.setattr("autotoken.gopay_auto_register.query_gopay_balance", fake_query_balance)

    def fake_fund(phone_number, **_kwargs):
        captured["funded"].append(phone_number)
        return {"transaction_id": "trx-3", "status": "completed"}

    monkeypatch.setattr("autotoken.rekberinaja.fund_gopay_wallet_if_enabled", fake_fund)

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"] = kwargs
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "email_used": "user@example.com",
            "successful_emails": ["user@example.com"],
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-balance-auto-transfer", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="user@example.com",
            gopay_pin="558023",
            gopay_auto_signup=True,
        )
    )

    result = captured["func"]()

    assert result["task_status"] == "completed"
    assert captured["signup_calls"] == 3
    assert captured["funded"] == ["87761973973"]
    assert captured["run_kwargs"]["phone_number"] == "87761973973"
    assert captured["closed"] == [(1, False), (2, False), (3, True)]
    assert any(progress["stage"] == "gopay_wallet_balance_auto_transfer_enabled" for progress in captured["progress"])
    assert any(progress["stage"] == "gopay_wallet_funding_started" for progress in captured["progress"])
    assert any(progress["stage"] == "gopay_wallet_funding_done" for progress in captured["progress"])


def test_gopay_auto_signup_disables_transfer_after_three_1001_balances(monkeypatch):
    captured = {
        "progress": [],
        "sleep": [],
        "run_kwargs": [],
        "balance_calls": [],
        "closed": [],
        "funded": [],
        "signup_calls": 0,
    }
    accounts = [
        {"email": "first@example.com"},
        {"email": "second@example.com"},
        {"email": "third@example.com"},
        {"email": "fourth@example.com"},
    ]

    monkeypatch.setenv("REKBERINAJA_ENABLED", "1")
    monkeypatch.setenv("REKBERINAJA_TRANSFER_ENABLED", "1")
    monkeypatch.setattr(api, "_gopay_wallet_balance_poll_intervals_from_env", lambda: [0])
    monkeypatch.setattr(api.time, "sleep", lambda seconds: captured["sleep"].append(seconds))
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda acc: f"data/auth_session/{acc['email']}.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda *_args, **_kwargs: None)

    class FakeWallet:
        session = object()
        gopay_cfg = {"unique_id": "device-1"}

        def __init__(self, index):
            self.index = index
            self.phone_number = f"8776197397{index}"
            self.access_token = f"gopay-token-{index}"

        def as_phone_account(self):
            return {
                "country_code": "62",
                "phone_number": self.phone_number,
                "sms_url": f"http://127.0.0.1:8787/otp/gopay-signup/{self.index}",
                "gopay_pin": "558023",
                "otp_channel": "sms",
            }

        def close(self, *, success=True):
            captured["closed"].append((self.index, success))

    def fake_register_wallet(**_kwargs):
        captured["signup_calls"] += 1
        return FakeWallet(captured["signup_calls"])

    monkeypatch.setattr("autotoken.gopay_auto_register.register_gopay_wallet", fake_register_wallet)

    def fake_query_balance(**kwargs):
        captured["balance_calls"].append(kwargs)
        token = kwargs["access_token"]
        wallet_index = int(token.rsplit("-", 1)[1])
        phone = f"8776197397{wallet_index}"
        if wallet_index <= 3:
            value = 1001 if phone in captured["funded"] else 0
        else:
            value = 1
        return {"value": value, "currency": "IDR", "display_value": f"Rp{value}"}

    monkeypatch.setattr("autotoken.gopay_auto_register.query_gopay_balance", fake_query_balance)

    def fake_fund(phone_number, **_kwargs):
        captured["funded"].append(phone_number)
        return {"transaction_id": f"trx-{len(captured['funded'])}", "status": "submitted"}

    monkeypatch.setattr("autotoken.rekberinaja.fund_gopay_wallet_if_enabled", fake_fund)

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"].append(kwargs)
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "email_used": kwargs["email"],
            "successful_emails": [kwargs["email"]],
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-transfer-auto-disabled", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="first@example.com",
            account_emails=["first@example.com", "second@example.com", "third@example.com", "fourth@example.com"],
            gopay_pin="558023",
            gopay_auto_signup=True,
        )
    )

    result = captured["func"]()

    assert result["task_status"] == "completed"
    assert captured["signup_calls"] == 4
    assert captured["funded"] == ["87761973971", "87761973972", "87761973973"]
    assert [item["phone_number"] for item in captured["run_kwargs"]] == [
        "87761973971",
        "87761973972",
        "87761973973",
        "87761973974",
    ]
    assert any(progress["stage"] == "gopay_wallet_transfer_auto_disabled" for progress in captured["progress"])
    assert any(
        progress["stage"] == "gopay_wallet_balance_ready"
        and progress.get("phone_number") == "***3974(len=11)"
        and progress.get("balance") == 1
        for progress in captured["progress"]
    )


def test_gopay_auto_signup_stops_after_three_funded_balance_insufficient(monkeypatch):
    captured = {
        "progress": [],
        "sleep": [],
        "run_kwargs": [],
        "balance_calls": [],
        "closed": [],
        "funded": [],
        "signup_calls": 0,
    }
    accounts = [
        {"email": "first@example.com"},
        {"email": "second@example.com"},
        {"email": "third@example.com"},
        {"email": "fourth@example.com"},
    ]

    monkeypatch.setenv("REKBERINAJA_ENABLED", "1")
    monkeypatch.setenv("REKBERINAJA_TRANSFER_ENABLED", "1")
    monkeypatch.setattr(api, "_gopay_wallet_balance_poll_intervals_from_env", lambda: [0])
    monkeypatch.setattr(api.time, "sleep", lambda seconds: captured["sleep"].append(seconds))
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda acc: f"data/auth_session/{acc['email']}.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda *_args, **_kwargs: None)

    class FakeWallet:
        session = object()
        gopay_cfg = {"unique_id": "device-1"}

        def __init__(self, index):
            self.index = index
            self.phone_number = f"8776197397{index}"
            self.access_token = f"gopay-token-{index}"

        def as_phone_account(self):
            return {
                "country_code": "62",
                "phone_number": self.phone_number,
                "sms_url": f"http://127.0.0.1:8787/otp/gopay-signup/{self.index}",
                "gopay_pin": "558023",
                "otp_channel": "sms",
            }

        def close(self, *, success=True):
            captured["closed"].append((self.index, success))

    def fake_register_wallet(**_kwargs):
        captured["signup_calls"] += 1
        return FakeWallet(captured["signup_calls"])

    monkeypatch.setattr("autotoken.gopay_auto_register.register_gopay_wallet", fake_register_wallet)

    def fake_query_balance(**kwargs):
        captured["balance_calls"].append(kwargs)
        return {"value": 0, "currency": "IDR", "display_value": "Rp0"}

    monkeypatch.setattr("autotoken.gopay_auto_register.query_gopay_balance", fake_query_balance)

    def fake_fund(phone_number, **_kwargs):
        captured["funded"].append(phone_number)
        return {"transaction_id": f"trx-{len(captured['funded'])}", "status": "submitted"}

    monkeypatch.setattr("autotoken.rekberinaja.fund_gopay_wallet_if_enabled", fake_fund)

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"].append(kwargs)
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "email_used": kwargs["email"],
            "successful_emails": [kwargs["email"]],
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-balance-insufficient-stop", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="first@example.com",
            account_emails=["first@example.com", "second@example.com", "third@example.com", "fourth@example.com"],
            gopay_pin="558023",
            gopay_auto_signup=True,
            gopay_concurrency=1,
        )
    )

    with pytest.raises(api.TaskResultError) as exc_info:
        captured["func"]()
    result = exc_info.value.task_result

    assert result["task_status"] == "failed"
    assert result["failure_stage"] == "gopay_wallet_balance_insufficient"
    assert captured["signup_calls"] == 3
    assert captured["funded"] == ["87761973971", "87761973972", "87761973973"]
    assert captured["run_kwargs"] == []
    assert captured["closed"] == [(1, False), (2, False), (3, False)]
    assert any(progress["stage"] == "gopay_wallet_balance_insufficient_limit" for progress in captured["progress"])


def test_gopay_auto_signup_retries_same_wallet_when_no_transfer_balance_pending(monkeypatch):
    captured = {"progress": [], "sleep": [], "run_kwargs": [], "calls": 0}
    account = {"email": "user@example.com"}

    monkeypatch.setenv("REKBERINAJA_ENABLED", "1")
    monkeypatch.setenv("REKBERINAJA_TRANSFER_ENABLED", "0")
    monkeypatch.setattr(api, "_gopay_auto_signup_no_transfer_retry_waits_seconds", lambda: [120, 180])
    monkeypatch.setattr(api.time, "sleep", lambda seconds: captured["sleep"].append(seconds))
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: account if email == account["email"] else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda *_args, **_kwargs: None)

    class FakeWallet:
        phone_number = "87761973970"

        def as_phone_account(self):
            return {
                "country_code": "62",
                "phone_number": self.phone_number,
                "sms_url": "http://127.0.0.1:8787/otp/gopay-signup/demo",
                "gopay_pin": "558023",
                "otp_channel": "sms",
            }

        def close(self, *, success=True):
            pass

    monkeypatch.setattr("autotoken.gopay_auto_register.register_gopay_wallet", lambda **_kwargs: FakeWallet())

    def fake_run_gopay_bind_task(**kwargs):
        captured["calls"] += 1
        captured["run_kwargs"].append(kwargs)
        if captured["calls"] == 1:
            return {
                "status": "failed",
                "failure_stage": "gopay_payment_process",
                "message": "GoPay payment/process 未成功: insufficient balance",
                "email_used": "user@example.com",
            }
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "email_used": "user@example.com",
            "successful_emails": ["user@example.com"],
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-no-transfer-retry", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="user@example.com",
            gopay_pin="558023",
            gopay_auto_signup=True,
        )
    )

    with pytest.raises(api.TaskResultError) as exc_info:
        captured["func"]()
    result = exc_info.value.task_result

    assert result["task_status"] == "failed"
    assert captured["calls"] == 1
    assert captured["sleep"] == []
    assert any(progress["stage"] == "gopay_wallet_balance_abandoned" for progress in captured["progress"])
    assert not any(progress["stage"] == "gopay_wallet_no_transfer_balance_wait" for progress in captured["progress"])


def test_gopay_auto_signup_preserves_wallet_after_no_transfer_balance_retry_exhausted(monkeypatch):
    captured = {"progress": [], "sleep": [], "calls": 0}
    account = {"email": "user@example.com"}

    monkeypatch.setenv("REKBERINAJA_ENABLED", "1")
    monkeypatch.setenv("REKBERINAJA_TRANSFER_ENABLED", "0")
    monkeypatch.setattr(api, "_gopay_auto_signup_no_transfer_retry_waits_seconds", lambda: [120])
    monkeypatch.setattr(api.time, "sleep", lambda seconds: captured["sleep"].append(seconds))
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.accounts.find_account", lambda accounts, email: account if email == account["email"] else None
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda _acc: "data/auth_session/user@example.com.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda *_args, **_kwargs: None)

    class FakeWallet:
        phone_number = "87761973970"

        def as_phone_account(self):
            return {
                "country_code": "62",
                "phone_number": self.phone_number,
                "sms_url": "http://127.0.0.1:8787/otp/gopay-signup/demo",
                "gopay_pin": "558023",
                "otp_channel": "sms",
            }

        def close(self, *, success=True):
            pass

    monkeypatch.setattr("autotoken.gopay_auto_register.register_gopay_wallet", lambda **_kwargs: FakeWallet())

    def fake_run_gopay_bind_task(**_kwargs):
        captured["calls"] += 1
        return {
            "status": "failed",
            "failure_stage": "post_submit",
            "message": "GoPay payment/process failed: insufficient balance",
            "email_used": "user@example.com",
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-no-transfer-preserve", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="user@example.com",
            gopay_pin="558023",
            gopay_auto_signup=True,
        )
    )

    with pytest.raises(api.TaskResultError) as exc_info:
        captured["func"]()
    result = exc_info.value.task_result

    assert result["task_status"] == "failed"
    assert captured["calls"] == 1
    assert captured["sleep"] == []
    assert any(progress["stage"] == "gopay_wallet_balance_abandoned" for progress in captured["progress"])
    assert not any(progress["stage"] == "gopay_wallet_preserved" for progress in captured["progress"])


def test_gopay_reused_wallet_skips_duplicate_funding_after_debited_rekberinaja_failure(monkeypatch):
    from autotoken.rekberinaja import RekberinajaError

    captured = {"progress": [], "closed": [], "funded": [], "run_kwargs": [], "signup_calls": 0, "funcs": []}
    accounts = [{"email": "first@example.com"}, {"email": "second@example.com"}]

    monkeypatch.setenv("REKBERINAJA_ENABLED", "1")
    monkeypatch.setenv("REKBERINAJA_TRANSFER_ENABLED", "1")
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda acc: f"data/auth_session/{acc['email']}.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda *_args, **_kwargs: None)

    class FakeWallet:
        phone_number = "87761973970"

        def as_phone_account(self):
            return {
                "country_code": "62",
                "phone_number": self.phone_number,
                "sms_url": "http://127.0.0.1:8787/otp/gopay-signup/reuse",
                "gopay_pin": "558023",
                "otp_channel": "sms",
            }

        def close(self, *, success=True):
            captured["closed"].append(success)

    def fake_register_wallet(**_kwargs):
        captured["signup_calls"] += 1
        return FakeWallet()

    monkeypatch.setattr("autotoken.gopay_auto_register.register_gopay_wallet", fake_register_wallet)
    monkeypatch.setattr("autotoken.gopay_auto_register.is_sms_bridge_reusable", lambda _token: (True, "active"))

    def fake_fund(phone_number, **kwargs):
        captured["funded"].append(phone_number)
        progress = kwargs.get("progress")
        if progress:
            progress("rekberinaja_saldo_pay_done", {"transaction_id": "trx-1", "message": "Rekberinaja 站内支付已提交"})
        raise RekberinajaError(
            "Rekberinaja GoPay 充值失败: transaction_id=trx-1 status=fail message=订单失败",
            stage="poll_order",
            transaction_id="trx-1",
            status="fail",
            debited_possible=True,
        )

    monkeypatch.setattr("autotoken.rekberinaja.fund_gopay_wallet_if_enabled", fake_fund)

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"].append(kwargs)
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "email_used": kwargs["email"],
            "successful_emails": [kwargs["email"]],
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["funcs"].append(func)
        return {"task_id": f"task-{len(captured['funcs'])}", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(email="first@example.com", gopay_pin="558023", gopay_auto_signup=True)
    )
    with pytest.raises(api.TaskResultError):
        captured["funcs"][0]()

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(email="second@example.com", gopay_pin="558023", gopay_auto_signup=True)
    )
    result = captured["funcs"][1]()

    assert result["task_status"] == "completed"
    assert captured["signup_calls"] == 1
    assert captured["funded"] == ["87761973970"]
    assert [item["phone_number"] for item in captured["run_kwargs"]] == ["87761973970"]
    assert any(progress["stage"] == "gopay_wallet_funding_failed" for progress in captured["progress"])
    assert any(progress["stage"] == "gopay_wallet_funding_skipped" for progress in captured["progress"])


def test_gopay_auto_signup_batch_registers_new_wallet_after_consuming_failure(monkeypatch):
    captured = {"progress": [], "closed": [], "run_kwargs": [], "signup_calls": 0}
    accounts = [{"email": "first@example.com"}, {"email": "second@example.com"}]

    monkeypatch.setenv("REKBERINAJA_ENABLED", "0")
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda acc: f"data/auth_session/{acc['email']}.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda *_args, **_kwargs: None)

    class FakeWallet:
        def __init__(self, index):
            self.index = index
            self.phone_number = f"8776197397{index}"

        def as_phone_account(self):
            return {
                "country_code": "62",
                "phone_number": self.phone_number,
                "sms_url": f"http://127.0.0.1:8787/otp/gopay-signup/{self.index}",
                "gopay_pin": "558023",
                "otp_channel": "sms",
            }

        def close(self, *, success=True):
            captured["closed"].append((self.index, success))

    def fake_register_wallet(**kwargs):
        captured["signup_calls"] += 1
        captured.setdefault("signup_kwargs", []).append(kwargs)
        return FakeWallet(captured["signup_calls"])

    monkeypatch.setattr("autotoken.gopay_auto_register.register_gopay_wallet", fake_register_wallet)

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"].append(kwargs)
        if kwargs["email"] == "first@example.com":
            return {
                "status": "failed",
                "failure_stage": "gopay_payment_process",
                "message": "GoPay 扣款授权失败",
                "email_used": "first@example.com",
                "payment_failed_emails": ["first@example.com"],
            }
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "email_used": "second@example.com",
            "successful_emails": ["second@example.com"],
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-bridge", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="first@example.com",
            account_emails=["first@example.com", "second@example.com"],
            gopay_pin="558023",
            gopay_auto_signup=True,
        )
    )

    result = captured["func"]()

    assert result["status"] == "success"
    assert result["email_used"] == "second@example.com"
    assert captured["signup_calls"] == 2
    assert [item["email"] for item in captured["run_kwargs"]] == ["first@example.com", "second@example.com"]
    assert all(item["account_emails"] == [] for item in captured["run_kwargs"])
    assert captured["run_kwargs"][0]["phone_number"] == "87761973971"
    assert captured["run_kwargs"][1]["phone_number"] == "87761973972"


def test_gopay_auto_signup_batch_reuses_wallet_after_chatgpt_account_failure(monkeypatch):
    captured = {"progress": [], "closed": [], "run_kwargs": [], "signup_calls": 0}
    accounts = [{"email": "first@example.com"}, {"email": "second@example.com"}]

    monkeypatch.setenv("REKBERINAJA_ENABLED", "0")
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: accounts)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    monkeypatch.setattr(api, "_resolve_status_auth_file", lambda acc: f"data/auth_session/{acc['email']}.json")
    monkeypatch.setattr(api, "_append_task_progress", lambda _task_id, progress: captured["progress"].append(progress))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda *_args, **_kwargs: None)

    class FakeWallet:
        phone_number = "87761973970"

        def as_phone_account(self):
            return {
                "country_code": "62",
                "phone_number": self.phone_number,
                "sms_url": "http://127.0.0.1:8787/otp/gopay-signup/reuse",
                "gopay_pin": "558023",
                "otp_channel": "sms",
            }

        def close(self, *, success=True):
            captured["closed"].append(success)

    def fake_register_wallet(**_kwargs):
        captured["signup_calls"] += 1
        return FakeWallet()

    monkeypatch.setattr("autotoken.gopay_auto_register.register_gopay_wallet", fake_register_wallet)

    def fake_run_gopay_bind_task(**kwargs):
        captured["run_kwargs"].append(kwargs)
        if kwargs["email"] == "first@example.com":
            return {
                "status": "failed",
                "failure_stage": "generate_checkout",
                "message": "执行 GoPay 任务时出现异常: HTTP 403: HTTP 403",
                "email_used": "first@example.com",
            }
        return {
            "status": "success",
            "message": "GoPay 绑定完成",
            "email_used": "second@example.com",
            "successful_emails": ["second@example.com"],
        }

    monkeypatch.setattr("autotoken.gopay_executor.run_gopay_bind_task", fake_run_gopay_bind_task)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["func"] = func
        return {"task_id": "task-bridge", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.post_gopay_bind_task(
        api.GoPayBindTaskParams(
            email="first@example.com",
            account_emails=["first@example.com", "second@example.com"],
            gopay_pin="558023",
            gopay_auto_signup=True,
        )
    )

    result = captured["func"]()

    assert result["status"] == "success"
    assert result["email_used"] == "second@example.com"
    assert captured["signup_calls"] == 1
    assert [item["email"] for item in captured["run_kwargs"]] == ["first@example.com", "second@example.com"]
    assert captured["run_kwargs"][0]["phone_number"] == "87761973970"
    assert captured["run_kwargs"][1]["phone_number"] == "87761973970"
    assert any(progress["stage"] == "gopay_wallet_preserved" for progress in captured["progress"])


def test_roxybrowser_config_response_uses_runtime_env(monkeypatch):
    monkeypatch.setenv("ROXYBROWSER_API_HOST", "127.0.0.1:50000")
    monkeypatch.setenv("ROXYBROWSER_API_TOKEN", "secret-token")

    cfg = build_roxybrowser_config_response(mask_secret=api._mask_secret_for_config)

    assert cfg["api_host"] == "http://127.0.0.1:50000"
    assert cfg["api_token_present"] is True
    assert "workspace_id" not in cfg
    assert "dir_id" not in cfg
    assert cfg["configured"] is True


def test_roxybrowser_config_response_marks_missing_token(monkeypatch):
    monkeypatch.setenv("ROXYBROWSER_API_HOST", "http://127.0.0.1:50000")
    monkeypatch.delenv("ROXYBROWSER_API_TOKEN", raising=False)
    monkeypatch.setattr("autotoken.setup_wizard._read_env", lambda: {})

    cfg = build_roxybrowser_config_response(mask_secret=api._mask_secret_for_config)

    assert cfg["api_host"] == "http://127.0.0.1:50000"
    assert cfg["api_token_present"] is False
    assert cfg["configured"] is False
    assert "ROXYBROWSER_API_TOKEN" in cfg["missing_keys"]
