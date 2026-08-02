import threading

import pytest

from autotoken import gopay_auto_register


@pytest.fixture(autouse=True)
def _force_http_signup_mode(monkeypatch):
    monkeypatch.setenv("GOPAY_AUTO_SIGNUP_MODE", "http")


def test_sms_bridge_payload_resend_calls_hero_sms_status(monkeypatch):
    set_status_calls = []

    monkeypatch.setattr(
        gopay_auto_register,
        "_hero_set_status",
        lambda base_url, api_key, activation_id, status: set_status_calls.append(
            (base_url, api_key, activation_id, status)
        ),
    )
    monkeypatch.setattr(
        gopay_auto_register,
        "_hero_request",
        lambda *_args, **_kwargs: (True, "STATUS_WAIT_CODE", None),
    )

    bridge = gopay_auto_register.GoPaySmsBridge(
        token="bridge-hero",
        activation_id="activation-hero",
        base_url="https://hero-sms.example.test",
        api_key="hero-key",
        provider="hero_sms",
    )
    with gopay_auto_register._BRIDGE_LOCK:
        gopay_auto_register._SMS_BRIDGES[bridge.token] = bridge
    try:
        payload = gopay_auto_register.get_sms_bridge_payload(bridge.token, resend=True)
    finally:
        with gopay_auto_register._BRIDGE_LOCK:
            gopay_auto_register._SMS_BRIDGES.pop(bridge.token, None)

    assert payload == {"ok": False, "data": {"status": "pending"}}
    assert set_status_calls == [
        (
            "https://hero-sms.example.test",
            "hero-key",
            "activation-hero",
            gopay_auto_register.STATUS_RESEND,
        )
    ]


def test_sms_bridge_payload_resend_calls_smsbower_status(monkeypatch):
    set_status_calls = []

    monkeypatch.setattr(
        gopay_auto_register,
        "_hero_set_status",
        lambda base_url, api_key, activation_id, status: set_status_calls.append(
            (base_url, api_key, activation_id, status)
        ),
    )
    monkeypatch.setattr(
        gopay_auto_register,
        "_hero_request",
        lambda *_args, **_kwargs: (True, "STATUS_WAIT_CODE", None),
    )

    bridge = gopay_auto_register.GoPaySmsBridge(
        token="bridge-smsbower",
        activation_id="activation-smsbower",
        base_url="https://smsbower.example.test",
        api_key="smsbower-key",
        provider="smsbower",
    )
    with gopay_auto_register._BRIDGE_LOCK:
        gopay_auto_register._SMS_BRIDGES[bridge.token] = bridge
    try:
        payload = gopay_auto_register.get_sms_bridge_payload(bridge.token, resend=True)
    finally:
        with gopay_auto_register._BRIDGE_LOCK:
            gopay_auto_register._SMS_BRIDGES.pop(bridge.token, None)

    assert payload == {"ok": False, "data": {"status": "pending"}}
    assert set_status_calls == [
        (
            "https://smsbower.example.test",
            "smsbower-key",
            "activation-smsbower",
            gopay_auto_register.STATUS_RESEND,
        )
    ]


def test_sms_activation_marks_ready_before_waiting_code(monkeypatch):
    set_status_calls = []
    request_calls = []

    monkeypatch.setattr(
        gopay_auto_register,
        "_hero_set_status",
        lambda base_url, api_key, activation_id, status: set_status_calls.append(
            (base_url, api_key, activation_id, status)
        ) or "ACCESS_READY",
    )

    def fake_hero_request(_base_url, _api_key, action, params=None, **_kwargs):
        request_calls.append((action, dict(params or {})))
        return True, "STATUS_OK:123456", None

    monkeypatch.setattr(gopay_auto_register, "_hero_request", fake_hero_request)

    activation = gopay_auto_register.SmsActivation(
        activation_id="activation-ready",
        phone="5591980652076",
        country_id=73,
        base_url="https://hero-sms.example.test",
        api_key="hero-key",
        log=lambda _message: None,
    )

    assert activation.wait_code(timeout_sec=30, label="test") == "123456"
    assert set_status_calls == [
        (
            "https://hero-sms.example.test",
            "hero-key",
            "activation-ready",
            gopay_auto_register.STATUS_READY,
        )
    ]
    assert request_calls == [("getStatus", {"id": "activation-ready"})]


def test_sms_activation_resend_bad_status_keeps_waiting_until_timeout(monkeypatch):
    set_status_calls = []
    logs = []
    now = {"value": 0.0}

    def fake_set_status(base_url, api_key, activation_id, status):
        set_status_calls.append((base_url, api_key, activation_id, status))
        if status == gopay_auto_register.STATUS_RESEND:
            raise RuntimeError("BAD_STATUS")
        return "ACCESS_READY"

    monkeypatch.setattr(gopay_auto_register, "_hero_set_status", fake_set_status)
    monkeypatch.setattr(
        gopay_auto_register,
        "_hero_request",
        lambda *_args, **_kwargs: (True, "STATUS_WAIT_CODE", None),
    )
    monkeypatch.setattr(gopay_auto_register, "POLL_INTERVAL_SEC", 31)
    monkeypatch.setattr(gopay_auto_register.time, "time", lambda: now["value"])
    monkeypatch.setattr(gopay_auto_register.time, "sleep", lambda seconds: now.__setitem__("value", now["value"] + seconds))

    activation = gopay_auto_register.SmsActivation(
        activation_id="activation-resend-bad-status",
        phone="5547999231890",
        country_id=73,
        base_url="https://smsbower.example.test",
        api_key="smsbower-key",
        provider="smsbower",
        log=logs.append,
    )

    assert activation.wait_code(timeout_sec=35, label="test") == ""
    assert set_status_calls == [
        (
            "https://smsbower.example.test",
            "smsbower-key",
            "activation-resend-bad-status",
            gopay_auto_register.STATUS_READY,
        ),
        (
            "https://smsbower.example.test",
            "smsbower-key",
            "activation-resend-bad-status",
            gopay_auto_register.STATUS_RESEND,
        ),
    ]
    assert any("短信供应商重发请求失败，继续等待验证码" in item for item in logs)


@pytest.mark.parametrize(
    ("ok", "response"),
    [
        (False, "REQUEST_ERROR:timed out"),
        (True, "BAD_STATUS"),
        (True, "NO_ACTIVATION"),
    ],
)
def test_hero_set_status_raises_when_provider_rejects_update(monkeypatch, ok, response):
    monkeypatch.setattr(
        gopay_auto_register,
        "_hero_request",
        lambda *_args, **_kwargs: (ok, response, None),
    )

    with pytest.raises(RuntimeError, match=response):
        gopay_auto_register._hero_set_status(
            "https://hero-sms.example.test",
            "hero-key",
            "activation-timeout",
            gopay_auto_register.STATUS_CANCEL,
        )


