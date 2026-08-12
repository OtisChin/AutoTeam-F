import json

import pytest
from fastapi import HTTPException

from autotoken.api_routes.account_login import (
    ACCOUNT_LOGIN_BATCH_DEFAULT_CONCURRENCY,
    ACCOUNT_LOGIN_BATCH_MAX_EMAILS,
    AccountEmailBatchAppendParams,
    AccountEmailBatchParams,
    LoginAccountParams,
    MailAccountAuthSessionBatchParams,
    create_account_login_router,
)
from autotoken.services.task_runtime import TASK_GROUP_OAUTH


def _routes(
    started,
    *,
    accounts=None,
    main_email="owner@example.com",
    build_oauth_proxy_selector=None,
    preflight_oauth_proxy_url=None,
    run_account_codex_login_once=None,
    current_oauth_task=None,
    init_oauth_batch_control=None,
    append_oauth_batch_emails=None,
    drain_oauth_batch_emails=None,
):
    accounts = accounts if accounts is not None else [{"email": "user@example.com"}]
    build_oauth_proxy_selector = build_oauth_proxy_selector or (lambda **_kwargs: (lambda: "", {}))
    preflight_oauth_proxy_url = preflight_oauth_proxy_url or (lambda _proxy_url, **_kwargs: (True, "ok"))
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
        preflight_oauth_proxy_url=preflight_oauth_proxy_url,
        run_account_codex_login_once=run_account_codex_login_once,
        append_task_progress=lambda _task_id, _progress: None,
        oauth_phone_required_result=lambda email, exc: {"email": email, "message": str(exc), "removed_pool_emails": []},
        oauth_phone_rate_limited_result=lambda email, exc: {"email": email, "message": str(exc), "removed_pool_emails": []},
        oauth_login_required_result=lambda email, exc: {"email": email, "message": str(exc), "removed_pool_emails": []},
        oauth_account_deactivated_result=lambda email, exc: {"email": email, "message": str(exc), "removed_pool_emails": []},
        task_result_error=RuntimeError,
        current_oauth_task=current_oauth_task,
        init_oauth_batch_control=init_oauth_batch_control,
        append_oauth_batch_emails=append_oauth_batch_emails,
        drain_oauth_batch_emails=drain_oauth_batch_emails,
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


def test_post_accounts_login_batch_append_adds_emails_to_running_oauth_task(monkeypatch):
    appended = {}
    rows = [{"email": "first@example.com"}, {"email": "second@example.com"}]
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: rows)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda accounts, email: next((account for account in accounts if account["email"] == email), None),
    )

    routes, _accounts = _routes(
        [],
        accounts=rows,
        current_oauth_task=lambda: {
            "task_id": "task-oauth",
            "command": "login-batch",
            "status": "running",
            "params": {"emails": ["first@example.com"]},
        },
        append_oauth_batch_emails=lambda task_id, emails: (
            appended.setdefault("value", (task_id, emails)),
            {"added_emails": emails, "duplicates": []},
        )[1],
    )

    result = routes["post_accounts_login_batch_append"](
        AccountEmailBatchAppendParams(emails=["SECOND@example.com", "missing@example.com"])
    )

    assert appended["value"] == ("task-oauth", ["second@example.com"])
    assert result["added_emails"] == ["second@example.com"]
    assert result["missing"] == ["missing@example.com"]


def test_post_accounts_login_batch_processes_appended_accounts_after_first_round(monkeypatch):
    started = []
    rows = [{"email": "first@example.com"}, {"email": "second@example.com"}]
    calls = []
    drain_calls = {"count": 0}
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: rows)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda accounts, email: next((account for account in accounts if account["email"] == email), None),
    )
    monkeypatch.setenv("CODEX_OAUTH_BATCH_CONCURRENCY", "1")

    def fake_run(email, acc, **_kwargs):
        calls.append((email, acc))
        return {"email": email, "plan": "free"}

    def fake_drain(_task_id, existing):
        drain_calls["count"] += 1
        if drain_calls["count"] == 1:
            assert existing == {"first@example.com"}
            return ["second@example.com"]
        return []

    routes, _accounts = _routes(
        started,
        accounts=rows,
        run_account_codex_login_once=fake_run,
        init_oauth_batch_control=lambda *_args, **_kwargs: None,
        drain_oauth_batch_emails=fake_drain,
    )
    routes["post_accounts_login_batch"](AccountEmailBatchParams(emails=["first@example.com"]))

    result = started[0]["func"]("task-batch")

    assert [email for email, _acc in calls] == ["first@example.com", "second@example.com"]
    assert result["total"] == 2
    assert sorted(item["email"] for item in result["ok"]) == ["first@example.com", "second@example.com"]


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


