import pytest
from fastapi import HTTPException

from autotoken.api_routes.bind_card_task import BindCardTaskParams, create_bind_card_task_router
from autotoken.services.task_runtime import TASK_GROUP_BIND_CARD


class _TaskResultError(RuntimeError):
    def __init__(self, message, *, task_result=None):
        super().__init__(message)
        self.task_result = task_result


def _logger():
    return type("Logger", (), {"exception": lambda *_args, **_kwargs: None})()


def _routes(started, *, progress=None, reusable=False):
    progress = progress if progress is not None else []

    def start_task(command, func, params, *args, **kwargs):
        started.append({"command": command, "func": func, "params": params, "args": args, "kwargs": kwargs})
        return {"task_id": "task-1", "command": command, "params": params}

    router = create_bind_card_task_router(
        start_task=start_task,
        normalize_email=lambda value: str(value or "").strip().lower(),
        resolve_status_auth_file=lambda account: account.get("auth_file"),
        session_only_account_stub=lambda email: {"email": email, "auth_file": f"session:{email}"},
        is_bind_card_reusable_result=lambda _result: reusable,
        current_task_id_for_group=lambda: "task-bind",
        append_task_progress=lambda task_id, item: progress.append({"task_id": task_id, **item}),
        task_result_error=_TaskResultError,
        task_group_bind_card=TASK_GROUP_BIND_CARD,
        logger=_logger(),
    )
    return {route.endpoint.__name__: route.endpoint for route in router.routes}


def test_post_bind_card_task_starts_task(monkeypatch):
    started = []
    account = {"email": "user@example.com", "auth_file": "auth.json"}
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda _accounts, email: account if email == "user@example.com" else None)
    monkeypatch.setattr("autotoken.card_pool.find_item", lambda pool_type, item_id: {"id": item_id, "status": "unused"})

    routes = _routes(started)
    result = routes["post_bind_card_task"](
        BindCardTaskParams(
            email=" USER@example.com ",
            card_item_id="card-1",
            checkout_url=" https://chatgpt.com/checkout/demo ",
            proxy_url="socks5://host:1080",
            proxy_label="res-us-01",
        )
    )

    assert result["command"] == "bind-card"
    assert started[0]["kwargs"]["task_group"] == TASK_GROUP_BIND_CARD
    assert started[0]["params"]["email"] == " USER@example.com "
    assert started[0]["params"]["checkout_url"] == " https://chatgpt.com/checkout/demo "


def test_bind_card_task_run_updates_card_account_audit_and_progress(monkeypatch):
    started = []
    progress = []
    updated = []
    audits = []
    finalized = []
    bind_calls = []
    account = {"email": "user@example.com", "auth_file": "auth.json"}
    reserved = {"id": "card-1", "status": "binding"}

    monkeypatch.setattr("autotoken.cancel_signal.is_cancelled", lambda: False)
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda _accounts, email: account if email == "user@example.com" else None)
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **payload: updated.append((email, payload)))
    monkeypatch.setattr("autotoken.card_pool.find_item", lambda _pool_type, item_id: {"id": item_id, "status": "unused"})
    monkeypatch.setattr("autotoken.card_pool.reserve_card_item", lambda *args, **kwargs: reserved)

    def finalize_card_binding(*args, **kwargs):
        finalized.append({"args": args, "kwargs": kwargs})
        return {"id": "card-1", "status": "used"}

    monkeypatch.setattr("autotoken.card_pool.finalize_card_binding", finalize_card_binding)
    monkeypatch.setattr(
        "autotoken.bind_executor.run_bind_task",
        lambda **kwargs: bind_calls.append(kwargs)
        or {"status": "success", "message": "ok", "screenshot_paths": ["shot.png"]},
    )
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda item: audits.append(item))

    routes = _routes(started, progress=progress, reusable=True)
    routes["post_bind_card_task"](
        BindCardTaskParams(
            email="user@example.com",
            card_item_id="card-1",
            checkout_url="https://chatgpt.com/checkout/demo",
            roxybrowser_workspace_id="workspace-1",
            roxybrowser_profile_id="profile-1",
            roxybrowser_auto_create_profile=True,
        )
    )
    result = started[0]["func"]()

    assert result["status"] == "success"
    assert result["task_status"] == "completed"
    assert result["card_status"] == "used"
    assert finalized[0]["kwargs"]["reusable"] is True
    assert bind_calls[0]["email"] == "user@example.com"
    assert bind_calls[0]["use_roxybrowser"] is True
    assert bind_calls[0]["roxybrowser_workspace_id"] == "workspace-1"
    assert bind_calls[0]["roxybrowser_profile_id"] == "profile-1"
    assert bind_calls[0]["roxybrowser_auto_create_profile"] is True
    assert bind_calls[0].get("payment_flow") is None
    assert updated[0][0] == "user@example.com"
    assert updated[0][1]["last_bind_provider"] == "card"
    assert audits[0]["task_id"] == "task-bind"
    assert [item["stage"] for item in progress] == ["binding", "completed"]


