"""PayPal 自动/人工绑定执行器。"""

from __future__ import annotations

import logging
import re
import secrets
import string
import time
import uuid
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from autoteam.auth_session_store import load_auth_session
from autoteam.bind_executor import _build_result, _capture_screenshot
from autoteam.chatgpt_api import ChatGPTTeamAPI
from autoteam.gopay_executor import (
    _accept_checkout_terms_on_page,
    _dismiss_address_autocomplete,
    _extract_checkout_error,
    _inject_chatgpt_browser_cookies,
    _open_checkout_in_page,
    _poll_otp_from_sms_url,
    _safe_url_summary,
    _select_chatgpt_account_if_needed,
    _suppress_address_autocomplete_ui,
)

logger = logging.getLogger(__name__)
DEFAULT_PAYPAL_NAME = "James Smith"
PAYPAL_ADDRESS_GENERATOR_URL = "https://www.meiguodizhi.com/api/v1/dz"
PAYPAL_ADDRESS_GENERATOR_REFERER = "https://www.meiguodizhi.com/"
DEFAULT_PAYPAL_BILLING_PROFILE = {
    "name": DEFAULT_PAYPAL_NAME,
    "country": "US",
    "state": "CA",
    "city": "Los Angeles",
    "zip": "90026",
    "address1": "3110 Sunset Boulevard",
    "address2": "",
    "phone_number": "213-555-0182",
}

SUCCESS_HINTS = (
    "payment successful",
    "payment complete",
    "thanks for subscribing",
    "subscription active",
    "subscription confirmed",
    "you are now subscribed",
    "your payment method was added",
    "you've successfully subscribed",
    "return to merchant",
    "付款成功",
    "支付成功",
    "订阅成功",
)
FAILURE_HINTS = (
    "card was declined",
    "declined",
    "payment failed",
    "your card was declined",
    "payment was not approved",
    "payment declined",
    "authorization failed",
    "try another payment method",
    "we couldn't complete",
    "we can’t complete",
    "something went wrong",
    "支付失败",
    "付款失败",
    "未获批准",
    "被拒绝",
)
PENDING_HINTS = (
    "payment pending",
    "processing payment",
    "we're processing",
    "正在处理",
    "处理中",
)
CANCEL_HINTS = (
    "payment canceled",
    "payment cancelled",
    "checkout canceled",
    "checkout cancelled",
    "you cancelled",
    "取消付款",
    "已取消",
)
REVIEW_HINTS = (
    "authentication required",
    "verify your purchase",
    "complete the verification",
    "return to merchant",
    "需要验证",
    "请完成验证",
    "3d secure",
)

SUCCESS_URL_RE = re.compile(r"(?:success|complete|completed|thank|subscribed)", re.I)
FAILURE_URL_RE = re.compile(r"(?:failed|failure|declined|error)", re.I)
CANCEL_URL_RE = re.compile(r"(?:cancel|cancelled|canceled)", re.I)

AUTOFILL_SELECTORS = {
    "name": [
        'input[autocomplete="name"]',
        'input[autocomplete="cc-name"]',
        'input[name*="name" i]',
        'input[id*="name" i]',
    ],
    "email": [
        'input[autocomplete="email"]',
        'input[type="email"]',
        'input[name*="email" i]',
        'input[id*="email" i]',
    ],
    "phone": [
        'input[autocomplete="tel"]',
        'input[type="tel"]',
        'input[name*="phone" i]',
        'input[id*="phone" i]',
    ],
    "address1": [
        'input[autocomplete="billing address-line1"]',
        'input[autocomplete="address-line1"]',
        '#billingAddressLine1',
        'input[name*="addressLine1" i]',
        'input[id*="addressLine1" i]',
        'input[name*="address" i]',
        'input[id*="address" i]',
    ],
    "address2": [
        'input[autocomplete="billing address-line2"]',
        'input[autocomplete="address-line2"]',
        '#billingAddressLine2',
        'input[name*="addressLine2" i]',
        'input[id*="addressLine2" i]',
    ],
    "city": [
        'input[autocomplete="billing address-level2"]',
        'input[autocomplete="address-level2"]',
        '#billingLocality',
        'input[name*="city" i]',
        'input[id*="city" i]',
        'input[name*="locality" i]',
        'input[id*="locality" i]',
    ],
    "state": [
        'select[autocomplete="billing address-level1"]',
        'input[autocomplete="billing address-level1"]',
        'select[autocomplete="address-level1"]',
        'input[autocomplete="address-level1"]',
        '#billingAdministrativeArea',
        'select[name*="state" i]',
        'input[name*="state" i]',
        'select[id*="state" i]',
        'input[id*="state" i]',
    ],
    "postal_code": [
        'input[autocomplete="billing postal-code"]',
        'input[autocomplete="postal-code"]',
        '#billingPostalCode',
        'input[name*="postal" i]',
        'input[id*="postal" i]',
        'input[name*="zip" i]',
        'input[id*="zip" i]',
    ],
    "country": [
        'select[autocomplete="billing country"]',
        'select[autocomplete="country"]',
        'select[name*="country" i]',
        'select[id*="country" i]',
    ],
}

PAYPAL_EMAIL_SELECTORS = [
    'input#email',
    'input[name="login_email"]',
    'input[name="email"]',
    'input[type="email"]',
    'input[autocomplete="username"]',
]
PAYPAL_PASSWORD_SELECTORS = [
    'input#password',
    'input#password-field',
    'input[name="login_password"]',
    'input[name="password"]',
    'input[type="password"]',
    'input[autocomplete="current-password"]',
]
PAYPAL_NEXT_SELECTORS = [
    'button:has-text("Next")',
    'button:has-text("Continue")',
    'button:has-text("Log In")',
    'button:has-text("Login")',
    'button:has-text("Sign In")',
    'button:has-text("下一步")',
    'button:has-text("下一頁")',
    'button:has-text("继续")',
    'button:has-text("繼續")',
    'button:has-text("继续付款")',
    'button:has-text("繼續付款")',
    'button:has-text("登录")',
    'button:has-text("登入")',
    'button[type="submit"]',
    '#btnNext',
    '#btnLogin',
]
PAYPAL_CREATE_ACCOUNT_SELECTORS = [
    '#createAccount',
    'button#createAccount',
    'a:has-text("Create an Account")',
    'button:has-text("Create an Account")',
    'a:has-text("Sign Up")',
    'button:has-text("Sign Up")',
    'a:has-text("建立帳戶")',
    'button:has-text("建立帳戶")',
    'a:has-text("建立账户")',
    'button:has-text("建立账户")',
    'button:has-text("创建账户")',
    'button:has-text("注册")',
]
PAYPAL_APPROVE_SELECTORS = [
    '#consentButton',
    'button[data-testid="consentButton"]',
    'button:has-text("Agree and Continue")',
    'button:has-text("Agree & Continue")',
    'button:has-text("Authorize")',
    'button:has-text("Accept")',
    'button:has-text("同意并继续")',
    'button:has-text("同意並繼續")',
    'button:has-text("授权")',
    'button:has-text("授權")',
    'button:has-text("继续")',
    'button:has-text("繼續")',
    'button[type="submit"]',
]
PAYPAL_COUNTRY_SELECTORS = [
    "select#country",
    'select[name="country"]',
]
PAYPAL_PHONE_SELECTORS = [
    "input#phone",
    'input[name="phone"]',
    'input[autocomplete="tel"]',
]
PAYPAL_CARD_NUMBER_SELECTORS = [
    "input#cardNumber",
    'input[name="cardNumber"]',
    'input[autocomplete="cc-number"]',
]
PAYPAL_CARD_EXPIRY_SELECTORS = [
    "input#cardExpiry",
    'input[name="cardExpiry"]',
    'input[autocomplete="cc-exp"]',
]
PAYPAL_CARD_CVV_SELECTORS = [
    "input#cardCvv",
    'input[name="cardCvv"]',
    'input[autocomplete="cc-csc"]',
]
PAYPAL_FIRST_NAME_SELECTORS = [
    "input#firstName",
    'input[name="firstName"]',
    'input[autocomplete="given-name"]',
]
PAYPAL_LAST_NAME_SELECTORS = [
    "input#lastName",
    'input[name="lastName"]',
    'input[autocomplete="family-name"]',
]
PAYPAL_BILLING_LINE1_SELECTORS = [
    "input#billingLine1",
    'input[name="billingLine1"]',
]
PAYPAL_BILLING_CITY_SELECTORS = [
    "input#billingCity",
    'input[name="billingCity"]',
]
PAYPAL_BILLING_POSTAL_SELECTORS = [
    "input#billingPostalCode",
    'input[name="billingPostalCode"]',
]
PAYPAL_BILLING_STATE_SELECTORS = [
    "select#billingState",
    "input#billingState",
    'select[name="billingState"]',
    'input[name="billingState"]',
]
PAYPAL_CREATE_SUBMIT_SELECTORS = [
    'button:has-text("Agree & Create Account")',
    'button:has-text("Agree and Create Account")',
    'button:has-text("Create Account")',
    'button:has-text("Agree & Continue")',
    'button:has-text("Continue Payment")',
    'button:has-text("继续付款")',
    'button:has-text("繼續付款")',
    'button:has-text("创建账户")',
    'button:has-text("建立帳戶")',
    'button[type="submit"]',
]
PAYPAL_DISMISS_PROMPT_SELECTORS = [
    'button:has-text("Not now")',
    'button:has-text("Maybe later")',
    'button:has-text("Skip")',
    'button:has-text("Close")',
    'button:has-text("Try another way")',
    'button:has-text("Use password instead")',
    'button:has-text("以后再说")',
    'button:has-text("暂不")',
    'button:has-text("关闭")',
    'button:has-text("改用密码")',
    '[data-testid*="close" i]',
]
PAYPAL_CHECKOUT_SELECTORS = [
    '[data-testid="paypal-accordion-item-button"]',
    'label[for="payment-method-accordion-item-title-paypal"]',
    '#payment-method-accordion-item-title-paypal',
    '.paypal-accordion-item button',
    'button:has-text("PayPal")',
    'label:has-text("PayPal")',
    '[role="button"]:has-text("PayPal")',
    '[role="radio"]:has-text("PayPal")',
    '[aria-label*="paypal" i]',
    'img[alt*="paypal" i]',
]
PAYPAL_CHECKOUT_STATE_SELECTORS = [
    '#payment-method-accordion-item-title-paypal',
    'input[type="radio"][id*="paypal" i]',
    'input[type="radio"][name*="payment" i][value*="paypal" i]',
    '[role="radio"][aria-label*="paypal" i]',
]
CHECKOUT_SUBMIT_SELECTORS = [
    'button[data-testid="submit-button"]',
    'button[data-testid="hosted-payment-submit-button"]',
    'button[data-atomic-wait-intent="Submit_Email"]',
    'button.SubmitButton--complete',
    'button:has-text("Subscribe")',
    'button:has-text("Pay")',
    'button:has-text("Continue")',
    'button:has-text("Agree")',
    'button:has-text("订阅")',
    'button[type="submit"]',
]

