from __future__ import annotations

import importlib
import sys

import pytest

from autotoken.services import paypal_protocol_local as service


def test_build_protocol_command_uses_vendored_engine_and_success_env(tmp_path, monkeypatch):
    engine = tmp_path / "engine"
    (engine / "var").mkdir(parents=True)
    (engine / "main.py").write_text("print('ok')\n", encoding="utf-8")
    fp = engine / "var" / "roxy_ios_fingerprint_current.json"
    fp.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("AUTOTEAM_PAYPAL_ENGINE_ROOT", str(engine))

    cmd, env, cwd = service.build_protocol_command(service.PaypalProtocolRunConfig(
        paypal_link="https://www.paypal.com/agreements/approve?ba_token=BA-1CMD123",
        phone="+18350000000",
        sms_record_url="https://sms.example/api/record?token=secret",
        proxy_url="proxy.example:10000:user:pass",
    ))

    assert cwd == engine.resolve()
    assert str(engine / "main.py") in cmd
    assert "--approval-path" in cmd and "create-member-no-fi" in cmd
    assert "--proxy" in cmd
    assert env["PAYPAL_USE_CURL_CFFI"] == "0"
    assert env["PAYPAL_HEADLESS_USE_PINNED_FINGERPRINT"] == "1"
    assert env["PAYPAL_HEADLESS_PINNED_FINGERPRINT_PATH"] == str(fp)
    assert env["PAYPAL_APPROVAL_PATH"] == "create_member_no_fi"
    assert env["PAYPAL_STRICT_BROWSER_RISK"] == "0"
    assert env["PAYPAL_MTR_HEADLESS_WAIT_SECONDS"] == "45"
    joined = " ".join(cmd)
    assert "153" + ".ink" not in joined
    assert "pay" + "153" not in joined


def test_protocol_service_sanitizes_sensitive_values():
    text = service.sanitize_log_text(
        "BA-1234567890 https://sms.example/api?token=abcdef socks5h://user:pass@proxy.example:10000"
    )

    assert "abcdef" not in text
    assert "user:pass" not in text
    assert "BA-1234567890" not in text


def test_build_protocol_command_rejects_unknown_country(tmp_path, monkeypatch):
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "main.py").write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.setenv("AUTOTEAM_PAYPAL_ENGINE_ROOT", str(engine))

    with pytest.raises(ValueError, match="AU/BR/CA/GB/ID/JP/MX/PH/TH/NL/US"):
        service.build_protocol_command(service.PaypalProtocolRunConfig(
            ba_token="BA-1CMD123",
            phone="+18350000000",
            sms_record_url="https://sms.example/api?token=secret",
            country="ZZ",
        ))


@pytest.mark.parametrize(
    ("country", "sms_country"),
    [
        ("BR", "73"),
        ("AU", "175"),
        ("CA", "36"),
        ("GB", "16"),
        ("ID", "6"),
        ("JP", "182"),
        ("MX", "54"),
        ("PH", "4"),
        ("TH", "52"),
        ("NL", "48"),
    ],
)
def test_build_protocol_command_supports_requested_countries(tmp_path, monkeypatch, country, sms_country):
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "main.py").write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.setenv("AUTOTEAM_PAYPAL_ENGINE_ROOT", str(engine))

    cmd, env, _cwd = service.build_protocol_command(service.PaypalProtocolRunConfig(
        ba_token=f"BA-1{country}CMD123",
        sms_provider="smsbower",
        country=country,
    ))

    assert cmd[cmd.index("--country") + 1] == country
    assert cmd[cmd.index("--sms-country") + 1] == sms_country
    assert env["PAYPAL_COUNTRY"] == country
    assert env["PAYPAL_SMS_COUNTRY"] == sms_country


def test_build_protocol_command_passes_sms_wait_and_poll(tmp_path, monkeypatch):
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "main.py").write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.setenv("AUTOTEAM_PAYPAL_ENGINE_ROOT", str(engine))

    cmd, _env, _cwd = service.build_protocol_command(service.PaypalProtocolRunConfig(
        ba_token="BA-1WAIT123",
        phone="+18350000000",
        sms_record_url="https://sms.example/api?token=secret",
        sms_record_wait_seconds=600,
        sms_record_poll_seconds=2,
    ))

    assert cmd[cmd.index("--sms-record-wait") + 1] == "600"
    assert cmd[cmd.index("--sms-record-poll") + 1] == "2.0"


