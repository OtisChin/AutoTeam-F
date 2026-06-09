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


def test_paypal_card_brand_allowed_accepts_supported_brands_only():
    assert payment_form_fields.paypal_card_brand_allowed("4111 1111 1111 1111") is True
    assert payment_form_fields.paypal_card_brand_allowed("5555 5555 5555 4444") is True
    assert payment_form_fields.paypal_card_brand_allowed("2221 0000 0000 0009") is True
    assert payment_form_fields.paypal_card_brand_allowed("3782 822463 10005") is True
    assert payment_form_fields.paypal_card_brand_allowed("6011 1111 1111 1117") is False
    assert payment_form_fields.paypal_card_brand_allowed("4111") is False


def test_paypal_card_generation_helpers_allow_deterministic_random_sources():
    def choose_first(options):
        return options[0]

    generated = payment_form_fields.generate_paypal_card_number(choose=choose_first)

    assert generated.startswith("4539")
    assert payment_form_fields.luhn_valid(generated) is True
    assert payment_form_fields.paypal_card_brand_allowed(generated) is True
    assert (
        payment_form_fields.normalize_or_generate_paypal_card_number(
            "3580264577581543",
            generate_card_number=lambda: generated,
        )
        == generated
    )
    assert (
        payment_form_fields.normalize_or_generate_paypal_card_number(
            "4111 1111 1111 1111",
            generate_card_number=lambda: generated,
        )
        == "4111111111111111"
    )
    assert payment_form_fields.generate_paypal_card_expiry(randbelow=lambda bound: 0) == "01 / 29"
    assert payment_form_fields.generate_paypal_card_cvv("4111111111111111", choose=choose_first) == "100"
    assert payment_form_fields.generate_paypal_card_cvv("378282246310005", choose=choose_first) == "1000"


def test_paypal_card_expiry_normalization_handles_four_and_six_digits():
    assert payment_form_fields.normalize_paypal_card_expiry("0328") == "03 / 28"
    assert payment_form_fields.normalize_paypal_card_expiry("03/2028") == "03 / 28"
    assert payment_form_fields.normalize_paypal_card_expiry("03 / 28") == "03 / 28"


def test_paypal_credential_helpers_trim_email_and_generate_deterministic_values():
    assert payment_form_fields.normalize_paypal_credentials(" user@example.com ", " Secret123! ") == {
        "email": "user@example.com",
        "password": " Secret123! ",
    }
    assert (
        payment_form_fields.generate_random_paypal_email(uuid_hex="abcdef1234567890deadbeef")
        == "ppabcdef1234567890@gmail.com"
    )

    choices = iter(["a", "A", "1", "!", *("x" for _ in range(10))])
    password = payment_form_fields.generate_random_paypal_password(
        choose=lambda options: next(choices),
        shuffle=lambda chars: None,
    )

    assert password == "aA1!xxxxxxxxxx"
    assert len(password) == 14
    assert any(char.islower() for char in password)
    assert any(char.isupper() for char in password)
    assert any(char.isdigit() for char in password)
    assert any(char in "!@#$%^" for char in password)


def test_paypal_name_and_phone_normalization_helpers():
    assert payment_form_fields.split_paypal_name("Jane Q Public") == ("Jane", "Q Public")
    assert payment_form_fields.split_paypal_name("Jane") == ("Jane", "Smith")
    assert payment_form_fields.split_paypal_name("") == ("James", "Smith")
    assert payment_form_fields.normalize_paypal_phone("+81 70-9487-0367") == "07094870367"
    assert payment_form_fields.normalize_paypal_phone("0081 70 9487 0367") == "07094870367"
    assert payment_form_fields.normalize_paypal_phone("1 (310) 555-0100") == "3105550100"
    assert payment_form_fields.normalize_paypal_phone("070-9487-0367") == "07094870367"


def test_paypal_phone_value_valid_uses_country_specific_rules():
    def normalize_country(value):
        return str(value or "").strip().upper()

    def normalize_phone(value):
        return payment_form_fields.normalize_paypal_phone(value)

    assert (
        payment_form_fields.paypal_phone_value_valid(
            "+81 90-2664-7330",
            country="JP",
            normalize_country=normalize_country,
            normalize_phone=normalize_phone,
        )
        is True
    )
    assert (
        payment_form_fields.paypal_phone_value_valid(
            "+81",
            country="JP",
            normalize_country=normalize_country,
            normalize_phone=normalize_phone,
        )
        is False
    )
    assert (
        payment_form_fields.paypal_phone_value_valid(
            "1 (310) 555-0100",
            country="US",
            normalize_country=normalize_country,
            normalize_phone=normalize_phone,
        )
        is True
    )
    assert (
        payment_form_fields.paypal_phone_value_valid(
            "123456",
            country="",
            normalize_country=normalize_country,
            normalize_phone=normalize_phone,
        )
        is False
    )


def test_payload_value_and_address_line_helpers():
    assert payment_form_fields.first_payload_value({"a": "", "b": "  value  "}, "a", "b") == "value"
    assert payment_form_fields.first_payload_value({"a": ""}, "a", "missing") == ""
    assert payment_form_fields.split_paypal_address_lines("500 Pine St Apt 2") == ("500 Pine St", "Apt 2")
    assert payment_form_fields.split_paypal_address_lines("500 Pine St") == ("500 Pine St", "")
    assert payment_form_fields.split_paypal_address_lines("") == ("", "")


def test_paypal_generator_field_helpers_flatten_and_match_aliases():
    address = {
        "Payment": {
            "Credit Card Number": " 4111111111111111 ",
            "Details": [{"CVV2": "123"}],
            "Empty": "",
        },
        "Meta": {"Expires": "04/2028"},
    }

    assert payment_form_fields.flatten_paypal_generator_fields(address) == {
        "Payment_Credit Card Number": "4111111111111111",
        "Payment_Details_0_CVV2": "123",
        "Payment_Empty": "",
        "Meta_Expires": "04/2028",
    }
    assert payment_form_fields.paypal_generator_field(address, "Credit_Card_Number") == "4111111111111111"
    assert payment_form_fields.paypal_generator_field(address, "CVV2") == "123"
    assert payment_form_fields.paypal_generator_field(address, "Expires") == "04/2028"
    assert payment_form_fields.paypal_generator_field(address, "Missing", "Empty") == ""


def test_merge_paypal_checkout_billing_payload_combines_generated_profile_and_card_fields():
    merged = payment_form_fields.merge_paypal_checkout_billing_payload(
        {"email": " user@example.com ", "phone": ""},
        {
            "name": " Card Source ",
            "state": "CA",
            "city": "Los Angeles",
            "zip": "90001",
            "address1": "742 Evergreen Terrace",
            "address2": "Apt 2",
            "phone_number": "3105550100",
            "cardNumber": "4111 1111 1111 1111",
            "cardExpiry": "03/2030",
            "cvv": " 9 9 6 ",
            "private_note": "ignored",
        },
        requested_country="US",
        default_name="James Smith",
        normalize_or_generate_card_number=lambda value: payment_form_fields.normalize_or_generate_paypal_card_number(
            value,
            generate_card_number=lambda: "4539000000000006",
        ),
        generate_card_expiry=lambda: "01 / 29",
        generate_card_cvv=lambda card_number: "123",
    )

    assert merged == {
        "name": "Card Source",
        "email": "user@example.com",
        "phone": "3105550100",
        "country": "US",
        "state": "CA",
        "city": "Los Angeles",
        "zip": "90001",
        "address1": "742 Evergreen Terrace",
        "address2": "Apt 2",
        "card_number": "4111111111111111",
        "card_expiry": "03/2030",
        "card_cvv": "996",
    }


