"""Shared browser form field helpers used by payment flows."""

from __future__ import annotations

import logging
import re
import secrets
import string
import time
import uuid
from collections.abc import Callable, Sequence
from typing import Any

from autotoken.services import payment_checkout_state


def value_matches(expected: str, actual: str) -> bool:
    expected_raw = str(expected or "").strip()
    actual_raw = str(actual or "").strip()
    if expected_raw == actual_raw:
        return True
    expected_norm = re.sub(r"\s+", " ", expected_raw).lower()
    actual_norm = re.sub(r"\s+", " ", actual_raw).lower()
    return bool(expected_norm) and expected_norm == actual_norm


def normalize_us_state_value(
    value: str,
    *,
    state_name_to_code: dict[str, str],
    state_code_to_name: dict[str, str],
) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "").strip()).lower()
    if not normalized:
        return ""
    upper = normalized.upper()
    if upper in state_code_to_name:
        return upper
    return state_name_to_code.get(normalized, upper)


def jp_prefecture_candidates(value: str, *, prefecture_name_to_ja: dict[str, str]) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    normalized = re.sub(r"\s+", "-", raw).strip().lower()
    candidates = [raw]
    mapped = prefecture_name_to_ja.get(normalized) or prefecture_name_to_ja.get(normalized.replace("-to", ""))
    if mapped:
        candidates.append(mapped)
        candidates.append(mapped.removesuffix("都").removesuffix("道").removesuffix("府").removesuffix("県"))
    elif raw in prefecture_name_to_ja.values():
        candidates.append(raw.removesuffix("都").removesuffix("道").removesuffix("府").removesuffix("県"))
    seen: set[str] = set()
    unique: list[str] = []
    for item in candidates:
        item = str(item or "").strip()
        if item and item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def normalize_jp_prefecture_value(value: str, *, prefecture_name_to_ja: dict[str, str]) -> str:
    raw = re.sub(r"\s+", " ", str(value or "").strip())
    if not raw:
        return ""
    lowered = raw.lower().replace(" ", "-")
    if lowered in prefecture_name_to_ja:
        return prefecture_name_to_ja[lowered]
    if raw in prefecture_name_to_ja.values():
        return raw
    for ja in prefecture_name_to_ja.values():
        if raw == ja.removesuffix("都").removesuffix("道").removesuffix("府").removesuffix("県"):
            return ja
    return raw


def state_value_matches(
    expected: str,
    actual: str,
    *,
    state_name_to_code: dict[str, str],
    state_code_to_name: dict[str, str],
    prefecture_name_to_ja: dict[str, str],
) -> bool:
    expected_jp = normalize_jp_prefecture_value(expected, prefecture_name_to_ja=prefecture_name_to_ja)
    actual_jp = normalize_jp_prefecture_value(actual, prefecture_name_to_ja=prefecture_name_to_ja)
    if expected_jp and actual_jp and expected_jp == actual_jp:
        return True
    expected_state = normalize_us_state_value(
        expected,
        state_name_to_code=state_name_to_code,
        state_code_to_name=state_code_to_name,
    )
    actual_state = normalize_us_state_value(
        actual,
        state_name_to_code=state_name_to_code,
        state_code_to_name=state_code_to_name,
    )
    if expected_state and actual_state and expected_state == actual_state:
        return True
    return value_matches(expected, actual)


def card_value_matches(
    expected: str,
    actual: str,
    *,
    field: str,
    normalize_card_expiry,
) -> bool:
    expected_digits = re.sub(r"\D+", "", str(expected or ""))
    actual_digits = re.sub(r"\D+", "", str(actual or ""))
    if field in {"card_number", "card_cvv"}:
        return bool(expected_digits) and expected_digits == actual_digits
    if field == "card_expiry":
        return normalize_card_expiry(expected) == normalize_card_expiry(actual)
    return value_matches(expected, actual)


def luhn_check_digit(prefix: str) -> str:
    digits = [int(char) for char in re.sub(r"\D+", "", str(prefix or ""))]
    total = 0
    parity = (len(digits) + 1) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return str((10 - (total % 10)) % 10)


def luhn_valid(value: str) -> bool:
    digits = re.sub(r"\D+", "", str(value or ""))
    if len(digits) < 12:
        return False
    total = 0
    parity = len(digits) % 2
    for index, char in enumerate(digits):
        digit = int(char)
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def paypal_card_brand_allowed(value: str) -> bool:
    digits = re.sub(r"\D+", "", str(value or ""))
    if len(digits) == 15 and digits[:2] in {"34", "37"}:
        return True
    if len(digits) == 16 and digits.startswith("4"):
        return True
    if len(digits) == 16 and 51 <= int(digits[:2] or "0") <= 55:
        return True
    return len(digits) == 16 and 2221 <= int(digits[:4] or "0") <= 2720


def generate_paypal_card_number(
    *,
    choose: Callable[[Sequence[str]], str] = secrets.choice,
) -> str:
    prefixes = ("4539", "4485", "4716", "5200", "5424", "2221", "3782")
    prefix = choose(prefixes)
    length = 15 if prefix.startswith(("34", "37")) else 16
    body_len = length - len(prefix) - 1
    body = prefix + "".join(choose(string.digits) for _ in range(body_len))
    return body + luhn_check_digit(body)


def normalize_or_generate_paypal_card_number(
    value: str,
    *,
    generate_card_number: Callable[[], str] = generate_paypal_card_number,
) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    if paypal_card_brand_allowed(digits) and luhn_valid(digits):
        return digits
    return generate_card_number()


def generate_paypal_card_expiry(
    *,
    randbelow: Callable[[int], int] = secrets.randbelow,
) -> str:
    month = randbelow(12) + 1
    year = 2029 + randbelow(4)
    return f"{month:02d} / {str(year)[-2:]}"


def generate_paypal_card_cvv(
    card_number: str = "",
    *,
    choose: Callable[[Sequence[str]], str] = secrets.choice,
) -> str:
    length = 4 if re.sub(r"\D+", "", str(card_number or "")).startswith(("34", "37")) else 3
    first = choose("123456789")
    return first + "".join(choose(string.digits) for _ in range(length - 1))


def normalize_paypal_card_expiry(value: str) -> str:
    raw = re.sub(r"\D+", "", str(value or ""))
    if len(raw) == 4:
        return f"{raw[:2]} / {raw[2:]}"
    if len(raw) == 6:
        return f"{raw[:2]} / {raw[-2:]}"
    return str(value or "").strip()


def normalize_paypal_credentials(email: str = "", password: str = "") -> dict[str, str]:
    return {
        "email": str(email or "").strip(),
        "password": str(password or ""),
    }


def generate_random_paypal_email(*, uuid_hex: str | None = None) -> str:
    value = uuid_hex if uuid_hex is not None else uuid.uuid4().hex
    return f"pp{str(value or '')[:16]}@gmail.com"


def generate_random_paypal_password(
    *,
    choose: Callable[[Sequence[str]], str] = secrets.choice,
    shuffle: Callable[[list[str]], None] | None = None,
) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^"
    required = [
        choose(string.ascii_lowercase),
        choose(string.ascii_uppercase),
        choose(string.digits),
        choose("!@#$%^"),
    ]
    required.extend(choose(alphabet) for _ in range(10))
    if shuffle is None:
        secrets.SystemRandom().shuffle(required)
    else:
        shuffle(required)
    return "".join(required)


def split_paypal_name(name: str) -> tuple[str, str]:
    parts = [part for part in re.split(r"\s+", str(name or "").strip()) if part]
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:])
    if len(parts) == 1:
        return parts[0], "Smith"
    return "James", "Smith"


def normalize_paypal_phone(phone: str) -> str:
    digits = re.sub(r"\D+", "", str(phone or ""))
    if digits.startswith("0081") and len(digits) >= 12:
        digits = digits[2:]
    if digits.startswith("81") and len(digits) >= 10:
        national = digits[2:]
        if national.startswith("0"):
            return national
        return f"0{national}"
    if len(digits) == 11 and digits.startswith("1"):
        return digits[1:]
    return digits


def paypal_phone_value_valid(phone: str, *, country: str = "", normalize_country, normalize_phone) -> bool:
    normalized_country = normalize_country(country) if country else ""
    normalized_phone = normalize_phone(phone)
    digits = re.sub(r"\D+", "", normalized_phone)
    if normalized_country == "JP":
        return len(digits) in {10, 11} and digits.startswith("0")
    if normalized_country == "US":
        return len(digits) == 10
    return len(digits) >= 7


def first_payload_value(source: dict, *keys: str) -> str:
    for key in keys:
        value = str(source.get(key) or "").strip()
        if value:
            return value
    return ""


def split_paypal_address_lines(address1: str) -> tuple[str, str]:
    raw = str(address1 or "").strip()
    if not raw:
        return "", ""
    matched = re.match(r"^(.*?)(?:\s+(APT|APARTMENT|UNIT|STE|SUITE|FL)\.?\s+.+)$", raw, flags=re.IGNORECASE)
    if not matched:
        return raw, ""
    line1 = matched.group(1).strip()
    line2 = raw[len(line1) :].strip(" ,")
    return line1, line2