def test_sms_activation_cancel_retries_transient_status_failure(monkeypatch):
    calls = []

    def fake_set_status(base_url, api_key, activation_id, status):
        calls.append((base_url, api_key, activation_id, status))
        if len(calls) == 1:
            raise RuntimeError("temporary failure")
        return "ACCESS_CANCEL"

    monkeypatch.setattr(gopay_auto_register, "_hero_set_status", fake_set_status)
    monkeypatch.setattr(gopay_auto_register.time, "sleep", lambda _seconds: None)
    activation = gopay_auto_register.SmsActivation(
        activation_id="activation-cancel",
        phone="27655370996",
        country_id=16,
        base_url="https://hero-sms.example.test",
        api_key="hero-key",
        log=lambda _message: None,
    )

    activation.cancel()

    assert len(calls) == 2
    assert calls[-1][-1] == gopay_auto_register.STATUS_SMSBOWER_CANCEL


def test_sms_activation_cancel_does_not_retry_early_cancel_denied(monkeypatch):
    calls = []

    def fake_set_status(*args):
        calls.append(args)
        raise RuntimeError(
            '{"title":"EARLY_CANCEL_DENIED","details":"Activation cannot be cancelled at this time.",'
            '"info":{"minActivationTime":120}}'
        )

    monkeypatch.setattr(gopay_auto_register, "_hero_set_status", fake_set_status)
    activation = gopay_auto_register.SmsActivation(
        activation_id="activation-early-cancel",
        phone="27619766274",
        country_id=31,
        base_url="https://hero-sms.example.test",
        api_key="hero-key",
        provider="hero_sms",
        log=lambda _message: None,
    )

    with pytest.raises(RuntimeError, match="EARLY_CANCEL_DENIED"):
        activation.cancel()

    assert len(calls) == 1


def test_sms_activation_cancel_uses_sms_activate_cancel_status_for_hero_sms(monkeypatch):
    calls = []
    monkeypatch.setattr(
        gopay_auto_register,
        "_hero_set_status",
        lambda *args: calls.append(args),
    )

    activation = gopay_auto_register.SmsActivation(
        activation_id="activation-hero-cancel",
        phone="27619766274",
        country_id=31,
        base_url="https://hero-sms.example.test",
        api_key="hero-key",
        provider="hero_sms",
        log=lambda _message: None,
    )

    activation.cancel()

    assert calls[0][-1] == gopay_auto_register.STATUS_SMSBOWER_CANCEL


def test_delayed_cancel_retries_when_provider_still_denies_early_cancel(monkeypatch):
    calls = {"cancel": 0}
    sleeps = []
    done = threading.Event()

    class DummyActivation:
        provider = "hero_sms"
        activation_id = "activation-delayed-early"

        def cancel(self):
            calls["cancel"] += 1
            if calls["cancel"] == 1:
                raise RuntimeError(
                    '{"title":"EARLY_CANCEL_DENIED","details":"Activation cannot be cancelled at this time.",'
                    '"info":{"minActivationTime":120}}'
                )

    monkeypatch.setattr(gopay_auto_register.time, "sleep", lambda seconds: sleeps.append(seconds))
    gopay_auto_register._delayed_cancel_activation(
        DummyActivation(),
        delay_seconds=1,
        log=lambda _message: None,
        on_success=done.set,
    )

    assert done.wait(1)
    assert calls["cancel"] == 2
    assert sleeps == [1, 10]


def test_register_gopay_wallet_uses_smsbower_config(monkeypatch):
    captured = {}

    monkeypatch.setenv("GOPAY_AUTO_SIGNUP_REQUIRE_PROXY", "0")

    def fake_get_number(**kwargs):
        captured["get_number"] = kwargs
        return "activation-smsbower", "6287712345678", ""

    def fake_auto_signup(**kwargs):
        captured["auto_signup"] = kwargs
        return gopay_auto_register.GoPayAccountResult(
            access_token="access",
            refresh_token="refresh",
            account_id="account",
            phone=kwargs["phone"],
            country_code=kwargs["country_code"],
            pin=kwargs["pin"],
        )

    set_status_calls = []
    monkeypatch.setattr(gopay_auto_register, "_smsbower_get_number", fake_get_number)
    monkeypatch.setattr(gopay_auto_register, "auto_signup", fake_auto_signup)
    monkeypatch.setattr(
        gopay_auto_register,
        "_hero_set_status",
        lambda base_url, api_key, activation_id, status: set_status_calls.append(
            (base_url, api_key, activation_id, status)
        ),
    )

    result = gopay_auto_register.register_gopay_wallet(
        pin="558023",
        sms_provider="smsbower",
        smsbower_config={
            "api_key": "smsbower-key",
            "base_url": "https://smsbower.example.test",
            "country": "6",
            "service": "ni",
            "min_price": "0.02",
            "max_price": "0.08",
            "preferred_price": "0.045",
        },
        public_base_url="http://127.0.0.1:8787",
    )

    try:
        assert result.phone_number == "87712345678"
        assert result.country_code == "62"
        assert result.sms_url.startswith("http://127.0.0.1:8787/otp/gopay-signup/")
        assert captured["get_number"] == {
            "service_code": "ni",
            "country_id": 6,
            "base_url": "https://smsbower.example.test",
            "api_key": "smsbower-key",
            "max_price": "0.08",
            "min_price": "0.02",
            "preferred_price": "0.045",
        }
        assert captured["auto_signup"]["phone"] == "87712345678"
        assert captured["auto_signup"]["country_code"] == "+62"
    finally:
        result.close(success=True)

    assert set_status_calls == [
        (
            "https://smsbower.example.test",
            "smsbower-key",
            "activation-smsbower",
            gopay_auto_register.STATUS_FINISH,
        )
    ]


def test_smsbower_get_number_skips_hero_price_probe(monkeypatch):
    requests = []

    def fake_hero_request(_base_url, _api_key, action, params=None, **_kwargs):
        requests.append((action, dict(params or {})))
        if action == "getNumber":
            return True, "ACCESS_NUMBER:activation-smsbower:6287712345678", None
        raise AssertionError(action)

    monkeypatch.setattr(gopay_auto_register, "_hero_request", fake_hero_request)

    activation_id, phone, error = gopay_auto_register._smsbower_get_number(
        service_code="ni",
        country_id=6,
        base_url="https://smsbower.example.test/stubs/handler_api.php",
        api_key="smsbower-key",
        min_price="0.02",
        max_price="0.08",
    )

    assert error == ""
    assert activation_id == "activation-smsbower"
    assert phone == "6287712345678"
    assert requests == [
        (
            "getNumber",
            {
                "service": "ni",
                "country": 6,
                "minPrice": "0.02",
                "maxPrice": "0.08",
            },
        )
    ]


