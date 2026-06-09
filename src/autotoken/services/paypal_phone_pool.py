"""PayPal phone-account normalization and leasing helpers."""

import os
import re
from typing import Any


def phone_account_value(raw_phone_account: Any, *names: str) -> Any:
    if isinstance(raw_phone_account, dict):
        for name in names:
            if name in raw_phone_account:
                return raw_phone_account.get(name)
        return None
    for name in names:
        if hasattr(raw_phone_account, name):
            return getattr(raw_phone_account, name)
    return None


def normalize_paypal_phone_accounts(
    raw_phone_accounts: list[Any],
    *,
    otp_channel: str = "sms",
) -> dict[str, Any]:
    phone_accounts: list[dict] = []
    seen_phone_accounts: set[tuple[str, str, str]] = set()
    effective_sms_url = ""
    effective_otp_channel = str(otp_channel or "sms").strip().lower() or "sms"
    billing_phone = ""

    for raw_phone_account in raw_phone_accounts or []:
        account_phone_number = str(
            phone_account_value(
                raw_phone_account, "phone_number", "phoneNumber", "phone", "billing_phone", "billingPhone"
            )
            or ""
        ).strip()
        account_sms_url = str(phone_account_value(raw_phone_account, "sms_url", "smsUrl") or "").strip()
        account_otp_channel = (
            str(phone_account_value(raw_phone_account, "otp_channel", "otpChannel") or effective_otp_channel or "sms")
            .strip()
            .lower()
        )
        if account_otp_channel not in {"sms", "whatsapp"}:
            raise ValueError("phone_accounts otp_channel 只支持 sms 或 whatsapp")
        if not account_phone_number and not account_sms_url:
            continue
        if not account_phone_number or not account_sms_url:
            raise ValueError("phone_accounts 每项都必须填写 phone_number、sms_url")
        phone_key = (account_phone_number, account_sms_url, account_otp_channel)
        if phone_key in seen_phone_accounts:
            continue
        seen_phone_accounts.add(phone_key)
        phone_accounts.append(
            {
                "phone_number": account_phone_number,
                "sms_url": account_sms_url,
                "otp_channel": account_otp_channel,
            }
        )

    if phone_accounts:
        first_account = phone_accounts[0]
        effective_sms_url = str(first_account.get("sms_url") or "").strip()
        effective_otp_channel = str(first_account.get("otp_channel") or effective_otp_channel).strip().lower() or "sms"
        billing_phone = str(first_account.get("phone_number") or "").strip()

    return {
        "phone_accounts": phone_accounts,
        "sms_url": effective_sms_url,
        "otp_channel": effective_otp_channel,
        "billing_phone": billing_phone,
    }


def _env_str(name: str, default: str = "") -> str:
    return str(os.environ.get(name, default) or "").strip()


def paypal_sms_auto_provision_enabled(*, paypal_mode: str, protocol_no_card: bool, sms_url: str, phone_accounts: list[dict]) -> bool:
    if paypal_mode != "create_account" or not protocol_no_card:
        return False
    if str(sms_url or "").strip() or phone_accounts:
        return False
    raw = _env_str("PAYPAL_SMS_AUTO_PROVISION", "")
    if raw:
        return raw.lower() in {"1", "true", "yes", "on"}
    return bool(_env_str("PAYPAL_SMS_PROVIDER"))


def _paypal_sms_provider() -> str:
    provider = re.sub(r"[^a-z0-9_ -]+", "", _env_str("PAYPAL_SMS_PROVIDER")).strip().lower()
    provider = provider.replace("-", "_").replace(" ", "_")
    if provider in {"hero", "herosms", "hero_sms"}:
        return "hero_sms"
    if provider in {"smsbower", "sms_bower"}:
        return "smsbower"
    if provider in {"smscode", "sms_code"}:
        return "smscode"
    if provider in {"smscloud", "sms_cloud"}:
        return "smscloud"
    return provider


def _public_base_url(public_base_url: str = "") -> str:
    return str(public_base_url or _env_str("AUTOTOKEN_LOCAL_BASE_URL", "http://127.0.0.1:8787")).strip().rstrip("/")