def flatten_paypal_generator_fields(value: Any, prefix: str = "") -> dict[str, str]:
    fields: dict[str, str] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            next_key = f"{prefix}_{key}" if prefix else str(key)
            fields.update(flatten_paypal_generator_fields(item, next_key))
        return fields
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            fields.update(flatten_paypal_generator_fields(item, f"{prefix}_{index}"))
        return fields
    if prefix:
        fields[prefix] = str(value or "").strip()
    return fields


def paypal_generator_field(address: dict, *names: str) -> str:
    normalized = {
        re.sub(r"[^a-z0-9]+", "", str(key or "").lower()): value
        for key, value in flatten_paypal_generator_fields(address).items()
    }
    for name in names:
        key = re.sub(r"[^a-z0-9]+", "", str(name or "").lower())
        value = str(normalized.get(key) or "").strip()
        if value:
            return value
    for name in names:
        key = re.sub(r"[^a-z0-9]+", "", str(name or "").lower())
        for candidate_key, value in normalized.items():
            if candidate_key.endswith(key):
                text = str(value or "").strip()
                if text:
                    return text
    return ""


def public_paypal_billing_info(billing: dict | None) -> dict[str, str]:
    source = dict(billing or {})
    return {
        "name": str(source.get("name") or "").strip(),
        "country": str(source.get("country") or "").strip(),
        "state": str(source.get("state") or "").strip(),
        "city": str(source.get("city") or "").strip(),
        "zip": str(source.get("zip") or "").strip(),
        "address1": str(source.get("address1") or "").strip(),
        "address2": str(source.get("address2") or "").strip(),
        "phone_number": str(source.get("phone_number") or "").strip(),
    }


def merge_paypal_checkout_billing_payload(
    requested: dict | None,
    generated_raw: dict | None,
    *,
    requested_country: str,
    default_name: str,
    normalize_or_generate_card_number: Callable[[str], str],
    generate_card_expiry: Callable[[], str],
    generate_card_cvv: Callable[[str], str],
) -> dict[str, str]:
    requested = dict(requested or {})
    generated_raw = dict(generated_raw or {})
    generated = public_paypal_billing_info(generated_raw)
    merged = {
        "name": str(generated.get("name") or default_name).strip() or default_name,
        "email": str(requested.get("email") or "").strip(),
        "phone": str(requested.get("phone") or generated.get("phone_number") or "").strip(),
        "country": str(requested_country or "").strip(),
        "state": str(generated.get("state") or "").strip(),
        "city": str(generated.get("city") or "").strip(),
        "zip": str(generated.get("zip") or "").strip(),
        "address1": str(generated.get("address1") or "").strip(),
        "address2": str(generated.get("address2") or "").strip(),
    }
    card_fields = {
        "card_number": first_payload_value(generated_raw, "card_number", "cardNumber"),
        "card_expiry": first_payload_value(
            generated_raw,
            "card_expiry",
            "cardExpiry",
            "expiry",
            "expiry_date",
        ),
        "card_cvv": first_payload_value(generated_raw, "card_cvv", "cardCvv", "cvv", "cvc"),
    }
    for key, value in card_fields.items():
        if value:
            merged[key] = str(value).strip()
    merged["card_number"] = normalize_or_generate_card_number(merged.get("card_number") or "")
    merged["card_expiry"] = str(merged.get("card_expiry") or "").strip() or generate_card_expiry()
    merged["card_cvv"] = re.sub(r"\D+", "", str(merged.get("card_cvv") or "")) or generate_card_cvv(
        merged["card_number"]
    )
    return merged


def normalize_paypal_phone_account(raw: Any, *, fallback_otp_channel: str = "sms") -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    phone = str(
        raw.get("phone")
        or raw.get("phone_number")
        or raw.get("phoneNumber")
        or raw.get("billing_phone")
        or raw.get("billingPhone")
        or ""
    ).strip()
    sms_url = str(raw.get("sms_url") or raw.get("smsUrl") or "").strip()
    otp_channel = (
        str(raw.get("otp_channel") or raw.get("otpChannel") or fallback_otp_channel or "sms").strip().lower() or "sms"
    )
    if not phone or not sms_url:
        return {}
    if otp_channel not in {"sms", "whatsapp"}:
        otp_channel = "sms"
    return {"phone": phone, "sms_url": sms_url, "otp_channel": otp_channel}


def sync_paypal_signup_phone_submission_state(
    signup_profile: dict[str, Any],
    state: dict[str, Any],
    *,
    signup_submitted: bool,
    normalize_phone,
) -> tuple[bool, str, set[str], bool]:
    phone_key = normalize_phone(str(signup_profile.get("phone") or ""))
    submitted_phone_keys = state.get("submitted_phone_keys")
    if not isinstance(submitted_phone_keys, set):
        submitted_phone_keys = set()
        state["submitted_phone_keys"] = submitted_phone_keys
    phone_already_submitted = bool(phone_key and phone_key in submitted_phone_keys)
    if phone_already_submitted and not signup_submitted:
        signup_submitted = True
        state["signup_submitted"] = True
    return signup_submitted, phone_key, submitted_phone_keys, phone_already_submitted


def paypal_signup_profiles_for_phone_pool(
    base_profile: dict[str, str | bool] | None,
    phone_accounts: list[dict] | None,
    *,
    normalize_phone: Callable[[str], str],
    phone_value_valid: Callable[..., bool],
) -> list[dict[str, str | bool]]:
    if not base_profile:
        return []
    fallback_otp_channel = str(base_profile.get("otp_channel") or "sms")
    normalized_accounts: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for raw in phone_accounts or []:
        account = normalize_paypal_phone_account(raw, fallback_otp_channel=fallback_otp_channel)
        if not account:
            continue
        key = (account["phone"], account["sms_url"], account["otp_channel"])
        if key in seen:
            continue
        seen.add(key)
        normalized_accounts.append(account)

    base_phone = str(base_profile.get("phone") or "").strip()
    base_sms_url = str(base_profile.get("sms_url") or "").strip()
    if not normalized_accounts and base_phone and base_sms_url:
        normalized_accounts.append(
            {
                "phone": base_phone,
                "sms_url": base_sms_url,
                "otp_channel": fallback_otp_channel,
            }
        )

    profiles: list[dict[str, str | bool]] = []
    total = len(normalized_accounts)
    for index, account in enumerate(normalized_accounts, start=1):
        profile = dict(base_profile)
        normalized_phone = normalize_phone(account["phone"])
        if not phone_value_valid(normalized_phone, country=str(profile.get("country") or "")):
            continue
        profile["phone"] = normalized_phone
        profile["sms_url"] = account["sms_url"]
        profile["otp_channel"] = account["otp_channel"]
        profile["phone_pool_index"] = str(index)
        profile["phone_pool_total"] = str(total)
        profiles.append(profile)
    if profiles:
        return profiles
    if (
        base_phone
        and base_sms_url
        and not phone_value_valid(base_phone, country=str(base_profile.get("country") or ""))
    ):
        return []
    return [dict(base_profile)]


def build_paypal_checkout_billing_payload(normalized: dict | None) -> dict[str, str]:
    normalized = dict(normalized or {})
    result = {
        "name": str(normalized.get("name") or "").strip(),
        "email": str(normalized.get("email") or "").strip(),
        "phone": str(normalized.get("phone") or "").strip(),
        "country": str(normalized.get("country") or "US").strip() or "US",
        "state": str(normalized.get("state") or "").strip(),
        "city": str(normalized.get("city") or "").strip(),
        "zip": str(normalized.get("postal_code") or "").strip(),
        "address1": str(normalized.get("address1") or "").strip(),
        "address2": str(normalized.get("address2") or "").strip(),
    }
    for key in ("card_number", "card_expiry", "card_cvv"):
        value = str(normalized.get(key) or "").strip()
        if value:
            result[key] = value
    return result


def paypal_billing_payload_complete(payload: dict[str, str]) -> bool:
    required = ("name", "country", "state", "city", "zip", "address1")
    return all(str(payload.get(key) or "").strip() for key in required)