PAYPAL_AUTO_STAGE_MESSAGES = {
    "paypal_session_ready": "已注入 ChatGPT 登录态，准备打开 checkout",
    "checkout_opened": "已打开 PayPal 相关支付页面",
    "paypal_autofill": "已自动填写账单/联系字段",
    "paypal_billing_fill_started": "正在自动填写 checkout 账单地址",
    "paypal_billing_fill_done": "checkout 账单地址已填写",
    "paypal_option_selected": "已切换到 PayPal 支付方式",
    "paypal_submit_checkout": "正在提交 checkout 并跳转 PayPal",
    "paypal_wait_redirect": "已提交 checkout，等待跳转到 PayPal",
    "paypal_authorize": "已进入 PayPal 页面，开始自动登录/授权",
    "paypal_login_email": "正在填写 PayPal 邮箱",
    "paypal_login_password": "正在填写 PayPal 密码",
    "paypal_create_account": "正在切换到 PayPal 注册流程",
    "paypal_fill_signup": "正在填写 PayPal 注册表单",
    "paypal_submit_signup": "正在提交 PayPal 注册信息",
    "paypal_wait_signup_otp": "正在等待 PayPal 短信验证码",
    "paypal_wait_sms_otp_window": "等待短信平台下发 PayPal 验证码",
    "paypal_fetch_otp": "正在从接码接口拉取 PayPal 验证码",
    "paypal_sms_otp_resend_due": "长时间未收到 PayPal 验证码，尝试重新拉取/重发",
    "paypal_sms_provider_resend_triggered": "已通知接码平台继续接收 PayPal 验证码",
    "paypal_otp_received": "已收到 PayPal 验证码",
    "paypal_submit_otp": "正在提交 PayPal 短信验证码",
    "paypal_prompt_dismissed": "已关闭 PayPal 通行密钥/提示弹窗",
    "paypal_approve_clicked": "已点击 PayPal 同意并继续",
    "paypal_wait_result": "PayPal 已授权，等待商户页面确认结果",
    "paypal_wait_manual": "等待人工完成 PayPal 支付流程",
}


def classify_paypal_checkout_state(url: str, body_text: str):
    normalized_url = str(url or "").strip().lower()
    normalized_body = str(body_text or "").strip().lower()
    haystack = f"{normalized_url}\n{normalized_body}"

    if CANCEL_URL_RE.search(normalized_url) or any(hint in haystack for hint in CANCEL_HINTS):
        return {
            "status": "failed",
            "failure_stage": "post_submit",
            "message": "检测到 PayPal 支付已取消",
        }

    if FAILURE_URL_RE.search(normalized_url) or any(hint in haystack for hint in FAILURE_HINTS):
        return {
            "status": "failed",
            "failure_stage": "post_submit",
            "message": "检测到 PayPal/支付失败提示",
        }

    if SUCCESS_URL_RE.search(normalized_url) or any(hint in haystack for hint in SUCCESS_HINTS):
        return {
            "status": "success",
            "failure_stage": "",
            "message": "检测到 PayPal/支付成功页面",
        }

    if any(hint in haystack for hint in PENDING_HINTS):
        return {
            "status": "needs_review",
            "failure_stage": "post_submit",
            "message": "检测到 PayPal 支付处理中，需要人工确认最终状态",
        }

    if any(hint in haystack for hint in REVIEW_HINTS):
        return {
            "status": "needs_review",
            "failure_stage": "post_submit",
            "message": "检测到需要额外验证或人工确认",
        }

    return None


def _safe_host(url: str) -> str:
    try:
        return (urlsplit(str(url or "")).hostname or "").lower()
    except Exception:
        return ""


def _is_paypal_host(url: str) -> bool:
    return _safe_host(url).endswith("paypal.com")


def _is_checkout_host(url: str) -> bool:
    host = _safe_host(url)
    if host in {"pay.openai.com", "checkout.stripe.com"}:
        return True
    return host == "chatgpt.com" and "/checkout/" in str(url or "").lower()


def _autofill_allowed(url: str) -> bool:
    host = _safe_host(url)
    if not host or host.endswith("paypal.com"):
        return False
    return host in {"pay.openai.com", "checkout.stripe.com", "chatgpt.com"} or host.endswith(".stripe.com")


def normalize_autofill_payload(payload: dict | None) -> dict:
    source = payload if isinstance(payload, dict) else {}
    aliases = {
        "name": ("name", "billing_name", "billingName"),
        "email": ("email", "billing_email", "billingEmail"),
        "phone": ("phone", "billing_phone", "billingPhone"),
        "address1": ("address1", "billing_address1", "billingAddress1", "line1"),
        "address2": ("address2", "billing_address2", "billingAddress2", "line2"),
        "city": ("city", "billing_city", "billingCity"),
        "state": ("state", "billing_state", "billingState"),
        "postal_code": ("postal_code", "billing_zip", "billingZip", "zip"),
        "country": ("country", "billing_country", "billingCountry"),
        "card_number": ("card_number", "paypal_card_number", "paypalCardNumber", "cardNumber"),
        "card_expiry": ("card_expiry", "paypal_card_expiry", "paypalCardExpiry", "expiry", "expiry_date"),
        "card_cvv": ("card_cvv", "paypal_card_cvv", "paypalCardCvv", "cvv", "cvc"),
    }
    normalized: dict[str, str] = {}
    for key, names in aliases.items():
        for name in names:
            value = str(source.get(name) or "").strip()
            if value:
                normalized[key] = value
                break
    return normalized


def _normalize_paypal_credentials(email: str = "", password: str = "") -> dict[str, str]:
    return {
        "email": str(email or "").strip(),
        "password": str(password or ""),
    }


def _normalize_paypal_mode(mode: str = "") -> str:
    normalized = str(mode or "").strip().lower()
    if normalized in {"", "login", "existing", "existing-account"}:
        return "existing_account"
    if normalized in {"signup", "register", "create-account"}:
        return "create_account"
    return normalized


def _generate_random_paypal_email() -> str:
    return f"pp{uuid.uuid4().hex[:16]}@gmail.com"


def _generate_random_paypal_password() -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^"
    required = [
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.digits),
        secrets.choice("!@#$%^"),
    ]
    required.extend(secrets.choice(alphabet) for _ in range(10))
    secrets.SystemRandom().shuffle(required)
    return "".join(required)


def _split_paypal_name(name: str) -> tuple[str, str]:
    parts = [part for part in re.split(r"\s+", str(name or "").strip()) if part]
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:])
    if len(parts) == 1:
        return parts[0], "Smith"
    return "James", "Smith"


def _normalize_paypal_phone(phone: str) -> str:
    digits = re.sub(r"\D+", "", str(phone or ""))
    if len(digits) == 11 and digits.startswith("1"):
        return digits[1:]
    return digits


def _normalize_paypal_card_expiry(value: str) -> str:
    raw = re.sub(r"\D+", "", str(value or ""))
    if len(raw) == 4:
        return f"{raw[:2]} / {raw[2:]}"
    if len(raw) == 6:
        return f"{raw[:2]} / {raw[-2:]}"
    return str(value or "").strip()


def _first_payload_value(source: dict, *keys: str) -> str:
    for key in keys:
        value = str(source.get(key) or "").strip()
        if value:
            return value
    return ""


