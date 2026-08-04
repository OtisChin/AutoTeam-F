import json
import sys
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from standalone.oauth_relogin.oauth_relogin import (
    DEFAULT_CALLBACK_PORT,
    BrowserOAuthRunner,
    CdkSmsProvider,
    HandlerApiSmsProvider,
    JsonPhonePoolProvider,
    LocalOAuthHelperServer,
    OAuthCallbackServer,
    OAuthConfig,
    OAuthFlowState,
    PhoneItem,
    PhoneSmsConfig,
    SMSCloudSmsProvider,
    SmsProviderConfig,
    build_authorization_url,
    build_helper_url,
    build_phone_sms_config_report,
    build_token_bundle,
    create_sms_provider,
    load_phone_sms_provider_configs,
    parse_callback_url,
    redact_secret,
    run_browser_oauth_relogin_flow,
    run_oauth_relogin_flow,
)


def _jwt(payload: dict) -> str:
    import base64

    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    return f"header.{encoded}.signature"


def test_authorization_url_is_configurable_and_uses_pkce_inputs():
    url = build_authorization_url(
        OAuthConfig(
            client_id="client-placeholder",
            redirect_uri=f"http://127.0.0.1:{DEFAULT_CALLBACK_PORT}/auth/callback",
        ),
        code_challenge="challenge-123",
        state="state-456",
        native_oauth=True,
    )
    parsed = urlsplit(url)
    values = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "auth.example.com"
    assert parsed.path == "/oauth/authorize"
    assert values["client_id"] == ["client-placeholder"]
    assert values["redirect_uri"] == [f"http://127.0.0.1:{DEFAULT_CALLBACK_PORT}/auth/callback"]
    assert values["code_challenge"] == ["challenge-123"]
    assert values["state"] == ["state-456"]
    assert values["prompt"] == ["login"]
    assert values["code_challenge_method"] == ["S256"]


def test_callback_parser_accepts_full_url_query_and_fragment():
    query_result = parse_callback_url("http://127.0.0.1:1455/auth/callback?code=abc&state=s1")
    fragment_result = parse_callback_url("http://127.0.0.1:1455/auth/callback#code=def&state=s2")

    assert query_result == {"code": "abc", "state": "s1", "error": "", "raw_url": query_result["raw_url"]}
    assert fragment_result["code"] == "def"
    assert fragment_result["state"] == "s2"


def test_build_token_bundle_extracts_non_sensitive_claims():
    id_token = _jwt(
        {
            "email": "USER@example.com",
            "https://api.openai.com/auth": {
                "chatgpt_account_id": "acct_123",
                "chatgpt_plan_type": "plus",
            },
        }
    )

    bundle = build_token_bundle(
        {
            "access_token": "access-secret",
            "refresh_token": "refresh-secret",
            "id_token": id_token,
            "expires_in": 120,
        },
        fallback_email="fallback@example.com",
        now=1000,
    )

    assert bundle["email"] == "user@example.com"
    assert bundle["account_id"] == "acct_123"
    assert bundle["plan_type"] == "plus"
    assert bundle["expired"] == 1120
    assert bundle["access_token"] == "access-secret"
    assert bundle["refresh_token"] == "refresh-secret"


def test_helper_url_uses_generic_keys_without_project_branding():
    helper_url = build_helper_url("secret-token", 1455, "https://auth.example.com/oauth/authorize?client_id=x")
    values = parse_qs(urlsplit(helper_url).fragment)

    assert values == {
        "oauth_relogin_token": ["secret-token"],
        "oauth_relogin_port": ["1455"],
        "oauth_relogin_auth": ["https://auth.example.com/oauth/authorize?client_id=x"],
    }
    assert "autotoken" not in helper_url.lower()
    assert "autoteam" not in helper_url.lower()


def test_redact_secret_keeps_short_shape_only():
    assert redact_secret("sk-abcdefghijklmnopqrstuvwxyz") == "sk-a...wxyz"
    assert redact_secret("") == ""
    assert redact_secret("short") == "***"