def test_build_protocol_command_supports_herosms_without_fixed_phone(tmp_path, monkeypatch):
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "main.py").write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.setenv("AUTOTEAM_PAYPAL_ENGINE_ROOT", str(engine))

    cmd, env, _cwd = service.build_protocol_command(service.PaypalProtocolRunConfig(
        ba_token="BA-1HERO123",
        sms_provider="hero-sms",
        sms_api_key="hero-secret",
        sms_service="ts",
        sms_country="48",
        sms_max_price="0.20",
    ))

    assert "--phone" not in cmd
    assert "--sms-record-url" not in cmd
    assert cmd[cmd.index("--sms-provider") + 1] == "hero-sms"
    assert cmd[cmd.index("--sms-service") + 1] == "ts"
    assert cmd[cmd.index("--sms-country") + 1] == "187"
    assert cmd[cmd.index("--sms-number-wait") + 1] == "60"
    assert "--sms-max-price" not in cmd
    assert env["PAYPAL_SMS_PROVIDER"] == "hero_sms"
    assert "PAYPAL_HERO_SMS_API_KEY" not in env or env["PAYPAL_HERO_SMS_API_KEY"] != "hero-secret"
    assert env["PAYPAL_SMS_COUNTRY"] == "187"
    assert env["PAYPAL_SMS_NUMBER_WAIT_SECONDS"] == "60"
    assert "hero-secret" not in service.sanitize_log_text(" ".join(cmd))


def test_build_protocol_command_supports_herosms_rent_phone(tmp_path, monkeypatch):
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "main.py").write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.setenv("AUTOTEAM_PAYPAL_ENGINE_ROOT", str(engine))

    cmd, env, _cwd = service.build_protocol_command(service.PaypalProtocolRunConfig(
        ba_token="BA-1HERORENT123",
        sms_provider="hero-sms-rent",
        phone="+31612345678",
        country="NL",
    ))

    assert cmd[cmd.index("--sms-provider") + 1] == "hero-sms-rent"
    assert cmd[cmd.index("--phone") + 1] == "+31612345678"
    assert cmd[cmd.index("--sms-country") + 1] == "48"
    assert "--sms-record-url" not in cmd
    assert env["PAYPAL_SMS_PROVIDER"] == "hero_sms_rent"
    assert env["PAYPAL_SMS_COUNTRY"] == "48"


def test_build_protocol_command_reuses_gopay_herosms_settings(tmp_path, monkeypatch):
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "main.py").write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.setenv("AUTOTEAM_PAYPAL_ENGINE_ROOT", str(engine))
    monkeypatch.setattr(service, "_load_project_env", lambda: {})
    monkeypatch.delenv("PAYPAL_HERO_SMS_API_KEY", raising=False)
    monkeypatch.delenv("PAYPAL_HEROSMS_API_KEY", raising=False)
    monkeypatch.delenv("HERO_SMS_API_KEY", raising=False)
    monkeypatch.delenv("HEROSMS_API_KEY", raising=False)
    monkeypatch.delenv("OAUTH_HERO_SMS_API_KEY", raising=False)
    monkeypatch.delenv("PAYPAL_HERO_SMS_BASE_URL", raising=False)
    monkeypatch.delenv("PAYPAL_HEROSMS_BASE_URL", raising=False)
    monkeypatch.delenv("OAUTH_HERO_SMS_BASE_URL", raising=False)
    monkeypatch.setenv("GOPAY_AUTO_SIGNUP_HERO_SMS_API_KEY", "gopay-hero-key")
    monkeypatch.setenv("GOPAY_AUTO_SIGNUP_HERO_SMS_BASE_URL", "https://hero.example/stubs/handler_api.php")

    _cmd, env, _cwd = service.build_protocol_command(service.PaypalProtocolRunConfig(
        ba_token="BA-1HEROGOPAY123",
        sms_provider="hero-sms",
        country="GB",
    ))

    assert env["PAYPAL_HERO_SMS_API_KEY"] == "gopay-hero-key"
    assert env["PAYPAL_HERO_SMS_BASE_URL"] == "https://hero.example/stubs/handler_api.php"
    assert env["PAYPAL_SMS_COUNTRY"] == "16"