def _split_paypal_address_lines(address1: str) -> tuple[str, str]:
    raw = str(address1 or "").strip()
    if not raw:
        return "", ""
    matched = re.match(r"^(.*?)(?:\s+(APT|APARTMENT|UNIT|STE|SUITE|FL)\.?\s+.+)$", raw, flags=re.IGNORECASE)
    if not matched:
        return raw, ""
    line1 = matched.group(1).strip()
    line2 = raw[len(line1):].strip(" ,")
    return line1, line2


def _flatten_paypal_generator_fields(value, prefix: str = "") -> dict[str, str]:
    fields: dict[str, str] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            next_key = f"{prefix}_{key}" if prefix else str(key)
            fields.update(_flatten_paypal_generator_fields(item, next_key))
        return fields
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            fields.update(_flatten_paypal_generator_fields(item, f"{prefix}_{index}"))
        return fields
    if prefix:
        fields[prefix] = str(value or "").strip()
    return fields


def _paypal_generator_field(address: dict, *names: str) -> str:
    normalized = {
        re.sub(r"[^a-z0-9]+", "", str(key or "").lower()): value
        for key, value in _flatten_paypal_generator_fields(address).items()
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


def _fetch_paypal_random_billing_profile() -> dict:
    try:
        resp = requests.post(
            PAYPAL_ADDRESS_GENERATOR_URL,
            json={"path": "/", "method": "address"},
            headers={
                "Content-Type": "application/json",
                "Origin": "https://www.meiguodizhi.com",
                "Referer": PAYPAL_ADDRESS_GENERATOR_REFERER,
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=30,
            verify=False,
        )
        resp.raise_for_status()
        data = resp.json()
        address = data.get("address") or {}
    except Exception as exc:
        logger.info("[paypal_bind_executor] PayPal billing profile generator unavailable, using fallback: %s", exc)
        return dict(DEFAULT_PAYPAL_BILLING_PROFILE)

    full_name = str(address.get("Full_Name") or "").strip()
    address1 = str(address.get("Address") or "").strip()
    city = str(address.get("City") or "").strip()
    state = str(address.get("State") or "").strip()
    zip_code = str(address.get("Zip_Code") or "").strip()
    if not all([address1, city, state, zip_code]):
        logger.info("[paypal_bind_executor] PayPal billing profile response incomplete, using fallback")
        return dict(DEFAULT_PAYPAL_BILLING_PROFILE)

    line1, line2 = _split_paypal_address_lines(address1)
    result = {
        "name": full_name or DEFAULT_PAYPAL_NAME,
        "country": "US",
        "state": state,
        "city": city,
        "zip": zip_code,
        "address1": line1 or address1,
        "address2": line2,
        "phone_number": str(address.get("Telephone") or "").strip(),
        "raw": address,
    }
    card_number = _paypal_generator_field(
        address,
        "Credit_Card_Number",
        "CreditCardNumber",
        "Card_Number",
        "CardNumber",
        "Credit Card Number",
        "CC Number",
        "CCNumber",
    )
    card_expiry = _paypal_generator_field(
        address,
        "Expires",
        "Expiry",
        "Expiry_Date",
        "ExpiryDate",
        "Exp_Date",
        "ExpDate",
        "Expiration",
        "Expiration_Date",
        "ExpirationDate",
        "Credit_Card_Expiry",
        "CreditCardExpiry",
        "Credit Card Expiry",
    )
    if not card_expiry:
        expiry_month = _paypal_generator_field(address, "Expiry_Month", "Exp_Month", "Expiration_Month")
        expiry_year = _paypal_generator_field(address, "Expiry_Year", "Exp_Year", "Expiration_Year")
        if expiry_month and expiry_year:
            card_expiry = f"{expiry_month}/{expiry_year}"
    card_cvv = _paypal_generator_field(address, "CVV2", "CVV", "CVC", "Security_Code", "Credit_Card_CVV", "Credit Card CVV")
    if card_number:
        result["card_number"] = card_number
    if card_expiry:
        result["card_expiry"] = card_expiry
    if card_cvv:
        result["card_cvv"] = card_cvv
    return result


def _public_paypal_billing_info(billing: dict | None) -> dict:
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


def _build_paypal_signup_profile(
    *,
    paypal_email: str = "",
    paypal_password: str = "",
    billing_payload: dict[str, str] | None = None,
    sms_url: str = "",
    otp_channel: str = "sms",
    paypal_card_number: str = "",
    paypal_card_expiry: str = "",
    paypal_card_cvv: str = "",
) -> dict[str, str | bool]:
    billing = dict(billing_payload or {})
    first_name, last_name = _split_paypal_name(str(billing.get("name") or ""))
    email = str(paypal_email or "").strip() or _generate_random_paypal_email()
    password = str(paypal_password or "").strip() or _generate_random_paypal_password()
    card_number = str(paypal_card_number or "").strip() or _first_payload_value(billing, "card_number", "cardNumber")
    card_expiry = str(paypal_card_expiry or "").strip() or _first_payload_value(
        billing,
        "card_expiry",
        "cardExpiry",
        "expiry",
        "expiry_date",
    )
    card_cvv = str(paypal_card_cvv or "").strip() or _first_payload_value(billing, "card_cvv", "cardCvv", "cvv", "cvc")
    return {
        "email": email,
        "password": password,
        "generated_email": not bool(str(paypal_email or "").strip()),
        "generated_password": not bool(str(paypal_password or "").strip()),
        "phone": _normalize_paypal_phone(str(billing.get("phone") or "")),
        "first_name": first_name,
        "last_name": last_name,
        "country": str(billing.get("country") or "US").strip() or "US",
        "state": str(billing.get("state") or "").strip(),
        "city": str(billing.get("city") or "").strip(),
        "zip": str(billing.get("zip") or "").strip(),
        "address1": str(billing.get("address1") or "").strip(),
        "address2": str(billing.get("address2") or "").strip(),
        "sms_url": str(sms_url or "").strip(),
        "otp_channel": str(otp_channel or "sms").strip().lower() or "sms",
        "card_number": re.sub(r"\D+", "", card_number),
        "card_expiry": _normalize_paypal_card_expiry(card_expiry),
        "card_cvv": re.sub(r"\D+", "", card_cvv),
    }


def _build_checkout_billing_payload(payload: dict | None) -> dict[str, str]:
    normalized = normalize_autofill_payload(payload)
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


def _merge_checkout_billing_payload(payload: dict | None) -> dict[str, str]:
    requested = _build_checkout_billing_payload(payload)
    generated_raw = _fetch_paypal_random_billing_profile()
    generated = _public_paypal_billing_info(generated_raw)
    merged = {
        "name": str(requested.get("name") or DEFAULT_PAYPAL_NAME).strip() or DEFAULT_PAYPAL_NAME,
        "email": str(requested.get("email") or "").strip(),
        "phone": str(requested.get("phone") or generated.get("phone_number") or "").strip(),
        "country": "US",
        "state": str(requested.get("state") or generated.get("state") or "").strip(),
        "city": str(requested.get("city") or generated.get("city") or "").strip(),
        "zip": str(requested.get("zip") or generated.get("zip") or "").strip(),
        "address1": str(requested.get("address1") or generated.get("address1") or "").strip(),
        "address2": str(requested.get("address2") or generated.get("address2") or "").strip(),
    }
    card_fields = {
        "card_number": _first_payload_value(requested, "card_number") or _first_payload_value(generated_raw, "card_number", "cardNumber"),
        "card_expiry": _first_payload_value(requested, "card_expiry") or _first_payload_value(
            generated_raw,
            "card_expiry",
            "cardExpiry",
            "expiry",
            "expiry_date",
        ),
        "card_cvv": _first_payload_value(requested, "card_cvv") or _first_payload_value(generated_raw, "card_cvv", "cardCvv", "cvv", "cvc"),
    }
    for key, value in card_fields.items():
        if value:
            merged[key] = str(value).strip()
    return merged


def _has_complete_billing_payload(payload: dict[str, str]) -> bool:
    required = ("name", "country", "state", "city", "zip", "address1")
    return all(str(payload.get(key) or "").strip() for key in required)


def _visible_locator_in_frames(api: ChatGPTTeamAPI, selectors: list[str], timeout_ms: int = 1000):
    return api._visible_locator_in_frames(selectors, timeout_ms=timeout_ms)


def _iter_page_frames(api: ChatGPTTeamAPI):
    try:
        page = getattr(api, "page", None)
        if not page:
            return []
        frames = []
        main_frame = getattr(page, "main_frame", None)
        if main_frame:
            frames.append(main_frame)
        for frame in list(getattr(page, "frames", []) or []):
            if frame not in frames:
                frames.append(frame)
        return frames
    except Exception:
        return []


def _attached_locator_in_frames(api: ChatGPTTeamAPI, selectors: list[str], timeout_ms: int = 500):
    for frame in _iter_page_frames(api):
        for selector in selectors:
            try:
                locator = frame.locator(selector).first
                locator.wait_for(state="attached", timeout=timeout_ms)
                return locator
            except Exception:
                continue
    return None


def _set_locator_value(locator, value: str) -> bool:
    try:
        tag_name = str(locator.evaluate("el => el.tagName") or "").lower()
    except Exception:
        tag_name = ""
    if tag_name == "select":
        for option in ({"value": value}, {"label": value}):
            try:
                locator.select_option(**option, timeout=1000)
                return True
            except Exception:
                continue
        return False
    try:
        locator.click(timeout=1200)
    except Exception:
        pass
    try:
        locator.fill(value, timeout=1500)
        return True
    except Exception:
        return False


def _type_locator_value(locator, value: str) -> bool:
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
        locator.type(str(value or ""), delay=25, timeout=6000)
        return True
    except Exception:
        return False


def _dispatch_locator_value(locator, value: str) -> bool:
    try:
        return bool(
            locator.evaluate(
                """(el, value) => {
                  el.focus();
                  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
                  const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
                  if (setter) setter.call(el, value);
                  else el.value = value;
                  el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: String(value || '') }));
                  el.dispatchEvent(new Event('change', { bubbles: true }));
                  el.dispatchEvent(new Event('blur', { bubbles: true }));
                  return true;
                }""",
                str(value or ""),
            )
        )
    except Exception:
        return False


def _read_locator_value(locator) -> str:
    try:
        return str(locator.input_value(timeout=800) or "").strip()
    except Exception:
        pass
    try:
        return str(locator.text_content(timeout=800) or "").strip()
    except Exception:
        return ""


def _value_matches(expected: str, actual: str) -> bool:
    expected_raw = str(expected or "").strip()
    actual_raw = str(actual or "").strip()
    if expected_raw == actual_raw:
        return True
    expected_norm = re.sub(r"\s+", " ", expected_raw).lower()
    actual_norm = re.sub(r"\s+", " ", actual_raw).lower()
    return bool(expected_norm) and expected_norm == actual_norm


def _card_value_matches(expected: str, actual: str, *, field: str) -> bool:
    expected_digits = re.sub(r"\D+", "", str(expected or ""))
    actual_digits = re.sub(r"\D+", "", str(actual or ""))
    if field in {"card_number", "card_cvv"}:
        return bool(expected_digits) and expected_digits == actual_digits
    if field == "card_expiry":
        return _normalize_paypal_card_expiry(expected) == _normalize_paypal_card_expiry(actual)
    return _value_matches(expected, actual)


def _field_value_matches(expected: str, actual: str, *, field: str = "") -> bool:
    if field in {"card_number", "card_expiry", "card_cvv"}:
        return _card_value_matches(expected, actual, field=field)
    if field == "phone":
        expected_digits = re.sub(r"\D+", "", str(expected or ""))
        actual_digits = re.sub(r"\D+", "", str(actual or ""))
        return bool(expected_digits) and expected_digits == actual_digits
    return _value_matches(expected, actual)


def _set_verified_locator_value(locator, value: str, *, field: str = "") -> bool:
    def matches() -> bool:
        actual = _read_locator_value(locator)
        return _field_value_matches(value, actual, field=field)

    for setter in (_set_locator_value, _type_locator_value, _dispatch_locator_value):
        if setter(locator, value):
            time.sleep(0.2)
            if matches():
                return True
    return False


def _body_excerpt(api: ChatGPTTeamAPI, limit: int = 2000):
    try:
        return api.page.locator("body").inner_text(timeout=1500)[:limit]
    except Exception:
        return ""


def _emit_progress(on_progress, event: dict):
    if callable(on_progress):
        on_progress(event)


def _progress_event(stage: str, message: str = "", **kwargs):
    payload = {
        "stage": stage,
        "message": message or PAYPAL_AUTO_STAGE_MESSAGES.get(stage) or stage,
    }
    payload.update(kwargs)
    return payload


def _progress_adapter(on_progress):
    def _adapter(stage: str, **kwargs):
        mapped_stage = stage if stage.startswith("paypal_") else f"paypal_{stage}"
        message = kwargs.pop("message", "") or PAYPAL_AUTO_STAGE_MESSAGES.get(mapped_stage) or PAYPAL_AUTO_STAGE_MESSAGES.get(stage) or mapped_stage
        _emit_progress(on_progress, _progress_event(mapped_stage, message, **kwargs))

    return _adapter


def _sync_relevant_payment_page(api: ChatGPTTeamAPI, *, prefer_paypal: bool = False):
    context = getattr(api, "context", None)
    if not context:
        return getattr(api, "page", None)
    pages = list(getattr(context, "pages", []) or [])
    if not pages:
        return getattr(api, "page", None)
    if prefer_paypal:
        for page in reversed(pages):
            if _is_paypal_host(getattr(page, "url", "")):
                api.page = page
                return page
    for page in reversed(pages):
        url = str(getattr(page, "url", "") or "")
        if _is_paypal_host(url) or _is_checkout_host(url):
            api.page = page
            return page
    api.page = pages[-1]
    return api.page


def _force_paypal_us_locale(api: ChatGPTTeamAPI) -> bool:
    current_url = str(getattr(api.page, "url", "") or "")
    if not _is_paypal_host(current_url):
        return False
    try:
        parsed = urlsplit(current_url)
    except Exception:
        return False
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    changed = False
    if query.get("country.x") != "US":
        query["country.x"] = "US"
        changed = True
    if query.get("locale.x") != "en_US":
        query["locale.x"] = "en_US"
        changed = True
    if not changed:
        return False
    next_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))
    try:
        api.page.goto(next_url, wait_until="domcontentloaded", timeout=60000)
        try:
            api.page.wait_for_timeout(1500)
        except Exception:
            time.sleep(1.5)
        return True
    except Exception as exc:
        logger.info("[paypal_bind_executor] forcing PayPal US locale failed: %s", exc)
        return False


