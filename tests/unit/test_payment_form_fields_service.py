from autotoken.services import payment_form_fields

class FakeLocator:
    def __init__(
        self,
        *,
        tag="INPUT",
        input_value="",
        text_content="",
        selected_text="",
        evaluate_result=True,
        fail_evaluate=False,
        fail_select=True,
        fail_fill=False,
    ):
        self.tag = tag
        self.input_value_value = input_value
        self.text_content_value = text_content
        self.selected_text = selected_text
        self.evaluate_result = evaluate_result
        self.fail_evaluate = fail_evaluate
        self.fail_select = fail_select
        self.fail_fill = fail_fill
        self.evaluations = []
        self.select_calls = []
        self.waits = []
        self.clicked = False
        self.filled = []
        self.scrolled = []
        self.pressed = []
        self.typed = []

    def evaluate(self, script, *args, **kwargs):
        self.evaluations.append((script, args, kwargs))
        if script == "el => el.tagName":
            return self.tag
        if "selectedOptions" in script:
            return self.selected_text
        if self.fail_evaluate:
            raise RuntimeError("evaluate failed")
        return self.evaluate_result

    def select_option(self, *, value=None, label=None, timeout=None):
        self.select_calls.append({"value": value, "label": label, "timeout": timeout})
        if self.fail_select:
            raise RuntimeError("select failed")
        return None

    def click(self, timeout=None):
        self.clicked = True

    def press(self, key, timeout=None):
        self.pressed.append((key, timeout))

    def type(self, value, delay=None, timeout=None):
        self.typed.append((value, delay, timeout))
        self.input_value_value = value

    def fill(self, value, timeout=None):
        if self.fail_fill:
            raise RuntimeError("fill failed")
        self.input_value_value = value
        self.filled.append((value, timeout))

    def wait_for(self, state=None, timeout=None):
        self.waits.append((state, timeout))

    def scroll_into_view_if_needed(self, timeout=None):
        self.scrolled.append(timeout)

    def input_value(self, timeout=None):
        if self.input_value_value is None:
            raise RuntimeError("no input")
        return self.input_value_value

    def text_content(self, timeout=None):
        if self.text_content_value is None:
            raise RuntimeError("no text")
        return self.text_content_value

US_STATE_NAME_TO_CODE = {
    "california": "CA",
    "new york": "NY",
}
US_STATE_CODE_TO_NAME = {code: name for name, code in US_STATE_NAME_TO_CODE.items()}
JP_PREFECTURE_NAME_TO_JA = {
    "tokyo": "東京都",
    "tokyo-to": "東京都",
    "osaka": "大阪府",
    "osaka-fu": "大阪府",
}

def test_value_matches_normalizes_whitespace_and_case():
    assert payment_form_fields.value_matches("501  Holly Avenue", "501 Holly Avenue") is True
    assert payment_form_fields.value_matches("Panama City", "panama city") is True
    assert payment_form_fields.value_matches("FL", "CA") is False

def test_state_value_matches_accepts_us_state_name_or_abbreviation():
    assert (
        payment_form_fields.state_value_matches(
            "California",
            "CA",
            state_name_to_code=US_STATE_NAME_TO_CODE,
            state_code_to_name=US_STATE_CODE_TO_NAME,
            prefecture_name_to_ja=JP_PREFECTURE_NAME_TO_JA,
        )
        is True
    )
    assert (
        payment_form_fields.state_value_matches(
            "New York",
            "NY",
            state_name_to_code=US_STATE_NAME_TO_CODE,
            state_code_to_name=US_STATE_CODE_TO_NAME,
            prefecture_name_to_ja=JP_PREFECTURE_NAME_TO_JA,
        )
        is True
    )
    assert (
        payment_form_fields.state_value_matches(
            "California",
            "NY",
            state_name_to_code=US_STATE_NAME_TO_CODE,
            state_code_to_name=US_STATE_CODE_TO_NAME,
            prefecture_name_to_ja=JP_PREFECTURE_NAME_TO_JA,
        )
        is False
    )

def test_state_value_matches_accepts_japanese_prefecture_label_and_suffixless_value():
    assert payment_form_fields.jp_prefecture_candidates("Tokyo", prefecture_name_to_ja=JP_PREFECTURE_NAME_TO_JA) == [
        "Tokyo",
        "東京都",
        "東京",
    ]
    assert (
        payment_form_fields.state_value_matches(
            "Tokyo",
            "東京都",
            state_name_to_code=US_STATE_NAME_TO_CODE,
            state_code_to_name=US_STATE_CODE_TO_NAME,
            prefecture_name_to_ja=JP_PREFECTURE_NAME_TO_JA,
        )
        is True
    )
    assert (
        payment_form_fields.state_value_matches(
            "東京都",
            "東京",
            state_name_to_code=US_STATE_NAME_TO_CODE,
            state_code_to_name=US_STATE_CODE_TO_NAME,
            prefecture_name_to_ja=JP_PREFECTURE_NAME_TO_JA,
        )
        is True
    )
    assert (
        payment_form_fields.state_value_matches(
            "Tokyo",
            "大阪府",
            state_name_to_code=US_STATE_NAME_TO_CODE,
            state_code_to_name=US_STATE_CODE_TO_NAME,
            prefecture_name_to_ja=JP_PREFECTURE_NAME_TO_JA,
        )
        is False
    )

