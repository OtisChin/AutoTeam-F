import base64
import importlib
import json
import logging
import sys
from pathlib import Path


def _load_auth_flow_module():
    protocol_dir = Path(__file__).resolve().parents[2] / "src" / "autotoken" / "_protocol_register"
    protocol_dir_str = str(protocol_dir)
    if protocol_dir_str not in sys.path:
        sys.path.insert(0, protocol_dir_str)
    return importlib.import_module("auth_flow")


def _jwt(payload: dict) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    return f"header.{encoded}.sig"


def _b64url_json(payload: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")


def test_phone_otp_command_args_accepts_json_argv_and_quoted_command():
    auth_flow = _load_auth_flow_module()

    assert auth_flow.AuthFlow._phone_otp_command_args('["python", "-c", "print(123456)"]') == [
        "python",
        "-c",
        "print(123456)",
    ]
    assert auth_flow.AuthFlow._phone_otp_command_args('python -c "print(123456)"') == [
        "python",
        "-c",
        "print(123456)",
    ]


def test_read_phone_otp_from_cmd_executes_without_shell(monkeypatch):
    auth_flow = _load_auth_flow_module()
    captured = {}

    class FakeConfig:
        proxy = None

    def fake_check_output(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return "OTP 123456"

    monkeypatch.setenv("OPENAI_PHONE_OTP_CMD", '["otp-tool", "--latest"]')
    monkeypatch.setattr(auth_flow.subprocess, "check_output", fake_check_output)

    flow = auth_flow.AuthFlow(FakeConfig())

    assert flow._read_phone_otp_from_cmd() == "123456"
    assert captured["args"] == ["otp-tool", "--latest"]
    assert captured["kwargs"] == {"text": True, "timeout": 20}


def test_get_auth_session_captures_account_metadata():
    auth_flow = _load_auth_flow_module()

    class FakeConfig:
        proxy = None

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "accessToken": "chatgpt-access",
                "account": {
                    "id": "acct-plus",
                    "planType": "plus",
                },
            }

    class FakeSession:
        def get(self, *_args, **_kwargs):
            return FakeResponse()

    flow = auth_flow.AuthFlow(FakeConfig())
    flow.session = FakeSession()
    flow._extract_chatgpt_session_token = lambda: "chatgpt-session"
    flow._build_chatgpt_cookie_header = lambda: "session-cookie"
    flow._trace_http = lambda *_args, **_kwargs: None

    flow.get_auth_session()

    assert flow.result.account_id == "acct-plus"
    assert flow.result.plan_type == "plus"
    assert flow.result.chatgpt_access_token == "chatgpt-access"


def test_oauth_token_exchange_summarizes_candidate_failures(caplog):
    auth_flow = _load_auth_flow_module()

    class FakeConfig:
        proxy = None

    class FakeResponse:
        status_code = 400
        text = '{"error":{"code":"token_exchange_user_error"}}'

    class FakeSession:
        def __init__(self):
            self.posts = []

        def post(self, url, **kwargs):
            self.posts.append((url, kwargs))
            return FakeResponse()

    flow = auth_flow.AuthFlow(FakeConfig())
    flow.session = FakeSession()
    flow._trace_http = lambda *_args, **_kwargs: None
    flow._sniff_login_verifier = lambda *_args, **_kwargs: None
    flow._collect_code_verifier_candidates = lambda *_args, **_kwargs: [("captured", "verifier-1")]

    caplog.set_level(logging.WARNING, logger=auth_flow.logger.name)

    assert flow.oauth_token_exchange(
        "https://chatgpt.com/api/auth/callback/openai?code=auth-code",
        "",
    ) is False

    warnings = [record.getMessage() for record in caplog.records if record.levelno >= logging.WARNING]
    assert warnings == [
        "Token 交换兜底失败: 已尝试 2 种模式，最后失败 mode=without_verifier status=400 body=400: token_exchange_user_error"
    ]
    assert "Token 交换失败(mode=" not in "\n".join(warnings)


def test_add_phone_fraud_guard_is_phone_rate_limited():
    auth_flow = _load_auth_flow_module()

    reason = (
        "add-phone/send 失败: 400: fraud_guard: We've detected suspicious behavior "
        "from phone numbers similar to yours."
    )

    assert auth_flow._is_add_phone_rate_limited_error(reason) is True


def test_email_otp_verify_retries_three_attempts_after_wrong_code(monkeypatch):
    auth_flow = _load_auth_flow_module()

    class FakeConfig:
        proxy = None

    flow = auth_flow.AuthFlow(FakeConfig())
    monkeypatch.setenv("OPENAI_EMAIL_OTP_VERIFY_MAX_ATTEMPTS", "3")
    verify_codes = []
    wait_calls = []
    delivery_modes = []
    dumps = []

    def fake_verify(code):
        verify_codes.append(code)
        if len(verify_codes) < 3:
            raise RuntimeError("OTP 验证失败: 401: wrong_email_otp_code")
        return {"continue_url": "https://chatgpt.com"}

    def fake_wait(*_args, **kwargs):
        wait_calls.append(kwargs)
        return f"retry-code-{len(wait_calls)}"

    flow.verify_otp = fake_verify
    flow._wait_for_email_otp = fake_wait
    flow.kickoff_otp_delivery = lambda mode="": delivery_modes.append(mode) or True
    flow.fetch_client_auth_session_dump = lambda stage="": dumps.append(stage)

    assert flow._verify_email_otp_with_retries(
        object(),
        "user@example.com",
        "initial-code",
        otp_timeout=60,
        retry_mode="protocol_verify_retry",
        dump_stage="post_verify_otp_protocol",
    ) == {"continue_url": "https://chatgpt.com"}

    assert verify_codes == ["initial-code", "retry-code-1", "retry-code-2"]
    assert delivery_modes == ["protocol_verify_retry", "protocol_verify_retry_2"]
    assert len(wait_calls) == 2
    assert all(call["exclude_used"] is True for call in wait_calls)
    assert dumps == ["post_verify_otp_protocol_retry_2"]


def test_protocol_mail_adapter_waits_before_first_email_otp_query(monkeypatch):
    from autotoken.auth import protocol_register

    events = []

    class FakeMailClient:
        def search_emails_by_recipient(self, *_args, **_kwargs):
            events.append("search")
            return [{"subject": "OpenAI code"}]

        def extract_verification_code(self, _item):
            return "123456"

    monkeypatch.setenv("OPENAI_EMAIL_OTP_INITIAL_DELAY", "3")
    monkeypatch.setattr(protocol_register.time, "time", lambda: 1_000.0)
    monkeypatch.setattr(protocol_register.time, "sleep", lambda seconds: events.append(("sleep", seconds)))

    adapter = protocol_register.ProtocolMailAdapter(FakeMailClient(), email="user@example.com")

    assert adapter.wait_for_otp("user@example.com", timeout=60) == "123456"
    assert events[:2] == [("sleep", 3.0), "search"]


def test_phone_first_oauth_failure_preserves_specific_error(monkeypatch):
    auth_flow = _load_auth_flow_module()

    class FakeSession:
        pass

    class FakeConfig:
        proxy = None

    flow = auth_flow.AuthFlow(FakeConfig())
    flow.session = FakeSession()
    flow.check_proxy = lambda: True
    flow.get_csrf_token = lambda: "csrf"
    flow.get_auth_url = lambda _csrf: "https://auth.openai.test/authorize"
    flow.auth_oauth_init = lambda _url: "device"
    flow.get_sentinel_token = lambda _device_id: "sentinel"
    flow.authorize_continue = lambda **_kwargs: {
        "page": {"type": "create_account_password"},
        "continue_url": "https://auth.openai.com/create-account/password",
    }
    flow.register_password = lambda _phone: True
    flow._phone_signup_send_otp = lambda: {}
    flow._phone_otp_validate = lambda _code: {"continue_url": "https://auth.openai.com/about-you"}
    flow.create_account = lambda: "https://chatgpt.com"
    flow.oauth_codex_rt_exchange = lambda mail_provider=None: False
    flow._last_codex_oauth_error = "LuckMail 购买邮箱失败: {'code': 2001, 'message': '余额不足'}"

    captured_timeout = {}
    def fake_phone_otp_reader(_item, timeout):
        captured_timeout["timeout"] = timeout
        return "123456"

    flow._openai_phone_supplier = lambda: {"phone_number": "+15551234567"}
    flow._openai_phone_otp_reader = fake_phone_otp_reader
    flow._openai_phone_success = lambda _item: None
    flow._openai_phone_failure = lambda _item, _reason="": None

    try:
        flow.run_phone_first_register(mail_provider=object())
    except RuntimeError as exc:
        assert "LuckMail 购买邮箱失败" in str(exc)
        assert "余额不足" in str(exc)
    else:
        raise AssertionError("expected specific OAuth failure")

    assert captured_timeout["timeout"] == 60


def test_phone_first_failure_callback_receives_specific_error(monkeypatch):
    auth_flow = _load_auth_flow_module()

    class FakeConfig:
        proxy = None

    flow = auth_flow.AuthFlow(FakeConfig())
    flow.check_proxy = lambda: True
    flow.get_csrf_token = lambda: "csrf"
    flow.get_auth_url = lambda _csrf: "https://auth.openai.test/authorize"
    flow.auth_oauth_init = lambda _url: "device"
    flow.get_sentinel_token = lambda _device_id: "sentinel"
    flow.authorize_continue = lambda **_kwargs: (_ for _ in ()).throw(
        RuntimeError("PHONE_ALREADY_REGISTERED: 手机号已注册或进入登录页")
    )

    reasons = []
    flow._openai_phone_supplier = lambda: {"phone_number": "+15551234567"}
    flow._openai_phone_failure = lambda _item, reason="": reasons.append(reason)
    monkeypatch.setenv("OPENAI_PHONE_FIRST_PHONE_ATTEMPTS", "1")

    try:
        flow.run_phone_first_register(mail_provider=object())
    except RuntimeError as exc:
        assert "PHONE_ALREADY_REGISTERED" in str(exc)
    else:
        raise AssertionError("expected phone-first failure")

    assert len(reasons) == 1
    assert "PHONE_ALREADY_REGISTERED" in reasons[0]


def test_add_phone_verification_hero_sms_no_numbers_does_not_fallback_to_env(monkeypatch):
    auth_flow = _load_auth_flow_module()

    class FakeConfig:
        proxy = None

    flow = auth_flow.AuthFlow(FakeConfig())
    flow._is_add_phone_page = lambda _page: True
    flow._openai_phone_provider = "hero_sms"
    flow._openai_phone_supplier = lambda: []

    monkeypatch.setenv("OPENAI_PHONE_NUMBER", "+15550000000")

    try:
        flow._handle_add_phone_verification("https://auth.openai.com/add-phone")
    except Exception as exc:
        assert "hero-sms" in str(exc).lower()
    else:
        raise AssertionError("expected hero-sms no-number failure")


def test_add_phone_verification_reacquire_path_handles_dynamic_phone_item_lists(monkeypatch):
    auth_flow = _load_auth_flow_module()

    class FakeConfig:
        proxy = None

    class FakePage:
        url = "https://auth.openai.com/add-phone"

        def reload(self, **_kwargs):
            return None

    state = {"calls": 0}

    def fake_supplier():
        state["calls"] += 1
        if state["calls"] == 1:
            return [{"phone_number": "+15551234567", "source": "hero_sms", "activation_id": "act-1"}]
        return []

    flow = auth_flow.AuthFlow(FakeConfig())
    flow._is_add_phone_page = lambda _page: True
    flow._openai_phone_provider = "hero_sms"
    flow._openai_phone_supplier = fake_supplier
    flow._add_phone_send = lambda _phone: {"page": {"type": "phone_otp_verification"}, "continue_url": "https://auth.openai.com/add-phone"}
    flow._extract_page_type = lambda _resp: "phone_otp_verification"
    flow._extract_continue_url_from_step = lambda _resp: "https://auth.openai.com/add-phone"
    flow._normalize_continue_url = lambda url: url
    flow._phone_otp_input_locator = lambda: object()
    flow._wait_phone_otp = lambda *_args, **_kwargs: "123456"
    flow._phone_otp_validate = lambda _code: (_ for _ in ()).throw(RuntimeError("PHONE_NUMBER_IN_USE"))
    flow._phone_otp_resend = lambda: None

    monkeypatch.setattr(auth_flow.time, "sleep", lambda *_args, **_kwargs: None)

    result = flow._handle_add_phone_verification("https://auth.openai.com/add-phone")

    assert result == "https://auth.openai.com/add-phone"
    assert state["calls"] >= 2


def test_add_phone_verification_oasis_no_numbers_reports_supplier_error(monkeypatch):
    auth_flow = _load_auth_flow_module()

    class FakeConfig:
        proxy = None

    flow = auth_flow.AuthFlow(FakeConfig())
    flow._openai_phone_provider = "oasis"
    flow._openai_phone_supplier = lambda: (_ for _ in ()).throw(RuntimeError("CDK已过期"))

    monkeypatch.setenv("OPENAI_PHONE_NUMBER", "+15550000000")

    try:
        flow._handle_add_phone_verification("https://auth.openai.com/add-phone")
    except Exception as exc:
        assert "CDK已过期" in str(exc)
    else:
        raise AssertionError("expected oasis supplier failure")


def test_add_phone_verification_preserves_dynamic_timeout_reason(monkeypatch):
    auth_flow = _load_auth_flow_module()

    class FakeConfig:
        proxy = None

    state = {"calls": 0}

    def fake_supplier():
        state["calls"] += 1
        return [
            {
                "phone_number": f"+2761000000{state['calls']}",
                "source": "hero_sms",
                "activation_id": f"act-timeout-{state['calls']}",
            }
        ]

    flow = auth_flow.AuthFlow(FakeConfig())
    flow._openai_phone_provider = "hero_sms"
    flow._openai_phone_supplier = fake_supplier
    flow._openai_phone_failure = lambda _item, _reason="": None
    flow._add_phone_send = lambda _phone: {
        "page": {"type": "phone_otp_verification"},
        "continue_url": "https://auth.openai.com/add-phone",
    }
    flow._extract_page_type = lambda resp: (resp.get("page") or {}).get("type", "")
    flow._extract_continue_url_from_step = lambda resp: resp.get("continue_url", "")
    flow._normalize_continue_url = lambda url: url
    flow._wait_phone_otp = lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("等待手机 OTP 超时 (60s)"))
    flow._phone_otp_resend = lambda: None

    monkeypatch.setenv("OPENAI_PHONE_DYNAMIC_MAX_ATTEMPTS", "2")
    monkeypatch.setattr(auth_flow.time, "sleep", lambda *_args, **_kwargs: None)

    result = flow._handle_add_phone_verification("https://auth.openai.com/add-phone")

    assert result == "https://auth.openai.com/add-phone"
    assert state["calls"] == 2
    assert "等待手机 OTP 超时" in flow._last_codex_oauth_error


