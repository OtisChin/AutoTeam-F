from autotoken.services import paypal_mockaddress

PREFECTURE_NAME_TO_JA = {
    "tokyo-to": "東京都",
    "osaka-fu": "大阪府",
    "kanagawa": "神奈川県",
    "fukuoka": "福岡県",
}


def test_mockaddress_jp_json_uses_cache_and_stores_dict_payloads():
    cache = {"jp_data": {"cached": True}}
    calls = []

    assert paypal_mockaddress.mockaddress_jp_json(
        cache,
        "jp_data",
        "https://example.test/jpData.json",
        get_json=lambda url: calls.append(url) or {"fresh": True},
    ) == {"cached": True}
    assert calls == []

    assert paypal_mockaddress.mockaddress_jp_json(
        cache,
        "jp_names",
        "https://example.test/jpNamesData.json",
        get_json=lambda url: calls.append(url) or {"fresh": True},
    ) == {"fresh": True}
    assert cache["jp_names"] == {"fresh": True}
    assert calls == ["https://example.test/jpNamesData.json"]


def test_mockaddress_jp_json_ignores_non_dict_payload_and_reports_errors():
    errors = []

    assert (
        paypal_mockaddress.mockaddress_jp_json(
            {},
            "jp_data",
            "https://example.test/jpData.json",
            get_json=lambda _url: ["not", "a", "dict"],
        )
        == {}
    )
    assert (
        paypal_mockaddress.mockaddress_jp_json(
            {},
            "jp_data",
            "https://example.test/jpData.json",
            get_json=lambda _url: (_ for _ in ()).throw(RuntimeError("network down")),
            on_error=errors.append,
        )
        == {}
    )
    assert [str(error) for error in errors] == ["network down"]


def test_jp_prefecture_key_from_text_accepts_japanese_and_english_names():
    assert (
        paypal_mockaddress.jp_prefecture_key_from_text(
            "大阪府",
            prefecture_name_to_ja=PREFECTURE_NAME_TO_JA,
        )
        == "OSAKA"
    )
    assert (
        paypal_mockaddress.jp_prefecture_key_from_text(
            "Osaka City",
            prefecture_name_to_ja=PREFECTURE_NAME_TO_JA,
        )
        == "OSAKA"
    )
    assert (
        paypal_mockaddress.jp_prefecture_key_from_text(
            "Kanagawa Prefecture",
            prefecture_name_to_ja=PREFECTURE_NAME_TO_JA,
        )
        == "KANAGAWA"
    )
    assert (
        paypal_mockaddress.jp_prefecture_key_from_text(
            "",
            prefecture_name_to_ja=PREFECTURE_NAME_TO_JA,
        )
        == ""
    )


def test_jp_prefecture_key_for_exit_location_handles_non_jp_and_region_city_fallbacks():
    assert paypal_mockaddress.jp_prefecture_key_for_exit_location(
        {"country_code": "US", "region": "California", "city": "Los Angeles", "ip": "203.0.113.10"},
        prefecture_name_to_ja=PREFECTURE_NAME_TO_JA,
    ) == (
        "",
        {"country_code": "US", "region": "California", "city": "Los Angeles", "ip": "203.0.113.10"},
        True,
    )
    assert paypal_mockaddress.jp_prefecture_key_for_exit_location(
        {"country_code": "JP", "region": "Osaka", "city": ""},
        prefecture_name_to_ja=PREFECTURE_NAME_TO_JA,
    ) == (
        "OSAKA",
        {"country_code": "JP", "region": "Osaka", "city": ""},
        False,
    )
    assert paypal_mockaddress.jp_prefecture_key_for_exit_location(
        {"country_code": "JP", "region": "", "city": "Fukuoka City"},
        prefecture_name_to_ja=PREFECTURE_NAME_TO_JA,
    ) == (
        "FUKUOKA",
        {"country_code": "JP", "region": "", "city": "Fukuoka City"},
        False,
    )
    assert paypal_mockaddress.jp_prefecture_key_for_exit_location(
        {},
        prefecture_name_to_ja=PREFECTURE_NAME_TO_JA,
    ) == ("", {}, False)


def test_format_jp_postcode_normalizes_seven_digits_only():
    assert paypal_mockaddress.format_jp_postcode("5300001") == "530-0001"
    assert paypal_mockaddress.format_jp_postcode("〒100-0001") == "100-0001"
    assert paypal_mockaddress.format_jp_postcode("10001") == "10001"