def test_merge_paypal_checkout_billing_payload_uses_defaults_and_generated_card_fallbacks():
    merged = payment_form_fields.merge_paypal_checkout_billing_payload(
        {"email": "user@example.com", "phone": "+819012345678"},
        {"name": "", "state": "Tokyo", "city": "Chiyoda", "zip": "100-0001", "address1": "1-1 Chiyoda"},
        requested_country="JP",
        default_name="James Smith",
        normalize_or_generate_card_number=lambda value: "4539000000000006",
        generate_card_expiry=lambda: "01 / 29",
        generate_card_cvv=lambda card_number: "123",
    )

    assert merged["name"] == "James Smith"
    assert merged["phone"] == "+819012345678"
    assert merged["country"] == "JP"
    assert merged["card_number"] == "4539000000000006"
    assert merged["card_expiry"] == "01 / 29"
    assert merged["card_cvv"] == "123"


def test_paypal_phone_account_normalization_accepts_aliases_and_channel_fallbacks():
    assert payment_form_fields.normalize_paypal_phone_account(
        {"phoneNumber": "+18352880840", "smsUrl": "https://sms.example/one"},
        fallback_otp_channel="whatsapp",
    ) == {
        "phone": "+18352880840",
        "sms_url": "https://sms.example/one",
        "otp_channel": "whatsapp",
    }
    assert payment_form_fields.normalize_paypal_phone_account(
        {"billing_phone": "+18352623053", "sms_url": "https://sms.example/two", "otp_channel": "voice"}
    ) == {
        "phone": "+18352623053",
        "sms_url": "https://sms.example/two",
        "otp_channel": "sms",
    }
    assert payment_form_fields.normalize_paypal_phone_account({"phone": "+1"}) == {}
    assert payment_form_fields.normalize_paypal_phone_account("not-a-dict") == {}


def test_sync_paypal_signup_phone_submission_state_initializes_key_set():
    state = {}

    result = payment_form_fields.sync_paypal_signup_phone_submission_state(
        {"phone": "+1 (310) 555-0100"},
        state,
        signup_submitted=False,
        normalize_phone=payment_form_fields.normalize_paypal_phone,
    )

    assert result == (False, "3105550100", set(), False)
    assert state == {"submitted_phone_keys": set()}


def test_sync_paypal_signup_phone_submission_state_marks_existing_phone_submitted():
    submitted = {"8352880840"}
    state = {"submitted_phone_keys": submitted}

    result = payment_form_fields.sync_paypal_signup_phone_submission_state(
        {"phone": "835-288-0840"},
        state,
        signup_submitted=False,
        normalize_phone=payment_form_fields.normalize_paypal_phone,
    )

    assert result == (True, "8352880840", submitted, True)
    assert state["signup_submitted"] is True


def test_paypal_signup_profiles_for_phone_pool_deduplicates_and_preserves_identity():
    base = {
        "email": "pp-demo@gmail.com",
        "password": "Secret123!",
        "phone": "3105550100",
        "country": "US",
        "sms_url": "https://sms.example/base",
        "otp_channel": "sms",
        "card_number": "4111111111111111",
    }

    profiles = payment_form_fields.paypal_signup_profiles_for_phone_pool(
        base,
        [
            {"phone_number": "+18352880840", "sms_url": "https://sms.example/one"},
            {"phone_number": "+18352880840", "sms_url": "https://sms.example/one"},
            {"phone_number": "+18352623053", "sms_url": "https://sms.example/two", "otp_channel": "whatsapp"},
        ],
        normalize_phone=payment_form_fields.normalize_paypal_phone,
        phone_value_valid=lambda phone, *, country="": len(payment_form_fields.normalize_paypal_phone(phone)) == 10,
    )

    assert [profile["phone"] for profile in profiles] == ["8352880840", "8352623053"]
    assert [profile["phone_pool_index"] for profile in profiles] == ["1", "2"]
    assert [profile["phone_pool_total"] for profile in profiles] == ["2", "2"]
    assert [profile["otp_channel"] for profile in profiles] == ["sms", "whatsapp"]
    assert all(profile["email"] == "pp-demo@gmail.com" for profile in profiles)
    assert all(profile["card_number"] == "4111111111111111" for profile in profiles)


def test_paypal_signup_profiles_for_phone_pool_rejects_invalid_base_fallback_phone():
    base = {
        "email": "pp-demo@gmail.com",
        "phone": "+81",
        "country": "JP",
        "sms_url": "https://sms.example/base",
    }

    assert (
        payment_form_fields.paypal_signup_profiles_for_phone_pool(
            base,
            [],
            normalize_phone=payment_form_fields.normalize_paypal_phone,
            phone_value_valid=lambda phone, *, country="": False,
        )
        == []
    )


def test_build_paypal_checkout_billing_payload_maps_normalized_fields_and_optional_card_fields():
    payload = payment_form_fields.build_paypal_checkout_billing_payload(
        {
            "name": " Jane Example ",
            "email": " jane@example.com ",
            "phone": " 3105550100 ",
            "country": "",
            "state": " CA ",
            "city": " Los Angeles ",
            "postal_code": " 90001 ",
            "address1": " 742 Evergreen Terrace ",
            "address2": " Apt 2 ",
            "card_number": " 4111 1111 1111 1111 ",
            "card_expiry": "",
            "card_cvv": " 123 ",
        }
    )

    assert payload == {
        "name": "Jane Example",
        "email": "jane@example.com",
        "phone": "3105550100",
        "country": "US",
        "state": "CA",
        "city": "Los Angeles",
        "zip": "90001",
        "address1": "742 Evergreen Terrace",
        "address2": "Apt 2",
        "card_number": "4111 1111 1111 1111",
        "card_cvv": "123",
    }


def test_paypal_billing_payload_complete_requires_core_address_fields():
    complete = {
        "name": "Jane Example",
        "country": "US",
        "state": "CA",
        "city": "Los Angeles",
        "zip": "90001",
        "address1": "742 Evergreen Terrace",
    }

    assert payment_form_fields.paypal_billing_payload_complete(complete) is True
    assert payment_form_fields.paypal_billing_payload_complete({**complete, "zip": ""}) is False
    assert payment_form_fields.paypal_billing_payload_complete({**complete, "address2": ""}) is True


def test_build_paypal_signup_profile_generates_missing_credentials_and_normalizes_card_fields():
    profile = payment_form_fields.build_paypal_signup_profile(
        billing_payload={
            "name": "James Smith",
            "phone": "+1 (310) 555-0100",
            "country": "US",
            "state": "CA",
            "city": "Los Angeles",
            "zip": "90001",
            "address1": "742 Evergreen Terrace",
            "address2": "Apt 2",
            "cardNumber": "4000-0000-0000-3220",
            "cardExpiry": "04/2031",
            "cvc": " 1 2 3 ",
        },
        sms_url=" https://sms.example.test/token=demo ",
        otp_channel="WHATSAPP",
        country_billing_profiles={},
        normalize_country=lambda value: str(value or "").strip().upper(),
        generate_email=lambda: "generated@example.com",
        generate_password=lambda: "Generated123!",
        normalize_or_generate_card_number=lambda value: payment_form_fields.normalize_or_generate_paypal_card_number(
            value,
            generate_card_number=lambda: "4539000000000006",
        ),
        generate_card_expiry=lambda: "01 / 29",
        generate_card_cvv=lambda card_number: "987",
    )

    assert profile["email"] == "generated@example.com"
    assert profile["password"] == "Generated123!"
    assert profile["generated_email"] is True
    assert profile["generated_password"] is True
    assert profile["phone"] == "3105550100"
    assert profile["first_name"] == "James"
    assert profile["last_name"] == "Smith"
    assert profile["card_number"] == "4000000000003220"
    assert profile["card_expiry"] == "04 / 31"
    assert profile["card_cvv"] == "123"
    assert profile["sms_url"] == "https://sms.example.test/token=demo"
    assert profile["otp_channel"] == "whatsapp"


