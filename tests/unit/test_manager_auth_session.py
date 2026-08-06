import os
import threading
import time

from autotoken import accounts, manager


class FakeRequest:
    url = "https://chatgpt.com/backend-api/sentinel/req"
    post_data = '{"flow":"chatgpt_checkout"}'
    headers = {
        "user-agent": "Mozilla/5.0 Test",
        "accept-language": "en-US,en;q=0.9",
        "oai-language": "en-US",
        "oai-device-id": "device-123",
        "oai-client-version": "web-test",
        "oai-client-build-number": "456",
        "openai-sentinel-token": "request-token",
        "content-type": "text/plain;charset=UTF-8",
        "origin": "https://chatgpt.com",
        "referer": "https://chatgpt.com/backend-api/sentinel/frame.html",
    }


class FakeResponse:
    url = "https://chatgpt.com/backend-api/sentinel/req"
    status = 200

    def json(self):
        return {"token": "response-token"}


def test_protocol_register_does_not_record_account_when_auth_session_save_fails(monkeypatch):
    events = []

    class FakeMailClient:
        provider_name = "outlook"

        def create_registration_email(self, prefix=None, domain=None):
            return "mailbox-1", "half-finished@example.com"

        def delete_account(self, account_id):
            events.append(("delete_mailbox", account_id))
            return {"code": 0}

    def fake_register_once(*args, **kwargs):
        return True, {
            "data": {
                "sessionToken": "session-token",
                "accessToken": "access-token",
            }
        }

    monkeypatch.setattr("autotoken.auth.protocol_register.register_once", fake_register_once)
    monkeypatch.setattr(manager, "_save_auth_from_session_page", lambda *args, **kwargs: None)
    monkeypatch.setattr(manager, "add_account", lambda *args, **kwargs: events.append(("add_account", args, kwargs)))
    monkeypatch.setattr(manager, "record_failure", lambda *args, **kwargs: events.append(("failure", args, kwargs)))
    monkeypatch.setattr(manager.registration, "replace_direct_registration_outcome", lambda *args, **kwargs: None)
    monkeypatch.setattr(manager, "_sync_provider_registered_email", lambda *args, **kwargs: None)

    result = manager.create_account_direct(
        FakeMailClient(),
        password="pw",
        check_team_membership=False,
        register_mode="protocol",
    )

    assert result is None
    assert not any(event[0] == "add_account" for event in events)
    assert any(event[0] == "failure" and event[1][1] == "auth_session_missing" for event in events)


class FakeContext:
    def cookies(self, url):
        assert url == "https://chatgpt.com"
        return [
            {"name": "oai-did", "value": "device-cookie"},
            {"name": "__Secure-next-auth.session-token", "value": "session-cookie"},
        ]


class FakeAuthSessionPage:
    url = "https://chatgpt.com/"

    def __init__(self, responses):
        self.responses = list(responses)
        self.auth_fetch_count = 0
        self.goto_urls = []
        self.load_state_waits = []

    def evaluate(self, script):
        if "api/auth/session" in script:
            self.auth_fetch_count += 1
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        return {
            "user_agent": "Mozilla/5.0 Test",
            "accept_language": "en-US",
            "oai_language": "en-US",
        }

    def goto(self, url, **kwargs):
        self.goto_urls.append(url)
        self.url = url

    def wait_for_load_state(self, *args, **kwargs):
        self.load_state_waits.append((args, kwargs))


def test_temporary_mail_provider_serializes_environment_overrides(monkeypatch):
    monkeypatch.setenv("MAIL_PROVIDER", "cloudflare_temp_email")
    entered = threading.Event()
    release = threading.Event()
    events = []

    def first_worker():
        with manager._temporary_mail_provider("luckmail"):
            events.append(("first_enter", os.environ.get("MAIL_PROVIDER")))
            entered.set()
            release.wait(timeout=2)
            events.append(("first_exit", os.environ.get("MAIL_PROVIDER")))

    def second_worker():
        entered.wait(timeout=2)
        with manager._temporary_mail_provider("outlook"):
            events.append(("second_enter", os.environ.get("MAIL_PROVIDER")))

    first = threading.Thread(target=first_worker)
    second = threading.Thread(target=second_worker)
    first.start()
    assert entered.wait(timeout=2)
    second.start()
    time.sleep(0.05)

    assert events == [("first_enter", "luckmail")]

    release.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert events == [
        ("first_enter", "luckmail"),
        ("first_exit", "luckmail"),
        ("second_enter", "outlook"),
    ]