def test_random_jp_phone_number_uses_prefecture_code_and_national_prefix():
    assert (
        paypal_mockaddress.random_jp_phone_number(
            {"phone_codes": ["6"]},
            choose=lambda values: values[0],
            randint=lambda start, _end: start,
        )
        == "06-1000-1000"
    )
    assert (
        paypal_mockaddress.random_jp_phone_number(
            {},
            choose=lambda values: values[0],
            randint=lambda _start, end: end,
        )
        == "090-9999-9999"
    )


def test_mockaddress_name_list_flattens_supported_name_groups():
    assert paypal_mockaddress.mockaddress_name_list([" Taro ", "", None, "Jiro"]) == ["Taro", "Jiro"]
    assert paypal_mockaddress.mockaddress_name_list(
        {
            "male": ["Taro"],
            "female": ["Hanako"],
            "kanji": ["太郎"],
            "hiragana": ["たろう"],
            "katakana": ["タロウ"],
            "ignored": ["not included"],
        }
    ) == ["Taro", "Hanako", "太郎", "たろう", "タロウ"]
    assert paypal_mockaddress.mockaddress_name_list("Taro") == []


def test_build_mockaddress_jp_name_profile_uses_name_data_and_filters_roman_candidates():
    profile = paypal_mockaddress.build_mockaddress_jp_name_profile(
        {
            "surnames": {"kanji": ["山田"], "katakana": ["ヤマダ"]},
            "firstNames": {
                "male": {"kanji": ["太郎"], "katakana": ["タロウ"]},
                "female": {"kanji": ["花子"], "katakana": ["ハナコ"]},
            },
        },
        {
            "nameGroups": {
                "western": {
                    "first": {"male": ["NotJapanese", "Taro"], "female": ["Hana"]},
                    "last": ["Unknown", "Yamada"],
                }
            }
        },
        default_native_first_name="太郎",
        default_native_last_name="山田",
        random_float=lambda: 0.75,
        randrange=lambda bound: 0,
        choose=lambda values: values[0],
    )

    assert profile == {
        "name": "タロウ ヤマダ",
        "first_name": "タロウ",
        "last_name": "ヤマダ",
        "native_first_name": "太郎",
        "native_last_name": "山田",
        "roman_first_name": "Taro",
        "roman_last_name": "Yamada",
    }


def test_build_mockaddress_jp_name_profile_falls_back_when_data_is_missing():
    profile = paypal_mockaddress.build_mockaddress_jp_name_profile(
        {},
        {},
        default_native_first_name="太郎",
        default_native_last_name="山田",
        random_float=lambda: 0.0,
        randrange=lambda bound: 0,
        choose=lambda values: values[0],
    )

    assert profile["name"] == "タロウ ヤマダ"
    assert profile["native_first_name"] == "太郎"
    assert profile["native_last_name"] == "山田"
    assert profile["roman_first_name"] == "Hiroshi"
    assert profile["roman_last_name"] == "Sato"


def test_merge_paypal_jp_signup_billing_payload_preserves_contact_and_card_fields():
    merged = paypal_mockaddress.merge_paypal_jp_signup_billing_payload(
        {
            "name": "Existing Name",
            "email": " user@example.com ",
            "phone": "+817094870367",
            "card_number": " 4111111111111111 ",
            "card_expiry": " 03 / 30 ",
            "card_cvv": " 123 ",
        },
        {
            "name": "タロウ ヤマダ",
            "first_name": "タロウ",
            "last_name": "ヤマダ",
            "native_first_name": "太郎",
            "native_last_name": "山田",
            "state": "大阪府",
            "city": "大阪市北区",
            "zip": "530-0001",
            "address1": "梅田1-1",
            "address2": "",
            "phone_number": "06-1000-1000",
        },
        auto_generate=False,
        default_name="James Smith",
        default_native_first_name="太郎",
        default_native_last_name="山田",
        default_billing_profile={
            "state": "Tokyo",
            "city": "Chiyoda",
            "zip": "100-0001",
            "address1": "1-1 Chiyoda",
        },
    )

    assert merged["name"] == "Existing Name"
    assert merged["country"] == "JP"
    assert merged["state"] == "大阪府"
    assert merged["phone"] == "+817094870367"
    assert merged["email"] == "user@example.com"
    assert merged["card_number"] == "4111111111111111"
    assert merged["card_expiry"] == "03 / 30"
    assert merged["card_cvv"] == "123"