def test_build_paypal_signup_profile_applies_forced_country_defaults_and_preserves_native_names():
    profile = payment_form_fields.build_paypal_signup_profile(
        paypal_email=" user@example.com ",
        paypal_password=" Secret123! ",
        billing_payload={
            "name": "",
            "firstName": "タロウ",
            "lastName": "ヤマダ",
            "nativeFirstName": "太郎",
            "nativeLastName": "山田",
            "phone": "+81 70 9487 0367",
            "country": "US",
            "state": "",
            "city": "",
            "zip": "",
            "address1": "",
            "birthDate": "1985/01/15",
        },
        paypal_country="jp",
        country_billing_profiles={
            "JP": {
                "name": "James Smith",
                "state": "Tokyo",
                "city": "Chiyoda",
                "zip": "100-0001",
                "address1": "1-1 Chiyoda",
                "address2": "",
            }
        },
        normalize_country=lambda value: str(value or "").strip().upper(),
        generate_email=lambda: "generated@example.com",
        generate_password=lambda: "Generated123!",
        normalize_or_generate_card_number=lambda value: "4539000000000006",
        generate_card_expiry=lambda: "01 / 29",
        generate_card_cvv=lambda card_number: "987",
    )

    assert profile["email"] == "user@example.com"
    assert profile["password"] == "Secret123!"
    assert profile["generated_email"] is False
    assert profile["generated_password"] is False
    assert profile["country"] == "JP"
    assert profile["state"] == "Tokyo"
    assert profile["city"] == "Chiyoda"
    assert profile["zip"] == "100-0001"
    assert profile["address1"] == "1-1 Chiyoda"
    assert profile["first_name"] == "タロウ"
    assert profile["last_name"] == "ヤマダ"
    assert profile["native_first_name"] == "太郎"
    assert profile["native_last_name"] == "山田"
    assert profile["birth_date"] == "1985/01/15"
    assert profile["card_number"] == "4539000000000006"
    assert profile["card_expiry"] == "01 / 29"
    assert profile["card_cvv"] == "987"


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


def test_set_locator_value_prefers_select_option_for_paypal_mode():
    locator = FakeLocator(tag="SELECT", fail_select=False)

    assert payment_form_fields.set_locator_value(locator, "CA", prefer_select_option=True, fill_fallback=True) is True

    assert locator.select_calls == [{"value": "CA", "label": None, "timeout": 1000}]
    assert len(locator.evaluations) == 1


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


def test_fill_signup_required_fields_skips_optional_missing_email_locator():
    phone = FakeLocator(input_value="5551234567")
    calls = []

    ok, error, locators = payment_form_fields.fill_signup_required_fields(
        [
            ("email", ["#email"], "user@example.com", "PayPal 注册邮箱"),
            ("phone", ["#phone"], "5551234567", "PayPal 注册手机号"),
        ],
        visible_locator=lambda selectors, timeout_ms: None if selectors == ["#email"] else phone,
        set_verified_value=lambda locator, value, field="": calls.append((field, value)) or True,
        read_value=lambda locator: locator.input_value(),
        optional_skip_fields={"email"},
    )

    assert (ok, error) == (True, "")
    assert locators == {"PayPal 注册手机号": phone}
    assert calls == [("phone", "5551234567")]


def test_fill_signup_required_fields_rejects_empty_required_value():
    ok, error, locators = payment_form_fields.fill_signup_required_fields(
        [("phone", ["#phone"], "", "PayPal 注册手机号")],
        visible_locator=lambda _selectors, timeout_ms: FakeLocator(),
        set_verified_value=lambda _locator, _value, field="": True,
        read_value=lambda locator: locator.input_value(),
    )

    assert (ok, error) == (False, "PayPal 注册手机号 为空")
    assert locators == {}


def test_fill_signup_required_fields_rejects_missing_required_locator():
    ok, error, locators = payment_form_fields.fill_signup_required_fields(
        [("phone", ["#phone"], "5551234567", "PayPal 注册手机号")],
        visible_locator=lambda _selectors, timeout_ms: None,
        set_verified_value=lambda _locator, _value, field="": True,
        read_value=lambda locator: locator.input_value(),
    )

    assert (ok, error) == (False, "未找到 PayPal 注册手机号 输入框")
    assert locators == {}


def test_fill_signup_required_fields_reports_readback_mismatch():
    locator = FakeLocator(input_value="wrong")

    ok, error, locators = payment_form_fields.fill_signup_required_fields(
        [("phone", ["#phone"], "5551234567", "PayPal 注册手机号")],
        visible_locator=lambda _selectors, timeout_ms: locator,
        set_verified_value=lambda _locator, _value, field="": False,
        read_value=lambda target: target.input_value(),
    )

    assert ok is False
    assert error == "PayPal 注册手机号 填写后校验失败: 期望='5551234567', 实际='wrong'"
    assert locators == {}


def test_fill_signup_address_fields_sets_state_and_dismisses_address_autocomplete():
    address = FakeLocator(input_value="11 Main St")
    city = FakeLocator(input_value="New York")
    zip_code = FakeLocator(input_value="10001")
    state = FakeLocator(input_value="NY")
    locators_by_selector = {
        "#address": address,
        "#city": city,
        "#zip": zip_code,
        "#state": state,
    }
    suppress_calls = []
    dismiss_calls = []
    state_calls = []

    ok, error, locators = payment_form_fields.fill_signup_address_fields(
        [
            ("address1", ["#address"], "11 Main St", "PayPal 账单地址"),
            ("city", ["#city"], "New York", "PayPal 城市"),
            ("zip", ["#zip"], "10001", "PayPal 邮编"),
            ("state", ["#state"], "NY", "PayPal 州"),
        ],
        country="US",
        suppress_autocomplete=lambda: suppress_calls.append(True),
        dismiss_autocomplete=lambda locator=None: dismiss_calls.append(locator),
        visible_locator=lambda selectors, timeout_ms: locators_by_selector.get(selectors[0]),
        set_verified_value=lambda locator, value, field="": setattr(locator, "input_value_value", value) is None,
        set_state_value=lambda locator, value, country="": (
            state_calls.append((value, country)) or setattr(locator, "input_value_value", value) is None
        ),
        read_value=lambda locator: locator.input_value(),
        field_value_matches=lambda expected, actual, field="": expected == actual,
        set_value=lambda locator, value: setattr(locator, "input_value_value", value) is None,
        sleep=lambda _seconds: None,
    )

    assert (ok, error) == (True, "")
    assert locators["address1"] is address
    assert locators["state"] is state
    assert suppress_calls == [True]
    assert dismiss_calls == [address, address]
    assert state_calls == [("NY", "US")]


def test_fill_signup_address_fields_rewrites_autocomplete_mutated_value():
    address = FakeLocator(input_value="11 Main St")
    city = FakeLocator(input_value="New York")
    zip_code = FakeLocator(input_value="10001")
    state = FakeLocator(input_value="NY")
    locators_by_selector = {
        "#address": address,
        "#city": city,
        "#zip": zip_code,
        "#state": state,
    }
    address_reads = iter(["autocomplete rewrite", "11 Main St"])
    rewrites = []

    def read_value(locator):
        if locator is address:
            return next(address_reads)
        return locator.input_value()

    ok, error, _locators = payment_form_fields.fill_signup_address_fields(
        [
            ("address1", ["#address"], "11 Main St", "PayPal 账单地址"),
            ("city", ["#city"], "New York", "PayPal 城市"),
            ("zip", ["#zip"], "10001", "PayPal 邮编"),
            ("state", ["#state"], "NY", "PayPal 州"),
        ],
        country="US",
        suppress_autocomplete=lambda: None,
        dismiss_autocomplete=lambda locator=None: None,
        visible_locator=lambda selectors, timeout_ms: locators_by_selector.get(selectors[0]),
        set_verified_value=lambda locator, value, field="": True,
        set_state_value=lambda locator, value, country="": True,
        read_value=read_value,
        field_value_matches=lambda expected, actual, field="": expected == actual,
        set_value=lambda locator, value: rewrites.append((locator, value)) or True,
        sleep=lambda _seconds: None,
    )

    assert (ok, error) == (True, "")
    assert rewrites == [(address, "11 Main St")]