def test_auth_context_capture_saves_sentinel_metadata():
    state = manager._new_auth_context_capture_state()

    manager._capture_auth_context_request(FakeRequest(), state)
    manager._capture_auth_context_response(FakeResponse(), state)

    assert state["openai_sentinel_token"] == "response-token"
    assert state["device_id"] == "device-123"
    assert state["oai_client_version"] == "web-test"
    assert state["sentinel_url"] == "https://chatgpt.com/backend-api/sentinel/req"
    assert state["sentinel_body"] == '{"flow":"chatgpt_checkout"}'
    assert state["sentinel_headers"]["referer"] == "https://chatgpt.com/backend-api/sentinel/frame.html"


def test_merge_auth_session_context_keeps_session_and_adds_context():
    data = {"accessToken": "access"}

    manager._merge_auth_session_context(
        data,
        {
            "openai_sentinel_token": "sentinel",
            "oai_client_version": "web-test",
            "cookie_header": "__Secure-next-auth.session-token=session",
            "empty": "",
        },
    )

    assert data["accessToken"] == "access"
    assert data["openai_sentinel_token"] == "sentinel"
    assert data["oai_client_version"] == "web-test"
    assert data["cookie_header"] == "__Secure-next-auth.session-token=session"
    assert "empty" not in data


def test_wait_for_direct_register_step_dismisses_passkey_then_returns_allowed_step(monkeypatch):
    page = object()
    steps = iter(["passkey", "email"])
    sleeps = []
    dismiss_calls = []

    monkeypatch.setattr(manager, "_detect_direct_register_step", lambda _page: next(steps))
    monkeypatch.setattr(manager, "dismiss_passkey_prompt", lambda value: dismiss_calls.append(value) or True)
    monkeypatch.setattr(manager.time, "sleep", lambda seconds: sleeps.append(seconds))

    assert manager._wait_for_direct_register_step(page, {"email"}, timeout=5) == "email"
    assert dismiss_calls == [page]
    assert sleeps == [0.5]


def test_wait_for_direct_step_change_dismisses_passkey_then_returns_next_step(monkeypatch):
    page = object()
    steps = iter(["passkey", "password"])
    sleeps = []
    dismiss_calls = []

    monkeypatch.setattr(manager, "_detect_direct_register_step", lambda _page: next(steps))
    monkeypatch.setattr(manager, "dismiss_passkey_prompt", lambda value: dismiss_calls.append(value) or True)
    monkeypatch.setattr(manager.time, "sleep", lambda seconds: sleeps.append(seconds))

    assert manager._wait_for_direct_step_change(page, "passkey", timeout=5) == "password"
    assert dismiss_calls == [page]
    assert sleeps == [0.5]


def test_fetch_auth_session_retries_after_403_and_keeps_context():
    page = FakeAuthSessionPage(
        [
            {"status": 403, "data": {}, "raw": "<html>blocked</html>"},
            {
                "status": 200,
                "data": {"accessToken": "access", "accountId": "account"},
                "raw": '{"accessToken":"access"}',
            },
        ]
    )

    result = manager._fetch_auth_session_from_page(
        page,
        FakeContext(),
        {"openai_sentinel_token": "sentinel"},
        max_attempts=2,
        retry_delay_seconds=0,
    )

    assert result["status"] == 200
    assert result["data"]["accessToken"] == "access"
    assert result["auth_context"]["openai_sentinel_token"] == "sentinel"
    assert result["auth_context"]["device_id"] == "device-cookie"
    assert result["auth_context"]["cookie_header"] == "oai-did=device-cookie; __Secure-next-auth.session-token=session-cookie"
    assert page.auth_fetch_count == 2
    assert page.goto_urls == ["https://chatgpt.com/"]


def test_save_auth_from_session_page_rejects_session_without_account_context(monkeypatch):
    events = []

    monkeypatch.setattr(manager.registration, "replace_outcome", lambda *args, **kwargs: events.append(kwargs))
    monkeypatch.setattr(
        "autotoken.auth_session_store.save_auth_session",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not save incomplete session")),
    )
    monkeypatch.setattr(
        "autotoken.accounts.add_account",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not add incomplete account")),
    )

    result = manager._save_auth_from_session_page(
        "no-org@example.com",
        "pw",
        "mailbox-1",
        {"status": 200, "data": {"accessToken": "access-token", "sessionToken": "session-token"}},
    )

    assert result is None
    assert events[-1]["status"] == "session_auth_no_organization"


