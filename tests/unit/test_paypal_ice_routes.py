import anyio
import pytest
from fastapi import HTTPException

from autotoken.api_routes.paypal_ice import (
    PayPalIceJobParams,
    PayPalIceOAuthLoginParams,
    PayPalIceTrialCheckParams,
    _clean_oauth_login_config,
    _paypal_ice_job_history,
    _paypal_ice_job_summary,
    create_paypal_ice_router,
)
from autotoken.core.timestamps import epoch_seconds


class FakeRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


def _routes(*, start_oauth_login=None, get_task=None):
    return {
        route.endpoint.__name__: route.endpoint
        for route in create_paypal_ice_router(
            mask_secret=lambda value: f"masked:{value}",
            start_oauth_login=start_oauth_login,
            get_task=get_task,
        ).routes
    }


def test_paypal_ice_config_masks_api_key(monkeypatch):
    monkeypatch.setattr(
        "autotoken.settings.setup_wizard._read_env",
        lambda: {"PAYPAL_ICE_BASE_URL": "https://plus.example.test", "PAYPAL_ICE_API_KEY": "ice-key"},
    )

    result = _routes()["get_paypal_ice_config"]()

    assert result == {
        "base_url": "https://plus.example.test",
        "api_key_present": True,
        "api_key_masked": "masked:ice-key",
        "configured": True,
    }


def test_save_paypal_ice_config_writes_env(monkeypatch):
    written = {}
    monkeypatch.setattr("autotoken.settings.setup_wizard._read_env", lambda: {})
    monkeypatch.setattr("autotoken.settings.setup_wizard._write_env", lambda key, value: written.update({key: value}))

    result = anyio.run(
        _routes()["save_paypal_ice_config"],
        FakeRequest({"base_url": "https://plus.example.test/", "api_key": "ice-key"}),
    )

    assert written["PAYPAL_ICE_BASE_URL"] == "https://plus.example.test"
    assert written["PAYPAL_ICE_API_KEY"] == "ice-key"
    assert result["configured"] is True
    assert result["message"] == "PayPal ICE 配置已保存"


def test_paypal_ice_summary_sets_stable_finished_at(monkeypatch):
    monkeypatch.setattr("autotoken.api_routes.paypal_ice.time.time", lambda: 1111.0)

    first = _paypal_ice_job_summary(
        {
            "job_id": "job-1",
            "status": "success",
            "result_code": "SUCCESS",
            "client_ref": "account@example.com",
        }
    )

    monkeypatch.setattr("autotoken.api_routes.paypal_ice.time.time", lambda: 2222.0)
    second = _paypal_ice_job_summary(
        {
            "job_id": "job-1",
            "status": "success",
            "result_code": "SUCCESS",
            "client_ref": "account@example.com",
        },
        fallback=first,
    )

    assert first["finished_at"] == 1111.0
    assert second["finished_at"] == 1111.0


def test_paypal_ice_history_backfills_success_finished_at(monkeypatch):
    monkeypatch.setattr(
        "autotoken.api_routes.paypal_ice.sqlite_store.get_json",
        lambda *_args, **_kwargs: [
            {
                "job_id": "job-old",
                "status": "success",
                "result_code": "SUCCESS",
                "created_at": 1000.0,
                "updated_at": 1234.0,
            }
        ],
    )

    assert _paypal_ice_job_history()[0]["finished_at"] == 1234.0