def test_callback_parser_rejects_missing_code_or_error():
    with pytest.raises(ValueError, match="缺少 code"):
        parse_callback_url("http://127.0.0.1:1455/auth/callback?state=s1")


def test_phone_sms_config_loads_sanitized_provider_settings(monkeypatch):
    monkeypatch.setenv("OAUTH_RELOGIN_PHONE_SMS_PROVIDER", "Phone-Pool")
    monkeypatch.setenv("OAUTH_RELOGIN_PHONE_SMS_COUNTRY", "US")
    monkeypatch.setenv("OAUTH_RELOGIN_PHONE_SMS_API_KEY", "super-secret-api-key")

    config = PhoneSmsConfig.from_env()

    assert config.provider == "phone_pool"
    assert config.country == "187"
    assert config.api_key == "super-secret-api-key"
    assert config.to_safe_dict()["api_key"] == "supe...-key"
    assert "super-secret-api-key" not in json.dumps(config.to_safe_dict())


def test_provider_specific_sms_configs_are_loaded_and_masked(monkeypatch):
    monkeypatch.setenv("OAUTH_RELOGIN_PHONE_SMS_PROVIDER", "smscloud")
    monkeypatch.setenv("OAUTH_RELOGIN_HERO_SMS_API_KEY", "hero-secret-key")
    monkeypatch.setenv("OAUTH_RELOGIN_HERO_SMS_COUNTRY", "US")
    monkeypatch.setenv("OAUTH_RELOGIN_SMSBOWER_API_KEY", "bower-secret-key")
    monkeypatch.setenv("OAUTH_RELOGIN_SMSBOWER_MAX_PRICE", "0.12")
    monkeypatch.setenv("OAUTH_RELOGIN_SMSCLOUD_API_KEY", "cloud-secret-key")
    monkeypatch.setenv("OAUTH_RELOGIN_SMSCLOUD_BASE_URL", "https://smscloud.example/api")
    monkeypatch.setenv("OAUTH_RELOGIN_OASIS_SMS_CDKS", "cdk-one\ncdk-two")
    monkeypatch.setenv("OAUTH_RELOGIN_TUJIE_SMS_CDKS", "tj-one,tj-two,tj-three")

    configs = load_phone_sms_provider_configs()
    report = build_phone_sms_config_report(configs)

    assert configs["hero_sms"].configured is True
    assert configs["hero_sms"].country == "187"
    assert configs["smsbower"].max_price == "0.12"
    assert configs["smscloud"].base_url == "https://smscloud.example/api"
    assert configs["oasis"].cdk_count == 2
    assert configs["tujie"].cdk_count == 3
    assert report["provider"] == "smscloud"
    assert report["configured"] is True
    assert {item["value"] for item in report["providers"]} == {
        "phone_pool",
        "hero_sms",
        "smsbower",
        "smscloud",
        "oasis",
        "tujie",
    }
    serialized = json.dumps(report, ensure_ascii=False)
    assert "hero-secret-key" not in serialized
    assert "bower-secret-key" not in serialized
    assert "cloud-secret-key" not in serialized
    assert "cdk-one" not in serialized
    assert "tj-one" not in serialized


def test_json_phone_pool_provider_imports_reserves_marks_bound_and_persists(tmp_path):
    pool_file = tmp_path / "phone-pool.json"
    provider = JsonPhonePoolProvider(pool_file)

    imported = provider.import_phones("+12025550111----https://sms.example/inbox/1\n12025550112|https://sms.example/inbox/2")
    reserved = provider.acquire_phone("user@example.com")
    reserved.otp = "123456"
    assert provider.wait_for_code(reserved) == "123456"
    provider.mark_bound(reserved, "user@example.com")

    data = json.loads(pool_file.read_text(encoding="utf-8"))
    assert imported["added_count"] == 2
    assert data["items"][0]["bound_emails"] == ["user@example.com"]
    assert data["items"][0]["bound_count"] == 1
    assert data["items"][0]["status"] == "available"