def test_post_account_login_refresh_session_with_auth_file_uses_oauth_authorization(monkeypatch):
    started = []
    oauth_calls = []
    plain_calls = []
    account = {"email": "revoked@example.com", "status": "auth_revoked", "auth_file": "auths/old.json"}
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda _accounts, email: account if email == "revoked@example.com" else None)

    def fake_oauth_run(email, acc, **kwargs):
        oauth_calls.append((email, acc, kwargs))
        return {"email": email, "plan": "plus"}

    def fake_plain_relogin(email, acc, **kwargs):
        plain_calls.append((email, acc, kwargs))
        return {"email": email, "status": "success", "auth_session_file": "auth_session/revoked.json", "codex_auth_updated": True}

    routes, _accounts = _routes(started, accounts=[account], run_account_codex_login_once=fake_oauth_run)
    monkeypatch.setattr(
        "autotoken.api_routes.account_login.relogin_account_auth_session_once",
        fake_plain_relogin,
        raising=False,
    )
    routes["post_account_login"](
        LoginAccountParams(email="revoked@example.com", refresh_auth_session=True, protocol_only=False)
    )
    task_result = started[0]["func"]("task-1")

    assert task_result == {"email": "revoked@example.com", "plan": "plus"}
    assert plain_calls == []
    assert oauth_calls[0][2]["refresh_auth_session"] is True
    assert oauth_calls[0][2]["protocol_only"] is True


def test_post_account_login_refresh_session_without_auth_file_uses_plain_relogin(monkeypatch):
    started = []
    oauth_calls = []
    plain_calls = []
    account = {"email": "missing-auth@example.com", "password": "pw", "auth_file": ""}
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda _accounts, email: account if email == "missing-auth@example.com" else None)

    def fake_oauth_run(email, acc, **kwargs):
        oauth_calls.append((email, acc, kwargs))
        return {"email": email, "plan": "free"}

    def fake_plain_relogin(email, acc, **kwargs):
        plain_calls.append((email, acc, kwargs))
        return {"email": email, "status": "success", "auth_session_file": "auth_session/missing-auth.json"}

    routes, _accounts = _routes(started, accounts=[account], run_account_codex_login_once=fake_oauth_run)
    monkeypatch.setattr(
        "autotoken.api_routes.account_login.relogin_account_auth_session_once",
        fake_plain_relogin,
        raising=False,
    )
    routes["post_account_login"](LoginAccountParams(email="missing-auth@example.com", refresh_auth_session=True))
    task_result = started[0]["func"]("task-1")

    assert task_result == {"email": "missing-auth@example.com", "status": "success", "auth_session_file": "auth_session/missing-auth.json"}
    assert oauth_calls == []
    assert plain_calls[0][0] == "missing-auth@example.com"
    assert "update_codex_auth" not in plain_calls[0][2]