def infer_paypal_stage(url: str, body_text: str):
    normalized_url = str(url or "").strip().lower()
    normalized_body = str(body_text or "").strip().lower()
    haystack = f"{normalized_url}\n{normalized_body}"

    if "paypal.com" in normalized_url:
        return "paypal_authorize", "已进入 PayPal 页面，等待人工完成登录/授权"
    if "pay.openai.com" in normalized_url or "checkout.stripe.com" in normalized_url:
        if "paypal" in haystack:
            return "paypal_option_ready", "已打开支付页，可人工切换到 PayPal 继续"
        return "checkout_opened", "已打开支付页，等待人工处理"
    if "chatgpt.com/checkout" in normalized_url:
        return "checkout_opened", "已打开 ChatGPT Checkout，等待人工处理"
    return "paypal_wait_manual", "等待人工完成 PayPal 支付流程"


def autofill_checkout_fields(api: ChatGPTTeamAPI, payload: dict | None, *, on_progress=None) -> dict:
    fields = normalize_autofill_payload(payload)
    current_url = getattr(api.page, "url", "")
    if not fields or not _autofill_allowed(current_url):
        return {"filled": [], "skipped": list(fields.keys())}

    filled: list[str] = []
    skipped: list[str] = []
    _suppress_address_autocomplete_ui(api)
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
    for key, value in ordered_fields:
        selectors = AUTOFILL_SELECTORS.get(key) or []
        if not selectors:
            skipped.append(key)
            continue
        locator = _visible_locator_in_frames(api, selectors, timeout_ms=1200)
        if locator and _set_locator_value(locator, value):
            filled.append(key)
            if key == "country":
                time.sleep(0.8)
            if key == "address1":
                address1_locator = locator
                _dismiss_address_autocomplete(api, locator)
        else:
            skipped.append(key)
    _dismiss_address_autocomplete(api, address1_locator)

    if filled:
        _emit_progress(
            on_progress,
            _progress_event(
                "paypal_autofill",
                f"已自动填写账单/联系字段: {', '.join(filled)}",
                autofill_fields=filled,
                url=current_url,
            ),
        )
    return {"filled": filled, "skipped": skipped}


def _read_checkout_field_value(api: ChatGPTTeamAPI, key: str) -> str:
    locator = _visible_locator_in_frames(api, AUTOFILL_SELECTORS.get(key) or [], timeout_ms=800)
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
        return _read_locator_value(locator)


def _checkout_value_matches(key: str, expected: str, actual: str) -> bool:
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
    return _value_matches(expected_text, actual_text)


def _fill_paypal_checkout_billing_form(
    api: ChatGPTTeamAPI,
    billing_payload: dict[str, str],
    session_id: str,
    screenshot_paths: list[str],
    *,
    on_progress=None,
) -> tuple[bool, str]:
    progress = _progress_adapter(on_progress)
    progress("fill_billing_info")
    required = {
        "country": str(billing_payload.get("country") or "US").strip() or "US",
        "address1": str(billing_payload.get("address1") or "").strip(),
        "city": str(billing_payload.get("city") or "").strip(),
        "state": str(billing_payload.get("state") or "").strip(),
        "postal_code": str(billing_payload.get("zip") or billing_payload.get("postal_code") or "").strip(),
    }
    if not all(required.values()):
        return False, "自动生成账单地址失败，缺少国家/地址/城市/州/邮编"

    last_values: dict[str, str] = {}
    for attempt in range(1, 9):
        _suppress_address_autocomplete_ui(api)
        autofill_checkout_fields(api, billing_payload, on_progress=on_progress)
        time.sleep(0.5)
        last_values = {key: _read_checkout_field_value(api, key) for key in required}
        missing = [
            key
            for key, expected in required.items()
            if not _checkout_value_matches(key, expected, last_values.get(key, ""))
        ]
        if not missing:
            return True, ""
        logger.info(
            "[paypal_bind_executor] PayPal checkout billing readback mismatch attempt=%s missing=%s values=%s expected=%s",
            attempt,
            missing,
            last_values,
            required,
        )
        time.sleep(0.8)

    _capture_screenshot(api, session_id, "paypal-billing-address-failed", screenshot_paths)
    return False, f"地址字段校验失败: 期望={required!r}, 实际={last_values!r}"


