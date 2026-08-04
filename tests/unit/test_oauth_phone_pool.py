from autotoken import codex_auth, oauth_phone_pool, protocol_register


def test_import_dedupes_by_phone_key(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))

    result = oauth_phone_pool.import_phones(
        "\n".join(
            [
                "+17328582987-------https://sms.example/a",
                "+1 (732) 858-2987----https://sms.example/duplicate",
                "+17328582988----https://sms.example/b",
            ]
        )
    )

    assert result["added_count"] == 2
    assert result["skipped_count"] == 1
    assert [item["phone_number"] for item in oauth_phone_pool.list_phones()] == [
        "+17328582988",
        "+17328582987",
    ]


def test_import_accepts_pipe_smscloud_format_and_keeps_us_country_code(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))

    result = oauth_phone_pool.import_phones(
        "12096968188|https://smscloud.sbs/api/system/get_sms/7ebf82030f3c461fbe75fbe0d1ae65b7"
    )

    assert result["added_count"] == 1
    item = oauth_phone_pool.list_phones()[0]
    assert item["phone_number"] == "+12096968188"
    assert item["phone_key"] == "12096968188"
    assert item["sms_url"] == "https://smscloud.sbs/api/system/get_sms/7ebf82030f3c461fbe75fbe0d1ae65b7"


def test_import_accepts_single_dash_before_sms_url(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))

    result = oauth_phone_pool.import_phones(
        "08024204085 - https://api.yamasakisms.com/api/private/getphonecode?order_no=453368427625598976"
    )

    assert result["added_count"] == 1
    item = oauth_phone_pool.list_phones()[0]
    assert item["phone_number"] == "+08024204085"
    assert item["phone_key"] == "08024204085"
    assert item["sms_url"] == "https://api.yamasakisms.com/api/private/getphonecode?order_no=453368427625598976"