def test_query_smsbower_price_tiers_returns_warning_when_price_api_denies_access(monkeypatch):
    requests = []

    def fake_hero_request(_base_url, _api_key, action, params=None, **_kwargs):
        requests.append((action, dict(params or {})))
        return False, '{"status":0,"message":"No access","data":[]}', {"status": 0, "message": "No access", "data": []}

    monkeypatch.setattr(gopay_auto_register, "_hero_request", fake_hero_request)

    result = gopay_auto_register.query_smsbower_price_tiers(
        service_code="ni",
        country_id=6,
        base_url="https://smsbower.example.test/stubs/handler_api.php",
        api_key="smsbower-key",
        min_price="0.02",
        max_price="0.08",
    )

    assert result["ok"] is True
    assert result["price_query_unavailable"] is True
    assert "无价格查询权限" in result["warning"]
    assert result["prices"] == []
    assert [request[0] for request in requests] == ["getPrices", "getTopCountriesByService"]


def test_query_smsbower_price_tiers_filters_supported_price_payload(monkeypatch):
    def fake_hero_request(_base_url, _api_key, action, params=None, **_kwargs):
        if action == "getPrices":
            return True, "", {"6": {"ni": {"low": {"cost": 0.04, "count": 8}, "mid": {"cost": 0.08, "count": 3}}}}
        if action == "getTopCountriesByService":
            return True, "", {}
        raise AssertionError(action)

    monkeypatch.setattr(gopay_auto_register, "_hero_request", fake_hero_request)

    result = gopay_auto_register.query_smsbower_price_tiers(
        service_code="ni",
        country_id=6,
        base_url="https://smsbower.example.test/stubs/handler_api.php",
        api_key="smsbower-key",
        min_price="0.05",
        max_price="0.09",
    )

    assert result["ok"] is True
    assert result["prices"] == [0.04, 0.08]
    assert result["filtered_prices"] == [0.08]
    assert result["filtered_tiers"] == [{"price": 0.08, "count": 3}]


def test_hero_price_within_limits_respects_empty_and_boundaries():
    assert gopay_auto_register._hero_price_within_limits(None, None, None) is False
    assert gopay_auto_register._hero_price_within_limits(0.0618, 0.07, None) is False
    assert gopay_auto_register._hero_price_within_limits(0.0618, None, 0.05) is False
    assert gopay_auto_register._hero_price_within_limits(0.0618, 0.0618, 0.0618) is True
    assert gopay_auto_register._hero_price_within_limits(0.0618, None, None) is True


def test_query_smsbower_countries_uses_get_countries(monkeypatch):
    requests = []

    def fake_hero_request(_base_url, _api_key, action, params=None, **_kwargs):
        requests.append((action, dict(params or {})))
        if action == "getCountries":
            return True, "", {
                "1": {"id": 1, "chn": "乌克兰", "eng": "Ukraine", "phone_code": "380"},
                "187": {"id": 187, "chn": "美国", "eng": "United States", "phone_code": "1"},
            }
        if action == "getTopCountriesByService":
            return True, "", {}
        raise AssertionError(action)

    monkeypatch.setattr(gopay_auto_register, "_hero_request", fake_hero_request)

    result = gopay_auto_register.query_dynamic_sms_countries(
        provider="smsbower",
        service_code="dr",
        base_url="https://smsbower.example.test/stubs/handler_api.php",
        api_key="smsbower-key",
    )

    assert result["ok"] is True
    assert [item["value"] for item in result["options"]] == ["1", "187"]
    assert "乌克兰" in result["options"][0]["label"]
    assert requests[0] == ("getCountries", {})


def test_query_smsbower_countries_ignores_internal_product_ids(monkeypatch):
    def fake_hero_request(_base_url, _api_key, action, params=None, **_kwargs):
        if action == "getCountries":
            return True, "", {
                "33": {"id": 33, "chn": "哥伦比亚", "eng": "Colombia"},
                "187": {"id": 187, "chn": "美国", "eng": "USA"},
            }
        if action == "getTopCountriesByService":
            return True, "", {
                "33": {"country": 33, "count": 9, "price": 0.04},
                "products": {
                    "3243": {"count": 10, "price": 0.017},
                    "3339": {"count": 211, "price": 0.027},
                },
            }
        raise AssertionError(action)

    monkeypatch.setattr(gopay_auto_register, "_hero_request", fake_hero_request)

    result = gopay_auto_register.query_dynamic_sms_countries(
        provider="smsbower",
        service_code="dr",
        base_url="https://smsbower.example.test/stubs/handler_api.php",
        api_key="smsbower-key",
    )

    values = [item["value"] for item in result["options"]]
    assert values == ["33", "187"]
    assert "哥伦比亚" in result["options"][0]["label"]
    assert "9个" in result["options"][0]["label"]
    assert "3243" not in values
    assert "3339" not in values


def test_query_hero_sms_countries_uses_top_countries(monkeypatch):
    requests = []

    def fake_hero_request(_base_url, _api_key, action, params=None, **_kwargs):
        requests.append((action, dict(params or {})))
        if action == "getCountries":
            return True, "", {
                "33": {"id": 33, "chn": "哥伦比亚", "eng": "Colombia"},
                "187": {"id": 187, "chn": "美国（物理)", "eng": "USA"},
            }
        if action == "getTopCountriesByService":
            return True, "", {
                "co": {"country": 33, "prefix": "57", "count": 12, "price": 0.05},
                "us": {"country": 187, "prefix": "1", "count": 4, "price": 0.09},
            }
        if action == "getPrices":
            return True, "", {}
        raise AssertionError(action)

    monkeypatch.setattr(gopay_auto_register, "_hero_request", fake_hero_request)

    result = gopay_auto_register.query_dynamic_sms_countries(
        provider="hero_sms",
        service_code="dr",
        base_url="https://hero-sms.example.test/stubs/handler_api.php",
        api_key="hero-key",
    )

    assert result["ok"] is True
    assert [item["value"] for item in result["options"]] == ["33", "187"]
    assert "哥伦比亚" in result["options"][0]["label"]
    assert "12个" in result["options"][0]["label"]
    assert "$0.05" in result["options"][0]["label"]
    assert requests[0] == ("getCountries", {})
    assert requests[1] == ("getTopCountriesByService", {"service": "dr", "freePrice": "true"})


def test_register_gopay_wallet_stops_when_smsbower_api_key_has_no_access(monkeypatch):
    requests = []

    monkeypatch.setenv("GOPAY_AUTO_SIGNUP_REQUIRE_PROXY", "0")

    def fake_hero_request(_base_url, _api_key, action, params=None, **_kwargs):
        requests.append((action, dict(params or {})))
        return False, '{"status":0,"message":"No access","data":[]}', {"status": 0, "message": "No access", "data": []}

    monkeypatch.setattr(gopay_auto_register, "_hero_request", fake_hero_request)

    with pytest.raises(gopay_auto_register.GoPayAutoSignupError) as exc_info:
        gopay_auto_register.register_gopay_wallet(
            pin="558023",
            sms_provider="smsbower",
            smsbower_config={
                "api_key": "smsbower-key",
                "base_url": "https://smsbower.example.test/stubs/handler_api.php",
                "country": "6",
                "service": "ni",
            },
            public_base_url="http://127.0.0.1:8787",
        )

    assert "无法访问客户端 API" in str(exc_info.value)
    assert requests == [("getBalance", {})]