def test_fill_signup_address_fields_reports_rewrite_failure_after_autocomplete_mutation():
    address = FakeLocator(input_value="rewritten")

    ok, error, _locators = payment_form_fields.fill_signup_address_fields(
        [("address1", ["#address"], "11 Main St", "PayPal 账单地址")],
        country="US",
        suppress_autocomplete=lambda: None,
        dismiss_autocomplete=lambda locator=None: None,
        visible_locator=lambda _selectors, timeout_ms: address,
        set_verified_value=lambda _locator, _value, field="": True,
        set_state_value=lambda _locator, _value, country="": True,
        read_value=lambda locator: locator.input_value(),
        field_value_matches=lambda expected, actual, field="": expected == actual,
        set_value=lambda _locator, _value: False,
        sleep=lambda _seconds: None,
    )

    assert (ok, error) == (False, "PayPal 账单地址 自动补全后被改写，且重写失败")


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


def test_fill_signup_birth_date_if_needed_rejects_readback_digit_mismatch():
    locator = FakeLocator(input_value="1985/01/16")

    result = payment_form_fields.fill_signup_birth_date_if_needed(
        {"birth_date": "1985/01/15"},
        country="JP",
        default_birth_date="1980/01/01",
        birth_date_selectors=["#birth"],
        normalize_country=lambda country: country,
        visible_locator=lambda _selectors, timeout_ms: locator,
        set_value=lambda _locator, _value: None,
        read_value=lambda target: target.input_value(),
        sleep=lambda _seconds: None,
    )

    assert result == (False, "PayPal 生年月日填写后校验失败: 期望='1985/01/15', 实际='1985/01/16'")


def test_validate_signup_dom_result_filters_optional_missing_fields():
    ok, error, still_missing = payment_form_fields.validate_signup_dom_result(
        {"stillMissing": ["email", "phone", ""]},
        country="US",
        optional_skip_fields={"email"},
        normalize_country=lambda country: country,
    )

    assert (ok, error) == (True, "")
    assert still_missing == ["phone"]


def test_validate_signup_dom_result_rejects_jp_required_missing_fields():
    ok, error, still_missing = payment_form_fields.validate_signup_dom_result(
        {"stillMissing": ["birth_date", "native_last_name", "phone"]},
        country="jp",
        optional_skip_fields=set(),
        normalize_country=lambda country: country.upper(),
    )

    assert ok is False
    assert error == "PayPal 日区注册字段填写后校验失败: birth_date, native_last_name"
    assert still_missing == ["birth_date", "native_last_name", "phone"]


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


def test_verify_signup_required_values_rejects_invalid_phone_before_locator_lookup():
    calls = []

    result = payment_form_fields.verify_signup_required_values(
        [("phone", ["#phone"], "+81", "PayPal 注册手机号")],
        country="JP",
        phone_value_valid=lambda value, country="": calls.append((value, country)) or False,
        visible_locator=lambda _selectors, timeout_ms: calls.append("visible"),
        read_value=lambda locator: locator.input_value(),
        field_value_matches=lambda expected, actual, field="": expected == actual,
    )

    assert result == (False, "PayPal 注册手机号 无效: '+81'")
    assert calls == [("+81", "JP")]


def test_verify_signup_required_values_rejects_missing_locator():
    result = payment_form_fields.verify_signup_required_values(
        [("card_number", ["#card"], "4111111111111111", "PayPal 卡号")],
        country="US",
        phone_value_valid=lambda value, country="": True,
        visible_locator=lambda _selectors, timeout_ms: None,
        read_value=lambda locator: locator.input_value(),
        field_value_matches=lambda expected, actual, field="": expected == actual,
    )

    assert result == (False, "提交前未找到 PayPal 卡号 输入框")


def test_verify_signup_required_values_rejects_readback_mismatch():
    locator = FakeLocator(input_value="4000000000000002")

    result = payment_form_fields.verify_signup_required_values(
        [("card_number", ["#card"], "4111111111111111", "PayPal 卡号")],
        country="US",
        phone_value_valid=lambda value, country="": True,
        visible_locator=lambda _selectors, timeout_ms: locator,
        read_value=lambda target: target.input_value(),
        field_value_matches=lambda expected, actual, field="": expected == actual,
    )

    assert result == (
        False,
        "提交前 PayPal 卡号 校验失败: 期望='4111111111111111', 实际='4000000000000002'",
    )


def test_verify_signup_required_values_accepts_all_matching_values():
    phone = FakeLocator(input_value="8352880971")
    state = FakeLocator(input_value="CA")
    locators = {"#phone": phone, "#state": state}

    result = payment_form_fields.verify_signup_required_values(
        [
            ("phone", ["#phone"], "8352880971", "PayPal 注册手机号"),
            ("state", ["#state"], "California", "PayPal 州/都道府县"),
        ],
        country="US",
        phone_value_valid=lambda value, country="": value == "8352880971" and country == "US",
        visible_locator=lambda selectors, timeout_ms: locators.get(selectors[0]),
        read_value=lambda target: target.input_value(),
        field_value_matches=lambda expected, actual, field="": field == "state" or expected == actual,
    )

    assert result == (True, "")


def test_verify_paypal_signup_required_values_builds_specs_and_accepts_matches():
    signup_profile = {
        "phone": "8352880971",
        "card_number": "4111111111111111",
        "card_expiry": "05 / 30",
        "card_cvv": "123",
        "password": "strong-password",
        "first_name": "Taro",
        "last_name": "Yamada",
        "address1": "11 Main St",
        "city": "Tokyo",
        "zip": "10001",
        "state": "Tokyo",
        "country": "JP",
    }
    selectors = {
        "phone_selectors": ["#phone"],
        "card_number_selectors": ["#card"],
        "card_expiry_selectors": ["#expiry"],
        "card_cvv_selectors": ["#cvv"],
        "password_selectors": ["#password"],
        "first_name_selectors": ["#first"],
        "last_name_selectors": ["#last"],
        "address1_selectors": ["#address"],
        "city_selectors": ["#city"],
        "postal_selectors": ["#postal"],
        "state_selectors": ["#state"],
    }
    locators = {
        "#phone": FakeLocator(input_value="8352880971"),
        "#card": FakeLocator(input_value="4111111111111111"),
        "#expiry": FakeLocator(input_value="05 / 30"),
        "#cvv": FakeLocator(input_value="123"),
        "#password": FakeLocator(input_value="strong-password"),
        "#first": FakeLocator(input_value="Taro"),
        "#last": FakeLocator(input_value="Yamada"),
        "#address": FakeLocator(input_value="11 Main St"),
        "#city": FakeLocator(input_value="Tokyo"),
        "#postal": FakeLocator(input_value="10001"),
        "#state": FakeLocator(input_value="Tokyo"),
    }
    visible_calls = []
    match_calls = []

    result = payment_form_fields.verify_paypal_signup_required_values(
        signup_profile,
        **selectors,
        phone_value_valid=lambda phone, country="": phone == "8352880971" and country == "JP",
        visible_locator=lambda selector_list, timeout_ms: (
            visible_calls.append((selector_list, timeout_ms)) or locators[selector_list[0]]
        ),
        read_value=lambda target: target.input_value(),
        field_value_matches=lambda expected, actual, field="": (
            match_calls.append((field, expected, actual)) or expected == actual
        ),
    )

    assert result == (True, "")
    assert visible_calls == [
        (["#phone"], 600),
        (["#card"], 600),
        (["#expiry"], 600),
        (["#cvv"], 600),
        (["#password"], 600),
        (["#first"], 600),
        (["#last"], 600),
        (["#address"], 600),
        (["#city"], 600),
        (["#postal"], 600),
        (["#state"], 600),
    ]
    assert [field for field, _expected, _actual in match_calls] == [
        "phone",
        "card_number",
        "card_expiry",
        "card_cvv",
        "password",
        "first_name",
        "last_name",
        "address1",
        "city",
        "zip",
        "state",
    ]


