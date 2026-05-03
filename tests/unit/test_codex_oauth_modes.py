import base64
import json
import urllib.parse

import requests

from autoteam import accounts, api, manager
from autoteam.codex_auth import (
    _build_auth_url,
    _extract_auth_code_from_url,
    _extract_session_token_from_cookie_header,
    _follow_codex_oauth_redirects_protocol,
    _is_personal_codex_plan,
    is_chrome_cdp_available,
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


def test_manual_account_flow_uses_native_codex_oauth_url():
    flow = ManualAccountFlow()
    params = _query(flow.auth_url)

    assert params["prompt"] == ["login"]
    assert params["id_token_add_organizations"] == ["true"]
    assert params["codex_cli_simplified_flow"] == ["true"]


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

    def fake_login(email, password, mail_client=None, *, use_personal=False, native_oauth=False, headless=False):
        captured["login"] = {
            "email": email,
            "password": password,
            "use_personal": use_personal,
            "native_oauth": native_oauth,
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
    assert task_result["mode"] == "native"
    assert ("plus@example.com", {"last_quota": {"primary_pct": 1}}) in updates
    assert any(
        email == "plus@example.com"
        and update.get("status") == accounts.STATUS_ACTIVE
        and update.get("account_type") == accounts.ACCOUNT_TYPE_PLUS
        and update.get("auth_file") == "auths/codex-plus@example.com-plus.json"
        for email, update in updates
    )


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

    def fake_login(email, password, mail_client=None, *, use_personal=False, native_oauth=False, headless=False):
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