def test_save_auth_from_session_page_records_active_auth_session_account(monkeypatch):
    captured = {"add": [], "update": []}

    monkeypatch.setattr("autotoken.auth_session_store.save_auth_session", lambda email, data: f"data/auth_session/{email}.json")
    monkeypatch.setattr(
        "autotoken.accounts.add_account",
        lambda *args, **kwargs: captured["add"].append((args, kwargs)),
    )
    monkeypatch.setattr(
        "autotoken.accounts.update_account",
        lambda email, **kwargs: captured["update"].append((email, kwargs)) or {"email": email, **kwargs},
    )

    result = manager._save_auth_from_session_page(
        "user@example.com",
        "pw",
        "mail-1",
        {"status": 200, "data": {"accessToken": "access", "accountId": "account-id"}},
        mail_provider="outlook",
    )

    assert result["auth_file"] == "data/auth_session/user@example.com.json"
    assert captured["add"][0][0] == ("user@example.com", "pw")
    assert captured["update"][0][0] == "user@example.com"
    assert captured["update"][0][1]["status"] == accounts.STATUS_ACTIVE
    assert captured["update"][0][1]["auth_file"] is None
    assert captured["update"][0][1]["account_source"] == accounts.ACCOUNT_SOURCE_MANAGED


def test_phone_first_oauth_saves_auth_session_before_codex_bundle(monkeypatch):
    events = []

    class FakeMailClient:
        pass

    def fake_phone_first_register_once(*args, **kwargs):
        return True, {
            "status": 200,
            "data": {
                "accessToken": "chatgpt-access",
                "sessionToken": "chatgpt-session",
            },
            "mailbox_email": "phone-first@example.com",
            "mailbox_account_id": "mail-1",
            "codex_oauth_bundle": {
                "access_token": "codex-access",
                "refresh_token": "codex-refresh",
                "id_token": "codex-id",
            },
        }

    def fake_save_session(email, password, cloudmail_account_id, session_data, **kwargs):
        events.append(("session", email, cloudmail_account_id, session_data["data"]["sessionToken"]))
        return {"email": email, "auth_file": f"data/auth_session/{email}.json"}

    def fake_save_bundle(email, password, cloudmail_account_id, bundle, **kwargs):
        events.append(("bundle", email, cloudmail_account_id, kwargs.get("source")))
        return {"email": email, "auth_file": f"data/auths/codex-{email}-free.json", "source": kwargs.get("source")}

    monkeypatch.setattr("autotoken.protocol_register.phone_first_register_once", fake_phone_first_register_once)
    monkeypatch.setattr(manager, "_save_auth_from_session_page", fake_save_session)
    monkeypatch.setattr(manager, "_save_codex_oauth_bundle_for_account", fake_save_bundle)

    result = manager.create_account_direct(
        FakeMailClient(),
        password="pw",
        registration_flow="phone_cpa",
        post_register_oauth=True,
        oauth_phone_sms_provider="phone_pool",
    )

    assert result["source"] == "phone_first_protocol_oauth"
    assert events == [
        ("session", "phone-first@example.com", "mail-1", "chatgpt-session"),
        ("bundle", "phone-first@example.com", "mail-1", "phone_first_protocol_oauth"),
    ]