def test_verify_paypal_signup_required_values_reuses_base_validation_errors():
    selectors = {
        "phone_selectors": ["#phone"],
        "card_number_selectors": ["#card"],
        "card_expiry_selectors": ["#expiry"],
        "card_cvv_selectors": ["#cvv"],
        "password_selectors": ["#password"],
        "first_name_selectors": ["#first"],
        "last_name_selectors": ["#last"],
        "address1_selectors": ["#address"],
        "city_selectors": ["#city"],
        "postal_selectors": ["#postal"],
        "state_selectors": ["#state"],
    }
    invalid_phone = payment_form_fields.verify_paypal_signup_required_values(
        {"phone": "+81", "country": "JP"},
        **selectors,
        phone_value_valid=lambda _phone, country="": False,
        visible_locator=lambda _selectors, timeout_ms: (_ for _ in ()).throw(
            AssertionError("invalid phone should stop before locator lookup")
        ),
        read_value=lambda target: target.input_value(),
        field_value_matches=lambda expected, actual, field="": expected == actual,
    )
    missing_card = payment_form_fields.verify_paypal_signup_required_values(
        {
            "phone": "8352880971",
            "card_number": "4111111111111111",
            "country": "US",
        },
        **selectors,
        phone_value_valid=lambda _phone, country="": True,
        visible_locator=lambda selector_list, timeout_ms: (
            FakeLocator(input_value="8352880971") if selector_list == ["#phone"] else None
        ),
        read_value=lambda target: target.input_value(),
        field_value_matches=lambda expected, actual, field="": expected == actual,
    )

    assert invalid_phone == (False, "PayPal 注册手机号 无效: '+81'")
    assert missing_card == (False, "提交前未找到 PayPal 卡号 输入框")


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


def test_replace_signup_field_values_rejects_missing_field():
    result = payment_form_fields.replace_signup_field_values(
        [("card_number", ["#card"], "4111111111111111", "PayPal 卡号")],
        set_first_visible_value_with_locator=lambda _selectors, _value: (False, None),
        set_verified_value=lambda _locator, _value, field="": True,
        read_value=lambda locator: locator.input_value(),
    )

    assert result == (False, "未找到 PayPal 卡号 输入框")


def test_replace_signup_field_values_reports_verification_failure():
    locator = FakeLocator(input_value="4000000000000002")

    result = payment_form_fields.replace_signup_field_values(
        [("card_number", ["#card"], "4111111111111111", "PayPal 卡号")],
        set_first_visible_value_with_locator=lambda _selectors, _value: (True, locator),
        set_verified_value=lambda _locator, _value, field="": False,
        read_value=lambda target: target.input_value(),
    )

    assert result == (
        False,
        "PayPal 卡号 替换后校验失败: 期望='4111111111111111', 实际='4000000000000002'",
    )


def test_replace_signup_field_values_supports_custom_error_messages():
    locator = FakeLocator(input_value="old")

    missing = payment_form_fields.replace_signup_field_values(
        [("phone", ["#phone"], "8352880971", "PayPal 注册手机号")],
        set_first_visible_value_with_locator=lambda _selectors, _value: (False, None),
        set_verified_value=lambda _locator, _value, field="": True,
        read_value=lambda target: target.input_value(),
        missing_message=lambda label: f"未找到 {label}输入框",
        mismatch_message=lambda label, expected, actual: f"{label}替换后校验失败: 期望={expected!r}, 实际={actual!r}",
    )
    mismatch = payment_form_fields.replace_signup_field_values(
        [("phone", ["#phone"], "8352880971", "PayPal 注册手机号")],
        set_first_visible_value_with_locator=lambda _selectors, _value: (True, locator),
        set_verified_value=lambda _locator, _value, field="": False,
        read_value=lambda target: target.input_value(),
        missing_message=lambda label: f"未找到 {label}输入框",
        mismatch_message=lambda label, expected, actual: f"{label}替换后校验失败: 期望={expected!r}, 实际={actual!r}",
    )

    assert missing == (False, "未找到 PayPal 注册手机号输入框")
    assert mismatch == (False, "PayPal 注册手机号替换后校验失败: 期望='8352880971', 实际='old'")


def test_replace_signup_field_values_accepts_all_replaced_values():
    card = FakeLocator(input_value="4111111111111111")
    expiry = FakeLocator(input_value="05 / 30")
    locators = {"#card": card, "#expiry": expiry}
    replaced = []

    result = payment_form_fields.replace_signup_field_values(
        [
            ("card_number", ["#card"], "4111111111111111", "PayPal 卡号"),
            ("card_expiry", ["#expiry"], "05 / 30", "PayPal 卡有效期"),
        ],
        set_first_visible_value_with_locator=lambda selectors, value: (
            replaced.append((selectors[0], value)) or (True, locators[selectors[0]])
        ),
        set_verified_value=lambda _locator, _value, field="": True,
        read_value=lambda target: target.input_value(),
    )

    assert result == (True, "")
    assert replaced == [("#card", "4111111111111111"), ("#expiry", "05 / 30")]


def test_replace_paypal_signup_phone_validates_and_emits_progress():
    class FakePage:
        url = "https://www.paypal.com/checkoutweb/signup"

    class FakeApi:
        page = FakePage()

    locator = FakeLocator(input_value="8352880971")
    progress_events = []

    result = payment_form_fields.replace_paypal_signup_phone(
        FakeApi(),
        signup_profile={"phone": " 8352880971 ", "country": "US"},
        phone_selectors=["#phone"],
        phone_value_valid=lambda phone, country="": phone == "8352880971" and country == "US",
        set_first_visible_value_with_locator=lambda selectors, value: (
            selectors == ["#phone"] and value == "8352880971",
            locator,
        ),
        set_verified_value=lambda _locator, _value, field="": field == "phone",
        read_value=lambda target: target.input_value(),
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        on_progress=progress_events.append,
    )

    assert result == (True, "")
    assert progress_events == [
        {
            "stage": "paypal_replace_signup_phone",
            "url": "https://www.paypal.com/checkoutweb/signup",
            "phone": "8352880971",
        }
    ]


def test_replace_paypal_signup_phone_reports_invalid_and_replace_failures():
    class FakeApi:
        page = object()

    invalid = payment_form_fields.replace_paypal_signup_phone(
        FakeApi(),
        signup_profile={"phone": "+81", "country": "JP"},
        phone_selectors=["#phone"],
        phone_value_valid=lambda _phone, country="": False,
        set_first_visible_value_with_locator=lambda _selectors, _value: (True, object()),
        set_verified_value=lambda _locator, _value, field="": True,
        read_value=lambda _target: "",
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
    )
    missing = payment_form_fields.replace_paypal_signup_phone(
        FakeApi(),
        signup_profile={"phone": "8352880971"},
        phone_selectors=["#phone"],
        phone_value_valid=lambda _phone, country="": True,
        set_first_visible_value_with_locator=lambda _selectors, _value: (False, None),
        set_verified_value=lambda _locator, _value, field="": True,
        read_value=lambda _target: "",
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
    )
    locator = FakeLocator(input_value="old")
    mismatch = payment_form_fields.replace_paypal_signup_phone(
        FakeApi(),
        signup_profile={"phone": "8352880971"},
        phone_selectors=["#phone"],
        phone_value_valid=lambda _phone, country="": True,
        set_first_visible_value_with_locator=lambda _selectors, _value: (True, locator),
        set_verified_value=lambda _locator, _value, field="": False,
        read_value=lambda target: target.input_value(),
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
    )

    assert invalid == (False, "PayPal 注册手机号无效: '+81'")
    assert missing == (False, "未找到 PayPal 注册手机号输入框")
    assert mismatch == (False, "PayPal 注册手机号替换后校验失败: 期望='8352880971', 实际='old'")