def _extract_auth_session_context(email: str) -> dict[str, str]:
    session = load_auth_session(email)
    account = session.get("account") if isinstance(session.get("account"), dict) else {}
    return {
        "session_token": str(session.get("sessionToken") or session.get("session_token") or "").strip(),
        "cookie_header": str(session.get("cookie_header") or "").strip(),
        "account_id": str(
            session.get("account_id")
            or session.get("accountId")
            or account.get("id")
            or account.get("account_id")
            or ""
        ).strip(),
        "device_id": str(
            session.get("device_id")
            or session.get("oai_device_id")
            or session.get("oaiDeviceId")
            or ""
        ).strip(),
    }


def _prepare_chatgpt_checkout_context(
    api: ChatGPTTeamAPI,
    *,
    email: str,
    checkout_url: str,
    session_context: dict[str, str],
    session_id: str,
    screenshot_paths: list[str],
    on_progress=None,
):
    has_session = bool(session_context.get("session_token") or session_context.get("cookie_header"))
    if has_session:
        _inject_chatgpt_browser_cookies(
            api,
            session_token=session_context.get("session_token", ""),
            cookie_header=session_context.get("cookie_header", ""),
            account_id=session_context.get("account_id", ""),
            device_id=session_context.get("device_id", ""),
        )
        _emit_progress(
            on_progress,
            _progress_event("paypal_session_ready", url="https://chatgpt.com/", email=email),
        )

    try:
        api.page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=60000)
        try:
            api.page.wait_for_timeout(2500)
        except Exception:
            time.sleep(2.5)
        api._wait_for_cloudflare()
        _select_chatgpt_account_if_needed(api, email=email)
    except Exception as exc:
        logger.info("[paypal_bind_executor] chatgpt warmup failed, continue to checkout directly: %s", exc)

    if not _open_checkout_in_page(api, checkout_url, email=email):
        _capture_screenshot(api, session_id, "paypal-open-checkout-failed", screenshot_paths)
        return _build_result(
            "failed",
            failure_stage="open_checkout",
            message="打开 PayPal checkout 页面失败: 未能稳定进入 checkout 页面",
            screenshot_paths=screenshot_paths,
        )

    api._wait_for_cloudflare()
    _capture_screenshot(api, session_id, "paypal-opened", screenshot_paths)
    _emit_progress(
        on_progress,
        _progress_event(
            "checkout_opened",
            "已打开 PayPal 相关支付页面",
            url=getattr(api.page, "url", ""),
        ),
    )
    return None


def _click_first(api: ChatGPTTeamAPI, selectors: list[str], *, timeout_ms: int = 2000) -> bool:
    locator = _visible_locator_in_frames(api, selectors, timeout_ms=timeout_ms)
    if not locator:
        return False
    try:
        locator.scroll_into_view_if_needed(timeout=1500)
    except Exception:
        pass
    try:
        locator.click(timeout=timeout_ms)
        return True
    except Exception:
        return False


def _locator_is_checked(locator) -> bool:
    try:
        return bool(locator.is_checked(timeout=500))
    except Exception:
        pass
    try:
        checked_attr = str(locator.get_attribute("checked", timeout=300) or "").strip().lower()
        if checked_attr in {"", "true", "checked"}:
            tag_name = str(locator.evaluate("el => el.tagName", timeout=300) or "").lower()
            if tag_name == "input":
                checked = locator.evaluate("el => Boolean(el.checked)", timeout=300)
                if checked is not None:
                    return bool(checked)
        return checked_attr in {"true", "checked"}
    except Exception:
        pass
    try:
        return str(locator.get_attribute("aria-checked", timeout=300) or "").strip().lower() == "true"
    except Exception:
        return False


def _is_paypal_option_selected(api: ChatGPTTeamAPI) -> bool:
    locator = _attached_locator_in_frames(api, PAYPAL_CHECKOUT_STATE_SELECTORS, timeout_ms=300)
    if locator and _locator_is_checked(locator):
        return True
    script = """() => {
      const radio = document.querySelector('#payment-method-accordion-item-title-paypal')
        || document.querySelector('input[type="radio"][id*="paypal" i]')
        || document.querySelector('input[type="radio"][name*="payment" i][value*="paypal" i]');
      if (radio) return Boolean(radio.checked);
      const roleRadio = document.querySelector('[role="radio"][aria-label*="paypal" i]');
      if (!roleRadio) return false;
      return String(roleRadio.getAttribute('aria-checked') || '').toLowerCase() === 'true';
    }"""
    try:
        return bool(api.page.evaluate(script))
    except Exception:
        return False


def _click_paypal_checkout_control(api: ChatGPTTeamAPI) -> bool:
    if _click_first(api, PAYPAL_CHECKOUT_SELECTORS, timeout_ms=2500):
        return True
    locator = _attached_locator_in_frames(api, PAYPAL_CHECKOUT_STATE_SELECTORS, timeout_ms=400)
    if locator:
        try:
            locator.scroll_into_view_if_needed(timeout=1200)
        except Exception:
            pass
        for clicker in (
            lambda: locator.check(timeout=1200, force=True),
            lambda: locator.click(timeout=1200, force=True),
            lambda: locator.evaluate(
                """(el) => {
                  el.click();
                  const wrapper = el.closest('label,button,div,[role="radio"],[role="button"]');
                  if (wrapper && wrapper !== el) wrapper.click();
                  return Boolean(el.checked) || String(wrapper?.getAttribute?.('aria-checked') || '').toLowerCase() === 'true';
                }""",
                timeout=1200,
            ),
        ):
            try:
                clicker()
                return True
            except Exception:
                continue
    script = """() => {
      const radio = document.querySelector('#payment-method-accordion-item-title-paypal')
        || document.querySelector('input[type="radio"][id*="paypal" i]')
        || document.querySelector('input[type="radio"][name*="payment" i][value*="paypal" i]');
      const button = document.querySelector('[data-testid="paypal-accordion-item-button"]')
        || radio?.closest('label,button,div,[role="radio"],[role="button"]');
      if (button) button.click();
      if (radio && !radio.checked) radio.click();
      return Boolean(radio?.checked)
        || String(button?.getAttribute?.('aria-checked') || '').toLowerCase() === 'true';
    }"""
    try:
        return bool(api.page.evaluate(script))
    except Exception:
        return False


def _select_paypal_option(api: ChatGPTTeamAPI, *, on_progress=None) -> bool:
    if _is_paypal_host(getattr(api.page, "url", "")):
        return True
    if _is_paypal_option_selected(api):
        _emit_progress(on_progress, _progress_event("paypal_option_selected", url=getattr(api.page, "url", "")))
        return True
    for _ in range(3):
        clicked = _click_paypal_checkout_control(api)
        time.sleep(0.8)
        if _is_paypal_host(getattr(api.page, "url", "")) or _is_paypal_option_selected(api):
            _emit_progress(on_progress, _progress_event("paypal_option_selected", url=getattr(api.page, "url", "")))
            return True
        if not clicked:
            time.sleep(0.4)
    return False


def _submit_checkout_to_paypal(
    api: ChatGPTTeamAPI,
    *,
    email: str,
    session_id: str,
    screenshot_paths: list[str],
    timeout_seconds: int,
    is_cancelled=None,
    on_progress=None,
):
    _emit_progress(on_progress, _progress_event("paypal_submit_checkout", url=getattr(api.page, "url", "")))
    deadline = time.time() + max(15, timeout_seconds)
    attempts = 0
    while time.time() < deadline:
        _sync_relevant_payment_page(api, prefer_paypal=True)
        current_url = getattr(api.page, "url", "")
        if _is_paypal_host(current_url):
            if _force_paypal_us_locale(api):
                current_url = getattr(api.page, "url", "")
            _emit_progress(on_progress, _progress_event("paypal_authorize", url=current_url))
            return None

        body_text = _body_excerpt(api)
        classified = classify_paypal_checkout_state(current_url, body_text)
        if classified and classified.get("status") != "needs_review":
            _capture_screenshot(api, session_id, classified["status"], screenshot_paths)
            classified["screenshot_paths"] = screenshot_paths
            return classified

        checkout_error = _extract_checkout_error(api)
        if checkout_error:
            _capture_screenshot(api, session_id, "paypal-checkout-submit-error", screenshot_paths)
            return _build_result(
                "failed",
                failure_stage="submit_checkout",
                message=f"Checkout 提交失败: {checkout_error}",
                screenshot_paths=screenshot_paths,
            )

        if callable(is_cancelled) and is_cancelled():
            _capture_screenshot(api, session_id, "paypal-cancelled", screenshot_paths)
            return _build_result("failed", failure_stage="submit_checkout", message="任务已取消", screenshot_paths=screenshot_paths)

        attempts += 1
        if _click_first(api, CHECKOUT_SUBMIT_SELECTORS, timeout_ms=5000):
            _emit_progress(
                on_progress,
                _progress_event("paypal_wait_redirect", attempt=attempts, url=current_url),
            )
            time.sleep(2.0)
            _select_chatgpt_account_if_needed(api, email=email)
        else:
            time.sleep(1.0)

    _capture_screenshot(api, session_id, "paypal-submit-timeout", screenshot_paths)
    return _build_result(
        "failed",
        failure_stage="submit_checkout",
        message="提交订阅后未跳转到 PayPal 授权页",
        screenshot_paths=screenshot_paths,
    )