def test_phone_first_token_only_saves_bundle_without_refreshing_web_auth(monkeypatch):
    events = []

    class FakeMailClient:
        pass

    def fake_phone_first_register_once(*args, **kwargs):
        return True, {
            "status": 200,
            "data": {
                "accessToken": "chatgpt-access",
                "refreshToken": "chatgpt-refresh",
            },
            "mailbox_email": "phone-first@example.com",
            "mailbox_account_id": "mail-1",
            "codex_oauth_bundle": {
                "access_token": "codex-access",
                "refresh_token": "codex-refresh",
                "id_token": "codex-id",
            },
        }

    def fake_refresh(*args, **kwargs):
        raise AssertionError("phone-first 注册不应通过协议补登录刷新 auth_session")

    def fake_save_session(email, password, cloudmail_account_id, session_data, **kwargs):
        raise AssertionError("缺少 Web session 时不应保存 token-only auth_session")

    def fake_save_bundle(email, password, cloudmail_account_id, bundle, **kwargs):
        events.append(("bundle", email, cloudmail_account_id, kwargs.get("source")))
        return {"email": email, "auth_file": f"data/auths/codex-{email}-free.json", "source": kwargs.get("source")}

    monkeypatch.setattr("autotoken.protocol_register.phone_first_register_once", fake_phone_first_register_once)
    monkeypatch.setattr(manager, "_refresh_auth_session_via_protocol_login", fake_refresh)
    monkeypatch.setattr(manager, "_save_auth_from_session_page", fake_save_session)
    monkeypatch.setattr(manager, "_save_codex_oauth_bundle_for_account", fake_save_bundle)

    result = manager.create_account_direct(
        FakeMailClient(),
        password="pw",
        registration_flow="phone_cpa",
        post_register_oauth=True,
        oauth_phone_sms_provider="phone_pool",
    )

    assert result["source"] == "phone_first_protocol_oauth"
    assert events == [
        ("bundle", "phone-first@example.com", "mail-1", "phone_first_protocol_oauth"),
    ]


def test_standard_registration_uses_registration_specific_mailbox_creation(monkeypatch):
    calls = []

    class FakeMailClient:
        provider_name = "luckmail"

        def create_registration_email(self, prefix=None, domain=None):
            calls.append(("registration", prefix, domain))
            return "tok_fresh", "fresh@outlook.com"

        def create_temp_email(self, *args, **kwargs):
            raise AssertionError("注册账号不应复用已有邮箱池")

    monkeypatch.setattr(
        manager,
        "_register_direct_once",
        lambda *_args, **_kwargs: (
            True,
            {"status": 200, "data": {"accessToken": "access", "sessionToken": "session"}},
        ),
    )
    monkeypatch.setattr(
        manager,
        "_save_auth_from_session_page",
        lambda email, *_args, **_kwargs: {"email": email, "auth_file": "data/auth_session/fresh.json"},
    )

    result = manager.create_account_direct(
        FakeMailClient(),
        email_prefix="new",
        password="pw",
        domain="outlook.com",
        check_team_membership=False,
        post_register_oauth=False,
    )

    assert result["email"] == "fresh@outlook.com"
    assert len(calls) == 1
    assert calls[0][0] == "registration"
    assert str(calls[0][1]).startswith("new")
    assert calls[0][2] == "outlook.com"


def test_browser_register_uses_default_playwright_context_without_randomized_fingerprint(monkeypatch):
    calls = {"contexts": []}

    class FakePage:
        url = "about:blank"

        def on(self, *_args, **_kwargs):
            return None

        def goto(self, *_args, **_kwargs):
            raise RuntimeError("Timeout while opening signup")

    class FakeContext:
        def __init__(self, kwargs):
            self.kwargs = kwargs

        def new_page(self):
            return FakePage()

    class FakeBrowser:
        def new_context(self, **kwargs):
            calls["contexts"].append(kwargs)
            return FakeContext(kwargs)

        def close(self):
            return None

    class FakeChromium:
        def launch(self, **_kwargs):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: FakePlaywright())
    monkeypatch.setattr(manager, "get_playwright_launch_options", lambda **_kwargs: {})
    monkeypatch.setattr(manager.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "autotoken.browser_fingerprint.generate_fingerprint",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("direct register should not randomize fingerprint")),
    )

    try:
        manager._register_direct_once(None, "new@example.com", "pw")
    except RuntimeError as exc:
        assert "打开 ChatGPT 登录页失败" in str(exc)
    else:
        raise AssertionError("expected signup goto failure")

    assert calls["contexts"] == [
        {
            "viewport": {"width": 1280, "height": 800},
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
        }
    ]


def test_direct_about_you_accepts_korean_required_consents():
    class FakePage:
        def __init__(self):
            self.scripts = []

        def evaluate(self, script):
            self.scripts.append(script)
            return 4

    page = FakePage()

    assert manager._accept_direct_about_you_required_consents(page) == 4
    assert "필수" in page.scripts[0]
    assert "국외" in page.scripts[0]
    assert "민감" in page.scripts[0]
    assert "계정 생성 끝내기" in manager._DIRECT_ABOUT_YOU_BUTTON_TEXTS