def test_post_accounts_login_batch_refresh_session_with_auth_file_uses_oauth_authorization(monkeypatch):
    started = []
    oauth_calls = []
    plain_calls = []
    account = {"email": "revoked@example.com", "status": "auth_revoked", "auth_file": "auths/old.json"}
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda _accounts, email: account if email == "revoked@example.com" else None)
    monkeypatch.setenv("CODEX_OAUTH_BATCH_CONCURRENCY", "1")

    def fake_oauth_run(email, acc, **kwargs):
        oauth_calls.append((email, acc, kwargs))
        return {"email": email, "plan": "plus"}

    def fake_plain_relogin(email, acc, **kwargs):
        plain_calls.append((email, acc, kwargs))
        return {"email": email, "status": "success", "codex_auth_updated": True}

    routes, _accounts = _routes(started, accounts=[account], run_account_codex_login_once=fake_oauth_run)
    monkeypatch.setattr(
        "autotoken.api_routes.account_login.relogin_account_auth_session_once",
        fake_plain_relogin,
        raising=False,
    )
    routes["post_accounts_login_batch"](
        AccountEmailBatchParams(emails=["revoked@example.com"], refresh_auth_session=True, protocol_only=False)
    )
    task_result = started[0]["func"]("task-batch")

    assert started[0]["params"]["refresh_auth_session"] is True
    assert task_result["ok"] == [{"email": "revoked@example.com", "plan": "plus"}]
    assert plain_calls == []
    assert oauth_calls[0][2]["refresh_auth_session"] is True
    assert oauth_calls[0][2]["protocol_only"] is True


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


def test_post_accounts_login_batch_passes_bind_phone(monkeypatch):
    started = []
    rows = [{"email": "first@example.com"}]
    captured = []
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: rows)
    monkeypatch.setattr("autotoken.accounts.find_account", lambda _accounts, email: rows[0] if email == "first@example.com" else None)

    def fake_run(email, acc, **kwargs):
        captured.append((email, acc, kwargs))
        return {"email": email, "plan": "plus"}

    routes, _accounts = _routes(started, accounts=rows, run_account_codex_login_once=fake_run)
    routes["post_accounts_login_batch"](
        AccountEmailBatchParams(
            emails=["first@example.com"],
            bind_email=False,
            bind_phone=True,
            oauth_phone_sms_provider="smsbower",
            oauth_phone_sms_country="187",
            oauth_phone_sms_max_price="0.05",
        )
    )

    result = started[0]["func"]("task-batch")
    assert result["total"] == 1
    assert captured[0][2]["bind_email"] is False
    assert captured[0][2]["bind_phone"] is True
    assert captured[0][2]["oauth_phone_sms_provider"] == "smsbower"
    assert captured[0][2]["oauth_phone_sms_country"] == "187"
    assert captured[0][2]["oauth_phone_sms_max_price"] == "0.05"


def test_post_accounts_login_batch_passes_proxy_api_country(monkeypatch):
    started = []
    rows = [{"email": "first@example.com"}]
    selector_calls = []
    captured = []
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: rows)
    monkeypatch.setattr("autotoken.accounts.find_account", lambda _accounts, email: rows[0] if email == "first@example.com" else None)

    def build_selector(**kwargs):
        selector_calls.append(kwargs)
        return (lambda: "socks5h://batch-proxy.example:1000"), {"proxy_api_provider": kwargs.get("proxy_api_provider")}

    def fake_run(email, acc, **kwargs):
        captured.append((email, acc, kwargs))
        return {"email": email, "plan": "plus"}

    routes, _accounts = _routes(
        started,
        accounts=rows,
        build_oauth_proxy_selector=build_selector,
        run_account_codex_login_once=fake_run,
    )
    routes["post_accounts_login_batch"](
        AccountEmailBatchParams(
            emails=["first@example.com"],
            proxy_api_provider="cliproxy",
            proxy_api_url="https://proxy-api.example/get",
            proxy_api_country="GB",
        )
    )

    result = started[0]["func"]("task-batch")
    assert result["total"] == 1
    assert selector_calls[0]["proxy_api_country"] == "GB"
    assert captured[0][2]["proxy_url"] == "socks5h://batch-proxy.example:1000"