def test_bind_card_task_protocol_flow_uses_protocol_executor(monkeypatch):
    started = []
    progress = []
    account = {"email": "user@example.com", "auth_file": "auth.json"}
    reserved = {"id": "card-1", "status": "binding"}
    browser_calls = []
    protocol_calls = []

    monkeypatch.setattr("autotoken.cancel_signal.is_cancelled", lambda: False)
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda _accounts, email: account if email == "user@example.com" else None)
    monkeypatch.setattr("autotoken.accounts.update_account", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("autotoken.card_pool.find_item", lambda _pool_type, item_id: {"id": item_id, "status": "unused"})
    monkeypatch.setattr("autotoken.card_pool.reserve_card_item", lambda *args, **kwargs: reserved)
    monkeypatch.setattr("autotoken.card_pool.finalize_card_binding", lambda *args, **kwargs: {"id": "card-1", "status": "used"})
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda _item: None)
    monkeypatch.setattr("autotoken.bind_executor.run_bind_task", lambda **kwargs: browser_calls.append(kwargs))
    monkeypatch.setattr(
        "autotoken.protocol_card_executor.run_protocol_card_bind_task",
        lambda **kwargs: protocol_calls.append(kwargs)
        or {"status": "success", "message": "protocol ok", "screenshot_paths": []},
    )

    routes = _routes(started, progress=progress)
    routes["post_bind_card_task"](
        BindCardTaskParams(
            email="user@example.com",
            card_item_id="card-1",
            checkout_url="https://chatgpt.com/checkout/openai_llc/cs_test",
            payment_flow="protocol",
        )
    )
    result = started[0]["func"]()

    assert result["status"] == "success"
    assert browser_calls == []
    assert protocol_calls[0]["email"] == "user@example.com"
    assert protocol_calls[0]["checkout_url"] == "https://chatgpt.com/checkout/openai_llc/cs_test"
    assert protocol_calls[0]["card_item"] is reserved
    assert protocol_calls[0]["timeout_seconds"] == 900
    assert [item["stage"] for item in progress] == ["binding", "completed"]


def test_bind_card_task_protocol_flow_allows_backend_checkout_generation(monkeypatch):
    started = []
    progress = []
    account = {"email": "user@example.com", "auth_file": "auth.json"}
    reserved = {"id": "card-1", "status": "binding"}
    protocol_calls = []
    reserved_calls = []

    monkeypatch.setattr("autotoken.cancel_signal.is_cancelled", lambda: False)
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda _accounts, email: account if email == "user@example.com" else None)
    monkeypatch.setattr("autotoken.accounts.update_account", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("autotoken.card_pool.find_item", lambda _pool_type, item_id: {"id": item_id, "status": "unused"})

    def reserve_card_item(*args, **kwargs):
        reserved_calls.append({"args": args, "kwargs": kwargs})
        return reserved

    monkeypatch.setattr("autotoken.card_pool.reserve_card_item", reserve_card_item)
    monkeypatch.setattr("autotoken.card_pool.finalize_card_binding", lambda *args, **kwargs: {"id": "card-1", "status": "used"})
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda _item: None)
    monkeypatch.setattr(
        "autotoken.protocol_card_executor.run_protocol_card_bind_task",
        lambda **kwargs: protocol_calls.append(kwargs)
        or {
            "status": "success",
            "message": "protocol ok",
            "screenshot_paths": [],
            "checkout_url": "https://chatgpt.com/checkout/openai_llc/oaics_generated",
        },
    )

    routes = _routes(started, progress=progress)
    routes["post_bind_card_task"](
        BindCardTaskParams(
            email="user@example.com",
            card_item_id="card-1",
            checkout_url="",
            payment_flow="protocol",
            bind_link_payload={
                "billing_details": {"country": "PH", "currency": "PHP"},
                "checkout_ui_mode": "hosted",
                "plan_name": "chatgptprolite",
            },
        )
    )
    result = started[0]["func"]()

    assert result["status"] == "success"
    assert reserved_calls[0]["kwargs"]["checkout_url"] == "<protocol-auto-generate>"
    assert protocol_calls[0]["checkout_url"] == ""
    assert protocol_calls[0]["checkout_payload"]["plan_name"] == "chatgptprolite"
    assert result["checkout_url"] == "https://chatgpt.com/checkout/openai_llc/oaics_generated"
    assert [item["stage"] for item in progress] == ["binding", "completed"]