def test_browser_register_uses_roxybrowser_cdp_and_reuses_idle_profiles(monkeypatch):
    calls = {"launches": [], "cdp": [], "closed": [], "deleted": [], "released": []}

    class FakePage:
        url = "about:blank"

        def on(self, *_args, **_kwargs):
            return None

        def goto(self, *_args, **_kwargs):
            raise RuntimeError("Timeout while opening signup")

    class FakeContext:
        pages = []

        def new_page(self):
            return FakePage()

    class FakeBrowser:
        contexts = [FakeContext()]

        def close(self):
            calls["closed"].append("browser")

    class FakeChromium:
        def launch(self, **_kwargs):
            raise AssertionError("RoxyBrowser 注册不应启动本地 Playwright Chromium")

        def connect_over_cdp(self, endpoint_url):
            calls["cdp"].append(endpoint_url)
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        def start(self):
            return self

        def stop(self):
            calls["closed"].append("playwright")

    class FakeRoxyClient:
        def __init__(self, api_host, api_token):
            calls["client"] = (api_host, api_token)

        def launch(self, **kwargs):
            calls["launches"].append(kwargs)
            return type(
                "Launch",
                (),
                {
                    "workspace_id": "workspace-1",
                    "dir_id": "dir-1",
                    "connection": {"http": "127.0.0.1:9222"},
                    "created_profile": True,
                },
            )()

        def browser_close(self, dir_id, **_kwargs):
            calls["closed"].append(dir_id)

        def browser_delete(self, workspace_id, dir_ids):
            calls["deleted"].append((workspace_id, dir_ids))

        def release_profile_reservation(self, dir_id):
            calls["released"].append(dir_id)

    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: FakePlaywright())
    monkeypatch.setattr("autotoken.settings.config.get_roxybrowser_config", lambda: {"api_host": "http://roxy", "api_token": "token"})
    monkeypatch.setattr("autotoken.roxybrowser_client.RoxyBrowserClient", FakeRoxyClient)
    monkeypatch.setattr(manager.time, "sleep", lambda _seconds: None)

    try:
        manager._register_direct_once(None, "roxy@example.com", "pw", proxy_url="http://proxy", use_roxybrowser=True)
    except RuntimeError as exc:
        assert "打开 ChatGPT 登录页失败" in str(exc)
    else:
        raise AssertionError("expected signup goto failure")

    assert calls["client"] == ("http://roxy", "token")
    assert calls["launches"][0]["proxy_url"] == "http://proxy"
    assert calls["launches"][0]["clear_profile_data"] is True
    assert calls["launches"][0]["force_new_profile"] is False
    assert calls["cdp"] == ["http://127.0.0.1:9222"]
    assert "dir-1" in calls["closed"]
    assert calls["deleted"] == [("workspace-1", ["dir-1"])]
    assert calls["released"] == ["dir-1"]


def test_session_data_keeps_chatgpt_access_separate_from_codex_bundle(monkeypatch):
    from autotoken.auth import protocol_register as protocol_register_module

    captured = {}

    class FakeResult:
        def to_dict(self):
            return {
                "email": "phone-first@example.com",
                "session_token": "chatgpt-session",
                "chatgpt_access_token": "chatgpt-access",
                "access_token": "codex-access",
                "refresh_token": "codex-refresh",
                "id_token": "codex-id",
                "cookie_header": "__Secure-next-auth.session-token=chatgpt-session",
            }

    def fake_build_bundle(token_response, fallback_email):
        captured["token_response"] = token_response
        captured["fallback_email"] = fallback_email
        return {"access_token": token_response["access_token"], "refresh_token": token_response["refresh_token"]}

    monkeypatch.setattr("autotoken.auth.codex_auth._build_bundle_from_token_response", fake_build_bundle)

    payload = protocol_register_module._session_data_from_auth_result(FakeResult())

    assert payload["data"]["accessToken"] == "chatgpt-access"
    assert payload["data"]["access_token"] == "chatgpt-access"
    assert payload["codex_oauth_bundle"]["access_token"] == "codex-access"
    assert captured["token_response"]["access_token"] == "codex-access"
    assert captured["fallback_email"] == "phone-first@example.com"