def _inspect_paypal_page(api: ChatGPTTeamAPI) -> dict[str, Any]:
    current_url = getattr(api.page, "url", "")
    body_text = _body_excerpt(api, 2500)
    body_lower = body_text.lower()
    is_paypal_page = _is_paypal_host(current_url)

    email_locator = _visible_locator_in_frames(api, PAYPAL_EMAIL_SELECTORS, timeout_ms=400)
    password_locator = _visible_locator_in_frames(api, PAYPAL_PASSWORD_SELECTORS, timeout_ms=400)
    approve_locator = _visible_locator_in_frames(api, PAYPAL_APPROVE_SELECTORS, timeout_ms=400)
    prompt_locator = _visible_locator_in_frames(api, PAYPAL_DISMISS_PROMPT_SELECTORS, timeout_ms=400)
    create_account_locator = _visible_locator_in_frames(api, PAYPAL_CREATE_ACCOUNT_SELECTORS, timeout_ms=400)
    phone_locator = _visible_locator_in_frames(api, PAYPAL_PHONE_SELECTORS, timeout_ms=400)
    card_locator = _visible_locator_in_frames(api, PAYPAL_CARD_NUMBER_SELECTORS, timeout_ms=400)

    login_phase = ""
    if email_locator and password_locator:
        login_phase = "login_combined"
    elif email_locator:
        login_phase = "email"
    elif password_locator:
        login_phase = "password"

    needs_login = is_paypal_page and (bool(email_locator or password_locator) or any(
        hint in body_lower
        for hint in (
            "log in",
            "login",
            "sign in",
            "welcome back",
            "password",
            "邮箱",
            "登录",
        )
    ))
    has_passkey_prompt = is_paypal_page and (bool(prompt_locator) or any(
        hint in body_lower
        for hint in (
            "passkey",
            "security key",
            "try another way",
            "use password instead",
            "通行密钥",
            "改用密码",
        )
    ))
    approve_ready = is_paypal_page and (bool(approve_locator) or any(
        hint in body_lower
        for hint in (
            "agree and continue",
            "authorize",
            "consent",
            "accept",
            "同意并继续",
            "授权",
        )
    ))
    registration_ready = is_paypal_page and (bool(card_locator or phone_locator) or "/checkoutweb/" in current_url.lower())
    needs_otp = is_paypal_page and any(
        hint in body_lower
        for hint in (
            "enter the code",
            "enter code",
            "6-digit code",
            "verification code",
            "security code",
            "验证码",
        )
    )
    return {
        "url": current_url,
        "body_text": body_text,
        "needs_login": needs_login,
        "login_phase": login_phase,
        "has_passkey_prompt": has_passkey_prompt,
        "approve_ready": approve_ready,
        "create_account_ready": bool(create_account_locator),
        "registration_ready": registration_ready,
        "needs_otp": needs_otp,
        "email_locator": email_locator,
        "password_locator": password_locator,
    }


def _dismiss_paypal_prompts(api: ChatGPTTeamAPI, *, on_progress=None) -> bool:
    if _click_first(api, PAYPAL_DISMISS_PROMPT_SELECTORS, timeout_ms=1500):
        _emit_progress(
            on_progress,
            _progress_event("paypal_prompt_dismissed", url=getattr(api.page, "url", "")),
        )
        return True
    return False


def _set_first_visible_value(api: ChatGPTTeamAPI, selectors: list[str], value: str) -> bool:
    locator = _visible_locator_in_frames(api, selectors, timeout_ms=1200)
    if not locator:
        return False
    return _set_locator_value(locator, value)


def _set_first_visible_value_with_locator(api: ChatGPTTeamAPI, selectors: list[str], value: str):
    locator = _visible_locator_in_frames(api, selectors, timeout_ms=1200)
    if not locator:
        return False, None
    return _set_locator_value(locator, value), locator


def _set_paypal_country(api: ChatGPTTeamAPI, country: str) -> bool:
    locator = _visible_locator_in_frames(api, PAYPAL_COUNTRY_SELECTORS, timeout_ms=1200)
    if not locator:
        return False
    for option in ("US", country, "United States", "United States of America"):
        if not option:
            continue
        try:
            locator.select_option(value=option, timeout=1200)
            time.sleep(1.0)
            return True
        except Exception:
            pass
        try:
            locator.select_option(label=option, timeout=1200)
            time.sleep(1.0)
            return True
        except Exception:
            pass
    return False


def _fill_paypal_signup_form(
    api: ChatGPTTeamAPI,
    *,
    signup_profile: dict[str, str | bool],
    on_progress=None,
) -> tuple[bool, str]:
    _emit_progress(on_progress, _progress_event("paypal_fill_signup", url=getattr(api.page, "url", "")))
    _set_paypal_country(api, str(signup_profile.get("country") or "US"))
    required_fields = [
        ("email", PAYPAL_EMAIL_SELECTORS, str(signup_profile.get("email") or ""), "PayPal 注册邮箱"),
        ("phone", PAYPAL_PHONE_SELECTORS, str(signup_profile.get("phone") or ""), "PayPal 注册手机号"),
        ("card_number", PAYPAL_CARD_NUMBER_SELECTORS, str(signup_profile.get("card_number") or ""), "PayPal 卡号"),
        ("card_expiry", PAYPAL_CARD_EXPIRY_SELECTORS, str(signup_profile.get("card_expiry") or ""), "PayPal 卡有效期"),
        ("card_cvv", PAYPAL_CARD_CVV_SELECTORS, str(signup_profile.get("card_cvv") or ""), "PayPal 卡 CVV"),
        ("password", PAYPAL_PASSWORD_SELECTORS, str(signup_profile.get("password") or ""), "PayPal 注册密码"),
        ("first_name", PAYPAL_FIRST_NAME_SELECTORS, str(signup_profile.get("first_name") or ""), "PayPal 名"),
        ("last_name", PAYPAL_LAST_NAME_SELECTORS, str(signup_profile.get("last_name") or ""), "PayPal 姓"),
    ]
    field_locators: dict[str, Any] = {}
    for key, selectors, value, label in required_fields:
        if not value:
            return False, f"{label} 为空"
        ok, locator = _set_first_visible_value_with_locator(api, selectors, value)
        if not ok:
            return False, f"未找到 {label} 输入框"
        if locator is not None and not _set_verified_locator_value(locator, value, field=key):
            actual = _read_locator_value(locator)
            return False, f"{label} 填写后校验失败: 期望={value!r}, 实际={actual!r}"
        if locator is not None:
            field_locators[label] = locator

    _suppress_address_autocomplete_ui(api)
    address_fields = [
        ("address1", PAYPAL_BILLING_LINE1_SELECTORS, str(signup_profile.get("address1") or ""), "PayPal 账单地址"),
        ("city", PAYPAL_BILLING_CITY_SELECTORS, str(signup_profile.get("city") or ""), "PayPal 城市"),
        ("zip", PAYPAL_BILLING_POSTAL_SELECTORS, str(signup_profile.get("zip") or ""), "PayPal 邮编"),
        ("state", PAYPAL_BILLING_STATE_SELECTORS, str(signup_profile.get("state") or ""), "PayPal 州"),
    ]
    for key, selectors, value, label in address_fields:
        if not value:
            return False, f"{label} 为空"
        ok, locator = _set_first_visible_value_with_locator(api, selectors, value)
        if not ok or locator is None:
            return False, f"未找到 {label} 输入框"
        field_locators[key] = locator
        if key == "address1":
            _dismiss_address_autocomplete(api, locator)
            time.sleep(0.3)

    _dismiss_address_autocomplete(api, field_locators.get("address1"))
    for key, selectors, expected, label in address_fields:
        locator = field_locators.get(key)
        actual = _read_locator_value(locator)
        if _value_matches(expected, actual):
            continue
        if not _set_locator_value(locator, expected):
            return False, f"{label} 自动补全后被改写，且重写失败"
        if key == "address1":
            _dismiss_address_autocomplete(api, locator)
        time.sleep(0.3)
        actual = _read_locator_value(locator)
        if not _value_matches(expected, actual):
            return False, f"{label} 自动补全后校验失败: 期望={expected!r}, 实际={actual!r}"
    return True, ""