def test_field_value_matches_handles_card_expiry_and_phone_callbacks():
    def normalize_card_expiry(value):
        digits = "".join(ch for ch in str(value or "") if ch.isdigit())
        return digits[-4:]

    def normalize_phone(value):
        digits = "".join(ch for ch in str(value or "") if ch.isdigit())
        if digits.startswith("81"):
            digits = "0" + digits[2:]
        return digits

    def phone_value_valid(value):
        return len(normalize_phone(value)) >= 10

    kwargs = {
        "state_name_to_code": US_STATE_NAME_TO_CODE,
        "state_code_to_name": US_STATE_CODE_TO_NAME,
        "prefecture_name_to_ja": JP_PREFECTURE_NAME_TO_JA,
        "normalize_card_expiry": normalize_card_expiry,
        "normalize_phone": normalize_phone,
        "phone_value_valid": phone_value_valid,
    }

    assert payment_form_fields.field_value_matches("12/28", "1228", field="card_expiry", **kwargs) is True
    assert payment_form_fields.field_value_matches("123", "123", field="card_cvv", **kwargs) is True
    assert payment_form_fields.field_value_matches("09026647330", "+81 90-2664-7330", field="phone", **kwargs) is True
    assert payment_form_fields.field_value_matches("09026647330", "+81", field="phone", **kwargs) is False

def test_luhn_helpers_validate_generated_card_digits():
    assert payment_form_fields.luhn_check_digit("411111111111111") == "1"
    assert payment_form_fields.luhn_valid("4111 1111 1111 1111") is True
    assert payment_form_fields.luhn_valid("4111 1111 1111 1112") is False
    assert payment_form_fields.luhn_valid("411111") is False

def test_checkout_value_matches_handles_country_postal_code_and_state():
    kwargs = {
        "state_name_to_code": US_STATE_NAME_TO_CODE,
        "state_code_to_name": US_STATE_CODE_TO_NAME,
        "prefecture_name_to_ja": JP_PREFECTURE_NAME_TO_JA,
    }

    assert payment_form_fields.checkout_value_matches("country", "US", "United States", **kwargs) is True
    assert payment_form_fields.checkout_value_matches("postal_code", "100-0001", "1000001", **kwargs) is True
    assert payment_form_fields.checkout_value_matches("state", "California", "CA", **kwargs) is True
    assert payment_form_fields.checkout_value_matches("city", "New  York", "new york", **kwargs) is True
    assert payment_form_fields.checkout_value_matches("city", "", "", **kwargs) is True

def test_set_locator_value_dispatches_with_autocomplete_disabled_for_gopay_mode():
    locator = FakeLocator(tag="INPUT")

    assert (
        payment_form_fields.set_locator_value(
            locator,
            "123 Main St",
            disable_autocomplete=True,
            dispatch_timeout=2000,
        )
        is True
    )

    script, args, kwargs = locator.evaluations[-1]
    assert "autocomplete" in script
    assert args[0]["value"] == "123 Main St"
    assert args[0]["disableAutocomplete"] is True
    assert args[0]["focus"] is False
    assert kwargs["timeout"] == 2000

def test_set_locator_value_falls_back_to_fill_when_dispatch_fails():
    locator = FakeLocator(tag="INPUT", fail_evaluate=True)

    assert payment_form_fields.set_locator_value(locator, "fallback", fill_fallback=True) is True

    assert locator.clicked is True
    assert locator.filled == [("fallback", 1500)]

def test_set_locator_value_can_use_legacy_dispatch_argument():
    locator = FakeLocator(tag="INPUT")

    assert payment_form_fields.set_locator_value(locator, "11 Main St", legacy_dispatch_arg=True) is True

    assert locator.evaluations[-1][1] == ("11 Main St",)

def test_select_state_locator_value_uses_japanese_prefecture_candidates_for_select_fallback():
    locator = FakeLocator(tag="SELECT", fail_select=True, evaluate_result=True)

    assert (
        payment_form_fields.select_state_locator_value(
            locator,
            "Tokyo",
            country="JP",
            normalize_country=lambda value: str(value or "").upper(),
            jp_prefecture_candidates=lambda value: payment_form_fields.jp_prefecture_candidates(
                value,
                prefecture_name_to_ja=JP_PREFECTURE_NAME_TO_JA,
            ),
            set_value=payment_form_fields.set_locator_value,
        )
        is True
    )

    assert locator.select_calls == [
        {"value": "Tokyo", "label": None, "timeout": 1000},
        {"value": None, "label": "Tokyo", "timeout": 1000},
        {"value": "東京都", "label": None, "timeout": 1000},
        {"value": None, "label": "東京都", "timeout": 1000},
        {"value": "東京", "label": None, "timeout": 1000},
        {"value": None, "label": "東京", "timeout": 1000},
    ]
    assert locator.evaluations[-1][1] == (["Tokyo", "東京都", "東京"],)