def test_replace_paypal_signup_card_generates_updates_and_emits_progress():
    class FakePage:
        url = "https://www.paypal.com/checkoutweb/signup"

    class FakeApi:
        page = FakePage()

    signup_profile = {}
    progress_events = []
    replaced = []
    sleeps = []
    locators = {
        "#card": FakeLocator(input_value="4111111111111111"),
        "#expiry": FakeLocator(input_value="05 / 30"),
        "#cvv": FakeLocator(input_value="123"),
    }

    result = payment_form_fields.replace_paypal_signup_card(
        FakeApi(),
        signup_profile=signup_profile,
        card_number_selectors=["#card"],
        card_expiry_selectors=["#expiry"],
        card_cvv_selectors=["#cvv"],
        generate_card_number=lambda: "4111111111111111",
        generate_card_expiry=lambda: "05 / 30",
        generate_card_cvv=lambda card_number: "123" if card_number == "4111111111111111" else "",
        set_first_visible_value_with_locator=lambda selectors, value: (
            replaced.append((selectors[0], value)) or (True, locators[selectors[0]])
        ),
        set_verified_value=lambda _locator, _value, field="": field in {"card_number", "card_expiry", "card_cvv"},
        read_value=lambda target: target.input_value(),
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        on_progress=progress_events.append,
        sleep=sleeps.append,
    )

    assert result == (True, "")
    assert signup_profile == {
        "card_number": "4111111111111111",
        "card_expiry": "05 / 30",
        "card_cvv": "123",
    }
    assert replaced == [
        ("#card", "4111111111111111"),
        ("#expiry", "05 / 30"),
        ("#cvv", "123"),
    ]
    assert progress_events == [
        {
            "stage": "paypal_card_rejected_retry",
            "url": "https://www.paypal.com/checkoutweb/signup",
        }
    ]
    assert sleeps == [0.5]


def test_replace_paypal_signup_card_returns_replace_error_after_profile_update():
    class FakeApi:
        page = object()

    signup_profile = {}

    result = payment_form_fields.replace_paypal_signup_card(
        FakeApi(),
        signup_profile=signup_profile,
        card_number_selectors=["#card"],
        card_expiry_selectors=["#expiry"],
        card_cvv_selectors=["#cvv"],
        generate_card_number=lambda: "4111111111111111",
        generate_card_expiry=lambda: "05 / 30",
        generate_card_cvv=lambda _card_number: "123",
        set_first_visible_value_with_locator=lambda selectors, _value: (selectors != ["#expiry"], object()),
        set_verified_value=lambda _locator, _value, field="": True,
        read_value=lambda _target: "",
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep should not run on failure")),
    )

    assert result == (False, "未找到 PayPal 卡有效期 输入框")
    assert signup_profile == {
        "card_number": "4111111111111111",
        "card_expiry": "05 / 30",
        "card_cvv": "123",
    }


def test_retry_paypal_signup_after_card_rejected_resubmits_with_new_card():
    class FakeApi:
        pass

    signup_profile = {"phone": "8352880971", "card_number": "old"}
    state = {}
    calls = []
    progress_events = []
    sleeps = []

    def replace_signup_card(_api, *, signup_profile, on_progress=None):
        calls.append("replace")
        signup_profile["card_number"] = "4111111111111111"
        return True, ""

    result = payment_form_fields.retry_paypal_signup_after_card_rejected(
        FakeApi(),
        signup_profile=signup_profile,
        state=state,
        card_retry_count=0,
        current_url="https://www.paypal.com/checkoutweb/signup",
        replace_signup_card=replace_signup_card,
        ensure_phone_lock=lambda _state, *, signup_profile, on_progress=None: calls.append("lock") or (True, ""),
        release_phone_lock=lambda _state, on_progress=None: calls.append("release"),
        verify_required_values=lambda _api, _signup_profile: calls.append("verify") or (True, ""),
        click_submit=lambda _api: calls.append("submit") or True,
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        on_progress=progress_events.append,
        now=lambda: 1234.5,
        sleep=sleeps.append,
    )

    assert result == (True, "", True)
    assert calls == ["release", "replace", "lock", "verify", "submit"]
    assert signup_profile["card_number"] == "4111111111111111"
    assert progress_events == [
        {
            "stage": "paypal_submit_signup",
            "url": "https://www.paypal.com/checkoutweb/signup",
            "phone": "8352880971",
        }
    ]
    assert state == {
        "signup_submitted": True,
        "signup_submitted_at": 1234.5,
        "card_retry_count": 1,
    }
    assert sleeps == [2.0]


def test_retry_paypal_signup_after_card_rejected_stops_after_retry_limit():
    calls = []

    result = payment_form_fields.retry_paypal_signup_after_card_rejected(
        object(),
        signup_profile={"phone": "8352880971"},
        state={},
        card_retry_count=5,
        current_url="https://www.paypal.com/checkoutweb/signup",
        replace_signup_card=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("card replacement should not run")
        ),
        ensure_phone_lock=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("phone lock should not run")),
        release_phone_lock=lambda _state, on_progress=None: calls.append("release"),
        verify_required_values=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("verification should not run")
        ),
        click_submit=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("submit should not run")),
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep should not run")),
    )

    assert result == (False, "PayPal 连续拒绝卡片，已停止换卡重试", False)
    assert calls == ["release"]


def test_retry_paypal_signup_after_card_rejected_releases_lock_on_required_value_failure():
    calls = []

    result = payment_form_fields.retry_paypal_signup_after_card_rejected(
        object(),
        signup_profile={"phone": "8352880971"},
        state={},
        card_retry_count=2,
        current_url="https://www.paypal.com/checkoutweb/signup",
        replace_signup_card=lambda *_args, **_kwargs: calls.append("replace") or (True, ""),
        ensure_phone_lock=lambda *_args, **_kwargs: calls.append("lock") or (True, ""),
        release_phone_lock=lambda _state, on_progress=None: calls.append("release"),
        verify_required_values=lambda *_args, **_kwargs: calls.append("verify") or (False, "missing card"),
        click_submit=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("submit should not run")),
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep should not run")),
    )

    assert result == (False, "missing card", True)
    assert calls == ["release", "replace", "lock", "verify", "release"]


def test_retry_paypal_signup_after_phone_rejected_replaces_phone_and_resubmits():
    signup_profile = {"phone": "8352880971"}
    state = {"phone_only_retry": True}
    submitted_phone_keys = {"8352881474"}
    calls = []
    progress_events = []
    sleeps = []

    result = payment_form_fields.retry_paypal_signup_after_phone_rejected(
        object(),
        signup_profile=signup_profile,
        state=state,
        phone_key="8352880971",
        submitted_phone_keys=submitted_phone_keys,
        current_url="https://www.paypal.com/checkoutweb/signup",
        ensure_phone_lock=lambda _state, *, signup_profile, on_progress=None: calls.append("lock") or (True, ""),
        replace_signup_phone=lambda _api, *, signup_profile, on_progress=None: calls.append("replace") or (True, ""),
        release_phone_lock=lambda _state, on_progress=None: calls.append("release"),
        verify_required_values=lambda _api, _signup_profile: calls.append("verify") or (True, ""),
        click_submit=lambda _api: calls.append("submit") or True,
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        on_progress=progress_events.append,
        now=lambda: 2345.5,
        sleep=sleeps.append,
    )

    assert result == (True, "", True)
    assert calls == ["lock", "replace", "verify", "submit"]
    assert progress_events == [
        {
            "stage": "paypal_submit_signup",
            "url": "https://www.paypal.com/checkoutweb/signup",
            "phone": "8352880971",
        }
    ]
    assert state == {
        "phone_only_retry": False,
        "signup_submitted": True,
        "signup_submitted_at": 2345.5,
    }
    assert submitted_phone_keys == {"8352881474", "8352880971"}
    assert sleeps == [2.0]


