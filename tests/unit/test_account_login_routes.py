import pytest
from fastapi import HTTPException

from autotoken.api_routes.account_login import (
    ACCOUNT_LOGIN_BATCH_DEFAULT_CONCURRENCY,
    ACCOUNT_LOGIN_BATCH_MAX_EMAILS,
    AccountEmailBatchParams,
    LoginAccountParams,
    create_account_login_router,
)
from autotoken.services.task_runtime import TASK_GROUP_OAUTH


def _routes(
    started,
    *,
    accounts=None,
    main_email="owner@example.com",
    build_oauth_proxy_selector=None,
    run_account_codex_login_once=None,
):
    accounts = accounts if accounts is not None else [{"email": "user@example.com"}]
    build_oauth_proxy_selector = build_oauth_proxy_selector or (lambda **_kwargs: (lambda: "", {}))
    run_account_codex_login_once = run_account_codex_login_once or (
        lambda email, _acc, **_kwargs: {"email": email, "plan": "free"}
    )

    def start_task(command, func, params, *args, **kwargs):
        started.append({"command": command, "func": func, "params": params, "args": args, "kwargs": kwargs})
        return {"task_id": "task-1", "command": command, "params": params}

    router = create_account_login_router(
        start_task=start_task,
        normalize_email=lambda value: str(value or "").strip().lower(),
        is_main_account_email=lambda email: str(email or "").strip().lower() == main_email,
        build_oauth_proxy_selector=build_oauth_proxy_selector,
        run_account_codex_login_once=run_account_codex_login_once,
        append_task_progress=lambda _task_id, _progress: None,
        oauth_phone_required_result=lambda email, exc: {"email": email, "message": str(exc), "removed_pool_emails": []},
        oauth_phone_rate_limited_result=lambda email, exc: {"email": email, "message": str(exc), "removed_pool_emails": []},
        oauth_login_required_result=lambda email, exc: {"email": email, "message": str(exc), "removed_pool_emails": []},
        oauth_account_deactivated_result=lambda email, exc: {"email": email, "message": str(exc), "removed_pool_emails": []},
        task_result_error=RuntimeError,
        logger=type(
            "Logger",
            (),
            {
                "info": lambda *_args, **_kwargs: None,
                "warning": lambda *_args, **_kwargs: None,
                "exception": lambda *_args, **_kwargs: None,
                "error": lambda *_args, **_kwargs: None,
            },
        )(),
    )
    routes = {route.endpoint.__name__: route.endpoint for route in router.routes}
    return routes, accounts


def test_post_account_login_rejects_main_account(monkeypatch):
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [{"email": "owner@example.com"}])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda _accounts, _email: {"email": "owner@example.com"})

    routes, _accounts = _routes([], main_email="owner@example.com")

    with pytest.raises(HTTPException) as exc_info:
        routes["post_account_login"](LoginAccountParams(email="owner@example.com"))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "主号不属于账号池登录对象"


def test_post_account_login_starts_oauth_task(monkeypatch):
    started = []
    account = {"email": "user@example.com"}
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda _accounts, email: account if email == "user@example.com" else None)

    routes, _accounts = _routes(started)
    result = routes["post_account_login"](LoginAccountParams(email="USER@example.com"))

    assert result == {"task_id": "task-1", "command": "login:user@example.com", "params": {"email": "user@example.com"}}
    assert started[0]["kwargs"]["task_group"] == TASK_GROUP_OAUTH
    assert started[0]["kwargs"]["pass_task_id"] is True
    assert started[0]["kwargs"]["exclusive"] is True
    assert started[0]["func"]("task-1") == {"email": "user@example.com", "plan": "free"}


def test_post_account_login_can_start_nonexclusive_oauth_task(monkeypatch):
    started = []
    account = {"email": "user@example.com"}
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda _accounts, email: account if email == "user@example.com" else None)

    routes, _accounts = _routes(started)
    routes["post_account_login"](LoginAccountParams(email="USER@example.com", exclusive=False))

    assert started[0]["kwargs"]["task_group"] == TASK_GROUP_OAUTH
    assert started[0]["kwargs"]["pass_task_id"] is True
    assert started[0]["kwargs"]["exclusive"] is False


def test_post_account_login_translates_proxy_pool_errors(monkeypatch):
    account = {"email": "user@example.com"}
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda _accounts, _email: account)

    def bad_proxy_selector(**_kwargs):
        raise ValueError("代理池文本过大")

    routes, _accounts = _routes([], build_oauth_proxy_selector=bad_proxy_selector)

    with pytest.raises(HTTPException) as exc_info:
        routes["post_account_login"](LoginAccountParams(email="user@example.com"))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "代理池文本过大"