def test_run_oauth_relogin_flow_binds_phone_and_writes_json_files(tmp_path):
    phone_pool = JsonPhonePoolProvider(tmp_path / "phone-pool.json")
    phone_pool.import_phones("+12025550111----https://sms.example/inbox/1")

    calls = {}

    def fake_oauth_runner(**kwargs):
        calls.update(kwargs)
        assert kwargs["phone_item"].phone_number == "+12025550111"
        assert kwargs["get_phone_code"]() == "654321"
        return {
            "email": "user@example.com",
            "access_token": "access-secret",
            "refresh_token": "refresh-secret",
            "id_token": "id-secret",
            "account_id": "acct_123",
            "plan_type": "plus",
            "expired": 1120,
        }

    result = run_oauth_relogin_flow(
        email="USER@example.com",
        password="password-secret",
        output_dir=tmp_path / "out",
        bind_phone=True,
        sms_provider=phone_pool,
        oauth_runner=fake_oauth_runner,
        phone_code_provider=lambda _phone_item: "654321",
        now=1000,
    )

    assert result["status"] == "completed"
    assert result["email"] == "user@example.com"
    assert Path(result["auth_file"]).exists()
    assert Path(result["phone_records_file"]).exists()
    assert "access-secret" not in json.dumps(result)
    assert "refresh-secret" not in json.dumps(result)
    assert calls["password"] == "password-secret"

    auth_data = json.loads(Path(result["auth_file"]).read_text(encoding="utf-8"))
    phone_records = json.loads(Path(result["phone_records_file"]).read_text(encoding="utf-8"))
    assert auth_data["refresh_token"] == "refresh-secret"
    assert phone_records["bindings"][0]["email"] == "user@example.com"
    assert phone_records["bindings"][0]["phone_number"] == "+12025550111"


class _FakeResponse:
    def __init__(self, text="", payload=None, status_code=200, headers=None):
        self.text = text
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_handler_api_sms_provider_acquires_polls_finishes_and_cancels():
    calls = []
    responses = [
        _FakeResponse("ACCESS_NUMBER:act-1:+12025550111"),
        _FakeResponse("STATUS_WAIT_CODE"),
        _FakeResponse("STATUS_OK:778899"),
        _FakeResponse("ACCESS_READY"),
        _FakeResponse("ACCESS_CANCEL"),
    ]

    def fake_get(url, *, params=None, headers=None, timeout=None):
        calls.append((url, params, headers, timeout))
        return responses.pop(0)

    provider = HandlerApiSmsProvider(
        SmsProviderConfig(
            provider="hero_sms",
            label="hero-sms",
            configured=True,
            api_key="api-key",
            base_url="https://sms.example/handler_api.php",
            country="187",
            service="dr",
            poll_attempts=3,
            poll_interval_seconds=0.01,
        ),
        http_get=fake_get,
    )

    phone = provider.acquire_phone("user@example.com")
    code = provider.wait_for_code(phone)
    provider.mark_bound(phone, "user@example.com")
    provider.release(phone, reason="manual_cancel")

    assert phone.phone_number == "+12025550111"
    assert code == "778899"
    assert [call[1]["action"] for call in calls] == ["getNumber", "getStatus", "getStatus", "setStatus", "setStatus"]
    assert calls[-2][1]["status"] == "6"
    assert calls[-1][1]["status"] == "8"