def test_herosms_rent_provider_resolves_phone_and_reads_rent_status(tmp_path):
    engine_root = service.DEFAULT_ENGINE_ROOT
    sys.path.insert(0, str(engine_root))
    try:
        smsbower = importlib.import_module("paypal.smsbower")
    finally:
        try:
            sys.path.remove(str(engine_root))
        except ValueError:
            pass

    class FakeClient:
        def __init__(self):
            self.actions = []

        def get_status(self, activation_id):
            self.actions.append(("getStatus", {"id": activation_id}))
            return "STATUS_OK:654321"

        def set_status(self, activation_id, status):
            self.actions.append(("setStatus", {"id": activation_id, "status": status}))
            return "ACCESS_READY"

    client = FakeClient()
    provider = smsbower.HeroSmsRentOtpProvider(
        client=client,
        phone_number="+31612345678#rent-123",
        store=smsbower.SMSBowerActivationStore(tmp_path / "rent-cache.json"),
        country="48",
        wait_seconds=1,
        poll_interval_seconds=0.01,
    )

    activation = provider.reserve_number()
    assert activation.activation_id == "rent-123"
    assert activation.phone_number == "+31612345678"
    assert provider.wait_for_code(activation, timeout_seconds=1) == "654321"
    assert ("getStatus", {"id": "rent-123"}) in client.actions


def test_sms_activate_provider_reuses_number_without_finishing(tmp_path):
    engine_root = service.DEFAULT_ENGINE_ROOT
    sys.path.insert(0, str(engine_root))
    try:
        smsbower = importlib.import_module("paypal.smsbower")
    finally:
        try:
            sys.path.remove(str(engine_root))
        except ValueError:
            pass

    class FakeClient:
        def __init__(self):
            self.actions = []
            self.statuses = ["STATUS_OK:111111", "STATUS_OK:111111", "STATUS_OK:222222"]

        def request_json_or_text(self, action, params=None):
            self.actions.append((action, dict(params or {})))
            if action == "getNumberV2":
                return {"activationId": "act-1", "phoneNumber": "447700900123", "activationCost": "0.1"}
            raise AssertionError(action)

        def get_status(self, activation_id):
            self.actions.append(("getStatus", {"id": activation_id}))
            return self.statuses.pop(0)

        def set_status(self, activation_id, status):
            self.actions.append(("setStatus", {"id": activation_id, "status": status}))
            return "ACCESS_READY"

    store = smsbower.SMSBowerActivationStore(tmp_path / "sms-cache.json")
    client = FakeClient()
    provider = smsbower.SmsActivateOtpProvider(
        client=client,
        provider_name="hero_sms",
        store=store,
        service="ts",
        country="16",
        wait_seconds=1,
        poll_interval_seconds=0.01,
        reuse_enabled=True,
        finalize_on_success=False,
    )

    first = provider.reserve_number()
    assert first.phone_number == "+447700900123"
    assert provider.wait_for_code(first, timeout_seconds=1) == "111111"
    provider.register_confirmation_result(first, True)

    reused = provider.reserve_number()
    assert reused.activation_id == "act-1"
    assert reused.reused is True
    assert provider.wait_for_code(reused, timeout_seconds=1) == "222222"
    provider.register_confirmation_result(reused, True)

    statuses = [item[1]["status"] for item in client.actions if item[0] == "setStatus"]
    assert 6 not in statuses
    assert statuses.count(3) >= 2