def test_add_phone_verification_dynamic_phone_attempts_default_to_three(monkeypatch):
    auth_flow = _load_auth_flow_module()

    class FakeConfig:
        proxy = None

    state = {"calls": 0}

    def fake_supplier():
        state["calls"] += 1
        return [
            {
                "phone_number": f"+1555123000{state['calls']}",
                "source": "hero_sms",
                "activation_id": f"act-{state['calls']}",
            }
        ]

    flow = auth_flow.AuthFlow(FakeConfig())
    flow._openai_phone_provider = "hero_sms"
    flow._openai_phone_supplier = fake_supplier
    flow._add_phone_send = lambda _phone: {"page": {"type": "phone_otp_verification"}, "continue_url": "https://auth.openai.com/add-phone"}
    flow._extract_page_type = lambda _resp: "phone_otp_verification"
    flow._extract_continue_url_from_step = lambda _resp: "https://auth.openai.com/add-phone"
    flow._normalize_continue_url = lambda url: url
    flow._wait_phone_otp = lambda *_args, **_kwargs: "123456"
    flow._phone_otp_validate = lambda _code: (_ for _ in ()).throw(RuntimeError("PHONE_NUMBER_IN_USE"))
    flow._phone_otp_resend = lambda: None

    monkeypatch.delenv("OPENAI_PHONE_DYNAMIC_MAX_ATTEMPTS", raising=False)
    monkeypatch.setattr(auth_flow.time, "sleep", lambda *_args, **_kwargs: None)

    result = flow._handle_add_phone_verification("https://auth.openai.com/add-phone")

    assert result == "https://auth.openai.com/add-phone"
    assert state["calls"] == 3