def test_smscloud_provider_acquires_polls_finishes_and_cancels():
    calls = []
    payloads = [
        {"code": 0, "data": {"id": "order-1", "phoneNumber": "+12025550112", "creditAmount": "0.1"}},
        {"code": 0, "data": {"text": "Your code is 112233"}},
        {"code": 0, "data": {}},
        {"code": 0, "data": {}},
    ]

    def fake_get(url, *, params=None, headers=None, timeout=None):
        calls.append((url, params, headers, timeout))
        return _FakeResponse(payload=payloads.pop(0))

    provider = SMSCloudSmsProvider(
        SmsProviderConfig(
            provider="smscloud",
            label="SMSCloud",
            configured=True,
            api_key="cloud-key",
            base_url="https://smscloud.example/api/system",
            country="187",
            service="dr",
            poll_attempts=2,
            poll_interval_seconds=0.01,
        ),
        http_get=fake_get,
    )

    phone = provider.acquire_phone("user@example.com")
    assert provider.wait_for_code(phone) == "112233"
    provider.mark_bound(phone, "user@example.com")
    provider.release(phone, reason="cancel")

    assert phone.activation_id == "order-1"
    assert calls[0][0].endswith("/public/sms/flexible")
    assert calls[1][0].endswith("/public/sms/orders/sync/order-1")
    assert calls[2][0].endswith("/public/sms/orders/finish/order-1")
    assert calls[3][0].endswith("/public/sms/orders/cancel/order-1")


def test_cdk_sms_provider_acquires_polls_records_mapping(tmp_path):
    calls = []
    payloads = [
        {"ok": True, "phone": "+12025550113"},
        {"sms": "验证码 445566"},
    ]

    def fake_post(url, *, json=None, headers=None, timeout=None):
        calls.append((url, json, headers, timeout))
        return _FakeResponse(payload=payloads.pop(0))

    provider = CdkSmsProvider(
        SmsProviderConfig(
            provider="oasis",
            label="Oasis CDK",
            configured=True,
            base_url="https://oasis.example",
            cdk_values=("SMS-AAAA-BBBB-CCCC",),
            account_map_file=str(tmp_path / "map.jsonl"),
            poll_attempts=2,
            poll_interval_seconds=0.01,
        ),
        http_post=fake_post,
    )

    phone = provider.acquire_phone("user@example.com")
    assert provider.wait_for_code(phone) == "445566"
    provider.mark_bound(phone, "user@example.com")

    assert phone.phone_number == "+12025550113"
    assert calls[0][0].endswith("/api.php?action=check_cdk")
    assert calls[1][0].endswith("/api.php?action=get_sms")
    assert json.loads((tmp_path / "map.jsonl").read_text(encoding="utf-8").splitlines()[0])["status"] == "success"


def test_create_sms_provider_returns_real_adapters(tmp_path):
    configs = {
        "phone_pool": SmsProviderConfig(provider="phone_pool", label="pool", configured=True),
        "hero_sms": SmsProviderConfig(provider="hero_sms", label="hero", configured=True, api_key="k"),
        "smsbower": SmsProviderConfig(provider="smsbower", label="bower", configured=True, api_key="k"),
        "smscloud": SmsProviderConfig(provider="smscloud", label="cloud", configured=True, api_key="k"),
        "oasis": SmsProviderConfig(provider="oasis", label="oasis", configured=True, cdk_values=("SMS-AAAA-BBBB-CCCC",)),
        "tujie": SmsProviderConfig(provider="tujie", label="tujie", configured=True, cdk_values=("TJ-CDK",)),
    }

    assert isinstance(create_sms_provider("phone_pool", configs=configs, phone_pool_path=tmp_path / "pool.json"), JsonPhonePoolProvider)
    assert isinstance(create_sms_provider("hero_sms", configs=configs), HandlerApiSmsProvider)
    assert isinstance(create_sms_provider("smsbower", configs=configs), HandlerApiSmsProvider)
    assert isinstance(create_sms_provider("smscloud", configs=configs), SMSCloudSmsProvider)
    assert isinstance(create_sms_provider("oasis", configs=configs), CdkSmsProvider)
    assert isinstance(create_sms_provider("tujie", configs=configs), CdkSmsProvider)