def test_bind_card_task_fetches_cliproxy_proxy_per_task(monkeypatch):
    started = []
    progress = []
    bind_calls = []
    fetched = []
    account = {"email": "user@example.com", "auth_file": "auth.json"}
    reserved = {"id": "card-1", "status": "binding"}

    monkeypatch.setattr("autotoken.cancel_signal.is_cancelled", lambda: False)
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda _accounts, email: account if email == "user@example.com" else None)
    monkeypatch.setattr("autotoken.accounts.update_account", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("autotoken.card_pool.find_item", lambda _pool_type, item_id: {"id": item_id, "status": "unused"})
    monkeypatch.setattr("autotoken.card_pool.reserve_card_item", lambda *args, **kwargs: reserved)
    monkeypatch.setattr("autotoken.card_pool.finalize_card_binding", lambda *args, **kwargs: {"id": "card-1", "status": "used"})
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda _item: None)

    def fake_fetch(api_url, *, default_auth_scheme, provider):
        fetched.append((api_url, default_auth_scheme, provider))
        return "socks5h://user:pass@cliproxy.example:3010"

    monkeypatch.setattr("autotoken.services.proxy_runtime.fetch_proxy_from_api_url", fake_fetch)
    monkeypatch.setattr("autotoken.services.proxy_runtime.preflight_payment_proxy_url", lambda proxy_url: (True, "ok"))
    monkeypatch.setattr(
        "autotoken.bind_executor.run_bind_task",
        lambda **kwargs: bind_calls.append(kwargs) or {"status": "success", "message": "ok", "screenshot_paths": []},
    )

    routes = _routes(started, progress=progress)
    routes["post_bind_card_task"](
        BindCardTaskParams(
            email="user@example.com",
            card_item_id="card-1",
            checkout_url="https://chatgpt.com/checkout/demo",
            proxy_api_provider="cliproxy",
            proxy_api_country="JP",
        )
    )
    result = started[0]["func"]()

    assert result["status"] == "success"
    assert fetched == [
        (
            "https://api.cliproxy.io/white/api?region=JP&num=1&time=30&format=n&type=json",
            "socks5h",
            "cliproxy",
        )
    ]
    assert bind_calls[0]["proxy_url"] == "socks5h://user:pass@cliproxy.example:3010"
    assert [item["stage"] for item in progress] == ["bind_proxy_api_selected", "binding", "completed"]