def test_add_phone_verification_retries_new_number_when_sms_switches_to_whatsapp(monkeypatch):
    auth_flow = _load_auth_flow_module()

    class FakeConfig:
        proxy = None

    state = {"calls": 0}
    failures = []

    def fake_supplier():
        state["calls"] += 1
        return [
            {
                "phone_number": f"+2761000000{state['calls']}",
                "source": "hero_sms",
                "activation_id": f"act-whatsapp-{state['calls']}",
            }
        ]

    send_responses = [
        {
            "page": {
                "type": "add_phone",
                "payload": {
                    "message": "我们无法向该电话号码发送短信，因此已切换为 WhatsApp。请继续通过 WhatsApp 发送验证码。"
                },
            }
        },
        {"page": {"type": "phone_otp_verification"}, "continue_url": "https://auth.openai.com/add-phone"},
    ]

    flow = auth_flow.AuthFlow(FakeConfig())
    flow._openai_phone_provider = "hero_sms"
    flow._openai_phone_supplier = fake_supplier
    flow._openai_phone_failure = lambda item, reason="": failures.append((item["activation_id"], reason))
    flow._openai_phone_success = lambda _item: None
    flow._add_phone_send = lambda _phone: send_responses.pop(0)
    flow._extract_page_type = lambda resp: (resp.get("page") or {}).get("type", "")
    flow._extract_continue_url_from_step = lambda resp: resp.get("continue_url", "")
    flow._normalize_continue_url = lambda url: url
    flow._wait_phone_otp = lambda *_args, **_kwargs: "123456"
    flow._phone_otp_validate = lambda _code: {"continue_url": "https://chatgpt.com"}

    monkeypatch.setattr(auth_flow.time, "sleep", lambda *_args, **_kwargs: None)

    result = flow._handle_add_phone_verification("https://auth.openai.com/add-phone")

    assert result == "https://chatgpt.com"
    assert state["calls"] == 2
    assert failures and failures[0][0] == "act-whatsapp-1"
    assert "WHATSAPP_FALLBACK" in failures[0][1]