def test_sms_activate_provider_timeout_switches_number(tmp_path):
    engine_root = service.DEFAULT_ENGINE_ROOT
    sys.path.insert(0, str(engine_root))
    try:
        smsbower = importlib.import_module("paypal.smsbower")
    finally:
        try:
            sys.path.remove(str(engine_root))
        except ValueError:
            pass

    class FakeClient:
        def __init__(self):
            self.actions = []
            self.next_id = 1

        def request_json_or_text(self, action, params=None):
            self.actions.append((action, dict(params or {})))
            if action == "getNumberV2":
                value = self.next_id
                self.next_id += 1
                return {
                    "activationId": f"act-{value}",
                    "phoneNumber": f"44770090012{value}",
                    "activationCost": "0.1",
                }
            raise AssertionError(action)

        def get_status(self, activation_id):
            self.actions.append(("getStatus", {"id": activation_id}))
            return "STATUS_WAIT_CODE"

        def set_status(self, activation_id, status):
            self.actions.append(("setStatus", {"id": activation_id, "status": status}))
            return "ACCESS_CANCEL"

    store = smsbower.SMSBowerActivationStore(tmp_path / "sms-cache.json")
    client = FakeClient()
    provider = smsbower.SmsActivateOtpProvider(
        client=client,
        provider_name="hero_sms",
        store=store,
        service="ts",
        country="16",
        wait_seconds=0.02,
        poll_interval_seconds=0.01,
        reuse_enabled=True,
        cancel_on_abandon=False,
    )

    first = provider.reserve_number()
    assert first.activation_id == "act-1"
    assert provider.wait_for_code(first, timeout_seconds=0.02) is None
    provider.abandon(first, "sms_timeout")

    second = provider.reserve_number()
    assert second.activation_id == "act-2"
    assert second.reused is False
    assert ("setStatus", {"id": "act-1", "status": 8}) in client.actions


def test_gb_generated_addresses_avoid_known_landmarks():
    engine_root = service.DEFAULT_ENGINE_ROOT
    sys.path.insert(0, str(engine_root))
    try:
        models = importlib.import_module("paypal.models")
    finally:
        try:
            sys.path.remove(str(engine_root))
        except ValueError:
            pass

    blocked = {"10 downing", "baker street", "deansgate", "temple street", "victoria square"}
    for _ in range(50):
        address = models.generate_address(country="GB")
        line = f"{address.street} {address.postal_code}".lower()
        assert not any(marker in line for marker in blocked)
        assert address.country == "GB"
        assert address.postal_code


def test_nl_generated_addresses_avoid_landmarks_and_have_real_house_numbers():
    engine_root = service.DEFAULT_ENGINE_ROOT
    sys.path.insert(0, str(engine_root))
    try:
        models = importlib.import_module("paypal.models")
    finally:
        try:
            sys.path.remove(str(engine_root))
        except ValueError:
            pass

    blocked = {"damrak", "coolsingel", "spui", "stadhuisplein", "grote markt"}
    for _ in range(50):
        address = models.generate_address(country="NL")
        line = f"{address.street} {address.postal_code}".lower()
        assert not any(marker in line for marker in blocked)
        assert address.country == "NL"
        assert address.house_number
        assert address.postal_code


@pytest.mark.parametrize(
    ("country", "locale", "language", "dial_code"),
    [
        ("BR", "pt_BR", "pt-BR", "55"),
        ("AU", "en_AU", "en-AU", "61"),
        ("CA", "en_CA", "en-CA", "1"),
        ("GB", "en_GB", "en-GB", "44"),
        ("ID", "id_ID", "id-ID", "62"),
        ("JP", "ja_JP", "ja-JP", "81"),
        ("MX", "es_MX", "es-MX", "52"),
        ("PH", "en_PH", "en-PH", "63"),
        ("TH", "th_TH", "th-TH", "66"),
        ("NL", "nl_NL", "nl-NL", "31"),
    ],
)
def test_requested_country_profiles_and_generated_models(country, locale, language, dial_code):
    engine_root = service.DEFAULT_ENGINE_ROOT
    sys.path.insert(0, str(engine_root))
    try:
        country_profile = importlib.import_module("paypal.country_profile")
        models = importlib.import_module("paypal.models")
    finally:
        try:
            sys.path.remove(str(engine_root))
        except ValueError:
            pass

    profile = country_profile.get_country_profile(country)
    assert profile.country == country
    assert profile.locale == locale
    assert profile.language == language
    assert profile.phone_country_code == dial_code

    user = models.generate_user(f"+{dial_code}9876543210", country=country)
    address = models.generate_address(country=country)
    card = models.generate_card(country=country)

    assert user.phone_country_code == f"+{dial_code}"
    assert user.phone.startswith(f"+{dial_code}")
    assert address.country == country
    assert address.street
    assert address.city
    assert address.postal_code
    assert card.number.isdigit()