def test_post_accounts_login_batch_retries_oauth_proxy_api_until_preflight_passes(monkeypatch):
    started = []
    rows = [{"email": "first@example.com"}]
    selector_calls = []
    preflighted = []
    captured = []
    proxies = ["socks5h://bad-batch-proxy.example:1000", "socks5h://good-batch-proxy.example:1001"]
    monkeypatch.setenv("CODEX_OAUTH_BATCH_CONCURRENCY", "1")
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: rows)
    monkeypatch.setattr("autotoken.accounts.find_account", lambda _accounts, email: rows[0] if email == "first@example.com" else None)

    def build_selector(**kwargs):
        selector_calls.append(kwargs)

        def selector():
            return proxies.pop(0)

        return selector, {"proxy_api_provider": kwargs.get("proxy_api_provider"), "proxy_api_url_present": True}

    def preflight(proxy_url, **kwargs):
        preflighted.append((proxy_url, kwargs.get("email")))
        if "bad-batch-proxy" in proxy_url:
            return False, "auth_api HTTP 403; html_challenge"
        return True, "auth_api HTTP 200"

    def fake_run(email, acc, **kwargs):
        captured.append((email, acc, kwargs))
        return {"email": email, "plan": "plus"}

    routes, _accounts = _routes(
        started,
        accounts=rows,
        build_oauth_proxy_selector=build_selector,
        preflight_oauth_proxy_url=preflight,
        run_account_codex_login_once=fake_run,
    )
    routes["post_accounts_login_batch"](
        AccountEmailBatchParams(
            emails=["first@example.com"],
            proxy_api_provider="cliproxy",
            proxy_api_url="https://proxy-api.example/get",
            proxy_api_country="GB",
        )
    )

    result = started[0]["func"]("task-batch")
    assert result["total"] == 1
    assert result["ok"][0]["email"] == "first@example.com"
    assert selector_calls[0]["proxy_api_country"] == "GB"
    assert preflighted == [
        ("socks5h://bad-batch-proxy.example:1000", "first@example.com"),
        ("socks5h://good-batch-proxy.example:1001", "first@example.com"),
    ]
    assert captured[0][2]["proxy_url"] == "socks5h://good-batch-proxy.example:1001"


def test_post_account_login_bind_phone_disables_bind_email(monkeypatch):
    started = []
    account = {"email": "first@example.com"}
    captured = {}
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda _accounts, email: account if email == "first@example.com" else None)

    def fake_run(email, acc, **kwargs):
        captured.update({"email": email, "acc": acc, "kwargs": kwargs})
        return {"email": email, "plan": "plus"}

    routes, _accounts = _routes(started, accounts=[account], run_account_codex_login_once=fake_run)
    routes["post_account_login"](LoginAccountParams(email="first@example.com", bind_phone=True))

    started[0]["func"]("task-1")
    assert captured["kwargs"]["bind_phone"] is True
    assert captured["kwargs"]["bind_email"] is False


def test_post_account_login_passes_proxy_api_country(monkeypatch):
    started = []
    account = {"email": "first@example.com"}
    selector_calls = []
    captured = {}
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda _accounts, email: account if email == "first@example.com" else None)

    def build_selector(**kwargs):
        selector_calls.append(kwargs)
        return (lambda: "socks5h://proxy.example:1000"), {"proxy_api_provider": kwargs.get("proxy_api_provider")}

    def fake_run(email, acc, **kwargs):
        captured.update({"email": email, "acc": acc, "kwargs": kwargs})
        return {"email": email, "plan": "plus"}

    routes, _accounts = _routes(
        started,
        accounts=[account],
        build_oauth_proxy_selector=build_selector,
        run_account_codex_login_once=fake_run,
    )
    routes["post_account_login"](
        LoginAccountParams(
            email="first@example.com",
            proxy_api_provider="cliproxy",
            proxy_api_url="https://proxy-api.example/get",
            proxy_api_country="GB",
        )
    )

    started[0]["func"]("task-1")
    assert selector_calls[0]["proxy_api_country"] == "GB"
    assert captured["kwargs"]["proxy_url"] == "socks5h://proxy.example:1000"