def test_bind_card_task_retries_proxy_api_until_preflight_passes(monkeypatch):
    started = []
    progress = []
    bind_calls = []
    reserved_calls = []
    account = {"email": "user@example.com", "auth_file": "auth.json"}
    reserved = {"id": "card-1", "status": "binding"}
    proxies = ["socks5h://bad-proxy.example:3010", "socks5h://good-proxy.example:3011"]

    monkeypatch.setenv("AUTOTOKEN_BIND_PROXY_PREFLIGHT_ATTEMPTS", "2")
    monkeypatch.setattr("autotoken.cancel_signal.is_cancelled", lambda: False)
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda _accounts, email: account if email == "user@example.com" else None)
    monkeypatch.setattr("autotoken.accounts.update_account", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("autotoken.card_pool.find_item", lambda _pool_type, item_id: {"id": item_id, "status": "unused"})

    def reserve_card_item(*args, **kwargs):
        reserved_calls.append({"args": args, "kwargs": kwargs})
        return reserved

    monkeypatch.setattr("autotoken.card_pool.reserve_card_item", reserve_card_item)
    monkeypatch.setattr("autotoken.card_pool.finalize_card_binding", lambda *args, **kwargs: {"id": "card-1", "status": "used"})
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda _item: None)
    monkeypatch.setattr(
        "autotoken.services.proxy_runtime.fetch_proxy_from_api_url",
        lambda *_args, **_kwargs: proxies.pop(0),
    )

    preflighted = []

    def preflight(proxy_url):
        preflighted.append(proxy_url)
        return (proxy_url.startswith("socks5h://good-"), "tls ok" if "good" in proxy_url else "tls failed")

    monkeypatch.setattr("autotoken.services.proxy_runtime.preflight_payment_proxy_url", preflight)
    monkeypatch.setattr(
        "autotoken.bind_executor.run_bind_task",
        lambda **kwargs: bind_calls.append(kwargs) or {"status": "success", "message": "ok", "screenshot_paths": []},
    )

    routes = _routes(started, progress=progress)
    routes["post_bind_card_task"](
        BindCardTaskParams(
            email="user@example.com",
            card_item_id="card-1",
            checkout_url="https://chatgpt.com/checkout/demo",
            proxy_api_provider="cliproxy",
            proxy_api_country="US",
        )
    )
    result = started[0]["func"]()

    assert result["status"] == "success"
    assert preflighted == ["socks5h://bad-proxy.example:3010", "socks5h://good-proxy.example:3011"]
    assert reserved_calls
    assert bind_calls[0]["proxy_url"] == "socks5h://good-proxy.example:3011"
    assert [item["stage"] for item in progress] == [
        "bind_proxy_preflight_failed",
        "bind_proxy_api_selected",
        "binding",
        "completed",
    ]


def test_bind_card_task_does_not_reserve_card_when_all_proxy_preflights_fail(monkeypatch):
    started = []
    progress = []
    reserved_calls = []
    account = {"email": "user@example.com", "auth_file": "auth.json"}

    monkeypatch.setenv("AUTOTOKEN_BIND_PROXY_PREFLIGHT_ATTEMPTS", "2")
    monkeypatch.setattr("autotoken.cancel_signal.is_cancelled", lambda: False)
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda _accounts, email: account if email == "user@example.com" else None)
    monkeypatch.setattr("autotoken.accounts.update_account", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("autotoken.card_pool.find_item", lambda _pool_type, item_id: {"id": item_id, "status": "unused"})
    monkeypatch.setattr("autotoken.card_pool.reserve_card_item", lambda *args, **kwargs: reserved_calls.append(kwargs))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda _item: None)
    monkeypatch.setattr(
        "autotoken.services.proxy_runtime.fetch_proxy_from_api_url",
        lambda *_args, **_kwargs: "socks5h://bad-proxy.example:3010",
    )
    monkeypatch.setattr("autotoken.services.proxy_runtime.preflight_payment_proxy_url", lambda _proxy: (False, "tls failed"))

    routes = _routes(started, progress=progress)
    routes["post_bind_card_task"](
        BindCardTaskParams(
            email="user@example.com",
            card_item_id="card-1",
            checkout_url="https://chatgpt.com/checkout/demo",
            proxy_api_provider="cliproxy",
            proxy_api_country="US",
        )
    )
    with pytest.raises(_TaskResultError) as exc_info:
        started[0]["func"]()
    result = exc_info.value.task_result

    assert result["status"] == "failed"
    assert result["failure_stage"] == "proxy_preflight"
    assert reserved_calls == []
    assert [item["stage"] for item in progress] == [
        "bind_proxy_preflight_failed",
        "bind_proxy_preflight_failed",
        "completed",
    ]