def build_paypal_signup_profile(
    *,
    paypal_email: str = "",
    paypal_password: str = "",
    billing_payload: dict[str, str] | None = None,
    paypal_country: str = "",
    sms_url: str = "",
    otp_channel: str = "sms",
    paypal_card_number: str = "",
    paypal_card_expiry: str = "",
    paypal_card_cvv: str = "",
    country_billing_profiles: dict[str, dict] | None = None,
    normalize_country: Callable[[str], str],
    generate_email: Callable[[], str],
    generate_password: Callable[[], str],
    normalize_or_generate_card_number: Callable[[str], str],
    generate_card_expiry: Callable[[], str],
    generate_card_cvv: Callable[[str], str],
) -> dict[str, str | bool]:
    billing = dict(billing_payload or {})
    country_billing_profiles = dict(country_billing_profiles or {})
    original_country = normalize_country(str(billing.get("country") or "")) if billing.get("country") else ""
    forced_country = normalize_country(paypal_country) if paypal_country else ""
    if forced_country:
        defaults = country_billing_profiles.get(forced_country, {})
        billing["country"] = forced_country
        if original_country and original_country != forced_country:
            for key in ("name", "state", "city", "zip", "address1", "address2"):
                if defaults.get(key):
                    billing[key] = str(defaults.get(key) or "")
        for key in ("name", "state", "city", "zip", "address1", "address2"):
            if not str(billing.get(key) or "").strip() and defaults.get(key):
                billing[key] = str(defaults.get(key) or "")
    first_name = str(billing.get("first_name") or billing.get("firstName") or "").strip()
    last_name = str(billing.get("last_name") or billing.get("lastName") or "").strip()
    if not first_name or not last_name:
        split_first_name, split_last_name = split_paypal_name(str(billing.get("name") or ""))
        first_name = first_name or split_first_name
        last_name = last_name or split_last_name
    email = str(paypal_email or "").strip() or generate_email()
    password = str(paypal_password or "").strip() or generate_password()
    card_number = normalize_or_generate_card_number(
        str(paypal_card_number or "").strip() or first_payload_value(billing, "card_number", "cardNumber")
    )
    card_expiry = (
        str(paypal_card_expiry or "").strip()
        or first_payload_value(
            billing,
            "card_expiry",
            "cardExpiry",
            "expiry",
            "expiry_date",
        )
        or generate_card_expiry()
    )
    card_cvv = str(paypal_card_cvv or "").strip() or first_payload_value(billing, "card_cvv", "cardCvv", "cvv", "cvc")
    if not re.sub(r"\D+", "", card_cvv):
        card_cvv = generate_card_cvv(card_number)
    return {
        "email": email,
        "password": password,
        "generated_email": not bool(str(paypal_email or "").strip()),
        "generated_password": not bool(str(paypal_password or "").strip()),
        "phone": normalize_paypal_phone(str(billing.get("phone") or "")),
        "first_name": first_name,
        "last_name": last_name,
        "country": str(billing.get("country") or "US").strip() or "US",
        "state": str(billing.get("state") or "").strip(),
        "city": str(billing.get("city") or "").strip(),
        "zip": str(billing.get("zip") or "").strip(),
        "address1": str(billing.get("address1") or "").strip(),
        "address2": str(billing.get("address2") or "").strip(),
        "birth_date": str(billing.get("birth_date") or billing.get("birthDate") or "").strip(),
        "native_first_name": str(billing.get("native_first_name") or billing.get("nativeFirstName") or "").strip(),
        "native_last_name": str(billing.get("native_last_name") or billing.get("nativeLastName") or "").strip(),
        "sms_url": str(sms_url or "").strip(),
        "otp_channel": str(otp_channel or "sms").strip().lower() or "sms",
        "card_number": card_number,
        "card_expiry": normalize_paypal_card_expiry(card_expiry),
        "card_cvv": re.sub(r"\D+", "", card_cvv),
    }


def field_value_matches(
    expected: str,
    actual: str,
    *,
    field: str = "",
    state_name_to_code: dict[str, str],
    state_code_to_name: dict[str, str],
    prefecture_name_to_ja: dict[str, str],
    normalize_card_expiry,
    normalize_phone,
    phone_value_valid,
) -> bool:
    if field in {"card_number", "card_expiry", "card_cvv"}:
        return card_value_matches(
            expected,
            actual,
            field=field,
            normalize_card_expiry=normalize_card_expiry,
        )
    if field == "phone":
        expected_digits = re.sub(r"\D+", "", normalize_phone(str(expected or "")))
        actual_digits = re.sub(r"\D+", "", normalize_phone(str(actual or "")))
        return phone_value_valid(expected) and phone_value_valid(actual) and expected_digits == actual_digits
    if field == "state":
        return state_value_matches(
            expected,
            actual,
            state_name_to_code=state_name_to_code,
            state_code_to_name=state_code_to_name,
            prefecture_name_to_ja=prefecture_name_to_ja,
        )
    return value_matches(expected, actual)


def checkout_value_matches(
    key: str,
    expected: str,
    actual: str,
    *,
    state_name_to_code: dict[str, str],
    state_code_to_name: dict[str, str],
    prefecture_name_to_ja: dict[str, str],
) -> bool:
    expected_text = str(expected or "").strip()
    actual_text = str(actual or "").strip()
    if not expected_text:
        return True
    if key == "country":
        expected_upper = expected_text.upper()
        actual_upper = actual_text.upper()
        return expected_upper == actual_upper or (expected_upper == "US" and "UNITED STATES" in actual_upper)
    if key == "postal_code":
        return re.sub(r"\D+", "", expected_text) == re.sub(r"\D+", "", actual_text)
    if key == "state":
        return state_value_matches(
            expected_text,
            actual_text,
            state_name_to_code=state_name_to_code,
            state_code_to_name=state_code_to_name,
            prefecture_name_to_ja=prefecture_name_to_ja,
        )
    return value_matches(expected_text, actual_text)


def locator_tag_name(locator: Any) -> str:
    try:
        return str(locator.evaluate("el => el.tagName") or "").lower()
    except Exception:
        return ""


def dispatch_locator_value(
    locator: Any,
    value: str,
    *,
    disable_autocomplete: bool = False,
    focus: bool = True,
    timeout: int | None = None,
    legacy_value_arg: bool = False,
) -> bool:
    script = """(el, args) => {
      const options = args && typeof args === 'object' && !Array.isArray(args) ? args : {};
      const rawValue = Object.prototype.hasOwnProperty.call(options, 'value') ? options.value : args;
      const value = rawValue == null ? '' : String(rawValue);
      if (!el) return false;
      if (options.disableAutocomplete) {
        el.setAttribute('autocomplete', 'off');
        el.setAttribute('aria-autocomplete', 'none');
      }
      if (options.focus && typeof el.focus === 'function') el.focus();
      const tag = (el.tagName || '').toLowerCase();
      if (tag === 'select') {
        el.value = value;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        el.dispatchEvent(new Event('blur', { bubbles: true }));
        if (typeof el.blur === 'function') el.blur();
        return true;
      }
      const proto = tag === 'textarea' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
      if (descriptor && descriptor.set) descriptor.set.call(el, value);
      else el.value = value;
      let inputEvent;
      try {
        inputEvent = new InputEvent('input', { bubbles: true, inputType: 'insertText', data: value });
      } catch (_) {
        inputEvent = new Event('input', { bubbles: true });
      }
      el.dispatchEvent(inputEvent);
      el.dispatchEvent(new Event('change', { bubbles: true }));
      el.dispatchEvent(new Event('blur', { bubbles: true }));
      if (typeof el.blur === 'function') el.blur();
      return true;
    }"""
    try:
        kwargs = {"timeout": timeout} if timeout is not None else {}
        arg = (
            str(value or "")
            if legacy_value_arg
            else {
                "value": str(value or ""),
                "disableAutocomplete": bool(disable_autocomplete),
                "focus": bool(focus),
            }
        )
        return bool(
            locator.evaluate(
                script,
                arg,
                **kwargs,
            )
        )
    except Exception:
        return False


def set_locator_value(
    locator: Any,
    value: str,
    *,
    prefer_select_option: bool = False,
    fill_fallback: bool = False,
    disable_autocomplete: bool = False,
    dispatch_timeout: int | None = None,
    legacy_dispatch_arg: bool = False,
) -> bool:
    text = str(value or "")
    tag_name = locator_tag_name(locator)
    if tag_name == "select" and prefer_select_option:
        for option in ({"value": text}, {"label": text}):
            try:
                locator.select_option(**option, timeout=1000)
                return True
            except Exception:
                continue
        return False
    if dispatch_locator_value(
        locator,
        text,
        disable_autocomplete=disable_autocomplete,
        focus=not disable_autocomplete,
        timeout=dispatch_timeout,
        legacy_value_arg=legacy_dispatch_arg,
    ):
        return True
    if not fill_fallback:
        return False
    try:
        locator.click(timeout=1200)
    except Exception:
        pass
    try:
        locator.fill(text, timeout=1500)
        return True
    except Exception:
        return False


def select_state_locator_value(
    locator: Any,
    value: str,
    *,
    country: str = "",
    normalize_country,
    jp_prefecture_candidates,
    set_value,
) -> bool:
    normalized_country = normalize_country(country)
    candidates = jp_prefecture_candidates(value) if normalized_country == "JP" else [str(value or "").strip()]
    if not candidates:
        return False
    tag_name = locator_tag_name(locator)
    if tag_name == "select":
        for candidate in candidates:
            for option in ({"value": candidate}, {"label": candidate}):
                try:
                    locator.select_option(**option, timeout=1000)
                    return True
                except Exception:
                    continue
        try:
            selected = bool(
                locator.evaluate(
                    r"""(el, candidates) => {
                      const normalize = (value) => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
                      const wanted = candidates.map(normalize).filter(Boolean);
                      const option = Array.from(el.options || []).find((opt) => {
                        const value = normalize(opt.value);
                        const text = normalize(opt.textContent);
                        return wanted.some((item) => value === item || text === item || text.includes(item) || item.includes(text));
                      });
                      if (!option) return false;
                      el.value = option.value;
                      el.dispatchEvent(new Event('input', { bubbles: true }));
                      el.dispatchEvent(new Event('change', { bubbles: true }));
                      el.dispatchEvent(new Event('blur', { bubbles: true }));
                      return true;
                    }""",
                    candidates,
                )
            )
            if selected:
                return True
        except Exception:
            pass
        return False
    for candidate in candidates:
        if set_value(locator, candidate):
            return True
    return False