def test_bound_count_reaches_full_and_is_not_acquired(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    item = oauth_phone_pool.upsert_phone(
        {
            "phone_number": "+17328582987",
            "sms_url": "https://sms.example/a",
            "bound_count": 2,
        }
    )

    bound = oauth_phone_pool.mark_phone_bound(item["id"], "first@example.com")
    assert bound["bound_count"] == 3
    assert bound["status"] == "full"
    assert oauth_phone_pool.acquire_available_phone("second@example.com") is None


def test_email_normalization_is_shared_for_bound_and_reserved_emails(monkeypatch, tmp_path):
    from autotoken.core.normalization import normalized_email

    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    item = oauth_phone_pool.upsert_phone(
        {
            "phone_number": "+17328582987",
            "sms_url": "https://sms.example/a",
            "bound_emails": [" USER@Example.com ", "user@example.com"],
            "reserved_by_email": " OTHER@Example.com ",
        }
    )

    listed = oauth_phone_pool.list_phones()[0]
    assert listed["bound_emails"] == [normalized_email(" USER@Example.com ")]
    assert listed["reserved_by"] == normalized_email(" OTHER@Example.com ")

    reserved = oauth_phone_pool.release_phone_reservation(item["id"], "other@example.com")
    assert reserved["reserved_by"] == ""

    rebound = oauth_phone_pool.mark_phone_bound(item["id"], " Second@Example.com ")
    assert "second@example.com" in rebound["bound_emails"]


def test_invalid_phone_is_not_acquired(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    item = oauth_phone_pool.upsert_phone(
        {
            "phone_number": "+17328582987",
            "sms_url": "https://sms.example/a",
        }
    )

    oauth_phone_pool.mark_phone_invalid(item["id"], "try a different phone")

    assert oauth_phone_pool.acquire_available_phone("next@example.com") is None
    listed = oauth_phone_pool.list_phones()[0]
    assert listed["status"] == "invalid"
    assert listed["invalid_reason"] == "try a different phone"


def test_cooldown_phone_is_not_acquired_until_expired(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    item = oauth_phone_pool.upsert_phone(
        {
            "phone_number": "+17328582987",
            "sms_url": "https://sms.example/a",
        }
    )

    cooled = oauth_phone_pool.mark_phone_cooldown(item["id"], "too many requests", seconds=120)

    assert cooled["status"] == "cooldown"
    assert cooled["cooldown_remaining_seconds"] > 0
    assert oauth_phone_pool.acquire_available_phone("next@example.com") is None

    oauth_phone_pool.update_phone(item["id"], {"status": "cooldown", "cooldown_until": 1})

    acquired = oauth_phone_pool.acquire_available_phone("next@example.com")
    assert acquired["id"] == item["id"]
    assert acquired["status"] == "available"


def test_codex_oauth_phone_failure_classification():
    assert (
        codex_auth._classify_oauth_phone_failure("此电话号码已关联到可关联的最多账户。")
        == "invalid"
    )
    assert (
        codex_auth._classify_oauth_phone_failure("无法向此电话号码发送验证码。请稍后重试或使用其他号码。")
        == "cooldown"
    )
    assert codex_auth._classify_oauth_phone_failure("页面填写失败: 未找到输入框") == ""


def test_codex_oauth_rate_limit_exception_classification_separates_account_and_phone():
    assert (
        codex_auth._classify_oauth_phone_rate_limit_exception("你请求手机验证的次数过多，请稍后再试。")
        == "account_rate_limited"
    )
    assert (
        codex_auth._classify_oauth_phone_rate_limit_exception("too many attempts, please try again later")
        == "cooldown"
    )
    assert (
        codex_auth._classify_oauth_phone_rate_limit_exception("无法向此电话号码发送验证码。请稍后重试或使用其他号码。")
        == "cooldown"
    )


def test_protocol_phone_pool_rate_limit_failure_cools_down_phone():
    assert protocol_register._phone_pool_failure_action("HTTP 429 - Too many requests") == "cooldown"
    assert protocol_register._phone_pool_failure_action("rate_limit_exceeded") == "cooldown"
    assert protocol_register._phone_pool_failure_action("fraud_guard: phone numbers similar to yours") == "cooldown"
    assert protocol_register._phone_pool_failure_action("PHONE_NUMBER_IN_USE: 手机号已被使用") == "invalid"
    assert protocol_register._phone_pool_failure_action("temporary network error") == "release"


def test_codex_oauth_hero_sms_acquire_and_otp_provider(monkeypatch, tmp_path):
    from autotoken import gopay_auto_register

    captured = {}

    def fake_get_number(**kwargs):
        captured.update(kwargs)
        return "act-1", "+12025550123", ""

    class DummyActivation:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.used_codes = set()

        def wait_code(self, **kwargs):
            self.wait_kwargs = kwargs
            return "654321"

    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setenv("OAUTH_HERO_SMS_API_KEY", "hero-key")
    monkeypatch.setenv("OAUTH_HERO_SMS_COUNTRY", "187")
    monkeypatch.setenv("OAUTH_HERO_SMS_MAX_PRICE", "0.045")
    monkeypatch.setattr(gopay_auto_register, "_hero_get_number", fake_get_number)
    monkeypatch.setattr(gopay_auto_register, "SmsActivation", DummyActivation)
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()

    item, error = codex_auth._acquire_oauth_hero_sms_phone("user@example.com")

    assert error == ""
    assert item["source"] == "hero_sms"
    assert item["phone_number"] == "+12025550123"
    assert captured["service_code"] == "dr"
    assert captured["country_id"] == 187
    assert captured["max_price"] == "0.045"
    provider = codex_auth._make_phone_item_otp_provider(item)
    provider._gopay_ignored_otps = {"111111"}
    assert provider() == "654321"
    assert "111111" in item["activation"].used_codes
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()


def test_codex_oauth_hero_sms_normalizes_openai_alias(monkeypatch):
    monkeypatch.setenv("OAUTH_HERO_SMS_SERVICE", "openai")

    assert codex_auth._oauth_hero_sms_config()["service"] == "dr"


def test_codex_oauth_hero_sms_preserves_numeric_country_id(monkeypatch):
    monkeypatch.setenv("OAUTH_HERO_SMS_COUNTRY", "12")

    assert codex_auth._oauth_hero_sms_config()["country"] == "12"


def test_codex_oauth_hero_sms_config_accepts_max_price_override(monkeypatch):
    monkeypatch.setenv("OAUTH_HERO_SMS_MAX_PRICE", "0.10")

    assert codex_auth._oauth_hero_sms_config(max_price="0.05")["max_price"] == "0.05"


def test_codex_oauth_smscloud_acquires_number(monkeypatch):
    captured = {}

    class FakeActivation:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    def fake_acquire(**kwargs):
        captured.update(kwargs)
        return {
            "id": "order-1",
            "phoneNumber": "447700900123",
            "countryCode": "44",
            "countryPhoneCode": "+44",
            "creditAmount": 0.07,
            "activationEndTime": 2000,
        }, ""

    monkeypatch.setenv("OAUTH_SMSCLOUD_API_KEY", "cloud-key")
    monkeypatch.setenv("OAUTH_SMSCLOUD_COUNTRY", "44")
    monkeypatch.setenv("OAUTH_SMSCLOUD_MAX_PRICE", "0.08")
    monkeypatch.setattr("autotoken.auth.smscloud_sms.acquire_smscloud_number", fake_acquire)
    monkeypatch.setattr("autotoken.auth.smscloud_sms.SMSCloudActivation", FakeActivation)

    item, error = codex_auth._acquire_oauth_smscloud_phone("user@example.com")

    assert error == ""
    assert item["source"] == "smscloud"
    assert item["activation_id"] == "order-1"
    assert item["phone_number"] == "447700900123"
    assert item["country_id"] == "44"
    assert captured["api_key"] == "cloud-key"
    assert captured["country"] == "44"
    assert captured["service"] == "dr"
    assert captured["max_price"] == "0.08"


def test_smscloud_acquire_uses_inventory_price_bucket_for_ceiling(monkeypatch):
    from autotoken.auth import smscloud_sms

    calls = []

    def fake_request(_base_url, _api_key, path, *, params=None):
        params = params or {}
        calls.append((path, dict(params)))
        if path == "/public/sms/getInventory":
            return {
                "code": 0,
                "data": [
                    {
                        "country": 73,
                        "retailPrice": 1.35,
                        "freePriceMap": {"1.63": "0", "1.74": "10", "4.61": "100"},
                    }
                ],
            }
        if path == "/public/sms/flexible":
            price = str(params.get("maxPrice") or "")
            if price in {"1.35", "1.63"}:
                raise RuntimeError("当前国家暂无可用号码，请稍后重试")
            assert price == "1.74"
            return {
                "code": 0,
                "data": {
                    "id": "order-br",
                    "phoneNumber": "551699991234",
                    "countryCode": "73",
                    "countryPhoneCode": "55",
                    "creditAmount": 1.74,
                },
            }
        raise AssertionError(path)

    monkeypatch.setattr(smscloud_sms, "_request_json", fake_request)

    data, error = smscloud_sms.acquire_smscloud_number(
        base_url="https://smscloud.example/api/system",
        api_key="key",
        service="dr",
        country="73",
        max_price="1.75",
    )

    assert error == ""
    assert data["id"] == "order-br"
    assert data["_requestedMaxPrice"] == "1.74"
    assert [params.get("maxPrice") for path, params in calls if path == "/public/sms/flexible"] == [
        "1.35",
        "1.63",
        "1.74",
    ]


def test_smscloud_acquire_reports_attempted_price_buckets_on_no_numbers(monkeypatch):
    from autotoken.auth import smscloud_sms

    def fake_request(_base_url, _api_key, path, *, params=None):
        params = params or {}
        if path == "/public/sms/getInventory":
            return {
                "code": 0,
                "data": [
                    {
                        "country": 33,
                        "retailPrice": 1.5,
                        "freePriceMap": {"1.87": "782", "2.4": "9846", "2.98": "10948", "3": "11363"},
                    }
                ],
            }
        if path == "/public/sms/flexible":
            raise RuntimeError("当前国家暂无可用号码，请稍后重试")
        raise AssertionError(path)

    monkeypatch.setattr(smscloud_sms, "_request_json", fake_request)

    data, error = smscloud_sms.acquire_smscloud_number(
        base_url="https://smscloud.example/api/system",
        api_key="key",
        service="dr",
        country="33",
        max_price="2.99",
    )

    assert data is None
    assert "当前国家暂无可用号码，请稍后重试" in error
    assert "已尝试价档: 1.5, 1.87, 2.4, 2.98" in error


def test_smscloud_acquire_filters_inventory_buckets_by_min_and_max_price(monkeypatch):
    from autotoken.auth import smscloud_sms

    calls = []

    def fake_request(_base_url, _api_key, path, *, params=None):
        params = params or {}
        calls.append((path, dict(params)))
        if path == "/public/sms/getInventory":
            return {
                "code": 0,
                "data": [
                    {
                        "country": 33,
                        "retailPrice": 1.5,
                        "freePriceMap": {"1.87": "782", "2.4": "9846", "2.98": "10948", "3": "11363"},
                    }
                ],
            }
        if path == "/public/sms/flexible":
            raise RuntimeError("当前国家暂无可用号码，请稍后重试")
        raise AssertionError(path)

    monkeypatch.setattr(smscloud_sms, "_request_json", fake_request)

    data, error = smscloud_sms.acquire_smscloud_number(
        base_url="https://smscloud.example/api/system",
        api_key="key",
        service="dr",
        country="33",
        min_price="2.98",
        max_price="2.99",
    )

    assert data is None
    assert [params.get("maxPrice") for path, params in calls if path == "/public/sms/flexible"] == ["2.98"]
    assert "已尝试价档: 2.98" in error
    assert "1.5" not in error


def test_smscloud_wait_code_continues_when_resend_not_supported(monkeypatch):
    from autotoken.auth import smscloud_sms

    state = {"now": 0.0}
    calls = []
    logs = []

    def fake_time():
        return state["now"]

    def fake_sleep(seconds):
        state["now"] += float(seconds)

    def fake_request(_base_url, _api_key, path, *, params=None):
        calls.append(path)
        if "/resend/" in path:
            raise RuntimeError("当前订单状态不支持重发")
        if "/sync/" in path and state["now"] >= 6:
            return {"code": 0, "data": {"code": "123456"}}
        return {"code": 0, "data": {}}

    monkeypatch.setattr(smscloud_sms.time, "time", fake_time)
    monkeypatch.setattr(smscloud_sms.time, "sleep", fake_sleep)
    monkeypatch.setattr(smscloud_sms, "_request_json", fake_request)

    activation = smscloud_sms.SMSCloudActivation(
        order_id="order-1",
        base_url="https://smscloud.example/api/system",
        api_key="key",
        log=lambda *args: logs.append(args),
    )

    assert activation.wait_code(timeout_sec=10, max_resends=2) == "123456"
    assert any("/resend/" in path for path in calls)
    assert any("重发请求失败" in str(item[0]) for item in logs)


def test_codex_oauth_smsbower_preserves_numeric_country_id(monkeypatch):
    monkeypatch.setenv("OAUTH_SMSBOWER_COUNTRY", "1")

    assert codex_auth._oauth_smsbower_config()["country"] == "1"


def test_api_oauth_country_normalizers_preserve_provider_country_ids():
    from autotoken import api

    assert api._normalize_oauth_hero_sms_country("1") == "1"
    assert api._normalize_oauth_smsbower_country("1") == "1"
    assert api._normalize_oauth_hero_sms_country("+1") == "187"
    assert api._normalize_oauth_smsbower_country("+1") == "187"


def test_codex_oauth_hero_sms_us_number_strips_country_code():
    assert codex_auth._format_oauth_phone_for_input(None, None, "12134567890", force_us=True) == "2134567890"


def test_codex_oauth_hero_sms_reuses_number_until_three_successes(monkeypatch, tmp_path):
    from autotoken import gopay_auto_register

    calls = {"get_number": 0, "finish": 0, "cancel": 0}

    def fake_get_number(**kwargs):
        calls["get_number"] += 1
        return f"act-{calls['get_number']}", "12134567890", ""

    class DummyActivation:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.used_codes = set()

        def finish(self):
            calls["finish"] += 1

        def cancel(self):
            calls["cancel"] += 1

    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setenv("OAUTH_HERO_SMS_API_KEY", "hero-key")
    monkeypatch.setenv("OAUTH_HERO_SMS_MAX_BINDS", "3")
    monkeypatch.setenv("OAUTH_HERO_SMS_REUSE_TTL_SECONDS", "1200")
    monkeypatch.setattr(gopay_auto_register, "_hero_get_number", fake_get_number)
    monkeypatch.setattr(gopay_auto_register, "SmsActivation", DummyActivation)
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()
    first, error = codex_auth._acquire_oauth_hero_sms_phone("a@example.com")
    assert error == ""
    codex_auth._mark_oauth_hero_sms_bound(first, email="a@example.com")
    second, error = codex_auth._acquire_oauth_hero_sms_phone("b@example.com")
    assert error == ""
    assert second["activation_id"] == first["activation_id"]
    codex_auth._mark_oauth_hero_sms_bound(second, email="b@example.com")
    third, error = codex_auth._acquire_oauth_hero_sms_phone("c@example.com")
    assert error == ""
    assert third["activation_id"] == first["activation_id"]
    codex_auth._mark_oauth_hero_sms_bound(third, email="c@example.com")

    assert calls["get_number"] == 1
    assert calls["finish"] == 1
    assert calls["cancel"] == 0
    assert codex_auth._OAUTH_HERO_SMS_REUSE.get("current") is None
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()


def test_codex_oauth_hero_sms_blank_email_keeps_number_reserved(monkeypatch, tmp_path):
    from autotoken import gopay_auto_register

    calls = {"get_number": 0}

    def fake_get_number(**kwargs):
        calls["get_number"] += 1
        return f"act-{calls['get_number']}", f"1213456789{calls['get_number']}", ""

    class DummyActivation:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.used_codes = set()

        def finish(self):
            pass

        def cancel(self):
            pass

    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setenv("OAUTH_HERO_SMS_API_KEY", "hero-key")
    monkeypatch.setenv("OAUTH_HERO_SMS_MAX_BINDS", "3")
    monkeypatch.setenv("OAUTH_HERO_SMS_REUSE_TTL_SECONDS", "1200")
    monkeypatch.setattr(gopay_auto_register, "_hero_get_number", fake_get_number)
    monkeypatch.setattr(gopay_auto_register, "SmsActivation", DummyActivation)
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()

    first, error = codex_auth._acquire_oauth_hero_sms_phone("")
    assert error == ""
    second, error = codex_auth._acquire_oauth_hero_sms_phone("")

    assert error == ""
    assert first["activation_id"] == "act-1"
    assert second["activation_id"] == "act-2"
    assert calls["get_number"] == 2
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()


def test_codex_oauth_hero_sms_no_reuse_does_not_cache_registration_phone(monkeypatch, tmp_path):
    from autotoken import gopay_auto_register, sqlite_store

    calls = {"get_number": 0}

    def fake_get_number(**kwargs):
        calls["get_number"] += 1
        return f"act-register-{calls['get_number']}", f"1213555000{calls['get_number']}", ""

    class DummyActivation:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.used_codes = set()

        def finish(self):
            pass

        def cancel(self):
            pass

    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setenv("OAUTH_HERO_SMS_API_KEY", "hero-key")
    monkeypatch.setenv("OAUTH_HERO_SMS_MAX_BINDS", "3")
    monkeypatch.setenv("OAUTH_HERO_SMS_REUSE_TTL_SECONDS", "1200")
    monkeypatch.setattr(gopay_auto_register, "_hero_get_number", fake_get_number)
    monkeypatch.setattr(gopay_auto_register, "SmsActivation", DummyActivation)
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()

    first, error = codex_auth._acquire_oauth_hero_sms_phone("", allow_reuse=False)
    assert error == ""
    second, error = codex_auth._acquire_oauth_hero_sms_phone("", allow_reuse=False)

    assert error == ""
    assert first["activation_id"] == "act-register-1"
    assert second["activation_id"] == "act-register-2"
    assert calls["get_number"] == 2
    assert codex_auth._OAUTH_HERO_SMS_REUSE.get("current") is None
    assert sqlite_store.get_json(
        codex_auth._OAUTH_HERO_SMS_REUSE_NAMESPACE,
        codex_auth._OAUTH_HERO_SMS_REUSE_KEY,
        default={},
    ) == {}
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()


def test_protocol_hero_sms_does_not_reuse_oauth_numbers(monkeypatch, tmp_path):
    from autotoken import gopay_auto_register
    from autotoken.protocol_register import _attach_oauth_phone_supplier

    calls = {"get_number": 0, "cancel": 0}

    def fake_get_number(**kwargs):
        calls["get_number"] += 1
        return f"act-submit-{calls['get_number']}", f"1213666000{calls['get_number']}", ""

    class DummyActivation:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.used_codes = set()

        def finish(self):
            pass

        def cancel(self):
            calls["cancel"] += 1

    class DummyFlow:
        pass

    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setenv("OAUTH_HERO_SMS_API_KEY", "hero-key")
    monkeypatch.setenv("OAUTH_HERO_SMS_MAX_BINDS", "3")
    monkeypatch.setenv("OAUTH_HERO_SMS_REUSE_TTL_SECONDS", "1200")
    monkeypatch.setattr(gopay_auto_register, "_hero_get_number", fake_get_number)
    monkeypatch.setattr(gopay_auto_register, "SmsActivation", DummyActivation)
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()

    flow = DummyFlow()
    _attach_oauth_phone_supplier(flow, provider="hero_sms", email="")
    first = flow._openai_phone_supplier()
    flow._openai_phone_failure(first, "failed_before_openai_submission")
    second = flow._openai_phone_supplier()

    assert first["activation_id"] == "act-submit-1"
    assert second["activation_id"] == "act-submit-2"
    assert calls["get_number"] == 2
    assert calls["cancel"] == 0

    second["phone_first_openai_used"] = True
    flow._openai_phone_failure(second, "failed_after_openai_submission")
    third = flow._openai_phone_supplier()

    assert third["activation_id"] == "act-submit-3"
    assert calls["get_number"] == 3
    assert calls["cancel"] == 1
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()


def test_protocol_hero_sms_otp_timeout_cancels_and_acquires_new_phone(monkeypatch, tmp_path):
    from autotoken import gopay_auto_register
    from autotoken.protocol_register import _attach_oauth_phone_supplier

    calls = {"get_number": 0, "cancel": 0}

    def fake_get_number(**kwargs):
        calls["get_number"] += 1
        return f"act-timeout-{calls['get_number']}", f"1213777000{calls['get_number']}", ""

    class DummyActivation:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.used_codes = set()

        def finish(self):
            pass

        def cancel(self):
            calls["cancel"] += 1

    class DummyFlow:
        pass

    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setenv("OAUTH_HERO_SMS_API_KEY", "hero-key")
    monkeypatch.setenv("OAUTH_HERO_SMS_MAX_BINDS", "3")
    monkeypatch.setenv("OAUTH_HERO_SMS_REUSE_TTL_SECONDS", "1200")
    monkeypatch.setattr(gopay_auto_register, "_hero_get_number", fake_get_number)
    monkeypatch.setattr(gopay_auto_register, "SmsActivation", DummyActivation)
    monkeypatch.setattr(codex_auth, "_oauth_hero_sms_finish_or_cancel", lambda entry, **_kwargs: entry["activation"].cancel() or "updated")
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()

    flow = DummyFlow()
    _attach_oauth_phone_supplier(flow, provider="hero_sms", email="timeout@example.com")
    first = flow._openai_phone_supplier()
    flow._openai_phone_failure(first, "等待手机 OTP 超时 (60s)")
    second = flow._openai_phone_supplier()

    assert first["activation_id"] == "act-timeout-1"
    assert second["activation_id"] == "act-timeout-2"
    assert calls["get_number"] == 2
    assert calls["cancel"] == 1
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()


def test_protocol_smsbower_otp_timeout_cancels_and_acquires_new_phone(monkeypatch, tmp_path):
    from autotoken import gopay_auto_register
    from autotoken.protocol_register import _attach_oauth_phone_supplier

    calls = {"get_number": 0, "cancel": 0}

    def fake_get_number(**kwargs):
        calls["get_number"] += 1
        return f"sb-timeout-{calls['get_number']}", f"1213888000{calls['get_number']}", ""

    class DummyActivation:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.used_codes = set()

        def finish(self):
            pass

        def cancel(self):
            calls["cancel"] += 1

    class DummyFlow:
        pass

    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setenv("OAUTH_SMSBOWER_API_KEY", "smsbower-key")
    monkeypatch.setenv("OAUTH_SMSBOWER_MAX_BINDS", "3")
    monkeypatch.setenv("OAUTH_SMSBOWER_REUSE_TTL_SECONDS", "1200")
    monkeypatch.setattr(gopay_auto_register, "_smsbower_get_number", fake_get_number)
    monkeypatch.setattr(gopay_auto_register, "SmsActivation", DummyActivation)
    codex_auth._OAUTH_SMSBOWER_REUSE.clear()

    flow = DummyFlow()
    _attach_oauth_phone_supplier(flow, provider="smsbower", email="timeout@example.com")
    first = flow._openai_phone_supplier()
    flow._openai_phone_failure(first, "等待手机 OTP 超时 (60s)")
    second = flow._openai_phone_supplier()

    assert first["activation_id"] == "sb-timeout-1"
    assert second["activation_id"] == "sb-timeout-2"
    assert calls["get_number"] == 2
    assert calls["cancel"] == 1
    codex_auth._OAUTH_SMSBOWER_REUSE.clear()


def test_protocol_hero_sms_phone_in_use_cancels_and_acquires_new_phone(monkeypatch, tmp_path):
    from autotoken import gopay_auto_register
    from autotoken.protocol_register import _attach_oauth_phone_supplier

    calls = {"get_number": 0, "cancel": 0}

    def fake_get_number(**kwargs):
        calls["get_number"] += 1
        return f"act-in-use-{calls['get_number']}", f"1213999000{calls['get_number']}", ""

    class DummyActivation:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.used_codes = set()

        def finish(self):
            pass

        def cancel(self):
            calls["cancel"] += 1

    class DummyFlow:
        pass

    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setenv("OAUTH_HERO_SMS_API_KEY", "hero-key")
    monkeypatch.setenv("OAUTH_HERO_SMS_MAX_BINDS", "3")
    monkeypatch.setenv("OAUTH_HERO_SMS_REUSE_TTL_SECONDS", "1200")
    monkeypatch.setattr(gopay_auto_register, "_hero_get_number", fake_get_number)
    monkeypatch.setattr(gopay_auto_register, "SmsActivation", DummyActivation)
    monkeypatch.setattr(codex_auth, "_oauth_hero_sms_finish_or_cancel", lambda entry, **_kwargs: entry["activation"].cancel() or "updated")
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()

    flow = DummyFlow()
    _attach_oauth_phone_supplier(flow, provider="hero_sms", email="in-use@example.com")
    first = flow._openai_phone_supplier()
    flow._openai_phone_failure(first, 'add-phone/send 失败: 400 - {"error":{"code":"phone_number_in_use"}}')
    second = flow._openai_phone_supplier()

    assert first["activation_id"] == "act-in-use-1"
    assert second["activation_id"] == "act-in-use-2"
    assert calls["get_number"] == 2
    assert calls["cancel"] == 1
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()


def test_protocol_hero_sms_acquire_retries_default_to_three_attempts(monkeypatch, tmp_path):
    from autotoken import gopay_auto_register
    from autotoken.protocol_register import _attach_oauth_phone_supplier

    calls = {"get_number": 0}

    def fake_get_number(**kwargs):
        calls["get_number"] += 1
        return "", "", "no_numbers"

    class DummyActivation:
        pass

    class DummyFlow:
        pass

    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setenv("OAUTH_HERO_SMS_API_KEY", "hero-key")
    monkeypatch.setattr(gopay_auto_register, "_hero_get_number", fake_get_number)
    monkeypatch.setattr(gopay_auto_register, "SmsActivation", DummyActivation)
    monkeypatch.setattr(protocol_register.time, "sleep", lambda *_args, **_kwargs: None)
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()

    flow = DummyFlow()
    _attach_oauth_phone_supplier(flow, provider="hero_sms", email="no-number@example.com")

    try:
        flow._openai_phone_supplier()
    except RuntimeError as exc:
        assert "no_numbers" in str(exc)
    else:
        raise AssertionError("expected no_numbers failure")

    assert calls["get_number"] == 3
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()


def test_protocol_smsbower_phone_in_use_cancels_and_acquires_new_phone(monkeypatch, tmp_path):
    from autotoken import gopay_auto_register
    from autotoken.protocol_register import _attach_oauth_phone_supplier

    calls = {"get_number": 0, "cancel": 0}

    def fake_get_number(**kwargs):
        calls["get_number"] += 1
        return f"sb-in-use-{calls['get_number']}", f"1213111000{calls['get_number']}", ""

    class DummyActivation:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.used_codes = set()

        def finish(self):
            pass

        def cancel(self):
            calls["cancel"] += 1

    class DummyFlow:
        pass

    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setenv("OAUTH_SMSBOWER_API_KEY", "smsbower-key")
    monkeypatch.setenv("OAUTH_SMSBOWER_MAX_BINDS", "3")
    monkeypatch.setenv("OAUTH_SMSBOWER_REUSE_TTL_SECONDS", "1200")
    monkeypatch.setattr(gopay_auto_register, "_smsbower_get_number", fake_get_number)
    monkeypatch.setattr(gopay_auto_register, "SmsActivation", DummyActivation)
    codex_auth._OAUTH_SMSBOWER_REUSE.clear()

    flow = DummyFlow()
    _attach_oauth_phone_supplier(flow, provider="smsbower", email="in-use@example.com")
    first = flow._openai_phone_supplier()
    flow._openai_phone_failure(first, 'add-phone/send 失败: 400 - {"error":{"code":"phone_number_in_use"}}')
    second = flow._openai_phone_supplier()

    assert first["activation_id"] == "sb-in-use-1"
    assert second["activation_id"] == "sb-in-use-2"
    assert calls["get_number"] == 2
    assert calls["cancel"] == 1
    codex_auth._OAUTH_SMSBOWER_REUSE.clear()


def test_phone_pool_otp_timeout_cools_number_before_next_acquire(monkeypatch, tmp_path):
    from autotoken.protocol_register import _attach_oauth_phone_supplier

    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    oauth_phone_pool.upsert_phone({"phone_number": "+10000000001", "sms_url": "https://sms.example/1"})
    oauth_phone_pool.upsert_phone({"phone_number": "+10000000002", "sms_url": "https://sms.example/2"})

    class DummyFlow:
        pass

    flow = DummyFlow()
    _attach_oauth_phone_supplier(flow, provider="phone_pool", email="timeout@example.com")
    first = flow._openai_phone_supplier()
    first_id = first["id"]
    flow._openai_phone_failure(first, "等待手机 OTP 超时 (60s)")
    second = flow._openai_phone_supplier()

    assert second["id"] != first_id
    assert oauth_phone_pool.get_phone(first_id)["status"] == "cooldown"


def test_protocol_hero_sms_early_cancel_is_delayed_until_minimum_age(monkeypatch, tmp_path):
    from autotoken import gopay_auto_register

    delayed = {}

    class DummyActivation:
        def cancel(self):
            raise RuntimeError(
                '{"title":"EARLY_CANCEL_DENIED","details":"Activation cannot be cancelled at this time.",'
                '"info":{"minActivationTime":120}}'
            )

    def fake_delayed_cancel(activation, **kwargs):
        delayed["activation"] = activation
        delayed.update(kwargs)

    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setattr(codex_auth.time, "time", lambda: 1_050.0)
    monkeypatch.setattr(gopay_auto_register, "_delayed_cancel_activation", fake_delayed_cancel)
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()
    item = {
        "id": "hero_sms:act-early",
        "record_id": "hero_sms:act-early",
        "source": "hero_sms",
        "activation_id": "act-early",
        "activation": DummyActivation(),
        "created_at": 1_000.0,
        "hero_reserved_by": "owner",
    }
    from autotoken.auth.oauth_phone_records import list_records, record_acquired

    record_acquired(item)
    codex_auth._OAUTH_HERO_SMS_REUSE["current"] = dict(item)

    codex_auth._release_oauth_hero_sms_phone(
        item,
        cancel=True,
        reason="account_creation_failed",
        reservation_owner="owner",
    )

    assert delayed["delay_seconds"] == 71
    assert list_records(1)[0]["status"] == "cancel_pending"
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()


def test_reconcile_pending_hero_sms_cancel_retries_due_record(monkeypatch, tmp_path):
    from autotoken import gopay_auto_register
    from autotoken.auth.oauth_phone_records import list_records, record_acquired

    calls = []

    class DummyActivation:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def cancel(self):
            calls.append(self.kwargs["activation_id"])

    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setenv("OAUTH_HERO_SMS_API_KEY", "hero-key")
    monkeypatch.setattr(gopay_auto_register, "SmsActivation", DummyActivation)
    monkeypatch.setattr(
        gopay_auto_register,
        "_hero_request",
        lambda *_args, **_kwargs: (True, "STATUS_WAIT_CODE", None),
    )
    record_acquired(
        {
            "id": "hero_sms:act-reconcile",
            "provider": "hero_sms",
            "activation_id": "act-reconcile",
            "phone_number": "573229728478",
            "country": "33",
            "status": "cancel_pending",
            "created_at": 1_000.0,
        }
    )

    result = codex_auth._reconcile_pending_oauth_hero_sms_cancels_once(now=1_121.0)

    assert result["cancelled"] == 1
    assert calls == ["act-reconcile"]
    assert list_records(1)[0]["status"] == "cancelled"


def test_reconcile_pending_hero_sms_cancel_archives_provider_terminal_errors(monkeypatch, tmp_path):
    from autotoken import gopay_auto_register
    from autotoken.auth.oauth_phone_records import list_records, record_acquired

    class DummyActivation:
        def __init__(self, **kwargs):
            self.activation_id = kwargs["activation_id"]

        def cancel(self):
            if self.activation_id == "act-not-active":
                raise RuntimeError('{"title":"ACTIVATION_NOT_ACTIVE","details":"Activation is terminated."}')
            raise RuntimeError('{"title":"OTP_RECEIVED","details":"Cannot terminate activation - OTP has been received"}')

    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setenv("OAUTH_HERO_SMS_API_KEY", "hero-key")
    monkeypatch.setattr(gopay_auto_register, "SmsActivation", DummyActivation)
    monkeypatch.setattr(
        gopay_auto_register,
        "_hero_request",
        lambda *_args, **_kwargs: (True, "STATUS_WAIT_CODE", None),
    )
    for activation_id in ("act-not-active", "act-otp"):
        record_acquired(
            {
                "id": f"hero_sms:{activation_id}",
                "provider": "hero_sms",
                "activation_id": activation_id,
                "phone_number": "573229728478",
                "country": "33",
                "status": "cancel_failed",
                "created_at": 1_000.0,
            }
        )

    result = codex_auth._reconcile_pending_oauth_hero_sms_cancels_once(now=1_121.0)

    records = {item["activation_id"]: item["status"] for item in list_records(10)}
    assert result["cancelled"] == 1
    assert result["finished"] == 1
    assert records["act-not-active"] == "cancelled"
    assert records["act-otp"] == "finished"


def test_protocol_hero_sms_otp_wait_uses_remaining_order_budget(monkeypatch):
    class DummyActivation:
        def __init__(self):
            self.wait_kwargs = None

        def wait_code(self, **kwargs):
            self.wait_kwargs = kwargs
            return ""

    class DummyFlow:
        pass

    activation = DummyActivation()
    monkeypatch.setattr(protocol_register.time, "time", lambda: 1_000.0)
    monkeypatch.setattr(
        codex_auth,
        "_acquire_oauth_hero_sms_phone",
        lambda *args, **kwargs: (
            {
                "id": "hero_sms:act-budget",
                "source": "hero_sms",
                "phone_number": "27655370996",
                "activation_id": "act-budget",
                "activation": activation,
                "created_at": 970.0,
            },
            "",
        ),
    )

    flow = DummyFlow()
    protocol_register._attach_oauth_phone_supplier(flow, provider="hero_sms", email="")
    item = flow._openai_phone_supplier()

    assert flow._openai_phone_otp_reader(item, 60) == ""
    assert activation.wait_kwargs["timeout_sec"] == 30


def test_oauth_add_phone_whatsapp_fallback_classifies_number_invalid():
    error = "WHATSAPP_FALLBACK: 我们无法向该电话号码发送短信，因此已切换为 WhatsApp。请继续通过 WhatsApp 发送验证码。"

    assert codex_auth._classify_oauth_phone_failure(error) == "invalid"
    assert protocol_register._phone_pool_failure_action(error) == "invalid"


def test_protocol_phone_supplier_not_attached_without_provider():
    from autotoken.protocol_register import _attach_oauth_phone_supplier

    class DummyFlow:
        pass

    flow = DummyFlow()
    _attach_oauth_phone_supplier(flow, provider="", email="email@example.com")

    assert not hasattr(flow, "_openai_phone_supplier")
    assert not hasattr(flow, "_openai_phone_otp_reader")


def test_protocol_hero_sms_supplier_retries_no_numbers_three_times(monkeypatch):
    from autotoken import codex_auth, protocol_register
    from autotoken.protocol_register import _attach_oauth_phone_supplier

    calls = {"count": 0}

    def fake_get_number(**kwargs):
        calls["count"] += 1
        if calls["count"] < 3:
            return None, "NO_NUMBERS"
        return "act-hero", "+15551234567", ""

    class DummyFlow:
        pass

    monkeypatch.setenv("OAUTH_HERO_SMS_API_KEY", "hero-key")
    monkeypatch.setattr(codex_auth, "_acquire_oauth_hero_sms_phone", fake_get_number)
    monkeypatch.setattr(protocol_register.time, "sleep", lambda *_args, **_kwargs: None)

    flow = DummyFlow()
    _attach_oauth_phone_supplier(flow, provider="hero_sms", email="hero@example.com")
    item = flow._openai_phone_supplier()

    assert item["phone_number"] == "+15551234567"
    assert calls["count"] == 3


def test_phone_first_register_defaults_to_phone_pool_supplier(monkeypatch):
    from autotoken import protocol_register

    captured = {}

    class DummyConfig:
        proxy = None

    class DummyFlow:
        def __init__(self, _cfg):
            pass

        def run_phone_first_register(self, _adapter):
            class Result:
                email = "phone@example.com"

                def is_valid(self):
                    return False

                def to_dict(self):
                    return {}

            return Result()

    def fake_attach(flow, **kwargs):
        captured["provider"] = kwargs.get("provider")

    monkeypatch.setattr(protocol_register, "_load_protocol_classes", lambda: (DummyFlow, DummyConfig))
    monkeypatch.setattr(protocol_register, "_attach_flow_stage_logs", lambda _flow: None)
    monkeypatch.setattr(protocol_register, "_attach_oauth_phone_supplier", fake_attach)

    success, _payload = protocol_register.phone_first_register_once(object(), password="pw")

    assert success is False
    assert captured["provider"] == "phone_pool"


def test_codex_oauth_smsbower_reuse_survives_memory_clear(monkeypatch, tmp_path):
    from autotoken import gopay_auto_register

    calls = {"get_number": 0}

    def fake_get_number(**kwargs):
        calls["get_number"] += 1
        return "act-smsbower", "12134567890", ""

    class DummyActivation:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.activation_id = kwargs["activation_id"]
            self.used_codes = set()

        def finish(self):
            pass

        def cancel(self):
            pass

    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setenv("OAUTH_SMSBOWER_API_KEY", "smsbower-key")
    monkeypatch.setenv("OAUTH_SMSBOWER_MAX_BINDS", "3")
    monkeypatch.setenv("OAUTH_SMSBOWER_REUSE_TTL_SECONDS", "1200")
    monkeypatch.setattr(gopay_auto_register, "_smsbower_get_number", fake_get_number)
    monkeypatch.setattr(gopay_auto_register, "SmsActivation", DummyActivation)
    codex_auth._OAUTH_SMSBOWER_REUSE.clear()

    first, error = codex_auth._acquire_oauth_smsbower_phone("a@example.com")
    assert error == ""
    codex_auth._mark_oauth_smsbower_bound(first, email="a@example.com")
    codex_auth._OAUTH_SMSBOWER_REUSE.clear()

    second, error = codex_auth._acquire_oauth_smsbower_phone("b@example.com")

    assert error == ""
    assert second["activation_id"] == "act-smsbower"
    assert second["smsbower_bound_count"] == 1
    assert calls["get_number"] == 1
    codex_auth._OAUTH_SMSBOWER_REUSE.clear()


def test_codex_oauth_hero_sms_lowest_mode_forces_price_lookup(monkeypatch, tmp_path):
    from autotoken import gopay_auto_register

    calls = []

    def fake_get_number(**kwargs):
        calls.append(kwargs)
        return "act-hero-lowest", "12134567890", ""

    class DummyActivation:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.used_codes = set()

    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setenv("OAUTH_HERO_SMS_API_KEY", "hero-key")
    monkeypatch.setenv("OAUTH_HERO_SMS_MIN_PRICE", "0.1")
    monkeypatch.setenv("OAUTH_HERO_SMS_PRICE_MODE", "lowest")
    monkeypatch.delenv("OAUTH_HERO_SMS_MAX_PRICE", raising=False)
    monkeypatch.setattr(gopay_auto_register, "_hero_get_number", fake_get_number)
    monkeypatch.setattr(gopay_auto_register, "SmsActivation", DummyActivation)

    item, error = codex_auth._acquire_oauth_hero_sms_phone("hero-lowest@example.com", allow_reuse=False)

    assert error == ""
    assert item["activation_id"] == "act-hero-lowest"
    assert calls[0]["min_price"] == "0.1"
    assert calls[0]["preferred_price"] == ""


def test_codex_oauth_smsbower_lowest_mode_uses_lowest_provider(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from autotoken import gopay_auto_register
    from autotoken._paypal_protocol_engine.paypal import smsbower as smsbower_mod

    captured = {}

    class FakeSMSBowerClient:
        def __init__(self, **kwargs):
            captured["client_init"] = kwargs

        def get_provider_prices(self, service, country):
            captured["price_query"] = {"service": service, "country": country}
            return [
                SimpleNamespace(provider_id="too-cheap", price=0.028, count=4),
                SimpleNamespace(provider_id="lowest-in-range", price=0.126, count=10),
                SimpleNamespace(provider_id="expensive", price=0.2, count=10),
            ]

        def get_number_v2(self, **kwargs):
            captured["get_number_v2"] = kwargs
            return {
                "activationId": "act-smsbower-lowest",
                "phoneNumber": "12135550000",
                "activationCost": kwargs["max_price"],
                "activationOperator": kwargs["provider_id"],
            }

    class DummyActivation:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.used_codes = set()

    def legacy_get_number_should_not_be_used(**_kwargs):
        raise AssertionError("lowest mode should use getPricesV3 + getNumberV2")

    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setenv("OAUTH_SMSBOWER_API_KEY", "smsbower-key")
    monkeypatch.setenv("OAUTH_SMSBOWER_COUNTRY", "73")
    monkeypatch.setenv("OAUTH_SMSBOWER_SERVICE", "dr")
    monkeypatch.setenv("OAUTH_SMSBOWER_MIN_PRICE", "0.1")
    monkeypatch.setenv("OAUTH_SMSBOWER_MAX_PRICE", "0.13")
    monkeypatch.setenv("OAUTH_SMSBOWER_PRICE_MODE", "lowest")
    monkeypatch.setattr(smsbower_mod, "SMSBowerClient", FakeSMSBowerClient)
    monkeypatch.setattr(gopay_auto_register, "_smsbower_get_number", legacy_get_number_should_not_be_used)
    monkeypatch.setattr(gopay_auto_register, "SmsActivation", DummyActivation)
    codex_auth._OAUTH_SMSBOWER_REUSE.clear()

    item, error = codex_auth._acquire_oauth_smsbower_phone("smsbower-lowest@example.com", allow_reuse=False)

    assert error == ""
    assert item["activation_id"] == "act-smsbower-lowest"
    assert captured["price_query"] == {"service": "dr", "country": "73"}
    assert captured["get_number_v2"]["provider_id"] == "lowest-in-range"
    assert captured["get_number_v2"]["max_price"] == 0.126
    codex_auth._OAUTH_SMSBOWER_REUSE.clear()


def test_protocol_smsbower_does_not_reuse_oauth_numbers(monkeypatch, tmp_path):
    from autotoken import gopay_auto_register
    from autotoken.protocol_register import _attach_oauth_phone_supplier

    calls = {"get_number": 0, "cancel": 0}

    def fake_get_number(**kwargs):
        calls["get_number"] += 1
        return f"act-smsbower-submit-{calls['get_number']}", f"1213777000{calls['get_number']}", ""

    class DummyActivation:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.used_codes = set()

        def finish(self):
            pass

        def cancel(self):
            calls["cancel"] += 1

    class DummyFlow:
        pass

    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setenv("OAUTH_SMSBOWER_API_KEY", "smsbower-key")
    monkeypatch.setenv("OAUTH_SMSBOWER_MAX_BINDS", "3")
    monkeypatch.setenv("OAUTH_SMSBOWER_REUSE_TTL_SECONDS", "1200")
    monkeypatch.setattr(gopay_auto_register, "_smsbower_get_number", fake_get_number)
    monkeypatch.setattr(gopay_auto_register, "SmsActivation", DummyActivation)
    codex_auth._OAUTH_SMSBOWER_REUSE.clear()

    flow = DummyFlow()
    _attach_oauth_phone_supplier(flow, provider="smsbower", email="")
    first = flow._openai_phone_supplier()
    flow._openai_phone_failure(first, "failed_before_openai_submission")
    second = flow._openai_phone_supplier()

    assert first["activation_id"] == "act-smsbower-submit-1"
    assert second["activation_id"] == "act-smsbower-submit-2"
    assert calls["get_number"] == 2
    assert calls["cancel"] == 0

    second["phone_first_openai_used"] = True
    flow._openai_phone_failure(second, "failed_after_openai_submission")
    third = flow._openai_phone_supplier()

    assert third["activation_id"] == "act-smsbower-submit-3"
    assert calls["get_number"] == 3
    assert calls["cancel"] == 1
    codex_auth._OAUTH_SMSBOWER_REUSE.clear()


def test_protocol_phone_pool_submitted_registration_phone_is_invalidated(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))

    class DummyFlow:
        pass

    item = oauth_phone_pool.upsert_phone(
        {
            "phone_number": "+17328582987",
            "sms_url": "https://sms.example/a",
        }
    )
    flow = DummyFlow()
    protocol_register._attach_oauth_phone_supplier(flow, provider="phone_pool", email="")
    acquired = flow._openai_phone_supplier()
    acquired["phone_first_openai_used"] = True
    flow._openai_phone_failure(acquired, "PHONE_NUMBER_IN_USE")

    listed = oauth_phone_pool.get_phone(item["id"])
    assert listed["status"] == "invalid"


def test_codex_oauth_hero_sms_reuse_survives_memory_clear(monkeypatch, tmp_path):
    from autotoken import gopay_auto_register

    calls = {"get_number": 0}

    def fake_get_number(**kwargs):
        calls["get_number"] += 1
        return "act-persisted", "12134567890", ""

    class DummyActivation:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.activation_id = kwargs["activation_id"]
            self.used_codes = set()

        def finish(self):
            pass

        def cancel(self):
            pass

    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setenv("OAUTH_HERO_SMS_API_KEY", "hero-key")
    monkeypatch.setenv("OAUTH_HERO_SMS_MAX_BINDS", "3")
    monkeypatch.setenv("OAUTH_HERO_SMS_REUSE_TTL_SECONDS", "1200")
    monkeypatch.setattr(gopay_auto_register, "_hero_get_number", fake_get_number)
    monkeypatch.setattr(gopay_auto_register, "SmsActivation", DummyActivation)
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()

    first, error = codex_auth._acquire_oauth_hero_sms_phone("a@example.com")
    assert error == ""
    codex_auth._mark_oauth_hero_sms_bound(first, email="a@example.com")
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()

    second, error = codex_auth._acquire_oauth_hero_sms_phone("b@example.com")

    assert error == ""
    assert second["activation_id"] == "act-persisted"
    assert second["hero_bound_count"] == 1
    assert calls["get_number"] == 1
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()


def test_codex_oauth_hero_sms_restore_ignores_stale_config(monkeypatch, tmp_path):
    from autotoken import gopay_auto_register

    calls = {"get_number": 0}

    def fake_get_number(**kwargs):
        calls["get_number"] += 1
        return f"act-{calls['get_number']}", "12134567890", ""

    class DummyActivation:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.activation_id = kwargs["activation_id"]
            self.used_codes = set()

        def finish(self):
            pass

        def cancel(self):
            pass

    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setenv("OAUTH_HERO_SMS_API_KEY", "hero-key-a")
    monkeypatch.setenv("OAUTH_HERO_SMS_MAX_BINDS", "3")
    monkeypatch.setenv("OAUTH_HERO_SMS_REUSE_TTL_SECONDS", "1200")
    monkeypatch.setattr(gopay_auto_register, "_hero_get_number", fake_get_number)
    monkeypatch.setattr(gopay_auto_register, "SmsActivation", DummyActivation)
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()

    first, error = codex_auth._acquire_oauth_hero_sms_phone("a@example.com")
    assert error == ""
    codex_auth._mark_oauth_hero_sms_bound(first, email="a@example.com")
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()

    monkeypatch.setenv("OAUTH_HERO_SMS_API_KEY", "hero-key-b")
    second, error = codex_auth._acquire_oauth_hero_sms_phone("b@example.com")

    assert error == ""
    assert second["activation_id"] == "act-2"
    assert calls["get_number"] == 2
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()


def test_codex_oauth_hero_sms_restore_closes_expired_cached_activation(monkeypatch, tmp_path):
    from autotoken import gopay_auto_register, sqlite_store

    calls = {"finish": 0, "cancel": 0}

    class DummyActivation:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.activation_id = kwargs["activation_id"]
            self.used_codes = set()

        def finish(self):
            calls["finish"] += 1

        def cancel(self):
            calls["cancel"] += 1

    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setenv("OAUTH_HERO_SMS_API_KEY", "hero-key")
    monkeypatch.setenv("OAUTH_HERO_SMS_MAX_BINDS", "3")
    monkeypatch.setattr(gopay_auto_register, "SmsActivation", DummyActivation)
    cfg = codex_auth._oauth_hero_sms_config()
    sqlite_store.set_json(
        codex_auth._OAUTH_HERO_SMS_REUSE_NAMESPACE,
        codex_auth._OAUTH_HERO_SMS_REUSE_KEY,
        {
            "activation_id": "act-expired",
            "phone_number": "12134567890",
            "country_id": "187",
            "created_at": 1,
            "expires_at": 2,
            "bound_count": 1,
            "used_codes": [],
            "config_fingerprint": codex_auth._oauth_hero_sms_config_fingerprint(cfg),
        },
    )
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()

    restored = codex_auth._oauth_hero_sms_restore_entry(cfg, DummyActivation)

    assert restored is None
    assert calls["finish"] == 1
    assert calls["cancel"] == 0
    assert sqlite_store.get_json(codex_auth._OAUTH_HERO_SMS_REUSE_NAMESPACE, codex_auth._OAUTH_HERO_SMS_REUSE_KEY, default={}) == {}


def test_codex_oauth_hero_sms_persists_used_codes_across_restore(monkeypatch, tmp_path):
    from autotoken import gopay_auto_register

    calls = {"get_number": 0}

    def fake_get_number(**kwargs):
        calls["get_number"] += 1
        return "act-used-code", "12134567890", ""

    class DummyActivation:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.activation_id = kwargs["activation_id"]
            self.used_codes = set()

        def wait_code(self, **kwargs):
            if "111111" not in self.used_codes:
                self.used_codes.add("111111")
                return "111111"
            self.used_codes.add("222222")
            return "222222"

        def finish(self):
            pass

        def cancel(self):
            pass

    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setenv("OAUTH_HERO_SMS_API_KEY", "hero-key")
    monkeypatch.setenv("OAUTH_HERO_SMS_MAX_BINDS", "3")
    monkeypatch.setenv("OAUTH_HERO_SMS_REUSE_TTL_SECONDS", "1200")
    monkeypatch.setattr(gopay_auto_register, "_hero_get_number", fake_get_number)
    monkeypatch.setattr(gopay_auto_register, "SmsActivation", DummyActivation)
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()

    first, error = codex_auth._acquire_oauth_hero_sms_phone("a@example.com")
    assert error == ""
    provider = codex_auth._make_phone_item_otp_provider(first)
    assert provider() == "111111"
    codex_auth._release_oauth_hero_sms_phone(first, email="a@example.com", reason="retry later")
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()

    second, error = codex_auth._acquire_oauth_hero_sms_phone("b@example.com")
    assert error == ""
    provider = codex_auth._make_phone_item_otp_provider(second)

    assert provider() == "222222"
    assert calls["get_number"] == 1
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()


def test_codex_oauth_hero_sms_first_code_timeout_releases_number(monkeypatch):
    assert (
        codex_auth._classify_oauth_phone_failure("HERO_SMS_FIRST_CODE_TIMEOUT:hero-sms 120s 内未收到第一个验证码")
        == "hero_release"
    )


def test_acquired_phone_is_reserved_until_released(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    item = oauth_phone_pool.upsert_phone(
        {
            "phone_number": "+17328582987",
            "sms_url": "https://sms.example/a",
        }
    )

    first = oauth_phone_pool.acquire_available_phone("first@example.com")

    assert first["id"] == item["id"]
    assert first["reserved"] is True
    assert oauth_phone_pool.acquire_available_phone("second@example.com") is None

    released = oauth_phone_pool.release_phone_reservation(item["id"], "first@example.com")
    assert released["reserved"] is False

    second = oauth_phone_pool.acquire_available_phone("second@example.com")
    assert second["id"] == item["id"]


def test_protocol_hero_sms_openai_phone_rate_limit_cancels_and_acquires_new_phone(monkeypatch, tmp_path):
    from autotoken import gopay_auto_register
    from autotoken.protocol_register import _attach_oauth_phone_supplier

    calls = {"get_number": 0, "cancel": 0}

    def fake_get_number(**kwargs):
        calls["get_number"] += 1
        return f"act-rate-{calls['get_number']}", f"1213555000{calls['get_number']}", ""

    class DummyActivation:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.used_codes = set()

        def finish(self):
            pass

        def cancel(self):
            calls["cancel"] += 1

    class DummyFlow:
        pass

    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setenv("OAUTH_HERO_SMS_API_KEY", "hero-key")
    monkeypatch.setenv("OAUTH_HERO_SMS_MAX_BINDS", "3")
    monkeypatch.setenv("OAUTH_HERO_SMS_REUSE_TTL_SECONDS", "1200")
    monkeypatch.setattr(gopay_auto_register, "_hero_get_number", fake_get_number)
    monkeypatch.setattr(gopay_auto_register, "SmsActivation", DummyActivation)
    monkeypatch.setattr(codex_auth, "_oauth_hero_sms_finish_or_cancel", lambda entry, **_kwargs: entry["activation"].cancel() or "updated")
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()

    flow = DummyFlow()
    _attach_oauth_phone_supplier(flow, provider="hero_sms", email="rate-limit@example.com")
    first = flow._openai_phone_supplier()
    flow._openai_phone_failure(
        first,
        "add-phone/send 失败: 400 - "
        "{\"error\":{\"message\":\"You've made too many phone verification requests. Please try again later.\"}}",
    )
    second = flow._openai_phone_supplier()

    assert first["activation_id"] == "act-rate-1"
    assert second["activation_id"] == "act-rate-2"
    assert calls["get_number"] == 2
    assert calls["cancel"] == 1
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()


def test_protocol_hero_sms_success_finishes_number_instead_of_reusing(monkeypatch, tmp_path):
    from autotoken import gopay_auto_register
    from autotoken.protocol_register import _attach_oauth_phone_supplier

    calls = {"get_number": 0, "finish": 0}

    def fake_get_number(**kwargs):
        calls["get_number"] += 1
        return f"act-success-{calls['get_number']}", f"1213444000{calls['get_number']}", ""

    class DummyActivation:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.used_codes = set()

        def finish(self):
            calls["finish"] += 1

        def cancel(self):
            pass

    class DummyFlow:
        pass

    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setenv("OAUTH_HERO_SMS_API_KEY", "hero-key")
    monkeypatch.setattr(gopay_auto_register, "_hero_get_number", fake_get_number)
    monkeypatch.setattr(gopay_auto_register, "SmsActivation", DummyActivation)
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()

    flow = DummyFlow()
    _attach_oauth_phone_supplier(flow, provider="hero_sms", email="success@example.com")
    first = flow._openai_phone_supplier()
    flow._openai_phone_success(first)
    second = flow._openai_phone_supplier()

    assert first["activation_id"] == "act-success-1"
    assert second["activation_id"] == "act-success-2"
    assert calls["get_number"] == 2
    assert calls["finish"] == 1
    assert codex_auth._OAUTH_HERO_SMS_REUSE.get("current") is None
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()


def test_protocol_smsbower_success_finishes_number_instead_of_reusing(monkeypatch, tmp_path):
    from autotoken import gopay_auto_register
    from autotoken.protocol_register import _attach_oauth_phone_supplier

    calls = {"get_number": 0, "finish": 0}

    def fake_get_number(**kwargs):
        calls["get_number"] += 1
        return f"sb-success-{calls['get_number']}", f"1213333000{calls['get_number']}", ""

    class DummyActivation:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.used_codes = set()

        def finish(self):
            calls["finish"] += 1

        def cancel(self):
            pass

    class DummyFlow:
        pass

    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setenv("OAUTH_SMSBOWER_API_KEY", "smsbower-key")
    monkeypatch.setattr(gopay_auto_register, "_smsbower_get_number", fake_get_number)
    monkeypatch.setattr(gopay_auto_register, "SmsActivation", DummyActivation)
    codex_auth._OAUTH_SMSBOWER_REUSE.clear()

    flow = DummyFlow()
    _attach_oauth_phone_supplier(flow, provider="smsbower", email="success@example.com")
    first = flow._openai_phone_supplier()
    flow._openai_phone_success(first)
    second = flow._openai_phone_supplier()

    assert first["activation_id"] == "sb-success-1"
    assert second["activation_id"] == "sb-success-2"
    assert calls["get_number"] == 2
    assert calls["finish"] == 1
    assert codex_auth._OAUTH_SMSBOWER_REUSE.get("current") is None
    codex_auth._OAUTH_SMSBOWER_REUSE.clear()
