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


def test_protocol_hero_sms_reuses_only_before_phone_first_submission(monkeypatch, tmp_path):
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

    assert second["activation_id"] == first["activation_id"]
    assert calls["get_number"] == 1
    assert calls["cancel"] == 0

    second["phone_first_openai_used"] = True
    flow._openai_phone_failure(second, "failed_after_openai_submission")
    third = flow._openai_phone_supplier()

    assert third["activation_id"] == "act-submit-2"
    assert calls["get_number"] == 2
    assert calls["cancel"] == 1
    codex_auth._OAUTH_HERO_SMS_REUSE.clear()


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
    from autotoken.auth.oauth_phone_records import record_acquired, list_records

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


def test_protocol_phone_supplier_not_attached_without_provider():
    from autotoken.protocol_register import _attach_oauth_phone_supplier

    class DummyFlow:
        pass

    flow = DummyFlow()
    _attach_oauth_phone_supplier(flow, provider="", email="email@example.com")

    assert not hasattr(flow, "_openai_phone_supplier")
    assert not hasattr(flow, "_openai_phone_otp_reader")


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


def test_protocol_smsbower_reuses_only_before_phone_first_submission(monkeypatch, tmp_path):
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

    assert second["activation_id"] == first["activation_id"]
    assert calls["get_number"] == 1
    assert calls["cancel"] == 0

    second["phone_first_openai_used"] = True
    flow._openai_phone_failure(second, "failed_after_openai_submission")
    third = flow._openai_phone_supplier()

    assert third["activation_id"] == "act-smsbower-submit-2"
    assert calls["get_number"] == 2
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