def test_new_protocol_register_uses_unified_email_otp_delivery(monkeypatch):
    auth_flow = _load_auth_flow_module()

    class FakeConfig:
        proxy = None

    class FakeMailProvider:
        def create_mailbox(self):
            return "fresh@outlook.my"

    flow = auth_flow.AuthFlow(FakeConfig())
    flow.check_proxy = lambda: True
    flow.get_csrf_token = lambda: "csrf"
    flow.get_auth_url = lambda _csrf: "https://auth.openai.test/authorize"
    flow.auth_oauth_init = lambda _url: "device"
    flow.get_sentinel_token = lambda _device_id: "sentinel"
    flow.signup = lambda _email, _sentinel: True
    flow.register_password = lambda _email: True
    flow.send_otp = lambda: (_ for _ in ()).throw(AssertionError("send_otp should be reached through kickoff only"))
    flow._wait_for_email_otp = lambda *_args, **_kwargs: "123456"
    flow.verify_otp = lambda _code: {}
    flow.fetch_client_auth_session_dump = lambda _stage="": {}
    flow.create_account = lambda: ""
    flow.get_auth_session = lambda: (
        setattr(flow.result, "session_token", "session-token"),
        setattr(flow.result, "access_token", "access-token"),
    )

    delivery_modes = []
    flow.kickoff_otp_delivery = lambda mode="": delivery_modes.append(mode) or True

    result = flow.run_register(FakeMailProvider())

    assert result.is_valid()
    assert delivery_modes == ["register_password_success"]