def _fill_paypal_otp_inputs(api: ChatGPTTeamAPI, otp_code: str) -> bool:
    digits = re.sub(r"\D+", "", str(otp_code or ""))[:8]
    if len(digits) < 5:
        return False
    script = """(code) => {
      const digits = String(code || '').replace(/\\D+/g, '').slice(0, 8).split('');
      if (digits.length < 5) return false;
      const candidates = Array.from(document.querySelectorAll('input')).filter((node) => {
        const type = String(node.type || '').toLowerCase();
        const mode = String(node.inputMode || '').toLowerCase();
        const auto = String(node.autocomplete || '').toLowerCase();
        const name = String(node.name || '').toLowerCase();
        const id = String(node.id || '').toLowerCase();
        const maxLength = Number(node.maxLength || 0);
        return (
          auto === 'one-time-code' ||
          mode === 'numeric' ||
          (type === 'tel' && maxLength === 1) ||
          (maxLength === 1 && (name.includes('code') || id.includes('code')))
        );
      });
      if (candidates.length >= digits.length) {
        candidates.slice(0, digits.length).forEach((node, index) => {
          node.focus();
          node.value = digits[index];
          node.dispatchEvent(new Event('input', { bubbles: true }));
          node.dispatchEvent(new Event('change', { bubbles: true }));
          node.dispatchEvent(new Event('blur', { bubbles: true }));
        });
        return true;
      }
      const single = candidates[0] || document.querySelector('input[autocomplete=\"one-time-code\"]');
      if (!single) return false;
      single.focus();
      single.value = digits.join('');
      single.dispatchEvent(new Event('input', { bubbles: true }));
      single.dispatchEvent(new Event('change', { bubbles: true }));
      single.dispatchEvent(new Event('blur', { bubbles: true }));
      return true;
    }"""
    try:
        return bool(api.page.evaluate(script, digits))
    except Exception:
        return False


def _click_paypal_create_account(api: ChatGPTTeamAPI, *, on_progress=None) -> bool:
    if _click_first(api, PAYPAL_CREATE_ACCOUNT_SELECTORS, timeout_ms=2000):
        _emit_progress(on_progress, _progress_event("paypal_create_account", url=getattr(api.page, "url", "")))
        return True
    return False


def _poll_paypal_signup_otp(
    *,
    signup_profile: dict[str, str | bool],
    timeout_seconds: int,
    is_cancelled=None,
    on_progress=None,
) -> str:
    sms_url = str(signup_profile.get("sms_url") or "").strip()
    _emit_progress(
        on_progress,
        _progress_event(
            "paypal_wait_signup_otp",
            sms_url=_safe_url_summary(sms_url) if sms_url else "",
            otp_channel=str(signup_profile.get("otp_channel") or "sms"),
        ),
    )
    provider = _poll_otp_from_sms_url(
        sms_url,
        timeout_seconds=max(60, timeout_seconds),
        initial_delay_seconds=8,
        resend_after_seconds=60,
        max_resend_attempts=2,
        is_cancelled=is_cancelled,
        progress=_progress_adapter(on_progress),
    )
    otp = str(provider() or "").strip()
    if otp:
        _emit_progress(on_progress, _progress_event("paypal_otp_received", otp="******"))
    return otp


def _submit_paypal_login_step(
    api: ChatGPTTeamAPI,
    *,
    credentials: dict[str, str],
    state: dict[str, Any],
    on_progress=None,
):
    email = credentials.get("email", "")
    password = credentials.get("password", "")
    phase = str(state.get("login_phase") or "")
    email_locator = state.get("email_locator")
    password_locator = state.get("password_locator")

    if phase in {"email", "login_combined"} and email_locator:
        if not email:
            return False, "自动 PayPal 模式缺少 paypal_email"
        try:
            current = str(email_locator.input_value(timeout=800) or "").strip()
        except Exception:
            current = ""
        if current.lower() != email.lower() and not _set_locator_value(email_locator, email):
            return False, "填写 PayPal 邮箱失败"
        _emit_progress(on_progress, _progress_event("paypal_login_email", url=getattr(api.page, "url", "")))

    if phase in {"password", "login_combined"} and password_locator:
        if not password:
            return False, "自动 PayPal 模式缺少 paypal_password"
        if not _set_locator_value(password_locator, password):
            return False, "填写 PayPal 密码失败"
        _emit_progress(on_progress, _progress_event("paypal_login_password", url=getattr(api.page, "url", "")))

    if not _click_first(api, PAYPAL_NEXT_SELECTORS, timeout_ms=2500):
        try:
            if password_locator:
                password_locator.press("Enter", timeout=1200)
            elif email_locator:
                email_locator.press("Enter", timeout=1200)
            else:
                return False, "未找到 PayPal 登录提交按钮"
        except Exception:
            return False, "未找到 PayPal 登录提交按钮"

    time.sleep(2.0)
    return True, ""


def _click_paypal_approve(api: ChatGPTTeamAPI, *, on_progress=None) -> bool:
    if _click_first(api, PAYPAL_APPROVE_SELECTORS, timeout_ms=2500):
        _emit_progress(
            on_progress,
            _progress_event("paypal_approve_clicked", url=getattr(api.page, "url", "")),
        )
        return True
    return False


def _run_paypal_signup_flow(
    api: ChatGPTTeamAPI,
    *,
    signup_profile: dict[str, str | bool],
    state: dict[str, Any],
    on_progress=None,
    is_cancelled=None,
) -> tuple[bool, str, bool]:
    current_url = getattr(api.page, "url", "")
    body_text = str(state.get("body_text") or "").lower()

    if state.get("create_account_ready") and _click_paypal_create_account(api, on_progress=on_progress):
        time.sleep(2.0)
        return True, "", True

    if state.get("registration_ready"):
        ok, error = _fill_paypal_signup_form(api, signup_profile=signup_profile, on_progress=on_progress)
        if not ok:
            return False, error, True
        _emit_progress(on_progress, _progress_event("paypal_submit_signup", url=current_url))
        if not _click_first(api, PAYPAL_CREATE_SUBMIT_SELECTORS, timeout_ms=2500):
            return False, "未找到 PayPal 注册提交按钮", False
        time.sleep(2.0)
        return True, "", True

    if state.get("needs_otp") or "code was sent" in body_text or "check your phone" in body_text:
        otp = _poll_paypal_signup_otp(
            signup_profile=signup_profile,
            timeout_seconds=180,
            is_cancelled=is_cancelled,
            on_progress=on_progress,
        )
        if not _fill_paypal_otp_inputs(api, otp):
            return False, "未找到 PayPal 验证码输入框", False
        _emit_progress(on_progress, _progress_event("paypal_submit_otp", url=current_url))
        if not _click_first(api, PAYPAL_NEXT_SELECTORS, timeout_ms=2500):
            try:
                api.page.keyboard.press("Enter")
            except Exception:
                return False, "未找到 PayPal 验证码提交按钮", False
        time.sleep(2.0)
        return True, "", True

    return True, "", False


def _run_paypal_authorize_flow(
    api: ChatGPTTeamAPI,
    *,
    paypal_mode: str,
    credentials: dict[str, str],
    signup_profile: dict[str, str | bool] | None,
    session_id: str,
    screenshot_paths: list[str],
    timeout_seconds: int,
    is_cancelled=None,
    on_progress=None,
):
    deadline = time.time() + max(20, timeout_seconds)
    effective_credentials = dict(credentials or {})
    if paypal_mode == "create_account" and signup_profile:
        effective_credentials = {
            "email": str(signup_profile.get("email") or ""),
            "password": str(signup_profile.get("password") or ""),
        }
    while time.time() < deadline:
        _sync_relevant_payment_page(api, prefer_paypal=True)
        _force_paypal_us_locale(api)
        current_url = getattr(api.page, "url", "")
        if current_url and not _is_paypal_host(current_url):
            _emit_progress(on_progress, _progress_event("paypal_wait_result", url=current_url))
            return None

        if callable(is_cancelled) and is_cancelled():
            _capture_screenshot(api, session_id, "paypal-cancelled", screenshot_paths)
            return _build_result("failed", failure_stage="post_submit", message="任务已取消", screenshot_paths=screenshot_paths)

        state = _inspect_paypal_page(api)
        classified = classify_paypal_checkout_state(current_url, state.get("body_text", ""))
        if classified and classified.get("status") == "failed":
            _capture_screenshot(api, session_id, "paypal-authorize-failed", screenshot_paths)
            classified["screenshot_paths"] = screenshot_paths
            return classified

        if state.get("has_passkey_prompt") and _dismiss_paypal_prompts(api, on_progress=on_progress):
            time.sleep(1.2)
            continue

        if paypal_mode == "create_account":
            ok, error, handled = _run_paypal_signup_flow(
                api,
                signup_profile=dict(signup_profile or {}),
                state=state,
                on_progress=on_progress,
                is_cancelled=is_cancelled,
            )
            if not ok:
                _capture_screenshot(api, session_id, "paypal-signup-failed", screenshot_paths)
                return _build_result(
                    "failed",
                    failure_stage="paypal_signup",
                    message=error,
                    screenshot_paths=screenshot_paths,
                )
            if handled:
                continue

        if state.get("needs_login"):
            ok, error = _submit_paypal_login_step(
                api,
                credentials=effective_credentials,
                state=state,
                on_progress=on_progress,
            )
            if not ok:
                _capture_screenshot(api, session_id, "paypal-login-failed", screenshot_paths)
                return _build_result("failed", failure_stage="paypal_login", message=error, screenshot_paths=screenshot_paths)
            continue

        if state.get("approve_ready") and _click_paypal_approve(api, on_progress=on_progress):
            time.sleep(2.0)
            continue

        time.sleep(1.0)

    _capture_screenshot(api, session_id, "paypal-authorize-timeout", screenshot_paths)
    return _build_result(
        "needs_review",
        failure_stage="paypal_authorize",
        message="等待 PayPal 登录/授权超时，需要人工确认",
        screenshot_paths=screenshot_paths,
    )