def test_hero_get_number_filters_min_price_and_prefers_configured_tier(monkeypatch):
    requests = []

    def fake_hero_request(_base_url, _api_key, action, params=None, **_kwargs):
        requests.append((action, dict(params or {})))
        if action == "getPricesExtended":
            return (
                True,
                '{"6":{"ni":[{"cost":"$0.0618","count":2},{"cost":0.08,"count":3},{"cost":0.12,"count":1}]}}',
                {
                    "6": {
                        "ni": [
                            {"cost": "$0.0618", "count": 2},
                            {"cost": 0.08, "count": 3},
                            {"cost": 0.12, "count": 1},
                        ]
                    }
                },
            )
        if action == "getPrices":
            return (
                True,
                '{"6":{"ni":{"low":{"cost":0.04,"count":8},"mid":{"cost":0.08,"count":3},"high":{"cost":0.12,"count":1}}}}',
                {
                    "6": {
                        "ni": {
                            "low": {"cost": 0.04, "count": 8},
                            "mid": {"cost": 0.08, "count": 3},
                            "high": {"cost": 0.12, "count": 1},
                        }
                    }
                },
            )
        if action == "getNumber":
            if str((params or {}).get("price")) == "0.08":
                return True, "ACCESS_NUMBER:activation-hero:6287712345678", None
            return False, "NO_NUMBERS", None
        raise AssertionError(action)

    monkeypatch.setattr(gopay_auto_register, "_hero_request", fake_hero_request)

    activation_id, phone, error = gopay_auto_register._hero_get_number(
        service_code="ni",
        country_id=6,
        base_url="https://hero-sms.example.test",
        api_key="hero-key",
        min_price="0.06",
        max_price="0.12",
        preferred_price="0.08",
    )

    assert error == ""
    assert activation_id == "activation-hero"
    assert phone == "6287712345678"
    assert requests == [
        ("getPricesExtended", {"service": "ni", "country": 6, "freePrice": "true"}),
        ("getPrices", {"service": "ni", "country": 6}),
        ("getPricesForVerification", {"service": "ni", "country": 6}),
        ("getTopCountriesByService", {"service": "ni", "freePrice": "true"}),
        ("getPricesVerification", {"service": "ni", "country": 6}),
        ("getNumber", {"service": "ni", "price": "0.08", "country": 6}),
    ]


def test_hero_price_query_merges_extended_tiers_and_prefers_configured_tier(monkeypatch):
    def fake_hero_request(_base_url, _api_key, action, params=None, **_kwargs):
        if action == "getPricesExtended":
            return (
                True,
                "",
                {
                    "6": {
                        "ni": [
                            {"cost": "$0.5295", "count": 1},
                            {"cost": "$0.0618", "count": 5},
                            {"cost": "$0.0473", "count": 2},
                        ]
                    }
                },
            )
        if action == "getPrices":
            return True, "", {"6": {"ni": {"0.045": 10}}}
        raise AssertionError(action)

    monkeypatch.setattr(gopay_auto_register, "_hero_request", fake_hero_request)

    result = gopay_auto_register.query_hero_sms_price_tiers(
        service_code="ni",
        country_id=6,
        base_url="https://hero-sms.example.test",
        api_key="hero-key",
        min_price="0.045",
        max_price="0.12",
        preferred_price="0.0618",
    )

    assert result["ok"] is True
    assert result["prices"] == [0.045, 0.0473, 0.0618, 0.5295]
    assert result["filtered_prices"] == [0.0618]


def test_hero_price_query_uses_configured_tier_even_when_legacy_api_only_returns_floor(monkeypatch):
    def fake_hero_request(_base_url, _api_key, action, params=None, **_kwargs):
        if action == "getPricesExtended":
            return False, '{"title":"BAD_ACTION","details":"Method Not Found"}', {
                "title": "BAD_ACTION",
                "details": "Method Not Found",
            }
        if action == "getPrices":
            return True, "", {"6": {"ni": {"cost": 0.045, "count": 3526, "physicalCount": 183}}}
        raise AssertionError(action)

    monkeypatch.setattr(gopay_auto_register, "_hero_request", fake_hero_request)

    result = gopay_auto_register.query_hero_sms_price_tiers(
        service_code="ni",
        country_id=6,
        base_url="https://hero-sms.example.test",
        api_key="hero-key",
        min_price="",
        max_price="0.1",
        preferred_price="0.0618",
    )

    assert result["ok"] is True
    assert result["prices"] == [0.045]
    assert result["filtered_prices"] == [0.0618]


def test_hero_get_number_uses_price_plan_when_only_max_price_is_configured(monkeypatch):
    requests = []

    def fake_hero_request(_base_url, _api_key, action, params=None, **_kwargs):
        requests.append((action, dict(params or {})))
        if action == "getPricesExtended":
            return False, "BAD_ACTION", None
        if action == "getPricesForVerification":
            return False, "BAD_ACTION", None
        if action == "getPricesVerification":
            return False, "BAD_ACTION", None
        if action == "getPrices":
            return True, "", {"6": {"ni": {"cost": 0.045, "count": 10, "physicalCount": 10}}}
        if action == "getTopCountriesByService":
            return True, "", {
                "0": {
                    "country": 6,
                    "freePriceMap": {
                        "0.0450": 10,
                        "0.0618": 20,
                        "0.1037": 30,
                    },
                }
            }
        if action == "getNumber":
            if str((params or {}).get("price")) == "0.045":
                return False, "NO_NUMBERS", None
            if str((params or {}).get("price")) == "0.0618":
                return True, "ACCESS_NUMBER:activation-hero:6287712345678", None
            return False, "NO_NUMBERS", None
        raise AssertionError(action)

    monkeypatch.setattr(gopay_auto_register, "_hero_request", fake_hero_request)

    activation_id, phone, error = gopay_auto_register._hero_get_number(
        service_code="ni",
        country_id=6,
        base_url="https://hero-sms.example.test",
        api_key="hero-key",
        max_price="0.1",
    )

    assert error == ""
    assert activation_id == "activation-hero"
    assert phone == "6287712345678"
    get_number_requests = [params for action, params in requests if action == "getNumber"]
    assert get_number_requests == [
        {"service": "ni", "price": "0.045", "country": 6},
        {"service": "ni", "price": "0.0618", "country": 6},
    ]