def test_new_protocol_register_resends_email_otp_after_timeout(monkeypatch):
    auth_flow = _load_auth_flow_module()

    class FakeConfig:
        proxy = None

    class FakeMailProvider:
        def create_mailbox(self):
            return "fresh@outlook.my"

    flow = auth_flow.AuthFlow(FakeConfig())
    monkeypatch.delenv("OTP_TIMEOUT", raising=False)
    flow.check_proxy = lambda: True
    flow.get_csrf_token = lambda: "csrf"
    flow.get_auth_url = lambda _csrf: "https://auth.openai.test/authorize"
    flow.auth_oauth_init = lambda _url: "device"
    flow.get_sentinel_token = lambda _device_id: "sentinel"
    flow.signup = lambda _email, _sentinel: True
    flow.register_password = lambda _email: True
    flow.send_otp = lambda: (_ for _ in ()).throw(AssertionError("send_otp should be reached through kickoff only"))
    flow.verify_otp = lambda _code: {}
    flow.fetch_client_auth_session_dump = lambda _stage="": {}
    flow.create_account = lambda: ""
    flow.get_auth_session = lambda: (
        setattr(flow.result, "session_token", "session-token"),
        setattr(flow.result, "access_token", "access-token"),
    )

    delivery_modes = []
    flow.kickoff_otp_delivery = lambda mode="": delivery_modes.append(mode) or True
    wait_calls = []

    def fake_wait(*_args, **kwargs):
        wait_calls.append(kwargs)
        if len(wait_calls) == 1:
            raise TimeoutError("no code")
        return "123456"

    flow._wait_for_email_otp = fake_wait

    result = flow.run_register(FakeMailProvider())

    assert result.is_valid()
    assert delivery_modes == ["register_password_success", "new_register_timeout_retry"]
    assert wait_calls[0]["timeout"] == 60
    assert wait_calls[1]["exclude_used"] is True