def test_type_locator_value_selects_existing_value_before_typing():
    locator = FakeLocator(tag="INPUT")

    assert payment_form_fields.type_locator_value(locator, "typed") is True

    assert locator.clicked is True
    assert locator.pressed == [("Control+A", 1000), ("Backspace", 1000)]
    assert locator.typed == [("typed", 8, 6000)]

def test_set_verified_locator_value_tries_setters_until_readback_matches():
    locator = FakeLocator(tag="INPUT", input_value="old")
    calls = []

    def first_setter(_locator, _value):
        calls.append("first")
        return False

    def second_setter(target, value):
        calls.append("second")
        target.input_value_value = value
        return True

    assert (
        payment_form_fields.set_verified_locator_value(
            locator,
            "new",
            setters=(first_setter, second_setter),
            read_value=lambda target: target.input_value(),
            matches=lambda expected, actual, field="": expected == actual,
            sleep=lambda _seconds: None,
        )
        is True
    )
    assert calls == ["first", "second"]

def test_fast_autofill_fields_evaluates_only_missing_fields_across_frames():
    class FakeFrame:
        def __init__(self, result):
            self.result = result
            self.calls = []

        def evaluate(self, _script, payload):
            self.calls.append(payload)
            return self.result

    first = FakeFrame(["address1"])
    second = FakeFrame(["city"])

    result = payment_form_fields.fast_autofill_fields(
        [first, second],
        {"country": "US", "address1": "11 Main St", "city": "New York"},
        fast_selectors={"address1": ["#a1"], "city": ["#city"], "country": ["#country"]},
    )

    assert set(result) == {"address1", "city"}
    assert first.calls[0]["fields"] == {"address1": "11 Main St", "city": "New York"}
    assert second.calls[0]["fields"] == {"city": "New York"}

def test_autofill_checkout_fields_falls_back_when_fast_readback_mismatches():
    locator = FakeLocator(tag="INPUT", input_value="wrong value")
    dismissed = []

    result = payment_form_fields.autofill_checkout_fields(
        {"address1": "11 Main St"},
        current_url="https://pay.openai.com/c/pay/cs_live_test",
        selectors={"address1": ["#billingAddressLine1"]},
        normalize_payload=lambda payload: dict(payload or {}),
        autofill_allowed=lambda _url: True,
        suppress_autocomplete=lambda: None,
        dismiss_autocomplete=lambda target=None: dismissed.append(target),
        fast_autofill=lambda _fields: ["address1"],
        read_checkout_value=lambda _key: locator.input_value(),
        checkout_value_matches=lambda _key, expected, actual: expected == actual,
        visible_locator=lambda _selectors, timeout_ms: locator,
        set_value=lambda target, value: setattr(target, "input_value_value", value) is None,
        progress=None,
        sleep=lambda _seconds: None,
    )

    assert result == {"filled": ["address1"], "skipped": []}
    assert locator.input_value() == "11 Main St"
    assert dismissed == [locator, locator]

def test_checkout_billing_required_fields_prefers_zip_alias_and_default_country():
    result = payment_form_fields.checkout_billing_required_fields(
        {
            "address1": " 11 Main St ",
            "city": " New York ",
            "state": " NY ",
            "zip": " 10001 ",
            "postal_code": "ignored",
        }
    )

    assert result == {
        "country": "US",
        "address1": "11 Main St",
        "city": "New York",
        "state": "NY",
        "postal_code": "10001",
    }

def test_fill_checkout_billing_form_retries_until_readback_matches():
    payload = {"country": "US", "address1": "11 Main St", "city": "New York", "state": "NY", "zip": "10001"}
    values_by_attempt = [
        {"country": "US", "address1": "", "city": "New York", "state": "NY", "postal_code": "10001"},
        {"country": "US", "address1": "11 Main St", "city": "New York", "state": "NY", "postal_code": "10001"},
    ]
    autofill_calls = []
    progress_events = []
    suppress_calls = []
    screenshots = []

    def read_value(key):
        return values_by_attempt[min(len(autofill_calls) - 1, len(values_by_attempt) - 1)][key]

    result = payment_form_fields.fill_checkout_billing_form(
        payload,
        suppress_autocomplete=lambda: suppress_calls.append(True),
        autofill_checkout=lambda data: autofill_calls.append(dict(data)),
        read_checkout_value=read_value,
        checkout_value_matches=lambda _key, expected, actual: expected == actual,
        capture_failure=lambda: screenshots.append("failed"),
        progress=lambda stage, **_kwargs: progress_events.append(stage),
        sleep=lambda _seconds: None,
    )

    assert result == (True, "")
    assert len(autofill_calls) == 2
    assert len(suppress_calls) == 2
    assert progress_events == ["fill_billing_info"]
    assert screenshots == []