def _phone_with_country_prefix(phone: str, country_code: str) -> str:
    digits = re.sub(r"\D+", "", str(phone or ""))
    prefix = re.sub(r"\D+", "", str(country_code or ""))
    if not digits:
        return ""
    if prefix and digits.startswith(prefix):
        return f"+{digits}"
    return f"+{prefix}{digits}" if prefix else f"+{digits}"


def explicit_paypal_phone_account_from_env() -> dict[str, str] | None:
    sms_url = _env_str("PAYPAL_SMS_URL")
    phone_number = (
        _env_str("PAYPAL_PHONE_NUMBER")
        or _env_str("PAYPAL_SMS_PHONE_NUMBER")
        or _env_str("PAYPAL_BILLING_PHONE")
    )
    if not sms_url and not phone_number:
        return None
    if not sms_url or not phone_number:
        raise ValueError("PAYPAL_SMS_URL 与 PAYPAL_PHONE_NUMBER 必须同时配置")
    otp_channel = _env_str("PAYPAL_OTP_CHANNEL", "sms").lower() or "sms"
    if otp_channel not in {"sms", "whatsapp"}:
        raise ValueError("PAYPAL_OTP_CHANNEL 只支持 sms 或 whatsapp")
    return {
        "phone_number": phone_number,
        "sms_url": sms_url,
        "otp_channel": otp_channel,
        "sms_provider": "explicit_env",
    }