def test_email_verification_delivery_uses_resend_before_passwordless():
    auth_flow = _load_auth_flow_module()

    class FakeConfig:
        proxy = None

    flow = auth_flow.AuthFlow(FakeConfig())
    calls = []
    flow.resend_otp = lambda _referer="": calls.append("resend") or True
    flow.send_passwordless_otp = lambda _referer="": calls.append("passwordless") or True
    flow.send_otp = lambda: calls.append("send")

    assert flow.kickoff_otp_delivery("existing_forced_resend") is True
    assert calls == ["resend"]


def test_password_registration_delivery_uses_email_otp_send_first():
    auth_flow = _load_auth_flow_module()

    class FakeConfig:
        proxy = None

    flow = auth_flow.AuthFlow(FakeConfig())
    calls = []
    flow.send_otp = lambda: calls.append("send")
    flow.resend_otp = lambda _referer="": calls.append("resend") or True
    flow.send_passwordless_otp = lambda _referer="": calls.append("passwordless") or True

    assert flow.kickoff_otp_delivery("register_password_success") is True
    assert calls == ["send"]


def test_passwordless_signup_is_not_marked_as_existing_account():
    auth_flow = _load_auth_flow_module()

    class FakeConfig:
        proxy = None

    flow = auth_flow.AuthFlow(FakeConfig())
    flow.authorize_continue = lambda **_kwargs: {
        "continue_url": "https://auth.openai.com/email-verification",
        "page": {
            "type": "email_otp_verification",
            "payload": {"email_verification_mode": "passwordless_signup"},
        },
    }

    assert flow.signup("fresh@outlook.my", "sentinel") is False
    assert flow._is_existing_account is False
    assert flow._existing_email_verification_mode == "passwordless_signup"