def test_fill_checkout_billing_form_fails_fast_when_required_fields_missing():
    progress_events = []
    calls = []

    result = payment_form_fields.fill_checkout_billing_form(
        {"country": "US", "address1": "", "city": "New York", "state": "NY", "zip": "10001"},
        suppress_autocomplete=lambda: calls.append("suppress"),
        autofill_checkout=lambda _payload: calls.append("autofill"),
        read_checkout_value=lambda _key: "",
        checkout_value_matches=lambda _key, expected, actual: expected == actual,
        capture_failure=lambda: calls.append("capture"),
        progress=lambda stage, **_kwargs: progress_events.append(stage),
        sleep=lambda _seconds: None,
    )

    assert result == (False, "账单地址缺少国家/地址/城市/州/邮编")
    assert progress_events == ["fill_billing_info"]
    assert calls == []

def test_fill_checkout_billing_form_captures_failure_after_attempts_exhausted():
    payload = {"country": "US", "address1": "11 Main St", "city": "New York", "state": "NY", "zip": "10001"}
    screenshots = []
    attempts = []

    ok, message = payment_form_fields.fill_checkout_billing_form(
        payload,
        suppress_autocomplete=lambda: None,
        autofill_checkout=lambda data: attempts.append(dict(data)),
        read_checkout_value=lambda key: "wrong" if key == "address1" else payload.get(key, payload.get("zip", "")),
        checkout_value_matches=lambda _key, expected, actual: expected == actual,
        capture_failure=lambda: screenshots.append("failed"),
        sleep=lambda _seconds: None,
        max_attempts=2,
    )

    assert ok is False
    assert "地址字段校验失败" in message
    assert "address1" in message
    assert len(attempts) == 2
    assert screenshots == ["failed"]

def test_fill_signup_birth_date_if_needed_skips_non_jp_country():
    calls = []

    result = payment_form_fields.fill_signup_birth_date_if_needed(
        {"birth_date": "1985/01/15"},
        country="US",
        default_birth_date="1980/01/01",
        birth_date_selectors=["#birth"],
        normalize_country=lambda country: country,
        visible_locator=lambda _selectors, timeout_ms: calls.append("visible"),
        set_value=lambda _locator, _value: calls.append("set"),
        read_value=lambda _locator: "",
        sleep=lambda _seconds: None,
    )

    assert result == (True, "")
    assert calls == []

def test_fill_signup_birth_date_if_needed_uses_default_for_jp_when_missing():
    locator = FakeLocator(input_value="1980/01/01")
    values = []

    result = payment_form_fields.fill_signup_birth_date_if_needed(
        {},
        country="jp",
        default_birth_date="1980/01/01",
        birth_date_selectors=["#birth"],
        normalize_country=lambda country: country.upper(),
        visible_locator=lambda _selectors, timeout_ms: locator,
        set_value=lambda target, value: values.append(value) or setattr(target, "input_value_value", value),
        read_value=lambda target: target.input_value(),
        sleep=lambda _seconds: None,
    )

    assert result == (True, "")
    assert values == ["1980/01/01"]

def test_fill_signup_birth_date_if_needed_allows_dom_fallback_when_locator_missing():
    result = payment_form_fields.fill_signup_birth_date_if_needed(
        {"birthDate": "1985/01/15"},
        country="JP",
        default_birth_date="1980/01/01",
        birth_date_selectors=["#birth"],
        normalize_country=lambda country: country,
        visible_locator=lambda _selectors, timeout_ms: None,
        set_value=lambda _locator, _value: None,
        read_value=lambda _locator: "",
        sleep=lambda _seconds: None,
    )

    assert result == (True, "")

def test_validate_signup_dom_result_filters_optional_missing_fields():
    ok, error, still_missing = payment_form_fields.validate_signup_dom_result(
        {"stillMissing": ["email", "phone", ""]},
        country="US",
        optional_skip_fields={"email"},
        normalize_country=lambda country: country,
    )

    assert (ok, error) == (True, "")
    assert still_missing == ["phone"]

def test_validate_signup_dom_result_allows_jp_specific_missing_fields_for_non_jp_country():
    ok, error, still_missing = payment_form_fields.validate_signup_dom_result(
        {"stillMissing": ["birth_date", "native_first_name"]},
        country="US",
        optional_skip_fields=set(),
        normalize_country=lambda country: country,
    )

    assert (ok, error) == (True, "")
    assert still_missing == ["birth_date", "native_first_name"]

