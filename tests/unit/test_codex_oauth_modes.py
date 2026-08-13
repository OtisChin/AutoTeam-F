import base64
import json
import os
import time
import urllib.parse
from pathlib import Path

import pytest
import requests

from autotoken import accounts, api, manager
from autotoken.auth import codex_auth as codex_auth_module
from autotoken.codex_auth import (
    WindowsUICodexAuthFlow,
    _build_auth_url,
    _click_oauth_consent_if_present,
    _click_primary_auth_button,
    _compact_input_snapshots,
    _extract_auth_code_from_url,
    _extract_session_token_from_cookie_header,
    _exchange_auth_code,
    _fill_auth_email_if_present,
    _fill_otp_input_and_verify,
    _follow_codex_oauth_redirects_protocol,
    _format_oauth_phone_for_input,
    _click_auth_retry_if_timed_out,
    _goto_oauth_auth_page,
    _wait_for_oauth_cloudflare_challenge,
    _is_add_phone_page,
    _is_browser_open_url,
    _is_codex_oauth_callback_url,
    _is_email_verification_page,
    _is_personal_codex_plan,
    _is_phone_otp_page,
    _otp_input_locator,
    _phone_otp_input_locator,
    _launch_codex_oauth_browser_context,
    _login_codex_via_browser_simple,
    _open_real_chrome_url,
    _parse_codex_oauth_callback_url,
    _poll_login_otp,
    _should_invalidate_oauth_phone,
    _handle_oauth_add_phone_if_present,
    _submit_oauth_add_phone_candidate,
    is_chrome_cdp_available,
    login_codex_via_auth_session_protocol,
    login_codex_via_browser,
)
from autotoken.manual_account import ManualAccountFlow
from autotoken.storage import auth_storage


def _query(url):
    return urllib.parse.parse_qs(urllib.parse.urlparse(url).query)