def provision_paypal_phone_account_from_env(
    *,
    public_base_url: str = "",
    log=None,
) -> dict[str, Any]:
    """Buy one PayPal signup phone from PAYPAL_SMS_* config and expose it as sms_url."""
    provider = _paypal_sms_provider()
    if not provider:
        raise ValueError("缺少 PAYPAL_SMS_PROVIDER 配置")
    if provider not in {"hero_sms", "smsbower", "smscode", "smscloud"}:
        raise ValueError("PAYPAL_SMS_PROVIDER 只支持 hero_sms、smsbower、smscode 或 smscloud")

    from autotoken.payments import gopay_auto_register as sms_activation

    logger = log if callable(log) else (lambda _message: None)
    activation = None
    activation_id = ""
    phone_raw = ""
    country_code = _env_str("PAYPAL_SMS_PHONE_COUNTRY_CODE", _env_str("PAYPAL_PHONE_COUNTRY_CODE", "81"))

    if provider == "hero_sms":
        api_key = _env_str("PAYPAL_HERO_SMS_API_KEY", _env_str("PAYPAL_SMS_API_KEY"))
        base_url = _env_str("PAYPAL_HERO_SMS_BASE_URL", _env_str("PAYPAL_SMS_BASE_URL", "https://hero-sms.com/stubs/handler_api.php"))
        country = _env_str("PAYPAL_HERO_SMS_COUNTRY", _env_str("PAYPAL_SMS_COUNTRY", "4"))
        service = _env_str("PAYPAL_HERO_SMS_SERVICE", _env_str("PAYPAL_SMS_SERVICE", "ts"))
        if not api_key:
            raise ValueError("缺少 PAYPAL_HERO_SMS_API_KEY 或 PAYPAL_SMS_API_KEY 配置")
        activation_id, phone_raw, error = sms_activation._hero_get_number(
            service_code=service,
            country_id=country,
            base_url=base_url,
            api_key=api_key,
            max_price=_env_str("PAYPAL_HERO_SMS_MAX_PRICE", _env_str("PAYPAL_SMS_MAX_PRICE")),
            min_price=_env_str("PAYPAL_HERO_SMS_MIN_PRICE", _env_str("PAYPAL_SMS_MIN_PRICE")),
            preferred_price=_env_str("PAYPAL_HERO_SMS_PREFERRED_PRICE", _env_str("PAYPAL_SMS_PREFERRED_PRICE")),
        )
        if not activation_id:
            raise ValueError(f"PayPal hero-sms 取号失败: {error}")
        activation = sms_activation.SmsActivation(
            activation_id=activation_id,
            phone=phone_raw,
            country_id=int(float(country or 0)),
            base_url=base_url,
            api_key=api_key,
            provider="hero_sms",
            log=logger,
        )
    elif provider == "smsbower":
        api_key = _env_str("PAYPAL_SMSBOWER_API_KEY", _env_str("PAYPAL_SMS_API_KEY"))
        base_url = _env_str("PAYPAL_SMSBOWER_BASE_URL", _env_str("PAYPAL_SMS_BASE_URL", "https://smsbower.page/stubs/handler_api.php"))
        country = _env_str("PAYPAL_SMSBOWER_COUNTRY", _env_str("PAYPAL_SMS_COUNTRY", "4"))
        service = _env_str("PAYPAL_SMSBOWER_SERVICE", _env_str("PAYPAL_SMS_SERVICE", "ts"))
        if not api_key:
            raise ValueError("缺少 PAYPAL_SMSBOWER_API_KEY 或 PAYPAL_SMS_API_KEY 配置")
        activation_id, phone_raw, error = sms_activation._smsbower_get_number(
            service_code=service,
            country_id=country,
            base_url=base_url,
            api_key=api_key,
            max_price=_env_str("PAYPAL_SMSBOWER_MAX_PRICE", _env_str("PAYPAL_SMS_MAX_PRICE")),
            min_price=_env_str("PAYPAL_SMSBOWER_MIN_PRICE", _env_str("PAYPAL_SMS_MIN_PRICE")),
            preferred_price=_env_str("PAYPAL_SMSBOWER_PREFERRED_PRICE", _env_str("PAYPAL_SMS_PREFERRED_PRICE")),
        )
        if not activation_id:
            raise ValueError(f"PayPal smsbower 取号失败: {error}")
        activation = sms_activation.SmsActivation(
            activation_id=activation_id,
            phone=phone_raw,
            country_id=int(float(country or 0)),
            base_url=base_url,
            api_key=api_key,
            provider="smsbower",
            log=logger,
        )
    elif provider == "smscode":
        api_token = _env_str("PAYPAL_SMSCODE_API_TOKEN", _env_str("PAYPAL_SMS_API_KEY"))
        base_url = _env_str("PAYPAL_SMSCODE_BASE_URL", _env_str("PAYPAL_SMS_BASE_URL", sms_activation.DEFAULT_SMSCODE_BASE_URL))
        country = _env_str("PAYPAL_SMSCODE_COUNTRY_ID", _env_str("PAYPAL_SMS_COUNTRY", "4"))
        if not api_token:
            raise ValueError("缺少 PAYPAL_SMSCODE_API_TOKEN 或 PAYPAL_SMS_API_KEY 配置")
        activation_id, phone_raw, error = sms_activation._smscode_get_number(
            base_url=base_url,
            api_token=api_token,
            country_id=country,
            platform_id=_env_str("PAYPAL_SMSCODE_PLATFORM_ID"),
            platform_query=_env_str("PAYPAL_SMSCODE_PLATFORM_QUERY", _env_str("PAYPAL_SMS_SERVICE", "paypal")),
            product_id=_env_str("PAYPAL_SMSCODE_PRODUCT_ID"),
            min_price=_env_str("PAYPAL_SMSCODE_MIN_PRICE", _env_str("PAYPAL_SMS_MIN_PRICE")),
            max_price=_env_str("PAYPAL_SMSCODE_MAX_PRICE", _env_str("PAYPAL_SMS_MAX_PRICE")),
        )
        if not activation_id:
            raise ValueError(f"PayPal SMSCode 取号失败: {error}")
        activation = sms_activation.SmsCodeActivation(
            activation_id=activation_id,
            phone=phone_raw,
            country_id=country,
            base_url=base_url,
            api_token=api_token,
            log=logger,
        )
    else:
        token = _env_str("PAYPAL_SMSCLOUD_XI_TOKEN", _env_str("PAYPAL_SMS_API_KEY"))
        base_url = _env_str("PAYPAL_SMSCLOUD_BASE_URL", _env_str("PAYPAL_SMS_BASE_URL", "https://smscloud.sbs/api"))
        country = _env_str("PAYPAL_SMSCLOUD_COUNTRY", _env_str("PAYPAL_SMS_COUNTRY", "4"))
        service = _env_str("PAYPAL_SMSCLOUD_SERVICE", _env_str("PAYPAL_SMS_SERVICE", "paypal"))
        if not token:
            raise ValueError("缺少 PAYPAL_SMSCLOUD_XI_TOKEN 或 PAYPAL_SMS_API_KEY 配置")
        activation_id, phone_raw, error = sms_activation._smscloud_get_number(
            service_code=service,
            country_id=country,
            base_url=base_url,
            token=token,
            max_price=_env_str("PAYPAL_SMSCLOUD_MAX_PRICE", _env_str("PAYPAL_SMS_MAX_PRICE")),
        )
        if not activation_id:
            raise ValueError(f"PayPal smscloud 取号失败: {error}")
        activation = sms_activation.SmsCloudActivation(
            activation_id=activation_id,
            phone=phone_raw,
            country_id=country,
            base_url=base_url,
            token=token,
            log=logger,
        )

    bridge = sms_activation.create_sms_bridge(activation)
    phone_number = _phone_with_country_prefix(phone_raw, country_code)
    logger(f"[paypal-sms] {provider} 取号成功: {phone_number[:4]}***{phone_number[-4:] if len(phone_number) >= 4 else ''}")
    return {
        "phone_number": phone_number,
        "sms_url": f"{_public_base_url(public_base_url)}/otp/gopay-signup/{bridge.token}",
        "otp_channel": "sms",
        "sms_provider": provider,
        "activation_id": activation_id,
        "bridge_token": bridge.token,
    }