@pytest.mark.parametrize(
    ("country", "sms_country", "dial_code"),
    [
        ("CA", "36", "1"),
        ("AU", "175", "61"),
        ("ID", "6", "62"),
        ("JP", "182", "81"),
        ("MX", "54", "52"),
        ("PH", "4", "63"),
        ("TH", "52", "66"),
    ],
)
def test_engine_sms_country_normalization_for_new_paypal_countries(country, sms_country, dial_code):
    engine_root = service.DEFAULT_ENGINE_ROOT
    sys.path.insert(0, str(engine_root))
    try:
        smsbower = importlib.import_module("paypal.smsbower")
    finally:
        try:
            sys.path.remove(str(engine_root))
        except ValueError:
            pass

    assert smsbower.normalize_paypal_sms_country("", paypal_country=country) == sms_country
    assert smsbower.normalize_paypal_sms_country(country, paypal_country="US") == sms_country
    assert smsbower.PAYPAL_SMS_COUNTRY_DIAL_CODES[sms_country] == dial_code


def test_signup_address_error_is_retryable():
    engine_root = service.DEFAULT_ENGINE_ROOT
    sys.path.insert(0, str(engine_root))
    try:
        flow = importlib.import_module("paypal.flow")
    finally:
        try:
            sys.path.remove(str(engine_root))
        except ValueError:
            pass

    assert flow.PayPalFlow._is_address_related_signup_error([
        {
            "errorType": "VALIDATION_ERROR",
            "message": "RESIDENTIAL_ADDRESS_NOT_FOUND",
            "path": ["onboardAccount"],
        }
    ])


def test_gb_signup_variables_match_weasley_primary_residential_shape(monkeypatch):
    engine_root = service.DEFAULT_ENGINE_ROOT
    sys.path.insert(0, str(engine_root))
    try:
        flow = importlib.import_module("paypal.flow")
        models = importlib.import_module("paypal.models")
    finally:
        try:
            sys.path.remove(str(engine_root))
        except ValueError:
            pass

    paypal_flow = flow.PayPalFlow.__new__(flow.PayPalFlow)
    paypal_flow.address = models.BillingAddress(
        street="27 Victoria Road",
        house_number="",
        district="",
        city="Cambridge",
        state="",
        postal_code="CB4 3BW",
        country="GB",
    )
    paypal_flow.user = models.UserInfo(
        first_name="Oliver",
        last_name="Smith",
        email="oliver.smith123@example.test",
        phone="+447700900123",
        phone_local="7700900123",
        phone_country_code="+44",
        password="Passw0rd!",
        dob="01/02/1988",
        cpf="",
    )
    paypal_flow.card = models.CardInfo(
        number="4111111111111111",
        expiry="08/2028",
        cvv="123",
    )
    paypal_flow.state = models.SessionState()
    paypal_flow._billing_address_autocomplete_succeeded = False
    monkeypatch.setattr(paypal_flow, "_content_metadata_is_unresolved", lambda: False)
    monkeypatch.setattr(paypal_flow, "_resolved_content_identifier", lambda: "GB:en:test:compliance.signupTerms")

    variables = paypal_flow._build_signup_variables("EC-TEST")

    assert "shippingAddress" not in variables
    assert variables["billingAddress"]["postalCode"] == "CB4 3BW"
    assert variables["billingAddress"]["line1"] == "27 Victoria Road"
    assert "line2" not in variables["billingAddress"]
    assert "state" not in variables["billingAddress"]
    assert variables["residentialAddress"] == variables["billingAddress"]
    assert variables["dateOfBirth"] == {"day": "01", "month": "02", "year": "1988"}