def test_post_account_login_retries_oauth_proxy_api_until_preflight_passes(monkeypatch):
    started = []
    account = {"email": "first@example.com"}
    selector_calls = []
    preflighted = []
    captured = {}
    proxies = ["socks5h://bad-proxy.example:1000", "socks5h://good-proxy.example:1001"]
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda _accounts, email: account if email == "first@example.com" else None)

    def build_selector(**kwargs):
        selector_calls.append(kwargs)

        def selector():
            return proxies.pop(0)

        return selector, {"proxy_api_provider": kwargs.get("proxy_api_provider"), "proxy_api_url_present": True}

    def preflight(proxy_url, **kwargs):
        preflighted.append((proxy_url, kwargs.get("email")))
        if "bad-proxy" in proxy_url:
            return False, "auth_api HTTP 403; html_challenge"
        return True, "auth_api HTTP 200"

    def fake_run(email, acc, **kwargs):
        captured.update({"email": email, "acc": acc, "kwargs": kwargs})
        return {"email": email, "plan": "plus"}

    routes, _accounts = _routes(
        started,
        accounts=[account],
        build_oauth_proxy_selector=build_selector,
        preflight_oauth_proxy_url=preflight,
        run_account_codex_login_once=fake_run,
    )
    routes["post_account_login"](
        LoginAccountParams(
            email="first@example.com",
            proxy_api_provider="cliproxy",
            proxy_api_url="https://proxy-api.example/get",
            proxy_api_country="GB",
        )
    )

    started[0]["func"]("task-1")
    assert selector_calls[0]["proxy_api_country"] == "GB"
    assert preflighted == [
        ("socks5h://bad-proxy.example:1000", "first@example.com"),
        ("socks5h://good-proxy.example:1001", "first@example.com"),
    ]
    assert captured["kwargs"]["proxy_url"] == "socks5h://good-proxy.example:1001"


def test_post_account_login_raises_when_all_oauth_proxy_preflights_fail(monkeypatch):
    started = []
    account = {"email": "first@example.com"}
    proxies = ["socks5h://bad-proxy.example:1000", "socks5h://bad-proxy.example:1001"]
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda _accounts, email: account if email == "first@example.com" else None)

    def build_selector(**_kwargs):
        def selector():
            return proxies.pop(0)

        return selector, {"proxy_api_provider": "cliproxy", "proxy_api_url_present": True}

    def preflight(_proxy_url, **_kwargs):
        return False, "auth_api HTTP 403; html_challenge"

    routes, _accounts = _routes(
        started,
        accounts=[account],
        build_oauth_proxy_selector=build_selector,
        preflight_oauth_proxy_url=preflight,
        run_account_codex_login_once=lambda *_args, **_kwargs: pytest.fail("login should not run when preflight fails"),
    )
    routes["post_account_login"](
        LoginAccountParams(
            email="first@example.com",
            proxy_api_provider="cliproxy",
            proxy_api_url="https://proxy-api.example/get",
            proxy_api_country="GB",
        )
    )

    with pytest.raises(RuntimeError, match="OAuth 代理预检失败"):
        started[0]["func"]("task-1")


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


def test_post_accounts_login_batch_aborts_after_consecutive_similar_phone_fraud_guard(monkeypatch):
    started = []
    rows = [
        {"email": "first@example.com"},
        {"email": "second@example.com"},
        {"email": "third@example.com"},
    ]
    calls = []
    monkeypatch.setenv("CODEX_OAUTH_BATCH_CONCURRENCY", "1")
    monkeypatch.delenv("CODEX_OAUTH_FRAUD_GUARD_ABORT_THRESHOLD", raising=False)
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: rows)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda accounts, email: next((account for account in accounts if account["email"] == email), None),
    )

    def fake_run(email, _acc, **_kwargs):
        from autotoken.auth.codex_auth import CodexOAuthPhoneRateLimited

        calls.append(email)
        raise CodexOAuthPhoneRateLimited(
            "add-phone/send 失败: 400: fraud_guard: We've detected suspicious behavior "
            "from phone numbers similar to yours. Please try again later"
        )

    routes, _accounts = _routes(started, accounts=rows, run_account_codex_login_once=fake_run)
    routes["post_accounts_login_batch"](AccountEmailBatchParams(emails=[row["email"] for row in rows]))

    result = started[0]["func"]("task-batch")

    assert calls == ["first@example.com", "second@example.com"]
    assert result["aborted"] is True
    assert result["abort_reason"].startswith("连续 2 个账号命中 OpenAI fraud_guard")
    assert [item["email"] for item in result["failed"]] == ["first@example.com", "second@example.com"]
    assert result["skipped"] == [{"email": "third@example.com", "reason": result["abort_reason"]}]


