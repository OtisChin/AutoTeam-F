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
        {"status": 200, "data": {"accessToken": "access"}},
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