def test_retry_paypal_signup_after_phone_rejected_returns_lock_failure_without_release():
    calls = []

    result = payment_form_fields.retry_paypal_signup_after_phone_rejected(
        object(),
        signup_profile={"phone": "8352880971"},
        state={},
        phone_key="8352880971",
        submitted_phone_keys=set(),
        current_url="https://www.paypal.com/checkoutweb/signup",
        ensure_phone_lock=lambda *_args, **_kwargs: calls.append("lock") or (False, "phone unavailable"),
        replace_signup_phone=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("replace should not run")),
        release_phone_lock=lambda *_args, **_kwargs: calls.append("release"),
        verify_required_values=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("verify should not run")),
        click_submit=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("submit should not run")),
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep should not run")),
    )

    assert result == (False, "phone unavailable", False)
    assert calls == ["lock"]


def test_retry_paypal_signup_after_phone_rejected_releases_lock_on_replace_failure():
    calls = []

    result = payment_form_fields.retry_paypal_signup_after_phone_rejected(
        object(),
        signup_profile={"phone": "8352880971"},
        state={},
        phone_key="8352880971",
        submitted_phone_keys=set(),
        current_url="https://www.paypal.com/checkoutweb/signup",
        ensure_phone_lock=lambda *_args, **_kwargs: calls.append("lock") or (True, ""),
        replace_signup_phone=lambda *_args, **_kwargs: calls.append("replace") or (False, "missing phone"),
        release_phone_lock=lambda _state, on_progress=None: calls.append("release"),
        verify_required_values=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("verify should not run")),
        click_submit=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("submit should not run")),
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep should not run")),
    )

    assert result == (False, "missing phone", True)
    assert calls == ["lock", "replace", "release"]


def test_retry_paypal_signup_after_phone_rejected_releases_lock_on_verify_or_submit_failure():
    verify_calls = []
    submit_calls = []

    verify_result = payment_form_fields.retry_paypal_signup_after_phone_rejected(
        object(),
        signup_profile={"phone": "8352880971"},
        state={},
        phone_key="8352880971",
        submitted_phone_keys=set(),
        current_url="https://www.paypal.com/checkoutweb/signup",
        ensure_phone_lock=lambda *_args, **_kwargs: verify_calls.append("lock") or (True, ""),
        replace_signup_phone=lambda *_args, **_kwargs: verify_calls.append("replace") or (True, ""),
        release_phone_lock=lambda _state, on_progress=None: verify_calls.append("release"),
        verify_required_values=lambda *_args, **_kwargs: verify_calls.append("verify") or (False, "missing card"),
        click_submit=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("submit should not run")),
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep should not run")),
    )
    submit_result = payment_form_fields.retry_paypal_signup_after_phone_rejected(
        object(),
        signup_profile={"phone": "8352880971"},
        state={},
        phone_key="8352880971",
        submitted_phone_keys=set(),
        current_url="https://www.paypal.com/checkoutweb/signup",
        ensure_phone_lock=lambda *_args, **_kwargs: submit_calls.append("lock") or (True, ""),
        replace_signup_phone=lambda *_args, **_kwargs: submit_calls.append("replace") or (True, ""),
        release_phone_lock=lambda _state, on_progress=None: submit_calls.append("release"),
        verify_required_values=lambda *_args, **_kwargs: submit_calls.append("verify") or (True, ""),
        click_submit=lambda *_args, **_kwargs: submit_calls.append("submit") or False,
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep should not run")),
    )

    assert verify_result == (False, "missing card", True)
    assert verify_calls == ["lock", "replace", "verify", "release"]
    assert submit_result == (False, "未找到 PayPal 注册提交按钮", False)
    assert submit_calls == ["lock", "replace", "verify", "submit", "release"]


def test_submit_paypal_signup_registration_form_fills_submits_and_tracks_phone_key():
    state = {"_fill_retry_count": 2}
    submitted_phone_keys = set()
    calls = []
    progress_events = []
    sleeps = []

    result = payment_form_fields.submit_paypal_signup_registration_form(
        object(),
        signup_profile={"phone": "8352880971"},
        state=state,
        phone_key="8352880971",
        submitted_phone_keys=submitted_phone_keys,
        current_url="https://www.paypal.com/checkoutweb/signup",
        wait_dom_loaded=lambda _api: calls.append("wait_dom"),
        ensure_phone_lock=lambda _state, *, signup_profile, on_progress=None: calls.append("lock") or (True, ""),
        fill_signup_form=lambda _api, *, signup_profile, on_progress=None: calls.append("fill") or (True, ""),
        release_phone_lock=lambda _state, on_progress=None: calls.append("release"),
        verify_required_values=lambda _api, _signup_profile: calls.append("verify") or (True, ""),
        click_submit=lambda _api: calls.append("submit") or True,
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        on_progress=progress_events.append,
        now=lambda: 3456.5,
        sleep=sleeps.append,
    )

    assert result == (True, "", True)
    assert calls == ["wait_dom", "lock", "fill", "verify", "submit"]
    assert state == {"_fill_retry_count": 0, "signup_submitted": True, "signup_submitted_at": 3456.5}
    assert submitted_phone_keys == {"8352880971"}
    assert progress_events == [
        {
            "stage": "paypal_submit_signup",
            "url": "https://www.paypal.com/checkoutweb/signup",
            "phone": "8352880971",
        }
    ]
    assert sleeps == [1.5, 2.0]


def test_submit_paypal_signup_registration_form_returns_phone_lock_failure():
    calls = []

    result = payment_form_fields.submit_paypal_signup_registration_form(
        object(),
        signup_profile={"phone": "8352880971"},
        state={},
        phone_key="8352880971",
        submitted_phone_keys=set(),
        current_url="https://www.paypal.com/checkoutweb/signup",
        wait_dom_loaded=lambda _api: calls.append("wait_dom"),
        ensure_phone_lock=lambda *_args, **_kwargs: calls.append("lock") or (False, "phone unavailable"),
        fill_signup_form=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("fill should not run")),
        release_phone_lock=lambda *_args, **_kwargs: calls.append("release"),
        verify_required_values=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("verify should not run")),
        click_submit=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("submit should not run")),
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        sleep=lambda _seconds: None,
    )

    assert result == (False, "phone unavailable", False)
    assert calls == ["wait_dom", "lock"]


def test_submit_paypal_signup_registration_form_retries_fill_failure_then_stops_after_limit():
    class FakeLogger:
        def __init__(self):
            self.messages = []

        def info(self, message, *args):
            self.messages.append((message, args))

    retry_state = {"_fill_retry_count": 2}
    retry_calls = []
    retry_logger = FakeLogger()
    retry_result = payment_form_fields.submit_paypal_signup_registration_form(
        object(),
        signup_profile={"phone": "8352880971"},
        state=retry_state,
        phone_key="8352880971",
        submitted_phone_keys=set(),
        current_url="https://www.paypal.com/checkoutweb/signup",
        wait_dom_loaded=lambda _api: retry_calls.append("wait_dom"),
        ensure_phone_lock=lambda *_args, **_kwargs: retry_calls.append("lock") or (True, ""),
        fill_signup_form=lambda *_args, **_kwargs: retry_calls.append("fill") or (False, "missing phone"),
        release_phone_lock=lambda _state, on_progress=None: retry_calls.append("release"),
        verify_required_values=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("verify should not run")),
        click_submit=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("submit should not run")),
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        logger=retry_logger,
        sleep=lambda _seconds: retry_calls.append("sleep"),
    )

    exhausted_state = {"_fill_retry_count": 3}
    exhausted_calls = []
    exhausted_result = payment_form_fields.submit_paypal_signup_registration_form(
        object(),
        signup_profile={"phone": "8352880971"},
        state=exhausted_state,
        phone_key="8352880971",
        submitted_phone_keys=set(),
        current_url="https://www.paypal.com/checkoutweb/signup",
        wait_dom_loaded=lambda _api: exhausted_calls.append("wait_dom"),
        ensure_phone_lock=lambda *_args, **_kwargs: exhausted_calls.append("lock") or (True, ""),
        fill_signup_form=lambda *_args, **_kwargs: exhausted_calls.append("fill") or (False, "missing phone"),
        release_phone_lock=lambda _state, on_progress=None: exhausted_calls.append("release"),
        verify_required_values=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("verify should not run")),
        click_submit=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("submit should not run")),
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        sleep=lambda _seconds: exhausted_calls.append("sleep"),
    )

    assert retry_result == (True, "", True)
    assert retry_state["_fill_retry_count"] == 3
    assert retry_calls == ["wait_dom", "sleep", "lock", "fill", "release", "sleep"]
    assert retry_logger.messages == [("[paypal_signup] fill form failed (%s), will retry (%d/3)", ("missing phone", 3))]
    assert exhausted_result == (False, "missing phone", True)
    assert exhausted_calls == ["wait_dom", "sleep", "lock", "fill", "release"]