def test_hero_price_query_rejects_reversed_range(monkeypatch):
    monkeypatch.setattr(
        gopay_auto_register,
        "_hero_request",
        lambda *_args, **_kwargs: (True, "", {"6": {"ni": {"tier": {"cost": 0.08, "count": 1}}}}),
    )

    result = gopay_auto_register.query_hero_sms_price_tiers(
        service_code="ni",
        country_id=6,
        base_url="https://hero-sms.example.test",
        api_key="hero-key",
        min_price="0.2",
        max_price="0.1",
    )

    assert result["ok"] is False
    assert "价格区间无效" in result["error"]


def test_sms_bridge_payload_resend_calls_smscloud_resend(monkeypatch):
    resend_calls = []

    monkeypatch.setattr(
        gopay_auto_register,
        "_smscloud_resend",
        lambda base_url, token, activation_id: resend_calls.append((base_url, token, activation_id)),
    )
    monkeypatch.setattr(
        gopay_auto_register,
        "_smscloud_latest_code",
        lambda *_args, **_kwargs: (False, "", "pending"),
    )

    bridge = gopay_auto_register.GoPaySmsBridge(
        token="bridge-smscloud",
        activation_id="activation-smscloud",
        base_url="https://smscloud.example.test/api",
        api_key="smscloud-key",
        provider="smscloud",
    )
    with gopay_auto_register._BRIDGE_LOCK:
        gopay_auto_register._SMS_BRIDGES[bridge.token] = bridge
    try:
        payload = gopay_auto_register.get_sms_bridge_payload(bridge.token, resend=True)
    finally:
        with gopay_auto_register._BRIDGE_LOCK:
            gopay_auto_register._SMS_BRIDGES.pop(bridge.token, None)

    assert payload == {"ok": False, "data": {"status": "pending"}}
    assert resend_calls == [("https://smscloud.example.test/api", "smscloud-key", "activation-smscloud")]


def test_smscode_get_number_selects_lowest_filtered_product(monkeypatch):
    requests = []

    def fake_smscode_request(_base_url, _api_token, method, path, **kwargs):
        requests.append((method, path, kwargs.get("params"), kwargs.get("data")))
        if path == "/catalog/services":
            return True, [{"id": "platform-gopay", "name": "GoPay"}], ""
        if path == "/catalog/products":
            return True, [
                {"id": "expensive", "price": 0.25, "available": 10},
                {"id": "cheap", "price": 0.08, "available": 3},
                {"id": "too-cheap", "price": 0.02, "available": 99},
                {"id": "empty", "price": 0.06, "available": 0},
            ], ""
        if path == "/orders/create":
            assert kwargs.get("data") == {"product_id": "cheap", "quantity": 1}
            return True, {"id": "order-1", "phone_number": "+6287712345678"}, ""
        raise AssertionError(path)

    monkeypatch.setattr(gopay_auto_register, "_smscode_request", fake_smscode_request)

    activation_id, phone, error = gopay_auto_register._smscode_get_number(
        base_url="https://api.smscode.example/v1",
        api_token="smscode-token",
        country_id="7",
        platform_query="gopay",
        min_price="0.05",
        max_price="0.1",
    )

    assert error == ""
    assert activation_id == "order-1"
    assert phone == "+6287712345678"
    assert requests[:2] == [
        ("get", "/catalog/services", {"country_id": "7"}, None),
        ("get", "/catalog/products", {"country_id": "7", "platform_id": "platform-gopay"}, None),
    ]


def test_smscode_get_number_defaults_to_gojek_platform(monkeypatch):
    requests = []

    def fake_smscode_request(_base_url, _api_token, method, path, **kwargs):
        requests.append((method, path, kwargs.get("params"), kwargs.get("data")))
        if path == "/catalog/services":
            return True, [{"id": "platform-gojek", "name": "Gojek"}], ""
        if path == "/catalog/products":
            return True, [{"id": "632495247", "price": 1002, "available": 5}], ""
        if path == "/orders/create":
            assert kwargs.get("data") == {"product_id": 632495247, "quantity": 1}
            return True, {"id": "order-gojek", "phone_number": "+6287712345678"}, ""
        raise AssertionError(path)

    monkeypatch.setattr(gopay_auto_register, "_smscode_request", fake_smscode_request)

    activation_id, phone, error = gopay_auto_register._smscode_get_number(
        base_url="https://api.smscode.example/v1",
        api_token="smscode-token",
        country_id="7",
    )

    assert error == ""
    assert activation_id == "order-gojek"
    assert phone == "+6287712345678"
    assert requests[:2] == [
        ("get", "/catalog/services", {"country_id": "7"}, None),
        ("get", "/catalog/products", {"country_id": "7", "platform_id": "platform-gojek"}, None),
    ]


def test_sms_bridge_payload_resend_calls_smscode_resend(monkeypatch):
    resend_calls = []

    monkeypatch.setattr(
        gopay_auto_register,
        "_smscode_resend",
        lambda base_url, token, activation_id: resend_calls.append((base_url, token, activation_id)),
    )
    monkeypatch.setattr(
        gopay_auto_register,
        "_smscode_latest_code",
        lambda *_args, **_kwargs: (False, "", "pending"),
    )

    bridge = gopay_auto_register.GoPaySmsBridge(
        token="bridge-smscode",
        activation_id="activation-smscode",
        base_url="https://api.smscode.example/v1",
        api_key="smscode-token",
        provider="smscode",
    )
    with gopay_auto_register._BRIDGE_LOCK:
        gopay_auto_register._SMS_BRIDGES[bridge.token] = bridge
    try:
        payload = gopay_auto_register.get_sms_bridge_payload(bridge.token, resend=True)
    finally:
        with gopay_auto_register._BRIDGE_LOCK:
            gopay_auto_register._SMS_BRIDGES.pop(bridge.token, None)

    assert payload == {"ok": False, "data": {"status": "pending"}}
    assert resend_calls == [("https://api.smscode.example/v1", "smscode-token", "activation-smscode")]


def test_smscode_order_action_sends_numeric_id(monkeypatch):
    requests = []

    def fake_smscode_request(_base_url, _api_token, method, path, **kwargs):
        requests.append((method, path, kwargs.get("data")))
        return True, {}, ""

    monkeypatch.setattr(gopay_auto_register, "_smscode_request", fake_smscode_request)

    gopay_auto_register._smscode_resend("https://api.smscode.example/v1", "smscode-token", "1833029")
    gopay_auto_register._smscode_finish("https://api.smscode.example/v1", "smscode-token", "order-abc")

    assert requests == [
        ("post", "/orders/resend", {"id": 1833029}),
        ("post", "/orders/finish", {"id": "order-abc"}),
    ]