def test_build_signup_visible_form_payload_normalizes_card_digits_and_default_country():
    payload = payment_form_fields.build_signup_visible_form_payload(
        {
            "email": " user@example.com ",
            "card_number": "4111 1111-1111 1111",
            "card_cvv": " 12-3 ",
            "country": "",
            "address2": " Apt 5 ",
        },
        normalize_country=lambda country: country,
        default_birth_date="1980/01/01",
        default_native_first_name="太郎",
        default_native_last_name="山田",
    )

    assert payload["email"] == "user@example.com"
    assert payload["card_number"] == "4111111111111111"
    assert payload["card_cvv"] == "123"
    assert payload["country"] == "US"
    assert payload["address2"] == "Apt 5"
    assert "birth_date" not in payload

def test_build_signup_visible_form_payload_adds_jp_aliases_and_defaults():
    payload = payment_form_fields.build_signup_visible_form_payload(
        {
            "country": "jp",
            "birthDate": "1990/02/03",
            "nativeFirstName": "花子",
        },
        normalize_country=lambda country: country.upper(),
        default_birth_date="1980/01/01",
        default_native_first_name="太郎",
        default_native_last_name="山田",
    )

    assert payload["country"] == "jp"
    assert payload["birth_date"] == "1990/02/03"
    assert payload["native_first_name"] == "花子"
    assert payload["native_last_name"] == "山田"

def test_select_country_locator_prefers_requested_country_value_before_fallback():
    calls = []

    class FakeCountryLocator:
        def select_option(self, *, value=None, label=None, timeout=None):
            calls.append(("value" if value is not None else "label", value or label, timeout))
            if value == "JP":
                return None
            raise RuntimeError("unexpected fallback")

    assert (
        payment_form_fields.select_country_locator(
            FakeCountryLocator(),
            "jp",
            normalize_country=lambda country: country.upper(),
            country_labels={"JP": ("Japan", "日本")},
            sleep=lambda _seconds: None,
        )
        is True
    )
    assert calls == [("value", "JP", 1200)]

def test_select_country_locator_tries_label_and_us_fallback_for_non_us_country():
    calls = []

    class FakeCountryLocator:
        def select_option(self, *, value=None, label=None, timeout=None):
            calls.append(("value" if value is not None else "label", value or label))
            if label == "United States":
                return None
            raise RuntimeError("option unavailable")

    assert (
        payment_form_fields.select_country_locator(
            FakeCountryLocator(),
            "JP",
            normalize_country=lambda country: country,
            country_labels={"JP": ("Japan", "日本")},
            sleep=lambda _seconds: None,
        )
        is True
    )
    assert calls == [
        ("value", "JP"),
        ("label", "JP"),
        ("value", "Japan"),
        ("label", "Japan"),
        ("value", "日本"),
        ("label", "日本"),
        ("value", "US"),
        ("label", "US"),
        ("value", "United States"),
        ("label", "United States"),
    ]

def test_set_first_visible_value_with_locator_returns_false_without_locator():
    calls = []

    result = payment_form_fields.set_first_visible_value_with_locator(
        selectors=["#missing"],
        value="new",
        visible_locator=lambda _selectors, timeout_ms: None,
        set_value=lambda _locator, _value: calls.append("set") or True,
    )

    assert result == (False, None)
    assert calls == []

def test_set_first_visible_value_with_locator_sets_visible_locator():
    locator = FakeLocator(input_value="")

    result = payment_form_fields.set_first_visible_value_with_locator(
        selectors=["#field"],
        value="new",
        visible_locator=lambda _selectors, timeout_ms: locator,
        set_value=lambda target, value: setattr(target, "input_value_value", value) is None,
    )

    assert result == (True, locator)
    assert locator.input_value() == "new"
    assert (
        payment_form_fields.set_first_visible_value(
            selectors=["#field"],
            value="again",
            visible_locator=lambda _selectors, timeout_ms: locator,
            set_value=lambda target, value: setattr(target, "input_value_value", value) is None,
        )
        is True
    )
    assert locator.input_value() == "again"

def test_read_locator_value_prefers_select_text_when_requested():
    locator = FakeLocator(tag="SELECT", input_value="CA", selected_text="California")

    assert payment_form_fields.read_locator_value(locator, prefer_select_text=True) == "California"

def test_read_locator_value_falls_back_to_text_content():
    locator = FakeLocator(tag="DIV", input_value=None, text_content="  Visible text  ")

    assert payment_form_fields.read_locator_value(locator) == "Visible text"

def test_visible_locator_in_frames_uses_api_helper_override():
    class FakeApi:
        def __init__(self):
            self.calls = []
            self.locator = object()

        def _visible_locator_in_frames(self, selectors, timeout_ms=1000):
            self.calls.append((selectors, timeout_ms))
            return self.locator

    api = FakeApi()

    assert payment_form_fields.visible_locator_in_frames(api, ["button"], timeout_ms=250) is api.locator
    assert api.calls == [(["button"], 250)]