def type_locator_value(locator: Any, value: str) -> bool:
    try:
        locator.click(timeout=1200)
    except Exception:
        pass
    try:
        locator.press("Control+A", timeout=1000)
        locator.press("Backspace", timeout=1000)
    except Exception:
        pass
    try:
        locator.type(str(value or ""), delay=8, timeout=6000)
        return True
    except Exception:
        return False


def set_verified_locator_value(
    locator: Any,
    value: str,
    *,
    field: str = "",
    setters,
    read_value,
    matches,
    sleep=time.sleep,
) -> bool:
    def verified() -> bool:
        actual = read_value(locator)
        return matches(value, actual, field=field)

    for setter in setters:
        if setter(locator, value):
            sleep(0.15)
            if verified():
                return True
    return False


def fast_autofill_fields(
    frames: list[Any], fields: dict[str, str], *, fast_selectors: dict[str, list[str]]
) -> list[str]:
    fast_fields = {
        key: str(value or "")
        for key, value in (fields or {}).items()
        if key != "country" and key in fast_selectors and str(value or "").strip()
    }
    if not fast_fields:
        return []
    script = """({ fields, selectors }) => {
      const filled = [];
      const isVisible = (node) => Boolean(node && (node.offsetParent || node.getClientRects?.().length));
      const setValue = (el, value) => {
        if (!el || el.disabled || el.readOnly || !isVisible(el)) return false;
        const tag = String(el.tagName || '').toLowerCase();
        if (tag === 'select') {
          const expected = String(value || '').trim().toLowerCase();
          const option = Array.from(el.options || []).find((opt) => {
            const optValue = String(opt.value || '').trim().toLowerCase();
            const optLabel = String(opt.textContent || opt.label || '').trim().toLowerCase();
            return optValue === expected || optLabel === expected || optLabel.includes(expected);
          });
          if (!option) return false;
          el.value = option.value;
        } else {
          el.focus();
          const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
          const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
          if (setter) setter.call(el, String(value));
          else el.value = String(value);
        }
        el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: String(value || '') }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        el.dispatchEvent(new Event('blur', { bubbles: true }));
        return true;
      };
      for (const [key, value] of Object.entries(fields || {})) {
        for (const selector of selectors[key] || []) {
          let node = null;
          try {
            node = document.querySelector(selector);
          } catch {
            node = null;
          }
          if (setValue(node, value)) {
            filled.push(key);
            break;
          }
        }
      }
      return filled;
    }"""
    filled: set[str] = set()
    for frame in frames:
        missing = {key: value for key, value in fast_fields.items() if key not in filled}
        if not missing:
            break
        try:
            result = frame.evaluate(script, {"fields": missing, "selectors": fast_selectors})
        except Exception:
            continue
        for key in result or []:
            if str(key) in missing:
                filled.add(str(key))
    return list(filled)


def read_checkout_field_value(*, key: str, selectors: dict[str, list[str]], visible_locator, read_value) -> str:
    locator = visible_locator(selectors.get(key) or [], timeout_ms=800)
    if not locator:
        return ""
    try:
        return str(
            locator.evaluate(
                """(el) => {
                  if (el instanceof HTMLSelectElement) {
                    const selected = el.selectedOptions && el.selectedOptions[0];
                    return el.value || (selected ? selected.textContent : '') || '';
                  }
                  return el.value || el.textContent || '';
                }"""
            )
            or ""
        ).strip()
    except Exception:
        return read_value(locator)


def autofill_checkout_fields(
    payload: dict | None,
    *,
    current_url: str,
    selectors: dict[str, list[str]],
    normalize_payload,
    autofill_allowed,
    suppress_autocomplete,
    dismiss_autocomplete,
    fast_autofill,
    read_checkout_value,
    checkout_value_matches,
    visible_locator,
    set_value,
    progress=None,
    sleep=time.sleep,
) -> dict:
    fields = normalize_payload(payload)
    if not fields or not autofill_allowed(current_url):
        return {"filled": [], "skipped": list(fields.keys())}

    filled: list[str] = []
    skipped: list[str] = []
    suppress_autocomplete()
    ordered_keys = [
        "country",
        "name",
        "email",
        "phone",
        "address1",
        "address2",
        "city",
        "state",
        "postal_code",
    ]
    ordered_fields = [(key, fields[key]) for key in ordered_keys if key in fields]
    ordered_fields.extend((key, value) for key, value in fields.items() if key not in ordered_keys)
    address1_locator = None
    fast_attempted = set(fast_autofill(dict(ordered_fields)))
    fast_verified = {
        key
        for key in fast_attempted
        if checkout_value_matches(key, str(fields.get(key) or ""), read_checkout_value(key))
    }
    for key, value in ordered_fields:
        if key in fast_verified:
            filled.append(key)
            continue
        field_selectors = selectors.get(key) or []
        if not field_selectors:
            skipped.append(key)
            continue
        locator = visible_locator(field_selectors, timeout_ms=1200)
        if locator and set_value(locator, value):
            filled.append(key)
            if key == "country":
                sleep(0.8)
            if key == "address1":
                address1_locator = locator
                dismiss_autocomplete(locator)
        else:
            skipped.append(key)
    dismiss_autocomplete(address1_locator)

    if filled and progress:
        progress(filled, current_url)
    return {"filled": filled, "skipped": skipped}


def checkout_billing_required_fields(billing_payload: dict[str, Any]) -> dict[str, str]:
    return {
        "country": str(billing_payload.get("country") or "US").strip() or "US",
        "address1": str(billing_payload.get("address1") or "").strip(),
        "city": str(billing_payload.get("city") or "").strip(),
        "state": str(billing_payload.get("state") or "").strip(),
        "postal_code": str(billing_payload.get("zip") or billing_payload.get("postal_code") or "").strip(),
    }


def fill_checkout_billing_form(
    billing_payload: dict[str, Any],
    *,
    suppress_autocomplete,
    autofill_checkout,
    read_checkout_value,
    checkout_value_matches,
    capture_failure,
    progress=None,
    logger: logging.Logger | None = None,
    log_prefix: str = "[payment_form_fields]",
    sleep=time.sleep,
    max_attempts: int = 8,
) -> tuple[bool, str]:
    if callable(progress):
        progress("fill_billing_info")
    required = checkout_billing_required_fields(billing_payload)
    if not all(required.values()):
        return False, "账单地址缺少国家/地址/城市/州/邮编"

    last_values: dict[str, str] = {}
    for attempt in range(1, max(1, int(max_attempts)) + 1):
        suppress_autocomplete()
        autofill_checkout(billing_payload)
        sleep(0.25)
        last_values = {key: read_checkout_value(key) for key in required}
        missing = [
            key
            for key, expected in required.items()
            if not checkout_value_matches(key, expected, last_values.get(key, ""))
        ]
        if not missing:
            return True, ""
        if logger:
            logger.info(
                "%s PayPal checkout billing readback mismatch attempt=%s missing=%s values=%s expected=%s",
                log_prefix,
                attempt,
                missing,
                last_values,
                required,
            )
        sleep(0.25)

    capture_failure()
    return False, f"地址字段校验失败: 期望={required!r}, 实际={last_values!r}"


def fill_signup_required_fields(
    field_specs: list[tuple[str, list[str], str, str]],
    *,
    visible_locator,
    set_verified_value,
    read_value,
    optional_skip_fields: set[str] | None = None,
    field_locators: dict[str, Any] | None = None,
    logger: logging.Logger | None = None,
    log_prefix: str = "[payment_form_fields]",
    timeout_ms: int = 1200,
) -> tuple[bool, str, dict[str, Any]]:
    optional_skip_fields = optional_skip_fields or set()
    field_locators = field_locators if field_locators is not None else {}
    for key, selectors, value, label in field_specs:
        if not value:
            if key in optional_skip_fields:
                continue
            return False, f"{label} 为空", field_locators
        locator = visible_locator(selectors, timeout_ms=timeout_ms)
        if locator is None:
            if key in optional_skip_fields:
                if logger:
                    logger.info("%s field '%s' not visible, skipping (likely already submitted)", log_prefix, key)
                continue
            return False, f"未找到 {label} 输入框", field_locators
        if not set_verified_value(locator, value, field=key):
            actual = read_value(locator)
            return False, f"{label} 填写后校验失败: 期望={value!r}, 实际={actual!r}", field_locators
        field_locators[label] = locator
    return True, "", field_locators