@pytest.mark.parametrize("country", ["AU", "CA", "ID", "JP", "MX", "PH", "TH", "NL"])
def test_non_brazil_protocol_countries_omit_empty_shipping_address(monkeypatch, country):
    engine_root = service.DEFAULT_ENGINE_ROOT
    sys.path.insert(0, str(engine_root))
    try:
        flow = importlib.import_module("paypal.flow")
        models = importlib.import_module("paypal.models")
    finally:
        try:
            sys.path.remove(str(engine_root))
        except ValueError:
            pass

    paypal_flow = flow.PayPalFlow.__new__(flow.PayPalFlow)
    paypal_flow.address = models.generate_address(country=country)
    paypal_flow.user = models.generate_user("+19995550123", country=country)
    paypal_flow.card = models.CardInfo(
        number="4111111111111111",
        expiry="08/2028",
        cvv="123",
    )
    paypal_flow.state = models.SessionState()
    paypal_flow._billing_address_autocomplete_succeeded = False
    monkeypatch.setattr(paypal_flow, "_content_metadata_is_unresolved", lambda: False)
    monkeypatch.setattr(
        paypal_flow,
        "_resolved_content_identifier",
        lambda: f"{country}:en:test:compliance.signupTerms",
    )

    variables = paypal_flow._build_signup_variables("EC-TEST")

    assert "shippingAddress" not in variables
    assert variables["billingAddress"]["country"] == country
    assert variables["phone"]["countryCode"] == paypal_flow.user.phone_country_code.lstrip("+")


def test_australia_generated_address_uses_state_abbreviation_and_four_digit_postcode():
    engine_root = service.DEFAULT_ENGINE_ROOT
    sys.path.insert(0, str(engine_root))
    try:
        models = importlib.import_module("paypal.models")
    finally:
        try:
            sys.path.remove(str(engine_root))
        except ValueError:
            pass

    valid_states = {"NSW", "VIC", "QLD", "SA", "WA", "TAS", "ACT", "NT"}
    for _ in range(50):
        address = models.generate_address(country="AU")
        assert address.country == "AU"
        assert address.state in valid_states
        assert address.postal_code.isdigit()
        assert len(address.postal_code) == 4
        assert address.street[0].isdigit()
        assert not address.house_number


def test_gb_auto_approval_path_uses_create_member_no_fi(monkeypatch):
    engine_root = service.DEFAULT_ENGINE_ROOT
    sys.path.insert(0, str(engine_root))
    try:
        flow = importlib.import_module("paypal.flow")
        models = importlib.import_module("paypal.models")
    finally:
        try:
            sys.path.remove(str(engine_root))
        except ValueError:
            pass

    paypal_flow = flow.PayPalFlow.__new__(flow.PayPalFlow)
    paypal_flow.address = models.BillingAddress(
        street="27 Victoria Road",
        house_number="",
        district="",
        city="Cambridge",
        state="",
        postal_code="CB4 3BW",
        country="GB",
    )
    monkeypatch.setenv("PAYPAL_APPROVAL_PATH", "auto")

    assert paypal_flow._create_member_no_fi_enabled() is True


def test_build_protocol_command_supports_gb_with_auto_path_and_sms_default(tmp_path, monkeypatch):
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "main.py").write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.setenv("AUTOTEAM_PAYPAL_ENGINE_ROOT", str(engine))

    cmd, env, _cwd = service.build_protocol_command(service.PaypalProtocolRunConfig(
        ba_token="BA-1GBCMD123",
        sms_provider="smsbower",
        country="GB",
    ))

    assert cmd[cmd.index("--country") + 1] == "GB"
    assert cmd[cmd.index("--approval-path") + 1] == "auto"
    assert cmd[cmd.index("--sms-country") + 1] == "16"
    assert env["PAYPAL_COUNTRY"] == "GB"
    assert env["PAYPAL_APPROVAL_PATH"] == "auto"
    assert env["PAYPAL_SMS_COUNTRY"] == "16"


def test_build_protocol_command_uses_provider_country_map_not_frontend_or_global(tmp_path, monkeypatch):
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "main.py").write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.setenv("AUTOTEAM_PAYPAL_ENGINE_ROOT", str(engine))
    monkeypatch.setenv("PAYPAL_SMS_COUNTRY", "999")
    monkeypatch.setenv("PAYPAL_HERO_SMS_COUNTRY_NL", "148")

    cmd, env, _cwd = service.build_protocol_command(service.PaypalProtocolRunConfig(
        ba_token="BA-1NLCMD123",
        sms_provider="hero_sms",
        sms_country="777",
        country="NL",
    ))

    assert cmd[cmd.index("--sms-country") + 1] == "148"
    assert env["PAYPAL_SMS_COUNTRY"] == "148"