def _wait_for_paypal_result(
    api: ChatGPTTeamAPI,
    *,
    session_id: str,
    screenshot_paths: list[str],
    timeout_seconds: int,
    is_cancelled=None,
    on_progress=None,
    autofill_enabled: bool = False,
    autofill_payload: dict | None = None,
):
    deadline = time.time() + max(10, timeout_seconds)
    last_stage = ""
    last_log_at = 0.0
    autofilled_urls: set[str] = set()

    while time.time() < deadline:
        _sync_relevant_payment_page(api, prefer_paypal=True)
        now = time.time()
        if now - last_log_at >= 60:
            remaining = max(0, int(deadline - now))
            logger.info(
                "[paypal_bind_executor] 等待 PayPal 流程结果，剩余约 %ss，当前 URL=%s",
                remaining,
                getattr(api.page, "url", ""),
            )
            last_log_at = now

        if callable(is_cancelled) and is_cancelled():
            _capture_screenshot(api, session_id, "paypal-cancelled", screenshot_paths)
            return _build_result("failed", failure_stage="post_submit", message="任务已取消", screenshot_paths=screenshot_paths)

        body_text = _body_excerpt(api)
        current_url = getattr(api.page, "url", "")
        if autofill_enabled and current_url not in autofilled_urls:
            autofill_checkout_fields(api, autofill_payload, on_progress=on_progress)
            autofilled_urls.add(current_url)
        stage, message = infer_paypal_stage(current_url, body_text)
        if stage != last_stage:
            _emit_progress(
                on_progress,
                _progress_event(stage, message, url=current_url),
            )
            last_stage = stage

        classified = classify_paypal_checkout_state(current_url, body_text)
        if classified:
            _capture_screenshot(api, session_id, classified["status"], screenshot_paths)
            classified["screenshot_paths"] = screenshot_paths
            return classified

        time.sleep(3)

    _capture_screenshot(api, session_id, "paypal-timeout", screenshot_paths)
    return _build_result(
        "needs_review",
        failure_stage="post_submit",
        message="等待 PayPal 支付结果超时，需要人工确认最终状态",
        screenshot_paths=screenshot_paths,
    )


def _run_paypal_auto_flow(
    api: ChatGPTTeamAPI,
    *,
    email: str,
    paypal_mode: str,
    paypal_credentials: dict[str, str],
    signup_profile: dict[str, str | bool] | None,
    session_id: str,
    screenshot_paths: list[str],
    timeout_seconds: int,
    is_cancelled=None,
    on_progress=None,
    autofill_enabled: bool = False,
    autofill_payload: dict | None = None,
):
    current_url = getattr(api.page, "url", "")
    billing_payload = _merge_checkout_billing_payload(autofill_payload)
    progress = _progress_adapter(on_progress)

    if _is_checkout_host(current_url):
        if not _select_paypal_option(api, on_progress=on_progress):
            _capture_screenshot(api, session_id, "paypal-option-not-found", screenshot_paths)
            return _build_result(
                "failed",
                failure_stage="select_paypal",
                message="未找到 PayPal 支付方式按钮",
                screenshot_paths=screenshot_paths,
            )
        if autofill_enabled and _autofill_allowed(getattr(api.page, "url", "")):
            if not _has_complete_billing_payload(billing_payload):
                _capture_screenshot(api, session_id, "paypal-billing-address-incomplete", screenshot_paths)
                return _build_result(
                    "failed",
                    failure_stage="fill_billing_info",
                    message="自动生成账单地址失败，缺少必要字段",
                    screenshot_paths=screenshot_paths,
                )
            _emit_progress(
                on_progress,
                _progress_event(
                    "paypal_billing_fill_started",
                    url=getattr(api.page, "url", ""),
                    billing_info=billing_payload,
                ),
            )
            ok, error = _fill_paypal_checkout_billing_form(
                api,
                billing_payload,
                session_id,
                screenshot_paths,
                on_progress=on_progress,
            )
            if not ok:
                return _build_result(
                    "failed",
                    failure_stage="fill_billing_info",
                    message=f"自动填写 checkout 账单地址失败: {error}",
                    screenshot_paths=screenshot_paths,
                )
            autofill_checkout_fields(api, billing_payload, on_progress=on_progress)
            _emit_progress(
                on_progress,
                _progress_event("paypal_billing_fill_done", url=getattr(api.page, "url", "")),
            )
        _accept_checkout_terms_on_page(api, progress=progress)
        handoff_result = _submit_checkout_to_paypal(
            api,
            email=email,
            session_id=session_id,
            screenshot_paths=screenshot_paths,
            timeout_seconds=min(timeout_seconds, 90),
            is_cancelled=is_cancelled,
            on_progress=on_progress,
        )
        if handoff_result:
            return handoff_result

    authorize_result = _run_paypal_authorize_flow(
        api,
        paypal_mode=paypal_mode,
        credentials=paypal_credentials,
        signup_profile=signup_profile,
        session_id=session_id,
        screenshot_paths=screenshot_paths,
        timeout_seconds=min(timeout_seconds, 240),
        is_cancelled=is_cancelled,
        on_progress=on_progress,
    )
    if authorize_result:
        return authorize_result

    return _wait_for_paypal_result(
        api,
        session_id=session_id,
        screenshot_paths=screenshot_paths,
        timeout_seconds=timeout_seconds,
        is_cancelled=is_cancelled,
        on_progress=on_progress,
        autofill_enabled=autofill_enabled,
        autofill_payload=autofill_payload,
    )


def run_paypal_bind_task(
    *,
    email: str = "",
    checkout_url: str,
    proxy_url: str | None = None,
    proxy_bypass: str | None = None,
    manual_confirm: bool = True,
    timeout_seconds: int = 900,
    is_cancelled=None,
    on_progress=None,
    autofill_enabled: bool = False,
    autofill_payload: dict | None = None,
    paypal_mode: str = "existing_account",
    paypal_email: str = "",
    paypal_password: str = "",
    sms_url: str = "",
    otp_channel: str = "sms",
    paypal_card_number: str = "",
    paypal_card_expiry: str = "",
    paypal_card_cvv: str = "",
):
    api = ChatGPTTeamAPI()
    session_id = uuid.uuid4().hex[:12]
    screenshot_paths: list[str] = []
    auto_mode = not bool(manual_confirm)
    paypal_mode = _normalize_paypal_mode(paypal_mode)

    try:
        api._launch_browser(
            proxy_url=proxy_url,
            proxy_bypass=proxy_bypass,
            background=False,
            locale="en-US",
            accept_language="en-US,en;q=0.9",
        )

        if callable(is_cancelled) and is_cancelled():
            return _build_result("failed", failure_stage="open_checkout", message="任务已取消")

        prepare_result = _prepare_chatgpt_checkout_context(
            api,
            email=str(email or "").strip(),
            checkout_url=checkout_url,
            session_context=_extract_auth_session_context(str(email or "").strip()) if email else {},
            session_id=session_id,
            screenshot_paths=screenshot_paths,
            on_progress=on_progress,
        )
        if prepare_result:
            return prepare_result

        if auto_mode:
            billing_payload = _merge_checkout_billing_payload(autofill_payload)
            return _run_paypal_auto_flow(
                api,
                email=str(email or "").strip(),
                paypal_mode=paypal_mode,
                paypal_credentials=_normalize_paypal_credentials(paypal_email, paypal_password),
                signup_profile=_build_paypal_signup_profile(
                    paypal_email=paypal_email,
                    paypal_password=paypal_password,
                    billing_payload=billing_payload,
                    sms_url=sms_url,
                    otp_channel=otp_channel,
                    paypal_card_number=paypal_card_number,
                    paypal_card_expiry=paypal_card_expiry,
                    paypal_card_cvv=paypal_card_cvv,
                ),
                session_id=session_id,
                screenshot_paths=screenshot_paths,
                timeout_seconds=timeout_seconds,
                is_cancelled=is_cancelled,
                on_progress=on_progress,
                autofill_enabled=autofill_enabled,
                autofill_payload=autofill_payload,
            )

        if autofill_enabled:
            autofill_checkout_fields(api, autofill_payload, on_progress=on_progress)

        return _wait_for_paypal_result(
            api,
            session_id=session_id,
            screenshot_paths=screenshot_paths,
            timeout_seconds=timeout_seconds,
            is_cancelled=is_cancelled,
            on_progress=on_progress,
            autofill_enabled=autofill_enabled,
            autofill_payload=autofill_payload,
        )
    except Exception as exc:
        logger.exception("[paypal_bind_executor] unexpected error")
        _capture_screenshot(api, session_id, "paypal-unexpected-error", screenshot_paths)
        return _build_result(
            "failed",
            failure_stage="post_submit",
            message=f"执行 PayPal 任务时出现异常: {exc}",
            screenshot_paths=screenshot_paths,
        )
    finally:
        try:
            api.stop()
        except Exception:
            pass