def test_post_accounts_login_batch_aborts_when_fraud_guard_is_wrapped_as_generic_failure(monkeypatch):
    started = []
    rows = [
        {"email": "first@example.com"},
        {"email": "second@example.com"},
        {"email": "third@example.com"},
    ]
    calls = []
    monkeypatch.setenv("CODEX_OAUTH_BATCH_CONCURRENCY", "1")
    monkeypatch.delenv("CODEX_OAUTH_FRAUD_GUARD_ABORT_THRESHOLD", raising=False)
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: rows)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda accounts, email: next((account for account in accounts if account["email"] == email), None),
    )

    def fake_run(email, _acc, **_kwargs):
        calls.append(email)
        raise RuntimeError(
            "协议登录完成但未生成 CPA OAuth bundle; Codex OAuth 失败原因: "
            "add-phone/send 失败: 400: fraud_guard: We've detected suspicious behavior "
            "from phone numbers similar to yours. Please try again later"
        )

    routes, _accounts = _routes(started, accounts=rows, run_account_codex_login_once=fake_run)
    routes["post_accounts_login_batch"](AccountEmailBatchParams(emails=[row["email"] for row in rows]))

    result = started[0]["func"]("task-batch")

    assert calls == ["first@example.com", "second@example.com"]
    assert result["aborted"] is True
    assert result["skipped"] == [{"email": "third@example.com", "reason": result["abort_reason"]}]


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


def test_post_accounts_login_batch_mailcom_failure_updates_mail_pool(monkeypatch):
    started = []
    rows = [{"email": "first@mail.com", "cloudmail_account_id": "first@mail.com", "mail_provider": "mail.com"}]
    captured = []
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: rows)
    monkeypatch.setattr("autotoken.accounts.find_account", lambda _accounts, email: rows[0] if email == "first@mail.com" else None)
    monkeypatch.setattr(
        "autotoken.storage.mail_accounts.mark_mailcom_login_failure",
        lambda email, error, **_kwargs: captured.append((email, error)),
    )

    def failing_run(_email, _acc, **_kwargs):
        raise RuntimeError("protocol login failed")

    routes, _accounts = _routes(started, accounts=rows, run_account_codex_login_once=failing_run)
    routes["post_accounts_login_batch"](
        AccountEmailBatchParams(
            emails=["first@mail.com"],
            mail_provider="mail.com",
            protocol_only=True,
            bind_email=False,
        )
    )

    result = started[0]["func"]("task-batch")

    assert result["total"] == 1
    assert result["failed"] == [{"email": "first@mail.com", "error": "protocol login failed"}]
    assert captured == [("first@mail.com", "protocol login failed")]


def test_post_accounts_login_batch_mailcom_success_syncs_refresh_token_from_auth_file(monkeypatch, tmp_path):
    started = []
    auth_file = tmp_path / "codex-first.json"
    auth_file.write_text(json.dumps({"refresh_token": "rt-login-new"}), encoding="utf-8")
    rows = [
        {
            "email": "first@mail.com",
            "password": "gpt-pass",
            "cloudmail_account_id": "first@mail.com",
            "mail_provider": "mail.com",
        }
    ]
    captured = []
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: rows)
    monkeypatch.setattr("autotoken.accounts.find_account", lambda _accounts, email: rows[0] if email == "first@mail.com" else None)
    monkeypatch.setattr(
        "autotoken.storage.mail_accounts.mark_mailcom_registered",
        lambda email, **kwargs: captured.append((email, kwargs)) or {"email": email},
    )

    def successful_run(email, _acc, **_kwargs):
        return {"email": email, "plan": "free", "auth_file": str(auth_file)}

    routes, _accounts = _routes(started, accounts=rows, run_account_codex_login_once=successful_run)
    routes["post_accounts_login_batch"](
        AccountEmailBatchParams(
            emails=["first@mail.com"],
            mail_provider="mail.com",
            protocol_only=True,
            bind_email=False,
        )
    )

    result = started[0]["func"]("task-batch")

    assert result["total"] == 1
    assert result["ok"] == [{"email": "first@mail.com", "plan": "free", "auth_file": str(auth_file)}]
    assert captured == [
        (
            "first@mail.com",
            {
                "gpt_password": "gpt-pass",
                "refresh_token": "rt-login-new",
                "source": "account_login_success",
            },
        )
    ]