def test_attached_locator_in_frames_returns_first_attached_selector():
    found = FakeLocator()

    class MissingLocator:
        @property
        def first(self):
            return self

        def wait_for(self, state=None, timeout=None):
            raise RuntimeError("missing")

    class FoundLocator:
        @property
        def first(self):
            return found

    class FakeFrame:
        def __init__(self, hit=False):
            self.hit = hit

        def locator(self, selector):
            return FoundLocator() if self.hit else MissingLocator()

    locator = payment_form_fields.attached_locator_in_frames([FakeFrame(), FakeFrame(hit=True)], ["#field"], 300)

    assert locator is found
    assert found.waits == [("attached", 300)]

def test_resolve_locator_in_frames_prefers_selector_before_placeholder():
    selector_locator = FakeLocator()

    class FakeFrame:
        def locator(self, selector):
            class Wrapper:
                first = selector_locator

            return Wrapper()

        def get_by_placeholder(self, text, exact=None):
            raise AssertionError("placeholder should not be used")

        def get_by_label(self, text, exact=None):
            raise AssertionError("label should not be used")

    locator = payment_form_fields.resolve_locator_in_frames(
        [FakeFrame()],
        ["input[name=name]"],
        placeholders=["Name"],
        labels=["Full name"],
        timeout_ms=900,
    )

    assert locator is selector_locator
    assert selector_locator.waits == [("visible", 400)]

def test_resolve_locator_in_frames_falls_back_to_placeholder():
    placeholder_locator = FakeLocator()

    class MissingLocator:
        @property
        def first(self):
            return self

        def wait_for(self, state=None, timeout=None):
            raise RuntimeError("missing")

    class PlaceholderWrapper:
        first = placeholder_locator

    class FakeFrame:
        def locator(self, selector):
            return MissingLocator()

        def get_by_placeholder(self, text, exact=None):
            return PlaceholderWrapper()

        def get_by_label(self, text, exact=None):
            return MissingLocator()

    locator = payment_form_fields.resolve_locator_in_frames(
        [FakeFrame()],
        ["#missing"],
        placeholders=["全名"],
        labels=[],
        timeout_ms=200,
    )

    assert locator is placeholder_locator
    assert placeholder_locator.waits == [("visible", 180)]

def test_scroll_locator_into_view_returns_status():
    locator = FakeLocator()

    assert payment_form_fields.scroll_locator_into_view(locator, "账单地址") is True
    assert locator.scrolled == [2500]

def test_score_billing_frame_returns_frame_score():
    class FakeFrame:
        def __init__(self):
            self.scripts = []

        def evaluate(self, script):
            self.scripts.append(script)
            return 4

    frame = FakeFrame()

    assert payment_form_fields.score_billing_frame(frame) == 4
    assert "address line 1" in frame.scripts[0]

def test_score_billing_frame_returns_zero_on_evaluate_error():
    class FakeFrame:
        def evaluate(self, script):
            raise RuntimeError("closed")

    assert payment_form_fields.score_billing_frame(FakeFrame()) == 0

def test_find_billing_form_frames_returns_high_score_frame(monkeypatch):
    class FakeFrame:
        url = "https://example.test/billing"

    frame = FakeFrame()
    monkeypatch.setattr(payment_form_fields, "score_billing_frame", lambda candidate: 3)

    result = payment_form_fields.find_billing_form_frames(
        lambda: [frame],
        timeout_seconds=1,
        safe_url_summary=lambda value: f"safe:{value}",
        sleep=lambda seconds: None,
    )

    assert result == [frame]

def test_find_billing_form_frames_uses_best_low_score_after_timeout(monkeypatch):
    class FakeFrame:
        url = "https://example.test/low-score"

    frame = FakeFrame()
    calls = []

    monkeypatch.setattr(payment_form_fields, "score_billing_frame", lambda candidate: 2)
    monkeypatch.setattr(payment_form_fields.time, "time", lambda: calls.pop(0))
    calls.extend([0, 0, 2])

    result = payment_form_fields.find_billing_form_frames(
        lambda: [frame],
        timeout_seconds=1,
        sleep=lambda seconds: None,
    )

    assert result == [frame]

def test_find_billing_form_frames_returns_none_without_score(monkeypatch):
    class FakeFrame:
        url = "https://example.test/no-score"

    calls = []

    monkeypatch.setattr(payment_form_fields, "score_billing_frame", lambda candidate: 0)
    monkeypatch.setattr(payment_form_fields.time, "time", lambda: calls.pop(0))
    calls.extend([0, 0, 2])

    result = payment_form_fields.find_billing_form_frames(
        lambda: [FakeFrame()],
        timeout_seconds=1,
        sleep=lambda seconds: None,
    )

    assert result is None

