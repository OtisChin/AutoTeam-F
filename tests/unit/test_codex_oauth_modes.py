import base64
import json
import time
import urllib.parse

import pytest
import requests

from autoteam import accounts, api, manager
from autoteam.codex_auth import (
    _build_auth_url,
    _extract_auth_code_from_url,
    _extract_session_token_from_cookie_header,
    _follow_codex_oauth_redirects_protocol,
    _login_codex_via_browser_simple,
    _is_personal_codex_plan,
    _poll_login_otp,
    is_chrome_cdp_available,
    login_codex_via_browser,
    login_codex_via_auth_session_protocol,
)
from autoteam.manual_account import ManualAccountFlow


def _query(url):
    return urllib.parse.parse_qs(urllib.parse.urlparse(url).query)


def _jwt(payload):
    def enc(data):
        raw = json.dumps(data, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{enc({'alg': 'none'})}.{enc(payload)}."


class FakeOAuthResponse:
    def __init__(self, status_code=200, text="", headers=None, payload=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self._payload = payload or {}

    def json(self):
        return self._payload


class FakeOAuthSession:
    def __init__(self, gets, post_payload=None):
        self.gets = list(gets)
        self.post_payload = post_payload or {}
        self.cookies = requests.cookies.RequestsCookieJar()
        self.post_calls = []
        self.get_calls = []

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        response = self.gets.pop(0)
        return response

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return FakeOAuthResponse(payload=self.post_payload)


def test_native_codex_auth_url_matches_cli_style():
    params = _query(_build_auth_url("challenge", "state-1", native_oauth=True))

    assert params["prompt"] == ["login"]
    assert params["id_token_add_organizations"] == ["true"]
    assert params["codex_cli_simplified_flow"] == ["true"]
    assert params["scope"] == ["openid email profile offline_access"]


def test_team_codex_auth_url_keeps_legacy_consent_prompt():
    params = _query(_build_auth_url("challenge", "state-1"))

    assert params["prompt"] == ["consent"]
    assert "id_token_add_organizations" not in params
    assert "codex_cli_simplified_flow" not in params


def test_native_browser_oauth_uses_simple_email_code_flow(monkeypatch):
    captured = {}

    def fake_simple(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"email": args[0], "plan_type": "plus"}

    monkeypatch.setattr("autoteam.codex_auth._login_codex_via_browser_simple", fake_simple)

    result = login_codex_via_browser(
        "user@example.com",
        "pw",
        mail_client=object(),
        native_oauth=True,
        headless=True,
        mail_account_id=123,
    )

    assert result == {"email": "user@example.com", "plan_type": "plus"}
    assert captured["args"][:2] == ("user@example.com", "pw")
    assert captured["kwargs"]["native_oauth"] is True
    assert captured["kwargs"]["headless"] is True
    assert captured["kwargs"]["mail_account_id"] == 123


def test_simple_oauth_mail_lookup_falls_back_from_account_id_to_email(monkeypatch):
    calls = []

    class FakeMailClient:
        def search_emails_by_recipient(self, email, size=10, account_id=None):
            calls.append((email, size, account_id))
            if account_id == 999:
                return []
            return [{"emailId": 8, "accountId": 123, "text": "Your code is 123456"}]

        def extract_verification_code(self, item):
            return "123456" if item.get("emailId") == 8 else None

    class FakePage:
        url = "https://auth.openai.com/email-verification"

        def __init__(self):
            self.handlers = {}
            self.keyboard = type("Keyboard", (), {"type": lambda *_args, **_kwargs: None})()

        def on(self, name, callback):
            self.handlers[name] = callback

        def goto(self, *_args, **_kwargs):
            pass

        def locator(self, selector):
            return FakeLocator(selector, self)

    class FakeLocator:
        def __init__(self, selector, page):
            self.selector = selector
            self.page = page
            self.value = ""
            self.first = self

        def is_visible(self, timeout=0):
            return "input" in self.selector or "button" in self.selector

        def fill(self, value):
            self.value = value

        def input_value(self, timeout=0):
            return self.value

        def click(self, *args, **kwargs):
            if "button" in self.selector and self.page.handlers.get("request"):
                request = type(
                    "Request",
                    (),
                    {"url": "http://localhost:1455/auth/callback?code=abc&state=state"},
                )()
                self.page.handlers["request"](request)

        def press(self, *_args, **_kwargs):
            pass

        def inner_text(self, timeout=0):
            return "检查您的收件箱 验证码"

    class FakeContext:
        def new_page(self):
            return FakePage()

    class FakeBrowser:
        def new_context(self, **_kwargs):
            return FakeContext()

        def close(self):
            pass

    class FakeChromium:
        def launch(self, **_kwargs):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr("autoteam.codex_auth.sync_playwright", lambda: FakePlaywright())
    monkeypatch.setattr("autoteam.codex_auth.LOGIN_OTP_INITIAL_DELAY_SECONDS", 0)
    monkeypatch.setattr("autoteam.codex_auth._fill_auth_email_if_present", lambda *_args, **_kwargs: False)
    monkeypatch.setattr("autoteam.codex_auth._click_email_code_login_if_present", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        "autoteam.codex_auth._exchange_auth_code",
        lambda code, verifier, fallback_email="": {
            "email": fallback_email,
            "access_token": "token",
            "refresh_token": "refresh",
            "id_token": "id",
            "account_id": "acct",
            "plan_type": "plus",
        },
    )
    monkeypatch.setattr("autoteam.codex_auth._screenshot", lambda *_args, **_kwargs: None)

    result = _login_codex_via_browser_simple(
        "user@example.com",
        "",
        FakeMailClient(),
        native_oauth=True,
        mail_account_id=999,
    )

    assert result["plan_type"] == "plus"
    assert ("user@example.com", 10, 999) in calls
    assert ("user@example.com", 10, None) in calls


def test_manual_account_flow_uses_native_codex_oauth_url():
    flow = ManualAccountFlow()
    params = _query(flow.auth_url)

    assert params["prompt"] == ["login"]
    assert params["id_token_add_organizations"] == ["true"]
    assert params["codex_cli_simplified_flow"] == ["true"]


def test_manual_account_flow_times_out_pending_callback(monkeypatch):
    monkeypatch.setattr("autoteam.manual_account.MANUAL_ACCOUNT_TIMEOUT_SECONDS", 60)
    flow = ManualAccountFlow()
    flow.started_at -= 61

    status = flow.status()

    assert status["in_progress"] is False
    assert status["status"] == "error"
    assert "等待超时" in status["error"]


def test_manual_account_flow_polls_mail_without_email_filled_event(monkeypatch):
    class FakeMailClient:
        def search_emails_by_recipient(self, email, size=5):
            return [{"emailId": 2, "subject": "OpenAI login code", "sendEmail": "noreply@tm.openai.com"}]

        def extract_verification_code(self, item):
            return "123456"

    class FakeServer:
        def __init__(self):
            self.phone_required_url = ""
            self.auth_code = ""
            self.callback_url = ""
            self.otp = ""
            self.events = []

    flow = ManualAccountFlow(email="user@example.com")
    flow._mail_client = FakeMailClient()
    flow._latest_email_id = 1
    flow._helper_server = FakeServer()

    import threading

    thread = threading.Thread(target=flow._helper_worker, daemon=True)
    thread.start()
    deadline = time.time() + 1
    while time.time() < deadline and flow._helper_server.otp != "123456":
        time.sleep(0.05)
    flow._finalized = True
    thread.join(timeout=1)

    assert flow._helper_server.otp == "123456"
    assert flow.status()["otp_status"] == "filled"


def test_main_codex_code_rejects_empty_value(monkeypatch):
    class FakeFlow:
        def submit_code(self, _code):
            raise AssertionError("empty code should not reach flow")

    monkeypatch.setattr(api, "_main_codex_flow", FakeFlow())
    monkeypatch.setattr(api, "_main_codex_step", "code_required")

    with pytest.raises(api.HTTPException) as exc:
        api.post_main_codex_code(api.AdminCodeParams(code="   "))

    assert exc.value.status_code == 400
    assert "验证码不能为空" in exc.value.detail


def test_poll_login_otp_accepts_fresh_code_at_snapshot_boundary():
    class FakeMailClient:
        def extract_verification_code(self, item):
            return item.get("code")

    now = int(time.time())

    code, email_id = _poll_login_otp(
        email="user@example.com",
        mail_client=FakeMailClient(),
        search_login_emails=lambda size=5: [
            {
                "emailId": 10,
                "createTime": now,
                "sendEmail": "noreply@tm.openai.com",
                "subject": "Your OpenAI code is 123456",
                "code": "123456",
            }
        ],
        latest_email_id=10,
        used_email_ids=set(),
        window_started_at=now,
        timeout=5,
        require_openai_sender=True,
    )

    assert (code, email_id) == ("123456", 10)


def test_poll_login_otp_does_not_require_openai_sender():
    class FakeMailClient:
        def extract_verification_code(self, item):
            return item.get("code")

    now = int(time.time())

    code, email_id = _poll_login_otp(
        email="user@example.com",
        mail_client=FakeMailClient(),
        search_login_emails=lambda size=5: [
            {
                "emailId": 11,
                "createTime": now,
                "sendEmail": "relay@example.net",
                "subject": "Your code is 654321",
                "code": "654321",
            }
        ],
        latest_email_id=10,
        used_email_ids=set(),
        window_started_at=now,
        timeout=5,
        require_openai_sender=True,
    )

    assert (code, email_id) == ("654321", 11)


def test_poll_login_otp_matches_registration_without_snapshot_filters():
    class FakeMailClient:
        def extract_verification_code(self, item):
            return item.get("code")

    code, email_id = _poll_login_otp(
        email="user@example.com",
        mail_client=FakeMailClient(),
        search_login_emails=lambda size=10: [
            {
                "emailId": 9,
                "createTime": 1,
                "sendEmail": "relay@example.net",
                "subject": "Invitation plus code",
                "code": "111222",
            }
        ],
        latest_email_id=10,
        used_email_ids={9},
        window_started_at=time.time(),
        timeout=5,
        require_openai_sender=True,
    )

    assert (code, email_id) == ("111222", 9)


def test_manual_account_flow_polls_mail_like_registration(monkeypatch):
    class FakeMailClient:
        def search_emails_by_recipient(self, email, size=10):
            assert size == 10
            return [{"emailId": 1, "subject": "Invitation", "sendEmail": "relay@example.net"}]

        def extract_verification_code(self, item):
            return "345678"

    flow = ManualAccountFlow(email="user@example.com")
    flow._mail_client = FakeMailClient()
    flow._latest_email_id = 10
    flow._submitted_codes.add("345678")

    assert flow._poll_email_otp_once() == ("345678", 1)


def test_extract_session_token_from_split_cookie_header():
    token = _extract_session_token_from_cookie_header(
        "a=1; __Secure-next-auth.session-token.1=bbb; "
        "__Secure-next-auth.session-token.0=aaa; oai-did=device"
    )

    assert token == "aaabbb"


def test_extract_auth_code_from_callback_url():
    url = "http://localhost:1455/auth/callback?code=abc123&state=state"

    assert _extract_auth_code_from_url(url) == "abc123"
    assert _extract_auth_code_from_url("https://auth.openai.com/oauth/authorize") == ""


def test_protocol_oauth_redirect_follow_extracts_callback_code():
    session = FakeOAuthSession(
        [
            FakeOAuthResponse(
                status_code=302,
                headers={"Location": "http://localhost:1455/auth/callback?code=abc&state=state-1"},
            )
        ]
    )

    callback = _follow_codex_oauth_redirects_protocol(
        session,
        "https://auth.openai.com/oauth/authorize?x=1",
        expected_state="state-1",
    )

    assert callback["code"] == "abc"
    assert callback["state"] == "state-1"


def test_protocol_oauth_login_saves_cpa_bundle(monkeypatch):
    token_payload = {
        "email": "new@example.com",
        "https://api.openai.com/auth": {
            "chatgpt_account_id": "acct-1",
            "chatgpt_plan_type": "plus",
        },
    }
    fake_session = FakeOAuthSession(
        [
            FakeOAuthResponse(
                status_code=302,
                headers={"Location": "http://localhost:1455/auth/callback?code=abc&state=state"},
            )
        ],
        post_payload={
            "access_token": _jwt(token_payload),
            "refresh_token": "refresh",
            "id_token": _jwt(token_payload),
            "expires_in": 3600,
        },
    )
    saved = {}

    monkeypatch.setattr("autoteam.codex_auth._make_protocol_oauth_session", lambda: fake_session)
    monkeypatch.setattr("autoteam.codex_auth.secrets.token_urlsafe", lambda *_args, **_kwargs: "state")

    def fake_save(bundle):
        saved["bundle"] = bundle
        return "data/auths/codex-new.json"

    result = login_codex_via_auth_session_protocol(
        "new@example.com",
        {
            "data": {"accountId": "acct-1"},
            "auth_context": {
                "cookie_header": "__Secure-next-auth.session-token=session; oai-did=device",
                "device_id": "device",
            },
        },
        auth_file_callback=fake_save,
    )

    assert result["auth_file"] == "data/auths/codex-new.json"
    assert saved["bundle"]["email"] == "new@example.com"
    assert saved["bundle"]["account_id"] == "acct-1"
    assert saved["bundle"]["plan_type"] == "plus"
    assert fake_session.post_calls[0][1]["data"]["code"] == "abc"


def test_personal_codex_plan_accepts_plus_and_rejects_team():
    assert _is_personal_codex_plan("free") is True
    assert _is_personal_codex_plan("plus") is True
    assert _is_personal_codex_plan("pro") is True
    assert _is_personal_codex_plan("team") is False
    assert _is_personal_codex_plan("unknown") is False


def test_chrome_cdp_availability_false_on_request_error(monkeypatch):
    def fail(*args, **kwargs):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(requests, "get", fail)

    assert is_chrome_cdp_available("http://127.0.0.1:9") is False


def test_plus_account_login_uses_native_oauth_and_updates_plan(monkeypatch):
    captured = {}
    updates = []
    account = {
        "email": "plus@example.com",
        "password": "pw",
        "status": accounts.STATUS_ACTIVE,
        "account_type": accounts.ACCOUNT_TYPE_PLUS,
        "cloudmail_account_id": 956,
    }

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autoteam.accounts.find_account", lambda items, email: account if email == account["email"] else None)

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["command"] = command
        captured["func"] = func
        captured["params"] = params
        return {"task_id": "task-login", "command": command, "params": params}

    class FakeMailClient:
        def login(self):
            captured["mail_login"] = True

    def fake_login(
        email,
        password,
        mail_client=None,
        *,
        use_personal=False,
        native_oauth=False,
        headless=False,
        mail_account_id=None,
    ):
        captured["login"] = {
            "email": email,
            "password": password,
            "use_personal": use_personal,
            "native_oauth": native_oauth,
            "mail_account_id": mail_account_id,
        }
        return {
            "email": email,
            "access_token": "token",
            "refresh_token": "refresh",
            "id_token": "id",
            "account_id": "acct-plus",
            "plan_type": "plus",
        }

    monkeypatch.setattr(api, "_start_task", fake_start_task)
    monkeypatch.setattr("autoteam.mail.TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr("autoteam.codex_auth.login_codex_via_browser", fake_login)
    monkeypatch.setattr("autoteam.codex_auth.save_auth_file", lambda bundle: f"auths/codex-{bundle['email']}-plus.json")
    monkeypatch.setattr("autoteam.codex_auth.check_codex_quota", lambda token, account_id=None: ("ok", {"primary_pct": 1}))
    monkeypatch.setattr("autoteam.accounts.update_account", lambda email, **kwargs: updates.append((email, kwargs)))
    monkeypatch.setattr("autoteam.cpa_sync.sync_to_cpa", lambda: captured.setdefault("synced", True))

    result = api.post_account_login(api.LoginAccountParams(email=account["email"]))
    task_result = captured["func"]()

    assert result["task_id"] == "task-login"
    assert captured["command"] == "login:plus@example.com"
    assert captured["login"]["use_personal"] is False
    assert captured["login"]["native_oauth"] is True
    assert captured["login"]["mail_account_id"] == 956
    assert task_result["mode"] == "native"
    assert ("plus@example.com", {"last_quota": {"primary_pct": 1}}) in updates
    assert any(
        email == "plus@example.com"
        and update.get("status") == accounts.STATUS_ACTIVE
        and update.get("account_type") == accounts.ACCOUNT_TYPE_PLUS
        and update.get("auth_file") == "auths/codex-plus@example.com-plus.json"
        for email, update in updates
    )


def test_account_login_skips_protocol_oauth_by_default(monkeypatch):
    captured = {}
    account = {
        "email": "plus@example.com",
        "password": "pw",
        "status": accounts.STATUS_ACTIVE,
        "account_type": accounts.ACCOUNT_TYPE_PLUS,
        "cloudmail_account_id": 956,
    }

    class FakeMailClient:
        def login(self):
            pass

    def fail_protocol(*_args, **_kwargs):
        raise AssertionError("protocol OAuth should be disabled by default")

    def fake_login(email, password, mail_client=None, *, use_personal=False, native_oauth=False, headless=False, mail_account_id=None):
        captured["login"] = {
            "email": email,
            "native_oauth": native_oauth,
            "mail_account_id": mail_account_id,
        }
        return {
            "email": email,
            "access_token": "token",
            "refresh_token": "refresh",
            "id_token": "id",
            "account_id": "acct-plus",
            "plan_type": "plus",
        }

    monkeypatch.delenv("CODEX_OAUTH_USE_AUTH_SESSION_PROTOCOL", raising=False)
    monkeypatch.setattr("autoteam.mail.TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr("autoteam.auth_session_store.load_auth_session", lambda _email: {"cookie_header": "session=1"})
    monkeypatch.setattr("autoteam.codex_auth.login_codex_via_auth_session_protocol", fail_protocol)
    monkeypatch.setattr("autoteam.codex_auth.login_codex_via_browser", fake_login)
    monkeypatch.setattr("autoteam.codex_auth.save_auth_file", lambda bundle: f"auths/{bundle['email']}.json")
    monkeypatch.setattr("autoteam.codex_auth.check_codex_quota", lambda token, account_id=None: ("ok", {}))
    monkeypatch.setattr("autoteam.accounts.update_account", lambda email, **kwargs: None)

    result = api._run_account_codex_login_once(account["email"], account)

    assert result["email"] == "plus@example.com"
    assert captured["login"] == {
        "email": "plus@example.com",
        "native_oauth": True,
        "mail_account_id": 956,
    }


def test_team_account_login_keeps_team_oauth(monkeypatch):
    captured = {}
    account = {
        "email": "team@example.com",
        "password": "pw",
        "status": accounts.STATUS_STANDBY,
        "account_type": accounts.ACCOUNT_TYPE_TEAM,
    }

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autoteam.accounts.find_account", lambda items, email: account if email == account["email"] else None)
    monkeypatch.setattr(api, "_start_task", lambda command, func, params, *args, **kwargs: captured.setdefault("func", func) or {})

    class FakeMailClient:
        def login(self):
            pass

    def fake_login(
        email,
        password,
        mail_client=None,
        *,
        use_personal=False,
        native_oauth=False,
        headless=False,
        mail_account_id=None,
    ):
        captured["use_personal"] = use_personal
        captured["native_oauth"] = native_oauth
        return {
            "email": email,
            "access_token": "token",
            "refresh_token": "refresh",
            "id_token": "id",
            "account_id": "acct-team",
            "plan_type": "team",
        }

    monkeypatch.setattr("autoteam.mail.TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr("autoteam.codex_auth.login_codex_via_browser", fake_login)
    monkeypatch.setattr("autoteam.codex_auth.save_auth_file", lambda bundle: "auths/codex-team@example.com-team.json")
    monkeypatch.setattr("autoteam.codex_auth.check_codex_quota", lambda token, account_id=None: ("ok", {}))
    monkeypatch.setattr("autoteam.accounts.update_account", lambda email, **kwargs: None)
    monkeypatch.setattr("autoteam.cpa_sync.sync_to_cpa", lambda: None)

    api.post_account_login(api.LoginAccountParams(email=account["email"]))
    captured["func"]()

    assert captured["use_personal"] is False
    assert captured["native_oauth"] is False


def test_register_accounts_skips_post_register_oauth(monkeypatch):
    captured = {}

    class FakeMailClient:
        def login(self):
            captured["mail_login"] = True

    def fake_create_account_direct(mail_client, **kwargs):
        captured["kwargs"] = kwargs
        kwargs["out_outcome"].update(status="success", email="new@example.com")
        return "new@example.com"

    monkeypatch.setattr(manager, "TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr(manager, "create_account_direct", fake_create_account_direct)

    result = manager.cmd_register_accounts(
        count=1,
        concurrency=1,
        interval_seconds=0,
        jitter_min_seconds=0,
        jitter_max_seconds=0,
    )

    assert captured["mail_login"] is True
    assert captured["kwargs"]["skip_post_register"] is True
    assert captured["kwargs"]["post_register_oauth"] is False
    assert captured["kwargs"]["check_team_membership"] is False
    assert result["ok"] == 1
    assert result["failed"] == 0


def test_register_accounts_can_enable_post_register_oauth(monkeypatch):
    captured = {}

    class FakeMailClient:
        def login(self):
            captured["mail_login"] = True

    def fake_create_account_direct(mail_client, **kwargs):
        captured["kwargs"] = kwargs
        kwargs["out_outcome"].update(status="success", email="oauth@example.com")
        return {"status": "success", "email": "oauth@example.com", "auth_file": "data/auths/codex-oauth.json"}

    monkeypatch.setattr(manager, "TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr(manager, "create_account_direct", fake_create_account_direct)

    result = manager.cmd_register_accounts(
        count=1,
        concurrency=1,
        interval_seconds=0,
        jitter_min_seconds=0,
        jitter_max_seconds=0,
        post_register_oauth=True,
    )

    assert captured["mail_login"] is True
    assert captured["kwargs"]["skip_post_register"] is False
    assert captured["kwargs"]["post_register_oauth"] is True
    assert captured["kwargs"]["check_team_membership"] is False
    assert result["ok"] == 1
    assert result["failed"] == 0