def _jwt(payload):
    def enc(data):
        raw = json.dumps(data, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{enc({'alg': 'none'})}.{enc(payload)}."


def test_save_auth_file_matches_email_glob_chars_literally(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    literal = auth_dir / "codex-user[abc]@example.com-unknown-deadbeef.json"
    wildcard_match = auth_dir / "codex-usera@example.com-unknown-deadbeef.json"
    literal.write_text("{}", encoding="utf-8")
    wildcard_match.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(codex_auth_module, "AUTH_DIR", auth_dir)
    monkeypatch.setattr(auth_storage, "AUTH_DIR", auth_dir)
    monkeypatch.setattr(codex_auth_module, "upsert_codex_auth_file", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(codex_auth_module, "delete_codex_auth_file", lambda *_args, **_kwargs: None)

    result = codex_auth_module.save_auth_file(
        {
            "email": "user[abc]@example.com",
            "plan_type": "plus",
            "account_id": "acc-literal",
            "access_token": "access-token",
            "id_token": "id-token",
            "refresh_token": "refresh-token",
            "expired": 1893456000,
        }
    )

    saved = Path(result)
    assert saved.parent == auth_dir
    assert saved.name.startswith("codex-user_abc_@example.com-plus-")
    assert not literal.exists()
    assert wildcard_match.exists()


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


def test_codex_oauth_callback_parser_accepts_query_or_fragment_values():
    query_callback = "http://localhost:1455/auth/callback?code=query-code&state=query-state"
    fragment_callback = "https://auth.openai.com/auth/callback#code=fragment-code&state=fragment-state"

    assert _is_codex_oauth_callback_url(query_callback) is True
    assert _is_codex_oauth_callback_url(fragment_callback) is True
    assert _parse_codex_oauth_callback_url(query_callback) == {
        "code": "query-code",
        "state": "query-state",
        "error": "",
        "raw_url": query_callback,
    }
    assert _parse_codex_oauth_callback_url(fragment_callback) == {
        "code": "fragment-code",
        "state": "fragment-state",
        "error": "",
        "raw_url": fragment_callback,
    }


def test_codex_oauth_callback_parser_uses_error_description_fallback():
    callback = "https://auth.openai.com/auth/callback#error_description=access_denied"

    assert _is_codex_oauth_callback_url(callback) is True
    assert _parse_codex_oauth_callback_url(callback)["error"] == "access_denied"


def test_exchange_auth_code_retries_transient_remote_disconnect(monkeypatch):
    calls = {"count": 0}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "access_token": _jwt({"https://api.openai.com/auth": {"chatgpt_plan_type": "plus"}}),
                "refresh_token": "refresh-token",
                "id_token": _jwt({"email": "user@example.com", "sub": "acct-1"}),
                "expires_in": 3600,
            }

    def fake_post(*_args, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise requests.exceptions.ConnectionError("Remote end closed connection without response")
        return FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(codex_auth_module.time, "sleep", lambda _seconds: None)

    bundle = _exchange_auth_code("auth-code", "verifier", fallback_email="user@example.com")

    assert calls["count"] == 2
    assert bundle["email"] == "user@example.com"
    assert bundle["refresh_token"] == "refresh-token"


def test_team_codex_auth_url_keeps_legacy_consent_prompt():
    params = _query(_build_auth_url("challenge", "state-1"))

    assert params["prompt"] == ["consent"]
    assert "id_token_add_organizations" not in params
    assert "codex_cli_simplified_flow" not in params


def test_browser_open_url_accepts_only_http_urls():
    assert _is_browser_open_url("https://auth.openai.com/oauth")
    assert _is_browser_open_url("http://127.0.0.1:3000/helper")
    assert not _is_browser_open_url("file:///C:/tmp/auth.html")
    assert not _is_browser_open_url("javascript:alert(1)")
    assert not _is_browser_open_url("https:///missing-host")


def test_open_real_chrome_url_uses_chrome_argv_without_cmd(monkeypatch, tmp_path):
    calls = []
    chrome = tmp_path / "chrome.exe"
    chrome.write_text("", encoding="utf-8")

    def fake_popen(args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setenv("OAUTH_WINDOWS_CHROME_PATH", str(chrome))
    monkeypatch.setenv("OAUTH_REAL_CHROME_USER_DATA_DIR", str(tmp_path / "User Data"))
    monkeypatch.setattr(codex_auth_module.subprocess, "Popen", fake_popen)

    assert _open_real_chrome_url("https://auth.openai.com/oauth?x=1") is True

    assert calls
    args, kwargs = calls[0]
    assert args[0] == str(chrome)
    assert args[-1] == "https://auth.openai.com/oauth?x=1"
    assert args[:3] != ["cmd", "/c", "start"]
    assert kwargs == {"stdout": codex_auth_module.subprocess.DEVNULL, "stderr": codex_auth_module.subprocess.DEVNULL}


def test_open_real_chrome_url_fallback_uses_default_browser_without_cmd(monkeypatch, tmp_path):
    popen_calls = []
    startfile_calls = []

    def fake_popen(args, **kwargs):
        popen_calls.append((args, kwargs))

    monkeypatch.setenv("OAUTH_WINDOWS_CHROME_PATH", str(tmp_path / "missing-chrome.exe"))
    monkeypatch.setattr(codex_auth_module.os, "startfile", lambda url: startfile_calls.append(url), raising=False)
    monkeypatch.setattr(codex_auth_module.subprocess, "Popen", fake_popen)

    assert _open_real_chrome_url("https://auth.openai.com/oauth?x=1") is True

    assert startfile_calls == ["https://auth.openai.com/oauth?x=1"]
    assert popen_calls == []


def test_open_real_chrome_url_rejects_non_http_without_process(monkeypatch):
    calls = []
    monkeypatch.setattr(codex_auth_module.subprocess, "Popen", lambda *args, **kwargs: calls.append((args, kwargs)))

    assert _open_real_chrome_url("file:///C:/tmp/auth.html") is False

    assert calls == []


def test_windows_ui_helper_url_uses_shared_autotoken_fragment_with_legacy_aliases():
    flow = object.__new__(WindowsUICodexAuthFlow)
    flow.auth_url = "https://auth.example/authorize"
    flow._server = type("HelperServer", (), {"token": "secret-token", "port": 4711})()

    fragment = urllib.parse.parse_qs(urllib.parse.urlparse(flow._helper_auth_url()).fragment)

    assert fragment["autotoken_token"] == ["secret-token"]
    assert fragment["autotoken_port"] == ["4711"]
    assert fragment["autotoken_auth"] == ["https://auth.example/authorize"]
    assert fragment["autoteam_token"] == ["secret-token"]
    assert fragment["autoteam_port"] == ["4711"]
    assert fragment["autoteam_auth"] == ["https://auth.example/authorize"]


def test_compact_input_snapshots_formats_visible_inputs(monkeypatch):
    monkeypatch.setattr(
        "autotoken.codex_auth._visible_input_snapshots",
        lambda _page: [
            {
                "idx": 0,
                "type": "email",
                "name": "username",
                "id": "email-field",
                "placeholder": "Email address",
                "aria": "Email",
                "value": "user@example.com",
                "label": "Email address label",
            }
        ],
    )

    assert _compact_input_snapshots(object()) == (
        "idx=0 type=email name=username id=email-field placeholder=Email address "
        "aria=Email value=user@example.com label=Email address label"
    )


def test_should_invalidate_oauth_phone_keeps_recoverable_errors_available():
    assert _should_invalidate_oauth_phone("") is False
    assert _should_invalidate_oauth_phone("页面填写失败: 输入框不可见") is False
    assert _should_invalidate_oauth_phone("手机验证码无效且未找到重新发送按钮: no button") is False
    assert _should_invalidate_oauth_phone("手机验证码提交后页面未前进: still waiting") is False
    assert _should_invalidate_oauth_phone("phone number already used") is True


def test_is_add_phone_page_does_not_match_login_phone_option():
    class FakeBody:
        def inner_text(self, timeout=0):
            return "欢迎回来\n电子邮件地址\n继续\n使用电话号码继续"

    class FakePage:
        url = "https://auth.openai.com/log-in"

        def locator(self, selector):
            assert selector == "body"
            return FakeBody()

    assert _is_add_phone_page(FakePage()) is False


def test_is_add_phone_page_matches_required_phone_title():
    class FakeBody:
        def inner_text(self, timeout=0):
            return "电话号码是必填项\n添加您的电话号码以继续。"

    class FakePage:
        url = "https://auth.openai.com/add-phone"

        def locator(self, selector):
            assert selector == "body"
            return FakeBody()

    assert _is_add_phone_page(FakePage()) is True


def test_japanese_email_verification_page_is_detected_as_otp_page():
    class FakeBody:
        def inner_text(self, timeout=0):
            return "受信箱を確認してください\nclays60_pitcher@icloud.com にお送りした検証コードを入力してください。"

    class FakeInput:
        def __init__(self, selector):
            self.selector = selector

        @property
        def first(self):
            return self

        def is_visible(self, timeout=0):
            return "input" in self.selector

    class FakePage:
        url = "https://auth.openai.com/log-in"

        def locator(self, selector):
            if selector == "body":
                return FakeBody()
            return FakeInput(selector)

    page = FakePage()

    assert _is_email_verification_page(page) is True
    assert _otp_input_locator(page) is not None


def test_japanese_phone_verification_page_is_detected_as_phone_otp_page():
    class FakeBody:
        def inner_text(self, timeout=0):
            return "携帯電話を確認してください\n+1 (430) 216-6265 にお送りした認証コードを入力してください。"

    class FakeInput:
        def __init__(self, selector):
            self.selector = selector

        @property
        def first(self):
            return self

        def is_visible(self, timeout=0):
            return "input" in self.selector

    class FakePage:
        url = "https://auth.openai.com/phone-verification"

        def locator(self, selector):
            if selector == "body":
                return FakeBody()
            return FakeInput(selector)

    page = FakePage()

    assert _is_phone_otp_page(page) is True
    assert _phone_otp_input_locator(page) is not None


def test_format_oauth_phone_for_input_prefixes_non_us_dynamic_country():
    class FakeBody:
        def inner_text(self, timeout=0):
            return "电话号码是必填项"

    class FakePage:
        def locator(self, selector):
            assert selector == "body"
            return FakeBody()

    class FakeInput:
        def input_value(self, timeout=0):
            return ""

    assert _format_oauth_phone_for_input(FakePage(), FakeInput(), "27631234567", country_id="31") == "+27631234567"
    assert _format_oauth_phone_for_input(FakePage(), FakeInput(), "631234567", country_id="31") == "+27631234567"


def test_format_oauth_phone_for_input_strips_us_country_when_page_is_us():
    class FakeBody:
        def inner_text(self, timeout=0):
            return "美国 (+1)\n电话号码是必填项"

    class FakePage:
        def locator(self, selector):
            assert selector == "body"
            return FakeBody()

    class FakeInput:
        def input_value(self, timeout=0):
            return "+1"

    assert _format_oauth_phone_for_input(FakePage(), FakeInput(), "12125551234", force_us=True, country_id="187") == "2125551234"


def test_native_browser_oauth_uses_simple_email_code_flow(monkeypatch):
    captured = {}

    def fake_simple(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"email": args[0], "plan_type": "plus"}

    monkeypatch.setattr("autotoken.codex_auth._login_codex_via_browser_simple", fake_simple)

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


def test_roxy_oauth_browser_context_uses_roxybrowser_cdp(monkeypatch):
    calls = []

    class FakeRoxyClient:
        def __init__(self, api_host, api_token):
            calls.append(("client", api_host, api_token))

        def launch(self, **kwargs):
            calls.append(("launch", kwargs))
            return type(
                "Launch",
                (),
                {
                    "connection": {"http": "127.0.0.1:54444"},
                    "workspace_id": "workspace-1",
                    "dir_id": "dir-1",
                    "created_profile": False,
                },
            )()

    class FakeContext:
        pass

    class FakeBrowser:
        def __init__(self):
            self.contexts = [FakeContext()]

    class FakeChromium:
        def connect_over_cdp(self, endpoint_url):
            calls.append(("cdp", endpoint_url))
            return FakeBrowser()

    monkeypatch.setattr("autotoken.settings.config.get_roxybrowser_config", lambda: {"api_host": "http://127.0.0.1:50000", "api_token": "token"})
    monkeypatch.setattr("autotoken.roxybrowser_client.RoxyBrowserClient", FakeRoxyClient)

    browser, context, cleanup = _launch_codex_oauth_browser_context(
        type("FakePlaywright", (), {"chromium": FakeChromium()})(),
        use_roxybrowser=True,
        email="user@example.com",
        proxy_url="socks5h://proxy.example:10000",
    )

    assert isinstance(browser, FakeBrowser)
    assert isinstance(context, FakeContext)
    assert callable(cleanup)
    assert calls == [
        ("client", "http://127.0.0.1:50000", "token"),
        (
            "launch",
            {
                "window_name": "autotoken-oauth-user@example.com",
                "proxy_url": "socks5h://proxy.example:10000",
                "clear_profile_data": True,
                "force_new_profile": True,
            },
        ),
        ("cdp", "http://127.0.0.1:54444"),
    ]


def test_oauth_cloudflare_wait_clicks_turnstile_until_challenge_clears(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    now = {"value": 0.0}
    monkeypatch.setattr(time, "time", lambda: now.__setitem__("value", now["value"] + 0.25) or now["value"])

    class FakeLocator:
        def __init__(self, page, selector):
            self.page = page
            self.selector = selector

        @property
        def first(self):
            return self

        def is_visible(self, timeout=0):
            return self.page.challenge and "iframe" in self.selector

        def bounding_box(self):
            return {"x": 10, "y": 20, "width": 300, "height": 80}

    class FakeFrameLocator:
        def __init__(self, page):
            self.page = page

        @property
        def first(self):
            return self

        def locator(self, _selector):
            return self

        def is_visible(self, timeout=0):
            return self.page.challenge

        def click(self, timeout=0, force=False):
            self.page.clicked += 1
            self.page.challenge = False

    class FakeMouse:
        def __init__(self, page):
            self.page = page

        def click(self, _x, _y):
            self.page.clicked += 1
            self.page.challenge = False

    class FakePage:
        url = "https://auth.openai.com/oauth/authorize"

        def __init__(self):
            self.challenge = True
            self.clicked = 0
            self.mouse = FakeMouse(self)

        def content(self):
            if self.challenge:
                return '<iframe src="https://challenges.cloudflare.com/cdn-cgi/challenge-platform"></iframe>请验证您是真人'
            return "<html>ok</html>"

        def frame_locator(self, _selector):
            return FakeFrameLocator(self)

        def locator(self, selector):
            return FakeLocator(self, selector)

    page = FakePage()

    assert _wait_for_oauth_cloudflare_challenge(page, stage="提交验证码后", timeout=5) is True
    assert page.clicked == 1






def test_add_phone_submit_html_json_error_is_returned_as_page_error(monkeypatch):
    monkeypatch.setattr(codex_auth_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(codex_auth_module, "_screenshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(codex_auth_module, "_phone_input_locator", lambda page: page.phone_input)
    monkeypatch.setattr(codex_auth_module, "_format_oauth_phone_for_input", lambda *_args, **_kwargs: "(913) 416-8508")
    monkeypatch.setattr(codex_auth_module, "_fill_oauth_phone_field", lambda *_args, **_kwargs: (True, ""))
    monkeypatch.setattr(codex_auth_module, "_true_oauth_phone_has_digits", lambda *_args, **_kwargs: (True, {}))
    monkeypatch.setattr(codex_auth_module, "_click_primary_auth_button", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(codex_auth_module, "_phone_otp_input_locator", lambda _page: None)
    monkeypatch.setattr(codex_auth_module, "_detect_phone_rate_limited", lambda _page: "")
    monkeypatch.setattr(codex_auth_module, "_detect_phone_whatsapp_fallback", lambda _page: "")
    monkeypatch.setattr(codex_auth_module, "_detect_phone_rejected", lambda _page: "")

    class FakeInput:
        pass

    class FakeBody:
        def inner_text(self, timeout=0):
            return "不明なエラーが発生しました\nUnexpected token '<', '<!DOCTYPE '... is not valid JSON\nもう一度試す"

    class FakePage:
        url = "https://auth.openai.com/add-phone"

        def __init__(self):
            self.phone_input = FakeInput()

        def locator(self, selector):
            if selector == "body":
                return FakeBody()
            raise RuntimeError(selector)

    ok, error = _submit_oauth_add_phone_candidate(
        FakePage(),
        email="innate_shout9h@icloud.com",
        phone_item={"phone_number": "19134168508", "source": "smsbower", "sms_url": "dynamic"},
    )

    assert ok is False
    assert "not valid JSON" in error
    assert "手机号提交后页面错误" in error


def test_add_phone_html_json_error_retries_whole_oauth_without_marking_phone_invalid(monkeypatch):
    releases = []
    phone_item = {
        "phone_number": "19134168508",
        "source": "smsbower",
        "sms_url": "dynamic",
        "activation_id": "act-1",
        "activation": object(),
    }

    class FakePage:
        url = "https://auth.openai.com/add-phone"

    monkeypatch.setattr(codex_auth_module, "_is_add_phone_page", lambda _page: True)
    monkeypatch.setattr(
        codex_auth_module,
        "_acquire_oauth_smsbower_phone",
        lambda *_args, **_kwargs: (phone_item, ""),
    )
    monkeypatch.setattr(
        codex_auth_module,
        "_submit_oauth_add_phone_candidate",
        lambda *_args, **_kwargs: (
            False,
            "手机号提交后页面错误: Unexpected token '<', '<!DOCTYPE '... is not valid JSON",
        ),
    )

    def fake_release(item, **kwargs):
        releases.append({"item": item, **kwargs})

    monkeypatch.setattr(codex_auth_module, "_release_oauth_sms_activation_phone", fake_release)

    with pytest.raises(RuntimeError, match="OAuth 页面临时错误"):
        _handle_oauth_add_phone_if_present(
            FakePage(),
            email="innate_shout9h@icloud.com",
            phone_sms_provider="smsbower",
        )

    assert releases
    assert releases[0]["item"] is phone_item
    assert releases[0].get("cancel") is not True
    assert "not valid JSON" in releases[0]["reason"]

def test_add_phone_otp_route_error_400_is_not_treated_as_success(monkeypatch):
    monkeypatch.setattr(codex_auth_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(codex_auth_module, "_screenshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(codex_auth_module, "_phone_input_locator", lambda page: page.phone_input)
    monkeypatch.setattr(codex_auth_module, "_format_oauth_phone_for_input", lambda *_args, **_kwargs: "(903) 505-8637")
    monkeypatch.setattr(codex_auth_module, "_fill_oauth_phone_field", lambda *_args, **_kwargs: (True, ""))
    monkeypatch.setattr(codex_auth_module, "_true_oauth_phone_has_digits", lambda *_args, **_kwargs: (True, {}))
    monkeypatch.setattr(codex_auth_module, "_click_primary_auth_button", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(codex_auth_module, "_phone_otp_input_locator", lambda page: page.otp_input if page.stage == "phone_otp" else None)
    monkeypatch.setattr(codex_auth_module, "_detect_phone_rate_limited", lambda _page: "")
    monkeypatch.setattr(codex_auth_module, "_detect_phone_whatsapp_fallback", lambda _page: "")
    monkeypatch.setattr(codex_auth_module, "_detect_phone_rejected", lambda _page: "")
    monkeypatch.setattr(codex_auth_module, "_make_phone_item_otp_provider", lambda _phone_item: lambda: "123456")

    class FakeInput:
        def __init__(self, page):
            self.page = page
            self.value = ""

        def fill(self, value):
            self.value = value

        def evaluate(self, _script, value=None):
            if value is not None:
                self.value = value
            return None

        def input_value(self, timeout=0):
            return self.value

        def press(self, _key):
            pass

    class FakeBody:
        def __init__(self, page):
            self.page = page

        def inner_text(self, timeout=0):
            if self.page.stage == "route_error":
                return 'Route Error (400 Bad Request): {"error":"invalid_state"}\nもう一度試す'
            return "携帯電話を確認 認証コード コードを入力"

    class FakeButton:
        def __init__(self, page):
            self.page = page

        @property
        def first(self):
            return self

        def click(self, *args, **kwargs):
            self.page.stage = "route_error"

    class FakePage:
        url = "https://auth.openai.com/add-phone/phone-verification"

        def __init__(self):
            self.stage = "phone_otp"
            self.phone_input = FakeInput(self)
            self.otp_input = FakeInput(self)

        def locator(self, selector):
            if selector == "body":
                return FakeBody(self)
            return FakeButton(self)

    ok, error = _submit_oauth_add_phone_candidate(
        FakePage(),
        email="innate_shout9h@icloud.com",
        phone_item={"phone_number": "19035058637", "source": "smsbower", "sms_url": "dynamic"},
    )

    assert ok is False
    assert "400" in error or "Route Error" in error



def test_auth_retry_does_not_click_retry_for_auth_400_invalid_state():
    class FakeBody:
        def inner_text(self, timeout=0):
            return 'Route Error (400 Bad Request): {"error":"invalid_state"}\nもう一度試す'

    class FakeButton:
        def __init__(self, page):
            self.page = page

        @property
        def first(self):
            return self

        def is_visible(self, timeout=0):
            return True

        def click(self):
            self.page.clicked += 1

    class FakePage:
        def __init__(self):
            self.clicked = 0

        def locator(self, selector):
            if selector == "body":
                return FakeBody()
            return FakeButton(self)

    page = FakePage()

    assert _click_auth_retry_if_timed_out(page) is False
    assert page.clicked == 0

def test_auth_retry_clicks_japanese_route_error_retry_button():
    class FakeBody:
        def inner_text(self, timeout=0):
            return '不明なエラーが発生しました\\nRoute Error (500 Internal Server Error): {"isTrusted": true}\\nもう一度試す'

    class FakeButton:
        def __init__(self, page, selector):
            self.page = page
            self.selector = selector

        @property
        def first(self):
            return self

        def is_visible(self, timeout=0):
            return "もう一度試す" in self.selector

        def click(self):
            self.page.clicked = True

    class FakePage:
        def __init__(self):
            self.clicked = False

        def locator(self, selector):
            if selector == "body":
                return FakeBody()
            return FakeButton(self, selector)

    page = FakePage()

    assert _click_auth_retry_if_timed_out(page) is True
    assert page.clicked is True


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
        pages = []

        def new_page(self):
            return FakePage()

        def close(self):
            pass

    class FakeBrowser:
        def new_context(self, **_kwargs):
            return FakeContext()

        def close(self):
            pass

    class FakeChromium:
        def launch(self, **_kwargs):
            return FakeBrowser()

        def launch_persistent_context(self, _user_data_dir, **_kwargs):
            return FakeContext()

    class FakePlaywright:
        chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr("autotoken.codex_auth.sync_playwright", lambda: FakePlaywright())
    monkeypatch.setattr("autotoken.codex_auth.LOGIN_OTP_INITIAL_DELAY_SECONDS", 0)
    monkeypatch.setattr("autotoken.codex_auth._fill_auth_email_if_present", lambda *_args, **_kwargs: False)
    monkeypatch.setattr("autotoken.codex_auth._click_email_code_login_if_present", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        "autotoken.codex_auth._exchange_auth_code",
        lambda code, verifier, fallback_email="": {
            "email": fallback_email,
            "access_token": "token",
            "refresh_token": "refresh",
            "id_token": "id",
            "account_id": "acct",
            "plan_type": "plus",
        },
    )
    monkeypatch.setattr("autotoken.codex_auth._screenshot", lambda *_args, **_kwargs: None)

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


def test_simple_oauth_retries_initial_auth_page_navigation_once(monkeypatch):
    goto_calls = {"count": 0}

    class FakeMailClient:
        def search_emails_by_recipient(self, email, size=10, account_id=None):
            return [{"emailId": 1, "text": "Your code is 123456"}]

        def extract_verification_code(self, item):
            return "123456"

    class FakePage:
        url = "https://auth.openai.com/email-verification"

        def __init__(self):
            self.handlers = {}
            self.keyboard = type("Keyboard", (), {"type": lambda *_args, **_kwargs: None})()

        def on(self, name, callback):
            self.handlers[name] = callback

        def goto(self, *_args, **_kwargs):
            goto_calls["count"] += 1
            if goto_calls["count"] == 1:
                raise RuntimeError("Page.goto: net::ERR_CONNECTION_CLOSED")

        def locator(self, selector):
            return FakeLocator(selector, self)

    class FakeLocator:
        def __init__(self, selector, page):
            self.selector = selector
            self.page = page
            self.value = ""

        @property
        def first(self):
            return self

        def is_visible(self, timeout=0):
            return "input" in self.selector or "button" in self.selector

        def click(self, *args, **kwargs):
            if "button" in self.selector and self.page.handlers.get("request"):
                self.page.handlers["request"](type("Request", (), {"url": "http://localhost:1455/auth/callback?code=abc"})())

        def input_value(self, timeout=0):
            return self.value

        def press(self, *_args, **_kwargs):
            pass

        def fill(self, value):
            self.value = value

        def evaluate(self, _script, value=None):
            if value is not None:
                self.value = value

        def inner_text(self, timeout=0):
            return "检查您的收件箱 验证码"

    class FakeContext:
        def new_page(self):
            return FakePage()

        def close(self):
            pass

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

    monkeypatch.setattr("autotoken.codex_auth.sync_playwright", lambda: FakePlaywright())
    monkeypatch.setattr("autotoken.codex_auth.LOGIN_OTP_INITIAL_DELAY_SECONDS", 0)
    monkeypatch.setattr("autotoken.codex_auth._fill_auth_email_if_present", lambda *_args, **_kwargs: False)
    monkeypatch.setattr("autotoken.codex_auth._click_email_code_login_if_present", lambda *_args, **_kwargs: False)
    monkeypatch.setattr("autotoken.codex_auth._screenshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("autotoken.codex_auth._exchange_auth_code", lambda *_args, **_kwargs: {"plan_type": "plus"})

    result = _login_codex_via_browser_simple("user@example.com", "", FakeMailClient(), native_oauth=True)

    assert result["plan_type"] == "plus"
    assert goto_calls["count"] == 2


def test_oauth_auth_page_navigation_retries_multiple_roxy_connection_closes(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    class FakePage:
        def __init__(self):
            self.calls = 0

        def goto(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls < 4:
                raise RuntimeError("Page.goto: net::ERR_CONNECTION_CLOSED")

    page = FakePage()

    _goto_oauth_auth_page(page, "https://auth.openai.com/oauth/authorize", stage="Roxy OAuth")

    assert page.calls == 4


def test_manual_account_flow_uses_native_codex_oauth_url():
    flow = ManualAccountFlow()
    params = _query(flow.auth_url)

    assert params["prompt"] == ["login"]
    assert params["id_token_add_organizations"] == ["true"]
    assert params["codex_cli_simplified_flow"] == ["true"]


def test_manual_account_flow_times_out_pending_callback(monkeypatch):
    monkeypatch.setattr("autotoken.manual_account.MANUAL_ACCOUNT_TIMEOUT_SECONDS", 60)
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


def test_poll_login_otp_skips_used_email_ids_and_placeholder_codes(monkeypatch):
    class FakeMailClient:
        def extract_verification_code(self, item):
            return item.get("code")

    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    calls = {"count": 0}

    def search(size=10):
        calls["count"] += 1
        if calls["count"] == 1:
            return [
                {
                    "emailId": 9,
                    "createTime": 1,
                    "sendEmail": "relay@example.net",
                    "subject": "Already submitted code",
                    "code": "111222",
                },
                {
                    "emailId": 10,
                    "createTime": 2,
                    "sendEmail": "relay@example.net",
                    "subject": "Placeholder code",
                    "code": "000000",
                },
            ]
        return [
            {
                "emailId": 11,
                "createTime": 3,
                "sendEmail": "relay@example.net",
                "subject": "New login code",
                "code": "333444",
            }
        ]

    code, email_id = _poll_login_otp(
        email="user@example.com",
        mail_client=FakeMailClient(),
        search_login_emails=search,
        latest_email_id=10,
        used_email_ids={9},
        window_started_at=time.time(),
        timeout=5,
        require_openai_sender=True,
    )

    assert (code, email_id) == ("333444", 11)


def test_fill_otp_input_rejects_partial_single_digit_fill():
    class FakeOtpInput:
        def evaluate(self, *_args, **_kwargs):
            return False

        def fill(self, value):
            self.value = str(value)[0]

        def input_value(self, timeout=1000):
            return self.value

    fake = FakeOtpInput()

    assert _fill_otp_input_and_verify(fake, "123456") is False


def test_fill_auth_email_does_not_write_on_email_verification_page(monkeypatch):
    class FakeField:
        value = ""

        def click(self, *args, **kwargs):
            pass

        def press(self, *_args, **_kwargs):
            pass

        def fill(self, value):
            self.value = value

        def input_value(self, timeout=1000):
            return self.value

    class FakePage:
        url = "https://auth.openai.com/email-verification"

        def __init__(self):
            self.field = FakeField()
            self.keyboard = type("Keyboard", (), {"type": lambda _self, value, **_kwargs: setattr(self.field, "value", value)})()

        def locator(self, selector):
            return self.field

    page = FakePage()
    monkeypatch.setattr("autotoken.codex_auth._email_input_locator", lambda _page: page.field)

    assert _fill_auth_email_if_present(page, "denisemaynard4560@outlook.com", timeout=10) is False
    assert page.field.value == ""


def test_fill_auth_email_does_not_match_username_autocomplete_on_code_page(monkeypatch):
    class FakeField:
        value = ""

        def click(self, *args, **kwargs):
            pass

        def press(self, *_args, **_kwargs):
            pass

        def fill(self, value):
            self.value = value

        def input_value(self, timeout=1000):
            return self.value

    class FakeLocator:
        first = None

        def __init__(self, field):
            self.first = self
            self.field = field

        def inner_text(self, timeout=500):
            return "检查你的收件箱 输入我们刚刚发送的验证码"

        def is_visible(self, timeout=300):
            return True

        def click(self, *args, **kwargs):
            self.field.click(*args, **kwargs)

        def press(self, *args, **kwargs):
            self.field.press(*args, **kwargs)

        def fill(self, value):
            self.field.fill(value)

        def input_value(self, timeout=1000):
            return self.field.input_value(timeout=timeout)

    class FakePage:
        url = "https://auth.openai.com/email-verification"

        def __init__(self):
            self.field = FakeField()
            self.locator_obj = FakeLocator(self.field)
            self.keyboard = type("Keyboard", (), {"type": lambda _self, value, **_kwargs: setattr(self.field, "value", value)})()

        def locator(self, selector):
            return self.locator_obj

    page = FakePage()

    assert _fill_auth_email_if_present(page, "davidsloan2776@outlook.com", timeout=10) is False
    assert page.field.value == ""


def test_fill_auth_email_does_not_run_on_visible_password_page(monkeypatch):
    class FakeField:
        value = ""

        def click(self, *args, **kwargs):
            pass

        def press(self, *_args, **_kwargs):
            pass

        def fill(self, value):
            self.value = value

        def input_value(self, timeout=1000):
            return self.value

    class FakePasswordLocator:
        first = None

        def __init__(self):
            self.first = self

        def is_visible(self, timeout=100):
            return True

    class FakePage:
        url = "https://auth.openai.com/log-in/password"

        def __init__(self):
            self.field = FakeField()
            self.password = FakePasswordLocator()
            self.keyboard = type("Keyboard", (), {"type": lambda _self, value, **_kwargs: setattr(self.field, "value", value)})()

        def locator(self, selector):
            return self.password

    page = FakePage()
    monkeypatch.setattr("autotoken.codex_auth._email_input_locator", lambda _page: page.field)

    assert _fill_auth_email_if_present(page, "rjtr26009@outlook.com", timeout=10) is False
    assert page.field.value == ""


def test_click_primary_auth_button_clicks_form_submit_before_enter_for_localized_labels():
    class HiddenLocator:
        @property
        def first(self):
            return self

        @property
        def last(self):
            return self

        def is_visible(self, timeout=0):
            return False

        def is_enabled(self, timeout=0):
            return False

        def get_attribute(self, *_args, **_kwargs):
            return ""

        def click(self, *args, **kwargs):
            raise AssertionError("hidden locator should not be clicked")

    class SubmitButton:
        @property
        def first(self):
            return self

        def __init__(self, page):
            self.page = page

        def is_visible(self, timeout=0):
            return True

        def is_enabled(self, timeout=0):
            return True

        def get_attribute(self, *_args, **_kwargs):
            return ""

        def click(self, *args, **kwargs):
            self.page.clicked_submit = True

    class FormLocator:
        @property
        def first(self):
            return self

        def __init__(self, page):
            self.page = page

        def get_by_role(self, *_args, **_kwargs):
            return HiddenLocator()

        def locator(self, selector):
            assert 'button[type="submit"]' in selector
            return SubmitButton(self.page)

    class Field:
        def __init__(self, page):
            self.page = page

        def locator(self, selector):
            assert selector == "xpath=ancestor::form[1]"
            return FormLocator(self.page)

        def press(self, key):
            self.page.pressed.append(key)

    class Page:
        def __init__(self):
            self.clicked_submit = False
            self.pressed = []

        def get_by_role(self, *_args, **_kwargs):
            return HiddenLocator()

    page = Page()

    assert _click_primary_auth_button(page, Field(page), ["Continue", "继续"]) is True
    assert page.clicked_submit is True
    assert page.pressed == []


def test_click_primary_auth_button_clicks_localized_page_button_before_enter():
    class HiddenLocator:
        @property
        def first(self):
            return self

        @property
        def last(self):
            return self

        def is_visible(self, timeout=0):
            return False

        def is_enabled(self, timeout=0):
            return False

        def get_attribute(self, *_args, **_kwargs):
            return ""

        def click(self, *args, **kwargs):
            raise AssertionError("hidden locator should not be clicked")

    class Field:
        def __init__(self, page):
            self.page = page

        def locator(self, selector):
            assert selector == "xpath=ancestor::form[1]"
            raise RuntimeError("no form ancestor")

        def press(self, key):
            self.page.pressed.append(key)

    class Page:
        def __init__(self):
            self.clicked_js = False
            self.pressed = []

        def get_by_role(self, *_args, **_kwargs):
            return HiddenLocator()

        def evaluate(self, script, arg):
            assert "続行" in arg["extraLabels"]
            self.clicked_js = True
            return "続行"

    page = Page()

    assert _click_primary_auth_button(page, Field(page), ["Continue", "继续"]) is True
    assert page.clicked_js is True
    assert page.pressed == []


def test_click_oauth_consent_clicks_continue_on_consent_page():
    class FakeLocator:
        def __init__(self, *, visible=False):
            self.visible = visible
            self.clicked = False
            self.first = self

        def is_visible(self, timeout=1000):
            return self.visible

        def is_enabled(self, timeout=1000):
            return True

        def scroll_into_view_if_needed(self, timeout=1000):
            pass

        def click(self, *args, **kwargs):
            self.clicked = True

    class FakePage:
        url = "https://auth.openai.com/sign-in-with-chatgpt/codex/consent"

        def __init__(self):
            self.hidden = FakeLocator(visible=False)
            self.button = FakeLocator(visible=True)

        def locator(self, selector):
            if "input" in selector and "submit" not in selector:
                return self.hidden
            if "Continue" in selector:
                return self.button
            return self.hidden

        def evaluate(self, *_args, **_kwargs):
            return ""

    page = FakePage()

    assert _click_oauth_consent_if_present(page, timeout=10) is True
    assert page.button.clicked is True


def test_click_oauth_consent_does_not_click_on_login_input_page():
    class FakeLocator:
        first = None

        def __init__(self, visible):
            self.visible = visible
            self.clicked = False
            self.first = self

        def is_visible(self, timeout=1000):
            return self.visible

        def is_enabled(self, timeout=1000):
            return True

        def click(self, *args, **kwargs):
            self.clicked = True

    class FakePage:
        url = "https://auth.openai.com/log-in"

        def __init__(self):
            self.input = FakeLocator(True)
            self.button = FakeLocator(True)

        def locator(self, selector):
            if "input" in selector and "submit" not in selector:
                return self.input
            return self.button

        def evaluate(self, *_args, **_kwargs):
            self.button.clicked = True
            return "continue"

    page = FakePage()

    assert _click_oauth_consent_if_present(page, timeout=10) is False
    assert page.button.clicked is False


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

    monkeypatch.setattr("autotoken.codex_auth._make_protocol_oauth_session", lambda: fake_session)
    monkeypatch.setattr("autotoken.codex_auth.secrets.token_urlsafe", lambda *_args, **_kwargs: "state")

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

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda items, email: account if email == account["email"] else None)

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
    monkeypatch.setattr("autotoken.mail.TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr("autotoken.codex_auth.login_codex_via_browser", fake_login)
    monkeypatch.setattr("autotoken.codex_auth.save_auth_file", lambda bundle: f"auths/codex-{bundle['email']}-plus.json")
    monkeypatch.setattr("autotoken.codex_auth.check_codex_quota", lambda token, account_id=None: ("ok", {"primary_pct": 1}))
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: updates.append((email, kwargs)))
    monkeypatch.setattr("autotoken.cpa_sync.sync_to_cpa", lambda: captured.setdefault("synced", True))

    result = api.post_account_login(api.LoginAccountParams(email=account["email"], protocol_only=False))
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
        and update.get("status") == accounts.STATUS_PLUS
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
    monkeypatch.setattr("autotoken.mail.TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr("autotoken.auth_session_store.load_auth_session", lambda _email: {"cookie_header": "session=1"})
    monkeypatch.setattr("autotoken.codex_auth.login_codex_via_auth_session_protocol", fail_protocol)
    monkeypatch.setattr("autotoken.codex_auth.login_codex_via_browser", fake_login)
    monkeypatch.setattr("autotoken.codex_auth.save_auth_file", lambda bundle: f"auths/{bundle['email']}.json")
    monkeypatch.setattr("autotoken.codex_auth.check_codex_quota", lambda token, account_id=None: ("ok", {}))
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: None)

    result = api._run_account_codex_login_once(account["email"], account)

    assert result["email"] == "plus@example.com"
    assert captured["login"] == {
        "email": "plus@example.com",
        "native_oauth": True,
        "mail_account_id": 956,
    }




def test_browser_oauth_refresh_auth_session_saves_bundle_token_without_session_fetch(monkeypatch):
    updates = []
    saved_sessions = []
    account = {
        "email": "plus@example.com",
        "password": "pw",
        "status": accounts.STATUS_ACTIVE,
        "account_type": accounts.ACCOUNT_TYPE_PLUS,
        "cloudmail_account_id": 956,
        "auth_file": "",
    }

    class FakeMailClient:
        def login(self):
            pass

    def fake_login(email, password, mail_client=None, **kwargs):
        assert kwargs.get("auth_session_callback") is None
        return {
            "email": email,
            "access_token": "codex-access",
            "refresh_token": "codex-refresh",
            "id_token": "id",
            "account_id": "acct-plus",
            "plan_type": "plus",
        }

    monkeypatch.delenv("CODEX_OAUTH_USE_AUTH_SESSION_PROTOCOL", raising=False)
    monkeypatch.setattr("autotoken.mail.TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr("autotoken.auth_session_store.load_auth_session", lambda _email: None)
    monkeypatch.setattr("autotoken.codex_auth.login_codex_via_browser", fake_login)
    monkeypatch.setattr(
        "autotoken.interfaces.manager._fetch_auth_session_from_page",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("不应再调用 /api/auth/session")),
    )
    monkeypatch.setattr(
        "autotoken.interfaces.manager._save_auth_from_session_page",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("不应依赖页面 session 保存")),
    )
    monkeypatch.setattr(
        "autotoken.auth_session_store.save_auth_session",
        lambda email, data: saved_sessions.append((email, data)) or f"session/{email}.json",
    )
    monkeypatch.setattr("autotoken.codex_auth.save_auth_file", lambda bundle: f"auths/{bundle['email']}.json")
    monkeypatch.setattr("autotoken.codex_auth.check_codex_quota", lambda token, account_id=None: ("ok", {}))
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: updates.append((email, kwargs)))

    result = api._run_account_codex_login_once(
        account["email"],
        account,
        refresh_auth_session=True,
        protocol_only=False,
        use_roxybrowser=True,
    )

    assert result["auth_session_file"] == "session/plus@example.com.json"
    assert saved_sessions == [
        (
            "plus@example.com",
            {
                "accessToken": "codex-access",
                "access_token": "codex-access",
                "chatgpt_access_token": "codex-access",
                "refreshToken": "codex-refresh",
                "refresh_token": "codex-refresh",
                "idToken": "id",
                "id_token": "id",
                "user": {"email": "plus@example.com"},
                "accountId": "acct-plus",
                "account": {"id": "acct-plus", "planType": "plus"},
                "planType": "plus",
                "plan_type": "plus",
            },
        )
    ]
    assert any(update.get("auth_file") == "auths/plus@example.com.json" for _email, update in updates)

def test_browser_oauth_success_updates_auth_session_from_bundle_without_page_session(monkeypatch):
    captured = {}
    updates = []
    saved_sessions = []
    account = {
        "email": "plus@example.com",
        "password": "pw",
        "status": accounts.STATUS_ACTIVE,
        "account_type": accounts.ACCOUNT_TYPE_PLUS,
        "cloudmail_account_id": 956,
        "auth_file": "",
    }

    class FakeMailClient:
        def login(self):
            pass

    def fake_login(email, password, mail_client=None, **kwargs):
        captured["login_kwargs"] = kwargs
        return {
            "email": email,
            "access_token": "codex-access",
            "refresh_token": "codex-refresh",
            "id_token": "id",
            "account_id": "acct-plus",
            "plan_type": "plus",
        }

    monkeypatch.delenv("CODEX_OAUTH_USE_AUTH_SESSION_PROTOCOL", raising=False)
    monkeypatch.setattr("autotoken.mail.TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr("autotoken.auth_session_store.load_auth_session", lambda _email: None)
    monkeypatch.setattr("autotoken.codex_auth.login_codex_via_browser", fake_login)
    monkeypatch.setattr(
        "autotoken.interfaces.manager._fetch_auth_session_from_page",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("不应再调用 /api/auth/session")),
    )
    monkeypatch.setattr(
        "autotoken.auth_session_store.save_auth_session",
        lambda email, data: saved_sessions.append((email, data)) or f"session/{email}.json",
    )
    monkeypatch.setattr("autotoken.codex_auth.save_auth_file", lambda bundle: f"auths/{bundle['email']}.json")
    monkeypatch.setattr("autotoken.codex_auth.check_codex_quota", lambda token, account_id=None: ("ok", {}))
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: updates.append((email, kwargs)))

    result = api._run_account_codex_login_once(
        account["email"],
        account,
        refresh_auth_session=True,
        protocol_only=False,
        use_roxybrowser=True,
    )

    assert "auth_session_callback" not in captured["login_kwargs"]
    assert result["auth_file"] == "auths/plus@example.com.json"
    assert result["auth_session_file"] == "session/plus@example.com.json"
    assert saved_sessions[0][1]["accessToken"] == "codex-access"
    assert saved_sessions[0][1]["refreshToken"] == "codex-refresh"
    assert any(update.get("auth_file") == "auths/plus@example.com.json" for _email, update in updates)

def test_account_login_uses_luckmail_provider_for_token_account_id(monkeypatch):
    captured = {}
    account = {
        "email": "plus@example.com",
        "password": "pw",
        "status": accounts.STATUS_ACTIVE,
        "account_type": accounts.ACCOUNT_TYPE_PLUS,
        "cloudmail_account_id": "tok_luck",
    }

    class FakeMailClient:
        def __init__(self):
            captured["mail_provider_env"] = os.environ.get("MAIL_PROVIDER")

        def login(self):
            pass

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
    monkeypatch.delenv("MAIL_PROVIDER", raising=False)
    monkeypatch.setattr("autotoken.mail.TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr("autotoken.auth_session_store.load_auth_session", lambda _email: None)
    monkeypatch.setattr("autotoken.codex_auth.login_codex_via_browser", fake_login)
    monkeypatch.setattr("autotoken.codex_auth.save_auth_file", lambda bundle: f"auths/{bundle['email']}.json")
    monkeypatch.setattr("autotoken.codex_auth.check_codex_quota", lambda token, account_id=None: ("ok", {}))
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: None)

    result = api._run_account_codex_login_once(account["email"], account)

    assert result["email"] == "plus@example.com"
    assert captured["mail_provider_env"] == "luckmail"
    assert captured["login"]["mail_account_id"] == "tok_luck"


def test_account_login_keeps_account_mail_provider_over_request_provider(monkeypatch):
    captured = {}
    account = {
        "email": "trentmelott5058@outlook.com",
        "password": "pw",
        "status": accounts.STATUS_ACTIVE,
        "account_type": accounts.ACCOUNT_TYPE_PLUS,
        "cloudmail_account_id": "outlook-mailbox-id",
        "mail_provider": "outlook",
    }

    class FakeMailClient:
        def __init__(self):
            captured["mail_provider_env"] = os.environ.get("MAIL_PROVIDER")

        def login(self):
            pass

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
    monkeypatch.delenv("MAIL_PROVIDER", raising=False)
    monkeypatch.setattr("autotoken.account_hub._restore_luckmail_tokens_for_accounts", lambda _rows: 0)
    monkeypatch.setattr("autotoken.mail.TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr("autotoken.auth_session_store.load_auth_session", lambda _email: None)
    monkeypatch.setattr("autotoken.codex_auth.login_codex_via_browser", fake_login)
    monkeypatch.setattr("autotoken.codex_auth.save_auth_file", lambda bundle: f"auths/{bundle['email']}.json")
    monkeypatch.setattr("autotoken.codex_auth.check_codex_quota", lambda token, account_id=None: ("ok", {}))
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: None)

    result = api._run_account_codex_login_once(account["email"], account, mail_provider="luckmail")

    assert result["email"] == "trentmelott5058@outlook.com"
    assert captured["mail_provider_env"] == "outlook"
    assert captured["login"]["mail_account_id"] == "outlook-mailbox-id"


def test_protocol_account_login_bind_phone_uses_saved_oauth_phone_config(monkeypatch):
    captured = {}
    account = {
        "email": "plus@example.com",
        "password": "pw",
        "status": accounts.STATUS_ACTIVE,
        "account_type": accounts.ACCOUNT_TYPE_PLUS,
        "cloudmail_account_id": "mail-id",
    }

    class FakeMailClient:
        def login(self):
            pass

    def fake_protocol_login(
        mail_client,
        *,
        email,
        password,
        account_id=None,
        proxy=None,
        oauth_phone_sms_provider=None,
        oauth_phone_sms_country=None,
        oauth_phone_sms_max_price=None,
        oauth_oasis_sms_cdks=None,
        totp_secret=None,
        progress_callback=None,
    ):
        captured["protocol_login"] = {
            "email": email,
            "account_id": account_id,
            "provider": oauth_phone_sms_provider,
            "country": oauth_phone_sms_country,
            "max_price": oauth_phone_sms_max_price,
            "oasis_cdks": oauth_oasis_sms_cdks,
        }
        return {
            "email": email,
            "account": {"id": "acct-session"},
            "codex_oauth_bundle": {
                "email": email,
                "access_token": "token",
                "refresh_token": "refresh",
                "id_token": "id",
                "account_id": "acct-plus",
                "plan_type": "plus",
            },
        }

    monkeypatch.setattr("autotoken.mail.TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr("autotoken.auth_session_store.load_auth_session", lambda _email: None)
    monkeypatch.setattr("autotoken.auth.protocol_register.login_once", fake_protocol_login)
    monkeypatch.setattr(
        api,
        "_oauth_phone_sms_env",
        lambda: {
            "provider": "smsbower",
            "smsbower_country": "187",
            "smsbower_max_price": "0.05",
        },
    )
    monkeypatch.setattr("autotoken.codex_auth.save_auth_file", lambda bundle: f"auths/{bundle['email']}.json")
    monkeypatch.setattr("autotoken.codex_auth.check_codex_quota", lambda token, account_id=None: ("ok", {}))
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: None)

    result = api._run_account_codex_login_once(account["email"], account, protocol_only=True, bind_phone=True)

    assert result["email"] == "plus@example.com"
    assert captured["protocol_login"] == {
        "email": "plus@example.com",
        "account_id": "mail-id",
        "provider": "smsbower",
        "country": "187",
        "max_price": "0.05",
        "oasis_cdks": "",
    }


def test_protocol_account_login_uses_saved_oauth_phone_config_without_bind_phone(monkeypatch):
    captured = {}
    account = {
        "email": "plus@example.com",
        "password": "pw",
        "status": accounts.STATUS_ACTIVE,
        "account_type": accounts.ACCOUNT_TYPE_PLUS,
        "cloudmail_account_id": "mail-id",
    }

    class FakeMailClient:
        def __init__(self):
            pass

        def login(self):
            pass

    def fake_protocol_login(mail_client, **kwargs):
        captured["protocol_login"] = kwargs
        return {
            "email": kwargs["email"],
            "account": {"id": "acct-session"},
            "codex_oauth_bundle": {
                "email": kwargs["email"],
                "access_token": "token",
                "refresh_token": "refresh",
                "id_token": "id",
                "account_id": "acct-plus",
                "plan_type": "plus",
            },
        }

    monkeypatch.setattr("autotoken.mail.TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr("autotoken.auth_session_store.load_auth_session", lambda _email: None)
    monkeypatch.setattr("autotoken.auth.protocol_register.login_once", fake_protocol_login)
    monkeypatch.setattr(
        api,
        "_oauth_phone_sms_env",
        lambda: {
            "provider": "hero_sms",
            "hero_sms_country": "187",
            "hero_sms_max_price": "0.04",
        },
    )
    monkeypatch.setattr("autotoken.codex_auth.save_auth_file", lambda bundle: f"auths/{bundle['email']}.json")
    monkeypatch.setattr("autotoken.codex_auth.check_codex_quota", lambda token, account_id=None: ("ok", {}))
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: None)

    result = api._run_account_codex_login_once(account["email"], account, protocol_only=True)

    assert result["email"] == "plus@example.com"
    assert captured["protocol_login"]["email"] == "plus@example.com"
    assert captured["protocol_login"]["account_id"] == "mail-id"
    assert captured["protocol_login"]["oauth_phone_sms_provider"] == "hero_sms"
    assert captured["protocol_login"]["oauth_phone_sms_country"] == "187"
    assert captured["protocol_login"]["oauth_phone_sms_max_price"] == "0.04"
    assert captured["protocol_login"]["oauth_oasis_sms_cdks"] == ""


def test_protocol_account_login_refresh_auth_session_saves_protocol_session(monkeypatch):
    saved_sessions = []
    account = {
        "email": "plus@example.com",
        "password": "pw",
        "status": accounts.STATUS_ACTIVE,
        "account_type": accounts.ACCOUNT_TYPE_PLUS,
        "cloudmail_account_id": "mail-id",
    }

    class FakeMailClient:
        def login(self):
            pass

    def fake_protocol_login(mail_client, **kwargs):
        return {
            "email": kwargs["email"],
            "data": {"accessToken": "chatgpt-token", "sessionToken": "session-token"},
            "account": {"id": "acct-session"},
            "codex_oauth_bundle": {
                "email": kwargs["email"],
                "access_token": "codex-access",
                "refresh_token": "codex-refresh",
                "id_token": "id",
                "account_id": "acct-plus",
                "plan_type": "plus",
            },
        }

    monkeypatch.setattr("autotoken.mail.TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr("autotoken.auth_session_store.load_auth_session", lambda _email: None)
    monkeypatch.setattr("autotoken.auth_session_store.save_auth_session", lambda email, data: saved_sessions.append((email, data)) or f"session/{email}.json")
    monkeypatch.setattr("autotoken.auth.protocol_register.login_once", fake_protocol_login)
    monkeypatch.setattr("autotoken.codex_auth.save_auth_file", lambda bundle: f"auths/{bundle['email']}.json")
    monkeypatch.setattr("autotoken.codex_auth.check_codex_quota", lambda token, account_id=None: ("ok", {}))
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: None)

    result = api._run_account_codex_login_once(account["email"], account, protocol_only=True, refresh_auth_session=True)

    assert result["email"] == "plus@example.com"
    assert result["auth_session_file"] == "session/plus@example.com.json"
    assert saved_sessions[0][0] == "plus@example.com"
    assert saved_sessions[0][1]["data"]["accessToken"] == "chatgpt-token"


def test_protocol_account_login_auth_session_only_does_not_require_codex_bundle(monkeypatch):
    saved_sessions = []
    account = {
        "email": "plain@example.com",
        "password": "pw",
        "status": accounts.STATUS_ACTIVE,
        "account_type": accounts.ACCOUNT_TYPE_PLUS,
        "cloudmail_account_id": "mail-id",
    }

    class FakeMailClient:
        def login(self):
            pass

    def fake_protocol_login(mail_client, **kwargs):
        return {
            "email": kwargs["email"],
            "data": {
                "accessToken": "chatgpt-token",
                "sessionToken": "session-token",
                "account": {"id": "acct-session", "planType": "plus"},
            },
        }

    monkeypatch.setenv("AUTH_SESSION_ONLY", "1")
    monkeypatch.setattr("autotoken.mail.TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr("autotoken.auth_session_store.load_auth_session", lambda _email: None)
    monkeypatch.setattr(
        "autotoken.auth_session_store.save_auth_session",
        lambda email, data: saved_sessions.append((email, data)) or f"session/{email}.json",
    )
    monkeypatch.setattr("autotoken.auth.protocol_register.login_once", fake_protocol_login)
    monkeypatch.setattr(
        "autotoken.codex_auth.login_codex_via_browser",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("auth_session-only 不应打开浏览器 OAuth")),
    )
    monkeypatch.setattr("autotoken.codex_auth.save_auth_file", lambda _bundle: (_ for _ in ()).throw(AssertionError("auth_session-only 不应保存 Codex auth_file")))
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: None)

    result = api._run_account_codex_login_once(
        account["email"],
        account,
        protocol_only=True,
        refresh_auth_session=True,
    )

    assert result["email"] == "plain@example.com"
    assert result["auth_session_file"] == "session/plain@example.com.json"
    assert result["codex_auth_updated"] is False
    assert saved_sessions[0][1]["data"]["accessToken"] == "chatgpt-token"


def test_protocol_account_login_auth_session_only_env_does_not_leak_into_other_thread(monkeypatch):
    saved_sessions = []
    account = {
        "email": "plain@example.com",
        "password": "pw",
        "status": accounts.STATUS_ACTIVE,
        "account_type": accounts.ACCOUNT_TYPE_PLUS,
        "cloudmail_account_id": "mail-id",
    }

    class FakeMailClient:
        def login(self):
            pass

    def fake_protocol_login(_mail_client, **kwargs):
        if kwargs["email"] == "plain@example.com":
            return {
                "email": kwargs["email"],
                "data": {"accessToken": "chatgpt-token", "sessionToken": "session-token"},
            }
        return {
            "email": kwargs["email"],
            "data": {"accessToken": "chatgpt-token", "sessionToken": "session-token"},
            "codex_oauth_bundle": {
                "email": kwargs["email"],
                "access_token": "codex-access",
                "refresh_token": "codex-refresh",
                "id_token": "id",
                "account_id": "acct-plus",
                "plan_type": "plus",
            },
        }

    monkeypatch.setattr("autotoken.mail.TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr("autotoken.auth_session_store.load_auth_session", lambda _email: None)
    monkeypatch.setattr(
        "autotoken.auth_session_store.save_auth_session",
        lambda email, data: saved_sessions.append((email, data)) or f"session/{email}.json",
    )
    monkeypatch.setattr("autotoken.auth.protocol_register.login_once", fake_protocol_login)
    monkeypatch.setattr("autotoken.codex_auth.save_auth_file", lambda bundle: f"auths/{bundle['email']}.json")
    monkeypatch.setattr("autotoken.codex_auth.check_codex_quota", lambda token, account_id=None: ("ok", {}))
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: None)

    result = api._run_account_codex_login_once(
        account["email"],
        account,
        protocol_only=True,
        refresh_auth_session=True,
    )

    assert result["email"] == "plain@example.com"
    assert result["auth_session_file"] == "session/plain@example.com.json"


def test_refresh_auth_session_with_codex_auth_file_forces_protocol_oauth(monkeypatch):
    account = {
        "email": "plus@example.com",
        "password": "pw",
        "status": accounts.STATUS_ACTIVE,
        "account_type": accounts.ACCOUNT_TYPE_PLUS,
        "auth_file": "auths/codex-plus@example.com-plus.json",
    }
    captured = {}

    class FakeMailClient:
        def login(self):
            pass

    def fake_protocol_login(mail_client, **kwargs):
        captured["protocol_login"] = kwargs
        return {
            "email": kwargs["email"],
            "data": {"accessToken": "chatgpt-token"},
            "codex_oauth_bundle": {
                "email": kwargs["email"],
                "access_token": "codex-access",
                "refresh_token": "codex-refresh",
                "id_token": "id",
                "account_id": "acct-plus",
                "plan_type": "plus",
            },
        }

    def fail_browser(*_args, **_kwargs):
        raise AssertionError("有 Codex auth 文件的补登录不应打开 Playwright/浏览器 OAuth")

    monkeypatch.setattr("autotoken.mail.TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr("autotoken.auth_session_store.load_auth_session", lambda _email: None)
    monkeypatch.setattr("autotoken.auth_session_store.save_auth_session", lambda email, _data: f"session/{email}.json")
    monkeypatch.setattr("autotoken.auth.protocol_register.login_once", fake_protocol_login)
    monkeypatch.setattr("autotoken.codex_auth.login_codex_via_browser", fail_browser)
    monkeypatch.setattr("autotoken.codex_auth.save_auth_file", lambda bundle: f"auths/{bundle['email']}.json")
    monkeypatch.setattr("autotoken.codex_auth.check_codex_quota", lambda token, account_id=None: ("ok", {}))
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: None)

    result = api._run_account_codex_login_once(
        account["email"],
        account,
        protocol_only=False,
        refresh_auth_session=True,
    )

    assert captured["protocol_login"]["email"] == "plus@example.com"
    assert result["auth_file"] == "auths/plus@example.com.json"


def test_account_login_restores_missing_luckmail_token_before_browser_oauth(monkeypatch):
    captured = {}
    account = {
        "email": "plus@outlook.com",
        "password": "pw",
        "status": accounts.STATUS_ACTIVE,
        "account_type": accounts.ACCOUNT_TYPE_PLUS,
        "cloudmail_account_id": None,
        "mail_provider": "luckmail",
    }

    class FakeMailClient:
        def __init__(self):
            captured["mail_provider_env"] = os.environ.get("MAIL_PROVIDER")

        def login(self):
            pass

    def fake_restore(rows):
        rows[0]["cloudmail_account_id"] = "tok_restored"
        rows[0]["mail_provider"] = "luckmail"
        return 1

    def fake_update(email, **kwargs):
        captured.setdefault("updates", []).append((email, kwargs))

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
    monkeypatch.delenv("MAIL_PROVIDER", raising=False)
    monkeypatch.setattr("autotoken.account_hub._restore_luckmail_tokens_for_accounts", fake_restore)
    monkeypatch.setattr("autotoken.mail.TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr("autotoken.auth_session_store.load_auth_session", lambda _email: None)
    monkeypatch.setattr("autotoken.codex_auth.login_codex_via_browser", fake_login)
    monkeypatch.setattr("autotoken.codex_auth.save_auth_file", lambda bundle: f"auths/{bundle['email']}.json")
    monkeypatch.setattr("autotoken.codex_auth.check_codex_quota", lambda token, account_id=None: ("ok", {}))
    monkeypatch.setattr("autotoken.accounts.update_account", fake_update)

    result = api._run_account_codex_login_once(account["email"], account)

    assert result["email"] == "plus@outlook.com"
    assert captured["mail_provider_env"] == "luckmail"
    assert captured["login"]["mail_account_id"] == "tok_restored"
    assert captured["updates"][0] == (
        "plus@outlook.com",
        {"cloudmail_account_id": "tok_restored", "mail_provider": "luckmail"},
    )


def test_team_account_login_keeps_team_oauth(monkeypatch):
    captured = {}
    account = {
        "email": "team@example.com",
        "password": "pw",
        "status": accounts.STATUS_STANDBY,
        "account_type": accounts.ACCOUNT_TYPE_TEAM,
    }

    monkeypatch.setattr("autotoken.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.accounts.find_account", lambda items, email: account if email == account["email"] else None)
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

    monkeypatch.setattr("autotoken.mail.TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr("autotoken.codex_auth.login_codex_via_browser", fake_login)
    monkeypatch.setattr("autotoken.codex_auth.save_auth_file", lambda bundle: "auths/codex-team@example.com-team.json")
    monkeypatch.setattr("autotoken.codex_auth.check_codex_quota", lambda token, account_id=None: ("ok", {}))
    monkeypatch.setattr("autotoken.accounts.update_account", lambda email, **kwargs: None)
    monkeypatch.setattr("autotoken.cpa_sync.sync_to_cpa", lambda: None)

    api.post_account_login(api.LoginAccountParams(email=account["email"], protocol_only=False))
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


def test_register_accounts_sms_max_price_does_not_serialize_workers(monkeypatch):
    import threading
    import time

    active = 0
    max_active = 0
    lock = threading.Lock()
    captured = []

    class FakeMailClient:
        def login(self):
            pass

    def fake_create_account_direct(mail_client, **kwargs):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.05)
            captured.append(kwargs)
            kwargs["out_outcome"].update(status="success", email=f"phone-{len(captured)}")
            return {"status": "success", "email": f"phone-{len(captured)}"}
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(manager, "TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr(manager, "create_account_direct", fake_create_account_direct)

    result = manager.cmd_register_accounts(
        count=4,
        concurrency=4,
        interval_seconds=0,
        jitter_min_seconds=0,
        jitter_max_seconds=0,
        registration_flow="phone_cpa",
        register_mode="protocol",
        oauth_phone_sms_provider="hero_sms",
        oauth_phone_sms_max_price="0.05",
        phone_only=True,
    )

    assert result["ok"] == 4
    assert max_active > 1
    assert {call["oauth_phone_sms_max_price"] for call in captured} == {"0.05"}


def test_register_accounts_retries_dynamic_proxy_when_probe_fails(monkeypatch):
    captured = {}
    progress_events = []
    proxies = iter(["http://bad-proxy.example:7001", "http://good-proxy.example:7002"])
    class ProbeResp:
        status_code = 200

        @staticmethod
        def json():
            return {"csrfToken": "csrf-ok"}

    probe_results = iter([RuntimeError("Proxy CONNECT aborted"), ProbeResp()])

    class FakeMailClient:
        def login(self):
            captured["mail_login"] = True

    class FakeSession:
        def get(self, _url, headers=None, timeout=0):
            result = next(probe_results)
            if isinstance(result, Exception):
                raise result
            return result

    def fake_create_account_direct(mail_client, **kwargs):
        captured["kwargs"] = kwargs
        kwargs["out_outcome"].update(status="success", email="proxy@example.com")
        return "proxy@example.com"

    monkeypatch.setattr(manager, "TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr(manager, "create_account_direct", fake_create_account_direct)
    monkeypatch.setattr("autotoken._protocol_register.http_client.create_http_session", lambda **_kwargs: FakeSession())

    result = manager.cmd_register_accounts(
        count=1,
        concurrency=1,
        interval_seconds=0,
        jitter_min_seconds=0,
        jitter_max_seconds=0,
        register_proxy_selector=lambda: next(proxies),
        register_proxy_meta={"proxy_api_provider": "cliproxy", "proxy_api_url_present": True},
        progress_callback=progress_events.append,
    )

    assert result["ok"] == 1
    assert captured["kwargs"]["proxy_url"] == "http://good-proxy.example:7002"
    assert [event["stage"] for event in progress_events].count("register_proxy_api_probe_failed") == 1
    assert any(event["stage"] == "register_proxy_api_selected" and event["proxy_attempt"] == 2 for event in progress_events)


def test_direct_register_continue_labels_include_japanese_locale():
    assert "続行" in manager._DIRECT_CONTINUE_LABELS
    assert "続行" in manager._DIRECT_PASSWORD_CONTINUE_LABELS
    assert "続行" in manager._DIRECT_CODE_CONTINUE_LABELS
    assert "続行" in manager._DIRECT_ABOUT_YOU_BUTTON_TEXTS


def test_roxybrowser_register_dynamic_proxy_skips_http_csrf_probe(monkeypatch):
    captured = {}
    progress_events = []
    proxies = iter(["http://proxy-roxy.example:7001"])

    class FakeMailClient:
        def login(self):
            captured["mail_login"] = True

    def fake_create_account_direct(mail_client, **kwargs):
        captured["kwargs"] = kwargs
        kwargs["out_outcome"].update(status="success", email="roxy@example.com")
        return "roxy@example.com"

    def fail_create_http_session(**_kwargs):
        raise AssertionError("RoxyBrowser registration should not use HTTP csrf proxy probe")

    monkeypatch.setattr(manager, "TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr(manager, "create_account_direct", fake_create_account_direct)
    monkeypatch.setattr("autotoken._protocol_register.http_client.create_http_session", fail_create_http_session)

    result = manager.cmd_register_accounts(
        count=1,
        concurrency=1,
        interval_seconds=0,
        jitter_min_seconds=0,
        jitter_max_seconds=0,
        register_proxy_selector=lambda: next(proxies),
        register_proxy_meta={"proxy_api_provider": "cliproxy", "proxy_api_url_present": True},
        use_roxybrowser=True,
        progress_callback=progress_events.append,
    )

    assert result["ok"] == 1
    assert captured["kwargs"]["proxy_url"] == "http://proxy-roxy.example:7001"
    assert captured["kwargs"]["use_roxybrowser"] is True
    assert not any(event["stage"] == "register_proxy_api_probe_failed" for event in progress_events)
    assert any(event["stage"] == "register_proxy_api_selected" and event["proxy_attempt"] == 1 for event in progress_events)


def test_register_accounts_stops_after_risky_failure_burst(monkeypatch):
    calls = []
    progress_events = []

    class FakeMailClient:
        def login(self):
            pass

    def fake_create_account_direct(mail_client, **kwargs):
        calls.append(kwargs)
        kwargs["out_outcome"].update(
            status="account_deactivated",
            reason="OpenAI 返回 account_deactivated",
        )
        return None

    monkeypatch.setenv("REGISTER_RISK_BREAKER_CONSECUTIVE_FAILURES", "2")
    monkeypatch.setattr(manager, "TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr(manager, "create_account_direct", fake_create_account_direct)

    result = manager.cmd_register_accounts(
        count=4,
        concurrency=1,
        interval_seconds=0,
        jitter_min_seconds=0,
        jitter_max_seconds=0,
        progress_callback=progress_events.append,
    )

    assert len(calls) == 2
    assert result["ok"] == 0
    assert result["failed"] == 4
    assert result["circuit_breaker_triggered"] is True
    assert result["results"][2]["status"] == "skipped_circuit_breaker"
    assert result["results"][3]["status"] == "skipped_circuit_breaker"
    assert any(event["stage"] == "register_circuit_breaker_opened" for event in progress_events)