def test_submit_paypal_signup_registration_form_releases_lock_on_verify_or_submit_failure():
    verify_calls = []
    submit_calls = []

    verify_result = payment_form_fields.submit_paypal_signup_registration_form(
        object(),
        signup_profile={"phone": "8352880971"},
        state={},
        phone_key="8352880971",
        submitted_phone_keys=set(),
        current_url="https://www.paypal.com/checkoutweb/signup",
        wait_dom_loaded=lambda _api: verify_calls.append("wait_dom"),
        ensure_phone_lock=lambda *_args, **_kwargs: verify_calls.append("lock") or (True, ""),
        fill_signup_form=lambda *_args, **_kwargs: verify_calls.append("fill") or (True, ""),
        release_phone_lock=lambda _state, on_progress=None: verify_calls.append("release"),
        verify_required_values=lambda *_args, **_kwargs: verify_calls.append("verify") or (False, "missing card"),
        click_submit=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("submit should not run")),
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        sleep=lambda _seconds: verify_calls.append("sleep"),
    )
    submit_result = payment_form_fields.submit_paypal_signup_registration_form(
        object(),
        signup_profile={"phone": "8352880971"},
        state={},
        phone_key="8352880971",
        submitted_phone_keys=set(),
        current_url="https://www.paypal.com/checkoutweb/signup",
        wait_dom_loaded=lambda _api: submit_calls.append("wait_dom"),
        ensure_phone_lock=lambda *_args, **_kwargs: submit_calls.append("lock") or (True, ""),
        fill_signup_form=lambda *_args, **_kwargs: submit_calls.append("fill") or (True, ""),
        release_phone_lock=lambda _state, on_progress=None: submit_calls.append("release"),
        verify_required_values=lambda *_args, **_kwargs: submit_calls.append("verify") or (True, ""),
        click_submit=lambda *_args, **_kwargs: submit_calls.append("submit") or False,
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        sleep=lambda _seconds: submit_calls.append("sleep"),
    )

    assert verify_result == (False, "missing card", True)
    assert verify_calls == ["wait_dom", "sleep", "lock", "fill", "verify", "release"]
    assert submit_result == (False, "未找到 PayPal 注册提交按钮", False)
    assert submit_calls == ["wait_dom", "sleep", "lock", "fill", "verify", "submit", "release"]


def test_paypal_signup_visible_validation_error_returns_matching_hints():
    text = "正しい日付を入力してください. Please check your information."

    assert (
        payment_form_fields.paypal_signup_visible_validation_error(text)
        == "正しい日付を入力してください / please check your information"
    )


def test_paypal_signup_visible_validation_error_returns_empty_without_match():
    assert payment_form_fields.paypal_signup_visible_validation_error("all good") == ""


def test_paypal_signup_otp_text_hint_detects_strict_english_and_japanese_prompts():
    assert payment_form_fields.paypal_signup_otp_text_hint("Enter your code We sent a 6-digit code") is True
    assert payment_form_fields.paypal_signup_otp_text_hint("コードを入力する 6桁のコードを送信しました") is True
    assert payment_form_fields.paypal_signup_otp_text_hint("Security code sent to your phone") is True
    assert payment_form_fields.paypal_signup_otp_text_hint("セキュリティコードを送信しました") is True


def test_paypal_signup_otp_text_hint_keeps_loose_inspection_hints_out_of_strict_mode():
    assert payment_form_fields.paypal_signup_otp_text_hint("check your phone") is False
    assert payment_form_fields.paypal_signup_otp_text_hint("check your phone", loose=True) is True
    assert payment_form_fields.paypal_signup_otp_text_hint("enter the code", loose=True) is True
    assert payment_form_fields.paypal_signup_otp_text_hint("验证码", loose=True) is True


def test_paypal_signup_otp_entry_text_hint_matches_fill_fallback_prompts():
    assert payment_form_fields.paypal_signup_otp_entry_text_hint("Enter your code") is True
    assert payment_form_fields.paypal_signup_otp_entry_text_hint("Security code") is True
    assert payment_form_fields.paypal_signup_otp_entry_text_hint("セキュリティコード") is True
    assert payment_form_fields.paypal_signup_otp_entry_text_hint("check your phone") is False


def test_paypal_signup_registration_text_hint_detects_english_and_japanese_forms():
    assert payment_form_fields.paypal_signup_registration_text_hint("Card number Billing address") is True
    assert (
        payment_form_fields.paypal_signup_registration_text_hint("Pay with debit or credit card and create password")
        is True
    )
    assert payment_form_fields.paypal_signup_registration_text_hint("カード番号 請求先住所") is True
    assert payment_form_fields.paypal_signup_registration_text_hint("生年月日 同意して続行") is True


def test_paypal_signup_registration_text_hint_rejects_partial_text():
    assert payment_form_fields.paypal_signup_registration_text_hint("Card number only") is False
    assert payment_form_fields.paypal_signup_registration_text_hint("電話番号だけ") is False


def test_paypal_signup_registration_form_text_visible_counts_any_two_markers():
    assert payment_form_fields.paypal_signup_registration_form_text_visible("Card number Create password") is True
    assert payment_form_fields.paypal_signup_registration_form_text_visible("電話番号 郵便番号") is True
    assert payment_form_fields.paypal_signup_registration_form_text_visible("Card number only") is False


def test_paypal_login_text_hint_detects_login_prompts():
    assert payment_form_fields.paypal_login_text_hint("Welcome back, log in to continue") is True
    assert payment_form_fields.paypal_login_text_hint("请输入邮箱后登录") is True
    assert payment_form_fields.paypal_login_text_hint("Create an account") is False


def test_paypal_passkey_text_hint_detects_passkey_prompts():
    assert payment_form_fields.paypal_passkey_text_hint("Use password instead or try another way") is True
    assert payment_form_fields.paypal_passkey_text_hint("通行密钥不可用，改用密码") is True
    assert payment_form_fields.paypal_passkey_text_hint("Password field") is False


def test_paypal_approve_text_hint_detects_authorization_prompts():
    assert payment_form_fields.paypal_approve_text_hint("Agree and continue to authorize") is True
    assert payment_form_fields.paypal_approve_text_hint("同意并继续 授权") is True
    assert payment_form_fields.paypal_approve_text_hint("Create account") is False


def test_paypal_rejected_text_hints_match_configured_hints_case_insensitively():
    phone_hints = ("try a different phone number", "別の電話番号")
    card_hints = ("card already linked", "try a different card")

    assert (
        payment_form_fields.paypal_phone_rejected_text_hint(
            "TRY A DIFFERENT PHONE NUMBER",
            hints=phone_hints,
        )
        is True
    )
    assert (
        payment_form_fields.paypal_phone_rejected_text_hint("別の電話番号をお試しください", hints=phone_hints) is True
    )
    assert payment_form_fields.paypal_phone_rejected_text_hint("", hints=phone_hints) is False
    assert payment_form_fields.paypal_card_rejected_text_hint("This card already linked.", hints=card_hints) is True
    assert payment_form_fields.paypal_card_rejected_text_hint("Payment approved", hints=card_hints) is False


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