def test_scroll_to_billing_section_uses_visible_locator_first():
    locator = FakeLocator()
    visible_calls = []

    class FakePage:
        def evaluate(self, script):
            raise AssertionError("DOM fallback should not run")

    result = payment_form_fields.scroll_to_billing_section(
        FakePage(),
        visible_locator=lambda selectors, timeout_ms: visible_calls.append((selectors, timeout_ms)) or locator,
    )

    assert result is True
    assert visible_calls == [
        (
            ["text=账单地址", "text=Billing address", "text=Billing Address"],
            2000,
        )
    ]
    assert locator.scrolled == [2000]

def test_scroll_to_billing_section_falls_back_to_dom_evaluate():
    class FailingLocator:
        def scroll_into_view_if_needed(self, timeout=None):
            raise RuntimeError("detached")

    class FakePage:
        def __init__(self):
            self.scripts = []

        def evaluate(self, script):
            self.scripts.append(script)

    page = FakePage()

    result = payment_form_fields.scroll_to_billing_section(
        page,
        visible_locator=lambda selectors, timeout_ms: FailingLocator(),
    )

    assert result is True
    assert "billing address" in page.scripts[0]

def test_scroll_to_billing_section_returns_false_when_all_paths_fail():
    class FakePage:
        def evaluate(self, script):
            raise RuntimeError("closed")

    assert (
        payment_form_fields.scroll_to_billing_section(
            FakePage(),
            visible_locator=lambda selectors, timeout_ms: None,
        )
        is False
    )

def test_billing_stability_checks_builds_expected_final_fields():
    checks = payment_form_fields.billing_stability_checks(
        {"name": "A", "address1": "B", "city": "C", "state": "D", "zip": "E"}
    )

    assert checks == [
        ("name", "账单姓名", "A", "gopay-billing-name-final-failed"),
        ("address1", "账单地址1", "B", "gopay-billing-address1-final-failed"),
        ("city", "账单城市", "C", "gopay-billing-city-final-failed"),
        ("state", "账单州/省", "D", "gopay-billing-state-final-failed"),
        ("zip", "账单邮编", "E", "gopay-billing-zip-final-failed"),
    ]

def test_verify_billing_fields_stable_reports_verified_fields():
    events = []
    suppressed = []
    dismissed = []
    screenshots = []
    locators = {
        "address1": FakeLocator(input_value="123 Main"),
        "name": FakeLocator(input_value="Alice"),
    }

    ok, error = payment_form_fields.verify_billing_fields_stable(
        locators,
        {"name": "Alice", "address1": "123 Main"},
        suppress_address_autocomplete_ui=lambda: suppressed.append(True),
        dismiss_address_autocomplete=lambda locator: dismissed.append(locator),
        capture_screenshot=lambda stage: screenshots.append(stage),
        progress=lambda stage, **extra: events.append((stage, extra)),
        sleep=lambda seconds: None,
    )

    assert (ok, error) == (True, "")
    assert suppressed == [True]
    assert dismissed == [locators["address1"]]
    assert screenshots == []
    assert events == [
        ("billing_field_verified", {"field": "账单姓名"}),
        ("billing_field_verified", {"field": "账单地址1"}),
    ]

def test_verify_billing_fields_stable_fails_when_locator_missing():
    screenshots = []

    ok, error = payment_form_fields.verify_billing_fields_stable(
        {},
        {"name": "Alice"},
        suppress_address_autocomplete_ui=lambda: None,
        dismiss_address_autocomplete=lambda locator: None,
        capture_screenshot=lambda stage: screenshots.append(stage),
        sleep=lambda seconds: None,
    )

    assert ok is False
    assert error == "提交前校验失败，缺少 账单姓名 定位器"
    assert screenshots == ["gopay-billing-name-final-failed"]

def test_verify_billing_fields_stable_rewrites_changed_field():
    dismissed = []
    locator = FakeLocator(input_value="Old")
    address_locator = FakeLocator(input_value="123 Main")

    ok, error = payment_form_fields.verify_billing_fields_stable(
        {"name": locator, "address1": address_locator},
        {"name": "Alice"},
        suppress_address_autocomplete_ui=lambda: None,
        dismiss_address_autocomplete=lambda locator: dismissed.append(locator),
        capture_screenshot=lambda stage: None,
        sleep=lambda seconds: None,
    )

    assert (ok, error) == (True, "")
    assert locator.filled == [("Alice", 2500)]
    assert dismissed == [address_locator, address_locator]

