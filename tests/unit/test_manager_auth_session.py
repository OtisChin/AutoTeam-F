from autoteam import manager


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