def fill_signup_address_fields(
    address_specs: list[tuple[str, list[str], str, str]],
    *,
    country: str,
    suppress_autocomplete,
    dismiss_autocomplete,
    visible_locator,
    set_verified_value,
    set_state_value,
    read_value,
    field_value_matches,
    set_value,
    field_locators: dict[str, Any] | None = None,
    sleep=time.sleep,
    timeout_ms: int = 1200,
) -> tuple[bool, str, dict[str, Any]]:
    field_locators = field_locators if field_locators is not None else {}
    suppress_autocomplete()
    for key, selectors, value, label in address_specs:
        if not value:
            return False, f"{label} 为空", field_locators
        locator = visible_locator(selectors, timeout_ms=timeout_ms)
        if locator is None:
            return False, f"未找到 {label} 输入框", field_locators
        if key == "state":
            did_set = set_state_value(locator, value, country=country)
            sleep(0.15)
            verified = field_value_matches(value, read_value(locator), field=key)
        else:
            did_set = set_verified_value(locator, value, field=key)
            verified = did_set
        if not did_set or not verified:
            actual = read_value(locator)
            return False, f"{label} 填写后校验失败: 期望={value!r}, 实际={actual!r}", field_locators
        field_locators[key] = locator
        if key == "address1":
            dismiss_autocomplete(locator)
            sleep(0.15)

    dismiss_autocomplete(field_locators.get("address1"))
    for key, _selectors, expected, label in address_specs:
        locator = field_locators.get(key)
        actual = read_value(locator)
        if field_value_matches(expected, actual, field=key):
            continue
        if key == "state":
            rewritten = set_state_value(locator, expected, country=country)
        else:
            rewritten = set_value(locator, expected)
        if not rewritten:
            return False, f"{label} 自动补全后被改写，且重写失败", field_locators
        if key == "address1":
            dismiss_autocomplete(locator)
        sleep(0.15)
        actual = read_value(locator)
        if not field_value_matches(expected, actual, field=key):
            return False, f"{label} 自动补全后校验失败: 期望={expected!r}, 实际={actual!r}", field_locators
    return True, "", field_locators


def fill_signup_birth_date_if_needed(
    signup_profile: dict[str, Any],
    *,
    country: str,
    default_birth_date: str,
    birth_date_selectors: list[str],
    normalize_country,
    visible_locator,
    set_value,
    read_value,
    logger: logging.Logger | None = None,
    log_prefix: str = "[payment_form_fields]",
    sleep=time.sleep,
    timeout_ms: int = 1200,
) -> tuple[bool, str]:
    if normalize_country(country) != "JP":
        return True, ""
    birth_date = str(signup_profile.get("birth_date") or signup_profile.get("birthDate") or default_birth_date).strip()
    birth_locator = visible_locator(birth_date_selectors, timeout_ms=timeout_ms)
    if birth_locator is None:
        if logger:
            logger.info("%s JP birth date input not found by direct selectors; DOM fallback will try", log_prefix)
        return True, ""
    set_value(birth_locator, birth_date)
    sleep(0.2)
    actual_birth = read_value(birth_locator)
    if re.sub(r"\D+", "", actual_birth) != re.sub(r"\D+", "", birth_date):
        return False, f"PayPal 生年月日填写后校验失败: 期望={birth_date!r}, 实际={actual_birth!r}"
    return True, ""


def validate_signup_dom_result(
    dom_result: dict[str, Any],
    *,
    country: str,
    optional_skip_fields: set[str] | None = None,
    normalize_country,
    jp_required_fields: tuple[str, ...] = ("birth_date", "native_first_name", "native_last_name"),
    logger: logging.Logger | None = None,
    log_prefix: str = "[payment_form_fields]",
) -> tuple[bool, str, list[str]]:
    optional_skip_fields = optional_skip_fields or set()
    still_missing = [
        str(item)
        for item in dom_result.get("stillMissing") or []
        if str(item) and str(item) not in optional_skip_fields
    ]
    if still_missing and logger:
        logger.info(
            "%s PayPal signup DOM validation could not confirm fields: %s",
            log_prefix,
            ", ".join(still_missing),
        )
    if normalize_country(country) == "JP":
        jp_missing = [field for field in jp_required_fields if field in still_missing]
        if jp_missing:
            return False, f"PayPal 日区注册字段填写后校验失败: {', '.join(jp_missing)}", still_missing
    return True, "", still_missing


def build_signup_visible_form_payload(
    signup_profile: dict[str, Any],
    *,
    normalize_country,
    default_birth_date: str,
    default_native_first_name: str,
    default_native_last_name: str,
) -> dict[str, str]:
    payload = {
        "email": str(signup_profile.get("email") or "").strip(),
        "phone": str(signup_profile.get("phone") or "").strip(),
        "card_number": re.sub(r"\D+", "", str(signup_profile.get("card_number") or "")),
        "card_expiry": str(signup_profile.get("card_expiry") or "").strip(),
        "card_cvv": re.sub(r"\D+", "", str(signup_profile.get("card_cvv") or "")),
        "password": str(signup_profile.get("password") or "").strip(),
        "first_name": str(signup_profile.get("first_name") or "").strip(),
        "last_name": str(signup_profile.get("last_name") or "").strip(),
        "country": str(signup_profile.get("country") or "US").strip() or "US",
        "state": str(signup_profile.get("state") or "").strip(),
        "city": str(signup_profile.get("city") or "").strip(),
        "zip": str(signup_profile.get("zip") or "").strip(),
        "address1": str(signup_profile.get("address1") or "").strip(),
        "address2": str(signup_profile.get("address2") or "").strip(),
    }
    if normalize_country(str(payload.get("country") or "")) == "JP":
        payload["birth_date"] = str(
            signup_profile.get("birth_date") or signup_profile.get("birthDate") or default_birth_date
        ).strip()
        payload["native_first_name"] = str(
            signup_profile.get("native_first_name")
            or signup_profile.get("nativeFirstName")
            or default_native_first_name
        ).strip()
        payload["native_last_name"] = str(
            signup_profile.get("native_last_name") or signup_profile.get("nativeLastName") or default_native_last_name
        ).strip()
    return payload


def select_country_locator(
    locator: Any,
    country: str,
    *,
    normalize_country,
    country_labels: dict[str, tuple[str, ...]],
    fallback_options: list[str] | tuple[str, ...] = ("US", "United States", "United States of America"),
    sleep=time.sleep,
    timeout_ms: int = 1200,
) -> bool:
    normalized_country = normalize_country(country)
    options = [normalized_country]
    options.extend(country_labels.get(normalized_country, ()))
    if normalized_country != "US":
        options.extend(fallback_options)
    for option in options:
        if not option:
            continue
        try:
            locator.select_option(value=option, timeout=timeout_ms)
            sleep(1.0)
            return True
        except Exception:
            pass
        try:
            locator.select_option(label=option, timeout=timeout_ms)
            sleep(1.0)
            return True
        except Exception:
            pass
    return False


def verify_signup_required_values(
    check_specs: list[tuple[str, list[str], str, str]],
    *,
    country: str,
    phone_value_valid,
    visible_locator,
    read_value,
    field_value_matches,
    timeout_ms: int = 600,
) -> tuple[bool, str]:
    for field, selectors, expected, label in check_specs:
        if field == "phone" and not phone_value_valid(expected, country=country):
            return False, f"{label} 无效: {expected!r}"
        locator = visible_locator(selectors, timeout_ms=timeout_ms)
        if locator is None:
            return False, f"提交前未找到 {label} 输入框"
        actual = read_value(locator)
        if not field_value_matches(expected, actual, field=field):
            return False, f"提交前 {label} 校验失败: 期望={expected!r}, 实际={actual!r}"
    return True, ""


def verify_paypal_signup_required_values(
    signup_profile: dict[str, Any],
    *,
    phone_selectors: list[str],
    card_number_selectors: list[str],
    card_expiry_selectors: list[str],
    card_cvv_selectors: list[str],
    password_selectors: list[str],
    first_name_selectors: list[str],
    last_name_selectors: list[str],
    address1_selectors: list[str],
    city_selectors: list[str],
    postal_selectors: list[str],
    state_selectors: list[str],
    phone_value_valid,
    visible_locator,
    read_value,
    field_value_matches,
) -> tuple[bool, str]:
    check_specs = [
        ("phone", phone_selectors, str(signup_profile.get("phone") or ""), "PayPal 注册手机号"),
        ("card_number", card_number_selectors, str(signup_profile.get("card_number") or ""), "PayPal 卡号"),
        ("card_expiry", card_expiry_selectors, str(signup_profile.get("card_expiry") or ""), "PayPal 卡有效期"),
        ("card_cvv", card_cvv_selectors, str(signup_profile.get("card_cvv") or ""), "PayPal 卡 CVV"),
        ("password", password_selectors, str(signup_profile.get("password") or ""), "PayPal 注册密码"),
        ("first_name", first_name_selectors, str(signup_profile.get("first_name") or ""), "PayPal 名"),
        ("last_name", last_name_selectors, str(signup_profile.get("last_name") or ""), "PayPal 姓"),
        ("address1", address1_selectors, str(signup_profile.get("address1") or ""), "PayPal 账单地址"),
        ("city", city_selectors, str(signup_profile.get("city") or ""), "PayPal 城市"),
        ("zip", postal_selectors, str(signup_profile.get("zip") or ""), "PayPal 邮编"),
        ("state", state_selectors, str(signup_profile.get("state") or ""), "PayPal 州/都道府县"),
    ]
    return verify_signup_required_values(
        check_specs,
        country=str(signup_profile.get("country") or ""),
        phone_value_valid=phone_value_valid,
        visible_locator=visible_locator,
        read_value=read_value,
        field_value_matches=field_value_matches,
    )