def test_build_protocol_command_reuses_settings_smsbower_key_fallback(tmp_path, monkeypatch):
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "main.py").write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.setenv("AUTOTEAM_PAYPAL_ENGINE_ROOT", str(engine))
    monkeypatch.setattr(service, "_load_project_env", lambda: {})
    monkeypatch.delenv("PAYPAL_SMSBOWER_API_KEY", raising=False)
    monkeypatch.delenv("SMSBOWER_API_KEY", raising=False)
    monkeypatch.delenv("OAUTH_SMSBOWER_API_KEY", raising=False)
    monkeypatch.delenv("PAYPAL_SMSBOWER_BASE_URL", raising=False)
    monkeypatch.delenv("SMSBOWER_BASE_URL", raising=False)
    monkeypatch.delenv("OAUTH_SMSBOWER_BASE_URL", raising=False)
    monkeypatch.setenv("GOPAY_AUTO_SIGNUP_SMSBOWER_API_KEY", "settings-smsbower-key")
    monkeypatch.setenv("GOPAY_AUTO_SIGNUP_SMSBOWER_BASE_URL", "https://settings.example/stubs/handler_api.php")

    cmd, env, _cwd = service.build_protocol_command(service.PaypalProtocolRunConfig(
        ba_token="BA-1SMSBOWERSETTINGS123",
        sms_provider="smsbower",
        country="GB",
    ))

    assert cmd[cmd.index("--sms-country") + 1] == "16"
    assert env["PAYPAL_SMSBOWER_API_KEY"] == "settings-smsbower-key"
    assert env["PAYPAL_SMSBOWER_BASE_URL"] == "https://settings.example/stubs/handler_api.php"


def test_protocol_service_classifies_oas_error(tmp_path, monkeypatch):
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "main.py").write_text(
        "print('GraphQL CreateMemberAccountMutation returned errors: OAS_ERROR createMemberAccount')\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTOTEAM_PAYPAL_ENGINE_ROOT", str(engine))

    result = service.run_paypal_protocol_payment(service.PaypalProtocolRunConfig(
        ba_token="BA-1OAS123",
        phone="+18350000000",
        sms_record_url="https://sms.example/api?token=secret",
    ))

    assert result["status"] == "failed"
    assert "OAS_ERROR" in result["message"]
    assert "createMemberAccount" in result["message"]


def test_protocol_service_classifies_signup_context_preflight_block(tmp_path, monkeypatch):
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "main.py").write_text(
        "print('Signup-context browser risk incomplete before CreateMemberAccount; blocked to avoid PayPal OAS_ERROR: missing=fraudnet_p1')\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTOTEAM_PAYPAL_ENGINE_ROOT", str(engine))

    result = service.run_paypal_protocol_payment(service.PaypalProtocolRunConfig(
        ba_token="BA-1MISS123",
        phone="+18350000000",
        sms_record_url="https://sms.example/api?token=secret",
    ))

    assert result["status"] == "failed"
    assert "风控信号不完整" in result["message"]


def test_protocol_service_classifies_mtr_missing_before_authchallenge(tmp_path, monkeypatch):
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "main.py").write_text(
        "print('PayPal authchallenge type=recaptcha requires manual/official verification')\n"
        "print('RESULT:')\n"
        "print('{\"status\":\"error\",\"risk_runtime\":{\"strict_blockers\":[\"mtr_sealedResult_missing\"]}}')\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTOTEAM_PAYPAL_ENGINE_ROOT", str(engine))

    logs: list[str] = []
    result = service.run_paypal_protocol_payment(
        service.PaypalProtocolRunConfig(
            ba_token="BA-1MTR123",
            phone="+18350000000",
            sms_record_url="https://sms.example/api?token=secret",
        ),
        log=logs.append,
    )

    assert result["status"] == "failed"
    assert "MTR" in result["message"]
    assert "sealedResult" in result["message"]
    assert any("RESULT JSON" in line for line in logs)
    assert not any("strict_blockers" in line for line in logs)