def test_session_data_preserves_chatgpt_account_metadata_in_codex_bundle(monkeypatch):
    from autotoken.auth import protocol_register as protocol_register_module

    class FakeResult:
        def to_dict(self):
            return {
                "email": "plus@example.com",
                "session_token": "chatgpt-session",
                "chatgpt_access_token": "chatgpt-access",
                "access_token": "codex-access",
                "refresh_token": "codex-refresh",
                "id_token": "codex-id",
                "account_id": "acct-plus",
                "plan_type": "plus",
            }

    monkeypatch.setattr(
        "autotoken.auth.codex_auth._build_bundle_from_token_response",
        lambda *_args, **_kwargs: {
            "email": "plus@example.com",
            "access_token": "codex-access",
            "refresh_token": "codex-refresh",
            "account_id": "",
            "plan_type": "unknown",
        },
    )

    payload = protocol_register_module._session_data_from_auth_result(FakeResult())

    assert payload["data"]["accountId"] == "acct-plus"
    assert payload["data"]["account"]["id"] == "acct-plus"
    assert payload["data"]["account"]["planType"] == "plus"
    assert payload["codex_oauth_bundle"]["account_id"] == "acct-plus"
    assert payload["codex_oauth_bundle"]["plan_type"] == "plus"
    assert payload["codex_oauth_bundle"]["chatgpt_plan_type"] == "plus"


def test_post_register_session_oauth_updates_account_with_codex_auth(monkeypatch):
    captured = {}
    updates = []

    def fake_login(email, session_data, mail_client=None, **kwargs):
        captured["login"] = {
            "email": email,
            "session_data": session_data,
            "native_oauth": kwargs.get("native_oauth"),
        }
        return {
            "auth_file": "data/auths/codex-new@example.com-free.json",
            "bundle": {
                "email": email,
                "plan_type": "free",
                "access_token": "access",
                "refresh_token": "refresh",
                "id_token": "id",
                "account_id": "account",
            },
        }

    monkeypatch.setattr(manager, "login_codex_via_auth_session_protocol", fake_login)
    monkeypatch.setattr(manager, "is_chrome_cdp_available", lambda *args, **kwargs: False)
    monkeypatch.setattr(manager, "add_account", lambda *args, **kwargs: captured.setdefault("add_account", (args, kwargs)))
    monkeypatch.setattr(manager, "update_account", lambda email, **kwargs: updates.append((email, kwargs)))
    monkeypatch.setattr(manager, "save_auth_file", lambda _bundle: "data/auths/codex-new@example.com-free.json")

    result = manager._run_post_register_session_oauth(
        "new@example.com",
        "pw",
        mail_client=object(),
        auth_session_data={"cookie_header": "__Secure-next-auth.session-token=session", "accountId": "account"},
        cloudmail_account_id="mail-id",
    )

    assert captured["login"]["email"] == "new@example.com"
    assert captured["login"]["native_oauth"] is True
    assert result["source"] == "protocol_oauth"
    assert result["auth_file"] == "data/auths/codex-new@example.com-free.json"
    assert updates == [
        (
            "new@example.com",
            {
                "status": "active",
                "account_type": "free",
                "seat_type": "codex",
                "auth_file": "data/auths/codex-new@example.com-free.json",
                "last_active_at": updates[0][1]["last_active_at"],
            },
        )
    ]