def test_merge_paypal_jp_signup_billing_payload_uses_generated_and_default_fallbacks():
    merged = paypal_mockaddress.merge_paypal_jp_signup_billing_payload(
        {"name": "Existing Name"},
        {"name": "Generated Name", "phone_number": "06-1000-1000"},
        auto_generate=True,
        default_name="James Smith",
        default_native_first_name="太郎",
        default_native_last_name="山田",
        default_billing_profile={
            "state": "Tokyo",
            "city": "Chiyoda",
            "zip": "100-0001",
            "address1": "1-1 Chiyoda",
        },
    )

    assert merged["name"] == "Generated Name"
    assert merged["native_first_name"] == "太郎"
    assert merged["native_last_name"] == "山田"
    assert merged["state"] == "Tokyo"
    assert merged["city"] == "Chiyoda"
    assert merged["zip"] == "100-0001"
    assert merged["address1"] == "1-1 Chiyoda"
    assert merged["phone"] == "06-1000-1000"


def test_prepare_paypal_jp_signup_billing_payload_returns_copy_for_non_jp_country():
    billing = {"country": "US", "state": "CA", "city": "Los Angeles"}

    prepared = paypal_mockaddress.prepare_paypal_jp_signup_billing_payload(
        billing,
        paypal_country="US",
        auto_generate=False,
        normalize_country=lambda value: str(value or "").upper(),
        billing_payload_complete=lambda _billing: True,
        fetch_generated_billing_profile=lambda: (_ for _ in ()).throw(AssertionError("should not fetch")),
        default_name="James Smith",
        default_native_first_name="太郎",
        default_native_last_name="山田",
        default_billing_profile={"state": "Tokyo", "city": "Chiyoda", "zip": "100-0001", "address1": "1-1 Chiyoda"},
    )

    assert prepared == billing
    assert prepared is not billing


def test_prepare_paypal_jp_signup_billing_payload_keeps_complete_jp_payload_without_fetching():
    billing = {
        "country": "jp",
        "state": "Tokyo",
        "city": "Chiyoda",
        "zip": "100-0001",
        "address1": "1-1 Chiyoda",
    }

    prepared = paypal_mockaddress.prepare_paypal_jp_signup_billing_payload(
        billing,
        paypal_country="jp",
        auto_generate=False,
        normalize_country=lambda value: str(value or "").upper(),
        billing_payload_complete=lambda _billing: True,
        fetch_generated_billing_profile=lambda: (_ for _ in ()).throw(AssertionError("should not fetch")),
        default_name="James Smith",
        default_native_first_name="太郎",
        default_native_last_name="山田",
        default_billing_profile={"state": "Tokyo", "city": "Chiyoda", "zip": "100-0001", "address1": "1-1 Chiyoda"},
    )

    assert prepared == {
        "country": "JP",
        "state": "Tokyo",
        "city": "Chiyoda",
        "zip": "100-0001",
        "address1": "1-1 Chiyoda",
    }
    assert billing["country"] == "jp"


def test_prepare_paypal_jp_signup_billing_payload_fetches_and_merges_when_generation_needed():
    calls = []

    prepared = paypal_mockaddress.prepare_paypal_jp_signup_billing_payload(
        {
            "name": "Existing Name",
            "country": "US",
            "email": " user@example.com ",
            "card_number": " 4111111111111111 ",
        },
        paypal_country="JP",
        auto_generate=True,
        normalize_country=lambda value: str(value or "").upper(),
        billing_payload_complete=lambda _billing: False,
        fetch_generated_billing_profile=lambda: (
            calls.append("fetch")
            or {
                "name": "Generated Name",
                "first_name": "タロウ",
                "last_name": "ヤマダ",
                "native_first_name": "太郎",
                "native_last_name": "山田",
                "state": "大阪府",
                "city": "大阪市北区",
                "zip": "530-0001",
                "address1": "梅田1-1",
                "phone_number": "06-1000-1000",
            }
        ),
        default_name="James Smith",
        default_native_first_name="太郎",
        default_native_last_name="山田",
        default_billing_profile={"state": "Tokyo", "city": "Chiyoda", "zip": "100-0001", "address1": "1-1 Chiyoda"},
    )

    assert calls == ["fetch"]
    assert prepared["name"] == "Generated Name"
    assert prepared["country"] == "JP"
    assert prepared["state"] == "大阪府"
    assert prepared["email"] == "user@example.com"
    assert prepared["card_number"] == "4111111111111111"
    assert prepared["phone"] == "06-1000-1000"