def test_existing_credentials_fallback_email_uses_shared_jwt_decoder():
    auth_flow = _load_auth_flow_module()

    class FakeConfig:
        proxy = None

    class FakeCookies:
        def __init__(self):
            self.values = {}

        def set(self, name, value, domain=None):
            self.values[(name, domain)] = value

        def get(self, name, default=""):
            for (cookie_name, _domain), value in self.values.items():
                if cookie_name == name:
                    return value
            return default

        def __iter__(self):
            return iter([])

    class FakeResponse:
        status_code = 200

        def json(self):
            return {}

    class FakeSession:
        def __init__(self):
            self.cookies = FakeCookies()

        def get(self, *_args, **_kwargs):
            return FakeResponse()

    access_token = _jwt({"https://api.openai.com/profile": {"email": "from-jwt@example.com"}})
    flow = auth_flow.AuthFlow(FakeConfig())
    flow.session = FakeSession()

    result = flow.from_existing_credentials("session-token", access_token, "device-id")

    assert result.email == "from-jwt@example.com"
    assert result.access_token == access_token
    assert result.session_token == "session-token"


def test_protocol_query_helpers_use_query_params_only():
    auth_flow = _load_auth_flow_module()

    url = "https://auth.example/callback?state=query-state#code=fragment-code&state=fragment-state"

    assert auth_flow.AuthFlow._extract_query_first(url, ["code", "state"]) == "query-state"
    assert auth_flow.AuthFlow._extract_query_first("https://auth.example/callback#code=fragment-code", ["code"]) == ""
    assert auth_flow.AuthFlow._callback_has_code(
        "https://app.example/callback#code=fragment-code",
        "https://app.example/callback",
    ) is False
    assert auth_flow.AuthFlow._callback_has_code(
        "https://app.example/callback?code=query-code",
        "https://app.example/callback",
    ) is True


def test_remember_oauth_params_uses_query_params_only():
    auth_flow = _load_auth_flow_module()

    class FakeConfig:
        proxy = None

    flow = auth_flow.AuthFlow(FakeConfig())
    flow._oauth_client_id = "default-client"
    flow._oauth_redirect_uri = "https://default.example/callback"

    flow._remember_oauth_params(
        "https://auth.example/authorize?"
        "redirect_uri=https%3A%2F%2Fapp.example%2Fcallback&scope=openid+email&state=query-state"
        "#client_id=fragment-client&state=fragment-state"
    )

    assert flow._oauth_auth_url.startswith("https://auth.example/authorize?")
    assert flow._oauth_client_id == "default-client"
    assert flow._oauth_redirect_uri == "https://app.example/callback"
    assert flow._oauth_scope == "openid email"
    assert flow._oauth_state == "query-state"


def test_protocol_cookie_base64url_decode_is_strict_and_size_bounded(monkeypatch):
    auth_flow = _load_auth_flow_module()
    encoded = _b64url_json({"login_challenge": "challenge-1"})

    assert auth_flow.AuthFlow._safe_b64url_decode_json(encoded) == {"login_challenge": "challenge-1"}
    assert auth_flow.AuthFlow._safe_b64url_decode_text("not valid base64") == ""

    monkeypatch.setattr(auth_flow, "AUTH_FLOW_B64URL_SEGMENT_MAX_CHARS", 8)

    assert auth_flow.AuthFlow._safe_b64url_decode_json(encoded) == {}


def test_extract_login_challenge_from_cookie_uses_bounded_decoder(monkeypatch):
    auth_flow = _load_auth_flow_module()

    class FakeConfig:
        proxy = None

    class Cookie:
        name = "login_session"

        def __init__(self, value):
            self.value = value

    class Cookies:
        def __init__(self, value):
            self.jar = [Cookie(value)]

    class FakeSession:
        def __init__(self, value):
            self.cookies = Cookies(value)

    encoded = _b64url_json({"login_challenge": "challenge-1"})
    flow = auth_flow.AuthFlow(FakeConfig())
    flow.session = FakeSession(f"{encoded}.sig")

    assert flow._extract_login_challenge_from_cookie() == "challenge-1"

    monkeypatch.setattr(auth_flow, "AUTH_FLOW_B64URL_SEGMENT_MAX_CHARS", 8)

    assert flow._extract_login_challenge_from_cookie() == ""


