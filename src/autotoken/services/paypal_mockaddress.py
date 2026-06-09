"""MockAddress data helpers used by PayPal signup flows."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import requests

from autotoken.services import payment_form_fields

MOCKADDRESS_HEADERS = {
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://mockaddress.com/jp-address/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
    ),
}


def _requests_json(url: str) -> Any:
    resp = requests.get(
        url,
        headers=MOCKADDRESS_HEADERS,
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def mockaddress_jp_json(
    cache: dict[str, Any],
    cache_key: str,
    url: str,
    *,
    get_json: Callable[[str], Any] = _requests_json,
    on_error: Callable[[Exception], None] | None = None,
) -> dict:
    cached = cache.get(cache_key)
    if isinstance(cached, dict) and cached:
        return cached
    try:
        payload = get_json(url)
        if isinstance(payload, dict):
            cache[cache_key] = payload
            return payload
    except Exception as exc:
        if on_error:
            on_error(exc)
    return {}


def jp_prefecture_key_from_text(value: str, *, prefecture_name_to_ja: dict[str, str]) -> str:
    raw = re.sub(r"\s+", " ", str(value or "").strip())
    if not raw:
        return ""
    raw_ja = payment_form_fields.normalize_jp_prefecture_value(raw, prefecture_name_to_ja=prefecture_name_to_ja)
    for english_name, ja_name in prefecture_name_to_ja.items():
        normalized_english = english_name.removesuffix("-to").removesuffix("-fu")
        key = re.sub(r"[^A-Z]", "", normalized_english.upper())
        if raw_ja == ja_name:
            return key
    normalized = re.sub(r"[^a-z]+", " ", raw.lower()).strip()
    tokens = set(normalized.split())
    compact = normalized.replace(" ", "")
    for english_name in prefecture_name_to_ja:
        base = english_name.removesuffix("-to").removesuffix("-fu")
        if base in tokens or base.replace("-", "") in compact:
            return re.sub(r"[^A-Z]", "", base.upper())
    return ""


def jp_prefecture_key_for_exit_location(
    exit_location: dict[str, str],
    *,
    prefecture_name_to_ja: dict[str, str],
) -> tuple[str, dict[str, str], bool]:
    location = dict(exit_location or {})
    country_code = str(location.get("country_code") or "").upper()
    if country_code and country_code != "JP":
        return "", location, True
    for value in (location.get("region"), location.get("city")):
        key = jp_prefecture_key_from_text(str(value or ""), prefecture_name_to_ja=prefecture_name_to_ja)
        if key:
            return key, location, False
    return "", location, False


def format_jp_postcode(value: Any) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    if len(digits) == 7:
        return f"{digits[:3]}-{digits[3:]}"
    return str(value or "").strip()


def random_jp_phone_number(
    prefecture: dict[str, Any] | None = None,
    *,
    choose: Callable[[list[Any]], Any],
    randint: Callable[[int, int], int],
) -> str:
    phone_codes = list((prefecture or {}).get("phone_codes") or [])
    code = str(choose(phone_codes) if phone_codes else "090").strip()
    code = re.sub(r"\D+", "", code) or "090"
    if not code.startswith("0"):
        code = f"0{code}"
    return f"{code}-{randint(1000, 9999)}-{randint(1000, 9999)}"


def mockaddress_name_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item or "").strip()]
    if isinstance(value, dict):
        result: list[str] = []
        for key in ("male", "female", "kanji", "hiragana", "katakana"):
            result.extend(mockaddress_name_list(value.get(key)))
        return result
    return []


JP_ROMAN_FIRST_CANDIDATES = [
    "Hiroshi",
    "Takeshi",
    "Akira",
    "Satoshi",
    "Kenji",
    "Taro",
    "Jiro",
    "Ichiro",
    "Yuki",
    "Ai",
    "Emi",
    "Yui",
    "Rina",
    "Miki",
    "Saki",
    "Nana",
    "Kana",
    "Mana",
    "Hanako",
    "Misaki",
    "Sakura",
    "Aya",
    "Rei",
    "Mai",
    "Eri",
    "Yuka",
]

JP_ROMAN_LAST_CANDIDATES = [
    "Sato",
    "Suzuki",
    "Takahashi",
    "Tanaka",
    "Watanabe",
    "Ito",
    "Yamamoto",
    "Nakamura",
    "Kobayashi",
    "Kato",
    "Yoshida",
    "Yamada",
    "Sasaki",
    "Yamaguchi",
    "Matsumoto",
    "Inoue",
    "Kimura",
    "Hayashi",
    "Shimizu",
    "Yamazaki",
    "Mori",
    "Abe",
    "Ikeda",
    "Hashimoto",
    "Ishikawa",
    "Maeda",
    "Fujita",
    "Ogawa",
    "Goto",
    "Okada",
]


def build_mockaddress_jp_name_profile(
    jp_names: dict | None,
    global_names: dict | None,
    *,
    default_native_first_name: str,
    default_native_last_name: str,
    random_float: Callable[[], float],
    randrange: Callable[[int], int],
    choose: Callable[[list[str]], str],
) -> dict[str, str]:
    jp_names = dict(jp_names or {})
    global_names = dict(global_names or {})
    surnames = jp_names.get("surnames") if isinstance(jp_names.get("surnames"), dict) else {}
    first_names = jp_names.get("firstNames") if isinstance(jp_names.get("firstNames"), dict) else {}
    gender_key = "male" if random_float() > 0.5 else "female"
    gender_names = first_names.get(gender_key) if isinstance(first_names.get(gender_key), dict) else {}

    native_last_names = mockaddress_name_list(surnames.get("kanji")) or [default_native_last_name]
    kana_last_names = (
        mockaddress_name_list(surnames.get("katakana")) or mockaddress_name_list(surnames.get("hiragana")) or ["ヤマダ"]
    )
    last_index = randrange(len(native_last_names)) if native_last_names else 0
    native_last = native_last_names[last_index % len(native_last_names)]
    kana_last = kana_last_names[last_index % len(kana_last_names)]

    native_first_names = mockaddress_name_list(gender_names.get("kanji")) or [default_native_first_name]
    kana_first_names = (
        mockaddress_name_list(gender_names.get("katakana"))
        or mockaddress_name_list(gender_names.get("hiragana"))
        or ["タロウ"]
    )
    first_index = randrange(len(native_first_names)) if native_first_names else 0
    native_first = native_first_names[first_index % len(native_first_names)]
    kana_first = kana_first_names[first_index % len(kana_first_names)]

    name_groups = global_names.get("nameGroups") if isinstance(global_names.get("nameGroups"), dict) else {}
    western = name_groups.get("western") if isinstance(name_groups.get("western"), dict) else {}
    first_pool = mockaddress_name_list((western.get("first") if isinstance(western, dict) else {}) or {})
    last_pool = mockaddress_name_list(western.get("last") if isinstance(western, dict) else [])
    roman_first_names = [name for name in first_pool if name in JP_ROMAN_FIRST_CANDIDATES] or JP_ROMAN_FIRST_CANDIDATES
    roman_last_names = [name for name in last_pool if name in JP_ROMAN_LAST_CANDIDATES] or JP_ROMAN_LAST_CANDIDATES
    roman_first = choose(roman_first_names)
    roman_last = choose(roman_last_names)
    return {
        "name": f"{kana_first} {kana_last}",
        "first_name": kana_first,
        "last_name": kana_last,
        "native_first_name": native_first,
        "native_last_name": native_last,
        "roman_first_name": roman_first,
        "roman_last_name": roman_last,
    }


def merge_paypal_jp_signup_billing_payload(
    billing_payload: dict[str, str] | None,
    generated: dict,
    *,
    auto_generate: bool,
    default_name: str,
    default_native_first_name: str,
    default_native_last_name: str,
    default_billing_profile: dict[str, str],
) -> dict[str, str]:
    billing = dict(billing_payload or {})
    preserved = {
        key: str(billing.get(key) or "").strip()
        for key in ("email", "phone", "card_number", "card_expiry", "card_cvv")
        if str(billing.get(key) or "").strip()
    }
    name = (
        str(
            (generated.get("name") if auto_generate else "")
            or billing.get("name")
            or generated.get("name")
            or default_name
        ).strip()
        or default_name
    )
    billing.update(
        {
            "name": name,
            "first_name": str(generated.get("first_name") or "").strip(),
            "last_name": str(generated.get("last_name") or "").strip(),
            "native_first_name": str(generated.get("native_first_name") or default_native_first_name).strip(),
            "native_last_name": str(generated.get("native_last_name") or default_native_last_name).strip(),
            "country": "JP",
            "state": str(generated.get("state") or default_billing_profile["state"]).strip(),
            "city": str(generated.get("city") or default_billing_profile["city"]).strip(),
            "zip": str(generated.get("zip") or default_billing_profile["zip"]).strip(),
            "address1": str(generated.get("address1") or default_billing_profile["address1"]).strip(),
            "address2": str(generated.get("address2") or "").strip(),
        }
    )
    if not preserved.get("phone"):
        preserved["phone"] = str(generated.get("phone_number") or "").strip()
    billing.update(preserved)
    return billing


def prepare_paypal_jp_signup_billing_payload(
    billing_payload: dict[str, str] | None,
    *,
    paypal_country: str,
    auto_generate: bool,
    normalize_country: Callable[[str], str],
    billing_payload_complete: Callable[[dict[str, str]], bool],
    fetch_generated_billing_profile: Callable[[], dict],
    default_name: str,
    default_native_first_name: str,
    default_native_last_name: str,
    default_billing_profile: dict[str, str],
) -> dict[str, str]:
    billing = dict(billing_payload or {})
    country = normalize_country(paypal_country)
    if country != "JP":
        return billing

    original_country = normalize_country(str(billing.get("country") or "")) if billing.get("country") else ""
    needs_generated = bool(auto_generate) or original_country != "JP" or not billing_payload_complete(billing)
    if not needs_generated:
        billing["country"] = "JP"
        return billing

    generated = fetch_generated_billing_profile()
    return merge_paypal_jp_signup_billing_payload(
        billing,
        generated,
        auto_generate=auto_generate,
        default_name=default_name,
        default_native_first_name=default_native_first_name,
        default_native_last_name=default_native_last_name,
        default_billing_profile=default_billing_profile,
    )


def mockaddress_jp_prefectures(data: dict) -> dict:
    prefectures = data.get("prefectures") if isinstance(data.get("prefectures"), dict) else {}
    return prefectures


def select_mockaddress_jp_prefecture_key(
    prefectures: dict,
    preferred_key: str,
    *,
    default_key: str = "TOKYO",
) -> str:
    if not prefectures:
        return ""
    preferred = str(preferred_key or "").strip()
    if preferred and preferred in prefectures:
        return preferred
    return default_key


def build_mockaddress_jp_billing_profile(
    data: dict,
    real_areas: dict,
    *,
    prefecture_key: str,
    exit_location: dict[str, str],
    generated_name: dict[str, str],
    default_name: str,
    default_native_first_name: str,
    default_native_last_name: str,
    default_billing_profile: dict[str, str],
    choose: Callable[[list[Any]], Any],
    randint: Callable[[int, int], int],
) -> dict:
    prefectures = mockaddress_jp_prefectures(data)
    if not prefectures:
        return dict(default_billing_profile)

    selected_key = select_mockaddress_jp_prefecture_key(prefectures, prefecture_key)
    prefecture = dict(prefectures.get(selected_key) or prefectures.get("TOKYO") or {})
    prefecture_name = str((prefecture.get("name") or {}).get("ja") or default_billing_profile["state"]).strip()
    rows = real_areas.get("data") if isinstance(real_areas.get("data"), list) else []
    candidates = [row for row in rows if isinstance(row, dict) and str(row.get("prefecture") or "") == prefecture_name]

    if candidates:
        row = dict(choose(candidates))
        city = str(row.get("city") or "").strip()
        town = str(row.get("town") or "").strip()
        address1 = f"{town}{randint(1, 50)}-{randint(1, 20)}" if town else f"{randint(1, 50)}-{randint(1, 20)}"
        zip_code = format_jp_postcode(row.get("postcode"))
    else:
        address_data = data.get("address_data") if isinstance(data.get("address_data"), dict) else {}
        cities = list((address_data.get("cities") or {}).get("kanji") or [])
        streets = list((address_data.get("streets") or {}).get("kanji") or [])
        wards = list((address_data.get("wards") or {}).get("kanji") or [])
        city = str(choose(cities) if cities else "東京").strip()
        street = str(choose(streets) if streets else "中央").strip()
        ward = str(choose(wards) if wards else "1丁目").strip()
        address1 = f"{street}{ward}{randint(1, 50)}番{randint(1, 20)}号"
        prefixes = list(prefecture.get("postal_prefix") or ["100"])
        zip_code = f"{choose(prefixes)}-{randint(1000, 9999)}"

    return {
        "name": generated_name.get("name") or default_name,
        "first_name": generated_name.get("first_name") or "",
        "last_name": generated_name.get("last_name") or "",
        "native_first_name": generated_name.get("native_first_name") or default_native_first_name,
        "native_last_name": generated_name.get("native_last_name") or default_native_last_name,
        "country": "JP",
        "state": prefecture_name,
        "city": city,
        "zip": zip_code,
        "address1": address1,
        "address2": "",
        "phone_number": random_jp_phone_number(prefecture, choose=choose, randint=randint),
        "raw": {
            "source": "mockaddress",
            "prefecture_key": selected_key,
            "proxy_exit": exit_location,
        },
    }