def test_verify_billing_fields_stable_fails_when_rewrite_does_not_stick():
    class StubbornLocator(FakeLocator):
        def fill(self, value, timeout=None):
            self.filled.append((value, timeout))

    screenshots = []
    locator = StubbornLocator(input_value="Old")

    ok, error = payment_form_fields.verify_billing_fields_stable(
        {"name": locator},
        {"name": "Alice"},
        suppress_address_autocomplete_ui=lambda: None,
        dismiss_address_autocomplete=lambda locator: None,
        capture_screenshot=lambda stage: screenshots.append(stage),
        sleep=lambda seconds: None,
    )

    assert ok is False
    assert error == "提交前校验失败 账单姓名: 期望='Alice', 实际='Old'"
    assert screenshots == ["gopay-billing-name-final-failed"]

def test_fill_billing_page_field_returns_optional_missing_success():
    ok, error, locator = payment_form_fields.fill_billing_page_field(
        selectors=["#missing"],
        value="",
        label="账单地址2",
        optional=True,
        resolve_locator=lambda *args, **kwargs: None,
    )

    assert (ok, error, locator) == (True, "", None)

def test_fill_billing_page_field_blocks_phone_like_zip():
    ok, error, locator = payment_form_fields.fill_billing_page_field(
        selectors=["#zip"],
        value="+6287761973970",
        label="账单邮编",
        resolve_locator=lambda *args, **kwargs: FakeLocator(),
        looks_like_phone_number=lambda value: True,
    )

    assert ok is False
    assert "疑似手机号" in error
    assert locator is None

def test_fill_billing_page_field_skips_when_current_value_matches():
    locator = FakeLocator(input_value="Alice")
    progress_events = []

    ok, error, returned = payment_form_fields.fill_billing_page_field(
        selectors=["#name"],
        value="Alice",
        label="账单姓名",
        resolve_locator=lambda *args, **kwargs: locator,
        progress=lambda stage, **extra: progress_events.append((stage, extra)),
    )

    assert (ok, error, returned) == (True, "", locator)
    assert locator.filled == []
    assert progress_events == []

def test_fill_billing_page_field_rewrites_after_readback_mismatch():
    class StaleFillLocator(FakeLocator):
        def fill(self, value, timeout=None):
            self.filled.append((value, timeout))

    locator = StaleFillLocator(input_value="")
    progress_events = []
    screenshots = []

    def read_value(_locator):
        return _locator.input_value_value

    def set_value(_locator, value):
        _locator.input_value_value = value
        return True

    ok, error, returned = payment_form_fields.fill_billing_page_field(
        selectors=["#name"],
        value="Alice",
        label="账单姓名",
        resolve_locator=lambda *args, **kwargs: locator,
        capture_screenshot=lambda stage: screenshots.append(stage),
        progress=lambda stage, **extra: progress_events.append((stage, extra)),
        read_value=read_value,
        matches=lambda expected, actual: expected == actual,
        set_value=set_value,
        sleep=lambda seconds: None,
    )

    assert (ok, error, returned) == (True, "", locator)
    assert locator.filled == [("Alice", 4000)]
    assert progress_events == [("billing_fill_field", {"field": "账单姓名"})]
    assert screenshots == []

def test_fill_billing_page_field_reports_required_missing_with_screenshot():
    screenshots = []

    ok, error, locator = payment_form_fields.fill_billing_page_field(
        selectors=["#missing"],
        value="Alice",
        label="账单姓名",
        screenshot_stage="missing-name",
        resolve_locator=lambda *args, **kwargs: None,
        capture_screenshot=lambda stage: screenshots.append(stage),
    )

    assert (ok, error, locator) == (False, "未找到 账单姓名", None)
    assert screenshots == ["missing-name"]

def test_select_billing_page_field_uses_value_option_first():
    locator = FakeLocator(tag="SELECT", fail_select=False, input_value="US")
    progress_events = []

    ok, error, returned = payment_form_fields.select_billing_page_field(
        selectors=["#country"],
        value="US",
        label="账单国家",
        resolve_locator=lambda *args, **kwargs: locator,
        keyboard=object(),
        progress=lambda stage, **extra: progress_events.append((stage, extra)),
    )

    assert (ok, error, returned) == (True, "", locator)
    assert locator.select_calls == [{"value": "US", "label": None, "timeout": 4000}]
    assert progress_events == [("billing_select_field", {"field": "账单国家"})]

def test_select_billing_page_field_falls_back_to_keyboard():
    class Keyboard:
        def __init__(self):
            self.typed = []
            self.pressed = []

        def type(self, value, delay=None):
            self.typed.append((value, delay))

        def press(self, key):
            self.pressed.append(key)

    locator = FakeLocator(tag="INPUT", fail_select=True)
    keyboard = Keyboard()

    ok, error, returned = payment_form_fields.select_billing_page_field(
        selectors=["#state"],
        value="CA",
        label="账单州/省",
        resolve_locator=lambda *args, **kwargs: locator,
        keyboard=keyboard,
    )

    assert (ok, error, returned) == (True, "", locator)
    assert locator.clicked is True
    assert keyboard.typed == [("CA", 30)]
    assert keyboard.pressed == ["Enter"]