def close_paypal_sms_bridges(phone_accounts: list[dict], *, success: bool) -> None:
    if not phone_accounts:
        return
    from autotoken.payments import gopay_auto_register as sms_activation

    closed_tokens: set[str] = set()
    for account in phone_accounts:
        if not isinstance(account, dict):
            continue
        token = str(account.get("bridge_token") or account.get("sms_bridge_token") or "").strip()
        if not token or token in closed_tokens:
            continue
        closed_tokens.add(token)
        sms_activation.close_sms_bridge(token, success=success)


def paypal_sms_bridge_success_for_result(result_payload: dict | None) -> bool:
    if not isinstance(result_payload, dict):
        return False
    if result_payload.get("status") == "success":
        return True
    if str(result_payload.get("paypal_user_id") or "").strip():
        return True
    if str(result_payload.get("return_url") or "").strip():
        return True
    if str(result_payload.get("failure_stage") or "") == "post_submit":
        return True
    return False


def normalize_paypal_phone_key(value: Any) -> str:
    raw = str(value or "").strip()
    digits = re.sub(r"\D+", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits or raw.lower()


def paypal_phone_account_key(account: dict | None) -> str:
    if not isinstance(account, dict):
        return ""
    return normalize_paypal_phone_key(
        account.get("phone_number")
        or account.get("phone")
        or account.get("phoneNumber")
        or account.get("billing_phone")
        or account.get("billingPhone")
    )


def paypal_phone_account_available(account: dict | None, invalid_keys: set[str]) -> bool:
    phone_key = paypal_phone_account_key(account)
    if not phone_key:
        return False
    status = str((account or {}).get("status") or "").strip().lower()
    if status in {"invalid", "disabled", "unavailable"}:
        return False
    return phone_key not in invalid_keys


def remember_invalid_paypal_phone(phone: Any, invalid_keys: set[str], invalid_pool: list[str]) -> bool:
    raw_phone = str(phone or "").strip()
    phone_key = normalize_paypal_phone_key(raw_phone)
    if not phone_key or phone_key in invalid_keys:
        return False
    invalid_keys.add(phone_key)
    invalid_pool.append(raw_phone or phone_key)
    return True


def lease_paypal_phone_accounts_from_candidates(
    candidates: list[dict],
    *,
    invalid_keys: set[str],
    reserved_keys: set[str],
    otp_channel: str,
    effective_concurrency: int,
) -> tuple[list[dict], str, str, str]:
    if not candidates:
        return [], "", otp_channel, ""

    leased: list[dict] = []
    for account_phone in candidates:
        if not isinstance(account_phone, dict):
            continue
        if not paypal_phone_account_available(account_phone, invalid_keys):
            continue
        phone_key = paypal_phone_account_key(account_phone)
        if phone_key in reserved_keys:
            continue
        reserved_keys.add(phone_key)
        leased.append(account_phone)
        if effective_concurrency > 1:
            break

    if not leased:
        return [], "", otp_channel, ""

    primary_phone = leased[0]
    current_sms_url = str(primary_phone.get("sms_url") or "").strip()
    current_otp_channel = str(primary_phone.get("otp_channel") or otp_channel or "sms").strip().lower() or "sms"
    current_billing_phone = str(primary_phone.get("phone_number") or "").strip()
    return leased, current_sms_url, current_otp_channel, current_billing_phone


def lease_paypal_phone_accounts(
    phone_accounts: list[dict],
    *,
    sms_url: str,
    otp_channel: str,
    invalid_keys: set[str],
    reserved_keys: set[str],
    effective_concurrency: int,
) -> tuple[list[dict], str, str, str]:
    if not phone_accounts:
        return phone_accounts, sms_url, otp_channel, ""
    return lease_paypal_phone_accounts_from_candidates(
        phone_accounts,
        invalid_keys=invalid_keys,
        reserved_keys=reserved_keys,
        otp_channel=otp_channel,
        effective_concurrency=effective_concurrency,
    )


def lease_paypal_phone_accounts_for_item(
    queue_item: dict[str, Any],
    *,
    phone_accounts: list[dict],
    sms_url: str,
    otp_channel: str,
    invalid_keys: set[str],
    reserved_keys: set[str],
    effective_concurrency: int,
) -> tuple[list[dict], str, str, str]:
    assigned_accounts = queue_item.get("phone_accounts")
    if not assigned_accounts:
        return lease_paypal_phone_accounts(
            phone_accounts,
            sms_url=sms_url,
            otp_channel=otp_channel,
            invalid_keys=invalid_keys,
            reserved_keys=reserved_keys,
            effective_concurrency=effective_concurrency,
        )
    if not isinstance(assigned_accounts, list):
        assigned_accounts = [assigned_accounts]
    if effective_concurrency <= 1:
        assigned_keys = {paypal_phone_account_key(item) for item in assigned_accounts if isinstance(item, dict)}
        candidates = list(assigned_accounts) + [
            account_phone
            for account_phone in phone_accounts
            if paypal_phone_account_key(account_phone) not in assigned_keys
        ]
        return lease_paypal_phone_accounts_from_candidates(
            candidates,
            invalid_keys=invalid_keys,
            reserved_keys=reserved_keys,
            otp_channel=otp_channel,
            effective_concurrency=effective_concurrency,
        )
    return lease_paypal_phone_accounts_from_candidates(
        assigned_accounts,
        invalid_keys=invalid_keys,
        reserved_keys=reserved_keys,
        otp_channel=otp_channel,
        effective_concurrency=effective_concurrency,
    )


def assign_paypal_phone_accounts_to_items(
    items: list[dict[str, Any]],
    *,
    paypal_mode: str,
    phone_accounts: list[dict],
    invalid_keys: set[str],
) -> list[dict[str, Any]]:
    if paypal_mode != "create_account" or not phone_accounts or not items:
        return items

    available = [
        account_phone for account_phone in phone_accounts if paypal_phone_account_available(account_phone, invalid_keys)
    ]
    assigned: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        next_item = dict(item)
        if index < len(available):
            next_item["phone_accounts"] = [available[index]]
        assigned.append(next_item)
    return assigned


def release_paypal_phone_accounts(active_phone_accounts: list[dict], reserved_keys: set[str]) -> None:
    for account_phone in active_phone_accounts or []:
        phone_key = paypal_phone_account_key(account_phone)
        if phone_key:
            reserved_keys.discard(phone_key)


def paypal_phone_retry_round_concurrency(
    *,
    base_concurrency: int,
    round_item_count: int,
    paypal_mode: str,
    phone_accounts: list[dict],
    invalid_keys: set[str],
) -> int:
    concurrency = max(1, min(base_concurrency, round_item_count or 1))
    if paypal_mode != "create_account" or not phone_accounts:
        return concurrency
    available_phone_count = sum(
        1 for phone_account in phone_accounts if paypal_phone_account_available(phone_account, invalid_keys)
    )
    return max(1, min(concurrency, available_phone_count or 1))