def test_paypal_ice_trial_check_uses_nerver_endpoint(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return FakeResponse(
            {
                "token_ok": True,
                "eligible": True,
                "reason": "",
                "message": "可开通：trial 可用",
                "coupon_state": "eligibile",
                "status": 200,
                "email": "user@example.com",
                "account_id": "acct-1",
                "plan_type": "free",
            }
        )

    monkeypatch.delenv("PAYPAL_ICE_TRIAL_CHECK_URL", raising=False)
    monkeypatch.setattr("autotoken.api_routes.paypal_ice.requests.post", fake_post)

    result = _routes()["post_paypal_ice_trial_check"](
        PayPalIceTrialCheckParams(token=" token-1 ", proxy_jp="ignored")
    )

    assert captured["url"] == "https://cha.nerver.cc/api/v1/check"
    assert captured["json"] == {"token": "token-1"}
    assert result["eligible"] is True
    assert result["resource_mode"] == "eligibile"
    assert result["account_id"] == "acct-1"


def test_paypal_ice_trial_check_normalizes_invalid_token(monkeypatch):
    def fake_post(_url, **_kwargs):
        return FakeResponse(
            {
                "token_ok": False,
                "eligible": False,
                "reason": "token_invalid",
                "message": "access token invalid",
                "coupon_state": "",
                "status": 401,
            }
        )

    monkeypatch.setattr("autotoken.api_routes.paypal_ice.requests.post", fake_post)

    result = _routes()["post_paypal_ice_trial_check"](PayPalIceTrialCheckParams(token="bad-token"))

    assert result["token_ok"] is False
    assert result["eligible"] is False
    assert result["blocked"] is False
    assert result["status"] == "access token invalid"
    assert result["status_code"] == 401


def test_paypal_ice_subscription_check_uses_nerver_endpoint(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return FakeResponse(
            {
                "status": "success",
                "plan_type": "plus",
                "has_active_subscription": True,
                "subscription_plan": "chatgptplusplan",
            }
        )

    monkeypatch.delenv("PAYPAL_ICE_SUBSCRIPTION_URL", raising=False)
    monkeypatch.setattr("autotoken.api_routes.paypal_ice.requests.post", fake_post)

    result = _routes()["post_paypal_ice_subscription"](PayPalIceTrialCheckParams(token=" token-plus "))

    assert captured["url"] == "https://cha.nerver.cc/api/v1/subscription"
    assert captured["json"] == {"token": "token-plus"}
    assert result["plan_type"] == "plus"
    assert result["has_active_subscription"] is True


def test_paypal_ice_job_uses_bearer_and_idempotency(monkeypatch):
    captured = {}
    history = []

    def fake_set_json(_namespace, _key, value):
        history[:] = list(value)
        return value

    monkeypatch.setattr(
        "autotoken.settings.setup_wizard._read_env",
        lambda: {"PAYPAL_ICE_BASE_URL": "https://plus.example.test", "PAYPAL_ICE_API_KEY": "ice-key"},
    )
    monkeypatch.setattr("autotoken.api_routes.paypal_ice.sqlite_store.get_json", lambda *_args, **_kwargs: history)
    monkeypatch.setattr("autotoken.api_routes.paypal_ice.sqlite_store.set_json", fake_set_json)

    def fake_request(method, url, **kwargs):
        captured.update({"method": method, "url": url, **kwargs})
        return FakeResponse(
            {
                "job_id": "job-1",
                "status": "queued",
                "progress": "34%",
                "stage": "creating_invoice",
                "message": "正在创建 PayPal 订单",
            }
        )

    monkeypatch.setattr("autotoken.api_routes.paypal_ice.requests.request", fake_request)

    result = _routes()["post_paypal_ice_job"](
        type(
            "Params",
            (),
            {
                "input": "token-1",
                "client_ref": "user@example.com",
                "callback_url": "",
                "proxy": "",
                "proxy_jp": "",
                "phone": "08012345678",
                "sms_api": "https://sms.example.test",
                "email": "",
                "cookies": None,
                "pplink_retry": 3,
                "otp_timeout": 180,
                "idempotency_key": "idem-1",
            },
        )()
    )

    assert result["job_id"] == "job-1"
    assert result["progress_percent"] == 34
    assert result["progress_stage"] == "creating_invoice"
    assert result["progress_message"] == "正在创建 PayPal 订单"
    assert captured["method"] == "POST"
    assert captured["url"] == "https://plus.example.test/api/v1/jobs"
    assert captured["headers"]["Authorization"] == "Bearer ice-key"
    assert captured["headers"]["Idempotency-Key"] == "idem-1"
    assert captured["json"]["input"] == "token-1"
    assert captured["json"]["phone"] == "08012345678"
    assert captured["json"]["sms_api"] == "https://sms.example.test"
    jobs = _routes()["list_paypal_ice_jobs"]()
    assert jobs["items"][0]["job_id"] == "job-1"
    assert jobs["items"][0]["client_ref"] == "user@example.com"
    assert jobs["items"][0]["status"] == "queued"
    assert jobs["items"][0]["progress_percent"] == 34


def test_paypal_ice_job_extracts_nested_progress(monkeypatch):
    history = []

    def fake_set_json(_namespace, _key, value):
        history[:] = list(value)
        return value

    monkeypatch.setattr(
        "autotoken.settings.setup_wizard._read_env",
        lambda: {"PAYPAL_ICE_BASE_URL": "https://plus.example.test", "PAYPAL_ICE_API_KEY": "ice-key"},
    )
    monkeypatch.setattr("autotoken.api_routes.paypal_ice.sqlite_store.get_json", lambda *_args, **_kwargs: history)
    monkeypatch.setattr("autotoken.api_routes.paypal_ice.sqlite_store.set_json", fake_set_json)

    def fake_request(method, url, **kwargs):
        return FakeResponse(
            {
                "job_id": "job-nested",
                "status": "running",
                "progress": {"percentage": 0.42, "stage_name": "prepare_checkout"},
                "logs": [{"message": "开始"}, {"message": "开通链接准备中"}],
            }
        )

    monkeypatch.setattr("autotoken.api_routes.paypal_ice.requests.request", fake_request)

    result = _routes()["get_paypal_ice_job"]("job-nested")

    assert result["progress_available"] is True
    assert result["progress_percent"] == 42
    assert result["progress_stage"] == "prepare_checkout"
    assert result["progress_message"] == "开通链接准备中"


def test_paypal_ice_job_requires_phone_sms_pair():
    with pytest.raises(HTTPException) as exc_info:
        _routes()["post_paypal_ice_job"](
            type(
                "Params",
                (),
                {
                    "input": "token-1",
                    "client_ref": "",
                    "callback_url": "",
                    "proxy": "",
                    "proxy_jp": "",
                    "phone": "08012345678",
                    "sms_api": "",
                    "email": "",
                    "cookies": None,
                    "pplink_retry": None,
                    "otp_timeout": None,
                    "idempotency_key": "",
                },
            )()
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "phone 和 sms_api 必须同时提供，或设置 use_pool=true 自动分配"


def test_paypal_ice_job_can_acquire_phone_from_pool(monkeypatch):
    history = []
    associated = []

    monkeypatch.setattr(
        "autotoken.settings.setup_wizard._read_env",
        lambda: {"PAYPAL_ICE_BASE_URL": "https://plus.example.test", "PAYPAL_ICE_API_KEY": "ice-key"},
    )
    monkeypatch.setattr("autotoken.api_routes.paypal_ice.sqlite_store.get_json", lambda *_args, **_kwargs: history)
    monkeypatch.setattr(
        "autotoken.api_routes.paypal_ice.sqlite_store.set_json",
        lambda _namespace, _key, value: history.__setitem__(slice(None), list(value)) or value,
    )
    monkeypatch.setattr(
        "autotoken.services.paypal_ice_phone_pool.acquire_phone",
        lambda: {
            "id": "phone-1",
            "phone_number": "08080051197",
            "sms_api": "https://sms.example.test/code",
        },
    )
    monkeypatch.setattr(
        "autotoken.services.paypal_ice_phone_pool.associate_job",
        lambda phone_id, job_id: associated.append((phone_id, job_id)),
    )

    captured = {}

    def fake_request(method, url, **kwargs):
        captured.update({"method": method, "url": url, **kwargs})
        return FakeResponse({"job_id": "job-pool", "status": "queued"})

    monkeypatch.setattr("autotoken.api_routes.paypal_ice.requests.request", fake_request)

    result = _routes()["post_paypal_ice_job"](
        PayPalIceJobParams(input="token-1", client_ref="user@example.com", use_pool=True)
    )

    assert result["job_id"] == "job-pool"
    assert captured["json"]["phone"] == "08080051197"
    assert captured["json"]["sms_api"] == "https://sms.example.test/code"
    assert associated == [("phone-1", "job-pool")]


def test_paypal_ice_success_marks_client_ref_plus(monkeypatch):
    history = []
    account_updates = []

    def fake_set_json(_namespace, _key, value):
        history[:] = list(value)
        return value

    monkeypatch.setattr(
        "autotoken.settings.setup_wizard._read_env",
        lambda: {"PAYPAL_ICE_BASE_URL": "https://plus.example.test", "PAYPAL_ICE_API_KEY": "ice-key"},
    )
    monkeypatch.setattr("autotoken.api_routes.paypal_ice.sqlite_store.get_json", lambda *_args, **_kwargs: history)
    monkeypatch.setattr("autotoken.api_routes.paypal_ice.sqlite_store.set_json", fake_set_json)
    monkeypatch.setattr("autotoken.api_routes.paypal_ice.time.time", lambda: 1234567890.0)
    monkeypatch.setattr(
        "autotoken.storage.accounts.update_account",
        lambda email, **kwargs: account_updates.append((email, kwargs)) or {"email": email, **kwargs},
    )

    def fake_request(method, url, **kwargs):
        return FakeResponse(
            {
                "job_id": "job-success",
                "status": "success",
                "result_code": "SUCCESS",
                "client_ref": "+27734762109",
                "billing_status": "charged",
                "finished_at": "2026-06-12T19:28:00Z",
                "oauth_login_result_email": "bound@example.com",
            }
        )

    monkeypatch.setattr("autotoken.api_routes.paypal_ice.requests.request", fake_request)

    result = _routes()["get_paypal_ice_job"]("job-success")
    bind_at = float(epoch_seconds("2026-06-12T19:28:00Z"))

    assert result["result_code"] == "SUCCESS"
    assert account_updates == [
        (
            "+27734762109",
            {
                "status": "active",
                "account_type": "plus",
                "last_bind_status": "success",
                "last_bind_at": bind_at,
                "last_bind_provider": "paypal_ice",
                "last_bind_task_id": "job-success",
                "last_bind_message": "PayPal ICE 激活成功",
                "last_bind_failure_stage": "",
                "plus_bound_at": bind_at,
            },
        ),
        (
            "bound@example.com",
            {
                "status": "active",
                "account_type": "plus",
                "last_bind_status": "success",
                "last_bind_at": bind_at,
                "last_bind_provider": "paypal_ice",
                "last_bind_task_id": "job-success",
                "last_bind_message": "PayPal ICE 激活成功",
                "last_bind_failure_stage": "",
                "plus_bound_at": bind_at,
            },
        ),
    ]


def test_paypal_ice_auto_oauth_login_defaults_off():
    params = PayPalIceJobParams(input="token", phone="08012345678", sms_api="https://sms.example.test")

    assert params.auto_oauth_login is False


def test_paypal_ice_oauth_config_filters_provider_specific_stale_values():
    payload = _clean_oauth_login_config(
        PayPalIceOAuthLoginParams(
            mail_provider="outlook",
            luckmail_email_type="ms_imap",
            luckmail_preferred_domain="outlook.com",
            email_domain="example.com",
            oauth_phone_sms_provider="phone_pool",
            oauth_phone_sms_country="187",
        )
    )

    assert payload == {
        "protocol_only": True,
        "bind_email": True,
        "mail_provider": "outlook",
    }


def test_paypal_ice_success_starts_auto_oauth_login_once(monkeypatch):
    kv = {}
    started = []
    tasks = {}

    monkeypatch.setattr(
        "autotoken.settings.setup_wizard._read_env",
        lambda: {"PAYPAL_ICE_BASE_URL": "https://plus.example.test", "PAYPAL_ICE_API_KEY": "ice-key"},
    )
    monkeypatch.setattr(
        "autotoken.api_routes.paypal_ice.sqlite_store.get_json",
        lambda namespace, key, default=None, **_kwargs: kv.get((namespace, key), default),
    )
    monkeypatch.setattr(
        "autotoken.api_routes.paypal_ice.sqlite_store.set_json",
        lambda namespace, key, value, **_kwargs: kv.__setitem__((namespace, key), value) or value,
    )
    monkeypatch.setattr(
        "autotoken.api_routes.paypal_ice.sqlite_store.delete_key",
        lambda namespace, key, **_kwargs: kv.pop((namespace, key), None),
    )
    monkeypatch.setattr("autotoken.storage.accounts.update_account", lambda email, **kwargs: {"email": email, **kwargs})

    def fake_request(method, url, **_kwargs):
        if method == "POST":
            return FakeResponse({"job_id": "job-auto", "status": "queued", "client_ref": "+27734762109"})
        return FakeResponse(
            {
                "job_id": "job-auto",
                "status": "success",
                "result_code": "SUCCESS",
                "client_ref": "+27734762109",
            }
        )

    def start_oauth_login(payload):
        started.append(payload)
        tasks["oauth-task"] = {"task_id": "oauth-task", "status": "pending"}
        return tasks["oauth-task"]

    monkeypatch.setattr("autotoken.api_routes.paypal_ice.requests.request", fake_request)
    routes = _routes(start_oauth_login=start_oauth_login, get_task=lambda task_id: tasks.get(task_id))
    routes["post_paypal_ice_job"](
        PayPalIceJobParams(
            input="token",
            client_ref="+27734762109",
            phone="08012345678",
            sms_api="https://sms.example.test",
            auto_oauth_login=True,
            oauth_login_config=PayPalIceOAuthLoginParams(
                mail_provider="luckmail",
                luckmail_email_type="ms_imap",
                luckmail_preferred_domain="outlook.com",
                oauth_phone_sms_provider="phone_pool",
                oauth_phone_sms_country="187",
            ),
        )
    )

    success = routes["get_paypal_ice_job"]("job-auto")
    assert success["oauth_login_task_id"] == "oauth-task"
    assert success["oauth_login_status"] == "pending"
    assert started == [
        {
            "email": "+27734762109",
            "protocol_only": True,
            "bind_email": True,
            "mail_provider": "luckmail",
            "luckmail_email_type": "ms_imap",
            "luckmail_preferred_domain": "outlook.com",
            "exclusive": False,
        }
    ]

    tasks["oauth-task"] = {
        "task_id": "oauth-task",
        "status": "running",
        "progress": {
            "stage": "phone_first_add_email_otp_wait",
            "message": "等待绑定邮箱 OTP",
            "email": "+27734762109",
        },
        "progress_events": [
            {
                "stage": "phone_first_add_email_started",
                "message": "开始绑定邮箱: bound@example.com",
                "email": "+27734762109",
            },
            {
                "stage": "phone_first_add_email_otp_wait",
                "message": "等待绑定邮箱 OTP",
                "email": "+27734762109",
            },
        ],
    }
    running = routes["get_paypal_ice_job"]("job-auto")
    assert running["oauth_login_status"] == "running"
    assert running["oauth_login_progress_stage"] == "phone_first_add_email_otp_wait"
    assert running["oauth_login_progress_message"] == "等待绑定邮箱 OTP"
    assert running["oauth_login_progress_events"][-1]["stage"] == "phone_first_add_email_otp_wait"

    tasks["oauth-task"] = {
        "task_id": "oauth-task",
        "status": "completed",
        "result": {"email": "bound@example.com"},
    }
    completed = routes["get_paypal_ice_job"]("job-auto")

    assert len(started) == 1
    assert completed["oauth_login_status"] == "completed"
    assert completed["oauth_login_result_email"] == "bound@example.com"
    assert completed["oauth_login_progress_stage"] == "phone_first_add_email_otp_wait"


def test_paypal_ice_auto_oauth_adopts_same_account_running_task(monkeypatch):
    kv = {}
    tasks = {
        "existing-oauth": {
            "task_id": "existing-oauth",
            "status": "completed",
            "result": {"email": "bound@example.com"},
            "progress": {"stage": "account_login_done", "message": "补登录成功: +27635220036"},
        }
    }

    monkeypatch.setattr(
        "autotoken.settings.setup_wizard._read_env",
        lambda: {"PAYPAL_ICE_BASE_URL": "https://plus.example.test", "PAYPAL_ICE_API_KEY": "ice-key"},
    )
    monkeypatch.setattr(
        "autotoken.api_routes.paypal_ice.sqlite_store.get_json",
        lambda namespace, key, default=None, **_kwargs: kv.get((namespace, key), default),
    )
    monkeypatch.setattr(
        "autotoken.api_routes.paypal_ice.sqlite_store.set_json",
        lambda namespace, key, value, **_kwargs: kv.__setitem__((namespace, key), value) or value,
    )
    monkeypatch.setattr(
        "autotoken.api_routes.paypal_ice.sqlite_store.delete_key",
        lambda namespace, key, **_kwargs: kv.pop((namespace, key), None),
    )
    monkeypatch.setattr("autotoken.storage.accounts.update_account", lambda email, **kwargs: {"email": email, **kwargs})

    def fake_request(method, url, **_kwargs):
        if method == "POST":
            return FakeResponse({"job_id": "job-conflict", "status": "queued", "client_ref": "+27635220036"})
        return FakeResponse(
            {
                "job_id": "job-conflict",
                "status": "success",
                "result_code": "SUCCESS",
                "client_ref": "+27635220036",
            }
        )

    def start_oauth_login(_payload):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "同类任务正在执行，请等待完成后再试",
                "running_task": {
                    "task_id": "existing-oauth",
                    "command": "login:+27635220036",
                    "task_group": "oauth",
                },
            },
        )

    monkeypatch.setattr("autotoken.api_routes.paypal_ice.requests.request", fake_request)
    routes = _routes(start_oauth_login=start_oauth_login, get_task=lambda task_id: tasks.get(task_id))
    routes["post_paypal_ice_job"](
        PayPalIceJobParams(
            input="token",
            client_ref="+27635220036",
            phone="08012345678",
            sms_api="https://sms.example.test",
            auto_oauth_login=True,
        )
    )

    result = routes["get_paypal_ice_job"]("job-conflict")

    assert result["oauth_login_task_id"] == "existing-oauth"
    assert result["oauth_login_status"] == "completed"
    assert result["oauth_login_error"] == ""
    assert result["oauth_login_result_email"] == "bound@example.com"


def test_paypal_ice_auto_oauth_retries_failed_login_three_times(monkeypatch):
    kv = {}
    started = []
    tasks = {}

    monkeypatch.setattr(
        "autotoken.settings.setup_wizard._read_env",
        lambda: {"PAYPAL_ICE_BASE_URL": "https://plus.example.test", "PAYPAL_ICE_API_KEY": "ice-key"},
    )
    monkeypatch.setattr(
        "autotoken.api_routes.paypal_ice.sqlite_store.get_json",
        lambda namespace, key, default=None, **_kwargs: kv.get((namespace, key), default),
    )
    monkeypatch.setattr(
        "autotoken.api_routes.paypal_ice.sqlite_store.set_json",
        lambda namespace, key, value, **_kwargs: kv.__setitem__((namespace, key), value) or value,
    )
    monkeypatch.setattr(
        "autotoken.api_routes.paypal_ice.sqlite_store.delete_key",
        lambda namespace, key, **_kwargs: kv.pop((namespace, key), None),
    )
    monkeypatch.setattr("autotoken.storage.accounts.update_account", lambda email, **kwargs: {"email": email, **kwargs})

    def fake_request(method, url, **_kwargs):
        if method == "POST":
            return FakeResponse({"job_id": "job-retry", "status": "queued", "client_ref": "+27635220036"})
        return FakeResponse(
            {
                "job_id": "job-retry",
                "status": "success",
                "result_code": "SUCCESS",
                "client_ref": "+27635220036",
            }
        )

    def start_oauth_login(payload):
        started.append(payload)
        task_id = f"oauth-task-{len(started)}"
        tasks[task_id] = {"task_id": task_id, "status": "pending"}
        return tasks[task_id]

    monkeypatch.setattr("autotoken.api_routes.paypal_ice.requests.request", fake_request)
    routes = _routes(start_oauth_login=start_oauth_login, get_task=lambda task_id: tasks.get(task_id))
    routes["post_paypal_ice_job"](
        PayPalIceJobParams(
            input="token",
            client_ref="+27635220036",
            phone="08012345678",
            sms_api="https://sms.example.test",
            auto_oauth_login=True,
        )
    )
    first = routes["get_paypal_ice_job"]("job-retry")
    assert first["oauth_login_status"] == "pending"
    assert first["oauth_login_task_id"] == "oauth-task-1"

    for attempt in range(1, 4):
        tasks[f"oauth-task-{attempt}"] = {
            "task_id": f"oauth-task-{attempt}",
            "status": "failed",
            "error": f"bind failed {attempt}",
        }
        retried = routes["get_paypal_ice_job"]("job-retry")
        assert retried["oauth_login_status"] == "pending"
        assert retried["oauth_login_task_id"] == f"oauth-task-{attempt + 1}"
        assert retried["oauth_login_retry_count"] == attempt

    tasks["oauth-task-4"] = {
        "task_id": "oauth-task-4",
        "status": "failed",
        "error": "bind failed final",
    }
    failed = routes["get_paypal_ice_job"]("job-retry")

    assert len(started) == 4
    assert failed["oauth_login_status"] == "failed"
    assert failed["oauth_login_retry_count"] == 3
    assert failed["oauth_login_task_id"] == "oauth-task-4"
    assert failed["oauth_login_error"] == "bind failed final，已重试 3 次"