def test_post_register_oauth_prefers_chrome_cdp_when_available(monkeypatch):
    captured = {}
    updates = []

    def fake_chrome_login(email, mail_client=None, **kwargs):
        captured["chrome"] = {
            "email": email,
            "native_oauth": kwargs.get("native_oauth"),
            "password": kwargs.get("password"),
        }
        return {
            "auth_file": "data/auths/codex-cdp@example.com-free.json",
            "bundle": {
                "email": email,
                "plan_type": "free",
                "access_token": "access",
                "refresh_token": "refresh",
                "id_token": "id",
                "account_id": "account",
            },
        }

    monkeypatch.setenv("OAUTH_BROWSER_MODE", "chrome_cdp")
    monkeypatch.setattr(manager, "is_chrome_cdp_available", lambda *args, **kwargs: True)
    monkeypatch.setattr(manager, "login_codex_via_chrome_cdp", fake_chrome_login)
    monkeypatch.setattr(manager, "save_auth_file", lambda _bundle: "data/auths/codex-cdp@example.com-free.json")
    monkeypatch.setattr(
        manager,
        "login_codex_via_auth_session",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("session fallback should not run")),
    )
    monkeypatch.setattr(manager, "add_account", lambda *args, **kwargs: captured.setdefault("add_account", (args, kwargs)))
    monkeypatch.setattr(manager, "update_account", lambda email, **kwargs: updates.append((email, kwargs)))

    result = manager._run_post_register_session_oauth(
        "cdp@example.com",
        "pw",
        mail_client=object(),
        auth_session_data={"cookie_header": "__Secure-next-auth.session-token=session", "accountId": "account"},
        cloudmail_account_id="mail-id",
    )

    assert captured["chrome"] == {"email": "cdp@example.com", "native_oauth": True, "password": "pw"}
    assert result["source"] == "chrome_cdp_oauth"
    assert result["auth_file"] == "data/auths/codex-cdp@example.com-free.json"
    assert updates[0][0] == "cdp@example.com"
    assert updates[0][1]["auth_file"] == "data/auths/codex-cdp@example.com-free.json"


def test_post_register_oauth_uses_windows_ui_when_requested(monkeypatch):
    captured = {}
    updates = []

    def fake_windows_login(email, mail_client=None, **kwargs):
        captured["windows"] = {
            "email": email,
            "native_oauth": kwargs.get("native_oauth"),
            "password": kwargs.get("password"),
        }
        return {
            "auth_file": "data/auths/codex-ui@example.com-free.json",
            "bundle": {
                "email": email,
                "plan_type": "free",
                "access_token": "access",
                "refresh_token": "refresh",
                "id_token": "id",
                "account_id": "account",
            },
        }

    monkeypatch.setenv("OAUTH_BROWSER_MODE", "windows_ui")
    monkeypatch.setattr(manager, "login_codex_via_windows_ui", fake_windows_login)
    monkeypatch.setattr(manager, "is_chrome_cdp_available", lambda *args, **kwargs: False)
    monkeypatch.setattr(manager, "save_auth_file", lambda _bundle: "data/auths/codex-ui@example.com-free.json")
    monkeypatch.setattr(
        manager,
        "login_codex_via_auth_session",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("session fallback should not run")),
    )
    monkeypatch.setattr(manager, "add_account", lambda *args, **kwargs: captured.setdefault("add_account", (args, kwargs)))
    monkeypatch.setattr(manager, "update_account", lambda email, **kwargs: updates.append((email, kwargs)))

    result = manager._run_post_register_session_oauth(
        "ui@example.com",
        "pw",
        mail_client=object(),
        auth_session_data={"cookie_header": "__Secure-next-auth.session-token=session", "accountId": "account"},
        cloudmail_account_id="mail-id",
    )

    assert captured["windows"] == {"email": "ui@example.com", "native_oauth": True, "password": "pw"}
    assert result["source"] == "windows_ui_oauth"
    assert result["auth_file"] == "data/auths/codex-ui@example.com-free.json"
    assert updates[0][0] == "ui@example.com"


def test_protocol_login_missing_codex_bundle_reports_underlying_oauth_error(monkeypatch):
    from autotoken.auth import protocol_register as protocol_register_module

    class FakeConfig:
        proxy = None

    class FakeResult:
        def is_valid(self):
            return True

        def to_dict(self):
            return {
                "email": "free@example.com",
                "session_token": "chatgpt-session",
                "chatgpt_access_token": "chatgpt-access",
                "access_token": "chatgpt-access",
                "refresh_token": "",
            }

    class FakeFlow:
        def __init__(self, _cfg):
            self._last_codex_oauth_error = ""

        def run_protocol_login(self, _adapter, _email, password=""):
            self._last_codex_oauth_error = "Codex OAuth 未捕获 callback code: https://auth.openai.com/add-phone"
            return FakeResult()

    monkeypatch.setattr(protocol_register_module, "_load_protocol_classes", lambda: (FakeFlow, FakeConfig))

    try:
        protocol_register_module.login_once(object(), email="free@example.com", password="pw")
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected missing bundle to raise detailed RuntimeError")

    assert "协议登录完成但未生成 CPA OAuth bundle" in message
    assert "Codex OAuth 未捕获 callback code" in message
    assert "add-phone" in message