def test_post_account_login_passes_protocol_oauth_config(monkeypatch):
    started = []
    account = {"email": "+27734762109"}
    captured = {}
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda _accounts, email: account if email == "+27734762109" else None)

    def fake_run(email, acc, **kwargs):
        captured.update({"email": email, "acc": acc, "kwargs": kwargs})
        return {"email": "bound@example.com", "plan": "plus"}

    routes, _accounts = _routes(started, accounts=[account], run_account_codex_login_once=fake_run)
    routes["post_account_login"](
        LoginAccountParams(
            email="+27734762109",
            mail_provider="luckmail",
            luckmail_email_type="ms_imap",
            luckmail_preferred_domain="outlook.com",
            oauth_phone_sms_provider="phone_pool",
            oauth_phone_sms_country="187",
        )
    )

    assert started[0]["func"]("task-1") == {"email": "bound@example.com", "plan": "plus"}
    assert captured["email"] == "+27734762109"
    progress_callback = captured["kwargs"].pop("progress_callback")
    assert callable(progress_callback)
    assert captured["kwargs"] == {
        "headless": False,
        "protocol_only": True,
        "bind_email": True,
        "mail_provider": "luckmail",
        "luckmail_email_type": "ms_imap",
        "luckmail_preferred_domain": "outlook.com",
        "oauth_phone_sms_provider": "phone_pool",
        "oauth_phone_sms_country": "187",
    }


def test_post_accounts_login_batch_requires_emails():
    with pytest.raises(HTTPException) as exc_info:
        routes, _accounts = _routes([])
        routes["post_accounts_login_batch"](AccountEmailBatchParams(emails=[]))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "emails 不能为空"


def test_post_accounts_login_batch_rejects_too_many_raw_emails():
    routes, _accounts = _routes([])

    with pytest.raises(HTTPException) as exc_info:
        routes["post_accounts_login_batch"](
            AccountEmailBatchParams(
                emails=[f"user{index}@example.com" for index in range(ACCOUNT_LOGIN_BATCH_MAX_EMAILS + 1)]
            )
        )

    assert exc_info.value.status_code == 400
    assert "批量补登录账号过多" in exc_info.value.detail


def test_post_accounts_login_batch_starts_single_task(monkeypatch):
    started = []
    rows = [{"email": "first@example.com"}, {"email": "second@example.com"}]
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: rows)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda accounts, email: next((account for account in accounts if account["email"] == email), None),
    )

    routes, _accounts = _routes(started)
    result = routes["post_accounts_login_batch"](AccountEmailBatchParams(emails=["FIRST@example.com", "second@example.com"]))

    assert result["command"] == "login-batch"
    assert result["params"] == {"emails": ["first@example.com", "second@example.com"], "missing": []}
    assert started[0]["kwargs"]["task_group"] == TASK_GROUP_OAUTH
    assert started[0]["kwargs"]["pass_task_id"] is True
    run_result = started[0]["func"]("task-batch")
    assert run_result["total"] == 2
    assert sorted(item["email"] for item in run_result["ok"]) == ["first@example.com", "second@example.com"]


def test_post_accounts_login_batch_defaults_to_ten_workers(monkeypatch):
    started = []
    rows = [{"email": f"user{index}@example.com"} for index in range(12)]
    monkeypatch.delenv("CODEX_OAUTH_BATCH_CONCURRENCY", raising=False)
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: rows)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda accounts, email: next((account for account in accounts if account["email"] == email), None),
    )

    routes, _accounts = _routes(started, accounts=rows)
    routes["post_accounts_login_batch"](AccountEmailBatchParams(emails=[row["email"] for row in rows]))

    result = started[0]["func"]("task-batch")

    assert result["total"] == 12
    assert result["concurrency"] == ACCOUNT_LOGIN_BATCH_DEFAULT_CONCURRENCY


def test_post_accounts_login_batch_passes_protocol_email_domain(monkeypatch):
    started = []
    rows = [{"email": "first@example.com"}]
    captured = []
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: rows)
    monkeypatch.setattr("autotoken.accounts.find_account", lambda _accounts, email: rows[0] if email == "first@example.com" else None)

    def fake_run(email, acc, **kwargs):
        captured.append((email, acc, kwargs))
        return {"email": email, "plan": "free"}

    routes, _accounts = _routes(started, accounts=rows, run_account_codex_login_once=fake_run)
    routes["post_accounts_login_batch"](
        AccountEmailBatchParams(
            emails=["first@example.com"],
            mail_provider="cloud-mail",
            email_domain="example.com",
            oauth_phone_sms_provider="smsbower",
            oauth_phone_sms_country="187",
        )
    )

    result = started[0]["func"]("task-batch")
    assert result["total"] == 1
    assert captured[0][2]["protocol_only"] is True
    assert captured[0][2]["bind_email"] is True
    assert captured[0][2]["mail_provider"] == "cloud-mail"
    assert captured[0][2]["email_domain"] == "example.com"
    assert captured[0][2]["oauth_phone_sms_provider"] == "smsbower"
    assert captured[0][2]["oauth_phone_sms_country"] == "187"