def test_bind_card_task_retries_when_proxy_api_fetch_fails(monkeypatch):
    started = []
    progress = []
    bind_calls = []
    account = {"email": "user@example.com", "auth_file": "auth.json"}
    reserved = {"id": "card-1", "status": "binding"}
    attempts = []

    monkeypatch.setenv("AUTOTOKEN_BIND_PROXY_PREFLIGHT_ATTEMPTS", "2")
    monkeypatch.setattr("autotoken.cancel_signal.is_cancelled", lambda: False)
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda _accounts, email: account if email == "user@example.com" else None)
    monkeypatch.setattr("autotoken.accounts.update_account", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("autotoken.card_pool.find_item", lambda _pool_type, item_id: {"id": item_id, "status": "unused"})
    monkeypatch.setattr("autotoken.card_pool.reserve_card_item", lambda *args, **kwargs: reserved)
    monkeypatch.setattr("autotoken.card_pool.finalize_card_binding", lambda *args, **kwargs: {"id": "card-1", "status": "used"})
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda _item: None)

    def fetch_proxy(*_args, **_kwargs):
        attempts.append("fetch")
        if len(attempts) == 1:
            raise RuntimeError("api timeout")
        return "socks5h://good-proxy.example:3011"

    monkeypatch.setattr("autotoken.services.proxy_runtime.fetch_proxy_from_api_url", fetch_proxy)
    monkeypatch.setattr("autotoken.services.proxy_runtime.preflight_payment_proxy_url", lambda _proxy: (True, "tls ok"))
    monkeypatch.setattr(
        "autotoken.bind_executor.run_bind_task",
        lambda **kwargs: bind_calls.append(kwargs) or {"status": "success", "message": "ok", "screenshot_paths": []},
    )

    routes = _routes(started, progress=progress)
    routes["post_bind_card_task"](
        BindCardTaskParams(
            email="user@example.com",
            card_item_id="card-1",
            checkout_url="https://chatgpt.com/checkout/demo",
            proxy_api_provider="cliproxy",
            proxy_api_country="US",
        )
    )
    result = started[0]["func"]()

    assert result["status"] == "success"
    assert len(attempts) == 2
    assert bind_calls[0]["proxy_url"] == "socks5h://good-proxy.example:3011"
    assert [item["stage"] for item in progress] == [
        "bind_proxy_preflight_failed",
        "bind_proxy_api_selected",
        "binding",
        "completed",
    ]


def test_bind_card_task_preflights_static_proxy_before_reserving_card(monkeypatch):
    started = []
    progress = []
    reserved_calls = []
    account = {"email": "user@example.com", "auth_file": "auth.json"}

    monkeypatch.setattr("autotoken.cancel_signal.is_cancelled", lambda: False)
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda _accounts, email: account if email == "user@example.com" else None)
    monkeypatch.setattr("autotoken.accounts.update_account", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("autotoken.card_pool.find_item", lambda _pool_type, item_id: {"id": item_id, "status": "unused"})
    monkeypatch.setattr("autotoken.card_pool.reserve_card_item", lambda *args, **kwargs: reserved_calls.append(kwargs))
    monkeypatch.setattr("autotoken.bind_audit.record_bind_audit", lambda _item: None)
    monkeypatch.setattr("autotoken.services.proxy_runtime.preflight_payment_proxy_url", lambda _proxy: (False, "connection refused"))

    routes = _routes(started, progress=progress)
    routes["post_bind_card_task"](
        BindCardTaskParams(
            email="user@example.com",
            card_item_id="card-1",
            checkout_url="https://chatgpt.com/checkout/demo",
            proxy_url="socks5h://bad-proxy.example:3010",
        )
    )
    with pytest.raises(_TaskResultError) as exc_info:
        started[0]["func"]()
    result = exc_info.value.task_result

    assert result["status"] == "failed"
    assert result["failure_stage"] == "proxy_preflight"
    assert reserved_calls == []
    assert [item["stage"] for item in progress] == ["bind_proxy_preflight_failed", "completed"]


def test_bind_card_task_rejects_missing_checkout_url(monkeypatch):
    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [])

    routes = _routes([])
    with pytest.raises(HTTPException) as exc_info:
        routes["post_bind_card_task"](BindCardTaskParams(email="user@example.com", card_item_id="card-1", checkout_url=" "))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "checkout_url 不能为空"