def test_mockaddress_jp_prefectures_returns_dict_payload_only():
    prefectures = {"TOKYO": {"name": {"ja": "東京都"}}}

    assert paypal_mockaddress.mockaddress_jp_prefectures({"prefectures": prefectures}) == prefectures
    assert paypal_mockaddress.mockaddress_jp_prefectures({"prefectures": []}) == {}
    assert paypal_mockaddress.mockaddress_jp_prefectures({}) == {}


def test_select_mockaddress_jp_prefecture_key_prefers_available_proxy_match():
    prefectures = {"TOKYO": {}, "OSAKA": {}}

    assert paypal_mockaddress.select_mockaddress_jp_prefecture_key(prefectures, "OSAKA") == "OSAKA"
    assert paypal_mockaddress.select_mockaddress_jp_prefecture_key(prefectures, "MISSING") == "TOKYO"
    assert paypal_mockaddress.select_mockaddress_jp_prefecture_key({}, "OSAKA") == ""


def test_build_mockaddress_jp_billing_profile_uses_real_area_candidate():
    profile = paypal_mockaddress.build_mockaddress_jp_billing_profile(
        {
            "prefectures": {
                "TOKYO": {"name": {"ja": "東京都"}, "phone_codes": ["03"], "postal_prefix": ["100"]},
                "OSAKA": {"name": {"ja": "大阪府"}, "phone_codes": ["06"], "postal_prefix": ["530"]},
            }
        },
        {
            "data": [
                {"postcode": "5300001", "prefecture": "大阪府", "city": "大阪市北区", "town": "梅田"},
            ]
        },
        prefecture_key="OSAKA",
        exit_location={"country_code": "JP", "region": "Osaka"},
        generated_name={
            "name": "タロウ ヤマダ",
            "first_name": "タロウ",
            "last_name": "ヤマダ",
            "native_first_name": "太郎",
            "native_last_name": "山田",
        },
        default_name="James Smith",
        default_native_first_name="太郎",
        default_native_last_name="山田",
        default_billing_profile={"state": "Tokyo", "city": "Chiyoda", "zip": "100-0001", "address1": "1-1 Chiyoda"},
        choose=lambda values: values[0],
        randint=lambda start, _end: start,
    )

    assert profile["name"] == "タロウ ヤマダ"
    assert profile["state"] == "大阪府"
    assert profile["city"] == "大阪市北区"
    assert profile["zip"] == "530-0001"
    assert profile["address1"] == "梅田1-1"
    assert profile["phone_number"] == "06-1000-1000"
    assert profile["raw"] == {
        "source": "mockaddress",
        "prefecture_key": "OSAKA",
        "proxy_exit": {"country_code": "JP", "region": "Osaka"},
    }


def test_build_mockaddress_jp_billing_profile_uses_address_data_fallback():
    profile = paypal_mockaddress.build_mockaddress_jp_billing_profile(
        {
            "prefectures": {
                "TOKYO": {"name": {"ja": "東京都"}, "phone_codes": [], "postal_prefix": ["100"]},
            },
            "address_data": {
                "cities": {"kanji": ["千代田区"]},
                "streets": {"kanji": ["丸の内"]},
                "wards": {"kanji": ["1丁目"]},
            },
        },
        {"data": []},
        prefecture_key="MISSING",
        exit_location={},
        generated_name={},
        default_name="James Smith",
        default_native_first_name="太郎",
        default_native_last_name="山田",
        default_billing_profile={"state": "Tokyo", "city": "Chiyoda", "zip": "100-0001", "address1": "1-1 Chiyoda"},
        choose=lambda values: values[0],
        randint=lambda start, _end: start,
    )

    assert profile["name"] == "James Smith"
    assert profile["state"] == "東京都"
    assert profile["city"] == "千代田区"
    assert profile["zip"] == "100-1000"
    assert profile["address1"] == "丸の内1丁目1番1号"
    assert profile["phone_number"] == "090-1000-1000"
    assert profile["raw"]["prefecture_key"] == "TOKYO"


def test_build_mockaddress_jp_billing_profile_returns_default_without_prefectures():
    default_profile = {"state": "Tokyo", "city": "Chiyoda", "zip": "100-0001", "address1": "1-1 Chiyoda"}

    assert (
        paypal_mockaddress.build_mockaddress_jp_billing_profile(
            {},
            {},
            prefecture_key="TOKYO",
            exit_location={},
            generated_name={},
            default_name="James Smith",
            default_native_first_name="太郎",
            default_native_last_name="山田",
            default_billing_profile=default_profile,
            choose=lambda values: values[0],
            randint=lambda start, _end: start,
        )
        == default_profile
    )