def test_helper_and_callback_servers_support_browser_runner_state():
    flow_state = OAuthFlowState(email="user@example.com", password="pw")
    helper = LocalOAuthHelperServer(flow_state, port=0, token="helper-token").start()
    callback = OAuthCallbackServer(port=0).start()
    try:
        helper.set_phone(PhoneItem(id="p1", phone_number="+12025550114", sms_url="https://sms.example/1"))
        helper.set_otp("123456")
        state_url = f"http://127.0.0.1:{helper.port}/state?token=helper-token"
        state = json.loads(urllib.request.urlopen(state_url, timeout=2).read().decode("utf-8"))
        assert state["email"] == "user@example.com"
        assert state["phone"] == "+12025550114"
        assert state["otp"] == "123456"

        event_req = urllib.request.Request(
            f"http://127.0.0.1:{helper.port}/event?token=helper-token",
            data=json.dumps({"type": "phone_required", "url": "https://auth.example.com/add-phone"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(event_req, timeout=2).read()
        assert helper.phone_required_url.endswith("/add-phone")

        urllib.request.urlopen(
            f"http://127.0.0.1:{callback.port}/auth/callback?code=abc&state=state-1",
            timeout=2,
        ).read()
        assert callback.wait_for_callback(timeout=1)["code"] == "abc"
    finally:
        helper.stop()
        callback.stop()


def test_browser_oauth_runner_orchestrates_phone_binding_without_real_browser(tmp_path):
    events = []
    phone_pool = JsonPhonePoolProvider(tmp_path / "phone-pool.json")
    phone_pool.import_phones("+12025550115----https://sms.example/inbox/15")

    def fake_open(url):
        events.append(("open", url))

    def fake_wait_callback(runner):
        runner.helper_server.phone_required_url = "https://auth.example.com/add-phone"
        runner._handle_phone_if_needed()
        assert runner.helper_server.state.phone == "+12025550115"
        assert runner.helper_server.state.otp == "998877"
        return {"code": "auth-code", "state": runner.state, "error": "", "raw_url": "http://127.0.0.1/cb?code=auth-code"}

    def fake_exchange(code, verifier, *, config=None, fallback_email=None):
        assert code == "auth-code"
        assert verifier
        return {
            "email": fallback_email,
            "access_token": "access-secret",
            "refresh_token": "refresh-secret",
            "id_token": "",
            "account_id": "acct_1",
            "plan_type": "plus",
            "expired": 1200,
        }

    runner = BrowserOAuthRunner(
        email="user@example.com",
        password="pw",
        sms_provider=phone_pool,
        phone_code_provider=lambda _phone: "998877",
        open_browser=fake_open,
        wait_callback=fake_wait_callback,
        exchange=fake_exchange,
    )

    bundle = runner.run()

    assert bundle["refresh_token"] == "refresh-secret"
    assert events and "oauth_relogin_token" in events[0][1]


def test_run_browser_oauth_relogin_flow_saves_bundle_and_phone_record(tmp_path):
    events = []
    phone_pool = JsonPhonePoolProvider(tmp_path / "phone-pool.json")
    phone_pool.import_phones("+12025550116----https://sms.example/inbox/16")

    def fake_wait_callback(runner):
        runner.helper_server.phone_required_url = "https://auth.example.com/add-phone"
        runner._handle_phone_if_needed()
        return {"code": "auth-code", "state": runner.state, "error": "", "raw_url": "http://127.0.0.1/cb?code=auth-code"}

    result = run_browser_oauth_relogin_flow(
        email="user@example.com",
        password="pw",
        output_dir=tmp_path / "out",
        sms_provider=phone_pool,
        phone_code_provider=lambda _phone: "111222",
        open_browser=lambda url: events.append(url),
        wait_callback=fake_wait_callback,
        exchange=lambda code, verifier, **kwargs: {
            "email": kwargs["fallback_email"],
            "access_token": "access-secret",
            "refresh_token": "refresh-secret",
            "id_token": "",
            "account_id": "acct_1",
            "plan_type": "plus",
            "expired": 1200,
        },
        now=1000,
    )

    assert result["status"] == "completed"
    assert Path(result["auth_file"]).exists()
    assert Path(result["phone_records_file"]).exists()
    assert json.loads(Path(result["phone_records_file"]).read_text(encoding="utf-8"))["bindings"][0]["phone_number"] == "+12025550116"
    assert "oauth_relogin_token" in events[0]