def set_first_visible_value_with_locator(
    *,
    selectors: list[str],
    value: str,
    visible_locator,
    set_value,
    timeout_ms: int = 1200,
) -> tuple[bool, Any]:
    locator = visible_locator(selectors, timeout_ms=timeout_ms)
    if not locator:
        return False, None
    return bool(set_value(locator, value)), locator


def set_first_visible_value(
    *,
    selectors: list[str],
    value: str,
    visible_locator,
    set_value,
    timeout_ms: int = 1200,
) -> bool:
    ok, _locator = set_first_visible_value_with_locator(
        selectors=selectors,
        value=value,
        visible_locator=visible_locator,
        set_value=set_value,
        timeout_ms=timeout_ms,
    )
    return ok


def replace_signup_field_values(
    field_specs: list[tuple[str, list[str], str, str]],
    *,
    set_first_visible_value_with_locator,
    set_verified_value,
    read_value,
    missing_message=None,
    mismatch_message=None,
) -> tuple[bool, str]:
    for key, selectors, value, label in field_specs:
        ok, locator = set_first_visible_value_with_locator(selectors, value)
        if not ok or locator is None:
            if callable(missing_message):
                return False, missing_message(label)
            return False, f"未找到 {label} 输入框"
        if not set_verified_value(locator, value, field=key):
            actual = read_value(locator)
            if callable(mismatch_message):
                return False, mismatch_message(label, value, actual)
            return False, f"{label} 替换后校验失败: 期望={value!r}, 实际={actual!r}"
    return True, ""


def replace_paypal_signup_phone(
    api: Any,
    *,
    signup_profile: dict[str, Any],
    phone_selectors: list[str],
    phone_value_valid,
    set_first_visible_value_with_locator,
    set_verified_value,
    read_value,
    progress_event,
    on_progress=None,
) -> tuple[bool, str]:
    phone = str(signup_profile.get("phone") or "").strip()
    if not phone_value_valid(phone, country=str(signup_profile.get("country") or "")):
        return False, f"PayPal 注册手机号无效: {phone!r}"
    ok, error = replace_signup_field_values(
        [("phone", phone_selectors, phone, "PayPal 注册手机号")],
        set_first_visible_value_with_locator=set_first_visible_value_with_locator,
        set_verified_value=set_verified_value,
        read_value=read_value,
        missing_message=lambda label: f"未找到 {label}输入框",
        mismatch_message=lambda label, expected, actual: f"{label}替换后校验失败: 期望={expected!r}, 实际={actual!r}",
    )
    if not ok:
        return False, error
    if on_progress:
        on_progress(
            progress_event(
                "paypal_replace_signup_phone",
                url=getattr(api.page, "url", ""),
                phone=phone,
            )
        )
    return True, ""


def replace_paypal_signup_card(
    api: Any,
    *,
    signup_profile: dict[str, Any],
    card_number_selectors: list[str],
    card_expiry_selectors: list[str],
    card_cvv_selectors: list[str],
    generate_card_number,
    generate_card_expiry,
    generate_card_cvv,
    set_first_visible_value_with_locator,
    set_verified_value,
    read_value,
    progress_event,
    on_progress=None,
    sleep=time.sleep,
) -> tuple[bool, str]:
    card_number = generate_card_number()
    card_expiry = generate_card_expiry()
    card_cvv = generate_card_cvv(card_number)
    signup_profile["card_number"] = card_number
    signup_profile["card_expiry"] = card_expiry
    signup_profile["card_cvv"] = card_cvv
    if on_progress:
        on_progress(
            progress_event(
                "paypal_card_rejected_retry",
                url=getattr(api.page, "url", ""),
            )
        )
    fields = [
        ("card_number", card_number_selectors, card_number, "PayPal 卡号"),
        ("card_expiry", card_expiry_selectors, card_expiry, "PayPal 卡有效期"),
        ("card_cvv", card_cvv_selectors, card_cvv, "PayPal 卡 CVV"),
    ]
    ok, error = replace_signup_field_values(
        fields,
        set_first_visible_value_with_locator=set_first_visible_value_with_locator,
        set_verified_value=set_verified_value,
        read_value=read_value,
    )
    if not ok:
        return False, error
    sleep(0.5)
    return True, ""


def retry_paypal_signup_after_card_rejected(
    api: Any,
    *,
    signup_profile: dict[str, Any],
    state: dict[str, Any],
    card_retry_count: int,
    current_url: str,
    replace_signup_card,
    ensure_phone_lock,
    release_phone_lock,
    verify_required_values,
    click_submit,
    progress_event,
    on_progress=None,
    now=time.time,
    sleep=time.sleep,
) -> tuple[bool, str, bool]:
    release_phone_lock(state, on_progress=on_progress)
    if card_retry_count >= 5:
        return False, "PayPal 连续拒绝卡片，已停止换卡重试", False
    ok, error = replace_signup_card(api, signup_profile=signup_profile, on_progress=on_progress)
    if not ok:
        return False, error, True
    if on_progress:
        on_progress(
            progress_event(
                "paypal_submit_signup",
                url=current_url,
                phone=str(signup_profile.get("phone") or ""),
            )
        )
    ok, error = ensure_phone_lock(state, signup_profile=signup_profile, on_progress=on_progress)
    if not ok:
        return False, error, False
    ready, ready_error = verify_required_values(api, signup_profile)
    if not ready:
        release_phone_lock(state, on_progress=on_progress)
        return False, ready_error, True
    if not click_submit(api):
        release_phone_lock(state, on_progress=on_progress)
        return False, "未找到 PayPal 注册提交按钮", False
    state["signup_submitted"] = True
    state["signup_submitted_at"] = now()
    state["card_retry_count"] = card_retry_count + 1
    sleep(2.0)
    return True, "", True


def retry_paypal_signup_after_phone_rejected(
    api: Any,
    *,
    signup_profile: dict[str, Any],
    state: dict[str, Any],
    phone_key: str,
    submitted_phone_keys: set[str],
    current_url: str,
    ensure_phone_lock,
    replace_signup_phone,
    release_phone_lock,
    verify_required_values,
    click_submit,
    progress_event,
    on_progress=None,
    now=time.time,
    sleep=time.sleep,
) -> tuple[bool, str, bool]:
    ok, error = ensure_phone_lock(state, signup_profile=signup_profile, on_progress=on_progress)
    if not ok:
        return False, error, False
    ok, error = replace_signup_phone(api, signup_profile=signup_profile, on_progress=on_progress)
    if not ok:
        release_phone_lock(state, on_progress=on_progress)
        return False, error, True
    if on_progress:
        on_progress(
            progress_event(
                "paypal_submit_signup",
                url=current_url,
                phone=str(signup_profile.get("phone") or ""),
            )
        )
    ready, ready_error = verify_required_values(api, signup_profile)
    if not ready:
        release_phone_lock(state, on_progress=on_progress)
        return False, ready_error, True
    if not click_submit(api):
        release_phone_lock(state, on_progress=on_progress)
        return False, "未找到 PayPal 注册提交按钮", False
    state["signup_submitted"] = True
    state["signup_submitted_at"] = now()
    state["phone_only_retry"] = False
    if phone_key:
        submitted_phone_keys.add(phone_key)
    sleep(2.0)
    return True, "", True


def submit_paypal_signup_registration_form(
    api: Any,
    *,
    signup_profile: dict[str, Any],
    state: dict[str, Any],
    phone_key: str,
    submitted_phone_keys: set[str],
    current_url: str,
    wait_dom_loaded,
    ensure_phone_lock,
    fill_signup_form,
    release_phone_lock,
    verify_required_values,
    click_submit,
    progress_event,
    on_progress=None,
    logger: logging.Logger | None = None,
    now=time.time,
    sleep=time.sleep,
) -> tuple[bool, str, bool]:
    wait_dom_loaded(api)
    sleep(1.5)
    ok, error = ensure_phone_lock(state, signup_profile=signup_profile, on_progress=on_progress)
    if not ok:
        return False, error, False
    ok, error = fill_signup_form(api, signup_profile=signup_profile, on_progress=on_progress)
    if not ok:
        release_phone_lock(state, on_progress=on_progress)
        fill_retry_count = int(state.get("_fill_retry_count") or 0)
        if fill_retry_count < 3:
            state["_fill_retry_count"] = fill_retry_count + 1
            if logger:
                logger.info("[paypal_signup] fill form failed (%s), will retry (%d/3)", error, fill_retry_count + 1)
            sleep(3.0)
            return True, "", True
        return False, error, True
    state["_fill_retry_count"] = 0
    if on_progress:
        on_progress(
            progress_event(
                "paypal_submit_signup",
                url=current_url,
                phone=str(signup_profile.get("phone") or ""),
            )
        )
    ready, ready_error = verify_required_values(api, signup_profile)
    if not ready:
        release_phone_lock(state, on_progress=on_progress)
        return False, ready_error, True
    if not click_submit(api):
        release_phone_lock(state, on_progress=on_progress)
        return False, "未找到 PayPal 注册提交按钮", False
    state["signup_submitted"] = True
    state["signup_submitted_at"] = now()
    if phone_key:
        submitted_phone_keys.add(phone_key)
    sleep(2.0)
    return True, "", True