def test_post_accounts_login_batch_non_mailcom_failure_does_not_update_mail_pool(monkeypatch):
    started = []
    rows = [{"email": "first@example.com", "cloudmail_account_id": "first@example.com", "mail_provider": "cloud-mail"}]
    captured = []
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: rows)
    monkeypatch.setattr(
        "autotoken.accounts.find_account",
        lambda _accounts, email: rows[0] if email == "first@example.com" else None,
    )
    monkeypatch.setattr(
        "autotoken.storage.mail_accounts.mark_mailcom_login_failure",
        lambda email, error, **_kwargs: captured.append((email, error)),
    )

    def failing_run(_email, _acc, **_kwargs):
        raise RuntimeError("protocol login failed")

    routes, _accounts = _routes(started, accounts=rows, run_account_codex_login_once=failing_run)
    routes["post_accounts_login_batch"](
        AccountEmailBatchParams(
            emails=["first@example.com"],
            mail_provider="cloud-mail",
            protocol_only=True,
            bind_email=False,
        )
    )

    result = started[0]["func"]("task-batch")

    assert result["total"] == 1
    assert result["failed"] == [{"email": "first@example.com", "error": "protocol login failed"}]
    assert captured == []


def test_post_mail_accounts_login_auth_session_uses_plain_chatgpt_login_not_oauth(monkeypatch):
    started = []
    captured = []

    def forbidden_oauth_login(*_args, **_kwargs):
        raise AssertionError("mail邮箱管理登录不能走 OAuth 补登录")

    monkeypatch.setattr(
        "autotoken.services.mailcom_auth_session.login_mailcom_auth_session_once",
        lambda email, **kwargs: captured.append((email, kwargs)) or {"email": email, "status": "success"},
    )

    routes, _accounts = _routes(started, run_account_codex_login_once=forbidden_oauth_login)
    result = routes["post_mail_accounts_login_auth_session"](
        MailAccountAuthSessionBatchParams(emails=["Finished@mail.com"])
    )
    task_result = started[0]["func"]("task-auth-session")

    assert result["command"] == "mail-auth-session"
    assert task_result["ok"] == [{"email": "finished@mail.com", "status": "success"}]
    assert task_result["failed"] == []
    assert captured == [("finished@mail.com", {"progress_callback": captured[0][1]["progress_callback"]})]


def test_single_account_login_passes_totp_secret_when_account_has_2fa(monkeypatch):
    started = []
    account = {"email": "totp@example.com", "password": "pw", "two_factor_enabled": True}
    captured = {}

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda _accounts, email: account if email == "totp@example.com" else None)

    def fake_run(email, acc, **kwargs):
        captured.update({"email": email, "acc": acc, "kwargs": kwargs})
        return {"status": "success"}

    routes, _accounts = _routes(started, accounts=[account], run_account_codex_login_once=fake_run)
    monkeypatch.setattr(
        "autotoken.storage.accounts.get_totp_credentials",
        lambda email: {"secret": ("GEZDGNBVGY3TQOJQ" + "GEZDGNBVGY3TQOJQ")} if email == "totp@example.com" else None,
    )

    response = routes["post_account_login"](LoginAccountParams(email="totp@example.com"))
    assert response["task_id"] == "task-1"
    assert started[0]["func"]("task-1") == {"status": "success"}
    assert captured["kwargs"]["totp_secret"] == ("GEZDGNBVGY3TQOJQ" + "GEZDGNBVGY3TQOJQ")