def test_protocol_service_classifies_member_approve_failure_from_result(tmp_path, monkeypatch):
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "main.py").write_text(
        "print('RESULT:')\n"
        "print('{\"status\":\"error\",\"error\":\"approveMemberPayment returned empty result\"}')\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTOTEAM_PAYPAL_ENGINE_ROOT", str(engine))

    result = service.run_paypal_protocol_payment(service.PaypalProtocolRunConfig(
        ba_token="BA-1APPROVE123",
        phone="+18350000000",
        sms_record_url="https://sms.example/api?token=secret",
    ))

    assert result["status"] == "failed"
    assert "member approve" in result["message"]


def test_protocol_service_records_terminal_ba_and_blocks_retry(tmp_path, monkeypatch):
    engine = tmp_path / "engine"
    engine.mkdir()
    script = engine / "main.py"
    script.write_text(
        "print('Member account created without backup FI. User ID: TEST')\n"
        "print('ApproveMemberPaymentMutation returned errors')\n"
        "print('RESULT:')\n"
        "print('{\"status\":\"error\",\"error\":\"approveMemberPayment returned empty result\"}')\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTOTEAM_PAYPAL_ENGINE_ROOT", str(engine))
    monkeypatch.setattr(service, "TERMINAL_BA_FILE", tmp_path / "terminal_ba.json")

    cfg = service.PaypalProtocolRunConfig(
        ba_token="BA-1TERM123",
        phone="+18350000000",
        sms_record_url="https://sms.example/api?token=secret",
    )
    first_logs: list[str] = []
    first = service.run_paypal_protocol_payment(cfg, log=first_logs.append)

    assert first["status"] == "failed"
    assert service.terminal_ba_record("BA-1TERM123")
    assert any("本机终态" in line for line in first_logs)

    script.write_text(
        "print('should run')\n"
        "print('GraphQL ApproveMemberPaymentMutation HTTP 200 bytes=1166')\n"
        "print('  \"state\": \"APPROVED\",')\n"
        "print('=== Flow completed successfully ===')\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    second_logs: list[str] = []
    second = service.run_paypal_protocol_payment(cfg, log=second_logs.append)

    assert second["status"] == "failed"
    assert "不可安全重试" in second["message"]
    assert "fresh BA" in second["message"]
    assert not any("should run" in line for line in second_logs)
    assert any("阻止重复协议支付" in line for line in second_logs)


def test_protocol_service_treats_success_log_as_success_when_result_json_missing(tmp_path, monkeypatch):
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "main.py").write_text(
        "print('GraphQL ApproveMemberPaymentMutation HTTP 200 bytes=1166')\n"
        "print('  \"state\": \"APPROVED\",')\n"
        "print('=== Flow completed successfully ===')\n"
        "print('RESULT:')\n"
        "print('{not-json')\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTOTEAM_PAYPAL_ENGINE_ROOT", str(engine))

    result = service.run_paypal_protocol_payment(service.PaypalProtocolRunConfig(
        ba_token="BA-1SUCCESS123",
        phone="+18350000000",
        sms_record_url="https://sms.example/api?token=secret",
    ))

    assert result["status"] == "success"
    assert result["protocol_result"]["inferred_from_log"] is True


def test_protocol_service_does_not_fail_success_on_risk_runtime_diagnostic(tmp_path, monkeypatch):
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "main.py").write_text(
        "print('=== Flow completed successfully ===')\n"
        "print('RESULT:')\n"
        "print('{\"status\":\"success\",\"risk_runtime\":{\"strict_blockers\":[\"mtr_sealedResult_missing\"]}}')\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTOTEAM_PAYPAL_ENGINE_ROOT", str(engine))

    result = service.run_paypal_protocol_payment(service.PaypalProtocolRunConfig(
        ba_token="BA-1RISKSUCCESS123",
        phone="+18350000000",
        sms_record_url="https://sms.example/api?token=secret",
    ))

    assert result["status"] == "success"
    assert "message" not in result