def test_sms_bridge_reusable_rejects_missing_or_closed_bridge():
    assert gopay_auto_register.is_sms_bridge_reusable("missing-token") == (False, "bridge_missing")

    bridge = gopay_auto_register.GoPaySmsBridge(
        token="bridge-closed",
        activation_id="activation-closed",
        base_url="https://hero-sms.example.test",
        api_key="hero-key",
        provider="hero_sms",
        closed=True,
    )
    with gopay_auto_register._BRIDGE_LOCK:
        gopay_auto_register._SMS_BRIDGES[bridge.token] = bridge
    try:
        assert gopay_auto_register.is_sms_bridge_reusable(bridge.token) == (False, "closed")
    finally:
        with gopay_auto_register._BRIDGE_LOCK:
            gopay_auto_register._SMS_BRIDGES.pop(bridge.token, None)


def test_sms_bridge_reusable_rejects_hero_terminal_status(monkeypatch):
    monkeypatch.setattr(
        gopay_auto_register,
        "_hero_request",
        lambda *_args, **_kwargs: (True, "STATUS_CANCEL", None),
    )
    bridge = gopay_auto_register.GoPaySmsBridge(
        token="bridge-cancelled",
        activation_id="activation-cancelled",
        base_url="https://hero-sms.example.test",
        api_key="hero-key",
        provider="hero_sms",
    )
    with gopay_auto_register._BRIDGE_LOCK:
        gopay_auto_register._SMS_BRIDGES[bridge.token] = bridge
    try:
        reusable, reason = gopay_auto_register.is_sms_bridge_reusable(bridge.token)
    finally:
        with gopay_auto_register._BRIDGE_LOCK:
            gopay_auto_register._SMS_BRIDGES.pop(bridge.token, None)

    assert reusable is False
    assert reason == "STATUS_CANCEL"


def test_sms_bridge_reusable_rejects_smscloud_finished_order(monkeypatch):
    monkeypatch.setattr(
        gopay_auto_register,
        "_smscloud_request",
        lambda *_args, **_kwargs: (
            True,
            {"rows": [{"id": "activation-smscloud", "status": "finished"}]},
            "",
        ),
    )
    bridge = gopay_auto_register.GoPaySmsBridge(
        token="bridge-smscloud-finished",
        activation_id="activation-smscloud",
        base_url="https://smscloud.example.test/api",
        api_key="smscloud-key",
        provider="smscloud",
    )
    with gopay_auto_register._BRIDGE_LOCK:
        gopay_auto_register._SMS_BRIDGES[bridge.token] = bridge
    try:
        reusable, reason = gopay_auto_register.is_sms_bridge_reusable(bridge.token)
    finally:
        with gopay_auto_register._BRIDGE_LOCK:
            gopay_auto_register._SMS_BRIDGES.pop(bridge.token, None)

    assert reusable is False
    assert "finished" in reason


def test_register_gopay_wallet_rejects_existing_number_without_auto_login(monkeypatch):
    monkeypatch.setenv("GOPAY_AUTO_SIGNUP_SMSCLOUD_XI_TOKEN", "xi-token")
    monkeypatch.setenv("GOPAY_AUTO_SIGNUP_REQUIRE_PROXY", "0")
    monkeypatch.setattr(
        gopay_auto_register,
        "_smscloud_get_number",
        lambda **_kwargs: ("activation-1", "+6287712343287", ""),
    )

    calls = {"auto_login": 0, "cancel": 0, "delayed_cancel": 0}

    def fake_auto_signup(**_kwargs):
        raise gopay_auto_register.GoPayNumberAlreadyRegistered("号码已存在 GoPay 钱包")

    def fake_auto_login(**_kwargs):
        calls["auto_login"] += 1

    def fake_cancel(_base_url, _token, _activation_id):
        calls["cancel"] += 1

    def fake_delayed_cancel(_activation, **_kwargs):
        calls["delayed_cancel"] += 1

    monkeypatch.setattr(gopay_auto_register, "auto_signup", fake_auto_signup)
    monkeypatch.setattr(gopay_auto_register, "auto_login", fake_auto_login)
    monkeypatch.setattr(gopay_auto_register, "_smscloud_cancel", fake_cancel)
    monkeypatch.setattr(gopay_auto_register, "_delayed_cancel_activation", fake_delayed_cancel)

    with pytest.raises(gopay_auto_register.GoPayNumberAlreadyRegistered, match="无法保证 PIN"):
        gopay_auto_register.register_gopay_wallet(pin="558023", sms_provider="smscloud")

    assert calls["auto_login"] == 0
    assert calls["cancel"] == 0
    assert calls["delayed_cancel"] == 1


def test_register_gopay_wallet_probe_error_cancels_without_delayed_existing_flow(monkeypatch):
    monkeypatch.setenv("GOPAY_AUTO_SIGNUP_SMSCLOUD_XI_TOKEN", "xi-token")
    monkeypatch.setenv("GOPAY_AUTO_SIGNUP_REQUIRE_PROXY", "0")
    monkeypatch.setattr(
        gopay_auto_register,
        "_smscloud_get_number",
        lambda **_kwargs: ("activation-1", "+6287712343287", ""),
    )

    calls = {"cancel": 0, "delayed_cancel": 0}

    def fake_auto_signup(**_kwargs):
        raise gopay_auto_register.GoPaySignupProbeError("GoPay 注册前探测异常: status=403")

    def fake_cancel(_base_url, _token, _activation_id):
        calls["cancel"] += 1

    def fake_delayed_cancel(_activation, **_kwargs):
        calls["delayed_cancel"] += 1

    monkeypatch.setattr(gopay_auto_register, "auto_signup", fake_auto_signup)
    monkeypatch.setattr(gopay_auto_register, "_smscloud_cancel", fake_cancel)
    monkeypatch.setattr(gopay_auto_register, "_delayed_cancel_activation", fake_delayed_cancel)

    with pytest.raises(gopay_auto_register.GoPaySignupProbeError, match="探测异常"):
        gopay_auto_register.register_gopay_wallet(pin="558023", sms_provider="smscloud")

    assert calls["cancel"] == 1
    assert calls["delayed_cancel"] == 0