def paypal_signup_visible_validation_error(text: str) -> str:
    lowered = str(text or "").lower()
    hints = (
        "正しい日付を入力してください",
        "漢字を使用してください",
        "入力内容を確認してください",
        "please enter a valid date",
        "please check your information",
    )
    matched = [hint for hint in hints if hint.lower() in lowered]
    return " / ".join(matched)


def paypal_signup_otp_text_hint(text: str, *, loose: bool = False) -> bool:
    return payment_checkout_state.paypal_signup_otp_text_hint(text, loose=loose)


def paypal_signup_otp_entry_text_hint(text: str) -> bool:
    return payment_checkout_state.paypal_signup_otp_entry_text_hint(text)


def paypal_signup_registration_text_hint(text: str) -> bool:
    return payment_checkout_state.paypal_signup_registration_text_hint(text)


def paypal_signup_registration_form_text_visible(text: str) -> bool:
    return payment_checkout_state.paypal_signup_registration_form_text_visible(text)


def paypal_login_text_hint(text: str) -> bool:
    return payment_checkout_state.paypal_login_text_hint(text)


def paypal_passkey_text_hint(text: str) -> bool:
    return payment_checkout_state.paypal_passkey_text_hint(text)


def paypal_approve_text_hint(text: str) -> bool:
    return payment_checkout_state.paypal_approve_text_hint(text)


def text_matches_any_hint(text: str, hints: tuple[str, ...] | list[str]) -> bool:
    return payment_checkout_state.text_matches_any_hint(text, hints)


def paypal_phone_rejected_text_hint(text: str, *, hints: tuple[str, ...] | list[str]) -> bool:
    return payment_checkout_state.paypal_phone_rejected_text_hint(text, hints=hints)


def paypal_card_rejected_text_hint(text: str, *, hints: tuple[str, ...] | list[str]) -> bool:
    return payment_checkout_state.paypal_card_rejected_text_hint(text, hints=hints)


def read_locator_value(locator: Any, *, prefer_select_text: bool = False) -> str:
    if prefer_select_text and locator_tag_name(locator) == "select":
        try:
            text = str(
                locator.evaluate(
                    "el => el.selectedOptions && el.selectedOptions[0] ? (el.selectedOptions[0].textContent || '') : ''"
                )
                or ""
            ).strip()
            if text:
                return text
        except Exception:
            pass
    try:
        return str(locator.input_value(timeout=800) or "").strip()
    except Exception:
        pass
    try:
        return str(locator.text_content(timeout=800) or "").strip()
    except Exception:
        return ""


def visible_locator_in_frames(api: Any, selectors: list[str], timeout_ms: int = 1000):
    helper = getattr(api, "_visible_locator_in_frames", None)
    if callable(helper):
        return helper(selectors, timeout_ms=timeout_ms)
    return None


def attached_locator_in_frames(frames: list[Any], selectors: list[str], timeout_ms: int = 500):
    for frame in frames:
        for selector in selectors:
            try:
                locator = frame.locator(selector).first
                locator.wait_for(state="attached", timeout=timeout_ms)
                return locator
            except Exception:
                continue
    return None


def scroll_locator_into_view(
    locator: Any,
    label: str,
    *,
    logger: logging.Logger | None = None,
    log_prefix: str = "[payment_form_fields]",
    timeout: int = 2500,
) -> bool:
    try:
        locator.scroll_into_view_if_needed(timeout=timeout)
        if logger:
            logger.info("%s 已滚动到字段 %s", log_prefix, label)
        return True
    except Exception as exc:
        if logger:
            logger.info("%s 滚动到字段 %s 失败: %s", log_prefix, label, exc)
        return False


def locator_by_placeholder_or_label_with_state(
    frames: list[Any],
    placeholders: list[str],
    labels: list[str],
    *,
    timeout_ms: int = 1200,
    require_visible: bool = True,
):
    state = "visible" if require_visible else "attached"
    per_try_timeout = max(80, min(180, timeout_ms))
    for frame in frames:
        for text in placeholders:
            try:
                locator = frame.get_by_placeholder(text, exact=True).first
                locator.wait_for(state=state, timeout=per_try_timeout)
                return locator
            except Exception:
                continue
        for text in placeholders:
            try:
                locator = frame.get_by_placeholder(re.compile(re.escape(text), re.IGNORECASE)).first
                locator.wait_for(state=state, timeout=per_try_timeout)
                return locator
            except Exception:
                continue
        for text in labels:
            try:
                locator = frame.get_by_label(text, exact=True).first
                locator.wait_for(state=state, timeout=per_try_timeout)
                return locator
            except Exception:
                continue
        for text in labels:
            try:
                locator = frame.get_by_label(re.compile(re.escape(text), re.IGNORECASE)).first
                locator.wait_for(state=state, timeout=per_try_timeout)
                return locator
            except Exception:
                continue
    return None


def locator_by_placeholder_or_label(
    frames: list[Any],
    placeholders: list[str],
    labels: list[str],
    *,
    timeout_ms: int = 1200,
):
    return locator_by_placeholder_or_label_with_state(
        frames,
        placeholders,
        labels,
        timeout_ms=timeout_ms,
        require_visible=True,
    )


def resolve_locator_in_frames(
    frames: list[Any],
    selectors: list[str],
    *,
    placeholders: list[str] | None = None,
    labels: list[str] | None = None,
    timeout_ms: int = 1200,
    require_visible: bool = True,
):
    state = "visible" if require_visible else "attached"
    for frame in frames:
        for selector in selectors:
            try:
                candidate = frame.locator(selector).first
                candidate.wait_for(state=state, timeout=min(400, timeout_ms))
                return candidate
            except Exception:
                continue
    if placeholders or labels:
        return locator_by_placeholder_or_label_with_state(
            frames,
            placeholders or [],
            labels or [],
            timeout_ms=timeout_ms,
            require_visible=require_visible,
        )
    return None


def score_billing_frame(frame: Any) -> int:
    script = """() => {
      const texts = [];
      for (const node of document.querySelectorAll('input,select,textarea,label,[aria-label]')) {
        texts.push(node.getAttribute('placeholder') || '');
        texts.push(node.getAttribute('aria-label') || '');
        texts.push(node.getAttribute('autocomplete') || '');
        texts.push(node.getAttribute('name') || '');
        texts.push(node.innerText || node.textContent || '');
      }
      const haystack = texts.join('\\n').toLowerCase();
      const tests = [
        /全名|full name|\\bname\\b/,
        /国家或地区|country/,
        /地址第\\s*1\\s*行|address line 1|street address|address-line1/,
        /城市|city|address-level2/,
        /州|state|province|address-level1/,
        /邮政编码|postal|zip/
      ];
      return tests.reduce((score, pattern) => score + (pattern.test(haystack) ? 1 : 0), 0);
    }"""
    try:
        return int(frame.evaluate(script) or 0)
    except Exception:
        return 0


def _summarize_frame_url(frame: Any, *, safe_url_summary) -> str:
    frame_url = str(getattr(frame, "url", "") or "")
    if len(frame_url) > 180:
        frame_url = frame_url[:180] + "..."
    return safe_url_summary(frame_url)


def find_billing_form_frames(
    frames_provider,
    *,
    timeout_seconds: int = 5,
    logger: logging.Logger | None = None,
    log_prefix: str = "[payment_form_fields]",
    safe_url_summary=str,
    sleep=time.sleep,
) -> list[Any] | None:
    deadline = time.time() + timeout_seconds
    best_frames = []
    best_score = 0
    while time.time() < deadline:
        scored = []
        for frame in frames_provider():
            score = score_billing_frame(frame)
            if score:
                scored.append((score, frame))
        if scored:
            scored.sort(key=lambda item: item[0], reverse=True)
            best_score, best_frame = scored[0]
            best_frames = [best_frame]
            if best_score >= 3:
                if logger:
                    logger.info(
                        "%s 已锁定账单表单 frame，score=%s url=%s",
                        log_prefix,
                        best_score,
                        _summarize_frame_url(best_frame, safe_url_summary=safe_url_summary),
                    )
                return best_frames
        sleep(0.3)
    if best_frames:
        if logger:
            logger.info(
                "%s 使用最高分账单 frame，score=%s url=%s",
                log_prefix,
                best_score,
                _summarize_frame_url(best_frames[0], safe_url_summary=safe_url_summary),
            )
        return best_frames
    if logger:
        logger.info("%s 未能锁定账单 frame，回退到全页面 frame 搜索", log_prefix)
    return None