def test_extract_workspace_id_uses_bounded_cookie_decoder(monkeypatch):
    auth_flow = _load_auth_flow_module()

    class FakeConfig:
        proxy = None

    class Cookies:
        def __init__(self, value):
            self.value = value

        def get(self, name, default=""):
            return self.value if name == "oai-client-auth-session" else default

    class FakeSession:
        def __init__(self, value):
            self.cookies = Cookies(value)

    encoded = _b64url_json({"workspaces": [{"id": "workspace-1"}]})
    flow = auth_flow.AuthFlow(FakeConfig())
    flow.session = FakeSession(f"{encoded}.sig")

    assert flow._extract_workspace_id() == "workspace-1"

    monkeypatch.setattr(auth_flow, "AUTH_FLOW_B64URL_SEGMENT_MAX_CHARS", 8)

    assert flow._extract_workspace_id() == ""


def test_add_phone_send_rate_limit_stops_account_without_reusing_phone(monkeypatch):
    auth_flow = _load_auth_flow_module()
    from autotoken.auth.codex_auth import CodexOAuthPhoneRateLimited

    class FakeConfig:
        proxy = None

    supplier_calls = {"count": 0}
    failure_reasons = []
    resend_calls = {"count": 0}

    def fake_supplier():
        supplier_calls["count"] += 1
        return {
            "phone_number": "+15551234567",
            "source": "hero_sms",
            "activation_id": f"act-{supplier_calls['count']}",
        }

    flow = auth_flow.AuthFlow(FakeConfig())
    flow._openai_phone_provider = "hero_sms"
    flow._openai_phone_supplier = fake_supplier
    flow._openai_phone_failure = lambda _item, reason="": failure_reasons.append(reason)
    flow._add_phone_send = lambda _phone: (_ for _ in ()).throw(
        RuntimeError(
            "add-phone/send 失败: 400 - "
            "{\"error\":{\"message\":\"You've made too many phone verification requests. Please try again later.\"}}"
        )
    )
    flow._phone_otp_resend = lambda: resend_calls.__setitem__("count", resend_calls["count"] + 1)

    try:
        flow._handle_add_phone_verification("https://auth.openai.com/add-phone")
    except CodexOAuthPhoneRateLimited as exc:
        assert "too many phone verification requests" in str(exc).lower()
    else:
        raise AssertionError("expected add-phone rate limit to stop current account")

    assert supplier_calls["count"] == 1
    assert len(failure_reasons) == 1
    assert "too many phone verification requests" in failure_reasons[0].lower()
    assert resend_calls["count"] == 0


def test_codex_rt_exchange_preserves_add_phone_failure_reason(monkeypatch):
    auth_flow = _load_auth_flow_module()

    class FakeConfig:
        proxy = None

    flow = auth_flow.AuthFlow(FakeConfig())
    flow._build_codex_authorize = lambda: (
        "https://auth.openai.com/oauth/authorize?prompt=login",
        "state",
        "verifier",
        "http://localhost:1455/auth/callback",
        "client",
    )
    flow._follow_authorize_for_callback = lambda *_args, **_kwargs: ("", "https://auth.openai.com/add-phone")
    flow._is_add_email_state = lambda **_kwargs: False
    flow._is_add_phone_state = lambda **_kwargs: True
    flow._handle_add_phone_verification = lambda **_kwargs: (_ for _ in ()).throw(
        RuntimeError("add-phone/send 失败: 400 - too many phone verification requests")
    )
    flow._codex_refresh_retry_after_add_phone = lambda **_kwargs: ("", "https://auth.openai.com/add-phone")
    flow._drop_query_keys = lambda url, _keys: url.replace("?prompt=login", "")
    flow._emit_progress = lambda *_args, **_kwargs: None
    monkeypatch.setenv("OAUTH_CODEX_ADD_PHONE_REFRESH_RETRY", "0")

    assert flow.oauth_codex_rt_exchange(mail_provider=None) is False
    assert "add-phone/send 失败" in flow._last_codex_oauth_error
    assert "too many phone verification requests" in flow._last_codex_oauth_error