def test_register_gopay_wallet_retries_network_error_with_same_number(monkeypatch):
    monkeypatch.setenv("GOPAY_AUTO_SIGNUP_SMSCLOUD_XI_TOKEN", "xi-token")
    monkeypatch.setenv("GOPAY_AUTO_SIGNUP_CURRENT_NUMBER_NETWORK_ATTEMPTS", "2")
    monkeypatch.setenv("GOPAY_AUTO_SIGNUP_REQUIRE_PROXY", "0")

    calls = {"get_number": 0, "auto_signup": 0, "cancel": 0, "logs": []}

    def fake_get_number(**_kwargs):
        calls["get_number"] += 1
        return ("activation-1", "+6287712343287", "")

    def fake_auto_signup(**kwargs):
        calls["auto_signup"] += 1
        assert kwargs["phone"] == "87712343287"
        if calls["auto_signup"] == 1:
            raise RuntimeError(
                "Failed to perform, curl: (97) Recv failure: Connection was reset. "
                "See https://curl.se/libcurl/c/libcurl-errors.html first for more details."
            )
        return gopay_auto_register.GoPayAccountResult(
            access_token="access-token",
            refresh_token="refresh-token",
            account_id="account-id",
            phone=kwargs["phone"],
            country_code=kwargs["country_code"],
            pin=kwargs["pin"],
            session=object(),
            gopay_cfg=kwargs["gopay_cfg"],
        )

    def fake_cancel(_base_url, _token, _activation_id):
        calls["cancel"] += 1

    monkeypatch.setattr(gopay_auto_register, "_smscloud_get_number", fake_get_number)
    monkeypatch.setattr(gopay_auto_register, "auto_signup", fake_auto_signup)
    monkeypatch.setattr(gopay_auto_register, "_smscloud_cancel", fake_cancel)
    monkeypatch.setattr(gopay_auto_register.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(gopay_auto_register, "create_sms_bridge", lambda activation: gopay_auto_register.GoPaySmsBridge(
        token="bridge-token",
        activation_id=activation.activation_id,
        base_url=activation.base_url,
        api_key=activation.api_key,
        provider=activation.provider,
    ))

    result = gopay_auto_register.register_gopay_wallet(
        pin="558023",
        sms_provider="smscloud",
        log=lambda message: calls["logs"].append(message),
    )

    assert calls["get_number"] == 1
    assert calls["auto_signup"] == 2
    assert calls["cancel"] == 0
    assert result.phone_number == "87712343287"
    assert any("使用当前号码重试" in message for message in calls["logs"])


def test_create_gopay_session_uses_stable_tls_profile_without_proxy_rotation(monkeypatch):
    captured = {}

    class FakeCurlSession:
        def __init__(self, *, impersonate):
            captured["impersonate"] = impersonate
            self.proxies = {}
            self.trust_env = True

    monkeypatch.setattr(gopay_auto_register, "CurlCffiSession", FakeCurlSession)
    monkeypatch.setattr(gopay_auto_register, "normalize_proxy_url", lambda value: value)

    session = gopay_auto_register.create_gopay_session(
        "socks5://user-sid-stable-session-id-region@proxy.example.test:1080"
    )

    assert captured["impersonate"] == "chrome136"
    assert session.trust_env is False
    assert session.proxies == {
        "http": "socks5://user-sid-stable-session-id-region@proxy.example.test:1080",
        "https": "socks5://user-sid-stable-session-id-region@proxy.example.test:1080",
    }


def test_build_gopay_app_headers_uses_stable_request_fingerprint(monkeypatch):
    monkeypatch.setattr(gopay_auto_register.uuid, "uuid1", lambda: "uuid1-request")
    monkeypatch.setattr(gopay_auto_register.random, "randint", lambda *_args: 42)

    headers = gopay_auto_register.build_gopay_app_headers(
        gopay_cfg={
            "_device_fingerprint_initialized": True,
            "_fp_location": "-6.2,106.8",
            "_fp_unique_id": "unique-id",
            "_fp_phone_make": "Samsung",
            "_fp_phone_model": "Samsung, SM-G991B",
            "_fp_device_os": "Android, 13",
            "_fp_x_m1": "x-m1",
            "_fp_transaction_id": "transaction-id",
        }
    )

    assert headers["accept-encoding"] == "gzip"
    assert headers["x-location"] == "-6.2,106.8"
    assert headers["x-location-accuracy"] == "0.042999999552965164"
    assert headers["x-request-id"] == "uuid1-request"
    assert "x-devicetoken" not in headers


def test_register_gopay_wallet_requires_proxy_before_taking_number(monkeypatch):
    monkeypatch.setenv("GOPAY_AUTO_SIGNUP_SMSCLOUD_XI_TOKEN", "xi-token")
    monkeypatch.delenv("GOPAY_AUTO_SIGNUP_PROXY_URL", raising=False)
    calls = {"get_number": 0}

    def fake_get_number(**_kwargs):
        calls["get_number"] += 1
        return ("activation-1", "+6287712343287", "")

    monkeypatch.setattr(gopay_auto_register, "_smscloud_get_number", fake_get_number)

    with pytest.raises(gopay_auto_register.GoPayAutoSignupError, match="需要配置印尼代理"):
        gopay_auto_register.register_gopay_wallet(pin="558023", sms_provider="smscloud")

    assert calls["get_number"] == 0


def test_auto_signup_matches_current_gopay_app_register_sequence(monkeypatch):
    class FakeResponse:
        def __init__(self, status_code=200, payload=None, text="{}"):
            self.status_code = status_code
            self._payload = payload if payload is not None else {"success": True}
            self.text = text

        def json(self):
            return self._payload

    class FakeSession:
        def __init__(self):
            self.posts = []

        def post(self, url, **kwargs):
            self.posts.append((url, kwargs))
            return FakeResponse(200, {"data": {"token": "pin-token"}, "success": True})

    session = FakeSession()
    calls = []

    def fake_signed_post(url, body, **kwargs):
        calls.append((url, body, kwargs))
        if url.endswith("/cvs/v1/methods"):
            return FakeResponse(200, {"data": {"verification_id": f"verification-{body['flow']}"}})
        if url.endswith("/cvs/v1/initiate"):
            return FakeResponse(200, {"data": {"otp_token": f"otp-{body['flow']}"}})
        if url.endswith("/cvs/v1/verify"):
            return FakeResponse(200, {"data": {"verification_token": f"token-{body['flow']}"}})
        if url.endswith("/v7/customers/signup"):
            return FakeResponse(
                201,
                {
                    "data": {
                        "resource_owner_id": 123,
                        "access_token": "signup-access",
                        "refresh_token": "signup-refresh",
                    },
                    "success": True,
                },
            )
        if url.endswith("/goto-auth/token"):
            return FakeResponse(
                201,
                {"data": {"access_token": "access-2", "refresh_token": "refresh-2"}, "success": True},
            )
        if url.endswith("/api/v2/consents/accept"):
            return FakeResponse(200, {"success": True})
        if url.endswith("/api/v1/users/pins/allowed"):
            return FakeResponse(200, {"success": True, "errors": []})
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(gopay_auto_register, "create_gopay_session", lambda _proxy_url: session)
    monkeypatch.setattr(gopay_auto_register, "signed_post", fake_signed_post)
    monkeypatch.setattr(gopay_auto_register.time, "sleep", lambda _seconds: None)

    result = gopay_auto_register.auto_signup(
        phone="877999991234",
        country_code="+62",
        pin="558023",
        otp_provider=lambda _label: "1234",
    )

    assert result.access_token == "access-2"
    token_calls = [body for url, body, _kwargs in calls if url.endswith("/goto-auth/token")]
    assert token_calls == [
        {
            "grant_type": "refresh_token",
            "token": "signup-refresh",
            "client_id": gopay_auto_register.CLIENT_ID,
            "client_secret": gopay_auto_register.CLIENT_SECRET,
        }
    ]
    called_urls = [url for url, _body, _kwargs in calls]
    assert not any(url.endswith("/goto-auth/login/methods") for url in called_urls)
    assert called_urls.index(f"{gopay_auto_register.CUSTOMER_URL}/api/v2/consents/accept") < called_urls.index(
        f"{gopay_auto_register.CUSTOMER_URL}/api/v1/users/pins/allowed"
    )
    assert session.posts[0][0].endswith("/api/v2/users/pins/setup/tokens")
    signup_cvs_calls = [
        kwargs
        for url, body, kwargs in calls
        if url.endswith(("/cvs/v1/methods", "/cvs/v1/initiate")) and body["flow"] == "signup"
    ]
    assert signup_cvs_calls[0]["authorization"] == ""
    assert signup_cvs_calls[0]["keep_auth"] is True
    assert signup_cvs_calls[1]["authorization"] == ""
    assert signup_cvs_calls[1]["keep_auth"] is True
    assert signup_cvs_calls[1]["extra_headers"] == {"key": "value"}


def test_auto_signup_does_not_retry_initiate_rate_limit(monkeypatch):
    class FakeResponse:
        def __init__(self, status_code, payload, text="{}"):
            self.status_code = status_code
            self._payload = payload
            self.text = text
            self.headers = {"ratelimit-reset": "600"}

        def json(self):
            return self._payload

    calls = []
    sleeps = []

    def fake_signed_post(url, *_args, **_kwargs):
        calls.append(url)
        if url.endswith("/cvs/v1/methods"):
            return FakeResponse(200, {"data": {"verification_id": "verification-1"}})
        if url.endswith("/cvs/v1/initiate"):
            return FakeResponse(429, {}, "rate limited")
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(gopay_auto_register, "create_gopay_session", lambda _proxy_url: object())
    monkeypatch.setattr(gopay_auto_register, "signed_post", fake_signed_post)
    monkeypatch.setattr(gopay_auto_register.time, "sleep", lambda seconds: sleeps.append(seconds))

    with pytest.raises(gopay_auto_register.GoPayAutoSignupError, match="signup initiate 未返回 otp_token"):
        gopay_auto_register.auto_signup(
            phone="877999991234",
            country_code="+62",
            pin="558023",
            otp_provider=lambda _label: "",
        )

    assert sum(1 for url in calls if url.endswith("/cvs/v1/initiate")) == 1
    assert not any(url.endswith("/goto-auth/login/methods") for url in calls)
    assert len(sleeps) == 2


def test_auto_signup_classifies_existing_wallet_without_login_probe(monkeypatch):
    class FakeResponse:
        status_code = 201
        text = (
            '{"data":{"default_method":"goto_pin","methods":["goto_pin","otp_sms"],'
            '"phone_number":"83116131986","country_code":"+62"},"success":true,"errors":[]}'
        )

        def json(self):
            return {
                "data": {
                    "default_method": "goto_pin",
                    "methods": ["goto_pin", "otp_sms"],
                    "phone_number": "83116131986",
                    "country_code": "+62",
                },
                "success": True,
                "errors": [],
            }

    monkeypatch.setattr(gopay_auto_register, "create_gopay_session", lambda _proxy_url: object())
    calls = []

    def fake_signed_post(url, *_args, **_kwargs):
        calls.append(url)
        if url.endswith("/cvs/v1/methods"):
            return FakeResponse()
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(gopay_auto_register, "signed_post", fake_signed_post)

    with pytest.raises(gopay_auto_register.GoPayNumberAlreadyRegistered, match="已存在 GoPay 钱包"):
        gopay_auto_register.auto_signup(
            phone="83116131986",
            country_code="+62",
            pin="558023",
            otp_provider=lambda _label: "",
        )
    assert calls == [f"{gopay_auto_register.BASE_URL}/cvs/v1/methods"]


def test_auto_signup_classifies_inconclusive_probe(monkeypatch):
    class FakeResponse:
        status_code = 403
        text = '{"success":false,"errors":[{"code":"auth:error:blocked"}]}'

        def json(self):
            return {"success": False, "errors": [{"code": "auth:error:blocked"}]}

    monkeypatch.setattr(gopay_auto_register, "create_gopay_session", lambda _proxy_url: object())
    monkeypatch.setattr(gopay_auto_register, "signed_post", lambda *_args, **_kwargs: FakeResponse())

    with pytest.raises(gopay_auto_register.GoPaySignupProbeError, match="auth:error:blocked"):
        gopay_auto_register.auto_signup(
            phone="877999991234",
            country_code="+62",
            pin="558023",
            otp_provider=lambda _label: "",
        )


def test_query_gopay_balance_extracts_gopay_wallet(monkeypatch):
    class FakeResponse:
        status_code = 200
        text = "{}"

        def json(self):
            return {
                "success": True,
                "data": [
                    {"type": "OTHER", "balance": {"value": 0, "currency": "IDR", "display_value": "Rp0"}},
                    {"type": "GOPAY_WALLET", "balance": {"value": 1, "currency": "IDR", "display_value": "Rp1"}},
                ],
            }

    captured = {}

    def fake_signed_get(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return FakeResponse()

    monkeypatch.setattr(gopay_auto_register, "signed_get", fake_signed_get)

    result = gopay_auto_register.query_gopay_balance(access_token="token-1", gopay_cfg={"unique_id": "device-1"})

    assert result["value"] == 1
    assert result["display_value"] == "Rp1"
    assert result["type"] == "GOPAY_WALLET"
    assert captured["url"].endswith("/v1/payment-options/balances")
    assert captured["kwargs"]["authorization"] == "Bearer token-1"
    assert captured["kwargs"]["keep_auth"] is True

def test_hero_get_number_passes_max_price(monkeypatch):
    captured = {}

    def fake_hero_request(base_url, api_key, action, params=None, **kwargs):
        captured.update(
            {
                "base_url": base_url,
                "api_key": api_key,
                "action": action,
                "params": params,
                "kwargs": kwargs,
            }
        )
        return True, "ACCESS_NUMBER:activation-1:6287712345678", None

    monkeypatch.setattr(gopay_auto_register, "_hero_request", fake_hero_request)

    activation_id, phone, error = gopay_auto_register._hero_get_number(
        service_code="ni",
        country_id=6,
        base_url="https://api.hero-sms.com",
        api_key="hero-key",
        max_price="0.045",
    )

    assert activation_id == "activation-1"
    assert phone == "6287712345678"
    assert error == ""
    assert captured["action"] == "getNumber"
    assert captured["params"] == {"service": "ni", "country": 6, "maxPrice": "0.045"}