def scroll_to_billing_section(
    page: Any,
    *,
    visible_locator,
    selectors: list[str] | None = None,
    logger: logging.Logger | None = None,
    log_prefix: str = "[payment_form_fields]",
) -> bool:
    section_selectors = selectors or [
        "text=账单地址",
        "text=Billing address",
        "text=Billing Address",
    ]
    locator = visible_locator(section_selectors, timeout_ms=2000)
    if locator:
        try:
            locator.scroll_into_view_if_needed(timeout=2000)
            if logger:
                logger.info("%s 已滚动到账单地址区域", log_prefix)
            return True
        except Exception:
            pass
    try:
        page.evaluate(
            """() => {
              const nodes = Array.from(document.querySelectorAll('h1,h2,h3,h4,div,span,label'));
              const hit = nodes.find((node) => /账单地址|billing address/i.test((node.innerText || node.textContent || '').trim()));
              if (hit) hit.scrollIntoView({ behavior: 'instant', block: 'center' });
            }"""
        )
        if logger:
            logger.info("%s 已尝试滚动到账单地址区域", log_prefix)
        return True
    except Exception:
        return False


def fill_billing_page_field(
    *,
    selectors: list[str],
    value: str,
    label: str,
    resolve_locator,
    optional: bool = False,
    screenshot_stage: str = "",
    placeholders: list[str] | None = None,
    labels: list[str] | None = None,
    capture_screenshot=None,
    scroll_locator=scroll_locator_into_view,
    progress=None,
    logger: logging.Logger | None = None,
    log_prefix: str = "[payment_form_fields]",
    read_value=read_locator_value,
    matches=value_matches,
    set_value=set_locator_value,
    looks_like_phone_number=lambda _value: False,
    sleep=time.sleep,
) -> tuple[bool, str, Any]:
    if label == "账单邮编" and looks_like_phone_number(str(value or "")):
        return False, f"{label} 值疑似手机号，已阻止误填: {value}", None
    locator = resolve_locator(selectors, placeholders=placeholders, labels=labels, timeout_ms=3000)
    if not locator:
        if optional:
            if logger:
                logger.info("%s 页面未找到可选字段 %s", log_prefix, label)
            return True, "", None
        if screenshot_stage and capture_screenshot:
            capture_screenshot(screenshot_stage)
        return False, f"未找到 {label}", None
    scroll_locator(locator, label)
    try:
        current = str(locator.input_value(timeout=1000) or "").strip()
    except Exception:
        current = ""
    if current == str(value or "").strip():
        if logger:
            logger.info("%s 页面 %s 已有目标值，跳过填写", log_prefix, label)
        return True, "", locator
    if logger:
        logger.info("%s 页面准备填写 %s，当前值=%r，新值=%r", log_prefix, label, current, value)
    if callable(progress):
        progress("billing_fill_field", field=label)
    try:
        locator.fill(str(value or ""), timeout=4000)
        actual = read_value(locator)
        if value and not matches(str(value), actual):
            if logger:
                logger.info("%s 页面 fill 写入 %s 后暂未读回目标值，实际=%r，尝试原生重写", log_prefix, label, actual)
            if set_value(locator, str(value or "")):
                sleep(0.2)
                actual = read_value(locator)
            if value and not matches(str(value), actual):
                if screenshot_stage and capture_screenshot:
                    capture_screenshot(screenshot_stage)
                return False, f"填写 {label} 后校验失败: 期望={value!r}, 实际={actual!r}", locator
        return True, "", locator
    except Exception as exc:
        if logger:
            logger.info("%s 页面 fill %s 失败，尝试原生写入: %s", log_prefix, label, exc)
        if set_value(locator, str(value or "")):
            sleep(0.2)
            actual = read_value(locator)
            if not value or matches(str(value), actual):
                return True, "", locator
        if screenshot_stage and capture_screenshot:
            capture_screenshot(screenshot_stage)
        return False, f"填写 {label} 失败: {exc}", locator


def select_billing_page_field(
    *,
    selectors: list[str],
    value: str,
    label: str,
    resolve_locator,
    keyboard,
    optional: bool = False,
    screenshot_stage: str = "",
    placeholders: list[str] | None = None,
    labels: list[str] | None = None,
    capture_screenshot=None,
    scroll_locator=scroll_locator_into_view,
    progress=None,
    logger: logging.Logger | None = None,
    log_prefix: str = "[payment_form_fields]",
    read_value=read_locator_value,
) -> tuple[bool, str, Any]:
    locator = resolve_locator(selectors, placeholders=placeholders, labels=labels, timeout_ms=3000)
    if not locator:
        if optional:
            if logger:
                logger.info("%s 页面未找到可选字段 %s", log_prefix, label)
            return True, "", None
        if screenshot_stage and capture_screenshot:
            capture_screenshot(screenshot_stage)
        return False, f"未找到 {label}", None
    scroll_locator(locator, label)
    if logger:
        logger.info("%s 页面准备选择 %s，新值=%r", log_prefix, label, value)
    if callable(progress):
        progress("billing_select_field", field=label)
    try:
        locator.select_option(value=str(value or ""), timeout=4000)
        actual = read_value(locator)
        if logger:
            logger.info("%s 页面已选择 %s，当前值=%r", log_prefix, label, actual)
        return True, "", locator
    except Exception:
        try:
            locator.select_option(label=str(value or ""), timeout=4000)
            actual = read_value(locator)
            if logger:
                logger.info("%s 页面已选择 %s，当前值=%r", log_prefix, label, actual)
            return True, "", locator
        except Exception:
            try:
                locator.click(timeout=1500)
                keyboard.type(str(value or ""), delay=30)
                keyboard.press("Enter")
                return True, "", locator
            except Exception as exc:
                if optional:
                    if logger:
                        logger.info("%s 页面跳过可选选择字段 %s: %s", log_prefix, label, exc)
                    return True, "", locator
                if screenshot_stage and capture_screenshot:
                    capture_screenshot(screenshot_stage)
                return False, f"选择 {label} 失败: {exc}", locator


def billing_stability_checks(billing: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    return [
        ("name", "账单姓名", str(billing.get("name") or ""), "gopay-billing-name-final-failed"),
        ("address1", "账单地址1", str(billing.get("address1") or ""), "gopay-billing-address1-final-failed"),
        ("city", "账单城市", str(billing.get("city") or ""), "gopay-billing-city-final-failed"),
        ("state", "账单州/省", str(billing.get("state") or ""), "gopay-billing-state-final-failed"),
        ("zip", "账单邮编", str(billing.get("zip") or ""), "gopay-billing-zip-final-failed"),
    ]


def _verify_billing_field_stable(
    field_locators: dict[str, Any],
    key: str,
    label: str,
    expected: str,
    screenshot_stage: str,
    *,
    capture_screenshot,
    dismiss_address_autocomplete,
    progress=None,
    logger: logging.Logger | None = None,
    log_prefix: str = "[payment_form_fields]",
    read_value=read_locator_value,
    matches=value_matches,
    set_value=set_locator_value,
    sleep=time.sleep,
) -> tuple[bool, str]:
    locator = field_locators.get(key)
    if not locator:
        capture_screenshot(screenshot_stage)
        return False, f"提交前校验失败，缺少 {label} 定位器"
    actual = read_value(locator)
    if matches(expected, actual):
        if logger:
            logger.info("%s 提交前校验通过 %s=%r", log_prefix, label, actual)
        if callable(progress):
            progress("billing_field_verified", field=label)
        return True, ""
    if logger:
        logger.info("%s 提交前发现 %s 被改写，实际=%r，重写为=%r", log_prefix, label, actual, expected)
    try:
        locator.fill(expected, timeout=2500)
    except Exception:
        set_value(locator, expected)
    dismiss_address_autocomplete(field_locators.get("address1"))
    sleep(0.3)
    actual = read_value(locator)
    if not matches(expected, actual):
        capture_screenshot(screenshot_stage)
        return False, f"提交前校验失败 {label}: 期望={expected!r}, 实际={actual!r}"
    if logger:
        logger.info("%s 提交前重写成功 %s=%r", log_prefix, label, actual)
    return True, ""


def verify_billing_fields_stable(
    field_locators: dict[str, Any],
    billing: dict[str, Any],
    *,
    suppress_address_autocomplete_ui,
    dismiss_address_autocomplete,
    capture_screenshot,
    progress=None,
    logger: logging.Logger | None = None,
    log_prefix: str = "[payment_form_fields]",
    read_value=read_locator_value,
    matches=value_matches,
    set_value=set_locator_value,
    sleep=time.sleep,
) -> tuple[bool, str]:
    suppress_address_autocomplete_ui()
    dismiss_address_autocomplete(field_locators.get("address1"))
    sleep(1.0)
    for key, label, expected, screenshot_stage in billing_stability_checks(billing):
        if not expected:
            continue
        ok, error = _verify_billing_field_stable(
            field_locators,
            key,
            label,
            expected,
            screenshot_stage,
            capture_screenshot=capture_screenshot,
            dismiss_address_autocomplete=dismiss_address_autocomplete,
            progress=progress,
            logger=logger,
            log_prefix=log_prefix,
            read_value=read_value,
            matches=matches,
            set_value=set_value,
            sleep=sleep,
        )
        if not ok:
            return False, error
    return True, ""
